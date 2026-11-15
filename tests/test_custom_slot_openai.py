"""Custom model slot served by an OpenAI-compatible endpoint (Qwen3.5-9B on Colab vLLM), §32 W6.4-D5a.

The API slot keeps its own provider (DeepSeek). Without RETAILOPS_CUSTOM_API_ENDPOINT the custom slot keeps the
legacy agent proxy.
"""
import io
import json
import os
import types
import unittest
from unittest.mock import patch

from gemma_fakes import chat_reply
from retailops.business.application import Application
from retailops.config import Settings
from retailops.guardrails.topic_filter import extract_canary_candidates
from retailops.models import build_gateways
from retailops_agent import RemoteAgent
from retailops_providers import TUNNEL_TOKEN_HEADER, OpenRouterAgent

CUSTOM_ENDPOINT = 'https://colab-fixture.ngrok-free.dev/v1/chat/completions'
CUSTOM_KEY = 'custom_key_fixture_' + 'k' * 30
CUSTOM_TUNNEL = 'custom_tunnel_fixture_' + 't' * 30
API_KEY = 'sk-' + 'd' * 40


def public_env(**extra):
    env = {
        'RETAILOPS_PUBLIC_ORIGIN': 'https://retailops.example.com',
        'RETAILOPS_PUBLIC_INVITE_TOKEN': 'invite_' + 'x' * 36,
        'RETAILOPS_API_ENABLED': 'true',
        'RETAILOPS_API_ENDPOINT': 'https://api.deepseek.com/chat/completions',
        'RETAILOPS_API_MODEL': 'deepseek-flash',
        'RETAILOPS_API_KEY': API_KEY,
        'RETAILOPS_PUBLIC_CUSTOM_ENABLED': 'true',
        'RETAILOPS_MODEL': 'Qwen/Qwen3.5-9B',
        'RETAILOPS_CUSTOM_API_ENDPOINT': CUSTOM_ENDPOINT,
        'RETAILOPS_CUSTOM_API_KEY': CUSTOM_KEY,
        'RETAILOPS_CUSTOM_API_TUNNEL_TOKEN': CUSTOM_TUNNEL,
    }
    env.update(extra)
    return {k: v for k, v in env.items() if v is not None}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class CustomSlotSettingsTests(unittest.TestCase):
    def test_settings_read_the_custom_endpoint_and_hide_its_secrets(self):
        settings = Settings.from_environment('public', environ=public_env())
        self.assertEqual(settings.custom_api_endpoint, CUSTOM_ENDPOINT)
        self.assertEqual(settings.custom_api_key, CUSTOM_KEY)
        self.assertEqual(settings.custom_api_tunnel_token, CUSTOM_TUNNEL)
        self.assertNotIn(CUSTOM_KEY, repr(settings))
        self.assertNotIn(CUSTOM_TUNNEL, repr(settings))
        self.assertEqual(settings.summary()['custom_backend'], 'openai_compatible')

    def test_invalid_custom_settings_are_rejected(self):
        cases = {
            'plain http': {'RETAILOPS_CUSTOM_API_ENDPOINT': 'http://colab-fixture.ngrok-free.dev/v1/chat/completions'},
            'query string': {'RETAILOPS_CUSTOM_API_ENDPOINT': CUSTOM_ENDPOINT + '?k=1'},
            'credentials in URL': {'RETAILOPS_CUSTOM_API_ENDPOINT': 'https://u:p@colab-fixture.ngrok-free.dev/v1/chat/completions'},
            'missing key': {'RETAILOPS_CUSTOM_API_KEY': None},
            'missing tunnel token': {'RETAILOPS_CUSTOM_API_TUNNEL_TOKEN': None},
            'short key': {'RETAILOPS_CUSTOM_API_KEY': 'short'},
            'same key twice': {'RETAILOPS_CUSTOM_API_TUNNEL_TOKEN': CUSTOM_KEY},
        }
        for name, extra in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                Settings.from_environment('public', environ=public_env(**extra))

    def test_without_the_custom_endpoint_the_settings_are_unchanged(self):
        env = public_env(RETAILOPS_CUSTOM_API_ENDPOINT=None, RETAILOPS_CUSTOM_API_KEY=None,
                         RETAILOPS_CUSTOM_API_TUNNEL_TOKEN=None)
        settings = Settings.from_environment('public', environ=env)
        self.assertEqual(settings.custom_api_endpoint, '')
        self.assertEqual(settings.summary()['custom_backend'], 'agent_proxy')


class CustomSlotGatewayTests(unittest.TestCase):
    def test_custom_slot_is_an_openai_gateway_and_the_api_slot_keeps_deepseek(self):
        gateways = build_gateways(Settings.from_environment('public', environ=public_env()))
        self.assertIsInstance(gateways.custom, OpenRouterAgent)
        self.assertEqual(gateways.custom.model, 'Qwen/Qwen3.5-9B')
        self.assertEqual(gateways.custom.endpoint, CUSTOM_ENDPOINT)
        self.assertFalse(gateways.custom.is_vision)
        self.assertIsInstance(gateways.api, OpenRouterAgent)
        self.assertEqual(gateways.api.model, 'deepseek-flash')
        self.assertEqual(gateways.api.endpoint, 'https://api.deepseek.com/chat/completions')

    def test_custom_chat_sends_both_layers_to_the_custom_endpoint_only(self):
        gateways = build_gateways(Settings.from_environment('public', environ=public_env()))
        seen = []

        def fake_open(request, timeout=0):
            seen.append((request.full_url, {k.lower(): v for k, v in request.header_items()}))
            return _Response(json.dumps(chat_reply('Xin chào', model='Qwen/Qwen3.5-9B')).encode('utf-8'))

        turn = gateways.custom.for_turn()
        with patch.object(turn._opener, 'open', side_effect=fake_open):
            res = turn.chat([{'role': 'user', 'content': 'alo'}], False, 5)
        self.assertEqual(res['message']['content'], 'Xin chào')
        url, headers = seen[0]
        self.assertEqual(url, CUSTOM_ENDPOINT)
        self.assertEqual(headers['authorization'], 'Bearer ' + CUSTOM_KEY)
        self.assertEqual(headers[TUNNEL_TOKEN_HEADER.lower()], CUSTOM_TUNNEL)
        self.assertNotIn(API_KEY, json.dumps(headers))

    def test_without_the_custom_endpoint_the_legacy_agent_proxy_is_used(self):
        env = public_env(RETAILOPS_CUSTOM_API_ENDPOINT=None, RETAILOPS_CUSTOM_API_KEY=None,
                         RETAILOPS_CUSTOM_API_TUNNEL_TOKEN=None,
                         RETAILOPS_MODEL_URL='https://proxy-fixture.ngrok-free.dev',
                         RETAILOPS_ALLOWED_HOST='proxy-fixture.ngrok-free.dev',
                         RETAILOPS_INFERENCE_TOKEN='inference_' + 'i' * 40)
        gateways = build_gateways(Settings.from_environment('public', environ=env))
        self.assertIsInstance(gateways.custom, RemoteAgent)


class CustomSlotDisplayTests(unittest.TestCase):
    def test_provider_list_shows_the_custom_model_and_label(self):
        gateways = build_gateways(Settings.from_environment('public', environ=public_env()))
        stub = types.SimpleNamespace(infer=gateways.custom, api_infer=gateways.api, api_daily_limit=30,
                                     default_provider='custom')
        providers = {p['id']: p for p in Application.providers(stub)['providers']}
        self.assertEqual(providers['custom']['model'], 'Qwen/Qwen3.5-9B')
        self.assertEqual(providers['custom']['label'], 'Custom model · Colab vLLM')
        self.assertTrue(providers['custom']['configured'])
        self.assertEqual(providers['api']['model'], 'deepseek-flash')

    def test_custom_secrets_are_redaction_candidates(self):
        with patch.dict(os.environ, {'RETAILOPS_CUSTOM_API_KEY': CUSTOM_KEY,
                                     'RETAILOPS_CUSTOM_API_TUNNEL_TOKEN': CUSTOM_TUNNEL}):
            candidates = extract_canary_candidates()
        self.assertIn(CUSTOM_KEY, candidates)
        self.assertIn(CUSTOM_TUNNEL, candidates)


if __name__ == '__main__':
    unittest.main()
