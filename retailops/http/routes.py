"""Business route dispatch for both HTTP adapters; identity comes from the server."""
import re
import time
from retailops.workflow import approval
from retailops.core import ApiError, fields
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
            return (200, {"orders": app.store.orders(customer)})
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
        if path == "/api/cancellation-proposals":
            app.require_permission(CANCEL)
            result = app.store.propose(customer, body)
            approval.drive(app, customer, result['proposal_id'])
            return (201, {**result, 'workflow_status': 'awaiting_confirmation'})
        m = re.fullmatch(r"/api/cancellation-proposals/([a-f0-9-]{36})/(confirm|dismiss)", path)
        if m:
            app.require_permission(CANCEL)
            if m[2] == "confirm":
                return (200, approval.confirm(app, customer, m[1], body, idempotency_key))
            fields(body, set())
            return (200, approval.dismiss(app, customer, m[1]))
    raise ApiError(404, "not_found", "Không tìm thấy đường dẫn.")
