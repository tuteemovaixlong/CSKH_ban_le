"""Supervisor & Intent Router Node for Multi-Agent RetailOps.
Performs fast guardrails triage, sentiment detection, and routes queries to specialized workers.
"""
import copy
import re
from typing import Any

from retailops.guardrails.sentiment import analyze_sentiment
from retailops.guardrails.topic_filter import check_topic_safety
from retailops.workflow.state import MultiAgentState, WorkerType

HUMAN_ESCALATION_KEYWORDS = [
    "gặp nhân viên", "gặp người", "gặp quản lý", "gặp tư vấn viên", "chuyển máy",
    "nói chuyện với người", "nhân viên đâu", "admin đâu", "human agent", "talk to human",
    "gặp người thật", "người thật", "tư vấn viên"
]

ORDER_KEYWORDS = [
    "đơn hàng", "mã đơn", "tra cứu đơn", "kiểm tra đơn", "giao đến đâu",
    "bao giờ nhận", "vận chuyển", "tracking", "giao hàng", "shipper", "bưu tá",
    "báo ảo", "cập nhật ảo", "không nghe máy", "không gọi", "giao lại", "chưa giao",
    "nghẽn kho", "mega soc", "chậm trễ", "lâu quá", "sao lâu thế", "o-"
]

DISPUTE_KEYWORDS = [
    "hủy đơn", "hủy hàng", "muốn hủy", "hoàn tiền", "trả hàng", "hàng lỗi",
    "rách", "vỡ", "bể", "khiếu nại", "sai hàng", "đổi hàng", "cancel",
    "đổi size", "không vừa", "chật", "rộng", "đổi sang size", "bung chỉ",
    "kẹt khóa", "hỏng khóa", "lỗi chỉ", "đổi 1-1", "đổi mới"
]

POLICY_KEYWORDS = [
    "chính sách", "quy định", "bảo hành", "đổi trả như thế nào", "freeship",
    "phí ship", "vận chuyển bao nhiêu", "hình thức thanh toán", "khuyến mãi", "voucher"
]


def run_supervisor(state: MultiAgentState) -> MultiAgentState:
    """Supervise conversation, evaluate guardrails, and decide next worker node."""
    state = copy.deepcopy(state)
    last_user_msg = next((m["content"] for m in reversed(state["messages"]) if m["role"] == "user"), "")
    lower_msg = last_user_msg.lower()

    # 1. Guardrail: Topic Safety (Forbidden domains)
    topic_result = check_topic_safety(last_user_msg)
    if not topic_result.is_safe:
        state["intent"] = "forbidden_topic"
        state["next_worker"] = "direct_response"
        reply = {"role": "assistant", "content": topic_result.refusal_message}
        state["messages"].append(reply)
        state["fresh"].append(reply)
        state["complete"] = True
        state["subagent_history"].append("supervisor:forbidden_refusal")
        return state

    # 2. Guardrail: Sentiment & Frustration Analysis (SOP 5)
    sentiment_result = analyze_sentiment(last_user_msg)
    state["sentiment"] = sentiment_result.sentiment
    state["strict_mode"] = sentiment_result.strict_mode_required

    # Extreme anger or boycott threat trigger (SOP 5)
    is_extreme_rage = any(kw in lower_msg for kw in ["bóc phốt", "tẩy chay", "báo công an", "sập tiệm"])
    if is_extreme_rage:
        state["intent"] = "dispute_complaint"
        state["next_worker"] = "human_escalation"
        state["requires_human"] = True
        state["human_reason"] = "SOP 5: Khách hàng bức xúc cực độ / đe dọa bóc phốt mạng xã hội (Strict Mode)"
        reply = {
            "role": "assistant",
            "content": "Dạ shop thành thật xin lỗi vì trải nghiệm rất không tốt vừa qua của anh/chị! Shop hoàn toàn hiểu sự bức xúc của anh/chị và xin cam kết chịu trách nhiệm xử lý thỏa đáng 100%. Em đã gửi cảnh báo đỏ trực tiếp đến Quản lý cửa hàng để tiếp nhận và gọi lại hỗ trợ anh/chị ngay lập tức ạ!"
        }
        state["messages"].append(reply)
        state["fresh"].append(reply)
        state["complete"] = True
        state["subagent_history"].append("supervisor:escalate_extreme_rage")
        return state

    # 3. Check for Explicit Human Escalation Request (SOP 6)
    if any(kw in lower_msg for kw in HUMAN_ESCALATION_KEYWORDS):
        state["intent"] = "dispute_complaint"
        state["next_worker"] = "human_escalation"
        state["requires_human"] = True
        state["human_reason"] = "SOP 6: Khách hàng bấm nút hoặc yêu cầu gặp trực tiếp nhân viên tư vấn"
        reply = {
            "role": "assistant",
            "content": "Dạ em đã ghi nhận yêu cầu của anh/chị và đang kết nối tới nhân viên tư vấn trực ca. Nhân viên sẽ phản hồi lại anh/chị trong ít phút nữa nhé ạ!"
        }
        state["messages"].append(reply)
        state["fresh"].append(reply)
        state["complete"] = True
        state["subagent_history"].append("supervisor:escalate_human")
        return state

    # 4. Intent Classification & Worker Assignment
    # Check direct actionable exchange/warranty defect actions first (SOP 2, SOP 3)
    if any(kw in lower_msg for kw in ["đổi 1-1", "đổi mới", "kẹt khóa", "bung chỉ", "đổi size"]):
        state["intent"] = "dispute_complaint"
        state["next_worker"] = "dispute_agent"
    # Check policy / RAG inquiry if asking about general rules/policy/instructions
    elif any(kw in lower_msg for kw in ["chính sách", "quy định", "hướng dẫn", "bảo hành", "điều khoản", "freeship", "phí ship", "voucher"]):
        state["intent"] = "policy_knowledge"
        state["next_worker"] = "policy_agent"
    # Check dispute / cancellation / return
    elif any(kw in lower_msg for kw in DISPUTE_KEYWORDS):
        state["intent"] = "dispute_complaint"
        state["next_worker"] = "dispute_agent"
    # Check order inquiry / shipper / delay (SOP 1, SOP 4)
    elif any(kw in lower_msg for kw in ORDER_KEYWORDS) or re.search(r'\b(o-\d+|dh\d+)\b', lower_msg):
        state["intent"] = "order_inquiry"
        state["next_worker"] = "order_agent"
    # Fallback to Witty Pivot Agent (Chitchat / OOD / General)
    else:
        state["intent"] = "chitchat_general"
        state["next_worker"] = "witty_agent"

    state["subagent_history"].append(f"supervisor:routed_to_{state['next_worker']}")
    return state
