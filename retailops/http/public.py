"""HTTPS WSGI adapter; session backend supplies authenticated business bindings."""
import hmac
import json
import os
import secrets
import threading
from http import HTTPStatus
from urllib.parse import urlsplit
from agent_protocol import PROTOCOL
from retailops.core import ApiError, ROOT, VERSION, fields, require
from retailops.config import public_origin
from retailops.identity.contracts import SessionBackend
from retailops.http.routes import api_result
from retailops.http.assets import ASSETS

CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"

class PublicWeb:
    def __init__(self, origin, sessions: SessionBackend):
        self.origin = public_origin(origin)
        self.host = urlsplit(origin).hostname
        self.sessions = sessions
        self.chat_admission = threading.BoundedSemaphore(6)

    def __call__(self, environ, start_response):
        extra, mime = [], 'application/json; charset=utf-8'
        acquired_chat = False
        method = environ.get('REQUEST_METHOD')
        path = environ.get('PATH_INFO', '')
        try:
            if method == 'POST' and path == '/api/chat':
                if not self.chat_admission.acquire(blocking=False):
                    raise ApiError(429, 'server_busy', 'Máy chủ đang bận xử lý hội thoại khác. Vui lòng thử lại sau giây lát.',
                                   headers=[('Retry-After', '5')])
                acquired_chat = True
            status, result, mime, extra = self.route(environ)
        except ApiError as exc:
            status, result = exc.status, {'error': exc.code, 'message': exc.message,
                                         **({'trace': exc.trace} if exc.trace else {})}
            if exc.headers:
                extra.extend(exc.headers)
        except (ValueError, TypeError, UnicodeError):
            status, result = 400, {'error': 'bad_request', 'message': 'Yêu cầu không hợp lệ.'}
        except Exception:
            status, result = 500, {'error': 'internal_error', 'message': 'Không hoàn tất yêu cầu. Hãy tải lại trạng thái.'}
        finally:
            if acquired_chat:
                self.chat_admission.release()
        payload = result if isinstance(result, bytes) else json.dumps(result, ensure_ascii=False).encode()
        headers = [('Content-Type', mime), ('Content-Length', str(len(payload))), ('Cache-Control', 'no-store'),
                   ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer'),
                   ('Content-Security-Policy', CSP), ('X-Frame-Options', 'DENY')]
        start_response(f'{status} {HTTPStatus(status).phrase}', headers + extra)
        return [payload]

    @staticmethod
    def json_body(environ, max_size=16384):
        require(environ.get('CONTENT_TYPE', '').split(';')[0].strip().lower() == 'application/json',
                415, 'json_required', 'Yêu cầu phải là JSON.')
        length = environ.get('CONTENT_LENGTH', '')
        require(length.isascii() and length.isdecimal(), 400, 'invalid_length', 'Độ dài yêu cầu không hợp lệ.')
        size = int(length)
        require(0 < size <= max_size, 413, 'body_too_large', 'Yêu cầu quá lớn hoặc rỗng.')
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
        require(not env.get('QUERY_STRING') or path == '/auth/google/callback', 400, 'unexpected_query', 'Đường dẫn không nhận tham số truy vấn.')

        # Emergency maintenance mode check for auth and provisioning routes
        if path in ('/auth/google/config', '/auth/google/login', '/auth/google/callback') or (path == '/api/login' and method == 'POST'):
            is_maintenance = (
                os.environ.get('RETAILOPS_AUTH_MAINTENANCE', '').strip().lower() in ('1', 'true', 'yes')
                or getattr(self, 'auth_maintenance', False) is True
                or getattr(self.sessions, 'auth_maintenance', False) is True
            )
            require(not is_maintenance, 503, 'maintenance_mode',
                    'Hệ thống xác thực đang bảo trì để đối soát dữ liệu.')
        if path == '/healthz' and method == 'GET':
            self.sessions.check_health()
            return 200, {'status': 'ok', 'scope': 'synthetic-demo', 'version': VERSION,
                         'data_mode': self.sessions.data_mode,
                         'storage_backend': self.sessions.metadata().get('storage_backend', 'sqlite'),
                         'agent_protocol': PROTOCOL, 'hosting': 'public-https'}, mime, headers
        if method == 'GET' and path in ASSETS:
            name, mime = ASSETS[path]
            # Fixed assets, no user-supplied file lookup. Public mode is a non-executable data attribute.
            data = (ROOT / 'web' / name).read_bytes()
            if path == '/':
                from retailops.http.auth_google import is_google_auth_configured
                mode = b' data-data-mode="persistent-demo"' if getattr(self.sessions, 'data_mode', None) == 'persistent-demo' else b''
                gauth = b' data-google-auth="true"' if is_google_auth_configured() else b''
                data = data.replace(b'<body>', b'<body data-auth="cookie"' + mode + gauth + b'>')
            return 200, data, mime, headers

        if path == '/auth/google/config' and method == 'GET':
            from retailops.http.auth_google import is_google_auth_configured
            return 200, {'configured': is_google_auth_configured()}, mime, headers

        if path == '/auth/google/login' and method == 'GET':
            from retailops.http.auth_google import is_google_auth_configured, create_state, get_google_auth_url
            require(is_google_auth_configured(), 503, 'google_auth_not_configured', 'Đăng nhập Google chưa được cấu hình trên máy chủ.')
            nonce = secrets.token_hex(16)
            state = create_state(nonce)
            redirect_url = get_google_auth_url(self.origin, state)
            headers.append(('Set-Cookie', f'retailops_oauth_transient={nonce}; Path=/auth/google; Secure; HttpOnly; SameSite=Lax; Max-Age=600'))
            headers.append(('Location', redirect_url))
            return 302, b'', 'text/html; charset=utf-8', headers

        if path == '/auth/google/callback' and method == 'GET':
            import hashlib
            import urllib.parse
            from retailops.http.auth_google import (
                verify_and_consume_state, exchange_code_for_user_info, resolve_role_from_email
            )
            # Parse transient nonce cookie
            cookie_header = env.get('HTTP_COOKIE', '')
            transient_nonce = None
            if cookie_header:
                for part in cookie_header.split(';'):
                    if '=' in part:
                        k, v = part.strip().split('=', 1)
                        if k == 'retailops_oauth_transient':
                            transient_nonce = v
                            break

            query_str = env.get('QUERY_STRING', '')
            query_params = urllib.parse.parse_qs(query_str)
            code = query_params.get('code', [''])[0]
            state = query_params.get('state', [''])[0]

            # Multi-tab safety: check if state matches this browser cookie nonce
            state_matches_cookie = False
            parts = state.split('.') if state else []
            if len(parts) == 4 and transient_nonce:
                expected_nh = hashlib.sha256(transient_nonce.encode('utf-8')).hexdigest()[:16]
                if hmac.compare_digest(parts[2], expected_nh):
                    state_matches_cookie = True

            clean_cookie_header = ('Set-Cookie', 'retailops_oauth_transient=; Path=/auth/google; Secure; HttpOnly; SameSite=Lax; Max-Age=0')
            err_headers = [clean_cookie_header] if state_matches_cookie else []

            require(code and state, 400, 'missing_oauth_params', 'Thiếu thông tin xác thực từ Google.', headers=err_headers)
            require(verify_and_consume_state(state, browser_nonce=transient_nonce), 403, 'invalid_oauth_state', 'Phiên xác thực đã hết hạn hoặc không hợp lệ.', headers=err_headers)

            try:
                user_info = exchange_code_for_user_info(code, self.origin)
            except ValueError as e:
                require(False, 400, 'oauth_exchange_failed', str(e), headers=err_headers)

            role = resolve_role_from_email(user_info['email'])
            is_live = getattr(self.sessions, 'data_mode', None) in ('production', 'live')
            email_verified = bool(user_info.get('email_verified', False))
            if is_live and not email_verified:
                require(False, 400, 'unverified_email', 'Tài khoản Google chưa được xác minh email.', headers=err_headers)

            secret = self.sessions.login_google(
                user_info['email'],
                user_info['name'],
                role=role,
                sub=user_info.get('sub'),
                email_verified=email_verified,
                live=is_live
            )
            if transient_nonce:
                headers.append(clean_cookie_header)
            headers.append(('Set-Cookie', f'{self.sessions.cookie_name}={secret}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age={self.sessions.session_seconds}'))
            headers.append(('Location', '/'))
            return 302, b'', 'text/html; charset=utf-8', headers

        require(path.startswith('/api/'), 404, 'not_found', 'Không tìm thấy đường dẫn.')
        body = None
        if method == 'POST':
            require(env.get('HTTP_ORIGIN') == self.origin, 403, 'invalid_origin', 'Nguồn yêu cầu không hợp lệ.')
            max_size = 10_485_760 if path in ('/api/chat', '/api/staff/customer-message') else 16384
            body = self.json_body(env, max_size=max_size)
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
            app.current_binding = binding
            status, result = api_result(app, binding.customer_id, method, path, body, env.get('HTTP_IDEMPOTENCY_KEY'), binding=binding)
            if path == '/api/session':
                result.update(self.sessions.metadata())
                if binding.principal_id is not None:
                    result.update(tenant_id=binding.tenant_id, principal_id=binding.principal_id,
                                  name=binding.display_name)
            return status, result, mime, headers
