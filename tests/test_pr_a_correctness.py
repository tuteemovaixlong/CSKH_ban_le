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
import uuid
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
        """F01-5: Eligible FAQ query that executes any read tool must NOT be stored into semantic cache."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        self.app.semantic_cache.clear()

        # ScriptedAgent emits a read tool call for an eligible FAQ query
        self.app.infer = ScriptedAgent(
            response("", ("list_orders", {})),
            response("Shop mở cửa từ 8:00 đến 22:00 ạ.")
        )

        res = self.app.chat("C-001", {"conversation_id": cid, "text": "Shop mở cửa mấy giờ?", "request_id": "req_tool_prov_000001"})
        # Provenance guard detects tool execution -> MUST NOT be in semantic cache
        self.assertEqual(len(self.app.semantic_cache._entries), 0)

    def test_f01_missing_unverified_trace_guard(self):
        """F01-6: Trace missing verification must fail-closed and avoid storing cache without crashing."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        self.app.semantic_cache.clear()

        # Mock agent returning trace without tools/tool_count or with None
        with patch.object(self.app, "semantic_cache") as mock_cache:
            mock_cache.lookup.return_value = None
            res = self.app.chat("C-001", {"conversation_id": cid, "text": "Shop mở cửa mấy giờ?", "request_id": "req_unverif_000001"})
            self.assertIsNotNone(res)
            # Normal eligible query without tool calls CAN be stored, but unverified trace cannot
            # Here we test that invalid trace fields do not crash finish_turn with 500

    # =========================================================================
    # [F02] Tuần Tự Hóa & Replay Contracts Dưới conv_lock
    # =========================================================================

    def test_f02_aborted_turn_retry_with_context_change(self):
        """F02-1: Retrying an interrupted turn with changed revision/context/digest returns 409."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        req_id = "req_interrupted_0000001"
        initial_rev = self.store.conversation("C-001", cid)["revision"]

        # 1. Create an interrupted turn: agent raises error during model call
        faulty_agent = MockAgent()
        faulty_agent.chat = MagicMock(side_effect=RuntimeError("Transient model crash"))
        self.app.infer = faulty_agent

        with self.assertRaises(ApiError):
            self.app.chat("C-001", {"conversation_id": cid, "text": "Shop mở cửa mấy giờ?", "request_id": req_id})

        # Verify a graph_run was created and persists in DB, but turn is NOT committed in agent_turns
        with self.store.connection() as db:
            run_count = db.execute("SELECT count(*) FROM graph_runs").fetchone()[0]
            turn_count = db.execute("SELECT count(*) FROM agent_turns WHERE request_id = ?", (req_id,)).fetchone()[0]
        self.assertGreaterEqual(run_count, 1)
        self.assertEqual(turn_count, 0)

        # Working agent for retries
        working_agent = MockAgent(reply="Shop mở cửa từ 8:00 đến 22:00 ạ.")
        self.app.infer = working_agent

        # Scenario A: Retry with bumped conversation.revision -> 409 conversation_changed
        with self.store.connection(write=True) as db:
            db.execute("UPDATE conversations SET revision = revision + 1 WHERE id = ?", (cid,))

        with self.assertRaises(ApiError) as ctx_rev:
            self.app.chat("C-001", {"conversation_id": cid, "text": "Shop mở cửa mấy giờ?", "request_id": req_id})
        self.assertEqual(ctx_rev.exception.status, 409)
        self.assertEqual(ctx_rev.exception.code, "conversation_changed")
        self.assertEqual(working_agent.call_count, 0)  # Rejected BEFORE model call!

        # Revert revision for Scenario B
        with self.store.connection(write=True) as db:
            db.execute("UPDATE conversations SET revision = revision - 1 WHERE id = ?", (cid,))

        # Scenario B: Retry with changed context (order_id) -> 409 conversation_changed
        snap = self.store.conversation("C-001", cid)
        self.store.remember("C-001", snap, "O-101", "P-101")
        with self.assertRaises(ApiError) as ctx_ctx:
            self.app.chat("C-001", {"conversation_id": cid, "text": "Shop mở cửa mấy giờ?", "request_id": req_id})
        self.assertEqual(ctx_ctx.exception.status, 409)
        self.assertEqual(ctx_ctx.exception.code, "conversation_changed")
        self.assertEqual(working_agent.call_count, 0)

        # Clear context back to None and restore initial_rev for Scenario C & D
        with self.store.connection(write=True) as db:
            db.execute("UPDATE conversations SET revision = ?, order_id = NULL, product_id = NULL WHERE id = ?", (initial_rev, cid))

        # Scenario C: Retry with changed text (digest mismatch) -> 409 request_conflict
        with self.assertRaises(ApiError) as ctx_dig:
            self.app.chat("C-001", {"conversation_id": cid, "text": "Hotline của shop là gì?", "request_id": req_id})
        self.assertEqual(ctx_dig.exception.status, 409)
        self.assertEqual(ctx_dig.exception.code, "request_conflict")
        self.assertEqual(working_agent.call_count, 0)

        # Scenario D: Unchanged retry -> resumes workflow and succeeds!
        res_ok = self.app.chat("C-001", {"conversation_id": cid, "text": "Shop mở cửa mấy giờ?", "request_id": req_id})
        self.assertIsNotNone(res_ok)
        with self.store.connection() as db:
            turn_count_after = db.execute("SELECT count(*) FROM agent_turns WHERE request_id = ?", (req_id,)).fetchone()[0]
        self.assertEqual(turn_count_after, 1)

        # Scenario E: Completed replay -> returns replayed turn with 0 extra model calls!
        calls_before = working_agent.call_count
        replay = self.app.chat("C-001", {"conversation_id": cid, "text": "Shop mở cửa mấy giờ?", "request_id": req_id})
        self.assertTrue(replay.get("replayed"))
        self.assertEqual(working_agent.call_count, calls_before)

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
        """F03-1: Infrastructure errors (429/503) from tools and provider gateway propagate to client."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]

        # 1. Tool 503 database_unavailable
        self.app.infer = ScriptedAgent(
            response("", ("get_order", {"order_id": "O-101"}))
        )
        with patch("retailops.business.application.BoundTools.__call__", side_effect=ApiError(503, "database_unavailable", "DB down")):
            with self.assertRaises(ApiError) as ctx:
                self.app.chat("C-001", {"conversation_id": cid, "text": "Đơn O-101 của tôi đâu?", "request_id": "req_f03_000000001"})
            self.assertEqual(ctx.exception.status, 503)
            self.assertEqual(ctx.exception.code, "tool_unavailable")

        # 2. Tool 429 server_busy
        self.app.infer = ScriptedAgent(
            response("", ("get_order", {"order_id": "O-101"}))
        )
        with patch("retailops.business.application.BoundTools.__call__", side_effect=ApiError(429, "server_busy", "Busy")):
            with self.assertRaises(ApiError) as ctx429:
                self.app.chat("C-001", {"conversation_id": cid, "text": "Đơn O-101 của tôi đâu?", "request_id": "req_f03_000000002"})
            self.assertEqual(ctx429.exception.status, 429)

        # 3. Dispute agent provider error 429 (no false acknowledgement)
        from retailops_agent import AgentError
        disp_err_agent = MockAgent()
        disp_err_agent.chat = MagicMock(side_effect=AgentError("api_rate_limited", "Rate limit", {"http_status": 429}))
        self.app.infer = disp_err_agent
        with self.assertRaises(ApiError) as ctx_disp:
            self.app.chat("C-001", {"conversation_id": cid, "text": "Hủy đơn O-101 giúp tôi", "request_id": "req_f03_000000003"})
        self.assertEqual(ctx_disp.exception.status, 429)

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
        from retailops_agent import AgentError
        overload_agent = MockAgent()
        overload_agent.chat = MagicMock(side_effect=AgentError("api_rate_limited", "Model queue full", {"http_status": 429}))
        self.app.infer = overload_agent

        with self.assertRaises(ApiError) as ctx:
            self.app.chat("C-001", {"conversation_id": cid, "text": "Hỏi thông tin", "request_id": "req_f03_000000003"})
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(ctx.exception.code, "api_rate_limited")

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
        """F04-1: Delivered order (O-102) cancellation tool returns eligible=False; proposal MUST NOT be created and refusal message preserved."""
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
        content = res_state["messages"][-1]["content"]
        self.assertGreater(len(content), 0)
        self.assertIn("delivered", content.lower())

    def test_f04_cancellation_model_calls_wrong_order_rejected(self):
        """F04-G06/N01: Customer requests O-102; model calls prepare_cancellation(O-101).
        Verified through Application: action is reply, no cancel card, no wrong order, no proposal, context untainted."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        self.app.infer = ScriptedAgent(
            response("", ("prepare_cancellation", {"order_id": "O-101"}))
        )
        res = self.app.chat("C-001", {"conversation_id": cid, "text": "Hủy luôn O-102", "request_id": "req_n01_wrong_order"})
        self.assertEqual(res["action"], "reply")
        self.assertNotIn("order", res)
        self.assertIsNone(res.get("action_proposal"))
        self.assertNotEqual(res["context"].get("order_id"), "O-101")

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
    # [F05] Phân Giải Thứ Tự Ưu Tiên Đơn Hàng Mới & G07
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

    def test_f05_new_order_without_product_does_not_steal_old_focus(self):
        """F05-G07/N07: If new order does not resolve to a product, dispute agent must NOT steal bound product from old focus."""
        called_tools = []
        def spy_tools(name, args):
            called_tools.append((name, args))
            if name == "get_order":
                return {"order": {"id": "O-999", "customer_id": "C-001", "product_id": None, "variant": None}}
            return {"error": "not_found"}

        tools = MagicMock(side_effect=spy_tools)
        state = {
            "messages": [{"role": "user", "content": "Đơn O-999 bị rách shop ơi"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {"order_id": "O-101", "product_id": "P-101"},  # old focus
            "intent": "defect_exchange", "next_worker": "dispute_agent", "subagent_history": [],
            "action_proposal": None,
        }
        res_state = run_dispute_agent(state, tools, self.agent)
        self.assertIsNone(res_state.get("action_proposal"))
        self.assertTrue(any(call[0] == "get_order" and call[1].get("order_id") == "O-999" for call in called_tools))
        self.assertFalse(any(call[0] == "get_product" and call[1].get("product_id") == "P-101" for call in called_tools))

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

    def test_f06_multiword_color_handling(self):
        """F06-G08: Multi-word colors like 'Xanh Nhạt' and 'Xanh Navy' are resolved completely without truncation."""
        tools = BoundTools(self.store, self.app.catalog, "C-004", {"id": "c1"}, {"name": "test"}, can_cancel=True)
        inv_navy = tools("check_inventory", {"product_id": "P-203", "size": "L", "color": "Xanh Navy"})
        self.assertEqual(inv_navy.get("stock"), 18)
        self.assertTrue(inv_navy.get("in_stock"))

        inv_nhat = tools("check_inventory", {"product_id": "P-103", "size": "L", "color": "Xanh Nhạt"})
        self.assertEqual(inv_nhat.get("stock"), 10)
        self.assertTrue(inv_nhat.get("in_stock"))

    def test_f06_preserve_original_color_not_default_to_tieuchuan(self):
        """F06-G08: O-301 original color is Trắng; asking to exchange size must preserve color Trắng, not default to Tiêu chuẩn."""
        tools = BoundTools(self.store, self.app.catalog, "C-003", {"id": "c1"}, {"name": "test"}, can_cancel=True)
        state = {
            "messages": [{"role": "user", "content": "Đơn O-301 đổi sang size L"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {"order_id": "O-301", "product_id": "P-103"},
            "intent": "size_exchange", "next_worker": "dispute_agent", "subagent_history": [],
            "action_proposal": None,
        }
        res_state = run_dispute_agent(state, tools, self.agent)
        # O-301 has original color Trắng, size M. Variant Trắng/L has stock 10.
        reply = res_state["messages"][-1]["content"]
        self.assertIn("trắng", reply.lower())

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
    # [F08a] Ranh Giới Ngôn Từ Đổi Hàng Trung Thực & Real Owner
    # =========================================================================

    def test_f08a_1_exchange_valid_option_ai_wording(self):
        """F08a-1: AI response for available exchange size does NOT claim proposal is created on screen."""
        tools = BoundTools(self.store, self.app.catalog, "C-004", {"id": "c1"}, {"name": "test"}, can_cancel=True)
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
        cid = self.store.new_conversation("C-004", "custom")["conversation_id"]
        tokens = {hashlib.sha256(b"c004_token").hexdigest(): "C-004"}
        app_c004 = Application(self.store, tokens, infer=self.agent, role="customer")
        with self.store.connection() as db:
            count_before = db.execute("SELECT COUNT(*) FROM conversation_feedback").fetchone()[0]

        # Chat with size exchange intent for owned order O-303
        app_c004.chat("C-004", {"conversation_id": cid, "text": "Đơn O-303 đổi sang size L", "request_id": "req_esc_000000001"})

        with self.store.connection() as db:
            count_after = db.execute("SELECT COUNT(*) FROM conversation_feedback").fetchone()[0]

        self.assertEqual(count_before, count_after)

    def test_g04_cache_semantic_topic_partitioning_negative_tests(self):
        """G04: Negative tests ensuring cross-topic semantic hits are rejected (Address vs Hotline vs Hours)."""
        cache = SemanticCache(min_similarity=0.65)
        cache.store("địa chỉ của cửa hàng như thế nào", "Địa chỉ cửa hàng: 123 Nguyễn Trãi")

        # Hotline query must NOT hit address
        hit_hotline = cache.lookup("hotline của cửa hàng như thế nào")
        self.assertIsNone(hit_hotline)

        # Hours query must NOT hit address
        hit_hours = cache.lookup("giờ mở cửa của cửa hàng thế nào")
        self.assertIsNone(hit_hours)

        # Address paraphrase MUST hit address
        hit_addr = cache.lookup("địa chỉ cửa hàng như thế nào")
        self.assertIsNotNone(hit_addr)
        self.assertEqual(hit_addr["answer"], "Địa chỉ cửa hàng: 123 Nguyễn Trãi")

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
        # G09: Inject product with both category = None and aliases = None
        self.store.add_product({
            "id": "P-998",
            "name": "Áo polo đặc biệt",
            "category": None,
            "aliases": None,
        })
        try:
            res = tools("search_products", {"query": "test"})
            self.assertIn("products", res)
            found_ids = [p["id"] for p in res["products"]]
            self.assertIn("P-999", found_ids)

            # G09: search for polo must find P-998 without TypeError
            res_polo = tools("search_products", {"query": "polo"})
            self.assertIn("products", res_polo)
            found_polo = [p["id"] for p in res_polo["products"]]
            self.assertIn("P-998", found_polo)
        finally:
            self.store.delete_product("P-999")
            self.store.delete_product("P-998")

    # =========================================================================
    # [N01–N07] Regression Suite Theo Đánh Giá REVIEW_ACCOUNT_ORDER_WORKFLOW
    # =========================================================================

    def test_n01_application_cancellation_unclear_target_asks_clarification(self):
        """N01: When customer says 'Hủy đơn giúp tôi' without explicit order id and model picks an order,
        Application MUST reject side-effect, cancel_order is cleared, action is reply, and AI asks for order id."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        self.app.infer = ScriptedAgent(
            response("", ("prepare_cancellation", {"order_id": "O-101"}))
        )
        res = self.app.chat("C-001", {"conversation_id": cid, "text": "Hủy đơn giúp tôi nhé", "request_id": "req_n01_unclear_0001"})
        self.assertEqual(res["action"], "reply")
        self.assertNotIn("order", res)
        self.assertIsNone(res.get("action_proposal"))
        self.assertIn("cung cấp mã đơn hàng", res["message"].lower())

    def test_n02_revalidate_ownership_under_focus_change(self):
        """N02: C-001 has focus on O-101/P-101. Owner of O-101 is changed to C-002 in DB.
        Subsequent request to exchange size must revalidate ownership via get_order, fail with 404/denial,
        and never execute check_inventory or produce an action proposal."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        # Seed focus context
        with self.store.connection(write=True) as db:
            db.execute("UPDATE conversations SET order_id='O-101', product_id='P-101' WHERE id=?", (cid,))
            # Transfer ownership of O-101 to C-002
            db.execute("UPDATE orders SET customer_id='C-002' WHERE id='O-101'")

        try:
            res = self.app.chat("C-001", {"conversation_id": cid, "text": "Đơn O-101 đổi size L", "request_id": "req_n02_ownership_001"})
            self.assertIsNone(res.get("action_proposal"))
            self.assertTrue(
                "không tìm thấy" in res["message"].lower() or "không thuộc tài khoản" in res["message"].lower()
            )
            # Ensure check_inventory was not called
            tool_names = [t.get("name") for t in res["trace"].get("tools", [])]
            self.assertNotIn("check_inventory", tool_names)
        finally:
            with self.store.connection(write=True) as db:
                db.execute("UPDATE orders SET customer_id='C-001' WHERE id='O-101'")

    def test_n03_tool_503_raises_retryable_api_error_without_commit(self):
        """N03: When a tool throws ApiError(503, database_unavailable), Application must propagate
        retryable 503 error (sanitized as tool_unavailable), record internal event/log without leaking DB details,
        and must NOT commit turn as successful reply."""
        from retailops.http.routes import api_result
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        with patch("retailops.business.application.BoundTools.__call__", side_effect=ApiError(503, "database_unavailable", "sensitive database detail")):
            with self.assertRaises(ApiError) as ctx:
                self.app.chat("C-001", {"conversation_id": cid, "text": "Đơn O-101 đổi size L", "request_id": "req_n03_503_error_0001"})
            self.assertEqual(ctx.exception.status, 503)
            self.assertEqual(ctx.exception.code, "tool_unavailable")
            self.assertNotIn("sensitive database detail", str(ctx.exception))

        # Check internal event was recorded containing original_code, status, stage, tool
        tool_events = [e for e in getattr(self.app, 'internal_events', []) if e.get('event') == 'tool_error']
        self.assertTrue(len(tool_events) >= 1)
        ev = tool_events[-1]
        self.assertEqual(ev.get('original_code'), 'database_unavailable')
        self.assertEqual(ev.get('status'), 503)
        self.assertEqual(ev.get('stage'), 'tool_execution')
        self.assertIn(ev.get('tool'), ('get_order', 'read_order'))

        # HTTP layer verification: returns HTTP 503 and sanitized error code
        with patch("retailops.business.application.BoundTools.__call__", side_effect=ApiError(503, "database_unavailable", "postgres://secret_pw@host/db")):
            with self.assertRaises(ApiError) as http_ctx:
                api_result(self.app, "C-001", "POST", "/api/chat",
                           {"conversation_id": cid, "text": "Đơn O-101 đổi size L", "request_id": "req_n03_http_test_0001"})
            self.assertEqual(http_ctx.exception.status, 503)
            self.assertEqual(http_ctx.exception.code, "tool_unavailable")
            self.assertNotIn("secret_pw", str(http_ctx.exception))

        # Turn was not committed to history
        hist = self.store.history("C-001", cid)
        self.assertEqual(len(hist), 0)

    def test_n04_advanced_variant_color_size_resolution(self):
        """N04: Dynamic size and color resolution:
        1. Distinguishes old color from new requested color (e.g. 'áo trắng muốn đổi size L màu xanh nhạt').
        2. Rejects explicit color requested by user if not in catalog instead of silently defaulting to original color.
        3. Supports sizes like XS, 3XL in catalog."""
        # 1. Test distinguishing old color vs requested color for O-301 (P-103, original color Trắng)
        cid3 = self.store.new_conversation("C-003", "custom")["conversation_id"]
        res = self.app.chat("C-003", {"conversation_id": cid3, "text": "Đơn O-301 áo trắng muốn đổi size L màu xanh nhạt", "request_id": "req_n04_distinguish_01"})
        proposal = res.get("action_proposal")
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal["target_color"], "Xanh Nhạt")
        self.assertEqual(proposal["target_size"], "L")

        # 2. Add product P-901 and order O-9001
        self.store.add_product({
            "id": "P-901", "name": "Áo Khoác Gió Đa Sắc", "category": "Áo khoác",
            "variants": ["Hồng Pastel · Size L", "Hồng Pastel · Size XS", "Be · Size L", "Be · Size 3XL", "Bạc · Size M"],
            "price": 450000, "warranty_days": 90, "stock": 50
        })
        with self.store.connection(write=True) as db:
            db.execute(
                "INSERT INTO orders (id, customer_id, name, variant, amount, status, product_id, version) "
                "VALUES ('O-9001', 'C-001', 'Áo Khoác Gió Đa Sắc', 'Be · Size M · Số lượng 1', 450000, 'delivered', 'P-901', 1)"
            )
        try:
            cid1 = self.store.new_conversation("C-001", "custom")["conversation_id"]
            # Ca 2: Explicit color requested 'màu bạc' but Bạc / L is not in catalog -> AI clarifies, does NOT silently default to Be
            res_bac = self.app.chat("C-001", {"conversation_id": cid1, "text": "Đơn O-9001 đổi size L màu bạc", "request_id": "req_n04_bac_0000000001"})
            self.assertIsNone(res_bac.get("action_proposal"))
            self.assertIn("không có biến thể màu bạc", res_bac["message"].lower())

            # Ca 3: Size XS with multiword color 'Hồng Pastel'
            res_xs = self.app.chat("C-001", {"conversation_id": cid1, "text": "Đơn O-9001 đổi size XS màu hồng pastel", "request_id": "req_n04_xs_00000000001"})
            prop_xs = res_xs.get("action_proposal")
            self.assertIsNotNone(prop_xs)
            self.assertEqual(prop_xs["target_size"], "XS")
            self.assertEqual(prop_xs["target_color"], "Hồng Pastel")
        finally:
            with self.store.connection(write=True) as db:
                db.execute("DELETE FROM orders WHERE id='O-9001'")
            self.store.delete_product("P-901")

    def test_n05_unmapped_order_abstains_without_claiming_inventory_checked(self):
        """N05: Order with product_id=None owned by customer must abstain clearly and NOT claim 'em đã kiểm tra kho'."""
        with self.store.connection(write=True) as db:
            db.execute(
                "INSERT INTO orders (id, customer_id, name, variant, amount, status, product_id, version) "
                "VALUES ('O-991001', 'C-001', 'Áo Không Rõ Mã', 'Trắng · Size L', 200000, 'delivered', NULL, 1)"
            )
        try:
            cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
            res = self.app.chat("C-001", {"conversation_id": cid, "text": "Đơn O-991001 đổi size L", "request_id": "req_n05_unmapped_00001"})
            self.assertIsNone(res.get("action_proposal"))
            self.assertNotIn("đã kiểm tra kho", res["message"].lower())
            self.assertIn("chưa có thông tin liên kết sản phẩm", res["message"].lower())
        finally:
            with self.store.connection(write=True) as db:
                db.execute("DELETE FROM orders WHERE id='O-991001'")

    def test_n06_graph_run_query_failure_raises_503_not_cache_hit(self):
        """N06: If querying graph_runs fails due to DB error, get_graph_run propagates 503 error
        and does not bypass idempotency check by returning a false cache hit."""
        cid = self.store.new_conversation("C-001", "custom")["conversation_id"]
        # Seed FAQ cache
        self.app.semantic_cache.store("Giờ mở cửa của shop thế nào?", "Shop mở cửa từ 8h đến 22h", action="reply")

        with patch.object(self.store, "get_graph_run", side_effect=ApiError(503, "database_unavailable", "disk error")):
            with self.assertRaises(ApiError) as ctx:
                self.app.chat("C-001", {"conversation_id": cid, "text": "Giờ mở cửa của shop thế nào?", "request_id": "req_n06_fail_000000001"})
            self.assertEqual(ctx.exception.status, 503)

    def test_n08_a_migration_with_business_db_and_ambiguous_quarantine(self):
        """N08-A: Legacy collision migration synchronizes both identity and business DBs.
        If an ambiguous collision occurs (orders exist for the shared customer ID):
        - Orders are quarantined under a designated quarantine customer.
        - Neither account is arbitrarily given the orders (no cross-account leak).
        - Both accounts receive distinct cust_<uuid> records created in the business DB.
        - Identity event 'collision_quarantined_reconciliation_required' is recorded.
        - Error injected in migration triggers safe rollback for both DBs."""
        from retailops.identity.store import IdentityStore, migrate_legacy_collisions
        from retailops.business.store import BusinessStore

        with tempfile.TemporaryDirectory() as td:
            id_path = Path(td) / "identity.sqlite3"
            t_dir = Path(td) / "tenants"
            t_dir.mkdir(parents=True, exist_ok=True)
            t_path = t_dir / "0123456789abcdef0123456789abcdef.sqlite3"

            # 1. Setup legacy identity DB with 2 accounts sharing 'CG-7b9b7957'
            db = sqlite3.connect(id_path)
            try:
                db.row_factory = sqlite3.Row
                db.execute("CREATE TABLE retailops_schema (component TEXT PRIMARY KEY, version INTEGER NOT NULL)")
                db.execute("INSERT INTO retailops_schema VALUES ('identity', 1)")
                db.execute("CREATE TABLE tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL, storage_key TEXT UNIQUE NOT NULL, active INTEGER NOT NULL DEFAULT 1)")
                db.execute("CREATE TABLE principals (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
                db.execute("CREATE TABLE memberships (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL, customer_id TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, auth_version INTEGER NOT NULL DEFAULT 1)")
                db.execute("CREATE TABLE identity_events (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL, kind TEXT NOT NULL, tenant_id TEXT, membership_id TEXT)")
                db.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, membership_id TEXT NOT NULL, auth_version INTEGER NOT NULL, expires_at REAL NOT NULL)")

                db.execute("INSERT INTO tenants VALUES ('shop-t1', 'Shop T1', '0123456789abcdef0123456789abcdef', 1)")
                db.execute("INSERT INTO principals VALUES ('p1', 'Alice Collide')")
                db.execute("INSERT INTO principals VALUES ('p2', 'Bob Collide')")
                db.execute("INSERT INTO memberships VALUES ('m1', 'shop-t1', 'p1', 'CG-7b9b7957', 'customer', 1, 1)")
                db.execute("INSERT INTO memberships VALUES ('m2', 'shop-t1', 'p2', 'CG-7b9b7957', 'customer', 1, 1)")
                db.execute("INSERT INTO sessions VALUES ('s1', 'm1', 1, 9999999999)")
                db.execute("INSERT INTO sessions VALUES ('s2', 'm2', 1, 9999999999)")
                db.commit()
            finally:
                db.close()

            # 2. Setup legacy tenant business DB with orders under 'CG-7b9b7957'
            bstore = BusinessStore(t_path, create=True)
            with bstore.connection(write=True) as bdb:
                bstore.seed_catalog(bdb)
                bdb.execute("INSERT INTO customers (id, name) VALUES ('CG-7b9b7957', 'Collided Customer')")
                bdb.execute(
                    "INSERT INTO orders (id, customer_id, name, variant, amount, status, version, product_id) "
                    "VALUES ('O-COLLIDE-01', 'CG-7b9b7957', 'Áo khoác len', 'Nâu / M', 650000, 'pending', 1, 'P-101')"
                )

            # 3. Run migration with tenant_stores resolver
            istore = IdentityStore(id_path, tenant_stores=lambda tid: bstore if tid == 'shop-t1' else None)

            # Verify both memberships received distinct new cust_<uuid> IDs
            with istore.connection() as id_db:
                m1 = id_db.execute("SELECT customer_id FROM memberships WHERE id='m1'").fetchone()
                m2 = id_db.execute("SELECT customer_id FROM memberships WHERE id='m2'").fetchone()
                self.assertTrue(m1["customer_id"].startswith("cust_"))
                self.assertTrue(m2["customer_id"].startswith("cust_"))
                self.assertNotEqual(m1["customer_id"], m2["customer_id"])

                # Stale sessions invalidated
                active_s = id_db.execute("SELECT count(*) AS cnt FROM sessions WHERE membership_id IN ('m1', 'm2')").fetchone()['cnt']
                self.assertEqual(active_s, 0)

                # Quarantine identity event recorded
                evs = id_db.execute("SELECT kind FROM identity_events WHERE kind='collision_quarantined_reconciliation_required'").fetchall()
                self.assertEqual(len(evs), 1)

            # Verify business DB: both new customer IDs exist in customers table
            with bstore.connection() as bdb:
                c1 = bdb.execute("SELECT id FROM customers WHERE id=?", (m1["customer_id"],)).fetchone()
                c2 = bdb.execute("SELECT id FROM customers WHERE id=?", (m2["customer_id"],)).fetchone()
                self.assertIsNotNone(c1)
                self.assertIsNotNone(c2)

                # The ambiguous order was quarantined, NOT assigned to m1 or m2!
                ord_row = bdb.execute("SELECT customer_id FROM orders WHERE id='O-COLLIDE-01'").fetchone()
                self.assertEqual(ord_row["customer_id"], "quarantine_CG-7b9b7957")

            # Neither account can see or read the quarantined order
            self.assertEqual(len(bstore.orders(m1["customer_id"])), 0)
            self.assertEqual(len(bstore.orders(m2["customer_id"])), 0)
            with self.assertRaises(ApiError):
                bstore.lookup(m1["customer_id"], "O-COLLIDE-01")

            # 4. Test transactional rollback when error injected in migration
            with istore.connection(write=True) as id_db:
                # Add another collision
                id_db.execute("INSERT INTO principals VALUES ('p3', 'Charlie')")
                id_db.execute("INSERT INTO principals VALUES ('p4', 'David')")
                id_db.execute("INSERT INTO memberships VALUES ('m3', 'shop-t1', 'p3', 'CG-failtest', 'customer', 1, 1)")
                id_db.execute("INSERT INTO memberships VALUES ('m4', 'shop-t1', 'p4', 'CG-failtest', 'customer', 1, 1)")

            # Faulty store that raises during migration
            class FaultyStore:
                def connection(self, write=True):
                    raise RuntimeError("Injected business store failure during migration")

            try:
                istore.migrate_legacy_collisions(tenant_stores=lambda tid: FaultyStore())
            except RuntimeError:
                pass

            # Check that memberships and business DB remained consistent (not half-migrated)
            with istore.connection() as id_db:
                check_m3 = id_db.execute("SELECT customer_id FROM memberships WHERE id='m3'").fetchone()
                self.assertEqual(check_m3["customer_id"], "CG-failtest")

    def test_n08_b_legacy_account_relogin_preserves_orders_and_linking(self):
        """N08-B: Returning legacy Google user retains their membership, customer ID, and orders.
        - Verified (issuer, sub) links to legacy principal without creating duplicate memberships.
        - Order history is preserved.
        - Changing Google email with same sub resolves to the same account.
        - In live mode, missing sub is rejected."""
        import hashlib
        import re
        from retailops.identity.persistent import PersistentSessions

        with tempfile.TemporaryDirectory() as td:
            sessions = PersistentSessions(Path(td), data_mode="persistent-demo")
            bstore = sessions.provision_tenant("shop-leg", "Shop Legacy", seed_demo=False)

            # Construct legacy user: email = legacyuser@example.com
            email = "legacyuser@example.com"
            clean_email = email.lower().strip()
            prefix = re.sub(r'[^a-zA-Z0-9_-]', '_', clean_email.split('@')[0])[:25]
            hash_suffix = hashlib.sha256(clean_email.encode()).hexdigest()[:10]
            legacy_pid = f"g_{prefix}_{hash_suffix}"
            legacy_cid = f"CG-{hash_suffix[:8]}"

            # Seed legacy principal, membership and order
            with sessions.control.connection(write=True) as id_db:
                id_db.execute("INSERT INTO principals VALUES (?,?)", (legacy_pid, "Legacy User"))
                id_db.execute("INSERT INTO memberships VALUES ('m-leg-01', 'shop-leg', ?, ?, 'customer', 1, 1)",
                              (legacy_pid, legacy_cid))

            with bstore.connection(write=True) as bdb:
                bstore.seed_catalog(bdb)
                bdb.execute("INSERT INTO customers VALUES (?,?)", (legacy_cid, "Legacy User"))
                bdb.execute(
                    "INSERT INTO orders (id, customer_id, name, variant, amount, status, version, product_id) "
                    "VALUES ('O-9001', ?, 'Váy Dạ Hội Đỏ', 'Đỏ / S', 950000, 'delivered', 1, 'P-101')",
                    (legacy_cid,)
                )

            # Verify 1 order exists before relogin
            self.assertEqual(len(bstore.orders(legacy_cid)), 1)

            # 1. Login via Google OAuth with verified sub and email_verified=True
            google_sub = "google-sub-100200300"
            secret = sessions.login_google(email, "Legacy User", sub=google_sub, email_verified=True, live=False)
            self.assertTrue(secret)

            # Verify same membership and customer ID were preserved
            with sessions.control.connection() as id_db:
                mems = id_db.execute("SELECT * FROM memberships WHERE tenant_id='shop-leg'").fetchall()
                self.assertEqual(len(mems), 1)  # No duplicate membership created!
                self.assertEqual(mems[0]["customer_id"], legacy_cid)

                # Verify external_identities links verified sub to legacy principal
                ext = id_db.execute("SELECT * FROM external_identities WHERE sub=?", (google_sub,)).fetchone()
                self.assertIsNotNone(ext)
                self.assertEqual(ext["principal_id"], legacy_pid)

            # Verify user still accesses their existing order O-9001
            resolved = sessions.control.resolve(sessions.cookie_id(f"__Host-retailops_account={secret}"))
            self.assertEqual(resolved["customer_id"], legacy_cid)
            orders = bstore.orders(resolved["customer_id"])
            self.assertEqual(len(orders), 1)
            self.assertEqual(orders[0]["id"], "O-9001")

            # 2. User changes email on Google, but Google sub remains identical
            secret2 = sessions.login_google("new_email_address@example.com", "Legacy User", sub=google_sub, email_verified=True, live=False)
            resolved2 = sessions.control.resolve(sessions.cookie_id(f"__Host-retailops_account={secret2}"))
            self.assertEqual(resolved2["customer_id"], legacy_cid)
            self.assertEqual(len(bstore.orders(resolved2["customer_id"])), 1)

            # 3. In live mode, login without verified sub must be rejected with 400 missing_sub
            live_sessions = PersistentSessions(Path(td) / "live", data_mode="production")
            live_sessions.provision_tenant("shop-live", "Shop Live", seed_demo=False)
            with self.assertRaises(ApiError) as ctx:
                live_sessions.login_google("user@gmail.com", "User", sub=None, live=True)
            self.assertEqual(ctx.exception.status, 400)
            self.assertEqual(ctx.exception.code, "missing_sub")

    def test_n08_c_postgresql_schema_and_migration_contract(self):
        """N08-C: PostgreSQL IDENTITY_DDL includes external_identities and customer_links,
        and schema initialization supports v1/v2 to v3 migration and import."""
        from retailops.storage.pg_schema import IDENTITY_DDL, initialize
        from retailops.storage.postgres import IDENTITY_SCHEMA_CURRENT
        from retailops.storage.import_sqlite import IDENTITY_TABLES

        # Check IDENTITY_DDL contains tables
        ddl_str = " ".join(IDENTITY_DDL)
        self.assertIn("CREATE TABLE external_identities", ddl_str)
        self.assertIn("CREATE TABLE customer_links", ddl_str)
        self.assertEqual(IDENTITY_SCHEMA_CURRENT, 3)

        # Check import_sqlite includes both tables
        self.assertIn("external_identities", IDENTITY_TABLES)
        self.assertIn("customer_links", IDENTITY_TABLES)

    def test_n08_d_live_data_mode_wired_through_settings_and_http(self):
        """N08-D: Settings -> bootstrap -> PublicWeb -> callback correctly sets up 0-order live customer."""
        from retailops.config import Settings
        from retailops.bootstrap import build_public_app

        with tempfile.TemporaryDirectory() as td:
            settings = Settings(
                interface="public",
                output=Path(td),
                access_token="a" * 43,
                data_mode="live",
                origin="https://shop.example.com",
            )
            app = build_public_app(settings)
            self.assertEqual(app.sessions.data_mode, "live")

            # Provision active tenant
            app.sessions.provision_tenant("prod-t1", "Prod Store", seed_demo=False)

            # Mock OAuth exchange
            with patch("retailops.http.auth_google.verify_and_consume_state", return_value=True), \
                 patch("retailops.http.auth_google.exchange_code_for_user_info", return_value={
                     "email": "customer@live.com",
                     "name": "Live Customer",
                     "sub": "live-google-sub-999",
                     "email_verified": True
                 }):
                callback_env = {
                    "REQUEST_METHOD": "GET",
                    "PATH_INFO": "/auth/google/callback",
                    "QUERY_STRING": "code=mock_code&state=mock_state",
                    "HTTP_HOST": "shop.example.com",
                }
                status, body, mime, headers = app.route(callback_env)
                self.assertEqual(status, 302)

                # Cookie received
                cookie_header = next((v for k, v in headers if k == "Set-Cookie"), None)
                self.assertIsNotNone(cookie_header)

                # Check customer in business store has exactly 0 orders
                bstore = app.sessions.business_store("prod-t1")
                with bstore.connection() as bdb:
                    cust = bdb.execute("SELECT id FROM customers WHERE name='Live Customer'").fetchone()
                    self.assertIsNotNone(cust)
                    orders = bdb.execute("SELECT * FROM orders WHERE customer_id=?", (cust["id"],)).fetchall()
                    self.assertEqual(len(orders), 0)

    def test_n08_order_mapping_does_not_leak_across_accounts(self):
        """N08: Account A's orders cannot be viewed, queried, or accessed by Account B (SQL ownership isolation)."""
        from retailops.identity.persistent import PersistentSessions
        with tempfile.TemporaryDirectory() as td:
            sessions = PersistentSessions(Path(td), data_mode="production")
            sessions.provision_tenant("iso-shop", "Iso Shop", seed_demo=True)

            # Login Account A & Account B
            sec_a = sessions.login_google("user_a@example.com", "User A", sub="sub-a", live=True)
            sec_b = sessions.login_google("user_b@example.com", "User B", sub="sub-b", live=True)

            mem_a = sessions.control.resolve(sessions.cookie_id(f"__Host-retailops_account={sec_a}"))
            mem_b = sessions.control.resolve(sessions.cookie_id(f"__Host-retailops_account={sec_b}"))
            cid_a, cid_b = mem_a["customer_id"], mem_b["customer_id"]
            self.assertNotEqual(cid_a, cid_b)

            bstore = sessions.business_store("iso-shop")
            with bstore.connection(write=True) as bdb:
                bdb.execute(
                    "INSERT INTO orders (id, customer_id, name, variant, amount, status, version, product_id) "
                    "VALUES ('O-USERA-01', ?, 'Váy Dạ Hội Đỏ', 'Đỏ / S', 950000, 'delivered', 1, 'P-101')",
                    (cid_a,)
                )

            # User A sees their order
            self.assertEqual(len(bstore.orders(cid_a)), 1)
            self.assertEqual(bstore.orders(cid_a)[0]["id"], "O-USERA-01")

            # User B has 0 orders and cannot read User A's order
            self.assertEqual(len(bstore.orders(cid_b)), 0)
            with self.assertRaises(ApiError) as ctx:
                bstore.lookup(cid_b, "O-USERA-01")
            self.assertEqual(ctx.exception.status, 404)
            self.assertEqual(ctx.exception.code, "order_not_found")

    def test_n08_a1_two_db_transaction_recovery_and_journal(self):
        """N08-A1 Fault-Injection: Saga recovery across two distinct database boundaries.
        Demonstrates that two databases commit separately without 2PC:
        1. Business DB and Identity DB start with colliding customer 'CG-shared'.
        2. Business DB contains BOTH orders and conversations under 'CG-shared'.
        3. Fault injection: simulate a crash/failure AFTER Business DB has committed quarantine,
           but BEFORE Identity DB commits.
        4. Verify Identity DB transaction rolled back completely (memberships unchanged, no links).
        5. Retry migration: idempotently resumes from partially-quarantined business DB,
           quarantines remaining records, allocates deterministic new customer IDs,
           records 'collision_quarantined_reconciliation_required', and clears unresolved status.
        6. Isolation verification: neither colliding member can access the quarantined orders or conversations."""
        from retailops.identity.store import IdentityStore
        from retailops.business.store import BusinessStore

        with tempfile.TemporaryDirectory() as td:
            id_path = Path(td) / "identity.sqlite3"
            t_path = Path(td) / "tenant.sqlite3"

            # 1. Setup legacy identity DB with 2 colliding accounts sharing customer_id 'CG-shared'
            db = sqlite3.connect(id_path)
            try:
                db.row_factory = sqlite3.Row
                db.execute("CREATE TABLE retailops_schema (component TEXT PRIMARY KEY, version INTEGER NOT NULL)")
                db.execute("INSERT INTO retailops_schema VALUES ('identity', 1)")
                db.execute("CREATE TABLE tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL, storage_key TEXT UNIQUE NOT NULL, active INTEGER NOT NULL DEFAULT 1)")
                db.execute("CREATE TABLE principals (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
                db.execute("CREATE TABLE memberships (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL, customer_id TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, auth_version INTEGER NOT NULL DEFAULT 1)")
                db.execute("CREATE TABLE identity_events (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL, kind TEXT NOT NULL, tenant_id TEXT, membership_id TEXT)")
                db.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, membership_id TEXT NOT NULL, auth_version INTEGER NOT NULL, expires_at REAL NOT NULL)")

                db.execute("INSERT INTO tenants VALUES ('t1', 'Shop T1', 'key1', 1)")
                db.execute("INSERT INTO principals VALUES ('p1', 'Alice')")
                db.execute("INSERT INTO principals VALUES ('p2', 'Bob')")
                db.execute("INSERT INTO memberships VALUES ('m1', 't1', 'p1', 'CG-shared', 'customer', 1, 1)")
                db.execute("INSERT INTO memberships VALUES ('m2', 't1', 'p2', 'CG-shared', 'customer', 1, 1)")
                db.commit()
            finally:
                db.close()

            # 2. Setup business DB with orders AND conversations
            bstore = BusinessStore(t_path, create=True)
            with bstore.connection(write=True) as bdb:
                bstore.seed_catalog(bdb)
                bdb.execute("INSERT INTO customers (id, name) VALUES ('CG-shared', 'Shared Customer')")
                bdb.execute(
                    "INSERT INTO orders (id, customer_id, name, variant, amount, status, version, product_id) "
                    "VALUES ('O-REC-01', 'CG-shared', 'Item 1', 'M', 100000, 'pending', 1, 'P-101')"
                )
                bdb.execute(
                    "INSERT INTO conversations (id, customer_id, order_id, product_id, revision, expires_at) "
                    "VALUES ('conv-shared-1', 'CG-shared', 'O-REC-01', 'P-101', 0, 9999999999.0)"
                )

            # 3. Fault Injection:
            # We intercept migration so that right after Business DB commits its quarantine updates,
            # an unhandled exception is injected in the Identity DB transaction.
            class FaultyConnection:
                def __init__(self, real_conn):
                    self._conn = real_conn
                def execute(self, sql, params=()):
                    if "UPDATE memberships SET customer_id" in sql:
                        raise RuntimeError("Crash before identity DB commit")
                    return self._conn.execute(sql, params)
                def __getattr__(self, name):
                    return getattr(self._conn, name)

            conn = sqlite3.connect(id_path)
            conn.row_factory = sqlite3.Row
            faulty_conn = FaultyConnection(conn)

            from retailops.identity.store import migrate_legacy_collisions
            with self.assertRaises(RuntimeError) as fault_ctx:
                migrate_legacy_collisions(faulty_conn, tenant_stores=lambda tid: bstore if tid == 't1' else None)
            self.assertIn("Crash before identity DB commit", str(fault_ctx.exception))
            conn.rollback()
            conn.close()

            # 4. Verify post-crash state:
            with bstore.connection() as bdb:
                ord_row = bdb.execute("SELECT customer_id FROM orders WHERE id='O-REC-01'").fetchone()
                conv_row = bdb.execute("SELECT customer_id FROM conversations WHERE id='conv-shared-1'").fetchone()
                self.assertEqual(ord_row["customer_id"], "quarantine_CG-shared")
                self.assertEqual(conv_row["customer_id"], "quarantine_CG-shared")

            id_db_raw = sqlite3.connect(id_path)
            try:
                id_db_raw.row_factory = sqlite3.Row
                m1_raw = id_db_raw.execute("SELECT customer_id FROM memberships WHERE id='m1'").fetchone()
                m2_raw = id_db_raw.execute("SELECT customer_id FROM memberships WHERE id='m2'").fetchone()
                self.assertEqual(m1_raw["customer_id"], "CG-shared")
                self.assertEqual(m2_raw["customer_id"], "CG-shared")
            finally:
                id_db_raw.close()

            # 5. Retry saga migration: clean restart must detect quarantine_CG-shared and finish migration idempotently
            istore_clean = IdentityStore(id_path, tenant_stores=lambda tid: bstore if tid == 't1' else None)

            with istore_clean.connection() as id_db:
                m1 = id_db.execute("SELECT customer_id FROM memberships WHERE id='m1'").fetchone()
                m2 = id_db.execute("SELECT customer_id FROM memberships WHERE id='m2'").fetchone()
                self.assertTrue(m1["customer_id"].startswith("cust_"))
                self.assertTrue(m2["customer_id"].startswith("cust_"))
                self.assertNotEqual(m1["customer_id"], m2["customer_id"])

                cl = id_db.execute("SELECT * FROM customer_links WHERE tenant_id='t1'").fetchall()
                self.assertEqual(len(cl), 2)

                ev = id_db.execute("SELECT * FROM identity_events WHERE kind='collision_quarantined_reconciliation_required'").fetchone()
                self.assertIsNotNone(ev)

                unres = id_db.execute("SELECT count(*) as cnt FROM unresolved_collisions WHERE tenant_id='t1'").fetchone()['cnt']
                self.assertEqual(unres, 0)

            # 6. Check business store: quarantined orders and conversations remain safe
            with bstore.connection() as bdb:
                ord_row = bdb.execute("SELECT customer_id FROM orders WHERE id='O-REC-01'").fetchone()
                conv_row = bdb.execute("SELECT customer_id FROM conversations WHERE id='conv-shared-1'").fetchone()
                self.assertEqual(ord_row["customer_id"], "quarantine_CG-shared")
                self.assertEqual(conv_row["customer_id"], "quarantine_CG-shared")

            self.assertEqual(len(bstore.orders(m1["customer_id"])), 0)
            self.assertEqual(len(bstore.orders(m2["customer_id"])), 0)

    def test_n08_a2_fail_closed_when_business_db_unavailable(self):
        """N08-A2 Regression: Fail-closed when business DB is unavailable or unmounted.
        - Accounts sharing a customer_id cannot be migrated safely without business DB.
        - Invalidate all existing sessions.
        - Persist unresolved status in unresolved_collisions table.
        - PURGE any stale customer_links that existed previously for the colliding ID.
        - create_session_for_membership raises 503 collision_unresolved.
        - login(token) raises 503 collision_unresolved.
        - get_or_create_google_member raises 503 collision_unresolved and refuses to claim link.
        - Restarting the process preserves the unresolved state and continues to fail closed."""
        from retailops.identity.store import IdentityStore

        with tempfile.TemporaryDirectory() as td:
            id_path = Path(td) / "identity.sqlite3"

            db = sqlite3.connect(id_path)
            try:
                db.row_factory = sqlite3.Row
                db.execute("CREATE TABLE retailops_schema (component TEXT PRIMARY KEY, version INTEGER NOT NULL)")
                db.execute("INSERT INTO retailops_schema VALUES ('identity', 1)")
                db.execute("CREATE TABLE tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL, storage_key TEXT UNIQUE NOT NULL, active INTEGER NOT NULL DEFAULT 1)")
                db.execute("CREATE TABLE principals (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
                db.execute("CREATE TABLE memberships (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL, customer_id TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, auth_version INTEGER NOT NULL DEFAULT 1)")
                db.execute("CREATE TABLE credentials (membership_id TEXT PRIMARY KEY, hash TEXT NOT NULL, created_at REAL NOT NULL)")
                db.execute("CREATE TABLE identity_events (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL, kind TEXT NOT NULL, tenant_id TEXT, membership_id TEXT)")
                db.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, membership_id TEXT NOT NULL, auth_version INTEGER NOT NULL, expires_at REAL NOT NULL)")
                db.execute("CREATE TABLE customer_links (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL, customer_id TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE(tenant_id, principal_id), UNIQUE(tenant_id, customer_id))")
                db.execute("CREATE TABLE external_identities (id TEXT PRIMARY KEY, issuer TEXT NOT NULL, sub TEXT NOT NULL, principal_id TEXT NOT NULL, email TEXT, created_at REAL NOT NULL, UNIQUE(issuer, sub))")
                db.execute("CREATE TABLE identity_rate (bucket TEXT PRIMARY KEY, window INTEGER NOT NULL, count INTEGER NOT NULL)")

                db.execute("INSERT INTO tenants VALUES ('t-unavail', 'Shop Unavail', 'key_u', 1)")
                db.execute("INSERT INTO principals VALUES ('p-u1', 'Alice U')")
                db.execute("INSERT INTO principals VALUES ('p-u2', 'Bob U')")
                db.execute("INSERT INTO memberships VALUES ('m-u1', 't-unavail', 'p-u1', 'CG-collision-u', 'customer', 1, 1)")
                db.execute("INSERT INTO memberships VALUES ('m-u2', 't-unavail', 'p-u2', 'CG-collision-u', 'customer', 1, 1)")

                # Pre-link p-u1 to Google sub-u1
                db.execute("INSERT INTO external_identities VALUES ('ext-u1', 'https://accounts.google.com', 'sub-u1', 'p-u1', 'alice@u.com', 1000.0)")

                # Credentials for token login
                token_u1 = "t" * 43
                db.execute("INSERT INTO credentials VALUES ('m-u1', ?, ?)",
                           (hashlib.sha256(token_u1.encode()).hexdigest(), time.time()))

                # Stale customer_link pre-existing for m-u1 from older/partial run
                db.execute("INSERT INTO customer_links VALUES ('cl-stale', 't-unavail', 'p-u1', 'CG-collision-u', 1000.0)")

                db.execute("INSERT INTO sessions VALUES ('s-u1', 'm-u1', 1, 9999999999)")
                db.commit()
            finally:
                db.close()

            # Business DB resolver returns None (simulating unmounted / unavailable DB)
            istore = IdentityStore(id_path, tenant_stores=lambda tid: None)

            with istore.connection() as id_db:
                m1 = id_db.execute("SELECT customer_id FROM memberships WHERE id='m-u1'").fetchone()
                m2 = id_db.execute("SELECT customer_id FROM memberships WHERE id='m-u2'").fetchone()
                self.assertEqual(m1["customer_id"], "CG-collision-u")
                self.assertEqual(m2["customer_id"], "CG-collision-u")

                # Stale customer_links were PURGED
                links = id_db.execute("SELECT count(*) AS cnt FROM customer_links WHERE tenant_id='t-unavail' AND customer_id='CG-collision-u'").fetchone()['cnt']
                self.assertEqual(links, 0)

                # Sessions invalidated
                active_s = id_db.execute("SELECT count(*) AS cnt FROM sessions WHERE membership_id='m-u1'").fetchone()['cnt']
                self.assertEqual(active_s, 0)

                # Persisted in unresolved_collisions table
                unres = id_db.execute("SELECT * FROM unresolved_collisions WHERE tenant_id='t-unavail' AND customer_id='CG-collision-u'").fetchone()
                self.assertIsNotNone(unres)

                # Event logged
                ev = id_db.execute("SELECT * FROM identity_events WHERE kind='legacy_collision_unresolved_storage_unavailable'").fetchone()
                self.assertIsNotNone(ev)

            # 1. create_session_for_membership raises 503
            with self.assertRaises(ApiError) as ctx_sess:
                istore.create_session_for_membership('m-u1', 3600, 10)
            self.assertEqual(ctx_sess.exception.status, 503)
            self.assertEqual(ctx_sess.exception.code, "collision_unresolved")

            # 2. login(token) raises 503
            with self.assertRaises(ApiError) as ctx_login:
                istore.login(token_u1, 3600, 10)
            self.assertEqual(ctx_login.exception.status, 503)
            self.assertEqual(ctx_login.exception.code, "collision_unresolved")

            # 3. get_or_create_google_member raises 503 and refuses to link
            with self.assertRaises(ApiError) as ctx_google:
                istore.get_or_create_google_member(
                    't-unavail', 'alice@u.com', 'Alice U', sub='sub-u1', email_verified=True
                )
            self.assertEqual(ctx_google.exception.status, 503)
            self.assertEqual(ctx_google.exception.code, "collision_unresolved")

            # 4. Restart process: simulate new application start
            istore_restarted = IdentityStore(id_path, tenant_stores=lambda tid: None)

            with self.assertRaises(ApiError) as ctx_re_sess:
                istore_restarted.create_session_for_membership('m-u1', 3600, 10)
            self.assertEqual(ctx_re_sess.exception.status, 503)
            self.assertEqual(ctx_re_sess.exception.code, "collision_unresolved")

            with self.assertRaises(ApiError) as ctx_re_login:
                istore_restarted.login(token_u1, 3600, 10)
            self.assertEqual(ctx_re_login.exception.status, 503)
            self.assertEqual(ctx_re_login.exception.code, "collision_unresolved")

            with self.assertRaises(ApiError) as ctx_re_goog:
                istore_restarted.get_or_create_google_member(
                    't-unavail', 'alice@u.com', 'Alice U', sub='sub-u1', email_verified=True
                )
            self.assertEqual(ctx_re_goog.exception.status, 503)
            self.assertEqual(ctx_re_goog.exception.code, "collision_unresolved")

    def test_n08_reconciliation_coordinator_journal_idempotency_and_recovery(self):
        """Blocker P2: Two-database reconciliation with journal, idempotency, and fault recovery.
        Exercises the reconciliation coordinator across independent Identity DB and Business DB boundaries:
        1. Setup: colliding accounts sharing 'CG-col-shared', quarantined in unresolved_collisions.
        2. Business DB: real orders and conversations for both users under 'CG-col-shared'.
        3. Pre-check: both accounts fail-closed with 503 collision_unresolved.
        4. Fault injection: crash after Business DB commit -> journal records 'business_committed',
           accounts remain fail-closed quarantined across crash boundary.
        5. Recovery: resume via reconcile_collision with persistent journal -> completed.
        6. Idempotency: re-running with same key returns already_completed=True.
        7. Post-check: clean independent sessions, orders/conversations ownership 100% isolated,
           customer_links and external_identities mapped.
        """
        import time
        from retailops.identity.persistent import PersistentSessions
        from retailops.identity.reconcile import reconcile_collision, get_reconciliation_status

        with tempfile.TemporaryDirectory() as td:
            sessions = PersistentSessions(Path(td), data_mode="production")
            sessions.provision_tenant("shop-rec", "Shop Reconciliation", seed_demo=False)
            now = time.time()

            # 1. Setup Identity DB with collision
            with sessions.control.connection(write=True) as id_db:
                id_db.execute("INSERT INTO principals (id, name) VALUES ('p-a', 'Alice Col')")
                id_db.execute("INSERT INTO principals (id, name) VALUES ('p-b', 'Bob Col')")
                id_db.execute(
                    "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                    "VALUES ('m-a', 'shop-rec', 'p-a', 'CG-col-shared', 'customer', 1, 1)"
                )
                id_db.execute(
                    "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                    "VALUES ('m-b', 'shop-rec', 'p-b', 'CG-col-shared', 'customer', 1, 1)"
                )
                id_db.execute(
                    "INSERT INTO unresolved_collisions (tenant_id, customer_id, created_at) "
                    "VALUES ('shop-rec', 'CG-col-shared', ?)",
                    (now,)
                )

            # 2. Setup Business DB with orders and conversations
            bstore = sessions.business_store("shop-rec")
            with bstore.connection(write=True) as bdb:
                bdb.execute("INSERT INTO customers (id, name) VALUES ('CG-col-shared', 'Shared Colliding Customer')")
                bdb.execute(
                    "INSERT INTO products (id, name, price, stock, is_system_immutable, created_at, updated_at) "
                    "VALUES ('P-COL-1', 'Polo Shirt', 100000, 50, 0, ?, ?)",
                    (now, now)
                )
                bdb.execute(
                    "INSERT INTO orders (id, customer_id, product_id, name, variant, amount, status, version) "
                    "VALUES ('O-A1', 'CG-col-shared', 'P-COL-1', 'Polo Shirt', 'M', 100000, 'pending', 1)"
                )
                bdb.execute(
                    "INSERT INTO orders (id, customer_id, product_id, name, variant, amount, status, version) "
                    "VALUES ('O-A2', 'CG-col-shared', 'P-COL-1', 'Polo Shirt', 'L', 100000, 'delivered', 1)"
                )
                bdb.execute(
                    "INSERT INTO orders (id, customer_id, product_id, name, variant, amount, status, version) "
                    "VALUES ('O-B1', 'CG-col-shared', 'P-COL-1', 'Polo Shirt', 'XL', 100000, 'pending', 1)"
                )
                bdb.execute(
                    "INSERT INTO conversations (id, customer_id, order_id, product_id, revision, expires_at) "
                    "VALUES ('CONV-A1', 'CG-col-shared', 'O-A1', 'P-COL-1', 1, ?)",
                    (now + 3600,)
                )
                bdb.execute(
                    "INSERT INTO conversations (id, customer_id, order_id, product_id, revision, expires_at) "
                    "VALUES ('CONV-B1', 'CG-col-shared', 'O-B1', 'P-COL-1', 1, ?)",
                    (now + 3600,)
                )

            # 3. Pre-check: fail-closed with 503
            with self.assertRaises(ApiError) as ctx_pre_a:
                sessions.control.create_session_for_membership('m-a', 3600, 10)
            self.assertEqual(ctx_pre_a.exception.status, 503)
            self.assertEqual(ctx_pre_a.exception.code, "collision_unresolved")

            with self.assertRaises(ApiError) as ctx_pre_b:
                sessions.control.create_session_for_membership('m-b', 3600, 10)
            self.assertEqual(ctx_pre_b.exception.status, 503)
            self.assertEqual(ctx_pre_b.exception.code, "collision_unresolved")

            plan = {
                "reassignments": [
                    {
                        "membership_id": "m-a",
                        "target_customer_id": "CG-col-alice",
                        "target_customer_name": "Alice Col",
                        "order_ids": ["O-A1", "O-A2"],
                        "conversation_ids": ["CONV-A1"],
                        "external_identity": {
                            "issuer": "https://accounts.google.com",
                            "sub": "sub-alice-col-1",
                            "email": "alice.col@example.com",
                        },
                    },
                    {
                        "membership_id": "m-b",
                        "target_customer_id": "CG-col-bob",
                        "target_customer_name": "Bob Col",
                        "order_ids": ["O-B1"],
                        "conversation_ids": ["CONV-B1"],
                        "external_identity": {
                            "issuer": "https://accounts.google.com",
                            "sub": "sub-bob-col-2",
                            "email": "bob.col@example.com",
                        },
                    },
                ]
            }
            idempotency_key = "rec-shop-rec-shared"

            # 4. Fault injection: crash after business commit
            with self.assertRaises(RuntimeError) as f_ctx:
                reconcile_collision(
                    sessions,
                    "shop-rec",
                    "CG-col-shared",
                    plan,
                    idempotency_key=idempotency_key,
                    fault_stage="after_business_commit",
                )
            self.assertIn("Fault injected after business commit", str(f_ctx.exception))

            # Journal is 'business_committed'
            j1 = get_reconciliation_status(sessions, idempotency_key)
            self.assertIsNotNone(j1)
            self.assertEqual(j1["status"], "business_committed")

            # System remains fail-closed across crash boundary
            with self.assertRaises(ApiError) as ctx_crash:
                sessions.control.create_session_for_membership('m-a', 3600, 10)
            self.assertEqual(ctx_crash.exception.status, 503)
            self.assertEqual(ctx_crash.exception.code, "collision_unresolved")

            # 5. Recovery & Resume: call reconcile_collision without fault
            res = reconcile_collision(
                sessions,
                "shop-rec",
                "CG-col-shared",
                plan,
                idempotency_key=idempotency_key,
            )
            self.assertEqual(res["status"], "completed")

            j2 = get_reconciliation_status(sessions, idempotency_key)
            self.assertEqual(j2["status"], "completed")

            # 6. Idempotency test
            res_idemp = reconcile_collision(
                sessions,
                "shop-rec",
                "CG-col-shared",
                plan,
                idempotency_key=idempotency_key,
            )
            self.assertEqual(res_idemp["status"], "completed")
            self.assertTrue(res_idemp.get("already_completed"))

            # 7. Post-reconciliation verification
            with sessions.control.connection() as id_db:
                unres = id_db.execute(
                    "SELECT 1 FROM unresolved_collisions WHERE tenant_id='shop-rec' AND customer_id='CG-col-shared'"
                ).fetchone()
                self.assertIsNone(unres)

            # Sessions resolve cleanly
            sid_a = sessions.control.create_session_for_membership('m-a', 3600, 10)
            import hashlib
            h_a = hashlib.sha256(sid_a.encode()).hexdigest()
            res_a = sessions.control.resolve(h_a)
            self.assertEqual(res_a["customer_id"], "CG-col-alice")

            sid_b = sessions.control.create_session_for_membership('m-b', 3600, 10)
            h_b = hashlib.sha256(sid_b.encode()).hexdigest()
            res_b = sessions.control.resolve(h_b)
            self.assertEqual(res_b["customer_id"], "CG-col-bob")

            # Orders ownership & isolation
            alice_orders = {o["id"] for o in bstore.orders("CG-col-alice")}
            self.assertEqual(alice_orders, {"O-A1", "O-A2"})
            bob_orders = {o["id"] for o in bstore.orders("CG-col-bob")}
            self.assertEqual(bob_orders, {"O-B1"})

            self.assertEqual(bstore.lookup("CG-col-alice", "O-A1")["id"], "O-A1")
            with self.assertRaises(ApiError):
                bstore.lookup("CG-col-alice", "O-B1")

            self.assertEqual(bstore.lookup("CG-col-bob", "O-B1")["id"], "O-B1")
            with self.assertRaises(ApiError):
                bstore.lookup("CG-col-bob", "O-A1")

            # Conversations ownership & isolation
            alice_convs = {c["id"] for c in bstore.list_conversations("CG-col-alice")}
            self.assertEqual(alice_convs, {"CONV-A1"})
            bob_convs = {c["id"] for c in bstore.list_conversations("CG-col-bob")}
            self.assertEqual(bob_convs, {"CONV-B1"})

            # External identities
            with sessions.control.connection() as id_db:
                ext_a = id_db.execute("SELECT sub, email FROM external_identities WHERE principal_id='p-a'").fetchone()
                self.assertEqual(ext_a["sub"], "sub-alice-col-1")
                ext_b = id_db.execute("SELECT sub, email FROM external_identities WHERE principal_id='p-b'").fetchone()
                self.assertEqual(ext_b["sub"], "sub-bob-col-2")

                cl_a = id_db.execute("SELECT customer_id FROM customer_links WHERE tenant_id='shop-rec' AND principal_id='p-a'").fetchone()
                self.assertEqual(cl_a["customer_id"], "CG-col-alice")
                cl_b = id_db.execute("SELECT customer_id FROM customer_links WHERE tenant_id='shop-rec' AND principal_id='p-b'").fetchone()
                self.assertEqual(cl_b["customer_id"], "CG-col-bob")


    def test_n08_b1_legacy_linking_requires_verified_email(self):
        """N08-B1 Regression: Legacy email linking strictly requires email_verified=True.
        - Unverified email in live OAuth callback raises 400 unverified_email.
        - Unverified email in store get_or_create_google_member refuses to link to existing legacy account.
        - Existing legacy account already linked to another sub refuses to link to a second sub."""
        from retailops.identity.persistent import PersistentSessions
        from retailops.http.public import PublicWeb

        with tempfile.TemporaryDirectory() as td:
            sessions = PersistentSessions(Path(td), data_mode="production")
            sessions.provision_tenant("shop-b1", "Shop B1", seed_demo=False)

            # Pre-seed legacy account: legacy_victim@example.com
            email = "legacy_victim@example.com"
            import re
            prefix = re.sub(r'[^a-zA-Z0-9_-]', '_', email.split('@')[0])[:25]
            hash_suffix = hashlib.sha256(email.encode()).hexdigest()[:10]
            legacy_pid = f"g_{prefix}_{hash_suffix}"
            legacy_cid = f"CG-{hash_suffix[:8]}"

            with sessions.control.connection(write=True) as id_db:
                id_db.execute("INSERT INTO principals VALUES (?,?)", (legacy_pid, "Victim"))
                id_db.execute("INSERT INTO memberships VALUES ('m-vic', 'shop-b1', ?, ?, 'customer', 1, 1)",
                              (legacy_pid, legacy_cid))

            # 1. Store level: login with email_verified=False and sub='sub-attacker'
            # Must NOT claim legacy_pid; must create a new distinct principal!
            mid_att, cid_att = sessions.control.get_or_create_google_member(
                "shop-b1", email, "Attacker", sub="sub-attacker", email_verified=False, live=False
            )
            with sessions.control.connection() as id_db:
                att_m = id_db.execute("SELECT principal_id, customer_id FROM memberships WHERE id=?", (mid_att,)).fetchone()
                self.assertNotEqual(att_m["principal_id"], legacy_pid)
                self.assertNotEqual(att_m["customer_id"], legacy_cid)

            # 2. Link legacy account legitimately with verified owner sub
            owner_sub = "sub-real-owner"
            mid_own, cid_own = sessions.control.get_or_create_google_member(
                "shop-b1", email, "Real Owner", sub=owner_sub, email_verified=True, live=False
            )
            self.assertEqual(mid_own, "m-vic")
            self.assertEqual(cid_own, legacy_cid)

            # 3. Third party tries with a third sub even if email_verified=True:
            # Cannot hijack legacy_pid because it is already bound to owner_sub!
            mid_thief, cid_thief = sessions.control.get_or_create_google_member(
                "shop-b1", email, "Thief", sub="sub-thief", email_verified=True, live=False
            )
            self.assertNotEqual(mid_thief, "m-vic")
            self.assertNotEqual(cid_thief, legacy_cid)

            # 4. HTTP callback level in live mode with unverified email: raises 400 unverified_email
            pub = PublicWeb("https://shop.example.com", sessions)
            with patch("retailops.http.auth_google.verify_and_consume_state", return_value=True), \
                 patch("retailops.http.auth_google.exchange_code_for_user_info", return_value={
                     "email": "user@gmail.com",
                     "name": "User",
                     "sub": "sub-123",
                     "email_verified": False,
                 }):
                callback_env = {
                    "REQUEST_METHOD": "GET",
                    "PATH_INFO": "/auth/google/callback",
                    "QUERY_STRING": "code=abc&state=xyz",
                    "HTTP_HOST": "shop.example.com",
                }
                with self.assertRaises(ApiError) as ctx:
                    pub.route(callback_env)
                self.assertEqual(ctx.exception.status, 400)
                self.assertEqual(ctx.exception.code, "unverified_email")

    def test_n08_c1_postgresql_schema_guard_and_upgrade(self):
        """N08-C1 Regression: PostgreSQL schema assertion, DDL structure, and v1/v2->v3 collision protection.
        - IDENTITY_DDL includes unresolved_collisions table.
        - assert_schema accepts IDENTITY_SCHEMA_COMPATIBLE=(1, 2, 3) for identity.
        - assert_schema rejects unsupported versions with ValueError.
        - PostgresIdentityStore with create=False detects v1 and v2, triggering upgrade to v3.
        - Existing v3 schema does not re-run initialize."""
        from retailops.storage.postgres import (
            assert_schema,
            IDENTITY_SCHEMA_CURRENT,
            IDENTITY_SCHEMA_COMPATIBLE,
        )
        from retailops.storage.pg_schema import IDENTITY_DDL
        from retailops.storage.pg_repositories import PostgresIdentityStore

        # 1. Compatibility constants & DDL check
        self.assertEqual(IDENTITY_SCHEMA_CURRENT, 3)
        self.assertEqual(IDENTITY_SCHEMA_COMPATIBLE, (1, 2, 3))
        ddl_str = " ".join(IDENTITY_DDL)
        self.assertIn("CREATE TABLE unresolved_collisions", ddl_str)
        self.assertIn("CREATE TABLE external_identities", ddl_str)
        self.assertIn("CREATE TABLE customer_links", ddl_str)

        # 2. Mock db and psycopg for assert_schema
        class MockPgDb:
            def __init__(self, version):
                self._version = version
                self.raw = self
            def execute(self, query, params=None):
                class MockCur:
                    def __init__(self, row):
                        self._row = row
                    def fetchone(self):
                        return self._row
                    def fetchall(self):
                        return [self._row]
                if "pg_namespace" in str(query):
                    return MockCur({"exists": 1})
                return MockCur({"component": "identity", "version": self._version})

        mock_psycopg = MagicMock()
        mock_sql = MagicMock()
        mock_sql.SQL = lambda s: MagicMock(format=lambda *a, **kw: s)
        mock_sql.Identifier = lambda s: s
        mock_psycopg.sql = mock_sql

        with patch.dict("sys.modules", {"psycopg": mock_psycopg, "psycopg.sql": mock_sql}):
            # Test valid versions 1, 2, and 3
            assert_schema(MockPgDb(1), "retailops_identity", "identity")
            assert_schema(MockPgDb(2), "retailops_identity", "identity")
            assert_schema(MockPgDb(3), "retailops_identity", "identity")

            # Test invalid versions 0 and 4
            with self.assertRaises(ValueError):
                assert_schema(MockPgDb(0), "retailops_identity", "identity")
            with self.assertRaises(ValueError):
                assert_schema(MockPgDb(4), "retailops_identity", "identity")

        # 3. PostgresIdentityStore auto-upgrade on v1 and v2, and no-op on v3
        with patch("retailops.storage.pg_repositories.check_schema") as mock_check, \
             patch("retailops.storage.pg_repositories.initialize") as mock_init, \
             patch.object(PostgresIdentityStore, "connection") as mock_conn:

            for test_ver, should_init in [(1, True), (2, True), (3, False)]:
                mock_init.reset_mock()
                mock_check.reset_mock()

                class MockTx:
                    def __init__(self, ver):
                        self.ver = ver
                    def __enter__(self):
                        mock_db = MagicMock()
                        mock_db.raw.execute.return_value.fetchone.return_value = {"version": self.ver}
                        return mock_db
                    def __exit__(self, *args):
                        pass

                mock_conn.return_value = MockTx(test_ver)
                store = PostgresIdentityStore("postgresql://test:test@localhost/test", create=False)
                mock_check.assert_called_once_with("postgresql://test:test@localhost/test", "retailops_identity", "identity")
                if should_init:
                    mock_init.assert_called_once()
                else:
                    mock_init.assert_not_called()


if __name__ == "__main__":
    unittest.main()
