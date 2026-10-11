"""Unit, integration and contract tests for Phase 5 P5-C: Sales Simulator & Import Contract.

Verifies:
- Sales simulator runs strictly offline/dev, emitting canonical events without writing directly to DB.
- Canonical event schema has exactly the 11 fields:
    source_system, event_id, tenant, external_customer_id, order_id, status, items, total, currency, timestamp, signature.
- Strict HMAC-SHA256 signature verification and constant-time tamper detection.
- P5-K4: Tenant-scoped mapping (external_customer_id -> customer_id), audit trail, and strict rejection of email as key.
- Timestamp drift / replay attack mitigation.
- Tenant validation (rejects non-existent / inactive tenants).
- P5-K5: Idempotency and replay detection without duplicate mutations or audit logs.
- Atomic rollback: database failure leaves no partial orders, items, imported_events or audit logs.
- P5-K6: Customer order visibility and isolation (customer only reads their own orders).
- ToolCache invalidation upon commit.
- Deterministic signed fixtures.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from retailops.core import ApiError
from retailops.identity.persistent import PersistentSessions
from retailops.sales.adapter import SalesImportAdapter
from retailops.sales.events import (
    CANONICAL_FIELDS,
    VALID_STATUSES,
    compute_signature,
    parse_timestamp,
    sign_event,
    validate_event_schema,
    validate_timestamp,
    verify_event_signature,
)
from retailops.sales.fixtures import get_signed_fixtures
from retailops.sales.simulator import DEFAULT_DEV_SECRET, SalesSimulator


class Phase5SalesSimulatorImportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp_dir.name)
        self.sessions = PersistentSessions(self.directory, data_mode="persistent-demo")
        self.tenant_id = "shop-alpha-01"
        self.sessions.provision_tenant(self.tenant_id, "Shop Alpha", seed_demo=True)
        self.simulator = SalesSimulator(tenant_id=self.tenant_id, secret_key=DEFAULT_DEV_SECRET)
        self.adapter = SalesImportAdapter(self.sessions, default_secret=DEFAULT_DEV_SECRET)

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Simulator Isolation & Canonical Event Contract
    # -------------------------------------------------------------------------

    def test_simulator_emits_valid_canonical_event_without_db(self):
        """Simulator emits valid canonical 11-field events and does NOT write directly to DB."""
        # Inspect that simulator has no DB connection or writer methods
        self.assertFalse(hasattr(self.simulator, "db"))
        self.assertFalse(hasattr(self.simulator, "connection"))
        self.assertFalse(hasattr(self.simulator, "execute"))

        event = self.simulator.create_order_event(
            order_id="O-SIM-001",
            external_customer_id="pos_buyer_999",
            status="delivered",
        )

        # Check all 11 canonical fields
        for field in CANONICAL_FIELDS:
            self.assertIn(field, event)
        self.assertEqual(len(event), 11)

        self.assertEqual(event["source_system"], "sales_simulator")
        self.assertEqual(event["tenant"], self.tenant_id)
        self.assertEqual(event["order_id"], "O-SIM-001")
        self.assertEqual(event["external_customer_id"], "pos_buyer_999")
        self.assertEqual(event["status"], "delivered")
        self.assertEqual(event["currency"], "VND")
        self.assertTrue(len(event["signature"]) == 64)

        # Check that DB was untouched: orders table has no O-SIM-001
        bstore = self.sessions.business_store(self.tenant_id)
        with bstore.connection() as db:
            row = db.execute("SELECT * FROM orders WHERE id='O-SIM-001'").fetchone()
            self.assertIsNone(row)

    # -------------------------------------------------------------------------
    # 2. HMAC Signature Validation & Tampering Detection
    # -------------------------------------------------------------------------

    def test_hmac_signature_verification_and_tamper_rejection(self):
        """Valid HMAC signature succeeds; any payload tampering is rejected."""
        event = self.simulator.create_order_event(order_id="O-HMAC-001")

        # 1. Valid signature passes
        self.assertTrue(verify_event_signature(event, DEFAULT_DEV_SECRET))
        result = self.adapter.ingest_event(event)
        self.assertTrue(result.success)
        self.assertEqual(result.status, "imported")

        # 2. Tampering total amount is rejected
        tampered_total = self.simulator.create_order_event(order_id="O-HMAC-002")
        tampered_total["total"] = tampered_total["total"] + 10000
        # If schema validation passes (if items updated) or signature check fails
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(tampered_total)
        self.assertIn(ctx.exception.code, ("total_mismatch", "invalid_signature"))

        # 3. Tampering order_id is rejected by HMAC
        tampered_id = self.simulator.create_order_event(order_id="O-HMAC-003")
        tampered_id["order_id"] = "O-HMAC-003-HACKED"
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(tampered_id)
        self.assertEqual(ctx.exception.code, "invalid_signature")

        # 4. Tampering external_customer_id is rejected by HMAC
        tampered_cust = self.simulator.create_order_event(order_id="O-HMAC-004")
        tampered_cust["external_customer_id"] = "impostor_cust_007"
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(tampered_cust)
        self.assertEqual(ctx.exception.code, "invalid_signature")

        # 5. Wrong secret key is rejected
        event_wrong_secret = self.simulator.create_order_event(
            order_id="O-HMAC-005", secret_override="wrong_secret_key_123"
        )
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(event_wrong_secret)
        self.assertEqual(ctx.exception.code, "invalid_signature")

    # -------------------------------------------------------------------------
    # 3. Schema Validation & Non-Email Enforcement (P5-K4)
    # -------------------------------------------------------------------------

    def test_schema_validation_rejects_missing_fields(self):
        """Missing canonical fields are rejected with descriptive ApiError."""
        for field in CANONICAL_FIELDS:
            event = self.simulator.create_order_event()
            del event[field]
            with self.assertRaises(ApiError) as ctx:
                validate_event_schema(event)
            self.assertEqual(ctx.exception.code, "missing_event_field")
            self.assertIn(field, ctx.exception.message)

    def test_schema_validation_rejects_invalid_status_and_items(self):
        """Invalid statuses, empty items, or mismatched totals are rejected."""
        # Invalid status
        event_bad_status = self.simulator.create_order_event(status="in_orbit")
        with self.assertRaises(ApiError) as ctx:
            validate_event_schema(event_bad_status)
        self.assertEqual(ctx.exception.code, "invalid_status")

        # Empty items list
        event_no_items = self.simulator.create_order_event(items=[])
        with self.assertRaises(ApiError) as ctx:
            validate_event_schema(event_no_items)
        self.assertEqual(ctx.exception.code, "invalid_items")

        # Invalid item quantity <= 0
        event_zero_qty = self.simulator.create_order_event(
            items=[{"product_id": "P-601", "product_title": "Áo", "quantity": 0, "unit_price": 100000}]
        )
        with self.assertRaises(ApiError) as ctx:
            validate_event_schema(event_zero_qty)
        self.assertEqual(ctx.exception.code, "invalid_item_quantity")

    def test_schema_strictly_rejects_email_as_external_customer_id(self):
        """P5-K4 rule: 'Không dùng email làm khóa' — emails are rejected as external_customer_id."""
        prohibited_emails = [
            "customer.alpha@example.com",
            "test_buyer+tag@gmail.com",
            "vip.user@retail-domain.vn",
        ]
        for email in prohibited_emails:
            bad_event = self.simulator.create_email_key_event(email=email)
            with self.assertRaises(ApiError) as ctx:
                validate_event_schema(bad_event)
            self.assertEqual(ctx.exception.code, "invalid_external_customer_id")
            self.assertIn("không dùng email làm khóa", ctx.exception.message)

            with self.assertRaises(ApiError) as ctx:
                self.adapter.ingest_event(bad_event)
            self.assertEqual(ctx.exception.code, "invalid_external_customer_id")

    # -------------------------------------------------------------------------
    # 4. Timestamp Drift & Replay Window Validation
    # -------------------------------------------------------------------------

    def test_timestamp_drift_validation(self):
        """Rejects events with timestamps too far in the past or future."""
        # 1. Past event older than max_age_seconds (e.g. 1 hour ago)
        expired_event = self.simulator.create_expired_event(age_seconds=3600)
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(expired_event)
        self.assertEqual(ctx.exception.code, "expired_timestamp")

        # 2. Future-dated event beyond drift tolerance (e.g. 1 hour into future)
        future_event = self.simulator.create_future_event(future_seconds=3600)
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(future_event)
        self.assertEqual(ctx.exception.code, "future_timestamp")

        # 3. Controlled reference time allows historical replay in testing
        fixed_now = 1791720000.0  # arbitrary epoch
        event_ref = self.simulator.create_order_event(
            timestamp=datetime.fromtimestamp(fixed_now, tz=timezone.utc).isoformat()
        )
        result = self.adapter.ingest_event(event_ref, reference_time=fixed_now)
        self.assertTrue(result.success)

    # -------------------------------------------------------------------------
    # 5. Tenant Validation & Multi-Tenant Boundary
    # -------------------------------------------------------------------------

    def test_tenant_validation_rejects_unknown_or_inactive(self):
        """Unknown or inactive tenants are rejected."""
        # 1. Non-existent tenant
        event_unknown = self.simulator.create_mismatched_tenant_event("unknown-shop-404")
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(event_unknown)
        self.assertEqual(ctx.exception.code, "tenant_not_found")

        # 2. Inactive tenant
        self.sessions.provision_tenant("shop-inactive", "Shop Inactive")
        with self.sessions.control.connection(write=True) as db:
            db.execute("UPDATE tenants SET active=0 WHERE id='shop-inactive'")

        event_inactive = self.simulator.create_order_event(tenant="shop-inactive")
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(event_inactive)
        self.assertEqual(ctx.exception.code, "tenant_inactive")

    # -------------------------------------------------------------------------
    # 6. Tenant-Scoped Customer Mapping (P5-K4)
    # -------------------------------------------------------------------------

    def test_tenant_scoped_customer_mapping_and_cross_tenant_isolation(self):
        """P5-K4: external_customer_id is tenant-scoped; same external ID in 2 tenants maps to distinct RetailOps customers."""
        tenant_a = self.tenant_id
        tenant_b = "shop-beta-02"
        self.sessions.provision_tenant(tenant_b, "Shop Beta", seed_demo=True)

        ext_cust_id = "pos_device_100_customer_77"

        # 1. Ingest order for ext_cust_id in Tenant A
        event_a = self.simulator.create_order_event(
            tenant=tenant_a,
            order_id="O-TENA-001",
            external_customer_id=ext_cust_id,
        )
        res_a = self.adapter.ingest_event(event_a)
        cust_a = res_a.customer_id
        self.assertTrue(cust_a.startswith("cust_"))

        # Verify mapping in identity store for Tenant A
        map_a = self.sessions.control.external_customer_mapping(tenant_a, "sales_simulator", ext_cust_id)
        self.assertIsNotNone(map_a)
        self.assertEqual(map_a["customer_id"], cust_a)

        # 2. Ingest order for the SAME ext_cust_id in Tenant B
        event_b = self.simulator.create_order_event(
            tenant=tenant_b,
            order_id="O-TENB-001",
            external_customer_id=ext_cust_id,
        )
        res_b = self.adapter.ingest_event(event_b)
        cust_b = res_b.customer_id
        self.assertTrue(cust_b.startswith("cust_"))

        # CRITICAL ASSERTION: Tenant A customer and Tenant B customer MUST be distinct!
        self.assertNotEqual(cust_a, cust_b)

        # Verify mapping in identity store for Tenant B
        map_b = self.sessions.control.external_customer_mapping(tenant_b, "sales_simulator", ext_cust_id)
        self.assertIsNotNone(map_b)
        self.assertEqual(map_b["customer_id"], cust_b)

        # 3. Subsequent event in Tenant A reuses cust_a
        event_a2 = self.simulator.create_order_event(
            tenant=tenant_a,
            order_id="O-TENA-002",
            external_customer_id=ext_cust_id,
        )
        res_a2 = self.adapter.ingest_event(event_a2)
        self.assertEqual(res_a2.customer_id, cust_a)

        # 4. Verify identity_events recorded audit for both mappings
        with self.sessions.control.connection() as db:
            events = db.execute("SELECT * FROM identity_events WHERE kind='external_customer_mapped'").fetchall()
            self.assertGreaterEqual(len(events), 2)

    def test_explicit_customer_link(self):
        """Can explicitly pre-link external_customer_id to an existing customer_id."""
        bstore = self.sessions.business_store(self.tenant_id)
        target_cid = "cust_pre_existing_google_user"

        with bstore.connection(write=True) as db:
            db.execute("INSERT INTO customers (id, name) VALUES (?, ?)", (target_cid, "Google User Pre-Linked"))

        # Link external ID to this customer
        self.adapter.link_external_customer(
            self.tenant_id, "pos_online", "external_pos_buyer_888", target_cid
        )

        # Ingest event with this external customer
        event = self.simulator.create_order_event(
            source_system="pos_online",
            external_customer_id="external_pos_buyer_888",
            order_id="O-LINK-001",
        )
        res = self.adapter.ingest_event(event)
        self.assertEqual(res.customer_id, target_cid)

        # Verify order belongs to target_cid in bstore
        order = bstore.lookup(target_cid, "O-LINK-001")
        self.assertEqual(order["id"], "O-LINK-001")
        self.assertEqual(order["customer_id"], target_cid)

    # -------------------------------------------------------------------------
    # 7. Idempotency & Replay Detection (P5-K5)
    # -------------------------------------------------------------------------

    def test_idempotent_event_ingestion_and_replay_detection(self):
        """P5-K5: Replaying the same event does not duplicate orders, items, or audit records."""
        event = self.simulator.create_order_event(
            order_id="O-REPLAY-001",
            external_customer_id="pos_repeat_buyer",
        )

        # First ingestion
        res1 = self.adapter.ingest_event(event)
        self.assertTrue(res1.success)
        self.assertFalse(res1.is_replay)
        self.assertEqual(res1.status, "imported")

        bstore = self.sessions.business_store(self.tenant_id)
        with bstore.connection() as db:
            orders_cnt1 = db.execute("SELECT count(*) as c FROM orders WHERE id='O-REPLAY-001'").fetchone()["c"]
            items_cnt1 = db.execute("SELECT count(*) as c FROM order_items WHERE order_id='O-REPLAY-001'").fetchone()["c"]
            audit_cnt1 = db.execute("SELECT count(*) as c FROM business_events WHERE kind='order_imported' AND order_id='O-REPLAY-001'").fetchone()["c"]
            imported_cnt1 = db.execute("SELECT count(*) as c FROM imported_events WHERE event_id=?", (event["event_id"],)).fetchone()["c"]

        self.assertEqual(orders_cnt1, 1)
        self.assertGreater(items_cnt1, 0)
        self.assertEqual(audit_cnt1, 1)
        self.assertEqual(imported_cnt1, 1)

        # Second ingestion: EXACT SAME EVENT (Replay)
        res2 = self.adapter.ingest_event(event)
        self.assertTrue(res2.success)
        self.assertTrue(res2.is_replay)
        self.assertEqual(res2.status, "already_processed")
        self.assertEqual(res2.order_id, "O-REPLAY-001")
        self.assertEqual(res2.customer_id, res1.customer_id)

        # Verify counts in DB did NOT increase
        with bstore.connection() as db:
            orders_cnt2 = db.execute("SELECT count(*) as c FROM orders WHERE id='O-REPLAY-001'").fetchone()["c"]
            items_cnt2 = db.execute("SELECT count(*) as c FROM order_items WHERE order_id='O-REPLAY-001'").fetchone()["c"]
            audit_cnt2 = db.execute("SELECT count(*) as c FROM business_events WHERE kind='order_imported' AND order_id='O-REPLAY-001'").fetchone()["c"]
            imported_cnt2 = db.execute("SELECT count(*) as c FROM imported_events WHERE event_id=?", (event["event_id"],)).fetchone()["c"]

        self.assertEqual(orders_cnt2, 1)
        self.assertEqual(items_cnt2, items_cnt1)
        self.assertEqual(audit_cnt2, 1)
        self.assertEqual(imported_cnt2, 1)

    # -------------------------------------------------------------------------
    # 8. Atomic Rollback on Error
    # -------------------------------------------------------------------------

    def test_atomic_rollback_on_database_error_leaves_no_traces(self):
        """Simulated error during order processing rolls back transaction completely."""
        event = self.simulator.create_order_event(
            order_id="O-ROLLBACK-001",
            external_customer_id="rollback_buyer_999",
        )

        from retailops.business.store import BusinessStore
        orig_connection = BusinessStore.connection

        class FaultyDBProxy:
            def __init__(self, real_db):
                self._real_db = real_db

            def execute(self, sql, *args, **kwargs):
                if "INSERT INTO order_items" in sql:
                    raise sqlite3.OperationalError("Simulated disk error or constraint crash during order_items insert")
                return self._real_db.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._real_db, name)

        from contextlib import contextmanager

        @contextmanager
        def faulty_connection(self_bs, *args, **kwargs):
            with orig_connection(self_bs, *args, **kwargs) as real_db:
                yield FaultyDBProxy(real_db)

        with patch.object(BusinessStore, "connection", faulty_connection):
            with self.assertRaises(ApiError) as ctx:
                self.adapter.ingest_event(event)
            self.assertEqual(ctx.exception.code, "database_unavailable")

        # VERIFY FULL ROLLBACK: zero traces in database!
        bstore = self.sessions.business_store(self.tenant_id)
        with bstore.connection() as db:
            order_row = db.execute("SELECT * FROM orders WHERE id='O-ROLLBACK-001'").fetchone()
            self.assertIsNone(order_row)

            items_cnt = db.execute("SELECT count(*) as c FROM order_items WHERE order_id='O-ROLLBACK-001'").fetchone()["c"]
            self.assertEqual(items_cnt, 0)

            event_row = db.execute("SELECT * FROM imported_events WHERE order_id='O-ROLLBACK-001'").fetchone()
            self.assertIsNone(event_row)

            audit_cnt = db.execute("SELECT count(*) as c FROM business_events WHERE order_id='O-ROLLBACK-001'").fetchone()["c"]
            self.assertEqual(audit_cnt, 0)

        # Also verify that identity store mapping was NOT leaked
        mapping = self.sessions.control.external_customer_mapping(self.tenant_id, "sales_simulator", "rollback_buyer_999")
        self.assertIsNone(mapping)

        # After resolving error, normal ingestion succeeds without issue
        res_retry = self.adapter.ingest_event(event)
        self.assertTrue(res_retry.success)
        self.assertEqual(res_retry.status, "imported")

        with bstore.connection() as db:
            order_row = db.execute("SELECT * FROM orders WHERE id='O-ROLLBACK-001'").fetchone()
            self.assertIsNotNone(order_row)

    # -------------------------------------------------------------------------
    # 9. Order Visibility & Isolation (P5-K6)
    # -------------------------------------------------------------------------

    def test_customer_order_visibility_and_isolation(self):
        """P5-K6: Customer only sees their imported order; accessing other customer's order is forbidden."""
        event_1 = self.simulator.create_order_event(
            order_id="O-VIS-001",
            external_customer_id="cust_one_external",
        )
        event_2 = self.simulator.create_order_event(
            order_id="O-VIS-002",
            external_customer_id="cust_two_external",
        )

        res_1 = self.adapter.ingest_event(event_1)
        res_2 = self.adapter.ingest_event(event_2)

        cid_1 = res_1.customer_id
        cid_2 = res_2.customer_id
        self.assertNotEqual(cid_1, cid_2)

        bstore = self.sessions.business_store(self.tenant_id)

        # Customer 1 orders list
        orders_1 = bstore.orders(cid_1)
        order_ids_1 = [o["id"] for o in orders_1]
        self.assertIn("O-VIS-001", order_ids_1)
        self.assertNotIn("O-VIS-002", order_ids_1)

        # Customer 2 orders list
        orders_2 = bstore.orders(cid_2)
        order_ids_2 = [o["id"] for o in orders_2]
        self.assertIn("O-VIS-002", order_ids_2)
        self.assertNotIn("O-VIS-001", order_ids_2)

        # Customer 1 accessing Customer 2's order raises 404 order_not_found
        with self.assertRaises(ApiError) as ctx:
            bstore.lookup(cid_1, "O-VIS-002")
        self.assertEqual(ctx.exception.code, "order_not_found")

        # Customer 2 accessing Customer 1's order raises 404 order_not_found
        with self.assertRaises(ApiError) as ctx:
            bstore.lookup(cid_2, "O-VIS-001")
        self.assertEqual(ctx.exception.code, "order_not_found")

    # -------------------------------------------------------------------------
    # 10. Multi-Item Orders & Line Items Storage
    # -------------------------------------------------------------------------

    def test_multi_item_order_persists_to_order_items(self):
        """Multi-item orders store individual line items in order_items with summary in orders."""
        items = [
            {"product_id": "P-601", "product_title": "Áo sơ mi lụa công sở", "variant_name": "Trắng / M", "quantity": 2, "unit_price": 450000},
            {"product_id": "P-602", "product_title": "Quần tây ống đứng tôn dáng", "variant_name": "Đen / L", "quantity": 1, "unit_price": 520000},
        ]
        total = 2 * 450000 + 1 * 520000  # 1420000
        event = self.simulator.create_order_event(
            order_id="O-MULTI-001",
            items=items,
            total=total,
            status="pending",
        )

        res = self.adapter.ingest_event(event)
        self.assertTrue(res.success)
        self.assertEqual(res.items_count, 2)
        self.assertEqual(res.total, 1420000)

        bstore = self.sessions.business_store(self.tenant_id)
        order = bstore.lookup(res.customer_id, "O-MULTI-001")
        self.assertEqual(order["amount"], 1420000)
        self.assertEqual(order["status"], "pending")
        self.assertIn("Áo sơ mi lụa công sở", order["name"])
        self.assertIn("1 sản phẩm khác", order["name"])

        # Check line items in order_items table
        line_items = bstore.order_items("O-MULTI-001")
        self.assertEqual(len(line_items), 2)
        p_ids = {it["product_id"] for it in line_items}
        self.assertEqual(p_ids, {"P-601", "P-602"})
        self.assertEqual(sum(it["subtotal"] for it in line_items), 1420000)

    # -------------------------------------------------------------------------
    # 11. ToolCache Invalidation After Commit
    # -------------------------------------------------------------------------

    def test_tool_cache_invalidation_after_import(self):
        """Ingesting an order invalidates ToolCache for the mapped customer."""
        customer_id = "cust_cache_test_01"
        self.adapter.link_external_customer(
            self.tenant_id, "sales_simulator", "ext_cache_user", customer_id
        )

        # Pre-seed tool cache
        tool_cache = self.sessions.tool_caches.setdefault(
            self.tenant_id, MagicMock()
        )
        tool_cache.invalidate = MagicMock()

        event = self.simulator.create_order_event(
            order_id="O-CACHE-001",
            external_customer_id="ext_cache_user",
        )
        self.adapter.ingest_event(event)

        # Verify invalidate was called with customer_id and order_id
        tool_cache.invalidate.assert_called_once_with(
            customer=customer_id, tenant_id=self.tenant_id, order_id="O-CACHE-001"
        )

    # -------------------------------------------------------------------------
    # 12. Pre-Signed Fixtures Contract
    # -------------------------------------------------------------------------

    def test_pre_signed_fixtures_validation(self):
        """Signed fixtures are verified against canonical contract."""
        fixtures = get_signed_fixtures()
        self.assertIn("single_item", fixtures)
        self.assertIn("multi_item", fixtures)

        for name, fixture in fixtures.items():
            # Validate schema
            validated = validate_event_schema(fixture)
            self.assertIsNotNone(validated)
            # Validate signature
            self.assertTrue(verify_event_signature(fixture, DEFAULT_DEV_SECRET))


if __name__ == "__main__":
    unittest.main()
