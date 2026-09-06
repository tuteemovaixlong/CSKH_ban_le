"""HTTPS WSGI adapter; session backend supplies authenticated business bindings."""
import json
from http import HTTPStatus
from urllib.parse import urlsplit
from agent_protocol import PROTOCOL
from retailops.core import ApiError, ROOT, VERSION, fields, require
from retailops.config import public_origin
from retailops.identity.contracts import SessionBackend
from retailops.http.routes import api_result

CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"

class PublicWeb:
    def __init__(self, origin, sessions: SessionBackend):
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
            self.sessions.check_health()
            return 200, {'status': 'ok', 'scope': 'synthetic-demo', 'version': VERSION,
                         'data_mode': self.sessions.data_mode,
                         'storage_backend': self.sessions.metadata().get('storage_backend', 'sqlite'),
                         'agent_protocol': PROTOCOL, 'hosting': 'public-https'}, mime, headers
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/styles.css': ('styles.css', 'text/css; charset=utf-8')}
        if method == 'GET' and path in assets:
            name, mime = assets[path]
            # Fixed assets, no user-supplied file lookup. Public mode is a non-executable data attribute.
            data = (ROOT / 'web' / name).read_bytes()
            if path == '/':
                mode = b' data-data-mode="persistent-demo"' if self.sessions.data_mode == 'persistent-demo' else b''
                data = data.replace(b'<body>', b'<body data-auth="cookie"' + mode + b'>')
            return 200, data, mime, headers
        require(path.startswith('/api/'), 404, 'not_found', 'Không tìm thấy đường dẫn.')
        body = None
        if method == 'POST':
            require(env.get('HTTP_ORIGIN') == self.origin, 403, 'invalid_origin', 'Nguồn yêu cầu không hợp lệ.')
            body = self.json_body(env)
        if method == 'POST' and path == '/api/login':
            fields(body, {'token'})
            secret = self.sessions.login(body['token'])
            headers.append(('Set-Cookie', f'{self.sessions.cookie_name}={secret}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={self.sessions.session_seconds}'))
            return 200, {'scope': 'synthetic-demo', 'session_seconds': self.sessions.session_seconds}, mime, headers
        cookie = env.get('HTTP_COOKIE', '')
        with self.sessions.resolve(cookie) as binding:
            app = binding.application
            if method == 'POST' and path == '/api/logout':
                fields(body, set())
                self.sessions.logout(cookie)
                headers.append(('Set-Cookie', f'{self.sessions.cookie_name}=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0'))
                return 200, {'logged_out': True}, mime, headers
            status, result = api_result(app, binding.customer_id, method, path, body, env.get('HTTP_IDEMPOTENCY_KEY'))
            if path == '/api/session':
                result.update(self.sessions.metadata())
                if binding.principal_id is not None:
                    result.update(tenant_id=binding.tenant_id, principal_id=binding.principal_id,
                                  name=binding.display_name)
            return status, result, mime, headers
