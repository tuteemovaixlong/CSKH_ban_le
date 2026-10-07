"""Tests for R13 Deployment Guard (check_deploy_eligibility.py).

Acceptance checks:
- eval-only changes: do NOT deploy (deploy_eligible=false)
- mixed eval + runtime changes: deploy eligible under existing policy (deploy_eligible=true)
- runtime-only changes: deploy eligible under existing policy (deploy_eligible=true)
- workflow_dispatch: manual trigger is ALWAYS deploy eligible (deploy_eligible=true)
"""

import subprocess
import sys
import unittest
from pathlib import Path

from scripts.check_deploy_eligibility import is_deploy_eligible, matches_any, DEPLOY_ELIGIBLE_PATTERNS


class TestDeployGuard(unittest.TestCase):

    def test_workflow_dispatch_always_eligible(self):
        eligible, reason = is_deploy_eligible("workflow_dispatch", ["docs/foo.md"])
        self.assertTrue(eligible)
        self.assertIn("workflow_dispatch", reason)

        eligible_empty, _ = is_deploy_eligible("workflow_dispatch", [])
        self.assertTrue(eligible_empty)

    def test_eval_only_files_not_eligible(self):
        eval_files = [
            "docs/phase4/PLAN_PHASE_4_EVALUATION.md",
            "evals/harness/schema.py",
            "evals/harness/writer.py",
            "tests/test_phase4_schema.py",
            "scripts/phase4_harness.py",
            ".github/workflows/ci.yml",
            "README.md",
        ]
        eligible, reason = is_deploy_eligible("push", eval_files)
        self.assertFalse(eligible)
        self.assertIn("deploy skipped", reason)

    def test_mixed_eval_and_runtime_is_eligible(self):
        mixed_files = [
            "evals/harness/schema.py",
            "docs/phase4/REVIEW_PHASE_4_PLAN.md",
            "retailops/business/application.py",
        ]
        eligible, reason = is_deploy_eligible("push", mixed_files)
        self.assertTrue(eligible)
        self.assertIn("retailops/business/application.py", reason)

    def test_runtime_only_files_is_eligible(self):
        runtime_files = [
            "Dockerfile",
            "requirements-graph.txt",
            "deploy/rollout-public-web.sh",
            "web/app.js",
            "data/knowledge/cancellation.md",
        ]
        for f in runtime_files:
            eligible, reason = is_deploy_eligible("push", [f])
            self.assertTrue(eligible, f"File {f} should be deploy-eligible")
            self.assertIn("deploy eligible", reason)

    def test_empty_files_not_eligible(self):
        eligible, reason = is_deploy_eligible("push", [])
        self.assertFalse(eligible)
        self.assertIn("no changed files", reason)

    def test_cli_execution_and_github_output(self, tmp_path=None):
        import tempfile
        with tempfile.NamedTemporaryFile("r+", delete=False) as tf:
            temp_path = tf.name

        try:
            cmd = [
                sys.executable,
                "scripts/check_deploy_eligibility.py",
                "--event-name", "push",
                "--files", "evals/harness/schema.py", "docs/test.md",
                "--github-output", temp_path,
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            self.assertIn("DEPLOY_ELIGIBILITY: false", res.stdout)

            out_content = Path(temp_path).read_text(encoding="utf-8")
            self.assertIn("deploy_eligible=false", out_content)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_additional_runtime_paths_are_deploy_eligible(self):
        """Newly covered runtime paths from H7 must be deploy eligible."""
        h7_runtime_paths = [
            "opsconsole/server.py",
            "opsconsole/client.js",
            "data/smoke.jsonl",
            "data/products.json",
            "data/mock_shipments.json",
            "data/users.json",
            "mcp_config.json",
            ".dockerignore",
            "scripts/deploy_remote_ec2.py",
            "scripts/opsconsole.py",
        ]
        for path in h7_runtime_paths:
            eligible, reason = is_deploy_eligible("push", [path])
            self.assertTrue(eligible, f"Path '{path}' must be deploy-eligible")
            self.assertIn("deploy eligible", reason)

    def test_unknown_path_fails_closed(self):
        """Unrecognized paths outside eval/docs must trigger deploy eligibility (fail-closed)."""
        unknown_paths = [
            "custom_daemon.py",
            "some/unknown/service.sh",
            "config/production.yaml",
        ]
        for path in unknown_paths:
            eligible, reason = is_deploy_eligible("push", [path])
            self.assertTrue(eligible, f"Unknown path '{path}' must fail-closed to deploy-eligible")
            self.assertIn("fail-closed", reason)

    def test_multi_commit_push_simulation(self):
        """Simulate multi-commit push where one commit has runtime changes and subsequent has docs."""
        # When both are present in the diff of before..sha, deploy must be eligible
        multi_commit_files = [
            "docs/phase4/REVIEW_GEMINI_PHASE4_2026-10-07.md",  # Commit 2 (docs only)
            "data/products.json",                              # Commit 1 (runtime)
        ]
        eligible, reason = is_deploy_eligible("push", multi_commit_files)
        self.assertTrue(eligible)
        self.assertIn("data/products.json", reason)


if __name__ == "__main__":
    unittest.main()
