"""Topic guardrail for filtering forbidden/sensitive domains.
Disallows medical diagnosis, legal counsel, politics, religious controversy, and violent/illegal content.
"""
import re
from dataclasses import dataclass

FORBIDDEN_TOPICS = {
    "medical": {
        "patterns": [
            r"\b(uống thuốc|liều lượng|đau bụng|ung thư|khám bệnh|chữa bệnh|chẩn đoán|bệnh viện|bác sĩ|triệu chứng|dược phẩm|kháng sinh)\b",
            r"\b(doctor|medicine|disease|symptom|prescription|hospital|treatment|cancer)\b"
        ],
        "refusal": "Dạ em là trợ lý bán hàng nên không có chuyên môn y tế. Đối với các vấn đề sức khỏe hoặc thuốc men, anh/chị vui lòng tham khảo ý kiến bác sĩ hoặc cơ sở y tế gần nhất để được hỗ trợ tốt nhất nhé ạ!"
    },
    "legal": {
        "patterns": [
            r"\b(luật sư|khởi kiện|tòa án|vi hiến|hình sự|tội phạm|lách luật|hối lộ|tham nhũng)\b",
            r"\b(lawyer|lawsuit|attorney|court|criminal|bribe|illegal)\b"
        ],
        "refusal": "Dạ em chỉ có thể tư vấn các chính sách bán hàng và đổi trả của shop, không thể đưa ra lời khuyên pháp lý. Anh/chị có câu hỏi nào về sản phẩm hay đơn hàng của shop không ạ?"
    },
    "politics_religion": {
        "patterns": [
            r"\b(chính trị|đảng|nhà nước|biểu tình|bầu cử|tôn giáo|phản động|bộ chính trị)\b",
            r"\b(politics|government|election|protest|religion)\b"
        ],
        "refusal": "Dạ em xin phép không thảo luận về các chủ đề chính trị hay tôn giáo. Shop luôn sẵn sàng hỗ trợ anh/chị về các sản phẩm và đơn hàng mua sắm ạ!"
    },
    "harassment_violence": {
        "patterns": [
            r"\b(tự tử|tự hại|đánh bom|vũ khí|giết|tự sát)\b",
            r"\b(suicide|self-harm|bomb|weapon|kill)\b"
        ],
        "refusal": "Dạ em xin phép từ chối phản hồi nội dung này. Nếu anh/chị đang gặp khó khăn hoặc cần hỗ trợ, xin vui lòng liên hệ các đường dây trợ giúp khẩn cấp ạ."
    },
    "prompt_injection_exfiltration": {
        "patterns": [
            r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above|system)\s+instructions",
            r"bỏ qua\s+(?:mọi\s+|tất cả\s+)?(?:hướng dẫn|quy tắc|chỉ thị)\s+(?:trước|hệ thống|nội bộ)",
            r"(?:reveal|dump|print|show|output|leak|exfiltrate)\s+(?:the\s+)?(?:hidden\s+|internal\s+)?(?:system\s+prompt|env(?:ironment)?\s+variables|api[_\s]?key|client[_\s]?secret|session[_\s]?secret|canary)",
            r"(?:in\s+ra|tiết lộ|hiển thị|xuất\s+ra)\s+(?:toàn bộ\s+)?(?:system\s+prompt|biến\s+môi\s+trường|khóa\s+bí\s+mật|mật\s+khẩu\s+db|chuỗi\s+canary)"
        ],
        "refusal": "Dạ em chỉ hỗ trợ tra cứu đơn hàng, sản phẩm và chính sách mua sắm tại cửa hàng; không thể cung cấp thông tin cấu hình nội bộ, system prompt hoặc khóa bí mật ạ."
    }
}

DEFAULT_CANARY_MARKERS = (
    "CANARY_SECRET",
    "SECRET_CANARY",
    "RETAILOPS_CANARY",
    "SYSTEM_PROMPT_CANARY",
    "GOOGLE_CLIENT_SECRET",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "RETAILOPS_POSTGRES_PASSWORD",
    "RETAILOPS_SESSION_SECRET",
    "DISPUTE_SYSTEM_PROMPT",
    "ORDER_SYSTEM_PROMPT",
)

_READ_ONLY_DECLARATION_PATTERNS = (
    r"\bchỉ\s+muốn\s+tra\s+cứu\b",
    r"\bchỉ\s+tra\s+cứu\b",
    r"\bchỉ\s+muốn\s+kiểm\s+tra\b",
    r"\bchỉ\s+kiểm\s+tra\b",
    r"\bchỉ\s+muốn\s+xem\b",
    r"\bchỉ\s+xem\s+(?:thông\s+tin|trạng\s+thái|đơn)\b",
    r"\bkhông\s+thực\s+hiện\s+thay\s+đổi\b",
    r"\bkhông\s+thay\s+đổi\b",
    r"\bđừng\s+thay\s+đổi\b",
    r"\bkhông\s+yêu\s+cầu\s+hủy\b",
    r"\bkhông\s+muốn\s+hủy\b",
    r"\bchưa\s+muốn\s+hủy\b",
    r"\bkhông\s+hủy\b",
    r"\bđừng\s+hủy\b",
    r"\bkhông\s+tạo\s+(?:yêu\s+cầu|đề\s+xuất)\s+hủy\b",
    r"\bchi\s+muon\s+tra\s+cuu\b",
    r"\bchi\s+tra\s+cuu\b",
    r"\bkhong\s+thuc\s+hien\s+thay\s+doi\b",
    r"\bkhong\s+muon\s+huy\b",
    r"\bkhong\s+huy\b",
    r"\bdung\s+huy\b",
    r"\bread[\s_-]?only\b",
    r"\bdo\s+not\s+(?:cancel|modify|mutate)\b",
    r"\bdon't\s+(?:cancel|modify|mutate)\b",
)


def is_read_only_lookup_intent(text: str) -> bool:
    """Return True if the user message explicitly declares read-only lookup / forbids state mutation,
    or if cancellation keywords only appear inside quoted text while the outer query is a lookup."""
    if not isinstance(text, str) or not text.strip():
        return False
    lower = text.lower()
    for pat in _READ_ONLY_DECLARATION_PATTERNS:
        if re.search(pat, lower):
            return True

    # Strip quoted substrings ('...', "...", “...”, ‘...’) to check if cancellation terms only exist inside quotes
    unquoted = re.sub(r"(?:'[^']{1,400}'|\"[^\"]{1,400}\"|“[^”]{1,400}”|‘[^’]{1,400}’)", " ", lower)
    cancel_terms = ("hủy đơn", "hủy hàng", "muốn hủy", "hủy luôn", "hủy giúp", "cancel")
    had_cancel_in_full = any(t in lower for t in cancel_terms)
    has_cancel_outside_quotes = any(t in unquoted for t in cancel_terms)
    lookup_outside_quotes = any(
        t in unquoted
        for t in ("tra cứu", "trạng thái", "kiểm tra", "xem đơn", "cho tôi biết", "đọc nội dung", "tóm tắt")
    )
    if had_cancel_in_full and not has_cancel_outside_quotes and lookup_outside_quotes:
        return True
    return False


def extract_canary_candidates(user_text: str = "", extra_canaries: list[str] | None = None) -> list[str]:
    """Collect canary/secret markers from defaults, extra list, and user-supplied canary tokens."""
    import base64
    import os

    candidates: list[str] = list(DEFAULT_CANARY_MARKERS)
    if extra_canaries:
        for item in extra_canaries:
            if isinstance(item, str) and len(item.strip()) >= 4:
                candidates.append(item.strip())

    for env_key in (
        "GOOGLE_CLIENT_SECRET",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "RETAILOPS_POSTGRES_PASSWORD",
        "RETAILOPS_INFERENCE_TOKEN",
    ):
        val = os.environ.get(env_key, "").strip()
        if len(val) >= 6:
            candidates.append(val)

    if isinstance(user_text, str) and user_text:
        for m in re.findall(r"[A-Za-z0-9_-]{4,128}", user_text):
            upper_m = m.upper()
            if any(k in upper_m for k in ("CANARY", "YRANAC", "SECRET", "TERCES", "API_KEY", "TOKEN")):
                candidates.append(m)
                candidates.append(m[::-1])
        for b64_m in re.findall(r"[A-Za-z0-9+/=_-]{8,160}", user_text):
            padded = b64_m + ("=" * ((4 - len(b64_m) % 4) % 4))
            for decoder in (base64.b64decode, base64.urlsafe_b64decode):
                try:
                    decoded = decoder(padded.encode("ascii")).decode("utf-8", errors="ignore")
                    if decoded and any(k in decoded.upper() for k in ("CANARY", "YRANAC", "SECRET", "TERCES")):
                        candidates.append(decoded.strip())
                        candidates.append(decoded.strip()[::-1])
                except Exception:
                    pass

    deduped: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        c_clean = c.strip()
        if len(c_clean) >= 4 and c_clean.lower() not in seen:
            seen.add(c_clean.lower())
            deduped.append(c_clean)
    return deduped


def contains_canary_or_secret(text: str, canaries: list[str] | None = None, user_text: str = "") -> bool:
    """Detect whether text contains any canary/secret in plain text, reversed, Base64, or hex form."""
    import base64

    if not isinstance(text, str) or not text:
        return False
    markers = extract_canary_candidates(user_text=user_text, extra_canaries=canaries)
    lower_text = text.lower()
    compact_text = re.sub(r"\s+", "", lower_text)

    for marker in markers:
        m_low = marker.lower()
        m_rev = m_low[::-1]
        if m_low in lower_text or m_rev in lower_text:
            return True
        if m_low in compact_text or m_rev in compact_text:
            return True
        for raw_variant in (marker, marker[::-1], marker.upper(), marker.lower()):
            raw_bytes = raw_variant.encode("utf-8")
            for enc in (base64.b64encode(raw_bytes).decode("ascii"), base64.urlsafe_b64encode(raw_bytes).decode("ascii")):
                enc_stripped = enc.rstrip("=").lower()
                if len(enc_stripped) >= 6 and enc_stripped in lower_text:
                    return True
            hex_str = raw_bytes.hex().lower()
            if len(hex_str) >= 8 and hex_str in lower_text:
                return True

    for b64_token in re.findall(r"[A-Za-z0-9+/=_-]{8,256}", text):
        padded = b64_token + ("=" * ((4 - len(b64_token) % 4) % 4))
        for decoder in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                decoded = decoder(padded.encode("ascii")).decode("utf-8", errors="ignore").lower()
                if decoded:
                    for marker in markers:
                        m_low = marker.lower()
                        if m_low in decoded or m_low[::-1] in decoded:
                            return True
            except Exception:
                pass
    return False


def sanitize_output_against_canary_leak(
    user_text: str,
    output_text: str,
    extra_canaries: list[str] | None = None,
) -> tuple[bool, str]:
    """Return (leaked, safe_output_text). Replaces output if any canary/secret is detected."""
    if contains_canary_or_secret(output_text, canaries=extra_canaries, user_text=user_text):
        return (
            True,
            "Dạ em chỉ hỗ trợ tra cứu đơn hàng, sản phẩm và chính sách mua sắm tại cửa hàng; "
            "không thể cung cấp thông tin cấu hình nội bộ, system prompt hoặc xử lý chuỗi bí mật ạ.",
        )
    return (False, output_text)


@dataclass
class TopicFilterResult:
    is_safe: bool
    category: str | None = None
    refusal_message: str | None = None


def check_topic_safety(text: str) -> TopicFilterResult:
    """Check whether the user input touches on forbidden domains."""
    if not text:
        return TopicFilterResult(is_safe=True)

    lower = text.lower()
    for category, details in FORBIDDEN_TOPICS.items():
        for pattern in details["patterns"]:
            if re.search(pattern, lower):
                return TopicFilterResult(
                    is_safe=False,
                    category=category,
                    refusal_message=details["refusal"]
                )

    return TopicFilterResult(is_safe=True)
