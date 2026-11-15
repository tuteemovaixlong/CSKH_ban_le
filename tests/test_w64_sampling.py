"""W6.4.0 row 2: opt-in OpenAI sampling; unchanged provider defaults."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gemma_fakes import FIXTURE_KEY, FIXTURE_MODEL, FIXTURE_ENDPOINT, chat_reply
from retailops_providers import OpenRouterAgent
from scripts import run_agent_scenarios as runner

SAMPLING = dict(temperature=1.0, top_p=.95, top_k=20, presence_penalty=1.5, max_tokens=4096)
ENV = {'RETAILOPS_MODEL_' + k.upper(): str(v) for k, v in SAMPLING.items()}


class SamplingTests(unittest.TestCase):
    def payload(self, env):
        with patch.dict(os.environ, env, clear=True):
            agent = OpenRouterAgent(FIXTURE_KEY, FIXTURE_MODEL, endpoint=FIXTURE_ENDPOINT)
            with patch.object(agent, 'request', return_value=chat_reply()) as request:
                agent.chat([{'role': 'user', 'content': 'Xin chào'}], True, 10)
            return request.call_args.args[0]

    def test_default_payload_keeps_old_values_and_omits_optional_fields(self):
        payload = self.payload({})
        self.assertEqual(payload['temperature'], .2)
        self.assertEqual(payload['max_tokens'], 2048)
        for key in ('top_p', 'top_k', 'presence_penalty'):
            self.assertNotIn(key, payload)

    def test_opt_in_payload_has_all_five_values(self):
        payload = self.payload(ENV)
        self.assertEqual({k: payload.get(k) for k in SAMPLING}, SAMPLING)

    def test_invalid_values_are_clear_errors(self):
        for key, values in {'temperature': ['-1', '2.1', 'nan', 'inf'], 'top_p': ['0', '1.1'],
                            'top_k': ['0', '-1', '1.5'], 'presence_penalty': ['-2.1', '2.1'],
                            'max_tokens': ['0', '-1', 'nope']}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(ValueError, 'RETAILOPS_MODEL_' + key.upper()):
                        self.payload({'RETAILOPS_MODEL_' + key.upper(): value})

    def test_cli_records_effective_sampling_and_restores_environment(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=True):
            target = Path(td) / 'report.json'
            args = ['--fake', '--only', runner.load_dataset(runner.DEFAULT_DATASET)[0]['id'], '--out', str(target)]
            for key, value in SAMPLING.items():
                args += ['--' + key.replace('_', '-'), str(value)]
            self.assertEqual(runner.main(args, out=io.StringIO()), 0)
            self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['config']['sampling'], SAMPLING)
            self.assertTrue(all(key not in os.environ for key in ENV))

    def test_google_and_anthropic_ignore_openai_sampling_overrides(self):
        with patch.dict(os.environ, ENV, clear=True):
            google = OpenRouterAgent('AIza' + 'x' * 40, 'gemini-2.5-flash')
            reply = chat_reply(model='gemini-2.5-flash')
            with patch.object(google, 'request', return_value=reply) as request:
                google.chat([{'role': 'user', 'content': 'Xin chào'}], True, 10)
            payload = request.call_args.args[0]
            self.assertEqual(payload['temperature'], .2)
            self.assertEqual(payload['max_tokens'], 2048)
            self.assertNotIn('top_k', payload)
            anthropic = OpenRouterAgent('sk-ant-' + 'x' * 40, 'claude-3-5-haiku-20241022')
            with patch.object(anthropic, '_chat_anthropic', return_value={}) as chat:
                anthropic.chat([{'role': 'user', 'content': 'Xin chào'}], True, 10)
            chat.assert_called_once()
