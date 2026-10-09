"""Tests for Phase 4 schema validation, common envelope, and R10 measured zero rules."""

import unittest

from evals.harness.constants import (
    CANONICAL_ARTIFACT_FILES,
    DISALLOWED_HARNESS_PLACEHOLDER_SHAS,
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
from evals.harness.gates import (
    GATE_G0_SPEC,
    GATE_G1_BUILD_HARNESS,
    GATE_G2_MERGED_VERIFIED,
    GATE_G3_SMOKE_AUTHORIZED,
    GATE_G4_LIVE_SMOKE,
    GATE_G5_LANE_MEASUREMENT_READY,
    GATE_G6_FULL_MEASUREMENT_AUTHORIZED,
    STATUS_MEASUREMENT_READY,
    STATUS_PREFLIGHT,
    GateOrderError,
    GatePermissionError,
    Phase4GateStateMachine,
    assert_gate_readiness,
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
            "evaluation_harness_sha": "1f8c344e5e06a6fa170518d31b75f7b5b23d2b1a",
            "evaluation_overlay_sha256": "none",
            "protocol_version": PROTOCOL_VERSION,
            "config_sha256": "a" * 64,
            "fixture_manifest_sha256": "b" * 64,
            "created_at_utc": "2026-10-06T00:00:00Z",
        }
        self.valid_manifest = {
            "schema_version": SCHEMA_VERSION_MANIFEST,
            "protocol_version": PROTOCOL_VERSION,
            "run_id": "run-test-01",
            "lane_id": "mock-a0",
            "provider_id": "mock",
            "cache_mode": "answer_cache_off",
            "retry_policy_id": "mock_retry_v1",
            "load_profile_id": "mock_single_worker",
            "system_commit_sha": SYSTEM_BASELINE_COMMIT_SHA,
            "evaluation_harness_sha": "1f8c344e5e06a6fa170518d31b75f7b5b23d2b1a",
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
            "evaluation_harness_sha": "1f8c344e5e06a6fa170518d31b75f7b5b23d2b1a",
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
            finished_at_utc="2026-10-06T00:00:00Z",
            http_status=200,
            outcome="handoff",
            response={"text": "Chuyển tiếp hỗ trợ"},
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
            qrels_source="evals/qrels/policy_qrels_v1.json",
            qrels_sha256="769a45d682648290a3356dad32aacae3c62f6942b62844dd4cc50f2d83c15161",
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
            finished_at_utc="2026-10-06T00:00:00Z",
            http_status=200,
            outcome="completed",
            response={"text": "OK"},
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
            "evaluation_harness_sha": "1f8c344e5e06a6fa170518d31b75f7b5b23d2b1a",
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
            qrels_source="evals/qrels/policy_qrels_v1.json",
            answerability_status="answerable",
            qrels_sha256="d" * 64,
        )
        validate_retrieval_record(valid_retrieval)

        # Invalid hex hash length
        bad_ret = dict(valid_retrieval, qrels_sha256="short_hash")
        with self.assertRaises(SchemaValidationError):
            validate_retrieval_record(bad_ret)

    def test_f1_evidence_refs_schema_validation(self):
        """Blocker F1: evidence_refs must be a non-empty list of non-empty strings."""
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
            evidence_refs=["rec-att-001", "rec-ret-001"],
            adjudicated=False,
            answerability_status="answerable",
            severity=None,
        )
        validate_grading_record(valid_grading)

        # 1. Not a list
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_grading_record(dict(valid_grading, evidence_refs="rec-001"))
        self.assertIn("must be a list", str(ctx.exception))

        # 2. Empty list
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_grading_record(dict(valid_grading, evidence_refs=[]))
        self.assertIn("non-empty list", str(ctx.exception))

        # 3. None
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_grading_record(dict(valid_grading, evidence_refs=None))
        self.assertIn("must be a list", str(ctx.exception))

        # 4. List with non-string element
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_grading_record(dict(valid_grading, evidence_refs=["rec-001", 123]))
        self.assertIn("non-empty string", str(ctx.exception))

        # 5. List with empty string
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_grading_record(dict(valid_grading, evidence_refs=["rec-001", ""]))
        self.assertIn("non-empty string", str(ctx.exception))

    def test_f2_placeholder_sha_rejection(self):
        """Blocker F2: reject harness SHA placeholders in common envelope and manifest."""
        valid_manifest = {
            "schema_version": SCHEMA_VERSION_MANIFEST,
            "protocol_version": PROTOCOL_VERSION,
            "run_id": "run-f2-test",
            "lane_id": "mock-a0",
            "provider_id": "mock",
            "cache_mode": "answer_cache_off",
            "retry_policy_id": "mock_retry_v1",
            "load_profile_id": "mock_single_worker",
            "system_commit_sha": SYSTEM_BASELINE_COMMIT_SHA,
            "evaluation_harness_sha": "1f8c344e5e06a6fa170518d31b75f7b5b23d2b1a",
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

        # 1. Common envelope rejects placeholders
        for placeholder in DISALLOWED_HARNESS_PLACEHOLDER_SHAS:
            bad_env = dict(self.common_envelope, evaluation_harness_sha=placeholder)
            with self.assertRaises(SchemaValidationError) as ctx:
                validate_common_envelope(bad_env, "test")
            self.assertIn("cannot be a placeholder", str(ctx.exception))

        # 2. Manifest rejects placeholders
        for placeholder in DISALLOWED_HARNESS_PLACEHOLDER_SHAS:
            bad_man = dict(valid_manifest, evaluation_harness_sha=placeholder)
            with self.assertRaises(SchemaValidationError) as ctx:
                validate_manifest(bad_man)
            self.assertIn("cannot be a placeholder", str(ctx.exception))

        # 3. Accepted bundle (is_preflight=False) requires non-None SHA
        man_no_sha = dict(valid_manifest, evaluation_harness_sha=None, is_preflight=False)
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_manifest(man_no_sha)
        self.assertIn("Accepted bundle requires non-null 40-hex evaluation_harness_sha", str(ctx.exception))

        # 4. Preflight bundle allows evaluation_harness_sha=None
        validate_manifest(dict(valid_manifest, evaluation_harness_sha=None, is_preflight=True))

        # 5. Preflight bundle still rejects explicit placeholder
        bad_preflight = dict(valid_manifest, evaluation_harness_sha="1" * 40, is_preflight=True)
        with self.assertRaises(SchemaValidationError):
            validate_manifest(bad_preflight)

    def test_r11_gate_readiness_state_machine(self):
        """R11 executable gate state machine transitions and permissions."""
        sm = Phase4GateStateMachine(initial_gate=GATE_G0_SPEC)
        self.assertEqual(sm.current_gate, GATE_G0_SPEC)

        # Linear progression passes
        sm.transition_to(GATE_G1_BUILD_HARNESS)
        sm.transition_to(GATE_G2_MERGED_VERIFIED)
        sm.transition_to(GATE_G3_SMOKE_AUTHORIZED)
        sm.transition_to(GATE_G4_LIVE_SMOKE)

        # G4 cannot declare READY FOR MEASUREMENT
        with self.assertRaises(GatePermissionError) as ctx:
            sm.assert_can_set_readiness(STATUS_MEASUREMENT_READY)
        self.assertIn("restricted", str(ctx.exception))

        # Move to G5
        sm.transition_to(GATE_G5_LANE_MEASUREMENT_READY)
        self.assertTrue(sm.can_grant_measurement_readiness())
        sm.assert_can_set_readiness(STATUS_MEASUREMENT_READY)

        # Non-linear jump must fail
        sm_bad = Phase4GateStateMachine(initial_gate=GATE_G0_SPEC)
        with self.assertRaises(GateOrderError):
            sm_bad.transition_to(GATE_G5_LANE_MEASUREMENT_READY)

        # assert_gate_readiness helper
        with self.assertRaises(GatePermissionError):
            assert_gate_readiness(GATE_G4_LIVE_SMOKE, STATUS_MEASUREMENT_READY)
        assert_gate_readiness(GATE_G5_LANE_MEASUREMENT_READY, STATUS_MEASUREMENT_READY)

        # validate_manifest with R11 gate check
        man_g4 = dict(self.valid_manifest, readiness_status=STATUS_MEASUREMENT_READY, gate=GATE_G4_LIVE_SMOKE)
        with self.assertRaises(SchemaValidationError):
            validate_manifest(man_g4)

        # Mock provider must be rejected from claiming READY FOR MEASUREMENT (N5)
        man_mock_g5 = dict(self.valid_manifest, readiness_status=STATUS_MEASUREMENT_READY, gate=GATE_G5_LANE_MEASUREMENT_READY)
        with self.assertRaises(SchemaValidationError):
            validate_manifest(man_mock_g5)

        # Real provider/lane with locked SHA passes G5
        man_g5 = dict(
            self.valid_manifest,
            provider_id="openai",
            lane_id="lane-a0",
            readiness_status=STATUS_MEASUREMENT_READY,
            gate=GATE_G5_LANE_MEASUREMENT_READY,
        )
        validate_manifest(man_g5)

    def test_attempt_finished_at_and_response_validation(self):
        """Attempt record requires finished_at_utc and response (dict or None)."""
        valid_att = dict(
            self.common_envelope,
            attempt_id="att-schema-01",
            retry_index=0,
            attempt_class="first",
            started_at_utc="2026-10-06T00:00:00Z",
            finished_at_utc="2026-10-06T00:00:01Z",
            http_status=200,
            outcome="completed",
            response={"text": "Xin chào quý khách"},
            trace={
                "actual_mode": "retail",
                "model_calls": 1,
                "tool_count": 0,
                "cache_hit": False,
                "provider_inference_ms": 150.0,
                "model_invocation_observed": True,
            },
        )
        validate_attempt_record(valid_att)

        # Missing finished_at_utc
        bad_att1 = dict(valid_att)
        del bad_att1["finished_at_utc"]
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(bad_att1)

        # Missing response
        bad_att2 = dict(valid_att)
        del bad_att2["response"]
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(bad_att2)

        # Invalid response type
        bad_att3 = dict(valid_att, response="should_be_a_dict_or_null")
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(bad_att3)

        # Response None is permitted (e.g. timeout error attempt)
        validate_attempt_record(dict(valid_att, response=None))

    def test_retrieval_chunk_structure_validation(self):
        """Retrieval chunks must have chunk_id, rank >= 1, float score, source_id."""
        valid_chunk = {
            "chunk_id": "chk_policy_001",
            "rank": 1,
            "score": 0.85,
            "source_id": "chinh_sach_doi_tra.md",
        }
        valid_ret = dict(
            self.common_envelope,
            schema_version=SCHEMA_VERSION_RETRIEVAL,
            attempt_id="att-01",
            retrieval_event_id="rev-01",
            query_id="q-01",
            stage="served",
            candidate_chunks=[valid_chunk],
            served_chunks=[valid_chunk],
            qrels_version="qrels-v1",
            qrels_source="evals/qrels/policy_qrels_v1.json",
            qrels_sha256="769a45d682648290a3356dad32aacae3c62f6942b62844dd4cc50f2d83c15161",
            answerability_status="answerable",
        )
        validate_retrieval_record(valid_ret)

        # Missing rank in candidate chunk
        bad_chunk = dict(valid_ret, candidate_chunks=[{
            "chunk_id": "chk_001",
            "score": 0.5,
            "source_id": "policy.md",
        }])
        with self.assertRaises(SchemaValidationError):
            validate_retrieval_record(bad_chunk)

        # Rank 0 (must be >= 1)
        bad_rank = dict(valid_ret, candidate_chunks=[{
            "chunk_id": "chk_001",
            "rank": 0,
            "score": 0.5,
            "source_id": "policy.md",
        }])
        with self.assertRaises(SchemaValidationError):
            validate_retrieval_record(bad_rank)

        # Non-numeric score
        bad_score = dict(valid_ret, candidate_chunks=[{
            "chunk_id": "chk_001",
            "rank": 1,
            "score": "high",
            "source_id": "policy.md",
        }])
        with self.assertRaises(SchemaValidationError):
            validate_retrieval_record(bad_score)

    def test_error_redaction_validation(self):
        """Error record message_redacted must not leak tokens or passwords."""
        valid_err = dict(
            self.common_envelope,
            schema_version=SCHEMA_VERSION_ERROR,
            attempt_id="att-01",
            error_id="err-01",
            stage="admission",
            taxonomy_code="INFRA_429_ADMISSION",
            severity="S2",
            retryable=True,
            http_status=429,
            message_redacted="upstream 429 rate limit exceeded",
        )
        validate_error_record(valid_err)

        # Empty message_redacted
        with self.assertRaises(SchemaValidationError):
            validate_error_record(dict(valid_err, message_redacted=""))

        # Leaking secret/token
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_error_record(dict(valid_err, message_redacted="authorization failed with Bearer eyJhbGciOi..."))
        self.assertIn("credential pattern", str(ctx.exception))


    def test_nan_inf_rejected_in_schema(self):
        """Blocker B3: NaN and Infinity must be strictly rejected across schema validators."""
        # NaN in attempt provider_inference_ms
        bad_att = dict(
            self.common_envelope,
            attempt_id="att-nan",
            retry_index=0,
            attempt_class="first",
            started_at_utc="2026-10-06T00:00:00Z",
            finished_at_utc="2026-10-06T00:00:00Z",
            http_status=200,
            outcome="completed",
            response={"text": "Hello"},
            trace={
                "model_invocation_observed": True,
                "model_calls": 1,
                "provider_inference_ms": float("nan"),
            },
        )
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(bad_att)

        # Inf in retrieval chunk score
        bad_chunk = {
            "chunk_id": "chk_001",
            "rank": 1,
            "score": float("inf"),
            "source_id": "policy.md",
        }
        bad_ret = dict(
            self.common_envelope,
            schema_version=SCHEMA_VERSION_RETRIEVAL,
            attempt_id="att-01",
            retrieval_event_id="rev-01",
            query_id="q-01",
            stage="served",
            candidate_chunks=[bad_chunk],
            served_chunks=[bad_chunk],
            qrels_version="qrels-v1",
            qrels_source="evals/qrels/policy_qrels_v1.json",
            qrels_sha256="769a45d682648290a3356dad32aacae3c62f6942b62844dd4cc50f2d83c15161",
            answerability_status="answerable",
        )
        with self.assertRaises(SchemaValidationError):
            validate_retrieval_record(bad_ret)

        # NaN in aggregate rate
        bad_agg = {
            "schema_version": SCHEMA_VERSION_AGGREGATE,
            "run_id": "run-test-01",
            "logical_cases": 1,
            "n_total": 1,
            "n_attempt": 1,
            "n_graded": 1,
            "n_blocked": 0,
            "first_attempt_outcomes": {"completed": 1},
            "eventual_outcomes": {"completed": 1},
            "quality_conditional": {"numerator": 1, "denominator": 1, "rate": float("nan")},
            "e2e_success": {"numerator": 1, "denominator": 1, "rate": 1.0},
            "derived_from": ["attempts.jsonl", "grading.jsonl", "retrieval.jsonl", "errors.jsonl"],
            "artifact_checksums": "checksums.sha256",
        }
        with self.assertRaises(SchemaValidationError):
            validate_aggregate(bad_agg)

    def test_is_preflight_strict_bool_validation(self):
        """is_preflight must be a strict boolean (not str or int)."""
        bad_str = dict(self.valid_manifest, is_preflight="true")
        with self.assertRaises(SchemaValidationError):
            validate_manifest(bad_str)

        bad_int = dict(self.valid_manifest, is_preflight=1)
        with self.assertRaises(SchemaValidationError):
            validate_manifest(bad_int)

        good_bool = dict(self.valid_manifest, is_preflight=True)
        validate_manifest(good_bool)

    def test_redaction_marker_allowed_in_error_record(self):
        """Sanitized error messages containing [REDACTED] or *** must not be flagged as credential leaks."""
        valid_err = dict(
            self.common_envelope,
            schema_version=SCHEMA_VERSION_ERROR,
            attempt_id="att-01",
            error_id="err-01",
            stage="admission",
            taxonomy_code="INFRA_429_ADMISSION",
            severity="S2",
            retryable=True,
            http_status=429,
            message_redacted="Authentication failed for user: password=[REDACTED]",
        )
        validate_error_record(valid_err)

    def test_only_g5_can_grant_measurement_ready(self):
        """Blocker B6: Only Gate G5 can grant READY FOR MEASUREMENT status."""
        # G6 must be rejected when requesting STATUS_MEASUREMENT_READY
        with self.assertRaises(GatePermissionError):
            assert_gate_readiness(GATE_G6_FULL_MEASUREMENT_AUTHORIZED, STATUS_MEASUREMENT_READY)

        # G1 must be rejected when requesting STATUS_MEASUREMENT_READY
        with self.assertRaises(GatePermissionError):
            assert_gate_readiness(GATE_G1_BUILD_HARNESS, STATUS_MEASUREMENT_READY)

        # G5 is allowed to grant STATUS_MEASUREMENT_READY
        assert_gate_readiness(GATE_G5_LANE_MEASUREMENT_READY, STATUS_MEASUREMENT_READY)

    def test_n4_trace_tools_called_validation(self):
        """N4: trace.tools_called must be list of non-empty strings."""
        valid_att = dict(
            self.common_envelope,
            attempt_id="att-n4-01",
            retry_index=0,
            attempt_class="first",
            started_at_utc="2026-10-06T00:00:00Z",
            finished_at_utc="2026-10-06T00:00:01Z",
            http_status=200,
            outcome="completed",
            response={"text": "Xin chào"},
            trace={
                "actual_mode": "retail",
                "model_invocation_observed": True,
                "model_calls": 1,
                "tool_count": 1,
                "tools_called": ["get_order"],
                "cache_hit": False,
                "provider_inference_ms": 100.0,
            },
        )
        validate_attempt_record(valid_att)

        # String instead of list
        bad_str = dict(valid_att, trace=dict(valid_att["trace"], tools_called="get_order"))
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(bad_str)

        # List with non-string
        bad_elem = dict(valid_att, trace=dict(valid_att["trace"], tools_called=[123]))
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(bad_elem)

        # List with empty string
        bad_empty = dict(valid_att, trace=dict(valid_att["trace"], tools_called=[""]))
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(bad_empty)

    def test_n4_trace_tool_calls_and_safety_flags_strict(self):
        """N4: tool_count/tool_calls must be non-negative int; safety flags must be strict bool."""
        base_att = dict(
            self.common_envelope,
            attempt_id="att-n4-02",
            retry_index=0,
            attempt_class="first",
            started_at_utc="2026-10-06T00:00:00Z",
            finished_at_utc="2026-10-06T00:00:01Z",
            http_status=200,
            outcome="completed",
            response={"text": "Xin chào"},
            trace={
                "actual_mode": "retail",
                "model_invocation_observed": True,
                "model_calls": 1,
                "tool_count": 0,
                "tools_called": [],
                "cache_hit": False,
                "provider_inference_ms": 100.0,
            },
        )

        # Bad tool_count: string or negative
        bad_tc_str = dict(base_att, trace=dict(base_att["trace"], tool_count="0"))
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(bad_tc_str)

        bad_tc_neg = dict(base_att, trace=dict(base_att["trace"], tool_count=-1))
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(bad_tc_neg)

        # Safety flags: non-strict bool
        safety_flags = (
            "privacy_leak",
            "prompt_injection",
            "unauthorized_mutation",
            "fabricated_source",
            "ownership_bypass",
            "ownership_violation",
            "identity_collision",
            "unsupported_claim",
        )
        for flag in safety_flags:
            bad_flag_str = dict(base_att, trace=dict(base_att["trace"], **{flag: "true"}))
            with self.assertRaises(SchemaValidationError):
                validate_attempt_record(bad_flag_str)

            bad_flag_int = dict(base_att, trace=dict(base_att["trace"], **{flag: 1}))
            with self.assertRaises(SchemaValidationError):
                validate_attempt_record(bad_flag_int)

            bad_flag_none = dict(base_att, trace=dict(base_att["trace"], **{flag: None}))
            with self.assertRaises(SchemaValidationError):
                validate_attempt_record(bad_flag_none)

            good_flag_f = dict(base_att, trace=dict(base_att["trace"], **{flag: False}))
            validate_attempt_record(good_flag_f)

            good_flag_t = dict(base_att, trace=dict(base_att["trace"], **{flag: True}))
            validate_attempt_record(good_flag_t)

    def test_l1_null_response_text_validation(self):
        """L1: response.text=None is rejected when outcome='completed', allowed on transport errors."""
        completed_null_text = dict(
            self.common_envelope,
            attempt_id="att-l1-01",
            retry_index=0,
            attempt_class="first",
            started_at_utc="2026-10-06T00:00:00Z",
            finished_at_utc="2026-10-06T00:00:01Z",
            http_status=200,
            outcome="completed",
            response={"text": None},
            trace={
                "actual_mode": "retail",
                "model_invocation_observed": True,
                "model_calls": 1,
                "tool_count": 0,
                "tools_called": [],
                "cache_hit": False,
                "provider_inference_ms": 100.0,
            },
        )
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(completed_null_text)

        # Transport error with null response is valid
        transport_err = dict(
            self.common_envelope,
            attempt_id="att-l1-02",
            retry_index=0,
            attempt_class="first",
            started_at_utc="2026-10-06T00:00:00Z",
            finished_at_utc="2026-10-06T00:00:01Z",
            http_status=500,
            outcome="transport_error",
            response=None,
            trace={
                "actual_mode": "retail",
                "model_calls": None,
                "tool_count": 0,
                "tools_called": [],
                "cache_hit": False,
                "provider_latency_ms": 0.0,
                "model_invocation_observed": False,
                "unavailable_reason": "server_error",
            },
        )
        validate_attempt_record(transport_err)

    def test_l3_aggregate_completeness_and_missing_grading(self):
        """L3: validate_aggregate accepts and validates completeness and n_missing_grading."""
        valid_agg = {
            "schema_version": SCHEMA_VERSION_AGGREGATE,
            "run_id": "run-test-01",
            "logical_cases": 1,
            "n_total": 1,
            "n_attempt": 1,
            "n_graded": 1,
            "n_blocked": 0,
            "first_attempt_outcomes": {"completed": 1},
            "eventual_outcomes": {"completed": 1},
            "quality_conditional": {"numerator": 1, "denominator": 1, "rate": 1.0},
            "e2e_success": {"numerator": 1, "denominator": 1, "rate": 1.0},
            "derived_from": ["attempts.jsonl", "grading.jsonl", "retrieval.jsonl", "errors.jsonl"],
            "artifact_checksums": "checksums.sha256",
            "n_missing_grading": 0,
            "completeness": 1.0,
        }
        validate_aggregate(valid_agg)

        # Bad n_missing_grading (negative)
        bad_missing = dict(valid_agg, n_missing_grading=-1)
        with self.assertRaises(SchemaValidationError):
            validate_aggregate(bad_missing)

        # Bad completeness (out of range or non-finite)
        bad_comp_high = dict(valid_agg, completeness=1.5)
        with self.assertRaises(SchemaValidationError):
            validate_aggregate(bad_comp_high)

        bad_comp_nan = dict(valid_agg, completeness=float("nan"))
        with self.assertRaises(SchemaValidationError):
            validate_aggregate(bad_comp_nan)

    def test_l4_manifest_readiness_status_typo_rejected(self):
        """L4: Typos in readiness_status must be rejected."""
        bad_typo = dict(self.valid_manifest, readiness_status="READY_FOR_MEASUREMENT")
        with self.assertRaises(SchemaValidationError):
            validate_manifest(bad_typo)

        bad_typo2 = dict(self.valid_manifest, readiness_status="READY FOR PREFLIGHT")
        with self.assertRaises(SchemaValidationError):
            validate_manifest(bad_typo2)


if __name__ == "__main__":
    unittest.main()
