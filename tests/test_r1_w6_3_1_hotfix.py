"""W6.3.1: synthetic test-first coverage; no independent evaluation cases."""
import copy
import json
import unittest

from agent_protocol import ProtocolError, validate_tool
from retailops.workflow.answer_check import check_final_answer
from scripts import run_agent_scenarios as runner
from test_r1_w3_2_agent_loop import AgentFixture, ScriptedModel, call, say


HANDOFF_NOTE = ('Em chưa chuyển được cuộc trò chuyện cho nhân viên; anh/chị nhắn '
                '"gặp nhân viên" để em thử lại ạ.')


def messages(payload, role='tool'):
    return [{'role': role, 'content': json.dumps(payload, ensure_ascii=False)}]


class HandoffTests(AgentFixture):
    def test_reason_lengths_create_real_handoffs(self):
        for length in (1, 65, 300, 1000):
            with self.subTest(length=length):
                cid = self.store_a.new_conversation('C-001')['conversation_id']
                model = ScriptedModel(call(('request_human_support', {'reason': 'x' * length})),
                                      say('Em đã chuyển yêu cầu sang bộ phận CSKH ạ.'))
                result = self.say(self.app(model), 'Tôi cần đổi địa chỉ nhận hàng', cid)
                self.assertEqual(result.get('human_support', {}).get('status'), 'escalated_to_human')
                with self.store_a.connection() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM handoff_episodes WHERE conversation_id=?',
                                                (cid,)).fetchone()[0], 1)

    def test_reason_rejection_and_other_limits_stay(self):
        for args in ({'reason': 'x' * 1001}, {'reason': ''}, {'reason': '   '}):
            with self.subTest(args=args), self.assertRaises(ProtocolError):
                validate_tool('request_human_support', args)
        for name, args in (('get_order', {'order_id': 'x' * 65}),
                           ('search_knowledge', {'query': 'x' * 201}),
                           ('prepare_order_action', {'order_id': 'O-1', 'target_variant': 'x' * 201,
                                                     'action_type': 'exchange'})):
            with self.subTest(name=name), self.assertRaises(ProtocolError):
                validate_tool(name, args)

    def test_unfounded_handoff_claims_need_success_this_turn(self):
        claims = ('Em đã chuyển cuộc trò chuyện cho nhân viên ạ.',
                  'Em vừa chuyển yêu cầu sang bộ phận CSKH.',
                  'Ca của anh/chị đã được chuyển tới người thật.',
                  'Đã chuyển yêu cầu sang bộ phận hỗ trợ.',
                  'Em đã ghi nhận yêu cầu của anh/chị và chuyển cho nhân viên hỗ trợ.')
        for claim in claims:
            for payload in ({'error': 'tool_not_allowed'}, {}, {'status': 'pending'}):
                with self.subTest(claim=claim, payload=payload):
                    self.assertEqual(check_final_answer(claim, messages(payload)).text, HANDOFF_NOTE)
            self.assertEqual(check_final_answer(claim, messages({'status': 'escalated_to_human'})).text, claim)
            self.assertEqual(check_final_answer(claim, messages({'status': 'escalated_to_human'}, 'user')).text,
                             HANDOFF_NOTE)

    def test_questions_offers_and_failure_note_are_preserved(self):
        for text in ('Em chuyển nhân viên cho anh/chị nhé?',
                     'Nếu anh/chị muốn, em chuyển yêu cầu cho nhân viên ạ.',
                     'Anh/chị muốn em chuyển cho nhân viên không ạ?', HANDOFF_NOTE):
            with self.subTest(text=text):
                self.assertFalse(check_final_answer(text).changed)


class DeadlineTests(unittest.TestCase):
    def test_server_deadline_facts_survive_only_with_tool_evidence(self):
        cases = (
            ('Đơn SIM-O-1 còn trong hạn trả hàng ạ.', {'eligibility': {'within_return_window': True}}),
            ('Đơn SIM-O-1 đang trên đường vận chuyển qua GHN và vẫn trong thời hạn giao dự kiến ạ.',
             {'shipment': {'promised_delivery_by': '2026-11-12T00:00:00Z'}}),
            ('Đơn của anh/chị còn hạn đổi size 15 ngày ạ.', {'eligibility': {'size_exchange_window_days': 15}}),
        )
        for text, payload in cases:
            with self.subTest(text=text):
                self.assertEqual(check_final_answer(text, messages(payload)).text, text)
                self.assertTrue(check_final_answer(text).changed)

    def test_each_deadline_field_and_false_eligibility_is_evidence(self):
        for key in ('return_window_days', 'size_exchange_window_days', 'warranty_window_days', 'warranty_days'):
            text = 'Thời hạn đổi trả là 17 ngày ạ.'
            with self.subTest(key=key):
                self.assertFalse(check_final_answer(text, messages({'nested': [{key: 17}]})).changed)
        for key in ('within_return_window', 'within_size_exchange_window', 'within_warranty'):
            with self.subTest(key=key):
                self.assertFalse(check_final_answer('Đơn đã quá hạn đổi trả ạ.', messages({key: False})).changed)
        for key in ('promised_delivery_by', 'estimated_delivery_at', 'latest_estimated_delivery_at'):
            with self.subTest(key=key):
                self.assertFalse(check_final_answer('Đơn còn trong thời hạn giao dự kiến ạ.',
                                                    messages({key: '2026-11-12T00:00:00Z'})).changed)

    def test_fee_logistics_and_unknown_numbers_still_need_citations(self):
        evidence = messages({'return_window_days': 7, 'size_exchange_window_days': 15,
                             'warranty_days': 90, 'within_return_window': True})
        for text in ('Shop miễn phí ship đổi size lần đầu ạ.', 'Shop đổi tận nhà trong 15 ngày ạ.',
                     'Shop cho đổi trong 30 ngày ạ.', 'Shop cho đổi trong 7 đến 30 ngày ạ.'):
            with self.subTest(text=text):
                self.assertTrue(check_final_answer(text, evidence).changed)
        self.assertTrue(check_final_answer('Thời hạn trả là 1 ngày ạ.', messages({'return_window_days': True})).changed)


class RunnerRailTests(unittest.TestCase):
    def case(self):
        case = copy.deepcopy(runner.load_dataset()[0])
        case['turns'] = [{'user': 'Cho tôi gặp nhân viên thật',
                          'fake_model': [{'call': [{'name': 'get_order', 'arguments': {'order_id': 'O-701'}}]},
                                         {'say': 'Câu trả lời tổng hợp không dùng.'}],
                          'expect': {'human_support': True}}]
        case['final_state'] = {}
        return case

    def test_rail_can_leave_two_steps_unused(self):
        record = runner.run_scenario(self.case(), runner.ScriptedGateway(), 'fake')
        self.assertTrue(record['passed'], record['failures'])
        self.assertTrue(record['turns'][0]['rail_answered'])
        self.assertEqual(record['turns'][0]['model_calls'], 0)

    def test_rail_still_grades_tools_called(self):
        case = self.case()
        case['turns'][0]['expect']['tools_called'] = ['get_order']
        record = runner.run_scenario(case, runner.ScriptedGateway(), 'fake')
        self.assertFalse(record['passed'])
        self.assertTrue(any('get_order' in error for error in record['failures']))
        self.assertFalse(any('scripted reply(ies)' in error for error in record['failures']))

    def test_model_turn_still_rejects_unused_steps(self):
        case = copy.deepcopy(runner.load_dataset()[0])
        case['turns'][0]['fake_model'].append({'say': 'Unused model step.'})
        record = runner.run_scenario(case, runner.ScriptedGateway(), 'fake')
        self.assertTrue(any('scripted reply(ies)' in error for error in record['failures']))


if __name__ == '__main__':
    unittest.main()
