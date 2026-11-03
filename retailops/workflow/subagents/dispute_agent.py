"""Cancel, return, exchange and complaint worker of the legacy graph (RETAILOPS_AGENT_MODE=legacy).

W3.2-D3/D7: the model decides what to say and which tool to call, and the server tools check eligibility,
ownership and variants. This worker holds no scripted answer, no keyword branch and no proposal of its own:
a request form is opened only by prepare_order_action, and only the customer's own confirmation sends it.
"""
from retailops.workflow.subagents.order_agent import _synthesize_order_response
from retailops.workflow.subagents.read_worker import run_read_worker

DISPUTE_SYSTEM_PROMPT = (
    'You help a customer of RetailOps Shop with a cancellation, return, exchange, defect or complaint, using '
    'server-bound tools. Answer naturally in Vietnamese, with empathy and without scripts. '
    'Every order request has one model: a type (cancel, return or exchange), an order, a reason and, for an exchange, '
    'the target variant. An exchange swaps to another variant of the same product (color, size, style) or replaces the '
    'same variant when the item is defective. '
    'Read the order with get_order or get_context; never invent an order ID. Call prepare_order_action to check '
    'eligibility on the server: it lists the valid reasons and, for an exchange, the product variants with their stock, '
    'and it opens the request form on the customer screen when the order is eligible. Put the customer words about '
    'the wanted variant in target_variant. Stock only informs the customer and staff; it never decides eligibility. '
    'If the tool says the order is not eligible, tell the customer so and why. '
    'Use get_product or check_inventory for variants and stock, and search_knowledge for store policy. State a fee, '
    'who pays, pickup or delivery, or a deadline only when a retrieved passage supports it, and copy its [KB:...] '
    'citation next to the claim; otherwise say the knowledge base does not provide it. '
    'Use request_human_support when the customer asks for a person or the complaint cannot be settled with the tools. '
    'No tool changes an order. Never say that something was cancelled, returned, exchanged or refunded: the customer '
    'must choose a reason and press the separate confirmation button. Do not guess the reason.'
)
ALLOWED = frozenset((
    'get_order', 'list_orders', 'get_context', 'get_product', 'search_products', 'check_inventory',
    'track_shipment', 'search_knowledge', 'prepare_order_action', 'prepare_cancellation', 'request_human_support',
))
_HARD_DENIALS = ('order_not_found', 'permission_denied', 'forbidden')
# A knowledge base that is not ready is not a refusal: the model reads the tool's note and hands the case over.
_KNOWLEDGE_ERRORS = frozenset(('knowledge_unavailable', 'knowledge_not_ready', 'knowledge_budget_exceeded',
                               'invalid_knowledge_query'))


def _render(records):
    """Evidence-only reply when a tool refused: ownership denials use the order renderer, others quote the tool."""
    refused = [r for r in records if r['result'].get('error') in _HARD_DENIALS]
    if refused:
        return _synthesize_order_response(refused)  # the refusal alone: nothing else retrieved can soften it
    lines = [r['result'].get('status_text') or r['result'].get('message') for r in records if r['result'].get('error')]
    lines = [line.strip() for line in lines if isinstance(line, str) and line.strip()]
    return ' '.join(dict.fromkeys(lines)) or None


def run_dispute_agent(state, execute, gateway, timeout=60):
    return run_read_worker(state, execute, gateway, prompt=DISPUTE_SYSTEM_PROMPT, allowed_tools=ALLOWED,
                           render=_render, worker='dispute_agent', timeout=timeout, tolerated=_KNOWLEDGE_ERRORS)
