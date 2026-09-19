"""Integration test for Multi-Agent LangGraph orchestration in Application.chat()."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from retailops.business.application import Application
from retailops.business.store import BusinessStore


class MockMultiAgentChatGateway:
    """Mock LLM gateway capable of handling supervisor routing, tool-calling and response generation."""
    def __init__(self):
        self.inputs = []

    def inspect(self):
        return {
            "name": "mock-qwen-multiagent",
            "digest": "mock-digest-multiagent",
            "provider": "custom",
            "ollama_version": "mock-0.1"
        }

    def chat(self, messages, allow_tools, timeout):
        self.inputs.append(copy.deepcopy(messages))
        last_msg = messages[-1]
        content = last_msg.get("content", "")

        # Check if this is a tool execution result callback
        if last_msg.get("role") == "tool":
            tool_name = last_msg.get("tool_name", "")
            tool_res = last_msg.get("content", "")
            return {
                "message": {
                    "role": "assistant",
                    "content": f"Dạ kết quả tra cứu từ hệ thống ({tool_name}): {tool_res}. Em đã cập nhật thông tin cho anh/chị rồi ạ!"
                },
                "done_reason": "stop",
                "prompt_eval_count": 80,
                "eval_count": 25
            }

        # If tools are allowed and user asks about order tracking
        if allow_tools and any(kw in content.lower() for kw in ("kiểm tra", "tra cứu", "o-101", "đơn hàng")):
            return {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "track_shipment",
                                "arguments": {"order_id": "O-101"}
                            }
                        }
                    ]
                },
                "done_reason": "tool_calls",
                "prompt_eval_count": 60,
                "eval_count": 15
            }

        # Default natural language reply (e.g. for witty_agent or general queries)
        return {
            "message": {
                "role": "assistant",
                "content": "Dạ shop chào anh/chị! Chúc anh/chị một ngày thật nhiều niềm vui. Em có thể hỗ trợ gì cho anh/chị hôm nay ạ?"
            },
            "done_reason": "stop",
            "prompt_eval_count": 50,
            "eval_count": 20
        }


class MultiAgentChatIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = BusinessStore(Path(self.temp.name) / "business.sqlite3")
        self.store.seed()
        self.gateway = MockMultiAgentChatGateway()
        self.app = Application(self.store, {}, infer=self.gateway, orchestrator="multi_agent")
        self.cid = self.store.new_conversation("C-001")["conversation_id"]

    def chat(self, text, cid=None, customer="C-001"):
        body = {
            "text": text,
            "conversation_id": cid or self.cid,
            "request_id": str(uuid.uuid4())
        }
        return self.app.chat(customer, body)

    def test_chitchat_routes_to_witty_agent_with_multiagent_trace(self):
        result = self.chat("Thời tiết hôm nay đẹp quá shop ơi!")
        self.assertEqual(result["action"], "reply")
        self.assertEqual(result["source"], "llm_agent")
        self.assertTrue(result["model_used"])
        trace = result["trace"]
        self.assertEqual(trace["orchestrator"], "multiagent_langgraph")
        self.assertEqual(trace["supervisor_intent"], "chitchat_general")
        self.assertIn("witty_agent", " ".join(trace["subagent_history"]))

        # Confirm turn persisted in SQLite conversation history
        history = self.store.history("C-001", self.cid)
        self.assertGreaterEqual(len(history), 2)
        self.assertEqual(history[0]["content"], "Thời tiết hôm nay đẹp quá shop ơi!")

    def test_order_inquiry_routes_to_order_agent_and_tracks_shipment(self):
        result = self.chat("Kiểm tra giúp tôi đơn hàng O-101 xem đang ở đâu nhé")
        self.assertEqual(result["action"], "reply")
        trace = result["trace"]
        self.assertEqual(trace["orchestrator"], "multiagent_langgraph")
        self.assertEqual(trace["supervisor_intent"], "order_inquiry")
        self.assertIn("order_agent", " ".join(trace["subagent_history"]))

        # Tool execution check: track_shipment was called
        tool_names = [t.get("name") for t in trace.get("tools", [])]
        self.assertIn("track_shipment", tool_names)

        # Result includes shipment context
        self.assertIsNotNone(result.get("shipment"))
        self.assertEqual(result["shipment"]["carrier"], "Giao Hàng Tiết Kiệm (GHTK)")
        self.assertEqual(result["shipment"]["tracking_code"], "GHTK.VN.0918231")
        self.assertEqual(result["context"]["order_id"], "O-101")

    def test_dispute_defect_creates_exchange_1to1_proposal(self):
        result = self.chat("Áo đơn O-101 bị kẹt khóa và bung chỉ, shop đổi 1-1 cho tôi")
        self.assertEqual(result["action"], "reply")
        trace = result["trace"]
        self.assertEqual(trace["orchestrator"], "multiagent_langgraph")
        self.assertEqual(trace["supervisor_intent"], "dispute_complaint")
        self.assertIn("dispute_agent", " ".join(trace["subagent_history"]))

        proposal = result.get("action_proposal")
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal["action"], "exchange_1to1")
        self.assertEqual(proposal["order_id"], "O-101")
        self.assertEqual(proposal["status"], "pending_staff_approval")

    def test_dispute_size_creates_size_exchange_proposal(self):
        result = self.chat("Tôi thử áo đơn O-101 bị chật quá, muốn đổi sang size L")
        self.assertEqual(result["action"], "reply")
        trace = result["trace"]
        self.assertEqual(trace["orchestrator"], "multiagent_langgraph")
        self.assertEqual(trace["supervisor_intent"], "dispute_complaint")

        proposal = result.get("action_proposal")
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal["action"], "size_exchange")
        self.assertEqual(proposal["target_size"], "L")
        self.assertEqual(proposal["status"], "pending_staff_approval")

    def test_human_support_escalation_in_chat(self):
        result = self.chat("Tôi cần gặp nhân viên tư vấn trực tiếp ngay bây giờ")
        self.assertEqual(result["action"], "reply")
        self.assertIn("kết nối tới nhân viên tư vấn", result["message"])
        trace = result["trace"]
        self.assertEqual(trace["orchestrator"], "multiagent_langgraph")


if __name__ == "__main__":
    unittest.main()
