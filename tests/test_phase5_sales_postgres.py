"""P5-C on real PostgreSQL (N2 + cross-store behaviour of N1/N4). Requires a disposable test database.

Set RETAILOPS_TEST_DATABASE_URL to a database whose name starts with retailops_test (same contract as
test_postgres.py). Only RetailOps schemas inside that database are dropped.
"""
import argparse
import os
import tempfile
import unittest
from unittest.mock import patch

import test_persistent_identity as fixtures
from retailops.core import ApiError
from retailops.identity.postgres import PostgresSessions
from retailops.sales.adapter import SalesImportAdapter
from retailops.sales.simulator import DEFAULT_DEV_SECRET, SalesSimulator
from retailops.storage import cli as database_cli
from retailops.storage.pg_repositories import PostgresIdentityStore
from retailops.storage.pg_schema import initialize
from retailops.storage.postgres import IDENTITY_SCHEMA, tenant_schema, transaction

DSN = os.environ.get('RETAILOPS_TEST_DATABASE_URL', '')
P5C_BUSINESS_TABLES = ('order_items', 'imported_events')


@unittest.skipUnless(DSN, 'PostgreSQL integration runs in CI with a dedicated test database.')
class PostgresSalesImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        if not psycopg.conninfo.conninfo_to_dict(DSN).get('dbname', '').startswith('retailops_test'):
            raise ValueError('Refusing to modify a database not named retailops_test*.')

    def clear(self):
        from psycopg import sql
        with transaction(DSN, write=True) as db:
            names = db.execute("SELECT nspname FROM pg_namespace WHERE nspname=? OR nspname ~ '^tenant_[a-f0-9]{32}$'",
                               (IDENTITY_SCHEMA,)).fetchall()
            for row in names:
                db.raw.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(row['nspname'])))

    def setUp(self):
        self.clear()
        self.addCleanup(self.clear)
        PostgresIdentityStore(DSN, create=True)
        self.sessions = PostgresSessions(DSN, api_infer=fixtures.ModelFixture(), api_daily_limit=1)
        self.tenant = 'shop-a'
        self.sessions.provision_tenant(self.tenant, 'Cửa hàng A', seed_demo=True)
        self.sessions.provision_tenant('shop-b', 'Cửa hàng B', seed_demo=True)
        self.simulator = SalesSimulator(tenant_id=self.tenant, secret_key=DEFAULT_DEV_SECRET)
        self.adapter = SalesImportAdapter(self.sessions, default_secret=DEFAULT_DEV_SECRET)
        self.control = self.sessions.control
        self.bstore = self.sessions.business_store(self.tenant)

    # ----- helpers -------------------------------------------------------------------------------------------
    def rows(self, sql, params=(), tenant=None):
        with self.sessions.business_store(tenant or self.tenant).connection() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def traces(self, order_id):
        return {
            'orders': len(self.rows('SELECT 1 FROM orders WHERE id=?', (order_id,))),
            'items': len(self.rows('SELECT 1 FROM order_items WHERE order_id=?', (order_id,))),
            'imported': len(self.rows('SELECT 1 FROM imported_events WHERE order_id=?', (order_id,))),
            'audit': len(self.rows('SELECT 1 FROM business_events WHERE order_id=?', (order_id,))),
        }

    def relation(self, store_connection, name):
        with store_connection as db:
            return db.execute('SELECT to_regclass(?) AS relation', (name,)).fetchone()['relation']

    def tenant_storage_key(self, tenant):
        with self.control.connection() as db:
            return db.execute('SELECT storage_key FROM tenants WHERE id=?', (tenant,)).fetchone()['storage_key']

    def mapping_audits(self):
        with self.control.connection() as db:
            return db.execute("SELECT 1 FROM identity_events WHERE kind='external_customer_mapped'").fetchall()

    def run_cli_migrate(self):
        env = {'RETAILOPS_STORAGE_BACKEND': 'postgresql', 'RETAILOPS_DATABASE_URL': DSN}
        with patch.dict(os.environ, env):
            return database_cli.run(argparse.Namespace(database_action='migrate'))

    # ----- N2: DDL --------------------------------------------------------------------------------------------
    def test_fresh_schema_contains_p5c_tables_with_constraints(self):
        for table in P5C_BUSINESS_TABLES:
            self.assertIsNotNone(self.relation(self.bstore.connection(), table), table)
        self.assertIsNotNone(self.relation(self.control.connection(), 'external_customer_mappings'))
        with self.bstore.connection() as db:
            names = {row['conname'] for row in db.execute(
                "SELECT conname FROM pg_constraint WHERE conrelid IN ('order_items'::regclass, 'imported_events'::regclass)").fetchall()}
        self.assertTrue(any(name.startswith('order_items_quantity') for name in names), names)
        self.assertTrue(any(name.startswith('imported_events_source_system_event_id') for name in names), names)

    def test_legacy_schema_without_p5c_tables_is_migrated_idempotently(self):
        key = self.tenant_storage_key(self.tenant)
        with self.bstore.connection(write=True) as db:
            db.execute('DROP TABLE order_items')
            db.execute('DROP TABLE imported_events')
        with self.control.connection(write=True) as db:
            db.execute('DROP TABLE external_customer_mappings')
        # Constructing the identity store (what `database migrate` does first) recreates its table.
        PostgresIdentityStore(DSN)
        self.assertIsNotNone(self.relation(self.control.connection(), 'external_customer_mappings'))

        for _ in range(2):  # second run proves idempotency
            result = self.run_cli_migrate()
            self.assertEqual(result['result'], 'POSTGRES_MIGRATED')
        for table in P5C_BUSINESS_TABLES:
            self.assertIsNotNone(self.relation(self.bstore.connection(), table), table)
        # Direct initialize() (used by the CLI loop) is also a no-op on a current schema.
        with transaction(DSN, tenant_schema(key), write=True) as db:
            initialize(db, tenant_schema(key), 'business')

    def test_migration_preserves_existing_p5c_rows(self):
        event = self.simulator.create_order_event(order_id='O-PG-MIG-1', external_customer_id='pg_mig_buyer')
        result = self.adapter.ingest_event(event)
        self.run_cli_migrate()
        self.assertEqual(len(self.rows('SELECT 1 FROM imported_events WHERE event_id=?', (event['event_id'],))), 1)
        self.assertEqual(self.control.external_customer_mapping(self.tenant, 'sales_simulator', 'pg_mig_buyer')['customer_id'],
                         result.customer_id)

    def test_money_columns_hold_values_above_32_bits(self):
        big = 5_000_000_000
        event = self.simulator.create_order_event(
            order_id='O-PG-BIG-1', external_customer_id='pg_big_buyer',
            items=[{'product_id': 'P-601', 'product_title': 'Lô hàng lớn', 'quantity': 1, 'unit_price': big}])
        self.adapter.ingest_event(event)
        self.assertEqual(self.rows('SELECT total FROM imported_events WHERE order_id=?', ('O-PG-BIG-1',))[0]['total'], big)
        self.assertEqual(self.rows('SELECT subtotal FROM order_items WHERE order_id=?', ('O-PG-BIG-1',))[0]['subtotal'], big)

    # ----- Adapter behaviour on PostgreSQL ---------------------------------------------------------------------
    def test_import_replay_and_tenant_scoped_mapping(self):
        event = self.simulator.create_order_event(order_id='O-PG-1', external_customer_id='pg_buyer')
        first = self.adapter.ingest_event(event)
        again = self.adapter.ingest_event(event)
        self.assertEqual((first.status, again.status, again.is_replay), ('imported', 'already_processed', True))
        self.assertEqual(self.traces('O-PG-1'), {'orders': 1, 'items': 1, 'imported': 1, 'audit': 1})
        other = SalesSimulator(tenant_id='shop-b', secret_key=DEFAULT_DEV_SECRET).create_order_event(
            order_id='O-PG-1', external_customer_id='pg_buyer')
        other_result = self.adapter.ingest_event(other)
        self.assertNotEqual(other_result.customer_id, first.customer_id)
        self.assertEqual(self.control.external_customer_mapping('shop-b', 'sales_simulator', 'pg_buyer')['customer_id'],
                         other_result.customer_id)
        self.assertEqual(self.traces('O-PG-1')['orders'], 1)  # tenant A untouched by tenant B's import

    def test_n1_other_customer_cannot_take_over_order(self):
        first = self.adapter.ingest_event(self.simulator.create_order_event(order_id='O-PG-OWN', external_customer_id='owner_a'))
        hijack = self.simulator.create_order_event(order_id='O-PG-OWN', external_customer_id='intruder_b', status='cancelled')
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(hijack)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (409, 'order_owner_conflict'))
        self.assertEqual(self.rows('SELECT customer_id, status FROM orders WHERE id=?', ('O-PG-OWN',))[0],
                         {'customer_id': first.customer_id, 'status': 'delivered'})
        self.assertEqual(self.rows('SELECT 1 FROM imported_events WHERE event_id=?', (hijack['event_id'],)), [])
        self.assertIsNone(self.control.external_customer_mapping(self.tenant, 'sales_simulator', 'intruder_b'))
        self.assertEqual(self.traces('O-PG-OWN'), {'orders': 1, 'items': 1, 'imported': 1, 'audit': 1})

    def test_rollback_leaves_no_traces_on_postgresql(self):
        event = self.simulator.create_order_event(
            order_id='O-PG-RB', external_customer_id='pg_rb_buyer',
            items=[{'product_id': 'P-DOES-NOT-EXIST', 'product_title': 'Ghost', 'quantity': 1, 'unit_price': 1000}])
        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(event)  # FK violation on order_items after orders/imported rows were written
        self.assertEqual(ctx.exception.code, 'database_unavailable')
        self.assertEqual(self.traces('O-PG-RB'), {'orders': 0, 'items': 0, 'imported': 0, 'audit': 0})
        self.assertEqual(self.rows('SELECT 1 FROM customers WHERE name=?', ('Khách pg_rb_buyer',)), [])
        self.assertIsNone(self.control.external_customer_mapping(self.tenant, 'sales_simulator', 'pg_rb_buyer'))

    def test_n4_identity_failure_after_commit_recovers_by_replay_and_reconcile(self):
        event = self.simulator.create_order_event(order_id='O-PG-REC', external_customer_id='pg_rec_buyer')
        with patch.object(self.control, 'link_external_customer', side_effect=RuntimeError('identity down')):
            with self.assertRaises(ApiError) as ctx:
                self.adapter.ingest_event(event)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (503, 'identity_mapping_pending'))
        self.assertEqual(self.traces('O-PG-REC'), {'orders': 1, 'items': 1, 'imported': 1, 'audit': 1})
        committed = self.rows('SELECT customer_id FROM imported_events WHERE event_id=?', (event['event_id'],))[0]['customer_id']
        self.assertIsNone(self.control.external_customer_mapping(self.tenant, 'sales_simulator', 'pg_rec_buyer'))

        retry = self.adapter.ingest_event(event)
        self.assertEqual((retry.status, retry.customer_id), ('already_processed', committed))
        self.assertEqual(self.control.external_customer_mapping(self.tenant, 'sales_simulator', 'pg_rec_buyer')['customer_id'], committed)
        self.assertEqual(self.traces('O-PG-REC'), {'orders': 1, 'items': 1, 'imported': 1, 'audit': 1})
        self.assertEqual(len(self.mapping_audits()), 1)
        report = self.adapter.reconcile_mappings(self.tenant)
        self.assertEqual((report['healed'], report['conflicts']), (0, []))

    def test_n4_next_event_after_identity_failure_reuses_customer(self):
        first = self.simulator.create_order_event(order_id='O-PG-REC2', external_customer_id='pg_rec2')
        with patch.object(self.control, 'link_external_customer', side_effect=RuntimeError('identity down')):
            with self.assertRaises(ApiError):
                self.adapter.ingest_event(first)
        committed = self.rows('SELECT customer_id FROM imported_events WHERE event_id=?', (first['event_id'],))[0]['customer_id']
        second = self.adapter.ingest_event(self.simulator.create_order_event(order_id='O-PG-REC3', external_customer_id='pg_rec2'))
        self.assertEqual(second.customer_id, committed)
        self.assertEqual(len(self.rows('SELECT 1 FROM customers WHERE name=?', ('Khách pg_rec2',))), 1)
        self.assertEqual(self.control.external_customer_mapping(self.tenant, 'sales_simulator', 'pg_rec2')['customer_id'], committed)

    def test_link_external_customer_conflict_on_postgresql(self):
        self.assertTrue(self.control.link_external_customer(self.tenant, 'sales_simulator', 'pg_link', 'cust_one')['created'])
        self.assertFalse(self.control.link_external_customer(self.tenant, 'sales_simulator', 'pg_link', 'cust_one')['created'])
        with self.assertRaises(ApiError) as ctx:
            self.control.link_external_customer(self.tenant, 'sales_simulator', 'pg_link', 'cust_two')
        self.assertEqual((ctx.exception.status, ctx.exception.code), (409, 'external_customer_mapping_conflict'))
        self.assertEqual(len(self.mapping_audits()), 1)

    def test_prior_business_import_authoritative_on_postgresql(self):
        first = self.adapter.ingest_event(
            self.simulator.create_order_event(order_id='O-PG-AUTH', external_customer_id='pg_auth')
        )
        with self.assertRaises(ApiError) as ctx:
            self.adapter.link_external_customer(self.tenant, 'sales_simulator', 'pg_auth', 'cust_somebody_else')
        self.assertEqual(ctx.exception.code, 'external_customer_mapping_conflict')

    def test_event_id_collision_rejected_on_postgresql(self):
        event = self.simulator.create_order_event(order_id='O-PG-COL1', external_customer_id='pg_col_a')
        self.adapter.ingest_event(event)

        import copy
        from retailops.sales.events import compute_signature
        tampered = copy.deepcopy(event)
        tampered['external_customer_id'] = 'pg_col_b'
        tampered['signature'] = compute_signature(tampered, DEFAULT_DEV_SECRET)

        with self.assertRaises(ApiError) as ctx:
            self.adapter.ingest_event(tampered)
        self.assertEqual(ctx.exception.code, 'event_id_collision')

    def test_exact_replay_after_300s_heals_mapping_on_postgresql(self):
        from datetime import datetime, timezone
        fixed = 1791720000.0
        iso_time = datetime.fromtimestamp(fixed, tz=timezone.utc).isoformat()
        event = self.simulator.create_order_event(
            order_id='O-PG-DRIFT', external_customer_id='pg_drift', timestamp=iso_time
        )
        with patch.object(self.control, 'link_external_customer', side_effect=RuntimeError('identity down')):
            with self.assertRaises(ApiError):
                self.adapter.ingest_event(event, reference_time=fixed)
        self.assertIsNone(self.control.external_customer_mapping(self.tenant, 'sales_simulator', 'pg_drift'))

        replay = self.adapter.ingest_event(event, reference_time=fixed + 1200.0)
        self.assertTrue(replay.is_replay)
        self.assertEqual(replay.status, 'already_processed')
        self.assertIsNotNone(self.control.external_customer_mapping(self.tenant, 'sales_simulator', 'pg_drift'))


if __name__ == '__main__':
    unittest.main()
