"""W3.2 item 2 (W3.2-D1, W3.2-D6): Business v7 and the controlled `migrate-v7` command.

SQLite runs for real. PostgreSQL runs against the SQLite-backed mock used by the W3 tests (it cannot
execute PL/pgSQL), and against a disposable real database when RETAILOPS_TEST_DATABASE_URL is set (CI).
No model, no network.
"""
import argparse
from contextlib import closing, contextmanager
import hashlib
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from retailops.business import schema as business_schema
from retailops.business.schema import (
    BUSINESS_V6_VERSION_MAPPING,
    BUSINESS_V7_VERSION_MAPPING,
    LEGACY_EXCHANGE_KIND_MAP,
    SQLITE_BUSINESS_SCHEMA_CURRENT,
    migrate_order_action_exchange_v7,
)
from retailops.business.store import (
    BusinessStore,
    _inspect_sqlite_business_ready,
    migrate_sqlite_business_v6,
    migrate_sqlite_business_v7,
)
from retailops.core import ApiError
from retailops.identity.persistent import PersistentSessions
from retailops.identity.postgres import PostgresSessions
from retailops.identity.store import IdentityStore
from retailops.storage import cli as database_cli
from retailops.storage import pg_schema
from retailops.storage.pg_repositories import PostgresBusinessStore, migrate_postgres_business_v7
from retailops.storage.pg_schema import initialize as pg_initialize
from retailops.storage.postgres import BUSINESS_SCHEMA_CURRENT, IDENTITY_SCHEMA, tenant_schema
from test_r1_w3_order_actions import _build_mock_pg_harness, _create_sqlite_v5_tenant_db

# The Business v6 (W3) tables exactly as W3 shipped them, so the fixtures are what production holds today.
LEGACY_REQUESTS_DDL = """CREATE TABLE order_action_requests (
    request_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    customer_id TEXT NOT NULL REFERENCES customers(id),
    case_id TEXT NOT NULL REFERENCES cases(case_id),
    conversation_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('cancel', 'return', 'exchange')),
    exchange_kind TEXT {kind_check},
    status TEXT NOT NULL CHECK(
        status IN ('requested', 'under_review', 'approved', 'rejected', 'received', 'inspected', 'completed')),
    inspection_outcome TEXT CHECK(inspection_outcome IS NULL OR inspection_outcome IN ('refund', 'exchange', 'no_action')),
    refund_status TEXT NOT NULL DEFAULT 'not_applicable' CHECK(
        refund_status IN ('not_applicable', 'pending', 'refunded', 'failed')),
    refund_decision TEXT CHECK(refund_decision IS NULL OR refund_decision IN ('approved', 'rejected')),
    reason_code TEXT NOT NULL CHECK(length(trim(reason_code)) > 0),
    reason_text TEXT CHECK(reason_text IS NULL OR length(reason_text) <= 500),
    raised_by_role TEXT NOT NULL CHECK(raised_by_role IN ('customer', 'staff', 'manager')),
    delivery_failure_attempts INTEGER CHECK(delivery_failure_attempts IS NULL OR delivery_failure_attempts >= 1),
    expected_order_version INTEGER NOT NULL CHECK(expected_order_version >= 1),
    version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    reviewed_at REAL,
    received_at REAL,
    inspected_at REAL,
    completed_at REAL,
    closed_at REAL,
    CHECK(
        (type = 'cancel' AND (
            (status IN ('requested', 'under_review') AND closed_at IS NULL)
            OR (status IN ('approved', 'rejected') AND closed_at IS NOT NULL)))
        OR (type IN ('return', 'exchange') AND (
            (status IN ('requested', 'under_review', 'approved', 'received', 'inspected') AND closed_at IS NULL)
            OR (status IN ('rejected', 'completed') AND closed_at IS NOT NULL)))
    ))"""
LEGACY_KIND_CHECK = """CHECK(
        (type = 'exchange' AND exchange_kind IN ('size', 'one_to_one'))
        OR (type <> 'exchange' AND exchange_kind IS NULL))"""
LEGACY_V6_STATEMENTS = (
    'CREATE INDEX idx_order_action_case ON order_action_requests(case_id, created_at DESC)',
    'CREATE INDEX idx_order_action_customer ON order_action_requests(customer_id, created_at DESC)',
    'CREATE INDEX idx_order_action_order ON order_action_requests(order_id, created_at DESC)',
    'CREATE UNIQUE INDEX idx_order_action_one_open_per_order ON order_action_requests(order_id) WHERE closed_at IS NULL',
    """CREATE TABLE order_action_decisions (
        decision_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL REFERENCES order_action_requests(request_id),
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        order_id TEXT NOT NULL REFERENCES orders(id),
        conversation_id TEXT NOT NULL,
        action TEXT NOT NULL, from_status TEXT, to_status TEXT NOT NULL,
        from_refund_status TEXT, to_refund_status TEXT, refund_decision TEXT, inspection_outcome TEXT,
        actor_principal_id TEXT NOT NULL, actor_role TEXT NOT NULL,
        note TEXT CHECK(note IS NULL OR length(note) <= 500),
        created_at REAL NOT NULL)""",
    """CREATE TRIGGER order_action_decisions_no_update BEFORE UPDATE ON order_action_decisions
       BEGIN SELECT RAISE(ABORT, 'order_action_decisions is append-only'); END""",
    """CREATE TRIGGER order_action_decisions_no_delete BEFORE DELETE ON order_action_decisions
       BEGIN SELECT RAISE(ABORT, 'order_action_decisions is append-only'); END""",
    """CREATE TABLE order_action_evidence (
        evidence_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL REFERENCES order_action_requests(request_id),
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        customer_id TEXT NOT NULL REFERENCES customers(id),
        conversation_id TEXT NOT NULL,
        uploaded_by_principal_id TEXT NOT NULL,
        uploaded_by_role TEXT NOT NULL CHECK(uploaded_by_role IN ('customer', 'staff', 'manager')),
        mime_type TEXT NOT NULL CHECK(mime_type IN ('image/jpeg', 'image/png', 'image/webp')),
        byte_size INTEGER NOT NULL CHECK(byte_size > 0 AND byte_size <= 10485760),
        width INTEGER NOT NULL CHECK(width > 0), height INTEGER NOT NULL CHECK(height > 0),
        sha256 TEXT NOT NULL, storage_relpath TEXT NOT NULL, created_at REAL NOT NULL, file_purged_at REAL)""",
    """CREATE TABLE integration_outbox (
        event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
        created_at REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'published', 'dead')),
        attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0), next_attempt_at REAL NOT NULL,
        last_error TEXT, published_at REAL)""",
)
REQUEST_ROWS = (  # request_id, order_id, type, exchange_kind, status, closed_at
    ('oar_cancel', 'O-101', 'cancel', None, 'requested', None),
    ('oar_size', 'O-102', 'exchange', 'size', 'requested', None),
    ('oar_121', 'O-103', 'exchange', 'one_to_one', 'requested', None),
    ('oar_done', 'O-104', 'exchange', 'size', 'completed', 90.0),
    ('oar_return', 'O-105', 'return', None, 'approved', None),
)
EXPECTED_KINDS = {'oar_cancel': None, 'oar_size': 'other_variant', 'oar_121': 'same_variant',
                  'oar_done': 'other_variant', 'oar_return': None}


def build_sqlite_v6_tenant_db(path):
    """A W3-era tenant database (SQLite schema 5) holding one request of every shape plus children."""
    _create_sqlite_v5_tenant_db(path)
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('ALTER TABLE orders ADD COLUMN delivered_at REAL')
        db.execute(LEGACY_REQUESTS_DDL.format(kind_check=LEGACY_KIND_CHECK))
        for statement in LEGACY_V6_STATEMENTS:
            db.execute(statement)
        for oid in ('O-103', 'O-104', 'O-105'):
            db.execute("INSERT INTO orders VALUES (?, 'C-001', 'Áo sơ mi', 'Đen / L', 350000, 'delivered', 1, NULL, 'P-101', NULL)",
                       (oid,))
        for rid, oid, kind_type, kind, status, closed in REQUEST_ROWS:
            db.execute(
                """INSERT INTO order_action_requests(
                       request_id, order_id, customer_id, case_id, conversation_id, type, exchange_kind, status,
                       refund_status, reason_code, raised_by_role, expected_order_version, version,
                       created_at, updated_at, closed_at)
                   VALUES (?, ?, 'C-001', 'case_v5_1', 'conv-v5-1', ?, ?, ?, 'not_applicable', 'wrong_size',
                           'customer', 1, 1, 100.0, 100.0, ?)""",
                (rid, oid, kind_type, kind, status, closed))
            db.execute(
                """INSERT INTO order_action_decisions(decision_id, request_id, case_id, order_id, conversation_id,
                       action, to_status, actor_principal_id, actor_role, created_at)
                   VALUES (?, ?, 'case_v5_1', ?, 'conv-v5-1', 'submit', 'requested', 'p-cust-1', 'customer', 100.0)""",
                ('dec_' + rid, rid, oid))
        db.execute(
            """INSERT INTO order_action_evidence(evidence_id, request_id, case_id, customer_id, conversation_id,
                   uploaded_by_principal_id, uploaded_by_role, mime_type, byte_size, width, height, sha256,
                   storage_relpath, created_at)
               VALUES ('ev_1', 'oar_size', 'case_v5_1', 'C-001', 'conv-v5-1', 'p-cust-1', 'customer', 'image/png',
                       1024, 64, 64, ?, 'shop/ev_1', 100.0)""", ('a' * 64,))
        db.execute("""INSERT INTO integration_outbox(event_id, tenant_id, event_type, payload_json, created_at,
                          next_attempt_at) VALUES ('evt_1', 'shop-a', 'exchange_requested', '{}', 100.0, 100.0)""")
        db.execute("UPDATE retailops_schema SET version=5 WHERE component='business'")
        db.commit()


def table_dump(path):
    with closing(sqlite3.connect(path)) as db:
        return '\n'.join(db.iterdump())


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class SqliteBusinessV7MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def workspace(self, tenants=2):
        ws = self.root / 'ws'
        pers = ws / 'persistent'
        pers.mkdir(parents=True)
        identity = IdentityStore(pers / 'identity.sqlite3')
        paths = []
        for index in range(tenants):
            tenant = identity.ensure_tenant(f'shop-{index}', f'Cửa hàng {index}')
            path = pers / 'tenants' / f"{tenant['storage_key']}.sqlite3"
            build_sqlite_v6_tenant_db(path)
            paths.append(path)
        return ws, pers, paths

    def cli(self, ws, *words):
        parser = argparse.ArgumentParser()
        database_cli.add_parser(parser.add_subparsers(dest='command', required=True))
        with patch.dict(os.environ, {'RETAILOPS_STORAGE_BACKEND': 'sqlite'}, clear=False):
            return database_cli.run(parser.parse_args(['database', '--output', str(ws), *words]))

    def test_version_mapping_is_recorded_in_code(self):
        self.assertEqual(SQLITE_BUSINESS_SCHEMA_CURRENT, 6)
        self.assertEqual(BUSINESS_SCHEMA_CURRENT, 7)
        self.assertEqual(BUSINESS_V6_VERSION_MAPPING, {'logical_milestone': 'business_v6', 'sqlite': 5, 'postgresql': 6})
        self.assertEqual(BUSINESS_V7_VERSION_MAPPING, {'logical_milestone': 'business_v7', 'sqlite': 6, 'postgresql': 7})
        self.assertEqual(LEGACY_EXCHANGE_KIND_MAP, {'size': 'other_variant', 'one_to_one': 'same_variant'})

    def test_fixture_is_a_real_w3_database(self):
        _, _, (path, _) = self.workspace()
        with closing(sqlite3.connect(path)) as db:
            db.execute('PRAGMA foreign_keys=ON')
            self.assertEqual(db.execute('SELECT version FROM retailops_schema').fetchone()[0], 5)
            columns = {r[1] for r in db.execute('PRAGMA table_info(order_action_requests)')}
            self.assertNotIn('target_variant_id', columns)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE order_action_requests SET exchange_kind='other_variant' WHERE request_id='oar_size'")

    def test_startup_is_blocked_until_migrate_v7_and_nothing_is_written(self):
        ws, pers, (path_a, path_b) = self.workspace()
        before = (file_sha(path_a), file_sha(path_b))
        for blocked in (
            lambda: _inspect_sqlite_business_ready(path_a),
            lambda: BusinessStore(path_a, create=False),
            lambda: PersistentSessions(pers),
            lambda: self.cli(ws, 'check'),
        ):
            with self.assertRaises(ApiError) as caught:
                blocked()
            self.assertEqual((caught.exception.status, caught.exception.code), (503, 'business_migration_required'))
            self.assertIn('migrate-v7', caught.exception.message)
        self.assertEqual((file_sha(path_a), file_sha(path_b)), before)
        with self.assertRaises(ApiError) as unconfirmed:
            self.cli(ws, 'migrate-v7', '--confirm-preflight')
        self.assertEqual((unconfirmed.exception.status, unconfirmed.exception.code), (400, 'migration_confirmation_required'))
        self.assertEqual((file_sha(path_a), file_sha(path_b)), before)

    def test_migrate_v7_maps_kinds_keeps_every_row_and_child_and_is_idempotent(self):
        ws, pers, (path_a, path_b) = self.workspace()
        result = self.cli(ws, 'migrate-v7', '--confirm-preflight', '--confirm-backup')
        self.assertEqual(result, {
            'result': 'BUSINESS_V7_MIGRATED', 'backend': 'sqlite', 'schema_version': 6, 'logical_version': 7,
            'tenants': 2, 'upgraded': True, 'order_action_requests': 10, 'exchange_requests_mapped': 6})
        for path in (path_a, path_b):
            with closing(sqlite3.connect(path)) as db:
                db.row_factory = sqlite3.Row
                db.execute('PRAGMA foreign_keys=ON')
                self.assertEqual(db.execute('SELECT version FROM retailops_schema').fetchone()[0], 6)
                rows = {r['request_id']: dict(r) for r in db.execute('SELECT * FROM order_action_requests')}
                self.assertEqual({k: v['exchange_kind'] for k, v in rows.items()}, EXPECTED_KINDS)
                self.assertTrue(all(v['target_variant_id'] is None and v['target_variant_label'] is None for v in rows.values()))
                self.assertEqual(rows['oar_done']['status'], 'completed')  # the closed request is kept as it was
                self.assertEqual(rows['oar_size']['reason_code'], 'wrong_size')  # old reason codes are untouched
                self.assertEqual(db.execute('SELECT COUNT(*) FROM order_action_decisions').fetchone()[0], 5)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM order_action_evidence').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM integration_outbox').fetchone()[0], 1)
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                indexes = {r[1] for r in db.execute('PRAGMA index_list(order_action_requests)')}
                self.assertTrue({'idx_order_action_one_open_per_order', 'idx_order_action_case',
                                 'idx_order_action_customer', 'idx_order_action_order'} <= indexes)
                with self.assertRaises(sqlite3.IntegrityError):  # one open request per order still holds
                    db.execute("""INSERT INTO order_action_requests(request_id, order_id, customer_id, case_id,
                        conversation_id, type, status, refund_status, reason_code, raised_by_role,
                        expected_order_version, created_at, updated_at) VALUES ('oar_dup', 'O-101', 'C-001',
                        'case_v5_1', 'conv-v5-1', 'cancel', 'requested', 'not_applicable', 'x', 'customer', 1, 1, 1)""")
        dumps = (table_dump(path_a), table_dump(path_b))
        again = self.cli(ws, 'migrate-v7', '--confirm-preflight', '--confirm-backup')
        self.assertEqual((again['upgraded'], again['exchange_requests_mapped'], again['order_action_requests']), (False, 0, 10))
        self.assertEqual((table_dump(path_a), table_dump(path_b)), dumps)
        self.assertEqual(self.cli(ws, 'check'), {'result': 'SQLITE_SCHEMA_READY', 'tenants_checked': 2})
        PersistentSessions(pers)  # startup now succeeds

    def test_offline_postgres_import_reads_both_the_w3_and_the_v7_snapshot(self):
        from retailops.storage.import_sqlite import BUSINESS_TABLES, read_database
        ws, pers, (path,) = self.workspace(1)
        legacy = read_database(path, 'business', BUSINESS_TABLES)['order_action_requests']
        self.assertEqual({r['request_id']: r['exchange_kind'] for r in legacy}, EXPECTED_KINDS)  # mapped on read
        self.assertTrue(all(r['target_variant_id'] is None and r['target_variant_label'] is None for r in legacy))
        migrate_sqlite_business_v7(ws, preflight_confirmed=True, backup_confirmed=True)
        current = read_database(path, 'business', BUSINESS_TABLES)['order_action_requests']
        self.assertEqual({r['request_id']: r['exchange_kind'] for r in current}, EXPECTED_KINDS)
        self.assertEqual(sorted(r['request_id'] for r in current), sorted(r['request_id'] for r in legacy))

    def test_migrate_v6_stops_at_the_w3_milestone(self):
        ws, pers, (path_a,) = self.workspace(1)
        dump = table_dump(path_a)
        result = migrate_sqlite_business_v6(ws, preflight_confirmed=True, backup_confirmed=True)
        self.assertEqual((result['schema_version'], result['upgraded']), (5, False))
        with closing(sqlite3.connect(path_a)) as db:
            columns = {r[1] for r in db.execute('PRAGMA table_info(order_action_requests)')}
        self.assertNotIn('target_variant_id', columns)
        self.assertEqual(table_dump(path_a), dump)

    def test_v5_database_reaches_v7_in_one_command(self):
        ws = self.root / 'v5'
        path = ws / 'business.sqlite3'
        _create_sqlite_v5_tenant_db(path)
        result = migrate_sqlite_business_v7(path, preflight_confirmed=True, backup_confirmed=True)
        self.assertEqual((result['schema_version'], result['tenants'], result['upgraded']), (6, 1, True))
        store = BusinessStore(path, create=False)
        with store.connection() as db:
            self.assertEqual(db.execute('SELECT version FROM retailops_schema').fetchone()[0], 6)
            columns = {r[1] for r in db.execute('PRAGMA table_info(order_action_requests)')}
        self.assertTrue({'target_variant_id', 'target_variant_label'} <= columns)

    def test_a_failed_migration_rolls_back_to_the_untouched_w3_database(self):
        _, _, (path,) = self.workspace(1)
        dump = table_dump(path)
        with patch.object(business_schema, 'ensure_order_action_tables', side_effect=RuntimeError('boom after rebuild')):
            with self.assertRaises(RuntimeError):
                migrate_sqlite_business_v7(path, preflight_confirmed=True, backup_confirmed=True)
        self.assertEqual(table_dump(path), dump)
        with self.assertRaises(ApiError):
            _inspect_sqlite_business_ready(path)

    def test_the_rebuild_refuses_to_run_with_foreign_keys_on(self):
        _, _, (path,) = self.workspace(1)
        with closing(sqlite3.connect(path)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            with self.assertRaises(ValueError):
                migrate_order_action_exchange_v7(db)
            self.assertNotIn('target_variant_id', {r[1] for r in db.execute('PRAGMA table_info(order_action_requests)')})

    def test_fresh_database_is_v7_and_enforces_the_exchange_shape(self):
        store = BusinessStore(self.root / 'fresh.sqlite3')
        store.seed()
        with store.connection(write=True) as db:
            self.assertEqual(db.execute('SELECT version FROM retailops_schema').fetchone()[0], 6)
            db.execute("INSERT INTO conversations(id, customer_id, expires_at, provider_id) VALUES ('c1', 'C-001', 9e9, 'custom')")
            db.execute("""INSERT INTO cases(case_id, conversation_id, customer_id, status, version, resume_count,
                          created_at, updated_at) VALUES ('k1', 'c1', 'C-001', 'waiting', 1, 0, 1, 1)""")
            orders = iter(['O-101', 'O-102', 'O-202'])

            def insert(kind, target_id=None, target_label=None, request_type='exchange'):
                db.execute(
                    """INSERT INTO order_action_requests(request_id, order_id, customer_id, case_id, conversation_id,
                           type, exchange_kind, target_variant_id, target_variant_label, status, refund_status,
                           reason_code, raised_by_role, expected_order_version, created_at, updated_at)
                       VALUES (?, ?, 'C-001', 'k1', 'c1', ?, ?, ?, ?, 'requested', 'not_applicable', 'x',
                               'customer', 1, 1, 1)""",
                    (f'r_{kind}_{target_id}_{request_type}', next(orders), request_type, kind, target_id, target_label))

            for bad in (('size',), ('one_to_one',), (None,), ('same_variant', 'V-1', 'Đen / L'),
                        ('other_variant', None, 'Đen / L'), ('other_variant', 'V-1', None),
                        ('other_variant', 'V-1', 'x' * 201)):
                with self.subTest(bad=bad), self.assertRaises(sqlite3.IntegrityError):
                    insert(*bad)
                orders = iter(['O-101', 'O-102', 'O-202'])
            with self.assertRaises(sqlite3.IntegrityError):  # a cancel request cannot carry an exchange kind
                insert('same_variant', request_type='cancel')
            orders = iter(['O-101', 'O-102', 'O-202'])
            insert('same_variant')
            insert('other_variant', 'V-1', 'Đen / L')
            insert('other_variant')  # a migrated W3 `size` row has no target, so the database allows it


class PostgresDdlStaticTests(unittest.TestCase):
    def test_no_statement_contains_a_percent_sign(self):
        """psycopg treats % as a placeholder, which is what broke the W3.1 LIKE patterns."""
        for name in ('BUSINESS_V6_DDL', 'BUSINESS_V7_UPGRADE_DDL'):
            for statement in getattr(pg_schema, name):
                self.assertNotIn('%', statement, (name, statement[:80]))

    def test_fresh_and_upgraded_tables_share_the_same_named_constraints(self):
        fresh = next(s for s in pg_schema.BUSINESS_V6_TABLES_DDL if s.lstrip().startswith('CREATE TABLE IF NOT EXISTS order_action_requests'))
        upgrade = ' '.join(pg_schema.BUSINESS_V7_UPGRADE_DDL)
        for name in ('order_action_requests_exchange_kind_v7_check', 'order_action_requests_target_variant_v7_check'):
            self.assertIn(name, fresh)
            self.assertIn(name, upgrade)
        self.assertIn('target_variant_id TEXT', fresh)
        self.assertNotIn("'size'", fresh)


class PostgresMockMigrationTests(unittest.TestCase):
    """The SQLite-backed PostgreSQL harness of the W3 tests, seeded with W3 (schema 6) tenants."""

    def build(self):
        keys = ['a' * 32, 'b' * 32]
        state, mock_conn = _build_mock_pg_harness(keys)
        for index, key in enumerate(keys):
            mem = state.schemas[tenant_schema(key)]
            # SQLite cannot drop a CHECK, so the mock W3 table omits the old kind check; the real thing is
            # covered by RealPostgresBusinessV7Tests below.
            mem.execute(LEGACY_REQUESTS_DDL.format(kind_check=''))
            if 'delivered_at' not in {r[1] for r in mem.execute('PRAGMA table_info(orders)')}:
                mem.execute('ALTER TABLE orders ADD COLUMN delivered_at REAL')
            mem.execute("INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version) "
                        "VALUES ('O-103', 'C-001', 'P-101', 'Áo PG', 'Đen / L', 1, 'delivered', 1)")
            mem.execute("INSERT INTO cases(case_id, conversation_id, customer_id, status, version, resume_count, "
                        "created_at, updated_at) VALUES ('case_pg_v6', 'conv_pg_v6', 'C-001', 'waiting', 1, 0, 1.0, 1.0)")
            rows = [('oar_x', 'O-102', 'exchange', 'size')] + ([('oar_y', 'O-103', 'exchange', 'one_to_one'),
                                                                  ('oar_z', 'O-101', 'cancel', None)] if index == 0 else [])
            for rid, oid, kind_type, kind in rows:
                mem.execute(
                    """INSERT INTO order_action_requests(request_id, order_id, customer_id, case_id, conversation_id,
                           type, exchange_kind, status, refund_status, reason_code, raised_by_role,
                           expected_order_version, version, created_at, updated_at)
                       VALUES (?, ?, 'C-001', 'case_pg_v6', 'conv_pg_v6', ?, ?, 'requested', 'not_applicable',
                               'changed_mind', 'customer', 1, 1, 1.0, 1.0)""", (rid, oid, kind_type, kind))
            mem.execute('UPDATE retailops_schema SET version=6')
            mem.commit()
        return keys, state, mock_conn

    def test_w3_postgres_schemas_are_blocked_then_migrated_with_the_same_mapping(self):
        dsn = 'postgresql://retailops:secret@127.0.0.1:5432/retailops'
        keys, state, mock_conn_cls = self.build()
        mock_psycopg = MagicMock()
        mock_psycopg.conninfo.conninfo_to_dict.return_value = {'dbname': 'retailops', 'user': 'retailops'}
        mock_sql = MagicMock()
        mock_sql.SQL = lambda s: SimpleNamespace(format=lambda *a: s.format(*a))
        mock_sql.Identifier = lambda s: s
        mock_psycopg.sql = mock_sql

        @contextmanager
        def fake_tx(dsn_, schema=IDENTITY_SCHEMA, *, write=False, read_only=False):
            yield mock_conn_cls(schema)

        parser = argparse.ArgumentParser()
        database_cli.add_parser(parser.add_subparsers(dest='command', required=True))
        schema_a, schema_b = (tenant_schema(k) for k in keys)
        with patch.dict('sys.modules', {'psycopg': mock_psycopg, 'psycopg.sql': mock_sql}), \
             patch('retailops.storage.pg_repositories.transaction', side_effect=fake_tx), \
             patch('retailops.storage.postgres.transaction', side_effect=fake_tx), \
             patch('retailops.identity.postgres.transaction', side_effect=fake_tx), \
             patch('retailops.storage.cli.os.environ', {'RETAILOPS_STORAGE_BACKEND': 'postgresql', 'RETAILOPS_DATABASE_URL': dsn}), \
             patch.dict(os.environ, {'RETAILOPS_STORAGE_BACKEND': 'postgresql', 'RETAILOPS_DATABASE_URL': dsn}, clear=False):
            for blocked in (
                lambda: pg_initialize(mock_conn_cls(schema_a), schema_a, 'business'),
                lambda: PostgresBusinessStore(dsn, keys[0], create=False),
                lambda: PostgresSessions(dsn),
                lambda: database_cli.run(parser.parse_args(['database', 'check'])),
                lambda: database_cli.run(parser.parse_args(['database', 'migrate'])),
            ):
                with self.assertRaises(ApiError) as caught:
                    blocked()
                self.assertEqual((caught.exception.status, caught.exception.code), (503, 'business_migration_required'))
                self.assertIn('migrate-v7', caught.exception.message)
            for schema in (schema_a, schema_b):
                self.assertEqual(state.schemas[schema].execute('SELECT version FROM retailops_schema').fetchone()[0], 6)
            with self.assertRaises(ApiError) as unconfirmed:
                database_cli.run(parser.parse_args(['database', 'migrate-v7', '--confirm-backup']))
            self.assertEqual(unconfirmed.exception.code, 'migration_confirmation_required')

            result = database_cli.run(parser.parse_args(['database', 'migrate-v7', '--confirm-preflight', '--confirm-backup']))
            self.assertEqual(result, {
                'result': 'BUSINESS_V7_MIGRATED', 'backend': 'postgresql', 'schema_version': 7, 'logical_version': 7,
                'tenants': 2, 'upgraded': True, 'order_action_requests': 4, 'exchange_requests_mapped': 3})
            again = migrate_postgres_business_v7(dsn, preflight_confirmed=True, backup_confirmed=True)
            self.assertEqual((again['upgraded'], again['exchange_requests_mapped'], again['order_action_requests']), (False, 0, 4))

            kinds = {}
            for schema in (schema_a, schema_b):
                mem = state.schemas[schema]
                self.assertEqual(mem.execute('SELECT version FROM retailops_schema').fetchone()[0], 7)
                self.assertTrue({'target_variant_id', 'target_variant_label'} <= {r[1] for r in mem.execute('PRAGMA table_info(order_action_requests)')})
                kinds.update({r['request_id']: (r['exchange_kind'], r['target_variant_id'])
                              for r in mem.execute('SELECT request_id, exchange_kind, target_variant_id FROM order_action_requests')})
            self.assertEqual(kinds, {'oar_x': ('other_variant', None), 'oar_y': ('same_variant', None), 'oar_z': (None, None)})
            self.assertEqual(database_cli.run(parser.parse_args(['database', 'check']))['result'], 'POSTGRES_SCHEMA_READY')

            PostgresBusinessStore(dsn, 'c' * 32, create=True)  # a fresh schema is v7 straight away
            self.assertEqual(state.schemas[tenant_schema('c' * 32)].execute('SELECT version FROM retailops_schema').fetchone()[0], 7)


DSN = os.environ.get('RETAILOPS_TEST_DATABASE_URL', '')


@unittest.skipUnless(DSN, 'PostgreSQL integration runs in CI with a dedicated test database.')
class RealPostgresBusinessV7Tests(unittest.TestCase):
    """Runs the real DDL (PL/pgSQL blocks, named CHECKs) against the disposable CI database."""

    @classmethod
    def setUpClass(cls):
        import psycopg
        from scripts.postgres_test_guard import require_disposable_postgres_test_target
        require_disposable_postgres_test_target(DSN, psycopg.conninfo.conninfo_to_dict)

    def clear(self):
        from psycopg import sql
        from retailops.storage.postgres import transaction
        with transaction(DSN, write=True) as db:
            names = db.execute("SELECT nspname FROM pg_namespace WHERE nspname=? OR nspname ~ '^tenant_[a-f0-9]{32}$'",
                               (IDENTITY_SCHEMA,)).fetchall()
            for row in names:
                db.raw.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(row['nspname'])))

    def setUp(self):
        from retailops.storage.pg_repositories import PostgresIdentityStore
        self.clear()
        self.addCleanup(self.clear)
        PostgresIdentityStore(DSN, create=True)
        self.sessions = PostgresSessions(DSN, api_daily_limit=1)
        self.sessions.provision_tenant('shop-a', 'Cửa hàng A', seed_demo=True)
        self.schema = tenant_schema(self.sessions.control.tenant('shop-a')['storage_key'])

    def constraints(self):
        from retailops.storage.postgres import transaction
        with transaction(DSN, self.schema) as db:
            return {r['conname'] for r in db.execute(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'order_action_requests'::regclass AND contype = 'c'").fetchall()}

    def downgrade_to_w3(self):
        """Rewrite the tenant's request table to what the W3 release created (auto-named kind CHECK)."""
        from retailops.storage.postgres import transaction
        with transaction(DSN, self.schema, write=True) as db:
            for statement in (
                'ALTER TABLE order_action_requests DROP CONSTRAINT order_action_requests_exchange_kind_v7_check',
                'ALTER TABLE order_action_requests DROP CONSTRAINT order_action_requests_target_variant_v7_check',
                'ALTER TABLE order_action_requests DROP COLUMN target_variant_id',
                'ALTER TABLE order_action_requests DROP COLUMN target_variant_label',
                "ALTER TABLE order_action_requests ADD CONSTRAINT order_action_requests_check1 CHECK ("
                "(type = 'exchange' AND exchange_kind IN ('size', 'one_to_one')) "
                "OR (type <> 'exchange' AND exchange_kind IS NULL))",
                "UPDATE retailops_schema SET version = 6 WHERE component = 'business'",
                "INSERT INTO orders(id, customer_id, name, variant, amount, status, version) VALUES "
                "('O-V7B', 'C-001', 'Áo', 'Đen / L', 1, 'delivered', 1), ('O-V7C', 'C-001', 'Áo', 'Đen / M', 1, 'delivered', 1), "
                "('O-V7A', 'C-001', 'Áo', 'Đen / S', 1, 'pending', 1)",
                "INSERT INTO cases(case_id, conversation_id, customer_id, status, version, resume_count, created_at, updated_at) "
                "VALUES ('case_v7', 'conv_v7', 'C-001', 'waiting', 1, 0, 1.0, 1.0)",
            ):
                db.execute(statement)
            for request_id, order_id, kind_type, kind in (('oar_a', 'O-V7A', 'cancel', None), ('oar_b', 'O-V7B', 'exchange', 'size'),
                                                         ('oar_c', 'O-V7C', 'exchange', 'one_to_one')):
                db.execute(
                    """INSERT INTO order_action_requests(request_id, order_id, customer_id, case_id, conversation_id,
                           type, exchange_kind, status, refund_status, reason_code, raised_by_role,
                           expected_order_version, version, created_at, updated_at)
                       VALUES (?, ?, 'C-001', 'case_v7', 'conv_v7', ?, ?, 'requested', 'not_applicable',
                               'changed_mind', 'customer', 1, 1, 1.0, 1.0)""", (request_id, order_id, kind_type, kind))

    def test_fresh_schema_is_v7_with_named_constraints(self):
        from retailops.storage.postgres import transaction
        self.assertTrue({'order_action_requests_exchange_kind_v7_check', 'order_action_requests_target_variant_v7_check'}
                        <= self.constraints())
        with transaction(DSN, self.schema) as db:
            self.assertEqual(db.execute('SELECT version FROM retailops_schema').fetchone()['version'], 7)

    def test_w3_schema_is_blocked_then_migrated_idempotently_with_the_mapping(self):
        from retailops.storage.postgres import transaction
        self.downgrade_to_w3()
        with self.assertRaises(ApiError) as blocked:
            PostgresBusinessStore(DSN, self.sessions.control.tenant('shop-a')['storage_key'])
        self.assertEqual(blocked.exception.code, 'business_migration_required')
        result = migrate_postgres_business_v7(DSN, preflight_confirmed=True, backup_confirmed=True)
        self.assertEqual((result['schema_version'], result['upgraded'], result['order_action_requests'],
                          result['exchange_requests_mapped']), (7, True, 3, 2))
        again = migrate_postgres_business_v7(DSN, preflight_confirmed=True, backup_confirmed=True)
        self.assertEqual((again['upgraded'], again['exchange_requests_mapped'], again['order_action_requests']), (False, 0, 3))
        with transaction(DSN, self.schema) as db:
            rows = {r['request_id']: (r['exchange_kind'], r['target_variant_id'])
                    for r in db.execute('SELECT request_id, exchange_kind, target_variant_id FROM order_action_requests').fetchall()}
            self.assertEqual(db.execute('SELECT version FROM retailops_schema').fetchone()['version'], 7)
        self.assertEqual(rows, {'oar_a': (None, None), 'oar_b': ('other_variant', None), 'oar_c': ('same_variant', None)})
        self.assertEqual(self.constraints() & {'order_action_requests_check1'}, set())
        self.assertTrue({'order_action_requests_exchange_kind_v7_check', 'order_action_requests_target_variant_v7_check'}
                        <= self.constraints())
        PostgresBusinessStore(DSN, self.sessions.control.tenant('shop-a')['storage_key'])  # startup works again

    def test_v7_constraints_reject_malformed_exchange_rows(self):
        from retailops.storage.postgres import transaction
        self.downgrade_to_w3()
        migrate_postgres_business_v7(DSN, preflight_confirmed=True, backup_confirmed=True)
        for kind, target, label in (('size', None, None), ('same_variant', 'V-1', 'Đen / L'),
                                    ('other_variant', 'V-1', None), ('other_variant', 'V-1', 'x' * 201)):
            with self.subTest(kind=kind, target=target), self.assertRaises(ApiError):
                with transaction(DSN, self.schema, write=True) as db:
                    db.execute("UPDATE order_action_requests SET exchange_kind = ?, target_variant_id = ?, "
                               "target_variant_label = ? WHERE request_id = 'oar_b'", (kind, target, label))


if __name__ == '__main__':
    unittest.main()
