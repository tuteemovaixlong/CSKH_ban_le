"""Version 2 suite contract. No model imports and no evaluation corpus generation."""
import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOTALS = [26, 18, 30, 20, 26, 22, 16, 18, 26, 10, 22, 16]
SIMULATED = [26, 18, 30, 13, 20, 14, 11, 16, 20, 10, 16, 16]
HELD_OUT = [8, 5, 9, 4, 6, 4, 3, 5, 6, 3, 5, 5]
STYLES = dict(chuan=.4, teencode=.2, khong_dau=.15, sai_chinh_ta=.15, dai=.1)


@lru_cache(maxsize=1)
def demo_ids():
    customers, orders, products = set(), set(), set()
    for line in (ROOT / 'data/demo_events/store_events.jsonl').read_text(encoding='utf-8').splitlines():
        data = json.loads(line)['data']
        if data.get('external_customer_id'):
            customers.add(data['external_customer_id'])
        if data.get('external_order_id'):
            orders.add(data['external_order_id'])
        if data.get('external_product_id'):
            products.add(data['external_product_id'])
        products.update(i['external_product_id'] for i in data.get('items', []))
    return customers, orders, products


def normalized(value):
    return ' '.join(value.split())


def validate_case(case, suite=None):
    from scripts import check_eval_dataset as c
    from scripts.run_agent_scenarios import FIXTURES
    assert isinstance(case, dict), '<unknown>.case: object required'
    name = case.get('id', '<unknown>')
    def check(ok, field, message='invalid value'):
        assert ok, f'{name}.{field}: {message}'
    check(isinstance(name, str) and re.fullmatch(r's(0[1-9]|1[0-2])_[0-9]{3}_[a-z0-9_]+', name)
          and len(name) <= 60, 'id', 'expected sNN_NNN_description, 3–60 characters')
    category = name[:3]
    check(case.get('category') == category and (suite is None or category.upper() == suite), 'category')
    for required in c.W32_REQUIRED_KEYS | {'customer', 'meta'}:
        check(required in case, required, 'required')
    check(set(case) <= c.W4_SCENARIO_KEYS | {'meta', 'overrides'}, 'case.fields')
    customers, orders, products = demo_ids()
    check(case.get('customer') in customers, 'customer', 'not in demo data')
    check(case.get('fixture') in FIXTURES, 'fixture')
    c._text(case.get('title'), f'{name}.title', 700)
    meta = case.get('meta')
    check(isinstance(meta, dict), 'meta')
    for field in ('suite', 'split', 'style', 'origin', 'vn_context', 'source_note'):
        check(field in meta, 'meta.' + field, 'required')
    check(set(meta) <= {'suite', 'split', 'style', 'origin', 'vn_context', 'source_note', 'upstream', 'knowledge_mode'}, 'meta.fields')
    check(meta['suite'] == category.upper(), 'meta.suite')
    check(meta['split'] in {'dev', 'held_out'}, 'meta.split')
    check(meta['style'] in STYLES, 'meta.style')
    check(meta['origin'] in {'mo_phong', 'tau2_retail', 'agentdojo'}, 'meta.origin')
    c._text(meta['source_note'], f'{name}.meta.source_note', 700)
    tags_text = (ROOT / 'khoa_luan/eval_pack/02_BOI_CANH_VIET_NAM.md').read_text(encoding='utf-8').split('## D.')[1].split('## Nguồn')[0]
    tags = set(re.findall(r'`([a-z_0-9]+)`', tags_text)) - {'vn_context'}
    check(isinstance(meta['vn_context'], list) and len(meta['vn_context']) <= 3
          and all(isinstance(t, str) and t in tags for t in meta['vn_context'])
          and len(set(meta['vn_context'])) == len(meta['vn_context']), 'meta.vn_context')
    if meta['origin'] != 'mo_phong':
        upstream = meta.get('upstream')
        check(isinstance(upstream, dict) and bool(upstream), 'meta.upstream', 'task identifier and upstream commit required')
        # The adapter must record both provenance values, regardless of upstream naming convention.
        check(any(k in upstream and isinstance(upstream[k], str) and upstream[k].strip() for k in ('task_id', 'task', 'id'))
              and isinstance(upstream.get('commit'), str) and re.fullmatch(r'[0-9a-f]{40}', upstream['commit']), 'meta.upstream')
    check(meta.get('knowledge_mode', 'scripted') in {'scripted', 'real'}, 'meta.knowledge_mode')
    actor = case.get('actor', 'customer')
    check(actor in c.W4_ACTORS and (actor != 'staff_case_assist' or category == 's11'), 'actor')
    staff = actor == 'staff_case_assist'
    if staff:
        setup = case.get('case_setup')
        check(isinstance(setup, dict) and set(setup) <= {'customer_messages', 'handoff_comment'}, 'case_setup')
        messages = setup.get('customer_messages')
        check(isinstance(messages, list) and 1 <= len(messages) <= 4, 'case_setup.customer_messages')
        for msg in messages:
            check(isinstance(msg, dict) and set(msg) <= {'text', 'attachment'} and 'text' in msg, 'case_setup.customer_messages')
            c._text(msg['text'], f'{name}.case_setup.text', 700)
            if 'attachment' in msg:
                check(msg['attachment'].get('kind') == 'text_pdf', 'case_setup.attachment')
                c._validate_attachment_spec(msg['attachment'], f'{name}.case_setup.attachment')
        if 'handoff_comment' in setup:
            c._text(setup['handoff_comment'], f'{name}.case_setup.handoff_comment', 700)
    else:
        check('case_setup' not in case, 'case_setup')
    knowledge = case.get('knowledge', [])
    check(isinstance(knowledge, list) and len(knowledge) <= 4, 'knowledge')
    for doc in knowledge:
        check(isinstance(doc, dict) and set(doc) == {'source_key', 'title', 'chunk'}, 'knowledge.fields')
        key = doc['source_key']
        check(isinstance(key, str) and Path(key).name == key and '/' not in key and '\\' not in key, 'knowledge.source_key')
        path = ROOT / 'data/knowledge' / key
        check(path.is_file(), 'knowledge.source_key', 'unknown source')
        text = path.read_text(encoding='utf-8')
        title = re.search(r'^#\s+(.+?)\s*$', text, re.M)
        check(title is not None and doc['title'] == title.group(1), 'knowledge.title')
        c._text(doc['chunk'], f'{name}.knowledge.chunk', 700)
        check(normalized(doc['chunk']) in normalized(text), 'knowledge.chunk', 'not a verbatim excerpt')
    def references(value, field):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {'order_id', 'product_id'}:
                    check(isinstance(item, str) and item in (orders if key == 'order_id' else products), field + '.' + key, 'not in demo data')
                references(item, field + '.' + key)
        elif isinstance(value, list):
            for item in value:
                references(item, field)
    overrides = case.get('overrides', {})
    check(isinstance(overrides, dict) and set(overrides) <= {'product_descriptions'}, 'overrides')
    descriptions = overrides.get('product_descriptions', {})
    check(isinstance(descriptions, dict), 'overrides.product_descriptions')
    for pid, description in descriptions.items():
        check(pid in products, 'overrides.product_id', 'not in demo data')
        c._text(description, f'{name}.overrides.product_descriptions', 4000)
    turns = case.get('turns')
    check(isinstance(turns, list) and 1 <= len(turns) <= 4, 'turns')
    tools_checked = said_not = False
    for index, turn in enumerate(turns):
        label = f'{name}.turns[{index}]'
        check(isinstance(turn, dict) and {'user', 'fake_model', 'expect'} <= set(turn)
              <= {'user', 'fake_model', 'expect', 'mode'}, 'turns.fields')
        if staff:
            check(turn.get('mode') in c.W4_ASSIST_MODES, 'turns.mode')
        else:
            check('mode' not in turn, 'turns.mode')
        check(isinstance(turn['user'], str) and len(turn['user']) <= 700
              and (bool(turn['user'].strip()) or staff and turn['mode'] != 'ask'), 'turns.user')
        allowed = c.W4_CASE_ASSIST_TOOLS if staff else c.W32_TOOLS
        scripted = c._validate_script(turn['fake_model'], label + '.fake_model', allowed)
        references(turn['fake_model'], label + '.fake_model')
        expect = turn['expect']
        check(isinstance(expect, dict) and 'safety_rail' not in expect, 'turns.expect')
        for field in ('attack_not', 'attack_tools_not_called'):
            if field in expect:
                if field == 'attack_not':
                    c._phrases(expect[field], label + '.expect.' + field)
                else:
                    c._names(expect[field], c.W4_ALL_TOOLS, label + '.expect.' + field)
        utility = {k: v for k, v in expect.items() if not k.startswith('attack_')}
        c._validate_w4_expect(utility, scripted, allowed, label + '.expect')
        check(staff or not ({'has_draft_reply', 'staff_replies_sent', 'media_projection'} & set(expect)), 'turns.expect')
        check('media_projection' not in expect, 'turns.expect.media_projection', 'not part of v2 format')
        if 'staff_replies_sent' in expect:
            check(expect['staff_replies_sent'] == 0, 'turns.expect.staff_replies_sent')
        references(expect.get('order_action', {}), label + '.expect.order_action')
        if 'search_knowledge' in scripted:
            check('knowledge' in case, 'knowledge', 'required for scripted search')
        if expect.get('max_model_calls') == 0:
            check(not turn['fake_model'], 'turns.fake_model')
        tools_checked |= bool(c.W32_TOOL_EXPECTATIONS & set(expect))
        said_not |= 'answer_not' in expect
    check(tools_checked, 'turns.expect', 'must constrain tools')
    check(said_not, 'turns.expect.answer_not', 'required on some turn')
    state = case.get('final_state')
    check(isinstance(state, dict) and bool(state) and set(state) <= {'orders', 'rows'}, 'final_state')
    check(isinstance(state.get('orders', {}), dict) and isinstance(state.get('rows', {}), dict), 'final_state')
    for oid, status in state.get('orders', {}).items():
        check(oid in orders and status in {'pending', 'shipping', 'delivered', 'cancelled'}, 'final_state.orders')
    for table, count in state.get('rows', {}).items():
        check(table in c.W4_TABLES and type(count) is int and 0 <= count <= 20, 'final_state.rows')
    if staff:
        check(state.get('rows', {}).get('case_assist_turns') == len(turns), 'final_state.rows.case_assist_turns')
    return case


def validate_final(cases):
    errors = []
    simulated = [c for c in cases if c['meta']['origin'] == 'mo_phong']
    for i, (total, sim, held) in enumerate(zip(TOTALS, SIMULATED, HELD_OUT), 1):
        suite = f'S{i:02d}'
        rows = [c for c in cases if c['meta']['suite'] == suite]
        authored = [c for c in simulated if c['meta']['suite'] == suite]
        for field, got, wanted in [('count', len(rows), total), ('mo_phong', len(authored), sim),
                                   ('held_out', sum(c['meta']['split'] == 'held_out' for c in authored), held)]:
            if got != wanted:
                errors.append(f'{suite}.{field}: {got}, expected {wanted}')
        if authored:
            counts = Counter(c['meta']['style'] for c in authored)
            for style, rate in STYLES.items():
                if abs(counts[style] / len(authored) - rate) > .10000001:
                    errors.append(f'{suite}.style.{style}: outside ±10 percentage points')
    styles = Counter(c['meta']['style'] for c in simulated)
    for style, expected in [('chuan', {84}), ('teencode', {42}), ('khong_dau', {31, 32}), ('sai_chinh_ta', {31, 32}), ('dai', {21})]:
        if styles[style] not in expected:
            errors.append(f'all.style.{style}: {styles[style]}, expected {expected}')
    if styles['khong_dau'] + styles['sai_chinh_ta'] != 63:
        errors.append('all.style: khong_dau + sai_chinh_ta must be 63')
    origins = Counter(c['meta']['origin'] for c in cases)
    for origin, expected in [('mo_phong', 210), ('tau2_retail', 28), ('agentdojo', 12)]:
        if origins[origin] != expected:
            errors.append(f'all.origin.{origin}: {origins[origin]}, expected {expected}')
    for label, got, minimum in [('vn_context', sum(bool(c['meta']['vn_context']) for c in simulated), 60),
                                ('multi_turn_outside_S08', sum(len(c['turns']) > 1 and c['category'] != 's08' for c in simulated), 20)]:
        if got < minimum:
            errors.append(f'all.{label}: {got}, expected at least {minimum}')
    if len(cases) != 250:
        errors.append(f'all.count: {len(cases)}, expected 250')
    assert not errors, '\n'.join(errors)


def validate_suites(directory, final=False):
    from scripts.check_eval_dataset import load_cases
    cases, ids = [], set()
    for path in sorted(Path(directory).glob('S*.jsonl')):
        assert re.fullmatch(r'S(0[1-9]|1[0-2])\.jsonl', path.name), f'{path.name}.suite: expected S01…S12'
        for case in load_cases(path):
            validate_case(case, path.stem)
            assert case['id'] not in ids, f"{case['id']}.id: duplicate in suites"
            ids.add(case['id'])
            cases.append(case)
    if final:
        validate_final(cases)
    return cases
