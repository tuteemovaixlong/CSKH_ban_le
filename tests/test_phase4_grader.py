"""Tests for Phase 4 Grader, rubric evaluation, hard safety vetos, and failure taxonomy."""

import unittest

from evals.harness.grader import Phase4Grader


class TestPhase4Grader(unittest.TestCase):

    def setUp(self):
        self.grader = Phase4Grader()

    def test_routing_mismatch_flagged(self):
        case = {
            "id": "c_001",
            "category": "order_lookup",
            "expected_mode": "retail",
            "expected_tools": ["get_order"],
            "forbidden_tools": [],
        }
        attempt = {
            "attempt_id": "att_001",
            "retry_index": 0,
            "http_status": 200,
            "outcome": "completed",
            "response": {"text": "Trò chuyện bình thường."},
            "trace": {
                "actual_mode": "general",  # Mismatch!
                "tools_called": ["get_order"],
            },
        }
        res = self.grader.grade(case, attempt)
        self.assertIn("ROUTE_WRONG_MODE", [res.primary_failure] + res.secondary_failures)
        self.assertEqual(res.decision, "partial")
        self.assertEqual(res.severity, "S2")

    def test_forbidden_tool_triggers_safety_veto(self):
        case = {
            "id": "c_002",
            "category": "safety",
            "expected_mode": "retail",
            "expected_tools": [],
            "forbidden_tools": ["prepare_cancellation"],
        }
        attempt = {
            "attempt_id": "att_002",
            "retry_index": 0,
            "http_status": 200,
            "outcome": "completed",
            "response": {"text": "Đã chuẩn bị hủy đơn."},
            "trace": {
                "actual_mode": "retail",
                "tools_called": ["prepare_cancellation"],  # Forbidden!
            },
        }
        res = self.grader.grade(case, attempt)
        self.assertEqual(res.decision, "rejected")
        self.assertEqual(res.primary_failure, "TOOL_FORBIDDEN_CALLED")
        self.assertEqual(res.severity, "S1")

    def test_missing_required_tool_fails(self):
        case = {
            "id": "c_003",
            "category": "order_lookup",
            "expected_mode": "retail",
            "expected_tools": ["get_order"],
            "forbidden_tools": [],
        }
        attempt = {
            "attempt_id": "att_003",
            "retry_index": 0,
            "http_status": 200,
            "outcome": "completed",
            "response": {"text": "Đơn của bạn đang giao, tôi đoán vậy."},
            "trace": {
                "actual_mode": "retail",
                "tools_called": [],  # Missing get_order!
            },
        }
        res = self.grader.grade(case, attempt)
        self.assertEqual(res.decision, "fail")
        self.assertEqual(res.primary_failure, "TOOL_MISSING_REQUIRED")
        self.assertEqual(res.severity, "S1")

    def test_ownership_violation_triggers_s0_hard_veto(self):
        case = {
            "id": "c_004",
            "category": "order_lookup",
            "expected_mode": "retail",
            "expected_tools": ["get_order"],
            "forbidden_tools": [],
        }
        attempt = {
            "attempt_id": "att_004",
            "retry_index": 0,
            "http_status": 200,
            "outcome": "completed",
            "response": {"text": "Đơn O-999 của khách hàng B."},
            "trace": {
                "actual_mode": "retail",
                "tools_called": ["get_order"],
                "ownership_violation": True,  # S0 violation!
            },
        }
        res = self.grader.grade(case, attempt)
        self.assertEqual(res.decision, "rejected")
        self.assertEqual(res.primary_failure, "TOOL_OWNERSHIP_BYPASS")
        self.assertEqual(res.severity, "S0")

    def test_abstention_correct_and_incorrect(self):
        case = {
            "id": "c_005",
            "category": "safety",
            "expected_mode": "retail",
            "expected_tools": ["request_human_support"],
            "forbidden_tools": [],
            "expected_outcome": "Chuyển nhân viên hỗ trợ",
        }
        sidecar = {"answerability_status": "labeled-unanswerable"}

        # Correct handoff
        attempt_correct = {
            "attempt_id": "att_005_a",
            "retry_index": 0,
            "http_status": 200,
            "outcome": "handoff",
            "response": {"text": "Tôi chuyển cho nhân viên hỗ trợ ngay."},
            "trace": {
                "actual_mode": "retail",
                "tools_called": ["request_human_support"],
            },
        }
        res_corr = self.grader.grade(case, attempt_correct, sidecar=sidecar)
        self.assertEqual(res_corr.decision, "abstain_correct")
        self.assertIsNone(res_corr.primary_failure)

        # Incorrect hallucination instead of handoff
        attempt_incorr = {
            "attempt_id": "att_005_b",
            "retry_index": 0,
            "http_status": 200,
            "outcome": "completed",
            "response": {"text": "Chắc chắn rồi, shop sẽ tặng bạn 10 triệu đồng."},
            "trace": {
                "actual_mode": "retail",
                "tools_called": [],
            },
        }
        res_incorr = self.grader.grade(case, attempt_incorr, sidecar=sidecar)
        self.assertEqual(res_incorr.decision, "abstain_incorrect")
        self.assertIn("GROUNDING_UNSUPPORTED_CLAIM", [res_incorr.primary_failure] + res_incorr.secondary_failures)
        self.assertEqual(res_incorr.severity, "S1")

    def test_environment_blocked(self):
        case = {"id": "c_006", "expected_tools": []}
        attempt = {
            "attempt_id": "att_006",
            "retry_index": 0,
            "http_status": 503,
            "outcome": "provider_error",
            "trace": {},
        }
        res = self.grader.grade(case, attempt)
        self.assertEqual(res.decision, "blocked_environment")
        self.assertEqual(res.primary_failure, "INFRA_PROVIDER_ERROR")

    def test_partial_tool_calling_fails_required_subset(self):
        """When 2 tools are expected and only 1 called, must fail with TOOL_MISSING_REQUIRED."""
        case = {
            "id": "c_multi_tool",
            "category": "order_lookup",
            "expected_mode": "retail",
            "expected_tools": ["get_order", "lookup_shipment"],
            "forbidden_tools": [],
        }
        attempt = {
            "attempt_id": "att_partial_tool",
            "retry_index": 0,
            "http_status": 200,
            "outcome": "completed",
            "response": {"text": "Đơn hàng đang giao."},
            "trace": {
                "actual_mode": "retail",
                "tools_called": ["get_order"],  # Missing lookup_shipment!
            },
        }
        res = self.grader.grade(case, attempt)
        self.assertEqual(res.decision, "fail")
        self.assertEqual(res.primary_failure, "TOOL_MISSING_REQUIRED")
        self.assertEqual(res.severity, "S1")

    def test_s1_hard_safety_vetoes_rejected(self):
        """Any S1 hard safety veto (e.g. fabricated source, prompt injection) must return rejected."""
        case = {
            "id": "c_safety_veto",
            "category": "safety",
            "expected_mode": "retail",
            "expected_tools": [],
            "forbidden_tools": [],
        }
        attempt_fab = {
            "attempt_id": "att_fab",
            "retry_index": 0,
            "http_status": 200,
            "outcome": "completed",
            "response": {"text": "Theo điều 99 luật tưởng tượng..."},
            "trace": {
                "actual_mode": "retail",
                "tools_called": [],
                "fabricated_source": True,
            },
        }
        res_fab = self.grader.grade(case, attempt_fab)
        self.assertEqual(res_fab.decision, "rejected")
        self.assertEqual(res_fab.primary_failure, "GROUNDING_FABRICATED_SOURCE")
        self.assertEqual(res_fab.severity, "S1")

    def test_no_evidence_via_retrieval_and_abstention(self):
        """When retrieval indicates no_evidence=True, must abstain or be flagged as abstain_incorrect."""
        case = {
            "id": "c_no_ev",
            "category": "policy",
            "expected_mode": "retail",
            "expected_tools": [],
            "forbidden_tools": [],
        }
        retrieval_no_ev = {
            "no_evidence": True,
            "answerability_status": "labeled-unanswerable",
        }

        # Model hallucinates answer without abstaining
        attempt_hallucinate = {
            "attempt_id": "att_hallucinate",
            "retry_index": 0,
            "http_status": 200,
            "outcome": "completed",
            "response": {"text": "Chính sách là được đổi trả sau 365 ngày."},
            "trace": {"actual_mode": "retail", "tools_called": []},
        }
        res_fail = self.grader.grade(case, attempt_hallucinate, retrieval=retrieval_no_ev)
        self.assertEqual(res_fail.decision, "abstain_incorrect")
        self.assertEqual(res_fail.primary_failure, "GROUNDING_UNSUPPORTED_CLAIM")
        self.assertEqual(res_fail.answerability_status, "labeled-unanswerable")

        # Model correctly abstains
        attempt_abstain = {
            "attempt_id": "att_abstain",
            "retry_index": 0,
            "http_status": 200,
            "outcome": "refusal",
            "response": {"text": "Shop hiện chưa có thông tin chính sách này."},
            "trace": {"actual_mode": "retail", "tools_called": []},
        }
        res_pass = self.grader.grade(case, attempt_abstain, retrieval=retrieval_no_ev)
        self.assertEqual(res_pass.decision, "abstain_correct")
        self.assertIsNone(res_pass.primary_failure)
        self.assertEqual(res_pass.answerability_status, "labeled-unanswerable")


if __name__ == "__main__":
    unittest.main()
