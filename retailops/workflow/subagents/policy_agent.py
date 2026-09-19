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
    for tr in tool_results:
        result = tr.get('result')
        if not isinstance(result, dict) or result.get('error'):
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
        return 'C\u00e1c tr\u00edch \u0111o\u1ea1n tra c\u1ee9u \u0111\u01b0\u1ee3c (ch\u01b0a c\u00f3 ph\u1ea7n di\u1ec5n gi\u1ea3i t\u1ef1 \u0111\u1ed9ng):\n\n' + '\n\n'.join(parts)
    if tool_results:
        return 'Ch\u01b0a t\u00ecm th\u1ea5y b\u1eb1ng ch\u1ee9ng ph\u00f9 h\u1ee3p trong kho ch\u00ednh s\u00e1ch. Ch\u01b0a th\u1ec3 x\u00e1c nh\u1eadn quy \u0111\u1ecbnh cho tr\u01b0\u1eddng h\u1ee3p n\u00e0y.'
    return None


def run_policy_agent(state, execute, gateway, timeout=30):
    return run_read_worker(state, execute, gateway, prompt=POLICY_SYSTEM_PROMPT,
                           allowed_tools=frozenset(('search_knowledge',)),
                           render=_synthesize_policy_response, worker='policy_agent', timeout=timeout)
