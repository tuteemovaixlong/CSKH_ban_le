import unittest

from retailops.workflow.case_assist import CaseAssistBoundTools, STAFF_CASE_ASSIST_TOOLS
from retailops_conversation import Catalog
from scripts import run_agent_scenarios as runner


CASE_SUMMARY_KEYS = (
    'id',
    'external_order_id',
    'status',
    'ordered_at',
    'name',
    'product_id',
    'variant',
    'amount',
    'currency',
    'shipping_fee',
    'payment_status',
    'delivered_at',
    'days_since_delivery',
    'allowed_action_types',
    'has_open_order_action',
    'items',
)

OMITTED_CASE_KEYS = (
    'internal_order_id',
    'source_system',
    'version',
    'payment_method',
    'ship_to_area',
    'recipient',
    'vouchers',
    'promised_delivery_by',
    'refund_summary',
    'eligibility',
    'as_of',
    'cancel_reason',
    'cancel_reason_label',
    'delivery_age_label',
)

EXPECTED_CASE_ORDERS_DESCRIPTION = (
    "READ ONLY: list the orders of the current case's customer as short summaries "
    "(without customer PII): IDs, status, dates, amount, payment status, delivery age, "
    "allowed actions, open-request flag and item names with quantities. "
    "Call get_case_order for payment, refund, eligibility and stock details."
)


class W641CaseOrdersTests(unittest.TestCase):
    def setUp(self):
        self.world = runner.World({'fixture': 'standard', 'customer': 'SIM-C-0057'}, runner.ScriptedGateway())
        self.addCleanup(self.world.close)
        self.store = self.world.store
        self.case_tools = CaseAssistBoundTools(
            self.store,
            Catalog(self.store),
            case_id='fixture-case',
            customer_id=self.world.customer_id,
            conversation_id=self.world.conversation,
        )

    def test_list_case_orders_summary_keys_and_truncation_flags(self):
        res_small = self.case_tools('list_case_orders', {})
        self.assertEqual(res_small['case_id'], 'fixture-case')
        self.assertEqual(res_small['count'], len(res_small['orders']))
        self.assertEqual(res_small['total_count'], len(res_small['orders']))
        self.assertFalse(res_small['truncated'])
        self.assertGreaterEqual(res_small['count'], 1)
        by_ext = {o.get('external_order_id'): o for o in res_small['orders']}
        self.assertIn('SIM-O-00091', by_ext)
        self.assertEqual(
            by_ext['SIM-O-00091']['items'],
            [
                {'name': 'Áo sơ mi lụa công sở', 'variant': 'Trắng · Size M', 'quantity': 1, 'subtotal': 450000},
                {'name': 'Quần tây đen hàn quốc', 'variant': 'Đen · Size M', 'quantity': 2, 'subtotal': 1040000},
            ],
        )

        # Assign all orders in DB (>20) to this customer to exercise LIMIT 20 + total_count/truncated.
        with self.store.connection(write=True) as db:
            db.execute('UPDATE orders SET customer_id=?', (self.world.customer_id,))
            total_in_db = db.execute('SELECT COUNT(*) FROM orders WHERE customer_id=?', (self.world.customer_id,)).fetchone()[0]
        self.assertGreater(total_in_db, 20)

        res_large = self.case_tools('list_case_orders', {})
        self.assertEqual(res_large['case_id'], 'fixture-case')
        self.assertEqual(res_large['count'], 20)
        self.assertEqual(len(res_large['orders']), 20)
        self.assertEqual(res_large['total_count'], total_in_db)
        self.assertTrue(res_large['truncated'])
        order_ids = [o['id'] for o in res_large['orders']]
        self.assertEqual(order_ids, sorted(order_ids), 'ORDER BY id ASC must be preserved')

        for order in res_large['orders']:
            self.assertEqual(list(order.keys()), list(CASE_SUMMARY_KEYS))
            for key in OMITTED_CASE_KEYS:
                self.assertNotIn(key, order)
            for item in order['items']:
                self.assertTrue(set(item.keys()).issubset({'name', 'variant', 'quantity', 'subtotal'}))

    def test_get_case_order_keeps_full_eligibility_and_full_items(self):
        detail = self.case_tools('get_case_order', {'order_id': 'SIM-O-00091'})
        order = detail['order']
        self.assertIsInstance(order.get('eligibility'), dict)
        self.assertEqual(
            order['items'],
            [
                {'product_id': 'P-601', 'name': 'Áo sơ mi lụa công sở', 'variant': 'Trắng · Size M',
                 'quantity': 1, 'unit_price': 450000, 'subtotal': 450000},
                {'product_id': 'P-602', 'name': 'Quần tây đen hàn quốc', 'variant': 'Đen · Size M',
                 'quantity': 2, 'unit_price': 520000, 'subtotal': 1040000},
            ],
        )

    def test_list_case_orders_tool_description_verbatim(self):
        tool_def = next(t for t in STAFF_CASE_ASSIST_TOOLS if t['function']['name'] == 'list_case_orders')
        self.assertEqual(tool_def['function']['description'], EXPECTED_CASE_ORDERS_DESCRIPTION)


if __name__ == '__main__':
    unittest.main()
