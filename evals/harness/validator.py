"""Comprehensive validator for Phase 4 canonical evaluation bundles.

Normative reference:
- docs/phase4/PHASE_4_RESULTS_SCHEMA.md
- docs/phase4/PHASE_4_FAILURE_TAXONOMY.md
- docs/phase4/PHASE_4_METRICS_DEFINITION.md
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import json

from evals.harness.constants import (
    CANONICAL_ARTIFACT_FILES,
    FROZEN_BENCHMARK_LF_SHA256,
    SYSTEM_BASELINE_COMMIT_SHA,
)
from evals.harness.schema import (
    SchemaValidationError,
    validate_aggregate,
    validate_attempt_record,
    validate_error_record,
    validate_grading_record,
    validate_manifest,
    validate_retrieval_record,
)
from evals.harness.writer import compute_sha256


@dataclass
class ValidationReport:
    """Detailed validation report of an evaluation run directory."""
    run_id: str
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    attempt_count: int = 0
    logical_case_count: int = 0
    grading_count: int = 0
    retrieval_count: int = 0
    error_count: int = 0
    recomputed_aggregate: Optional[Dict[str, Any]] = None


def recompute_aggregate_from_raw(
    manifest: Dict[str, Any],
    attempts: List[Dict[str, Any]],
    gradings: List[Dict[str, Any]],
    errors: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Deterministically recomputes summary metrics directly from raw artifacts per logical case."""
    run_id = manifest.get("run_id", "")
    all_case_ids: Set[str] = {a["case_id"] for a in attempts}
    n_total = len(all_case_ids)
    n_attempt = len(attempts)

    # Attempts grouped by case_id
    attempts_by_case = defaultdict(list)
    for a in attempts:
        attempts_by_case[a["case_id"]].append(a)

    # First attempt outcomes (retry_index == 0)
    first_attempts = [a for a in attempts if a.get("retry_index") == 0]
    first_outcomes = Counter(a.get("outcome") for a in first_attempts)

    # Gradings indexed by attempt_id
    gradings_by_attempt = {g["graded_attempt_id"]: g for g in gradings}
    graded_cases: Set[str] = {g["case_id"] for g in gradings}
    n_graded = len(graded_cases)

    blocked_cases: Set[str] = {g["case_id"] for g in gradings if g.get("decision") == "blocked_environment"}
    n_blocked = len(blocked_cases)

    # Quality conditional on first attempts: pass + abstain_correct / n_graded_first
    first_attempt_ids = {a["attempt_id"] for a in first_attempts}
    first_gradings = [g for g in gradings if g.get("graded_attempt_id") in first_attempt_ids and g.get("first_attempt") is True]
    n_graded_first = len(first_gradings)
    first_passes = sum(1 for g in first_gradings if g.get("decision") in ("pass", "abstain_correct"))

    quality_cond_rate = (first_passes / n_graded_first) if n_graded_first > 0 else 0.0
    quality_conditional = {
        "numerator": first_passes,
        "denominator": n_graded_first,
        "rate": round(quality_cond_rate, 4),
    }

    # Eventual outcomes and passes computed strictly per logical case (latest attempt per case_id)
    eventual_outcomes = Counter()
    eventual_passes = 0
    for cid, atts in attempts_by_case.items():
        latest = max(atts, key=lambda x: x.get("retry_index", 0))
        eventual_outcomes[latest.get("outcome")] += 1
        latest_g = gradings_by_attempt.get(latest.get("attempt_id"))
        if latest_g and latest_g.get("decision") in ("pass", "abstain_correct"):
            eventual_passes += 1

    # E2E success: cases where eventual outcome is 'completed'
    eventual_completed = eventual_outcomes.get("completed", 0)
    e2e_rate = (eventual_completed / n_total) if n_total > 0 else 0.0
    e2e_success = {
        "numerator": eventual_completed,
        "denominator": n_total,
        "rate": round(e2e_rate, 4),
    }

    # Retry recovery rate: of cases that failed first attempt, how many eventually passed?
    first_pass_cids = {g["case_id"] for g in first_gradings if g.get("decision") in ("pass", "abstain_correct")}
    failed_first_cases = [cid for cid in all_case_ids if cid not in first_pass_cids]
    if failed_first_cases:
        recovered = 0
        for cid in failed_first_cases:
            latest = max(attempts_by_case[cid], key=lambda x: x.get("retry_index", 0))
            latest_g = gradings_by_attempt.get(latest.get("attempt_id"))
            if latest_g and latest_g.get("decision") in ("pass", "abstain_correct"):
                recovered += 1
        retry_recovery_rate = round(recovered / len(failed_first_cases), 4)
    else:
        retry_recovery_rate = None

    # Severity and taxonomy counts
    severity_counts = Counter(g.get("severity") for g in gradings if g.get("severity"))
    taxonomy_counts = Counter(g.get("primary_failure") for g in gradings if g.get("primary_failure"))
    for g in gradings:
        for sec in g.get("secondary_failures", []):
            taxonomy_counts[sec] += 1

    first_attempt_success_rate = round((first_passes / n_total), 4) if n_total > 0 else 0.0
    eventual_success_rate = round((eventual_passes / n_total), 4) if n_total > 0 else 0.0

    return {
        "schema_version": "phase4-aggregate-v1",
        "run_id": run_id,
        "logical_cases": n_total,
        "n_total": n_total,
        "n_attempt": n_attempt,
        "n_graded": n_graded,
        "n_blocked": n_blocked,
        "first_attempt_outcomes": dict(first_outcomes),
        "eventual_outcomes": dict(eventual_outcomes),
        "quality_conditional": quality_conditional,
        "e2e_success": e2e_success,
        "first_attempt_success_rate": first_attempt_success_rate,
        "eventual_success_rate": eventual_success_rate,
        "retry_recovery_rate": retry_recovery_rate,
        "severity_counts": dict(severity_counts),
        "taxonomy_failure_counts": dict(taxonomy_counts),
        "derived_from": [
            "attempts.jsonl",
            "grading.jsonl",
            "retrieval.jsonl",
            "errors.jsonl",
        ],
        "artifact_checksums": "checksums.sha256",
    }


class CanonicalBundleValidator:
    """Validates an entire run bundle against Phase 4 specifications."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)

    def validate(self) -> ValidationReport:
        errors: List[str] = []
        warnings: List[str] = []
        all_record_ids: Set[str] = set()

        # 1. Check all canonical files exist
        for fname in CANONICAL_ARTIFACT_FILES:
            fpath = self.run_dir / fname
            if not fpath.is_file():
                errors.append(f"Missing canonical artifact file: {fname}")

        if errors:
            return ValidationReport(run_id="<unknown>", is_valid=False, errors=errors)

        # 2. Validate manifest.json
        manifest_path = self.run_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            validate_manifest(manifest)
            run_id = manifest.get("run_id", "")
        except Exception as exc:
            errors.append(f"manifest.json validation failed: {exc}")
            return ValidationReport(run_id="<unknown>", is_valid=False, errors=errors)

        # Verify manifest dataset_sha256 strictly equals frozen benchmark LF hash
        if manifest.get("dataset_sha256") != FROZEN_BENCHMARK_LF_SHA256:
            errors.append(
                f"manifest.json: dataset_sha256 mismatch: expected {FROZEN_BENCHMARK_LF_SHA256}, got {manifest.get('dataset_sha256')}"
            )

        # 3. Validate Checksums (checksums.sha256)
        checksum_path = self.run_dir / "checksums.sha256"
        recorded_checksums: Dict[str, str] = {}
        expected_checksum_files = {"manifest.json", "attempts.jsonl", "grading.jsonl", "retrieval.jsonl", "errors.jsonl", "aggregate.json"}
        import re
        hex_64_re = re.compile(r"^[0-9a-f]{64}$")

        try:
            for line_no, line in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), start=1):
                line = line.strip()
                if not line:
                    continue
                parts = line.split(maxsplit=1)
                if len(parts) != 2:
                    errors.append(f"checksums.sha256: Invalid line {line_no}: '{line}'")
                    continue
                sha, filename = parts[0], parts[1].strip()
                if not hex_64_re.match(sha):
                    errors.append(f"checksums.sha256: Invalid 64-hex SHA on line {line_no}: '{sha}'")
                if filename not in expected_checksum_files:
                    errors.append(f"checksums.sha256: Non-canonical or disallowed entry '{filename}' on line {line_no}")
                recorded_checksums[filename] = sha
        except Exception as exc:
            errors.append(f"Failed to read checksums.sha256: {exc}")

        # Check self-reference avoidance
        if "checksums.sha256" in recorded_checksums:
            errors.append("checksums.sha256 must not reference itself (self-reference detected)")

        # Verify all expected canonical files have checksum entries
        for fname in expected_checksum_files:
            if fname not in recorded_checksums:
                errors.append(f"checksums.sha256 is missing entry for {fname}")
            else:
                actual_sha = compute_sha256(self.run_dir / fname)
                if actual_sha != recorded_checksums[fname]:
                    errors.append(
                        f"Checksum mismatch for {fname}: recorded={recorded_checksums[fname]}, actual={actual_sha}"
                    )

        # 4. Parse and validate attempts.jsonl
        attempts: List[Dict[str, Any]] = []
        attempts_by_id: Dict[str, Dict[str, Any]] = {}
        attempt_record_ids: Set[str] = set()
        retry_groups: Dict[Tuple[str, str], List[int]] = defaultdict(list)
        attempts_path = self.run_dir / "attempts.jsonl"
        try:
            for line_no, line in enumerate(attempts_path.read_text(encoding="utf-8").splitlines(), start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    att = json.loads(line)
                    validate_attempt_record(att)
                except Exception as exc:
                    errors.append(f"attempts.jsonl line {line_no} schema error: {exc}")
                    continue

                rec_id = att["record_id"]
                if rec_id in all_record_ids:
                    errors.append(f"attempts.jsonl: Duplicate record_id '{rec_id}' at line {line_no}")
                all_record_ids.add(rec_id)
                attempt_record_ids.add(rec_id)

                att_id = att["attempt_id"]
                if att_id in attempts_by_id:
                    errors.append(f"attempts.jsonl: Duplicate attempt_id '{att_id}' at line {line_no}")
                attempts_by_id[att_id] = att

                # Check run_id and commit SHA match manifest
                if att.get("run_id") != run_id:
                    errors.append(f"attempts.jsonl line {line_no}: run_id '{att.get('run_id')}' != manifest run_id '{run_id}'")
                if att.get("system_commit_sha") != manifest.get("system_commit_sha"):
                    errors.append(f"attempts.jsonl line {line_no}: system_commit_sha does not match manifest")
                if att.get("evaluation_harness_sha") != manifest.get("evaluation_harness_sha"):
                    errors.append(f"attempts.jsonl line {line_no}: evaluation_harness_sha does not match manifest")

                group_key = (att["case_id"], att["logical_request_id"])
                retry_groups[group_key].append(att["retry_index"])
                attempts.append(att)
        except Exception as exc:
            errors.append(f"Failed reading attempts.jsonl: {exc}")

        # Check retry sequencing per retry group
        for group_key, indices in retry_groups.items():
            sorted_indices = sorted(indices)
            expected = list(range(len(indices)))
            if sorted_indices != expected:
                errors.append(
                    f"Invalid retry sequence for case {group_key[0]}, request {group_key[1]}: got {indices}, expected {expected}"
                )

        # 5. Parse and validate grading.jsonl
        gradings: List[Dict[str, Any]] = []
        grading_ids: Set[str] = set()
        grading_record_ids: Set[str] = set()
        grading_path = self.run_dir / "grading.jsonl"
        try:
            for line_no, line in enumerate(grading_path.read_text(encoding="utf-8").splitlines(), start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    gr = json.loads(line)
                    validate_grading_record(gr)
                except Exception as exc:
                    errors.append(f"grading.jsonl line {line_no} schema error: {exc}")
                    continue

                rec_id = gr["record_id"]
                if rec_id in all_record_ids:
                    errors.append(f"grading.jsonl: Duplicate record_id '{rec_id}' at line {line_no}")
                all_record_ids.add(rec_id)
                grading_record_ids.add(rec_id)

                gid = gr["grading_id"]
                if gid in grading_ids:
                    errors.append(f"grading.jsonl: Duplicate grading_id '{gid}' at line {line_no}")
                grading_ids.add(gid)

                # Check join key and provenance to target attempt
                target_att_id = gr["graded_attempt_id"]
                target_att = attempts_by_id.get(target_att_id)
                if not target_att:
                    errors.append(
                        f"grading.jsonl line {line_no}: graded_attempt_id '{target_att_id}' not found in attempts.jsonl"
                    )
                else:
                    if gr.get("run_id") != target_att.get("run_id"):
                        errors.append(f"grading.jsonl line {line_no}: run_id '{gr.get('run_id')}' != target attempt run_id '{target_att.get('run_id')}'")
                    if gr.get("case_id") != target_att.get("case_id"):
                        errors.append(f"grading.jsonl line {line_no}: case_id '{gr.get('case_id')}' != target attempt case_id '{target_att.get('case_id')}'")
                    if gr.get("logical_request_id") != target_att.get("logical_request_id"):
                        errors.append(f"grading.jsonl line {line_no}: logical_request_id '{gr.get('logical_request_id')}' != target attempt logical_request_id '{target_att.get('logical_request_id')}'")
                    if gr.get("system_commit_sha") != target_att.get("system_commit_sha"):
                        errors.append(f"grading.jsonl line {line_no}: system_commit_sha != target attempt system_commit_sha")
                    if gr.get("evaluation_harness_sha") != target_att.get("evaluation_harness_sha"):
                        errors.append(f"grading.jsonl line {line_no}: evaluation_harness_sha != target attempt evaluation_harness_sha")
                    if gr.get("config_sha256") != target_att.get("config_sha256"):
                        errors.append(f"grading.jsonl line {line_no}: config_sha256 != target attempt config_sha256")

                gradings.append(gr)
        except Exception as exc:
            errors.append(f"Failed reading grading.jsonl: {exc}")

        # 6. Parse and validate retrieval.jsonl
        retrievals: List[Dict[str, Any]] = []
        retrieval_ids: Set[str] = set()
        retrieval_record_ids: Set[str] = set()
        retrieval_path = self.run_dir / "retrieval.jsonl"
        try:
            for line_no, line in enumerate(retrieval_path.read_text(encoding="utf-8").splitlines(), start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rt = json.loads(line)
                    validate_retrieval_record(rt)
                except Exception as exc:
                    errors.append(f"retrieval.jsonl line {line_no} schema error: {exc}")
                    continue

                rec_id = rt["record_id"]
                if rec_id in all_record_ids:
                    errors.append(f"retrieval.jsonl: Duplicate record_id '{rec_id}' at line {line_no}")
                all_record_ids.add(rec_id)
                retrieval_record_ids.add(rec_id)

                rid = rt["retrieval_event_id"]
                if rid in retrieval_ids:
                    errors.append(f"retrieval.jsonl: Duplicate retrieval_event_id '{rid}' at line {line_no}")
                retrieval_ids.add(rid)

                # Check join key and provenance to target attempt
                target_att_id = rt["attempt_id"]
                target_att = attempts_by_id.get(target_att_id)
                if not target_att:
                    errors.append(
                        f"retrieval.jsonl line {line_no}: attempt_id '{target_att_id}' not found in attempts.jsonl"
                    )
                else:
                    if rt.get("run_id") != target_att.get("run_id"):
                        errors.append(f"retrieval.jsonl line {line_no}: run_id '{rt.get('run_id')}' != target attempt run_id '{target_att.get('run_id')}'")
                    if rt.get("case_id") != target_att.get("case_id"):
                        errors.append(f"retrieval.jsonl line {line_no}: case_id '{rt.get('case_id')}' != target attempt case_id '{target_att.get('case_id')}'")
                    if rt.get("logical_request_id") != target_att.get("logical_request_id"):
                        errors.append(f"retrieval.jsonl line {line_no}: logical_request_id '{rt.get('logical_request_id')}' != target attempt logical_request_id '{target_att.get('logical_request_id')}'")
                    if rt.get("system_commit_sha") != target_att.get("system_commit_sha"):
                        errors.append(f"retrieval.jsonl line {line_no}: system_commit_sha != target attempt system_commit_sha")
                    if rt.get("evaluation_harness_sha") != target_att.get("evaluation_harness_sha"):
                        errors.append(f"retrieval.jsonl line {line_no}: evaluation_harness_sha != target attempt evaluation_harness_sha")
                    if rt.get("config_sha256") != target_att.get("config_sha256"):
                        errors.append(f"retrieval.jsonl line {line_no}: config_sha256 != target attempt config_sha256")

                retrievals.append(rt)
        except Exception as exc:
            errors.append(f"Failed reading retrieval.jsonl: {exc}")

        # 7. Parse and validate errors.jsonl
        error_records: List[Dict[str, Any]] = []
        error_ids: Set[str] = set()
        error_record_ids: Set[str] = set()
        errors_path = self.run_dir / "errors.jsonl"
        try:
            for line_no, line in enumerate(errors_path.read_text(encoding="utf-8").splitlines(), start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    err = json.loads(line)
                    validate_error_record(err)
                except Exception as exc:
                    errors.append(f"errors.jsonl line {line_no} schema error: {exc}")
                    continue

                rec_id = err["record_id"]
                if rec_id in all_record_ids:
                    errors.append(f"errors.jsonl: Duplicate record_id '{rec_id}' at line {line_no}")
                all_record_ids.add(rec_id)
                error_record_ids.add(rec_id)

                eid = err["error_id"]
                if eid in error_ids:
                    errors.append(f"errors.jsonl: Duplicate error_id '{eid}' at line {line_no}")
                error_ids.add(eid)

                # Check join key and provenance to target attempt
                target_att_id = err["attempt_id"]
                target_att = attempts_by_id.get(target_att_id)
                if not target_att:
                    errors.append(
                        f"errors.jsonl line {line_no}: attempt_id '{target_att_id}' not found in attempts.jsonl"
                    )
                else:
                    if err.get("run_id") != target_att.get("run_id"):
                        errors.append(f"errors.jsonl line {line_no}: run_id '{err.get('run_id')}' != target attempt run_id '{target_att.get('run_id')}'")
                    if err.get("case_id") != target_att.get("case_id"):
                        errors.append(f"errors.jsonl line {line_no}: case_id '{err.get('case_id')}' != target attempt case_id '{target_att.get('case_id')}'")
                    if err.get("logical_request_id") != target_att.get("logical_request_id"):
                        errors.append(f"errors.jsonl line {line_no}: logical_request_id '{err.get('logical_request_id')}' != target attempt logical_request_id '{target_att.get('logical_request_id')}'")
                    if err.get("system_commit_sha") != target_att.get("system_commit_sha"):
                        errors.append(f"errors.jsonl line {line_no}: system_commit_sha != target attempt system_commit_sha")
                    if err.get("evaluation_harness_sha") != target_att.get("evaluation_harness_sha"):
                        errors.append(f"errors.jsonl line {line_no}: evaluation_harness_sha != target attempt evaluation_harness_sha")
                    if err.get("config_sha256") != target_att.get("config_sha256"):
                        errors.append(f"errors.jsonl line {line_no}: config_sha256 != target attempt config_sha256")

                error_records.append(err)
        except Exception as exc:
            errors.append(f"Failed reading errors.jsonl: {exc}")

        # 8. Parse and validate aggregate.json & Recompute check
        recomputed = None
        aggregate_path = self.run_dir / "aggregate.json"
        try:
            aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
            validate_aggregate(aggregate)

            # Recompute aggregate from raw records
            recomputed = recompute_aggregate_from_raw(manifest, attempts, gradings, error_records)

            for key in ("logical_cases", "n_total", "n_attempt", "n_graded", "n_blocked"):
                if aggregate.get(key) != recomputed[key]:
                    errors.append(
                        f"aggregate.json {key} mismatch: recorded={aggregate.get(key)}, recomputed={recomputed[key]}"
                    )

            for ratio_key in ("quality_conditional", "e2e_success"):
                rec_ratio = aggregate.get(ratio_key, {})
                recomp_ratio = recomputed[ratio_key]
                if rec_ratio.get("numerator") != recomp_ratio["numerator"] or rec_ratio.get("denominator") != recomp_ratio["denominator"]:
                    errors.append(
                        f"aggregate.json {ratio_key} mismatch: recorded={rec_ratio}, recomputed={recomp_ratio}"
                    )
        except Exception as exc:
            errors.append(f"aggregate.json recomputation validation failed: {exc}")

        is_valid = len(errors) == 0
        return ValidationReport(
            run_id=run_id,
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            attempt_count=len(attempts),
            logical_case_count=len({a["case_id"] for a in attempts}),
            grading_count=len(gradings),
            retrieval_count=len(retrievals),
            error_count=len(error_records),
            recomputed_aggregate=recomputed,
        )
