"""Explicit PostgreSQL DDL and staged business migrations."""
from retailops.core import ApiError
from retailops.storage.postgres import (BUSINESS_SCHEMA_CURRENT, BUSINESS_V5_SCHEMA_VERSION,
                                        IDENTITY_SCHEMA, IDENTITY_SCHEMA_CURRENT,
                                        assert_schema, valid_schema)

BUSINESS_DDL = [
    'CREATE TABLE customers (id TEXT PRIMARY KEY, name TEXT NOT NULL)',
    '''CREATE TABLE products (id TEXT PRIMARY KEY, name TEXT NOT NULL,
        aliases TEXT NOT NULL DEFAULT '[]', category TEXT, price BIGINT,
        stock INTEGER, warranty_days INTEGER, description TEXT,
        variants TEXT NOT NULL DEFAULT '[]', material TEXT, care TEXT,
        is_system_immutable INTEGER NOT NULL DEFAULT 0 CHECK(is_system_immutable IN (0,1)),
        extra_data TEXT NOT NULL DEFAULT '{}',
        created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL)''',
    '''CREATE TABLE product_variants (id TEXT PRIMARY KEY,
        product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        variant_name TEXT NOT NULL, size TEXT, color TEXT, stock INTEGER,
        sku TEXT, price BIGINT)''',
    'CREATE INDEX idx_variants_product ON product_variants(product_id)',
    'CREATE INDEX idx_variants_size_color ON product_variants(product_id, size, color)',
    '''CREATE TABLE orders (id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
        product_id TEXT REFERENCES products(id),
        name TEXT NOT NULL, variant TEXT NOT NULL, amount BIGINT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','delivered','cancelled')),
        version INTEGER NOT NULL DEFAULT 1, cancel_reason TEXT,
        delivered_at DOUBLE PRECISION)''',
    'CREATE INDEX idx_orders_customer_id ON orders(customer_id)',
    'CREATE INDEX idx_orders_product_id ON orders(product_id)',
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
    '''CREATE TABLE IF NOT EXISTS conversation_feedback (
        id BIGSERIAL PRIMARY KEY,
        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        turn_id BIGINT REFERENCES agent_turns(id) ON DELETE SET NULL,
        customer_id TEXT NOT NULL REFERENCES customers(id),
        feedback_type TEXT NOT NULL CHECK(feedback_type IN ('turn_rating', 'session_csat', 'human_handoff')),
        rating INTEGER CHECK(rating BETWEEN 1 AND 5),
        sentiment_flag TEXT CHECK(sentiment_flag IN ('positive', 'negative', 'neutral')),
        reason_code TEXT,
        comment TEXT,
        created_at DOUBLE PRECISION NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS idx_feedback_conv ON conversation_feedback(conversation_id)',
    'CREATE INDEX IF NOT EXISTS idx_feedback_type ON conversation_feedback(feedback_type)',
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
        role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
        auth_version INTEGER NOT NULL DEFAULT 1, disabled_reason TEXT,
        CONSTRAINT memberships_role_check CHECK(role IN ('customer','staff','manager') OR (role IN ('viewer','platform_admin') AND active = 0)),
        UNIQUE(tenant_id,principal_id))''',
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
    '''CREATE TABLE external_identities (id TEXT PRIMARY KEY, issuer TEXT NOT NULL,
        sub TEXT NOT NULL, principal_id TEXT NOT NULL REFERENCES principals(id), email TEXT,
        created_at DOUBLE PRECISION NOT NULL, UNIQUE(issuer, sub))''',
    '''CREATE TABLE customer_links (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
        principal_id TEXT NOT NULL REFERENCES principals(id), customer_id TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL, UNIQUE(tenant_id, principal_id), UNIQUE(tenant_id, customer_id))''',
    '''CREATE TABLE unresolved_collisions (tenant_id TEXT NOT NULL REFERENCES tenants(id),
        customer_id TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL, PRIMARY KEY(tenant_id, customer_id))''',
    '''CREATE TABLE IF NOT EXISTS reconciliation_journal (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id),
        colliding_customer_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('started', 'business_committed', 'identity_committed', 'completed')),
        plan_json TEXT NOT NULL,
        plan_hash TEXT,
        error_message TEXT,
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS idx_reconciliation_journal_tenant ON reconciliation_journal(tenant_id, colliding_customer_id)',
]

# Phase 5 / P5-C (sales import). Additive and idempotent: used for fresh schemas AND applied to
# existing schemas by initialize()/`database migrate`, without bumping the schema version.
P5C_BUSINESS_DDL = [
    '''CREATE TABLE IF NOT EXISTS order_items (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
        order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        product_id TEXT NOT NULL REFERENCES products(id), variant_id TEXT,
        product_title TEXT NOT NULL, variant_name TEXT,
        quantity INTEGER NOT NULL CHECK(quantity > 0),
        unit_price BIGINT NOT NULL CHECK(unit_price >= 0),
        subtotal BIGINT NOT NULL CHECK(subtotal >= 0),
        created_at DOUBLE PRECISION NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id)',
    '''CREATE TABLE IF NOT EXISTS imported_events (id TEXT PRIMARY KEY, source_system TEXT NOT NULL,
        event_id TEXT NOT NULL, tenant_id TEXT NOT NULL, external_customer_id TEXT NOT NULL,
        customer_id TEXT NOT NULL, order_id TEXT NOT NULL, status TEXT NOT NULL,
        total BIGINT NOT NULL, currency TEXT NOT NULL, payload_json TEXT NOT NULL,
        signature TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL,
        UNIQUE(source_system, event_id))''',
    'CREATE INDEX IF NOT EXISTS idx_imported_events_tenant_order ON imported_events(tenant_id, order_id)',
    '''CREATE INDEX IF NOT EXISTS idx_imported_events_external
        ON imported_events(tenant_id, source_system, external_customer_id)''',
    '''CREATE TABLE IF NOT EXISTS order_purge_tombstones (
        order_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        customer_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        status TEXT NOT NULL,
        amount BIGINT NOT NULL,
        snapshot_name TEXT NOT NULL,
        variant TEXT,
        reason TEXT NOT NULL,
        operator_id TEXT NOT NULL,
        purged_at DOUBLE PRECISION NOT NULL,
        pre_counts_json TEXT NOT NULL,
        post_counts_json TEXT NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS idx_order_purge_tombstones_customer ON order_purge_tombstones(customer_id, product_id)',
]

P5C_IDENTITY_DDL = [
    '''CREATE TABLE IF NOT EXISTS external_customer_mappings (id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id), source_system TEXT NOT NULL,
        external_customer_id TEXT NOT NULL, customer_id TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL,
        UNIQUE(tenant_id, source_system, external_customer_id))''',
    '''CREATE INDEX IF NOT EXISTS idx_ext_cust_mappings_tenant_cust
        ON external_customer_mappings(tenant_id, customer_id)''',
    '''CREATE TABLE IF NOT EXISTS membership_quota_overrides (
        membership_id TEXT PRIMARY KEY REFERENCES memberships(id),
        daily_limit INTEGER NOT NULL CHECK(daily_limit BETWEEN 1 AND 10000),
        effective_at DOUBLE PRECISION NOT NULL,
        expires_at DOUBLE PRECISION,
        reason TEXT NOT NULL,
        updated_by TEXT NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS admin_audit_log (
        id BIGSERIAL PRIMARY KEY,
        created_at DOUBLE PRECISION NOT NULL,
        correlation_id TEXT NOT NULL,
        actor_principal_id TEXT NOT NULL,
        actor_role TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        target_membership_id TEXT NOT NULL,
        action TEXT NOT NULL,
        outcome TEXT NOT NULL CHECK(outcome IN ('allowed', 'denied')),
        before_json TEXT NOT NULL,
        after_json TEXT NOT NULL,
        reason TEXT NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS idx_admin_audit_tenant ON admin_audit_log(tenant_id, id DESC)',
    'CREATE INDEX IF NOT EXISTS idx_admin_audit_target ON admin_audit_log(target_membership_id, id DESC)',
]

BUSINESS_V5_DDL = [
    '''CREATE TABLE IF NOT EXISTS cases (
        case_id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        customer_id TEXT NOT NULL REFERENCES customers(id),
        status TEXT NOT NULL CHECK(status IN ('waiting', 'in_progress', 'resolved')),
        holder TEXT,
        holder_name TEXT,
        version INTEGER NOT NULL DEFAULT 1,
        awaiting_customer_since DOUBLE PRECISION,
        reminder_deadline DOUBLE PRECISION,
        reminded_at DOUBLE PRECISION,
        inactivity_deadline DOUBLE PRECISION,
        feedback_prompted_at DOUBLE PRECISION,
        completion_deadline DOUBLE PRECISION,
        resolved_reason TEXT,
        resolved_at DOUBLE PRECISION,
        resumed_at DOUBLE PRECISION,
        resume_count INTEGER NOT NULL DEFAULT 0,
        previous_case_id TEXT REFERENCES cases(case_id),
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS idx_cases_conversation ON cases(conversation_id, created_at DESC)',
    'CREATE INDEX IF NOT EXISTS idx_cases_status_updated ON cases(status, updated_at DESC)',
    'CREATE INDEX IF NOT EXISTS idx_cases_customer ON cases(customer_id, created_at DESC)',
    '''CREATE UNIQUE INDEX IF NOT EXISTS idx_cases_one_open_per_conv
        ON cases(conversation_id) WHERE status <> 'resolved' ''',
    '''CREATE TABLE IF NOT EXISTS handoff_episodes (
        handoff_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        conversation_id TEXT NOT NULL,
        customer_id TEXT NOT NULL REFERENCES customers(id),
        status TEXT NOT NULL CHECK(status IN ('pending', 'resolved', 'customer_closed')),
        reason_code TEXT,
        comment TEXT,
        created_at DOUBLE PRECISION NOT NULL,
        closed_at DOUBLE PRECISION,
        closed_by TEXT)''',
    'CREATE INDEX IF NOT EXISTS idx_handoff_episodes_case ON handoff_episodes(case_id, created_at DESC)',
    'CREATE INDEX IF NOT EXISTS idx_handoff_episodes_conversation ON handoff_episodes(conversation_id)',
    '''CREATE UNIQUE INDEX IF NOT EXISTS idx_handoff_episodes_one_open
        ON handoff_episodes(case_id) WHERE status = 'pending' ''',
    '''CREATE TABLE IF NOT EXISTS case_feedback_events (
        feedback_event_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        conversation_id TEXT NOT NULL,
        turn_id BIGINT,
        customer_id TEXT NOT NULL REFERENCES customers(id),
        feedback_type TEXT NOT NULL CHECK(feedback_type IN ('turn_rating', 'session_csat')),
        raw_value TEXT NOT NULL,
        rating INTEGER CHECK(rating IS NULL OR (rating BETWEEN 1 AND 5)),
        sentiment_flag TEXT CHECK(sentiment_flag IS NULL OR sentiment_flag IN ('positive', 'negative', 'neutral')),
        preference_label TEXT NOT NULL CHECK(preference_label IN ('chosen', 'rejected')),
        reason_code TEXT,
        comment TEXT,
        created_at DOUBLE PRECISION NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS idx_case_feedback_case ON case_feedback_events(case_id, created_at DESC)',
    'CREATE INDEX IF NOT EXISTS idx_case_feedback_conv ON case_feedback_events(conversation_id)',
]

BUSINESS_V6_TABLES_DDL = [
    '''CREATE TABLE IF NOT EXISTS order_action_requests (
        request_id TEXT PRIMARY KEY,
        order_id TEXT NOT NULL REFERENCES orders(id),
        customer_id TEXT NOT NULL REFERENCES customers(id),
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        conversation_id TEXT NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('cancel', 'return', 'exchange')),
        exchange_kind TEXT CHECK(
            (type = 'exchange' AND exchange_kind IN ('size', 'one_to_one'))
            OR (type <> 'exchange' AND exchange_kind IS NULL)
        ),
        status TEXT NOT NULL CHECK(
            status IN ('requested', 'under_review', 'approved', 'rejected', 'received', 'inspected', 'completed')
        ),
        inspection_outcome TEXT CHECK(
            inspection_outcome IS NULL OR inspection_outcome IN ('refund', 'exchange', 'no_action')
        ),
        refund_status TEXT NOT NULL DEFAULT 'not_applicable' CHECK(
            refund_status IN ('not_applicable', 'pending', 'refunded', 'failed')
        ),
        refund_decision TEXT CHECK(
            refund_decision IS NULL OR refund_decision IN ('approved', 'rejected')
        ),
        reason_code TEXT NOT NULL CHECK(char_length(trim(reason_code)) > 0),
        reason_text TEXT CHECK(reason_text IS NULL OR char_length(reason_text) <= 500),
        raised_by_role TEXT NOT NULL CHECK(raised_by_role IN ('customer', 'staff', 'manager')),
        delivery_failure_attempts INTEGER CHECK(
            delivery_failure_attempts IS NULL OR delivery_failure_attempts >= 1
        ),
        expected_order_version INTEGER NOT NULL CHECK(expected_order_version >= 1),
        version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL,
        reviewed_at DOUBLE PRECISION,
        received_at DOUBLE PRECISION,
        inspected_at DOUBLE PRECISION,
        completed_at DOUBLE PRECISION,
        closed_at DOUBLE PRECISION,
        CHECK(
            (type = 'cancel' AND (
                (status IN ('requested', 'under_review') AND closed_at IS NULL)
                OR (status IN ('approved', 'rejected') AND closed_at IS NOT NULL)
            ))
            OR (type IN ('return', 'exchange') AND (
                (status IN ('requested', 'under_review', 'approved', 'received', 'inspected') AND closed_at IS NULL)
                OR (status IN ('rejected', 'completed') AND closed_at IS NOT NULL)
            ))
        ))''',
    'CREATE INDEX IF NOT EXISTS idx_order_action_case ON order_action_requests(case_id, created_at DESC)',
    'CREATE INDEX IF NOT EXISTS idx_order_action_customer ON order_action_requests(customer_id, created_at DESC)',
    'CREATE INDEX IF NOT EXISTS idx_order_action_order ON order_action_requests(order_id, created_at DESC)',
    '''CREATE UNIQUE INDEX IF NOT EXISTS idx_order_action_one_open_per_order
        ON order_action_requests(order_id) WHERE closed_at IS NULL''',
    '''CREATE TABLE IF NOT EXISTS order_action_decisions (
        decision_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL REFERENCES order_action_requests(request_id),
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        order_id TEXT NOT NULL REFERENCES orders(id),
        conversation_id TEXT NOT NULL,
        action TEXT NOT NULL,
        from_status TEXT,
        to_status TEXT NOT NULL,
        from_refund_status TEXT,
        to_refund_status TEXT,
        refund_decision TEXT,
        inspection_outcome TEXT,
        actor_principal_id TEXT NOT NULL,
        actor_role TEXT NOT NULL,
        note TEXT CHECK(note IS NULL OR char_length(note) <= 500),
        created_at DOUBLE PRECISION NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS idx_order_action_decisions_req ON order_action_decisions(request_id, created_at ASC)',
    'CREATE INDEX IF NOT EXISTS idx_order_action_decisions_case ON order_action_decisions(case_id, created_at ASC)',
    '''CREATE OR REPLACE FUNCTION order_action_decisions_immutable() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'order_action_decisions is append-only';
    END;
    $$ LANGUAGE plpgsql''',
    'DROP TRIGGER IF EXISTS trg_order_action_decisions_immutable ON order_action_decisions',
    '''CREATE TRIGGER trg_order_action_decisions_immutable
        BEFORE UPDATE OR DELETE ON order_action_decisions
        FOR EACH ROW EXECUTE FUNCTION order_action_decisions_immutable()''',
    '''CREATE TABLE IF NOT EXISTS order_action_evidence (
        evidence_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL REFERENCES order_action_requests(request_id),
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        customer_id TEXT NOT NULL REFERENCES customers(id),
        conversation_id TEXT NOT NULL,
        uploaded_by_principal_id TEXT NOT NULL,
        uploaded_by_role TEXT NOT NULL CHECK(uploaded_by_role IN ('customer', 'staff', 'manager')),
        mime_type TEXT NOT NULL CHECK(mime_type IN ('image/jpeg', 'image/png', 'image/webp')),
        byte_size INTEGER NOT NULL CHECK(byte_size > 0 AND byte_size <= 10485760),
        width INTEGER NOT NULL CHECK(width > 0),
        height INTEGER NOT NULL CHECK(height > 0),
        sha256 TEXT NOT NULL,
        storage_relpath TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL,
        file_purged_at DOUBLE PRECISION)''',
    'CREATE INDEX IF NOT EXISTS idx_order_action_evidence_req ON order_action_evidence(request_id, created_at ASC)',
    'CREATE INDEX IF NOT EXISTS idx_order_action_evidence_purge ON order_action_evidence(file_purged_at, request_id)',
    '''CREATE TABLE IF NOT EXISTS integration_outbox (
        event_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'published', 'dead')),
        attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
        next_attempt_at DOUBLE PRECISION NOT NULL,
        last_error TEXT,
        published_at DOUBLE PRECISION)''',
    'CREATE INDEX IF NOT EXISTS idx_integration_outbox_due ON integration_outbox(status, next_attempt_at, created_at)',
]

BUSINESS_V6_DDL = [
    'ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at DOUBLE PRECISION',
    *BUSINESS_V6_TABLES_DDL,
]

BUSINESS_DDL.extend(P5C_BUSINESS_DDL)
BUSINESS_DDL.extend(BUSINESS_V5_DDL)
BUSINESS_DDL.extend(BUSINESS_V6_TABLES_DDL)
IDENTITY_DDL.extend(P5C_IDENTITY_DDL)


CACHE_DDL = [
    '''CREATE TABLE IF NOT EXISTS semantic_cache (
        id TEXT PRIMARY KEY, query_text TEXT NOT NULL, query_hash TEXT NOT NULL,
        embedding retailops_extensions.vector(384) NOT NULL, response_json TEXT NOT NULL,
        hit_count INTEGER NOT NULL DEFAULT 0, created_at DOUBLE PRECISION NOT NULL,
        expires_at DOUBLE PRECISION NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS idx_semantic_cache_hash ON semantic_cache(query_hash)',
    '''CREATE INDEX IF NOT EXISTS idx_semantic_cache_embedding ON semantic_cache
        USING hnsw (embedding retailops_extensions.vector_cosine_ops)''',
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


def initialize_cache(db):
    vector_extension(db)
    for statement in CACHE_DDL:
        db.raw.execute(statement)


def initialize(
    db,
    schema,
    component,
    *,
    allow_identity_v5_upgrade=False,
    allow_business_v5_upgrade=False,
    allow_business_v6_upgrade=False,
):
    from psycopg import sql
    valid_schema(schema)
    if (schema == IDENTITY_SCHEMA) != (component == 'identity'):
        raise ValueError('Schema and component mismatch.')
    exists = db.raw.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s', (schema,)).fetchone()
    if exists:
        row = db.raw.execute(sql.SQL('SELECT component,version FROM {}.retailops_schema').format(sql.Identifier(schema))).fetchone()
        if not row or row['component'] != component:
            raise ValueError('Unsupported PostgreSQL schema version or component.')
        if component == 'identity':
            if row['version'] not in (1, 2, 3, 4, 5):
                raise ValueError('Unsupported PostgreSQL schema version or component.')
            if row['version'] < IDENTITY_SCHEMA_CURRENT and not allow_identity_v5_upgrade:
                raise ApiError(
                    503,
                    'identity_migration_required',
                    f"Kho dữ liệu identity PostgreSQL đang ở schema v{row['version']}; khởi động bị chặn fail-closed. "
                    "Hãy chạy lệnh operator identity migrate-v5 với --confirm-preflight --confirm-backup.",
                )
            db.raw.execute(sql.SQL('SET LOCAL search_path TO {}, pg_catalog').format(sql.Identifier(schema)))
            if row['version'] == 1:
                for statement in (
                    '''CREATE TABLE IF NOT EXISTS external_identities (
                        id TEXT PRIMARY KEY, issuer TEXT NOT NULL, sub TEXT NOT NULL,
                        principal_id TEXT NOT NULL REFERENCES principals(id), email TEXT,
                        created_at DOUBLE PRECISION NOT NULL, UNIQUE(issuer, sub))''',
                    '''CREATE TABLE IF NOT EXISTS customer_links (
                        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
                        principal_id TEXT NOT NULL REFERENCES principals(id), customer_id TEXT NOT NULL,
                        created_at DOUBLE PRECISION NOT NULL, UNIQUE(tenant_id, principal_id), UNIQUE(tenant_id, customer_id))''',
                    '''CREATE TABLE IF NOT EXISTS unresolved_collisions (
                        tenant_id TEXT NOT NULL REFERENCES tenants(id),
                        customer_id TEXT NOT NULL,
                        created_at DOUBLE PRECISION NOT NULL,
                        PRIMARY KEY(tenant_id, customer_id))''',
                    '''INSERT INTO unresolved_collisions (tenant_id, customer_id, created_at)
                       SELECT tenant_id, customer_id, extract(epoch from now())
                       FROM memberships
                       WHERE role = 'customer'
                       GROUP BY tenant_id, customer_id
                       HAVING count(*) > 1
                       ON CONFLICT DO NOTHING''',
                    '''DELETE FROM sessions WHERE membership_id IN (
                           SELECT id FROM memberships
                           WHERE role = 'customer'
                             AND (tenant_id, customer_id) IN (
                                 SELECT tenant_id, customer_id FROM memberships WHERE role = 'customer' GROUP BY tenant_id, customer_id HAVING count(*) > 1
                             )
                       )''',
                    '''INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at)
                       SELECT md5(random()::text || clock_timestamp()::text), m.tenant_id, m.principal_id, m.customer_id, extract(epoch from now())
                       FROM memberships m
                       WHERE m.role='customer'
                         AND (m.tenant_id, m.customer_id) NOT IN (
                             SELECT tenant_id, customer_id FROM memberships WHERE role='customer' GROUP BY tenant_id, customer_id HAVING count(*) > 1
                         )
                       ON CONFLICT DO NOTHING''',
                    '''CREATE TABLE IF NOT EXISTS reconciliation_journal (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL REFERENCES tenants(id),
                        colliding_customer_id TEXT NOT NULL,
                        status TEXT NOT NULL CHECK(status IN ('started', 'business_committed', 'identity_committed', 'completed')),
                        plan_json TEXT NOT NULL,
                        plan_hash TEXT,
                        error_message TEXT,
                        created_at DOUBLE PRECISION NOT NULL,
                        updated_at DOUBLE PRECISION NOT NULL)''',
                    'CREATE INDEX IF NOT EXISTS idx_reconciliation_journal_tenant ON reconciliation_journal(tenant_id, colliding_customer_id)',
                    'ALTER TABLE reconciliation_journal ADD COLUMN IF NOT EXISTS plan_hash TEXT',
                ):
                    db.raw.execute(statement)
                db.execute("UPDATE retailops_schema SET version=4 WHERE component='identity'")
                row = {'component': 'identity', 'version': 4}
            if row['version'] == 2:
                for statement in (
                    '''CREATE TABLE IF NOT EXISTS unresolved_collisions (
                        tenant_id TEXT NOT NULL REFERENCES tenants(id),
                        customer_id TEXT NOT NULL,
                        created_at DOUBLE PRECISION NOT NULL,
                        PRIMARY KEY(tenant_id, customer_id))''',
                    '''INSERT INTO unresolved_collisions (tenant_id, customer_id, created_at)
                       SELECT tenant_id, customer_id, extract(epoch from now())
                       FROM memberships
                       WHERE role = 'customer'
                       GROUP BY tenant_id, customer_id
                       HAVING count(*) > 1
                       ON CONFLICT DO NOTHING''',
                    '''DELETE FROM customer_links WHERE (tenant_id, customer_id) IN (
                           SELECT tenant_id, customer_id FROM unresolved_collisions
                       )''',
                    '''DELETE FROM sessions WHERE membership_id IN (
                           SELECT id FROM memberships
                           WHERE role = 'customer'
                             AND (
                                 (tenant_id, customer_id) IN (
                                     SELECT tenant_id, customer_id FROM memberships WHERE role = 'customer' GROUP BY tenant_id, customer_id HAVING count(*) > 1
                                 )
                                 OR (tenant_id, customer_id) IN (
                                     SELECT tenant_id, customer_id FROM unresolved_collisions
                                 )
                             )
                       )''',
                    '''CREATE TABLE IF NOT EXISTS reconciliation_journal (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL REFERENCES tenants(id),
                        colliding_customer_id TEXT NOT NULL,
                        status TEXT NOT NULL CHECK(status IN ('started', 'business_committed', 'identity_committed', 'completed')),
                        plan_json TEXT NOT NULL,
                        plan_hash TEXT,
                        error_message TEXT,
                        created_at DOUBLE PRECISION NOT NULL,
                        updated_at DOUBLE PRECISION NOT NULL)''',
                    'CREATE INDEX IF NOT EXISTS idx_reconciliation_journal_tenant ON reconciliation_journal(tenant_id, colliding_customer_id)',
                    'ALTER TABLE reconciliation_journal ADD COLUMN IF NOT EXISTS plan_hash TEXT',
                ):
                    db.raw.execute(statement)
                db.execute("UPDATE retailops_schema SET version=4 WHERE component='identity'")
                row = {'component': 'identity', 'version': 4}
            if row['version'] == 3:
                for statement in (
                    '''CREATE TABLE IF NOT EXISTS reconciliation_journal (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL REFERENCES tenants(id),
                        colliding_customer_id TEXT NOT NULL,
                        status TEXT NOT NULL CHECK(status IN ('started', 'business_committed', 'identity_committed', 'completed')),
                        plan_json TEXT NOT NULL,
                        plan_hash TEXT,
                        error_message TEXT,
                        created_at DOUBLE PRECISION NOT NULL,
                        updated_at DOUBLE PRECISION NOT NULL)''',
                    'CREATE INDEX IF NOT EXISTS idx_reconciliation_journal_tenant ON reconciliation_journal(tenant_id, colliding_customer_id)',
                    'ALTER TABLE reconciliation_journal ADD COLUMN IF NOT EXISTS plan_hash TEXT',
                ):
                    db.raw.execute(statement)
                db.execute("UPDATE retailops_schema SET version=4 WHERE component='identity'")
                row = {'component': 'identity', 'version': 4}
            if row['version'] == 4:
                for statement in (
                    'ALTER TABLE memberships ADD COLUMN IF NOT EXISTS disabled_reason TEXT',
                    '''DELETE FROM sessions WHERE membership_id IN (
                           SELECT id FROM memberships WHERE role IN ('viewer', 'platform_admin')
                       )''',
                    '''INSERT INTO identity_events (created_at, kind, tenant_id, membership_id)
                       SELECT extract(epoch from now()), 'legacy_role_disabled', tenant_id, id
                       FROM memberships
                       WHERE role IN ('viewer', 'platform_admin')
                         AND (active <> 0 OR disabled_reason IS NULL)''',
                    '''UPDATE memberships
                       SET active = 0,
                           disabled_reason = COALESCE(disabled_reason, 'retired_legacy_role_r1_w1'),
                           auth_version = auth_version + 1
                       WHERE role IN ('viewer', 'platform_admin')
                         AND (active <> 0 OR disabled_reason IS NULL)''',
                    'ALTER TABLE memberships DROP CONSTRAINT IF EXISTS memberships_role_check',
                    '''ALTER TABLE memberships ADD CONSTRAINT memberships_role_check
                       CHECK (role IN ('customer', 'staff', 'manager') OR (role IN ('viewer', 'platform_admin') AND active = 0))''',
                ):
                    db.raw.execute(statement)
                db.execute("UPDATE retailops_schema SET version=? WHERE component='identity'", (IDENTITY_SCHEMA_CURRENT,))
                row = {'component': 'identity', 'version': IDENTITY_SCHEMA_CURRENT}
            if row['version'] != IDENTITY_SCHEMA_CURRENT:
                raise ValueError('Unsupported PostgreSQL schema version or component.')
            for statement in P5C_IDENTITY_DDL:
                db.raw.execute(statement)
        if component == 'business':
            if row['version'] not in (1, 2, 3, 4, 5, 6):
                raise ValueError('Unsupported PostgreSQL schema version or component.')
            target_ver = (
                BUSINESS_SCHEMA_CURRENT
                if allow_business_v6_upgrade
                else (BUSINESS_V5_SCHEMA_VERSION if allow_business_v5_upgrade and row['version'] <= BUSINESS_V5_SCHEMA_VERSION else BUSINESS_SCHEMA_CURRENT)
            )
            if row['version'] < BUSINESS_V5_SCHEMA_VERSION and not (allow_business_v5_upgrade or allow_business_v6_upgrade):
                raise ApiError(
                    503,
                    'business_migration_required',
                    f"Kho dữ liệu business PostgreSQL ({schema}) đang ở schema v{row['version']}; khởi động bị chặn fail-closed. "
                    "Hãy chạy lệnh operator database migrate-v6 với --confirm-preflight --confirm-backup.",
                )
            if row['version'] < target_ver and target_ver == BUSINESS_SCHEMA_CURRENT and not allow_business_v6_upgrade:
                raise ApiError(
                    503,
                    'business_migration_required',
                    f"Kho dữ liệu business PostgreSQL ({schema}) đang ở schema v{row['version']}; khởi động bị chặn fail-closed. "
                    "Hãy chạy lệnh operator database migrate-v6 với --confirm-preflight --confirm-backup.",
                )
            db.raw.execute(sql.SQL('SET LOCAL search_path TO {}, pg_catalog').format(sql.Identifier(schema)))
            if row['version'] == 1:
                from retailops.workflow.schema import initialize as graph_schema
                graph_schema(db)
                db.execute("UPDATE retailops_schema SET version=2 WHERE component='business'")
                row = {'component': 'business', 'version': 2}
            if row['version'] == 2:
                initialize_knowledge(db)
                db.execute("UPDATE retailops_schema SET version=3 WHERE component='business'")
                row = {'component': 'business', 'version': 3}
            if row['version'] == 3:
                for statement in (
                    '''CREATE TABLE IF NOT EXISTS products (id TEXT PRIMARY KEY, name TEXT NOT NULL,
                        aliases TEXT NOT NULL DEFAULT '[]', category TEXT, price BIGINT,
                        stock INTEGER, warranty_days INTEGER, description TEXT,
                        variants TEXT NOT NULL DEFAULT '[]', material TEXT, care TEXT,
                        is_system_immutable INTEGER NOT NULL DEFAULT 0 CHECK(is_system_immutable IN (0,1)),
                        extra_data TEXT NOT NULL DEFAULT '{}',
                        created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL)''',
                    '''CREATE TABLE IF NOT EXISTS product_variants (id TEXT PRIMARY KEY,
                        product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                        variant_name TEXT NOT NULL, size TEXT, color TEXT, stock INTEGER,
                        sku TEXT, price BIGINT)''',
                    'CREATE INDEX IF NOT EXISTS idx_variants_product ON product_variants(product_id)',
                    'CREATE INDEX IF NOT EXISTS idx_variants_size_color ON product_variants(product_id, size, color)',
                    'ALTER TABLE orders ADD COLUMN IF NOT EXISTS product_id TEXT REFERENCES products(id)',
                    'CREATE INDEX IF NOT EXISTS idx_orders_product_id ON orders(product_id)',
                ):
                    db.raw.execute(statement)
                db.execute("UPDATE retailops_schema SET version=4 WHERE component='business'")
                row = {'component': 'business', 'version': 4}
            for statement in (
                '''CREATE TABLE IF NOT EXISTS conversation_feedback (
                    id BIGSERIAL PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    turn_id BIGINT REFERENCES agent_turns(id) ON DELETE SET NULL,
                    customer_id TEXT NOT NULL REFERENCES customers(id),
                    feedback_type TEXT NOT NULL CHECK(feedback_type IN ('turn_rating', 'session_csat', 'human_handoff')),
                    rating INTEGER CHECK(rating BETWEEN 1 AND 5),
                    sentiment_flag TEXT CHECK(sentiment_flag IN ('positive', 'negative', 'neutral')),
                    reason_code TEXT,
                    comment TEXT,
                    created_at DOUBLE PRECISION NOT NULL)''',
                'CREATE INDEX IF NOT EXISTS idx_feedback_conv ON conversation_feedback(conversation_id)',
                'CREATE INDEX IF NOT EXISTS idx_feedback_type ON conversation_feedback(feedback_type)',
            ):
                db.raw.execute(statement)
            if row['version'] == 4 and target_ver >= BUSINESS_V5_SCHEMA_VERSION:
                from retailops.business.schema import backfill_business_v5_cases
                for statement in BUSINESS_V5_DDL:
                    db.raw.execute(statement)
                backfill_business_v5_cases(db)
                db.execute("UPDATE retailops_schema SET version=? WHERE component='business'", (BUSINESS_V5_SCHEMA_VERSION,))
                row = {'component': 'business', 'version': BUSINESS_V5_SCHEMA_VERSION}
            if row['version'] == BUSINESS_V5_SCHEMA_VERSION and target_ver >= BUSINESS_SCHEMA_CURRENT:
                for statement in BUSINESS_V6_DDL:
                    db.raw.execute(statement)
                db.execute("UPDATE retailops_schema SET version=? WHERE component='business'", (BUSINESS_SCHEMA_CURRENT,))
                row = {'component': 'business', 'version': BUSINESS_SCHEMA_CURRENT}
            if row['version'] != target_ver:
                raise ValueError('Unsupported PostgreSQL schema version or component.')
            for statement in P5C_BUSINESS_DDL:
                db.raw.execute(statement)
            for statement in BUSINESS_V5_DDL:
                db.raw.execute(statement)
            if target_ver >= BUSINESS_SCHEMA_CURRENT:
                for statement in BUSINESS_V6_DDL:
                    db.raw.execute(statement)
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
               (component, BUSINESS_SCHEMA_CURRENT if component == 'business' else IDENTITY_SCHEMA_CURRENT))
    return True
