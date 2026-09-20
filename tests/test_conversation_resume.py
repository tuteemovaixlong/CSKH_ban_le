"""Unit tests for Multi-turn Chat History Resume, List Conversations and Session Continuity."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.http.routes import api_result
from retailops.core import ApiError


class FakeModel:
    def __init__(self):
        self.replies = []
        self.history_received = []

    def inspect(self):
        return {"model": "test-model", "provider": "custom", "features": ["chat", "tools"]}

    def chat(self, messages, allow_tools=True, timeout=30):
        self.history_received.append(messages)
        if self.replies:
            reply = self.replies.pop(0)
            if callable(reply):
                return reply(messages)
            return reply
        return {
            "message": {"role": "assistant", "content": "Phản hồi mẫu từ trợ lý."},
            "done_reason": "stop",
            "eval_count": 12,
            "prompt_eval_count": 80
        }


class TestConversationResume(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.tmp.close()
        self.store = BusinessStore(self.tmp.name, create=True)
        self.store.seed()
        self.model = FakeModel()
        self.app = Application(self.store, {}, self.model, role="customer")

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_list_conversations_empty(self):
        convs = self.store.list_conversations("C-001")
        self.assertEqual(convs, [])

    def test_conversation_ttl_is_7_days(self):
        res = self.store.new_conversation("C-001")
        cid = res["conversation_id"]
        conv = self.store.conversation("C-001", cid)
        # Verify expires_at is roughly 7 days in the future (within 10s tolerance)
        now = time.time()
        self.assertGreater(conv["expires_at"], now + 6 * 86400)
        self.assertLessEqual(conv["expires_at"], now + 7 * 86400 + 5)

    def test_list_conversations_and_transcript_lifecycle(self):
        conv_res = self.app.new_conversation("C-001", {"provider_id": "custom"})
        cid = conv_res["conversation_id"]

        # 1. Chat turn 1
        self.model.replies = [{
            "message": {"role": "assistant", "content": "Dạ em chào anh/chị, em có thể giúp gì về đơn hàng ạ?"},
            "done_reason": "stop"
        }]
        turn1_res = self.app.chat("C-001", {
            "text": "Kiểm tra đơn O-101 giúp tôi",
            "conversation_id": cid,
            "request_id": "req-turn-1-12345678"
        })
        self.assertIn("Dạ em chào", turn1_res["message"])

        # 2. List conversations via store
        convs = self.store.list_conversations("C-001")
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["id"], cid)
        self.assertEqual(convs[0]["turns_count"], 1)
        self.assertIn("O-101", convs[0]["snippet"])

        # 3. HTTP GET /api/conversations
        status, http_list = api_result(self.app, "C-001", "GET", "/api/conversations")
        self.assertEqual(status, 200)
        self.assertIn("conversations", http_list)
        self.assertEqual(len(http_list["conversations"]), 1)
        self.assertEqual(http_list["conversations"][0]["id"], cid)

        # 4. HTTP GET /api/conversations/<cid>/messages
        status, transcript = api_result(self.app, "C-001", "GET", f"/api/conversations/{cid}/messages")
        self.assertEqual(status, 200)
        self.assertEqual(len(transcript["turns"]), 1)
        turn_data = transcript["turns"][0]
        res_payload = json.loads(turn_data["result"])
        self.assertIn("Dạ em chào", res_payload["message"])

        # 5. Multi-turn continuity: chat turn 2 in the same conversation
        self.model.replies = [{
            "message": {"role": "assistant", "content": "Đơn O-101 của anh/chị đang được vận chuyển ạ."},
            "done_reason": "stop"
        }]
        turn2_res = self.app.chat("C-001", {
            "text": "Đơn này bao giờ tới nơi?",
            "conversation_id": cid,
            "request_id": "req-turn-2-12345678"
        })
        self.assertIn("đang được vận chuyển", turn2_res["message"])

        # Verify model history received in turn 2 included turn 1's Q&A
        self.assertGreaterEqual(len(self.model.history_received), 2)
        turn2_prompt = self.model.history_received[-1]
        user_msgs = [m for m in turn2_prompt if m.get("role") == "user"]
        self.assertTrue(any("O-101" in m.get("content", "") for m in user_msgs))

        # Check transcript now has 2 turns
        status, transcript_after = api_result(self.app, "C-001", "GET", f"/api/conversations/{cid}/messages")
        self.assertEqual(status, 200)
        self.assertEqual(len(transcript_after["turns"]), 2)

    def test_conversation_privacy_isolation(self):
        # Create conversation for Customer C-001
        res = self.app.new_conversation("C-001", {"provider_id": "custom"})
        cid = res["conversation_id"]

        self.model.replies = [{
            "message": {"role": "assistant", "content": "Bí mật của C-001"},
            "done_reason": "stop"
        }]
        self.app.chat("C-001", {
            "text": "Thông tin riêng tư",
            "conversation_id": cid,
            "request_id": "req-privacy-1-12345"
        })

        # Customer C-002 tries to list conversations -> must NOT see C-001's conversation
        convs_c002 = self.store.list_conversations("C-002")
        self.assertEqual(convs_c002, [])

        status, http_list_c002 = api_result(self.app, "C-002", "GET", "/api/conversations")
        self.assertEqual(status, 200)
        self.assertEqual(http_list_c002["conversations"], [])

        # Customer C-002 tries to access C-001's transcript directly -> must receive 403 Forbidden
        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, "C-002", "GET", f"/api/conversations/{cid}/messages")
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, "permission_denied")


if __name__ == "__main__":
    unittest.main()
