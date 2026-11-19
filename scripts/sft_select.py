#!/usr/bin/env python3
"""W6.7.0 / W6.7.2 Part B1: Select SFT distillation candidates, export blind judge packets, and assign tiers.

Subcommands:
  --print-rubric    Print the full tier-judging rubric for human/LLM judges
  --print-rubric-s  Print the Tier S pairwise rubric for human/LLM judges
  score             Code-grade, flag, filter, and rank runs from Qwen and DeepSeek
  export            Export anonymised blind judge packets (round 1, round 2 --after, or --arbiter)
  import            Validate judge verdicts, verify verbatim quotes, assign Tier A/B/C (or --arbiter)
  export-tier-s     Export pairwise blind packets for Tier S grading
  import-tier-s     Validate Tier S pairwise verdicts, verify 7 quotes per slot, label S and pair diff
  select            Merge adjudicated rounds/Tier S and select up to 2 runs per case with caps
"""
from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import eval_regrade  # noqa: E402

MODEL_PRIORITY = {'qwen': 0, 'deepseek': 1}
TIER_PRIORITY = {'A_code': 0, 'B_code': 1}
MODEL_NAME_RE = re.compile(r'(?i)\b(?:qwen|deepseek)[\w./:-]*')
DEFAULT_MAX_TOOL_CHARS = 3000
DEFAULT_SEED = 20261203
DEFAULT_BATCH_SIZE = 25
DEFAULT_TIER_S_BATCH_SIZE = 20

# Hằng số dùng chung W6.7.2 — theo quyết định owner ngày 19/11/2026:
# - W6.7.3: 4 bộ khó; T11 chỉ lấy mẫu thứ hai qua Tier S của chính ca đó.
HARD_SUITES = frozenset({'T05', 'T06', 'T08', 'T12'})
# - T09/T10/T14 áp trần mẫu thứ hai chặt hơn (<= 25% số ca có mẫu chính của khung).
EASY_TIGHT = frozenset({'T09', 'T10', 'T14'})
# - Trần số ca có mẫu thứ hai theo khung: 50% khung thường, 25% cho T09/T10.
SECOND_CAP = 0.5
SECOND_CAP_TIGHT = 0.25
# - Trần tỉ trọng DeepSeek toàn tập (chính + thứ hai) <= 35%; chỉ bỏ mẫu thứ hai khi vượt.
DEEPSEEK_SHARE_CAP = 0.35
# - Ngưỡng độ giống tối đa giữa 2 lượt CÙNG model (Qwen); không dùng giữa 2 model khác nhau.
QWEN_SECOND_MAX_SIM = 0.85
# - Nhận diện ký tự Hán/Nhật/Hàn (Hiragana, Katakana, CJK Ext A, CJK Unified, Hangul).
CJK_PATTERN = r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]'
CJK_RE = re.compile(CJK_PATTERN)
CJK_SPAN_RE = re.compile(CJK_PATTERN + '+')

TIER_S_CRITERIA = ('1', '2', '3', '4', '5', '6', '7')
TIER_S_TOT_HON = ('mau_1', 'mau_2', 'ngang')
TIER_S_KHAC_BIET = ('cach_xu_ly', 'thong_tin', 'chi_cau_chu')
TIER_S_REQUIREMENT_TEXT = (
    'Đánh giá từng mẫu (mau_1, mau_2) xem có đạt Tier S (đủ cả 7 tiêu chí kèm trích dẫn nguyên văn từ đúng mẫu đó) hay không, '
    'so sánh mẫu nào tốt hơn (tot_hon) và phân loại mức độ khác biệt giữa hai mẫu (khac_biet).'
)
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


def rubric_text(max_tool_chars: int = DEFAULT_MAX_TOOL_CHARS) -> str:
    # W6.7.1: mốc hiển thị phải khớp giới hạn dùng khi xuất gói chấm.
    if max_tool_chars <= 0:
        raise ValueError('--max-tool-chars phải lớn hơn 0')
    return RUBRIC_TEXT.replace('3.000 ký tự', f"{max_tool_chars:,} ký tự".replace(',', '.'))


TIER_S_RUBRIC = """# Hướng dẫn chấm cặp Tier S dữ liệu SFT (W6.7.2)

Bạn là giám khảo đánh giá cặp mẫu hội thoại đã đạt Tier A cho hệ thống chăm sóc khách hàng bán lẻ bằng tiếng Việt.
Mỗi mục gồm **một lượt hội thoại hoàn chỉnh** với hai mẫu ứng viên (`mau_1` và `mau_2`) cùng ngữ cảnh `context`.
Thứ tự `mau_1` và `mau_2` được xáo ngẫu nhiên theo từng mục. Bạn **không** biết model nào (`qwen` / `deepseek`), mã ca, hay lần chạy; **không đoán model**, **không thiên vị câu dài**.

## Bạn được xem gì

- `context`: ngữ cảnh lượt hội thoại (`title`, `role`, `turn`, `earlier_customer_messages`, `customer_message`, và `customer_messages` nếu là `staff_case_assist`).
- `mau_1` và `mau_2`: mỗi mẫu gồm `steps` (`reasoning`, `tool_calls`, `tool_results` cắt tối đa 8.000 ký tự) và `answer`.

## 7 tiêu chí Tier S (mẫu đạt `S = true` khi và chỉ khi đạt ĐỦ cả 7 tiêu chí)

Với **mỗi** tiêu chí 1–7, nếu chấm `S = true`, bạn phải trích **nguyên văn** một đoạn (dài ít nhất 8 ký tự) nằm trong văn bản của **đúng mẫu đó** (`mau_1` lấy từ `mau_1`, `mau_2` lấy từ `mau_2`). Thiếu hoặc sai trích dẫn (kể cả lấy nhầm từ mẫu kia) sẽ khiến mẫu bị hạ `S = false`.

1. **Đầy đủ** — trả lời mọi ý khách hỏi trong lượt.
2. **Đúng trọng tâm** — suy luận nêu đúng dữ kiện quyết định từ kết quả tool (trạng thái, hạn, điều kiện) và đi thẳng tới kết luận, không vòng vo, không tự mâu thuẫn.
3. **Giàu thông tin hữu ích** — chủ động nêu thêm điều khách sẽ cần (hạn còn lại, trạng thái hoàn tiền, phí, bước tiếp theo, lựa chọn thay thế hợp lệ). Mọi câu thêm phải có căn cứ trong kết quả tool/KB và liên quan đến việc của khách; câu xã giao, lặp lại, chung chung không được tính, nhiều câu như vậy thì trượt tiêu chí này. Không chấm theo độ dài.
4. **Dùng tool tiết kiệm** — không gọi trùng, không gọi thừa so với điều cần kiểm.
5. **Dẫn đúng nguồn** — chính sách nêu ra khớp đúng tài liệu KB được trích.
6. **Đúng quy trình** — bước xử lý (mở biểu mẫu, chuyển nhân viên, hướng dẫn) đúng chính sách, không hứa vượt chính sách.
7. **Rõ ràng với khách Việt** — bố cục dễ đọc, tiếng Việt tự nhiên, không lẫn chữ nước ngoài (Hán/Nhật/Hàn…).

## So sánh cặp

- `tot_hon`: chọn một trong `"mau_1"`, `"mau_2"`, `"ngang"`.
- `khac_biet`: phân loại khác biệt giữa hai mẫu trong lượt này:
  - `"cach_xu_ly"`: khác hướng giải quyết hoặc thứ tự kiểm tra.
  - `"thong_tin"`: khác thông tin hữu ích đưa cho khách.
  - `"chi_cau_chu"`: cùng cách xử lý và cùng thông tin, chỉ khác cách diễn đạt/câu chữ.

## Ghi phiếu

Mỗi mục ghi một dòng JSON trong `verdicts/batch-NN.jsonl` với đúng `item_id`:

```json
{
  "item_id": "a3f91c07",
  "mau_1": {"S": true, "bang_chung": {"1": "...", "2": "...", "3": "...", "4": "...", "5": "...", "6": "...", "7": "..."}, "truot": []},
  "mau_2": {"S": false, "bang_chung": {"1": "..."}, "truot": [3, 7]},
  "tot_hon": "mau_1",
  "khac_biet": "thong_tin",
  "reason": "Một câu tiếng Việt tóm tắt lý do."
}
```

- Không bỏ sót mục, không thêm mục, không sửa tệp trong `packets/`, không mở `map.json`.
"""


def tier_s_rubric_text(max_tool_chars: int = 8000) -> str:
    if max_tool_chars <= 0:
        raise ValueError('--max-tool-chars phải lớn hơn 0')
    return TIER_S_RUBRIC.replace('8.000 ký tự', f"{max_tool_chars:,} ký tự".replace(',', '.'))


def _norm_sim_text(text: str) -> str:
    """Chuẩn hóa câu chữ để đo độ giống giữa 2 lượt CÙNG model (03 thiết kế W6.7.2)."""
    cleaned = re.sub(r'[*#`>|_-]', '', str(text or '').lower())
    return re.sub(r'\s+', ' ', cleaned)[:3000]


def candidate_text_similarity(cand_a: dict[str, Any], cand_b: dict[str, Any]) -> float:
    """Độ giống câu chữ (SequenceMatcher) giữa 2 lượt cùng model; không dùng giữa 2 model khác nhau."""
    a = '\n'.join(str(x or '') for x in (cand_a.get('turns_text') or []))
    b = '\n'.join(str(x or '') for x in (cand_b.get('turns_text') or []))
    return difflib.SequenceMatcher(None, _norm_sim_text(a), _norm_sim_text(b)).ratio()


def _parse_exclude_templates(raw: Any) -> set[str]:
    out: set[str] = set()
    if not raw:
        return out
    items: list[Any] = [raw] if isinstance(raw, str) else list(raw)
    for item in items:
        if isinstance(item, (list, tuple, set, frozenset)):
            out.update(_parse_exclude_templates(item))
        elif isinstance(item, str):
            for part in item.split(','):
                name = part.strip()
                if name:
                    out.add(name)
    return out


def _hash_tiebreak(seed: int, case_id: str) -> str:
    return hashlib.sha256(f'{seed}:{case_id}'.encode('utf-8')).hexdigest()


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
    # v3: chấm lại theo kỳ vọng hiện tại của ca (thước đã hiệu chỉnh theo bộ đo, W6.7.0 18/11) — trùng runner khi kỳ vọng
    # không đổi (kiểm trên 7.200 lượt Qwen + DeepSeek), trừ trần tool: vượt trần chỉ gắn cờ over_tool_budget (hạng B).
    regrade = eval_regrade.regrade_record_v3(record, case, calls)
    passed_official = bool(regrade['passed_official'])
    passed_v2 = bool(regrade['passed_v2'])
    passed_v3 = bool(regrade['passed_v3'])
    # Cờ tấn công kiểu runner tính lại với attack_not hiện tại (trùng cờ runner khi kỳ vọng không đổi; W6.7.0 19/11)
    attack_official = bool(regrade['attack_official_v3'])
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

    if not passed_v3:
        reject_reasons.append('failed_checks')
    flags += regrade['flags_v3']

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
        'passed_v3': passed_v3,
        'failures_v3': regrade['failures_v3'],
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
    *, runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cases_list = _read_jsonl(cases_path)
    cases = {c['id']: c for c in cases_list}
    if not cases:
        raise ValueError(f'No cases found in {cases_path}')

    run_dir_strings: dict[str, str] = {}
    repo_shas: dict[str, str | None] = {}
    by_case_runs: dict[str, list[dict[str, Any]]] = defaultdict(list)

    specs = runs if runs is not None else [
        {'model': m, 'dir': str(run_specs[m]), 'run_offset': 0, 'hinted': False}
        for m in sorted(run_specs, key=lambda m: MODEL_PRIORITY.get(m, 99))]
    if runs is not None and (not isinstance(runs, list) or not runs):
        raise ValueError('--runs phải chứa danh sách lượt chạy không rỗng')
    occupied = set()
    run_owners = {}
    labels = set()
    for spec_no, spec in enumerate(specs):
        model, rdir = spec['model'], Path(spec['dir'])
        if model not in MODEL_PRIORITY:
            raise ValueError(f'Model không hợp lệ: {model}')
        offset = spec.get('run_offset', 0)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError('run_offset phải là số nguyên không âm')
        if runs is not None:
            if ('run_offset' not in spec or not isinstance(spec.get('label'), str) or not spec['label']
                    or spec['label'] in labels or not isinstance(spec.get('hinted'), bool)):
                raise ValueError('Mỗi lượt chạy cần label duy nhất và hinted kiểu boolean')
            labels.add(spec['label'])
        run_dir_strings[model] = str(rdir.resolve())
        merged, manifest, calls = eval_regrade.load_run(rdir)
        sha = (merged.get('provenance') or {}).get('git_sha') or manifest.get('git_sha')
        repo_shas[model] = sha
        logs = _read_jsonl(Path(spec['hint_log'])) if spec.get('hint_log') else []
        verified_requests = {(row.get('case_id'), row.get('turn'), row.get('request_sha256'))
                             for row in logs if row.get('hinted') is True}
        for record in merged.get('scenarios') or []:
            cid = record['id']
            if cid not in cases:
                raise ValueError(f'Case {cid!r} in {rdir} not found in {cases_path}')
            shifted_run = record['run'] + offset
            key = (model, cid, shifted_run)
            owner = (model, shifted_run)
            if key in occupied or (owner in run_owners and run_owners[owner] != spec_no):
                raise ValueError(f'Số run trùng theo model: {model}#{shifted_run}')
            occupied.add(key)
            run_owners[owner] = spec_no
            cand = _evaluate_run_record(model, record, cases[cid], calls)
            reasons = []
            for number, turn in enumerate(record.get('turns') or [], 1):
                current = cases[cid].get('turns', [])
                if number <= len(current) and 'user' in turn and turn['user'] != current[number-1]['user']:
                    reasons.append('stale_input')
                traces = calls.get((cid, record['run'], number), [])
                # Vết cũ thiếu trường user không đủ dữ kiện để kết luận đầu vào đổi.
                # Không suy ngược từ prompt đã định dạng/che dữ liệu của ứng dụng.
                if spec.get('hinted'):
                    text = json.dumps([t.get('response') or {} for t in traces], ensure_ascii=False)
                    text += json.dumps({k: v for k, v in turn.items() if k in ('answer', 'draft_reply', 'reasoning', 'reasoning_content')}, ensure_ascii=False)
                    if re.search(r'GOI_Y|HET_GOI_Y|gợi ý sinh dữ liệu|\bhint\b', text, re.I):
                        reasons.append('hint_leak')
                    # Mỗi lời gọi đã chèn phải có dấu vết khớp hash thân yêu cầu gốc.
                    from scripts.sft_hint_proxy import sha256
                    verified = bool(traces) and all(
                        (cid, number, sha256(json.dumps(t.get('request') or {}, ensure_ascii=False).encode('utf-8')))
                        in verified_requests for t in traces)
                    if not verified:
                        cand['flags'].append('hint_unverified')
            if reasons:
                cand['code_tier'] = 'rejected'
                cand['reject_reasons'] = list(dict.fromkeys(cand['reject_reasons'] + reasons))
            elif cand['flags'] and cand['code_tier'] == 'A_code':
                cand['code_tier'] = 'B_code'
            cand['flags'] = list(dict.fromkeys(cand['flags']))
            if runs is not None:
                cand.update(run=shifted_run, source_run=record['run'], run_dir=str(rdir.resolve()),
                            hinted=spec['hinted'], run_label=spec['label'], repo_sha=sha)
            by_case_runs[cid].append(cand)

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
        if runs is not None:
            case_entries[cid]['modes'] = [t.get('mode') for t in case.get('turns', []) if t.get('mode')]

    result = {
        'cases_path': str(cases_path.resolve()),
        'run_dirs': run_dir_strings,
        'repo_sha': repo_shas,
        'cases': case_entries,
    }
    if runs is not None:
        result['runs'] = specs
    return result


def load_mapped_trace_calls(run_dir: Path, run_offset: int = 0):
    """Ánh xạ vết dùng chung cho chấm/chọn, CJK và dựng SFT; không sửa vết nguồn."""
    result = defaultdict(list)
    for path in sorted(run_dir.glob('shard-*.jsonl')):
        for call in _read_jsonl(path):
            source_run = call.get('run')
            run = source_run + run_offset if run_offset else source_run
            result[(call.get('case_id'), run, call.get('turn'))].append(call)
    return result


def _score_calls(scores: dict[str, Any], model: str):
    """Khóa vết theo run toàn cục; vết nguồn vẫn giữ số run gốc."""
    if 'runs' not in scores:
        return load_mapped_trace_calls(Path(scores['run_dirs'][model]))
    result = {}
    for spec in scores['runs']:
        if spec['model'] != model:
            continue
        calls = load_mapped_trace_calls(Path(spec['dir']), spec['run_offset'])
        for key, values in calls.items():
            if key in result:
                raise ValueError(f'Vết run trùng: {key}')
            result[key] = values
    return result


def _extract_turn_steps(
    turn_calls: list[dict[str, Any]],
    max_tool_chars: int = DEFAULT_MAX_TOOL_CHARS,
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
                'content': raw_res[:max_tool_chars],
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


def _build_turn_payload(
    case: dict[str, Any],
    cid: str,
    run_no: int,
    turn_no: int,
    calls: dict[tuple[Any, Any, Any], list[dict[str, Any]]],
    turns_text: list[str],
    max_tool_chars: int,
) -> dict[str, Any]:
    """Dựng ngữ cảnh, các bước và câu trả lời đã ẩn tên model cho một lượt."""
    turn_calls = calls.get((cid, run_no, turn_no), [])
    steps, trace_answer = _extract_turn_steps(turn_calls, max_tool_chars)
    fallback_answer = turns_text[turn_no - 1] if turn_no - 1 < len(turns_text) else ''
    answer = trace_answer if trace_answer else fallback_answer
    masked_context = _mask_model_names(_turn_context(case, turn_no))
    masked_steps = _mask_model_names(steps)
    masked_answer = _mask_model_names(answer)
    full_text = _mask_model_names(_format_item_text(masked_steps, masked_answer))
    return {
        'context': masked_context,
        'steps': masked_steps,
        'answer': masked_answer,
        'text': full_text,
    }


def _extract_candidate_tool_seq(
    case: dict[str, Any],
    cand: dict[str, Any],
    calls: dict[tuple[Any, Any, Any], list[dict[str, Any]]],
) -> list[list[str]]:
    """Chuỗi tên tool theo đúng thứ tự từng lượt (dùng xác định cặp khác chuỗi tool ở Tier S)."""
    cid = cand['case_id']
    run_no = int(cand['run'])
    rail_turns = set(cand.get('rail_turns') or [])
    seq: list[list[str]] = []
    for turn_no in range(1, len(case.get('turns') or []) + 1):
        if turn_no in rail_turns:
            seq.append([])
            continue
        steps, _ = _extract_turn_steps(calls.get((cid, run_no, turn_no), []), DEFAULT_MAX_TOOL_CHARS)
        seq.append([tc['name'] for st in steps for tc in (st.get('tool_calls') or [])])
    return seq


def _merge_adjudicated_files(
    adjudicated_paths: list[Path],
) -> tuple[
    dict[tuple[str, str, int], dict[str, Any]],
    dict[tuple[str, str, int], bool],
    dict[tuple[str, str], dict[str, Any]],
    list[tuple[str, str]],
    list[dict[str, Any]],
]:
    """Gộp nhiều tệp adjudicated theo thứ tự: ứng viên, nhãn Tier S, cặp S; tệp sau ghi đè tệp trước."""
    adjudicated_by_cand: dict[tuple[str, str, int], dict[str, Any]] = {}
    tier_s_by_cand: dict[tuple[str, str, int], bool] = {}
    s_pairs_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    all_pairs: list[tuple[str, str]] = []
    seen_round_items: set[tuple[Any, str]] = set()
    round_agreements: list[dict[str, Any]] = []

    for adj_path in adjudicated_paths:
        adj = json.loads(adj_path.read_text(encoding='utf-8'))
        rnd = adj.get('round')
        jdir = adj.get('judge_dir', str(adj_path))
        if 'agreement_ab' in adj:
            round_agreements.append({
                'round': rnd,
                **(adj.get('agreement_ab') or {}),
            })
        for iid, v in (adj.get('verdicts') or {}).items():
            if 'a' in v and 'b' in v:
                key_item = (jdir, iid)
                if key_item not in seen_round_items:
                    seen_round_items.add(key_item)
                    all_pairs.append((v['a'], v['b']))
        for cand in (adj.get('candidates') or {}).values():
            ckey = (cand['case_id'], cand['model'], int(cand['run']))
            adjudicated_by_cand[ckey] = cand
            if cand.get('tier') == 'S':
                tier_s_by_cand[ckey] = True
            elif 'tier_s' in cand:
                tier_s_by_cand[ckey] = bool(cand['tier_s'])
        for ckey_str, s_val in (adj.get('tier_s') or {}).items():
            if isinstance(s_val, dict):
                ckey = (s_val['case_id'], s_val['model'], int(s_val['run']))
                tier_s_by_cand[ckey] = bool(s_val.get('tier_s', s_val.get('is_s', False)))
            else:
                parts = str(ckey_str).split('#')
                if len(parts) == 3:
                    tier_s_by_cand[(parts[0], parts[1], int(parts[2]))] = bool(s_val)
        for p_val in (adj.get('s_pairs') or {}).values():
            if isinstance(p_val, dict) and p_val.get('primary') and p_val.get('other'):
                pkey = tuple(sorted((str(p_val['primary']), str(p_val['other']))))
                s_pairs_by_key[pkey] = p_val

    return adjudicated_by_cand, tier_s_by_cand, s_pairs_by_key, all_pairs, round_agreements


def export_judge_round(
    scores_path: Path,
    out_dir: Path,
    *,
    round_no: int = 1,
    after_paths: list[Path] | None = None,
    seed: int = DEFAULT_SEED,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_tool_chars: int = DEFAULT_MAX_TOOL_CHARS,
    exclude_templates: set[str] | list[str] | None = None,
) -> dict[str, Any]:
    # Giữ mặc định 3.000 để tái lập vòng 1; owner có thể chọn 8.000 ở vòng 2 / trọng tài.
    rubric_text(max_tool_chars)  # kiểm tham số trước khi ghi bất kỳ tệp nào
    if (out_dir / 'map.json').exists() or (out_dir / 'packets').exists():
        raise FileExistsError(f'{out_dir} đã có gói chấm; mỗi thư mục chấm chỉ xuất một lần')
    if round_no > 1 and not after_paths:
        raise ValueError(f'--after is required when --round {round_no} > 1')

    exclude_set = _parse_exclude_templates(exclude_templates)
    scores_data = json.loads(scores_path.read_text(encoding='utf-8'))
    cases_list = _read_jsonl(Path(scores_data['cases_path']))
    cases_by_id = {c['id']: c for c in cases_list}

    selected_candidates: list[dict[str, Any]] = []
    cand_cls: dict[str, str] = {}

    if round_no == 1:
        # Giữ nguyên tuyệt đối hành vi vòng 1 để trùng từng byte với bản đã chấm.
        for cid, entry in scores_data['cases'].items():
            if exclude_set and entry.get('template', '') in exclude_set:
                continue
            for cand in entry.get('candidates') or []:
                selected_candidates.append(cand)
                break
    else:
        # W6.7.2 mục A: vòng 2 theo luật Qwen trước, chỉ lấy A_code, ba lớp ứng viên: q_next / ds_pair / q_second.
        adjudicated_by_cand, _, _, _, _ = _merge_adjudicated_files(after_paths or [])
        already_judged = set(adjudicated_by_cand.keys())

        for cid, entry in scores_data['cases'].items():
            if exclude_set and entry.get('template', '') in exclude_set:
                continue
            a_cands = [c for c in (entry.get('candidates') or []) if c.get('code_tier') == 'A_code']
            tier_a_cands = [
                c for c in a_cands
                if adjudicated_by_cand.get((cid, c['model'], int(c['run'])), {}).get('tier') in ('A', 'S')
            ]
            # a_cands đã xếp Qwen A_code trước DeepSeek A_code rồi theo rank → phần tử đầu là Tier A tốt nhất.
            best_tier_a = tier_a_cands[0] if tier_a_cands else None
            unjudged_qwen = [
                c for c in a_cands
                if c['model'] == 'qwen' and (cid, c['model'], int(c['run'])) not in already_judged
            ]
            unjudged_ds = [
                c for c in a_cands
                if c['model'] == 'deepseek' and (cid, c['model'], int(c['run'])) not in already_judged
            ]

            picked: list[tuple[str, dict[str, Any]]] = []
            if best_tier_a is None:
                # Lớp q_next: ca chưa có Tier A -> A_code Qwen chưa chấm, rank tốt nhất; không có thì không xuất.
                if unjudged_qwen:
                    picked.append(('q_next', unjudged_qwen[0]))
            elif best_tier_a['model'] == 'qwen':
                # Lớp ds_pair: Tier A tốt nhất của ca là Qwen -> A_code DeepSeek chưa chấm, rank tốt nhất.
                if unjudged_ds:
                    picked.append(('ds_pair', unjudged_ds[0]))
                # Lớp q_second: bộ thuộc HARD_SUITES, Tier A là Qwen, không có A_code DeepSeek chưa chấm
                # -> A_code Qwen chưa chấm có độ giống với mẫu Tier A < 0,85, rank tốt nhất.
                elif entry.get('suite') in HARD_SUITES:
                    for qc in unjudged_qwen:
                        if candidate_text_similarity(qc, best_tier_a) < QWEN_SECOND_MAX_SIM:
                            picked.append(('q_second', qc))
                            break

            for cls_name, cand in picked:
                ckey = f"{cid}#{cand['model']}#{int(cand['run'])}"
                cand_cls[ckey] = cls_name
                selected_candidates.append(cand)

    # Load traces for needed models only
    calls_by_model: dict[str, dict[tuple[Any, Any, Any], list[dict[str, Any]]]] = {}
    for model in {c['model'] for c in selected_candidates}:
        calls = _score_calls(scores_data, model)
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
            payload = _build_turn_payload(
                case, cid, run_no, turn_no, calls, cand.get('turns_text') or [], max_tool_chars
            )
            items.append({
                'case_id': cid,
                'model': model,
                'run': run_no,
                'turn': turn_no,
                'code_tier': cand['code_tier'],
                'rank': cand['rank'],
                'candidate_key': cand_key,
                'context': payload['context'],
                'steps': payload['steps'],
                'answer': payload['answer'],
                'text': payload['text'],
            })
            cand_item_indices.append(len(items) - 1)

        cand_entry: dict[str, Any] = {
            'case_id': cid,
            'model': model,
            'run': run_no,
            'code_tier': cand['code_tier'],
            'rank': cand['rank'],
            'item_indices': cand_item_indices,
        }
        if cand_key in cand_cls:
            cand_entry['cls'] = cand_cls[cand_key]
        cand_map[cand_key] = cand_entry

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

    mapping: dict[str, Any] = {
        'round': round_no,
        'scores_path': str(scores_path.resolve()),
        'seed': seed,
        'batch_size': batch_size,
        'max_tool_chars': max_tool_chars,
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
                **({'cls': val['cls']} if 'cls' in val else {}),
                'item_ids': [items[idx]['item_id'] for idx in val['item_indices']],
            }
            for key, val in cand_map.items()
        },
    }
    if round_no > 1:
        mapping['after'] = [str(p.resolve()) for p in (after_paths or [])]
    if exclude_set:
        mapping['exclude_templates'] = sorted(exclude_set)
    _write_json(out_dir / 'map.json', mapping)

    summary: dict[str, Any] = {
        'round': round_no,
        'candidates': len(selected_candidates),
        'items': len(items),
        'batches': len(batches),
    }
    if round_no > 1:
        summary['by_class'] = dict(sorted(Counter(cand_cls.values()).items()))
    return summary


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


def _read_single_judge_verdicts(
    judge_dir: Path,
    mapping: dict[str, Any],
    *,
    kind: str,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Đọc và kiểm tra phiếu một giám khảo trong verdicts/batch-NN.jsonl (trọng tài hoặc Tier S)."""
    folder = judge_dir / 'verdicts'
    errors: list[str] = []
    verdicts: dict[str, dict[str, Any]] = {}

    for batch, expected_ids in (mapping.get('batches') or {}).items():
        path = folder / f'{batch}.jsonl'
        if not path.exists():
            errors.append(f'thiếu phiếu {batch}.jsonl')
            continue
        expected_set = set(expected_ids)
        seen: set[str] = set()
        for lineno, raw_line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith('```'):
                errors.append(f'{batch} dòng {lineno}: có dòng ``` — xóa trước khi nhập')
                continue
            try:
                row = json.loads(line)
            except ValueError:
                errors.append(f'{batch} dòng {lineno}: JSON hỏng')
                continue
            if not isinstance(row, dict):
                errors.append(f'{batch} dòng {lineno}: dòng phải là JSON object')
                continue
            iid = row.get('item_id')
            if iid not in expected_set:
                errors.append(f'{batch} dòng {lineno}: item_id lạ {iid!r}')
                continue
            if iid in seen:
                errors.append(f'{batch}: item_id trùng {iid}')
                continue

            if kind == 'arbiter':
                if row.get('verdict') not in eval_regrade.VERDICTS:
                    errors.append(f'{batch} dòng {lineno}: verdict không hợp lệ {row.get("verdict")!r}')
                    continue
            elif kind == 'tier_s':
                slot_err = False
                for slot in ('mau_1', 'mau_2'):
                    sobj = row.get(slot)
                    if not isinstance(sobj, dict) or not isinstance(sobj.get('S'), bool):
                        errors.append(f'{batch} dòng {lineno}: {slot} thiếu trường boolean S')
                        slot_err = True
                    elif 'bang_chung' in sobj and not isinstance(sobj.get('bang_chung'), dict):
                        errors.append(f'{batch} dòng {lineno}: {slot}.bang_chung phải là object')
                        slot_err = True
                if row.get('tot_hon') not in TIER_S_TOT_HON:
                    errors.append(f'{batch} dòng {lineno}: tot_hon không hợp lệ {row.get("tot_hon")!r}')
                    slot_err = True
                if row.get('khac_biet') not in TIER_S_KHAC_BIET:
                    errors.append(f'{batch} dòng {lineno}: khac_biet không hợp lệ {row.get("khac_biet")!r}')
                    slot_err = True
                if slot_err:
                    continue
            else:
                raise ValueError(f'Unknown single-judge kind: {kind!r}')

            seen.add(iid)
            verdicts[iid] = row

        missing = expected_set - seen
        if missing:
            errors.append(f'{batch}: thiếu {len(missing)} mục ({sorted(missing)[:5]})')

    return verdicts, errors


def export_arbiter(
    base_adjudicated_path: Path,
    scores_path: Path,
    out_dir: Path,
    *,
    base_map_path: Path | None = None,
    seed: int = DEFAULT_SEED,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_tool_chars: int = DEFAULT_MAX_TOOL_CHARS,
) -> dict[str, Any]:
    """W6.7.2 mục B: xuất gói trọng tài cho ứng viên Tier B (A_code, không có mục nào khong_dat)."""
    rubric_text(max_tool_chars)
    if (out_dir / 'map.json').exists() or (out_dir / 'packets').exists():
        raise FileExistsError(f'{out_dir} đã có gói chấm; mỗi thư mục chấm chỉ xuất một lần')

    base = json.loads(base_adjudicated_path.read_text(encoding='utf-8'))
    resolved_base_map = base_map_path or (Path(base['judge_dir']) / 'map.json')
    if not resolved_base_map.is_file():
        raise FileNotFoundError(f'Không tìm thấy map.json gốc tại {resolved_base_map}')
    base_map = json.loads(resolved_base_map.read_text(encoding='utf-8'))
    base_max_chars = int(base_map.get('max_tool_chars') or DEFAULT_MAX_TOOL_CHARS)

    scores_data = json.loads(scores_path.read_text(encoding='utf-8'))
    cases_by_id = {c['id']: c for c in _read_jsonl(Path(scores_data['cases_path']))}
    V = base.get('verdicts') or {}

    cands = {
        k: c for k, c in (base.get('candidates') or {}).items()
        if c.get('tier') == 'B'
        and c.get('code_tier') == 'A_code'
        and not any(V[i]['any_khong_dat'] for i in c.get('item_ids') or [])
    }
    sent = [i for c in cands.values() for i in c.get('item_ids') or [] if not V[i]['both_dat']]
    if len(set(sent)) != len(sent):
        raise ValueError('Trùng item_id trong danh sách mục gửi trọng tài')

    turns_text_by_run: dict[tuple[str, str, int], list[str]] = {}
    for cid, entry in (scores_data.get('cases') or {}).items():
        for bucket in (entry.get('candidates') or [], entry.get('rejected') or []):
            for x in bucket:
                turns_text_by_run[(cid, x['model'], int(x['run']))] = list(x.get('turns_text') or [])

    needed_models = {base_map['items'][iid]['model'] for iid in sent}
    calls_by_model: dict[str, dict[tuple[Any, Any, Any], list[dict[str, Any]]]] = {}
    for model in needed_models:
        calls = _score_calls(scores_data, model)
        calls_by_model[model] = calls

    # Chặn an toàn: dựng lại ở số ký tự gốc phải trùng text trong map.json gốc, lệch thì dừng trước khi ghi tệp.
    built_items: dict[str, dict[str, Any]] = {}
    longer = 0
    for iid in sent:
        it = base_map['items'][iid]
        cid, model, run_no, turn_no = it['case_id'], it['model'], int(it['run']), int(it['turn'])
        tt = turns_text_by_run.get((cid, model, run_no), [])
        old_payload = _build_turn_payload(
            cases_by_id[cid], cid, run_no, turn_no, calls_by_model[model], tt, base_max_chars
        )
        if old_payload['text'] != it['text']:
            raise ValueError(
                f'{iid}: dựng lại ở {base_max_chars} ký tự không khớp text trong map.json gốc'
            )
        new_payload = _build_turn_payload(
            cases_by_id[cid], cid, run_no, turn_no, calls_by_model[model], tt, max_tool_chars
        )
        if new_payload['text'] != old_payload['text']:
            longer += 1
        built_items[iid] = new_payload

    order = list(sent)
    random.Random(seed).shuffle(order)
    batches = [order[i:i + batch_size] for i in range(0, len(order), batch_size)]

    packets_dir = out_dir / 'packets'
    packets_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'verdicts').mkdir(parents=True, exist_ok=True)
    for batch_num, batch in enumerate(batches, 1):
        lines = [
            json.dumps({
                'item_id': iid,
                'kind': 'sft_tier',
                'context': built_items[iid]['context'],
                'steps': built_items[iid]['steps'],
                'answer': built_items[iid]['answer'],
                'requirement': REQUIREMENT_TEXT,
            }, ensure_ascii=False)
            for iid in batch
        ]
        (packets_dir / f'batch-{batch_num:02d}.jsonl').write_text(
            '\n'.join(lines) + '\n', encoding='utf-8'
        )

    mapping = {
        'round': f"arbiter_r{base.get('round', 1)}",
        'arbiter': True,
        'base_adjudicated': str(base_adjudicated_path.resolve()),
        'base_map': str(resolved_base_map.resolve()),
        'scores_path': str(scores_path.resolve()),
        'max_tool_chars': max_tool_chars,
        'base_max_tool_chars': base_max_chars,
        'seed': seed,
        'batch_size': batch_size,
        'batches': {f'batch-{n:02d}': b for n, b in enumerate(batches, 1)},
        'items': {
            iid: {
                'case_id': base_map['items'][iid]['case_id'],
                'model': base_map['items'][iid]['model'],
                'run': base_map['items'][iid]['run'],
                'turn': base_map['items'][iid]['turn'],
                'code_tier': base_map['items'][iid].get('code_tier', 'A_code'),
                'rank': base_map['items'][iid].get('rank'),
                'candidate_key': base_map['items'][iid]['candidate_key'],
                'pair_r1': [V[iid]['a'], V[iid]['b']],
                'text': built_items[iid]['text'],
            }
            for iid in sent
        },
        'candidates': {
            k: {
                'case_id': c['case_id'],
                'model': c['model'],
                'run': c['run'],
                'code_tier': c['code_tier'],
                'rank': c['rank'],
                'item_ids': list(c['item_ids']),
            }
            for k, c in cands.items()
        },
    }
    _write_json(out_dir / 'map.json', mapping)
    return {
        'round': mapping['round'],
        'candidates': len(cands),
        'items': len(sent),
        'batches': len(batches),
        'longer_than_base': longer,
    }


def import_arbiter(
    judge_dir: Path,
    base_adjudicated_path: Path,
    out_path: Path,
    *,
    strict_kckc: bool = False,
) -> tuple[int, dict[str, Any]]:
    """W6.7.2 mục B: nhập phiếu trọng tài vào adjudicated gốc và xếp lại Tier A/B/C."""
    mapping = json.loads((judge_dir / 'map.json').read_text(encoding='utf-8'))
    rows, errors = _read_single_judge_verdicts(judge_dir, mapping, kind='arbiter')
    if errors:
        return 2, {'errors': errors}

    base = json.loads(base_adjudicated_path.read_text(encoding='utf-8'))
    out = copy.deepcopy(base)
    V = out['verdicts']
    arb_counts: Counter[tuple[str, str]] = Counter()
    downgraded: Counter[str] = Counter()

    for iid, it in (mapping.get('items') or {}).items():
        if iid not in V:
            return 2, {'errors': [f'item_id {iid} không có trong base adjudicated']}
        raw = rows[iid]['verdict']
        eff = effective_tier_verdict(rows[iid], {'text': it['text']})
        if raw in ('dat', 'khong_dat') and eff != raw:
            downgraded[raw] += 1
        pair_r1 = list(it.get('pair_r1') or [V[iid].get('a'), V[iid].get('b')])
        pair_label = '/'.join(str(x) for x in pair_r1)
        arb_counts[(pair_label, eff)] += 1
        V[iid].update(
            arbiter_raw=raw,
            arbiter=eff,
            arbiter_reason=str(rows[iid].get('reason') or ''),
        )
        if eff == 'khong_dat':
            V[iid]['any_khong_dat'] = True
            V[iid]['both_dat'] = False
        elif eff == 'dat' and not (strict_kckc and pair_r1 == ['khong_chac', 'khong_chac']):
            V[iid]['both_dat'] = True

    for c in (out.get('candidates') or {}).values():
        tv = [V[i] for i in c.get('item_ids') or []]
        if any(t['any_khong_dat'] for t in tv):
            c['tier'] = 'C'
        elif c.get('code_tier') == 'A_code' and tv and all(t['both_dat'] for t in tv):
            c['tier'] = 'A'
        else:
            c['tier'] = 'B'

    after_counts = Counter(c['tier'] for c in (out.get('candidates') or {}).values())
    out['tier_counts'] = dict(after_counts)
    out['arbiter'] = {
        'judge_dir': str(judge_dir.resolve()),
        'base_adjudicated': str(base_adjudicated_path.resolve()),
        'strict_kckc': bool(strict_kckc),
        'rule': 'strict_kckc' if strict_kckc else 'handoff',
        'counts': {f'{p}->{e}': n for (p, e), n in sorted(arb_counts.items())},
        'downgraded_quotes': dict(downgraded),
    }
    _write_json(out_path, out)
    return 0, out


def export_tier_s(
    scores_path: Path,
    adjudicated_paths: list[Path],
    out_dir: Path,
    *,
    seed: int = DEFAULT_SEED,
    batch_size: int = DEFAULT_TIER_S_BATCH_SIZE,
    max_tool_chars: int = DEFAULT_MAX_TOOL_CHARS,
    exclude_templates: set[str] | list[str] | None = None,
) -> dict[str, Any]:
    """W6.7.2 mục C: xuất gói chấm cặp Tier S cho mọi ca có >= 2 ứng viên Tier A."""
    tier_s_rubric_text(max_tool_chars)
    if (out_dir / 'map.json').exists() or (out_dir / 'packets').exists():
        raise FileExistsError(f'{out_dir} đã có gói chấm; mỗi thư mục chấm chỉ xuất một lần')

    exclude_set = _parse_exclude_templates(exclude_templates)
    scores_data = json.loads(scores_path.read_text(encoding='utf-8'))
    cases_by_id = {c['id']: c for c in _read_jsonl(Path(scores_data['cases_path']))}
    adjudicated_by_cand, _, _, _, _ = _merge_adjudicated_files(adjudicated_paths)

    pair_specs: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for cid, entry in (scores_data.get('cases') or {}).items():
        if exclude_set and entry.get('template', '') in exclude_set:
            continue
        tier_a_cands = [
            c for c in (entry.get('candidates') or [])
            if adjudicated_by_cand.get((cid, c['model'], int(c['run'])), {}).get('tier') in ('A', 'S')
        ]
        if len(tier_a_cands) < 2:
            continue
        # Mẫu chính = Qwen tốt nhất nếu có, ngược lại DeepSeek tốt nhất (candidates đã xếp Qwen trước rồi rank).
        primary = tier_a_cands[0]
        for other in tier_a_cands[1:]:
            pair_specs.append((cid, primary, other))

    needed_models = {m for _, p, o in pair_specs for m in (p['model'], o['model'])}
    calls_by_model: dict[str, dict[tuple[Any, Any, Any], list[dict[str, Any]]]] = {}
    for model in needed_models:
        calls = _score_calls(scores_data, model)
        calls_by_model[model] = calls

    rng = random.Random(seed)
    items: list[dict[str, Any]] = []
    pair_map: dict[str, dict[str, Any]] = {}

    for cid, primary, other in pair_specs:
        case = cases_by_id[cid]
        p_key = f"{cid}#{primary['model']}#{int(primary['run'])}"
        o_key = f"{cid}#{other['model']}#{int(other['run'])}"
        pair_key = f'{p_key}__{o_key}'
        seq_p = _extract_candidate_tool_seq(case, primary, calls_by_model[primary['model']])
        seq_o = _extract_candidate_tool_seq(case, other, calls_by_model[other['model']])
        rail_both = set(primary.get('rail_turns') or []) & set(other.get('rail_turns') or [])

        pair_item_indices: list[int] = []
        for turn_no in range(1, len(case.get('turns') or []) + 1):
            if turn_no in rail_both:
                continue
            p_pay = _build_turn_payload(
                case, cid, int(primary['run']), turn_no,
                calls_by_model[primary['model']], primary.get('turns_text') or [], max_tool_chars,
            )
            o_pay = _build_turn_payload(
                case, cid, int(other['run']), turn_no,
                calls_by_model[other['model']], other.get('turns_text') or [], max_tool_chars,
            )
            swapped = bool(rng.getrandbits(1))
            if not swapped:
                m1_cand, m1_pay, m1_key = primary, p_pay, p_key
                m2_cand, m2_pay, m2_key = other, o_pay, o_key
            else:
                m1_cand, m1_pay, m1_key = other, o_pay, o_key
                m2_cand, m2_pay, m2_key = primary, p_pay, p_key

            items.append({
                'case_id': cid,
                'turn': turn_no,
                'pair_key': pair_key,
                'context': p_pay['context'],
                'mau_1': {'steps': m1_pay['steps'], 'answer': m1_pay['answer']},
                'mau_2': {'steps': m2_pay['steps'], 'answer': m2_pay['answer']},
                'mau_1_meta': {
                    'model': m1_cand['model'],
                    'run': int(m1_cand['run']),
                    'candidate_key': m1_key,
                    'is_primary': m1_key == p_key,
                    'text': m1_pay['text'],
                },
                'mau_2_meta': {
                    'model': m2_cand['model'],
                    'run': int(m2_cand['run']),
                    'candidate_key': m2_key,
                    'is_primary': m2_key == p_key,
                    'text': m2_pay['text'],
                },
            })
            pair_item_indices.append(len(items) - 1)

        pair_map[pair_key] = {
            'case_id': cid,
            'primary': p_key,
            'other': o_key,
            'tool_seq_primary': seq_p,
            'tool_seq_other': seq_o,
            'tool_seq_diff': seq_p != seq_o,
            'item_indices': pair_item_indices,
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
    (out_dir / 'verdicts').mkdir(parents=True, exist_ok=True)
    for batch_num, batch in enumerate(batches, 1):
        lines = [
            json.dumps({
                'item_id': items[idx]['item_id'],
                'kind': 'sft_tier_s_cap',
                'context': items[idx]['context'],
                'mau_1': items[idx]['mau_1'],
                'mau_2': items[idx]['mau_2'],
                'requirement': TIER_S_REQUIREMENT_TEXT,
            }, ensure_ascii=False)
            for idx in batch
        ]
        (packets_dir / f'batch-{batch_num:02d}.jsonl').write_text(
            '\n'.join(lines) + '\n', encoding='utf-8'
        )

    mapping: dict[str, Any] = {
        'kind': 'sft_tier_s_cap',
        'scores_path': str(scores_path.resolve()),
        'adjudicated_paths': [str(p.resolve()) for p in adjudicated_paths],
        'seed': seed,
        'batch_size': batch_size,
        'max_tool_chars': max_tool_chars,
        'batches': {
            f'batch-{n:02d}': [items[i]['item_id'] for i in b]
            for n, b in enumerate(batches, 1)
        },
        'items': {
            it['item_id']: {
                'case_id': it['case_id'],
                'turn': it['turn'],
                'pair_key': it['pair_key'],
                'mau_1': it['mau_1_meta'],
                'mau_2': it['mau_2_meta'],
            }
            for it in items
        },
        'pairs': {
            pk: {
                'case_id': val['case_id'],
                'primary': val['primary'],
                'other': val['other'],
                'tool_seq_primary': val['tool_seq_primary'],
                'tool_seq_other': val['tool_seq_other'],
                'tool_seq_diff': val['tool_seq_diff'],
                'item_ids': [items[idx]['item_id'] for idx in val['item_indices']],
            }
            for pk, val in pair_map.items()
        },
    }
    if exclude_set:
        mapping['exclude_templates'] = sorted(exclude_set)
    _write_json(out_dir / 'map.json', mapping)
    return {
        'pairs': len(pair_map),
        'items': len(items),
        'batches': len(batches),
    }


def _verify_tier_s_slot(slot_verdict: dict[str, Any], slot_text: str) -> tuple[bool, list[str]]:
    """Kiểm đủ 7 trích dẫn (>= MIN_QUOTE theo eval_regrade.v2) trong đúng văn bản mẫu đó."""
    if not slot_verdict.get('S'):
        return False, []
    evidence = slot_verdict.get('bang_chung')
    if not isinstance(evidence, dict):
        return False, list(TIER_S_CRITERIA)
    norm_text = eval_regrade.v2(slot_text)
    bad: list[str] = []
    for crit in TIER_S_CRITERIA:
        raw_q = evidence.get(crit)
        if raw_q is None and int(crit) in evidence:
            raw_q = evidence[int(crit)]
        if not isinstance(raw_q, str):
            bad.append(crit)
            continue
        norm_q = eval_regrade.v2(raw_q)
        if len(norm_q) < eval_regrade.MIN_QUOTE or norm_q not in norm_text:
            bad.append(crit)
    return (len(bad) == 0), bad


def import_tier_s(
    judge_dir: Path,
    adjudicated_paths: list[Path],
    out_path: Path,
) -> tuple[int, dict[str, Any]]:
    """W6.7.2 mục C: nhập phiếu chấm cặp Tier S, kiểm 7 trích dẫn/mẫu, gắn nhãn S và loại khác biệt."""
    mapping = json.loads((judge_dir / 'map.json').read_text(encoding='utf-8'))
    rows, errors = _read_single_judge_verdicts(judge_dir, mapping, kind='tier_s')
    if errors:
        return 2, {'errors': errors}

    # Gộp các tệp adjudicated đầu vào (nếu truyền 1 tệp thì giữ nguyên mọi trường của tệp đó).
    base_adjs = [json.loads(p.read_text(encoding='utf-8')) for p in adjudicated_paths]
    out = copy.deepcopy(base_adjs[0]) if len(base_adjs) == 1 else {
        'round': 'tier_s_merged',
        'sources': [str(p.resolve()) for p in adjudicated_paths],
        'candidates': {},
        'verdicts': {},
    }
    if len(base_adjs) > 1:
        for adj in base_adjs:
            out['candidates'].update(copy.deepcopy(adj.get('candidates') or {}))
            out['verdicts'].update(copy.deepcopy(adj.get('verdicts') or {}))

    downgraded_s: list[dict[str, Any]] = []
    cand_eval_turns: dict[str, list[bool]] = defaultdict(list)
    cand_meta: dict[str, dict[str, Any]] = {}
    item_verdicts_out: dict[str, dict[str, Any]] = {}

    for iid, it in (mapping.get('items') or {}).items():
        row = rows[iid]
        slot_res: dict[str, Any] = {}
        for slot in ('mau_1', 'mau_2'):
            meta = it[slot]
            ckey = meta['candidate_key']
            cand_meta[ckey] = {
                'case_id': it['case_id'],
                'model': meta['model'],
                'run': int(meta['run']),
            }
            s_raw = bool(row[slot]['S'])
            s_eff, bad_criteria = _verify_tier_s_slot(row[slot], meta['text'])
            if s_raw and not s_eff:
                downgraded_s.append({
                    'item_id': iid,
                    'slot': slot,
                    'candidate_key': ckey,
                    'turn': it['turn'],
                    'invalid_criteria': bad_criteria,
                })
            cand_eval_turns[ckey].append(s_eff)
            slot_res[slot] = {
                'candidate_key': ckey,
                'S_raw': s_raw,
                'S': s_eff,
                'invalid_criteria': bad_criteria,
                'truot': list(row[slot].get('truot') or []),
            }
        tot_hon_raw = row['tot_hon']
        tot_hon_cand = (
            it[tot_hon_raw]['candidate_key']
            if tot_hon_raw in ('mau_1', 'mau_2')
            else 'ngang'
        )
        item_verdicts_out[iid] = {
            'case_id': it['case_id'],
            'turn': it['turn'],
            'pair_key': it['pair_key'],
            'mau_1': slot_res['mau_1'],
            'mau_2': slot_res['mau_2'],
            'tot_hon_raw': tot_hon_raw,
            'tot_hon': tot_hon_cand,
            'khac_biet': row['khac_biet'],
            'reason': str(row.get('reason') or ''),
        }

    # Ứng viên đạt Tier S khi và chỉ khi MỌI lượt đều đạt S (sau kiểm trích dẫn).
    tier_s_out: dict[str, dict[str, Any]] = {}
    for ckey, flags in sorted(cand_eval_turns.items()):
        is_s = bool(flags) and all(flags)
        meta = cand_meta[ckey]
        tier_s_out[ckey] = {
            'case_id': meta['case_id'],
            'model': meta['model'],
            'run': meta['run'],
            'tier_s': is_s,
            'turns_evaluated': len(flags),
            'turns_s': sum(1 for f in flags if f),
        }
        if ckey in (out.get('candidates') or {}):
            out['candidates'][ckey]['tier_s'] = is_s

    # Cặp khác nhau khi chuỗi tên tool (mọi lượt, theo thứ tự) khác nhau, HOẶC có lượt khac_biet ∈ {cach_xu_ly, thong_tin}.
    s_pairs_out: dict[str, dict[str, Any]] = {}
    for pk, pair in (mapping.get('pairs') or {}).items():
        iids = pair.get('item_ids') or []
        kb_turns = [item_verdicts_out[i]['khac_biet'] for i in iids]
        tot_hon_turns = [item_verdicts_out[i]['tot_hon'] for i in iids]
        tool_diff = bool(pair.get('tool_seq_diff'))
        diff_kinds = sorted(
            ({'tool_seq'} if tool_diff else set())
            | {kb for kb in kb_turns if kb in ('cach_xu_ly', 'thong_tin')}
        )
        different = bool(diff_kinds)
        s_pairs_out[pk] = {
            'case_id': pair['case_id'],
            'primary': pair['primary'],
            'other': pair['other'],
            'tool_seq_diff': tool_diff,
            'khac_biet_turns': kb_turns,
            'diff_kinds': diff_kinds,
            'different': different,
            'tot_hon_turns': tot_hon_turns,
            'item_ids': list(iids),
        }

    out['tier_s'] = tier_s_out
    out['s_pairs'] = s_pairs_out
    out['tier_s_verdicts'] = item_verdicts_out
    out['downgraded_s'] = downgraded_s
    out['tier_s_summary'] = {
        'judge_dir': str(judge_dir.resolve()),
        'candidates_evaluated': len(tier_s_out),
        'candidates_s': sum(1 for v in tier_s_out.values() if v['tier_s']),
        'pairs_total': len(s_pairs_out),
        'pairs_different': sum(1 for v in s_pairs_out.values() if v['different']),
        'downgraded_s_count': len(downgraded_s),
    }
    _write_json(out_path, out)
    return 0, out


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


def _make_selection_entry(
    case_entry: dict[str, Any],
    cand: dict[str, Any],
    scores_data: dict[str, Any],
    *,
    tier: str,
    role: str,
    rule: int | None,
    used_fallback: bool = False,
) -> dict[str, Any]:
    model = cand['model']
    result = {
        'case_id': case_entry['case_id'],
        'template': case_entry.get('template', ''),
        'suite': case_entry.get('suite', ''),
        'style': case_entry.get('style', ''),
        'actor': case_entry.get('actor', 'customer'),
        'model': model,
        'source_model': model,
        'run': int(cand['run']),
        'role': role,
        'tier': tier,
        'rule': rule,
        'code_tier': cand['code_tier'],
        'allow_b_fallback': used_fallback,
        'run_dir': cand.get('run_dir') or scores_data['run_dirs'][model],
        'repo_sha': cand.get('repo_sha') or (scores_data.get('repo_sha') or {}).get(model),
        'turns_count': int(case_entry.get('turns_count') or cand.get('turns_count') or 1),
        'rail_turns': list(cand.get('rail_turns') or []),
        'tool_calls': cand['tool_calls'],
        'completion_tokens': cand['completion_tokens'],
        'answer_chars': cand['answer_chars'],
    }
    for key in ('hinted', 'run_label', 'source_run'):
        if key in cand:
            result[key] = cand[key]
    return result


def select_candidates(
    scores_path: Path,
    adjudicated_paths: list[Path],
    out_path: Path,
    *,
    allow_b: bool = False,
    max_per_case: int = 2,
    seed: int = DEFAULT_SEED,
    exclude_templates: set[str] | list[str] | None = None,
    suite_caps: dict[str, float] | None = None,
    mode_caps: dict[str, float] | None = None,
) -> dict[str, Any]:
    if max_per_case < 1:
        raise ValueError('--max-per-case phải lớn hơn hoặc bằng 1')

    exclude_set = _parse_exclude_templates(exclude_templates)
    scores_data = json.loads(scores_path.read_text(encoding='utf-8'))
    (
        adjudicated_by_cand,
        tier_s_by_cand,
        s_pairs_by_key,
        all_pairs,
        round_agreements,
    ) = _merge_adjudicated_files(adjudicated_paths)

    def _eff_tier(cid: str, cand: dict[str, Any]) -> str:
        return 'S' if tier_s_by_cand.get((cid, cand['model'], int(cand['run'])), False) else 'A'

    def _pair_info(cid: str, c1: dict[str, Any], c2: dict[str, Any]) -> dict[str, Any] | None:
        k1 = f"{cid}#{c1['model']}#{int(c1['run'])}"
        k2 = f"{cid}#{c2['model']}#{int(c2['run'])}"
        return s_pairs_by_key.get(tuple(sorted((k1, k2))))

    primaries_by_case: dict[str, dict[str, Any]] = {}
    seconds_by_case: dict[str, dict[str, Any]] = {}
    case_order: list[str] = []
    dropped: list[dict[str, Any]] = []

    for cid, case_entry in scores_data['cases'].items():
        if exclude_set and case_entry.get('template', '') in exclude_set:
            dropped.append({
                'case_id': cid,
                'template': case_entry.get('template', ''),
                'suite': case_entry.get('suite', ''),
                'reason': 'excluded_template',
                'detail': [case_entry.get('template', '')],
            })
            continue

        candidates = case_entry.get('candidates') or []
        tier_a_cands = [
            c for c in candidates
            if adjudicated_by_cand.get((cid, c['model'], int(c['run'])), {}).get('tier') in ('A', 'S')
        ]

        chosen: dict[str, Any] | None = None
        chosen_tier: str | None = None
        used_fallback = False

        if tier_a_cands:
            # Mẫu chính: Qwen tốt nhất (S trước A, rồi rank); không có Qwen Tier A -> DeepSeek tốt nhất (S trước A, rồi rank).
            tier_a_sorted = sorted(
                tier_a_cands,
                key=lambda c: ((
                    0 if _eff_tier(cid, c) == 'S' else 1,
                    bool(c.get('hinted', False)),
                    MODEL_PRIORITY.get(c['model'], 99), c['rank'],
                ) if any(x.get('hinted') for x in tier_a_cands) else (
                    MODEL_PRIORITY.get(c['model'], 99),
                    0 if _eff_tier(cid, c) == 'S' else 1,
                    bool(c.get('hinted', False)),
                    c['rank'],
                )),
            )
            chosen = tier_a_sorted[0]
            chosen_tier = _eff_tier(cid, chosen)
        elif allow_b:
            for cand in sorted(candidates, key=lambda c: (bool(c.get('hinted', False)), c['rank'])):
                adj_c = adjudicated_by_cand.get((cid, cand['model'], int(cand['run'])))
                if adj_c and adj_c.get('tier') == 'B':
                    chosen = cand
                    chosen_tier = 'B'
                    used_fallback = True
                    break

        if chosen is None or chosen_tier is None:
            reason, detail = _describe_drop_reason(case_entry, allow_b, adjudicated_by_cand)
            dropped.append({
                'case_id': cid,
                'template': case_entry.get('template', ''),
                'suite': case_entry.get('suite', ''),
                'reason': reason,
                'detail': detail,
            })
            continue

        case_order.append(cid)
        primaries_by_case[cid] = _make_selection_entry(
            case_entry, chosen, scores_data,
            tier=chosen_tier, role='primary', rule=None, used_fallback=used_fallback,
        )

        # Mẫu thứ hai (tối đa 1 mẫu/ca khi max_per_case >= 2 và mẫu chính đạt A/S).
        if max_per_case >= 2 and chosen_tier in ('A', 'S'):
            others = sorted(
                [c for c in tier_a_cands if c is not chosen],
                key=lambda c: (0 if _eff_tier(cid, c) == 'S' else 1, bool(c.get('hinted', False)), c['rank']),
            )
            suite = case_entry.get('suite', '')
            is_hard = suite in HARD_SUITES
            second_cand: dict[str, Any] | None = None
            second_rule: int | None = None

            if chosen['model'] == 'qwen':
                # Luật 1: DeepSeek S, khác mẫu chính (mục C) — mọi bộ.
                for c in others:
                    if c['model'] == 'deepseek' and _eff_tier(cid, c) == 'S':
                        pi = _pair_info(cid, chosen, c)
                        if pi is not None and pi.get('different'):
                            second_cand, second_rule = c, 1
                            break

                # Luật 2: Qwen S khác lượt mẫu chính, độ giống < 0,85 — mọi bộ.
                if second_cand is None:
                    for c in others:
                        if c['model'] == 'qwen' and _eff_tier(cid, c) == 'S':
                            pi = _pair_info(cid, chosen, c)
                            if pi is not None and not pi.get('different', True):
                                continue
                            if candidate_text_similarity(chosen, c) < QWEN_SECOND_MAX_SIM:
                                second_cand, second_rule = c, 2
                                break

                # Luật 3 (bộ khó): DeepSeek Tier A (quyết định 19/11: đã chấm cặp S mà different=False thì chặn, sang luật 4).
                if second_cand is None and is_hard:
                    for c in others:
                        if c['model'] == 'deepseek':
                            pi = _pair_info(cid, chosen, c)
                            if pi is not None and not pi.get('different'):
                                continue
                            second_cand, second_rule = c, 3
                            break

                # Luật 4 (bộ khó): Qwen Tier A khác lượt, độ giống < 0,85.
                if second_cand is None and is_hard:
                    for c in others:
                        if c['model'] == 'qwen':
                            pi = _pair_info(cid, chosen, c)
                            if pi is not None and not pi.get('different', True):
                                continue
                            if candidate_text_similarity(chosen, c) < QWEN_SECOND_MAX_SIM:
                                second_cand, second_rule = c, 4
                                break
            else:
                # Luật 5: Mẫu chính là DeepSeek -> chỉ nhận DeepSeek S khác mẫu chính.
                for c in others:
                    if c['model'] == 'deepseek' and _eff_tier(cid, c) == 'S':
                        pi = _pair_info(cid, chosen, c)
                        if pi is not None and pi.get('different'):
                            second_cand, second_rule = c, 5
                            break

            if second_cand is not None and second_rule is not None:
                seconds_by_case[cid] = _make_selection_entry(
                    case_entry, second_cand, scores_data,
                    tier=_eff_tier(cid, second_cand), role='second', rule=second_rule,
                )

    # Trần khung: số ca có mẫu thứ hai <= floor(cap * số ca có mẫu chính A/S) của khung.
    template_cap_dropped: list[dict[str, Any]] = []
    if max_per_case >= 2 and seconds_by_case:
        primary_by_tmpl: Counter[str] = Counter()
        suite_by_tmpl: dict[str, str] = {}
        for p in primaries_by_case.values():
            tmpl = p['template']
            if p['tier'] in ('A', 'S'):
                primary_by_tmpl[tmpl] += 1
            suite_by_tmpl.setdefault(tmpl, p['suite'])

        seconds_by_tmpl: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for s in seconds_by_case.values():
            seconds_by_tmpl[s['template']].append(s)

        for tmpl, sec_list in sorted(seconds_by_tmpl.items()):
            cap_ratio = SECOND_CAP_TIGHT if suite_by_tmpl.get(tmpl) in EASY_TIGHT else SECOND_CAP
            max_sec = math.floor(cap_ratio * primary_by_tmpl.get(tmpl, 0))
            if len(sec_list) > max_sec:
                # Giữ ưu tiên cao trước (1 < 2 < 3 < 4 < 5), cùng hạng giữ theo băm case_id + seed.
                ranked = sorted(sec_list, key=lambda x: (x['rule'], _hash_tiebreak(seed, x['case_id'])))
                for drop_item in ranked[max_sec:]:
                    del seconds_by_case[drop_item['case_id']]
                    template_cap_dropped.append({
                        'case_id': drop_item['case_id'],
                        'template': tmpl,
                        'suite': drop_item['suite'],
                        'model': drop_item['model'],
                        'run': drop_item['run'],
                        'tier': drop_item['tier'],
                        'rule': drop_item['rule'],
                        'cap_ratio': cap_ratio,
                        'max_seconds': max_sec,
                    })

    # Trần DeepSeek: tổng mẫu DeepSeek (chính + thứ hai) <= 35% tổng mẫu; chỉ bỏ mẫu thứ hai DeepSeek.
    deepseek_cap_dropped: list[dict[str, Any]] = []
    ds_cap_frac = Fraction(str(DEEPSEEK_SHARE_CAP))
    total_samples = len(primaries_by_case) + len(seconds_by_case)
    ds_total = sum(1 for x in primaries_by_case.values() if x['model'] == 'deepseek') + sum(
        1 for x in seconds_by_case.values() if x['model'] == 'deepseek'
    )
    if max_per_case >= 2:
        while total_samples > 0 and Fraction(ds_total, total_samples) > ds_cap_frac:
            ds_seconds = [s for s in seconds_by_case.values() if s['model'] == 'deepseek']
            if not ds_seconds:
                break
            # Bỏ bộ không khó trước, Tier A trước S, rồi theo băm case_id + seed.
            ds_seconds.sort(
                key=lambda x: (
                    0 if x['suite'] not in HARD_SUITES else 1,
                    0 if x['tier'] != 'S' else 1,
                    _hash_tiebreak(seed, x['case_id']),
                )
            )
            victim = ds_seconds[0]
            del seconds_by_case[victim['case_id']]
            deepseek_cap_dropped.append({
                'case_id': victim['case_id'],
                'template': victim['template'],
                'suite': victim['suite'],
                'model': victim['model'],
                'run': victim['run'],
                'tier': victim['tier'],
                'rule': victim['rule'],
            })
            ds_total -= 1
            total_samples -= 1

    proportion_drops = []
    if suite_caps or mode_caps:
        for cap in list((suite_caps or {}).values()) + list((mode_caps or {}).values()):
            if not 0 < cap <= 1:
                raise ValueError('Trần tỉ trọng phải thuộc (0, 1]')
        cases_for_modes = {c['id']: c for c in _read_jsonl(Path(scores_data['cases_path']))}

        def modes(item):
            case = cases_for_modes[item['case_id']]
            return [t.get('mode', '') for n, t in enumerate(case.get('turns') or [], 1)
                    if n not in item.get('rail_turns', [])]

        while True:
            entries = list(primaries_by_case.values()) + list(seconds_by_case.values())
            suite_counts, mode_counts = Counter(), Counter()
            total = 0
            for item in entries:
                ms = modes(item)
                total += len(ms)
                suite_counts[item['suite']] += len(ms)
                mode_counts.update(f"{item['suite']}:{mode}" for mode in ms)
            over_suites = {s for s, cap in (suite_caps or {}).items()
                           if total and Fraction(suite_counts[s], total) > Fraction(str(cap))}
            over_modes = {key for key, cap in (mode_caps or {}).items()
                          if suite_counts[key.split(':')[0]] and
                          Fraction(mode_counts[key], suite_counts[key.split(':')[0]]) > Fraction(str(cap))}
            if not over_suites and not over_modes:
                break
            victims = [item for item in entries if 'draft' not in modes(item) and (
                item['suite'] in over_suites or any(f"{item['suite']}:{mode}" in over_modes for mode in modes(item)))]
            if not victims:
                break  # draft được bảo vệ dù trần không thể đạt.
            def drop_rank(item):
                over_mode = any(f"{item['suite']}:{mode}" in over_modes for mode in modes(item))
                cand = next(c for c in scores_data['cases'][item['case_id']]['candidates']
                            if c['model'] == item['model'] and c['run'] == item['run'])
                return (0 if over_mode else 1, 0 if item['role'] == 'second' else 1,
                        -cand['rank'], _hash_tiebreak(seed, item['case_id']))
            victim = min(victims, key=drop_rank)
            # Không giữ mẫu thứ hai khi mẫu chính của chính ca ấy bị cắt.
            to_drop = [victim]
            if victim['role'] == 'primary' and victim['case_id'] in seconds_by_case:
                to_drop.insert(0, seconds_by_case[victim['case_id']])
            for item in to_drop:
                target = seconds_by_case if item['role'] == 'second' else primaries_by_case
                target.pop(item['case_id'])
                proportion_drops.append({**item, 'modes': modes(item)})
                if item['role'] == 'primary':
                    dropped.append({'case_id': item['case_id'], 'template': item['template'],
                                    'suite': item['suite'], 'reason': 'proportion_cap', 'detail': modes(item)})

    selected: list[dict[str, Any]] = []
    for cid in case_order:
        if cid not in primaries_by_case:
            continue
        selected.append(primaries_by_case[cid])
        if cid in seconds_by_case:
            selected.append(seconds_by_case[cid])

    total_cases = len(scores_data['cases'])
    selected_cases = len(primaries_by_case)
    selected_samples = len(selected)
    by_model = Counter(s['source_model'] for s in selected)
    by_suite = Counter(s['suite'] for s in selected)
    by_template = Counter(s['template'] for s in selected)
    by_role = Counter(s['role'] for s in selected)
    by_tier = Counter(s['tier'] for s in selected)
    by_rule = Counter(str(s['rule']) for s in selected if s['rule'] is not None)
    by_sstr = Counter(f"{s['suite']}|{s['model']}|{s['tier']}|{s['role']}" for s in selected)
    drop_reasons = Counter(d['reason'] for d in dropped)
    agreed = sum(a == b for a, b in all_pairs)
    overall_agree = {
        'items': len(all_pairs),
        'agreed': agreed,
        'percent': (agreed / len(all_pairs)) if all_pairs else None,
        'kappa': eval_regrade.kappa(all_pairs),
    }
    ds_share = (by_model.get('deepseek', 0) / selected_samples) if selected_samples else None
    ds_cap_satisfied = (selected_samples == 0) or (Fraction(by_model.get('deepseek', 0), selected_samples) <= ds_cap_frac)

    selection = {
        'scores_path': str(scores_path.resolve()),
        'cases_path': scores_data.get('cases_path'),
        'run_dirs': scores_data.get('run_dirs') or {},
        'repo_sha': scores_data.get('repo_sha') or {},
        'allow_b': allow_b,
        'max_per_case': max_per_case,
        'seed': seed,
        'selected': selected,
        'dropped': dropped,
        'summary': {
            'total_cases': total_cases,
            'selected_cases': selected_cases,
            'selected_samples': selected_samples,
            'dropped_cases': len(dropped),
            'by_model': {m: by_model.get(m, 0) for m in ('qwen', 'deepseek')},
            'by_role': {r: by_role.get(r, 0) for r in ('primary', 'second')},
            'by_tier': {t: by_tier.get(t, 0) for t in ('S', 'A', 'B') if by_tier.get(t, 0) or t in ('S', 'A')},
            'by_rule': dict(sorted(by_rule.items(), key=lambda kv: int(kv[0]))),
            'by_suite': dict(sorted(by_suite.items())),
            'by_template': dict(sorted(by_template.items())),
            'by_suite_source_tier_role': dict(sorted(by_sstr.items())),
            'deepseek_share': round(ds_share, 4) if ds_share is not None else None,
            'caps': {
                'second_cap': SECOND_CAP,
                'second_cap_tight': SECOND_CAP_TIGHT,
                'deepseek_share_cap': DEEPSEEK_SHARE_CAP,
                'template_cap_dropped_count': len(template_cap_dropped),
                'template_cap_dropped': template_cap_dropped,
                'deepseek_cap_dropped_count': len(deepseek_cap_dropped),
                'deepseek_cap_dropped': deepseek_cap_dropped,
                'deepseek_cap_satisfied': ds_cap_satisfied,
            },
            'drop_reasons': dict(sorted(drop_reasons.items())),
            'agreement_ab': overall_agree,
            'rounds': round_agreements,
        },
    }
    if suite_caps or mode_caps:
        selection['summary']['proportion_caps'] = {
            'suite': suite_caps or {}, 'mode': mode_caps or {}, 'dropped': proportion_drops,
            'dropped_samples': sum(len(item['modes']) for item in proportion_drops),
            'by_suite_mode_role': dict(sorted(Counter(
                f"{item['suite']}|{mode}|{item['role']}" for item in proportion_drops for mode in item['modes']).items())),
            'remaining_over_suites': sorted(over_suites), 'remaining_over_modes': sorted(over_modes),
        }
    _write_json(out_path, selection)
    report_path = out_path.parent / 'selection_report.md'
    report_path.write_text(_render_selection_report(selection), encoding='utf-8')
    return selection


def _render_selection_report(selection: dict[str, Any]) -> str:
    s = selection['summary']
    total = s['total_cases']
    sel_cases = s['selected_cases']
    sel_samples = s.get('selected_samples', sel_cases)
    drop_n = s['dropped_cases']
    by_model = s['by_model']
    qwen_n = by_model.get('qwen', 0)
    ds_n = by_model.get('deepseek', 0)
    by_role = s.get('by_role') or {'primary': sel_cases, 'second': 0}
    by_tier = s.get('by_tier') or {}
    caps = s.get('caps') or {}
    ag = s['agreement_ab']
    k_val = '-' if ag['kappa'] is None else f"{ag['kappa']:.3f}"

    lines = [
        '# Báo cáo chọn mẫu SFT (`sft_select`)',
        '',
        '## Tổng quan',
        '',
        f'- Tổng số ca đầu vào: **{total}**',
        f'- Số ca chọn được mẫu: **{sel_cases}** ({_pct_str(sel_cases / total if total else None)})',
        f'- Tổng số mẫu được chọn (`--max-per-case {selection.get("max_per_case", 2)}`): **{sel_samples}** '
        f'(chính: **{by_role.get("primary", 0)}**, thứ hai: **{by_role.get("second", 0)}**)',
        f'- Theo Tier: {by_tier}',
        f'- Số ca bị bỏ: **{drop_n}**',
        f'- Cho phép fallback Tier B (`--allow-b`): **{selection["allow_b"]}**',
        f'- Tỉ trọng DeepSeek: **{_pct_str(s.get("deepseek_share"))}** '
        f'(trần {int(DEEPSEEK_SHARE_CAP * 100)}%, đạt trần: **{caps.get("deepseek_cap_satisfied", True)}**)',
        f'- Độ khớp giám khảo A–B: **{_pct_str(ag["percent"])}** trên {ag["items"]} mục, Cohen\'s kappa = **{k_val}**',
        '',
        '## Trần đã áp',
        '',
        f'- Trần mẫu thứ hai theo khung (≤ {int(SECOND_CAP * 100)}% khung thường, ≤ {int(SECOND_CAP_TIGHT * 100)}% T09/T10): '
        f'bỏ **{caps.get("template_cap_dropped_count", 0)}** mẫu thứ hai',
        f'- Trần DeepSeek (≤ {int(DEEPSEEK_SHARE_CAP * 100)}% toàn tập): '
        f'bỏ **{caps.get("deepseek_cap_dropped_count", 0)}** mẫu thứ hai DeepSeek',
        f'- Phân bổ mẫu thứ hai theo luật (1–5): {s.get("by_rule") or {}}',
        '',
        '## Tỉ lệ nguồn mẫu (Qwen / DeepSeek)',
        '',
        '| Nguồn | Số mẫu | Tỉ lệ trong tổng mẫu |',
        '|---|---|---|',
        f'| `qwen` | {qwen_n} | {_pct_str(qwen_n / sel_samples if sel_samples else None)} |',
        f'| `deepseek` | {ds_n} | {_pct_str(ds_n / sel_samples if sel_samples else None)} |',
        '',
        '## Phân bổ theo bộ × nguồn × tier × vai',
        '',
        '| Bộ | Nguồn | Tier | Vai | Số mẫu |',
        '|---|---|---|---|---|',
    ]
    sstr = s.get('by_suite_source_tier_role') or {}
    for key, cnt in sorted(sstr.items()):
        suite, src, tier, role = key.split('|')
        lines.append(f'| {suite} | `{src}` | {tier} | `{role}` | {cnt} |')
    if not sstr:
        lines.append('| (trống) | - | - | - | 0 |')

    lines += [
        '',
        '## Phân bổ theo bộ (`suite`)',
        '',
        '| Bộ | Số mẫu |',
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
        '| Khung | Số mẫu |',
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

    if 'proportion_caps' in s:
        caps_info = s['proportion_caps']
        lines += ['', '## Trần tỉ trọng theo bộ × chế độ × vai', '',
                  f'- Số mẫu bỏ: {caps_info["dropped_samples"]}',
                  f'- Phân bổ: {caps_info["by_suite_mode_role"]}',
                  f'- Bộ còn vượt trần do bảo vệ draft: {caps_info["remaining_over_suites"]}',
                  f'- Chế độ còn vượt trần do bảo vệ draft: {caps_info["remaining_over_modes"]}']
    lines.append('')
    return '\n'.join(lines)


def _parse_caps(specs, *, mode=False):
    result = {}
    for spec in specs or []:
        for piece in spec.split(','):
            key, sep, value = piece.partition('=')
            pattern = r'T\d{2}:(?:draft|ask|summary)' if mode else r'T\d{2}'
            if not sep or not re.fullmatch(pattern, key) or key in result:
                raise ValueError(f'Trần tỉ trọng không hợp lệ hoặc trùng: {piece}')
            ratio = float(value)
            if not 0 < ratio <= 1:
                raise ValueError(f'Trần tỉ trọng phải thuộc (0, 1]: {piece}')
            result[key] = ratio
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='sft_select.py', description=__doc__.split('\n\n')[0])
    parser.add_argument('--print-rubric', action='store_true', help='In đầy đủ hướng dẫn chấm tier cho giám khảo và thoát')
    parser.add_argument('--print-rubric-s', action='store_true', help='In hướng dẫn chấm cặp Tier S (7 tiêu chí) và thoát')
    parser.add_argument('--max-tool-chars', type=int, default=DEFAULT_MAX_TOOL_CHARS,
                        help='Giới hạn ký tự kết quả tool trong rubric (mặc định 3000)')
    sub = parser.add_subparsers(dest='command')

    p_score = sub.add_parser('score', help='Chấm code, gắn cờ và xếp hạng ứng viên từ kết quả runner')
    p_score.add_argument('--cases', required=True, type=Path, help='Tệp ca huấn luyện JSONL')
    p_score.add_argument('--run', '--run-dir', action='append', default=[], metavar='MODEL=DIR',
                         help='Thư mục kết quả theo model, ví dụ qwen=dir hoặc deepseek=dir')
    p_score.add_argument('--out', required=True, type=Path, help='Đường dẫn scores.json đầu ra')
    p_score.add_argument('--runs', type=Path, help='Danh sách lượt chạy có offset và nhãn gợi ý')

    p_exp = sub.add_parser('export', help='Xuất gói giám khảo ẩn danh cho vòng 1, vòng 2 hoặc trọng tài (--arbiter)')
    p_exp.add_argument('--scores', required=True, type=Path, help='Tệp scores.json')
    p_exp.add_argument('--out', required=True, type=Path, help='Thư mục gói chấm đầu ra')
    p_exp.add_argument('--round', type=int, default=1, help='Số vòng chấm (1 hoặc 2)')
    p_exp.add_argument('--after', nargs='+', action='append', type=Path, default=None,
                       help='Tệp adjudicated JSON từ các vòng trước (bắt buộc nếu --round >= 2)')
    p_exp.add_argument('--arbiter', action='store_true', help='Xuất gói trọng tài từ tệp --base adjudicated')
    p_exp.add_argument('--base', type=Path, default=None, help='Tệp adjudicated gốc (bắt buộc khi --arbiter)')
    p_exp.add_argument('--base-map', type=Path, default=None, help='Đường dẫn map.json gốc tùy chọn khi --arbiter')
    p_exp.add_argument('--exclude-templates', nargs='+', action='append', default=None,
                       help='Danh sách tên khung cần loại trừ (không ghim cứng trong code)')
    p_exp.add_argument('--seed', type=int, default=DEFAULT_SEED)
    p_exp.add_argument('--batch-size', type=int, default=DEFAULT_BATCH_SIZE)
    p_exp.add_argument('--max-tool-chars', type=int, default=argparse.SUPPRESS,
                       help='Giới hạn ký tự mỗi kết quả tool (mặc định 3000)')

    p_imp = sub.add_parser('import', help='Đọc phiếu giám khảo A/B hoặc trọng tài (--arbiter), kiểm trích dẫn và xếp Tier')
    p_imp.add_argument('--judge-dir', required=True, type=Path, help='Thư mục gói chấm chứa map.json và verdicts/')
    p_imp.add_argument('--scores', type=Path, default=None, help='Tệp scores.json (bắt buộc khi không dùng --arbiter)')
    p_imp.add_argument('--arbiter', action='store_true', help='Nhập phiếu trọng tài (1 giám khảo) vào --base')
    p_imp.add_argument('--base', type=Path, default=None, help='Tệp adjudicated gốc (bắt buộc khi --arbiter)')
    p_imp.add_argument('--strict-kckc', action='store_true',
                       help='Chế độ chặt: mục kc/kc dù trọng tài dat vẫn giữ Tier B (chỉ dùng cùng --arbiter)')
    p_imp.add_argument('--out', required=True, type=Path, help='Tệp adjudicated JSON đầu ra')

    p_exps = sub.add_parser('export-tier-s', help='Xuất gói chấm cặp Tier S cho mọi ca có >= 2 ứng viên Tier A')
    p_exps.add_argument('--scores', required=True, type=Path, help='Tệp scores.json')
    p_exps.add_argument('--adjudicated', nargs='+', action='append', required=True, type=Path,
                        help='Một hoặc nhiều tệp adjudicated JSON')
    p_exps.add_argument('--out', required=True, type=Path, help='Thư mục gói chấm cặp Tier S đầu ra')
    p_exps.add_argument('--exclude-templates', nargs='+', action='append', default=None,
                        help='Danh sách tên khung cần loại trừ')
    p_exps.add_argument('--seed', type=int, default=DEFAULT_SEED)
    p_exps.add_argument('--batch-size', type=int, default=DEFAULT_TIER_S_BATCH_SIZE)
    p_exps.add_argument('--max-tool-chars', type=int, default=argparse.SUPPRESS,
                        help='Giới hạn ký tự mỗi kết quả tool (mặc định 3000)')

    p_imps = sub.add_parser('import-tier-s', help='Đọc phiếu chấm cặp Tier S, kiểm 7 trích dẫn/mẫu và gắn nhãn S')
    p_imps.add_argument('--judge-dir', required=True, type=Path, help='Thư mục gói chấm Tier S chứa map.json và verdicts/')
    p_imps.add_argument('--adjudicated', nargs='+', action='append', required=True, type=Path,
                        help='Một hoặc nhiều tệp adjudicated JSON để gắn thêm tier_s và s_pairs')
    p_imps.add_argument('--out', required=True, type=Path, help='Tệp adjudicated JSON đầu ra có thêm tier_s và s_pairs')

    p_sel = sub.add_parser('select', help='Gộp kết quả adjudicated/Tier S và chọn tối đa 2 mẫu/ca theo trần')
    p_sel.add_argument('--scores', required=True, type=Path, help='Tệp scores.json')
    p_sel.add_argument('--adjudicated', nargs='+', action='append', required=True, type=Path,
                       help='Một hoặc nhiều tệp adjudicated JSON')
    p_sel.add_argument('--allow-b', action='store_true', help='Cho phép fallback sang Tier B nếu ca không có Tier A')
    p_sel.add_argument('--max-per-case', type=int, default=2,
                       help='Số mẫu tối đa mỗi ca (mặc định 2; truyền 1 để giữ hành vi chọn 1 mẫu/ca cũ)')
    p_sel.add_argument('--seed', type=int, default=DEFAULT_SEED, help='Seed băm khi cắt trần khung/DeepSeek')
    p_sel.add_argument('--exclude-templates', nargs='+', action='append', default=None,
                       help='Danh sách tên khung cần loại trừ')
    p_sel.add_argument('--out', required=True, type=Path, help='Tệp selection.json đầu ra')
    p_sel.add_argument('--suite-cap', action='append', default=[], help='Ví dụ T11=0.12')
    p_sel.add_argument('--mode-cap', action='append', default=[], help='Ví dụ T11:summary=0.25,T11:ask=0.45')

    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.print_rubric:
        if args.max_tool_chars <= 0:
            parser.error('--max-tool-chars phải lớn hơn 0')
        print(rubric_text(args.max_tool_chars))
        return 0
    if args.print_rubric_s:
        if args.max_tool_chars <= 0:
            parser.error('--max-tool-chars phải lớn hơn 0')
        # Nếu user không chỉ định --max-tool-chars ở mức top-level thì dùng 8.000 theo thiết kế Tier S.
        explicit_chars = any(tok == '--max-tool-chars' or tok.startswith('--max-tool-chars=') for tok in (argv or sys.argv[1:]))
        print(tier_s_rubric_text(args.max_tool_chars if explicit_chars else 8000))
        return 0
    if not args.command:
        parser.error('a subcommand (score, export, import, export-tier-s, import-tier-s, select) or --print-rubric is required')

    try:
        if args.command == 'score':
            if bool(args.run) == bool(args.runs):
                raise ValueError('Chọn đúng một trong --run-dir và --runs')
            run_specs = _parse_run_specs(args.run)
            runs = json.loads(args.runs.read_text(encoding='utf-8')) if args.runs else None
            result = score_runs(args.cases, run_specs, runs=runs)
            _write_json(args.out, result)
            total = len(result['cases'])
            with_cand = sum(1 for c in result['cases'].values() if c['candidates'])
            print(f'score: {total} ca, {with_cand} ca có ứng viên A_code/B_code -> {args.out}')
            return 0

        if args.command == 'export':
            if args.arbiter:
                if not args.base:
                    parser.error('--base là bắt buộc khi dùng --arbiter')
                info = export_arbiter(
                    args.base,
                    args.scores,
                    args.out,
                    base_map_path=args.base_map,
                    seed=args.seed,
                    batch_size=args.batch_size,
                    max_tool_chars=args.max_tool_chars,
                )
                print(
                    f"export trọng tài ({info['round']}): {info['candidates']} ứng viên, "
                    f"{info['items']} lượt trong {info['batches']} lô -> {args.out}"
                )
                return 0
            after_flat = [p for grp in (args.after or []) for p in grp]
            info = export_judge_round(
                args.scores,
                args.out,
                round_no=args.round,
                after_paths=after_flat,
                seed=args.seed,
                batch_size=args.batch_size,
                max_tool_chars=args.max_tool_chars,
                exclude_templates=args.exclude_templates,
            )
            extra = f" {info['by_class']}" if 'by_class' in info else ''
            print(
                f"export vòng {info['round']}: {info['candidates']} ứng viên{extra}, "
                f"{info['items']} lượt trong {info['batches']} lô -> {args.out}"
            )
            return 0

        if args.command == 'import':
            if args.arbiter:
                if not args.base:
                    parser.error('--base là bắt buộc khi dùng --arbiter')
                code, res = import_arbiter(
                    args.judge_dir,
                    args.base,
                    args.out,
                    strict_kckc=args.strict_kckc,
                )
                if code != 0:
                    print('Phiếu trọng tài chưa hợp lệ, chưa gộp:\n  ' + '\n  '.join(res['errors']))
                    return code
                print(
                    f"import trọng tài ({res['arbiter']['rule']}): tier={res['tier_counts']}, "
                    f"counts={res['arbiter']['counts']} -> {args.out}"
                )
                return 0
            if not args.scores:
                parser.error('--scores là bắt buộc khi không dùng --arbiter')
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

        if args.command == 'export-tier-s':
            adj_flat = [p for grp in args.adjudicated for p in grp]
            info = export_tier_s(
                args.scores,
                adj_flat,
                args.out,
                seed=args.seed,
                batch_size=args.batch_size,
                max_tool_chars=args.max_tool_chars,
                exclude_templates=args.exclude_templates,
            )
            print(
                f"export-tier-s: {info['pairs']} cặp, {info['items']} lượt trong {info['batches']} lô -> {args.out}"
            )
            return 0

        if args.command == 'import-tier-s':
            adj_flat = [p for grp in args.adjudicated for p in grp]
            code, res = import_tier_s(args.judge_dir, adj_flat, args.out)
            if code != 0:
                print('Phiếu Tier S chưa hợp lệ, chưa gộp:\n  ' + '\n  '.join(res['errors']))
                return code
            ts = res['tier_s_summary']
            print(
                f"import-tier-s: S={ts['candidates_s']}/{ts['candidates_evaluated']}, "
                f"cặp khác={ts['pairs_different']}/{ts['pairs_total']}, "
                f"hạ S={ts['downgraded_s_count']} -> {args.out}"
            )
            return 0

        if args.command == 'select':
            adj_flat = [p for grp in args.adjudicated for p in grp]
            sel = select_candidates(
                args.scores,
                adj_flat,
                args.out,
                allow_b=args.allow_b,
                max_per_case=args.max_per_case,
                seed=args.seed,
                exclude_templates=args.exclude_templates,
                suite_caps=_parse_caps(args.suite_cap),
                mode_caps=_parse_caps(args.mode_cap, mode=True),
            )
            s = sel['summary']
            print(
                f"select: {s['selected_cases']}/{s['total_cases']} ca, {s['selected_samples']} mẫu "
                f"(qwen={s['by_model']['qwen']}, deepseek={s['by_model']['deepseek']}, "
                f"ds_share={_pct_str(s['deepseek_share'])}) -> {args.out}"
            )
            return 0
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f'Lỗi: {exc}', file=sys.stderr)
        return 2

    return 0


if __name__ == '__main__':
    sys.exit(main())
