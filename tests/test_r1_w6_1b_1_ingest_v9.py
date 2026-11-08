"""Phase R1 W6.1b-1 isolated & mock/real PostgreSQL tests (Items 0-10)."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import copy
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
from retailops.integration.ingest import IntegrationIngestService
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


def _sample_v2_events() -> dict[str, dict]:
    return {
        "product.upserted": {
            "contract": "retailops-integration-v2",
            "event_id": "evt-prod-sample-0001",
            "event_type": "product.upserted",
            "source_system": "marketplace_sim",
            "merchant_id": "shop-demo",
            "occurred_at": "2026-10-01T08:00:00+07:00",
            "sequence": 1,
            "data": {
                "external_product_id": "P-101",
                "title": "Áo sơ mi Oxford nam",
                "category": "Áo sơ mi",
                "price": 350000,
                "description": "Áo sơ mi công sở chất cotton thoáng mát.",
                "material": "Cotton Oxford",
                "care": "Giặt nước lạnh",
                "warranty_days": 90,
                "variants": [
                    {
                        "sku": "SKU-P101-WHT-M",
                        "variant_name": "Trắng · Size M",
                        "size": "M",
                        "color": "Trắng",
                        "price": 350000,
                        "stock": 12,
                    }
                ],
            },
        },
        "customer.upserted": {
            "contract": "retailops-integration-v2",
            "event_id": "evt-cust-sample-0001",
            "event_type": "customer.upserted",
            "source_system": "marketplace_sim",
            "merchant_id": "shop-demo",
            "occurred_at": "2026-10-01T08:05:00+07:00",
            "sequence": 1,
            "data": {
                "external_customer_id": "SIM-C-0001",
                "display_name": "Nguyễn Thị Minh",
            },
        },
        "order.created": {
            "contract": "retailops-integration-v2",
            "event_id": "evt-ord-sample-0001",
            "event_type": "order.created",
            "source_system": "marketplace_sim",
            "merchant_id": "shop-demo",
            "occurred_at": "2026-10-01T09:00:00+07:00",
            "sequence": 1,
            "data": {
                "external_order_id": "SIM-O-20261001-0001",
                "external_customer_id": "SIM-C-0001",
                "ordered_at": "2026-10-01T09:00:00+07:00",
                "items": [
                    {
                        "sku": "SKU-P101-WHT-M",
                        "external_product_id": "P-101",
                        "title": "Áo sơ mi Oxford nam",
                        "variant_name": "Trắng · Size M",
                        "quantity": 1,
                        "unit_price": 350000,
                    }
                ],
                "shipping_fee": 25000,
                "total": 375000,
                "currency": "VND",
                "payment_method": "cod",
                "promised_delivery_by": "2026-10-04T18:00:00+07:00",
                "recipient": {
                    "name": "Nguyễn Thị Minh",
                    "phone": "0901234567",
                    "address_line": "123 Lê Lợi",
                    "ward": "Phường Bến Nghé",
                    "district": "Quận 1",
                    "province": "TP. Hồ Chí Minh",
                },
            },
        },
        "order.status_changed": {
            "contract": "retailops-integration-v2",
            "event_id": "evt-ordst-sample-0002",
            "event_type": "order.status_changed",
            "source_system": "marketplace_sim",
            "merchant_id": "shop-demo",
            "occurred_at": "2026-10-01T11:00:00+07:00",
            "sequence": 2,
            "data": {
                "external_order_id": "SIM-O-20261001-0001",
                "status": "shipping",
                "reason": None,
            },
        },
        "shipment.updated": {
            "contract": "retailops-integration-v2",
            "event_id": "evt-shp-sample-0001",
            "event_type": "shipment.updated",
            "source_system": "marketplace_sim",
            "merchant_id": "shop-demo",
            "occurred_at": "2026-10-01T14:00:00+07:00",
            "sequence": 1,
            "data": {
                "external_shipment_id": "SIM-S-20261001-0001",
                "external_order_id": "SIM-O-20261001-0001",
                "carrier": "GHN",
                "tracking_code": "GHN88899900",
                "carrier_status_raw": "transporting",
                "hub_name": "Kho phân loại Quận 12",
                "district": "Quận 12",
                "province": "TP. Hồ Chí Minh",
                "description": "Kiện hàng đang trung chuyển",
                "fail_reason": None,
                "shipper_name": "Trần Văn Giao",
                "shipper_phone_masked": "0903***418",
                "estimated_delivery_at": "2026-10-03T17:00:00+07:00",
                "delivery_attempts": 0,
            },
        },
        "payment.updated": {
            "contract": "retailops-integration-v2",
            "event_id": "evt-pay-sample-0001",
            "event_type": "payment.updated",
            "source_system": "payment_sim",
            "merchant_id": "shop-demo",
            "occurred_at": "2026-10-01T09:01:00+07:00",
            "sequence": 1,
            "data": {
                "provider": "payment_sim",
                "provider_txn_ref": "PAY-SIM-0001",
                "external_order_id": "SIM-O-20261001-0001",
                "method": "bank_transfer",
                "amount": 375000,
                "provider_status_raw": "PAY_SUCCEEDED",
                "settled_at": "2026-10-01T09:01:00+07:00",
            },
        },
        "refund.updated": {
            "contract": "retailops-integration-v2",
            "event_id": "evt-ref-sample-0001",
            "event_type": "refund.updated",
            "source_system": "payment_sim",
            "merchant_id": "shop-demo",
            "occurred_at": "2026-10-05T10:00:00+07:00",
            "sequence": 1,
            "data": {
                "provider": "payment_sim",
                "provider_refund_ref": "REF-SIM-0001",
                "provider_txn_ref": "PAY-SIM-0001",
                "external_order_id": "SIM-O-20261001-0001",
                "amount": 350000,
                "channel": "original_method",
                "provider_status_raw": "REFUND_COMPLETED",
                "failure_reason": None,
                "initiated_at": "2026-10-05T09:00:00+07:00",
                "completed_at": "2026-10-05T10:00:00+07:00",
            },
        },
        "voucher.issued": {
            "contract": "retailops-integration-v2",
            "event_id": "evt-vch-sample-0001",
            "event_type": "voucher.issued",
            "source_system": "marketplace_sim",
            "merchant_id": "shop-demo",
            "occurred_at": "2026-10-06T10:00:00+07:00",
            "sequence": 1,
            "data": {
                "external_voucher_id": "VCH-SIM-0001",
                "code": "COMP50K-0001",
                "voucher_type": "amount",
                "value": 50000,
                "valid_until": "2026-11-06T23:59:59+07:00",
                "external_order_id": "SIM-O-20261001-0001",
                "external_customer_id": "SIM-C-0001",
                "request_ref": "req-comp-0001",
            },
        },
        "voucher.requested": {
            "contract": "retailops-integration-v2",
            "event_id": "evt-vchreq-sample-0001",
            "event_type": "voucher.requested",
            "source_system": "retailops",
            "merchant_id": "shop-demo",
            "occurred_at": "2026-10-06T09:55:00+07:00",
            "sequence": 1,
            "data": {
                "request_id": "req-comp-0001",
                "external_order_id": "SIM-O-20261001-0001",
                "external_customer_id": "SIM-C-0001",
                "voucher_type": "amount",
                "value": 50000,
                "reason": "late_delivery",
                "approved_by_role": "staff",
            },
        },
    }


class Item1ContractV2AndRetireV1Tests(unittest.TestCase):
    """W6.1b-1 Item 1 (W6.1b-D3): RetailOps v2 contract validator and v1 sales retirement."""

    def setUp(self) -> None:
        self.samples = _sample_v2_events()

    def test_all_event_types_and_nullable_fields_pass_retailops_validator(self) -> None:
        import copy
        from retailops.integration.contract import (
            ALL_EVENT_TYPES,
            ContractValidationError,
            INBOUND_EVENT_TYPES,
            validate_event_v2,
        )

        self.assertEqual(set(self.samples.keys()), set(ALL_EVENT_TYPES))
        for etype, ev in self.samples.items():
            with self.subTest(event_type=etype):
                out = validate_event_v2(copy.deepcopy(ev))
                self.assertEqual(out["event_type"], etype)
                if etype in INBOUND_EVENT_TYPES:
                    validate_event_v2(copy.deepcopy(ev), allow_requests=False)
                else:
                    with self.assertRaises(ContractValidationError):
                        validate_event_v2(copy.deepcopy(ev), allow_requests=False)

        refund = copy.deepcopy(self.samples["refund.updated"])
        for f in ("provider_txn_ref", "provider_status_raw", "initiated_at", "completed_at"):
            refund["data"][f] = None
        validate_event_v2(refund)

        voucher = copy.deepcopy(self.samples["voucher.issued"])
        for f in ("valid_until", "external_order_id", "external_customer_id", "request_ref"):
            voucher["data"][f] = None
        validate_event_v2(voucher)

    def test_w61a_intentional_negative_mutations_all_rejected(self) -> None:
        import copy
        from retailops.integration.contract import ContractValidationError, validate_event_v2
        from retailops.integration.ingest import redact_order_created_recipient

        # Missing envelope keys
        for env_key in list(self.samples["order.created"].keys()):
            m = copy.deepcopy(self.samples["order.created"])
            del m[env_key]
            with self.assertRaises(ContractValidationError):
                validate_event_v2(m)

        # Missing data keys for every event type
        for etype, base in self.samples.items():
            for dk in list(base["data"].keys()):
                m = copy.deepcopy(base)
                del m["data"][dk]
                with self.assertRaises(ContractValidationError):
                    validate_event_v2(m)

        # Missing nested keys in variants, items, recipient
        for sk in list(self.samples["product.upserted"]["data"]["variants"][0].keys()):
            m = copy.deepcopy(self.samples["product.upserted"])
            del m["data"]["variants"][0][sk]
            with self.assertRaises(ContractValidationError):
                validate_event_v2(m)
        for sk in list(self.samples["order.created"]["data"]["items"][0].keys()):
            m = copy.deepcopy(self.samples["order.created"])
            del m["data"]["items"][0][sk]
            with self.assertRaises(ContractValidationError):
                validate_event_v2(m)
        for sk in list(self.samples["order.created"]["data"]["recipient"].keys()):
            m = copy.deepcopy(self.samples["order.created"])
            del m["data"]["recipient"][sk]
            with self.assertRaises(ContractValidationError):
                validate_event_v2(m)

        # Unknown fields at envelope, data, and nested levels
        m_env = copy.deepcopy(self.samples["customer.upserted"])
        m_env["extra_top"] = "forbidden"
        with self.assertRaises(ContractValidationError):
            validate_event_v2(m_env)

        for etype, base in self.samples.items():
            m = copy.deepcopy(base)
            m["data"]["unexpected_field"] = 1
            with self.assertRaises(ContractValidationError):
                validate_event_v2(m)

        for contact in ("phone", "email", "address"):
            m = copy.deepcopy(self.samples["customer.upserted"])
            m["data"][contact] = "0901234567"
            with self.assertRaises(ContractValidationError):
                validate_event_v2(m)

        m_var = copy.deepcopy(self.samples["product.upserted"])
        m_var["data"]["variants"][0]["extra"] = 1
        with self.assertRaises(ContractValidationError):
            validate_event_v2(m_var)

        m_itm = copy.deepcopy(self.samples["order.created"])
        m_itm["data"]["items"][0]["discount"] = 0
        with self.assertRaises(ContractValidationError):
            validate_event_v2(m_itm)

        m_rec = copy.deepcopy(self.samples["order.created"])
        m_rec["data"]["recipient"]["email"] = "x@y.com"
        with self.assertRaises(ContractValidationError):
            validate_event_v2(m_rec)

        # Booleans, floats, empty items, non-dict, domain & cross-field rules
        bad_cases: list[tuple[str, object]] = [("not_a_dict", ["bad"])]

        def mut(etype: str, fn) -> dict:
            d = copy.deepcopy(self.samples[etype])
            fn(d)
            return d

        bad_cases.extend(
            [
                ("bool_sequence", mut("customer.upserted", lambda d: d.__setitem__("sequence", True))),
                ("bool_price", mut("product.upserted", lambda d: d["data"].__setitem__("price", False))),
                ("float_price", mut("product.upserted", lambda d: d["data"].__setitem__("price", 100.5))),
                ("empty_items", mut("order.created", lambda d: d["data"].__setitem__("items", []))),
                ("wrong_contract", mut("customer.upserted", lambda d: d.__setitem__("contract", "retailops-integration-v1"))),
                ("short_event_id", mut("customer.upserted", lambda d: d.__setitem__("event_id", "short"))),
                ("space_event_id", mut("customer.upserted", lambda d: d.__setitem__("event_id", "bad id spaces"))),
                ("utc_z_ts", mut("customer.upserted", lambda d: d.__setitem__("occurred_at", "2026-10-01T08:00:00Z"))),
                ("offset_08_ts", mut("customer.upserted", lambda d: d.__setitem__("occurred_at", "2026-10-01T08:00:00+08:00"))),
                ("zero_sequence", mut("customer.upserted", lambda d: d.__setitem__("sequence", 0))),
                ("neg_amount", mut("payment.updated", lambda d: d["data"].__setitem__("amount", -1))),
                ("huge_amount", mut("payment.updated", lambda d: d["data"].__setitem__("amount", 10**12 + 1))),
                ("long_text", mut("product.upserted", lambda d: d["data"].__setitem__("description", "A" * 501))),
                ("email_in_text", mut("customer.upserted", lambda d: d["data"].__setitem__("display_name", "Khách a@b.vn"))),
                ("total_mismatch", mut("order.created", lambda d: d["data"].__setitem__("total", d["data"]["total"] + 1000))),
                ("promised_eq_ordered", mut("order.created", lambda d: d["data"].__setitem__("promised_delivery_by", d["data"]["ordered_at"]))),
                ("wrong_currency", mut("order.created", lambda d: d["data"].__setitem__("currency", "USD"))),
                ("wrong_pay_method", mut("order.created", lambda d: d["data"].__setitem__("payment_method", "crypto"))),
                ("bad_order_status", mut("order.status_changed", lambda d: d["data"].__setitem__("status", "returned"))),
                ("unmasked_shipper_phone", mut("shipment.updated", lambda d: d["data"].__setitem__("shipper_phone_masked", "0903123418"))),
                ("attempts_gt_3", mut("shipment.updated", lambda d: d["data"].__setitem__("delivery_attempts", 4))),
                ("mkt_prepaid_payment", mut("payment.updated", lambda d: (d.__setitem__("source_system", "marketplace_sim"), d["data"].__setitem__("method", "bank_transfer")))),
                ("paysim_cod_payment", mut("payment.updated", lambda d: (d.__setitem__("source_system", "payment_sim"), d["data"].__setitem__("method", "cod")))),
                ("bad_refund_channel", mut("refund.updated", lambda d: d["data"].__setitem__("channel", "cash"))),
                ("wrong_refund_source", mut("refund.updated", lambda d: d.__setitem__("source_system", "marketplace_sim"))),
                ("free_ship_nonzero", mut("voucher.issued", lambda d: (d["data"].__setitem__("voucher_type", "free_shipping"), d["data"].__setitem__("value", 30000)))),
                ("voucher_customer_approver", mut("voucher.requested", lambda d: d["data"].__setitem__("approved_by_role", "customer"))),
                ("voucher_bad_reason", mut("voucher.requested", lambda d: d["data"].__setitem__("reason", "vip_gift"))),
            ]
        )

        # Redacted order.created cannot be re-imported (W6.1b-D7)
        redacted_ord, redacted_paths, area = redact_order_created_recipient(self.samples["order.created"])
        self.assertEqual(
            redacted_paths,
            ["data.recipient.name", "data.recipient.phone", "data.recipient.address_line"],
        )
        self.assertEqual(area, "Quận 1, TP. Hồ Chí Minh")
        bad_cases.append(("redacted_order_reimport", redacted_ord))

        for label, bad_ev in bad_cases:
            with self.subTest(case=label):
                with self.assertRaises(ContractValidationError):
                    validate_event_v2(bad_ev)

    def test_voucher_issued_validates_v2_but_returns_422_unsupported_in_w6_1b_1(self) -> None:
        import copy
        from retailops.integration.contract import ensure_w6_1b_1_supported_event, validate_event_v2
        from retailops.integration.ingest import IntegrationIngestService

        vch = copy.deepcopy(self.samples["voucher.issued"])
        validate_event_v2(vch, allow_requests=False)
        with self.assertRaises(ApiError) as err1:
            ensure_w6_1b_1_supported_event("voucher.issued")
        self.assertEqual((err1.exception.status, err1.exception.code), (422, "unsupported_event_type"))

        with tempfile.TemporaryDirectory() as tmp:
            sessions = PersistentSessions(Path(tmp))
            sessions.provision_tenant("shop-demo", "Shop Demo", seed_demo=False)
            svc = IntegrationIngestService(sessions, digest_key=b"test-digest-key-32-bytes-minimum!!")
            with self.assertRaises(ApiError) as err2:
                svc.ingest_event(vch, tenant_id="shop-demo", connector_source_system="marketplace_sim")
            self.assertEqual((err2.exception.status, err2.exception.code), (422, "unsupported_event_type"))

    def test_v1_sales_retired_and_retailops_never_imports_marketplace_sim(self) -> None:
        import ast

        repo_root = Path(__file__).resolve().parents[1]
        sales_dir = repo_root / "retailops" / "sales"
        self.assertEqual(list(sales_dir.rglob("*.py")) if sales_dir.exists() else [], [])

        py_files = (
            list((repo_root / "retailops").rglob("*.py"))
            + list((repo_root / "scripts").rglob("*.py"))
            + list(repo_root.glob("retailops_*.py"))
            + [repo_root / "agent_protocol.py"]
        )
        for py_path in py_files:
            if not py_path.exists():
                continue
            src = py_path.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(py_path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(
                            alias.name == "marketplace_sim" or alias.name.startswith("marketplace_sim."),
                            f"{py_path} imports marketplace_sim",
                        )
                        self.assertFalse(
                            alias.name == "retailops.sales" or alias.name.startswith("retailops.sales."),
                            f"{py_path} imports retired retailops.sales",
                        )
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    self.assertFalse(
                        mod == "marketplace_sim" or mod.startswith("marketplace_sim."),
                        f"{py_path} imports from marketplace_sim",
                    )
                    self.assertFalse(
                        mod == "retailops.sales" or mod.startswith("retailops.sales."),
                        f"{py_path} imports from retired retailops.sales",
                    )


class Item2ConnectorAndComposeSecretsTests(unittest.TestCase):
    """Item 2 (W6.1b-D5): integration_connectors, secret_ref safety, status mappings, CLI & audit."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="r1-w61b1-item2-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out_dir = self.root / "out"
        self.secrets_dir = self.root / "secrets"
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        self.sessions = PersistentSessions(self.out_dir / "persistent")
        self.sessions.provision_tenant("shop-demo", "Shop Demo", seed_demo=False)

    def test_secret_ref_rejects_database_url_and_path_traversal(self) -> None:
        from retailops.integration.connectors import ConnectorManager, validate_secret_ref

        mgr = ConnectorManager(self.sessions, env={"RETAILOPS_CONNECTOR_SECRETS_DIR": str(self.secrets_dir)})
        for bad_ref in (
            "retailops_database_url",
            "postgres_admin_password",
            "../x",
            "retailops_connector_../x",
            "/run/secrets/retailops_connector_x",
            "retailops_connector_UPPER",
            "retailops_connector_",
            "",
        ):
            with self.subTest(secret_ref=bad_ref):
                with self.assertRaises(ApiError) as err1:
                    validate_secret_ref(bad_ref)
                self.assertEqual((err1.exception.status, err1.exception.code), (400, "invalid_secret_ref"))
                with self.assertRaises(ApiError) as err2:
                    mgr.add_connector("shop-demo", source_system="marketplace_sim", secret_ref=bad_ref)
                self.assertEqual((err2.exception.status, err2.exception.code), (400, "invalid_secret_ref"))

    def test_missing_short_directory_and_symlink_keys_fail_closed_503_with_no_default(self) -> None:
        from retailops.integration.connectors import ConnectorManager, inspect_secret_file, load_connector_secret

        env = {"RETAILOPS_CONNECTOR_SECRETS_DIR": str(self.secrets_dir)}
        mgr = ConnectorManager(self.sessions, env=env)
        mgr.add_connector("shop-demo", source_system="marketplace_sim")

        # 1. Missing file -> 503 connector_unavailable (never falls back to default key)
        with self.assertRaises(ApiError) as e_missing:
            mgr.require_ready_connector("shop-demo", "marketplace_sim")
        self.assertEqual((e_missing.exception.status, e_missing.exception.code), (503, "connector_unavailable"))

        # 2. Short key (<32 bytes) -> 503 connector_unavailable
        key_path = self.secrets_dir / "retailops_connector_marketplace_sim"
        key_path.write_bytes(b"short-key-31-bytes-01234567890!")
        self.assertEqual(len(key_path.read_bytes()), 31)
        with self.assertRaises(ApiError) as e_short:
            load_connector_secret("retailops_connector_marketplace_sim", env=env)
        self.assertEqual((e_short.exception.status, e_short.exception.code), (503, "connector_unavailable"))

        # 3. Directory instead of regular file -> 503 connector_unavailable
        key_path.unlink()
        key_path.mkdir()
        self.assertEqual(inspect_secret_file(key_path), (False, "not_regular_file"))
        with self.assertRaises(ApiError) as e_dir:
            load_connector_secret("retailops_connector_marketplace_sim", env=env)
        self.assertEqual((e_dir.exception.status, e_dir.exception.code), (503, "connector_unavailable"))
        key_path.rmdir()

        # 4. Symlink -> 503 connector_unavailable
        real_secret = self.root / "real_target.secret"
        real_secret.write_bytes(b"valid-secret-key-at-least-32-bytes-long!!")
        symlink_created = False
        try:
            os.symlink(real_secret, key_path)
            symlink_created = True
        except (OSError, NotImplementedError):
            symlink_created = False
        if symlink_created:
            self.assertEqual(inspect_secret_file(key_path), (False, "symlink_rejected"))
            with self.assertRaises(ApiError) as e_sym:
                load_connector_secret("retailops_connector_marketplace_sim", env=env)
            self.assertEqual((e_sym.exception.status, e_sym.exception.code), (503, "connector_unavailable"))
            key_path.unlink()
        else:
            # Verify lstat symlink branch deterministically on Windows runners without SeCreateSymbolicLinkPrivilege
            fake_lstat = SimpleNamespace(st_mode=0o120777)
            with patch("retailops.integration.connectors.os.lstat", return_value=fake_lstat), \
                 patch("retailops.integration.ingest.os.lstat", return_value=fake_lstat):
                self.assertEqual(inspect_secret_file(real_secret), (False, "symlink_rejected"))
                with self.assertRaises(ApiError) as e_sym2:
                    load_connector_secret("retailops_connector_marketplace_sim", env={"RETAILOPS_CONNECTOR_SECRETS_DIR": str(self.root)})
                self.assertEqual((e_sym2.exception.status, e_sym2.exception.code), (503, "connector_unavailable"))

        # 5. Valid >=32-byte regular file succeeds
        key_path.write_bytes(b"connector-secret-32-bytes-exact!")
        rec, loaded = mgr.require_ready_connector("shop-demo", "marketplace_sim")
        self.assertEqual(loaded, b"connector-secret-32-bytes-exact!")
        self.assertEqual(rec["merchant_id"], "MERCHANT-SIM-001")

    def test_status_mapping_covers_39_carrier_codes_and_rejects_unknown_without_mutating_db(self) -> None:
        from retailops.integration.connectors import (
            CANONICAL_SHIPMENT_STATUSES,
            ConnectorManager,
            load_default_status_mapping,
            map_raw_status,
            validate_status_mapping,
        )
        from retailops.integration.ingest import IntegrationIngestService

        mapping = load_default_status_mapping("marketplace_sim")
        self.assertEqual(mapping["order"]["shipping"], "shipping")
        self.assertNotEqual(mapping["order"]["shipping"], "delivered")
        for carrier in ("GHN", "FASTSHIP_SIM", "VIETEXPRESS_SIM"):
            self.assertEqual(len(mapping["shipment"][carrier]), 13)
            for raw_code, canonical in mapping["shipment"][carrier].items():
                self.assertIn(canonical, CANONICAL_SHIPMENT_STATUSES)
                self.assertEqual(map_raw_status(mapping, "shipment", raw_code, carrier=carrier), canonical)

        with self.assertRaises(ApiError) as bad_f16:
            validate_status_mapping({"order": {"shipping": "delivered"}})
        self.assertEqual(bad_f16.exception.status, 400)

        for domain, code, kw in (
            ("shipment", "UNKNOWN_CARRIER_STAGE", {"carrier": "GHN"}),
            ("shipment", "delivering", {"carrier": "UNKNOWN_CARRIER"}),
            ("payment", "PAY_MYSTERY", {}),
            ("refund", "REFUND_MYSTERY", {}),
            ("order", "mystery_state", {}),
        ):
            with self.assertRaises(ApiError) as unk:
                map_raw_status(mapping, domain, code, **kw)
            self.assertEqual((unk.exception.status, unk.exception.code), (422, "unknown_status_code"))

        # Unknown status in connector mapping rejects event with 422 and leaves DB untouched
        mgr = ConnectorManager(self.sessions, env={"RETAILOPS_CONNECTOR_SECRETS_DIR": str(self.secrets_dir)})
        partial_map = dict(mapping)
        partial_map["order"] = {"pending": "pending", "shipping": "shipping"}  # omit 'delivered'
        mgr.add_connector("shop-demo", source_system="marketplace_sim", status_mapping=partial_map)

        svc = IntegrationIngestService(self.sessions, digest_key=b"digest-key-at-least-32-bytes-ok!")
        svc.ingest_event(
            {
                "contract": "retailops-integration-v2",
                "event_id": "evt:order:ORD-MAP-1:1",
                "event_type": "order.created",
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "occurred_at": "2026-10-10T09:00:00+07:00",
                "sequence": 1,
                "data": {
                    "external_order_id": "ORD-MAP-1",
                    "external_customer_id": "CUST-MAP-1",
                    "ordered_at": "2026-10-10T09:00:00+07:00",
                    "promised_delivery_by": "2026-10-12T09:00:00+07:00",
                    "payment_method": "cod",
                    "shipping_fee": 20000,
                    "total": 310000,
                    "currency": "VND",
                    "recipient": {
                        "name": "Trần Văn A",
                        "phone": "0900111222",
                        "address_line": "10 Lê Lợi",
                        "ward": "Phường Bến Nghé",
                        "district": "Quận 1",
                        "province": "TP. Hồ Chí Minh",
                    },
                    "items": [
                        {
                            "external_product_id": "P-101",
                            "sku": "SKU-101-M",
                            "title": "Áo sơ mi lụa công sở",
                            "variant_name": "Trắng / M",
                            "quantity": 1,
                            "unit_price": 290000,
                        }
                    ],
                },
            },
            tenant_id="shop-demo",
            connector_source_system="marketplace_sim",
        )
        with self.assertRaises(ApiError) as unk_ev:
            svc.ingest_event(
                {
                    "contract": "retailops-integration-v2",
                    "event_id": "evt:order:ORD-MAP-1:2",
                    "event_type": "order.status_changed",
                    "source_system": "marketplace_sim",
                    "merchant_id": "MERCHANT-SIM-001",
                    "occurred_at": "2026-10-11T09:00:00+07:00",
                    "sequence": 2,
                    "data": {
                        "external_order_id": "ORD-MAP-1",
                        "status": "delivered",
                        "reason": None,
                    },
                },
                tenant_id="shop-demo",
                connector_source_system="marketplace_sim",
            )
        self.assertEqual((unk_ev.exception.status, unk_ev.exception.code), (422, "unknown_status_code"))
        with self.sessions.business_store("shop-demo").connection() as db:
            ord_row = db.execute("SELECT status FROM orders WHERE external_order_id='ORD-MAP-1'").fetchone()
            ev_cnt = db.execute("SELECT COUNT(*) FROM imported_events").fetchone()[0]
        self.assertEqual(ord_row["status"], "pending")
        self.assertEqual(ev_cnt, 1)

    def test_cli_audit_startup_warning_healthz_and_secret_non_leakage(self) -> None:
        import subprocess
        import sys
        from retailops.bootstrap import build_public_app
        from retailops.config import Settings
        from retailops.integration.connectors import warn_unready_connectors_on_startup

        secret_marker = "TOPSECRET_CONNECTOR_KEY_VALUE_32B_XYZ987654"
        digest_marker = "TOPSECRET_DIGEST_KEY_VALUE_32B_ABC123456789"
        conn_key_file = self.secrets_dir / "retailops_connector_marketplace_sim"
        digest_key_file = self.secrets_dir / "retailops_event_digest_key"
        conn_key_file.write_text(secret_marker + "\n", encoding="utf-8")
        digest_key_file.write_text(digest_marker + "\n", encoding="utf-8")

        cli_env = {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "RETAILOPS_OUTPUT": str(self.out_dir),
            "RETAILOPS_STORAGE_BACKEND": "sqlite",
            "RETAILOPS_CONNECTOR_SECRETS_DIR": str(self.secrets_dir),
            "RETAILOPS_EVENT_DIGEST_KEY_FILE": str(digest_key_file),
        }
        repo_root = Path(__file__).resolve().parents[1]

        def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, "-m", "retailops", "connector", "--output", str(self.out_dir), *args],
                cwd=str(repo_root),
                env=cli_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

        res_add = run_cli("add", "--tenant", "shop-demo", "--source-system", "marketplace_sim")
        self.assertEqual(res_add.returncode, 0, res_add.stderr)
        res_list = run_cli("list", "--tenant", "shop-demo")
        self.assertEqual(res_list.returncode, 0, res_list.stderr)
        res_check_ok = run_cli("check")
        self.assertEqual(res_check_ok.returncode, 0, res_check_ok.stderr)

        for out_blob in (res_add.stdout, res_add.stderr, res_list.stdout, res_list.stderr, res_check_ok.stdout):
            self.assertNotIn(secret_marker, out_blob)
            self.assertNotIn(digest_marker, out_blob)

        # Remove connector key: startup logs one warning (source_system + reason only), /healthz remains 200, check fails non-zero
        conn_key_file.unlink()
        res_check_missing = run_cli("check")
        self.assertNotEqual(res_check_missing.returncode, 0)
        self.assertIn("missing_file", res_check_missing.stderr)

        with self.assertLogs("retailops_integration", level="WARNING") as cm:
            warnings_out = warn_unready_connectors_on_startup(self.sessions, env=cli_env)
        self.assertEqual(len(warnings_out), 1)
        self.assertEqual(warnings_out[0]["source_system"], "marketplace_sim")
        self.assertEqual(warnings_out[0]["reason"], "missing_file")
        joined_logs = "\n".join(cm.output)
        self.assertNotIn(secret_marker, joined_logs)
        self.assertNotIn(digest_marker, joined_logs)

        # /healthz remains 200 OK even when connector key is missing
        with patch.dict(
            os.environ,
            {
                "RETAILOPS_ENV": "development",
                "RETAILOPS_DATA_MODE": "persistent-demo",
                "RETAILOPS_STORAGE_BACKEND": "sqlite",
                "RETAILOPS_OUTPUT": str(self.out_dir),
                "RETAILOPS_PUBLIC_ORIGIN": "https://retailops.example.test",
                "RETAILOPS_PUBLIC_HOST": "retailops.example.test",
                "RETAILOPS_API_ENABLED": "false",
                "RETAILOPS_CUSTOM_ENABLED": "false",
                "RETAILOPS_CONNECTOR_SECRETS_DIR": str(self.secrets_dir),
                "RETAILOPS_EVENT_DIGEST_KEY_FILE": "",
            },
            clear=False,
        ):
            pub_app = build_public_app(Settings.from_environment("public"))
            try:
                status_code, result_obj, _mime, _headers = pub_app.route(
                    {
                        "REQUEST_METHOD": "GET",
                        "PATH_INFO": "/healthz",
                        "REMOTE_ADDR": "127.0.0.1",
                        "HTTP_HOST": "127.0.0.1:8000",
                    }
                )
                self.assertEqual(status_code, 200)
                self.assertEqual(result_obj["status"], "ok")
            finally:
                pub_app.stop_case_timer_worker()

        # Disable connector -> connector check passes when digest key exists, fails when digest key missing
        res_dis = run_cli("disable", "--tenant", "shop-demo", "--source-system", "marketplace_sim")
        self.assertEqual(res_dis.returncode, 0, res_dis.stderr)
        self.assertEqual(run_cli("check").returncode, 0)
        digest_key_file.unlink()
        res_check_no_digest = run_cli("check")
        self.assertNotEqual(res_check_no_digest.returncode, 0)
        self.assertIn("event_digest_key", res_check_no_digest.stderr)

        # Verify admin_audit_log recorded add, list, disable and contains zero secret bytes
        with self.sessions.control.connection() as id_db:
            audits = [
                dict(r)
                for r in id_db.execute(
                    "SELECT action, before_json, after_json, reason FROM admin_audit_log WHERE tenant_id='shop-demo' ORDER BY id ASC"
                ).fetchall()
            ]
        actions = [a["action"] for a in audits]
        self.assertIn("connector.add", actions)
        self.assertIn("connector.list", actions)
        self.assertIn("connector.disable", actions)
        audit_dump = json.dumps(audits, ensure_ascii=False)
        self.assertNotIn(secret_marker, audit_dump)
        self.assertNotIn(digest_marker, audit_dump)


class Item3InternalRouteAndImportEventsCliTests(unittest.TestCase):
    """Item 3 (W6.1b-D4): /internal/integrations/<tenant>/<source>/events HMAC & proxy guards + import-events CLI."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="r1-w61b1-item3-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out_dir = self.root / "out"
        self.secrets_dir = self.root / "secrets"
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        self.conn_secret = b"connector-hmac-secret-32-bytes-ok!"
        self.digest_secret = b"event-digest-hmac-key-32-bytes-ok!"
        (self.secrets_dir / "retailops_connector_marketplace_sim").write_bytes(self.conn_secret + b"\n")
        self.digest_file = self.secrets_dir / "retailops_event_digest_key"
        self.digest_file.write_bytes(self.digest_secret + b"\n")

        self.sessions = PersistentSessions(self.out_dir / "persistent")
        self.sessions.provision_tenant("shop-demo", "Shop Demo", seed_demo=False)

    def _make_order_event(
        self,
        *,
        event_id: str = "evt:order:ORD-I3-1:1",
        ext_order_id: str = "ORD-I3-1",
        merchant_id: str = "MERCHANT-SIM-001",
        occurred_at: str = "2026-10-10T08:00:00+07:00",
        ordered_at: str = "2026-10-10T08:00:00+07:00",
        promised_by: str = "2026-10-12T08:00:00+07:00",
    ) -> dict:
        return {
            "contract": "retailops-integration-v2",
            "event_id": event_id,
            "event_type": "order.created",
            "source_system": "marketplace_sim",
            "merchant_id": merchant_id,
            "occurred_at": occurred_at,
            "sequence": 1,
            "data": {
                "external_order_id": ext_order_id,
                "external_customer_id": "CUST-I3-1",
                "ordered_at": ordered_at,
                "promised_delivery_by": promised_by,
                "payment_method": "cod",
                "shipping_fee": 25000,
                "total": 315000,
                "currency": "VND",
                "recipient": {
                    "name": "Lê Thị Mẫu",
                    "phone": "0909888777",
                    "address_line": "99 Nguyễn Huệ",
                    "ward": "Phường Bến Nghé",
                    "district": "Quận 1",
                    "province": "TP. Hồ Chí Minh",
                },
                "items": [
                    {
                        "external_product_id": "P-101",
                        "sku": "SKU-101-S",
                        "title": "Áo sơ mi lụa công sở",
                        "variant_name": "Trắng / S",
                        "quantity": 1,
                        "unit_price": 290000,
                    }
                ],
            },
        }

    def test_internal_route_auth_proxy_connector_and_replay_guards(self) -> None:
        import threading
        import time
        import urllib.error
        import urllib.request
        from wsgiref.simple_server import WSGIRequestHandler, make_server
        from retailops.http.public import PublicWeb
        from retailops.integration.connectors import ConnectorManager
        from retailops.integration.intake import compute_sim_hmac_signature

        class QuietHandler(WSGIRequestHandler):
            def log_message(self, format, *args):  # noqa: A002
                pass

        env_vars = {
            "RETAILOPS_CONNECTOR_SECRETS_DIR": str(self.secrets_dir),
            "RETAILOPS_EVENT_DIGEST_KEY_FILE": str(self.digest_file),
        }
        with patch.dict(os.environ, env_vars, clear=False):
            mgr = ConnectorManager(self.sessions)
            pub = PublicWeb("https://retailops.example.test", self.sessions, start_timer_worker=False)
            httpd = make_server("127.0.0.1", 0, pub, handler_class=QuietHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                base_url = f"http://127.0.0.1:{port}"
                target_url = f"{base_url}/internal/integrations/shop-demo/marketplace_sim/events"
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

                def post_raw(url: str, raw_body: bytes, hdrs: dict[str, str]) -> tuple[int, dict]:
                    req = urllib.request.Request(
                        url,
                        data=raw_body,
                        headers={"Content-Type": "application/json; charset=utf-8", **hdrs},
                        method="POST",
                    )
                    try:
                        with opener.open(req, timeout=5) as resp:
                            return int(resp.getcode()), json.loads(resp.read().decode("utf-8"))
                    except urllib.error.HTTPError as exc:
                        return int(exc.code), json.loads(exc.read().decode("utf-8"))

                ev = self._make_order_event()
                raw = json.dumps(ev, ensure_ascii=False).encode("utf-8")
                ts_now = int(time.time())
                valid_hdrs = {
                    "X-Sim-Event-Id": ev["event_id"],
                    "X-Sim-Timestamp": str(ts_now),
                    "X-Sim-Signature": compute_sim_hmac_signature(self.conn_secret, ts_now, raw),
                }

                # 1. Connector not added yet -> 404
                code, _ = post_raw(target_url, raw, valid_hdrs)
                self.assertEqual(code, 404)

                # Add connector, then disable -> 503
                mgr.add_connector("shop-demo", source_system="marketplace_sim")
                mgr.disable_connector("shop-demo", source_system="marketplace_sim")
                code, body = post_raw(target_url, raw, valid_hdrs)
                self.assertEqual((code, body["error"]), (503, "connector_unavailable"))

                # Re-enable connector
                mgr.add_connector("shop-demo", source_system="marketplace_sim")

                # 2. Proxy headers -> 404
                for proxy_h, proxy_v in (
                    ("X-Forwarded-For", "203.0.113.10"),
                    ("Via", "1.1 caddy"),
                    ("X-Forwarded-Proto", "https"),
                    ("Forwarded", "for=198.51.100.1"),
                    ("X-Real-IP", "198.51.100.2"),
                ):
                    code, body = post_raw(target_url, raw, {**valid_hdrs, proxy_h: proxy_v})
                    self.assertEqual((code, body["error"]), (404, "not_found"), proxy_h)

                # 3. Bad signature -> 401
                code, _ = post_raw(
                    target_url,
                    raw,
                    {**valid_hdrs, "X-Sim-Signature": "v1=" + ("0" * 64)},
                )
                self.assertEqual(code, 401)

                # 4. Stale timestamp (>300s) -> 401
                old_ts = ts_now - 305
                code, _ = post_raw(
                    target_url,
                    raw,
                    {
                        "X-Sim-Event-Id": ev["event_id"],
                        "X-Sim-Timestamp": str(old_ts),
                        "X-Sim-Signature": compute_sim_hmac_signature(self.conn_secret, old_ts, raw),
                    },
                )
                self.assertEqual(code, 401)

                # 5. Mismatched X-Sim-Event-Id -> 401
                code, _ = post_raw(
                    target_url,
                    raw,
                    {**valid_hdrs, "X-Sim-Event-Id": "evt:other:999"},
                )
                self.assertEqual(code, 401)

                # 6. Wrong merchant_id -> 401
                bad_m_ev = self._make_order_event(
                    event_id="evt:order:ORD-BAD-M:1",
                    ext_order_id="ORD-BAD-M",
                    merchant_id="WRONG-MERCHANT",
                )
                bad_m_raw = json.dumps(bad_m_ev, ensure_ascii=False).encode("utf-8")
                code, body = post_raw(
                    target_url,
                    bad_m_raw,
                    {
                        "X-Sim-Event-Id": bad_m_ev["event_id"],
                        "X-Sim-Timestamp": str(ts_now),
                        "X-Sim-Signature": compute_sim_hmac_signature(self.conn_secret, ts_now, bad_m_raw),
                    },
                )
                self.assertEqual((code, body["error"]), (401, "merchant_id_mismatch"))

                # 7. Valid first delivery -> 200; replay -> 409 duplicate_event without changing DB
                code1, body1 = post_raw(target_url, raw, valid_hdrs)
                self.assertEqual(code1, 200)
                self.assertTrue(body1["ok"])
                with self.sessions.business_store("shop-demo").connection() as db:
                    orders_before = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
                    events_before = db.execute("SELECT COUNT(*) FROM imported_events").fetchone()[0]

                code2, body2 = post_raw(target_url, raw, valid_hdrs)
                self.assertEqual((code2, body2["error"]), (409, "duplicate_event"))
                with self.sessions.business_store("shop-demo").connection() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM orders").fetchone()[0], orders_before)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM imported_events").fetchone()[0], events_before)
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_import_events_cli_idempotent_replay_audit_and_rebase_clock(self) -> None:
        import subprocess
        import sys
        from retailops.integration.contract import iso_vn_to_epoch
        from retailops.integration.intake import import_events_jsonl

        ev1 = self._make_order_event(
            event_id="evt:order:ORD-IMP-1:1",
            ext_order_id="ORD-IMP-1",
            occurred_at="2026-10-05T10:00:00+07:00",
            ordered_at="2026-10-05T10:00:00+07:00",
            promised_by="2026-10-07T10:00:00+07:00",
        )
        ev2 = self._make_order_event(
            event_id="evt:order:ORD-IMP-2:1",
            ext_order_id="ORD-IMP-2",
            occurred_at="2026-10-10T10:00:00+07:00",
            ordered_at="2026-10-10T10:00:00+07:00",
            promised_by="2026-10-13T10:00:00+07:00",
        )
        jsonl_file = self.root / "batch.jsonl"
        jsonl_file.write_text(
            json.dumps(ev1, ensure_ascii=False) + "\n" + json.dumps(ev2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        fixed_now = 1800000000.0
        res1 = import_events_jsonl(
            self.sessions,
            tenant_id="shop-demo",
            source_system="marketplace_sim",
            jsonl_path=jsonl_file,
            rebase_clock="now",
            now_fn=lambda: fixed_now,
            digest_key=self.digest_secret,
        )
        self.assertEqual((res1["received"], res1["duplicates"], res1["errors"]), (2, 0, 0))
        expected_offset = fixed_now - iso_vn_to_epoch("2026-10-10T10:00:00+07:00", "occurred_at")
        self.assertAlmostEqual(res1["rebase_offset_seconds"], expected_offset, places=3)

        # Verify relative intervals preserved after --rebase-clock now
        with self.sessions.business_store("shop-demo").connection() as db:
            r1 = dict(db.execute("SELECT * FROM orders WHERE external_order_id='ORD-IMP-1'").fetchone())
            r2 = dict(db.execute("SELECT * FROM orders WHERE external_order_id='ORD-IMP-2'").fetchone())
        self.assertAlmostEqual(r2["ordered_at"], fixed_now, places=3)
        self.assertAlmostEqual(r2["ordered_at"] - r1["ordered_at"], 5 * 86400.0, places=3)
        self.assertAlmostEqual(r1["promised_delivery_by"] - r1["ordered_at"], 2 * 86400.0, places=3)
        self.assertAlmostEqual(r2["promised_delivery_by"] - r2["ordered_at"], 3 * 86400.0, places=3)

        # Second run via packaged CLI reports only duplicates
        cli_env = {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "RETAILOPS_OUTPUT": str(self.out_dir),
            "RETAILOPS_STORAGE_BACKEND": "sqlite",
            "RETAILOPS_EVENT_DIGEST_KEY_FILE": str(self.digest_file),
        }
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "retailops",
                "database",
                "--output",
                str(self.out_dir),
                "import-events",
                "--tenant",
                "shop-demo",
                "--source-system",
                "marketplace_sim",
                "--file",
                str(jsonl_file),
            ],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=cli_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        res2 = json.loads(proc.stdout)
        self.assertEqual((res2["received"], res2["duplicates"], res2["errors"]), (0, 2, 0))

        with self.sessions.control.connection() as id_db:
            audits = [
                json.loads(r["after_json"])
                for r in id_db.execute(
                    "SELECT after_json FROM admin_audit_log WHERE action='database.import_events' ORDER BY id ASC"
                ).fetchall()
            ]
        self.assertEqual(len(audits), 2)
        self.assertEqual((audits[0]["received"], audits[0]["duplicates"]), (2, 0))
        self.assertEqual((audits[1]["received"], audits[1]["duplicates"]), (0, 2))


class Item4CanonicalModelAndPiiTests(unittest.TestCase):
    """W6.1b-1 Item 4: canonical writes, sequence monotonicity, non-regression, HMAC digest & PII redaction."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.digest_key = b"item4-hmac-digest-secret-32-bytes!!"
        self.sessions = PersistentSessions(self.root / "persistent")
        self.sessions.provision_tenant("shop-demo", "Shop Demo", seed_demo=False)
        self.service = IntegrationIngestService(self.sessions, digest_key=self.digest_key)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_hmac_digest_pii_redaction_and_missing_digest_key_rejection(self) -> None:
        import hashlib
        import hmac

        ev = _sample_v2_events()["order.created"]
        ev["data"]["recipient"] = {
            "name": "Phạm Thị Thu Hương",
            "phone": "0123987654",
            "address_line": "Số 88 Đường Nguyễn Huệ, Tầng 5",
            "ward": "Phường Bến Nghé",
            "district": "Quận 1",
            "province": "TP. Hồ Chí Minh",
        }
        raw_line = json.dumps(ev, ensure_ascii=False, separators=(",", ":"))
        raw_bytes = raw_line.encode("utf-8")

        # Missing digest key must fail closed with 503 and leave DB untouched
        no_key_service = IntegrationIngestService(self.sessions, digest_key=None)
        with patch.dict(os.environ, {"RETAILOPS_EVENT_DIGEST_KEY_FILE": ""}, clear=False):
            with self.assertRaises(ApiError) as missing_err:
                no_key_service.ingest_event(raw_bytes, tenant_id="shop-demo")
        self.assertEqual((missing_err.exception.status, missing_err.exception.code), (503, "connector_unavailable"))

        res = self.service.ingest_event(
            raw_bytes,
            tenant_id="shop-demo",
            rebase_offset_seconds=3600.0,
        )
        self.assertTrue(res.success)
        self.assertTrue(res.order_id.startswith("ord_"))

        expected_hmac = hmac.new(self.digest_key, raw_bytes, hashlib.sha256).hexdigest()
        plain_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        self.assertNotEqual(expected_hmac, plain_sha256)

        bstore = self.sessions.business_store("shop-demo")
        with bstore.connection() as db:
            imp = dict(
                db.execute(
                    "SELECT * FROM imported_events WHERE event_id=?", (ev["event_id"],)
                ).fetchone()
            )
            self.assertEqual(imp["payload_digest"], expected_hmac)
            self.assertNotEqual(imp["payload_digest"], plain_sha256)
            self.assertEqual(
                json.loads(imp["redacted_fields"]),
                [
                    "data.recipient.name",
                    "data.recipient.phone",
                    "data.recipient.address_line",
                ],
            )
            stored_payload = json.loads(imp["payload_json"])
            rec = stored_payload["data"]["recipient"]
            self.assertEqual(
                set(rec.keys()),
                {"name", "phone", "address_line", "ward", "district", "province"},
            )
            self.assertIsNone(rec["name"])
            self.assertIsNone(rec["phone"])
            self.assertIsNone(rec["address_line"])
            self.assertEqual(rec["ward"], "Phường Bến Nghé")
            self.assertEqual(rec["district"], "Quận 1")
            self.assertEqual(rec["province"], "TP. Hồ Chí Minh")

            # Scan every table & column in tenant DB for PII leaks
            tables = [
                r["name"]
                for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            for tbl in tables:
                for row in db.execute(f"SELECT * FROM {tbl}").fetchall():
                    dumped = json.dumps(dict(row), ensure_ascii=False)
                    self.assertNotIn("Phạm Thị Thu Hương", dumped, tbl)
                    self.assertNotIn("0123987654", dumped, tbl)
                    self.assertNotIn("Số 88 Đường Nguyễn Huệ", dumped, tbl)

            # W6.1b-2 tables must remain completely empty
            for empty_tbl in ("order_recipients", "delivery_compensations", "vouchers"):
                cnt = db.execute(f"SELECT COUNT(*) AS c FROM {empty_tbl}").fetchone()["c"]
                self.assertEqual(cnt, 0, empty_tbl)

    def test_two_sources_same_external_order_id_and_sequence_non_regression(self) -> None:
        base_events = _sample_v2_events()

        # F17: Same external_order_id from two different sources creates two distinct orders.id
        ev_src_a = copy.deepcopy(base_events["order.created"])
        ev_src_a["event_id"] = "evt:srcA:same-oid:1"
        ev_src_a["source_system"] = "marketplace_sim"
        ev_src_a["data"]["external_order_id"] = "EXT-SHARED-999"

        ev_src_b = copy.deepcopy(base_events["order.created"])
        ev_src_b["event_id"] = "evt:srcB:same-oid:1"
        ev_src_b["source_system"] = "marketplace_b_sim"
        ev_src_b["data"]["external_order_id"] = "EXT-SHARED-999"

        res_a = self.service.ingest_event(
            ev_src_a, tenant_id="shop-demo", connector_source_system="marketplace_sim"
        )
        res_b = self.service.ingest_event(
            ev_src_b, tenant_id="shop-demo", connector_source_system="marketplace_b_sim"
        )
        self.assertNotEqual(res_a.order_id, res_b.order_id)

        # F16: order.status_changed 'shipping' -> canonical 'shipping' (never 'delivered')
        ev_ship = copy.deepcopy(base_events["order.status_changed"])
        ev_ship["event_id"] = "evt:srcA:same-oid:3"
        ev_ship["sequence"] = 3
        ev_ship["data"]["external_order_id"] = "EXT-SHARED-999"
        ev_ship["data"]["status"] = "shipping"
        self.service.ingest_event(ev_ship, tenant_id="shop-demo")

        bstore = self.sessions.business_store("shop-demo")
        with bstore.connection() as db:
            st = db.execute("SELECT status FROM orders WHERE id=?", (res_a.order_id,)).fetchone()["status"]
        self.assertEqual(st, "shipping")

        # Out-of-order lower sequence (seq=2 'confirmed') still records imported_events, does NOT regress order
        ev_late_confirmed = copy.deepcopy(base_events["order.status_changed"])
        ev_late_confirmed["event_id"] = "evt:srcA:same-oid:2"
        ev_late_confirmed["sequence"] = 2
        ev_late_confirmed["data"]["external_order_id"] = "EXT-SHARED-999"
        ev_late_confirmed["data"]["status"] = "confirmed"
        res_late = self.service.ingest_event(ev_late_confirmed, tenant_id="shop-demo")
        self.assertTrue(res_late.sequence_ignored)

        # Higher sequence with regressed canonical status ('pending' after 'shipping') also does NOT regress
        ev_regress = copy.deepcopy(base_events["order.status_changed"])
        ev_regress["event_id"] = "evt:srcA:same-oid:4"
        ev_regress["sequence"] = 4
        ev_regress["data"]["external_order_id"] = "EXT-SHARED-999"
        ev_regress["data"]["status"] = "pending"
        res_reg = self.service.ingest_event(ev_regress, tenant_id="shop-demo")
        self.assertTrue(res_reg.sequence_ignored)

        # Shipment out-of-order & status non-regression
        shp_1 = copy.deepcopy(base_events["shipment.updated"])
        shp_1["event_id"] = "evt:shp:EXT-SHARED-999:2"
        shp_1["sequence"] = 2
        shp_1["data"]["external_order_id"] = "EXT-SHARED-999"
        shp_1["data"]["external_shipment_id"] = "SHP-SHARED-1"
        shp_1["data"]["carrier_status_raw"] = "delivering"
        self.service.ingest_event(shp_1, tenant_id="shop-demo")

        shp_old = copy.deepcopy(shp_1)
        shp_old["event_id"] = "evt:shp:EXT-SHARED-999:1"
        shp_old["sequence"] = 1
        shp_old["data"]["carrier_status_raw"] = "ready_to_pick"
        res_shp_old = self.service.ingest_event(shp_old, tenant_id="shop-demo")
        self.assertTrue(res_shp_old.sequence_ignored)

        shp_reg = copy.deepcopy(shp_1)
        shp_reg["event_id"] = "evt:shp:EXT-SHARED-999:3"
        shp_reg["sequence"] = 3
        shp_reg["data"]["carrier_status_raw"] = "picked"
        res_shp_reg = self.service.ingest_event(shp_reg, tenant_id="shop-demo")
        self.assertTrue(res_shp_reg.sequence_ignored)

        with bstore.connection() as db:
            ord_row = db.execute("SELECT status FROM orders WHERE id=?", (res_a.order_id,)).fetchone()
            shp_row = db.execute(
                "SELECT shipment_id, status FROM shipments WHERE external_shipment_id='SHP-SHARED-1'"
            ).fetchone()
            se_cnt = db.execute(
                "SELECT COUNT(*) AS c FROM shipment_events WHERE shipment_id=?",
                (shp_row["shipment_id"],),
            ).fetchone()["c"]
            ie_cnt = db.execute(
                "SELECT COUNT(*) AS c FROM imported_events WHERE order_id=?",
                (res_a.order_id,),
            ).fetchone()["c"]
        self.assertEqual(ord_row["status"], "shipping")
        self.assertEqual(shp_row["status"], "out_for_delivery")
        self.assertEqual(se_cnt, 1)
        self.assertEqual(ie_cnt, 7)


if __name__ == "__main__":
    unittest.main()
