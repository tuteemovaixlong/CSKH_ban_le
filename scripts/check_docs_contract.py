#!/usr/bin/env python3
"""
RetailOps Documentation Contract & Integrity Validator
Enforces truthfulness between codebase implementation and documentation:
1. Dataset Integrity & EOL-normalized SHA-256 validation for master/benchmark/baseline datasets.
2. Stale Git HEAD metadata detection in active status and plan documents.
3. Relative markdown link verification and prohibition of absolute file:/// URLs.
4. Dynamic AST tool contract validation between Python code and documentation specifications.
"""
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]

# Pinned SHA-256 for canonical 250-case benchmark dataset under POSIX LF normalization
PINNED_MASTER_V1_SHA256 = "36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411"

ACTIVE_DOCS_FOR_STALE_HEAD = [
    "docs/CURRENT_PROJECT_STATUS.md",
    "docs/PLAN_ROADMAP_INDEX.md",
    "docs/PLAN_MULTIMODAL_ATTACHMENTS.md",
    "docs/PLAN_RBAC_GOOGLE_AUTH.md",
    "docs/PLAN_FIX_UI_01_TRUTHFUL_UX.md",
    "docs/PLAN_FIX_UI_02_MANAGER_PERSISTENCE.md",
    "docs/PLAN_FIX_UI_03_OPSCONSOLE_INTEGRITY.md",
    "docs/PLAN_FIX_UI_04_CHAT_HISTORY_RESUME.md",
    "docs/PLAN_ECOMMERCE_OPS_COPILOT.md",
    "docs/PLAN_DEEPSEEK_EVAL_FRAMEWORK.md",
    "docs/PLAN_DATA_COLLECTION_FLYWHEEL.md",
    "docs/BUSINESS_TEST_SCENARIOS.md",
]


def normalized_sha256(path: Path) -> str:
    """Compute SHA-256 over cross-platform LF-normalized bytes."""
    with open(path, "rb") as f:
        content = f.read()
    normalized = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def count_valid_jsonl_lines(path: Path) -> int:
    """Count valid JSON objects in JSONL file."""
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                json.loads(line)
                count += 1
    return count


def check_datasets() -> List[str]:
    errors = []
    master_path = ROOT / "evals" / "scenarios" / "master_250_v1.jsonl"
    bench_path = ROOT / "evals" / "scenarios" / "benchmark_250.jsonl"
    baseline_path = ROOT / "evals" / "scenarios" / "baseline_v1.jsonl"

    if not master_path.exists():
        errors.append(f"Missing canonical dataset: {master_path}")
    else:
        master_hash = normalized_sha256(master_path)
        if master_hash != PINNED_MASTER_V1_SHA256:
            errors.append(f"master_250_v1.jsonl hash mismatch: got {master_hash}, expected {PINNED_MASTER_V1_SHA256}")
        lines = count_valid_jsonl_lines(master_path)
        if lines != 250:
            errors.append(f"master_250_v1.jsonl line count mismatch: got {lines}, expected 250")

    if not bench_path.exists():
        errors.append(f"Missing active benchmark mirror: {bench_path}")
    else:
        bench_hash = normalized_sha256(bench_path)
        if bench_hash != PINNED_MASTER_V1_SHA256:
            errors.append(f"benchmark_250.jsonl hash mismatch: got {bench_hash}, expected {PINNED_MASTER_V1_SHA256}")
        lines = count_valid_jsonl_lines(bench_path)
        if lines != 250:
            errors.append(f"benchmark_250.jsonl line count mismatch: got {lines}, expected 250")

    if not baseline_path.exists():
        errors.append(f"Missing CI baseline dataset: {baseline_path}")
    else:
        lines = count_valid_jsonl_lines(baseline_path)
        if lines != 30:
            errors.append(f"baseline_v1.jsonl line count mismatch: got {lines}, expected 30")

    return errors


def check_stale_git_head() -> List[str]:
    errors = []
    stale_patterns = [
        re.compile(r"Git HEAD\s*[:=]\s*[0-9a-fA-F]{7,40}", re.IGNORECASE),
        re.compile(r"[0-9a-fA-F]{7,40}\s*\(Git HEAD\)", re.IGNORECASE),
    ]

    for rel_path in ACTIVE_DOCS_FOR_STALE_HEAD:
        file_path = ROOT / rel_path
        if not file_path.exists():
            continue
        with open(file_path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, 1):
                cleaned_line = re.sub(r"[`*_]", "", line)
                for pat in stale_patterns:
                    if pat.search(cleaned_line):
                        errors.append(
                            f"{rel_path}:{idx}: Stale Git HEAD detected: '{line.strip()}'. "
                            f"Active docs must use 'Audit basis / Documentation baseline reviewed: <sha>' snapshot."
                        )
    return errors


def check_links_and_markdown_rules() -> List[str]:
    errors = []
    md_files = list(ROOT.glob("docs/**/*.md")) + [ROOT / "README.md"]
    link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

    for md_path in md_files:
        if not md_path.exists():
            continue
        rel_doc = md_path.relative_to(ROOT)
        content = md_path.read_text(encoding="utf-8")

        if "file:///" in content:
            errors.append(f"{rel_doc}: Contains forbidden 'file:///' local system URL.")

        for match in link_pattern.finditer(content):
            target = match.group(2).strip()
            if not target:
                continue

            # Ignore external links, in-page anchors, and mailto
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if target.startswith("#"):
                continue

            # Strip anchor query if present
            path_part = target.split("#")[0].split("?")[0]
            if not path_part:
                continue

            resolved_path = (md_path.parent / path_part).resolve()
            if not resolved_path.exists():
                errors.append(f"{rel_doc}: Broken relative link '{target}' -> resolved to missing '{resolved_path}'")

    return errors


def extract_mcp_tools_via_ast() -> dict:
    """Dynamically parse retailops_mcp_server.py via AST to extract registered MCP tools."""
    server_path = ROOT / "retailops_mcp_server.py"
    if not server_path.exists():
        return {}

    tree = ast.parse(server_path.read_text(encoding="utf-8"))
    tools = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                is_tool = False
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    if dec.func.attr == "tool":
                        is_tool = True
                if is_tool:
                    args = [a.arg for a in node.args.args]
                    tools[node.name] = args
    return tools


def extract_protocol_tools_via_ast() -> Set[str]:
    """Dynamically parse agent_protocol.py via AST to extract protocol tools."""
    proto_path = ROOT / "agent_protocol.py"
    if not proto_path.exists():
        return set()

    tree = ast.parse(proto_path.read_text(encoding="utf-8"))
    tools = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "TOOLS":
                    if isinstance(node.value, ast.List):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Call) and len(elt.args) >= 1:
                                if isinstance(elt.args[0], ast.Constant):
                                    tools.add(elt.args[0].value)
    return tools


def check_ast_tools_contract() -> List[str]:
    errors = []
    mcp_tools = extract_mcp_tools_via_ast()
    if len(mcp_tools) != 10:
        errors.append(f"retailops_mcp_server.py AST extracted {len(mcp_tools)} tools; expected exactly 10 tools.")

    proto_tools = extract_protocol_tools_via_ast()
    if len(proto_tools) != 12:
        errors.append(f"agent_protocol.py AST extracted {len(proto_tools)} tools; expected exactly 12 tools.")

    # Validate PLAN_MCP_INTEGRATION.md documents all 10 tools
    mcp_plan = ROOT / "docs" / "PLAN_MCP_INTEGRATION.md"
    if mcp_plan.exists():
        plan_text = mcp_plan.read_text(encoding="utf-8")
        for tool_name, args in mcp_tools.items():
            if f"`{tool_name}`" not in plan_text:
                errors.append(f"docs/PLAN_MCP_INTEGRATION.md is missing documentation for MCP tool `{tool_name}`")

    return errors


def main():
    print("=" * 70)
    print("RetailOps Documentation Contract & Integrity Validator")
    print("=" * 70)

    dataset_errors = check_datasets()
    stale_head_errors = check_stale_git_head()
    link_errors = check_links_and_markdown_rules()
    ast_tool_errors = check_ast_tools_contract()

    all_errors = dataset_errors + stale_head_errors + link_errors + ast_tool_errors

    print(f"1. Dataset integrity check: {'FAIL' if dataset_errors else 'PASS'}")
    for err in dataset_errors:
        print(f"   - {err}")

    print(f"2. Stale Git HEAD check: {'FAIL' if stale_head_errors else 'PASS'}")
    for err in stale_head_errors:
        print(f"   - {err}")

    print(f"3. Link & markdown rules check: {'FAIL' if link_errors else 'PASS'}")
    for err in link_errors:
        print(f"   - {err}")

    print(f"4. AST Dynamic tool contract check: {'FAIL' if ast_tool_errors else 'PASS'}")
    for err in ast_tool_errors:
        print(f"   - {err}")

    print("=" * 70)
    if all_errors:
        print(f"FAILED: Found {len(all_errors)} contract violation(s).")
        sys.exit(1)
    else:
        print("SUCCESS: All documentation contracts are valid and truthful.")
        sys.exit(0)


if __name__ == "__main__":
    main()
