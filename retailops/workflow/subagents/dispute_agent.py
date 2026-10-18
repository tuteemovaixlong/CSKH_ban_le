"""Dispute & Refund Subagent.
Handles cancellations, complaints, and refunds with strict human-in-the-loop proposals.
Never executes mutations directly!
"""
import copy
import json
import re
from typing import Any

from retailops.core import ApiError
from retailops.guardrails.topic_filter import is_read_only_lookup_intent
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

_DEFECT_WARRANTY_QUERY_TERMS = (
    "kẹt khóa", "bung chỉ", "hỏng khóa", "lỗi chỉ", "lỗi đường may", "bung đường may",
    "sứt chỉ", "đứt chỉ", "gãy khóa", "bung cúc", "đứt cúc", "rách", "bị thủng",
    "đường chỉ bị lệch", "đường may bị lệch", "lệch đường may", "lệch chỉ", "chỉ bị lệch",
    "đường chỉ lệch", "đường may lệch", "may bị lệch", "may lệch",
    "tuột chỉ", "sút chỉ", "rút chỉ",
    "đổi 1-1", "1 đổi 1", "đổi mới", "bảo hành",
    "sản phẩm lỗi", "hàng lỗi", "lỗi sản phẩm", "bị lỗi", "lỗi",
    "bị hỏng", "hư hỏng", "bị hư", "hỏng", "hư",
    "trầy xước", "bị xước", "bị trầy", "móp méo", "bị vỡ", "bị nứt", "bị bể",
    "ố màu", "phai màu", "loang màu", "lem màu", "bị bẩn", "xù lông", "kém chất lượng",
    "ket khoa", "bung chi", "hong khoa", "loi chi", "loi duong may", "bung duong may",
    "sut chi", "dut chi", "gay khoa", "bung cuc", "dut cuc", "rach", "bi thung",
    "duong chi bi lech", "duong may bi lech", "lech duong may", "lech chi", "chi bi lech",
    "duong chi lech", "duong may lech", "may bi lech", "may lech",
    "tuot chi", "sut chi", "rut chi",
    "doi 1-1", "1 doi 1", "doi moi", "bao hanh",
    "san pham loi", "hang loi", "loi san pham", "bi loi", "loi",
    "bi hong", "hu hong", "bi hu", "hong", "hu",
    "tray xuoc", "bi xuoc", "bi tray", "mop meo", "bi vo", "bi nut", "bi be",
    "o mau", "phai mau", "loang mau", "lem mau", "bi ban", "xu long", "kem chat luong",
)

_EXCERPT_EXCLUSION_PATTERNS = (
    "không áp dụng", "không được áp dụng", "không thuộc phạm vi", "không nằm trong phạm vi",
    "không hỗ trợ", "không được hỗ trợ", "không bảo hành", "không được bảo hành",
    "không nhận bảo hành", "không đổi mới", "không được đổi mới", "không đổi 1-1",
    "không nhận đổi", "không giải quyết", "không tiếp nhận", "không chịu trách nhiệm",
    "không bao gồm", "loại trừ", "ngoại trừ", "từ chối bảo hành", "từ chối đổi",
    "từ chối", "miễn trừ", "chưa áp dụng", "chưa hỗ trợ", "chưa có chính sách",
    "không bị lỗi", "không lỗi", "không rách", "không hư hỏng", "không hỏng",
    "chỉ áp dụng đổi size", "chỉ áp dụng cho sản phẩm nguyên tem",
    "khong ap dung", "khong duoc ap dung", "khong thuoc pham vi", "khong nam trong pham vi",
    "khong ho tro", "khong duoc ho tro", "khong bao hanh", "khong duoc bao hanh",
    "khong nhan bao hanh", "khong doi moi", "khong duoc doi moi", "khong doi 1-1",
    "khong nhan doi", "khong giai quyet", "khong tiep nhan", "khong chiu trach nhiem",
    "khong bao gom", "loai tru", "ngoai tru", "tu choi bao hanh", "tu choi doi",
    "tu choi", "mien tru", "chua ap dung", "chua ho tro", "chua co chinh sach",
    "khong bi loi", "khong loi", "khong rach", "khong hu hong", "khong hong",
    "chi ap dung doi size", "chi ap dung cho san pham nguyen tem",
)

_EXCERPT_DEFECT_SUBJECT_TERMS = (
    "bảo hành", "đổi mới", "đổi 1-1", "1 đổi 1",
    "hàng lỗi", "sản phẩm lỗi", "lỗi sản phẩm", "bị lỗi",
    "lỗi từ nhà sản xuất", "lỗi nhà sản xuất", "lỗi sản xuất", "lỗi kỹ thuật", "lỗi vận chuyển",
    "lỗi đường may", "bung đường may", "bung chỉ", "lỗi chỉ", "sứt chỉ", "đứt chỉ",
    "đường chỉ bị lệch", "đường may bị lệch", "lệch đường may", "lệch chỉ", "chỉ bị lệch",
    "đường chỉ lệch", "đường may lệch", "may bị lệch", "may lệch",
    "tuột chỉ", "sút chỉ", "rút chỉ",
    "kẹt khóa", "hỏng khóa", "gãy khóa", "rách", "hư hỏng", "trầy xước", "móp méo",
    "bao hanh", "doi moi", "doi 1-1", "1 doi 1",
    "hang loi", "san pham loi", "loi san pham", "bi loi",
    "loi tu nha san xuat", "loi nha san xuat", "loi san xuat", "loi ky thuat", "loi van chuyen",
    "loi duong may", "bung duong may", "bung chi", "loi chi", "sut chi", "dut chi",
    "duong chi bi lech", "duong may bi lech", "lech duong may", "lech chi", "chi bi lech",
    "duong chi lech", "duong may lech", "may bi lech", "may lech",
    "tuot chi", "sut chi", "rut chi",
    "ket khoa", "hong khoa", "gay khoa", "rach", "hu hong", "tray xuoc", "mop meo",
)

_EXCERPT_AFFIRMATIVE_REMEDY_TERMS = (
    "đổi mới", "đổi 1-1", "1 đổi 1", "hỗ trợ đổi", "được đổi", "áp dụng đổi", "sẽ đổi",
    "thay sản phẩm", "thay mới", "gửi bù",
    "hỗ trợ bảo hành", "được bảo hành", "áp dụng bảo hành", "áp dụng chính sách bảo hành",
    "chính sách bảo hành:", "quy định bảo hành:", "bảo hành miễn phí",
    "doi moi", "doi 1-1", "1 doi 1", "ho tro doi", "duoc doi", "ap dung doi", "se doi",
    "thay san pham", "thay moi", "gui bu",
    "ho tro bao hanh", "duoc bao hanh", "ap dung bao hanh", "ap dung chinh sach bao hanh",
    "chinh sach bao hanh:", "quy dinh bao hanh:", "bao hanh mien phi",
)

_UNSUPPORTED_REMEDY_TERMS = (
    "đổi mới", "đổi 1-1", "1-1", "1 đổi 1", "đổi hàng", "đổi trả", "trả hàng",
    "thay sản phẩm", "thay mới", "gửi bù", "gửi lại", "đền bù", "bồi thường",
    "hoàn tiền", "bảo hành", "miễn phí", "freeship", "2 chiều",
    "áp dụng chính sách", "quy định đổi", "hỗ trợ đổi", "sẽ đổi", "được đổi",
    "doi moi", "doi 1-1", "1 doi 1", "doi hang", "doi tra", "tra hang",
    "thay san pham", "thay moi", "gui bu", "gui lai", "den bu", "boi thuong",
    "hoan tien", "bao hanh", "mien phi", "2 chieu",
    "ap dung chinh sach", "quy dinh doi", "ho tro doi", "se doi", "duoc doi",
)

_WARRANTY_REPLACEMENT_PROMISE_TERMS = (
    "đổi mới", "đổi 1-1", "1-1", "1 đổi 1", "thay sản phẩm", "thay mới", "gửi bù",
    "bảo hành", "sản phẩm lỗi", "hàng lỗi",
    "doi moi", "doi 1-1", "1 doi 1", "thay san pham", "thay moi", "gui bu",
    "bao hanh", "san pham loi", "hang loi",
)

_SAFE_HANDOFF_TERMS = ("cskh", "chuyên viên", "nhân viên tư vấn", "nhân viên cskh")


def _has_whole_term(text: str, terms: Any) -> bool:
    for term in terms:
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text):
            return True
    return False


def _is_defect_warranty_query(user_msg: str) -> bool:
    cleaned = (user_msg or "").lower()
    for benign in ("xin lỗi", "xin loi", "trả lời", "tra loi", "thứ lỗi", "thu loi", "màu hồng", "mau hong", "hoa hồng", "hoa hong"):
        cleaned = cleaned.replace(benign, " ")
    return _has_whole_term(cleaned, _DEFECT_WARRANTY_QUERY_TERMS)


def _excerpt_supports_defect_warranty(excerpt: Any) -> bool:
    if not isinstance(excerpt, str) or not excerpt.strip():
        return False
    lower_excerpt = excerpt.lower()
    if any(pat in lower_excerpt for pat in _EXCERPT_EXCLUSION_PATTERNS):
        return False

    benign_negations = (
        "không mất phí", "không tốn phí", "không tính phí", "không thu phí",
        "không cần", "không giới hạn",
        "khong mat phi", "khong ton phi", "khong tinh phi", "khong thu phi",
        "khong can", "khong gioi han",
    )
    clause_negations = (
        "không", "khong", "chưa", "chua", "loại trừ", "loai tru",
        "ngoại trừ", "ngoai tru", "từ chối", "tu choi", "miễn trừ", "mien tru",
        "trừ khi", "tru khi", "trừ trường hợp", "tru truong hop",
    )

    for raw_clause in re.split(r"[.!?\n;]+", lower_excerpt):
        clause = raw_clause.strip()
        if not clause:
            continue
        cleaned_clause = clause
        for benign in benign_negations:
            cleaned_clause = cleaned_clause.replace(benign, " ")
        if _has_whole_term(cleaned_clause, clause_negations):
            continue
        has_subject = _has_whole_term(cleaned_clause, _EXCERPT_DEFECT_SUBJECT_TERMS)
        has_remedy = (
            any(term in cleaned_clause for term in _EXCERPT_AFFIRMATIVE_REMEDY_TERMS)
            or bool(re.search(r"bảo hành\s+\d+\s*(?:ngày|tháng|năm)|bao hanh\s+\d+\s*(?:ngay|thang|nam)", cleaned_clause))
        )
        if has_subject and has_remedy:
            return True
    return False


def _is_relevant_defect_warranty_evidence(search_res: Any, user_msg: str = "") -> bool:
    """Check if retrieved knowledge results actually establish relevant defect/warranty policy."""
    if not isinstance(search_res, dict) or search_res.get("error"):
        return False
    results = search_res.get("results")
    if not results or not isinstance(results, list):
        return False

    for doc in results:
        if not isinstance(doc, dict):
            continue
        if _excerpt_supports_defect_warranty(doc.get("excerpt", "")):
            return True
    return False



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
    read_only_lookup = is_read_only_lookup_intent(last_user_msg)

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
    knowledge_called = False
    knowledge_has_evidence = False
    knowledge_has_defect_warranty_evidence = False
    retrieved_citations: list[str] = []
    trace = state.setdefault("trace", {})
    try:
        response = gateway.chat(prompt_messages, True, timeout)
        trace["model_calls"] = trace.get("model_calls", 0) + 1
        trace["prompt_tokens"] = trace.get("prompt_tokens", 0) + (response.get("prompt_eval_count") or 0)
        trace["generated_tokens"] = trace.get("generated_tokens", 0) + (response.get("eval_count") or 0)
        if response.get("reasoning"):
            trace["reasoning"] = str(response["reasoning"])
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
                    if name == "prepare_cancellation" and read_only_lookup:
                        execute("clear_cancellation", {})
                        action_proposal = None
                        lookup_oid = args.get("order_id") or extracted_oid
                        if lookup_oid:
                            result = execute("get_order", {"order_id": lookup_oid})
                            state["tool_count"] += 1
                            trace.setdefault("tools", []).append({"name": "get_order", "status": "error" if isinstance(result, dict) and result.get("error") else "ok"})
                        continue
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
                            ord_obj = result.get("order", {}) if isinstance(result, dict) else {}
                            raw_reason = args.get("reason", "ordered_by_mistake")
                            canonical_reason = raw_reason if raw_reason in ("ordered_by_mistake", "no_longer_needed") else "ordered_by_mistake"
                            action_proposal = {
                                "action": "cancel_order",
                                "order_id": chosen_oid,
                                "order_version": ord_obj.get("version", 1),
                                "reason": canonical_reason,
                                "cancel_reason": canonical_reason,
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
                            if isinstance(result, dict) and (result.get("error") or not result.get("order")):
                                final_content = (
                                    f"Dạ em rất tiếc, hệ thống không tìm thấy đơn hàng {chosen_oid} "
                                    f"(hoặc đơn không thuộc tài khoản của anh/chị). "
                                    "Anh/chị vui lòng kiểm tra lại chính xác Mã đơn hàng để em hỗ trợ nhé ạ!"
                                )
                            else:
                                status_desc = result.get("order", {}).get("status") if (isinstance(result, dict) and result.get("order")) else "delivered"
                                final_content = (
                                    f"Dạ đơn hàng {chosen_oid} hiện ở trạng thái '{status_desc}', "
                                    "shop không thể hỗ trợ hủy đơn qua hệ thống. "
                                    "Nếu cần hỗ trợ thêm, anh/chị vui lòng liên hệ nhân viên CSKH để được trợ giúp nhé ạ!"
                                )
                    else:
                        if name == "search_knowledge":
                            knowledge_called = True
                        result = execute(name, args)
                        if name == "search_knowledge":
                            if _is_relevant_defect_warranty_evidence(result, last_user_msg):
                                knowledge_has_defect_warranty_evidence = True
                            if isinstance(result, dict) and not result.get("error"):
                                res_list = result.get("results")
                                if isinstance(res_list, list):
                                    for doc in res_list:
                                        if isinstance(doc, dict) and bool(str(doc.get("excerpt") or "").strip()):
                                            knowledge_has_evidence = True
                                            cid_val = str(doc.get("citation_id") or "").strip()
                                            if cid_val and cid_val not in retrieved_citations:
                                                retrieved_citations.append(cid_val)
                        state["tool_count"] += 1
                        trace.setdefault("tools", []).append({"name": name, "status": "error" if isinstance(result, dict) and result.get("error") else "ok"})
                        tool_content = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
                        tool_entry = {"role": "tool", "tool_name": name, "content": tool_content}
                        prompt_messages.append(message)
                        prompt_messages.append(tool_entry)

            if not refusal_set and not final_content:
                try:
                    second_resp = gateway.chat(prompt_messages, False, timeout)
                    trace["model_calls"] = trace.get("model_calls", 0) + 1
                    trace["prompt_tokens"] = trace.get("prompt_tokens", 0) + (second_resp.get("prompt_eval_count") or 0)
                    trace["generated_tokens"] = trace.get("generated_tokens", 0) + (second_resp.get("eval_count") or 0)
                    if second_resp.get("reasoning"):
                        trace["reasoning"] = str(second_resp["reasoning"])
                    second_msg = second_resp.get("message", {})
                    if second_msg.get("content"):
                        final_content = second_msg.get("content")
                except (AgentError, ApiError, TimeoutError):
                    raise
                except Exception:
                    pass

        is_defect_query = _is_defect_warranty_query(last_user_msg)
        lower_final = (final_content or "").lower()
        has_warranty_promise = any(term in lower_final for term in _WARRANTY_REPLACEMENT_PROMISE_TERMS)
        has_unsupported = any(term in lower_final for term in _UNSUPPORTED_REMEDY_TERMS)
        has_safe_handoff = any(k in lower_final for k in _SAFE_HANDOFF_TERMS)

        knowledge_no_evidence = False
        if knowledge_called:
            if is_defect_query and not knowledge_has_defect_warranty_evidence:
                knowledge_no_evidence = True
            elif not knowledge_has_evidence:
                knowledge_no_evidence = True
            elif has_warranty_promise and not knowledge_has_defect_warranty_evidence:
                # R4-A: unrelated retrieval (shipping/returns/size) must NOT ground an unsupported warranty promise
                knowledge_no_evidence = True

        if knowledge_no_evidence:
            refusal_set = True
            action_proposal = None
            state["drop_knowledge_sources"] = True
            if not final_content or has_unsupported or not has_safe_handoff:
                final_content = (
                    "Dạ hiện tại kho tri thức chính sách của shop chưa có tài liệu quy định phù hợp cho nội dung này. "
                    "Để đảm bảo quyền lợi khiếu nại của anh/chị, em xin phép ghi nhận thông tin và chuyển chuyên viên CSKH hỗ trợ trực tiếp, "
                    "không tự ý áp dụng quy định chưa được xác thực nhé ạ!"
                )

        # Check domain heuristic for SOP 2 (Defect / Warranty Exchange 1-1)
        if not refusal_set and (is_defect_query or has_warranty_promise):
            if extracted_oid:
                bound_oid = bound_context.get("order_id") or bound_obj.get("order_id")
                is_order_ok = True
                order_data = {}
                # N02 & P5-K7: Luôn gọi get_order để revalidate quyền sở hữu mới nhất (kể cả khi search_knowledge có kết quả)
                try:
                    order_res = execute("get_order", {"order_id": extracted_oid})
                    state["tool_count"] += 1
                    is_order_ok = isinstance(order_res, dict) and not order_res.get("error") and bool(order_res.get("order"))
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
                    refusal_set = True
                    state["drop_knowledge_sources"] = True
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
                        refusal_set = True
                        state["drop_knowledge_sources"] = True
                        final_content = (
                            f"Dạ em rất tiếc, hệ thống chưa xác định được thông tin sản phẩm của đơn hàng {extracted_oid}. "
                            "Anh/chị vui lòng kiểm tra lại đơn hàng hoặc liên hệ CSKH để được hỗ trợ kiểm tra bảo hành chính xác nhé ạ!"
                        )
                    else:
                        warranty_days = None
                        try:
                            prod_res = execute("get_product", {"product_id": pid})
                            state["tool_count"] += 1
                            is_prod_ok = isinstance(prod_res, dict) and not prod_res.get("error")
                            trace.setdefault("tools", []).append({"name": "get_product", "status": "ok" if is_prod_ok else "error"})
                            if is_prod_ok:
                                prod_data = prod_res.get("product", prod_res)
                                if isinstance(prod_data, dict) and prod_data.get("warranty_days") is not None:
                                    warranty_days = prod_data["warranty_days"]
                        except ApiError as exc:
                            if exc.status == 429 or exc.status >= 500:
                                raise
                            trace.setdefault("tools", []).append({"name": "get_product", "status": "error"})
                        except Exception:
                            trace.setdefault("tools", []).append({"name": "get_product", "status": "error"})

                        if warranty_days is None:
                            action_proposal = None
                            refusal_set = True
                            state["drop_knowledge_sources"] = True
                            final_content = (
                                f"Dạ em rất tiếc, hệ thống chưa xác định được thời hạn bảo hành của sản phẩm thuộc đơn hàng {extracted_oid}. "
                                "Anh/chị vui lòng liên hệ nhân viên CSKH để được hỗ trợ kiểm tra bảo hành và xử lý khiếu nại chính xác nhé ạ!"
                            )
                        else:
                            w_desc = f"{warranty_days} ngày"
                            cite_suffix = f" [{retrieved_citations[0]}]" if retrieved_citations else ""
                            action_proposal = {
                                "action": "exchange_1to1",
                                "order_id": extracted_oid,
                                "reason": "Hàng lỗi vận chuyển/kẹt khóa/bung chỉ",
                                "details": f"Đổi mới 1-1 tận nhà (Bảo hành {w_desc})",
                                "status": "pending_staff_approval"
                            }
                            final_content = (
                                f"Dạ shop chân thành xin lỗi anh/chị về sự cố của đơn hàng {extracted_oid}! "
                                f"Shop áp dụng chính sách bảo hành {w_desc} và hỗ trợ Đổi mới 1-1 cho sản phẩm lỗi{cite_suffix}. "
                                "Em đã xác định được một phương án đổi phù hợp này; nếu anh/chị muốn tiếp tục, hệ thống cần ghi nhận yêu cầu để CSKH xem xét hỗ trợ ạ."
                            )
            else:
                action_proposal = None
                state["drop_knowledge_sources"] = True
                final_content = (
                    "Dạ shop rất tiếc về sự cố sản phẩm anh/chị gặp phải. "
                    "Anh/chị vui lòng cung cấp Mã đơn hàng (ví dụ: O-101) để em hỗ trợ kiểm tra thông tin và phương án xử lý phù hợp nhé ạ!"
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
        elif not read_only_lookup and any(w in lower_msg for w in ["hủy đơn", "hủy hàng", "hủy giúp", "muốn hủy", "huy don", "huy hang", "cancel"]):
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
                        ord_obj = res.get("order", {}) if isinstance(res, dict) else {}
                        action_proposal = {
                            "action": "cancel_order",
                            "order_id": extracted_oid,
                            "order_version": ord_obj.get("version", 1),
                            "reason": "ordered_by_mistake",
                            "cancel_reason": "ordered_by_mistake",
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
                        if isinstance(res, dict) and (res.get("error") or not res.get("order")):
                            final_content = (
                                f"Dạ em rất tiếc, hệ thống không tìm thấy đơn hàng {extracted_oid} "
                                f"(hoặc đơn không thuộc tài khoản của anh/chị). "
                                "Anh/chị vui lòng kiểm tra lại chính xác Mã đơn hàng để em hỗ trợ nhé ạ!"
                            )
                        else:
                            status_desc = res.get("order", {}).get("status") if (isinstance(res, dict) and res.get("order")) else "delivered"
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
            if not refusal_set and extracted_oid:
                is_order_ok = True
                try:
                    order_res = execute("get_order", {"order_id": extracted_oid})
                    state["tool_count"] += 1
                    is_order_ok = isinstance(order_res, dict) and not order_res.get("error") and bool(order_res.get("order"))
                    trace.setdefault("tools", []).append({"name": "get_order", "status": "ok" if is_order_ok else "error"})
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
                    refusal_set = True
                    state["drop_knowledge_sources"] = True
                    final_content = (
                        f"Dạ em rất tiếc, hệ thống không tìm thấy đơn hàng {extracted_oid} "
                        f"(hoặc đơn không thuộc tài khoản của anh/chị). "
                        "Anh/chị vui lòng kiểm tra lại chính xác Mã đơn hàng để em có thể tra cứu và hỗ trợ mình ngay nhé ạ!"
                    )

            if not extracted_oid and not knowledge_has_evidence and not refusal_set:
                action_proposal = None
                final_content = (
                    "Dạ shop rất tiếc về sự cố sản phẩm anh/chị gặp phải. "
                    "Anh/chị vui lòng cung cấp Mã đơn hàng (ví dụ: O-101) để em hỗ trợ kiểm tra thông tin và phương án xử lý phù hợp nhé ạ!"
                )
            elif not final_content:
                cand_content = message.get("content") or ""
                lower_cand = cand_content.lower()
                has_unsupported = any(term in lower_cand for term in _UNSUPPORTED_REMEDY_TERMS)
                if has_unsupported:
                    action_proposal = None
                    state["drop_knowledge_sources"] = True
                    if extracted_oid:
                        final_content = (
                            f"Dạ em rất tiếc, hệ thống chưa xác định được thời hạn bảo hành của sản phẩm thuộc đơn hàng {extracted_oid}. "
                            "Anh/chị vui lòng liên hệ nhân viên CSKH để được hỗ trợ kiểm tra bảo hành và xử lý khiếu nại chính xác nhé ạ!"
                        )
                    else:
                        final_content = (
                            "Dạ shop rất tiếc về sự cố sản phẩm anh/chị gặp phải. "
                            "Anh/chị vui lòng cung cấp Mã đơn hàng (ví dụ: O-101) để em hỗ trợ kiểm tra thông tin và phương án xử lý phù hợp nhé ạ!"
                        )
                else:
                    final_content = cand_content or "Dạ shop rất tiếc vì trải nghiệm chưa trọn vẹn này của anh/chị. Anh/chị cho em xin mã đơn hàng và tình trạng gặp phải để em hỗ trợ xử lý ngay nhé ạ!"

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
        if isinstance(exc, TimeoutError):
            raise AgentError('agent_timeout', 'Model đã vượt thời gian xử lý. Chat chưa thay đổi đơn.', trace) from exc
        if isinstance(exc, ConnectionError):
            raise ApiError(503, 'service_unavailable', 'Dịch vụ tạm thời gián đoạn.') from exc
        raise

    if action_proposal:
        state["action_proposal"] = action_proposal

    if state.get("drop_knowledge_sources"):
        if isinstance(state.get("bound"), dict) and isinstance(state["bound"].get("knowledge"), dict):
            state["bound"]["knowledge"]["sources"] = []
        for cell in (getattr(execute, "__closure__", None) or ()):
            try:
                cell_val = cell.cell_contents
            except ValueError:
                continue
            kn = getattr(cell_val, "knowledge", None)
            if kn is not None and isinstance(getattr(kn, "sources", None), list):
                kn.sources.clear()

    msg = {"role": "assistant", "content": final_content}
    state["messages"].append(msg)
    state["fresh"].append(msg)
    state["complete"] = True
    state["subagent_history"].append("dispute_agent:proposal_ready" if state.get("action_proposal") else "dispute_agent:listening")
    return state
