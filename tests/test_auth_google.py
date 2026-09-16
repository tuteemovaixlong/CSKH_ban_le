"""Unit tests for Google OAuth 2.0 (SSO) and Role-Based Identity."""
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
        state = auth_google.create_state()
        self.assertTrue(isinstance(state, str) and len(state) >= 20)
        # First verification succeeds
        self.assertTrue(auth_google.verify_and_consume_state(state))
        # Second verification fails (single use / consumed)
        self.assertFalse(auth_google.verify_and_consume_state(state))
        # Non-existent state fails
        self.assertFalse(auth_google.verify_and_consume_state("bogus_token"))

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
        # Create a valid state
        valid_state = auth_google.create_state()
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
            }
            status, body, mime, headers = self.web.route(env)
            self.assertEqual(status, 302)
            headers_dict = dict(headers)
            self.assertEqual(headers_dict.get('Location'), '/')
            self.assertIn('Set-Cookie', headers_dict)
            self.assertIn('__Host-retailops_account=sec_', headers_dict['Set-Cookie'])
            self.mock_sessions.login_google.assert_called_once()


if __name__ == '__main__':
    unittest.main()
