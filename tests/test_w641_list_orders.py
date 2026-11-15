import json
import unittest
import uuid

import agent_protocol
from agent_protocol import ProtocolError, TOOLS, validate_tool
from retailops.business.application import Application
from retailops.guardrails.topic_filter import enforce_final_answer_grounding
from retailops.workflow.compaction import compact_tool_result, dump
from retailops.workflow.subagents.order_agent import _order
from retailops_conversation import Catalog
from retailops_tools import BoundTools
from scripts import run_agent_scenarios as runner


SUMMARY_KEYS = (
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
    'payment_method',
    'payment_status',
    'promised_delivery_by',
    'delivered_at',
    'items',
)

FORBIDDEN_KEYS = (
    'internal_order_id',
    'source_system',
    'payment',
    'delivery',
    'refund',
    'refund_summary',
    'eligibility',
    'vouchers',
    'recipient',
    'address',
    'as_of',
    'source',
    'version',
)

EXPECTED_DESCRIPTION = (
    "List the authenticated customer's orders as short summaries, newest first: "
    "5 per call by default (limit up to 20; offset pages through older orders). "
    "Each summary has both order IDs, status, ordered_at, amount, shipping_fee, "
    "payment status, delivery dates and item names with quantities. "
    "Call get_order for payment, delivery, refund and eligibility details. "
    "When has_more is true, say how many of total_count are shown and offer to "
    "show more (offset=next_offset) or to narrow down."
)


class _ScriptedModel:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.inputs = []

    def inspect(self):
        return {'name': 'fixture-agent', 'digest': 'fixture-digest', 'provider': 'custom'}

    def chat(self, messages, allow_tools, timeout):
        idx = len(self.inputs)
        self.inputs.append(messages)
        step = self.steps[idx]
        return step(messages) if callable(step) else step


class W641ListOrdersTests(unittest.TestCase):
    def setUp(self):
        self.world = runner.World({'fixture': 'standard', 'customer': 'SIM-C-0057'}, runner.ScriptedGateway())
        self.addCleanup(self.world.close)
        self.store = self.world.store
        self.tools = BoundTools(
            self.store,
            Catalog(self.store),
            self.world.customer_id,
            {'id': self.world.conversation},
            {},
        )

    def _assign_all_orders_to_customer(self):
        with self.store.connection(write=True) as db:
            db.execute('UPDATE orders SET customer_id=?', (self.world.customer_id,))

    def test_summary_keys_exact_order_and_no_forbidden_keys(self):
        self._assign_all_orders_to_customer()
        res = self.tools('list_orders', {})
        self.assertTrue(res['orders'])
        for order in res['orders']:
            full = self.tools.read_order(order['id'], focus=False)
            expected_keys = [k for k in SUMMARY_KEYS if k in full]
            self.assertEqual(list(order.keys()), expected_keys)
            for key in FORBIDDEN_KEYS:
                self.assertNotIn(key, order)
            for item in order['items']:
                self.assertTrue(set(item.keys()).issubset({'name', 'variant', 'quantity', 'subtotal'}))

    def test_sim_o_00091_shortened_items(self):
        res = self.tools('list_orders', {})
        by_ext = {o.get('external_order_id'): o for o in res['orders']}
        self.assertIn('SIM-O-00091', by_ext)
        self.assertEqual(
            by_ext['SIM-O-00091']['items'],
            [
                {'name': 'Áo sơ mi lụa công sở', 'variant': 'Trắng · Size M', 'quantity': 1, 'subtotal': 450000},
                {'name': 'Quần tây đen hàn quốc', 'variant': 'Đen · Size M', 'quantity': 2, 'subtotal': 1040000},
            ],
        )

    def test_default_call_newest_first_and_top_level_fields(self):
        self._assign_all_orders_to_customer()
        with self.store.connection(write=True) as db:
            rows = db.execute(
                'SELECT id, ordered_at FROM orders WHERE customer_id=?',
                (self.world.customer_id,),
            ).fetchall()
            # Force two rows to share the highest ordered_at so id DESC tie-breaker is exercised.
            top_pair = sorted(rows, key=lambda r: r['id'])[-2:]
            db.execute('UPDATE orders SET ordered_at=2000000000.0 WHERE id IN (?, ?)',
                       (top_pair[0]['id'], top_pair[1]['id']))
            rows = db.execute(
                'SELECT id, ordered_at FROM orders WHERE customer_id=?',
                (self.world.customer_id,),
            ).fetchall()

        expected_ordered_ids = [
            r['id']
            for r in sorted(
                rows,
                key=lambda r: (r['ordered_at'] is not None and r['ordered_at'] != '', float(r['ordered_at']) if r['ordered_at'] not in (None, '') else 0.0, str(r['id'])),
                reverse=True,
            )
        ]

        res = self.tools('list_orders', {})
        self.assertEqual(len(res['orders']), 5)
        self.assertEqual([o['id'] for o in res['orders']], expected_ordered_ids[:5])
        self.assertEqual(res['orders'][0]['id'], max(top_pair[0]['id'], top_pair[1]['id']))
        self.assertEqual(res['orders'][1]['id'], min(top_pair[0]['id'], top_pair[1]['id']))
        self.assertEqual(res['total_count'], len(rows))
        self.assertEqual(res['returned_count'], 5)
        self.assertEqual(res['offset'], 0)
        self.assertEqual(res['limit'], 5)
        self.assertTrue(res['has_more'])
        self.assertEqual(res['next_offset'], 5)
        self.assertTrue(res['truncated'])
        self.assertEqual(
            res['note'],
            f"Đang hiện 5/{len(rows)} đơn gần nhất. Gọi lại list_orders với offset=5 để xem tiếp, hoặc get_order để xem chi tiết một đơn.",
        )

        # Verify NULL/empty ordered_at rows are placed last when store returns them.
        sample_rows = [dict(r) for r in rows[:3]]
        null_id = sample_rows[0]['id']
        orig_orders = self.store.orders
        sample_rows[0]['ordered_at'] = None
        sample_rows[1]['ordered_at'] = 1700000000.0
        sample_rows[2]['ordered_at'] = 1800000000.0
        self.store.orders = lambda _cust: sample_rows
        try:
            null_res = self.tools('list_orders', {'limit': 5})
            self.assertEqual([o['id'] for o in null_res['orders']], [sample_rows[2]['id'], sample_rows[1]['id'], null_id])
        finally:
            self.store.orders = orig_orders

        # Customer with 0 orders: no note, no next_offset
        with self.store.connection(write=True) as db:
            db.execute("INSERT OR IGNORE INTO customers(id, name) VALUES ('C-ZERO-W641', 'Zero Orders')")
        zero_tools = BoundTools(self.store, Catalog(self.store), 'C-ZERO-W641', {'id': self.world.conversation}, {})
        zero_res = zero_tools('list_orders', {})
        self.assertEqual(zero_res['orders'], [])
        self.assertEqual(zero_res['total_count'], 0)
        self.assertEqual(zero_res['returned_count'], 0)
        self.assertFalse(zero_res['has_more'])
        self.assertFalse(zero_res['truncated'])
        self.assertNotIn('next_offset', zero_res)
        self.assertNotIn('note', zero_res)

    def test_pagination_walk_visits_all_orders_without_duplicates_or_gaps(self):
        self._assign_all_orders_to_customer()
        with self.store.connection() as db:
            all_ids = {r['id'] for r in db.execute('SELECT id FROM orders WHERE customer_id=?', (self.world.customer_id,))}

        seen = []
        offset = 0
        while True:
            res = self.tools('list_orders', {'limit': 7, 'offset': offset})
            seen.extend(o['id'] for o in res['orders'])
            if not res['has_more']:
                self.assertFalse(res['truncated'])
                self.assertNotIn('next_offset', res)
                self.assertNotIn('note', res)
                break
            self.assertTrue(res['truncated'])
            offset = res['next_offset']

        self.assertEqual(len(seen), len(all_ids))
        self.assertEqual(set(seen), all_ids)

    def test_offset_past_end_returns_empty_with_note(self):
        self._assign_all_orders_to_customer()
        first = self.tools('list_orders', {})
        total = first['total_count']
        for off in (total, total + 10):
            with self.subTest(offset=off):
                res = self.tools('list_orders', {'offset': off})
                self.assertEqual(res['orders'], [])
                self.assertEqual(res['returned_count'], 0)
                self.assertFalse(res['has_more'])
                self.assertFalse(res['truncated'])
                self.assertNotIn('next_offset', res)
                self.assertEqual(res['note'], f'Không còn đơn nào sau vị trí này; khách có {total} đơn.')

    def test_bound_tools_validation_errors_and_ascii_digit_acceptance(self):
        invalid_cases = [
            {'limit': 0},
            {'limit': 21},
            {'limit': 'abc'},
            {'limit': True},
            {'limit': False},
            {'limit': None},
            {'offset': -1},
            {'offset': 'abc'},
            {'offset': True},
        ]
        for bad_args in invalid_cases:
            with self.subTest(args=bad_args):
                res = self.tools('list_orders', bad_args)
                self.assertEqual(res.get('error'), 'invalid_arguments', res)
                self.assertIn('limit', res.get('message', ''))

        ok = self.tools('list_orders', {'limit': '5', 'offset': '0'})
        self.assertNotIn('error', ok)
        self.assertLessEqual(len(ok['orders']), 5)

    def test_validate_tool_integer_arguments_and_atomicity(self):
        self.assertEqual(validate_tool('list_orders', {}), {})
        self.assertEqual(validate_tool('list_orders', {'limit': 5}), {'limit': 5})
        norm = validate_tool('list_orders', {'limit': '5', 'offset': '10'})
        self.assertEqual(norm, {'limit': 5, 'offset': 10})
        self.assertIs(type(norm['limit']), int)
        self.assertIs(type(norm['offset']), int)

        raw = {'limit': '5', 'offset': -1}
        with self.assertRaises(ProtocolError):
            validate_tool('list_orders', raw)
        self.assertEqual(raw['limit'], '5', 'validate_tool must not mutate arguments partially on error')

        for bad in (
            {'limit': True},
            {'limit': False},
            {'limit': 0},
            {'limit': 21},
            {'offset': -1},
            {'offset': 10001},
            {'limit': ' 5 '},
            {'page': 1},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ProtocolError):
                    validate_tool('list_orders', dict(bad))

        with self.assertRaises(ProtocolError):
            validate_tool('get_order', {'order_id': 5})

    def test_tools_schema_and_verbatim_description(self):
        self.assertEqual(getattr(agent_protocol, 'LIST_ORDERS_DESCRIPTION', None), EXPECTED_DESCRIPTION)
        schema = next(t for t in TOOLS if t['function']['name'] == 'list_orders')['function']
        self.assertEqual(schema['description'], EXPECTED_DESCRIPTION)
        params = schema['parameters']
        self.assertEqual(params['required'], [])
        self.assertEqual(set(params['properties'].keys()), {'limit', 'offset'})
        self.assertEqual(params['properties']['limit'], {
            'type': 'integer',
            'minimum': 1,
            'maximum': 20,
            'description': 'How many orders to return; default 5.',
        })
        self.assertEqual(params['properties']['offset'], {
            'type': 'integer',
            'minimum': 0,
            'description': 'How many of the newest orders to skip; default 0. Use next_offset from the previous call.',
        })

    def test_f44_five_fixture_orders_fit_without_compaction_at_16k(self):
        # Pick 5 distinct orders (must include SIM-O-00091 with 2 persisted line items) for this customer
        with self.store.connection(write=True) as db:
            db.execute('UPDATE orders SET customer_id=? WHERE id IN (SELECT id FROM orders ORDER BY id LIMIT 4)',
                       (self.world.customer_id,))
            rows = db.execute('SELECT id FROM orders WHERE customer_id=?', (self.world.customer_id,)).fetchall()
            if len(rows) < 5:
                db.execute(
                    f'UPDATE orders SET customer_id=? WHERE id IN (SELECT id FROM orders WHERE customer_id!=? ORDER BY id LIMIT {5 - len(rows)})',
                    (self.world.customer_id, self.world.customer_id),
                )
            rows = db.execute('SELECT id FROM orders WHERE customer_id=?', (self.world.customer_id,)).fetchall()
        self.assertGreaterEqual(len(rows), 5)

        result = self.tools('list_orders', {'limit': 5, 'offset': 0})
        self.assertEqual(len(result['orders']), 5)
        compacted = compact_tool_result(result)
        self.assertEqual(compacted, dump(result))
        self.assertNotIn('_truncated', json.loads(compacted))

    def test_compatibility_order_agent_and_topic_filter(self):
        self._assign_all_orders_to_customer()
        res = self.tools('list_orders', {})
        for summary in res['orders']:
            self.assertIsNotNone(_order(summary), f'_order returned None for {summary}')
        self.assertTrue(res['has_more'])
        self.assertTrue(res['truncated'])
        grounded = enforce_final_answer_grounding(
            'Xem danh sách đơn hàng của tôi',
            'Đây là các đơn hàng của bạn.',
            messages=[{'role': 'tool', 'tool_name': 'list_orders', 'content': json.dumps(res, ensure_ascii=False)}],
        )
        self.assertIn(f"{res['returned_count']}/{res['total_count']}", grounded)
        self.assertIn('truncated=True', grounded)

    def test_real_agent_loop_accepts_string_digit_pagination_args(self):
        self._assign_all_orders_to_customer()
        seen_payloads = []

        def second_turn(messages):
            tool_msg = next(m for m in reversed(messages) if m.get('role') == 'tool')
            payload = json.loads(tool_msg['content'])
            seen_payloads.append(payload)
            return {
                'message': {
                    'role': 'assistant',
                    'content': f"Đang hiện {payload['returned_count']}/{payload['total_count']} đơn hàng gần nhất.",
                },
                'prompt_eval_count': 20,
                'eval_count': 10,
            }

        model = _ScriptedModel(
            {
                'message': {
                    'role': 'assistant',
                    'content': '',
                    'tool_calls': [{'function': {'name': 'list_orders', 'arguments': {'limit': '5', 'offset': '0'}}}],
                },
                'prompt_eval_count': 20,
                'eval_count': 10,
            },
            second_turn,
        )
        app = Application(self.store, {}, infer=model, orchestrator='single_agent')
        conv = app.new_conversation(self.world.customer_id, {'provider_id': 'custom'})
        reply = app.chat(
            self.world.customer_id,
            {
                'conversation_id': conv['conversation_id'],
                'text': 'Cho xem 5 đơn gần nhất',
                'request_id': 'req-' + uuid.uuid4().hex,
            },
        )
        self.assertEqual(reply['action'], 'reply')
        self.assertEqual(len(seen_payloads), 1)
        payload = seen_payloads[0]
        self.assertNotIn('error', payload)
        self.assertEqual(payload['returned_count'], 5)
        self.assertEqual(payload['limit'], 5)
        self.assertEqual(payload['offset'], 0)
        self.assertEqual(len(payload['orders']), 5)


if __name__ == '__main__':
    unittest.main()
