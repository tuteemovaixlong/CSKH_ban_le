"""Disposable, invite-only demo workspaces. Not a production identity backend.

Only this adapter ties a demo database to an expiring guest session. A durable
identity backend must resolve existing business data without this purge policy.
"""
from __future__ import annotations
import hashlib
import hmac
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from http.cookies import SimpleCookie
from pathlib import Path
from retailops.core import require
from retailops.business.application import Application
from retailops.business.progress import TurnCancelRegistry
from retailops.business.store import BusinessStore
from retailops.identity.contracts import SessionBinding
from retailops.inference_gate import InferenceGate

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
        self.inference_gate = InferenceGate()
        self.cancel_registry = TurnCancelRegistry()
        self.apps, self.active = {}, {}
        self._seeded_sids: set[str] = set()
        self._guest_names: dict[str, str] = {}
        self._store_template_meta: tuple[float, tuple[str, str], dict] | None = None
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

    def _rate_in_tx(self, db, bucket, limit, seconds=60):
        window = int(time.time()) // seconds
        row = db.execute('SELECT window,count FROM public_rate WHERE bucket=?', (bucket,)).fetchone()
        require(row is None or row['window'] != window or row['count'] < limit,
                429, 'rate_limited', 'Demo đang nhận nhiều yêu cầu. Vui lòng thử lại sau một phút.')
        db.execute('''INSERT INTO public_rate VALUES (?,?,1) ON CONFLICT(bucket) DO UPDATE SET
            count=CASE WHEN window=excluded.window THEN count+1 ELSE 1 END, window=excluded.window''', (bucket, window))

    def rate(self, bucket, limit, seconds=60):
        with self.control.connection(write=True) as db:
            self._rate_in_tx(db, bucket, limit, seconds=seconds)

    def _ensure_store_template(self) -> tuple[Path, dict]:
        tmpl_path = self.directory / '_store_seed_template.sqlite3'
        env_sig = (
            os.environ.get('RETAILOPS_ENV', '').strip(),
            os.environ.get('RETAILOPS_EVENT_DIGEST_KEY_FILE', '').strip(),
        )
        now = time.time()
        if (
            self._store_template_meta is not None
            and tmpl_path.is_file()
            and tmpl_path.stat().st_size > 0
            and self._store_template_meta[1] == env_sig
            and (now - self._store_template_meta[0]) < 300.0
        ):
            return tmpl_path, dict(self._store_template_meta[2])
        for suffix in ('', '-wal', '-shm'):
            (self.directory / ('_store_seed_template.sqlite3' + suffix)).unlink(missing_ok=True)
        tmpl_store = BusinessStore(tmpl_path)
        tmpl_store.data_mode = getattr(self, 'data_mode', 'synthetic-demo')
        tmpl_store.tenant_id = 'guest-template'
        tmpl_store.seed()
        raw_conn = sqlite3.connect(str(tmpl_path))
        try:
            raw_conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            raw_conn.execute('PRAGMA journal_mode=DELETE')
        finally:
            raw_conn.close()
        ext_map = dict(getattr(tmpl_store, '_standalone_ext_mappings', {}))
        self._store_template_meta = (now, env_sig, ext_map)
        return tmpl_path, dict(ext_map)

    def purge(self):
        with self.lock, self.control.connection(write=True) as db:
            rows = db.execute('SELECT id FROM guest_sessions WHERE expires_at<? OR invite_hash!=?',
                              (time.time(), self.invite_hash)).fetchall()
            for row in rows:
                sid = row['id']
                if self.active.get(sid, 0):
                    continue
                self.apps.pop(sid, None)
                self._seeded_sids.discard(sid)
                self._guest_names.pop(sid, None)
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
                cnt_row = db.execute('SELECT count(*) AS cnt FROM guest_sessions').fetchone()
                if cnt_row:
                    try:
                        count = cnt_row['cnt'] if 'cnt' in cnt_row else cnt_row[0]
                    except (TypeError, KeyError, IndexError):
                        count = cnt_row[0] if cnt_row else 0
                else:
                    count = 0
                require(count < self.capacity, 429, 'demo_capacity', 'Demo đã đủ phiên. Vui lòng thử lại sau.')
                db.execute('INSERT INTO guest_sessions VALUES (?,?,?)',
                           (sid, self.invite_hash, time.time() + SESSION_SECONDS))
            return secret

    def login_google(self, email, name, role='customer', sub=None, **kwargs):
        self.rate('login', 15)
        with self.lock:
            self.purge()
            secret = secrets.token_urlsafe(32)
            sid = hashlib.sha256(secret.encode()).hexdigest()
            with self.control.connection(write=True) as db:
                cnt_row = db.execute('SELECT count(*) AS cnt FROM guest_sessions').fetchone()
                if cnt_row:
                    try:
                        count = cnt_row['cnt'] if 'cnt' in cnt_row else cnt_row[0]
                    except (TypeError, KeyError, IndexError):
                        count = cnt_row[0] if cnt_row else 0
                else:
                    count = 0
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
            with self.control.connection(write=True) as db:
                row = db.execute('SELECT expires_at,invite_hash FROM guest_sessions WHERE id=?', (sid,)).fetchone()
                require(row is not None and row['expires_at'] > time.time() and row['invite_hash'] == self.invite_hash,
                        401, 'session_expired', 'Phiên demo đã kết thúc. Hãy nhập lại mã mời.')
                self._rate_in_tx(db, 'session:' + sid, 60)
            if sid not in self.apps:
                db_file = self.directory / (sid + '.sqlite3')
                has_custom_clock = callable(getattr(self, 'store_clock', None))
                existing_db = db_file.is_file() and db_file.stat().st_size > 0
                already_seeded = sid in self._seeded_sids and existing_db
                copied_store_template = False
                template_ext_map = None
                if not existing_db and not has_custom_clock:
                    tmpl_path, template_ext_map = self._ensure_store_template()
                    shutil.copyfile(tmpl_path, db_file)
                    copied_store_template = True
                store = BusinessStore(
                    db_file,
                    initialize_db=not (already_seeded or copied_store_template),
                )
                store.data_mode = getattr(self, 'data_mode', 'synthetic-demo')
                store.tenant_id = f'guest-{sid[:16]}'
                store.data_root = self.directory.parent if self.directory.name == 'public-guests' else self.directory
                if has_custom_clock:
                    store.clock = self.store_clock
                if getattr(self, 'case_timer_config', None) is not None:
                    store.case_timer_config = self.case_timer_config
                if copied_store_template:
                    store._standalone_ext_mappings = template_ext_map
                    with store.connection() as wdb:
                        wdb.execute('PRAGMA journal_mode=WAL')
                    store.seed_demo_sample_orders('C-001')
                if not already_seeded:
                    if not copied_store_template and not store.has_demo_store_seed():
                        store.seed()
                        store.seed_demo_sample_orders('C-001')
                    with store.connection() as rdb:
                        crow = rdb.execute("SELECT name FROM customers WHERE id='C-001'").fetchone()
                    self._guest_names[sid] = (
                        str(crow['name']).strip() if crow and crow['name'] else 'Khách mẫu'
                    )
                    self._seeded_sids.add(sid)
                app = Application(store, {}, self.infer, self.api_infer, self.api_daily_limit,
                                  cancel_registry=self.cancel_registry)
                app.quota_store = self.control
                app.inference_gate = self.inference_gate
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
        sid = self.cookie_id(header)
        with self.session(header) as app:
            yield SessionBinding(
                app,
                customer_id='C-001',
                workspace_id=sid,
                display_name=self._guest_names.get(sid),
            )

    def check_health(self):
        with self.control.connection() as db:
            db.execute('SELECT 1').fetchone()

    def metadata(self):
        return {'session_scope': 'isolated-guest', 'session_seconds': self.session_seconds}

    def run_case_timers_once(self, now: float | None = None) -> dict:
        with self.lock:
            apps = list(self.apps.values())
        totals = {
            'reminded': 0,
            'resolved_inactivity': 0,
            'resolved_completed': 0,
            'evidence_purged': 0,
            'compensations_proposed': 0,
            'outbox_published': 0,
            'outbox_retried': 0,
            'outbox_dead': 0,
            'outbox_manifests_sealed': 0,
            'tenants': 0,
        }
        for app in apps:
            store = getattr(app, 'store', None)
            if store is None or not hasattr(store, 'process_due_case_timers'):
                continue
            if callable(getattr(self, 'store_clock', None)):
                store.clock = self.store_clock
            if getattr(self, 'case_timer_config', None) is not None:
                store.case_timer_config = self.case_timer_config
            res = store.process_due_case_timers(now=now)
            ev_res = store.purge_expired_evidence(now=now) if hasattr(store, 'purge_expired_evidence') else {}
            comp_res = (
                store.scan_late_delivery_compensations(now=now)
                if hasattr(store, 'scan_late_delivery_compensations')
                else {}
            )
            ob_res = store.process_outbox_batch(now=now) if hasattr(store, 'process_outbox_batch') else {}
            totals['tenants'] += 1
            for k in ('reminded', 'resolved_inactivity', 'resolved_completed'):
                totals[k] += int(res.get(k, 0))
            totals['evidence_purged'] += int(ev_res.get('purged', 0))
            totals['compensations_proposed'] += int(comp_res.get('proposed', 0))
            totals['outbox_published'] += int(ob_res.get('published', 0))
            totals['outbox_retried'] += int(ob_res.get('retried', 0))
            totals['outbox_dead'] += int(ob_res.get('dead', 0))
            totals['outbox_manifests_sealed'] += int(ob_res.get('manifests_sealed', 0))
        return totals
