"""Single-EC2, invite-only HTTPS demo. Run with Waitress behind the supplied Caddy.

The public entrypoint owns separate guest databases and cookie sessions. It never
accepts the owner's private bearer token as a business session or exposes keys.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

from agent_protocol import PROTOCOL
from retailops_api import Application, ApiError, BusinessStore, ROOT, api_result, fields, require
from retailops_agent import RemoteAgent
from retailops_baseline import ModelConfig
from retailops_providers import api_from_environment

COOKIE = '__Host-retailops_session'
SESSION_SECONDS = 8 * 3600
CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"


def public_origin(value):
    parsed = urlsplit(value)
    hostname = parsed.hostname or ''
    if (value != 'https://' + hostname or parsed.scheme != 'https' or parsed.netloc != hostname or parsed.path or parsed.query or parsed.fragment
            or len(hostname) > 253 or '.' not in hostname
            or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in hostname.split('.'))):
        raise ValueError('RETAILOPS_PUBLIC_ORIGIN must be https:// followed by a lowercase DNS hostname, with no path or port.')
    return value


class GuestSessions:
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


class PublicWeb:
    def __init__(self, origin, sessions):
        self.origin = public_origin(origin)
        self.host = urlsplit(origin).hostname
        self.sessions = sessions

    def __call__(self, environ, start_response):
        extra, mime = [], 'application/json; charset=utf-8'
        try:
            status, result, mime, extra = self.route(environ)
        except ApiError as exc:
            status, result = exc.status, {'error': exc.code, 'message': exc.message,
                                         **({'trace': exc.trace} if exc.trace else {})}
        except (ValueError, TypeError, UnicodeError):
            status, result = 400, {'error': 'bad_request', 'message': 'Yêu cầu không hợp lệ.'}
        except Exception:
            status, result = 500, {'error': 'internal_error', 'message': 'Không hoàn tất yêu cầu. Hãy tải lại trạng thái.'}
        payload = result if isinstance(result, bytes) else json.dumps(result, ensure_ascii=False).encode()
        headers = [('Content-Type', mime), ('Content-Length', str(len(payload))), ('Cache-Control', 'no-store'),
                   ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer'),
                   ('Content-Security-Policy', CSP), ('X-Frame-Options', 'DENY')]
        start_response(f'{status} {HTTPStatus(status).phrase}', headers + extra)
        return [payload]

    @staticmethod
    def json_body(environ):
        require(environ.get('CONTENT_TYPE', '').split(';')[0].strip().lower() == 'application/json',
                415, 'json_required', 'Yêu cầu phải là JSON.')
        length = environ.get('CONTENT_LENGTH', '')
        require(length.isascii() and length.isdecimal(), 400, 'invalid_length', 'Độ dài yêu cầu không hợp lệ.')
        size = int(length)
        require(0 < size <= 16384, 413, 'body_too_large', 'Yêu cầu quá lớn hoặc rỗng.')
        raw = environ['wsgi.input'].read(size)
        require(len(raw) == size, 400, 'invalid_length', 'Nội dung yêu cầu chưa đầy đủ.')
        return json.loads(raw)

    def route(self, env):
        method, path, host = env.get('REQUEST_METHOD'), env.get('PATH_INFO', ''), env.get('HTTP_HOST', '')
        mime, headers = 'application/json; charset=utf-8', []
        # Health checks may reach Waitress directly. Every business route requires the exact public host.
        loopback_health = method == 'GET' and path == '/healthz' and env.get('REMOTE_ADDR') in ('127.0.0.1', '::1') and host in ('127.0.0.1:8000', 'localhost:8000')
        require(host == self.host or loopback_health, 403, 'invalid_host', 'Địa chỉ web không hợp lệ.')
        require(method in ('GET', 'POST'), 405, 'method_not_allowed', 'Phương thức không được hỗ trợ.')
        require(not env.get('QUERY_STRING'), 400, 'unexpected_query', 'Đường dẫn không nhận tham số truy vấn.')
        if path == '/healthz' and method == 'GET':
            with self.sessions.control.connection() as db:
                db.execute('SELECT 1').fetchone()
            return 200, {'status': 'ok', 'scope': 'synthetic-demo', 'version': '0.5',
                         'agent_protocol': PROTOCOL, 'hosting': 'public-https'}, mime, headers
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/styles.css': ('styles.css', 'text/css; charset=utf-8')}
        if method == 'GET' and path in assets:
            name, mime = assets[path]
            # Fixed assets, no user-supplied file lookup. Public mode is a non-executable data attribute.
            data = (ROOT / 'web' / name).read_bytes()
            if path == '/':
                data = data.replace(b'<body>', b'<body data-auth="cookie">')
            return 200, data, mime, headers
        require(path.startswith('/api/'), 404, 'not_found', 'Không tìm thấy đường dẫn.')
        body = None
        if method == 'POST':
            require(env.get('HTTP_ORIGIN') == self.origin, 403, 'invalid_origin', 'Nguồn yêu cầu không hợp lệ.')
            body = self.json_body(env)
        if method == 'POST' and path == '/api/login':
            fields(body, {'token'})
            secret = self.sessions.login(body['token'])
            headers.append(('Set-Cookie', f'{COOKIE}={secret}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={SESSION_SECONDS}'))
            return 200, {'scope': 'synthetic-demo', 'session_seconds': SESSION_SECONDS}, mime, headers
        cookie = env.get('HTTP_COOKIE', '')
        with self.sessions.session(cookie) as app:
            if method == 'POST' and path == '/api/logout':
                fields(body, set())
                self.sessions.logout(cookie)
                headers.append(('Set-Cookie', f'{COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0'))
                return 200, {'logged_out': True}, mime, headers
            status, result = api_result(app, 'C-001', method, path, body, env.get('HTTP_IDEMPOTENCY_KEY'))
            if path == '/api/session':
                result.update(session_scope='isolated-guest', session_seconds=SESSION_SECONDS)
            return status, result, mime, headers


def create_application():
    origin = public_origin(os.getenv('RETAILOPS_PUBLIC_ORIGIN', ''))
    api = api_from_environment()
    infer = None
    # A stopped Colab must never prevent the API-backed website from starting.
    if os.getenv('RETAILOPS_PUBLIC_CUSTOM_ENABLED', 'false').lower() == 'true':
        infer = RemoteAgent(ModelConfig(model=os.getenv('RETAILOPS_MODEL', 'qwen3.5:4b'),
                                       base_url=os.getenv('RETAILOPS_MODEL_URL', '')),
                            allowed_host=os.getenv('RETAILOPS_ALLOWED_HOST', ''),
                            token=os.getenv('RETAILOPS_INFERENCE_TOKEN', ''))
    sessions = GuestSessions(Path(os.getenv('RETAILOPS_OUTPUT', '/data')) / 'public-guests',
                             os.getenv('RETAILOPS_PUBLIC_INVITE_TOKEN', ''), infer, api,
                             int(os.getenv('RETAILOPS_API_DAILY_TURN_LIMIT', '20')))
    return PublicWeb(origin, sessions)


def main():
    from waitress import serve
    app = create_application()
    print('RetailOps HTTPS backend ready; awaiting Caddy.', flush=True)
    # No trusted forwarded headers: authorization uses the configured origin and cookie only.
    serve(app, host='0.0.0.0', port=8000, threads=8, connection_limit=100,
          channel_timeout=30, max_request_header_size=16384, max_request_body_size=16384,
          clear_untrusted_proxy_headers=True, expose_tracebacks=False, ident='RetailOps')


if __name__ == '__main__':
    main()
