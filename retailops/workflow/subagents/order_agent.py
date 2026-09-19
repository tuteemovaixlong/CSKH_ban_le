"""Order & Logistics Subagent.
Handles order status, order listing, item tracking, and shipping estimates using read-only tools.
"""
import copy
import json
import logging
from typing import Any

from retailops.workflow.state import MultiAgentState

log = logging.getLogger("retailops.order_agent")

ORDER_SYSTEM_PROMPT = (
    "Bạn là Chuyên viên Quản lý Đơn hàng & Logistics của shop Thương Mại Điện Tử.\n"
    "Nhiệm vụ của bạn là tra cứu đơn hàng, lộ trình vận chuyển, tình trạng shipper giao hàng.\n"
    "Quy tắc nghiệp vụ TMĐT 2026:\n"
    "- Sử dụng các công cụ: `read_order`, `get_order`, `list_orders`, `track_shipment`, `search_products`.\n"
    "- SOP 1 (Bưu tá báo ảo / không gọi): Khi kiểm tra thấy bưu tá cập nhật không liên lạc được dù khách ở nhà, trích xuất rõ Họ tên bưu tá và Số điện thoại, đồng thời khẳng định shop tin tưởng khách và đã kích hoạt lệnh khiếu nại yêu cầu bưu cục giao lại ngay trong ca trước 18:00.\n"
    "- SOP 4 (Nghẽn trạm Mega SOC > 48h): Khi phát hiện kiện hàng bị trễ tại trạm phân loại liên tỉnh đợt Mega Sale, giải thích chân thành nguyên nhân ùn ứ, thông báo ngày giao dự kiến và chủ động tặng mã Voucher giảm giá 50.000đ (mã voucher từ kết quả tra cứu hoặc 'SALE50K-BN-SOC') gửi tặng khách hàng.\n"
    "- Luôn giao tiếp lịch sự, minh bạch và bảo vệ quyền lợi tối đa cho khách hàng."
)

_STATUS_MAP = {
    "pending": "Đang xử lý",
    "delivered": "Đã giao thành công",
    "cancelled": "Đã hủy",
    "processing": "Đang chuẩn bị hàng",
    "shipping": "Đang vận chuyển",
}


def _synthesize_order_response(tool_results):
    """Build a customer-facing answer from tool results when the model returns empty content.

    This handles the case where certain vLLM model backends (e.g. Gemma-4 with
    ``--tool-call-parser gemma4``) emit follow-up text as internal *thought*
    tokens that are not surfaced in the OpenAI-compatible ``content`` field,
    causing ``assistant_message()`` to raise ``ProtocolError('Empty assistant
    answer')``.  Instead of falling through to a generic "hệ thống bận" fallback
    the agent now synthesises a helpful response from the actual tool output.
    """
    for tr in tool_results:
        name, args, result = tr["name"], tr["args"], tr["result"]

        # --- Error responses ---
        if isinstance(result, dict) and result.get("error"):
            error_code = result["error"]
            if error_code == "order_not_found":
                oid = args.get("order_id", "")
                return (
                    f"Dạ em đã kiểm tra nhưng không tìm thấy đơn hàng {oid} "
                    "trong hệ thống của shop. Anh/chị vui lòng kiểm tra lại mã đơn hàng "
                    "(ví dụ: O-101, O-102) giúp em nhé ạ!"
                )
            return (
                f"Dạ em gặp trục trặc khi tra cứu: {result.get('message', 'Lỗi không xác định')}. "
                "Anh/chị vui lòng thử lại hoặc cung cấp thêm thông tin giúp em nhé ạ!"
            )

        # --- Shipment tracking (track_shipment) ---
        if isinstance(result, dict) and "shipment" in result:
            shipment = result["shipment"]
            oid = result.get("order_id", args.get("order_id", ""))
            carrier = shipment.get("carrier", "GHTK")
            status_text = shipment.get("status_text", "Đang xử lý")
            location = shipment.get("current_location", "Đang cập nhật")
            eta = shipment.get("estimated_delivery", "Đang cập nhật")
            shipper = shipment.get("shipper", "")
            lines = [
                f"Dạ em đã tra cứu hành trình đơn hàng {oid} qua {carrier} ạ:",
                f"📦 Trạng thái: **{status_text}**",
                f"📍 Vị trí hiện tại: {location}",
                f"🚚 Dự kiến giao: {eta}",
            ]
            if shipper and shipper != "Chưa phân công":
                lines.append(f"👤 Shipper: {shipper}")
            # SOP 1: virtual delivery
            if shipment.get("status") == "delivery_failed_virtual":
                lines.append(
                    "\n⚠️ Shop đã ghi nhận nghi vấn bưu tá **báo ảo không liên lạc được**. "
                    "Shop tin tưởng anh/chị và đã kích hoạt lệnh khiếu nại yêu cầu bưu cục giao lại ngay trong ca trước 18:00 ạ!"
                )
            # SOP 4: mega sale delay
            if shipment.get("status") == "sorting_delayed":
                voucher = shipment.get("voucher_code", "SALE50K-BN-SOC")
                lines.append(
                    f"\n😔 Shop chân thành xin lỗi vì sự chậm trễ do ùn ứ đợt Mega Sale. "
                    f"Shop xin tặng anh/chị mã Voucher giảm **50.000đ**: `{voucher}` để bù đắp nhé ạ!"
                )
            steps = shipment.get("steps", [])
            if steps:
                lines.append("\n📋 Lịch trình chi tiết:")
                for step in steps[:4]:
                    lines.append(f"  • {step.get('time', '')}: {step.get('event', '')}")
            return "\n".join(lines)

        # --- Order info (get_order / read_order) ---
        if isinstance(result, dict) and "order" in result:
            order = result["order"]
            oid = order.get("id", args.get("order_id", ""))
            status_text = _STATUS_MAP.get(order.get("status"), order.get("status", "Không rõ"))
            name_product = order.get("name", "")
            variant = order.get("variant", "")
            amount = order.get("amount")
            parts = [f"Dạ đơn hàng **{oid}**"]
            if name_product:
                parts[0] += f" – {name_product}"
            if variant:
                parts[0] += f" ({variant})"
            parts.append(f"📦 Trạng thái: **{status_text}**")
            if amount:
                parts.append(f"💰 Giá trị: {amount:,.0f}đ")
            parts.append("Anh/chị cần em hỗ trợ thêm gì không ạ?")
            return "\n".join(parts)

        # --- Order list (list_orders) ---
        if isinstance(result, dict) and "orders" in result:
            orders = result["orders"]
            if not orders:
                return "Dạ tài khoản của anh/chị hiện chưa có đơn hàng nào trong hệ thống ạ."
            lines = ["Dạ đây là danh sách đơn hàng của anh/chị:"]
            for o in orders[:5]:
                st = _STATUS_MAP.get(o.get("status"), o.get("status", ""))
                lines.append(f"  • **{o.get('id')}** – {o.get('name', '')} → {st}")
            if result.get("truncated"):
                lines.append("  _(và còn thêm đơn hàng khác)_")
            lines.append("Anh/chị muốn em kiểm tra chi tiết đơn nào ạ?")
            return "\n".join(lines)

    return "Dạ em đã kiểm tra thông tin đơn hàng cho anh/chị rồi ạ. Anh/chị cần hỗ trợ thêm gì không ạ?"


def run_order_agent(state: MultiAgentState, execute: Any, gateway: Any, timeout: int = 30) -> MultiAgentState:
    """Execute order and logistics subagent with read-only tools."""
    state = copy.deepcopy(state)
    state["consecutive_ood_count"] = 0  # Reset OOD counter on retail domain inquiry
    trace = state.setdefault("trace", {})

    last_user_msg = next((m["content"] for m in reversed(state["messages"]) if m["role"] == "user"), "")
    prompt_messages = [
        {"role": "system", "content": ORDER_SYSTEM_PROMPT},
        {"role": "user", "content": last_user_msg}
    ]

    # Let model inspect orders with tool permission
    try:
        response = gateway.chat(prompt_messages, True, timeout)
        trace["model_calls"] = trace.get("model_calls", 0) + 1
        trace["prompt_tokens"] = trace.get("prompt_tokens", 0) + (response.get("prompt_eval_count") or 0)
        trace["generated_tokens"] = trace.get("generated_tokens", 0) + (response.get("eval_count") or 0)
        message = response.get("message", {})
        calls = message.get("tool_calls", [])

        if calls:
            tool_results = []
            for call in calls:
                name = call["function"]["name"]
                args = call["function"]["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                if name in ("read_order", "list_orders", "search_products", "track_shipment", "get_order", "get_context"):
                    result = execute(name, args)
                    state["tool_count"] += 1
                    trace.setdefault("tools", []).append({"name": name, "status": "error" if isinstance(result, dict) and result.get("error") else "ok"})
                    tool_results.append({"name": name, "args": args, "result": result})
                    tool_content = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
                    tool_entry = {"role": "tool", "tool_name": name, "content": tool_content}
                    prompt_messages.append(message)
                    prompt_messages.append(tool_entry)

            # Follow-up completion after tool results.
            # Some vLLM backends (Gemma-4 with --tool-call-parser gemma4) return
            # content:null on the follow-up turn, causing ProtocolError.  In that
            # case we synthesise a response from the tool results directly.
            try:
                final_res = gateway.chat(prompt_messages, False, timeout)
                trace["model_calls"] = trace.get("model_calls", 0) + 1
                trace["prompt_tokens"] = trace.get("prompt_tokens", 0) + (final_res.get("prompt_eval_count") or 0)
                trace["generated_tokens"] = trace.get("generated_tokens", 0) + (final_res.get("eval_count") or 0)
                final_content = (final_res.get("message", {}).get("content") or "").strip()
            except Exception as follow_exc:
                log.info("Follow-up model call returned empty/error (%s), synthesising from tool results", follow_exc)
                final_content = ""

            if not final_content:
                final_content = _synthesize_order_response(tool_results)
        else:
            final_content = message.get("content", "Dạ anh/chị cung cấp giúp em mã đơn hàng để em kiểm tra ngay nhé ạ!")

    except Exception as exc:
        log.warning("Order agent execution fallback: %s", exc)
        final_content = "Dạ hệ thống tra cứu đơn hàng đang bận một chút, anh/chị vui lòng để lại mã đơn hàng để em kiểm tra lại nhé ạ!"

    msg = {"role": "assistant", "content": final_content}
    state["messages"].append(msg)
    state["fresh"].append(msg)
    state["complete"] = True
    state["subagent_history"].append("order_agent:done")
    return state
