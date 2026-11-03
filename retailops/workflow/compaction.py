"""Keep what the customer agent sends to the model small enough for the serving window (W3.2-D10).

One prompt is the system text, the settled history, the customer's message and every tool result of the
turn, so each part has its own character budget (the whole must stay under MAX_CHARACTERS of
agent_protocol, which the Colab proxy enforces too). The window was 8,192 tokens; the owner raised it to
16,384 on 2026-11-03 and the budgets below follow. Cutting is generic: long strings are shortened and
long lists lose their tail, with a marker, whatever the tool or the topic was. A tool result always stays
valid JSON that says it was cut, so the model never reads half a sentence as a fact.
"""
import json

TOOL_RESULT_MAX_CHARS = 5200   # one tool result
TOOL_CONTENT_BUDGET = 12000    # every tool result of one turn together
MIN_RESULT_CHARS = 800         # a late result always gets at least this much room
HISTORY_CHAR_BUDGET = 6000     # earlier turns together
HISTORY_MESSAGE_CHARS = 1500   # one earlier message
_STEPS = ((240, 10), (160, 6), (120, 4), (80, 2))  # (string cap, list cap) from gentle to harsh


def dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _shrink(value, string_cap, list_cap):
    if isinstance(value, str):
        return value[:string_cap] + '…' if len(value) > string_cap else value
    if isinstance(value, list):
        kept = [_shrink(v, string_cap, list_cap) for v in value[:list_cap]]
        if len(value) > list_cap:
            kept.append(f'…(+{len(value) - list_cap} more)')
        return kept
    if isinstance(value, dict):
        return {k: _shrink(v, string_cap, list_cap) for k, v in value.items()}
    return value


def compact_tool_result(result, limit=TOOL_RESULT_MAX_CHARS) -> str:
    """The JSON text of `result`, at most about `limit` characters, flagged when anything was cut."""
    text = dump(result)
    if len(text) <= limit:
        return text
    for string_cap, list_cap in _STEPS:
        shrunk = _shrink(result, string_cap, list_cap)
        if isinstance(shrunk, dict):
            shrunk['_truncated'] = True
        text = dump(shrunk)
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
    return max(MIN_RESULT_CHARS, min(TOOL_RESULT_MAX_CHARS, TOOL_CONTENT_BUDGET - used_chars))


def cut_text(text, limit) -> str:
    text = text if isinstance(text, str) else ''
    return text[:limit].rstrip() + '…' if len(text) > limit else text


def fit_history(messages, budget=HISTORY_CHAR_BUDGET, per_message=HISTORY_MESSAGE_CHARS):
    """Earlier turns of a shaped transcript (`model_history`) cut to `budget`, newest kept.

    `messages` holds alternating user/assistant turns that start with a user turn, then the turn in
    progress. Long earlier messages are shortened first; whole oldest user/assistant pairs go next, so the
    transcript still alternates. The turn in progress is never touched.
    """
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
