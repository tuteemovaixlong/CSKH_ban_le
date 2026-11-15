"""W6.4.0 row 5: pure Colab command/resume planning; never starts Colab or a model."""
import ast
import json
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
