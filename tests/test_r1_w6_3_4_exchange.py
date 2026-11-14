"""W6.3.4-D2: use canonical simulated orders, never a live store."""
import unittest

from retailops.business.variants import match_variants
from retailops.core import ApiError
from retailops_tools import BoundTools
from scripts import run_agent_scenarios as runner


class MultiVariantExchangeTests(unittest.TestCase):
    def setUp(self):
        self.world = runner.World(runner.load_dataset('evals/suites/S06.jsonl')[0], runner.ScriptedGateway())
        self.addCleanup(self.world.close)
        self.store = self.world.store

    def order(self, external):
        with self.store.connection() as db:
            return dict(db.execute('SELECT * FROM orders WHERE external_order_id = ?', (external,)).fetchone())

    def options(self, external, staff=False):
        order = self.order(external)
        if not staff:
            return self.store.exchange_options(order['customer_id'], order['id'])
        cid = self.store.new_conversation(order['customer_id'])['conversation_id']
        case = self.store.request_human_handoff(order['customer_id'], cid, reason_code='customer_requested')
        return self.store.case_exchange_options(case['case_id'], order['id'])

    def test_customer_and_staff_can_target_both_held_variants(self):
        for staff in (False, True):
            variants = self.options('SIM-O-00079', staff)['variants']
            held = [v for v in variants if v['is_current']]
            self.assertEqual({v['label'] for v in held}, {'Trắng · Size L', 'Đen · Size L'})
            for variant in held:
                with self.subTest(staff=staff, label=variant['label']):
                    self.assertIs(variant.get('can_target'), True)

    def test_quantity_two_is_still_one_distinct_variant(self):
        for staff in (False, True):
            variants = self.options('SIM-O-00105', staff)['variants']
            held = [v for v in variants if v['is_current']]
            self.assertEqual([v['label'] for v in held], ['Đen · Size L'])
            self.assertIs(held[0].get('can_target'), False)
            self.assertTrue(all(v.get('can_target') for v in variants if not v['is_current']))

    def test_match_full_label_and_attributes_to_a_held_target(self):
        variants = self.options('SIM-O-00079')['variants']
        for text in ('Đen · Size L', 'màu đen size L'):
            with self.subTest(text=text):
                self.assertEqual([v['label'] for v in match_variants(variants, text)], ['Đen · Size L'])
        self.assertEqual(match_variants(self.options('SIM-O-00105')['variants'], 'Đen · Size L'), [])

    def test_prepare_opens_other_variant_with_target_and_flags(self):
        order = self.order('SIM-O-00079')
        tools = BoundTools(self.store, self.world.app.catalog, order['customer_id'], {}, {})
        response = tools('prepare_order_action', {'order_id': order['id'], 'action_type': 'exchange',
                                                'target_variant': 'Đen · Size L'})
        prepared = tools.prepared_order_action
        self.assertEqual(prepared['exchange_kind'], 'other_variant')
        self.assertEqual([v['label'] for v in response['exchange']['matched_variants']], ['Đen · Size L'])
        held = [v for v in response['exchange']['variants'] if v['is_current']]
        self.assertTrue(all(v.get('can_target') is True for v in held))
        self.assertEqual(prepared['target_variant_id'], response['exchange']['matched_variants'][0]['id'])

    def test_server_accepts_held_target_for_multiple_variants(self):
        order = self.order('SIM-O-00079')
        target = next(v for v in self.options('SIM-O-00079')['variants'] if v['label'] == 'Đen · Size L')
        result = self.store.create_order_action_request(order['customer_id'], {
            'order_id': order['id'], 'type': 'exchange', 'exchange_kind': 'other_variant',
            'target_variant_id': target['id'], 'expected_order_version': order['version'],
            'reason_code': 'change_of_mind'})
        self.assertEqual(result['order_action']['target_variant_label'], 'Đen · Size L')

    def test_server_rejects_held_target_for_single_variant(self):
        order = self.order('SIM-O-00105')
        target = next(v for v in self.options('SIM-O-00105')['variants'] if v['is_current'])
        with self.assertRaises(ApiError) as caught:
            self.store.create_order_action_request(order['customer_id'], {
                'order_id': order['id'], 'type': 'exchange', 'exchange_kind': 'other_variant',
                'target_variant_id': target['id'], 'expected_order_version': order['version'],
                'reason_code': 'change_of_mind'})
        self.assertEqual((caught.exception.status, caught.exception.code), (400, 'target_is_current_variant'))


if __name__ == '__main__':
    unittest.main()
