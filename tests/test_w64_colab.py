"""W6.4.0 row 5: pure Colab command/resume planning; never starts Colab or a model."""
import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

if not (Path(__file__).resolve().parents[1] / '.github/workflows/ci.yml').exists():
    raise unittest.SkipTest('Colab evaluation source is not shipped in the standalone agent bundle')

from notebooks import colab_eval_w64 as colab


class ColabPlanTests(unittest.TestCase):
    def test_vllm_flags_across_context_gpu_and_mtp(self):
        for context in (16384, 8192):
            for gb in (24, 96):
                for mtp in (True, False):
                    with self.subTest(context=context, gb=gb, mtp=mtp):
                        cmd = colab.build_vllm_command('/model', context, gb, mtp=mtp, max_num_seqs=4)
                        self.assertEqual(cmd[:3], ['vllm', 'serve', '/model'])
                        for flag, value in {'--max-model-len': str(context), '--host': '127.0.0.1',
                                            '--served-model-name': 'Qwen/Qwen3.5-9B', '--reasoning-parser': 'qwen3',
                                            '--tool-call-parser': 'qwen3_coder', '--max-num-seqs': '4'}.items():
                            self.assertEqual(cmd[cmd.index(flag) + 1], value)
                        self.assertIn('--enable-auto-tool-choice', cmd)
                        self.assertEqual('--quantization' in cmd, gb < 40)
                        self.assertEqual('--speculative-config' in cmd, mtp)
                        if mtp:
                            self.assertEqual(json.loads(cmd[cmd.index('--speculative-config') + 1]),
                                             {'method': 'qwen3_next_mtp', 'num_speculative_tokens': 2})

    def test_shards_are_deterministic_disjoint_and_cover_every_case(self):
        ids = [f'case-{i}' for i in range(250)]
        shards = colab.shard_case_ids(ids, 12)
        self.assertEqual(shards, colab.shard_case_ids(list(reversed(ids)), 12))
        self.assertEqual(sorted(x for shard in shards for x in shard), sorted(ids))
        self.assertLessEqual(max(map(len, shards)) - min(map(len, shards)), 1)
        with self.assertRaises(ValueError):
            colab.shard_case_ids(['x', 'x'], 2)

    def test_runner_command_contains_sampling_trace_and_real_knowledge(self):
        cmd = colab.runner_command('/venv/bin/python', 'ids.txt', 'report.json', 'trace.jsonl',
                                    ['--dataset-dir', 'evals/suites'], context_tokens=8192, max_tokens=4096)
        for flag, value in {'--thinking': 'on', '--context-tokens': '8192', '--temperature': '1.0',
                            '--top-p': '0.95', '--top-k': '20', '--presence-penalty': '1.5',
                            '--max-tokens': '4096', '--trace-out': 'trace.jsonl', '--knowledge': 'real',
                            '--only-file': 'ids.txt'}.items():
            self.assertEqual(cmd[cmd.index(flag) + 1], value)
        self.assertNotIn('--fake', cmd)

    def test_completed_failure_is_skipped_but_partial_report_is_not(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'shard.json'
            self.assertFalse(colab.report_complete(p, ['x'], 2))
            p.write_text('{', encoding='utf-8')
            self.assertFalse(colab.report_complete(p, ['x'], 2))
            report = {'provenance': {'git_sha': 'a' * 40},
                      'scenarios': [{'id': 'x', 'run': 1, 'passed': False}, {'id': 'x', 'run': 2, 'passed': True}]}
            p.write_text(json.dumps(report), encoding='utf-8')
            self.assertTrue(colab.report_complete(p, ['x'], 2))
            self.assertFalse(colab.report_complete(p, ['x', 'y'], 2))

    def test_clone_is_pinned_and_requirements_are_hash_checked(self):
        commands = colab.clone_commands('/repo', 'a' * 40)
        self.assertIn(['git', '-C', '/repo', 'checkout', '--detach', 'a' * 40], commands)
        with self.assertRaises(ValueError):
            colab.clone_commands('/repo', 'main')
        cmd = colab.requirements_command('/venv/bin/python', '/repo')
        self.assertIn('--require-hashes', cmd)
        self.assertIn('/repo/requirements-web.txt', cmd)
        self.assertIn('/repo/requirements-postgres.txt', cmd)

    def test_import_is_passive_and_processes_are_isolated(self):
        source = Path(colab.__file__).read_text(encoding='utf-8')
        ast.parse(source)
        self.assertIn('start_new_session=True', source)
        self.assertIn('require_disposable_postgres_test_target', source)
        self.assertIn('SIGTERM', source)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'print':
                rendered = ast.unparse(node)
                self.assertNotIn('API_KEY', rendered)
                self.assertNotIn('DATABASE_URL', rendered)

    def test_scheduler_bounds_processes_and_skips_completed_shards(self):
        running, peak, started = [], [], set()
        jobs = [(['x'], Path(f'{i}.json'), Path(f'{i}.jsonl'), [str(i)], 1) for i in range(5)]
        def complete(path, ids, repeat):
            return path.stem == '0' or path.stem in started
        def launch(command, **kwargs):
            self.assertTrue(kwargs['start_new_session'])
            started.add(command[0])
            class Process:
                def poll(self):
                    running.remove(self)
                    return 0
            p = Process()
            running.append(p)
            peak.append(len(running))
            return p
        with patch.object(colab, 'report_complete', side_effect=complete), \
                patch.object(colab.subprocess, 'Popen', side_effect=launch), patch.object(colab, 'CHILDREN', []):
            result = colab.run_shards(jobs, 2, repo='/repo', env={})
        self.assertEqual(result.count('skipped'), 1)
        self.assertEqual(result.count('done'), 4)
        self.assertEqual(max(peak), 2)

    def test_interrupted_scheduler_stops_its_children(self):
        class Process:
            def poll(self):
                raise KeyboardInterrupt()
        p = Process()
        with patch.object(colab, 'report_complete', return_value=False), \
                patch.object(colab.subprocess, 'Popen', return_value=p), patch.object(colab, 'CHILDREN', []), \
                patch.object(colab, 'stop_process') as stop:
            with self.assertRaises(KeyboardInterrupt):
                colab.run_shards([(['x'], Path('r'), Path('t'), ['cmd'], 1)], 1, repo='/repo', env={})
            stop.assert_called_once_with(p)


class ColabDiagnosticsTests(unittest.TestCase):
    """Claude's W6.4.0 follow-up: failures explain themselves and MTP speed is recorded, without leaking secrets."""

    SECRET = 'k' * 24

    def test_redacted_tail_keeps_the_last_lines_only(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / 'vllm.log'
            log.write_text('\n'.join([f'line {i}' for i in range(100)] + [f'key={self.SECRET}']) + '\n',
                           encoding='utf-8')
            tail = colab.log_tail(log, (self.SECRET,), lines=5)
        self.assertEqual(tail.splitlines(), ['line 96', 'line 97', 'line 98', 'line 99', 'key=[REDACTED]'])
        self.assertEqual(colab.log_tail(Path(td) / 'missing.log', ()), '')

    def test_failed_setup_step_shows_its_redacted_output(self):
        script = f'import sys; print("E: Unable to locate package python3.12"); print("pw={self.SECRET}"); sys.exit(3)'
        with self.assertRaises(RuntimeError) as caught:
            colab.quiet([sys.executable, '-c', script], secrets=(self.SECRET,))
        message = str(caught.exception)
        self.assertIn('exit 3', message)
        self.assertIn('Unable to locate package python3.12', message)
        self.assertIn('pw=[REDACTED]', message)
        self.assertNotIn(self.SECRET, message)
        with self.assertRaises(RuntimeError) as caught:
            colab.quiet([sys.executable, '-c', 'import sys; print(sys.stdin.read()); sys.exit(1)'],
                        input=f"CREATE ROLE x PASSWORD '{self.SECRET}';", text=True, secrets=(self.SECRET,))
        self.assertNotIn(self.SECRET, str(caught.exception))
        colab.quiet([sys.executable, '-c', 'print("fine")'])

    def test_vllm_output_goes_to_a_local_log_and_the_key_stays_in_its_environment(self):
        with tempfile.TemporaryDirectory() as td, patch.object(colab.subprocess, 'Popen') as popen, \
                patch.object(colab, 'CHILDREN', []):
            log = Path(td) / 'vllm.log'
            colab.start_server(['vllm', 'serve', '/model'], self.SECRET, log)
            kwargs = popen.call_args.kwargs
            self.assertNotIn(self.SECRET, ' '.join(popen.call_args.args[0]))
            self.assertEqual(kwargs['env']['VLLM_API_KEY'], self.SECRET)
            self.assertNotEqual(kwargs['stdout'], colab.subprocess.DEVNULL)
            self.assertEqual(kwargs['stderr'], colab.subprocess.STDOUT)
            self.assertTrue(kwargs['start_new_session'])
            self.assertTrue(log.exists())

    def test_spec_decode_counters_give_acceptance_rate_length_and_throughput(self):
        def page(drafts, draft_tokens, accepted, generated):
            labels = '{engine="0",model_name="Qwen/Qwen3.5-9B"}'
            return '\n'.join([
                '# HELP vllm:spec_decode_num_drafts_total Number of spec decoding drafts.',
                '# TYPE vllm:spec_decode_num_drafts_total counter',
                f'vllm:spec_decode_num_drafts_total{labels} {drafts}',
                f'vllm:spec_decode_num_drafts_created{labels} 1.7e9',
                f'vllm:spec_decode_num_draft_tokens_total{labels} {draft_tokens}',
                f'vllm:spec_decode_num_accepted_tokens_total{labels} {accepted}',
                f'vllm:spec_decode_num_accepted_tokens_per_pos_total{{engine="0",position="0"}} {accepted}',
                f'vllm:generation_tokens_total{labels} {generated}',
                'process_cpu_seconds_total 12.0'])
        before = colab.parse_metrics(page(10.0, 20.0, 15.0, 100.0))
        after = colab.parse_metrics(page(110.0, 220.0, 165.0, 1100.0))
        self.assertEqual(after['vllm:spec_decode_num_drafts'], 110.0)
        self.assertNotIn('vllm:spec_decode_num_drafts_created', after)
        summary = colab.metrics_delta(before, after, seconds=50.0)
        self.assertAlmostEqual(summary['draft_acceptance_rate'], 0.75)
        self.assertAlmostEqual(summary['mean_acceptance_length'], 2.5)
        self.assertAlmostEqual(summary['generation_tokens_per_second'], 20.0)
        no_mtp = colab.metrics_delta({}, colab.parse_metrics('vllm:generation_tokens_total 40'), seconds=4.0)
        self.assertIsNone(no_mtp['draft_acceptance_rate'])
        self.assertIsNone(no_mtp['mean_acceptance_length'])
        self.assertEqual(no_mtp['generation_tokens_per_second'], 10.0)

    def test_shard_logs_are_saved_redacted_and_a_failure_shows_its_tail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ok_report, bad_report = root / 'shard-000.json', root / 'shard-001.json'
            jobs = [(['a'], ok_report, root / 'shard-000.jsonl',
                     [sys.executable, '-c', f'print("ran with {self.SECRET}")'], 1),
                    (['b'], bad_report, root / 'shard-001.jsonl',
                     [sys.executable, '-c', 'import sys; print("Traceback: boom"); sys.exit(2)'], 1)]
            finished = set()
            def complete(path, ids, repeat):
                return path == ok_report and path in finished
            real_popen = colab.subprocess.Popen
            def launch(command, **kwargs):
                process = real_popen(command, **kwargs)
                process.wait()
                finished.add(ok_report if 'ran with' in command[-1] else bad_report)
                return process
            with patch.object(colab, 'report_complete', side_effect=complete), \
                    patch.object(colab.subprocess, 'Popen', side_effect=launch), \
                    patch.object(colab, 'CHILDREN', []), patch.object(colab, 'stop_process'):
                with self.assertRaises(RuntimeError) as caught:
                    colab.run_shards(jobs, 1, repo=td, env=None, log_dir=root / 'local', secrets=(self.SECRET,))
            self.assertIn('shard-001', str(caught.exception))
            self.assertIn('Traceback: boom', str(caught.exception))
            saved = ok_report.with_suffix('.log').read_text(encoding='utf-8')
            self.assertIn('ran with [REDACTED]', saved)
            self.assertNotIn(self.SECRET, saved)
            self.assertIn('Traceback: boom', bad_report.with_suffix('.log').read_text(encoding='utf-8'))


class ColabDatabaseTests(unittest.TestCase):
    def test_disposable_database_gets_pgvector_in_the_extensions_schema(self):
        calls = []
        with patch.object(colab, 'quiet', side_effect=lambda cmd, **kw: calls.append((cmd, kw))):
            colab.provision_database('/venv/bin/python', '/repo', {}, 'a' * 64)
        sql = ''.join(kw.get('input') or '' for _, kw in calls)
        self.assertIn('SUPERUSER', sql)
        self.assertNotIn('CREATE EXTENSION', sql)
        prepare = [kw for cmd, kw in calls if cmd == ['/venv/bin/python', 'scripts/prepare_test_pgvector.py']]
        self.assertEqual(len(prepare), 1)
        self.assertEqual(prepare[0].get('cwd'), '/repo')
        self.assertEqual(prepare[0].get('secrets'), ('a' * 64,))
