#!/usr/bin/env python3
"""R13 Deployment Guard: Evaluates deployment eligibility based on changed files.

Acceptance criteria:
- eval-only changes: DO NOT deploy (deploy_eligible=false)
- mixed eval + runtime changes: deploy eligible under existing policy (deploy_eligible=true)
- runtime-only changes: deploy eligible under existing policy (deploy_eligible=true)
- workflow_dispatch: manual trigger is ALWAYS deploy eligible (deploy_eligible=true)

Normative reference:
- docs/phase4/REVIEW_PHASE_4_PLAN.md (R13)
- docs/phase4/PHASE_4_EXECUTION_HANDOFF.md (R13)
"""

from pathlib import Path
from typing import List, Optional, Tuple
import argparse
import fnmatch
import os
import subprocess
import sys

DEPLOY_ELIGIBLE_PATTERNS = [
    "retailops/**",
    "deploy/**",
    "web/**",
    "data/knowledge/**",
    "data/deepseek_seed_data.json",
    "Dockerfile",
    "compose.yaml",
    "requirements*.txt",
    "agent_protocol.py",
    "retailops_*.py",
    "inference_proxy.py",
    "backup_state.py",
]

EVAL_AND_DOCS_PATTERNS = [
    "docs/**",
    "evals/**",
    "tests/**",
    "*.md",
    "scripts/check_docs_contract.py",
    "scripts/check_eval_dataset.py",
    "scripts/run_benchmark_eval.py",
    "scripts/phase4_harness.py",
    "scripts/check_deploy_eligibility.py",
    ".github/workflows/ci.yml",
    ".github/workflows/ops-console.yml",
    ".github/workflows/deploy-ec2.yml",
    ".github/workflows/live-e2e.yml",
    ".gitignore",
    ".dockerignore",
]


def matches_any(path_str: str, patterns: List[str]) -> bool:
    normalized = path_str.replace("\\", "/").strip()
    for pat in patterns:
        if fnmatch.fnmatch(normalized, pat) or fnmatch.fnmatch(normalized, f"*/{pat}"):
            return True
        if pat.endswith("/**"):
            prefix = pat[:-3]
            if normalized == prefix or normalized.startswith(f"{prefix}/"):
                return True
    return False


def is_deploy_eligible(event_name: str, changed_files: List[str]) -> Tuple[bool, str]:
    """Determines whether a commit/push is eligible for deployment to EC2."""
    if event_name == "workflow_dispatch":
        return True, "workflow_dispatch manual trigger is always deploy-eligible"

    if not changed_files:
        return False, "no changed files detected"

    eligible_triggers = []
    for f in changed_files:
        if matches_any(f, DEPLOY_ELIGIBLE_PATTERNS):
            eligible_triggers.append(f)

    if eligible_triggers:
        return True, f"deploy eligible: detected runtime/deploy changes in {eligible_triggers[:3]}"

    return False, f"deploy skipped: all {len(changed_files)} changed files are eval/docs/test only"


def get_changed_files_from_git(before: Optional[str], sha: Optional[str]) -> List[str]:
    """Retrieves list of changed files via git diff."""
    all_zeros = "0000000000000000000000000000000000000000"
    if before and before != all_zeros and sha:
        cmd = ["git", "diff", "--name-only", f"{before}..{sha}"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return [line.strip() for line in res.stdout.splitlines() if line.strip()]
        except Exception:
            pass

    # Fallback to HEAD~1..HEAD or single commit diff
    for fallback_cmd in (
        ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
    ):
        try:
            res = subprocess.run(fallback_cmd, capture_output=True, text=True, check=True)
            files = [line.strip() for line in res.stdout.splitlines() if line.strip()]
            if files:
                return files
        except Exception:
            continue

    return []


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check deployment eligibility")
    parser.add_argument("--event-name", default="push", help="GitHub event name")
    parser.add_argument("--before", help="Commit SHA before push")
    parser.add_argument("--sha", help="Current commit SHA")
    parser.add_argument("--files", nargs="*", help="Explicit list of changed files (for testing)")
    parser.add_argument("--github-output", help="Path to write GITHUB_OUTPUT")

    args = parser.parse_args(argv)

    if args.files is not None:
        changed_files = args.files
    else:
        changed_files = get_changed_files_from_git(args.before, args.sha)

    eligible, reason = is_deploy_eligible(args.event_name, changed_files)
    eligible_str = "true" if eligible else "false"

    print(f"DEPLOY_ELIGIBILITY: {eligible_str} ({reason})")

    out_path = args.github_output or os.environ.get("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(f"deploy_eligible={eligible_str}\n")
            f.write(f"reason={reason}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
