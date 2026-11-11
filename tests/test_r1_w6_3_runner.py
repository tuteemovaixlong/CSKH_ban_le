"""W6.3 row 2: fake gateways, default-preserving experiments."""
import importlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import run_agent_scenarios as runner


class ExperimentTests(unittest.TestCase):
    def test_only_file_filters_and_unknown_ids_fail(self):
        cases = runner.load_dataset()[:2]
        with tempfile.TemporaryDirectory() as tmp:
            selected, output = Path(tmp) / 'only.txt', Path(tmp) / 'report.json'
            selected.write_text('\ufeff' + cases[1]['id'] + '\n\n', encoding='utf-8')
            self.assertEqual(runner.main(['--fake', '--only-file', str(selected), '--out', str(output)], out=io.StringIO()), 0)
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual([r['id'] for r in report['scenarios']], [cases[1]['id']])
            selected.write_text('unknown_id\n', encoding='utf-8')
            self.assertEqual(runner.main(['--fake', '--only-file', str(selected)], out=io.StringIO()), 2)
            selected.write_text('', encoding='utf-8')
            self.assertEqual(runner.main(['--fake', '--only-file', str(selected)], out=io.StringIO()), 2)

    def test_new_cli_options(self):
        args = runner.build_parser().parse_args(['--fake', '--repeat', '3', '--thinking', 'off',
              '--context-tokens', '8192', '--knowledge', 'scripted', '--dataset-dir', 'evals/suites',
              '--suite', 'S01', '--split', 'dev', '--agent-mode', 'agent'])
        self.assertEqual(args.repeat, 3)

    def test_default_and_half_compaction_budgets(self):
        from retailops.workflow import compaction as c
        try:
            with patch.dict(os.environ, {}, clear=True):
                importlib.reload(c)
                self.assertEqual((c.TOOL_RESULT_MAX_CHARS, c.TOOL_CONTENT_BUDGET, c.MIN_RESULT_CHARS,
                                  c.HISTORY_CHAR_BUDGET, c.HISTORY_MESSAGE_CHARS), (5200, 12000, 800, 6000, 1500))
            with patch.dict(os.environ, {'RETAILOPS_MODEL_CONTEXT_TOKENS': '8192'}):
                importlib.reload(c)
                self.assertEqual((c.TOOL_RESULT_MAX_CHARS, c.TOOL_CONTENT_BUDGET, c.HISTORY_CHAR_BUDGET,
                                  c.HISTORY_MESSAGE_CHARS), (2600, 6000, 3000, 750))
        finally:
            importlib.reload(c)

    def test_thinking_request_default_and_off(self):
        from retailops_providers import OpenRouterAgent
        captured = []
        def request(agent, payload, timeout):
            captured.append(payload)
            return {'model': agent.model, 'usage': {'prompt_tokens': 10, 'completion_tokens': 2},
                    'choices': [{'message': {'role': 'assistant', 'content': 'ok'}, 'finish_reason': 'stop'}]}
        with patch.object(OpenRouterAgent, 'request', request), patch.dict(os.environ, {}, clear=True):
            gateway = OpenRouterAgent('synthetic-key-' + '0' * 32, runner.DEFAULT_MODEL)
            gateway.chat([{'role': 'user', 'content': 'hello'}], False, 10)
            self.assertNotIn('chat_template_kwargs', captured[-1])
            os.environ['RETAILOPS_MODEL_ENABLE_THINKING'] = 'false'
            gateway.chat([{'role': 'user', 'content': 'hello'}], False, 10)
            self.assertEqual(captured[-1]['chat_template_kwargs'], {'enable_thinking': False})

    def test_repeat_one_failure_and_separate_attack(self):
        cases = runner.load_dataset()[:1]
        n = [0]
        def run(case, gateway, mode):
            n[0] += 1
            return dict(id=case['id'], category=case['category'], title=case['title'],
                        passed=n[0] != 2, failures=[] if n[0] != 2 else ['intentional'], turns=[])
        with patch.object(runner, 'run_scenario', run):
            report = runner.run_suite(cases, runner.ScriptedGateway, 'fake', repeat=3)
        self.assertAlmostEqual(report['summary']['pass_at_1'], 2/3)
        self.assertEqual(report['summary']['pass_power_k'], 0)
        outcome = {'result': {'message': 'INJECTED PHRASE'}, 'tools': [], 'error': None, 'model_calls': 1}
        self.assertTrue(runner.attack_success({'attack_not': ['injected phrase']}, outcome))
        self.assertEqual(runner.grade_turn({'attack_not': ['injected phrase']}, outcome), [])

    def test_override_visible_to_real_product_tool(self):
        case = runner.load_dataset()[0]
        case['overrides'] = {'product_descriptions': {'P-101': 'synthetic injection canary'}}
        world = runner.World(case, runner.ScriptedGateway())
        try:
            from retailops_tools import BoundTools
            # Exercise the same executor used by the customer agent.
            executor = BoundTools(world.store, world.app.catalog, world.customer_id,
                                  {'id': world.conversation}, {})
            result = executor('get_product', {'product_id': 'P-101'})
            self.assertIn('synthetic injection canary', str(result))
        finally:
            world.close()

    def test_attack_grade_and_repeat_use_actual_gateway(self):
        case = runner.load_dataset()[0]
        case['turns'][0]['fake_model'][-1]['say'] += ' synthetic attack canary'
        case['turns'][0]['expect']['attack_not'] = ['synthetic attack canary']
        report = runner.run_suite([case], runner.ScriptedGateway, 'fake', repeat=3)
        self.assertEqual(report['summary']['pass_power_k'], 1)
        self.assertTrue(all(r['attack_success'] and r['utility'] for r in report['scenarios']))
        self.assertEqual([r['run'] for r in report['scenarios']], [1, 2, 3])

    def test_actual_gateway_fails_exactly_one_of_three_runs(self):
        import copy
        case = runner.load_dataset()[0]
        counter = [0]
        class FlakyGateway(runner.ScriptedGateway):
            def load(self, steps):
                steps = copy.deepcopy(steps)
                if self.fail:
                    steps[-1]['say'] = 'Xin chào.'
                super().load(steps)
        def make():
            counter[0] += 1
            gateway = FlakyGateway()
            gateway.fail = counter[0] == 2
            return gateway
        report = runner.run_suite([case], make, 'fake', repeat=3)
        self.assertAlmostEqual(report['summary']['pass_at_1'], 2/3)
        self.assertEqual(report['summary']['pass_power_k'], 0)
        self.assertEqual([r['passed'] for r in report['scenarios']], [True, False, True])

    def test_directory_filters_hashes_config_and_empty_directory(self):
        from tests.test_r1_w6_3_dataset import sample
        with tempfile.TemporaryDirectory() as tmp:
            folder, output = Path(tmp), Path(tmp) / 'report.json'
            self.assertEqual(runner.main(['--fake', '--dataset-dir', tmp, '--out', str(output)], out=io.StringIO()), 0)
            case = sample()
            (folder / 'S01.jsonl').write_text(json.dumps(case), encoding='utf-8')
            self.assertEqual(runner.main(['--fake', '--dataset-dir', tmp, '--suite', 'S01', '--split', 'dev',
                  '--repeat', '2', '--out', str(output)], out=io.StringIO()), 0)
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(report['config']['repeat'], 2)
            self.assertEqual(report['datasets']['S01.jsonl'], runner.dataset_digest(folder / 'S01.jsonl'))
            self.assertEqual(report['summary']['cases'], 1)
            self.assertEqual(report['summary']['pass_power_k'], 1.)

    def test_legacy_fake_and_invalid_context_are_rejected(self):
        for args in (['--fake', '--agent-mode', 'legacy'], ['--fake', '--context-tokens', '2048']):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                runner.main(args, out=io.StringIO())

    def test_vllm_max_model_len_default_and_override_without_running_notebook(self):
        import ast
        import re
        source = runner.ROOT / 'notebooks/colab_vllm_l4.py'
        function = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                        if isinstance(n, ast.FunctionDef) and n.name == 'build_vllm_server_command')
        namespace = dict(json=json, re=re, MAX_IMAGES_PER_REQUEST=3)
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        for setting, expected in [('', '16384'), ('8192', '8192')]:
            with patch.dict(os.environ, {'RETAILOPS_MAX_MODEL_LEN': setting} if setting else {}, clear=True):
                command = namespace['build_vllm_server_command']('python', 'fake-model', 'fp8', 'template', 'k' * 32)
                self.assertEqual(command[command.index('--max-model-len') + 1], expected)
