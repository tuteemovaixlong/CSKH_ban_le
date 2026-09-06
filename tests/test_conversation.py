import hashlib
import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock

from retailops_api import ApiError, Application, BusinessStore, Server


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = BusinessStore(Path(self.temp.name) / 'business.sqlite3')
        self.store.seed()
        self.model = Mock(return_value={'valid': True, 'decision': {
            'action': 'cancel_order', 'order_id': 'O-101', 'cancel_reason': 'ordered_by_mistake'}})
        self.app = Application(self.store, {}, self.model)
        self.cid = self.store.new_conversation('C-001')['conversation_id']

    def chat(self, text, cid=None, customer='C-001'):
        return self.app.chat(customer, {'text': text, 'conversation_id': cid or self.cid})

    def assert_error(self, code, call):
        with self.assertRaises(ApiError) as context:
            call()
        self.assertEqual(context.exception.code, code)

    def test_greetings_and_general_questions_without_gpu(self):
        self.app.infer = None
        for text, expected in [('hello', 'greeting'), ('Xin chào!', 'greeting'), ('Cảm ơn bạn', 'courtesy'),
                               ('giải thích thuật toán SAC', 'unsupported'), ('hôm nay là ngày mấy', 'unsupported'),
                               ('định lý Pitago là gì', 'unsupported')]:
            with self.subTest(text=text):
                result = self.chat(text)
                self.assertEqual(result['action'], expected)
                self.assertFalse(result['model_used'])
                self.assertNotIn('Vui lòng nêu rõ một mã đơn', result['message'])

    def test_full_order_and_followup_amount_are_grounded(self):
        first = self.chat('O-101, cho tôi biết mọi thứ về mã đơn này')
        for fact in ['O-101', 'Áo thun Essential', 'Trắng', 'Size M', '299.000', 'Chờ xử lý', 'chưa có']:
            self.assertIn(fact, first['message'])
        self.assertEqual(first['context']['order_id'], 'O-101')
        self.assertIn('299.000', self.chat('Đơn này bao nhiêu tiền?')['message'])
        self.model.assert_not_called()

    def test_named_product_and_missing_material(self):
        result = self.chat('Áo khoác Everyday là gì?')
        self.assertEqual(result['product']['id'], 'P-102')
        self.assertEqual(result['source'], 'catalog')
        self.assertIn('Size L', result['message'])
        detail = self.chat('Áo này chất liệu gì?')
        self.assertIn('chưa có thông tin chất liệu', detail['message'])
        self.assertIn('Everyday', detail['message'])
        self.assertNotIn('cotton', detail['message'].lower())

    def test_unknown_named_product_does_not_reuse_previous_product(self):
        self.chat('Áo khoác Everyday là gì?')
        result = self.chat('Áo Galaxy là gì?')
        self.assertEqual(result['action'], 'product_not_found')
        self.assertIsNone(result['context']['product_id'])
        self.assertEqual(self.chat('Chất liệu gì?')['action'], 'clarify')

    def test_product_price_and_unlisted_variants_not_invented(self):
        self.chat('Xem O-102')
        price = self.chat('Áo này giá bao nhiêu?')
        self.assertIn('chưa có thông tin giá bán hiện tại', price['message'])
        self.assertNotIn('799', price['message'])
        variants = self.chat('Có size S không?')
        self.assertIn('Size L', variants['message'])
        self.assertIn('chưa xác nhận', variants['message'])

    def test_manual_order_selection_sets_product_context(self):
        self.app.focus('C-001', self.cid, {'order_id': 'O-102'})
        result = self.chat('Áo này là gì?')
        self.assertEqual(result['product']['name'], 'Áo khoác Everyday')
        self.assertEqual(result['context']['order_id'], 'O-102')

    def test_followups_read_new_state_after_cancellation(self):
        self.chat('Kiểm tra O-101')
        proposal = self.store.propose('C-001', {'order_id': 'O-101', 'order_version': 1, 'cancel_reason': 'ordered_by_mistake'})
        self.store.confirm('C-001', proposal['proposal_id'], {'confirmed': True}, 'a'*32)
        result = self.chat('Đơn này đã hủy chưa?')
        self.assertIn('đã hủy', result['message'])
        self.assertEqual(result['order']['version'], 2)
        self.assertEqual(self.chat('Cho tôi thông tin đơn này')['order']['status'], 'cancelled')

    def test_missing_shipping_payment_and_stock_not_invented(self):
        self.chat('Xem O-101')
        for text, fragment in [('Bao giờ giao hàng?', 'chưa có mã vận đơn'),
                               ('Đã thanh toán chưa?', 'chưa có dữ liệu thanh toán'),
                               ('Áo này còn hàng không?', 'chưa có thông tin tồn kho')]:
            with self.subTest(text=text):
                self.assertIn(fragment, self.chat(text)['message'])

    def test_cancellation_uses_context_but_never_executes_from_chat(self):
        self.chat('Xem O-101')
        result = self.chat('Hủy đơn này vì tôi đặt nhầm')
        self.assertEqual(result['action'], 'choose_cancel_reason')
        self.assertTrue(result['model_used'])
        self.assertIn('O-101', self.model.call_args.args[0])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM proposals').fetchone()[0], 0)
        self.assertEqual(self.store.lookup('C-001', 'O-101')['status'], 'pending')

    def test_model_cannot_switch_context_to_a_different_order(self):
        self.chat('Xem O-101')
        self.model.return_value['decision']['order_id'] = 'O-202'
        self.assert_error('ungrounded_order', lambda: self.chat('Hủy đơn này vì tôi đặt nhầm'))
        self.assertIsNone(self.store.conversation('C-001', self.cid)['order_id'])

    def test_multiple_orders_clear_context_instead_of_guessing(self):
        self.chat('Xem O-101')
        result = self.chat('Tra O-101 và O-102')
        self.assertEqual(result['action'], 'clarify')
        self.assertIsNone(result['context']['order_id'])
        self.assertEqual(self.chat('Hủy đơn này')['action'], 'clarify')
        self.model.assert_not_called()

    def test_failed_explicit_lookup_cannot_fall_back_to_previous_order(self):
        self.chat('Xem O-101')
        self.assert_error('order_not_found', lambda: self.chat('Xem O-202'))
        self.assertEqual(self.chat('Hủy đơn này')['action'], 'clarify')

    def test_context_separate_for_tabs_and_customers(self):
        self.chat('Xem O-101')
        other = self.store.new_conversation('C-001')['conversation_id']
        self.assertEqual(self.chat('Đơn này thế nào?', cid=other)['action'], 'clarify')
        self.assert_error('conversation_not_found', lambda: self.chat('Đơn này thế nào?', customer='C-002'))
        self.assert_error('order_not_found', lambda: self.app.focus('C-001', self.cid, {'order_id': 'O-202'}))

    def test_new_product_clears_unrelated_order_for_later_cancellation(self):
        self.chat('Xem O-101')
        result = self.chat('Áo khoác Everyday là gì?')
        self.assertIsNone(result['context']['order_id'])
        self.assertEqual(self.chat('Hủy đơn này')['action'], 'clarify')

    def test_context_expiry_and_conflicting_updates(self):
        snapshot = self.store.conversation('C-001', self.cid)
        self.app.focus('C-001', self.cid, {'order_id': 'O-101'})
        self.assert_error('conversation_changed', lambda: self.store.remember('C-001', snapshot, 'O-102', 'P-102'))
        with self.store.connection(write=True) as db:
            db.execute('UPDATE conversations SET expires_at=? WHERE id=?', (time.time()-1, self.cid))
        self.assert_error('conversation_expired', lambda: self.chat('Xem O-101'))

    def test_keep_order_and_cancellation_policy_do_not_call_model(self):
        self.chat('Xem O-101')
        for text, action in [('Đừng hủy đơn này', 'keep_order'), ('Giữ đơn hàng', 'keep_order'),
                             ('Đơn này có thể hủy không?', 'lookup_order')]:
            with self.subTest(text=text):
                self.assertEqual(self.chat(text)['action'], action)
        self.model.assert_not_called()

    def test_state_survives_process_restart_but_new_session_has_no_context(self):
        self.chat('Xem O-102')
        reopened = BusinessStore(self.store.path)
        self.assertEqual(reopened.conversation('C-001', self.cid)['order_id'], 'O-102')
        new = reopened.new_conversation('C-001')
        self.assertIsNone(new['context']['order_id'])

    def test_existing_database_migrates_without_resetting_orders(self):
        path = Path(self.temp.name) / 'old.sqlite3'
        # A real v0.2 schema fixture: create via the original tables, no conversations.
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE orders (id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, name TEXT NOT NULL, variant TEXT NOT NULL, amount INTEGER NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, cancel_reason TEXT)')
            db.execute("INSERT INTO orders VALUES ('O-101','C-001','Áo thun Essential','M',299000,'cancelled',2,'ordered_by_mistake')")
        migrated = BusinessStore(path)
        migrated.seed()
        self.assertEqual(migrated.lookup('C-001', 'O-101')['status'], 'cancelled')
        self.assertEqual(migrated.lookup('C-001', 'O-101')['version'], 2)
        self.assertTrue(migrated.new_conversation('C-001')['conversation_id'])


class ConversationHttpTests(unittest.TestCase):
    def test_session_focus_chat_and_cross_customer_access(self):
        with tempfile.TemporaryDirectory() as folder:
            store = BusinessStore(Path(folder) / 'business.sqlite3'); store.seed()
            tokens = {hashlib.sha256(('a'*40).encode()).hexdigest(): 'C-001', hashlib.sha256(('b'*40).encode()).hexdigest(): 'C-002'}
            server = Server(('127.0.0.1', 0), Application(store, tokens))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def post(path, body, token='a'*40):
                request = urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+path,
                    data=json.dumps(body).encode(), headers={'Authorization': 'Bearer '+token, 'Content-Type': 'application/json'})
                try:
                    response = http.open(request, timeout=3)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    return response.status, json.load(response)
            try:
                status, session = post('/api/conversations', {})
                self.assertEqual(status, 201)
                cid = session['conversation_id']
                self.assertEqual(post('/api/conversations/'+cid+'/focus', {'order_id': 'O-102'})[0], 200)
                status, answer = post('/api/chat', {'conversation_id': cid, 'text': 'Áo này là gì?'})
                self.assertEqual(status, 200)
                self.assertEqual(answer['product']['id'], 'P-102')
                self.assertEqual(post('/api/chat', {'conversation_id': cid, 'text': 'Đơn này?'}, token='b'*40)[0], 404)
                self.assertEqual(post('/api/conversations', {'customer_id': 'C-002'})[0], 400)
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
