"""Integration event import on real PostgreSQL (migrated from P5-C onto v2 in W6.1b-1). Requires a disposable test database.

Set RETAILOPS_TEST_DATABASE_URL to the explicit loopback database named exactly retailops_test and set
RETAILOPS_ALLOW_DESTRUCTIVE_TEST_DATABASE=1. Only RetailOps schemas inside that database are dropped.
"""
import argparse
import copy
import os
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_persistent_identity as fixtures
from retailops.core import ApiError
from retailops.identity.postgres import PostgresSessions
from retailops.integration.ingest import IntegrationIngestService
from retailops.integration.recipient_crypto import RecipientKeyring
from retailops.storage import cli as database_cli
from retailops.storage.pg_repositories import PostgresBusinessStore, PostgresIdentityStore
from retailops.storage.pg_schema import initialize
from retailops.storage.postgres import IDENTITY_SCHEMA, tenant_schema, transaction
from scripts.postgres_test_guard import require_disposable_postgres_test_target

DSN = os.environ.get('RETAILOPS_TEST_DATABASE_URL', '')
P5C_BUSINESS_TABLES = ('order_items', 'imported_events')
TEST_DIGEST_KEY = b'test-digest-key-32-bytes-minimum!!'
TEST_RECIPIENT_KEYRING = RecipientKeyring.from_raw_keys(
    {'v1': b'test-recipient-key-32-bytes-min!'}, 'v1'
)


def make_pg_order_created(
    *,
    external_order_id: str,
    external_customer_id: str,
    items: list | None = None,
    event_id: str | None = None,
    sequence: int = 1,
) -> dict:
    resolved_items = items or [
        {
            'sku': 'SKU-P601-WHT-M',
            'external_product_id': 'P-601',
            'title': 'Áo sơ mi lụa công sở',
            'variant_name': 'Trắng / M',
            'quantity': 1,
            'unit_price': 450000,
        }
    ]
    total = sum(int(i['quantity']) * int(i['unit_price']) for i in resolved_items)
    return {
        'contract': 'retailops-integration-v2',
        'event_id': event_id or f'evt_pg_{uuid.uuid4().hex[:18]}',
        'event_type': 'order.created',
        'source_system': 'marketplace_sim',
        'merchant_id': 'shop-pg',
        'occurred_at': '2026-11-01T10:00:00+07:00',
        'sequence': sequence,
        'data': {
            'external_order_id': external_order_id,
            'external_customer_id': external_customer_id,
            'ordered_at': '2026-11-01T10:00:00+07:00',
            'items': resolved_items,
            'shipping_fee': 0,
            'total': total,
            'currency': 'VND',
            'payment_method': 'cod',
            'promised_delivery_by': '2026-11-04T10:00:00+07:00',
            'recipient': {
                'name': 'Nguyễn Văn Thử',
                'phone': '0901234567',
                'address_line': '123 Đường Mẫu',
                'ward': 'Phường Bến Nghé',
                'district': 'Quận 1',
                'province': 'TP. Hồ Chí Minh',
            },
        },
    }


@unittest.skipUnless(DSN, 'PostgreSQL integration runs in CI with a dedicated test database.')
class PostgresSalesImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        require_disposable_postgres_test_target(DSN, psycopg.conninfo.conninfo_to_dict)

    def clear(self):
        from psycopg import sql
        with transaction(DSN, write=True) as db:
            names = db.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname=? OR nspname ~ '^tenant_[a-f0-9]{32}$'",
                (IDENTITY_SCHEMA,),
            ).fetchall()
            for row in names:
                db.raw.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(row['nspname'])))

    def setUp(self):
        self.clear()
        self.addCleanup(self.clear)
        PostgresIdentityStore(DSN, create=True)
        self.sessions = PostgresSessions(DSN, api_infer=fixtures.ModelFixture(), api_daily_limit=1)
        self.tenant = 'shop-a'
        store_a = self.sessions.provision_tenant(self.tenant, 'Cửa hàng A', seed_demo=False)
        store_a.seed_catalog()
        store_b = self.sessions.provision_tenant('shop-b', 'Cửa hàng B', seed_demo=False)
        store_b.seed_catalog()
        self.service = IntegrationIngestService(
            self.sessions, digest_key=TEST_DIGEST_KEY, recipient_keyring=TEST_RECIPIENT_KEYRING
        )
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
            names = {
                row['conname']
                for row in db.execute(
                    "SELECT conname FROM pg_constraint WHERE conrelid IN ('order_items'::regclass, 'imported_events'::regclass)"
                ).fetchall()
            }
        self.assertTrue(any(name.startswith('order_items_quantity') for name in names), names)
        self.assertTrue(any(name.startswith('imported_events_source_system_event_id') for name in names), names)

    def test_legacy_schema_without_p5c_tables_is_migrated_idempotently(self):
        key = self.tenant_storage_key(self.tenant)
        with self.bstore.connection(write=True) as db:
            db.execute('DROP TABLE order_items')
            db.execute('DROP TABLE imported_events')
        with self.control.connection(write=True) as db:
            db.execute('DROP TABLE external_customer_mappings')
        PostgresIdentityStore(DSN)
        self.assertIsNotNone(self.relation(self.control.connection(), 'external_customer_mappings'))

        for _ in range(2):
            result = self.run_cli_migrate()
            self.assertEqual(result['result'], 'POSTGRES_MIGRATED')
        for table in P5C_BUSINESS_TABLES:
            self.assertIsNotNone(self.relation(self.bstore.connection(), table), table)
        with transaction(DSN, tenant_schema(key), write=True) as db:
            initialize(db, tenant_schema(key), 'business')

    def test_migration_preserves_existing_p5c_rows(self):
        event = make_pg_order_created(external_order_id='SIM-O-PG-MIG-1', external_customer_id='pg_mig_buyer')
        result = self.service.ingest_event(event, tenant_id=self.tenant)
        self.run_cli_migrate()
        self.assertEqual(
            len(self.rows('SELECT 1 FROM imported_events WHERE event_id=?', (event['event_id'],))), 1
        )
        self.assertEqual(
            self.control.external_customer_mapping(self.tenant, 'marketplace_sim', 'pg_mig_buyer')['customer_id'],
            result.customer_id,
        )

    def test_money_columns_hold_values_above_32_bits(self):
        big = 5_000_000_000
        event = make_pg_order_created(
            external_order_id='SIM-O-PG-BIG-1',
            external_customer_id='pg_big_buyer',
            items=[
                {
                    'sku': 'SKU-P601-BIG',
                    'external_product_id': 'P-601',
                    'title': 'Lô hàng lớn',
                    'variant_name': 'Tiêu chuẩn',
                    'quantity': 1,
                    'unit_price': big,
                }
            ],
        )
        res = self.service.ingest_event(event, tenant_id=self.tenant)
        self.assertEqual(
            self.rows('SELECT total FROM imported_events WHERE order_id=?', (res.order_id,))[0]['total'], big
        )
        self.assertEqual(
            self.rows('SELECT subtotal FROM order_items WHERE order_id=?', (res.order_id,))[0]['subtotal'], big
        )

    # ----- Service behaviour on PostgreSQL --------------------------------------------------------------------
    def test_import_replay_and_tenant_scoped_mapping(self):
        event = make_pg_order_created(external_order_id='SIM-O-PG-1', external_customer_id='pg_buyer')
        first = self.service.ingest_event(event, tenant_id=self.tenant)
        again = self.service.ingest_event(event, tenant_id=self.tenant)
        self.assertEqual((first.status, again.status, again.is_replay), ('imported', 'already_processed', True))
        self.assertEqual(self.traces(first.order_id), {'orders': 1, 'items': 1, 'imported': 1, 'audit': 1})
        other = make_pg_order_created(external_order_id='SIM-O-PG-1', external_customer_id='pg_buyer')
        other_result = self.service.ingest_event(other, tenant_id='shop-b')
        self.assertNotEqual(other_result.customer_id, first.customer_id)
        self.assertEqual(
            self.control.external_customer_mapping('shop-b', 'marketplace_sim', 'pg_buyer')['customer_id'],
            other_result.customer_id,
        )
        self.assertEqual(self.traces(first.order_id)['orders'], 1)

    def test_n1_other_customer_cannot_take_over_order(self):
        first = self.service.ingest_event(
            make_pg_order_created(external_order_id='SIM-O-PG-OWN', external_customer_id='owner_a'),
            tenant_id=self.tenant,
        )
        hijack = make_pg_order_created(
            external_order_id='SIM-O-PG-OWN', external_customer_id='intruder_b', sequence=2
        )
        with self.assertRaises(ApiError) as ctx:
            self.service.ingest_event(hijack, tenant_id=self.tenant)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (409, 'order_owner_conflict'))
        self.assertEqual(
            self.rows('SELECT customer_id, status FROM orders WHERE id=?', (first.order_id,))[0],
            {'customer_id': first.customer_id, 'status': 'pending'},
        )
        self.assertEqual(self.rows('SELECT 1 FROM imported_events WHERE event_id=?', (hijack['event_id'],)), [])
        self.assertIsNone(self.control.external_customer_mapping(self.tenant, 'marketplace_sim', 'intruder_b'))
        self.assertEqual(self.traces(first.order_id), {'orders': 1, 'items': 1, 'imported': 1, 'audit': 1})

    def test_rollback_leaves_no_traces_on_postgresql(self):
        from contextlib import contextmanager

        event = make_pg_order_created(
            external_order_id='SIM-O-PG-RB',
            external_customer_id='pg_rb_buyer',
        )
        orig_conn = PostgresBusinessStore.connection

        class FaultyPgProxy:
            def __init__(self, real_db):
                self._real_db = real_db

            def execute(self, sql, *args, **kwargs):
                if 'INSERT INTO order_items' in sql:
                    return self._real_db.execute('SELECT 1 / 0')
                return self._real_db.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._real_db, name)

        @contextmanager
        def faulty_conn(store_self, *args, **kwargs):
            with orig_conn(store_self, *args, **kwargs) as real_db:
                yield FaultyPgProxy(real_db)

        with patch.object(PostgresBusinessStore, 'connection', faulty_conn):
            with self.assertRaises(ApiError) as ctx:
                self.service.ingest_event(event, tenant_id=self.tenant)
        self.assertEqual(ctx.exception.code, 'database_unavailable')
        self.assertEqual(
            self.rows("SELECT 1 FROM orders WHERE external_order_id='SIM-O-PG-RB'"), []
        )
        self.assertEqual(
            self.rows('SELECT 1 FROM imported_events WHERE event_id=?', (event['event_id'],)), []
        )
        self.assertEqual(self.rows('SELECT 1 FROM customers WHERE name=?', ('Khách pg_rb_buyer',)), [])
        self.assertIsNone(self.control.external_customer_mapping(self.tenant, 'marketplace_sim', 'pg_rb_buyer'))

    def test_n4_identity_failure_after_commit_recovers_by_replay_and_reconcile(self):
        event = make_pg_order_created(external_order_id='SIM-O-PG-REC', external_customer_id='pg_rec_buyer')
        with patch.object(self.control, 'link_external_customer', side_effect=RuntimeError('identity down')):
            with self.assertRaises(ApiError) as ctx:
                self.service.ingest_event(event, tenant_id=self.tenant)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (503, 'identity_mapping_pending'))
        imp_row = self.rows(
            'SELECT order_id, customer_id FROM imported_events WHERE event_id=?', (event['event_id'],)
        )[0]
        oid = imp_row['order_id']
        committed = imp_row['customer_id']
        self.assertEqual(self.traces(oid), {'orders': 1, 'items': 1, 'imported': 1, 'audit': 1})
        self.assertIsNone(self.control.external_customer_mapping(self.tenant, 'marketplace_sim', 'pg_rec_buyer'))

        retry = self.service.ingest_event(event, tenant_id=self.tenant)
        self.assertEqual((retry.status, retry.customer_id), ('already_processed', committed))
        self.assertEqual(
            self.control.external_customer_mapping(self.tenant, 'marketplace_sim', 'pg_rec_buyer')['customer_id'],
            committed,
        )
        self.assertEqual(self.traces(oid), {'orders': 1, 'items': 1, 'imported': 1, 'audit': 1})
        self.assertEqual(len(self.mapping_audits()), 1)
        report = self.service.reconcile_mappings(self.tenant)
        self.assertEqual((report['healed'], report['conflicts']), (0, []))

    def test_n4_next_event_after_identity_failure_reuses_customer(self):
        first = make_pg_order_created(external_order_id='SIM-O-PG-REC2', external_customer_id='pg_rec2')
        with patch.object(self.control, 'link_external_customer', side_effect=RuntimeError('identity down')):
            with self.assertRaises(ApiError):
                self.service.ingest_event(first, tenant_id=self.tenant)
        committed = self.rows(
            'SELECT customer_id FROM imported_events WHERE event_id=?', (first['event_id'],)
        )[0]['customer_id']
        second = self.service.ingest_event(
            make_pg_order_created(external_order_id='SIM-O-PG-REC3', external_customer_id='pg_rec2'),
            tenant_id=self.tenant,
        )
        self.assertEqual(second.customer_id, committed)
        self.assertEqual(len(self.rows('SELECT 1 FROM customers WHERE name=?', ('Khách pg_rec2',))), 1)
        self.assertEqual(
            self.control.external_customer_mapping(self.tenant, 'marketplace_sim', 'pg_rec2')['customer_id'],
            committed,
        )

    def test_link_external_customer_conflict_on_postgresql(self):
        self.assertTrue(
            self.control.link_external_customer(self.tenant, 'marketplace_sim', 'pg_link', 'cust_one')['created']
        )
        self.assertFalse(
            self.control.link_external_customer(self.tenant, 'marketplace_sim', 'pg_link', 'cust_one')['created']
        )
        with self.assertRaises(ApiError) as ctx:
            self.control.link_external_customer(self.tenant, 'marketplace_sim', 'pg_link', 'cust_two')
        self.assertEqual(
            (ctx.exception.status, ctx.exception.code), (409, 'external_customer_mapping_conflict')
        )
        self.assertEqual(len(self.mapping_audits()), 1)

    def test_prior_business_import_authoritative_on_postgresql(self):
        self.service.ingest_event(
            make_pg_order_created(external_order_id='SIM-O-PG-AUTH', external_customer_id='pg_auth'),
            tenant_id=self.tenant,
        )
        with self.assertRaises(ApiError) as ctx:
            self.service.link_external_customer(
                self.tenant, 'marketplace_sim', 'pg_auth', 'cust_somebody_else'
            )
        self.assertEqual(ctx.exception.code, 'external_customer_mapping_conflict')

    def test_event_id_collision_rejected_on_postgresql(self):
        event = make_pg_order_created(external_order_id='SIM-O-PG-COL1', external_customer_id='pg_col_a')
        self.service.ingest_event(event, tenant_id=self.tenant)

        tampered = copy.deepcopy(event)
        tampered['data']['external_customer_id'] = 'pg_col_b'

        with self.assertRaises(ApiError) as ctx:
            self.service.ingest_event(tampered, tenant_id=self.tenant)
        self.assertEqual(ctx.exception.code, 'event_id_collision')


if __name__ == '__main__':
    unittest.main()
