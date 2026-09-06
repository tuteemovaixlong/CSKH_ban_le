"""Private, synthetic RetailOps API. Serve only through the documented SSM tunnel.

The model extracts intent. Only an authenticated, explicit confirmation changes
an order. This standard-library server is a single-instance demo, not public hosting.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from retailops_baseline import ModelConfig, RemoteOllama, Runner, Store

REASONS = {"ordered_by_mistake": "Tôi đặt nhầm", "no_longer_needed": "Tôi không còn cần"}
ROOT = Path(__file__).resolve().parent
STATUSES = {"pending": "Chờ xử lý", "delivered": "Đã giao", "cancelled": "Đã hủy"}


class ApiError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def require(condition, status, code, message):
    if not condition:
        raise ApiError(status, code, message)


def fields(body, expected):
    require(isinstance(body, dict) and set(body) == set(expected), 400,
            "invalid_fields", "Các trường của yêu cầu không hợp lệ.")


class BusinessStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS orders (
                  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, name TEXT NOT NULL,
                  variant TEXT NOT NULL, amount INTEGER NOT NULL,
                  status TEXT NOT NULL CHECK(status IN ('pending','delivered','cancelled')),
                  version INTEGER NOT NULL DEFAULT 1, cancel_reason TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
                CREATE TABLE IF NOT EXISTS proposals (
                  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, order_id TEXT NOT NULL REFERENCES orders(id),
                  order_version INTEGER NOT NULL, reason TEXT NOT NULL,
                  expires_at REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                  confirm_key TEXT, result TEXT,
                  UNIQUE(customer_id, confirm_key)
                );
                CREATE TABLE IF NOT EXISTS business_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT NOT NULL,
                  created_at REAL NOT NULL, kind TEXT NOT NULL, order_id TEXT, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_business_events_customer_id_id
                  ON business_events(customer_id, id);
            ''')

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def seed(self):
        # INSERT OR IGNORE preserves cancelled orders across process/container restarts.
        with self.connection(write=True) as db:
            db.executemany("INSERT OR IGNORE INTO orders(id, customer_id, name, variant, amount, status) VALUES (?,?,?,?,?,?)", [
                ("O-101", "C-001", "Áo thun Essential", "Trắng · Size M · Số lượng 1", 299000, "pending"),
                ("O-102", "C-001", "Áo khoác Everyday", "Đen · Size L · Số lượng 1", 799000, "delivered"),
                ("O-202", "C-002", "Áo polo", "Xanh · Size M · Số lượng 1", 399000, "pending"),
            ])

    @staticmethod
    def owned(db, customer, oid):
        row = db.execute("SELECT * FROM orders WHERE id=? AND customer_id=?", (oid, customer)).fetchone()
        require(row is not None, 404, "order_not_found", "Không tìm thấy đơn hàng của bạn.")
        return dict(row)

    @staticmethod
    def log(db, customer, kind, oid=None, **payload):
        db.execute("INSERT INTO business_events(customer_id,created_at,kind,order_id,payload) VALUES (?,?,?,?,?)",
                   (customer, time.time(), kind, oid, json.dumps(payload, ensure_ascii=False)))

    def event(self, customer, kind, oid=None, **payload):
        with self.connection(write=True) as db:
            self.log(db, customer, kind, oid, **payload)

    def orders(self, customer):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM orders WHERE customer_id=? ORDER BY id", (customer,))]

    def lookup(self, customer, oid):
        with self.connection(write=True) as db:
            order = self.owned(db, customer, oid)
            self.log(db, customer, "order_viewed", oid)
            return order

    def events(self, customer):
        with self.connection() as db:
            result = [dict(r) for r in db.execute(
                "SELECT id,created_at,kind,order_id,payload FROM business_events WHERE customer_id=? ORDER BY id DESC LIMIT 30", (customer,))]
        for row in result:
            row["payload"] = json.loads(row["payload"])
        return result

    def propose(self, customer, body):
        fields(body, {"order_id", "order_version", "cancel_reason"})
        oid, version, reason = body["order_id"], body["order_version"], body["cancel_reason"]
        require(isinstance(oid, str) and type(version) is int and isinstance(reason, str) and reason in REASONS,
                400, "invalid_proposal", "Chọn mã đơn và một lý do được hỗ trợ.")
        with self.connection(write=True) as db:
            order = self.owned(db, customer, oid)
            require(order["status"] == "pending", 409, "not_cancellable", "Đơn không còn ở trạng thái cho phép hủy.")
            require(order["version"] == version, 409, "stale_order", "Đơn đã thay đổi. Vui lòng tải lại thông tin.")
            pid, expires = str(uuid.uuid4()), time.time() + 600
            db.execute("INSERT INTO proposals(id,customer_id,order_id,order_version,reason,expires_at) VALUES (?,?,?,?,?,?)",
                       (pid, customer, oid, version, reason, expires))
            self.log(db, customer, "cancellation_proposed", oid, proposal_id=pid, reason=reason)
        return {"proposal_id": pid, "order": order, "reason": reason, "expires_at": expires,
                "message": "Đơn chưa bị hủy. Vui lòng xem lại và xác nhận."}

    def confirm(self, customer, pid, body, key):
        fields(body, {"confirmed"})
        require(body["confirmed"] is True, 400, "confirmation_required", "Cần xác nhận rõ ràng trước khi hủy.")
        require(isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key),
                400, "idempotency_required", "Thiếu mã chống thực hiện lặp.")
        with self.connection(write=True) as db:
            p = db.execute("SELECT * FROM proposals WHERE id=? AND customer_id=?", (pid, customer)).fetchone()
            require(p is not None, 404, "proposal_not_found", "Không tìm thấy đề xuất của bạn.")
            if p["state"] == "confirmed":
                require(hmac.compare_digest(p["confirm_key"], key), 409, "already_confirmed", "Đề xuất đã được thực hiện.")
                return {**json.loads(p["result"]), "replayed": True}
            require(p["state"] == "pending" and p["expires_at"] > time.time(),
                    409, "inactive_proposal", "Đề xuất đã hết hạn hoặc bị bỏ. Hãy tạo yêu cầu mới.")
            used = db.execute("SELECT id FROM proposals WHERE customer_id=? AND confirm_key=?", (customer, key)).fetchone()
            require(used is None, 409, "idempotency_conflict", "Mã xác nhận đã dùng cho đề xuất khác.")
            order = self.owned(db, customer, p["order_id"])
            require(order["status"] == "pending" and order["version"] == p["order_version"],
                    409, "stale_order", "Đơn đã thay đổi; yêu cầu hủy chưa được thực hiện.")
            db.execute("UPDATE orders SET status='cancelled', version=version+1, cancel_reason=? WHERE id=? AND customer_id=?",
                       (p["reason"], p["order_id"], customer))
            order = self.owned(db, customer, p["order_id"])
            result = {"order": order, "proposal_id": pid, "replayed": False, "message": "Đã hủy đơn mẫu và lưu nhật ký."}
            db.execute("UPDATE proposals SET state='confirmed', confirm_key=?, result=? WHERE id=?",
                       (key, json.dumps(result, ensure_ascii=False), pid))
            self.log(db, customer, "order_cancelled", order["id"], proposal_id=pid, reason=p["reason"], version=order["version"])
            return result

    def dismiss(self, customer, pid):
        with self.connection(write=True) as db:
            p = db.execute("SELECT * FROM proposals WHERE id=? AND customer_id=?", (pid, customer)).fetchone()
            require(p is not None, 404, "proposal_not_found", "Không tìm thấy đề xuất của bạn.")
            require(p["state"] != "confirmed", 409, "already_confirmed", "Đơn đã được hủy; không thể giữ lại bằng thao tác này.")
            if p["state"] == "pending":
                db.execute("UPDATE proposals SET state='dismissed' WHERE id=?", (pid,))
                self.log(db, customer, "proposal_dismissed", p["order_id"], proposal_id=pid)
        return {"message": "Đã bỏ đề xuất. Trạng thái đơn được giữ nguyên."}


class ModelInference:
    def __init__(self, output):
        self.output = Path(output)
        self.lock = threading.Lock()

    def __call__(self, text):
        require(self.lock.acquire(blocking=False), 429, "model_busy", "Model đang xử lý yêu cầu khác. Vui lòng thử lại.")
        try:
            config = ModelConfig(model=os.getenv("RETAILOPS_MODEL", "qwen3.5:4b"),
                                 base_url=os.getenv("RETAILOPS_MODEL_URL", ""), timeout_s=15)
            gateway = RemoteOllama(config, allowed_host=os.getenv("RETAILOPS_ALLOWED_HOST", ""),
                                   token=os.getenv("RETAILOPS_INFERENCE_TOKEN", ""))
            runner = Runner(gateway, Store(self.output / "api-inference.sqlite3"))
            result = runner.infer(text, cache=False, scope="synthetic-business-demo")
            if not result.get("valid") and "raw_output" not in result:
                raise RuntimeError("Inference transport failed")
            return result
        finally:
            self.lock.release()


class Application:
    def __init__(self, store, tokens, infer=None):
        self.store, self.tokens, self.infer = store, tokens, infer

    def authenticate(self, header):
        token = header.removeprefix("Bearer ") if header.startswith("Bearer ") else ""
        hashed = hashlib.sha256(token.encode()).hexdigest()
        customer = next((c for expected, c in self.tokens.items() if hmac.compare_digest(expected, hashed)), None)
        require(customer is not None, 401, "unauthorized", "Nhập mã truy cập demo hợp lệ.")
        return customer

    def chat(self, customer, body):
        fields(body, {"text"})
        text = body["text"]
        require(isinstance(text, str) and 0 < len(text.strip()) <= 2000, 400, "invalid_text", "Nhập yêu cầu tối đa 2.000 ký tự.")
        require(self.infer is not None, 503, "model_offline", "Model chưa kết nối. Bạn vẫn có thể tra đơn và chọn yêu cầu hủy ở bảng đơn hàng.")
        try:
            record = self.infer(text)
        except ApiError:
            raise
        except (RuntimeError, ValueError, OSError):
            self.store.event(customer, "model_unavailable")
            raise ApiError(503, "model_unavailable", "Không gọi được model. Đơn hàng chưa thay đổi; hãy dùng các nút thao tác.") from None
        self.store.event(customer, "model_extraction", valid=bool(record.get("valid")), latency_ms=record.get("latency_ms"))
        decision = record.get("decision") if record.get("valid") else None
        if not decision:
            return {"action": "clarify", "message": "Chưa xác định được yêu cầu hợp lệ. Hãy gửi đủ mã đơn và lý do, hoặc dùng các nút thao tác.", "model_valid": False}
        action, oid = decision["action"], decision["order_id"]
        if action in ("lookup_order", "cancel_order"):
            explicit_ids = set(re.findall(r"(?<![A-Za-z0-9_-])[A-Z]{1,6}-[0-9]{1,8}(?![A-Za-z0-9_-])", text))
            require(explicit_ids == {oid}, 422, "ungrounded_order", "Hãy ghi rõ đúng một mã đơn; không dùng mã đơn do model suy đoán.")
            order = self.store.lookup(customer, oid)
            if action == "lookup_order":
                return {"action": action, "order": order, "message": f"Đơn {oid}: {STATUSES[order['status']]}."}
            require(order["status"] == "pending", 409, "not_cancellable", "Đơn không còn ở trạng thái cho phép hủy.")
            # Deliberately discard the model's reason, even if schema-valid. The
            # user must select a reason and approve the stored proposal separately.
            return {"action": "choose_cancel_reason", "order": order,
                    "message": "Chọn lý do hủy bên dưới. Đơn chỉ thay đổi sau khi bạn xác nhận."}
        return {"action": action, "message": "Hiện chỉ hỗ trợ tra và hủy đơn mẫu." if action == "unsupported"
                else "Vui lòng nêu rõ một mã đơn và yêu cầu cần xử lý. Bạn cũng có thể dùng các nút thao tác."}


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, app):
        self.app = app
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
    server_version = "RetailOpsDemo/0.2"
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
            self.reply(exc.status, {"error": exc.code, "message": exc.message})
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
            return self.reply(200, {"status": "ok", "scope": "synthetic-demo"})
        assets = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/styles.css": ("styles.css", "text/css; charset=utf-8")}
        if self.command == "GET" and path in assets:
            name, mime = assets[path]
            return self.reply(200, (ROOT / "web" / name).read_bytes(), mime)
        require(path.startswith("/api/"), 404, "not_found", "Không tìm thấy đường dẫn.")
        customer = app.authenticate(self.headers.get("Authorization", ""))
        if self.command == "GET":
            if path == "/api/session":
                return self.reply(200, {"customer_id": customer, "name": "Mai Anh" if customer == "C-001" else "Khách mẫu",
                                        "model_configured": app.infer is not None, "scope": "synthetic-demo"})
            if path == "/api/orders":
                return self.reply(200, {"orders": app.store.orders(customer)})
            if path == "/api/events":
                return self.reply(200, {"events": app.store.events(customer)})
            m = re.fullmatch(r"/api/orders/([A-Z]{1,6}-[0-9]{1,8})", path)
            if m:
                return self.reply(200, {"order": app.store.lookup(customer, m[1])})
        if self.command == "POST":
            require(self.headers.get("Origin") in (None, "http://" + host), 403, "invalid_origin", "Nguồn yêu cầu không hợp lệ.")
            require(self.headers.get_content_type() == "application/json", 415, "json_required", "Yêu cầu phải là JSON.")
            lengths = self.headers.get_all("Content-Length", [])
            require(len(lengths) == 1 and self.headers.get("Transfer-Encoding") is None, 400, "invalid_length", "Độ dài yêu cầu không hợp lệ.")
            size = int(lengths[0])
            require(0 < size <= 16384, 413, "body_too_large", "Yêu cầu quá lớn hoặc rỗng.")
            body = json.loads(self.rfile.read(size))
            if path == "/api/chat":
                return self.reply(200, app.chat(customer, body))
            if path == "/api/cancellation-proposals":
                return self.reply(201, app.store.propose(customer, body))
            m = re.fullmatch(r"/api/cancellation-proposals/([a-f0-9-]{36})/(confirm|dismiss)", path)
            if m:
                if m[2] == "confirm":
                    return self.reply(200, app.store.confirm(customer, m[1], body, self.headers.get("Idempotency-Key")))
                fields(body, set())
                return self.reply(200, app.store.dismiss(customer, m[1]))
        raise ApiError(404, "not_found", "Không tìm thấy đường dẫn.")


def main():
    token = os.getenv("RETAILOPS_DEMO_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
        raise SystemExit("Set RETAILOPS_DEMO_TOKEN to a random 32–128 character URL-safe value.")
    output = Path(os.getenv("RETAILOPS_OUTPUT", str(ROOT / "artifacts")))
    store = BusinessStore(output / "business.sqlite3")
    store.seed()
    infer = ModelInference(output) if os.getenv("RETAILOPS_MODEL_ENABLED", "false").lower() == "true" else None
    app = Application(store, {hashlib.sha256(token.encode()).hexdigest(): "C-001"}, infer)
    address = (os.getenv("RETAILOPS_API_BIND", "127.0.0.1"), int(os.getenv("RETAILOPS_API_PORT", "8000")))
    print("RetailOps synthetic API started; model configured:", infer is not None, flush=True)
    with Server(address, app) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
