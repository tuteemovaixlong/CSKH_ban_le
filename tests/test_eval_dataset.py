import json
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


def load_cases():
    return [json.loads(line) for line in DATASET.read_text(encoding='utf-8').splitlines() if line.strip()]


def test_eval_dataset_has_balanced_foundation():
    cases = load_cases()
    assert len(cases) >= 30
    assert {case['split'] for case in cases} == ALLOWED_SPLITS
    assert {case['category'] for case in cases} == ALLOWED_CATEGORIES
    counts = {category: sum(case['category'] == category for case in cases) for category in ALLOWED_CATEGORIES}
    assert all(count >= 5 for count in counts.values())


def test_eval_dataset_contract_and_unique_ids():
    cases = load_cases()
    ids = set()
    for case in cases:
        assert set(case) == REQUIRED
        assert case['id'] not in ids
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


def test_general_cases_are_tool_free():
    for case in load_cases():
        if case['expected_mode'] == 'general':
            assert case['expected_tools'] == []
            assert 'search_knowledge' in case['forbidden_tools']


def test_dataset_contains_no_secret_material():
    forbidden_fragments = ('AKIA', 'OPENROUTER_API_KEY=', 'RETAILOPS_INFERENCE_TOKEN=', 'postgresql://')
    text = DATASET.read_text(encoding='utf-8')
    assert not any(fragment in text for fragment in forbidden_fragments)
