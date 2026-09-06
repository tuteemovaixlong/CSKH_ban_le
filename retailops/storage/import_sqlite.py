"""Import a stopped, copied v0.7 persistent workspace into an empty PostgreSQL target."""
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing

from retailops.storage.pg_schema import initialize
from retailops.storage.postgres import IDENTITY_SCHEMA, tenant_schema, transaction

IDENTITY_TABLES = ('tenants', 'principals', 'memberships', 'credentials', 'identity_rate',
                   'provider_daily_usage', 'identity_events')
BUSINESS_TABLES = ('customers', 'orders', 'proposals', 'business_events', 'conversations',
                   'agent_turns', 'provider_daily_usage')
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
            allowed_versions = (1, 2) if component == 'business' else (1,)
            if len(marker) != 1 or marker[0]['component'] != component or marker[0]['version'] not in allowed_versions:
                raise ValueError('Import requires identity v1 and business v1/v2 in a stopped persistent SQLite snapshot.')
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('SQLite snapshot failed integrity checks.')
            if component == 'business' and marker[0]['version'] == 2:
                tables = (*tables, 'graph_runs', 'graph_checkpoints', 'graph_writes')
            return {table: [dict(row) for row in db.execute('SELECT * FROM "'+table+'"')] for table in tables}
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
        # Login sessions are deliberately not copied. Existing personal codes still work.
    return {'result': 'POSTGRES_IMPORT_VERIFIED', 'sessions_imported': 0, 'tables': report}
