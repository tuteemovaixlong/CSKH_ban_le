"""Tests for Phase R1 W6.1b-2 Item 4: late-delivery detection and compensation proposals (W6.1b-2-D6, D7)."""
from __future__ import annotations

import concurrent.futures
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_protocol import PROTOCOL, TOOLS
from retailops.business import eligibility as elig_mod
from retailops.business.application import Application
from retailops.business.permissions import ROLE_PERMISSIONS
from retailops.core import ApiError
from retailops.http.routes import api_result
from retailops.identity.contracts import RequestContext
from retailops.identity.persistent import PersistentSessions
from retailops.integration.ingest import IntegrationIngestService
from retailops.workflow.case_assist import CaseAssistBoundTools
from retailops_tools import BoundTools
from tests._w6_1b_2_pg_base import RealPostgresW61b2Base, pg_test_enabled


def _ctx(
    role: str,
    principal_id: str,
    *,
    customer_id: str,
    tenant_id: str = "shop-demo",
    display_name: str = "Test Actor",
) -> RequestContext:
    return RequestContext(
        customer_id=customer_id,
        role=role,
        permissions=ROLE_PERMISSIONS[role],
        tenant_id=tenant_id,
        principal_id=principal_id,
        membership_id=f"mem_{principal_id}",
        display_name=display_name,
        authenticated_session=True,
    )


def _seed_late_test_orders(sessions, store, *, tenant_id: str = "shop-demo", base_ts: float = 1_762_700_000.0):
    """Create canonical orders via integration events to test 47h vs 49h late thresholds."""
    from retailops.business.eligibility import format_vn_iso

    svc = IntegrationIngestService(sessions)

    events = [
        {
            "contract": "retailops-integration-v2",
            "event_id": "evt_i4_prod_01",
            "event_type": "product.upserted",
            "source_system": "marketplace_sim",
            "merchant_id": "MERCHANT-SIM-001",
            "occurred_at": format_vn_iso(base_ts - 500_000),
            "sequence": 1,
            "data": {
                "external_product_id": "MP-P-401",
                "title": "Áo khoác gió chống nước",
                "category": "Áo khoác",
                "price": 350000,
                "description": "Áo khoác mỏng nhẹ",
                "material": "Polyester",
                "care": "Giặt nhẹ",
                "warranty_days": 90,
                "variants": [
                    {
                        "sku": "SKU-401-L",
                        "variant_name": "Đen / L",
                        "size": "L",
                        "color": "Đen",
                        "price": 350000,
                        "stock": 20,
                    }
                ],
            },
        },
        {
            "contract": "retailops-integration-v2",
            "event_id": "evt_i4_cust_01",
            "event_type": "customer.upserted",
            "source_system": "marketplace_sim",
            "merchant_id": "MERCHANT-SIM-001",
            "occurred_at": format_vn_iso(base_ts - 490_000),
            "sequence": 1,
            "data": {
                "external_customer_id": "EXT-C-401",
                "display_name": "Khách kiểm thử bồi thường",
            },
        },
    ]

    # 1) Order A: shipping, promised at (scan_now - 47h) -> NOT eligible (47h <= 48h)
    # 2) Order B: shipping, promised at (scan_now - 49h) -> ELIGIBLE (49h > 48h)
    # 3) Order C: delivered at (promised + 49h) -> ELIGIBLE (49h > 48h)
    # 4) Order D: cancelled, promised at (scan_now - 60h) -> NOT eligible (cancelled)
    specs = [
        ("SIM-I4-47H", base_ts - 300_000, base_ts - 47 * 3600, "shipping", None, "SHP-I4-47H"),
        ("SIM-I4-49H", base_ts - 300_000, base_ts - 49 * 3600, "shipping", None, "SHP-I4-49H"),
        ("SIM-I4-DELIV-49H", base_ts - 400_000, base_ts - 100 * 3600, "delivered", base_ts - 51 * 3600, "SHP-I4-DELIV"),
        ("SIM-I4-CANCEL-60H", base_ts - 300_000, base_ts - 60 * 3600, "cancelled", None, None),
    ]
    for idx, (ext_oid, ordered_ts, promised_ts, target_st, deliv_ts, ext_ship_id) in enumerate(specs, start=1):
        events.append(
            {
                "contract": "retailops-integration-v2",
                "event_id": f"evt_i4_ord_create_{idx:02d}",
                "event_type": "order.created",
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "occurred_at": format_vn_iso(ordered_ts),
                "sequence": 1,
                "data": {
                    "external_order_id": ext_oid,
                    "external_customer_id": "EXT-C-401",
                    "ordered_at": format_vn_iso(ordered_ts),
                    "items": [
                        {
                            "sku": "SKU-401-L",
                            "external_product_id": "MP-P-401",
                            "title": "Áo khoác gió chống nước",
                            "variant_name": "Đen / L",
                            "quantity": 1,
                            "unit_price": 350000,
                        }
                    ],
                    "shipping_fee": 20000,
                    "total": 370000,
                    "currency": "VND",
                    "payment_method": "cod",
                    "promised_delivery_by": format_vn_iso(promised_ts),
                    "recipient": {
                        "name": "Trần Văn Kiểm Thử",
                        "phone": "0990123456",
                        "address_line": "12 Đường Mẫu",
                        "ward": "Phường 1",
                        "district": "Quận 3",
                        "province": "TP. Hồ Chí Minh",
                    },
                },
            }
        )
        if ext_ship_id is not None:
            ship_raw = "delivered" if target_st == "delivered" else "transporting"
            ship_occ = deliv_ts if deliv_ts is not None else (ordered_ts + 3600)
            events.append(
                {
                    "contract": "retailops-integration-v2",
                    "event_id": f"evt_i4_ship_{idx:02d}",
                    "event_type": "shipment.updated",
                    "source_system": "marketplace_sim",
                    "merchant_id": "MERCHANT-SIM-001",
                    "occurred_at": format_vn_iso(ship_occ),
                    "sequence": 2,
                    "data": {
                        "external_order_id": ext_oid,
                        "external_shipment_id": ext_ship_id,
                        "carrier": "GHN",
                        "tracking_code": f"GHN-{idx:04d}",
                        "carrier_status_raw": ship_raw,
                        "hub_name": "Kho Quận 3",
                        "district": "Quận 3",
                        "province": "TP. Hồ Chí Minh",
                        "description": "Đang trung chuyển" if ship_raw != "delivered" else "Giao hàng thành công",
                        "fail_reason": None,
                        "shipper_name": "Bưu tá GHN",
                        "estimated_delivery_at": format_vn_iso(promised_ts),
                        "shipper_phone_masked": "0901.xxx.123",
                        "delivery_attempts": 1,
                    },
                }
            )
        events.append(
            {
                "contract": "retailops-integration-v2",
                "event_id": f"evt_i4_ord_st_{idx:02d}",
                "event_type": "order.status_changed",
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "occurred_at": format_vn_iso(deliv_ts if deliv_ts is not None else (ordered_ts + 7200)),
                "sequence": 3,
                "data": {
                    "external_order_id": ext_oid,
                    "status": target_st,
                    "reason": "buyer_cancelled" if target_st == "cancelled" else None,
                },
            }
        )

    for ev in events:
        raw = __import__("json").dumps(ev, ensure_ascii=False).encode("utf-8")
        res = svc.ingest_event(raw, tenant_id=tenant_id)
        assert res.success, res

    with store.connection() as db:
        rows = db.execute(
            "SELECT id, external_order_id, customer_id, status FROM orders ORDER BY external_order_id ASC"
        ).fetchall()
    by_ext = {r["external_order_id"]: dict(r) for r in rows}
    return by_ext


class CompensationItem4Mixins:
    """Shared Item 4 assertions executed on both SQLite and real PostgreSQL."""

    def run_item4_suite(self, sessions, store, *, tenant_id: str = "shop-demo") -> None:
        # 1. Fixed policy constants in eligibility.py (W6.1b-2-D7)
        self.assertEqual(elig_mod.LATE_DELIVERY_COMPENSATION_THRESHOLD_HOURS, 48)
        self.assertEqual(elig_mod.LATE_DELIVERY_COMPENSATION_VOUCHER_TYPE, "amount")
        self.assertEqual(elig_mod.LATE_DELIVERY_COMPENSATION_VOUCHER_VND, 50000)

        scan_now = 1_762_700_000.0
        by_ext = _seed_late_test_orders(sessions, store, tenant_id=tenant_id, base_ts=scan_now)
        ord_47h = by_ext["SIM-I4-47H"]
        ord_49h = by_ext["SIM-I4-49H"]
        ord_deliv_49h = by_ext["SIM-I4-DELIV-49H"]
        customer_id = ord_49h["customer_id"]

        # 2. Simulate a mid-scan failure after the first compensation write, then recover on re-run
        real_insert_hook_calls = {"count": 0}
        orig_scan = store.scan_late_delivery_compensations

        def _crashing_once(*args, **kwargs):
            kwargs["_fail_after_first_insert_for_test"] = True
            return orig_scan(*args, **kwargs)

        with self.assertRaises(RuntimeError):
            _crashing_once(now=scan_now)

        # Re-run background worker scan multiple times and in parallel
        res1 = sessions.run_case_timers_once(now=scan_now)
        self.assertGreaterEqual(res1.get("compensations_proposed", 0), 1)
        res2 = sessions.run_case_timers_once(now=scan_now)
        self.assertEqual(res2.get("compensations_proposed", 0), 0)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futs = [pool.submit(sessions.run_case_timers_once, now=scan_now) for _ in range(4)]
            for f in futs:
                f.result()

        with store.connection() as db:
            comp_rows = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM delivery_compensations ORDER BY order_id ASC"
                ).fetchall()
            ]
        # Only SIM-I4-49H (shipping, 49h late) and SIM-I4-DELIV-49H (delivered, 49h late) qualify!
        # SIM-I4-47H (47h late) and SIM-I4-CANCEL-60H (cancelled) MUST NOT have proposals!
        self.assertEqual(len(comp_rows), 2)
        comp_by_oid = {r["order_id"]: r for r in comp_rows}
        self.assertNotIn(ord_47h["id"], comp_by_oid)
        self.assertIn(ord_49h["id"], comp_by_oid)
        self.assertIn(ord_deliv_49h["id"], comp_by_oid)

        for r in comp_rows:
            self.assertEqual(r["status"], "proposed")
            self.assertEqual(r["voucher_type"], "amount")
            self.assertEqual(int(r["value"]), 50000)
            self.assertEqual(r["reason"], "late_delivery")
            self.assertIsNotNone(r["shipment_id"])
            self.assertGreater(float(r["late_by_hours"]), 48.0)

        comp_shipping = comp_by_oid[ord_49h["id"]]
        comp_deliv = comp_by_oid[ord_deliv_49h["id"]]

        # 3. Prepare Staff Desk case linked to ord_49h
        app_staff_holder = Application(store, {}, None, None, role="staff", tenant_id=tenant_id)
        app_staff_holder.identity_store = sessions.control
        app_staff_other = Application(store, {}, None, None, role="staff", tenant_id=tenant_id)
        app_staff_other.identity_store = sessions.control
        app_manager = Application(store, {}, None, None, role="manager", tenant_id=tenant_id)
        app_manager.identity_store = sessions.control
        app_customer = Application(store, {}, None, None, role="customer", tenant_id=tenant_id)
        app_customer.identity_store = sessions.control

        ctx_holder = _ctx("staff", "p_staff_holder", customer_id="C_STAFF_1", tenant_id=tenant_id)
        ctx_other = _ctx("staff", "p_staff_other", customer_id="C_STAFF_2", tenant_id=tenant_id)
        ctx_mgr = _ctx("manager", "p_mgr_1", customer_id="C_MGR_1", tenant_id=tenant_id)
        ctx_cust = _ctx("customer", "p_cust_1", customer_id=customer_id, tenant_id=tenant_id)

        conv = app_customer.new_conversation(customer_id, {})
        cid = conv["conversation_id"]
        app_customer.focus(customer_id, cid, {"order_id": ord_49h["id"]})
        store.request_human_handoff(
            customer_id,
            cid,
            reason_code="customer_requested",
            comment="Đơn giao trễ hơn 2 ngày",
        )
        desk = store.staff_desk_cases()
        case_id = desk["waiting"][0]["case_id"]
        store.claim_case(
            case_id,
            staff_name="Staff Holder",
            actor={
                "principal_id": "p_staff_holder",
                "role": "staff",
                "tenant_id": tenant_id,
                "membership_id": "mem_p_staff_holder",
            },
        )

        # Staff Desk case endpoint includes compensations for linked order
        st_oa, body_oa = api_result(
            app_staff_holder,
            ctx_holder.customer_id,
            "GET",
            f"/api/staff/cases/{case_id}/order-actions",
            None,
            "",
            None,
            context=ctx_holder,
        )
        self.assertEqual(st_oa, 200)
        case_comps = body_oa.get("compensations") or []
        self.assertEqual(len(case_comps), 1)
        self.assertEqual(case_comps[0]["compensation_id"], comp_shipping["compensation_id"])
        self.assertEqual(case_comps[0]["value"], 50000)

        # Manager list view shows ALL store compensations
        st_mgr_list, body_mgr_list = api_result(
            app_manager,
            ctx_mgr.customer_id,
            "GET",
            "/api/manager/compensations",
            None,
            "",
            None,
            context=ctx_mgr,
        )
        self.assertEqual(st_mgr_list, 200)
        self.assertEqual(body_mgr_list["total"], 2)

        # 4. API MUST reject any value / denomination / voucher_type field with 400 (W6.1b-2-D7)
        for bad_payload in (
            {"value": 100000},
            {"value": 50000},
            {"amount": 50000},
            {"voucher_type": "free_shipping"},
            {"denomination": 50000},
        ):
            with self.assertRaises(ApiError) as bad_cm:
                api_result(
                    app_staff_holder,
                    ctx_holder.customer_id,
                    "POST",
                    f"/api/staff/compensations/{comp_shipping['compensation_id']}/approve",
                    bad_payload,
                    "",
                    None,
                    context=ctx_holder,
                )
            self.assertEqual(bad_cm.exception.status, 400)

        # 5. Customer & non-holding Staff MUST receive 403
        with self.assertRaises(ApiError) as cust_cm:
            api_result(
                app_customer,
                ctx_cust.customer_id,
                "POST",
                f"/api/staff/compensations/{comp_shipping['compensation_id']}/approve",
                {"note": "Khách tự duyệt"},
                "",
                None,
                context=ctx_cust,
            )
        self.assertEqual(cust_cm.exception.status, 403)

        with self.assertRaises(ApiError) as other_cm:
            api_result(
                app_staff_other,
                ctx_other.customer_id,
                "POST",
                f"/api/staff/compensations/{comp_shipping['compensation_id']}/approve",
                {"note": "Nhân viên không giữ ca"},
                "",
                None,
                context=ctx_other,
            )
        self.assertEqual(other_cm.exception.status, 403)

        # Staff holding case for ord_49h also CANNOT approve comp_deliv (unlinked order) -> 403
        with self.assertRaises(ApiError) as unlinked_cm:
            api_result(
                app_staff_holder,
                ctx_holder.customer_id,
                "POST",
                f"/api/staff/compensations/{comp_deliv['compensation_id']}/approve",
                {"note": "Đơn không gắn ca"},
                "",
                None,
                context=ctx_holder,
            )
        self.assertEqual(unlinked_cm.exception.status, 403)

        # 6. Concurrent race on comp_shipping between Staff Holder (approve) and Manager (reject):
        #    Conditional WHERE status='proposed' ensures 1 wins (200) and 1 gets 409!
        barrier = threading.Barrier(2)
        outcomes: list[tuple[str, int]] = []

        def _holder_approve():
            barrier.wait(timeout=5)
            try:
                st, _ = api_result(
                    app_staff_holder,
                    ctx_holder.customer_id,
                    "POST",
                    f"/api/staff/compensations/{comp_shipping['compensation_id']}/approve",
                    {"case_id": case_id, "note": "Duyệt bồi thường giao trễ"},
                    "",
                    None,
                    context=ctx_holder,
                )
                outcomes.append(("holder", st))
            except ApiError as exc:
                outcomes.append(("holder", exc.status))

        def _mgr_reject():
            barrier.wait(timeout=5)
            try:
                st, _ = api_result(
                    app_manager,
                    ctx_mgr.customer_id,
                    "POST",
                    f"/api/staff/compensations/{comp_shipping['compensation_id']}/reject",
                    {"note": "Manager từ chối thử tranh chấp"},
                    "",
                    None,
                    context=ctx_mgr,
                )
                outcomes.append(("manager", st))
            except ApiError as exc:
                outcomes.append(("manager", exc.status))

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_holder_approve)
            f2 = pool.submit(_mgr_reject)
            f1.result()
            f2.result()

        statuses = sorted(code for _, code in outcomes)
        self.assertEqual(statuses, [200, 409], f"Expected one 200 and one 409, got {outcomes}")

        # 7. Manager approves comp_deliv (store proposal with NO linked case) -> 200
        st_mgr_ok, body_mgr_ok = api_result(
            app_manager,
            ctx_mgr.customer_id,
            "POST",
            f"/api/staff/compensations/{comp_deliv['compensation_id']}/approve",
            {"note": "Manager duyệt đề xuất toàn cửa hàng"},
            "",
            None,
            context=ctx_mgr,
        )
        self.assertEqual(st_mgr_ok, 200)
        self.assertIn(body_mgr_ok["compensation"]["status"], ("approved", "requested"))
        self.assertEqual(int(body_mgr_ok["compensation"]["value"]), 50000)
        self.assertEqual(body_mgr_ok["compensation"]["decided_by_principal_id"], "p_mgr_1")

        # Second attempt on already-decided comp_deliv returns 409
        with self.assertRaises(ApiError) as dup_cm:
            api_result(
                app_manager,
                ctx_mgr.customer_id,
                "POST",
                f"/api/staff/compensations/{comp_deliv['compensation_id']}/approve",
                {"note": "Duyệt lần hai"},
                "",
                None,
                context=ctx_mgr,
            )
        self.assertEqual(dup_cm.exception.status, 409)

        # 8. AI tool boundary: AI has zero tools to create or approve compensations/vouchers
        tool_names = {t["function"]["name"] for t in TOOLS}
        for forbidden in ("create_voucher", "approve_voucher", "issue_voucher", "approve_compensation", "propose_compensation"):
            self.assertNotIn(forbidden, tool_names)
            self.assertFalse(hasattr(BoundTools, forbidden))
            self.assertFalse(hasattr(CaseAssistBoundTools, forbidden))


class SQLiteCompensationsItem4Tests(unittest.TestCase, CompensationItem4Mixins):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="r1-w61b2-i4-sqlite-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rec_key = self.root / "retailops_recipient_key_v1"
        self.rec_key.write_bytes(b"R" * 32)
        self.dig_key = self.root / "retailops_event_digest_key"
        self.dig_key.write_bytes(b"D" * 32)
        self.ref_key = "test-customer-ref-secret-key-012345"
        self.env_patch = patch.dict(
            os.environ,
            {
                "RETAILOPS_RECIPIENT_KEY_FILE": str(self.rec_key),
                "RETAILOPS_EVENT_DIGEST_KEY_FILE": str(self.dig_key),
                "RETAILOPS_CUSTOMER_REF_KEY": self.ref_key,
            },
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.sessions = PersistentSessions(self.root / "persistent")
        self.store = self.sessions.provision_tenant("shop-demo", "Shop Demo", seed_demo=False)

    def test_sqlite_late_delivery_compensations_end_to_end(self) -> None:
        self.run_item4_suite(self.sessions, self.store, tenant_id="shop-demo")


@unittest.skipUnless(
    pg_test_enabled(),
    "Set RETAILOPS_TEST_DATABASE_URL to run real PostgreSQL W6.1b-2 Item 4 tests",
)
class RealPostgresCompensationsItem4Tests(RealPostgresW61b2Base, CompensationItem4Mixins):
    def test_postgres_late_delivery_compensations_end_to_end(self) -> None:
        rec_key = self.root / "retailops_recipient_key_v1"
        rec_key.write_bytes(b"P" * 32)
        dig_key = self.root / "retailops_event_digest_key"
        dig_key.write_bytes(b"G" * 32)
        ref_key = "pg-test-customer-ref-secret-key-012345"
        self.sessions.customer_ref_key = ref_key
        self.store.customer_ref_key = ref_key
        with patch.dict(
            os.environ,
            {
                "RETAILOPS_RECIPIENT_KEY_FILE": str(rec_key),
                "RETAILOPS_EVENT_DIGEST_KEY_FILE": str(dig_key),
                "RETAILOPS_CUSTOMER_REF_KEY": ref_key,
            },
        ):
            self.run_item4_suite(self.sessions, self.store, tenant_id="shop-demo")


if __name__ == "__main__":
    unittest.main()
