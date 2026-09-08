"""Deterministic dependency-light checks for account-scoped quota metadata."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from retailops.account_usage import AccountQuotaStore
from retailops.core import ApiError
from retailops.identity.store import IdentityStore


def ui_contracts():
    customer = (ROOT / 'web' / 'chat-focus.js').read_text(encoding='utf-8')
    admin = (ROOT / 'opsconsole' / 'web' / 'admin.js').read_text(encoding='utf-8')
    for token in ('/api/account/usage', 'api_quota', 'prompt_tokens', 'generated_tokens',
                  'reported_cost_usd', 'remaining', 'reset_at'):
        assert token in customer, f'customer account usage UI lost contract: {token}'
    assert "dataMode !== 'persistent-demo'" in customer, 'account usage control must stay persistent-account only'
    assert 'credentials: \'same-origin\'' in customer, 'account usage must use the authenticated same-origin cookie'
    for token in ('routerOnly', 'Latency p50', 'Prompt tokens', 'Output tokens',
                  'inference_calls = 0'):
        assert token in admin, f'admin usage/evaluation UI lost contract: {token}'


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

        # Replays are deliberately not part of this low-level ledger contract; the
        # HTTP integration test verifies that route-level replay filtering happens.
        with control.connection() as db:
            global_api = db.execute("SELECT attempts FROM provider_daily_usage WHERE provider_id='api'").fetchone()
        assert global_api and global_api['attempts'] == 3

    ui_contracts()
    print('ACCOUNT_USAGE_QUOTA_OK')


if __name__ == '__main__':
    main()
