"""Isolated unit tests for Phase R1 W2: operational hygiene, Business v5 migration, case lifecycle, timers, resume, and feedback."""
import ast
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import urllib.parse

from retailops.core import ROOT


def _load_colab_ngrok_helper(rel_path: str):
    source = (ROOT / rel_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=rel_path)
    fn_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "open_colab_ngrok_tunnel"
    )
    mod = ast.Module(body=[fn_node], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns = {"urllib": SimpleNamespace(parse=urllib.parse)}
    exec(compile(mod, rel_path, "exec"), ns)
    return ns["open_colab_ngrok_tunnel"], source


class PhaseR1W2Item0HygieneTests(unittest.TestCase):
    def test_update_ec2_refuses_execution_writes_nothing_and_has_no_patch_or_constraint_mutations(self):
        script_path = ROOT / "scripts" / "update_ec2.py"
        script_src = script_path.read_text(encoding="utf-8")
        self.assertNotIn("/opt/retailops/patches", script_src)
        self.assertNotIn("ALTER TABLE", script_src)
        self.assertNotIn("memberships_role_check", script_src)
        self.assertNotIn("subprocess", script_src)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            for extra_args in ([], ["--auto-ip"], ["--api-endpoint", "https://example.ngrok-free.app/v1/chat/completions"]):
                proc = subprocess.run(
                    [sys.executable, str(script_path), *extra_args],
                    cwd=tmp_dir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=10,
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(list(tmp_dir.iterdir()), [])
                combined = proc.stdout + proc.stderr
                self.assertIn("RETAILOPS_API_ENDPOINT", combined)
                self.assertIn("api.env", combined)
                self.assertIn("--force-recreate web", combined)
                self.assertIn("migrate-v5", combined)

    def test_colab_launchers_remove_update_ec2_and_enforce_static_ngrok_domain_rules(self):
        for rel_path in ("notebooks/colab_vllm_l4.py", "notebooks/colab_llama_server_gguf.py"):
            with self.subTest(notebook=rel_path):
                helper, src = _load_colab_ngrok_helper(rel_path)
                self.assertNotIn("update_ec2.py", src)
                self.assertIn("RETAILOPS_API_ENDPOINT", src)
                self.assertIn("--force-recreate web", src)
                self.assertIn("NGROK_DOMAIN", src)

                class _FakeNgrok:
                    def __init__(self, behavior):
                        self.behavior = behavior
                        self.auth_tokens_seen = []
                        self.connect_calls = []
                        self.disconnected = []

                    def get_tunnels(self):
                        return [SimpleNamespace(public_url="https://old.ngrok-free.app")]

                    def disconnect(self, url):
                        self.disconnected.append(url)

                    def set_auth_token(self, tok):
                        self.auth_tokens_seen.append(tok)

                    def connect(self, port, proto="http", **kwargs):
                        self.connect_calls.append((port, proto, kwargs))
                        return self.behavior(self.auth_tokens_seen[-1], port, proto, kwargs)

                # 1. Static NGROK_DOMAIN: uses ONLY first token and validates matching hostname
                ok_ngrok = _FakeNgrok(
                    lambda tok, port, proto, kw: SimpleNamespace(public_url="https://shop-static.ngrok-free.app")
                )
                url = helper(
                    ok_ngrok,
                    8001,
                    ["tok-primary", "tok-secondary"],
                    ngrok_domain="shop-static.ngrok-free.app",
                )
                self.assertEqual(url, "https://shop-static.ngrok-free.app")
                self.assertEqual(ok_ngrok.auth_tokens_seen, ["tok-primary"])
                self.assertEqual(ok_ngrok.connect_calls, [(8001, "http", {"domain": "shop-static.ngrok-free.app"})])
                self.assertIn("https://old.ngrok-free.app", ok_ngrok.disconnected)

                # 2. Static NGROK_DOMAIN: when first token fails, must NOT try second token
                fail_domain_ngrok = _FakeNgrok(
                    lambda tok, port, proto, kw: (_ for _ in ()).throw(RuntimeError("domain not owned"))
                )
                with self.assertRaises(RuntimeError) as dom_fail:
                    helper(
                        fail_domain_ngrok,
                        8001,
                        ["tok-primary", "tok-secondary"],
                        ngrok_domain="shop-static.ngrok-free.app",
                    )
                self.assertEqual(fail_domain_ngrok.auth_tokens_seen, ["tok-primary"])
                self.assertIn("shop-static.ngrok-free.app", str(dom_fail.exception))

                # 3. Static NGROK_DOMAIN: mismatched returned URL disconnects and raises RuntimeError
                mismatch_ngrok = _FakeNgrok(
                    lambda tok, port, proto, kw: SimpleNamespace(public_url="https://random-other.ngrok-free.app")
                )
                with self.assertRaises(RuntimeError) as mis_err:
                    helper(
                        mismatch_ngrok,
                        8001,
                        ["tok-primary"],
                        ngrok_domain="shop-static.ngrok-free.app",
                    )
                self.assertIn("không khớp", str(mis_err.exception))
                self.assertIn("https://random-other.ngrok-free.app", mismatch_ngrok.disconnected)

                # 4. Dynamic tunnel (no NGROK_DOMAIN): falls back to second token, and errors clearly when all fail
                fallback_ngrok = _FakeNgrok(
                    lambda tok, port, proto, kw: (
                        (_ for _ in ()).throw(RuntimeError("quota exceeded"))
                        if tok == "tok-1"
                        else SimpleNamespace(public_url="https://dynamic-ok.ngrok-free.app")
                    )
                )
                dyn_url = helper(fallback_ngrok, 8001, ["tok-1", "tok-2"], ngrok_domain="")
                self.assertEqual(dyn_url, "https://dynamic-ok.ngrok-free.app")
                self.assertEqual(fallback_ngrok.auth_tokens_seen, ["tok-1", "tok-2"])

                all_fail_ngrok = _FakeNgrok(
                    lambda tok, port, proto, kw: (_ for _ in ()).throw(RuntimeError(f"bad {tok}"))
                )
                with self.assertRaises(RuntimeError) as all_fail_err:
                    helper(all_fail_ngrok, 8001, ["tok-1", "tok-2"], ngrok_domain="")
                self.assertIn("tok-1", str(all_fail_err.exception))
                self.assertIn("tok-2", str(all_fail_err.exception))

                with self.assertRaises(RuntimeError):
                    helper(all_fail_ngrok, 8001, ["  ", ""], ngrok_domain="")


if __name__ == "__main__":
    unittest.main()
