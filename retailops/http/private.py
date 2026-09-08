"""Localhost/SSM HTTP adapter. Build and configure it through retailops.bootstrap."""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from agent_protocol import PROTOCOL
from retailops.core import ApiError, ROOT, VERSION, require
from retailops.http.routes import api_result
from retailops.http.assets import ASSETS

LOCAL_AUTO_CUSTOMER = 'C-001'
LOOPBACK_BINDS = ('127.0.0.1', 'localhost')


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, app, *, local_auto_login=False):
        if local_auto_login and address[0] not in LOOPBACK_BINDS:
            raise ValueError('Local auto-login requires a loopback bind.')
        self.app = app
        self.local_auto_login = bool(local_auto_login)
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "RetailOpsDemo/" + VERSION
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        pass  # Do not write tokens, request bodies or upstream URLs to access logs.

    def reply(self, status, body, content_type="application/json; charset=utf-8"):
        payload = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def dispatch(self):
        try:
            self.route()
        except ApiError as exc:
            self.reply(exc.status, {"error": exc.code, "message": exc.message,
                                    **({"trace": exc.trace} if exc.trace else {})})
        except (ValueError, UnicodeError, TypeError):
            self.reply(400, {"error": "bad_request", "message": "Yêu cầu không hợp lệ."})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            self.reply(500, {"error": "internal_error", "message": "Không hoàn tất yêu cầu. Vui lòng tải lại trạng thái trước khi thử tiếp."})

    def route(self):
        host = self.headers.get("Host", "")
        require(re.fullmatch(r"(?:localhost|127\.0\.0\.1)(?::[0-9]{1,5})?", host), 403, "invalid_host", "Mở ứng dụng qua kết nối localhost được hướng dẫn.")
        path = urlsplit(self.path).path
        app = self.server.app
        if self.command == "GET" and path == "/healthz":
            with app.store.connection() as db:
                db.execute("SELECT 1 FROM orders LIMIT 1").fetchone()
            return self.reply(200, {"status": "ok", "scope": "synthetic-demo", "version": VERSION, "agent_protocol": PROTOCOL})
        if self.command == "GET" and path in ASSETS:
            name, mime = ASSETS[path]
            data = (ROOT / "web" / name).read_bytes()
            if path == "/" and self.server.local_auto_login:
                # Reuse the frontend's no-Bearer/session bootstrap path. No cookie is
                # issued locally; identity remains server-owned and loopback-only.
                data = data.replace(b"<body>", b'<body data-auth="cookie" data-local-auto-login="true">')
            return self.reply(200, data, mime)
        require(path.startswith("/api/"), 404, "not_found", "Không tìm thấy đường dẫn.")
        customer = LOCAL_AUTO_CUSTOMER if self.server.local_auto_login else app.authenticate(self.headers.get("Authorization", ""))
        body = None
        if self.command == "POST":
            require(self.headers.get("Origin") in (None, "http://" + host), 403, "invalid_origin", "Nguồn yêu cầu không hợp lệ.")
            require(self.headers.get_content_type() == "application/json", 415, "json_required", "Yêu cầu phải là JSON.")
            lengths = self.headers.get_all("Content-Length", [])
            require(len(lengths) == 1 and self.headers.get("Transfer-Encoding") is None, 400, "invalid_length", "Độ dài yêu cầu không hợp lệ.")
            size = int(lengths[0])
            require(0 < size <= 16384, 413, "body_too_large", "Yêu cầu quá lớn hoặc rỗng.")
            body = json.loads(self.rfile.read(size))
        if self.server.local_auto_login and self.command == "POST" and path == "/api/logout":
            require(body == {}, 400, "invalid_fields", "Không gửi thêm dữ liệu cho thao tác này.")
            return self.reply(200, {"logged_out": True, "local_auto_login": True})
        status, result = api_result(app, customer, self.command, path, body, self.headers.get("Idempotency-Key"))
        return self.reply(status, result)
