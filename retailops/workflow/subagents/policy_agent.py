"""Policy & Knowledge Subagent.
Handles RAG search for store rules, warranties, return/exchange terms, and FAQ.
"""
import copy
import json
from typing import Any

from retailops.workflow.state import MultiAgentState

POLICY_SYSTEM_PROMPT = (
    "Bạn là Chuyên viên Giải đáp Chính sách & Quy định của shop.\n"
    "Nhiệm vụ của bạn là giải đáp chính sách đổi trả, bảo hành, thanh toán và khuyến mãi.\n"
    "Quy tắc bắt buộc:\n"
    "- Sử dụng công cụ `search_knowledge` để tìm kiếm thông tin quy định chính thức.\n"
    "- Mọi khẳng định về chính sách phải kèm theo mã trích dẫn nguồn `[KB:<id>]` nếu được cung cấp.\n"
    "- Tuyệt đối không tự ý cam kết vượt ngoài chính sách quy định của shop."
)


def run_policy_agent(state: MultiAgentState, execute: Any, gateway: Any, timeout: int = 30) -> MultiAgentState:
    """Execute knowledge retrieval and policy subagent."""
    state = copy.deepcopy(state)
    state["consecutive_ood_count"] = 0  # Reset OOD counter
    trace = state.setdefault("trace", {})

    last_user_msg = next((m["content"] for m in reversed(state["messages"]) if m["role"] == "user"), "")
    prompt_messages = [
        {"role": "system", "content": POLICY_SYSTEM_PROMPT},
        {"role": "user", "content": last_user_msg}
    ]

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
                if name in ("search_knowledge", "get_runtime_info"):
                    result = execute(name, args)
                    state["tool_count"] += 1
                    trace.setdefault("tools", []).append({"name": name, "status": "error" if isinstance(result, dict) and result.get("error") else "ok"})
                    tool_content = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
                    tool_entry = {"role": "tool", "tool_name": name, "content": tool_content}
                    prompt_messages.append(message)
                    prompt_messages.append(tool_entry)

            final_res = gateway.chat(prompt_messages, False, timeout)
            trace["model_calls"] = trace.get("model_calls", 0) + 1
            trace["prompt_tokens"] = trace.get("prompt_tokens", 0) + (final_res.get("prompt_eval_count") or 0)
            trace["generated_tokens"] = trace.get("generated_tokens", 0) + (final_res.get("eval_count") or 0)
            final_content = final_res.get("message", {}).get("content", "Dạ theo quy định của shop thì chính sách được áp dụng đầy đủ ạ.")
        else:
            final_content = message.get("content", "Dạ anh/chị cần em hỗ trợ giải đáp về chính sách đổi trả, bảo hành hay ưu đãi nào ạ?")

    except Exception:
        final_content = "Dạ hệ thống tra cứu chính sách đang được cập nhật, anh/chị vui lòng để lại câu hỏi cụ thể để shop giải đáp nhé ạ!"

    msg = {"role": "assistant", "content": final_content}
    state["messages"].append(msg)
    state["fresh"].append(msg)
    state["complete"] = True
    state["subagent_history"].append("policy_agent:done")
    return state
