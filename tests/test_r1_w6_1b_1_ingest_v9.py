"""Phase R1 W6.1b-1 isolated & mock/real PostgreSQL tests (Items 0-10)."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from retailops.business import schema as business_schema
from retailops.business.schema import (
    BUSINESS_V8_VERSION_MAPPING,
    BUSINESS_V9_VERSION_MAPPING,
    POSTGRES_BUSINESS_SCHEMA_CURRENT,
    POSTGRES_BUSINESS_V8_SCHEMA_VERSION,
    REQUIRED_V9_TABLES,
    SQLITE_BUSINESS_SCHEMA_CURRENT,
    SQLITE_BUSINESS_V8_SCHEMA_VERSION,
)
from retailops.business.store import (
    BusinessStore,
    _inspect_sqlite_business_ready,
    migrate_sqlite_business_v8,
    migrate_sqlite_business_v9,
)
from retailops.config import Settings
from retailops.core import ApiError, STATUSES
from retailops.bootstrap import build_public_app
from retailops.identity.persistent import PersistentSessions
from retailops.identity.postgres import PostgresSessions
from retailops.identity.store import IdentityStore
from retailops.storage import cli as database_cli
from retailops.storage import pg_schema
from retailops.storage.pg_repositories import PostgresBusinessStore, migrate_postgres_business_v9
from retailops.storage.pg_schema import initialize as pg_initialize
from retailops.storage.postgres import (
    BUSINESS_SCHEMA_COMPATIBLE,
    BUSINESS_SCHEMA_CURRENT,
    BUSINESS_V8_SCHEMA_VERSION,
    IDENTITY_SCHEMA,
    tenant_schema,
)
try:
    from test_r1_w3_2_business_v7 import file_sha, table_dump
except ImportError:
    from tests.test_r1_w3_2_business_v7 import file_sha, table_dump

DSN = os.environ.get("RETAILOPS_TEST_DATABASE_URL", "")


def _create_sqlite_v8_workspace(root: Path) -> tuple[Path, Path, list[Path]]:
    """Create a real multi-tenant SQLite Business v8 (SQLite version 7) workspace with legacy orders & v1 imported_events."""
    ws = root / "ws_v8"
    pers = ws / "persistent"
    tenants_dir = pers / "tenants"
    tenants_dir.mkdir(parents=True, exist_ok=True)
    id_store = IdentityStore(pers / "identity.sqlite3")
    t_a = id_store.ensure_tenant("shop-a", "Shop A")
    t_b = id_store.ensure_tenant("shop-b", "Shop B")
    paths = [
        tenants_dir / f"{t_a['storage_key']}.sqlite3",
        tenants_dir / f"{t_b['storage_key']}.sqlite3",
    ]
    for idx, p in enumerate(paths):
        with closing(sqlite3.connect(p)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("BEGIN IMMEDIATE")
            business_schema.migrate_v3(db)
            db.execute(
                """CREATE TABLE orders (
                    id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    variant TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','delivered','cancelled')),
                    version INTEGER NOT NULL DEFAULT 1,
                    cancel_reason TEXT,
                    product_id TEXT REFERENCES products(id),
                    delivered_at REAL
                )"""
            )
            db.execute("CREATE INDEX idx_orders_customer_id ON orders(customer_id)")
            db.execute("CREATE INDEX idx_orders_product_id ON orders(product_id)")
            db.execute(
                """CREATE TABLE order_items (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                    product_id TEXT NOT NULL REFERENCES products(id),
                    variant_id TEXT,
                    product_title TEXT NOT NULL,
                    variant_name TEXT,
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    unit_price INTEGER NOT NULL CHECK (unit_price >= 0),
                    subtotal INTEGER NOT NULL CHECK (subtotal >= 0),
                    created_at REAL NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE imported_events (
                    id TEXT PRIMARY KEY,
                    source_system TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    external_customer_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(source_system, event_id)
                )"""
            )
            db.execute(
                """CREATE TABLE order_purge_tombstones (
                    order_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    snapshot_name TEXT NOT NULL,
                    variant TEXT,
                    reason TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    purged_at DOUBLE PRECISION NOT NULL,
                    pre_counts_json TEXT NOT NULL,
                    post_counts_json TEXT NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE proposals (
                    id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, order_id TEXT NOT NULL REFERENCES orders(id),
                    order_version INTEGER NOT NULL, reason TEXT NOT NULL,
                    expires_at REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    confirm_key TEXT, result TEXT,
                    UNIQUE(customer_id, confirm_key)
                )"""
            )
            db.execute(
                """CREATE TABLE business_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT NOT NULL,
                    created_at REAL NOT NULL, kind TEXT NOT NULL, order_id TEXT, payload TEXT NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE conversations (
                    id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
                    order_id TEXT, product_id TEXT,
                    revision INTEGER NOT NULL DEFAULT 0, expires_at REAL NOT NULL,
                    provider_id TEXT NOT NULL DEFAULT 'custom'
                )"""
            )
            db.execute(
                """CREATE TABLE agent_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    customer_id TEXT NOT NULL, request_id TEXT NOT NULL, input_hash TEXT NOT NULL,
                    messages TEXT NOT NULL, result TEXT NOT NULL, created_at REAL NOT NULL,
                    UNIQUE(conversation_id, request_id)
                )"""
            )
            db.execute(
                """CREATE TABLE conversation_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    turn_id INTEGER REFERENCES agent_turns(id) ON DELETE SET NULL,
                    customer_id TEXT NOT NULL,
                    feedback_type TEXT NOT NULL CHECK(feedback_type IN ('turn_rating', 'session_csat', 'human_handoff')),
                    rating INTEGER CHECK(rating BETWEEN 1 AND 5),
                    sentiment_flag TEXT CHECK(sentiment_flag IN ('positive', 'negative', 'neutral')),
                    reason_code TEXT, comment TEXT, created_at REAL NOT NULL
                )"""
            )
            db.execute(
                "CREATE TABLE provider_daily_usage (day TEXT NOT NULL, provider_id TEXT NOT NULL, attempts INTEGER NOT NULL, PRIMARY KEY(day,provider_id))"
            )
            db.execute("CREATE TABLE customers (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
            business_schema._ensure_order_customer_triggers(db)
            from retailops.workflow.schema import initialize as graph_schema

            graph_schema(db)
            business_schema.ensure_case_tables(db)
            business_schema.ensure_order_action_tables(db)
            business_schema.ensure_case_assist_tables(db)
            db.execute("CREATE TABLE retailops_schema (component TEXT PRIMARY KEY, version INTEGER NOT NULL)")
            db.execute("INSERT INTO retailops_schema VALUES ('business', 7)")

            db.execute("INSERT INTO customers VALUES ('C-001', 'Khách v8')")
            db.execute(
                "INSERT INTO products(id, name, created_at, updated_at) VALUES ('P-101', 'Áo thun', 1000.0, 1000.0)"
            )
            db.execute(
                "INSERT INTO orders(id, customer_id, name, variant, amount, status, version, product_id) "
                "VALUES ('O-101', 'C-001', 'Áo thun', 'Trắng / M', 299000, 'pending', 1, 'P-101')"
            )
            if idx == 0:
                db.execute(
                    "INSERT INTO orders(id, customer_id, name, variant, amount, status, version, product_id, delivered_at) "
                    "VALUES ('O-102', 'C-001', 'Áo thun', 'Đen / L', 299000, 'delivered', 2, 'P-101', 1700000500.0)"
                )
            db.commit()
    return ws, pers, paths


class PhaseR1W61b1Item0SQLiteTests(unittest.TestCase):
    """Item 0 (W6.1b-D1): SQLite Business v9 fresh schema, v8 fail-closed, migrate-v9 backfill, constraints, triggers."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r1-w61b1-item0-sq-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_version_constants_and_fresh_sqlite_db_is_v9_with_all_constraints_and_triggers(self):
        self.assertEqual(SQLITE_BUSINESS_V8_SCHEMA_VERSION, 7)
        self.assertEqual(POSTGRES_BUSINESS_V8_SCHEMA_VERSION, 8)
        self.assertEqual(SQLITE_BUSINESS_SCHEMA_CURRENT, 8)
        self.assertEqual(POSTGRES_BUSINESS_SCHEMA_CURRENT, 9)
        self.assertEqual(BUSINESS_SCHEMA_CURRENT, 9)
        self.assertIn(8, BUSINESS_SCHEMA_COMPATIBLE)
        self.assertIn(9, BUSINESS_SCHEMA_COMPATIBLE)
        self.assertEqual(STATUSES["shipping"], "Đang giao")
        self.assertEqual(BUSINESS_V8_VERSION_MAPPING, {"logical_milestone": "business_v8", "sqlite": 7, "postgresql": 8})
        self.assertEqual(BUSINESS_V9_VERSION_MAPPING, {"logical_milestone": "business_v9", "sqlite": 8, "postgresql": 9})

        fresh_path = self.root / "fresh_v9.sqlite3"
        store = BusinessStore(fresh_path)
        self.assertEqual(_inspect_sqlite_business_ready(fresh_path), "v9_ready")

        with store.connection(write=True) as db:
            ver = db.execute("SELECT version FROM retailops_schema WHERE component='business'").fetchone()[0]
            self.assertEqual(ver, 8)
            tables = {
                r[0]
                for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            self.assertTrue(set(REQUIRED_V9_TABLES).issubset(tables))
            # W6.1b-2 tables exist and start completely empty
            for w61b2_tbl in ("order_recipients", "delivery_compensations", "vouchers"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {w61b2_tbl}").fetchone()[0], 0)

            # integration_connectors carries merchant_id per W6.1b-D5
            conn_cols = {r["name"] for r in db.execute("PRAGMA table_info(integration_connectors)")}
            self.assertTrue(
                {"connector_id", "source_system", "kind", "merchant_id", "secret_ref", "status_mapping_json", "enabled"}
                <= conn_cols
            )

            db.execute("INSERT INTO customers VALUES ('C-1', 'Khách 1')")
            db.execute("INSERT INTO products(id, name, created_at, updated_at) VALUES ('P-1', 'Áo 1', 1.0, 1.0)")

            # SKU partial unique index: multiple NULL/empty SKUs allowed, duplicate non-empty SKU rejected
            db.execute(
                "INSERT INTO product_variants(id, product_id, variant_name, sku) VALUES ('V-1', 'P-1', 'M', NULL)"
            )
            db.execute(
                "INSERT INTO product_variants(id, product_id, variant_name, sku) VALUES ('V-2', 'P-1', 'L', '   ')"
            )
            db.execute(
                "INSERT INTO product_variants(id, product_id, variant_name, sku) VALUES ('V-3', 'P-1', 'XL', 'SKU-TEE-XL')"
            )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "INSERT INTO product_variants(id, product_id, variant_name, sku) VALUES ('V-4', 'P-1', 'XXL', 'SKU-TEE-XL')"
                )

            # orders: 'shipping' allowed, invalid status rejected, same external_order_id allowed across distinct source_system,
            # duplicate (source_system, external_order_id) rejected
            db.execute(
                """INSERT INTO orders(
                       id, customer_id, product_id, source_system, external_order_id,
                       name, variant, amount, status, ordered_at, payment_method, payment_status,
                       shipping_fee, ship_to_area, promised_delivery_by
                   ) VALUES (
                       'ord_1', 'C-1', 'P-1', 'marketplace_sim', 'MS-1001',
                       'Áo 1', 'XL', 299000, 'shipping', 1700000000.0, 'cod', 'unpaid',
                       25000, 'Quận 1, TP. Hồ Chí Minh', 1700259200.0
                   )"""
            )
            db.execute(
                """INSERT INTO orders(
                       id, customer_id, product_id, source_system, external_order_id,
                       name, variant, amount, status, ordered_at
                   ) VALUES (
                       'ord_2', 'C-1', 'P-1', 'other_shop_sim', 'MS-1001',
                       'Áo 1', 'XL', 299000, 'pending', 1700000010.0
                   )"""
            )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    """INSERT INTO orders(
                           id, customer_id, product_id, source_system, external_order_id,
                           name, variant, amount, status, ordered_at
                       ) VALUES (
                           'ord_dup_ext', 'C-1', 'P-1', 'marketplace_sim', 'MS-1001',
                           'Áo 1', 'XL', 299000, 'pending', 1700000020.0
                       )"""
                )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    """INSERT INTO orders(
                           id, customer_id, product_id, source_system, external_order_id,
                           name, variant, amount, status, ordered_at
                       ) VALUES (
                           'ord_bad_st', 'C-1', 'P-1', 'marketplace_sim', 'MS-9999',
                           'Áo 1', 'XL', 299000, 'processing', 1700000020.0
                       )"""
                )

            # shipments & append-only shipment_events triggers
            db.execute(
                """INSERT INTO shipments(
                       shipment_id, order_id, source_system, external_shipment_id,
                       carrier, tracking_code, status, carrier_status_raw, delivery_attempts, updated_at
                   ) VALUES (
                       'shp_1', 'ord_1', 'marketplace_sim', 'SHP-1001',
                       'GHN', 'GHN123456', 'in_transit', 'transporting', 0, 1700001000.0
                   )"""
            )
            db.execute(
                """INSERT INTO shipment_events(
                       shipment_event_id, shipment_id, occurred_at, status, carrier_status_raw,
                       description, hub_name, district, province, source_event_id
                   ) VALUES (
                       'se_1', 'shp_1', 1700001000.0, 'in_transit', 'transporting',
                       'Đang trung chuyển', 'Kho SOC', 'Quận 12', 'TP. Hồ Chí Minh', 'evt-shp-0001'
                   )"""
            )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE shipment_events SET description='Sửa trái phép' WHERE shipment_event_id='se_1'")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM shipment_events WHERE shipment_event_id='se_1'")

            # imported_events accepts non-order events such as product.upserted with NULL order/customer/signature
            db.execute(
                """INSERT INTO imported_events(
                       id, source_system, event_id, tenant_id,
                       event_type, sequence, received_via, payload_digest, redacted_fields,
                       payload_json, created_at
                   ) VALUES (
                       'ie_prod_1', 'marketplace_sim', 'evt-prod-0001', 'shop-a',
                       'product.upserted', 1, 'import', 'hmac_sha256_hex', '[]',
                       '{"event_type":"product.upserted"}', 1700000000.0
                   )"""
            )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    """INSERT INTO imported_events(
                           id, source_system, event_id, tenant_id,
                           event_type, sequence, received_via, payload_json, created_at
                       ) VALUES (
                           'ie_prod_dup', 'marketplace_sim', 'evt-prod-0001', 'shop-a',
                           'product.upserted', 1, 'http', '{}', 1700000001.0
                       )"""
                )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    """INSERT INTO imported_events(
                           id, source_system, event_id, tenant_id,
                           event_type, sequence, received_via, payload_json, created_at
                       ) VALUES (
                           'ie_bad_via', 'marketplace_sim', 'evt-prod-0002', 'shop-a',
                           'product.upserted', 1, 'ftp', '{}', 1700000001.0
                       )"""
                )

    def test_v8_fixture_is_blocked_at_startup_migrates_exact_backfill_count_and_rerun_is_idempotent(self):
        ws, pers, (path_a, path_b) = _create_sqlite_v8_workspace(self.root)
        before_hashes = (file_sha(path_a), file_sha(path_b))

        parser = argparse.ArgumentParser()
        database_cli.add_parser(parser.add_subparsers(dest="command", required=True))

        with patch.dict(os.environ, {"RETAILOPS_STORAGE_BACKEND": "sqlite"}, clear=False):
            for blocked in (
                lambda: _inspect_sqlite_business_ready(path_a),
                lambda: BusinessStore(path_a, create=False),
                lambda: PersistentSessions(pers),
                lambda: build_public_app(
                    Settings(
                        interface="public",
                        bind="127.0.0.1",
                        port=8000,
                        origin="https://retailops.example.com",
                        access_token="unused-token-" + "z" * 32,
                        output=ws,
                        data_mode="persistent-demo",
                    )
                ),
                lambda: database_cli.run(parser.parse_args(["database", "--output", str(ws), "check"])),
            ):
                with self.assertRaises(ApiError) as err:
                    blocked()
                self.assertEqual((err.exception.status, err.exception.code), (503, "business_migration_required"))
                self.assertIn("migrate-v9", err.exception.message)

            # Fail-closed startup wrote zero bytes
            self.assertEqual((file_sha(path_a), file_sha(path_b)), before_hashes)

            # Missing confirmation flags rejected
            for unconf in (
                ["database", "--output", str(ws), "migrate-v9"],
                ["database", "--output", str(ws), "migrate-v9", "--confirm-preflight"],
                ["database", "--output", str(ws), "migrate-v9", "--confirm-backup"],
            ):
                with self.assertRaises(ApiError) as cerr:
                    database_cli.run(parser.parse_args(unconf))
                self.assertEqual((cerr.exception.status, cerr.exception.code), (400, "migration_confirmation_required"))
            self.assertEqual((file_sha(path_a), file_sha(path_b)), before_hashes)

            t_before = time.time()
            res = database_cli.run(
                parser.parse_args(
                    ["database", "--output", str(ws), "migrate-v9", "--confirm-preflight", "--confirm-backup"]
                )
            )
            t_after = time.time()
            self.assertEqual(
                res,
                {
                    "result": "BUSINESS_V9_MIGRATED",
                    "backend": "sqlite",
                    "schema_version": 8,
                    "logical_version": 9,
                    "tenants": 2,
                    "upgraded": True,
                    "orders_backfilled": 3,
                },
            )

            chk = database_cli.run(parser.parse_args(["database", "--output", str(ws), "check"]))
            self.assertEqual(chk, {"result": "SQLITE_SCHEMA_READY", "tenants_checked": 2})

        sessions = PersistentSessions(pers)
        store_a = sessions.business_store("shop-a")
        with store_a.connection() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM orders ORDER BY id ASC").fetchall()]
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertEqual(row["source_system"], "retailops_seed")
                self.assertEqual(row["external_order_id"], row["id"])
                self.assertEqual(row["ordered_at_backfilled"], 1)
                self.assertEqual(row["payment_status"], "unpaid")
                self.assertGreaterEqual(row["ordered_at"], t_before - 1.0)
                self.assertLessEqual(row["ordered_at"], t_after + 1.0)
            self.assertEqual(rows[1]["delivered_at"], 1700000500.0)

        # Re-running migrate-v9 is 100% no-op
        dumps_after = (table_dump(path_a), table_dump(path_b))
        again = migrate_sqlite_business_v9(ws, preflight_confirmed=True, backup_confirmed=True)
        self.assertEqual(
            again,
            {
                "result": "BUSINESS_V9_MIGRATED",
                "backend": "sqlite",
                "schema_version": 8,
                "logical_version": 9,
                "tenants": 2,
                "upgraded": False,
                "orders_backfilled": 0,
            },
        )
        self.assertEqual((table_dump(path_a), table_dump(path_b)), dumps_after)


class PhaseR1W61b1Item0PostgresMockTests(unittest.TestCase):
    """Item 0 (W6.1b-D1): Mock PostgreSQL fresh v9, v8 fail-closed, migrate-v9 backfill, and DDL safety."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r1-w61b1-item0-pgmock-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_pg_schema_v9_ddl_contains_no_qmark_or_percent_placeholders(self):
        for stmt in [*pg_schema.BUSINESS_DDL, *pg_schema.BUSINESS_V9_TABLES_DDL, *pg_schema.BUSINESS_V9_UPGRADE_DDL]:
            self.assertNotIn("?", stmt)
            self.assertNotIn("%", stmt)

    def test_postgres_mock_v8_blocked_migrated_to_v9_with_exact_backfill_and_rerun_noop(self):
        try:
            from test_r1_w3_order_actions import _build_mock_pg_harness
        except ImportError:
            from tests.test_r1_w3_order_actions import _build_mock_pg_harness

        dsn = "postgresql://retailops:secret@127.0.0.1:5432/retailops"
        keys = ["a" * 32, "b" * 32]
        state, mock_conn_cls = _build_mock_pg_harness(keys)
        ws_out = self.root / "pg_out"

        mock_psycopg = MagicMock()
        mock_psycopg.conninfo.conninfo_to_dict.return_value = {"dbname": "retailops", "user": "retailops"}
        mock_sql = MagicMock()
        mock_sql.SQL = lambda s: SimpleNamespace(format=lambda *a: s.format(*a))
        mock_sql.Identifier = lambda s: s
        mock_psycopg.sql = mock_sql

        @contextmanager
        def fake_tx(dsn_, schema=IDENTITY_SCHEMA, *, write=False, read_only=False, lock_schema=True):
            yield mock_conn_cls(schema)

        parser = argparse.ArgumentParser()
        database_cli.add_parser(parser.add_subparsers(dest="command", required=True))
        schema_a, schema_b = (tenant_schema(k) for k in keys)

        with patch.dict("sys.modules", {"psycopg": mock_psycopg, "psycopg.sql": mock_sql}), \
             patch("retailops.storage.pg_repositories.transaction", side_effect=fake_tx), \
             patch("retailops.storage.postgres.transaction", side_effect=fake_tx), \
             patch("retailops.identity.postgres.transaction", side_effect=fake_tx), \
             patch("retailops.storage.cli.os.environ", {"RETAILOPS_STORAGE_BACKEND": "postgresql", "RETAILOPS_DATABASE_URL": dsn}), \
             patch.dict(os.environ, {"RETAILOPS_STORAGE_BACKEND": "postgresql", "RETAILOPS_DATABASE_URL": dsn}, clear=False):

            database_cli.run(
                parser.parse_args(["database", "--output", str(ws_out), "migrate-v8", "--confirm-preflight", "--confirm-backup"])
            )
            for sc in (schema_a, schema_b):
                self.assertEqual(
                    state.schemas[sc].execute("SELECT version FROM retailops_schema").fetchone()[0],
                    BUSINESS_V8_SCHEMA_VERSION,
                )

            # v8 PG schemas are blocked fail-closed on startup, store init, and `database check`
            for blocked in (
                lambda: pg_initialize(mock_conn_cls(schema_a), schema_a, "business"),
                lambda: PostgresBusinessStore(dsn, keys[0], create=False),
                lambda: PostgresSessions(dsn),
                lambda: database_cli.run(parser.parse_args(["database", "check"])),
                lambda: database_cli.run(parser.parse_args(["database", "migrate"])),
            ):
                with self.assertRaises(ApiError) as err:
                    blocked()
                self.assertEqual((err.exception.status, err.exception.code), (503, "business_migration_required"))
                self.assertIn("migrate-v9", err.exception.message)

            with self.assertRaises(ApiError) as unconf:
                database_cli.run(parser.parse_args(["database", "migrate-v9", "--confirm-backup"]))
            self.assertEqual(unconf.exception.code, "migration_confirmation_required")

            mig = database_cli.run(
                parser.parse_args(["database", "--output", str(ws_out), "migrate-v9", "--confirm-preflight", "--confirm-backup"])
            )
            self.assertEqual(
                mig,
                {
                    "result": "BUSINESS_V9_MIGRATED",
                    "backend": "postgresql",
                    "schema_version": 9,
                    "logical_version": 9,
                    "tenants": 2,
                    "upgraded": True,
                    "orders_backfilled": 4,
                },
            )
            self.assertEqual(database_cli.run(parser.parse_args(["database", "check"]))["result"], "POSTGRES_SCHEMA_READY")

            for sc in (schema_a, schema_b):
                mem = state.schemas[sc]
                self.assertEqual(mem.execute("SELECT version FROM retailops_schema").fetchone()[0], 9)
                tables = {r[0] for r in mem.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                self.assertTrue(set(REQUIRED_V9_TABLES).issubset(tables))
                ord_rows = [dict(r) for r in mem.execute("SELECT * FROM orders ORDER BY id").fetchall()]
                self.assertTrue(all(r["source_system"] == "retailops_seed" for r in ord_rows))
                self.assertTrue(all(r["external_order_id"] == r["id"] for r in ord_rows))
                self.assertTrue(all(r["ordered_at_backfilled"] == 1 for r in ord_rows))

            again = migrate_postgres_business_v9(dsn, preflight_confirmed=True, backup_confirmed=True, data_root=ws_out)
            self.assertEqual(
                again,
                {
                    "result": "BUSINESS_V9_MIGRATED",
                    "backend": "postgresql",
                    "schema_version": 9,
                    "logical_version": 9,
                    "tenants": 2,
                    "upgraded": False,
                    "orders_backfilled": 0,
                },
            )

            # Fresh PG schema initializes directly to v9
            PostgresBusinessStore(dsn, "d" * 32, create=True)
            self.assertEqual(
                state.schemas[tenant_schema("d" * 32)].execute("SELECT version FROM retailops_schema").fetchone()[0],
                9,
            )


@unittest.skipUnless(DSN, "PostgreSQL integration runs in CI with a dedicated test database.")
class RealPostgresBusinessV9Tests(unittest.TestCase):
    """Real PostgreSQL 16 verification for Business v9 migration, constraints, SKU unique index, and triggers."""

    @classmethod
    def setUpClass(cls):
        import psycopg
        from scripts.postgres_test_guard import require_disposable_postgres_test_target

        require_disposable_postgres_test_target(DSN, psycopg.conninfo.conninfo_to_dict)

    def clear(self):
        from psycopg import sql
        from retailops.storage.postgres import transaction

        with transaction(DSN, write=True) as db:
            names = db.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname=? OR nspname ~ '^tenant_[a-f0-9]{32}$'",
                (IDENTITY_SCHEMA,),
            ).fetchall()
            for row in names:
                db.raw.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(row["nspname"])))

    def setUp(self):
        from retailops.storage.pg_repositories import PostgresIdentityStore

        self.temp = tempfile.TemporaryDirectory(prefix="r1-w61b1-realpg-")
        self.addCleanup(self.temp.cleanup)
        self.clear()
        self.addCleanup(self.clear)
        PostgresIdentityStore(DSN, create=True)
        self.sessions = PostgresSessions(DSN, api_daily_limit=1, data_root=Path(self.temp.name))
        self.sessions.provision_tenant("shop-v9", "Cửa hàng V9", seed_demo=False)
        self.key = self.sessions.control.tenant("shop-v9")["storage_key"]
        self.schema = tenant_schema(self.key)

    def test_real_postgres_v8_to_v9_migration_backfill_triggers_and_constraints(self):
        import psycopg
        from retailops.storage.postgres import transaction

        # Downgrade the tenant schema to genuine Business v8 shape with 2 legacy orders and v1 imported_events
        with transaction(DSN, self.schema, write=True) as db:
            for tbl in reversed(REQUIRED_V9_TABLES):
                db.raw.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")
            db.raw.execute("DROP INDEX IF EXISTS idx_product_variants_sku_unique")
            db.raw.execute("DROP TABLE IF EXISTS imported_events CASCADE")
            db.raw.execute(
                """CREATE TABLE imported_events (
                    id TEXT PRIMARY KEY, source_system TEXT NOT NULL,
                    event_id TEXT NOT NULL, tenant_id TEXT NOT NULL, external_customer_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL, order_id TEXT NOT NULL, status TEXT NOT NULL,
                    total BIGINT NOT NULL, currency TEXT NOT NULL, payload_json TEXT NOT NULL,
                    signature TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL,
                    UNIQUE(source_system, event_id))"""
            )
            db.raw.execute("ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_source_external_v9_unique")
            db.raw.execute("ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_status_v9_check")
            for col in (
                "source_system",
                "external_order_id",
                "ordered_at",
                "ordered_at_backfilled",
                "payment_method",
                "payment_status",
                "shipping_fee",
                "ship_to_area",
                "promised_delivery_by",
            ):
                db.raw.execute(f"ALTER TABLE orders DROP COLUMN IF EXISTS {col}")
            db.raw.execute(
                "ALTER TABLE orders ADD CONSTRAINT orders_legacy_status_check CHECK (status IN ('pending','delivered','cancelled'))"
            )
            db.raw.execute("INSERT INTO customers(id, name) VALUES ('C-PG-1', 'Khách PG') ON CONFLICT DO NOTHING")
            db.raw.execute(
                "INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version) "
                "VALUES ('O-PG-1', 'C-PG-1', 'P-101', 'Áo sơ mi', 'M', 350000, 'pending', 1)"
            )
            db.raw.execute(
                "INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version, delivered_at) "
                "VALUES ('O-PG-2', 'C-PG-1', 'P-101', 'Áo sơ mi', 'L', 350000, 'delivered', 2, 1700000500.0)"
            )
            db.raw.execute("UPDATE retailops_schema SET version = 8 WHERE component = 'business'")

        with self.assertRaises(ApiError) as blocked:
            PostgresBusinessStore(DSN, self.key)
        self.assertEqual(blocked.exception.code, "business_migration_required")
        self.assertIn("migrate-v9", blocked.exception.message)

        res = migrate_postgres_business_v9(
            DSN,
            preflight_confirmed=True,
            backup_confirmed=True,
            data_root=Path(self.temp.name),
        )
        self.assertEqual(
            res,
            {
                "result": "BUSINESS_V9_MIGRATED",
                "backend": "postgresql",
                "schema_version": 9,
                "logical_version": 9,
                "tenants": 1,
                "upgraded": True,
                "orders_backfilled": 2,
            },
        )

        # Re-run is a 100% no-op
        again = migrate_postgres_business_v9(
            DSN,
            preflight_confirmed=True,
            backup_confirmed=True,
            data_root=Path(self.temp.name),
        )
        self.assertEqual((again["upgraded"], again["orders_backfilled"]), (False, 0))

        with transaction(DSN, self.schema, write=True) as db:
            ord_rows = db.execute("SELECT * FROM orders ORDER BY id ASC").fetchall()
            self.assertEqual(len(ord_rows), 2)
            for r in ord_rows:
                self.assertEqual(r["source_system"], "retailops_seed")
                self.assertEqual(r["external_order_id"], r["id"])
                self.assertEqual(r["ordered_at_backfilled"], 1)
                self.assertEqual(r["payment_status"], "unpaid")

            # 'shipping' accepted on orders; invalid status rejected
            db.execute(
                """INSERT INTO orders(
                       id, customer_id, product_id, source_system, external_order_id,
                       name, variant, amount, status, ordered_at
                   ) VALUES ('ord_pg_ship', 'C-PG-1', 'P-101', 'marketplace_sim', 'MS-PG-1', 'Áo', 'M', 350000, 'shipping', 1700001000.0)"""
            )

            # Non-order event (product.upserted) inserts into imported_events with NULL order_id/customer_id
            db.execute(
                """INSERT INTO imported_events(
                       id, source_system, event_id, tenant_id, event_type, sequence, received_via,
                       payload_digest, redacted_fields, payload_json, created_at
                   ) VALUES (
                       'ie_pg_prod', 'marketplace_sim', 'evt-pg-prod-1', 'shop-v9', 'product.upserted', 1, 'import',
                       'digest123', '[]', '{}', 1700001000.0
                   )"""
            )

            # Append-only shipment_events trigger blocks UPDATE and DELETE on real PostgreSQL
            db.execute(
                """INSERT INTO shipments(
                       shipment_id, order_id, source_system, external_shipment_id,
                       carrier, tracking_code, status, carrier_status_raw, updated_at
                   ) VALUES ('shp_pg_1', 'ord_pg_ship', 'marketplace_sim', 'SHP-PG-1', 'GHN', 'GHN999', 'in_transit', 'transporting', 1700001000.0)"""
            )
            db.execute(
                """INSERT INTO shipment_events(
                       shipment_event_id, shipment_id, occurred_at, status, carrier_status_raw, source_event_id
                   ) VALUES ('se_pg_1', 'shp_pg_1', 1700001000.0, 'in_transit', 'transporting', 'evt-pg-se-1')"""
            )

        with self.assertRaises(ApiError):
            with transaction(DSN, self.schema, write=True) as db:
                db.execute("UPDATE shipment_events SET description = 'bad' WHERE shipment_event_id = 'se_pg_1'")
        with self.assertRaises(ApiError):
            with transaction(DSN, self.schema, write=True) as db:
                db.execute("DELETE FROM shipment_events WHERE shipment_event_id = 'se_pg_1'")

        # Duplicate non-empty SKU blocked on real PostgreSQL
        with transaction(DSN, self.schema, write=True) as db:
            db.execute(
                "INSERT INTO product_variants(id, product_id, variant_name, sku) VALUES ('pv_pg_1', 'P-101', 'PG-M', 'SKU-PG-DUP')"
            )
        with self.assertRaises(ApiError):
            with transaction(DSN, self.schema, write=True) as db:
                db.execute(
                    "INSERT INTO product_variants(id, product_id, variant_name, sku) VALUES ('pv_pg_2', 'P-101', 'PG-L', 'SKU-PG-DUP')"
                )


if __name__ == "__main__":
    unittest.main()
