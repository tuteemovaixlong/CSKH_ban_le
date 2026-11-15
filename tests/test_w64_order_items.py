"""W6.4.0 row 1: all model-facing order tools expose only persisted line items."""
import json
import unittest

from retailops_conversation import Catalog
from retailops_tools import BoundTools
from retailops.workflow.case_assist import CaseAssistBoundTools as CaseTools
from retailops.workflow.compaction import compact_tool_result, TOOL_RESULT_MAX_CHARS
from scripts import run_agent_scenarios as runner


class OrderItemsTests(unittest.TestCase):
    def setUp(self):
        self.world = runner.World({'fixture': 'standard', 'customer': 'SIM-C-0057'}, runner.ScriptedGateway())
        self.addCleanup(self.world.close)
        self.store = self.world.store
        self.tools = BoundTools(self.store, Catalog(self.store), self.world.customer_id,
                                {'id': self.world.conversation}, {})

    def test_all_six_model_tools_preserve_the_two_persisted_items(self):
        expected = [
            {'product_id': 'P-601', 'name': 'Áo sơ mi lụa công sở', 'variant': 'Trắng · Size M',
             'quantity': 1, 'unit_price': 450000, 'subtotal': 450000},
            {'product_id': 'P-602', 'name': 'Quần tây đen hàn quốc', 'variant': 'Đen · Size M',
             'quantity': 2, 'unit_price': 520000, 'subtotal': 1040000},
        ]
        expected_summary = [
            {'name': item['name'], 'variant': item['variant'], 'quantity': item['quantity'], 'subtotal': item['subtotal']}
            for item in expected
        ]
        first = self.tools('get_order', {'order_id': 'SIM-O-00091'})['order']
        case_tools = CaseTools(self.store, Catalog(self.store), case_id='fixture-case',
                               customer_id=self.world.customer_id, conversation_id=self.world.conversation)
        results = {
            'get_order': first,
            'get_context': self.tools('get_context', {})['order'],
            'list_orders': next(o for o in self.tools('list_orders', {})['orders'] if o['id'] == first['id']),
            'prepare_order_action': self.tools('prepare_order_action',
                                              {'order_id': 'SIM-O-00091', 'action_type': 'return'})['order'],
            'get_case_order': case_tools('get_case_order', {'order_id': 'SIM-O-00091'})['order'],
            'list_case_orders': next(o for o in case_tools('list_case_orders', {})['orders'] if o['id'] == first['id']),
        }
        for name, order in results.items():
            with self.subTest(tool=name):
                self.assertEqual(order.get('items'), expected_summary if name == 'list_orders' else expected)
                for key in ('name', 'product_id', 'variant'):
                    self.assertEqual(order[key], first[key])

    def test_one_item_and_missing_rows_never_infer_from_primary_product(self):
        oid = self.tools('get_order', {'order_id': 'SIM-O-00091'})['order']['id']
        with self.store.connection(write=True) as db:
            db.execute('DELETE FROM order_items WHERE order_id=? AND product_id=?', (oid, 'P-602'))
        self.assertEqual(len(self.tools.read_order(oid)['items']), 1)
        with self.store.connection(write=True) as db:
            db.execute('DELETE FROM order_items WHERE order_id=?', (oid,))
        self.assertEqual(self.tools.read_order(oid)['items'], [])

    def test_ten_orders_stay_within_existing_model_result_budget(self):
        with self.store.connection(write=True) as db:
            db.execute('UPDATE orders SET customer_id=?', (self.world.customer_id,))
        result = self.tools('list_orders', {'limit': 10})
        self.assertEqual(result['returned_count'], 10)
        text = compact_tool_result(result)
        self.assertLessEqual(len(text), TOOL_RESULT_MAX_CHARS)
        self.assertIsInstance(json.loads(text), dict)


if __name__ == '__main__':
    unittest.main()
