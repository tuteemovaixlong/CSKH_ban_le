"""W3.2 item 3 (W3.2-D1, W3.2-D5): general exchange in the service and the HTTP API.

Isolated: SQLite tenants behind the real PublicWeb router, no model, no network.
"""
import json
import time
import unittest

from retailops.business.store import BusinessStore
from w32_harness import RoleHarness

CAT = 'Đen · Size M · Số lượng 1'  # how seeded orders write their variant


class ExchangeFixture(RoleHarness):
    def setUp(self):
        super().setUp()
        self.add_order('O-701', 'delivered', CAT)                                  # P-102, current = Đen · Size M
        self.add_order('O-704', 'delivered', 'Xanh navy / L')                      # P-102, no catalog match
        self.add_order('O-705', 'pending', 'Đen / L')                              # P-102, not delivered
        self.add_order('O-702', 'delivered', 'Đen / 41', product_id='P-603', name='Giày lười da bò cao cấp')
        self.add_order('O-703', 'delivered', 'Đen / L', product_id=None, name='Sản phẩm không có trong danh mục')
        self.add_order('O-706', 'delivered', 'Trắng / M', product_id='P-103', name='Áo Sơ Mi Oxford Dài Tay')

    def options(self, order_id, cookie=None):
        status, body = self.request('GET', f'/api/orders/{order_id}/exchange-options', cookie=cookie or self.cust1)
        self.assertEqual(status, 200, body)
        return body

    def variant_ids(self, order_id):
        return {v['label']: v['id'] for v in self.options(order_id)['variants']}

    def exchange(self, order_id, kind, target=None, reason='change_of_mind', cookie=None, **extra):
        body = {'order_id': order_id, 'type': 'exchange', 'exchange_kind': kind, 'expected_order_version': 1,
                'reason_code': reason, **extra}
        if target is not None:
            body['target_variant_id'] = target
        return self.request('POST', '/api/order-actions', body, cookie=cookie or self.cust1)

    def rows(self):
        with self.store_a.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM order_action_requests ORDER BY created_at')]


class VariantTextTests(unittest.TestCase):
    def test_order_variant_text_is_compared_by_normalized_size_and_color(self):
        attrs = BusinessStore._variant_attributes
        self.assertEqual(attrs('Trắng · Size M · Số lượng 1'), ('m', 'trang'))
        self.assertEqual(attrs('Đen / L'), ('l', 'den'))
        self.assertEqual(attrs('Xanh Nhạt · Size XL'), ('xl', 'xanh nhat'))
        self.assertEqual(attrs('M'), ('m', None))
        self.assertEqual(attrs(''), (None, None))
        self.assertEqual(BusinessStore._stock_status(None), 'unknown')
        self.assertEqual(BusinessStore._stock_status(0), 'out_of_stock')
        self.assertEqual(BusinessStore._stock_status(3), 'in_stock')

    def test_notices_name_the_exchange_kind_without_the_old_labels(self):
        notice = BusinessStore._order_action_notice_text
        self.assertIn('đổi sang biến thể khác', notice('exchange', 'other_variant', 'O-1', 'approved'))
        self.assertIn('đổi cùng biến thể', notice('exchange', 'same_variant', 'O-1', 'approved'))
        for kind in ('other_variant', 'same_variant'):
            self.assertNotIn('đổi size', notice('exchange', kind, 'O-1', 'under_review'))
            self.assertNotIn('đổi 1-1', notice('exchange', kind, 'O-1', 'under_review'))


class ExchangeOptionsTests(ExchangeFixture):
    def test_customer_sees_the_product_variants_with_stock_status_and_the_current_one_marked(self):
        data = self.options('O-701')
        self.assertEqual((data['order_id'], data['product_id'], data['current_variant_label']), ('O-701', 'P-102', CAT))
        by_label = {v['label']: v for v in data['variants']}
        self.assertEqual(set(by_label), {'Đen · Size S', 'Đen · Size M', 'Đen · Size L', 'Đen · Size XL'})
        self.assertEqual({k: v['stock_status'] for k, v in by_label.items()},
                         {'Đen · Size S': 'out_of_stock', 'Đen · Size M': 'in_stock',
                          'Đen · Size L': 'in_stock', 'Đen · Size XL': 'in_stock'})
        self.assertEqual([k for k, v in by_label.items() if v['is_current']], ['Đen · Size M'])
        self.assertTrue(all('stock' not in v for v in data['variants']))  # customers get a status, not a count

    def test_unknown_stock_is_reported_as_unknown(self):
        ids = self.variant_ids('O-701')
        with self.store_a.connection(write=True) as db:
            db.execute('UPDATE product_variants SET stock = NULL WHERE id = ?', (ids['Đen · Size L'],))
        by_label = {v['label']: v for v in self.options('O-701')['variants']}
        self.assertEqual(by_label['Đen · Size L']['stock_status'], 'unknown')

    def test_a_pending_order_still_lists_its_variants(self):
        self.assertEqual(len(self.options('O-705')['variants']), 4)

    def test_another_customers_order_is_not_visible(self):
        status, body = self.request('GET', '/api/orders/O-701/exchange-options', cookie=self.cust2)
        self.assertEqual((status, body['error']), (404, 'order_not_found'))
        status, body = self.request('GET', '/api/orders/O-701/exchange-options', cookie=self.mgr_a)
        self.assertEqual((status, body['error']), (404, 'order_not_found'))
        status, _ = self.request('GET', '/api/orders/O-701/exchange-options')
        self.assertIn(status, (401, 403))

    def test_structured_order_items_decide_the_current_variant(self):
        ids = self.variant_ids('O-704')
        with self.store_a.connection(write=True) as db:
            db.execute(
                """INSERT INTO order_items(id, tenant_id, order_id, product_id, variant_id, product_title,
                       variant_name, quantity, unit_price, subtotal, created_at)
                   VALUES ('it-1', 'shop-a', 'O-704', 'P-102', ?, 'Áo khoác', 'Đen · Size XL', 1, 1, 1, 1.0)""",
                (ids['Đen · Size XL'],))
        current = [v['label'] for v in self.options('O-704')['variants'] if v['is_current']]
        self.assertEqual(current, ['Đen · Size XL'])

    def test_an_order_without_a_catalog_product_has_no_options(self):
        data = self.options('O-703')
        self.assertEqual((data['product_id'], data['variants']), (None, []))

    def test_color_variants_of_a_footwear_order_are_listed(self):
        by_label = {v['label']: v for v in self.options('O-702')['variants']}
        self.assertEqual([k for k, v in by_label.items() if v['is_current']], ['Đen · Size 41'])
        self.assertIn('Nâu · Size 41', by_label)

    def test_staff_options_follow_the_case_and_include_counts(self):
        status, created = self.request('POST', '/api/order-actions', {
            'order_id': 'O-705', 'type': 'cancel', 'expected_order_version': 1, 'reason_code': 'change_of_mind'},
            cookie=self.cust1)
        self.assertEqual(status, 201, created)
        case_id = created['case_id']
        path = f'/api/staff/cases/{case_id}/orders/O-701/exchange-options'
        for cookie in (self.staff_a, self.mgr_a):
            status, data = self.request('GET', path, cookie=cookie)
            self.assertEqual(status, 200, data)
            by_label = {v['label']: v for v in data['variants']}
            self.assertEqual(by_label['Đen · Size M']['stock'], 4)
            self.assertEqual(by_label['Đen · Size S']['stock_status'], 'out_of_stock')
            self.assertEqual((data['case_id'], data['read_only']), (case_id, False))
        self.assertEqual(self.request('GET', path, cookie=self.cust1)[0], 403)
        self.assertIn(self.request('GET', path, cookie=self.staff_b)[0], (403, 404))
        status, body = self.request('GET', f'/api/staff/cases/{case_id}/orders/O-202/exchange-options', cookie=self.staff_a)
        self.assertEqual((status, body['error']), (404, 'order_not_found'))  # another customer's order


class ExchangeRequestTests(ExchangeFixture):
    def test_exchange_to_another_variant_stores_target_snapshot_audit_and_outbox(self):
        ids = self.variant_ids('O-701')
        status, body = self.exchange('O-701', 'other_variant', ids['Đen · Size L'])
        self.assertEqual(status, 201, body)
        oa = body['order_action']
        self.assertEqual((oa['exchange_kind'], oa['target_variant_id'], oa['target_variant_label']),
                         ('other_variant', ids['Đen · Size L'], 'Đen · Size L'))
        self.assertEqual((oa['current_variant_label'], oa['target_stock_status']), (CAT, 'in_stock'))
        self.assertEqual(oa['target_stock'], 15)
        with self.store_a.connection() as db:
            outbox = [json.loads(r['payload_json']) for r in db.execute(
                "SELECT payload_json FROM integration_outbox WHERE event_type = 'exchange_requested'")]
            event = [json.loads(r['payload']) for r in db.execute(
                "SELECT payload FROM business_events WHERE kind = 'order_action_requested'")]
        self.assertEqual((outbox[0]['exchange_kind'], outbox[0]['target_variant_id']), ('other_variant', ids['Đen · Size L']))
        self.assertEqual(event[-1]['target_variant_id'], ids['Đen · Size L'])
        with self.store_a.connection() as db:
            comment = db.execute('SELECT comment FROM handoff_episodes').fetchone()['comment']
        self.assertIn('Đen · Size L', comment)

    def test_a_color_change_uses_the_same_flow(self):
        ids = self.variant_ids('O-702')
        status, body = self.exchange('O-702', 'other_variant', ids['Nâu · Size 41'])
        self.assertEqual(status, 201, body)
        self.assertEqual(body['order_action']['target_variant_label'], 'Nâu · Size 41')

    def test_an_out_of_stock_or_unknown_stock_target_is_still_accepted(self):
        ids = self.variant_ids('O-701')
        status, body = self.exchange('O-701', 'other_variant', ids['Đen · Size S'])  # stock 0
        self.assertEqual(status, 201, body)
        self.assertEqual((body['order_action']['target_stock_status'], body['order_action']['target_stock']), ('out_of_stock', 0))
        ids = self.variant_ids('O-704')
        with self.store_a.connection(write=True) as db:
            db.execute('UPDATE product_variants SET stock = NULL WHERE id = ?', (ids['Đen · Size XL'],))
        status, body = self.exchange('O-704', 'other_variant', ids['Đen · Size XL'])
        self.assertEqual(status, 201, body)
        self.assertEqual(body['order_action']['target_stock_status'], 'unknown')

    def test_same_variant_exchange_needs_no_target(self):
        status, body = self.exchange('O-701', 'same_variant', reason='defective_item')
        self.assertEqual(status, 201, body)
        oa = body['order_action']
        self.assertEqual((oa['exchange_kind'], oa['target_variant_id'], oa['target_variant_label']), ('same_variant', None, None))
        self.assertIsNone(oa['target_stock_status'])

    def test_every_malformed_target_is_a_400_and_creates_nothing(self):
        mine = self.variant_ids('O-701')
        other_product = self.variant_ids('O-706')  # P-103
        cases = [
            ('missing target', 'other_variant', None, 'target_variant_required'),
            ('blank target', 'other_variant', '   ', 'target_variant_required'),
            ('variant of another product', 'other_variant', next(iter(other_product.values())), 'invalid_target_variant'),
            ('unknown variant', 'other_variant', 'P-102-XXL-Đen', 'invalid_target_variant'),
            ('the variant the order holds', 'other_variant', mine['Đen · Size M'], 'target_is_current_variant'),
            ('oversized id', 'other_variant', 'V' * 129, 'invalid_target_variant'),
            ('same_variant with a target', 'same_variant', mine['Đen · Size L'], 'target_variant_not_allowed'),
            ('W3 kind size', 'size', None, 'invalid_exchange_kind'),
            ('W3 kind one_to_one', 'one_to_one', None, 'invalid_exchange_kind'),
        ]
        for name, kind, target, code in cases:
            with self.subTest(name):
                status, body = self.exchange('O-701', kind, target)
                self.assertEqual((status, body['error']), (400, code), body)
        self.assertEqual(self.rows(), [])

    def test_only_an_exchange_may_carry_a_kind_or_a_target(self):
        mine = self.variant_ids('O-701')
        for action, order in (('return', 'O-701'), ('cancel', 'O-705')):
            status, body = self.request('POST', '/api/order-actions', {
                'order_id': order, 'type': action, 'expected_order_version': 1, 'reason_code': 'change_of_mind',
                'target_variant_id': mine['Đen · Size L']}, cookie=self.cust1)
            self.assertEqual((status, body['error']), (400, 'target_variant_not_allowed'), (action, body))
        self.assertEqual(self.rows(), [])

    def test_variant_matching_uses_the_order_text_when_there_are_no_items(self):
        ids = self.variant_ids('O-704')  # "Xanh navy / L": no catalog variant has that color
        status, body = self.exchange('O-704', 'other_variant', ids['Đen · Size L'])
        self.assertEqual(status, 201, body)

    def test_an_order_without_a_catalog_product_can_only_do_a_same_variant_exchange(self):
        status, body = self.exchange('O-703', 'other_variant', 'P-102-L-Đen')
        self.assertEqual((status, body['error']), (409, 'order_product_unknown'))
        self.assertEqual(self.exchange('O-703', 'same_variant', reason='wrong_item')[0], 201)

    def test_eligibility_and_conflicts_still_apply(self):
        ids = self.variant_ids('O-705')
        status, body = self.exchange('O-705', 'other_variant', ids['Đen · Size XL'])
        self.assertEqual((status, body['error']), (409, 'order_not_eligible'))  # not delivered
        mine = self.variant_ids('O-701')
        self.assertEqual(self.exchange('O-701', 'other_variant', mine['Đen · Size L'])[0], 201)
        status, body = self.exchange('O-701', 'other_variant', mine['Đen · Size XL'])
        self.assertEqual((status, body['error']), (409, 'order_action_conflict'))
        status, body = self.exchange('O-202', 'other_variant', mine['Đen · Size L'])
        self.assertEqual((status, body['error']), (404, 'order_not_found'))  # another customer's order

    def test_reason_rules_still_apply_to_exchanges(self):
        mine = self.variant_ids('O-701')
        status, body = self.exchange('O-701', 'other_variant', mine['Đen · Size L'], reason='delivery_failed')
        self.assertEqual((status, body['error']), (403, 'permission_denied'))
        status, body = self.exchange('O-701', 'other_variant', mine['Đen · Size L'], reason='other')
        self.assertEqual((status, body['error']), (400, 'reason_text_required'))
        status, body = self.exchange('O-701', 'other_variant', mine['Đen · Size L'], reason='other', reason_text='Muốn size lớn hơn')
        self.assertEqual(status, 201, body)

    def test_staff_creates_the_same_request_on_the_customers_consent(self):
        status, created = self.request('POST', '/api/order-actions', {
            'order_id': 'O-705', 'type': 'cancel', 'expected_order_version': 1, 'reason_code': 'change_of_mind'},
            cookie=self.cust1)
        self.assertEqual(status, 201, created)
        case_id = created['case_id']
        with self.store_a.connection(write=True) as db:
            turn_id = db.execute(
                """INSERT INTO agent_turns(conversation_id, customer_id, request_id, input_hash, messages, result, created_at)
                   VALUES (?, 'C-001', 'req-consent-0001', 'h', ?, ?, ?) RETURNING id""",
                (created['conversation_id'], json.dumps([{'role': 'user', 'content': 'ok shop đổi giúp mình'}]),
                 json.dumps({'author': 'customer'}), time.time())).fetchone()['id']
        mine = self.variant_ids('O-701')
        path = f'/api/staff/cases/{case_id}/order-actions'
        body = {'order_id': 'O-701', 'expected_order_version': 1, 'type': 'exchange', 'exchange_kind': 'other_variant',
                'reason_code': 'change_of_mind', 'consent_turn_id': turn_id}
        for bad in ({}, {'target_variant_id': 'P-101-M-Trắng'}, {'target_variant_id': mine['Đen · Size M']}):
            status, resp = self.request('POST', path, {**body, **bad}, cookie=self.mgr_a)
            self.assertEqual(status, 400, resp)
        status, resp = self.request('POST', path, {**body, 'target_variant_id': mine['Đen · Size L']}, cookie=self.mgr_a)
        self.assertEqual(status, 201, resp)
        self.assertEqual(resp['order_action']['raised_by_role'], 'customer')
        self.assertEqual(resp['order_action']['target_variant_label'], 'Đen · Size L')

    def test_the_panel_shows_current_to_target_with_stock(self):
        ids = self.variant_ids('O-701')
        status, created = self.exchange('O-701', 'other_variant', ids['Đen · Size S'])
        self.assertEqual(status, 201, created)
        status, info = self.request('GET', f"/api/staff/cases/{created['case_id']}/orders", cookie=self.staff_a)
        self.assertEqual(status, 200, info)
        order = next(o for o in info['orders'] if o['id'] == 'O-701')
        open_action = order['open_order_action']
        self.assertEqual((open_action['current_variant_label'], open_action['target_variant_label'],
                          open_action['target_stock_status']), (CAT, 'Đen · Size S', 'out_of_stock'))
        status, listing = self.request('GET', f"/api/staff/cases/{created['case_id']}/order-actions", cookie=self.staff_a)
        item = listing['order_actions'][0]
        self.assertEqual((item['exchange_kind'], item['target_variant_id']), ('other_variant', ids['Đen · Size S']))

    def test_stock_shown_in_the_panel_is_live_not_a_snapshot(self):
        ids = self.variant_ids('O-701')
        status, created = self.exchange('O-701', 'other_variant', ids['Đen · Size L'])
        with self.store_a.connection(write=True) as db:
            db.execute('UPDATE product_variants SET stock = 0 WHERE id = ?', (ids['Đen · Size L'],))
        listing = self.request('GET', f"/api/staff/cases/{created['case_id']}/order-actions", cookie=self.staff_a)[1]
        self.assertEqual(listing['order_actions'][0]['target_stock_status'], 'out_of_stock')
        self.assertEqual(listing['order_actions'][0]['target_variant_label'], 'Đen · Size L')  # the label stays as chosen


if __name__ == '__main__':
    unittest.main()
