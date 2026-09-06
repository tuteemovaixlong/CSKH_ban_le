"""System boundaries and startup contracts; temporary data, no external inference."""
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from retailops.bootstrap import build_private_app, build_public_app
from retailops.business.store import BusinessStore
from retailops.config import Settings
from retailops.core import ApiError, ROOT
from retailops.http.public import PublicWeb
from retailops.identity.contracts import SessionBinding
from retailops.models import build_gateways

INVITE = 'fixture_invite_' + 'a'*40
INFERENCE = 'fixture_inference_' + 'b'*40
API_KEY = 'fixture_api_' + 'c'*40
ORIGIN = 'https://retailops.example.com'


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)/'data'
        self.env = {'RETAILOPS_PUBLIC_ORIGIN': ORIGIN, 'RETAILOPS_PUBLIC_INVITE_TOKEN': INVITE,
                    'RETAILOPS_DEMO_TOKEN': INVITE, 'RETAILOPS_OUTPUT': str(self.output)}

    def request(self, web, path):
        env = {'REQUEST_METHOD': 'GET', 'PATH_INFO': path, 'HTTP_HOST': 'retailops.example.com',
               'HTTP_COOKIE': 'fixture-cookie', 'QUERY_STRING': '', 'wsgi.input': io.BytesIO()}
        captured = {}
        def start(status, headers):
            captured.update(status=int(status.split()[0]))
        result = json.loads(b''.join(web(env, start)))
        return captured['status'], result

    def test_legacy_api_imports_preserve_exception_and_store_identity(self):
        from retailops_api import ApiError as LegacyError, BusinessStore as LegacyStore
        from retailops_public import GuestSessions as LegacySessions
        from retailops.identity.demo import GuestSessions
        self.assertIs(LegacyError, ApiError)
        self.assertIs(LegacyStore, BusinessStore)
        self.assertIs(LegacySessions, GuestSessions)

    def test_business_transaction_runs_without_http_identity_or_model_modules(self):
        script = '''
import importlib.abc, pathlib, sys, tempfile
class BlockAdapters(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = ('retailops.http', 'retailops.identity', 'retailops.models', 'retailops.bootstrap',
                   'retailops_agent', 'retailops_baseline', 'retailops_providers', 'retailops_tools', 'waitress')
        if any(fullname == name or fullname.startswith(name+'.') for name in blocked):
            raise AssertionError('Business repository depends on an outer adapter: '+fullname)
sys.meta_path.insert(0, BlockAdapters())
from retailops.business.store import BusinessStore
with tempfile.TemporaryDirectory() as directory:
    store = BusinessStore(pathlib.Path(directory)/'business.sqlite3')
    assert store.orders('C-001') == []
    store.seed()
    proposal = store.propose('C-001', {'order_id':'O-101', 'order_version':1, 'cancel_reason':'ordered_by_mistake'})
    assert store.lookup('C-001','O-101')['status'] == 'pending'
    assert store.confirm('C-001',proposal['proposal_id'],{'confirmed':True},'x'*32)['order']['status'] == 'cancelled'
print('BUSINESS_BOUNDARY_OK')
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('BUSINESS_BOUNDARY_OK', result.stdout)

    def test_invalid_mode_or_flags_fail_before_any_data_is_created(self):
        for changes in ({'RETAILOPS_DATA_MODE': 'production'}, {'RETAILOPS_API_ENABLED': 'treu'},
                        {'RETAILOPS_PUBLIC_CUSTOM_ENABLED': '1'}, {'RETAILOPS_API_DAILY_TURN_LIMIT': '0'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                build_public_app(Settings.from_environment('public', {**self.env, **changes}))
        self.assertFalse(self.output.exists())

    def test_bad_enabled_provider_is_rejected_before_data_creation(self):
        for changes in ({'RETAILOPS_API_ENABLED': 'true', 'OPENROUTER_API_KEY': 'missing'},
                        {'RETAILOPS_PUBLIC_CUSTOM_ENABLED': 'true', 'RETAILOPS_MODEL_URL': 'http://not-https'}):
            settings = Settings.from_environment('public', {**self.env, **changes})
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                build_public_app(settings)
        self.assertFalse(self.output.exists())

    def test_disabled_colab_is_not_parsed_or_contacted_by_public_start(self):
        settings = Settings.from_environment('public', {**self.env, 'RETAILOPS_MODEL_ENABLED': 'true',
                                                     'RETAILOPS_MODEL_URL': 'stale-value'})
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Unexpected network request')):
            app = build_public_app(settings)
        self.assertIsNone(app.sessions.infer)
        self.assertIsNone(app.sessions.api_infer)
        self.assertEqual(self.request(app, '/healthz')[0], 200)

    def test_configured_gateways_do_not_probe_or_leak_secrets(self):
        settings = Settings.from_environment('public', {**self.env,
            'RETAILOPS_PUBLIC_CUSTOM_ENABLED': 'true', 'RETAILOPS_MODEL_URL': 'https://model.example.com',
            'RETAILOPS_ALLOWED_HOST': 'model.example.com', 'RETAILOPS_INFERENCE_TOKEN': INFERENCE,
            'RETAILOPS_API_ENABLED': 'true', 'OPENROUTER_API_KEY': API_KEY})
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Unexpected inference')):
            gateways = build_gateways(settings)
        self.assertIsNotNone(gateways.custom)
        self.assertIsNotNone(gateways.api)
        displayed = repr(settings) + repr(gateways) + json.dumps(settings.summary())
        for secret in (INVITE, INFERENCE, API_KEY):
            self.assertNotIn(secret, displayed)
        self.assertFalse(self.output.exists())

    def test_cli_check_config_is_redacted_and_does_not_create_databases(self):
        env = {**os.environ, **self.env, 'RETAILOPS_API_ENABLED': 'false',
               'RETAILOPS_PUBLIC_CUSTOM_ENABLED': 'false', 'RETAILOPS_DATA_MODE': 'synthetic-demo',
               'RETAILOPS_API_DAILY_TURN_LIMIT': '20',
               'RETAILOPS_INFERENCE_TOKEN': INFERENCE, 'OPENROUTER_API_KEY': API_KEY}
        result = subprocess.run([sys.executable, '-m', 'retailops', 'check-config'], cwd=ROOT,
                                env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['result'], 'CONFIG_VALID')
        self.assertFalse(data['connectivity_checked'])
        for secret in (INVITE, INFERENCE, API_KEY):
            self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_transport_uses_session_identity_instead_of_fixed_demo_customer(self):
        from retailops.business.application import Application
        store = BusinessStore(self.output/'binding.sqlite3'); store.seed()
        application = Application(store, {})
        class CustomerTwoSessions:
            @contextmanager
            def resolve(self, header):
                yield SessionBinding(application, customer_id='C-002', workspace_id='test-workspace')
            def metadata(self):
                return {'session_scope':'binding-fixture'}
        web = PublicWeb(ORIGIN, CustomerTwoSessions())
        status, result = self.request(web, '/api/orders/O-202')
        self.assertEqual(status, 200)
        self.assertEqual(result['order']['customer_id'], 'C-002')
        self.assertEqual(self.request(web, '/api/orders/O-101')[0], 404)
        self.assertEqual(self.request(web, '/api/session')[1]['customer_id'], 'C-002')

    def test_private_restart_preserves_business_state_and_public_logout_cannot_remove_it(self):
        private_settings = Settings.from_environment('private', self.env)
        app = build_private_app(private_settings)
        self.assertEqual(app.authenticate('Bearer '+INVITE), 'C-001')
        proposal = app.store.propose('C-001', {'order_id':'O-101', 'order_version':1, 'cancel_reason':'ordered_by_mistake'})
        app.store.confirm('C-001', proposal['proposal_id'], {'confirmed':True}, 'z'*32)
        public = build_public_app(Settings.from_environment('public', self.env))
        secret = public.sessions.login(INVITE)
        cookie = public.sessions.cookie_name+'='+secret
        with public.sessions.resolve(cookie) as binding:
            self.assertEqual(binding.customer_id, 'C-001')
            self.assertEqual(binding.workspace_id, hashlib.sha256(secret.encode()).hexdigest())
            self.assertEqual(binding.application.store.lookup('C-001','O-101')['status'], 'pending')
        public.sessions.logout(cookie)
        self.assertTrue((self.output/'business.sqlite3').exists())
        reopened = build_private_app(private_settings)
        self.assertEqual(reopened.store.lookup('C-001','O-101')['status'], 'cancelled')
        self.assertTrue(reopened.store.confirm('C-001',proposal['proposal_id'],{'confirmed':True},'z'*32)['replayed'])

    def test_wrong_interface_cannot_reuse_other_interfaces_auth_configuration(self):
        public = Settings.from_environment('public', self.env)
        private = Settings.from_environment('private', self.env)
        with self.assertRaises(ValueError):
            build_private_app(public)
        with self.assertRaises(ValueError):
            build_public_app(private)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
