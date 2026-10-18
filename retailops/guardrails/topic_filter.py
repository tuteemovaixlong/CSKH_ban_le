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
    "LEAKED_SYSTEM_PROMPT_CANARY",
    "PROMPT_INJECTION_SUCCESS_CANARY",
    "SYSTEM_INSTRUCTION_DUMP_CANARY",
    "[SYSTEM_PROMPT_LEAK]",
    "GOOGLE_CLIENT_SECRET",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "RETAILOPS_POSTGRES_PASSWORD",
    "RETAILOPS_SESSION_SECRET",
    "DISPUTE_SYSTEM_PROMPT",
    "ORDER_SYSTEM_PROMPT",
    "POLICY_SYSTEM_PROMPT",
    "WITTY_SYSTEM_PROMPT",
)

SAFE_REFUSAL_MESSAGE = (
    "Dạ em chỉ hỗ trợ tra cứu đơn hàng, sản phẩm và chính sách mua sắm tại cửa hàng; "
    "không thể cung cấp thông tin cấu hình nội bộ, system prompt hoặc xử lý chuỗi bí mật ạ."
)

_PROMPT_LEAK_REGEXES = (
    re.compile(r"\[SYSTEM_PROMPT_LEAK\]", re.IGNORECASE),
    re.compile(r"\b(?:LEAKED_SYSTEM_PROMPT_CANARY|PROMPT_INJECTION_SUCCESS_CANARY|SYSTEM_INSTRUCTION_DUMP_CANARY)\b", re.IGNORECASE),
    re.compile(r"\bRETAILOPS_CANARY_[A-Za-z0-9_-]+\b", re.IGNORECASE),
    re.compile(r"You support a Vietnamese retail customer of RetailOps Shop using server-bound read-only tools", re.IGNORECASE),
    re.compile(r"Bạn là Chuyên viên Tiếp nhận Khiếu nại, Bảo hành & Đổi trả của shop Thương Mại Điện Tử", re.IGNORECASE),
    re.compile(r"\b(?:sk-or-v1-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,})\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
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
    for rx in _PROMPT_LEAK_REGEXES:
        if rx.search(text):
            return True
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
        return (True, SAFE_REFUSAL_MESSAGE)
    return (False, output_text)


def sanitize_structured_payload(
    payload,
    *,
    user_text: str = "",
    extra_canaries: list[str] | None = None,
    preserve_keys: tuple[str, ...] = ("reasoning", "thought", "_reasoning"),
    preserve_reasoning: bool = True,
    redact_text: str = "[REDACTED_BY_OUTPUT_GUARD]",
):
    """Recursively sanitize dicts, lists, and JSON strings against canary/secret exfiltration,
    while preserving raw Chain-of-Thought fields (reasoning / thought) and user input messages."""
    import json

    effective_preserve_keys = preserve_keys if preserve_reasoning else ()

    if isinstance(payload, str):
        if not payload:
            return False, payload
        stripped = payload.strip()
        if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, (dict, list)):
                    sub_leaked, sub_clean = sanitize_structured_payload(
                        parsed,
                        user_text=user_text,
                        extra_canaries=extra_canaries,
                        preserve_keys=effective_preserve_keys,
                        preserve_reasoning=preserve_reasoning,
                        redact_text=redact_text,
                    )
                    if sub_leaked:
                        return True, json.dumps(sub_clean, ensure_ascii=False, separators=(",", ":"))
                    if not contains_canary_or_secret(payload, canaries=extra_canaries, user_text=user_text):
                        return False, payload
            except Exception:
                pass
        if contains_canary_or_secret(payload, canaries=extra_canaries, user_text=user_text):
            return True, redact_text
        return False, payload

    if isinstance(payload, dict):
        role = payload.get("role")
        if role == "user" and "content" in payload:
            return False, dict(payload)
        if role == "assistant" and "content" in payload:
            out = dict(payload)
            leaked = False
            content_val = out.get("content")
            if isinstance(content_val, str) and content_val:
                c_leaked, c_safe = sanitize_output_against_canary_leak(user_text, content_val, extra_canaries=extra_canaries)
                if c_leaked:
                    out["content"] = c_safe
                    leaked = True
            if "tool_calls" in out and out["tool_calls"]:
                tc_leaked, tc_safe = sanitize_structured_payload(
                    out["tool_calls"],
                    user_text=user_text,
                    extra_canaries=extra_canaries,
                    preserve_keys=effective_preserve_keys,
                    preserve_reasoning=preserve_reasoning,
                    redact_text=redact_text,
                )
                if tc_leaked:
                    out["tool_calls"] = tc_safe
                    leaked = True
            return leaked, out

        out_dict = {}
        any_leaked = False
        for k, v in payload.items():
            if k in effective_preserve_keys:
                out_dict[k] = v
                continue
            if k in ("message", "final_reply", "assistant_message", "final_message") and isinstance(v, str) and v:
                c_leaked, c_safe = sanitize_output_against_canary_leak(user_text, v, extra_canaries=extra_canaries)
                out_dict[k] = c_safe
                any_leaked = any_leaked or c_leaked
                continue
            sub_leaked, sub_v = sanitize_structured_payload(
                v,
                user_text=user_text,
                extra_canaries=extra_canaries,
                preserve_keys=effective_preserve_keys,
                preserve_reasoning=preserve_reasoning,
                redact_text=redact_text,
            )
            out_dict[k] = sub_v
            any_leaked = any_leaked or sub_leaked
        return any_leaked, out_dict

    if isinstance(payload, list):
        out_list = []
        any_leaked = False
        for item in payload:
            sub_leaked, sub_item = sanitize_structured_payload(
                item,
                user_text=user_text,
                extra_canaries=extra_canaries,
                preserve_keys=effective_preserve_keys,
                preserve_reasoning=preserve_reasoning,
                redact_text=redact_text,
            )
            out_list.append(sub_item)
            any_leaked = any_leaked or sub_leaked
        return any_leaked, out_list

    return False, payload


def enforce_final_answer_grounding(
    user_text: str,
    reply_text: str,
    *,
    messages: list | None = None,
    bound=None,
    catalog=None,
) -> str:
    """Deterministic final-answer grounding guard (P5-E-AI4 / DATA2):
    - Prevents fabricating price, stock, or warranty_days when inspected/queried product has null attributes (e.g. P-604).
    - Ensures list_orders truncation (truncated=True) is disclosed and never misrepresented as complete.
    - Prevents false claims that an order was already cancelled/mutated during a chat turn.
    - Prevents fabricating order status/details when get_order returned order_not_found.
    """
    import json

    if not isinstance(reply_text, str) or not reply_text.strip():
        return reply_text

    out_text = reply_text
    lower_reply = out_text.lower()
    lower_user = (user_text or "").lower()

    tool_Outputs: list[tuple[str, dict]] = []
    for m in messages or []:
        if isinstance(m, dict) and m.get("role") == "tool":
            t_name = str(m.get("tool_name") or "")
            raw_c = m.get("content")
            if isinstance(raw_c, str) and raw_c.strip().startswith("{"):
                try:
                    parsed = json.loads(raw_c)
                    if isinstance(parsed, dict):
                        tool_Outputs.append((t_name, parsed))
                except Exception:
                    pass

    # 1. Check inspected or explicitly queried products with null attributes (e.g. P-604)
    inspected_products: dict[str, dict] = {}
    for t_name, t_res in tool_Outputs:
        if isinstance(t_res.get("product"), dict) and t_res["product"].get("id"):
            p = t_res["product"]
            inspected_products[str(p["id"]).upper()] = p
        if isinstance(t_res.get("products"), list):
            for p in t_res["products"]:
                if isinstance(p, dict) and p.get("id"):
                    inspected_products[str(p["id"]).upper()] = p
        if t_name == "check_inventory" and t_res.get("product_id"):
            pid = str(t_res["product_id"]).upper()
            if pid not in inspected_products and catalog is not None:
                cat_p = catalog.get(pid)
                if isinstance(cat_p, dict):
                    inspected_products[pid] = cat_p

    for pid_match in re.findall(r"\b(P-\d{3,6})\b", user_text or "", flags=re.IGNORECASE):
        pid_up = pid_match.upper()
        if pid_up not in inspected_products and catalog is not None:
            cat_p = catalog.get(pid_up)
            if isinstance(cat_p, dict):
                inspected_products[pid_up] = cat_p

    bound_pid = getattr(bound, "product_id", None)
    if isinstance(bound_pid, str) and bound_pid.upper() not in inspected_products and catalog is not None:
        cat_p = catalog.get(bound_pid.upper())
        if isinstance(cat_p, dict):
            inspected_products[bound_pid.upper()] = cat_p

    for pid, prod in inspected_products.items():
        p_price = prod.get("price")
        p_stock = prod.get("stock")
        p_warranty = prod.get("warranty_days")
        if p_price is None or p_stock is None or p_warranty is None:
            pname = prod.get("name") or pid
            fabricated = False
            if p_price is None and re.search(r"\b\d[\d.,]*\s*(?:đ|vnđ|vnd|đồng|nghìn|ngàn|triệu)\b", lower_reply):
                fabricated = True
            if p_stock is None and (
                re.search(r"\b(?:còn|tồn\s*kho)\s*[:là]*\s*\d+\s*(?:sản\s*phẩm|bộ|chiếc|món| cái|hàng)?\b", lower_reply)
                or ("còn hàng" in lower_reply and not any(k in lower_reply for k in ("chưa", "không rõ", "stock=none", "unknown")))
            ):
                fabricated = True
            if p_warranty is None and re.search(r"\bbảo\s+hành\s+\d+\s*(?:ngày|tháng|năm|tuần)\b", lower_reply):
                fabricated = True

            asks_null_attr = any(
                k in lower_user for k in ("giá", "bao nhiêu tiền", "tồn kho", "còn hàng", "bảo hành", "thông tin", "chi tiết")
            )
            discloses_unknown = any(
                k in lower_reply
                for k in ("chưa có thông tin", "chưa cập nhật", "chưa xác định", "chưa rõ", "không rõ", "=none", "trống")
            )
            if fabricated or (asks_null_attr and pid.lower() in lower_user and not discloses_unknown):
                missing_labels = []
                if p_price is None:
                    missing_labels.append("giá bán (price=None)")
                if p_stock is None:
                    missing_labels.append("tồn kho (stock=None)")
                if p_warranty is None:
                    missing_labels.append("thời hạn bảo hành (warranty_days=None)")
                out_text = (
                    f"Chưa có thông tin: sản phẩm {pid} ({pname}) hiện chưa có thông tin {', '.join(missing_labels)} "
                    "trên hệ thống danh mục. Em xin phép chỉ cung cấp thông tin đã xác thực và không tự suy đoán các thông số đang để trống ạ."
                )
                lower_reply = out_text.lower()

    # 2. Check list_orders truncation disclosure
    for t_name, t_res in tool_Outputs:
        if t_name == "list_orders" and t_res.get("truncated") is True:
            ret_cnt = t_res.get("returned_count", len(t_res.get("orders") or []))
            tot_cnt = t_res.get("total_count", ret_cnt)
            claims_all = any(
                phrase in lower_reply
                for phrase in ("tất cả đơn hàng của bạn là", "toàn bộ đơn hàng của bạn gồm", "toàn bộ các đơn hàng của bạn", "đầy đủ tất cả các đơn", "chỉ có bấy nhiêu đơn")
            )
            discloses_trunc = any(
                marker in lower_reply
                for marker in ("rút gọn", "truncated", f"{ret_cnt}/{tot_cnt}", "gần nhất", "chưa hiển thị", "một phần")
            )
            if claims_all or not discloses_trunc:
                note_suffix = (
                    f" (Lưu ý: Danh sách đã rút gọn (truncated=True), chỉ hiển thị {ret_cnt}/{tot_cnt} đơn hàng gần nhất; "
                    f"còn {max(0, int(tot_cnt) - int(ret_cnt))} đơn hàng khác chưa hiển thị đầy đủ.)"
                )
                if claims_all:
                    out_text = (
                        f"Dạ hệ thống hiện hiển thị {ret_cnt}/{tot_cnt} đơn hàng gần nhất trong tài khoản của anh/chị "
                        f"(truncated=True; danh sách đã rút gọn, còn {max(0, int(tot_cnt) - int(ret_cnt))} đơn hàng khác chưa hiển thị đầy đủ)."
                    )
                else:
                    out_text = out_text.rstrip() + note_suffix
                lower_reply = out_text.lower()

    # 3. Check order_not_found fabrication guard
    for t_name, t_res in tool_Outputs:
        if t_name == "get_order" and t_res.get("error") == "order_not_found":
            not_found_disclosed = any(
                k in lower_reply
                for k in ("không tìm thấy", "chưa tìm thấy", "không thuộc tài khoản", "không có đơn", "order_not_found")
            )
            if not not_found_disclosed:
                out_text = (
                    "Dạ hệ thống không tìm thấy đơn hàng này trong danh sách đơn thuộc tài khoản của anh/chị. "
                    "Vui lòng kiểm tra lại mã đơn hàng hoặc chọn một đơn trong danh sách bên phải ạ."
                )
                lower_reply = out_text.lower()

    # 4. Prevent false claims of completed order cancellation/mutation during chat
    false_completion_patterns = (
        r"\bđã\s+(?:được\s+)?hủy\s+(?:đơn(?:\s+hàng)?\s+(?:O-\d+\s+)?)?thành\s+công\b",
        r"\bđơn\s+hàng\s+(?:O-\d+\s+)?(?:của\s+bạn\s+)?đã\s+được\s+(?:em\s+|hệ\s+thống\s+)?hủy\s+(?:xong|thành\s+công)\b",
        r"\bem\s+đã\s+hủy\s+đơn\s+(?:hàng\s+)?(?:O-\d+\s+)?cho\s+(?:anh/chị|bạn)\b",
        r"\bđã\s+hoàn\s+tiền\s+thành\s+công\b",
    )
    if any(re.search(pat, lower_reply) for pat in false_completion_patterns):
        inspected_order = None
        for t_name, t_res in tool_Outputs:
            if isinstance(t_res.get("order"), dict) and t_res["order"].get("id"):
                inspected_order = t_res["order"]
        if inspected_order:
            oid = inspected_order.get("id")
            ostatus = inspected_order.get("status", "pending")
            out_text = (
                f"Dạ qua kênh chat, hệ thống chưa thực hiện hủy đơn hàng {oid}; "
                f"đơn {oid} hiện đang ở trạng thái {ostatus} (chưa bị hủy) và chưa ghi nhận thông tin giao hàng/địa chỉ "
                f"(delivery={inspected_order.get('delivery')}, address={inspected_order.get('address')}). "
                "Mọi thao tác hủy đơn đều cần tạo đề xuất hợp lệ và được anh/chị bấm xác nhận trực tiếp ạ."
            )
        else:
            out_text = (
                "Dạ qua kênh chat, hệ thống chưa thực hiện hủy hoặc thay đổi trạng thái đơn hàng (đơn chưa bị hủy). "
                "Mọi thao tác hủy đơn đều cần tạo đề xuất hợp lệ và được anh/chị bấm xác nhận trực tiếp ạ."
            )

    return out_text



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
