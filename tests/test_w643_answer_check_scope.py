import copy
import json
import unittest

from retailops.business.application import Application
from retailops.workflow.answer_check import (
    AUDIT_RULES,
    BLOCKING_RULES,
    CLAIM_NOTE,
    POLICY_NOTE,
    check_final_answer,
)
from scripts import run_agent_scenarios as runner
from test_r1_w3_2_agent_loop import AgentFixture, ScriptedModel, call, say

LIST_2 = {'orders': [
    {'id': 'o2', 'external_order_id': 'SIM-O-38588564-02', 'status': 'shipping', 'ordered_at': '2026-11-09T10:00:00+07:00',
     'amount': 839000, 'shipping_fee': 40000, 'promised_delivery_by': '2026-11-13T23:59:00+07:00',
     'items': [{'name': 'Áo khoác Everyday', 'quantity': 1, 'subtotal': 799000}]},
    {'id': 'o1', 'external_order_id': 'SIM-O-38588564-01', 'status': 'delivered', 'ordered_at': '2026-11-03T09:00:00+07:00',
     'amount': 319000, 'shipping_fee': 20000, 'promised_delivery_by': '2026-11-06T23:59:00+07:00',
     'delivered_at': '2026-11-05T13:28:00+07:00', 'items': [{'name': 'Áo thun Essential', 'quantity': 1, 'subtotal': 299000}]}]}

GET_9 = {'order': {'id': 'o9', 'external_order_id': 'SIM-O-9', 'amount': 450000, 'shipping_fee': 0, 'status': 'delivered',
         'eligibility': {'warranty_window_days': 90, 'return_window_days': 7, 'size_exchange_window_days': 15,
                         'within_warranty': True},
         'shipment': {'carrier': 'GHN', 'shipper_phone': '090***1234'}}}


def _msgs(payload):
    return [{'role': 'tool', 'content': json.dumps(payload, ensure_ascii=False)}]


class Row1AnswerCheckScopeTests(unittest.TestCase):
    TABLE_LINES = (
        (1, '| SIM-O-38588564-02 | 09/11/2026 | Áo khoác Everyday | 839.000₫ (gồm phí ship 40.000₫) | Đang vận chuyển |', LIST_2),
        (2, '- Đặt ngày 2026-11-09, phí ship 40.000₫.', LIST_2),
        (3, '| SIM-O-38588564-02 | 839.000₫ | Đang vận chuyển (trễ hạn 54 giờ) |', LIST_2),
        (4, 'Shipper 090***1234 sẽ giao hàng, phí ship 0đ ạ.', GET_9),
        (5, 'Sản phẩm còn bảo hành 3 tháng ạ.', GET_9),
        (6, 'Anh/chị được đổi hàng trong 7 ngày kể từ khi nhận hàng.', GET_9),
        (7, 'Thời hạn đổi trả là 30 ngày.', GET_9),
        (8, 'Phí ship do shop chịu hoàn toàn.', GET_9),
        (9, 'Đơn SIM-O-9 được miễn phí ship ạ.', GET_9),
        (10, 'Đổi size lần đầu được miễn phí ship ạ.', GET_9),
        (11, 'Shop đổi size tận nhà cho anh/chị ạ.', GET_9),
        (12, 'Em đã hủy đơn SIM-O-9 cho anh/chị theo chính sách [KB:0123456789abcdef01234567].', GET_9),
    )

    def test_rule_group_constants(self):
        self.assertEqual(BLOCKING_RULES, ('handoff_claim', 'done_claim', 'logistics', 'policy_fee'))
        self.assertEqual(AUDIT_RULES, ('fee_amount', 'deadline_number', 'deadline_no_fact'))

    def test_twelve_line_table(self):
        kept_expected = {
            1: None,
            2: None,
            3: 'deadline_number',
            4: None,
            5: 'deadline_number',
            6: None,
            7: 'deadline_number',
            9: None,
        }
        dropped_expected = {
            8: ('policy_fee', POLICY_NOTE),
            10: ('policy_fee', POLICY_NOTE),
            11: ('logistics', POLICY_NOTE),
            12: ('done_claim', CLAIM_NOTE),
        }
        for idx, line, ev in self.TABLE_LINES:
            with self.subTest(row=idx):
                res = check_final_answer(line, _msgs(ev))
                if idx in kept_expected:
                    self.assertFalse(res.changed)
                    self.assertEqual(res.text, line)
                    self.assertEqual(res.details, ())
                    rule = kept_expected[idx]
                    if rule is None:
                        self.assertEqual(res.audit, ())
                    else:
                        self.assertEqual(res.audit, ({'line': 1, 'rule': rule},))
                else:
                    rule, note = dropped_expected[idx]
                    self.assertTrue(res.changed)
                    self.assertEqual(res.audit, ())
                    self.assertEqual([d['rule'] for d in res.details], [rule])
                    self.assertIn(note, res.text)
                    self.assertNotIn(line, res.text)

    def test_shop_supported_shipping_is_policy_fee(self):
        res = check_final_answer('Phí vận chuyển sẽ được shop hỗ trợ.', _msgs(GET_9))
        self.assertTrue(res.changed)
        self.assertEqual(res.text, POLICY_NOTE)
        self.assertEqual([d['rule'] for d in res.details], ['policy_fee'])
        self.assertEqual(res.audit, ())

    def test_numeric_rules_without_evidence_are_audited_and_kept(self):
        for idx in (3, 5, 7):
            line = self.TABLE_LINES[idx - 1][1]
            res = check_final_answer(line, None)
            self.assertFalse(res.changed)
            self.assertEqual(res.text, line)
            self.assertEqual(res.audit, ({'line': 1, 'rule': 'deadline_number'},))

        no_fact = 'Đơn còn trong thời hạn đổi trả ạ.'
        res_no_fact = check_final_answer(no_fact, None)
        self.assertFalse(res_no_fact.changed)
        self.assertEqual(res_no_fact.text, no_fact)
        self.assertEqual(res_no_fact.audit, ({'line': 1, 'rule': 'deadline_no_fact'},))

    def test_done_claim_and_fee_amount_same_sentence_drops_without_audit(self):
        sentence = 'Em đã hoàn tiền 35.000đ phí ship cho anh/chị rồi ạ.'
        res = check_final_answer(sentence, None)
        self.assertTrue(res.changed)
        self.assertEqual(res.text, CLAIM_NOTE)
        self.assertEqual([d['rule'] for d in res.details], ['done_claim'])
        self.assertEqual(res.audit, ())

    def test_three_line_mixed_answer_and_audit_shape_and_idempotence(self):
        lines = [
            self.TABLE_LINES[0][1],   # line 1: kept, clean
            self.TABLE_LINES[2][1],   # line 2: kept, audited deadline_number
            self.TABLE_LINES[10][1],  # line 3: dropped logistics
        ]
        raw = '\n'.join(lines)
        res = check_final_answer(raw, _msgs(LIST_2))
        self.assertTrue(res.changed)
        self.assertEqual(res.text.count(POLICY_NOTE), 1)
        self.assertIn(lines[0], res.text)
        self.assertIn(lines[1], res.text)
        self.assertNotIn(lines[2], res.text)
        self.assertEqual(res.audit, ({'line': 2, 'rule': 'deadline_number'},))
        self.assertEqual([d['rule'] for d in res.details], ['logistics'])

        for entry in res.audit:
            self.assertEqual(set(entry.keys()), {'line', 'rule'})
            self.assertIsInstance(entry['line'], int)
            self.assertIn(entry['rule'], AUDIT_RULES)
        dumped = json.dumps(list(res.audit), ensure_ascii=False)
        for line in lines:
            self.assertNotIn(line, dumped)
        self.assertNotIn('54', dumped)

        second = check_final_answer(res.text, _msgs(LIST_2))
        self.assertFalse(second.changed)
        self.assertEqual(second.text, res.text)


class Row2ApplicationTraceTests(AgentFixture):
    MODES = ('agent', 'legacy')

    def chat(self, mode, model, text):
        app = Application(self.store_a, {}, infer=model, orchestrator=mode)
        cid = self.store_a.new_conversation('C-001')['conversation_id']
        return self.say(app, text, cid)

    def test_audit_recorded_even_when_unchanged_in_both_modes(self):
        reply = 'Thời hạn đổi trả là 30 ngày.'
        for mode in self.MODES:
            result = self.chat(mode, ScriptedModel(say(reply)), 'Thời hạn đổi trả là bao lâu?')
            with self.subTest(mode=mode):
                self.assertEqual(result['message'], reply)
                self.assertNotIn('answer_check', result['trace'])
                self.assertNotIn('answer_check_detail', result['trace'])
                self.assertEqual(result['trace']['answer_check_audit'], [{'line': 1, 'rule': 'deadline_number'}])

    def test_blocking_logistics_records_answer_check_and_detail(self):
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
                self.assertNotIn('answer_check_audit', result['trace'])

    def test_clean_turn_has_no_answer_check_or_audit(self):
        for mode in self.MODES:
            model = ScriptedModel(
                call(('get_order', {'order_id': 'O-701'})),
                say('Đơn O-701 hiện đã được giao rồi ạ.'),
            )
            result = self.chat(mode, model, 'Đơn O-701 giao chưa ạ?')
            with self.subTest(mode=mode):
                self.assertNotIn('answer_check', result['trace'])
                self.assertNotIn('answer_check_detail', result['trace'])
                self.assertNotIn('answer_check_audit', result['trace'])


class Row2RunnerAuditTests(unittest.TestCase):
    def test_runner_records_answer_check_audit_when_present_and_omits_when_clean(self):
        case = copy.deepcopy(runner.load_dataset()[0])
        case['turns'] = [
            {
                'user': 'Thời hạn đổi trả của shop là bao lâu?',
                'fake_model': [{'say': 'Thời hạn đổi trả là 30 ngày.'}],
                'expect': {'action': 'reply'},
            },
            {
                'user': 'Cảm ơn shop nhé.',
                'fake_model': [{'say': 'Dạ em chào anh/chị ạ.'}],
                'expect': {'action': 'reply'},
            },
        ]
        case['final_state'] = {}
        record = runner.run_scenario(case, runner.ScriptedGateway(), 'fake')
        self.assertTrue(record['passed'], record.get('failures'))

        first_turn, second_turn = record['turns']
        self.assertNotIn('answer_check', first_turn)
        self.assertEqual(first_turn['answer_check_audit'], [{'line': 1, 'rule': 'deadline_number'}])
        dumped = json.dumps(first_turn['answer_check_audit'], ensure_ascii=False)
        self.assertNotIn('30', dumped)
        self.assertNotIn('Thời hạn', dumped)

        self.assertNotIn('answer_check', second_turn)
        self.assertNotIn('answer_check_audit', second_turn)


if __name__ == '__main__':
    unittest.main()
