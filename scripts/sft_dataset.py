"""SFT training dataset format validator and utilities (sft_v1).

W6.7.0 Part A.
Validates individual training cases and full training sets against the SFT contract.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SFT_EVENTS_PATH = ROOT / 'data' / 'demo_events' / 'store_events_sft_v1.jsonl'
EVAL_SUITES_DIR = ROOT / 'evals' / 'suites'

# Same style weights and names as eval_dataset_v2
STYLES = {'chuan', 'teencode', 'khong_dau', 'sai_chinh_ta', 'dai'}


def normalize_text(text: str) -> str:
    return ' '.join(str(text or '').strip().lower().split())


@lru_cache(maxsize=1)
def sft_v1_demo_ids() -> tuple[set[str], set[str], set[str]]:
    customers: set[str] = set()
    orders: set[str] = set()
    products: set[str] = set()

    # Product catalog
    cat_file = ROOT / 'data' / 'products.json'
    if cat_file.exists():
        try:
            cat_data = json.loads(cat_file.read_text(encoding='utf-8'))
            for p in cat_data.get('products', []):
                if p.get('id'):
                    products.add(p['id'])
        except Exception:
            pass

    if SFT_EVENTS_PATH.exists():
        for line in SFT_EVENTS_PATH.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            data = ev.get('data', {})
            if data.get('external_customer_id'):
                customers.add(data['external_customer_id'])
            if data.get('external_order_id'):
                orders.add(data['external_order_id'])
            if data.get('external_product_id'):
                products.add(data['external_product_id'])
            for it in data.get('items', []):
                if isinstance(it, dict) and it.get('external_product_id'):
                    products.add(it['external_product_id'])

    return customers, orders, products


@lru_cache(maxsize=1)
def get_eval_user_utterances() -> set[str]:
    utterances: set[str] = set()
    for suite_file in EVAL_SUITES_DIR.glob('S*.jsonl'):
        for line in suite_file.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            for turn in case.get('turns', []):
                user_msg = turn.get('user')
                if user_msg:
                    utterances.add(normalize_text(user_msg))
            if case.get('actor') == 'staff_case_assist':
                setup = case.get('case_setup', {})
                for cmsg in setup.get('customer_messages', []):
                    txt = cmsg.get('text')
                    if txt:
                        utterances.add(normalize_text(txt))
    return utterances


def validate_train_case(case: dict[str, Any]) -> dict[str, Any]:
    from scripts import eval_dataset_v2

    assert isinstance(case, dict), '<unknown>.case: object required'
    name = case.get('id', '<unknown>')

    def check(ok: bool, field: str, message: str = 'invalid value') -> None:
        assert ok, f'{name}.{field}: {message}'

    check(
        isinstance(name, str)
        and bool(re.fullmatch(r't(0[1-9]|1[0-2])_[0-9]{3}_[a-z0-9_]+', name))
        and len(name) <= 60,
        'id',
        'expected tNN_NNN_description, <=60 chars',
    )
    category = name[:3]
    check(case.get('category') == category, 'category', f'expected {category}')
    check(case.get('fixture') == 'sft_v1', 'fixture', "expected 'sft_v1'")

    meta = case.get('meta')
    check(isinstance(meta, dict), 'meta', 'expected dict')
    check(meta.get('suite') == category.upper(), 'meta.suite', f"expected '{category.upper()}'")
    check(meta.get('split') == 'train', 'meta.split', "expected 'train'")
    check(meta.get('origin') == 'sinh_sft', 'meta.origin', "expected 'sinh_sft'")
    check(meta.get('style') in STYLES, 'meta.style', f'expected one of {sorted(STYLES)}')

    template = meta.get('template')
    check(isinstance(template, str) and bool(template), 'meta.template', 'missing or empty template')

    # Template must be registered in sft_templates if templates are available
    try:
        from scripts.sft_templates import TEMPLATES
        if TEMPLATES:
            check(template in TEMPLATES, 'meta.template', f'unregistered template {template!r}')
    except ImportError:
        pass

    sft_customers, _, _ = sft_v1_demo_ids()
    check(case.get('customer') in sft_customers, 'customer', 'customer not in sft_v1 events')

    # Validate structural schema using normalized copy in eval_dataset_v2.validate_case
    norm = json.loads(json.dumps(case))
    norm['id'] = 's' + case['id'][1:]
    norm['category'] = 's' + case['category'][1:]
    norm['fixture'] = 'standard'
    norm['meta']['suite'] = 'S' + case['meta']['suite'][1:]
    norm['meta']['split'] = 'dev'
    norm['meta']['origin'] = 'mo_phong'
    norm['meta'].pop('template', None)

    # If user utterances are placeholders (e.g. empty), eval_dataset_v2 requires text length >= 2
    # Temporarily substitute dummy text if turn['user'] is placeholder to pass structural checks
    for turn in norm.get('turns', []):
        if not turn.get('user'):
            turn['user'] = 'Khách hỏi thăm đơn hàng kiểm tra cấu trúc'
    if norm.get('actor') == 'staff_case_assist':
        setup = norm.get('case_setup', {})
        for cmsg in setup.get('customer_messages', []):
            if not cmsg.get('text'):
                cmsg['text'] = 'Khách gửi tin nhắn mẫu kiểm tra cấu trúc'

    orig_demo_ids = eval_dataset_v2.demo_ids
    eval_dataset_v2.demo_ids = sft_v1_demo_ids
    try:
        eval_dataset_v2.validate_case(norm, suite=norm['meta']['suite'])
    finally:
        eval_dataset_v2.demo_ids = orig_demo_ids

    return case


def validate_train_set(cases: list[dict[str, Any]]) -> None:
    assert isinstance(cases, list), 'cases must be a list'
    ids: set[str] = set()
    template_counts: Counter[str] = Counter()
    eval_utterances = get_eval_user_utterances()

    for case in cases:
        validate_train_case(case)
        cid = case['id']
        assert cid not in ids, f'Duplicate case id: {cid}'
        ids.add(cid)

        tmpl = case['meta']['template']
        template_counts[tmpl] += 1
        assert template_counts[tmpl] <= 15, f'Template {tmpl} has {template_counts[tmpl]} cases (>15)'

        # Check filled customer utterances against 250 evaluation cases
        for turn in case.get('turns', []):
            user_msg = turn.get('user')
            if user_msg and not user_msg.startswith('<chờ lời khách'):
                norm_u = normalize_text(user_msg)
                assert norm_u not in eval_utterances, (
                    f'Case {cid} user message overlaps with eval suites: {user_msg!r}'
                )

        if case.get('actor') == 'staff_case_assist':
            setup = case.get('case_setup', {})
            for cmsg in setup.get('customer_messages', []):
                txt = cmsg.get('text')
                if txt and not txt.startswith('<chờ lời khách'):
                    norm_u = normalize_text(txt)
                    assert norm_u not in eval_utterances, (
                        f'Case {cid} setup customer message overlaps with eval suites: {txt!r}'
                    )
