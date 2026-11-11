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
import re
import unicodedata
from dataclasses import dataclass, field

POLICY_NOTE = ('Phần phí, giao nhận và thời hạn em chưa có trích dẫn từ kho chính sách của shop '
               'nên chưa thể xác nhận ạ.')
CLAIM_NOTE = ('Em chưa thực hiện thay đổi nào trên đơn qua chat: yêu cầu hủy, đổi hoặc trả chỉ được gửi '
              'khi anh/chị chọn lý do và bấm nút xác nhận ạ.')
HANDOFF_NOTE = ('Em chưa chuyển được cuộc trò chuyện cho nhân viên; anh/chị nhắn '
                '"gặp nhân viên" để em thử lại ạ.')

_CITATION = re.compile(r'\[KB:[^\]\r\n]*\]', re.IGNORECASE)
_CITATION_ONLY = re.compile(r'^\s*(?:\[KB:[^\]\r\n]*\]\s*)+[.!?…]*\s*$', re.IGNORECASE)
_SPLIT = re.compile(r'(?<=[.!?…])(\s+)')

_FEE = re.compile(
    r'miễn phí|miễn cước|free ?ship|phí (?:ship|vận chuyển|giao|đổi|trả|hoàn)|'
    r'không (?:mất|tốn|tính|thu|phải trả) (?:thêm )?(?:phí|cước)|không mất tiền|'
    r'(?:chịu|trả|hỗ trợ) (?:toàn bộ )?(?:phí|cước)')
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
_CLAIMS = (
    re.compile(r'(?:em|shop|bên em|hệ thống|mình|cửa hàng|chúng em)\s+(?:đã|vừa)\s+(?:xong\s+)?(?:' + _DONE_VERBS + ')'),
    re.compile(r'(?:đơn|đơn hàng)[^.!?\n]{0,40}\b(?:đã|vừa)\s+(?:được\s+)?'
               r'(?:hủy|huỷ|hoàn tiền|hoàn trả|đổi(?!\s+ý)\s+(?:sang|mới|hàng|size|màu)|trả hàng)'),
    re.compile(r'yêu cầu[^.!?\n]{0,40}\b(?:đã|vừa)\s+(?:được\s+)?(?:gửi|tạo|duyệt|chấp nhận|xử lý xong)'),
    re.compile(r'(?:đã|vừa)\s+(?:được\s+)?(?:hủy|huỷ|hoàn tiền)\s+(?:thành công|xong)|'
               r'(?:hủy|huỷ|đổi|trả hàng|hoàn tiền)\s+thành công'),
)
_CANCEL_WORDS = re.compile(r'hủy|huỷ')
_HANDOFF_CLAIM = re.compile(
    r'(?:đã|vừa)\s+(?:được\s+)?(?:[^.!?\n]{0,120}?\s+)?chuyển\b'
    r'[^.!?\n]{0,120}?(?:cho|sang|tới|đến)\s+(?:nhân viên|bộ phận|người thật|cskh)')
# Digits inside opaque order/product IDs are identifiers, not a number of days.
_FACT_ID = re.compile(r'\b[a-z][a-z0-9]*(?:[-_][a-z0-9]+)+\b', re.IGNORECASE)
_DAY_FIELDS = ('return_window_days', 'size_exchange_window_days', 'warranty_window_days', 'warranty_days')
_WINDOW_FIELDS = ('within_return_window', 'within_size_exchange_window', 'within_warranty')
_DELIVERY_FIELDS = ('promised_delivery_by', 'estimated_delivery_at', 'latest_estimated_delivery_at')


@dataclass(frozen=True)
class Evidence:
    cancelled: bool = False                              # a tool of this turn shows a cancelled order
    warranty_days: frozenset = field(default_factory=frozenset)
    deadline_days: frozenset = field(default_factory=frozenset)
    has_window: bool = False
    has_delivery_date: bool = False
    escalated_to_human: bool = False


@dataclass(frozen=True)
class AnswerCheck:
    text: str
    dropped_policy: int = 0
    dropped_claims: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.dropped_policy or self.dropped_claims)


def tool_evidence(messages) -> Evidence:
    """What the tool results of this turn establish, read from their JSON."""
    cancelled, warranty, deadlines = False, set(), set()
    has_window, has_delivery_date, escalated = False, False, False

    def walk(value):
        nonlocal cancelled, has_window, has_delivery_date, escalated
        if isinstance(value, dict):
            if value.get('status') == 'cancelled' and 'id' in value:
                cancelled = True
            if value.get('order_status') == 'cancelled':
                cancelled = True
            escalated |= value.get('status') == 'escalated_to_human'
            has_window |= any(isinstance(value.get(key), bool) for key in _WINDOW_FIELDS)
            has_delivery_date |= any(bool(value.get(key)) for key in _DELIVERY_FIELDS)
            for key in _DAY_FIELDS:
                if type(value.get(key)) is int:
                    deadlines.add(value[key])
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
    return Evidence(cancelled=cancelled, warranty_days=frozenset(warranty), deadline_days=frozenset(deadlines),
                    has_window=has_window, has_delivery_date=has_delivery_date, escalated_to_human=escalated)


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


def _uncited_policy_promise(sentence, evidence) -> bool:
    plain = _CITATION.sub(' ', sentence).lower()
    if _CITATION.search(sentence) or sentence.rstrip().endswith('?') or _HEDGE.search(plain):
        return False
    if not _POLICY_CONTEXT.search(plain):
        return False
    if _FEE.search(plain) or _LOGISTICS.search(plain):
        return True
    if _DEADLINE.search(plain):
        numbers = {int(n) for n in re.findall(r'\d+', _FACT_ID.sub(' ', plain))}
        if numbers:
            return not numbers <= evidence.deadline_days
        return not (evidence.has_window or evidence.has_delivery_date)
    return False


def _unfounded_claim(sentence, evidence) -> bool:
    plain = _CITATION.sub(' ', sentence).lower()
    if sentence.rstrip().endswith('?') or not any(pattern.search(plain) for pattern in _CLAIMS):
        return False
    if evidence.cancelled and _CANCEL_WORDS.search(plain):
        return False  # an order record of this turn says it is cancelled: that is a fact, not a promise
    return True


def _unfounded_handoff(sentence, evidence) -> bool:
    plain = _CITATION.sub(' ', sentence).lower()
    return bool(not evidence.escalated_to_human and not sentence.rstrip().endswith('?')
                and _HANDOFF_CLAIM.search(plain))


def check_final_answer(text, messages=None) -> AnswerCheck:
    """`text` without the sentences the evidence of the turn does not support, plus one note per kind removed."""
    if not isinstance(text, str) or not text.strip():
        return AnswerCheck(text or '')
    evidence = tool_evidence(messages)
    kept_lines, dropped_policy, dropped_claims, dropped_handoffs, orphan_refs = [], 0, 0, 0, []
    for line in unicodedata.normalize('NFC', text).split('\n'):
        kept = []
        for sentence, separator in _fragments(line):
            if _unfounded_handoff(sentence, evidence):
                dropped_claims += 1
                dropped_handoffs += 1
                orphan_refs.extend(_CITATION.findall(sentence))
            elif _uncited_policy_promise(sentence, evidence):
                dropped_policy += 1
            elif _unfounded_claim(sentence, evidence):
                dropped_claims += 1
                orphan_refs.extend(_CITATION.findall(sentence))
            else:
                kept.append(sentence + separator)
        kept_lines.append(''.join(kept).strip() if kept else '')
    if not (dropped_policy or dropped_claims):
        return AnswerCheck(text)
    body = '\n'.join(kept_lines)
    body = re.sub(r'\n{3,}', '\n\n', body).strip()
    notes = [note for note, count in ((POLICY_NOTE, dropped_policy), (CLAIM_NOTE, dropped_claims - dropped_handoffs),
                                    (HANDOFF_NOTE, dropped_handoffs)) if count]
    if orphan_refs:
        notes[-1] += ' ' + ' '.join(dict.fromkeys(orphan_refs))  # a removed sentence must not strand its citation
    return AnswerCheck('\n\n'.join(part for part in (body, *notes) if part), dropped_policy, dropped_claims)
