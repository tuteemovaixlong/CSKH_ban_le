"""P5-C review fixes N1, N2, N4 migrated onto retailops-integration-v2 (offline, SQLite).

N1 - an event can never change the owner of an existing (source_system, external_order_id) order.
N4 - identity mapping stays consistent when the identity write fails after business commit.
N2 (offline part) - the PostgreSQL DDL for the P5-C tables is wired into fresh/migrated schemas.
"""
from __future__ import annotations

import copy
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from retailops.core import ApiError
from retailops.identity.persistent import PersistentSessions
from retailops.integration.ingest import IntegrationIngestService
from retailops.storage import pg_schema

TENANT = "shop-alpha-01"
TEST_DIGEST_KEY = b"test-digest-key-32-bytes-minimum!!"


def make_order_created(
    *,
    external_order_id: str,
    external_customer_id: str,
    source_system: str = "marketplace_sim",
    event_id: str | None = None,
    sequence: int = 1,
) -> dict:
    return {
        "contract": "retailops-integration-v2",
        "event_id": event_id or f"evt_{uuid.uuid4().hex[:20]}",
        "event_type": "order.created",
        "source_system": source_system,
        "merchant_id": "shop-alpha",
        "occurred_at": "2026-11-01T10:00:00+07:00",
        "sequence": sequence,
        "data": {
            "external_order_id": external_order_id,
            "external_customer_id": external_customer_id,
            "ordered_at": "2026-11-01T10:00:00+07:00",
            "items": [
                {
                    "sku": "SKU-P601-WHT-M",
                    "external_product_id": "P-601",
                    "title": "Áo sơ mi lụa công sở",
                    "variant_name": "Trắng / M",
                    "quantity": 1,
                    "unit_price": 450000,
                }
            ],
            "shipping_fee": 0,
            "total": 450000,
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


def make_order_status_changed(
    *,
    external_order_id: str,
    status: str,
    source_system: str = "marketplace_sim",
    event_id: str | None = None,
    sequence: int = 2,
    reason: str | None = None,
) -> dict:
    return {
        "contract": "retailops-integration-v2",
        "event_id": event_id or f"evt_{uuid.uuid4().hex[:20]}",
        "event_type": "order.status_changed",
        "source_system": source_system,
        "merchant_id": "shop-alpha",
        "occurred_at": "2026-11-02T10:00:00+07:00",
        "sequence": sequence,
        "data": {
            "external_order_id": external_order_id,
            "status": status,
            "reason": reason,
        },
    }


class SalesReviewBase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.sessions = PersistentSessions(Path(self.temp_dir.name), data_mode="persistent-demo")
        self.sessions.provision_tenant(TENANT, "Shop Alpha", seed_demo=True)
        self.service = IntegrationIngestService(self.sessions, digest_key=TEST_DIGEST_KEY)
        self.bstore = self.sessions.business_store(TENANT)
        self.control = self.sessions.control

    def rows(self, sql, params=()):
        with self.bstore.connection() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def trace_counts(self, order_id):
        return {
            "orders": len(self.rows("SELECT id FROM orders WHERE id=?", (order_id,))),
            "items": len(self.rows("SELECT id FROM order_items WHERE order_id=?", (order_id,))),
            "imported": len(self.rows("SELECT id FROM imported_events WHERE order_id=?", (order_id,))),
            "audit": len(self.rows("SELECT id FROM business_events WHERE order_id=?", (order_id,))),
        }

    def mapping_audits(self):
        with self.control.connection() as db:
            return db.execute(
                "SELECT * FROM identity_events WHERE kind='external_customer_mapped'"
            ).fetchall()


class N1OrderOwnershipTests(SalesReviewBase):
    def test_other_customer_cannot_take_over_existing_order(self):
        first = self.service.ingest_event(
            make_order_created(external_order_id="SIM-O-OWN-001", external_customer_id="owner_a"),
            tenant_id=TENANT,
        )
        before = self.trace_counts(first.order_id)
        order_before = self.rows("SELECT * FROM orders WHERE id=?", (first.order_id,))[0]

        hijack = make_order_created(
            external_order_id="SIM-O-OWN-001", external_customer_id="intruder_b", sequence=2
        )
        with self.assertRaises(ApiError) as ctx:
            self.service.ingest_event(hijack, tenant_id=TENANT)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (409, "order_owner_conflict"))

        self.assertEqual(
            self.rows("SELECT * FROM orders WHERE id=?", (first.order_id,))[0], order_before
        )
        self.assertEqual(
            self.rows("SELECT customer_id FROM orders WHERE id=?", (first.order_id,))[0]["customer_id"],
            first.customer_id,
        )
        self.assertEqual(self.trace_counts(first.order_id), before)
        self.assertEqual(
            self.rows("SELECT id FROM imported_events WHERE event_id=?", (hijack["event_id"],)), []
        )
        self.assertEqual(self.rows("SELECT id FROM customers WHERE name=?", ("Khách intruder_b",)), [])
        self.assertIsNone(self.control.external_customer_mapping(TENANT, "marketplace_sim", "intruder_b"))
        self.assertEqual(self.bstore.lookup(first.customer_id, first.order_id)["status"], "pending")

    def test_same_customer_can_still_update_its_own_order(self):
        first = self.service.ingest_event(
            make_order_created(external_order_id="SIM-O-OWN-002", external_customer_id="owner_a"),
            tenant_id=TENANT,
        )
        update = self.service.ingest_event(
            make_order_status_changed(external_order_id="SIM-O-OWN-002", status="delivered", sequence=2),
            tenant_id=TENANT,
        )
        self.assertEqual(update.customer_id, first.customer_id)
        order = self.bstore.lookup(first.customer_id, first.order_id)
        self.assertEqual((order["status"], order["version"]), ("delivered", 2))

    def test_owner_change_through_explicit_link_is_also_blocked(self):
        first = self.service.ingest_event(
            make_order_created(external_order_id="SIM-O-OWN-004", external_customer_id="owner_a"),
            tenant_id=TENANT,
        )
        event = make_order_created(
            external_order_id="SIM-O-OWN-004", external_customer_id="owner_c", sequence=2
        )
        with self.assertRaises(ApiError) as ctx:
            self.service.ingest_event(event, tenant_id=TENANT)
        self.assertEqual(ctx.exception.code, "order_owner_conflict")
        self.assertEqual(self.bstore.orders(first.customer_id)[0]["id"], first.order_id)


class N4MappingRecoveryTests(SalesReviewBase):
    def fail_identity_write(self, error=None):
        return patch.object(
            self.control, "link_external_customer", side_effect=error or RuntimeError("identity down")
        )

    def test_identity_failure_after_business_commit_is_retryable_and_heals_on_replay(self):
        event = make_order_created(external_order_id="SIM-O-REC-001", external_customer_id="rec_buyer")
        with self.fail_identity_write():
            with self.assertRaises(ApiError) as ctx:
                self.service.ingest_event(event, tenant_id=TENANT)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (503, "identity_mapping_pending"))

        imp_row = self.rows("SELECT order_id, customer_id FROM imported_events WHERE event_id=?", (event["event_id"],))[0]
        oid = imp_row["order_id"]
        committed_customer = imp_row["customer_id"]
        self.assertEqual(self.trace_counts(oid), {"orders": 1, "items": 1, "imported": 1, "audit": 1})
        self.assertEqual(
            self.rows("SELECT customer_id FROM orders WHERE id=?", (oid,))[0]["customer_id"],
            committed_customer,
        )
        self.assertIsNone(self.control.external_customer_mapping(TENANT, "marketplace_sim", "rec_buyer"))

        retry = self.service.ingest_event(event, tenant_id=TENANT)
        self.assertEqual(
            (retry.status, retry.is_replay, retry.customer_id),
            ("already_processed", True, committed_customer),
        )
        mapping = self.control.external_customer_mapping(TENANT, "marketplace_sim", "rec_buyer")
        self.assertEqual(mapping["customer_id"], committed_customer)
        self.assertEqual(self.trace_counts(oid), {"orders": 1, "items": 1, "imported": 1, "audit": 1})
        self.assertEqual(len(self.mapping_audits()), 1)

        self.assertTrue(self.service.ingest_event(event, tenant_id=TENANT).is_replay)
        self.assertEqual(len(self.mapping_audits()), 1)

    def test_next_event_of_same_external_customer_reuses_committed_customer(self):
        first = make_order_created(external_order_id="SIM-O-REC-002", external_customer_id="rec_buyer2")
        with self.fail_identity_write(ApiError(503, "database_unavailable", "down")):
            with self.assertRaises(ApiError) as ctx:
                self.service.ingest_event(first, tenant_id=TENANT)
        self.assertEqual(ctx.exception.code, "identity_mapping_pending")
        committed_customer = self.rows(
            "SELECT customer_id FROM imported_events WHERE event_id=?", (first["event_id"],)
        )[0]["customer_id"]

        second = make_order_created(external_order_id="SIM-O-REC-003", external_customer_id="rec_buyer2")
        result = self.service.ingest_event(second, tenant_id=TENANT)
        self.assertEqual((result.status, result.customer_id), ("imported", committed_customer))
        self.assertEqual(
            self.control.external_customer_mapping(TENANT, "marketplace_sim", "rec_buyer2")["customer_id"],
            committed_customer,
        )
        customers = self.rows("SELECT id FROM customers WHERE name=?", ("Khách rec_buyer2",))
        self.assertEqual([row["id"] for row in customers], [committed_customer])
        self.assertEqual(
            {
                row["customer_id"]
                for row in self.rows(
                    "SELECT customer_id FROM orders WHERE external_order_id IN ('SIM-O-REC-002','SIM-O-REC-003')"
                )
            },
            {committed_customer},
        )

    def test_repeated_identity_failures_never_create_second_customer(self):
        customers = set()
        for index in range(3):
            event = make_order_created(
                external_order_id=f"SIM-O-REC-10{index}", external_customer_id="flaky_buyer"
            )
            with self.fail_identity_write():
                with self.assertRaises(ApiError) as ctx:
                    self.service.ingest_event(event, tenant_id=TENANT)
            self.assertEqual(ctx.exception.code, "identity_mapping_pending")
            customers.add(
                self.rows(
                    "SELECT customer_id FROM imported_events WHERE event_id=?", (event["event_id"],)
                )[0]["customer_id"]
            )
        self.assertEqual(len(customers), 1)
        report = self.service.reconcile_mappings(TENANT)
        self.assertEqual((report["checked"], report["healed"], report["conflicts"]), (1, 1, []))
        self.assertEqual(
            self.control.external_customer_mapping(TENANT, "marketplace_sim", "flaky_buyer")["customer_id"],
            customers.pop(),
        )

    def test_reconcile_is_idempotent_and_reports_conflicts_without_overwriting(self):
        event = make_order_created(external_order_id="SIM-O-REC-004", external_customer_id="rec_buyer4")
        with self.fail_identity_write():
            with self.assertRaises(ApiError):
                self.service.ingest_event(event, tenant_id=TENANT)
        first = self.service.reconcile_mappings(TENANT)
        self.assertEqual((first["checked"], first["healed"]), (1, 1))
        again = self.service.reconcile_mappings(TENANT)
        self.assertEqual((again["checked"], again["healed"], again["conflicts"]), (1, 0, []))
        self.assertEqual(len(self.mapping_audits()), 1)

        with self.control.connection(write=True) as db:
            db.execute(
                "UPDATE external_customer_mappings SET customer_id='cust_somebody_else' WHERE external_customer_id='rec_buyer4'"
            )
        report = self.service.reconcile_mappings(TENANT)
        self.assertEqual(report["healed"], 0)
        self.assertEqual([item["code"] for item in report["conflicts"]], ["external_customer_mapping_conflict"])
        self.assertEqual(
            self.control.external_customer_mapping(TENANT, "marketplace_sim", "rec_buyer4")["customer_id"],
            "cust_somebody_else",
        )

    def test_link_external_customer_is_insert_if_absent(self):
        first = self.control.link_external_customer(TENANT, "marketplace_sim", "link_ext", "cust_one")
        self.assertTrue(first["created"])
        again = self.control.link_external_customer(TENANT, "marketplace_sim", "link_ext", "cust_one")
        self.assertFalse(again["created"])
        self.assertEqual(len(self.mapping_audits()), 1)
        with self.assertRaises(ApiError) as ctx:
            self.control.link_external_customer(TENANT, "marketplace_sim", "link_ext", "cust_two")
        self.assertEqual(
            (ctx.exception.status, ctx.exception.code), (409, "external_customer_mapping_conflict")
        )
        self.assertEqual(
            self.control.external_customer_mapping(TENANT, "marketplace_sim", "link_ext")["customer_id"],
            "cust_one",
        )
        self.assertEqual(len(self.mapping_audits()), 1)

    def test_mapping_conflict_is_not_masked_as_pending(self):
        event = make_order_created(external_order_id="SIM-O-REC-005", external_customer_id="rec_buyer5")
        conflict = ApiError(409, "external_customer_mapping_conflict", "conflict")
        with self.fail_identity_write(conflict):
            with self.assertRaises(ApiError) as ctx:
                self.service.ingest_event(event, tenant_id=TENANT)
        self.assertEqual(ctx.exception.code, "external_customer_mapping_conflict")

    def test_cache_is_invalidated_even_when_identity_write_fails(self):
        cache = self.sessions.tool_caches.setdefault(TENANT, MagicMock())
        cache.invalidate = MagicMock()
        event = make_order_created(external_order_id="SIM-O-REC-006", external_customer_id="rec_buyer6")
        with self.fail_identity_write():
            with self.assertRaises(ApiError):
                self.service.ingest_event(event, tenant_id=TENANT)
        cache.invalidate.assert_called_once()

    def test_prior_business_import_is_authoritative_and_conflicting_mapping_rejected(self):
        self.service.ingest_event(
            make_order_created(external_order_id="SIM-O-AUTH-001", external_customer_id="auth_buyer"),
            tenant_id=TENANT,
        )

        with self.assertRaises(ApiError) as ctx:
            self.service.link_external_customer(TENANT, "marketplace_sim", "auth_buyer", "cust_intruder_99")
        self.assertEqual(ctx.exception.code, "external_customer_mapping_conflict")

        with self.control.connection(write=True) as db:
            db.execute(
                "UPDATE external_customer_mappings SET customer_id='cust_intruder_99' WHERE external_customer_id='auth_buyer'"
            )

        next_event = make_order_created(
            external_order_id="SIM-O-AUTH-002", external_customer_id="auth_buyer"
        )
        with self.assertRaises(ApiError) as ctx:
            self.service.ingest_event(next_event, tenant_id=TENANT)
        self.assertEqual(ctx.exception.code, "external_customer_mapping_conflict")
        self.assertEqual(
            self.rows("SELECT id FROM orders WHERE external_order_id='SIM-O-AUTH-002'"), []
        )

    def test_event_id_collision_rejected_with_different_payload_or_customer(self):
        event = make_order_created(external_order_id="SIM-O-COLL-001", external_customer_id="coll_buyer1")
        res1 = self.service.ingest_event(event, tenant_id=TENANT)
        self.assertEqual(res1.status, "imported")

        hijack_cust = copy.deepcopy(event)
        hijack_cust["data"]["external_customer_id"] = "coll_intruder"
        with self.assertRaises(ApiError) as ctx:
            self.service.ingest_event(hijack_cust, tenant_id=TENANT)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (409, "event_id_collision"))
        self.assertIsNone(self.control.external_customer_mapping(TENANT, "marketplace_sim", "coll_intruder"))

        diff_order = copy.deepcopy(event)
        diff_order["data"]["external_order_id"] = "SIM-O-COLL-002"
        with self.assertRaises(ApiError) as ctx:
            self.service.ingest_event(diff_order, tenant_id=TENANT)
        self.assertEqual(ctx.exception.code, "event_id_collision")

        diff_items = copy.deepcopy(event)
        diff_items["data"]["items"][0]["quantity"] = 2
        diff_items["data"]["total"] = diff_items["data"]["items"][0]["unit_price"] * 2
        with self.assertRaises(ApiError) as ctx:
            self.service.ingest_event(diff_items, tenant_id=TENANT)
        self.assertEqual(ctx.exception.code, "event_id_collision")


class N2PostgresDdlContractTests(unittest.TestCase):
    """Offline guard: the P5-C tables exist in the PostgreSQL DDL and are applied on migration."""

    TABLES = ("order_items", "imported_events")

    def test_business_ddl_has_p5c_tables_and_is_idempotent(self):
        joined = "\n".join(pg_schema.P5C_BUSINESS_DDL)
        for table in self.TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", joined)
        self.assertTrue(all(statement in pg_schema.BUSINESS_DDL for statement in pg_schema.P5C_BUSINESS_DDL))
        for statement in pg_schema.P5C_BUSINESS_DDL:
            self.assertIn("IF NOT EXISTS", statement)
            self.assertNotIn("?", statement)
            self.assertNotIn("%", statement)

    def test_identity_ddl_has_mapping_table_with_tenant_scoped_uniqueness(self):
        joined = "\n".join(pg_schema.P5C_IDENTITY_DDL)
        self.assertIn("CREATE TABLE IF NOT EXISTS external_customer_mappings", joined)
        self.assertIn("UNIQUE(tenant_id, source_system, external_customer_id)", joined.replace("  ", " "))
        self.assertTrue(all(statement in pg_schema.IDENTITY_DDL for statement in pg_schema.P5C_IDENTITY_DDL))

    def test_imported_events_enforces_idempotency_key(self):
        joined = "\n".join(pg_schema.P5C_BUSINESS_DDL)
        self.assertIn("UNIQUE(source_system, event_id)", joined.replace("  ", " "))

    def test_existing_schema_migration_paths_apply_p5c_ddl(self):
        source = Path(pg_schema.__file__).read_text(encoding="utf-8")
        self.assertIn("for statement in P5C_IDENTITY_DDL", source)
        self.assertIn("for statement in P5C_BUSINESS_DDL", source)


if __name__ == "__main__":
    unittest.main()
