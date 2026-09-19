"""Witty Pivot Agent: Handles general knowledge / chit-chat with a delightful pivot to sales.
Adheres strictly to sentiment, topic, and token guardrails.
"""
import copy
from typing import Any

from retailops.guardrails.rate_limiter import check_ood_limit
from retailops.workflow.state import MultiAgentState

WITTY_SYSTEM_PROMPT = (
    "Bạn là trợ lý CSKH thông minh và dí dỏm của shop bán lẻ.\n"
    "Khách hàng đang hỏi một câu hỏi ngoài lề hoặc kiến thức chung (ví dụ thuật toán, đời sống, thời tiết).\n"
    "Nhiệm vụ của bạn:\n"
    "1. Giải thích hoặc trả lời thật ngắn gọn bản chất câu hỏi trong 1-2 câu cực kỳ dễ hiểu (dưới 40 từ).\n"
    "2. Nối thêm 1 câu 'bẻ lái' tự nhiên, hài hước sang việc thư giãn, mua sắm hoặc sắm đồ tại shop.\n"
    "Quy tắc nghiêm ngặt:\n"
    "- Không đoán mò hoặc bịa đặt thời tiết/nhiệt độ hiện tại vì bạn không có kết nối cảm biến thời tiết trực tiếp.\n"
    "- Không viết bài luận dài dòng, không giải bài tập chi tiết.\n"
    "- Luôn thân thiện, lễ phép (dạ, ạ), kết thúc bằng lời mời xem sản phẩm hoặc ưu đãi."
)


def run_witty_agent(state: MultiAgentState, gateway: Any, timeout: int = 15) -> MultiAgentState:
    """Execute the witty pivot subagent."""
    state = copy.deepcopy(state)
    last_user_msg = next((m["content"] for m in reversed(state["messages"]) if m["role"] == "user"), "")
    
    # 1. Check OOD abuse rate limit
    ood_check = check_ood_limit(state.get("consecutive_ood_count", 0))
    if not ood_check.allow_witty_pivot:
        reply_content = ood_check.cutoff_message
        msg = {"role": "assistant", "content": reply_content}
        state["messages"].append(msg)
        state["fresh"].append(msg)
        state["complete"] = True
        state["subagent_history"].append("witty_agent:cutoff")
        return state

    # 2. Check Strict Mode (Customer is angry or frustrated)
    if state.get("strict_mode") or state.get("sentiment") == "negative":
        reply_content = (
            "Dạ em là trợ lý bán lẻ nên chỉ có thể hỗ trợ về đơn hàng và sản phẩm của shop thôi ạ! "
            "Anh/chị đang cần em kiểm tra đơn hàng hay hỗ trợ vấn đề gì gấp không ạ?"
        )
        msg = {"role": "assistant", "content": reply_content}
        state["messages"].append(msg)
        state["fresh"].append(msg)
        state["complete"] = True
        state["subagent_history"].append("witty_agent:strict_redirect")
        return state

    # 3. Call Model with Witty Pivot Prompt & Hard Token Limit
    prompt_messages = [
        {"role": "system", "content": WITTY_SYSTEM_PROMPT},
        {"role": "user", "content": last_user_msg}
    ]

    try:
        # Request short completion
        response = gateway.chat(prompt_messages, False, timeout)
        content = response.get("message", {}).get("content", "").strip()
        if not content:
            content = (
                "Dạ câu hỏi thú vị quá! Nhưng mà dù nghiên cứu gì đi nữa thì tinh thần sảng khoái vẫn là nhất ạ. "
                "Shop đang có nhiều món đồ giúp nâng cao năng suất và giải trí, anh/chị ghé xem thử nhé!"
            )
    except Exception as exc:
        import logging
        logging.getLogger("retailops.witty_agent").warning("Witty agent execution fallback: %s", exc)
        # Safe fallback
        content = (
            "Dạ kiến thức này rộng lớn quá em chỉ biết chút ít thôi ạ! "
            "Nhưng về đồ mua sắm của shop thì em nắm rõ trong lòng bàn tay, anh/chị cần tư vấn món gì không ạ?"
        )

    msg = {"role": "assistant", "content": content}
    state["messages"].append(msg)
    state["fresh"].append(msg)
    state["complete"] = True
    state["consecutive_ood_count"] = state.get("consecutive_ood_count", 0) + 1
    state["subagent_history"].append("witty_agent:pivot_success")
    return state
