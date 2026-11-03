#!/usr/bin/env python3
"""Validate the synthetic evaluation dataset without importing model/runtime code."""
import json
import re
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
    'prepare_cancellation', 'get_runtime_info', 'get_current_time', 'search_knowledge',
    'track_shipment', 'check_inventory', 'request_human_support'
}
FORBIDDEN_FRAGMENTS = (
    'AKIA', 'OPENROUTER_API_KEY=', 'RETAILOPS_INFERENCE_TOKEN=', 'postgresql://'
)


import sys

def load_cases(target_path=None):
    target = Path(target_path) if target_path else DATASET
    text = target.read_text(encoding='utf-8')
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


# ---------------------------------------------------------------------------------------------
# W3.2-D12: tau-bench style agent scenarios, evals/agent_scenarios_w3_2.jsonl.
# One record is one conversation of the synthetic customer C-001. `fake_model` is the scripted reply of the
# fake gateway used by CI (scripts/run_agent_scenarios.py --fake); a real model ignores it and plans for itself.
# ---------------------------------------------------------------------------------------------
W32_DATASET = ROOT / 'evals' / 'agent_scenarios_w3_2.jsonl'
W32_MIN_SCENARIOS, W32_MAX_SCENARIOS, W32_MIN_PER_CATEGORY = 20, 30, 2
W32_CATEGORIES = (
    'order_lookup', 'cancel', 'return_exchange', 'variant_change', 'ineligible',
    'follow_up', 'off_topic', 'policy', 'human_handoff'
)
W32_FIXTURES = {'standard'}
# The customer toolset of agent_protocol.TOOLS (a test keeps the two lists equal).
W32_TOOLS = {
    'list_orders', 'get_order', 'search_products', 'get_product', 'get_context', 'prepare_order_action',
    'get_runtime_info', 'get_current_time', 'search_knowledge', 'track_shipment', 'check_inventory', 'request_human_support'
}
W32_RAILS = {'forbidden_topic', 'extreme_rage', 'human_request'}
W32_MODES = {'general', 'retail'}
W32_ACTIONS = {'reply', 'choose_cancel_reason', 'choose_order_action_reason'}
W32_TABLES = {'order_action_requests', 'order_action_decisions', 'proposals', 'integration_outbox', 'handoff_episodes'}
W32_ORDER_ACTION_KEYS = {'order_id', 'action_type', 'exchange_kind', 'target_variant_id', 'target_variant_label'}
W32_SCENARIO_KEYS = {'id', 'category', 'title', 'fixture', 'turns', 'final_state', 'knowledge'}
W32_REQUIRED_KEYS = {'id', 'category', 'title', 'fixture', 'turns', 'final_state'}
W32_EXPECT_KEYS = {
    'tools_called', 'tools_any', 'tools_not_called', 'max_tool_calls', 'max_model_calls', 'action', 'order_action',
    'safety_rail', 'request_mode', 'human_support', 'sources', 'answer_all', 'answer_any', 'answer_not'
}
W32_TOOL_EXPECTATIONS = {'tools_called', 'tools_any', 'tools_not_called', 'max_tool_calls', 'safety_rail'}
W32_ID = re.compile(r'[a-z0-9_]{3,60}')
W32_ORDER_ID = re.compile(r'O-[0-9]{3,6}')
W32_STATUS = re.compile(r'[a-z_]{3,20}')
W32_TEMPLATE = re.compile(r'\{\{\s*([^{}]*?)\s*\}\}')
W32_TEMPLATE_PATH = re.compile(r'last_tool\.[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*')
W32_TEXT_LIMIT = 700


def _text(value, label, limit=W32_TEXT_LIMIT):
    assert isinstance(value, str) and value.strip(), f'{label}: expected a non-empty string'
    assert len(value) <= limit, f'{label}: longer than {limit} characters'
    return value


def _names(value, allowed, label):
    assert isinstance(value, list) and value, f'{label}: expected a non-empty list'
    assert all(isinstance(x, str) for x in value), f'{label}: expected strings'
    assert set(value) <= allowed, f'{label}: unknown name(s) {sorted(set(value) - allowed)}'
    assert len(set(value)) == len(value), f'{label}: repeated name'
    return set(value)


def _phrases(value, label):
    assert isinstance(value, list) and value, f'{label}: expected a non-empty list'
    for phrase in value:
        _text(phrase, label, 160)


def _validate_script(steps, label):
    """The fake gateway's replies of one turn: calls, then exactly one final `say`."""
    assert isinstance(steps, list) and len(steps) <= 6, f'{label}: fake_model must be a list of at most 6 steps'
    called, seen_call = set(), False
    for index, step in enumerate(steps):
        where = f'{label}[{index}]'
        assert isinstance(step, dict) and set(step) in ({'say'}, {'call'}, {'call', 'text'}), \
            f'{where}: a step is {{"say": ...}} or {{"call": [...]}}'
        if 'say' in step:
            assert index == len(steps) - 1, f'{where}: the final answer must be the last step'
        else:
            assert index < len(steps) - 1, f'{where}: the last step must be the final answer'
            calls = step['call']
            assert isinstance(calls, list) and 1 <= len(calls) <= 4, f'{where}: 1-4 calls per step'
            for call in calls:
                assert isinstance(call, dict) and set(call) == {'name', 'arguments'}, f'{where}: a call has name and arguments'
                assert call['name'] in W32_TOOLS, f'{where}: unknown tool {call["name"]!r}'
                assert isinstance(call['arguments'], dict), f'{where}: arguments must be an object'
                called.add(call['name'])
        for key in ('say', 'text'):
            if key in step:
                text = step[key]
                assert isinstance(text, str) and len(text) <= W32_TEXT_LIMIT and (key == 'text' or text.strip()), f'{where}: bad {key}'
                for found in W32_TEMPLATE.findall(text):
                    assert W32_TEMPLATE_PATH.fullmatch(found), f'{where}: unknown template {{{{{found}}}}}'
                    assert seen_call, f'{where}: a template needs a tool result before it'
        if 'call' in step:
            seen_call = True
    return called


def _validate_expect(expect, scripted, label):
    assert isinstance(expect, dict) and expect, f'{label}: expect must be a non-empty object'
    assert set(expect) <= W32_EXPECT_KEYS, f'{label}: unknown expectation(s) {sorted(set(expect) - W32_EXPECT_KEYS)}'
    rail = expect.get('safety_rail') is not None
    called = _names(expect['tools_called'], W32_TOOLS, f'{label}.tools_called') if 'tools_called' in expect else set()
    not_called = _names(expect['tools_not_called'], W32_TOOLS, f'{label}.tools_not_called') if 'tools_not_called' in expect else set()
    assert not (called & not_called), f'{label}: a tool is both required and forbidden'
    if not rail:  # a rail's own tool call (the hand-off) is made by the code, not by the script
        assert called <= scripted, f'{label}: tools_called {sorted(called - scripted)} are never scripted'
    assert not (not_called & scripted), f'{label}: the script calls {sorted(not_called & scripted)}'
    assert isinstance(expect.get('tools_any', []), list), f'{label}.tools_any: expected a list of groups'
    for index, group in enumerate(expect.get('tools_any', [])):
        _names(group, W32_TOOLS, f'{label}.tools_any[{index}]')
        if not rail:
            assert set(group) & scripted, f'{label}.tools_any[{index}]: the script calls none of {group}'
    for key, high in (('max_tool_calls', 10), ('max_model_calls', 6)):
        if key in expect:
            assert type(expect[key]) is int and 0 <= expect[key] <= high, f'{label}.{key}: integer 0-{high}'
    if 'action' in expect:
        assert expect['action'] in W32_ACTIONS, f'{label}.action: one of {sorted(W32_ACTIONS)}'
    if 'order_action' in expect:
        assert isinstance(expect['order_action'], dict) and expect['order_action'], f'{label}.order_action: non-empty object'
        assert set(expect['order_action']) <= W32_ORDER_ACTION_KEYS, f'{label}.order_action: unknown key'
        assert all(isinstance(v, str) and v for v in expect['order_action'].values()), f'{label}.order_action: strings'
    if 'safety_rail' in expect:
        assert expect['safety_rail'] is None or expect['safety_rail'] in W32_RAILS, f'{label}.safety_rail: {sorted(W32_RAILS)} or null'
    if 'request_mode' in expect:
        assert expect['request_mode'] in W32_MODES, f'{label}.request_mode: one of {sorted(W32_MODES)}'
    if 'human_support' in expect:
        assert isinstance(expect['human_support'], bool), f'{label}.human_support: boolean'
    if 'sources' in expect:
        _phrases(expect['sources'], f'{label}.sources')
    for key in ('answer_all', 'answer_not'):
        if key in expect:
            _phrases(expect[key], f'{label}.{key}')
    if 'answer_any' in expect:
        assert isinstance(expect['answer_any'], list) and expect['answer_any'], f'{label}.answer_any: list of groups'
        for index, group in enumerate(expect['answer_any']):
            _phrases(group, f'{label}.answer_any[{index}]')


def validate_w32(cases):
    assert W32_MIN_SCENARIOS <= len(cases) <= W32_MAX_SCENARIOS, \
        f'expected {W32_MIN_SCENARIOS}-{W32_MAX_SCENARIOS} scenarios, got {len(cases)}'
    counts, ids, multi_turn = Counter(), set(), 0
    for case in cases:
        assert isinstance(case, dict), 'a scenario must be an object'
        name = case.get('id', '<unknown>')
        assert W32_REQUIRED_KEYS <= set(case) <= W32_SCENARIO_KEYS, f'{name}: invalid fields'
        assert isinstance(name, str) and W32_ID.fullmatch(name), f'{name}: id must be lower-case letters, digits and underscores'
        assert name not in ids, f'duplicate id: {name}'
        ids.add(name)
        assert case['category'] in W32_CATEGORIES, f'{name}: unknown category {case["category"]!r}'
        counts[case['category']] += 1
        _text(case['title'], f'{name}.title', 140)
        assert case['fixture'] in W32_FIXTURES, f'{name}: unknown fixture {case["fixture"]!r}'
        turns = case['turns']
        assert isinstance(turns, list) and 1 <= len(turns) <= 4, f'{name}: 1-4 turns'
        multi_turn += len(turns) > 1
        if 'knowledge' in case:
            assert isinstance(case['knowledge'], list) and len(case['knowledge']) <= 4, f'{name}.knowledge: at most 4 documents'
            for doc in case['knowledge']:
                assert isinstance(doc, dict) and set(doc) == {'source_key', 'title', 'chunk'}, f'{name}.knowledge: source_key, title, chunk'
                _text(doc['source_key'], f'{name}.knowledge.source_key', 120)
                _text(doc['title'], f'{name}.knowledge.title', 120)
                _text(doc['chunk'], f'{name}.knowledge.chunk', 900)
        tools_checked = said_not = False
        for number, turn in enumerate(turns, start=1):
            label = f'{name}.turns[{number}]'
            assert isinstance(turn, dict) and set(turn) == {'user', 'fake_model', 'expect'}, f'{label}: user, fake_model, expect'
            _text(turn['user'], f'{label}.user', 500)
            scripted = _validate_script(turn['fake_model'], f'{label}.fake_model')
            if 'search_knowledge' in scripted:
                assert 'knowledge' in case, f'{label}: the script searches the knowledge base but the scenario has no `knowledge`'
            _validate_expect(turn['expect'], scripted, f'{label}.expect')
            if turn['expect'].get('safety_rail') or turn['expect'].get('max_model_calls') == 0:
                assert not turn['fake_model'], f'{label}: a turn that never reaches the model has no fake_model'
            else:
                assert turn['fake_model'], f'{label}: a turn that reaches the model needs a fake_model script'
            tools_checked |= bool(W32_TOOL_EXPECTATIONS & set(turn['expect']))
            said_not |= 'answer_not' in turn['expect']
        assert tools_checked, f'{name}: some turn must say which tools may or may not be used'
        assert said_not, f'{name}: some turn must say what the answer must not claim (answer_not)'
        state = case['final_state']
        assert isinstance(state, dict) and state and set(state) <= {'orders', 'rows'}, f'{name}.final_state: orders and/or rows'
        for order_id, status in (state.get('orders') or {}).items():
            assert W32_ORDER_ID.fullmatch(order_id) and isinstance(status, str) and W32_STATUS.fullmatch(status), \
                f'{name}.final_state.orders: {order_id}: {status}'
        for table, count in (state.get('rows') or {}).items():
            assert table in W32_TABLES and type(count) is int and 0 <= count <= 20, f'{name}.final_state.rows: {table}: {count}'
    assert set(counts) == set(W32_CATEGORIES) and min(counts.values()) >= W32_MIN_PER_CATEGORY, \
        f'every category needs at least {W32_MIN_PER_CATEGORY} scenarios: {dict(counts)}'
    assert multi_turn >= 2, 'at least two scenarios must continue over several turns'
    return counts


def load_w32_scenarios(target_path=None):
    return load_cases(target_path or W32_DATASET)


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    if target and Path(target).name.startswith('agent_scenarios'):
        scenarios = load_w32_scenarios(target)
        counts = validate_w32(scenarios)
        print('EVAL_DATASET_OK', Path(target).name, 'scenarios=' + str(len(scenarios)), 'categories=' + json.dumps(dict(sorted(counts.items())), sort_keys=True))
        return
    cases = load_cases(target)
    counts = validate(cases)
    target_name = Path(target).name if target else DATASET.name
    print('EVAL_DATASET_OK', target_name, 'cases=' + str(len(cases)), 'categories=' + json.dumps(dict(sorted(counts.items())), sort_keys=True))
    if target is None:  # the default run (CI) also checks the W3.2 agent scenarios
        scenarios = load_w32_scenarios()
        counts = validate_w32(scenarios)
        print('EVAL_DATASET_OK', W32_DATASET.name, 'scenarios=' + str(len(scenarios)), 'categories=' + json.dumps(dict(sorted(counts.items())), sort_keys=True))


if __name__ == '__main__':
    main()
