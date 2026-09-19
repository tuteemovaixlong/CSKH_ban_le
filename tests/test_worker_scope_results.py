"""Real adapter regression cases for mixed order results; no live model or data."""
import copy
import json
import os
import time
import unittest
from unittest.mock import patch

import test_order_tool_recovery as recovery
from test_order_tool_recovery import api_response, state, MODEL, KEY
from agent_protocol import PROTOCOL, ProtocolError, build_request, validate_envelope, validate_messages
from retailops.core import ApiError
from retailops.workflow.subagents.order_agent import _ALLOWED, _synthesize_order_response, run_order_agent
from retailops.workflow.subagents.policy_agent import run_policy_agent
from retailops_providers import OpenRouterAgent
from retailops_agent import AgentError, LocalAgent, RemoteAgent
from retailops_baseline import ModelConfig, LocalOllama


class WorkerScopeResultsTests(unittest.TestCase):
    def setUp(self):
        recovery.OrderToolRecoveryTests.setUp(self)
        with self.store.connection(write=True) as db:
            db.execute('INSERT INTO orders(id,customer_id,name,variant,amount,status) VALUES (?,?,?,?,?,?)',
                       ('O-819127', 'C-001', 'Fixture shoe', 'Brown / 41', 890000, 'delivered'))

    body = recovery.OrderToolRecoveryTests.body

    def test_order_schema_is_limited_on_every_model_request(self):
        responses = [api_response(None, [('get_order', {'order_id': 'O-819125'})]),
                     api_response('Verified order')]
        with patch.object(OpenRouterAgent, 'request', side_effect=responses) as request:
            self.app.chat('C-001', self.body())
        for call in request.call_args_list:
            body = call.args[0]
            self.assertEqual({t['function']['name'] for t in body['tools']}, set(_ALLOWED))
            self.assertNotIn('search_knowledge', {t['function']['name'] for t in body['tools']})
            self.assertNotIn('prepare_cancellation', {t['function']['name'] for t in body['tools']})

    def test_policy_schema_is_only_knowledge(self):
        with patch.object(self.adapter, 'request', return_value=api_response('No policy verified')) as request:
            run_policy_agent(state('Store policy'), lambda n, a: {}, self.adapter)
        self.assertEqual([t['function']['name'] for t in request.call_args.args[0]['tools']], ['search_knowledge'])

    def test_delivered_order_products_and_denied_policy_do_not_erase_results(self):
        responses = [api_response(None, [('get_order', {'order_id': 'O-819127'})]),
                     api_response(None, [('track_shipment', {'order_id': 'O-819127'}),
                                         ('search_products', {'query': 'Essential'})]),
                     api_response(None, [('search_knowledge', {'query': 'shipping'})])]
        with patch.object(OpenRouterAgent, 'request', side_effect=responses):
            result = self.app.chat('C-001', self.body('O-819127 tim thong tin cu the'))
        self.assertEqual(result['source'], 'tool_result')
        self.assertIn('O-819127', result['message'])
        self.assertIn('\u0110\u00e3 giao', result['message'])
        self.assertIn('P-101', result['message'])
        self.assertNotIn('Vui l\u00f2ng x\u00e1c nh\u1eadn m\u00e3', result['message'])
        self.assertEqual(result['trace']['tools'][-1]['error_code'], 'tool_not_allowed')
        self.assertEqual(result['trace']['outcome'], 'partial')
        validate_messages(self.store.history('C-001', self.cid) + [{'role': 'user', 'content': 'Next'}])

    def test_empty_catalog_search_does_not_make_order_unavailable(self):
        records = [{'name': 'get_order', 'args': {}, 'result': {'order': {'id': 'O-819125', 'status': 'pending'}}},
                   {'name': 'search_products', 'args': {'query': 'absent'}, 'result': {'products': []}},
                   {'name': 'search_knowledge', 'args': {}, 'result': {'error': 'tool_not_allowed'}}]
        answer = _synthesize_order_response(records)
        self.assertIsInstance(answer, str)
        self.assertIn('O-819125', answer)
        self.assertIn('danh m\u1ee5c', answer)
        self.assertNotIn('x\u00e1c nh\u1eadn m\u00e3', answer)

    def test_product_and_context_results_have_evidence_only_renderers(self):
        product = {'id': 'P-101', 'name': 'Fixture product', 'description': 'Verified description',
                   'material': None, 'care': None, 'stock': None, 'variants': ['White / M']}
        for name, payload in [('get_product', {'product': product}),
                              ('get_context', {'order': None, 'product': product}),
                              ('get_context', {'order': None, 'product': None})]:
            with self.subTest(name=name, payload=payload):
                answer = _synthesize_order_response([{'name': name, 'args': {}, 'result': payload}])
                self.assertIsInstance(answer, str)
                self.assertNotIn('None', answer)
                self.assertNotIn('C\u00f2n 15', answer)

    def test_failed_model_attempt_has_measured_latency(self):
        def fail(*args, **kwargs):
            time.sleep(0.012)
            raise AgentError('api_unavailable', 'private provider error')
        with patch.object(OpenRouterAgent, 'request', side_effect=fail):
            with self.assertRaises(ApiError) as caught:
                self.app.chat('C-001', self.body())
        self.assertGreater(caught.exception.trace['latency_ms'], 5)
        self.assertEqual(caught.exception.trace['model_calls'], 1)

    def test_invalid_tool_arguments_are_distinct_from_worker_scope(self):
        with patch.object(OpenRouterAgent, 'request', return_value=api_response(None, [('get_order', {'customer_id': 'C-002', 'order_id': 'O-819125'})])):
            result = self.app.chat('C-001', self.body())
        self.assertEqual(result['trace']['tools'][0]['error_code'], 'invalid_tool_arguments')
        self.assertNotIn('Fixture shirt', result['message'])

    def test_malformed_product_is_not_treated_as_success(self):
        self.assertIsNone(_synthesize_order_response([{'name': 'search_products', 'result': {'products': [None]}}]))

    def test_scoped_local_and_remote_adapters(self):
        history = [{'role': 'user', 'content': 'Check order O-101'}]
        local = LocalAgent(ModelConfig())
        with patch.object(LocalOllama, 'request', return_value={'ok': True}) as request:
            local.chat_scoped(history, True, 2, ('get_order',))
        self.assertEqual([t['function']['name'] for t in request.call_args.args[1]['tools']], ['get_order'])
        with patch.object(RemoteAgent, 'gateway') as gateway:
            remote = RemoteAgent(ModelConfig(base_url='https://fixture.ngrok-free.app'), 'fixture.ngrok-free.app', 'fixture-token-' + 'x' * 40)
            remote.chat_scoped(history, True, 2, ('get_order',))
        envelope = gateway.return_value.request.call_args.args[1]
        self.assertEqual(envelope['allowed_tools'], ['get_order'])
        messages, allow = validate_envelope(envelope)
        payload = build_request('fixture', messages, allow, allowed_tools=envelope['allowed_tools'])
        self.assertEqual([t['function']['name'] for t in payload['tools']], ['get_order'])

    def test_scoped_anthropic_does_not_advertise_other_tools(self):
        with patch.dict(os.environ, {}, clear=True):
            ant = OpenRouterAgent('sk-ant-' + 'x' * 50, 'claude-3-5-haiku-20241022')
        response = {'content': [{'type': 'text', 'text': 'Done'}], 'usage': {'input_tokens': 10, 'output_tokens': 2}}
        with patch.object(ant, 'request', return_value=response) as req:
            ant.chat_scoped([{'role': 'user', 'content': 'Check order'}], True, 2, ('get_order',))
        self.assertEqual([t['name'] for t in req.call_args.args[0]['tools']], ['get_order'])

    def test_scope_envelope_rejects_unknown_duplicate_and_non_list_names(self):
        base = {'protocol': PROTOCOL, 'messages': [{'role': 'user', 'content': 'Check order'}], 'allow_tools': True}
        for names in (['delete_database'], ['get_order', 'get_order'], 'get_order', [None]):
            with self.subTest(names=names), self.assertRaises(ProtocolError):
                validate_envelope({**base, 'allowed_tools': names})
        self.assertEqual(validate_envelope(base), (base['messages'], True))
        self.assertEqual(validate_envelope({**base, 'allowed_tools': []}), (base['messages'], True))

    def test_cached_product_restores_same_focus_as_uncached(self):
        # A prior lookup warms the cache. A second turn must restore product context.
        responses = [api_response(None, [('get_product', {'product_id': 'P-101'})]), api_response('Product checked')]
        with patch.object(OpenRouterAgent, 'request', side_effect=responses):
            self.app.chat('C-001', self.body('O-819125 product P-101'))
        self.app.focus('C-001', self.cid, {'order_id': 'O-819126'})
        with patch.object(OpenRouterAgent, 'request', side_effect=copy.deepcopy(responses)):
            result = self.app.chat('C-001', self.body('O-819126 product P-101'))
        self.assertEqual(result['context'], {'order_id': None, 'product_id': 'P-101'})

    def test_products_then_empty_model_response_keeps_order_details(self):
        responses = [api_response(None, [('get_order', {'order_id': 'O-819127'}),
                                        ('get_product', {'product_id': 'P-101'})]), api_response(None)]
        with patch.object(OpenRouterAgent, 'request', side_effect=responses):
            result = self.app.chat('C-001', self.body('O-819127 product P-101'))
        self.assertIn('O-819127', result['message'])
        self.assertIn('P-101', result['message'])
        self.assertEqual(result['trace']['fallback_reason'], 'agent_response_failed')
        self.assertTrue(result['trace']['degraded'])

    def test_cached_order_restores_product_focus(self):
        responses = [api_response(None, [('get_order', {'order_id': 'O-819125'})]), api_response('Order checked')]
        with patch.object(OpenRouterAgent, 'request', side_effect=responses):
            self.app.chat('C-001', self.body())
        with self.store.connection(write=True) as db:
            db.execute("UPDATE conversations SET product_id='P-101' WHERE id=?", (self.cid,))
        with patch.object(OpenRouterAgent, 'request', side_effect=copy.deepcopy(responses)):
            result = self.app.chat('C-001', self.body())
        self.assertEqual(result['context'], {'order_id': 'O-819125', 'product_id': None})


class ScopedProxyTransportTests(unittest.TestCase):
    def test_remote_proxy_applies_requested_subset_before_local_runtime(self):
        import test_agent_http as chain
        fixture = chain.ChainTests('test_full_chat_chain_uses_fixed_protocol_tools_and_real_store')
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        class Loopback(RemoteAgent):
            def gateway(inner, timeout):
                gateway = LocalOllama(ModelConfig(base_url=fixture.proxy_url, timeout_s=timeout))
                gateway._headers['Authorization'] = 'Bearer ' + chain.TOKEN
                return gateway
        remote = Loopback(ModelConfig(base_url='https://fixture.ngrok-free.app'), 'fixture.ngrok-free.app', chain.TOKEN)
        remote.chat_scoped([{'role': 'user', 'content': 'Check order O-101'}], True, 3, ('get_order',))
        self.assertEqual([t['function']['name'] for t in fixture.upstream_requests[0]['tools']], ['get_order'])


if __name__ == '__main__':
    unittest.main()
