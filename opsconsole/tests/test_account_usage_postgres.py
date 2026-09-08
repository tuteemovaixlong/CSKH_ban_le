"""Account usage SQL integration against the disposable CI PostgreSQL database."""
import hashlib
import os
import unittest
import uuid

DSN = os.environ.get('RETAILOPS_TEST_DATABASE_URL')


@unittest.skipUnless(DSN, 'Requires dedicated CI PostgreSQL database')
class AccountUsagePostgresTests(unittest.TestCase):
    def test_membership_quota_and_trace_aggregates(self):
        import psycopg
        from retailops.account_usage import AccountQuotaStore
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
            report = ledger.snapshot(3, api_configured=True)
            self.assertEqual(report['api_quota']['used'], 1)
            self.assertEqual(report['api_quota']['remaining'], 2)
            self.assertEqual(report['totals']['prompt_tokens'], 321)
            self.assertEqual(report['totals']['generated_tokens'], 23)
            self.assertEqual(report['totals']['model_calls'], 2)
            self.assertEqual(report['totals']['reported_cost_usd']['known_sum'], 0.002345)
            self.assertNotIn(membership, str(report))
            self.assertNotIn(principal_id, str(report))
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
