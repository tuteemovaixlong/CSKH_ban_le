import time
import uuid

# Phase R1 W2/W3 backend schema version mappings:
#   - Business v5 (W2-D3): SQLite 4, PostgreSQL 5 (cases, handoff_episodes, case_feedback_events)
#   - Business v6 (W3-D1..W3-D4, W3-D6): SQLite 5, PostgreSQL 6
#     (orders.delivered_at, order_action_requests, order_action_decisions,
#      order_action_evidence, integration_outbox).
SQLITE_BUSINESS_V5_SCHEMA_VERSION = 4
POSTGRES_BUSINESS_V5_SCHEMA_VERSION = 5
BUSINESS_V5_VERSION_MAPPING = {
    'logical_milestone': 'business_v5',
    'sqlite': SQLITE_BUSINESS_V5_SCHEMA_VERSION,
    'postgresql': POSTGRES_BUSINESS_V5_SCHEMA_VERSION,
}
SQLITE_BUSINESS_SCHEMA_CURRENT = 5
POSTGRES_BUSINESS_SCHEMA_CURRENT = 6
BUSINESS_V6_VERSION_MAPPING = {
    'logical_milestone': 'business_v6',
    'sqlite': SQLITE_BUSINESS_SCHEMA_CURRENT,
    'postgresql': POSTGRES_BUSINESS_SCHEMA_CURRENT,
}


def migrate_v3(db):
    db.execute("""CREATE TABLE IF NOT EXISTS products (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  aliases TEXT NOT NULL DEFAULT '[]',
                  category TEXT,
                  price BIGINT,
                  stock INTEGER,
                  warranty_days INTEGER,
                  description TEXT,
                  variants TEXT NOT NULL DEFAULT '[]',
                  material TEXT,
                  care TEXT,
                  is_system_immutable INTEGER NOT NULL DEFAULT 0 CHECK(is_system_immutable IN (0,1)),
                  extra_data TEXT NOT NULL DEFAULT '{}',
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL
                )""")
    db.execute("""CREATE TABLE IF NOT EXISTS product_variants (
                  id TEXT PRIMARY KEY,
                  product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                  variant_name TEXT NOT NULL,
                  size TEXT,
                  color TEXT,
                  stock INTEGER,
                  sku TEXT,
                  price BIGINT
                )""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_variants_product ON product_variants(product_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_variants_size_color ON product_variants(product_id, size, color)')
    orders_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='orders'").fetchone()
    if orders_table:
        order_cols = {row['name'] for row in db.execute('PRAGMA table_info(orders)')}
        if 'product_id' not in order_cols:
            db.execute('ALTER TABLE orders ADD COLUMN product_id TEXT REFERENCES products(id)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_orders_product_id ON orders(product_id)')


def ensure_import_tables(db):
    db.execute("""CREATE TABLE IF NOT EXISTS order_items (
                  id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                  product_id TEXT NOT NULL REFERENCES products(id),
                  variant_id TEXT,
                  product_title TEXT NOT NULL,
                  variant_name TEXT,
                  quantity INTEGER NOT NULL CHECK (quantity > 0),
                  unit_price INTEGER NOT NULL CHECK (unit_price >= 0),
                  subtotal INTEGER NOT NULL CHECK (subtotal >= 0),
                  created_at REAL NOT NULL
                )""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id)')
    db.execute("""CREATE TABLE IF NOT EXISTS imported_events (
                  id TEXT PRIMARY KEY,
                  source_system TEXT NOT NULL,
                  event_id TEXT NOT NULL,
                  tenant_id TEXT NOT NULL,
                  external_customer_id TEXT NOT NULL,
                  customer_id TEXT NOT NULL,
                  order_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  total INTEGER NOT NULL,
                  currency TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  signature TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  UNIQUE(source_system, event_id)
                )""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_imported_events_tenant_order ON imported_events(tenant_id, order_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_imported_events_external '
               'ON imported_events(tenant_id, source_system, external_customer_id)')
    db.execute("""CREATE TABLE IF NOT EXISTS order_purge_tombstones (
                  order_id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  customer_id TEXT NOT NULL,
                  product_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  amount INTEGER NOT NULL,
                  snapshot_name TEXT NOT NULL,
                  variant TEXT,
                  reason TEXT NOT NULL,
                  operator_id TEXT NOT NULL,
                  purged_at DOUBLE PRECISION NOT NULL,
                  pre_counts_json TEXT NOT NULL,
                  post_counts_json TEXT NOT NULL
                )""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_order_purge_tombstones_customer ON order_purge_tombstones(customer_id, product_id)')


def initialize(db):
    migrate_v3(db)
    db.execute("""CREATE TABLE IF NOT EXISTS orders (
                  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, name TEXT NOT NULL,
                  variant TEXT NOT NULL, amount INTEGER NOT NULL,
                  status TEXT NOT NULL CHECK(status IN ('pending','delivered','cancelled')),
                  version INTEGER NOT NULL DEFAULT 1, cancel_reason TEXT,
                  product_id TEXT REFERENCES products(id),
                  delivered_at REAL
                )""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_orders_product_id ON orders(product_id)')
    ensure_import_tables(db)
    db.execute("""CREATE TABLE IF NOT EXISTS proposals (
                  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, order_id TEXT NOT NULL REFERENCES orders(id),
                  order_version INTEGER NOT NULL, reason TEXT NOT NULL,
                  expires_at REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                  confirm_key TEXT, result TEXT,
                  UNIQUE(customer_id, confirm_key)
                )""")
    db.execute("""CREATE TABLE IF NOT EXISTS business_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT NOT NULL,
                  created_at REAL NOT NULL, kind TEXT NOT NULL, order_id TEXT, payload TEXT NOT NULL
                )""")
    db.execute("""CREATE INDEX IF NOT EXISTS idx_business_events_customer_id_id
                  ON business_events(customer_id, id)""")
    db.execute("""CREATE TABLE IF NOT EXISTS conversations (
                  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
                  order_id TEXT, product_id TEXT,
                  revision INTEGER NOT NULL DEFAULT 0, expires_at REAL NOT NULL
                )""")
    db.execute("""CREATE TABLE IF NOT EXISTS agent_turns (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                  customer_id TEXT NOT NULL, request_id TEXT NOT NULL, input_hash TEXT NOT NULL,
                  messages TEXT NOT NULL, result TEXT NOT NULL, created_at REAL NOT NULL,
                  UNIQUE(conversation_id, request_id)
                )""")
    db.execute("""CREATE TABLE IF NOT EXISTS conversation_feedback (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                  turn_id INTEGER REFERENCES agent_turns(id) ON DELETE SET NULL,
                  customer_id TEXT NOT NULL,
                  feedback_type TEXT NOT NULL CHECK(feedback_type IN ('turn_rating', 'session_csat', 'human_handoff')),
                  rating INTEGER CHECK(rating BETWEEN 1 AND 5),
                  sentiment_flag TEXT CHECK(sentiment_flag IN ('positive', 'negative', 'neutral')),
                  reason_code TEXT,
                  comment TEXT,
                  created_at REAL NOT NULL
                )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_feedback_conv ON conversation_feedback(conversation_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_feedback_type ON conversation_feedback(feedback_type)")
    db.execute("""CREATE TABLE IF NOT EXISTS provider_daily_usage (
                  day TEXT NOT NULL, provider_id TEXT NOT NULL, attempts INTEGER NOT NULL,
                  PRIMARY KEY(day,provider_id)
                )""")
    if 'provider_id' not in {row['name'] for row in db.execute('PRAGMA table_info(conversations)')}:
        db.execute("ALTER TABLE conversations ADD COLUMN provider_id TEXT NOT NULL DEFAULT 'custom'")
    db.execute('CREATE TABLE IF NOT EXISTS customers (id TEXT PRIMARY KEY, name TEXT NOT NULL)')
    db.execute("INSERT OR IGNORE INTO customers SELECT DISTINCT customer_id, 'Khách hàng' FROM orders")
    db.execute("""CREATE TRIGGER IF NOT EXISTS order_customer_insert BEFORE INSERT ON orders
        WHEN NOT EXISTS (SELECT 1 FROM customers WHERE id=NEW.customer_id)
        BEGIN SELECT RAISE(ABORT,'Unknown customer'); END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS order_customer_update BEFORE UPDATE OF customer_id ON orders
        WHEN NOT EXISTS (SELECT 1 FROM customers WHERE id=NEW.customer_id)
        BEGIN SELECT RAISE(ABORT,'Unknown customer'); END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS customer_delete BEFORE DELETE ON customers
        WHEN EXISTS (SELECT 1 FROM orders WHERE customer_id=OLD.id)
        BEGIN SELECT RAISE(ABORT,'Customer owns orders'); END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS customer_id_update BEFORE UPDATE OF id ON customers
        WHEN NEW.id<>OLD.id AND EXISTS (SELECT 1 FROM orders WHERE customer_id=OLD.id)
        BEGIN SELECT RAISE(ABORT,'Customer owns orders'); END""")
    ensure_case_tables(db)
    ensure_order_action_tables(db)


def ensure_case_tables(db):
    """Create Business v5 case lifecycle tables on SQLite without FK cascade from conversations."""
    db.execute("""CREATE TABLE IF NOT EXISTS cases (
                  case_id TEXT PRIMARY KEY,
                  conversation_id TEXT NOT NULL,
                  customer_id TEXT NOT NULL,
                  status TEXT NOT NULL CHECK(status IN ('waiting', 'in_progress', 'resolved')),
                  holder TEXT,
                  holder_name TEXT,
                  version INTEGER NOT NULL DEFAULT 1,
                  awaiting_customer_since REAL,
                  reminder_deadline REAL,
                  reminded_at REAL,
                  inactivity_deadline REAL,
                  feedback_prompted_at REAL,
                  completion_deadline REAL,
                  resolved_reason TEXT,
                  resolved_at REAL,
                  resumed_at REAL,
                  resume_count INTEGER NOT NULL DEFAULT 0,
                  previous_case_id TEXT REFERENCES cases(case_id),
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL
                )""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_cases_conversation ON cases(conversation_id, created_at DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_cases_status_updated ON cases(status, updated_at DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_cases_customer ON cases(customer_id, created_at DESC)')
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_cases_one_open_per_conv "
        "ON cases(conversation_id) WHERE status <> 'resolved'"
    )
    db.execute("""CREATE TABLE IF NOT EXISTS handoff_episodes (
                  handoff_id TEXT PRIMARY KEY,
                  case_id TEXT NOT NULL REFERENCES cases(case_id),
                  conversation_id TEXT NOT NULL,
                  customer_id TEXT NOT NULL,
                  status TEXT NOT NULL CHECK(status IN ('pending', 'resolved', 'customer_closed')),
                  reason_code TEXT,
                  comment TEXT,
                  created_at REAL NOT NULL,
                  closed_at REAL,
                  closed_by TEXT
                )""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_handoff_episodes_case ON handoff_episodes(case_id, created_at DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_handoff_episodes_conversation ON handoff_episodes(conversation_id)')
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_handoff_episodes_one_open "
        "ON handoff_episodes(case_id) WHERE status = 'pending'"
    )
    db.execute("""CREATE TABLE IF NOT EXISTS case_feedback_events (
                  feedback_event_id TEXT PRIMARY KEY,
                  case_id TEXT NOT NULL REFERENCES cases(case_id),
                  conversation_id TEXT NOT NULL,
                  turn_id INTEGER,
                  customer_id TEXT NOT NULL,
                  feedback_type TEXT NOT NULL CHECK(feedback_type IN ('turn_rating', 'session_csat')),
                  raw_value TEXT NOT NULL,
                  rating INTEGER CHECK(rating IS NULL OR (rating BETWEEN 1 AND 5)),
                  sentiment_flag TEXT CHECK(sentiment_flag IS NULL OR sentiment_flag IN ('positive', 'negative', 'neutral')),
                  preference_label TEXT NOT NULL CHECK(preference_label IN ('chosen', 'rejected')),
                  reason_code TEXT,
                  comment TEXT,
                  created_at REAL NOT NULL
                )""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_case_feedback_case ON case_feedback_events(case_id, created_at DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_case_feedback_conv ON case_feedback_events(conversation_id)')


def ensure_order_action_tables(db):
    """Create Business v6 order-action, append-only decision, evidence, and outbox tables on SQLite.

    Also adds nullable orders.delivered_at (leaving existing orders NULL per W3-D6).
    Never uses ON DELETE CASCADE from conversations so expired conversation cleanup preserves
    every request, decision, evidence record, and outbox event.
    """
    orders_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='orders'").fetchone()
    if orders_table:
        order_cols = {row['name'] for row in db.execute('PRAGMA table_info(orders)')}
        if 'delivered_at' not in order_cols:
            db.execute('ALTER TABLE orders ADD COLUMN delivered_at REAL')

    db.execute("""CREATE TABLE IF NOT EXISTS order_action_requests (
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
                  reason_code TEXT NOT NULL CHECK(length(trim(reason_code)) > 0),
                  reason_text TEXT CHECK(reason_text IS NULL OR length(reason_text) <= 500),
                  raised_by_role TEXT NOT NULL CHECK(raised_by_role IN ('customer', 'staff', 'manager')),
                  delivery_failure_attempts INTEGER CHECK(
                      delivery_failure_attempts IS NULL OR delivery_failure_attempts >= 1
                  ),
                  expected_order_version INTEGER NOT NULL CHECK(expected_order_version >= 1),
                  version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL,
                  reviewed_at REAL,
                  received_at REAL,
                  inspected_at REAL,
                  completed_at REAL,
                  closed_at REAL,
                  CHECK(
                      (type = 'cancel' AND (
                          (status IN ('requested', 'under_review') AND closed_at IS NULL)
                          OR (status IN ('approved', 'rejected') AND closed_at IS NOT NULL)
                      ))
                      OR (type IN ('return', 'exchange') AND (
                          (status IN ('requested', 'under_review', 'approved', 'received', 'inspected') AND closed_at IS NULL)
                          OR (status IN ('rejected', 'completed') AND closed_at IS NOT NULL)
                      ))
                  )
                )""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_order_action_case ON order_action_requests(case_id, created_at DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_order_action_customer ON order_action_requests(customer_id, created_at DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_order_action_order ON order_action_requests(order_id, created_at DESC)')
    db.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_order_action_one_open_per_order '
        'ON order_action_requests(order_id) WHERE closed_at IS NULL'
    )

    db.execute("""CREATE TABLE IF NOT EXISTS order_action_decisions (
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
                  note TEXT CHECK(note IS NULL OR length(note) <= 500),
                  created_at REAL NOT NULL
                )""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_order_action_decisions_req ON order_action_decisions(request_id, created_at ASC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_order_action_decisions_case ON order_action_decisions(case_id, created_at ASC)')
    db.execute("""CREATE TRIGGER IF NOT EXISTS order_action_decisions_no_update
                  BEFORE UPDATE ON order_action_decisions
                  BEGIN SELECT RAISE(ABORT, 'order_action_decisions is append-only'); END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS order_action_decisions_no_delete
                  BEFORE DELETE ON order_action_decisions
                  BEGIN SELECT RAISE(ABORT, 'order_action_decisions is append-only'); END""")

    db.execute("""CREATE TABLE IF NOT EXISTS order_action_evidence (
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
                  created_at REAL NOT NULL,
                  file_purged_at REAL
                )""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_order_action_evidence_req ON order_action_evidence(request_id, created_at ASC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_order_action_evidence_purge ON order_action_evidence(file_purged_at, request_id)')

    db.execute("""CREATE TABLE IF NOT EXISTS integration_outbox (
                  event_id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'published', 'dead')),
                  attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                  next_attempt_at REAL NOT NULL,
                  last_error TEXT,
                  published_at REAL
                )""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_integration_outbox_due ON integration_outbox(status, next_attempt_at, created_at)')


def backfill_business_v5_cases(db, *, now=None):
    """Idempotently backfill Business v5 cases and open handoff_episodes from existing conversations.

    Never deletes or mutates legacy rows in conversation_feedback.
    Works identically on SQLite connections and PostgreSQL Queries wrappers.
    """
    now_ts = float(time.time() if now is None else now)
    db.execute(
        "INSERT INTO customers(id, name) "
        "SELECT DISTINCT customer_id, 'Khách hàng' FROM conversations "
        "WHERE customer_id IS NOT NULL "
        "ON CONFLICT(id) DO NOTHING"
    )
    unmapped = db.execute(
        """SELECT c.id AS conversation_id, c.customer_id
           FROM conversations c
           WHERE NOT EXISTS (SELECT 1 FROM cases k WHERE k.conversation_id = c.id)
           ORDER BY c.id"""
    ).fetchall()
    cases_created = 0
    episodes_created = 0
    for conv in unmapped:
        cid = conv['conversation_id']
        cust_id = conv['customer_id']
        turn_row = db.execute(
            'SELECT MIN(created_at) AS first_ts FROM agent_turns WHERE conversation_id = ?',
            (cid,),
        ).fetchone()
        first_ts = turn_row['first_ts'] if turn_row and turn_row['first_ts'] is not None else None
        open_handoff = db.execute(
            """SELECT id, reason_code, comment, created_at
               FROM conversation_feedback
               WHERE conversation_id = ?
                 AND feedback_type = 'human_handoff'
                 AND COALESCE(reason_code, '') <> 'resolved'
               ORDER BY created_at DESC, id DESC
               LIMIT 1""",
            (cid,),
        ).fetchone()
        case_id = f'case_{uuid.uuid4().hex}'
        created_ts = float(
            first_ts
            if first_ts is not None
            else (open_handoff['created_at'] if open_handoff and open_handoff['created_at'] is not None else now_ts)
        )
        if open_handoff is not None:
            db.execute(
                """INSERT INTO cases(
                       case_id, conversation_id, customer_id, status, holder, holder_name,
                       version, resolved_reason, resolved_at, resume_count, created_at, updated_at
                   ) VALUES (?, ?, ?, 'waiting', NULL, NULL, 1, NULL, NULL, 0, ?, ?)""",
                (case_id, cid, cust_id, created_ts, now_ts),
            )
            handoff_id = f'hoff_{uuid.uuid4().hex}'
            ep_ts = float(open_handoff['created_at'] if open_handoff['created_at'] is not None else now_ts)
            db.execute(
                """INSERT INTO handoff_episodes(
                       handoff_id, case_id, conversation_id, customer_id,
                       status, reason_code, comment, created_at
                   ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
                (handoff_id, case_id, cid, cust_id, open_handoff['reason_code'], open_handoff['comment'], ep_ts),
            )
            cases_created += 1
            episodes_created += 1
        else:
            db.execute(
                """INSERT INTO cases(
                       case_id, conversation_id, customer_id, status, holder, holder_name,
                       version, resolved_reason, resolved_at, resume_count, created_at, updated_at
                   ) VALUES (?, ?, ?, 'resolved', NULL, NULL, 1, 'migrated_v5', ?, 0, ?, ?)""",
                (case_id, cid, cust_id, now_ts, created_ts, now_ts),
            )
            cases_created += 1
    return {'cases_created': cases_created, 'episodes_created': episodes_created}
