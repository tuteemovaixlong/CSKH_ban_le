"""Phase R1 W3 isolated tests for Business v6, order actions, evidence, outbox, and UI/agent contracts."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from retailops.business.application import Application
from retailops.business.schema import (
    BUSINESS_V5_VERSION_MAPPING,
    BUSINESS_V6_VERSION_MAPPING,
    POSTGRES_BUSINESS_SCHEMA_CURRENT,
    SQLITE_BUSINESS_SCHEMA_CURRENT,
    ensure_case_tables,
)
from retailops.business.store import (
    BusinessStore,
    _inspect_sqlite_business_ready,
    migrate_sqlite_business_v6,
)
from retailops.core import ApiError
from retailops.http.public import PublicWeb
from retailops.identity.persistent import PersistentSessions
from retailops.identity.postgres import PostgresSessions
from retailops.identity.store import IdentityStore
from retailops.storage import cli as database_cli
from retailops.storage.pg_repositories import (
    PostgresBusinessStore,
    migrate_postgres_business_v6,
    migrate_postgres_business_v7,
)
from retailops.storage.pg_schema import (
    BUSINESS_DDL,
    BUSINESS_V5_DDL,
    P5C_BUSINESS_DDL,
    initialize as pg_initialize,
)
from retailops.storage.postgres import (
    BUSINESS_SCHEMA_CURRENT,
    IDENTITY_SCHEMA,
    tenant_schema,
)


def _create_sqlite_v5_tenant_db(path: Path) -> None:
    """Create a realistic Business v5 (SQLite v4) tenant DB fixture before W3 v6 existed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("CREATE TABLE retailops_schema (component TEXT PRIMARY KEY, version INTEGER NOT NULL)")
        db.execute("INSERT INTO retailops_schema VALUES ('business', 4)")
        db.execute("CREATE TABLE customers (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
        db.execute("INSERT INTO customers VALUES ('C-001', 'Khách A'), ('C-002', 'Khách B')")
        db.execute(
            """CREATE TABLE products (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, aliases TEXT NOT NULL DEFAULT '[]',
                category TEXT, price BIGINT, stock INTEGER, warranty_days INTEGER, description TEXT,
                variants TEXT NOT NULL DEFAULT '[]', material TEXT, care TEXT,
                is_system_immutable INTEGER NOT NULL DEFAULT 0, extra_data TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            )"""
        )
        db.execute(
            "INSERT INTO products(id, name, created_at, updated_at) VALUES ('P-101', 'Áo sơ mi', 1000.0, 1000.0)"
        )
        # Note: NO delivered_at column on pre-v6 orders
        db.execute(
            """CREATE TABLE orders (
                id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, name TEXT NOT NULL,
                variant TEXT NOT NULL, amount INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','delivered','cancelled')),
                version INTEGER NOT NULL DEFAULT 1, cancel_reason TEXT,
                product_id TEXT REFERENCES products(id)
            )"""
        )
        db.execute(
            "INSERT INTO orders VALUES ('O-101', 'C-001', 'Áo sơ mi', 'Trắng / M', 350000, 'pending', 1, NULL, 'P-101')"
        )
        db.execute(
            "INSERT INTO orders VALUES ('O-102', 'C-001', 'Áo sơ mi', 'Đen / L', 350000, 'delivered', 2, NULL, 'P-101')"
        )
        db.execute(
            """CREATE TABLE proposals (
                id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, order_id TEXT NOT NULL REFERENCES orders(id),
                order_version INTEGER NOT NULL, reason TEXT NOT NULL,
                expires_at REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                confirm_key TEXT, result TEXT, UNIQUE(customer_id, confirm_key)
            )"""
        )
        # Draft pending proposal that MUST NOT be backfilled into order_action_requests (W3-D9)
        db.execute(
            "INSERT INTO proposals VALUES ('prop-draft-1', 'C-001', 'O-101', 1, 'changed_mind', 9999999999.0, 'pending', NULL, NULL)"
        )
        db.execute(
            """CREATE TABLE business_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT NOT NULL,
                created_at REAL NOT NULL, kind TEXT NOT NULL, order_id TEXT, payload TEXT NOT NULL
            )"""
        )
        db.execute(
            """CREATE TABLE conversations (
                id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, order_id TEXT, product_id TEXT,
                revision INTEGER NOT NULL DEFAULT 0, expires_at REAL NOT NULL,
                provider_id TEXT NOT NULL DEFAULT 'custom'
            )"""
        )
        db.execute(
            "INSERT INTO conversations VALUES ('conv-v5-1', 'C-001', 'O-101', NULL, 1, 9999999999.0, 'custom')"
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
        from retailops.workflow.schema import initialize as graph_schema

        graph_schema(db)
        ensure_case_tables(db)
        db.execute(
            """INSERT INTO cases(
                case_id, conversation_id, customer_id, status, version, resume_count, created_at, updated_at
            ) VALUES ('case_v5_1', 'conv-v5-1', 'C-001', 'waiting', 1, 0, 1000.0, 1000.0)"""
        )
        db.commit()
    finally:
        db.close()


def _build_mock_pg_harness(tenant_keys_v5: list[str]):
    """Build an in-memory SQLite-backed mock PostgreSQL harness seeded with Business v5 (PG v5) tenants."""
    state = SimpleNamespace(identity_version=5, tenants=[], schemas={})

    def _exec_pg_ddl_on_sqlite(mem: sqlite3.Connection, statement: str, params=()):
        q = " ".join(statement.strip().split())
        if q.startswith("REVOKE ALL ON SCHEMA ") or "USING gin" in q or "USING hnsw" in q:
            return []
        if q.startswith("CREATE OR REPLACE FUNCTION ") or q.startswith("DROP TRIGGER IF EXISTS "):
            return []
        if "EXECUTE FUNCTION order_action_decisions_immutable()" in q:
            mem.execute(
                "CREATE TRIGGER IF NOT EXISTS order_action_decisions_no_update "
                "BEFORE UPDATE ON order_action_decisions "
                "BEGIN SELECT RAISE(ABORT, 'order_action_decisions is append-only'); END"
            )
            mem.execute(
                "CREATE TRIGGER IF NOT EXISTS order_action_decisions_no_delete "
                "BEFORE DELETE ON order_action_decisions "
                "BEGIN SELECT RAISE(ABORT, 'order_action_decisions is append-only'); END"
            )
            mem.commit()
            return []
        if q.startswith("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at"):
            cols = {r[1] for r in mem.execute("PRAGMA table_info(orders)").fetchall()}
            if "delivered_at" not in cols:
                mem.execute("ALTER TABLE orders ADD COLUMN delivered_at REAL")
                mem.commit()
            return []
        # Business v7 upgrade statements. SQLite cannot emulate PL/pgSQL DO blocks (they only drop and add
        # named CHECK constraints), so they are no-ops here; the real PostgreSQL run is covered by the
        # RETAILOPS_TEST_DATABASE_URL test in test_r1_w3_2_business_v7.py.
        if q.startswith("DO $$"):
            return []
        if q.startswith("ALTER TABLE order_action_requests ADD COLUMN IF NOT EXISTS "):
            column = q.split("IF NOT EXISTS ", 1)[1].split()[0]
            cols = {r[1] for r in mem.execute("PRAGMA table_info(order_action_requests)").fetchall()}
            if column not in cols:
                mem.execute(q.replace(" IF NOT EXISTS", ""))
                mem.commit()
            return []
        sql_sqlite = (
            statement.replace("%s", "?")
            .replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
            .replace("DOUBLE PRECISION", "REAL")
            .replace("retailops_extensions.vector(384)", "TEXT")
            .replace("tsvector GENERATED", "TEXT GENERATED")
            .replace("char_length(", "length(")
        )
        cur = mem.execute(sql_sqlite, tuple(params or ()))
        mem.commit()
        if cur.description:
            return [dict(r) for r in cur.fetchall()]
        return []

    base_v4_ddl = [
        stmt
        for stmt in BUSINESS_DDL
        if "order_action_" not in stmt and "integration_outbox" not in stmt
    ]
    for idx, key in enumerate(tenant_keys_v5, start=1):
        tid = f"shop-{idx}"
        sc = tenant_schema(key)
        state.tenants.append({"id": tid, "storage_key": key, "active": 1})
        mem = sqlite3.connect(":memory:")
        mem.row_factory = sqlite3.Row
        mem.execute("PRAGMA foreign_keys=ON")
        for stmt in base_v4_ddl:
            if stmt.lstrip().startswith("CREATE TABLE orders"):
                # Pre-v6 orders table has NO delivered_at column
                stmt = stmt.replace(",\n        delivered_at DOUBLE PRECISION", "")
            if stmt in BUSINESS_V5_DDL or stmt in P5C_BUSINESS_DDL:
                continue
            _exec_pg_ddl_on_sqlite(mem, stmt)
        for stmt in P5C_BUSINESS_DDL:
            _exec_pg_ddl_on_sqlite(mem, stmt)
        for stmt in BUSINESS_V5_DDL:
            _exec_pg_ddl_on_sqlite(mem, stmt)
        mem.execute("CREATE TABLE retailops_schema (component TEXT PRIMARY KEY, version INTEGER NOT NULL)")
        mem.execute("INSERT INTO retailops_schema VALUES ('business', 5)")
        mem.execute("INSERT INTO customers VALUES ('C-001', 'Khách PG')")
        mem.execute(
            "INSERT INTO products(id, name, created_at, updated_at) VALUES ('P-101', 'Áo PG', 1000.0, 1000.0)"
        )
        mem.execute(
            "INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version) "
            "VALUES ('O-101', 'C-001', 'P-101', 'Áo PG', 'Đen / M', 320000, 'pending', 1)"
        )
        mem.execute(
            "INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version) "
            "VALUES ('O-102', 'C-001', 'P-101', 'Áo PG', 'Trắng / L', 320000, 'delivered', 2)"
        )
        mem.execute(
            "INSERT INTO proposals(id, customer_id, order_id, order_version, reason, expires_at, state) "
            "VALUES ('prop-pg-draft', 'C-001', 'O-101', 1, 'changed_mind', 9999999999.0, 'pending')"
        )
        mem.commit()
        state.schemas[sc] = mem

    class _CursorAdapter:
        def __init__(self, rows):
            self._rows = list(rows)

        def fetchone(self):
            return self._rows[0] if self._rows else None

        def fetchall(self):
            return list(self._rows)

    class _MockPgConn:
        def __init__(self, active_schema):
            self.active_schema = active_schema
            self.raw = self

        def execute(self, query, params=()):
            q = " ".join(str(query).strip().split())
            norm_params = tuple(params or ())
            if "FROM pg_extension" in q:
                return _CursorAdapter([{"schema": "retailops_extensions", "version": "0.7.0"}])
            if "FROM pg_namespace" in q:
                target = norm_params[0]
                exists = target == IDENTITY_SCHEMA or target in state.schemas
                return _CursorAdapter([{"?column?": 1}] if exists else [])
            if q.startswith("CREATE SCHEMA "):
                new_sc = q.split("CREATE SCHEMA ", 1)[1].strip().strip('"')
                mem = sqlite3.connect(":memory:")
                mem.row_factory = sqlite3.Row
                mem.execute("PRAGMA foreign_keys=ON")
                mem.create_function("to_tsvector", 2, lambda _cfg, txt: txt, deterministic=True)
                state.schemas[new_sc] = mem
                return _CursorAdapter([])
            if q.startswith("SET LOCAL search_path TO "):
                target = q.split("SET LOCAL search_path TO ", 1)[1].split(",", 1)[0].strip().strip('"')
                self.active_schema = target
                return _CursorAdapter([])
            if "information_schema.tables" in q:
                t_schema = norm_params[0]
                mem = state.schemas.get(t_schema)
                has_cases = bool(
                    mem and mem.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cases'").fetchone()
                )
                return _CursorAdapter([{"exists": 1}] if has_cases else [])
            if ".retailops_schema" in q:
                prefix = q.split("FROM ", 1)[1].split(".retailops_schema", 1)[0].strip().strip('"')
                if prefix == IDENTITY_SCHEMA:
                    return _CursorAdapter([{"component": "identity", "version": state.identity_version}])
                mem = state.schemas[prefix]
                rows = [dict(r) for r in mem.execute("SELECT component, version FROM retailops_schema").fetchall()]
                return _CursorAdapter(rows)
            if self.active_schema == IDENTITY_SCHEMA:
                if "SELECT version FROM retailops_schema" in q:
                    return _CursorAdapter([{"version": state.identity_version}])
                if "FROM tenants" in q:
                    return _CursorAdapter(list(state.tenants))
                return _CursorAdapter([])
            mem = state.schemas[self.active_schema]
            return _CursorAdapter(_exec_pg_ddl_on_sqlite(mem, str(query), norm_params))

    return state, _MockPgConn


class PhaseR1W3BusinessV6SchemaAndMigrationTests(unittest.TestCase):
    """Items 1 & 2: Business v6 schema, DB invariants, fail-closed v5 guard, and controlled migrate-v6."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_item1_sqlite_fresh_v6_schema_partial_unique_append_only_and_no_cascade_cleanup(self):
        # W3.2 moved the current version on to Business v7 (SQLite 6, PostgreSQL 7); the W3 milestone is fixed history.
        self.assertEqual(SQLITE_BUSINESS_SCHEMA_CURRENT, 6)
        self.assertEqual(POSTGRES_BUSINESS_SCHEMA_CURRENT, 7)
        self.assertEqual(BUSINESS_SCHEMA_CURRENT, 7)
        self.assertEqual(
            BUSINESS_V5_VERSION_MAPPING,
            {"logical_milestone": "business_v5", "sqlite": 4, "postgresql": 5},
        )
        self.assertEqual(
            BUSINESS_V6_VERSION_MAPPING,
            {"logical_milestone": "business_v6", "sqlite": 5, "postgresql": 6},
        )

        db_path = self.root / "fresh_v6.sqlite3"
        store = BusinessStore(db_path)
        store.seed()
        now = time.time()

        with store.connection(write=True) as db:
            ver_row = db.execute("SELECT component, version FROM retailops_schema").fetchone()
            self.assertEqual((ver_row["component"], ver_row["version"]), ("business", 6))
            order_cols = {r["name"] for r in db.execute("PRAGMA table_info(orders)").fetchall()}
            self.assertIn("delivered_at", order_cols)

            # Seeded existing orders leave delivered_at NULL
            seeded_delivered = db.execute("SELECT delivered_at FROM orders WHERE id='O-102'").fetchone()
            self.assertIsNotNone(seeded_delivered)
            self.assertIsNone(seeded_delivered["delivered_at"])

            # Insert conversation + case + open request
            db.execute(
                "INSERT INTO conversations(id, customer_id, order_id, expires_at, provider_id) "
                "VALUES ('conv-exp-w3', 'C-001', 'O-101', ?, 'custom')",
                (now - 120,),
            )
            db.execute(
                "INSERT INTO cases(case_id, conversation_id, customer_id, status, version, resume_count, created_at, updated_at) "
                "VALUES ('case_w3_1', 'conv-exp-w3', 'C-001', 'waiting', 1, 0, ?, ?)",
                (now - 200, now - 100),
            )
            db.execute(
                """INSERT INTO order_action_requests(
                    request_id, order_id, customer_id, case_id, conversation_id,
                    type, exchange_kind, status, refund_status, reason_code, reason_text,
                    raised_by_role, expected_order_version, version, created_at, updated_at, closed_at
                ) VALUES (
                    'oar_1', 'O-101', 'C-001', 'case_w3_1', 'conv-exp-w3',
                    'cancel', NULL, 'requested', 'not_applicable', 'changed_mind', 'Đổi ý mua mẫu khác',
                    'customer', 1, 1, ?, ?, NULL
                )""",
                (now - 90, now - 90),
            )

            # Second open request on the same order MUST fail at DB layer (idx_order_action_one_open_per_order)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    """INSERT INTO order_action_requests(
                        request_id, order_id, customer_id, case_id, conversation_id,
                        type, exchange_kind, status, refund_status, reason_code,
                        raised_by_role, expected_order_version, version, created_at, updated_at, closed_at
                    ) VALUES (
                        'oar_2', 'O-101', 'C-001', 'case_w3_1', 'conv-exp-w3',
                        'cancel', NULL, 'under_review', 'not_applicable', 'changed_mind',
                        'customer', 1, 1, ?, ?, NULL
                    )""",
                    (now - 80, now - 80),
                )

            # Insert decision, evidence metadata, and outbox row linked to conv-exp-w3
            db.execute(
                """INSERT INTO order_action_decisions(
                    decision_id, request_id, case_id, order_id, conversation_id,
                    action, from_status, to_status, actor_principal_id, actor_role, note, created_at
                ) VALUES (
                    'dec_1', 'oar_1', 'case_w3_1', 'O-101', 'conv-exp-w3',
                    'submit', NULL, 'requested', 'p-cust-1', 'customer', 'Khách gửi yêu cầu hủy', ?
                )""",
                (now - 90,),
            )
            # order_action_decisions MUST be append-only (UPDATE and DELETE blocked at DB layer)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE order_action_decisions SET note='tampered' WHERE decision_id='dec_1'")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM order_action_decisions WHERE decision_id='dec_1'")

            db.execute(
                """INSERT INTO order_action_evidence(
                    evidence_id, request_id, case_id, customer_id, conversation_id,
                    uploaded_by_principal_id, uploaded_by_role, mime_type, byte_size,
                    width, height, sha256, storage_relpath, created_at
                ) VALUES (
                    'ev_1', 'oar_1', 'case_w3_1', 'C-001', 'conv-exp-w3',
                    'p-cust-1', 'customer', 'image/png', 1024,
                    64, 64, ?, 'shop-a/ev_1', ?
                )""",
                ("a" * 64, now - 85),
            )
            db.execute(
                """INSERT INTO integration_outbox(
                    event_id, tenant_id, event_type, payload_json, created_at, status, attempts, next_attempt_at
                ) VALUES (
                    'evt_1', 'shop-a', 'cancel_requested', '{"schema":"retailops.order_action"}', ?, 'pending', 0, ?
                )""",
                (now - 90, now - 90),
            )

            # Delete expired conversation: MUST NOT cascade-delete requests, decisions, evidence, or outbox
            db.execute("DELETE FROM conversations WHERE expires_at < ?", (now,))

            self.assertIsNone(db.execute("SELECT 1 FROM conversations WHERE id='conv-exp-w3'").fetchone())
            self.assertEqual(db.execute("SELECT COUNT(*) FROM order_action_requests WHERE request_id='oar_1'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM order_action_decisions WHERE decision_id='dec_1'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM order_action_evidence WHERE evidence_id='ev_1'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM integration_outbox WHERE event_id='evt_1'").fetchone()[0], 1)

            # Once oar_1 is closed (rejected), a subsequent open request on O-101 is permitted by the partial index
            db.execute(
                "UPDATE order_action_requests SET status='rejected', closed_at=?, updated_at=?, version=2 WHERE request_id='oar_1'",
                (now - 50, now - 50),
            )
            db.execute(
                """INSERT INTO order_action_requests(
                    request_id, order_id, customer_id, case_id, conversation_id,
                    type, exchange_kind, status, refund_status, reason_code,
                    raised_by_role, expected_order_version, version, created_at, updated_at, closed_at
                ) VALUES (
                    'oar_after_close', 'O-101', 'C-001', 'case_w3_1', 'conv-exp-w3',
                    'cancel', NULL, 'requested', 'not_applicable', 'found_cheaper',
                    'customer', 1, 1, ?, ?, NULL
                )""",
                (now - 40, now - 40),
            )

    def test_item2_sqlite_v5_fixture_fail_closed_and_controlled_migrate_v6_idempotent(self):
        ws = self.root / "ws"
        pers = ws / "persistent"
        pers.mkdir(parents=True, exist_ok=True)

        id_store = IdentityStore(pers / "identity.sqlite3")
        t1 = id_store.ensure_tenant("shop-a", "Cửa hàng A")
        t2 = id_store.ensure_tenant("shop-b", "Cửa hàng B")
        t1_path = pers / "tenants" / f"{t1['storage_key']}.sqlite3"
        t2_path = pers / "tenants" / f"{t2['storage_key']}.sqlite3"
        _create_sqlite_v5_tenant_db(t1_path)
        _create_sqlite_v5_tenant_db(t2_path)

        def _file_sha(p: Path) -> str:
            return hashlib.sha256(p.read_bytes()).hexdigest()

        sha1_before = _file_sha(t1_path)
        sha2_before = _file_sha(t2_path)

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command", required=True)
        database_cli.add_parser(sub)

        with patch.dict(os.environ, {"RETAILOPS_STORAGE_BACKEND": "sqlite"}, clear=False):
            # 1. Startup, store init, inspection, and CLI check MUST fail closed with 503 and ZERO writes
            for blocked_call in (
                lambda: _inspect_sqlite_business_ready(t1_path),
                lambda: BusinessStore(t1_path, create=False),
                lambda: PersistentSessions(pers),
                lambda: database_cli.run(parser.parse_args(["database", "--output", str(ws), "check"])),
            ):
                with self.assertRaises(ApiError) as err:
                    blocked_call()
                self.assertEqual((err.exception.status, err.exception.code), (503, "business_migration_required"))

            self.assertEqual(_file_sha(t1_path), sha1_before)
            self.assertEqual(_file_sha(t2_path), sha2_before)

            # Missing confirmation flags -> 400
            with self.assertRaises(ApiError) as unconf:
                database_cli.run(
                    parser.parse_args(["database", "--output", str(ws), "migrate-v6", "--confirm-preflight"])
                )
            self.assertEqual((unconf.exception.status, unconf.exception.code), (400, "migration_confirmation_required"))
            self.assertEqual(_file_sha(t1_path), sha1_before)

            # 2. Controlled migrate-v6 upgrades ALL tenants to SQLite v5 (logical Business v6, the W3 milestone)
            mig1 = database_cli.run(
                parser.parse_args(
                    ["database", "--output", str(ws), "migrate-v6", "--confirm-preflight", "--confirm-backup"]
                )
            )
            self.assertEqual(
                mig1,
                {
                    "result": "BUSINESS_V6_MIGRATED",
                    "backend": "sqlite",
                    "schema_version": 5,
                    "logical_version": 6,
                    "tenants": 2,
                    "upgraded": True,
                },
            )

            # 3. Re-running migrate-v6 is idempotent
            mig2 = migrate_sqlite_business_v6(ws, preflight_confirmed=True, backup_confirmed=True)
            self.assertEqual(mig2["upgraded"], False)
            self.assertEqual(mig2["tenants"], 2)

            # 4. Since W3.2 the W3 milestone is no longer current: startup and check stay blocked until migrate-v7
            with self.assertRaises(ApiError) as still_blocked:
                database_cli.run(parser.parse_args(["database", "--output", str(ws), "check"]))
            self.assertEqual((still_blocked.exception.status, still_blocked.exception.code),
                             (503, "business_migration_required"))
            mig3 = database_cli.run(
                parser.parse_args(
                    ["database", "--output", str(ws), "migrate-v7", "--confirm-preflight", "--confirm-backup"]
                )
            )
            self.assertEqual(
                mig3,
                {
                    "result": "BUSINESS_V7_MIGRATED",
                    "backend": "sqlite",
                    "schema_version": 6,
                    "logical_version": 7,
                    "tenants": 2,
                    "upgraded": True,
                    "order_action_requests": 0,
                    "exchange_requests_mapped": 0,
                },
            )

            chk = database_cli.run(parser.parse_args(["database", "--output", str(ws), "check"]))
            self.assertEqual(chk, {"result": "SQLITE_SCHEMA_READY", "tenants_checked": 2})

        # Verify W3-D6 (old delivered order delivered_at stays NULL) and W3-D9 (pending proposals NOT backfilled)
        sessions = PersistentSessions(pers)
        b1 = sessions.business_store("shop-a")
        with b1.connection() as db:
            o102 = db.execute("SELECT status, delivered_at FROM orders WHERE id='O-102'").fetchone()
            self.assertEqual(o102["status"], "delivered")
            self.assertIsNone(o102["delivered_at"])
            prop_cnt = db.execute("SELECT COUNT(*) FROM proposals WHERE state='pending'").fetchone()[0]
            self.assertEqual(prop_cnt, 1)
            oar_cnt = db.execute("SELECT COUNT(*) FROM order_action_requests").fetchone()[0]
            self.assertEqual(oar_cnt, 0)

    def test_item1_and_item2_postgres_mock_fresh_v6_fail_closed_v5_and_controlled_migrate_v6(self):
        pg_dsn = "postgresql://retailops:secret@127.0.0.1:5432/retailops"
        key_a = "a" * 32
        key_b = "b" * 32
        schema_a = tenant_schema(key_a)
        schema_b = tenant_schema(key_b)
        state, mock_conn_cls = _build_mock_pg_harness([key_a, key_b])

        mock_psycopg = MagicMock()
        mock_psycopg.conninfo.conninfo_to_dict.return_value = {"dbname": "retailops", "user": "retailops"}
        mock_sql = MagicMock()
        mock_sql.SQL = lambda s: SimpleNamespace(format=lambda *a: s.format(*a))
        mock_sql.Identifier = lambda s: s
        mock_psycopg.sql = mock_sql

        @contextmanager
        def _fake_tx(dsn, schema=IDENTITY_SCHEMA, *, write=False, read_only=False):
            yield mock_conn_cls(schema)

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command", required=True)
        database_cli.add_parser(sub)

        with patch.dict("sys.modules", {"psycopg": mock_psycopg, "psycopg.sql": mock_sql}), \
             patch("retailops.storage.pg_repositories.transaction", side_effect=_fake_tx), \
             patch("retailops.storage.postgres.transaction", side_effect=_fake_tx), \
             patch("retailops.identity.postgres.transaction", side_effect=_fake_tx), \
             patch("retailops.storage.cli.os.environ", {"RETAILOPS_STORAGE_BACKEND": "postgresql", "RETAILOPS_DATABASE_URL": pg_dsn}), \
             patch.dict(os.environ, {"RETAILOPS_STORAGE_BACKEND": "postgresql", "RETAILOPS_DATABASE_URL": pg_dsn}, clear=False):

            # 1. PG v5 schemas fail-closed on startup, store construction, pg_initialize, and CLI check/migrate
            for pg_blocked in (
                lambda: pg_initialize(mock_conn_cls(schema_a), schema_a, "business"),
                lambda: PostgresBusinessStore(pg_dsn, key_a, create=False),
                lambda: PostgresSessions(pg_dsn),
                lambda: database_cli.run(parser.parse_args(["database", "check"])),
                lambda: database_cli.run(parser.parse_args(["database", "migrate"])),
            ):
                with self.assertRaises(ApiError) as err:
                    pg_blocked()
                self.assertEqual((err.exception.status, err.exception.code), (503, "business_migration_required"))

            for sc in (schema_a, schema_b):
                self.assertEqual(state.schemas[sc].execute("SELECT version FROM retailops_schema").fetchone()[0], 5)
                self.assertIsNone(
                    state.schemas[sc].execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='order_action_requests'"
                    ).fetchone()
                )

            with self.assertRaises(ApiError) as unconf:
                database_cli.run(parser.parse_args(["database", "migrate-v6", "--confirm-backup"]))
            self.assertEqual((unconf.exception.status, unconf.exception.code), (400, "migration_confirmation_required"))

            # 2. Controlled migrate-v6 upgrades all PG tenants from v5 -> v6; idempotent on re-run
            mig1 = database_cli.run(
                parser.parse_args(["database", "migrate-v6", "--confirm-preflight", "--confirm-backup"])
            )
            self.assertEqual(
                mig1,
                {
                    "result": "BUSINESS_V6_MIGRATED",
                    "backend": "postgresql",
                    "schema_version": 6,
                    "logical_version": 6,
                    "tenants": 2,
                    "upgraded": True,
                },
            )
            mig2 = migrate_postgres_business_v6(pg_dsn, preflight_confirmed=True, backup_confirmed=True)
            self.assertEqual(mig2["upgraded"], False)

            # Since W3.2 the W3 milestone is no longer current: the store and check stay blocked until migrate-v7
            for pg_blocked in (
                lambda: database_cli.run(parser.parse_args(["database", "check"])),
                lambda: PostgresBusinessStore(pg_dsn, key_a, create=False),
            ):
                with self.assertRaises(ApiError) as still_blocked:
                    pg_blocked()
                self.assertEqual((still_blocked.exception.status, still_blocked.exception.code),
                                 (503, "business_migration_required"))
            for sc in (schema_a, schema_b):
                self.assertEqual(state.schemas[sc].execute("SELECT version FROM retailops_schema").fetchone()[0], 6)

            mig3 = database_cli.run(
                parser.parse_args(["database", "migrate-v7", "--confirm-preflight", "--confirm-backup"])
            )
            self.assertEqual(
                mig3,
                {
                    "result": "BUSINESS_V7_MIGRATED",
                    "backend": "postgresql",
                    "schema_version": 7,
                    "logical_version": 7,
                    "tenants": 2,
                    "upgraded": True,
                    "order_action_requests": 0,
                    "exchange_requests_mapped": 0,
                },
            )
            mig4 = migrate_postgres_business_v7(pg_dsn, preflight_confirmed=True, backup_confirmed=True)
            self.assertEqual(mig4["upgraded"], False)

            chk = database_cli.run(parser.parse_args(["database", "check"]))
            self.assertEqual(chk["result"], "POSTGRES_SCHEMA_READY")

            for sc in (schema_a, schema_b):
                mem = state.schemas[sc]
                self.assertEqual(mem.execute("SELECT version FROM retailops_schema").fetchone()[0], 7)
                o102 = mem.execute("SELECT delivered_at FROM orders WHERE id='O-102'").fetchone()
                self.assertIsNone(o102["delivered_at"])
                # Pending proposal NOT backfilled (W3-D9)
                self.assertEqual(mem.execute("SELECT COUNT(*) FROM proposals").fetchone()[0], 1)
                self.assertEqual(mem.execute("SELECT COUNT(*) FROM order_action_requests").fetchone()[0], 0)

            # 3. Fresh PostgreSQL tenant schema initializes directly to v7 and enforces partial unique + append-only
            key_c = "c" * 32
            PostgresBusinessStore(pg_dsn, key_c, create=True)
            schema_c = tenant_schema(key_c)
            mem_c = state.schemas[schema_c]
            self.assertEqual(mem_c.execute("SELECT version FROM retailops_schema").fetchone()[0], 7)
            mem_c.execute("INSERT INTO customers VALUES ('C-900', 'Khách C')")
            mem_c.execute(
                "INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version) "
                "VALUES ('O-900', 'C-900', 'P-101', 'Áo C', 'Đen / M', 290000, 'pending', 1)"
            )
            mem_c.execute(
                "INSERT INTO cases(case_id, conversation_id, customer_id, status, version, resume_count, created_at, updated_at) "
                "VALUES ('case_pg_c', 'conv_pg_c', 'C-900', 'waiting', 1, 0, 100.0, 100.0)"
            )
            mem_c.execute(
                """INSERT INTO order_action_requests(
                    request_id, order_id, customer_id, case_id, conversation_id,
                    type, exchange_kind, status, refund_status, reason_code,
                    raised_by_role, expected_order_version, version, created_at, updated_at, closed_at
                ) VALUES (
                    'oar_pg_1', 'O-900', 'C-900', 'case_pg_c', 'conv_pg_c',
                    'cancel', NULL, 'requested', 'not_applicable', 'changed_mind',
                    'customer', 1, 1, 100.0, 100.0, NULL
                )"""
            )
            with self.assertRaises(sqlite3.IntegrityError):
                mem_c.execute(
                    """INSERT INTO order_action_requests(
                        request_id, order_id, customer_id, case_id, conversation_id,
                        type, exchange_kind, status, refund_status, reason_code,
                        raised_by_role, expected_order_version, version, created_at, updated_at, closed_at
                    ) VALUES (
                        'oar_pg_2', 'O-900', 'C-900', 'case_pg_c', 'conv_pg_c',
                        'cancel', NULL, 'requested', 'not_applicable', 'changed_mind',
                        'customer', 1, 1, 101.0, 101.0, NULL
                    )"""
                )
            mem_c.execute(
                """INSERT INTO order_action_decisions(
                    decision_id, request_id, case_id, order_id, conversation_id,
                    action, from_status, to_status, actor_principal_id, actor_role, created_at
                ) VALUES (
                    'dec_pg_1', 'oar_pg_1', 'case_pg_c', 'O-900', 'conv_pg_c',
                    'submit', NULL, 'requested', 'p-c900', 'customer', 100.0
                )"""
            )
            with self.assertRaises(sqlite3.IntegrityError):
                mem_c.execute("UPDATE order_action_decisions SET action='tamper' WHERE decision_id='dec_pg_1'")


class PhaseR1W3OrderActionCreationAndFacadeTests(unittest.TestCase):
    """Items 3 & 4: Unified order-action creation service and /api/cancellation-proposals* compatibility facade."""

    ORIGIN = "https://retailops.example.com"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pers = self.root / "persistent"
        self.sessions = PersistentSessions(self.pers, data_mode="persistent-demo")
        self.store_a = self.sessions.provision_tenant("shop-a", "Shop A", seed_demo=True)
        self.store_b = self.sessions.provision_tenant("shop-b", "Shop B", seed_demo=True)
        with self.store_a.connection(write=True) as db:
            db.execute(
                "INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version) "
                "VALUES ('O-103', 'C-001', 'P-102', 'Áo khoác Everyday', 'Xanh navy / L', 599000, 'delivered', 1)"
            )
            db.execute(
                "INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version) "
                "VALUES ('O-104', 'C-001', 'P-101', 'Áo thun Essential', 'Trắng / S', 299000, 'pending', 1)"
            )
        self.store_a.add_customer("C-STAFF-A", "Nhân viên A")
        self.store_a.add_customer("C-MGR-A", "Quản lý A")
        self.store_b.add_customer("C-STAFF-B", "Nhân viên B")
        self.web = PublicWeb(self.ORIGIN, self.sessions)
        self.cust1 = self._issue_cookie("shop-a", "p-cust-1", "Khách 1", "C-001", "customer")
        self.cust2 = self._issue_cookie("shop-a", "p-cust-2", "Khách 2", "C-002", "customer")
        self.staff_a = self._issue_cookie("shop-a", "p-staff-a", "Nhân viên A", "C-STAFF-A", "staff")
        self.mgr_a = self._issue_cookie("shop-a", "p-mgr-a", "Quản lý A", "C-MGR-A", "manager")
        self.staff_b = self._issue_cookie("shop-b", "p-staff-b", "Nhân viên B", "C-STAFF-B", "staff")

    def _issue_cookie(self, tenant_id: str, principal_id: str, name: str, customer_id: str, role: str) -> str:
        mid = self.sessions.create_member(tenant_id, principal_id, name, customer_id, role)
        tok = secrets.token_urlsafe(32)
        self.sessions.control.register_credential(mid, tok)
        secret = self.sessions.login(tok)
        return f"{self.sessions.cookie_name}={secret}"

    def _req(self, method: str, path: str, body: dict | None = None, *, cookie: str | None = None, headers: dict | None = None):
        raw = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        env = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "HTTP_HOST": "retailops.example.com",
            "wsgi.input": io.BytesIO(raw),
        }
        if method != "GET":
            env["HTTP_ORIGIN"] = self.ORIGIN
        if body is not None:
            env["CONTENT_TYPE"] = "application/json"
            env["CONTENT_LENGTH"] = str(len(raw))
        if cookie:
            env["HTTP_COOKIE"] = cookie
        for k, v in (headers or {}).items():
            env["HTTP_" + k.upper().replace("-", "_")] = v
        try:
            status, payload, _, _ = self.web.route(env)
            return status, payload
        except ApiError as err:
            return err.status, {"error": err.code, "message": err.message}

    def test_item3_atomic_rollback_on_mid_tx_failure_leaves_zero_rows(self):
        with patch.object(self.store_a, "_enqueue_outbox_in_tx", side_effect=RuntimeError("simulated_outbox_crash")):
            with self.assertRaises(RuntimeError):
                self.store_a.create_order_action_request(
                    "C-001",
                    {
                        "order_id": "O-101",
                        "type": "cancel",
                        "expected_order_version": 1,
                        "reason_code": "ordered_by_mistake",
                    },
                    actor={"principal_id": "p-cust-1", "role": "customer", "tenant_id": "shop-a"},
                )

        with self.store_a.connection() as db:
            for tbl in (
                "order_action_requests",
                "order_action_decisions",
                "handoff_episodes",
                "integration_outbox",
            ):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0], 0, tbl)
            ev_cnt = db.execute(
                "SELECT COUNT(*) FROM business_events WHERE kind IN ('order_action_requested', 'human_escalation_requested')"
            ).fetchone()[0]
            self.assertEqual(ev_cnt, 0)

    def test_item3_eligibility_version_customer_isolation_and_waiting_queue(self):
        # 1. Wrong order status & wrong version & missing reason/exchange_kind rejected
        st, body = self._req(
            "POST",
            "/api/order-actions",
            {"order_id": "O-102", "type": "cancel", "expected_order_version": 1, "reason_code": "changed_mind"},
            cookie=self.cust1,
        )
        self.assertEqual((st, body["error"]), (409, "not_cancellable"))

        for bad_type in ("return", "exchange"):
            payload = {"order_id": "O-101", "type": bad_type, "expected_order_version": 1, "reason_code": "defective_item"}
            if bad_type == "exchange":
                payload["exchange_kind"] = "same_variant"
            st, body = self._req("POST", "/api/order-actions", payload, cookie=self.cust1)
            self.assertEqual((st, body["error"]), (409, "order_not_eligible"))

        st, body = self._req(
            "POST",
            "/api/order-actions",
            {"order_id": "O-101", "type": "cancel", "expected_order_version": 99, "reason_code": "changed_mind"},
            cookie=self.cust1,
        )
        self.assertEqual((st, body["error"]), (409, "stale_order"))

        st, body = self._req(
            "POST",
            "/api/order-actions",
            {"order_id": "O-102", "type": "exchange", "expected_order_version": 1, "reason_code": "wrong_size"},
            cookie=self.cust1,
        )
        self.assertEqual((st, body["error"]), (400, "invalid_exchange_kind"))

        # Foreign order rejected with 404
        st, body = self._req(
            "POST",
            "/api/order-actions",
            {"order_id": "O-202", "type": "cancel", "expected_order_version": 1, "reason_code": "changed_mind"},
            cookie=self.cust1,
        )
        self.assertEqual((st, body["error"]), (404, "order_not_found"))

        # 2. Valid cancel (pending O-101), return (delivered O-102), exchange (delivered O-103), and C-002 cancel (O-202)
        st1, c_res = self._req(
            "POST",
            "/api/order-actions",
            {"order_id": "O-101", "type": "cancel", "expected_order_version": 1, "reason_code": "ordered_by_mistake"},
            cookie=self.cust1,
        )
        self.assertEqual(st1, 201)
        self.assertEqual(c_res["status"], "requested")

        st2, r_res = self._req(
            "POST",
            "/api/order-actions",
            {"order_id": "O-102", "type": "return", "expected_order_version": 1, "reason_code": "defective_item"},
            cookie=self.cust1,
        )
        self.assertEqual(st2, 201)
        self.assertEqual(r_res["order_action"]["delivery_age_label"], "chưa có ngày giao")

        st3, x_res = self._req(
            "POST",
            "/api/order-actions",
            {
                "order_id": "O-103",
                "type": "exchange",
                "exchange_kind": "same_variant",
                "expected_order_version": 1,
                "reason_code": "defective_item",
            },
            cookie=self.cust1,
        )
        self.assertEqual(st3, 201)
        self.assertEqual(x_res["order_action"]["exchange_kind"], "same_variant")
        self.assertIsNone(x_res["order_action"]["target_variant_id"])

        st4, c2_res = self._req(
            "POST",
            "/api/order-actions",
            {"order_id": "O-202", "type": "cancel", "expected_order_version": 1, "reason_code": "no_longer_needed"},
            cookie=self.cust2,
        )
        self.assertEqual(st4, 201)

        # 3. Customer isolation on GET /api/order-actions
        _, l1 = self._req("GET", "/api/order-actions", cookie=self.cust1)
        _, l2 = self._req("GET", "/api/order-actions", cookie=self.cust2)
        self.assertEqual({x["order_id"] for x in l1["order_actions"]}, {"O-101", "O-102", "O-103"})
        self.assertEqual([x["order_id"] for x in l2["order_actions"]], ["O-202"])

        # 4. Staff Desk waiting queue contains created cases with reason_code='order_action_review'
        st_q, desk = self._req("GET", "/api/staff/escalations", cookie=self.staff_a)
        self.assertEqual(st_q, 200)
        waiting_cases = {row["case_id"]: row for row in desk["waiting"]}
        self.assertIn(c_res["case_id"], waiting_cases)
        self.assertEqual(waiting_cases[c_res["case_id"]]["reason_code"], "order_action_review")

        # 5. GET /api/staff/cases/<case_id>/order-actions: allowed to same-tenant Staff/Manager, denied to customer & cross-tenant Staff
        case_id = c_res["case_id"]
        st_cust, _ = self._req("GET", f"/api/staff/cases/{case_id}/order-actions", cookie=self.cust1)
        self.assertEqual(st_cust, 403)
        st_xb, _ = self._req("GET", f"/api/staff/cases/{case_id}/order-actions", cookie=self.staff_b)
        self.assertIn(st_xb, (403, 404))
        st_sa, sa_body = self._req("GET", f"/api/staff/cases/{case_id}/order-actions", cookie=self.staff_a)
        self.assertEqual(st_sa, 200)
        self.assertTrue(any(x["request_id"] == c_res["order_action_request_id"] for x in sa_body["order_actions"]))

        # Verify submit decision + outbox event types recorded
        with self.store_a.connection() as db:
            outbox_types = [r["event_type"] for r in db.execute("SELECT event_type FROM integration_outbox").fetchall()]
            self.assertIn("cancel_requested", outbox_types)
            self.assertIn("return_requested", outbox_types)
            self.assertIn("exchange_requested", outbox_types)

    def test_item4_cancellation_proposals_facade_creates_requested_action_replays_once_and_keeps_order_pending(self):
        # 1. Create proposal: order stays pending, no order_action_requests yet
        st_p, prop = self._req(
            "POST",
            "/api/cancellation-proposals",
            {"order_id": "O-101", "order_version": 1, "cancel_reason": "ordered_by_mistake"},
            cookie=self.cust1,
        )
        self.assertEqual(st_p, 201)
        pid = prop["proposal_id"]
        self.assertEqual(self.store_a.list_customer_order_actions("C-001"), [])

        # 2. Confirm twice with same Idempotency-Key -> replayed: True, 1 request, order still pending
        idem = "idem_w3_item4_facade_0001"
        st_c1, conf1 = self._req(
            "POST",
            f"/api/cancellation-proposals/{pid}/confirm",
            {"confirmed": True},
            cookie=self.cust1,
            headers={"Idempotency-Key": idem},
        )
        st_c2, conf2 = self._req(
            "POST",
            f"/api/cancellation-proposals/{pid}/confirm",
            {"confirmed": True},
            cookie=self.cust1,
            headers={"Idempotency-Key": idem},
        )
        self.assertEqual((st_c1, st_c2), (200, 200))
        self.assertFalse(conf1["replayed"])
        self.assertTrue(conf2["replayed"])
        self.assertEqual(conf1["status"], "requested")
        self.assertEqual(conf1["message"], "Đã gửi yêu cầu hủy, chờ cửa hàng duyệt")
        self.assertEqual(conf1["order_action_request_id"], conf2["order_action_request_id"])
        self.assertEqual(conf1["order"]["status"], "pending")
        self.assertEqual(conf1["order"]["version"], 1)

        actions = self.store_a.list_customer_order_actions("C-001")
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["request_id"], conf1["order_action_request_id"])
        self.assertEqual(self.store_a.lookup("C-001", "O-101")["status"], "pending")

        # 3. Dismiss on a separate pending order keeps proposals dismiss unchanged
        st_p2, prop2 = self._req(
            "POST",
            "/api/cancellation-proposals",
            {"order_id": "O-104", "order_version": 1, "cancel_reason": "no_longer_needed"},
            cookie=self.cust1,
        )
        self.assertEqual(st_p2, 201)
        st_d, dis = self._req(
            "POST",
            f"/api/cancellation-proposals/{prop2['proposal_id']}/dismiss",
            {},
            cookie=self.cust1,
        )
        self.assertEqual(st_d, 200)
        self.assertIn("Đã bỏ đề xuất", dis["message"])
        self.assertEqual(len(self.store_a.list_customer_order_actions("C-001")), 1)


class PhaseR1W3ReviewLifecycleDeliveryFailureRefundAndManagerStatusTests(unittest.TestCase):
    """Items 5, 6, 7 & 8: Review/post-review transitions, delivery-failure cancel, manual refund, and Manager order status."""

    ORIGIN = "https://retailops.example.com"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pers = self.root / "persistent"
        self.sessions = PersistentSessions(self.pers, data_mode="persistent-demo")
        self.store_a = self.sessions.provision_tenant("shop-a", "Shop A", seed_demo=True)
        for cid, cname in (
            ("C-STAFF-1", "Nhân viên 1"),
            ("C-STAFF-2", "Nhân viên 2"),
            ("C-MGR-1", "Quản lý 1"),
            ("C-MGR-2", "Quản lý 2"),
        ):
            self.store_a.add_customer(cid, cname)
        with self.store_a.connection(write=True) as db:
            db.execute(
                "INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version) "
                "VALUES ('O-105', 'C-001', 'P-101', 'Áo thun Essential', 'Đen / L', 299000, 'pending', 1)"
            )
            db.execute(
                "INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version) "
                "VALUES ('O-106', 'C-001', 'P-102', 'Áo khoác Everyday', 'Xám / M', 599000, 'delivered', 1)"
            )
        self.web = PublicWeb(self.ORIGIN, self.sessions)
        self.cust1 = self._issue_cookie("shop-a", "p-cust-1", "Khách 1", "C-001", "customer")
        self.staff1 = self._issue_cookie("shop-a", "p-staff-1", "Nhân viên 1", "C-STAFF-1", "staff")
        self.staff2 = self._issue_cookie("shop-a", "p-staff-2", "Nhân viên 2", "C-STAFF-2", "staff")
        self.mgr1 = self._issue_cookie("shop-a", "p-mgr-1", "Quản lý 1", "C-MGR-1", "manager")
        self.mgr2 = self._issue_cookie("shop-a", "p-mgr-2", "Quản lý 2", "C-MGR-2", "manager")

    def _issue_cookie(self, tenant_id: str, principal_id: str, name: str, customer_id: str, role: str) -> str:
        mid = self.sessions.create_member(tenant_id, principal_id, name, customer_id, role)
        tok = secrets.token_urlsafe(32)
        self.sessions.control.register_credential(mid, tok)
        return f"{self.sessions.cookie_name}={self.sessions.login(tok)}"

    def _req(self, method: str, path: str, body: dict | None = None, *, cookie: str | None = None):
        raw = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        env = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "HTTP_HOST": "retailops.example.com",
            "wsgi.input": io.BytesIO(raw),
        }
        if method != "GET":
            env["HTTP_ORIGIN"] = self.ORIGIN
        if body is not None:
            env["CONTENT_TYPE"] = "application/json"
            env["CONTENT_LENGTH"] = str(len(raw))
        if cookie:
            env["HTTP_COOKIE"] = cookie
        try:
            status, payload, _, _ = self.web.route(env)
            return status, payload
        except ApiError as err:
            return err.status, {"error": err.code, "message": err.message}

    def _notice_turns(self, cid: str) -> list[dict]:
        st, trans = self._req("GET", f"/api/conversations/{cid}/messages", cookie=self.cust1)
        self.assertEqual(st, 200)
        notices = []
        for t in trans["turns"]:
            res = json.loads(t["result"]) if isinstance(t["result"], str) else t["result"]
            if res.get("author") == "system_order_action":
                notices.append(res)
        return notices

    def test_item5_cancel_and_return_lifecycle_holder_rules_concurrency_and_exact_customer_notices(self):
        # 1. Create cancel request on pending O-101
        st, created = self._req(
            "POST",
            "/api/order-actions",
            {"order_id": "O-101", "type": "cancel", "expected_order_version": 1, "reason_code": "changed_mind"},
            cookie=self.cust1,
        )
        self.assertEqual(st, 201)
        req_id = created["order_action_request_id"]
        case_id = created["case_id"]
        cid = created["conversation_id"]

        # Unclaimed case: Staff1 blocked (409 case_not_claimed)
        st_unclaimed, err_unclaimed = self._req(
            "POST",
            f"/api/order-actions/{req_id}/approve",
            {"version": 1},
            cookie=self.staff1,
        )
        self.assertEqual((st_unclaimed, err_unclaimed["error"]), (409, "case_not_claimed"))
        self.assertEqual(len(self._notice_turns(cid)), 0)

        # Claim case by Staff1 -> request transitions requested (v1) -> under_review (v2), 1 notice
        st_claim, _ = self._req("POST", f"/api/staff/cases/{case_id}/claim", {}, cookie=self.staff1)
        self.assertEqual(st_claim, 200)
        _, case_oas = self._req("GET", f"/api/staff/cases/{case_id}/order-actions", cookie=self.staff1)
        oar_after_claim = case_oas["order_actions"][0]
        self.assertEqual((oar_after_claim["status"], oar_after_claim["version"]), ("under_review", 2))
        self.assertEqual(len(self._notice_turns(cid)), 1)
        # System notice turns do NOT pollute has_turns / LLM history
        self.assertFalse(self.store_a.has_turns("C-001", cid))
        self.assertEqual(self.store_a.history("C-001", cid), [])

        # Staff2 (not holding case) blocked with 409 case_held_by_other
        st_other, err_other = self._req(
            "POST",
            f"/api/order-actions/{req_id}/approve",
            {"version": 2},
            cookie=self.staff2,
        )
        self.assertEqual((st_other, err_other["error"]), (409, "case_held_by_other"))

        # Invalid transition on cancel (mark-received not allowed) -> 409
        st_bad, err_bad = self._req(
            "POST",
            f"/api/order-actions/{req_id}/mark-received",
            {"version": 2},
            cookie=self.staff1,
        )
        self.assertEqual((st_bad, err_bad["error"]), (409, "invalid_order_action_transition"))

        # Concurrent approval race between Staff1 (holder) and Manager1 with same version=2 -> exactly 1 wins!
        def _race_approve(cookie):
            return self._req("POST", f"/api/order-actions/{req_id}/approve", {"version": 2, "note": "Đồng ý hủy"}, cookie=cookie)

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(_race_approve, [self.staff1, self.mgr1]))
        statuses = sorted(s for s, _ in outcomes)
        self.assertEqual(statuses, [200, 409])
        loser = [b for s, b in outcomes if s == 409][0]
        self.assertEqual(loser["error"], "order_action_version_conflict")

        # Order O-101 is now cancelled (version 2), closed_at set, and exactly 2 notices total (under_review + approved)
        ord_101 = self.store_a.lookup("C-001", "O-101")
        self.assertEqual((ord_101["status"], ord_101["version"]), ("cancelled", 2))
        self.assertEqual(len(self._notice_turns(cid)), 2)

        # 2. Full return/exchange lifecycle on delivered O-102 with out-of-order rejection + exact 1 notice per step
        st_r, r_created = self._req(
            "POST",
            "/api/order-actions",
            {
                "order_id": "O-102",
                "type": "exchange",
                "exchange_kind": "same_variant",
                "expected_order_version": 1,
                "reason_code": "wrong_size",  # a W3 code: still accepted as an alias of fit_issue
            },
            cookie=self.cust1,
        )
        self.assertEqual(st_r, 201)
        rid = r_created["order_action_request_id"]
        rcase = r_created["case_id"]
        rcid = r_created["conversation_id"]

        # Out-of-order mark-received before approve -> 409
        self.assertEqual(
            self._req("POST", f"/api/order-actions/{rid}/mark-received", {"version": 1}, cookie=self.mgr1)[0],
            409,
        )
        # Claim -> under_review (v2, notice #1)
        self.assertEqual(self._req("POST", f"/api/staff/cases/{rcase}/claim", {}, cookie=self.staff1)[0], 200)
        self.assertEqual(len(self._notice_turns(rcid)), 1)

        # Approve -> approved (v3, notice #2, closed_at still None)
        st_ap, ap_res = self._req("POST", f"/api/order-actions/{rid}/approve", {"version": 2}, cookie=self.staff1)
        self.assertEqual((st_ap, ap_res["status"]), (200, "approved"))
        self.assertIsNone(ap_res["order_action"]["closed_at"])
        self.assertEqual(len(self._notice_turns(rcid)), 2)

        # Out-of-order complete before mark-received/mark-inspected -> 409
        self.assertEqual(
            self._req("POST", f"/api/order-actions/{rid}/complete", {"version": 3}, cookie=self.staff1)[0],
            409,
        )

        # Mark-received -> received (v4, notice #3)
        st_rc, rc_res = self._req("POST", f"/api/order-actions/{rid}/mark-received", {"version": 3}, cookie=self.staff1)
        self.assertEqual((st_rc, rc_res["status"]), (200, "received"))
        self.assertEqual(len(self._notice_turns(rcid)), 3)

        # Mark-inspected without outcome -> 400; with outcome='exchange' -> inspected (v5, notice #4)
        self.assertEqual(
            self._req("POST", f"/api/order-actions/{rid}/mark-inspected", {"version": 4}, cookie=self.staff1)[0],
            400,
        )
        st_in, in_res = self._req(
            "POST",
            f"/api/order-actions/{rid}/mark-inspected",
            {"version": 4, "inspection_outcome": "exchange"},
            cookie=self.staff1,
        )
        self.assertEqual((st_in, in_res["status"], in_res["order_action"]["inspection_outcome"]), (200, "inspected", "exchange"))
        self.assertEqual(len(self._notice_turns(rcid)), 4)

        # Complete -> completed (v6, notice #5, closed_at set)
        st_cp, cp_res = self._req("POST", f"/api/order-actions/{rid}/complete", {"version": 5}, cookie=self.staff1)
        self.assertEqual((st_cp, cp_res["status"]), (200, "completed"))
        self.assertIsNotNone(cp_res["order_action"]["closed_at"])
        notices = self._notice_turns(rcid)
        self.assertEqual(
            [n["order_action_status"] for n in notices],
            ["under_review", "approved", "received", "inspected", "completed"],
        )

    def test_item6_delivery_failure_cancel_requires_attempts_and_manager_only_decision(self):
        conv = self.store_a.new_conversation("C-001")
        cid = conv["conversation_id"]
        handoff = self.store_a.request_human_handoff("C-001", cid, reason_code="shipping_issue", comment="Shipper gọi nhỡ")
        case_id = handoff["case_id"]

        # Unclaimed case -> 409 case_not_claimed
        st_unc, _ = self._req(
            "POST",
            f"/api/staff/cases/{case_id}/order-actions",
            {"order_id": "O-105", "delivery_failure_attempts": 3, "note": "Giao 3 lần không nghe máy"},
            cookie=self.staff1,
        )
        self.assertEqual(st_unc, 409)

        # Staff1 claims case
        self.assertEqual(self._req("POST", f"/api/staff/cases/{case_id}/claim", {}, cookie=self.staff1)[0], 200)

        # Missing or invalid delivery_failure_attempts -> 400
        for bad_body in (
            {"order_id": "O-105", "note": "Thiếu số lần giao"},
            {"order_id": "O-105", "delivery_failure_attempts": 0, "note": "Số lần = 0"},
            {"order_id": "O-105", "delivery_failure_attempts": 2},
        ):
            st_b, _ = self._req("POST", f"/api/staff/cases/{case_id}/order-actions", bad_body, cookie=self.staff1)
            self.assertEqual(st_b, 400, bad_body)

        # Valid delivery-failure cancel created by Staff1 holding case
        st_ok, created = self._req(
            "POST",
            f"/api/staff/cases/{case_id}/order-actions",
            {"order_id": "O-105", "delivery_failure_attempts": 3, "note": "Shipper báo khách hẹn lại 3 lần không nhận"},
            cookie=self.staff1,
        )
        self.assertEqual(st_ok, 201)
        req_id = created["order_action_request_id"]
        self.assertEqual(created["order_action"]["raised_by_role"], "staff")
        self.assertEqual(created["order_action"]["delivery_failure_attempts"], 3)

        # Staff1 (even though holding the case!) MUST get 403 on both approve and reject
        for act in ("approve", "reject"):
            st_s, body_s = self._req("POST", f"/api/order-actions/{req_id}/{act}", {"version": 1}, cookie=self.staff1)
            self.assertEqual((st_s, body_s["error"]), (403, "permission_denied"))

        # Manager1 approves -> 200, order O-105 becomes cancelled
        st_m, body_m = self._req(
            "POST",
            f"/api/order-actions/{req_id}/approve",
            {"version": 1, "note": "Quản lý xác nhận hủy đơn hoàn kho"},
            cookie=self.mgr1,
        )
        self.assertEqual(st_m, 200)
        self.assertEqual(body_m["order"]["status"], "cancelled")

    def test_item7_manual_refund_staff_requests_manager_decides_and_records_outcome(self):
        st, created = self._req(
            "POST",
            "/api/order-actions",
            {"order_id": "O-106", "type": "return", "expected_order_version": 1, "reason_code": "defective_item"},
            cookie=self.cust1,
        )
        self.assertEqual(st, 201)
        req_id = created["order_action_request_id"]
        case_id = created["case_id"]

        # Staff1 claims case (v1 -> v2 under_review)
        self.assertEqual(self._req("POST", f"/api/staff/cases/{case_id}/claim", {}, cookie=self.staff1)[0], 200)

        # Refund request BEFORE request is approved -> 409 invalid_refund_state
        self.assertEqual(
            self._req("POST", f"/api/order-actions/{req_id}/refund-request", {"version": 2}, cookie=self.staff1)[0],
            409,
        )

        # Staff1 approves return request (v2 -> v3 approved)
        self.assertEqual(self._req("POST", f"/api/order-actions/{req_id}/approve", {"version": 2}, cookie=self.staff1)[0], 200)

        # Staff1 submits refund request (v3 -> v4, refund_status='pending')
        st_rr, rr = self._req(
            "POST",
            f"/api/order-actions/{req_id}/refund-request",
            {"version": 3, "note": "Đề nghị hoàn 599.000đ qua chuyển khoản"},
            cookie=self.staff1,
        )
        self.assertEqual((st_rr, rr["refund_status"], rr["refund_decision"]), (200, "pending", None))

        # Staff1 CANNOT decide refund or record refund outcome -> 403
        self.assertEqual(
            self._req(
                "POST",
                f"/api/order-actions/{req_id}/refund-decision",
                {"version": 4, "decision": "approved"},
                cookie=self.staff1,
            )[0],
            403,
        )
        self.assertEqual(
            self._req(
                "POST",
                f"/api/order-actions/{req_id}/refund-outcome",
                {"version": 4, "outcome": "refunded"},
                cookie=self.staff1,
            )[0],
            403,
        )

        # Manager1 CANNOT record refund outcome BEFORE refund-decision approved -> 409 refund_not_approved
        st_early, err_early = self._req(
            "POST",
            f"/api/order-actions/{req_id}/refund-outcome",
            {"version": 4, "outcome": "refunded"},
            cookie=self.mgr1,
        )
        self.assertEqual((st_early, err_early["error"]), (409, "refund_not_approved"))

        # Manager1 approves refund (v4 -> v5, refund_decision='approved')
        st_dec, dec = self._req(
            "POST",
            f"/api/order-actions/{req_id}/refund-decision",
            {"version": 4, "decision": "approved", "note": "Duyệt chi hoàn tiền"},
            cookie=self.mgr1,
        )
        self.assertEqual((st_dec, dec["refund_status"], dec["refund_decision"]), (200, "pending", "approved"))

        # Manager1 records outcome refunded (v5 -> v6)
        st_out, out = self._req(
            "POST",
            f"/api/order-actions/{req_id}/refund-outcome",
            {"version": 5, "outcome": "refunded", "note": "Đã chuyển khoản hoàn tất"},
            cookie=self.mgr1,
        )
        self.assertEqual((st_out, out["refund_status"]), (200, "refunded"))

        # Verify audit events and outbox rows for every step
        with self.store_a.connection() as db:
            refund_evs = db.execute(
                "SELECT COUNT(*) FROM business_events WHERE kind='order_action_refund_updated'"
            ).fetchone()[0]
            self.assertEqual(refund_evs, 3)
            outbox_rows = [
                json.loads(r["payload_json"])
                for r in db.execute(
                    "SELECT payload_json FROM integration_outbox WHERE payload_json LIKE ? ORDER BY created_at ASC",
                    (f"%{req_id}%",),
                ).fetchall()
            ]
            event_types = [r["event_type"] for r in outbox_rows]
            self.assertIn("refund_requested", event_types)
            self.assertIn("refund_decided", event_types)
            self.assertTrue(
                any(r["event_type"] == "request_status_changed" and r.get("after", {}).get("refund_status") == "refunded" for r in outbox_rows)
            )

    def test_item8_manager_direct_order_status_version_check_delivered_at_and_outbox(self):
        # Wrong version -> 409 stale_order
        st_bad, err_bad = self._req(
            "POST",
            "/api/manager/orders/update-status",
            {"order_id": "O-101", "status": "delivered", "version": 9},
            cookie=self.mgr1,
        )
        self.assertEqual((st_bad, err_bad["error"]), (409, "stale_order"))

        # Correct version=1 -> 200, delivered_at populated, outbox order_status_changed written
        st_ok, ok_body = self._req(
            "POST",
            "/api/manager/orders/update-status",
            {"order_id": "O-101", "status": "delivered", "version": 1},
            cookie=self.mgr1,
        )
        self.assertEqual(st_ok, 200)
        self.assertEqual((ok_body["new_status"], ok_body["version"]), ("delivered", 2))
        self.assertIsNotNone(ok_body["delivered_at"])

        ord_after = self.store_a.lookup("C-001", "O-101")
        self.assertIsNotNone(ord_after["delivered_at"])

        # Creating a return request on O-101 now shows numeric days_since_delivery (0 ngày kể từ khi giao)
        st_ret, ret_body = self._req(
            "POST",
            "/api/order-actions",
            {"order_id": "O-101", "type": "return", "expected_order_version": 2, "reason_code": "wrong_item"},
            cookie=self.cust1,
        )
        self.assertEqual(st_ret, 201)
        self.assertEqual(ret_body["order_action"]["days_since_delivery"], 0)
        self.assertIn("0 ngày kể từ khi giao", ret_body["order_action"]["delivery_age_label"])

        with self.store_a.connection() as db:
            ob = [
                json.loads(r["payload_json"])
                for r in db.execute(
                    "SELECT payload_json FROM integration_outbox WHERE event_type='order_status_changed'"
                ).fetchall()
            ]
            self.assertEqual(len(ob), 1)
            self.assertEqual(ob[0]["order_id"], "O-101")
            self.assertEqual(ob[0]["before"], {"status": "pending", "version": 1})
            self.assertEqual(ob[0]["after"], {"status": "delivered", "version": 2})


class PhaseR1W3EvidenceStorageExifStripAuthAndPurgeTests(unittest.TestCase):
    """Item 9 isolated acceptance tests: JPEG/PNG/WebP magic bytes, EXIF/GPS strip, 5-image/10MB caps, auth, 90d purge."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "data"
        self.now = 1_785_000_000.0
        self.sessions = PersistentSessions(self.root / "persistent")
        self.sessions.store_clock = lambda: self.now

        # Tenant A (seed_demo already creates C-001 and C-002)
        self.store_a = self.sessions.provision_tenant("tenant-ev-a", "Store Evidence A", seed_demo=True)
        self.store_a.add_customer("C-STAFF1", "Staff Một")
        self.store_a.add_customer("C-MGR1", "Manager Một")
        with self.store_a.connection(write=True) as db:
            db.execute(
                "UPDATE orders SET status = 'delivered', delivered_at = ? WHERE id = 'O-202'",
                (self.now - 2 * 86400,),
            )
        # Tenant B (isolated tenant)
        self.store_b = self.sessions.provision_tenant("tenant-ev-b", "Store Evidence B", seed_demo=True)
        self.store_b.add_customer("C-MGRB", "Manager B")

        self.origin = "https://retailops.example.com"
        self.web = PublicWeb(self.origin, self.sessions, start_timer_worker=False)
        self.cust1 = self._issue_cookie("tenant-ev-a", "p-cust1-a", "Khách A", "C-001", "customer")
        self.cust2 = self._issue_cookie("tenant-ev-a", "p-cust2-a", "Khách B", "C-002", "customer")
        self.staff1 = self._issue_cookie("tenant-ev-a", "p-staff1-a", "Staff Một", "C-STAFF1", "staff")
        self.mgr1 = self._issue_cookie("tenant-ev-a", "p-mgr1-a", "Manager Một", "C-MGR1", "manager")
        self.cust_b = self._issue_cookie("tenant-ev-b", "p-cust1-b", "Khách Tenant B", "C-001", "customer")
        self.mgr_b = self._issue_cookie("tenant-ev-b", "p-mgr1-b", "Manager Tenant B", "C-MGRB", "manager")

    def _issue_cookie(self, tenant_id: str, principal_id: str, name: str, customer_id: str, role: str) -> str:
        mid = self.sessions.create_member(tenant_id, principal_id, name, customer_id, role)
        tok = secrets.token_urlsafe(32)
        self.sessions.control.register_credential(mid, tok)
        return f"{self.sessions.cookie_name}={self.sessions.login(tok)}"

    def _raw_call(self, method: str, path: str, payload: bytes = b"", *, content_type: str = "application/json", cookie: str = "", length_override: str | None = None):
        env = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "HTTP_HOST": "retailops.example.com",
            "HTTP_COOKIE": cookie,
            "QUERY_STRING": "",
            "wsgi.input": io.BytesIO(payload),
        }
        if method == "POST":
            env["HTTP_ORIGIN"] = self.origin
            env["CONTENT_TYPE"] = content_type
            env["CONTENT_LENGTH"] = length_override if length_override is not None else str(len(payload))
        captured: dict = {}

        def start_response(status, headers):
            captured["status"] = int(status.split()[0])
            captured["headers"] = dict(headers)

        raw_out = b"".join(self.web(env, start_response))
        return captured["status"], captured["headers"], raw_out

    def _json_req(self, method: str, path: str, body: dict | None = None, *, cookie: str):
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        st, hdrs, out = self._raw_call(method, path, raw, content_type="application/json", cookie=cookie)
        return st, json.loads(out.decode("utf-8"))

    @staticmethod
    def _make_jpeg_with_exif_and_gps() -> bytes:
        from PIL import Image

        img = Image.new("RGB", (48, 32), color=(210, 45, 70))
        exif = Image.Exif()
        exif[0x010E] = "Customer Private Home Photo"  # ImageDescription
        exif[0x013B] = "Nguyen Van Secret"  # Artist
        exif[0x0131] = "CameraOS 9.9"  # Software
        # GPS IFD (0x8825)
        exif[0x8825] = {
            1: "N",
            2: (10.0, 46.0, 36.0),
            3: "E",
            4: (106.0, 42.0, 3.0),
        }
        buf = io.BytesIO()
        img.save(buf, format="JPEG", exif=exif.tobytes())
        raw = buf.getvalue()
        # Sanity check: source bytes truly carry EXIF & GPS tags
        with Image.open(io.BytesIO(raw)) as verify_src:
            src_exif = verify_src.getexif()
            assert len(src_exif) >= 3
            assert len(src_exif.get_ifd(0x8825)) >= 2
        return raw

    @staticmethod
    def _make_png_with_text() -> bytes:
        from PIL import Image, PngImagePlugin

        img = Image.new("RGBA", (24, 24), color=(20, 120, 220, 255))
        meta = PngImagePlugin.PngInfo()
        meta.add_text("Author", "Private PII Author")
        meta.add_text("GPS", "10.7769,106.7009")
        buf = io.BytesIO()
        img.save(buf, format="PNG", pnginfo=meta)
        return buf.getvalue()

    @staticmethod
    def _make_webp() -> bytes:
        from PIL import Image

        img = Image.new("RGB", (30, 20), color=(40, 180, 90))
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=85)
        return buf.getvalue()

    def test_item9_exif_stripped_magic_bytes_limits_auth_and_90_day_purge(self):
        from PIL import Image

        # Create return request on delivered O-102 (Customer 1, Tenant A)
        st, created = self._json_req(
            "POST",
            "/api/order-actions",
            {"order_id": "O-102", "type": "return", "expected_order_version": 1, "reason_code": "defective_item"},
            cookie=self.cust1,
        )
        self.assertEqual(st, 201)
        req_id = created["order_action_request_id"]
        case_id = created["case_id"]

        # Create second request on O-202 (Customer 2, Tenant A — another case in same tenant)
        st2, created2 = self._json_req(
            "POST",
            "/api/order-actions",
            {"order_id": "O-202", "type": "return", "expected_order_version": 1, "reason_code": "wrong_item"},
            cookie=self.cust2,
        )
        self.assertEqual(st2, 201)
        req_id_other_case = created2["order_action_request_id"]

        # 1. Reject PDF (%PDF-1.7) and invalid magic bytes (GIF, EXE, polyglot)
        st_pdf, _, raw_pdf = self._raw_call(
            "POST",
            f"/api/order-actions/{req_id}/evidence",
            b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n",
            content_type="application/pdf",
            cookie=self.cust1,
        )
        self.assertEqual((st_pdf, json.loads(raw_pdf)["error"]), (415, "pdf_evidence_deferred"))

        for bad_bytes in (b"GIF89a\x01\x00\x01\x00\x80\x00\x00", b"MZ\x90\x00\x03\x00\x00\x00", b"\xff\xd8\xffNOT_A_VALID_JPEG"):
            st_bad, _, raw_bad = self._raw_call(
                "POST",
                f"/api/order-actions/{req_id}/evidence",
                bad_bytes,
                content_type="image/jpeg",
                cookie=self.cust1,
            )
            self.assertIn(st_bad, (400, 415))

        # 2. Reject > 10 MB on evidence route (413 evidence_too_large), AND verify other routes still cap at 16 KB!
        st_huge, _, raw_huge = self._raw_call(
            "POST",
            f"/api/order-actions/{req_id}/evidence",
            b"x",
            content_type="image/jpeg",
            cookie=self.cust1,
            length_override=str(10_485_761),
        )
        self.assertEqual((st_huge, json.loads(raw_huge)["error"]), (413, "evidence_too_large"))

        big_json = json.dumps({"pad": "a" * 20_000}).encode("utf-8")
        st_other_route, _, raw_other_route = self._raw_call(
            "POST",
            "/api/order-actions",
            big_json,
            content_type="application/json",
            cookie=self.cust1,
        )
        self.assertEqual((st_other_route, json.loads(raw_other_route)["error"]), (413, "body_too_large"))

        # 3. Upload JPEG with EXIF+GPS, PNG with text chunks, and 3 WebPs (total 5 images) -> 6th rejected with 409!
        jpeg_with_exif = self._make_jpeg_with_exif_and_gps()
        st_up1, _, raw_up1 = self._raw_call(
            "POST",
            f"/api/order-actions/{req_id}/evidence",
            jpeg_with_exif,
            content_type="image/jpeg",
            cookie=self.cust1,
        )
        self.assertEqual(st_up1, 201, raw_up1)
        ev1 = json.loads(raw_up1)["evidence"]
        ev1_id = ev1["evidence_id"]
        self.assertEqual((ev1["mime_type"], ev1["width"], ev1["height"]), ("image/jpeg", 48, 32))

        # Verify stored file is outside web root under <data_root>/evidence/tenant-ev-a/<ev_id> with ZERO EXIF/GPS
        stored_path = self.root / "evidence" / "tenant-ev-a" / ev1_id
        self.assertTrue(stored_path.is_file())
        stored_bytes = stored_path.read_bytes()
        self.assertEqual(hashlib.sha256(stored_bytes).hexdigest(), ev1["sha256"])
        self.assertNotIn(b"Nguyen Van Secret", stored_bytes)
        self.assertNotIn(b"Customer Private Home Photo", stored_bytes)
        with Image.open(io.BytesIO(stored_bytes)) as clean_img:
            clean_exif = clean_img.getexif()
            self.assertEqual(len(clean_exif), 0)
            self.assertEqual(len(clean_exif.get_ifd(0x8825)), 0)

        # Upload #2 (PNG with PII text metadata) -> metadata stripped
        png_with_meta = self._make_png_with_text()
        st_up2, _, raw_up2 = self._raw_call(
            "POST",
            f"/api/order-actions/{req_id}/evidence",
            png_with_meta,
            content_type="image/png",
            cookie=self.cust1,
        )
        self.assertEqual(st_up2, 201)
        ev2 = json.loads(raw_up2)["evidence"]
        png_stored = (self.root / "evidence" / "tenant-ev-a" / ev2["evidence_id"]).read_bytes()
        self.assertNotIn(b"Private PII Author", png_stored)
        self.assertNotIn(b"10.7769", png_stored)

        # Uploads #3, #4, #5 (WebP, including one multipart/form-data upload)
        webp_raw = self._make_webp()
        boundary = "----RetailOpsEvidenceBoundary99"
        mp_body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="photo3.webp"\r\n'
            f"Content-Type: image/webp\r\n\r\n"
        ).encode("utf-8") + webp_raw + f"\r\n--{boundary}--\r\n".encode("utf-8")
        st_mp, _, _ = self._raw_call(
            "POST",
            f"/api/order-actions/{req_id}/evidence",
            mp_body,
            content_type=f"multipart/form-data; boundary={boundary}",
            cookie=self.cust1,
        )
        self.assertEqual(st_mp, 201)
        for _ in range(2):
            st_w, _, _ = self._raw_call(
                "POST",
                f"/api/order-actions/{req_id}/evidence",
                webp_raw,
                content_type="image/webp",
                cookie=self.cust1,
            )
            self.assertEqual(st_w, 201)

        # Upload #6 -> MUST fail with 409 evidence_limit_exceeded!
        st_6, _, raw_6 = self._raw_call(
            "POST",
            f"/api/order-actions/{req_id}/evidence",
            webp_raw,
            content_type="image/webp",
            cookie=self.cust1,
        )
        self.assertEqual((st_6, json.loads(raw_6)["error"]), (409, "evidence_limit_exceeded"))

        # 4. Authorization checks on EVERY GET download:
        # Unauthenticated -> 401
        self.assertEqual(self._raw_call("GET", f"/api/order-actions/{req_id}/evidence/{ev1_id}")[0], 401)
        # Other customer in same tenant (case 2) -> 404
        self.assertEqual(self._raw_call("GET", f"/api/order-actions/{req_id}/evidence/{ev1_id}", cookie=self.cust2)[0], 404)
        # Mismatched case/request ID (trying to fetch case 1's evidence via case 2's request_id) -> 404
        self.assertEqual(
            self._raw_call("GET", f"/api/order-actions/{req_id_other_case}/evidence/{ev1_id}", cookie=self.mgr1)[0],
            404,
        )
        # Cross-tenant customer & manager -> 404
        self.assertEqual(self._raw_call("GET", f"/api/order-actions/{req_id}/evidence/{ev1_id}", cookie=self.cust_b)[0], 404)
        self.assertEqual(self._raw_call("GET", f"/api/order-actions/{req_id}/evidence/{ev1_id}", cookie=self.mgr_b)[0], 404)

        # Owning customer & same-tenant Staff/Manager -> 200 with nosniff + clean image bytes
        for ok_cookie in (self.cust1, self.staff1, self.mgr1):
            st_dl, hdrs_dl, bytes_dl = self._raw_call("GET", f"/api/order-actions/{req_id}/evidence/{ev1_id}", cookie=ok_cookie)
            self.assertEqual(st_dl, 200)
            self.assertEqual(hdrs_dl.get("Content-Type"), "image/jpeg")
            self.assertEqual(hdrs_dl.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(bytes_dl, stored_bytes)

        # Once Staff1 claims case (status -> under_review), customer upload is rejected (409 evidence_upload_closed)
        self.assertEqual(self._json_req("POST", f"/api/staff/cases/{case_id}/claim", {}, cookie=self.staff1)[0], 200)
        st_closed_cust, _, raw_closed_cust = self._raw_call(
            "POST",
            f"/api/order-actions/{req_id}/evidence",
            webp_raw,
            content_type="image/webp",
            cookie=self.cust1,
        )
        self.assertEqual((st_closed_cust, json.loads(raw_closed_cust)["error"]), (409, "evidence_upload_closed"))

        # 5. Close request (reject) -> outbox carries evidence_refs (opaque ID + sha256 only, no bytes/URLs), then test 90-day purge!
        st_rej, _ = self._json_req("POST", f"/api/order-actions/{req_id}/reject", {"version": 2, "note": "Không đủ điều kiện"}, cookie=self.staff1)
        self.assertEqual(st_rej, 200)

        with self.store_a.connection() as db:
            rej_ob = json.loads(
                db.execute(
                    "SELECT payload_json FROM integration_outbox WHERE event_type='request_rejected' ORDER BY created_at DESC LIMIT 1"
                ).fetchone()["payload_json"]
            )
            self.assertEqual(len(rej_ob["evidence_refs"]), 5)
            self.assertEqual(set(rej_ob["evidence_refs"][0].keys()), {"evidence_id", "sha256"})

        # At closed_at + 89 days: purge does NOT delete files yet
        self.now += 89 * 86400
        res_early = self.web.run_case_timers_once(now=self.now)
        self.assertEqual(res_early["evidence_purged"], 0)
        self.assertTrue(stored_path.is_file())

        # At closed_at + 90 days + 1s: background purge deletes all 5 files, keeps sha256 & metadata in DB, GET returns 410
        self.now += 86400 + 1
        res_due = self.web.run_case_timers_once(now=self.now)
        self.assertEqual(res_due["evidence_purged"], 5)
        self.assertFalse(stored_path.is_file())

        st_gone, _, raw_gone = self._raw_call("GET", f"/api/order-actions/{req_id}/evidence/{ev1_id}", cookie=self.cust1)
        self.assertEqual((st_gone, json.loads(raw_gone)["error"]), (410, "evidence_purged"))

        with self.store_a.connection() as db:
            ev_meta = db.execute(
                "SELECT sha256, mime_type, byte_size, width, height, file_purged_at FROM order_action_evidence WHERE evidence_id=?",
                (ev1_id,),
            ).fetchone()
            self.assertEqual(ev_meta["sha256"], ev1["sha256"])
            self.assertEqual(ev_meta["mime_type"], "image/jpeg")
            self.assertGreater(ev_meta["byte_size"], 0)
            self.assertEqual((ev_meta["width"], ev_meta["height"]), (48, 32))
            self.assertEqual(ev_meta["file_purged_at"], self.now)


class PhaseR1W3OutboxWorkerJsonlEnvelopeManifestAndCliTests(unittest.TestCase):
    """Item 10 isolated acceptance tests: rollback, concurrent workers, §11.4 PII-free JSONL, closed-day sha256, backoff/dead, CLI."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "data"
        # Fixed UTC timestamp: 2026-11-02T10:00:00Z
        self.now = 1_793_613_600.0
        self.sessions = PersistentSessions(self.root / "persistent")
        self.sessions.store_clock = lambda: self.now
        self.store = self.sessions.provision_tenant("tenant-ob-1", "Outbox Shop", seed_demo=True)
        with self.store.connection(write=True) as db:
            db.execute("UPDATE customers SET name = ? WHERE id = 'C-001'", ("Nguyễn Văn Bí Mật",))
        self.web = PublicWeb("https://retailops.example.com", self.sessions, start_timer_worker=False)

    def test_item10_rollback_concurrency_pii_free_envelope_manifest_backoff_dead_and_cli(self):
        from retailops.business.outbox import utc_day_string, validate_outbox_envelope

        # 1. Rolled-back transaction MUST leave zero outbox rows
        with self.assertRaises(RuntimeError):
            with self.store.connection(write=True) as db:
                self.store._enqueue_outbox_in_tx(
                    db,
                    event_type="order_status_changed",
                    actor={"principal_id": "mgr-1", "role": "manager"},
                    customer_id="C-001",
                    order_id="O-101",
                    before={"status": "pending", "version": 1},
                    after={"status": "delivered", "version": 2},
                    now=self.now,
                )
                raise RuntimeError("abort_before_commit")
        self.assertEqual(self.store.outbox_status_summary()["pending"], 0)

        # 2. Produce committed events (cancel_requested, exchange_requested, order_status_changed, case_feedback_recorded)
        self.store.create_order_action_request(
            "C-001",
            {"order_id": "O-101", "type": "cancel", "expected_order_version": 1, "reason_code": "ordered_by_mistake"},
            actor={"principal_id": "p-cust-secret", "role": "customer", "tenant_id": "tenant-ob-1"},
        )
        self.store.create_order_action_request(
            "C-001",
            {
                "order_id": "O-102",
                "type": "exchange",
                "exchange_kind": "same_variant",
                "expected_order_version": 1,
                "reason_code": "defective_item",
            },
            actor={"principal_id": "p-cust-secret", "role": "customer", "tenant_id": "tenant-ob-1"},
        )
        conv = self.store.new_conversation("C-001")
        self.store.record_feedback(
            "C-001",
            {
                "conversation_id": conv["conversation_id"],
                "feedback_type": "session_csat",
                "rating": 5,
                "reason_code": "fast_support",
                "comment": "Nguyễn Văn Bí Mật SĐT 0909123456 địa chỉ 123 Lê Lợi chat nội dung nhạy cảm",
            },
        )
        self.assertEqual(self.store.outbox_status_summary()["pending"], 3)

        # 3. Run 4 concurrent workers -> each event published ONCE with ZERO duplicate JSONL lines!
        def _worker(_idx):
            s = self.sessions.business_store("tenant-ob-1", migrate=False)
            return s.process_outbox_batch(now=self.now, batch_size=10)

        with ThreadPoolExecutor(max_workers=4) as pool:
            worker_results = list(pool.map(_worker, range(4)))
        self.assertEqual(sum(r["published"] for r in worker_results), 3)
        self.assertEqual(self.store.outbox_status_summary(), {
            "pending": 0,
            "published": 3,
            "dead": 0,
            "oldest_pending_at": None,
            "latest_dead": None,
        })

        day1 = utc_day_string(self.now)
        day1_jsonl = self.root / "integration" / "tenant-ob-1" / f"{day1}.jsonl"
        self.assertTrue(day1_jsonl.is_file())
        raw_text = day1_jsonl.read_text(encoding="utf-8")
        lines = [ln for ln in raw_text.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 3)

        # Validate every envelope against §11.4 schema and assert ZERO PII anywhere in JSONL
        for forbidden_pii in ("Nguyễn Văn Bí Mật", "0909123456", "123 Lê Lợi", "chat nội dung nhạy cảm", "C-001", "p-cust-secret"):
            self.assertNotIn(forbidden_pii, raw_text)

        event_ids = set()
        event_types = set()
        for ln in lines:
            env = json.loads(ln)
            validate_outbox_envelope(env)
            event_ids.add(env["event_id"])
            event_types.add(env["event_type"])
            self.assertTrue(env["customer_ref"].startswith("custref_"))
        self.assertEqual(len(event_ids), 3)
        self.assertEqual(event_types, {"cancel_requested", "exchange_requested", "case_feedback_recorded"})

        # Same UTC day -> manifest NOT sealed yet
        self.assertFalse((self.root / "integration" / "tenant-ob-1" / f"{day1}.sha256").is_file())

        # 4. Advance fake clock to next UTC day (+86400s) -> closed-day SHA-256 manifest is written & matches!
        self.now += 86400
        tick = self.web.run_case_timers_once(now=self.now)
        self.assertEqual(tick["outbox_manifests_sealed"], 1)
        manifest_file = self.root / "integration" / "tenant-ob-1" / f"{day1}.sha256"
        self.assertTrue(manifest_file.is_file())
        expected_sha = hashlib.sha256(day1_jsonl.read_bytes()).hexdigest()
        self.assertEqual(manifest_file.read_text(encoding="utf-8"), f"{expected_sha}  {day1}.jsonl\n")

        # 5. Fake-clock retry schedule: 60s, 300s, 1800s, 7200s, 43200s, 43200s, 43200s -> 8th failure marks 'dead'
        with self.store.connection(write=True) as db:
            db.execute(
                "INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version) "
                "VALUES ('O-199', 'C-001', 'P-101', 'Áo thun', 'Đen / M', 250000, 'pending', 1)"
            )
        self.store.manager_update_order_status("O-199", "delivered", expected_version=1)

        def _always_fail_sink(*_args, **_kwargs):
            raise OSError("disk_sink_unavailable")

        expected_delays = [60, 300, 1800, 7200, 43200, 43200, 43200]
        for idx, exp_delay in enumerate(expected_delays, start=1):
            res_fail = self.store.process_outbox_batch(now=self.now, sink_writer=_always_fail_sink)
            self.assertEqual((res_fail["retried"], res_fail["dead"]), (1, 0), f"attempt {idx}")
            with self.store.connection() as db:
                ob_row = db.execute(
                    "SELECT status, attempts, next_attempt_at FROM integration_outbox WHERE status='pending'"
                ).fetchone()
                self.assertEqual((ob_row["status"], ob_row["attempts"]), ("pending", idx))
                self.assertEqual(ob_row["next_attempt_at"], self.now + exp_delay)
            # 1 second before due -> skipped!
            skip_res = self.store.process_outbox_batch(now=self.now + exp_delay - 1, sink_writer=_always_fail_sink)
            self.assertEqual((skip_res["retried"], skip_res["published"], skip_res["dead"]), (0, 0, 0))
            self.now += exp_delay

        # 8th attempt fails -> transitions to 'dead'!
        res_dead = self.store.process_outbox_batch(now=self.now, sink_writer=_always_fail_sink)
        self.assertEqual((res_dead["retried"], res_dead["dead"]), (0, 1))
        summary = self.store.outbox_status_summary()
        self.assertEqual((summary["pending"], summary["published"], summary["dead"]), (0, 3, 1))
        self.assertEqual(summary["latest_dead"]["attempts"], 8)

        # 6. Read-only CLI: python -m retailops database outbox-status
        cli_env = {**os.environ, "RETAILOPS_STORAGE_BACKEND": "sqlite", "RETAILOPS_OUTPUT": str(self.root)}
        cli_proc = subprocess.run(
            [sys.executable, "-m", "retailops", "database", "outbox-status"],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=cli_env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(cli_proc.returncode, 0, cli_proc.stderr)
        cli_json = json.loads(cli_proc.stdout)
        self.assertEqual(cli_json["result"], "OUTBOX_STATUS")
        self.assertTrue(cli_json["read_only"])
        self.assertEqual(cli_json["totals"], {"pending": 0, "published": 3, "dead": 1})


class PhaseR1W3AgentPrepareOrderActionTests(unittest.TestCase):
    """Item 11: prepare_order_action (and alias prepare_cancellation) strictly read-only, uncached, and action-aware."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="r1-w3-item11-")
        self.addCleanup(self.tmp.cleanup)
        self.store = BusinessStore(Path(self.tmp.name) / "business.sqlite3")
        self.store.seed()

        class ScriptedAgent:
            def __init__(self):
                self.replies = []

            def chat(self, _messages, _allow_tools, _timeout):
                return self.replies.pop(0)

            def inspect(self):
                return {
                    "name": "qwen3.5:4b",
                    "digest": "sha256:fixture",
                    "details": {},
                    "ollama_version": "0.6.0",
                    "agent_protocol": "retailops-agent-v2",
                    "provider": "custom",
                    "identity_source": "fixture",
                }

        self.model = ScriptedAgent()
        self.app = Application(self.store, {}, self.model, orchestrator="single_agent")
        self.cid = self.store.new_conversation("C-001")["conversation_id"]

    @staticmethod
    def _tool_reply(name: str, args: dict):
        return {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": name, "arguments": args}}],
            }
        }

    @staticmethod
    def _text_reply(text: str):
        return {"message": {"role": "assistant", "content": text}}

    def _chat(self, text: str) -> dict:
        return self.app.chat(
            "C-001",
            {
                "conversation_id": self.cid,
                "text": text,
                "request_id": f"req-{secrets.token_hex(12)}",
            },
        )

    def test_item11_prepare_order_action_and_alias_are_strictly_readonly_and_uncached(self):
        from agent_protocol import ProtocolError, TOOLS, validate_tool

        self.assertEqual(len(TOOLS), 12)
        self.assertIn("prepare_order_action", {t["function"]["name"] for t in TOOLS})

        # Protocol validation: prepare_order_action & alias prepare_cancellation reject write flags or bad enums
        validate_tool("prepare_order_action", {"order_id": "O-101"})
        validate_tool("prepare_order_action", {"order_id": "O-102", "action_type": "return"})
        validate_tool("prepare_order_action", {"order_id": "O-102", "action_type": "exchange", "exchange_kind": "same_variant"})
        validate_tool("prepare_cancellation", {"order_id": "O-101"})
        for bad_name, bad_args in (
            ("prepare_order_action", {"order_id": "O-101", "confirmed": True}),
            ("prepare_order_action", {"order_id": "O-101", "action_type": "refund"}),
            ("prepare_order_action", {"order_id": "O-102", "action_type": "return", "exchange_kind": "other_variant"}),
            ("prepare_order_action", {"order_id": "O-102", "action_type": "exchange", "exchange_kind": "size"}),
            ("prepare_cancellation", {"order_id": "O-101", "action_type": "return"}),
        ):
            with self.assertRaises(ProtocolError):
                validate_tool(bad_name, bad_args)

        # 1. prepare_order_action(O-101, cancel) -> eligible, opens reason card, creates ZERO rows!
        self.model.replies = [
            self._tool_reply("prepare_order_action", {"order_id": "O-101", "action_type": "cancel"}),
            self._text_reply("Vui lòng chọn lý do hủy đơn O-101 trên giao diện."),
        ]
        res_cancel = self._chat("Tôi muốn hủy đơn O-101")
        self.assertEqual(res_cancel["action"], "choose_cancel_reason")
        self.assertEqual(res_cancel["order"]["id"], "O-101")
        self.assertEqual(res_cancel["order_action"], {"action_type": "cancel", "exchange_kind": None, "order_id": "O-101"})

        # 2. prepare_order_action(O-102, exchange, other_variant) on delivered order -> eligible, choose_order_action_reason, ZERO rows!
        self.model.replies = [
            self._tool_reply(
                "prepare_order_action",
                {"order_id": "O-102", "action_type": "exchange", "exchange_kind": "other_variant"},
            ),
            self._text_reply("Đơn O-102 đủ điều kiện đổi size, vui lòng chọn lý do và xác nhận."),
        ]
        res_ex = self._chat("Tôi muốn đổi size cho đơn O-102")
        self.assertEqual(res_ex["action"], "choose_order_action_reason")
        self.assertEqual(
            res_ex["order_action"],
            {"action_type": "exchange", "exchange_kind": "other_variant", "order_id": "O-102"},
        )

        # 3. Alias prepare_cancellation(O-101) still works identically and remains read-only
        self.model.replies = [
            self._tool_reply("prepare_cancellation", {"order_id": "O-101"}),
            self._text_reply("Mở chọn lý do hủy đơn O-101."),
        ]
        res_alias = self._chat("Hủy giúp tôi đơn O-101")
        self.assertEqual(res_alias["action"], "choose_cancel_reason")

        # 4. Ineligible combinations (return on pending O-101; cancel on delivered O-102) -> action == 'reply'
        self.model.replies = [
            self._tool_reply("prepare_order_action", {"order_id": "O-101", "action_type": "return"}),
            self._text_reply("Đơn O-101 chưa giao nên chưa thể trả hàng."),
        ]
        self.assertEqual(self._chat("Trả hàng đơn O-101")["action"], "reply")

        self.model.replies = [
            self._tool_reply("prepare_order_action", {"order_id": "O-102", "action_type": "cancel"}),
            self._text_reply("Đơn O-102 đã giao nên không thể hủy."),
        ]
        self.assertEqual(self._chat("Hủy đơn O-102")["action"], "reply")

        # Verify ZERO requests, ZERO decisions, ZERO proposals, ZERO handoffs, ZERO outbox rows were created by tools!
        with self.store.connection() as db:
            for tbl in ("order_action_requests", "order_action_decisions", "proposals", "handoff_episodes", "integration_outbox"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0], 0, tbl)
            self.assertEqual(db.execute("SELECT status FROM orders WHERE id='O-101'").fetchone()[0], "pending")
            self.assertEqual(db.execute("SELECT status FROM orders WHERE id='O-102'").fetchone()[0], "delivered")

        # Verify prepare_order_action is NEVER cached in tool_cache
        self.assertIsNone(
            self.app.tool_cache.get("default", "C-001", "prepare_order_action", {"order_id": "O-101", "action_type": "cancel"})
        )

        # 5. Once customer submits an open request on O-102, prepare_order_action reports ineligible (has_open_request=True)
        self.store.create_order_action_request(
            "C-001",
            {
                "order_id": "O-102",
                "type": "return",
                "expected_order_version": 1,
                "reason_code": "defective_item",
                "conversation_id": self.cid,
            },
        )
        self.model.replies = [
            self._tool_reply("prepare_order_action", {"order_id": "O-102", "action_type": "return"}),
            self._text_reply("Đơn O-102 đã có yêu cầu đang chờ xử lý."),
        ]
        self.assertEqual(self._chat("Cho tôi gửi thêm yêu cầu trả hàng O-102")["action"], "reply")


if __name__ == "__main__":
    unittest.main()
