"""Dispute & Refund Subagent.
Handles cancellations, complaints, and refunds with strict human-in-the-loop proposals.
Never executes mutations directly!
"""
import copy
import json
import re
from typing import Any

from retailops.core import ApiError
from retailops.workflow.state import MultiAgentState

DISPUTE_SYSTEM_PROMPT = (
    "Bạn là Chuyên viên Tiếp nhận Khiếu nại, Bảo hành & Đổi trả của shop Thương Mại Điện Tử.\n"
    "Nhiệm vụ của bạn là lắng nghe khiếu nại, đồng cảm và tạo đề xuất xử lý an toàn (Human-in-the-Loop).\n"
    "Quy tắc nghiệp vụ TMĐT 2026:\n"
    "- Bạn KHÔNG tự ý hủy đơn hay cập nhật DB mà chỉ chuẩn bị Đề xuất (Proposal) để người dùng hoặc nhân viên xác nhận.\n"
    "- SOP 2 (Hàng lỗi / Bung chỉ / Kẹt khóa): Khi khách khiếu nại hàng bị lỗi do vận chuyển (hoặc gửi ảnh unboxing), gọi get_order và get_product để xác minh đơn hàng và kiểm tra thời hạn bảo hành thực tế của sản phẩm. Chuẩn bị đề xuất Đổi mới 1-1 tận nhà (shipper mang hàng mới đến đổi hàng lỗi về, freeship 2 chiều) chuyển cho chuyên viên CSKH duyệt nếu đơn hợp lệ.\n"
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

    # Extract order_id safely from message or bound context (supports both flat bound and nested context)
    bound_obj = state.get("bound", {}) if isinstance(state.get("bound"), dict) else {}
    bound_context = bound_obj.get("context", {}) if isinstance(bound_obj.get("context"), dict) else bound_obj
    order_match = re.search(r'\b(o-\d+|o0\d{5,}|o\d{5,}|dh\d+|\d{5,})\b', lower_msg)
    if order_match:
        matched_str = order_match.group(1).upper()
        if matched_str.startswith('O0'):
            extracted_oid = 'O-' + matched_str[2:]
        elif matched_str.startswith('O') and not matched_str.startswith('O-'):
            extracted_oid = 'O-' + matched_str[1:]
        elif matched_str.isdigit():
            extracted_oid = 'O-' + matched_str
        else:
            extracted_oid = matched_str
    else:
        extracted_oid = bound_context.get("order_id") or bound_obj.get("order_id")

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
                if name in ("prepare_cancellation", "check_inventory", "get_order", "get_product", "track_shipment", "search_knowledge", "request_human_support"):
                    result = execute(name, args)
                    state["tool_count"] += 1
                    trace.setdefault("tools", []).append({"name": name, "status": "error" if isinstance(result, dict) and result.get("error") else "ok"})
                    tool_content = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
                    tool_entry = {"role": "tool", "tool_name": name, "content": tool_content}
                    prompt_messages.append(message)
                    prompt_messages.append(tool_entry)

                    if name == "prepare_cancellation" and extracted_oid:
                        chosen_oid = args.get("order_id") or extracted_oid
                        if isinstance(chosen_oid, str) and chosen_oid.upper().startswith('O0'):
                            chosen_oid = 'O-' + chosen_oid[2:]
                        is_eligible = (
                            isinstance(result, dict)
                            and not result.get("error")
                            and result.get("eligible") is True
                            and result.get("order", {}).get("id") == chosen_oid
                        )
                        if is_eligible:
                            action_proposal = {
                                "action": "cancel_order",
                                "order_id": chosen_oid,
                                "reason": args.get("reason", "Khách yêu cầu hủy"),
                                "status": "pending_user_confirmation"
                            }
                        else:
                            action_proposal = None
                            status_desc = result.get("order", {}).get("status") if isinstance(result, dict) else "delivered"
                            final_content = (
                                f"Dạ đơn hàng {chosen_oid} hiện ở trạng thái '{status_desc}', "
                                "shop không thể hỗ trợ hủy đơn qua hệ thống. "
                                "Nếu cần hỗ trợ thêm, anh/chị vui lòng liên hệ nhân viên CSKH để được trợ giúp nhé ạ!"
                            )

        # Check domain heuristic for SOP 2 (Defect / Warranty Exchange 1-1)
        if any(w in lower_msg for w in ["kẹt khóa", "bung chỉ", "hỏng khóa", "lỗi chỉ", "rách", "đổi 1-1", "đổi mới", "bảo hành"]):
            if extracted_oid:
                bound_oid = bound_context.get("order_id") or bound_obj.get("order_id")
                is_order_ok = True
                order_data = {}
                if extracted_oid != bound_oid or not (bound_context.get("product_id") or bound_obj.get("product_id")):
                    try:
                        order_res = execute("get_order", {"order_id": extracted_oid})
                        state["tool_count"] += 1
                        is_order_ok = isinstance(order_res, dict) and not order_res.get("error")
                        trace.setdefault("tools", []).append({"name": "get_order", "status": "ok" if is_order_ok else "error"})
                        if is_order_ok and isinstance(order_res, dict):
                            order_data = order_res.get("order", {})
                    except ApiError as exc:
                        if exc.status == 429 or exc.status >= 500:
                            raise
                        is_order_ok = False
                        state["tool_count"] += 1
                        trace.setdefault("tools", []).append({"name": "get_order", "status": "error"})
                    except Exception:
                        is_order_ok = False
                        state["tool_count"] += 1
                        trace.setdefault("tools", []).append({"name": "get_order", "status": "error"})

                if not is_order_ok:
                    action_proposal = None
                    final_content = (
                        f"Dạ em rất tiếc, hệ thống không tìm thấy đơn hàng {extracted_oid} "
                        f"(hoặc đơn không thuộc tài khoản của anh/chị). "
                        "Anh/chị vui lòng kiểm tra lại chính xác Mã đơn hàng để em có thể tra cứu bảo hành và hỗ trợ mình ngay nhé ạ!"
                    )
                else:
                    pid = None
                    if isinstance(order_data, dict):
                        pid = order_data.get("product_id")
                        if not pid:
                            items = order_data.get("items", [])
                            if items and isinstance(items, list) and isinstance(items[0], dict):
                                pid = items[0].get("product_id")
                    if not pid:
                        pid = bound_context.get("product_id") or bound_obj.get("product_id")

                    warranty_days = None
                    if pid:
                        prod_res = execute("get_product", {"product_id": pid})
                        if isinstance(prod_res, dict) and not prod_res.get("error"):
                            prod_data = prod_res.get("product", prod_res)
                            if isinstance(prod_data, dict) and prod_data.get("warranty_days") is not None:
                                warranty_days = prod_data["warranty_days"]

                    w_desc = f"{warranty_days} ngày" if warranty_days is not None else "tiêu chuẩn của hãng/shop"
                    action_proposal = {
                        "action": "exchange_1to1",
                        "order_id": extracted_oid,
                        "reason": "Hàng lỗi vận chuyển/kẹt khóa/bung chỉ",
                        "details": f"Đổi mới 1-1 tận nhà (Bảo hành {w_desc})",
                        "status": "pending_staff_approval"
                    }
                    final_content = (
                        f"Dạ shop chân thành xin lỗi anh/chị về sự cố của đơn hàng {extracted_oid}! "
                        f"Shop áp dụng chính sách bảo hành {w_desc} và hỗ trợ Đổi mới 1-1 cho sản phẩm lỗi. "
                        "Em đã xác định được một phương án đổi phù hợp này; nếu anh/chị muốn tiếp tục, hệ thống cần ghi nhận yêu cầu để CSKH xem xét hỗ trợ ạ."
                    )
            else:
                final_content = (
                    "Dạ shop chân thành xin lỗi anh/chị về sự cố sản phẩm gặp lỗi/kẹt khóa/bung chỉ! "
                    "Shop áp dụng chính sách Đổi mới 1-1 tận nhà hoàn toàn miễn phí 2 chiều trong thời hạn bảo hành. "
                    "Anh/chị vui lòng cung cấp Mã đơn hàng (ví dụ: O-101) để em kiểm tra bảo hành và hỗ trợ mình ngay nhé ạ!"
                )
        # Check domain heuristic for SOP 3 (Size Exchange 2-Way)
        elif any(w in lower_msg for w in ["đổi size", "không vừa", "chật", "rộng", "đổi sang size"]):
            if extracted_oid:
                bound_oid = bound_context.get("order_id") or bound_obj.get("order_id")
                is_order_ok = True
                order_data = {}
                if extracted_oid != bound_oid or not (bound_context.get("product_id") or bound_obj.get("product_id")):
                    try:
                        order_res = execute("get_order", {"order_id": extracted_oid})
                        state["tool_count"] += 1
                        is_order_ok = isinstance(order_res, dict) and not order_res.get("error")
                        trace.setdefault("tools", []).append({"name": "get_order", "status": "ok" if is_order_ok else "error"})
                        if is_order_ok and isinstance(order_res, dict):
                            order_data = order_res.get("order", {})
                    except ApiError as exc:
                        if exc.status == 429 or exc.status >= 500:
                            raise
                        is_order_ok = False
                        state["tool_count"] += 1
                        trace.setdefault("tools", []).append({"name": "get_order", "status": "error"})
                    except Exception:
                        is_order_ok = False
                        state["tool_count"] += 1
                        trace.setdefault("tools", []).append({"name": "get_order", "status": "error"})

                if not is_order_ok:
                    action_proposal = None
                    final_content = (
                        f"Dạ em rất tiếc, hệ thống không tìm thấy đơn hàng {extracted_oid} "
                        f"(hoặc đơn không thuộc tài khoản của anh/chị). "
                        "Anh/chị vui lòng kiểm tra lại chính xác Mã đơn hàng để em có thể kiểm tra kho và tạo phiếu đổi size nhé ạ!"
                    )
                else:
                    pid = None
                    if isinstance(order_data, dict):
                        pid = order_data.get("product_id")
                        if not pid:
                            items = order_data.get("items", [])
                            if items and isinstance(items, list) and isinstance(items[0], dict):
                                pid = items[0].get("product_id")
                    if not pid:
                        pid = bound_context.get("product_id") or bound_obj.get("product_id")

                    target_match = re.search(r'(?:đổi sang|sang|đổi)\s+(?:size\s+)?([smlx]|2xl|xl|xxl|\d{2})\b', lower_msg)
                    color_match = re.search(r'\b(trắng|đen|xanh|đỏ|vàng|xám|hồng|be|ghi)\b', lower_msg)

                    target_size = None
                    if target_match:
                        target_size = target_match.group(1).upper()
                    else:
                        all_sizes = re.findall(r'\b(?:size\s+)?([smlx]|2xl|xl|xxl|\d{2})\b', lower_msg)
                        if all_sizes:
                            target_size = all_sizes[-1].upper()

                    target_color = None
                    if color_match:
                        target_color = color_match.group(1).title()
                    elif isinstance(order_data, dict) and order_data.get("variant"):
                        v_str = order_data.get("variant")
                        if "·" in str(v_str):
                            target_color = str(v_str).split("·")[0].strip()
                        elif "/" in str(v_str):
                            target_color = str(v_str).split("/")[0].strip()
                    if not target_color:
                        target_color = "Tiêu chuẩn"

                    if not target_size:
                        action_proposal = None
                        final_content = (
                            f"Dạ shop hỗ trợ đổi size tận nhà miễn phí 2 chiều cho đơn {extracted_oid}! "
                            "Anh/chị vui lòng cho em biết chính xác Size và Màu sắc muốn đổi sang để em kiểm tra kho hỗ trợ mình nhé ạ!"
                        )
                    else:
                        stock_res = {}
                        if pid:
                            stock_res = execute("check_inventory", {"product_id": pid, "size": target_size, "color": target_color})
                            state["tool_count"] += 1
                            trace.setdefault("tools", []).append({"name": "check_inventory", "status": "ok"})

                        if isinstance(stock_res, dict) and (stock_res.get("error") == "variant_not_found" or stock_res.get("status") == "variant_not_found"):
                            action_proposal = None
                            final_content = (
                                f"Dạ em đã kiểm tra kho cho đơn {extracted_oid}: Sản phẩm hiện không có biến thể màu {target_color}, size {target_size} trong danh mục của shop. "
                                "Anh/chị vui lòng tham khảo các màu sắc/kích cỡ có sẵn hoặc liên hệ CSKH để được tư vấn thêm nhé ạ!"
                            )
                        elif isinstance(stock_res, dict) and (stock_res.get("stock") is None or stock_res.get("status") == "stock_unknown"):
                            action_proposal = None
                            final_content = (
                                f"Dạ em đã kiểm tra kho cho đơn {extracted_oid}: Tồn kho của size {target_size} màu {target_color} hiện chưa được cập nhật chính xác trên hệ thống. "
                                "Em sẽ ghi nhận để CSKH kiểm tra kho thực tế và phản hồi lại cho anh/chị nhé ạ!"
                            )
                        else:
                            stock_qty = stock_res.get("stock") if isinstance(stock_res, dict) else 0
                            if stock_qty and stock_qty > 0:
                                action_proposal = {
                                    "action": "size_exchange",
                                    "order_id": extracted_oid,
                                    "target_size": target_size,
                                    "target_color": target_color,
                                    "reason": "Khách mặc không vừa size",
                                    "details": f"Đổi sang size {target_size} (Kho còn {stock_qty} sản phẩm)",
                                    "status": "pending_staff_approval"
                                }
                                final_content = (
                                    f"Dạ em đã kiểm tra kho cho đơn {extracted_oid}: Size {target_size} màu {target_color} hiện còn {stock_qty} sản phẩm. "
                                    "Em đã xác định được một phương án đổi phù hợp này; nếu anh/chị muốn tiếp tục, hệ thống cần ghi nhận yêu cầu để CSKH xem xét hỗ trợ ạ."
                                )
                            else:
                                action_proposal = None
                                final_content = (
                                    f"Dạ em đã kiểm tra kho cho đơn {extracted_oid}: Size {target_size} màu {target_color} hiện tạm thời đã hết hàng trong kho. "
                                    "Anh/chị có thể tham khảo mẫu tương tự hoặc đợi đợt hàng tiếp theo nhé ạ!"
                                )
            else:
                final_content = (
                    "Dạ shop hỗ trợ đổi size tận nhà miễn phí 2 chiều cho anh/chị! "
                    "Anh/chị vui lòng cung cấp Mã đơn hàng và Size/Màu sắc muốn đổi sang để em kiểm tra kho và tạo phiếu hỗ trợ ngay nhé ạ!"
                )
        elif any(w in lower_msg for w in ["hủy đơn", "hủy đơn hàng", "muốn hủy", "huy don", "cancel"]):
            if extracted_oid:
                try:
                    res = execute("prepare_cancellation", {"order_id": extracted_oid, "reason": "Khách yêu cầu hủy qua chat"})
                    state["tool_count"] += 1
                    is_eligible = (
                        isinstance(res, dict)
                        and not res.get("error")
                        and res.get("eligible") is True
                        and res.get("order", {}).get("id") == extracted_oid
                    )
                    if is_eligible:
                        action_proposal = {
                            "action": "cancel_order",
                            "order_id": extracted_oid,
                            "reason": "Khách yêu cầu hủy qua chat",
                            "status": "pending_user_confirmation"
                        }
                        final_content = (
                            f"Dạ em đã ghi nhận yêu cầu hủy đơn hàng {extracted_oid}. "
                            "Em đã mở bảng xem lại đề xuất trên màn hình, anh/chị vui lòng kiểm tra và bấm 'Xác nhận hủy' để hệ thống xử lý an toàn nhé ạ!"
                        )
                    else:
                        action_proposal = None
                        status_desc = res.get("order", {}).get("status") if isinstance(res, dict) else "delivered"
                        final_content = (
                            f"Dạ đơn hàng {extracted_oid} hiện ở trạng thái '{status_desc}', "
                            "shop không thể hỗ trợ hủy đơn qua hệ thống. "
                            "Nếu cần hỗ trợ thêm, anh/chị vui lòng liên hệ nhân viên CSKH để được trợ giúp nhé ạ!"
                        )
                except ApiError as exc:
                    if exc.status == 429 or exc.status >= 500:
                        raise
                    action_proposal = None
                    final_content = f"Dạ đơn hàng {extracted_oid} không thể hủy vào lúc này. Vui lòng liên hệ CSKH để được hỗ trợ ạ."
            else:
                final_content = "Dạ anh/chị vui lòng cung cấp Mã đơn hàng cần hủy để em kiểm tra trạng thái hỗ trợ mình nhé ạ!"
        elif action_proposal and action_proposal["action"] == "cancel_order":
            final_content = (
                f"Dạ em đã ghi nhận yêu cầu hủy đơn hàng {action_proposal['order_id']} với lý do: "
                f"'{action_proposal['reason']}'. "
                "Em đã mở bảng xem lại đề xuất trên màn hình, anh/chị vui lòng kiểm tra và bấm 'Xác nhận hủy' để hệ thống xử lý an toàn nhé ạ!"
            )
        else:
            final_content = message.get("content", "Dạ shop rất tiếc vì trải nghiệm chưa trọn vẹn này của anh/chị. Anh/chị cho em xin mã đơn hàng và tình trạng gặp phải để em hỗ trợ xử lý ngay nhé ạ!")

    except ApiError as exc:
        if exc.status == 429 or exc.status >= 500:
            raise
        import logging
        logging.getLogger("retailops.dispute_agent").warning("Dispute agent execution ApiError: %s", exc)
        final_content = "Dạ shop đã ghi nhận phản hồi của anh/chị và sẽ ưu tiên kiểm tra xử lý ngay ạ!"
    except Exception as exc:
        import logging
        logging.getLogger("retailops.dispute_agent").warning("Dispute agent execution fallback: %s", exc)
        final_content = "Dạ shop đã ghi nhận phản hồi của anh/chị và sẽ ưu tiên kiểm tra xử lý ngay ạ!"

    if action_proposal:
        state["action_proposal"] = action_proposal

    msg = {"role": "assistant", "content": final_content}
    state["messages"].append(msg)
    state["fresh"].append(msg)
    state["complete"] = True
    state["subagent_history"].append("dispute_agent:proposal_ready" if state.get("action_proposal") else "dispute_agent:listening")
    return state
