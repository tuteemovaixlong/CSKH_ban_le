"""W3.2 item 5 (W3.2-D3, W3.2-D11): the final-answer check and the switch between the two agents.

Isolated: scripted fake gateways, no model, no network. The check reads the wording of the model's answer and
the tool results of the turn; it never reads the customer's message and holds no script for a situation.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from retailops.business.application import Application
from retailops.config import Settings
from retailops.knowledge.repository import KnowledgeRepository
from retailops.workflow.answer_check import CLAIM_NOTE, POLICY_NOTE, check_final_answer, tool_evidence
from test_r1_w3_2_agent_loop import AgentFixture, ScriptedModel, call, say, tool_data

CITATION = '[KB:0123456789abcdef01234567]'


def tool_message(name, payload):
    return {'role': 'tool', 'tool_name': name, 'content': json.dumps(payload, ensure_ascii=False)}


class FinalAnswerCheckTests(unittest.TestCase):
    def test_uncited_policy_promises_are_removed(self):
        for promise in ('Shop đổi size tận nhà miễn phí 2 chiều cho anh/chị ạ.',
                        'Anh/chị được đổi hàng trong 7 ngày kể từ khi nhận hàng.',
                        'Phí ship do shop chịu hoàn toàn.',
                        'Em sẽ đổi mới 1-1 cho anh/chị.',
                        'Shipper sẽ đến lấy lại hàng cũ khi giao hàng mới.',
                        'Thời hạn đổi trả là 30 ngày.'):
            with self.subTest(promise=promise):
                checked = check_final_answer(promise)
                self.assertEqual((checked.dropped_policy, checked.dropped_claims), (1, 0))
                self.assertEqual(checked.text, POLICY_NOTE)

    def test_the_facts_around_a_removed_promise_stay_in_place(self):
        checked = check_final_answer('Đơn O-701 đã giao ngày 2 tháng này.\nShop miễn phí đổi trả 2 chiều ạ. Anh/chị chọn biến thể trên form nhé.')
        self.assertTrue(checked.text.startswith('Đơn O-701 đã giao ngày 2 tháng này.\nAnh/chị chọn biến thể trên form nhé.'))
        self.assertNotIn('miễn phí', checked.text)
        self.assertTrue(checked.text.endswith(POLICY_NOTE))

    def test_cited_hedged_and_question_sentences_stay(self):
        for text in (f'Theo chính sách, đổi hàng miễn phí trong 7 ngày kể từ khi nhận hàng {CITATION}.',
                     f'Đổi hàng miễn phí trong 7 ngày kể từ khi nhận hàng. {CITATION}',
                     'Em chưa có thông tin về phí đổi hàng, em xin phép kiểm tra thêm.',
                     'Kho chính sách không nêu phí ship cho trường hợp này.',
                     'Anh/chị có muốn đổi miễn phí không ạ?',
                     'Em chưa thể xác nhận thời hạn đổi trả cho đơn này.'):
            with self.subTest(text=text):
                checked = check_final_answer(text)
                self.assertFalse(checked.changed)
                self.assertEqual(checked.text, text)

    def test_a_structured_warranty_fact_from_a_tool_is_not_a_promise(self):
        messages = [tool_message('get_product', {'product': {'id': 'P-102', 'warranty_days': 90}})]
        self.assertFalse(check_final_answer('Sản phẩm này được bảo hành 90 ngày ạ.', messages).changed)
        self.assertTrue(check_final_answer('Sản phẩm này được bảo hành 120 ngày ạ.', messages).changed)
        self.assertTrue(check_final_answer('Sản phẩm này được bảo hành 90 ngày ạ.').changed)  # no tool shows it
        self.assertEqual(tool_evidence(messages).warranty_days, frozenset({90}))

    def test_order_facts_and_plain_acknowledgements_stay(self):
        for text in ('Đơn dự kiến giao trong 2 ngày nữa ạ.',
                     'Tổng giá trị đơn hàng là 299.000 ₫.',
                     'Em đã mở bảng chọn lý do trên màn hình, anh/chị chọn lý do rồi bấm xác nhận nhé.',
                     'Em đã ghi nhận yêu cầu của anh/chị và chuyển cho nhân viên hỗ trợ.',
                     'Đơn hàng đã được giao vào hôm qua.',
                     'Anh/chị đã đổi ý nên muốn hủy đơn phải không ạ?',
                     'Em chưa thể hủy đơn qua chat.',
                     'Sản phẩm này tặng kèm quà miễn phí ạ.'):
            with self.subTest(text=text):
                self.assertFalse(check_final_answer(text).changed)

    def test_claims_of_changes_the_server_did_not_make_are_removed(self):
        for claim in ('Em đã hủy đơn O-101 cho anh/chị rồi ạ.',
                      'Đơn của anh/chị đã được hoàn tiền thành công.',
                      'Em đã gửi yêu cầu đổi hàng cho anh/chị.',
                      'Shop đã đổi sang size L cho anh/chị rồi.',
                      'Yêu cầu của anh/chị đã được gửi đi.',
                      'Đơn O-101 đã được hủy thành công.'):
            with self.subTest(claim=claim):
                checked = check_final_answer(claim)
                self.assertEqual((checked.dropped_policy, checked.dropped_claims), (0, 1))
                self.assertEqual(checked.text, CLAIM_NOTE)

    def test_a_cancelled_order_that_a_tool_shows_can_be_reported(self):
        messages = [tool_message('get_order', {'order': {'id': 'O-710', 'status': 'cancelled'}})]
        self.assertFalse(check_final_answer('Đơn O-710 đã được hủy rồi ạ.', messages).changed)
        self.assertTrue(check_final_answer('Em đã hủy đơn O-710 cho anh/chị rồi ạ.',
                                           [tool_message('get_order', {'order': {'id': 'O-710', 'status': 'pending'}})]).changed)
        track = [tool_message('track_shipment', {'order_id': 'O-710', 'order_status': 'cancelled', 'shipment': {}})]
        self.assertTrue(tool_evidence(track).cancelled)

    def test_both_notes_come_once_and_a_stranded_citation_is_kept(self):
        checked = check_final_answer(f'Shop miễn phí đổi trả 2 chiều ạ. Em đã hủy đơn O-101 cho anh/chị theo chính sách {CITATION}.')
        self.assertEqual((checked.dropped_policy, checked.dropped_claims), (1, 1))
        self.assertEqual(checked.text.count(POLICY_NOTE), 1)
        self.assertEqual(checked.text.count(CLAIM_NOTE), 1)
        self.assertIn(CITATION, checked.text)  # the removed sentence must not leave its source unreferenced

    def test_the_output_of_the_check_passes_the_check(self):
        first = check_final_answer('Shop miễn phí đổi trả 2 chiều ạ. Em đã hủy đơn O-101 cho anh/chị rồi.')
        again = check_final_answer(first.text)
        self.assertFalse(again.changed)
        self.assertEqual(again.text, first.text)

    def test_empty_or_missing_text_is_returned_as_it_is(self):
        for text in ('', '   ', None):
            self.assertFalse(check_final_answer(text).changed)
        self.assertEqual(check_final_answer(None).text, '')

    def test_unreadable_tool_results_are_ignored(self):
        messages = [{'role': 'tool', 'tool_name': 'x', 'content': 'not json'}, {'role': 'tool', 'tool_name': 'y', 'content': '[1, 2]'},
                    {'role': 'user', 'content': 'hi'}, None, {'role': 'tool', 'content': 5}]
        self.assertFalse(tool_evidence(messages).cancelled)


class FinalAnswerInApplicationTests(AgentFixture):
    """The same check runs after both agents, so a rollback to the legacy graph keeps it."""
    MODES = ('agent', 'legacy')

    def chat(self, mode, model, text):
        app = Application(self.store_a, {}, infer=model, orchestrator=mode)
        cid = self.store_a.new_conversation('C-001')['conversation_id']
        return self.say(app, text, cid), cid

    def test_an_uncited_exchange_promise_is_removed_and_the_fact_stays(self):
        for mode in self.MODES:
            model = ScriptedModel(call(('get_order', {'order_id': 'O-701'})),
                                  say('Đơn O-701 đã giao. Shop sẽ đổi size tận nhà miễn phí 2 chiều cho anh/chị ạ.'))
            result, cid = self.chat(mode, model, 'Em muốn đổi size cho đơn O-701')
            with self.subTest(mode=mode):
                self.assertIn('Đơn O-701 đã giao.', result['message'])
                self.assertNotIn('miễn phí', result['message'])
                self.assertNotIn('tận nhà', result['message'])
                self.assertIn(POLICY_NOTE, result['message'])
                self.assertEqual(result['trace']['answer_check'], {'dropped_policy_promises': 1, 'dropped_done_claims': 0})
                self.assertEqual(self.store_a.history('C-001', cid)[-1]['content'], result['message'])  # what is stored is what was shown

    def test_a_promise_backed_by_a_retrieved_citation_is_kept(self):
        document = {'chunk': 'Đổi hàng miễn phí trong 7 ngày kể từ khi nhận hàng nếu còn nguyên tem mác.',
                    'source_key': 'policies/returns.md', 'title': 'Chính sách đổi trả', 'score': 0.9}
        self.store_a.schema = 'tenant_alpha'  # a tenant with an indexed knowledge base

        def cites(messages):
            citation = tool_data(messages)['results'][0]['citation_id']
            return say(f'Theo chính sách, đổi hàng miễn phí trong 7 ngày kể từ khi nhận hàng [{citation}].')
        for mode in self.MODES:
            model = ScriptedModel(call(('search_knowledge', {'query': 'chính sách đổi trả'})), cites)
            with patch.object(KnowledgeRepository, 'search', lambda repo, query, limit=5: [dict(document)]):
                result, _ = self.chat(mode, model, 'Cho em hỏi chính sách đổi trả của shop')
            with self.subTest(mode=mode):
                self.assertIn('miễn phí trong 7 ngày', result['message'])
                self.assertNotIn('answer_check', result['trace'])
                self.assertEqual([s['source_key'] for s in result['sources']], ['policies/returns.md'])

    def test_a_claim_that_a_change_was_made_is_removed_while_the_form_stays_open(self):
        for mode in self.MODES:
            model = ScriptedModel(call(('prepare_order_action', {'order_id': 'O-705', 'action_type': 'cancel'})),
                                  say('Em đã hủy đơn O-705 cho anh/chị rồi ạ!'))
            result, _ = self.chat(mode, model, 'Tôi muốn hủy đơn O-705')
            with self.subTest(mode=mode):
                self.assertEqual(result['message'], CLAIM_NOTE)
                self.assertEqual(result['trace']['answer_check'], {'dropped_policy_promises': 0, 'dropped_done_claims': 1})
                self.assertEqual(result['action'], 'choose_cancel_reason')  # the form is still the only way to send it
                with self.store_a.connection() as db:
                    self.assertEqual(db.execute("SELECT status FROM orders WHERE id='O-705'").fetchone()[0], 'pending')

    def test_a_cancellation_that_the_order_record_shows_can_be_reported(self):
        self.add_order('O-710', 'cancelled', 'Đen / L')
        for mode in self.MODES:
            model = ScriptedModel(call(('get_order', {'order_id': 'O-710'})), say('Đơn O-710 đã được hủy rồi ạ.'))
            result, _ = self.chat(mode, model, 'Đơn O-710 thế nào rồi shop')
            with self.subTest(mode=mode):
                self.assertEqual(result['message'], 'Đơn O-710 đã được hủy rồi ạ.')
                self.assertNotIn('answer_check', result['trace'])

    def test_the_replies_of_the_safety_rails_are_not_rewritten(self):
        model = ScriptedModel(say('Không được gọi tới.'))
        result, _ = self.chat('agent', model, 'Cho tôi gặp nhân viên thật')
        self.assertEqual(result['trace']['safety_rail'], 'human_request')
        self.assertNotIn('answer_check', result['trace'])


class AgentModeSwitchTests(AgentFixture):
    """W3.2-D11: the new loop is the default and the old graph comes back by configuration alone."""
    TEXT = 'Em muốn đổi size L cho đơn O-701'

    def model(self):
        return ScriptedModel(
            call(('prepare_order_action', {'order_id': 'O-701', 'action_type': 'exchange', 'target_variant': 'size L'})),
            say('Em đã mở form đổi hàng, anh/chị chọn lý do rồi bấm xác nhận nhé.'))

    def run_chat(self, environment=None, **options):
        with patch.dict(os.environ, environment or {}):
            for name in ('RETAILOPS_AGENT_MODE', 'RETAILOPS_ORCHESTRATOR'):
                if not (environment or {}).get(name):
                    os.environ.pop(name, None)
            app = Application(self.store_a, {}, infer=self.model(), **options)
        cid = self.store_a.new_conversation('C-001')['conversation_id']
        return app, self.say(app, self.TEXT, cid)

    def test_the_new_loop_is_the_default(self):
        app, result = self.run_chat()
        self.assertEqual(app.agent_mode, 'agent')
        self.assertEqual((result['trace']['orchestrator'], result['trace']['agent_mode']), ('langgraph', 'agent'))
        self.assertEqual(result['action'], 'choose_order_action_reason')

    def test_the_environment_alone_brings_the_old_graph_back_with_the_same_form(self):
        _, new = self.run_chat()
        app, old = self.run_chat({'RETAILOPS_AGENT_MODE': 'legacy'})
        self.assertEqual(app.agent_mode, 'legacy')
        self.assertEqual((old['trace']['orchestrator'], old['trace']['agent_mode']), ('multiagent_langgraph', 'legacy'))
        self.assertEqual(old['trace']['supervisor_intent'], 'dispute_complaint')
        self.assertEqual(old['action'], new['action'])
        self.assertEqual(old['order_action'], new['order_action'])  # same request model whichever agent answered
        self.assertEqual(new['order_action']['target_variant_id'], 'P-102-L-Đen')

    def test_switching_back_is_the_same_single_setting(self):
        for value, expected in (('legacy', 'legacy'), ('agent', 'agent'), (' LEGACY ', 'legacy')):
            app, _ = self.run_chat({'RETAILOPS_AGENT_MODE': value})
            self.assertEqual(app.agent_mode, expected, value)

    def test_the_older_orchestrator_names_are_still_understood_and_the_new_setting_wins(self):
        self.assertEqual(self.run_chat({'RETAILOPS_ORCHESTRATOR': 'multi_agent'})[0].agent_mode, 'legacy')
        self.assertEqual(self.run_chat({'RETAILOPS_ORCHESTRATOR': 'single_agent'})[0].agent_mode, 'agent')
        self.assertEqual(self.run_chat({'RETAILOPS_ORCHESTRATOR': 'multi_agent', 'RETAILOPS_AGENT_MODE': 'agent'})[0].agent_mode, 'agent')
        app, _ = self.run_chat({'RETAILOPS_AGENT_MODE': 'agent'}, orchestrator='multi_agent')
        self.assertEqual((app.agent_mode, app.orchestrator), ('legacy', 'multi_agent'))  # an explicit argument beats the environment

    def test_an_unknown_value_stops_startup_instead_of_choosing_a_mode(self):
        with patch.dict(os.environ, {'RETAILOPS_AGENT_MODE': 'turbo'}):
            with self.assertRaises(ValueError):
                Application(self.store_a, {}, infer=self.model())
        with self.assertRaises(ValueError):
            Application(self.store_a, {}, infer=self.model(), orchestrator='turbo')

    def test_the_startup_settings_validate_and_show_the_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            base = {'RETAILOPS_PUBLIC_ORIGIN': 'https://retailops.example.com', 'RETAILOPS_DATA_MODE': 'persistent-demo',
                    'RETAILOPS_OUTPUT': directory}
            self.assertEqual(Settings.from_environment('public', base).summary()['agent_mode'], 'agent')
            legacy = Settings.from_environment('public', {**base, 'RETAILOPS_AGENT_MODE': 'legacy'})
            self.assertEqual(legacy.summary()['agent_mode'], 'legacy')
            with self.assertRaises(ValueError):
                Settings.from_environment('public', {**base, 'RETAILOPS_AGENT_MODE': 'turbo'})


if __name__ == '__main__':
    unittest.main()
