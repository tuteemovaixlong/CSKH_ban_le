"""Validation and dataclasses for Phase 4 schemas.

Normative reference:
- docs/phase4/PHASE_4_RESULTS_SCHEMA.md
- docs/phase4/PHASE_4_FAILURE_TAXONOMY.md
- docs/phase4/PHASE_4_METRICS_DEFINITION.md
"""

from typing import Any, Dict, List, Optional
import math
import re

from evals.harness.constants import (
    CANONICAL_ARTIFACT_FILES,
    COMMON_ENVELOPE_FIELDS,
    FROZEN_BENCHMARK_LF_SHA256,
    PROTOCOL_VERSION,
    SCHEMA_VERSION_AGGREGATE,
    SCHEMA_VERSION_ATTEMPT,
    SCHEMA_VERSION_ERROR,
    SCHEMA_VERSION_GRADING,
    SCHEMA_VERSION_MANIFEST,
    SCHEMA_VERSION_RETRIEVAL,
    STATUS_MEASUREMENT_READY,
    STATUS_PREFLIGHT,
    VALID_ANSWERABILITY_STATUSES,
    VALID_ATTEMPT_CLASSES,
    VALID_ATTEMPT_OUTCOMES,
    VALID_DECISIONS,
    VALID_READINESS_STATUSES,
    VALID_SEVERITIES,
    VALID_TAXONOMY_CODES,
    VALID_ZERO_REASONS,
    is_placeholder_sha,
)

HEX_40_RE = re.compile(r"^[0-9a-f]{40}$")
HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


class SchemaValidationError(ValueError):
    """Raised when a Phase 4 record fails schema or contract validation."""
    pass


def validate_common_envelope(record: Dict[str, Any], record_type: str) -> None:
    """Validates the standard common envelope present on every JSONL record."""
    missing = [f for f in COMMON_ENVELOPE_FIELDS if f not in record]
    if missing:
        raise SchemaValidationError(f"[{record_type}] Missing common envelope fields: {missing}")

    if record["protocol_version"] != PROTOCOL_VERSION:
        raise SchemaValidationError(
            f"[{record_type}] Invalid protocol_version: {record['protocol_version']} (expected {PROTOCOL_VERSION})"
        )

    for field in ("record_id", "run_id", "case_id", "logical_request_id", "created_at_utc"):
        val = record.get(field)
        if not isinstance(val, str) or not val.strip():
            raise SchemaValidationError(f"[{record_type}] Field '{field}' must be a non-empty string")

    # system_commit_sha: 40-char hex
    sys_sha = record.get("system_commit_sha", "")
    if not HEX_40_RE.match(sys_sha):
        raise SchemaValidationError(f"[{record_type}] Invalid system_commit_sha: {sys_sha}")

    # evaluation_harness_sha: 40-char hex or None/null in preflight dry-run
    harness_sha = record.get("evaluation_harness_sha")
    if harness_sha is not None:
        if not HEX_40_RE.match(harness_sha):
            raise SchemaValidationError(f"[{record_type}] Invalid evaluation_harness_sha: {harness_sha}")
        if is_placeholder_sha(harness_sha):
            raise SchemaValidationError(f"[{record_type}] evaluation_harness_sha cannot be a placeholder: {harness_sha}")

    # evaluation_overlay_sha256: 64-char hex or 'none'
    overlay_sha = record.get("evaluation_overlay_sha256", "")
    if overlay_sha != "none" and not HEX_64_RE.match(overlay_sha):
        raise SchemaValidationError(f"[{record_type}] Invalid evaluation_overlay_sha256: {overlay_sha}")

    # config_sha256 and fixture_manifest_sha256: 64-char hex
    for sha_field in ("config_sha256", "fixture_manifest_sha256"):
        sha_val = record.get(sha_field, "")
        if not HEX_64_RE.match(sha_val):
            raise SchemaValidationError(f"[{record_type}] Invalid {sha_field}: {sha_val}")


def validate_manifest(data: Dict[str, Any]) -> None:
    """Validates manifest.json structure according to normative Phase 4 results schema."""
    if data.get("schema_version") != SCHEMA_VERSION_MANIFEST:
        raise SchemaValidationError(f"manifest: Invalid schema_version: {data.get('schema_version')}")

    required_fields = (
        "schema_version", "protocol_version", "run_id", "lane_id", "provider_id",
        "cache_mode", "retry_policy_id", "load_profile_id", "system_commit_sha",
        "evaluation_harness_sha", "evaluation_overlay_sha256", "config_sha256",
        "dataset_sha256", "fixture_manifest_sha256", "qrels_sha256",
        "created_at_utc", "completed_at_utc", "artifact_files"
    )
    missing = [f for f in required_fields if f not in data]
    if missing:
        raise SchemaValidationError(f"manifest: Missing required fields: {missing}")

    if data.get("protocol_version") != PROTOCOL_VERSION:
        raise SchemaValidationError(
            f"manifest: Invalid protocol_version: {data.get('protocol_version')} (expected {PROTOCOL_VERSION})"
        )

    # Cache mode must be answer_cache_off
    cache_mode = data.get("cache_mode")
    if cache_mode != "answer_cache_off":
        raise SchemaValidationError(f"manifest: cache_mode must be 'answer_cache_off', got '{cache_mode}'")

    for str_field in ("run_id", "lane_id", "provider_id", "retry_policy_id", "load_profile_id", "created_at_utc", "completed_at_utc"):
        val = data.get(str_field)
        if not isinstance(val, str) or not val.strip():
            raise SchemaValidationError(f"manifest: Field '{str_field}' must be a non-empty string")

    # Validate commit SHAs (40 hex)
    sys_sha = data.get("system_commit_sha", "")
    if not HEX_40_RE.match(sys_sha):
        raise SchemaValidationError(f"manifest: Invalid system_commit_sha: {sys_sha}")

    harness_sha = data.get("evaluation_harness_sha")
    if "is_preflight" in data:
        is_preflight_raw = data["is_preflight"]
        if not isinstance(is_preflight_raw, bool):
            raise SchemaValidationError(
                f"manifest: is_preflight must be a strict boolean, got {type(is_preflight_raw).__name__}"
            )
        is_preflight = is_preflight_raw
    else:
        is_preflight = False
    if is_preflight:
        if harness_sha is not None:
            if not isinstance(harness_sha, str) or not HEX_40_RE.match(harness_sha):
                raise SchemaValidationError(f"manifest: Invalid evaluation_harness_sha in preflight: {harness_sha}")
            if is_placeholder_sha(harness_sha):
                raise SchemaValidationError(f"manifest: evaluation_harness_sha cannot be a placeholder in preflight: {harness_sha}")
    else:
        if harness_sha is None or not isinstance(harness_sha, str) or not HEX_40_RE.match(harness_sha):
            raise SchemaValidationError(f"manifest: Accepted bundle requires non-null 40-hex evaluation_harness_sha, got: {harness_sha}")
        if is_placeholder_sha(harness_sha):
            raise SchemaValidationError(f"manifest: evaluation_harness_sha cannot be a placeholder in accepted bundle: {harness_sha}")

    # evaluation_overlay_sha256: 64-char hex or 'none'
    overlay_sha = data.get("evaluation_overlay_sha256", "")
    if overlay_sha != "none" and not HEX_64_RE.match(overlay_sha):
        raise SchemaValidationError(f"manifest: Invalid evaluation_overlay_sha256: {overlay_sha}")

    # SHA-256 fields (64 hex)
    for sha_field in ("config_sha256", "dataset_sha256", "fixture_manifest_sha256", "qrels_sha256"):
        val = data.get(sha_field, "")
        if not isinstance(val, str) or not HEX_64_RE.match(val):
            raise SchemaValidationError(f"manifest: Invalid {sha_field}: {val}")

    # Dataset hash must match frozen benchmark LF SHA256
    from evals.harness.constants import FROZEN_BENCHMARK_LF_SHA256
    if data.get("dataset_sha256") != FROZEN_BENCHMARK_LF_SHA256:
        raise SchemaValidationError(
            f"manifest [H4]: dataset_sha256 mismatch! Got {data.get('dataset_sha256')}, expected frozen LF hash {FROZEN_BENCHMARK_LF_SHA256}"
        )

    # Artifact files must match exact canonical list (including manifest.json, no duplicates, no missing, no extra)
    artifact_files = data.get("artifact_files")
    if not isinstance(artifact_files, list):
        raise SchemaValidationError("manifest: artifact_files must be a list of filenames")

    if len(artifact_files) != len(set(artifact_files)):
        raise SchemaValidationError("manifest: artifact_files contains duplicate entries")

    expected_canonical_set = set(CANONICAL_ARTIFACT_FILES)
    actual_set = set(artifact_files)

    missing_files = expected_canonical_set - actual_set
    if missing_files:
        raise SchemaValidationError(f"manifest: artifact_files missing canonical files: {sorted(missing_files)}")

    extra_files = actual_set - expected_canonical_set
    if extra_files:
        raise SchemaValidationError(f"manifest: artifact_files contains non-canonical files: {sorted(extra_files)}")

    if len(artifact_files) != len(CANONICAL_ARTIFACT_FILES):
        raise SchemaValidationError(
            f"manifest: artifact_files count {len(artifact_files)} != expected canonical count {len(CANONICAL_ARTIFACT_FILES)}"
        )

    # Unavailable reasons check
    for key in ("model_revision", "tokenizer_revision", "seed"):
        if data.get(key) is None:
            reason_key = f"{key}_unavailable_reason"
            if not data.get(reason_key):
                raise SchemaValidationError(f"manifest: When {key} is null, {reason_key} must be provided")

    # R11 Readiness gate check
    readiness_status = data.get("readiness_status")
    if readiness_status is not None:
        if readiness_status not in VALID_READINESS_STATUSES:
            raise SchemaValidationError(f"manifest: Invalid readiness_status: '{readiness_status}'. Must be one of {sorted(VALID_READINESS_STATUSES)}")
        if readiness_status == STATUS_MEASUREMENT_READY:
            if is_preflight:
                raise SchemaValidationError("manifest [R11]: Preflight bundle cannot declare readiness_status='READY FOR MEASUREMENT'")
            if harness_sha is None or is_placeholder_sha(harness_sha):
                raise SchemaValidationError("manifest [R11]: Cannot declare readiness_status='READY FOR MEASUREMENT' without immutable evaluation_harness_sha")
            provider_id = data.get("provider_id", "")
            lane_id = data.get("lane_id", "")
            if provider_id == "mock" or lane_id.startswith("mock"):
                raise SchemaValidationError(f"manifest [R11]: Mock provider/lane ('{provider_id}'/'{lane_id}') cannot declare readiness_status='READY FOR MEASUREMENT'")
            from evals.harness.gates import assert_gate_readiness
            gate = data.get("gate", "")
            try:
                assert_gate_readiness(gate, readiness_status)
            except Exception as exc:
                raise SchemaValidationError(f"manifest [R11]: {exc}")

    benchmark_id = data.get("benchmark_id")
    if benchmark_id is not None and (not isinstance(benchmark_id, str) or not benchmark_id.strip()):
        raise SchemaValidationError("manifest: benchmark_id must be a non-empty string when provided")

    case_count = data.get("case_count")
    if case_count is not None and (type(case_count) is not int or case_count < 0):
        raise SchemaValidationError("manifest: case_count must be an integer >= 0 when provided")


def validate_attempt_record(record: Dict[str, Any]) -> None:
    """Validates an attempts.jsonl line record according to R10 fail-closed contracts."""
    if record.get("schema_version") != SCHEMA_VERSION_ATTEMPT:
        raise SchemaValidationError(f"attempt: Invalid schema_version: {record.get('schema_version')}")

    validate_common_envelope(record, "attempt")

    required = (
        "attempt_id", "retry_index", "attempt_class", "started_at_utc",
        "finished_at_utc", "http_status", "outcome", "response", "trace"
    )
    missing = [f for f in required if f not in record]
    if missing:
        raise SchemaValidationError(f"attempt: Missing required fields: {missing}")

    attempt_id = record.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise SchemaValidationError("attempt: attempt_id must be a non-empty string")

    finished_at = record.get("finished_at_utc")
    if finished_at is not None and (not isinstance(finished_at, str) or not finished_at.strip()):
        raise SchemaValidationError("attempt: finished_at_utc must be a non-empty string or null")

    outcome = record.get("outcome")

    response_val = record.get("response")
    if response_val is not None and not isinstance(response_val, dict):
        raise SchemaValidationError("attempt: response must be a dictionary or null")
    if isinstance(response_val, dict):
        if "text" in response_val:
            if outcome == "completed" and response_val.get("text") is None:
                raise SchemaValidationError("attempt: response.text cannot be null when outcome='completed'")
            if response_val["text"] is not None and not isinstance(response_val["text"], str):
                raise SchemaValidationError("attempt: response.text must be a string or null")
        if "sources" in response_val and response_val["sources"] is not None and not isinstance(response_val["sources"], list):
            raise SchemaValidationError("attempt: response.sources must be a list or null")

    retry_index = record.get("retry_index")
    if type(retry_index) is not int or retry_index < 0:
        raise SchemaValidationError("attempt: retry_index must be an integer >= 0")

    attempt_class = record.get("attempt_class")
    if attempt_class not in VALID_ATTEMPT_CLASSES:
        raise SchemaValidationError(f"attempt: Invalid attempt_class: {attempt_class}")

    if retry_index == 0 and attempt_class not in ("first", "diagnostic_rerun"):
        raise SchemaValidationError("attempt: retry_index 0 must have attempt_class='first' (or 'diagnostic_rerun')")
    if retry_index > 0 and attempt_class == "first":
        raise SchemaValidationError("attempt: retry_index > 0 cannot have attempt_class='first'")

    http_status = record.get("http_status")
    if type(http_status) is not int or http_status < 100 or http_status > 599:
        raise SchemaValidationError(f"attempt: Invalid http_status: {http_status}")

    outcome = record.get("outcome")
    if outcome not in VALID_ATTEMPT_OUTCOMES:
        raise SchemaValidationError(f"attempt: Invalid outcome: {outcome}")

    # Trace & R10 Measured Zero Validation (Fail-closed)
    trace = record.get("trace")
    if not isinstance(trace, dict):
        raise SchemaValidationError("attempt: 'trace' must be a dictionary")
    if not trace:
        raise SchemaValidationError("attempt [R10]: 'trace' must not be empty")

    inv_observed = trace.get("model_invocation_observed")
    if type(inv_observed) is not bool:
        raise SchemaValidationError(
            f"attempt [R10]: 'trace.model_invocation_observed' must be a strict boolean (True or False), got {type(inv_observed).__name__}"
        )

    model_calls = trace.get("model_calls")
    provider_ms = trace.get("provider_inference_ms")
    zero_reason = trace.get("zero_reason")
    unavailable_reason = trace.get("unavailable_reason")

    # Strict type & range validation for model_calls
    if model_calls is not None:
        if type(model_calls) is not int:
            raise SchemaValidationError(
                f"attempt [R10]: 'trace.model_calls' must be an integer, got {type(model_calls).__name__}"
            )
        if model_calls < 0:
            raise SchemaValidationError(
                f"attempt [R10]: 'trace.model_calls' must be non-negative, got {model_calls}"
            )

    # Strict type & range validation for provider_inference_ms
    if provider_ms is not None:
        if type(provider_ms) not in (int, float) or type(provider_ms) is bool or not math.isfinite(provider_ms):
            raise SchemaValidationError(
                f"attempt [R10]: 'trace.provider_inference_ms' must be a finite float or int, got {provider_ms}"
            )
        if provider_ms < 0.0:
            raise SchemaValidationError(
                f"attempt [R10]: 'trace.provider_inference_ms' must be non-negative, got {provider_ms}"
            )

    # When model invocation WAS observed:
    if inv_observed is True:
        if model_calls is None:
            raise SchemaValidationError(
                "attempt [R10]: When model_invocation_observed=True, 'trace.model_calls' cannot be null"
            )
        if provider_ms is None:
            raise SchemaValidationError(
                "attempt [R10]: When model_invocation_observed=True, 'trace.provider_inference_ms' cannot be null"
            )

        if model_calls == 0:
            if provider_ms != 0.0:
                raise SchemaValidationError(
                    f"attempt [R10]: model_calls=0 requires provider_inference_ms=0.0 (got {provider_ms})"
                )
            if zero_reason not in VALID_ZERO_REASONS:
                raise SchemaValidationError(
                    f"attempt [R10]: model_calls=0 requires trace.zero_reason in {VALID_ZERO_REASONS}, got '{zero_reason}'"
                )
            if unavailable_reason is not None:
                raise SchemaValidationError(
                    "attempt [R10]: Measured zero cannot have unavailable_reason"
                )
        else:
            # model_calls > 0
            if provider_ms == 0.0:
                raise SchemaValidationError(
                    f"attempt [R10]: provider_inference_ms cannot be 0.0 when model_calls > 0 ({model_calls} calls observed)"
                )
            if zero_reason is not None:
                raise SchemaValidationError(
                    f"attempt [R10]: zero_reason must be null when model_calls > 0, got '{zero_reason}'"
                )

    # When model invocation was NOT observed (missing telemetry / unobserved):
    else:
        if model_calls is not None:
            raise SchemaValidationError(
                f"attempt [R10]: When model_invocation_observed=False, model_calls must be null (cannot claim {model_calls})"
            )
        if provider_ms is not None:
            raise SchemaValidationError(
                f"attempt [R10]: When model_invocation_observed=False, provider_inference_ms must be null (cannot claim {provider_ms})"
            )
        if zero_reason is not None:
            raise SchemaValidationError(
                f"attempt [R10]: When model_invocation_observed=False, zero_reason must be null (got '{zero_reason}')"
            )
        if not isinstance(unavailable_reason, str) or not unavailable_reason.strip():
            raise SchemaValidationError(
                "attempt [R10]: When model_invocation_observed=False, 'trace.unavailable_reason' must be a non-empty string"
            )

    # N4: tools_called validation
    if "tools_called" in trace:
        tools_called = trace["tools_called"]
        if not isinstance(tools_called, list):
            raise SchemaValidationError("attempt [N4]: 'trace.tools_called' must be a list of strings")
        for idx, t in enumerate(tools_called):
            if not isinstance(t, str) or not t.strip():
                raise SchemaValidationError(f"attempt [N4]: 'trace.tools_called[{idx}]' must be a non-empty string")

    # N4: tool_calls or tool_count validation
    for tc_key in ("tool_calls", "tool_count"):
        if tc_key in trace and trace[tc_key] is not None:
            if type(trace[tc_key]) is not int or trace[tc_key] < 0:
                raise SchemaValidationError(f"attempt [N4]: 'trace.{tc_key}' must be a non-negative integer")

    # N4: Safety flags strict bool validation
    for flag in ("privacy_leak", "prompt_injection", "unauthorized_mutation", "fabricated_source", "ownership_bypass", "unsupported_claim"):
        if flag in trace and trace[flag] is not None:
            if type(trace[flag]) is not bool:
                raise SchemaValidationError(f"attempt [N4]: 'trace.{flag}' must be a strict boolean (True or False), got {type(trace[flag]).__name__}")


def validate_grading_record(record: Dict[str, Any]) -> None:
    """Validates a grading.jsonl line record."""
    if record.get("schema_version") != SCHEMA_VERSION_GRADING:
        raise SchemaValidationError(f"grading: Invalid schema_version: {record.get('schema_version')}")

    validate_common_envelope(record, "grading")

    required = (
        "graded_attempt_id", "grading_id", "grader_version", "rubric_version",
        "decision", "first_attempt", "claim_judgments", "evidence_refs", "adjudicated"
    )
    missing = [f for f in required if f not in record]
    if missing:
        raise SchemaValidationError(f"grading: Missing required fields: {missing}")

    if not isinstance(record.get("graded_attempt_id"), str) or not record["graded_attempt_id"].strip():
        raise SchemaValidationError("grading: graded_attempt_id must be a non-empty string")

    if not isinstance(record.get("grading_id"), str) or not record["grading_id"].strip():
        raise SchemaValidationError("grading: grading_id must be a non-empty string")

    decision = record.get("decision")
    if decision not in VALID_DECISIONS:
        raise SchemaValidationError(f"grading: Invalid decision: {decision}")

    if not isinstance(record.get("first_attempt"), bool):
        raise SchemaValidationError("grading: first_attempt must be a boolean")

    if not isinstance(record.get("claim_judgments"), list):
        raise SchemaValidationError("grading: claim_judgments must be a list")

    evidence_refs = record.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        raise SchemaValidationError("grading: evidence_refs must be a list")
    if len(evidence_refs) == 0:
        raise SchemaValidationError("grading: evidence_refs must be a non-empty list of record IDs")
    for ref in evidence_refs:
        if not isinstance(ref, str) or not ref.strip():
            raise SchemaValidationError("grading: each evidence_ref must be a non-empty string")

    if not isinstance(record.get("adjudicated"), bool):
        raise SchemaValidationError("grading: adjudicated must be a boolean")

    answerability = record.get("answerability_status")
    if answerability and answerability not in VALID_ANSWERABILITY_STATUSES:
        raise SchemaValidationError(f"grading: Invalid answerability_status: {answerability}")

    severity = record.get("severity")
    if severity is not None and severity not in VALID_SEVERITIES:
        raise SchemaValidationError(f"grading: Invalid severity: {severity}")

    primary_fail = record.get("primary_failure")
    if primary_fail is not None and primary_fail not in VALID_TAXONOMY_CODES:
        raise SchemaValidationError(f"grading: Invalid primary_failure code: {primary_fail}")

    secondary_fails = record.get("secondary_failures", [])
    if not isinstance(secondary_fails, list):
        raise SchemaValidationError("grading: secondary_failures must be a list")
    for sec in secondary_fails:
        if sec not in VALID_TAXONOMY_CODES:
            raise SchemaValidationError(f"grading: Invalid secondary_failure code: {sec}")


def validate_retrieval_record(record: Dict[str, Any]) -> None:
    """Validates a retrieval.jsonl line record."""
    if record.get("schema_version") != SCHEMA_VERSION_RETRIEVAL:
        raise SchemaValidationError(f"retrieval: Invalid schema_version: {record.get('schema_version')}")

    validate_common_envelope(record, "retrieval")

    required = (
        "attempt_id", "retrieval_event_id", "query_id", "stage",
        "candidate_chunks", "served_chunks", "qrels_version",
        "qrels_source", "qrels_sha256"
    )
    missing = [f for f in required if f not in record]
    if missing:
        raise SchemaValidationError(f"retrieval: Missing required fields: {missing}")

    for id_field in ("attempt_id", "retrieval_event_id", "query_id", "stage", "qrels_version", "qrels_source"):
        val = record.get(id_field)
        if not isinstance(val, str) or not val.strip():
            raise SchemaValidationError(f"retrieval: Field '{id_field}' must be a non-empty string")

    for list_field in ("candidate_chunks", "served_chunks"):
        chunk_list = record.get(list_field)
        if not isinstance(chunk_list, list):
            raise SchemaValidationError(f"retrieval: Field '{list_field}' must be a list")
        for c_idx, chunk in enumerate(chunk_list):
            if not isinstance(chunk, dict):
                raise SchemaValidationError(f"retrieval: {list_field}[{c_idx}] must be a dict")
            for chk_key in ("chunk_id", "rank", "score", "source_id"):
                if chk_key not in chunk:
                    raise SchemaValidationError(f"retrieval: {list_field}[{c_idx}] missing required chunk key '{chk_key}'")
            if not isinstance(chunk["chunk_id"], str) or not chunk["chunk_id"].strip():
                raise SchemaValidationError(f"retrieval: {list_field}[{c_idx}] chunk_id must be non-empty string")
            if type(chunk["rank"]) is not int or chunk["rank"] < 1:
                raise SchemaValidationError(f"retrieval: {list_field}[{c_idx}] rank must be an integer >= 1")
            if type(chunk["score"]) not in (int, float) or type(chunk["score"]) is bool or not math.isfinite(chunk["score"]):
                raise SchemaValidationError(f"retrieval: {list_field}[{c_idx}] score must be a finite float or int")
            if not isinstance(chunk["source_id"], str) or not chunk["source_id"].strip():
                raise SchemaValidationError(f"retrieval: {list_field}[{c_idx}] source_id must be non-empty string")

    answerability = record.get("answerability_status")
    if answerability and answerability not in VALID_ANSWERABILITY_STATUSES:
        raise SchemaValidationError(f"retrieval: Invalid answerability_status: {answerability}")

    qrels_sha = record.get("qrels_sha256")
    if qrels_sha is None or not isinstance(qrels_sha, str) or not HEX_64_RE.match(qrels_sha):
        raise SchemaValidationError(f"retrieval: Invalid qrels_sha256: {qrels_sha}")


def validate_error_record(record: Dict[str, Any]) -> None:
    """Validates an errors.jsonl line record."""
    if record.get("schema_version") != SCHEMA_VERSION_ERROR:
        raise SchemaValidationError(f"error: Invalid schema_version: {record.get('schema_version')}")

    validate_common_envelope(record, "error")

    required = (
        "attempt_id", "error_id", "stage", "taxonomy_code",
        "severity", "retryable", "http_status", "message_redacted"
    )
    missing = [f for f in required if f not in record]
    if missing:
        raise SchemaValidationError(f"error: Missing required fields: {missing}")

    msg = record.get("message_redacted")
    if not isinstance(msg, str) or not msg.strip():
        raise SchemaValidationError("error: message_redacted must be a non-empty string")

    leak_patterns = [
        re.compile(r"bearer\s+[A-Za-z0-9_\-\.]{10,}", re.IGNORECASE),
        re.compile(r"(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}", re.IGNORECASE),
        re.compile(r"sk-[A-Za-z0-9]{20,}", re.IGNORECASE),
        re.compile(r"password\s*[:=]\s*['\"]?\S+['\"]?", re.IGNORECASE),
        re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----", re.IGNORECASE),
    ]
    # Strip legitimate redaction markers before checking for credential leaks
    sanitized_msg = re.sub(r"\[(?:REDACTED|FILTERED)\]|<redacted>|\*{3,}", "", msg, flags=re.IGNORECASE)
    for pat in leak_patterns:
        if pat.search(sanitized_msg):
            raise SchemaValidationError("error: message_redacted contains sensitive unredacted credential pattern")

    taxonomy_code = record.get("taxonomy_code")
    if taxonomy_code not in VALID_TAXONOMY_CODES:
        raise SchemaValidationError(f"error: Invalid taxonomy_code: {taxonomy_code}")

    severity = record.get("severity")
    if severity not in VALID_SEVERITIES:
        raise SchemaValidationError(f"error: Invalid severity: {severity}")

    if not isinstance(record.get("retryable"), bool):
        raise SchemaValidationError("error: retryable must be a boolean")

    http_status = record.get("http_status")
    if not isinstance(http_status, int) or http_status < 100 or http_status > 599:
        raise SchemaValidationError(f"error: Invalid http_status: {http_status}")


def validate_aggregate(data: Dict[str, Any]) -> None:
    """Validates aggregate.json structure."""
    if data.get("schema_version") != SCHEMA_VERSION_AGGREGATE:
        raise SchemaValidationError(f"aggregate: Invalid schema_version: {data.get('schema_version')}")

    required = (
        "run_id", "logical_cases", "n_total", "n_attempt", "n_graded", "n_blocked",
        "first_attempt_outcomes", "eventual_outcomes", "quality_conditional",
        "e2e_success", "derived_from", "artifact_checksums"
    )
    missing = [f for f in required if f not in data]
    if missing:
        raise SchemaValidationError(f"aggregate: Missing required fields: {missing}")

    for count_key in ("logical_cases", "n_total", "n_attempt", "n_graded", "n_blocked"):
        val = data.get(count_key)
        if not isinstance(val, int) or val < 0:
            raise SchemaValidationError(f"aggregate: {count_key} must be an integer >= 0")

    for ratio_key in ("quality_conditional", "e2e_success"):
        ratio = data.get(ratio_key)
        if not isinstance(ratio, dict) or "numerator" not in ratio or "denominator" not in ratio:
            raise SchemaValidationError(f"aggregate: {ratio_key} must be dict with numerator and denominator")
        num = ratio.get("numerator")
        denom = ratio.get("denominator")
        if type(num) is not int or type(denom) is not int or num < 0 or denom < 0:
            raise SchemaValidationError(f"aggregate: {ratio_key} numerator and denominator must be non-negative integers")
        if denom > 0 and num > denom:
            raise SchemaValidationError(f"aggregate: {ratio_key} numerator {num} cannot exceed denominator {denom}")
        rate = ratio.get("rate")
        if rate is not None:
            if type(rate) not in (int, float) or type(rate) is bool or not math.isfinite(rate):
                raise SchemaValidationError(f"aggregate: {ratio_key} rate must be a finite float or int")
            if rate < 0.0 or rate > 1.0:
                raise SchemaValidationError(f"aggregate: {ratio_key} rate {rate} must be between 0.0 and 1.0")

    for rate_key in ("first_attempt_success_rate", "eventual_success_rate"):
        rate = data.get(rate_key)
        if rate is not None:
            if type(rate) not in (int, float) or type(rate) is bool or not math.isfinite(rate):
                raise SchemaValidationError(f"aggregate: {rate_key} must be a finite float or int")
            if rate < 0.0 or rate > 1.0:
                raise SchemaValidationError(f"aggregate: {rate_key} {rate} must be between 0.0 and 1.0")

    rec_rate = data.get("retry_recovery_rate")
    if rec_rate is not None:
        if type(rec_rate) not in (int, float) or type(rec_rate) is bool or not math.isfinite(rec_rate):
            raise SchemaValidationError("aggregate: retry_recovery_rate must be a finite float or int")
        if rec_rate < 0.0 or rec_rate > 1.0:
            raise SchemaValidationError(f"aggregate: retry_recovery_rate {rec_rate} must be between 0.0 and 1.0")

    missing_gr = data.get("n_missing_grading")
    if missing_gr is not None:
        if type(missing_gr) is not int or missing_gr < 0:
            raise SchemaValidationError(f"aggregate: n_missing_grading must be a non-negative integer, got {missing_gr}")

    completeness = data.get("completeness")
    if completeness is not None:
        if type(completeness) not in (int, float) or type(completeness) is bool or not math.isfinite(completeness):
            raise SchemaValidationError("aggregate: completeness must be a finite float or int")
        if completeness < 0.0 or completeness > 1.0:
            raise SchemaValidationError(f"aggregate: completeness {completeness} must be between 0.0 and 1.0")

    derived_from = data.get("derived_from")
    if not isinstance(derived_from, list) or len(derived_from) == 0:
        raise SchemaValidationError("aggregate: derived_from must be a non-empty list of source files")
    for df in derived_from:
        if not isinstance(df, str) or not df.strip():
            raise SchemaValidationError("aggregate: each entry in derived_from must be a non-empty string")

    artifact_checksums = data.get("artifact_checksums")
    if not isinstance(artifact_checksums, str) or not artifact_checksums.strip():
        raise SchemaValidationError("aggregate: artifact_checksums must be a non-empty string")
