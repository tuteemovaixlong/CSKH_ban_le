"""Supervisor & Intent Router Node for Multi-Agent RetailOps.
Performs fast guardrails triage, sentiment detection, and routes queries to specialized workers.
"""
import copy
import re
from typing import Any
from retailops_conversation import normalize

from agent_protocol import classify_user_text
from retailops.guardrails.sentiment import analyze_sentiment
from retailops.guardrails.topic_filter import is_read_only_lookup_intent
from retailops.workflow.state import MultiAgentState, WorkerType
from retailops.workflow.safety import HUMAN_REPLY, HUMAN_REQUEST_KEYWORDS, SafetyVerdict, hours_inquiry_text, safety_gate

# The rails shared with the customer agent live in retailops.workflow.safety; the two phrases below are
# legacy-only routing hints that the agent-first loop deliberately does not carry.
HUMAN_ESCALATION_KEYWORDS = [*HUMAN_REQUEST_KEYWORDS, "đổi giúp đc ko shop", "đổi giúp được không shop"]

ORDER_KEYWORDS = [
    "đơn hàng", "mã đơn", "tra cứu đơn", "kiểm tra đơn", "check đơn", "xem đơn", "tra đơn",
    "giao đến đâu", "bao giờ nhận", "vận chuyển", "tracking", "giao hàng", "shipper", "bưu tá",
    "tài xế", "báo ảo", "giao ảo", "giao thất bại", "bom hàng", "chuyển hoàn", "kẹt kho",
    "nghẽn kho", "mega soc", "củ chi", "bắc ninh", "kho tổng", "đứng yên", "xuất kho",
    "chậm trễ", "lâu quá", "sao lâu thế", "chưa nhận được", "chưa thấy giao", "không gọi",
    "giao lại", "chưa giao", "đang ở đâu", "ở kho nào", "giao chưa", "đơn shopee", "shopee",
    "ghtk", "ghn", "spx", "viettel post", "j&t", "đơn em", "đơn này", "đơn tôi", "đơn mình",
    "đơn của", "đơn bên", "đơn kẹt", "đơn báo", "đơn bị", "đơn cũ", "mã đây", "đơn mega sale"
]

PRODUCT_OR_STORE_KEYWORDS = [
    "sản phẩm", "quần tây", "áo sơ mi", "giày lười", "áo thun", "váy", "đầm",
    "quần áo", "shop tên gì", "tên shop", "shop tên", "cửa hàng tên gì", "tên cửa hàng",
    "shop bán gì", "cửa hàng bán gì", "shop có gì", "cửa hàng có gì", "mặt hàng"
]

DISPUTE_KEYWORDS = [
    "hủy đơn", "hủy hàng", "muốn hủy", "hủy luôn", "hoàn tiền", "trả hàng", "hàng lỗi",
    "hàng em lỗi", "rách", "vỡ", "bể", "sai hàng", "đổi hàng", "cancel",
    "đổi size", "không vừa", "chật", "rộng", "đổi sang size", "bung chỉ", "kẹt khóa",
    "hỏng khóa", "lỗi chỉ", "đổi 1-1", "đổi mới", "bị lỗi", "móp", "trầy", "sai màu",
    "sai mẫu", "lỗi nặng", "kích chân", "muốn đổi", "cần đổi", "đổi 2 chiều", "đổi tận nhà",
    "còn size", "đổi áo", "đổi quần", "đổi mẫu", "đổi đơn này", "đổi sang", "đổi size mới"
]

POLICY_KEYWORDS = [
    "chính sách", "quy định", "hướng dẫn", "điều khoản", "freeship", "bảo hành",
    "phí ship", "vận chuyển bao nhiêu", "hình thức thanh toán", "khuyến mãi", "voucher",
    "tổng đài", "hotline", "khung giờ", "mấy giờ", "quy trình", "điều kiện", "áp dụng cho",
    "trong bao lâu", "thời hạn", "mất phí", "ai trả", "tính từ lúc nào",
    "có được xem là", "được xem là lỗi kỹ thuật", "lỗi kỹ thuật để đổi", "đã giặt rồi thì còn",
    "bảo hành 90 ngày có cover", "bảo hành 90 ngày", "có đc bảo hành", "đổi mới ko ạ", "đổi mới ko",
    "đổi mới 1-1 ko", "hỗ trợ đổi mới 1-1", "voucher đền bù", "nhận kiểu gì",
    "đổi size trong 15 ngày", "đổi size quá 15 ngày",
    "cần giấy tờ gì", "cần hóa đơn", "làm mất bill", "có cần hóa đơn", "có cần mã đơn",
    "áp dụng cho những lỗi nào", "thế nào để được bảo hành", "làm sao để được bảo hành",
    "tư vấn chính sách"
]


def run_supervisor(state: MultiAgentState) -> MultiAgentState:
    """Supervise conversation, evaluate guardrails, and decide next worker node."""
    state = copy.deepcopy(state)
    last_user_msg = next((m["content"] for m in reversed(state["messages"]) if m["role"] == "user"), "")
    lower_msg = last_user_msg.lower()
    folded = normalize(last_user_msg)
    plural_orders = bool(re.search(r'\b(cac don|tat ca (cac )?don|liet ke don|kiem tra don)\b', folded))

    # Both customer entry points use the same ordered safety rails.
    sentiment_result = analyze_sentiment(last_user_msg)
    state["sentiment"] = sentiment_result.sentiment
    state["strict_mode"] = sentiment_result.strict_mode_required
    read_only_lookup = is_read_only_lookup_intent(last_user_msg)
    is_hours_inquiry = hours_inquiry_text(last_user_msg)
    verdict = safety_gate(last_user_msg)
    # Preserve the two legacy-only exchange routing hints.
    if verdict is None and not read_only_lookup and any(
            kw in lower_msg for kw in ("đổi giúp đc ko shop", "đổi giúp được không shop")):
        verdict = SafetyVerdict("human_request", HUMAN_REPLY,
            human_reason="SOP 6: Khách hàng bấm nút hoặc yêu cầu gặp trực tiếp nhân viên tư vấn")
    if verdict is not None:
        forbidden = verdict.rail == "forbidden_topic"
        state["intent"] = "forbidden_topic" if forbidden else "dispute_complaint"
        state["next_worker"] = "direct_response" if forbidden else "human_escalation"
        if verdict.human_reason:
            state["requires_human"] = True
            state["human_reason"] = verdict.human_reason
        state["strict_mode"] = verdict.strict_mode or state["strict_mode"]
        reply = {"role": "assistant", "content": verdict.reply}
        state["messages"].append(reply)
        state["fresh"].append(reply)
        state["complete"] = True
        history_tag = {"forbidden_topic": "forbidden_refusal", "extreme_rage": "escalate_extreme_rage",
                       "human_request": "escalate_human"}[verdict.rail]
        state["subagent_history"].append("supervisor:" + history_tag)
        return state

    import unicodedata
    normalized_msg = unicodedata.normalize('NFKD', lower_msg).encode('ASCII', 'ignore').decode('utf-8')

    # Check for order or product identifier in user text
    has_specific_oid = bool(re.search(r'\b(ord_[a-f0-9]{32}|sim-o-\d+|o-\d+|o0\d{5,}|o\d{5,}|dh\d+|\d{5,})\b', lower_msg))
    has_specific_pid = bool(re.search(r'\b(sim-p-\d+|p-\d+)\b', lower_msg))
    has_order_phrase = bool(any(w in lower_msg for w in [
        "đơn em", "đơn này", "đơn tôi", "đơn mình", "đơn của", "mã đơn", "check đơn",
        "xem đơn", "tra đơn", "đơn cũ", "đơn mega sale", "có đơn", "đơn nào", "tìm đơn",
        "đơn mua", "đã mua", "mua món", "mua cái", "mua hàng"
    ]))
    has_check_request = bool(has_order_phrase and any(w in lower_msg for w in ["check", "xem", "tra", "mã đơn đây", "kẹt"]))

    # Multi-turn context resolution: active server context, conversational history, and attachments
    bound_ctx = state.get("bound", {}).get("context", {}) or {}
    active_order_id = bound_ctx.get("order_id")
    active_product_id = bound_ctx.get("product_id")

    prev_messages = state.get("messages", [])[:-1]
    prev_had_order = any(bool(re.search(r'\b(ord_[a-f0-9]{32}|SIM-O-\d+|SIM-P-\d+|O-\d+|P-\d+)\b', m.get("content", ""))) for m in prev_messages[-4:])
    recent_subagents = [s for s in state.get("subagent_history", []) if s.startswith("supervisor:routed_to_")]
    prev_was_order_agent = bool(recent_subagents and recent_subagents[-1] == "supervisor:routed_to_order_agent")

    has_attachment = bool(state["messages"] and state["messages"][-1].get("attachment"))
    is_false_image_term = bool(re.search(r'\b(hình thức|tình hình|ảnh hưởng)\b', lower_msg))
    has_image_query = not is_false_image_term and bool(re.search(
        r'\b(ảnh|hình|hình ảnh|tấm ảnh|tấm hình|bức ảnh|đọc ảnh|xem ảnh|nhìn ảnh|trong ảnh|ảnh này|ảnh đó|ảnh đính kèm)\b',
        lower_msg
    ))

    is_info_continuation = any(w in lower_msg for w in [
        "ngoài ra", "còn thông tin", "chi tiết hơn", "thêm thông tin", "nhiều thông tin",
        "còn gì nữa", "hết chưa", "thì sao", "là sao", "còn cái", "còn đơn", "thế còn",
        "còn gì", "shop tên gì", "tên shop"
    ])
    is_action_prompt = any(w in lower_msg for w in [
        "thực hiện đi", "kiểm tra đi", "check đi", "tra đi", "xem đi", "làm đi",
        "tra cứu đi", "kiểm tra giúp", "check giúp", "xem giúp", "giải thích giúp",
        "check xem", "xem có", "kiểm tra xem", "tìm xem", "coi xem", "đọc ảnh", "xem ảnh"
    ])
    is_item_selection = any(w in lower_msg for w in [
        "cái này", "cái đó", "đơn này", "đơn đầu", "cái thứ", "mục này", "lấy cái này", "chọn cái này",
        "món này", "món đó", "món kia", "đồ này", "đồ đó", "sản phẩm này", "sản phẩm đó",
        "mẫu này", "mẫu đó", "quần tây", "áo sơ mi", "giày lười", "áo thun", "váy", "đầm",
        "áo này", "quần này", "giày này", "chiếc này", "đôi này"
    ]) or any(w in normalized_msg for w in [
        "cai nay", "cai do", "don nay", "don dau", "mon nay", "mon do", "san pham nay",
        "ao nay", "quan nay", "giay nay", "chiec nay", "doi nay"
    ])

    # Product attributes inquiry (material, size, care, catalog warranty, color, specs)
    is_product_spec_q = any(w in lower_msg for w in [
        "chất liệu", "chất vải", "làm bằng gì", "vải gì", "chất gì",
        "bảo quản", "giặt thế nào", "giặt sao", "hướng dẫn bảo quản", "có giặt máy được không",
        "màu gì", "màu sắc", "kích cỡ", "thông số", "chi tiết sản phẩm",
        "size gì", "mặc vừa", "có size"
    ]) or any(w in normalized_msg for w in [
        "chat lieu", "chat vai", "lam bang gi", "vai gi", "chat gi",
        "bao quan", "giat the nao", "giat sao", "mau sac", "mau gi", "thong so"
    ])

    # Item warranty inquiry (asking how long this specific item is under warranty, or if it's still covered)
    has_warranty_term = ("bảo hành" in lower_msg or "bao hanh" in normalized_msg or "hạn bảo hành" in lower_msg)
    is_item_warranty_q = has_warranty_term and (
        is_item_selection
        or any(w in lower_msg for w in [
            "bao lâu", "mấy tháng", "mấy ngày", "hết hạn chưa", "còn hạn",
            "còn bảo hành", "được bảo hành bao lâu", "bảo hành được bao lâu",
            "món này", "sản phẩm này", "áo này", "quần này", "giày này", "đơn này"
        ])
        or any(w in normalized_msg for w in [
            "bao lau", "may thang", "may ngay", "het han chua", "con han",
            "con bao hanh", "mon nay", "san pham nay", "ao nay", "quan nay", "don nay"
        ])
    )

    # General store policy FAQ: explicit inquiry about shop rules/policies, fees, procedures, hotline
    is_general_store_policy = any(kw in lower_msg for kw in [
        "chính sách của shop", "chính sách bảo hành của shop", "chính sách đổi trả của shop",
        "chính sách shop", "quy định của shop", "chính sách bảo hành", "chính sách đổi trả",
        "quy trình bảo hành", "thủ tục bảo hành", "điều kiện bảo hành",
        "bảo hành có mất phí không", "mất phí không", "có mất phí", "ai trả phí", "ai chịu phí",
        "mất hóa đơn", "mất bill", "cần hóa đơn không", "lỗi kỹ thuật để đổi",
        "áp dụng cho những lỗi nào", "bảo hành áp dụng cho",
        "tư vấn chính sách", "hotline", "tổng đài", "khung giờ", "mấy giờ"
    ]) or any(kw in normalized_msg for kw in [
        "chinh sach cua shop", "chinh sach bao hanh cua shop", "chinh sach shop",
        "quy trinh bao hanh", "thu tuc bao hanh", "dieu kien bao hanh",
        "bao hanh co mat phi khong", "mat phi khong", "ai tra phi"
    ])

    is_explicit_general = classify_user_text(last_user_msg) == "general" or any(w in lower_msg for w in [
        "thuật toán", "algorithm", "thời tiết", "weather", "thủ đô", "toán học", "lập trình", "python"
    ])

    routing_reason = "default_routing"

    is_policy_intent = any(kw in lower_msg for kw in POLICY_KEYWORDS) or is_hours_inquiry or is_general_store_policy
    is_how_to_claim = any(w in lower_msg for w in ["nhận kiểu gì", "nhận như thế nào", "làm sao để nhận"])
    is_policy_condition_q = any(w in lower_msg for w in [
        "áp dụng cho", "điều kiện", "trong bao lâu", "thời hạn", "mất phí", "ai trả",
        "tính từ lúc nào", "làm sao để", "cần giấy tờ gì", "có cần", "làm mất bill",
        "có đc", "có được", "được ko", "được không", "đc ko", "đc không", "cover ko",
        "tư vấn chính sách", "hỗ trợ đổi mới 1-1 ko", "có nằm trong", "đổi mới 1-1 ko",
        "như thế nào", "thế nào", "ra sao"
    ])

    read_only_lookup = is_read_only_lookup_intent(last_user_msg)

    # 4. Actionable Cancellation & Refund (Dispute priority)
    if not read_only_lookup and any(kw in lower_msg for kw in ["hủy đơn", "hủy hàng", "muốn hủy", "hủy luôn", "hoàn tiền"]):
        state["intent"] = "dispute_complaint"
        state["next_worker"] = "dispute_agent"
        routing_reason = "dispute_cancellation_refund"
    # 5. Product specification or item-specific warranty inquiry (SOP 1, SOP 4)
    # Takes precedence over general policy if the inquiry is about a specific item or product attributes.
    elif not is_general_store_policy and (is_product_spec_q or is_item_warranty_q):
        has_focus = bool(active_order_id or active_product_id or has_specific_oid or has_specific_pid or has_order_phrase or prev_had_order or prev_was_order_agent)
        state["intent"] = "order_inquiry"
        state["next_worker"] = "order_agent"
        routing_reason = "product_spec_inquiry" if has_focus else "product_spec_no_context"
    # 6. Policy conditions FAQ without an order check request:
    elif (is_policy_intent and not has_specific_oid and not has_check_request and is_policy_condition_q) or is_how_to_claim or is_hours_inquiry or is_general_store_policy:
        state["intent"] = "policy_knowledge"
        state["next_worker"] = "policy_agent"
        routing_reason = "policy_conditions_faq"
    # 7. Actionable Exchange, Defect & Inventory (SOP 2, SOP 3)
    elif not read_only_lookup and any(kw in lower_msg for kw in DISPUTE_KEYWORDS):
        state["intent"] = "dispute_complaint"
        state["next_worker"] = "dispute_agent"
        routing_reason = "dispute_exchange_defect"
    # 8. Policy inquiry that didn't match dispute keywords
    elif is_policy_intent and not (has_specific_oid or has_order_phrase):
        state["intent"] = "policy_knowledge"
        state["next_worker"] = "policy_agent"
        routing_reason = "policy_inquiry"
    # 9. Order & Product / Store inquiry (SOP 1, SOP 4)
    elif (
        plural_orders
        or any(kw in lower_msg for kw in ORDER_KEYWORDS)
        or any(kw in lower_msg for kw in PRODUCT_OR_STORE_KEYWORDS)
        or has_specific_oid
        or has_specific_pid
        or has_order_phrase
    ):
        state["intent"] = "order_inquiry"
        state["next_worker"] = "order_agent"
        routing_reason = "order_or_product_keywords"
    # 10. Multi-turn order context continuation, image-assisted inquiry, or focused order inquiry
    elif not is_explicit_general and (
        has_attachment
        or has_image_query
        or (active_order_id and (is_info_continuation or is_action_prompt or is_item_selection))
        or ((prev_was_order_agent or prev_had_order) and (is_info_continuation or is_action_prompt or is_item_selection))
    ):
        state["intent"] = "order_inquiry"
        state["next_worker"] = "order_agent"
        routing_reason = "order_context_continuation"
    # 11. Fallback to Witty Pivot Agent (Chitchat / OOD / General)
    else:
        state["intent"] = "chitchat_general"
        state["next_worker"] = "witty_agent"
        routing_reason = "witty_general_fallback"

    state.setdefault("trace", {})["routing_reason"] = routing_reason
    state["subagent_history"].append(f"supervisor:routed_to_{state['next_worker']}")
    return state
