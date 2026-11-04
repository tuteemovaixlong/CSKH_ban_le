"""Diagnosable model failures: one recorder shared by every worker (W3.2-D8).

`trace['model_errors']` is a short list. Each entry says which call failed and why: the
failure kind, the HTTP status when a provider answered, and the first 300 characters of the
provider (or transport) message with secrets, URLs and opaque tokens removed.
"""
import json
import re

from retailops.guardrails.topic_filter import contains_canary_or_secret

MESSAGE_LIMIT = 300
MAX_ENTRIES = 8
BODY_LIMIT = 4096
REDACTED = '[REDACTED]'

_URL = re.compile(r'(?:https?|wss?)://[^\s"\'<>]+', re.IGNORECASE)
_BEARER = re.compile(r'(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}')
_CREDENTIAL_FIELD = re.compile(
    r'(?i)\b(?:authorization|x-api-key|x-goog-api-key|x-retailops-tunnel-token|'
    r'tunnel[_-]?token|api[_-]?key|access[_-]?token|secret|password)\b'
    r'\s*[:=]\s*[^\s,;"\'}]+')
_JWT = re.compile(r'\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b')
_KEY_SHAPES = re.compile(r'\b(?:sk-(?:proj-|or-v1-|ant-)?[A-Za-z0-9_-]{12,}|AIza[0-9A-Za-z_-]{20,})\b')
_OPAQUE = re.compile(r'(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])')
_SPACES = re.compile(r'\s+')
_DIAGNOSTIC_KEYS = ('finish_reason', 'completion_tokens', 'had_reasoning', 'stage', 'upstream_code', 'auth_layer')


def filter_provider_text(text, *, secrets=(), keep=(), limit=MESSAGE_LIMIT):
    """Return at most `limit` characters of `text` that are safe to store in a trace."""
    text = str(text if text is not None else '')[:BODY_LIMIT]
    holders = {}
    for index, name in enumerate(n for n in keep if isinstance(n, str) and len(n) >= 4):
        marker = f'\x00keep{index}\x00'
        if name in text:
            holders[marker] = name
            text = text.replace(name, marker)
    for secret in sorted((s for s in secrets if isinstance(s, str) and len(s) >= 6), key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    for pattern in (_URL, _BEARER, _CREDENTIAL_FIELD, _JWT, _KEY_SHAPES, _OPAQUE):
        text = pattern.sub(REDACTED, text)
    text = _SPACES.sub(' ', text).strip()
    for marker, name in holders.items():
        text = text.replace(marker, name)
    if contains_canary_or_secret(text):
        return '[REDACTED_BY_OUTPUT_GUARD]'
    return text[:limit]


def _message_from_json(data):
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, list):
        parts = [_message_from_json(item) for item in data[:4]]
        return '; '.join(p for p in parts if p)
    if isinstance(data, dict):
        for key in ('error', 'message', 'detail', 'msg'):
            if key in data:
                found = _message_from_json(data[key])
                if found:
                    return found
    return ''


def provider_error_text(body):
    """Pull the readable message out of an HTTP error body, JSON or plain text."""
    if isinstance(body, (bytes, bytearray)):
        body = bytes(body)[:BODY_LIMIT].decode('utf-8', errors='replace')
    text = str(body or '').strip()
    try:
        data = json.loads(text)
    except ValueError:
        return text
    return _message_from_json(data) or text


def error_entry(exc, *, code, call, secrets=(), keep=()):
    """Describe one failed model call without ever echoing a secret."""
    source = exc.trace if isinstance(getattr(exc, 'trace', None), dict) else {}
    diagnostics = getattr(exc, 'diagnostics', None)
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    is_agent_error = hasattr(exc, 'code') and hasattr(exc, 'trace')
    entry = {'call': call, 'code': code}
    entry['error_kind'] = str(source.get('error_kind') or (code if is_agent_error else type(exc).__name__))[:64]
    http_status = getattr(exc, 'http_status', None) or source.get('http_status')
    if isinstance(http_status, int) and 100 <= http_status <= 599:
        entry['http_status'] = http_status
    message = source.get('provider_message')
    if message is None and not is_agent_error:
        message = str(exc)
    if message:
        entry['provider_message'] = filter_provider_text(message, secrets=secrets, keep=keep)
    for key in _DIAGNOSTIC_KEYS:
        value = diagnostics.get(key, source.get(key))
        if isinstance(value, (int, bool)) or (isinstance(value, str) and len(value) <= 64):
            entry[key] = value
    return entry


def record_model_error(trace, exc, *, code, call=None, secrets=(), keep=()):
    """Append a diagnosable entry for a failed model call to `trace['model_errors']`."""
    if call is None:
        call = trace.get('model_calls', 0)
    entry = error_entry(exc, code=code, call=call, secrets=secrets, keep=keep)
    entries = trace.setdefault('model_errors', [])
    if len(entries) < MAX_ENTRIES:
        entries.append(entry)
    return entry
