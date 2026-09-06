"""Provider choice and API transport contracts; no paid calls or GPU inference."""
import copy
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from agent_protocol import PROTOCOL, SYSTEM, TOOLS, ProtocolError
from retailops_agent import AgentError, run_agent
from retailops_api import ApiError, Application, BusinessStore, Server
from retailops_providers import API_MODEL, OpenRouterAgent, api_from_environment

KEY = 'test_not_a_real_key_' + 'a'*40


def api_response(content='API answer', calls=None, cost=0.0003):
    message = {'role': 'assistant', 'content': content}
    if calls:
        message['tool_calls'] = [
            {'id': 'provider_call_' + str(i), 'type': 'function', 'function': {
                'name': name, 'arguments': json.dumps(args)}} for i, (name, args) in enumerate(calls)]
    return {'model': API_MODEL, 'choices': [{'message': message, 'finish_reason': 'tool_calls' if calls else 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 30, 'cost': cost}}


class FakeAgent:
    def __init__(self, name, fail=False):
        self.name, self.model, self.fail, self.inputs = name, name, fail, []

    def inspect(self):
        return {'name': self.name, 'digest': 'fixture' if self.name == 'custom' else None,
                'provider': 'openrouter' if self.name == 'api' else 'custom', 'agent_protocol': PROTOCOL}

    def chat(self, messages, allow_tools, timeout):
        self.inputs.append(copy.deepcopy(messages))
        if self.fail:
            raise AgentError('api_credit_exhausted', 'API không đủ tín dụng.')
        return {'message': {'role': 'assistant', 'content': self.name + ' answer'},
                'prompt_eval_count': 10, 'eval_count': 5}


class ApiAdapterTests(unittest.TestCase):
    def test_tool_ids_and_reasoning_roundtrip_are_transient(self):
        adapter = OpenRouterAgent(KEY)
        first = api_response(None, [('get_order', {'order_id': 'O-101'}), ('get_product', {'product_id': 'P-101'})])
        reasoning = [{'type': 'reasoning.encrypted', 'data': 'opaque_private_block', 'format': 'fixture', 'index': 0}]
        first['choices'][0]['message']['reasoning_details'] = reasoning
        with patch.object(adapter, 'request', side_effect=[first, api_response('Final API text')]) as call:
            result = run_agent(adapter, 'Explain O-101', [], lambda name, args: {'result': name}, adapter.inspect())
        first_payload, second_payload = [x.args[0] for x in call.call_args_list]
        self.assertEqual(first_payload['messages'][0], {'role': 'system', 'content': SYSTEM})
        self.assertEqual(first_payload['tools'], TOOLS)
        self.assertEqual(second_payload['tools'], TOOLS)
        assistant = second_payload['messages'][2]
        self.assertEqual(assistant['reasoning_details'], reasoning)
        self.assertEqual([m['tool_call_id'] for m in second_payload['messages'] if m['role'] == 'tool'],
                         ['provider_call_0', 'provider_call_1'])
        self.assertNotIn('opaque_private_block', json.dumps(result))
        self.assertNotIn('reasoning_details', json.dumps(result['messages']))
        self.assertNotIn(KEY, json.dumps(first_payload))
        self.assertEqual(result['message'], 'Final API text')
        self.assertEqual(result['trace']['reported_cost_usd'], 0.0006)
        self.assertIsNone(result['trace']['model_digest'])
        self.assertEqual(adapter.for_turn()._messages, {})

    def test_completed_history_rebuilds_consistent_tool_ids(self):
        adapter = OpenRouterAgent(KEY)
        history = [{'role': 'user', 'content': 'old'}, {'role': 'assistant', 'content': '', 'tool_calls': [
            {'function': {'name': 'get_order', 'arguments': {'order_id': 'O-101'}}}]},
            {'role': 'tool', 'tool_name': 'get_order', 'content': '{}'},
            {'role': 'assistant', 'content': 'Old answer'}, {'role': 'user', 'content': 'new'}]
        out = adapter.translate(history)
        self.assertEqual(out[1]['tool_calls'][0]['id'], out[2]['tool_call_id'])
        self.assertEqual(out[1]['tool_calls'][0]['function']['arguments'], '{"order_id": "O-101"}')

    def test_disabling_tools_keeps_schema_and_disables_selection(self):
        adapter = OpenRouterAgent(KEY)
        with patch.object(adapter, 'request', return_value=api_response()) as request:
            adapter.chat([{'role': 'user', 'content': 'hello'}], False, 1)
        body = request.call_args.args[0]
        self.assertEqual(body['tool_choice'], 'none'); self.assertEqual(body['tools'], TOOLS)
        self.assertEqual(body['max_tokens'], 2048)
        self.assertEqual(body['provider'], {'only': ['meta'], 'allow_fallbacks': False})
        self.assertNotIn('models', body)

    def test_api_disabled_by_default_and_models_allowlisted(self):
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': KEY}, clear=True):
            self.assertIsNone(api_from_environment())
        with patch.dict(os.environ, {'RETAILOPS_API_ENABLED': 'true', 'OPENROUTER_API_KEY': KEY}, clear=True):
            self.assertEqual(api_from_environment().model, API_MODEL)
        for key, model in [('short', API_MODEL), (KEY+'\nheader', API_MODEL), (KEY, 'openrouter/auto')]:
            with self.subTest(model=model), self.assertRaises(ValueError):
                OpenRouterAgent(key, model)

    def test_auth_credit_and_rate_errors_do_not_echo_upstream(self):
        for status, code in [(401, 'api_auth_failed'), (402, 'api_credit_exhausted'), (429, 'api_rate_limited'), (500, 'api_unavailable')]:
            adapter = OpenRouterAgent(KEY)
            err = urllib.error.HTTPError(adapter.ENDPOINT, status, 'bad', {}, io.BytesIO(KEY.encode()))
            with patch.object(adapter._opener, 'open', side_effect=err), self.assertRaises(AgentError) as ctx:
                adapter.request({}, 1)
            self.assertEqual(ctx.exception.code, code)
            self.assertNotIn(KEY, str(ctx.exception)); self.assertNotIn(adapter.ENDPOINT, str(ctx.exception))

    def test_redirect_timeout_and_non_json_are_sanitized(self):
        adapter = OpenRouterAgent(KEY)
        for error in (RuntimeError('redirect '+KEY), urllib.error.URLError(KEY), TimeoutError(KEY)):
            with patch.object(adapter._opener, 'open', side_effect=error), self.assertRaises(AgentError) as ctx:
                adapter.request({}, 1)
            self.assertEqual(ctx.exception.code, 'api_unavailable'); self.assertNotIn(KEY, str(ctx.exception))

    def test_model_mismatch_truncated_duplicate_tool_ids_and_missing_usage_rejected(self):
        samples = []
        data = api_response(); data['model'] = 'another-model'; samples.append(data)
        data = api_response(); data['choices'][0]['finish_reason'] = 'length'; samples.append(data)
        data = api_response('', [('get_current_time', {}), ('get_context', {})])
        data['choices'][0]['message']['tool_calls'][1]['id'] = 'provider_call_0'; samples.append(data)
        data = api_response(); data['usage'] = {}; samples.append(data)
        data = api_response(); data['usage']['cost'] = float('nan'); samples.append(data)
        data = api_response(); data['choices'][0]['message']['content'] = ''; samples.append(data)
        for data in samples:
            adapter = OpenRouterAgent(KEY)
            with patch.object(adapter, 'request', return_value=data), self.assertRaises((AgentError, ProtocolError)):
                adapter.chat([{'role': 'user', 'content': 'hi'}], True, 1)

    def test_failed_api_call_keeps_error_code_and_unknown_cost(self):
        adapter = FakeAgent('api', fail=True)
        with self.assertRaises(AgentError) as ctx:
            run_agent(adapter, 'hi', [], lambda name, args: {}, adapter.inspect())
        self.assertEqual(ctx.exception.code, 'api_credit_exhausted')
        self.assertEqual(ctx.exception.trace['model_calls'], 1)
        self.assertIsNone(ctx.exception.trace['reported_cost_usd'])


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = BusinessStore(Path(self.temp.name)/'business.sqlite3'); self.store.seed()
        self.custom, self.api = FakeAgent('custom'), FakeAgent('api')
        self.app = Application(self.store, {}, self.custom, api_infer=self.api, api_daily_limit=2)

    def start(self, provider):
        return self.app.new_conversation('C-001', {'provider_id': provider})['conversation_id']

    def chat(self, cid, text='hello', key='a'*32, customer='C-001'):
        return self.app.chat(customer, {'conversation_id': cid, 'text': text, 'request_id': key})

    def error(self, code, fn):
        with self.assertRaises(ApiError) as ctx:
            fn()
        self.assertEqual(ctx.exception.code, code)

    def test_switch_is_new_conversation_and_never_shares_history(self):
        custom_cid, api_cid = self.start('custom'), self.start('api')
        self.chat(custom_cid, 'Private Colab text'); self.chat(api_cid, 'API-only text')
        self.assertNotIn('Private Colab text', json.dumps(self.api.inputs))
        self.assertNotIn('API-only text', json.dumps(self.custom.inputs))
        self.chat(custom_cid, 'Custom followup', key='b'*32)
        self.assertIn('Private Colab text', json.dumps(self.custom.inputs[-1]))
        self.assertEqual(self.store.lookup('C-001', 'O-101')['status'], 'pending')
        reopened = BusinessStore(self.store.path)
        self.assertEqual(reopened.conversation('C-001', api_cid)['provider_id'], 'api')

    def test_selecting_provider_does_not_probe_or_spend(self):
        self.app.providers(); self.start('api'); self.start('custom')
        self.assertEqual(self.api.inputs, []); self.assertEqual(self.custom.inputs, [])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM provider_daily_usage').fetchone()[0], 0)

    def test_browser_cannot_supply_keys_urls_models_or_mutate_chat_provider(self):
        for field in ('api_key', 'base_url', 'model', 'customer_id'):
            self.error('invalid_fields', lambda: self.app.new_conversation('C-001', {'provider_id': 'api', field: 'injected'}))
        self.error('invalid_provider', lambda: self.start('unknown'))
        cid = self.start('custom')
        self.error('invalid_fields', lambda: self.app.chat('C-001', {'conversation_id': cid, 'text': 'hi', 'request_id': 'a'*32, 'provider_id': 'api'}))
        self.error('conversation_not_found', lambda: self.chat(cid, customer='C-002'))

    def test_disabled_option_enforced_on_server_and_no_automatic_fallback(self):
        self.app.api_infer = None
        choices = self.app.providers()['providers']
        self.assertFalse(next(p for p in choices if p['id'] == 'api')['configured'])
        self.error('provider_not_configured', lambda: self.start('api'))
        self.app.api_infer = self.api
        cid = self.start('custom'); self.app.infer = None
        self.error('model_offline', lambda: self.chat(cid))
        self.assertEqual(self.api.inputs, [])
        cid = self.start('api'); self.api.fail = True
        self.error('api_credit_exhausted', lambda: self.chat(cid))
        self.assertEqual(self.custom.inputs, [])

    def test_daily_limit_survives_restart_and_replay_does_not_spend_again(self):
        cid = self.start('api')
        self.chat(cid); self.assertTrue(self.chat(cid)['replayed'])
        self.chat(cid, key='b'*32)
        self.app.store = BusinessStore(self.store.path)
        self.error('api_daily_limit', lambda: self.chat(cid, key='c'*32))
        self.assertEqual(len(self.api.inputs), 2)
        self.chat(self.start('custom')); self.assertEqual(len(self.custom.inputs), 1)

    def test_failed_attempts_also_consume_limit_and_no_history_is_committed(self):
        self.api.fail = True; cid = self.start('api')
        self.error('api_credit_exhausted', lambda: self.chat(cid))
        self.error('api_credit_exhausted', lambda: self.chat(cid))
        self.error('api_daily_limit', lambda: self.chat(cid))
        self.assertEqual(self.store.history('C-001', cid), [])

    def test_metadata_does_not_expose_endpoint_or_key(self):
        self.app.api_infer = OpenRouterAgent(KEY)
        metadata = json.dumps(self.app.providers())
        self.assertNotIn(KEY, metadata); self.assertNotIn('https://', metadata)
        self.assertIn(API_MODEL, metadata)

    def test_v04_conversations_migrate_to_custom_without_reset(self):
        path = Path(self.temp.name)/'v04.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE conversations (id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, order_id TEXT, product_id TEXT, revision INTEGER NOT NULL DEFAULT 0, expires_at REAL NOT NULL)')
            db.execute("INSERT INTO conversations VALUES ('old','C-001','O-101','P-101',4,99999999999)")
        migrated = BusinessStore(path)
        with migrated.connection() as db:
            row = dict(db.execute("SELECT * FROM conversations WHERE id='old'").fetchone())
        self.assertEqual((row['provider_id'], row['revision'], row['order_id']), ('custom', 4, 'O-101'))


class SelectorHttpTests(unittest.TestCase):
    def test_authenticated_options_and_selection_reach_correct_gateway(self):
        with tempfile.TemporaryDirectory() as folder:
            store = BusinessStore(Path(folder)/'business.sqlite3'); store.seed()
            custom, external = FakeAgent('custom'), FakeAgent('api')
            token = 't'*40
            app = Application(store, {hashlib.sha256(token.encode()).hexdigest(): 'C-001'}, custom, external)
            server = Server(('127.0.0.1', 0), app)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def request(path, body=None, auth=True):
                req = urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+path,
                    data=None if body is None else json.dumps(body).encode(), headers={'Content-Type': 'application/json',
                    **({'Authorization': 'Bearer '+token} if auth else {})})
                try: resp = http.open(req, timeout=3)
                except urllib.error.HTTPError as err: resp = err
                with resp: return resp.status, json.load(resp)
            try:
                self.assertEqual(request('/api/providers', auth=False)[0], 401)
                self.assertEqual(len(request('/api/providers')[1]['providers']), 2)
                cid = request('/api/conversations', {'provider_id': 'api'})[1]['conversation_id']
                status, result = request('/api/chat', {'conversation_id': cid, 'text': 'hello', 'request_id': 'a'*32})
                self.assertEqual(status, 200); self.assertEqual(result['provider_id'], 'api')
                self.assertEqual(result['message'], 'api answer'); self.assertEqual(custom.inputs, [])
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
