"""Import a stopped, copied v0.7 persistent workspace into an empty PostgreSQL target."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from contextlib import closing

from retailops.business.schema import LEGACY_EXCHANGE_KIND_MAP
from retailops.storage.pg_schema import initialize
from retailops.storage.postgres import IDENTITY_SCHEMA, tenant_schema, transaction

IDENTITY_TABLES = ('tenants', 'principals', 'memberships', 'credentials', 'identity_rate',
                   'provider_daily_usage', 'identity_events', 'external_identities', 'customer_links', 'unresolved_collisions')
BUSINESS_TABLES = ('customers', 'products', 'product_variants', 'orders', 'proposals',
                   'business_events', 'conversations', 'agent_turns', 'provider_daily_usage')
SEQUENCES = {'identity': ('identity_events',), 'business': ('business_events', 'agent_turns')}


def digest(rows):
    # Independent of row order and PostgreSQL's physical column order.
    encoded = sorted(json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(',', ':')) for row in rows)
    return hashlib.sha256('\n'.join(encoded).encode()).hexdigest()


def read_database(path, component, tables):
    if not path.is_file() or path.is_symlink():
        raise ValueError('Snapshot database is missing or is a symbolic link.')
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN')
            marker = [dict(row) for row in db.execute('SELECT component,version FROM retailops_schema')]
            allowed_versions = (1, 2, 3, 4, 5, 6, 7, 8) if component == 'business' else (1, 2, 3, 4, 5)
            if len(marker) != 1 or marker[0]['component'] != component or marker[0]['version'] not in allowed_versions:
                raise ValueError('Import requires identity v1/v2/v3/v4/v5 and business v1/v2/v3/v4/v5/v6/v7/v8 in a stopped persistent SQLite snapshot.')
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('SQLite snapshot failed integrity checks.')
            if component == 'business':
                # Order tables to respect foreign keys: customers and products must precede orders,
                # and cases must precede handoff_episodes, case_feedback_events, and order_action_*.
                ordered = ['customers']
                if marker[0]['version'] >= 3:
                    ordered.extend(['products', 'product_variants'])
                ordered.extend(['orders', 'proposals', 'business_events', 'conversations',
                               'agent_turns', 'conversation_feedback', 'provider_daily_usage'])
                if marker[0]['version'] >= 2:
                    ordered.extend(['graph_runs', 'graph_checkpoints', 'graph_writes'])
                if marker[0]['version'] >= 4:
                    ordered.extend(['cases', 'handoff_episodes', 'case_feedback_events'])
                if marker[0]['version'] >= 5:
                    ordered.extend([
                        'order_action_requests',
                        'order_action_decisions',
                        'order_action_evidence',
                        'integration_outbox',
                    ])
                if marker[0]['version'] >= 7:
                    ordered.append('case_assist_turns')
                if marker[0]['version'] >= 8:
                    ordered.extend([
                        'integration_connectors',
                        'order_items',
                        'imported_events',
                        'order_purge_tombstones',
                        'shipments',
                        'shipment_events',
                        'payment_transactions',
                        'refunds',
                        'order_recipients',
                        'delivery_compensations',
                        'vouchers',
                    ])
                tables = tuple(ordered)
            existing_tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            result = {table: [dict(row) for row in db.execute('SELECT * FROM "'+table+'"')] for table in tables if table in existing_tables}
            if component == 'business':
                import_ts = round(time.time(), 3)
                for row in result.get('orders', ()):
                    row.setdefault('delivered_at', None)
                    if row.get('source_system') is None:
                        row['source_system'] = 'retailops_seed'
                    if 'external_order_id' not in row or (
                        row['external_order_id'] is None and row['source_system'] == 'retailops_seed'
                    ):
                        row['external_order_id'] = row['id']
                    if row.get('ordered_at') is None:
                        row['ordered_at'] = import_ts
                        row['ordered_at_backfilled'] = 1
                    else:
                        row.setdefault('ordered_at_backfilled', 0)
                    row.setdefault('payment_method', None)
                    if row.get('payment_status') is None:
                        row['payment_status'] = 'unpaid'
                    row.setdefault('shipping_fee', None)
                    row.setdefault('ship_to_area', None)
                    row.setdefault('promised_delivery_by', None)
                for row in result.get('imported_events', ()):
                    row.setdefault('event_type', None)
                    row.setdefault('sequence', None)
                    row.setdefault('received_via', None)
                    row.setdefault('payload_digest', None)
                    row.setdefault('redacted_fields', None)
                # A W3 snapshot (SQLite 5) predates general exchange: carry its requests over the same way
                # `migrate-v7` does, so the PostgreSQL target (always the current shape) accepts them.
                for row in result.get('order_action_requests', ()):
                    row['exchange_kind'] = LEGACY_EXCHANGE_KIND_MAP.get(row.get('exchange_kind'), row.get('exchange_kind'))
                    row.setdefault('target_variant_id', None)
                    row.setdefault('target_variant_label', None)
                for row in result.get('order_action_evidence', ()):
                    row.setdefault('filename', None)
                    row.setdefault('page_count', None)
                    row.setdefault('scan_status', None)
                    row.setdefault('scan_engine', None)
                    row.setdefault('scanned_at', None)
            if component == 'identity':
                for row in result.get('memberships', ()):
                    row.setdefault('disabled_reason', None)
                    if row.get('role') in ('viewer', 'platform_admin'):
                        was_active = int(row.get('active', 1)) != 0
                        was_missing_reason = not row.get('disabled_reason')
                        row['active'] = 0
                        row['disabled_reason'] = row.get('disabled_reason') or 'retired_legacy_role_r1_w1'
                        if was_active or was_missing_reason:
                            row['auth_version'] = int(row.get('auth_version') or 1) + 1
            return result
    except sqlite3.Error:
        raise ValueError('Cannot read the persistent SQLite snapshot; no target data was imported.') from None


def snapshot(source):
    source = Path(source)
    identity = read_database(source/'identity.sqlite3', 'identity', IDENTITY_TABLES)
    tenants = {}
    for tenant in identity['tenants']:
        key = tenant['storage_key']
        schema = tenant_schema(key)  # Reject paths supplied by a malformed snapshot.
        tenants[schema] = read_database(source/'tenants'/(key+'.sqlite3'), 'business', BUSINESS_TABLES)
    for member in identity['memberships']:
        tenant = next((t for t in identity['tenants'] if t['id'] == member['tenant_id']), None)
        if tenant is None or not any(c['id'] == member['customer_id'] for c in tenants[tenant_schema(tenant['storage_key'])]['customers']):
            raise ValueError('Snapshot membership references a missing tenant or customer.')
    return {IDENTITY_SCHEMA: identity, **tenants}


def import_snapshot(dsn, source):
    from psycopg import sql
    content = snapshot(source)  # Validate every source before opening a target write transaction.
    report = {}
    with transaction(dsn, write=True) as db:
        initialize(db, IDENTITY_SCHEMA, 'identity')
        if db.raw.execute("SELECT 1 FROM pg_namespace WHERE nspname ~ '^tenant_[a-f0-9]{32}$'").fetchone():
            raise ValueError('Target contains tenant schemas. Use a new PostgreSQL database for import.')
        # Explicitly refuse populated targets; never replace or merge existing customers.
        for table in (*IDENTITY_TABLES, 'sessions'):
            count = db.raw.execute(sql.SQL('SELECT count(*) AS total FROM {}.{}').format(
                sql.Identifier(IDENTITY_SCHEMA), sql.Identifier(table))).fetchone()['total']
            if count:
                raise ValueError('Target is not empty. Use a new PostgreSQL database for import.')
        for schema, tables in content.items():
            component = 'identity' if schema == IDENTITY_SCHEMA else 'business'
            if component == 'business':
                if db.raw.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s', (schema,)).fetchone():
                    raise ValueError('A target tenant schema already exists; import refused.')
                initialize(db, schema, component)
            for table, rows in tables.items():
                if rows:
                    columns = list(rows[0])
                    statement = sql.SQL('INSERT INTO {}.{} ({}) VALUES ({})').format(
                        sql.Identifier(schema), sql.Identifier(table),
                        sql.SQL(',').join(map(sql.Identifier, columns)),
                        sql.SQL(',').join(sql.Placeholder() for _ in columns))
                    with db.raw.cursor() as cursor:
                        cursor.executemany(statement, [[row[c] for c in columns] for row in rows])
                actual = [dict(row) for row in db.raw.execute(sql.SQL('SELECT * FROM {}.{}').format(
                    sql.Identifier(schema), sql.Identifier(table))).fetchall()]
                if digest(actual) != digest(rows):
                    raise ValueError('PostgreSQL content verification failed; import rolled back.')
                report[schema+'.'+table] = {'rows': len(rows), 'sha256': digest(rows)}
            for table in SEQUENCES[component]:
                db.raw.execute(sql.SQL('''SELECT setval(pg_get_serial_sequence(%s,'id'),
                    COALESCE(MAX(id),1),COUNT(*)>0) FROM {}.{}''').format(sql.Identifier(schema), sql.Identifier(table)),
                    (schema+'.'+table,))
            if component == 'business':
                if 'conversation_feedback' in tables:
                    db.raw.execute(sql.SQL('''SELECT setval(pg_get_serial_sequence(%s,'id'),
                        COALESCE(MAX(id),1),COUNT(*)>0) FROM {}.conversation_feedback''').format(sql.Identifier(schema)),
                        (schema+'.conversation_feedback',))
                if 'cases' not in tables:
                    from retailops.business.schema import backfill_business_v5_cases
                    db.raw.execute(sql.SQL('SET LOCAL search_path TO {}, pg_catalog').format(sql.Identifier(schema)))
                    backfill_business_v5_cases(db)
        # Login sessions are deliberately not copied. Existing personal codes still work.
    return {'result': 'POSTGRES_IMPORT_VERIFIED', 'sessions_imported': 0, 'tables': report}
