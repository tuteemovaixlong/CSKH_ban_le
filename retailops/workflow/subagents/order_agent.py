"""Order & Logistics Subagent.
Handles order status, order listing, item tracking, and shipping estimates using read-only tools.
"""
import copy
from typing import Any

from retailops.workflow.state import MultiAgentState

ORDER_SYSTEM_PROMPT = (
    "Bạn là Chuyên viên Quản lý Đơn hàng & Logistics của shop Thương Mại Điện Tử.\n"
    "Nhiệm vụ của bạn là tra cứu đơn hàng, lộ trình vận chuyển, tình trạng shipper giao hàng.\n"
    "Quy tắc nghiệp vụ TMĐT 2026:\n"
    "- Sử dụng các công cụ: `read_order`, `get_order`, `list_orders`, `track_shipment`, `search_products`.\n"
    "- SOP 1 (Bưu tá báo ảo / không gọi): Khi kiểm tra thấy bưu tá cập nhật không liên lạc được dù khách ở nhà, trích xuất rõ Họ tên bưu tá và Số điện thoại, đồng thời khẳng định shop tin tưởng khách và đã kích hoạt lệnh khiếu nại yêu cầu bưu cục giao lại ngay trong ca trước 18:00.\n"
    "- SOP 4 (Nghẽn trạm Mega SOC > 48h): Khi phát hiện kiện hàng bị trễ tại trạm phân loại liên tỉnh đợt Mega Sale, giải thích chân thành nguyên nhân ùn ứ, thông báo ngày giao dự kiến và chủ động tặng mã Voucher giảm giá 50.000đ (mã voucher từ kết quả tra cứu hoặc 'SALE50K-BN-SOC') gửi tặng khách hàng.\n"
    "- Luôn giao tiếp lịch sự, minh bạch và bảo vệ quyền lợi tối đa cho khách hàng."
)


def run_order_agent(state: MultiAgentState, execute: Any, gateway: Any, timeout: int = 30) -> MultiAgentState:
    """Execute order and logistics subagent with read-only tools."""
    state = copy.deepcopy(state)
    state["consecutive_ood_count"] = 0  # Reset OOD counter on retail domain inquiry

    last_user_msg = next((m["content"] for m in reversed(state["messages"]) if m["role"] == "user"), "")
    prompt_messages = [
        {"role": "system", "content": ORDER_SYSTEM_PROMPT},
        {"role": "user", "content": last_user_msg}
    ]

    # Let model inspect orders with tool permission
    try:
        response = gateway.chat(prompt_messages, True, timeout)
        message = response.get("message", {})
        calls = message.get("tool_calls", [])

        if calls:
            for call in calls:
                name = call["function"]["name"]
                args = call["function"]["arguments"]
                if name in ("read_order", "list_orders", "search_products", "track_shipment", "get_order"):
                    result = execute(name, args)
                    state["tool_count"] += 1
                    tool_entry = {"role": "tool", "tool_name": name, "content": str(result)}
                    prompt_messages.append(message)
                    prompt_messages.append(tool_entry)

            # Follow-up completion after tool results
            final_res = gateway.chat(prompt_messages, False, timeout)
            final_content = final_res.get("message", {}).get("content", "Dạ em đã kiểm tra đơn hàng cho anh/chị rồi ạ.")
        else:
            final_content = message.get("content", "Dạ anh/chị cung cấp giúp em mã đơn hàng để em kiểm tra ngay nhé ạ!")

    except Exception:
        final_content = "Dạ hệ thống tra cứu đơn hàng đang bận một chút, anh/chị vui lòng để lại mã đơn hàng để em kiểm tra lại nhé ạ!"

    msg = {"role": "assistant", "content": final_content}
    state["messages"].append(msg)
    state["fresh"].append(msg)
    state["complete"] = True
    state["subagent_history"].append("order_agent:done")
    return state
