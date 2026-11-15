"""Keep what the customer agent sends to the model small enough for the serving window (W3.2-D10).

One prompt is the system text, the settled history, the customer's message and every tool result of the
turn, so each part has its own character budget (the whole must stay under MAX_CHARACTERS of
agent_protocol, which the Colab proxy enforces too). The window was 8,192 tokens; the owner raised it to
16,384 on 2026-11-03 and the budgets below follow. Cutting is generic: long strings are shortened and
long lists lose their tail, with a marker, whatever the tool or the topic was. A tool result always stays
valid JSON that says it was cut, so the model never reads half a sentence as a fact.
"""
import json

from agent_protocol import context_tokens


def _budget(base, floor):
    return max(floor, base * context_tokens() // 16384)

TOOL_RESULT_MAX_CHARS = _budget(5200, 800)   # one tool result
TOOL_CONTENT_BUDGET = _budget(12000, 1600)   # every tool result of one turn together
MIN_RESULT_CHARS = _budget(800, 200)         # a late result's floor
HISTORY_CHAR_BUDGET = _budget(6000, 1000)     # earlier turns together
HISTORY_MESSAGE_CHARS = _budget(1500, 300)   # one earlier message
_STRING_CAPS = (240, 160, 120, 80)
_LIST_CAPS = (10, 6, 4, 2)
LOW_VALUE_KEYS = ('description', 'image_url', 'images', 'note', 'notes', 'raw', 'metadata', 'as_of', 'source')


def dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _shrink_strings(value, string_cap):
    if isinstance(value, str):
        return value[:string_cap] + '…' if len(value) > string_cap else value
    if isinstance(value, list):
        return [_shrink_strings(v, string_cap) for v in value]
    if isinstance(value, dict):
        return {k: _shrink_strings(v, string_cap) for k, v in value.items()}
    return value


def _strip_low_value_keys(value, depth=1):
    if isinstance(value, list):
        return [_strip_low_value_keys(v, depth + 1) for v in value]
    if isinstance(value, dict):
        # Preserve top-level keys (such as list_orders pagination `note`); only strip at depth >= 2.
        return {
            k: _strip_low_value_keys(v, depth + 1)
            for k, v in value.items()
            if depth < 2 or k not in LOW_VALUE_KEYS
        }
    return value


def _cap_lists(value, list_cap):
    if isinstance(value, list):
        kept = [_cap_lists(v, list_cap) for v in value[:list_cap]]
        if len(value) > list_cap:
            kept.append(
                f'…(còn {len(value) - list_cap} mục bị ẩn do giới hạn hiển thị; hỏi hẹp hơn hoặc dùng tool xem chi tiết)'
            )
        return kept
    if isinstance(value, dict):
        return {k: _cap_lists(v, list_cap) for k, v in value.items()}
    return value


def compact_tool_result(result, limit=None) -> str:
    """The JSON text of `result`, at most about `limit` characters, flagged when anything was cut."""
    limit = _budget(5200, 800) if limit is None else limit
    text = dump(result)
    if len(text) <= limit:
        return text
    # Phase A: shrink long strings while keeping all keys and list elements intact.
    shrunk = result
    for string_cap in _STRING_CAPS:
        shrunk = _shrink_strings(result, string_cap)
        if isinstance(shrunk, dict):
            shrunk['_truncated'] = True
        text = dump(shrunk)
        if len(text) <= limit:
            return text
    # Phase B: drop low-value metadata at depth >= 2 while still keeping all list elements.
    shrunk = _strip_low_value_keys(shrunk, depth=1)
    if isinstance(shrunk, dict):
        shrunk['_truncated'] = True
    text = dump(shrunk)
    if len(text) <= limit:
        return text
    # Phase C: cut list tails only when string shrinking and metadata stripping are insufficient.
    for list_cap in _LIST_CAPS:
        capped = _cap_lists(shrunk, list_cap)
        if isinstance(capped, dict):
            capped['_truncated'] = True
        text = dump(capped)
        if len(text) <= limit:
            return text
    preview = dump(result)[: max(0, limit - 160)]
    while True:
        text = dump({'_truncated': True, 'note': 'The result was too large to show in full; ask a narrower question.',
                     'preview': preview})
        if len(text) <= limit or not preview:
            return text
        preview = preview[: len(preview) // 2]  # escaping can double the size of a JSON preview


def result_limit(used_chars) -> int:
    """Room left for the next tool result, given how many characters earlier results of this turn used."""
    return max(_budget(800, 200), min(_budget(5200, 800), _budget(12000, 1600) - used_chars))


def cut_text(text, limit) -> str:
    text = text if isinstance(text, str) else ''
    return text[:limit].rstrip() + '…' if len(text) > limit else text


def fit_history(messages, budget=None, per_message=None):
    """Earlier turns of a shaped transcript (`model_history`) cut to `budget`, newest kept.

    `messages` holds alternating user/assistant turns that start with a user turn, then the turn in
    progress. Long earlier messages are shortened first; whole oldest user/assistant pairs go next, so the
    transcript still alternates. The turn in progress is never touched.
    """
    budget = _budget(6000, 1000) if budget is None else budget
    per_message = _budget(1500, 300) if per_message is None else per_message
    last_user = max((i for i, m in enumerate(messages) if m.get('role') == 'user'), default=None)
    if last_user is None:
        return list(messages)
    settled = [{**m, 'content': cut_text(m.get('content'), per_message)} for m in messages[:last_user]]
    while settled and sum(len(m['content']) for m in settled) > budget:
        del settled[:2]
    return settled + list(messages[last_user:])


def transcript_size(messages) -> int:
    """Characters of a transcript the way validate_messages counts them."""
    return sum(len(m.get('content') or '') + len(json.dumps(m.get('tool_calls', []), ensure_ascii=False))
               for m in messages)


def fit_transcript(messages, limit):
    """The transcript with the oldest tool results of the turn in progress shortened until it fits `limit`.

    Each result was already cut when it arrived; this is the last guard for a turn whose results together
    would still not fit. Only tool results change: the system text, the customer's words and what the model
    said stay exactly as they are, and the newest results are the last to be cut.
    """
    fitted = list(messages)
    if transcript_size(fitted) <= limit:
        return fitted
    for cap in (2400, 1200, 600, 300):
        for index, message in enumerate(fitted):
            if message.get('role') != 'tool' or len(message['content']) <= cap:
                continue
            try:
                data = json.loads(message['content'])
            except ValueError:
                data = {'preview': message['content']}
            fitted[index] = {**message, 'content': compact_tool_result(data, cap)}
            if transcript_size(fitted) <= limit:
                return fitted
    return fitted
