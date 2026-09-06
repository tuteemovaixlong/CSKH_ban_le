import hashlib
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from retailops_api import ApiError, Application, BusinessStore, Server


class BusinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = BusinessStore(Path(self.temp.name) / 'business.sqlite3')
        self.store.seed()

    def proposal(self, customer='C-001', oid='O-101', version=1, reason='ordered_by_mistake'):
        return self.store.propose(customer, {'order_id': oid, 'order_version': version, 'cancel_reason': reason})

    def assert_error(self, code, call):
        with self.assertRaises(ApiError) as ctx:
            call()
        self.assertEqual(ctx.exception.code, code)

    def test_lookup_is_scoped_to_owner(self):
        self.assertEqual([r['id'] for r in self.store.orders('C-001')], ['O-101', 'O-102'])
        self.assert_error('order_not_found', lambda: self.store.lookup('C-001', 'O-202'))
        self.assert_error('order_not_found', lambda: self.proposal(oid='O-202'))

    def test_proposal_does_not_cancel(self):
        self.proposal()
        self.assertEqual(self.store.lookup('C-001', 'O-101')['status'], 'pending')

    def test_rejects_delivered_stale_and_invalid_reason(self):
        for code, args in [('not_cancellable', {'oid': 'O-102'}), ('stale_order', {'version': 0}),
                           ('invalid_proposal', {'reason': 'shipping_too_expensive'}), ('invalid_proposal', {'reason': None})]:
            with self.subTest(code=code, args=args):
                self.assert_error(code, lambda: self.proposal(**args))

    def test_confirmation_must_be_explicit_and_owned(self):
        pid = self.proposal()['proposal_id']
        self.assert_error('confirmation_required', lambda: self.store.confirm('C-001', pid, {'confirmed': 'true'}, 'a'*32))
        self.assert_error('idempotency_required', lambda: self.store.confirm('C-001', pid, {'confirmed': True}, None))
        self.assert_error('proposal_not_found', lambda: self.store.confirm('C-002', pid, {'confirmed': True}, 'a'*32))
        self.assert_error('invalid_fields', lambda: self.store.confirm('C-001', pid, {'confirmed': True, 'cancel_reason': 'no_longer_needed'}, 'a'*32))

    def test_atomic_confirmation_and_replay_after_restart(self):
        pid = self.proposal()['proposal_id']
        result = self.store.confirm('C-001', pid, {'confirmed': True}, 'a'*32)
        self.assertEqual(result['order']['status'], 'cancelled')
        reopened = BusinessStore(self.store.path)
        reopened.seed()
        replay = reopened.confirm('C-001', pid, {'confirmed': True}, 'a'*32)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['order']['version'], 2)
        self.assertEqual(len([e for e in reopened.events('C-001') if e['kind'] == 'order_cancelled']), 1)
        self.assert_error('already_confirmed', lambda: reopened.confirm('C-001', pid, {'confirmed': True}, 'b'*32))

    def test_concurrent_double_click_executes_once(self):
        pid = self.proposal()['proposal_id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.store.confirm('C-001', pid, {'confirmed': True}, 'a'*32), range(2)))
        self.assertEqual(sorted(r['replayed'] for r in results), [False, True])
        self.assertEqual(len([e for e in self.store.events('C-001') if e['kind'] == 'order_cancelled']), 1)

    def test_rechecks_order_at_confirmation(self):
        pid = self.proposal()['proposal_id']
        with self.store.connection(write=True) as db:
            db.execute("UPDATE orders SET status='delivered',version=2 WHERE id='O-101'")
        self.assert_error('stale_order', lambda: self.store.confirm('C-001', pid, {'confirmed': True}, 'a'*32))
        self.assertEqual(self.store.lookup('C-001', 'O-101')['status'], 'delivered')

    def test_expired_and_dismissed_proposals_cannot_execute(self):
        for expired in (True, False):
            pid = self.proposal()['proposal_id']
            if expired:
                with self.store.connection(write=True) as db:
                    db.execute('UPDATE proposals SET expires_at=? WHERE id=?', (time.time()-1, pid))
            else:
                self.store.dismiss('C-001', pid)
            self.assert_error('inactive_proposal', lambda: self.store.confirm('C-001', pid, {'confirmed': True}, 'a'*32))

    def test_distinct_proposals_cannot_cancel_same_order_twice(self):
        first, second = self.proposal(), self.proposal()
        self.store.confirm('C-001', first['proposal_id'], {'confirmed': True}, 'a'*32)
        self.assert_error('stale_order', lambda: self.store.confirm('C-001', second['proposal_id'], {'confirmed': True}, 'b'*32))

    def test_idempotency_key_cannot_be_reused_for_another_order(self):
        with self.store.connection(write=True) as db:
            db.execute("INSERT INTO orders(id,customer_id,name,variant,amount,status) VALUES ('O-103','C-001','Test','M',100,'pending')")
        first, second = self.proposal(), self.proposal(oid='O-103')
        self.store.confirm('C-001', first['proposal_id'], {'confirmed': True}, 'a'*32)
        self.assert_error('idempotency_conflict', lambda: self.store.confirm('C-001', second['proposal_id'], {'confirmed': True}, 'a'*32))

    def test_model_hallucinated_reason_never_creates_a_proposal(self):
        app = Application(self.store, {}, lambda text: {'valid': True, 'decision': {
            'action': 'cancel_order', 'order_id': 'O-101', 'cancel_reason': 'no_longer_needed'}})
        result = app.chat('C-001', {'text': 'Cancel O-101 because shipping is too expensive.'})
        self.assertEqual(result['action'], 'choose_cancel_reason')
        self.assertNotIn('reason', result)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM proposals').fetchone()[0], 0)
        self.assertEqual(self.store.lookup('C-001', 'O-101')['status'], 'pending')

    def test_model_cannot_invent_order_or_access_other_owner(self):
        app = Application(self.store, {}, lambda text: {'valid': True, 'decision': {
            'action': 'lookup_order', 'order_id': 'O-202', 'cancel_reason': None}})
        self.assert_error('ungrounded_order', lambda: app.chat('C-001', {'text': 'Show my order'}))
        self.assert_error('order_not_found', lambda: app.chat('C-001', {'text': 'Show O-202'}))

    def test_invalid_model_and_outage_leave_orders_unchanged(self):
        app = Application(self.store, {}, lambda text: {'valid': False, 'raw_output': 'invalid'})
        self.assertEqual(app.chat('C-001', {'text': 'Hủy O-101'})['action'], 'clarify')
        app.infer = None
        self.assert_error('model_offline', lambda: app.chat('C-001', {'text': 'Hủy O-101'}))
        def fail(text):
            raise RuntimeError('upstream body should not be returned')
        app.infer = fail
        self.assert_error('model_unavailable', lambda: app.chat('C-001', {'text': 'Hủy O-101'}))
        self.assertEqual(self.store.lookup('C-001', 'O-101')['status'], 'pending')


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.token = 't'*40
        self.store = BusinessStore(Path(self.temp.name) / 'business.sqlite3')
        self.store.seed()
        app = Application(self.store, {hashlib.sha256(self.token.encode()).hexdigest(): 'C-001'})
        self.server = Server(('127.0.0.1', 0), app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, body=None, headers=None, auth=True):
        h = {'Authorization': 'Bearer ' + self.token} if auth else {}
        if body is not None:
            h['Content-Type'] = 'application/json'
        h.update(headers or {})
        request = urllib.request.Request(self.url + path, headers=h, data=None if body is None else json.dumps(body).encode())
        try:
            response = self.http.open(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            return response.status, json.loads(raw) if response.headers.get_content_type() == 'application/json' else raw

    def test_auth_health_and_assets(self):
        self.assertEqual(self.request('/healthz', auth=False)[0], 200)
        self.assertEqual(self.request('/api/orders', auth=False)[0], 401)
        self.assertEqual(self.request('/api/orders', headers={'Authorization': 'Bearer incorrect'})[0], 401)
        self.assertEqual(self.request('/api/orders')[0], 200)
        self.assertIn(b'login-form', self.request('/', auth=False)[1])
        self.assertEqual(self.request('/../retailops_api.py', auth=False)[0], 404)
        self.assertEqual(self.request('/api/orders', headers={'Host': 'evil.example'})[0], 403)

    def test_http_confirmation_and_owner_contract(self):
        self.assertEqual(self.request('/api/orders/O-202')[0], 404)
        status, proposal = self.request('/api/cancellation-proposals', {'order_id': 'O-101', 'order_version': 1, 'cancel_reason': 'ordered_by_mistake'})
        self.assertEqual(status, 201)
        path = '/api/cancellation-proposals/' + proposal['proposal_id'] + '/confirm'
        self.assertEqual(self.request(path, {'confirmed': True})[0], 400)
        status, result = self.request(path, {'confirmed': True}, {'Idempotency-Key': 'a'*32})
        self.assertEqual(status, 200)
        self.assertEqual(result['order']['status'], 'cancelled')
        self.assertTrue(self.request(path, {'confirmed': True}, {'Idempotency-Key': 'a'*32})[1]['replayed'])

    def test_json_origin_and_offline_model(self):
        self.assertEqual(self.request('/api/chat', {'text': 'hello'}, {'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('/api/chat', {'text': 'hello'}, {'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.request('/api/chat', {'text': 'x'*17000})[0], 413)
        self.assertEqual(self.request('/api/chat', {'text': 'hello'})[0], 503)
        self.assertEqual(self.request('/api/chat', {'text': 'hello', 'customer_id': 'C-002'})[0], 400)


if __name__ == '__main__':
    unittest.main()
