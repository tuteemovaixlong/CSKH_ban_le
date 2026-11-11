"""W6.3 row 3: known exact probabilities and seeded case bootstrap."""
import unittest
import contextlib
import io
import json
import tempfile
from collections import Counter
from pathlib import Path


class StatsTests(unittest.TestCase):
    def test_subset_cli_is_seeded_proportional_and_not_first_cases(self):
        from scripts.eval_stats import main
        with tempfile.TemporaryDirectory() as tmp:
            for suite, count in [('S01', 26), ('S02', 18), ('S03', 30), ('S04', 20), ('S05', 26), ('S06', 22),
                                 ('S07', 16), ('S08', 18), ('S09', 26), ('S10', 10), ('S11', 22), ('S12', 16)]:
                rows = [dict(id=f'{suite.lower()}_{i:03d}_synthetic', meta={'suite': suite}) for i in range(count)]
                (Path(tmp) / (suite + '.jsonl')).write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
            def select(seed):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(main(['subset', '--size', '100', '--seed', str(seed), tmp]), 0)
                return out.getvalue().splitlines()
            ids = select(20261110)
            self.assertEqual(len(ids), 100)
            self.assertEqual(len(set(ids)), 100)
            self.assertEqual(ids, select(20261110))
            self.assertNotEqual(ids, select(42))
            counts = Counter(case_id[:3].upper() for case_id in ids)
            self.assertEqual(counts, dict(S01=11, S02=7, S03=12, S04=8, S05=11, S06=9,
                                          S07=6, S08=7, S09=10, S10=4, S11=9, S12=6))
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(['subset', '--size', '251', tmp])

    def test_compare_cases_file_filters_reports_but_preserves_hash_guard(self):
        from scripts.eval_stats import compare, main
        a = {'datasets': {'S01.jsonl': 'abc'}, 'scenarios': [dict(id='x', passed=True), dict(id='y', passed=False)]}
        b = {**a, 'scenarios': [dict(id='x', passed=False), dict(id='z', passed=True)]}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name, report in [('a.json', a), ('b.json', b)]:
                (folder / name).write_text(json.dumps(report), encoding='utf-8')
            cases = folder / 'cases.txt'
            cases.write_text('x\ny\nz\n', encoding='utf-8')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main(['compare', str(folder / 'a.json'), str(folder / 'b.json'), '--cases', str(cases)])
            result = json.loads(out.getvalue())
            self.assertEqual((result['cases'], result['b'], result['c']), (1, 1, 0))
            self.assertEqual(result['excluded_case_ids'], ['y', 'z'])
        with self.assertRaisesRegex(ValueError, 'SHA'):
            compare(a, {**b, 'datasets': {'S01.jsonl': 'changed'}}, cases=['x'])
        with self.assertRaisesRegex(ValueError, 'common'):
            compare(a, b, cases=['missing'])

    def test_exact_mcnemar(self):
        from scripts.eval_stats import mcnemar_exact
        self.assertAlmostEqual(mcnemar_exact(10, 2), 0.03857421875)
        self.assertEqual(mcnemar_exact(10, 10), 1)
        self.assertEqual(mcnemar_exact(0, 0), 1)

    def test_case_bootstrap(self):
        from scripts.eval_stats import bootstrap_ci
        values = [1.] * 50 + [0.] * 50
        left, right = bootstrap_ci(values)
        self.assertLess(left, .5)
        self.assertGreater(right, .5)
        self.assertTrue(.37 < left < .43 and .57 < right < .63)
        self.assertEqual((left, right), bootstrap_ci(values))

    def test_compare_rejects_unpaired_or_changed_data(self):
        from scripts.eval_stats import compare
        report = {'datasets': {'S01.jsonl': 'abc'}, 'scenarios': [dict(id='x', passed=True)]}
        with self.assertRaisesRegex(ValueError, 'SHA'):
            compare(report, {**report, 'datasets': {'S01.jsonl': 'changed'}})
        with self.assertRaisesRegex(ValueError, 'case'):
            compare(report, {**report, 'scenarios': [dict(id='y', passed=True)]})
