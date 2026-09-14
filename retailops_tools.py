"""Read-only tools bound to the authenticated customer by the application."""
from datetime import datetime, timedelta, timezone

from retailops_conversation import normalize
from retailops.knowledge.tool import KnowledgeTool


class BoundTools:
    def __init__(self, store, catalog, customer, snapshot, identity, *, can_cancel=True):
        self.store, self.catalog, self.customer = store, catalog, customer
        self.context = {k: snapshot[k] for k in ('order_id', 'product_id')}
        self.identity = identity
        self.versions = {}
        self.cancel_order = None
        self.can_cancel = can_cancel
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
            return {'orders': [self.read_order(o['id'], focus=False) for o in orders[:10]],
                    'truncated': len(orders) > 10}
        if name == 'get_order':
            return {'order': self.read_order(args['order_id'])}
        if name == 'search_products':
            query = normalize(args['query']).strip()
            products = [p for p in self.catalog.products.values() if query in normalize(
                ' '.join([p['id'], p['name'], p['category']] + p['aliases']))]
            if len(products) == 1:
                if self.context['product_id'] != products[0]['id']:
                    self.context['order_id'] = None
                self.context['product_id'] = products[0]['id']
            return {'products': products[:10], 'source': self.catalog.source,
                    'note': 'Null or absent attributes are unknown; listed variants do not imply stock.'}
        if name == 'get_product':
            product = self.catalog.products.get(args['product_id'])
            if product is None:
                return {'error': 'product_not_found', 'message': 'No matching product in the catalog.'}
            if self.context['product_id'] != product['id']:
                self.context['order_id'] = None
            self.context['product_id'] = product['id']
            return {'product': product, 'source': self.catalog.source,
                    'note': 'Null or absent attributes are unknown; listed variants do not imply stock.'}
        if name == 'get_context':
            oid = self.context['order_id']
            order = self.read_order(oid) if oid else None
            return {'order': order, 'product': self.catalog.products.get(self.context['product_id']),
                    'note': 'These are current focused records, not permission to change them.'}
        if name == 'prepare_cancellation':
            if not self.can_cancel:
                return {'error': 'permission_denied', 'message': 'This account can view orders but cannot request cancellation.'}
            order = self.read_order(args['order_id'])
            eligible = order['status'] == 'pending'
            self.cancel_order = order if eligible else None
            return {'order': order, 'eligible': eligible, 'transaction_performed': False,
                    'next_step': 'User must select a reason and press the separate confirmation button.' if eligible
                    else 'Order cannot be cancelled in its current state.'}
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
                }
            }
            shipment = carriers.get(oid, {
                'carrier': 'Giao Hàng Tiết Kiệm (GHTK)',
                'tracking_code': f'GHTK.VN.{oid.replace("-", "")}99',
                'status': 'processing',
                'status_text': 'Đang chuẩn bị kiện hàng',
                'current_location': 'Kho tổng RetailOps',
                'shipper': 'Chưa phân công',
                'estimated_delivery': '2-3 ngày làm việc',
                'steps': [{'time': 'Vừa xong', 'event': 'Đơn hàng đang được kiểm đếm và đóng gói'}]
            })
            self.shipment = shipment
            return {'order_id': oid, 'shipment': shipment, 'order_status': order['status']}
        if name == 'check_inventory':
            pid = args['product_id']
            size = args['size'].upper().strip()
            color = args['color'].strip()
            product = self.catalog.products.get(pid)
            if not product:
                return {'error': 'product_not_found', 'message': f'Sản phẩm {pid} không tồn tại trong kho.'}
            stock_map = {
                'P-101': {'S': 5, 'M': 12, 'L': 8, 'XL': 0},
                'P-102': {'S': 0, 'M': 4, 'L': 15, 'XL': 3},
                'P-202': {'S': 20, 'M': 18, 'L': 25, 'XL': 10},
            }
            available = stock_map.get(pid, {}).get(size, 6)
            return {
                'product_id': pid, 'product_name': product.get('name'),
                'size': size, 'color': color,
                'stock': available,
                'in_stock': available > 0,
                'status_text': f'Còn {available} sản phẩm trong kho' if available > 0 else 'Tạm thời hết size này'
            }
        if name == 'request_human_support':
            reason = args['reason'].strip()
            res = {
                'status': 'escalated_to_human',
                'reason': reason,
                'support_rep': 'Nguyễn Mai Anh (Chuyên viên CSKH)',
                'queue': 'priority_vip',
                'estimated_wait': '30 giây',
                'message': f'Đã chuyển yêu cầu hỗ trợ trực tiếp cho nhân viên: "{reason}". Chuyên viên CSKH đang vào phòng chat để hỗ trợ bạn.'
            }
            self.human_support = res
            return res
        return {'error': 'tool_not_allowed', 'message': 'No action performed.'}
