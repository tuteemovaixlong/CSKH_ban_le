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
    "nói chuyện với người", "nhân viên đâu", "admin đâu", "human agent", "talk to human"
]

ORDER_KEYWORDS = [
    "đơn hàng", "mã đơn", "tra cứu đơn", "kiểm tra đơn", "giao đến đâu",
    "bao giờ nhận", "vận chuyển", "tracking", "giao hàng", "shipper", "o-"
]

DISPUTE_KEYWORDS = [
    "hủy đơn", "hủy hàng", "muốn hủy", "hoàn tiền", "trả hàng", "hàng lỗi",
    "rách", "vỡ", "bể", "khiếu nại", "sai hàng", "đổi hàng", "cancel"
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

    # 2. Guardrail: Sentiment & Frustration Analysis
    sentiment_result = analyze_sentiment(last_user_msg)
    state["sentiment"] = sentiment_result.sentiment
    state["strict_mode"] = sentiment_result.strict_mode_required

    # 3. Check for Explicit Human Escalation Request
    if any(kw in lower_msg for kw in HUMAN_ESCALATION_KEYWORDS):
        state["intent"] = "dispute_complaint"
        state["next_worker"] = "human_escalation"
        state["requires_human"] = True
        state["human_reason"] = "Khách hàng yêu cầu gặp trực tiếp nhân viên tư vấn"
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
    # Check policy / RAG inquiry first if explicitly asking about rules/policy/instructions
    if any(kw in lower_msg for kw in ["chính sách", "quy định", "hướng dẫn", "bảo hành", "điều khoản", "freeship", "phí ship", "voucher"]):
        state["intent"] = "policy_knowledge"
        state["next_worker"] = "policy_agent"
    # Check dispute / cancellation
    elif any(kw in lower_msg for kw in DISPUTE_KEYWORDS):
        state["intent"] = "dispute_complaint"
        state["next_worker"] = "dispute_agent"
    # Check order inquiry
    elif any(kw in lower_msg for kw in ORDER_KEYWORDS) or re.search(r'\b(o-\d+|dh\d+)\b', lower_msg):
        state["intent"] = "order_inquiry"
        state["next_worker"] = "order_agent"
    # Fallback to Witty Pivot Agent (Chitchat / OOD / General)
    else:
        state["intent"] = "chitchat_general"
        state["next_worker"] = "witty_agent"

    state["subagent_history"].append(f"supervisor:routed_to_{state['next_worker']}")
    return state
