"""Durable identity and tenant isolation through actual HTTP/business boundaries."""
import hashlib
import io
import json
import os
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from retailops.bootstrap import build_public_app
from retailops.config import Settings
from retailops.core import ApiError, ROOT
from retailops.http.public import PublicWeb
from retailops.identity.cli import issue_credential
from retailops.identity.persistent import PersistentSessions
from retailops.identity.store import IdentityStore

ORIGIN = 'https://retailops.example.com'
PROPOSAL = {'order_id': 'O-101', 'order_version': 1, 'cancel_reason': 'ordered_by_mistake'}


class ModelFixture:
    model = 'fixture-api'

    def inspect(self):
        return {'name': self.model, 'provider': 'openrouter', 'digest': None}

    def chat(self, messages, allow_tools, timeout):
        return {'message': {'role': 'assistant', 'content': 'Fixture reply'}, 'eval_count': 3, 'prompt_eval_count': 10}


class PersistentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)/'persistent'
        self.restart()
        self.sessions.provision_tenant('shop-a', 'Cửa hàng A', seed_demo=True)
        self.sessions.provision_tenant('shop-b', 'Cửa hàng B', seed_demo=True)
        self.alice = self.member('alice', 'shop-a', 'C-001')
        self.bob = self.member('bob', 'shop-a', 'C-002')
        self.other = self.member('other', 'shop-b', 'C-001')
        self.viewer = self.member('viewer', 'shop-a', 'C-001', 'viewer')

    def restart(self):
        self.sessions = PersistentSessions(self.directory, api_infer=ModelFixture(), api_daily_limit=1)
        self.web = PublicWeb(ORIGIN, self.sessions)

    def member(self, principal, tenant, customer, role='customer'):
        mid = self.sessions.create_member(tenant, principal, principal.title(), customer, role)
        token = secrets.token_urlsafe(32)
        self.sessions.control.register_credential(mid, token)
        return mid, token

    def request(self, path, body=None, cookie='', **overrides):
        raw = json.dumps(body).encode() if body is not None else b''
        env = {'REQUEST_METHOD': 'GET' if body is None else 'POST', 'PATH_INFO': path, 'QUERY_STRING': '',
               'HTTP_HOST': 'retailops.example.com', 'HTTP_ORIGIN': ORIGIN, 'HTTP_COOKIE': cookie,
               'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(raw)), 'wsgi.input': io.BytesIO(raw)}
        env.update(overrides)
        captured = {}
        def start(status, headers):
            captured.update(status=int(status.split()[0]), headers=dict(headers))
        body = b''.join(self.web(env, start))
        if captured['headers']['Content-Type'].startswith('application/json'):
            body = json.loads(body)
        return captured['status'], body, captured['headers']

    def login(self, member):
        status, body, headers = self.request('/api/login', {'token': member[1]})
        self.assertEqual(status, 200, body)
        for flag in ('Secure', 'HttpOnly', 'SameSite=Strict', 'Path=/', 'Max-Age=28800'):
            self.assertIn(flag, headers['Set-Cookie'])
        return headers['Set-Cookie'].split(';')[0]

    def cancel(self, cookie):
        status, proposal, _ = self.request('/api/cancellation-proposals', PROPOSAL, cookie)
        self.assertEqual(status, 201, proposal)
        endpoint = '/api/cancellation-proposals/'+proposal['proposal_id']+'/confirm'
        status, result, _ = self.request(endpoint, {'confirmed': True}, cookie, HTTP_IDEMPOTENCY_KEY='confirm-a'*4)
        self.assertEqual(status, 200, result)
        return endpoint

    def test_logout_relogin_restart_keep_order_audit_and_idempotency(self):
        alice = self.login(self.alice)
        endpoint = self.cancel(alice)
        self.assertEqual(self.request('/api/logout', {}, alice)[0], 200)
        self.assertEqual(self.request('/api/orders', cookie=alice)[0], 401)
        self.restart()
        alice = self.login(self.alice)
        result = self.request('/api/orders/O-101', cookie=alice)[1]['order']
        self.assertEqual((result['status'], result['version']), ('cancelled', 2))
        self.assertTrue(self.request(endpoint, {'confirmed': True}, alice, HTTP_IDEMPOTENCY_KEY='confirm-a'*4)[1]['replayed'])
        events = self.request('/api/events', cookie=alice)[1]['events']
        self.assertEqual(sum(e['kind'] == 'order_cancelled' for e in events), 1)

    def test_expiry_and_purge_never_delete_business_databases(self):
        alice = self.login(self.alice)
        self.cancel(alice)
        paths = sorted((self.directory/'tenants').glob('*.sqlite3'))
        with self.sessions.control.connection(write=True) as db:
            db.execute('UPDATE sessions SET expires_at=0')
        self.sessions.purge()
        self.assertEqual(self.request('/api/orders', cookie=alice)[0], 401)
        self.assertTrue(all(p.is_file() for p in paths))
        self.assertEqual(self.request('/api/orders/O-101', cookie=self.login(self.alice))[1]['order']['status'], 'cancelled')

    def test_tenant_customer_order_proposal_conversation_and_replay_isolation(self):
        alice, bob, other = [self.login(m) for m in (self.alice, self.bob, self.other)]
        self.assertEqual([o['id'] for o in self.request('/api/orders', cookie=bob)[1]['orders']], ['O-202'])
        self.assertEqual(self.request('/api/orders/O-101', cookie=bob)[0], 404)
        self.assertEqual(self.request('/api/orders/O-202', cookie=alice)[0], 404)
        proposal = self.request('/api/cancellation-proposals', PROPOSAL, alice)[1]
        conversation = self.request('/api/conversations', {}, alice)[1]['conversation_id']
        body = {'text': 'hello', 'conversation_id': conversation, 'request_id': 'chat-a'*4}
        self.assertEqual(self.request('/api/chat', body, alice)[0], 200)
        for stranger in (bob, other):
            self.assertEqual(self.request('/api/chat', body, stranger)[0], 404)
            self.assertEqual(self.request('/api/conversations/'+conversation+'/focus', {'order_id': 'O-101'}, stranger)[0], 404)
            for action, data in (('confirm', {'confirmed': True}), ('dismiss', {})):
                self.assertEqual(self.request('/api/cancellation-proposals/'+proposal['proposal_id']+'/'+action,
                                              data, stranger, HTTP_IDEMPOTENCY_KEY='isolation'*4)[0], 404)
        self.cancel(alice)
        self.assertEqual(self.request('/api/orders/O-101', cookie=other)[1]['order']['status'], 'pending')
        self.assertFalse(any(e['kind'] == 'order_cancelled' for e in self.request('/api/events', cookie=other)[1]['events']))

    def test_viewer_cannot_propose_confirm_dismiss_or_prepare_via_model(self):
        alice, viewer = self.login(self.alice), self.login(self.viewer)
        proposal = self.request('/api/cancellation-proposals', PROPOSAL, alice)[1]
        self.assertEqual(self.request('/api/cancellation-proposals', PROPOSAL, viewer)[0], 403)
        for action, data in (('confirm', {'confirmed': True}), ('dismiss', {})):
            self.assertEqual(self.request('/api/cancellation-proposals/'+proposal['proposal_id']+'/'+action,
                                          data, viewer, HTTP_IDEMPOTENCY_KEY='viewer'*4)[0], 403)
        def model_run(gateway, text, history, execute, identity, **options):
            self.assertEqual(execute('prepare_cancellation', {'order_id': 'O-101'})['error'], 'permission_denied')
            self.assertEqual(execute('get_order', {'order_id': 'O-101'})['order']['id'], 'O-101')
            return {'message': 'Read only.', 'trace': {}, 'messages': []}
        conversation = self.request('/api/conversations', {}, viewer)[1]['conversation_id']
        with patch('retailops.business.application.run_agent', side_effect=model_run):
            status, result, _ = self.request('/api/chat', {'text': 'cancel', 'conversation_id': conversation,
                                                         'request_id': 'viewer-chat'*3}, viewer)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['action'], 'reply')
        self.assertNotIn('order', result)
        self.assertEqual(self.request('/api/orders/O-101', cookie=viewer)[1]['order']['status'], 'pending')

    def test_role_change_credential_rotation_and_revocation_invalidate_cached_sessions(self):
        alice = self.login(self.alice)
        self.assertEqual(self.request('/api/session', cookie=alice)[1]['role'], 'customer')
        self.sessions.control.set_role(self.alice[0], 'viewer')
        self.assertEqual(self.request('/api/orders', cookie=alice)[0], 401)
        current = self.login(self.alice)
        self.assertEqual(self.request('/api/session', cookie=current)[1]['permissions'], ['orders:read'])
        replacement = secrets.token_urlsafe(32)
        self.sessions.control.register_credential(self.alice[0], replacement)
        self.assertEqual(self.request('/api/orders', cookie=current)[0], 401)
        self.assertEqual(self.request('/api/login', {'token': self.alice[1]})[0], 401)
        current = self.login((self.alice[0], replacement))
        self.sessions.control.revoke(self.alice[0])
        self.assertEqual(self.request('/api/orders', cookie=current)[0], 401)
        self.assertEqual(self.request('/api/login', {'token': replacement})[0], 401)
        self.assertEqual(len(self.sessions.business_store('shop-a').orders('C-001')), 2)

    def test_http_cannot_override_membership_and_cookie_is_separate_from_guest(self):
        alice = self.login(self.alice)
        for field, value in (('tenant_id', 'shop-b'), ('customer_id', 'C-002'), ('role', 'customer')):
            self.assertEqual(self.request('/api/login', {'token': self.alice[1], field: value})[0], 400)
        info = self.request('/api/session', cookie=alice)[1]
        self.assertEqual((info['tenant_id'], info['principal_id'], info['customer_id'], info['name']),
                         ('shop-a', 'alice', 'C-001', 'Alice'))
        self.assertEqual(info['session_scope'], 'persistent-account')
        self.assertIn(b'data-data-mode="persistent-demo"', self.request('/')[1])
        self.assertEqual(self.request('/healthz')[1]['data_mode'], 'persistent-demo')
        self.assertEqual(self.request('/api/orders', cookie=alice.replace('__Host-retailops_account', '__Host-retailops_guest'))[0], 401)
        self.assertEqual(self.request('/api/orders', cookie=alice, HTTP_HOST='evil.example.com')[0], 403)
        self.assertEqual(self.request('/api/logout', {}, alice, HTTP_ORIGIN='https://evil.example.com')[0], 403)

    def test_credentials_and_cookie_secrets_are_not_stored_in_control_database(self):
        cookie = self.login(self.alice).split('=', 1)[1]
        with self.sessions.control.connection() as db:
            dump = '\n'.join(db.iterdump())
        for token in (self.alice[1], cookie):
            self.assertNotIn(token, dump)
            self.assertIn(hashlib.sha256(token.encode()).hexdigest(), dump)

    def test_bad_login_throttle_and_global_api_limit_survive_restart(self):
        with patch('retailops.identity.store.time.time', return_value=1800000000):
            for _ in range(15):
                self.assertEqual(self.request('/api/login', {'token': 'wrong'})[0], 401)
            self.restart()
            self.assertEqual(self.request('/api/login', {'token': self.alice[1]})[0], 429)
        self.sessions.control.reserve_api_attempt(1)
        self.restart()
        with self.assertRaises(ApiError) as caught:
            self.sessions.control.reserve_api_attempt(1)
        self.assertEqual(caught.exception.code, 'api_daily_limit')

    def test_missing_tenant_database_is_not_recreated_even_for_cached_application(self):
        alice = self.login(self.alice)
        self.assertEqual(self.request('/api/orders', cookie=alice)[0], 200)
        path = self.sessions.business_store('shop-a').path
        path.rename(path.with_suffix('.held'))
        self.assertEqual(self.request('/api/orders', cookie=alice)[0], 503)
        self.assertFalse(path.exists())
        self.restart()
        self.assertEqual(self.request('/api/orders', cookie=alice)[0], 503)
        self.assertFalse(path.exists())

    def test_membership_requires_customer_and_storage_path_is_not_user_supplied(self):
        with self.assertRaises(ApiError):
            self.sessions.create_member('shop-a', 'unknown', 'Unknown', 'C-999')
        for value in ('../escape', '/tmp/escape', 'a/b'):
            with self.assertRaises(ApiError):
                self.sessions.provision_tenant(value, 'Invalid')
        path = self.sessions.business_store('shop-a').path
        self.assertEqual(path.parent, self.directory/'tenants')
        self.assertRegex(path.stem, r'^[a-f0-9]{32}$')
        self.assertEqual(self.sessions.provision_tenant('empty', 'Empty').orders('C-001'), [])

    def test_consistent_offline_copy_restores_identity_and_tenant_state(self):
        alice = self.login(self.alice)
        self.cancel(alice)
        # Simulates a stopped web process: no requests/provisioning run during this copy.
        restored = Path(self.temp.name)/'restored'
        shutil.copytree(self.directory, restored)
        self.directory = restored
        self.restart()
        self.assertEqual(self.request('/api/orders/O-101', cookie=self.login(self.alice))[1]['order']['status'], 'cancelled')
        with self.sessions.control.connection() as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        with self.sessions.business_store('shop-a').connection() as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_credential_file_rotation_is_private_and_existing_file_cannot_revoke(self):
        alice = self.login(self.alice)
        path = Path(self.temp.name)/'delivery.txt'
        path.write_text('existing')
        with self.assertRaises(FileExistsError):
            issue_credential(self.sessions.control, self.alice[0], path)
        self.assertEqual(path.read_text(), 'existing')
        self.assertEqual(self.request('/api/orders', cookie=alice)[0], 200)
        path.unlink()
        result = issue_credential(self.sessions.control, self.alice[0], path)
        token = path.read_text().strip()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertNotIn(token, json.dumps(result))
        self.assertEqual(self.request('/api/orders', cookie=alice)[0], 401)
        self.assertEqual(self.request('/api/login', {'token': token})[0], 200)
        failed_path = path.with_name('failed.txt')
        with self.assertRaises(ApiError):
            issue_credential(self.sessions.control, 'nonexistent', failed_path)
        self.assertFalse(failed_path.exists())

    def test_cli_provisions_accounts_without_models_and_never_prints_access_code(self):
        output = Path(self.temp.name)/'cli-data'
        def cli(*args):
            return subprocess.run([sys.executable, '-m', 'retailops', 'identity', '--output', str(output), *args],
                                  cwd=ROOT, text=True, capture_output=True, timeout=10)
        result = cli('init-tenant', '--tenant', 'demo', '--name', 'Demo', '--seed-demo')
        self.assertEqual(result.returncode, 0, result.stderr)
        result = cli('create-member', '--tenant', 'demo', '--principal', 'mai-anh', '--name', 'Mai Anh', '--customer', 'C-001')
        self.assertEqual(result.returncode, 0, result.stderr)
        mid = json.loads(result.stdout)['membership_id']
        path = Path(self.temp.name)/'code.txt'
        result = cli('issue-credential', '--membership', mid, '--credential-file', str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(path.read_text().strip(), result.stdout+result.stderr)
        self.assertEqual(cli('issue-credential', '--membership', mid, '--credential-file', str(path)).returncode, 2)
        self.assertEqual(cli('set-role', '--membership', mid, '--role', 'viewer').returncode, 0)
        self.assertEqual(cli('revoke', '--membership', mid).returncode, 0)

    def test_persistent_mode_requires_https_and_no_shared_invite(self):
        output = Path(self.temp.name)/'config-data'
        env = {'RETAILOPS_OUTPUT': str(output), 'RETAILOPS_DATA_MODE': 'persistent-demo',
               'RETAILOPS_PUBLIC_ORIGIN': ORIGIN}
        settings = Settings.from_environment('public', env)
        self.assertEqual(settings.access_token, '')
        self.assertFalse(output.exists())
        with self.assertRaises(ValueError):
            Settings.from_environment('private', env)
        with self.assertRaises(ValueError):
            build_public_app(Settings.from_environment('public', {**env, 'RETAILOPS_API_ENABLED': 'true'}))
        self.assertFalse(output.exists())
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Unexpected inference')):
            web = build_public_app(settings)
        self.assertIsInstance(web.sessions, PersistentSessions)
        with self.assertRaises(ApiError):
            web.sessions.login(self.alice[1])  # No implicit account/tenant seed.


if __name__ == '__main__':
    unittest.main()
