#!/usr/bin/env python3
"""W6.7.2 mục F: Xuất đoạn chữ Hán/Nhật/Hàn trong mẫu SFT ra CSV để owner sửa tay và nhập lại thành lớp phủ.

Code KHÔNG điền cột `sua_thanh`, không gợi ý chữ thay, và không sửa vết gốc.

Subcommands:
  export  Xuất các đoạn CJK từ vết gốc của các mẫu trong selection.json ra CSV (UTF-8 BOM, không ghi đè)
  import  Kiểm bản CSV owner đã sửa và ghi lớp phủ owner_edits_cjk.jsonl cho sft_build
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import eval_regrade, sft_select  # noqa: E402

CJK_RE = sft_select.CJK_RE
CJK_SPAN_RE = sft_select.CJK_SPAN_RE
CSV_FIELDS = ['stt', 'ma_mau', 'luot', 'truong', 'chu_han', 'doan_chua', 'sua_thanh']
CONTEXT_WINDOW = 50
OVERLAY_CONTEXT = 20
MAX_FIX_CHARS = 40
DELETE_SENTINEL = '(xóa)'
LEFT_SPACE_PUNCT = ',;:.!?)'


def _run_assistant_texts(
    calls: dict[tuple[Any, Any, Any], list[dict[str, Any]]],
    cid: str,
    run_no: int,
    turns_count: int,
) -> list[str]:
    """Thu mọi chuỗi văn bản trợ lý (content + reasoning_content/reasoning) từ vết gốc của một lượt chạy."""
    texts: list[str] = []
    for t in range(1, turns_count + 1):
        for call in calls.get((cid, run_no, t), []):
            resp = call.get('response') or {}
            texts.append(str(resp.get('content') or ''))
            r_resp = resp.get('reasoning_content')
            if r_resp is None:
                r_resp = resp.get('reasoning')
            texts.append(str(r_resp or ''))
            for msg in (call.get('request') or {}).get('messages') or []:
                if msg.get('role') == 'assistant':
                    texts.append(str(msg.get('content') or ''))
                    r_msg = msg.get('reasoning_content')
                    if r_msg is None:
                        r_msg = msg.get('reasoning')
                    texts.append(str(r_msg or ''))
    return texts


def _load_calls_for_models(
    scores_data: dict[str, Any],
    models: set[str],
    extra_run_dirs: dict[str, str] | None = None,
) -> dict[str, dict[tuple[Any, Any, Any], list[dict[str, Any]]]]:
    run_dirs = dict(scores_data.get('run_dirs') or {})
    if extra_run_dirs:
        run_dirs.update({k: v for k, v in extra_run_dirs.items() if v})
    calls_by_model: dict[str, dict[tuple[Any, Any, Any], list[dict[str, Any]]]] = {}
    for model in sorted(models):
        rdir = run_dirs.get(model)
        if not rdir:
            raise ValueError(f'Thiếu run_dir cho model {model!r}')
        _, _, calls = eval_regrade.load_run(Path(rdir))
        calls_by_model[model] = calls
    return calls_by_model


def export_cjk(
    scores_path: Path,
    selection_path: Path,
    out_csv: Path,
) -> dict[str, Any]:
    """Xuất các đoạn CJK từ vết gốc của các mẫu trong selection.json ra tệp CSV (không ghi đè)."""
    if out_csv.exists():
        raise FileExistsError(f'{out_csv} đã tồn tại — không ghi đè')

    scores_data = json.loads(scores_path.read_text(encoding='utf-8'))
    selection = json.loads(selection_path.read_text(encoding='utf-8'))

    selected_entries = selection.get('selected') or []
    unique_samples: dict[tuple[str, str, int], dict[str, Any]] = {}
    extra_run_dirs: dict[str, str] = dict(selection.get('run_dirs') or {})
    for entry in selected_entries:
        cid = entry['case_id']
        model = entry.get('model') or entry['source_model']
        run_no = int(entry['run'])
        if entry.get('run_dir'):
            extra_run_dirs.setdefault(model, str(entry['run_dir']))
        unique_samples.setdefault((cid, model, run_no), entry)

    needed_models = {m for _, m, _ in unique_samples}
    calls_by_model = _load_calls_for_models(scores_data, needed_models, extra_run_dirs)

    rows: list[dict[str, Any]] = []
    for (cid, model, run_no), entry in sorted(unique_samples.items()):
        case_info = (scores_data.get('cases') or {}).get(cid) or {}
        turns_count = int(case_info.get('turns_count') or entry.get('turns_count') or 1)
        calls = calls_by_model[model]
        seen: set[tuple[str, str, str]] = set()

        for t in range(1, turns_count + 1):
            stops = [
                c for c in calls.get((cid, run_no, t), [])
                if (c.get('response') or {}).get('finish_reason') == 'stop'
            ]
            if not stops:
                continue
            last = stops[-1]
            resp = last.get('response') or {}
            resp_reasoning = resp.get('reasoning_content')
            if resp_reasoning is None:
                resp_reasoning = resp.get('reasoning')
            texts: list[tuple[str, str]] = [
                ('tra_loi', str(resp.get('content') or '')),
                ('suy_luan', str(resp_reasoning or '')),
            ]
            for msg in (last.get('request') or {}).get('messages') or []:
                if msg.get('role') == 'assistant':
                    m_reasoning = msg.get('reasoning_content')
                    if m_reasoning is None:
                        m_reasoning = msg.get('reasoning')
                    texts.append(('tin_truoc', str(msg.get('content') or '')))
                    texts.append(('tin_truoc_suy_luan', str(m_reasoning or '')))

            for field, text in texts:
                for mt in CJK_SPAN_RE.finditer(text):
                    ctx = (
                        text[max(0, mt.start() - CONTEXT_WINDOW):mt.start()]
                        + '⟦' + mt.group() + '⟧'
                        + text[mt.end():mt.end() + CONTEXT_WINDOW]
                    )
                    base_field = 'suy_luan' if field in ('suy_luan', 'tin_truoc_suy_luan') else 'tra_loi'
                    dedup_key = (base_field, mt.group(), ctx)
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)
                    rows.append({
                        'stt': len(rows) + 1,
                        'ma_mau': f'{cid}|{model}|{run_no}',
                        'luot': t,
                        'truong': field,
                        'chu_han': mt.group(),
                        'doan_chua': ctx.replace('\n', ' ⏎ '),
                        'sua_thanh': '',
                    })

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, 'w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    return {
        'rows': len(rows),
        'samples_with_cjk': len({r['ma_mau'] for r in rows}),
        'out_csv': str(out_csv),
    }


def _build_overlay_pair(left: str, span: str, right: str, fix: str) -> tuple[str, str]:
    """Dựng cặp (old, new) theo luật (xóa) và luật thêm dấu cách cho chữ Hán dính liền chữ Việt."""
    old = left + span + right
    if fix == DELETE_SENTINEL:
        new_right = right[1:] if (left.endswith(' ') and right.startswith(' ')) else right
        return old, left + new_right
    pre = (
        ' '
        if fix and left and (left[-1].isalnum() or left[-1] in LEFT_SPACE_PUNCT) and fix[0].isalnum()
        else ''
    )
    post = (
        ' '
        if fix and right and fix[-1].isalnum() and (right[0].isalnum() or right[0] == '(')
        else ''
    )
    return old, left + pre + fix + post + right


def import_cjk(
    csv_path: Path,
    scores_path: Path,
    out_jsonl: Path,
    *,
    check_only: bool = False,
) -> tuple[int, dict[str, Any]]:
    """Kiểm bản CSV owner đã điền và xuất lớp phủ owner_edits_cjk.jsonl (không sửa vết gốc)."""
    if not csv_path.is_file():
        raise FileNotFoundError(f'Không tìm thấy tệp CSV: {csv_path}')

    with open(csv_path, encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))

    scores_data = json.loads(scores_path.read_text(encoding='utf-8'))
    cases_map = scores_data.get('cases') or {}

    needed_models: set[str] = set()
    for row in rows:
        parts = str(row.get('ma_mau') or '').split('|')
        if len(parts) == 3 and parts[1]:
            needed_models.add(parts[1])
    calls_by_model = _load_calls_for_models(scores_data, needed_models)

    problems: list[str] = []
    edits: list[dict[str, Any]] = []
    text_cache: dict[tuple[str, str, int], list[str]] = {}

    for idx, row in enumerate(rows, 1):
        n = str(row.get('stt') or idx)
        fix = str(row.get('sua_thanh') or '').strip()
        chu_han = str(row.get('chu_han') or '')
        if not fix:
            problems.append(f'dòng {n}: chưa điền sua_thanh')
            continue
        row_has_err = False
        if CJK_RE.search(fix):
            problems.append(f'dòng {n}: bản sửa vẫn còn chữ Hán/Nhật/Hàn')
            row_has_err = True
        if len(fix) > MAX_FIX_CHARS:
            problems.append(f'dòng {n}: bản sửa dài {len(fix)} ký tự (> {MAX_FIX_CHARS}) — chỉ thay đúng đoạn chữ Hán')
            row_has_err = True
        if re.search(r'\d', fix) and not re.search(r'\d', chu_han):
            problems.append(f'dòng {n}: bản sửa thêm chữ số — không thêm dữ kiện mới')
            row_has_err = True

        ctx_raw = str(row.get('doan_chua') or '').replace(' ⏎ ', '\n')
        if '⟦' not in ctx_raw or '⟧' not in ctx_raw:
            problems.append(f'dòng {n}: doan_chua thiếu dấu phân tách ⟦ ⟧')
            continue
        left_full, rest = ctx_raw.split('⟦', 1)
        if '⟧' not in rest:
            problems.append(f'dòng {n}: doan_chua thiếu dấu đóng ⟧')
            continue
        span, right_full = rest.split('⟧', 1)
        left = left_full[-OVERLAY_CONTEXT:]
        right = right_full[:OVERLAY_CONTEXT]
        # Nếu có đoạn CJK khác nằm trong vùng ngữ cảnh 20 ký tự, cắt sát đoạn đó để hai lớp phủ gần nhau không ghi đè lẫn nhau.
        prev_cjk = list(CJK_SPAN_RE.finditer(left))
        if prev_cjk:
            left = left[prev_cjk[-1].end():]
        next_cjk = CJK_SPAN_RE.search(right)
        if next_cjk:
            right = right[:next_cjk.start()]

        parts = str(row.get('ma_mau') or '').split('|')
        if len(parts) != 3:
            problems.append(f"dòng {n}: ma_mau không hợp lệ {row.get('ma_mau')!r}")
            continue
        cid, model, run_str = parts
        try:
            run_no = int(run_str)
        except ValueError:
            problems.append(f"dòng {n}: run không hợp lệ trong ma_mau {row.get('ma_mau')!r}")
            continue

        key = (cid, model, run_no)
        if key not in text_cache:
            turns_count = int((cases_map.get(cid) or {}).get('turns_count') or 1)
            text_cache[key] = _run_assistant_texts(calls_by_model[model], cid, run_no, turns_count)

        old, new = _build_overlay_pair(left, span, right, fix)
        if not any(old in txt for txt in text_cache[key]):
            problems.append(f"dòng {n}: không tìm thấy đoạn gốc trong vết {row.get('ma_mau')}")
            continue
        if row_has_err:
            continue

        edits.append({
            'case_id': cid,
            'model': model,
            'run': run_no,
            'old': old,
            'new': new,
            'owner_edit': 'cjk',
            'source_csv': csv_path.name,
            'stt': int(n) if n.isdigit() else idx,
        })

    result: dict[str, Any] = {
        'rows': len(rows),
        'valid': len(edits),
        'problems': problems,
        'written': 0,
        'total_in_out': 0,
    }
    if problems:
        return 1, result
    if check_only:
        return 0, result

    existing: list[dict[str, Any]] = []
    if out_jsonl.is_file():
        for line in out_jsonl.read_text(encoding='utf-8-sig').splitlines():
            if line.strip():
                existing.append(json.loads(line))
    keep = [e for e in existing if e.get('source_csv') != csv_path.name]
    merged = keep + edits
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_jsonl.with_name(out_jsonl.name + '.tmp')
    tmp.write_text(
        ''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in merged),
        encoding='utf-8',
        newline='\n',
    )
    tmp.replace(out_jsonl)
    result['written'] = len(edits)
    result['total_in_out'] = len(merged)
    return 0, result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='sft_cjk.py', description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)

    p_exp = sub.add_parser('export', help='Xuất các đoạn chữ Hán/Nhật/Hàn trong mẫu đã chọn ra CSV (UTF-8 BOM)')
    p_exp.add_argument('--scores', required=True, type=Path, help='Tệp scores.json')
    p_exp.add_argument('--selection', required=True, type=Path, help='Tệp selection.json')
    p_exp.add_argument('--out', required=True, type=Path, help='Tệp CSV đầu ra (không ghi đè nếu đã có)')

    p_imp = sub.add_parser('import', help='Kiểm bản CSV owner đã sửa và ghi lớp phủ owner_edits_cjk.jsonl')
    p_imp.add_argument('--csv', required=True, type=Path, help='Tệp CSV đã điền cột sua_thanh')
    p_imp.add_argument('--scores', required=True, type=Path, help='Tệp scores.json')
    p_imp.add_argument('--out', required=True, type=Path, help='Tệp lớp phủ owner_edits_cjk.jsonl đầu ra')
    p_imp.add_argument('--check-only', action='store_true', help='Chỉ kiểm tra hợp lệ, không ghi tệp đầu ra')

    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == 'export':
            info = export_cjk(args.scores, args.selection, args.out)
            print(f"{info['rows']} đoạn / {info['samples_with_cjk']} mẫu -> {args.out}")
            return 0
        if args.command == 'import':
            code, res = import_cjk(args.csv, args.scores, args.out, check_only=args.check_only)
            print(f"{res['rows']} dòng | hợp lệ {res['valid']} | vấn đề {len(res['problems'])}")
            for p in res['problems'][:30]:
                print('  -', p)
            if code == 0 and not args.check_only:
                print(f"ghi {res['written']} sửa (tổng {res['total_in_out']}) -> {args.out}")
            return code
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f'Lỗi: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
