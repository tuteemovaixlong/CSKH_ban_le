"""Integration and contract tests for RetailOps integration event import (migrated from P5-C onto v2 in W6.1b-1).

Verifies:
- Tenant validation (rejects non-existent / inactive tenants).
- P5-K4: Tenant-scoped mapping (external_customer_id -> customer_id) and audit trail.
- Explicit external customer pre-linking.
- P5-K5: Idempotency and replay detection without duplicate mutations or audit logs.
- Atomic rollback: database failure leaves no partial orders, items, imported_events or audit logs.
- P5-K6: Customer order visibility and isolation (customer only reads their own orders).
- Multi-item order persistence into order_items.
- ToolCache invalidation upon commit.
"""
from __future__ import annotations

from contextlib import contextmanager
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from retailops.business.store import BusinessStore
from retailops.core import ApiError
from retailops.identity.persistent import PersistentSessions
from retailops.integration.ingest import IntegrationIngestService
from retailops.integration.recipient_crypto import RecipientKeyring

TEST_DIGEST_KEY = b"test-digest-key-32-bytes-minimum!!"
TEST_RECIPIENT_KEYRING = RecipientKeyring.from_raw_keys(
    {"v1": b"test-recipient-key-32-bytes-min!"}, "v1"
)


def make_v2_order_created(
    *,
    external_order_id: str = "SIM-O-00001",
    external_customer_id: str = "sim_buyer_001",
    source_system: str = "marketplace_sim",
    merchant_id: str = "shop-alpha",
    event_id: str | None = None,
    sequence: int = 1,
    items: list[dict] | None = None,
    shipping_fee: int = 0,
    total: int | None = None,
) -> dict:
    resolved_items = items or [
        {
            "sku": "SKU-P601-WHT-M",
            "external_product_id": "P-601",
            "title": "Áo sơ mi lụa công sở",
            "variant_name": "Trắng / M",
            "quantity": 1,
            "unit_price": 450000,
        }
    ]
    computed_total = (
        sum(int(i["quantity"]) * int(i["unit_price"]) for i in resolved_items) + shipping_fee
        if total is None
        else total
    )
    return {
        "contract": "retailops-integration-v2",
        "event_id": event_id or f"evt_{uuid.uuid4().hex[:20]}",
        "event_type": "order.created",
        "source_system": source_system,
        "merchant_id": merchant_id,
        "occurred_at": "2026-11-01T10:00:00+07:00",
        "sequence": sequence,
        "data": {
            "external_order_id": external_order_id,
            "external_customer_id": external_customer_id,
            "ordered_at": "2026-11-01T10:00:00+07:00",
            "items": resolved_items,
            "shipping_fee": shipping_fee,
            "total": computed_total,
            "currency": "VND",
            "payment_method": "cod",
            "promised_delivery_by": "2026-11-04T10:00:00+07:00",
            "recipient": {
                "name": "Nguyễn Văn Thử",
                "phone": "0901234567",
                "address_line": "123 Đường Mẫu",
                "ward": "Phường Bến Nghé",
                "district": "Quận 1",
                "province": "TP. Hồ Chí Minh",
            },
        },
    }


class Phase5SalesSimulatorImportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp_dir.name)
        self.sessions = PersistentSessions(self.directory, data_mode="persistent-demo")
        self.tenant_id = "shop-alpha-01"
        self.sessions.provision_tenant(self.tenant_id, "Shop Alpha", seed_demo=True)
        self.service = IntegrationIngestService(
            self.sessions, digest_key=TEST_DIGEST_KEY, recipient_keyring=TEST_RECIPIENT_KEYRING
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_tenant_validation_rejects_unknown_or_inactive(self):
        """Unknown or inactive tenants are rejected."""
        event = make_v2_order_created(external_order_id="SIM-O-UNK-01")
        with self.assertRaises(ApiError) as ctx:
            self.service.ingest_event(event, tenant_id="unknown-shop-404")
        self.assertEqual(ctx.exception.code, "tenant_not_found")

        self.sessions.provision_tenant("shop-inactive", "Shop Inactive")
        with self.sessions.control.connection(write=True) as db:
            db.execute("UPDATE tenants SET active=0 WHERE id='shop-inactive'")

        event_inactive = make_v2_order_created(external_order_id="SIM-O-INACT-01")
        with self.assertRaises(ApiError) as ctx:
            self.service.ingest_event(event_inactive, tenant_id="shop-inactive")
        self.assertEqual(ctx.exception.code, "tenant_inactive")

    def test_tenant_scoped_customer_mapping_and_cross_tenant_isolation(self):
        """P5-K4: external_customer_id is tenant-scoped; same external ID in 2 tenants maps to distinct RetailOps customers."""
        tenant_a = self.tenant_id
        tenant_b = "shop-beta-02"
        self.sessions.provision_tenant(tenant_b, "Shop Beta", seed_demo=True)

        ext_cust_id = "pos_device_100_customer_77"

        event_a = make_v2_order_created(
            external_order_id="SIM-O-TENA-001",
            external_customer_id=ext_cust_id,
        )
        res_a = self.service.ingest_event(event_a, tenant_id=tenant_a)
        cust_a = res_a.customer_id
        self.assertTrue(cust_a.startswith("cust_"))

        map_a = self.sessions.control.external_customer_mapping(
            tenant_a, "marketplace_sim", ext_cust_id
        )
        self.assertIsNotNone(map_a)
        self.assertEqual(map_a["customer_id"], cust_a)

        event_b = make_v2_order_created(
            external_order_id="SIM-O-TENB-001",
            external_customer_id=ext_cust_id,
        )
        res_b = self.service.ingest_event(event_b, tenant_id=tenant_b)
        cust_b = res_b.customer_id
        self.assertTrue(cust_b.startswith("cust_"))
        self.assertNotEqual(cust_a, cust_b)

        map_b = self.sessions.control.external_customer_mapping(
            tenant_b, "marketplace_sim", ext_cust_id
        )
        self.assertIsNotNone(map_b)
        self.assertEqual(map_b["customer_id"], cust_b)

        event_a2 = make_v2_order_created(
            external_order_id="SIM-O-TENA-002",
            external_customer_id=ext_cust_id,
        )
        res_a2 = self.service.ingest_event(event_a2, tenant_id=tenant_a)
        self.assertEqual(res_a2.customer_id, cust_a)

        with self.sessions.control.connection() as db:
            events = db.execute(
                "SELECT * FROM identity_events WHERE kind='external_customer_mapped'"
            ).fetchall()
            self.assertGreaterEqual(len(events), 2)

    def test_explicit_customer_link(self):
        """Can explicitly pre-link external_customer_id to an existing customer_id."""
        bstore = self.sessions.business_store(self.tenant_id)
        target_cid = "cust_pre_existing_google_user"

        with bstore.connection(write=True) as db:
            db.execute(
                "INSERT INTO customers (id, name) VALUES (?, ?)",
                (target_cid, "Google User Pre-Linked"),
            )

        self.service.link_external_customer(
            self.tenant_id, "pos_online", "external_pos_buyer_888", target_cid
        )

        event = make_v2_order_created(
            source_system="pos_online",
            external_customer_id="external_pos_buyer_888",
            external_order_id="SIM-O-LINK-001",
        )
        res = self.service.ingest_event(
            event, tenant_id=self.tenant_id, connector_source_system="pos_online"
        )
        self.assertEqual(res.customer_id, target_cid)
        self.assertEqual(res.external_order_id, "SIM-O-LINK-001")

        order = bstore.lookup(target_cid, res.order_id)
        self.assertEqual(order["id"], res.order_id)
        self.assertEqual(order["external_order_id"], "SIM-O-LINK-001")
        self.assertEqual(order["customer_id"], target_cid)

    def test_idempotent_event_ingestion_and_replay_detection(self):
        """P5-K5: Replaying the same event does not duplicate orders, items, or audit records."""
        event = make_v2_order_created(
            external_order_id="SIM-O-REPLAY-001",
            external_customer_id="pos_repeat_buyer",
        )

        res1 = self.service.ingest_event(event, tenant_id=self.tenant_id)
        self.assertTrue(res1.success)
        self.assertFalse(res1.is_replay)
        self.assertEqual(res1.status, "imported")

        bstore = self.sessions.business_store(self.tenant_id)
        with bstore.connection() as db:
            orders_cnt1 = db.execute(
                "SELECT count(*) as c FROM orders WHERE id=?", (res1.order_id,)
            ).fetchone()["c"]
            items_cnt1 = db.execute(
                "SELECT count(*) as c FROM order_items WHERE order_id=?", (res1.order_id,)
            ).fetchone()["c"]
            audit_cnt1 = db.execute(
                "SELECT count(*) as c FROM business_events WHERE kind='order_imported' AND order_id=?",
                (res1.order_id,),
            ).fetchone()["c"]
            imported_cnt1 = db.execute(
                "SELECT count(*) as c FROM imported_events WHERE event_id=?",
                (event["event_id"],),
            ).fetchone()["c"]

        self.assertEqual(orders_cnt1, 1)
        self.assertGreater(items_cnt1, 0)
        self.assertEqual(audit_cnt1, 1)
        self.assertEqual(imported_cnt1, 1)

        res2 = self.service.ingest_event(event, tenant_id=self.tenant_id)
        self.assertTrue(res2.success)
        self.assertTrue(res2.is_replay)
        self.assertEqual(res2.status, "already_processed")
        self.assertEqual(res2.order_id, res1.order_id)
        self.assertEqual(res2.customer_id, res1.customer_id)

        with bstore.connection() as db:
            orders_cnt2 = db.execute(
                "SELECT count(*) as c FROM orders WHERE id=?", (res1.order_id,)
            ).fetchone()["c"]
            items_cnt2 = db.execute(
                "SELECT count(*) as c FROM order_items WHERE order_id=?", (res1.order_id,)
            ).fetchone()["c"]
            audit_cnt2 = db.execute(
                "SELECT count(*) as c FROM business_events WHERE kind='order_imported' AND order_id=?",
                (res1.order_id,),
            ).fetchone()["c"]
            imported_cnt2 = db.execute(
                "SELECT count(*) as c FROM imported_events WHERE event_id=?",
                (event["event_id"],),
            ).fetchone()["c"]

        self.assertEqual(orders_cnt2, 1)
        self.assertEqual(items_cnt2, items_cnt1)
        self.assertEqual(audit_cnt2, 1)
        self.assertEqual(imported_cnt2, 1)

    def test_atomic_rollback_on_database_error_leaves_no_traces(self):
        """Simulated error during order processing rolls back transaction completely."""
        event = make_v2_order_created(
            external_order_id="SIM-O-ROLLBACK-001",
            external_customer_id="rollback_buyer_999",
        )

        orig_connection = BusinessStore.connection

        class FaultyDBProxy:
            def __init__(self, real_db):
                self._real_db = real_db

            def execute(self, sql, *args, **kwargs):
                if "INSERT INTO order_items" in sql:
                    raise sqlite3.OperationalError(
                        "Simulated disk error or constraint crash during order_items insert"
                    )
                return self._real_db.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._real_db, name)

        @contextmanager
        def faulty_connection(self_bs, *args, **kwargs):
            with orig_connection(self_bs, *args, **kwargs) as real_db:
                yield FaultyDBProxy(real_db)

        with patch.object(BusinessStore, "connection", faulty_connection):
            with self.assertRaises(ApiError) as ctx:
                self.service.ingest_event(event, tenant_id=self.tenant_id)
            self.assertEqual(ctx.exception.code, "database_unavailable")

        bstore = self.sessions.business_store(self.tenant_id)
        with bstore.connection() as db:
            order_row = db.execute(
                "SELECT * FROM orders WHERE external_order_id='SIM-O-ROLLBACK-001'"
            ).fetchone()
            self.assertIsNone(order_row)
            event_row = db.execute(
                "SELECT * FROM imported_events WHERE event_id=?", (event["event_id"],)
            ).fetchone()
            self.assertIsNone(event_row)

        mapping = self.sessions.control.external_customer_mapping(
            self.tenant_id, "marketplace_sim", "rollback_buyer_999"
        )
        self.assertIsNone(mapping)

        res_retry = self.service.ingest_event(event, tenant_id=self.tenant_id)
        self.assertTrue(res_retry.success)
        self.assertEqual(res_retry.status, "imported")

        with bstore.connection() as db:
            order_row = db.execute(
                "SELECT * FROM orders WHERE id=?", (res_retry.order_id,)
            ).fetchone()
            self.assertIsNotNone(order_row)

    def test_customer_order_visibility_and_isolation(self):
        """P5-K6: Customer only sees their imported order; accessing other customer's order is forbidden."""
        event_1 = make_v2_order_created(
            external_order_id="SIM-O-VIS-001",
            external_customer_id="cust_one_external",
        )
        event_2 = make_v2_order_created(
            external_order_id="SIM-O-VIS-002",
            external_customer_id="cust_two_external",
        )

        res_1 = self.service.ingest_event(event_1, tenant_id=self.tenant_id)
        res_2 = self.service.ingest_event(event_2, tenant_id=self.tenant_id)

        cid_1 = res_1.customer_id
        cid_2 = res_2.customer_id
        self.assertNotEqual(cid_1, cid_2)

        bstore = self.sessions.business_store(self.tenant_id)

        orders_1 = bstore.orders(cid_1)
        order_ids_1 = [o["id"] for o in orders_1]
        self.assertIn(res_1.order_id, order_ids_1)
        self.assertNotIn(res_2.order_id, order_ids_1)

        orders_2 = bstore.orders(cid_2)
        order_ids_2 = [o["id"] for o in orders_2]
        self.assertIn(res_2.order_id, order_ids_2)
        self.assertNotIn(res_1.order_id, order_ids_2)

        with self.assertRaises(ApiError) as ctx:
            bstore.lookup(cid_1, res_2.order_id)
        self.assertEqual(ctx.exception.code, "order_not_found")

        with self.assertRaises(ApiError) as ctx:
            bstore.lookup(cid_2, res_1.order_id)
        self.assertEqual(ctx.exception.code, "order_not_found")

    def test_multi_item_order_persists_to_order_items(self):
        """Multi-item orders store individual line items in order_items with summary in orders."""
        items = [
            {
                "sku": "SKU-P601-WHT-M",
                "external_product_id": "P-601",
                "title": "Áo sơ mi lụa công sở",
                "variant_name": "Trắng / M",
                "quantity": 2,
                "unit_price": 450000,
            },
            {
                "sku": "SKU-P602-BLK-L",
                "external_product_id": "P-602",
                "title": "Quần tây đen hàn quốc",
                "variant_name": "Đen / L",
                "quantity": 1,
                "unit_price": 520000,
            },
        ]
        total = 2 * 450000 + 1 * 520000
        event = make_v2_order_created(
            external_order_id="SIM-O-MULTI-001",
            items=items,
            total=total,
        )

        res = self.service.ingest_event(event, tenant_id=self.tenant_id)
        self.assertTrue(res.success)
        self.assertEqual(res.items_count, 2)
        self.assertEqual(res.total, 1420000)

        bstore = self.sessions.business_store(self.tenant_id)
        order = bstore.lookup(res.customer_id, res.order_id)
        self.assertEqual(order["amount"], 1420000)
        self.assertEqual(order["status"], "pending")
        self.assertIn("Áo sơ mi lụa công sở", order["name"])
        self.assertIn("1 sản phẩm khác", order["name"])

        line_items = bstore.order_items(res.order_id)
        self.assertEqual(len(line_items), 2)
        p_ids = {it["product_id"] for it in line_items}
        self.assertEqual(p_ids, {"P-601", "P-602"})
        self.assertEqual(sum(it["subtotal"] for it in line_items), 1420000)

    def test_tool_cache_invalidation_after_import(self):
        """Ingesting an order invalidates ToolCache for the mapped customer."""
        customer_id = "cust_cache_test_01"
        self.service.link_external_customer(
            self.tenant_id, "marketplace_sim", "ext_cache_user", customer_id
        )

        tool_cache = self.sessions.tool_caches.setdefault(self.tenant_id, MagicMock())
        tool_cache.invalidate = MagicMock()

        event = make_v2_order_created(
            external_order_id="SIM-O-CACHE-001",
            external_customer_id="ext_cache_user",
        )
        res = self.service.ingest_event(event, tenant_id=self.tenant_id)

        tool_cache.invalidate.assert_called_once_with(
            customer=customer_id, tenant_id=self.tenant_id, order_id=res.order_id
        )


if __name__ == "__main__":
    unittest.main()
