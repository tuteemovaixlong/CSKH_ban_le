"""Tests for feedback collection (CSAT, Like/Dislike, Human Handoff) and dataset export."""
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
from retailops.http.routes import api_result
from retailops.business.export import export_datasets


class FeedbackStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "test_store.sqlite3"
        self.store = BusinessStore(self.db_path, create=True)
        self.store.seed()

        self.cid_1 = str(uuid.uuid4())
        self.cid_2 = str(uuid.uuid4())

        # Create a test conversation and turn
        with self.store.connection(write=True) as db:
            db.execute("INSERT INTO conversations(id, customer_id, expires_at) VALUES (?,?,?)",
                       (self.cid_1, "C-001", time.time() + 1800))
            db.execute("INSERT INTO conversations(id, customer_id, expires_at) VALUES (?,?,?)",
                       (self.cid_2, "C-002", time.time() + 1800))

    def test_record_session_csat(self):
        res = self.store.record_feedback("C-001", {
            "conversation_id": self.cid_1,
            "feedback_type": "session_csat",
            "rating": 5,
            "comment": "Dịch vụ rất tuyệt vời!"
        })
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["feedback_type"], "session_csat")
        self.assertIsNotNone(res["feedback_id"])

        feedbacks = self.store.feedbacks(customer="C-001")
        self.assertEqual(len(feedbacks), 1)
        self.assertEqual(feedbacks[0]["rating"], 5)
        self.assertEqual(feedbacks[0]["comment"], "Dịch vụ rất tuyệt vời!")

    def test_record_turn_like_and_dislike(self):
        snapshot = self.store.conversation("C-001", self.cid_1)
        messages = [{"role": "user", "content": "Tra cứu đơn O-101"},
                    {"role": "assistant", "content": "Đơn hàng O-101 đang chờ xử lý"}]
        result = {"context": {"order_id": "O-101", "product_id": None}, "trace": {}}
        turn_id = self.store.finish_turn("C-001", snapshot, "req-101", "hash-101", messages, result, {})
        self.assertIsNotNone(turn_id)
        self.assertEqual(result.get("turn_id"), turn_id)

        # Record positive feedback
        pos_res = self.store.record_feedback("C-001", {
            "conversation_id": self.cid_1,
            "turn_id": turn_id,
            "feedback_type": "turn_rating",
            "sentiment_flag": "positive"
        })
        self.assertEqual(pos_res["status"], "ok")

        # Record negative feedback with reason
        neg_res = self.store.record_feedback("C-001", {
            "conversation_id": self.cid_1,
            "turn_id": turn_id,
            "feedback_type": "turn_rating",
            "sentiment_flag": "negative",
            "reason_code": "wrong_info",
            "comment": "Thông tin đơn bị sai"
        })
        self.assertEqual(neg_res["status"], "ok")

        feedbacks = self.store.feedbacks(conversation_id=self.cid_1)
        self.assertEqual(len(feedbacks), 2)

    def test_record_human_handoff(self):
        res = self.store.record_feedback("C-001", {
            "conversation_id": self.cid_1,
            "feedback_type": "human_handoff",
            "reason_code": "user_requested",
            "comment": "Khách cần gặp tư vấn viên trực tiếp"
        })
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["feedback_type"], "human_handoff")

    def test_validation_errors(self):
        # Invalid feedback type
        with self.assertRaises(ApiError) as ctx:
            self.store.record_feedback("C-001", {"conversation_id": self.cid_1, "feedback_type": "unknown"})
        self.assertEqual(ctx.exception.code, "invalid_feedback_type")

        # Invalid rating range
        with self.assertRaises(ApiError) as ctx:
            self.store.record_feedback("C-001", {"conversation_id": self.cid_1, "feedback_type": "session_csat", "rating": 6})
        self.assertEqual(ctx.exception.code, "invalid_rating")

        # Conversation not owned by customer
        with self.assertRaises(ApiError) as ctx:
            self.store.record_feedback("C-001", {"conversation_id": self.cid_2, "feedback_type": "session_csat", "rating": 5})
        self.assertEqual(ctx.exception.code, "conversation_not_found")


class FeedbackRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "test_route.sqlite3"
        self.store = BusinessStore(self.db_path, create=True)
        self.store.seed()
        self.cid_route = str(uuid.uuid4())

        with self.store.connection(write=True) as db:
            db.execute("INSERT INTO conversations(id, customer_id, expires_at) VALUES (?,?,?)",
                       (self.cid_route, "C-001", time.time() + 1800))

        class MockApp:
            def __init__(self, store):
                self.store = store
                self.quota_store = None
                self.infer = None
                self.api_infer = None

        self.app = MockApp(self.store)

    def test_route_feedback_post(self):
        payload = {
            "conversation_id": self.cid_route,
            "feedback_type": "session_csat",
            "rating": 5,
            "comment": "Phản hồi qua HTTP route"
        }
        status, data = api_result(self.app, "C-001", "POST", "/api/feedback", payload)
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["feedback_type"], "session_csat")


class DatasetExportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "test_export.sqlite3"
        self.store = BusinessStore(self.db_path, create=True)
        self.store.seed()
        self.cid_export = str(uuid.uuid4())

        # Create conversation and turns
        with self.store.connection(write=True) as db:
            db.execute("INSERT INTO conversations(id, customer_id, expires_at) VALUES (?,?,?)",
                       (self.cid_export, "C-001", time.time() + 1800))

        snapshot = self.store.conversation("C-001", self.cid_export)
        
        # Turn 1: Positively rated
        messages_1 = [{"role": "user", "content": "Tra đơn O-101"},
                      {"role": "assistant", "content": "Đơn hàng O-101 đang chờ giao"}]
        res_1 = {"message": "Đơn hàng O-101 đang chờ giao", "context": {"order_id": "O-101", "product_id": None}, "trace": {}}
        t1 = self.store.finish_turn("C-001", snapshot, "req-301", "h-301", messages_1, res_1, {})
        self.store.record_feedback("C-001", {
            "conversation_id": self.cid_export,
            "turn_id": t1,
            "feedback_type": "turn_rating",
            "sentiment_flag": "positive"
        })

        # Turn 2: Negatively rated (for DPO)
        snapshot = self.store.conversation("C-001", self.cid_export)
        messages_2 = [{"role": "user", "content": "Tại sao giao chậm thế?"},
                      {"role": "assistant", "content": "Tôi không biết."}]
        res_2 = {"message": "Tôi không biết.", "context": {"order_id": "O-101", "product_id": None}, "trace": {}}
        t2 = self.store.finish_turn("C-001", snapshot, "req-302", "h-302", messages_2, res_2, {})
        self.store.record_feedback("C-001", {
            "conversation_id": self.cid_export,
            "turn_id": t2,
            "feedback_type": "turn_rating",
            "sentiment_flag": "negative",
            "reason_code": "tone_issue",
            "comment": "Cần giải thích lịch sự hơn"
        })

    def test_export_pipeline(self):
        with self.store.connection() as db:
            stats = export_datasets(db, self.temp_dir.name)

        self.assertGreaterEqual(stats["sft_samples"], 1)
        self.assertGreaterEqual(stats["dpo_samples"], 1)

        sft_path = Path(stats["sft_path"])
        dpo_path = Path(stats["dpo_path"])
        self.assertTrue(sft_path.exists())
        self.assertTrue(dpo_path.exists())

        # Validate SFT JSONL format
        with open(sft_path, encoding="utf-8") as f:
            lines = f.readlines()
            self.assertGreater(len(lines), 0)
            sample = json.loads(lines[0])
            self.assertIn("messages", sample)
            self.assertEqual(sample["messages"][0]["role"], "system")

        # Validate DPO JSONL format
        with open(dpo_path, encoding="utf-8") as f:
            lines = f.readlines()
            self.assertGreater(len(lines), 0)
            sample = json.loads(lines[0])
            self.assertIn("prompt", sample)
            self.assertIn("chosen", sample)
            self.assertIn("rejected", sample)
            self.assertEqual(sample["rejected"], "Tôi không biết.")


if __name__ == "__main__":
    unittest.main()
