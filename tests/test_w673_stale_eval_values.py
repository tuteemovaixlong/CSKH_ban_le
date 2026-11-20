"""Bổ sung G: loại vết theo ca và phòng thủ giá trị giả trong mọi tin của mẫu."""
import contextlib
import copy
import io
import json
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / 'scripts/sft_select.py').is_file():
    raise unittest.SkipTest('Công cụ SFT không nằm trong gói Colab ứng dụng')

from scripts import sft_build as build, sft_select as select, sft_eval_values as values
from tests.test_w670_sft_select_build import _make_turn_trace, _build_synthetic_workspace
from tests import test_w671_sft_no_eval_values as fixture_check

BASE = '0f21789f1a37dd99d38dc31d46fd3e930e6c3c85'


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def write_lines(path, rows):
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')


def baseline(name):
    source = subprocess.check_output(['git', 'show', f'{BASE}:scripts/{name}.py'], cwd=ROOT).decode('utf-8')
    mod = types.ModuleType('before_g_' + name)
    mod.__file__ = str(ROOT / 'scripts' / f'{name}.py')
    exec(compile(source, mod.__file__, 'exec'), mod.__dict__)
    return mod


def staff_fixture(root):
    cases, records, traces = [], [], []
    for n in (1, 2):
        cid = f't11_{n:03d}_kiem_dau_vao'
        setup = {'customer_messages': [{'text': chr(65 + n), 'attachment':
                  {'kind': 'text_pdf', 'pages': [chr(70 + n)]}}]}
        case = {'id': cid, 'actor': 'staff_case_assist',
                'meta': {'template': 't11_pdf_email_la', 'suite': 'T11'},
                'case_setup': copy.deepcopy(setup),
                'turns': [{'mode': 'draft', 'user': chr(85), 'expect': {}}]}
        records.append({'id': cid, 'run': 1, 'passed': True, 'failures': [],
                        'case_setup': copy.deepcopy(setup),
                        'turns': [{'user': chr(85), 'answer': chr(82), 'tools': [], 'model_calls': 1}]})
        traces.extend(_make_turn_trace(cid, 1, 1, user_text=chr(85), final_content=chr(82), final_reasoning=''))
        case['case_setup']['customer_messages'][0]['attachment']['pages'] = [chr(80 + n)]
        cases.append(case)
    write_lines(root / 'cases', cases)
    for folder in ('old', 'fresh'):
        directory = root / folder
        directory.mkdir()
        write_json(directory / 'merged.json', {'scenarios': records})
        write_lines(directory / 'shard-00.jsonl', traces)
    return cases


class ExcludeCasesTests(unittest.TestCase):
    def test_case_setup_changed_same_user_excluded_only_for_specified_runs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = staff_fixture(root)
            cid, other = (c['id'] for c in cases)
            (root / 'ids').write_text('\n' + cid + '\n\n', encoding='utf-8-sig')
            old_setup = json.loads((root / 'old/merged.json').read_text(encoding='utf-8'))['scenarios'][0]
            self.assertEqual(cases[0]['turns'][0]['user'], old_setup['turns'][0]['user'])
            self.assertNotEqual(cases[0]['case_setup'], old_setup['case_setup'])
            specs = [dict(label=label, model='qwen', dir=str(root / directory),
                          run_offset=offset, hinted=False, hint_log=None)
                     for label, directory, offset in (('v3', 'old', 0), ('v5', 'fresh', 4))]
            unfiltered = select.score_runs(root / 'cases', {}, runs=specs)
            self.assertEqual([c['run'] for c in unfiltered['cases'][cid]['candidates']], [1, 5])
            select._write_json(root / 'unfiltered', unfiltered)
            before = (root / 'unfiltered').read_bytes()
            old_select = baseline('sft_select')
            old_select._write_json(root / 'unfiltered', old_select.score_runs(root / 'cases', {}, runs=specs))
            self.assertEqual(before, (root / 'unfiltered').read_bytes())
            specs[0]['exclude_cases'] = str(root / 'ids')
            filtered = select.score_runs(root / 'cases', {}, runs=specs)
            self.assertEqual([c['run'] for c in filtered['cases'][cid]['candidates']], [5])
            rejected = filtered['cases'][cid]['rejected']
            self.assertEqual([(c['run'], c['reject_reasons']) for c in rejected], [(1, ['stale_input'])])
            self.assertEqual(filtered['cases'][other], unfiltered['cases'][other])

    def test_legacy_cli_exclusions_apply_to_every_model_and_no_flag_keeps_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = staff_fixture(root)
            cid, other = (c['id'] for c in cases)
            (root / 'ids').write_text(cid + '\n', encoding='utf-8')
            args = ['score', '--cases', str(root / 'cases'), '--run-dir', f'qwen={root / "old"}',
                    '--run-dir', f'deepseek={root / "fresh"}', '--out', str(root / 'scores')]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(select.main(args), 0)
            before = (root / 'scores').read_bytes()
            old = baseline('sft_select')
            old._write_json(root / 'scores', old.score_runs(root / 'cases', {'qwen': root / 'old', 'deepseek': root / 'fresh'}))
            self.assertEqual(before, (root / 'scores').read_bytes())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(select.main(args + ['--exclude-cases', str(root / 'ids')]), 0)
            result = json.loads((root / 'scores').read_text(encoding='utf-8'))['cases']
            self.assertFalse(result[cid]['candidates'])
            self.assertEqual({c['model'] for c in result[cid]['rejected']}, {'qwen', 'deepseek'})
            self.assertTrue(all('stale_input' in c['reject_reasons'] for c in result[cid]['rejected']))
            self.assertEqual(len(result[other]['candidates']), 2)


class EvalValueBuildTests(unittest.TestCase):
    def test_shared_extractor_is_the_existing_fixture_checker(self):
        self.assertIs(fixture_check.VALUE_RE, values.VALUE_RE)
        self.assertIs(fixture_check.eval_values, values.eval_values)
        self.assertIs(fixture_check.strings, values.strings)

    def test_all_message_fields_including_tool_results_and_reasoning_are_rejected(self):
        # Chỉ đọc giá trị từ nguồn bộ đo dùng chung; không chép giá trị nào vào ca/phiếu T14.
        value = next(v for v in sorted(values.eval_values()) if '@' in v and 'retailops-mail.com' in v)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cid = 't11_001_phong_thu'
            case = {'id': cid, 'meta': {'template': 't11_pdf_email_la', 'suite': 'T11'},
                    'actor': 'staff_case_assist', 'turns': [{'mode': 'draft', 'user': chr(85), 'expect': {}}]}
            write_lines(root / 'cases', [case])
            directory = root / 'run'
            directory.mkdir()
            write_json(directory / 'merged.json', {'scenarios': [dict(id=cid, run=1, passed=True, failures=[],
                       turns=[dict(user=chr(85), answer=chr(82), tools=[], model_calls=2)])]})
            traces = _make_turn_trace(cid, 1, 1, user_text=chr(85), steps=[{
                'content': chr(72), 'reasoning': chr(73),
                'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'SIM-O-59999'}}],
                'tool_results': [json.dumps({'ok': True})],
            }], final_content=chr(82), final_reasoning=chr(83))
            write_lines(directory / 'shard-00.jsonl', traces)
            scores = select.score_runs(root / 'cases', {'qwen': directory})
            entry = scores['cases'][cid]
            candidate = entry['candidates'][0]
            selection = select._make_selection_entry(entry, candidate, scores, tier='A', role='primary', rule=None)
            write_json(root / 'selection', {'selected': [selection]})
            good = build.build_sft_dataset(root / 'selection', root / 'cases', root / 'good')
            self.assertEqual(good['samples']['total'], 1)
            for location in ('system', 'user', 'tool', 'history', 'history_reasoning', 'answer', 'reasoning'):
                with self.subTest(location=location):
                    dirty = copy.deepcopy(traces)
                    last = dirty[-1]
                    if location in ('system', 'user', 'tool'):
                        message = next(m for m in last['request']['messages'] if m['role'] == location)
                        message['content'] += value
                    elif location in ('history', 'history_reasoning'):
                        message = next(m for m in last['request']['messages'] if m['role'] == 'assistant')
                        message['content' if location == 'history' else 'reasoning'] += value
                    else:
                        last['response']['content' if location == 'answer' else 'reasoning'] += value
                    write_lines(directory / 'shard-00.jsonl', dirty)
                    output = root / location
                    stats = build.build_sft_dataset(root / 'selection', root / 'cases', output)
                    self.assertEqual(stats['samples']['total'], 0)
                    self.assertEqual(stats['rejected']['by_reason'], {'eval_value': 1})
                    self.assertIn(value, stats['rejected']['items'][0]['eval_values'])
                    self.assertEqual(stats['rejected']['items'][0]['case_id'], cid)
                    self.assertIn(value, (output / 'build_report.md').read_text(encoding='utf-8'))
                    self.assertIn('eval_value', (output / 'build_report.md').read_text(encoding='utf-8'))
                    self.assertEqual((output / 'train.jsonl').read_bytes(), b'')

    def test_old_synthetic_build_outputs_are_identical_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = _build_synthetic_workspace(root)
            scores = select.score_runs(fixture['cases_path'], {'qwen': fixture['qwen_dir'], 'deepseek': fixture['ds_dir']})
            selected = [select._make_selection_entry(entry, entry['candidates'][0], scores, tier='A', role='primary', rule=None)
                        for entry in scores['cases'].values() if entry['candidates']]
            write_json(root / 'selection', {'selected': selected})
            old = baseline('sft_build')
            old.build_sft_dataset(root / 'selection', fixture['cases_path'], root / 'built')
            before = {p.name: p.read_bytes() for p in (root / 'built').iterdir()}
            build.build_sft_dataset(root / 'selection', fixture['cases_path'], root / 'built')
            self.assertEqual(before, {p.name: p.read_bytes() for p in (root / 'built').iterdir()})


if __name__ == '__main__':
    unittest.main()
