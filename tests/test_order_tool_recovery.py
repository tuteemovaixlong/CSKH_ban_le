"""Regression tests for 2026-09-20 order lookup failures; no GPU/live data."""
import copy
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from agent_protocol import ProtocolError, validate_messages
from retailops.core import ApiError
from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.knowledge.citations import cited_sources
from retailops.workflow.subagents.order_agent import run_order_agent, _synthesize_order_response
from retailops.workflow.subagents.policy_agent import run_policy_agent, _synthesize_policy_response
from retailops.workflow.supervisor import run_supervisor
from retailops_agent import AgentError
from retailops_providers import OpenRouterAgent, SYSTEM
from retailops_tools import BoundTools

MODEL = 'fixture-retailops-tool-model'
KEY = 'fixture_not_a_secret_' + 'a' * 40


def api_response(content='Done', calls=()):
    message = {'role': 'assistant', 'content': content}
    if calls:
        message['tool_calls'] = [
            {'id': f'call_{i}', 'type': 'function',
             'function': {'name': name, 'arguments': json.dumps(args)}}
            for i, (name, args) in enumerate(calls)]
    return {'model': MODEL,
            'choices': [{'message': message, 'finish_reason': 'tool_calls' if calls else 'stop'}],
            'usage': {'prompt_tokens': 80, 'completion_tokens': 20}}


def state(text='Check O-819125'):
    msg = {'role': 'user', 'content': text}
    return {'messages': [msg], 'fresh': [copy.deepcopy(msg)], 'trace': {'model_calls': 0},
            'tool_count': 0, 'bound': {}, 'complete': False, 'subagent_history': [],
            'consecutive_ood_count': 0, 'sentiment': 'neutral', 'strict_mode': False}


class OrderToolRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.environment = patch.dict(os.environ, {
            'RETAILOPS_API_ENDPOINT': 'https://fixture.example/v1/chat/completions'}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.store = BusinessStore(Path(self.temp.name) / 'business.sqlite3')
        self.store.add_customer('C-001', 'Fixture customer')
        self.store.add_customer('C-002', 'Other fixture customer')
        with self.store.connection(write=True) as db:
            for oid, owner, status in [('O-819125', 'C-001', 'pending'),
                                        ('O-819126', 'C-001', 'delivered')]:
                db.execute('INSERT INTO orders(id,customer_id,name,variant,amount,status) VALUES (?,?,?,?,?,?)',
                           (oid, owner, 'Fixture shirt', 'White / M', 450000, status))
        self.adapter = OpenRouterAgent(KEY, MODEL)
        self.app = Application(self.store, {}, api_infer=self.adapter, orchestrator='multi_agent')
        self.cid = self.app.new_conversation('C-001', {'provider_id': 'api'})['conversation_id']

    def body(self, text='Ki\u1ec3m tra \u0111\u01a1n O-819125', attachment=None):
        value = {'conversation_id': self.cid, 'text': text, 'request_id': str(uuid.uuid4())}
        if attachment:
            value['attachment'] = attachment
        return value

    def test_missing_order_is_scoped_result_without_second_model_call(self):
        body = self.body('Ki\u1ec3m tra tr\u1ea1ng th\u00e1i \u0111\u01a1n O-1002 xem giao \u0111\u1ebfn \u0111\u00e2u')
        with patch.object(OpenRouterAgent, 'request', return_value=api_response(None, [('get_order', {'order_id': 'O-1002'})])) as req:
            result = self.app.chat('C-001', body)
            replay = self.app.chat('C-001', body)
        self.assertEqual(req.call_count, 1)
        self.assertIn('O-1002', result['message'])
        self.assertIn('thu\u1ed9c t\u00e0i kho\u1ea3n', result['message'])
        self.assertNotIn('O-101', result['message'])
        self.assertNotIn('b\u1eadn', result['message'])
        self.assertEqual(result['source'], 'tool_result')
        self.assertEqual(result['trace']['model_calls'], 1)
        self.assertEqual(result['trace']['tools'][0]['error_code'], 'order_not_found')
        self.assertTrue(replay['replayed'])
        self.assertIsNone(result['trace']['reported_cost_usd'])
        self.assertEqual(self.store.lookup('C-001', 'O-819125')['status'], 'pending')

    def test_other_customer_order_is_not_disclosed(self):
        with self.store.connection(write=True) as db:
            db.execute('INSERT INTO orders(id,customer_id,name,variant,amount,status) VALUES (?,?,?,?,?,?)',
                       ('O-1002', 'C-002', 'PRIVATE ITEM', 'SECRET VARIANT', 999, 'delivered'))
        with patch.object(OpenRouterAgent, 'request', return_value=api_response(None, [('get_order', {'order_id': 'O-1002'})])):
            result = self.app.chat('C-001', self.body('Ki\u1ec3m tra \u0111\u01a1n O-1002'))
        serialized = json.dumps(result)
        self.assertNotIn('PRIVATE ITEM', serialized)
        self.assertNotIn('C-002', serialized)
        self.assertIn('thu\u1ed9c t\u00e0i kho\u1ea3n', result['message'])

    def test_empty_followup_uses_verified_order_and_counts_both_attempts(self):
        responses = [api_response(None, [('get_order', {'order_id': 'O-819125'})]), api_response(None)]
        with patch.object(OpenRouterAgent, 'request', side_effect=responses) as req:
            result = self.app.chat('C-001', self.body())
        self.assertEqual(req.call_count, 2)
        self.assertEqual(result['trace']['model_calls'], 2)
        self.assertEqual(result['trace']['model_responses'], 1)
        self.assertTrue(result['trace']['degraded'])
        self.assertEqual(result['source'], 'tool_result')
        self.assertIn('O-819125', result['message'])
        self.assertIn('Ch\u1edd x\u1eed l\u00fd', result['message'])
        self.assertNotIn('b\u1eadn', result['message'])
        self.assertEqual(result['context']['order_id'], 'O-819125')
        self.assertIsNone(result['trace']['reported_cost_usd'])
        history = self.store.history('C-001', self.cid)
        validate_messages(history + [{'role': 'user', 'content': 'Next question'}])

    def test_initial_transport_failure_is_not_recorded_as_model_answer(self):
        with patch.object(OpenRouterAgent, 'request', side_effect=AgentError('api_unavailable', 'secret upstream text')):
            with self.assertRaises(ApiError) as caught:
                self.app.chat('C-001', self.body())
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.code, 'api_unavailable')
        self.assertEqual(caught.exception.trace['model_calls'], 1)
        self.assertIsNone(caught.exception.trace['reported_cost_usd'])
        self.assertNotIn('secret upstream', str(caught.exception))
        self.assertEqual(self.store.history('C-001', self.cid), [])

    def test_two_tools_have_one_assistant_and_matching_results(self):
        responses = [api_response(None, [('get_order', {'order_id': 'O-819125'}),
                                         ('get_order', {'order_id': 'O-819126'})]), api_response('Two orders checked')]
        with patch.object(OpenRouterAgent, 'request', side_effect=responses) as req:
            result = self.app.chat('C-001', self.body('Ki\u1ec3m tra O-819125 v\u00e0 O-819126'))
        messages = req.call_args_list[1].args[0]['messages']
        self.assertEqual([m['role'] for m in messages], ['system', 'user', 'assistant', 'tool', 'tool'])
        self.assertEqual([m['tool_call_id'] for m in messages if m['role'] == 'tool'], ['call_0', 'call_1'])
        self.assertEqual(result['message'], 'Two orders checked')

    def test_system_policy_is_kept_but_not_sent_twice(self):
        with patch.object(self.adapter, 'request', return_value=api_response()) as req:
            self.adapter.chat([{'role': 'system', 'content': 'Worker rules'},
                               {'role': 'user', 'content': 'Check O-819125'}], True, 2)
        messages = req.call_args.args[0]['messages']
        self.assertEqual([m['role'] for m in messages], ['system', 'user'])
        self.assertIn(SYSTEM, messages[0]['content'])
        self.assertIn('Worker rules', messages[0]['content'])

    def test_custom_endpoint_does_not_claim_openrouter(self):
        self.assertEqual(self.adapter.inspect()['provider'], 'custom_api')
        self.assertNotIn(KEY, json.dumps(self.adapter.inspect()))
        self.assertNotIn('fixture.example', json.dumps(self.adapter.inspect()))

    def test_image_reaches_actual_adapter_and_is_counted(self):
        attachment = {'type': 'image', 'data': 'aW1hZ2U=', 'mime_type': 'image/png', 'name': 'fixture.png'}
        with patch.object(OpenRouterAgent, 'request', return_value=api_response('Visible fixture')) as req:
            result = self.app.chat('C-001', self.body('Gi\u1ea3i th\u00edch \u1ea3nh', attachment))
        user = next(m for m in req.call_args.args[0]['messages'] if m['role'] == 'user')
        self.assertEqual(user['content'][1]['image_url']['url'], 'data:image/png;base64,aW1hZ2U=')
        self.assertEqual(result['trace']['model_calls'], 1)
        self.assertEqual(result['message'], 'Visible fixture')

    def test_unknown_shipment_does_not_invent_carrier_or_eta(self):
        snapshot = {'order_id': None, 'product_id': None}
        bound = BoundTools(self.store, self.app.catalog, 'C-001', snapshot, {})
        result = bound('track_shipment', {'order_id': 'O-819125'})
        self.assertEqual(result['order_status'], 'pending')
        self.assertIsNone(result['shipment']['carrier'])
        self.assertIsNone(result['shipment']['tracking_code'])
        self.assertIsNone(result['shipment']['estimated_delivery'])

    def test_database_outage_is_not_order_not_found(self):
        with patch.object(OpenRouterAgent, 'request', return_value=api_response(None, [('get_order', {'order_id': 'O-819125'})])):
            with patch.object(BoundTools, 'read_order', side_effect=ApiError(503, 'database_unavailable', 'sensitive database detail')):
                with self.assertRaises(ApiError) as caught:
                    self.app.chat('C-001', self.body())
        self.assertEqual(caught.exception.code, 'tool_unavailable')
        self.assertNotIn('sensitive database', str(caught.exception))
        self.assertEqual(self.store.history('C-001', self.cid), [])

    def test_invalid_owner_argument_never_reaches_dispatcher(self):
        response = api_response(None, [('get_order', {'order_id': 'O-819125', 'customer_id': 'C-002'})])
        with patch.object(OpenRouterAgent, 'request', return_value=response):
            with patch.object(BoundTools, '__call__') as dispatch:
                self.app.chat('C-001', self.body())
        dispatch.assert_not_called()

    def test_plural_vietnamese_order_request_is_not_tool_free(self):
        for text in ('check t\u1ea5t c\u1ea3 c\u00e1c \u0111\u01a1n hi\u1ec7n c\u00f3, ki\u1ec3m tra t\u00ecnh tr\u1ea1ng t\u1eebng \u0111\u01a1n',
                     'check tat ca cac don hien co'):
            with self.subTest(text=text):
                routed = run_supervisor(state(text))
                self.assertEqual(routed['next_worker'], 'order_agent')

    def test_renderer_never_claims_a_complaint_or_voucher_was_issued(self):
        for status in ('delivery_failed_virtual', 'sorting_delayed'):
            out = _synthesize_order_response([{'name': 'track_shipment', 'args': {'order_id': 'O-819125'},
                'result': {'order_id': 'O-819125', 'shipment': {'status': status, 'status_text': 'Delayed'}}}])
            self.assertNotIn('SALE50K', out)
            self.assertNotIn('18:00', out)
            self.assertNotIn('GHTK', out)

    def test_empty_results_do_not_synthesize_success(self):
        self.assertIsNone(_synthesize_order_response([]))
        self.assertIsNone(_synthesize_order_response([{'name': 'get_order', 'args': {}, 'result': {}}]))
        self.assertIsNone(_synthesize_order_response([{'name': 'get_order', 'args': {}, 'result': {'order': None}}]))

    def test_list_renderer_keeps_all_returned_orders(self):
        orders = [{'id': f'O-{i}', 'status': 'pending'} for i in range(10)]
        text = _synthesize_order_response([{'name': 'list_orders', 'args': {}, 'result': {'orders': orders}}])
        self.assertIn('O-9:', text)

    def test_policy_fallback_uses_excerpt_and_single_kb_prefix(self):
        source = {'citation_id': 'KB:' + 'a' * 24, 'title': 'Fixture policy',
                  'excerpt': 'Returns require an approved request.'}
        responses = [api_response(None, [('search_knowledge', {'query': 'returns'})]), api_response(None)]
        with patch.object(self.adapter, 'request', side_effect=responses):
            result = run_policy_agent(state('Store policy'), lambda n, a: {'results': [source]}, self.adapter)
        text = result['fresh'][-1]['content']
        self.assertIn(source['excerpt'], text)
        self.assertIn('[' + source['citation_id'] + ']', text)
        self.assertNotIn('KB:KB:', text)
        self.assertEqual(cited_sources(text, [source]), [source])
        self.assertEqual(result['trace']['model_calls'], 2)
        self.assertEqual(result['trace']['answer_source'], 'tool_result')

    def test_policy_missing_excerpt_is_not_fabricated(self):
        source = {'citation_id': 'KB:' + 'a' * 24, 'title': 'Title only'}
        self.assertIsNone(_synthesize_policy_response([{'result': {'results': [source]}}]))

    def test_anthropic_system_and_tool_ids_roundtrip(self):
        # Verify the system role is consumed, not stuck in the adapter's while loop.
        with patch.dict(os.environ, {}, clear=True):
            ant = OpenRouterAgent('sk-ant-' + 'x' * 50, 'claude-3-5-haiku-20241022')
        history = [{'role': 'system', 'content': 'Worker instruction'},
                   {'role': 'user', 'content': 'Check order'},
                   {'role': 'assistant', 'content': '', 'tool_calls': [
                       {'function': {'name': 'get_order', 'arguments': {'order_id': 'O-819125'}}}]},
                   {'role': 'tool', 'tool_name': 'get_order', 'content': '{}'}]
        response = {'content': [{'type': 'text', 'text': 'Done'}], 'usage': {'input_tokens': 10, 'output_tokens': 2}}
        with patch.object(ant, 'request', return_value=response) as req:
            ant.chat(history, False, 2)
        body = req.call_args.args[0]
        use = body['messages'][1]['content'][0]
        tool_result = body['messages'][2]['content'][0]
        self.assertEqual(use['id'], tool_result['tool_use_id'])
        self.assertIn('Worker instruction', body['system'])


if __name__ == '__main__':
    unittest.main()
