"""Phase R1 W6.1b-1.1 Item 3 tests: D8 external_order_id & Business v9 details in UI/focus/Staff Desk."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from retailops.business.application import Application
from retailops.core import STATUSES
from retailops.http.routes import _enrich_staff_cases_external_order_id
from retailops.identity.persistent import PersistentSessions
from retailops.identity.postgres import PostgresSessions
from retailops.order_reasons import reason_catalog
from retailops.storage.postgres import IDENTITY_SCHEMA, tenant_schema
from retailops_conversation import describe_order

DSN = os.environ.get("RETAILOPS_TEST_DATABASE_URL", "")
REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_item3_store_and_focus_suite(tc: unittest.TestCase, sessions) -> None:
    now_ts = 1_794_236_400.0  # 2026-11-09T22:00:00+07:00
    bstore = sessions.provision_tenant("tenant-a", "Shop A", seed_demo=False)
    bstore_other = sessions.provision_tenant("tenant-b", "Shop B", seed_demo=False)
    bstore.seed_catalog()
    bstore_other.seed_catalog()
    bstore.clock = lambda: now_ts
    bstore_other.clock = lambda: now_ts

    cust_id = "cust_uiv9_01"
    oid_pending = "ord_5aeef27f000000000000000000000001"
    oid_shipping = "ord_5aeef27f000000000000000000000002"
    oid_delivered = "ord_5aeef27f000000000000000000000003"
    oid_cancelled = "ord_5aeef27f000000000000000000000004"
    oid_legacy_null = "O-LEG-NULL-EXT"

    with bstore.connection(write=True) as db:
        db.execute(
            "INSERT INTO customers(id, name) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (cust_id, "Nguyễn Thị Thử Nghiệm"),
        )
        db.execute(
            """INSERT INTO orders(
                   id, customer_id, product_id, source_system, external_order_id,
                   ordered_at, ordered_at_backfilled, name, variant, amount, status,
                   payment_method, payment_status, shipping_fee, ship_to_area,
                   promised_delivery_by, delivered_at, cancel_reason, version
               ) VALUES
               (?, ?, 'P-101', 'marketplace_sim', 'SIM-O-00201', ?, 0, 'Áo sơ mi Oxford', 'Trắng / M', 299000, 'pending',
                'e_wallet', 'paid', 25000, 'Quận Cầu Giấy, Hà Nội', ?, NULL, NULL, 1),
               (?, ?, 'P-102', 'marketplace_sim', 'SIM-O-00202', ?, 0, 'Quần tây công sở', 'Đen / L', 520000, 'shipping',
                'cod', 'unpaid', 30000, 'Quận 7, TP.HCM', ?, NULL, NULL, 2),
               (?, ?, 'P-202', 'marketplace_sim', 'SIM-O-00203', ?, 0, 'Đầm chữ A thanh lịch', 'Be / S', 650000, 'delivered',
                'bank_transfer', 'paid', 0, 'Quận Hải Châu, Đà Nẵng', ?, ?, NULL, 3),
               (?, ?, 'P-101', 'marketplace_sim', 'SIM-O-00204', ?, 0, 'Áo sơ mi Oxford', 'Xanh / L', 299000, 'cancelled',
                'card', 'refunded', NULL, NULL, NULL, NULL, 'ordered_by_mistake', 2),
               (?, ?, 'P-101', 'retailops_seed', NULL, ?, 1, 'Áo sơ mi cũ', 'Trắng / S', 299000, 'pending',
                NULL, 'unpaid', NULL, NULL, NULL, NULL, NULL, 1)""",
            (
                oid_pending, cust_id, now_ts - 3600, now_ts + 2 * 86400,
                oid_shipping, cust_id, now_ts - 86400, now_ts + 86400,
                oid_delivered, cust_id, now_ts - 5 * 86400, now_ts - 4 * 86400, now_ts - 3 * 86400,
                oid_cancelled, cust_id, now_ts - 2 * 86400,
                oid_legacy_null, cust_id, now_ts - 10 * 86400,
            ),
        )
        db.execute(
            """INSERT INTO payment_transactions(
                   payment_id, order_id, provider, provider_txn_ref, method,
                   amount, status, provider_status_raw, created_at, settled_at
               ) VALUES
               ('pay_201', ?, 'PAYSIM', 'TXN-201', 'e_wallet', 299000, 'succeeded', 'PAID', ?, ?),
               ('pay_203', ?, 'PAYSIM', 'TXN-203', 'bank_transfer', 650000, 'succeeded', 'PAID', ?, ?),
               ('pay_204', ?, 'PAYSIM', 'TXN-204', 'card', 299000, 'succeeded', 'PAID', ?, ?)""",
            (
                oid_pending, now_ts - 3500, now_ts - 3400,
                oid_delivered, now_ts - 5 * 86400, now_ts - 5 * 86400 + 60,
                oid_cancelled, now_ts - 2 * 86400, now_ts - 2 * 86400 + 60,
            ),
        )
        db.execute(
            """INSERT INTO refunds(
                   refund_id, order_id, request_id, payment_id, provider, provider_refund_ref,
                   amount, channel, status, provider_status_raw, initiated_at, completed_at, failure_reason
               ) VALUES
               ('ref_204', ?, NULL, 'pay_204', 'PAYSIM', 'REF-204', 299000, 'original_method',
                'completed', 'REFUND_COMPLETED', ?, ?, NULL)""",
            (oid_cancelled, now_ts - 86400, now_ts - 82800),
        )
        db.execute(
            """INSERT INTO shipments(
                   shipment_id, order_id, source_system, external_shipment_id, carrier, tracking_code,
                   status, carrier_status_raw, current_area, shipper_name, shipper_phone_masked,
                   estimated_delivery_at, delivered_at, delivery_attempts, updated_at
               ) VALUES
               ('shp_202', ?, 'carrier_ghn_sim', 'SHP-EXT-202', 'GHN', 'GHN-202',
                'in_transit', 'transporting', 'Kho Tân Thuận, TP.HCM', 'Lê Minh', '090****123',
                ?, NULL, 0, ?),
               ('shp_203', ?, 'carrier_ghtk_sim', 'SHP-EXT-203', 'GHTK', 'GHTK-203',
                'delivered', 'delivered', 'Quận Hải Châu, Đà Nẵng', 'Trần Hải', '091****456',
                ?, ?, 1, ?)""",
            (
                oid_shipping, now_ts + 43200, now_ts - 1800,
                oid_delivered, now_ts - 3 * 86400 - 3600, now_ts - 3 * 86400, now_ts - 3 * 86400,
            ),
        )

    # Seed same internal ID in tenant-b with a different external_order_id to prove strict tenant isolation
    with bstore_other.connection(write=True) as db_other:
        db_other.execute(
            "INSERT INTO customers(id, name) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (cust_id, "Khách Tenant Khác"),
        )
        db_other.execute(
            """INSERT INTO orders(
                   id, customer_id, product_id, source_system, external_order_id,
                   ordered_at, ordered_at_backfilled, name, variant, amount, status, version
               ) VALUES (?, ?, 'P-101', 'marketplace_sim', 'OTHER-TENANT-LEAK-999', ?, 0, 'Áo khác', 'Đen / M', 299000, 'shipping', 1)""",
            (oid_shipping, cust_id, now_ts - 3600),
        )

    app = Application(bstore, {"tok-cust": cust_id}, tenant_id="tenant-a")
    reason_labels = reason_catalog().labels()
    conv = app.new_conversation(cust_id, {})
    cid = conv["conversation_id"]

    # 1. Pending order with paid e_wallet, area & promised deadline, but no shipment yet
    with tc.subTest(part="3a_3b_pending"):
        res_pen = app.focus(cust_id, cid, {"order_id": oid_pending})
        tc.assertEqual(res_pen["context"].get("order_id"), oid_pending)
        tc.assertEqual(res_pen["context"].get("external_order_id"), "SIM-O-00201")
        msg_pen = res_pen["message"]
        tc.assertIn("SIM-O-00201", msg_pen)
        tc.assertNotIn("ord_5aeef27f", msg_pen)
        tc.assertNotIn("chưa có trong dữ liệu demo", msg_pen)
        tc.assertIn("Ví điện tử", msg_pen)
        tc.assertIn("Đã thanh toán", msg_pen)
        tc.assertIn("Quận Cầu Giấy, Hà Nội", msg_pen)
        tc.assertIn("chưa có thông tin vận đơn", msg_pen.lower())
        tc.assertIn("hủy", msg_pen.lower())

    # 2. Shipping order: has GHN shipment + COD unpaid; MUST NOT say "đã giao" or "có thể yêu cầu hủy"
    res_ship = app.focus(cust_id, cid, {"order_id": oid_shipping})
    with tc.subTest(part="3a_3b_shipping"):
        tc.assertEqual(res_ship["context"].get("order_id"), oid_shipping)
        tc.assertEqual(res_ship["context"].get("external_order_id"), "SIM-O-00202")
        msg_ship = res_ship["message"]
        tc.assertIn("SIM-O-00202", msg_ship)
        tc.assertNotIn("ord_5aeef27f", msg_ship)
        tc.assertNotIn("đã giao", msg_ship.lower())
        tc.assertNotIn("có thể yêu cầu hủy", msg_ship.lower())
        tc.assertIn("GHN", msg_ship)
        tc.assertIn("Đang trung chuyển", msg_ship)
        tc.assertIn("Quận 7, TP.HCM", msg_ship)
        tc.assertIn("COD", msg_ship)
        tc.assertIn("Chưa thanh toán", msg_ship)

    with bstore.connection() as db:
        ship_details = bstore.read_order_details_in_tx(db, res_ship["order"], now=now_ts)
    for fld in ("amount", "shipping", "payment", "cancellation"):
        with tc.subTest(part=f"3a_shipping_field_{fld}"):
            sub = describe_order(res_ship["order"], STATUSES, reason_labels, field=fld, details=ship_details)
            tc.assertIn("SIM-O-00202", sub)
            tc.assertNotIn("ord_5aeef27f", sub)
            tc.assertNotIn("đã giao", sub.lower())
            tc.assertNotIn("có thể yêu cầu hủy", sub.lower())
            tc.assertNotIn("chưa có trong dữ liệu demo", sub)
            tc.assertNotIn("Luồng đổi/trả chưa được triển khai", sub)

    # 3. Delivered order: has GHTK delivered shipment, bank_transfer paid, within 7-day return & 15-day size-exchange
    res_del = app.focus(cust_id, cid, {"order_id": oid_delivered})
    with tc.subTest(part="3a_3b_delivered"):
        tc.assertEqual(res_del["context"].get("external_order_id"), "SIM-O-00203")
        msg_del = res_del["message"]
        tc.assertIn("SIM-O-00203", msg_del)
        tc.assertNotIn("ord_5aeef27f", msg_del)
        tc.assertIn("GHTK", msg_del)
        tc.assertIn("Chuyển khoản ngân hàng", msg_del)
        tc.assertIn("Đã thanh toán", msg_del)
        tc.assertIn("Quận Hải Châu, Đà Nẵng", msg_del)
        tc.assertIn("22:00 06/11/2026", msg_del)
        tc.assertNotIn("+07:00", msg_del)
        tc.assertIn("trả hàng", msg_del.lower())
        tc.assertIn("đổi size", msg_del.lower())
        tc.assertNotIn("Luồng đổi/trả chưa được triển khai", msg_del)

    with bstore.connection() as db:
        del_details = bstore.read_order_details_in_tx(db, res_del["order"], now=now_ts)
    with tc.subTest(part="3a_delivered_field_cancellation"):
        del_cancel_field = describe_order(res_del["order"], STATUSES, reason_labels, field="cancellation", details=del_details)
        tc.assertIn("SIM-O-00203", del_cancel_field)
        tc.assertNotIn("Luồng đổi/trả chưa được triển khai", del_cancel_field)
        tc.assertIn("trả hàng", del_cancel_field.lower())

    # 4. Cancelled order with completed refund and null shipment/area
    with tc.subTest(part="3a_3b_cancelled"):
        res_can = app.focus(cust_id, cid, {"order_id": oid_cancelled})
        tc.assertEqual(res_can["context"].get("external_order_id"), "SIM-O-00204")
        msg_can = res_can["message"]
        tc.assertIn("SIM-O-00204", msg_can)
        tc.assertNotIn("ord_5aeef27f", msg_can)
        tc.assertIn("299.000 ₫", msg_can)
        tc.assertIn("Đã hoàn tiền", msg_can)
        tc.assertIn("chưa có thông tin vận đơn", msg_can.lower())

    # 5. Legacy order with external_order_id=NULL and all v9 payment/shipment/area fields NULL + PII redaction check
    with tc.subTest(part="3a_3b_legacy_null_and_pii"):
        res_leg = app.focus(cust_id, cid, {"order_id": oid_legacy_null})
        tc.assertEqual(res_leg["context"].get("order_id"), oid_legacy_null)
        tc.assertIsNone(res_leg["context"].get("external_order_id"))
        msg_leg = res_leg["message"]
        tc.assertIn(oid_legacy_null, msg_leg)
        tc.assertIn("Chưa có thông tin thanh toán", msg_leg)
        tc.assertIn("Chưa có thông tin hoàn tiền", msg_leg)
        tc.assertIn("chưa có thông tin vận đơn", msg_leg.lower())
        tc.assertIn("chưa có khu vực giao", msg_leg.lower())

        pii_order = {
            **res_ship["order"],
            "recipient_name": "Phạm Văn Mật",
            "phone": "0987654321",
            "address_line": "Số 99 Đường Bí Mật, Phường 1",
        }
        pii_msg = describe_order(pii_order, STATUSES, reason_labels, details=ship_details)
        tc.assertNotIn("Phạm Văn Mật", pii_msg)
        tc.assertNotIn("0987654321", pii_msg)
        tc.assertNotIn("Số 99 Đường Bí Mật", pii_msg)

    # 6. Conversation restore & Staff Desk case payloads carry external_order_id from same-tenant orders only
    with tc.subTest(part="3b_3e_staff_desk_and_conversation_restore"):
        app.focus(cust_id, cid, {"order_id": oid_shipping})
        bstore.record_feedback(
            cust_id,
            {"conversation_id": cid, "feedback_type": "human_handoff", "reason_code": "need_human", "comment": "Cần kiểm đơn đang giao"},
        )
        desk = bstore.staff_desk_cases()
        tc.assertEqual(len(desk["waiting"]), 1)
        tc.assertEqual(desk["waiting"][0]["order_id"], oid_shipping)
        tc.assertEqual(desk["waiting"][0].get("external_order_id"), "SIM-O-00202")
        tc.assertNotEqual(desk["waiting"][0].get("external_order_id"), "OTHER-TENANT-LEAK-999")

        esc = bstore.escalations()
        tc.assertEqual(len(esc), 1)
        tc.assertEqual(esc[0]["order_id"], oid_shipping)
        tc.assertEqual(esc[0].get("external_order_id"), "SIM-O-00202")

        transcript = bstore.conversation_transcript(cid)
        tc.assertEqual(transcript["conversation"]["order_id"], oid_shipping)
        tc.assertEqual(transcript["conversation"].get("external_order_id"), "SIM-O-00202")

        convs = bstore.list_conversations(cust_id)
        matched_conv = next(c for c in convs if c["id"] == cid)
        tc.assertEqual(matched_conv["order_id"], oid_shipping)
        tc.assertEqual(matched_conv.get("external_order_id"), "SIM-O-00202")

        # Server route fallback enrichment when external_order_id is absent on a case payload
        unenriched = {
            "waiting": [
                {"case_id": "case-same", "customer_id": cust_id, "order_id": oid_shipping},
                {"case_id": "case-other-cust", "customer_id": "cust_stranger", "order_id": oid_shipping},
                {"case_id": "case-missing", "customer_id": cust_id, "order_id": "ord_only_in_other_tenant"},
            ]
        }
        with bstore_other.connection(write=True) as db_other:
            db_other.execute(
                """INSERT INTO orders(
                       id, customer_id, product_id, source_system, external_order_id,
                       ordered_at, ordered_at_backfilled, name, variant, amount, status, version
                   ) VALUES ('ord_only_in_other_tenant', ?, 'P-101', 'marketplace_sim', 'OTHER-ONLY-777', ?, 0, 'Áo khác', 'Đen / M', 299000, 'pending', 1)""",
                (cust_id, now_ts - 1800),
            )
        enriched = _enrich_staff_cases_external_order_id(bstore, unenriched)
        tc.assertEqual(enriched["waiting"][0].get("external_order_id"), "SIM-O-00202")
        tc.assertIsNone(enriched["waiting"][1].get("external_order_id"))
        tc.assertIsNone(enriched["waiting"][2].get("external_order_id"))


class SQLiteItem3UiD8V9Tests(unittest.TestCase):
    """W6.1b-1.1 Item 3 tests on SQLite + repo-wide legacy string absence check."""

    def test_sqlite_focus_describe_order_and_staff_desk_external_order_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="r1-w61b11-item3-sq-") as tmp:
            sessions = PersistentSessions(Path(tmp) / "persistent", data_mode="persistent-demo")
            _run_item3_store_and_focus_suite(self, sessions)

    def test_legacy_demo_and_unimplemented_phrases_absent_from_repo(self) -> None:
        forbidden = (
            "chưa có trong dữ liệu demo",
            "Luồng đổi/trả chưa được triển khai",
        )
        targets = [REPO_ROOT / "retailops_conversation.py"]
        targets.extend(sorted((REPO_ROOT / "retailops").rglob("*.py")))
        targets.extend(p for p in sorted((REPO_ROOT / "web").glob("*")) if p.is_file())
        hits: list[str] = []
        for path in targets:
            content = path.read_text(encoding="utf-8")
            for phrase in forbidden:
                if phrase in content:
                    hits.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {phrase}")
        self.assertEqual(hits, [], f"Forbidden legacy phrases still present: {hits}")


@unittest.skipUnless(DSN, "PostgreSQL integration runs in CI with a dedicated test database.")
class RealPostgresItem3UiD8V9Tests(unittest.TestCase):
    """W6.1b-1.1 Item 3 tests on real PostgreSQL 16."""

    @classmethod
    def setUpClass(cls) -> None:
        import psycopg
        from scripts.postgres_test_guard import require_disposable_postgres_test_target

        require_disposable_postgres_test_target(DSN, psycopg.conninfo.conninfo_to_dict)

    def clear(self) -> None:
        from psycopg import sql
        from retailops.storage.postgres import transaction

        with transaction(DSN, write=True) as db:
            names = db.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname=? OR nspname ~ '^tenant_[a-f0-9]{32}$'",
                (IDENTITY_SCHEMA,),
            ).fetchall()
            for row in names:
                db.raw.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(row["nspname"])))

    def setUp(self) -> None:
        from retailops.storage.pg_repositories import PostgresIdentityStore

        self.temp = tempfile.TemporaryDirectory(prefix="r1-w61b11-item3-pg-")
        self.addCleanup(self.temp.cleanup)
        self.clear()
        self.addCleanup(self.clear)
        PostgresIdentityStore(DSN, create=True)
        self.sessions = PostgresSessions(DSN, api_daily_limit=5, data_root=Path(self.temp.name))

    def test_real_postgres_focus_describe_order_and_staff_desk_external_order_id(self) -> None:
        _run_item3_store_and_focus_suite(self, self.sessions)
        key = self.sessions.control.tenant("tenant-a")["storage_key"]
        self.assertTrue(tenant_schema(key).startswith("tenant_"))


if __name__ == "__main__":
    unittest.main()
