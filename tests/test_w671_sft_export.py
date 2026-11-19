"""Giới hạn tool tùy chọn, kiểm tương thích gói chấm vòng 1 bằng bản băm trước sửa."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import sft_select
from tests.test_w670_sft_select_build import _build_synthetic_workspace


class TestExportLimit(unittest.TestCase):
    def test_default_packets_match_legacy_and_8000_keeps_more_tool_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fx = _build_synthetic_workspace(root)
            scores = sft_select.score_runs(fx['cases_path'], {'qwen': fx['qwen_dir'], 'deepseek': fx['ds_dir']})
            scores_path = root / 'scores.json'
            scores_path.write_text(json.dumps(scores, ensure_ascii=False), encoding='utf-8')
            for name, args in [('default', []), ('explicit', ['--max-tool-chars', '3000']),
                               ('long', ['--max-tool-chars', '8000'])]:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = sft_select.main(['export', '--scores', str(scores_path), '--out', str(root / name),
                                            '--seed', '12345', '--batch-size', '2', *args])
                self.assertEqual(code, 0)
            def packets(name):
                return b''.join(p.read_bytes() for p in sorted((root / name / 'packets').glob('*.jsonl')))
            self.assertEqual(packets('default'), packets('explicit'))
            # Bản băm gói của exporter gốc 302f54b6; chuẩn hóa LF chỉ để chạy trên cả Windows và Linux.
            self.assertEqual(hashlib.sha256(packets('default').replace(b'\r\n', b'\n')).hexdigest(),
                             'c9588f7875062b744e560dc009c55addb840b4fe597997f9497d81b67f62050a')
            maps = {n: json.loads((root / n / 'map.json').read_text(encoding='utf-8'))
                    for n in ('default', 'long')}
            self.assertEqual(maps['default']['max_tool_chars'], 3000)
            self.assertEqual(maps['long']['max_tool_chars'], 8000)
            def tool_lengths(name):
                return [len(r['content']) for line in packets(name).splitlines() for step in json.loads(line)['steps']
                        for r in step['tool_results']]
            self.assertGreater(max(tool_lengths('long')), max(tool_lengths('default')))
            self.assertLessEqual(max(tool_lengths('long')), 8000)

    def test_rubric_matches_selected_limit(self):
        self.assertEqual(sft_select.rubric_text(), sft_select.RUBRIC_TEXT)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(sft_select.main(['--print-rubric', '--max-tool-chars', '8000']), 0)
        self.assertEqual(buf.getvalue().count('8.000 ký tự'), 2)
        self.assertNotIn('3.000 ký tự', buf.getvalue())

    def test_invalid_limit_leaves_no_export(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'out'
            for limit in (0, -1):
                with self.assertRaises(ValueError):
                    sft_select.export_judge_round(Path(td) / 'missing.json', out, max_tool_chars=limit)
                self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
