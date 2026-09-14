"""Dispute & Refund Subagent.
Handles cancellations, complaints, and refunds with strict human-in-the-loop proposals.
Never executes mutations directly!
"""
import copy
from typing import Any

from retailops.workflow.state import MultiAgentState

DISPUTE_SYSTEM_PROMPT = (
    "Bạn là Chuyên viên Tiếp nhận Khiếu nại & Hỗ trợ Đổi trả của shop.\n"
    "Nhiệm vụ của bạn là lắng nghe khiếu nại, đồng cảm với khách hàng và tạo đề xuất hủy đơn/hoàn tiền.\n"
    "Quy tắc tối cao:\n"
    "- Bạn KHÔNG ĐƯỢC tự ý sửa cơ sở dữ liệu hay tự ý hủy đơn.\n"
    "- Khi khách hàng yêu cầu hủy đơn, hãy ghi nhận lý do và chuẩn bị Đề xuất hủy đơn để người dùng tự tay xác nhận trên giao diện.\n"
    "- Luôn giữ thái độ ân cần, đồng cảm và lịch sự."
)


def run_dispute_agent(state: MultiAgentState, execute: Any, gateway: Any, timeout: int = 30) -> MultiAgentState:
    """Execute dispute and cancellation proposal subagent."""
    state = copy.deepcopy(state)
    state["consecutive_ood_count"] = 0

    last_user_msg = next((m["content"] for m in reversed(state["messages"]) if m["role"] == "user"), "")
    prompt_messages = [
        {"role": "system", "content": DISPUTE_SYSTEM_PROMPT},
        {"role": "user", "content": last_user_msg}
    ]

    # Model inspects or extracts proposal
    try:
        response = gateway.chat(prompt_messages, True, timeout)
        message = response.get("message", {})
        calls = message.get("tool_calls", [])

        cancellation_proposal = None
        if calls:
            for call in calls:
                name = call["function"]["name"]
                args = call["function"]["arguments"]
                if name == "prepare_cancellation":
                    # Tool sets up proposal in state context
                    result = execute(name, args)
                    state["tool_count"] += 1
                    cancellation_proposal = {
                        "action": "cancel_order",
                        "order_id": args.get("order_id"),
                        "reason": args.get("reason", "Khách yêu cầu hủy"),
                        "status": "pending_user_confirmation"
                    }

        final_content = message.get("content", "")
        if cancellation_proposal:
            state["action_proposal"] = cancellation_proposal
            final_content = (
                f"Dạ em đã ghi nhận yêu cầu hủy đơn hàng {cancellation_proposal['order_id']} với lý do: "
                f"'{cancellation_proposal['reason']}'. "
                "Em đã mở bảng xem lại đề xuất trên màn hình, anh/chị vui lòng kiểm tra và bấm 'Xác nhận hủy' để hệ thống xử lý an toàn nhé ạ!"
            )
        elif not final_content:
            final_content = "Dạ shop rất tiếc vì trải nghiệm chưa trọn vẹn này của anh/chị. Anh/chị cho em xin mã đơn hàng và tình trạng gặp phải để em hỗ trợ xử lý ngay nhé ạ!"

    except Exception:
        final_content = "Dạ shop đã ghi nhận phản hồi của anh/chị và sẽ ưu tiên kiểm tra xử lý ngay ạ!"

    msg = {"role": "assistant", "content": final_content}
    state["messages"].append(msg)
    state["fresh"].append(msg)
    state["complete"] = True
    state["subagent_history"].append("dispute_agent:proposal_ready" if state.get("action_proposal") else "dispute_agent:listening")
    return state
