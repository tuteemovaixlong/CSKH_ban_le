"""Disposable, invite-only demo workspaces. Not a production identity backend.

Only this adapter ties a demo database to an expiring guest session. A durable
identity backend must resolve existing business data without this purge policy.
"""
from __future__ import annotations
import hashlib
import hmac
import re
import secrets
import threading
import time
from contextlib import contextmanager
from http.cookies import SimpleCookie
from pathlib import Path
from retailops.core import require
from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.identity.contracts import SessionBinding

COOKIE = '__Host-retailops_session'
SESSION_SECONDS = 8 * 3600

class GuestSessions:
    data_mode = 'synthetic-demo'
    cookie_name = COOKIE
    session_seconds = SESSION_SECONDS

    def __init__(self, directory, invite, infer=None, api_infer=None, api_daily_limit=20, capacity=50):
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', invite):
            raise ValueError('Set a random RETAILOPS_PUBLIC_INVITE_TOKEN (32–128 URL-safe characters).')
        if type(api_daily_limit) is not int or not 1 <= api_daily_limit <= 10000:
            raise ValueError('API daily turn limit must be an integer from 1 to 10000.')
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.invite_hash = hashlib.sha256(invite.encode()).hexdigest()
        self.infer, self.api_infer, self.api_daily_limit = infer, api_infer, api_daily_limit
        self.capacity = capacity
        self.lock = threading.RLock()
        self.agent_lock = threading.Lock()
        self.apps, self.active = {}, {}
        # All guests share this persistent quota. Owner business.sqlite3 is untouched.
        self.control = BusinessStore(self.directory / 'control.sqlite3')
        with self.control.connection(write=True) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS guest_sessions (
                  id TEXT PRIMARY KEY, invite_hash TEXT NOT NULL, expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS public_rate (
                  bucket TEXT PRIMARY KEY, window INTEGER NOT NULL, count INTEGER NOT NULL
                );
            ''')
        self.purge()

    def rate(self, bucket, limit, seconds=60):
        window = int(time.time()) // seconds
        with self.control.connection(write=True) as db:
            row = db.execute('SELECT window,count FROM public_rate WHERE bucket=?', (bucket,)).fetchone()
            require(row is None or row['window'] != window or row['count'] < limit,
                    429, 'rate_limited', 'Demo đang nhận nhiều yêu cầu. Vui lòng thử lại sau một phút.')
            db.execute('''INSERT INTO public_rate VALUES (?,?,1) ON CONFLICT(bucket) DO UPDATE SET
                count=CASE WHEN window=excluded.window THEN count+1 ELSE 1 END, window=excluded.window''', (bucket, window))

    def purge(self):
        with self.lock, self.control.connection(write=True) as db:
            rows = db.execute('SELECT id FROM guest_sessions WHERE expires_at<? OR invite_hash!=?',
                              (time.time(), self.invite_hash)).fetchall()
            for row in rows:
                sid = row['id']
                if self.active.get(sid, 0):
                    continue
                self.apps.pop(sid, None)
                # IDs are generated hashes, never browser-supplied paths.
                if re.fullmatch('[a-f0-9]{64}', sid):
                    for suffix in ('', '-wal', '-shm'):
                        (self.directory / (sid + '.sqlite3' + suffix)).unlink(missing_ok=True)
                db.execute('DELETE FROM guest_sessions WHERE id=?', (sid,))
                db.execute('DELETE FROM public_rate WHERE bucket=?', ('session:' + sid,))

    def login(self, token):
        self.rate('login', 15)
        require(isinstance(token, str) and len(token) <= 128
                and hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), self.invite_hash),
                401, 'unauthorized', 'Mã mời demo chưa đúng.')
        with self.lock:
            self.purge()
            secret = secrets.token_urlsafe(32)
            sid = hashlib.sha256(secret.encode()).hexdigest()
            with self.control.connection(write=True) as db:
                count = db.execute('SELECT count(*) FROM guest_sessions').fetchone()[0]
                require(count < self.capacity, 429, 'demo_capacity', 'Demo đã đủ phiên. Vui lòng thử lại sau.')
                db.execute('INSERT INTO guest_sessions VALUES (?,?,?)',
                           (sid, self.invite_hash, time.time() + SESSION_SECONDS))
            return secret

    @staticmethod
    def cookie_id(header):
        cookies = SimpleCookie()
        try:
            cookies.load(header)
            value = cookies[COOKIE].value
        except (KeyError, ValueError):
            value = ''
        require(re.fullmatch(r'[A-Za-z0-9_-]{43}', value), 401, 'unauthorized', 'Nhập mã mời để mở phiên demo.')
        return hashlib.sha256(value.encode()).hexdigest()

    @contextmanager
    def session(self, header):
        sid = self.cookie_id(header)
        with self.lock:
            with self.control.connection() as db:
                row = db.execute('SELECT expires_at,invite_hash FROM guest_sessions WHERE id=?', (sid,)).fetchone()
            require(row is not None and row['expires_at'] > time.time() and row['invite_hash'] == self.invite_hash,
                    401, 'session_expired', 'Phiên demo đã kết thúc. Hãy nhập lại mã mời.')
            self.rate('session:' + sid, 60)
            if sid not in self.apps:
                store = BusinessStore(self.directory / (sid + '.sqlite3'))
                store.seed()
                app = Application(store, {}, self.infer, self.api_infer, self.api_daily_limit)
                app.quota_store = self.control
                app.agent_lock = self.agent_lock
                app.default_provider = 'api' if self.api_infer is not None else 'custom'
                self.apps[sid] = app
            self.active[sid] = self.active.get(sid, 0) + 1
            app = self.apps[sid]
        try:
            yield app
        finally:
            with self.lock:
                self.active[sid] -= 1
                if not self.active[sid]:
                    del self.active[sid]

    def logout(self, header):
        sid = self.cookie_id(header)
        with self.control.connection(write=True) as db:
            db.execute('UPDATE guest_sessions SET expires_at=0 WHERE id=?', (sid,))
        self.purge()

    @contextmanager
    def resolve(self, header):
        with self.session(header) as app:
            yield SessionBinding(app, customer_id='C-001', workspace_id=self.cookie_id(header))

    def check_health(self):
        with self.control.connection() as db:
            db.execute('SELECT 1').fetchone()

    def metadata(self):
        return {'session_scope': 'isolated-guest', 'session_seconds': self.session_seconds}
