"""Giá trị giả của bộ đo: dùng chung cho kiểm ca/phiếu và lọc mẫu SFT."""
from __future__ import annotations

import json
import re
from pathlib import Path

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


def eval_values(suites_dir: Path | None = None):
    values = set()
    directory = suites_dir if suites_dir is not None else ROOT / 'evals/suites'
    for path in sorted(directory.glob('S*.jsonl')):
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


