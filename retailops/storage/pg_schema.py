"""PostgreSQL v1 DDL. Migrations are explicit and atomic, never run by a web request."""
from retailops.storage.postgres import IDENTITY_SCHEMA, assert_schema, valid_schema

BUSINESS_DDL = [
    'CREATE TABLE customers (id TEXT PRIMARY KEY, name TEXT NOT NULL)',
    '''CREATE TABLE orders (id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
        name TEXT NOT NULL, variant TEXT NOT NULL, amount BIGINT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','delivered','cancelled')),
        version INTEGER NOT NULL DEFAULT 1, cancel_reason TEXT)''',
    'CREATE INDEX idx_orders_customer_id ON orders(customer_id)',
    '''CREATE TABLE proposals (id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
        order_id TEXT NOT NULL REFERENCES orders(id), order_version INTEGER NOT NULL, reason TEXT NOT NULL,
        expires_at DOUBLE PRECISION NOT NULL, state TEXT NOT NULL DEFAULT 'pending', confirm_key TEXT, result TEXT,
        UNIQUE(customer_id,confirm_key))''',
    '''CREATE TABLE business_events (id BIGSERIAL PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
        created_at DOUBLE PRECISION NOT NULL, kind TEXT NOT NULL, order_id TEXT, payload TEXT NOT NULL)''',
    'CREATE INDEX idx_business_events_customer_id_id ON business_events(customer_id,id)',
    '''CREATE TABLE conversations (id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
        order_id TEXT, product_id TEXT, revision INTEGER NOT NULL DEFAULT 0, expires_at DOUBLE PRECISION NOT NULL,
        provider_id TEXT NOT NULL DEFAULT 'custom')''',
    '''CREATE TABLE agent_turns (id BIGSERIAL PRIMARY KEY,
        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        customer_id TEXT NOT NULL REFERENCES customers(id), request_id TEXT NOT NULL, input_hash TEXT NOT NULL,
        messages TEXT NOT NULL, result TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL,
        UNIQUE(conversation_id,request_id))''',
    '''CREATE TABLE provider_daily_usage (day TEXT NOT NULL, provider_id TEXT NOT NULL,
        attempts INTEGER NOT NULL, PRIMARY KEY(day,provider_id))''',
]

IDENTITY_DDL = [
    '''CREATE TABLE tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL, storage_key TEXT UNIQUE NOT NULL,
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)))''',
    'CREATE TABLE principals (id TEXT PRIMARY KEY, name TEXT NOT NULL)',
    '''CREATE TABLE memberships (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
        principal_id TEXT NOT NULL REFERENCES principals(id), customer_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('customer','viewer')), active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
        auth_version INTEGER NOT NULL DEFAULT 1, UNIQUE(tenant_id,principal_id))''',
    '''CREATE TABLE credentials (hash TEXT PRIMARY KEY, membership_id TEXT NOT NULL REFERENCES memberships(id),
        created_at DOUBLE PRECISION NOT NULL)''',
    '''CREATE TABLE sessions (id TEXT PRIMARY KEY, membership_id TEXT NOT NULL REFERENCES memberships(id),
        auth_version INTEGER NOT NULL, expires_at DOUBLE PRECISION NOT NULL)''',
    'CREATE INDEX idx_sessions_membership ON sessions(membership_id)',
    'CREATE INDEX idx_sessions_expiry ON sessions(expires_at)',
    'CREATE TABLE identity_rate (bucket TEXT PRIMARY KEY, "window" BIGINT NOT NULL, count INTEGER NOT NULL)',
    '''CREATE TABLE provider_daily_usage (day TEXT NOT NULL, provider_id TEXT NOT NULL,
        attempts INTEGER NOT NULL, PRIMARY KEY(day,provider_id))''',
    '''CREATE TABLE identity_events (id BIGSERIAL PRIMARY KEY, created_at DOUBLE PRECISION NOT NULL,
        kind TEXT NOT NULL, tenant_id TEXT, membership_id TEXT)''',
]


def initialize(db, schema, component):
    from psycopg import sql
    valid_schema(schema)
    if (schema == IDENTITY_SCHEMA) != (component == 'identity'):
        raise ValueError('Schema and component mismatch.')
    exists = db.raw.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s', (schema,)).fetchone()
    if exists:
        if component == 'business':
            row = db.raw.execute(sql.SQL('SELECT component,version FROM {}.retailops_schema').format(sql.Identifier(schema))).fetchone()
            if row == {'component': 'business', 'version': 1}:
                db.raw.execute(sql.SQL('SET LOCAL search_path TO {}, pg_catalog').format(sql.Identifier(schema)))
                from retailops.workflow.schema import initialize as graph_schema
                graph_schema(db)
                db.execute("UPDATE retailops_schema SET version=2 WHERE component='business'")
        assert_schema(db, schema, component)
        return False
    db.raw.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    db.raw.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC').format(sql.Identifier(schema)))
    db.raw.execute(sql.SQL('SET LOCAL search_path TO {}, pg_catalog').format(sql.Identifier(schema)))
    for statement in IDENTITY_DDL if component == 'identity' else BUSINESS_DDL:
        db.raw.execute(statement)
    db.execute('CREATE TABLE retailops_schema (component TEXT PRIMARY KEY, version INTEGER NOT NULL)')
    if component == 'business':
        from retailops.workflow.schema import initialize as graph_schema
        graph_schema(db)
    db.execute('INSERT INTO retailops_schema VALUES (?,?)', (component, 2 if component == 'business' else 1))
    return True
