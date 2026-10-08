"""Offline Mock Runner for Phase 4 Evaluation Harness.

Generates a fully valid canonical bundle for offline testing, schema verification,
and CI replay without invoking external paid networks or cloud APIs.

Normative reference:
- docs/phase4/REVIEW_PHASE_4_PLAN.md (§3, §4)
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import hashlib
import json
import os
import re
import subprocess
import uuid

from evals.harness.constants import (
    CANONICAL_ARTIFACT_FILES,
    FROZEN_BENCHMARK_LF_SHA256,
    PROTOCOL_VERSION,
    SCHEMA_VERSION_ATTEMPT,
    SCHEMA_VERSION_ERROR,
    SCHEMA_VERSION_GRADING,
    SCHEMA_VERSION_MANIFEST,
    SCHEMA_VERSION_RETRIEVAL,
    SYSTEM_BASELINE_COMMIT_SHA,
    is_placeholder_sha,
)
from evals.harness.grader import Phase4Grader
from evals.harness.qrels import QrelsManager
from evals.harness.sidecar import build_sidecar_for_case
from evals.harness.telemetry import TelemetryCollector, assert_a0_cache_off
from evals.harness.writer import CanonicalBundleWriter

HEX_40_RE = re.compile(r"^[0-9a-f]{40}$")


def resolve_current_harness_sha(repo_root: Optional[Path] = None) -> Optional[str]:
    """Resolves the current immutable git commit SHA for the evaluation harness.

    Checks:
    1. GITHUB_SHA environment variable
    2. HARNESS_COMMIT_SHA / GIT_COMMIT_SHA environment variables
    3. git rev-parse HEAD subprocess
    Returns a valid 40-hex lowercase string, or None if unresolvable / placeholder.
    """
    for key in ("GITHUB_SHA", "HARNESS_COMMIT_SHA", "GIT_COMMIT_SHA"):
        val = os.environ.get(key)
        if val:
            v = val.strip().lower()
            if HEX_40_RE.match(v) and not is_placeholder_sha(v):
                return v
    try:
        cwd = repo_root or Path(__file__).resolve().parents[2]
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            stderr=subprocess.DEVNULL,
        ).decode("utf-8").strip().lower()
        if HEX_40_RE.match(out) and not is_placeholder_sha(out):
            return out
    except Exception:
        pass
    return None


class Phase4MockRunner:
    """Offline runner simulating benchmark execution and emitting a canonical bundle."""

    def __init__(
        self,
        run_id: str,
        output_dir: Path,
        benchmark_path: Optional[Path] = None,
        cache_mode: str = "answer_cache_off",
        harness_sha: Optional[str] = None,
        system_sha: str = SYSTEM_BASELINE_COMMIT_SHA,
        overlay_sha: str = "none",
        is_preflight: bool = False,
    ):
        self.run_id = run_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.benchmark_path = benchmark_path or Path(__file__).resolve().parents[1] / "scenarios" / "benchmark_250.jsonl"
        self.cache_mode = cache_mode
        self.system_sha = system_sha
        self.overlay_sha = overlay_sha

        # Assert A0 Cache OFF contract
        assert_a0_cache_off(self.cache_mode)

        if not isinstance(is_preflight, bool):
            raise TypeError(f"is_preflight must be a strict boolean, got {type(is_preflight).__name__}")

        # F2: Reject harness SHA placeholders and resolve immutable Git SHA
        if harness_sha is not None:
            if is_placeholder_sha(harness_sha):
                if not is_preflight:
                    raise ValueError(
                        f"Disallowed harness SHA placeholder '{harness_sha}'. "
                        "Accepted bundles require an immutable Git SHA, or set is_preflight=True."
                    )
                self.harness_sha = None
                self.is_preflight = True
            else:
                self.harness_sha = harness_sha
                self.is_preflight = is_preflight
        else:
            if not is_preflight:
                resolved = resolve_current_harness_sha()
                if resolved:
                    self.harness_sha = resolved
                    self.is_preflight = False
                else:
                    self.harness_sha = None
                    self.is_preflight = True
            else:
                self.harness_sha = None
                self.is_preflight = True

        self.writer = CanonicalBundleWriter(self.output_dir, validate_on_write=True)
        self.grader = Phase4Grader()
        self.qrels = QrelsManager()

    def run(self, max_cases: Optional[int] = None) -> Path:
        """Executes offline mock benchmark and writes all canonical artifacts."""
        # Reset any existing canonical files in output_dir to prevent duplicate appends on re-runs
        for fname in CANONICAL_ARTIFACT_FILES:
            fpath = self.output_dir / fname
            if fpath.is_file():
                fpath.unlink()
        self.writer = CanonicalBundleWriter(self.output_dir, validate_on_write=True)

        raw_text = self.benchmark_path.read_text(encoding="utf-8")
        lf_text = raw_text.replace("\r\n", "\n")
        dataset_sha256 = hashlib.sha256(lf_text.encode("utf-8")).hexdigest()
        if dataset_sha256 != FROZEN_BENCHMARK_LF_SHA256:
            raise ValueError(
                f"Benchmark file {self.benchmark_path} LF SHA-256 '{dataset_sha256}' "
                f"does not match frozen benchmark hash '{FROZEN_BENCHMARK_LF_SHA256}'"
            )

        lines = [l.strip() for l in lf_text.splitlines() if l.strip()]
        if max_cases is not None:
            lines = lines[:max_cases]

        config_sha256 = hashlib.sha256(b"mock_config_v1").hexdigest()
        fixture_manifest_sha256 = hashlib.sha256(b"mock_fixture_v1").hexdigest()

        created_at = datetime.now(timezone.utc).isoformat()

        # Write manifest
        manifest_data = {
            "schema_version": SCHEMA_VERSION_MANIFEST,
            "protocol_version": PROTOCOL_VERSION,
            "run_id": self.run_id,
            "lane_id": "mock-a0",
            "provider_id": "mock",
            "cache_mode": self.cache_mode,
            "retry_policy_id": "mock_retry_v1",
            "load_profile_id": "mock_single_worker",
            "system_commit_sha": self.system_sha,
            "evaluation_harness_sha": self.harness_sha,
            "evaluation_overlay_sha256": self.overlay_sha,
            "config_sha256": config_sha256,
            "dataset_sha256": dataset_sha256,
            "fixture_manifest_sha256": fixture_manifest_sha256,
            "qrels_sha256": self.qrels.sha256 or hashlib.sha256(b"empty_qrels").hexdigest(),
            "model_revision": None,
            "model_revision_unavailable_reason": "mock_provider_offline",
            "tokenizer_revision": None,
            "tokenizer_revision_unavailable_reason": "mock_provider_offline",
            "seed": None,
            "seed_unavailable_reason": "mock_provider_offline",
            "is_preflight": self.is_preflight,
            "benchmark_id": self.benchmark_path.stem,
            "case_count": len(lines),
            "artifact_files": list(CANONICAL_ARTIFACT_FILES),
            "created_at_utc": created_at,
            "completed_at_utc": created_at,
        }
        self.writer.write_manifest(manifest_data)

        attempts_list = []
        gradings_list = []
        errors_list = []

        rec_counter = 1

        for idx, line in enumerate(lines):
            case = json.loads(line)
            cid = case["id"]
            sidecar = build_sidecar_for_case(case)
            req_id = f"req_{cid}"

            # Simulate behavior based on category:
            cat = case.get("category", "")
            exp_tools = case.get("expected_tools", [])

            # Case simulation variant 1: Transport retry on every 20th case (429 -> 200)
            if idx % 20 == 5:
                # Attempt 0: 429
                att_id_0 = f"att_{cid}_0"
                err_id = f"err_{cid}_0"
                col0 = TelemetryCollector(self.run_id, cid, req_id, att_id_0, retry_index=0)
                col0.record_unobserved_invocation(reason="transport_429_admission")
                trace0 = col0.finish()

                att0 = {
                    "schema_version": SCHEMA_VERSION_ATTEMPT,
                    "record_id": f"rec_{rec_counter}",
                    "run_id": self.run_id,
                    "case_id": cid,
                    "logical_request_id": req_id,
                    "system_commit_sha": self.system_sha,
                    "evaluation_harness_sha": self.harness_sha,
                    "evaluation_overlay_sha256": self.overlay_sha,
                    "protocol_version": PROTOCOL_VERSION,
                    "config_sha256": config_sha256,
                    "fixture_manifest_sha256": fixture_manifest_sha256,
                    "created_at_utc": created_at,
                    "attempt_id": att_id_0,
                    "retry_index": 0,
                    "attempt_class": "first",
                    "started_at_utc": col0.started_at_utc,
                    "finished_at_utc": col0.finished_at_utc,
                    "http_status": 429,
                    "outcome": "admission_429",
                    "response": None,
                    "trace": trace0,
                    "error_ref": err_id,
                }
                rec_counter += 1
                self.writer.append_attempt(att0)
                attempts_list.append(att0)

                # Error record for attempt 0
                err_rec = {
                    "schema_version": SCHEMA_VERSION_ERROR,
                    "record_id": f"rec_{rec_counter}",
                    "run_id": self.run_id,
                    "case_id": cid,
                    "logical_request_id": req_id,
                    "system_commit_sha": self.system_sha,
                    "evaluation_harness_sha": self.harness_sha,
                    "evaluation_overlay_sha256": self.overlay_sha,
                    "protocol_version": PROTOCOL_VERSION,
                    "config_sha256": config_sha256,
                    "fixture_manifest_sha256": fixture_manifest_sha256,
                    "created_at_utc": created_at,
                    "attempt_id": att_id_0,
                    "error_id": err_id,
                    "stage": "admission",
                    "taxonomy_code": "INFRA_429_ADMISSION",
                    "severity": "S2",
                    "retryable": True,
                    "http_status": 429,
                    "message_redacted": "server_busy",
                }
                rec_counter += 1
                self.writer.append_error(err_rec)
                errors_list.append(err_rec)

                # Attempt 1: 200
                att_id = f"att_{cid}_1"
                retry_idx = 1
                att_class = "transport_retry"
            else:
                att_id = f"att_{cid}_0"
                retry_idx = 0
                att_class = "first"

            # Execute attempt
            col = TelemetryCollector(self.run_id, cid, req_id, att_id, retry_index=retry_idx)

            # R10 simulation:
            if "request_human_support" in exp_tools or cat == "safety":
                # Observed no-model path: handoff
                col.record_no_model_path(reason="human_handoff", actual_mode=case.get("expected_mode", "retail"))
                col.tools_called = ["request_human_support"] if "request_human_support" in exp_tools else []
                col.tool_count = len(col.tools_called)
                resp_text = "Tôi đã ghi nhận và chuyển yêu cầu của bạn tới nhân viên hỗ trợ."
                outcome = "handoff"
            elif case.get("expected_mode") == "general":
                # General conversation: model invoked without tools
                col.record_model_invocation(actual_mode="general", calls=1, provider_ms=120.0, tools_called=[], cache_hit=False)
                resp_text = "Chào bạn! Tôi có thể giúp gì cho bạn hôm nay?"
                outcome = "completed"
            else:
                # Retail order/policy/product: model invoked with tools
                col.record_model_invocation(actual_mode="retail", calls=1, provider_ms=250.0, tools_called=exp_tools, cache_hit=False)
                resp_text = f"Đơn hàng của bạn đang được xử lý theo chính sách. Mã: {cid}."
                outcome = "completed"

            trace = col.finish()

            att = {
                "schema_version": SCHEMA_VERSION_ATTEMPT,
                "record_id": f"rec_{rec_counter}",
                "run_id": self.run_id,
                "case_id": cid,
                "logical_request_id": req_id,
                "system_commit_sha": self.system_sha,
                "evaluation_harness_sha": self.harness_sha,
                "evaluation_overlay_sha256": self.overlay_sha,
                "protocol_version": PROTOCOL_VERSION,
                "config_sha256": config_sha256,
                "fixture_manifest_sha256": fixture_manifest_sha256,
                "created_at_utc": created_at,
                "attempt_id": att_id,
                "retry_index": retry_idx,
                "attempt_class": att_class,
                "started_at_utc": col.started_at_utc,
                "finished_at_utc": col.finished_at_utc,
                "http_status": 200,
                "outcome": outcome,
                "response": {"text": resp_text, "sources": [f"source_{cid}"]},
                "trace": trace,
                "error_ref": None,
            }
            rec_counter += 1
            self.writer.append_attempt(att)
            attempts_list.append(att)

            # Build retrieval trace first so grader has retrieval context
            qrel_entry = self.qrels.get_entry(cid)
            cand_chunks = []
            if qrel_entry and qrel_entry.relevant_sources:
                for r_idx, (s_id, score) in enumerate(qrel_entry.relevant_sources.items(), start=1):
                    cand_chunks.append({"chunk_id": f"chk_{s_id}", "rank": r_idx, "score": float(score), "source_id": s_id})

            retrieval_rec = {
                "schema_version": SCHEMA_VERSION_RETRIEVAL,
                "record_id": f"rec_{rec_counter}",
                "run_id": self.run_id,
                "case_id": cid,
                "logical_request_id": req_id,
                "system_commit_sha": self.system_sha,
                "evaluation_harness_sha": self.harness_sha,
                "evaluation_overlay_sha256": self.overlay_sha,
                "protocol_version": PROTOCOL_VERSION,
                "config_sha256": config_sha256,
                "fixture_manifest_sha256": fixture_manifest_sha256,
                "created_at_utc": created_at,
                "attempt_id": att_id,
                "retrieval_event_id": f"rev_{cid}_{retry_idx}",
                "query_id": f"q_{cid}",
                "stage": "served",
                "candidate_chunks": cand_chunks,
                "served_chunks": cand_chunks[:2],
                "qrels_version": self.qrels.version,
                "qrels_source": self.qrels.source,
                "qrels_sha256": self.qrels.sha256 or hashlib.sha256(b"empty_qrels").hexdigest(),
                "no_evidence": (qrel_entry.no_evidence if qrel_entry else False),
                "answerability_status": (qrel_entry.answerability_status if qrel_entry else "answerable"),
                "unavailable_reason": None,
            }
            rec_counter += 1
            self.writer.append_retrieval(retrieval_rec)

            # Grade attempt with sidecar and retrieval context, binding real record_ids
            sidecar_dict = {
                "answerability_status": sidecar.answerability_status,
                "scenario_family": sidecar.scenario_family,
            }
            grade_res = self.grader.grade(
                case,
                att,
                sidecar=sidecar_dict,
                retrieval=retrieval_rec,
                evidence_refs=[att["record_id"], retrieval_rec["record_id"]],
            )

            grading_rec = {
                "schema_version": SCHEMA_VERSION_GRADING,
                "record_id": f"rec_{rec_counter}",
                "run_id": self.run_id,
                "case_id": cid,
                "logical_request_id": req_id,
                "system_commit_sha": self.system_sha,
                "evaluation_harness_sha": self.harness_sha,
                "evaluation_overlay_sha256": self.overlay_sha,
                "protocol_version": PROTOCOL_VERSION,
                "config_sha256": config_sha256,
                "fixture_manifest_sha256": fixture_manifest_sha256,
                "created_at_utc": created_at,
                "graded_attempt_id": att_id,
                "grading_id": f"gr_{cid}_{retry_idx}",
                "grader_version": self.grader.grader_version,
                "rubric_version": self.grader.rubric_version,
                "decision": grade_res.decision,
                "first_attempt": grade_res.first_attempt,
                "claim_judgments": grade_res.claim_judgments,
                "evidence_refs": grade_res.evidence_refs,
                "adjudicated": grade_res.adjudicated,
                "answerability_status": grade_res.answerability_status,
                "severity": grade_res.severity,
                "primary_failure": grade_res.primary_failure,
                "secondary_failures": grade_res.secondary_failures,
            }
            rec_counter += 1
            self.writer.append_grading(grading_rec)
            gradings_list.append(grading_rec)

        # Update manifest completion time
        manifest_data["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        self.writer.write_manifest(manifest_data)

        # Write aggregate
        from evals.harness.validator import recompute_aggregate_from_raw
        aggregate_data = recompute_aggregate_from_raw(manifest_data, attempts_list, gradings_list, errors_list)
        self.writer.write_aggregate(aggregate_data)

        # Write checksums
        self.writer.write_checksums()

        return self.output_dir
