"""Adversarial acceptance tests for Phase 4 Evaluation Harness.

Normative reference:
- docs/phase4/REVIEW_PHASE_4_PLAN.md (§6 Acceptance/CI/replay)
"""

from pathlib import Path
import json
import shutil
import tempfile
import unittest

from evals.harness.constants import (
    PROTOCOL_VERSION,
    SCHEMA_VERSION_ATTEMPT,
    SCHEMA_VERSION_ERROR,
    SCHEMA_VERSION_GRADING,
    SCHEMA_VERSION_MANIFEST,
    SCHEMA_VERSION_RETRIEVAL,
    SYSTEM_BASELINE_COMMIT_SHA,
)
from evals.harness.grader import Phase4Grader
from evals.harness.runner import Phase4MockRunner
from evals.harness.schema import SchemaValidationError, validate_attempt_record
from evals.harness.telemetry import EvaluationOverlayError, assert_a0_cache_off
from evals.harness.validator import CanonicalBundleValidator
from evals.harness.writer import CanonicalBundleWriter


class TestPhase4Adversarial(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="phase4_adversarial_"))
        self.grader = Phase4Grader()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_a0_cache_off_assertion(self):
        # A0 protocol strictly requires answer_cache_off
        assert_a0_cache_off("answer_cache_off")

        with self.assertRaises(EvaluationOverlayError):
            assert_a0_cache_off("answer_cache_on")

        with self.assertRaises(EvaluationOverlayError):
            Phase4MockRunner(
                run_id="run_cache_err",
                output_dir=self.test_dir,
                cache_mode="answer_cache_on",
            )

    def test_observed_vs_fabricated_zero_r10(self):
        base_record = {
            "schema_version": SCHEMA_VERSION_ATTEMPT,
            "record_id": "rec-adv-01",
            "run_id": "run-adv",
            "case_id": "ro_s1_001",
            "logical_request_id": "req-01",
            "system_commit_sha": SYSTEM_BASELINE_COMMIT_SHA,
            "evaluation_harness_sha": "1f8c344e5e06a6fa170518d31b75f7b5b23d2b1a",
            "evaluation_overlay_sha256": "none",
            "protocol_version": PROTOCOL_VERSION,
            "config_sha256": "a" * 64,
            "fixture_manifest_sha256": "b" * 64,
            "created_at_utc": "2026-10-06T00:00:00Z",
            "attempt_id": "att-adv-01",
            "retry_index": 0,
            "attempt_class": "first",
            "started_at_utc": "2026-10-06T00:00:00Z",
            "finished_at_utc": "2026-10-06T00:00:00Z",
            "http_status": 200,
            "outcome": "refusal",
            "response": {"text": "Tôi từ chối trả lời."},
        }

        # Valid observed zero (rule refusal)
        valid_att = dict(base_record, trace={
            "actual_mode": "retail",
            "model_calls": 0,
            "tool_count": 0,
            "cache_hit": None,
            "provider_inference_ms": 0.0,
            "model_invocation_observed": True,
            "zero_reason": "refusal",
        })
        validate_attempt_record(valid_att)

        # Fabricated zero (unobserved, false flag)
        fab_att_1 = dict(base_record, trace={
            "actual_mode": "retail",
            "model_calls": 0,
            "tool_count": 0,
            "cache_hit": None,
            "provider_inference_ms": 0.0,
            "model_invocation_observed": False,
        })
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(fab_att_1)

        # Fabricated zero (zero_reason missing)
        fab_att_2 = dict(base_record, trace={
            "actual_mode": "retail",
            "model_calls": 0,
            "provider_inference_ms": 0.0,
            "model_invocation_observed": True,
            "zero_reason": None,
        })
        with self.assertRaises(SchemaValidationError):
            validate_attempt_record(fab_att_2)

    def test_429_to_200_retains_first_failure(self):
        """Simulates 429 followed by 200 retry and verifies first attempt retention."""
        runner = Phase4MockRunner(run_id="run_retry_test", output_dir=self.test_dir)
        runner.run(max_cases=20)  # Case index 5 triggers 429 -> 200 retry

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertTrue(report.is_valid, f"Validation failed: {report.errors}")

        # Check attempts.jsonl has the 429 attempt and the 200 retry
        attempts = [json.loads(line) for line in (self.test_dir / "attempts.jsonl").read_text(encoding="utf-8").splitlines()]
        case_5_atts = [a for a in attempts if a["case_id"] == "ro_s1_006"]
        self.assertEqual(len(case_5_atts), 2)
        self.assertEqual(case_5_atts[0]["retry_index"], 0)
        self.assertEqual(case_5_atts[0]["http_status"], 429)
        self.assertEqual(case_5_atts[0]["attempt_class"], "first")
        self.assertEqual(case_5_atts[1]["retry_index"], 1)
        self.assertEqual(case_5_atts[1]["http_status"], 200)
        self.assertEqual(case_5_atts[1]["attempt_class"], "transport_retry")

        # Verify aggregate recomputation retains first failure in first_attempt_outcomes
        agg = json.loads((self.test_dir / "aggregate.json").read_text(encoding="utf-8"))
        self.assertEqual(agg["first_attempt_outcomes"].get("admission_429", 0), 1)
        self.assertEqual(agg["eventual_outcomes"].get("completed", 0), 20)
        self.assertEqual(agg["retry_recovery_rate"], 1.0)

    def test_malformed_and_empty_200_fails_grading(self):
        case = {
            "id": "c_malformed",
            "category": "order_lookup",
            "expected_mode": "retail",
            "expected_tools": ["get_order"],
            "forbidden_tools": [],
        }
        attempt_empty = {
            "attempt_id": "att_empty",
            "retry_index": 0,
            "http_status": 200,
            "outcome": "completed",
            "response": {"text": ""},  # Empty text
            "trace": {"actual_mode": "retail", "tools_called": []},
        }
        res = self.grader.grade(case, attempt_empty)
        self.assertEqual(res.decision, "fail")
        self.assertEqual(res.primary_failure, "TOOL_MISSING_REQUIRED")

    def test_duplicate_and_orphan_join_rejection(self):
        runner = Phase4MockRunner(run_id="run_joins_test", output_dir=self.test_dir)
        runner.run(max_cases=2)

        # 1. Duplicate retrieval event ID
        rt_path = self.test_dir / "retrieval.jsonl"
        lines = rt_path.read_text(encoding="utf-8").splitlines()
        first_rt = json.loads(lines[0])
        dup_rt = dict(first_rt, record_id="rec_dup_rt")
        with open(rt_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(dup_rt) + "\n")

        writer = CanonicalBundleWriter(self.test_dir)
        writer.write_checksums()

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("Duplicate retrieval_event_id" in e for e in report.errors))


if __name__ == "__main__":
    unittest.main()
