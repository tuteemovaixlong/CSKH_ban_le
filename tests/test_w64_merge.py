"""W6.4.0 row 4: recompute shard metrics; reject incompatible measurements."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import eval_stats as stats, run_agent_scenarios as runner


class MergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ids = [s['id'] for s in runner.load_dataset(runner.DEFAULT_DATASET)[:2]]
        cls.reports = []
        with tempfile.TemporaryDirectory() as td, patch.object(runner.time, 'perf_counter', return_value=1000):
            for i, selected in enumerate(([ids[0]], [ids[1]], ids)):
                out = Path(td) / f'{i}.json'
                assert runner.main(['--fake', '--repeat', '3', '--only', *selected, '--out', str(out)], out=io.StringIO()) == 0
                cls.reports.append(json.loads(out.read_text(encoding='utf-8')))

    def test_two_fake_shards_equal_whole_summary_and_pass_power_k(self):
        a, b, whole = copy.deepcopy(self.reports)
        a['summary']['passed'] = 999  # Never sum cached shard summaries.
        merged = stats.merge_reports([a, b])
        for key in ('summary', 'by_category', 'aggregates'):
            self.assertEqual(merged[key], whole[key])
        self.assertEqual(stats.summary(merged), stats.summary(whole))
        self.assertEqual(stats.compare(merged, whole)['p_value'], 1)

    def test_provenance_mismatch_rejected(self):
        for field in self.reports[0]['provenance']:
            a, b = copy.deepcopy(self.reports[:2])
            b['provenance'][field] = 'different'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'provenance'):
                stats.merge_reports([a, b])

    def test_dataset_sha_mismatch_rejected(self):
        a, b = copy.deepcopy(self.reports[:2])
        b['datasets'][next(iter(b['datasets']))] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'dataset SHA'):
            stats.merge_reports([a, b])

    def test_duplicate_case_run_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate.*run'):
            stats.merge_reports([self.reports[0], self.reports[0]])

    def test_runner_config_mismatch_rejected(self):
        a, b = copy.deepcopy(self.reports[:2])
        b['config']['repeat'] = 2
        with self.assertRaisesRegex(ValueError, 'runner config'):
            stats.merge_reports([a, b])

    def test_cli_merge_summary_compare_and_missing_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            paths = [Path(td) / f'{n}.json' for n in ('a', 'b', 'merged')]
            for path, report in zip(paths, self.reports[:2]):
                path.write_text(json.dumps(report), encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(stats.main(['merge', str(paths[2]), *map(str, paths[:2])]), 0)
                self.assertEqual(stats.main(['summary', str(paths[2])]), 0)
                self.assertEqual(stats.main(['compare', str(paths[2]), str(paths[2])]), 0)
        old = copy.deepcopy(self.reports[0])
        del old['provenance']
        with self.assertRaisesRegex(ValueError, 'provenance'):
            stats.merge_reports([old])


@unittest.skipUnless((runner.ROOT / 'khoa_luan' / 'eval_pack' / '06_vi_du.jsonl').exists(),
                     'the examples file is not shipped in the image; checked on the source tree')
class DatasetLabelTests(unittest.TestCase):
    """Shards of one dataset must carry one report label, whatever case each shard starts with."""

    def test_shards_of_a_mixed_dataset_share_one_label_and_merge(self):
        dataset = runner.ROOT / 'khoa_luan' / 'eval_pack' / '06_vi_du.jsonl'
        cases = runner.load_dataset(str(dataset))
        actor = next(s['id'] for s in cases if 'actor' in s)
        plain = next(s['id'] for s in cases if 'actor' not in s)
        reports = []
        with tempfile.TemporaryDirectory() as td:
            for i, selected in enumerate(([actor], [plain], [plain, actor])):
                out = Path(td) / f'{i}.json'
                code = runner.main(['--fake', '--dataset', str(dataset), '--only', *selected, '--out', str(out)],
                                   out=io.StringIO())
                self.assertEqual(code, 0)
                reports.append(json.loads(out.read_text(encoding='utf-8')))
        self.assertEqual({r['report'] for r in reports}, {reports[2]['report']})
        merged = stats.merge_reports(reports[:2])
        self.assertEqual(merged['summary']['cases'], 2)
