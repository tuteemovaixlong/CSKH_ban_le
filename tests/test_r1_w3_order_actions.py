"""Phase R1 W3 isolated tests for Business v6, order actions, evidence, outbox, and UI/agent contracts."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

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
from retailops.identity.persistent import PersistentSessions
from retailops.identity.postgres import PostgresSessions
from retailops.identity.store import IdentityStore
from retailops.storage import cli as database_cli
from retailops.storage.pg_repositories import (
    PostgresBusinessStore,
    migrate_postgres_business_v6,
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
        self.assertEqual(SQLITE_BUSINESS_SCHEMA_CURRENT, 5)
        self.assertEqual(POSTGRES_BUSINESS_SCHEMA_CURRENT, 6)
        self.assertEqual(BUSINESS_SCHEMA_CURRENT, 6)
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
            self.assertEqual((ver_row["component"], ver_row["version"]), ("business", 5))
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

            # 2. Controlled migrate-v6 upgrades ALL tenants to SQLite v5 (logical Business v6)
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

            chk = database_cli.run(parser.parse_args(["database", "check"]))
            self.assertEqual(chk["result"], "POSTGRES_SCHEMA_READY")

            for sc in (schema_a, schema_b):
                mem = state.schemas[sc]
                self.assertEqual(mem.execute("SELECT version FROM retailops_schema").fetchone()[0], 6)
                o102 = mem.execute("SELECT delivered_at FROM orders WHERE id='O-102'").fetchone()
                self.assertIsNone(o102["delivered_at"])
                # Pending proposal NOT backfilled (W3-D9)
                self.assertEqual(mem.execute("SELECT COUNT(*) FROM proposals").fetchone()[0], 1)
                self.assertEqual(mem.execute("SELECT COUNT(*) FROM order_action_requests").fetchone()[0], 0)

            # 3. Fresh PostgreSQL tenant schema initializes directly to v6 and enforces partial unique + append-only
            key_c = "c" * 32
            PostgresBusinessStore(pg_dsn, key_c, create=True)
            schema_c = tenant_schema(key_c)
            mem_c = state.schemas[schema_c]
            self.assertEqual(mem_c.execute("SELECT version FROM retailops_schema").fetchone()[0], 6)
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


if __name__ == "__main__":
    unittest.main()
