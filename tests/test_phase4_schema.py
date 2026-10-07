"""Tests for Phase 4 schema validation, common envelope, and R10 measured zero rules."""

import unittest

from evals.harness.constants import (
    CANONICAL_ARTIFACT_FILES,
    FROZEN_BENCHMARK_LF_SHA256,
    PROTOCOL_VERSION,
    SCHEMA_VERSION_AGGREGATE,
    SCHEMA_VERSION_ATTEMPT,
    SCHEMA_VERSION_ERROR,
    SCHEMA_VERSION_GRADING,
    SCHEMA_VERSION_MANIFEST,
    SCHEMA_VERSION_RETRIEVAL,
    SYSTEM_BASELINE_COMMIT_SHA,
)
from evals.harness.schema import (
    SchemaValidationError,
    validate_aggregate,
    validate_attempt_record,
    validate_common_envelope,
    validate_error_record,
    validate_grading_record,
    validate_manifest,
    validate_retrieval_record,
)


class TestPhase4Schema(unittest.TestCase):

    def setUp(self):
        self.common_envelope = {
            "schema_version": SCHEMA_VERSION_ATTEMPT,
            "record_id": "rec-001",
            "run_id": "run-test-01",
            "case_id": "ro_s1_001",
            "logical_request_id": "req-001",
            "system_commit_sha": SYSTEM_BASELINE_COMMIT_SHA,
            "evaluation_harness_sha": "1" * 40,
            "evaluation_overlay_sha256": "none",
            "protocol_version": PROTOCOL_VERSION,
            "config_sha256": "a" * 64,
            "fixture_manifest_sha256": "b" * 64,
            "created_at_utc": "2026-10-06T00:00:00Z",
        }

    def test_common_envelope_validation(self):
        # Valid envelope
        validate_common_envelope(self.common_envelope, "test")

        # Missing field
        bad_env = dict(self.common_envelope)
        del bad_env["system_commit_sha"]
        with self.assertRaises(SchemaValidationError):
            validate_common_envelope(bad_env, "test")

        # Invalid system commit sha length
        bad_sha = dict(self.common_envelope, system_commit_sha="invalid_sha")
        with self.assertRaises(SchemaValidationError):
            validate_common_envelope(bad_sha, "test")

    def test_manifest_validation(self):
        valid_manifest = {
            "schema_version": SCHEMA_VERSION_MANIFEST,
            "protocol_version": PROTOCOL_VERSION,
            "run_id": "run-test-01",
            "lane_id": "mock-a0",
            "provider_id": "mock",
            "cache_mode": "answer_cache_off",
            "retry_policy_id": "mock_retry_v1",
            "load_profile_id": "mock_single_worker",
            "system_commit_sha": SYSTEM_BASELINE_COMMIT_SHA,
            "evaluation_harness_sha": "1" * 40,
            "evaluation_overlay_sha256": "none",
            "config_sha256": "a" * 64,
            "dataset_sha256": FROZEN_BENCHMARK_LF_SHA256,
            "fixture_manifest_sha256": "b" * 64,
            "qrels_sha256": "c" * 64,
            "created_at_utc": "2026-10-06T00:00:00Z",
            "completed_at_utc": "2026-10-06T00:00:00Z",
            "artifact_files": list(CANONICAL_ARTIFACT_FILES),
            "model_revision": None,
            "model_revision_unavailable_reason": "not_exposed",
            "tokenizer_revision": None,
            "tokenizer_revision_unavailable_reason": "not_exposed",
            "seed": None,
            "seed_unavailable_reason": "deterministic",
        }
        validate_manifest(valid_manifest)

        # Missing unavailable reason when model_revision is None
        bad_manifest = dict(valid_manifest)
        del bad_manifest["model_revision_unavailable_reason"]
        with self.assertRaises(SchemaValidationError):
            validate_manifest(bad_manifest)

    def test_r10_measured_zero_validation(self):
        # Valid observed zero (handoff)
        valid_zero_att = dict(
            self.common_envelope,
            attempt_id="att-01",
            retry_index=0,
            attempt_class="first",
            started_at_utc="2026-10-06T00:00:00Z",
            http_status=200,
            outcome="handoff",
            trace={
                "actual_mode": "retail",
                "model_calls": 0,
                "tool_count": 1,
                "cache_hit": None,
                "provider_inference_ms": 0.0,
                "model_invocation_observed": True,
                "zero_reason": "human_handoff",
            },
        )
        validate_attempt_record(valid_zero_att)

        # Fabricated zero: model_calls=0 but model_invocation_observed=False -> Must fail
        fab_zero_att = dict(valid_zero_att)
        fab_zero_att["trace"] = {
            "model_calls": 0,
            "provider_inference_ms": 0.0,
            "model_invocation_observed": False,
        }
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(fab_zero_att)

        # Fabricated zero: model_calls=0 but missing zero_reason -> Must fail
        no_reason_att = dict(valid_zero_att)
        no_reason_att["trace"] = {
            "model_calls": 0,
            "provider_inference_ms": 0.0,
            "model_invocation_observed": True,
            "zero_reason": None,
        }
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(no_reason_att)

        # Valid unobserved invocation (null + reason)
        unobs_att = dict(valid_zero_att)
        unobs_att["trace"] = {
            "model_calls": None,
            "provider_inference_ms": None,
            "model_invocation_observed": False,
            "unavailable_reason": "telemetry_lost",
        }
        validate_attempt_record(unobs_att)

    def test_grading_record_validation(self):
        valid_grading = dict(
            self.common_envelope,
            schema_version=SCHEMA_VERSION_GRADING,
            graded_attempt_id="att-01",
            grading_id="gr-01",
            grader_version="g-v1",
            rubric_version="rubric-v1",
            decision="pass",
            first_attempt=True,
            claim_judgments=[],
            evidence_refs=["rec-001"],
            adjudicated=False,
            answerability_status="answerable",
            severity=None,
        )
        validate_grading_record(valid_grading)

        # Invalid decision
        bad_dec = dict(valid_grading, decision="unknown_decision")
        with self.assertRaises(SchemaValidationError):
            validate_grading_record(bad_dec)

        # Invalid severity
        bad_sev = dict(valid_grading, severity="S99")
        with self.assertRaises(SchemaValidationError):
            validate_grading_record(bad_sev)

    def test_retrieval_and_error_validation(self):
        valid_retrieval = dict(
            self.common_envelope,
            schema_version=SCHEMA_VERSION_RETRIEVAL,
            attempt_id="att-01",
            retrieval_event_id="rev-01",
            query_id="q-01",
            stage="served",
            candidate_chunks=[],
            served_chunks=[],
            qrels_version="qrels-v1",
            answerability_status="answerable",
        )
        validate_retrieval_record(valid_retrieval)

        valid_error = dict(
            self.common_envelope,
            schema_version=SCHEMA_VERSION_ERROR,
            attempt_id="att-01",
            error_id="err-01",
            stage="admission",
            taxonomy_code="INFRA_429_ADMISSION",
            severity="S2",
            retryable=True,
            http_status=429,
            message_redacted="server_busy",
        )
        validate_error_record(valid_error)

        bad_error = dict(valid_error, taxonomy_code="NON_EXISTENT_CODE")
        with self.assertRaises(SchemaValidationError):
            validate_error_record(bad_error)

    def test_r10_fail_closed_mutations(self):
        """Strict fail-closed checks for R10 probe cases in H2."""
        base_att = dict(
            self.common_envelope,
            attempt_id="att-r10-mut",
            retry_index=0,
            attempt_class="first",
            started_at_utc="2026-10-06T00:00:00Z",
            http_status=200,
            outcome="completed",
        )

        # 1. Empty trace dictionary must fail
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(dict(base_att, trace={}))

        # 2. Negative model_calls must fail
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(dict(base_att, trace={
                "model_invocation_observed": True,
                "model_calls": -1,
                "provider_inference_ms": 100.0,
            }))

        # 3. Negative provider_inference_ms must fail
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(dict(base_att, trace={
                "model_invocation_observed": True,
                "model_calls": 1,
                "provider_inference_ms": -5.0,
            }))

        # 4. Boolean passed for model_calls must fail (strict int check)
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(dict(base_att, trace={
                "model_invocation_observed": True,
                "model_calls": True,  # bool is instance of int in Python!
                "provider_inference_ms": 100.0,
            }))

        # 5. model_calls=0 with provider_inference_ms=None must fail
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(dict(base_att, trace={
                "model_invocation_observed": True,
                "model_calls": 0,
                "provider_inference_ms": None,
                "zero_reason": "refusal",
            }))

        # 6. model_calls=0 with provider_inference_ms > 0 must fail
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(dict(base_att, trace={
                "model_invocation_observed": True,
                "model_calls": 0,
                "provider_inference_ms": 12.5,
                "zero_reason": "refusal",
            }))

        # 7. model_calls > 0 with provider_inference_ms=0.0 must fail
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(dict(base_att, trace={
                "model_invocation_observed": True,
                "model_calls": 1,
                "provider_inference_ms": 0.0,
            }))

        # 8. Unobserved invocation missing unavailable_reason must fail
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(dict(base_att, trace={
                "model_invocation_observed": False,
                "model_calls": None,
                "provider_inference_ms": None,
                "unavailable_reason": None,
            }))

        # 9. Unobserved invocation with non-null calls must fail
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(dict(base_att, trace={
                "model_invocation_observed": False,
                "model_calls": 1,
                "provider_inference_ms": 100.0,
                "unavailable_reason": "network_down",
            }))

    def test_h8_manifest_artifact_files_exact_canonical_mutations(self):
        """Mutation tests for H8: manifest artifact_files must exactly match CANONICAL_ARTIFACT_FILES."""
        valid_manifest = {
            "schema_version": SCHEMA_VERSION_MANIFEST,
            "protocol_version": PROTOCOL_VERSION,
            "run_id": "run-h8-test",
            "lane_id": "mock-a0",
            "provider_id": "mock",
            "cache_mode": "answer_cache_off",
            "retry_policy_id": "mock_retry_v1",
            "load_profile_id": "mock_single_worker",
            "system_commit_sha": SYSTEM_BASELINE_COMMIT_SHA,
            "evaluation_harness_sha": "1" * 40,
            "evaluation_overlay_sha256": "none",
            "config_sha256": "a" * 64,
            "dataset_sha256": FROZEN_BENCHMARK_LF_SHA256,
            "fixture_manifest_sha256": "b" * 64,
            "qrels_sha256": "c" * 64,
            "created_at_utc": "2026-10-06T00:00:00Z",
            "completed_at_utc": "2026-10-06T00:00:00Z",
            "artifact_files": list(CANONICAL_ARTIFACT_FILES),
            "model_revision": None,
            "model_revision_unavailable_reason": "mock",
            "tokenizer_revision": None,
            "tokenizer_revision_unavailable_reason": "mock",
            "seed": None,
            "seed_unavailable_reason": "mock",
        }
        # Baseline must pass
        validate_manifest(valid_manifest)

        # 1. Missing manifest.json must fail (H8 probe reproduction)
        files_no_manifest = [f for f in CANONICAL_ARTIFACT_FILES if f != "manifest.json"]
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_manifest(dict(valid_manifest, artifact_files=files_no_manifest))
        self.assertIn("missing canonical files", str(ctx.exception))
        self.assertIn("manifest.json", str(ctx.exception))

        # 2. Duplicate entries must fail
        files_dup = list(CANONICAL_ARTIFACT_FILES) + ["manifest.json"]
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_manifest(dict(valid_manifest, artifact_files=files_dup))
        self.assertIn("duplicate entries", str(ctx.exception))

        # 3. Non-canonical / extra files must fail
        files_extra = list(CANONICAL_ARTIFACT_FILES) + ["extra_probe.json"]
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_manifest(dict(valid_manifest, artifact_files=files_extra))
        self.assertIn("non-canonical files", str(ctx.exception))

        # 4. artifact_files not a list must fail
        with self.assertRaises(SchemaValidationError):
            validate_manifest(dict(valid_manifest, artifact_files="not_a_list"))

    def test_h9_aggregate_bounds_mutations(self):
        """Mutation tests for H9: aggregate ratios and rates must be bounded and valid."""
        valid_agg = {
            "schema_version": SCHEMA_VERSION_AGGREGATE,
            "run_id": "run-agg-test",
            "logical_cases": 5,
            "n_total": 5,
            "n_attempt": 6,
            "n_graded": 5,
            "n_blocked": 0,
            "first_attempt_outcomes": {"completed": 5},
            "eventual_outcomes": {"completed": 5},
            "quality_conditional": {"numerator": 5, "denominator": 5, "rate": 1.0},
            "e2e_success": {"numerator": 5, "denominator": 5, "rate": 1.0},
            "first_attempt_success_rate": 1.0,
            "eventual_success_rate": 1.0,
            "retry_recovery_rate": None,
            "derived_from": ["attempts.jsonl", "grading.jsonl", "retrieval.jsonl", "errors.jsonl"],
            "artifact_checksums": "checksums.sha256",
        }
        validate_aggregate(valid_agg)

        # 1. Numerator > denominator must fail
        bad_num = dict(valid_agg, quality_conditional={"numerator": 6, "denominator": 5, "rate": 1.2})
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_aggregate(bad_num)
        self.assertIn("cannot exceed denominator", str(ctx.exception))

        # 2. Rate > 1.0 must fail
        bad_rate = dict(valid_agg, first_attempt_success_rate=1.2)
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_aggregate(bad_rate)
        self.assertIn("must be between 0.0 and 1.0", str(ctx.exception))

        # 3. retry_recovery_rate > 1.0 must fail
        bad_rec = dict(valid_agg, retry_recovery_rate=1.05)
        with self.assertRaises(SchemaValidationError):
            validate_aggregate(bad_rec)

        # 4. Negative denominator must fail
        bad_denom = dict(valid_agg, e2e_success={"numerator": 0, "denominator": -1, "rate": 0.0})
        with self.assertRaises(SchemaValidationError):
            validate_aggregate(bad_denom)

    def test_retrieval_qrels_sha_validation(self):
        """Retrieval record qrels_sha256 format validation."""
        valid_retrieval = dict(
            self.common_envelope,
            schema_version=SCHEMA_VERSION_RETRIEVAL,
            attempt_id="att-01",
            retrieval_event_id="rev-01",
            query_id="q-01",
            stage="served",
            candidate_chunks=[],
            served_chunks=[],
            qrels_version="qrels-v1",
            answerability_status="answerable",
            qrels_sha256="d" * 64,
        )
        validate_retrieval_record(valid_retrieval)

        # Invalid hex hash length
        bad_ret = dict(valid_retrieval, qrels_sha256="short_hash")
        with self.assertRaises(SchemaValidationError):
            validate_retrieval_record(bad_ret)


if __name__ == "__main__":
    unittest.main()
