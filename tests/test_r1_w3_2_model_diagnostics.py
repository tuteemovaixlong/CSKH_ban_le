"""W3.2 item 0 (W3.2-D8): model failures are diagnosable and history is shaped in one place.

Everything runs against fakes: a fake vLLM endpoint that mimics a strict Gemma chat template.
No real model, Colab, network or customer data is used.
"""
import copy
import json
import os
import tempfile
import time
import unittest
import urllib.error
import uuid
from pathlib import Path
from unittest.mock import patch

from agent_protocol import model_history, validate_messages
from gemma_fakes import (FIXTURE_ENDPOINT, FIXTURE_KEY, FIXTURE_MODEL, FakeVllm, chat_reply,
                         gemma_template_error, http_error)
from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.core import ApiError
from retailops.workflow.subagents.order_agent import run_order_agent
from retailops.workflow.subagents.policy_agent import run_policy_agent
from retailops.workflow.subagents.read_worker import call_model
from retailops.workflow.subagents.witty_agent import run_witty_agent
from retailops_agent import AgentError, run_agent
from retailops_providers import OpenRouterAgent

SYSTEM_TURN = {'role': 'system', 'content': 'Bạn là trợ lý.'}
GET_ORDER_CALL = {'role': 'assistant', 'content': '', 'tool_calls': [
    {'function': {'name': 'get_order', 'arguments': {'order_id': 'O-101'}}}]}
GET_ORDER_RESULT = {'role': 'tool', 'tool_name': 'get_order',
                    'content': json.dumps({'order': {'id': 'O-101', 'status': 'pending'}})}


def production_history():
    """What BusinessStore.history() returns after one turn that called get_order."""
    return [{'role': 'user', 'content': 'tra cứu đơn O-101 giúp tôi'},
            copy.deepcopy(GET_ORDER_CALL), copy.deepcopy(GET_ORDER_RESULT),
            {'role': 'assistant', 'content': 'Đơn O-101 đang chờ xử lý.'}]


def worker_state(history, text):
    user = {'role': 'user', 'content': text}
    return {'messages': list(history) + [user], 'fresh': [copy.deepcopy(user)], 'trace': {'model_calls': 0},
            'tool_count': 0, 'bound': {}, 'complete': False, 'subagent_history': [],
            'consecutive_ood_count': 0, 'sentiment': 'neutral', 'strict_mode': False}


class EndpointCase(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {'RETAILOPS_API_ENDPOINT': FIXTURE_ENDPOINT}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.adapter = OpenRouterAgent(FIXTURE_KEY, FIXTURE_MODEL)


class ProviderErrorTraceTests(EndpointCase):
    def failure(self, error):
        with patch.object(self.adapter._opener, 'open', side_effect=error), self.assertRaises(AgentError) as caught:
            self.adapter.request({}, 1)
        return caught.exception

    def test_http_error_keeps_status_kind_and_filtered_provider_message(self):
        leaky = (f'Engine unavailable. Authorization: Bearer abcdefghijklmnop1234 key {FIXTURE_KEY} '
                 f'while calling https://colab-tunnel.example/v1/chat?token=zzzz retry later')
        exc = self.failure(http_error(503, {'object': 'error', 'message': leaky, 'code': 503}))
        self.assertEqual(exc.code, 'api_unavailable')
        self.assertEqual(exc.trace['http_status'], 503)
        self.assertEqual(exc.trace['error_kind'], 'service_unavailable')
        message = exc.trace['provider_message']
        self.assertIn('Engine unavailable', message)
        self.assertLessEqual(len(message), 300)
        for secret in (FIXTURE_KEY, 'abcdefghijklmnop1234', 'colab-tunnel.example', 'zzzz'):
            self.assertNotIn(secret, message)
        self.assertNotIn('Engine unavailable', str(exc))  # users never see the provider text

    def test_provider_message_is_cut_to_300_characters(self):
        exc = self.failure(http_error(500, {'message': 'chat template failed ' * 200}))
        self.assertEqual(len(exc.trace['provider_message']), 300)
        self.assertEqual(exc.trace['error_kind'], 'http_500')

    def test_plain_text_and_validation_style_bodies_are_readable(self):
        plain = self.failure(http_error(502, b'<html>Bad Gateway from tunnel</html>'))
        self.assertIn('Bad Gateway from tunnel', plain.trace['provider_message'])
        detail = self.failure(http_error(422, {'detail': [{'msg': 'field required', 'loc': ['body']}]}))
        self.assertEqual(detail.trace['provider_message'], 'field required')

    def test_model_name_is_kept_but_opaque_tokens_are_removed(self):
        body = {'message': f'The model `{FIXTURE_MODEL}` does not exist; header {"A1b2" * 12}'}
        message = self.failure(http_error(404, body)).trace['provider_message']
        self.assertIn(FIXTURE_MODEL, message)
        self.assertNotIn('A1b2' * 12, message)

    def test_transport_errors_have_a_kind_and_never_leak_the_key(self):
        timed_out = self.failure(urllib.error.URLError(f'timed out {FIXTURE_KEY}'))
        self.assertEqual(timed_out.trace['error_kind'], 'timeout')
        self.assertNotIn('http_status', timed_out.trace)
        reset = self.failure(ConnectionResetError(f'peer reset {FIXTURE_KEY}'))
        self.assertEqual(reset.trace['error_kind'], 'ConnectionResetError')
        for exc in (timed_out, reset):
            self.assertNotIn(FIXTURE_KEY, json.dumps(exc.trace))
            self.assertNotIn(FIXTURE_KEY, str(exc))


class ModelErrorRecordingTests(EndpointCase):
    def trace_after(self, script, **options):
        vllm = FakeVllm(script, strict=False)
        trace = {'model_calls': 0}
        messages = [{'role': 'system', 'content': 'Hệ thống'}, {'role': 'user', 'content': 'hiện có những size nào'}]
        with vllm.install(), self.assertRaises(AgentError) as caught:
            call_model(self.adapter, messages, False, time.monotonic() + 30, trace, **options)
        return caught.exception, trace

    def test_failed_call_records_kind_status_and_provider_message(self):
        exc, trace = self.trace_after(lambda p: http_error(503, {'message': 'vLLM engine is dead'}))
        self.assertEqual(len(trace['model_errors']), 1)
        entry = trace['model_errors'][0]
        self.assertEqual({k: entry[k] for k in ('call', 'code', 'error_kind', 'http_status')},
                         {'call': 1, 'code': 'api_unavailable', 'error_kind': 'service_unavailable', 'http_status': 503})
        self.assertEqual(entry['provider_message'], 'vLLM engine is dead')
        self.assertEqual(exc.http_status, 503)
        self.assertTrue(trace['usage_incomplete'])

    def test_unusable_reply_after_tokens_were_generated_is_not_reported_as_zero_tokens(self):
        exc, trace = self.trace_after(lambda p: chat_reply('', finish_reason='length', completion_tokens=2048))
        entry = trace['model_errors'][0]
        self.assertEqual(entry['code'], 'agent_response_failed')
        self.assertEqual(entry['error_kind'], 'ProtocolError')
        self.assertEqual(entry['finish_reason'], 'length')
        self.assertEqual(entry['completion_tokens'], 2048)
        self.assertEqual(trace['generated_tokens'] if 'generated_tokens' in trace else 0, 0)
        self.assertIn('incomplete', entry['provider_message'])

    def test_reasoning_only_reply_is_recorded_as_empty_answer(self):
        def script(payload):
            reply = chat_reply('', completion_tokens=900)
            reply['choices'][0]['message']['reasoning'] = 'thinking about sizes'
            return reply
        _, trace = self.trace_after(script)
        entry = trace['model_errors'][0]
        self.assertEqual(entry['provider_message'], 'Empty assistant answer')
        self.assertIs(entry['had_reasoning'], True)
        self.assertEqual(entry['completion_tokens'], 900)

    def test_timeout_is_recorded_with_its_own_kind(self):
        exc, trace = self.trace_after(lambda p: urllib.error.URLError('timed out'))
        self.assertEqual(trace['model_errors'][0]['error_kind'], 'timeout')
        self.assertNotIn('http_status', trace['model_errors'][0])

    def test_single_agent_loop_keeps_provider_details_and_status(self):
        vllm = FakeVllm(lambda p: http_error(502, {'message': 'tunnel closed'}), strict=False)
        with vllm.install(), self.assertRaises(AgentError) as caught:
            run_agent(self.adapter, 'hi', [], lambda name, args: {}, self.adapter.inspect())
        entry = caught.exception.trace['model_errors'][0]
        self.assertEqual((entry['http_status'], entry['provider_message']), (502, 'tunnel closed'))
        self.assertEqual(caught.exception.http_status, 502)


class ApplicationFixture(EndpointCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = BusinessStore(Path(self.temp.name) / 'business.sqlite3')
        self.store.seed()
        self.app = Application(self.store, {}, api_infer=self.adapter, api_daily_limit=100,
                               orchestrator='multi_agent')
        self.cid = self.app.new_conversation('C-001', {'provider_id': 'api'})['conversation_id']

    def say(self, text):
        return self.app.chat('C-001', {'conversation_id': self.cid, 'text': text,
                                       'request_id': 'req-' + uuid.uuid4().hex})


def order_lookup_then_text(payload):
    """Scripted model: look the order up when asked, then answer; plain text otherwise."""
    last = payload['messages'][-1]
    if last['role'] == 'tool':
        return chat_reply('Đơn O-101 đang chờ xử lý.')
    if payload.get('tools') and 'O-101' in last['content']:
        return chat_reply('', [('get_order', {'order_id': 'O-101'})])
    return chat_reply('Dạ hiện có các size S, M, L ạ.')


class ApplicationDiagnosticsTests(ApplicationFixture):
    def test_failed_turn_returns_and_persists_model_errors(self):
        vllm = FakeVllm(lambda p: http_error(503, {'message': 'engine is dead'}), strict=False)
        with vllm.install(), self.assertRaises(ApiError) as caught:
            self.say('tra cứu đơn O-101 giúp tôi')
        self.assertEqual(caught.exception.status, 503)
        entries = caught.exception.trace['model_errors']
        self.assertEqual((entries[0]['http_status'], entries[0]['provider_message']), (503, 'engine is dead'))
        with self.store.connection() as db:
            stored = [json.loads(r['payload']) for r in
                      db.execute("SELECT payload FROM business_events WHERE kind='agent_failed'")]
        self.assertEqual(stored[-1]['trace']['model_errors'][0]['provider_message'], 'engine is dead')

    def test_followup_after_get_order_turn_reproduces_and_is_fixed(self):
        """The 503: a follow-up turn replayed the stored tool exchange to a strict template."""
        vllm = FakeVllm(order_lookup_then_text, strict=True)
        with vllm.install():
            first = self.say('tra cứu đơn O-101 giúp tôi')
            self.assertEqual([t['name'] for t in first['trace']['tools']], ['get_order'])
            stored = self.store.history('C-001', self.cid)
            self.assertEqual([m['role'] for m in stored], ['user', 'assistant', 'tool', 'assistant'])
            raw_payload = self.adapter.for_turn().translate(
                [{'role': 'system', 'content': 's'}, *stored, {'role': 'user', 'content': 'hiện có những size nào'}])
            self.assertIsNotNone(gemma_template_error(raw_payload))  # what used to be sent
            second = self.say('hiện có những size nào')
        self.assertIn('size', second['message'])
        sent = vllm.payloads[-1]['messages']
        self.assertEqual([m['role'] for m in sent], ['system', 'user', 'assistant', 'user'])
        self.assertIsNone(gemma_template_error(sent))
        self.assertEqual(second['trace'].get('model_errors', []), [])

    def test_stored_turns_still_keep_the_tool_exchange_for_audit(self):
        with FakeVllm(order_lookup_then_text, strict=True).install():
            self.say('tra cứu đơn O-101 giúp tôi')
            self.say('hiện có những size nào')
        roles = [m['role'] for m in self.store.history('C-001', self.cid, limit=10)]
        self.assertEqual(roles[:4], ['user', 'assistant', 'tool', 'assistant'])


class RecordingGateway:
    """Model double for workers: records every request and checks it against the strict template."""
    def __init__(self):
        self.requests = []

    def chat(self, messages, allow_tools, timeout):
        self.requests.append(copy.deepcopy(messages))
        return {'message': {'role': 'assistant', 'content': 'Dạ ok ạ.'}, 'prompt_eval_count': 5, 'eval_count': 3}


class SharedHistoryTests(unittest.TestCase):
    def test_settled_turns_become_plain_alternating_text(self):
        shaped = model_history([SYSTEM_TURN, *production_history(), {'role': 'user', 'content': 'còn màu khác không'}])
        self.assertEqual([m['role'] for m in shaped], ['system', 'user', 'assistant', 'user'])
        self.assertEqual(shaped[2]['content'], 'Đơn O-101 đang chờ xử lý.')
        self.assertIsNone(gemma_template_error(shaped))

    def test_turn_in_progress_keeps_native_tool_calls(self):
        turn = [*production_history(), {'role': 'user', 'content': 'xem lại đơn O-101'},
                copy.deepcopy(GET_ORDER_CALL), copy.deepcopy(GET_ORDER_RESULT)]
        shaped = model_history(turn)
        self.assertEqual([m['role'] for m in shaped], ['user', 'assistant', 'user', 'assistant', 'tool'])
        self.assertIn('tool_calls', shaped[3])
        self.assertIsNone(gemma_template_error(shaped))
        validate_messages([SYSTEM_TURN, *shaped])

    def test_adjacent_roles_are_merged_and_edges_are_trimmed(self):
        shaped = model_history([
            {'role': 'assistant', 'content': 'xin chào'},
            {'role': 'user', 'content': 'a'}, {'role': 'user', 'content': 'b'},
            {'role': 'assistant', 'content': 'c'}, {'role': 'assistant', 'content': 'd'},
            {'role': 'user', 'content': 'e'}, {'role': 'system', 'content': 'late system'},
            {'role': 'user', 'content': 'câu mới'}])
        self.assertEqual([(m['role'], m['content']) for m in shaped],
                         [('user', 'a\nb'), ('assistant', 'c\nd'), ('user', 'câu mới')])

    def test_shaping_is_idempotent_and_keeps_attachments(self):
        picture = {'type': 'image', 'name': 'a.png'}
        history = [{'role': 'user', 'content': 'xem ảnh', 'attachment': picture},
                   {'role': 'assistant', 'content': 'Ảnh đẹp'}]
        once = model_history([*history, {'role': 'user', 'content': 'tiếp'}])
        self.assertEqual(once[0]['attachment'], picture)
        self.assertEqual(model_history(once), once)

    def test_every_worker_sends_a_valid_transcript_after_a_get_order_turn(self):
        history = production_history()
        text = 'hiện có những size nào'
        runners = {
            'order_agent': lambda gw: run_order_agent(worker_state(history, text), lambda n, a: {}, gw),
            'policy_agent': lambda gw: run_policy_agent(worker_state(history, text), lambda n, a: {}, gw),
            'witty_agent': lambda gw: run_witty_agent(worker_state(history, text), gw),
            'single_agent': lambda gw: run_agent(gw, text, history, lambda n, a: {},
                                                 {'name': FIXTURE_MODEL, 'provider': 'custom'}),
        }
        for name, run in runners.items():
            with self.subTest(worker=name):
                gateway = RecordingGateway()
                try:
                    run(gateway)
                except AgentError:
                    pass  # the policy worker may refuse an answer without sources; the request still matters
                self.assertTrue(gateway.requests, name)
                for request in gateway.requests:
                    self.assertIsNone(gemma_template_error(request), (name, [m['role'] for m in request]))
                    self.assertNotIn('tool', [m['role'] for m in request])


if __name__ == '__main__':
    unittest.main()
