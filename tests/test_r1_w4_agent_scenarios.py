"""Phase R1 W4 Item 9 tests: Evaluation scenarios for Case Assistant and Image/PDF media pipeline.

Isolated: uses scripted fake gateways and FakeVllm under the real OpenRouterAgent HTTP adapter.
No live model, no Colab, no network, no real customer data, no external ClamAV daemon.
"""
from __future__ import annotations

from collections import deque
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gemma_fakes import FIXTURE_ENDPOINT, FIXTURE_KEY, FIXTURE_MODEL, FakeVllm, chat_reply
from retailops.workflow.case_assist import STAFF_CASE_ASSIST_TOOLS
from scripts import check_eval_dataset as checker
from scripts import run_agent_scenarios as runner

W4_DATASET = Path(runner.W4_DATASET)
FIXTURE_TUNNEL_TOKEN = 'fixture_tunnel_not_a_secret_' + 't' * 36


def w4_scenarios():
    return runner.load_dataset(W4_DATASET)


def by_id(name):
    return next(s for s in w4_scenarios() if s['id'] == name)


class RecordingTwoLayerVllm(FakeVllm):
    """FakeVllm that records request URLs and Case-Insensitive HTTP headers."""

    def __init__(self, script, **options):
        super().__init__(script, **options)
        self.requests = []

    def _open(self, opener, request, *args, **kwargs):
        headers = {k.lower(): v for k, v in request.header_items()}
        self.requests.append((request.full_url, headers))
        return super()._open(opener, request, *args, **kwargs)


def _count_wire_images(payload):
    count = 0
    for msg in payload.get('messages', ()):
        content = msg.get('content')
        if isinstance(content, list):
            count += sum(1 for p in content if isinstance(p, dict) and p.get('type') == 'image_url')
    return count


def replay_w4(selected):
    """Build a FakeVllm script for W4 scenarios with realistic per-image prompt token counts."""
    queue = deque(
        step
        for s in selected
        for turn in s['turns']
        for step in turn['fake_model']
    )

    def script(payload):
        step = queue.popleft()
        text = runner.fill_templates(step.get('say') or step.get('text') or '', payload['messages'])
        calls = [(c['name'], c['arguments']) for c in step.get('call', [])]
        img_cnt = _count_wire_images(payload)
        prompt_tokens = 110 + (260 * img_cnt)
        return chat_reply(text, calls, prompt_tokens=prompt_tokens, completion_tokens=32)

    return script, queue


class W4DatasetFormatTests(unittest.TestCase):
    def test_w4_dataset_passes_format_check_and_matches_code_contracts(self):
        cases = w4_scenarios()
        self.assertEqual(len(cases), 12)
        self.assertEqual({c['category'] for c in cases}, set(checker.W4_CATEGORIES))
        self.assertIsNone(checker.LEGACY_SEED_ORDER_ID.search(W4_DATASET.read_text(encoding='utf-8')))
        self.assertEqual(
            checker.W4_CASE_ASSIST_TOOLS,
            {t['function']['name'] for t in STAFF_CASE_ASSIST_TOOLS},
        )
        self.assertEqual(checker.W4_TABLES, set(runner.W4_COUNTED_TABLES))

        out = io.StringIO()
        with patch.object(checker.sys, 'argv', ['check_eval_dataset.py', str(W4_DATASET)]), contextlib.redirect_stdout(out):
            checker.main()
        self.assertIn(f'EVAL_DATASET_OK {W4_DATASET.name} scenarios={len(cases)}', out.getvalue())

    def test_all_handoff_item9_situations_are_covered(self):
        ids = {c['id'] for c in w4_scenarios()}
        expected_ids = {
            'assist_summary_cites_case_and_order',
            'assist_summary_reads_sanitized_pdf_in_case',
            'assist_ask_order_and_variant_stock',
            'assist_ask_order_and_return_policy_cited',
            'assist_draft_reply_never_auto_sends',
            'assist_multi_turn_summary_then_draft',
            'assist_out_of_case_order_is_refused',
            'assist_read_only_refuses_direct_cancellation',
            'customer_image_projected_within_bounds_no_exif_no_pii',
            'customer_pdf_text_and_scanned_projected_within_bounds',
            'customer_image_endpoint_error_escalates_to_staff',
            'customer_scanned_pdf_vision_disabled_escalates_to_staff',
        }
        self.assertTrue(expected_ids.issubset(ids), sorted(expected_ids - ids))

    def test_malformed_w4_scenarios_are_rejected(self):
        def check_bad(mutate, why):
            bad = copy.deepcopy(w4_scenarios())
            mutate(bad)
            with self.assertRaises(AssertionError, msg=why):
                checker.validate_w4(bad)

        check_bad(
            lambda c: c[0].update(actor='admin'),
            'unknown actor',
        )
        check_bad(
            lambda c: c[0]['turns'][0]['fake_model'][0]['call'][0].update(name='prepare_order_action'),
            'mutating customer tool inside staff_case_assist script',
        )
        check_bad(
            lambda c: c[0].pop('case_setup'),
            'staff_case_assist without case_setup',
        )
        check_bad(
            lambda c: next(x for x in c if x['id'] == 'customer_image_projected_within_bounds_no_exif_no_pii')[
                'turns'
            ][0]['expect']['media_projection'].update(max_edge=2048),
            'media_projection max_edge > 1024',
        )
        check_bad(
            lambda c: next(x for x in c if x['id'] == 'customer_image_projected_within_bounds_no_exif_no_pii')[
                'turns'
            ][0]['attachment'].update(kind='exe_payload'),
            'unsupported synthetic attachment kind',
        )
        check_bad(
            lambda c: c[0].update(final_state={'orders': {'O-102': 'delivered'}}),
            'legacy seed order ID rejected',
        )


class W4FakeGatewayRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = runner.run_suite(w4_scenarios(), runner.ScriptedGateway, 'fake')

    def test_every_w4_scenario_passes_in_fake_mode(self):
        failed = {r['id']: r['failures'] for r in self.report['scenarios'] if not r['passed']}
        self.assertEqual(failed, {})
        summary = self.report['summary']
        self.assertEqual(self.report['report'], 'agent_scenarios_w4')
        self.assertEqual((summary['passed'], summary['failed'], summary['success_rate']), (len(w4_scenarios()), 0, 1.0))
        self.assertEqual(summary['valid_tool_call_rate'], 1.0)
        self.assertEqual(summary['duplicate_tool_calls'], 0)
        self.assertEqual(summary['model_error_turns'], 0)
        # 1 projected JPEG + 3 rendered pages from the 5-page scanned PDF = 4 projected images across 2 turns.
        self.assertEqual(summary['media_tokens']['image_turns'], 2)
        self.assertEqual(summary['media_tokens']['images_sent'], 4)

    def test_cli_fake_mode_writes_w4_report_and_prints_image_token_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / 'w4_fake_report.json'
            stdout = io.StringIO()
            rc = runner.main(['--fake', '--dataset', str(W4_DATASET), '--out', str(out_path)], out=stdout)
            report = json.loads(out_path.read_text(encoding='utf-8'))
        self.assertEqual(rc, 0)
        self.assertEqual(report['report'], 'agent_scenarios_w4')
        self.assertEqual(report['summary']['success_rate'], 1.0)
        self.assertIn('image token cost:', stdout.getvalue())

    def test_projection_guard_catches_oversized_or_exif_leaks_when_safeguard_broken(self):
        scenario = copy.deepcopy(by_id('customer_image_projected_within_bounds_no_exif_no_pii'))
        scenario['turns'][0]['expect']['media_projection']['max_edge'] = 512
        rec = runner.run_scenario(scenario, runner.ScriptedGateway(), 'fake')
        self.assertFalse(rec['passed'])
        self.assertIn('exceeds 512 px', ' | '.join(rec['failures']))


class W4RealHttpAdapterTwoLayerAuthTests(unittest.TestCase):
    def test_real_adapter_sends_both_item0_headers_measures_image_tokens_and_redacts_secrets(self):
        script, queue = replay_w4(w4_scenarios())
        vllm = RecordingTwoLayerVllm(script, strict=True)
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / 'api_key.secret'
            tunnel_file = Path(tmp) / 'tunnel_token.secret'
            report_file = Path(tmp) / 'w4_real_report.json'
            key_file.write_text(FIXTURE_KEY + '\n', encoding='utf-8')
            tunnel_file.write_text(FIXTURE_TUNNEL_TOKEN + '\n', encoding='utf-8')

            out = io.StringIO()
            err = io.StringIO()
            clean_env = {
                k: v for k, v in os.environ.items()
                if k not in (
                    'RETAILOPS_API_KEY',
                    'RETAILOPS_API_KEY_FILE',
                    'RETAILOPS_API_TUNNEL_TOKEN',
                    'RETAILOPS_API_TUNNEL_TOKEN_FILE',
                    'RETAILOPS_API_ENDPOINT',
                    'RETAILOPS_API_VISION',
                )
            }
            with vllm.install(), patch.dict(os.environ, clean_env, clear=True), contextlib.redirect_stderr(err):
                rc = runner.main(
                    [
                        '--dataset', str(W4_DATASET),
                        '--endpoint', FIXTURE_ENDPOINT,
                        '--model', FIXTURE_MODEL,
                        '--api-key-file', str(key_file),
                        '--tunnel-token-file', str(tunnel_file),
                        '--vision', 'on',
                        '--out', str(report_file),
                    ],
                    out=out,
                )
            report_text = report_file.read_text(encoding='utf-8')

        report = json.loads(report_text)
        failed = {r['id']: r['failures'] for r in report['scenarios'] if not r['passed']}
        self.assertEqual((rc, failed), (0, {}))
        self.assertEqual(len(queue), 0)
        self.assertEqual(report['mode'], 'real')
        self.assertEqual(report['summary']['success_rate'], 1.0)

        # Every HTTP request carried BOTH Item 0 headers (Authorization Bearer + X-RetailOps-Tunnel-Token)
        self.assertGreater(len(vllm.requests), 10)
        for url, headers in vllm.requests:
            self.assertEqual(url, FIXTURE_ENDPOINT)
            self.assertEqual(headers.get('authorization'), f'Bearer {FIXTURE_KEY}')
            self.assertEqual(headers.get('x-retailops-tunnel-token'), FIXTURE_TUNNEL_TOKEN)

        # Image token cost measured across the 4 projected images (1 JPEG + 3 rendered pages of 5-page scanned PDF)
        mt = report['summary']['media_tokens']
        self.assertEqual(mt['image_turns'], 2)
        self.assertEqual(mt['images_sent'], 4)
        self.assertGreater(mt['image_prompt_tokens'], 1000)
        self.assertGreater(mt['avg_prompt_tokens_per_image'], 250.0)
        self.assertIn('tokens/image', out.getvalue())

        # Secrets and full path never leak to stdout, stderr, or JSON report
        combined = out.getvalue() + err.getvalue() + report_text
        self.assertNotIn(FIXTURE_KEY, combined)
        self.assertNotIn(FIXTURE_TUNNEL_TOKEN, combined)
        self.assertNotIn('/v1/chat/completions', combined)

    def test_vision_on_without_tunnel_token_fails_closed_before_any_http_call(self):
        def must_not_call(_payload):
            raise AssertionError('HTTP must not be called when two-layer auth is incomplete')

        vllm = RecordingTwoLayerVllm(must_not_call)
        err = io.StringIO()
        clean_env = {'RETAILOPS_API_KEY': FIXTURE_KEY}
        with vllm.install(), patch.dict(os.environ, clean_env, clear=True), contextlib.redirect_stderr(err):
            rc = runner.main(
                [
                    '--dataset', str(W4_DATASET),
                    '--endpoint', FIXTURE_ENDPOINT,
                    '--model', FIXTURE_MODEL,
                    '--vision', 'on',
                ],
                out=io.StringIO(),
            )
        self.assertEqual(rc, 2)
        self.assertEqual(len(vllm.requests), 0)
        self.assertIn('RETAILOPS_API_TUNNEL_TOKEN', err.getvalue())

    def test_rogue_mutating_tool_call_in_case_assist_is_blocked_and_counted_invalid(self):
        replies = deque(
            [
                chat_reply('', [('prepare_order_action', {'order_id': 'SIM-O-00115', 'action_type': 'cancel'})]),
                chat_reply('', [('get_case_order', {'order_id': 'SIM-O-00115'})]),
                chat_reply('Trợ lý ca chỉ có quyền đọc, không thể hủy đơn SIM-O-00115 trên hệ thống.'),
            ]
        )
        vllm = RecordingTwoLayerVllm(lambda _payload: replies.popleft(), strict=True)
        out = io.StringIO()
        env = {
            'RETAILOPS_API_KEY': FIXTURE_KEY,
            'RETAILOPS_API_TUNNEL_TOKEN': FIXTURE_TUNNEL_TOKEN,
        }
        with vllm.install(), patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(io.StringIO()):
            rc = runner.main(
                [
                    '--dataset', str(W4_DATASET),
                    '--only', 'assist_read_only_refuses_direct_cancellation',
                    '--endpoint', FIXTURE_ENDPOINT,
                    '--model', FIXTURE_MODEL,
                ],
                out=out,
            )
        self.assertEqual(rc, 0)
        # 1 invalid (prepare_order_action -> tool_not_allowed) + 1 valid (get_case_order) => 1/2 = 0.5
        self.assertIn('valid tool-call rate: 1/2 = 0.5', out.getvalue())
        self.assertIn('FAIL assist_read_only_refuses_direct_cancellation', out.getvalue())
        self.assertIn('tool prepare_order_action must not be called', out.getvalue())


if __name__ == '__main__':
    unittest.main()
