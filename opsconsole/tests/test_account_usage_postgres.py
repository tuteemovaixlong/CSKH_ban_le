"""Account usage SQL integration against the disposable CI PostgreSQL database."""
import hashlib
import os
import unittest
import uuid

DSN = os.environ.get('RETAILOPS_TEST_DATABASE_URL')


@unittest.skipUnless(DSN, 'Requires dedicated CI PostgreSQL database')
class AccountUsagePostgresTests(unittest.TestCase):
    def test_membership_quota_route_trace_and_replay(self):
        import psycopg
        from retailops.account_usage import AccountQuotaStore
        from retailops.http.routes import api_result
        from retailops.storage.pg_repositories import PostgresIdentityStore

        control = PostgresIdentityStore(DSN, create=True)
        suffix = uuid.uuid4().hex[:12]
        tenant_id = 'quota-' + suffix
        principal_id = 'principal-' + suffix
        tenant = control.ensure_tenant(tenant_id, 'Quota integration fixture')
        membership = control.create_membership(tenant_id, principal_id, 'Quota User', 'C-001', 'customer')
        subject = hashlib.sha256(membership.encode()).hexdigest()[:24]
        ledger = AccountQuotaStore(control, membership)
        try:
            ledger.reserve_api_attempt(3)
            ledger.record_turn('api', {
                'model_calls': 2,
                'prompt_tokens': 321,
                'generated_tokens': 23,
                'latency_ms': 1234.5,
                'reported_cost_usd': 0.002345,
            }, success=True)

            class UsageApp:
                api_daily_limit = 3
                api_infer = object()
                infer = object()
                quota_store = ledger

            status, report = api_result(UsageApp(), 'C-001', 'GET', '/api/account/usage')
            self.assertEqual(status, 200)
            self.assertEqual(report['schema'], 'retailops-account-usage-v1')
            self.assertEqual(report['api_quota']['used'], 1)
            self.assertEqual(report['api_quota']['remaining'], 2)
            self.assertEqual(report['totals']['prompt_tokens'], 321)
            self.assertEqual(report['totals']['generated_tokens'], 23)
            self.assertEqual(report['totals']['model_calls'], 2)
            self.assertEqual(report['totals']['reported_cost_usd']['known_sum'], 0.002345)
            self.assertNotIn(membership, str(report))
            self.assertNotIn(principal_id, str(report))
            self.assertNotIn('C-001', str(report))

            class FakeStore:
                @staticmethod
                def conversation(customer, conversation_id):
                    return {'provider_id': 'custom'}

            class ChatApp(UsageApp):
                store = FakeStore()
                @staticmethod
                def chat(customer, body):
                    return {'provider_id': 'custom', 'replayed': False, 'trace': {
                        'model_calls': 1, 'prompt_tokens': 50, 'generated_tokens': 5,
                        'latency_ms': 500.0, 'reported_cost_usd': None,
                    }}

            status, _ = api_result(ChatApp(), 'C-001', 'POST', '/api/chat',
                                   {'conversation_id': '00000000-0000-0000-0000-000000000000',
                                    'request_id': 'abcdefghijklmnop', 'text': 'demo'})
            self.assertEqual(status, 200)
            after_chat = ledger.snapshot(3)
            self.assertEqual(after_chat['providers']['custom']['turns'], 1)
            self.assertEqual(after_chat['totals']['prompt_tokens'], 371)

            class ReplayApp(ChatApp):
                @staticmethod
                def chat(customer, body):
                    return {'provider_id': 'custom', 'replayed': True, 'trace': {
                        'model_calls': 1, 'prompt_tokens': 999, 'generated_tokens': 999,
                        'latency_ms': 999.0, 'reported_cost_usd': None,
                    }}

            status, _ = api_result(ReplayApp(), 'C-001', 'POST', '/api/chat',
                                   {'conversation_id': '00000000-0000-0000-0000-000000000000',
                                    'request_id': 'abcdefghijklmnop', 'text': 'demo'})
            self.assertEqual(status, 200)
            after_replay = ledger.snapshot(3)
            self.assertEqual(after_replay['totals']['prompt_tokens'], 371)
            self.assertEqual(after_replay['providers']['custom']['turns'], 1)
        finally:
            with psycopg.connect(DSN) as db:
                db.execute("DELETE FROM retailops_identity.provider_daily_usage WHERE provider_id LIKE %s", ('acct:' + subject + ':%',))
                db.execute("DELETE FROM retailops_identity.sessions WHERE membership_id=%s", (membership,))
                db.execute("DELETE FROM retailops_identity.credentials WHERE membership_id=%s", (membership,))
                db.execute("DELETE FROM retailops_identity.identity_events WHERE tenant_id=%s OR membership_id=%s", (tenant_id, membership))
                db.execute("DELETE FROM retailops_identity.memberships WHERE id=%s", (membership,))
                db.execute("DELETE FROM retailops_identity.principals WHERE id=%s", (principal_id,))
                db.execute("DELETE FROM retailops_identity.tenants WHERE id=%s", (tenant['id'],))


if __name__ == '__main__':
    unittest.main()
