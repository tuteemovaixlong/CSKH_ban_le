"""Unit tests for Multi-Agent Workflow and Routing."""
import unittest

from retailops.workflow.graph import run_multiagent
from retailops.workflow.state import MultiAgentState
from retailops.workflow.supervisor import run_supervisor


class MockGateway:
    def __init__(self, reply="Dạ shop xin chào anh/chị!"):
        self.reply = reply
        self.calls = []

    def chat(self, messages, allow_tools, timeout):
        self.calls.append({"messages": messages, "allow_tools": allow_tools})
        return {
            "message": {
                "role": "assistant",
                "content": self.reply
            }
        }


class MultiAgentFlowTests(unittest.TestCase):

    def setUp(self):
        self.gateway = MockGateway("Thuật toán SAC giúp AI học tối ưu! Ghé shop mua áo đẹp ngồi code mượt nhé!")
        self.identity = {"name": "test-slm", "provider": "mock"}
        self.execute = lambda name, args: {"status": "ok", "name": name, "args": args}

    def test_supervisor_routing_order(self):
        state: MultiAgentState = {
            "messages": [{"role": "user", "content": "Kiểm tra giúp tôi đơn hàng O-101"}],
            "fresh": [], "trace": {}, "tool_count": 0, "bound": {}, "complete": False,
            "intent": "unknown", "next_worker": "supervisor", "subagent_history": [],
            "sentiment": "neutral", "strict_mode": False, "consecutive_ood_count": 0,
            "action_proposal": None, "requires_human": False, "human_reason": None
        }
        res = run_supervisor(state)
        self.assertEqual(res["intent"], "order_inquiry")
        self.assertEqual(res["next_worker"], "order_agent")

    def test_supervisor_routing_policy(self):
        state: MultiAgentState = {
            "messages": [{"role": "user", "content": "Chính sách đổi trả hàng và bảo hành như thế nào?"}],
            "fresh": [], "trace": {}, "tool_count": 0, "bound": {}, "complete": False,
            "intent": "unknown", "next_worker": "supervisor", "subagent_history": [],
            "sentiment": "neutral", "strict_mode": False, "consecutive_ood_count": 0,
            "action_proposal": None, "requires_human": False, "human_reason": None
        }
        res = run_supervisor(state)
        self.assertEqual(res["intent"], "policy_knowledge")
        self.assertEqual(res["next_worker"], "policy_agent")

    def test_supervisor_routing_dispute(self):
        state: MultiAgentState = {
            "messages": [{"role": "user", "content": "Tôi muốn hủy đơn hàng O-999 vì đặt nhầm size"}],
            "fresh": [], "trace": {}, "tool_count": 0, "bound": {}, "complete": False,
            "intent": "unknown", "next_worker": "supervisor", "subagent_history": [],
            "sentiment": "neutral", "strict_mode": False, "consecutive_ood_count": 0,
            "action_proposal": None, "requires_human": False, "human_reason": None
        }
        res = run_supervisor(state)
        self.assertEqual(res["intent"], "dispute_complaint")
        self.assertEqual(res["next_worker"], "dispute_agent")

    def test_supervisor_routing_witty_ood(self):
        # General question about algorithm SAC
        state: MultiAgentState = {
            "messages": [{"role": "user", "content": "Giải thích thuật toán SAC cho mình với"}],
            "fresh": [], "trace": {}, "tool_count": 0, "bound": {}, "complete": False,
            "intent": "unknown", "next_worker": "supervisor", "subagent_history": [],
            "sentiment": "neutral", "strict_mode": False, "consecutive_ood_count": 0,
            "action_proposal": None, "requires_human": False, "human_reason": None
        }
        res = run_supervisor(state)
        self.assertEqual(res["intent"], "chitchat_general")
        self.assertEqual(res["next_worker"], "witty_agent")

    def test_supervisor_human_escalation(self):
        state: MultiAgentState = {
            "messages": [{"role": "user", "content": "Tôi cần gặp nhân viên tư vấn trực tiếp"}],
            "fresh": [], "trace": {}, "tool_count": 0, "bound": {}, "complete": False,
            "intent": "unknown", "next_worker": "supervisor", "subagent_history": [],
            "sentiment": "neutral", "strict_mode": False, "consecutive_ood_count": 0,
            "action_proposal": None, "requires_human": False, "human_reason": None
        }
        res = run_supervisor(state)
        self.assertTrue(res["requires_human"])
        self.assertTrue(res["complete"])
        self.assertIn("kết nối tới nhân viên tư vấn", res["fresh"][-1]["content"])

    def test_supervisor_forbidden_topic(self):
        state: MultiAgentState = {
            "messages": [{"role": "user", "content": "Tôi bị sốt cao uống kháng sinh gì?"}],
            "fresh": [], "trace": {}, "tool_count": 0, "bound": {}, "complete": False,
            "intent": "unknown", "next_worker": "supervisor", "subagent_history": [],
            "sentiment": "neutral", "strict_mode": False, "consecutive_ood_count": 0,
            "action_proposal": None, "requires_human": False, "human_reason": None
        }
        res = run_supervisor(state)
        self.assertEqual(res["intent"], "forbidden_topic")
        self.assertTrue(res["complete"])
        self.assertIn("chuyên môn y tế", res["fresh"][-1]["content"])

    def test_end_to_end_witty_pivot_flow(self):
        # Full LangGraph execution of general question
        res = run_multiagent(
            self.gateway,
            "Thời tiết hôm nay thế nào?",
            [],
            self.execute,
            self.identity
        )
        self.assertEqual(res["intent"], "chitchat_general")
        self.assertIn("Thuật toán SAC", res["message"])
        self.assertIn("witty_agent", " ".join(res["subagent_history"]))

    def test_witty_pivot_strict_mode_when_angry(self):
        # Angry user asking OOD question -> No jokes!
        res = run_multiagent(
            self.gateway,
            "Shop lừa đảo làm ăn quá tệ, giải thích thuật toán SAC đi xem nào!",
            [],
            self.execute,
            self.identity
        )
        self.assertEqual(res["sentiment"], "negative")
        self.assertIn("chỉ có thể hỗ trợ về đơn hàng và sản phẩm", res["message"])
        self.assertIn("strict_redirect", " ".join(res["subagent_history"]))


if __name__ == "__main__":
    unittest.main()
