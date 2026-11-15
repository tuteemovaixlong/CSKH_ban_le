"""Offline-testable provenance and opt-in evaluation traces. No transport headers are stored."""
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path


def git_sha(root):
    try:
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True,
                                text=True, timeout=10, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        result = os.environ.get('RETAILOPS_GIT_SHA', '').strip()
    return result if re.fullmatch('[0-9a-fA-F]{40}', result) else None


def safe_payload(value, secrets=()):
    """Keep diagnostic content while removing credentials, header names and credential-bearing URLs."""
    if isinstance(value, dict):
        return {safe_payload(str(k), secrets): safe_payload(v, secrets) for k, v in value.items()
                if str(k).lower() not in ('headers', 'authorization', 'x-api-key', 'x-retailops-tunnel-token')}
    if isinstance(value, (list, tuple)):
        return [safe_payload(v, secrets) for v in value]
    if not isinstance(value, str):
        return value
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        value = value.replace(secret, '[REDACTED]')
    def url(match):
        try:
            p = urllib.parse.urlsplit(match.group())
            return '[REDACTED_URL]' if p.query or p.username or p.password else match.group()
        except ValueError:
            return '[REDACTED_URL]'
    value = re.sub(r'https?://[^\s<>"\']+', url, value)
    return re.sub(r'(?i)\b(?:authorization|x-api-key|x-retailops-tunnel-token)\b', '[REDACTED_HEADER]', value)


def server_metadata(endpoint, model, key, tunnel_token=''):
    from retailops_baseline import NoRedirects
    p = urllib.parse.urlsplit(endpoint)
    base = urllib.parse.urlunsplit((p.scheme, p.netloc, '', '', ''))
    prefix = p.path.rsplit('/chat/completions', 1)[0]
    headers = {'Authorization': 'Bearer ' + key, 'ngrok-skip-browser-warning': 'true'}
    if tunnel_token:
        headers['X-RetailOps-Tunnel-Token'] = tunnel_token
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirects())
    def get(path):
        try:
            with opener.open(urllib.request.Request(base + path, headers=headers), timeout=10) as response:
                raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                return {}
            result = json.loads(raw)
            return result if isinstance(result, dict) else {}
        except (OSError, ValueError):
            return {}
    models = get(prefix + '/models').get('data') or []
    ids = [m['id'] for m in models if isinstance(m, dict) and isinstance(m.get('id'), str)]
    served = model if model in ids else (ids[0] if len(ids) == 1 else None)
    version = get('/version').get('version')
    return {'model': served, 'vllm_version': version if isinstance(version, str) else None}


class TraceWriter:
    def __init__(self, path, context, secrets=()):
        self.path, self.context, self.secrets = Path(path) if path else None, context, secrets
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text('', encoding='utf-8')

    def call(self, request, invoke, *, wire=True):
        started = time.perf_counter()
        response, error = None, None
        try:
            response = invoke()
            return response
        except Exception as exc:
            error = {'code': getattr(exc, 'code', type(exc).__name__),
                     'kind': (getattr(exc, 'trace', None) or {}).get('error_kind', type(exc).__name__)}
            raise
        finally:
            if self.path:
                choice = ((response or {}).get('choices') or [{}])[0] if wire else {}
                message = choice.get('message') or {} if wire else (response or {}).get('message') or {}
                record = {**self.context.get(), 'request': request,
                          'response': {'content': message.get('content'),
                                       'reasoning': message.get('reasoning_content') or message.get('reasoning'),
                                       'tool_calls': message.get('tool_calls') or [],
                                       'finish_reason': choice.get('finish_reason'),
                                       'usage': (response or {}).get('usage') or {}, 'error': error},
                          'seconds': round(time.perf_counter() - started, 6)}
                with self.path.open('a', encoding='utf-8', newline='\n') as stream:
                    stream.write(json.dumps(safe_payload(record, self.secrets), ensure_ascii=False) + '\n')
