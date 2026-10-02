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
        """PostgreSQL Integration: Rollback policy guard and account reconciliation runbook.

        Review Finding (P1/P2):
        - Disabling existing colliding memberships (active=0) is INSUFFICIENT for baseline v1 rollback,
          because baseline v1 binary (c6c7a1a) lacks collision guards and will provision NEW customer
          memberships sharing the same colliding customer_id (e.g. via CG-{hash[:8]}).
        - Policy: Rollback to baseline binaries lacking collision guards is strictly FORBIDDEN.
          Rollback is only safe to images containing collision guards.

        Test Verification:
        1. Setup: Schema at v3 with quarantined customer_id 'CG-rec-shared' and unresolved_collisions entry.
        2. Guard Enforcement: Verify that PostgresIdentityStore (v3) fail-closed blocks any login,
           session creation, or Google OAuth provisioning on colliding customer_ids.
        3. Reconciliation & Reactivation Runbook Execution:
           Step a: Admin identifies collision from unresolved_collisions ('shop-a', 'CG-rec-shared').
           Step b: Admin disambiguates: keeps 'CG-rec-shared' for member 1 ('m-rec-1'), provisions
                   distinct customer_id ('CG-rec-distinct-2') for member 2 ('m-rec-2').
           Step c: Admin updates memberships.customer_id for 'm-rec-2'.
           Step d: Admin creates 1-to-1 customer_links for each member.
           Step e: Admin removes resolved collision from unresolved_collisions table.
           Step f: Admin reactivates memberships: active=1, auth_version=auth_version+1.
        4. Post-Reconciliation Verification:
           - Both members can create sessions and authenticate cleanly.
           - Member 1 session resolves to 'CG-rec-shared'.
           - Member 2 session resolves to 'CG-rec-distinct-2'.
           - Neither membership is blocked with 503 collision_unresolved.
           - Data isolation between the two customer accounts is completely restored.
        """
        with transaction(DSN, write=True) as db:
            # Setup two colliding customer accounts sharing 'CG-rec-shared'
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
                (time.time(),)
            )

        pg_istore = PostgresIdentityStore(DSN, create=False)

        # 1. Guard check: Both members are blocked with 503 collision_unresolved
        with self.assertRaises(ApiError) as ctx1:
            pg_istore.create_session_for_membership('m-rec-1', 3600, 10)
        self.assertEqual(ctx1.exception.status, 503)
        self.assertEqual(ctx1.exception.code, "collision_unresolved")

        with self.assertRaises(ApiError) as ctx2:
            pg_istore.create_session_for_membership('m-rec-2', 3600, 10)
        self.assertEqual(ctx2.exception.status, 503)
        self.assertEqual(ctx2.exception.code, "collision_unresolved")

        # 2. Execute Account Reconciliation & Reactivation Runbook:
        with transaction(DSN, write=True) as db:
            # Step a: Verify collision is detected
            collision_row = db.execute(
                "SELECT * FROM unresolved_collisions WHERE tenant_id='shop-a' AND customer_id='CG-rec-shared'"
            ).fetchone()
            self.assertIsNotNone(collision_row)

            # Step b & c: Disambiguate identities - allocate distinct customer_id for m-rec-2
            db.execute(
                "UPDATE memberships SET customer_id='CG-rec-distinct-2' WHERE id='m-rec-2'"
            )

            # Step d: Establish 1-to-1 customer_links mapping
            db.execute(
                "INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) "
                "VALUES ('cl-rec-1', 'shop-a', 'p-rec-1', 'CG-rec-shared', ?) ON CONFLICT DO NOTHING",
                (time.time(),)
            )
            db.execute(
                "INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) "
                "VALUES ('cl-rec-2', 'shop-a', 'p-rec-2', 'CG-rec-distinct-2', ?) ON CONFLICT DO NOTHING",
                (time.time(),)
            )

            # Step e: Remove resolved collision record from unresolved_collisions
            db.execute(
                "DELETE FROM unresolved_collisions WHERE tenant_id='shop-a' AND customer_id='CG-rec-shared'"
            )

            # Step f: Reactivate both memberships with bumped auth_version
            db.execute(
                "UPDATE memberships SET active=1, auth_version=auth_version+1 WHERE id IN ('m-rec-1', 'm-rec-2')"
            )

        # 3. Post-reconciliation verification
        # Member 1 session creation succeeds
        sid1 = pg_istore.create_session_for_membership('m-rec-1', 3600, 10)
        h1 = hashlib.sha256(sid1.encode()).hexdigest()
        res1 = pg_istore.resolve(h1)
        self.assertIsNotNone(res1)
        self.assertEqual(res1.get('customer_id'), 'CG-rec-shared')
        self.assertEqual(res1.get('id'), 'm-rec-1')

        # Member 2 session creation succeeds with segregated customer_id
        sid2 = pg_istore.create_session_for_membership('m-rec-2', 3600, 10)
        h2 = hashlib.sha256(sid2.encode()).hexdigest()
        res2 = pg_istore.resolve(h2)
        self.assertIsNotNone(res2)
        self.assertEqual(res2.get('customer_id'), 'CG-rec-distinct-2')
        self.assertEqual(res2.get('id'), 'm-rec-2')

        # Both customer IDs are distinct and segregated
        self.assertNotEqual(res1.get('customer_id'), res2.get('customer_id'))


if __name__ == '__main__':
    unittest.main()
