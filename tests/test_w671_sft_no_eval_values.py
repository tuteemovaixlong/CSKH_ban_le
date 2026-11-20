"""Chặn giá trị giả của bộ đo lọt vào ca và phiếu SFT, kể cả chuỗi con."""
from __future__ import annotations

import json
import tempfile
import unittest

from scripts.sft_cases import generate_cases

from scripts.sft_eval_values import VALUE_RE, eval_values, strings


def collisions(cases, briefs):
    found = {}
    for value in sorted(eval_values()):
        ca = [c['id'] for c in cases if value in json.dumps(c, ensure_ascii=False)]
        br = [b['brief_id'] for b in briefs if value in json.dumps(b, ensure_ascii=False)]
        if ca or br:
            found[value] = {'cases': ca, 'briefs': br}
    return found


class TestNoEvalValues(unittest.TestCase):
    def test_no_eval_values_in_cases_or_briefs(self):
        with tempfile.TemporaryDirectory(prefix='w671-values-') as td:
            cases, briefs, _ = generate_cases(td)
            self.assertEqual(collisions(cases, briefs), {})

    def test_extract_codes_emails_urls_and_domains(self):
        text = 'VCH-DEMO-123 a@fake-demo.com https://fake-demo.org/x fake-demo.net SIM-O-50001'
        self.assertEqual(VALUE_RE.findall(text), [
            'VCH-DEMO-123', 'a@fake-demo.com', 'https://fake-demo.org/x', 'fake-demo.net', 'SIM-O-50001'])


if __name__ == '__main__':
    unittest.main()
