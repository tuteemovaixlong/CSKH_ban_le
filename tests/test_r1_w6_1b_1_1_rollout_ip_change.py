"""Phase R1 W6.1b-1.1 Item 1 contract tests for `deploy/rollout-public-web.sh` on EC2 IP change."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLLOUT_SCRIPT = ROOT / "deploy" / "rollout-public-web.sh"


def _find_bash() -> str | None:
    found = shutil.which("bash")
    if found:
        return found
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    if git_bash.is_file():
        return str(git_bash)
    return None


def _extract_function(script_text: str, name: str) -> str:
    match = re.search(
        rf"^({re.escape(name)}\(\)\s*\{{\n.*?\n^\}})",
        script_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise AssertionError(f"{name}() function not found in deploy/rollout-public-web.sh")
    return match.group(1)


class TestW61b11RolloutIpChangeContract(unittest.TestCase):
    def test_rollout_script_ordering_no_premature_up_and_2026_11_09_comment(self):
        script_text = ROLLOUT_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("\r", script_text, "rollout-public-web.sh must use LF line endings")
        self.assertIn("2026-11-09", script_text)

        # (a) web_container, previous_image, running_image_id captured BEFORE sslip.io refresh
        web_idx = script_text.find("web_container=")
        prev_idx = script_text.find("previous_image=")
        run_idx = script_text.find("running_image_id=")
        sslip_idx = script_text.find("existing_host=")
        self.assertGreater(web_idx, 0)
        self.assertGreater(prev_idx, web_idx)
        self.assertGreater(run_idx, prev_idx)
        self.assertGreater(
            sslip_idx,
            run_idx,
            "previous_image and running_image_id must be read BEFORE the sslip.io hostname refresh block",
        )

        # (b) sslip.io refresh block only updates public.env and sets host_changed=true; no `up ` inside
        overlay_idx = script_text.find("overlay_changed=false", sslip_idx)
        self.assertGreater(overlay_idx, sslip_idx)
        sslip_block = script_text[sslip_idx:overlay_idx]
        self.assertIn("host_changed=true", sslip_block)
        self.assertNotIn("up ", sslip_block, "sslip.io refresh block must NOT run docker compose up")
        self.assertNotIn("web caddy", sslip_block)

        # (c) Rollout condition includes host_changed alongside overlay_changed, then recreates caddy
        self.assertRegex(
            script_text,
            r'if \[\[ "\$running_image_id" != "\$target_image_id" \|\| "\$overlay_changed" == true \|\| "\$host_changed" == true \]\]; then',
        )
        self.assertIn("recreate_caddy deployed.env", script_text)

        # (d) restore_previous preserves pinned digest / allowed_repo guards and recreates caddy when host_changed
        restore_fn = _extract_function(script_text, "restore_previous")
        self.assertIn('"$host_changed" != true', restore_fn)
        self.assertIn('if [[ "$host_changed" == true ]]; then', restore_fn)
        self.assertIn('recreate_caddy "$rollback_env"', restore_fn)
        self.assertIn("@sha256:[a-f0-9]{64}$", restore_fn)
        self.assertIn('"${previous_image%@*}" != "$allowed_repo"', restore_fn)

    def test_bash_syntax_and_recreate_caddy_admin_overlay_conditions(self):
        bash = _find_bash()
        if not bash:
            self.skipTest("bash is not available on this host")

        subprocess.run([bash, "-n", "deploy/rollout-public-web.sh"], cwd=ROOT, check=True)

        script_text = ROLLOUT_SCRIPT.read_text(encoding="utf-8")
        recreate_fn = _extract_function(script_text, "recreate_caddy")
        harness = (
            "set -euo pipefail\n"
            ': > docker.log\n'
            'docker() { printf "DOCKER:%s\\n" "$*" >> docker.log; }\n'
            + recreate_fn
            + '\nrecreate_caddy "${1:-deployed.env}"\n'
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "compose.public.yaml").write_text("services: {}\n", encoding="utf-8")

            # Case 1: neither admin.env nor compose.admin.yaml -> no admin overlay
            subprocess.run([bash, "-c", harness], cwd=root, check=True, capture_output=True, text=True)
            out_no_admin = (root / "docker.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                out_no_admin,
                [
                    "DOCKER:compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml config --quiet",
                    "DOCKER:compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml up -d --no-deps --no-build --pull never --force-recreate caddy",
                ],
            )

            # Case 2: compose.admin.yaml alone (without admin.env) -> still NO admin overlay
            (root / "compose.admin.yaml").write_text("services: {}\n", encoding="utf-8")
            subprocess.run([bash, "-c", harness], cwd=root, check=True, capture_output=True, text=True)
            out_partial = (root / "docker.log").read_text(encoding="utf-8").splitlines()
            self.assertNotIn("compose.admin.yaml", "\n".join(out_partial))
            self.assertNotIn("admin.env", "\n".join(out_partial))

            # Case 3: both admin.env and compose.admin.yaml (+ postgres + clamav) -> matches compose(admin=True)
            (root / "admin.env").write_text("ADMIN=1\n", encoding="utf-8")
            (root / "postgres-secrets").mkdir()
            (root / "compose.postgres.yaml").write_text("services: {}\n", encoding="utf-8")
            (root / "compose.clamav.yaml").write_text("services: {}\n", encoding="utf-8")
            subprocess.run(
                [bash, "-c", harness, "bash", "deployed.rollback.abc"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            out_with_admin = (root / "docker.log").read_text(encoding="utf-8").splitlines()
            expected_prefix = (
                "DOCKER:compose --project-name retailops-web "
                "--env-file deployed.rollback.abc --env-file public.env "
                "-f compose.public.yaml -f compose.postgres.yaml -f compose.clamav.yaml "
                "--env-file admin.env -f compose.admin.yaml "
            )
            self.assertEqual(
                out_with_admin,
                [
                    expected_prefix + "config --quiet",
                    expected_prefix + "up -d --no-deps --no-build --pull never --force-recreate caddy",
                ],
            )

    def test_restore_previous_rolls_back_to_old_image_and_preserves_admin_overlay_on_ip_change(self):
        bash = _find_bash()
        if not bash:
            self.skipTest("bash is not available on this host")

        script_text = ROLLOUT_SCRIPT.read_text(encoding="utf-8")
        recreate_fn = _extract_function(script_text, "recreate_caddy")
        restore_fn = _extract_function(script_text, "restore_previous").replace(
            "mktemp /opt/retailops/deployed.rollback.XXXXXX",
            "mktemp ./deployed.rollback.XXXXXX",
        )
        old_img = "123456789012.dkr.ecr.us-east-1.amazonaws.com/retailops@sha256:" + ("a" * 64)
        new_img = "123456789012.dkr.ecr.us-east-1.amazonaws.com/retailops@sha256:" + ("b" * 64)

        sim_script = (
            "set -euo pipefail\n"
            ": > docker.log\n"
            f'allowed_repo="123456789012.dkr.ecr.us-east-1.amazonaws.com/retailops"\n'
            f'previous_image="{old_img}"\n'
            f'image_ref="{new_img}"\n'
            'data_dir="/data"\n'
            "overlay_changed=false\n"
            'compose_backup=""\n'
            "host_changed=true\n"
            'docker() { printf "DOCKER:%s\\n" "$*" >> docker.log; }\n'
            + recreate_fn
            + "\n"
            + restore_fn
            + "\nrestore_previous\n"
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "compose.public.yaml").write_text("services: {}\n", encoding="utf-8")
            (root / "public.env").write_text(
                "RETAILOPS_PUBLIC_HOST=retailops.100-26-48-5.sslip.io\n"
                "RETAILOPS_PUBLIC_ORIGIN=https://retailops.100-26-48-5.sslip.io\n",
                encoding="utf-8",
            )
            (root / "deployed.env").write_text(
                f"RETAILOPS_IMAGE={new_img}\nRETAILOPS_DATA_DIR=/data\n",
                encoding="utf-8",
            )
            (root / "admin.env").write_text("ADMIN=1\n", encoding="utf-8")
            (root / "compose.admin.yaml").write_text("services: {}\n", encoding="utf-8")

            proc = subprocess.run(
                [bash, "-c", sim_script], cwd=root, check=True, capture_output=True, text=True
            )
            self.assertIn("PUBLIC_WEB_ROLLBACK_OK", proc.stdout.splitlines())
            lines = (root / "docker.log").read_text(encoding="utf-8").splitlines()
            self.assertTrue(
                any("up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 90 web" in ln for ln in lines),
                lines,
            )
            self.assertTrue(
                any("--env-file admin.env -f compose.admin.yaml up -d --no-deps --no-build --pull never --force-recreate caddy" in ln for ln in lines),
                lines,
            )
            deployed_after = (root / "deployed.env").read_text(encoding="utf-8")
            self.assertIn(f"RETAILOPS_IMAGE={old_img}", deployed_after)
            self.assertNotIn(new_img, deployed_after)


if __name__ == "__main__":
    unittest.main()
