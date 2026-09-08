"""Immutable, versioned evaluation artifacts without customer text or credentials."""
from __future__ import annotations
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timezone
import uuid
from opsconsole.metrics import MODES, TOOLS, classification, ratio, trace_metrics, number

SCHEMA = 'retailops-evaluation-v1'
GRADER = 'observed-contracts-v1'
IDENTIFIER = re.compile(r'[A-Za-z0-9_.:-]{1,100}')
FULL_CHECKS = ('exact_live_image health public_login_surface knowledge_ingest login session_binding orders providers general_model order_model_tool chat_replay_before_restart product_model_tool rag_model_tool model_prepares_but_does_not_mutate proposal_created_and_reloadable restart_session_persistence restart_pending_persistence chat_replay_after_restart confirm_idempotency_and_backend_state viewer_denied_cancel').split()
SMOKE_CHECKS = ('exact_live_image health public_login_surface login session_binding orders providers owned_order logout_revokes_session').split()
CRITICAL = frozenset(('model_prepares_but_does_not_mutate', 'confirm_idempotency_and_backend_state',
                      'viewer_denied_cancel', 'session_binding', 'logout_revokes_session'))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_json(path):
    path = Path(path)
    if path.stat().st_size > 5_000_000:
        raise ValueError('Input exceeds five MB')
    return json.loads(path.read_text(encoding='utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def trace_summary(raw):
    raw = raw if isinstance(raw, dict) else {}
    names = []
    for item in (raw.get('tools') or [])[:64]:
        name = item.get('name') if isinstance(item, dict) else item
        names.append(name if name in TOOLS else 'unknown_tool')
    result = {key: number(raw.get(key)) for key in
              ('model_calls', 'prompt_tokens', 'generated_tokens', 'reported_cost_usd', 'latency_ms')}
    result['tools'] = names
    result['request_mode'] = raw.get('request_mode') if raw.get('request_mode') in MODES else None
    for key in ('provider', 'model'):
        value = raw.get(key)
        result[key] = value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_./:-]{1,100}', value) and '://' not in value else None
    knowledge = raw.get('knowledge')
    result['knowledge'] = ({key: number(knowledge.get(key)) for key in ('searches', 'retrieved_sources', 'cited_sources')}
                           if isinstance(knowledge, dict) else None)
    return result


def summarize(cases):
    checks = [value for case in cases for value in case['checks'].values()]
    passed = sum(case['status'] == 'pass' for case in cases)
    categories = {}
    for case in cases:
        item = categories.setdefault(case['category'], {'total': 0, 'passed': 0, 'failed': 0, 'incomplete': 0})
        item['total'] += 1
        item[{'pass': 'passed', 'fail': 'failed', 'incomplete': 'incomplete'}[case['status']]] += 1
    for item in categories.values():
        item['pass_rate'] = ratio(item['passed'], item['total'])
    pairs = [(case['expected_mode'], case.get('actual_mode')) for case in cases if case.get('expected_mode') in MODES]
    critical = [value for case in cases for key, value in case['checks'].items() if key in CRITICAL]
    return {'status': 'fail' if any(c['status'] == 'fail' for c in cases) else 'incomplete' if not cases or any(c['status'] == 'incomplete' for c in cases) else 'pass',
            'cases': len(cases), 'passed': passed, 'case_pass_rate': ratio(passed, len(cases)),
            'checks': {'passed': sum(v is True for v in checks), 'failed': sum(v is False for v in checks),
                       'unmeasured': sum(v is None for v in checks)},
            'critical_checks': {'evaluated': sum(v is not None for v in critical),
                                'failed': sum(v is False for v in critical),
                                'status': 'fail' if False in critical else 'pass' if critical and None not in critical else 'not_measured'},
            'by_category': categories, 'routing': classification(pairs),
            'usage': trace_metrics(case['trace'] for case in cases if case.get('trace')),
            'rag_recall_at_5': None, 'semantic_groundedness': None,
            'task_success': None,
            'limits': ['Contract pass is not semantic answer correctness.',
                       'Citation provenance is not faithfulness.',
                       'No retrieval score without relevance judgments.',
                       'Do not treat router-only or imported E2E results as a complete release gate.']}


def case_result(case_id, category, checks, **kwargs):
    if not IDENTIFIER.fullmatch(case_id) or not IDENTIFIER.fullmatch(category):
        raise ValueError('Invalid case identifier')
    if any(type(v) is not bool and v is not None for v in checks.values()):
        raise ValueError('Checks must be boolean or null')
    status = 'fail' if False in checks.values() else 'pass' if checks and None not in checks.values() else 'incomplete'
    return {'id': case_id, 'category': category, 'checks': checks, 'status': status, **kwargs}


def router_report(dataset, router, commit='unknown'):
    path = Path(dataset)
    raw = path.read_bytes()
    if len(raw) > 5_000_000:
        raise ValueError('Dataset too large')
    items = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    if not items or len(items) > 10000 or len({item['id'] for item in items}) != len(items):
        raise ValueError('Empty, oversized or duplicate dataset')
    cases = []
    for item in items:
        if item['expected_mode'] not in MODES or item['split'] not in ('dev', 'held_out'):
            raise ValueError('Invalid dataset labels')
        actual = router([{'role': 'user', 'content': item['user_text']}])
        cases.append(case_result(item['id'], item['category'], {'routing': actual == item['expected_mode']},
                                 split=item['split'], expected_mode=item['expected_mode'],
                                 actual_mode=actual if actual in MODES else None))
    report = make_report('router', cases, {'git_sha': commit, 'dataset_sha256': digest(json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()), 'source_bytes_sha256': digest(raw),
                                          'dataset': path.name, 'model': None, 'inference_calls': 0,
                                          'history_policy': 'independent single-turn cases'})
    report['metrics']['by_split'] = {split: summarize([case for case in cases if case['split'] == split])
                                     for split in ('dev', 'held_out')}
    return report


def import_live(source):
    raw = Path(source).read_bytes()
    doc = load_json(source)
    if doc.get('report') != 'RetailOps live E2E' or doc.get('mode') not in ('full', 'smoke'):
        raise ValueError('Not a supported live E2E report')
    cases = [case_result('source_result', 'live_acceptance', {'source_report_pass': doc.get('pass')})]
    for key in FULL_CHECKS if doc['mode'] == 'full' else SMOKE_CHECKS:
        cases.append(case_result(key, 'live_acceptance', {key: doc.get('checks', {}).get(key)}))
    mapping = {'general': 'general', 'order': 'retail', 'product': 'retail', 'rag': 'retail', 'cancel': 'retail'}
    for name, raw_trace in doc.get('traces', {}).items():
        if name not in mapping:
            continue
        trace = trace_summary(raw_trace)
        expected = mapping[name]
        checks = {'routing': trace['request_mode'] == expected}
        if name == 'general':
            checks['tool_free'] = trace['tools'] == []
        cases.append(case_result('trace.' + name, name, checks, expected_mode=expected,
                                 actual_mode=trace['request_mode'], trace=trace))
    runtime = doc.get('runtime') or {}
    image = runtime.get('web_image') or ''
    image_hash = re.search(r'sha256:[a-f0-9]{64}$', image)
    report = make_report('live-' + doc['mode'], cases,
        {'source_sha256': digest(raw), 'source_started_at': doc.get('started_at_utc'),
         'source_finished_at': doc.get('finished_at_utc'),
         'image_digest': image_hash.group() if image_hash else None,
         'git_sha': None, 'dataset': None, 'source_report_pass': doc.get('pass'), 'source_check_count': len(doc.get('checks', {})),
         'transport': 'HTTP through Caddy on EC2 loopback; not external browser E2E'})
    report['run_id'] = 'live-' + digest(raw)[:24]
    return report


def make_report(kind, cases, metadata):
    source = Path(__file__).read_text(encoding='utf-8') + Path(__file__).with_name('metrics.py').read_text(encoding='utf-8')
    metadata = {**metadata, 'grader_sha256': digest(source.encode())}
    return {'schema': SCHEMA, 'grader': GRADER, 'run_id': datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:12],
            'kind': kind, 'created_at': stamp(), 'manifest': metadata, 'cases': cases, 'metrics': summarize(cases)}


def save_report(report, directory):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    target = root / report['run_id']
    if target.exists():
        existing = load_json(target / 'report.json')
        if report['kind'].startswith('live-') and existing['manifest'].get('source_sha256') == report['manifest'].get('source_sha256'):
            return target
        raise FileExistsError('Immutable run already exists')
    with tempfile.TemporaryDirectory(prefix='.pending-', dir=root) as staging:
        stage = Path(staging)
        for name, value in [('report.json', report), ('manifest.json', report['manifest']), ('metrics.json', report['metrics'])]:
            (stage / name).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n', encoding='utf-8')
        for name, cases in [('cases.jsonl', report['cases']), ('failures.jsonl', [c for c in report['cases'] if c['status'] != 'pass'])]:
            (stage / name).write_text(''.join(json.dumps(case, ensure_ascii=False, allow_nan=False) + '\n' for case in cases), encoding='utf-8')
        with (stage / 'cases.csv').open('w', newline='', encoding='utf-8') as handle:
            fields = ['id', 'category', 'status', 'expected_mode', 'actual_mode']
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(report['cases'])
        def scalar_metrics(value, prefix=''):
            for key, item in value.items():
                name = prefix + key
                if isinstance(item, dict):
                    yield from scalar_metrics(item, name + '.')
                elif item is None or type(item) in (int, float):
                    yield (name, '' if item is None else item, item is not None)
        with (stage / 'metrics.csv').open('w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['metric', 'value', 'measured'])
            writer.writerows(scalar_metrics(report['metrics']))
        checksums = {p.name: digest(p.read_bytes()) for p in stage.iterdir()}
        (stage / 'checksums.json').write_text(json.dumps(checksums, indent=2) + '\n', encoding='utf-8')
        os.rename(stage, target)
    return target
