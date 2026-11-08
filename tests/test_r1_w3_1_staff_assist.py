"""Phase R1 W3.1 isolated tests for Staff Desk operational & UX improvements (§15)."""
from __future__ import annotations

import io
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from retailops.core import ApiError
from retailops.http.public import PublicWeb
from retailops.identity.persistent import PersistentSessions
from legacy_seed_fixture import provision_legacy_unit_tenant


class PhaseR1W31BaseTestCase(unittest.TestCase):
    """Shared multi-role PersistentSessions + PublicWeb fixture for W3.1 tests."""

    ORIGIN = "https://retailops.example.com"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pers = self.root / "persistent"
        self.sessions = PersistentSessions(self.pers, data_mode="persistent-demo")
        self.sessions.customer_ref_key = "test-w31-customer-ref-key-0123456789abcdef"
        self.store_a = provision_legacy_unit_tenant(self.sessions, "shop-a", "Shop A")
        self.store_b = provision_legacy_unit_tenant(self.sessions, "shop-b", "Shop B")
        with self.store_a.connection(write=True) as db:
            db.execute(
                "INSERT INTO orders(id, customer_id, product_id, source_system, external_order_id, ordered_at, name, variant, amount, status, version, delivered_at) "
                "VALUES ('O-103', 'C-001', 'P-102', 'retailops_seed', 'O-103', 1759900000.0, 'Áo khoác Everyday', 'Xanh navy / L', 599000, 'delivered', 1, 1760000000.0)"
            )
            db.execute(
                "INSERT INTO orders(id, customer_id, product_id, source_system, external_order_id, ordered_at, name, variant, amount, status, version) "
                "VALUES ('O-104', 'C-001', 'P-101', 'retailops_seed', 'O-104', 1759900000.0, 'Áo thun Essential', 'Trắng / S', 299000, 'pending', 1)"
            )
        self.store_a.add_customer("C-STAFF-A1", "Nhân viên Lan")
        self.store_a.add_customer("C-STAFF-A2", "Nhân viên Hùng")
        self.store_a.add_customer("C-MGR-A", "Quản lý Minh")
        self.store_b.add_customer("C-STAFF-B", "Nhân viên Shop B")
        self.web = PublicWeb(self.ORIGIN, self.sessions)
        self.cust1 = self._issue_cookie("shop-a", "p-cust-1", "Khách 1", "C-001", "customer")
        self.cust2 = self._issue_cookie("shop-a", "p-cust-2", "Khách 2", "C-002", "customer")
        self.staff_a1 = self._issue_cookie("shop-a", "p-staff-a1", "Nhân viên Lan", "C-STAFF-A1", "staff")
        self.staff_a2 = self._issue_cookie("shop-a", "p-staff-a2", "Nhân viên Hùng", "C-STAFF-A2", "staff")
        self.mgr_a = self._issue_cookie("shop-a", "p-mgr-a", "Quản lý Minh", "C-MGR-A", "manager")
        self.staff_b = self._issue_cookie("shop-b", "p-staff-b", "Nhân viên Shop B", "C-STAFF-B", "staff")

    def _issue_cookie(self, tenant_id: str, principal_id: str, name: str, customer_id: str, role: str) -> str:
        mid = self.sessions.create_member(tenant_id, principal_id, name, customer_id, role)
        tok = secrets.token_urlsafe(32)
        self.sessions.control.register_credential(mid, tok)
        secret = self.sessions.login(tok)
        return f"{self.sessions.cookie_name}={secret}"

    def _req(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        cookie: str | None = None,
        headers: dict | None = None,
    ):
        raw = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        env = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "HTTP_HOST": "retailops.example.com",
            "wsgi.input": io.BytesIO(raw),
        }
        if method != "GET":
            env["HTTP_ORIGIN"] = self.ORIGIN
        if body is not None:
            env["CONTENT_TYPE"] = "application/json"
            env["CONTENT_LENGTH"] = str(len(raw))
        if cookie:
            env["HTTP_COOKIE"] = cookie
        for k, v in (headers or {}).items():
            env["HTTP_" + k.upper().replace("-", "_")] = v
        try:
            status, payload, _, _ = self.web.route(env)
            return status, payload
        except ApiError as err:
            return err.status, {"error": err.code, "message": err.message}


class PhaseR1W31Item1CaseMilestoneNoticesTests(PhaseR1W31BaseTestCase):
    """Item 1 (W3.1-D3): Persist case lifecycle milestones as sys-notice-* turns atomically."""

    def _sys_notice_turns(self, cid: str) -> list[dict]:
        with self.store_a.connection() as db:
            rows = db.execute(
                "SELECT id, request_id, input_hash, messages, result, created_at "
                "FROM agent_turns WHERE conversation_id = ? AND request_id LIKE 'sys-notice-%' ORDER BY id ASC",
                (cid,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["messages_obj"] = json.loads(d["messages"])
            d["result_obj"] = json.loads(d["result"])
            out.append(d)
        return out

    def test_item1_each_milestone_writes_single_turn_persists_on_reload_and_leaves_timers_untouched(self):
        st, conv = self._req("POST", "/api/conversations", {}, cookie=self.cust1)
        self.assertEqual(st, 201)
        cid = conv["conversation_id"]
        case_id = conv["case_id"]

        # Seed one regular bot turn first so we can verify history() & timer behavior
        snap = self.store_a.conversation("C-001", cid)
        self.store_a.finish_turn(
            "C-001",
            snap,
            "req-bot-1",
            "hash-bot-1",
            [
                {"role": "user", "content": "Cho em hỏi về đơn O-103"},
                {"role": "assistant", "content": "Đơn O-103 đã giao thành công."},
            ],
            {
                "message": "Đơn O-103 đã giao thành công.",
                "source": "store_data",
                "context": {"order_id": "O-103", "product_id": "P-102"},
                "trace": {"turn_id": "t-bot-1"},
            },
            {"O-103": 1},
        )
        self.assertEqual(len(self._sys_notice_turns(cid)), 0)

        # Milestone 1: Customer requests human handoff -> writes 1 sys-notice-handoff-* turn & clears bot timers
        st, fb = self._req(
            "POST",
            "/api/feedback",
            {"conversation_id": cid, "feedback_type": "human_handoff", "comment": "Cần gặp nhân viên tư vấn"},
            cookie=self.cust1,
        )
        self.assertEqual(st, 200)
        self.assertIsNotNone(fb.get("notice_turn_id"))
        notices = self._sys_notice_turns(cid)
        self.assertEqual(len(notices), 1)
        self.assertTrue(notices[0]["request_id"].startswith("sys-notice-handoff-"))
        self.assertEqual(notices[0]["result_obj"]["author"], "system_case_notice")
        self.assertEqual(notices[0]["result_obj"]["milestone"], "handoff_requested")

        # Duplicate handoff feedback while episode is already open must NOT append a second notice turn
        st_dup, _ = self._req(
            "POST",
            "/api/feedback",
            {"conversation_id": cid, "feedback_type": "human_handoff", "comment": "Nhắc lại"},
            cookie=self.cust1,
        )
        self.assertEqual(st_dup, 200)
        self.assertEqual(len(self._sys_notice_turns(cid)), 1)

        # Milestone 2: Staff 1 claims case -> writes 1 sys-notice-claim-* turn
        st, claimed = self._req("POST", f"/api/staff/cases/{case_id}/claim", {}, cookie=self.staff_a1)
        self.assertEqual(st, 200)
        self.assertIsNotNone(claimed.get("notice_turn_id"))
        notices = self._sys_notice_turns(cid)
        self.assertEqual(len(notices), 2)
        self.assertTrue(notices[1]["request_id"].startswith(f"sys-notice-claim-{case_id}-"))
        self.assertEqual(notices[1]["result_obj"]["milestone"], "case_claimed")
        self.assertIn("Nhân viên Lan", notices[1]["result_obj"]["message"])

        # Milestone 3: Staff 1 releases case -> writes 1 sys-notice-release-* turn
        st, released = self._req("POST", f"/api/staff/cases/{case_id}/release", {}, cookie=self.staff_a1)
        self.assertEqual(st, 200)
        self.assertIsNotNone(released.get("notice_turn_id"))
        notices = self._sys_notice_turns(cid)
        self.assertEqual(len(notices), 3)
        self.assertTrue(notices[2]["request_id"].startswith(f"sys-notice-release-{case_id}-"))
        self.assertEqual(notices[2]["result_obj"]["milestone"], "case_released")
        self.assertIn("Nhân viên Lan", notices[2]["result_obj"]["message"])

        # Staff 2 claims and resolves case -> writes claim + resolve notices
        st, claimed2 = self._req("POST", f"/api/staff/cases/{case_id}/claim", {}, cookie=self.staff_a2)
        self.assertEqual(st, 200)
        self.assertEqual(len(self._sys_notice_turns(cid)), 4)

        # Milestone 4: Staff 2 resolves case -> writes 1 sys-notice-resolve-* turn
        st, resolved = self._req(
            "POST",
            "/api/staff/resolve",
            {"case_id": case_id, "handoff_id": claimed2["handoff_id"]},
            cookie=self.staff_a2,
        )
        self.assertEqual(st, 200)
        self.assertIsNotNone(resolved.get("notice_turn_id"))
        notices = self._sys_notice_turns(cid)
        self.assertEqual(len(notices), 5)
        self.assertTrue(notices[4]["request_id"].startswith(f"sys-notice-resolve-{case_id}-"))
        self.assertEqual(notices[4]["result_obj"]["milestone"], "case_resolved")
        self.assertIn("Nhân viên Hùng", notices[4]["result_obj"]["message"])

        # Verify timers were NEVER refreshed by any sys-notice-* write
        with self.store_a.connection() as db:
            crow = db.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        self.assertIsNone(crow["awaiting_customer_since"])
        self.assertIsNone(crow["reminder_deadline"])
        self.assertIsNone(crow["inactivity_deadline"])
        self.assertIsNone(crow["completion_deadline"])

        # Verify transcript reload returns all 5 sys-notice-* turns for BOTH Customer and Staff Desk
        st_cust, cust_tr = self._req("GET", f"/api/conversations/{cid}/messages", cookie=self.cust1)
        self.assertEqual(st_cust, 200)
        cust_milestones = [
            json.loads(t["result"]).get("milestone")
            for t in cust_tr["turns"]
            if str(t.get("request_id") or "").startswith("sys-notice-")
        ]
        self.assertEqual(
            cust_milestones,
            ["handoff_requested", "case_claimed", "case_released", "case_claimed", "case_resolved"],
        )

        st_staff, staff_tr = self._req("GET", f"/api/staff/cases/{case_id}/messages", cookie=self.staff_a2)
        self.assertEqual(st_staff, 200)
        staff_milestones = [
            json.loads(t["result"]).get("milestone")
            for t in staff_tr["turns"]
            if str(t.get("request_id") or "").startswith("sys-notice-")
        ]
        self.assertEqual(
            staff_milestones,
            ["handoff_requested", "case_claimed", "case_released", "case_claimed", "case_resolved"],
        )

        # Verify model history & turn counts strictly exclude sys-notice-* turns
        model_hist = self.store_a.history("C-001", cid)
        self.assertEqual(len(model_hist), 2)  # Only the 1 user + 1 assistant message from finish_turn!
        for msg in model_hist:
            self.assertNotIn("nhận ca", msg["content"])
            self.assertNotIn("trả ca", msg["content"])
            self.assertNotIn("đóng ca", msg["content"])

        st_list, conv_list = self._req("GET", "/api/conversations", cookie=self.cust1)
        self.assertEqual(st_list, 200)
        matched = next(c for c in conv_list["conversations"] if c["id"] == cid)
        self.assertEqual(matched["turns_count"], 1)
        self.assertTrue(matched["has_case_notices"])

        # On a fresh conversation with ONLY handoff notice (0 chat turns), has_turns() is False & turns_count == 0
        st2, conv2 = self._req("POST", "/api/conversations", {}, cookie=self.cust1)
        self.assertEqual(st2, 201)
        cid2 = conv2["conversation_id"]
        self.store_a.request_human_handoff("C-001", cid2, reason_code="customer_requested_human")
        self.assertFalse(self.store_a.has_turns("C-001", cid2))
        self.assertEqual(self.store_a.history("C-001", cid2), [])
        st_list2, conv_list2 = self._req("GET", "/api/conversations", cookie=self.cust1)
        self.assertEqual(st_list2, 200)
        matched2 = next(c for c in conv_list2["conversations"] if c["id"] == cid2)
        self.assertEqual(matched2["turns_count"], 0)
        self.assertTrue(matched2["has_case_notices"])

    def test_item1_transaction_rollback_leaves_zero_sys_notice_turns_across_all_milestones(self):
        st, conv = self._req("POST", "/api/conversations", {}, cookie=self.cust1)
        self.assertEqual(st, 201)
        cid = conv["conversation_id"]
        case_id = conv["case_id"]

        # 1) Handoff failure after _append_case_system_notice_in_tx -> 0 sys-notice turns & 0 handoff episodes
        with patch.object(self.store_a, "log", side_effect=sqlite3.OperationalError("simulated disk error")):
            with self.assertRaises(ApiError):
                self.store_a.request_human_handoff("C-001", cid, reason_code="customer_requested_human")
        self.assertEqual(self._sys_notice_turns(cid), [])
        with self.store_a.connection() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM handoff_episodes WHERE case_id = ?", (case_id,)).fetchone()[0], 0
            )

        # Now succeed handoff -> 1 notice turn
        handoff = self.store_a.request_human_handoff("C-001", cid, reason_code="customer_requested_human")
        self.assertEqual(len(self._sys_notice_turns(cid)), 1)

        # 2) Claim failure inside _append_case_system_notice_in_tx -> case stays waiting, still only 1 notice turn
        with patch.object(
            self.store_a,
            "_append_case_system_notice_in_tx",
            side_effect=sqlite3.OperationalError("simulated claim notice failure"),
        ):
            with self.assertRaises(ApiError):
                self.store_a.claim_case(
                    case_id,
                    staff_name="Nhân viên Lan",
                    actor={"principal_id": "p-staff-a1", "role": "staff", "tenant_id": "shop-a"},
                )
        self.assertEqual(len(self._sys_notice_turns(cid)), 1)
        with self.store_a.connection() as db:
            crow = db.execute("SELECT status, holder FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        self.assertEqual((crow["status"], crow["holder"]), ("waiting", None))

        # Succeed claim -> 2 notice turns
        self.store_a.claim_case(
            case_id,
            staff_name="Nhân viên Lan",
            actor={"principal_id": "p-staff-a1", "role": "staff", "tenant_id": "shop-a"},
        )
        self.assertEqual(len(self._sys_notice_turns(cid)), 2)

        # 3) Release failure inside _append_case_system_notice_in_tx -> case stays in_progress, still 2 notice turns
        with patch.object(
            self.store_a,
            "_append_case_system_notice_in_tx",
            side_effect=sqlite3.OperationalError("simulated release notice failure"),
        ):
            with self.assertRaises(ApiError):
                self.store_a.release_case(
                    case_id,
                    staff_name="Nhân viên Lan",
                    actor={"principal_id": "p-staff-a1", "role": "staff", "tenant_id": "shop-a"},
                )
        self.assertEqual(len(self._sys_notice_turns(cid)), 2)
        with self.store_a.connection() as db:
            crow = db.execute("SELECT status, holder FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        self.assertEqual((crow["status"], crow["holder"]), ("in_progress", "p-staff-a1"))

        # 4) Resolve failure inside _append_case_system_notice_in_tx -> case stays in_progress, still 2 notice turns
        with patch.object(
            self.store_a,
            "_append_case_system_notice_in_tx",
            side_effect=sqlite3.OperationalError("simulated resolve notice failure"),
        ):
            with self.assertRaises(ApiError):
                self.store_a.resolve_escalation(
                    cid,
                    "Nhân viên Lan",
                    actor={"principal_id": "p-staff-a1", "role": "staff", "tenant_id": "shop-a"},
                    case_id=case_id,
                    handoff_id=handoff["handoff_id"],
                )
        self.assertEqual(len(self._sys_notice_turns(cid)), 2)
        with self.store_a.connection() as db:
            crow = db.execute("SELECT status, holder FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        self.assertEqual((crow["status"], crow["holder"]), ("in_progress", "p-staff-a1"))


class PhaseR1W31Item2HeldSilenceBadgeTests(PhaseR1W31BaseTestCase):
    """Item 2 (W3.1-D2): Compute customer_silent_seconds on read for held cases; production rejects < 300s."""

    def test_item2_fake_clock_held_silence_threshold_reply_clear_no_holder_and_never_auto_closes(self):
        fake_now = [1_760_000_000.0]
        self.sessions.store_clock = lambda: fake_now[0]
        self.store_a.clock = lambda: fake_now[0]

        st, conv = self._req("POST", "/api/conversations", {}, cookie=self.cust1)
        self.assertEqual(st, 201)
        cid = conv["conversation_id"]
        case_id = conv["case_id"]

        # Customer opens handoff at t=0
        st, _ = self._req(
            "POST",
            "/api/feedback",
            {"conversation_id": cid, "feedback_type": "human_handoff", "comment": "Cần hỗ trợ"},
            cookie=self.cust1,
        )
        self.assertEqual(st, 200)

        # Unclaimed case without holder -> never flagged even after 600s
        fake_now[0] += 600.0
        st, desk0 = self._req("GET", "/api/staff/cases", cookie=self.staff_a1)
        self.assertEqual(st, 200)
        self.assertIsNone(desk0["waiting"][0]["customer_silent_seconds"])

        # Staff claims case at t=600, before sending any staff reply -> still None after another 400s
        st, _ = self._req("POST", f"/api/staff/cases/{case_id}/claim", {}, cookie=self.staff_a1)
        self.assertEqual(st, 200)
        fake_now[0] += 400.0
        st, desk_before_reply = self._req("GET", "/api/staff/cases", cookie=self.staff_a1)
        self.assertEqual(st, 200)
        self.assertIsNone(desk_before_reply["in_progress"][0]["customer_silent_seconds"])

        # Staff sends reply at t=1000
        st, _ = self._req(
            "POST",
            "/api/staff/reply",
            {"conversation_id": cid, "case_id": case_id, "message": "Dạ anh/chị muốn đổi sang size nào ạ?"},
            cookie=self.staff_a1,
        )
        self.assertEqual(st, 200)

        # Below threshold (299s < 300s default): customer_silent_seconds is None
        fake_now[0] += 299.0
        st, desk_below = self._req("GET", "/api/staff/cases", cookie=self.staff_a1)
        self.assertEqual(st, 200)
        self.assertIsNone(desk_below["in_progress"][0]["customer_silent_seconds"])
        st, tr_below = self._req("GET", f"/api/staff/cases/{case_id}/messages", cookie=self.staff_a1)
        self.assertEqual(st, 200)
        self.assertIsNone(tr_below["case"]["customer_silent_seconds"])

        # At/above threshold (425s >= 300s): customer_silent_seconds == 425 in both Staff Desk endpoints
        fake_now[0] += 126.0  # total 425s since staff reply
        turns_before_timer = len(tr_below["turns"])
        timer_res = self.store_a.process_due_case_timers(now=fake_now[0])
        self.assertEqual(timer_res["reminded"], 0)
        self.assertEqual(timer_res["resolved_inactivity"], 0)

        st, desk_above = self._req("GET", "/api/staff/cases", cookie=self.staff_a1)
        self.assertEqual(st, 200)
        self.assertEqual(desk_above["in_progress"][0]["customer_silent_seconds"], 425)
        self.assertEqual(desk_above["in_progress"][0]["status"], "in_progress")

        st, tr_above = self._req("GET", f"/api/staff/cases/{case_id}/messages", cookie=self.staff_a1)
        self.assertEqual(st, 200)
        self.assertEqual(tr_above["case"]["customer_silent_seconds"], 425)
        self.assertEqual(tr_above["case"]["status"], "in_progress")
        # Never sends reminder message to customer or auto-closes held case
        self.assertEqual(len(tr_above["turns"]), turns_before_timer)

        # If staff releases the case (no holder), customer_silent_seconds is None even though last chat was staff
        st, _ = self._req("POST", f"/api/staff/cases/{case_id}/release", {}, cookie=self.staff_a1)
        self.assertEqual(st, 200)
        st, desk_unheld = self._req("GET", "/api/staff/cases", cookie=self.staff_a1)
        self.assertEqual(st, 200)
        self.assertIsNone(desk_unheld["waiting"][0]["customer_silent_seconds"])
        st, tr_unheld = self._req("GET", f"/api/staff/cases/{case_id}/messages", cookie=self.staff_a1)
        self.assertEqual(st, 200)
        self.assertIsNone(tr_unheld["case"]["customer_silent_seconds"])

        # Re-claim -> silent seconds shows up again (since staff reply is still the latest chat turn!)
        st, re_claimed = self._req("POST", f"/api/staff/cases/{case_id}/claim", {}, cookie=self.staff_a1)
        self.assertEqual(st, 200)
        self.assertEqual(re_claimed["case"]["customer_silent_seconds"], 425)

        # Customer replies -> badge/silent seconds immediately clears to None!
        fake_now[0] += 10.0
        st, _ = self._req(
            "POST",
            "/api/staff/customer-message",
            {"conversation_id": cid, "message": "Dạ cho mình đổi sang size XL nhé"},
            cookie=self.cust1,
        )
        self.assertEqual(st, 200)
        fake_now[0] += 600.0  # Even 10 minutes after customer reply, customer is NOT silent (waiting on staff!)
        st, desk_after_cust = self._req("GET", "/api/staff/cases", cookie=self.staff_a1)
        self.assertEqual(st, 200)
        self.assertIsNone(desk_after_cust["in_progress"][0]["customer_silent_seconds"])
        st, tr_after_cust = self._req("GET", f"/api/staff/cases/{case_id}/messages", cookie=self.staff_a1)
        self.assertEqual(st, 200)
        self.assertIsNone(tr_after_cust["case"]["customer_silent_seconds"])

    def test_item2_env_config_and_production_rejects_shortened_held_silence_seconds(self):
        from retailops.config import CaseTimerConfig, DEFAULT_CASE_HELD_SILENCE_SECONDS, Settings

        self.assertEqual(DEFAULT_CASE_HELD_SILENCE_SECONDS, 300.0)
        # Non-production evaluation mode permits shorter threshold
        eval_cfg = CaseTimerConfig(held_silence_seconds=45, data_mode="persistent-demo", production_env=False)
        self.assertEqual(eval_cfg.held_silence_seconds, 45.0)

        # Production/live mode strictly rejects < 300s via CaseTimerConfig AND Settings.from_environment
        with self.assertRaises(ValueError):
            CaseTimerConfig(held_silence_seconds=299, data_mode="live", production_env=False)
        with self.assertRaises(ValueError):
            CaseTimerConfig(held_silence_seconds=120, data_mode="persistent-demo", production_env=True)
        with self.assertRaises(ValueError):
            Settings.from_environment(
                "public",
                {
                    "RETAILOPS_DATA_MODE": "live",
                    "RETAILOPS_PUBLIC_ORIGIN": "https://retailops.example.com",
                    "RETAILOPS_CASE_HELD_SILENCE_SECONDS": "60",
                },
            )
        ok_prod = Settings.from_environment(
            "public",
            {
                "RETAILOPS_DATA_MODE": "live",
                "RETAILOPS_PUBLIC_ORIGIN": "https://retailops.example.com",
                "RETAILOPS_CASE_HELD_SILENCE_SECONDS": "300",
            },
        )
        self.assertEqual(ok_prod.case_timer_config.held_silence_seconds, 300.0)


class PhaseR1W31Item3StaffConsentedOrderActionsTests(PhaseR1W31BaseTestCase):
    """Item 3 (W3.1-D1): Staff creates customer-consented order action requests; consent & authority enforced."""

    def test_item3_case_orders_endpoint_and_consent_turn_validations_and_staff_holder_rules(self):
        fake_now = [1_760_100_000.0]
        self.sessions.store_clock = lambda: fake_now[0]
        self.store_a.clock = lambda: fake_now[0]

        with self.store_a.connection(write=True) as db:
            db.execute(
                "INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version, source_system, external_order_id, ordered_at) "
                "VALUES ('O-105', 'C-001', 'P-101', 'Áo thun Essential', 'Đen / M', 299000, 'cancelled', 1, 'retailops_seed', 'O-105', 1760000000.0)"
            )
            db.execute(
                "INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version, delivered_at, source_system, external_order_id, ordered_at) "
                "VALUES ('O-106', 'C-001', 'P-102', 'Áo khoác Everyday', 'Đen / XL', 599000, 'delivered', 1, 1760050000.0, 'retailops_seed', 'O-106', 1760000000.0)"
            )

        # Open conversation 1 for cust1 and seed a bot turn
        st, conv1 = self._req("POST", "/api/conversations", {}, cookie=self.cust1)
        self.assertEqual(st, 201)
        cid1 = conv1["conversation_id"]
        case1 = conv1["case_id"]
        snap1 = self.store_a.conversation("C-001", cid1)
        bot_turn_id = self.store_a.finish_turn(
            "C-001",
            snap1,
            "req-bot-item3",
            "hash-bot-item3",
            [
                {"role": "user", "content": "Mình muốn hủy đơn O-104 luôn nha"},
                {"role": "assistant", "content": "Bạn có thể gặp nhân viên hỗ trợ để được xử lý."},
            ],
            {
                "message": "Bạn có thể gặp nhân viên hỗ trợ để được xử lý.",
                "source": "store_data",
                "context": {"order_id": "O-104", "product_id": "P-101"},
                "trace": {"turn_id": "t-bot-item3"},
            },
            {"O-104": 1},
        )

        # Open a second conversation (different case) with a customer message
        st, conv_other = self._req("POST", "/api/conversations", {}, cookie=self.cust1)
        self.assertEqual(st, 201)
        cid_other = conv_other["conversation_id"]
        self._req(
            "POST",
            "/api/feedback",
            {"conversation_id": cid_other, "feedback_type": "human_handoff", "comment": "Ca khác"},
            cookie=self.cust1,
        )
        st, other_msg = self._req(
            "POST",
            "/api/staff/customer-message",
            {"conversation_id": cid_other, "message": "Ok đồng ý hủy bên ca khác"},
            cookie=self.cust1,
        )
        self.assertEqual(st, 200)
        other_case_turn_id = other_msg["turn_id"]

        # Handoff & customer consent in opening #1 of case1, then resolve & reopen to test previous-opening rejection
        st, handoff1 = self._req(
            "POST",
            "/api/feedback",
            {"conversation_id": cid1, "feedback_type": "human_handoff", "comment": "Hỗ trợ đơn"},
            cookie=self.cust1,
        )
        self.assertEqual(st, 200)
        sys_notice_turn_id = handoff1["notice_turn_id"]

        st, prev_open_msg = self._req(
            "POST",
            "/api/staff/customer-message",
            {"conversation_id": cid1, "message": "Ok đồng ý ở lần mở ca cũ"},
            cookie=self.cust1,
        )
        self.assertEqual(st, 200)
        prev_opening_turn_id = prev_open_msg["turn_id"]

        st, claim_open1 = self._req("POST", f"/api/staff/cases/{case1}/claim", {}, cookie=self.staff_a1)
        self.assertEqual(st, 200)
        st, _ = self._req(
            "POST",
            "/api/staff/resolve",
            {"case_id": case1, "handoff_id": claim_open1["handoff_id"]},
            cookie=self.staff_a1,
        )
        self.assertEqual(st, 200)

        # Reopen case1 (opening #2)
        fake_now[0] += 60.0
        st, _ = self._req("POST", f"/api/conversations/{cid1}/resume", {}, cookie=self.cust1)
        self.assertEqual(st, 200)

        # Customer sends an old message in opening #2 that will expire (> 30 min)
        st, handoff2_early = self._req(
            "POST",
            "/api/feedback",
            {"conversation_id": cid1, "feedback_type": "human_handoff", "comment": "Mở lại ca"},
            cookie=self.cust1,
        )
        self.assertEqual(st, 200)
        st, expired_msg = self._req(
            "POST",
            "/api/staff/customer-message",
            {"conversation_id": cid1, "message": "Ok đồng ý lúc trước (sẽ quá 30 phút)"},
            cookie=self.cust1,
        )
        self.assertEqual(st, 200)
        expired_turn_id = expired_msg["turn_id"]

        # Advance 30 min + 5s so expired_turn_id is > 1800s old
        fake_now[0] += 1805.0

        # Seed a recent bot turn in opening #2 within the 30m window to verify bot turn rejection
        snap2 = self.store_a.conversation("C-001", cid1)
        bot_turn_id = self.store_a.finish_turn(
            "C-001",
            snap2,
            "req-bot-item3-open2",
            "hash-bot-item3-open2",
            [
                {"role": "user", "content": "Hủy đơn O-104 giúp mình"},
                {"role": "assistant", "content": "Đang chờ nhân viên hỗ trợ xử lý."},
            ],
            {
                "message": "Đang chờ nhân viên hỗ trợ xử lý.",
                "source": "store_data",
                "context": {"order_id": "O-104", "product_id": "P-101"},
                "trace": {"turn_id": "t-bot-item3-open2"},
            },
            {"O-104": 1},
        )

        # Customer sends a fresh consent message in opening #2
        st, fresh_msg = self._req(
            "POST",
            "/api/staff/customer-message",
            {"conversation_id": cid1, "message": "Ok shop hủy đơn O-104 và đổi size O-103 giúp mình nhé"},
            cookie=self.cust1,
        )
        self.assertEqual(st, 200)
        valid_consent_turn_id = fresh_msg["turn_id"]

        # Unclaimed case: Staff 1 cannot create consented request before claiming (409 case_not_claimed)
        st_unclaimed, err_unclaimed = self._req(
            "POST",
            f"/api/staff/cases/{case1}/order-actions",
            {
                "order_id": "O-104",
                "expected_order_version": 1,
                "type": "cancel",
                "reason_code": "changed_mind",
                "consent_turn_id": valid_consent_turn_id,
            },
            cookie=self.staff_a1,
        )
        self.assertEqual(st_unclaimed, 409)
        self.assertEqual(err_unclaimed["error"], "case_not_claimed")

        # Customer cannot call staff endpoints (403); cross-tenant staff blocked (403/404)
        st_cust_forbid, _ = self._req("GET", f"/api/staff/cases/{case1}/orders", cookie=self.cust1)
        self.assertEqual(st_cust_forbid, 403)
        st_cust_post, _ = self._req(
            "POST",
            f"/api/staff/cases/{case1}/order-actions",
            {
                "order_id": "O-104",
                "expected_order_version": 1,
                "type": "cancel",
                "reason_code": "changed_mind",
                "consent_turn_id": valid_consent_turn_id,
            },
            cookie=self.cust1,
        )
        self.assertEqual(st_cust_post, 403)
        st_cross, _ = self._req("GET", f"/api/staff/cases/{case1}/orders", cookie=self.staff_b)
        self.assertIn(st_cross, (403, 404))

        # Staff 1 claims case1 and sends a staff reply
        st, claim_open2 = self._req("POST", f"/api/staff/cases/{case1}/claim", {}, cookie=self.staff_a1)
        self.assertEqual(st, 200)
        sys_notice_turn_id = claim_open2["notice_turn_id"]
        fake_now[0] += 5.0
        st, staff_rep = self._req(
            "POST",
            "/api/staff/reply",
            {"conversation_id": cid1, "case_id": case1, "message": "Dạ shop tạo yêu cầu ngay cho mình ạ"},
            cookie=self.staff_a1,
        )
        self.assertEqual(st, 200)
        with self.store_a.connection() as db:
            staff_turn_id = db.execute(
                "SELECT id FROM agent_turns WHERE conversation_id = ? AND request_id = ?",
                (cid1, staff_rep["request_id"]),
            ).fetchone()["id"]

        # Verify GET /api/staff/cases/<case_id>/orders returns customer orders with allowed_action_types & valid consent_turns
        st_ords, ords_payload = self._req("GET", f"/api/staff/cases/{case1}/orders", cookie=self.staff_a1)
        self.assertEqual(st_ords, 200)
        by_oid = {o["id"]: o for o in ords_payload["orders"]}
        self.assertEqual(by_oid["O-104"]["allowed_action_types"], ["cancel"])
        self.assertEqual(by_oid["O-103"]["allowed_action_types"], ["return", "exchange"])
        self.assertEqual(by_oid["O-105"]["allowed_action_types"], [])
        self.assertIsNone(by_oid["O-104"]["open_order_action"])
        # Only the fresh customer consent turn from current opening within 30m appears in consent_turns!
        self.assertEqual([t["turn_id"] for t in ords_payload["consent_turns"]], [valid_consent_turn_id])
        self.assertIn("Ok shop hủy đơn O-104", ords_payload["consent_turns"][0]["excerpt"])

        # Non-holding Staff 2 is blocked (409 case_held_by_other)
        st_other_staff, err_other_staff = self._req(
            "POST",
            f"/api/staff/cases/{case1}/order-actions",
            {
                "order_id": "O-104",
                "expected_order_version": 1,
                "type": "cancel",
                "reason_code": "changed_mind",
                "consent_turn_id": valid_consent_turn_id,
            },
            cookie=self.staff_a2,
        )
        self.assertEqual(st_other_staff, 409)
        self.assertEqual(err_other_staff["error"], "case_held_by_other")

        # Reject missing or invalid consent_turn_id (missing, bot turn, staff turn, system turn, other case, previous opening, >30m)
        bad_turn_cases = [
            ("missing", None, "invalid_consent_turn"),
            ("bot_turn", bot_turn_id, "consent_turn_not_customer"),
            ("staff_turn", staff_turn_id, "consent_turn_not_customer"),
            ("sys_notice_turn", sys_notice_turn_id, "consent_turn_not_customer"),
            ("other_case_turn", other_case_turn_id, "invalid_consent_turn"),
            ("previous_opening_turn", prev_opening_turn_id, "invalid_consent_turn"),
            ("expired_30m_turn", expired_turn_id, "consent_turn_expired"),
        ]
        for label, bad_tid, expected_code in bad_turn_cases:
            payload = {
                "order_id": "O-104",
                "expected_order_version": 1,
                "type": "cancel",
                "reason_code": "changed_mind",
            }
            if bad_tid is not None:
                payload["consent_turn_id"] = bad_tid
            st_bad, err_bad = self._req(
                "POST", f"/api/staff/cases/{case1}/order-actions", payload, cookie=self.staff_a1
            )
            self.assertEqual(st_bad, 400, msg=f"{label} should return 400, got {st_bad}: {err_bad}")
            self.assertEqual(err_bad["error"], expected_code, msg=f"{label} wrong error code: {err_bad}")

    def test_item3_successful_creation_audit_submit_decision_outbox_409_conflict_and_staff_approval(self):
        fake_now = [1_760_200_000.0]
        self.sessions.store_clock = lambda: fake_now[0]
        self.store_a.clock = lambda: fake_now[0]

        with self.store_a.connection(write=True) as db:
            db.execute(
                "INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version, delivered_at, source_system, external_order_id, ordered_at) "
                "VALUES ('O-106', 'C-001', 'P-102', 'Áo khoác Everyday', 'Đen / XL', 599000, 'delivered', 1, 1760150000.0, 'retailops_seed', 'O-106', 1760000000.0)"
            )

        st, conv = self._req("POST", "/api/conversations", {}, cookie=self.cust1)
        self.assertEqual(st, 201)
        cid = conv["conversation_id"]
        case_id = conv["case_id"]

        self._req(
            "POST",
            "/api/feedback",
            {"conversation_id": cid, "feedback_type": "human_handoff", "comment": "Hỗ trợ đổi/hủy"},
            cookie=self.cust1,
        )
        self._req("POST", f"/api/staff/cases/{case_id}/claim", {}, cookie=self.staff_a1)
        self._req(
            "POST",
            "/api/staff/reply",
            {"conversation_id": cid, "case_id": case_id, "message": "Shop hỗ trợ hủy O-104 và đổi size O-103 cho mình nhé?"},
            cookie=self.staff_a1,
        )
        fake_now[0] += 15.0
        st, cust_consent = self._req(
            "POST",
            "/api/staff/customer-message",
            {"conversation_id": cid, "message": "Được nha shop, làm giúp mình luôn"},
            cookie=self.cust1,
        )
        self.assertEqual(st, 200)
        consent_tid = cust_consent["turn_id"]

        # 1) Holding Staff creates cancel request on O-104 with customer consent
        st_create, created = self._req(
            "POST",
            f"/api/staff/cases/{case_id}/order-actions",
            {
                "order_id": "O-104",
                "expected_order_version": 1,
                "type": "cancel",
                "reason_code": "changed_mind",
                "reason_text": "Khách đồng ý hủy qua chat",
                "consent_turn_id": consent_tid,
            },
            cookie=self.staff_a1,
        )
        self.assertEqual(st_create, 201)
        req_cancel_id = created["order_action_request_id"]
        self.assertEqual(created["order_action"]["raised_by_role"], "customer")
        self.assertEqual(created["consent_turn_id"], consent_tid)
        self.assertIn("Được nha shop", created["consent_excerpt"])

        # Verify submit row in order_action_decisions, business_events audit, and integration_outbox actor
        with self.store_a.connection() as db:
            dec_row = db.execute(
                "SELECT * FROM order_action_decisions WHERE request_id = ? AND action = 'submit'",
                (req_cancel_id,),
            ).fetchone()
            ev_row = db.execute(
                "SELECT payload FROM business_events WHERE kind = 'order_action_requested' AND order_id = 'O-104' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            outbox_row = db.execute(
                "SELECT payload_json FROM integration_outbox WHERE event_type = 'cancel_requested' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()

        self.assertEqual(dec_row["actor_principal_id"], "p-staff-a1")
        self.assertEqual(dec_row["actor_role"], "staff")
        self.assertIn(f"[consent_turn_id={consent_tid}]", dec_row["note"])
        self.assertIn("Được nha shop", dec_row["note"])

        ev_payload = json.loads(ev_row["payload"])
        self.assertEqual(ev_payload["raised_by_role"], "customer")
        self.assertEqual(ev_payload["consent_turn_id"], consent_tid)
        self.assertIn("Được nha shop", ev_payload["consent_excerpt"])
        self.assertEqual(ev_payload["actor"]["principal_id"], "p-staff-a1")
        self.assertEqual(ev_payload["actor"]["role"], "staff")

        outbox_payload = json.loads(outbox_row["payload_json"])
        outbox_actor = outbox_payload["actor"]
        self.assertEqual(outbox_payload["order_action_request_id"], req_cancel_id)
        self.assertEqual(outbox_actor["principal_id"], "p-staff-a1")
        self.assertEqual(outbox_actor["role"], "staff")
        self.assertEqual(outbox_payload["consent_turn_id"], consent_tid)
        self.assertNotIn("Được nha shop", outbox_row["payload_json"])  # Zero raw chat PII in outbox

        # 2) Creating a second request on O-104 while open -> 409 order_action_conflict
        st_dup, err_dup = self._req(
            "POST",
            f"/api/staff/cases/{case_id}/order-actions",
            {
                "order_id": "O-104",
                "expected_order_version": 1,
                "type": "cancel",
                "reason_code": "ordered_by_mistake",
                "consent_turn_id": consent_tid,
            },
            cookie=self.staff_a1,
        )
        self.assertEqual(st_dup, 409)
        self.assertEqual(err_dup["error"], "order_action_conflict")

        # GET /api/staff/cases/<case_id>/orders reflects open_order_action on O-104
        st_ords, ords_after = self._req("GET", f"/api/staff/cases/{case_id}/orders", cookie=self.staff_a1)
        self.assertEqual(st_ords, 200)
        o104 = next(o for o in ords_after["orders"] if o["id"] == "O-104")
        self.assertEqual(o104["open_order_action"]["request_id"], req_cancel_id)

        # 3) Holding Staff CAN approve the customer-consented cancel request (unlike delivery-failure cancel!)
        st_app, approved = self._req(
            "POST",
            f"/api/order-actions/{req_cancel_id}/approve",
            {"version": created["order_action"]["version"], "note": "Nhân viên duyệt hủy theo đồng ý khách"},
            cookie=self.staff_a1,
        )
        self.assertEqual(st_app, 200)
        self.assertEqual(approved["order_action"]["status"], "approved")
        self.assertEqual(approved["order"]["status"], "cancelled")

        # 4) Holding Staff creates exchange (same_variant) on O-103 AND Manager creates return on O-106; Staff approves & completes exchange
        st_ex, ex_created = self._req(
            "POST",
            f"/api/staff/cases/{case_id}/order-actions",
            {
                "order_id": "O-103",
                "expected_order_version": 1,
                "type": "exchange",
                "exchange_kind": "same_variant",
                "reason_code": "defective_item",
                "consent_turn_id": consent_tid,
            },
            cookie=self.staff_a1,
        )
        self.assertEqual(st_ex, 201)
        ex_id = ex_created["order_action_request_id"]
        self.assertEqual(ex_created["order_action"]["raised_by_role"], "customer")
        self.assertEqual(ex_created["order_action"]["exchange_kind"], "same_variant")

        st_ex_app, ex_app = self._req(
            "POST",
            f"/api/order-actions/{ex_id}/approve",
            {"version": ex_created["order_action"]["version"], "note": "Duyệt đổi size"},
            cookie=self.staff_a1,
        )
        self.assertEqual(st_ex_app, 200)
        self.assertEqual(ex_app["order_action"]["status"], "approved")

        # Manager can also create consented return on O-106 even while staff_a1 holds the case
        st_mgr, mgr_created = self._req(
            "POST",
            f"/api/staff/cases/{case_id}/order-actions",
            {
                "order_id": "O-106",
                "expected_order_version": 1,
                "type": "return",
                "reason_code": "defective_item",
                "consent_turn_id": consent_tid,
            },
            cookie=self.mgr_a,
        )
        self.assertEqual(st_mgr, 201)
        self.assertEqual(mgr_created["order_action"]["raised_by_role"], "customer")

    def test_postgres_psycopg_placeholder_safety_for_w3_1_queries(self):
        """Ensure W3.1 LIKE / NOT LIKE queries never pass unescaped '%' literals to psycopg."""
        import contextlib
        import re
        from retailops.storage.postgres import Queries

        store = self.store_a
        st, conv = self._req("POST", "/api/conversations", {}, cookie=self.cust1)
        self.assertEqual(st, 201)
        cid = conv["conversation_id"]
        case_id = conv["case_id"]
        self._req(
            "POST",
            "/api/feedback",
            {"conversation_id": cid, "feedback_type": "human_handoff", "comment": "Cần hỗ trợ"},
            cookie=self.cust1,
        )
        st_claim, _ = self._req(
            "POST", f"/api/staff/cases/{case_id}/claim", {}, cookie=self.staff_a1
        )
        self.assertEqual(st_claim, 200)
        self._req(
            "POST",
            "/api/staff/reply",
            {"conversation_id": cid, "message": "Em đang kiểm tra đơn ạ."},
            cookie=self.staff_a1,
        )
        self._req(
            "POST",
            "/api/staff/customer-message",
            {"conversation_id": cid, "message": "ok anh đồng ý hủy O-104"},
            cookie=self.cust1,
        )
        consent_tid = store.conversation_transcript(cid)["turns"][-1]["id"]

        orig_conn = store.connection

        class _PsycopgStrictRaw:
            def __init__(self, sqlite_conn):
                self._sqlite = sqlite_conn

            def execute(self, pg_sql, parameters=()):
                tokens = re.findall(r"%.", pg_sql)
                for tok in tokens:
                    if tok != "%s":
                        raise AssertionError(f"Unescaped '%' token {tok!r} in SQL: {pg_sql}")
                expected = len(parameters or ())
                if len(tokens) != expected:
                    raise AssertionError(
                        f"Placeholder count mismatch ({len(tokens)} != {expected}) in SQL: {pg_sql}"
                    )
                sqlite_sql = pg_sql.replace("%s", "?")
                return self._sqlite.execute(sqlite_sql, parameters)

        @contextlib.contextmanager
        def strict_connection(*args, **kwargs):
            with orig_conn(*args, **kwargs) as db:
                yield Queries(_PsycopgStrictRaw(db))

        store.connection = strict_connection
        try:
            st_convs, convs = self._req("GET", "/api/conversations", cookie=self.cust1)
            self.assertEqual(st_convs, 200)
            self.assertEqual(len(convs["conversations"]), 1)
            st_cases, cases = self._req("GET", "/api/staff/cases", cookie=self.staff_a1)
            self.assertEqual(st_cases, 200)
            self.assertEqual(len(cases["in_progress"]), 1)
            st_escs, escs = self._req("GET", "/api/staff/escalations", cookie=self.staff_a1)
            self.assertEqual(st_escs, 200)
            self.assertEqual(len(escs["escalations"]), 1)
            st_det, detail = self._req("GET", f"/api/staff/cases/{case_id}/messages", cookie=self.staff_a1)
            self.assertEqual(st_det, 200)
            self.assertEqual(detail["case"]["case_id"], case_id)
            st_ord, orders_res = self._req("GET", f"/api/staff/cases/{case_id}/orders", cookie=self.staff_a1)
            self.assertEqual(st_ord, 200)
            self.assertGreaterEqual(len(orders_res["orders"]), 1)
            st_create, created = self._req(
                "POST",
                f"/api/staff/cases/{case_id}/order-actions",
                {
                    "order_id": "O-104",
                    "expected_order_version": 1,
                    "type": "cancel",
                    "reason_code": "changed_mind",
                    "consent_turn_id": consent_tid,
                },
                cookie=self.staff_a1,
            )
            self.assertEqual(st_create, 201)
            self.assertEqual(created["order_action"]["raised_by_role"], "customer")
        finally:
            store.connection = orig_conn


if __name__ == "__main__":
    unittest.main()
