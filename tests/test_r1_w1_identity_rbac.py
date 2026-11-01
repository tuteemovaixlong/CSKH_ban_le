"""Targeted isolated unit tests for Phase R1 W1: identity, RBAC, backend authorization, and identity v5 migration."""
import argparse
from contextlib import closing
from dataclasses import FrozenInstanceError
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from retailops.bootstrap import build_public_app
from retailops.business.application import Application
from retailops.business.permissions import ACTIVE_BUSINESS_ROLES, LEGACY_DISABLED_ROLES, ROLE_PERMISSIONS
from retailops.business.store import BusinessStore
from retailops.config import Settings
from retailops.core import ApiError
from retailops.http import auth_google
from retailops.http.public import PublicWeb
from retailops.http.routes import api_result
from retailops.identity import cli as identity_cli
from retailops.identity.contracts import RequestContext, SessionBinding
from retailops.identity.persistent import PersistentSessions
from retailops.identity.postgres import PostgresSessions
from retailops.identity.store import (
    IDENTITY_V5_DISABLE_REASON,
    IdentityStore,
    migrate_sqlite_identity_v5,
    upgrade_sqlite_memberships_role_constraint,
)
from retailops.storage.import_sqlite import IDENTITY_TABLES, read_database
from retailops.storage.pg_repositories import PostgresIdentityStore, migrate_postgres_identity_v5
from retailops.storage.pg_schema import initialize as pg_initialize
from retailops.storage.postgres import IDENTITY_SCHEMA, IDENTITY_SCHEMA_CURRENT

ORIGIN = "https://retailops.example.com"


class _FixtureGateway:
    model = "fixture-r1-w1"

    def inspect(self):
        return {"name": self.model, "provider": "openrouter", "digest": None}

    def chat(self, messages, allow_tools=True, timeout=30):
        return {"message": {"role": "assistant", "content": "Phản hồi kiểm thử W1."}, "eval_count": 2, "prompt_eval_count": 5}


def _wsgi(web: PublicWeb, method: str, path: str, body=None, *, cookie: str = "", query: str = "", origin: str = ORIGIN):
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    env = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "HTTP_HOST": "retailops.example.com",
        "HTTP_COOKIE": cookie,
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw),
    }
    if origin:
        env["HTTP_ORIGIN"] = origin
    captured = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(headers)

    payload = b"".join(web(env, start_response))
    if captured["headers"].get("Content-Type", "").startswith("application/json"):
        return captured["status"], json.loads(payload.decode("utf-8")), captured["headers"]
    return captured["status"], payload, captured["headers"]


class PhaseR1W1IdentityRbacTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sessions = PersistentSessions(
            self.root / "persistent",
            infer=_FixtureGateway(),
            api_infer=_FixtureGateway(),
            api_daily_limit=10,
            default_tenant_id="tenant-a",
        )
        self.store_a = self.sessions.provision_tenant("tenant-a", "Cửa hàng Alpha", seed_demo=True)
        self.store_b = self.sessions.provision_tenant("tenant-b", "Cửa hàng Beta", seed_demo=True)
        self.web = PublicWeb(ORIGIN, self.sessions)

    def _provision_member(self, tenant_id: str, principal_id: str, name: str, customer_id: str, role: str):
        mid = self.sessions.create_member(tenant_id, principal_id, name, customer_id, role=role)
        tok = secrets.token_urlsafe(32)
        self.sessions.control.register_credential(mid, tok)
        status, _, headers = _wsgi(self.web, "POST", "/api/login", {"token": tok})
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"].split(";")[0]
        return mid, tok, cookie

    def test_immutable_request_context_and_no_mutable_current_binding(self):
        mid_mgr_1, _, cookie_mgr_1 = self._provision_member("tenant-a", "prin_mgr_1", "Quản Lý Một", "C-001", "manager")
        mid_mgr_2, _, cookie_mgr_2 = self._provision_member("tenant-a", "prin_mgr_2", "Quản Lý Hai", "C-002", "manager")

        ctx = RequestContext(
            customer_id="C-001",
            role="manager",
            permissions=ROLE_PERMISSIONS["manager"],
            workspace_id="ws-1",
            tenant_id="tenant-a",
            principal_id="prin_mgr_1",
            display_name="Quản Lý Một",
            membership_id=mid_mgr_1,
        )
        with self.assertRaises(FrozenInstanceError):
            ctx.role = "customer"  # type: ignore[misc]

        # Concurrent product updates over PublicWeb must keep exact per-request principal_id and never attach current_binding
        errors = []
        barrier = threading.Barrier(2)

        def _worker(cookie: str, pid: str):
            try:
                barrier.wait(timeout=5)
                code, _, _ = _wsgi(
                    self.web,
                    "POST",
                    "/api/manager/products",
                    {"id": pid, "name": f"SP {pid}", "price": 199000},
                    cookie=cookie,
                )
                if code != 201:
                    errors.append(f"unexpected status {code} for {pid}")
            except Exception as exc:  # pragma: no cover
                errors.append(str(exc))

        t1 = threading.Thread(target=_worker, args=(cookie_mgr_1, "P-910"))
        t2 = threading.Thread(target=_worker, args=(cookie_mgr_2, "P-920"))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        self.assertEqual(errors, [])

        for cached_app in self.sessions.apps.values():
            self.assertFalse(hasattr(cached_app, "current_binding"))

        code_ev, ev_body, _ = _wsgi(self.web, "GET", "/api/manager/events", cookie=cookie_mgr_1)
        self.assertEqual(code_ev, 200)
        created = {
            e["payload"]["product_id"]: e["payload"]["actor"]
            for e in ev_body["events"]
            if e["kind"] == "product_created" and e["payload"].get("product_id") in ("P-910", "P-920")
        }
        self.assertEqual(created["P-910"]["principal_id"], "prin_mgr_1")
        self.assertEqual(created["P-910"]["membership_id"], mid_mgr_1)
        self.assertEqual(created["P-920"]["principal_id"], "prin_mgr_2")
        self.assertEqual(created["P-920"]["membership_id"], mid_mgr_2)

    def test_role_matrix_tenant_admin_scope_last_manager_guard_and_opsadmin_separation(self):
        self.assertEqual(ACTIVE_BUSINESS_ROLES, ("customer", "staff", "manager"))
        self.assertEqual(LEGACY_DISABLED_ROLES, ("viewer", "platform_admin"))
        self.assertEqual(ROLE_PERMISSIONS["viewer"], frozenset())
        self.assertEqual(ROLE_PERMISSIONS["platform_admin"], frozenset())
        self.assertNotIn("opsadmin", ROLE_PERMISSIONS)

        mid_cust_a, _, cookie_cust_a = self._provision_member("tenant-a", "prin_cust_a", "Khách Alpha", "C-001", "customer")
        mid_staff_a, _, cookie_staff_a = self._provision_member("tenant-a", "prin_staff_a", "Nhân Viên Alpha", "C-002", "staff")
        mid_mgr_a1, _, cookie_mgr_a1 = self._provision_member("tenant-a", "prin_mgr_a1", "Quản Lý Alpha 1", "C-003", "manager")
        mid_mgr_a2, _, cookie_mgr_a2 = self._provision_member("tenant-a", "prin_mgr_a2", "Quản Lý Alpha 2", "C-001", "manager")
        mid_cust_b, _, _ = self._provision_member("tenant-b", "prin_cust_b", "Khách Beta", "C-001", "customer")

        # Orders scope: customer & staff get own customer scope; only manager gets store_all within session tenant
        _, cust_orders, _ = _wsgi(self.web, "GET", "/api/orders", cookie=cookie_cust_a)
        _, staff_orders, _ = _wsgi(self.web, "GET", "/api/orders", cookie=cookie_staff_a)
        _, mgr_orders, _ = _wsgi(self.web, "GET", "/api/orders", cookie=cookie_mgr_a1)
        expected_c001_ids = {o["id"] for o in self.store_a.orders("C-001")}
        self.assertEqual({o["id"] for o in cust_orders["orders"]}, expected_c001_ids)
        self.assertFalse(any(o["id"] == "O-101" for o in staff_orders["orders"]))
        self.assertGreater(len(mgr_orders["orders"]), len(cust_orders["orders"]))

        # Staff denied on /api/manager/* and /api/admin/* (and audited on /api/admin/*)
        self.assertEqual(_wsgi(self.web, "GET", "/api/manager/kpis", cookie=cookie_staff_a)[0], 403)
        code_staff_adm, body_staff_adm, _ = _wsgi(self.web, "GET", "/api/admin/accounts", cookie=cookie_staff_a)
        self.assertEqual((code_staff_adm, body_staff_adm["error"]), (403, "permission_denied"))

        # Manager cross-tenant query or cross-tenant target membership denied with 403 + denied audit
        self.assertEqual(_wsgi(self.web, "GET", "/api/admin/accounts", cookie=cookie_mgr_a1, query="tenant_id=tenant-b")[0], 403)
        self.assertEqual(_wsgi(self.web, "GET", f"/api/admin/accounts/{mid_cust_b}", cookie=cookie_mgr_a1)[0], 403)
        self.assertEqual(
            _wsgi(self.web, "POST", f"/api/admin/accounts/{mid_cust_b}/suspend", {"reason": "Cross tenant"}, cookie=cookie_mgr_a1)[0],
            403,
        )

        # Two active managers: mgr_a1 can suspend mgr_a2 (leaving mgr_a1 as last active manager)
        code_s2, body_s2, _ = _wsgi(
            self.web,
            "POST",
            f"/api/admin/accounts/{mid_mgr_a2}/suspend",
            {"reason": "Tạm ngưng quản lý thứ hai"},
            cookie=cookie_mgr_a1,
        )
        self.assertEqual(code_s2, 200)
        self.assertEqual(body_s2["account"]["disabled_reason"], "admin_suspended")
        self.assertEqual(_wsgi(self.web, "GET", "/api/session", cookie=cookie_mgr_a2)[0], 401)

        # Last-active-manager guard: suspending the sole remaining active manager of tenant-a fails closed with 409
        with self.assertRaises(ApiError) as last_mgr_err:
            self.sessions.control.admin_suspend_account(
                {"principal_id": "prin_other_mgr", "role": "manager", "tenant_id": "tenant-a", "membership_id": "m_other"},
                mid_mgr_a1,
                reason="Thử khóa quản lý hoạt động cuối cùng",
                correlation_id="corr-last-mgr-guard",
            )
        self.assertEqual((last_mgr_err.exception.status, last_mgr_err.exception.code), (409, "last_active_manager_forbidden"))

        code_audit, audit_body, _ = _wsgi(self.web, "GET", "/api/admin/audit-log", cookie=cookie_mgr_a1)
        self.assertEqual(code_audit, 200)
        by_corr = {r["correlation_id"]: r for r in audit_body["audit_logs"]}
        self.assertEqual(by_corr["corr-last-mgr-guard"]["outcome"], "denied")
        self.assertEqual(by_corr["corr-last-mgr-guard"]["after"]["error"], "last_active_manager_forbidden")

        # Viewer and platform_admin fail closed at Application and route boundaries without promoting or aliasing
        for retired_role in ("viewer", "platform_admin"):
            retired_app = Application(self.store_a, {}, role=retired_role)
            with self.assertRaises(ApiError) as app_err:
                retired_app.new_conversation("C-001", {})
            self.assertEqual((app_err.exception.status, app_err.exception.code), (403, "permission_denied"))
            with self.assertRaises(ApiError) as route_err:
                api_result(retired_app, "C-001", "GET", "/api/orders")
            self.assertEqual((route_err.exception.status, route_err.exception.code), (403, "permission_denied"))

    def test_server_actor_identity_anti_spoofing_and_no_mai_anh_synthesis(self):
        _, _, cookie_cust = self._provision_member("tenant-a", "prin_cust_1", "Nguyễn Văn Khách", "C-001", "customer")
        mid_staff, _, cookie_staff = self._provision_member("tenant-a", "prin_staff_real", "Trần Thị Nhân Viên", "C-002", "staff")

        # Persistent session/profile never synthesize "Mai Anh" even if principal name in DB is blank
        with self.sessions.control.connection(write=True) as db:
            db.execute("INSERT INTO principals(id, name) VALUES ('prin_blank_staff', '')")
            db.execute(
                "INSERT INTO memberships(id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m_blank_staff', 'tenant-a', 'prin_blank_staff', 'C-003', 'staff', 1, 1)"
            )
        blank_secret = self.sessions.control.create_session_for_membership("m_blank_staff", 3600, 50)
        cookie_blank = f"{self.sessions.cookie_name}={blank_secret}"
        _, sess_blank, _ = _wsgi(self.web, "GET", "/api/session", cookie=cookie_blank)
        _, prof_blank, _ = _wsgi(self.web, "GET", "/api/profile", cookie=cookie_blank)
        self.assertEqual(sess_blank["name"], "")
        self.assertEqual(prof_blank["name"], "")
        self.assertNotIn("Mai Anh", json.dumps(sess_blank, ensure_ascii=False))
        self.assertNotIn("Mai Anh", json.dumps(prof_blank, ensure_ascii=False))

        # Customer opens conversation and requests human handoff
        _, conv_res, _ = _wsgi(self.web, "POST", "/api/conversations", {}, cookie=cookie_cust)
        conv_id = conv_res["conversation_id"]
        code_fb, _, _ = _wsgi(
            self.web,
            "POST",
            "/api/feedback",
            {"conversation_id": conv_id, "feedback_type": "human_handoff", "reason_code": "customer_requested_human"},
            cookie=cookie_cust,
        )
        self.assertEqual(code_fb, 200)

        # Staff sends spoofed staff_name -> server ignores client staff_name and records session actor
        code_rep, rep_body, _ = _wsgi(
            self.web,
            "POST",
            "/api/staff/reply",
            {
                "conversation_id": conv_id,
                "message": "Shop đã kiểm tra đơn O-101 cho bạn.",
                "staff_name": "Giả Mạo Quản Trị",
            },
            cookie=cookie_staff,
        )
        self.assertEqual(code_rep, 200)
        self.assertEqual(rep_body["staff_name"], "Trần Thị Nhân Viên")

        code_tool, _, _ = _wsgi(
            self.web,
            "POST",
            "/api/tools/execute",
            {"conversation_id": conv_id, "tool_name": "get_order", "arguments": {"order_id": "O-101"}},
            cookie=cookie_staff,
        )
        self.assertEqual(code_tool, 200)

        code_res, _, _ = _wsgi(
            self.web,
            "POST",
            "/api/staff/resolve",
            {"conversation_id": conv_id, "staff_name": "Giả Mạo Quản Trị"},
            cookie=cookie_staff,
        )
        self.assertEqual(code_res, 200)

        # Verify turn trace and business_events store server actor, not spoofed staff_name
        raw_events = self.store_a.events("C-001")
        reply_ev = next(e for e in raw_events if e["kind"] == "staff_replied")
        resolve_ev = next(e for e in raw_events if e["kind"] == "escalation_resolved")
        for ev in (reply_ev, resolve_ev):
            self.assertEqual(ev["payload"]["staff_name"], "Trần Thị Nhân Viên")
            self.assertEqual(ev["payload"]["actor"]["principal_id"], "prin_staff_real")
            self.assertEqual(ev["payload"]["actor"]["role"], "staff")
            self.assertEqual(ev["payload"]["actor"]["membership_id"], mid_staff)
            self.assertEqual(ev["payload"]["actor"]["tenant_id"], "tenant-a")
            self.assertNotIn("Giả Mạo", json.dumps(ev, ensure_ascii=False))

        # Customer /api/events hides internal staff_tool_executed and strips internal actor metadata
        _, cust_ev_body, _ = _wsgi(self.web, "GET", "/api/events", cookie=cookie_cust)
        self.assertFalse(any(e["kind"] == "staff_tool_executed" for e in cust_ev_body["events"]))
        cust_rep_ev = next(e for e in cust_ev_body["events"] if e["kind"] == "staff_replied")
        cust_res_ev = next(e for e in cust_ev_body["events"] if e["kind"] == "escalation_resolved")
        self.assertNotIn("actor", cust_rep_ev["payload"])
        self.assertNotIn("actor", cust_res_ev["payload"])

    def test_tools_execute_requires_binding_escalation_tenant_and_object_scope(self):
        _, _, cookie_cust_a1 = self._provision_member("tenant-a", "prin_ca1", "Khách A1", "C-001", "customer")
        _, _, cookie_staff_a = self._provision_member("tenant-a", "prin_sa1", "Staff A1", "C-002", "staff")
        _, _, cookie_mgr_a = self._provision_member("tenant-a", "prin_ma1", "Manager A1", "C-003", "manager")
        _, _, cookie_cust_b1 = self._provision_member("tenant-b", "prin_cb1", "Khách B1", "C-001", "customer")

        conv_a_unescalated = _wsgi(self.web, "POST", "/api/conversations", {}, cookie=cookie_cust_a1)[1]["conversation_id"]
        conv_a_escalated = _wsgi(self.web, "POST", "/api/conversations", {}, cookie=cookie_cust_a1)[1]["conversation_id"]
        _wsgi(
            self.web,
            "POST",
            "/api/feedback",
            {"conversation_id": conv_a_escalated, "feedback_type": "human_handoff", "reason_code": "need_human"},
            cookie=cookie_cust_a1,
        )
        conv_b = _wsgi(self.web, "POST", "/api/conversations", {}, cookie=cookie_cust_b1)[1]["conversation_id"]
        _wsgi(
            self.web,
            "POST",
            "/api/feedback",
            {"conversation_id": conv_b, "feedback_type": "human_handoff", "reason_code": "need_human"},
            cookie=cookie_cust_b1,
        )

        # Missing conversation_id -> 403 missing_object_binding; malformed conversation_id -> 400 invalid_conversation
        code_no_conv, body_no_conv, _ = _wsgi(
            self.web,
            "POST",
            "/api/tools/execute",
            {"tool_name": "get_order", "arguments": {"order_id": "O-101"}},
            cookie=cookie_staff_a,
        )
        self.assertEqual((code_no_conv, body_no_conv["error"]), (403, "missing_object_binding"))
        code_bad_conv, body_bad_conv, _ = _wsgi(
            self.web,
            "POST",
            "/api/tools/execute",
            {"conversation_id": "not-a-uuid", "tool_name": "get_order", "arguments": {"order_id": "O-101"}},
            cookie=cookie_staff_a,
        )
        self.assertEqual((code_bad_conv, body_bad_conv["error"]), (400, "invalid_conversation"))
        # Unescalated conversation rejected for BOTH staff AND manager (403 case_not_escalated) — W1-RB-02
        code_unesc, body_unesc, _ = _wsgi(
            self.web,
            "POST",
            "/api/tools/execute",
            {"conversation_id": conv_a_unescalated, "tool_name": "get_order", "arguments": {"order_id": "O-101"}},
            cookie=cookie_staff_a,
        )
        self.assertEqual((code_unesc, body_unesc["error"]), (403, "case_not_escalated"))
        code_mgr_unesc, body_mgr_unesc, _ = _wsgi(
            self.web,
            "POST",
            "/api/tools/execute",
            {"conversation_id": conv_a_unescalated, "tool_name": "get_order", "arguments": {"order_id": "O-101"}},
            cookie=cookie_mgr_a,
        )
        self.assertEqual((code_mgr_unesc, body_mgr_unesc["error"]), (403, "case_not_escalated"))
        # Cross-tenant conversation -> 404 for both staff and manager
        self.assertEqual(
            _wsgi(
                self.web,
                "POST",
                "/api/tools/execute",
                {"conversation_id": conv_b, "tool_name": "get_order", "arguments": {"order_id": "O-101"}},
                cookie=cookie_staff_a,
            )[0],
            404,
        )
        self.assertEqual(
            _wsgi(
                self.web,
                "POST",
                "/api/tools/execute",
                {"conversation_id": conv_b, "tool_name": "get_order", "arguments": {"order_id": "O-101"}},
                cookie=cookie_mgr_a,
            )[0],
            404,
        )
        # Cross-customer order on C-001's escalated conversation (O-202 belongs to C-002) -> 403 object_scope_denied
        code_other_ord, body_other_ord, _ = _wsgi(
            self.web,
            "POST",
            "/api/tools/execute",
            {"conversation_id": conv_a_escalated, "tool_name": "get_order", "arguments": {"order_id": "O-202"}},
            cookie=cookie_staff_a,
        )
        self.assertEqual((code_other_ord, body_other_ord["error"]), (403, "object_scope_denied"))

        # Valid escalated case + matching order -> 200 + staff_tool_executed audit event for both Staff and Manager
        code_ok, body_ok, _ = _wsgi(
            self.web,
            "POST",
            "/api/tools/execute",
            {"conversation_id": conv_a_escalated, "tool_name": "get_order", "arguments": {"order_id": "O-101"}},
            cookie=cookie_staff_a,
        )
        self.assertEqual(code_ok, 200)
        self.assertEqual(body_ok["result"]["order"]["id"], "O-101")
        code_mgr_ok, body_mgr_ok, _ = _wsgi(
            self.web,
            "POST",
            "/api/tools/execute",
            {"conversation_id": conv_a_escalated, "tool_name": "get_order", "arguments": {"order_id": "O-101"}},
            cookie=cookie_mgr_a,
        )
        self.assertEqual(code_mgr_ok, 200)
        self.assertEqual(body_mgr_ok["result"]["order"]["id"], "O-101")
        tool_evs = [e for e in self.store_a.events("C-001") if e["kind"] == "staff_tool_executed"]
        self.assertEqual({e["payload"]["actor"]["principal_id"] for e in tool_evs}, {"prin_sa1", "prin_ma1"})
        for e in tool_evs:
            self.assertEqual(e["payload"]["conversation_id"], conv_a_escalated)

    def test_staff_and_manager_handoff_episode_object_scope_w1_rb_01(self):
        _, _, cookie_cust_a = self._provision_member("tenant-a", "prin_rb01_ca", "Khách A", "C-001", "customer")
        _, _, cookie_staff_a = self._provision_member("tenant-a", "prin_rb01_sa", "Staff A", "C-002", "staff")
        _, _, cookie_mgr_a = self._provision_member("tenant-a", "prin_rb01_ma", "Manager A", "C-003", "manager")
        _, _, cookie_cust_b = self._provision_member("tenant-b", "prin_rb01_cb", "Khách B", "C-001", "customer")

        # 1) Conversation with no handoff; 2) Conversation with resolved handoff;
        # 3) Conversation A with open handoff alongside Conversation B without handoff;
        # 4) Conversation in tenant-b (with open handoff there); 5) Non-existent conversation UUID.
        conv_no_handoff = _wsgi(self.web, "POST", "/api/conversations", {}, cookie=cookie_cust_a)[1]["conversation_id"]
        conv_resolved = _wsgi(self.web, "POST", "/api/conversations", {}, cookie=cookie_cust_a)[1]["conversation_id"]
        _wsgi(
            self.web,
            "POST",
            "/api/feedback",
            {"conversation_id": conv_resolved, "feedback_type": "human_handoff", "reason_code": "need_human"},
            cookie=cookie_cust_a,
        )
        self.assertEqual(
            _wsgi(self.web, "POST", "/api/staff/resolve", {"conversation_id": conv_resolved}, cookie=cookie_staff_a)[0],
            200,
        )

        conv_open_a = _wsgi(self.web, "POST", "/api/conversations", {}, cookie=cookie_cust_a)[1]["conversation_id"]
        _wsgi(
            self.web,
            "POST",
            "/api/feedback",
            {"conversation_id": conv_open_a, "feedback_type": "human_handoff", "reason_code": "need_human"},
            cookie=cookie_cust_a,
        )
        conv_unescalated_b = _wsgi(self.web, "POST", "/api/conversations", {}, cookie=cookie_cust_a)[1]["conversation_id"]

        conv_other_tenant = _wsgi(self.web, "POST", "/api/conversations", {}, cookie=cookie_cust_b)[1]["conversation_id"]
        _wsgi(
            self.web,
            "POST",
            "/api/feedback",
            {"conversation_id": conv_other_tenant, "feedback_type": "human_handoff", "reason_code": "need_human"},
            cookie=cookie_cust_b,
        )
        conv_missing = "00000000-0000-4000-8000-000000000099"

        def _counts(bstore: BusinessStore):
            with bstore.connection() as db:
                turns = db.execute("SELECT COUNT(*) FROM agent_turns").fetchone()[0]
                events = db.execute("SELECT COUNT(*) FROM business_events").fetchone()[0]
                return turns, events

        baseline_a = _counts(self.store_a)
        baseline_b = _counts(self.store_b)

        denied_cases = [
            ("no_handoff", conv_no_handoff, 403, 409, "case_not_escalated"),
            ("handoff_on_A_call_on_B", conv_unescalated_b, 403, 409, "case_not_escalated"),
            ("missing_conv", conv_missing, 404, 404, "conversation_not_found"),
            ("other_tenant_conv", conv_other_tenant, 404, 404, "conversation_not_found"),
        ]
        for role_label, actor_cookie in (("staff", cookie_staff_a), ("manager", cookie_mgr_a)):
            for case_name, target_cid, exp_status, exp_resolve_status, exp_code in denied_cases:
                with self.subTest(role=role_label, case=case_name):
                    s1, b1, _ = _wsgi(self.web, "GET", f"/api/staff/conversations/{target_cid}/messages", cookie=actor_cookie)
                    self.assertEqual((s1, b1["error"]), (exp_status, exp_code))

                    s2, b2, _ = _wsgi(self.web, "GET", f"/api/conversations/{target_cid}/messages", cookie=actor_cookie)
                    self.assertEqual((s2, b2["error"]), (exp_status, exp_code))

                    s3, b3, _ = _wsgi(
                        self.web,
                        "POST",
                        "/api/staff/reply",
                        {"conversation_id": target_cid, "message": "Không được phép ghi"},
                        cookie=actor_cookie,
                    )
                    self.assertEqual((s3, b3["error"]), (exp_status, exp_code))

                    s4, b4, _ = _wsgi(
                        self.web,
                        "POST",
                        "/api/staff/resolve",
                        {"conversation_id": target_cid},
                        cookie=actor_cookie,
                    )
                    self.assertEqual((s4, b4["error"]), (exp_resolve_status, exp_code))
                    self.assertNotEqual(b4.get("resolved"), True)

            # W2-D2: Resolved cases in the same tenant Remain strictly blocked on reply (403) and resolve (409)
            s_rep_res, b_rep_res, _ = _wsgi(
                self.web,
                "POST",
                "/api/staff/reply",
                {"conversation_id": conv_resolved, "message": "Không được phép ghi vào ca đã đóng"},
                cookie=actor_cookie,
            )
            self.assertEqual((s_rep_res, b_rep_res["error"]), (403, "case_not_escalated"))
            s_res_res, b_res_res, _ = _wsgi(
                self.web,
                "POST",
                "/api/staff/resolve",
                {"conversation_id": conv_resolved},
                cookie=actor_cookie,
            )
            self.assertEqual((s_res_res, b_res_res["error"]), (409, "case_not_escalated"))

        # Direct store calls also fail closed without writing turns or events
        for bad_cid in (conv_no_handoff, conv_resolved, conv_unescalated_b):
            with self.assertRaises(ApiError) as rep_err:
                self.store_a.staff_reply("C-001", bad_cid, "Staff", "Blocked")
            self.assertEqual((rep_err.exception.status, rep_err.exception.code), (403, "case_not_escalated"))
            with self.assertRaises(ApiError) as res_err:
                self.store_a.resolve_escalation(bad_cid, "Staff")
            self.assertEqual((res_err.exception.status, res_err.exception.code), (409, "case_not_escalated"))

        self.assertEqual(_counts(self.store_a), baseline_a)
        self.assertEqual(_counts(self.store_b), baseline_b)

        # W2-D2: Same-tenant Staff and Manager can view resolved transcript read-only within retention, logging audit on every view
        for actor_cookie in (cookie_staff_a, cookie_mgr_a):
            sr, br, _ = _wsgi(self.web, "GET", f"/api/staff/conversations/{conv_resolved}/messages", cookie=actor_cookie)
            self.assertEqual(sr, 200)
            self.assertTrue(br.get("read_only"))

        # Valid open handoff works for both Staff and Manager (including NULL reason_code)
        self.assertEqual(_wsgi(self.web, "GET", f"/api/staff/conversations/{conv_open_a}/messages", cookie=cookie_staff_a)[0], 200)
        self.assertEqual(_wsgi(self.web, "GET", f"/api/conversations/{conv_open_a}/messages", cookie=cookie_mgr_a)[0], 200)
        self.assertEqual(
            _wsgi(
                self.web,
                "POST",
                "/api/staff/reply",
                {"conversation_id": conv_open_a, "message": "Hỗ trợ hợp lệ từ quản lý"},
                cookie=cookie_mgr_a,
            )[0],
            200,
        )
        res_ok_status, res_ok_body, _ = _wsgi(
            self.web,
            "POST",
            "/api/staff/resolve",
            {"conversation_id": conv_open_a},
            cookie=cookie_mgr_a,
        )
        self.assertEqual(res_ok_status, 200)
        self.assertIs(res_ok_body["resolved"], True)

        # Once resolved, a second resolve attempt on the same conversation is denied with 409 (never resolved: True)
        res_dup_status, res_dup_body, _ = _wsgi(
            self.web,
            "POST",
            "/api/staff/resolve",
            {"conversation_id": conv_open_a},
            cookie=cookie_mgr_a,
        )
        self.assertEqual((res_dup_status, res_dup_body["error"]), (409, "case_not_escalated"))
        self.assertNotEqual(res_dup_body.get("resolved"), True)

    def test_google_login_never_overwrites_existing_role_and_enforces_email_verified(self):
        for default_ok in ("customer", ""):
            with patch.dict(
                os.environ,
                {
                    "STAFF_EMAILS": "staff@shop.vn",
                    "MANAGER_EMAILS": "mgr@shop.vn",
                    "DEFAULT_ROLE": default_ok,
                },
                clear=False,
            ):
                # Unverified email must never get elevated role from allowlists
                self.assertEqual(auth_google.resolve_role_from_email("mgr@shop.vn", email_verified=False), "customer")
                self.assertEqual(auth_google.resolve_role_from_email("staff@shop.vn", email_verified=False), "customer")
                self.assertEqual(auth_google.resolve_role_from_email("new@shop.vn", email_verified=True), "customer")
                self.assertEqual(auth_google.resolve_role_from_email("staff@shop.vn", email_verified=True), "staff")
                self.assertEqual(auth_google.resolve_role_from_email("mgr@shop.vn", email_verified=True), "manager")

        # W1-ID-01: DEFAULT_ROLE other than 'customer' (including 'staff' and 'manager') must fail closed with 403
        for privileged_default in ("staff", "manager", "opsadmin", "unknown_role"):
            with patch.dict(os.environ, {"DEFAULT_ROLE": privileged_default, "STAFF_EMAILS": "", "MANAGER_EMAILS": ""}, clear=False):
                for verified_flag in (True, False):
                    with self.assertRaises(ApiError) as priv_def:
                        auth_google.resolve_role_from_email("newuser@example.com", email_verified=verified_flag)
                    self.assertEqual((priv_def.exception.status, priv_def.exception.code), (403, "invalid_default_role"))

        for retired_default in ("viewer", "platform_admin"):
            with patch.dict(os.environ, {"DEFAULT_ROLE": retired_default, "STAFF_EMAILS": "", "MANAGER_EMAILS": ""}, clear=False):
                with self.assertRaises(ApiError) as bad_def:
                    auth_google.resolve_role_from_email("newuser@example.com", email_verified=True)
                self.assertEqual((bad_def.exception.status, bad_def.exception.code), (403, "legacy_role_disabled"))

        # Defense-in-depth: direct store provisioning never grants privileged role to an unverified email
        for priv_role in ("staff", "manager"):
            with self.assertRaises(ApiError) as unv_err:
                self.sessions.control.get_or_create_google_member(
                    "tenant-a",
                    f"unverified_{priv_role}@example.com",
                    "Unverified User",
                    role=priv_role,
                    sub=f"sub-unv-{priv_role}",
                    email_verified=False,
                )
            self.assertEqual((unv_err.exception.status, unv_err.exception.code), (403, "unverified_privileged_role"))

        # 1. Existing customer logs in via Google; later someone puts their email in MANAGER_EMAILS -> role stays customer!
        sec1 = self.sessions.login_google(
            "returning@example.com",
            "Returning Customer",
            role="customer",
            sub="sub-returning-001",
            email_verified=True,
            tenant_id="tenant-a",
        )
        row_before = self.sessions.control.resolve(self.sessions.cookie_id(f"{self.sessions.cookie_name}={sec1}"))
        self.assertEqual(row_before["role"], "customer")
        auth_ver_before = row_before["auth_version"]

        sec2 = self.sessions.login_google(
            "returning@example.com",
            "Returning Customer",
            role="manager",
            sub="sub-returning-001",
            email_verified=True,
            tenant_id="tenant-a",
        )
        row_after = self.sessions.control.resolve(self.sessions.cookie_id(f"{self.sessions.cookie_name}={sec2}"))
        self.assertEqual(row_after["role"], "customer")
        self.assertEqual(row_after["auth_version"], auth_ver_before)

        # 2. Operator promotes via CLI/store set_role -> auth_version bumps, old session invalidated, audit recorded;
        #    subsequent Google login with role='customer' does NOT demote back to customer!
        self.sessions.control.set_role(row_before["id"], "staff")
        with self.assertRaises(ApiError):
            self.sessions.control.resolve(self.sessions.cookie_id(f"{self.sessions.cookie_name}={sec2}"))

        sec3 = self.sessions.login_google(
            "returning@example.com",
            "Returning Customer",
            role="customer",
            sub="sub-returning-001",
            email_verified=True,
            tenant_id="tenant-a",
        )
        row_staff = self.sessions.control.resolve(self.sessions.cookie_id(f"{self.sessions.cookie_name}={sec3}"))
        self.assertEqual(row_staff["role"], "staff")

    def test_identity_v5_migration_sqlite_postgres_mock_and_snapshot_import(self):
        legacy_root = self.root / "legacy_v4_env"
        legacy_pers = legacy_root / "persistent"
        legacy_pers.mkdir(parents=True, exist_ok=True)
        legacy_path = legacy_pers / "identity.sqlite3"
        with closing(sqlite3.connect(legacy_path)) as db, db:
            db.executescript(
                """
                CREATE TABLE retailops_schema(component TEXT PRIMARY KEY, version INTEGER NOT NULL);
                INSERT INTO retailops_schema VALUES ('identity', 4);
                CREATE TABLE tenants(id TEXT PRIMARY KEY, name TEXT NOT NULL, storage_key TEXT UNIQUE NOT NULL, active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE principals(id TEXT PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE memberships(
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id),
                    principal_id TEXT NOT NULL REFERENCES principals(id),
                    customer_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('customer','viewer','staff','manager','platform_admin')),
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
                    auth_version INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(tenant_id, principal_id)
                );
                CREATE TABLE credentials(hash TEXT PRIMARY KEY, membership_id TEXT NOT NULL REFERENCES memberships(id), created_at REAL NOT NULL);
                CREATE TABLE sessions(id TEXT PRIMARY KEY, membership_id TEXT NOT NULL REFERENCES memberships(id), auth_version INTEGER NOT NULL, expires_at REAL NOT NULL);
                CREATE TABLE identity_events(id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL, kind TEXT NOT NULL, tenant_id TEXT, membership_id TEXT);
                INSERT INTO tenants VALUES ('t1', 'Shop 1', '0123456789abcdef0123456789abcdef', 1);
                INSERT INTO principals VALUES ('p_cust', 'Cust'), ('p_view', 'View'), ('p_padm', 'PAdmin');
                INSERT INTO memberships VALUES ('m_cust', 't1', 'p_cust', 'C-001', 'customer', 1, 3);
                INSERT INTO memberships VALUES ('m_view', 't1', 'p_view', 'C-001', 'viewer', 1, 2);
                INSERT INTO memberships VALUES ('m_padm', 't1', 'p_padm', 'C-002', 'platform_admin', 1, 5);
                INSERT INTO sessions VALUES ('s_cust', 'm_cust', 3, 1999999999.0);
                INSERT INTO sessions VALUES ('s_view', 'm_view', 2, 1999999999.0);
                INSERT INTO sessions VALUES ('s_padm', 'm_padm', 5, 1999999999.0);
                """
            )

        def _sqlite_v4_snapshot(p: Path):
            uri = p.resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as rdb:
                ver = rdb.execute("SELECT version FROM retailops_schema WHERE component='identity'").fetchone()[0]
                cols = [r[1] for r in rdb.execute("PRAGMA table_info(memberships)").fetchall()]
                mems = rdb.execute(
                    "SELECT id, role, active, auth_version FROM memberships ORDER BY id"
                ).fetchall()
                sess = [r[0] for r in rdb.execute("SELECT id FROM sessions ORDER BY id").fetchall()]
                evs = rdb.execute("SELECT COUNT(*) FROM identity_events").fetchone()[0]
                return ver, cols, mems, sess, evs

        snap_before = _sqlite_v4_snapshot(legacy_path)
        self.assertEqual(snap_before[0], 4)
        self.assertNotIn("disabled_reason", snap_before[1])

        # W1-MIG-01: Store construction, PersistentSessions, build_public_app, and ordinary CLI fail closed with ZERO data changes
        for fn in (
            lambda: IdentityStore(legacy_path),
            lambda: IdentityStore(legacy_path, initialize_db=False, read_only=False),
            lambda: PersistentSessions(legacy_pers),
            lambda: build_public_app(
                Settings(
                    interface="public",
                    bind="127.0.0.1",
                    port=8000,
                    origin=ORIGIN,
                    access_token="unused-token-" + "x" * 32,
                    output=legacy_root,
                    data_mode="persistent-demo",
                )
            ),
        ):
            with self.assertRaises(ApiError) as mig_req:
                fn()
            self.assertEqual((mig_req.exception.status, mig_req.exception.code), (503, "identity_migration_required"))

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command", required=True)
        identity_cli.add_parser(sub)
        with patch.dict(os.environ, {"RETAILOPS_STORAGE_BACKEND": "sqlite"}, clear=False):
            for bad_cli_argv in (
                ["identity", "--output", str(legacy_root), "set-role", "--membership", "m_cust", "--role", "staff"],
                ["identity", "--output", str(legacy_root), "revoke", "--membership", "m_cust"],
            ):
                with self.assertRaises(ApiError) as cli_mig_err:
                    identity_cli.run(parser.parse_args(bad_cli_argv))
                self.assertEqual((cli_mig_err.exception.status, cli_mig_err.exception.code), (503, "identity_migration_required"))

            # Explicit migrate-v5 without both confirmation flags also fails closed with zero data changes
            for unconfirmed_argv in (
                ["identity", "--output", str(legacy_root), "migrate-v5"],
                ["identity", "--output", str(legacy_root), "migrate-v5", "--confirm-preflight"],
                ["identity", "--output", str(legacy_root), "migrate-v5", "--confirm-backup"],
            ):
                with self.assertRaises(ApiError) as confirm_err:
                    identity_cli.run(parser.parse_args(unconfirmed_argv))
                self.assertEqual(
                    (confirm_err.exception.status, confirm_err.exception.code),
                    (400, "migration_confirmation_required"),
                )

        # Verify 100% zero data modification after all blocked startup/CLI attempts
        self.assertEqual(_sqlite_v4_snapshot(legacy_path), snap_before)

        # Explicit operator migrate-v5 with both confirmation flags upgrades cleanly and idempotently
        with patch.dict(os.environ, {"RETAILOPS_STORAGE_BACKEND": "sqlite"}, clear=False):
            mig_res_1 = identity_cli.run(
                parser.parse_args(
                    [
                        "identity",
                        "--output",
                        str(legacy_root),
                        "migrate-v5",
                        "--confirm-preflight",
                        "--confirm-backup",
                    ]
                )
            )
            self.assertEqual(
                mig_res_1,
                {"result": "IDENTITY_V5_MIGRATED", "backend": "sqlite", "schema_version": 5, "upgraded": True},
            )
            mig_res_2 = identity_cli.run(
                parser.parse_args(
                    [
                        "identity",
                        "--output",
                        str(legacy_root),
                        "migrate-v5",
                        "--confirm-preflight",
                        "--confirm-backup",
                    ]
                )
            )
            self.assertEqual(
                mig_res_2,
                {"result": "IDENTITY_V5_MIGRATED", "backend": "sqlite", "schema_version": 5, "upgraded": False},
            )

        store = IdentityStore(legacy_path)
        mgr_id = self.sessions.create_member("tenant-a", "prin_mgr_react", "Quản Lý", "C-003", role="manager")
        store_mgr_id = store.create_membership("t1", "p_mgr", "Mgr", "C-003", "manager")

        # W1-ID-02: set_role / CLI set-role MUST reject retired legacy memberships, keep disabled_reason intact,
        # and subsequent Manager reactivate MUST still fail closed with 409 legacy_role_retired
        for retired_mid, target_role in (("m_view", "staff"), ("m_padm", "manager")):
            with store.connection() as db:
                before_row = dict(db.execute("SELECT * FROM memberships WHERE id=?", (retired_mid,)).fetchone())
            with self.assertRaises(ApiError) as set_err:
                store.set_role(retired_mid, target_role)
            self.assertEqual((set_err.exception.status, set_err.exception.code), (409, "legacy_role_retired"))
            with patch.dict(os.environ, {"RETAILOPS_STORAGE_BACKEND": "sqlite"}, clear=False):
                with self.assertRaises(ApiError) as cli_set_err:
                    identity_cli.run(
                        parser.parse_args(
                            [
                                "identity",
                                "--output",
                                str(legacy_root),
                                "set-role",
                                "--membership",
                                retired_mid,
                                "--role",
                                target_role,
                            ]
                        )
                    )
                self.assertEqual((cli_set_err.exception.status, cli_set_err.exception.code), (409, "legacy_role_retired"))
            with store.connection() as db:
                after_row = dict(db.execute("SELECT * FROM memberships WHERE id=?", (retired_mid,)).fetchone())
            self.assertEqual(after_row, before_row)
            self.assertEqual(after_row["disabled_reason"], IDENTITY_V5_DISABLE_REASON)

            with self.assertRaises(ApiError) as react_err:
                store.admin_reactivate_account(
                    {"principal_id": "p_mgr", "role": "manager", "tenant_id": "t1", "membership_id": store_mgr_id},
                    retired_mid,
                    reason="Thử mở lại tài khoản legacy sau set-role",
                )
            self.assertEqual((react_err.exception.status, react_err.exception.code), (409, "legacy_role_retired"))

        # Even if a row has an active role name in DB but carries disabled_reason='retired_legacy_role_r1_w1',
        # set_role and admin_reactivate_account still reject it and never clear the marker
        with store.connection(write=True) as db:
            db.execute("INSERT INTO principals VALUES ('p_marked', 'Marked Legacy')")
            db.execute(
                "INSERT INTO memberships(id, tenant_id, principal_id, customer_id, role, active, auth_version, disabled_reason) "
                "VALUES ('m_marked', 't1', 'p_marked', 'C-009', 'customer', 0, 1, ?)",
                (IDENTITY_V5_DISABLE_REASON,),
            )
        with self.assertRaises(ApiError) as marked_set_err:
            store.set_role("m_marked", "staff")
        self.assertEqual((marked_set_err.exception.status, marked_set_err.exception.code), (409, "legacy_role_retired"))
        with self.assertRaises(ApiError) as marked_react_err:
            store.admin_reactivate_account(
                {"principal_id": "p_mgr", "role": "manager", "tenant_id": "t1", "membership_id": store_mgr_id},
                "m_marked",
                reason="Thử mở lại row mang marker retire",
            )
        self.assertEqual((marked_react_err.exception.status, marked_react_err.exception.code), (409, "legacy_role_retired"))
        with store.connection() as db:
            marked_after = dict(db.execute("SELECT * FROM memberships WHERE id='m_marked'").fetchone())
        self.assertEqual(marked_after["role"], "customer")
        self.assertEqual(marked_after["active"], 0)
        self.assertEqual(marked_after["disabled_reason"], IDENTITY_V5_DISABLE_REASON)
        self.assertTrue(mgr_id)

        with store.connection() as db:
            ver = db.execute("SELECT version FROM retailops_schema WHERE component='identity'").fetchone()[0]
            self.assertEqual(ver, 5)
            m_cust = dict(db.execute("SELECT * FROM memberships WHERE id='m_cust'").fetchone())
            m_view = dict(db.execute("SELECT * FROM memberships WHERE id='m_view'").fetchone())
            m_padm = dict(db.execute("SELECT * FROM memberships WHERE id='m_padm'").fetchone())
            self.assertEqual((m_cust["active"], m_cust["auth_version"], m_cust["disabled_reason"]), (1, 3, None))
            self.assertEqual((m_view["active"], m_view["auth_version"], m_view["disabled_reason"]), (0, 3, IDENTITY_V5_DISABLE_REASON))
            self.assertEqual((m_padm["active"], m_padm["auth_version"], m_padm["disabled_reason"]), (0, 6, IDENTITY_V5_DISABLE_REASON))
            rem_sessions = [r["id"] for r in db.execute("SELECT id FROM sessions").fetchall()]
            self.assertEqual(rem_sessions, ["s_cust"])

        # Valid membership set-role still works: bumps auth_version, revokes active session s_cust, writes audit
        with patch.dict(os.environ, {"RETAILOPS_STORAGE_BACKEND": "sqlite"}, clear=False):
            upd_res = identity_cli.run(
                parser.parse_args(
                    ["identity", "--output", str(legacy_root), "set-role", "--membership", "m_cust", "--role", "staff"]
                )
            )
        self.assertEqual(upd_res["result"], "MEMBERSHIP_UPDATED")
        with store.connection() as db:
            m_cust_after = dict(db.execute("SELECT * FROM memberships WHERE id='m_cust'").fetchone())
            self.assertEqual((m_cust_after["role"], m_cust_after["auth_version"]), ("staff", 4))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions WHERE membership_id='m_cust'").fetchone()[0], 0)
            audit_set = db.execute(
                "SELECT action, outcome FROM admin_audit_log WHERE target_membership_id='m_cust' AND action='set_role'"
            ).fetchone()
            self.assertEqual((audit_set["action"], audit_set["outcome"]), ("set_role", "allowed"))

        # Brand-new empty SQLite DB still initializes directly at schema v5
        fresh_db = self.root / "brand_new_v5.sqlite3"
        IdentityStore(fresh_db)
        with closing(sqlite3.connect(fresh_db)) as fdb:
            self.assertEqual(fdb.execute("SELECT version FROM retailops_schema WHERE component='identity'").fetchone()[0], 5)

        # Database CHECK constraint itself blocks activating viewer/platform_admin directly
        with self.assertRaises(sqlite3.IntegrityError), store.connection(write=True) as db:
            db.execute("UPDATE memberships SET active=1 WHERE id='m_view'")

        # Snapshot reader accepts identity v5 and preserves normalized disabled legacy memberships
        snap = read_database(legacy_path, "identity", IDENTITY_TABLES)
        snap_by_id = {r["id"]: r for r in snap["memberships"]}
        self.assertEqual(snap_by_id["m_view"]["active"], 0)
        self.assertEqual(snap_by_id["m_view"]["disabled_reason"], IDENTITY_V5_DISABLE_REASON)

        # Mocked PostgreSQL v4 -> v5 migration check (isolated, no network/live DB)
        executed_sql = []

        class _MockPg:
            def __init__(self, *, version=4, schema_exists=True):
                self.version = version
                self.schema_exists = schema_exists
                self.raw = self

            def execute(self, query, params=None):
                q = str(query)
                executed_sql.append((q, params))
                cur = MagicMock()
                if "pg_namespace" in q:
                    val = {"exists": 1} if self.schema_exists else None
                    cur.fetchone.return_value = val
                    cur.fetchall.return_value = [val] if val else []
                elif "SELECT component,version" in q or "SELECT version FROM retailops_schema" in q:
                    row_val = {"component": "identity", "version": self.version}
                    cur.fetchone.return_value = row_val
                    cur.fetchall.return_value = [row_val]
                elif "CREATE SCHEMA" in q:
                    self.schema_exists = True
                    cur.fetchone.return_value = None
                    cur.fetchall.return_value = []
                elif "INSERT INTO retailops_schema" in q:
                    self.version = params[1] if params else 5
                    cur.fetchone.return_value = None
                    cur.fetchall.return_value = []
                elif "UPDATE retailops_schema SET version=" in q:
                    self.version = params[0] if params else 5
                    cur.fetchone.return_value = None
                    cur.fetchall.return_value = []
                else:
                    cur.fetchone.return_value = None
                    cur.fetchall.return_value = []
                return cur

        from contextlib import contextmanager

        mock_psycopg = MagicMock()
        mock_psycopg.conninfo.conninfo_to_dict.return_value = {"dbname": "retailops", "user": "retailops"}
        mock_sql = MagicMock()
        mock_sql.SQL = lambda s: MagicMock(format=lambda *a, **kw: s)
        mock_sql.Identifier = lambda s: s
        mock_psycopg.sql = mock_sql
        pg_db = _MockPg(version=4, schema_exists=True)
        pg_dsn = "postgresql://retailops:secret@127.0.0.1:5432/retailops"

        @contextmanager
        def _fake_tx(dsn, schema=IDENTITY_SCHEMA, *, write=False, read_only=False):
            yield pg_db

        with patch.dict("sys.modules", {"psycopg": mock_psycopg, "psycopg.sql": mock_sql}), \
             patch("retailops.storage.pg_repositories.transaction", side_effect=_fake_tx), \
             patch("retailops.storage.postgres.transaction", side_effect=_fake_tx), \
             patch.dict(
                 os.environ,
                 {"RETAILOPS_STORAGE_BACKEND": "postgresql", "RETAILOPS_DATABASE_URL": pg_dsn},
                 clear=False,
             ):
            # 1. Startup, store construction, direct pg_initialize default, and ordinary CLI fail closed on PG v4 with zero DML/DDL
            for pg_fn in (
                lambda: pg_initialize(pg_db, IDENTITY_SCHEMA, "identity"),
                lambda: PostgresIdentityStore(pg_dsn, create=False),
                lambda: PostgresSessions(pg_dsn),
                lambda: identity_cli.run(
                    parser.parse_args(["identity", "set-role", "--membership", "m_cust", "--role", "staff"])
                ),
            ):
                with self.assertRaises(ApiError) as pg_mig_err:
                    pg_fn()
                self.assertEqual((pg_mig_err.exception.status, pg_mig_err.exception.code), (503, "identity_migration_required"))

            with self.assertRaises(ApiError) as pg_unconf:
                identity_cli.run(parser.parse_args(["identity", "migrate-v5", "--confirm-preflight"]))
            self.assertEqual((pg_unconf.exception.status, pg_unconf.exception.code), (400, "migration_confirmation_required"))

            self.assertEqual(pg_db.version, 4)
            blocked_sql = "\n".join(q for q, _ in executed_sql)
            self.assertNotIn("DELETE FROM sessions", blocked_sql)
            self.assertNotIn("retired_legacy_role_r1_w1", blocked_sql)
            self.assertNotIn("ALTER TABLE memberships", blocked_sql)

            # 2. Explicit operator migrate-v5 with confirmation flags upgrades PG v4 -> v5 and is idempotent
            executed_sql.clear()
            pg_mig_1 = identity_cli.run(
                parser.parse_args(["identity", "migrate-v5", "--confirm-preflight", "--confirm-backup"])
            )
            self.assertEqual(
                pg_mig_1,
                {"result": "IDENTITY_V5_MIGRATED", "backend": "postgresql", "schema_version": IDENTITY_SCHEMA_CURRENT, "upgraded": True},
            )
            self.assertEqual(pg_db.version, IDENTITY_SCHEMA_CURRENT)
            joined_sql = "\n".join(q for q, _ in executed_sql)
            self.assertIn("ADD COLUMN IF NOT EXISTS disabled_reason TEXT", joined_sql)
            self.assertIn("DELETE FROM sessions WHERE membership_id IN", joined_sql)
            self.assertIn("retired_legacy_role_r1_w1", joined_sql)

            executed_sql.clear()
            pg_mig_2 = migrate_postgres_identity_v5(pg_dsn, preflight_confirmed=True, backup_confirmed=True)
            self.assertEqual(pg_mig_2["upgraded"], False)
            self.assertNotIn("DELETE FROM sessions", "\n".join(q for q, _ in executed_sql))

            # 3. Brand-new empty PostgreSQL schema creates v5 directly
            empty_pg = _MockPg(version=0, schema_exists=False)

            @contextmanager
            def _fake_empty_tx(dsn, schema=IDENTITY_SCHEMA, *, write=False, read_only=False):
                yield empty_pg

            with patch("retailops.storage.pg_repositories.transaction", side_effect=_fake_empty_tx):
                PostgresIdentityStore(pg_dsn, create=True)
            self.assertEqual(empty_pg.version, IDENTITY_SCHEMA_CURRENT)


if __name__ == "__main__":
    unittest.main()
