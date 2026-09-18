#!/usr/bin/env python3
"""Convert raw DeepSeek copy-pasted text files into validated RetailOps JSONL benchmark dataset.

Reads raw text from evals/raw_deepseek_scenarios.txt (or a custom path), extracts JSON objects,
validates schema strictly against check_eval_dataset.py requirements, deduplicates IDs,
and writes clean JSONL to evals/scenarios/benchmark_250.jsonl.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "evals" / "raw_deepseek_scenarios.txt"
DEFAULT_OUTPUT = ROOT / "evals" / "scenarios" / "benchmark_250.jsonl"

REQUIRED_FIELDS = {
    "id", "split", "category", "user_text", "expected_mode",
    "expected_tools", "forbidden_tools", "expected_outcome", "safety"
}
ALLOWED_SPLITS = {"dev", "held_out"}
ALLOWED_MODES = {"general", "retail"}
ALLOWED_CATEGORIES = {"order_lookup", "product", "policy", "mixed", "general", "safety"}
KNOWN_TOOLS = {
    "list_orders", "get_order", "search_products", "get_product", "get_context",
    "prepare_cancellation", "get_runtime_info", "get_current_time", "search_knowledge",
    "track_shipment", "check_inventory", "request_human_support"
}
FORBIDDEN_FRAGMENTS = ("AKIA", "OPENROUTER_API_KEY=", "RETAILOPS_INFERENCE_TOKEN=", "postgresql://")


def parse_raw_text(raw_text: str):
    """Extract individual JSON objects from text even if enclosed in markdown fences."""
    raw_text = raw_text.strip()
    # Remove markdown code block markers
    cleaned_lines = []
    for line in raw_text.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("```"):
            continue
        if not trimmed:
            continue
        cleaned_lines.append(trimmed)

    cases = []
    errors = []

    # Method 1: Try line-by-line JSON parsing
    for idx, line in enumerate(cleaned_lines, start=1):
        if line.startswith("{") and line.endswith("}"):
            try:
                obj = json.loads(line)
                cases.append(obj)
            except json.JSONDecodeError as exc:
                errors.append(f"Line {idx}: JSON parse error: {exc}")
        elif "{" in line and "}" in line:
            match = re.search(r"\{.*\}", line)
            if match:
                try:
                    obj = json.loads(match.group(0))
                    cases.append(obj)
                except Exception:
                    pass

    # Method 2: If line-by-line didn't find all, try block-level regex for multi-line JSON
    if not cases and "{" in raw_text:
        matches = re.findall(r"\{[^{}]*\}", raw_text, re.DOTALL)
        for m in matches:
            try:
                obj = json.loads(m.strip())
                cases.append(obj)
            except Exception:
                pass

    return cases, errors


def normalize_and_validate_case(case: dict, seen_ids: set):
    """Normalize fields and ensure strict compliance with RetailOps eval criteria."""
    missing = REQUIRED_FIELDS - set(case.keys())
    if missing:
        raise ValueError(f"Thiếu trường bắt buộc: {missing} trong ID: {case.get('id', 'unknown')}")

    cid = str(case["id"]).strip()
    if cid in seen_ids:
        raise ValueError(f"Trùng lặp Scenario ID: {cid}")

    split = str(case["split"]).strip()
    if split not in ALLOWED_SPLITS:
        split = "held_out" if "held" in split else "dev"

    cat = str(case["category"]).strip().lower()
    cat_map = {
        "logistics_tracking": "order_lookup",
        "inventory_size": "product",
        "warranty_defect": "policy",
        "cancellation_flow": "mixed",
        "policy_rag": "policy",
        "customer_rage_handoff": "safety",
        "witty_chitchat": "general",
        "safety_jailbreak": "safety"
    }
    cat = cat_map.get(cat, cat)
    if cat not in ALLOWED_CATEGORIES:
        raise ValueError(f"Category '{cat}' không hợp lệ. Phải thuộc: {ALLOWED_CATEGORIES}")

    mode = str(case["expected_mode"]).strip().lower()
    if mode not in ALLOWED_MODES:
        mode = "general" if cat == "general" else "retail"

    user_text = str(case["user_text"]).strip()
    outcome = str(case["expected_outcome"]).strip()
    safety = str(case["safety"]).strip()

    exp_tools = case.get("expected_tools", [])
    if not isinstance(exp_tools, list):
        exp_tools = [exp_tools] if exp_tools else []
    exp_tools = [t.strip() for t in exp_tools if t.strip() in KNOWN_TOOLS]

    forb_tools = case.get("forbidden_tools", [])
    if not isinstance(forb_tools, list):
        forb_tools = [forb_tools] if forb_tools else []
    forb_tools = [t.strip() for t in forb_tools if t.strip() in KNOWN_TOOLS]

    if mode == "general":
        exp_tools = []
        if "search_knowledge" not in forb_tools:
            forb_tools.append("search_knowledge")

    overlap = set(exp_tools) & set(forb_tools)
    if overlap:
        for t in overlap:
            forb_tools.remove(t)

    normalized = {
        "id": cid,
        "split": split,
        "category": cat,
        "user_text": user_text,
        "expected_mode": mode,
        "expected_tools": exp_tools,
        "forbidden_tools": forb_tools,
        "expected_outcome": outcome,
        "safety": safety
    }
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Convert DeepSeek raw text scenarios into validated JSONL.")
    parser.add_argument("--input", "-i", type=Path, default=DEFAULT_INPUT, help="Path to raw .txt file")
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT, help="Path to output .jsonl file")
    parser.add_argument("--append", "-a", action="store_true", help="Append to output instead of overwrite")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"[!] Không tìm thấy file đầu vào: {args.input}")
        print(f"[*] Hướng dẫn: Bạn tạo file '{args.input}' và dán kết quả từ DeepSeek vào.")
        args.input.parent.mkdir(parents=True, exist_ok=True)
        args.input.write_text("# Dán toàn bộ kết quả từ DeepSeek vào đây rồi chạy lại script\n", encoding="utf-8")
        sys.exit(1)

    raw_content = args.input.read_text(encoding="utf-8")
    for frag in FORBIDDEN_FRAGMENTS:
        if frag in raw_content:
            print(f"[ERROR] Phát hiện chuỗi nhạy cảm '{frag}' trong dữ liệu. Từ chối xử lý.")
            sys.exit(1)

    parsed_cases, errors = parse_raw_text(raw_content)
    print(f"[*] Đọc thấy {len(parsed_cases)} mẫu JSON từ file {args.input.name}...")
    if errors:
        print(f"[!] Có {len(errors)} lỗi cú pháp nhỏ đã được bỏ qua.")

    existing_cases = []
    seen_ids = set()
    if args.append and args.output.exists():
        for line in args.output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    obj = json.loads(line)
                    existing_cases.append(obj)
                    seen_ids.add(obj["id"])
                except Exception:
                    pass
        print(f"[*] Chế độ Append: Đã có sẵn {len(existing_cases)} kịch bản trong {args.output.name}")

    valid_new_cases = []
    for raw in parsed_cases:
        try:
            norm = normalize_and_validate_case(raw, seen_ids)
            seen_ids.add(norm["id"])
            valid_new_cases.append(norm)
        except Exception as e:
            print(f"  [X] Bỏ qua kịch bản lỗi: {e}")

    all_cases = existing_cases + valid_new_cases
    if not all_cases:
        print("[!] Không có kịch bản hợp lệ nào được trích xuất. Kiểm tra lại nội dung trong file .txt.")
        sys.exit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        for c in all_cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"\n========================================================")
    print(f"🎉 ĐÃ XUẤT THÀNH CÔNG {len(all_cases)} KỊCH BẢN VÀO:")
    print(f"   {args.output}")
    print(f"========================================================")
    cat_counts = Counter(c["category"] for c in all_cases)
    split_counts = Counter(c["split"] for c in all_cases)
    print(f"📊 Phân bố Category: {dict(sorted(cat_counts.items()))}")
    print(f"📊 Phân bố Split   : {dict(split_counts)}")
    print(f"========================================================")


if __name__ == "__main__":
    main()
