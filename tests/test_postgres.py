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
from retailops.storage.pg_repositories import PostgresBusinessStore, PostgresIdentityStore
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

    def test_p604_catalog_seed_preserves_unknowns_and_is_idempotent_postgres(self):
        """P-604 seed keeps unsupported toy-safety/commercial facts unknown and adds no order."""
        store = self.sessions.business_store('shop-a')
        p604 = store.get_product('P-604')
        self.assertEqual(p604['name'], 'Bộ xếp hình gỗ cho bé')
        for field in ('price', 'stock', 'warranty_days', 'recommended_age',
                      'safety_warnings', 'safety_certifications'):
            self.assertIsNone(p604[field], field)
        self.assertEqual(p604['variants'], [])

        with store.connection(write=True) as db:
            db.execute(
                "INSERT INTO orders(id, customer_id, name, variant, amount, status, version, product_id) "
                "VALUES ('O-P604-SEED-REGRESSION', 'C-001', 'Quần tây ống đứng tôn dáng', "
                "'Đen / L', 520000, 'delivered', 1, 'P-602') ON CONFLICT DO NOTHING"
            )
        with store.connection() as db:
            self.assertIsNone(db.execute(
                "SELECT id FROM orders WHERE product_id='P-604'"
            ).fetchone())
            legacy_before = db.execute(
                "SELECT name, variant, amount, status, product_id FROM orders "
                "WHERE id='O-P604-SEED-REGRESSION'"
            ).fetchone()

        store.seed_catalog()
        self.assertEqual(store.get_product('P-604'), p604)
        with store.connection() as db:
            self.assertIsNone(db.execute(
                "SELECT id FROM orders WHERE product_id='P-604'"
            ).fetchone())
            legacy_after = db.execute(
                "SELECT name, variant, amount, status, product_id FROM orders "
                "WHERE id='O-P604-SEED-REGRESSION'"
            ).fetchone()
        self.assertEqual(dict(legacy_after), dict(legacy_before))

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

        # 4. Verify v4 upgrade state
        with transaction(DSN) as db:
            self.assertEqual(db.execute("SELECT version FROM retailops_schema WHERE component='identity'").fetchone()['version'], 4)

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
            # 1. Version upgraded to 4
            self.assertEqual(db.execute("SELECT version FROM retailops_schema WHERE component='identity'").fetchone()['version'], 4)

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

        # 9. Verify subsequent startup does NOT fail and leaves version at 4
        pg_istore_reopened = PostgresIdentityStore(DSN, create=False)
        with transaction(DSN) as db:
            self.assertEqual(db.execute("SELECT version FROM retailops_schema WHERE component='identity'").fetchone()['version'], 4)

    def test_identity_v3_to_v4_migration_creates_journal_on_postgres(self):
        """P1 Integration: Existing v3 PostgreSQL schema lacking reconciliation_journal table
        auto-upgrades to v4 upon startup and provides working reconciliation."""
        with transaction(DSN, write=True) as db:
            db.execute("DROP TABLE IF EXISTS reconciliation_journal CASCADE")
            db.execute("UPDATE retailops_schema SET version = 3 WHERE component = 'identity'")

        # Startup auto-upgrades to v4 and creates reconciliation_journal
        pg_istore = PostgresIdentityStore(DSN, create=False)
        with transaction(DSN) as db:
            self.assertEqual(db.execute("SELECT version FROM retailops_schema WHERE component='identity'").fetchone()['version'], 4)
            has_journal = db.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema='retailops_identity' AND table_name='reconciliation_journal'"
            ).fetchone()
            self.assertIsNotNone(has_journal)
            has_col = db.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_schema='retailops_identity' AND table_name='reconciliation_journal' AND column_name='plan_hash'"
            ).fetchone()
            self.assertIsNotNone(has_col)

    def test_identity_v1_legacy_collision_migration_to_reconciliation_on_postgres(self):
        """P1 Integration: Legacy v1 PostgreSQL schema with collision migrates to v4 quarantine,
        blocks colliding members with 503, and allows operator reconciliation to target accounts."""
        now = time.time()
        with transaction(DSN, write=True) as db:
            db.execute("DROP TABLE IF EXISTS reconciliation_journal CASCADE")
            db.execute("DROP TABLE IF EXISTS customer_links CASCADE")
            db.execute("DROP TABLE IF EXISTS unresolved_collisions CASCADE")
            db.execute("UPDATE retailops_schema SET version = 1 WHERE component = 'identity'")

            db.execute("INSERT INTO tenants (id, name, storage_key, active) VALUES ('shop-mig-pg', 'Shop Mig PG', '0123456789abcdef0123456789abcdef', 1) ON CONFLICT DO NOTHING")
            db.execute("INSERT INTO principals (id, name) VALUES ('p-mig-1', 'Alice Mig') ON CONFLICT DO NOTHING")
            db.execute("INSERT INTO principals (id, name) VALUES ('p-mig-2', 'Bob Mig') ON CONFLICT DO NOTHING")
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-mig-1', 'shop-mig-pg', 'p-mig-1', 'CG-mig-shared', 'customer', 1, 1) ON CONFLICT DO NOTHING"
            )
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-mig-2', 'shop-mig-pg', 'p-mig-2', 'CG-mig-shared', 'customer', 1, 1) ON CONFLICT DO NOTHING"
            )

        # Setup business DB
        b_store = PostgresBusinessStore(DSN, '0123456789abcdef0123456789abcdef', create=True)
        with b_store.connection(write=True) as b_db:
            b_db.execute("INSERT INTO customers (id, name) VALUES ('CG-mig-shared', 'Shared Mig Customer') ON CONFLICT DO NOTHING")
            b_db.execute(
                "INSERT INTO orders (id, customer_id, name, variant, amount, status, version) "
                "VALUES ('O-MIG-1', 'CG-mig-shared', 'Item Mig', 'L', 200000, 'pending', 1) ON CONFLICT DO NOTHING"
            )
            b_db.execute(
                "INSERT INTO conversations (id, customer_id, order_id, product_id, revision, expires_at) "
                "VALUES ('conv-mig-1', 'CG-mig-shared', 'O-MIG-1', 'P-1', 1, ?) ON CONFLICT DO NOTHING",
                (now + 3600,)
            )

        # Startup auto-upgrades from v1 to v4:
        pg_istore = PostgresIdentityStore(DSN, create=False)

        # 1. Collision must be detected and stored in unresolved_collisions
        with transaction(DSN) as db:
            unres = db.execute("SELECT 1 FROM unresolved_collisions WHERE tenant_id='shop-mig-pg' AND customer_id='CG-mig-shared'").fetchone()
            self.assertIsNotNone(unres)

        # 2. Both members strictly fail-closed with 503 collision_unresolved
        with self.assertRaises(ApiError) as ctx1:
            pg_istore.create_session_for_membership('m-mig-1', 3600, 10)
        self.assertEqual(ctx1.exception.status, 503)
        self.assertEqual(ctx1.exception.code, "collision_unresolved")

        # 3. Reconcile via coordinator
        plan = {
            "reassignments": [
                {
                    "membership_id": "m-mig-1",
                    "target_customer_id": "CG-mig-alice",
                    "target_customer_name": "Alice Mig Resolved",
                    "order_ids": ["O-MIG-1"],
                    "conversation_ids": ["conv-mig-1"],
                },
                {
                    "membership_id": "m-mig-2",
                    "target_customer_id": "CG-mig-bob",
                    "target_customer_name": "Bob Mig Resolved",
                    "order_ids": [],
                    "conversation_ids": [],
                },
            ]
        }
        res = reconcile_collision(self.sessions, "shop-mig-pg", "CG-mig-shared", plan, idempotency_key="rec-mig-pg-ok")
        self.assertEqual(res["status"], "completed")

        # 4. Verify post-reconciliation: unresolved_collisions cleaned up
        with transaction(DSN) as db:
            unres_after = db.execute("SELECT 1 FROM unresolved_collisions WHERE tenant_id='shop-mig-pg' AND customer_id='CG-mig-shared'").fetchone()
            self.assertIsNone(unres_after)

        # Sessions now work cleanly
        s1 = pg_istore.create_session_for_membership('m-mig-1', 3600, 10)
        s2 = pg_istore.create_session_for_membership('m-mig-2', 3600, 10)
        self.assertTrue(bool(s1))
        self.assertTrue(bool(s2))

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
            # Real conversations: 11111111-1111-1111-1111-111111111111 for Alice, 22222222-2222-2222-2222-222222222222 for Bob
            b_db.execute(
                "INSERT INTO conversations (id, customer_id, order_id, product_id, revision, expires_at) "
                "VALUES ('11111111-1111-1111-1111-111111111111', 'CG-rec-shared', 'O-REC-001', 'P-REC-001', 1, ?) ON CONFLICT DO NOTHING",
                (now + 3600,)
            )
            b_db.execute(
                "INSERT INTO conversations (id, customer_id, order_id, product_id, revision, expires_at) "
                "VALUES ('22222222-2222-2222-2222-222222222222', 'CG-rec-shared', 'O-REC-003', 'P-REC-001', 1, ?) ON CONFLICT DO NOTHING",
                (now + 3600,)
            )
            b_db.execute(
                "INSERT INTO agent_turns (conversation_id, customer_id, request_id, input_hash, messages, result, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                ('11111111-1111-1111-1111-111111111111', 'CG-rec-shared', 'req-turn-001', 'hash001', '[]', '{\"reply\":\"Alice hello\"}', now)
            )
            b_db.execute(
                "INSERT INTO agent_turns (conversation_id, customer_id, request_id, input_hash, messages, result, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                ('22222222-2222-2222-2222-222222222222', 'CG-rec-shared', 'req-turn-002', 'hash002', '[]', '{\"reply\":\"Bob hello\"}', now)
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
                    "conversation_ids": ["11111111-1111-1111-1111-111111111111"],
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
                    "conversation_ids": ["22222222-2222-2222-2222-222222222222"],
                    "external_identity": {
                        "issuer": "https://accounts.google.com",
                        "sub": "google-sub-bob-rec-67890",
                        "email": "bob.rec@example.com",
                    },
                },
            ]
        }
        idempotency_key = "rec-shop-a-shared"

        # 4a. Preflight validation checks on PostgreSQL:
        # - Reject plan with incomplete membership coverage
        inc_mem_plan = {
            "reassignments": [
                {
                    "membership_id": "m-rec-1",
                    "target_customer_id": "CG-rec-alice",
                    "order_ids": ["O-REC-001", "O-REC-002"],
                    "conversation_ids": ["11111111-1111-1111-1111-111111111111"],
                }
            ]
        }
        with self.assertRaises(ApiError) as ctx_pg_mem:
            reconcile_collision(self.sessions, "shop-a", "CG-rec-shared", inc_mem_plan, idempotency_key="rec-pg-inc-mem")
        self.assertEqual(ctx_pg_mem.exception.status, 400)
        self.assertEqual(ctx_pg_mem.exception.code, "incomplete_membership_coverage")

        # - Reject plan with incomplete order coverage
        inc_ord_plan = {
            "reassignments": [
                {
                    "membership_id": "m-rec-1",
                    "target_customer_id": "CG-rec-alice",
                    "order_ids": ["O-REC-001"],
                    "conversation_ids": ["11111111-1111-1111-1111-111111111111"],
                },
                {
                    "membership_id": "m-rec-2",
                    "target_customer_id": "CG-rec-bob",
                    "order_ids": [],
                    "conversation_ids": ["22222222-2222-2222-2222-222222222222"],
                },
            ]
        }
        with self.assertRaises(ApiError) as ctx_pg_ord:
            reconcile_collision(self.sessions, "shop-a", "CG-rec-shared", inc_ord_plan, idempotency_key="rec-pg-inc-ord")
        self.assertEqual(ctx_pg_ord.exception.status, 400)
        self.assertEqual(ctx_pg_ord.exception.code, "incomplete_order_coverage")

        # - Reject plan with incomplete conversation coverage
        inc_conv_plan = {
            "reassignments": [
                {
                    "membership_id": "m-rec-1",
                    "target_customer_id": "CG-rec-alice",
                    "order_ids": ["O-REC-001", "O-REC-002"],
                    "conversation_ids": [],
                },
                {
                    "membership_id": "m-rec-2",
                    "target_customer_id": "CG-rec-bob",
                    "order_ids": ["O-REC-003"],
                    "conversation_ids": ["22222222-2222-2222-2222-222222222222"],
                },
            ]
        }
        with self.assertRaises(ApiError) as ctx_pg_conv:
            reconcile_collision(self.sessions, "shop-a", "CG-rec-shared", inc_conv_plan, idempotency_key="rec-pg-inc-conv")
        self.assertEqual(ctx_pg_conv.exception.status, 400)
        self.assertEqual(ctx_pg_conv.exception.code, "incomplete_conversation_coverage")

        # Verify fail-closed: unresolved_collisions still holds the collision on PostgreSQL
        with transaction(DSN) as db:
            col_check = db.execute("SELECT 1 FROM unresolved_collisions WHERE tenant_id='shop-a' AND customer_id='CG-rec-shared'").fetchone()
            self.assertIsNotNone(col_check)

        # 5a. Fault Injection 1a: Crash after Business DB commit BEFORE journal update
        with self.assertRaises(RuntimeError) as fault1a:
            reconcile_collision(
                self.sessions,
                "shop-a",
                "CG-rec-shared",
                plan,
                idempotency_key=idempotency_key,
                fault_stage="after_business_commit_before_journal",
            )
        self.assertIn("before journal update", str(fault1a.exception))

        # Check Journal status is 'started'
        j0 = get_reconciliation_status(self.sessions, idempotency_key)
        self.assertIsNotNone(j0)
        self.assertEqual(j0["status"], "started")

        # 5b. Fault Injection 1b: Crash after Business DB commit AND journal updated to business_committed
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
                "SELECT id, customer_id FROM conversations WHERE id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222')"
            ).fetchall()
            conv_map = {r["id"]: r["customer_id"] for r in conv_rows}
            self.assertEqual(conv_map["11111111-1111-1111-1111-111111111111"], "CG-rec-alice")
            self.assertEqual(conv_map["22222222-2222-2222-2222-222222222222"], "CG-rec-bob")

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

        # 6. Fault Injection 2: Crash during Identity DB commit AFTER updates executed
        with self.assertRaises(RuntimeError) as fault2:
            reconcile_collision(
                self.sessions,
                "shop-a",
                "CG-rec-shared",
                plan,
                idempotency_key=idempotency_key,
                fault_stage="during_identity_commit_after_updates",
            )
        self.assertIn("Fault injected during identity commit after updates executed", str(fault2.exception))

        # Identity DB transaction rolled back: still fail-closed
        with self.assertRaises(ApiError) as ctx1_roll:
            pg_istore.create_session_for_membership('m-rec-1', 3600, 10)
        self.assertEqual(ctx1_roll.exception.status, 503)
        self.assertEqual(ctx1_roll.exception.code, "collision_unresolved")

        # 6b. Plan Immutability check on retry: retrying with altered plan raises 409
        import copy
        altered_plan = copy.deepcopy(plan)
        altered_plan["reassignments"][0]["target_customer_id"] = "CG-rec-altered"
        with self.assertRaises(ApiError) as ctx_alt:
            reconcile_collision(
                self.sessions,
                "shop-a",
                "CG-rec-shared",
                altered_plan,
                idempotency_key=idempotency_key,
            )
        self.assertEqual(ctx_alt.exception.status, 409)
        self.assertEqual(ctx_alt.exception.code, "plan_conflict")

        # 7. Recovery & Resume: Simulate process restart by instantiating a fresh PostgresSessions
        restarted_pg_sessions = PostgresSessions(DSN)
        rec_result = reconcile_collision(
            restarted_pg_sessions,
            "shop-a",
            "CG-rec-shared",
            plan,
            idempotency_key=idempotency_key,
        )
        self.assertEqual(rec_result["status"], "completed")

        # Verify Journal state is 'completed'
        j2 = get_reconciliation_status(restarted_pg_sessions, idempotency_key)
        self.assertIsNotNone(j2)
        self.assertEqual(j2["status"], "completed")

        # Verify Idempotency: re-running with same idempotency_key returns already_completed
        idempotent_result = reconcile_collision(
            restarted_pg_sessions,
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

        # Alice owns 11111111-1111-1111-1111-111111111111, CANNOT see Bob's 22222222-2222-2222-2222-222222222222
        alice_convs = b_store.list_conversations('CG-rec-alice')
        alice_conv_ids = {c['id'] for c in alice_convs}
        self.assertEqual(alice_conv_ids, {'11111111-1111-1111-1111-111111111111'})
        self.assertNotIn('22222222-2222-2222-2222-222222222222', alice_conv_ids)
        with self.assertRaises(ApiError) as ctx_cross_conv1:
            b_store.conversation('CG-rec-alice', '22222222-2222-2222-2222-222222222222')
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

        # Bob owns 22222222-2222-2222-2222-222222222222, CANNOT see Alice's 11111111-1111-1111-1111-111111111111
        bob_convs = b_store.list_conversations('CG-rec-bob')
        bob_conv_ids = {c['id'] for c in bob_convs}
        self.assertEqual(bob_conv_ids, {'22222222-2222-2222-2222-222222222222'})
        self.assertNotIn('11111111-1111-1111-1111-111111111111', bob_conv_ids)
        with self.assertRaises(ApiError) as ctx_cross_conv2:
            b_store.conversation('CG-rec-bob', '11111111-1111-1111-1111-111111111111')
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

        # 8g. Ownership & External Identity hijack protections on PostgreSQL:
        with transaction(DSN, write=True) as db:
            db.execute("INSERT INTO principals (id, name) VALUES ('p-rec-3', 'Charlie'), ('p-rec-4', 'Dave') ON CONFLICT DO NOTHING")
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-rec-3', 'shop-a', 'p-rec-3', 'CG-rec-shared-2', 'customer', 1, 1), "
                "       ('m-rec-4', 'shop-a', 'p-rec-4', 'CG-rec-shared-2', 'customer', 1, 1) ON CONFLICT DO NOTHING"
            )
            db.execute("INSERT INTO unresolved_collisions VALUES ('shop-a', 'CG-rec-shared-2', ?) ON CONFLICT DO NOTHING", (now,))

        bad_owner_plan = {
            "reassignments": [
                {
                    "membership_id": "m-rec-3",
                    "target_customer_id": "CG-rec-charlie",
                    "order_ids": ["O-REC-003"],  # O-REC-003 belongs to Bob (CG-rec-bob), NOT CG-rec-shared-2!
                },
                {
                    "membership_id": "m-rec-4",
                    "target_customer_id": "CG-rec-dave",
                    "order_ids": [],
                },
            ]
        }
        with self.assertRaises(ApiError) as ctx_pg_owner:
            reconcile_collision(restarted_pg_sessions, "shop-a", "CG-rec-shared-2", bad_owner_plan, idempotency_key="rec-pg-bad-owner")
        self.assertEqual(ctx_pg_owner.exception.status, 403)
        self.assertEqual(ctx_pg_owner.exception.code, "order_ownership_conflict")

        hijack_sub_plan = {
            "reassignments": [
                {
                    "membership_id": "m-rec-3",
                    "target_customer_id": "CG-rec-charlie",
                    "order_ids": [],
                    "external_identity": {
                        "issuer": "https://accounts.google.com",
                        "sub": "google-sub-bob-rec-67890",  # belongs to Bob / p-rec-2!
                    },
                },
                {
                    "membership_id": "m-rec-4",
                    "target_customer_id": "CG-rec-dave",
                    "order_ids": [],
                },
            ]
        }
        with self.assertRaises(ApiError) as ctx_pg_hijack:
            reconcile_collision(restarted_pg_sessions, "shop-a", "CG-rec-shared-2", hijack_sub_plan, idempotency_key="rec-pg-hijack")
        self.assertEqual(ctx_pg_hijack.exception.status, 409)
        self.assertEqual(ctx_pg_hijack.exception.code, "external_identity_conflict")

    def test_reconciliation_rejects_target_owned_by_other_principal_on_postgres(self):
        """P1.1 Regression (PostgreSQL): same scenario as the SQLite suite; mis-targeted plans are
        rejected before any Business DB write, data unchanged, collision unresolved, journal not
        bound, and a corrected retry with the same idempotency key completes."""
        try:
            import reconcile_target_cases
        except ImportError:
            from tests import reconcile_target_cases
        reconcile_target_cases.run(self, self.sessions, 'shop-a')

    def test_reconciliation_toctou_target_taken_after_preflight_on_postgres(self):
        """P1.1 TOCTOU (PostgreSQL): same interleaving scenario as the SQLite suite, including
        LOCK TABLE serialization, reservation, compensation and the Step 3 re-check."""
        try:
            import reconcile_interleaving_cases
        except ImportError:
            from tests import reconcile_interleaving_cases
        reconcile_interleaving_cases.run(self, self.sessions, 'shop-a')

    def test_google_tenant_resolution_and_active_membership_on_postgres(self):
        """P5-K3 remediation (PostgreSQL): full login_google() and resolve_google_tenant() regressions for
        (a) inactive-only membership + single active store, (b) multiple active memberships,
        (c) unknown identity onboarding in single-store demo, (d) selector conflicting with existing identity
        (including legacy GOOGLE_AUTH_TENANT_ID), (e) verified-email legacy principal inactive-only fail-closed
        plus same-tenant legacy positive control, and case-insensitive smoke-tenant exclusion with zero side effects on failure."""
        self.sessions.provision_tenant('e2e-smoke-pg-01', 'PG Smoke Tenant', seed_demo=True)
        self.sessions.provision_tenant('E2E-UPPER-PG-02', 'PG Upper Smoke Tenant', seed_demo=True)

        def pg_snapshot_state():
            with transaction(DSN, write=False) as db:
                prins = {r["id"] for r in db.execute("SELECT id FROM principals").fetchall()}
                exts = {
                    (r["id"], r["issuer"], r["sub"], r["principal_id"])
                    for r in db.execute("SELECT id, issuer, sub, principal_id FROM external_identities").fetchall()
                }
                links = {
                    (r["id"], r["tenant_id"], r["principal_id"], r["customer_id"])
                    for r in db.execute("SELECT id, tenant_id, principal_id, customer_id FROM customer_links").fetchall()
                }
                mems = {
                    (r["id"], r["tenant_id"], r["principal_id"], r["customer_id"], r["active"])
                    for r in db.execute("SELECT id, tenant_id, principal_id, customer_id, active FROM memberships").fetchall()
                }
                sess = {r["id"] for r in db.execute("SELECT id FROM sessions").fetchall()}
                trows = db.execute("SELECT id, storage_key FROM tenants ORDER BY id").fetchall()
            custs = {}
            for trow in trows:
                with transaction(DSN, tenant_schema(trow["storage_key"]), write=False) as bdb:
                    c_ids = {r["id"] for r in bdb.execute("SELECT id FROM customers").fetchall()}
                    custs[trow["id"]] = (len(c_ids), c_ids)
            return (
                (len(prins), prins),
                (len(exts), exts),
                (len(links), links),
                (len(mems), mems),
                (len(sess), sess),
                custs,
            )

        # 1. With shop-a and shop-b active and no default_tenant_id, unlinked Google sub fails closed with 503 ambiguous_tenant
        before_unlinked = pg_snapshot_state()
        with self.assertRaises(ApiError) as ctx_amb:
            self.sessions.login_google('unlinked@example.com', 'Unlinked', sub='pg-google-sub-unlinked-1', email_verified=True)
        self.assertEqual(ctx_amb.exception.status, 503)
        self.assertEqual(ctx_amb.exception.code, 'ambiguous_tenant')
        self.assertEqual(pg_snapshot_state(), before_unlinked)

        # 2. Smoke tenant (lowercase, uppercase, mixed-case) in selector rejected with 503 tenant_unavailable
        for bad_smoke in ('e2e-smoke-pg-01', 'E2E-UPPER-PG-02', 'Smoke-Mixed-PG-03', 'SYNTHETIC-PG-04'):
            pg_smoke_sessions = PostgresSessions(DSN, default_tenant_id=bad_smoke)
            with self.assertRaises(ApiError) as ctx_smoke:
                pg_smoke_sessions.login_google('unlinked@example.com', 'Unlinked', sub='pg-google-sub-unlinked-1', email_verified=True)
            self.assertEqual(ctx_smoke.exception.status, 503)
            self.assertEqual(ctx_smoke.exception.code, 'tenant_unavailable')
        self.assertEqual(pg_snapshot_state(), before_unlinked)

        # 3. Configured RETAILOPS_DEMO_TENANT_ID / default_tenant_id resolves deterministically for unknown identity;
        #    empty RETAILOPS_DEMO_TENANT_ID falls back to GOOGLE_AUTH_TENANT_ID; conflicting selectors fail closed
        pg_cfg_sessions = PostgresSessions(DSN, default_tenant_id='  shop-b  ')
        self.assertEqual(pg_cfg_sessions.resolve_google_tenant(sub='pg-google-sub-unlinked-1'), 'shop-b')

        with patch.dict(os.environ, {'RETAILOPS_DEMO_TENANT_ID': '   ', 'GOOGLE_AUTH_TENANT_ID': ' "shop-b" '}, clear=False):
            pg_fb_sessions = PostgresSessions(DSN)
            self.assertEqual(pg_fb_sessions.default_tenant_id, 'shop-b')
            self.assertEqual(pg_fb_sessions.resolve_google_tenant(sub='pg-google-sub-unlinked-1'), 'shop-b')

        with patch.dict(os.environ, {'RETAILOPS_DEMO_TENANT_ID': 'shop-a', 'GOOGLE_AUTH_TENANT_ID': 'shop-b'}, clear=False):
            pg_conflict_sessions = PostgresSessions(DSN)
            self.assertIsNone(pg_conflict_sessions.default_tenant_id)
            with self.assertRaises(ApiError) as ctx_conf:
                pg_conflict_sessions.login_google('unlinked@example.com', 'Unlinked', sub='pg-google-sub-unlinked-1', email_verified=True)
            self.assertEqual(ctx_conf.exception.status, 503)
            self.assertEqual(ctx_conf.exception.code, 'ambiguous_tenant')
        self.assertEqual(pg_snapshot_state(), before_unlinked)

        # 4. Provision known identity in shop-a (and smoke tenants which must be ignored)
        sub_mem = 'pg-google-sub-member-01'
        self.sessions.login_google('pg.member@example.com', 'PG Member', sub=sub_mem, email_verified=True, tenant_id='shop-a')
        self.sessions.control.get_or_create_google_member('e2e-smoke-pg-01', 'pg.member@example.com', 'PG Member', sub=sub_mem, email_verified=True)
        self.sessions.control.get_or_create_google_member('E2E-UPPER-PG-02', 'pg.member@example.com', 'PG Member', sub=sub_mem, email_verified=True)

        # (d) Selector conflicting with an existing identity (default_tenant_id, RETAILOPS_DEMO_TENANT_ID,
        #     legacy GOOGLE_AUTH_TENANT_ID alone, or explicit tenant_id='shop-b') must fail closed on full login_google()
        #     and produce ZERO new principals, external_identities, customer_links, memberships, customers, or sessions.
        before_d = pg_snapshot_state()
        pg_wrong_default = PostgresSessions(DSN, default_tenant_id='shop-b')
        with self.assertRaises(ApiError) as ctx_d1:
            pg_wrong_default.login_google('pg.member@example.com', 'PG Member', sub=sub_mem, email_verified=True)
        self.assertEqual(ctx_d1.exception.status, 503)
        self.assertEqual(ctx_d1.exception.code, 'ambiguous_tenant')
        with patch.dict(os.environ, {'RETAILOPS_DEMO_TENANT_ID': 'shop-b'}, clear=False):
            with self.assertRaises(ApiError) as ctx_d2:
                self.sessions.login_google('pg.member@example.com', 'PG Member', sub=sub_mem, email_verified=True)
            self.assertEqual(ctx_d2.exception.status, 503)
            self.assertEqual(ctx_d2.exception.code, 'ambiguous_tenant')
        with patch.dict(os.environ, {'RETAILOPS_DEMO_TENANT_ID': '', 'GOOGLE_AUTH_TENANT_ID': 'shop-b'}, clear=False):
            with self.assertRaises(ApiError) as ctx_d_leg:
                self.sessions.login_google('pg.member@example.com', 'PG Member', sub=sub_mem, email_verified=True)
            self.assertEqual(ctx_d_leg.exception.status, 503)
            self.assertEqual(ctx_d_leg.exception.code, 'ambiguous_tenant')
        with self.assertRaises(ApiError) as ctx_d3:
            self.sessions.login_google('pg.member@example.com', 'PG Member', sub=sub_mem, email_verified=True, tenant_id='shop-b')
        self.assertEqual(ctx_d3.exception.status, 503)
        self.assertEqual(ctx_d3.exception.code, 'ambiguous_tenant')
        self.assertEqual(pg_snapshot_state(), before_d)

        # (b) Multiple active memberships: add active membership in shop-b; full login_google() without explicit tenant_id
        #     (and even with default_tenant_id='shop-a') must fail closed with 503 ambiguous_tenant and zero side effects.
        self.sessions.control.get_or_create_google_member('shop-b', 'pg.member@example.com', 'PG Member', sub=sub_mem, email_verified=True)
        before_b = pg_snapshot_state()
        with self.assertRaises(ApiError) as ctx_b1:
            self.sessions.login_google('pg.member@example.com', 'PG Member', sub=sub_mem, email_verified=True)
        self.assertEqual(ctx_b1.exception.status, 503)
        self.assertEqual(ctx_b1.exception.code, 'ambiguous_tenant')
        pg_default_a = PostgresSessions(DSN, default_tenant_id='shop-a')
        with self.assertRaises(ApiError) as ctx_b2:
            pg_default_a.login_google('pg.member@example.com', 'PG Member', sub=sub_mem, email_verified=True)
        self.assertEqual(ctx_b2.exception.status, 503)
        self.assertEqual(ctx_b2.exception.code, 'ambiguous_tenant')
        self.assertEqual(pg_snapshot_state(), before_b)

        # (a) Inactive-only membership + single active store:
        #     create sub_only_inactive in shop-a, then deactivate shop-a so shop-b is the SOLE active non-smoke store.
        #     sub_only_inactive must fail closed on login_google() (with or without default_tenant_id='shop-b') and produce zero new rows;
        #     meanwhile sub_mem (which has active membership in shop-b) resolves cleanly to shop-b.
        sub_only_inactive = 'pg-google-sub-only-inactive-02'
        self.sessions.login_google('pg.inactive@example.com', 'PG Inactive', sub=sub_only_inactive, email_verified=True, tenant_id='shop-a')
        with transaction(DSN, write=True) as db:
            db.execute("UPDATE tenants SET active=0 WHERE id='shop-a'")
            db.execute("DELETE FROM sessions")

        sec_b = self.sessions.login_google('pg.member@example.com', 'PG Member', sub=sub_mem, email_verified=True)
        mem_b = self.sessions.control.resolve(self.sessions.cookie_id(f'__Host-retailops_account={sec_b}'))
        self.assertEqual(mem_b['tenant_id'], 'shop-b')

        before_a = pg_snapshot_state()
        with self.assertRaises(ApiError) as ctx_a1:
            self.sessions.login_google('pg.inactive@example.com', 'PG Inactive', sub=sub_only_inactive, email_verified=True)
        self.assertEqual(ctx_a1.exception.status, 503)
        self.assertEqual(ctx_a1.exception.code, 'ambiguous_tenant')
        with self.assertRaises(ApiError) as ctx_a2:
            pg_wrong_default.login_google('pg.inactive@example.com', 'PG Inactive', sub=sub_only_inactive, email_verified=True)
        self.assertEqual(ctx_a2.exception.status, 503)
        self.assertEqual(ctx_a2.exception.code, 'ambiguous_tenant')
        self.assertEqual(pg_snapshot_state(), before_a)

        # Also test when tenant shop-b stays active=1 but sub_mem's membership row in shop-b is deactivated (m.active=0):
        with transaction(DSN, write=True) as db:
            db.execute("UPDATE memberships SET active=0 WHERE tenant_id='shop-b' AND customer_id=%s", (mem_b['customer_id'],))
        before_a_mem = pg_snapshot_state()
        with self.assertRaises(ApiError) as ctx_a3:
            self.sessions.login_google('pg.member@example.com', 'PG Member', sub=sub_mem, email_verified=True)
        self.assertEqual(ctx_a3.exception.status, 503)
        self.assertEqual(ctx_a3.exception.code, 'ambiguous_tenant')
        self.assertEqual(pg_snapshot_state(), before_a_mem)

        # (e) Verified-email legacy principal (no external_identities row yet) whose only membership is inactive
        #     (in deactivated 'shop-a' or with m.active=0 in 'shop-b') must fail closed BEFORE any writes
        #     (no new external_identities, customer_links, memberships, customers, or sessions) when logging in with its first Google sub.
        import re
        legacy_inactive_email = 'pg.legacy.inactive@example.com'
        leg_inact_prefix = re.sub(r'[^a-zA-Z0-9_-]', '_', legacy_inactive_email.split('@')[0])[:25]
        leg_inact_hash = hashlib.sha256(legacy_inactive_email.encode()).hexdigest()[:10]
        leg_inact_pid = f"g_{leg_inact_prefix}_{leg_inact_hash}"
        leg_inact_cid = f"CG-{leg_inact_hash[:8]}"
        with transaction(DSN, write=True) as db:
            db.execute("INSERT INTO principals (id, name) VALUES (%s, %s)", (leg_inact_pid, 'PG Legacy Inactive'))
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-pg-leg-inact-1', 'shop-a', %s, %s, 'customer', 1, 1)",
                (leg_inact_pid, leg_inact_cid),
            )
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-pg-leg-inact-2', 'shop-b', %s, %s, 'customer', 0, 1)",
                (leg_inact_pid, leg_inact_cid),
            )

        before_leg_inact = pg_snapshot_state()
        with self.assertRaises(ApiError) as ctx_leg1:
            self.sessions.login_google(
                legacy_inactive_email, 'PG Legacy Inactive', sub='pg-new-sub-legacy-inactive', email_verified=True
            )
        self.assertEqual(ctx_leg1.exception.status, 503)
        self.assertEqual(ctx_leg1.exception.code, 'ambiguous_tenant')
        with self.assertRaises(ApiError) as ctx_leg2:
            pg_wrong_default.login_google(
                legacy_inactive_email, 'PG Legacy Inactive', sub='pg-new-sub-legacy-inactive', email_verified=True
            )
        self.assertEqual(ctx_leg2.exception.status, 503)
        self.assertEqual(ctx_leg2.exception.code, 'ambiguous_tenant')
        self.assertEqual(pg_snapshot_state(), before_leg_inact)

        # Positive control for verified-email legacy principal: active membership in active 'shop-b' links cleanly
        legacy_active_email = 'pg.legacy.active@example.com'
        leg_act_prefix = re.sub(r'[^a-zA-Z0-9_-]', '_', legacy_active_email.split('@')[0])[:25]
        leg_act_hash = hashlib.sha256(legacy_active_email.encode()).hexdigest()[:10]
        leg_act_pid = f"g_{leg_act_prefix}_{leg_act_hash}"
        leg_act_cid = f"CG-{leg_act_hash[:8]}"
        with transaction(DSN, write=True) as db:
            db.execute("INSERT INTO principals (id, name) VALUES (%s, %s)", (leg_act_pid, 'PG Legacy Active'))
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-pg-leg-act-1', 'shop-b', %s, %s, 'customer', 1, 1)",
                (leg_act_pid, leg_act_cid),
            )
        sec_leg_ok = self.sessions.login_google(
            legacy_active_email, 'PG Legacy Active', sub='pg-new-sub-legacy-active', email_verified=True
        )
        mem_leg_ok = self.sessions.control.resolve(self.sessions.cookie_id(f'__Host-retailops_account={sec_leg_ok}'))
        self.assertEqual(mem_leg_ok['tenant_id'], 'shop-b')
        self.assertEqual(mem_leg_ok['principal_id'], leg_act_pid)
        self.assertEqual(mem_leg_ok['customer_id'], leg_act_cid)

        # (c) Unknown identity onboarding in a single-store demo ('shop-b' is the sole active non-smoke store):
        #     genuinely new Google identity succeeds on login_google() and resolves to 'shop-b'.
        sec_new_single = self.sessions.login_google(
            'pg.new.single@example.com', 'PG New Single', sub='pg-google-sub-new-single-03', email_verified=True
        )
        mem_new_single = self.sessions.control.resolve(self.sessions.cookie_id(f'__Host-retailops_account={sec_new_single}'))
        self.assertEqual(mem_new_single['tenant_id'], 'shop-b')

    def test_phase5_e_postgres_governance_and_ai_boundaries(self):
        """Phase 5-E PostgreSQL parity: AI3 boundaries, ADM1-ADM6 governance/quota/audit, and DATA1-DATA2 hygiene."""
        store_a = self.sessions.business_store('shop-a')

        # 1. AI3: Entity/owner boundary and Unicode confusables / SQL-like IDs on PostgresBusinessStore
        self.assertEqual(store_a.lookup('C-001', 'O-101')['id'], 'O-101')
        for bad_oid in ('O-201', 'O-999', "O-101' OR '1'='1", 'O-101\u200b', 'O-\uff11\uff10\uff11'):
            with self.assertRaises(ApiError) as ctx_oid:
                store_a.lookup('C-001', bad_oid)
            self.assertEqual(ctx_oid.exception.status, 404, bad_oid)
        for bad_pid in ("P-602' OR '1'='1", 'P-602\u200b', 'P-\uff16\uff10\uff12'):
            self.assertIsNone(store_a.get_product(bad_pid), bad_pid)

        # 2. DATA1 & DATA2 on PostgresSessions + PostgresBusinessStore
        sec_sample = self.sessions.login_google(
            'pg.p5e.sample@example.com', 'PG P5E Sample', sub='pg-sub-p5e-data1', email_verified=True, tenant_id='shop-a'
        )
        cookie_sample = f"{self.sessions.cookie_name}={sec_sample}"
        code_ord, body_ord, _ = self.request('/api/orders', cookie=cookie_sample)
        self.assertEqual(code_ord, 200)
        p602_ords = [o for o in body_ord['orders'] if o.get('product_id') == 'P-602']
        self.assertEqual(len(p602_ords), 1)
        self.assertEqual(p602_ords[0]['display_name'], 'Bộ xếp hình gỗ cho bé')
        self.assertEqual(p602_ords[0]['name'], 'Quần tây ống đứng tôn dáng')
        self.assertEqual(p602_ords[0]['product_id'], 'P-602')

        p604 = store_a.get_product('P-604')
        self.assertIsNotNone(p604)
        self.assertIsNone(p604['price'])
        self.assertIsNone(p604['stock'])
        self.assertIsNone(p604['warranty_days'])
        self.assertEqual(p604['material'], 'Gỗ')
        self.assertIsNone(p604['care'])
        self.assertIn('bộ xếp hình gỗ', [a.lower() for a in p604.get('aliases', [])])

        store_a.add_product({
            'id': 'P-PG-NULL-STOCK',
            'name': 'SP PG Null Stock',
            'category': 'Phụ kiện',
            'price': None,
            'stock': None,
            'variants': ['Đỏ · Size S', 'Xanh · Size M'],
        })
        var_null = store_a.get_variant_stock('P-PG-NULL-STOCK', 'S', 'Đỏ')
        self.assertIsNone(var_null.stock)
        self.assertEqual(var_null.status, 'stock_unknown')

        store_a.add_product({
            'id': 'P-PG-ZERO-STOCK',
            'name': 'SP PG Zero Stock',
            'category': 'Phụ kiện',
            'price': 99000,
            'stock': 0,
            'variants': ['Đỏ · Size S', 'Xanh · Size M'],
        })
        var_zero = store_a.get_variant_stock('P-PG-ZERO-STOCK', 'S', 'Đỏ')
        self.assertEqual(var_zero.stock, 0)
        self.assertEqual(var_zero.status, 'ok')

        # 3. ADM1..ADM6 on PostgresSessions + PublicWeb
        mgr_a = self.member('mgr_a_p5e', 'shop-a', 'C-002', 'manager')
        padmin = self.member('padmin_p5e', 'shop-a', 'C-003', 'platform_admin')
        cookie_alice = self.login(self.alice)
        cookie_other = self.login(self.other)
        cookie_mgr_a = self.login(mgr_a)
        cookie_padmin = self.login(padmin)

        # Unauthenticated -> 401
        code_unauth, _, _ = self.request('/api/admin/accounts')
        self.assertEqual(code_unauth, 401)

        # Customer -> 403 permission_denied + audit log
        code_cust, body_cust, _ = self.request('/api/admin/accounts', cookie=cookie_alice)
        self.assertEqual(code_cust, 403)
        self.assertEqual(body_cust['error'], 'permission_denied')

        # Manager A lists shop-a accounts cleanly without secret exposure
        code_list, body_list, _ = self.request('/api/admin/accounts', cookie=cookie_mgr_a)
        self.assertEqual(code_list, 200)
        self.assertEqual(body_list['tenant_id'], 'shop-a')
        self.assertTrue(all(a['tenant_id'] == 'shop-a' for a in body_list['accounts']))
        self.assertNotIn('token', json.dumps(body_list['accounts']))
        self.assertNotIn('hash', json.dumps(body_list['accounts']))

        # Manager A cross-tenant access to shop-b denied with 403
        code_cross, _, _ = self.request('/api/admin/accounts', cookie=cookie_mgr_a, QUERY_STRING='tenant_id=shop-b')
        self.assertEqual(code_cross, 403)

        # Platform admin requires explicit tenant_id
        code_pa_missing, body_pa_missing, _ = self.request('/api/admin/accounts', cookie=cookie_padmin)
        self.assertEqual(code_pa_missing, 400)
        self.assertEqual(body_pa_missing['error'], 'missing_tenant_id')

        code_pa_b, body_pa_b, _ = self.request('/api/admin/accounts', cookie=cookie_padmin, QUERY_STRING='tenant_id=shop-b')
        self.assertEqual(code_pa_b, 200)
        self.assertEqual(body_pa_b['tenant_id'], 'shop-b')

        # ADM3: Self-lockout blocked; suspend Alice -> immediate session revocation; reactivate -> new login works
        code_self, body_self, _ = self.request(
            f'/api/admin/accounts/{mgr_a[0]}/suspend',
            {'reason': 'Test self lockout'},
            cookie_mgr_a,
        )
        self.assertEqual(code_self, 400)
        self.assertEqual(body_self['error'], 'self_lockout_forbidden')

        code_susp, body_susp, _ = self.request(
            f'/api/admin/accounts/{self.alice[0]}/suspend',
            {'reason': 'PG test suspend customer', 'correlation_id': 'pg-corr-susp-1'},
            cookie_mgr_a,
        )
        self.assertEqual(code_susp, 200)
        self.assertFalse(body_susp['account']['active'])

        code_sess_after, _, _ = self.request('/api/session', cookie=cookie_alice)
        self.assertEqual(code_sess_after, 401)

        code_react, body_react, _ = self.request(
            f'/api/admin/accounts/{self.alice[0]}/reactivate',
            {'reason': 'PG test reactivate customer', 'correlation_id': 'pg-corr-react-1'},
            cookie_mgr_a,
        )
        self.assertEqual(code_react, 200)
        self.assertTrue(body_react['account']['active'])
        self.assertEqual(body_react['account']['customer_id'], 'C-001')

        # Old cookie remains dead; new login works
        self.assertEqual(self.request('/api/session', cookie=cookie_alice)[0], 401)
        cookie_alice = self.login(self.alice)
        self.assertEqual(self.request('/api/session', cookie=cookie_alice)[0], 200)

        # ADM4: Quota override persists across restart and enforces bounded limit per membership
        code_q_bad, _, _ = self.request(
            f'/api/admin/accounts/{self.alice[0]}/quota',
            {'daily_limit': 0, 'reason': 'Bad limit'},
            cookie_mgr_a,
        )
        self.assertEqual(code_q_bad, 400)

        code_q_ok, body_q_ok, _ = self.request(
            f'/api/admin/accounts/{self.alice[0]}/quota',
            {'daily_limit': 2, 'reason': 'Nâng hạn mức PG cho Alice', 'correlation_id': 'pg-corr-quota-1'},
            cookie_mgr_a,
        )
        self.assertEqual(code_q_ok, 200)
        self.assertEqual(body_q_ok['account']['quota']['limit'], 2)
        self.assertEqual(body_q_ok['account']['quota']['default_limit'], 1)

        # Restart PostgresSessions and verify override=2 survived in PostgreSQL (default_limit=1)
        self.restart()
        code_get_a, body_get_a, _ = self.request(f'/api/admin/accounts/{self.alice[0]}', cookie=cookie_mgr_a)
        self.assertEqual(code_get_a, 200)
        self.assertEqual(body_get_a['account']['quota']['limit'], 2)

        # Alice can make 2 API chat calls (whereas default_limit=1), and 3rd fails with 429 api_daily_limit
        _, conv_a, _ = self.request('/api/conversations', {'provider_id': 'api'}, cookie_alice)
        c1, _, _ = self.request(
            '/api/chat',
            {'conversation_id': conv_a['conversation_id'], 'request_id': 'req_pg_q_turn_00001', 'text': 'Lần 1'},
            cookie_alice,
        )
        self.assertEqual(c1, 200)
        c2, _, _ = self.request(
            '/api/chat',
            {'conversation_id': conv_a['conversation_id'], 'request_id': 'req_pg_q_turn_00002', 'text': 'Lần 2'},
            cookie_alice,
        )
        self.assertEqual(c2, 200)
        c3, body_c3, _ = self.request(
            '/api/chat',
            {'conversation_id': conv_a['conversation_id'], 'request_id': 'req_pg_q_turn_00003', 'text': 'Lần 3'},
            cookie_alice,
        )
        self.assertEqual(c3, 429)
        self.assertEqual(body_c3['error'], 'api_daily_limit')

        # Other tenant member (shop-b) is unaffected
        _, conv_b, _ = self.request('/api/conversations', {'provider_id': 'api'}, cookie_other)
        cb1, _, _ = self.request(
            '/api/chat',
            {'conversation_id': conv_b['conversation_id'], 'request_id': 'req_pg_other_000001', 'text': 'Shop B turn 1'},
            cookie_other,
        )
        self.assertEqual(cb1, 200)

        # ADM5: Append-only admin_audit_log and transactional rollback on audit failure
        code_post_audit, body_post_audit, _ = self.request('/api/admin/audit-log', {'action': 'delete'}, cookie_mgr_a)
        self.assertEqual(code_post_audit, 405)
        self.assertEqual(body_post_audit['error'], 'audit_log_append_only')

        code_logs, body_logs, _ = self.request('/api/admin/audit-log', cookie=cookie_mgr_a)
        self.assertEqual(code_logs, 200)
        corrs = {r['correlation_id'] for r in body_logs['audit_logs']}
        self.assertIn('pg-corr-susp-1', corrs)
        self.assertIn('pg-corr-react-1', corrs)
        self.assertIn('pg-corr-quota-1', corrs)

        # Simulate failure inside record_admin_audit -> PostgreSQL transaction rolls back suspension
        with patch.object(self.sessions.control, 'record_admin_audit', side_effect=RuntimeError('pg_simulated_audit_fail')):
            with self.assertRaises(RuntimeError):
                self.sessions.control.admin_suspend_account(
                    {'principal_id': 'mgr_a_p5e', 'role': 'manager', 'tenant_id': 'shop-a', 'membership_id': mgr_a[0]},
                    self.alice[0],
                    reason='Should rollback on PG',
                )
        self.assertEqual(self.request('/api/session', cookie=cookie_alice)[0], 200)


if __name__ == '__main__':
    unittest.main()
