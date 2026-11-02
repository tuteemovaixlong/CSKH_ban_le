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


class PhaseR1W31BaseTestCase(unittest.TestCase):
    """Shared multi-role PersistentSessions + PublicWeb fixture for W3.1 tests."""

    ORIGIN = "https://retailops.example.com"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pers = self.root / "persistent"
        self.sessions = PersistentSessions(self.pers, data_mode="persistent-demo")
        self.store_a = self.sessions.provision_tenant("shop-a", "Shop A", seed_demo=True)
        self.store_b = self.sessions.provision_tenant("shop-b", "Shop B", seed_demo=True)
        with self.store_a.connection(write=True) as db:
            db.execute(
                "INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version, delivered_at) "
                "VALUES ('O-103', 'C-001', 'P-102', 'Áo khoác Everyday', 'Xanh navy / L', 599000, 'delivered', 1, 1760000000.0)"
            )
            db.execute(
                "INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version) "
                "VALUES ('O-104', 'C-001', 'P-101', 'Áo thun Essential', 'Trắng / S', 299000, 'pending', 1)"
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


if __name__ == "__main__":
    unittest.main()
