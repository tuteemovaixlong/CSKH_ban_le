"""HTTPS-facing contracts; no certificate issuance, external API or GPU calls."""
import hashlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from retailops_api import BusinessStore
from retailops_public import COOKIE, GuestSessions, PublicWeb, create_application, public_origin

INVITE = 'fixture_invite_' + 'a' * 40
ORIGIN = 'https://retailops.example.com'


class ModelFixture:
    model = 'fixture-api'

    def inspect(self):
        return {'name': self.model, 'provider': 'openrouter', 'digest': None}

    def chat(self, messages, allow_tools, timeout):
        return {'message': {'role': 'assistant', 'content': 'Fixture reply'}, 'eval_count': 3, 'prompt_eval_count': 10}


class PublicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'public-guests'
        self.sessions = GuestSessions(self.directory, INVITE, api_infer=ModelFixture(), api_daily_limit=1)
        self.web = PublicWeb(ORIGIN, self.sessions)

    def request(self, path, body=None, cookie='', **overrides):
        raw = json.dumps(body).encode() if body is not None else b''
        env = {'REQUEST_METHOD': 'GET' if body is None else 'POST', 'PATH_INFO': path, 'QUERY_STRING': '',
               'HTTP_HOST': 'retailops.example.com', 'HTTP_ORIGIN': ORIGIN, 'HTTP_COOKIE': cookie,
               'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(raw)), 'wsgi.input': io.BytesIO(raw)}
        env.update(overrides)
        captured = {}
        def start(status, headers):
            captured.update(status=int(status.split()[0]), headers=dict(headers))
        data = b''.join(self.web(env, start))
        if captured['headers']['Content-Type'].startswith('application/json'):
            data = json.loads(data)
        return captured['status'], data, captured['headers']

    def login(self):
        status, body, headers = self.request('/api/login', {'token': INVITE})
        self.assertEqual(status, 200)
        for flag in ('Secure', 'HttpOnly', 'SameSite=Strict', 'Path=/', 'Max-Age=28800'):
            self.assertIn(flag, headers['Set-Cookie'])
        self.assertNotIn(INVITE, json.dumps(body))
        return headers['Set-Cookie'].split(';')[0]

    def test_public_assets_health_and_no_private_bearer_access(self):
        status, data, headers = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn(b'data-auth="cookie"', data)
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(self.request('/healthz')[1]['hosting'], 'public-https')
        self.assertEqual(self.request('/api/orders', HTTP_AUTHORIZATION='Bearer '+INVITE)[0], 401)
        self.assertEqual(self.request('/../api.env')[0], 404)
        self.assertEqual(self.request('/api/orders', QUERY_STRING='token='+INVITE)[0], 400)

    def test_exact_host_origin_and_body_limits(self):
        cookie = self.login()
        for host in ('evil.example', 'localhost:8080', 'retailops.example.com.evil', 'retailops.example.com:443'):
            self.assertEqual(self.request('/api/orders', cookie=cookie, HTTP_HOST=host,
                                         HTTP_X_FORWARDED_HOST='retailops.example.com')[0], 403)
        for origin in ('http://retailops.example.com', 'https://evil.example', '', 'null'):
            self.assertEqual(self.request('/api/conversations', {}, cookie, HTTP_ORIGIN=origin)[0], 403)
        self.assertEqual(self.request('/api/login', {'token': INVITE}, CONTENT_TYPE='text/plain')[0], 415)
        self.assertEqual(self.request('/api/login', {'token': 'x'*17000})[0], 413)
        self.assertEqual(self.request('/api/login', {'token': INVITE}, CONTENT_LENGTH='-1')[0], 400)
        self.assertEqual(self.request('/api/login', {'token': INVITE}, CONTENT_LENGTH='300')[0], 400)
        self.assertEqual(self.request('/healthz', REQUEST_METHOD='DELETE')[0], 405)
        self.assertEqual(self.request('/api/login', {'token': INVITE, 'customer_id': 'C-002'})[0], 400)

    def test_cancellation_guest_isolation_and_restart(self):
        # Existing private owner cancellation remains private and untouched.
        owner = BusinessStore(Path(self.temp.name) / 'business.sqlite3'); owner.seed()
        owner_proposal = owner.propose('C-001', {'order_id': 'O-101', 'order_version': 1, 'cancel_reason': 'no_longer_needed'})
        owner.confirm('C-001', owner_proposal['proposal_id'], {'confirmed': True}, 'o'*32)
        alice, bob = self.login(), self.login()
        status, proposal, _ = self.request('/api/cancellation-proposals',
            {'order_id': 'O-101', 'order_version': 1, 'cancel_reason': 'ordered_by_mistake'}, alice)
        self.assertEqual(status, 201)
        endpoint = '/api/cancellation-proposals/' + proposal['proposal_id'] + '/confirm'
        self.assertEqual(self.request(endpoint, {'confirmed': True}, bob, HTTP_IDEMPOTENCY_KEY='b'*32)[0], 404)
        self.assertEqual(self.request(endpoint, {'confirmed': False}, alice, HTTP_IDEMPOTENCY_KEY='a'*32)[0], 400)
        self.assertEqual(self.request(endpoint, {'confirmed': True}, alice, HTTP_IDEMPOTENCY_KEY='a'*32)[0], 200)
        self.web = PublicWeb(ORIGIN, GuestSessions(self.directory, INVITE))
        self.assertEqual(self.request('/api/orders/O-101', cookie=alice)[1]['order']['status'], 'cancelled')
        self.assertEqual(self.request('/api/orders/O-101', cookie=bob)[1]['order']['status'], 'pending')
        self.assertEqual(self.request('/api/orders/O-202', cookie=alice)[0], 404)
        bob_events = self.request('/api/events', cookie=bob)[1]['events']
        self.assertFalse(any(e['kind'] == 'order_cancelled' for e in bob_events))
        self.assertEqual(owner.lookup('C-001', 'O-101')['cancel_reason'], 'no_longer_needed')

    def test_api_default_shared_quota_and_conversation_isolation(self):
        alice, bob = self.login(), self.login()
        self.assertEqual(self.request('/api/providers', cookie=alice)[1]['default_provider'], 'api')
        first = self.request('/api/conversations', {}, alice)[1]['conversation_id']
        second = self.request('/api/conversations', {}, bob)[1]['conversation_id']
        body = {'text': 'hello', 'conversation_id': first, 'request_id': 'a'*32}
        self.assertEqual(self.request('/api/chat', body, bob)[0], 404)
        self.assertEqual(self.request('/api/chat', body, alice)[0], 200)
        self.assertTrue(self.request('/api/chat', body, alice)[1]['replayed'])
        self.web = PublicWeb(ORIGIN, GuestSessions(self.directory, INVITE, api_infer=ModelFixture(), api_daily_limit=1))
        status, result, _ = self.request('/api/chat', {**body, 'conversation_id': second}, bob)
        self.assertEqual(status, 429); self.assertEqual(result['error'], 'api_daily_limit')

    def test_logout_expiry_rotation_and_capacity(self):
        alice = self.login()
        self.sessions.capacity = 1
        self.assertEqual(self.request('/api/login', {'token': INVITE})[0], 429)
        status, _, headers = self.request('/api/logout', {}, alice)
        self.assertEqual(status, 200); self.assertIn('Max-Age=0', headers['Set-Cookie'])
        self.assertEqual(self.request('/api/orders', cookie=alice)[0], 401)
        bob = self.login()
        self.assertEqual(self.request('/api/orders', cookie=bob)[0], 200)
        with self.sessions.control.connection(write=True) as db:
            db.execute('UPDATE guest_sessions SET expires_at=0')
        self.assertEqual(self.request('/api/orders', cookie=bob)[0], 401)
        charlie = self.login()
        self.web = PublicWeb(ORIGIN, GuestSessions(self.directory, 'new_invite_'+'c'*40))
        self.assertEqual(self.request('/api/orders', cookie=charlie)[0], 401)
        self.assertEqual(self.request('/api/login', {'token': INVITE})[0], 401)

    def test_login_throttle_persists_across_restart(self):
        for _ in range(15):
            self.assertEqual(self.request('/api/login', {'token': 'incorrect'})[0], 401)
        self.web = PublicWeb(ORIGIN, GuestSessions(self.directory, INVITE))
        self.assertEqual(self.request('/api/login', {'token': INVITE})[0], 429)

    def test_no_colab_dependency_on_public_start_and_bad_origin_rejected(self):
        for value in ('http://retailops.example.com', ORIGIN+'/', ORIGIN+':443', 'https://u:p@retailops.example.com',
                      'https://retailops.example.com\nother', 'https://*.example.com', 'https://example.com?x=1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                public_origin(value)
        with patch.dict(os.environ, {'RETAILOPS_PUBLIC_ORIGIN': ORIGIN, 'RETAILOPS_PUBLIC_INVITE_TOKEN': INVITE,
                                    'RETAILOPS_OUTPUT': self.temp.name, 'RETAILOPS_MODEL_ENABLED': 'true',
                                    'RETAILOPS_MODEL_URL': 'stale-colab-value'}, clear=True):
            app = create_application()
        self.assertIsNone(app.sessions.infer)
        self.assertIsNone(app.sessions.api_infer)

    def test_waitress_real_http_when_installed(self):
        try:
            from waitress.server import create_server
        except ImportError:
            self.skipTest('Waitress is required in Docker/CI; optional for the embedded Colab source tests.')
        server = create_server(self.web, host='127.0.0.1', port=0, threads=2)
        thread = threading.Thread(target=server.run, daemon=True); thread.start()
        try:
            http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            base = 'http://127.0.0.1:' + str(server.effective_port)
            request = urllib.request.Request(base+'/api/login', data=json.dumps({'token': INVITE}).encode(),
                headers={'Host': 'retailops.example.com', 'Origin': ORIGIN, 'Content-Type': 'application/json'})
            with http.open(request, timeout=3) as response:
                self.assertEqual(response.status, 200)
                cookie = response.headers['Set-Cookie'].split(';')[0]
            request = urllib.request.Request(base+'/api/orders', headers={'Host': 'retailops.example.com', 'Cookie': cookie})
            with http.open(request, timeout=3) as response:
                self.assertEqual(len(json.load(response)['orders']), 2)
        finally:
            server.close(); server.task_dispatcher.shutdown(); thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
