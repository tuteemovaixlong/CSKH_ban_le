"""Customer utterance generator using DeepSeek with code validation and deduplication (sft_v1).

W6.7.0 Part A.
CLI:
  python scripts/sft_utterances.py fill --dir <thư mục generate> \\
      --endpoint https://api.deepseek.com/chat/completions \\
      --model deepseek-flash --concurrency 8 [--allow-peak] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import eval_regrade
from scripts.sft_dataset import get_eval_user_utterances

DEFAULT_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-flash"

VIETNAMESE_ACCENTS_RE = re.compile(
    r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    r"ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ]"
)

SYSTEM_PROMPT = """Bạn là người viết lời khách hàng cho bộ dữ liệu chăm sóc khách hàng (CSKH) thương mại điện tử Việt Nam.
Nhiệm vụ: Bạn nhận được một phiếu yêu cầu (JSON brief) và phải viết MỘT câu hoặc đoạn tin nhắn của khách hàng đúng theo yêu cầu trong phiếu.

Quy tắc bắt buộc:
1. Trả về DUY NHẤT một đối tượng JSON hợp lệ: {"user": "..."}. Không kèm bất kỳ lời giải thích nào khác.
2. Viết đúng giọng văn được yêu cầu trong phiếu:
   - "chuan": Tiếng Việt chuẩn mực, tự nhiên, lịch sự.
   - "khong_dau": Tiếng Việt KHÔNG DẤU hoàn toàn (tuyệt đối không có ký tự có dấu nào, ví dụ: "shop oi don hang cua minh toi dau roi").
   - "teencode": Viết tắt kiểu chat giới trẻ (ví dụ: ko, dc, mk, ak, z, b, j, nha...).
   - "sai_chinh_ta": Một vài lỗi gõ phím/telex tự nhiên (dính phím, ch/tr, s/x, d/gi...).
   - "dai": 3 đến 6 câu kể lể hoàn cảnh chi tiết, dài dòng.
3. Bắt buộc chứa nguyên văn mọi chuỗi trong "must_include" (đặc biệt là mã đơn hàng, tên sản phẩm nếu có).
4. Tuyệt đối KHÔNG chứa bất kỳ cụm từ nào trong "must_not_include".
5. Đóng đúng vai khách hàng: không nói thay trợ lý, không chào thay shop, không nhắc tới AI, hệ thống hay prompt (trừ khi phiếu có yêu cầu "injection", khi đó hãy chèn nội dung injection nguyên văn).
"""


def is_peak_hour(now_dt: datetime | None = None) -> bool:
    tz_vn = timezone(timedelta(hours=7))
    dt = now_dt or datetime.now(tz_vn)
    # Vietnam time: Monday - Friday (0..4), 13:00 to 17:00 (hours 13, 14, 15, 16)
    return dt.weekday() < 5 and 13 <= dt.hour < 17


def get_char_ngrams(text: str, n: int = 5) -> set[str]:
    norm = " ".join(str(text or "").lower().split())
    if len(norm) < n:
        return set()
    return {norm[i : i + n] for i in range(len(norm) - n + 1)}


def jaccard_5gram(t1: str, t2: str) -> float:
    g1 = get_char_ngrams(t1)
    g2 = get_char_ngrams(t2)
    if not g1 or not g2:
        return 0.0
    return len(g1 & g2) / len(g1 | g2)


def max_common_substring_len(s1: str, s2: str, threshold: int = 40) -> int:
    norm1 = " ".join(str(s1 or "").lower().split())
    norm2 = " ".join(str(s2 or "").lower().split())
    if len(norm1) < threshold or len(norm2) < threshold:
        return 0
    for i in range(len(norm1) - threshold + 1):
        if norm1[i : i + threshold] in norm2:
            return threshold
    return 0


def validate_utterance(
    user_text: str,
    brief: dict[str, Any],
    eval_utterances: set[str],
    template_utterances: list[str],
) -> tuple[bool, str]:
    txt = str(user_text or "").strip()
    if not txt:
        return False, "Câu trả lời rỗng"

    # 1. must_include check
    for item in brief.get("must_include", []):
        if item not in txt:
            return False, f"Thiếu chuỗi bắt buộc '{item}'"

    # 2. must_not_include check (using eval_regrade.v2)
    canon_user = eval_regrade.v2(txt)
    for item in brief.get("must_not_include", []):
        if eval_regrade.v2(item) in canon_user:
            return False, f"Chứa cụm từ cấm '{item}'"

    # 3. length check
    length_req = brief.get("length", "vừa")
    style = brief.get("style", "chuan")
    words = txt.split()

    if style == "dai":
        if len(txt) < 80 and len(words) < 15:
            return False, f"Giọng 'dai' nhưng câu quá ngắn ({len(txt)} ký tự)"
    elif length_req == "ngắn":
        if len(words) > 40 or len(txt) > 220:
            return False, f"Yêu cầu 'ngắn' nhưng câu dài quá ({len(words)} từ)"

    # 4. khong_dau check
    if style == "khong_dau":
        if VIETNAMESE_ACCENTS_RE.search(txt):
            return False, "Giọng 'khong_dau' nhưng có chứa ký tự tiếng Việt có dấu"

    # 5. Overlap with all 250 evaluation cases: Jaccard 5-gram <= 0.45 and no common substring >= 40 chars
    for eval_u in eval_utterances:
        if jaccard_5gram(txt, eval_u) > 0.45:
            return False, f"Trùng lặp 5-gram > 0.45 với câu của ca đo: {eval_u[:50]}..."
        if max_common_substring_len(txt, eval_u, 40) >= 40:
            return False, f"Chung chuỗi con >= 40 ký tự với ca đo: {eval_u[:50]}..."

    # 6. Overlap with other utterances in the same template: Jaccard 5-gram <= 0.70
    for other_u in template_utterances:
        if jaccard_5gram(txt, other_u) > 0.70:
            return False, f"Trùng lặp 5-gram > 0.70 với câu khác cùng khung: {other_u[:50]}..."

    return True, "OK"


class DeepSeekClient:
    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        mock_handler: Callable[[dict[str, Any]], str] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.mock_handler = mock_handler

    def call(self, brief: dict[str, Any], feedback: str | None = None) -> str:
        if self.mock_handler is not None:
            return self.mock_handler(brief)

        if not self.api_key:
            raise ValueError("Thiếu biến môi trường DEEPSEEK_API_KEY để gọi DeepSeek API.")

        user_content = json.dumps(brief, ensure_ascii=False, indent=2)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Hãy viết lời khách cho phiếu sau:\n{user_content}"},
        ]
        if feedback:
            messages.append(
                {"role": "system", "content": f"LẦN THỬ TRƯỚC BỊ LỖI: {feedback}. Hãy sửa lại đúng các quy tắc."}
            )

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 1.0,
            "response_format": {"type": "json_object"},
        }

        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choice = data["choices"][0]["message"]["content"]
                parsed = json.loads(choice)
                return str(parsed.get("user") or "").strip()
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"DeepSeek API HTTP {exc.code}: {err_body}") from exc


def fill_utterances(
    generate_dir: Path | str,
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    model: str = DEFAULT_MODEL,
    allow_peak: bool = False,
    limit: int | None = None,
    client: DeepSeekClient | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    gen_dir = Path(generate_dir).resolve()
    briefs_file = gen_dir / "briefs_sft_v1.jsonl"
    cases_file = gen_dir / "cases_sft_v1.jsonl"
    cache_file = gen_dir / "utterances_cache.jsonl"
    filled_file = gen_dir / "cases_sft_v1_filled.jsonl"
    report_file = gen_dir / "utterances_report.md"

    assert briefs_file.is_file(), f"Briefs file not found: {briefs_file}"
    assert cases_file.is_file(), f"Cases file not found: {cases_file}"

    # Peak hour gate
    current_dt = now_fn() if now_fn else None
    if not allow_peak and is_peak_hour(current_dt):
        raise RuntimeError(
            "Đang trong giờ cao điểm của DeepSeek (13:00–17:00 ngày thường, giờ VN). "
            "Dừng để tránh lỗi nghẽn và chi phí cao, trừ khi truyền flag --allow-peak."
        )

    # Load cache if exists
    cache: dict[str, str] = {}
    if cache_file.is_file():
        for line in cache_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                if item.get("brief_id") and item.get("user"):
                    cache[item["brief_id"]] = item["user"]

    briefs: list[dict[str, Any]] = []
    for line in briefs_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            briefs.append(json.loads(line))

    eval_utterances = get_eval_user_utterances()
    template_utterances: dict[str, list[str]] = {}

    for bid, txt in cache.items():
        pass

    llm = client or DeepSeekClient(endpoint=endpoint, model=model)

    filled_count = 0
    failed_count = 0
    failures: list[dict[str, Any]] = []

    target_briefs = briefs if limit is None else briefs[: int(limit)]

    with open(cache_file, "a", encoding="utf-8") as cache_fh:
        for b in target_briefs:
            bid = b["brief_id"]
            tmpl = b.get("template", "unknown")
            template_list = template_utterances.setdefault(tmpl, [])

            if bid in cache:
                template_list.append(cache[bid])
                filled_count += 1
                continue

            # Generation loop with up to 3 retries
            feedback = None
            success = False
            final_user = ""

            for attempt in range(1, 4):
                try:
                    generated = llm.call(b, feedback=feedback)
                except Exception as exc:
                    feedback = f"Lỗi gọi API: {exc}"
                    continue

                ok, reason = validate_utterance(generated, b, eval_utterances, template_list)
                if ok:
                    final_user = generated
                    success = True
                    break
                else:
                    feedback = reason

            if success:
                cache[bid] = final_user
                template_list.append(final_user)
                cache_fh.write(json.dumps({"brief_id": bid, "user": final_user}, ensure_ascii=False) + "\n")
                cache_fh.flush()
                filled_count += 1
            else:
                failed_count += 1
                failures.append({"brief_id": bid, "case_id": b["case_id"], "reason": feedback})

    # Assemble cases_sft_v1_filled.jsonl
    cases: list[dict[str, Any]] = []
    for line in cases_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))

    # Index briefs by (case_id, turn)
    brief_map: dict[tuple[str, int], str] = {}
    setup_brief_map: dict[str, str] = {}

    for b in briefs:
        bid = b["brief_id"]
        if bid in cache:
            if b.get("suite") == "T11" and "_setup" in bid:
                setup_brief_map[b["case_id"]] = cache[bid]
            else:
                brief_map[(b["case_id"], b["turn"])] = cache[bid]

    filled_cases = []
    dropped_cases = []

    for c in cases:
        cid = c["id"]
        is_complete = True

        if c.get("actor") == "staff_case_assist":
            if cid in setup_brief_map:
                c["case_setup"]["customer_messages"][0]["text"] = setup_brief_map[cid]
            elif any(f["case_id"] == cid for f in failures):
                is_complete = False

        for t_idx, turn in enumerate(c.get("turns", []), start=1):
            if (cid, t_idx) in brief_map:
                turn["user"] = brief_map[(cid, t_idx)]
            elif any(f["case_id"] == cid for f in failures):
                is_complete = False

        if is_complete:
            filled_cases.append(c)
        else:
            dropped_cases.append(cid)

    with open(filled_file, "w", encoding="utf-8") as f:
        for fc in filled_cases:
            f.write(json.dumps(fc, ensure_ascii=False) + "\n")

    report_lines = [
        "# Báo Cáo Điền Lời Khách Hàng (SFT v1)",
        f"- Tổng số phiếu: **{len(briefs)}**",
        f"- Số câu đã điền thành công: **{filled_count}**",
        f"- Số câu thất bại: **{failed_count}**",
        f"- Số ca hoàn chỉnh: **{len(filled_cases)}**",
        f"- Số ca bị loại: **{len(dropped_cases)}**",
        "",
        "## Danh sách ca thất bại (nếu có)",
    ]
    if failures:
        for fail in failures:
            report_lines.append(f"- `{fail['brief_id']}` ({fail['case_id']}): {fail['reason']}")
    else:
        report_lines.append("Không có ca nào thất bại.")

    report_file.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    return {
        "total_briefs": len(briefs),
        "filled_count": filled_count,
        "failed_count": failed_count,
        "filled_cases": len(filled_cases),
        "dropped_cases": len(dropped_cases),
        "report_path": report_file,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and validate customer utterances")
    subparsers = parser.add_subparsers(dest="command")

    p_fill = subparsers.add_parser("fill", help="Fill customer utterances from briefs")
    p_fill.add_argument("--dir", required=True, help="Generation directory containing briefs and cases")
    p_fill.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="DeepSeek API endpoint")
    p_fill.add_argument("--model", default=DEFAULT_MODEL, help="DeepSeek model name")
    p_fill.add_argument("--concurrency", type=int, default=8, help="Concurrency level")
    p_fill.add_argument("--allow-peak", action="store_true", help="Allow running during peak hours")
    p_fill.add_argument("--limit", type=int, default=None, help="Limit number of briefs to process")

    args = parser.parse_args()

    if args.command == "fill":
        res = fill_utterances(
            args.dir,
            endpoint=args.endpoint,
            model=args.model,
            allow_peak=args.allow_peak,
            limit=args.limit,
        )
        print(f"Filled: {res['filled_count']}/{res['total_briefs']} briefs.")
        print(f"Cases: {res['filled_cases']} complete, {res['dropped_cases']} dropped.")
        print(f"Report: {res['report_path']}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
