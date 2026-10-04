"""Unit tests for Google OAuth 2.0 (SSO) and Role-Based Identity."""
import json
import os
import unittest
from unittest.mock import patch, MagicMock

from retailops.http import auth_google
from retailops.http.public import PublicWeb
from retailops.business.permissions import ROLE_PERMISSIONS, STAFF, MANAGER


class GoogleAuthModuleTests(unittest.TestCase):
    def test_configured_check(self):
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "cid123", "GOOGLE_CLIENT_SECRET": "csec456"}):
            self.assertTrue(auth_google.is_google_auth_configured())

        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": ""}):
            self.assertFalse(auth_google.is_google_auth_configured())

    def test_state_lifecycle(self):
        nonce = "test_nonce_12345"
        state = auth_google.create_state(nonce)
        self.assertTrue(isinstance(state, str) and len(state) >= 20)
        # First verification succeeds with matching browser nonce
        self.assertTrue(auth_google.verify_and_consume_state(state, browser_nonce=nonce))
        # Second verification fails (single use / consumed)
        self.assertFalse(auth_google.verify_and_consume_state(state, browser_nonce=nonce))
        # Verification without nonce fails
        state_fresh = auth_google.create_state(nonce)
        self.assertFalse(auth_google.verify_and_consume_state(state_fresh))
        # Verification with mismatched nonce fails
        self.assertFalse(auth_google.verify_and_consume_state(state_fresh, browser_nonce="wrong_nonce"))
        # Non-existent state fails
        self.assertFalse(auth_google.verify_and_consume_state("bogus_token", browser_nonce=nonce))
        # Empty nonce in create_state raises ValueError
        with self.assertRaises(ValueError):
            auth_google.create_state("")

    def test_auth_url_construction(self):
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "my-client.apps.googleusercontent.com"}):
            url = auth_google.get_google_auth_url("https://retailops.example.com", "state_abc")
            self.assertIn("https://accounts.google.com/o/oauth2/v2/auth?", url)
            self.assertIn("client_id=my-client.apps.googleusercontent.com", url)
            self.assertIn("redirect_uri=https%3A%2F%2Fretailops.example.com%2Fauth%2Fgoogle%2Fcallback", url)
            self.assertIn("state=state_abc", url)
            self.assertIn("response_type=code", url)
            self.assertIn("scope=openid+email+profile", url)

    def test_smart_role_mapping(self):
        with patch.dict(os.environ, {
            "STAFF_EMAILS": "staff1@shop.com, cskh@retailops.vn",
            "MANAGER_EMAILS": "boss@shop.com, owner@gmail.com",
            "DEFAULT_ROLE": "customer"
        }):
            self.assertEqual(auth_google.resolve_role_from_email("boss@shop.com"), "manager")
            self.assertEqual(auth_google.resolve_role_from_email("OWNER@GMAIL.COM"), "manager")
            self.assertEqual(auth_google.resolve_role_from_email("cskh@retailops.vn"), "staff")
            self.assertEqual(auth_google.resolve_role_from_email("random_user@gmail.com"), "customer")

    def test_role_permissions_matrix(self):
        self.assertIn('staff', ROLE_PERMISSIONS)
        self.assertIn('manager', ROLE_PERMISSIONS)
        self.assertIn(STAFF, ROLE_PERMISSIONS['staff'])
        self.assertIn(MANAGER, ROLE_PERMISSIONS['manager'])
        self.assertNotIn(STAFF, ROLE_PERMISSIONS['customer'])
        self.assertNotIn(MANAGER, ROLE_PERMISSIONS['staff'])


class GoogleAuthHTTPRoutesTests(unittest.TestCase):
    def setUp(self):
        self.mock_sessions = MagicMock()
        self.mock_sessions.data_mode = 'persistent-demo'
        self.mock_sessions.cookie_name = '__Host-retailops_account'
        self.mock_sessions.session_seconds = 28800
        self.mock_sessions.metadata.return_value = {'storage_backend': 'sqlite'}
        self.web = PublicWeb('https://retailops.example.com', self.mock_sessions)

    def _call_wsgi(self, app, environ):
        response_headers = []
        status_code = [None]
        def start_response(status, headers):
            status_code[0] = int(status.split()[0])
            response_headers.extend(headers)
        body_iterable = app(environ, start_response)
        body = b"".join(body_iterable)
        headers_dict = dict(response_headers)
        json_body = json.loads(body.decode("utf-8")) if "application/json" in headers_dict.get("Content-Type", "") else body
        return status_code[0], json_body, response_headers

    def test_config_endpoint(self):
        env = {
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/auth/google/config',
            'HTTP_HOST': 'retailops.example.com',
        }
        status, body, mime, headers = self.web.route(env)
        self.assertEqual(status, 200)
        self.assertIn('configured', body)

    def test_login_endpoint_redirects_when_configured(self):
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": "sec"}):
            env = {
                'REQUEST_METHOD': 'GET',
                'PATH_INFO': '/auth/google/login',
                'HTTP_HOST': 'retailops.example.com',
            }
            status, body, mime, headers = self.web.route(env)
            self.assertEqual(status, 302)
            headers_dict = dict(headers)
            self.assertIn('Location', headers_dict)
            self.assertIn('accounts.google.com', headers_dict['Location'])

    def test_callback_fails_with_invalid_state(self):
        env = {
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/auth/google/callback',
            'QUERY_STRING': 'code=somecode&state=bad_state',
            'HTTP_HOST': 'retailops.example.com',
        }
        from retailops.core import ApiError
        with self.assertRaises(ApiError) as cm:
            self.web.route(env)
        self.assertEqual(cm.exception.status, 403)

    def test_callback_success_sets_session_cookie(self):
        # Create a valid state with browser nonce
        nonce = "success_nonce_cookie_123"
        valid_state = auth_google.create_state(nonce)
        self.mock_sessions.login_google.return_value = 'sec_' + 'A'*39

        with patch('retailops.http.auth_google.exchange_code_for_user_info') as mock_exchange:
            mock_exchange.return_value = {
                'email': 'maianh.cskh@gmail.com',
                'name': 'Mai Anh',
                'sub': 'google-12345'
            }
            env = {
                'REQUEST_METHOD': 'GET',
                'PATH_INFO': '/auth/google/callback',
                'QUERY_STRING': f'code=authcode123&state={valid_state}',
                'HTTP_HOST': 'retailops.example.com',
                'HTTP_COOKIE': f'retailops_oauth_transient={nonce}',
            }
            status, body, mime, headers = self.web.route(env)
            self.assertEqual(status, 302)
            headers_dict = dict(headers)
            self.assertEqual(headers_dict.get('Location'), '/')
            self.assertIn('Set-Cookie', headers_dict)
            self.assertIn('__Host-retailops_account=sec_', headers_dict['Set-Cookie'])
            self.mock_sessions.login_google.assert_called_once()

    def test_callback_legacy_unbound_state_rejected_403_via_wsgi(self):
        """B-01: Callback must reject any state not bound to browser nonce via PublicWeb.__call__."""
        # 1. Callback with no cookie at all
        nonce = "some_nonce_123"
        state = auth_google.create_state(nonce)
        env_no_cookie = {
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/auth/google/callback',
            'QUERY_STRING': f'code=code123&state={state}',
            'HTTP_HOST': 'retailops.example.com',
        }
        status, body, headers = self._call_wsgi(self.web, env_no_cookie)
        self.assertEqual(status, 403)
        self.assertEqual(body.get('error'), 'invalid_oauth_state')

        # 2. Callback with legacy 3-part state format (token.exp.sig)
        import time, secrets, hmac, hashlib
        from retailops.http.auth_google import _state_key
        token = secrets.token_urlsafe(24)
        exp = str(int(time.time() + 600))
        msg = f"{token}:{exp}".encode("utf-8")
        sig = hmac.new(_state_key(), msg, hashlib.sha256).hexdigest()[:24]
        legacy_state = f"{token}.{exp}.{sig}"

        env_legacy = {
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/auth/google/callback',
            'QUERY_STRING': f'code=code123&state={legacy_state}',
            'HTTP_HOST': 'retailops.example.com',
            'HTTP_COOKIE': 'retailops_oauth_transient=some_cookie',
        }
        status, body, headers = self._call_wsgi(self.web, env_legacy)
        self.assertEqual(status, 403)
        self.assertEqual(body.get('error'), 'invalid_oauth_state')

    def test_callback_exchange_error_returns_502_and_cleans_cookie_via_wsgi(self):
        """B-04: Upstream token exchange failure returns HTTP 502 oauth_exchange_failed and clears transient cookie."""
        nonce = "exchange_fail_nonce"
        state = auth_google.create_state(nonce)

        with patch('retailops.http.auth_google.exchange_code_for_user_info') as mock_exchange:
            mock_exchange.side_effect = ValueError("Google IDP token endpoint returned 500 Internal Server Error")
            env = {
                'REQUEST_METHOD': 'GET',
                'PATH_INFO': '/auth/google/callback',
                'QUERY_STRING': f'code=badcode&state={state}',
                'HTTP_HOST': 'retailops.example.com',
                'HTTP_COOKIE': f'retailops_oauth_transient={nonce}',
            }
            status, body, headers = self._call_wsgi(self.web, env)
            self.assertEqual(status, 502)
            self.assertEqual(body.get('error'), 'oauth_exchange_failed')
            # Verify Set-Cookie cleans up the transient cookie
            cleanup_cookies = [v for k, v in headers if k == 'Set-Cookie' and 'retailops_oauth_transient=' in v]
            self.assertTrue(len(cleanup_cookies) >= 1)
            self.assertIn('Max-Age=0', cleanup_cookies[0])

    def test_google_oauth_end_to_end_persistent_sessions(self):
        import tempfile
        from retailops.identity.persistent import PersistentSessions
        from retailops.http.public import PublicWeb

        with tempfile.TemporaryDirectory() as td:
            sessions = PersistentSessions(td)
            sessions.provision_tenant('T-001', 'Test Tenant', seed_demo=True)
            web = PublicWeb('https://retailops.example.com', sessions)

            nonce = "persistent_nonce_e2e"
            state = auth_google.create_state(nonce)
            with patch('retailops.http.auth_google.exchange_code_for_user_info') as mock_exchange:
                mock_exchange.return_value = {
                    'email': 'teemo.gamer@gmail.com',
                    'name': 'Teemo',
                    'sub': 'g-99999'
                }
                callback_env = {
                    'REQUEST_METHOD': 'GET',
                    'PATH_INFO': '/auth/google/callback',
                    'QUERY_STRING': f'code=code_xyz&state={state}',
                    'HTTP_HOST': 'retailops.example.com',
                    'HTTP_COOKIE': f'retailops_oauth_transient={nonce}',
                }
                status, body, mime, headers = web.route(callback_env)
                self.assertEqual(status, 302)
                headers_dict = dict(headers)
                self.assertEqual(headers_dict.get('Location'), '/')
                cookie_val = headers_dict.get('Set-Cookie', '').split(';')[0]
                self.assertTrue(cookie_val.startswith('__Host-retailops_account='))

                # Now verify /api/session succeeds with this cookie
                session_env = {
                    'REQUEST_METHOD': 'GET',
                    'PATH_INFO': '/api/session',
                    'HTTP_HOST': 'retailops.example.com',
                    'HTTP_COOKIE': cookie_val,
                }
                s_status, s_body, s_mime, s_headers = web.route(session_env)
                self.assertEqual(s_status, 200)
                self.assertEqual(s_body.get('name'), 'Teemo')
                self.assertEqual(s_body.get('role'), 'customer')

    def test_google_oauth_end_to_end_guest_sessions(self):
        import tempfile
        from retailops.identity.demo import GuestSessions
        from retailops.http.public import PublicWeb

        with tempfile.TemporaryDirectory() as td:
            sessions = GuestSessions(td, 'invite_fixture_123456789012345678901234567890')
            web = PublicWeb('https://retailops.example.com', sessions)

            nonce = "guest_nonce_e2e"
            state = auth_google.create_state(nonce)
            with patch('retailops.http.auth_google.exchange_code_for_user_info') as mock_exchange:
                mock_exchange.return_value = {
                    'email': 'guest.user@gmail.com',
                    'name': 'Guest User',
                    'sub': 'g-88888'
                }
                callback_env = {
                    'REQUEST_METHOD': 'GET',
                    'PATH_INFO': '/auth/google/callback',
                    'QUERY_STRING': f'code=code_abc&state={state}',
                    'HTTP_HOST': 'retailops.example.com',
                    'HTTP_COOKIE': f'retailops_oauth_transient={nonce}',
                }
                status, body, mime, headers = web.route(callback_env)
                self.assertEqual(status, 302)
                headers_dict = dict(headers)
                self.assertEqual(headers_dict.get('Location'), '/')
                cookie_val = headers_dict.get('Set-Cookie', '').split(';')[0]
                self.assertTrue(cookie_val.startswith('__Host-retailops_session='))

                session_env = {
                    'REQUEST_METHOD': 'GET',
                    'PATH_INFO': '/api/session',
                    'HTTP_HOST': 'retailops.example.com',
                    'HTTP_COOKIE': cookie_val,
                }
                s_status, s_body, s_mime, s_headers = web.route(session_env)
                self.assertEqual(s_status, 200)
                self.assertEqual(s_body.get('role'), 'customer')

    def test_oauth_csrf_state_binding(self):
        """Canonical test for SEC-01 / AC-13: OAuth state browser cookie binding, atomic consume, multi-tab safety."""
        from urllib.parse import parse_qs, urlsplit
        from retailops.core import ApiError

        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": "sec"}):
            # 1. Login sets transient cookie and binds nonce into state
            login_env = {
                'REQUEST_METHOD': 'GET',
                'PATH_INFO': '/auth/google/login',
                'HTTP_HOST': 'retailops.example.com',
            }
            status, _, _, headers = self.web.route(login_env)
            self.assertEqual(status, 302)
            headers_dict = dict(headers)
            set_cookie = headers_dict.get('Set-Cookie', '')
            self.assertIn('retailops_oauth_transient=', set_cookie)
            self.assertIn('Path=/auth/google', set_cookie)
            self.assertIn('Max-Age=600', set_cookie)

            # Extract nonce from cookie
            cookie_part = [p for p in headers if p[0] == 'Set-Cookie' and 'retailops_oauth_transient=' in p[1]][0][1]
            nonce_val = cookie_part.split(';')[0].split('=')[1]

            # Extract state from redirect location
            loc = headers_dict['Location']
            query = parse_qs(urlsplit(loc).query)
            state_val = query['state'][0]
            parts = state_val.split('.')
            self.assertEqual(len(parts), 4)

            # 2. Callback with matching cookie succeeds and deletes transient cookie
            self.mock_sessions.login_google.return_value = 'sec_' + 'K' * 39
            with patch('retailops.http.auth_google.exchange_code_for_user_info') as mock_exchange:
                mock_exchange.return_value = {
                    'email': 'valid.user@gmail.com',
                    'name': 'Valid User',
                    'sub': 'google-valid'
                }
                cb_env = {
                    'REQUEST_METHOD': 'GET',
                    'PATH_INFO': '/auth/google/callback',
                    'QUERY_STRING': f'code=code123&state={state_val}',
                    'HTTP_HOST': 'retailops.example.com',
                    'HTTP_COOKIE': f'retailops_oauth_transient={nonce_val}',
                }
                cb_status, _, _, cb_headers = self.web.route(cb_env)
                self.assertEqual(cb_status, 302)
                # Verify transient cookie cleanup header
                cleanup_cookies = [v for k, v in cb_headers if k == 'Set-Cookie' and 'retailops_oauth_transient=' in v]
                self.assertTrue(len(cleanup_cookies) >= 1)
                self.assertIn('Max-Age=0', cleanup_cookies[0])

            # 3. Single-use: Replaying the same state fails with 403 invalid_oauth_state
            with self.assertRaises(ApiError) as ctx:
                self.web.route(cb_env)
            self.assertEqual(ctx.exception.status, 403)
            self.assertEqual(ctx.exception.code, 'invalid_oauth_state')

            # 4. Callback missing cookie fails with 403
            state2 = auth_google.create_state(nonce='dummy_nonce')
            cb_no_cookie = {
                'REQUEST_METHOD': 'GET',
                'PATH_INFO': '/auth/google/callback',
                'QUERY_STRING': f'code=code123&state={state2}',
                'HTTP_HOST': 'retailops.example.com',
            }
            with self.assertRaises(ApiError) as ctx:
                self.web.route(cb_no_cookie)
            self.assertEqual(ctx.exception.status, 403)
            self.assertEqual(ctx.exception.code, 'invalid_oauth_state')

            # 5. Callback with mismatched cookie fails with 403
            cb_mismatched = {
                'REQUEST_METHOD': 'GET',
                'PATH_INFO': '/auth/google/callback',
                'QUERY_STRING': f'code=code123&state={state2}',
                'HTTP_HOST': 'retailops.example.com',
                'HTTP_COOKIE': 'retailops_oauth_transient=wrong_nonce_val',
            }
            with self.assertRaises(ApiError) as ctx:
                self.web.route(cb_mismatched)
            self.assertEqual(ctx.exception.status, 403)
            self.assertEqual(ctx.exception.code, 'invalid_oauth_state')

            # 6. Multi-tab safety: Tab A login -> Tab B login -> late Tab A callback -> Tab B callback
            nonce_a = 'tab_a_nonce_12345'
            state_a = auth_google.create_state(nonce_a)
            nonce_b = 'tab_b_nonce_67890'
            state_b = auth_google.create_state(nonce_b)

            # Tab A callback arrives, but browser cookie currently holds Tab B's nonce
            late_tab_a_env = {
                'REQUEST_METHOD': 'GET',
                'PATH_INFO': '/auth/google/callback',
                'QUERY_STRING': f'code=code_a&state={state_a}',
                'HTTP_HOST': 'retailops.example.com',
                'HTTP_COOKIE': f'retailops_oauth_transient={nonce_b}',
            }
            with self.assertRaises(ApiError) as ctx:
                self.web.route(late_tab_a_env)
            self.assertEqual(ctx.exception.status, 403)
            # Crucial: Error response must NOT clean up cookie of Tab B
            self.assertFalse(any('retailops_oauth_transient' in h[1] for h in ctx.exception.headers))

            # Now Tab B callback arrives with matching nonce_b -> it MUST succeed!
            with patch('retailops.http.auth_google.exchange_code_for_user_info') as mock_exchange:
                mock_exchange.return_value = {
                    'email': 'tab.b@gmail.com',
                    'name': 'Tab B',
                    'sub': 'google-tab-b'
                }
                tab_b_env = {
                    'REQUEST_METHOD': 'GET',
                    'PATH_INFO': '/auth/google/callback',
                    'QUERY_STRING': f'code=code_b&state={state_b}',
                    'HTTP_HOST': 'retailops.example.com',
                    'HTTP_COOKIE': f'retailops_oauth_transient={nonce_b}',
                }
                status_b, _, _, headers_b = self.web.route(tab_b_env)
                self.assertEqual(status_b, 302)
                cleanup_b = [v for k, v in headers_b if k == 'Set-Cookie' and 'retailops_oauth_transient=' in v]
                self.assertTrue(len(cleanup_b) >= 1)
                self.assertIn('Max-Age=0', cleanup_b[0])


if __name__ == '__main__':
    unittest.main()
