"""Explicit PostgreSQL DDL and staged business migrations."""
from retailops.storage.postgres import (BUSINESS_SCHEMA_CURRENT, IDENTITY_SCHEMA,
                                        assert_schema, valid_schema)

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

KNOWLEDGE_DDL = [
    '''CREATE TABLE IF NOT EXISTS knowledge_documents (
        id TEXT PRIMARY KEY, source_key TEXT NOT NULL UNIQUE, title TEXT NOT NULL, source_uri TEXT NOT NULL,
        checksum TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}',
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), updated_at DOUBLE PRECISION NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS knowledge_chunks (
        id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL CHECK(ordinal>=0), content TEXT NOT NULL CHECK(char_length(content) BETWEEN 1 AND 4000),
        embedding_model TEXT NOT NULL, embedding retailops_extensions.vector(384) NOT NULL,
        search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple',content)) STORED,
        UNIQUE(document_id,ordinal))''',
    'CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document ON knowledge_chunks(document_id,ordinal)',
    'CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_search ON knowledge_chunks USING gin(search_tsv)',
    '''CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding ON knowledge_chunks
        USING hnsw (embedding retailops_extensions.vector_cosine_ops)''',
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


def vector_extension(db):
    row = db.raw.execute("""SELECT n.nspname AS schema,e.extversion AS version FROM pg_extension e
        JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'""").fetchone()
    if not row or row['schema'] != 'retailops_extensions':
        raise ValueError('pgvector is not enabled in retailops_extensions. Run deploy/enable-pgvector.sh first.')
    return row['version']


def initialize_knowledge(db):
    vector_extension(db)
    for statement in KNOWLEDGE_DDL:
        db.raw.execute(statement)


def initialize(db, schema, component):
    from psycopg import sql
    valid_schema(schema)
    if (schema == IDENTITY_SCHEMA) != (component == 'identity'):
        raise ValueError('Schema and component mismatch.')
    exists = db.raw.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s', (schema,)).fetchone()
    if exists:
        row = db.raw.execute(sql.SQL('SELECT component,version FROM {}.retailops_schema').format(sql.Identifier(schema))).fetchone()
        if not row or row['component'] != component:
            raise ValueError('Unsupported PostgreSQL schema version or component.')
        if component == 'business':
            db.raw.execute(sql.SQL('SET LOCAL search_path TO {}, pg_catalog').format(sql.Identifier(schema)))
            if row['version'] == 1:
                from retailops.workflow.schema import initialize as graph_schema
                graph_schema(db)
                db.execute("UPDATE retailops_schema SET version=2 WHERE component='business'")
                row = {'component': 'business', 'version': 2}
            if row['version'] == 2:
                initialize_knowledge(db)
                db.execute("UPDATE retailops_schema SET version=? WHERE component='business'", (BUSINESS_SCHEMA_CURRENT,))
                row = {'component': 'business', 'version': BUSINESS_SCHEMA_CURRENT}
            if row['version'] != BUSINESS_SCHEMA_CURRENT:
                raise ValueError('Unsupported PostgreSQL schema version or component.')
        assert_schema(db, schema, component)
        return False
    if component == 'business':
        vector_extension(db)
    db.raw.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    db.raw.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC').format(sql.Identifier(schema)))
    db.raw.execute(sql.SQL('SET LOCAL search_path TO {}, pg_catalog').format(sql.Identifier(schema)))
    for statement in IDENTITY_DDL if component == 'identity' else BUSINESS_DDL:
        db.raw.execute(statement)
    db.execute('CREATE TABLE retailops_schema (component TEXT PRIMARY KEY, version INTEGER NOT NULL)')
    if component == 'business':
        from retailops.workflow.schema import initialize as graph_schema
        graph_schema(db)
        initialize_knowledge(db)
    db.execute('INSERT INTO retailops_schema VALUES (?,?)',
               (component, BUSINESS_SCHEMA_CURRENT if component == 'business' else 1))
    return True
