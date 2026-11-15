"""The final answer, checked in code before it reaches the customer (W3.2-D3, W3.2-D11).

The model writes the answer; this module only removes kinds of sentence that the evidence of the turn
does not support, and says so once:

* a promise about the shop's policy on fees, pick-up/delivery or deadlines (an exchange "miễn phí", "tận nhà",
  "trong 7 ngày") that carries no [KB:...] citation from the policy search of this turn;
* a claim that the shop or the system has already cancelled, exchanged, returned or refunded something, or
  has already sent a request, when no tool of this turn shows it. The chat never changes an order: a request
  exists only after the customer picks a reason and presses the separate confirmation button.
* a claim that a conversation or request was transferred to human support without a successful tool result.

The rules read the wording of the answer, never the customer's message, and name no situation: they look for
what a sentence promises and for what the tools of the turn show. Questions, hedges ("chưa có thông tin") and
sentences that quote a structured tool fact (warranty days, a cancelled order) are left alone.
"""
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal

POLICY_NOTE = ('Phần phí, giao nhận và thời hạn em chưa có trích dẫn từ kho chính sách của shop '
               'nên chưa thể xác nhận ạ.')
CLAIM_NOTE = ('Em chưa thực hiện thay đổi nào trên đơn qua chat: yêu cầu hủy, đổi hoặc trả chỉ được gửi '
              'khi anh/chị chọn lý do và bấm nút xác nhận ạ.')
HANDOFF_NOTE = ('Em chưa chuyển được cuộc trò chuyện cho nhân viên; anh/chị nhắn '
                '"gặp nhân viên" để em thử lại ạ.')

_CITATION = re.compile(r'\[KB:[^\]\r\n]*\]', re.IGNORECASE)
_CITATION_ONLY = re.compile(r'^\s*(?:\[KB:[^\]\r\n]*\]\s*)+[.!?…]*\s*$', re.IGNORECASE)
_SPLIT = re.compile(r'(?<=[.!?…])(\s+)')

_ORDER_FEE = r'phí (?:ship|vận chuyển|giao)'
_POLICY_FEE = (
    r'miễn phí|miễn cước|free ?ship|phí (?:đổi|trả|hoàn)|'
    r'không (?:mất|tốn|tính|thu|phải trả) (?:thêm )?(?:phí|cước)|không mất tiền|'
    r'(?:chịu|trả|hỗ trợ) (?:toàn bộ )?(?:phí|cước)')
_FEE = re.compile(_ORDER_FEE + '|' + _POLICY_FEE)
_POLICY_FEE_MATCH = re.compile(_POLICY_FEE)
_LOGISTICS = re.compile(
    r'tận nhà|tận nơi|(?:2|hai) chiều|'
    r'(?:shipper|nhân viên giao hàng|bưu tá|đơn vị vận chuyển)[^.!?\n]{0,40}(?:đến|tới|qua|sang)[^.!?\n]{0,15}(?:lấy|nhận|thu)|'
    r'(?:đến|tới|qua|sang) (?:lấy|thu hồi) (?:lại )?(?:hàng|sản phẩm)|thu hồi (?:lại )?(?:hàng|sản phẩm)|'
    r'gửi (?:lại )?(?:hàng|sản phẩm|size) mới|\b1\s*đổi\s*1\b|\b1\s*[-–]\s*1\b')
_DEADLINE = re.compile(
    r'(?:trong|trong vòng|quá|sau|tối đa|trước|hạn|thời hạn)[^.!?\n]{0,14}\d+\s*(?:ngày|tuần|giờ|tháng|năm)|'
    r'bảo hành[^.!?\n]{0,14}\d+\s*(?:ngày|tuần|tháng|năm)|'
    r'\d+\s*(?:ngày|tuần|tháng|năm)\s*(?:kể từ|tính từ|làm việc|đầu)|thời hạn|hạn (?:đổi|trả|bảo hành)')
_POLICY_CONTEXT = re.compile(
    r'đổi|trả|hoàn|hủy|huỷ|bảo hành|ship|vận chuyển|giao hàng|giao nhận|lấy hàng|thu hồi|gửi hàng|khiếu nại')
_HEDGE = re.compile(
    r'chưa (?:có|rõ|xác nhận|thể|nêu|đề cập|tìm thấy|thấy|biết|dám)|'
    r'không (?:có thông tin|rõ|nêu|đề cập|thể xác nhận|chắc chắn|tìm thấy|thấy|biết|dám)|'
    r'cần xác nhận')

_DONE_VERBS = (r'(?:hủy|huỷ)(?:\s+đơn)?|đổi(?!\s+ý)\s+(?:sang|mới|hàng|size|màu|cho)|trả hàng|hoàn tiền|hoàn trả|'
               r'gửi yêu cầu|tạo yêu cầu|lập yêu cầu|xác nhận (?:hủy|huỷ|đổi|trả)|xử lý xong|'
               r'thay đổi (?:đơn|trạng thái)|cập nhật (?:đơn|trạng thái)')
# Returning a shipment and completing/finishing something are not monetary refunds.
_REFUND_COMPLETION = r'hoàn\b(?!\s+(?:về\s+(?:kho|shop|cửa\s+hàng|người\s+gửi)|tất|thiện|chỉnh)\b)'
_CLAIMS = (
    re.compile(r'(?:em|shop|bên em|hệ thống|mình|cửa hàng|chúng em)\s+(?:đã|vừa)\s+(?:xong\s+)?(?:' + _DONE_VERBS + ')'),
    re.compile(r'(?:đơn|đơn hàng)[^.!?\n]{0,40}\b(?:đã|vừa)\s+(?:được\s+)?'
               r'(?:hủy|huỷ|hoàn tiền|hoàn trả|đổi(?!\s+ý)\s+(?:sang|mới|hàng|size|màu)|trả hàng)'),
    re.compile(r'yêu cầu[^.!?\n]{0,40}\b(?:đã|vừa)\s+(?:được\s+)?(?:gửi|tạo|duyệt|chấp nhận|xử lý xong)'),
    re.compile(r'(?:đã|vừa)\s+(?:được\s+)?(?:hủy|huỷ|hoàn tiền)\s+(?:thành công|xong)|'
               r'(?:hủy|huỷ|đổi|trả hàng|hoàn tiền)\s+thành công'),
    re.compile(r'(?:đã|vừa)\s+được\s+' + _REFUND_COMPLETION),
)
# In a negated clause, "vừa X vừa Y" means concurrent actions, not recent completion.
# Mask only that pair (the "vừa" after the negation and the next one in the clause) for the claim check;
# a later "vừa" joined by "và"/"nên" is still a claim. Other claims and the customer's wording stay intact.
_NEGATED_CONCURRENT = re.compile(
    r'\b(?:không|chưa)(?:\s+(?:thể|được))?\s+vừa\b'
    r'(?:(?:(?!\b(?:nhưng|song)\b)[^,;:.!?\n])*?\bvừa\b)?')
_VUA = re.compile(r'\bvừa\b')
_CANCEL_WORDS = re.compile(r'hủy|huỷ')
_REFUND_WORDS = re.compile(r'hoàn tiền|hoàn trả|(?<=được )' + _REFUND_COMPLETION)
_OTHER_DONE_ACTION = re.compile(r'(?:và|đồng thời|cũng)\s+(?:(?:đã|vừa)\s+)?(?:được\s+)?(?:' + _DONE_VERBS + ')')
_HANDOFF_CLAIM = re.compile(
    r'(?:đã|vừa)\s+(?:được\s+)?(?:[^.!?\n]{0,120}?\s+)?chuyển\b'
    r'[^.!?\n]{0,120}?(?:cho|sang|tới|đến)\s+(?:nhân viên|bộ phận|người thật|cskh)')
# Digits inside opaque order/product IDs are identifiers, not a number of days.
_FACT_ID = re.compile(r'\b[a-z][a-z0-9]*(?:[-_][a-z0-9]+)+\b', re.IGNORECASE)
_LIST_ITEM = re.compile(r'^\s*(?:[-*+]|\d+[.)])\s+')
_MD_HEADING = re.compile(r'^(#{1,6})\s+(.+?)\s*#*$')
_BOLD_HEADING = re.compile(r'^\*\*(.+?)\*\*(.*)$')
_LABEL_SEPARATORS = (' — ', ' – ', ' - ', ': ', ' | ')
_EMPTY_OR_ORDINAL = re.compile(r'^(?:\d+[.)])?$')
_TIME_NUMBER = re.compile(r'\b(\d+)\s*(?:ngày|tuần|tháng|năm|giờ)\b')
_MONEY = re.compile(r'(?<!\w)(\d+(?:[.,]\d+)*)(?:\s*(triệu|nghìn|ngàn|k|vnđ|vnd|đ|₫)(?!\w))?')
_THOUSANDS = re.compile(r'\d{1,3}(?:[.,]\d{3})+')
_MONEY_FIELDS = ('shipping_fee', 'amount', 'refunded_total', 'pending_total', 'unit_price', 'subtotal')
_DAY_FIELDS = ('return_window_days', 'size_exchange_window_days', 'warranty_window_days', 'warranty_days')
_DERIVED_TIME_WINDOWS = ('return_window_days', 'size_exchange_window_days', 'warranty_window_days')
_WINDOW_FIELDS = ('within_return_window', 'within_size_exchange_window', 'within_warranty')
_DELIVERY_FIELDS = ('promised_delivery_by', 'estimated_delivery_at', 'latest_estimated_delivery_at')


@dataclass(frozen=True)
class Evidence:
    cancelled: bool = False                              # a tool of this turn shows a cancelled order
    refunded: bool = False
    money_amounts: frozenset = field(default_factory=frozenset)
    warranty_days: frozenset = field(default_factory=frozenset)
    deadline_days: frozenset = field(default_factory=frozenset)
    has_window: bool = False
    has_delivery_date: bool = False
    escalated_to_human: bool = False
    derived_money: frozenset = field(default_factory=frozenset)
    derived_time: frozenset = field(default_factory=frozenset)


@dataclass(frozen=True)
class AnswerCheck:
    text: str
    dropped_policy: int = 0
    dropped_claims: int = 0
    details: tuple = ()

    @property
    def changed(self) -> bool:
        return bool(self.dropped_policy or self.dropped_claims)


def _items_subtotal(value: dict):
    items = value.get('items')
    if not isinstance(items, list) or not items:
        return None
    total = 0
    for item in items:
        if not isinstance(item, dict) or type(item.get('subtotal')) is not int:
            return None
        total += item['subtotal']
    return total


def _order_record_code(value: dict):
    if type(value.get('amount')) is not int or type(value.get('shipping_fee')) is not int:
        return None
    for key in ('id', 'external_order_id'):
        code = value.get(key)
        if isinstance(code, str) and code:
            return code
    return None


def _is_finite_number(value) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def tool_evidence(messages) -> Evidence:
    """What the tool results of this turn establish, read from their JSON."""
    cancelled, refunded, warranty, deadlines, money = False, False, set(), set(), set()
    derived_money, derived_time, order_records = set(), set(), {}
    has_window, has_delivery_date, escalated = False, False, False

    def walk(value):
        nonlocal cancelled, refunded, has_window, has_delivery_date, escalated
        if isinstance(value, dict):
            if value.get('status') == 'cancelled' and 'id' in value:
                cancelled = True
            if value.get('order_status') == 'cancelled':
                cancelled = True
            refunded |= value.get('payment_status') in ('refunded', 'partially_refunded')
            for key in ('refund_summary', 'refund'):
                refund = value.get(key)
                if isinstance(refund, dict):
                    total = refund.get('refunded_total')
                    refunded |= (refund.get('latest_status') == 'completed' or
                                 (type(total) in (int, float) and total > 0))
            for key in _MONEY_FIELDS:
                if type(value.get(key)) is int:
                    money.add(value[key])
            items_sub = _items_subtotal(value)
            if items_sub is not None:
                derived_money.add(items_sub)
            order_code = _order_record_code(value)
            if order_code is not None and order_code not in order_records:
                order_records[order_code] = (value['amount'], value['shipping_fee'], items_sub)
            escalated |= value.get('status') == 'escalated_to_human'
            has_window |= any(isinstance(value.get(key), bool) for key in _WINDOW_FIELDS)
            has_delivery_date |= any(bool(value.get(key)) for key in _DELIVERY_FIELDS)
            for key in _DAY_FIELDS:
                if type(value.get(key)) is int:
                    deadlines.add(value[key])
            late_hours = value.get('late_by_hours')
            if _is_finite_number(late_hours) and late_hours > 0:
                derived_time.update((
                    math.floor(late_hours),
                    math.ceil(late_hours),
                    math.floor(late_hours / 24),
                    math.ceil(late_hours / 24),
                ))
            since_delivery = value.get('days_since_delivery')
            if _is_finite_number(since_delivery) and since_delivery >= 0:
                derived_time.update((math.floor(since_delivery), math.ceil(since_delivery)))
                for key in _DERIVED_TIME_WINDOWS:
                    window = value.get(key)
                    if type(window) is int and window >= since_delivery:
                        remaining = window - since_delivery
                        derived_time.update((math.floor(remaining), math.ceil(remaining)))
            days = value.get('warranty_days')
            if isinstance(days, int) and not isinstance(days, bool):
                warranty.add(days)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for message in messages or []:
        if isinstance(message, dict) and message.get('role') == 'tool' and isinstance(message.get('content'), str):
            try:
                walk(json.loads(message['content']))
            except ValueError:
                continue
    if len(order_records) >= 2:
        derived_money.add(sum(amount for amount, _, _ in order_records.values()))
        derived_money.add(sum(shipping for _, shipping, _ in order_records.values()))
        if all(sub is not None for _, _, sub in order_records.values()):
            derived_money.add(sum(sub for _, _, sub in order_records.values()))
    return Evidence(cancelled=cancelled, refunded=refunded, money_amounts=frozenset(money),
                    warranty_days=frozenset(warranty), deadline_days=frozenset(deadlines),
                    has_window=has_window, has_delivery_date=has_delivery_date, escalated_to_human=escalated,
                    derived_money=frozenset(derived_money), derived_time=frozenset(derived_time))


def _fragments(text):
    """(sentence, separator) pairs; a citation standing alone belongs to the sentence before it."""
    parts = _SPLIT.split(text)
    pairs = [[parts[i], parts[i + 1] if i + 1 < len(parts) else ''] for i in range(0, len(parts), 2)]
    merged = []
    for sentence, separator in pairs:
        if merged and _CITATION_ONLY.match(sentence):
            merged[-1][0] += merged[-1][1] + sentence
            merged[-1][1] = separator
        else:
            merged.append([sentence, separator])
    return merged


def _money_amounts(plain):
    """Money only: ignore identifiers and bare small product/size/quantity numbers."""
    amounts = set()
    for match in _MONEY.finditer(_FACT_ID.sub(' ', plain)):
        number, unit = match.groups()
        grouped = bool(_THOUSANDS.fullmatch(number))
        if grouped:
            number = number.replace('.', '').replace(',', '')
        elif number.count('.') + number.count(',') > 1:
            # An unrecognised monetary number must not silently disappear from the check.
            amounts.add(None)
            continue
        value = Decimal(number.replace(',', '.'))
        if unit or grouped or value >= 1000:
            scale = 1000000 if unit == 'triệu' else 1000 if unit in ('k', 'nghìn', 'ngàn') else 1
            amounts.add(value * scale)
    return amounts


def _policy_rule(sentence, evidence):
    plain = _CITATION.sub(' ', sentence).lower()
    if _CITATION.search(sentence) or sentence.rstrip().endswith('?') or _HEDGE.search(plain):
        return None
    if not _POLICY_CONTEXT.search(plain):
        return None
    if _LOGISTICS.search(plain):
        return 'logistics'
    if _FEE.search(plain):
        numbers = _money_amounts(plain)
        if _POLICY_FEE_MATCH.search(plain):
            return 'policy_fee'
        if not numbers or not numbers <= (evidence.money_amounts | evidence.derived_money):
            return 'fee_amount'
    if _DEADLINE.search(plain):
        numbers = {int(n) for n in _TIME_NUMBER.findall(_FACT_ID.sub(' ', plain))}
        if numbers:
            return None if numbers <= (evidence.deadline_days | evidence.derived_time) else 'deadline_number'
        return None if (evidence.has_window or evidence.has_delivery_date) else 'deadline_no_fact'
    return None


def _uncited_policy_promise(sentence, evidence) -> bool:
    return _policy_rule(sentence, evidence) is not None


def _unfounded_claim(sentence, evidence) -> bool:
    plain = _CITATION.sub(' ', sentence).lower()
    plain = _NEGATED_CONCURRENT.sub(lambda match: _VUA.sub('   ', match.group()), plain)
    if sentence.rstrip().endswith('?') or not any(pattern.search(plain) for pattern in _CLAIMS):
        return False
    if evidence.refunded and _REFUND_WORDS.search(plain):
        remaining = _REFUND_WORDS.sub('ghi nhận', plain)
        if evidence.cancelled:
            remaining = _CANCEL_WORDS.sub(' ', remaining)
        # A refund fact does not also establish an exchange, return or request submission.
        return bool(_OTHER_DONE_ACTION.search(remaining) or any(pattern.search(remaining) for pattern in _CLAIMS))
    if evidence.cancelled and _CANCEL_WORDS.search(plain):
        return False  # an order record of this turn says it is cancelled: that is a fact, not a promise
    return True


def _unfounded_handoff(sentence, evidence) -> bool:
    plain = _CITATION.sub(' ', sentence).lower()
    return bool(not evidence.escalated_to_human and not sentence.rstrip().endswith('?')
                and _HANDOFF_CLAIM.search(plain))


def _extract_heading_label(raw: str) -> str:
    cuts = [raw.find(sep) for sep in _LABEL_SEPARATORS if sep in raw]
    head = raw[:min(cuts)] if cuts else raw
    return head.strip(' :–—-')


def _heading_replacement(line: str):
    if _LIST_ITEM.match(line):
        return None
    stripped = line.strip()
    md = _MD_HEADING.match(stripped)
    if md:
        label = _extract_heading_label(md.group(2))
        return f'{md.group(1)} {label}' if label else None
    bold = _BOLD_HEADING.match(stripped)
    if bold:
        bold_text, rest = bold.group(1), bold.group(2)
        if rest.strip() in ('', ':') or _FACT_ID.search(bold_text):
            label = _extract_heading_label(bold_text)
            return f'**{label}**' if label else None
    return None


def _sentence_drop_info(sentence, evidence):
    if _unfounded_handoff(sentence, evidence):
        return ('handoff', 'handoff_claim')
    policy_rule = _policy_rule(sentence, evidence)
    if policy_rule:
        return ('policy', policy_rule)
    if _unfounded_claim(sentence, evidence):
        return ('claim', 'done_claim')
    return None


def _any_sentence_dropped(text: str, evidence) -> bool:
    return any(_sentence_drop_info(sentence, evidence) is not None for sentence, _ in _fragments(text))


def check_final_answer(text, messages=None) -> AnswerCheck:
    """`text` without the sentences the evidence of the turn does not support, plus one note per kind removed."""
    if not isinstance(text, str) or not text.strip():
        return AnswerCheck(text or '')
    evidence = tool_evidence(messages)
    kept_lines, dropped_policy, dropped_claims, dropped_handoffs, orphan_refs, details = [], 0, 0, 0, [], []
    for line_no, line in enumerate(unicodedata.normalize('NFC', text).split('\n'), start=1):
        kept, line_details = [], []
        for sentence, separator in _fragments(line):
            drop = _sentence_drop_info(sentence, evidence)
            if not drop:
                kept.append(sentence + separator)
                continue
            kind, rule = drop
            line_details.append({'line': line_no, 'kind': kind, 'rule': rule, 'heading_label_kept': False})
            if kind == 'policy':
                dropped_policy += 1
            else:
                dropped_claims += 1
                if kind == 'handoff':
                    dropped_handoffs += 1
                orphan_refs.extend(_CITATION.findall(sentence))
        line_text = ''.join(kept).strip() if kept else ''
        if line_details:
            replacement = _heading_replacement(line)
            if replacement and not _any_sentence_dropped(replacement, evidence):
                line_text = replacement
                for entry in line_details:
                    entry['heading_label_kept'] = True
            elif _EMPTY_OR_ORDINAL.match(re.sub(r'[*#_\s]+', '', line_text)):
                line_text = ''
            details.extend(line_details)
        kept_lines.append(line_text)
    if not (dropped_policy or dropped_claims):
        return AnswerCheck(text)
    body = '\n'.join(kept_lines)
    body = re.sub(r'\n{3,}', '\n\n', body).strip()
    notes = [note for note, count in ((POLICY_NOTE, dropped_policy), (CLAIM_NOTE, dropped_claims - dropped_handoffs),
                                    (HANDOFF_NOTE, dropped_handoffs)) if count]
    if orphan_refs:
        notes[-1] += ' ' + ' '.join(dict.fromkeys(orphan_refs))  # a removed sentence must not strand its citation
    return AnswerCheck('\n\n'.join(part for part in (body, *notes) if part), dropped_policy, dropped_claims, tuple(details))
