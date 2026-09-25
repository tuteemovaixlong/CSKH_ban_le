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
    def test_t01_select_order_context_resolves_without_asking_again(self):
        """T01: When order facts are returned via get_context/get_order, response presents facts without asking to select."""
        tool_results = [
            {'name': 'get_context', 'args': {}, 'result': {
                'order': {'id': 'O-819125', 'name': 'Áo sơ mi lụa công sở', 'variant': 'Trắng / M', 'amount': 450000, 'status': 'pending'}
            }}
        ]
        res = _synthesize_order_response(tool_results)
        self.assertIsNotNone(res)
        self.assertIn('O-819125', res)
        self.assertIn('Áo sơ mi lụa công sở', res)
        self.assertNotIn('Chưa có đơn hoặc sản phẩm được chọn', res)

    def test_t02_followup_more_info_uses_verified_order_without_guessing_pending_cause(self):
        """T02: More info follow-up preserves verified order facts and does not invent missing shipment causes."""
        tool_results = [
            {'name': 'get_order', 'args': {'order_id': 'O-819125'}, 'result': {
                'order': {'id': 'O-819125', 'name': 'Áo sơ mi lụa công sở', 'variant': 'Trắng / M', 'amount': 450000, 'status': 'pending'}
            }},
            {'name': 'track_shipment', 'args': {'order_id': 'O-819125'}, 'result': {'shipment': {}}}
        ]
        res = _synthesize_order_response(tool_results)
        self.assertIsNotNone(res)
        self.assertIn('O-819125', res)
        self.assertNotIn('do đơn hàng đang pending nên chưa có mã vận đơn', res.lower())

    def test_t03_list_orders_then_duplicate_get_order_then_dispute_tool_blocked(self):
        """T03: Sequence list_orders -> duplicate get_order -> unallowed tool does not trigger tool_response_failed."""
        tool_results = [
            {'name': 'list_orders', 'args': {}, 'result': {'orders': [
                {'id': 'O-819126', 'name': 'Quần tây ống đứng tôn dáng', 'variant': 'Đen / L', 'amount': 520000, 'status': 'delivered'}
            ]}},
            {'name': 'get_order', 'args': {'order_id': 'O-819126'}, 'result': {'order': {
                'id': 'O-819126', 'name': 'Quần tây ống đứng tôn dáng', 'variant': 'Đen / L', 'amount': 520000, 'status': 'delivered'
            }}},
            {'name': 'prepare_cancellation', 'args': {'order_id': 'O-819126'}, 'result': {'error': 'tool_not_allowed'}}
        ]
        res = _synthesize_order_response(tool_results)
        self.assertIsNotNone(res)
        self.assertIn('O-819126', res)
        self.assertIn('Quần tây ống đứng tôn dáng', res)
        self.assertIn('Một phần tra cứu bổ sung không thực hiện được', res)

    def test_t04_distinct_ids_o12_and_o123_not_confused_by_substring(self):
        """T04: Substring O-12 inside O-123 is not conflated during deduplication."""
        tool_results = [
            {'name': 'list_orders', 'args': {}, 'result': {'orders': [
                {'id': 'O-12', 'name': 'Item Twelve', 'variant': 'V1', 'amount': 120000, 'status': 'delivered'},
                {'id': 'O-123', 'name': 'Item OneTwoThree', 'variant': 'V2', 'amount': 230000, 'status': 'pending'}
            ]}},
            {'name': 'get_order', 'args': {'order_id': 'O-123'}, 'result': {'order': {
                'id': 'O-123', 'name': 'Item OneTwoThree', 'variant': 'V2', 'amount': 230000, 'status': 'pending'
            }}}
        ]
        res = _synthesize_order_response(tool_results)
        self.assertIsNotNone(res)
        self.assertIn('O-12: Đã giao', res)
        self.assertIn('O-123: Chờ xử lý', res)

    def test_t05_ownership_denied_or_missing_order_does_not_fabricate_confirmation(self):
        """T05: Missing or forbidden order returns denial, never synthesizes fake order confirmation."""
        not_found_res = _synthesize_order_response([
            {'name': 'get_order', 'args': {'order_id': 'O-999999'}, 'result': {'error': 'order_not_found'}}
        ])
        self.assertIsNotNone(not_found_res)
        self.assertIn('Không tìm thấy đơn hàng O-999999', not_found_res)
        self.assertNotIn('Đã giao', not_found_res)

        forbidden_res = _synthesize_order_response([
            {'name': 'get_order', 'args': {'order_id': 'O-888888'}, 'result': {'error': 'forbidden'}}
        ])
        self.assertIsNotNone(forbidden_res)
        self.assertIn('không có quyền thực hiện tra cứu này', forbidden_res)

    def test_t06_google_login_seeds_product_id_and_backfill_is_idempotent(self):
        """T06: Google login seeds valid product_ids from catalog, and backfill script is idempotent."""
        from retailops.identity.persistent import PersistentSessions
        from retailops.storage.backfill import backfill_sqlite
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        sessions = PersistentSessions(Path(temp_dir.name))
        sessions.provision_tenant('test-tenant', 'Test Shop', seed_demo=True)
        sessions.login_google('customer1@example.com', 'Customer One')
        bstore = sessions.business_store('test-tenant')

        # Check seeded orders have product_ids
        with bstore.connection() as conn:
            cust = conn.execute("SELECT id FROM customers WHERE name='Customer One'").fetchone()
            self.assertIsNotNone(cust)
            orders = conn.execute("SELECT id, name, product_id FROM orders WHERE customer_id=?", (cust['id'],)).fetchall()
            self.assertEqual(len(orders), 3)
            pids = {o['product_id'] for o in orders}
            self.assertEqual(pids, {'P-601', 'P-602', 'P-603'})

        # Run backfill: first run should find 0 to update because they're already linked
        tenant_file = sessions.tenant_path(sessions.control.ensure_tenant('test-tenant', 'Test Shop'))
        run1 = backfill_sqlite(tenant_file, dry_run=False)
        self.assertEqual(run1['to_update'], 0)
        self.assertEqual(run1['updated'], 0)

        # Re-run backfill: second run must also be 0 (idempotent)
        run2 = backfill_sqlite(tenant_file, dry_run=False)
        self.assertEqual(run2['to_update'], 0)
        self.assertEqual(run2['updated'], 0)

    def test_t07_missing_catalog_link_and_shipment_states_missing_without_inventing_facts(self):
        """T07: Order lacking catalog link and carrier shipment still preserves order facts truthfully."""
        tool_results = [
            {'name': 'get_order', 'args': {'order_id': 'O-819125'}, 'result': {
                'order': {'id': 'O-819125', 'name': 'Áo sơ mi lụa công sở', 'variant': 'Trắng / M', 'amount': 450000, 'status': 'pending'}
            }},
            {'name': 'get_product', 'args': {'product_id': 'P-999'}, 'result': {'error': 'product_not_found'}}
        ]
        res = _synthesize_order_response(tool_results)
        self.assertIsNotNone(res)
        self.assertIn('O-819125', res)
        self.assertIn('Áo sơ mi lụa công sở', res)
        self.assertIn('Danh mục chưa có sản phẩm khớp mã tra cứu', res)

    def test_t08_image_with_purchase_query_reaches_model_payload_and_routes_to_order_agent(self):
        """T08: Image query about purchasing routes to order_agent, includes image_url in payload, no canned greeting."""
        att = {'type': 'image', 'data': 'aW1hZ2U=', 'mime_type': 'image/jpeg', 'name': 'pant.jpg'}
        st = state('Có đơn nào mua món này không?')
        st['messages'][-1]['attachment'] = att
        routed = run_supervisor(st)
        self.assertEqual(routed['next_worker'], 'order_agent')

        responses = [
            api_response(None, [('list_orders', {})]),
            api_response('Bạn đã đặt Quần tây ống đứng tôn dáng trong đơn O-819126.')
        ]
        with patch.object(OpenRouterAgent, 'request', side_effect=responses) as req:
            result = self.app.chat('C-001', self.body('Có đơn nào mua món này không?', attachment=att))
        first_call_msgs = req.call_args_list[0].args[0]['messages']
        user_entry = next(m for m in first_call_msgs if m['role'] == 'user')
        self.assertEqual(user_entry['content'][1]['image_url']['url'], 'data:image/jpeg;base64,aW1hZ2U=')
        self.assertNotIn('Dạ em là trợ lý bán lẻ', result['message'])
        self.assertIn(result['source'], ('llm_agent', 'model'))

    def test_t09_image_multiturn_followup_without_reupload_restores_image_from_history(self):
        """T09: Follow-up turn referencing image restores attachment from conversation history without re-upload."""
        att = {'type': 'image', 'data': 'aW1hZ2U=', 'mime_type': 'image/jpeg', 'name': 'pant.jpg'}
        # Turn 1 with image
        with patch.object(OpenRouterAgent, 'request', return_value=api_response('Tôi thấy bạn gửi ảnh quần tây.')):
            self.app.chat('C-001', self.body('Món này tôi từng mua chưa?', attachment=att))

        # Turn 2 follow-up without attachment
        with patch.object(OpenRouterAgent, 'request', return_value=api_response('Đã đọc lại ảnh từ lịch sử và kiểm tra')) as req:
            result2 = self.app.chat('C-001', self.body('đọc ảnh check tiếp đơn cho tôi xem'))
        turn2_msgs = req.call_args.args[0]['messages']
        user_entry2 = next(m for m in turn2_msgs if m['role'] == 'user')
        self.assertTrue(any(item.get('type') == 'image_url' for item in user_entry2['content']))
        self.assertEqual(result2['message'], 'Đã đọc lại ảnh từ lịch sử và kiểm tra')

    def test_t10_attachment_isolation_across_conversations_and_customers(self):
        """T10: Attachments do not leak to other conversations or other customers."""
        att = {'type': 'image', 'data': 'aW1hZ2U=', 'mime_type': 'image/jpeg', 'name': 'pant.jpg'}
        # Turn 1 with image in cid (C-001)
        with patch.object(OpenRouterAgent, 'request', return_value=api_response('Nhận được ảnh')):
            self.app.chat('C-001', self.body('Ảnh sản phẩm', attachment=att))

        # New conversation for C-001
        cid_new = self.app.new_conversation('C-001', {'provider_id': 'api'})['conversation_id']
        body_new = {'conversation_id': cid_new, 'text': 'đọc ảnh check tiếp', 'request_id': str(uuid.uuid4())}
        with patch.object(OpenRouterAgent, 'request', return_value=api_response('Không có ảnh nào')) as req:
            self.app.chat('C-001', body_new)
        user_entry = next(m for m in req.call_args.args[0]['messages'] if m['role'] == 'user')
        if isinstance(user_entry['content'], list):
            self.assertFalse(any(item.get('type') == 'image_url' for item in user_entry['content']))

        # Conversation for C-002
        cid_c2 = self.app.new_conversation('C-002', {'provider_id': 'api'})['conversation_id']
        body_c2 = {'conversation_id': cid_c2, 'text': 'đọc ảnh check tiếp', 'request_id': str(uuid.uuid4())}
        with patch.object(OpenRouterAgent, 'request', return_value=api_response('Không có ảnh nào')) as req:
            self.app.chat('C-002', body_c2)
        user_entry_c2 = next(m for m in req.call_args.args[0]['messages'] if m['role'] == 'user')
        if isinstance(user_entry_c2['content'], list):
            self.assertFalse(any(item.get('type') == 'image_url' for item in user_entry_c2['content']))

    def test_t11_visual_match_presents_backend_candidates_without_unverified_certainty(self):
        """T11: Candidate products from visual/search match are framed as candidates without 100% certainty."""
        tool_results = [
            {'name': 'search_products', 'args': {'query': 'quần tây'}, 'result': {'products': [
                {'id': 'P-602', 'name': 'Quần tây ống đứng tôn dáng', 'category': 'Thời trang', 'variants': ['Đen · Size S/M/L'], 'price': 520000}
            ]}}
        ]
        res = _synthesize_order_response(tool_results)
        self.assertIsNotNone(res)
        self.assertIn('Sản phẩm khớp trong danh mục (chưa xác nhận liên kết với đơn):', res)
        self.assertIn('P-602', res)
        self.assertIn('Quần tây ống đứng tôn dáng', res)

    def test_t12_truncated_order_list_explicitly_informs_customer(self):
        """T12: When list_orders is truncated, synthesized response clearly notifies customer."""
        tool_results = [
            {'name': 'list_orders', 'args': {}, 'result': {
                'orders': [{'id': f'O-{i}', 'name': f'Item {i}', 'status': 'delivered'} for i in range(10)],
                'truncated': True
            }}
        ]
        res = _synthesize_order_response(tool_results)
        self.assertIn('Danh sách đã rút gọn; còn các đơn khác chưa hiển thị.', res)

    def test_t13_payment_method_and_false_image_terms_route_to_policy_agent(self):
        """T13: 'hình thức thanh toán', 'tình hình', 'ảnh hưởng' do not falsely trigger image routing."""
        s1 = state('Shop cho mình hỏi hình thức thanh toán bên mình như thế nào ạ?')
        r1 = run_supervisor(s1)
        self.assertEqual(r1['next_worker'], 'policy_agent')

        s2 = state('Tình hình thời tiết có ảnh hưởng đến thời gian giao hàng không?')
        r2 = run_supervisor(s2)
        self.assertNotIn('image', r2.get('trace', {}).get('routing_reason', ''))

    def test_t14_store_inquiry_and_no_hardcoded_customer_orders_in_prompt(self):
        """T14: Store info routed appropriately and prompt contains zero customer order hardcodes."""
        s = state('Shop tên gì?')
        r = run_supervisor(s)
        self.assertEqual(r['next_worker'], 'order_agent')

        from retailops.workflow.subagents.order_agent import ORDER_SYSTEM_PROMPT
        self.assertNotIn('O-819125', ORDER_SYSTEM_PROMPT)
        self.assertNotIn('O-819126', ORDER_SYSTEM_PROMPT)
        self.assertNotIn('O-819127', ORDER_SYSTEM_PROMPT)

    def test_t15_code_block_text_call_and_unclosed_thought_hardening(self):
        """T15: Calls in markdown code blocks are ignored; unclosed thought tags are cleanly stripped."""
        from agent_protocol import assistant_message
        resp_code_block = {
            'message': {
                'role': 'assistant',
                'content': 'Đây là ví dụ mã lệnh:\n```python\ncall:get_order{"order_id": "O-9999"}\n```\nBạn xem nhé.'
            }
        }
        msg = assistant_message(resp_code_block)
        self.assertFalse(msg.get('tool_calls'))
        self.assertIn('Đây là ví dụ mã lệnh', msg['content'])

        resp_unclosed = {
            'message': {
                'role': 'assistant',
                'content': 'Dạ chào anh/chị!\n<thought>Tôi đang suy nghĩ về đơn hàng này chưa đóng tag'
            }
        }
        msg_unclosed = assistant_message(resp_unclosed)
        self.assertNotIn('Tôi đang suy nghĩ', msg_unclosed['content'])
        self.assertIn('Dạ chào anh/chị!', msg_unclosed['content'])

    def test_t16_witty_agent_records_system_fallback_when_unexpected_tools_produced(self):
        """T16: When model emits unexpected tool calls with tools disabled, witty agent records system_fallback."""
        from retailops.workflow.subagents.witty_agent import run_witty_agent
        bad_resp = api_response(None, [('get_order', {'order_id': 'O-123'})])
        with patch.object(self.adapter, 'chat', return_value={'message': {'role': 'assistant', 'content': '', 'tool_calls': [{'function': {'name': 'get_order', 'arguments': '{}'}}]}}):
            s = state('Hôm nay thời tiết thế nào?')
            out = run_witty_agent(s, self.adapter)
        self.assertEqual(out['trace']['answer_source'], 'system_fallback')
        self.assertTrue(out['trace']['degraded'])
        self.assertEqual(out['trace']['fallback_reason'], 'unexpected_tools_in_no_tool_worker')
        self.assertIn('witty_agent:fallback', out['subagent_history'])
        self.assertNotIn('witty_agent:pivot_success', out['subagent_history'])

    def test_t17_provider_trace_classifies_http_errors_and_masks_keys(self):
        """T17: HTTP errors are classified by status code and error_kind without leaking secrets."""
        import io
        import urllib.error

        agent = OpenRouterAgent(KEY, MODEL)
        err400 = urllib.error.HTTPError('https://fixture.example', 400, 'Bad Request', {}, io.BytesIO(b'{"error": "bad"}'))
        with patch.object(agent._opener, 'open', side_effect=err400):
            with self.assertRaises(AgentError) as cm:
                agent.request({'messages': []}, 5)
            self.assertEqual(cm.exception.trace.get('http_status'), 400)
            self.assertEqual(cm.exception.trace.get('error_kind'), 'bad_request')
            self.assertNotIn(KEY, str(cm.exception))

        err413 = urllib.error.HTTPError('https://fixture.example', 413, 'Payload Too Large', {}, io.BytesIO(b'too big'))
        with patch.object(agent._opener, 'open', side_effect=err413):
            with self.assertRaises(AgentError) as cm:
                agent.request({'messages': []}, 5)
            self.assertEqual(cm.exception.trace.get('http_status'), 413)
            self.assertEqual(cm.exception.trace.get('error_kind'), 'payload_too_large')

        with patch.object(agent._opener, 'open', side_effect=TimeoutError('Connection timed out')):
            with self.assertRaises(AgentError) as cm:
                agent.request({'messages': []}, 5)
            self.assertEqual(cm.exception.trace.get('error_kind'), 'timeout')

    def test_t18_order_id_typo_handling_and_normalization(self):
        """T18: Order ID typos like O0819127 are routed appropriately and normalized by dispute handler."""
        s = state('Kiểm tra đơn O0819127 xem giao đến đâu')
        r = run_supervisor(s)
        self.assertEqual(r['next_worker'], 'order_agent')

        from retailops.workflow.subagents.dispute_agent import run_dispute_agent
        disp_state = state('Tôi muốn hủy đơn O0819127')
        mock_tool = lambda n, a: {'eligible': True, 'order_id': a.get('order_id')}
        tool_call = {'function': {'name': 'prepare_cancellation', 'arguments': json.dumps({'order_id': 'O0819127', 'reason': 'Đổi ý'})}}
        with patch.object(self.adapter, 'chat', return_value={'message': {'role': 'assistant', 'content': '', 'tool_calls': [tool_call]}}):
            out = run_dispute_agent(disp_state, mock_tool, self.adapter)
        self.assertEqual(out.get('action_proposal', {}).get('order_id'), 'O-819127')

    def test_t19_worker_model_errors_preserves_upstream_http_metadata(self):
        """T19: Worker model_errors preserves upstream http_status and error_kind diagnostics."""
        from retailops.workflow.subagents.order_agent import run_order_agent
        order_st = state('Kiểm tra đơn O-819127')
        http_err_trace = {'http_status': 400, 'error_kind': 'bad_request'}
        with patch.object(self.adapter, 'chat_scoped', side_effect=AgentError('api_unavailable', 'Bad request', http_err_trace)):
            with self.assertRaises(AgentError) as cm:
                run_order_agent(order_st, lambda n, a: {}, self.adapter)
            errors = cm.exception.trace.get('model_errors', [])
            self.assertTrue(len(errors) > 0)
            self.assertEqual(errors[0].get('code'), 'api_unavailable')
            self.assertEqual(errors[0].get('http_status'), 400)
            self.assertEqual(errors[0].get('error_kind'), 'bad_request')


if __name__ == '__main__':
    unittest.main()

