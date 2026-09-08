"""Read-only metadata snapshot. Never select credentials, transcripts or answers."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import sys
import time
from opsconsole.evaluation import trace_summary
from opsconsole.metrics import trace_metrics, ratio

WINDOWS = (1, 7, 30)
EVENTS = frozenset(('agent_replied', 'agent_failed', 'order_viewed', 'order_cancelled',
                    'cancellation_proposed', 'proposal_dismissed'))
TEST_PREFIXES = ('e2e-', 'eval-', 'ci-', 'test-')


def test_tenant(tenant):
    return tenant.startswith(TEST_PREFIXES)


def window(records, logins, now, days):
    cutoff = now - days * 86400
    rows = [r for r in records if cutoff <= r['created_at'] <= now]
    logins = [r for r in logins if cutoff <= r['created_at'] <= now]
    kinds = Counter(r['kind'] for r in rows)
    traces = [r['trace'] for r in rows if r['kind'] in ('agent_replied', 'agent_failed') and r.get('trace')]
    by_day = Counter(datetime.fromtimestamp(r['created_at'], timezone.utc).strftime('%Y-%m-%d') for r in rows)
    models = {}
    for trace in traces:
        key = (trace.get('provider') or 'unknown') + ' / ' + (trace.get('model') or 'unknown')
        models.setdefault(key, []).append(trace)
    return {'window_days': days, 'events': len(rows), 'login_events': len(logins),
            'unique_login_principals': len({r['principal'] for r in logins}),
            'active_customer_bindings': len({(r['tenant'], r['customer']) for r in rows}),
            'active_tenants': len({r['tenant'] for r in rows}), 'event_counts': dict(kinds),
            'recorded_chat_outcomes': kinds['agent_replied'] + kinds['agent_failed'],
            'recorded_chat_success_rate': ratio(kinds['agent_replied'], kinds['agent_replied'] + kinds['agent_failed']),
            'daily_events_utc': dict(sorted(by_day.items())), 'usage': trace_metrics(traces),
            'by_model': {key: trace_metrics(values) for key, values in sorted(models.items())},
            'conversations': None, 'browser_messages': None, 'retry_rate': None, 'satisfaction': None,
            'cancellation_funnel': None}


def aggregate(records, logins, now, salt, *, source_partial=False):
    traffic = {name: [] for name in ('demo_user', 'test')}
    login_traffic = {name: [] for name in ('demo_user', 'test')}
    for record in records:
        traffic['test' if test_tenant(record['tenant']) else 'demo_user'].append(record)
    for record in logins:
        login_traffic['test' if test_tenant(record['tenant']) else 'demo_user'].append(record)
    tenants = []
    for tenant in sorted({r['tenant'] for r in traffic['demo_user']}):
        label = 'tenant-' + hmac.new(salt, tenant.encode(), hashlib.sha256).hexdigest()[:16]
        tenants.append({'tenant': label, 'last_30_days': window([r for r in traffic['demo_user'] if r['tenant'] == tenant],
                       [r for r in login_traffic['demo_user'] if r['tenant'] == tenant], now, 30)})
    return {'schema': 'retailops-usage-v1', 'generated_at': now, 'timezone': 'UTC',
            'traffic_policy': 'Known e2e-/eval-/ci-/test- tenant prefixes excluded from demo_user (heuristic, not a security boundary).',
            'source': 'retained business_events + successful identity login events; not HTTP request logs',
            'source_partial': source_partial,
            'windows': {name: {str(days): window(rows, login_traffic[name], now, days) for days in WINDOWS}
                        for name, rows in traffic.items()},
            'tenants': tenants,
            'limitations': [
                'All traffic is synthetic-demo; no claim of real customers.',
                'Login principals are not DAU; business events identify tenant/customer, not the acting principal.',
                'One chat may trigger multiple business events. Event count is not message count.',
                'Failures before an audit event and HTTP replay requests are not observed here.',
                'Conversation/message history is bounded; it is not used as an analytics ledger.',
                'Recorded trace usage may repeat on checkpoint retries; this is not billing reconciliation.',
                'No user text, model answers, session IDs or raw principal/customer IDs exported.',
                'No funnel conversion rate without a correlated cohort and window definition.']}


def export_snapshot(salt, *, max_rows=100000):
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from retailops.config import database_settings
    from retailops.storage.postgres import tenant_schema
    if len(salt) < 32:
        raise ValueError('Telemetry pseudonym key required')
    backend, dsn = database_settings(os.environ)
    if backend != 'postgresql':
        raise ValueError('PostgreSQL required for deployed usage export')
    now = time.time()
    records, logins, partial = [], [], False
    with psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row) as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        db.execute("SET LOCAL statement_timeout='5s'")
        db.execute("SET LOCAL lock_timeout='1s'")
        tenants = db.execute('SELECT id, storage_key FROM retailops_identity.tenants ORDER BY id LIMIT 501').fetchall()
        if len(tenants) > 500:
            raise ValueError('Tenant scan budget exceeded')
        rows = db.execute('''SELECT e.created_at,e.tenant_id,m.principal_id FROM retailops_identity.identity_events e
            JOIN retailops_identity.memberships m ON m.id=e.membership_id
            WHERE e.kind='login' AND e.created_at>=%s AND e.created_at<=%s ORDER BY e.id DESC LIMIT %s''',
            (now-30*86400, now, max_rows+1)).fetchall()
        partial |= len(rows) > max_rows
        logins = [{'created_at': r['created_at'], 'tenant': r['tenant_id'], 'principal': r['principal_id']}
                  for r in rows[:max_rows] if r['tenant_id']]
        earliest = db.execute('SELECT MIN(created_at) AS earliest FROM retailops_identity.identity_events').fetchone()['earliest']
        for tenant in tenants:
            schema = tenant_schema(tenant['storage_key'])
            exists = db.execute('SELECT to_regclass(%s) AS name', (schema + '.business_events',)).fetchone()['name']
            if not exists:
                partial = True
                continue
            remaining = max_rows - len(records)
            if remaining <= 0:
                partial = True
                break
            query = sql.SQL('''SELECT created_at, customer_id, kind, payload::jsonb->'trace' AS trace
                FROM {}.business_events WHERE created_at >= %s AND created_at <= %s
                ORDER BY id DESC LIMIT %s''').format(sql.Identifier(schema))
            events = db.execute(query, (now-30*86400, now, remaining+1)).fetchall()
            partial |= len(events) > remaining
            for row in events[:remaining]:
                records.append({'tenant': tenant['id'], 'customer': row['customer_id'],
                    'created_at': row['created_at'], 'kind': row['kind'] if row['kind'] in EVENTS else 'other_event',
                    'trace': trace_summary(row['trace']) if isinstance(row['trace'], dict) else None})
        result = aggregate(records, logins, now, salt, source_partial=partial)
        result['earliest_retained_identity_event'] = earliest
        return result


if __name__ == '__main__':
    try:
        key = sys.stdin.buffer.read(129)
        if not 32 <= len(key) <= 128:
            raise ValueError('Invalid key length')
        print(json.dumps(export_snapshot(key), allow_nan=False, ensure_ascii=False))
    except Exception:
        print('USAGE_EXPORT_FAILED (snapshot unchanged; no connection details logged)', file=sys.stderr)
        raise SystemExit(1)
