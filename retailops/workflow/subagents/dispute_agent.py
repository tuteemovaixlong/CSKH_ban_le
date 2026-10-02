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
    try:
        from retailops_agent import AgentError
    except Exception:
        AgentError = ()
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
    final_content = None
    refusal_set = False
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
                    if name == "prepare_cancellation":
                        arg_oid = args.get("order_id")
                        if isinstance(arg_oid, str) and arg_oid.upper().startswith('O0'):
                            arg_oid = 'O-' + arg_oid[2:]

                        bound_oid = bound_context.get("order_id") or bound_obj.get("order_id")
                        target_oid = extracted_oid or bound_oid

                        # N01: Kiểm tra tính hợp lệ của target TRƯỚC KHI gọi tool có side effect!
                        if not target_oid or (arg_oid and target_oid and arg_oid != target_oid):
                            action_proposal = None
                            refusal_set = True
                            if not target_oid:
                                final_content = "Dạ anh/chị vui lòng cung cấp Mã đơn hàng cần hủy để em kiểm tra trạng thái hỗ trợ mình nhé ạ!"
                            else:
                                final_content = (
                                    f"Dạ anh/chị đang trao đổi về đơn hàng {target_oid} nhưng hệ thống nhận diện mã đơn {arg_oid}. "
                                    "Để đảm bảo an toàn, anh/chị vui lòng xác nhận chính xác mã đơn cần hủy nhé ạ!"
                                )
                            execute("clear_cancellation", {})
                            continue

                        result = execute(name, args)
                        state["tool_count"] += 1
                        trace.setdefault("tools", []).append({"name": name, "status": "error" if isinstance(result, dict) and result.get("error") else "ok"})
                        tool_content = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
                        tool_entry = {"role": "tool", "tool_name": name, "content": tool_content}
                        prompt_messages.append(message)
                        prompt_messages.append(tool_entry)

                        chosen_oid = arg_oid or target_oid
                        is_eligible = (
                            isinstance(result, dict)
                            and not result.get("error")
                            and result.get("eligible") is True
                            and result.get("order", {}).get("id") == chosen_oid
                            and chosen_oid == target_oid
                        )
                        if is_eligible:
                            action_proposal = {
                                "action": "cancel_order",
                                "order_id": chosen_oid,
                                "reason": args.get("reason", "Khách yêu cầu hủy qua chat"),
                                "status": "pending_user_confirmation"
                            }
                            refusal_set = True
                            final_content = (
                                f"Dạ em đã ghi nhận yêu cầu hủy đơn hàng {chosen_oid}. "
                                "Em đã mở bảng xem lại đề xuất trên màn hình, anh/chị vui lòng kiểm tra và bấm 'Xác nhận hủy' để hệ thống xử lý an toàn nhé ạ!"
                            )
                        else:
                            action_proposal = None
                            refusal_set = True
                            execute("clear_cancellation", {})
                            status_desc = result.get("order", {}).get("status") if isinstance(result, dict) else "delivered"
                            final_content = (
                                f"Dạ đơn hàng {chosen_oid} hiện ở trạng thái '{status_desc}', "
                                "shop không thể hỗ trợ hủy đơn qua hệ thống. "
                                "Nếu cần hỗ trợ thêm, anh/chị vui lòng liên hệ nhân viên CSKH để được trợ giúp nhé ạ!"
                            )
                    else:
                        result = execute(name, args)
                        state["tool_count"] += 1
                        trace.setdefault("tools", []).append({"name": name, "status": "error" if isinstance(result, dict) and result.get("error") else "ok"})
                        tool_content = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
                        tool_entry = {"role": "tool", "tool_name": name, "content": tool_content}
                        prompt_messages.append(message)
                        prompt_messages.append(tool_entry)

        # Check domain heuristic for SOP 2 (Defect / Warranty Exchange 1-1)
        if any(w in lower_msg for w in ["kẹt khóa", "bung chỉ", "hỏng khóa", "lỗi chỉ", "rách", "đổi 1-1", "đổi mới", "bảo hành"]):
            if extracted_oid:
                bound_oid = bound_context.get("order_id") or bound_obj.get("order_id")
                is_order_ok = True
                order_data = {}
                # N02: Luôn gọi get_order để revalidate quyền sở hữu mới nhất
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
                    # G07: ONLY reuse bound product if bound order is the exact SAME order as extracted_oid!
                    if not pid and bound_oid == extracted_oid:
                        pid = bound_context.get("product_id") or bound_obj.get("product_id")

                    if not pid:
                        action_proposal = None
                        final_content = (
                            f"Dạ em rất tiếc, hệ thống chưa xác định được thông tin sản phẩm của đơn hàng {extracted_oid}. "
                            "Anh/chị vui lòng kiểm tra lại đơn hàng hoặc liên hệ CSKH để được hỗ trợ kiểm tra bảo hành chính xác nhé ạ!"
                        )
                    else:
                        warranty_days = None
                        try:
                            prod_res = execute("get_product", {"product_id": pid})
                            state["tool_count"] += 1
                            if isinstance(prod_res, dict) and not prod_res.get("error"):
                                prod_data = prod_res.get("product", prod_res)
                                if isinstance(prod_data, dict) and prod_data.get("warranty_days") is not None:
                                    warranty_days = prod_data["warranty_days"]
                        except ApiError as exc:
                            if exc.status == 429 or exc.status >= 500:
                                raise
                        except Exception:
                            pass

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
                # G08: Luôn lấy order_data để bảo toàn màu sắc và biến thể gốc của đơn hàng
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
                    if not pid and bound_oid == extracted_oid:
                        pid = bound_context.get("product_id") or bound_obj.get("product_id")

                    # N05: Nếu đơn không có product_id liên kết, từ chối rõ ràng và KHÔNG nói đã kiểm tra kho
                    if not pid:
                        action_proposal = None
                        final_content = (
                            f"Dạ em rất tiếc, đơn hàng {extracted_oid} hiện chưa có thông tin liên kết sản phẩm trên hệ thống để kiểm tra kho tự động. "
                            "Anh/chị vui lòng liên hệ nhân viên CSKH để được hỗ trợ kiểm tra phương án đổi size phù hợp nhé ạ!"
                        )
                    else:
                        catalog_variants = []
                        catalog_colors = []
                        catalog_sizes = []
                        try:
                            prod_res = execute("get_product", {"product_id": pid})
                            state["tool_count"] += 1
                            if isinstance(prod_res, dict) and not prod_res.get("error"):
                                prod_data = prod_res.get("product", {})
                                catalog_variants = prod_data.get("variants", [])
                                for v in (catalog_variants or []):
                                    parts = re.split(r'[/·,\-]', str(v))
                                    if parts:
                                        c_name = parts[0].strip().title()
                                        if c_name not in catalog_colors:
                                            catalog_colors.append(c_name)
                                        if len(parts) > 1:
                                            s_m = re.search(r'(?:size\s+)?([a-zA-Z0-9]+)', parts[1], re.IGNORECASE)
                                            if s_m and s_m.group(1).upper() not in catalog_sizes:
                                                catalog_sizes.append(s_m.group(1).upper())
                        except ApiError as exc:
                            if exc.status == 429 or exc.status >= 500:
                                raise
                        except Exception:
                            pass

                        # N04: Trích xuất size động, tránh match nhầm số mã đơn và đòi hỏi tiền tố size hoặc động từ đổi
                        search_text_for_size = re.sub(r'\b(?:o-\d+|o\d+|dh\d+|\d{5,})\b', '', lower_msg, flags=re.IGNORECASE)
                        size_pattern = r'(?:(?:đổi\s+sang|sang|đổi|lên|xuống)\s+(?:size\s+)?|(?:size\s+))\b(2xs|xs|s|m|l|xl|2xl|3xl|4xl|5xl|xxl|\d{1,2})\b'
                        all_sizes = re.findall(size_pattern, search_text_for_size, re.IGNORECASE)
                        target_size = None
                        if all_sizes:
                            target_size = all_sizes[-1].upper()
                        elif catalog_sizes:
                            for s in catalog_sizes:
                                if re.search(rf'(?:(?:đổi\s+sang|sang|đổi|lên|xuống)\s+(?:size\s+)?|(?:size\s+))\b{re.escape(s)}\b', search_text_for_size, re.IGNORECASE):
                                    target_size = s.upper()
                                    break

                        # N04: Phân biệt màu cũ và màu muốn đổi (phần sau từ khóa đổi/sang là màu cần tìm)
                        change_parts = re.split(r'\b(?:muốn đổi|đổi sang|đổi|sang)\b', lower_msg)
                        target_search_text = change_parts[-1] if len(change_parts) > 1 else lower_msg

                        target_color = None
                        sorted_colors = sorted(catalog_colors, key=len, reverse=True)
                        for c in sorted_colors:
                            if c.lower() in target_search_text:
                                target_color = c
                                break
                            elif c.lower() in lower_msg and len(change_parts) == 1:
                                target_color = c
                                break

                        # Kiểm tra xem người dùng có yêu cầu màu cụ thể mà catalog không có không
                        explicit_color_requested = False
                        requested_color_name = ""
                        if not target_color:
                            m_match = re.search(r'màu\s+([a-zA-Z\u00C0-\u024F\u1EA0-\u1EF9]+(?:\s+[a-zA-Z\u00C0-\u024F\u1EA0-\u1EF9]+)?)', target_search_text)
                            if m_match:
                                extracted_phrase = m_match.group(1).strip().title()
                                found_in_cat = False
                                for c in sorted_colors:
                                    if c.lower() == extracted_phrase.lower() or c.lower().startswith(extracted_phrase.lower()):
                                        target_color = c
                                        found_in_cat = True
                                        break
                                if not found_in_cat:
                                    explicit_color_requested = True
                                    requested_color_name = extracted_phrase

                        # Nếu người dùng không nêu màu mới, lấy màu gốc từ đơn hoặc catalog đơn sắc
                        if not target_color and not explicit_color_requested:
                            if isinstance(order_data, dict) and order_data.get("variant"):
                                v_str = order_data.get("variant")
                                parts = re.split(r'[/·,\-]', str(v_str))
                                if parts:
                                    orig_color = parts[0].strip().title()
                                    if orig_color in catalog_colors or not catalog_colors:
                                        target_color = orig_color
                            elif len(catalog_colors) == 1:
                                target_color = catalog_colors[0]

                        if explicit_color_requested:
                            action_proposal = None
                            final_content = (
                                f"Dạ em rất tiếc, sản phẩm của đơn {extracted_oid} hiện không có biến thể màu {requested_color_name} trong danh mục của shop. "
                                f"Shop hiện có các màu: {', '.join(catalog_colors) if catalog_colors else 'mặc định'}. "
                                "Anh/chị vui lòng chọn màu có sẵn để em kiểm tra kho hỗ trợ mình nhé ạ!"
                            )
                        elif not target_size:
                            action_proposal = None
                            final_content = (
                                f"Dạ shop hỗ trợ đổi size tận nhà miễn phí 2 chiều cho đơn {extracted_oid}! "
                                "Anh/chị vui lòng cho em biết chính xác Size muốn đổi sang để em kiểm tra kho hỗ trợ mình nhé ạ!"
                            )
                        elif not target_color:
                            action_proposal = None
                            final_content = (
                                f"Dạ shop hỗ trợ đổi size tận nhà miễn phí 2 chiều cho đơn {extracted_oid}! "
                                "Anh/chị vui lòng cho em biết chính xác Màu sắc muốn đổi sang để em kiểm tra kho hỗ trợ mình nhé ạ!"
                            )
                        else:
                            stock_res = {}
                            try:
                                stock_res = execute("check_inventory", {"product_id": pid, "size": target_size, "color": target_color})
                                state["tool_count"] += 1
                                trace.setdefault("tools", []).append({"name": "check_inventory", "status": "ok"})
                            except ApiError as exc:
                                if exc.status == 429 or exc.status >= 500:
                                    raise
                                stock_res = {"error": exc.code}

                            if isinstance(stock_res, dict) and (stock_res.get("error") == "variant_not_found" or stock_res.get("status") == "variant_not_found"):
                                action_proposal = None
                                final_content = (
                                    f"Dạ em đã kiểm tra kho cho đơn {extracted_oid}: Sản phẩm hiện không có biến thể màu {target_color}, size {target_size} trong danh mục của shop. "
                                    "Anh/chị vui lòng tham khảo các màu sắc/kích cỡ có sẵn hoặc liên hệ CSKH để được tư vấn thêm nhé ạ!"
                                )
                            elif isinstance(stock_res, dict) and (stock_res.get("stock") is None or stock_res.get("status") == "stock_unknown"):
                                action_proposal = None
                                final_content = (
                                    f"Dạ em đã kiểm tra kho cho đơn {extracted_oid}: Tồn kho của size {target_size} màu {target_color} hiện chưa thể xác nhận tự động trên hệ thống. "
                                    "Anh/chị vui lòng liên hệ nhân viên CSKH để được hỗ trợ kiểm tra kho thực tế nhé ạ!"
                                )
                            else:
                                stock_qty = stock_res.get("stock") if isinstance(stock_res, dict) else 0
                                if stock_qty and stock_qty > 0:
                                    action_proposal = {
                                        "action": "size_exchange",
                                        "order_id": extracted_oid,
                                        "target_size": target_size,
                                        "target_color": target_color,
                                        "product_id": pid,
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
        elif any(w in lower_msg for w in ["hủy đơn", "hủy hàng", "hủy giúp", "muốn hủy", "huy don", "huy hang", "cancel"]):
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
                        refusal_set = True
                        final_content = (
                            f"Dạ em đã ghi nhận yêu cầu hủy đơn hàng {extracted_oid}. "
                            "Em đã mở bảng xem lại đề xuất trên màn hình, anh/chị vui lòng kiểm tra và bấm 'Xác nhận hủy' để hệ thống xử lý an toàn nhé ạ!"
                        )
                    else:
                        action_proposal = None
                        refusal_set = True
                        execute("clear_cancellation", {})
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
                    refusal_set = True
                    execute("clear_cancellation", {})
                    final_content = f"Dạ đơn hàng {extracted_oid} không thể hủy vào lúc này. Vui lòng liên hệ CSKH để được hỗ trợ ạ."
            else:
                execute("clear_cancellation", {})
                final_content = "Dạ anh/chị vui lòng cung cấp Mã đơn hàng cần hủy để em kiểm tra trạng thái hỗ trợ mình nhé ạ!"
        elif action_proposal and action_proposal["action"] == "cancel_order":
            final_content = (
                f"Dạ em đã ghi nhận yêu cầu hủy đơn hàng {action_proposal['order_id']} với lý do: "
                f"'{action_proposal['reason']}'. "
                "Em đã mở bảng xem lại đề xuất trên màn hình, anh/chị vui lòng kiểm tra và bấm 'Xác nhận hủy' để hệ thống xử lý an toàn nhé ạ!"
            )
        else:
            if not final_content:
                final_content = message.get("content") or "Dạ shop rất tiếc vì trải nghiệm chưa trọn vẹn này của anh/chị. Anh/chị cho em xin mã đơn hàng và tình trạng gặp phải để em hỗ trợ xử lý ngay nhé ạ!"

    except ApiError as exc:
        if exc.status == 429 or exc.status >= 500:
            raise
        final_content = "Dạ shop đã ghi nhận thông tin và sẽ hỗ trợ anh/chị xử lý ạ."
    except AgentError:
        # G03: Always propagate provider errors (429/5xx/timeout) out to application and client!
        raise
    except Exception as exc:
        if type(exc).__name__ == "AgentError":
            raise
        if isinstance(exc, (TimeoutError, ConnectionError)):
            raise ApiError(503, 'service_unavailable', 'Dịch vụ tạm thời gián đoạn.') from exc
        raise

    if action_proposal:
        state["action_proposal"] = action_proposal

    msg = {"role": "assistant", "content": final_content}
    state["messages"].append(msg)
    state["fresh"].append(msg)
    state["complete"] = True
    state["subagent_history"].append("dispute_agent:proposal_ready" if state.get("action_proposal") else "dispute_agent:listening")
    return state
