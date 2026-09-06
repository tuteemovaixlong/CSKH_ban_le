"""Server-configured OpenRouter adapter; never accepts keys or endpoints from a browser.

Tool IDs and reasoning blocks are retained only during one in-memory model turn.
Completed history uses the existing provider-neutral transcript and stores no reasoning.
"""
import copy
import json
import math
import os
import re
import urllib.error
import urllib.request

from agent_protocol import PROTOCOL, SYSTEM, TOOLS, ProtocolError, assistant_message, validate_messages
from retailops_agent import AgentError
from retailops_baseline import NoRedirects

API_MODEL = 'meta/muse-spark-1.3-contributor'
API_MODELS = {API_MODEL, 'meta/muse-spark-1.2-contributor'}


class OpenRouterAgent:
    ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'

    def __init__(self, key, model=API_MODEL):
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', key):
            raise ValueError('Set a valid OpenRouter API key on the server')
        if model not in API_MODELS:
            raise ValueError('API model must be an approved Muse Spark Contributor model')
        self.key, self.model = key, model
        self._messages = {}
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirects())

    def for_turn(self):
        return type(self)(self.key, self.model)

    def inspect(self):
        # This is configuration, not a successful connectivity probe or a weights hash.
        return {'name': self.model, 'digest': None, 'provider': 'openrouter',
                'identity_source': 'configured_api_model', 'agent_protocol': PROTOCOL}

    def translate(self, messages):
        validate_messages(messages)
        translated, pending = [], []
        for index, message in enumerate(messages):
            if message['role'] == 'assistant':
                saved = self._messages.get(index)
                if saved is not None:
                    if assistant_message({'message': saved}) != message:
                        raise ProtocolError('Current tool transcript changed')
                    entry = copy.deepcopy(saved)
                else:
                    entry = {'role': 'assistant', 'content': message['content']}
                    if message.get('tool_calls'):
                        entry['tool_calls'] = [
                            {'id': f'history_{index}_{j}', 'type': 'function', 'function': {
                                'name': call['function']['name'],
                                'arguments': json.dumps(call['function']['arguments'], ensure_ascii=False)}}
                            for j, call in enumerate(message['tool_calls'])]
                pending = [call['id'] for call in entry.get('tool_calls', [])]
            elif message['role'] == 'tool':
                if not pending:
                    raise ProtocolError('Missing API tool call ID')
                entry = {'role': 'tool', 'tool_call_id': pending.pop(0), 'content': message['content']}
            else:
                entry = dict(message)
            translated.append(entry)
        return translated

    def request(self, payload, timeout):
        request = urllib.request.Request(self.ENDPOINT, method='POST',
            headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'},
            data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode())
        try:
            with self._opener.open(request, timeout=timeout) as response:
                raw = response.read(1_048_577)
                if len(raw) > 1_048_576:
                    raise ValueError('Oversize provider response')
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError('Invalid provider response')
                return result
        except urllib.error.HTTPError as exc:
            status = exc.code; exc.close()
            if status in (401, 403):
                raise AgentError('api_auth_failed', 'API chưa xác thực được. Chủ demo cần kiểm tra API key/quyền truy cập.') from None
            if status == 402:
                raise AgentError('api_credit_exhausted', 'API không đủ tín dụng. Bạn có thể chọn custom model đã được cấu hình.') from None
            if status == 429:
                raise AgentError('api_rate_limited', 'API đang giới hạn lưu lượng. Bạn thử lại sau nhé.') from None
            raise AgentError('api_unavailable', 'API chưa hoàn tất yêu cầu. Không tự chuyển sang model khác.') from None
        except (RuntimeError, OSError, ValueError):
            # Strip URLs, upstream bodies and credentials from exceptions.
            raise AgentError('api_unavailable', 'Không nhận được phản hồi API hợp lệ. Bạn có thể thử lại sau.') from None

    def chat(self, messages, allow_tools, timeout):
        payload = {'model': self.model, 'messages': [{'role': 'system', 'content': SYSTEM}] + self.translate(messages),
                   'tools': TOOLS, 'tool_choice': 'auto' if allow_tools else 'none', 'stream': False,
                   'max_tokens': 2048, 'temperature': 0.2,
                   'reasoning': {'effort': 'minimal'},
                   'provider': {'only': ['meta'], 'allow_fallbacks': False}}
        result = self.request(payload, timeout)
        if result.get('error'):
            raise AgentError('api_unavailable', 'API báo lỗi xử lý. Không tự chuyển model hoặc gửi lại yêu cầu.')
        if result.get('model') != self.model:
            raise AgentError('api_model_mismatch', 'API trả về model khác cấu hình; lượt chat chưa được chấp nhận.')
        choices = result.get('choices')
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ProtocolError('Invalid API choices')
        choice = choices[0]
        if choice.get('finish_reason') not in ('stop', 'tool_calls'):
            raise ProtocolError('API response incomplete or refused')
        raw = choice.get('message')
        if not isinstance(raw, dict) or raw.get('role') != 'assistant':
            raise ProtocolError('Invalid API message')
        entry = {'role': 'assistant', 'content': raw.get('content') or ''}
        if raw.get('tool_calls'):
            entry['tool_calls'] = raw['tool_calls']
        clean = assistant_message({'message': entry})
        if clean.get('tool_calls'):
            ids = []
            for call in entry['tool_calls']:
                cid = call.get('id')
                if call.get('type') != 'function' or not isinstance(cid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', cid):
                    raise ProtocolError('Invalid API tool ID')
                ids.append(cid)
            if len(set(ids)) != len(ids):
                raise ProtocolError('Duplicate API tool IDs')
            # Opaque provider reasoning stays in this turn only, never SQLite/trace/UI.
            for key in ('reasoning', 'reasoning_details'):
                if raw.get(key) is not None:
                    entry[key] = copy.deepcopy(raw[key])
            self._messages[len(messages)] = entry
        usage = result.get('usage') or {}
        if not isinstance(usage, dict):
            raise ProtocolError('Invalid API token usage')
        for key in ('prompt_tokens', 'completion_tokens'):
            if type(usage.get(key)) is not int or not 0 <= usage[key] <= 2_000_000:
                raise ProtocolError('API token usage missing or invalid')
        cost = usage.get('cost')
        if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
            raise ProtocolError('Invalid API cost')
        return {'message': clean, 'done_reason': 'stop', 'model': self.model,
                'prompt_eval_count': usage['prompt_tokens'], 'eval_count': usage['completion_tokens'],
                'reported_cost_usd': cost}


def api_from_environment():
    if os.getenv('RETAILOPS_API_ENABLED', 'false').lower() != 'true':
        return None
    return OpenRouterAgent(os.getenv('OPENROUTER_API_KEY', ''), os.getenv('RETAILOPS_API_MODEL', API_MODEL))
