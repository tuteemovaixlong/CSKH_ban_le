"""Validation and dataclasses for Phase 4 schemas.

Normative reference:
- docs/phase4/PHASE_4_RESULTS_SCHEMA.md
- docs/phase4/PHASE_4_FAILURE_TAXONOMY.md
- docs/phase4/PHASE_4_METRICS_DEFINITION.md
"""

from typing import Any, Dict, List, Optional
import re

from evals.harness.constants import (
    COMMON_ENVELOPE_FIELDS,
    PROTOCOL_VERSION,
    SCHEMA_VERSION_AGGREGATE,
    SCHEMA_VERSION_ATTEMPT,
    SCHEMA_VERSION_ERROR,
    SCHEMA_VERSION_GRADING,
    SCHEMA_VERSION_MANIFEST,
    SCHEMA_VERSION_RETRIEVAL,
    VALID_ANSWERABILITY_STATUSES,
    VALID_ATTEMPT_CLASSES,
    VALID_ATTEMPT_OUTCOMES,
    VALID_DECISIONS,
    VALID_SEVERITIES,
    VALID_TAXONOMY_CODES,
    VALID_ZERO_REASONS,
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
    if harness_sha is not None and not HEX_40_RE.match(harness_sha):
        raise SchemaValidationError(f"[{record_type}] Invalid evaluation_harness_sha: {harness_sha}")

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
    """Validates manifest.json structure."""
    if data.get("schema_version") != SCHEMA_VERSION_MANIFEST:
        raise SchemaValidationError(f"manifest: Invalid schema_version: {data.get('schema_version')}")

    required_fields = (
        "run_id", "lane_id", "system_commit_sha", "evaluation_harness_sha",
        "evaluation_overlay_sha256", "config_sha256", "dataset_sha256",
        "artifact_files"
    )
    missing = [f for f in required_fields if f not in data]
    if missing:
        raise SchemaValidationError(f"manifest: Missing required fields: {missing}")

    # Validate commit SHAs
    sys_sha = data.get("system_commit_sha", "")
    if not HEX_40_RE.match(sys_sha):
        raise SchemaValidationError(f"manifest: Invalid system_commit_sha: {sys_sha}")

    harness_sha = data.get("evaluation_harness_sha")
    if harness_sha is not None and not HEX_40_RE.match(harness_sha):
        raise SchemaValidationError(f"manifest: Invalid evaluation_harness_sha: {harness_sha}")

    for sha_field in ("config_sha256", "dataset_sha256"):
        val = data.get(sha_field, "")
        if not HEX_64_RE.match(val):
            raise SchemaValidationError(f"manifest: Invalid {sha_field}: {val}")

    if not isinstance(data.get("artifact_files"), list):
        raise SchemaValidationError("manifest: artifact_files must be a list of filenames")

    # Unavailable reasons check
    for key in ("model_revision", "tokenizer_revision", "seed"):
        if data.get(key) is None:
            reason_key = f"{key}_unavailable_reason"
            if not data.get(reason_key):
                raise SchemaValidationError(f"manifest: When {key} is null, {reason_key} must be provided")


def validate_attempt_record(record: Dict[str, Any]) -> None:
    """Validates an attempts.jsonl line record according to R10 and phase4-attempt-v1."""
    if record.get("schema_version") != SCHEMA_VERSION_ATTEMPT:
        raise SchemaValidationError(f"attempt: Invalid schema_version: {record.get('schema_version')}")

    validate_common_envelope(record, "attempt")

    required = ("attempt_id", "retry_index", "attempt_class", "started_at_utc", "http_status", "outcome", "trace")
    missing = [f for f in required if f not in record]
    if missing:
        raise SchemaValidationError(f"attempt: Missing required fields: {missing}")

    attempt_id = record.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise SchemaValidationError("attempt: attempt_id must be a non-empty string")

    retry_index = record.get("retry_index")
    if not isinstance(retry_index, int) or retry_index < 0:
        raise SchemaValidationError("attempt: retry_index must be an integer >= 0")

    attempt_class = record.get("attempt_class")
    if attempt_class not in VALID_ATTEMPT_CLASSES:
        raise SchemaValidationError(f"attempt: Invalid attempt_class: {attempt_class}")

    if retry_index == 0 and attempt_class not in ("first", "diagnostic_rerun"):
        raise SchemaValidationError("attempt: retry_index 0 must have attempt_class='first' (or 'diagnostic_rerun')")
    if retry_index > 0 and attempt_class == "first":
        raise SchemaValidationError("attempt: retry_index > 0 cannot have attempt_class='first'")

    http_status = record.get("http_status")
    if not isinstance(http_status, int) or http_status < 100 or http_status > 599:
        raise SchemaValidationError(f"attempt: Invalid http_status: {http_status}")

    outcome = record.get("outcome")
    if outcome not in VALID_ATTEMPT_OUTCOMES:
        raise SchemaValidationError(f"attempt: Invalid outcome: {outcome}")

    # Trace & R10 Measured Zero Validation
    trace = record.get("trace")
    if not isinstance(trace, dict):
        raise SchemaValidationError("attempt: 'trace' must be a dictionary")

    model_calls = trace.get("model_calls")
    provider_ms = trace.get("provider_inference_ms")
    inv_observed = trace.get("model_invocation_observed")
    zero_reason = trace.get("zero_reason")

    # R10 validation:
    # 1. model_calls == 0
    if model_calls == 0:
        if inv_observed is not True:
            raise SchemaValidationError(
                "attempt [R10]: model_calls=0 requires trace.model_invocation_observed=True (fabricated zero rejected)"
            )
        if zero_reason not in VALID_ZERO_REASONS:
            raise SchemaValidationError(
                f"attempt [R10]: model_calls=0 requires trace.zero_reason in {VALID_ZERO_REASONS}, got {zero_reason}"
            )

    # 2. provider_inference_ms == 0.0
    if provider_ms == 0.0:
        if inv_observed is not True:
            raise SchemaValidationError(
                "attempt [R10]: provider_inference_ms=0.0 requires trace.model_invocation_observed=True (fabricated zero rejected)"
            )
        if model_calls is not None and model_calls > 0:
            raise SchemaValidationError(
                "attempt [R10]: provider_inference_ms cannot be 0.0 when model_calls > 0"
            )

    # 3. If unobserved, must not claim 0
    if inv_observed is False:
        if model_calls == 0:
            raise SchemaValidationError("attempt [R10]: Unobserved invocation cannot claim model_calls=0")
        if provider_ms == 0.0:
            raise SchemaValidationError("attempt [R10]: Unobserved invocation cannot claim provider_inference_ms=0.0")


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

    if not isinstance(record.get("evidence_refs"), list):
        raise SchemaValidationError("grading: evidence_refs must be a list")

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
        "candidate_chunks", "served_chunks", "qrels_version"
    )
    missing = [f for f in required if f not in record]
    if missing:
        raise SchemaValidationError(f"retrieval: Missing required fields: {missing}")

    for id_field in ("attempt_id", "retrieval_event_id", "query_id", "stage", "qrels_version"):
        val = record.get(id_field)
        if not isinstance(val, str) or not val.strip():
            raise SchemaValidationError(f"retrieval: Field '{id_field}' must be a non-empty string")

    for list_field in ("candidate_chunks", "served_chunks"):
        if not isinstance(record.get(list_field), list):
            raise SchemaValidationError(f"retrieval: Field '{list_field}' must be a list")

    answerability = record.get("answerability_status")
    if answerability and answerability not in VALID_ANSWERABILITY_STATUSES:
        raise SchemaValidationError(f"retrieval: Invalid answerability_status: {answerability}")


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
