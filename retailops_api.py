"""Private, synthetic RetailOps API. Serve only through the documented SSM tunnel.

The model chats through read-only tools. Only an authenticated, explicit confirmation changes
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

from retailops_baseline import ModelConfig
from agent_protocol import PROTOCOL
from retailops_agent import AgentError, RemoteAgent, run_agent
from retailops_tools import BoundTools
from retailops_providers import API_MODEL, api_from_environment
from retailops_conversation import Catalog, describe_order

REASONS = {"ordered_by_mistake": "Tôi đặt nhầm", "no_longer_needed": "Tôi không còn cần"}
ROOT = Path(__file__).resolve().parent
STATUSES = {"pending": "Chờ xử lý", "delivered": "Đã giao", "cancelled": "Đã hủy"}


class ApiError(Exception):
    def __init__(self, status, code, message, trace=None):
        self.status, self.code, self.message = status, code, message
        self.trace = trace
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
                CREATE TABLE IF NOT EXISTS agent_turns (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                  customer_id TEXT NOT NULL, request_id TEXT NOT NULL, input_hash TEXT NOT NULL,
                  messages TEXT NOT NULL, result TEXT NOT NULL, created_at REAL NOT NULL,
                  UNIQUE(conversation_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS provider_daily_usage (
                  day TEXT NOT NULL, provider_id TEXT NOT NULL, attempts INTEGER NOT NULL,
                  PRIMARY KEY(day,provider_id)
                );
            ''')
            if 'provider_id' not in {row['name'] for row in db.execute('PRAGMA table_info(conversations)')}:
                db.execute("ALTER TABLE conversations ADD COLUMN provider_id TEXT NOT NULL DEFAULT 'custom'")

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

    def new_conversation(self, customer, provider_id='custom'):
        cid = str(uuid.uuid4())
        with self.connection(write=True) as db:
            db.execute('DELETE FROM conversations WHERE expires_at < ?', (time.time(),))
            db.execute('INSERT INTO conversations(id,customer_id,expires_at,provider_id) VALUES (?,?,?,?)',
                       (cid, customer, time.time() + 1800, provider_id))
        return {'conversation_id': cid, 'provider_id': provider_id, 'context': {'order_id': None, 'product_id': None}}

    def reserve_api_attempt(self, limit):
        # Reserve before network I/O; even failed/timed-out calls can be billable.
        day = time.strftime('%Y-%m-%d', time.gmtime())
        with self.connection(write=True) as db:
            row = db.execute("SELECT attempts FROM provider_daily_usage WHERE day=? AND provider_id='api'", (day,)).fetchone()
            require(row is None or row['attempts'] < limit, 429, 'api_daily_limit',
                    'Demo đã hết lượt chat API hôm nay (UTC). Bạn có thể chọn custom model đang được cấu hình.')
            db.execute("""INSERT INTO provider_daily_usage(day,provider_id,attempts) VALUES (?,'api',1)
                ON CONFLICT(day,provider_id) DO UPDATE SET attempts=attempts+1""", (day,))
            db.execute("DELETE FROM provider_daily_usage WHERE day < date('now','-31 days')")

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

    def replay(self, customer, cid, request_id, digest):
        with self.connection() as db:
            row = db.execute('''SELECT input_hash,result FROM agent_turns
                WHERE conversation_id=? AND customer_id=? AND request_id=?''',
                (cid, customer, request_id)).fetchone()
        if row:
            require(row['input_hash'] == digest, 409, 'request_conflict', 'Mã yêu cầu đã dùng cho nội dung khác.')
            result = json.loads(row['result'])
            # The answer is explicitly an old result. Never reopen a stale cancel card.
            return {**result, 'replayed': True, 'action': 'reply'}
        return None

    def history(self, customer, cid):
        with self.connection() as db:
            rows = db.execute('''SELECT messages FROM agent_turns WHERE conversation_id=? AND customer_id=?
                ORDER BY id DESC LIMIT 6''', (cid, customer)).fetchall()
        turns, characters, count = [], 0, 0
        for row in rows:
            messages = json.loads(row['messages'])
            size = sum(len(m.get('content', '')) + len(json.dumps(m.get('tool_calls', []), ensure_ascii=False)) for m in messages)
            if characters + size > 4500 or count + len(messages) > 16:
                break  # Keep whole contiguous turns, never orphan tool calls/results.
            characters += size; count += len(messages); turns.append(messages)
        return [m for turn in reversed(turns) for m in turn]

    def finish_turn(self, customer, snapshot, request_id, digest, messages, result, versions):
        with self.connection(write=True) as db:
            for oid, version in versions.items():
                require(self.owned(db, customer, oid)['version'] == version, 409, 'order_changed_during_chat',
                        'Đơn đã thay đổi trong lúc model trả lời. Hãy gửi lại để đọc trạng thái mới.')
            context = result['context']
            updated = db.execute('''UPDATE conversations SET order_id=?,product_id=?,revision=revision+1,expires_at=?
                WHERE id=? AND customer_id=? AND revision=? AND expires_at>?''',
                (context['order_id'], context['product_id'], time.time()+1800, snapshot['id'], customer,
                 snapshot['revision'], time.time())).rowcount
            require(updated == 1, 409, 'conversation_changed', 'Ngữ cảnh đã thay đổi hoặc hết hạn. Hãy gửi lại trong cuộc trò chuyện hiện tại.')
            db.execute('''INSERT INTO agent_turns(conversation_id,customer_id,request_id,input_hash,messages,result,created_at)
                VALUES (?,?,?,?,?,?,?)''', (snapshot['id'], customer, request_id, digest,
                json.dumps(messages, ensure_ascii=False), json.dumps(result, ensure_ascii=False), time.time()))
            # Transcript retention is bounded; expired conversations are removed on next creation.
            db.execute('''DELETE FROM agent_turns WHERE conversation_id=? AND id NOT IN
                (SELECT id FROM agent_turns WHERE conversation_id=? ORDER BY id DESC LIMIT 6)''',
                (snapshot['id'], snapshot['id']))
            self.log(db, customer, 'agent_replied', context['order_id'], trace=result['trace'])

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


class Application:
    def __init__(self, store, tokens, infer=None, api_infer=None, api_daily_limit=20):
        self.store, self.tokens, self.infer = store, tokens, infer
        self.api_infer = api_infer
        if type(api_daily_limit) is not int or not 1 <= api_daily_limit <= 10000:
            raise ValueError('API daily turn limit must be an integer from 1 to 10000')
        self.api_daily_limit = api_daily_limit
        self.catalog = Catalog()
        self.agent_lock = threading.Lock()

    def providers(self):
        custom_model = getattr(getattr(self.infer, 'config', None), 'model', 'qwen3.5:4b')
        api_model = getattr(self.api_infer, 'model', API_MODEL)
        return {'default_provider': 'custom', 'providers': [
            {'id': 'custom', 'label': 'Custom model · Colab/Ollama', 'model': custom_model,
             'configured': self.infer is not None, 'notice': 'Cần phiên model đang chạy. Kết nối được kiểm tra khi gửi tin.'},
            {'id': 'api', 'label': 'API · OpenRouter', 'model': api_model,
             'configured': self.api_infer is not None,
             'notice': f'API tính phí theo sử dụng, tối đa {self.api_daily_limit} lần thử chat/ngày UTC cho demo. Contributor: nội dung có thể được Meta dùng để cải thiện sản phẩm. Chỉ nhập dữ liệu giả lập.',
             'daily_turn_limit': self.api_daily_limit}]}

    def new_conversation(self, customer, body):
        require(isinstance(body, dict) and set(body) in (set(), {'provider_id'}),
                400, 'invalid_fields', 'Chỉ chọn nguồn model đã được cấu hình.')
        provider_id = body.get('provider_id', 'custom')
        require(isinstance(provider_id, str) and provider_id in ('custom', 'api'),
                400, 'invalid_provider', 'Nguồn model không hợp lệ.')
        # Offline custom sessions still support direct business buttons. API is opt-in.
        require(provider_id != 'api' or self.api_infer is not None, 503, 'provider_not_configured',
                'API chưa được chủ demo cấu hình. Hãy chọn custom model.')
        return self.store.new_conversation(customer, provider_id)

    def authenticate(self, header):
        token = header.removeprefix("Bearer ") if header.startswith("Bearer ") else ""
        hashed = hashlib.sha256(token.encode()).hexdigest()
        customer = next((c for expected, c in self.tokens.items() if hmac.compare_digest(expected, hashed)), None)
        require(customer is not None, 401, "unauthorized", "Nhập mã truy cập demo hợp lệ.")
        return customer

    def chat(self, customer, body):
        fields(body, {'text', 'conversation_id', 'request_id'})
        text, request_id = body['text'], body['request_id']
        require(isinstance(text, str) and 0 < len(text.strip()) <= 2000,
                400, 'invalid_text', 'Nhập yêu cầu tối đa 2.000 ký tự.')
        require(isinstance(request_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{16,128}', request_id),
                400, 'invalid_request_id', 'Thiếu mã yêu cầu hội thoại.')
        snapshot = self.store.conversation(customer, body['conversation_id'])
        digest = hashlib.sha256(text.encode()).hexdigest()
        replay = self.store.replay(customer, snapshot['id'], request_id, digest)
        if replay:
            return replay
        provider_id = snapshot['provider_id']
        gateway = self.infer if provider_id == 'custom' else self.api_infer if provider_id == 'api' else None
        require(gateway is not None, 503, 'model_offline',
                'Model chưa kết nối. Bạn vẫn có thể dùng các nút tra đơn và yêu cầu hủy.')
        require(self.agent_lock.acquire(blocking=False), 429, 'model_busy',
                'Model đang xử lý một cuộc trò chuyện khác. Bạn thử lại sau nhé.')
        try:
            # A concurrent completed retry must not spend GPU or duplicate history.
            replay = self.store.replay(customer, snapshot['id'], request_id, digest)
            if replay:
                return replay
            if hasattr(gateway, 'for_turn'):
                gateway = gateway.for_turn()
            identity = {**gateway.inspect(), 'selection': provider_id}
            if provider_id == 'api':
                self.store.reserve_api_attempt(self.api_daily_limit)
            bound = BoundTools(self.store, self.catalog, customer, snapshot, identity)

            def execute(name, arguments):
                try:
                    return bound(name, arguments)
                except ApiError as exc:
                    if name in ('get_order', 'prepare_cancellation'):
                        bound.context = {'order_id': None, 'product_id': None}
                        bound.cancel_order = None
                    return {'error': exc.code, 'message': exc.message}

            answer = run_agent(gateway, text, self.store.history(customer, snapshot['id']), execute, identity)
            result = {'action': 'choose_cancel_reason' if bound.cancel_order else 'reply',
                      'message': answer['message'], 'source': 'llm_agent', 'model_used': True,
                      'context': bound.context, 'trace': answer['trace'], 'provider_id': provider_id, 'replayed': False}
            if bound.cancel_order:
                result['order'] = bound.cancel_order
            self.store.finish_turn(customer, snapshot, request_id, digest, answer['messages'], result, bound.versions)
            return result
        except AgentError as exc:
            self.store.event(customer, 'agent_failed', code=exc.code, trace=exc.trace)
            raise ApiError(503, exc.code, str(exc), exc.trace) from None
        except (RuntimeError, ValueError, OSError):
            self.store.event(customer, 'agent_failed', code='model_unavailable')
            raise ApiError(503, 'model_unavailable',
                           'Không kết nối được nguồn model đã chọn. Kiểm tra cấu hình; hệ thống không tự chuyển model.') from None
        finally:
            self.agent_lock.release()

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
    server_version = "RetailOpsDemo/0.4.1"
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
            return self.reply(200, {"status": "ok", "scope": "synthetic-demo", "version": "0.4.1", "agent_protocol": PROTOCOL})
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
                                        "model_configured": app.infer is not None or app.api_infer is not None, "scope": "synthetic-demo"})
            if path == "/api/providers":
                return self.reply(200, app.providers())
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
                return self.reply(201, app.new_conversation(customer, body))
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
    infer = None
    if os.getenv('RETAILOPS_MODEL_ENABLED', 'false').lower() == 'true':
        infer = RemoteAgent(ModelConfig(model=os.getenv('RETAILOPS_MODEL', 'qwen3.5:4b'),
                                       base_url=os.getenv('RETAILOPS_MODEL_URL', '')),
                            allowed_host=os.getenv('RETAILOPS_ALLOWED_HOST', ''),
                            token=os.getenv('RETAILOPS_INFERENCE_TOKEN', ''))
    app = Application(store, {hashlib.sha256(token.encode()).hexdigest(): 'C-001'}, infer,
                      api_infer=api_from_environment(),
                      api_daily_limit=int(os.getenv('RETAILOPS_API_DAILY_TURN_LIMIT', '20')))
    address = (os.getenv("RETAILOPS_API_BIND", "127.0.0.1"), int(os.getenv("RETAILOPS_API_PORT", "8000")))
    print("RetailOps synthetic API started; model configured:", infer is not None, flush=True)
    with Server(address, app) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
