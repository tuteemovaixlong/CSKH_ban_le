"""Constants and enums for Phase 4 Scientific Evaluation Harness.

Normative reference:
- docs/phase4/PHASE_4_RESULTS_SCHEMA.md
- docs/phase4/PHASE_4_FAILURE_TAXONOMY.md
- docs/phase4/PHASE_4_METRICS_DEFINITION.md
"""

from typing import Optional, Set

PROTOCOL_VERSION = "p4-v1"
SCHEMA_VERSION_MANIFEST = "phase4-manifest-v1"
SCHEMA_VERSION_ATTEMPT = "phase4-attempt-v1"
SCHEMA_VERSION_GRADING = "phase4-grading-v1"
SCHEMA_VERSION_RETRIEVAL = "phase4-retrieval-v1"
SCHEMA_VERSION_ERROR = "phase4-error-v1"
SCHEMA_VERSION_AGGREGATE = "phase4-aggregate-v1"

CANONICAL_ARTIFACT_FILES = (
    "manifest.json",
    "attempts.jsonl",
    "grading.jsonl",
    "retrieval.jsonl",
    "errors.jsonl",
    "aggregate.json",
    "checksums.sha256",
)

SYSTEM_BASELINE_COMMIT_SHA = "49671b928ad6badfaa01331174eb73f0e366752e"
FROZEN_BENCHMARK_LF_SHA256 = "36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411"
CANONICAL_QRELS_SHA256 = "769a45d682648290a3356dad32aacae3c62f6942b62844dd4cc50f2d83c15161"
CANONICAL_BENCHMARK_250_SIDECAR_SHA256 = "69e9835d3f4c63a2466d6ab08749737dcf59de65f2c22713372bd66b19bb3f2d"

COMMON_ENVELOPE_FIELDS = (
    "schema_version",
    "record_id",
    "run_id",
    "case_id",
    "logical_request_id",
    "system_commit_sha",
    "evaluation_harness_sha",
    "evaluation_overlay_sha256",
    "protocol_version",
    "config_sha256",
    "fixture_manifest_sha256",
    "created_at_utc",
)

COMMON_PROVENANCE_FIELDS = (
    "run_id",
    "system_commit_sha",
    "evaluation_harness_sha",
    "evaluation_overlay_sha256",
    "protocol_version",
    "config_sha256",
    "fixture_manifest_sha256",
)

STATUS_PREFLIGHT = "READY FOR HARNESS/PREFLIGHT"
STATUS_MEASUREMENT_READY = "READY FOR MEASUREMENT"
VALID_READINESS_STATUSES: Set[str] = {STATUS_PREFLIGHT, STATUS_MEASUREMENT_READY}

VALID_SEVERITIES: Set[str] = {"S0", "S1", "S2", "S3"}

# R10 Measured Zero reasons
VALID_ZERO_REASONS: Set[str] = {
    "refusal",
    "direct_response",
    "human_handoff",
    "replay",
    "cache_hit",
}

VALID_DECISIONS: Set[str] = {
    "pass",
    "partial",
    "fail",
    "abstain_correct",
    "abstain_incorrect",
    "blocked_environment",
    "inconclusive",
    "rejected",
}

QUALITY_ELIGIBLE_DECISIONS: Set[str] = {
    "pass",
    "partial",
    "fail",
    "abstain_correct",
    "abstain_incorrect",
    "rejected",
}

VALID_ANSWERABILITY_STATUSES: Set[str] = {
    "answerable",
    "labeled-unanswerable",
    "annotation-missing",
    "not-applicable",
}

VALID_ATTEMPT_CLASSES: Set[str] = {
    "first",
    "transport_retry",
    "diagnostic_rerun",
}

VALID_ATTEMPT_OUTCOMES: Set[str] = {
    "completed",
    "transport_error",
    "timeout",
    "admission_429",
    "model_429",
    "provider_error",
    "refusal",
    "handoff",
}

VALID_TAXONOMY_CODES: Set[str] = {
    # Routing
    "ROUTE_WRONG_MODE",
    "ROUTE_WRONG_WORKER",
    "ROUTE_MISSED_MULTI_INTENT",
    "ROUTE_NO_CLARIFY",
    "ROUTE_OVERCONFIDENT",
    # Retrieval
    "RETRIEVAL_MISS",
    "RETRIEVAL_WRONG_SCOPE",
    "RETRIEVAL_RANKING",
    "RETRIEVAL_CHUNKING",
    "RETRIEVAL_EMPTY",
    # Grounding
    "GROUNDING_UNSUPPORTED_CLAIM",
    "GROUNDING_CITATION_MISMATCH",
    "GROUNDING_POLICY_CONFLICT",
    "GROUNDING_FABRICATED_SOURCE",
    # Tool
    "TOOL_MISSING_REQUIRED",
    "TOOL_FORBIDDEN_CALLED",
    "TOOL_BAD_ARGUMENT",
    "TOOL_OWNERSHIP_BYPASS",
    "TOOL_STALE_STATE",
    "TOOL_SIDE_EFFECT_UNCONFIRMED",
    "TOOL_RESULT_MISREAD",
    # Data/identity
    "IDENTITY_UNBOUND",
    "IDENTITY_COLLISION",
    "DATA_STALE",
    "DATA_IMPORT_SCHEMA",
    "DATA_IMPORT_DUPLICATE",
    "DATA_IMPORT_PARTIAL",
    # Workflow/policy
    "WORKFLOW_NO_HANDOFF",
    "WORKFLOW_NO_CONFIRMATION",
    "WORKFLOW_HISTORY_LOSS",
    "WORKFLOW_SUMMARY_DRIFT",
    "WORKFLOW_LOOP_BUDGET",
    # Generation
    "GEN_UNCLEAR",
    "GEN_LANGUAGE",
    "GEN_CONTRADICTION",
    # Safety
    "SAFETY_PRIVACY_LEAK",
    "SAFETY_PROMPT_INJECTION",
    "SAFETY_UNAUTHORIZED_MUTATION",
    # Infra/provider
    "INFRA_TIMEOUT",
    "INFRA_429_ADMISSION",
    "INFRA_429_MODEL",
    "INFRA_PROVIDER_ERROR",
    "INFRA_DB_ERROR",
    "INFRA_CACHE_CORRUPTION",
    # Observability
    "OBS_MISSING_TRACE",
    "OBS_FALSE_TELEMETRY",
    "UNOBSERVED_TRACE",
    # Harness/grader
    "HARNESS_FIXTURE_MISSING",
    "HARNESS_IDENTITY_MISMATCH",
    "GRADER_CONTRACT_ERROR",
    # Retrieval labels
    "QRELS_MISSING",
    "QRELS_AMBIGUOUS",
    # Artifact/schema
    "ARTIFACT_SCHEMA_INVALID",
    "ARTIFACT_INCOMPLETE",
    # Budget/quota
    "INFRA_APP_QUOTA",
    "INFRA_BUDGET_CAP",
    # Reproducibility
    "REPRO_DRIFT",
    "REPRO_INCOMPLETE",
}

# Safety Veto Codes
SAFETY_HARD_VETO_CODES: Set[str] = {
    "TOOL_FORBIDDEN_CALLED",
    "TOOL_OWNERSHIP_BYPASS",
    "SAFETY_PRIVACY_LEAK",
    "SAFETY_PROMPT_INJECTION",
    "SAFETY_UNAUTHORIZED_MUTATION",
    "GROUNDING_FABRICATED_SOURCE",
    "IDENTITY_COLLISION",
}

DISALLOWED_HARNESS_PLACEHOLDER_SHAS: Set[str] = {
    "0" * 40,
    "1" * 40,
    "2" * 40,
    "a" * 40,
    "f" * 40,
    "1234567890123456789012345678901234567890",
}


def is_placeholder_sha(sha: Optional[str]) -> bool:
    """Returns True if the given SHA is a disallowed dummy or placeholder SHA."""
    if not sha or not isinstance(sha, str):
        return False
    s = sha.strip().lower()
    if len(s) == 40 and len(set(s)) == 1:
        return True
    if s in DISALLOWED_HARNESS_PLACEHOLDER_SHAS:
        return True
    return False
