#!/usr/bin/env python3
"""Batch and Full Dataset Validator for RetailOps Evaluation Benchmark.

Validates:
1. Valid single-line JSONL format with exact 9 keys in strict order.
2. Alignment with manifest slots (RetailOps_BATCH_PLAN_250.json) for batch or full dataset.
3. Strict tool constraints (only 12 tools, disjoint sets).
4. General mode invariance (empty expected_tools, forbidden_tools includes search_knowledge).
5. No duplicate IDs, no leakages, no secret keys.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from collections import Counter

KNOWN_TOOLS = frozenset([
    "list_orders", "get_order", "search_products", "get_product", "get_context",
    "prepare_cancellation", "get_runtime_info", "get_current_time", "search_knowledge",
    "track_shipment", "check_inventory", "request_human_support"
])

REQUIRED_FIELDS = (
    "id", "split", "category", "user_text", "expected_mode",
    "expected_tools", "forbidden_tools", "expected_outcome", "safety"
)

ALLOWED_SPLITS = frozenset(["dev", "held_out"])
ALLOWED_MODES = frozenset(["retail", "general"])
ALLOWED_CATEGORIES = frozenset(["order_lookup", "product", "policy", "mixed", "general", "safety"])
FORBIDDEN_FRAGMENTS = ("AKIA", "OPENROUTER_API_KEY=", "RETAILOPS_INFERENCE_TOKEN=", "postgresql://")


def normalize_text(text: str) -> str:
    """Normalize text for duplicate prompt detection."""
    return re.sub(r"\s+", " ", text.lower().strip())


def validate_file(jsonl_path: Path, manifest_path: Path = None, batch_id: str = None, strict_general: bool = False):
    if not jsonl_path.exists():
        raise SystemExit(f"[FAIL] File not found: {jsonl_path}")

    text = jsonl_path.read_text(encoding="utf-8")
    assert not any(frag in text for frag in FORBIDDEN_FRAGMENTS), "[FAIL] File contains secret-like material"

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise SystemExit("[FAIL] File is empty")

    cases = []
    seen_ids = set()
    seen_prompts = {}
    errors = []

    for line_no, raw in enumerate(lines, start=1):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"Line {line_no}: JSONDecodeError - {exc.msg}")
            continue

        if tuple(obj.keys()) != REQUIRED_FIELDS:
            errors.append(f"Line {line_no} ({obj.get('id', 'unknown')}): Keys must strictly match {REQUIRED_FIELDS}, got {tuple(obj.keys())}")

        cid = obj.get("id", "")
        if not cid or not isinstance(cid, str):
            errors.append(f"Line {line_no}: Missing or invalid 'id'")
        elif cid in seen_ids:
            errors.append(f"Line {line_no}: Duplicate ID '{cid}'")
        seen_ids.add(cid)

        split = obj.get("split")
        if split not in ALLOWED_SPLITS:
            errors.append(f"Line {line_no} ({cid}): Invalid split '{split}'")

        category = obj.get("category")
        if category not in ALLOWED_CATEGORIES:
            errors.append(f"Line {line_no} ({cid}): Invalid category '{category}'")

        mode = obj.get("expected_mode")
        if mode not in ALLOWED_MODES:
            errors.append(f"Line {line_no} ({cid}): Invalid expected_mode '{mode}'")

        exp_tools = obj.get("expected_tools", [])
        forb_tools = obj.get("forbidden_tools", [])

        if not isinstance(exp_tools, list) or not isinstance(forb_tools, list):
            errors.append(f"Line {line_no} ({cid}): expected_tools and forbidden_tools must be lists")
        else:
            invalid_exp = set(exp_tools) - KNOWN_TOOLS
            if invalid_exp:
                errors.append(f"Line {line_no} ({cid}): Unknown expected tools: {invalid_exp}")
            invalid_forb = set(forb_tools) - KNOWN_TOOLS
            if invalid_forb:
                errors.append(f"Line {line_no} ({cid}): Unknown forbidden tools: {invalid_forb}")

            intersection = set(exp_tools) & set(forb_tools)
            if intersection:
                errors.append(f"Line {line_no} ({cid}): Tools intersect in expected and forbidden: {intersection}")

            if mode == "general":
                if exp_tools:
                    errors.append(f"Line {line_no} ({cid}): General mode must have expected_tools == []")
                if "search_knowledge" not in forb_tools:
                    errors.append(f"Line {line_no} ({cid}): General mode must forbid 'search_knowledge'")
                if strict_general and set(forb_tools) != KNOWN_TOOLS:
                    errors.append(f"Line {line_no} ({cid}): Strict general mode must forbid all 12 tools")

        norm_p = normalize_text(obj.get("user_text", ""))
        if not norm_p:
            errors.append(f"Line {line_no} ({cid}): user_text is empty")
        elif norm_p in seen_prompts:
            errors.append(f"Line {line_no} ({cid}): Prompt duplicates prompt from ID '{seen_prompts[norm_p]}'")
        else:
            seen_prompts[norm_p] = cid

        cases.append(obj)

    # Validate against Manifest if provided
    if manifest_path and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        batches = {b["batch_id"]: b for b in manifest.get("batches", [])}

        if batch_id:
            if batch_id not in batches:
                errors.append(f"Batch ID '{batch_id}' not found in manifest")
            else:
                expected_slots = batches[batch_id]["slots"]
                if len(cases) != len(expected_slots):
                    errors.append(f"Batch '{batch_id}' expects {len(expected_slots)} cases, got {len(cases)}")
                for idx, (case, slot) in enumerate(zip(cases, expected_slots)):
                    if case["id"] != slot["id"]:
                        errors.append(f"Case {idx+1}: ID mismatch. Expected '{slot['id']}', got '{case['id']}'")
                    if case["split"] != slot["split"]:
                        errors.append(f"Case '{case['id']}': Split mismatch. Expected '{slot['split']}', got '{case['split']}'")
                    if case["category"] != slot["category"]:
                        errors.append(f"Case '{case['id']}': Category mismatch. Expected '{slot['category']}', got '{case['category']}'")
                    if case["expected_mode"] != slot["expected_mode"]:
                        errors.append(f"Case '{case['id']}': Mode mismatch. Expected '{slot['expected_mode']}', got '{case['expected_mode']}'")
        else:
            # Full manifest validation
            total_expected = sum(len(b["slots"]) for b in manifest.get("batches", []))
            if len(cases) != total_expected:
                errors.append(f"Full dataset expects {total_expected} cases, got {len(cases)}")

    if errors:
        print(f"[FAIL] Found {len(errors)} validation errors:")
        for err in errors[:20]:
            print(f"  - {err}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more errors.")
        sys.exit(1)

    counts = Counter(c["category"] for c in cases)
    splits = Counter(c["split"] for c in cases)
    print(f"[PASS] {jsonl_path.name} is VALID! ({len(cases)} cases)")
    print(f"       Splits: {dict(splits)}")
    print(f"       Categories: {dict(counts)}")


def main():
    parser = argparse.ArgumentParser(description="Validate RetailOps benchmark JSONL file.")
    parser.add_argument("file", type=Path, help="Path to .jsonl file")
    parser.add_argument("--manifest", "-m", type=Path, default=None, help="Path to manifest JSON")
    parser.add_argument("--batch-id", "-b", type=str, default=None, help="Batch ID (e.g. B01) if checking single batch")
    parser.add_argument("--strict-general", action="store_true", help="Require all 12 tools to be forbidden in general mode")
    args = parser.parse_args()

    validate_file(args.file, args.manifest, args.batch_id, args.strict_general)


if __name__ == "__main__":
    main()
