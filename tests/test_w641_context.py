import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_py(code: str, env_override: dict[str, str] | None = None, *, remove_context_env: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if remove_context_env:
        env.pop('RETAILOPS_MODEL_CONTEXT_TOKENS', None)
    if env_override:
        env.update(env_override)
    env['PYTHONUTF8'] = '1'
    existing_pp = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = f"{ROOT}{os.pathsep}{existing_pp}" if existing_pp else str(ROOT)
    return subprocess.run(
        [sys.executable, '-c', code],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )


class W641ContextBudgetTests(unittest.TestCase):
    def test_context_tokens_env_values_in_fresh_subprocesses(self):
        cases = [
            (None, [16384, 36000, 5200]),
            ('16384', [16384, 36000, 5200]),
            ('32768', [32768, 72000, 10400]),
            ('8192', [8192, 18000, 2600]),
        ]
        code = (
            "import json, agent_protocol; "
            "from retailops.workflow import compaction; "
            "print(json.dumps([agent_protocol.CONTEXT_TOKENS, agent_protocol.MAX_CHARACTERS, compaction.TOOL_RESULT_MAX_CHARS]))"
        )
        for env_val, expected in cases:
            with self.subTest(RETAILOPS_MODEL_CONTEXT_TOKENS=env_val):
                override = {'RETAILOPS_MODEL_CONTEXT_TOKENS': env_val} if env_val is not None else None
                proc = _run_py(code, override)
                self.assertEqual(proc.returncode, 0, msg=proc.stderr)
                self.assertEqual(json.loads(proc.stdout.strip()), expected)

    def test_invalid_context_tokens_rejected_on_import(self):
        for bad_val in ('2048', '200000'):
            with self.subTest(RETAILOPS_MODEL_CONTEXT_TOKENS=bad_val):
                proc = _run_py("import agent_protocol", {'RETAILOPS_MODEL_CONTEXT_TOKENS': bad_val})
                self.assertNotEqual(proc.returncode, 0)
                combined = proc.stdout + proc.stderr
                self.assertIn('RETAILOPS_MODEL_CONTEXT_TOKENS', combined)

    def test_separate_module_imports_have_no_circular_import(self):
        for mod in ('agent_protocol', 'retailops.workflow.compaction', 'retailops.workflow.agent'):
            with self.subTest(module=mod):
                proc = _run_py(f"import {mod}")
                self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_runner_import_order_updates_runtime_max_characters(self):
        code = (
            "import os, json, retailops_providers, agent_protocol; "
            "os.environ['RETAILOPS_MODEL_CONTEXT_TOKENS'] = '32768'; "
            "from retailops.workflow import compaction; "
            "print(json.dumps([agent_protocol.max_characters(), compaction.TOOL_RESULT_MAX_CHARS]))"
        )
        proc = _run_py(code)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(json.loads(proc.stdout.strip()), [72000, 10400])

    def test_real_runner_fake_32k_passes_71800_limit_to_fit_transcript(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / 'out_32k.json'
            code = "\n".join([
                "import io, json",
                "from scripts import run_agent_scenarios as runner",
                "from retailops.workflow import agent as agent_mod",
                "seen = []",
                "orig = agent_mod.fit_transcript",
                "def wrapped(messages, limit):",
                "    seen.append(limit)",
                "    return orig(messages, limit)",
                "agent_mod.fit_transcript = wrapped",
                f"rc = runner.main(['--fake', '--context-tokens', '32768', '--only', 'lookup_all_orders', '--out', {str(out_path)!r}], out=io.StringIO())",
                "print(json.dumps({'rc': rc, 'seen': seen}))",
            ])
            proc = _run_py(code)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr + '\n' + proc.stdout)
            payload = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertEqual(payload['rc'], 0)
            self.assertTrue(payload['seen'], 'fit_transcript was never called')
            self.assertTrue(all(lim == 72000 - 200 for lim in payload['seen']), payload['seen'])
            self.assertTrue(out_path.exists())


if __name__ == '__main__':
    unittest.main()
