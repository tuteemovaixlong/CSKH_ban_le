#!/usr/bin/env python3
"""W6.7.0 Part B2: Build SFT train/val JSONL dataset from selected traces.

CLI:
  python scripts/sft_build.py --selection selection.json --cases <cases.jsonl> \
      --out-dir <dir> [--val-ratio 0.1] [--seed 20261203]
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import eval_regrade, sft_dataset, sft_select  # noqa: E402
from scripts.run_agent_scenarios import percentile  # noqa: E402

DEFAULT_SEED = 20261203
DEFAULT_VAL_RATIO = 0.1
CHARS_PER_TOKEN = 3.2
CJK_RE = sft_select.CJK_RE
CJK_SPAN_RE = sft_select.CJK_SPAN_RE

SECRET_PATTERNS = (
    ('openai_or_sk_key', re.compile(r'sk-[A-Za-z0-9_-]{8,}')),
    ('bearer_token', re.compile(r'Bearer\s+[A-Za-z0-9_.\-]{8,}', re.IGNORECASE)),
    ('google_api_key', re.compile(r'AIza[0-9A-Za-z_-]{10,}')),
    ('github_token', re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,})')),
    ('hf_token', re.compile(r'hf_[A-Za-z0-9]{10,}')),
    ('slack_token', re.compile(r'xox[baprs]-[0-9A-Za-z-]{10,}')),
    ('aws_access_key', re.compile(r'AKIA[0-9A-Z]{16}')),
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows)
    path.write_text(content, encoding='utf-8', newline='\n')


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def load_eval_utterance_sets(suites_dir: Path | None = None) -> tuple[set[str], set[str]]:
    """Collect normalized user utterances from all 250 eval suite cases under both normalize_text and v2."""
    directory = suites_dir or (ROOT / 'evals' / 'suites')
    norm_v1: set[str] = set()
    norm_v2: set[str] = set()
    if not directory.is_dir():
        return norm_v1, norm_v2

    def _add(raw: Any) -> None:
        if not isinstance(raw, str) or not raw.strip():
            return
        n1 = sft_dataset.normalize_text(raw)
        if n1:
            norm_v1.add(n1)
        n2 = eval_regrade.v2(raw)
        if n2:
            norm_v2.add(n2)

    for suite_file in sorted(directory.glob('S*.jsonl')):
        for case in _read_jsonl(suite_file):
            for turn in case.get('turns') or []:
                _add(turn.get('user'))
            if case.get('actor') == 'staff_case_assist':
                for cmsg in (case.get('case_setup') or {}).get('customer_messages') or []:
                    _add(cmsg.get('text'))
    return norm_v1, norm_v2


def _load_trace_calls(run_dir: Path, run_offset: int = 0) -> dict[tuple[Any, Any, Any], list[dict[str, Any]]]:
    return sft_select.load_mapped_trace_calls(run_dir, run_offset)


def _load_merged_turns(run_dir: Path) -> dict[tuple[str, int], list[dict[str, Any]]]:
    merged_path = run_dir / 'merged.json'
    if not merged_path.is_file():
        return {}
    merged = json.loads(merged_path.read_text(encoding='utf-8'))
    out: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for rec in merged.get('scenarios') or []:
        cid = rec.get('id')
        run_no = rec.get('run')
        if isinstance(cid, str) and isinstance(run_no, int):
            out[(cid, run_no)] = list(rec.get('turns') or [])
    return out


def _is_merged_rail_turn(
    merged_turns: dict[tuple[str, int], list[dict[str, Any]]],
    case_id: str,
    run_no: int,
    turn_no: int,
) -> bool:
    turns = merged_turns.get((case_id, run_no))
    if not turns or turn_no > len(turns):
        return False
    turn = turns[turn_no - 1]
    if turn.get('error'):
        return False
    if int(turn.get('model_calls') or 0) != 0:
        return False
    return bool(str(turn.get('answer') or turn.get('draft_reply') or '').strip())


def _sample_calls_tool(sample: dict[str, Any], tool_name: str) -> bool:
    for msg in sample.get('messages') or []:
        if msg.get('role') != 'assistant':
            continue
        for tc in msg.get('tool_calls') or []:
            fn = tc.get('function') if isinstance(tc, dict) else None
            if isinstance(fn, dict) and fn.get('name') == tool_name:
                return True
    return False


def _count_model_calls_in_turn(sample: dict[str, Any]) -> int:
    msgs = sample.get('messages') or []
    last_user_idx = -1
    for idx, msg in enumerate(msgs):
        if msg.get('role') == 'user':
            last_user_idx = idx
    return sum(1 for msg in msgs[last_user_idx + 1:] if msg.get('role') == 'assistant')


def _append_user_text(texts: list[str], raw: str) -> None:
    if not raw.strip():
        return
    texts.append(raw)
    marker = '\n\n[Tệp đính kèm:'
    if marker in raw:
        prefix = raw.split(marker, 1)[0].strip()
        if prefix:
            texts.append(prefix)


def _extract_user_texts(messages: list[dict[str, Any]], case: dict[str, Any], turn_no: int) -> list[str]:
    texts: list[str] = []
    for msg in messages:
        if msg.get('role') != 'user':
            continue
        content = msg.get('content')
        if isinstance(content, str):
            _append_user_text(texts, content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get('type') == 'text' and isinstance(part.get('text'), str):
                    _append_user_text(texts, part['text'])
    turns = case.get('turns') or []
    for idx in range(min(turn_no, len(turns))):
        u = turns[idx].get('user')
        if isinstance(u, str) and u.strip():
            texts.append(u)
    if case.get('actor') == 'staff_case_assist':
        for cmsg in (case.get('case_setup') or {}).get('customer_messages') or []:
            t = cmsg.get('text')
            if isinstance(t, str) and t.strip():
                texts.append(t)
    return texts


def _find_secret_hit(sample: dict[str, Any]) -> str | None:
    serialized = json.dumps(sample, ensure_ascii=False)
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(serialized):
            return label
    return None


def _normalize_request_messages(raw_messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Deep-copy request messages verbatim, only converting assistant reasoning->reasoning_content and arguments->dict."""
    messages = copy.deepcopy(raw_messages)
    for msg in messages:
        if msg.get('role') != 'assistant':
            continue
        if 'reasoning' in msg:
            if msg.get('reasoning_content') is None and msg['reasoning'] is not None:
                msg['reasoning_content'] = msg['reasoning']
            msg.pop('reasoning', None)
        msg.pop('reasoning_details', None)

        tool_calls = msg.get('tool_calls')
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get('function') if isinstance(tc, dict) else None
                if not isinstance(fn, dict):
                    return None, 'invalid_tool_arguments'
                raw_args = fn.get('arguments')
                if isinstance(raw_args, dict):
                    continue
                if isinstance(raw_args, str):
                    try:
                        parsed = json.loads(raw_args)
                    except (ValueError, TypeError):
                        return None, 'invalid_tool_arguments'
                    if not isinstance(parsed, dict):
                        return None, 'invalid_tool_arguments'
                    fn['arguments'] = parsed
                else:
                    return None, 'invalid_tool_arguments'
    return messages, None


def _length_stats(values: list[float | int]) -> dict[str, Any]:
    if not values:
        return {'p50': None, 'p95': None, 'max': None, 'min': None, 'mean': None}
    return {
        'p50': percentile(values, 50),
        'p95': percentile(values, 95),
        'max': round(max(values), 2),
        'min': round(min(values), 2),
        'mean': round(sum(values) / len(values), 2),
    }


def _sample_char_length(sample: dict[str, Any]) -> int:
    payload = {'messages': sample['messages'], 'tools': sample['tools']}
    return len(json.dumps(payload, ensure_ascii=False))


def _load_owner_edits(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f'Không tìm thấy tệp lớp phủ --owner-edits: {path}')
    rows = _read_jsonl(path)
    edits: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f'--owner-edits dòng {idx}: phải là JSON object')
        cid = row.get('case_id')
        model = row.get('model')
        run_raw = row.get('run')
        old = row.get('old')
        new = row.get('new')
        if not isinstance(cid, str) or not cid:
            raise ValueError(f'--owner-edits dòng {idx}: thiếu case_id')
        if not isinstance(model, str) or not model:
            raise ValueError(f'--owner-edits dòng {idx}: thiếu model')
        if isinstance(run_raw, bool) or run_raw is None:
            raise ValueError(f'--owner-edits dòng {idx}: thiếu run')
        try:
            run_no = int(run_raw)
        except (ValueError, TypeError) as exc:
            raise ValueError(f'--owner-edits dòng {idx}: run không hợp lệ {run_raw!r}') from exc
        if not isinstance(old, str) or not old:
            raise ValueError(f'--owner-edits dòng {idx}: trường old phải là chuỗi không rỗng')
        if not isinstance(new, str):
            raise ValueError(f'--owner-edits dòng {idx}: trường new phải là chuỗi')
        edits.append({
            'line': idx,
            'case_id': cid,
            'model': model,
            'run': run_no,
            'old': old,
            'new': new,
            'owner_edit': str(row.get('owner_edit') or 'cjk'),
        })
    return edits


def _apply_owner_edits(
    norm_msgs: list[dict[str, Any]],
    edit_indices: list[int],
    all_edits: list[dict[str, Any]],
    applied_counts: list[int],
) -> str | None:
    """Áp lớp phủ old -> new lên mọi content/reasoning_content của trợ lý (tin trước và tin cuối)."""
    applied_tag: str | None = None
    for idx in edit_indices:
        edit = all_edits[idx]
        old = edit['old']
        new = edit['new']
        for msg in norm_msgs:
            if msg.get('role') != 'assistant':
                continue
            for field in ('content', 'reasoning_content'):
                val = msg.get(field)
                if isinstance(val, str) and old in val:
                    msg[field] = val.replace(old, new)
                    applied_counts[idx] += 1
                    applied_tag = edit['owner_edit']
    return applied_tag


def _find_assistant_cjk(norm_msgs: list[dict[str, Any]]) -> list[str]:
    spans: list[str] = []
    for msg in norm_msgs:
        if msg.get('role') != 'assistant':
            continue
        for field in ('content', 'reasoning_content'):
            val = msg.get(field)
            if isinstance(val, str) and val:
                spans.extend(m.group(0) for m in CJK_SPAN_RE.finditer(val))
    return spans


def build_sft_dataset(
    selection_path: Path,
    cases_path: Path,
    out_dir: Path,
    *,
    val_ratio: float = DEFAULT_VAL_RATIO,
    seed: int = DEFAULT_SEED,
    eval_suites_dir: Path | None = None,
    owner_edits_path: Path | None = None,
) -> dict[str, Any]:
    if not 0.0 <= val_ratio < 1.0:
        raise ValueError(f'--val-ratio must be in [0, 1), got {val_ratio}')

    selection = json.loads(selection_path.read_text(encoding='utf-8'))
    cases_by_id = {c['id']: c for c in _read_jsonl(cases_path)}
    eval_v1, eval_v2 = load_eval_utterance_sets(eval_suites_dir)

    all_edits: list[dict[str, Any]] = _load_owner_edits(owner_edits_path) if owner_edits_path is not None else []
    selected_run_keys = {(entry['case_id'], entry.get('model') or entry['source_model'], int(entry['run']))
                         for entry in selection.get('selected') or []}
    unused_owner_edits = [edit for edit in all_edits
                          if (edit['case_id'], edit['model'], edit['run']) not in selected_run_keys]
    edits_by_run: dict[tuple[str, str, int], list[int]] = defaultdict(list)
    for idx, edit in enumerate(all_edits):
        edits_by_run[(edit['case_id'], edit['model'], edit['run'])].append(idx)
    applied_counts = [0] * len(all_edits)

    trace_cache: dict[tuple[Path, int], dict[tuple[Any, Any, Any], list[dict[str, Any]]]] = {}
    merged_cache: dict[Path, dict[tuple[str, int], list[dict[str, Any]]]] = {}
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_case_entries: Counter[str] = Counter()

    for entry in selection.get('selected') or []:
        cid = entry['case_id']
        run_no = int(entry['run'])
        source_run = int(entry.get('source_run', run_no))
        model = entry.get('model') or entry['source_model']
        seen_case_entries[cid] += 1
        role = entry.get('role') or ('primary' if seen_case_entries[cid] == 1 else 'second')
        entry_slot = 1 if role == 'primary' and seen_case_entries[cid] == 1 else max(2, seen_case_entries[cid])

        if str(cid).strip().lower().startswith('s'):
            rejected.append({
                'case_id': cid, 'model': model, 'run': run_no, 'turn': None, 'role': role,
                'reason': 'eval_case_id_prefix_s',
            })
            continue

        if cid not in cases_by_id:
            raise ValueError(f'Selected case {cid!r} not found in {cases_path}')
        case = cases_by_id[cid]

        rdir_str = entry.get('run_dir') or (selection.get('run_dirs') or {}).get(model)
        if not rdir_str:
            raise ValueError(f'Missing run_dir for model {model!r} in selection')
        rdir = Path(rdir_str).resolve()
        trace_key = (rdir, run_no - source_run)
        if trace_key not in trace_cache:
            trace_cache[trace_key] = _load_trace_calls(rdir, trace_key[1])
        calls = trace_cache[trace_key]

        n_turns = len(case.get('turns') or [])
        case_meta = case.get('meta') or {}
        rail_turns = set(entry.get('rail_turns') or [])
        matching_edit_indices = edits_by_run.get((cid, model, run_no), [])

        for turn_no in range(1, n_turns + 1):
            sample_id = f'{cid}#t{turn_no}' if entry_slot == 1 else f'{cid}#t{turn_no}#{entry_slot}'
            turn_calls = calls.get((cid, run_no, turn_no), [])
            if turn_no in rail_turns:
                rejected.append({
                    'case_id': cid, 'model': model, 'run': run_no, 'turn': turn_no,
                    'role': role, 'sample_id': sample_id,
                    'reason': 'rail_turn_no_model_call',
                })
                continue
            if not turn_calls:
                if rdir not in merged_cache:
                    merged_cache[rdir] = _load_merged_turns(rdir)
                if _is_merged_rail_turn(merged_cache[rdir], cid, source_run, turn_no):
                    rejected.append({
                        'case_id': cid, 'model': model, 'run': run_no, 'turn': turn_no,
                        'role': role, 'sample_id': sample_id,
                        'reason': 'rail_turn_no_model_call',
                    })
                    continue

            stop_calls = [c for c in turn_calls if (c.get('response') or {}).get('finish_reason') == 'stop']
            if not stop_calls:
                rejected.append({
                    'case_id': cid, 'model': model, 'run': run_no, 'turn': turn_no,
                    'role': role, 'sample_id': sample_id,
                    'reason': 'missing_stop_call',
                })
                continue

            last_stop = stop_calls[-1]
            req = last_stop.get('request') or {}
            resp = last_stop.get('response') or {}

            norm_msgs, err_reason = _normalize_request_messages(req.get('messages') or [])
            if err_reason or norm_msgs is None:
                rejected.append({
                    'case_id': cid, 'model': model, 'run': run_no, 'turn': turn_no,
                    'role': role, 'sample_id': sample_id,
                    'reason': err_reason or 'invalid_messages',
                })
                continue

            final_content = resp.get('content')
            final_reasoning = resp.get('reasoning_content')
            if final_reasoning is None:
                final_reasoning = resp.get('reasoning')
            norm_msgs.append({
                'role': 'assistant',
                'content': '' if final_content is None else str(final_content),
                'reasoning_content': '' if final_reasoning is None else str(final_reasoning),
            })
            from scripts.sft_hint_proxy import START, END
            if any(marker in json.dumps(norm_msgs, ensure_ascii=False) for marker in (START, END)):
                raise ValueError(f'{sample_id}: mẫu còn chuỗi đánh dấu gợi ý')

            # W6.7.2 mục E: áp lớp phủ owner edits trên bản sao trong bộ nhớ (không sửa vết gốc).
            owner_edit_tag = (
                _apply_owner_edits(norm_msgs, matching_edit_indices, all_edits, applied_counts)
                if matching_edit_indices
                else None
            )
            if any(marker in json.dumps(norm_msgs, ensure_ascii=False) for marker in (START, END)):
                raise ValueError(f'{sample_id}: mẫu còn chuỗi đánh dấu gợi ý sau lớp phủ')

            # W6.7.2 mục E: chặn mẫu còn chữ Hán/Nhật/Hàn trong văn bản trợ lý sau lớp phủ.
            cjk_spans = _find_assistant_cjk(norm_msgs)
            if cjk_spans:
                rejected.append({
                    'case_id': cid, 'model': model, 'run': run_no, 'turn': turn_no,
                    'role': role, 'sample_id': sample_id,
                    'reason': 'cjk_text',
                    'cjk_spans': cjk_spans[:10],
                })
                continue

            # P2: Reject DeepSeek samples that mention "deepseek" in any message
            if model == 'deepseek' and 'deepseek' in json.dumps(norm_msgs, ensure_ascii=False).lower():
                rejected.append({
                    'case_id': cid, 'model': model, 'run': run_no, 'turn': turn_no,
                    'role': role, 'sample_id': sample_id,
                    'reason': 'model_identity_leak',
                })
                continue

            tools = copy.deepcopy(req.get('tools') or [])
            sample_meta = {
                'sample_id': sample_id,
                'case_id': cid,
                'template': case_meta.get('template') or entry.get('template', ''),
                'suite': case_meta.get('suite') or entry.get('suite') or case.get('category', '').upper(),
                'turn': turn_no,
                'source': model,
                'source_model': model,
                'run': run_no,
                'tier': entry['tier'],
                'role': role,
                'owner_edit': owner_edit_tag,
                'style': case_meta.get('style') or entry.get('style', ''),
                'repo_sha': entry.get('repo_sha') or (selection.get('repo_sha') or {}).get(model),
            }
            sample = {'messages': norm_msgs, 'tools': tools, 'meta': sample_meta}
            if 'hinted' in entry:
                sample_meta['hinted'] = bool(entry['hinted'])

            # Check overlap with 250 eval customer utterances
            user_texts = _extract_user_texts(norm_msgs, case, turn_no)
            if any(
                (sft_dataset.normalize_text(t) in eval_v1) or (eval_regrade.v2(t) in eval_v2)
                for t in user_texts
            ):
                rejected.append({
                    'case_id': cid, 'model': model, 'run': run_no, 'turn': turn_no,
                    'role': role, 'sample_id': sample_id,
                    'reason': 'eval_utterance_overlap',
                })
                continue

            # Check secrets/keys in entire serialized sample
            secret_kind = _find_secret_hit(sample)
            if secret_kind:
                rejected.append({
                    'case_id': cid, 'model': model, 'run': run_no, 'turn': turn_no,
                    'role': role, 'sample_id': sample_id,
                    'reason': f'secret_detected:{secret_kind}',
                })
                continue

            kept.append(sample)

    # Mỗi dòng trong --owner-edits phải áp được ít nhất một lần; nếu không thì dừng có lỗi trước khi ghi tệp.
    unapplied = [
        all_edits[idx] for idx, cnt in enumerate(applied_counts) if cnt == 0
        and (all_edits[idx]['case_id'], all_edits[idx]['model'], all_edits[idx]['run']) in selected_run_keys
    ]
    if unapplied:
        preview = ', '.join(
            f"dòng {e['line']} ({e['case_id']}|{e['model']}|{e['run']})"
            for e in unapplied[:5]
        )
        raise ValueError(
            f'--owner-edits có {len(unapplied)} dòng không áp được lần nào: {preview}'
        )

    templates = sorted({s['meta']['template'] for s in kept})
    n_templates = len(templates)
    if n_templates >= 2 and val_ratio > 0:
        n_val = min(n_templates - 1, max(1, round(n_templates * val_ratio)))
        val_templates = set(random.Random(seed).sample(templates, n_val))
    else:
        val_templates = set()

    train_samples = [s for s in kept if s['meta']['template'] not in val_templates]
    val_samples = [s for s in kept if s['meta']['template'] in val_templates]

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / 'train.jsonl', train_samples)
    _write_jsonl(out_dir / 'val.jsonl', val_samples)

    char_lengths = [_sample_char_length(s) for s in kept]
    est_tokens = [round(c / CHARS_PER_TOKEN, 2) for c in char_lengths]

    by_suite: dict[str, dict[str, int]] = {}
    for s in kept:
        st = s['meta']['suite']
        bucket = by_suite.setdefault(st, {'total': 0, 'train': 0, 'val': 0})
        bucket['total'] += 1
        if s['meta']['template'] in val_templates:
            bucket['val'] += 1
        else:
            bucket['train'] += 1

    src_counts = Counter(s['meta']['source_model'] for s in kept)
    total_kept = len(kept)
    by_source = {
        m: {
            'count': src_counts.get(m, 0),
            'ratio': round(src_counts.get(m, 0) / total_kept, 4) if total_kept else 0.0,
        }
        for m in sorted(set(src_counts) | {'qwen', 'deepseek'})
    }
    by_tier = Counter(s['meta']['tier'] for s in kept)
    by_role = Counter(s['meta']['role'] for s in kept)
    by_sstr = Counter(
        f"{s['meta']['suite']}|{s['meta']['source']}|{s['meta']['tier']}|{s['meta']['role']}"
        for s in kept
    )
    owner_edit_counts = Counter(
        s['meta']['owner_edit'] for s in kept if s['meta'].get('owner_edit') is not None
    )
    cjk_rejected = [r for r in rejected if r.get('reason') == 'cjk_text']

    turn_idx_counts = Counter(str(s['meta']['turn']) for s in kept)
    turns_per_case: Counter[str] = Counter()
    for cid in {s['meta']['case_id'] for s in kept}:
        turns_per_case[str(len(cases_by_id[cid].get('turns') or []))] += 1

    sources_list = sorted(set(src_counts) | {'qwen', 'deepseek'})
    runtime_info_by_src = Counter(
        s['meta']['source_model'] for s in kept if _sample_calls_tool(s, 'get_runtime_info')
    )
    no_tools_by_src = Counter(
        s['meta']['source_model'] for s in kept if len(s.get('tools') or []) == 0
    )
    model_calls_dist = Counter(str(_count_model_calls_in_turn(s)) for s in kept)
    empty_reasoning_by_src = Counter(
        s['meta']['source_model']
        for s in kept
        if not str((s['messages'][-1] if s.get('messages') else {}).get('reasoning_content') or '').strip()
    )

    reject_counts = Counter(r['reason'] for r in rejected)

    stats = {
        'seed': seed,
        'val_ratio': val_ratio,
        'owner_edits_path': str(owner_edits_path.resolve()) if owner_edits_path is not None else None,
        'samples': {
            'total': total_kept,
            'train': len(train_samples),
            'val': len(val_samples),
        },
        'cases': {
            'total': len({s['meta']['case_id'] for s in kept}),
            'train': len({s['meta']['case_id'] for s in train_samples}),
            'val': len({s['meta']['case_id'] for s in val_samples}),
        },
        'templates': {
            'total': n_templates,
            'train': len({s['meta']['template'] for s in train_samples}),
            'val': len({s['meta']['template'] for s in val_samples}),
            'val_templates': sorted(val_templates),
        },
        'by_suite': dict(sorted(by_suite.items())),
        'by_source': by_source,
        'by_tier': dict(sorted(by_tier.items())),
        'by_role': {r: by_role.get(r, 0) for r in ('primary', 'second')},
        'by_suite_source_tier_role': dict(sorted(by_sstr.items())),
        'owner_edit_samples': sum(owner_edit_counts.values()),
        'by_owner_edit': dict(sorted(owner_edit_counts.items())),
        'cjk_rejected_count': len(cjk_rejected),
        'cjk_rejected': cjk_rejected,
        'by_turn_index': dict(sorted(turn_idx_counts.items(), key=lambda kv: int(kv[0]))),
        'by_case_turns': dict(sorted(turns_per_case.items(), key=lambda kv: int(kv[0]))),
        'runtime_info_calls': {
            'total': sum(runtime_info_by_src.values()),
            'by_source': {m: runtime_info_by_src.get(m, 0) for m in sources_list},
        },
        'final_call_without_tools': {
            'total': sum(no_tools_by_src.values()),
            'by_source': {m: no_tools_by_src.get(m, 0) for m in sources_list},
        },
        'model_calls_in_turn': dict(sorted(model_calls_dist.items(), key=lambda kv: int(kv[0]))),
        'empty_final_reasoning': sum(empty_reasoning_by_src.values()),
        'empty_final_reasoning_by_source': {m: empty_reasoning_by_src.get(m, 0) for m in sources_list},
        'char_length': _length_stats(char_lengths),
        'estimated_tokens': _length_stats(est_tokens),
        'chars_per_token_estimate': CHARS_PER_TOKEN,
        'rejected': {
            'total': len(rejected),
            'by_reason': dict(sorted(reject_counts.items())),
            'items': rejected,
        },
    }
    if any('hinted' in entry for entry in selection.get('selected') or []):
        stats['by_hinted'] = {str(value).lower(): sum(s['meta'].get('hinted', False) == value for s in kept)
                              for value in (False, True)}
    if owner_edits_path is not None:
        stats['unused_owner_edits'] = unused_owner_edits
    _write_json(out_dir / 'stats.json', stats)
    (out_dir / 'build_report.md').write_text(_render_build_report(stats), encoding='utf-8')
    return stats


def _render_build_report(stats: dict[str, Any]) -> str:
    sm = stats['samples']
    cs = stats['cases']
    tm = stats['templates']
    cl = stats['char_length']
    tk = stats['estimated_tokens']
    rj = stats['rejected']

    lines = [
        '# Báo cáo dựng tập SFT (`sft_build`)',
        '',
        '## Tổng quan',
        '',
        f'- Tổng số mẫu: **{sm["total"]}** (`train`: **{sm["train"]}**, `val`: **{sm["val"]}**)',
        f'- Tổng số ca: **{cs["total"]}** (`train`: **{cs["train"]}**, `val`: **{cs["val"]}**)',
        f'- Tổng số khung: **{tm["total"]}** (`train`: **{tm["train"]}**, `val`: **{tm["val"]}**; `val_ratio` = {stats["val_ratio"]}, `seed` = {stats["seed"]})',
        f'- Khung trong `val`: {", ".join(f"`{t}`" for t in tm["val_templates"]) or "(không có)"}',
        f'- Theo Tier: {stats.get("by_tier") or {}} | Theo vai (`role`): {stats.get("by_role") or {}}',
        f'- Số mẫu có lớp phủ `owner_edit`: **{stats.get("owner_edit_samples", 0)}** ({stats.get("by_owner_edit") or {}})',
        f'- Số mẫu loại vì còn chữ Hán/Nhật/Hàn (`cjk_text`): **{stats.get("cjk_rejected_count", 0)}**',
        '',
        '## Nguồn mẫu (`source_model`)',
        '',
        '| Nguồn | Số mẫu | Tỉ lệ |',
        '|---|---|---|',
    ]
    for src, info in stats['by_source'].items():
        lines.append(f'| `{src}` | {info["count"]} | {100 * info["ratio"]:.1f}% |')
    if 'by_hinted' in stats:
        lines += ['', f'- Theo gợi ý (`hinted`): {stats["by_hinted"]}']
    if 'unused_owner_edits' in stats:
        lines += ['', f'- Lớp phủ ngoài selection (`unused_owner_edits`): {stats["unused_owner_edits"]}']

    lines += [
        '',
        '## Phân bổ theo bộ × nguồn × tier × vai',
        '',
        '| Bộ | Nguồn | Tier | Vai | Số mẫu |',
        '|---|---|---|---|---|',
    ]
    sstr = stats.get('by_suite_source_tier_role') or {}
    for key, cnt in sorted(sstr.items()):
        suite, src, tier, role = key.split('|')
        lines.append(f'| {suite} | `{src}` | {tier} | `{role}` | {cnt} |')
    if not sstr:
        lines.append('| (trống) | - | - | - | 0 |')

    lines += [
        '',
        '## Phân bổ theo bộ (`suite`)',
        '',
        '| Bộ | Tổng | Train | Val |',
        '|---|---|---|---|',
    ]
    for suite, b in stats['by_suite'].items():
        lines.append(f'| {suite} | {b["total"]} | {b["train"]} | {b["val"]} |')
    if not stats['by_suite']:
        lines.append('| (trống) | 0 | 0 | 0 |')

    lines += [
        '',
        '## Chỉ số cấu trúc lượt & F52',
        '',
        f'- Số mẫu gọi `get_runtime_info`: **{stats["runtime_info_calls"]["total"]}** '
        f'(theo nguồn: {stats["runtime_info_calls"]["by_source"]})',
        f'- Số mẫu lần gọi `stop` cuối không có `tools` (`final_call_without_tools`): '
        f'**{stats["final_call_without_tools"]["total"]}** '
        f'(theo nguồn: {stats["final_call_without_tools"]["by_source"]})',
        f'- Phân bố số lần gọi model trong lượt (`model_calls_in_turn`): {stats["model_calls_in_turn"]}',
        f'- Số mẫu `reasoning_content` cuối rỗng (`empty_final_reasoning`): **{stats["empty_final_reasoning"]}** '
        f'(theo nguồn: {stats["empty_final_reasoning_by_source"]})',
        '',
        '## Độ dài mẫu và ước lượng token (`chars / 3.2`)',
        '',
        '| Chỉ số | Ký tự | Ước lượng token |',
        '|---|---|---|',
        f'| p50 | {cl["p50"]} | {tk["p50"]} |',
        f'| p95 | {cl["p95"]} | {tk["p95"]} |',
        f'| max | {cl["max"]} | {tk["max"]} |',
        '',
        f'## Mẫu bị loại ({rj["total"]})',
        '',
        '| Lý do | Số mẫu |',
        '|---|---|',
    ]
    for reason, cnt in rj['by_reason'].items():
        lines.append(f'| `{reason}` | {cnt} |')
    if not rj['by_reason']:
        lines.append('| (không có) | 0 |')

    cjk_items = stats.get('cjk_rejected') or []
    if cjk_items:
        lines += ['', f'### Danh sách mẫu loại vì `cjk_text` ({len(cjk_items)})', '']
        for item in cjk_items:
            spans = ', '.join(f'`{sp}`' for sp in (item.get('cjk_spans') or []))
            lines.append(
                f"- `{item.get('sample_id') or item['case_id']}` "
                f"(`{item['case_id']}|{item['model']}|{item['run']}`, lượt {item['turn']}): {spans}"
            )

    lines.append('')
    return '\n'.join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='sft_build.py', description=__doc__.split('\n\n')[0])
    parser.add_argument('--selection', required=True, type=Path, help='Tệp selection.json từ sft_select.py select')
    parser.add_argument('--cases', required=True, type=Path, help='Tệp ca huấn luyện JSONL')
    parser.add_argument('--out-dir', required=True, type=Path, help='Thư mục xuất train.jsonl, val.jsonl, stats.json, build_report.md')
    parser.add_argument('--owner-edits', type=Path, default=None,
                        help='Tệp lớp phủ owner_edits_cjk.jsonl (áp lên văn bản trợ lý, không sửa vết gốc)')
    parser.add_argument('--val-ratio', type=float, default=DEFAULT_VAL_RATIO, help='Tỉ lệ khung dành cho val (mặc định 0.1)')
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED, help='Seed tách train/val theo khung')
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        stats = build_sft_dataset(
            args.selection,
            args.cases,
            args.out_dir,
            val_ratio=args.val_ratio,
            seed=args.seed,
            owner_edits_path=args.owner_edits,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f'Lỗi: {exc}', file=sys.stderr)
        return 2
    sm = stats['samples']
    print(
        f"sft_build: {sm['total']} mẫu (train={sm['train']}, val={sm['val']}), "
        f"owner_edit={stats['owner_edit_samples']}, loại={stats['rejected']['total']} -> {args.out_dir}"
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
