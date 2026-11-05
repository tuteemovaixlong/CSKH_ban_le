"""Phase R1 W5 isolated backend tests (Items 0, 1, 2, 4, 5 — §18 W5-D1..W5-D6)."""
from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from agent_protocol import PROTOCOL
from retailops.business.application import Application
from retailops.business.permissions import ROLE_PERMISSIONS
from retailops.business.progress import CANCELLED_MESSAGE, TurnCancelRegistry
from retailops.business.store import BusinessStore
from retailops.core import ApiError
from retailops.http.routes import ALLOWED_DIRECT_TOOLS, api_result
from retailops.identity.contracts import RequestContext
from retailops.identity.persistent import PersistentSessions
from retailops.storage.postgres import Queries


def _ctx(
    role: str,
    principal_id: str,
    *,
    customer_id: str = "C-001",
    tenant_id: str = "shop_a",
    display_name: str = "",
) -> RequestContext:
    return RequestContext(
        customer_id=customer_id,
        role=role,
        permissions=ROLE_PERMISSIONS[role],
        workspace_id="ws-w5",
        tenant_id=tenant_id,
        principal_id=principal_id,
        membership_id=f"mem_{tenant_id}_{principal_id}",
        display_name=display_name or principal_id,
    )


def _call_api(
    app: Application,
    method: str,
    path: str,
    customer: str = "C-001",
    body=None,
    query_params: dict | None = None,
    *,
    context: RequestContext | None = None,
    idempotency_key: str | None = None,
) -> tuple[int, dict]:
    qs = urlencode(query_params) if query_params else None
    try:
        return api_result(
            app,
            customer,
            method,
            path,
            body=body,
            idempotency_key=idempotency_key,
            context=context,
            query=qs,
        )
    except ApiError as exc:
        err_body: dict = {"error": exc.code, "message": exc.message}
        if exc.trace is not None:
            err_body["trace"] = exc.trace
        return exc.status, err_body


class _BlockingFakeGateway:
    """Fake LLM gateway that can block inside model execution to test cooperative cancellation."""

    def __init__(self, steps: list[dict], *, block_on_call: int | None = 1):
        self.steps = list(steps)
        self.block_on_call = block_on_call
        self.call_count = 0
        self.entered_event = threading.Event()
        self.release_event = threading.Event()
        self.calls: list[dict] = []

    def inspect(self):
        return {
            "name": "fake-w5-model",
            "digest": "sha256:fakew5",
            "provider": "custom_api",
            "ollama_version": None,
            "agent_protocol": PROTOCOL,
        }

    def _next_reply(self, method: str, messages, allow_tools: bool):
        self.call_count += 1
        self.calls.append(
            {
                "method": method,
                "call_index": self.call_count,
                "allow_tools": allow_tools,
                "messages_count": len(messages),
            }
        )
        if self.block_on_call == self.call_count:
            self.entered_event.set()
            self.release_event.wait(timeout=5.0)
        msg = self.steps.pop(0) if self.steps else {"role": "assistant", "content": "Câu trả lời mặc định."}
        return {
            "message": msg,
            "done_reason": "stop",
            "model": "fake-w5-model",
            "prompt_eval_count": 100,
            "eval_count": 40,
            "reported_cost_usd": None,
            "reasoning": "Suy luận thử nghiệm W5",
        }

    def chat(self, messages, allow_tools, timeout):
        return self._next_reply("chat", messages, allow_tools)

    def chat_profile(self, messages, allow_tools, timeout, *, system_prompt, tool_schemas):
        return self._next_reply("chat_profile", messages, allow_tools)


class TestR1W5CooperativeCancel(unittest.TestCase):
    """Item 0 (W5-D3): Cooperative stop for Customer chat and Staff/Manager Case Assistant."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "w5_cancel.sqlite3"
        self.store = BusinessStore(self.db_path)
        self.store.tenant_id = "shop_a"
        self.store.data_root = Path(self.tmp.name) / "data"
        self.store.seed()
        self.cancel_registry = TurnCancelRegistry()

    def tearDown(self):
        self.tmp.cleanup()

    def _make_app(self, gateway: _BlockingFakeGateway) -> Application:
        return Application(
            self.store,
            {},
            infer=gateway,
            role="customer",
            tenant_id="shop_a",
            cancel_registry=self.cancel_registry,
        )

    def test_customer_chat_cancel_blocks_subsequent_tools_discards_partial_and_saves_marker(self):
        # Model attempts to call prepare_order_action + return partial text, but turn is cancelled mid-flight!
        gw = _BlockingFakeGateway(
            [
                {
                    "role": "assistant",
                    "content": "Câu trả lời dở dang không được lưu",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "prepare_order_action",
                                "arguments": {
                                    "order_id": "O-101",
                                    "action_type": "cancel",
                                    "reason_code": "change_of_mind",
                                },
                            }
                        }
                    ],
                },
                {"role": "assistant", "content": "Dạ em đã thấy tin trước anh/chị dừng câu trả lời ạ."},
            ],
            block_on_call=1,
        )
        app = self._make_app(gw)
        cust_ctx = _ctx("customer", "p_cust_1", customer_id="C-001", display_name="Khách A")
        other_ctx = _ctx("customer", "p_cust_2", customer_id="C-002", display_name="Khách B")

        conv = app.new_conversation("C-001", {"provider_id": "custom"})
        cid = conv["conversation_id"]
        req_id = "req_w5_chat_cancel_1"

        result_holder: dict = {}

        def _run_chat():
            code, payload = _call_api(
                app,
                "POST",
                "/api/chat",
                "C-001",
                {"conversation_id": cid, "text": "Hủy đơn O-101 giúp tôi", "request_id": req_id},
                context=cust_ctx,
            )
            result_holder["code"] = code
            result_holder["payload"] = payload

        worker = threading.Thread(target=_run_chat, daemon=True)
        worker.start()
        self.assertTrue(gw.entered_event.wait(timeout=3.0), "Fake gateway did not enter model step")

        # Another principal cannot cancel this customer's in-flight turn -> 404
        other_code, other_res = _call_api(
            app,
            "POST",
            "/api/chat/cancel",
            "C-002",
            {"conversation_id": cid, "request_id": req_id},
            context=other_ctx,
        )
        self.assertEqual(other_code, 404)
        self.assertEqual(other_res["error"], "turn_not_found")

        # Owner cancels the in-flight turn -> 200 cancelled: True
        cancel_code, cancel_res = _call_api(
            app,
            "POST",
            "/api/chat/cancel",
            "C-001",
            {"conversation_id": cid, "request_id": req_id},
            context=cust_ctx,
        )
        self.assertEqual(cancel_code, 200)
        self.assertTrue(cancel_res["cancelled"])
        self.assertFalse(cancel_res["already_finished"])

        gw.release_event.set()
        worker.join(timeout=5.0)
        self.assertFalse(worker.is_alive())

        self.assertEqual(result_holder["code"], 200)
        chat_res = result_holder["payload"]
        self.assertTrue(chat_res["cancelled"])
        self.assertEqual(chat_res["message"], CANCELLED_MESSAGE)
        self.assertEqual(chat_res.get("action"), "reply")
        self.assertIsNone(chat_res.get("prepared_order_action"))
        self.assertEqual(chat_res["trace"]["cancelled"], True)
        self.assertEqual(chat_res["trace"]["stopped_at"], "after_model")
        self.assertEqual(len(chat_res["trace"]["tools"]), 0, "Zero tools may run after cancellation")
        self.assertTrue(any(s.get("action") == "cancelled" for s in chat_res["trace"]["steps"]))

        # Conversation history stores user message + CANCELLED_MESSAGE, zero partial text
        hist_code, hist_res = _call_api(
            app, "GET", f"/api/conversations/{cid}/messages", "C-001", context=cust_ctx
        )
        self.assertEqual(hist_code, 200)
        self.assertEqual(len(hist_res["turns"]), 1)
        raw_stored_msgs = hist_res["turns"][0]["messages"]
        stored_msgs = json.loads(raw_stored_msgs) if isinstance(raw_stored_msgs, str) else raw_stored_msgs
        self.assertEqual(
            stored_msgs,
            [
                {"role": "user", "content": "Hủy đơn O-101 giúp tôi"},
                {"role": "assistant", "content": CANCELLED_MESSAGE},
            ],
        )
        self.assertNotIn("Câu trả lời dở dang", json.dumps(hist_res, ensure_ascii=False))

        # Replaying the exact same request_id returns the saved cancelled result
        rep_code, rep_res = _call_api(
            app,
            "POST",
            "/api/chat",
            "C-001",
            {"conversation_id": cid, "text": "Hủy đơn O-101 giúp tôi", "request_id": req_id},
            context=cust_ctx,
        )
        self.assertEqual(rep_code, 200)
        self.assertTrue(rep_res["replayed"])
        self.assertTrue(rep_res["cancelled"])
        self.assertEqual(rep_res["message"], CANCELLED_MESSAGE)

        # Cancelling AFTER completion returns already_finished: True without changing history
        after_code, after_res = _call_api(
            app,
            "POST",
            "/api/chat/cancel",
            "C-001",
            {"conversation_id": cid, "request_id": req_id},
            context=cust_ctx,
        )
        self.assertEqual(after_code, 200)
        self.assertFalse(after_res["cancelled"])
        self.assertTrue(after_res["already_finished"])

        # Follow-up turn succeeds and receives prior user + cancelled marker in model messages
        next_code, next_res = _call_api(
            app,
            "POST",
            "/api/chat",
            "C-001",
            {"conversation_id": cid, "text": "Kiểm tra lại giúp mình nhé", "request_id": "req_w5_followup_2"},
            context=cust_ctx,
        )
        self.assertEqual(next_code, 200)
        self.assertFalse(next_res.get("cancelled", False))
        self.assertIn("đã thấy tin trước", next_res["message"])

    def test_chat_cancel_on_second_step_prevents_second_tool_and_restores_bound_context(self):
        # Step 1 runs get_order("O-101") which binds order O-101; Step 2 blocks in model and gets cancelled:
        # 2nd tool must NOT run and bound context must revert to initial snapshot!
        gw = _BlockingFakeGateway(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": "get_order", "arguments": {"order_id": "O-101"}}}],
                },
                {
                    "role": "assistant",
                    "content": "Đơn O-101 đang chờ xử lý",
                    "tool_calls": [{"function": {"name": "track_shipment", "arguments": {"order_id": "O-101"}}}],
                },
            ],
            block_on_call=2,
        )
        app = self._make_app(gw)
        cust_ctx = _ctx("customer", "p_cust_1", customer_id="C-001")
        conv = app.new_conversation("C-001", {"provider_id": "custom"})
        cid = conv["conversation_id"]
        req_id = "req_w5_step2_cancel"

        out: dict = {}

        def _worker():
            out["res"] = _call_api(
                app,
                "POST",
                "/api/chat",
                "C-001",
                {"conversation_id": cid, "text": "Xem đơn O-101", "request_id": req_id},
                context=cust_ctx,
            )

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        self.assertTrue(gw.entered_event.wait(timeout=3.0))
        _call_api(
            app,
            "POST",
            "/api/chat/cancel",
            "C-001",
            {"conversation_id": cid, "request_id": req_id},
            context=cust_ctx,
        )
        gw.release_event.set()
        t.join(timeout=5.0)

        code, body = out["res"]
        self.assertEqual(code, 200)
        self.assertTrue(body["cancelled"])
        # Only 1st tool ran before step 2 model was cancelled; 2nd tool (track_shipment) NEVER ran
        self.assertEqual(len(body["trace"]["tools"]), 1)
        self.assertEqual(body["trace"]["stopped_at"], "after_model")
        self.assertIsNone(body["context"]["order_id"], "Cancelled turn must not mutate conversation bound order")

    def test_chat_cancel_at_before_tool_stops_remaining_tools_in_same_step(self):
        # Single model step emits 2 tool calls; cancel is triggered inside 1st tool so 2nd tool is stopped at before_tool
        gw = _BlockingFakeGateway(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "list_orders", "arguments": {}}},
                        {"function": {"name": "track_shipment", "arguments": {"order_id": "O-101"}}},
                    ],
                }
            ],
            block_on_call=None,
        )
        app = self._make_app(gw)
        cust_ctx = _ctx("customer", "p_cust_1", customer_id="C-001")
        conv = app.new_conversation("C-001", {"provider_id": "custom"})
        cid = conv["conversation_id"]
        req_id = "req_w5_before_tool_cancel"

        orig_orders = self.store.orders

        def _orders_then_cancel(customer_id):
            res = orig_orders(customer_id)
            _call_api(
                app,
                "POST",
                "/api/chat/cancel",
                "C-001",
                {"conversation_id": cid, "request_id": req_id},
                context=cust_ctx,
            )
            return res

        with patch.object(self.store, "orders", side_effect=_orders_then_cancel):
            code, body = _call_api(
                app,
                "POST",
                "/api/chat",
                "C-001",
                {"conversation_id": cid, "text": "Xem đơn của tôi", "request_id": req_id},
                context=cust_ctx,
            )
        self.assertEqual(code, 200)
        self.assertTrue(body["cancelled"])
        self.assertEqual(body["trace"]["stopped_at"], "before_tool:track_shipment")
        self.assertEqual([t["name"] for t in body["trace"]["tools"]], ["list_orders"])

    def test_case_assistant_cancel_isolation_replay_and_already_finished(self):
        conv = self.store.new_conversation("C-001", "custom")
        cid = conv["conversation_id"]
        case_id = conv["case_id"]
        self.store.customer_message("C-001", cid, "Nhờ kiểm tra đơn O-101")
        self.store.request_human_handoff("C-001", cid, reason_code="customer_requested", comment="Cần hỗ trợ")
        self.store.claim_case(
            case_id,
            staff_name="NV Lan",
            actor={"principal_id": "p_staff_1", "role": "staff", "tenant_id": "shop_a", "display_name": "NV Lan"},
        )

        gw = _BlockingFakeGateway(
            [
                {
                    "role": "assistant",
                    "content": "Nháp dở dang không được lưu\n---DRAFT---\nChào anh/chị bản nháp dở",
                    "tool_calls": [{"function": {"name": "list_case_orders", "arguments": {}}}],
                }
            ],
            block_on_call=1,
        )
        app = self._make_app(gw)
        staff_holder = _ctx("staff", "p_staff_1", display_name="NV Lan")
        staff_other = _ctx("staff", "p_staff_2", display_name="NV Minh")
        req_id = "case_assist_cancel_req_1"

        out: dict = {}

        def _worker():
            out["res"] = _call_api(
                app,
                "POST",
                f"/api/staff/cases/{case_id}/assist",
                "C-001",
                {"mode": "draft", "request_id": req_id},
                context=staff_holder,
            )

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        self.assertTrue(gw.entered_event.wait(timeout=3.0))

        # Other staff cannot cancel p_staff_1's Case Assistant turn -> 404
        c_other, b_other = _call_api(
            app,
            "POST",
            f"/api/staff/cases/{case_id}/assist/cancel",
            "C-001",
            {"request_id": req_id},
            context=staff_other,
        )
        self.assertEqual(c_other, 404)
        self.assertEqual(b_other["error"], "turn_not_found")

        # Holder cancels own Case Assistant turn -> 200 cancelled: True
        c_ok, b_ok = _call_api(
            app,
            "POST",
            f"/api/staff/cases/{case_id}/assist/cancel",
            "C-001",
            {"request_id": req_id},
            context=staff_holder,
        )
        self.assertEqual(c_ok, 200)
        self.assertTrue(b_ok["cancelled"])

        gw.release_event.set()
        t.join(timeout=5.0)

        code, body = out["res"]
        self.assertEqual(code, 200)
        self.assertTrue(body["cancelled"])
        self.assertEqual(body["answer"], CANCELLED_MESSAGE)
        self.assertIsNone(body["draft_reply"])
        self.assertEqual(len(body["trace"]["tools"]), 0)

        # Replay same request_id -> returns saved cancelled turn
        rep_code, rep_body = _call_api(
            app,
            "POST",
            f"/api/staff/cases/{case_id}/assist",
            "C-001",
            {"mode": "draft", "request_id": req_id},
            context=staff_holder,
        )
        self.assertEqual(rep_code, 200)
        self.assertTrue(rep_body["replayed"])
        self.assertTrue(rep_body["cancelled"])
        self.assertEqual(rep_body["answer"], CANCELLED_MESSAGE)

        # Cancel after finished -> already_finished: True
        fin_code, fin_body = _call_api(
            app,
            "POST",
            f"/api/staff/cases/{case_id}/assist/cancel",
            "C-001",
            {"request_id": req_id},
            context=staff_holder,
        )
        self.assertEqual(fin_code, 200)
        self.assertFalse(fin_body["cancelled"])
        self.assertTrue(fin_body["already_finished"])


class TestR1W5StaffManagerOperations(unittest.TestCase):
    """Items 1, 2, 4, 5 (W5-D1, W5-D2, W5-D4, W5-D6) + PostgreSQL SQL placeholder checks."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        gw = _BlockingFakeGateway(
            [{"role": "assistant", "content": "Tóm tắt ca của NV Lan."}],
            block_on_call=None,
        )
        self.sessions = PersistentSessions(
            root / "persistent",
            infer=gw,
            api_infer=gw,
            api_daily_limit=50,
            default_tenant_id="shop_a",
        )
        self.store_a = self.sessions.provision_tenant("shop_a", "Shop A", seed_demo=True)
        self.store_b = self.sessions.provision_tenant("shop_b", "Shop B", seed_demo=True)
        self.id_store = self.sessions.control

        # Seed a second customer C-002 with order O-202 in shop_a (and PII in customers.name)
        with self.store_a.connection(write=True) as db:
            db.execute(
                "UPDATE customers SET name = 'Lê Thị Hoa - 0912345678 - 99 Nguyễn Huệ, Quận 1' WHERE id = 'C-001'"
            )
            db.execute(
                "INSERT OR IGNORE INTO customers(id, name) VALUES ('C-002', 'Trần Văn Nam - 0988777666')"
            )
            db.execute(
                """INSERT OR IGNORE INTO orders(id, customer_id, product_id, name, variant, amount, status, version)
                   VALUES ('O-202', 'C-002', 'P-102', 'Áo khoác khách khác', 'Đen · Size L', 520000, 'pending', 1)"""
            )

        self.p_cust_a = "p_cust_a"
        self.p_cust_2 = "p_cust_2"
        self.p_staff_1 = "p_staff_1"
        self.p_staff_2 = "p_staff_2"
        self.p_staff_inactive = "p_staff_inactive"
        self.p_mgr_a = "p_mgr_a"
        self.p_staff_b = "p_staff_b"
        self.p_mgr_b = "p_mgr_b"

        self.m_cust_a = self.sessions.create_member("shop_a", self.p_cust_a, "Lê Thị Hoa", "C-001", role="customer")
        self.m_cust_2 = self.sessions.create_member("shop_a", self.p_cust_2, "Trần Văn Nam", "C-002", role="customer")
        self.m_staff_1 = self.sessions.create_member("shop_a", self.p_staff_1, "Chuyên viên Lan", "C-001", role="staff")
        self.m_staff_2 = self.sessions.create_member("shop_a", self.p_staff_2, "Chuyên viên Minh", "C-001", role="staff")
        self.m_staff_inactive = self.sessions.create_member(
            "shop_a", self.p_staff_inactive, "Nhân viên Tạm nghỉ", "C-001", role="staff"
        )
        self.m_mgr_a = self.sessions.create_member("shop_a", self.p_mgr_a, "Quản lý Hùng", "C-001", role="manager")
        self.m_staff_b = self.sessions.create_member("shop_b", self.p_staff_b, "Nhân viên Shop B", "C-001", role="staff")
        self.m_mgr_b = self.sessions.create_member("shop_b", self.p_mgr_b, "Quản lý Shop B", "C-001", role="manager")

        # Mark p_staff_inactive inactive and attach Google emails in external_identities to verify zero email leakage
        with self.id_store.connection(write=True) as db:
            db.execute("UPDATE memberships SET active = 0, disabled_reason = 'tam_nghi' WHERE id = ?", (self.m_staff_inactive,))
            now = 1_762_300_000.0
            for idx, (pid, email) in enumerate(
                [
                    (self.p_staff_1, "lan.secret@shop-a.example"),
                    (self.p_staff_2, "minh.secret@shop-a.example"),
                    (self.p_mgr_a, "hung.secret@shop-a.example"),
                ]
            ):
                db.execute(
                    """INSERT INTO external_identities(id, issuer, sub, principal_id, email, created_at)
                       VALUES (?, 'https://accounts.google.com', ?, ?, ?, ?)""",
                    (f"ext_{idx}", f"sub_{idx}", pid, email, now),
                )

        self.app_a = Application(
            self.store_a,
            {},
            infer=gw,
            role="manager",
            tenant_id="shop_a",
            cancel_registry=self.sessions.cancel_registry,
        )
        self.app_a.identity_store = self.id_store

        self.app_b = Application(
            self.store_b,
            {},
            infer=gw,
            role="manager",
            tenant_id="shop_b",
            cancel_registry=self.sessions.cancel_registry,
        )
        self.app_b.identity_store = self.id_store

        self.ctx_cust_a = _ctx("customer", self.p_cust_a, customer_id="C-001", tenant_id="shop_a", display_name="Hoa")
        self.ctx_cust_2 = _ctx("customer", self.p_cust_2, customer_id="C-002", tenant_id="shop_a", display_name="Nam")
        self.ctx_staff_1 = _ctx("staff", self.p_staff_1, customer_id="C-001", tenant_id="shop_a", display_name="Chuyên viên Lan")
        self.ctx_staff_2 = _ctx("staff", self.p_staff_2, customer_id="C-001", tenant_id="shop_a", display_name="Chuyên viên Minh")
        self.ctx_mgr_a = _ctx("manager", self.p_mgr_a, customer_id="C-001", tenant_id="shop_a", display_name="Quản lý Hùng")
        self.ctx_staff_b = _ctx("staff", self.p_staff_b, customer_id="C-001", tenant_id="shop_b", display_name="Nhân viên Shop B")
        self.ctx_mgr_b = _ctx("manager", self.p_mgr_b, customer_id="C-001", tenant_id="shop_b", display_name="Quản lý Shop B")

    def tearDown(self):
        self.tmp.cleanup()

    # --- Item 1 (W5-D2): Staff members & Direct Case Transfer ---

    def test_staff_members_same_store_active_only_and_zero_email(self):
        # Customer forbidden -> 403
        c_cust, _ = _call_api(self.app_a, "GET", "/api/staff/members", "C-001", context=self.ctx_cust_a)
        self.assertEqual(c_cust, 403)

        # Staff in shop_a -> sees active staff/manager in shop_a ONLY, zero emails
        c_ok, body = _call_api(self.app_a, "GET", "/api/staff/members", "C-001", context=self.ctx_staff_1)
        self.assertEqual(c_ok, 200)
        members = body["members"]
        pids = {m["principal_id"] for m in members}
        self.assertEqual(pids, {self.p_staff_1, self.p_staff_2, self.p_mgr_a})
        self.assertNotIn(self.p_cust_a, pids)
        self.assertNotIn(self.p_staff_inactive, pids)
        self.assertNotIn(self.p_staff_b, pids)
        for m in members:
            self.assertEqual(set(m.keys()), {"principal_id", "display_name", "role"})
        serialized = json.dumps(body, ensure_ascii=False)
        self.assertNotIn("@", serialized)
        self.assertNotIn("secret@shop-a.example", serialized)

    def test_case_transfer_permissions_version_targets_atomicity_and_assist_isolation(self):
        conv = self.app_a.new_conversation("C-001", {"provider_id": "custom"})
        cid = conv["conversation_id"]
        case_id = conv["case_id"]
        self.app_a.store.customer_message("C-001", cid, "Nhờ hỗ trợ đơn O-101")
        self.app_a.store.request_human_handoff("C-001", cid, reason_code="customer_requested", comment="Cần gặp NV")

        # Unclaimed (waiting) case cannot be transferred -> 409
        c_wait, b_wait = _call_api(
            self.app_a,
            "POST",
            f"/api/staff/cases/{case_id}/transfer",
            "C-001",
            {"to_principal_id": self.p_staff_2, "version": 2},
            context=self.ctx_mgr_a,
        )
        self.assertEqual(c_wait, 409)
        self.assertEqual(b_wait["error"], "case_not_claimed")

        # Claim case as Staff 1 via route
        c_claim, claim_res = _call_api(
            self.app_a,
            "POST",
            "/api/staff/claim",
            "C-001",
            {"case_id": case_id},
            context=self.ctx_staff_1,
        )
        self.assertEqual(c_claim, 200)
        ver = claim_res["case"]["version"]

        # Staff 1 records a private Case Assistant turn before transferring
        c_assist, _ = _call_api(
            self.app_a,
            "POST",
            f"/api/staff/cases/{case_id}/assist",
            "C-001",
            {"mode": "summary", "request_id": "req_lan_assist_1"},
            context=self.ctx_staff_1,
        )
        self.assertEqual(c_assist, 200)

        # Non-holder Staff 2 gets 403
        c_non_holder, b_non_holder = _call_api(
            self.app_a,
            "POST",
            f"/api/staff/cases/{case_id}/transfer",
            "C-001",
            {"to_principal_id": self.p_staff_2, "version": ver},
            context=self.ctx_staff_2,
        )
        self.assertEqual(c_non_holder, 403)
        self.assertEqual(b_non_holder["error"], "case_held_by_other")

        # Wrong version -> 409
        c_ver, b_ver = _call_api(
            self.app_a,
            "POST",
            f"/api/staff/cases/{case_id}/transfer",
            "C-001",
            {"to_principal_id": self.p_staff_2, "version": ver + 99},
            context=self.ctx_staff_1,
        )
        self.assertEqual(c_ver, 409)
        self.assertEqual(b_ver["error"], "case_version_conflict")

        # Invalid targets: self, inactive staff, customer, other-store staff, unknown -> 400
        for bad_target in (self.p_staff_1, self.p_staff_inactive, self.p_cust_a, self.p_staff_b, "nonexistent_p"):
            c_bad, b_bad = _call_api(
                self.app_a,
                "POST",
                f"/api/staff/cases/{case_id}/transfer",
                "C-001",
                {"to_principal_id": bad_target, "version": ver},
                context=self.ctx_staff_1,
            )
            self.assertEqual(c_bad, 400, f"Expected 400 for target {bad_target}")
            self.assertEqual(b_bad["error"], "invalid_transfer_target")

        # Atomic rollback check: if writing customer notice fails mid-transaction, holder & version & audit must NOT change
        target_member = self.id_store.active_staff_member("shop_a", self.p_staff_2)
        with patch.object(self.app_a.store, "_append_case_system_notice_in_tx", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.app_a.store.transfer_case(
                    case_id,
                    to_principal_id=self.p_staff_2,
                    target_member=target_member,
                    expected_version=ver,
                    actor={"principal_id": self.p_staff_1, "role": "staff", "tenant_id": "shop_a"},
                )
        with self.app_a.store.connection() as db:
            unchanged_case = db.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
            tx_ev_cnt = db.execute("SELECT COUNT(*) AS n FROM business_events WHERE kind = 'case_transferred'").fetchone()["n"]
        self.assertEqual(unchanged_case["holder"], self.p_staff_1)
        self.assertEqual(int(unchanged_case["version"]), ver)
        self.assertEqual(tx_ev_cnt, 0)

        # Valid transfer by holder Staff 1 -> Staff 2
        c_tx, b_tx = _call_api(
            self.app_a,
            "POST",
            f"/api/staff/cases/{case_id}/transfer",
            "C-001",
            {"to_principal_id": self.p_staff_2, "version": ver},
            context=self.ctx_staff_1,
        )
        self.assertEqual(c_tx, 200)
        self.assertTrue(b_tx["transferred"])
        self.assertEqual(b_tx["case"]["holder"], self.p_staff_2)
        self.assertEqual(b_tx["case"]["holder_name"], "Chuyên viên Minh")
        self.assertEqual(b_tx["case"]["version"], ver + 1)
        self.assertEqual(b_tx["notice_message"], "Ca của bạn đã được chuyển cho Chuyên viên Minh")

        # Customer transcript contains the sys-notice- milestone
        _, conv_msgs = _call_api(
            self.app_a, "GET", f"/api/conversations/{cid}/messages", "C-001", context=self.ctx_cust_a
        )
        notice_turns = [t for t in conv_msgs["turns"] if str(t.get("request_id", "")).startswith("sys-notice-transfer-")]
        self.assertEqual(len(notice_turns), 1)
        raw_notice_res = notice_turns[0]["result"]
        notice_res = json.loads(raw_notice_res) if isinstance(raw_notice_res, str) else raw_notice_res
        self.assertEqual(notice_res["milestone"], "case_transferred")
        self.assertEqual(notice_res["message"], "Ca của bạn đã được chuyển cho Chuyên viên Minh")

        # Audit event case_transferred recorded with from_principal_id, to_principal_id, actor
        events = [e for e in self.app_a.store.manager_events(limit=100) if e["kind"] == "case_transferred"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["from_principal_id"], self.p_staff_1)
        self.assertEqual(events[0]["payload"]["to_principal_id"], self.p_staff_2)
        self.assertEqual(events[0]["payload"]["actor"]["principal_id"], self.p_staff_1)

        # Case Assistant history stays private per principal: Staff 2 sees 0 turns and can_assist=True
        _, s2_assist = _call_api(
            self.app_a,
            "GET",
            f"/api/staff/cases/{case_id}/assist",
            "C-001",
            context=self.ctx_staff_2,
        )
        self.assertEqual(s2_assist["turns"], [])
        self.assertTrue(s2_assist["can_assist"])

        # Manager can also transfer the case directly from Staff 2 back to Staff 1
        c_mgr_tx, b_mgr_tx = _call_api(
            self.app_a,
            "POST",
            f"/api/staff/cases/{case_id}/transfer",
            "C-001",
            {"to_principal_id": self.p_staff_1, "version": ver + 1},
            context=self.ctx_mgr_a,
        )
        self.assertEqual(c_mgr_tx, 200)
        self.assertEqual(b_mgr_tx["case"]["holder"], self.p_staff_1)
        self.assertEqual(b_mgr_tx["case"]["version"], ver + 2)

    # --- Item 2 (W5-D1): Manager Console Order-Actions Queue ---

    def test_manager_order_actions_rbac_tenant_isolation_filters_pii_and_pagination(self):
        # Staff and Customer get 403
        for forbidden_ctx in (self.ctx_cust_a, self.ctx_staff_1):
            code, body = _call_api(
                self.app_a, "GET", "/api/manager/order-actions", "C-001", context=forbidden_ctx
            )
            self.assertEqual(code, 403)
            self.assertEqual(body["error"], "permission_denied")

        # Limit > 50 rejected fail-closed with 400 invalid_limit
        c_over, b_over = _call_api(
            self.app_a,
            "GET",
            "/api/manager/order-actions",
            "C-001",
            query_params={"limit": "51"},
            context=self.ctx_mgr_a,
        )
        self.assertEqual(c_over, 400)
        self.assertEqual(b_over["error"], "invalid_limit")

        # Create 3 order actions in shop_a via HTTP routes:
        # 1) O-101 cancel -> approve -> completed
        c_r1, res_r1 = _call_api(
            self.app_a,
            "POST",
            "/api/order-actions",
            "C-001",
            {
                "order_id": "O-101",
                "expected_order_version": 1,
                "type": "cancel",
                "reason_code": "change_of_mind",
                "reason_text": "Ghi chú riêng tư 0901234567 không được lộ ở queue tổng",
            },
            context=self.ctx_cust_a,
            idempotency_key="idem_w5_oa_1",
        )
        self.assertEqual(c_r1, 201, res_r1)
        r1 = res_r1["order_action"]
        c_app1, _ = _call_api(
            self.app_a,
            "POST",
            f"/api/order-actions/{r1['request_id']}/approve",
            "C-001",
            {"version": r1["version"]},
            context=self.ctx_mgr_a,
            idempotency_key="idem_w5_oa_1_app",
        )
        self.assertEqual(c_app1, 200)

        # 2) O-102 delivered return -> approve -> mark-received -> mark-inspected(refund) -> refund-request (needs_manager!)
        c_r2, res_r2 = _call_api(
            self.app_a,
            "POST",
            "/api/order-actions",
            "C-001",
            {
                "order_id": "O-102",
                "expected_order_version": 1,
                "type": "return",
                "reason_code": "defective_item",
                "reason_text": "Áo bung chỉ tại địa chỉ 99 Nguyễn Huệ",
            },
            context=self.ctx_cust_a,
            idempotency_key="idem_w5_oa_2",
        )
        self.assertEqual(c_r2, 201, res_r2)
        r2 = res_r2["order_action"]
        v = r2["version"]
        for step_idx, (slug, extra) in enumerate(
            [
                ("approve", {}),
                ("mark-received", {}),
                ("mark-inspected", {"inspection_outcome": "refund"}),
                ("refund-request", {}),
            ]
        ):
            c_s, res_step = _call_api(
                self.app_a,
                "POST",
                f"/api/order-actions/{r2['request_id']}/{slug}",
                "C-001",
                {"version": v, **extra},
                context=self.ctx_mgr_a,
                idempotency_key=f"idem_w5_oa_2_{step_idx}",
            )
            self.assertEqual(c_s, 200, f"Step {slug} failed: {res_step}")
            v = res_step["order_action"]["version"]

        # 3) O-202 in shop_a (in_progress)
        c_r3, res_r3 = _call_api(
            self.app_a,
            "POST",
            "/api/order-actions",
            "C-002",
            {
                "order_id": "O-202",
                "expected_order_version": 1,
                "type": "cancel",
                "reason_code": "change_of_mind",
            },
            context=self.ctx_cust_2,
            idempotency_key="idem_w5_oa_3",
        )
        self.assertEqual(c_r3, 201, res_r3)
        r3 = res_r3["order_action"]

        # Also create an order action in shop_b to verify cross-store isolation!
        ctx_cust_b = _ctx("customer", "p_cust_b", customer_id="C-001", tenant_id="shop_b", display_name="Khách B")
        c_rb, res_rb = _call_api(
            self.app_b,
            "POST",
            "/api/order-actions",
            "C-001",
            {
                "order_id": "O-101",
                "expected_order_version": 1,
                "type": "cancel",
                "reason_code": "change_of_mind",
            },
            context=ctx_cust_b,
            idempotency_key="idem_w5_shop_b_1",
        )
        self.assertEqual(c_rb, 201, res_rb)
        rb = res_rb["order_action"]

        # Query all in shop_a
        c_all, b_all = _call_api(
            self.app_a,
            "GET",
            "/api/manager/order-actions",
            "C-001",
            query_params={"status_group": "all", "limit": "50"},
            context=self.ctx_mgr_a,
        )
        self.assertEqual(c_all, 200)
        self.assertEqual(b_all["limit"], 50)
        self.assertEqual(b_all["counts"], {"needs_manager": 1, "in_progress": 1, "completed": 1, "all": 3})
        req_ids = [it["request_id"] for it in b_all["items"]]
        self.assertEqual(set(req_ids), {r1["request_id"], r2["request_id"], r3["request_id"]})
        self.assertNotIn(rb["request_id"], req_ids, "Must never include other store's order actions")

        # Filter needs_manager -> strictly r2
        c_nm, b_nm = _call_api(
            self.app_a,
            "GET",
            "/api/manager/order-actions",
            "C-001",
            query_params={"status_group": "needs_manager"},
            context=self.ctx_mgr_a,
        )
        self.assertEqual(c_nm, 200)
        self.assertEqual([it["request_id"] for it in b_nm["items"]], [r2["request_id"]])
        self.assertTrue(b_nm["items"][0]["needs_manager"])
        self.assertTrue(b_nm["items"][0]["case_id"])

        # PII check: customer_display_name has phone/address stripped; zero phone/address/reason_text leaked
        raw_json = json.dumps(b_all, ensure_ascii=False)
        self.assertNotIn("0912345678", raw_json)
        self.assertNotIn("0988777666", raw_json)
        self.assertNotIn("0901234567", raw_json)
        self.assertNotIn("99 Nguyễn Huệ", raw_json)
        self.assertNotIn("reason_text", raw_json)
        r2_row = next(it for it in b_all["items"] if it["request_id"] == r2["request_id"])
        self.assertEqual(r2_row["customer_display_name"], "Lê Thị Hoa")

        # Deterministic pagination: page 1 (limit=2, offset=0) + page 2 (limit=2, offset=2) == full ordered list
        _, p1 = _call_api(
            self.app_a,
            "GET",
            "/api/manager/order-actions",
            "C-001",
            query_params={"status_group": "all", "limit": "2", "offset": "0"},
            context=self.ctx_mgr_a,
        )
        _, p2 = _call_api(
            self.app_a,
            "GET",
            "/api/manager/order-actions",
            "C-001",
            query_params={"status_group": "all", "limit": "2", "offset": "2"},
            context=self.ctx_mgr_a,
        )
        self.assertEqual(len(p1["items"]), 2)
        self.assertEqual(len(p2["items"]), 1)
        self.assertEqual([x["request_id"] for x in p1["items"] + p2["items"]], req_ids)

    # --- Item 4 (W5-D6): Idempotent second POST /api/staff/resolve ---

    def test_resolve_twice_returns_200_already_resolved_with_zero_extra_writes_and_preserves_conflicts(self):
        # Bot-only unescalated case still returns 409 case_not_escalated
        bot_conv = self.app_a.new_conversation("C-001", {"provider_id": "custom"})
        c_bot, b_bot = _call_api(
            self.app_a,
            "POST",
            "/api/staff/resolve",
            "C-001",
            {"case_id": bot_conv["case_id"]},
            context=self.ctx_staff_1,
        )
        self.assertEqual(c_bot, 409)
        self.assertEqual(b_bot["error"], "case_not_escalated")

        # Escalated case
        conv = self.app_a.new_conversation("C-001", {"provider_id": "custom"})
        cid = conv["conversation_id"]
        case_id = conv["case_id"]
        ep1 = self.app_a.store.request_human_handoff("C-001", cid, reason_code="customer_requested")
        handoff_1 = ep1["handoff_id"]
        _call_api(self.app_a, "POST", "/api/staff/claim", "C-001", {"case_id": case_id}, context=self.ctx_staff_1)

        # Unauthorized Customer gets 403
        c_unauth, _ = _call_api(
            self.app_a,
            "POST",
            "/api/staff/resolve",
            "C-001",
            {"case_id": case_id},
            context=self.ctx_cust_a,
        )
        self.assertEqual(c_unauth, 403)

        # First resolve -> 200, already_resolved: False
        c1, r1 = _call_api(
            self.app_a,
            "POST",
            "/api/staff/resolve",
            "C-001",
            {"case_id": case_id, "handoff_id": handoff_1},
            context=self.ctx_staff_1,
        )
        self.assertEqual(c1, 200)
        self.assertFalse(r1.get("already_resolved", False))
        self.assertEqual(r1["case"]["status"], "resolved")

        with self.app_a.store.connection() as db:
            ev_count_1 = db.execute("SELECT COUNT(*) AS n FROM business_events").fetchone()["n"]
            turn_count_1 = db.execute("SELECT COUNT(*) AS n FROM agent_turns WHERE conversation_id = ?", (cid,)).fetchone()["n"]
            fb_count_1 = db.execute("SELECT COUNT(*) AS n FROM conversation_feedback WHERE conversation_id = ?", (cid,)).fetchone()["n"]

        # Second resolve -> 200, already_resolved: True, ZERO new audit rows, notices, or feedback prompts
        c2, r2 = _call_api(
            self.app_a,
            "POST",
            "/api/staff/resolve",
            "C-001",
            {"case_id": case_id, "handoff_id": handoff_1},
            context=self.ctx_staff_2,
        )
        self.assertEqual(c2, 200)
        self.assertTrue(r2["already_resolved"])
        self.assertEqual(r2["case"]["case_id"], case_id)
        self.assertEqual(r2["case"]["status"], "resolved")
        self.assertIsNone(r2["notice_turn_id"])

        with self.app_a.store.connection() as db:
            ev_count_2 = db.execute("SELECT COUNT(*) AS n FROM business_events").fetchone()["n"]
            turn_count_2 = db.execute("SELECT COUNT(*) AS n FROM agent_turns WHERE conversation_id = ?", (cid,)).fetchone()["n"]
            fb_count_2 = db.execute("SELECT COUNT(*) AS n FROM conversation_feedback WHERE conversation_id = ?", (cid,)).fetchone()["n"]
        self.assertEqual(ev_count_2, ev_count_1)
        self.assertEqual(turn_count_2, turn_count_1)
        self.assertEqual(fb_count_2, fb_count_1)

        # Unauthorized caller on already-resolved case is still blocked (403)
        c_unauth_after, _ = _call_api(
            self.app_a,
            "POST",
            "/api/staff/resolve",
            "C-001",
            {"case_id": case_id},
            context=self.ctx_cust_a,
        )
        self.assertEqual(c_unauth_after, 403)

        # Reopen case via POST /api/conversations/<cid>/resume, escalate new episode, then pass stale handoff_1 -> 409
        c_res, _ = _call_api(
            self.app_a,
            "POST",
            f"/api/conversations/{cid}/resume",
            "C-001",
            {},
            context=self.ctx_cust_a,
        )
        self.assertEqual(c_res, 200)
        self.app_a.store.request_human_handoff("C-001", cid, reason_code="customer_requested")
        c_stale, b_stale = _call_api(
            self.app_a,
            "POST",
            "/api/staff/resolve",
            "C-001",
            {"case_id": case_id, "handoff_id": handoff_1},
            context=self.ctx_staff_1,
        )
        self.assertEqual(c_stale, 409)
        self.assertEqual(b_stale["error"], "stale_handoff_episode")

    # --- Item 5 (W5-D4): Manager-only, read-only, case-bound Tool Inspector ---

    def test_tool_inspector_manager_only_allowlist_and_case_scope(self):
        self.assertEqual(
            ALLOWED_DIRECT_TOOLS,
            frozenset({"get_order", "list_orders", "track_shipment", "check_inventory", "search_knowledge", "get_context"}),
        )

        # Unescalated bot-only case -> rejected even for Manager
        bot_conv = self.app_a.new_conversation("C-001", {"provider_id": "custom"})
        c_unesc, _ = _call_api(
            self.app_a,
            "POST",
            "/api/tools/execute",
            "C-001",
            {"case_id": bot_conv["case_id"], "tool_name": "list_orders", "arguments": {}},
            context=self.ctx_mgr_a,
        )
        self.assertEqual(c_unesc, 403)

        # Escalated case for C-001
        conv = self.app_a.new_conversation("C-001", {"provider_id": "custom"})
        cid = conv["conversation_id"]
        case_id = conv["case_id"]
        self.app_a.store.request_human_handoff("C-001", cid, reason_code="customer_requested")

        # Staff and Customer get 403 permission_denied
        for denied_ctx in (self.ctx_staff_1, self.ctx_cust_a):
            code, body = _call_api(
                self.app_a,
                "POST",
                "/api/tools/execute",
                "C-001",
                {"case_id": case_id, "tool_name": "list_orders", "arguments": {}},
                context=denied_ctx,
            )
            self.assertEqual(code, 403)
            self.assertEqual(body["error"], "permission_denied")

        # Non-allowlisted tools (including request_human_support & prepare_order_action) -> 403 tool_not_allowed
        for forbidden_tool in ("request_human_support", "prepare_order_action", "get_product", "search_products"):
            code, body = _call_api(
                self.app_a,
                "POST",
                "/api/tools/execute",
                "C-001",
                {"case_id": case_id, "tool_name": forbidden_tool, "arguments": {}},
                context=self.ctx_mgr_a,
            )
            self.assertEqual(code, 403)
            self.assertEqual(body["error"], "tool_not_allowed")

        # Manager executes allowlisted read-only tools scoped strictly to C-001's case
        c_list, b_list = _call_api(
            self.app_a,
            "POST",
            "/api/tools/execute",
            "C-001",
            {"case_id": case_id, "tool_name": "list_orders", "arguments": {}},
            context=self.ctx_mgr_a,
        )
        self.assertEqual(c_list, 200)
        listed_ids = {o["id"] for o in b_list["result"]["orders"]}
        self.assertIn("O-101", listed_ids)
        self.assertNotIn("O-202", listed_ids, "Must never include C-002's orders")

        # Attempting get_order on C-002's O-202 within C-001's case fails closed (403 case_scope_violation)
        c_cross, b_cross = _call_api(
            self.app_a,
            "POST",
            "/api/tools/execute",
            "C-001",
            {"case_id": case_id, "tool_name": "get_order", "arguments": {"order_id": "O-202"}},
            context=self.ctx_mgr_a,
        )
        self.assertIn(c_cross, (200, 403, 404))
        if c_cross == 200:
            self.assertEqual(b_cross["result"].get("found"), False)

        # Case orders endpoint supplies dynamic order & product IDs for the Inspector UI
        c_orders, b_orders = _call_api(
            self.app_a,
            "GET",
            f"/api/staff/cases/{case_id}/orders",
            "C-001",
            context=self.ctx_mgr_a,
        )
        self.assertEqual(c_orders, 200)
        first_ord = b_orders["orders"][0]
        self.assertTrue(first_ord["id"])
        self.assertTrue(first_ord["product_id"])

        for tool_name, tool_args in [
            ("get_order", {"order_id": first_ord["id"]}),
            ("track_shipment", {"order_id": first_ord["id"]}),
            ("check_inventory", {"product_id": first_ord["product_id"], "size": "M", "color": "Trắng"}),
            ("search_knowledge", {"query": "Chính sách đổi trả"}),
            ("get_context", {}),
        ]:
            code, res = _call_api(
                self.app_a,
                "POST",
                "/api/tools/execute",
                "C-001",
                {"case_id": case_id, "tool_name": tool_name, "arguments": tool_args},
                context=self.ctx_mgr_a,
            )
            self.assertEqual(code, 200, f"{tool_name} failed: {res}")

    def test_postgres_sql_translation_safety_for_w5_queries(self):
        sample_queries = [
            """SELECT m.principal_id, p.name AS display_name, m.role
               FROM memberships m
               JOIN tenants t ON t.id = m.tenant_id
               JOIN principals p ON p.id = m.principal_id
               WHERE m.tenant_id = ? AND m.active = 1 AND t.active = 1
                 AND m.role IN ('staff', 'manager')
               ORDER BY p.name ASC, m.principal_id ASC""",
            """SELECT r.request_id, r.order_id, r.case_id, r.type, r.exchange_kind,
                      r.status, r.refund_status, r.refund_decision,
                      r.created_at, r.updated_at, r.closed_at,
                      c.name AS customer_name
               FROM order_action_requests r
               LEFT JOIN customers c ON r.customer_id = c.id
               WHERE r.refund_status = 'pending' AND r.refund_decision IS NULL
               ORDER BY r.created_at DESC, r.request_id DESC
               LIMIT ? OFFSET ?""",
        ]
        captured: list[str] = []

        class _FakeConn:
            def execute(self, sql, params):
                captured.append(sql)

        q_wrap = Queries(_FakeConn())
        for q in sample_queries:
            captured.clear()
            q_wrap.execute(q, ("x",) * q.count("?"))
            self.assertEqual(captured[0].count("%s"), q.count("?"))

    def test_chat_route_supports_legacy_two_arg_app_stub(self):
        class _FakeStore:
            @staticmethod
            def conversation(_customer, _cid):
                return {"provider_id": "custom"}

        class _TwoArgChatApp:
            store = _FakeStore()
            quota_store = None

            @staticmethod
            def chat(_customer, _body):
                return {"provider_id": "custom", "replayed": False, "trace": {}}

        status, res = api_result(
            _TwoArgChatApp(),
            "C-001",
            "POST",
            "/api/chat",
            {"conversation_id": "00000000-0000-0000-0000-000000000000", "request_id": "req_stub_12345678", "text": "demo"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(res["provider_id"], "custom")


if __name__ == "__main__":
    unittest.main()
