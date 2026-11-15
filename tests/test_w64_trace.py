"""W6.4.0 row 3: actual wire payloads, metadata and secret-free JSONL."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gemma_fakes import FakeVllm, FIXTURE_ENDPOINT, FIXTURE_MODEL, FIXTURE_KEY, chat_reply
from scripts import run_agent_scenarios as runner


class TraceTests(unittest.TestCase):
    def run_report(self, reply=None, version=True):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        report, trace = [Path(temp.name) / name for name in ('report.json', 'trace.jsonl')]
        fake = FakeVllm(lambda payload: reply or chat_reply())
        fake.metadata_version = '0.33.0' if version else None
        env = {k: os.environ[k] for k in ('PATH', 'SystemRoot') if k in os.environ}
        env['RETAILOPS_API_KEY'] = FIXTURE_KEY
        env['RETAILOPS_GIT_SHA'] = 'a' * 40  # the source-only/image checkout may omit .git
        with fake.install(), patch.dict(os.environ, env, clear=True):
            code = runner.main(['--endpoint', FIXTURE_ENDPOINT, '--model', FIXTURE_MODEL,
                                '--only', 'lookup_delivered_order_status', '--repeat', '2',
                                '--trace-out', str(trace), '--out', str(report)], out=io.StringIO())
        self.assertEqual(code, 0)
        return json.loads(report.read_text(encoding='utf-8')), trace.read_text(encoding='utf-8'), fake

    def test_wire_call_count_context_reasoning_and_provenance(self):
        reply = chat_reply()
        reply['choices'][0]['message']['reasoning_content'] = 'suy nghĩ thử'
        report, raw, fake = self.run_report(reply)
        p = report['provenance']
        self.assertEqual(set(p), {'git_sha', 'model', 'vllm_version', 'sampling', 'context_tokens',
                                  'thinking', 'agent_mode', 'knowledge'})
        self.assertRegex(p['git_sha'], r'^[0-9a-f]{40}$')
        self.assertEqual(p['model'], FIXTURE_MODEL)
        self.assertEqual(p['vllm_version'], '0.33.0')
        rows = [json.loads(line) for line in raw.splitlines()]
        self.assertEqual(len(rows), len(fake.payloads))
        self.assertEqual(len(rows), report['summary']['model_calls'])
        self.assertEqual({r['run'] for r in rows}, {1, 2})
        for row, payload in zip(rows, fake.payloads):
            self.assertEqual(row['case_id'], 'lookup_delivered_order_status')
            self.assertEqual(row['turn'], 1)
            self.assertEqual(row['request'], payload)
            self.assertEqual(row['response']['reasoning'], 'suy nghĩ thử')
            self.assertEqual(row['response']['finish_reason'], 'stop')
            self.assertEqual(row['response']['usage']['completion_tokens'], 20)
            self.assertGreaterEqual(row['seconds'], 0)

    def test_optional_version_and_secret_echo_are_safe(self):
        reply = chat_reply('Authorization: Bearer ' + FIXTURE_KEY + ' https://example.test/?api_key=' + FIXTURE_KEY)
        reply['choices'][0]['message']['reasoning'] = FIXTURE_KEY
        report, trace, _ = self.run_report(reply, version=False)
        self.assertIsNone(report['provenance']['vllm_version'])
        combined = trace + json.dumps(report)
        self.assertNotIn(FIXTURE_KEY, combined)
        self.assertNotIn('Authorization', combined)
        self.assertNotIn('https://example.test/?api_key=', combined)

    def test_git_sha_fallback_when_git_is_absent(self):
        from scripts.eval_telemetry import git_sha
        with patch('subprocess.run', side_effect=FileNotFoundError), patch.dict(os.environ, {'RETAILOPS_GIT_SHA': 'a' * 40}):
            self.assertEqual(git_sha(runner.ROOT), 'a' * 40)

    def test_length_and_transport_failure_are_also_traced(self):
        report, raw, fake = self.run_report(chat_reply(finish_reason='length'))
        rows = [json.loads(line) for line in raw.splitlines()]
        self.assertEqual(len(rows), len(fake.payloads))
        self.assertTrue(all(r['response']['finish_reason'] == 'length' for r in rows))
        report, raw, fake = self.run_report(TimeoutError('timed out'))
        rows = [json.loads(line) for line in raw.splitlines()]
        self.assertEqual(len(rows), len(fake.payloads))
        self.assertTrue(all(r['response']['error']['kind'] == 'timeout' for r in rows))
