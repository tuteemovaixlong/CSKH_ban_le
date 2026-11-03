"""W3.2 item 1 (W3.2-D2, W3.2-D4): one shared catalog of order-action reasons.

Isolated tests only: no model, network or real database.
"""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import retailops.order_reasons as order_reasons
from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.core import ROOT, ApiError
from retailops.order_reasons import ReasonCatalog, ReasonCatalogError, load_catalog, reason_catalog
from w32_harness import RoleHarness

CATALOG_FILE = ROOT / 'data' / 'order_action_reasons.json'
STAFF = {'principal_id': 'p-staff-a', 'role': 'staff', 'tenant_id': 'shop-a'}
CUSTOMER = {'principal_id': 'p-cust-1', 'role': 'customer', 'tenant_id': 'shop-a'}


def valid_document():
    return json.loads(CATALOG_FILE.read_text(encoding='utf-8'))


class CatalogFileTests(unittest.TestCase):
    def test_declares_the_v1_reasons_of_w3_2_d4(self):
        catalog = load_catalog()
        reasons = {e['code']: e for e in catalog.options(role='manager')}
        self.assertEqual(set(reasons), {
            'change_of_mind', 'fit_issue', 'defective_item', 'wrong_item', 'not_as_described',
            'ordered_by_mistake', 'no_longer_needed', 'delivery_failed', 'other'})
        self.assertEqual([c for c, e in reasons.items() if e['staff_only']], ['delivery_failed'])
        self.assertEqual(reasons['delivery_failed']['applies_to'], ['cancel'])
        self.assertEqual([c for c, e in reasons.items() if e['requires_text']], ['other'])
        for entry in reasons.values():
            self.assertTrue(entry['label'].strip())

    def test_old_w3_codes_still_resolve_with_a_label(self):
        catalog = reason_catalog()
        self.assertEqual(catalog.canonical('changed_mind'), 'change_of_mind')
        self.assertEqual(catalog.canonical('wrong_size'), 'fit_issue')
        self.assertEqual(catalog.label('wrong_size'), catalog.label('fit_issue'))
        self.assertEqual(catalog.label('something_unknown'), 'something_unknown')
        labels = catalog.labels()
        self.assertEqual(labels['changed_mind'], labels['change_of_mind'])

    def test_customer_view_hides_staff_only_reasons(self):
        catalog = reason_catalog()
        self.assertNotIn('delivery_failed', [e['code'] for e in catalog.options('cancel', role='customer')])
        self.assertIn('delivery_failed', [e['code'] for e in catalog.options('cancel', role='staff')])
        public = catalog.public('customer')
        self.assertTrue(all('staff_only' not in e for e in public['reasons']))
        self.assertTrue(all('staff_only' in e for e in catalog.public('manager')['reasons']))

    def test_shipped_file_is_the_only_reason_list_in_python_code(self):
        offenders = []
        for path in [*(ROOT / 'retailops').rglob('*.py'), ROOT / 'retailops_tools.py']:
            text = path.read_text(encoding='utf-8')
            if 'ORDER_ACTION_REASONS' in text or re.search(r'["\']wrong_size["\']\s*:', text) \
                    or re.search(r'["\']changed_mind["\']\s*:', text):
                offenders.append(path.name)
        self.assertEqual(offenders, [])


class CatalogValidationTests(unittest.TestCase):
    def broken(self, mutate):
        document = valid_document()
        mutate(document)
        with self.assertRaises(ReasonCatalogError):
            ReasonCatalog(document)

    def test_malformed_documents_fail_closed(self):
        cases = {
            'not an object': lambda d: d.clear() or d.update(reasons='x'),
            'no reasons': lambda d: d.update(reasons=[]),
            'bad version': lambda d: d.update(version='1'),
            'unknown top-level key': lambda d: d.update(extra=True),
            'duplicate code': lambda d: d['reasons'].append(copy.deepcopy(d['reasons'][0])),
            'bad code': lambda d: d['reasons'][0].update(code='Bad Code'),
            'empty label': lambda d: d['reasons'][0].update(label=' '),
            'unknown action': lambda d: d['reasons'][0].update(applies_to=['refund']),
            'no action': lambda d: d['reasons'][0].update(applies_to=[]),
            'flag not boolean': lambda d: d['reasons'][0].update(requires_text='yes'),
            'missing field': lambda d: d['reasons'][0].pop('staff_only'),
            'extra field': lambda d: d['reasons'][0].update(color='red'),
            'alias to nowhere': lambda d: d['aliases'].update(old_one='ghost'),
            'alias shadows a code': lambda d: d['aliases'].update(other='fit_issue'),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                self.broken(mutate)

    def test_every_request_type_needs_a_customer_selectable_reason(self):
        def only_staff_cancel(document):
            for reason in document['reasons']:
                if 'cancel' in reason['applies_to'] and not reason['staff_only']:
                    reason['applies_to'].remove('cancel')
                    if not reason['applies_to']:
                        reason['applies_to'] = ['return']
        self.broken(only_staff_cancel)

    def test_unreadable_or_invalid_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / 'missing.json'
            with self.assertRaises(ReasonCatalogError):
                load_catalog(missing)
            garbled = Path(temp) / 'garbled.json'
            garbled.write_text('{not json', encoding='utf-8')
            with self.assertRaises(ReasonCatalogError):
                load_catalog(garbled)

    def test_application_refuses_to_start_with_an_invalid_catalog(self):
        with tempfile.TemporaryDirectory() as temp:
            bad = Path(temp) / 'order_action_reasons.json'
            bad.write_text(json.dumps({'version': 1, 'reasons': []}), encoding='utf-8')
            store = BusinessStore(Path(temp) / 'business.sqlite3')
            order_reasons.reset_catalog_cache()
            self.addCleanup(order_reasons.reset_catalog_cache)
            with patch.object(order_reasons, 'CATALOG_PATH', bad), self.assertRaises(ReasonCatalogError):
                Application(store, {})
            order_reasons.reset_catalog_cache()
            Application(store, {})  # the shipped file is accepted again


class ServerReasonChecksTests(RoleHarness):
    def setUp(self):
        super().setUp()
        self.add_order('O-103', 'delivered', 'Xanh navy / L')
        self.add_order('O-104', 'pending', 'Trắng / S', product_id='P-101', name='Áo thun Essential', amount=299000)

    def post(self, order_id, action, reason_code, **extra):
        body = {'order_id': order_id, 'type': action, 'expected_order_version': 1, 'reason_code': reason_code, **extra}
        if action == 'exchange':
            body.setdefault('exchange_kind', 'same_variant')
        return self.request('POST', '/api/order-actions', body, cookie=self.cust1)

    def test_api_returns_the_catalog_by_role(self):
        status, customer = self.request('GET', '/api/order-action-reasons', cookie=self.cust1)
        self.assertEqual(status, 200)
        codes = [e['code'] for e in customer['reasons']]
        self.assertIn('other', codes)
        self.assertNotIn('delivery_failed', codes)
        self.assertEqual(customer['role'], 'customer')
        self.assertEqual(customer['text_max_length'], 500)
        status, staff = self.request('GET', '/api/order-action-reasons', cookie=self.staff_a)
        self.assertEqual(status, 200)
        delivery = next(e for e in staff['reasons'] if e['code'] == 'delivery_failed')
        self.assertEqual((delivery['staff_only'], delivery['applies_to']), (True, ['cancel']))
        status, _ = self.request('GET', '/api/order-action-reasons')
        self.assertIn(status, (401, 403))

    def test_reason_outside_the_catalog_is_rejected(self):
        status, body = self.post('O-104', 'cancel', 'because_i_said_so')
        self.assertEqual((status, body['error']), (400, 'invalid_reason_code'))

    def test_reason_for_the_wrong_request_type_is_rejected(self):
        for order, action, reason in [('O-104', 'cancel', 'fit_issue'), ('O-104', 'cancel', 'defective_item'),
                                      ('O-103', 'return', 'delivery_failed')]:
            with self.subTest(action=action, reason=reason):
                status, body = self.post(order, action, reason)
                self.assertEqual(status, 403 if reason == 'delivery_failed' else 400, body)
                self.assertIn(body['error'], ('reason_not_applicable', 'permission_denied'))

    def test_other_requires_a_description(self):
        status, body = self.post('O-104', 'cancel', 'other')
        self.assertEqual((status, body['error']), (400, 'reason_text_required'))
        status, body = self.post('O-104', 'cancel', 'other', reason_text='   ')
        self.assertEqual((status, body['error']), (400, 'reason_text_required'))
        status, body = self.post('O-104', 'cancel', 'other', reason_text='Đổi địa chỉ nhận hàng')
        self.assertEqual(status, 201, body)
        self.assertEqual(body['order_action']['reason_code'], 'other')
        self.assertEqual(body['order_action']['reason_text'], 'Đổi địa chỉ nhận hàng')

    def test_customer_cannot_use_delivery_failed_but_staff_can_for_cancel_only(self):
        status, body = self.post('O-104', 'cancel', 'delivery_failed')
        self.assertEqual((status, body['error']), (403, 'permission_denied'))
        with self.store_a.connection(write=True) as db:
            ok = self.store_a._create_order_action_request_in_tx(
                db, customer_id='C-001', order_id='O-104', action_type='cancel', expected_order_version=1,
                reason_code='delivery_failed', reason_text='Bưu tá gọi 3 lần không được', actor=STAFF,
                raised_by_role='staff', delivery_failure_attempts=3)
        self.assertEqual((ok['type'], ok['reason_code'], ok['reason_label']), ('cancel', 'delivery_failed', 'Giao hàng thất bại'))
        with self.store_a.connection(write=True) as db, self.assertRaises(ApiError) as caught:
            self.store_a._create_order_action_request_in_tx(
                db, customer_id='C-001', order_id='O-103', action_type='return', expected_order_version=1,
                reason_code='delivery_failed', reason_text='x', actor=STAFF, raised_by_role='staff')
        self.assertEqual(caught.exception.code, 'reason_not_applicable')

    def test_old_w3_codes_are_accepted_and_stored_under_the_catalog_code(self):
        status, body = self.post('O-103', 'exchange', 'wrong_size')
        self.assertEqual(status, 201, body)
        self.assertEqual(body['order_action']['reason_code'], 'fit_issue')
        status, body = self.post('O-104', 'cancel', 'changed_mind')
        self.assertEqual(status, 201, body)
        self.assertEqual(body['order_action']['reason_code'], 'change_of_mind')

    def test_stored_old_codes_display_with_the_catalog_label(self):
        self.post('O-103', 'exchange', 'defective_item')
        with self.store_a.connection(write=True) as db:
            db.execute("UPDATE order_action_requests SET reason_code='wrong_size', reason_text=NULL")
        status, body = self.request('GET', '/api/order-actions', cookie=self.cust1)
        self.assertEqual(status, 200)
        item = body['order_actions'][0]
        self.assertEqual((item['reason_code'], item['reason_label']), ('wrong_size', 'Không vừa'))

    def test_cancellation_facade_uses_the_same_catalog(self):
        proposal = {'order_id': 'O-104', 'order_version': 1}
        status, body = self.request('POST', '/api/cancellation-proposals',
                                    {**proposal, 'cancel_reason': 'other'}, cookie=self.cust1)
        self.assertEqual((status, body['error']), (400, 'invalid_proposal'))
        status, body = self.request('POST', '/api/cancellation-proposals',
                                    {**proposal, 'cancel_reason': 'delivery_failed'}, cookie=self.cust1)
        self.assertEqual((status, body['error']), (400, 'invalid_proposal'))
        status, body = self.request('POST', '/api/cancellation-proposals',
                                    {**proposal, 'cancel_reason': 'changed_mind'}, cookie=self.cust1)
        self.assertEqual(status, 201, body)
        self.assertEqual(body['reason'], 'change_of_mind')

    def test_staff_desk_reason_map_comes_from_the_catalog(self):
        status, escalation = self.post('O-104', 'cancel', 'no_longer_needed')
        self.assertEqual(status, 201, escalation)
        status, info = self.request('GET', f"/api/staff/cases/{escalation['case_id']}/orders", cookie=self.staff_a)
        self.assertEqual(status, 200, info)
        reasons = info['order_action_reasons']
        self.assertEqual(set(reasons), {'cancel', 'return', 'exchange'})
        self.assertEqual(reasons['exchange']['fit_issue'], 'Không vừa')
        self.assertIn('delivery_failed', reasons['cancel'])
        self.assertNotIn('delivery_failed', reasons['return'])


if __name__ == '__main__':
    unittest.main()
