"""Order worker with ownership-safe results and evidence-only degraded replies."""
import math
import re

from retailops.workflow.subagents.read_worker import run_read_worker

ORDER_SYSTEM_PROMPT = (
    'You support a Vietnamese retail customer using server-bound read-only tools. '
    'Use list_orders for all orders, get_order/get_context for current order facts, '
    'and track_shipment for carrier information. Never invent identifiers or facts. '
    'An order_not_found result means no matching order is visible to this account; '
    'do not claim the order is absent globally or owned by somebody else. '
    'Missing carrier information is unknown, not a delivery ETA. '
    'These tools do not file complaints, issue vouchers, cancel orders or promise redelivery. '
    'Do not claim any of those actions have occurred. For a status-only question get_order is enough. '
    'Track shipment only for a delivery question; missing tracking remains unknown. '
    'Use catalog tools only for requested product details. Catalog matches are not proof of an order link. '
    'Do not search store policy to fill missing order fields or call tools outside the supplied schema. '
    'Once the requested facts are available, answer; do not keep making speculative calls. '
    'Answer naturally in Vietnamese.'
)
_ALLOWED = frozenset(('get_order', 'list_orders', 'get_context', 'track_shipment',
                      'get_product', 'search_products'))
_STATUS_MAP = {'pending': 'Ch\u1edd x\u1eed l\u00fd', 'delivered': '\u0110\u00e3 giao',
               'cancelled': '\u0110\u00e3 h\u1ee7y', 'processing': '\u0110ang chu\u1ea9n b\u1ecb h\u00e0ng',
               'shipping': '\u0110ang v\u1eadn chuy\u1ec3n'}


def _text(value, limit=180):
    return value.strip()[:limit] if isinstance(value, str) else ''


def _order(order):
    if not isinstance(order, dict) or not _text(order.get('id')):
        return None
    status = _STATUS_MAP.get(order.get('status'), 'Ch\u01b0a r\u00f5 tr\u1ea1ng th\u00e1i')
    lines = [f"{_text(order['id'])}: {status}"]
    for key in ('name', 'variant'):
        if _text(order.get(key)):
            lines.append(_text(order[key]))
    amount = order.get('amount')
    if type(amount) in (int, float) and math.isfinite(amount) and amount >= 0:
        lines.append("Gi\u00e1 tr\u1ecb: " + f"{amount:,.0f}".replace(",", ".") + " VND")
    return '\n'.join(lines)


def _product(product):
    if not isinstance(product, dict) or not _text(product.get('id')) or not _text(product.get('name')):
        return None
    lines = [f"{_text(product['id'])}: {_text(product['name'])}"]
    for key, label in (('description', 'M\u00f4 t\u1ea3'), ('material', 'Ch\u1ea5t li\u1ec7u'),
                       ('care', 'B\u1ea3o qu\u1ea3n')):
        if _text(product.get(key)):
            lines.append(label + ': ' + _text(product[key], 300))
    return '\n'.join(lines)


def _synthesize_order_response(tool_results):
    """Only show returned facts; supplemental misses cannot erase verified orders."""
    parts, supplemental = [], []
    for tr in tool_results:
        result = tr.get('result')
        if not isinstance(result, dict):
            return None
        code = result.get('error')
        name = tr.get('name')
        if code:
            raw_id = tr.get('args', {}).get('order_id', '')
            oid = raw_id if isinstance(raw_id, str) and re.fullmatch(r'[A-Z]{1,6}-[0-9]{1,8}', raw_id) else ''
            if code == 'order_not_found':
                parts.append(f'Kh\u00f4ng t\u00ecm th\u1ea5y \u0111\u01a1n h\u00e0ng {oid} trong c\u00e1c \u0111\u01a1n thu\u1ed9c t\u00e0i kho\u1ea3n c\u1ee7a anh/ch\u1ecb. '
                             'Vui l\u00f2ng ki\u1ec3m tra m\u00e3 ho\u1eb7c ch\u1ecdn m\u1ed9t \u0111\u01a1n trong danh s\u00e1ch b\u00ean ph\u1ea3i.')
            elif code in ('permission_denied', 'forbidden'):
                parts.append('T\u00e0i kho\u1ea3n hi\u1ec7n t\u1ea1i kh\u00f4ng c\u00f3 quy\u1ec1n th\u1ef1c hi\u1ec7n tra c\u1ee9u n\u00e0y.')
            elif code == 'product_not_found':
                supplemental.append('Danh m\u1ee5c ch\u01b0a c\u00f3 s\u1ea3n ph\u1ea9m kh\u1edbp m\u00e3 tra c\u1ee9u.')
            elif code in ('tool_not_allowed', 'invalid_tool_arguments'):
                supplemental.append('M\u1ed9t ph\u1ea7n tra c\u1ee9u b\u1ed5 sung kh\u00f4ng th\u1ef1c hi\u1ec7n \u0111\u01b0\u1ee3c; ch\u1ec9 th\u00f4ng tin \u0111\u00e3 x\u00e1c minh \u0111\u01b0\u1ee3c hi\u1ec3n th\u1ecb.')
            else:
                return None
        elif isinstance(result.get('shipment'), dict) and result['shipment']:
            shipment = result['shipment']
            lines = [f"Th\u00f4ng tin v\u1eadn chuy\u1ec3n \u0111\u01a1n {_text(result.get('order_id'))}:"]
            for key, label in (('carrier', 'H\u00e3ng'), ('status_text', 'Tr\u1ea1ng th\u00e1i'),
                               ('current_location', 'V\u1ecb tr\u00ed'), ('estimated_delivery', 'D\u1ef1 ki\u1ebfn giao')):
                if _text(shipment.get(key)):
                    lines.append(f'{label}: {_text(shipment[key])}')
            if result.get('order_status') in _STATUS_MAP:
                lines.append('Tr\u1ea1ng th\u00e1i \u0111\u01a1n: ' + _STATUS_MAP[result['order_status']])
            if len(lines) == 1:
                return None
            parts.append('\n'.join(lines))
        elif isinstance(result.get('orders'), list):
            rendered = [_order(order) for order in result['orders']]
            if any(item is None for item in rendered):
                return None
            parts.append('\n\n'.join(rendered) if rendered else 'T\u00e0i kho\u1ea3n hi\u1ec7n ch\u01b0a c\u00f3 \u0111\u01a1n h\u00e0ng.')
            if result.get('truncated'):
                parts.append('Danh s\u00e1ch \u0111\u00e3 r\u00fat g\u1ecdn; c\u00f2n c\u00e1c \u0111\u01a1n kh\u00e1c ch\u01b0a hi\u1ec3n th\u1ecb.')
        elif isinstance(result.get('products'), list):
            rendered = [_product(product) for product in result['products']]
            if any(item is None for item in rendered):
                return None
            if rendered:
                parts.append('S\u1ea3n ph\u1ea9m kh\u1edbp trong danh m\u1ee5c (ch\u01b0a x\u00e1c nh\u1eadn li\u00ean k\u1ebft v\u1edbi \u0111\u01a1n):\n' + '\n\n'.join(rendered))
            else:
                parts.append('Ch\u01b0a t\u00ecm th\u1ea5y s\u1ea3n ph\u1ea9m kh\u1edbp trong danh m\u1ee5c. Th\u00f4ng tin b\u1ed5 sung ch\u01b0a c\u00f3.')
        elif 'order' in result or 'product' in result:
            rendered = []
            if result.get('order') is not None:
                item = _order(result['order'])
                if item is None:
                    return None
                rendered.append(item)
            if result.get('product') is not None:
                item = _product(result['product'])
                if item is None:
                    return None
                rendered.append('Th\u00f4ng tin danh m\u1ee5c:\n' + item)
            if rendered:
                parts.extend(rendered)
            elif name == 'get_context':
                parts.append('Ch\u01b0a c\u00f3 \u0111\u01a1n ho\u1eb7c s\u1ea3n ph\u1ea9m \u0111\u01b0\u1ee3c ch\u1ecdn. Vui l\u00f2ng ch\u1ecdn \u0111\u01a1n ho\u1eb7c cung c\u1ea5p m\u00e3.')
            else:
                return None
        else:
            return None
    if parts:
        return '\n\n'.join(dict.fromkeys(parts + supplemental))
    if supplemental:
        return '\n\n'.join(dict.fromkeys(supplemental))
    return None


def run_order_agent(state, execute, gateway, timeout=30):
    return run_read_worker(state, execute, gateway, prompt=ORDER_SYSTEM_PROMPT,
                           allowed_tools=_ALLOWED, render=_synthesize_order_response,
                           worker='order_agent', timeout=timeout)
