"""Item 6 tests (W6.1b-2-D5): Tighten refund.updated auto-linking rules.

Covers:
- Request A is closed, customer opens Request B -> late refund of A does NOT link to B
  (neither when B is unapproved nor when B is approved after A's refund was initiated).
- Refund amount exceeding requested order amount does NOT link; Staff Desk warns.
- Refund timestamp not strictly after refund approval timestamp does NOT link; Staff Desk warns.
- Valid refund (approved waiting request, amount <= order amount, initiated_at > approved_at) links;
  duplicate/replay/subsequent status events never overwrite an existing request_id link.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from retailops.business.application import Application
from retailops.business.permissions import MANAGER, READ, STAFF
from retailops.http.routes import api_result
from retailops.identity.contracts import RequestContext
from retailops.identity.persistent import PersistentSessions
from retailops.integration.connectors import ConnectorManager
from retailops.integration.ingest import IntegrationIngestService

VN_TZ = timezone(timedelta(hours=7))
BASE_DT = datetime(2026, 11, 8, 8, 0, 0, tzinfo=VN_TZ)


def _iso_at(offset_seconds: float) -> str:
    return (BASE_DT + timedelta(seconds=offset_seconds)).isoformat(timespec="seconds")


def _epoch_at(offset_seconds: float) -> float:
    return (BASE_DT + timedelta(seconds=offset_seconds)).timestamp()


class RefundLinkingItem6Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="r1-w61b2-item6-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.secrets_dir = self.root / "secrets"
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        (self.secrets_dir / "retailops_connector_marketplace_sim").write_bytes(b"k" * 32)
        self.digest_file = self.root / "digest_key"
        self.digest_file.write_bytes(b"d" * 32)
        self.recipient_file = self.root / "recipient_key"
        self.recipient_file.write_bytes(b"r" * 32)

        self.env_patcher = patch.dict(
            os.environ,
            {
                "RETAILOPS_CONNECTOR_SECRETS_DIR": str(self.secrets_dir),
                "RETAILOPS_EVENT_DIGEST_KEY_FILE": str(self.digest_file),
                "RETAILOPS_RECIPIENT_KEY_FILE": str(self.recipient_file),
            },
            clear=False,
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

        self.sessions = PersistentSessions(self.root / "tenants")
        self.store = self.sessions.provision_tenant("shop-i6", "Shop Item 6", seed_demo=False)
        self.mgr = ConnectorManager(self.sessions)
        self.mgr.add_connector(
            "shop-i6",
            source_system="marketplace_sim",
            kind="marketplace",
            merchant_id="MERCHANT-SIM-001",
            secret_ref="retailops_connector_marketplace_sim",
        )
        self.store.seed_catalog()
        self.svc = IntegrationIngestService(self.sessions, digest_key=b"d" * 32)
        self.manager_actor = {
            "principal_id": "p_mgr_i6",
            "role": "manager",
            "tenant_id": "shop-i6",
        }
        self.mgr_ctx = RequestContext(
            customer_id="C-MGR-I6",
            role="manager",
            permissions=frozenset({READ, STAFF, MANAGER}),
            tenant_id="shop-i6",
            principal_id="p_mgr_i6",
            membership_id="m_mgr_i6",
            display_name="Manager Item 6",
            authenticated_session=True,
        )

    def _ingest_raw(self, ev: dict):
        raw = json.dumps(ev, ensure_ascii=False).encode("utf-8")
        return self.svc.ingest_event(raw, tenant_id="shop-i6", received_via="import")

    def _seed_order(
        self,
        ext_oid: str,
        ext_cid: str,
        *,
        amount_subtotal: int = 239000,
        shipping_fee: int = 20000,
        extra_paid_amount: int = 0,
    ) -> tuple[str, str]:
        total = amount_subtotal + shipping_fee
        self._ingest_raw(
            {
                "contract": "retailops-integration-v2",
                "event_id": f"ev-cust-{ext_oid}",
                "event_type": "customer.upserted",
                "occurred_at": _iso_at(0),
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 1,
                "data": {"external_customer_id": ext_cid, "display_name": "Khách Kiểm Thử Mục 6"},
            }
        )
        res_ord = self._ingest_raw(
            {
                "contract": "retailops-integration-v2",
                "event_id": f"ev-ord-{ext_oid}",
                "event_type": "order.created",
                "occurred_at": _iso_at(60),
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 1,
                "data": {
                    "external_order_id": ext_oid,
                    "external_customer_id": ext_cid,
                    "ordered_at": _iso_at(60),
                    "promised_delivery_by": _iso_at(86400 * 2),
                    "currency": "VND",
                    "payment_method": "bank_transfer",
                    "items": [
                        {
                            "sku": "SKU-P101-TRANG-M",
                            "external_product_id": "P-101",
                            "title": "Áo sơ mi lụa công sở",
                            "variant_name": "Trắng · Size M",
                            "quantity": 1,
                            "unit_price": amount_subtotal,
                        }
                    ],
                    "shipping_fee": shipping_fee,
                    "total": total,
                    "recipient": {
                        "name": "Trần Minh Anh",
                        "phone": "0901234567",
                        "address_line": "10 Nguyễn Huệ",
                        "ward": "Phường Bến Nghé",
                        "district": "Quận 1",
                        "province": "TP. Hồ Chí Minh",
                    },
                },
            }
        )
        self._ingest_raw(
            {
                "contract": "retailops-integration-v2",
                "event_id": f"ev-pay-1-{ext_oid}",
                "event_type": "payment.updated",
                "occurred_at": _iso_at(120),
                "source_system": "payment_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 1,
                "data": {
                    "provider": "PAYSIM_GATEWAY",
                    "provider_txn_ref": f"TXN-1-{ext_oid}",
                    "external_order_id": ext_oid,
                    "method": "bank_transfer",
                    "amount": total,
                    "provider_status_raw": "PAY_SUCCEEDED",
                    "settled_at": _iso_at(120),
                },
            }
        )
        if extra_paid_amount > 0:
            self._ingest_raw(
                {
                    "contract": "retailops-integration-v2",
                    "event_id": f"ev-pay-2-{ext_oid}",
                    "event_type": "payment.updated",
                    "occurred_at": _iso_at(150),
                    "source_system": "payment_sim",
                    "merchant_id": "MERCHANT-SIM-001",
                    "sequence": 1,
                    "data": {
                        "provider": "PAYSIM_GATEWAY",
                        "provider_txn_ref": f"TXN-2-{ext_oid}",
                        "external_order_id": ext_oid,
                        "method": "bank_transfer",
                        "amount": extra_paid_amount,
                        "provider_status_raw": "PAY_SUCCEEDED",
                        "settled_at": _iso_at(150),
                    },
                }
            )
        self._ingest_raw(
            {
                "contract": "retailops-integration-v2",
                "event_id": f"ev-deliv-{ext_oid}",
                "event_type": "order.status_changed",
                "occurred_at": _iso_at(600),
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 2,
                "data": {
                    "external_order_id": ext_oid,
                    "status": "delivered",
                    "reason": None,
                },
            }
        )
        return str(res_ord.order_id), str(res_ord.customer_id)

    def _assert_staff_desk_warns_unlinked(self, cid: str, case_id: str, refund_ref: str) -> None:
        app = Application(self.store, {}, None, tenant_id="shop-i6")
        st, body = api_result(
            app,
            cid,
            "GET",
            f"/api/staff/cases/{case_id}/order-actions",
            context=self.mgr_ctx,
        )
        self.assertEqual(st, 200)
        refs = [r["provider_refund_ref"] for r in body["unlinked_refunds"]]
        self.assertIn(refund_ref, refs)
        self.assertTrue(any(refund_ref in w for w in body["warnings"]))

    def test_closed_request_a_late_refund_does_not_link_to_new_request_b(self) -> None:
        # Subcase A: B's refund is requested (pending) but NOT yet approved by Manager
        oid1, cid1 = self._seed_order("SIM-O-I6-AB1", "SIM-C-I6-AB1")
        with patch.object(self.store, "_now", return_value=_epoch_at(1000)):
            req_a = self.store.create_order_action_request(
                cid1,
                {
                    "order_id": oid1,
                    "type": "return",
                    "expected_order_version": 2,
                    "reason_code": "defective_item",
                    "reason_text": "Yêu cầu A đã đóng",
                },
            )
            req_a_id = req_a["order_action"]["request_id"]
            s1 = self.store.transition_order_action_request(
                req_a_id, "approve", {"version": req_a["order_action"]["version"]}, actor=self.manager_actor
            )
            s2 = self.store.transition_order_action_request(
                req_a_id, "mark_received", {"version": s1["order_action"]["version"]}, actor=self.manager_actor
            )
            s3 = self.store.transition_order_action_request(
                req_a_id,
                "mark_inspected",
                {"version": s2["order_action"]["version"], "inspection_outcome": "refund"},
                actor=self.manager_actor,
            )
            s4 = self.store.transition_order_action_request(
                req_a_id, "complete", {"version": s3["order_action"]["version"]}, actor=self.manager_actor
            )
            s5 = self.store.request_order_action_refund(
                req_a_id, {"version": s4["order_action"]["version"]}, actor=self.manager_actor
            )
            self.store.decide_order_action_refund(
                req_a_id,
                {"version": s5["order_action"]["version"], "decision": "approved"},
                actor=self.manager_actor,
            )

        # First refund attempt for A fails at t=1400 -> A now has closed_at != NULL and refund_status='failed'
        self._ingest_raw(
            {
                "contract": "retailops-integration-v2",
                "event_id": "ev-i6-ab1-a-fail",
                "event_type": "refund.updated",
                "occurred_at": _iso_at(1400),
                "source_system": "payment_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 1,
                "data": {
                    "provider": "PAYSIM_GATEWAY",
                    "provider_refund_ref": "REF-I6-AB1-FAIL",
                    "provider_txn_ref": "TXN-1-SIM-O-I6-AB1",
                    "external_order_id": "SIM-O-I6-AB1",
                    "amount": 259000,
                    "channel": "bank_transfer",
                    "provider_status_raw": "REFUND_FAILED",
                    "initiated_at": _iso_at(1350),
                    "completed_at": None,
                    "failure_reason": "Lỗi tạm thời tại ngân hàng",
                },
            }
        )

        # Customer opens Request B at t=2000; Staff approves B and requests refund (refund_decision is still None!)
        with patch.object(self.store, "_now", return_value=_epoch_at(2000)):
            req_b = self.store.create_order_action_request(
                cid1,
                {
                    "order_id": oid1,
                    "type": "return",
                    "expected_order_version": 2,
                    "reason_code": "wrong_item",
                    "reason_text": "Yêu cầu B mới mở",
                },
            )
            req_b_id = req_b["order_action"]["request_id"]
            b1 = self.store.transition_order_action_request(
                req_b_id, "approve", {"version": req_b["order_action"]["version"]}, actor=self.manager_actor
            )
            self.store.request_order_action_refund(
                req_b_id, {"version": b1["order_action"]["version"]}, actor=self.manager_actor
            )

        # Late refund of A arrives at t=2100 (initiated_at t=1500) -> must NOT link to unapproved B!
        self._ingest_raw(
            {
                "contract": "retailops-integration-v2",
                "event_id": "ev-i6-ab1-a-late",
                "event_type": "refund.updated",
                "occurred_at": _iso_at(2100),
                "source_system": "payment_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 1,
                "data": {
                    "provider": "PAYSIM_GATEWAY",
                    "provider_refund_ref": "REF-I6-AB1-LATE",
                    "provider_txn_ref": "TXN-1-SIM-O-I6-AB1",
                    "external_order_id": "SIM-O-I6-AB1",
                    "amount": 259000,
                    "channel": "bank_transfer",
                    "provider_status_raw": "REFUND_COMPLETED",
                    "initiated_at": _iso_at(1500),
                    "completed_at": _iso_at(2100),
                    "failure_reason": None,
                },
            }
        )
        with self.store.connection() as db:
            ref_late_1 = db.execute(
                "SELECT * FROM refunds WHERE provider_refund_ref='REF-I6-AB1-LATE'"
            ).fetchone()
            oar_b1 = db.execute(
                "SELECT refund_status, refund_decision FROM order_action_requests WHERE request_id=?",
                (req_b_id,),
            ).fetchone()
        self.assertIsNone(ref_late_1["request_id"])
        self.assertEqual(oar_b1["refund_status"], "pending")
        self.assertIsNone(oar_b1["refund_decision"])
        self._assert_staff_desk_warns_unlinked(cid1, req_b["case_id"], "REF-I6-AB1-LATE")

        # Subcase B: Even if Manager HAS approved B's refund at t=2200, A's late refund (initiated_at t=1500 < 2200) must NOT link to B!
        oid2, cid2 = self._seed_order("SIM-O-I6-AB2", "SIM-C-I6-AB2")
        with patch.object(self.store, "_now", return_value=_epoch_at(1000)):
            ra2 = self.store.create_order_action_request(
                cid2,
                {
                    "order_id": oid2,
                    "type": "return",
                    "expected_order_version": 2,
                    "reason_code": "defective_item",
                    "reason_text": "A2 đã đóng",
                },
            )
            ra2_id = ra2["order_action"]["request_id"]
            u1 = self.store.transition_order_action_request(
                ra2_id, "approve", {"version": ra2["order_action"]["version"]}, actor=self.manager_actor
            )
            self.store.transition_order_action_request(
                ra2_id,
                "reject",
                {"version": ra2["order_action"]["version"]},
                actor=self.manager_actor,
            ) if False else None
            u2 = self.store.transition_order_action_request(
                ra2_id, "mark_received", {"version": u1["order_action"]["version"]}, actor=self.manager_actor
            )
            u3 = self.store.transition_order_action_request(
                ra2_id,
                "mark_inspected",
                {"version": u2["order_action"]["version"], "inspection_outcome": "no_action"},
                actor=self.manager_actor,
            )
            self.store.transition_order_action_request(
                ra2_id, "complete", {"version": u3["order_action"]["version"]}, actor=self.manager_actor
            )

        with patch.object(self.store, "_now", return_value=_epoch_at(2200)):
            rb2 = self.store.create_order_action_request(
                cid2,
                {
                    "order_id": oid2,
                    "type": "return",
                    "expected_order_version": 2,
                    "reason_code": "wrong_item",
                    "reason_text": "B2 đã duyệt hoàn lúc t=2200",
                },
            )
            rb2_id = rb2["order_action"]["request_id"]
            v1 = self.store.transition_order_action_request(
                rb2_id, "approve", {"version": rb2["order_action"]["version"]}, actor=self.manager_actor
            )
            v2 = self.store.request_order_action_refund(
                rb2_id, {"version": v1["order_action"]["version"]}, actor=self.manager_actor
            )
            self.store.decide_order_action_refund(
                rb2_id,
                {"version": v2["order_action"]["version"], "decision": "approved"},
                actor=self.manager_actor,
            )

        self._ingest_raw(
            {
                "contract": "retailops-integration-v2",
                "event_id": "ev-i6-ab2-a-late",
                "event_type": "refund.updated",
                "occurred_at": _iso_at(2300),
                "source_system": "payment_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 1,
                "data": {
                    "provider": "PAYSIM_GATEWAY",
                    "provider_refund_ref": "REF-I6-AB2-LATE",
                    "provider_txn_ref": "TXN-1-SIM-O-I6-AB2",
                    "external_order_id": "SIM-O-I6-AB2",
                    "amount": 259000,
                    "channel": "bank_transfer",
                    "provider_status_raw": "REFUND_COMPLETED",
                    "initiated_at": _iso_at(1500),
                    "completed_at": _iso_at(2300),
                    "failure_reason": None,
                },
            }
        )
        with self.store.connection() as db:
            ref_late_2 = db.execute(
                "SELECT * FROM refunds WHERE provider_refund_ref='REF-I6-AB2-LATE'"
            ).fetchone()
            oar_b2 = db.execute(
                "SELECT refund_status FROM order_action_requests WHERE request_id=?",
                (rb2_id,),
            ).fetchone()
        self.assertIsNone(ref_late_2["request_id"])
        self.assertEqual(oar_b2["refund_status"], "pending")
        self._assert_staff_desk_warns_unlinked(cid2, rb2["case_id"], "REF-I6-AB2-LATE")

    def test_refund_exceeding_requested_amount_does_not_link_and_warns(self) -> None:
        # Order amount is 259,000, customer accidentally paid twice (paid_sum = 518,000)
        oid, cid = self._seed_order(
            "SIM-O-I6-AMT",
            "SIM-C-I6-AMT",
            amount_subtotal=239000,
            shipping_fee=20000,
            extra_paid_amount=259000,
        )
        with patch.object(self.store, "_now", return_value=_epoch_at(1000)):
            created = self.store.create_order_action_request(
                cid,
                {
                    "order_id": oid,
                    "type": "return",
                    "expected_order_version": 2,
                    "reason_code": "defective_item",
                    "reason_text": "Hoàn tiền đơn lỗi",
                },
            )
            req_id = created["order_action"]["request_id"]
            ap = self.store.transition_order_action_request(
                req_id, "approve", {"version": created["order_action"]["version"]}, actor=self.manager_actor
            )
            rr = self.store.request_order_action_refund(
                req_id, {"version": ap["order_action"]["version"]}, actor=self.manager_actor
            )
            self.store.decide_order_action_refund(
                req_id,
                {"version": rr["order_action"]["version"], "decision": "approved"},
                actor=self.manager_actor,
            )

        # Refund of 300,000 (<= paid_sum 518,000, but > requested order amount 259,000)
        self._ingest_raw(
            {
                "contract": "retailops-integration-v2",
                "event_id": "ev-i6-amt-exceed",
                "event_type": "refund.updated",
                "occurred_at": _iso_at(1500),
                "source_system": "payment_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 1,
                "data": {
                    "provider": "PAYSIM_GATEWAY",
                    "provider_refund_ref": "REF-I6-AMT-300K",
                    "provider_txn_ref": "TXN-1-SIM-O-I6-AMT",
                    "external_order_id": "SIM-O-I6-AMT",
                    "amount": 300000,
                    "channel": "bank_transfer",
                    "provider_status_raw": "REFUND_COMPLETED",
                    "initiated_at": _iso_at(1450),
                    "completed_at": _iso_at(1500),
                    "failure_reason": None,
                },
            }
        )
        with self.store.connection() as db:
            ref_row = db.execute(
                "SELECT * FROM refunds WHERE provider_refund_ref='REF-I6-AMT-300K'"
            ).fetchone()
            oar = db.execute(
                "SELECT refund_status FROM order_action_requests WHERE request_id=?",
                (req_id,),
            ).fetchone()
        self.assertIsNotNone(ref_row)
        self.assertIsNone(ref_row["request_id"])
        self.assertEqual(oar["refund_status"], "pending")
        self._assert_staff_desk_warns_unlinked(cid, created["case_id"], "REF-I6-AMT-300K")

    def test_refund_before_approval_timestamp_does_not_link(self) -> None:
        oid, cid = self._seed_order("SIM-O-I6-TS", "SIM-C-I6-TS")
        with patch.object(self.store, "_now", return_value=_epoch_at(1000)):
            created = self.store.create_order_action_request(
                cid,
                {
                    "order_id": oid,
                    "type": "return",
                    "expected_order_version": 2,
                    "reason_code": "defective_item",
                    "reason_text": "Hoàn tiền kiểm tra mốc duyệt",
                },
            )
            req_id = created["order_action"]["request_id"]
            ap = self.store.transition_order_action_request(
                req_id, "approve", {"version": created["order_action"]["version"]}, actor=self.manager_actor
            )
            rr = self.store.request_order_action_refund(
                req_id, {"version": ap["order_action"]["version"]}, actor=self.manager_actor
            )

        # Manager approves refund at t=2000
        with patch.object(self.store, "_now", return_value=_epoch_at(2000)):
            self.store.decide_order_action_refund(
                req_id,
                {"version": rr["order_action"]["version"], "decision": "approved"},
                actor=self.manager_actor,
            )

        # Refund initiated at t=1900 (< t=2000 approval timestamp) -> must NOT link!
        self._ingest_raw(
            {
                "contract": "retailops-integration-v2",
                "event_id": "ev-i6-ts-before",
                "event_type": "refund.updated",
                "occurred_at": _iso_at(1950),
                "source_system": "payment_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 1,
                "data": {
                    "provider": "PAYSIM_GATEWAY",
                    "provider_refund_ref": "REF-I6-TS-BEFORE",
                    "provider_txn_ref": "TXN-1-SIM-O-I6-TS",
                    "external_order_id": "SIM-O-I6-TS",
                    "amount": 259000,
                    "channel": "bank_transfer",
                    "provider_status_raw": "REFUND_COMPLETED",
                    "initiated_at": _iso_at(1900),
                    "completed_at": _iso_at(1950),
                    "failure_reason": None,
                },
            }
        )
        with self.store.connection() as db:
            ref_row = db.execute(
                "SELECT * FROM refunds WHERE provider_refund_ref='REF-I6-TS-BEFORE'"
            ).fetchone()
            oar = db.execute(
                "SELECT refund_status FROM order_action_requests WHERE request_id=?",
                (req_id,),
            ).fetchone()
        self.assertIsNone(ref_row["request_id"])
        self.assertEqual(oar["refund_status"], "pending")
        self._assert_staff_desk_warns_unlinked(cid, created["case_id"], "REF-I6-TS-BEFORE")

    def test_valid_refund_links_and_duplicate_or_subsequent_events_never_relink(self) -> None:
        oid, cid = self._seed_order("SIM-O-I6-KEEP", "SIM-C-I6-KEEP")
        with patch.object(self.store, "_now", return_value=_epoch_at(1000)):
            req_a = self.store.create_order_action_request(
                cid,
                {
                    "order_id": oid,
                    "type": "return",
                    "expected_order_version": 2,
                    "reason_code": "defective_item",
                    "reason_text": "Yêu cầu A hợp lệ",
                },
            )
            req_a_id = req_a["order_action"]["request_id"]
            ap_a = self.store.transition_order_action_request(
                req_a_id, "approve", {"version": req_a["order_action"]["version"]}, actor=self.manager_actor
            )
            rr_a = self.store.request_order_action_refund(
                req_a_id, {"version": ap_a["order_action"]["version"]}, actor=self.manager_actor
            )
        with patch.object(self.store, "_now", return_value=_epoch_at(1300)):
            self.store.decide_order_action_refund(
                req_a_id,
                {"version": rr_a["order_action"]["version"], "decision": "approved"},
                actor=self.manager_actor,
            )

        ev_init = {
            "contract": "retailops-integration-v2",
            "event_id": "ev-i6-keep-1",
            "event_type": "refund.updated",
            "occurred_at": _iso_at(1500),
            "source_system": "payment_sim",
            "merchant_id": "MERCHANT-SIM-001",
            "sequence": 1,
            "data": {
                "provider": "PAYSIM_GATEWAY",
                "provider_refund_ref": "REF-I6-KEEP-1",
                "provider_txn_ref": "TXN-1-SIM-O-I6-KEEP",
                "external_order_id": "SIM-O-I6-KEEP",
                "amount": 259000,
                "channel": "bank_transfer",
                "provider_status_raw": "REFUND_INITIATED",
                "initiated_at": _iso_at(1500),
                "completed_at": None,
                "failure_reason": None,
            },
        }
        res_1 = self._ingest_raw(ev_init)
        self.assertFalse(res_1.is_replay)

        with self.store.connection() as db:
            ref_1 = db.execute("SELECT * FROM refunds WHERE provider_refund_ref='REF-I6-KEEP-1'").fetchone()
        self.assertEqual(ref_1["request_id"], req_a_id)

        # Close Request A and open + approve Request B before REF-I6-KEEP-1 completes
        with self.store.connection() as db:
            cur_ver_a = int(
                db.execute("SELECT version FROM order_action_requests WHERE request_id=?", (req_a_id,)).fetchone()[
                    "version"
                ]
            )
        with patch.object(self.store, "_now", return_value=_epoch_at(1600)):
            s2 = self.store.transition_order_action_request(
                req_a_id, "mark_received", {"version": cur_ver_a}, actor=self.manager_actor
            )
            s3 = self.store.transition_order_action_request(
                req_a_id,
                "mark_inspected",
                {"version": s2["order_action"]["version"], "inspection_outcome": "refund"},
                actor=self.manager_actor,
            )
            self.store.transition_order_action_request(
                req_a_id, "complete", {"version": s3["order_action"]["version"]}, actor=self.manager_actor
            )

            req_b = self.store.create_order_action_request(
                cid,
                {
                    "order_id": oid,
                    "type": "return",
                    "expected_order_version": 2,
                    "reason_code": "wrong_item",
                    "reason_text": "Yêu cầu B mở sau khi A đã gắn REF-I6-KEEP-1",
                },
            )
            req_b_id = req_b["order_action"]["request_id"]
            ap_b = self.store.transition_order_action_request(
                req_b_id, "approve", {"version": req_b["order_action"]["version"]}, actor=self.manager_actor
            )
            rr_b = self.store.request_order_action_refund(
                req_b_id, {"version": ap_b["order_action"]["version"]}, actor=self.manager_actor
            )
            self.store.decide_order_action_refund(
                req_b_id,
                {"version": rr_b["order_action"]["version"], "decision": "approved"},
                actor=self.manager_actor,
            )

        # Replay of ev_init (same event_id) and subsequent REFUND_COMPLETED (seq 2) must keep request_id == req_a_id!
        dup_res = self._ingest_raw(ev_init)
        self.assertTrue(dup_res.is_replay)

        ev_comp = {
            "contract": "retailops-integration-v2",
            "event_id": "ev-i6-keep-2",
            "event_type": "refund.updated",
            "occurred_at": _iso_at(2000),
            "source_system": "payment_sim",
            "merchant_id": "MERCHANT-SIM-001",
            "sequence": 2,
            "data": {
                "provider": "PAYSIM_GATEWAY",
                "provider_refund_ref": "REF-I6-KEEP-1",
                "provider_txn_ref": "TXN-1-SIM-O-I6-KEEP",
                "external_order_id": "SIM-O-I6-KEEP",
                "amount": 259000,
                "channel": "bank_transfer",
                "provider_status_raw": "REFUND_COMPLETED",
                "initiated_at": _iso_at(1500),
                "completed_at": _iso_at(2000),
                "failure_reason": None,
            },
        }
        self._ingest_raw(ev_comp)

        # Same sequence replay with new event_id -> sequence_ignored, link still req_a_id
        ev_comp_dup_seq = dict(ev_comp, event_id="ev-i6-keep-2-re")
        res_seq_ign = self._ingest_raw(ev_comp_dup_seq)
        self.assertTrue(res_seq_ign.sequence_ignored)

        with self.store.connection() as db:
            ref_final = db.execute("SELECT * FROM refunds WHERE provider_refund_ref='REF-I6-KEEP-1'").fetchone()
            oar_a = db.execute("SELECT refund_status FROM order_action_requests WHERE request_id=?", (req_a_id,)).fetchone()
            oar_b = db.execute("SELECT refund_status FROM order_action_requests WHERE request_id=?", (req_b_id,)).fetchone()
        self.assertEqual(ref_final["request_id"], req_a_id)
        self.assertEqual(oar_a["refund_status"], "refunded")
        self.assertEqual(oar_b["refund_status"], "pending")


if __name__ == "__main__":
    unittest.main()
