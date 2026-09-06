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
from retailops_conversation import Catalog, describe_order, matches, normalize, route

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
                CREATE TABLE IF NOT EXISTS conversations (
                  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
                  order_id TEXT, product_id TEXT,
                  revision INTEGER NOT NULL DEFAULT 0, expires_at REAL NOT NULL
                );
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

    def new_conversation(self, customer):
        cid = str(uuid.uuid4())
        with self.connection(write=True) as db:
            db.execute('DELETE FROM conversations WHERE expires_at < ?', (time.time(),))
            db.execute('INSERT INTO conversations(id,customer_id,expires_at) VALUES (?,?,?)',
                       (cid, customer, time.time() + 1800))
        return {'conversation_id': cid, 'context': {'order_id': None, 'product_id': None}}

    def conversation(self, customer, cid):
        require(isinstance(cid, str) and re.fullmatch(r'[a-f0-9-]{36}', cid),
                400, 'invalid_conversation', 'Mã cuộc trò chuyện không hợp lệ.')
        with self.connection() as db:
            row = db.execute('SELECT * FROM conversations WHERE id=? AND customer_id=?', (cid, customer)).fetchone()
        require(row is not None, 404, 'conversation_not_found', 'Không tìm thấy cuộc trò chuyện của bạn. Hãy mở cuộc trò chuyện mới.')
        require(row['expires_at'] > time.time(), 409, 'conversation_expired', 'Cuộc trò chuyện đã hết hạn. Hãy bấm Cuộc trò chuyện mới.')
        return dict(row)

    def remember(self, customer, snapshot, oid, pid):
        if snapshot is None:
            return
        with self.connection(write=True) as db:
            if oid is not None:
                self.owned(db, customer, oid)
            updated = db.execute('''UPDATE conversations SET order_id=?,product_id=?,revision=revision+1,expires_at=?
                WHERE id=? AND customer_id=? AND revision=? AND expires_at>?''',
                (oid, pid, time.time()+1800, snapshot['id'], customer, snapshot['revision'], time.time())).rowcount
            require(updated == 1, 409, 'conversation_changed', 'Ngữ cảnh đã thay đổi hoặc hết hạn. Hãy gửi lại yêu cầu trong cuộc trò chuyện hiện tại.')

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
        self.catalog = Catalog()

    def authenticate(self, header):
        token = header.removeprefix("Bearer ") if header.startswith("Bearer ") else ""
        hashed = hashlib.sha256(token.encode()).hexdigest()
        customer = next((c for expected, c in self.tokens.items() if hmac.compare_digest(expected, hashed)), None)
        require(customer is not None, 401, "unauthorized", "Nhập mã truy cập demo hợp lệ.")
        return customer

    def chat(self, customer, body):
        require(isinstance(body, dict) and set(body) in ({'text'}, {'text', 'conversation_id'}),
                400, 'invalid_fields', 'Các trường của yêu cầu không hợp lệ.')
        text = body["text"]
        require(isinstance(text, str) and 0 < len(text.strip()) <= 2000, 400, "invalid_text", "Nhập yêu cầu tối đa 2.000 ký tự.")
        snapshot = self.store.conversation(customer, body['conversation_id']) if 'conversation_id' in body else None
        oid = snapshot['order_id'] if snapshot else None
        pid = snapshot['product_id'] if snapshot else None
        plan = route(text, self.catalog)

        def reply(action, message, source='assistant_rules', **extra):
            self.store.remember(customer, snapshot, oid, pid)
            self.store.event(customer, 'chat_replied', action=action, source=source)
            return {'action': action, 'message': message, 'source': source, 'model_used': source == 'model_and_store',
                    'context': {'order_id': oid, 'product_id': pid}, **extra}

        kind = plan['kind']
        if kind == 'ambiguous':
            oid, pid = None, None
            return reply('clarify', 'Bạn đang nhắc đến nhiều đơn hoặc sản phẩm. Hãy chọn một mục để mình trả lời chính xác.')
        if kind == 'greeting':
            return reply('greeting', 'Chào bạn! Mình có thể tra thông tin đơn, giải thích sản phẩm trong danh mục và hỗ trợ yêu cầu hủy. Bạn muốn xem đơn hay sản phẩm nào?')
        if kind == 'courtesy':
            return reply('courtesy', 'Cảm ơn bạn. Nếu cần xem thêm đơn hoặc sản phẩm, bạn cứ hỏi nhé.')
        if kind == 'outside':
            return reply('unsupported', 'Câu hỏi này nằm ngoài phạm vi hỗ trợ cửa hàng. Mình có thể giúp bạn về đơn hàng và sản phẩm trong danh mục mẫu.')
        if kind == 'unsupported_business':
            return reply('unsupported', 'Bản hiện tại chưa hỗ trợ đổi/trả, hoàn tiền hoặc sửa địa chỉ. Mình có thể tra thông tin đơn và hỗ trợ yêu cầu hủy nếu đơn đủ điều kiện.')
        if kind == 'keep':
            return reply('keep_order', 'Tin nhắn này không thực hiện hủy đơn. Nếu đang có đề xuất chờ xác nhận, hãy chọn Giữ đơn hàng trên hộp xác nhận để bỏ đề xuất đó.')

        # An explicit new order is resolved against the authenticated owner, even
        # if the previous conversation referred to a different accessible order.
        order = None
        if plan['ids']:
            oid, pid = None, None  # Never fall back to the previous order on a failed lookup.
            try:
                order = self.store.lookup(customer, plan['ids'][0])
            except ApiError:
                self.store.remember(customer, snapshot, None, None)
                raise
            oid = order['id']
            linked = self.catalog.for_order(order)
            pid = linked['id'] if linked else None

        if kind == 'product':
            named = plan['products'][0] if plan['products'] else None
            if named:
                # Naming a different product does not leave an unrelated order
                # as the target for a later cancellation follow-up.
                if pid != named['id']:
                    oid = None
                pid = named['id']
            elif plan.get('unknown_named'):
                oid, pid = None, None
                return reply('product_not_found', 'Mình chưa tìm thấy sản phẩm bạn nêu trong danh mục. Hiện có Áo thun Essential, Áo khoác Everyday và Áo polo.')
            product = self.catalog.products.get(pid)
            if product is None:
                return reply('clarify', 'Bạn muốn hỏi sản phẩm nào? Hãy nêu tên sản phẩm hoặc tra một đơn trước.')
            return reply('product_details', self.catalog.describe(product, plan.get('field')), 'catalog',
                         product=product, catalog_source=self.catalog.source)

        if kind == 'order':
            if oid is None:
                return reply('clarify', 'Bạn muốn xem đơn nào? Hãy gửi một mã đơn, ví dụ O-101 hoặc O-102.')
            # Read state again on every turn, never render a stale order snapshot.
            order = order or self.store.lookup(customer, oid)
            product = self.catalog.for_order(order)
            pid = product['id'] if product else None
            return reply('lookup_order', describe_order(order, STATUSES, REASONS, plan.get('field')), 'store_data', order=order)

        model_text = text
        if not plan['ids'] and matches(r'\b(don (nay|do|ay)|ma (nay|do)|this order|that order)\b', normalize(text)):
            if oid is None:
                return reply('clarify', 'Mình chưa xác định được đơn đang nhắc tới. Bạn gửi mã đơn trước nhé.')
            self.store.lookup(customer, oid)
            model_text = text + '\nMã đơn được tham chiếu trong phiên: ' + oid
            require(len(model_text) <= 2000, 400, 'invalid_text', 'Bạn rút ngắn yêu cầu để mình thêm mã đơn đang trao đổi nhé.')
        try:
            result = self._model_chat(customer, model_text)
        except ApiError:
            self.store.remember(customer, snapshot, None, None)
            raise
        if result.get('order'):
            order = result['order']
            oid = order['id']
            product = self.catalog.for_order(order)
            pid = product['id'] if product else None
        action, message = result.pop('action'), result.pop('message')
        return reply(action, message, 'model_and_store', **result)

    def focus(self, customer, cid, body):
        fields(body, {'order_id'})
        require(isinstance(body['order_id'], str), 400, 'invalid_order', 'Mã đơn không hợp lệ.')
        snapshot = self.store.conversation(customer, cid)
        order = self.store.lookup(customer, body['order_id'])
        product = self.catalog.for_order(order)
        pid = product['id'] if product else None
        self.store.remember(customer, snapshot, order['id'], pid)
        return {'order': order, 'message': describe_order(order, STATUSES, REASONS),
                'context': {'order_id': order['id'], 'product_id': pid}, 'source': 'store_data', 'model_used': False}

    def _model_chat(self, customer, text):
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
                return {"action": action, "order": order, "message": describe_order(order, STATUSES, REASONS)}
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
    server_version = "RetailOpsDemo/0.3"
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
            return self.reply(200, {"status": "ok", "scope": "synthetic-demo", "version": "0.3"})
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
            if path == '/api/conversations':
                fields(body, set())
                return self.reply(201, app.store.new_conversation(customer))
            focus = re.fullmatch(r'/api/conversations/([a-f0-9-]{36})/focus', path)
            if focus:
                return self.reply(200, app.focus(customer, focus[1], body))
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
