"""Real PostgreSQL integration. Requires an explicitly named disposable test database.

Set RETAILOPS_TEST_DATABASE_URL to a database whose name starts with retailops_test.
The suite drops only RetailOps schemas in that test database, never a normal app DB.
"""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import test_persistent_identity as fixtures
import test_workflows as workflows
from test_knowledge import KnowledgeCases
from retailops.bootstrap import build_public_app
from retailops.config import Settings
from retailops.core import ApiError, ROOT
from retailops.http.public import PublicWeb
from retailops.identity.persistent import PersistentSessions
from retailops.identity.postgres import PostgresSessions
from retailops.storage.import_sqlite import import_snapshot
from retailops.storage.pg_repositories import PostgresIdentityStore
from retailops.storage.postgres import IDENTITY_SCHEMA, tenant_schema, transaction

DSN = os.environ.get('RETAILOPS_TEST_DATABASE_URL', '')


@unittest.skipUnless(DSN, 'PostgreSQL integration runs in CI with a dedicated test database.')
class PostgresTests(KnowledgeCases, workflows.WorkflowCases, unittest.TestCase):
    def fresh_store(self):
        return self.sessions.business_store('shop-a')

    @classmethod
    def setUpClass(cls):
        import psycopg
        if not psycopg.conninfo.conninfo_to_dict(DSN).get('dbname', '').startswith('retailops_test'):
            raise ValueError('Refusing to modify a database not named retailops_test*.')
        with psycopg.connect(DSN) as db:
            db.execute('CREATE SCHEMA IF NOT EXISTS retailops_extensions')
            db.execute('CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA retailops_extensions')

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
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        PostgresIdentityStore(DSN, create=True)
        self.restart()
        self.sessions.provision_tenant('shop-a', 'Cửa hàng A', seed_demo=True)
        self.sessions.provision_tenant('shop-b', 'Cửa hàng B', seed_demo=True)
        self.alice = self.member('alice', 'shop-a', 'C-001')
        self.bob = self.member('bob', 'shop-a', 'C-002')
        self.other = self.member('other', 'shop-b', 'C-001')
        self.viewer = self.member('viewer', 'shop-a', 'C-001', 'viewer')

    def restart(self):
        self.sessions = PostgresSessions(DSN, api_infer=fixtures.ModelFixture(), api_daily_limit=1)
        self.web = PublicWeb(fixtures.ORIGIN, self.sessions)

    request = fixtures.PersistentTests.request
    login = fixtures.PersistentTests.login
    member = fixtures.PersistentTests.member
    cancel = fixtures.PersistentTests.cancel
    # The same HTTP assertions exercise both engines without mocking repository operations.
    test_logout_relogin_restart = fixtures.PersistentTests.test_logout_relogin_restart_keep_order_audit_and_idempotency
    test_scope_isolation = fixtures.PersistentTests.test_tenant_customer_order_proposal_conversation_and_replay_isolation
    test_viewer_permissions = fixtures.PersistentTests.test_viewer_cannot_propose_confirm_dismiss_or_prepare_via_model
    test_role_rotation_revocation = fixtures.PersistentTests.test_role_change_credential_rotation_and_revocation_invalidate_cached_sessions
    test_http_identity_boundary = fixtures.PersistentTests.test_http_cannot_override_membership_and_cookie_is_separate_from_guest
    test_rate_and_quota_persistence = fixtures.PersistentTests.test_bad_login_throttle_and_global_api_limit_survive_restart
    test_credential_delivery = fixtures.PersistentTests.test_credential_file_rotation_is_private_and_existing_file_cannot_revoke

    def test_two_independent_repositories_confirm_once_with_atomic_audit(self):
        store = self.sessions.business_store('shop-a')
        proposal = store.propose('C-001', fixtures.PROPOSAL)
        barrier = threading.Barrier(2)
        def confirm():
            separate = PostgresSessions(DSN).business_store('shop-a')
            barrier.wait(timeout=5)
            return separate.confirm('C-001', proposal['proposal_id'], {'confirmed': True}, 'pg-concurrent-confirm')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: confirm(), range(2)))
        self.assertEqual(sum(bool(r.get('replayed')) for r in results), 1)
        self.assertEqual(store.lookup('C-001', 'O-101')['version'], 2)
        self.assertEqual(sum(e['kind'] == 'order_cancelled' for e in store.events('C-001')), 1)

    def test_two_different_proposals_cannot_cancel_same_order_twice(self):
        store = self.sessions.business_store('shop-a')
        proposals = [store.propose('C-001', fixtures.PROPOSAL) for _ in range(2)]
        barrier = threading.Barrier(2)
        def confirm(index):
            separate = PostgresSessions(DSN).business_store('shop-a')
            barrier.wait(timeout=5)
            try:
                separate.confirm('C-001', proposals[index]['proposal_id'], {'confirmed': True}, 'concurrent-'+str(index)*20)
                return 'ok'
            except ApiError as error:
                return error.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(confirm, range(2))), ['ok', 'stale_order'])
        self.assertEqual(sum(e['kind'] == 'order_cancelled' for e in store.events('C-001')), 1)

    def test_quota_reservation_is_shared_across_process_connections(self):
        barrier = threading.Barrier(2)
        def reserve(_):
            control = PostgresIdentityStore(DSN)
            barrier.wait(timeout=5)
            try:
                control.reserve_api_attempt(1)
                return 'ok'
            except ApiError as error:
                return error.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(reserve, range(2))), ['ok', 'api_daily_limit'])

    def test_parameter_values_are_never_interpreted_as_sql(self):
        text = "O'Brien ? %s; DROP TABLE customers; -- Áo mẫu"
        store = self.sessions.business_store('shop-a')
        store.add_customer('C-quoted', text)
        self.assertEqual(store.customer('C-quoted')['name'], text)
        self.assertEqual(len(store.orders('C-001')), 2)

    def test_expired_sessions_do_not_remove_orders_or_schemas(self):
        alice = self.login(self.alice)
        self.cancel(alice)
        with self.sessions.control.connection(write=True) as db:
            db.execute('UPDATE sessions SET expires_at=0')
        self.sessions.purge()
        self.assertEqual(self.request('/api/orders', cookie=alice)[0], 401)
        self.restart()
        self.assertEqual(self.request('/api/orders/O-101', cookie=self.login(self.alice))[1]['order']['status'], 'cancelled')

    def test_missing_schema_is_not_recreated_by_login_or_request(self):
        from psycopg import sql
        alice = self.login(self.alice)
        self.assertEqual(self.request('/api/orders', cookie=alice)[0], 200)
        schema = tenant_schema(self.sessions.control.tenant('shop-a')['storage_key'])
        with transaction(DSN, write=True) as db:
            db.raw.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        self.assertEqual(self.request('/api/orders', cookie=alice)[0], 503)
        with transaction(DSN) as db:
            self.assertIsNone(db.execute('SELECT 1 FROM pg_namespace WHERE nspname=?', (schema,)).fetchone())

    def make_snapshot(self):
        source = Path(self.temp.name)/'snapshot'
        old = PersistentSessions(source)
        store = old.provision_tenant('old-shop', 'Old shop', seed_demo=True)
        mid = old.create_member('old-shop', 'old-user', 'Old user', 'C-001')
        token = secrets.token_urlsafe(32)
        old.control.register_credential(mid, token)
        cookie = old.cookie_name+'='+old.login(token)
        proposal = store.propose('C-001', fixtures.PROPOSAL)
        store.confirm('C-001', proposal['proposal_id'], {'confirmed': True}, 'import-confirm-key')
        old.control.reserve_api_attempt(1)
        return source, old, token, cookie, proposal

    def test_import_preserves_codes_orders_audit_replay_and_quota_but_not_sessions(self):
        source, old, token, cookie, proposal = self.make_snapshot()
        self.clear()
        report = import_snapshot(DSN, source)
        self.assertEqual(report['sessions_imported'], 0)
        self.restart()
        self.assertEqual(self.request('/api/orders', cookie=cookie)[0], 401)
        current = self.login(('unused', token))
        self.assertEqual(self.request('/api/orders/O-101', cookie=current)[1]['order']['status'], 'cancelled')
        store = self.sessions.business_store('old-shop')
        self.assertTrue(store.confirm('C-001', proposal['proposal_id'], {'confirmed': True}, 'import-confirm-key')['replayed'])
        store.lookup('C-001', 'O-101')  # Sequence repaired: new events cannot collide with imported IDs.
        self.assertEqual(sum(e['kind'] == 'order_cancelled' for e in store.events('C-001')), 1)
        with self.assertRaises(ApiError) as caught:
            self.sessions.control.reserve_api_attempt(1)
        self.assertEqual(caught.exception.code, 'api_daily_limit')
        self.assertEqual(old.business_store('old-shop').orders('C-001')[0]['status'], 'cancelled')
        with self.assertRaises(ValueError):
            import_snapshot(DSN, source)

    def test_import_failure_rolls_back_all_target_schemas_and_records(self):
        source, _, _, _, _ = self.make_snapshot()
        self.clear()
        with patch('retailops.storage.import_sqlite.digest', side_effect=['expected', 'different']), self.assertRaises(ValueError):
            import_snapshot(DSN, source)
        with transaction(DSN) as db:
            self.assertIsNone(db.execute('SELECT 1 FROM pg_namespace WHERE nspname=?', (IDENTITY_SCHEMA,)).fetchone())
        self.assertEqual(import_snapshot(DSN, source)['result'], 'POSTGRES_IMPORT_VERIFIED')

    def test_import_keeps_pending_langgraph_approval_resumable(self):
        from retailops.business.application import Application
        from retailops.http.routes import api_result
        from retailops.workflow import approval
        source = Path(self.temp.name)/'pending-snapshot'
        old = PersistentSessions(source)
        store = old.provision_tenant('old-shop', 'Old shop', seed_demo=True)
        proposal = api_result(Application(store, {}), 'C-001', 'POST', '/api/cancellation-proposals', fixtures.PROPOSAL)[1]
        self.clear()
        report = import_snapshot(DSN, source)
        self.assertTrue(any(k.endswith('.graph_checkpoints') and v['rows'] > 0 for k,v in report['tables'].items()))
        self.restart()
        app = Application(self.sessions.business_store('old-shop'), {})
        result = approval.confirm(app, 'C-001', proposal['proposal_id'], {'confirmed': True}, 'import-graph-confirm')
        self.assertEqual(result['order']['version'], 2)
        self.assertEqual(old.business_store('old-shop').orders('C-001')[0]['status'], 'pending')

    def test_business_v1_migration_is_explicit_preserves_data_and_idempotent(self):
        from retailops.storage.pg_schema import initialize
        store = self.fresh_store()
        with store.connection(write=True) as db:
            for name in ('graph_writes', 'graph_checkpoints', 'graph_runs'):
                db.execute('DROP TABLE '+name)
            db.execute("UPDATE retailops_schema SET version=1 WHERE component='business'")
        with self.assertRaises(ValueError):
            self.fresh_store()
        for _ in range(2):
            with store.connection(write=True) as db:
                initialize(db, store.schema, 'business')
        self.assertEqual(self.fresh_store().orders('C-001')[0]['status'], 'pending')
        with store.connection() as db:
            self.assertEqual(db.execute('SELECT version FROM retailops_schema').fetchone()['version'], 2)

    def test_future_schema_is_rejected_without_downgrade(self):
        with transaction(DSN, write=True) as db:
            db.execute('UPDATE retailops_schema SET version=99')
        with self.assertRaises(ValueError):
            PostgresIdentityStore(DSN, create=True)
        with transaction(DSN) as db:
            self.assertEqual(db.execute('SELECT version FROM retailops_schema').fetchone()['version'], 99)

    def test_failed_transaction_does_not_leave_business_event(self):
        store = self.sessions.business_store('shop-a')
        before = store.events('C-001')
        with self.assertRaises(RuntimeError), store.connection(write=True) as db:
            store.log(db, 'C-001', 'fixture_uncommitted')
            raise RuntimeError('Rollback fixture')
        self.assertEqual(store.events('C-001'), before)

    def test_cli_and_config_file_use_postgres_without_exposing_dsn(self):
        filename = Path(self.temp.name)/'dsn'
        filename.write_text(DSN)
        env = {**os.environ, 'RETAILOPS_STORAGE_BACKEND': 'postgresql', 'RETAILOPS_DATA_MODE': 'persistent-demo',
               'RETAILOPS_DATABASE_URL_FILE': str(filename), 'RETAILOPS_PUBLIC_ORIGIN': fixtures.ORIGIN,
               'RETAILOPS_PUBLIC_CUSTOM_ENABLED': 'false', 'RETAILOPS_API_ENABLED': 'false'}
        env.pop('RETAILOPS_DATABASE_URL', None)
        settings = Settings.from_environment('public', env)
        self.assertNotIn(DSN, repr(settings)+json.dumps(settings.summary()))
        self.assertIsInstance(build_public_app(settings).sessions, PostgresSessions)
        result = subprocess.run([sys.executable, '-m', 'retailops', 'database', 'check'], env=env,
                                cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(DSN, result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
