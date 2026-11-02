"""Test doubles for a vLLM endpoint that serves a Gemma chat template. No network, no model.

The fake sits under `OpenRouterAgent` (at the urllib opener), so every request goes through the
real message translation and error mapping before the fake template and the scripted model see it.
"""
import io
import json
import urllib.error
import urllib.request
from unittest.mock import patch

TEMPLATE_ERROR = 'Conversation roles must alternate user/assistant/user/assistant/...'
FIXTURE_MODEL = 'fixture-gemma-vllm'
FIXTURE_ENDPOINT = 'https://fixture-vllm.example/v1/chat/completions'
FIXTURE_KEY = 'fixture_not_a_secret_' + 'g' * 40


def gemma_template_error(messages):
    """Return None when a strict Gemma-style template accepts `messages`, else its error text.

    Rules from the W3.2 handoff (item 0): an optional leading system turn, then strictly
    alternating user/assistant turns; a `tool` or `system` turn inside the history is rejected.
    Only the turn in progress (after the last user message) may carry native tool calls and results.
    """
    turns = list(messages)
    if turns and turns[0].get('role') == 'system':
        turns = turns[1:]
    users = [i for i, m in enumerate(turns) if m.get('role') == 'user']
    if not users:
        return TEMPLATE_ERROR
    last = users[-1]
    for index, message in enumerate(turns[:last + 1]):
        role = message.get('role')
        if role in ('tool', 'system') or message.get('tool_calls'):
            return f"{TEMPLATE_ERROR} (history turn {index} has role/tool_calls '{role}')"
        if (role == 'user') != (index % 2 == 0):
            return TEMPLATE_ERROR
    for message in turns[last + 1:]:
        if message.get('role') not in ('assistant', 'tool'):
            return TEMPLATE_ERROR
    return None


def chat_reply(content='Dạ ok', calls=(), *, model=FIXTURE_MODEL, finish_reason=None,
               prompt_tokens=80, completion_tokens=20):
    """An OpenAI-style chat completion, as vLLM returns it."""
    message = {'role': 'assistant', 'content': content}
    if calls:
        message['tool_calls'] = [
            {'id': f'call_{i}', 'type': 'function',
             'function': {'name': name, 'arguments': json.dumps(args)}}
            for i, (name, args) in enumerate(calls)]
    return {'model': model,
            'choices': [{'message': message,
                         'finish_reason': finish_reason or ('tool_calls' if calls else 'stop')}],
            'usage': {'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens}}


def http_error(status, body):
    raw = body if isinstance(body, (bytes, bytearray)) else json.dumps(body, ensure_ascii=False).encode()
    return urllib.error.HTTPError(FIXTURE_ENDPOINT, status, 'fixture', {}, io.BytesIO(bytes(raw)))


class _Response:
    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        return self._data if size is None or size < 0 else self._data[:size]


class FakeVllm:
    """Replaces the HTTP layer under OpenRouterAgent.

    `script(payload)` returns an OpenAI-style dict, or an exception instance to raise. With
    `strict=True` the payload first has to pass `gemma_template_error`; otherwise vLLM's HTTP 400
    template error is returned, like the real server would.
    """
    def __init__(self, script, *, strict=True):
        self.script, self.strict = script, strict
        self.payloads = []

    def _open(self, opener, request, *args, **kwargs):
        payload = json.loads(request.data)
        self.payloads.append(payload)
        if self.strict:
            error = gemma_template_error(payload['messages'])
            if error:
                raise http_error(400, {'object': 'error', 'message': error,
                                       'type': 'BadRequestError', 'code': 400})
        result = self.script(payload)
        if isinstance(result, BaseException):
            raise result
        return _Response(json.dumps(result).encode())

    def install(self):
        fake = self

        def open_(opener, request, data=None, timeout=None):
            return fake._open(opener, request)
        return patch.object(urllib.request.OpenerDirector, 'open', open_)
