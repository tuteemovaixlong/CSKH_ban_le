"""Business route dispatch for both HTTP adapters; identity comes from the server."""
import json
import math
from pathlib import Path
import re
import time
import urllib.parse
from retailops.core import ApiError, fields, require
from retailops.workflow import approval
from retailops.business.permissions import ACTIVE_BUSINESS_ROLES, READ, CANCEL, STAFF, MANAGER
from retailops.identity.contracts import RequestContext

CUSTOMER_SAFE_EVENT_KINDS = frozenset({
    'order_viewed',
    'cancellation_proposed',
    'order_cancelled',
    'proposal_dismissed',
    'order_status_updated_by_manager',
    'customer_messaged_staff',
    'staff_replied',
    'escalation_resolved',
    'feedback_received',
    'agent_replied',
})

ALLOWED_DIRECT_TOOLS = frozenset({
    'get_context',
    'get_order',
    'track_shipment',
    'get_product',
    'check_variant_stock',
    'search_products',
    'search_knowledge',
})


def _admin_control(app):
    control = getattr(app, 'identity_store', None) or getattr(getattr(app, 'quota_store', None), 'control', None)
    if control is None or not hasattr(control, 'admin_list_accounts'):
        raise ApiError(404, 'admin_governance_unavailable', 'Quản trị tài khoản chỉ có trên phiên đăng nhập persistent.')
    return control


def _format_order_for_api(order, app=None):
    if not isinstance(order, dict):
        return order
    out = dict(order)
    data_mode = getattr(app, 'data_mode', 'synthetic-demo') if app is not None else 'synthetic-demo'
    store = getattr(app, 'store', None) if app is not None else None
    is_demo_fixture = (
        callable(getattr(store, 'is_demo_sample_order', None))
        and store.is_demo_sample_order(out.get('customer_id'), out.get('id'))
    )
    if (
        data_mode in ('synthetic-demo', 'persistent-demo')
        and is_demo_fixture
        and out.get('product_id') == 'P-602'
        and out.get('name') == 'Quần tây đen hàn quốc'
        and out.get('variant') == 'Đen / L'
        and out.get('amount') == 520000
        and isinstance(out.get('id'), str)
        and re.fullmatch(r'O-[78]\d{5}', out['id'])
    ):
        out['display_name'] = 'Bộ xếp hình gỗ cho bé'
    return out


def _parse_query_dict(query_str, allowed_keys):
    if not query_str:
        return {}
    parsed = urllib.parse.parse_qs(query_str, keep_blank_values=True)
    require(set(parsed).issubset(set(allowed_keys)), 400, 'invalid_query_params', 'Tham số truy vấn không hợp lệ.')
    return {k: (v[-1] if v else '') for k, v in parsed.items()}


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


def _parse_price(val):
    if val is None or isinstance(val, bool):
        return False, None
    if isinstance(val, (int, float)):
        if not math.isfinite(val) or val < 0:
            return False, None
        try:
            return True, int(val)
        except (ValueError, OverflowError):
            return False, None
    if isinstance(val, str):
        v = val.strip()
        if not v.isdigit():
            return False, None
        try:
            num = int(v)
            if num < 0:
                return False, None
            return True, num
        except (ValueError, OverflowError):
            return False, None
    return False, None


def _parse_non_negative_int(val):
    if val is None or isinstance(val, bool):
        return False, None
    if isinstance(val, (int, float)):
        if not math.isfinite(val) or val < 0 or int(val) != val:
            return False, None
        try:
            return True, int(val)
        except (ValueError, OverflowError):
            return False, None
    if isinstance(val, str):
        v = val.strip()
        if not v.isdigit():
            return False, None
        try:
            num = int(v)
            if num < 0:
                return False, None
            return True, num
        except (ValueError, OverflowError):
            return False, None
    return False, None


def _resolve_request_context(app, customer, binding=None, context=None) -> RequestContext:
    if isinstance(context, RequestContext):
        return context
    if binding is not None:
        return RequestContext.from_binding(
            binding,
            data_mode=getattr(app, 'data_mode', 'synthetic-demo'),
        )
    return RequestContext.from_app(
        app,
        customer,
        data_mode=getattr(app, 'data_mode', 'synthetic-demo'),
        authenticated_session=False,
    )


def _require_ctx_permission(ctx: RequestContext, permission: str) -> None:
    require(
        ctx.role in ACTIVE_BUSINESS_ROLES and permission in ctx.permissions,
        403,
        'permission_denied',
        'Tài khoản này không có quyền thực hiện thao tác.',
    )


def _actor_display_name(ctx: RequestContext) -> str:
    clean = (ctx.display_name or '').strip()
    if clean:
        return clean
    return 'Quản lý cửa hàng' if ctx.role == 'manager' else 'Nhân viên hỗ trợ'


def _check_staff_tenant_scope(app, ctx: RequestContext) -> None:
    app_tid = getattr(app, 'tenant_id', None)
    if app_tid and app_tid != 'default' and ctx.tenant_id and ctx.tenant_id != 'default':
        require(
            ctx.tenant_id == app_tid,
            403,
            'tenant_scope_denied',
            'Ngữ cảnh cửa hàng không khớp với phiên làm việc.',
        )


def _authorize_staff_transcript_view(app, ctx: RequestContext, actor: dict, *, cid: str | None = None, case_id: str | None = None):
    _check_staff_tenant_scope(app, ctx)
    now = app.store._now() if hasattr(app.store, '_now') else time.time()
    with app.store.connection() as db:
        if case_id is not None:
            case_row = db.execute('SELECT * FROM cases WHERE case_id = ?', (case_id,)).fetchone()
            require(case_row is not None, 404, 'case_not_found', 'Không tìm thấy ca hỗ trợ.')
            cid = case_row['conversation_id']
            conv = db.execute(
                'SELECT id, customer_id, order_id, product_id, expires_at FROM conversations WHERE id=?',
                (cid,),
            ).fetchone()
        else:
            conv = db.execute(
                'SELECT id, customer_id, order_id, product_id, expires_at FROM conversations WHERE id=?',
                (cid,),
            ).fetchone()
            case_row = app.store._latest_case_in_tx(db, cid) if hasattr(app.store, '_latest_case_in_tx') else None
            require(conv is not None or case_row is not None, 404, 'conversation_not_found', 'Không tìm thấy cuộc trò chuyện.')
        open_ep = (
            db.execute(
                "SELECT handoff_id FROM handoff_episodes WHERE case_id = ? AND status = 'pending' LIMIT 1",
                (case_row['case_id'],),
            ).fetchone()
            if case_row is not None
            else None
        )

    if (
        case_row is not None
        and case_row['status'] in ('waiting', 'in_progress')
        and (open_ep is not None or case_row['holder'] is not None)
    ):
        return cid, case_row['case_id'], False

    if case_row is not None and case_row['status'] == 'resolved':
        within_retention = (
            conv is not None
            and float(conv['expires_at']) > now
            and (case_row['resolved_at'] is None or (now - float(case_row['resolved_at'])) <= app.store.CONVERSATION_TTL)
        )
        require(
            within_retention,
            403,
            'case_retention_expired',
            'Ca hỗ trợ đã đóng và quá thời hạn lưu trữ để xem lại.',
        )
        app.store.event(
            case_row['customer_id'],
            'resolved_case_viewed',
            conv['order_id'] if conv is not None else None,
            case_id=case_row['case_id'],
            conversation_id=cid,
            actor=actor,
        )
        return cid, case_row['case_id'], True

    raise ApiError(
        403,
        'case_not_escalated',
        'Cuộc trò chuyện này hiện không có yêu cầu chuyển tiếp nhân viên đang mở.',
    )


def _sanitize_customer_events(events):
    stripped_keys = {'actor', 'actor_principal_id', 'actor_membership_id', 'actor_role', 'tenant_id', 'trace'}
    safe = []
    for ev in events:
        if not isinstance(ev, dict) or ev.get('kind') not in CUSTOMER_SAFE_EVENT_KINDS:
            continue
        item = dict(ev)
        payload = item.get('payload')
        if isinstance(payload, dict):
            item['payload'] = {k: v for k, v in payload.items() if k not in stripped_keys}
        safe.append(item)
    return safe


def _extract_actor(app, customer, binding=None, context=None):
    ctx = _resolve_request_context(app, customer, binding=binding, context=context)
    principal_id = ctx.principal_id
    membership_id = ctx.membership_id
    tenant_id = ctx.tenant_id
    if not ctx.authenticated_session:
        if not membership_id:
            membership_id = getattr(getattr(app, 'quota_store', None), 'membership_id', None)
        if not principal_id:
            principal_id = getattr(app, 'principal_id', None) or (
                'manager' if ctx.role == 'manager' else ctx.customer_id
            )
    return {
        "principal_id": principal_id,
        "role": ctx.role,
        "tenant_id": tenant_id,
        "customer_id": ctx.customer_id,
        "membership_id": membership_id,
        "display_name": ctx.display_name,
        "actor_type": "principal",
    }


def api_result(app, customer, method, path, body=None, idempotency_key=None, binding=None, query=None, context=None):
    if isinstance(path, str) and '?' in path and not query:
        path, query = path.split('?', 1)
    ctx = _resolve_request_context(app, customer, binding=binding, context=context)
    customer = ctx.customer_id
    if not (isinstance(path, str) and path.startswith('/api/admin/')):
        _require_ctx_permission(ctx, READ)
    if method == "GET":
        if path in ("/api/session", "/api/profile"):
            if ctx.principal_id is not None:
                display_name = (ctx.display_name or "").strip()
            else:
                display_name = ctx.display_name or ("Mai Anh" if customer == "C-001" else "Khách mẫu")
            res = {
                "customer_id": customer,
                "name": display_name,
                "model_configured": app.infer is not None or app.api_infer is not None,
                "permissions": sorted(ctx.permissions),
                "role": ctx.role,
                "scope": "synthetic-demo",
            }
            if ctx.tenant_id is not None:
                res["tenant_id"] = ctx.tenant_id
            if ctx.principal_id is not None:
                res["principal_id"] = ctx.principal_id
            return (200, res)
        if path == '/api/account/usage':
            return (200, _account_usage(app))
        if path == '/api/admin/accounts':
            control = _admin_control(app)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            qparams = _parse_query_dict(query, {'tenant_id', 'q', 'limit'})
            lim = 50
            if 'limit' in qparams and qparams['limit'] != '':
                ok_lim, lim_val = _parse_non_negative_int(qparams['limit'])
                require(ok_lim and 1 <= lim_val <= 200, 400, 'invalid_limit', 'Giới hạn danh sách không hợp lệ.')
                lim = lim_val
            return (200, control.admin_list_accounts(
                actor,
                tenant_id=qparams.get('tenant_id'),
                query=qparams.get('q'),
                limit=lim,
                default_limit=app.api_daily_limit,
                correlation_id=idempotency_key,
            ))
        m_admin_acct = re.fullmatch(r'/api/admin/accounts/([A-Za-z0-9_-]{1,64})', path)
        if m_admin_acct:
            control = _admin_control(app)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            qparams = _parse_query_dict(query, {'tenant_id'})
            return (200, control.admin_get_account(
                actor,
                m_admin_acct[1],
                tenant_id=qparams.get('tenant_id'),
                default_limit=app.api_daily_limit,
                correlation_id=idempotency_key,
            ))
        if path == '/api/admin/audit-log':
            control = _admin_control(app)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            qparams = _parse_query_dict(query, {'tenant_id', 'membership_id', 'limit'})
            lim = 100
            if 'limit' in qparams and qparams['limit'] != '':
                ok_lim, lim_val = _parse_non_negative_int(qparams['limit'])
                require(ok_lim and 1 <= lim_val <= 500, 400, 'invalid_limit', 'Giới hạn truy vấn audit không hợp lệ.')
                lim = lim_val
            return (200, control.admin_list_audit_logs(
                actor,
                tenant_id=qparams.get('tenant_id'),
                target_membership_id=qparams.get('membership_id'),
                limit=lim,
                correlation_id=idempotency_key,
            ))
        if path == "/api/providers":
            return (200, app.providers())
        if path == "/api/orders":
            if ctx.role == 'manager':
                with app.store.connection() as db:
                    all_orders = [_format_order_for_api(dict(r), app) for r in db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 50")]
                return (200, {"orders": all_orders, "scope": "store_all"})
            return (200, {"orders": [_format_order_for_api(o, app) for o in app.store.orders(customer)], "scope": "customer"})
        if path == "/api/manager/products":
            _require_ctx_permission(ctx, MANAGER)
            prods = app.catalog.all_products()
            return (200, {"products": prods, "count": len(prods)})
        if path == "/api/manager/kpis":
            _require_ctx_permission(ctx, MANAGER)
            with app.store.connection() as db:
                rows = [dict(r) for r in db.execute("SELECT status, amount FROM orders").fetchall()]
                try:
                    fb_rows = [dict(r) for r in db.execute("SELECT feedback_type, rating FROM conversation_feedback").fetchall()]
                    csat_ratings = [r['rating'] for r in fb_rows if r['feedback_type'] == 'session_csat' and r.get('rating') is not None]
                    avg_csat = round(sum(csat_ratings) / len(csat_ratings), 1) if csat_ratings else None
                    csat_sample_size = len(csat_ratings)
                    esc_row = db.execute("SELECT COUNT(DISTINCT conversation_id) AS cnt FROM conversation_feedback WHERE feedback_type = 'human_handoff'").fetchone()
                    if esc_row:
                        try:
                            esc_count = esc_row["cnt"] if "cnt" in esc_row else esc_row[0]
                        except (TypeError, KeyError, IndexError):
                            esc_count = esc_row[0] if esc_row else 0
                    else:
                        esc_count = 0
                    conv_row = db.execute("SELECT COUNT(*) AS cnt FROM conversations").fetchone()
                    if conv_row:
                        try:
                            total_convs = conv_row["cnt"] if "cnt" in conv_row else conv_row[0]
                        except (TypeError, KeyError, IndexError):
                            total_convs = conv_row[0] if conv_row else 0
                    else:
                        total_convs = 0
                    if total_convs > 0:
                        escalation_rate = round((esc_count / total_convs) * 100, 1)
                        ai_resolution_rate = round(100.0 - escalation_rate, 1)
                    else:
                        escalation_rate = None
                        ai_resolution_rate = None
                except Exception:
                    avg_csat, csat_sample_size, escalation_rate, ai_resolution_rate = None, 0, None, None
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
                "ai_resolution_rate": ai_resolution_rate,
                "escalation_rate": escalation_rate,
                "avg_csat": avg_csat,
                "csat_sample_size": csat_sample_size,
                "active_products": len(app.catalog.products)
            })
        if path == "/api/manager/benchmark":
            _require_ctx_permission(ctx, MANAGER)
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
            _require_ctx_permission(ctx, CANCEL)
            with app.store.connection() as db:
                rows = db.execute("SELECT id FROM proposals WHERE customer_id=? AND state='pending' AND expires_at>? ORDER BY expires_at DESC LIMIT 10", (customer, time.time())).fetchall()
            return (200, {'proposals': [approval.proposal(app.store, customer, r['id']) for r in rows]})
        if path == "/api/events":
            raw_events = app.store.events(customer)
            if STAFF not in ctx.permissions:
                raw_events = _sanitize_customer_events(raw_events)
            return (200, {"events": raw_events})
        if path == "/api/manager/events":
            _require_ctx_permission(ctx, MANAGER)
            return (200, {"events": app.store.manager_events(limit=100)})
        m = re.fullmatch(r"/api/orders/([A-Z]{1,6}-[0-9]{1,8})", path)
        if m:
            return (200, {"order": _format_order_for_api(app.store.lookup(customer, m[1]), app)})
        if path == "/api/staff/cases":
            _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            return (200, app.store.staff_desk_cases())
        if path == "/api/staff/escalations":
            _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            desk = app.store.staff_desk_cases()
            return (200, {"escalations": app.store.escalations(), **desk})
        if path == "/api/conversations":
            return (200, {"conversations": app.store.list_conversations(customer)})
        m_case_trans = re.fullmatch(r"/api/staff/cases/([A-Za-z0-9_-]{1,80})/messages", path)
        if m_case_trans:
            _require_ctx_permission(ctx, STAFF)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            cid, resolved_case_id, ro = _authorize_staff_transcript_view(
                app, ctx, actor, case_id=m_case_trans[1]
            )
            return (200, app.store.conversation_transcript(cid, case_id=resolved_case_id, read_only=ro))
        m_trans = re.fullmatch(r"/api/(?:staff/)?conversations/([a-f0-9-]{36})/messages", path)
        if m_trans:
            cid = m_trans[1]
            if STAFF not in ctx.permissions:
                with app.store.connection() as db:
                    row = db.execute("SELECT customer_id FROM conversations WHERE id=?", (cid,)).fetchone()
                require(row is not None and row["customer_id"] == customer, 403, "permission_denied", "Tài khoản này không có quyền thực hiện thao tác.")
                return (200, app.store.conversation_transcript(cid))
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            cid, resolved_case_id, ro = _authorize_staff_transcript_view(app, ctx, actor, cid=cid)
            return (200, app.store.conversation_transcript(cid, case_id=resolved_case_id, read_only=ro))
    if method == "POST":
        if path == '/api/conversations':
            return (201, app.new_conversation(customer, body))
        focus = re.fullmatch(r'/api/conversations/([a-f0-9-]{36})/focus', path)
        if focus:
            res = app.focus(customer, focus[1], body)
            if isinstance(res, dict) and 'order' in res:
                res = {**res, 'order': _format_order_for_api(res['order'], app)}
            return (200, res)
        m_resume = re.fullmatch(r'/api/conversations/([a-f0-9-]{36})/resume', path)
        if m_resume:
            require(body is None or (isinstance(body, dict) and set(body) == set()), 400, 'invalid_fields', 'Các trường của yêu cầu không hợp lệ.')
            return (200, app.store.resume_case(customer, m_resume[1]))
        if path.startswith('/api/admin/audit-log'):
            raise ApiError(405, 'audit_log_append_only', 'Nhật ký audit quản trị là chỉ-ghi-thêm (append-only); không hỗ trợ sửa hoặc xóa.')
        m_admin_act = re.fullmatch(r'/api/admin/accounts/([A-Za-z0-9_-]{1,64})/(suspend|reactivate|revoke-sessions|quota)', path)
        if m_admin_act:
            control = _admin_control(app)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            mid, act_kind = m_admin_act[1], m_admin_act[2]
            corr_id = (body.get('correlation_id') if isinstance(body, dict) else None) or idempotency_key
            raw_reason = (body.get('reason') if isinstance(body, dict) else None) or act_kind
            qparams = _parse_query_dict(query, {'tenant_id'}) if query else {}
            expected_tid = (body.get('tenant_id') if isinstance(body, dict) else None) or qparams.get('tenant_id')
            # Enforce permission/scope check before field validation so spoofed/unauthorized attempts always log 'denied' and return 403/409
            control._load_target_for_admin_mutation(
                actor, mid,
                'set_quota_override' if act_kind == 'quota' else (
                    'revoke_sessions' if act_kind == 'revoke-sessions' else f'{act_kind}_account'
                ),
                str(raw_reason),
                correlation_id=corr_id,
                expected_tenant_id=expected_tid,
            )
            require(isinstance(body, dict), 400, 'invalid_body', 'Yêu cầu phải là đối tượng JSON.')
            if act_kind in ('suspend', 'reactivate', 'revoke-sessions'):
                require(
                    {'reason'}.issubset(set(body)) and set(body).issubset({'reason', 'correlation_id', 'tenant_id'}),
                    400,
                    'invalid_fields',
                    'Các trường của yêu cầu quản trị không hợp lệ.',
                )
                if act_kind == 'suspend':
                    return (200, control.admin_suspend_account(
                        actor, mid, reason=body['reason'], correlation_id=corr_id, default_limit=app.api_daily_limit, expected_tenant_id=expected_tid
                    ))
                if act_kind == 'reactivate':
                    return (200, control.admin_reactivate_account(
                        actor, mid, reason=body['reason'], correlation_id=corr_id, default_limit=app.api_daily_limit, expected_tenant_id=expected_tid
                    ))
                return (200, control.admin_revoke_sessions(
                    actor, mid, reason=body['reason'], correlation_id=corr_id, default_limit=app.api_daily_limit, expected_tenant_id=expected_tid
                ))
            require(
                {'daily_limit', 'reason'}.issubset(set(body))
                and set(body).issubset({'daily_limit', 'reason', 'expires_at', 'effective_at', 'correlation_id', 'tenant_id'}),
                400,
                'invalid_fields',
                'Các trường cập nhật hạn mức không hợp lệ.',
            )
            return (200, control.admin_set_quota_override(
                actor,
                mid,
                daily_limit=body['daily_limit'],
                reason=body['reason'],
                expires_at=body.get('expires_at'),
                effective_at=body.get('effective_at'),
                correlation_id=corr_id,
                default_limit=app.api_daily_limit,
                expected_tenant_id=expected_tid,
            ))
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
        m_case_act = re.fullmatch(r"/api/staff/cases/([A-Za-z0-9_-]{1,80})/(claim|release)", path)
        if m_case_act:
            _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            require(
                body is None or (isinstance(body, dict) and set(body).issubset({"version"})),
                400,
                "invalid_fields",
                "Các trường của yêu cầu không hợp lệ.",
            )
            exp_ver = body.get("version") if isinstance(body, dict) else None
            if exp_ver is not None:
                require(type(exp_ver) is int and exp_ver >= 1, 400, "invalid_version", "Phiên bản ca không hợp lệ.")
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            staff_label = _actor_display_name(ctx)
            if m_case_act[2] == "claim":
                return (200, app.store.claim_case(m_case_act[1], staff_name=staff_label, actor=actor, expected_version=exp_ver))
            return (200, app.store.release_case(m_case_act[1], staff_name=staff_label, actor=actor, expected_version=exp_ver))
        if path in ("/api/staff/claim", "/api/staff/release"):
            _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            require(
                isinstance(body, dict)
                and {"case_id"}.issubset(set(body))
                and set(body).issubset({"case_id", "version"}),
                400,
                "invalid_fields",
                "Các trường của yêu cầu không hợp lệ.",
            )
            exp_ver = body.get("version")
            if exp_ver is not None:
                require(type(exp_ver) is int and exp_ver >= 1, 400, "invalid_version", "Phiên bản ca không hợp lệ.")
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            staff_label = _actor_display_name(ctx)
            if path == "/api/staff/claim":
                return (200, app.store.claim_case(body["case_id"], staff_name=staff_label, actor=actor, expected_version=exp_ver))
            return (200, app.store.release_case(body["case_id"], staff_name=staff_label, actor=actor, expected_version=exp_ver))
        if path == "/api/staff/reply":
            _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            require(
                isinstance(body, dict)
                and "message" in body
                and ("conversation_id" in body or "case_id" in body)
                and set(body).issubset({"conversation_id", "case_id", "message", "staff_name"}),
                400,
                "invalid_fields",
                "Các trường của yêu cầu không hợp lệ.",
            )
            cid = body.get("conversation_id")
            case_id = body.get("case_id")
            msg = body["message"]
            if cid is not None:
                require(isinstance(cid, str) and bool(re.fullmatch(r"[a-f0-9-]{36}", cid)), 400, "invalid_conversation", "Mã cuộc trò chuyện không hợp lệ.")
            if case_id is not None:
                require(isinstance(case_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", case_id)), 400, "invalid_case_id", "Mã ca hỗ trợ không hợp lệ.")
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            staff_label = _actor_display_name(ctx)
            res = app.store.staff_reply(None, cid, staff_label, msg, actor=actor, case_id=case_id)
            return (200, res)
        if path == "/api/staff/resolve":
            _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            require(
                isinstance(body, dict)
                and ("conversation_id" in body or "case_id" in body or "handoff_id" in body)
                and set(body).issubset({"conversation_id", "case_id", "handoff_id", "staff_name"}),
                400,
                "invalid_fields",
                "Các trường của yêu cầu không hợp lệ.",
            )
            cid = body.get("conversation_id")
            case_id = body.get("case_id")
            handoff_id = body.get("handoff_id")
            if cid is not None:
                require(isinstance(cid, str) and bool(re.fullmatch(r"[a-f0-9-]{36}", cid)), 400, "invalid_conversation", "Mã cuộc trò chuyện không hợp lệ.")
            if case_id is not None:
                require(isinstance(case_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", case_id)), 400, "invalid_case_id", "Mã ca hỗ trợ không hợp lệ.")
            if handoff_id is not None:
                require(isinstance(handoff_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", handoff_id)), 400, "invalid_handoff_id", "Mã phiên chuyển tiếp không hợp lệ.")
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            staff_label = _actor_display_name(ctx)
            res = app.store.resolve_escalation(cid, staff_label, actor=actor, case_id=case_id, handoff_id=handoff_id)
            return (200, res)
        if path == "/api/cancellation-proposals":
            _require_ctx_permission(ctx, CANCEL)
            result = app.store.propose(customer, body)
            approval.drive(app, customer, result['proposal_id'])
            return (201, {**result, 'workflow_status': 'awaiting_confirmation'})
        if path == "/api/tools/execute":
            _require_ctx_permission(ctx, STAFF)
            has_session_binding = (
                (context is not None or binding is not None)
                and bool(ctx.principal_id)
                and bool(ctx.tenant_id)
                and ctx.tenant_id != 'default'
            )
            require(
                has_session_binding,
                403,
                'missing_session_binding',
                'Đường gọi công cụ trực tiếp yêu cầu phiên xác thực gắn với người thực hiện và cửa hàng.',
            )
            app_tid = getattr(app, 'tenant_id', None)
            if app_tid and app_tid != 'default':
                require(
                    ctx.tenant_id == app_tid,
                    403,
                    'tenant_scope_denied',
                    'Ngữ cảnh cửa hàng không khớp với phiên làm việc.',
                )
            require(
                isinstance(body, dict)
                and {'tool_name', 'arguments'}.issubset(set(body))
                and ('conversation_id' in body or 'case_id' in body)
                and set(body).issubset({'tool_name', 'arguments', 'conversation_id', 'case_id'}),
                403,
                'missing_object_binding',
                'Đường gọi công cụ trực tiếp yêu cầu gắn với cuộc trò chuyện/ca hỗ trợ cụ thể.',
            )
            cid = body.get('conversation_id')
            tool_case_id = body.get('case_id')
            if cid is not None:
                require(
                    isinstance(cid, str) and bool(re.fullmatch(r'[a-f0-9-]{36}', cid)),
                    400,
                    'invalid_conversation',
                    'Mã cuộc trò chuyện không hợp lệ.',
                )
            if tool_case_id is not None:
                require(
                    isinstance(tool_case_id, str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,80}', tool_case_id)),
                    400,
                    'invalid_case_id',
                    'Mã ca hỗ trợ không hợp lệ.',
                )
            from agent_protocol import validate_tool
            from retailops_tools import BoundTools
            tool_name, arguments = body['tool_name'], body['arguments']
            require(
                isinstance(tool_name, str) and tool_name in ALLOWED_DIRECT_TOOLS,
                403,
                'tool_not_allowed',
                'Công cụ này không được phép gọi trực tiếp qua đường vận hành.',
            )
            validate_tool(tool_name, arguments)
            with app.store.connection() as db:
                if tool_case_id is not None:
                    case_row = db.execute('SELECT * FROM cases WHERE case_id = ?', (tool_case_id,)).fetchone()
                    require(case_row is not None, 404, 'case_not_found', 'Không tìm thấy ca hỗ trợ trong cửa hàng hiện tại.')
                    if cid is not None:
                        require(case_row['conversation_id'] == cid, 409, 'case_conversation_mismatch', 'Mã ca không khớp với cuộc trò chuyện.')
                    cid = case_row['conversation_id']
                else:
                    case_row = app.store._latest_case_in_tx(db, cid) if hasattr(app.store, '_latest_case_in_tx') else None
                conv = db.execute(
                    'SELECT id, customer_id, order_id, product_id, expires_at FROM conversations WHERE id=?',
                    (cid,),
                ).fetchone()
                require(conv is not None, 404, 'conversation_not_found', 'Không tìm thấy cuộc trò chuyện trong cửa hàng hiện tại.')
                open_ep = (
                    db.execute(
                        "SELECT handoff_id FROM handoff_episodes WHERE case_id = ? AND status = 'pending' LIMIT 1",
                        (case_row['case_id'],),
                    ).fetchone()
                    if case_row is not None and case_row['status'] in ('waiting', 'in_progress')
                    else None
                )
                require(
                    open_ep is not None,
                    403,
                    'case_not_escalated',
                    'Chỉ được tra cứu công cụ trực tiếp trên ca hỗ trợ đang có yêu cầu chuyển tiếp chưa đóng.',
                )
                if isinstance(arguments, dict) and arguments.get('order_id'):
                    ord_row = db.execute(
                        'SELECT customer_id FROM orders WHERE id=?',
                        (arguments['order_id'],),
                    ).fetchone()
                    require(
                        ord_row is not None and ord_row['customer_id'] == conv['customer_id'],
                        403,
                        'object_scope_denied',
                        'Đơn hàng không thuộc khách hàng của ca hỗ trợ đang gắn kết.',
                    )
            snapshot = {'order_id': conv['order_id'], 'product_id': conv['product_id']}
            bound = BoundTools(
                app.store,
                app.catalog,
                conv['customer_id'],
                snapshot,
                {'name': 'inspector', 'provider': 'inspector'},
                can_cancel=False,
                read_only=True,
            )
            res = bound(tool_name, arguments)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            app.store.event(
                conv['customer_id'],
                'staff_tool_executed',
                conv['order_id'],
                tool_name=tool_name,
                conversation_id=cid,
                actor=actor,
            )
            return (200, {'tool_name': tool_name, 'arguments': arguments, 'conversation_id': cid, 'result': res})
        if path in ("/api/manager/products", "/api/manager/products/create"):
            _require_ctx_permission(ctx, MANAGER)
            require(isinstance(body, dict), 400, "invalid_body", "Dữ liệu sản phẩm không hợp lệ.")
            pid = str(body.get("id", "")).strip().upper()
            name = str(body.get("name", "")).strip()
            require(pid and re.fullmatch(r"P-[0-9]{3,6}", pid), 400, "invalid_product_id", "Mã sản phẩm phải có dạng P-xxx (ví dụ: P-509).")
            require(name, 400, "invalid_product_name", "Tên sản phẩm không được để trống.")
            if pid in app.catalog.products:
                raise ApiError(409, "product_exists", f"Sản phẩm {pid} đã tồn tại trong danh mục.")
            require("price" in body, 400, "invalid_price", "Thiếu giá sản phẩm.")
            valid_price, price = _parse_price(body["price"])
            require(valid_price, 400, "invalid_price", "Giá sản phẩm phải là số không âm.")
            category = str(body["category"]).strip() if body.get("category") else None
            description = str(body["description"]).strip() if body.get("description") else None
            raw_variants = body.get("variants")
            if isinstance(raw_variants, str):
                variants = [v.strip() for v in raw_variants.split(",") if v.strip()]
            elif isinstance(raw_variants, list):
                variants = [str(v).strip() for v in raw_variants if str(v).strip()]
            else:
                variants = []
            stock = None
            if "stock" in body and body["stock"] is not None:
                valid_stock, stock = _parse_non_negative_int(body["stock"])
                require(valid_stock, 400, "invalid_stock", "Số lượng tồn kho phải là số nguyên không âm.")
            warranty_days = None
            if "warranty_days" in body and body["warranty_days"] is not None:
                valid_w, warranty_days = _parse_non_negative_int(body["warranty_days"])
                require(valid_w, 400, "invalid_warranty_days", "Số ngày bảo hành phải là số nguyên không âm.")
            aliases = body.get("aliases", [name.lower(), pid.lower()])
            product = {
                "id": pid, "name": name, "aliases": aliases, "category": category,
                "description": description, "variants": variants, "price": price,
                "stock": stock, "warranty_days": warranty_days, "material": body.get("material"),
                "care": body.get("care"), "is_system_immutable": False
            }
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            app.catalog.add_product(product, actor=actor)
            with app.store.connection(write=True) as db:
                app.store.log(db, customer, "product_created_by_manager", pid, name=name, price=price, actor=actor)
            if hasattr(app, 'tool_cache'):
                app.tool_cache.invalidate_product(pid)
            if hasattr(app, 'semantic_cache') and app.semantic_cache:
                app.semantic_cache.clear()
            return (201, {"status": "ok", "product": product, "message": f"Đã thêm sản phẩm {name} ({pid}) vào catalog."})
        if path == "/api/manager/products/update":
            _require_ctx_permission(ctx, MANAGER)
            require(isinstance(body, dict) and "id" in body, 400, "invalid_body", "Thiếu mã sản phẩm.")
            pid = str(body["id"]).strip().upper()
            if pid not in app.catalog.products:
                raise ApiError(404, "product_not_found", f"Không tìm thấy sản phẩm {pid}.")
            updates = {}
            if "name" in body:
                n_val = str(body["name"]).strip()
                require(n_val, 400, "invalid_product_name", "Tên sản phẩm không được để trống.")
                updates["name"] = n_val
            if "price" in body:
                valid_p, price_val = _parse_price(body["price"])
                require(valid_p, 400, "invalid_price", "Giá sản phẩm phải là số không âm.")
                updates["price"] = price_val
            if "stock" in body:
                if body["stock"] is not None:
                    valid_s, stock_val = _parse_non_negative_int(body["stock"])
                    require(valid_s, 400, "invalid_stock", "Số lượng tồn kho phải là số nguyên không âm.")
                    updates["stock"] = stock_val
                else:
                    updates["stock"] = None
            if "warranty_days" in body:
                if body["warranty_days"] is not None:
                    valid_w, w_val = _parse_non_negative_int(body["warranty_days"])
                    require(valid_w, 400, "invalid_warranty_days", "Số ngày bảo hành phải là số nguyên không âm.")
                    updates["warranty_days"] = w_val
                else:
                    updates["warranty_days"] = None
            if "category" in body:
                updates["category"] = str(body["category"]).strip() if body["category"] else None
            if "description" in body:
                updates["description"] = str(body["description"]).strip() if body["description"] else None
            if "variants" in body:
                raw_vars = body["variants"]
                if isinstance(raw_vars, str):
                    updates["variants"] = [v.strip() for v in raw_vars.split(",") if v.strip()]
                elif isinstance(raw_vars, list):
                    updates["variants"] = [str(v).strip() for v in raw_vars if str(v).strip()]
                else:
                    updates["variants"] = []
            if "variant_stocks" in body and isinstance(body["variant_stocks"], dict):
                updates["variant_stocks"] = body["variant_stocks"]
            for k in ("material", "care"):
                if k in body:
                    updates[k] = body[k]
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            product = app.catalog.update_product(pid, updates, actor=actor)
            with app.store.connection(write=True) as db:
                app.store.log(db, customer, "product_updated_by_manager", pid, updates=updates, actor=actor)
            if hasattr(app, 'tool_cache'):
                app.tool_cache.invalidate_product(pid)
            if hasattr(app, 'semantic_cache') and app.semantic_cache:
                app.semantic_cache.clear()
            return (200, {"status": "ok", "product": product, "message": f"Đã cập nhật sản phẩm {pid}."})
        if path == "/api/manager/products/delete":
            _require_ctx_permission(ctx, MANAGER)
            require(isinstance(body, dict) and "id" in body, 400, "invalid_body", "Thiếu mã sản phẩm.")
            pid = str(body["id"]).strip().upper()
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            try:
                removed = app.catalog.delete_product(pid, actor=actor)
            except ValueError as exc:
                err_msg = str(exc)
                if "product_has_existing_orders" in err_msg:
                    raise ApiError(400, "product_has_existing_orders", err_msg)
                raise ApiError(400, "system_product_immutable", err_msg)
            except KeyError as exc:
                raise ApiError(404, "product_not_found", str(exc))
            with app.store.connection(write=True) as db:
                app.store.log(db, customer, "product_deleted_by_manager", pid, actor=actor)
            if hasattr(app, 'tool_cache'):
                app.tool_cache.invalidate_product(pid)
            if hasattr(app, 'semantic_cache') and app.semantic_cache:
                app.semantic_cache.clear()
            return (200, {"status": "ok", "removed": removed, "message": f"Đã xóa sản phẩm {pid}."})
        if path == "/api/manager/orders/update-status":
            _require_ctx_permission(ctx, MANAGER)
            require(isinstance(body, dict) and {"order_id", "status"}.issubset(set(body)), 400, "invalid_body", "Thiếu order_id hoặc status.")
            oid, new_status = body["order_id"], body["status"]
            require(new_status in ('pending', 'delivered', 'cancelled'), 400, "invalid_status", "Trạng thái phải là pending, delivered hoặc cancelled.")
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            with app.store.connection(write=True) as db:
                row = db.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
                require(row is not None, 404, "order_not_found", f"Không tìm thấy đơn hàng {oid}.")
                cur_status = row["status"]
                if cur_status == new_status:
                    return (200, {"status": "ok", "order_id": oid, "new_status": new_status, "message": f"Đơn hàng {oid} đã ở trạng thái {new_status}."})
                require(cur_status == 'pending', 400, "invalid_transition", f"Không thể chuyển trạng thái từ '{cur_status}' sang '{new_status}'. Đơn đã vào trạng thái kết thúc.")
                db.execute("UPDATE orders SET status=?, version=version+1 WHERE id=?", (new_status, oid))
                app.store.log(db, row["customer_id"], "order_status_updated_by_manager", oid, new_status=new_status, previous_status=cur_status, actor=actor)
            if hasattr(app, 'tool_cache'):
                tenant_id = ctx.tenant_id or getattr(app, 'tenant_id', 'default')
                app.tool_cache.invalidate(tenant_id=tenant_id, customer=row["customer_id"])
            return (200, {"status": "ok", "order_id": oid, "new_status": new_status, "message": f"Đã cập nhật trạng thái đơn {oid} sang {new_status}."})
        m = re.fullmatch(r"/api/cancellation-proposals/([a-f0-9-]{36})/(confirm|dismiss)", path)
        if m:
            _require_ctx_permission(ctx, CANCEL)
            if m[2] == "confirm":
                res = approval.confirm(app, customer, m[1], body, idempotency_key)
                if hasattr(app, 'tool_cache'):
                    tenant_id = ctx.tenant_id or getattr(app, 'tenant_id', 'default')
                    app.tool_cache.invalidate(tenant_id=tenant_id, customer=customer)
                return (200, res)
            fields(body, set())
            return (200, approval.dismiss(app, customer, m[1]))
    raise ApiError(404, "not_found", "Không tìm thấy đường dẫn.")
