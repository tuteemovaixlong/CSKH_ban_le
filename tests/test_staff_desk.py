"""Tests for Staff Live Chat Console (Escalations, Transcript, Reply, Resolve)."""
import json
import sqlite3
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from retailops.core import ApiError
from retailops.business.store import BusinessStore
from retailops.business.schema import initialize as initialize_schema
from retailops.business.export import export_datasets
from retailops.http.routes import api_result


class DummyApp:
    def __init__(self, store, role="staff"):
        self.store = store
        self.role = role
        from retailops.business.permissions import ROLE_PERMISSIONS
        self.permissions = set(ROLE_PERMISSIONS.get(role, set()))
        self.infer = None
        self.api_infer = None
        self.catalog = {"products": []}

    def require_permission(self, perm):
        if perm not in self.permissions:
            raise ApiError(403, 'permission_denied', 'Tài khoản này không có quyền thực hiện thao tác.')


class StaffDeskTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "test_staff.sqlite3"
        self.store = BusinessStore(self.db_path, create=True)
        self.store.seed()
        self.app = DummyApp(self.store)

        self.cid = str(uuid.uuid4())
        with self.store.connection(write=True) as db:
            db.execute("INSERT INTO conversations(id, customer_id, order_id, expires_at) VALUES (?,?,?,?)",
                       (self.cid, "C-001", "O-101", time.time() + 1800))

        # Initial turn
        snapshot = self.store.conversation("C-001", self.cid)
        messages = [{"role": "user", "content": "Tôi muốn đổi hàng sang size L ngay"}]
        result = {"message": "Đang chuyển máy cho nhân viên...", "context": {"order_id": "O-101", "product_id": None}, "trace": {}}
        self.turn_id = self.store.finish_turn("C-001", snapshot, "req-1", "hash-1", messages, result, {})

        # Escalation feedback
        self.store.record_feedback("C-001", {
            "conversation_id": self.cid,
            "turn_id": self.turn_id,
            "feedback_type": "human_handoff",
            "reason_code": "size_exchange_request",
            "comment": "Khách cần đổi size áo L"
        })

    def test_escalations_list(self):
        escalations = self.store.escalations()
        self.assertEqual(len(escalations), 1)
        esc = escalations[0]
        self.assertEqual(esc["conversation_id"], self.cid)
        self.assertEqual(esc["customer_id"], "C-001")
        self.assertEqual(esc["reason_code"], "size_exchange_request")
        self.assertEqual(esc["sentiment_flag"], None)  # Not resolved yet

    def test_conversation_transcript(self):
        data = self.store.conversation_transcript(self.cid)
        self.assertIsNotNone(data["conversation"])
        self.assertEqual(data["conversation"]["id"], self.cid)
        self.assertGreaterEqual(len(data["turns"]), 1)
        self.assertGreaterEqual(len(data["feedbacks"]), 1)

    def test_staff_reply_and_resolve(self):
        reply_res = self.store.staff_reply(
            "C-001", self.cid, "Nguyễn Mai Anh",
            "Dạ em chào anh/chị, em đã kiểm tra kho và còn sẵn 1 áo size L để đổi cho mình ạ."
        )
        self.assertEqual(reply_res["status"], "ok")
        self.assertEqual(reply_res["staff_name"], "Nguyễn Mai Anh")
        self.assertIn("size L", reply_res["message"])

        # Verify turn was created
        transcript = self.store.conversation_transcript(self.cid)
        self.assertEqual(len(transcript["turns"]), 2)
        last_turn = transcript["turns"][-1]
        res = json.loads(last_turn["result"])
        self.assertEqual(res["author"], "staff")
        self.assertEqual(res["staff_name"], "Nguyễn Mai Anh")

        # Verify feedback updated to resolved
        feedbacks = transcript["feedbacks"]
        handoff = [f for f in feedbacks if f["feedback_type"] == "human_handoff"][0]
        self.assertEqual(handoff["reason_code"], "resolved")

        # Resolve escalation explicitly
        resolve_res = self.store.resolve_escalation(self.cid, "Nguyễn Mai Anh")
        self.assertTrue(resolve_res["resolved"])

    def test_http_staff_routes(self):
        # 1. GET /api/staff/escalations
        status, res = api_result(self.app, "C-001", "GET", "/api/staff/escalations")
        self.assertEqual(status, 200)
        self.assertIn("escalations", res)
        self.assertEqual(len(res["escalations"]), 1)

        # 2. GET /api/staff/conversations/<cid>/messages
        status, res = api_result(self.app, "C-001", "GET", f"/api/staff/conversations/{self.cid}/messages")
        self.assertEqual(status, 200)
        self.assertIn("turns", res)

        # 3. POST /api/staff/reply
        status, res = api_result(self.app, "C-001", "POST", "/api/staff/reply", {
            "conversation_id": self.cid,
            "message": "Em đã lưu thông tin đổi hàng cho mình rồi ạ!",
            "staff_name": "Nguyễn Mai Anh"
        })
        self.assertEqual(status, 200)
        self.assertEqual(res["status"], "ok")

        # 4. POST /api/staff/resolve
        status, res = api_result(self.app, "C-001", "POST", "/api/staff/resolve", {
            "conversation_id": self.cid,
            "staff_name": "Nguyễn Mai Anh"
        })
        self.assertEqual(status, 200)
        self.assertTrue(res["resolved"])

        # 5. RBAC: Customer without staff permission is rejected with 403
        customer_app = DummyApp(self.store, role="customer")
        with self.assertRaises(ApiError) as ctx:
            api_result(customer_app, "C-001", "GET", "/api/staff/escalations")
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, "permission_denied")

        with self.assertRaises(ApiError) as ctx:
            api_result(customer_app, "C-001", "POST", "/api/staff/reply", {
                "conversation_id": self.cid,
                "message": "Trái phép",
                "staff_name": "Hacker"
            })
        self.assertEqual(ctx.exception.status, 403)

        with self.assertRaises(ApiError) as ctx:
            api_result(customer_app, "C-001", "POST", "/api/staff/resolve", {
                "conversation_id": self.cid,
                "staff_name": "Hacker"
            })
        self.assertEqual(ctx.exception.status, 403)

        # 6. Customer can access their OWN conversation messages, stranger gets 403
        status, res = api_result(customer_app, "C-001", "GET", f"/api/staff/conversations/{self.cid}/messages")
        self.assertEqual(status, 200)

        with self.assertRaises(ApiError) as ctx:
            api_result(customer_app, "C-999", "GET", f"/api/staff/conversations/{self.cid}/messages")
        self.assertEqual(ctx.exception.status, 403)

    def test_dpo_export_uses_staff_reply_as_gold_chosen(self):
        # Staff replies
        self.store.staff_reply(
            "C-001", self.cid, "Nguyễn Mai Anh",
            "Dạ em là Mai Anh, em hỗ trợ giữ ngay 1 áo size L cho đơn O-101 của mình ạ."
        )

        with self.store.connection() as db:
            stats = export_datasets(db, self.temp_dir.name)

        self.assertGreaterEqual(stats["dpo_samples"], 1)
        dpo_path = Path(stats["dpo_path"])
        with open(dpo_path, encoding="utf-8") as f:
            lines = [json.loads(l) for l in f.readlines()]
            matched = [l for l in lines if l["conversation_id"] == self.cid]
            self.assertEqual(len(matched), 1)
            record = matched[0]
            # Verify the chosen text is the actual staff reply!
            self.assertEqual(record["chosen"], "Dạ em là Mai Anh, em hỗ trợ giữ ngay 1 áo size L cho đơn O-101 của mình ạ.")
            self.assertEqual(record["rejected"], "Đang chuyển máy cho nhân viên...")

    def test_customer_message_and_two_way_chat(self):
        # 1. Customer sends message in live human mode via HTTP POST /api/staff/customer-message
        status, res = api_result(self.app, "C-001", "POST", "/api/staff/customer-message", {
            "conversation_id": self.cid,
            "message": "hello shop ơi hỗ trợ em"
        })
        self.assertEqual(status, 200)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["message"], "hello shop ơi hỗ trợ em")

        # 2. Check escalation feedback comment is updated with customer's latest message
        escalations = self.store.escalations()
        self.assertEqual(len(escalations), 1)
        self.assertEqual(escalations[0]["comment"], "hello shop ơi hỗ trợ em")

        # 3. Staff replies via POST /api/staff/reply
        status, res = api_result(self.app, "C-001", "POST", "/api/staff/reply", {
            "conversation_id": self.cid,
            "message": "Dạ chào bạn, Mai Anh CSKH nghe đây ạ!",
            "staff_name": "Nguyễn Mai Anh (Chuyên viên CSKH)"
        })
        self.assertEqual(status, 200)
        self.assertEqual(res["status"], "ok")

        # 4. Check transcript has both customer message and staff reply
        status, transcript = api_result(self.app, "C-001", "GET", f"/api/staff/conversations/{self.cid}/messages")
        self.assertEqual(status, 200)
        turns = transcript["turns"]
        self.assertGreaterEqual(len(turns), 3)  # initial turn + customer msg + staff reply

        # Check customer turn
        cust_turn = json.loads(turns[1]["messages"])
        self.assertEqual(cust_turn[0]["role"], "user")
        self.assertEqual(cust_turn[0]["content"], "hello shop ơi hỗ trợ em")

        # Check staff turn
        staff_turn = json.loads(turns[2]["messages"])
        staff_res = json.loads(turns[2]["result"])
        self.assertEqual(staff_turn[0]["role"], "assistant")
        self.assertEqual(staff_turn[0]["content"], "Dạ chào bạn, Mai Anh CSKH nghe đây ạ!")
        self.assertEqual(staff_res["author"], "staff")
        # 5. Verify conversation history handed back to Bot AI passes validate_messages
        from agent_protocol import validate_messages
        history = self.store.history("C-001", self.cid)
        self.assertGreaterEqual(len(history), 2)
        # Check that appending a new user question to history is 100% valid under agent_protocol!
        new_messages = history + [{"role": "user", "content": "áo thun của tôi sao rồi"}]
        validated = validate_messages(new_messages)
        self.assertEqual(len(validated), len(new_messages))


if __name__ == "__main__":
    unittest.main()


