"""Phase R1 W4 post-verification deploy contract tests.

Covers:
1. ClamAV compose overlay (`-f compose.clamav.yaml`) preserved across `deploy/rollout-public-web.sh`
   (both `compose` and `rollback` arrays, while keeping `--no-deps`), `deploy/admin-console.py`
   (`compose()`), and `deploy/live-e2e.py` (`compose_base()`).
2. `notebooks/colab_vllm_l4.py` CELL 3 EC2 guidance writes values directly into `/opt/retailops/api.env`
   (editing existing `RETAILOPS_API_KEY`, adding `RETAILOPS_API_TUNNEL_TOKEN` and
   `RETAILOPS_CUSTOMER_REF_KEY`, warning against `*_FILE` on EC2, and invoking
   `sudo /opt/retailops/rollout-public-web.sh "<RETAILOPS_IMAGE trong deployed.env>"`), while
   keeping `*_FILE` support intact in application code.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from retailops.business.outbox import resolve_customer_ref_key
from retailops.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    if "fcntl" not in sys.modules:
        try:
            import fcntl  # noqa: F401
        except ImportError:
            stub = types.ModuleType("fcntl")
            stub.LOCK_EX = 2
            stub.LOCK_NB = 4
            stub.flock = lambda *_args, **_kwargs: None
            with patch.dict(sys.modules, {"fcntl": stub}):
                spec.loader.exec_module(mod)
                return mod
    spec.loader.exec_module(mod)
    return mod


def _split_rollout_sections(script_text: str) -> tuple[str, str]:
    match = re.search(
        r"^restore_previous\(\)\s*\{\n(.*?)\n^\}",
        script_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise AssertionError("restore_previous() function not found in deploy/rollout-public-web.sh")
    restore_body = match.group(1)
    outer_body = script_text[: match.start()] + "\n" + script_text[match.end() :]
    return outer_body, restore_body


class TestW4ClamAVDeployOverlayContract(unittest.TestCase):
    def test_rollout_script_adds_clamav_overlay_to_both_compose_and_rollback_and_keeps_no_deps(self):
        rollout_path = ROOT / "deploy" / "rollout-public-web.sh"
        script_text = rollout_path.read_text(encoding="utf-8")
        self.assertNotIn("\r", script_text, "rollout-public-web.sh must use LF line endings")
        self.assertIn('deployment_dir=/opt/retailops\ncd "$deployment_dir"', script_text)

        outer_body, restore_body = _split_rollout_sections(script_text)

        # 1. Forward `compose` array in main body
        compose_block = re.search(
            r"compose=\(docker compose --project-name retailops-web --env-file deployed\.env "
            r"--env-file public\.env -f compose\.public\.yaml\)(.*?)\"\$\{compose\[@\]\}\" config --quiet",
            outer_body,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(compose_block, "Forward compose array block missing before config --quiet")
        compose_Logic = compose_block.group(1)
        pg_idx = compose_Logic.find("compose+=(-f compose.postgres.yaml)")
        clam_idx = compose_Logic.find("compose+=(-f compose.clamav.yaml)")
        self.assertGreaterEqual(pg_idx, 0)
        self.assertGreater(clam_idx, pg_idx, "ClamAV overlay must be appended after PostgreSQL overlay in compose")
        self.assertRegex(
            compose_Logic,
            r"if \[\[ -f compose\.clamav\.yaml \]\]; then\s+compose\+=\(-f compose\.clamav\.yaml\)\s+fi",
        )
        self.assertIn(
            '"${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 90 web',
            outer_body,
        )

        # 2. `rollback` array inside restore_previous()
        rollback_block = re.search(
            r'rollback=\(docker compose --project-name retailops-web --env-file "\$rollback_env" '
            r'--env-file public\.env -f compose\.public\.yaml\)(.*?)"\$\{rollback\[@\]\}" config --quiet',
            restore_body,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(rollback_block, "Rollback compose array block missing inside restore_previous()")
        rollback_logic = rollback_block.group(1)
        rb_pg_idx = rollback_logic.find("rollback+=(-f compose.postgres.yaml)")
        rb_clam_idx = rollback_logic.find("rollback+=(-f compose.clamav.yaml)")
        self.assertGreaterEqual(rb_pg_idx, 0)
        self.assertGreater(
            rb_clam_idx, rb_pg_idx, "ClamAV overlay must be appended after PostgreSQL overlay in rollback"
        )
        self.assertRegex(
            rollback_logic,
            r"if \[\[ -f compose\.clamav\.yaml \]\]; then\s+rollback\+=\(-f compose\.clamav\.yaml\);?\s+fi",
        )
        self.assertIn(
            '"${rollback[@]}" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 90 web',
            restore_body,
        )

        # 3. On POSIX hosts with bash available, also evaluate both array snippets directly in bash
        if os.name == "posix" and shutil.which("bash"):
            subprocess.run(["bash", "-n", str(rollout_path)], check=True)
            compose_snippet = (
                "set -euo pipefail\n"
                "compose=(docker compose --project-name retailops-web --env-file deployed.env "
                "--env-file public.env -f compose.public.yaml)\n"
                + compose_Logic
                + '\nprintf "%s\\n" "${compose[@]}"\n'
            )
            rollback_snippet = (
                "set -euo pipefail\n"
                "rollback_env=/opt/retailops/deployed.rollback.test\n"
                'rollback=(docker compose --project-name retailops-web --env-file "$rollback_env" '
                "--env-file public.env -f compose.public.yaml)\n"
                + rollback_logic
                + '\nprintf "%s\\n" "${rollback[@]}"\n'
            )
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "compose.public.yaml").write_text("services: {}\n", encoding="utf-8")

                # Without clamav or postgres
                out_c = subprocess.run(
                    ["bash", "-c", compose_snippet], cwd=root, check=True, capture_output=True, text=True
                ).stdout.splitlines()
                out_r = subprocess.run(
                    ["bash", "-c", rollback_snippet], cwd=root, check=True, capture_output=True, text=True
                ).stdout.splitlines()
                self.assertNotIn("compose.clamav.yaml", out_c)
                self.assertNotIn("compose.clamav.yaml", out_r)

                # With postgres-secrets + compose.postgres.yaml + compose.clamav.yaml
                (root / "postgres-secrets").mkdir()
                (root / "compose.postgres.yaml").write_text("services: {}\n", encoding="utf-8")
                (root / "compose.clamav.yaml").write_text("services: {}\n", encoding="utf-8")
                out_c2 = subprocess.run(
                    ["bash", "-c", compose_snippet], cwd=root, check=True, capture_output=True, text=True
                ).stdout.splitlines()
                out_r2 = subprocess.run(
                    ["bash", "-c", rollback_snippet], cwd=root, check=True, capture_output=True, text=True
                ).stdout.splitlines()
                self.assertEqual(
                    out_c2[-6:],
                    ["-f", "compose.public.yaml", "-f", "compose.postgres.yaml", "-f", "compose.clamav.yaml"],
                )
                self.assertEqual(
                    out_r2[-6:],
                    ["-f", "compose.public.yaml", "-f", "compose.postgres.yaml", "-f", "compose.clamav.yaml"],
                )

    def test_admin_console_compose_includes_clamav_overlay_when_present(self):
        admin_mod = _load_module("admin_console_contract", ROOT / "deploy" / "admin-console.py")
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            with patch.object(admin_mod, "ROOT", fake_root):
                # Base only
                self.assertEqual(
                    admin_mod.compose(False),
                    [
                        "docker", "compose", "--project-name", "retailops-web",
                        "--env-file", "deployed.env", "--env-file", "public.env",
                        "-f", "compose.public.yaml",
                    ],
                )
                self.assertNotIn("compose.clamav.yaml", admin_mod.compose(True))

                # Directory named compose.clamav.yaml is ignored (must be a file)
                (fake_root / "compose.clamav.yaml").mkdir()
                self.assertNotIn("compose.clamav.yaml", admin_mod.compose(False))
                (fake_root / "compose.clamav.yaml").rmdir()

                # ClamAV file only
                (fake_root / "compose.clamav.yaml").write_text("services: {}\n", encoding="utf-8")
                self.assertEqual(
                    admin_mod.compose(False),
                    [
                        "docker", "compose", "--project-name", "retailops-web",
                        "--env-file", "deployed.env", "--env-file", "public.env",
                        "-f", "compose.public.yaml", "-f", "compose.clamav.yaml",
                    ],
                )
                self.assertEqual(
                    admin_mod.compose(True),
                    [
                        "docker", "compose", "--project-name", "retailops-web",
                        "--env-file", "deployed.env", "--env-file", "public.env",
                        "-f", "compose.public.yaml", "-f", "compose.clamav.yaml",
                        "--env-file", "admin.env", "-f", "compose.admin.yaml",
                    ],
                )

                # PostgreSQL + ClamAV + Admin overlays in deterministic order
                (fake_root / "postgres-secrets").mkdir()
                self.assertEqual(
                    admin_mod.compose(True),
                    [
                        "docker", "compose", "--project-name", "retailops-web",
                        "--env-file", "deployed.env", "--env-file", "public.env",
                        "-f", "compose.public.yaml",
                        "-f", "compose.postgres.yaml",
                        "-f", "compose.clamav.yaml",
                        "--env-file", "admin.env", "-f", "compose.admin.yaml",
                    ],
                )

    def test_live_e2e_compose_base_includes_clamav_overlay_when_present(self):
        e2e_mod = _load_module("live_e2e_contract", ROOT / "deploy" / "live-e2e.py")
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            with patch.object(e2e_mod, "ROOT", fake_root):
                self.assertEqual(
                    e2e_mod.compose_base(),
                    [
                        "docker", "compose", "--project-name", "retailops-web",
                        "--env-file", "deployed.env", "--env-file", "public.env",
                        "-f", "compose.public.yaml",
                    ],
                )

                # Directory named compose.clamav.yaml is ignored
                (fake_root / "compose.clamav.yaml").mkdir()
                self.assertNotIn("compose.clamav.yaml", e2e_mod.compose_base())
                (fake_root / "compose.clamav.yaml").rmdir()

                # ClamAV file present
                (fake_root / "compose.clamav.yaml").write_text("services: {}\n", encoding="utf-8")
                self.assertEqual(
                    e2e_mod.compose_base(),
                    [
                        "docker", "compose", "--project-name", "retailops-web",
                        "--env-file", "deployed.env", "--env-file", "public.env",
                        "-f", "compose.public.yaml", "-f", "compose.clamav.yaml",
                    ],
                )

                # PostgreSQL + ClamAV present
                (fake_root / "postgres-secrets").mkdir()
                self.assertEqual(
                    e2e_mod.compose_base(),
                    [
                        "docker", "compose", "--project-name", "retailops-web",
                        "--env-file", "deployed.env", "--env-file", "public.env",
                        "-f", "compose.public.yaml",
                        "-f", "compose.postgres.yaml",
                        "-f", "compose.clamav.yaml",
                    ],
                )


class TestW4ColabEC2SecretGuidanceContract(unittest.TestCase):
    def test_colab_vllm_notebook_direct_api_env_guidance_and_rollout_helper(self):
        nb_py = ROOT / "notebooks" / "colab_vllm_l4.py"
        src = nb_py.read_text(encoding="utf-8")
        ast.parse(src, filename="notebooks/colab_vllm_l4.py")

        forbidden_secrets_dir = "/opt/retailops/" + "secrets"
        forbidden_file_vars = (
            "RETAILOPS_API_KEY" + "_FILE",
            "RETAILOPS_API_TUNNEL_TOKEN" + "_FILE",
            "RETAILOPS_CUSTOMER_REF_KEY" + "_FILE",
        )
        self.assertNotIn(forbidden_secrets_dir, src)
        for var_name in forbidden_file_vars:
            self.assertNotIn(var_name, src)

        self.assertIn("# %% [CELL 3]", src)
        cell3 = src.split("# %% [CELL 3]", 1)[1]

        # Step 1: write values directly into /opt/retailops/api.env
        self.assertIn("/opt/retailops/api.env", cell3)
        self.assertIn("TRỰC TIẾP", cell3)
        self.assertIn("SỬA dòng RETAILOPS_API_KEY", cell3)
        self.assertIn("KHÔNG thêm dòng mới", cell3)
        self.assertIn("RETAILOPS_API_KEY=", cell3)
        self.assertIn("RETAILOPS_API_TUNNEL_TOKEN=", cell3)
        self.assertIn("RETAILOPS_CUSTOMER_REF_KEY=", cell3)
        self.assertIn("*_FILE", cell3)

        # Step 2: run rollout-public-web.sh instead of hand-assembled docker compose
        self.assertIn(
            'sudo /opt/retailops/rollout-public-web.sh "<RETAILOPS_IMAGE trong deployed.env>"',
            cell3,
        )
        self.assertNotIn("docker compose --project-name retailops-web", cell3)

        # Standalone colab_agent.ipynb cells (excluding compressed source archive line) must also never suggest /opt/retailops/secrets/*_FILE
        ipynb = json.loads((ROOT / "notebooks" / "colab_agent.ipynb").read_text(encoding="utf-8"))
        for cell in ipynb.get("cells", []):
            for line in cell.get("source", []):
                if "zlib.decompress(base64.b64decode(" in line:
                    continue
                self.assertNotIn(forbidden_secrets_dir, line)
                for var_name in forbidden_file_vars:
                    self.assertNotIn(var_name, line)

    def test_code_retains_secret_file_support_for_non_ec2_environments(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            api_key_file = tmp_path / "api_key"
            tunnel_file = tmp_path / "tunnel_token"
            cust_ref_file = tmp_path / "customer_ref_key"
            api_key_val = "vllm_secret_key_" + "k" * 24
            tunnel_val = "ngrok_tunnel_tok_" + "t" * 24
            cust_ref_val = "hmac_customer_ref_secret_0123456789"
            api_key_file.write_text(api_key_val + "\n", encoding="utf-8")
            tunnel_file.write_text(tunnel_val + "\n", encoding="utf-8")
            cust_ref_file.write_text(cust_ref_val + "\n", encoding="utf-8")

            api_key_var = "RETAILOPS_API_KEY" + "_FILE"
            tunnel_var = "RETAILOPS_API_TUNNEL_TOKEN" + "_FILE"
            cust_ref_var = "RETAILOPS_CUSTOMER_REF_KEY" + "_FILE"

            settings = Settings.from_environment(
                "public",
                environ={
                    "RETAILOPS_PUBLIC_ORIGIN": "https://retailops.example.com",
                    "RETAILOPS_PUBLIC_INVITE_TOKEN": "invite_" + "x" * 36,
                    "RETAILOPS_API_ENABLED": "true",
                    "RETAILOPS_API_ENDPOINT": "https://shop.ngrok-free.app/v1/chat/completions",
                    "RETAILOPS_API_MODEL": "google/gemma-4-12b",
                    api_key_var: str(api_key_file),
                    tunnel_var: str(tunnel_file),
                    cust_ref_var: str(cust_ref_file),
                },
            )
            self.assertEqual(settings.api_key, api_key_val)
            self.assertEqual(settings.api_tunnel_token, tunnel_val)
            self.assertEqual(settings.customer_ref_key, cust_ref_val)

            key_resolved, err_code, err_msg = resolve_customer_ref_key(environ={cust_ref_var: str(cust_ref_file)})
            self.assertEqual(key_resolved, cust_ref_val)
            self.assertIsNone(err_code)
            self.assertIsNone(err_msg)


if __name__ == "__main__":
    unittest.main()
