"""Deterministic regression checks for account-scoped quota and usage metadata."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from retailops.account_usage import AccountQuotaStore
from retailops.core import ApiError
from retailops.http.routes import api_result
from retailops.identity.store import IdentityStore


def main():
    with tempfile.TemporaryDirectory(prefix='retailops-account-usage-') as tmp:
        control = IdentityStore(Path(tmp) / 'identity.sqlite3')
        control.ensure_tenant('T-1', 'Tenant 1')
        first = control.create_membership('T-1', 'P-1', 'User 1', 'C-1', 'customer')
        second = control.create_membership('T-1', 'P-2', 'User 2', 'C-2', 'customer')
        a, b = AccountQuotaStore(control, first), AccountQuotaStore(control, second)

        a.reserve_api_attempt(2)
        a.reserve_api_attempt(2)
        try:
            a.reserve_api_attempt(2)
        except ApiError as exc:
            assert exc.status == 429 and exc.code == 'api_daily_limit'
        else:
            raise AssertionError('third account API reservation must be rejected')
        b.reserve_api_attempt(2)

        a.record_turn('custom', {
            'model_calls': 1, 'prompt_tokens': 100, 'generated_tokens': 10,
            'latency_ms': 1000.0, 'reported_cost_usd': None,
        }, success=True)
        a.record_turn('api', {
            'model_calls': 2, 'prompt_tokens': 200, 'generated_tokens': 20,
            'latency_ms': 3000.0, 'reported_cost_usd': 0.001234,
        }, success=True)

        first_snapshot = a.snapshot(2, api_configured=True, custom_configured=True)
        second_snapshot = b.snapshot(2, api_configured=True, custom_configured=True)
        assert first_snapshot['api_quota']['used'] == 2
        assert first_snapshot['api_quota']['remaining'] == 0
        assert second_snapshot['api_quota']['used'] == 1
        assert second_snapshot['api_quota']['remaining'] == 1
        assert first_snapshot['totals']['turns'] == 2
        assert first_snapshot['totals']['model_calls'] == 3
        assert first_snapshot['totals']['prompt_tokens'] == 300
        assert first_snapshot['totals']['generated_tokens'] == 30
        assert first_snapshot['totals']['latency_ms']['mean'] == 2000.0
        assert first_snapshot['totals']['reported_cost_usd']['known_sum'] == 0.001234
        assert first_snapshot['totals']['reported_cost_usd']['coverage'] == 0.5
        serialized = json.dumps(first_snapshot, sort_keys=True)
        assert first not in serialized and second not in serialized
        assert 'C-1' not in serialized and 'P-1' not in serialized

        class FakeApp:
            api_daily_limit = 2
            api_infer = object()
            infer = object()
            quota_store = a

        status, routed = api_result(FakeApp(), 'C-1', 'GET', '/api/account/usage')
        assert status == 200 and routed['schema'] == 'retailops-account-usage-v1'

        class FakeStore:
            @staticmethod
            def conversation(customer, cid):
                return {'provider_id': 'custom'}

        class FakeChatApp(FakeApp):
            store = FakeStore()
            @staticmethod
            def chat(customer, body):
                return {'provider_id': 'custom', 'replayed': False, 'trace': {
                    'model_calls': 1, 'prompt_tokens': 50, 'generated_tokens': 5,
                    'latency_ms': 500.0, 'reported_cost_usd': None,
                }}

        status, _ = api_result(FakeChatApp(), 'C-1', 'POST', '/api/chat',
                               {'conversation_id': '00000000-0000-0000-0000-000000000000',
                                'request_id': 'abcdefghijklmnop', 'text': 'demo'})
        assert status == 200
        after = a.snapshot(2)
        assert after['providers']['custom']['turns'] == 2
        assert after['totals']['prompt_tokens'] == 350

        class ReplayApp(FakeChatApp):
            @staticmethod
            def chat(customer, body):
                return {'provider_id': 'custom', 'replayed': True, 'trace': {
                    'model_calls': 1, 'prompt_tokens': 999, 'generated_tokens': 999,
                    'latency_ms': 999.0, 'reported_cost_usd': None,
                }}

        api_result(ReplayApp(), 'C-1', 'POST', '/api/chat',
                   {'conversation_id': '00000000-0000-0000-0000-000000000000',
                    'request_id': 'abcdefghijklmnop', 'text': 'demo'})
        replay_after = a.snapshot(2)
        assert replay_after['totals']['prompt_tokens'] == 350

        with control.connection() as db:
            global_api = db.execute("SELECT attempts FROM provider_daily_usage WHERE provider_id='api'").fetchone()
        assert global_api and global_api['attempts'] == 3

    print('ACCOUNT_USAGE_QUOTA_OK')


if __name__ == '__main__':
    main()
