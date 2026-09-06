"""Read-only tools bound to the authenticated customer by the application."""
from datetime import datetime, timedelta, timezone

from retailops_conversation import normalize


class BoundTools:
    def __init__(self, store, catalog, customer, snapshot, identity):
        self.store, self.catalog, self.customer = store, catalog, customer
        self.context = {k: snapshot[k] for k in ('order_id', 'product_id')}
        self.identity = identity
        self.versions = {}
        self.cancel_order = None

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
            order = self.read_order(args['order_id'])
            eligible = order['status'] == 'pending'
            self.cancel_order = order if eligible else None
            return {'order': order, 'eligible': eligible, 'transaction_performed': False,
                    'next_step': 'User must select a reason and press the separate confirmation button.' if eligible
                    else 'Order cannot be cancelled in its current state.'}
        if name == 'get_runtime_info':
            return {k: self.identity.get(k) for k in ('name', 'digest', 'details', 'ollama_version', 'agent_protocol')}
        if name == 'get_current_time':
            now = datetime.now(timezone(timedelta(hours=7)))
            return {'date': now.date().isoformat(), 'time': now.isoformat(timespec='seconds'),
                    'timezone': 'Asia/Ho_Chi_Minh (UTC+07:00)', 'source': 'backend_clock'}
        return {'error': 'tool_not_allowed', 'message': 'No action performed.'}
