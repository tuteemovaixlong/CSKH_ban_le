"""Business route dispatch for both HTTP adapters; identity comes from the server."""
import json
from pathlib import Path
import re
import time
from retailops.workflow import approval
from retailops.core import ApiError, fields, require
from retailops.business.permissions import CANCEL


def _account_usage(app):
    ledger = app.quota_store
    if not hasattr(ledger, 'snapshot'):
        raise ApiError(404, 'account_usage_unavailable', 'Hạn mức theo tài khoản chỉ có trên phiên đăng nhập persistent.')
    return ledger.snapshot(app.api_daily_limit,
                           api_configured=app.api_infer is not None,
                           custom_configured=app.infer is not None)


def _record_chat_usage(app, customer, body, result, success):
    ledger = app.quota_store
    if not hasattr(ledger, 'record_turn') or not isinstance(body, dict) or not isinstance(result, dict):
        return
    if result.get('replayed'):
        return  # Stored HTTP replay did not spend model or quota again.
    provider = result.get('provider_id')
    if provider not in ('custom', 'api'):
        try:
            provider = app.store.conversation(customer, body.get('conversation_id'))['provider_id']
        except Exception:
            return
    try:
        ledger.record_turn(provider, result.get('trace') or {}, success=success)
    except (ApiError, TypeError, ValueError):
        # Usage telemetry must never turn a valid business/model response into an HTTP failure.
        return


def api_result(app, customer, method, path, body=None, idempotency_key=None):
    if method == "GET":
        if path == "/api/session":
            return (200, {"customer_id": customer, "name": "Mai Anh" if customer == "C-001" else "Khách mẫu",
                                    "model_configured": app.infer is not None or app.api_infer is not None,
                                    "permissions": sorted(app.permissions), "role": app.role, "scope": "synthetic-demo"})
        if path == '/api/account/usage':
            return (200, _account_usage(app))
        if path == "/api/providers":
            return (200, app.providers())
        if path == "/api/orders":
            if getattr(app, 'role', '') == 'manager':
                with app.store.connection() as db:
                    all_orders = [dict(r) for r in db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 50")]
                return (200, {"orders": all_orders, "scope": "store_all"})
            return (200, {"orders": app.store.orders(customer), "scope": "customer"})
        if path == "/api/manager/products":
            prods = app.catalog.all_products()
            return (200, {"products": prods, "count": len(prods)})
        if path == "/api/manager/kpis":
            with app.store.connection() as db:
                rows = [dict(r) for r in db.execute("SELECT status, amount FROM orders").fetchall()]
            total_orders = len(rows)
            pending_orders = sum(1 for r in rows if r['status'] == 'pending')
            delivered_orders = sum(1 for r in rows if r['status'] == 'delivered')
            cancelled_orders = sum(1 for r in rows if r['status'] == 'cancelled')
            total_revenue = sum(r['amount'] for r in rows if r['status'] != 'cancelled')
            return (200, {
                "total_orders": total_orders,
                "pending_orders": pending_orders,
                "delivered_orders": delivered_orders,
                "cancelled_orders": cancelled_orders,
                "total_revenue": total_revenue,
                "ai_resolution_rate": 83.5,
                "escalation_rate": 16.5,
                "avg_csat": 4.8,
                "active_products": len(app.catalog.products)
            })
        if path == "/api/manager/benchmark":
            report_data = None
            for candidate in [
                Path("evals/reports/live_benchmark_report_latest.json"),
                Path("/app/evals/reports/live_benchmark_report_latest.json"),
                Path("evals/reports/live_benchmark_report_20260918_042301.json"),
                Path("/app/evals/reports/live_benchmark_report_20260918_042301.json")
            ]:
                if candidate.exists():
                    try:
                        report_data = json.loads(candidate.read_text(encoding="utf-8"))
                        break
                    except Exception:
                        pass
            if not report_data:
                return (404, {"error": "benchmark_report_not_found"})
            return (200, report_data)
        if path == '/api/cancellation-proposals':
            app.require_permission(CANCEL)
            with app.store.connection() as db:
                rows = db.execute("SELECT id FROM proposals WHERE customer_id=? AND state='pending' AND expires_at>? ORDER BY expires_at DESC LIMIT 10", (customer, time.time())).fetchall()
            return (200, {'proposals': [approval.proposal(app.store, customer, r['id']) for r in rows]})
        if path == "/api/events":
            return (200, {"events": app.store.events(customer)})
        m = re.fullmatch(r"/api/orders/([A-Z]{1,6}-[0-9]{1,8})", path)
        if m:
            return (200, {"order": app.store.lookup(customer, m[1])})
        if path == "/api/staff/escalations":
            return (200, {"escalations": app.store.escalations()})
        m_trans = re.fullmatch(r"/api/(?:staff/)?conversations/([a-f0-9-]{36})/messages", path)
        if m_trans:
            return (200, app.store.conversation_transcript(m_trans[1]))
    if method == "POST":
        if path == '/api/conversations':
            return (201, app.new_conversation(customer, body))
        focus = re.fullmatch(r'/api/conversations/([a-f0-9-]{36})/focus', path)
        if focus:
            return (200, app.focus(customer, focus[1], body))
        if path == "/api/chat":
            try:
                result = app.chat(customer, body)
            except ApiError as exc:
                _record_chat_usage(app, customer, body, {'trace': exc.trace}, False)
                raise
            _record_chat_usage(app, customer, body, result, True)
            return (200, result)
        if path == "/api/feedback":
            res = app.store.record_feedback(customer, body)
            return (200, res)
        if path == "/api/staff/customer-message":
            require(isinstance(body, dict) and {"conversation_id", "message"}.issubset(set(body)) and set(body).issubset({"conversation_id", "message"}), 400, "invalid_fields", "Các trường của yêu cầu không hợp lệ.")
            cid, msg = body["conversation_id"], body["message"]
            res = app.store.customer_message(customer, cid, msg)
            return (200, res)
        if path == "/api/staff/reply":
            require(isinstance(body, dict) and {"conversation_id", "message"}.issubset(set(body)) and set(body).issubset({"conversation_id", "message", "staff_name"}), 400, "invalid_fields", "Các trường của yêu cầu không hợp lệ.")
            cid, msg = body["conversation_id"], body["message"]
            staff_name = body.get("staff_name", "Mai Anh (Chuyên viên CSKH)")
            with app.store.connection() as db:
                row = db.execute("SELECT customer_id FROM conversations WHERE id=?", (cid,)).fetchone()
            require(row is not None, 404, "conversation_not_found", "Không tìm thấy cuộc trò chuyện.")
            res = app.store.staff_reply(row["customer_id"], cid, staff_name, msg)
            return (200, res)
        if path == "/api/staff/resolve":
            require(isinstance(body, dict) and {"conversation_id"}.issubset(set(body)) and set(body).issubset({"conversation_id", "staff_name"}), 400, "invalid_fields", "Các trường của yêu cầu không hợp lệ.")
            cid = body["conversation_id"]
            staff_name = body.get("staff_name", "Mai Anh (Chuyên viên CSKH)")
            res = app.store.resolve_escalation(cid, staff_name)
            return (200, res)
        if path == "/api/cancellation-proposals":
            app.require_permission(CANCEL)
            result = app.store.propose(customer, body)
            approval.drive(app, customer, result['proposal_id'])
            return (201, {**result, 'workflow_status': 'awaiting_confirmation'})
        if path == "/api/tools/execute":
            fields(body, {'tool_name', 'arguments'})
            from agent_protocol import validate_tool
            from retailops_tools import BoundTools
            tool_name, arguments = body['tool_name'], body['arguments']
            validate_tool(tool_name, arguments)
            snapshot = {'order_id': None, 'product_id': None}
            bound = BoundTools(app.store, app.catalog, customer, snapshot, {'name': 'inspector', 'provider': 'inspector'})
            res = bound(tool_name, arguments)
            return (200, {'tool_name': tool_name, 'arguments': arguments, 'result': res})
        if path in ("/api/manager/products", "/api/manager/products/create"):
            require(isinstance(body, dict), 400, "invalid_body", "Dữ liệu sản phẩm không hợp lệ.")
            pid = str(body.get("id", "")).strip().upper()
            name = str(body.get("name", "")).strip()
            require(pid and re.fullmatch(r"P-[0-9]{3,6}", pid), 400, "invalid_product_id", "Mã sản phẩm phải có dạng P-xxx (ví dụ: P-509).")
            require(name, 400, "invalid_product_name", "Tên sản phẩm không được để trống.")
            if pid in app.catalog.products:
                raise ApiError(409, "product_exists", f"Sản phẩm {pid} đã tồn tại trong danh mục.")
            price = int(body.get("price", 299000))
            category = str(body.get("category", "Thời trang")).strip()
            desc = str(body.get("description", f"Sản phẩm {name} chất lượng cao từ RetailOps.")).strip()
            variants = body.get("variants", ["Tiêu chuẩn"])
            if isinstance(variants, str):
                variants = [v.strip() for v in variants.split(",") if v.strip()]
            stock = body.get("stock", 25)
            warranty_days = int(body.get("warranty_days", 30))
            aliases = body.get("aliases", [name.lower(), pid.lower()])
            product = {
                "id": pid, "name": name, "aliases": aliases, "category": category,
                "description": desc, "variants": variants, "price": price,
                "stock": stock, "warranty_days": warranty_days, "material": body.get("material", "Vải cao cấp"),
                "care": body.get("care", "Giặt máy nhẹ"), "is_system_immutable": False
            }
            app.catalog.add_product(product)
            return (201, {"status": "ok", "product": product, "message": f"Đã thêm sản phẩm {name} ({pid}) vào catalog."})
        if path == "/api/manager/products/update":
            require(isinstance(body, dict) and "id" in body, 400, "invalid_body", "Thiếu mã sản phẩm.")
            pid = str(body["id"]).strip().upper()
            if pid not in app.catalog.products:
                raise ApiError(404, "product_not_found", f"Không tìm thấy sản phẩm {pid}.")
            updates = {}
            for k in ("name", "category", "description", "price", "stock", "warranty_days", "variants", "material", "care"):
                if k in body:
                    updates[k] = body[k]
            product = app.catalog.update_product(pid, updates)
            return (200, {"status": "ok", "product": product, "message": f"Đã cập nhật sản phẩm {pid}."})
        if path == "/api/manager/products/delete":
            require(isinstance(body, dict) and "id" in body, 400, "invalid_body", "Thiếu mã sản phẩm.")
            pid = str(body["id"]).strip().upper()
            try:
                removed = app.catalog.delete_product(pid)
            except ValueError as exc:
                raise ApiError(400, "system_product_immutable", str(exc))
            except KeyError as exc:
                raise ApiError(404, "product_not_found", str(exc))
            return (200, {"status": "ok", "removed": removed, "message": f"Đã xóa sản phẩm {pid}."})
        if path == "/api/manager/orders/update-status":
            require(isinstance(body, dict) and {"order_id", "status"}.issubset(set(body)), 400, "invalid_body", "Thiếu order_id hoặc status.")
            oid, new_status = body["order_id"], body["status"]
            require(new_status in ('pending', 'delivered', 'cancelled'), 400, "invalid_status", "Trạng thái phải là pending, delivered hoặc cancelled.")
            with app.store.connection(write=True) as db:
                row = db.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
                require(row is not None, 404, "order_not_found", f"Không tìm thấy đơn hàng {oid}.")
                db.execute("UPDATE orders SET status=?, version=version+1 WHERE id=?", (new_status, oid))
                app.store.log(db, row["customer_id"], "order_status_updated_by_manager", oid, new_status=new_status)
            return (200, {"status": "ok", "order_id": oid, "new_status": new_status, "message": f"Đã cập nhật trạng thái đơn {oid} sang {new_status}."})
        m = re.fullmatch(r"/api/cancellation-proposals/([a-f0-9-]{36})/(confirm|dismiss)", path)
        if m:
            app.require_permission(CANCEL)
            if m[2] == "confirm":
                return (200, approval.confirm(app, customer, m[1], body, idempotency_key))
            fields(body, set())
            return (200, approval.dismiss(app, customer, m[1]))
    raise ApiError(404, "not_found", "Không tìm thấy đường dẫn.")
