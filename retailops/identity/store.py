"""Durable principals, memberships and revocable sessions; credentials stored as hashes."""
import hashlib
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path

from retailops.business.permissions import ROLE_PERMISSIONS
from retailops.core import require
from retailops.schema import migrate


def initialize(db):
    statements = [
        '''CREATE TABLE tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL,
            storage_key TEXT UNIQUE NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)))''',
        'CREATE TABLE principals (id TEXT PRIMARY KEY, name TEXT NOT NULL)',
        '''CREATE TABLE memberships (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
            principal_id TEXT NOT NULL REFERENCES principals(id), customer_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('customer','viewer','staff','manager')), active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            auth_version INTEGER NOT NULL DEFAULT 1, UNIQUE(tenant_id,principal_id))''',
        '''CREATE TABLE credentials (hash TEXT PRIMARY KEY, membership_id TEXT NOT NULL REFERENCES memberships(id),
            created_at REAL NOT NULL)''',
        '''CREATE TABLE sessions (id TEXT PRIMARY KEY, membership_id TEXT NOT NULL REFERENCES memberships(id),
            auth_version INTEGER NOT NULL, expires_at REAL NOT NULL)''',
        'CREATE INDEX idx_sessions_membership ON sessions(membership_id)',
        'CREATE INDEX idx_sessions_expiry ON sessions(expires_at)',
        'CREATE TABLE identity_rate (bucket TEXT PRIMARY KEY, window INTEGER NOT NULL, count INTEGER NOT NULL)',
        '''CREATE TABLE provider_daily_usage (day TEXT NOT NULL, provider_id TEXT NOT NULL,
            attempts INTEGER NOT NULL, PRIMARY KEY(day,provider_id))''',
        '''CREATE TABLE identity_events (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL,
            kind TEXT NOT NULL, tenant_id TEXT, membership_id TEXT)''',
        '''CREATE TABLE IF NOT EXISTS external_identities (id TEXT PRIMARY KEY, issuer TEXT NOT NULL,
            sub TEXT NOT NULL, principal_id TEXT NOT NULL REFERENCES principals(id), email TEXT,
            created_at REAL NOT NULL, UNIQUE(issuer, sub))''',
        '''CREATE TABLE IF NOT EXISTS customer_links (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
            principal_id TEXT NOT NULL REFERENCES principals(id), customer_id TEXT NOT NULL,
            created_at REAL NOT NULL, UNIQUE(tenant_id, principal_id), UNIQUE(tenant_id, customer_id))''',
        '''CREATE TABLE IF NOT EXISTS unresolved_collisions (tenant_id TEXT NOT NULL REFERENCES tenants(id),
            customer_id TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(tenant_id, customer_id))''',
    ]
    for statement in statements:
        db.execute(statement)


def migrate_legacy_collisions(db, tenant_stores=None):
    """Saga / idempotent multi-database recovery process across independent business and identity database boundaries.
    Atomically resolves any legacy collisions where multiple customer memberships
    in the same tenant share a customer_id, and guarantees unique customer_links.

    If ambiguous collisions exist with business data (orders/conversations):
    - Ambiguous orders/conversations are quarantined under a designated quarantine customer.
    - An identity event 'collision_quarantined_reconciliation_required' is recorded.
    - Each colliding membership receives a fresh, distinct customer_id (cust_<hash>).
    - Business customers table is updated with corresponding customer records.
    - Affected active sessions are invalidated to prevent stale identity hijacking.
    """
    db.execute('''CREATE TABLE IF NOT EXISTS external_identities (
        id TEXT PRIMARY KEY,
        issuer TEXT NOT NULL,
        sub TEXT NOT NULL,
        principal_id TEXT NOT NULL REFERENCES principals(id),
        email TEXT,
        created_at REAL NOT NULL,
        UNIQUE(issuer, sub)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS customer_links (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id),
        principal_id TEXT NOT NULL REFERENCES principals(id),
        customer_id TEXT NOT NULL,
        created_at REAL NOT NULL,
        UNIQUE(tenant_id, principal_id),
        UNIQUE(tenant_id, customer_id)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS unresolved_collisions (
        tenant_id TEXT NOT NULL REFERENCES tenants(id),
        customer_id TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY(tenant_id, customer_id)
    )''')

    # Helper to resolve tenant business database connection
    def get_tenant_db_conn(t_id):
        if tenant_stores:
            try:
                if callable(tenant_stores):
                    store = tenant_stores(t_id)
                elif isinstance(tenant_stores, dict):
                    store = tenant_stores.get(t_id)
                else:
                    store = getattr(tenant_stores, 'business_store', lambda _: None)(t_id)
                if store:
                    return store.connection(write=True)
            except Exception:
                pass
        try:
            main_rows = [r[2] for r in db.execute("PRAGMA database_list").fetchall() if r[1] == 'main']
            if main_rows and main_rows[0]:
                p = Path(main_rows[0])
                t_row = db.execute("SELECT storage_key FROM tenants WHERE id=?", (t_id,)).fetchone()
                if t_row:
                    t_file = p.parent / 'tenants' / f"{t_row['storage_key']}.sqlite3"
                    if t_file.is_file():
                        from retailops.business.store import BusinessStore
                        return BusinessStore(t_file, create=False).connection(write=True)
        except Exception:
            pass
        return None

    collision_groups = db.execute('''
        SELECT tenant_id, customer_id, COUNT(*) as cnt
        FROM memberships
        WHERE role = 'customer'
        GROUP BY tenant_id, customer_id
        HAVING cnt > 1
    ''').fetchall()

    unresolved_collision_members = set()

    for grp in collision_groups:
        t_id, c_id = grp['tenant_id'], grp['customer_id']
        members = db.execute('''
            SELECT m.id, m.principal_id, p.name
            FROM memberships m
            JOIN principals p ON p.id=m.principal_id
            WHERE m.tenant_id=? AND m.customer_id=? AND m.role='customer'
            ORDER BY m.id
        ''', (t_id, c_id)).fetchall()

        b_conn_ctx = get_tenant_db_conn(t_id)
        if not b_conn_ctx:
            # N08-A2 FAIL-CLOSED: Business DB unavailable / resolver error / mount missing.
            # Do NOT mutate memberships, do NOT assign random CIDs, do NOT log legacy_collision_migrated!
            # Invalidate all active sessions for colliding members to prevent leaked access.
            for m in members:
                unresolved_collision_members.add(m['id'])
                db.execute('DELETE FROM sessions WHERE membership_id=?', (m['id'],))
            db.execute(
                'INSERT INTO unresolved_collisions (tenant_id, customer_id, created_at) VALUES (?,?,?) '
                'ON CONFLICT(tenant_id, customer_id) DO NOTHING',
                (t_id, c_id, time.time())
            )
            db.execute('DELETE FROM customer_links WHERE tenant_id=? AND customer_id=?', (t_id, c_id))
            db.execute(
                'INSERT INTO identity_events(created_at, kind, tenant_id, membership_id) VALUES (?,?,?,?)',
                (time.time(), 'legacy_collision_unresolved_storage_unavailable', t_id, None)
            )
            continue

        with b_conn_ctx as bdb:
            quarantine_cid = f"quarantine_{c_id}"
            # Check original c_id AND quarantine_cid for orders/conversations (idempotent recovery N08-A1)
            orig_orders = bdb.execute("SELECT count(*) AS total FROM orders WHERE customer_id=?", (c_id,)).fetchone()['total']
            quarantined_orders = bdb.execute("SELECT count(*) AS total FROM orders WHERE customer_id=?", (quarantine_cid,)).fetchone()['total']
            has_orders = (orig_orders + quarantined_orders) > 0

            try:
                orig_convs = bdb.execute("SELECT count(*) AS total FROM conversations WHERE customer_id=?", (c_id,)).fetchone()['total']
                quarantined_convs = bdb.execute("SELECT count(*) AS total FROM conversations WHERE customer_id=?", (quarantine_cid,)).fetchone()['total']
                has_convs = (orig_convs + quarantined_convs) > 0
            except Exception as e:
                raise RuntimeError(f"Failed to query conversations for customer {c_id} in tenant {t_id}: {e}") from e

            is_ambiguous = (has_orders or has_convs)
            new_cids = {}

            if is_ambiguous:
                # Ambiguous collision: quarantine orders & conversations pending manual reconciliation
                bdb.execute("INSERT INTO customers (id, name) VALUES (?,?) ON CONFLICT DO NOTHING",
                            (quarantine_cid, "Quarantined Ambiguous Collision"))
                if orig_orders > 0:
                    bdb.execute("UPDATE orders SET customer_id=? WHERE customer_id=?", (quarantine_cid, c_id))
                if orig_convs > 0:
                    try:
                        bdb.execute("UPDATE conversations SET customer_id=? WHERE customer_id=?", (quarantine_cid, c_id))
                    except Exception as e:
                        raise RuntimeError(f"Failed to update conversations for customer {c_id}: {e}") from e

                for m in members:
                    pid = m['principal_id']
                    hash_key = f"{t_id}:{pid}:{c_id}".encode()
                    new_cid = f"cust_{hashlib.sha256(hash_key).hexdigest()[:32]}"
                    new_cids[m['id']] = new_cid
                    bdb.execute("INSERT INTO customers (id, name) VALUES (?,?) ON CONFLICT DO NOTHING",
                                (new_cid, m['name']))
            else:
                for secondary in members[1:]:
                    sec_pid = secondary['principal_id']
                    sec_hash_key = f"{t_id}:{sec_pid}:{c_id}".encode()
                    new_cid = f"cust_{hashlib.sha256(sec_hash_key).hexdigest()[:32]}"
                    new_cids[secondary['id']] = new_cid
                    bdb.execute("INSERT INTO customers (id, name) VALUES (?,?) ON CONFLICT DO NOTHING",
                                (new_cid, secondary['name']))

        # Business DB transaction is now committed. Execute Identity DB updates:
        if is_ambiguous:
            for m in members:
                new_cid = new_cids[m['id']]
                db.execute('UPDATE memberships SET customer_id=? WHERE id=?', (new_cid, m['id']))
                db.execute('DELETE FROM sessions WHERE membership_id=?', (m['id'],))
                db.execute(
                    'INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) '
                    'VALUES (?,?,?,?,?) ON CONFLICT(tenant_id, principal_id) DO UPDATE SET customer_id=excluded.customer_id',
                    (str(uuid.uuid4()), t_id, m['principal_id'], new_cid, time.time())
                )

            db.execute(
                'INSERT INTO identity_events(created_at, kind, tenant_id, membership_id) VALUES (?,?,?,?)',
                (time.time(), 'collision_quarantined_reconciliation_required', t_id, None)
            )
            db.execute('DELETE FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?', (t_id, c_id))
        else:
            for secondary in members[1:]:
                new_cid = new_cids[secondary['id']]
                db.execute('UPDATE memberships SET customer_id=? WHERE id=?', (new_cid, secondary['id']))
                db.execute('DELETE FROM sessions WHERE membership_id=?', (secondary['id'],))
                db.execute(
                    'INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) '
                    'VALUES (?,?,?,?,?) ON CONFLICT(tenant_id, principal_id) DO UPDATE SET customer_id=excluded.customer_id',
                    (str(uuid.uuid4()), t_id, secondary['principal_id'], new_cid, time.time())
                )
                db.execute(
                    'INSERT INTO identity_events(created_at, kind, tenant_id, membership_id) VALUES (?,?,?,?)',
                    (time.time(), 'legacy_collision_migrated', t_id, secondary['id'])
                )
            # Link primary member
            db.execute(
                'INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) '
                'VALUES (?,?,?,?,?) ON CONFLICT(tenant_id, principal_id) DO UPDATE SET customer_id=excluded.customer_id',
                (str(uuid.uuid4()), t_id, members[0]['principal_id'], c_id, time.time())
            )
            db.execute('DELETE FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?', (t_id, c_id))

    unlinked = db.execute('''
        SELECT m.id, m.tenant_id, m.principal_id, m.customer_id, p.name
        FROM memberships m
        JOIN principals p ON p.id=m.principal_id
        LEFT JOIN customer_links cl ON cl.tenant_id = m.tenant_id AND cl.principal_id = m.principal_id
        WHERE m.role = 'customer' AND cl.id IS NULL
    ''').fetchall()

    for m in unlinked:
        if m['id'] in unresolved_collision_members:
            continue
        try:
            is_unres = db.execute(
                'SELECT 1 FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?',
                (m['tenant_id'], m['customer_id'])
            ).fetchone()
        except Exception:
            is_unres = None
        if is_unres:
            continue
        existing_link = db.execute(
            'SELECT 1 FROM customer_links WHERE tenant_id=? AND customer_id=?',
            (m['tenant_id'], m['customer_id'])
        ).fetchone()
        assigned_cid = m['customer_id'] if not existing_link else f"cust_{uuid.uuid4().hex}"
        if assigned_cid != m['customer_id']:
            db.execute('UPDATE memberships SET customer_id=? WHERE tenant_id=? AND principal_id=?',
                       (assigned_cid, m['tenant_id'], m['principal_id']))
        db.execute(
            'INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) VALUES (?,?,?,?,?) '
            'ON CONFLICT(tenant_id, principal_id) DO UPDATE SET customer_id=excluded.customer_id',
            (str(uuid.uuid4()), m['tenant_id'], m['principal_id'], assigned_cid, time.time())
        )
        b_conn_ctx = get_tenant_db_conn(m['tenant_id'])
        if b_conn_ctx:
            with b_conn_ctx as bdb:
                bdb.execute("INSERT INTO customers (id, name) VALUES (?,?) ON CONFLICT DO NOTHING",
                            (assigned_cid, m['name']))


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value)


def valid_name(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 100


class IdentityStore:
    def __init__(self, path, tenant_stores=None, data_mode=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.tenant_stores = tenant_stores
        self.data_mode = data_mode
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
        with self.connection(write=True) as db:
            migrate(db, 'identity', initialize)
            migrate_legacy_collisions(db, tenant_stores=tenant_stores)

    def migrate_legacy_collisions(self, tenant_stores=None):
        stores = tenant_stores if tenant_stores is not None else self.tenant_stores
        with self.connection(write=True) as db:
            migrate_legacy_collisions(db, tenant_stores=stores)

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def event(db, kind, tenant=None, membership=None):
        db.execute('INSERT INTO identity_events(created_at,kind,tenant_id,membership_id) VALUES (?,?,?,?)',
                   (time.time(), kind, tenant, membership))

    def ensure_tenant(self, tenant_id, name):
        require(valid_id(tenant_id) and valid_name(name), 400, 'invalid_tenant', 'Thông tin cửa hàng không hợp lệ.')
        with self.connection(write=True) as db:
            row = db.execute('SELECT * FROM tenants WHERE id=?', (tenant_id,)).fetchone()
            if row:
                require(row['name'] == name, 409, 'tenant_conflict', 'Mã cửa hàng đã dùng với tên khác.')
            else:
                db.execute('INSERT INTO tenants(id,name,storage_key) VALUES (?,?,?)', (tenant_id, name, uuid.uuid4().hex))
                self.event(db, 'tenant_created', tenant_id)
        return self.tenant(tenant_id)

    def tenant(self, tenant_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM tenants WHERE id=?', (tenant_id,)).fetchone()
        require(row is not None and row['active'], 404, 'tenant_not_found', 'Không tìm thấy cửa hàng đang hoạt động.')
        return dict(row)

    def create_membership(self, tenant_id, principal_id, name, customer_id, role):
        require(valid_id(principal_id) and valid_name(name) and valid_id(customer_id) and role in ROLE_PERMISSIONS,
                400, 'invalid_membership', 'Thông tin tài khoản hoặc quyền không hợp lệ.')
        self.tenant(tenant_id)
        with self.connection(write=True) as db:
            person = db.execute('SELECT name FROM principals WHERE id=?', (principal_id,)).fetchone()
            require(person is None or person['name'] == name, 409, 'principal_conflict', 'Mã người dùng đã thuộc tên khác.')
            require(db.execute('SELECT 1 FROM memberships WHERE tenant_id=? AND principal_id=?',
                               (tenant_id, principal_id)).fetchone() is None,
                    409, 'membership_exists', 'Tài khoản đã thuộc cửa hàng này.')
            db.execute('INSERT INTO principals VALUES (?,?) ON CONFLICT DO NOTHING', (principal_id, name))
            if role == 'customer':
                existing_link = db.execute(
                    'SELECT principal_id FROM customer_links WHERE tenant_id=? AND customer_id=?',
                    (tenant_id, customer_id)
                ).fetchone()
                require(existing_link is None or existing_link['principal_id'] == principal_id,
                        409, 'customer_link_conflict', 'Mã khách hàng đã được gán cho tài khoản khác trong cửa hàng này.')
                db.execute(
                    'INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) '
                    'VALUES (?,?,?,?,?) ON CONFLICT(tenant_id, principal_id) DO UPDATE SET customer_id=excluded.customer_id',
                    (str(uuid.uuid4()), tenant_id, principal_id, customer_id, time.time())
                )
            mid = str(uuid.uuid4())
            db.execute('INSERT INTO memberships(id,tenant_id,principal_id,customer_id,role) VALUES (?,?,?,?,?)',
                       (mid, tenant_id, principal_id, customer_id, role))
            self.event(db, 'membership_created', tenant_id, mid)
        return mid

    def membership(self, membership_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM memberships WHERE id=?', (membership_id,)).fetchone()
        require(row is not None, 404, 'membership_not_found', 'Không tìm thấy tài khoản.')
        return dict(row)

    def register_credential(self, membership_id, token):
        require(isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', token),
                400, 'invalid_credential', 'Credential phải do bộ sinh mã ngẫu nhiên của quản trị tạo.')
        with self.connection(write=True) as db:
            row = db.execute('SELECT * FROM memberships WHERE id=? AND active=1', (membership_id,)).fetchone()
            require(row is not None, 404, 'membership_not_found', 'Không tìm thấy tài khoản đang hoạt động.')
            db.execute('DELETE FROM credentials WHERE membership_id=?', (membership_id,))
            db.execute('INSERT INTO credentials VALUES (?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), membership_id, time.time()))
            db.execute('UPDATE memberships SET auth_version=auth_version+1 WHERE id=?', (membership_id,))
            db.execute('DELETE FROM sessions WHERE membership_id=?', (membership_id,))
            self.event(db, 'credential_rotated', row['tenant_id'], membership_id)

    def set_role(self, membership_id, role):
        require(role in ROLE_PERMISSIONS, 400, 'invalid_role', 'Quyền không hợp lệ.')
        with self.connection(write=True) as db:
            row = db.execute('SELECT tenant_id FROM memberships WHERE id=?', (membership_id,)).fetchone()
            require(row is not None, 404, 'membership_not_found', 'Không tìm thấy tài khoản.')
            db.execute('UPDATE memberships SET role=?,auth_version=auth_version+1 WHERE id=?', (role, membership_id))
            db.execute('DELETE FROM sessions WHERE membership_id=?', (membership_id,))
            self.event(db, 'role_changed', row['tenant_id'], membership_id)

    def revoke(self, membership_id):
        with self.connection(write=True) as db:
            row = db.execute('SELECT tenant_id FROM memberships WHERE id=?', (membership_id,)).fetchone()
            require(row is not None, 404, 'membership_not_found', 'Không tìm thấy tài khoản.')
            db.execute('UPDATE memberships SET active=0,auth_version=auth_version+1 WHERE id=?', (membership_id,))
            db.execute('DELETE FROM credentials WHERE membership_id=?', (membership_id,))
            db.execute('DELETE FROM sessions WHERE membership_id=?', (membership_id,))
            self.event(db, 'membership_revoked', row['tenant_id'], membership_id)

    def rate(self, bucket, limit):
        window = int(time.time()) // 60
        with self.connection(write=True) as db:
            row = db.execute('SELECT "window",count FROM identity_rate WHERE bucket=?', (bucket,)).fetchone()
            require(row is None or row['window'] != window or row['count'] < limit,
                    429, 'rate_limited', 'Có quá nhiều yêu cầu. Vui lòng thử lại sau một phút.')
            db.execute('''INSERT INTO identity_rate VALUES (?,?,1) ON CONFLICT(bucket) DO UPDATE SET
                count=CASE WHEN identity_rate."window"=excluded."window" THEN identity_rate.count+1 ELSE 1 END,
                "window"=excluded."window"''', (bucket, window))

    def login(self, token, lifetime, capacity):
        self.rate('login', 15)  # Commit bad-login attempts separately from failed authentication.
        require(isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', token),
                401, 'unauthorized', 'Mã truy cập cá nhân chưa đúng hoặc đã bị thu hồi.')
        with self.connection(write=True) as db:
            row = db.execute('''SELECT m.* FROM credentials c JOIN memberships m ON c.membership_id=m.id
                JOIN tenants t ON t.id=m.tenant_id WHERE c.hash=? AND m.active=1 AND t.active=1''',
                (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            require(row is not None, 401, 'unauthorized', 'Mã truy cập cá nhân chưa đúng hoặc đã bị thu hồi.')
            if row['role'] == 'customer':
                col_cnt = db.execute(
                    "SELECT count(*) as total FROM memberships WHERE tenant_id=? AND customer_id=? AND role='customer'",
                    (row['tenant_id'], row['customer_id'])
                ).fetchone()['total']
                try:
                    unres = db.execute(
                        "SELECT 1 FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?",
                        (row['tenant_id'], row['customer_id'])
                    ).fetchone()
                except Exception:
                    unres = None
                if col_cnt > 1 or unres:
                    require(False, 503, 'collision_unresolved', 'Tài khoản đang chờ xử lý va chạm dữ liệu.')
            db.execute('DELETE FROM sessions WHERE expires_at<=?', (time.time(),))
            require(db.execute('SELECT count(*) AS total FROM sessions').fetchone()['total'] < capacity,
                    429, 'session_capacity', 'Hệ thống đã đủ phiên đăng nhập. Vui lòng thử lại sau.')
            secret = secrets.token_urlsafe(32)
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (hashlib.sha256(secret.encode()).hexdigest(),
                       row['id'], row['auth_version'], time.time()+lifetime))
            self.event(db, 'login', row['tenant_id'], row['id'])
        return secret

    def create_session_for_membership(self, membership_id, lifetime, capacity):
        with self.connection(write=True) as db:
            row = db.execute('''SELECT m.* FROM memberships m
                JOIN tenants t ON t.id=m.tenant_id WHERE m.id=? AND m.active=1 AND t.active=1''',
                (membership_id,)).fetchone()
            require(row is not None, 401, 'unauthorized', 'Tài khoản chưa được kích hoạt hoặc không tồn tại.')
            if row['role'] == 'customer':
                col_cnt = db.execute(
                    "SELECT count(*) as total FROM memberships WHERE tenant_id=? AND customer_id=? AND role='customer'",
                    (row['tenant_id'], row['customer_id'])
                ).fetchone()['total']
                try:
                    unres = db.execute(
                        "SELECT 1 FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?",
                        (row['tenant_id'], row['customer_id'])
                    ).fetchone()
                except Exception:
                    unres = None
                if col_cnt > 1 or unres:
                    require(False, 503, 'collision_unresolved', 'Tài khoản đang chờ xử lý va chạm dữ liệu.')
            db.execute('DELETE FROM sessions WHERE expires_at<=?', (time.time(),))
            require(db.execute('SELECT count(*) AS total FROM sessions').fetchone()['total'] < capacity,
                    429, 'session_capacity', 'Hệ thống đã đủ phiên đăng nhập. Vui lòng thử lại sau.')
            secret = secrets.token_urlsafe(32)
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (hashlib.sha256(secret.encode()).hexdigest(),
                       row['id'], row['auth_version'], time.time()+lifetime))
            self.event(db, 'login', row['tenant_id'], row['id'])
        return secret

    def get_or_create_google_member(self, tenant_id, email, name, role='customer', customer_id=None, sub=None, issuer='https://accounts.google.com', email_verified=False, live=False):
        email_clean = email.strip().lower()
        require(role in ROLE_PERMISSIONS, 400, 'invalid_role', 'Quyền không hợp lệ.')
        name_clean = name.strip() if (name and isinstance(name, str) and name.strip()) else email_clean.split('@')[0]
        sub_clean = str(sub).strip() if (sub and str(sub).strip()) else None
        issuer_clean = str(issuer).strip() if (issuer and str(issuer).strip()) else 'https://accounts.google.com'

        is_live = live or getattr(self, 'data_mode', None) in ('production', 'live')
        if is_live and not sub_clean:
            require(False, 400, 'missing_sub', 'Live Google authentication requires a verified sub.')

        self.tenant(tenant_id)
        with self.connection(write=True) as db:
            principal_id = None
            # 1. External identity check: UNIQUE(issuer, sub)
            if sub_clean:
                ext = db.execute('SELECT * FROM external_identities WHERE issuer=? AND sub=?',
                                 (issuer_clean, sub_clean)).fetchone()
                if ext:
                    principal_id = ext['principal_id']
                    db.execute('UPDATE principals SET name=? WHERE id=?', (name_clean, principal_id))

            # 2. If not found by (issuer, sub), check if this is a returning legacy principal (ONLY IF email_verified is True!)
            if not principal_id:
                if email_verified and sub_clean:
                    prefix = re.sub(r'[^a-zA-Z0-9_-]', '_', email_clean.split('@')[0])[:25]
                    hash_suffix = hashlib.sha256(email_clean.encode()).hexdigest()[:10]
                    legacy_pid = f"g_{prefix}_{hash_suffix}"
                    legacy_p = db.execute('SELECT id, name FROM principals WHERE id=?', (legacy_pid,)).fetchone()
                    if not legacy_p:
                        legacy_p = db.execute('SELECT id, name FROM principals WHERE id=?', (email_clean,)).fetchone()

                    if legacy_p:
                        # Check if legacy principal is already bound to a different sub
                        already_bound = db.execute(
                            'SELECT sub FROM external_identities WHERE issuer=? AND principal_id=?',
                            (issuer_clean, legacy_p['id'])
                        ).fetchone()
                        if already_bound and already_bound['sub'] != sub_clean:
                            # Bound to another sub! Do not merge identities
                            principal_id = None
                        else:
                            principal_id = legacy_p['id']
                            db.execute(
                                'INSERT INTO external_identities (id, issuer, sub, principal_id, email, created_at) '
                                'VALUES (?,?,?,?,?,?) ON CONFLICT(issuer, sub) DO UPDATE SET principal_id=excluded.principal_id',
                                (str(uuid.uuid4()), issuer_clean, sub_clean, principal_id, email_clean, time.time())
                            )

                if not principal_id:
                    principal_id = f"prin_{uuid.uuid4().hex}"
                    db.execute('INSERT INTO principals (id, name) VALUES (?,?)', (principal_id, name_clean))
                    effective_sub = sub_clean or f"demo_{uuid.uuid4().hex}"
                    db.execute(
                        'INSERT INTO external_identities (id, issuer, sub, principal_id, email, created_at) '
                        'VALUES (?,?,?,?,?,?) ON CONFLICT(issuer, sub) DO NOTHING',
                        (str(uuid.uuid4()), issuer_clean, effective_sub, principal_id, email_clean, time.time())
                    )

            existing = db.execute('SELECT * FROM memberships WHERE tenant_id=? AND principal_id=?',
                                  (tenant_id, principal_id)).fetchone()
            if existing:
                mid = existing['id']
                cid = existing['customer_id']
                if existing['role'] == 'customer':
                    col_cnt = db.execute(
                        "SELECT count(*) as total FROM memberships WHERE tenant_id=? AND customer_id=? AND role='customer'",
                        (tenant_id, cid)
                    ).fetchone()['total']
                    try:
                        unres = db.execute(
                            "SELECT 1 FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?",
                            (tenant_id, cid)
                        ).fetchone()
                    except Exception:
                        unres = None
                    if col_cnt > 1 or unres:
                        require(False, 503, 'collision_unresolved', 'Tài khoản đang chờ xử lý va chạm dữ liệu.')

                if existing['role'] != role:
                    db.execute('UPDATE memberships SET role=?, auth_version=auth_version+1 WHERE id=?', (role, mid))
                    self.event(db, 'role_changed', tenant_id, mid)
                db.execute(
                    'INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) '
                    'VALUES (?,?,?,?,?) ON CONFLICT(tenant_id, principal_id) DO UPDATE SET customer_id=excluded.customer_id',
                    (str(uuid.uuid4()), tenant_id, principal_id, cid, time.time())
                )
                return mid, cid

            # 3. Customer linkage: UNIQUE(tenant_id, customer_id) and UNIQUE(tenant_id, principal_id)
            cust_link = db.execute('SELECT * FROM customer_links WHERE tenant_id=? AND principal_id=?',
                                   (tenant_id, principal_id)).fetchone()
            if cust_link:
                cid = cust_link['customer_id']
            else:
                cid = customer_id or f"cust_{uuid.uuid4().hex}"
                existing_cust = db.execute(
                    'SELECT principal_id FROM customer_links WHERE tenant_id=? AND customer_id=?',
                    (tenant_id, cid)
                ).fetchone()
                existing_mem = db.execute(
                    "SELECT 1 FROM memberships WHERE tenant_id=? AND customer_id=? AND role='customer'",
                    (tenant_id, cid)
                ).fetchone()
                try:
                    unres = db.execute(
                        "SELECT 1 FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?",
                        (tenant_id, cid)
                    ).fetchone()
                except Exception:
                    unres = None
                if (existing_cust and existing_cust['principal_id'] != principal_id) or existing_mem or unres:
                    cid = f"cust_{uuid.uuid4().hex}"
                db.execute(
                    'INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) VALUES (?,?,?,?,?) '
                    'ON CONFLICT(tenant_id, principal_id) DO UPDATE SET customer_id=excluded.customer_id',
                    (str(uuid.uuid4()), tenant_id, principal_id, cid, time.time())
                )

            mid = str(uuid.uuid4())
            db.execute('INSERT INTO memberships(id,tenant_id,principal_id,customer_id,role) VALUES (?,?,?,?,?)',
                       (mid, tenant_id, principal_id, cid, role))
            self.event(db, 'membership_created', tenant_id, mid)
            return mid, cid

    def resolve(self, sid):
        with self.connection() as db:
            row = db.execute('''SELECT m.*,t.storage_key,p.name FROM sessions s
                JOIN memberships m ON m.id=s.membership_id JOIN tenants t ON t.id=m.tenant_id
                JOIN principals p ON p.id=m.principal_id
                WHERE s.id=? AND s.expires_at>? AND s.auth_version=m.auth_version AND m.active=1 AND t.active=1''',
                (sid, time.time())).fetchone()
        require(row is not None, 401, 'session_expired', 'Phiên đã kết thúc hoặc quyền đã thay đổi. Vui lòng đăng nhập lại.')
        return dict(row)

    def logout(self, sid):
        with self.connection(write=True) as db:
            row = db.execute('SELECT membership_id FROM sessions WHERE id=?', (sid,)).fetchone()
            db.execute('DELETE FROM sessions WHERE id=?', (sid,))
            if row:
                self.event(db, 'logout', membership=row['membership_id'])

    def purge(self):
        with self.connection(write=True) as db:
            db.execute('DELETE FROM sessions WHERE expires_at<=?', (time.time(),))
            db.execute('DELETE FROM identity_rate WHERE "window"<?', (int(time.time())//60-2,))

    def reserve_api_attempt(self, limit):
        day = time.strftime('%Y-%m-%d', time.gmtime())
        with self.connection(write=True) as db:
            row = db.execute("SELECT attempts FROM provider_daily_usage WHERE day=? AND provider_id='api'", (day,)).fetchone()
            require(row is None or row['attempts'] < limit, 429, 'api_daily_limit', 'Đã hết lượt chat API hôm nay (UTC).')
            db.execute("""INSERT INTO provider_daily_usage VALUES (?,'api',1) ON CONFLICT(day,provider_id)
                DO UPDATE SET attempts=provider_daily_usage.attempts+1""", (day,))
            cutoff = (datetime.now(timezone.utc) - timedelta(days=31)).date().isoformat()
            db.execute("DELETE FROM provider_daily_usage WHERE day < ?", (cutoff,))
