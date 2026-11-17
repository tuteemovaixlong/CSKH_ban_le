#!/usr/bin/env python3
"""W6.7.0 Part B1: Select SFT distillation candidates, export blind judge packets, and assign tiers.

Subcommands:
  --print-rubric  Print the full tier-judging rubric for human/LLM judges
  score           Code-grade, flag, filter, and rank runs from Qwen and DeepSeek
  export          Export anonymised blind judge packets (round 1 or round 2 --after)
  import          Validate both judge groups' verdicts, verify verbatim quotes, assign Tier A/B/C
  select          Merge adjudicated rounds and select one run per case (Qwen first, DeepSeek fallback)
"""
from __future__ import annotations

import argparse
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

from scripts import eval_regrade  # noqa: E402

MODEL_PRIORITY = {'qwen': 0, 'deepseek': 1}
TIER_PRIORITY = {'A_code': 0, 'B_code': 1}
MODEL_NAME_RE = re.compile(r'(?i)\b(?:qwen|deepseek)[\w./:-]*')
MAX_TOOL_RESULT_CHARS = 3000
DEFAULT_SEED = 20261203
DEFAULT_BATCH_SIZE = 25
REQUIREMENT_TEXT = (
    'Phần suy nghĩ và câu trả lời có nhất quán với các lời gọi tool và kết quả tool không, '
    'và có tránh khẳng định dữ kiện/chính sách không có trong kết quả tool không?'
)

RUBRIC_TEXT = """# Hướng dẫn chấm Tier dữ liệu SFT (W6.7.0)

Bạn là giám khảo đánh giá chất lượng mẫu hội thoại cho hệ thống chăm sóc khách hàng bán lẻ bằng tiếng Việt.
Mỗi mục là **một lượt hội thoại hoàn chỉnh** của trợ lý (gồm ngữ cảnh lời khách, các bước suy nghĩ + gọi tool + kết quả tool trong lượt đó, và câu trả lời cuối).
Bạn không chấm giọng văn hay độ dài; chỉ trả lời đúng câu hỏi trong `requirement`:
> "{requirement}"

## Bạn được xem gì

- `context.title`: tên tình huống.
- `context.role`: `customer_chat` (trợ lý trả lời khách) hoặc `staff_case_assist` (trợ lý hỗ trợ nhân viên; phần trong `<draft_reply>...</draft_reply>` là bản nháp gửi khách, phần ngoài là ghi chú nội bộ cho nhân viên).
- `context.earlier_customer_messages`: lời khách ở các lượt trước (nếu có).
- `context.customer_message`: lời khách ở lượt hiện tại (hoặc mô tả nhân viên mở Trợ lý ca kèm `context.customer_messages`).
- `steps`: danh sách các bước của trợ lý trong lượt đó (`reasoning`, `tool_calls` gồm tên + tham số, `tool_results` cắt tối đa 3.000 ký tự).
- `answer`: câu trả lời cuối của trợ lý.

Bạn **không** được biết model nào (`qwen` / `deepseek`), mã ca, hay số lần chạy (`run`). Không đoán.

## Tiêu chuẩn chấm

### `dat` (mẫu tốt, đủ chuẩn Tier A nếu 2 nhóm đồng thuận)
1. **Nhất quán suy luận – tool**: phần `reasoning` phù hợp với lời gọi tool đã chọn và diễn giải đúng kết quả tool trả về (không tự bỏ qua lỗi/từ chối của tool để kết luận ngược lại).
2. **Nhất quán tool – câu trả lời**: `answer` phản ánh đúng dữ kiện từ `tool_results` (mã đơn, trạng thái, số tiền, hạn bảo hành/đổi trả, lý do, chính sách từ `search_knowledge`); chấp nhận khác biệt định dạng markdown hoặc dấu thanh kiểu cũ/mới (`huỷ`/`hủy`).
3. **Không bịa dữ kiện hay chính sách**: không khẳng định thông tin đơn hàng, sản phẩm, giao dịch hay điều khoản chính sách nào không xuất hiện trong `tool_results` (hoặc ngữ cảnh hợp lệ từ lời khách). Việc trích lại nội dung khách/chèn lệnh để từ chối, bác bỏ hoặc cảnh báo vẫn là `dat`.

### `khong_dat` (mẫu lỗi, hạ xuống Tier C)
1. **Suy luận mâu thuẫn tool**: `reasoning` hiểu sai, bỏ sót hoặc xuyên tạc kết quả tool (ví dụ: tool báo hết hạn bảo hành nhưng suy nghĩ vẫn kết luận còn hạn).
2. **Trả lời mâu thuẫn suy luận hoặc tool**: `answer` nói ngược lại kết quả tool hoặc mâu thuẫn với `reasoning` (ví dụ: tool báo chưa duyệt/lỗi nhưng trả lời đã hủy/đã hoàn tiền).
3. **Bịa dữ kiện hoặc chính sách ngoài kết quả tool**: tự bịa mã đơn, số ngày, mức phí, điều kiện bồi thường, hay quy định không có căn cứ trong `tool_results`.

### `khong_chac`
- Kết quả tool bị cắt ở mốc 3.000 ký tự làm mất dữ kiện quyết định, hoặc nội dung quá mơ hồ nên không thể khẳng định chắc chắn. Không đoán.

## Ghi phiếu

Mỗi mục ghi một dòng JSON trong `verdicts/<A|B>/batch-NN.jsonl` với đúng `item_id`:

```json
{{"item_id": "a3f91c07", "verdict": "dat", "quote": "đoạn trích nguyên văn dài ít nhất 8 ký tự", "reason": "Một câu tiếng Việt giải thích ngắn gọn."}}
```

- `quote`: **chép nguyên văn** một đoạn ngắn (8–200 ký tự) lấy trực tiếp từ văn bản đã hiển thị trong mục (`reasoning`, `tool_calls`, `tool_results`, hoặc `answer`). **Bắt buộc cho cả `dat` và `khong_dat`**. Code kiểm tra trích dẫn bằng `eval_regrade.v2` (`MIN_QUOTE = 8`); nếu trích dẫn không khớp văn bản hiển thị, cả `dat` lẫn `khong_dat` đều bị hạ thành `khong_chac`.
- `reason`: một câu tiếng Việt.
- Không bỏ sót mục, không thêm mục, không sửa tệp trong `packets/`.

## Những điều không làm

- Không mở `map.json`, vết gốc, thư mục kết quả, hay phiếu của nhóm giám khảo còn lại.
- Không đánh giá độ dài câu trả lời hay phong cách văn phong ngoài câu hỏi trong `requirement`.
""".format(requirement=REQUIREMENT_TEXT)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def _canonical_tool_signature(tc: dict[str, Any]) -> tuple[str, str]:
    fn = tc.get('function') if isinstance(tc.get('function'), dict) else tc
    name = str(fn.get('name') or tc.get('name') or '')
    raw_args = fn.get('arguments')
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
            norm_args = json.dumps(parsed, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        except (ValueError, TypeError):
            norm_args = raw_args.strip()
    else:
        norm_args = json.dumps(
            raw_args if raw_args is not None else {},
            sort_keys=True,
            ensure_ascii=False,
            separators=(',', ':'),
        )
    return name, norm_args


def _has_valid_tool_arguments(tc: dict[str, Any]) -> bool:
    fn = tc.get('function') if isinstance(tc, dict) else None
    if not isinstance(fn, dict):
        return False
    raw_args = fn.get('arguments')
    if isinstance(raw_args, dict):
        return True
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except (ValueError, TypeError):
            return False
        return isinstance(parsed, dict)
    return False


def _parse_tool_call_display(tc: dict[str, Any]) -> dict[str, Any]:
    fn = tc.get('function') if isinstance(tc.get('function'), dict) else tc
    name = str(fn.get('name') or tc.get('name') or '')
    raw_args = fn.get('arguments')
    if isinstance(raw_args, str):
        try:
            args: Any = json.loads(raw_args)
        except (ValueError, TypeError):
            args = raw_args
    elif raw_args is None:
        args = {}
    else:
        args = raw_args
    return {'name': name, 'arguments': args}


def _evaluate_run_record(
    model: str,
    record: dict[str, Any],
    case: dict[str, Any],
    calls: dict[tuple[Any, Any, Any], list[dict[str, Any]]],
) -> dict[str, Any]:
    case_id = record['id']
    run_no = record['run']
    regrade = eval_regrade.regrade_record(record, case, calls)
    passed_official = bool(regrade['passed_official'])
    passed_v2 = bool(regrade['passed_v2'])
    attack_official = bool(regrade['attack_official'])
    attack_v2 = bool(regrade['attack_v2'])

    flags: list[str] = []
    reject_reasons: list[str] = []

    if attack_official or attack_v2:
        reject_reasons.append('attack_success')

    turns = record.get('turns') or []
    expected_turns = len(case.get('turns') or [])
    if len(turns) != expected_turns:
        reject_reasons.append('incomplete_turns')

    total_tool_calls = 0
    total_completion_tokens = 0
    has_any_trace_tokens = False
    rail_turns: list[int] = []

    for k, turn in enumerate(turns, 1):
        if turn.get('error'):
            reject_reasons.append('turn_error')
        if turn.get('answer_check'):
            flags.append('dropped')
        if turn.get('answer_check_audit'):
            flags.append('audit')

        turn_calls = calls.get((case_id, run_no, k), [])
        n_model_calls = len(turn_calls) if turn_calls else int(turn.get('model_calls') or 0)
        turn_answer = str(turn.get('answer') or turn.get('draft_reply') or '').strip()
        seen_sigs: set[tuple[str, str]] = set()
        has_stop = False
        turn_trace_tools = 0
        turn_trace_tokens = 0
        turn_has_trace_tokens = False

        if n_model_calls == 0:
            if not turn.get('error') and turn_answer:
                rail_turns.append(k)
            elif not turn.get('error'):
                reject_reasons.append('missing_stop_call')
        else:
            for c in turn_calls:
                resp = c.get('response') or {}
                fr = resp.get('finish_reason')
                if fr == 'length':
                    reject_reasons.append('finish_reason_length')
                if resp.get('error'):
                    reject_reasons.append('trace_error')
                if fr == 'stop':
                    has_stop = True

                tcs = resp.get('tool_calls') or []
                turn_trace_tools += len(tcs)
                for tc in tcs:
                    if not _has_valid_tool_arguments(tc):
                        reject_reasons.append('invalid_tool_arguments')
                    sig = _canonical_tool_signature(tc)
                    if sig in seen_sigs:
                        flags.append('duplicate_tool')
                    seen_sigs.add(sig)

                usage = resp.get('usage') or {}
                ct = usage.get('completion_tokens')
                if isinstance(ct, (int, float)) and not isinstance(ct, bool):
                    turn_trace_tokens += int(ct)
                    turn_has_trace_tokens = True

            if not has_stop:
                reject_reasons.append('missing_stop_call')

        merged_tools_count = len(turn.get('tools') or [])
        total_tool_calls += turn_trace_tools if turn_trace_tools > 0 else merged_tools_count
        if turn_has_trace_tokens:
            total_completion_tokens += turn_trace_tokens
            has_any_trace_tokens = True
        else:
            total_completion_tokens += int(turn.get('generated_tokens') or 0)

    if turns and len(rail_turns) == len(turns):
        reject_reasons.append('no_model_turns')

    if not has_any_trace_tokens and total_completion_tokens == 0 and record.get('generated_tokens'):
        total_completion_tokens = int(record['generated_tokens'])

    if not (passed_official and passed_v2):
        reject_reasons.append('failed_checks')

    # Deduplicate preserving order
    flags = list(dict.fromkeys(flags))
    reject_reasons = list(dict.fromkeys(reject_reasons))
    turns_text = [
        eval_regrade.model_text(calls, (case_id, run_no, k)) or str(t.get('text') or '')
        for k, t in enumerate(regrade['turns'], 1)
    ]
    answer_chars = sum(len(txt) for txt in turns_text)

    if reject_reasons:
        code_tier = 'rejected'
    elif not flags:
        code_tier = 'A_code'
    else:
        code_tier = 'B_code'

    return {
        'case_id': case_id,
        'model': model,
        'run': run_no,
        'code_tier': code_tier,
        'passed_official': passed_official,
        'passed_v2': passed_v2,
        'attack_official': attack_official,
        'attack_v2': attack_v2,
        'flags': flags,
        'reject_reasons': reject_reasons,
        'tool_calls': total_tool_calls,
        'completion_tokens': total_completion_tokens,
        'answer_chars': answer_chars,
        'turns_count': len(turns),
        'rail_turns': rail_turns,
        'turns_text': turns_text,
    }


def _candidate_sort_key(cand: dict[str, Any]) -> tuple[Any, ...]:
    """Order: Qwen A_code -> DeepSeek A_code -> Qwen B_code -> DeepSeek B_code, then metrics."""
    return (
        TIER_PRIORITY.get(cand['code_tier'], 99),
        MODEL_PRIORITY.get(cand['model'], 99),
        cand['tool_calls'],
        cand['completion_tokens'],
        cand['answer_chars'],
        cand['run'],
    )


def _parse_run_specs(specs: list[str]) -> dict[str, Path]:
    run_dirs: dict[str, Path] = {}
    for spec in specs:
        model, sep, raw_path = spec.partition('=')
        model = model.strip().lower()
        if not sep or not model or not raw_path.strip():
            raise ValueError(f'Invalid --run specification {spec!r}; expected model=dir')
        if model not in MODEL_PRIORITY:
            raise ValueError(f'Unsupported model {model!r}; expected one of {sorted(MODEL_PRIORITY)}')
        if model in run_dirs:
            raise ValueError(f'Duplicate --run for model {model!r}')
        path = Path(raw_path.strip())
        if not (path / 'merged.json').is_file():
            raise ValueError(f'Missing merged.json in {path}')
        run_dirs[model] = path
    return run_dirs


def score_runs(
    cases_path: Path,
    run_specs: dict[str, Path],
) -> dict[str, Any]:
    cases_list = _read_jsonl(cases_path)
    cases = {c['id']: c for c in cases_list}
    if not cases:
        raise ValueError(f'No cases found in {cases_path}')

    run_dir_strings: dict[str, str] = {}
    repo_shas: dict[str, str | None] = {}
    by_case_runs: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for model in sorted(run_specs, key=lambda m: MODEL_PRIORITY.get(m, 99)):
        rdir = run_specs[model]
        run_dir_strings[model] = str(rdir.resolve())
        merged, manifest, calls = eval_regrade.load_run(rdir)
        sha = (merged.get('provenance') or {}).get('git_sha') or manifest.get('git_sha')
        repo_shas[model] = sha
        for record in merged.get('scenarios') or []:
            cid = record['id']
            if cid not in cases:
                raise ValueError(f'Case {cid!r} in {rdir} not found in {cases_path}')
            by_case_runs[cid].append(_evaluate_run_record(model, record, cases[cid], calls))

    case_entries: dict[str, Any] = {}
    for cid, case in cases.items():
        all_runs = by_case_runs.get(cid, [])
        eligible = [r for r in all_runs if r['code_tier'] in ('A_code', 'B_code')]
        eligible.sort(key=_candidate_sort_key)
        for rank, cand in enumerate(eligible):
            cand['rank'] = rank
        rejected = [r for r in all_runs if r['code_tier'] == 'rejected']
        meta = case.get('meta') or {}
        case_entries[cid] = {
            'case_id': cid,
            'template': meta.get('template', ''),
            'suite': meta.get('suite') or case.get('category', '').upper(),
            'style': meta.get('style', ''),
            'actor': case.get('actor', 'customer'),
            'turns_count': len(case.get('turns') or []),
            'candidates': eligible,
            'rejected': rejected,
        }

    return {
        'cases_path': str(cases_path.resolve()),
        'run_dirs': run_dir_strings,
        'repo_sha': repo_shas,
        'cases': case_entries,
    }


def _extract_turn_steps(
    turn_calls: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    """Reconstruct each assistant step (reasoning, tool_calls, truncated tool_results) for one turn."""
    stop_indices = [i for i, c in enumerate(turn_calls) if (c.get('response') or {}).get('finish_reason') == 'stop']
    if not stop_indices:
        return [], ''
    last_stop_idx = stop_indices[-1]
    relevant_calls = turn_calls[:last_stop_idx + 1]
    last_stop = relevant_calls[-1]
    base_len = len((relevant_calls[0].get('request') or {}).get('messages') or [])
    last_msgs = (last_stop.get('request') or {}).get('messages') or []
    tail_msgs = last_msgs[base_len:] if len(last_msgs) >= base_len else []

    # Map tool_call_id -> tool message content, and fallback sequential queue of tool messages
    tool_by_id: dict[str, str] = {}
    tool_queue: list[str] = []
    for m in tail_msgs:
        if m.get('role') == 'tool':
            content_str = str(m.get('content') or '')
            tool_queue.append(content_str)
            tcid = m.get('tool_call_id')
            if isinstance(tcid, str) and tcid:
                tool_by_id[tcid] = content_str

    queue_pos = 0
    steps: list[dict[str, Any]] = []
    for idx, call in enumerate(relevant_calls, 1):
        resp = call.get('response') or {}
        reasoning = str(resp.get('reasoning') or resp.get('reasoning_content') or '')
        raw_tcs = resp.get('tool_calls') or []
        parsed_tcs = [_parse_tool_call_display(tc) for tc in raw_tcs]

        step_results: list[dict[str, Any]] = []
        # If next call exists, check exact slice added between call and next_call
        next_slice_tools: list[dict[str, Any]] = []
        if idx < len(relevant_calls):
            cur_len = len((call.get('request') or {}).get('messages') or [])
            nxt_msgs = (relevant_calls[idx].get('request') or {}).get('messages') or []
            if len(nxt_msgs) > cur_len:
                next_slice_tools = [m for m in nxt_msgs[cur_len:] if m.get('role') == 'tool']

        for j, (raw_tc, tc) in enumerate(zip(raw_tcs, parsed_tcs)):
            tcid = raw_tc.get('id') if isinstance(raw_tc, dict) else None
            raw_res = ''
            if isinstance(tcid, str) and tcid in tool_by_id:
                raw_res = tool_by_id[tcid]
                if queue_pos < len(tool_queue) and tool_queue[queue_pos] == raw_res:
                    queue_pos += 1
            elif j < len(next_slice_tools):
                raw_res = str(next_slice_tools[j].get('content') or '')
                if queue_pos < len(tool_queue):
                    queue_pos += 1
            elif queue_pos < len(tool_queue):
                raw_res = tool_queue[queue_pos]
                queue_pos += 1
            step_results.append({
                'name': tc['name'],
                'content': raw_res[:MAX_TOOL_RESULT_CHARS],
            })

        steps.append({
            'step': idx,
            'reasoning': reasoning,
            'tool_calls': parsed_tcs,
            'tool_results': step_results,
        })

    final_answer = str((last_stop.get('response') or {}).get('content') or '')
    return steps, final_answer


def _format_item_text(steps: list[dict[str, Any]], answer: str) -> str:
    """Build the full searchable assistant text shown to judges for quote verification."""
    parts: list[str] = []
    for st in steps:
        if st.get('reasoning'):
            parts.append(str(st['reasoning']))
        if st.get('tool_calls'):
            parts.append(json.dumps(st['tool_calls'], ensure_ascii=False))
        for tr in st.get('tool_results') or []:
            if tr.get('content'):
                parts.append(str(tr['content']))
    if answer:
        parts.append(answer)
    return '\n'.join(parts)


def _mask_model_names(value: Any) -> Any:
    """Recursively mask model family names (qwen/deepseek variants) to preserve blind judging."""
    if isinstance(value, str):
        return MODEL_NAME_RE.sub('[model]', value)
    if isinstance(value, list):
        return [_mask_model_names(v) for v in value]
    if isinstance(value, dict):
        return {k: _mask_model_names(v) for k, v in value.items()}
    return value


def _sanitize_title(case: dict[str, Any]) -> str:
    title = str(case.get('title') or '')
    for token in (case.get('id'), (case.get('meta') or {}).get('template')):
        if isinstance(token, str) and token:
            title = title.replace(token, ' ')
    title = re.sub(r'\b[ts](?:0[1-9]|1[0-2])_[0-9]{3}[a-z0-9_]*\b', ' ', title, flags=re.IGNORECASE)
    title = re.sub(r'\b[ts](?:0[1-9]|1[0-2])_[a-z0-9_]+\b', ' ', title, flags=re.IGNORECASE)
    title = re.sub(r'\b(?:qwen|deepseek)\b', ' ', title, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', title).strip(' -—:|')


def _turn_context(case: dict[str, Any], turn_no: int) -> dict[str, Any]:
    turns = case.get('turns') or []
    turn = turns[turn_no - 1]
    staff = case.get('actor') == 'staff_case_assist'
    message = turn.get('user') or (
        f"(nhân viên mở Trợ lý ca, chế độ {turn.get('mode') or 'mặc định'})" if staff else ''
    )
    ctx: dict[str, Any] = {
        'title': _sanitize_title(case),
        'role': 'staff_case_assist' if staff else 'customer_chat',
        'turn': turn_no,
        'earlier_customer_messages': [t.get('user', '') for t in turns[:turn_no - 1] if t.get('user')],
        'customer_message': message,
    }
    if staff:
        setup = case.get('case_setup') or {}
        ctx['customer_messages'] = [
            m.get('text', '') for m in (setup.get('customer_messages') or []) if m.get('text')
        ]
    return ctx


def export_judge_round(
    scores_path: Path,
    out_dir: Path,
    *,
    round_no: int = 1,
    after_paths: list[Path] | None = None,
    seed: int = DEFAULT_SEED,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    if (out_dir / 'map.json').exists() or (out_dir / 'packets').exists():
        raise FileExistsError(f'{out_dir} đã có gói chấm; mỗi thư mục chấm chỉ xuất một lần')
    if round_no > 1 and not after_paths:
        raise ValueError(f'--after is required when --round {round_no} > 1')

    scores_data = json.loads(scores_path.read_text(encoding='utf-8'))
    cases_list = _read_jsonl(Path(scores_data['cases_path']))
    cases_by_id = {c['id']: c for c in cases_list}

    cases_with_tier_a: set[str] = set()
    already_judged: set[tuple[str, str, int]] = set()
    for path in (after_paths or []):
        adj = json.loads(path.read_text(encoding='utf-8'))
        for cand in (adj.get('candidates') or {}).values():
            cid, model, run_no = cand['case_id'], cand['model'], int(cand['run'])
            already_judged.add((cid, model, run_no))
            if cand.get('tier') == 'A':
                cases_with_tier_a.add(cid)

    selected_candidates: list[dict[str, Any]] = []
    for cid, entry in scores_data['cases'].items():
        if round_no > 1 and cid in cases_with_tier_a:
            continue
        for cand in entry.get('candidates') or []:
            key = (cid, cand['model'], int(cand['run']))
            if round_no == 1 or key not in already_judged:
                selected_candidates.append(cand)
                break

    # Load traces for needed models only
    calls_by_model: dict[str, dict[tuple[Any, Any, Any], list[dict[str, Any]]]] = {}
    for model in {c['model'] for c in selected_candidates}:
        rdir = Path(scores_data['run_dirs'][model])
        _, _, calls = eval_regrade.load_run(rdir)
        calls_by_model[model] = calls

    rng = random.Random(seed)
    items: list[dict[str, Any]] = []
    cand_map: dict[str, dict[str, Any]] = {}

    for cand in selected_candidates:
        cid = cand['case_id']
        model = cand['model']
        run_no = int(cand['run'])
        case = cases_by_id[cid]
        calls = calls_by_model[model]
        cand_key = f'{cid}#{model}#{run_no}'
        cand_item_indices: list[int] = []

        rail_turns = set(cand.get('rail_turns') or [])
        for turn_no in range(1, len(case.get('turns') or []) + 1):
            if turn_no in rail_turns:
                continue
            turn_calls = calls.get((cid, run_no, turn_no), [])
            steps, trace_answer = _extract_turn_steps(turn_calls)
            turns_text = cand.get('turns_text') or []
            fallback_answer = turns_text[turn_no - 1] if turn_no - 1 < len(turns_text) else ''
            answer = trace_answer if trace_answer else fallback_answer
            masked_context = _mask_model_names(_turn_context(case, turn_no))
            masked_steps = _mask_model_names(steps)
            masked_answer = _mask_model_names(answer)
            full_text = _mask_model_names(_format_item_text(masked_steps, masked_answer))
            items.append({
                'case_id': cid,
                'model': model,
                'run': run_no,
                'turn': turn_no,
                'code_tier': cand['code_tier'],
                'rank': cand['rank'],
                'candidate_key': cand_key,
                'context': masked_context,
                'steps': masked_steps,
                'answer': masked_answer,
                'text': full_text,
            })
            cand_item_indices.append(len(items) - 1)

        cand_map[cand_key] = {
            'case_id': cid,
            'model': model,
            'run': run_no,
            'code_tier': cand['code_tier'],
            'rank': cand['rank'],
            'item_indices': cand_item_indices,
        }

    ids: set[str] = set()
    while len(ids) < len(items):
        ids.add(f'{rng.getrandbits(32):08x}')
    id_list = sorted(ids)
    rng.shuffle(id_list)
    for item, item_id in zip(items, id_list):
        item['item_id'] = item_id

    order = list(range(len(items)))
    rng.shuffle(order)
    batches = [order[i:i + batch_size] for i in range(0, len(order), batch_size)]

    packets_dir = out_dir / 'packets'
    packets_dir.mkdir(parents=True, exist_ok=True)
    for batch_num, batch in enumerate(batches, 1):
        lines = [
            json.dumps({
                'item_id': items[idx]['item_id'],
                'kind': 'sft_tier',
                'context': items[idx]['context'],
                'steps': items[idx]['steps'],
                'answer': items[idx]['answer'],
                'requirement': REQUIREMENT_TEXT,
            }, ensure_ascii=False)
            for idx in batch
        ]
        (packets_dir / f'batch-{batch_num:02d}.jsonl').write_text(
            '\n'.join(lines) + '\n', encoding='utf-8'
        )

    mapping = {
        'round': round_no,
        'scores_path': str(scores_path.resolve()),
        'seed': seed,
        'batch_size': batch_size,
        'batches': {
            f'batch-{n:02d}': [items[i]['item_id'] for i in b]
            for n, b in enumerate(batches, 1)
        },
        'items': {
            it['item_id']: {
                'case_id': it['case_id'],
                'model': it['model'],
                'run': it['run'],
                'turn': it['turn'],
                'code_tier': it['code_tier'],
                'rank': it['rank'],
                'candidate_key': it['candidate_key'],
                'text': it['text'],
            }
            for it in items
        },
        'candidates': {
            key: {
                'case_id': val['case_id'],
                'model': val['model'],
                'run': val['run'],
                'code_tier': val['code_tier'],
                'rank': val['rank'],
                'item_ids': [items[idx]['item_id'] for idx in val['item_indices']],
            }
            for key, val in cand_map.items()
        },
    }
    _write_json(out_dir / 'map.json', mapping)
    return {
        'round': round_no,
        'candidates': len(selected_candidates),
        'items': len(items),
        'batches': len(batches),
    }


def effective_tier_verdict(row: dict[str, Any], item: dict[str, Any]) -> str:
    """Verify verbatim quote (>= MIN_QUOTE under v2) for both 'dat' and 'khong_dat'."""
    verdict = row['verdict']
    if verdict == 'dat':
        return eval_regrade.effective(row, item)
    if verdict == 'khong_dat':
        quote = eval_regrade.v2(row.get('quote') or '')
        return (
            'khong_dat'
            if len(quote) >= eval_regrade.MIN_QUOTE and quote in eval_regrade.v2(item['text'])
            else 'khong_chac'
        )
    return 'khong_chac'


def import_judge_round(
    judge_dir: Path,
    scores_path: Path,
    out_path: Path,
) -> tuple[int, dict[str, Any]]:
    mapping = json.loads((judge_dir / 'map.json').read_text(encoding='utf-8'))
    a, errors_a = eval_regrade.read_verdicts(judge_dir, 'A', mapping)
    b, errors_b = eval_regrade.read_verdicts(judge_dir, 'B', mapping)
    if errors_a or errors_b:
        return 2, {'errors': errors_a + errors_b}

    items = mapping['items']
    verdicts_out: dict[str, dict[str, Any]] = {}
    pairs: list[tuple[str, str]] = []
    downgraded = {'a': {'dat': 0, 'khong_dat': 0}, 'b': {'dat': 0, 'khong_dat': 0}}

    for item_id, item in items.items():
        va = effective_tier_verdict(a[item_id], item)
        vb = effective_tier_verdict(b[item_id], item)
        ra = a[item_id]['verdict']
        rb = b[item_id]['verdict']
        if ra in ('dat', 'khong_dat') and va != ra:
            downgraded['a'][ra] += 1
        if rb in ('dat', 'khong_dat') and vb != rb:
            downgraded['b'][rb] += 1
        verdicts_out[item_id] = {
            'a_raw': ra,
            'b_raw': rb,
            'a': va,
            'b': vb,
            'both_dat': va == 'dat' and vb == 'dat',
            'any_khong_dat': va == 'khong_dat' or vb == 'khong_dat',
        }
        pairs.append((va, vb))

    cand_results: dict[str, dict[str, Any]] = {}
    tier_counts: Counter[str] = Counter()
    for key, cand in (mapping.get('candidates') or {}).items():
        item_ids = cand.get('item_ids') or []
        turn_verdicts = [verdicts_out[iid] for iid in item_ids]
        if any(tv['any_khong_dat'] for tv in turn_verdicts):
            tier = 'C'
        elif (
            cand.get('code_tier') == 'A_code'
            and turn_verdicts
            and all(tv['both_dat'] for tv in turn_verdicts)
        ):
            tier = 'A'
        else:
            tier = 'B'
        tier_counts[tier] += 1
        cand_results[key] = {
            'case_id': cand['case_id'],
            'model': cand['model'],
            'run': cand['run'],
            'code_tier': cand['code_tier'],
            'rank': cand['rank'],
            'item_ids': item_ids,
            'tier': tier,
        }

    agreed = sum(x == y for x, y in pairs)
    result = {
        'round': mapping.get('round', 1),
        'judge_dir': str(judge_dir.resolve()),
        'scores_path': str(scores_path.resolve()),
        'agreement_ab': {
            'items': len(pairs),
            'agreed': agreed,
            'percent': (agreed / len(pairs)) if pairs else None,
            'kappa': eval_regrade.kappa(pairs),
        },
        'downgraded_quotes': downgraded,
        'tier_counts': dict(tier_counts),
        'verdicts': verdicts_out,
        'candidates': cand_results,
    }
    _write_json(out_path, result)
    return 0, result


def _pct_str(val: float | None) -> str:
    return '-' if val is None else f'{100.0 * val:.1f}%'


def _describe_drop_reason(
    case_entry: dict[str, Any],
    allow_b: bool,
    adjudicated_by_cand: dict[tuple[str, str, int], dict[str, Any]],
) -> tuple[str, list[str]]:
    cid = case_entry['case_id']
    candidates = case_entry.get('candidates') or []
    rejected = case_entry.get('rejected') or []
    if not candidates and not rejected:
        return 'no_runs', []
    if not candidates:
        reasons = sorted({r for run in rejected for r in run.get('reject_reasons') or []})
        return 'no_passing_code_candidate', reasons
    if allow_b:
        return 'no_tier_a_or_b', []
    any_judged = any((cid, c['model'], int(c['run'])) in adjudicated_by_cand for c in candidates)
    a_code_cands = [c for c in candidates if c.get('code_tier') == 'A_code']
    unjudged_a = any((cid, c['model'], int(c['run'])) not in adjudicated_by_cand for c in a_code_cands)
    if not any_judged or unjudged_a:
        return 'not_judged_yet', []
    return 'no_tier_a_judged', []


def select_candidates(
    scores_path: Path,
    adjudicated_paths: list[Path],
    out_path: Path,
    *,
    allow_b: bool = False,
) -> dict[str, Any]:
    scores_data = json.loads(scores_path.read_text(encoding='utf-8'))
    adjudicated_by_cand: dict[tuple[str, str, int], dict[str, Any]] = {}
    all_pairs: list[tuple[str, str]] = []
    seen_round_items: set[tuple[Any, str]] = set()
    round_agreements: list[dict[str, Any]] = []

    for adj_path in adjudicated_paths:
        adj = json.loads(adj_path.read_text(encoding='utf-8'))
        rnd = adj.get('round')
        jdir = adj.get('judge_dir', str(adj_path))
        round_agreements.append({
            'round': rnd,
            **(adj.get('agreement_ab') or {}),
        })
        for iid, v in (adj.get('verdicts') or {}).items():
            key_item = (jdir, iid)
            if key_item not in seen_round_items:
                seen_round_items.add(key_item)
                all_pairs.append((v['a'], v['b']))
        for cand in (adj.get('candidates') or {}).values():
            ckey = (cand['case_id'], cand['model'], int(cand['run']))
            adjudicated_by_cand[ckey] = cand

    selected: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    for cid, case_entry in scores_data['cases'].items():
        candidates = case_entry.get('candidates') or []
        chosen: dict[str, Any] | None = None
        chosen_tier: str | None = None
        used_fallback = False

        # First pass: look for Tier A in candidate rank order
        for cand in candidates:
            adj_c = adjudicated_by_cand.get((cid, cand['model'], int(cand['run'])))
            if adj_c and adj_c.get('tier') == 'A':
                chosen = cand
                chosen_tier = 'A'
                break

        # Second pass: optional --allow-b fallback
        if chosen is None and allow_b:
            for cand in candidates:
                adj_c = adjudicated_by_cand.get((cid, cand['model'], int(cand['run'])))
                if adj_c and adj_c.get('tier') == 'B':
                    chosen = cand
                    chosen_tier = 'B'
                    used_fallback = True
                    break

        if chosen is not None and chosen_tier is not None:
            model = chosen['model']
            selected.append({
                'case_id': cid,
                'template': case_entry.get('template', ''),
                'suite': case_entry.get('suite', ''),
                'style': case_entry.get('style', ''),
                'actor': case_entry.get('actor', 'customer'),
                'source_model': model,
                'run': int(chosen['run']),
                'tier': chosen_tier,
                'code_tier': chosen['code_tier'],
                'allow_b_fallback': used_fallback,
                'run_dir': scores_data['run_dirs'][model],
                'repo_sha': (scores_data.get('repo_sha') or {}).get(model),
                'turns_count': int(case_entry.get('turns_count') or chosen.get('turns_count') or 1),
                'rail_turns': list(chosen.get('rail_turns') or []),
                'tool_calls': chosen['tool_calls'],
                'completion_tokens': chosen['completion_tokens'],
                'answer_chars': chosen['answer_chars'],
            })
        else:
            reason, detail = _describe_drop_reason(case_entry, allow_b, adjudicated_by_cand)
            dropped.append({
                'case_id': cid,
                'template': case_entry.get('template', ''),
                'suite': case_entry.get('suite', ''),
                'reason': reason,
                'detail': detail,
            })

    total_cases = len(scores_data['cases'])
    by_model = Counter(s['source_model'] for s in selected)
    by_suite = Counter(s['suite'] for s in selected)
    by_template = Counter(s['template'] for s in selected)
    drop_reasons = Counter(d['reason'] for d in dropped)
    agreed = sum(a == b for a, b in all_pairs)
    overall_agree = {
        'items': len(all_pairs),
        'agreed': agreed,
        'percent': (agreed / len(all_pairs)) if all_pairs else None,
        'kappa': eval_regrade.kappa(all_pairs),
    }

    selection = {
        'scores_path': str(scores_path.resolve()),
        'cases_path': scores_data.get('cases_path'),
        'run_dirs': scores_data.get('run_dirs') or {},
        'repo_sha': scores_data.get('repo_sha') or {},
        'allow_b': allow_b,
        'selected': selected,
        'dropped': dropped,
        'summary': {
            'total_cases': total_cases,
            'selected_cases': len(selected),
            'dropped_cases': len(dropped),
            'by_model': {m: by_model.get(m, 0) for m in ('qwen', 'deepseek')},
            'by_suite': dict(sorted(by_suite.items())),
            'by_template': dict(sorted(by_template.items())),
            'drop_reasons': dict(sorted(drop_reasons.items())),
            'agreement_ab': overall_agree,
            'rounds': round_agreements,
        },
    }
    _write_json(out_path, selection)
    report_path = out_path.parent / 'selection_report.md'
    report_path.write_text(_render_selection_report(selection), encoding='utf-8')
    return selection


def _render_selection_report(selection: dict[str, Any]) -> str:
    s = selection['summary']
    total = s['total_cases']
    sel_n = s['selected_cases']
    drop_n = s['dropped_cases']
    by_model = s['by_model']
    qwen_n = by_model.get('qwen', 0)
    ds_n = by_model.get('deepseek', 0)
    ag = s['agreement_ab']
    k_val = '-' if ag['kappa'] is None else f"{ag['kappa']:.3f}"

    lines = [
        '# Báo cáo chọn mẫu SFT (`sft_select`)',
        '',
        '## Tổng quan',
        '',
        f'- Tổng số ca đầu vào: **{total}**',
        f'- Số ca chọn được mẫu: **{sel_n}** ({_pct_str(sel_n / total if total else None)})',
        f'- Số ca bị bỏ: **{drop_n}**',
        f'- Cho phép fallback Tier B (`--allow-b`): **{selection["allow_b"]}**',
        f'- Độ khớp giám khảo A–B: **{_pct_str(ag["percent"])}** trên {ag["items"]} mục, Cohen\'s kappa = **{k_val}**',
        '',
        '## Tỉ lệ nguồn mẫu (Qwen / DeepSeek)',
        '',
        '| Nguồn | Số ca | Tỉ lệ trong ca được chọn |',
        '|---|---|---|',
        f'| `qwen` | {qwen_n} | {_pct_str(qwen_n / sel_n if sel_n else None)} |',
        f'| `deepseek` | {ds_n} | {_pct_str(ds_n / sel_n if sel_n else None)} |',
        '',
        '## Phân bổ theo bộ (`suite`)',
        '',
        '| Bộ | Số ca |',
        '|---|---|',
    ]
    for suite, cnt in sorted(s['by_suite'].items()):
        lines.append(f'| {suite} | {cnt} |')
    if not s['by_suite']:
        lines.append('| (trống) | 0 |')

    lines += [
        '',
        '## Phân bổ theo khung (`template`)',
        '',
        '| Khung | Số ca |',
        '|---|---|',
    ]
    for tmpl, cnt in sorted(s['by_template'].items()):
        lines.append(f'| `{tmpl}` | {cnt} |')
    if not s['by_template']:
        lines.append('| (trống) | 0 |')

    lines += [
        '',
        f'## Ca bị bỏ ({drop_n})',
        '',
        '| Lý do | Số ca |',
        '|---|---|',
    ]
    for reason, cnt in sorted(s['drop_reasons'].items()):
        lines.append(f'| `{reason}` | {cnt} |')
    if not s['drop_reasons']:
        lines.append('| (không có) | 0 |')

    if selection['dropped']:
        lines += ['', 'Chi tiết ca bị bỏ:', '']
        for d in selection['dropped']:
            detail = f' ({", ".join(d["detail"])})' if d.get('detail') else ''
            lines.append(f'- `{d["case_id"]}` [{d["suite"]}/{d["template"]}]: `{d["reason"]}`{detail}')

    lines.append('')
    return '\n'.join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='sft_select.py', description=__doc__.split('\n\n')[0])
    parser.add_argument('--print-rubric', action='store_true', help='In đầy đủ hướng dẫn chấm tier cho giám khảo và thoát')
    sub = parser.add_subparsers(dest='command')

    p_score = sub.add_parser('score', help='Chấm code, gắn cờ và xếp hạng ứng viên từ kết quả runner')
    p_score.add_argument('--cases', required=True, type=Path, help='Tệp ca huấn luyện JSONL')
    p_score.add_argument('--run', action='append', required=True, metavar='MODEL=DIR',
                         help='Thư mục kết quả theo model, ví dụ qwen=dir hoặc deepseek=dir')
    p_score.add_argument('--out', required=True, type=Path, help='Đường dẫn scores.json đầu ra')

    p_exp = sub.add_parser('export', help='Xuất gói giám khảo ẩn danh cho vòng 1 hoặc vòng 2')
    p_exp.add_argument('--scores', required=True, type=Path, help='Tệp scores.json')
    p_exp.add_argument('--out', required=True, type=Path, help='Thư mục gói chấm đầu ra')
    p_exp.add_argument('--round', type=int, default=1, help='Số vòng chấm (1 hoặc 2)')
    p_exp.add_argument('--after', nargs='+', action='append', type=Path, default=None,
                       help='Tệp adjudicated JSON từ các vòng trước (bắt buộc nếu --round >= 2)')
    p_exp.add_argument('--seed', type=int, default=DEFAULT_SEED)
    p_exp.add_argument('--batch-size', type=int, default=DEFAULT_BATCH_SIZE)

    p_imp = sub.add_parser('import', help='Đọc phiếu giám khảo A/B, kiểm trích dẫn và xếp Tier A/B/C')
    p_imp.add_argument('--judge-dir', required=True, type=Path, help='Thư mục gói chấm chứa map.json và verdicts/')
    p_imp.add_argument('--scores', required=True, type=Path, help='Tệp scores.json')
    p_imp.add_argument('--out', required=True, type=Path, help='Tệp adjudicated JSON đầu ra')

    p_sel = sub.add_parser('select', help='Gộp kết quả các vòng adjudicated và chọn 1 lượt chạy mỗi ca')
    p_sel.add_argument('--scores', required=True, type=Path, help='Tệp scores.json')
    p_sel.add_argument('--adjudicated', nargs='+', action='append', required=True, type=Path,
                       help='Một hoặc nhiều tệp adjudicated JSON')
    p_sel.add_argument('--allow-b', action='store_true', help='Cho phép fallback sang Tier B nếu ca không có Tier A')
    p_sel.add_argument('--out', required=True, type=Path, help='Tệp selection.json đầu ra')

    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.print_rubric:
        print(RUBRIC_TEXT)
        return 0
    if not args.command:
        parser.error('a subcommand (score, export, import, select) or --print-rubric is required')

    try:
        if args.command == 'score':
            run_specs = _parse_run_specs(args.run)
            result = score_runs(args.cases, run_specs)
            _write_json(args.out, result)
            total = len(result['cases'])
            with_cand = sum(1 for c in result['cases'].values() if c['candidates'])
            print(f'score: {total} ca, {with_cand} ca có ứng viên A_code/B_code -> {args.out}')
            return 0

        if args.command == 'export':
            after_flat = [p for grp in (args.after or []) for p in grp]
            info = export_judge_round(
                args.scores,
                args.out,
                round_no=args.round,
                after_paths=after_flat,
                seed=args.seed,
                batch_size=args.batch_size,
            )
            print(
                f"export vòng {info['round']}: {info['candidates']} ứng viên, "
                f"{info['items']} lượt trong {info['batches']} lô -> {args.out}"
            )
            return 0

        if args.command == 'import':
            code, res = import_judge_round(args.judge_dir, args.scores, args.out)
            if code != 0:
                print('Phiếu chưa hợp lệ, chưa gộp:\n  ' + '\n  '.join(res['errors']))
                return code
            ag = res['agreement_ab']
            print(
                f"import vòng {res['round']}: tier={res['tier_counts']}, "
                f"khớp A-B={_pct_str(ag['percent'])}, kappa={ag['kappa']} -> {args.out}"
            )
            return 0

        if args.command == 'select':
            adj_flat = [p for grp in args.adjudicated for p in grp]
            sel = select_candidates(args.scores, adj_flat, args.out, allow_b=args.allow_b)
            s = sel['summary']
            print(
                f"select: {s['selected_cases']}/{s['total_cases']} ca được chọn "
                f"(qwen={s['by_model']['qwen']}, deepseek={s['by_model']['deepseek']}) -> {args.out}"
            )
            return 0
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f'Lỗi: {exc}', file=sys.stderr)
        return 2

    return 0


if __name__ == '__main__':
    sys.exit(main())
