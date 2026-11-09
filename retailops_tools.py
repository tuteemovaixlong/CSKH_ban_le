"""Read-only tools bound to the authenticated customer by the application."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

from retailops.business.eligibility import compute_order_eligibility, format_vn_iso
from retailops.business.variants import match_variants
from retailops.core import ApiError
from retailops.knowledge.tool import KnowledgeTool
from retailops.order_reasons import reason_catalog
from retailops_conversation import normalize

ROOT = Path(__file__).resolve().parent
_ORDER_ID = re.compile(r'\bO-(\d+)\b', re.IGNORECASE)
_INTERNAL_ORDER_ID = re.compile(r'\bord_([0-9a-f]{32})\b', re.IGNORECASE)
_EXTERNAL_ORDER_ID = re.compile(r'\b((?!P-\d+\b|KB:)[A-Za-z0-9]{2,12}-[A-Za-z0-9_-]{2,48})\b', re.IGNORECASE)

# Customer PII (name, phone, address, email, customer_id) and internal backfill markers are never sent to the model.
_PII_KEYS = (
    'customer_id',
    'customer_name',
    'phone',
    'customer_phone',
    'shipping_address',
    'address',
    'address_line',
    'email',
    'ordered_at_backfilled',
    'name_enc',
    'phone_enc',
    'address_line_enc',
    'phone_lookup_hmac',
    'recipient_name',
    'recipient_phone',
    'recipient_address',
)


def customer_named_orders(text):
    """Order IDs (internal or external) the customer wrote in a message."""
    src = text or ''
    found = {f'O-{digits}' for digits in _ORDER_ID.findall(src)}
    found.update(f'ord_{h.lower()}' for h in _INTERNAL_ORDER_ID.findall(src))
    for ext in _EXTERNAL_ORDER_ID.findall(src):
        found.add(ext)
        found.add(ext.upper())
    return found


def is_order_confirmed(order, confirmed):
    """Return True when an order's internal id or external_order_id is in confirmed."""
    if confirmed is None:
        return True
    if not isinstance(order, dict) or not confirmed:
        return False
    lowered = {str(x).lower() for x in confirmed if x}
    for key in ('id', 'internal_order_id', 'external_order_id'):
        val = order.get(key)
        if val and (val in confirmed or str(val).lower() in lowered):
            return True
    return False


def confirmed_orders_for(text, snapshot):
    """Orders a request form may be prepared for: the ones the customer named, else the one in focus.

    The model never chooses the target of a transaction on its own: an order that is neither named in the
    customer's message nor the conversation's focused order has to be confirmed with the customer first.
    """
    named = customer_named_orders(text)
    focus = snapshot.get('order_id') if isinstance(snapshot, dict) else None
    return named or ({focus} if focus else set())


def _ambiguous_order_response(oid, candidates):
    return {
        'error': 'ambiguous_order',
        'order_id': oid,
        'message': (
            'Có nhiều đơn hàng của bạn trùng mã này từ các nguồn khác nhau. '
            'Không tự chọn đơn: hãy hỏi lại khách xác nhận nguồn đặt hàng, ngày đặt hoặc tên sản phẩm '
            'rồi gọi lại công cụ bằng internal_order_id tương ứng.'
        ),
        'candidates': candidates,
    }


def _fallback_order_details(order, product, *, now_ts=None):
    eligibility = compute_order_eligibility(order, product=product, as_of=now_ts)
    ordered_iso = (
        None
        if int(order.get('ordered_at_backfilled') or 0) == 1
        else format_vn_iso(order.get('ordered_at'))
    )
    is_unrecorded_seed = (
        order.get('source_system') == 'retailops_seed'
        and order.get('payment_method') is None
    )
    payment_status = None if is_unrecorded_seed else order.get('payment_status')
    return {
        'ordered_at': ordered_iso,
        'payment_method': order.get('payment_method'),
        'payment_status': payment_status,
        'shipping_fee': int(order['shipping_fee']) if order.get('shipping_fee') is not None else None,
        'ship_to_area': order.get('ship_to_area'),
        'promised_delivery_by': format_vn_iso(order.get('promised_delivery_by')),
        'delivered_at': format_vn_iso(order.get('delivered_at')),
        'refund_summary': None,
        'payment': (
            {'method': order.get('payment_method'), 'status': payment_status}
            if order.get('payment_method') is not None
            else None
        ),
        'delivery': (
            {
                'ship_to_area': order.get('ship_to_area'),
                'promised_delivery_by': format_vn_iso(order.get('promised_delivery_by')),
                'delivered_at': format_vn_iso(order.get('delivered_at')),
            }
            if (order.get('delivered_at') is not None or order.get('promised_delivery_by') is not None)
            else None
        ),
        'refund': None,
        'recipient': None,
        'vouchers': [],
        'eligibility': eligibility,
        'as_of': eligibility['as_of'],
    }


class BoundTools:
    def __init__(self, store, catalog, customer, snapshot, identity, *, can_cancel=True, read_only=False, user_text='',
                 confirmed_orders=None):
        self.store, self.catalog, self.customer, self.snapshot = store, catalog, customer, snapshot
        self.conversation_id = snapshot.get('id') if isinstance(snapshot, dict) else None
        self.context = {k: (snapshot.get(k) if isinstance(snapshot, dict) else None) for k in ('order_id', 'product_id')}
        self.identity = identity
        self.versions = {}
        self.cancel_order = None
        self.prepared_order_action = None
        self.can_cancel = bool(can_cancel) and not bool(read_only)
        self.read_only = bool(read_only)
        self.user_text = str(user_text or '')
        # None: not enforced (direct callers). A set: the only orders prepare_order_action may open a form for.
        self.confirmed_orders = None if confirmed_orders is None else frozenset(confirmed_orders)
        self.knowledge = KnowledgeTool(store)
        self.shipment = None
        self.human_support = None

    def _resolve_order_or_candidates(self, oid, *, focus=True):
        with self.store.connection() as db:
            if hasattr(self.store, 'resolve_customer_order_in_tx'):
                order, candidates = self.store.resolve_customer_order_in_tx(db, self.customer, oid)
                if candidates is not None:
                    return None, _ambiguous_order_response(oid, candidates)
            else:
                order = self.store.owned(db, self.customer, oid)
            product = self.catalog.for_order(order)
            if hasattr(self.store, 'read_order_details_in_tx'):
                details = self.store.read_order_details_in_tx(db, order)
            else:
                now_ts = self.store._now() if hasattr(self.store, '_now') else None
                details = _fallback_order_details(order, product, now_ts=now_ts)
        canonical_id = order['id']
        ext_id = order.get('external_order_id') or canonical_id
        self.versions[canonical_id] = order['version']
        if focus:
            self.context = {'order_id': canonical_id, 'product_id': product['id'] if product else order.get('product_id')}
        enriched = {k: v for k, v in order.items() if k not in _PII_KEYS} | {
            'id': canonical_id,
            'internal_order_id': canonical_id,
            'external_order_id': ext_id,
            'source_system': order.get('source_system'),
            'product_id': product['id'] if product else order.get('product_id'),
            'currency': 'VND',
            'ordered_at': details['ordered_at'],
            'payment_method': details['payment_method'],
            'payment_status': details['payment_status'],
            'shipping_fee': details['shipping_fee'],
            'ship_to_area': details['ship_to_area'],
            'promised_delivery_by': details['promised_delivery_by'],
            'delivered_at': details['delivered_at'],
            'refund_summary': details['refund_summary'],
            'payment': details['payment'],
            'delivery': details['delivery'],
            'address': None,
            'recipient': details.get('recipient'),
            'vouchers': details.get('vouchers') or [],
            'refund': details['refund'],
            'eligibility': details['eligibility'],
            'as_of': details['as_of'],
            'source': 'retailops_db/orders',
        }
        return enriched, None

    def read_order(self, oid, focus=True):
        order, ambiguous = self._resolve_order_or_candidates(oid, focus=focus)
        if ambiguous is not None:
            err = ApiError(409, 'ambiguous_order', ambiguous['message'])
            err.ambiguous_payload = ambiguous
            raise err
        return order

    def __call__(self, name, args):
        if name == 'search_knowledge':
            return self.knowledge.search(args['query'])
        if name == 'list_orders':
            orders = self.store.orders(self.customer)
            sliced = orders[:10]
            truncated = len(orders) > 10
            res = {
                'orders': [self.read_order(o['id'], focus=False) for o in sliced],
                'truncated': truncated,
                'returned_count': len(sliced),
                'total_count': len(orders),
            }
            if truncated:
                res['note'] = f'Showing {len(sliced)} of {len(orders)} orders; list is truncated and not complete.'
            return res
        if name == 'get_order':
            try:
                return {'order': self.read_order(args['order_id'], focus=True)}
            except ApiError as exc:
                if exc.code == 'ambiguous_order' and hasattr(exc, 'ambiguous_payload'):
                    return exc.ambiguous_payload
                raise
        if name == 'search_products':
            query = normalize(args['query']).strip()
            products = []
            for p in self.catalog.products.values():
                cat = str(p.get('category') or '')
                raw_aliases = p.get('aliases')
                if isinstance(raw_aliases, (list, tuple)):
                    aliases = [str(a) for a in raw_aliases if a is not None]
                elif isinstance(raw_aliases, str):
                    aliases = [raw_aliases]
                else:
                    aliases = []
                searchable = normalize(' '.join([str(p.get('id', '')), str(p.get('name', '')), cat] + aliases))
                if query in searchable:
                    products.append(p)
            if len(products) == 1:
                if self.context['product_id'] != products[0]['id']:
                    self.context['order_id'] = None
                self.context['product_id'] = products[0]['id']
            return {'products': products[:10], 'source': self.catalog.source,
                    'note': 'Null or absent attributes are unknown; listed variants do not imply stock.'}
        if name == 'get_product':
            raw_pid = args['product_id']
            product = self.catalog.products.get(raw_pid) if (isinstance(raw_pid, str) and raw_pid.isascii()) else None
            if product is None:
                return {'error': 'product_not_found', 'message': 'No matching product in the catalog.'}
            if self.context['product_id'] != product['id']:
                self.context['order_id'] = None
            self.context['product_id'] = product['id']
            result = {'product': product, 'source': self.catalog.source,
                      'note': 'Null or absent attributes are unknown. `availability` (when present) is the only stock '
                              'information: each variant is in_stock, out_of_stock or unknown.'}
            availability = getattr(self.store, 'product_variant_availability', None)
            if callable(availability):
                listed = availability(product['id'])
                if listed:
                    result['availability'] = listed
            return result
        if name == 'get_context':
            oid = self.context['order_id']
            if oid:
                order, ambiguous = self._resolve_order_or_candidates(oid, focus=True)
                if ambiguous is not None:
                    return ambiguous
            else:
                order = None
            return {'order': order, 'product': self.catalog.products.get(self.context['product_id']),
                    'note': 'These are current focused records, not permission to change them.'}
        if name in ('prepare_order_action', 'prepare_cancellation'):
            if not self.can_cancel:
                return {'error': 'permission_denied', 'message': 'This account can view orders but cannot request order actions.'}
            if name == 'prepare_cancellation':
                action_type, target_text = 'cancel', None
            else:
                action_type = str(args.get('action_type') or 'cancel').strip().lower()
                if action_type not in ('cancel', 'return', 'exchange'):
                    return {'error': 'invalid_tool_arguments', 'message': 'action_type must be cancel, return, or exchange.'}
                target_text = args.get('target_variant')
                if target_text is not None and action_type != 'exchange':
                    return {'error': 'invalid_tool_arguments', 'message': 'target_variant is only allowed when action_type is exchange.'}
            order, ambiguous = self._resolve_order_or_candidates(args['order_id'], focus=False)
            if ambiguous is not None:
                self.prepared_order_action = None
                self.cancel_order = None
                return ambiguous
            if not is_order_confirmed(order, self.confirmed_orders):
                self.prepared_order_action = None
                self.cancel_order = None
                return {
                    'order_id': order['external_order_id'],
                    'internal_order_id': order['id'],
                    'external_order_id': order['external_order_id'],
                    'action_type': action_type,
                    'eligible': False,
                    'ineligible_reason': {
                        'code': 'order_not_confirmed',
                        'message': 'The customer did not name this order in their message and it is not the order in focus.'},
                    'transaction_performed': False,
                    'next_step': 'Ask the customer which order they mean (its ID), then call this tool again.',
                }
            self.context = {'order_id': order['id'], 'product_id': order['product_id']}  # the customer's order is now the focus
            has_open_request = False
            try:
                with self.store.connection() as db:
                    open_row = db.execute(
                        'SELECT 1 FROM order_action_requests WHERE order_id = ? AND closed_at IS NULL LIMIT 1',
                        (order['id'],),
                    ).fetchone()
                    has_open_request = open_row is not None
            except Exception:
                has_open_request = False
            ineligible = None
            handoff_recommended = False
            if has_open_request:
                ineligible = {'code': 'open_request_exists',
                              'message': 'This order already has an open order-action request.'}
            elif action_type == 'cancel' and order['status'] == 'shipping':
                handoff_recommended = True
                ineligible = {
                    'code': 'order_already_shipping',
                    'message': (
                        'Đơn hàng đang trong quá trình vận chuyển (shipping) nên không thể mở yêu cầu hủy tự phục vụ; '
                        'cần chuyển nhân viên CSKH hỗ trợ.'
                    ),
                }
            elif action_type == 'cancel' and order['status'] != 'pending':
                ineligible = {'code': 'order_not_pending',
                              'message': f"Only a pending order can be cancelled; this order is {order['status']}."}
            elif action_type != 'cancel' and order['status'] != 'delivered':
                ineligible = {'code': 'order_not_delivered',
                              'message': f"Only a delivered order can be returned or exchanged; this order is {order['status']}."}
            eligible = ineligible is None
            reason_options = [
                {'code': e['code'], 'label': e['label'], 'requires_text': e['requires_text']}
                for e in reason_catalog().options(action_type, role='customer')
            ]
            exchange_kind, target_variant_id, exchange_view = None, None, None
            if action_type == 'exchange':
                options = self.store.exchange_options(self.customer, order['id'])
                matches = match_variants(options['variants'], target_text) if target_text else []
                if len(matches) == 1:
                    exchange_kind, target_variant_id = 'other_variant', matches[0]['id']
                exchange_view = {
                    'product_id': options['product_id'],
                    'current_variant': order.get('variant'),
                    'kinds': {'other_variant': 'swap to another variant of the same product (color, size, style)',
                              'same_variant': 'replace the same variant, for a defective item'},
                    'variants': [{k: v[k] for k in ('id', 'label', 'stock_status', 'is_current')}
                                 for v in options['variants']],
                    'requested_target': target_text,
                    'matched_variants': [{'id': v['id'], 'label': v['label'], 'stock_status': v['stock_status']}
                                         for v in matches],
                    'note': 'Stock is information for the customer and staff; it never decides whether a request '
                            'may be made. The customer picks the target on the form.',
                }
            if eligible:
                self.prepared_order_action = {
                    'order': order,
                    'action_type': action_type,
                    'exchange_kind': exchange_kind,
                    'target_variant_id': target_variant_id,
                }
                self.cancel_order = order if action_type == 'cancel' else None
            else:
                self.prepared_order_action = None
                self.cancel_order = None
            if eligible:
                next_step = 'A request form is open on the customer\'s screen: they pick a reason and press the separate confirmation button.'
            elif handoff_recommended:
                next_step = (
                    'Explain clearly that an order already in shipping status cannot open a self-service cancellation '
                    'request, and offer to transfer the conversation to a human support staff member '
                    '(call request_human_support if the customer wants human assistance).'
                )
            else:
                next_step = ineligible['message']
            result = {
                'order': order,
                'order_id': order['external_order_id'],
                'internal_order_id': order['id'],
                'external_order_id': order['external_order_id'],
                'action_type': action_type,
                'exchange_kind': exchange_kind,
                'eligible': eligible,
                'ineligible_reason': ineligible,
                'handoff_recommended': handoff_recommended,
                'eligibility': order.get('eligibility'),
                'as_of': order.get('as_of'),
                'has_open_request': has_open_request,
                'reasons': reason_options,
                'transaction_performed': False,
                'next_step': next_step,
            }
            if exchange_view is not None:
                result['exchange'] = exchange_view
            return result
        if name in ('clear_cancellation', 'reset_cancellation', 'clear_order_action'):
            self.cancel_order = None
            self.prepared_order_action = None
            return {'cleared': True}
        if name == 'get_runtime_info':
            return {k: self.identity.get(k) for k in ('name', 'digest', 'details', 'ollama_version', 'agent_protocol', 'provider', 'identity_source')}
        if name == 'get_current_time':
            vn_tz = timezone(timedelta(hours=7))
            now = (
                datetime.fromtimestamp(float(self.store._now()), tz=vn_tz)
                if hasattr(self.store, '_now')
                else datetime.now(vn_tz)
            )
            return {'date': now.date().isoformat(), 'time': now.isoformat(timespec='seconds'),
                    'timezone': 'Asia/Ho_Chi_Minh (UTC+07:00)', 'source': 'backend_clock'}
        if name == 'track_shipment':
            oid = args['order_id']
            with self.store.connection() as db:
                if hasattr(self.store, 'resolve_customer_order_in_tx'):
                    raw_order, candidates = self.store.resolve_customer_order_in_tx(db, self.customer, oid)
                    if candidates is not None:
                        self.shipment = None
                        return _ambiguous_order_response(oid, candidates)
                else:
                    raw_order = self.store.owned(db, self.customer, oid)
                product = self.catalog.for_order(raw_order)
                if hasattr(self.store, 'read_order_details_in_tx'):
                    details = self.store.read_order_details_in_tx(db, raw_order)
                else:
                    now_ts = self.store._now() if hasattr(self.store, '_now') else None
                    details = _fallback_order_details(raw_order, product, now_ts=now_ts)
                shipment = (
                    self.store.read_order_shipment_in_tx(db, raw_order)
                    if hasattr(self.store, 'read_order_shipment_in_tx')
                    else None
                )
            canonical_id = raw_order['id']
            ext_id = raw_order.get('external_order_id') or canonical_id
            self.versions[canonical_id] = raw_order['version']
            self.context = {
                'order_id': canonical_id,
                'product_id': product['id'] if product else raw_order.get('product_id'),
            }
            self.shipment = shipment
            return {
                'order_id': ext_id,
                'internal_order_id': canonical_id,
                'external_order_id': ext_id,
                'source_system': raw_order.get('source_system'),
                'order_status': raw_order.get('status'),
                'promised_delivery_by': details.get('promised_delivery_by'),
                'eligibility': details.get('eligibility'),
                'as_of': details.get('as_of'),
                'shipment': shipment,
                'source': 'retailops_db/shipments',
            }
        if name == 'check_inventory':
            pid = args['product_id']
            size = args['size'].upper().strip()
            color = args['color'].strip()
            if not isinstance(pid, str) or not pid.isascii():
                return {'error': 'product_not_found', 'message': f'Sản phẩm {pid} không tồn tại trong kho.'}
            product = self.catalog.products.get(pid) or (self.store.get_product(pid) if hasattr(self, 'store') and self.store else None)
            if not product:
                return {'error': 'product_not_found', 'message': f'Sản phẩm {pid} không tồn tại trong kho.'}
            var_res = self.catalog.get_variant_stock(pid, size, color)
            if hasattr(var_res, 'status'):
                stock, status = var_res.stock, var_res.status
            elif isinstance(var_res, tuple):
                stock, status = var_res[0], var_res[1]
            else:
                stock, status = var_res, ('ok' if var_res is not None else 'stock_unknown')

            if status == 'variant_not_found':
                return {
                    'error': 'variant_not_found',
                    'product_id': pid, 'product_name': product.get('name'),
                    'size': size, 'color': color,
                    'stock': 0, 'in_stock': False,
                    'status_text': f'Sản phẩm {product.get("name")} không có biến thể màu "{color}", size "{size}".'
                }
            if status == 'stock_unknown' or stock is None:
                return {
                    'product_id': pid, 'product_name': product.get('name'),
                    'size': size, 'color': color,
                    'stock': None, 'in_stock': None,
                    'status_text': f'Tồn kho sản phẩm {product.get("name")} hiện chưa được cập nhật.'
                }
            in_stock = stock > 0
            return {
                'product_id': pid, 'product_name': product.get('name'),
                'size': size, 'color': color,
                'stock': stock,
                'in_stock': in_stock,
                'status_text': f'Còn {stock} sản phẩm trong kho' if in_stock else f'Sản phẩm {product.get("name")} (màu {color}, size {size}) tạm thời hết hàng.'
            }
        if name == 'request_human_support':
            if self.read_only:
                self.human_support = None
                return {
                    'status': 'read_only_blocked',
                    'escalated': False,
                    'message': 'Truy vấn hiện tại ở chế độ chỉ đọc (read-only); không thực hiện chuyển tiếp hoặc thay đổi trạng thái.',
                }
            from retailops.guardrails.topic_filter import contains_canary_or_secret

            reason = str(args.get('reason') or '').strip()
            if contains_canary_or_secret(reason, user_text=self.user_text):
                reason = 'Khách hàng yêu cầu hỗ trợ trực tiếp từ nhân viên [REDACTED_BY_OUTPUT_GUARD]'

            cid = self.snapshot.get('id') if hasattr(self, 'snapshot') and isinstance(self.snapshot, dict) else None
            if not cid or not hasattr(self, 'store') or self.store is None:
                self.human_support = None
                raise ApiError(
                    503,
                    'handoff_unavailable',
                    'Không thể lưu phiên chuyển tiếp nhân viên khi thiếu cuộc trò chuyện hoặc kho dữ liệu.',
                )

            if hasattr(self.store, 'request_human_handoff'):
                handoff = self.store.request_human_handoff(
                    self.customer,
                    cid,
                    reason_code='customer_requested_human',
                    comment=reason,
                )
            else:
                fn = getattr(self.store, 'record_feedback', getattr(self.store, 'save_feedback', None))
                if not fn:
                    self.human_support = None
                    raise ApiError(503, 'handoff_unavailable', 'Kho dữ liệu không hỗ trợ lưu phiên chuyển tiếp nhân viên.')
                handoff = fn(self.customer, {
                    'conversation_id': cid,
                    'feedback_type': 'human_handoff',
                    'sentiment_flag': 'neutral',
                    'reason_code': 'customer_requested_human',
                    'comment': reason,
                })

            res = {
                'status': 'escalated_to_human',
                'case_id': handoff.get('case_id') if isinstance(handoff, dict) else None,
                'handoff_id': handoff.get('handoff_id') if isinstance(handoff, dict) else None,
                'notice_turn_id': handoff.get('notice_turn_id') if isinstance(handoff, dict) else None,
                'notice_message': handoff.get('notice_message') if isinstance(handoff, dict) else None,
                'reason': reason,
                'queue': 'staff_desk',
                'message': (
                    f'Đã chuyển yêu cầu hỗ trợ trực tiếp cho nhân viên: "{reason}". '
                    'Bộ phận CSKH sẽ tiếp nhận ca của bạn.'
                ),
            }
            self.human_support = res
            return res
        return {'error': 'tool_not_allowed', 'message': 'No action performed.'}
