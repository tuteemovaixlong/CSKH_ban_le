import json
from pathlib import Path
import tempfile
import unittest
from opsconsole.metrics import classification, distribution, observed_sum, retrieval
from opsconsole.evaluation import (router_report, save_report, load_json, import_live,
                                   case_result, summarize, trace_summary)
from opsconsole.usage import aggregate
from opsconsole.server import Console


class MetricsTests(unittest.TestCase):
    def test_confusion_and_f1(self):
        m = classification([('general', 'general'), ('general', 'retail'), ('retail', 'retail')])
        self.assertEqual(m['confusion_matrix'], [[1, 1, 0], [0, 1, 0]])
        self.assertAlmostEqual(m['accuracy'], 2/3)
        self.assertAlmostEqual(m['macro_f1'], 2/3)

    def test_missing_not_success(self):
        m = classification([('general', None)])
        self.assertEqual(m['accuracy'], 0)
        self.assertEqual(m['classes']['general']['f1'], 0)
        self.assertIsNone(classification([])['accuracy'])
        self.assertIsNone(classification([])['macro_f1'])

    def test_unknown_cost_not_zero(self):
        self.assertIsNone(observed_sum([None, None])['known_sum'])
        self.assertEqual(observed_sum([0, None])['coverage'], .5)
        self.assertEqual(observed_sum([0, None])['known_sum'], 0)
        self.assertIsNone(observed_sum([True, float('nan'), float('inf')])['known_sum'])

    def test_small_sample_percentiles(self):
        self.assertIsNone(distribution([1, 2, 3])['p95'])
        self.assertEqual(distribution([1, 2, 3])['p50'], 2)
        self.assertIsNotNone(distribution(range(20))['p95'])
        self.assertIsNone(distribution(range(20))['p99'])

    def test_retrieval_requires_qrels(self):
        self.assertIsNone(retrieval(['doc1'], None, 5)['recall_at_k'])
        m = retrieval(['wrong', 'doc1', 'doc1'], {'doc1': 1, 'doc2': 1}, 3)
        self.assertEqual(m['recall_at_k'], .5)
        self.assertEqual(m['mrr_at_k'], .5)
        self.assertAlmostEqual(m['precision_at_k'], 1/3)

    def test_critical_failure_not_averaged_away(self):
        cases = [case_result('a', 'safety', {'viewer_denied_cancel': False}),
                 case_result('b', 'general', {'routing': True})]
        self.assertEqual(summarize(cases)['critical_checks']['status'], 'fail')
        self.assertEqual(case_result('c', 'x', {'unmeasured': None})['status'], 'incomplete')

    def test_trace_allowlist(self):
        clean = trace_summary({'token': 'SECRET', 'messages': 'private content',
                               'model': 'https://secret.example', 'tools': ['get_order', 'shell'],
                               'latency_ms': -1})
        self.assertNotIn('SECRET', json.dumps(clean))
        self.assertNotIn('private content', json.dumps(clean))
        self.assertEqual(clean['tools'], ['get_order', 'unknown_tool'])
        self.assertIsNone(clean['model'])
        self.assertIsNone(clean['latency_ms'])


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_router_splits_and_immutable_output(self):
        data = [{'id': 'a', 'category': 'general', 'split': 'dev', 'expected_mode': 'general', 'user_text': 'technical'},
                {'id': 'b', 'category': 'general', 'split': 'held_out', 'expected_mode': 'general', 'user_text': 'hello'}]
        source = self.root / 'cases.jsonl'
        source.write_text('\n'.join(json.dumps(v) for v in data), encoding='utf-8')
        report = router_report(source, lambda messages: 'retail', 'a'*40)
        self.assertEqual(report['metrics']['routing']['accuracy'], 0)
        self.assertEqual(report['metrics']['by_split']['held_out']['cases'], 1)
        self.assertIsNone(report['metrics']['task_success'])
        path = save_report(report, self.root / 'runs')
        self.assertTrue((path / 'failures.jsonl').exists())
        self.assertTrue((path / 'checksums.json').exists())
        with self.assertRaises(FileExistsError):
            save_report(report, self.root / 'runs')

    def test_live_import_idempotent_and_sanitized(self):
        source = self.root / 'live.json'
        source.write_text(json.dumps({'report': 'RetailOps live E2E', 'mode': 'full', 'pass': True,
            'checks': {'health': True}, 'credential': 'SECRET',
            'traces': {'general': {'request_mode': 'general', 'tools': [], 'message': 'SECRET'}}}), encoding='utf-8')
        report = import_live(source)
        self.assertNotIn('SECRET', json.dumps(report))
        self.assertEqual(report['metrics']['checks']['passed'], 4)
        self.assertEqual(report['metrics']['status'], 'incomplete')
        path = save_report(report, self.root / 'runs')
        self.assertEqual(save_report(import_live(source), self.root / 'runs'), path)
        self.assertEqual(len(list((self.root / 'runs').iterdir())), 1)

    def test_aborted_report_never_becomes_a_pass(self):
        source = self.root / 'failed.json'
        source.write_text(json.dumps({'report': 'RetailOps live E2E', 'mode': 'full', 'pass': False, 'checks': {'health': True}}), encoding='utf-8')
        report = import_live(source)
        self.assertEqual(report['metrics']['status'], 'fail')
        self.assertGreater(report['metrics']['checks']['unmeasured'], 0)
        self.assertEqual(report['metrics']['critical_checks']['status'], 'not_measured')

    def test_nonfinite_json_rejected(self):
        p = self.root / 'bad.json'
        p.write_text('{"score": NaN}', encoding='utf-8')
        with self.assertRaises(ValueError):
            load_json(p)

    def test_http_read_only_host_and_traversal(self):
        app = Console(self.root, 'admin.example.com')
        def request(path, method='GET', host='admin.example.com', query=''):
            response = []
            data = b''.join(app({'PATH_INFO': path, 'REQUEST_METHOD': method, 'HTTP_HOST': host,
                                 'QUERY_STRING': query}, lambda status, headers: response.append((status, headers))))
            return response[0][0], data
        self.assertTrue(request('/api/runs')[0].startswith('200'))
        self.assertTrue(request('/api/runs', host='evil.example')[0].startswith('403'))
        self.assertTrue(request('/api/runs', method='POST')[0].startswith('405'))
        self.assertTrue(request('/api/runs', query='path=/etc/passwd')[0].startswith('400'))
        self.assertFalse(request('/api/runs/../../secret')[0].startswith('200'))
        self.assertTrue(request('/api/usage')[0].startswith('200'))
        self.assertTrue(request('/unknown')[0].startswith('404'))

    def test_symlink_artifact_rejected(self):
        folder = self.root / 'runs'
        folder.mkdir()
        try:
            (folder / 'escape').symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest('OS does not permit symlinks')
        with self.assertRaises(ValueError):
            Console(self.root, 'admin.example.com').read_run('escape')


class UsageTests(unittest.TestCase):
    def test_demo_and_e2e_separate_no_identifiers_or_content(self):
        now = 1788840000
        rows = [{'tenant': t, 'customer': 'C-SECRET', 'kind': 'agent_replied', 'created_at': now-10,
                 'trace': trace_summary({'model': 'qwen3.5:4b', 'provider': 'custom', 'prompt_tokens': 100,
                                         'message': 'DO_NOT_EXPORT'})} for t in ('browser-demo', 'e2e-full-1')]
        logins = [{'tenant': 'browser-demo', 'principal': 'PRIVATE_USER', 'created_at': now-30}]
        report = aggregate(rows, logins, now, b'x'*32)
        self.assertEqual(report['windows']['demo_user']['1']['events'], 1)
        self.assertEqual(report['windows']['test']['1']['events'], 1)
        self.assertEqual(report['windows']['demo_user']['1']['unique_login_principals'], 1)
        for secret in ('C-SECRET', 'PRIVATE_USER', 'DO_NOT_EXPORT', 'browser-demo'):
            self.assertNotIn(secret, json.dumps(report))
        self.assertIsNone(report['windows']['demo_user']['1']['retry_rate'])
        self.assertIsNone(report['windows']['demo_user']['1']['usage']['reported_cost_usd']['known_sum'])
        self.assertIsNone(report['windows']['demo_user']['1']['cancellation_funnel'])

    def test_windows_and_partial_coverage(self):
        now = 1788840000
        rows = [{'tenant': 'demo', 'customer': 'x', 'kind': 'order_viewed', 'created_at': now-2*86400}]
        report = aggregate(rows, [], now, b'x'*32, source_partial=True)
        self.assertEqual(report['windows']['demo_user']['1']['events'], 0)
        self.assertEqual(report['windows']['demo_user']['7']['events'], 1)
        self.assertTrue(report['source_partial'])


if __name__ == '__main__':
    unittest.main()
