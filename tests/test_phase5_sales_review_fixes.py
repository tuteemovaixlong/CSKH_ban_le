"""P5-C review fixes N1-N4 (offline, SQLite): order ownership, strict schema, cross-store recovery.

N1 - an event can never change the owner of an existing order_id.
N3 - exactly the 11 canonical fields, strict numeric types, bounded values.
N4 - identity mapping stays consistent when the identity write fails after business commit.
N2 (offline part) - the PostgreSQL DDL for the P5-C tables is wired into fresh/migrated schemas.
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from retailops.core import ApiError
from retailops.identity.persistent import PersistentSessions
from retailops.sales.adapter import SalesImportAdapter
from retailops.sales.events import compute_signature, validate_event_schema
from retailops.sales.simulator import DEFAULT_DEV_SECRET, SalesSimulator
from retailops.storage import pg_schema

TENANT = "shop-alpha-01"


def resign(event, secret=DEFAULT_DEV_SECRET):
    """Re-sign a mutated event so only the schema (not the HMAC) can reject it."""
    signed = {key: value for key, value in event.items() if key != "signature"}
    signed["signature"] = compute_signature(signed, secret)
    return signed


class SalesReviewBase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.sessions = PersistentSessions(Path(self.temp_dir.name), data_mode="persistent-demo")
        self.sessions.provision_tenant(TENANT, "Shop Alpha", seed_demo=True)
        self.simulator = SalesSimulator(tenant_id=TENANT, secret_key=DEFAULT_DEV_SECRET)
        self.adapter = SalesImportAdapter(self.sessions, default_secret=DEFAULT_DEV_SECRET)
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
            return db.execute("SELECT * FROM identity_events WHERE kind='external_customer_mapped'").fetchall()


class N1OrderOwnershipTests(SalesReviewBase):
    def test_other_customer_cannot_take_over_existing_order(self):
        first = self.adapter.ingest_event(
            self.simulator.create_order_event(order_id="O-OWN-001", external_customer_id="owner_a")
        )
        before = self.trace_counts("O-OWN-001")
        order_before = self.rows("SELECT * FROM orders WHERE id='O-OWN-001'")[0]

        hijack = self.simulator.create_order_event(
            order_id="O-OWN-001", external_customer_id="intruder_b", status="cancelled"
        )
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(hijack)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (409, "order_owner_conflict"))

        self.assertEqual(self.rows("SELECT * FROM orders WHERE id='O-OWN-001'")[0], order_before)
        self.assertEqual(self.rows("SELECT customer_id FROM orders WHERE id='O-OWN-001'")[0]["customer_id"], first.customer_id)
        self.assertEqual(self.trace_counts("O-OWN-001"), before)
        self.assertEqual(self.rows("SELECT id FROM imported_events WHERE event_id=?", (hijack["event_id"],)), [])
        # The rejected event leaves nothing behind: no customer row, no identity mapping.
        self.assertEqual(self.rows("SELECT id FROM customers WHERE name=?", ("Khách intruder_b",)), [])
        self.assertIsNone(self.control.external_customer_mapping(TENANT, "sales_simulator", "intruder_b"))
        # The victim still sees its order and the intruder has none.
        self.assertEqual(self.bstore.lookup(first.customer_id, "O-OWN-001")["status"], "delivered")

    def test_same_customer_can_still_update_its_own_order(self):
        first = self.adapter.ingest_event(
            self.simulator.create_order_event(order_id="O-OWN-002", external_customer_id="owner_a", status="pending")
        )
        update = self.adapter.ingest_event(
            self.simulator.create_order_event(order_id="O-OWN-002", external_customer_id="owner_a", status="delivered")
        )
        self.assertEqual(update.customer_id, first.customer_id)
        order = self.bstore.lookup(first.customer_id, "O-OWN-002")
        self.assertEqual((order["status"], order["version"]), ("delivered", 2))

    def test_same_external_id_from_other_source_is_a_different_customer_and_cannot_take_over(self):
        first = self.adapter.ingest_event(
            self.simulator.create_order_event(order_id="O-OWN-003", external_customer_id="shared_ext_id")
        )
        other_source = self.simulator.create_order_event(
            order_id="O-OWN-003", external_customer_id="shared_ext_id", source_system="pos_online"
        )
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(other_source)
        self.assertEqual(ctx.exception.code, "order_owner_conflict")
        self.assertEqual(self.rows("SELECT customer_id FROM orders WHERE id='O-OWN-003'")[0]["customer_id"], first.customer_id)

    def test_import_cannot_take_over_seeded_demo_order(self):
        seeded = self.rows("SELECT id, customer_id FROM orders ORDER BY id LIMIT 1")[0]
        event = self.simulator.create_order_event(order_id=seeded["id"], external_customer_id="intruder_demo")
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(event)
        self.assertEqual(ctx.exception.code, "order_owner_conflict")
        self.assertEqual(self.rows("SELECT customer_id FROM orders WHERE id=?", (seeded["id"],))[0]["customer_id"], seeded["customer_id"])

    def test_owner_change_through_explicit_link_is_also_blocked(self):
        """Pre-linking an external id to the victim does not let another id steal the order either."""
        first = self.adapter.ingest_event(
            self.simulator.create_order_event(order_id="O-OWN-004", external_customer_id="owner_a")
        )
        event = self.simulator.create_order_event(order_id="O-OWN-004", external_customer_id="owner_c")
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(event)
        self.assertEqual(ctx.exception.code, "order_owner_conflict")
        self.assertEqual(self.bstore.orders(first.customer_id)[0]["id"], "O-OWN-004")


class N3StrictSchemaTests(SalesReviewBase):
    def event(self, **kwargs):
        return self.simulator.create_order_event(order_id="O-SCHEMA-001", external_customer_id="schema_buyer", **kwargs)

    def assert_rejected(self, event, code):
        with self.assertRaises(ApiError) as ctx:
            validate_event_schema(event)
        self.assertEqual(ctx.exception.code, code)
        # Also rejected at the service boundary, with nothing written.
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(resign(event))
        self.assertEqual(ctx.exception.code, code)
        self.assertEqual(self.trace_counts("O-SCHEMA-001"), {"orders": 0, "items": 0, "imported": 0, "audit": 0})

    def test_exact_schema_accepts_valid_event_with_optional_item_fields(self):
        event = self.event(items=[{
            "product_id": "P-601", "product_title": "Áo", "variant_id": "V-1", "variant_name": "Trắng / M",
            "quantity": 2, "unit_price": 450000,
        }])
        self.assertEqual(len(event), 11)
        self.assertIs(validate_event_schema(event), event)
        self.assertTrue(self.adapter.ingest_event(event).success)

    def test_rejects_extra_top_level_field_even_when_signed(self):
        event = self.event()
        event["note"] = "unsigned extra"
        self.assert_rejected(resign(event), "unexpected_event_field")
        event = self.event()
        event["email"] = "buyer@example.com"
        self.assert_rejected(resign(event), "unexpected_event_field")

    def test_rejects_extra_item_field(self):
        event = self.event()
        event["items"][0]["discount"] = 1
        self.assert_rejected(resign(event), "unexpected_item_field")

    def test_rejects_bool_numbers(self):
        for field, value, code in (("quantity", True, "invalid_item_quantity"),
                                   ("unit_price", True, "invalid_item_unit_price")):
            event = self.event()
            event["items"][0][field] = value
            event["total"] = 1
            self.assert_rejected(resign(event), code)
        event = self.event(items=[{"product_id": "P-1", "product_title": "T", "quantity": 1, "unit_price": 1}], total=1)
        event["total"] = True  # True == 1 would otherwise equal the computed total
        self.assert_rejected(resign(event), "invalid_total")

    def test_rejects_float_numbers_even_when_integral(self):
        event = self.event()
        event["items"][0]["quantity"] = 1.0
        self.assert_rejected(resign(event), "invalid_item_quantity")
        event = self.event()
        event["items"][0]["unit_price"] = 450000.0
        self.assert_rejected(resign(event), "invalid_item_unit_price")
        event = self.event()
        event["total"] = 450000.0
        self.assert_rejected(resign(event), "invalid_total")
        event = self.event()
        event["items"][0]["unit_price"] = 450000.5
        event["total"] = 450000
        self.assert_rejected(resign(event), "invalid_item_unit_price")

    def test_rejects_numeric_strings_and_none(self):
        for field, value, code in (("quantity", "1", "invalid_item_quantity"),
                                   ("unit_price", "450000", "invalid_item_unit_price"),
                                   ("unit_price", None, "invalid_item_unit_price")):
            event = self.event()
            event["items"][0][field] = value
            self.assert_rejected(resign(event), code)
        event = self.event()
        event["total"] = "450000"
        self.assert_rejected(resign(event), "invalid_total")

    def test_rejects_out_of_range_values(self):
        event = self.event()
        event["items"][0]["quantity"] = -1
        self.assert_rejected(resign(event), "invalid_item_quantity")
        event = self.event()
        event["items"][0]["quantity"] = 100_001
        self.assert_rejected(resign(event), "invalid_item_quantity")
        event = self.event()
        event["items"][0]["unit_price"] = -5
        self.assert_rejected(resign(event), "invalid_item_unit_price")
        event = self.event()
        event["items"][0]["unit_price"] = 10 ** 12 + 1
        event["total"] = 10 ** 12 + 1
        self.assert_rejected(resign(event), "invalid_item_unit_price")
        event = self.event()
        event["total"] = -450000
        self.assert_rejected(resign(event), "invalid_total")

    def test_rejects_malformed_text_fields(self):
        cases = (
            ("currency", "vnd", "invalid_currency"),
            ("currency", "VNDX", "invalid_currency"),
            ("currency", 704, "invalid_currency"),
            ("timestamp", 1791720000, "invalid_timestamp"),
            ("order_id", "O 1;DROP", "invalid_order_id"),
            ("order_id", "", "invalid_order_id"),
            ("event_id", "x" * 129, "invalid_event_id"),
            ("source_system", "pos online", "invalid_source_system"),
            ("tenant", "shop/alpha", "invalid_tenant"),
            ("external_customer_id", "bad id", "invalid_external_customer_id"),
            ("status", ["delivered"], "invalid_status"),
        )
        for field, value, code in cases:
            with self.subTest(field=field, value=value):
                event = self.event()
                event[field] = value
                with self.assertRaises(ApiError) as ctx:
                    validate_event_schema(resign(event))
                self.assertEqual(ctx.exception.code, code)

    def test_rejects_bad_item_shapes(self):
        event = self.event()
        event["items"] = [["P-601"]]
        self.assert_rejected(resign(event), "invalid_item")
        event = self.event()
        event["items"][0]["variant_name"] = 5
        self.assert_rejected(resign(event), "invalid_item_variant_name")
        event = self.event()
        event["items"][0]["product_title"] = ""
        self.assert_rejected(resign(event), "invalid_item_title")
        event = self.event()
        event["items"] = event["items"] * 201
        event["total"] = 450000 * 201
        self.assert_rejected(resign(event), "invalid_items")

    def test_numeric_strictness_does_not_allow_signature_bypass(self):
        event = self.event()
        tampered = copy.deepcopy(event)
        tampered["items"][0]["quantity"] = 1.0  # signature of the original no longer matches
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(tampered)
        self.assertEqual(ctx.exception.code, "invalid_item_quantity")


class N4MappingRecoveryTests(SalesReviewBase):
    def fail_identity_write(self, error=None):
        return patch.object(self.control, "link_external_customer", side_effect=error or RuntimeError("identity down"))

    def test_identity_failure_after_business_commit_is_retryable_and_heals_on_replay(self):
        event = self.simulator.create_order_event(order_id="O-REC-001", external_customer_id="rec_buyer")
        with self.fail_identity_write():
            with self.assertRaises(ApiError) as ctx:
                self.adapter.ingest_event(event)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (503, "identity_mapping_pending"))

        # Business side committed exactly once; mapping is absent (no half-written state).
        self.assertEqual(self.trace_counts("O-REC-001"), {"orders": 1, "items": 1, "imported": 1, "audit": 1})
        committed_customer = self.rows("SELECT customer_id FROM imported_events WHERE event_id=?", (event["event_id"],))[0]["customer_id"]
        self.assertEqual(self.rows("SELECT customer_id FROM orders WHERE id='O-REC-001'")[0]["customer_id"], committed_customer)
        self.assertIsNone(self.control.external_customer_mapping(TENANT, "sales_simulator", "rec_buyer"))

        # Retry with the same event_id: idempotent, mapping created with the committed customer.
        retry = self.adapter.ingest_event(event)
        self.assertEqual((retry.status, retry.is_replay, retry.customer_id), ("already_processed", True, committed_customer))
        mapping = self.control.external_customer_mapping(TENANT, "sales_simulator", "rec_buyer")
        self.assertEqual(mapping["customer_id"], committed_customer)
        self.assertEqual(self.trace_counts("O-REC-001"), {"orders": 1, "items": 1, "imported": 1, "audit": 1})
        self.assertEqual(len(self.mapping_audits()), 1)

        # Further replays are no-ops (no extra audit, no state change).
        self.assertTrue(self.adapter.ingest_event(event).is_replay)
        self.assertEqual(len(self.mapping_audits()), 1)

    def test_next_event_of_same_external_customer_reuses_committed_customer(self):
        first = self.simulator.create_order_event(order_id="O-REC-002", external_customer_id="rec_buyer2")
        with self.fail_identity_write(ApiError(503, "database_unavailable", "down")):
            with self.assertRaises(ApiError) as ctx:
                self.adapter.ingest_event(first)
        self.assertEqual(ctx.exception.code, "identity_mapping_pending")
        committed_customer = self.rows("SELECT customer_id FROM imported_events WHERE event_id=?", (first["event_id"],))[0]["customer_id"]

        second = self.simulator.create_order_event(order_id="O-REC-003", external_customer_id="rec_buyer2")
        result = self.adapter.ingest_event(second)  # identity healthy again, mapping still missing
        self.assertEqual((result.status, result.customer_id), ("imported", committed_customer))
        self.assertEqual(self.control.external_customer_mapping(TENANT, "sales_simulator", "rec_buyer2")["customer_id"], committed_customer)
        customers = self.rows("SELECT id FROM customers WHERE name=?", ("Khách rec_buyer2",))
        self.assertEqual([row["id"] for row in customers], [committed_customer])
        self.assertEqual({row["customer_id"] for row in self.rows("SELECT customer_id FROM orders WHERE id IN ('O-REC-002','O-REC-003')")}, {committed_customer})

    def test_repeated_identity_failures_never_create_second_customer(self):
        customers = set()
        for index in range(3):
            event = self.simulator.create_order_event(order_id=f"O-REC-10{index}", external_customer_id="flaky_buyer")
            with self.fail_identity_write():
                with self.assertRaises(ApiError) as ctx:
                    self.adapter.ingest_event(event)
            self.assertEqual(ctx.exception.code, "identity_mapping_pending")
            customers.add(self.rows("SELECT customer_id FROM imported_events WHERE event_id=?", (event["event_id"],))[0]["customer_id"])
        self.assertEqual(len(customers), 1)
        report = self.adapter.reconcile_mappings(TENANT)
        self.assertEqual((report["checked"], report["healed"], report["conflicts"]), (1, 1, []))
        self.assertEqual(self.control.external_customer_mapping(TENANT, "sales_simulator", "flaky_buyer")["customer_id"], customers.pop())

    def test_reconcile_is_idempotent_and_reports_conflicts_without_overwriting(self):
        event = self.simulator.create_order_event(order_id="O-REC-004", external_customer_id="rec_buyer4")
        with self.fail_identity_write():
            with self.assertRaises(ApiError):
                self.adapter.ingest_event(event)
        first = self.adapter.reconcile_mappings(TENANT)
        self.assertEqual((first["checked"], first["healed"]), (1, 1))
        again = self.adapter.reconcile_mappings(TENANT)
        self.assertEqual((again["checked"], again["healed"], again["conflicts"]), (1, 0, []))
        self.assertEqual(len(self.mapping_audits()), 1)

        with self.control.connection(write=True) as db:
            db.execute("UPDATE external_customer_mappings SET customer_id='cust_somebody_else' WHERE external_customer_id='rec_buyer4'")
        report = self.adapter.reconcile_mappings(TENANT)
        self.assertEqual(report["healed"], 0)
        self.assertEqual([item["code"] for item in report["conflicts"]], ["external_customer_mapping_conflict"])
        self.assertEqual(self.control.external_customer_mapping(TENANT, "sales_simulator", "rec_buyer4")["customer_id"], "cust_somebody_else")

    def test_link_external_customer_is_insert_if_absent(self):
        first = self.control.link_external_customer(TENANT, "sales_simulator", "link_ext", "cust_one")
        self.assertTrue(first["created"])
        again = self.control.link_external_customer(TENANT, "sales_simulator", "link_ext", "cust_one")
        self.assertFalse(again["created"])
        self.assertEqual(len(self.mapping_audits()), 1)
        with self.assertRaises(ApiError) as ctx:
            self.control.link_external_customer(TENANT, "sales_simulator", "link_ext", "cust_two")
        self.assertEqual((ctx.exception.status, ctx.exception.code), (409, "external_customer_mapping_conflict"))
        self.assertEqual(self.control.external_customer_mapping(TENANT, "sales_simulator", "link_ext")["customer_id"], "cust_one")
        self.assertEqual(len(self.mapping_audits()), 1)

    def test_mapping_conflict_is_not_masked_as_pending(self):
        """A 4xx conflict from the identity store is a real error and must surface unchanged."""
        event = self.simulator.create_order_event(order_id="O-REC-005", external_customer_id="rec_buyer5")
        conflict = ApiError(409, "external_customer_mapping_conflict", "conflict")
        with self.fail_identity_write(conflict):
            with self.assertRaises(ApiError) as ctx:
                self.adapter.ingest_event(event)
        self.assertEqual(ctx.exception.code, "external_customer_mapping_conflict")

    def test_cache_is_invalidated_even_when_identity_write_fails(self):
        from unittest.mock import MagicMock
        cache = self.sessions.tool_caches.setdefault(TENANT, MagicMock())
        cache.invalidate = MagicMock()
        event = self.simulator.create_order_event(order_id="O-REC-006", external_customer_id="rec_buyer6")
        with self.fail_identity_write():
            with self.assertRaises(ApiError):
                self.adapter.ingest_event(event)
        cache.invalidate.assert_called_once()


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
