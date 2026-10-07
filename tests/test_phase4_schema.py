"""Tests for Phase 4 schema validation, common envelope, and R10 measured zero rules."""

import unittest

try:
    from evals.harness.constants import (
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
    _HARNESS_AVAILABLE = True
except ImportError:
    _HARNESS_AVAILABLE = False


class TestPhase4Schema(unittest.TestCase):

    def setUp(self):
        if not _HARNESS_AVAILABLE:
            self.skipTest("evals.harness not available in runtime-only container")
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
            "run_id": "run-test-01",
            "lane_id": "mock-a0",
            "system_commit_sha": SYSTEM_BASELINE_COMMIT_SHA,
            "evaluation_harness_sha": "1" * 40,
            "evaluation_overlay_sha256": "none",
            "config_sha256": "a" * 64,
            "dataset_sha256": "b" * 64,
            "artifact_files": ["manifest.json", "attempts.jsonl"],
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


if __name__ == "__main__":
    unittest.main()
