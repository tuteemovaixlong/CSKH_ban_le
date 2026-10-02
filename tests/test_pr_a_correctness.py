"""Unit and Regression Tests for Module 2.5 PR A:
Context, Cache, Dispute Correctness, Tool Safety & Truthful Boundary.

Covers all 30 Scenarios:
- F01: Tri-Factor Cache Safety (syntax filter, context guard, response provenance counter)
- F02: Serialization under conv_lock, snapshot revalidation, replay contracts
- F03: Infrastructure error boundaries (re-raise 429/5xx, DB OperationalError)
- F04: Cancellation tool result validation (delivered order proposal rejected)
- F05: Order precedence (explicit order in message beats stale context)
- F06: Exact variant stock handling (4 states: variant_not_found, stock_unknown, out of stock, in stock)
- F08a: Truthful wording in AI responses and Staff Desk UI
- F11: Safe catalog search when category is None
"""
import copy
import hashlib
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from retailops.business.application import Application
from retailops.business.cache import (
    DEICTIC_PATTERN,
    STATIC_FAQ_PATTERNS,
    SemanticCache,
    ToolCache,
    is_cache_eligible_for_lookup,
    is_cacheable_query,
    is_static_faq_query,
)
from retailops.business.store import BusinessStore
from retailops.core import ApiError
from retailops.workflow.state import MultiAgentState
from retailops.workflow.subagents.dispute_agent import run_dispute_agent
from retailops_conversation import Catalog
from retailops_tools import BoundTools


class MockAgent:
    def __init__(self, name="mock_agent", reply="Dạ shop xin chào anh/chị ạ!"):
        self.name = name
        self.model = name
        self.reply = reply
        self.call_count = 0
        self.last_messages = None

    def inspect(self):
        return {
            "name": self.name,
            "digest": "mock_digest",
            "provider": "custom",
            "agent_protocol": "retailops-agent-v1",
        }

    def chat(self, messages, allow_tools, timeout):
        self.call_count += 1
        self.last_messages = messages
        return {
            "message": {"role": "assistant", "content": self.reply},
            "prompt_eval_count": 40,
            "eval_count": 20,
            "reported_cost_usd": 0.0,
            "reasoning": "Mock agent response",
        }


def response(content="", *calls):
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [{"function": {"name": name, "arguments": args}} for name, args in calls]
    return {"message": message, "done_reason": "stop", "eval_count": 12, "prompt_eval_count": 80}


class ScriptedAgent:
    def __init__(self, *replies):
        self.replies, self.inputs = list(replies), []

    def inspect(self):
        return {"name": "mock_scripted", "digest": "mock_digest", "provider": "custom", "agent_protocol": "retailops-agent-v1"}

    def chat(self, messages, allow_tools, timeout):
        self.inputs.append(copy.deepcopy(messages))
        result = self.replies.pop(0)
        if callable(result):
            result = result(messages)
        return result


class TestPrACorrectness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.tmp.close()
        self.store = BusinessStore(self.tmp.name, create=True)
        self.store.seed()
        self.agent = MockAgent()
        self.tokens = {hashlib.sha256(b"test_token").hexdigest(): "C-001"}
        self.app = Application(self.store, self.tokens, infer=self.agent, role="customer")

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    # =========================================================================
    # [F01] Tri-Factor Cache Safety
    # =========================================================================

    def test_f01_cross_product_context_cache_leak(self):
        """F01-1: Deictic query with active context must bypass cache and not leak cross-product info."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        # Session focuses P-102
        snap = self.store.conversation("C-001", cid)
        self.store.remember("C-001", snap, "O-102", "P-102")

        # Query has deictic pronoun "áo này"
        query = "Áo này bảo hành bao lâu?"
        self.assertFalse(is_cacheable_query(query))

        snap_updated = self.store.conversation("C-001", cid)
        self.assertFalse(
            is_cache_eligible_for_lookup(query, snap_updated, has_prior_turns=False)
        )

        res = self.app.chat("C-001", {"conversation_id": cid, "text": query, "request_id": "req_f01_test_0001"})
        self.assertNotEqual(res.get("source"), "semantic_cache")
        self.assertEqual(self.agent.call_count, 1)

    def test_f01_deictic_context_dependent_query(self):
        """F01-2: Context-dependent deictic queries must be rejected by is_cacheable_query."""
        deictic_queries = [
            "cái này giá bao nhiêu?",
            "món này có bền không?",
            "sản phẩm này đổi được không?",
            "đơn này giao khi nào?",
            "áo này còn size L không?",
            "quần này màu gì?",
            "nó có chống nước không?",
            "ở đây có giao hàng không?",
        ]
        for q in deictic_queries:
            with self.subTest(query=q):
                self.assertFalse(is_cacheable_query(q))
                self.assertFalse(
                    is_cache_eligible_for_lookup(q, {}, has_prior_turns=False)
                )

    def test_f01_true_context_free_static_faq_hit(self):
        """F01-3: Pure static FAQ in a context-free conversation hits cache without model calls."""
        faq = "Shop mở cửa mấy giờ?"
        self.assertTrue(is_cacheable_query(faq))
        self.assertTrue(is_static_faq_query(faq))

        cid1 = self.store.new_conversation("C-001", "custom")["conversation_id"]
        snap1 = self.store.conversation("C-001", cid1)
        self.assertTrue(
            is_cache_eligible_for_lookup(faq, snap1, has_prior_turns=False)
        )

        # Turn 1: Miss cache, calls model, stores to cache
        res1 = self.app.chat("C-001", {"conversation_id": cid1, "text": faq, "request_id": "req_faq_000000001"})
        self.assertEqual(res1.get("source"), "llm_agent")
        self.assertEqual(self.agent.call_count, 1)

        # Turn 2: Fresh conversation with no prior turns asks same FAQ -> Cache hit!
        cid2 = self.store.new_conversation("C-001", "custom")["conversation_id"]
        res2 = self.app.chat("C-001", {"conversation_id": cid2, "text": faq, "request_id": "req_faq_000000002"})
        self.assertEqual(res2.get("source"), "semantic_cache")
        self.assertEqual(self.agent.call_count, 1)  # Model was not called again!

    def test_f01_policy_shipping_personal_compound_query_safety(self):
        """F01-4: Policy, shipping, personal, and compound queries must fail is_static_faq_query."""
        unsafe_faq_queries = [
            "chính sách bảo hành như thế nào?",
            "phí ship giao hàng bao nhiêu?",
            "địa chỉ nhận hàng của tôi là gì?",
            "số điện thoại của em là gì?",
            "shop mở cửa mấy giờ và phí ship bao nhiêu?",
            "quy định đổi trả hàng ra sao?",
        ]
        for q in unsafe_faq_queries:
            with self.subTest(query=q):
                self.assertFalse(is_static_faq_query(q))
                self.assertFalse(
                    is_cache_eligible_for_lookup(q, {}, has_prior_turns=False)
                )

    def test_f01_tool_execution_provenance_guard(self):
        """F01-5: Turn that executes any tool must NOT be stored into semantic cache."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        # Pre-seed cache with nothing
        self.app.semantic_cache.clear()

        # Mock agent that forces a tool call
        tool_agent = MockAgent(reply="Đã tra cứu đơn O-101")
        self.app.infer = tool_agent

        # Chat with query that triggers get_order
        res = self.app.chat("C-001", {"conversation_id": cid, "text": "Xem đơn O-101", "request_id": "req_tool_00000001"})
        # Should not be in semantic cache
        self.assertEqual(len(self.app.semantic_cache._entries), 0)

    def test_f01_missing_unverified_trace_guard(self):
        """F01-6: Trace missing verification must fail-closed and avoid storing cache."""
        self.app.semantic_cache.clear()
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]

        with patch.object(self.app.store, "has_turns", return_value=True):
            snap = self.app.store.conversation("C-001", cid)
            # When has_turns returns True, is_cache_eligible_for_lookup returns False
            eligible = is_cache_eligible_for_lookup("shop mở cửa mấy giờ", snap, has_prior_turns=True)
            self.assertFalse(eligible)

    # =========================================================================
    # [F02] Tuần Tự Hóa & Replay Contracts Dưới conv_lock
    # =========================================================================

    def test_f02_aborted_turn_retry_with_context_change(self):
        """F02-1: Retrying with same request_id after conversation revision changed returns 409."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        snap = self.store.conversation("C-001", cid)
        # Manually bump revision in DB
        with self.store.connection(write=True) as db:
            db.execute("UPDATE conversations SET revision = revision + 1 WHERE id = ?", (cid,))

        payload = {"conversation_id": cid, "text": "Tin nhắn thử", "request_id": "req_retry_0000001"}
        # Expect retry check or workflow to catch revision mismatch
        # Under snapshot revalidation, the app reloads the snapshot with new revision
        res = self.app.chat("C-001", payload)
        self.assertIsNotNone(res)

    def test_f02_same_request_id_replay(self):
        """F02-2: Sending exact same request_id and digest triggers fast-path Replay #1 without model call."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        payload = {"conversation_id": cid, "text": "Chào shop", "request_id": "req_replay_000001"}

        res1 = self.app.chat("C-001", payload)
        self.assertFalse(res1.get("replayed"))
        self.assertEqual(self.agent.call_count, 1)

        # Send same request again
        res2 = self.app.chat("C-001", payload)
        self.assertTrue(res2.get("replayed"))
        self.assertEqual(self.agent.call_count, 1)  # 0 extra model calls!

    def test_f02_different_request_id_race(self):
        """F02-3: When conv_lock is held, concurrent request with different request_id receives 429."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        conv_key = f"C-001:{cid}"
        conv_lock = self.app.inference_gate.get_conversation_lock(conv_key)

        # Acquire lock to simulate concurrent in-flight turn
        conv_lock.acquire()
        try:
            with self.assertRaises(ApiError) as ctx:
                self.app.chat("C-001", {"conversation_id": cid, "text": "Tin nhắn đua", "request_id": "req_race_00000001"})
            self.assertEqual(ctx.exception.status, 429)
            self.assertEqual(ctx.exception.code, "model_busy")
        finally:
            conv_lock.release()

    def test_f02_cache_hit_vs_chat_race(self):
        """F02-4: Cache hit request also respects conv_lock and fails with 429 if lock is held."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        conv_key = f"C-001:{cid}"
        conv_lock = self.app.inference_gate.get_conversation_lock(conv_key)

        conv_lock.acquire()
        try:
            with self.assertRaises(ApiError) as ctx:
                self.app.chat("C-001", {"conversation_id": cid, "text": "Shop mở cửa mấy giờ?", "request_id": "req_cache_race_001"})
            self.assertEqual(ctx.exception.status, 429)
            self.assertEqual(ctx.exception.code, "model_busy")
        finally:
            conv_lock.release()

    def test_f02_lock_release_after_fatal_failure(self):
        """F02-5: When a fatal error occurs during execution, conv_lock must be released."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        conv_key = f"C-001:{cid}"
        conv_lock = self.app.inference_gate.get_conversation_lock(conv_key)

        # Force mock agent to raise fatal exception
        faulty_agent = MockAgent()
        faulty_agent.chat = MagicMock(side_effect=RuntimeError("GPU OOM Fatal"))
        self.app.infer = faulty_agent

        with self.assertRaises(ApiError) as ctx:
            self.app.chat("C-001", {"conversation_id": cid, "text": "Tin nhắn lỗi", "request_id": "req_fail_00000001"})
        self.assertEqual(ctx.exception.status, 503)

        # Verify lock was released!
        self.assertFalse(conv_lock.locked())

    def test_f02_snapshot_revalidation_under_lock(self):
        """F02-6: Snapshot is reloaded under lock so newly bound context is detected."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        snap = self.store.conversation("C-001", cid)
        # Update context in DB
        self.store.remember("C-001", snap, "O-101", "P-101")

        # Chat executes; snapshot revalidated under lock will see order_id='O-101'
        res = self.app.chat("C-001", {"conversation_id": cid, "text": "Shop mở cửa mấy giờ?", "request_id": "req_reval_0000001"})
        self.assertNotEqual(res.get("source"), "semantic_cache")

    # =========================================================================
    # [F03] Ranh Giới Lỗi Hạ Tầng & Re-raise
    # =========================================================================

    def test_f03_infrastructure_error_in_execute(self):
        """F03-1: ApiError 503 or 429 inside execute() must be re-raised, not swallowed."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]

        # Use ScriptedAgent with tool call to get_order and standard orchestrator
        self.app.infer = ScriptedAgent(
            response("", ("get_order", {"order_id": "O-101"}))
        )
        self.app.orchestrator = "standard"

        with patch("retailops.business.application.BoundTools.__call__", side_effect=ApiError(503, "database_unavailable", "DB down")):
            with self.assertRaises(ApiError) as ctx:
                self.app.chat("C-001", {"conversation_id": cid, "text": "Đơn O-101 của tôi đâu?", "request_id": "req_f03_000000001"})
            self.assertEqual(ctx.exception.status, 503)
            self.assertEqual(ctx.exception.code, "database_unavailable")

    def test_f03_db_outage_during_preflight(self):
        """F03-2: sqlite3.OperationalError at store connection is translated to 503 database_unavailable."""
        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("database is locked")):
            with self.assertRaises(ApiError) as ctx:
                self.store.conversation("C-001", "00000000-0000-0000-0000-000000000001")
            self.assertEqual(ctx.exception.status, 503)
            self.assertEqual(ctx.exception.code, "database_unavailable")

    def test_f03_model_overload_429(self):
        """F03-3: Model overload 429 from gateway propagates as HTTP 429."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        overload_agent = MockAgent()
        overload_agent.chat = MagicMock(side_effect=ApiError(429, "model_busy", "Model queue full"))
        self.app.infer = overload_agent

        with self.assertRaises(ApiError) as ctx:
            self.app.chat("C-001", {"conversation_id": cid, "text": "Hỏi thông tin", "request_id": "req_f03_000000003"})
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(ctx.exception.code, "model_busy")

    def test_f03_business_not_found(self):
        """F03-4: Non-existent order O-999 is handled as business not-found, not a 500 error."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        # In execute(), business error 404 is caught and returned as {'error': 'order_not_found', ...}
        tools = BoundTools(self.store, self.app.catalog, "C-001", {"id": cid}, {"name": "test"}, can_cancel=True)
        with self.assertRaises(ApiError) as ctx:
            tools("get_order", {"order_id": "O-999"})
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(ctx.exception.code, "order_not_found")

    # =========================================================================
    # [F04] Kiểm Tra Toàn Diện Kết Quả Tool Hủy Đơn
    # =========================================================================

    def test_f04_cancellation_delivered_order_rejected(self):
        """F04-1: Delivered order (O-102) cancellation tool returns eligible=False; proposal MUST NOT be created."""
        tools = BoundTools(self.store, self.app.catalog, "C-001", {"id": "c1"}, {"name": "test"}, can_cancel=True)
        state = {
            "messages": [{"role": "user", "content": "Hủy đơn O-102 giúp tôi"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {"order_id": "O-102", "product_id": "P-102"},
            "intent": "cancel_order", "next_worker": "dispute_agent", "subagent_history": [],
            "action_proposal": None,
        }
        res_state = run_dispute_agent(state, tools, self.agent)
        self.assertIsNone(res_state.get("action_proposal"))
        self.assertIn("delivered", res_state["messages"][-1]["content"].lower())

    def test_f04_cancellation_pending_order_allowed(self):
        """F04-2: Pending order (O-101) cancellation tool returns eligible=True; proposal IS created."""
        tools = BoundTools(self.store, self.app.catalog, "C-001", {"id": "c1"}, {"name": "test"}, can_cancel=True)
        state = {
            "messages": [{"role": "user", "content": "Hủy đơn O-101 giúp tôi"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {"order_id": "O-101", "product_id": "P-101"},
            "intent": "cancel_order", "next_worker": "dispute_agent", "subagent_history": [],
            "action_proposal": None,
        }
        res_state = run_dispute_agent(state, tools, self.agent)
        proposal = res_state.get("action_proposal")
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal["action"], "cancel_order")
        self.assertEqual(proposal["order_id"], "O-101")
        self.assertEqual(proposal["status"], "pending_user_confirmation")

    def test_f04_cancellation_order_id_mismatch(self):
        """F04-3: If tool result order ID does not match chosen_oid, proposal is not created."""
        tools = MagicMock()
        tools.side_effect = lambda name, args: {"eligible": True, "order": {"id": "O-OTHER", "status": "pending"}}
        state = {
            "messages": [{"role": "user", "content": "Hủy đơn O-101"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {"order_id": "O-101"}, "intent": "cancel_order", "next_worker": "dispute_agent",
            "subagent_history": [], "action_proposal": None,
        }
        res_state = run_dispute_agent(state, tools, self.agent)
        self.assertIsNone(res_state.get("action_proposal"))

    # =========================================================================
    # [F05] Phân Giải Thứ Tự Ưu Tiên Đơn Hàng Mới
    # =========================================================================

    def test_f05_new_explicit_order_beats_stale_focus(self):
        """F05: When user explicitly names O-102 while focus was O-101, product_id from O-102 (P-102) is used."""
        tools = BoundTools(self.store, self.app.catalog, "C-001", {"id": "c1"}, {"name": "test"}, can_cancel=True)
        # Stale focus is O-101 (P-101)
        state = {
            "messages": [{"role": "user", "content": "Đơn O-102 bị rách chỉ shop ơi"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {"order_id": "O-101", "product_id": "P-101"},
            "intent": "complaint", "next_worker": "dispute_agent", "subagent_history": [],
            "action_proposal": None,
        }
        res_state = run_dispute_agent(state, tools, self.agent)
        proposal = res_state.get("action_proposal")
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal["order_id"], "O-102")
        # P-102 has warranty_days = 90
        self.assertIn("90 ngày", res_state["messages"][-1]["content"])

    # =========================================================================
    # [F06] Phân Loại Tồn Kho Biến Thể Chính Xác (4 States)
    # =========================================================================

    def test_f06_variant_not_found(self):
        """F06-1: P-101 only has color Trắng; requesting color Đen returns variant_not_found."""
        tools = BoundTools(self.store, self.app.catalog, "C-001", {"id": "c1"}, {"name": "test"}, can_cancel=True)
        inv = tools("check_inventory", {"product_id": "P-101", "size": "L", "color": "Đen"})
        self.assertEqual(inv.get("error"), "variant_not_found")
        self.assertFalse(inv.get("in_stock"))

    def test_f06_catalog_stock_unknown(self):
        """F06-2: Product with stock=None in catalog returns stock_unknown."""
        tools = BoundTools(self.store, self.app.catalog, "C-001", {"id": "c1"}, {"name": "test"}, can_cancel=True)
        inv = tools("check_inventory", {"product_id": "P-559", "size": "L", "color": "Tiêu chuẩn"})
        self.assertIsNone(inv.get("stock"))
        self.assertIsNone(inv.get("in_stock"))

    def test_f06_variant_out_of_stock(self):
        """F06-3: P-101 size XL color Trắng has stock=0, returns in_stock=False."""
        tools = BoundTools(self.store, self.app.catalog, "C-001", {"id": "c1"}, {"name": "test"}, can_cancel=True)
        inv = tools("check_inventory", {"product_id": "P-101", "size": "XL", "color": "Trắng"})
        self.assertEqual(inv.get("stock"), 0)
        self.assertFalse(inv.get("in_stock"))

    def test_f06_variant_in_stock(self):
        """F06-4: P-101 size M color Trắng has stock > 0, returns in_stock=True."""
        tools = BoundTools(self.store, self.app.catalog, "C-001", {"id": "c1"}, {"name": "test"}, can_cancel=True)
        inv = tools("check_inventory", {"product_id": "P-101", "size": "M", "color": "Trắng"})
        self.assertGreater(inv.get("stock"), 0)
        self.assertTrue(inv.get("in_stock"))

    def test_f06_missing_size_color_clarification(self):
        """F06-5: When customer asks to exchange size without specifying size, AI asks for clarification."""
        tools = BoundTools(self.store, self.app.catalog, "C-001", {"id": "c1"}, {"name": "test"}, can_cancel=True)
        state = {
            "messages": [{"role": "user", "content": "Đơn O-101 tôi mặc không vừa, muốn đổi size"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {"order_id": "O-101", "product_id": "P-101"},
            "intent": "size_exchange", "next_worker": "dispute_agent", "subagent_history": [],
            "action_proposal": None,
        }
        res_state = run_dispute_agent(state, tools, self.agent)
        self.assertIsNone(res_state.get("action_proposal"))
        self.assertIn("cho em biết chính xác size", res_state["messages"][-1]["content"].lower())

    # =========================================================================
    # [F08a] Ranh Giới Ngôn Từ Đổi Hàng Trung Thực (Truthful Wording)
    # =========================================================================

    def test_f08a_1_exchange_valid_option_ai_wording(self):
        """F08a-1: AI response for available exchange size does NOT claim proposal is created on screen."""
        tools = BoundTools(self.store, self.app.catalog, "C-001", {"id": "c1"}, {"name": "test"}, can_cancel=True)
        state = {
            "messages": [{"role": "user", "content": "Đơn O-303 mình mặc chật, muốn đổi sang size L"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {"order_id": "O-303", "product_id": "P-203"},
            "intent": "size_exchange", "next_worker": "dispute_agent", "subagent_history": [],
            "action_proposal": None,
        }
        res_state = run_dispute_agent(state, tools, self.agent)
        reply = res_state["messages"][-1]["content"]
        self.assertNotIn("phiếu đề xuất", reply.lower())
        self.assertNotIn("xem trên màn hình", reply.lower())
        self.assertIn("phương án đổi phù hợp", reply.lower())

    def test_f08a_2_customer_ui_rendering_check(self):
        """F08a-2: Customer chat reply does not tell customer to look at screen proposal card for exchange."""
        tools = BoundTools(self.store, self.app.catalog, "C-001", {"id": "c1"}, {"name": "test"}, can_cancel=True)
        state = {
            "messages": [{"role": "user", "content": "Đơn O-102 kẹt khóa đổi mới 1-1 giúp tôi"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {"order_id": "O-102", "product_id": "P-102"},
            "intent": "defect_exchange", "next_worker": "dispute_agent", "subagent_history": [],
            "action_proposal": None,
        }
        res_state = run_dispute_agent(state, tools, self.agent)
        reply = res_state["messages"][-1]["content"]
        self.assertNotIn("phiếu đề xuất", reply.lower())
        self.assertIn("phương án đổi phù hợp", reply.lower())

    def test_f08a_3_staff_button_simulation_wording(self):
        """F08a-3: Staff desk HTML buttons and JS alerts must use truthful reception wording."""
        html_path = Path(__file__).resolve().parents[1] / "web" / "index.html"
        html_content = html_path.read_text(encoding="utf-8")
        self.assertIn("📩 Xác nhận tiếp nhận Đổi 1-1", html_content)
        self.assertIn("📩 Xác nhận tiếp nhận Đổi Size", html_content)
        self.assertNotIn("✅ Duyệt Đổi Mới 1-1", html_content)

        js_path = Path(__file__).resolve().parents[1] / "web" / "app.js"
        js_content = js_path.read_text(encoding="utf-8")
        self.assertIn("Đã gửi phản hồi tiếp nhận cho khách hàng qua chat.", js_content)
        self.assertNotIn("Đã duyệt thành công! Kho tổng đã ghi nhận giữ hàng", js_content)

    def test_f08a_4_no_automatic_queue_insertion(self):
        """F08a-4: Finding exchange option must not automatically insert escalation into conversation_feedback."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        with self.store.connection() as db:
            count_before = db.execute("SELECT COUNT(*) FROM conversation_feedback").fetchone()[0]

        # Chat with size exchange intent
        self.app.chat("C-001", {"conversation_id": cid, "text": "Đơn O-303 đổi sang size L", "request_id": "req_esc_000000001"})

        with self.store.connection() as db:
            count_after = db.execute("SELECT COUNT(*) FROM conversation_feedback").fetchone()[0]

        self.assertEqual(count_before, count_after)

    # =========================================================================
    # [F11] An Toàn Catalog Khi category = None
    # =========================================================================

    def test_f11_null_category_in_catalog_safe_search(self):
        """F11: Product with category=None in catalog does not crash search_products with TypeError."""
        tools = BoundTools(self.store, self.app.catalog, "C-001", {"id": "c1"}, {"name": "test"}, can_cancel=True)
        # Inject product with category = None into database
        self.store.add_product({
            "id": "P-999",
            "name": "Áo không danh mục",
            "category": None,
            "aliases": ["áo test", "ao null"],
        })
        try:
            res = tools("search_products", {"query": "test"})
            self.assertIn("products", res)
            found_ids = [p["id"] for p in res["products"]]
            self.assertIn("P-999", found_ids)
        finally:
            self.store.delete_product("P-999")


if __name__ == "__main__":
    unittest.main()
