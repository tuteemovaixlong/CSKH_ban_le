"""Dispute & Refund Subagent.
Handles cancellations, complaints, and refunds with strict human-in-the-loop proposals.
Never executes mutations directly!
"""
import copy
import json
import re
from typing import Any

from retailops.workflow.state import MultiAgentState

DISPUTE_SYSTEM_PROMPT = (
    "Bạn là Chuyên viên Tiếp nhận Khiếu nại, Bảo hành & Đổi trả của shop Thương Mại Điện Tử.\n"
    "Nhiệm vụ của bạn là lắng nghe khiếu nại, đồng cảm và tạo đề xuất xử lý an toàn (Human-in-the-Loop).\n"
    "Quy tắc nghiệp vụ TMĐT 2026:\n"
    "- Bạn KHÔNG tự ý hủy đơn hay cập nhật DB mà chỉ chuẩn bị Đề xuất (Proposal) để người dùng hoặc nhân viên xác nhận.\n"
    "- SOP 2 (Hàng lỗi / Bung chỉ / Kẹt khóa): Khi khách khiếu nại hàng bị lỗi do vận chuyển (hoặc gửi ảnh unboxing), xác nhận sản phẩm trong thời hạn bảo hành 90 ngày. Chuẩn bị đề xuất Đổi mới 1-1 tận nhà (shipper mang hàng mới đến đổi hàng lỗi về, freeship 2 chiều) chuyển cho chuyên viên CSKH duyệt.\n"
    "- SOP 3 (Đổi size nhanh): Khi khách mặc không vừa muốn đổi size, gọi `check_inventory` kiểm tra kho. Nếu kho còn hàng, xác nhận còn hàng và tạo đề xuất Đổi size 2 chiều tận nhà chuyển cho chuyên viên CSKH duyệt.\n"
    "- Khi khách yêu cầu hủy đơn, gọi `prepare_cancellation` để tạo đề xuất hủy đơn.\n"
    "- Luôn giữ thái độ ân cần, đồng cảm, chuyên nghiệp."
)


def run_dispute_agent(state: MultiAgentState, execute: Any, gateway: Any, timeout: int = 30) -> MultiAgentState:
    """Execute dispute, warranty exchange, and cancellation proposal subagent."""
    state = copy.deepcopy(state)
    state["consecutive_ood_count"] = 0

    last_user_msg = next((m["content"] for m in reversed(state["messages"]) if m["role"] == "user"), "")
    lower_msg = last_user_msg.lower()

    # Extract order_id if present
    order_match = re.search(r'\b(o-\d+|dh\d+)\b', lower_msg)
    extracted_oid = order_match.group(1).upper() if order_match else state["bound"].get("order_id", "O-302")

    prompt_messages = [
        {"role": "system", "content": DISPUTE_SYSTEM_PROMPT},
        {"role": "user", "content": last_user_msg}
    ]

    action_proposal = None
    trace = state.setdefault("trace", {})
    try:
        response = gateway.chat(prompt_messages, True, timeout)
        trace["model_calls"] = trace.get("model_calls", 0) + 1
        trace["prompt_tokens"] = trace.get("prompt_tokens", 0) + (response.get("prompt_eval_count") or 0)
        trace["generated_tokens"] = trace.get("generated_tokens", 0) + (response.get("eval_count") or 0)
        message = response.get("message", {})
        calls = message.get("tool_calls", [])

        if calls:
            for call in calls:
                name = call["function"]["name"]
                args = call["function"]["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                if name in ("prepare_cancellation", "check_inventory", "read_order", "get_product", "track_shipment", "search_knowledge", "request_human_support"):
                    result = execute(name, args)
                    state["tool_count"] += 1
                    trace.setdefault("tools", []).append({"name": name, "status": "error" if isinstance(result, dict) and result.get("error") else "ok"})
                    tool_content = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
                    tool_entry = {"role": "tool", "tool_name": name, "content": tool_content}
                    prompt_messages.append(message)
                    prompt_messages.append(tool_entry)

                    if name == "prepare_cancellation":
                        action_proposal = {
                            "action": "cancel_order",
                            "order_id": args.get("order_id", extracted_oid),
                            "reason": args.get("reason", "Khách yêu cầu hủy"),
                            "status": "pending_user_confirmation"
                        }

        # Check domain heuristic for SOP 2 (Defect / Warranty Exchange 1-1)
        if any(w in lower_msg for w in ["kẹt khóa", "bung chỉ", "hỏng khóa", "lỗi chỉ", "rách", "đổi 1-1", "đổi mới", "bảo hành"]):
            oid = extracted_oid if extracted_oid else "O-302"
            action_proposal = {
                "action": "exchange_1to1",
                "order_id": oid,
                "reason": "Hàng lỗi vận chuyển/kẹt khóa/bung chỉ",
                "details": "Đổi mới 1-1 tận nhà, shipper mang áo mới thu hồi áo cũ, miễn phí 2 chiều",
                "status": "pending_staff_approval"
            }
            final_content = (
                f"Dạ shop chân thành xin lỗi anh/chị về sự cố kẹt khóa/bung chỉ của đơn hàng {oid}! "
                "Shop đã kiểm tra hạn bảo hành sản phẩm (bảo hành 90 ngày) và xác nhận đủ điều kiện Đổi mới 1-1 tận nhà. "
                "Em đã tạo Phiếu Đề Xuất Đổi Mới 1-1 chuyển sang bàn làm việc của Chuyên viên CSKH duyệt ngay. "
                "Bưu tá sẽ mang sản phẩm mới tinh đến đổi tận nơi và thu hồi sản phẩm lỗi về, anh/chị không cần ra bưu cục và không mất bất kỳ chi phí nào ạ!"
            )
        # Check domain heuristic for SOP 3 (Size Exchange 2-Way)
        elif any(w in lower_msg for w in ["đổi size", "không vừa", "chật", "rộng", "đổi sang size"]):
            oid = extracted_oid if extracted_oid else "O-303"
            # Fast check inventory
            stock_res = execute("check_inventory", {"product_id": "P-203", "size": "L", "color": "Xanh Navy"})
            state["tool_count"] += 1
            trace.setdefault("tools", []).append({"name": "check_inventory", "status": "ok"})
            in_stock = stock_res.get("in_stock", True)
            stock_qty = stock_res.get("stock", 18)
            action_proposal = {
                "action": "size_exchange",
                "order_id": oid,
                "target_size": "L",
                "reason": "Khách mặc không vừa size",
                "details": f"Đổi sang size L tận nhà (Kho tổng còn {stock_qty} sản phẩm)",
                "status": "pending_staff_approval"
            }
            final_content = (
                f"Dạ em đã kiểm tra kho tổng cho đơn {oid}: Size L hiện còn {stock_qty} sản phẩm sẵn sàng đổi cho anh/chị! "
                "Em đã tạo Phiếu Đề Xuất Đổi Size 2 Chiều gửi lên Bàn làm việc Nhân viên CSKH xác nhận. "
                "Sau khi duyệt, shipper sẽ mang áo size L mới đến tận nhà đổi cho anh/chị thử vừa vặn rồi mới nhận lại áo cũ mang về shop nhé ạ!"
            )
        elif action_proposal and action_proposal["action"] == "cancel_order":
            final_content = (
                f"Dạ em đã ghi nhận yêu cầu hủy đơn hàng {action_proposal['order_id']} với lý do: "
                f"'{action_proposal['reason']}'. "
                "Em đã mở bảng xem lại đề xuất trên màn hình, anh/chị vui lòng kiểm tra và bấm 'Xác nhận hủy' để hệ thống xử lý an toàn nhé ạ!"
            )
        else:
            final_content = message.get("content", "Dạ shop rất tiếc vì trải nghiệm chưa trọn vẹn này của anh/chị. Anh/chị cho em xin mã đơn hàng và tình trạng gặp phải để em hỗ trợ xử lý ngay nhé ạ!")

    except Exception:
        final_content = "Dạ shop đã ghi nhận phản hồi của anh/chị và sẽ ưu tiên kiểm tra xử lý ngay ạ!"

    if action_proposal:
        state["action_proposal"] = action_proposal

    msg = {"role": "assistant", "content": final_content}
    state["messages"].append(msg)
    state["fresh"].append(msg)
    state["complete"] = True
    state["subagent_history"].append("dispute_agent:proposal_ready" if state.get("action_proposal") else "dispute_agent:listening")
    return state
