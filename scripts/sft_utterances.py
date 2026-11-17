"""Customer utterance generator using DeepSeek with code validation and deduplication (sft_v1).

W6.7.0 Part A.
CLI:
  python scripts/sft_utterances.py fill --dir <thư mục generate> \\
      --endpoint https://api.deepseek.com/chat/completions \\
      --model deepseek-flash --concurrency 8 [--allow-peak] [--limit N]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import inspect
import json
import os
import re
import sys
import threading
import time
import unicodedata
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


def strip_vietnamese_accents(s: str) -> str:
    """Strip Vietnamese accents from string: đ/Đ -> d/D and remove combining marks."""
    s = s.replace('đ', 'd').replace('Đ', 'D')
    decomposed = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in decomposed if not unicodedata.combining(c))


def normalize_brief_for_style(brief: dict[str, Any]) -> dict[str, Any]:
    """Normalize brief requirements based on style: convert must_include/may_include to unaccented if khong_dau, shorten long product names for teencode/sai_chinh_ta."""
    b = dict(brief)
    style = b.get("style")
    if style == "khong_dau":
        b["must_include"] = [strip_vietnamese_accents(x) for x in b.get("must_include", [])]
        b["may_include"] = [strip_vietnamese_accents(x) for x in b.get("may_include", [])]
        notes = b.get("notes", "")
        if "viết không dấu" not in notes.lower():
            b["notes"] = (notes + " (Lưu ý: Tên sản phẩm và các từ khóa được viết không dấu)").strip()
    elif style in ("teencode", "sai_chinh_ta"):
        must = list(b.get("must_include", []))
        may = list(b.get("may_include", []))
        pid = next((x for x in may if x.startswith("P-")), None)
        new_must = []
        for item in must:
            words = item.split()
            has_code = any(c.isdigit() or c == '-' for c in item)
            if len(words) >= 3 and not has_code:
                if pid:
                    new_must.append(pid)
                else:
                    new_must.append(" ".join(words[:2]))
            else:
                new_must.append(item)
        b["must_include"] = new_must
    return b

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

    style = brief.get("style", "chuan")
    is_khong_dau = style == "khong_dau"

    # 1. must_include check
    for raw_item in brief.get("must_include", []):
        item = strip_vietnamese_accents(raw_item) if is_khong_dau else raw_item
        # IDs, codes, numeric identifiers (e.g. SIM-O-50001, VCH-..., 11.11, P-101): check case-sensitive
        if any(c.isdigit() or c == '-' for c in item):
            if item not in txt:
                return False, f"Thiếu chuỗi bắt buộc '{item}'"
        else:
            if style in ("teencode", "sai_chinh_ta") and len(item.split()) >= 3:
                # Flexible match: if >= 60% of unaccented words appear in text
                unacc_item_words = strip_vietnamese_accents(item).lower().split()
                unacc_txt = strip_vietnamese_accents(txt).lower()
                matches = sum(1 for w in unacc_item_words if w in unacc_txt)
                if matches / len(unacc_item_words) < 0.60:
                    return False, f"Thiếu chuỗi bắt buộc (khớp linh hoạt < 60%): '{item}'"
            else:
                if item.lower() not in txt.lower():
                    return False, f"Thiếu chuỗi bắt buộc '{item}'"

    # 1b. injection check if specified in brief
    injection = brief.get("injection")
    if injection:
        if injection not in txt:
            return False, f"Thiếu chuỗi chèn lệnh (injection) '{injection}'"

    # 2. must_not_include check (using eval_regrade.v2)
    canon_user = eval_regrade.v2(txt)
    for item in brief.get("must_not_include", []):
        if eval_regrade.v2(item) in canon_user:
            return False, f"Chứa cụm từ cấm '{item}'"

    # 3. length check
    length_req = brief.get("length", "vừa")
    words = txt.split()

    if style == "dai":
        if len(txt) < 80 and len(words) < 15:
            return False, f"Giọng 'dai' nhưng câu quá ngắn ({len(txt)} ký tự)"
    elif length_req == "ngắn":
        if len(words) > 40 or len(txt) > 220:
            return False, f"Yêu cầu 'ngắn' nhưng câu dài quá ({len(words)} từ)"

    # 4. khong_dau check (exclude injection string if present)
    if is_khong_dau:
        txt_to_check = txt
        if injection:
            txt_to_check = txt_to_check.replace(injection, "")
        if VIETNAMESE_ACCENTS_RE.search(txt_to_check):
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
        mock_handler: Callable[..., str] | None = None,
        backoff_seconds: tuple[float, ...] = (1.0, 2.0, 4.0),
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.mock_handler = mock_handler
        self.backoff_seconds = backoff_seconds

    def call(self, brief: dict[str, Any], feedback: str | None = None) -> str:
        max_retries = len(self.backoff_seconds)
        for retry in range(max_retries + 1):
            try:
                if self.mock_handler is not None:
                    sig = inspect.signature(self.mock_handler)
                    if len(sig.parameters) >= 2:
                        return self.mock_handler(brief, feedback)
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

                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    choice = data["choices"][0]["message"]["content"]
                    parsed = json.loads(choice)
                    return str(parsed.get("user") or "").strip()
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and retry < max_retries:
                    time.sleep(self.backoff_seconds[retry])
                    continue
                err_body = exc.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"DeepSeek API HTTP {exc.code}: {err_body}") from exc


def fill_utterances(
    generate_dir: Path | str,
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    model: str = DEFAULT_MODEL,
    concurrency: int = 8,
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
            briefs.append(normalize_brief_for_style(json.loads(line)))

    eval_utterances = get_eval_user_utterances()
    template_utterances: dict[str, list[str]] = {}

    # Pre-populate template_utterances from existing cache
    brief_by_id = {b["brief_id"]: b for b in briefs}
    for bid, txt in cache.items():
        if bid in brief_by_id:
            tmpl = brief_by_id[bid].get("template", "unknown")
            template_utterances.setdefault(tmpl, []).append(txt)

    llm = client or DeepSeekClient(endpoint=endpoint, model=model)

    target_briefs = briefs if limit is None else briefs[: int(limit)]
    uncached_by_tmpl: dict[str, list[dict[str, Any]]] = {}

    filled_count = 0
    for b in target_briefs:
        bid = b["brief_id"]
        tmpl = b.get("template", "unknown")
        template_utterances.setdefault(tmpl, [])
        if bid in cache:
            filled_count += 1
        else:
            uncached_by_tmpl.setdefault(tmpl, []).append(b)

    failures: list[dict[str, Any]] = []
    cache_lock = threading.Lock()

    with open(cache_file, "a", encoding="utf-8") as cache_fh:
        def process_template(tmpl_name: str, b_list: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
            t_list = template_utterances[tmpl_name]
            loc_filled = 0
            loc_failures = []
            for b in b_list:
                bid = b["brief_id"]
                feedback = None
                success = False
                final_user = ""

                # 1 initial call + up to 3 retries with feedback (total 4 attempts)
                for attempt in range(4):
                    try:
                        generated = llm.call(b, feedback=feedback)
                    except Exception as exc:
                        feedback = f"Lỗi gọi API: {exc}"
                        continue

                    ok, reason = validate_utterance(generated, b, eval_utterances, t_list)
                    if ok:
                        final_user = generated
                        success = True
                        break
                    else:
                        feedback = reason

                if success:
                    t_list.append(final_user)
                    with cache_lock:
                        cache[bid] = final_user
                        cache_fh.write(json.dumps({"brief_id": bid, "user": final_user}, ensure_ascii=False) + "\n")
                        cache_fh.flush()
                    loc_filled += 1
                else:
                    loc_failures.append({"brief_id": bid, "case_id": b["case_id"], "reason": feedback})
            return loc_filled, loc_failures

        if uncached_by_tmpl:
            max_workers = max(1, min(concurrency, len(uncached_by_tmpl)))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(process_template, tmpl, b_list): tmpl
                    for tmpl, b_list in uncached_by_tmpl.items()
                }
                for fut in concurrent.futures.as_completed(futures):
                    loc_filled, loc_fails = fut.result()
                    filled_count += loc_filled
                    failures.extend(loc_fails)

    failed_count = len(failures)

    # Assemble cases_sft_v1_filled.jsonl
    cases: list[dict[str, Any]] = []
    for line in cases_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))

    case_briefs_map: dict[str, list[dict[str, Any]]] = {}
    for b in briefs:
        case_briefs_map.setdefault(b["case_id"], []).append(b)

    failed_case_ids = {f["case_id"] for f in failures}
    filled_cases = []
    dropped_cases = []
    pending_cases = []

    for c in cases:
        cid = c["id"]
        c_briefs = case_briefs_map.get(cid, [])
        all_cached = bool(c_briefs) and all(b["brief_id"] in cache for b in c_briefs)

        if all_cached:
            c_copy = json.loads(json.dumps(c))
            for b in c_briefs:
                bid = b["brief_id"]
                txt = cache[bid]
                if b.get("suite") == "T11" and "_setup" in bid:
                    idx = int(b.get("setup_msg_index", 0))
                    c_copy["case_setup"]["customer_messages"][idx]["text"] = txt
                else:
                    turn_idx = int(b["turn"]) - 1
                    c_copy["turns"][turn_idx]["user"] = txt

            c_str = json.dumps(c_copy, ensure_ascii=False)
            if "<chờ lời khách" not in c_str:
                filled_cases.append(c_copy)
            else:
                if cid in failed_case_ids:
                    dropped_cases.append(cid)
                else:
                    pending_cases.append(cid)
        else:
            if cid in failed_case_ids:
                dropped_cases.append(cid)
            else:
                pending_cases.append(cid)

    if filled_cases:
        from scripts.sft_dataset import validate_train_set
        validate_train_set(filled_cases)

    with open(filled_file, "w", encoding="utf-8") as f:
        for fc in filled_cases:
            f.write(json.dumps(fc, ensure_ascii=False) + "\n")

    report_lines = [
        "# Báo Cáo Điền Lời Khách Hàng (SFT v1)",
        f"- Tổng số phiếu: **{len(briefs)}**",
        f"- Số câu đã điền thành công: **{filled_count}**",
        f"- Số câu thất bại: **{failed_count}**",
        f"- Số ca hoàn chỉnh: **{len(filled_cases)}**",
        f"- Số ca bị loại (thất bại): **{len(dropped_cases)}**",
        f"- Số ca chưa chạy (pending): **{len(pending_cases)}**",
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
        "pending_cases": len(pending_cases),
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
            concurrency=args.concurrency,
            allow_peak=args.allow_peak,
            limit=args.limit,
        )
        print(f"Filled: {res['filled_count']}/{res['total_briefs']} briefs.")
        print(f"Cases: {res['filled_cases']} complete, {res['dropped_cases']} dropped, {res['pending_cases']} pending.")
        print(f"Report: {res['report_path']}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
