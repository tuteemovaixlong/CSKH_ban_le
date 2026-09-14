"""Tests for 3-tier Cache Engineering: Exact, Semantic, and Tool Execution Cache."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from retailops.business.application import Application
from retailops.business.cache import SemanticCache, ToolCache, is_cacheable_query
from retailops.business.store import BusinessStore


class FakeAgent:
    def __init__(self, name="fake_agent"):
        self.name = name
        self.model = name
        self.call_count = 0

    def inspect(self):
        return {"name": self.name, "digest": "fixture", "provider": "custom", "agent_protocol": "retailops-agent-v1"}

    def chat(self, messages, allow_tools, timeout):
        self.call_count += 1
        return {
            "message": {"role": "assistant", "content": "Chính sách bảo hành và đổi trả trong 7 ngày làm việc."},
            "prompt_eval_count": 50,
            "eval_count": 25,
            "reported_cost_usd": 0.0,
            "reasoning": "Tra cứu chính sách bảo hành chung."
        }


class CacheEngineeringUnitTests(unittest.TestCase):
    def test_safety_filter_rejects_orders_and_mutations(self):
        # Safe queries
        self.assertTrue(is_cacheable_query("Chính sách đổi trả hàng như thế nào?"))
        self.assertTrue(is_cacheable_query("Thời gian giao hàng mất mấy ngày?"))
        self.assertTrue(is_cacheable_query("Shop có ship COD không?"))
        self.assertTrue(is_cacheable_query("giải thích thuật toán SAC"))

        # Unsafe queries: must bypass semantic cache to avoid returning stale/wrong personalized state
        self.assertFalse(is_cacheable_query("Kiểm tra đơn O-101"))
        self.assertFalse(is_cacheable_query("Xem chi tiết đơn o-205"))
        self.assertFalse(is_cacheable_query("Sản phẩm P-101 còn hàng không?"))
        self.assertFalse(is_cacheable_query("Tôi muốn hủy đơn hàng"))
        self.assertFalse(is_cacheable_query("Đổi địa chỉ nhận hàng giúp tôi"))
        self.assertFalse(is_cacheable_query("a"))  # too short
        self.assertFalse(is_cacheable_query(""))

    def test_semantic_cache_exact_and_similarity(self):
        cache = SemanticCache(min_similarity=0.65)

        # Store initial FAQ answer
        q = "Chính sách đổi trả hàng của shop trong bao lâu?"
        a = "Shop hỗ trợ đổi trả miễn phí trong vòng 7 ngày kể từ khi nhận hàng."
        entry_id = cache.store(q, a)
        self.assertIsNotNone(entry_id)

        # 1. Exact match lookup
        hit_exact = cache.lookup(q)
        self.assertIsNotNone(hit_exact)
        self.assertEqual(hit_exact["type"], "exact")
        self.assertEqual(hit_exact["similarity"], 1.0)
        self.assertEqual(hit_exact["answer"], a)
        self.assertEqual(hit_exact["hit_count"], 1)

        # 2. Semantic match lookup with varied wording
        related_q = "Cho tôi hỏi chính sách đổi trả hàng của shop?"
        hit_semantic = cache.lookup(related_q)
        self.assertIsNotNone(hit_semantic)
        self.assertEqual(hit_semantic["type"], "semantic")
        self.assertGreaterEqual(hit_semantic["similarity"], 0.65)
        self.assertEqual(hit_semantic["answer"], a)
        self.assertEqual(hit_semantic["hit_count"], 2)

        # 3. Unrelated query must miss
        unrelated_q = "Thời tiết Hà Nội hôm nay thế nào?"
        miss = cache.lookup(unrelated_q)
        self.assertIsNone(miss)

    def test_tool_cache_hit_and_mutation_invalidation(self):
        tc = ToolCache(default_ttl=60.0)
        customer = "C-001"
        args = {"order_id": "O-101"}
        dummy_order = {"id": "O-101", "status": "pending", "amount": 250000}

        # Initially miss
        self.assertIsNone(tc.get(customer, "get_order", args))

        # Cache order result
        tc.set(customer, "get_order", args, dummy_order)

        # Hit on second read
        cached = tc.get(customer, "get_order", args)
        self.assertEqual(cached, dummy_order)

        # Invalidate customer orders upon mutation
        removed = tc.invalidate(customer, order_id="O-101")
        self.assertEqual(removed, 1)

        # After invalidation, must miss
        self.assertIsNone(tc.get(customer, "get_order", args))


class ApplicationCacheIntegrationTests(unittest.TestCase):
    def test_application_chat_semantic_cache_fast_path(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "business.sqlite3"
            store = BusinessStore(db_path)
            store.seed()

            agent = FakeAgent("custom_model")
            token = "t" * 40
            tokens = {hashlib.sha256(token.encode()).hexdigest(): "C-001"}
            app = Application(store, tokens, infer=agent, api_infer=None)

            # Pre-seed semantic cache with FAQ
            app.semantic_cache.store(
                "Chính sách đổi trả hàng như thế nào?",
                "Shop hỗ trợ đổi trả trong vòng 7 ngày nếu lỗi nhà sản xuất."
            )

            # Create conversation
            cid = store.new_conversation("C-001", "custom")["conversation_id"]

            # Query with semantically similar wording
            body = {
                "conversation_id": cid,
                "text": "Chính sách đổi trả hàng như thế nào?",
                "request_id": "req_" + "1" * 28
            }

            result = app.chat("C-001", body)

            # Verification: fast-path returned without calling model!
            self.assertEqual(result["source"], "semantic_cache")
            self.assertFalse(result["model_used"])
            self.assertEqual(result["trace"]["cache_hit"], "exact")
            self.assertEqual(result["trace"]["latency_ms"], 5.0)
            self.assertEqual(result["trace"]["model_calls"], 0)
            self.assertEqual(agent.call_count, 0)  # Model was NEVER touched!

    def test_application_chat_semantic_similarity_hit_and_ingestion(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "business.sqlite3"
            store = BusinessStore(db_path)
            store.seed()

            agent = FakeAgent("custom_model")
            token = "t" * 40
            tokens = {hashlib.sha256(token.encode()).hexdigest(): "C-001"}
            app = Application(store, tokens, infer=agent, api_infer=None)

            cid = store.new_conversation("C-001", "custom")["conversation_id"]

            # 1. First turn: cache miss, agent is called and response is auto-cached!
            body1 = {
                "conversation_id": cid,
                "text": "Chính sách bảo hành sản phẩm?",
                "request_id": "req_" + "a" * 28
            }
            res1 = app.chat("C-001", body1)
            self.assertEqual(agent.call_count, 1)
            self.assertEqual(res1["source"], "llm_agent")

            # 2. Second turn: semantically similar query hits cache, agent is NOT called!
            cid2 = store.new_conversation("C-001", "custom")["conversation_id"]
            body2 = {
                "conversation_id": cid2,
                "text": "Cho tôi hỏi chính sách bảo hành sản phẩm?",
                "request_id": "req_" + "b" * 28
            }
            res2 = app.chat("C-001", body2)
            self.assertEqual(agent.call_count, 1)  # STILL 1! No model call!
            self.assertEqual(res2["source"], "semantic_cache")
            self.assertEqual(res2["trace"]["cache_hit"], "semantic")
            self.assertGreaterEqual(res2["trace"]["similarity"], 0.65)


if __name__ == "__main__":
    unittest.main()
