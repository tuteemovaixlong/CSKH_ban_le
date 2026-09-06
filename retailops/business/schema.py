"""Business schema v1, including safe upgrade of pre-versioned databases."""

def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS orders (
                  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, name TEXT NOT NULL,
                  variant TEXT NOT NULL, amount INTEGER NOT NULL,
                  status TEXT NOT NULL CHECK(status IN ('pending','delivered','cancelled')),
                  version INTEGER NOT NULL DEFAULT 1, cancel_reason TEXT
                )""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id)')
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
