#!/usr/bin/env python3
"""Validate the synthetic evaluation dataset without importing model/runtime code."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'evals' / 'scenarios' / 'baseline_v1.jsonl'

REQUIRED = {
    'id', 'split', 'category', 'user_text', 'expected_mode',
    'expected_tools', 'forbidden_tools', 'expected_outcome', 'safety'
}
ALLOWED_SPLITS = {'dev', 'held_out'}
ALLOWED_MODES = {'general', 'retail'}
ALLOWED_CATEGORIES = {'order_lookup', 'product', 'policy', 'mixed', 'general', 'safety'}
KNOWN_TOOLS = {
    'list_orders', 'get_order', 'search_products', 'get_product', 'get_context',
    'prepare_cancellation', 'get_runtime_info', 'get_current_time', 'search_knowledge'
}
FORBIDDEN_FRAGMENTS = (
    'AKIA', 'OPENROUTER_API_KEY=', 'RETAILOPS_INFERENCE_TOKEN=', 'postgresql://'
)


def load_cases():
    text = DATASET.read_text(encoding='utf-8')
    assert not any(fragment in text for fragment in FORBIDDEN_FRAGMENTS), 'dataset contains secret-like material'
    cases = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AssertionError(f'invalid JSONL at line {line_no}: {exc.msg}') from None
    return cases


def validate(cases):
    assert len(cases) >= 30, f'expected at least 30 cases, got {len(cases)}'
    assert {case.get('split') for case in cases} == ALLOWED_SPLITS
    assert {case.get('category') for case in cases} == ALLOWED_CATEGORIES

    counts = Counter(case['category'] for case in cases)
    assert all(counts[category] >= 5 for category in ALLOWED_CATEGORIES), counts

    ids = set()
    for case in cases:
        assert set(case) == REQUIRED, f"{case.get('id', '<unknown>')}: invalid fields"
        assert case['id'] not in ids, f"duplicate id: {case['id']}"
        ids.add(case['id'])
        assert case['split'] in ALLOWED_SPLITS
        assert case['expected_mode'] in ALLOWED_MODES
        assert case['category'] in ALLOWED_CATEGORIES
        assert isinstance(case['user_text'], str) and case['user_text'].strip()
        assert isinstance(case['expected_outcome'], str) and case['expected_outcome'].strip()
        assert isinstance(case['safety'], str) and case['safety'].strip()
        assert isinstance(case['expected_tools'], list)
        assert isinstance(case['forbidden_tools'], list)
        assert set(case['expected_tools']) <= KNOWN_TOOLS
        assert set(case['forbidden_tools']) <= KNOWN_TOOLS
        assert not (set(case['expected_tools']) & set(case['forbidden_tools']))
        if case['expected_mode'] == 'general':
            assert case['expected_tools'] == [], f"{case['id']}: general mode must be tool-free"
            assert 'search_knowledge' in case['forbidden_tools'], f"{case['id']}: general mode must forbid KB search"

    return counts


def main():
    cases = load_cases()
    counts = validate(cases)
    print('EVAL_DATASET_OK', 'cases=' + str(len(cases)), 'categories=' + json.dumps(dict(sorted(counts.items())), sort_keys=True))


if __name__ == '__main__':
    main()
