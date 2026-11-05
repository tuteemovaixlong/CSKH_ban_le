"""Business route dispatch for both HTTP adapters; identity comes from the server."""
from email.parser import BytesParser
from email.policy import HTTP as EMAIL_HTTP_POLICY
import json
import math
from pathlib import Path
import re
import time
import urllib.parse
from retailops.core import ApiError, BinaryPayload, EVIDENCE_MAX_BYTES, PDF_EVIDENCE_MAX_BYTES, fields, require
from retailops.order_reasons import ACTION_TYPES, reason_catalog
from retailops.workflow import approval
from retailops.business.permissions import ACTIVE_BUSINESS_ROLES, READ, CANCEL, STAFF, MANAGER
from retailops.identity.contracts import RequestContext

EVIDENCE_UPLOAD_ROUTE_RE = re.compile(r"/api/order-actions/[A-Za-z0-9_-]{1,80}/evidence")

CUSTOMER_SAFE_EVENT_KINDS = frozenset({
    'order_viewed',
    'cancellation_proposed',
    'order_cancelled',
    'order_action_requested',
    'order_action_status_changed',
    'order_action_refund_updated',
    'order_action_evidence_uploaded',
    'chat_attachment_stored',
    'proposal_dismissed',
    'order_status_updated_by_manager',
    'customer_messaged_staff',
    'staff_replied',
    'escalation_resolved',
    'feedback_received',
    'agent_replied',
})

ALLOWED_DIRECT_TOOLS = frozenset({
    'get_order',
    'list_orders',
    'track_shipment',
    'check_inventory',
    'search_knowledge',
    'get_context',
})


def parse_evidence_request_body(
    content_type: str | None,
    content_length: str | None,
    stream,
    *,
    max_size: int = PDF_EVIDENCE_MAX_BYTES,
) -> dict:
    length_str = content_length if isinstance(content_length, str) else ""
    require(
        bool(length_str) and length_str.isascii() and length_str.isdecimal(),
        400,
        "invalid_length",
        "Độ dài yêu cầu không hợp lệ.",
    )
    size = int(length_str)
    require(size > 0, 400, "empty_evidence", "Tệp bằng chứng rỗng.")
    ct_full = (content_type or "").strip()
    ct_main = ct_full.split(";", 1)[0].strip().lower()
    effective_max = (
        min(int(max_size), PDF_EVIDENCE_MAX_BYTES)
        if ct_main in ("application/pdf", "multipart/form-data")
        else min(int(max_size), EVIDENCE_MAX_BYTES)
    )
    limit_label = "20 MB" if effective_max > EVIDENCE_MAX_BYTES else "10 MB"
    require(size <= effective_max, 413, "evidence_too_large", f"Tệp bằng chứng vượt quá giới hạn {limit_label}.")
    raw = stream.read(size)
    require(len(raw) == size, 400, "invalid_length", "Nội dung yêu cầu chưa đầy đủ.")
    if ct_main == "multipart/form-data":
        header_blob = f"Content-Type: {ct_full}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1", errors="ignore")
        msg = BytesParser(policy=EMAIL_HTTP_POLICY).parsebytes(header_blob + raw)
        require(msg.is_multipart(), 400, "invalid_multipart", "Dữ liệu multipart không hợp lệ.")
        file_parts = []
        for part in msg.iter_parts():
            disp_name = part.get_param("name", header="content-disposition")
            if part.get_filename() is not None or disp_name in ("file", "evidence", "image", "document"):
                file_parts.append(part)
        require(
            len(file_parts) == 1,
            400,
            "invalid_evidence_upload",
            "Mỗi yêu cầu tải lên chỉ được chứa đúng một tệp bằng chứng.",
        )
        payload = file_parts[0].get_payload(decode=True)
        require(isinstance(payload, (bytes, bytearray)) and len(payload) > 0, 400, "empty_evidence", "Tệp bằng chứng rỗng.")
        part_ct = (file_parts[0].get_content_type() or "").lower()
        part_is_pdf = part_ct == "application/pdf" or bytes(payload[:5]) == b"%PDF-"
        part_max = min(int(max_size), PDF_EVIDENCE_MAX_BYTES if part_is_pdf else EVIDENCE_MAX_BYTES)
        part_label = "20 MB" if part_is_pdf else "10 MB"
        require(len(payload) <= part_max, 413, "evidence_too_large", f"Tệp bằng chứng vượt quá giới hạn {part_label}.")
        return {
            "_raw_evidence_bytes": bytes(payload),
            "_declared_content_type": part_ct or "application/octet-stream",
            "_filename": file_parts[0].get_filename(),
        }
    return {
        "_raw_evidence_bytes": raw,
        "_declared_content_type": ct_main or "application/octet-stream",
        "_filename": None,
    }


def _identity_control_optional(app):
    return getattr(app, 'identity_store', None) or getattr(getattr(app, 'quota_store', None), 'control', None)


def _admin_control(app):
    control = _identity_control_optional(app)
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


def _authorize_staff_transcript_view(
    app,
    ctx: RequestContext,
    actor: dict,
    *,
    cid: str | None = None,
    case_id: str | None = None,
    audit_resolved: bool = True,
):
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
        if audit_resolved:
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
        if path == "/api/order-action-reasons":
            _require_ctx_permission(ctx, READ)
            return (200, reason_catalog().public(ctx.role))
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
        if path == '/api/order-actions':
            items = app.store.list_customer_order_actions(customer)
            for item in items:
                if isinstance(item.get('order'), dict):
                    item['order'] = _format_order_for_api(item['order'], app)
            return (200, {'order_actions': items})
        m_oa_ev_get = re.fullmatch(r"/api/order-actions/([A-Za-z0-9_-]{1,80})/evidence/(ev_[a-f0-9]{32})", path)
        if m_oa_ev_get:
            req_id, ev_id = m_oa_ev_get[1], m_oa_ev_get[2]
            req_row, ev_row = app.store.get_order_action_evidence_record(req_id, ev_id)
            if STAFF in ctx.permissions:
                actor = _extract_actor(app, customer, binding=binding, context=ctx)
                _authorize_staff_transcript_view(
                    app,
                    ctx,
                    actor,
                    case_id=req_row["case_id"],
                    audit_resolved=True,
                )
            else:
                require(
                    req_row["customer_id"] == customer,
                    404,
                    "order_action_not_found",
                    "Không tìm thấy yêu cầu đơn hàng.",
                )
            data, mime_type = app.store.read_order_action_evidence_bytes(ev_row)
            disp = 'attachment; filename="evidence.pdf"' if mime_type == "application/pdf" else "inline"
            return (200, BinaryPayload(data, mime_type, headers=[("Content-Disposition", disp)]))
        m_chat_ev_get = re.fullmatch(r"/api/conversations/([a-f0-9-]{36})/evidence/(ev_[a-f0-9]{32})", path)
        if m_chat_ev_get:
            cid, ev_id = m_chat_ev_get[1], m_chat_ev_get[2]
            ev_row = app.store.get_chat_evidence_record(cid, ev_id)
            if STAFF in ctx.permissions:
                actor = _extract_actor(app, customer, binding=binding, context=ctx)
                _authorize_staff_transcript_view(
                    app,
                    ctx,
                    actor,
                    cid=cid,
                    case_id=ev_row.get("case_id"),
                    audit_resolved=True,
                )
            else:
                require(
                    ev_row["customer_id"] == customer,
                    404,
                    "evidence_not_found",
                    "Không tìm thấy tệp đính kèm trên cuộc trò chuyện này.",
                )
            data, mime_type = app.store.read_order_action_evidence_bytes(ev_row)
            disp = 'attachment; filename="attachment.pdf"' if mime_type == "application/pdf" else "inline"
            return (200, BinaryPayload(data, mime_type, headers=[("Content-Disposition", disp)]))
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
        if path == "/api/manager/order-actions":
            _require_ctx_permission(ctx, MANAGER)
            _check_staff_tenant_scope(app, ctx)
            qparams = _parse_query_dict(query, {"status_group", "group", "limit", "offset"}) if query else {}
            status_group = qparams.get("status_group") or qparams.get("group") or "all"
            lim = 50
            if "limit" in qparams and qparams["limit"] != "":
                ok_lim, lim_val = _parse_non_negative_int(qparams["limit"])
                require(ok_lim and 1 <= lim_val <= 50, 400, "invalid_limit", "Giới hạn mỗi trang phải từ 1 đến 50.")
                lim = lim_val
            off = 0
            if "offset" in qparams and qparams["offset"] != "":
                ok_off, off_val = _parse_non_negative_int(qparams["offset"])
                require(ok_off and off_val >= 0, 400, "invalid_offset", "Vị trí phân trang không hợp lệ.")
                off = off_val
            return (200, app.store.list_manager_order_actions(status_group=status_group, limit=lim, offset=off))
        m_exchange_options = re.fullmatch(r"/api/orders/([A-Z]{1,6}-[0-9]{1,8})/exchange-options", path)
        if m_exchange_options:
            # Variants of the order's own product with stock status; another customer's order is a 404.
            return (200, app.store.exchange_options(customer, m_exchange_options[1]))
        m = re.fullmatch(r"/api/orders/([A-Z]{1,6}-[0-9]{1,8})", path)
        if m:
            return (200, {"order": _format_order_for_api(app.store.lookup(customer, m[1]), app)})
        if path == "/api/staff/cases":
            _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            return (200, app.store.staff_desk_cases())
        if path == "/api/staff/members":
            _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            control = _identity_control_optional(app)
            tid = ctx.tenant_id or getattr(app, "tenant_id", None)
            members = (
                control.list_active_staff_members(tid)
                if (control is not None and tid and hasattr(control, "list_active_staff_members"))
                else []
            )
            return (200, {"members": members})
        if path == "/api/staff/escalations":
            _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            desk = app.store.staff_desk_cases()
            return (200, {"escalations": app.store.escalations(), **desk})
        if path == "/api/conversations":
            return (200, {"conversations": app.store.list_conversations(customer)})
        m_case_orders = re.fullmatch(r"/api/staff/cases/([A-Za-z0-9_-]{1,80})/orders", path)
        if m_case_orders:
            _require_ctx_permission(ctx, STAFF)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            _, resolved_case_id, ro = _authorize_staff_transcript_view(
                app, ctx, actor, case_id=m_case_orders[1], audit_resolved=False
            )
            info = app.store.list_case_orders(resolved_case_id)
            formatted_orders = []
            for o in info["orders"]:
                open_oa = o.get("open_order_action")
                if isinstance(open_oa, dict) and isinstance(open_oa.get("order"), dict):
                    open_oa = {**open_oa, "order": _format_order_for_api(open_oa["order"], app)}
                base_ord = _format_order_for_api(o, app)
                base_ord["allowed_action_types"] = list(o.get("allowed_action_types") or [])
                base_ord["open_order_action"] = open_oa
                base_ord["days_since_delivery"] = o.get("days_since_delivery")
                base_ord["delivery_age_label"] = o.get("delivery_age_label")
                formatted_orders.append(base_ord)
            return (200, {
                "case_id": resolved_case_id,
                "read_only": ro,
                "orders": formatted_orders,
                "consent_turns": info["consent_turns"],
                "order_action_reasons": {
                    action: {e["code"]: e["label"] for e in reason_catalog().options(action, role=ctx.role)}
                    for action in ACTION_TYPES
                },
            })
        m_case_exchange_options = re.fullmatch(
            r"/api/staff/cases/([A-Za-z0-9_-]{1,80})/orders/([A-Z]{1,6}-[0-9]{1,8})/exchange-options", path
        )
        if m_case_exchange_options:
            _require_ctx_permission(ctx, STAFF)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            _, resolved_case_id, ro = _authorize_staff_transcript_view(
                app, ctx, actor, case_id=m_case_exchange_options[1], audit_resolved=False
            )
            options = app.store.case_exchange_options(resolved_case_id, m_case_exchange_options[2])
            return (200, {**options, "case_id": resolved_case_id, "read_only": ro})
        m_case_oa = re.fullmatch(r"/api/staff/cases/([A-Za-z0-9_-]{1,80})/order-actions", path)
        if m_case_oa:
            _require_ctx_permission(ctx, STAFF)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            _, resolved_case_id, ro = _authorize_staff_transcript_view(
                app, ctx, actor, case_id=m_case_oa[1], audit_resolved=False
            )
            items = app.store.list_case_order_actions(resolved_case_id)
            for item in items:
                if isinstance(item.get('order'), dict):
                    item['order'] = _format_order_for_api(item['order'], app)
            with app.store.connection() as db:
                case_row = db.execute("SELECT customer_id FROM cases WHERE case_id = ?", (resolved_case_id,)).fetchone()
            customer_orders = [
                _format_order_for_api(o, app)
                for o in (app.store.orders(case_row['customer_id']) if case_row else [])
            ]
            return (200, {
                "case_id": resolved_case_id,
                "read_only": ro,
                "order_actions": items,
                "customer_orders": customer_orders,
            })
        m_case_trans = re.fullmatch(r"/api/staff/cases/([A-Za-z0-9_-]{1,80})/messages", path)
        if m_case_trans:
            _require_ctx_permission(ctx, STAFF)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            cid, resolved_case_id, ro = _authorize_staff_transcript_view(
                app, ctx, actor, case_id=m_case_trans[1]
            )
            return (200, app.store.conversation_transcript(cid, case_id=resolved_case_id, read_only=ro))
        m_case_assist_get = re.fullmatch(r"/api/staff/cases/([A-Za-z0-9_-]{1,80})/assist", path)
        if m_case_assist_get:
            _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            qparams = _parse_query_dict(query, {"limit"}) if query else {}
            lim = 50
            if "limit" in qparams and qparams["limit"] != "":
                ok_lim, lim_val = _parse_non_negative_int(qparams["limit"])
                require(ok_lim and 1 <= lim_val <= 100, 400, "invalid_limit", "Giới hạn lịch sử Trợ lý ca không hợp lệ.")
                lim = lim_val
            return (200, app.case_assist_history(actor, m_case_assist_get[1], limit=lim))
        m_case_assist_progress = re.fullmatch(r"/api/staff/cases/([A-Za-z0-9_-]{1,80})/assist/progress", path)
        if m_case_assist_progress:
            _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            return (200, app.case_assist_progress(actor, m_case_assist_progress[1]))
        m_progress = re.fullmatch(r"/api/conversations/([a-f0-9-]{36})/progress", path)
        if m_progress:
            # What the customer's own running turn has done so far (tool names only); nothing for anyone else's.
            _require_ctx_permission(ctx, READ)
            return (200, app.turn_progress(customer, m_progress[1]))
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
        m_fb_prompt = re.fullmatch(r'/api/conversations/([a-f0-9-]{36})/feedback-prompt', path)
        if m_fb_prompt:
            require(body is None or (isinstance(body, dict) and set(body) == set()), 400, 'invalid_fields', 'Các trường của yêu cầu không hợp lệ.')
            return (200, app.store.prompt_case_feedback(customer, m_fb_prompt[1]))
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
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            try:
                result = app.chat(customer, body, actor=actor)
            except ApiError as exc:
                _record_chat_usage(app, customer, body, {'trace': exc.trace}, False)
                raise
            _record_chat_usage(app, customer, body, result, True)
            return (200, result)
        if path == "/api/chat/cancel":
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            return (200, app.cancel_chat(customer, body, actor=actor))
        if path == "/api/feedback":
            res = app.store.record_feedback(customer, body)
            return (200, res)
        if path == "/api/staff/customer-message":
            require(
                isinstance(body, dict)
                and {"conversation_id", "message"}.issubset(set(body))
                and set(body).issubset({"conversation_id", "message", "attachment"}),
                400,
                "invalid_fields",
                "Các trường của yêu cầu không hợp lệ.",
            )
            cid, msg = body["conversation_id"], body["message"]
            res = app.store.customer_message(customer, cid, msg, attachment=body.get("attachment"))
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
        m_case_transfer = re.fullmatch(r"/api/staff/cases/([A-Za-z0-9_-]{1,80})/transfer", path)
        if m_case_transfer:
            _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            require(
                isinstance(body, dict) and set(body) == {"to_principal_id", "version"},
                400,
                "invalid_fields",
                "Các trường của yêu cầu chuyển ca không hợp lệ.",
            )
            to_pid = body["to_principal_id"]
            exp_ver = body["version"]
            require(
                isinstance(to_pid, str) and bool(to_pid.strip()) and len(to_pid.strip()) <= 64,
                400,
                "invalid_transfer_target",
                "Người nhận ca không hợp lệ.",
            )
            require(type(exp_ver) is int and exp_ver >= 1, 400, "invalid_version", "Phiên bản ca không hợp lệ.")
            control = _identity_control_optional(app)
            tid = ctx.tenant_id or getattr(app, "tenant_id", None)
            target_member = (
                control.active_staff_member(tid, to_pid.strip())
                if (control is not None and tid and hasattr(control, "active_staff_member"))
                else None
            )
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            return (
                200,
                app.store.transfer_case(
                    m_case_transfer[1],
                    to_principal_id=to_pid.strip(),
                    target_member=target_member,
                    expected_version=exp_ver,
                    actor=actor,
                ),
            )
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
        m_staff_case_assist_cancel = re.fullmatch(r"/api/staff/cases/([A-Za-z0-9_-]{1,80})/assist/cancel", path)
        if m_staff_case_assist_cancel:
            _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            return (200, app.cancel_case_assist(actor, m_staff_case_assist_cancel[1], body))
        m_staff_case_assist = re.fullmatch(r"/api/staff/cases/([A-Za-z0-9_-]{1,80})/assist", path)
        if m_staff_case_assist:
            _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            try:
                result = app.case_assist(actor, m_staff_case_assist[1], body)
            except ApiError as exc:
                _record_chat_usage(app, customer, body or {}, {"trace": exc.trace}, False)
                raise
            _record_chat_usage(app, customer, body or {}, result, True)
            return (200, result)
        m_staff_case_oa = re.fullmatch(r"/api/staff/cases/([A-Za-z0-9_-]{1,80})/order-actions", path)
        if m_staff_case_oa:
            _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            is_delivery_failure = isinstance(body, dict) and (
                "delivery_failure_attempts" in body
                or ("note" in body and "consent_turn_id" not in body and "reason_code" not in body)
            )
            if is_delivery_failure:
                res = app.store.create_delivery_failure_cancel_request(
                    m_staff_case_oa[1],
                    body,
                    actor=actor,
                    idempotency_key=idempotency_key,
                )
            else:
                res = app.store.create_staff_consented_order_action_request(
                    m_staff_case_oa[1],
                    body,
                    actor=actor,
                    idempotency_key=idempotency_key,
                )
            if isinstance(res.get('order'), dict):
                res['order'] = _format_order_for_api(res['order'], app)
            if isinstance(res.get('order_action'), dict) and isinstance(res['order_action'].get('order'), dict):
                res['order_action']['order'] = _format_order_for_api(res['order_action']['order'], app)
            return (201, res)
        m_oa_ev_post = re.fullmatch(r"/api/order-actions/([A-Za-z0-9_-]{1,80})/evidence", path)
        if m_oa_ev_post:
            oa_id = m_oa_ev_post[1]
            require(
                isinstance(body, dict) and isinstance(body.get("_raw_evidence_bytes"), (bytes, bytearray)),
                415,
                "unsupported_evidence_type",
                "Đường dẫn này nhận tệp ảnh nhị phân hoặc multipart/form-data.",
            )
            if STAFF in ctx.permissions:
                _require_ctx_permission(ctx, STAFF)
                _check_staff_tenant_scope(app, ctx)
            else:
                _require_ctx_permission(ctx, CANCEL)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            res = app.store.upload_order_action_evidence(
                oa_id,
                bytes(body["_raw_evidence_bytes"]),
                customer_id=customer,
                actor=actor,
                filename=body.get("_filename"),
            )
            if isinstance(res.get("order_action"), dict) and isinstance(res["order_action"].get("order"), dict):
                res["order_action"]["order"] = _format_order_for_api(res["order_action"]["order"], app)
            return (201, res)
        m_oa_step = re.fullmatch(
            r"/api/order-actions/([A-Za-z0-9_-]{1,80})/(approve|reject|mark-received|mark-inspected|complete|refund-request|refund-decision|refund-outcome)",
            path,
        )
        if m_oa_step:
            oa_id, step_slug = m_oa_step[1], m_oa_step[2]
            if step_slug in ("refund-decision", "refund-outcome"):
                _require_ctx_permission(ctx, MANAGER)
            else:
                _require_ctx_permission(ctx, STAFF)
            _check_staff_tenant_scope(app, ctx)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            if step_slug == "refund-request":
                res = app.store.request_order_action_refund(
                    oa_id, body, actor=actor, idempotency_key=idempotency_key
                )
            elif step_slug == "refund-decision":
                res = app.store.decide_order_action_refund(
                    oa_id, body, actor=actor, idempotency_key=idempotency_key
                )
            elif step_slug == "refund-outcome":
                res = app.store.record_order_action_refund_outcome(
                    oa_id, body, actor=actor, idempotency_key=idempotency_key
                )
            else:
                act_map = {
                    "approve": "approve",
                    "reject": "reject",
                    "mark-received": "mark_received",
                    "mark-inspected": "mark_inspected",
                    "complete": "complete",
                }
                res = app.store.transition_order_action_request(
                    oa_id, act_map[step_slug], body, actor=actor, idempotency_key=idempotency_key
                )
                if res.get("order_mutated") and hasattr(app, "tool_cache"):
                    ord_cust = (res.get("order") or {}).get("customer_id")
                    tenant_id = ctx.tenant_id or getattr(app, "tenant_id", "default")
                    if ord_cust:
                        app.tool_cache.invalidate(tenant_id=tenant_id, customer=ord_cust)
            if isinstance(res.get('order'), dict):
                res['order'] = _format_order_for_api(res['order'], app)
            if isinstance(res.get('order_action'), dict) and isinstance(res['order_action'].get('order'), dict):
                res['order_action']['order'] = _format_order_for_api(res['order_action']['order'], app)
            return (200, res)
        if path == "/api/order-actions":
            _require_ctx_permission(ctx, CANCEL)
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            res = app.store.create_order_action_request(
                customer,
                body,
                actor=actor,
                idempotency_key=idempotency_key,
            )
            if isinstance(res.get('order'), dict):
                res['order'] = _format_order_for_api(res['order'], app)
            if isinstance(res.get('order_action'), dict) and isinstance(res['order_action'].get('order'), dict):
                res['order_action']['order'] = _format_order_for_api(res['order_action']['order'], app)
            return (201, res)
        if path == "/api/cancellation-proposals":
            _require_ctx_permission(ctx, CANCEL)
            result = app.store.propose(customer, body)
            approval.drive(app, customer, result['proposal_id'])
            return (201, {**result, 'workflow_status': 'awaiting_confirmation'})
        if path == "/api/tools/execute":
            _require_ctx_permission(ctx, MANAGER)
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
            from agent_protocol import ProtocolError, validate_tool
            from retailops_tools import BoundTools
            tool_name, arguments = body['tool_name'], body['arguments']
            require(
                isinstance(tool_name, str) and tool_name in ALLOWED_DIRECT_TOOLS,
                403,
                'tool_not_allowed',
                'Công cụ này không được phép gọi trực tiếp qua đường vận hành.',
            )
            try:
                validate_tool(tool_name, arguments)
            except ProtocolError as exc:
                raise ApiError(400, 'invalid_tool_arguments', str(exc)) from None
            now_ts = app.store._now() if hasattr(app.store, '_now') else time.time()
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
                any_ep = (
                    db.execute(
                        'SELECT handoff_id FROM handoff_episodes WHERE case_id = ? LIMIT 1',
                        (case_row['case_id'],),
                    ).fetchone()
                    if case_row is not None
                    else None
                )
                if case_row is not None and case_row['status'] in ('waiting', 'in_progress') and (
                    open_ep is not None or case_row['holder'] is not None
                ):
                    pass
                elif case_row is not None and case_row['status'] == 'resolved' and any_ep is not None:
                    within_retention = (
                        float(conv['expires_at']) > now_ts
                        and (
                            case_row['resolved_at'] is None
                            or (now_ts - float(case_row['resolved_at'])) <= app.store.CONVERSATION_TTL
                        )
                    )
                    require(
                        within_retention,
                        403,
                        'case_retention_expired',
                        'Ca hỗ trợ đã đóng và quá thời hạn lưu trữ.',
                    )
                else:
                    raise ApiError(
                        403,
                        'case_not_escalated',
                        'Chỉ được tra cứu công cụ trực tiếp trên ca hỗ trợ trong phạm vi Staff Desk.',
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
                case_id=case_row['case_id'],
                conversation_id=cid,
                actor=actor,
            )
            return (200, {'tool_name': tool_name, 'arguments': arguments, 'case_id': case_row['case_id'], 'conversation_id': cid, 'result': res})
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
            require(
                isinstance(body, dict)
                and {"order_id", "status"}.issubset(set(body))
                and set(body).issubset({"order_id", "status", "version", "expected_order_version"}),
                400,
                "invalid_body",
                "Thiếu order_id hoặc status, hoặc có trường không hợp lệ.",
            )
            oid, new_status = body["order_id"], body["status"]
            if "version" in body and "expected_order_version" in body:
                require(
                    body["version"] == body["expected_order_version"],
                    400,
                    "invalid_order_version",
                    "Trường version và expected_order_version xung đột.",
                )
            expected_ver = body.get("version") if "version" in body else body.get("expected_order_version")
            actor = _extract_actor(app, customer, binding=binding, context=ctx)
            res = app.store.manager_update_order_status(
                oid,
                new_status,
                expected_version=expected_ver,
                actor=actor,
                idempotency_key=idempotency_key,
            )
            if res.get("changed") and hasattr(app, 'tool_cache'):
                tenant_id = ctx.tenant_id or getattr(app, 'tenant_id', 'default')
                app.tool_cache.invalidate(tenant_id=tenant_id, customer=res["customer_id"])
            return (200, {
                "status": "ok",
                "order_id": res["order_id"],
                "new_status": res["new_status"],
                "version": res["version"],
                "delivered_at": res["delivered_at"],
                "message": res["message"],
            })
        m = re.fullmatch(r"/api/cancellation-proposals/([a-f0-9-]{36})/(confirm|dismiss)", path)
        if m:
            _require_ctx_permission(ctx, CANCEL)
            if m[2] == "confirm":
                actor = _extract_actor(app, customer, binding=binding, context=ctx)
                res = approval.confirm(app, customer, m[1], body, idempotency_key, actor=actor)
                if hasattr(app, 'tool_cache'):
                    tenant_id = ctx.tenant_id or getattr(app, 'tenant_id', 'default')
                    app.tool_cache.invalidate(tenant_id=tenant_id, customer=customer)
                return (200, res)
            fields(body, set())
            return (200, approval.dismiss(app, customer, m[1]))
    raise ApiError(404, "not_found", "Không tìm thấy đường dẫn.")
