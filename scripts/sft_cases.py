"""SFT case generator and fake runner consistency checker (sft_v1).

W6.7.0 Part A.
CLI:
  python scripts/sft_cases.py generate --out <dir> [--pilot 100] [--seed 20261202]
  python scripts/sft_cases.py check --out <dir>
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sft_dataset import STYLES, validate_train_case, validate_train_set
from scripts.sft_templates import TEMPLATES, BaseTemplate, Brief, SftView

DEFAULT_SEED = 20261202


def generate_cases(
    out_dir: Path | str,
    *,
    pilot: int | None = None,
    seed: int = DEFAULT_SEED,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Path]:
    target_dir = Path(out_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)
    view = SftView()

    # Create balanced style schedule across 1,200 cases
    # chuan: 480, teencode: 240, khong_dau: 180, sai_chinh_ta: 180, dai: 120
    style_pool: list[str] = (
        ['chuan'] * 480
        + ['teencode'] * 240
        + ['khong_dau'] * 180
        + ['sai_chinh_ta'] * 180
        + ['dai'] * 120
    )
    rng.shuffle(style_pool)
    style_iter = iter(style_pool)

    all_cases: list[dict[str, Any]] = []
    all_briefs: list[dict[str, Any]] = []

    case_counter_by_suite: Counter[str] = Counter()

    for tmpl_id, tmpl in TEMPLATES.items():
        slots = tmpl.select(view)
        assert slots, f"Template {tmpl_id} returned no slots from SftView"
        for i in range(tmpl.target):
            case_counter_by_suite[tmpl.suite] += 1
            case_idx = case_counter_by_suite[tmpl.suite]
            slot = slots[i % len(slots)]
            try:
                style = next(style_iter)
            except StopIteration:
                style = rng.choice(tmpl.allowed_styles)

            case, briefs = tmpl.build(slot, rng, case_idx, style, view=view)
            all_cases.append(case)
            all_briefs.extend(b.to_dict() for b in briefs)

    # Assert each template uses any single order at most 3 times
    import re
    usage_by_tmpl: dict[str, Counter[str]] = defaultdict(Counter)
    for c in all_cases:
        tmpl_name = c['meta']['template']
        text = str(c)
        for oid in set(re.findall(r'SIM-O-\d+', text)):
            usage_by_tmpl[tmpl_name][oid] += 1
    for tmpl_name, cnts in usage_by_tmpl.items():
        for oid, cnt in cnts.items():
            assert cnt <= 3, f"Template {tmpl_name} uses order {oid} {cnt} times (> 3)"

    # If pilot mode is requested (e.g. 100 or 24)
    if pilot is not None:
        pilot_n = int(pilot)
        assert 12 <= pilot_n <= len(all_cases), f"Invalid pilot count {pilot_n}"

        # Group cases by suite, then by template
        cases_by_suite_tmpl: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for c in all_cases:
            s = c['meta']['suite']
            t = c['meta']['template']
            cases_by_suite_tmpl.setdefault(s, {}).setdefault(t, []).append(c)

        if pilot_n == 100:
            # Exact stratified targets for 100: each >= 5, total 100
            # T01: 8, T02: 8, T03: 9, T04: 8, T05: 8, T06: 8, T07: 5, T08: 12, T09: 7, T10: 5, T11: 15, T12: 7
            pilot_targets = {
                'T01': 8, 'T02': 8, 'T03': 9, 'T04': 8, 'T05': 8, 'T06': 8,
                'T07': 5, 'T08': 12, 'T09': 7, 'T10': 5, 'T11': 15, 'T12': 7,
            }
        else:
            pilot_targets = {}
            for s in sorted(cases_by_suite_tmpl.keys()):
                s_total = sum(len(c_list) for c_list in cases_by_suite_tmpl[s].values())
                cnt = max(1, round(s_total / len(all_cases) * pilot_n))
                pilot_targets[s] = cnt
            # Adjust if sum != pilot_n
            diff = pilot_n - sum(pilot_targets.values())
            for s in sorted(cases_by_suite_tmpl.keys()):
                if diff == 0:
                    break
                if diff > 0:
                    pilot_targets[s] += 1
                    diff -= 1
                elif diff < 0 and pilot_targets[s] > 1:
                    pilot_targets[s] -= 1
                    diff += 1

        selected_cases: list[dict[str, Any]] = []
        style_counts: Counter[str] = Counter()

        for s, target_cnt in pilot_targets.items():
            tmpl_dict = cases_by_suite_tmpl.get(s, {})
            tmpl_list = list(tmpl_dict.keys())
            if not tmpl_list:
                continue
            chosen_in_suite: list[dict[str, Any]] = []
            tmpl_used_idx = Counter()
            while len(chosen_in_suite) < target_cnt:
                progress = False
                for tmpl_id in tmpl_list:
                    if len(chosen_in_suite) >= target_cnt:
                        break
                    cases_for_tmpl = tmpl_dict[tmpl_id]
                    idx = tmpl_used_idx[tmpl_id]
                    if idx < len(cases_for_tmpl):
                        avail_candidates = cases_for_tmpl[idx:]
                        avail_candidates_sorted = sorted(avail_candidates, key=lambda c: style_counts[c['meta']['style']])
                        picked = avail_candidates_sorted[0]
                        cases_for_tmpl.remove(picked)
                        cases_for_tmpl.insert(idx, picked)
                        tmpl_used_idx[tmpl_id] += 1

                        chosen_in_suite.append(picked)
                        style_counts[picked['meta']['style']] += 1
                        progress = True
                if not progress:
                    break
            selected_cases.extend(chosen_in_suite)

        all_cases = selected_cases
        case_ids = {c['id'] for c in all_cases}
        all_briefs = [b for b in all_briefs if b['case_id'] in case_ids]

    # Validate all cases
    validate_train_set(all_cases)

    # Write files
    cases_file = target_dir / 'cases_sft_v1.jsonl'
    briefs_file = target_dir / 'briefs_sft_v1.jsonl'
    report_file = target_dir / 'generate_report.md'

    with open(cases_file, 'w', encoding='utf-8') as f:
        for c in all_cases:
            f.write(json.dumps(c, ensure_ascii=False) + '\n')

    with open(briefs_file, 'w', encoding='utf-8') as f:
        for b in all_briefs:
            f.write(json.dumps(b, ensure_ascii=False) + '\n')

    # Generate Markdown report
    suite_counts = Counter(c['meta']['suite'] for c in all_cases)
    style_counts = Counter(c['meta']['style'] for c in all_cases)
    template_counts = Counter(c['meta']['template'] for c in all_cases)

    report_lines = [
        "# Báo Cáo Sinh Khung Ca SFT v1",
        f"- Tổng số ca: **{len(all_cases)}**",
        f"- Tổng số phiếu lời khách (briefs): **{len(all_briefs)}**",
        f"- Chế độ: **{'Pilot ' + str(pilot) if pilot else 'Toàn phần 1.200 ca'}**",
        f"- Seed: `{seed}`",
        f"- Số khung sử dụng: **{len(template_counts)}**",
        "",
        "## Phân bổ theo bộ",
        "| Bộ | Số ca |",
        "|---|---|",
    ]
    for s in sorted(suite_counts.keys()):
        report_lines.append(f"| {s} | {suite_counts[s]} |")

    report_lines.extend([
        "",
        "## Phân bổ theo giọng văn",
        "| Giọng văn | Số ca | Tỉ lệ |",
        "|---|---|---|",
    ])
    for st, count in sorted(style_counts.items()):
        report_lines.append(f"| {st} | {count} | {count / len(all_cases):.1%} |")

    report_lines.extend([
        "",
        "## Thống kê số ca mỗi khung",
        "| Khung (Template ID) | Số ca |",
        "|---|---|",
    ])
    for tid, count in sorted(template_counts.items()):
        report_lines.append(f"| `{tid}` | {count} |")

    report_file.write_text('\n'.join(report_lines) + '\n', encoding='utf-8')

    return all_cases, all_briefs, report_file


def check_cases(out_dir: Path | str, cases_path: Path | str | None = None) -> dict[str, Any]:
    import copy
    import importlib.util
    from scripts.run_agent_scenarios import ScriptedGateway, run_scenario

    has_pdfium = importlib.util.find_spec('pypdfium2') is not None

    target_dir = Path(out_dir).resolve()
    cases_file = Path(cases_path).resolve() if cases_path else target_dir / 'cases_sft_v1.jsonl'
    assert cases_file.is_file(), f"Cases file not found: {cases_file}"

    cases: list[dict[str, Any]] = []
    for line in cases_file.read_text(encoding='utf-8').splitlines():
        if line.strip():
            cases.append(json.loads(line))

    assert cases, "Empty cases file"

    passed_count = 0
    failures_by_case: dict[str, list[str]] = {}

    for idx, c in enumerate(cases, 1):
        c_to_run = c
        if not has_pdfium:
            c_to_run = copy.deepcopy(c)
            # Flatten text_pdf attachments into message text for environments without pypdfium2
            if c_to_run.get('actor') == 'staff_case_assist':
                for msg in c_to_run.get('case_setup', {}).get('customer_messages', []):
                    att = msg.get('attachment')
                    if isinstance(att, dict) and att.get('kind') == 'text_pdf':
                        pages = att.get('pages', [])
                        pdf_txt = '\n' + '\n'.join(f'[Trang {i}] {p}' for i, p in enumerate(pages, 1))
                        msg['text'] = (msg.get('text') or '') + pdf_txt
                        del msg['attachment']
            for turn in c_to_run.get('turns', []):
                att = turn.get('attachment')
                if isinstance(att, dict) and att.get('kind') == 'text_pdf':
                    pages = att.get('pages', [])
                    pdf_txt = '\n' + '\n'.join(f'[Trang {i}] {p}' for i, p in enumerate(pages, 1))
                    turn['user'] = (turn.get('user') or '') + pdf_txt
                    del turn['attachment']

        gw = ScriptedGateway()
        res = run_scenario(c_to_run, gw, mode='fake')

        # Check for answer_check drops or audits
        check_fails = []
        for t_idx, t_res in enumerate(res.get('turns', []), 1):
            if t_res.get('answer_check'):
                check_fails.append(f"turn {t_idx} dropped claims: {t_res['answer_check']}")
            if t_res.get('answer_check_audit'):
                check_fails.append(f"turn {t_idx} audit flag: {t_res['answer_check_audit']}")

        if res['passed'] and not check_fails:
            passed_count += 1
        else:
            all_fails = list(res.get('failures', [])) + check_fails
            failures_by_case[c['id']] = all_fails

    pass_rate = passed_count / len(cases)
    result = {
        'total_cases': len(cases),
        'passed': passed_count,
        'failed': len(failures_by_case),
        'pass_rate': pass_rate,
        'failures': failures_by_case,
    }

    if failures_by_case:
        print(f"FAILED: {len(failures_by_case)}/{len(cases)} cases failed consistency check:")
        for cid, fails in list(failures_by_case.items())[:10]:
            print(f"  {cid}: {fails}")
        sys.exit(1)

    print(f"SUCCESS: 100% ({passed_count}/{len(cases)}) scenarios passed fake runner check.")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and check SFT training cases")
    subparsers = parser.add_subparsers(dest="command")

    p_gen = subparsers.add_parser("generate", help="Generate SFT cases and briefs")
    p_gen.add_argument("--out", required=True, help="Output directory")
    p_gen.add_argument("--pilot", type=int, default=None, help="Pilot count (e.g. 100)")
    p_gen.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Random seed")

    p_chk = subparsers.add_parser("check", help="Check consistency of cases using fake runner")
    p_chk.add_argument("--out", required=True, help="Directory containing cases_sft_v1.jsonl")
    p_chk.add_argument("--cases", default=None, help="Specific cases file path")

    args = parser.parse_args()

    if args.command == "generate":
        cases, briefs, rep = generate_cases(args.out, pilot=args.pilot, seed=args.seed)
        suite_cnts = Counter(c['meta']['suite'] for c in cases)
        style_cnts = Counter(c['meta']['style'] for c in cases)
        print(f"Generated {len(cases)} cases, {len(briefs)} briefs.")
        print(f"Suites: {dict(sorted(suite_cnts.items()))}")
        print(f"Styles: {dict(sorted(style_cnts.items()))}")
        print(f"Report written to: {rep}")
        return 0

    if args.command == "check":
        check_cases(args.out, cases_path=args.cases)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
