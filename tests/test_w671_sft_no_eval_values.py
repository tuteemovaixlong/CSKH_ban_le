"""Chặn giá trị giả của bộ đo lọt vào ca và phiếu SFT, kể cả chuỗi con."""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from scripts.sft_cases import generate_cases

ROOT = Path(__file__).resolve().parents[1]
VALUE_RE = re.compile(
    r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b"
    r"|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
    r"|https?://[^\s<>\"']+"
    r"|\b[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|vn|io|xyz|info)\b"
)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def eval_values():
    values = set()
    for path in sorted((ROOT / 'evals/suites').glob('S*.jsonl')):
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            for turn in case.get('turns', []):
                values.update(strings(turn.get('expect', {}).get('attack_not', [])))
            for text in strings([case.get('turns', []), case.get('case_setup', {})]):
                values.update(VALUE_RE.findall(text))
    return {v for v in values if len(v) >= 8
            and not v.startswith(('SIM-', 'KB:', 'P-')) and 'retailops.local' not in v}


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
