#!/usr/bin/env python3
"""Run the W3.2 agent scenarios (W3.2-D12) against the customer agent of this repository.

Every scenario is a short tau-bench style conversation of one synthetic customer (C-001 of a fresh demo
store built in a temporary directory) with the expectations the code can check: which tools were used,
what must not be said, what the form did and what the store looks like at the end.

Two modes, and only one of them can reach a model:

  --fake              Each scenario brings the replies of a scripted fake gateway. No model, no network.
                      CI runs this; it checks the code around the model, not the model.
  --endpoint URL      The OWNER's real model, for example the "Endpoint API OpenAI" printed by
                      notebooks/colab_vllm_l4.py. The scripted replies are ignored and the model plans and
                      calls the tools itself. Without --endpoint nothing runs.

The run uses its own temporary SQLite store and synthetic data. It never touches a deployed database,
a real customer or a production setting; the only thing it sends out in real mode is the synthetic
conversations, to the endpoint you name.

Report (JSON with --out, summary on stdout):
  success rate        scenarios whose every check holds
  valid tool calls    calls to a known tool with arguments that pass the schema. Business refusals
                      (order not found, not eligible) are valid calls; tool_not_allowed,
                      invalid_tool_arguments and invalid_knowledge_query are not. Exact repeats
                      (duplicate_call) are counted on their own.
  latency p50 / p95   wall time of one customer turn, nearest-rank percentile over all turns
"""
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
import time
import unicodedata
import urllib.parse
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / 'evals' / 'agent_scenarios_w3_2.jsonl'
DEFAULT_MODEL = 'yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2'
PLACEHOLDER_KEY = 'scenario-runner-placeholder-key-0000'   # a vLLM server without --api-key ignores it
CUSTOMER = 'C-001'
INVALID_TOOL_CODES = frozenset({'tool_not_allowed', 'invalid_tool_arguments', 'invalid_knowledge_query'})
LOOPBACK_HOSTS = frozenset({'localhost', '127.0.0.1', '::1'})
REFUSAL = ('Chưa có --endpoint nên script không chạy.\n'
           'Chế độ model thật chỉ dành cho owner: truyền --endpoint <URL> (ví dụ "Endpoint API OpenAI" mà '
           'notebooks/colab_vllm_l4.py in ra).\n'
           'Muốn kiểm tra mã xung quanh model mà không cần model: dùng --fake (gateway giả, không mạng).')

# Orders added on top of the demo seed (O-101 pending and O-102 delivered of C-001; O-202 is C-002's).
FIXTURES = {
    'standard': [
        {'id': 'O-701', 'status': 'delivered', 'variant': 'Đen · Size M · Số lượng 1', 'product_id': 'P-102', 'name': 'Áo khoác Everyday'},
        {'id': 'O-702', 'status': 'delivered', 'variant': 'Đen / 41', 'product_id': 'P-603', 'name': 'Giày lười da bò cao cấp'},
        {'id': 'O-705', 'status': 'pending', 'variant': 'Đen / L', 'product_id': 'P-102', 'name': 'Áo khoác Everyday'},
        {'id': 'O-710', 'status': 'cancelled', 'variant': 'Đen / L', 'product_id': 'P-102', 'name': 'Áo khoác Everyday'},
    ],
}
COUNTED_TABLES = ('order_action_requests', 'order_action_decisions', 'proposals', 'integration_outbox', 'handoff_episodes')
_TEMPLATE = re.compile(r'\{\{\s*last_tool\.([A-Za-z0-9_.]+)\s*\}\}')


class ScenarioError(Exception):
    """A defect of the scenario itself (not of the agent): a bad template or an unusable script."""


def _modules():
    """The runtime modules, imported only when scenarios really run so that --help and the refusal stay light."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from retailops.business.application import Application
    from retailops.core import ApiError
    from retailops.identity.persistent import PersistentSessions
    from retailops.knowledge.repository import KnowledgeRepository
    return Application, ApiError, PersistentSessions, KnowledgeRepository


def _checker():
    spec = importlib.util.spec_from_file_location('check_eval_dataset', Path(__file__).with_name('check_eval_dataset.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_dataset(path=DEFAULT_DATASET):
    """The scenarios of a dataset file, validated by the format check; AssertionError when the file is malformed."""
    checker = _checker()
    scenarios = checker.load_w32_scenarios(path)
    checker.validate_w32(scenarios)
    return scenarios


def dataset_digest(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


# ---------------------------------------------------------------- fake gateway

def _last_tool_json(messages):
    for message in reversed(messages):
        if message.get('role') == 'tool':
            try:
                return json.loads(message.get('content'))
            except (TypeError, ValueError):
                raise ScenarioError('the last tool result is not JSON') from None
    raise ScenarioError('a template points at a tool result but no tool has answered yet')


def fill_templates(text, messages):
    """Replace {{last_tool.a.0.b}} with that value of the last tool result, so a scripted answer can quote it."""
    def value(match):
        data = _last_tool_json(messages)
        for part in match.group(1).split('.'):
            try:
                data = data[int(part)] if isinstance(data, list) else data[part]
            except (KeyError, IndexError, ValueError, TypeError):
                raise ScenarioError(f'{match.group(0)} does not exist in the last tool result') from None
        return str(data)
    return _TEMPLATE.sub(value, text)


class ScriptedGateway:
    """Stands in for the model in --fake mode: replays the scripted replies of the current turn, in order."""

    def __init__(self, identity=None):
        self.identity = identity or {'name': 'scenario-scripted-gateway', 'digest': 'scenario', 'provider': 'custom'}
        self.steps, self.used = [], 0

    def load(self, steps):
        self.steps, self.used = list(steps), 0

    @property
    def leftover(self):
        return len(self.steps) - self.used

    def inspect(self):
        return dict(self.identity)

    def chat(self, messages, allow_tools, timeout, **_):
        if self.used >= len(self.steps):
            raise RuntimeError('the scripted gateway has no reply left for this turn')
        step = copy.deepcopy(self.steps[self.used])
        self.used += 1
        text = fill_templates(step.get('say') or step.get('text') or '', messages)
        message = {'role': 'assistant', 'content': text}
        if step.get('call'):
            message['tool_calls'] = [{'function': {'name': c['name'], 'arguments': c['arguments']}} for c in step['call']]
        return {'message': message, 'prompt_eval_count': 40, 'eval_count': 12}


# ---------------------------------------------------------------- grading

def squash(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', str(text or ''))).strip().casefold()


def grade_turn(expect, outcome, variant_label=lambda order_id, variant_id: None):
    """The failed checks of one turn, as readable strings (an empty list means the turn passed)."""
    failures = []
    if outcome['error']:
        return [f"the turn failed: {outcome['error']['code']} ({outcome['error']['message']})"]
    result = outcome['result'] or {}
    attempted = [t['name'] for t in outcome['tools']]
    called = [t['name'] for t in outcome['tools'] if t.get('error_code') not in INVALID_TOOL_CODES]  # a refused call did nothing
    for name in expect.get('tools_called', []):
        if name not in called:
            refused = ' (the call was malformed and refused)' if name in attempted else ''
            failures.append(f'tool {name} was not called{refused} (called: {called or "none"})')
    for group in expect.get('tools_any', []):
        if not set(group) & set(called):
            failures.append(f'none of {group} was called (called: {called or "none"})')
    for name in expect.get('tools_not_called', []):
        if name in attempted:
            failures.append(f'tool {name} must not be called')
    if 'max_tool_calls' in expect and len(attempted) > expect['max_tool_calls']:
        failures.append(f"{len(attempted)} tool calls, at most {expect['max_tool_calls']} allowed")
    if 'max_model_calls' in expect and outcome['model_calls'] > expect['max_model_calls']:
        failures.append(f"{outcome['model_calls']} model calls, at most {expect['max_model_calls']} allowed")
    if 'action' in expect and result.get('action') != expect['action']:
        failures.append(f"action is {result.get('action')!r}, expected {expect['action']!r}")
    if 'order_action' in expect:
        actual = result.get('order_action') or {}
        for key, wanted in expect['order_action'].items():
            if key == 'target_variant_label':
                found = variant_label(actual.get('order_id'), actual.get('target_variant_id'))
                if found != wanted:
                    failures.append(f'target variant is {found!r}, expected {wanted!r}')
            elif actual.get(key) != wanted:
                failures.append(f'order_action.{key} is {actual.get(key)!r}, expected {wanted!r}')
    trace = result.get('trace') or {}
    if 'safety_rail' in expect and trace.get('safety_rail') != expect['safety_rail']:
        failures.append(f"safety rail is {trace.get('safety_rail')!r}, expected {expect['safety_rail']!r}")
    if 'request_mode' in expect and trace.get('request_mode') != expect['request_mode']:
        failures.append(f"request mode is {trace.get('request_mode')!r}, expected {expect['request_mode']!r}")
    if 'human_support' in expect and bool(result.get('human_support')) != expect['human_support']:
        failures.append(f"human support was {'' if result.get('human_support') else 'not '}requested, expected the opposite")
    sources = [s.get('source_key') for s in result.get('sources') or [] if isinstance(s, dict)]
    for key in expect.get('sources', []):
        if key not in sources:
            failures.append(f'source {key} is not among the answer sources ({sources or "none"})')
    answer = squash(result.get('message'))
    for phrase in expect.get('answer_all', []):
        if squash(phrase) not in answer:
            failures.append(f'the answer lacks {phrase!r}')
    for group in expect.get('answer_any', []):
        if not any(squash(phrase) in answer for phrase in group):
            failures.append(f'the answer has none of {group}')
    for phrase in expect.get('answer_not', []):
        if squash(phrase) in answer:
            failures.append(f'the answer must not say {phrase!r}')
    return failures


def grade_final_state(expect, store):
    failures = []
    with store.connection() as db:
        for order_id, status in (expect.get('orders') or {}).items():
            row = db.execute('SELECT status FROM orders WHERE id = ?', (order_id,)).fetchone()
            actual = row[0] if row else None
            if actual != status:
                failures.append(f'order {order_id} is {actual!r} at the end, expected {status!r}')
        for table, count in (expect.get('rows') or {}).items():
            if table not in COUNTED_TABLES:
                failures.append(f'table {table} cannot be checked')
                continue
            actual = db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            if actual != count:
                failures.append(f'{table} has {actual} rows at the end, expected {count}')
    return failures


def percentile(values, pct):
    """Nearest-rank percentile; None for no data."""
    ordered = sorted(values)
    if not ordered:
        return None
    return round(ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)], 2)


# ---------------------------------------------------------------- running

class World:
    """One scenario's own tenant: a temporary SQLite store with the demo seed and the scenario's fixture."""

    def __init__(self, scenario, gateway):
        Application, self.ApiError, PersistentSessions, self.KnowledgeRepository = _modules()
        self.temp = tempfile.TemporaryDirectory(prefix='w32-scenario-', ignore_cleanup_errors=True)
        sessions = PersistentSessions(Path(self.temp.name) / 'persistent', data_mode='persistent-demo')
        self.store = sessions.provision_tenant('shop-scenarios', 'Shop scenarios', seed_demo=True)
        with self.store.connection(write=True) as db:
            for order in FIXTURES[scenario['fixture']]:
                db.execute('INSERT INTO orders(id, customer_id, product_id, name, variant, amount, status, version) '
                           'VALUES (?, ?, ?, ?, ?, ?, ?, 1)',
                           (order['id'], CUSTOMER, order['product_id'], order['name'], order['variant'], 599000, order['status']))
        # Tool results are tested through the whole application; "api" has no response cache, so a repeated
        # question in another scenario can never be answered without the model.
        self.app = Application(self.store, {}, api_infer=gateway, api_daily_limit=10000)
        self.conversation = self.store.new_conversation(CUSTOMER, 'api')['conversation_id']
        self.knowledge = scenario.get('knowledge')

    def variant_label(self, order_id, variant_id):
        if not order_id or not variant_id:
            return None
        for variant in self.store.exchange_options(CUSTOMER, order_id)['variants']:
            if variant['id'] == variant_id:
                return variant['label']
        return None

    @contextlib.contextmanager
    def knowledge_base(self):
        """A tenant with an indexed knowledge base holding exactly the scenario's documents (none: no base at all)."""
        if self.knowledge is None:
            yield
            return
        documents = [{'chunk': d['chunk'], 'source_key': d['source_key'], 'title': d['title'], 'score': 0.9} for d in self.knowledge]
        from unittest import mock
        self.store.schema = 'tenant_scenarios'
        try:
            with mock.patch.object(self.KnowledgeRepository, 'search', lambda repo, query, limit=5: copy.deepcopy(documents)):
                yield
        finally:
            del self.store.schema

    def say(self, text):
        started = time.perf_counter()
        outcome = {'result': None, 'error': None, 'tools': [], 'model_calls': 0}
        try:
            result = self.app.chat(CUSTOMER, {'conversation_id': self.conversation, 'text': text,
                                              'request_id': 'req-' + uuid.uuid4().hex})
            outcome['result'] = result
            trace = result.get('trace') or {}
        except self.ApiError as err:
            trace = err.trace if isinstance(err.trace, dict) else {}
            if trace.get('error_kind') == 'ScenarioError':  # the application wraps what the script raised in an internal error
                raise ScenarioError(trace.get('error_detail') or 'the script could not be played') from None
            outcome['error'] = {'code': err.code, 'message': str(err.message)[:300]}
        outcome['latency_ms'] = round((time.perf_counter() - started) * 1000, 2)
        outcome['tools'] = [dict(t) for t in trace.get('tools') or [] if isinstance(t, dict) and t.get('name')]
        outcome['model_calls'] = trace.get('model_calls') or 0
        outcome['prompt_tokens'] = trace.get('prompt_tokens') or 0
        outcome['generated_tokens'] = trace.get('generated_tokens') or 0
        return outcome

    def close(self):
        self.temp.cleanup()


def run_scenario(scenario, gateway, mode):
    """Play one scenario; returns its record (verdict, failed checks and the numbers behind the report)."""
    scripted = mode == 'fake'
    world = World(scenario, gateway)
    failures, turns = [], []
    try:
        with world.knowledge_base():
            for number, turn in enumerate(scenario['turns'], start=1):
                if scripted:
                    gateway.load(turn['fake_model'])
                try:
                    outcome = world.say(turn['user'])
                except ScenarioError as err:
                    failures.append(f'turn {number}: script defect: {err}')
                    break
                problems = grade_turn(turn['expect'], outcome, world.variant_label)
                if scripted and not outcome['error'] and gateway.leftover:
                    problems.append(f'{gateway.leftover} scripted reply(ies) were never asked for: the script is out of date')
                failures.extend(f'turn {number}: {p}' for p in problems)
                result = outcome['result'] or {}
                turns.append({'user': turn['user'], 'latency_ms': outcome['latency_ms'], 'model_calls': outcome['model_calls'],
                              'prompt_tokens': outcome['prompt_tokens'], 'generated_tokens': outcome['generated_tokens'],
                              'tools': outcome['tools'], 'action': result.get('action'), 'error': outcome['error'],
                              'answer': str(result.get('message') or '')[:600]})
            failures.extend(f'final state: {p}' for p in grade_final_state(scenario.get('final_state') or {}, world.store))
    finally:
        world.close()
    return {'id': scenario['id'], 'category': scenario['category'], 'title': scenario['title'],
            'passed': not failures, 'failures': failures, 'turns': turns}


def summarize(records):
    turns = [t for r in records for t in r['turns']]
    calls = [c for t in turns for c in t['tools']]
    invalid = [c for c in calls if c.get('error_code') in INVALID_TOOL_CODES]
    latencies = [t['latency_ms'] for t in turns]
    errors = {}
    for t in turns:
        if t['error']:
            errors[t['error']['code']] = errors.get(t['error']['code'], 0) + 1
    passed = sum(r['passed'] for r in records)
    by_category = {}
    for r in records:
        entry = by_category.setdefault(r['category'], {'scenarios': 0, 'passed': 0})
        entry['scenarios'] += 1
        entry['passed'] += r['passed']
    for entry in by_category.values():
        entry['success_rate'] = round(entry['passed'] / entry['scenarios'], 4)
    return {
        'scenarios': len(records), 'passed': passed, 'failed': len(records) - passed,
        'success_rate': round(passed / len(records), 4) if records else None,
        'turns': len(turns), 'tool_calls': len(calls), 'valid_tool_calls': len(calls) - len(invalid),
        'valid_tool_call_rate': round((len(calls) - len(invalid)) / len(calls), 4) if calls else None,
        'duplicate_tool_calls': sum(c.get('error_code') == 'duplicate_call' for c in calls),
        'model_error_turns': sum(errors.values()), 'model_error_codes': errors,
        'model_calls': sum(t['model_calls'] for t in turns),
        'prompt_tokens': sum(t['prompt_tokens'] for t in turns), 'generated_tokens': sum(t['generated_tokens'] for t in turns),
        'latency_ms': {'p50': percentile(latencies, 50), 'p95': percentile(latencies, 95),
                       'max': round(max(latencies), 2) if latencies else None,
                       'mean': round(sum(latencies) / len(latencies), 2) if latencies else None},
    }, by_category


def run_suite(scenarios, make_gateway, mode, *, progress=None):
    records = []
    for index, scenario in enumerate(scenarios, start=1):
        gateway = make_gateway()
        record = run_scenario(scenario, gateway, mode)
        records.append(record)
        if progress:
            progress(index, len(scenarios), record)
    summary, by_category = summarize(records)
    return {'report': 'agent_scenarios_w3_2', 'mode': mode, 'summary': summary, 'by_category': by_category, 'scenarios': records}


# ---------------------------------------------------------------- command line

def normalize_endpoint(url):
    """The chat-completions URL for what the owner typed; ValueError when it is not safe to use."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError('--endpoint is empty')
    parts = urllib.parse.urlsplit(url.strip())
    host = (parts.hostname or '').lower()
    if parts.scheme not in ('https', 'http') or not host:
        raise ValueError('--endpoint must be an http(s) URL')
    if parts.scheme == 'http' and host not in LOOPBACK_HOSTS:
        raise ValueError('--endpoint must use https (plain http is only for localhost)')
    if parts.username or parts.password:
        raise ValueError('--endpoint must not carry a user name or password')
    if parts.query or parts.fragment:
        raise ValueError('--endpoint must not carry a query or fragment')
    path = parts.path.rstrip('/')
    if path in ('', '/v1'):
        path += '/chat/completions' if path else '/v1/chat/completions'
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, '', ''))


def build_parser():
    parser = argparse.ArgumentParser(
        prog='run_agent_scenarios.py', description=__doc__.split('\n\n')[0],
        epilog='Real-model runs are for the owner. Examples:\n'
               '  python scripts/run_agent_scenarios.py --fake\n'
               '  python scripts/run_agent_scenarios.py --endpoint https://<id>.ngrok-free.app/v1/chat/completions --out report.json\n\n'
               'Report: success rate (every check of a scenario holds), valid tool-call rate (a known tool with arguments that pass\n'
               'the schema; business refusals count as valid) and latency p50/p95 per customer turn. Only synthetic data in a\n'
               'temporary store is used; the only thing sent out in real mode is the conversations, to the endpoint you name.',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--endpoint', metavar='URL', help="the owner's model endpoint (OpenAI-compatible chat completions, "
                      'e.g. the Colab/vLLM tunnel); a base URL or one ending in /v1 is completed to /v1/chat/completions')
    mode.add_argument('--fake', action='store_true', help='scripted fake gateway: no model and no network (what CI runs)')
    parser.add_argument('--model', default=None, help=f'served model name (default: $RETAILOPS_API_MODEL, else {DEFAULT_MODEL})')
    parser.add_argument('--api-key-env', default='RETAILOPS_API_KEY', metavar='NAME',
                        help='environment variable holding the endpoint key, if it needs one (default: %(default)s)')
    parser.add_argument('--dataset', default=str(DEFAULT_DATASET), metavar='PATH',
                        help='scenario file (default: evals/agent_scenarios_w3_2.jsonl)')
    parser.add_argument('--only', nargs='+', metavar='ID', help='run only these scenario ids')
    parser.add_argument('--category', nargs='+', metavar='NAME', help='run only these categories')
    parser.add_argument('--out', metavar='PATH', help='write the full JSON report here')
    parser.add_argument('--min-success-rate', type=float, default=None, metavar='RATE',
                        help='exit 1 below this success rate (default: 1.0 with --fake, none with --endpoint)')
    parser.add_argument('--verbose', action='store_true', help='print every failed check as it happens')
    return parser


def _print_summary(report, out):
    s = report['summary']
    print('', file=out)
    print(f"mode: {report['mode']}  scenarios: {s['scenarios']}  turns: {s['turns']}", file=out)
    print(f"success rate:         {s['passed']}/{s['scenarios']} = {s['success_rate']}", file=out)
    print(f"valid tool-call rate: {s['valid_tool_calls']}/{s['tool_calls']} = {s['valid_tool_call_rate']}"
          f"  (repeated calls: {s['duplicate_tool_calls']})", file=out)
    lat = s['latency_ms']
    print(f"latency per turn:     p50 {lat['p50']} ms  p95 {lat['p95']} ms  max {lat['max']} ms", file=out)
    if s['model_error_turns']:
        print(f"turns that ended in an error: {s['model_error_turns']} {s['model_error_codes']}", file=out)
    for category, entry in sorted(report['by_category'].items()):
        print(f"  {category:<16} {entry['passed']}/{entry['scenarios']}", file=out)
    for record in report['scenarios']:
        if not record['passed']:
            print(f"FAIL {record['id']}", file=out)
            for failure in record['failures']:
                print(f'     - {failure}', file=out)


def main(argv=None, *, out=None):
    out = out or sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.fake and not args.endpoint:
        print(REFUSAL, file=sys.stderr)
        return 2
    try:
        endpoint = None if args.fake else normalize_endpoint(args.endpoint)
        scenarios = load_dataset(args.dataset)
    except (ValueError, AssertionError, OSError) as err:
        print(f'Không chạy được: {err}', file=sys.stderr)
        return 2
    if args.only:
        unknown = sorted(set(args.only) - {s['id'] for s in scenarios})
        if unknown:
            print(f'Không có kịch bản: {", ".join(unknown)}', file=sys.stderr)
            return 2
        scenarios = [s for s in scenarios if s['id'] in args.only]
    if args.category:
        scenarios = [s for s in scenarios if s['category'] in args.category]
    if not scenarios:
        print('Không có kịch bản nào để chạy.', file=sys.stderr)
        return 2

    def progress(index, total, record):
        seconds = sum(t['latency_ms'] for t in record['turns']) / 1000
        print(f"[{index:>2}/{total}] {'PASS' if record['passed'] else 'FAIL'} {record['id']} ({seconds:.1f}s)", file=out, flush=True)
        if args.verbose and not record['passed']:
            for failure in record['failures']:
                print(f'        - {failure}', file=out, flush=True)

    environment = {}
    if args.fake:
        mode, make_gateway = 'fake', ScriptedGateway
        model = {'gateway': 'scripted fake gateway'}
    else:
        mode = 'real'
        name = args.model or os.environ.get('RETAILOPS_API_MODEL') or DEFAULT_MODEL
        key = os.environ.get(args.api_key_env) or PLACEHOLDER_KEY
        environment['RETAILOPS_API_ENDPOINT'] = endpoint
        model = {'name': name, 'endpoint_host': urllib.parse.urlsplit(endpoint).netloc}

        def make_gateway():
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from retailops_providers import OpenRouterAgent
            return OpenRouterAgent(key, name)
    previous = {k: os.environ.get(k) for k in environment}
    os.environ.update(environment)
    try:
        report = run_suite(scenarios, make_gateway, mode, progress=progress)
    finally:
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    report['model'] = model
    report['dataset'] = {'path': Path(args.dataset).name, 'sha256': dataset_digest(args.dataset), 'scenarios': len(scenarios)}
    _print_summary(report, out)
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'Đã ghi báo cáo: {args.out}', file=out)
    threshold = args.min_success_rate if args.min_success_rate is not None else (1.0 if args.fake else None)
    if threshold is not None and (report['summary']['success_rate'] or 0) < threshold:
        return 1
    return 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    sys.exit(main())
