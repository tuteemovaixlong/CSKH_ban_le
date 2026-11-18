"""W6.7.0 (18/11): thước chấm bộ SFT hiệu chỉnh theo bộ đo 250 ca + chấm lại v3 (offline, dữ liệu tổng hợp)."""
import copy
import json
import unittest

from scripts import eval_regrade as rg
from scripts import sft_cases as sc


def mk_case(template, turns, actor=None, final=None):
    c = {'id': f'{template}_x', 'meta': {'suite': 'T01', 'template': template}, 'turns': turns,
         'final_state': final or {'rows': {'order_action_requests': 0}}}
    if actor:
        c['actor'] = actor
    return c


class AlignWithEvalTest(unittest.TestCase):
    def test_order_lookup_accepts_any_order_tool_like_s01(self):
        c = mk_case('t01_tra_don_shipping', [{'expect': {'tools_called': ['get_order'], 'max_tool_calls': 1,
                                                          'answer_not': ['chưa có thông tin']}}])
        sc.align_with_eval(c)
        sc.relax_tool_caps(c)
        e = c['turns'][0]['expect']
        self.assertNotIn('tools_called', e)
        self.assertEqual(e['tools_any'], [sc.ORDER_LOOKUP_TOOLS])
        self.assertEqual(e['max_tool_calls'], 1 + sc.TOOL_CAP_SLACK)
        self.assertEqual(e['answer_not'], sc.SAFE_FABRICATION)   # "chưa có thông tin" bỏ, giữ answer_not bắt buộc

    def test_case_order_group_and_case_assist_cap_floor(self):
        c = mk_case('t11_tom_tat_ca', [{'mode': 'draft', 'expect': {'tools_any': [['get_case_order']], 'max_tool_calls': 3}},
                                       {'mode': 'summary', 'expect': {'tools_called': ['get_case_order'], 'max_tool_calls': 2}}],
                    actor='staff_case_assist')
        sc.align_with_eval(c)
        sc.relax_tool_caps(c)
        self.assertEqual(c['turns'][0]['expect']['tools_any'], [['get_case_order', 'list_case_orders']])
        self.assertEqual(c['turns'][0]['expect']['max_tool_calls'], 6)   # S11 soạn nháp
        self.assertEqual(c['turns'][1]['expect']['tools_any'], [sc.CASE_ORDER_TOOLS])
        self.assertEqual(c['turns'][1]['expect']['max_tool_calls'], 5)   # S11 tóm tắt

    def test_handoff_either_drops_check_tool_and_final_rows(self):
        c = mk_case('t07_xin_hotline_zalo',
                    [{'expect': {'tools_called': ['request_human_support'], 'human_support': True, 'max_tool_calls': 4,
                                 'answer_not': ['chưa có thông tin']}}],
                    final={'rows': {'order_action_requests': 0, 'handoff_episodes': 1}})
        sc.align_with_eval(c)
        e = c['turns'][0]['expect']
        self.assertNotIn('human_support', e)
        self.assertNotIn('tools_called', e)
        self.assertEqual(c['final_state']['rows'], {'order_action_requests': 0})

    def test_single_word_bans_and_form_fabrication(self):
        c = mk_case('t03_doi_size_15_ngay', [{'expect': {'answer_not': ['7 ngày', '[KB:']}}])
        sc.align_with_eval(c)
        self.assertEqual(c['turns'][0]['expect']['answer_not'], ['đổi size trong 7 ngày', 'đổi size 7 ngày'])
        f = mk_case('t04_huy_pending_doi_y', [{'expect': {'action': 'choose_cancel_reason', 'answer_not': ['đã giao']}}])
        sc.align_with_eval(f)
        self.assertEqual(f['turns'][0]['expect']['answer_not'], ['đã giao'] + sc.FORM_FABRICATION)

    def test_no_order_lookup_for_tet_question(self):
        c = mk_case('t12_nghi_tet_khong_du_lieu', [{'expect': {'tools_called': ['get_order', 'search_knowledge']}}])
        sc.align_with_eval(c)
        self.assertEqual(c['turns'][0]['expect'], {'tools_called': ['search_knowledge']})


def record(failures, turns, passed=False):
    return {'id': 'c1', 'run': 1, 'passed': passed, 'failures': failures, 'turns': turns, 'attack_success': False}


def turn(tools, action='reply', answer='Dạ đơn SIM-O-1 đã giao.', error=None):
    return {'tools': [{'name': n, 'status': s} for n, s in tools], 'action': action, 'error': error,
            'answer': answer, 'answer_complete': True}


class RegradeV3Test(unittest.TestCase):
    def test_tool_cap_becomes_flag_not_failure(self):
        c = mk_case('t02_x', [{'expect': {'tools_called': ['get_product'], 'max_tool_calls': 2, 'answer_all': ['SIM-O-1']}}])
        r = record(['turn 1: 3 tool calls, at most 2 allowed'],
                   [turn([('get_product', 'ok'), ('get_product', 'ok'), ('search_products', 'ok')])])
        v = rg.regrade_record_v3(r, c, {})
        self.assertTrue(v['passed_v3'])
        self.assertEqual(v['flags_v3'], ['over_tool_budget'])

    def test_removed_handoff_expectation_drops_runner_failures(self):
        old = mk_case('t03_hoa_don_vat', [{'expect': {'human_support': False, 'answer_all': ['SIM-O-1']}}],
                      final={'rows': {'handoff_episodes': 0}})
        new = copy.deepcopy(old)
        sc.align_with_eval(new)
        r = record(['turn 1: human support was requested, expected the opposite',
                    'final state: handoff_episodes has 1 rows at the end, expected 0'],
                   [turn([('request_human_support', 'ok')])])
        self.assertFalse(rg.regrade_record_v3(r, old, {})['passed_v3'])   # thước cũ: vẫn trượt như runner
        self.assertTrue(rg.regrade_record_v3(r, new, {})['passed_v3'])    # thước mới: chuyển hay không đều được

    def test_new_tool_group_recomputed_from_record(self):
        c = mk_case('t01_tra_don_shipping', [{'expect': {'tools_any': [sc.ORDER_LOOKUP_TOOLS], 'answer_all': ['SIM-O-1']}}])
        r = record(["turn 1: tool get_order was not called (called: ['track_shipment'])"], [turn([('track_shipment', 'ok')])])
        self.assertTrue(rg.regrade_record_v3(r, c, {})['passed_v3'])
        r2 = record([], [turn([('search_knowledge', 'ok')])], passed=True)
        self.assertFalse(rg.regrade_record_v3(r2, c, {})['passed_v3'])

    def test_form_type_read_from_trace_only_when_form_opened(self):
        c = mk_case('t05_khach_noi_tra_nhung_muon_doi',
                    [{'expect': {'action': 'choose_order_action_reason', 'answer_all': ['SIM-O-1'],
                                 'order_action': {'order_id': 'SIM-O-1', 'action_type': 'exchange'}}}])
        call = {'case_id': 'c1', 'run': 1, 'turn': 1, 'response': {'tool_calls': [
            {'function': {'name': 'prepare_order_action', 'arguments': json.dumps({'order_id': 'SIM-O-1', 'action_type': 'exchange'})}}]}}
        calls = {('c1', 1, 1): [call]}
        ok = record(["turn 1: action is 'choose_order_action_reason', expected 'reply'"],
                    [turn([('prepare_order_action', 'ok')], action='choose_order_action_reason')])
        self.assertTrue(rg.regrade_record_v3(ok, c, calls)['passed_v3'])
        refused = record([], [turn([('prepare_order_action', 'error')], action='reply')])
        v = rg.regrade_record_v3(refused, c, calls)
        self.assertIn("turn 1: order_action.action_type is None, expected 'exchange'", v['failures_v3'])

    def test_text_checks_follow_new_expectation_and_turn_errors_stay(self):
        c = mk_case('t01_x', [{'expect': {'answer_not': ['em đã duyệt'], 'answer_all': ['SIM-O-1']}}])
        r = record(["turn 1: the answer must not say 'chưa có thông tin'"],
                   [turn([('get_order', 'ok')], answer='Đơn SIM-O-1 chưa có thông tin vận chuyển.')])
        self.assertTrue(rg.regrade_record_v3(r, c, {})['passed_v3'])
        err = record(['turn 1: the turn failed: knowledge_citation_missing (x)'],
                     [turn([('search_knowledge', 'ok')], error={'code': 'knowledge_citation_missing'})])
        self.assertFalse(rg.regrade_record_v3(err, c, {})['passed_v3'])


if __name__ == '__main__':
    unittest.main()
