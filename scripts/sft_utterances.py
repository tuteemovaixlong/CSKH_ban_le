"""Customer utterance generator (OpenAI-compatible chat API) with code validation and deduplication (sft_v1).

W6.7.0 Part A; writer options added for Muse Glimmer (§34 W6.7-D1).
CLI:
  # DeepSeek (đối chứng / viết thay phiếu Glimmer từ chối)
  python scripts/sft_utterances.py fill --dir <thư mục generate> \\
      --endpoint https://api.deepseek.com/chat/completions \\
      --model deepseek-flash --writer-label deepseek-flash --concurrency 8 [--allow-peak] [--limit N]

  # Muse Glimmer tự chạy bằng vLLM trên Colab (không cần khóa)
  python scripts/sft_utterances.py fill --dir <thư mục generate> \\
      --endpoint http://127.0.0.1:8000/v1/chat/completions --model <tên served> \\
      --no-auth --system-extra "Reasoning strength: low" \\
      --writer-label muse-glimmer-30b --timeout 180 --concurrency 32

Mỗi câu trong utterances_cache.jsonl mang nhãn người viết (`writer`, `model`);
ca đã điền mang `meta.utterance_writers` (chính sách sử dụng Glimmer mục 3.5:
đầu ra phải ghi rõ là do AI sinh). Chạy lại trên cùng thư mục chỉ điền phiếu
còn thiếu, nên có thể chạy Glimmer trước rồi DeepSeek viết thay phần còn lại.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import inspect
import json
import os
import re
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
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
DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 30.0
UNLABELED_WRITER = "chua_ghi_nhan"

VIETNAMESE_ACCENTS_RE = re.compile(
    r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    r"ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ]"
)


# Mã định danh trong dữ liệu sft_v1: SIM-O-50001, SIM-O-ST-502, SIM-C-1234, P-501, VCH-VIP-500K-1, REF-TEST-AUTO-…
# Lời khách chỉ được nhắc mã có trong phiếu (kể cả lượt trước, chuỗi chèn lệnh) — mã tự bịa làm ca lệch kho dữ liệu.
CODE_RE = re.compile(r"\b[A-Za-z]{1,4}(?:-[A-Za-z0-9]+){1,5}\b")


def extract_codes(text: str) -> set[str]:
    return {m.upper() for m in CODE_RE.findall(str(text or "")) if any(ch.isdigit() for ch in m)}


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


# Giờ cao điểm DeepSeek (giá ×2), theo https://api-docs.deepseek.com/quick_start/pricing (kiểm 2026-11-17):
# "01:00 - 04:00 and 06:00 - 10:00 UTC, Monday through Friday, excluding Chinese public holidays"
# = 08:00–11:00 và 13:00–17:00 giờ VN (UTC+7). Ngày lễ Trung Quốc không tính ở đây (chặn thừa, an toàn).
PEAK_WINDOWS_VN = ((8, 11), (13, 17))
PEAK_WINDOWS_TEXT = "08:00–11:00 và 13:00–17:00 thứ Hai–thứ Sáu, giờ VN"


def is_peak_hour(now_dt: datetime | None = None) -> bool:
    tz_vn = timezone(timedelta(hours=7))
    dt = now_dt or datetime.now(tz_vn)
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz_vn)
    return dt.weekday() < 5 and any(start <= dt.hour < end for start, end in PEAK_WINDOWS_VN)


def is_deepseek_endpoint(endpoint: str) -> bool:
    """Giờ cao điểm chỉ áp cho API DeepSeek; vLLM tự chạy (Glimmer) không bị chặn."""
    host = (urllib.parse.urlsplit(str(endpoint or "")).hostname or "").lower()
    return host == "deepseek.com" or host.endswith(".deepseek.com")


_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$")


def parse_user_json(content: Any) -> str:
    """Lấy trường "user" từ nội dung model trả về.

    Chấp nhận JSON thuần, JSON trong hàng rào ```json, hoặc có chữ thừa quanh
    đối tượng JSON đầu tiên (model tự chạy không phải lúc nào cũng tôn trọng
    JSON mode). Nội dung rỗng/không có đối tượng hợp lệ → ValueError để vòng
    thử lại gửi phản hồi lỗi.
    """
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Model trả về nội dung rỗng (có thể đã dùng hết token cho phần suy luận)")
    text = _CODE_FENCE_RE.sub("", content.strip()).strip()
    candidates = [text]
    start = text.find("{")
    if start > 0:
        candidates.append(text[start:])
    decoder = json.JSONDecoder()
    for cand in candidates:
        try:
            obj, _ = decoder.raw_decode(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "user" in obj:
            return str(obj.get("user") or "").strip()
    raise ValueError('Không đọc được đối tượng JSON dạng {"user": "..."} từ câu trả lời')


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


def brief_conflicts(brief: dict[str, Any]) -> list[str]:
    """Phiếu tự mâu thuẫn: cụm cấm nằm trong chính cụm bắt buộc / chuỗi chèn lệnh (so như bộ kiểm, sau chuẩn hóa giọng).

    Phiếu như vậy không người viết nào làm đạt; sft_cases.generate gọi hàm này để dừng sớm.
    """
    b = normalize_brief_for_style(brief)
    required = list(b.get("must_include", [])) + ([b["injection"]] if b.get("injection") else [])
    out = []
    for n in b.get("must_not_include", []):
        cn = eval_regrade.v2(n)
        for m in required:
            if cn and cn in eval_regrade.v2(m):
                out.append(f"{brief.get('brief_id')}: cụm cấm {n!r} nằm trong cụm bắt buộc {m!r}")
    return out


def validate_utterance(
    user_text: str,
    brief: dict[str, Any],
    eval_utterances: set[str],
    template_utterances: list[str],
) -> tuple[bool, str]:
    txt = str(user_text or "").strip()
    if not txt:
        return False, "Câu trả lời rỗng"

    if brief.get('rail_pass'):
        from retailops.workflow.safety import safety_gate
        rail = safety_gate(txt)
        if rail is not None:
            return False, f"Bị rào an toàn chặn ({rail.rail})"

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

    # 1c. Không có mã (đơn/khách/sản phẩm/voucher) nào ngoài các mã phiếu đã cho
    allowed_codes = extract_codes(json.dumps(brief, ensure_ascii=False))
    for code in sorted(extract_codes(txt) - allowed_codes):
        return False, f"Có mã '{code}' không có trong phiếu (không được tự bịa mã đơn/sản phẩm)"

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


class ChatClient:
    """Client cho API chat kiểu OpenAI (DeepSeek, hoặc vLLM tự chạy cho Muse Glimmer).

    - `api_key_env`: tên biến môi trường chứa khóa; `None` = không gửi khóa
      (vLLM cục bộ). Khóa chỉ đọc từ môi trường, không nhận qua dòng lệnh.
    - `system_extra`: dòng thêm vào đầu system prompt (vd. "Reasoning strength: low").
    - `json_mode`: gửi `response_format={"type": "json_object"}`; tắt nếu server
      không hỗ trợ. Câu trả lời luôn được đọc bằng `parse_user_json`.
    - `writer_label`: nhãn người viết ghi vào cache (mặc định = tên model).
    """

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        mock_handler: Callable[..., str] | None = None,
        backoff_seconds: tuple[float, ...] = (1.0, 2.0, 4.0),
        *,
        api_key_env: str | None = DEFAULT_API_KEY_ENV,
        system_extra: str | None = None,
        json_mode: bool = True,
        writer_label: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.api_key_env = api_key_env or None
        if api_key:
            self.api_key = api_key
        elif self.api_key_env:
            self.api_key = os.environ.get(self.api_key_env, "")
        else:
            self.api_key = ""
        self.mock_handler = mock_handler
        self.backoff_seconds = backoff_seconds
        self.system_extra = (system_extra or "").strip() or None
        self.json_mode = json_mode
        self.writer_label = (writer_label or "").strip() or str(model)
        self.timeout = float(timeout)

    def build_messages(self, brief: dict[str, Any], feedback: str | None = None) -> list[dict[str, str]]:
        """Một tin system ở đầu + một tin user.

        Phản hồi lỗi của lần thử trước được gộp vào tin user (không thêm tin
        system thứ hai giữa hội thoại) vì nhiều chat template của model tự chạy
        chỉ nhận system ở vị trí đầu và đòi user/assistant xen kẽ.
        """
        system = SYSTEM_PROMPT if not self.system_extra else f"{self.system_extra}\n\n{SYSTEM_PROMPT}"
        user_content = json.dumps(brief, ensure_ascii=False, indent=2)
        user_msg = f"Hãy viết lời khách cho phiếu sau:\n{user_content}"
        if feedback:
            user_msg += f"\n\nLẦN THỬ TRƯỚC BỊ LỖI: {feedback}. Hãy sửa lại đúng các quy tắc."
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]

    def build_payload(self, brief: dict[str, Any], feedback: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self.build_messages(brief, feedback),
            "temperature": 1.0,
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def call(self, brief: dict[str, Any], feedback: str | None = None) -> str:
        max_retries = len(self.backoff_seconds)
        for retry in range(max_retries + 1):
            try:
                if self.mock_handler is not None:
                    sig = inspect.signature(self.mock_handler)
                    if len(sig.parameters) >= 2:
                        return self.mock_handler(brief, feedback)
                    return self.mock_handler(brief)

                if self.api_key_env and not self.api_key:
                    raise ValueError(
                        f"Thiếu biến môi trường {self.api_key_env} để gọi {self.endpoint} "
                        "(endpoint cục bộ không cần khóa thì dùng --no-auth)."
                    )

                payload = self.build_payload(brief, feedback)
                headers = {"Content-Type": "application/json"}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"

                req = urllib.request.Request(
                    self.endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )

                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    message = data["choices"][0]["message"]
                    return parse_user_json(message.get("content"))
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and retry < max_retries:
                    time.sleep(self.backoff_seconds[retry])
                    continue
                err_body = exc.read().decode("utf-8", errors="ignore") if exc.fp is not None else ""
                raise RuntimeError(f"API HTTP {exc.code} ({self.endpoint}): {err_body[:500]}") from exc
        raise RuntimeError("Hết lượt thử lại")


# Tên cũ giữ lại cho mã/test đã dùng (W6.7.0 phần A).
DeepSeekClient = ChatClient


def fill_utterances(
    generate_dir: Path | str,
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    model: str = DEFAULT_MODEL,
    concurrency: int = 8,
    allow_peak: bool = False,
    limit: int | None = None,
    client: ChatClient | None = None,
    now_fn: Callable[[], datetime] | None = None,
    api_key_env: str | None = DEFAULT_API_KEY_ENV,
    system_extra: str | None = None,
    json_mode: bool = True,
    writer_label: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    gen_dir = Path(generate_dir).resolve()
    briefs_file = gen_dir / "briefs_sft_v1.jsonl"
    cases_file = gen_dir / "cases_sft_v1.jsonl"
    cache_file = gen_dir / "utterances_cache.jsonl"
    filled_file = gen_dir / "cases_sft_v1_filled.jsonl"
    report_file = gen_dir / "utterances_report.md"

    assert briefs_file.is_file(), f"Briefs file not found: {briefs_file}"
    assert cases_file.is_file(), f"Cases file not found: {cases_file}"

    llm = client or ChatClient(
        endpoint=endpoint,
        model=model,
        api_key_env=api_key_env,
        system_extra=system_extra,
        json_mode=json_mode,
        writer_label=writer_label,
        timeout=timeout,
    )
    writer = getattr(llm, "writer_label", None) or str(getattr(llm, "model", "") or UNLABELED_WRITER)
    writer_model = str(getattr(llm, "model", "") or "")

    # Peak hour gate (chỉ khi gọi API DeepSeek)
    current_dt = now_fn() if now_fn else None
    if not allow_peak and is_deepseek_endpoint(getattr(llm, "endpoint", "")) and is_peak_hour(current_dt):
        raise RuntimeError(
            f"Đang trong giờ cao điểm của DeepSeek ({PEAK_WINDOWS_TEXT}). "
            "Dừng để tránh lỗi nghẽn và chi phí cao, trừ khi truyền flag --allow-peak."
        )

    # Load cache if exists (dòng cũ chưa có nhãn → UNLABELED_WRITER)
    cache: dict[str, str] = {}
    cache_writer: dict[str, str] = {}
    if cache_file.is_file():
        for line in cache_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                if item.get("brief_id") and item.get("user"):
                    cache[item["brief_id"]] = item["user"]
                    cache_writer[item["brief_id"]] = str(item.get("writer") or UNLABELED_WRITER)

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

    with open(cache_file, "a", encoding="utf-8", newline="\n") as cache_fh:
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
                        cache_writer[bid] = writer
                        record = {"brief_id": bid, "user": final_user, "writer": writer, "model": writer_model}
                        cache_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
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
            c_copy.setdefault("meta", {})["utterance_writers"] = sorted(
                {cache_writer.get(b["brief_id"], UNLABELED_WRITER) for b in c_briefs}
            )

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

    with open(filled_file, "w", encoding="utf-8", newline="\n") as f:
        for fc in filled_cases:
            f.write(json.dumps(fc, ensure_ascii=False) + "\n")

    writer_counts: dict[str, int] = {}
    for b in briefs:
        if b["brief_id"] in cache:
            w = cache_writer.get(b["brief_id"], UNLABELED_WRITER)
            writer_counts[w] = writer_counts.get(w, 0) + 1

    report_lines = [
        "# Báo Cáo Điền Lời Khách Hàng (SFT v1)",
        f"- Người viết lần chạy này: **{writer}** (model `{writer_model}`)",
        f"- Tổng số phiếu: **{len(briefs)}**",
        f"- Số câu đã điền thành công: **{filled_count}**",
        f"- Số câu thất bại: **{failed_count}**",
        f"- Số ca hoàn chỉnh: **{len(filled_cases)}**",
        f"- Số ca bị loại (thất bại): **{len(dropped_cases)}**",
        f"- Số ca chưa chạy (pending): **{len(pending_cases)}**",
        "",
        "## Số câu theo người viết (toàn bộ cache, câu do AI sinh)",
    ]
    for w in sorted(writer_counts):
        report_lines.append(f"- `{w}`: {writer_counts[w]}")
    if not writer_counts:
        report_lines.append("Chưa có câu nào.")
    report_lines += ["", "## Danh sách ca thất bại (nếu có)"]
    if failures:
        for fail in failures:
            report_lines.append(f"- `{fail['brief_id']}` ({fail['case_id']}): {fail['reason']}")
    else:
        report_lines.append("Không có ca nào thất bại.")

    report_file.write_text("\n".join(report_lines) + "\n", encoding="utf-8", newline="\n")

    return {
        "total_briefs": len(briefs),
        "filled_count": filled_count,
        "failed_count": failed_count,
        "filled_cases": len(filled_cases),
        "dropped_cases": len(dropped_cases),
        "pending_cases": len(pending_cases),
        "writer": writer,
        "writer_counts": writer_counts,
        "failed_brief_ids": [f["brief_id"] for f in failures],
        "report_path": report_file,
    }


def verify_utterances(generate_dir: Path | str) -> dict[str, Any]:
    """Kiểm lại cache và tệp ca đã điền theo ĐÚNG bộ phiếu trong thư mục (chạy sau fill, trước khi sinh quỹ đạo).

    Bắt: câu trong cache thuộc phiếu không có ở đây hoặc viết cho phiếu khác nội dung (cache lấy từ lần sinh khác),
    câu không còn qua luật (mã bắt buộc, mã lạ, cụm cấm, giọng, độ dài, trùng ca đo), ca đã điền lệch cache,
    ca còn chỗ trống hoặc thiếu nhãn người viết. Không kiểm trùng trong khung (fill đã kiểm theo thứ tự viết).
    """
    gen_dir = Path(generate_dir).resolve()
    briefs = {}
    for line in (gen_dir / "briefs_sft_v1.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            b = normalize_brief_for_style(json.loads(line))
            briefs[b["brief_id"]] = b
    cache: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    cache_file = gen_dir / "utterances_cache.jsonl"
    if cache_file.is_file():
        for n, line in enumerate(cache_file.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            bid = rec.get("brief_id")
            if bid in cache and cache[bid].get("user") != rec.get("user"):
                problems.append(f"cache dòng {n}: {bid} có hai câu khác nhau")
            cache[bid] = rec

    eval_utterances = get_eval_user_utterances()
    for bid, rec in cache.items():
        if bid not in briefs:
            problems.append(f"{bid}: có trong cache nhưng không có trong briefs_sft_v1.jsonl (cache từ lần sinh khác?)")
            continue
        ok, reason = validate_utterance(rec.get("user", ""), briefs[bid], eval_utterances, [])
        if not ok:
            problems.append(f"{bid}: {reason}")

    filled_file = gen_dir / "cases_sft_v1_filled.jsonl"
    filled_cases = 0
    if filled_file.is_file():
        by_case: dict[str, list[dict[str, Any]]] = {}
        for b in briefs.values():
            by_case.setdefault(b["case_id"], []).append(b)
        for line in filled_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            filled_cases += 1
            cid = case["id"]
            if case.get("fixture") != "sft_v1":
                problems.append(f"{cid}: fixture {case.get('fixture')!r} khác 'sft_v1'")
            if "<chờ lời khách" in json.dumps(case, ensure_ascii=False):
                problems.append(f"{cid}: còn chỗ trống chưa điền")
            writers = set()
            for b in by_case.get(cid, []):
                rec = cache.get(b["brief_id"])
                if rec is None:
                    problems.append(f"{cid}: phiếu {b['brief_id']} không có trong cache")
                    continue
                writers.add(str(rec.get("writer") or UNLABELED_WRITER))
                if b.get("suite") == "T11" and "_setup" in b["brief_id"]:
                    got = case["case_setup"]["customer_messages"][int(b.get("setup_msg_index", 0))]["text"]
                else:
                    got = case["turns"][int(b["turn"]) - 1]["user"]
                if got != rec.get("user"):
                    problems.append(f"{cid}: câu ở {b['brief_id']} khác câu trong cache")
            if sorted(writers) != list((case.get("meta") or {}).get("utterance_writers") or []):
                problems.append(f"{cid}: meta.utterance_writers {case.get('meta', {}).get('utterance_writers')} ≠ cache {sorted(writers)}")

    return {
        "briefs": len(briefs),
        "cached": sum(1 for b in cache if b in briefs),
        "filled_cases": filled_cases,
        "problems": problems,
    }


def _brief_index(path: Path):
    result, raw = {}, {}
    for line in path.read_bytes().splitlines(keepends=True):
        if line.strip():
            row = json.loads(line)
            bid = row['brief_id']
            if bid in result:
                raise ValueError(f'Phiếu bị trùng brief_id: {bid}')
            result[bid] = row
            raw[bid] = line
    return result, raw


def _cache_changes(generate_dir: Path, old_briefs: Path):
    old, old_raw = _brief_index(old_briefs)
    current, current_raw = _brief_index(generate_dir / 'briefs_sft_v1.jsonl')
    changed = set()
    injections = {}
    t11_email_only = {}
    for bid in old.keys() | current.keys():
        before, after = old.get(bid), current.get(bid)
        if before == after:
            continue
        if before and after:
            keys = {k for k in before.keys() | after.keys()
                    if k not in before or k not in after or before[k] != after[k]}
            if keys == {'injection'} and all(isinstance(b.get('injection'), str) and b['injection']
                                               for b in (before, after)):
                injections[bid] = (before['injection'], after['injection'])
                continue
            # Quyết định owner W6.7.1: chỉ giữ đệm t11 nếu đúng một email cấm được đổi,
            # toàn bộ byte khác của phiếu v3 giữ nguyên; không mở rộng sang thay đổi khác.
            if (keys == {'must_not_include'} and before.get('template') == 't11_pdf_email_la'
                    and after.get('template') == 't11_pdf_email_la'):
                forbidden = before.get('must_not_include', [])
                emails = [x for x in forbidden if isinstance(x, str) and re.fullmatch(
                    r'ketoan-uynhiem-\d+@fake-retailops-mail\.com', x)]
                if len(emails) == 1:
                    previous = emails[0]
                    following = previous.replace('@fake-retailops-mail.com', '@thanhtoan-ncc.example')
                    expected = [following if x == previous else x for x in forbidden]
                    if (forbidden.count(previous) == 1 and after['must_not_include'] == expected
                            and old_raw[bid].count(previous.encode('utf-8')) == 1
                            and old_raw[bid].replace(previous.encode('utf-8'), following.encode('utf-8'), 1)
                            == current_raw[bid]):
                        t11_email_only[bid] = (previous, following)
                        continue
        changed.add(bid)
    return changed, injections, t11_email_only


def _replace_cache(path: Path, data: bytes) -> None:
    # Chỉ thay tệp sau khi kiểm hết các dòng; lỗi ở cuối không được để cache đổi dở dang.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.cache-', delete=False) as fh:
            tmp_path = Path(fh.name)
            fh.write(data)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()


def drop_cache(generate_dir: Path | str, old_briefs: Path | str) -> dict[str, Any]:
    """Xóa đệm của phiếu đổi, giữ nguyên từng byte dòng khác và nhóm chỉ đổi injection."""
    directory = Path(generate_dir)
    changed, _, t11_email_only = _cache_changes(directory, Path(old_briefs))
    path = directory / 'utterances_cache.jsonl'
    data = path.read_bytes()
    kept, removed, retained_t11 = [], [], []
    records = [(line, json.loads(line) if line.strip() else {}) for line in data.splitlines(keepends=True)]
    for _, row in records:
        bid = row.get('brief_id')
        if bid in t11_email_only:
            text = row.get('user')
            if not isinstance(text, str) or any(
                    token.casefold() in text.casefold() for token in (*t11_email_only[bid], 'retailops-mail')):
                changed.add(bid)  # Có một dòng nhiễm thì xóa mọi dòng đệm của phiếu đó.
    for line, row in records:
        bid = row.get('brief_id')
        if bid in changed:
            removed.append(bid)
        else:
            kept.append(line)
            if bid in t11_email_only:
                retained_t11.append(bid)
    # Không ghi đè bản sao lưu của lần trước: owner cần giữ được bộ đệm trước khi xóa.
    backup = directory / 'utterances_cache.before_drop.jsonl'
    with backup.open('xb') as fh:
        fh.write(data)
    if removed:
        _replace_cache(path, b''.join(kept))
    return {'removed': len(removed), 'brief_ids': sorted(set(removed)), 'backup': str(backup),
            'retained_t11': len(retained_t11), 'retained_t11_brief_ids': sorted(set(retained_t11))}


def migrate_injection(generate_dir: Path | str, old_briefs: Path | str) -> dict[str, Any]:
    """Thay đúng một chuỗi injection, giữ nhãn tác giả/model; hoàn toàn offline."""
    directory = Path(generate_dir)
    _, injections, _ = _cache_changes(directory, Path(old_briefs))
    path = directory / 'utterances_cache.jsonl'
    lines, migrated = [], []
    for line in path.read_bytes().splitlines(keepends=True):
        row = json.loads(line) if line.strip() else {}
        bid = row.get('brief_id')
        if bid in injections:
            before, after = injections[bid]
            text = row.get('user')
            count = text.count(before) if isinstance(text, str) else 0
            if count != 1:
                raise ValueError(f'{bid}: injection cũ xuất hiện {count} lần, cần đúng 1 lần')
            row['user'] = text.replace(before, after, 1)
            row['migrated'] = 'injection'
            line = (json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8')
            migrated.append(bid)
        lines.append(line)
    if migrated:
        _replace_cache(path, b''.join(lines))
    return {'migrated': len(migrated), 'brief_ids': sorted(set(migrated))}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and validate customer utterances")
    subparsers = parser.add_subparsers(dest="command")

    for command in ('drop-cache', 'migrate-injection'):
        cache_parser = subparsers.add_parser(command, help='Bảo trì đệm offline khi phiếu đổi')
        cache_parser.add_argument('--dir', required=True, help='Thư mục phiếu hiện tại và bản sao bộ đệm')
        cache_parser.add_argument('--old-briefs', required=True, help='Phiếu v3 trước khi sửa khung')

    p_verify = subparsers.add_parser("verify", help="Re-check cache and filled cases against this directory's briefs")
    p_verify.add_argument("--dir", required=True, help="Generation directory containing briefs, cache and filled cases")

    p_fill = subparsers.add_parser("fill", help="Fill customer utterances from briefs")
    p_fill.add_argument("--dir", required=True, help="Generation directory containing briefs and cases")
    p_fill.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="OpenAI-compatible chat completions endpoint")
    p_fill.add_argument("--model", default=DEFAULT_MODEL, help="Model name sent in the request")
    p_fill.add_argument("--concurrency", type=int, default=8, help="Concurrency level (templates in parallel)")
    p_fill.add_argument("--allow-peak", action="store_true", help="Allow running DeepSeek during peak hours")
    p_fill.add_argument("--limit", type=int, default=None, help="Limit number of briefs to process")
    auth = p_fill.add_mutually_exclusive_group()
    auth.add_argument(
        "--api-key-env",
        default=DEFAULT_API_KEY_ENV,
        help=f"Name of the environment variable holding the API key (default {DEFAULT_API_KEY_ENV})",
    )
    auth.add_argument("--no-auth", action="store_true", help="Send no API key (self-hosted vLLM)")
    p_fill.add_argument(
        "--system-extra",
        default=None,
        help='Extra line prepended to the system prompt, e.g. "Reasoning strength: low" for Muse Glimmer',
    )
    p_fill.add_argument("--no-json-mode", action="store_true", help="Do not send response_format=json_object")
    p_fill.add_argument(
        "--writer-label",
        default=None,
        help="Writer label stored with every utterance (default: model name), e.g. muse-glimmer-30b",
    )
    p_fill.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="HTTP timeout in seconds per request"
    )

    args = parser.parse_args()

    if args.command in ('drop-cache', 'migrate-injection'):
        operation = drop_cache if args.command == 'drop-cache' else migrate_injection
        try:
            result = operation(args.dir, args.old_briefs)
        except (ValueError, OSError) as exc:
            print(f'Lỗi: {exc}', file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "verify":
        res = verify_utterances(args.dir)
        print(f"Verify: {res['cached']}/{res['briefs']} briefs cached, {res['filled_cases']} filled cases, "
              f"{len(res['problems'])} problems.")
        for p in res["problems"][:50]:
            print("  -", p)
        return 1 if res["problems"] else 0

    if args.command == "fill":
        res = fill_utterances(
            args.dir,
            endpoint=args.endpoint,
            model=args.model,
            concurrency=args.concurrency,
            allow_peak=args.allow_peak,
            limit=args.limit,
            api_key_env=None if args.no_auth else args.api_key_env,
            system_extra=args.system_extra,
            json_mode=not args.no_json_mode,
            writer_label=args.writer_label,
            timeout=args.timeout,
        )
        print(f"Writer: {res['writer']}")
        print(f"Filled: {res['filled_count']}/{res['total_briefs']} briefs.")
        print(f"Cases: {res['filled_cases']} complete, {res['dropped_cases']} dropped, {res['pending_cases']} pending.")
        print(f"Report: {res['report_path']}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
