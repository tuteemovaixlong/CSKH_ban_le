"""Integration runs only with the CI disposable database, never the live DSN."""
import json
import os
import unittest
from unittest.mock import patch
import uuid

DSN = os.environ.get('RETAILOPS_TEST_DATABASE_URL')


@unittest.skipUnless(DSN, 'Requires dedicated CI PostgreSQL database')
class UsagePostgresTests(unittest.TestCase):
    def test_export_is_read_only_and_excludes_content(self):
        import psycopg
        from psycopg import sql
        from retailops.storage.pg_repositories import PostgresIdentityStore, PostgresBusinessStore
        from retailops.storage.postgres import tenant_schema
        from opsconsole.usage import export_snapshot
        tid = 'eval-console-' + uuid.uuid4().hex[:16]
        control = PostgresIdentityStore(DSN, create=True)
        tenant = control.ensure_tenant(tid, 'Console integration fixture')
        schema = tenant_schema(tenant['storage_key'])
        store = PostgresBusinessStore(DSN, tenant['storage_key'], create=True)
        store.seed()
        try:
            store.event('C-001', 'agent_replied', trace={'provider': 'custom', 'model': 'test-model',
                        'model_calls': 1, 'prompt_tokens': 123, 'generated_tokens': 7,
                        'latency_ms': 42, 'tools': [{'name': 'get_order'}],
                        'message': 'PRIVATE_SENTINEL'}, raw_prompt='DO_NOT_EXPORT')
            before = store.orders('C-001')
            env = {'RETAILOPS_STORAGE_BACKEND': 'postgresql', 'RETAILOPS_DATABASE_URL': DSN,
                   'RETAILOPS_DATABASE_URL_FILE': ''}
            with patch.dict(os.environ, env):
                report = export_snapshot(b't'*32)
            self.assertEqual(store.orders('C-001'), before)
            self.assertGreaterEqual(report['windows']['test']['1']['events'], 1)
            serialized = json.dumps(report)
            for text in ('PRIVATE_SENTINEL', 'DO_NOT_EXPORT', DSN, tid):
                self.assertNotIn(text, serialized)
        finally:
            with psycopg.connect(DSN) as db:
                db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
                db.execute('DELETE FROM retailops_identity.identity_events WHERE tenant_id=%s', (tid,))
                db.execute('DELETE FROM retailops_identity.tenants WHERE id=%s', (tid,))
