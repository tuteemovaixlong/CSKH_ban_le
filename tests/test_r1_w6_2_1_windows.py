"""W6.2.1-D1: tool and direct HTTP enforce server-computed order windows."""
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

# Match the existing suites' support for both discovery and tests.<module> invocation.
_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from retailops.business.application import Application
from retailops_conversation import Catalog
from retailops_tools import BoundTools
from test_r1_w3_2_agent_loop import ScriptedModel, call, say
from test_r1_w3_2_exchange_service import ExchangeFixture

NOW = 1794412800.0


class WindowFixture(ExchangeFixture):
    def setUp(self):
        clock = patch('time.time', return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        super().setUp()

    def delivery(self, days, warranty=90):
        with self.store_a.connection(write=True) as db:
            db.execute('UPDATE orders SET delivered_at=? WHERE id=?',
                       (None if days is None else NOW - days * 86400, 'O-701'))
            db.execute('UPDATE products SET warranty_days=? WHERE id=?', (warranty, 'P-102'))

    def prepare(self, action, target=None, bound=None):
        bound = bound or BoundTools(self.store_a, Catalog(store=self.store_a), 'C-001', {}, {}, user_text='O-701')
        args = {'order_id': 'O-701', 'action_type': action}
        if target is not None:
            args['target_variant'] = target
        return bound, bound('prepare_order_action', args)

    def counts(self):
        with self.store_a.connection() as db:
            tables = ('order_action_requests', 'order_action_decisions', 'order_action_evidence',
                      'cases', 'conversations', 'handoff_episodes', 'business_events', 'integration_outbox')
            return {table: db.execute(f'SELECT COUNT(*) AS n FROM {table}').fetchone()['n'] for table in tables}

    def create(self, action, kind=None):
        body = {'order_id': 'O-701', 'type': action, 'expected_order_version': 1, 'reason_code': 'defective_item'}
        if kind:
            body['exchange_kind'] = kind
        if kind == 'other_variant':
            body['target_variant_id'] = self.variant_ids('O-701')['Đen · Size L']
        return self.request('POST', '/api/order-actions', body, cookie=self.cust1)


class ToolWindowTests(WindowFixture):
    def test_returns_in_window_and_expired_warranty_suggestion(self):
        for days, eligible, suggestion in ((2, True, None), (7, True, None), (7.01, False, 'exchange_same_variant_if_defective'), (30, False, 'exchange_same_variant_if_defective'), (100, False, None)):
            with self.subTest(days=days):
                self.delivery(days)
                bound, result = self.prepare('return')
                self.assertEqual(result['eligible'], eligible)
                self.assertEqual(result.get('suggested_action'), suggestion)
                self.assertEqual(bound.prepared_order_action is not None, eligible)
                if not eligible:
                    self.assertEqual(result['ineligible_reason']['code'], 'return_window_expired')

    def test_exchange_windows_and_product_specific_warranty(self):
        for days, warranty, target, allowed, code in (
            (10, 90, 'size L', ['other_variant', 'same_variant'], None),
            (15, 90, 'size L', ['other_variant', 'same_variant'], None),
            (15.01, 90, 'size L', ['same_variant'], 'size_exchange_window_expired'),
            (30, 90, None, ['same_variant'], None),
            (100, 90, None, [], 'exchange_window_expired'),
            (3, 0, None, ['other_variant'], None),
            (30, 0, None, [], 'exchange_window_expired'),
            (100, 365, None, ['same_variant'], None),
            (100, 365, 'size L', ['same_variant'], 'size_exchange_window_expired'),
        ):
            with self.subTest(days=days, warranty=warranty, target=target):
                self.delivery(days, warranty)
                bound, result = self.prepare('exchange', target)
                self.assertEqual(result.get('allowed_exchange_kinds'), allowed)
                self.assertEqual(result['eligible'], code is None)
                self.assertEqual(bound.prepared_order_action is not None, code is None)
                self.assertEqual((result.get('ineligible_reason') or {}).get('code'), code)

    def test_missing_delivery_and_non_delivered_status(self):
        self.delivery(None, 0)
        for action in ('return', 'exchange'):
            with self.subTest(action=action):
                _, result = self.prepare(action)
                self.assertTrue(result['eligible'])
                self.assertIs(result.get('window_unknown'), True)
                if action == 'exchange':
                    self.assertEqual(result['allowed_exchange_kinds'], ['other_variant', 'same_variant'])
        with self.store_a.connection(write=True) as db:
            db.execute("UPDATE orders SET status='pending' WHERE id='O-701'")
        bound, result = self.prepare('exchange')
        self.assertFalse(result['eligible'])
        self.assertIsNone(bound.prepared_order_action)
        self.assertEqual(result['ineligible_reason']['code'], 'order_not_delivered')
        self.assertEqual(result['allowed_exchange_kinds'], [])

    def test_expired_prepare_clears_an_earlier_form(self):
        self.delivery(1)
        bound, _ = self.prepare('return')
        self.assertIsNotNone(bound.prepared_order_action)
        self.delivery(10)
        _, result = self.prepare('return', bound=bound)
        self.assertFalse(result['eligible'])
        self.assertIsNone(bound.prepared_order_action)

    def test_application_transmits_allowed_kinds_and_does_not_open_expired_return(self):
        self.delivery(30)
        for action in ('return', 'exchange'):
            with self.subTest(action=action):
                model = ScriptedModel(call(('prepare_order_action', {'order_id': 'O-701', 'action_type': action})), say('Em đã kiểm tra điều kiện của đơn.'))
                app = Application(self.store_a, {}, infer=model)
                cid = self.store_a.new_conversation('C-001')['conversation_id']
                result = app.chat('C-001', {'text': 'Kiểm tra ' + action + ' O-701', 'conversation_id': cid, 'request_id': 'w621-window-request-' + action})
                if action == 'return':
                    self.assertEqual(result['action'], 'reply')
                    self.assertNotIn('order_action', result)
                else:
                    self.assertEqual(result['action'], 'choose_order_action_reason')
                    self.assertEqual(result['allowed_exchange_kinds'], ['same_variant'])


class ApiWindowTests(WindowFixture):
    def assert_denied(self, days, warranty, action, kind, code):
        self.delivery(days, warranty)
        before = self.counts()
        status, result = self.create(action, kind)
        self.assertEqual((status, result.get('error')), (409, code))
        self.assertEqual(self.counts(), before)
        self.assertRegex(result['message'], r'[à-ỹ]')

    def test_direct_expired_return_writes_nothing(self):
        self.assert_denied(8, 90, 'return', None, 'return_window_expired')

    def test_direct_expired_size_exchange_writes_nothing(self):
        self.assert_denied(16, 90, 'exchange', 'other_variant', 'size_exchange_window_expired')

    def test_direct_expired_warranty_writes_nothing(self):
        self.assert_denied(91, 90, 'exchange', 'same_variant', 'warranty_expired')

    def test_direct_zero_warranty_writes_nothing(self):
        self.assert_denied(1, 0, 'exchange', 'same_variant', 'warranty_expired')

    def assert_creates(self, days, warranty, action, kind=None):
        self.delivery(days, warranty)
        status, result = self.create(action, kind)
        self.assertEqual(status, 201, result)

    def test_in_window_return(self):
        self.assert_creates(1, 90, 'return')

    def test_in_window_size_exchange(self):
        self.assert_creates(10, 90, 'exchange', 'other_variant')

    def test_product_long_warranty(self):
        self.assert_creates(100, 365, 'exchange', 'same_variant')

    def test_missing_delivery_return(self):
        self.assert_creates(None, 0, 'return')

    def test_missing_delivery_exchange(self):
        self.assert_creates(None, 0, 'exchange', 'same_variant')

    def test_already_open_request_can_be_approved_after_window_expires(self):
        self.delivery(1)
        status, created = self.create('return')
        self.assertEqual(status, 201, created)
        self.delivery(120)
        case_id, request_id = created['case_id'], created['order_action_request_id']
        self.assertEqual(self.request('POST', '/api/staff/cases/' + case_id + '/claim', {}, cookie=self.mgr_a)[0], 200)
        status, result = self.request('POST', f'/api/order-actions/{request_id}/approve', {'version': 2}, cookie=self.mgr_a)
        self.assertEqual((status, result.get('status')), (200, 'approved'))
