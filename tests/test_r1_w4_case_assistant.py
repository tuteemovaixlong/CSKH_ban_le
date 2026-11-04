"""Phase R1 W4 Item 5 tests: Scoped Staff/Manager Case Assistant & partitioned history (W4-D1, W4-D4, W4-D5)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from agent_protocol import PROTOCOL, TOOLS
from retailops.business.application import Application
from retailops.business.permissions import ROLE_PERMISSIONS
from retailops.business.store import BusinessStore
from retailops.core import ApiError
from retailops.http.routes import api_result
from retailops.identity.contracts import RequestContext
from retailops.workflow.case_assist import STAFF_CASE_ASSIST_TOOLS
from retailops_providers import OpenRouterAgent


class _ScriptedFakeGateway:
    """Fake model gateway returning scripted tool_calls / answers without any network call."""

    def __init__(self, steps: list[dict]):
        self.steps = list(steps)
        self.calls: list[dict] = []

    def inspect(self):
        return {
            "name": "fake-case-assist-model",
            "digest": "sha256:fakew4",
            "provider": "custom_api",
            "ollama_version": None,
            "agent_protocol": PROTOCOL,
        }

    def chat_profile(self, messages, allow_tools, timeout, *, system_prompt, tool_schemas):
        self.calls.append(
            {
                "method": "chat_profile",
                "messages": json.loads(json.dumps(messages, ensure_ascii=False)),
                "allow_tools": allow_tools,
                "system_prompt": system_prompt,
                "tool_names": [t["function"]["name"] for t in tool_schemas],
            }
        )
        msg = self.steps.pop(0)
        return {
            "message": msg,
            "done_reason": "stop",
            "model": "fake-case-assist-model",
            "prompt_eval_count": 120,
            "eval_count": 45,
            "reported_cost_usd": None,
            "reasoning": None,
        }

    def chat(self, messages, allow_tools, timeout):
        self.calls.append(
            {
                "method": "chat",
                "messages": json.loads(json.dumps(messages, ensure_ascii=False)),
                "allow_tools": allow_tools,
            }
        )
        msg = self.steps.pop(0)
        return {
            "message": msg,
            "done_reason": "stop",
            "model": "fake-case-assist-model",
            "prompt_eval_count": 120,
            "eval_count": 45,
            "reported_cost_usd": None,
            "reasoning": None,
        }


def _make_ctx(role: str, principal_id: str, customer_id: str = "C-001", tenant_id: str = "tenant_w4", display_name: str = "") -> RequestContext:
    return RequestContext(
        customer_id=customer_id,
        role=role,
        permissions=ROLE_PERMISSIONS[role],
        tenant_id=tenant_id,
        principal_id=principal_id,
        membership_id=f"mem_{principal_id}",
        display_name=display_name or principal_id,
        session_scope="persistent-account",
        data_mode="persistent-demo",
        authenticated_session=True,
    )


class TestR1W4CaseAssistant(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "w4_case_assist.sqlite3"
        self.now = 1_762_200_000.0
        self.store = BusinessStore(self.db_path)
        self.store._now = lambda: self.now
        self.store.tenant_id = "tenant_w4"
        self.store.data_root = Path(self.tmp.name) / "data"
        self.store.seed()

        # Seed a second customer & order O-201 to test out-of-case scope isolation
        with self.store.connection(write=True) as db:
            db.execute("INSERT OR IGNORE INTO customers(id, name) VALUES ('C-002', 'Trần Văn B - 0909999888')")
            db.execute(
                """INSERT OR IGNORE INTO orders(id, customer_id, product_id, name, variant, amount, status, version)
                   VALUES ('O-201', 'C-002', 'P-101', 'Áo thun người khác', 'Đen · Size L', 250000, 'pending', 1)"""
            )

        # Open a customer conversation and escalate to human support so we have an active case
        conv = self.store.new_conversation("C-001", "custom")
        self.cid = conv["conversation_id"]
        self.case_id = conv["case_id"]
        self.store.customer_message("C-001", self.cid, "Cho mình hỏi đơn O-101 đổi sang màu khác được không?")
        handoff = self.store.request_human_handoff(
            "C-001",
            self.cid,
            reason_code="customer_requested",
            comment="Khách cần nhân viên tư vấn đơn O-101",
        )
        self.handoff_id = handoff["handoff_id"]

        self.customer_ctx = _make_ctx("customer", "cust_p1", customer_id="C-001")
        self.staff_a_ctx = _make_ctx("staff", "staff_a", customer_id="C-STAFF-A", display_name="Nhân viên A")
        self.staff_b_ctx = _make_ctx("staff", "staff_b", customer_id="C-STAFF-B", display_name="Nhân viên B")
        self.manager_ctx = _make_ctx("manager", "mgr_1", customer_id="C-MGR-1", display_name="Quản lý 1")

    def tearDown(self):
        self.tmp.cleanup()

    def _make_app(self, gateway) -> Application:
        return Application(
            self.store,
            {},
            infer=gateway,
            role="staff",
            tenant_id="tenant_w4",
        )

    def test_customer_tools_unchanged_and_staff_tools_isolated(self):
        self.assertEqual(len(TOOLS), 12)
        staff_tool_names = [t["function"]["name"] for t in STAFF_CASE_ASSIST_TOOLS]
        self.assertEqual(
            staff_tool_names,
            [
                "get_case_transcript",
                "list_case_orders",
                "get_case_order",
                "list_case_order_actions",
                "search_knowledge",
            ],
        )

    def test_non_holding_staff_and_customer_blocked_while_holder_and_manager_allowed(self):
        gw = _ScriptedFakeGateway(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": "get_case_transcript", "arguments": {}}}],
                },
                {
                    "role": "assistant",
                    "content": "Tóm tắt: Khách đang hỏi về đơn O-101.",
                },
                {
                    "role": "assistant",
                    "content": "Quản lý ghi nhận: Đơn O-101 đang ở trạng thái chờ xử lý.",
                },
            ]
        )
        app = self._make_app(gw)

        # 1. Customer cannot call /api/staff/cases/<case_id>/assist
        with self.assertRaises(ApiError) as cust_err:
            api_result(
                app,
                "C-001",
                "POST",
                f"/api/staff/cases/{self.case_id}/assist",
                body={"mode": "summary"},
                context=self.customer_ctx,
            )
        self.assertEqual(cust_err.exception.status, 403)
        self.assertEqual(cust_err.exception.code, "permission_denied")

        # 2. Case is still waiting (unclaimed): Staff A is rejected and audited
        with self.assertRaises(ApiError) as unclaimed_err:
            api_result(
                app,
                "C-STAFF-A",
                "POST",
                f"/api/staff/cases/{self.case_id}/assist",
                body={"mode": "summary"},
                context=self.staff_a_ctx,
            )
        self.assertEqual(unclaimed_err.exception.status, 403)
        self.assertEqual(unclaimed_err.exception.code, "case_not_held")

        # 3. Staff A claims the case -> Staff B (not holding) is still rejected
        api_result(
            app,
            "C-STAFF-A",
            "POST",
            f"/api/staff/cases/{self.case_id}/claim",
            body={},
            context=self.staff_a_ctx,
        )
        with self.assertRaises(ApiError) as other_staff_err:
            api_result(
                app,
                "C-STAFF-B",
                "POST",
                f"/api/staff/cases/{self.case_id}/assist",
                body={"mode": "summary"},
                context=self.staff_b_ctx,
            )
        self.assertEqual(other_staff_err.exception.status, 403)
        self.assertEqual(other_staff_err.exception.code, "case_not_held")

        # 4. Staff A (holder) succeeds!
        st, res_a = api_result(
            app,
            "C-STAFF-A",
            "POST",
            f"/api/staff/cases/{self.case_id}/assist",
            body={"mode": "summary"},
            context=self.staff_a_ctx,
        )
        self.assertEqual(st, 200)
        self.assertEqual(res_a["mode"], "summary")
        self.assertIn("O-101", res_a["answer"])
        self.assertIsNone(res_a["draft_reply"])

        # Verify model payload used chat_profile with STAFF_CASE_ASSIST_TOOLS and contained zero customer PII ("Mai Anh")
        self.assertEqual(gw.calls[0]["method"], "chat_profile")
        self.assertEqual(
            gw.calls[0]["tool_names"],
            ["get_case_transcript", "list_case_orders", "get_case_order", "list_case_order_actions", "search_knowledge"],
        )
        serialized_call_2 = json.dumps(gw.calls[1]["messages"], ensure_ascii=False)
        self.assertNotIn("Mai Anh", serialized_call_2)

        # 5. Manager (not holding the case) also succeeds!
        st_mgr, res_mgr = api_result(
            app,
            "C-MGR-1",
            "POST",
            f"/api/staff/cases/{self.case_id}/assist",
            body={"mode": "ask", "question": "Tình trạng đơn O-101 sao rồi?"},
            context=self.manager_ctx,
        )
        self.assertEqual(st_mgr, 200)
        self.assertEqual(res_mgr["mode"], "ask")
        self.assertIn("O-101", res_mgr["answer"])

        # Audit events recorded for both denied and allowed uses
        mgr_events = self.store.manager_events(limit=50)
        kinds = [e["kind"] for e in mgr_events]
        self.assertIn("staff_case_assist_denied", kinds)
        self.assertIn("staff_case_assist_used", kinds)

        # Customer /api/events must NEVER leak internal staff_case_assist_* events
        _, cust_events = api_result(app, "C-001", "GET", "/api/events", context=self.customer_ctx)
        cust_kinds = {e["kind"] for e in cust_events["events"]}
        self.assertFalse(cust_kinds & {"staff_case_assist_used", "staff_case_assist_denied", "staff_case_assist_failed"})

    def test_out_of_case_order_and_mutation_tools_rejected_without_side_effects(self):
        gw = _ScriptedFakeGateway(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "get_case_order", "arguments": {"order_id": "O-201"}}},
                        {"function": {"name": "prepare_order_action", "arguments": {"order_id": "O-101", "action_type": "cancel"}}},
                        {"function": {"name": "approve_order_action", "arguments": {"request_id": "oar_fake"}}},
                        {"function": {"name": "get_case_order", "arguments": {"order_id": "O-101"}}},
                    ],
                },
                {
                    "role": "assistant",
                    "content": "Đơn O-201 không thuộc ca này. Đơn O-101 của khách trong ca đang ở trạng thái pending.",
                },
            ]
        )
        app = self._make_app(gw)
        api_result(app, "C-STAFF-A", "POST", f"/api/staff/cases/{self.case_id}/claim", body={}, context=self.staff_a_ctx)

        st, res = api_result(
            app,
            "C-STAFF-A",
            "POST",
            f"/api/staff/cases/{self.case_id}/assist",
            body={"mode": "ask", "question": "Kiểm tra đơn O-201 và O-101"},
            context=self.staff_a_ctx,
        )
        self.assertEqual(st, 200)
        tools_trace = res["trace"]["tools"]
        self.assertEqual(
            [(t["name"], t["status"], t.get("error_code")) for t in tools_trace],
            [
                ("get_case_order", "error", "order_outside_case_scope"),
                ("prepare_order_action", "error", "tool_not_allowed"),
                ("approve_order_action", "error", "tool_not_allowed"),
                ("get_case_order", "ok", None),
            ],
        )

        # Verify zero PII of C-002 leaked to the model and zero order mutations occurred
        second_call_msgs = json.dumps(gw.calls[1]["messages"], ensure_ascii=False)
        self.assertNotIn("Trần Văn B", second_call_msgs)
        self.assertNotIn("0909999888", second_call_msgs)
        self.assertNotIn("Áo thun người khác", second_call_msgs)

        with self.store.connection() as db:
            o101 = db.execute("SELECT status, version FROM orders WHERE id='O-101'").fetchone()
            o201 = db.execute("SELECT status, version FROM orders WHERE id='O-201'").fetchone()
            oar_cnt = db.execute("SELECT COUNT(*) AS cnt FROM order_action_requests").fetchone()["cnt"]
        self.assertEqual((o101["status"], o101["version"]), ("pending", 1))
        self.assertEqual((o201["status"], o201["version"]), ("pending", 1))
        self.assertEqual(oar_cnt, 0)

    def test_draft_not_in_customer_transcript_until_staff_replies_and_caches_bypassed(self):
        gw = _ScriptedFakeGateway(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "get_case_transcript", "arguments": {}}},
                        {"function": {"name": "list_case_orders", "arguments": {}}},
                    ],
                },
                {
                    "role": "assistant",
                    "content": (
                        "Ghi chú cho nhân viên: Đơn O-101 đang ở trạng thái pending nên chỉ hỗ trợ hủy đơn.\n"
                        "<draft_reply>\n"
                        "Chào anh/chị, hiện đơn O-101 đang ở trạng thái chờ xử lý (pending) nên bên em có thể hỗ trợ hủy đơn để anh/chị đặt lại màu mới ạ.\n"
                        "</draft_reply>"
                    ),
                },
            ]
        )
        app = self._make_app(gw)
        # Pre-seed caches to prove Case Assistant neither reads nor writes them
        app.semantic_cache.store("Hãy soạn bản nháp", "CACHED_WRONG_ANSWER", action="reply")
        api_result(app, "C-STAFF-A", "POST", f"/api/staff/cases/{self.case_id}/claim", body={}, context=self.staff_a_ctx)

        with (
            patch.object(app.tool_cache, "get", wraps=app.tool_cache.get) as spy_tc_get,
            patch.object(app.tool_cache, "set", wraps=app.tool_cache.set) as spy_tc_set,
            patch.object(app.semantic_cache, "lookup", wraps=app.semantic_cache.lookup) as spy_sc_lookup,
            patch.object(app.semantic_cache, "store", wraps=app.semantic_cache.store) as spy_sc_store,
        ):
            st, res = api_result(
                app,
                "C-STAFF-A",
                "POST",
                f"/api/staff/cases/{self.case_id}/assist",
                body={"mode": "draft"},
                context=self.staff_a_ctx,
            )
            self.assertEqual(st, 200)
            self.assertEqual(spy_tc_get.call_count, 0)
            self.assertEqual(spy_tc_set.call_count, 0)
            self.assertEqual(spy_sc_lookup.call_count, 0)
            self.assertEqual(spy_sc_store.call_count, 0)

        self.assertIsNotNone(res["draft_reply"])
        self.assertIn("Chào anh/chị, hiện đơn O-101", res["draft_reply"])
        self.assertNotIn("<draft_reply>", res["draft_reply"])
        self.assertNotIn("<draft_reply>", res["answer"])
        self.assertTrue(res["trace"].get("cache_bypassed"))

        # Draft MUST NOT appear in customer transcript before staff manually sends it!
        _, cust_trans_before = api_result(
            app, "C-001", "GET", f"/api/conversations/{self.cid}/messages", context=self.customer_ctx
        )
        before_blob = json.dumps(cust_trans_before, ensure_ascii=False)
        self.assertNotIn("hỗ trợ hủy đơn để anh/chị đặt lại màu mới", before_blob)

        # Now Staff A reviews/edits the draft and explicitly sends via /api/staff/reply
        edited_reply = res["draft_reply"] + " Anh/chị xác nhận giúp em nhé!"
        st_rep, _ = api_result(
            app,
            "C-STAFF-A",
            "POST",
            "/api/staff/reply",
            body={"case_id": self.case_id, "message": edited_reply},
            context=self.staff_a_ctx,
        )
        self.assertEqual(st_rep, 200)

        _, cust_trans_after = api_result(
            app, "C-001", "GET", f"/api/conversations/{self.cid}/messages", context=self.customer_ctx
        )
        after_blob = json.dumps(cust_trans_after, ensure_ascii=False)
        self.assertIn("Anh/chị xác nhận giúp em nhé!", after_blob)

    def test_partitioned_history_isolated_per_principal_and_purged_after_case_retention(self):
        gw = _ScriptedFakeGateway(
            [
                {"role": "assistant", "content": "Phản hồi riêng cho Nhân viên A."},
                {"role": "assistant", "content": "Phản hồi riêng cho Nhân viên B."},
                {"role": "assistant", "content": "Phản hồi riêng cho Quản lý 1."},
            ]
        )
        app = self._make_app(gw)

        # Staff A claims and uses Case Assistant
        api_result(app, "C-STAFF-A", "POST", f"/api/staff/cases/{self.case_id}/claim", body={}, context=self.staff_a_ctx)
        api_result(
            app,
            "C-STAFF-A",
            "POST",
            f"/api/staff/cases/{self.case_id}/assist",
            body={"mode": "ask", "question": "Câu hỏi mật của A"},
            context=self.staff_a_ctx,
        )

        # Staff B checks history while Staff A holds -> sees empty turns
        _, hist_b_while_a_holds = api_result(
            app, "C-STAFF-B", "GET", f"/api/staff/cases/{self.case_id}/assist", context=self.staff_b_ctx
        )
        self.assertEqual(hist_b_while_a_holds["turns"], [])
        self.assertFalse(hist_b_while_a_holds["can_assist"])

        # Staff A releases the case; Staff B claims the case -> Staff B STILL sees zero of Staff A's turns!
        api_result(app, "C-STAFF-A", "POST", f"/api/staff/cases/{self.case_id}/release", body={}, context=self.staff_a_ctx)
        api_result(app, "C-STAFF-B", "POST", f"/api/staff/cases/{self.case_id}/claim", body={}, context=self.staff_b_ctx)

        _, hist_b_after_claim = api_result(
            app, "C-STAFF-B", "GET", f"/api/staff/cases/{self.case_id}/assist", context=self.staff_b_ctx
        )
        self.assertEqual(hist_b_after_claim["turns"], [])
        self.assertTrue(hist_b_after_claim["can_assist"])

        # Staff B and Manager each run their own turn
        api_result(
            app,
            "C-STAFF-B",
            "POST",
            f"/api/staff/cases/{self.case_id}/assist",
            body={"mode": "ask", "question": "Câu hỏi riêng của B"},
            context=self.staff_b_ctx,
        )
        api_result(
            app,
            "C-MGR-1",
            "POST",
            f"/api/staff/cases/{self.case_id}/assist",
            body={"mode": "ask", "question": "Câu hỏi riêng của Quản lý"},
            context=self.manager_ctx,
        )

        _, hist_a = api_result(app, "C-STAFF-A", "GET", f"/api/staff/cases/{self.case_id}/assist", context=self.staff_a_ctx)
        _, hist_b = api_result(app, "C-STAFF-B", "GET", f"/api/staff/cases/{self.case_id}/assist", context=self.staff_b_ctx)
        _, hist_m = api_result(app, "C-MGR-1", "GET", f"/api/staff/cases/{self.case_id}/assist", context=self.manager_ctx)

        self.assertEqual([t["answer"] for t in hist_a["turns"]], ["Phản hồi riêng cho Nhân viên A."])
        self.assertEqual([t["answer"] for t in hist_b["turns"]], ["Phản hồi riêng cho Nhân viên B."])
        self.assertEqual([t["answer"] for t in hist_m["turns"]], ["Phản hồi riêng cho Quản lý 1."])

        # Resolve the case: within retention, history still exists; past retention TTL, purged!
        api_result(
            app,
            "C-STAFF-B",
            "POST",
            "/api/staff/resolve",
            body={"case_id": self.case_id},
            context=self.staff_b_ctx,
        )
        self.now += 60.0
        _, hist_m_within = api_result(
            app, "C-MGR-1", "GET", f"/api/staff/cases/{self.case_id}/assist", context=self.manager_ctx
        )
        self.assertEqual(len(hist_m_within["turns"]), 1)

        # Advance past 7-day CONVERSATION_TTL retention
        self.now += float(self.store.CONVERSATION_TTL) + 120.0
        purge_res = self.store.purge_expired_case_assist_turns(now=self.now)
        self.assertEqual(purge_res["purged"], 3)

        with self.store.connection() as db:
            rem = db.execute("SELECT COUNT(*) AS cnt FROM case_assist_turns WHERE case_id = ?", (self.case_id,)).fetchone()
        self.assertEqual(rem["cnt"], 0)

        with self.assertRaises(ApiError) as exp_err:
            api_result(app, "C-MGR-1", "GET", f"/api/staff/cases/{self.case_id}/assist", context=self.manager_ctx)
        self.assertEqual(exp_err.exception.status, 403)
        self.assertEqual(exp_err.exception.code, "case_retention_expired")

    def test_openrouter_agent_chat_profile_sends_case_assist_tools_without_customer_prompt(self):
        captured = {}

        def fake_request(payload, timeout):
            captured["payload"] = payload
            return {
                "model": "google/gemma-4-31b-it:free",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Đã kiểm tra ca."},
                    }
                ],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10},
            }

        agent = OpenRouterAgent("k" * 40, "google/gemma-4-31b-it:free")
        with patch.object(agent, "request", side_effect=fake_request):
            res = agent.chat_profile(
                [
                    {"role": "system", "content": "Custom case assist system prompt"},
                    {"role": "user", "content": "[Chế độ: summary] Tóm tắt ca"},
                ],
                True,
                30,
                system_prompt="Custom case assist system prompt",
                tool_schemas=STAFF_CASE_ASSIST_TOOLS,
            )
        self.assertEqual(res["message"]["content"], "Đã kiểm tra ca.")
        self.assertEqual(captured["payload"]["messages"][0]["content"], "Custom case assist system prompt")
        sent_tools = [t["function"]["name"] for t in captured["payload"]["tools"]]
        self.assertEqual(
            sent_tools,
            ["get_case_transcript", "list_case_orders", "get_case_order", "list_case_order_actions", "search_knowledge"],
        )


if __name__ == "__main__":
    unittest.main()
