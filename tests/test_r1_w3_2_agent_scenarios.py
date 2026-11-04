"""W3.2 item 7 (W3.2-D12): the agent scenarios and the runner that plays them.

Isolated: the scenarios are played with a scripted fake gateway or with a fake vLLM under the real HTTP adapter.
No model, no Colab, no network, no customer data. What is checked here is the code around the model and the
runner itself; how good a real model is at the scenarios is the owner's measurement (`--endpoint`).
"""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from agent_protocol import TOOLS
from gemma_fakes import FIXTURE_ENDPOINT, FIXTURE_KEY, FIXTURE_MODEL, FakeVllm, chat_reply
from scripts import check_eval_dataset as checker
from scripts import run_agent_scenarios as runner

DATASET = Path(runner.DEFAULT_DATASET)


def scenarios():
    return runner.load_dataset(DATASET)


def by_id(name):
    return next(s for s in scenarios() if s['id'] == name)


def run_one(scenario):
    return runner.run_scenario(scenario, runner.ScriptedGateway(), 'fake')


class RecordingVllm(FakeVllm):
    """The fake vLLM that also remembers where each request went and what it carried."""

    def __init__(self, script, **options):
        super().__init__(script, **options)
        self.requests = []

    def _open(self, opener, request, *args, **kwargs):
        self.requests.append((request.full_url, dict(request.header_items())))
        return super()._open(opener, request, *args, **kwargs)


def replay(steps_by_scenario):
    """A fake-vLLM script that answers each HTTP request with the next scripted step, in dataset order."""
    queue = deque(step for steps in steps_by_scenario for step in steps)

    def script(payload):
        step = queue.popleft()
        text = runner.fill_templates(step.get('say') or step.get('text') or '', payload['messages'])
        calls = [(c['name'], c['arguments']) for c in step.get('call', [])]
        return chat_reply(text, calls)
    return script, queue


def all_steps(selected):
    return [turn['fake_model'] for s in selected for turn in s['turns']]


class DatasetFormatTests(unittest.TestCase):
    def test_the_shipped_dataset_passes_the_format_check(self):
        cases = scenarios()
        self.assertTrue(20 <= len(cases) <= 30, len(cases))
        self.assertEqual({c['category'] for c in cases}, set(checker.W32_CATEGORIES))

    def test_the_handoff_situations_are_all_covered(self):
        ids = {c['id'] for c in scenarios()}
        for situation in ('lookup_delivered_order_status', 'cancel_pending_order_opens_form', 'return_delivered_order_opens_form',
                          'exchange_to_another_size', 'exchange_to_another_colour', 'cancel_delivered_order_refused',
                          'follow_up_target_chosen_in_chat_keeps_the_order', 'off_topic_general_question_is_tool_free',
                          'policy_return_window_is_cited', 'human_request_goes_straight_to_staff'):
            self.assertIn(situation, ids)

    def test_the_lists_of_the_format_check_follow_the_code(self):
        self.assertEqual(checker.W32_TOOLS, {t['function']['name'] for t in TOOLS})
        self.assertEqual(checker.W32_FIXTURES, set(runner.FIXTURES))
        self.assertEqual(checker.W32_TABLES, set(runner.COUNTED_TABLES))

    def test_the_default_check_command_validates_both_datasets(self):
        out = io.StringIO()
        with patch.object(sys, 'argv', ['check_eval_dataset.py']), contextlib.redirect_stdout(out):
            checker.main()
        lines = out.getvalue().splitlines()
        self.assertEqual(
            [l.split()[1] for l in lines],
            ['baseline_v1.jsonl', 'agent_scenarios_w3_2.jsonl', 'agent_scenarios_w4.jsonl'],
        )
        self.assertTrue(all(l.startswith('EVAL_DATASET_OK') for l in lines))
        out = io.StringIO()
        with patch.object(sys, 'argv', ['check_eval_dataset.py', str(DATASET)]), contextlib.redirect_stdout(out):
            checker.main()
        self.assertIn('scenarios=' + str(len(scenarios())), out.getvalue())

    def assert_invalid(self, mutate, why):
        cases = copy.deepcopy(scenarios())
        mutate(cases)
        with self.assertRaises(AssertionError, msg=why):
            checker.validate_w32(cases)

    def test_a_malformed_dataset_is_refused(self):
        def first_turn(cases, name=None):
            case = cases[0] if name is None else next(c for c in cases if c['id'] == name)
            return case['turns'][0]
        mutations = {
            'an unknown tool in the script': lambda c: first_turn(c)['fake_model'][0]['call'][0].update(name='delete_everything'),
            'a duplicate id': lambda c: c[1].update(id=c[0]['id']),
            'an id with capital letters': lambda c: c[0].update(id='Lookup-Order'),
            'an unknown category': lambda c: c[0].update(category='sales'),
            'an unknown fixture': lambda c: c[0].update(fixture='huge'),
            'a turn without expect': lambda c: first_turn(c).pop('expect'),
            'an empty expect': lambda c: first_turn(c).update(expect={}),
            'an unknown expectation': lambda c: first_turn(c)['expect'].update(vibes='good'),
            'a required tool that the script never calls': lambda c: first_turn(c)['expect'].update(tools_called=['get_product']),
            'a forbidden tool that the script calls': lambda c: first_turn(c)['expect'].update(tools_not_called=['get_order']),
            'a script that does not end with an answer': lambda c: first_turn(c)['fake_model'].pop(),
            'an answer before the last step': lambda c: first_turn(c)['fake_model'].insert(0, {'say': 'xin chào'}),
            'a template before any tool result': lambda c: first_turn(c, 'cancel_without_order_id_asks_which')['fake_model'][0].update(say='mã đơn {{last_tool.x}}'),
            'a template that is not a path': lambda c: first_turn(c)['fake_model'][-1].update(say='xin {{ os.system }}'),
            'a script on a turn that stops at a rail': lambda c: first_turn(c, 'off_topic_medical_question_stops_at_the_rail').update(fake_model=[{'say': 'x'}]),
            'a search of a knowledge base that is not declared': lambda c: next(x for x in c if x['id'] == 'policy_return_window_is_cited').pop('knowledge'),
            'no statement of what must not be said': lambda c: [t['expect'].pop('answer_not', None) for t in c[0]['turns']],
            'no statement about tools': lambda c: first_turn(c, 'cancel_without_order_id_asks_which')['expect'].pop('tools_not_called'),
            'no final state': lambda c: c[0].pop('final_state'),
            'a final state with a table that cannot be counted': lambda c: c[0].update(final_state={'rows': {'sqlite_master': 0}}),
            'an order status that is not a word': lambda c: c[0].update(final_state={'orders': {'O-102': 'Delivered!'}}),
            'too few scenarios': lambda c: c.__delitem__(slice(5, None)),
            'a category left out': lambda c: [c.remove(x) for x in [y for y in c if y['category'] == 'policy']],
            'more than four turns': lambda c: c[0].update(turns=c[0]['turns'] * 5),
            'an unknown action': lambda c: first_turn(c)['expect'].update(action='delete_order'),
            'an unknown rail': lambda c: first_turn(c, 'human_request_goes_straight_to_staff')['expect'].update(safety_rail='angry'),
        }
        for why, mutate in mutations.items():
            with self.subTest(why=why):
                self.assert_invalid(mutate, why)

    def test_secret_like_text_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'agent_scenarios_x.jsonl'
            path.write_text(DATASET.read_text(encoding='utf-8').replace('Đơn O-102', 'AKIA Đơn O-102', 1), encoding='utf-8')
            with self.assertRaises(AssertionError):
                checker.load_w32_scenarios(path)


class ScriptTemplateTests(unittest.TestCase):
    MESSAGES = [{'role': 'user', 'content': 'hi'},
                {'role': 'tool', 'tool_name': 'x', 'content': json.dumps({'results': [{'citation_id': 'KB:1'}, {'citation_id': 'KB:2'}],
                                                                           'order': {'status': 'delivered'}})}]

    def test_a_template_quotes_the_last_tool_result(self):
        self.assertEqual(runner.fill_templates('Nguồn [{{last_tool.results.1.citation_id}}], đơn {{ last_tool.order.status }}.', self.MESSAGES),
                         'Nguồn [KB:2], đơn delivered.')
        self.assertEqual(runner.fill_templates('không có mẫu', []), 'không có mẫu')

    def test_a_template_that_points_nowhere_is_a_script_defect(self):
        for text in ('{{last_tool.results.5.citation_id}}', '{{last_tool.nothing}}', '{{last_tool.order.status.x}}'):
            with self.subTest(text=text), self.assertRaises(runner.ScenarioError):
                runner.fill_templates(text, self.MESSAGES)
        with self.assertRaises(runner.ScenarioError):
            runner.fill_templates('{{last_tool.a}}', [{'role': 'user', 'content': 'hi'}])


class FakeGatewayRunTests(unittest.TestCase):
    """The scenarios against the whole application with the scripted gateway: what CI runs."""

    @classmethod
    def setUpClass(cls):
        cls.report = runner.run_suite(scenarios(), runner.ScriptedGateway, 'fake')

    def test_every_scenario_passes(self):
        failed = {r['id']: r['failures'] for r in self.report['scenarios'] if not r['passed']}
        self.assertEqual(failed, {})
        summary = self.report['summary']
        self.assertEqual((summary['passed'], summary['failed'], summary['success_rate']), (len(scenarios()), 0, 1.0))

    def test_the_report_has_the_numbers_the_owner_asked_for(self):
        summary = self.report['summary']
        self.assertEqual(self.report['mode'], 'fake')
        self.assertEqual(summary['valid_tool_call_rate'], 1.0)
        self.assertGreater(summary['tool_calls'], 20)
        self.assertEqual(summary['duplicate_tool_calls'], 0)
        self.assertEqual(summary['model_error_turns'], 0)
        self.assertEqual(set(summary['latency_ms']), {'p50', 'p95', 'max', 'mean'})
        self.assertTrue(0 < summary['latency_ms']['p50'] <= summary['latency_ms']['p95'] <= summary['latency_ms']['max'])
        self.assertEqual(summary['turns'], sum(len(s['turns']) for s in self.report['scenarios']))
        self.assertGreater(summary['prompt_tokens'], 0)
        self.assertEqual(set(self.report['by_category']), set(checker.W32_CATEGORIES))
        self.assertTrue(all(e['success_rate'] == 1.0 for e in self.report['by_category'].values()))

    def test_the_rails_never_reach_the_model_and_the_rest_stay_read_only(self):
        rails = [r for r in self.report['scenarios'] if r['category'] in ('human_handoff', 'off_topic')]
        self.assertTrue(rails)
        for record in self.report['scenarios']:
            for turn in record['turns']:
                self.assertLessEqual(turn['model_calls'], 6)
        for name in ('human_request_goes_straight_to_staff', 'angry_customer_threatening_to_post_is_escalated',
                     'off_topic_medical_question_stops_at_the_rail', 'off_topic_prompt_injection_is_refused'):
            record = next(r for r in self.report['scenarios'] if r['id'] == name)
            self.assertEqual(record['turns'][0]['model_calls'], 0, name)

    def test_the_command_line_in_fake_mode_exits_zero_and_writes_the_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            out = io.StringIO()
            self.assertEqual(runner.main(['--fake', '--only', 'lookup_all_orders', 'cancel_pending_order_opens_form', '--out', str(path)], out=out), 0)
            report = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual((report['mode'], report['summary']['scenarios'], report['summary']['success_rate']), ('fake', 2, 1.0))
        self.assertEqual(report['dataset']['sha256'], runner.dataset_digest(DATASET))
        self.assertEqual(report['model'], {'gateway': 'scripted fake gateway'})
        for text in ('success rate', 'valid tool-call rate', 'p50', 'p95'):
            self.assertIn(text, out.getvalue())

    def test_filters_and_unknown_names(self):
        out = io.StringIO()
        self.assertEqual(runner.main(['--fake', '--category', 'policy'], out=out), 0)
        self.assertIn('3/3', out.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(runner.main(['--fake', '--only', 'no_such_scenario']), 2)
            self.assertEqual(runner.main(['--fake', '--category', 'no_such_category']), 2)
        self.assertIn('no_such_scenario', err.getvalue())


class RunnerNotesFailuresTests(unittest.TestCase):
    """A runner that cannot fail would prove nothing: each way a scenario can go wrong is reported."""

    def failures(self, name, change):
        scenario = copy.deepcopy(by_id(name))
        change(scenario)
        record = run_one(scenario)
        self.assertFalse(record['passed'], name)
        return ' | '.join(record['failures'])

    def test_a_required_tool_that_was_not_called(self):
        text = self.failures('lookup_delivered_order_status', lambda s: s['turns'][0]['expect'].update(tools_called=['track_shipment']))
        self.assertIn('track_shipment was not called', text)

    def test_a_forbidden_tool_and_too_many_calls(self):
        text = self.failures('lookup_delivered_order_status', lambda s: s['turns'][0]['expect'].update(
            tools_not_called=['get_order'], max_tool_calls=0, max_model_calls=1))
        for part in ('must not be called', 'at most 0 allowed', 'model calls'):
            self.assertIn(part, text)

    def test_a_forbidden_phrase_and_a_missing_one(self):
        text = self.failures('lookup_delivered_order_status', lambda s: s['turns'][0]['expect'].update(
            answer_not=['ĐÃ ĐƯỢC   GIAO'], answer_all=['O-999'], answer_any=[['không có từ này']]))
        for part in ('must not say', "lacks 'O-999'", 'has none of'):
            self.assertIn(part, text)

    def test_the_wrong_action_form_or_target(self):
        text = self.failures('exchange_to_another_size', lambda s: s['turns'][0]['expect'].update(
            action='reply', order_action={'target_variant_label': 'Đen · Size XL', 'exchange_kind': 'same_variant'}))
        for part in ("action is 'choose_order_action_reason'", 'target variant is', 'exchange_kind'):
            self.assertIn(part, text)

    def test_the_wrong_rail_mode_sources_and_hand_off(self):
        text = self.failures('policy_return_window_is_cited', lambda s: s['turns'][0]['expect'].update(
            safety_rail='human_request', request_mode='general', human_support=True, sources=['policies/other.md']))
        for part in ('safety rail', 'request mode', 'human support', 'source policies/other.md'):
            self.assertIn(part, text)

    def test_a_final_state_that_changed(self):
        text = self.failures('cancel_pending_order_opens_form', lambda s: s.update(
            final_state={'orders': {'O-101': 'cancelled', 'O-999': 'pending'}, 'rows': {'order_action_requests': 3}}))
        for part in ('order O-101 is', 'order O-999 is None', 'order_action_requests has 0 rows'):
            self.assertIn(part, text)

    def test_a_script_that_is_out_of_date(self):
        self.assertIn('never asked for', self.failures('cancel_without_order_id_asks_which', lambda s: s['turns'][0]['fake_model'].append({'say': 'thừa'})))
        self.assertIn('the turn failed', self.failures('lookup_delivered_order_status',
                                                       lambda s: s['turns'][0]['fake_model'].pop()))

    def test_a_template_defect_is_a_script_defect_not_a_pass(self):
        text = self.failures('policy_return_window_is_cited', lambda s: s['turns'][0]['fake_model'][-1].update(say='{{last_tool.results.9.x}}'))
        self.assertIn('script defect', text)

    def test_the_server_side_checks_are_what_the_scenarios_rely_on(self):
        """Switch a code safeguard off and the scenario written for it fails."""
        from retailops.business import application
        with patch.object(application, 'check_final_answer', lambda text, messages=None: type('R', (), {
                'changed': False, 'text': text, 'dropped_policy': 0, 'dropped_claims': 0})()):
            record = run_one(by_id('policy_uncited_promise_is_removed_by_the_server'))
        self.assertFalse(record['passed'])
        self.assertIn('must not say', ' '.join(record['failures']))
        with patch('retailops.workflow.agent.safety_gate', lambda text: None):
            record = run_one(by_id('human_request_goes_straight_to_staff'))
        self.assertFalse(record['passed'])
        with patch('retailops_tools.BoundTools.__call__', lambda self, name, args: {'error': 'tool_not_allowed', 'message': 'x'}):
            record = run_one(by_id('cancel_pending_order_opens_form'))
        self.assertFalse(record['passed'])

    def test_percentiles_are_nearest_rank(self):
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        self.assertEqual((runner.percentile(values, 50), runner.percentile(values, 95), runner.percentile(values, 100)), (50, 100, 100))
        self.assertEqual(runner.percentile([7], 95), 7)
        self.assertIsNone(runner.percentile([], 50))

    def test_the_valid_tool_call_rate_counts_only_malformed_calls_against_the_model(self):
        records = [{'id': 'a', 'category': 'cancel', 'passed': True, 'turns': [
            {'latency_ms': 5.0, 'model_calls': 2, 'prompt_tokens': 1, 'generated_tokens': 1, 'error': None, 'tools': [
                {'name': 'get_order', 'status': 'error', 'error_code': 'order_not_found'},      # a business refusal is a valid call
                {'name': 'get_order', 'status': 'ok'},
                {'name': 'bogus', 'status': 'error', 'error_code': 'tool_not_allowed'},
                {'name': 'prepare_order_action', 'status': 'error', 'error_code': 'invalid_tool_arguments'},
                {'name': 'get_order', 'status': 'error', 'error_code': 'duplicate_call'}]}]}]
        summary, _ = runner.summarize(records)
        self.assertEqual((summary['tool_calls'], summary['valid_tool_calls'], summary['duplicate_tool_calls']), (5, 3, 1))
        self.assertEqual(summary['valid_tool_call_rate'], 0.6)


class CommandLineTests(unittest.TestCase):
    def test_help_describes_both_modes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as caught:
            runner.main(['--help'])
        self.assertEqual(caught.exception.code, 0)
        for text in ('--endpoint', '--fake', '--model', '--api-key-env', '--out', '--only', 'owner'):
            self.assertIn(text, out.getvalue())

    def test_without_an_endpoint_it_refuses_and_touches_nothing(self):
        err = io.StringIO()

        def forbidden(*args, **kwargs):
            raise AssertionError('must not run or connect')
        with patch.object(runner, 'run_suite', forbidden), patch('urllib.request.OpenerDirector.open', forbidden), \
                contextlib.redirect_stderr(err):
            self.assertEqual(runner.main([]), 2)
            self.assertEqual(runner.main(['--only', 'lookup_all_orders']), 2)
        self.assertIn('--endpoint', err.getvalue())
        self.assertIn('--fake', err.getvalue())

    def test_the_two_modes_exclude_each_other(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            runner.main(['--fake', '--endpoint', 'https://example.test/v1'])
        self.assertEqual(caught.exception.code, 2)

    def test_endpoint_forms(self):
        for given, expected in (('https://abc.ngrok-free.app', 'https://abc.ngrok-free.app/v1/chat/completions'),
                                ('https://abc.ngrok-free.app/', 'https://abc.ngrok-free.app/v1/chat/completions'),
                                ('https://abc.ngrok-free.app/v1', 'https://abc.ngrok-free.app/v1/chat/completions'),
                                ('https://abc.ngrok-free.app/v1/chat/completions', 'https://abc.ngrok-free.app/v1/chat/completions'),
                                ('http://localhost:8001/v1', 'http://localhost:8001/v1/chat/completions'),
                                ('http://127.0.0.1:8001', 'http://127.0.0.1:8001/v1/chat/completions')):
            self.assertEqual(runner.normalize_endpoint(given), expected)

    def test_unsafe_endpoints_are_refused(self):
        for bad in ('', '   ', 'abc.ngrok-free.app', 'ftp://example.test/v1', 'http://example.test/v1', 'https://user:pw@example.test/v1',
                    'https://example.test/v1?token=x', 'https://example.test/v1#frag', 'https:///v1', None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                runner.normalize_endpoint(bad)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(runner.main(['--endpoint', 'http://example.test/v1']), 2)
        self.assertIn('https', err.getvalue())


class RealModeThroughTheHttpAdapterTests(unittest.TestCase):
    """--endpoint with a fake vLLM underneath: the real request path, a strict Gemma template, no model."""

    def run_main(self, vllm, *argv, key=FIXTURE_KEY):
        out = io.StringIO()
        environment = {'RETAILOPS_API_KEY': key} if key else {}
        with vllm.install(), patch.dict(os.environ, environment), contextlib.redirect_stderr(io.StringIO()):
            os.environ.pop('RETAILOPS_API_ENDPOINT', None)
            if not key:
                os.environ.pop('RETAILOPS_API_KEY', None)
            code = runner.main(['--endpoint', FIXTURE_ENDPOINT, '--model', FIXTURE_MODEL, *argv], out=out)
            leftover = os.environ.get('RETAILOPS_API_ENDPOINT')
        return code, out.getvalue(), leftover

    def test_the_whole_dataset_runs_through_the_real_adapter_and_a_strict_template(self):
        script, queue = replay(all_steps(scenarios()))
        vllm = RecordingVllm(script, strict=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            code, output, leftover = self.run_main(vllm, '--out', str(path))
            text = path.read_text(encoding='utf-8')
        report = json.loads(text)
        failed = {r['id']: r['failures'] for r in report['scenarios'] if not r['passed']}
        self.assertEqual((code, failed), (0, {}))
        self.assertEqual(len(queue), 0, 'every scripted reply was asked for through HTTP, no more and no fewer')
        self.assertEqual(report['mode'], 'real')
        self.assertEqual(report['summary']['success_rate'], 1.0)
        self.assertEqual({url for url, _ in vllm.requests}, {FIXTURE_ENDPOINT})
        self.assertTrue(all(headers.get('Authorization') == 'Bearer ' + FIXTURE_KEY for _, headers in vllm.requests))
        self.assertEqual({p['model'] for p in vllm.payloads}, {FIXTURE_MODEL})
        self.assertIsNone(leftover, 'the endpoint is set for the run only')
        # The report names the host, never the key or the whole URL.
        self.assertEqual(report['model'], {'name': FIXTURE_MODEL, 'endpoint_host': 'fixture-vllm.example'})
        self.assertNotIn(FIXTURE_KEY, text + output)
        self.assertNotIn('/v1/chat/completions', text + output)

    def test_a_weak_model_lowers_the_rate_without_failing_the_run_unless_asked(self):
        def babble(payload):
            return chat_reply('Dạ vâng ạ.')
        code, output, _ = self.run_main(FakeVllm(babble), '--only', 'lookup_delivered_order_status', 'cancel_pending_order_opens_form')
        self.assertEqual(code, 0)
        self.assertIn('success rate:         0/2 = 0.0', output)
        self.assertIn('FAIL lookup_delivered_order_status', output)
        code, _, _ = self.run_main(FakeVllm(babble), '--only', 'lookup_delivered_order_status', '--min-success-rate', '1.0')
        self.assertEqual(code, 1)

    def test_a_model_that_breaks_the_protocol_is_counted_not_hidden(self):
        replies = deque([chat_reply('', [('get_order', {'order': 'O-102'})]),     # arguments the schema does not allow
                         chat_reply('', [('delete_everything', {'now': True})]),  # a tool that does not exist
                         chat_reply('Dạ em chưa tra được đơn ạ.')])
        code, output, _ = self.run_main(FakeVllm(lambda payload: replies.popleft()), '--only', 'lookup_delivered_order_status')
        self.assertEqual(code, 0)
        self.assertIn('FAIL lookup_delivered_order_status', output)
        self.assertIn('valid tool-call rate: 0/2 = 0.0', output)
        self.assertIn('tool get_order was not called (the call was malformed and refused)', output)

    def test_an_endpoint_that_is_down_is_reported_per_turn(self):
        def down(payload):
            raise OSError('connection refused')
        code, output, _ = self.run_main(FakeVllm(down), '--only', 'lookup_delivered_order_status')
        self.assertEqual(code, 0)
        self.assertIn('turns that ended in an error: 1', output)

    def test_a_server_without_a_key_gets_a_placeholder_not_a_missing_header(self):
        script, _ = replay(all_steps([by_id('lookup_all_orders')]))
        vllm = RecordingVllm(script)
        code, _, _ = self.run_main(vllm, '--only', 'lookup_all_orders', key=None)
        self.assertEqual(code, 0)
        self.assertEqual({h.get('Authorization') for _, h in vllm.requests}, {'Bearer ' + runner.PLACEHOLDER_KEY})


if __name__ == '__main__':
    unittest.main()
