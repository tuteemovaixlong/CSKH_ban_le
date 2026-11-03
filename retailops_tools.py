"""Read-only tools bound to the authenticated customer by the application."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

from retailops.business.variants import match_variants
from retailops.order_reasons import reason_catalog
from retailops_conversation import normalize
from retailops.knowledge.tool import KnowledgeTool

ROOT = Path(__file__).resolve().parent
_ORDER_ID = re.compile(r'\bO-(\d+)\b', re.IGNORECASE)


def customer_named_orders(text):
    """Order IDs the customer wrote in a message."""
    return {f'O-{digits}' for digits in _ORDER_ID.findall(text or '')}


def confirmed_orders_for(text, snapshot):
    """Orders a request form may be prepared for: the ones the customer named, else the one in focus.

    The model never chooses the target of a transaction on its own: an order that is neither named in the
    customer's message nor the conversation's focused order has to be confirmed with the customer first.
    """
    named = customer_named_orders(text)
    focus = snapshot.get('order_id') if isinstance(snapshot, dict) else None
    return named or ({focus} if focus else set())


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

    def read_order(self, oid, focus=True):
        with self.store.connection() as db:
            order = self.store.owned(db, self.customer, oid)
        self.versions[oid] = order['version']
        product = self.catalog.for_order(order)
        if focus:
            self.context = {'order_id': oid, 'product_id': product['id'] if product else None}
        # Customer identity is never model-controlled or needed in the transcript.
        return {k: v for k, v in order.items() if k != 'customer_id'} | {
            'product_id': product['id'] if product else None, 'currency': 'VND',
            'payment': None, 'delivery': None, 'address': None, 'refund': None,
            'source': 'synthetic-demo/orders'}

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
            return {'order': self.read_order(args['order_id'])}
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
            order = self.read_order(oid) if oid else None
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
            order = self.read_order(args['order_id'], focus=False)
            if self.confirmed_orders is not None and order['id'] not in self.confirmed_orders:
                self.prepared_order_action = None
                self.cancel_order = None
                return {
                    'order_id': order['id'], 'action_type': action_type, 'eligible': False,
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
            if has_open_request:
                ineligible = {'code': 'open_request_exists',
                              'message': 'This order already has an open order-action request.'}
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
            else:
                next_step = ineligible['message']
            result = {
                'order': order,
                'action_type': action_type,
                'exchange_kind': exchange_kind,
                'eligible': eligible,
                'ineligible_reason': ineligible,
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
            now = datetime.now(timezone(timedelta(hours=7)))
            return {'date': now.date().isoformat(), 'time': now.isoformat(timespec='seconds'),
                    'timezone': 'Asia/Ho_Chi_Minh (UTC+07:00)', 'source': 'backend_clock'}
        if name == 'track_shipment':
            oid = args['order_id']
            order = self.read_order(oid)
            carriers = {
                'O-101': {
                    'carrier': 'Giao Hàng Tiết Kiệm (GHTK)',
                    'tracking_code': 'GHTK.VN.0918231',
                    'status': 'in_transit',
                    'status_text': 'Đang trung chuyển',
                    'current_location': 'Bưu cục Tân Bình, TP.HCM',
                    'shipper': 'Nguyễn Văn Nam (0903.112.334)',
                    'estimated_delivery': 'Ngày mai (trước 17:00)',
                    'steps': [
                        {'time': '08:30 hôm nay', 'event': 'Đang trên xe trung chuyển liên tỉnh'},
                        {'time': '20:15 hôm qua', 'event': 'Đã nhập kho phân loại Tân Bình'},
                        {'time': '14:00 hôm qua', 'event': 'Shop RetailOps đã bàn giao cho shipper GHTK'}
                    ]
                },
                'O-102': {
                    'carrier': 'Giao Hàng Nhanh (GHN)',
                    'tracking_code': 'GHN.VN.8839210',
                    'status': 'delivered',
                    'status_text': 'Đã giao thành công',
                    'current_location': 'Người nhận đã ký nhận',
                    'shipper': 'Trần Quốc Tuấn (0982.551.442)',
                    'estimated_delivery': 'Đã giao lúc 10:15 hôm qua',
                    'steps': [
                        {'time': '10:15 hôm qua', 'event': 'Giao hàng thành công - Khách hàng đã ký nhận'},
                        {'time': '08:00 hôm qua', 'event': 'Shipper đang trên đường giao tới bạn'}
                    ]
                },
                'O-301': {
                    'carrier': 'SPX Express',
                    'tracking_code': 'SPX.VN.9928110',
                    'status': 'delivery_failed_virtual',
                    'status_text': 'Bưu tá báo không liên lạc được (Ảo)',
                    'current_location': 'Bưu cục Cầu Giấy 2, Hà Nội',
                    'shipper': 'Nguyễn Văn Tuấn (0934.112.233)',
                    'system_note': 'Tổng đài kiểm tra bưu cục ghi nhận không có lịch sử cuộc gọi ra lúc cập nhật.',
                    'can_reassign_today': True,
                    'estimated_delivery': 'Hôm nay trước 18:00 (khiếu nại giao lại ngay trong ca)',
                    'steps': [
                        {'time': '14:30 hôm nay', 'event': 'Bưu tá báo không liên lạc được (Hệ thống ghi nhận nghi vấn báo ảo)'},
                        {'time': '08:15 hôm nay', 'event': 'Bưu tá Nguyễn Văn Tuấn (0934.112.233) xuất kho giao hàng'},
                        {'time': '05:00 hôm nay', 'event': 'Nhập bưu cục Cầu Giấy 2'}
                    ]
                },
                'O-302': {
                    'carrier': 'Giao Hàng Tiết Kiệm (GHTK)',
                    'tracking_code': 'GHTK.VN.4419201',
                    'status': 'delivered',
                    'status_text': 'Đã giao thành công',
                    'current_location': 'Khách hàng đã ký nhận',
                    'shipper': 'Lê Quốc Bảo (0912.883.991)',
                    'delivery_date': '5 ngày trước',
                    'product_id': 'P-104',
                    'warranty_eligible': True,
                    'warranty_days_left': 85,
                    'steps': [
                        {'time': '11:00 5 ngày trước', 'event': 'Giao hàng thành công - Người nhận ký nhận'},
                        {'time': '08:30 5 ngày trước', 'event': 'Shipper đang giao hàng'}
                    ]
                },
                'O-303': {
                    'carrier': 'Giao Hàng Nhanh (GHN)',
                    'tracking_code': 'GHN.VN.7721890',
                    'status': 'delivered',
                    'status_text': 'Đã giao thành công',
                    'current_location': 'Khách hàng đã ký nhận',
                    'shipper': 'Hoàng Minh Đức (0977.441.229)',
                    'delivery_date': '2 ngày trước',
                    'product_id': 'P-203',
                    'exchange_eligible': True,
                    'steps': [
                        {'time': '15:20 2 ngày trước', 'event': 'Giao hàng thành công - Người nhận ký nhận'},
                        {'time': '09:00 2 ngày trước', 'event': 'Shipper đang giao hàng'}
                    ]
                },
                'O-304': {
                    'carrier': 'Giao Hàng Nhanh (GHN)',
                    'tracking_code': 'GHN.VN.8821990',
                    'status': 'sorting_delayed',
                    'status_text': 'Nghẽn trạm phân loại Mega Sale > 48h',
                    'current_location': 'Kho Tổng BN Mega SOC (Bắc Ninh)',
                    'delayed_hours': 54,
                    'reason': 'Quá tải phân loại hàng hóa đợt Mega Sale sàn TMĐT',
                    'shipper': 'Chưa điều phối (Đang chờ phân tuyến trung chuyển)',
                    'estimated_delivery': 'Dự kiến 20/09/2026',
                    'eligible_voucher': 'VOUCHER_50K_COMPENSATION',
                    'voucher_code': 'SALE50K-BN-SOC',
                    'steps': [
                        {'time': '54 giờ trước', 'event': 'Đã nhập Kho Tổng BN Mega SOC - Đang chờ phân loại'},
                        {'time': '60 giờ trước', 'event': 'Rời kho lấy hàng Shop RetailOps'}
                    ]
                }
            }
            extra_shipments_file = ROOT / "data" / "mock_shipments.json"
            if extra_shipments_file.exists():
                try:
                    with open(extra_shipments_file, "r", encoding="utf-8") as f:
                        carriers.update(json.load(f))
                except Exception:
                    pass
            # Unknown per-account synthetic orders have no carrier record. Do not
            # fabricate a tracking code, carrier, location or delivery promise.
            shipment = carriers.get(oid) or {
                'carrier': None, 'tracking_code': None, 'status': 'unknown',
                'status_text': 'Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u h\u00e0nh tr\u00ecnh v\u1eadn chuy\u1ec3n',
                'current_location': None, 'shipper': None,
                'estimated_delivery': None, 'steps': []
            }
            self.shipment = shipment
            return {'order_id': oid, 'shipment': shipment, 'order_status': order['status'],
                    'source': 'synthetic-demo/shipments'}
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
            from retailops.core import ApiError
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
