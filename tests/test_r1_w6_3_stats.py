"""W6.3 row 3: known exact probabilities and seeded case bootstrap."""
import unittest


class StatsTests(unittest.TestCase):
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
