"""Account-scoped AI usage built on the existing durable daily counter table.

The ledger stores only aggregates. It never stores prompts, answers, credentials,
session ids, customer ids, or provider keys. API quota reservation happens before
network I/O; trace aggregates are observational and are not an invoice ledger.
"""
from __future__ import annotations

import hashlib
import math
import time
from datetime import datetime, timedelta, timezone

from retailops.core import require

_PROVIDERS = ('custom', 'api')
_METRICS = (
    'turns', 'success', 'failed', 'model_calls', 'prompt_tokens',
    'generated_tokens', 'latency_ms_total', 'latency_samples',
    'cost_microusd', 'cost_known',
)


def _non_negative_int(value):
    return type(value) is int and value >= 0


def _trace_number(trace, name):
    value = trace.get(name) if isinstance(trace, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return value


class AccountQuotaStore:
    """Membership-scoped view over IdentityStore.provider_daily_usage."""

    def __init__(self, control, membership_id):
        if not isinstance(membership_id, str) or not membership_id:
            raise ValueError('Account usage requires a membership id.')
        self.control = control
        self.subject = hashlib.sha256(membership_id.encode()).hexdigest()[:24]

    def _key(self, provider, metric):
        if provider not in _PROVIDERS or metric not in _METRICS + ('attempts',):
            raise ValueError('Invalid account usage metric.')
        return f'acct:{self.subject}:{provider}:{metric}'

    @staticmethod
    def _increment(db, day, key, amount):
        if not _non_negative_int(amount):
            raise ValueError('Usage counters must be non-negative integers.')
        if amount == 0:
            return
        db.execute('''INSERT INTO provider_daily_usage(day,provider_id,attempts) VALUES (?,?,?)
            ON CONFLICT(day,provider_id) DO UPDATE SET attempts=provider_daily_usage.attempts+excluded.attempts''',
            (day, key, amount))

    @staticmethod
    def _prune(db):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=31)).date().isoformat()
        db.execute('DELETE FROM provider_daily_usage WHERE day < ?', (cutoff,))

    def reserve_api_attempt(self, limit):
        """Reserve one account API turn before provider I/O."""
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError('API daily limit must be from 1 to 10000.')
        day = time.strftime('%Y-%m-%d', time.gmtime())
        key = self._key('api', 'attempts')
        with self.control.connection(write=True) as db:
            row = db.execute('SELECT attempts FROM provider_daily_usage WHERE day=? AND provider_id=?',
                             (day, key)).fetchone()
            used = 0 if row is None else row['attempts']
            require(used < limit, 429, 'api_daily_limit',
                    'Tài khoản đã hết lượt chat API hôm nay (UTC). Bạn có thể chọn custom model đang được cấu hình.')
            self._increment(db, day, key, 1)
            # Preserve the legacy provider-wide counter for operations visibility only.
            self._increment(db, day, 'api', 1)
            self._prune(db)

    def record_turn(self, provider, trace, *, success):
        """Record one HTTP chat outcome. Replayed saved responses must be skipped by caller."""
        if provider not in _PROVIDERS:
            raise ValueError('Invalid provider for account usage.')
        day = time.strftime('%Y-%m-%d', time.gmtime())
        model_calls = _trace_number(trace, 'model_calls')
        prompt_tokens = _trace_number(trace, 'prompt_tokens')
        generated_tokens = _trace_number(trace, 'generated_tokens')
        latency_ms = _trace_number(trace, 'latency_ms')
        reported_cost = _trace_number(trace, 'reported_cost_usd')
        with self.control.connection(write=True) as db:
            self._increment(db, day, self._key(provider, 'turns'), 1)
            self._increment(db, day, self._key(provider, 'success' if success else 'failed'), 1)
            if model_calls is not None:
                self._increment(db, day, self._key(provider, 'model_calls'), int(model_calls))
            if prompt_tokens is not None:
                self._increment(db, day, self._key(provider, 'prompt_tokens'), int(prompt_tokens))
            if generated_tokens is not None:
                self._increment(db, day, self._key(provider, 'generated_tokens'), int(generated_tokens))
            if latency_ms is not None:
                self._increment(db, day, self._key(provider, 'latency_ms_total'), int(round(latency_ms)))
                self._increment(db, day, self._key(provider, 'latency_samples'), 1)
            if reported_cost is not None:
                self._increment(db, day, self._key(provider, 'cost_microusd'), int(round(reported_cost * 1_000_000)))
                self._increment(db, day, self._key(provider, 'cost_known'), 1)
            self._prune(db)

    def snapshot(self, api_daily_limit, *, api_configured=False, custom_configured=False):
        if type(api_daily_limit) is not int or not 1 <= api_daily_limit <= 10000:
            raise ValueError('API daily limit must be from 1 to 10000.')
        now = datetime.now(timezone.utc)
        day = now.date().isoformat()
        prefix = f'acct:{self.subject}:'
        with self.control.connection() as db:
            rows = db.execute('SELECT provider_id,attempts FROM provider_daily_usage WHERE day=? AND provider_id LIKE ?',
                              (day, prefix + '%')).fetchall()
        values = {row['provider_id']: row['attempts'] for row in rows}

        def provider_view(provider):
            metrics = {name: values.get(self._key(provider, name), 0) for name in _METRICS}
            turns = metrics['turns']
            samples = metrics['latency_samples']
            known = metrics['cost_known']
            return {
                'turns': turns,
                'successful_turns': metrics['success'],
                'failed_turns': metrics['failed'],
                'model_calls': metrics['model_calls'],
                'prompt_tokens': metrics['prompt_tokens'],
                'generated_tokens': metrics['generated_tokens'],
                'latency_ms': {
                    'mean': round(metrics['latency_ms_total'] / samples, 2) if samples else None,
                    'samples': samples,
                },
                'reported_cost_usd': {
                    'known_sum': round(metrics['cost_microusd'] / 1_000_000, 6) if known else None,
                    'known_count': known,
                    'coverage': round(known / turns, 6) if turns else 0.0,
                },
            }

        providers = {provider: provider_view(provider) for provider in _PROVIDERS}
        api_used = values.get(self._key('api', 'attempts'), 0)
        total_turns = sum(item['turns'] for item in providers.values())
        total_model_calls = sum(item['model_calls'] for item in providers.values())
        total_prompt = sum(item['prompt_tokens'] for item in providers.values())
        total_generated = sum(item['generated_tokens'] for item in providers.values())
        total_latency_samples = sum(item['latency_ms']['samples'] for item in providers.values())
        latency_total = sum(
            (item['latency_ms']['mean'] or 0) * item['latency_ms']['samples']
            for item in providers.values()
        )
        cost_known_count = sum(item['reported_cost_usd']['known_count'] for item in providers.values())
        cost_known_values = [item['reported_cost_usd']['known_sum'] for item in providers.values()
                             if item['reported_cost_usd']['known_sum'] is not None]
        tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        return {
            'schema': 'retailops-account-usage-v1',
            'day_utc': day,
            'reset_at': tomorrow.timestamp(),
            'api_configured': bool(api_configured),
            'custom_configured': bool(custom_configured),
            'api_quota': {
                'limit': api_daily_limit,
                'used': api_used,
                'remaining': max(0, api_daily_limit - api_used),
                'scope': 'membership / UTC day',
                'reservation_policy': 'reserved before provider I/O; failed or timed-out API attempts may consume quota',
            },
            'totals': {
                'turns': total_turns,
                'model_calls': total_model_calls,
                'prompt_tokens': total_prompt,
                'generated_tokens': total_generated,
                'latency_ms': {
                    'mean': round(latency_total / total_latency_samples, 2) if total_latency_samples else None,
                    'samples': total_latency_samples,
                },
                'reported_cost_usd': {
                    'known_sum': round(sum(cost_known_values), 6) if cost_known_values else None,
                    'known_count': cost_known_count,
                    'coverage': round(cost_known_count / total_turns, 6) if total_turns else 0.0,
                },
            },
            'providers': providers,
            'measurement_scope': (
                'Account quota reservation is authoritative for this demo. Token, latency and reported-cost aggregates '
                'come from recorded chat traces and are not provider billing reconciliation.'
            ),
        }
