"""W6.4.2: synthetic tests for F46/F47 answer_check fixes and details trace."""
import copy
import json
import unittest
from unittest.mock import patch

from retailops.business.application import Application
from retailops.knowledge.repository import KnowledgeRepository
from retailops.workflow.answer_check import POLICY_NOTE, check_final_answer, tool_evidence
from scripts import run_agent_scenarios as runner
from test_r1_w3_2_agent_loop import AgentFixture, ScriptedModel, call, say, tool_data


def messages(payload, name='get_order'):
    return [{'role': 'tool', 'tool_name': name, 'content': json.dumps(payload, ensure_ascii=False)}]


ITEMS_91 = [
    {'name': 'Áo sơ mi lụa công sở', 'variant': 'Trắng · Size M', 'quantity': 1, 'unit_price': 450000, 'subtotal': 450000},
    {'name': 'Quần tây đen hàn quốc', 'variant': 'Đen · Size M', 'quantity': 2, 'unit_price': 520000, 'subtotal': 1040000},
]
ORDER_91 = {
    'order': {
        'id': 'ord_91',
        'external_order_id': 'SIM-O-00091',
        'amount': 1530000,
        'shipping_fee': 40000,
        'items': ITEMS_91,
        'eligibility': {
            'late_by_hours': 72.0,
            'days_since_delivery': 4.3169,
            'return_window_days': 7,
            'size_exchange_window_days': 15,
            'warranty_window_days': 90,
            'within_return_window': True,
        },
    }
}
LIST_3 = {
    'orders': [
        {
            'id': 'ord_91',
            'external_order_id': 'SIM-O-00091',
            'amount': 1530000,
            'shipping_fee': 40000,
            'items': [{'name': i['name'], 'quantity': i['quantity'], 'subtotal': i['subtotal']} for i in ITEMS_91],
        },
        {
            'id': 'ord_58',
            'external_order_id': 'SIM-O-00058',
            'amount': 440000,
            'shipping_fee': 20000,
            'items': [{'name': 'Áo thun', 'quantity': 1, 'subtotal': 420000}],
        },
        {
            'id': 'ord_57',
            'external_order_id': 'SIM-O-00057',
            'amount': 179000,
            'shipping_fee': 30000,
            'items': [{'name': 'Tất', 'quantity': 1, 'subtotal': 149000}],
        },
    ],
    'total_count': 3,
    'has_more': False,
}


class Row1MoneyEvidenceTests(unittest.TestCase):
    def test_item_prices_and_subtotal_kept_with_order_91_and_dropped_without_evidence(self):
        lines = (
            '- Tiền hàng 1.490.000₫ + phí ship 40.000₫ = 1.530.000₫',
            '- Áo sơ mi lụa công sở 450.000₫, Quần tây đen hàn quốc 1.040.000₫; phí vận chuyển 40.000₫.',
            '- Đơn giá Quần tây đen hàn quốc 520.000₫ × 2, phí ship 40.000₫.',
        )
        ev = messages(ORDER_91)
        for line in lines:
            with self.subTest(line=line):
                res = check_final_answer(line, ev)
                self.assertFalse(res.changed)
                self.assertEqual(res.text, line)
                no_ev = check_final_answer(line)
                self.assertEqual(no_ev.text, POLICY_NOTE)
                self.assertEqual(no_ev.dropped_policy, 1)

    def test_policy_fee_and_wrong_shipping_amount_still_dropped_with_order_91(self):
        ev = messages(ORDER_91)
        for line in (
            'Phí ship đơn này là 35.000đ ạ.',
            'Phí đổi hàng là 450.000đ ạ.',
            'Shop miễn phí ship đổi size lần đầu ạ.',
        ):
            with self.subTest(line=line):
                res = check_final_answer(line, ev)
                self.assertEqual(res.text, POLICY_NOTE)
                self.assertEqual(res.dropped_policy, 1)

    def test_single_order_evidence_money_amounts_and_derived_money(self):
        ev = tool_evidence(messages(ORDER_91))
        self.assertTrue({450000, 520000, 1040000}.issubset(ev.money_amounts))
        self.assertEqual(ev.derived_money, frozenset({1490000}))

    def test_multi_order_derived_money_and_totals_kept(self):
        ev_msgs = messages(LIST_3, 'list_orders')
        ev = tool_evidence(ev_msgs)
        self.assertEqual(ev.derived_money, frozenset({1490000, 420000, 149000, 2149000, 90000, 2059000}))
        for line in (
            'Tổng phí ship 3 đơn: 90.000₫.',
            'Tổng chi 2.149.000₫, trong đó phí ship 90.000₫.',
        ):
            with self.subTest(line=line):
                res = check_final_answer(line, ev_msgs)
                self.assertFalse(res.changed)
                self.assertEqual(res.text, line)
                self.assertEqual(check_final_answer(line).text, POLICY_NOTE)

    def test_deduplicates_same_order_across_list_orders_and_get_order(self):
        combined = messages(LIST_3, 'list_orders') + messages(ORDER_91)
        self.assertEqual(
            tool_evidence(combined).derived_money,
            frozenset({1490000, 420000, 149000, 2149000, 90000, 2059000}),
        )

    def test_payment_records_do_not_count_as_orders(self):
        combined = messages(LIST_3, 'list_orders') + messages({'payments': [{'payment_id': 'pay_1', 'amount': 999000}]})
        self.assertEqual(
            tool_evidence(combined).derived_money,
            frozenset({1490000, 420000, 149000, 2149000, 90000, 2059000}),
        )
        single_plus_payment = messages(ORDER_91) + messages({'payments': [{'id': 'pay_1', 'amount': 999000}]})
        self.assertEqual(tool_evidence(single_plus_payment).derived_money, frozenset({1490000}))

    def test_invalid_subtotals_and_empty_items_add_no_order_subtotal(self):
        for bad_subtotal in (True, '450000', 450000.0):
            payload = copy.deepcopy(ORDER_91)
            payload['order']['items'][0]['subtotal'] = bad_subtotal
            with self.subTest(bad_subtotal=bad_subtotal):
                self.assertEqual(tool_evidence(messages(payload)).derived_money, frozenset())
        missing_subtotal = copy.deepcopy(ORDER_91)
        del missing_subtotal['order']['items'][1]['subtotal']
        self.assertEqual(tool_evidence(messages(missing_subtotal)).derived_money, frozenset())
        empty_items = copy.deepcopy(ORDER_91)
        empty_items['order']['items'] = []
        self.assertEqual(tool_evidence(messages(empty_items)).derived_money, frozenset())

        # Two orders where only one has valid items: total amount/shipping included, total items omitted.
        partial_list = copy.deepcopy(LIST_3)
        partial_list['orders'][1]['items'] = []
        self.assertEqual(
            tool_evidence(messages(partial_list, 'list_orders')).derived_money,
            frozenset({1490000, 149000, 2149000, 90000}),
        )

    def test_orders_missing_both_id_and_external_order_id_excluded_from_multi_order_totals(self):
        payload = {
            'orders': [
                {'amount': 100000, 'shipping_fee': 20000},
                {'amount': 200000, 'shipping_fee': 30000},
            ]
        }
        self.assertEqual(tool_evidence(messages(payload, 'list_orders')).derived_money, frozenset())

    def test_money_amounts_unchanged_when_no_unit_price_or_subtotal(self):
        payload = {'orders': [{'shipping_fee': 30000, 'amount': 380000}, {'refunded_total': 500, 'pending_total': 1000}]}
        self.assertEqual(tool_evidence(messages(payload, 'list_orders')).money_amounts, frozenset({30000, 380000, 500, 1000}))


class Row2TimeEvidenceTests(unittest.TestCase):
    def test_order_91_derived_time_matches_exact_set(self):
        self.assertEqual(
            tool_evidence(messages(ORDER_91)).derived_time,
            frozenset({72, 3, 4, 5, 2, 10, 11, 85, 86}),
        )

    def test_derived_time_sentences_kept_with_order_91_and_dropped_without_evidence(self):
        ev = messages(ORDER_91)
        for line, expected_no_ev in (
            ('**SIM-O-00091 — trễ hạn 72 giờ, sắp hết hạn trả hàng**', f'**SIM-O-00091**\n\n{POLICY_NOTE}'),
            ('- Hạn đổi size còn khoảng 10 ngày.', POLICY_NOTE),
            ('- Đã giao được 4 ngày, trong hạn trả 7 ngày.', POLICY_NOTE),
            ('- Đơn giao hàng trễ, quá hạn 3 ngày.', POLICY_NOTE),
        ):
            with self.subTest(line=line):
                res = check_final_answer(line, ev)
                self.assertFalse(res.changed)
                self.assertEqual(res.text, line)
                no_ev = check_final_answer(line)
                self.assertEqual(no_ev.text, expected_no_ev)
                self.assertEqual(no_ev.dropped_policy, 1)

    def test_unknown_or_policy_time_numbers_still_dropped_with_order_91(self):
        ev = messages(ORDER_91)
        for line in (
            '- Hạn đổi size còn 12 ngày.',
            'Shop cho đổi trong 30 ngày ạ.',
        ):
            with self.subTest(line=line):
                res = check_final_answer(line, ev)
                self.assertEqual(res.text, POLICY_NOTE)
                self.assertEqual(res.dropped_policy, 1)

    def test_invalid_or_zero_late_by_hours_and_days_add_no_time_numbers(self):
        for bad_late in (0.0, 0, -5.0, None, '72', True, float('nan'), float('inf')):
            with self.subTest(bad_late=bad_late):
                self.assertEqual(
                    tool_evidence(messages({'eligibility': {'late_by_hours': bad_late}})).derived_time,
                    frozenset(),
                )
        for bad_days in (-1.0, None, '4', True, float('nan'), float('inf')):
            with self.subTest(bad_days=bad_days):
                self.assertEqual(
                    tool_evidence(messages({'eligibility': {'days_since_delivery': bad_days, 'return_window_days': 7}})).derived_time,
                    frozenset(),
                )

    def test_days_since_delivery_20_with_windows_7_15_90(self):
        payload = {
            'eligibility': {
                'days_since_delivery': 20.0,
                'return_window_days': 7,
                'size_exchange_window_days': 15,
                'warranty_window_days': 90,
            }
        }
        self.assertEqual(tool_evidence(messages(payload)).derived_time, frozenset({20, 70}))


class Row3HeadingAndNumberedLineTests(unittest.TestCase):
    def test_heading_table_examples_without_evidence(self):
        cases = (
            ('**SIM-O-38588564-03 — trễ hạn 72 giờ, sắp hết hạn trả hàng**', '**SIM-O-38588564-03**'),
            ('**1. SIM-O-38588564-02** — Đang giao hàng, quá hạn 54 giờ.', '**1. SIM-O-38588564-02**'),
            ('### Đổi trả: miễn phí 2 chiều tận nhà', '### Đổi trả'),
            ('**Miễn phí đổi trả 2 chiều**', ''),
            ('- **SIM-O-1 — trễ hạn trả hàng 72 giờ**', ''),
            ('**Phí ship:** 30.000đ', ''),
        )
        for line, expected_first_line in cases:
            with self.subTest(line=line):
                res = check_final_answer(line)
                expected = f'{expected_first_line}\n\n{POLICY_NOTE}' if expected_first_line else POLICY_NOTE
                self.assertEqual(res.text, expected)
                self.assertEqual(res.dropped_policy, 1)
                again = check_final_answer(res.text)
                self.assertFalse(again.changed)
                self.assertEqual(again.text, res.text)

    def test_smoke_multi_order_response_preserves_order_and_second_heading(self):
        text = (
            '**SIM-O-38588564-01 — đơn đúng hạn**\n'
            '- Giao 05/11, sớm hơn mốc cam kết 06/11.\n\n'
            '**SIM-O-38588564-03 — trễ hạn 72 giờ, sắp hết hạn trả hàng**\n'
            '- Cam kết 06/11 nhưng giao 09/11.\n\n'
            '**SIM-O-38588564-02 — đang giao**\n'
            '- Đang ở trạm trung chuyển Đà Nẵng.'
        )
        res = check_final_answer(text)
        expected = (
            '**SIM-O-38588564-01 — đơn đúng hạn**\n'
            '- Giao 05/11, sớm hơn mốc cam kết 06/11.\n\n'
            '**SIM-O-38588564-03**\n'
            '- Cam kết 06/11 nhưng giao 09/11.\n\n'
            '**SIM-O-38588564-02 — đang giao**\n'
            '- Đang ở trạm trung chuyển Đà Nẵng.\n\n'
            f'{POLICY_NOTE}'
        )
        self.assertEqual(res.text, expected)
        self.assertEqual(res.dropped_policy, 1)
        self.assertEqual(res.text.count(POLICY_NOTE), 1)
        again = check_final_answer(res.text)
        self.assertFalse(again.changed)
        self.assertEqual(again.text, res.text)

    def test_orphan_numbered_item_removed_when_sentence_dropped(self):
        for line in (
            '1. Shop miễn phí đổi trả 2 chiều.',
            '**1. Shop miễn phí đổi trả 2 chiều.**',
            '2) Thời hạn đổi trả là 30 ngày.',
        ):
            with self.subTest(line=line):
                res = check_final_answer(line)
                self.assertEqual(res.text, POLICY_NOTE)
                self.assertEqual(res.dropped_policy, 1)
                again = check_final_answer(res.text)
                self.assertFalse(again.changed)
                self.assertEqual(again.text, res.text)

        kept = check_final_answer('1. Đơn O-701 đã giao. Shop miễn phí đổi trả 2 chiều.')
        self.assertEqual(kept.text, f'1. Đơn O-701 đã giao.\n\n{POLICY_NOTE}')
        self.assertEqual(kept.dropped_policy, 1)

    def test_heading_separators_empty_label_and_stranded_citation(self):
        self.assertEqual(
            check_final_answer('## SIM-O-00091 | trễ hạn trả hàng 72 giờ ##').text,
            f'## SIM-O-00091\n\n{POLICY_NOTE}',
        )
        self.assertEqual(
            check_final_answer('** — trễ hạn trả hàng 72 giờ**').text,
            POLICY_NOTE,
        )
        cit = '[KB:0123456789abcdef01234567]'
        res = check_final_answer(f'**SIM-O-00091 — Em đã hủy đơn rồi {cit}**')
        self.assertTrue(res.text.startswith('**SIM-O-00091**'))
        self.assertIn(cit, res.text)
        self.assertEqual(res.dropped_claims, 1)


class Row4DetailsUnitTests(unittest.TestCase):
    def test_five_line_details_order_keys_and_no_leaked_text(self):
        lines = [
            'Shop đổi size tận nhà cho anh/chị ạ.',
            'Phí ship đơn này là 35.000đ ạ.',
            'Thời hạn đổi trả là 30 ngày.',
            'Em đã hủy đơn SIM-O-00115 cho anh/chị rồi ạ.',
            'Em đã chuyển cuộc trò chuyện cho nhân viên rồi ạ.',
        ]
        res = check_final_answer('\n'.join(lines))
        expected = (
            {'line': 1, 'kind': 'policy', 'rule': 'logistics', 'heading_label_kept': False},
            {'line': 2, 'kind': 'policy', 'rule': 'fee_amount', 'heading_label_kept': False},
            {'line': 3, 'kind': 'policy', 'rule': 'deadline_number', 'heading_label_kept': False},
            {'line': 4, 'kind': 'claim', 'rule': 'done_claim', 'heading_label_kept': False},
            {'line': 5, 'kind': 'handoff', 'rule': 'handoff_claim', 'heading_label_kept': False},
        )
        self.assertEqual(res.details, expected)
        self.assertEqual(len(res.details), res.dropped_policy + res.dropped_claims)
        serialized = json.dumps(res.details, ensure_ascii=False)
        for item in res.details:
            self.assertEqual(set(item.keys()), {'line', 'kind', 'rule', 'heading_label_kept'})
        for line in lines:
            self.assertNotIn(line, serialized)
        for forbidden in ('tận nhà', '35.000', '30 ngày', 'SIM-O-00115', 'nhân viên'):
            self.assertNotIn(forbidden, serialized)

    def test_policy_fee_vs_logistics_hedge_and_deadline_no_fact(self):
        fee = check_final_answer('Shop miễn phí đổi hàng ạ.')
        self.assertEqual(fee.details, ({'line': 1, 'kind': 'policy', 'rule': 'policy_fee', 'heading_label_kept': False},))

        two_way = check_final_answer('Shop miễn phí đổi hàng 2 chiều ạ.')
        self.assertEqual(two_way.details, ({'line': 1, 'kind': 'policy', 'rule': 'logistics', 'heading_label_kept': False},))

        hedged = check_final_answer('Thời hạn đổi trả là bao lâu thì em chưa rõ, em sẽ kiểm tra thêm.')
        self.assertFalse(hedged.changed)
        self.assertEqual(hedged.details, ())

        no_fact = check_final_answer('Đơn còn trong thời hạn đổi trả ạ.')
        self.assertEqual(
            no_fact.details,
            ({'line': 1, 'kind': 'policy', 'rule': 'deadline_no_fact', 'heading_label_kept': False},),
        )

    def test_heading_label_kept_flag_and_unchanged_details_empty(self):
        heading = check_final_answer('**SIM-O-00091 — trễ hạn 72 giờ, sắp hết hạn trả hàng**')
        self.assertEqual(
            heading.details,
            ({'line': 1, 'kind': 'policy', 'rule': 'deadline_number', 'heading_label_kept': True},),
        )
        orphan_list = check_final_answer('1. Shop miễn phí đổi trả 2 chiều.')
        self.assertEqual(
            orphan_list.details,
            ({'line': 1, 'kind': 'policy', 'rule': 'logistics', 'heading_label_kept': False},),
        )
        safe = check_final_answer('Đơn SIM-O-00091 đã được giao thành công.')
        self.assertFalse(safe.changed)
        self.assertEqual(safe.details, ())


class Row4ApplicationTests(AgentFixture):
    MODES = ('agent', 'legacy')

    def chat(self, mode, model, text):
        app = Application(self.store_a, {}, infer=model, orchestrator=mode)
        cid = self.store_a.new_conversation('C-001')['conversation_id']
        return self.say(app, text, cid)

    def test_application_trace_contains_answer_check_detail_in_both_modes(self):
        for mode in self.MODES:
            model = ScriptedModel(
                call(('get_order', {'order_id': 'O-701'})),
                say('Đơn O-701 đã giao. Shop sẽ đổi size tận nhà miễn phí 2 chiều cho anh/chị ạ.'),
            )
            result = self.chat(mode, model, 'Em muốn đổi size cho đơn O-701')
            with self.subTest(mode=mode):
                self.assertEqual(result['trace']['answer_check'], {'dropped_policy_promises': 1, 'dropped_done_claims': 0})
                self.assertEqual(
                    result['trace']['answer_check_detail'],
                    [{'line': 1, 'kind': 'policy', 'rule': 'logistics', 'heading_label_kept': False}],
                )
                self.assertNotIn('tận nhà', result['message'])
                self.assertNotIn('tận nhà', json.dumps(result['trace']['answer_check_detail'], ensure_ascii=False))

    def test_cited_turn_has_no_answer_check_or_detail_in_trace(self):
        document = {
            'chunk': 'Đổi hàng miễn phí trong 7 ngày kể từ khi nhận hàng nếu còn nguyên tem mác.',
            'source_key': 'policies/returns.md',
            'title': 'Chính sách đổi trả',
            'score': 0.9,
        }
        self.store_a.schema = 'tenant_alpha'

        def cites(msgs):
            citation = tool_data(msgs)['results'][0]['citation_id']
            return say(f'Theo chính sách, đổi hàng miễn phí trong 7 ngày kể từ khi nhận hàng [{citation}].')

        for mode in self.MODES:
            model = ScriptedModel(call(('search_knowledge', {'query': 'chính sách đổi trả'})), cites)
            with patch.object(KnowledgeRepository, 'search', lambda repo, query, limit=5: [dict(document)]):
                result = self.chat(mode, model, 'Cho em hỏi chính sách đổi trả của shop')
            with self.subTest(mode=mode):
                self.assertNotIn('answer_check', result['trace'])
                self.assertNotIn('answer_check_detail', result['trace'])


class Row4RunnerTests(unittest.TestCase):
    def test_runner_records_answer_check_only_when_dropped(self):
        case = copy.deepcopy(runner.load_dataset()[0])
        case['turns'] = [
            {
                'user': 'Đơn SIM-O-00105 có được đổi size tận nhà miễn phí không?',
                'fake_model': [
                    {'call': [{'name': 'get_order', 'arguments': {'order_id': 'SIM-O-00105'}}]},
                    {'say': 'Đơn SIM-O-00105 đã giao. Shop sẽ đổi size tận nhà miễn phí 2 chiều cho anh/chị ạ.'},
                ],
                'expect': {'tools_called': ['get_order'], 'action': 'reply'},
            },
            {
                'user': 'Cảm ơn shop, cho mình xem lại trạng thái đơn SIM-O-00105.',
                'fake_model': [
                    {'call': [{'name': 'get_order', 'arguments': {'order_id': 'SIM-O-00105'}}]},
                    {'say': 'Đơn SIM-O-00105 hiện ở trạng thái đã giao ạ.'},
                ],
                'expect': {'tools_called': ['get_order'], 'action': 'reply'},
            },
        ]
        case['final_state'] = {}
        record = runner.run_scenario(case, runner.ScriptedGateway(), 'fake')
        self.assertTrue(record['passed'], record['failures'])
        dropped_turn, clean_turn = record['turns']
        self.assertEqual(
            dropped_turn['answer_check'],
            {
                'dropped_policy_promises': 1,
                'dropped_done_claims': 0,
                'detail': [{'line': 1, 'kind': 'policy', 'rule': 'logistics', 'heading_label_kept': False}],
            },
        )
        self.assertNotIn('tận nhà', dropped_turn['answer'])
        self.assertNotIn('tận nhà', json.dumps(dropped_turn['answer_check'], ensure_ascii=False))
        self.assertNotIn('answer_check', clean_turn)


if __name__ == '__main__':
    unittest.main()
