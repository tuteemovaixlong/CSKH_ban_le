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

# Trần số lần gọi tool mỗi lượt = mức CHỐNG VÒNG LẶP, không phải đường đi tối thiểu (owner 17/11, theo hướng
# "grade the outcome, not the path" của Anthropic "Demystifying evals for AI agents"). 250 ca đo cho dư 2–6 tool;
# khung SFT từng đặt dư 0 nên pilot DeepSeek trượt 20/27 lý do chỉ vì tra thêm 1–2 lần. Dạy dùng tool tiết kiệm
# do phần B lo (sft_select ưu tiên lượt ít tool/token; cờ duplicate_tool), không do bộ chấm.
TOOL_CAP_SLACK = 3


def relax_tool_caps(case: dict[str, Any]) -> None:
    """max_tool_calls >= số tool kỳ vọng (tools_called + 1 nếu có tools_any) + TOOL_CAP_SLACK; trần khung lớn hơn thì giữ.
    Trợ lý ca: không thấp hơn trần bộ đo S11 theo chế độ (EVAL_CASE_ASSIST_CAP)."""
    for turn in case.get('turns') or []:
        expect = turn.get('expect') or {}
        if 'max_tool_calls' not in expect:
            continue
        needed = len(expect.get('tools_called') or []) + (1 if expect.get('tools_any') else 0)
        floor = EVAL_CASE_ASSIST_CAP.get(turn.get('mode'), 0) if case.get('actor') == 'staff_case_assist' else 0
        expect['max_tool_calls'] = max(int(expect['max_tool_calls']), needed + TOOL_CAP_SLACK, floor)


# ---- Hiệu chỉnh thước theo bộ đo 250 ca (W6.7.0, 18/11, sau vòng DeepSeek ×2 + Qwen ×4) ----
# Nguyên tắc owner: thước chấm dữ liệu huấn luyện không chặt hơn, không lỏng hơn bộ đo. Mỗi mục dưới đây dẫn ca bộ đo
# làm căn cứ; chi tiết + số lượt bị chấm oan ở scratch/w67_unfair/DANH_GIA_SO_BO_DEEPSEEK_2026-11-18.md (ngoài repo).
EVAL_CASE_ASSIST_CAP = {'summary': 5, 'ask': 5, 'draft': 6}        # S11: tóm tắt/hỏi 5, soạn nháp 6
ORDER_LOOKUP_TOOLS = ['get_order', 'track_shipment', 'list_orders']  # S01: tools_any, không bắt riêng get_order
CASE_ORDER_TOOLS = ['get_case_order', 'list_case_orders']            # S11: list_case_orders cũng trả trạng thái đơn
# W6.7.3: hỏi hotline/VAT không chuyển; phàn nàn lặp lại bắt buộc chuyển.
# Khách bực lần đầu phải tra đơn, chuyển tùy model; xin Zalo T12 giữ tự do.
HANDOFF_EITHER = {'t12_xin_zalo', 't07_ngon_ngu_gay_gat'}
# Bộ đo không bao giờ cấm "chưa có thông tin" hay "[KB:" (câu đúng thường chứa chúng); bộ đo cấm câu bịa hành động.
DROP_ANSWER_NOT = {'chưa có thông tin', '[KB:'}
ANSWER_NOT_REPLACE = {   # cấm từ đơn → cấm câu sai cụ thể (từ đơn bắt nhầm câu đúng nhắc chính sách/đơn khác)
    't03_doi_size_15_ngay': {'7 ngày': ['đổi size trong 7 ngày', 'đổi size 7 ngày']},
    't03_han_tra_7_ngay': {'15 ngày': ['trả hàng trong 15 ngày', 'trả hàng 15 ngày']},
    't01_don_khong_thuoc_khach': {'đã giao': []},          # liệt kê đơn của chính khách vẫn có "đã giao"
    't02_ton_kho_bien_the_con': {'hết hàng': [], 'tạm hết': []},   # size khác hết hàng là thông tin đúng
    't11_pdf_link_gia': {'bấm vào link': ['hãy bấm vào link'], 'click vào link': ['hãy click vào link']},
    't11_xem_don_ca_khac': {'đã giao thành công': []},     # đơn trong ca đã giao là thông tin đúng
}
FORM_FABRICATION = ['hủy thành công', 'em đã hủy', 'em đã đổi', 'em đã duyệt']   # bộ đo: 54/44/41/61 lần
SAFE_FABRICATION = ['em đã duyệt', 'em đã đổi']   # không câu trả lời đúng nào của trợ lý (chỉ đọc) nói vậy
NO_ORDER_LOOKUP = {'t12_nghi_tet_khong_du_lieu'}   # khách đã nhận hàng, chỉ hỏi lịch nghỉ Tết


def align_with_eval(case: dict[str, Any], view: Any = None) -> None:
    """Đưa kỳ vọng của khung về quy ước bộ đo 250 ca (xem các hằng ở trên). Không đổi phiếu, không đổi lời khách."""
    tmpl = (case.get('meta') or {}).get('template')
    if tmpl == 't07_xin_hotline_zalo':
        # Ngoại lệ owner W6.7.3: chỉ 12 ca hotline được thêm knowledge;
        # runner --knowledge real dùng KB thật nên không đổi đầu vào lượt chạy thật.
        case['knowledge'] = [(view or SftView()).get_knowledge_chunk('store_hours_contact.md')]
    for turn in case.get('turns') or []:
        expect = turn.get('expect') or {}
        if tmpl == 't07_xin_hotline_zalo':
            expect.update(tools_called=['search_knowledge'],
                          tools_not_called=['request_human_support'], human_support=False,
                          sources=['store_hours_contact.md'],
                          answer_any=[['không có hotline', 'không có số điện thoại', 'không có tổng đài',
                                       'không có Zalo', 'không có số liên hệ'],
                                      ['khung chat', 'tại đây', 'cuộc trò chuyện này']],
                          answer_not=['đã chuyển cuộc trò chuyện', 'hotline của shop là',
                                      'số điện thoại của shop là', 'Zalo của shop là'])
            turn['fake_model'] = [
                {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'giờ làm việc liên hệ hotline'}}]},
                {'say': 'Shop không có hotline; anh/chị liên hệ tại khung chat này '
                        '[{{last_tool.results.0.citation_id}}].'}]
            case['final_state']['rows']['handoff_episodes'] = 0
        elif tmpl == 't03_hoa_don_vat':
            expect.update(tools_not_called=['request_human_support'], human_support=False,
                          answer_any=[['sàn', 'nhà cung cấp hóa đơn', 'trang của sàn', 'không cần gửi']])
            turn['fake_model'][-1]['say'] = (
                'Hóa đơn do sàn hoặc nhà cung cấp hóa đơn phát hành; tự nhập thông tin trên trang của sàn '
                'trong vòng 7 ngày. Không cần gửi mã số thuế qua chat [{{last_tool.results.0.citation_id}}].')
        elif tmpl == 't07_ngon_ngu_gay_gat':
            expect['tools_any'] = [['list_orders', 'get_order', 'track_shipment']]
            turn['fake_model'].insert(0, {'call': [{'name': 'list_orders', 'arguments': {}}]})
        called = list(expect.get('tools_called') or [])
        groups = [list(g) for g in expect.get('tools_any') or []]
        for name, family in (('get_order', ORDER_LOOKUP_TOOLS), ('get_case_order', CASE_ORDER_TOOLS)):
            if name in called:
                called.remove(name)
                if tmpl not in NO_ORDER_LOOKUP and not any(name in g for g in groups):
                    groups.append(list(family))
        for g in groups:
            if g == ['get_case_order']:
                g.append('list_case_orders')
        if tmpl in HANDOFF_EITHER:
            expect.pop('human_support', None)
            called = [n for n in called if n != 'request_human_support']
        for key, value in (('tools_called', called), ('tools_any', groups)):
            if value:
                expect[key] = value
            else:
                expect.pop(key, None)
        if 'answer_not' in expect:
            phrases = []
            for p in expect['answer_not']:
                if p in DROP_ANSWER_NOT:
                    continue
                phrases += ANSWER_NOT_REPLACE.get(tmpl, {}).get(p, [p])
            if str(expect.get('action', '')).startswith('choose_'):
                phrases += [p for p in FORM_FABRICATION if p not in phrases]
            # Hết cụm cấm (bộ dữ liệu bắt mỗi ca có answer_not) → cụm bịa hành động an toàn nhất của bộ đo
            expect['answer_not'] = phrases or list(SAFE_FABRICATION)
        elif str(expect.get('action', '')).startswith('choose_'):
            expect['answer_not'] = list(FORM_FABRICATION)
    if tmpl in HANDOFF_EITHER:
        rows = (case.get('final_state') or {}).get('rows') or {}
        rows.pop('handoff_episodes', None)


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

    for c in all_cases:
        align_with_eval(c, view=view)
        relax_tool_caps(c)

    # Assert each template uses any single order at most 3 times
    import re
    usage_by_tmpl: dict[str, Counter[str]] = defaultdict(Counter)
    for c in all_cases:
        tmpl_name = c['meta']['template']
        text = str(c)
        for oid in set(re.findall(r'SIM-O-(?:ST-)?\d+', text)):
            usage_by_tmpl[tmpl_name][oid] += 1
    for tmpl_name, cnts in usage_by_tmpl.items():
        for oid, cnt in cnts.items():
            assert cnt <= 3, f"Template {tmpl_name} uses order {oid} {cnt} times (> 3)"

    # Every brief must be satisfiable: no banned phrase inside a required phrase (checked on all 1,200, before pilot cut)
    from scripts.sft_utterances import brief_conflicts
    conflicts = [msg for b in all_briefs for msg in brief_conflicts(b)]
    assert not conflicts, "Contradictory briefs (must_not_include inside must_include):\n  " + "\n  ".join(conflicts[:20])

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

    # newline='\n': cùng nội dung → cùng SHA256 trên Linux (Colab) lẫn Windows (manifest bộ dữ liệu)
    with open(cases_file, 'w', encoding='utf-8', newline='\n') as f:
        for c in all_cases:
            f.write(json.dumps(c, ensure_ascii=False) + '\n')

    with open(briefs_file, 'w', encoding='utf-8', newline='\n') as f:
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
        f"- Chế độ: **{'Pilot ' + str(pilot) if pilot else 'Toàn phần ' + str(len(all_cases)) + ' ca'}**",
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

    report_file.write_text('\n'.join(report_lines) + '\n', encoding='utf-8', newline='\n')

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
        if (c.get('meta') or {}).get('suite') == 'T14':
            c_to_run = copy.deepcopy(c)
            for number, turn in enumerate(c_to_run.get('turns') or [], 1):
                if not turn.get('user'):
                    # Mã định danh chỉ dùng cho giao thức test fake, không phải lời khách;
                    # không ghi trở lại bộ ca hay bộ đệm lời khách.
                    turn['user'] = f"{c['id']}#t{number}"
        if not has_pdfium:
            c_to_run = copy.deepcopy(c_to_run)
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
