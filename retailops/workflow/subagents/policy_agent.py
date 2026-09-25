"""Policy worker; fallback quotes actual excerpts with exact provenance IDs."""
from retailops.knowledge.citations import CITATION_ID
from retailops.workflow.subagents.read_worker import run_read_worker

POLICY_SYSTEM_PROMPT = (
    'You answer Vietnamese store-policy questions using search_knowledge. '
    'Only report facts supported by returned excerpts and cite exact [KB:...] IDs. '
    'An empty search is not permission to invent policy. '
    'Order-specific eligibility must be verified separately; never promise a transaction.'
)


def _synthesize_policy_response(tool_results):
    parts, seen = [], set()
    has_disallowed_tool = False
    for tr in tool_results:
        result = tr.get('result')
        if not isinstance(result, dict):
            return None
        code = result.get('error')
        if code in ('tool_not_allowed', 'invalid_tool_arguments'):
            has_disallowed_tool = True
            continue
        if code:
            return None
        sources = result.get('results')
        if not isinstance(sources, list):
            return None
        for source in sources:
            if not isinstance(source, dict):
                return None
            cid, excerpt = source.get('citation_id'), source.get('excerpt')
            if not isinstance(cid, str) or not CITATION_ID.fullmatch(cid) or not isinstance(excerpt, str) or not excerpt.strip():
                return None
            if cid not in seen:
                # The stored ID already includes KB:. Do not prefix it twice.
                parts.append(excerpt.strip() + f' [{cid}]')
                seen.add(cid)
    if parts:
        msg = 'Các trích đoạn tra cứu được (chưa có phần diễn giải tự động):\n\n' + '\n\n'.join(parts)
        if has_disallowed_tool:
            msg += '\n\n(Lưu ý: Một công cụ ngoài phạm vi tra cứu chính sách đã không được thực thi).'
        return msg
    if has_disallowed_tool:
        return 'Yêu cầu tra cứu nằm ngoài phạm vi của chuyên viên chính sách (chỉ hỗ trợ tra cứu quy định cửa hàng). Vui lòng kiểm tra lại câu hỏi hoặc chọn đơn hàng phù hợp.'
    if tool_results:
        return 'Chưa tìm thấy bằng chứng phù hợp trong kho chính sách. Chưa thể xác nhận quy định cho trường hợp này.'
    return None


def run_policy_agent(state, execute, gateway, timeout=30):
    return run_read_worker(state, execute, gateway, prompt=POLICY_SYSTEM_PROMPT,
                           allowed_tools=frozenset(('search_knowledge',)),
                           render=_synthesize_policy_response, worker='policy_agent', timeout=timeout)
