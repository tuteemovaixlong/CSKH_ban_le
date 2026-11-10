"""Tests for Phase R1 W6.1b-2 Item 1: encrypted `order_recipients` ingest & retention lifecycle."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from retailops.core import ApiError
from retailops.integration.contract import iso_vn_to_epoch
from retailops.integration.demo_seed import seed_demo_store_events
from retailops.integration.ingest import IntegrationIngestService
from retailops.integration.recipient_crypto import RecipientKeyring
from retailops.identity.persistent import PersistentSessions
from tests._w6_1b_2_pg_base import RealPostgresW61b2Base, pg_test_enabled


def _make_order_created(
    *,
    event_id: str = "evt:w61b2:i1:ord1:1",
    ext_order_id: str = "SIM-ORD-I1-001",
    ext_customer_id: str = "SIM-CUST-I1-001",
    occurred_at: str = "2026-10-15T08:00:00+07:00",
    ordered_at: str = "2026-10-15T08:00:00+07:00",
    promised_by: str = "2026-10-17T08:00:00+07:00",
    ext_product_id: str = "PROD-I1-101",
    sku: str = "SKU-I1-101",
    recipient_name: str = "Nguyễn Thị Bích Ngọc",
    recipient_phone: str = "0903127418",
    recipient_address: str = "Số 45 Đường Lê Thánh Tôn, Lầu 3",
) -> dict:
    return {
        "contract": "retailops-integration-v2",
        "event_id": event_id,
        "event_type": "order.created",
        "source_system": "marketplace_sim",
        "merchant_id": "MERCHANT-SIM-001",
        "occurred_at": occurred_at,
        "sequence": 1,
        "data": {
            "external_order_id": ext_order_id,
            "external_customer_id": ext_customer_id,
            "ordered_at": ordered_at,
            "promised_delivery_by": promised_by,
            "payment_method": "cod",
            "shipping_fee": 25000,
            "total": 425000,
            "currency": "VND",
            "recipient": {
                "name": recipient_name,
                "phone": recipient_phone,
                "address_line": recipient_address,
                "ward": "Phường Bến Nghé",
                "district": "Quận 1",
                "province": "TP. Hồ Chí Minh",
            },
            "items": [
                {
                    "external_product_id": ext_product_id,
                    "sku": sku,
                    "title": "Máy sấy tóc ion âm",
                    "variant_name": "Trắng",
                    "quantity": 1,
                    "unit_price": 400000,
                }
            ],
        },
    }


def _make_product_upserted(
    *,
    event_id: str = "evt:w61b2:i1:prod:1",
    ext_product_id: str = "PROD-I1-101",
    sku: str = "SKU-I1-101",
    warranty_days: int = 365,
    sequence: int = 1,
) -> dict:
    return {
        "contract": "retailops-integration-v2",
        "event_id": event_id,
        "event_type": "product.upserted",
        "source_system": "marketplace_sim",
        "merchant_id": "MERCHANT-SIM-001",
        "occurred_at": "2026-10-16T09:00:00+07:00",
        "sequence": sequence,
        "data": {
            "external_product_id": ext_product_id,
            "title": "Máy sấy tóc ion âm",
            "category": "electronics",
            "price": 400000,
            "description": "Máy sấy tóc công suất cao",
            "material": "Nhựa ABS",
            "care": "Bảo quản nơi khô ráo",
            "warranty_days": warranty_days,
            "variants": [
                {
                    "sku": sku,
                    "variant_name": "Trắng",
                    "size": None,
                    "color": "Trắng",
                    "price": 400000,
                    "stock": 10,
                }
            ],
        },
    }


class SQLiteRecipientIngestItem1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="r1-w61b2-item1-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.digest_key = b"w61b2-item1-digest-secret-32byte!"
        self.recipient_secret = b"w61b2-item1-recipient-key-32byte!"
        self.keyring = RecipientKeyring.from_raw_keys({"v1": self.recipient_secret}, "v1")
        self.sessions = PersistentSessions(self.root / "persistent")
        self.store = self.sessions.provision_tenant("shop-demo", "Shop Demo", seed_demo=False)
        self.svc = IntegrationIngestService(
            self.sessions,
            digest_key=self.digest_key,
            recipient_keyring=self.keyring,
        )

    def _assert_zero_plaintext_sqlite(self, needles: list[str]) -> None:
        with self.store.connection() as db:
            tables = [
                r["name"]
                for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            ]
            for tbl in tables:
                for row in db.execute(f"SELECT * FROM {tbl}").fetchall():
                    dumped = json.dumps(dict(row), ensure_ascii=False, default=str)
                    for needle in needles:
                        self.assertNotIn(needle, dumped, f"Plaintext leaked in tenant table {tbl}")
        with self.sessions.control.connection() as id_db:
            id_tables = [
                r["name"]
                for r in id_db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            ]
            for tbl in id_tables:
                for row in id_db.execute(f"SELECT * FROM {tbl}").fetchall():
                    dumped = json.dumps(dict(row), ensure_ascii=False, default=str)
                    for needle in needles:
                        self.assertNotIn(needle, dumped, f"Plaintext leaked in identity table {tbl}")

    def test_missing_recipient_key_fails_closed_503_with_zero_rows_written(self) -> None:
        ev = _make_order_created()
        raw = json.dumps(ev, ensure_ascii=False).encode("utf-8")
        no_rcp_svc = IntegrationIngestService(self.sessions, digest_key=self.digest_key, recipient_keyring=None)
        with patch.dict(os.environ, {"RETAILOPS_RECIPIENT_KEY_FILE": ""}, clear=False):
            with self.assertRaises(ApiError) as ctx:
                no_rcp_svc.ingest_event(raw, tenant_id="shop-demo")
        self.assertEqual((ctx.exception.status, ctx.exception.code), (503, "recipient_key_unavailable"))

        with self.store.connection() as db:
            for tbl in ("orders", "order_items", "order_recipients", "imported_events"):
                cnt = db.execute(f"SELECT COUNT(*) AS c FROM {tbl}").fetchone()["c"]
                self.assertEqual(cnt, 0, f"{tbl} must remain empty after 503 missing recipient key")

        # Production demo seed also fails closed with 503 when recipient key is missing
        digest_path = self.root / "digest_key"
        digest_path.write_bytes(self.digest_key)
        with patch.dict(
            os.environ,
            {
                "RETAILOPS_ENV": "production",
                "RETAILOPS_EVENT_DIGEST_KEY_FILE": str(digest_path),
                "RETAILOPS_RECIPIENT_KEY_FILE": "",
            },
            clear=False,
        ):
            with self.assertRaises(ApiError) as prod_err:
                seed_demo_store_events(self.store, sessions=self.sessions)
        self.assertEqual((prod_err.exception.status, prod_err.exception.code), (503, "recipient_key_unavailable"))

    def test_order_created_encrypts_recipient_zero_plaintext_and_retention_lifecycle(self) -> None:
        plain_name = "Nguyễn Thị Bích Ngọc"
        plain_phone = "0903127418"
        plain_addr = "Số 45 Đường Lê Thánh Tôn, Lầu 3"
        ev = _make_order_created(
            recipient_name=plain_name,
            recipient_phone=plain_phone,
            recipient_address=plain_addr,
        )
        res = self.svc.ingest_event(
            json.dumps(ev, ensure_ascii=False).encode("utf-8"),
            tenant_id="shop-demo",
        )
        self.assertTrue(res.success)
        oid = res.order_id

        with self.store.connection() as db:
            rec = dict(db.execute("SELECT * FROM order_recipients WHERE order_id=?", (oid,)).fetchone())
            self.assertTrue(str(rec["name_enc"]).startswith("r1gcm1:v1:"))
            self.assertTrue(str(rec["phone_enc"]).startswith("r1gcm1:v1:"))
            self.assertTrue(str(rec["address_line_enc"]).startswith("r1gcm1:v1:"))
            self.assertEqual(rec["phone_masked"], "0903.xxx.418")
            self.assertEqual(rec["ward"], "Phường Bến Nghé")
            self.assertEqual(rec["district"], "Quận 1")
            self.assertEqual(rec["province"], "TP. Hồ Chí Minh")
            self.assertIsNone(rec["retention_until"])
            self.assertEqual(rec["phone_lookup_hmac"], self.keyring.compute_phone_lookup_hmac(plain_phone))

            # Decrypt with matching AAD succeeds; wrong order_id fails authentication
            self.assertEqual(
                self.keyring.decrypt_field(
                    rec["name_enc"], tenant_id="shop-demo", order_id=oid, field_name="name"
                ),
                plain_name,
            )
            self.assertEqual(
                self.keyring.decrypt_field(
                    rec["phone_enc"], tenant_id="shop-demo", order_id=oid, field_name="phone"
                ),
                plain_phone,
            )
            self.assertEqual(
                self.keyring.decrypt_field(
                    rec["address_line_enc"], tenant_id="shop-demo", order_id=oid, field_name="address_line"
                ),
                plain_addr,
            )
            with self.assertRaises(ApiError) as bad_aad:
                self.keyring.decrypt_field(
                    rec["phone_enc"], tenant_id="shop-demo", order_id=oid + "_wrong", field_name="phone"
                )
            self.assertEqual(bad_aad.exception.code, "recipient_decrypt_failed")

        self._assert_zero_plaintext_sqlite([plain_name, plain_phone, plain_addr, "Lê Thánh Tôn"])

        # Transition to delivered without product warranty -> delivered_at + 90d
        deliv_iso = "2026-10-16T15:30:00+07:00"
        deliv_ts = iso_vn_to_epoch(deliv_iso, "delivered_at")
        self.svc.ingest_event(
            json.dumps(
                {
                    "contract": "retailops-integration-v2",
                    "event_id": "evt:w61b2:i1:ord1:2",
                    "event_type": "order.status_changed",
                    "source_system": "marketplace_sim",
                    "merchant_id": "MERCHANT-SIM-001",
                    "occurred_at": deliv_iso,
                    "sequence": 2,
                    "data": {
                        "external_order_id": "SIM-ORD-I1-001",
                        "status": "delivered",
                        "reason": None,
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            tenant_id="shop-demo",
        )
        with self.store.connection() as db:
            rec90 = dict(db.execute("SELECT * FROM order_recipients WHERE order_id=?", (oid,)).fetchone())
            self.assertAlmostEqual(rec90["retention_until"], deliv_ts + 90 * 86400.0, places=3)

        # Product upserted later with warranty_days=365 (> 90) updates retention_until to delivered_at + 365d
        self.svc.ingest_event(
            json.dumps(_make_product_upserted(warranty_days=365), ensure_ascii=False).encode("utf-8"),
            tenant_id="shop-demo",
        )
        with self.store.connection() as db:
            rec365 = dict(db.execute("SELECT * FROM order_recipients WHERE order_id=?", (oid,)).fetchone())
            self.assertAlmostEqual(rec365["retention_until"], deliv_ts + 365 * 86400.0, places=3)

        # Second order cancelled via order.status_changed -> cancelled_at + 30d
        ev2 = _make_order_created(
            event_id="evt:w61b2:i1:ord2:1",
            ext_order_id="SIM-ORD-I1-002",
            ext_customer_id="SIM-CUST-I1-002",
        )
        res2 = self.svc.ingest_event(json.dumps(ev2, ensure_ascii=False).encode("utf-8"), tenant_id="shop-demo")
        cancel_iso = "2026-10-15T12:00:00+07:00"
        cancel_ts = iso_vn_to_epoch(cancel_iso, "occurred_at")
        self.svc.ingest_event(
            json.dumps(
                {
                    "contract": "retailops-integration-v2",
                    "event_id": "evt:w61b2:i1:ord2:2",
                    "event_type": "order.status_changed",
                    "source_system": "marketplace_sim",
                    "merchant_id": "MERCHANT-SIM-001",
                    "occurred_at": cancel_iso,
                    "sequence": 2,
                    "data": {
                        "external_order_id": "SIM-ORD-I1-002",
                        "status": "cancelled",
                        "reason": "buyer_requested",
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            tenant_id="shop-demo",
        )
        with self.store.connection() as db:
            rec_can = dict(
                db.execute("SELECT * FROM order_recipients WHERE order_id=?", (res2.order_id,)).fetchone()
            )
            self.assertAlmostEqual(rec_can["retention_until"], cancel_ts + 30 * 86400.0, places=3)

        # Third order cancelled via manager_update_order_status -> retention_until = now + 30d
        ev3 = _make_order_created(
            event_id="evt:w61b2:i1:ord3:1",
            ext_order_id="SIM-ORD-I1-003",
            ext_customer_id="SIM-CUST-I1-003",
        )
        res3 = self.svc.ingest_event(json.dumps(ev3, ensure_ascii=False).encode("utf-8"), tenant_id="shop-demo")
        mgr_actor = {"principal_id": "p_mgr", "role": "manager", "tenant_id": "shop-demo"}
        before_mgr = float(self.store._now())
        self.store.manager_update_order_status(res3.order_id, "cancelled", actor=mgr_actor)
        after_mgr = float(self.store._now())
        with self.store.connection() as db:
            rec_mgr = dict(
                db.execute("SELECT * FROM order_recipients WHERE order_id=?", (res3.order_id,)).fetchone()
            )
            self.assertGreaterEqual(rec_mgr["retention_until"], before_mgr + 30 * 86400.0 - 1.0)
            self.assertLessEqual(rec_mgr["retention_until"], after_mgr + 30 * 86400.0 + 1.0)


@unittest.skipUnless(
    pg_test_enabled(),
    "PostgreSQL integration runs in CI with RETAILOPS_TEST_DATABASE_URL.",
)
class RealPostgresRecipientIngestItem1Tests(RealPostgresW61b2Base):
    """Real PostgreSQL verification for Item 1: encrypted `order_recipients` & zero plaintext leak."""

    def test_real_postgres_order_recipients_encryption_retention_and_zero_plaintext(self) -> None:
        digest_key = b"pg-item1-digest-secret-32-bytes!!"
        keyring = RecipientKeyring.from_raw_keys({"v1": b"pg-item1-recipient-key-32-bytes!!"}, "v1")
        svc = IntegrationIngestService(
            self.sessions,
            digest_key=digest_key,
            recipient_keyring=keyring,
        )

        plain_name = "Trần Hoàng Minh Châu"
        plain_phone = "0918456721"
        plain_addr = "128 Nguyễn Thị Minh Khai, Căn hộ B12"

        # Missing key fails closed on PostgreSQL with zero rows committed
        no_key_svc = IntegrationIngestService(self.sessions, digest_key=digest_key, recipient_keyring=None)
        with patch.dict(os.environ, {"RETAILOPS_RECIPIENT_KEY_FILE": ""}, clear=False):
            with self.assertRaises(ApiError) as err:
                no_key_svc.ingest_event(
                    json.dumps(_make_order_created(), ensure_ascii=False).encode("utf-8"),
                    tenant_id="shop-demo",
                )
        self.assertEqual((err.exception.status, err.exception.code), (503, "recipient_key_unavailable"))

        # Ingest product (warranty 180d) + order + delivered status on real PostgreSQL
        svc.ingest_event(
            json.dumps(_make_product_upserted(warranty_days=180), ensure_ascii=False).encode("utf-8"),
            tenant_id="shop-demo",
        )
        ev = _make_order_created(
            recipient_name=plain_name,
            recipient_phone=plain_phone,
            recipient_address=plain_addr,
        )
        res = svc.ingest_event(
            json.dumps(ev, ensure_ascii=False).encode("utf-8"),
            tenant_id="shop-demo",
        )
        oid = res.order_id

        with self.store.connection() as db:
            rec = dict(db.execute("SELECT * FROM order_recipients WHERE order_id=?", (oid,)).fetchone())
            self.assertIsNone(rec["retention_until"])
            self.assertEqual(rec["phone_masked"], "0918.xxx.721")
            self.assertEqual(
                keyring.decrypt_field(
                    rec["address_line_enc"],
                    tenant_id="shop-demo",
                    order_id=oid,
                    field_name="address_line",
                ),
                plain_addr,
            )

        deliv_iso = "2026-10-16T18:00:00+07:00"
        deliv_ts = iso_vn_to_epoch(deliv_iso, "delivered_at")
        svc.ingest_event(
            json.dumps(
                {
                    "contract": "retailops-integration-v2",
                    "event_id": "evt:w61b2:i1:pg:deliv",
                    "event_type": "order.status_changed",
                    "source_system": "marketplace_sim",
                    "merchant_id": "MERCHANT-SIM-001",
                    "occurred_at": deliv_iso,
                    "sequence": 2,
                    "data": {
                        "external_order_id": "SIM-ORD-I1-001",
                        "status": "delivered",
                        "reason": None,
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            tenant_id="shop-demo",
        )
        with self.store.connection() as db:
            rec_after = dict(db.execute("SELECT * FROM order_recipients WHERE order_id=?", (oid,)).fetchone())
            self.assertAlmostEqual(rec_after["retention_until"], deliv_ts + 180 * 86400.0, places=3)

        scanned = self.assert_no_plaintext_in_all_pg_schemas(
            [plain_name, plain_phone, plain_addr, "Nguyễn Thị Minh Khai"]
        )
        self.assertGreater(scanned, 0)


if __name__ == "__main__":
    unittest.main()
