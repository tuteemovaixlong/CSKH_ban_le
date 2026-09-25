"""Tests for safe tool summarization and multi-turn ReAct execution without 500 crashes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.workflow.subagents.read_worker import _summarize_tool_result


class ToolSummarySafetyUnitTests(unittest.TestCase):
    def test_summarize_get_context_with_none_values(self):
        # Must not raise AttributeError
        res = _summarize_tool_result('get_context', {}, {'order': None, 'product': None})
        self.assertEqual(res, 'Context: không có focus')

        res2 = _summarize_tool_result('get_context', {}, {'order': {'id': 'O-99'}, 'product': None})
        self.assertEqual(res2, 'Context: đơn O-99')

        res3 = _summarize_tool_result('get_context', {}, {'order': None, 'product': {'id': 'P-101'}})
        self.assertEqual(res3, 'Context: sản phẩm P-101')

        res4 = _summarize_tool_result('get_context', None, {})
        self.assertEqual(res4, 'Context: không có focus')

    def test_summarize_get_order_with_none(self):
        res = _summarize_tool_result('get_order', {'order_id': 'O-101'}, {'order': None})
        self.assertEqual(res, 'Không có thông tin đơn hàng')

    def test_summarize_get_product_with_none(self):
        res = _summarize_tool_result('get_product', {'product_id': 'P-101'}, {'product': None})
        self.assertEqual(res, 'Không có thông tin sản phẩm')

    def test_summarize_track_shipment_with_none(self):
        res = _summarize_tool_result('track_shipment', {'order_id': 'O-101'}, {'shipment': None})
        self.assertEqual(res, 'Chưa có thông tin vận đơn')

    def test_summarize_search_knowledge_with_none(self):
        res = _summarize_tool_result('search_knowledge', {'query': 'đổi trả'}, {'results': None})
        self.assertEqual(res, 'Tìm thấy 0 tài liệu chính sách liên quan')

    def test_summarize_list_orders_with_none(self):
        res = _summarize_tool_result('list_orders', {}, {'orders': None})
        self.assertEqual(res, 'Tìm thấy 0 đơn hàng trong tài khoản')

    def test_summarize_malformed_inputs(self):
        # Should not raise exception on non-dict result or invalid args
        self.assertEqual(_summarize_tool_result('unknown_tool', None, None), 'Kết quả không xác định')
        self.assertEqual(_summarize_tool_result('unknown_tool', {}, 'string_result'), 'Kết quả không xác định')


class MockReActGateway:
    def __init__(self, tool_to_call='get_context'):
        self.tool_to_call = tool_to_call
        self.calls = 0

    def inspect(self):
        return {
            'name': 'mock-gemma4-react',
            'digest': 'mock-digest',
            'provider': 'custom_api',
            'ollama_version': '0.1'
        }

    def chat_scoped(self, messages, allow_tools, timeout, allowed_tools):
        return self.chat(messages, allow_tools, timeout)

    def chat(self, messages, allow_tools, timeout):
        self.calls += 1
        last_msg = messages[-1]
        if last_msg.get('role') == 'tool':
            return {
                'message': {
                    'role': 'assistant',
                    'content': 'Dạ mình đã kiểm tra thông tin đơn hàng của bạn rồi ạ.'
                },
                'done_reason': 'stop',
                'prompt_eval_count': 100,
                'eval_count': 30,
                'reasoning': 'User received order info.'
            }

        if allow_tools:
            return {
                'message': {
                    'role': 'assistant',
                    'content': '',
                    'tool_calls': [
                        {
                            'function': {
                                'name': self.tool_to_call,
                                'arguments': {}
                            }
                        }
                    ]
                },
                'done_reason': 'tool_calls',
                'prompt_eval_count': 80,
                'eval_count': 15,
                'reasoning': 'Need to check order context first.'
            }

        return {
            'message': {
                'role': 'assistant',
                'content': 'Dạ shop xin chào bạn ạ!'
            },
            'done_reason': 'stop',
            'prompt_eval_count': 50,
            'eval_count': 20
        }


class ReActEndToEndIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = BusinessStore(Path(self.temp.name) / 'business.sqlite3')
        self.store.seed()
        self.gateway = MockReActGateway()
        self.app = Application(self.store, {}, infer=self.gateway, orchestrator='multi_agent')
        self.cid = self.store.new_conversation('C-001')['conversation_id']

    def test_unfocused_order_query_does_not_500(self):
        result = self.app.chat('C-001', {
            'conversation_id': self.cid,
            'text': 'cho tôi biết mọi chi tiết của đơn này',
            'request_id': str(uuid.uuid4())
        })
        self.assertEqual(result['action'], 'reply')
        self.assertEqual(result['source'], 'llm_agent')
        steps = result.get('trace', {}).get('steps', [])
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]['tools'][0]['summary'], 'Context: không có focus')
        self.assertEqual(steps[1]['action'], 'final_answer')

    def test_focused_order_query_does_not_500(self):
        snapshot = self.store.conversation('C-001', self.cid)
        self.store.remember('C-001', snapshot, 'O-101', None)
        result = self.app.chat('C-001', {
            'conversation_id': self.cid,
            'text': 'giải thích đơn tôi đang select',
            'request_id': str(uuid.uuid4())
        })
        self.assertEqual(result['action'], 'reply')
        self.assertEqual(result['source'], 'llm_agent')
        steps = result.get('trace', {}).get('steps', [])
        self.assertEqual(len(steps), 2)
        self.assertIn('đơn O-101', steps[0]['tools'][0]['summary'])
        self.assertEqual(steps[1]['action'], 'final_answer')


if __name__ == '__main__':
    unittest.main()
