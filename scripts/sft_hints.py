"""Xuất phiếu đỡ trống và kiểm/nhập nội dung do Claude soạn, owner duyệt."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sft_hint_proxy import START, END
from scripts.sft_select import _merge_adjudicated_files
from scripts.sft_utterances import extract_codes, jaccard_5gram
from scripts.sft_dataset import get_eval_user_utterances

FIELDS = ['template', 'turn', 'so_ca', 'ky_vong', 'loi_thuong_gap', 'goi_y']
CASE_FIELDS = ['case_id', 'mode', 'order_codes']
MONEY = re.compile(r'\d[\d.,\s]*(?:đ\b|₫|đồng\b|vnd\b|vnđ\b|k\b|triệu\b|nghìn\b|ngàn\b|usd\b|\$)|\$\s*\d', re.I)


def _judge_errors(paths):
    errors = defaultdict(Counter)
    seen = set()
    for path in paths:
        adj = json.loads(path.read_text(encoding='utf-8'))
        locations = [adj.get('judge_dir'), (adj.get('arbiter') or {}).get('judge_dir')]
        for location in locations:
            if not location:
                continue
            folder = Path(location)
            if folder.resolve() in seen or not (folder / 'map.json').is_file():
                continue
            seen.add(folder.resolve())
            mapping = json.loads((folder / 'map.json').read_text(encoding='utf-8'))
            for source in sorted((folder / 'verdicts').rglob('*.jsonl')):
                for line in source.read_text(encoding='utf-8-sig').splitlines():
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    item = mapping.get('items', {}).get(row.get('item_id'), {})
                    if row.get('verdict') == 'khong_dat' and item.get('case_id'):
                        reason = str(row.get('reason') or row.get('ly_do') or '')
                        if reason:
                            errors[(item['case_id'], int(item['turn']))][reason[:120]] += 1
    return errors


def export_hints(scores_path: Path, adjudicated: list[Path], cases_path: Path, out: Path,
                 *, templates=None, per_case_templates=None) -> list[dict]:
    scores = json.loads(scores_path.read_text(encoding='utf-8'))
    judged, _, _, _, _ = _merge_adjudicated_files(adjudicated)
    judge_errors = _judge_errors(adjudicated)
    cases = {c['id']: c for c in (json.loads(x) for x in cases_path.read_text(encoding='utf-8').splitlines() if x.strip())}
    per_case = set(per_case_templates or [])
    groups = defaultdict(list)
    for cid, entry in scores['cases'].items():
        template = entry['template']
        if templates and template not in templates:
            continue
        runs = [c for c in entry.get('candidates', []) if 'stale_input' not in c.get('reject_reasons', [])]
        if any(judged.get((cid, c['model'], int(c['run'])), {}).get('tier') in ('A', 'S') for c in runs):
            continue
        rejected = entry.get('rejected', [])
        if not runs and rejected and all('stale_input' in c.get('reject_reasons', []) for c in rejected):
            continue
        for turn_no, turn in enumerate(cases[cid]['turns'], 1):
            groups[(template, turn_no, cid if template in per_case else '')].append((cid, turn, entry))
    rows = []
    keys = ('tools_called', 'tools_any', 'tools_not_called', 'sources', 'answer_not', 'human_support')
    for (template, turn_no, cid_key), items in sorted(groups.items()):
        expectations, errors = [], Counter()
        for cid, turn, entry in items:
            errors.update(judge_errors.get((cid, turn_no), {}))
            summary = {k: turn['expect'][k] for k in keys if k in turn.get('expect', {})}
            if summary not in expectations:
                expectations.append(summary)
            for c in entry.get('candidates', []) + entry.get('rejected', []):
                if 'stale_input' in c.get('reject_reasons', []):
                    continue
                for failure in c.get('failures_v3', []):
                    match = re.match(r'turn (\d+):', failure)
                    if match is None or int(match[1]) == turn_no:
                        errors[failure[:120]] += 1
                adj = judged.get((cid, c['model'], int(c['run'])), {})
                for verdict in (adj.get('turns') or {}).values():
                    if verdict.get('verdict') == 'khong_dat':
                        reason = str(verdict.get('reason') or verdict.get('ly_do') or '')
                        if reason:
                            errors[reason[:120]] += 1
        row = dict(template=template, turn=turn_no, so_ca=len(items),
                   ky_vong=json.dumps(expectations, ensure_ascii=False),
                   loi_thuong_gap=json.dumps(dict(errors.most_common(8)), ensure_ascii=False), goi_y='')
        if per_case:
            row.update(case_id=cid_key, mode='', order_codes='')
            if cid_key:
                case = cases[cid_key]
                row['mode'] = items[0][1].get('mode', '')
                row['order_codes'] = ' '.join(sorted(code for code in extract_codes(json.dumps(case, ensure_ascii=False))
                                                      if code.startswith('SIM-O-')))
        rows.append(row)
    with out.open('x', encoding='utf-8-sig', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS + (CASE_FIELDS if per_case else []))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def import_hints(csv_path: Path, out: Path, *, check_only=False, eval_utterances=None) -> list[dict]:
    eval_texts = get_eval_user_utterances() if eval_utterances is None else eval_utterances
    with csv_path.open(encoding='utf-8-sig', newline='') as fh:
        rows = list(csv.DictReader(fh))
    results, seen = [], set()
    for line, row in enumerate(rows, 2):
        hint = (row.get('goi_y') or '').strip()
        limit = 1200 if row.get('case_id') else 800
        error = None
        if not hint or len(hint) > limit:
            error = f'Gợi ý phải có 1–{limit} ký tự'
        elif START in hint or END in hint or 'GOI_Y' in hint.upper() or 'HET_GOI_Y' in hint.upper():
            error = 'Gợi ý chứa chuỗi đánh dấu'
        elif MONEY.search(hint):
            error = 'Gợi ý chứa số tiền'
        else:
            allowed = extract_codes(row.get('order_codes', '')) if row.get('case_id') else set()
            allowed = {code for code in allowed if code.startswith('SIM-O-')}
            if extract_codes(hint) - allowed:
                error = 'Gợi ý chứa mã ngoài các mã đơn của chính ca'
            elif any(jaccard_5gram(hint, text) > 0.45 for text in eval_texts):
                error = 'Gợi ý trùng 5-gram > 0,45 với bộ đo'
        if error:
            raise ValueError(f'Dòng {line}: {error}')
        kind = 'case_id' if row.get('case_id') else 'template'
        value = (row.get(kind) or '').strip()
        if not value:
            raise ValueError(f'Dòng {line}: thiếu {kind}')
        turn = int(row['turn']) if row.get('turn', '').strip() else None
        if turn is not None and turn < 1:
            raise ValueError(f'Dòng {line}: lượt phải lớn hơn 0')
        key = (kind, value, turn)
        if key in seen:
            raise ValueError(f'Dòng {line}: trùng khóa {key}')
        seen.add(key)
        results.append({kind: value, 'turn': turn, 'hint': hint,
                        'sha256': hashlib.sha256(hint.encode('utf-8')).hexdigest()})
    if not check_only:
        with out.open('x', encoding='utf-8', newline='\n') as fh:
            for row in results:
                fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    exp = sub.add_parser('export')
    exp.add_argument('--scores', required=True, type=Path)
    exp.add_argument('--adjudicated', required=True, nargs='+', type=Path)
    exp.add_argument('--cases', required=True, type=Path)
    exp.add_argument('--out', required=True, type=Path)
    exp.add_argument('--templates', nargs='+')
    exp.add_argument('--per-case-templates', nargs='+')
    imp = sub.add_parser('import')
    imp.add_argument('--csv', required=True, type=Path)
    imp.add_argument('--out', required=True, type=Path)
    imp.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'export':
            rows = export_hints(args.scores, args.adjudicated, args.cases, args.out,
                                templates=args.templates, per_case_templates=args.per_case_templates)
        else:
            rows = import_hints(args.csv, args.out, check_only=args.check_only)
    except (ValueError, OSError) as exc:
        print(f'Lỗi: {exc}', file=sys.stderr)
        return 2
    print(f'{args.command}: {len(rows)} phiếu đỡ')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
