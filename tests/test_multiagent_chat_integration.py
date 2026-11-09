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
            if tool_name == "search_knowledge":
                res_data = {}
                try:
                    res_data = json.loads(tool_res) if isinstance(tool_res, str) else tool_res
                except Exception:
                    pass
                if isinstance(res_data, dict) and not res_data.get("results"):
                    return {
                        "message": {
                            "role": "assistant",
                            "content": (
                                "Dạ hiện tại kho tri thức chính sách của shop chưa có tài liệu quy định phù hợp cho trường hợp khiếu nại này. "
                                "Để đảm bảo quyền lợi của anh/chị, em xin phép ghi nhận thông tin và chuyển chuyên viên CSKH hỗ trợ trực tiếp, "
                                "không tự ý áp dụng quy định chưa được xác thực nhé ạ!"
                            ),
                        },
                        "done_reason": "stop",
                        "prompt_eval_count": 80,
                        "eval_count": 30,
                    }
            return {
                "message": {
                    "role": "assistant",
                    "content": f"Dạ kết quả tra cứu từ hệ thống ({tool_name}): {tool_res}. Em đã cập nhật thông tin cho anh/chị rồi ạ!"
                },
                "done_reason": "stop",
                "prompt_eval_count": 80,
                "eval_count": 25
            }

        # If tools are allowed and user asks about policy
        if allow_tools and any(kw in content.lower() for kw in ("chính sách", "quy định", "chính sách bảo hành")):
            return {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "search_knowledge",
                                "arguments": {"query": "chính sách bảo hành đổi mới hàng lỗi"}
                            }
                        }
                    ]
                },
                "done_reason": "tool_calls",
                "prompt_eval_count": 60,
                "eval_count": 15
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


class ScriptedWorkerGateway:
    """Model double for the legacy dispute worker: one scripted response per call, each a dict or a function of the transcript."""

    def __init__(self, *steps):
        self.steps, self.inputs = list(steps), []

    def inspect(self):
        return {"name": "mock-legacy-dispute", "digest": "mock-digest", "provider": "custom", "ollama_version": "mock-0.1"}

    def chat(self, messages, allow_tools, timeout):
        self.inputs.append(copy.deepcopy(messages))
        step = self.steps[len(self.inputs) - 1]
        return step(messages) if callable(step) else copy.deepcopy(step)


def tool_call(name, args):
    return {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]},
            "prompt_eval_count": 40, "eval_count": 10}


def text(content):
    return {"message": {"role": "assistant", "content": content}, "prompt_eval_count": 40, "eval_count": 10}


class MultiAgentChatIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        from legacy_seed_fixture import seed_legacy_unit_fixture
        self.store = seed_legacy_unit_fixture(BusinessStore(Path(self.temp.name) / "business.sqlite3"))
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
        with self.store.connection() as db:
            db.execute(
                """INSERT INTO shipments (
                    shipment_id, order_id, source_system, external_shipment_id, carrier, tracking_code,
                    status, carrier_status_raw, current_area, estimated_delivery_at, delivered_at,
                    delivery_attempts, shipper_name, shipper_phone_masked, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "shp_chat_101", "O-101", "marketplace_sim", "EXT-SHP-CHAT-101",
                    "Giao Hàng Tiết Kiệm (GHTK)", "GHTK.VN.0918231",
                    "in_transit", "transporting", "Bưu cục Tân Bình, TP.HCM",
                    1794218400.0, None, 0, "Nguyễn Văn Nam", "090****334", 1794132000.0,
                ),
            )
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

    # W3.2-D3/D7: the legacy dispute worker is driven by the model through the server tools. The scripted
    # branches, the warranty/stock heuristics and the old proposals (exchange_1to1, size_exchange,
    # cancel_order + pending_staff_approval) are gone, and so are the tests that asserted them. What they
    # protected still holds and is asserted below: ownership comes from the tool result, a refused lookup is
    # answered from the tool and not by the model, and only prepare_order_action opens a request form.
    # "No unsupported fee or replacement promise" is now the final-answer check (tests/test_r1_w3_2_answer_check.py).

    def legacy_chat(self, model, text_in, customer="C-001"):
        app = Application(self.store, {}, infer=model, orchestrator="multi_agent")
        return app.chat(customer, {"text": text_in, "conversation_id": self.cid, "request_id": str(uuid.uuid4())})

    def test_dispute_defect_is_routed_to_the_model_driven_worker_without_any_proposal(self):
        model = ScriptedWorkerGateway(
            tool_call("get_order", {"order_id": "O-101"}),
            text("Em rất tiếc về sự cố ạ. Em đã xem đơn O-101; anh/chị gửi ảnh phần bị lỗi để em chuyển CSKH xử lý nhé."))
        result = self.legacy_chat(model, "Áo đơn O-101 bị kẹt khóa và bung chỉ, shop đổi 1-1 cho tôi")
        trace = result["trace"]
        self.assertEqual(trace["orchestrator"], "multiagent_langgraph")
        self.assertEqual(trace["supervisor_intent"], "dispute_complaint")
        self.assertEqual(trace["subagent_history"], ["supervisor:routed_to_dispute_agent", "dispute_agent:done"])
        self.assertEqual([t["name"] for t in trace["tools"]], ["get_order"])
        self.assertEqual(result["action"], "reply")
        self.assertNotIn("action_proposal", result)
        self.assertEqual(result["message"], "Em rất tiếc về sự cố ạ. Em đã xem đơn O-101; anh/chị gửi ảnh phần bị lỗi để em chuyển CSKH xử lý nhé.")
        self.assertEqual(model.inputs[0][0]["role"], "system")  # the worker prompt states principles, not a script
        self.assertNotIn("SOP", model.inputs[0][0]["content"])

    def test_dispute_size_exchange_opens_the_shared_request_form_with_the_matched_variant(self):
        model = ScriptedWorkerGateway(
            tool_call("prepare_order_action", {"order_id": "O-102", "action_type": "exchange", "target_variant": "size XL"}),
            text("Em đã mở form đổi hàng cho đơn O-102, anh/chị chọn lý do rồi bấm xác nhận nhé."))
        result = self.legacy_chat(model, "Đơn O-102 mặc chật quá, muốn đổi sang size XL")  # O-102 holds size L today
        self.assertEqual(result["trace"]["supervisor_intent"], "dispute_complaint")
        self.assertEqual(result["action"], "choose_order_action_reason")
        self.assertEqual(result["order"]["id"], "O-102")
        self.assertEqual(result["order_action"], {"action_type": "exchange", "exchange_kind": "other_variant",
                                                  "target_variant_id": "P-102-XL-Đen", "order_id": "O-102"})
        self.assertNotIn("action_proposal", result)
        with self.store.connection() as db:  # opening the form creates nothing: only the customer's own confirmation does
            self.assertEqual(db.execute("SELECT COUNT(*) FROM order_action_requests").fetchone()[0], 0)

    def test_dispute_reports_the_server_condition_when_the_order_is_not_eligible(self):
        def verdict(messages):
            return text("Đơn O-102 chưa thể hủy: " + json.loads(messages[-1]["content"])["ineligible_reason"]["message"])
        model = ScriptedWorkerGateway(tool_call("prepare_order_action", {"order_id": "O-102", "action_type": "cancel"}), verdict)
        result = self.legacy_chat(model, "Tôi muốn hủy đơn O-102")
        self.assertEqual(result["action"], "reply")
        self.assertNotIn("order_action", result)
        self.assertIn("Only a pending order can be cancelled; this order is delivered", result["message"])

    def test_dispute_answers_a_foreign_or_missing_order_from_the_tool_and_not_from_the_model(self):
        for order_id in ("O-202", "O-999"):  # O-202 belongs to another customer, O-999 does not exist
            model = ScriptedWorkerGateway(
                tool_call("get_order", {"order_id": order_id}),
                text("Shop sẽ đổi mới 1-1 miễn phí cho đơn của anh/chị ạ."))  # must never be reached
            result = self.legacy_chat(model, f"Áo đơn {order_id} bị kẹt khóa và bung chỉ, shop đổi giúp tôi")
            with self.subTest(order_id=order_id):
                self.assertEqual(len(model.inputs), 1)
                self.assertIn("Không tìm thấy đơn hàng", result["message"])
                self.assertNotIn("đổi mới", result["message"].lower())
                self.assertNotIn("miễn phí", result["message"].lower())
                self.assertNotIn("Áo polo", json.dumps(result, ensure_ascii=False))  # nothing of the other customer's order
                self.assertEqual(result["action"], "reply")
                self.assertNotIn("action_proposal", result)

    def test_human_support_escalation_in_chat(self):
        result = self.chat("Tôi cần gặp nhân viên tư vấn trực tiếp ngay bây giờ")
        self.assertEqual(result["action"], "reply")
        self.assertIn("kết nối tới nhân viên tư vấn", result["message"])
        trace = result["trace"]
        self.assertEqual(trace["orchestrator"], "multiagent_langgraph")


if __name__ == "__main__":
    unittest.main()
