import copy
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

    def test_supervisor_multi_turn_order_continuation_routing(self):
        # 1. "ngoài ra còn thông tin nào không" after order discussion
        order_history_state: MultiAgentState = {
            "messages": [
                {"role": "user", "content": "giải thích giúp tôi đơn tôi đang select"},
                {"role": "assistant", "content": "Danh sách đơn: O-819125, O-819126, O-819127"},
                {"role": "user", "content": "O-819125 cái này"},
                {"role": "assistant", "content": "Đơn O-819125: Chờ xử lý. Áo sơ mi lụa công sở."},
                {"role": "user", "content": "ngoài ra còn thông tin nào không"}
            ],
            "fresh": [], "trace": {}, "tool_count": 0, "bound": {"context": {"order_id": "O-819125"}},
            "complete": False, "intent": "unknown", "next_worker": "supervisor",
            "subagent_history": ["supervisor:routed_to_order_agent", "order_agent:done"],
            "sentiment": "neutral", "strict_mode": False, "consecutive_ood_count": 0,
            "action_proposal": None, "requires_human": False, "human_reason": None
        }
        res1 = run_supervisor(order_history_state)
        self.assertEqual(res1["intent"], "order_inquiry")
        self.assertEqual(res1["next_worker"], "order_agent")
        self.assertEqual(res1["trace"].get("routing_reason"), "order_context_continuation")

        # 2. "còn cái quần tây ống thì sao ? shop tên gì"
        state2 = copy.deepcopy(order_history_state)
        state2["messages"][-1] = {"role": "user", "content": "còn cái quần tây ống thì sao ? shop tên gì"}
        res2 = run_supervisor(state2)
        self.assertEqual(res2["intent"], "order_inquiry")
        self.assertEqual(res2["next_worker"], "order_agent")

        # 3. Action prompts: "thực hiện đi ơ ?" / "kiểm tra đi"
        for action_text in ["thực hiện đi ơ ?", "kiểm tra đi", "check giúp"]:
            state3 = copy.deepcopy(order_history_state)
            state3["messages"][-1] = {"role": "user", "content": action_text}
            res3 = run_supervisor(state3)
            self.assertEqual(res3["intent"], "order_inquiry")
            self.assertEqual(res3["next_worker"], "order_agent")

        # 4. Explicit general question while order is in history switches to witty_agent
        state4 = copy.deepcopy(order_history_state)
        state4["messages"][-1] = {"role": "user", "content": "Giải thích thuật toán SAC cho mình"}
        res4 = run_supervisor(state4)
        self.assertEqual(res4["intent"], "chitchat_general")
        self.assertEqual(res4["next_worker"], "witty_agent")

        # 5. Fresh product/store inquiry without previous order history
        fresh_product_state: MultiAgentState = {
            "messages": [{"role": "user", "content": "cái quần tây ống là sao ? shop tên gì"}],
            "fresh": [], "trace": {}, "tool_count": 0, "bound": {},
            "complete": False, "intent": "unknown", "next_worker": "supervisor",
            "subagent_history": [], "sentiment": "neutral", "strict_mode": False,
            "consecutive_ood_count": 0, "action_proposal": None,
            "requires_human": False, "human_reason": None
        }
        res5 = run_supervisor(fresh_product_state)
        self.assertEqual(res5["intent"], "order_inquiry")
        self.assertEqual(res5["next_worker"], "order_agent")
        self.assertEqual(res5["trace"].get("routing_reason"), "order_or_product_keywords")

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
