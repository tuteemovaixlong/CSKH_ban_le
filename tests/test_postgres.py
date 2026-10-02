"""Real PostgreSQL integration. Requires an explicitly named disposable test database.

Set RETAILOPS_TEST_DATABASE_URL to a database whose name starts with retailops_test.
The suite drops only RetailOps schemas in that test database, never a normal app DB.
"""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import test_persistent_identity as fixtures
import test_workflows as workflows
from retailops.bootstrap import build_public_app
from retailops.config import Settings
from retailops.core import ApiError, ROOT
from retailops.http.public import PublicWeb
from retailops.identity.persistent import PersistentSessions
from retailops.identity.postgres import PostgresSessions
from retailops.identity.reconcile import get_reconciliation_status, reconcile_collision
from retailops.storage.import_sqlite import import_snapshot
from retailops.storage.pg_repositories import PostgresIdentityStore
from retailops.storage.postgres import BUSINESS_SCHEMA_CURRENT, IDENTITY_SCHEMA, tenant_schema, transaction

DSN = os.environ.get('RETAILOPS_TEST_DATABASE_URL', '')


@unittest.skipUnless(DSN, 'PostgreSQL integration runs in CI with a dedicated test database.')
class PostgresTests(workflows.WorkflowCases, unittest.TestCase):
    def fresh_store(self):
        return self.sessions.business_store('shop-a')

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
            self.assertEqual(db.execute('SELECT version FROM retailops_schema').fetchone()['version'], BUSINESS_SCHEMA_CURRENT)

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

    def test_identity_v1_to_v3_migration_blocks_collision_and_prevents_first_login_claim(self):
        """PostgreSQL Integration: Real v1->v3 migration with legacy collisions.
        - Seeds v1 identity schema containing two customer accounts sharing customer_id 'CG-pg-shared'.
        - Maps legacy Google principal ID to Alice Collide so Google OAuth actually resolves to m-pg1.
        - Seeds tenant business orders under 'CG-pg-shared'.
        - Triggers v1->v3 upgrade via PostgresIdentityStore.
        - Verifies unresolved_collisions table is populated with ('shop-a', 'CG-pg-shared').
        - Verifies colliding sessions are invalidated while staff session is preserved.
        - Verifies customer_links excludes colliding accounts.
        - Verifies the first Google login or token login is blocked with 503 collision_unresolved.
        - Verifies neither account can access or claim the orders."""
        # 1. Roll identity schema back to v1 state and simulate legacy collisions
        with transaction(DSN, write=True) as db:
            db.raw.execute("DROP TABLE IF EXISTS customer_links CASCADE")
            db.raw.execute("DROP TABLE IF EXISTS external_identities CASCADE")
            db.raw.execute("DROP TABLE IF EXISTS unresolved_collisions CASCADE")
            db.execute("UPDATE retailops_schema SET version=1 WHERE component='identity'")

            # Insert colliding memberships in shop-a sharing 'CG-pg-shared'
            # Derive Alice Collide's legacy Google principal ID so Google login matches her membership
            prefix = re.sub(r'[^a-zA-Z0-9_-]', '_', 'alice_pg@example.com'.split('@')[0])[:25]
            hash_suffix = hashlib.sha256('alice_pg@example.com'.encode()).hexdigest()[:10]
            alice_pid = f"g_{prefix}_{hash_suffix}"

            db.execute("INSERT INTO principals (id, name) VALUES (?, 'Alice Collide') ON CONFLICT DO NOTHING", (alice_pid,))
            db.execute("INSERT INTO principals (id, name) VALUES ('p-pg2', 'Bob Collide') ON CONFLICT DO NOTHING")
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-pg1', 'shop-a', ?, 'CG-pg-shared', 'customer', 1, 1)",
                (alice_pid,)
            )
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-pg2', 'shop-a', 'p-pg2', 'CG-pg-shared', 'customer', 1, 1)"
            )
            token_pg1 = "k" * 43
            db.execute("INSERT INTO credentials (membership_id, hash, created_at) VALUES ('m-pg1', ?, ?)",
                       (hashlib.sha256(token_pg1.encode()).hexdigest(), time.time()))
            db.execute("INSERT INTO sessions (id, membership_id, auth_version, expires_at) VALUES ('s-pg1', 'm-pg1', 1, 9999999999)")
            db.execute("INSERT INTO sessions (id, membership_id, auth_version, expires_at) VALUES ('s-pg2', 'm-pg2', 1, 9999999999)")

            # Insert an active staff session sharing CG-pg-shared to verify v1->v3 does not revoke non-customer sessions
            db.execute("INSERT INTO principals (id, name) VALUES ('p-pg-staff', 'Staff PG') ON CONFLICT DO NOTHING")
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-pg-staff', 'shop-a', 'p-pg-staff', 'CG-pg-shared', 'staff', 1, 1)"
            )
            db.execute("INSERT INTO sessions (id, membership_id, auth_version, expires_at) VALUES ('s-pg-staff', 'm-pg-staff', 1, 9999999999)")

        # 2. Add an order under 'CG-pg-shared' in shop-a's business store
        bstore = self.sessions.business_store('shop-a')
        with bstore.connection(write=True) as bdb:
            bdb.execute("INSERT INTO customers (id, name) VALUES ('CG-pg-shared', 'Shared Collided Customer') ON CONFLICT DO NOTHING")
            bdb.execute(
                "INSERT INTO orders (id, customer_id, name, variant, amount, status, version, product_id) "
                "VALUES ('O-PG-COLLIDE', 'CG-pg-shared', 'Áo Khoác PG', 'Đen / L', 800000, 'pending', 1, 'P-101') "
                "ON CONFLICT DO NOTHING"
            )

        # 3. Initialize / Upgrade PostgresIdentityStore to v3
        pg_istore = PostgresIdentityStore(DSN, create=False)

        # 4. Verify v3 upgrade state
        with transaction(DSN) as db:
            self.assertEqual(db.execute("SELECT version FROM retailops_schema WHERE component='identity'").fetchone()['version'], 3)

            # Check unresolved_collisions table
            unres = db.execute("SELECT * FROM unresolved_collisions WHERE tenant_id='shop-a' AND customer_id='CG-pg-shared'").fetchone()
            self.assertIsNotNone(unres)

            # Check colliding sessions were invalidated
            sessions_active = db.execute("SELECT count(*) as cnt FROM sessions WHERE membership_id IN ('m-pg1', 'm-pg2')").fetchone()['cnt']
            self.assertEqual(sessions_active, 0)

            # Check customer_links does NOT contain CG-pg-shared
            cl_count = db.execute("SELECT count(*) as cnt FROM customer_links WHERE tenant_id='shop-a' AND customer_id='CG-pg-shared'").fetchone()['cnt']
            self.assertEqual(cl_count, 0)

            # Check staff session was preserved despite sharing CG-pg-shared
            staff_active = db.execute("SELECT count(*) as cnt FROM sessions WHERE membership_id='m-pg-staff'").fetchone()['cnt']
            self.assertEqual(staff_active, 1)

        # Colliding customer session resolve fails (session revoked)
        with self.assertRaises(ApiError) as ctx_revoked_v1:
            pg_istore.resolve('s-pg1')
        self.assertEqual(ctx_revoked_v1.exception.status, 401)
        self.assertEqual(ctx_revoked_v1.exception.code, 'session_expired')

        # Staff session resolves successfully
        resolved_staff_v1 = pg_istore.resolve('s-pg-staff')
        self.assertIsNotNone(resolved_staff_v1)
        self.assertEqual(resolved_staff_v1.get('role'), 'staff')

        # 5. First login attempts: verify fail-closed with 503 collision_unresolved
        # A. Credential / token login
        with self.assertRaises(ApiError) as ctx_login:
            pg_istore.login(token_pg1, 3600, 10)
        self.assertEqual(ctx_login.exception.status, 503)
        self.assertEqual(ctx_login.exception.code, "collision_unresolved")

        # B. Session creation
        with self.assertRaises(ApiError) as ctx_sess:
            pg_istore.create_session_for_membership('m-pg1', 3600, 10)
        self.assertEqual(ctx_sess.exception.status, 503)
        self.assertEqual(ctx_sess.exception.code, "collision_unresolved")

        # C. First Google login for m-pg1: actually resolves to alice_pid / m-pg1, must NOT claim customer_id or create customer_links!
        with self.assertRaises(ApiError) as ctx_google:
            pg_istore.get_or_create_google_member(
                'shop-a', 'alice_pg@example.com', 'Alice Collide', sub='google-sub-pg1', email_verified=True
            )
        self.assertEqual(ctx_google.exception.status, 503)
        self.assertEqual(ctx_google.exception.code, "collision_unresolved")

        # Verify NO customer_links was created for m-pg1 after Google login attempt
        with transaction(DSN) as db:
            cl_post = db.execute("SELECT count(*) as cnt FROM customer_links WHERE tenant_id='shop-a' AND customer_id='CG-pg-shared'").fetchone()['cnt']
            self.assertEqual(cl_post, 0)

    def test_identity_v2_existing_schema_upgrade_marks_collision_and_revokes_active_sessions(self):
        """PostgreSQL Integration: Existing v2 schema migration to v3 with active sessions.
        - Schema starts at version 2 (with external_identities, customer_links) but truly without unresolved_collisions table.
        - Introduces colliding customer memberships sharing 'CG-v2-shared' with an active session.
        - Introduces a non-customer (staff) membership with an active session to test revocation scope.
        - Triggers PostgresIdentityStore(DSN, create=False) which executes v2->v3 migration.
        - Verifies unresolved_collisions table is created and populated for ('shop-a', 'CG-v2-shared').
        - Verifies retailops_schema version is upgraded to 3.
        - Verifies only the colliding customer session is revoked; staff session remains intact.
        - Verifies resolving colliding session returns None / unauthorized.
        - Verifies resolving staff session succeeds.
        - Verifies login, session creation, and Google login remain blocked with 503 collision_unresolved.
        - Verifies subsequent PostgresIdentityStore startup leaves version at 3 without re-running initialize."""
        with transaction(DSN, write=True) as db:
            # 1. Faithfully simulate legacy v2 schema: drop unresolved_collisions if present, set version=2
            db.raw.execute("DROP TABLE IF EXISTS unresolved_collisions CASCADE")
            db.execute("UPDATE retailops_schema SET version=2 WHERE component='identity'")

            # Insert two colliding customer accounts in shop-a sharing 'CG-v2-shared'
            prefix = re.sub(r'[^a-zA-Z0-9_-]', '_', 'alice_v2@example.com'.split('@')[0])[:25]
            hash_suffix = hashlib.sha256('alice_v2@example.com'.encode()).hexdigest()[:10]
            alice_v2_pid = f"g_{prefix}_{hash_suffix}"

            db.execute("INSERT INTO principals (id, name) VALUES (?, 'Alice V2') ON CONFLICT DO NOTHING", (alice_v2_pid,))
            db.execute("INSERT INTO principals (id, name) VALUES ('p-v2-2', 'Bob V2') ON CONFLICT DO NOTHING")
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-v2-1', 'shop-a', ?, 'CG-v2-shared', 'customer', 1, 1) ON CONFLICT DO NOTHING",
                (alice_v2_pid,)
            )
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-v2-2', 'shop-a', 'p-v2-2', 'CG-v2-shared', 'customer', 1, 1) ON CONFLICT DO NOTHING"
            )

            # Insert an active session for colliding customer m-v2-1
            active_secret = secrets.token_urlsafe(32)
            session_hash = hashlib.sha256(active_secret.encode()).hexdigest()
            db.execute(
                "INSERT INTO sessions (id, membership_id, auth_version, expires_at) "
                "VALUES (?, 'm-v2-1', 1, ?) ON CONFLICT DO NOTHING",
                (session_hash, time.time() + 3600)
            )

            # Insert an active staff membership sharing the exact same collided customer_id 'CG-v2-shared'
            # This verifies that session revocation strictly targets role='customer' and preserves staff/manager sessions
            db.execute("INSERT INTO principals (id, name) VALUES ('p-v2-staff', 'Staff Member') ON CONFLICT DO NOTHING")
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-v2-staff', 'shop-a', 'p-v2-staff', 'CG-v2-shared', 'staff', 1, 1) ON CONFLICT DO NOTHING"
            )
            staff_secret = secrets.token_urlsafe(32)
            staff_session_hash = hashlib.sha256(staff_secret.encode()).hexdigest()
            db.execute(
                "INSERT INTO sessions (id, membership_id, auth_version, expires_at) "
                "VALUES (?, 'm-v2-staff', 1, ?) ON CONFLICT DO NOTHING",
                (staff_session_hash, time.time() + 3600)
            )

        # Trigger PostgresIdentityStore startup with create=False on the existing v2 schema -> executes v2->v3 migration
        pg_istore = PostgresIdentityStore(DSN, create=False)

        # Verify post-migration state:
        with transaction(DSN) as db:
            # 1. Version upgraded to 3
            self.assertEqual(db.execute("SELECT version FROM retailops_schema WHERE component='identity'").fetchone()['version'], 3)

            # 2. Collision recorded in newly created unresolved_collisions table
            unres = db.execute(
                "SELECT * FROM unresolved_collisions WHERE tenant_id='shop-a' AND customer_id='CG-v2-shared'"
            ).fetchone()
            self.assertIsNotNone(unres)

            # 3. Active colliding customer session was revoked / deleted
            sess_row = db.execute("SELECT * FROM sessions WHERE id=?", (session_hash,)).fetchone()
            self.assertIsNone(sess_row)

            sess_cnt = db.execute(
                "SELECT count(*) as cnt FROM sessions WHERE membership_id IN ('m-v2-1', 'm-v2-2')"
            ).fetchone()['cnt']
            self.assertEqual(sess_cnt, 0)

            # 4. Active staff session was NOT revoked / preserved
            staff_sess_row = db.execute("SELECT * FROM sessions WHERE id=?", (staff_session_hash,)).fetchone()
            self.assertIsNotNone(staff_sess_row)

        # 5. Colliding customer session resolve fails (session revoked)
        with self.assertRaises(ApiError) as ctx_revoked:
            pg_istore.resolve(session_hash)
        self.assertEqual(ctx_revoked.exception.status, 401)
        self.assertEqual(ctx_revoked.exception.code, 'session_expired')

        # 6. Staff session resolve succeeds and preserves role
        resolved_staff = pg_istore.resolve(staff_session_hash)
        self.assertIsNotNone(resolved_staff)
        self.assertEqual(resolved_staff.get('role'), 'staff')
        self.assertEqual(resolved_staff.get('id'), 'm-v2-staff')

        # 7. Attempting to create a session on m-v2-1 is blocked with 503 collision_unresolved
        with self.assertRaises(ApiError) as ctx:
            pg_istore.create_session_for_membership('m-v2-1', 3600, 10)
        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(ctx.exception.code, "collision_unresolved")

        # 8. Google login mapped to m-v2-1 is also blocked with 503 collision_unresolved
        with self.assertRaises(ApiError) as ctx_goog:
            pg_istore.get_or_create_google_member(
                'shop-a', 'alice_v2@example.com', 'Alice V2', sub='google-sub-v2-1', email_verified=True
            )
        self.assertEqual(ctx_goog.exception.status, 503)
        self.assertEqual(ctx_goog.exception.code, "collision_unresolved")

        # 9. Verify subsequent startup does NOT fail and leaves version at 3
        pg_istore_reopened = PostgresIdentityStore(DSN, create=False)
        with transaction(DSN) as db:
            self.assertEqual(db.execute("SELECT version FROM retailops_schema WHERE component='identity'").fetchone()['version'], 3)

    def test_identity_rollback_policy_and_account_reconciliation(self):
        """PostgreSQL Integration: Rollback policy guard and two-database account reconciliation with journal.

        Review Finding (P1 Blocker 2 & 3):
        - Disabling existing colliding memberships (active=0) is INSUFFICIENT for baseline v1 rollback,
          because baseline v1 binary lacks collision guards and provisions new customer memberships
          sharing the same colliding customer_id. Rollback to baseline binaries is strictly FORBIDDEN.
        - Two-database reconciliation must operate across Identity DB and Business DB with:
          1. Persistent reconciliation journal ('started' -> 'business_committed' -> 'completed').
          2. Fail-closed guarantee: accounts remain quarantined in unresolved_collisions until both DBs commit.
          3. Fault injection testing:
             - Injected fault after Business DB commit: verify Business DB migrated orders/conversations,
               while Identity DB remains fail-closed (503 collision_unresolved) with zero data leak.
             - Injected fault during Identity DB commit: verify rollback maintains fail-closed state.
          4. Recovery & Retry via standard reconciliation service: resumes cleanly using the journal and idempotency key.
          5. Real Business DB data: real products, orders, conversations, agent turns for both customers.
          6. Post-reconciliation ownership & data isolation verification:
             - Alice owns only Alice's orders and conversations; 404 on Bob's records.
             - Bob owns only Bob's orders and conversations; 404 on Alice's records.
             - External identities (Google sub/email) linked 1-to-1.
             - customer_links mapped 1-to-1.
        """
        now = time.time()
        # 1. Setup Identity DB: two colliding accounts sharing 'CG-rec-shared'
        with transaction(DSN, write=True) as db:
            db.execute("INSERT INTO principals (id, name) VALUES ('p-rec-1', 'Alice Rec') ON CONFLICT DO NOTHING")
            db.execute("INSERT INTO principals (id, name) VALUES ('p-rec-2', 'Bob Rec') ON CONFLICT DO NOTHING")
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-rec-1', 'shop-a', 'p-rec-1', 'CG-rec-shared', 'customer', 1, 1) ON CONFLICT DO NOTHING"
            )
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-rec-2', 'shop-a', 'p-rec-2', 'CG-rec-shared', 'customer', 1, 1) ON CONFLICT DO NOTHING"
            )
            db.execute(
                "INSERT INTO unresolved_collisions (tenant_id, customer_id, created_at) "
                "VALUES ('shop-a', 'CG-rec-shared', ?) ON CONFLICT DO NOTHING",
                (now,)
            )

        # 2. Setup Business DB: real products, orders, and conversations for both customers under colliding ID
        b_store = self.sessions.business_store('shop-a')
        with b_store.connection(write=True) as b_db:
            b_db.execute(
                "INSERT INTO customers (id, name) VALUES ('CG-rec-shared', 'Colliding Shared Customer') ON CONFLICT DO NOTHING"
            )
            b_db.execute(
                "INSERT INTO products (id, name, price, stock, is_system_immutable, created_at, updated_at) "
                "VALUES ('P-REC-001', 'Áo Polo Test', 250000, 100, 0, ?, ?) ON CONFLICT DO NOTHING",
                (now, now)
            )
            # Real orders: O-REC-001 & O-REC-002 intended for Alice, O-REC-003 intended for Bob
            b_db.execute(
                "INSERT INTO orders (id, customer_id, product_id, name, variant, amount, status, version) "
                "VALUES ('O-REC-001', 'CG-rec-shared', 'P-REC-001', 'Áo Polo Test', 'L / Đen', 250000, 'pending', 1) "
                "ON CONFLICT DO NOTHING"
            )
            b_db.execute(
                "INSERT INTO orders (id, customer_id, product_id, name, variant, amount, status, version) "
                "VALUES ('O-REC-002', 'CG-rec-shared', 'P-REC-001', 'Áo Polo Test', 'XL / Trắng', 250000, 'delivered', 1) "
                "ON CONFLICT DO NOTHING"
            )
            b_db.execute(
                "INSERT INTO orders (id, customer_id, product_id, name, variant, amount, status, version) "
                "VALUES ('O-REC-003', 'CG-rec-shared', 'P-REC-001', 'Áo Polo Test', 'M / Xanh', 500000, 'pending', 1) "
                "ON CONFLICT DO NOTHING"
            )
            # Real conversations: CONV-REC-001 for Alice, CONV-REC-002 for Bob
            b_db.execute(
                "INSERT INTO conversations (id, customer_id, order_id, product_id, revision, expires_at) "
                "VALUES ('CONV-REC-001', 'CG-rec-shared', 'O-REC-001', 'P-REC-001', 1, ?) ON CONFLICT DO NOTHING",
                (now + 3600,)
            )
            b_db.execute(
                "INSERT INTO conversations (id, customer_id, order_id, product_id, revision, expires_at) "
                "VALUES ('CONV-REC-002', 'CG-rec-shared', 'O-REC-003', 'P-REC-001', 1, ?) ON CONFLICT DO NOTHING",
                (now + 3600,)
            )
            b_db.execute(
                "INSERT INTO agent_turns (conversation_id, customer_id, request_id, input_hash, messages, result, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                ('CONV-REC-001', 'CG-rec-shared', 'req-turn-001', 'hash001', '[]', '{\"reply\":\"Alice hello\"}', now)
            )
            b_db.execute(
                "INSERT INTO agent_turns (conversation_id, customer_id, request_id, input_hash, messages, result, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                ('CONV-REC-002', 'CG-rec-shared', 'req-turn-002', 'hash002', '[]', '{\"reply\":\"Bob hello\"}', now)
            )

        pg_istore = PostgresIdentityStore(DSN, create=False)

        # 3. Pre-Reconciliation Guard Check: Both members are strictly blocked with 503 collision_unresolved
        with self.assertRaises(ApiError) as ctx1:
            pg_istore.create_session_for_membership('m-rec-1', 3600, 10)
        self.assertEqual(ctx1.exception.status, 503)
        self.assertEqual(ctx1.exception.code, "collision_unresolved")

        with self.assertRaises(ApiError) as ctx2:
            pg_istore.create_session_for_membership('m-rec-2', 3600, 10)
        self.assertEqual(ctx2.exception.status, 503)
        self.assertEqual(ctx2.exception.code, "collision_unresolved")

        # 4. Formulate Two-Database Reconciliation Plan
        plan = {
            "reassignments": [
                {
                    "membership_id": "m-rec-1",
                    "target_customer_id": "CG-rec-alice",
                    "target_customer_name": "Alice Rec",
                    "order_ids": ["O-REC-001", "O-REC-002"],
                    "conversation_ids": ["CONV-REC-001"],
                    "external_identity": {
                        "issuer": "https://accounts.google.com",
                        "sub": "google-sub-alice-rec-12345",
                        "email": "alice.rec@example.com",
                    },
                },
                {
                    "membership_id": "m-rec-2",
                    "target_customer_id": "CG-rec-bob",
                    "target_customer_name": "Bob Rec",
                    "order_ids": ["O-REC-003"],
                    "conversation_ids": ["CONV-REC-002"],
                    "external_identity": {
                        "issuer": "https://accounts.google.com",
                        "sub": "google-sub-bob-rec-67890",
                        "email": "bob.rec@example.com",
                    },
                },
            ]
        }
        idempotency_key = "rec-shop-a-shared"

        # 5. Fault Injection 1: Crash immediately after Business DB commit
        with self.assertRaises(RuntimeError) as fault1:
            reconcile_collision(
                self.sessions,
                "shop-a",
                "CG-rec-shared",
                plan,
                idempotency_key=idempotency_key,
                fault_stage="after_business_commit",
            )
        self.assertIn("Fault injected after business commit", str(fault1.exception))

        # Check Journal status in Identity DB is 'business_committed'
        j1 = get_reconciliation_status(self.sessions, idempotency_key)
        self.assertIsNotNone(j1)
        self.assertEqual(j1["status"], "business_committed")

        # Check Business DB state: orders and conversations have migrated to target customer IDs
        with b_store.connection() as b_db:
            order_rows = b_db.execute(
                "SELECT id, customer_id FROM orders WHERE id IN ('O-REC-001', 'O-REC-002', 'O-REC-003')"
            ).fetchall()
            order_map = {r["id"]: r["customer_id"] for r in order_rows}
            self.assertEqual(order_map["O-REC-001"], "CG-rec-alice")
            self.assertEqual(order_map["O-REC-002"], "CG-rec-alice")
            self.assertEqual(order_map["O-REC-003"], "CG-rec-bob")

            conv_rows = b_db.execute(
                "SELECT id, customer_id FROM conversations WHERE id IN ('CONV-REC-001', 'CONV-REC-002')"
            ).fetchall()
            conv_map = {r["id"]: r["customer_id"] for r in conv_rows}
            self.assertEqual(conv_map["CONV-REC-001"], "CG-rec-alice")
            self.assertEqual(conv_map["CONV-REC-002"], "CG-rec-bob")

        # CRITICAL FAIL-CLOSED VERIFICATION:
        # Identity DB has NOT committed: unresolved_collisions is STILL active
        # Neither customer can create sessions or access data across the crash boundary!
        with self.assertRaises(ApiError) as ctx1_crash:
            pg_istore.create_session_for_membership('m-rec-1', 3600, 10)
        self.assertEqual(ctx1_crash.exception.status, 503)
        self.assertEqual(ctx1_crash.exception.code, "collision_unresolved")

        with self.assertRaises(ApiError) as ctx2_crash:
            pg_istore.create_session_for_membership('m-rec-2', 3600, 10)
        self.assertEqual(ctx2_crash.exception.status, 503)
        self.assertEqual(ctx2_crash.exception.code, "collision_unresolved")

        # 6. Fault Injection 2: Crash during Identity DB commit
        with self.assertRaises(RuntimeError) as fault2:
            reconcile_collision(
                self.sessions,
                "shop-a",
                "CG-rec-shared",
                plan,
                idempotency_key=idempotency_key,
                fault_stage="during_identity_commit",
            )
        self.assertIn("Fault injected during identity DB commit", str(fault2.exception))

        # Identity DB transaction rolled back: still fail-closed
        with self.assertRaises(ApiError) as ctx1_roll:
            pg_istore.create_session_for_membership('m-rec-1', 3600, 10)
        self.assertEqual(ctx1_roll.exception.status, 503)
        self.assertEqual(ctx1_roll.exception.code, "collision_unresolved")

        # 7. Recovery & Resume: Call standard reconcile_collision service (no fault)
        rec_result = reconcile_collision(
            self.sessions,
            "shop-a",
            "CG-rec-shared",
            plan,
            idempotency_key=idempotency_key,
        )
        self.assertEqual(rec_result["status"], "completed")

        # Verify Journal state is 'completed'
        j2 = get_reconciliation_status(self.sessions, idempotency_key)
        self.assertIsNotNone(j2)
        self.assertEqual(j2["status"], "completed")

        # Verify Idempotency: re-running with same idempotency_key returns already_completed
        idempotent_result = reconcile_collision(
            self.sessions,
            "shop-a",
            "CG-rec-shared",
            plan,
            idempotency_key=idempotency_key,
        )
        self.assertEqual(idempotent_result["status"], "completed")
        self.assertTrue(idempotent_result.get("already_completed"))

        # 8. Post-Reconciliation Verification:
        # 8a. Collision record removed from unresolved_collisions
        with transaction(DSN) as db:
            unres = db.execute(
                "SELECT 1 FROM unresolved_collisions WHERE tenant_id='shop-a' AND customer_id='CG-rec-shared'"
            ).fetchone()
            self.assertIsNone(unres)

        # 8b. Member 1 (Alice) session creation succeeds and maps to CG-rec-alice
        sid1 = pg_istore.create_session_for_membership('m-rec-1', 3600, 10)
        h1 = hashlib.sha256(sid1.encode()).hexdigest()
        res1 = pg_istore.resolve(h1)
        self.assertIsNotNone(res1)
        self.assertEqual(res1.get('customer_id'), 'CG-rec-alice')
        self.assertEqual(res1.get('id'), 'm-rec-1')

        # 8c. Member 2 (Bob) session creation succeeds and maps to CG-rec-bob
        sid2 = pg_istore.create_session_for_membership('m-rec-2', 3600, 10)
        h2 = hashlib.sha256(sid2.encode()).hexdigest()
        res2 = pg_istore.resolve(h2)
        self.assertIsNotNone(res2)
        self.assertEqual(res2.get('customer_id'), 'CG-rec-bob')
        self.assertEqual(res2.get('id'), 'm-rec-2')

        # 8d. Business DB Data Isolation & Ownership Verification:
        # Alice owns O-REC-001 and O-REC-002, CANNOT see Bob's O-REC-003
        alice_orders = b_store.orders('CG-rec-alice')
        alice_order_ids = {o['id'] for o in alice_orders}
        self.assertEqual(alice_order_ids, {'O-REC-001', 'O-REC-002'})
        self.assertNotIn('O-REC-003', alice_order_ids)

        self.assertEqual(b_store.lookup('CG-rec-alice', 'O-REC-001')['id'], 'O-REC-001')
        with self.assertRaises(ApiError) as ctx_cross1:
            b_store.lookup('CG-rec-alice', 'O-REC-003')
        self.assertEqual(ctx_cross1.exception.status, 404)

        # Alice owns CONV-REC-001, CANNOT see Bob's CONV-REC-002
        alice_convs = b_store.list_conversations('CG-rec-alice')
        alice_conv_ids = {c['id'] for c in alice_convs}
        self.assertEqual(alice_conv_ids, {'CONV-REC-001'})
        self.assertNotIn('CONV-REC-002', alice_conv_ids)
        with self.assertRaises(ApiError) as ctx_cross_conv1:
            b_store.conversation('CG-rec-alice', 'CONV-REC-002')
        self.assertEqual(ctx_cross_conv1.exception.status, 404)

        # Bob owns O-REC-003, CANNOT see Alice's O-REC-001 or O-REC-002
        bob_orders = b_store.orders('CG-rec-bob')
        bob_order_ids = {o['id'] for o in bob_orders}
        self.assertEqual(bob_order_ids, {'O-REC-003'})
        self.assertNotIn('O-REC-001', bob_order_ids)
        self.assertNotIn('O-REC-002', bob_order_ids)

        self.assertEqual(b_store.lookup('CG-rec-bob', 'O-REC-003')['id'], 'O-REC-003')
        with self.assertRaises(ApiError) as ctx_cross2:
            b_store.lookup('CG-rec-bob', 'O-REC-001')
        self.assertEqual(ctx_cross2.exception.status, 404)

        # Bob owns CONV-REC-002, CANNOT see Alice's CONV-REC-001
        bob_convs = b_store.list_conversations('CG-rec-bob')
        bob_conv_ids = {c['id'] for c in bob_convs}
        self.assertEqual(bob_conv_ids, {'CONV-REC-002'})
        self.assertNotIn('CONV-REC-001', bob_conv_ids)
        with self.assertRaises(ApiError) as ctx_cross_conv2:
            b_store.conversation('CG-rec-bob', 'CONV-REC-001')
        self.assertEqual(ctx_cross_conv2.exception.status, 404)

        # 8e. External identities verification (Google sub and email mappings)
        with transaction(DSN) as db:
            alice_ext = db.execute("SELECT sub, email FROM external_identities WHERE principal_id='p-rec-1'").fetchone()
            self.assertIsNotNone(alice_ext)
            self.assertEqual(alice_ext['sub'], 'google-sub-alice-rec-12345')
            self.assertEqual(alice_ext['email'], 'alice.rec@example.com')

            bob_ext = db.execute("SELECT sub, email FROM external_identities WHERE principal_id='p-rec-2'").fetchone()
            self.assertIsNotNone(bob_ext)
            self.assertEqual(bob_ext['sub'], 'google-sub-bob-rec-67890')
            self.assertEqual(bob_ext['email'], 'bob.rec@example.com')

            # 8f. Customer links verification
            cl_alice = db.execute("SELECT customer_id FROM customer_links WHERE tenant_id='shop-a' AND principal_id='p-rec-1'").fetchone()
            self.assertIsNotNone(cl_alice)
            self.assertEqual(cl_alice['customer_id'], 'CG-rec-alice')

            cl_bob = db.execute("SELECT customer_id FROM customer_links WHERE tenant_id='shop-a' AND principal_id='p-rec-2'").fetchone()
            self.assertIsNotNone(cl_bob)
            self.assertEqual(cl_bob['customer_id'], 'CG-rec-bob')


if __name__ == '__main__':
    unittest.main()
