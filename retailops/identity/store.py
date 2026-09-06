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
            role TEXT NOT NULL CHECK(role IN ('customer','viewer')), active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
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
    ]
    for statement in statements:
        db.execute(statement)


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value)


def valid_name(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 100


class IdentityStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
        with self.connection(write=True) as db:
            migrate(db, 'identity', initialize)

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
            db.execute('DELETE FROM sessions WHERE expires_at<=?', (time.time(),))
            require(db.execute('SELECT count(*) AS total FROM sessions').fetchone()['total'] < capacity,
                    429, 'session_capacity', 'Hệ thống đã đủ phiên đăng nhập. Vui lòng thử lại sau.')
            secret = secrets.token_urlsafe(32)
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (hashlib.sha256(secret.encode()).hexdigest(),
                       row['id'], row['auth_version'], time.time()+lifetime))
            self.event(db, 'login', row['tenant_id'], row['id'])
        return secret

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
