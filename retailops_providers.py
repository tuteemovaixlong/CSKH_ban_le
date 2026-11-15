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
import uuid
from pathlib import Path

from agent_protocol import (GENERAL_SYSTEM, PROTOCOL, SYSTEM, TOOLS, ProtocolError, assistant_message, merge_system,
                            request_mode, validate_messages, scoped_tools)
from retailops.model_errors import BODY_LIMIT, filter_provider_text, provider_error_text
from retailops_agent import AgentError
from retailops_baseline import NoRedirects

ANTHROPIC_ENDPOINT = 'https://api.anthropic.com/v1/messages'
GOOGLE_ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'
OPENROUTER_ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'

API_MODEL = 'meta/muse-spark-1.3-contributor'
API_MODELS = {
    API_MODEL,
    'meta/muse-spark-1.2-contributor',
    'yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2',
    'yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2-GGUF',
    'google/gemma-4-26b-a4b-it:free',
    'google/gemma-4-26b-a4b-it',
    'google/gemma-4-31b-it:free',
    'google/gemma-2-9b-it:free',
    'gemini-2.5-flash',
    'gemini-2.5-flash-lite',
    'gemini-2.0-flash',
    'gemini-2.0-flash-lite',
    'gemini-1.5-flash',
    'gemini-1.5-pro',
    'gemini-3.6-flash',
    'gemini-3.5-flash',
    'gemini-3.5-flash-lite',
    'gemini-flash-latest',
    'gemini-flash-lite-latest',
    'anthropic/claude-3.5-haiku',
    'anthropic/claude-3.5-sonnet',
    'anthropic/claude-3-haiku',
    'anthropic/claude-3-sonnet',
    'claude-3-5-haiku-20241022',
    'claude-3-5-sonnet-20241022',
    'claude-3-haiku-20240307',
    'Qwen/Qwen2-VL-7B-Instruct',
    'Qwen/Qwen2.5-VL-7B-Instruct',
    'Qwen/Qwen2.5-VL-7B-Instruct-AWQ',
    'Qwen/Qwen2.5-VL-27B-Instruct-AWQ',
    'Qwen/Qwen2.5-VL-32B-Instruct-AWQ',
    'Qwen/Qwen3.8-27B',
    'Qwen/Qwen3.8-27B-Instruct',
    'Qwen3.8-27B',
    'qwen3.8:27b',
    'qwen2-vl:7b',
    'qwen2.5-vl:7b',
    'vllm/qwen2.5-vl',
}


def resolve_api_vision_flag(vision=None, *, environ=None):
    """W4-D7: model image capability is controlled strictly by explicit config (default off), never model-name guessing."""
    if isinstance(vision, bool):
        return vision
    raw = os.getenv('RETAILOPS_API_VISION') if (vision is None and environ is None) else (
        environ.get('RETAILOPS_API_VISION') if (vision is None and environ is not None) else vision
    )
    val = 'off' if raw is None or str(raw).strip() == '' else str(raw).strip().lower()
    if val not in ('on', 'off'):
        raise ValueError('RETAILOPS_API_VISION must be on or off')
    return val == 'on'


def filter_system_prompt_for_tools(system_text, allowed_tools):
    """Removes directives requiring tools outside allowed_tools to prevent worker prompt conflicts."""
    if allowed_tools is None:
        return system_text
    allowed_set = set(allowed_tools)
    lines = []
    for line in system_text.split('\n'):
        if ('get_order' in line or 'get_context' in line) and not ({'get_order', 'get_context'} & allowed_set):
            if 'Call get_order or get_context' in line:
                continue
        if ('get_product' in line or 'search_products' in line) and not ({'get_product', 'search_products'} & allowed_set):
            if 'Call get_product' in line:
                continue
        if 'search_knowledge' in line and 'search_knowledge' not in allowed_set:
            if 'For store policies, returns, shipping guidance' in line:
                continue
        if ('prepare_order_action' in line or 'prepare_cancellation' in line) and not ({'prepare_order_action', 'prepare_cancellation'} & allowed_set):
            if 'The only cancellation-related tool is prepare_cancellation' in line or 'The only order-action preparation tool is prepare_order_action' in line:
                continue
        lines.append(line)
    return '\n'.join(lines)


TUNNEL_TOKEN_HEADER = 'X-RetailOps-Tunnel-Token'
MAX_MODEL_IMAGES = 3


def _normalize_model_image_urls(att):
    """Extract at most MAX_MODEL_IMAGES EXIF-free, <=1024 px data URLs from an attachment dict (W4-D3, W4-D7)."""
    from retailops.business.evidence import decode_attachment_data_payload, project_image_for_model

    raw_items = []
    if isinstance(att.get('images'), list) and att['images']:
        for item in att['images'][:MAX_MODEL_IMAGES]:
            if isinstance(item, str) and item.strip():
                raw_items.append((item.strip(), att.get('mime_type', 'image/jpeg')))
            elif isinstance(item, dict) and isinstance(item.get('data'), str) and item['data'].strip():
                raw_items.append((item['data'].strip(), item.get('mime_type') or att.get('mime_type') or 'image/jpeg'))
    elif isinstance(att.get('data'), str) and att['data'].strip():
        raw_items.append((att['data'].strip(), att.get('mime_type', 'image/jpeg')))

    urls = []
    for raw_data, fallback_mime in raw_items[:MAX_MODEL_IMAGES]:
        try:
            raw_bytes = decode_attachment_data_payload(raw_data)
            proj = project_image_for_model(raw_bytes)
            urls.append(proj['data_url'])
        except Exception:
            data_url = raw_data if raw_data.startswith('data:') else f"data:{fallback_mime};base64,{raw_data}"
            urls.append(data_url)
    return urls


def read_provider_secret(name, environ=None):
    env = os.environ if environ is None else environ
    file_var = f'{name}_FILE'
    direct = (env.get(name) or '').strip()
    filepath = (env.get(file_var) or '').strip()
    if direct and filepath:
        raise ValueError(f'Set only one of {name} or {file_var}')
    if filepath:
        try:
            return Path(filepath).read_text(encoding='utf-8').strip()
        except OSError:
            raise ValueError(f'Cannot read secret file for {name}') from None
    return direct


SAMPLING_FIELDS = ('temperature', 'top_p', 'top_k', 'presence_penalty', 'max_tokens')


def model_sampling(environ=None):
    """OpenAI-compatible overrides; absence preserves the production payload exactly."""
    env = os.environ if environ is None else environ
    result = {'temperature': 0.2, 'max_tokens': 2048}
    for field in SAMPLING_FIELDS:
        name = 'RETAILOPS_MODEL_' + field.upper()
        raw = env.get(name, '').strip()
        if not raw:
            continue
        integer = field in ('top_k', 'max_tokens')
        bounds = {'temperature': (0, 2), 'top_p': (0, 1), 'presence_penalty': (-2, 2)}
        description = 'a positive integer' if integer else str(bounds[field])
        try:
            value = int(raw) if integer else float(raw)
            valid = value > 0 if integer else math.isfinite(value) and bounds[field][0] <= value <= bounds[field][1]
            if field == 'top_p':
                valid = valid and value > 0
            if not valid:
                raise ValueError()
        except (ValueError, OverflowError):
            raise ValueError(f'{name} must be {description}' + (' (greater than 0)' if field == 'top_p' else '')) from None
        result[field] = value
    return result


class OpenRouterAgent:
    ENDPOINT = OPENROUTER_ENDPOINT

    def __init__(self, key, model=API_MODEL, *, tunnel_token=None, endpoint=None, vision=None):
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{32,256}', key):
            raise ValueError('Set a valid API key on the server')
        resolved_tunnel = read_provider_secret('RETAILOPS_API_TUNNEL_TOKEN') if tunnel_token is None else str(tunnel_token).strip()
        if resolved_tunnel and not re.fullmatch(r'[A-Za-z0-9_.-]{32,256}', resolved_tunnel):
            raise ValueError('Set a valid API tunnel token on the server')
        resolved_vision = resolve_api_vision_flag(vision)
        if resolved_vision and not resolved_tunnel:
            raise ValueError('RETAILOPS_API_VISION=on requires both RETAILOPS_API_KEY and RETAILOPS_API_TUNNEL_TOKEN')
        custom_endpoint = (os.getenv('RETAILOPS_API_ENDPOINT', '').strip() if endpoint is None else str(endpoint).strip())
        if not custom_endpoint and model not in API_MODELS:
            raise ValueError('API model must be an approved model')
        self.key, self.model = key, model
        self.tunnel_token = resolved_tunnel
        self._explicit_endpoint = custom_endpoint
        self.is_custom = bool(custom_endpoint)
        if custom_endpoint:
            self.endpoint = custom_endpoint
            self.ENDPOINT = custom_endpoint
            self.is_anthropic = False
            self.is_google = False
        else:
            self.is_anthropic = (
                key.startswith('sk-ant-')
                or model.startswith('claude-')
                or os.getenv('RETAILOPS_API_PROVIDER', '').lower() == 'anthropic'
            )
            self.is_google = not self.is_anthropic and (
                model.startswith('gemini-')
                or key.startswith('AIza')
                or key.startswith('AQ.')
                or os.getenv('RETAILOPS_API_PROVIDER', '').lower() == 'google'
            )
            if self.is_anthropic:
                self.endpoint = ANTHROPIC_ENDPOINT
            elif self.is_google:
                self.endpoint = GOOGLE_ENDPOINT
            else:
                self.endpoint = OPENROUTER_ENDPOINT
            self.ENDPOINT = self.endpoint
        self.is_vision = resolved_vision
        self._messages = {}
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirects())

    def for_turn(self):
        return type(self)(
            self.key,
            self.model,
            tunnel_token=self.tunnel_token,
            endpoint=self._explicit_endpoint if self.is_custom else '',
            vision=self.is_vision,
        )

    def inspect(self):
        if self.is_custom:
            provider_name = 'custom_api'
        elif self.is_anthropic:
            provider_name = 'anthropic'
        elif self.is_google:
            provider_name = 'google'
        else:
            provider_name = 'openrouter'
        return {'name': self.model, 'digest': None, 'provider': provider_name,
                'identity_source': 'configured_api_model', 'agent_protocol': PROTOCOL}


    def translate(self, messages, *, extra_tool_names=()):
        validate_messages(messages)
        # Pre-allocate image budget from newest user turn backwards so total images never exceed MAX_MODEL_IMAGES (3).
        allowed_urls_by_index = {}
        if self.is_vision:
            remaining_images = MAX_MODEL_IMAGES
            for idx in range(len(messages) - 1, -1, -1):
                m = messages[idx]
                if m.get('role') == 'user' and isinstance(m.get('attachment'), dict) and remaining_images > 0:
                    urls = _normalize_model_image_urls(m['attachment'])
                    if urls:
                        take = urls[:remaining_images]
                        allowed_urls_by_index[idx] = take
                        remaining_images -= len(take)

        translated, pending = [], []
        for index, message in enumerate(messages):
            if message['role'] == 'assistant':
                saved = self._messages.get(index)
                if saved is not None:
                    if assistant_message({'message': saved}, extra_tool_names=extra_tool_names) != message:
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
            elif message['role'] == 'user' and message.get('attachment'):
                att = message['attachment']
                text_content = message.get('content') or ''
                img_urls = allowed_urls_by_index.get(index) or []
                if att.get('type') == 'image' and (att.get('data') or att.get('images')):
                    if self.is_vision and img_urls:
                        entry = {
                            'role': 'user',
                            'content': [
                                {'type': 'text', 'text': text_content},
                                *[
                                    {'type': 'image_url', 'image_url': {'url': url}}
                                    for url in img_urls
                                ],
                            ]
                        }
                    else:
                        img_name = att.get('name') or 'hình ảnh'
                        notice = f"[Tệp đính kèm: {img_name}] (Ghi chú: Mô hình hiện tại là SLM văn bản/công cụ, không hỗ trợ nhận diện trực tiếp pixel hình ảnh. Hãy xử lý yêu cầu dựa trên văn bản và công cụ tra cứu dữ liệu)."
                        entry = {'role': 'user', 'content': f"{text_content}\n\n{notice}".strip()}
                elif att.get('type') == 'document':
                    doc_name = att.get('name', 'tài liệu')
                    excerpt = (att.get('excerpt') or '').strip()
                    doc_text = f"{text_content}\n\n[Tệp đính kèm: {doc_name}]".strip()
                    if excerpt:
                        doc_text = f"{doc_text}\n{excerpt}"
                    if self.is_vision and img_urls:
                        entry = {
                            'role': 'user',
                            'content': [
                                {'type': 'text', 'text': doc_text},
                                *[
                                    {'type': 'image_url', 'image_url': {'url': url}}
                                    for url in img_urls
                                ],
                            ]
                        }
                    else:
                        entry = {'role': 'user', 'content': doc_text}
                else:
                    entry = {'role': 'user', 'content': text_content}
            else:
                entry = dict(message)
            translated.append(entry)
        return translated

    def payload_messages(self, messages, system_prompt, allowed_tools=None, *, extra_tool_names=()):
        """Exactly one system turn; preserve transport indices/tool IDs."""
        translated = self.translate(messages, extra_tool_names=extra_tool_names)
        if allowed_tools is not None:
            system_prompt = filter_system_prompt_for_tools(system_prompt, allowed_tools)
        if translated and translated[0].get('role') == 'system':
            translated[0] = {'role': 'system', 'content': merge_system(system_prompt, translated[0]['content'])}
            return translated
        return [{'role': 'system', 'content': system_prompt}, *translated]

    def request(self, payload, timeout):
        headers = {'Content-Type': 'application/json', 'ngrok-skip-browser-warning': 'true'}
        if self.is_anthropic:
            headers['x-api-key'] = self.key
            headers['anthropic-version'] = '2023-06-01'
        else:
            headers['Authorization'] = 'Bearer ' + self.key
            if self.is_google:
                headers['x-goog-api-key'] = self.key
        if self.tunnel_token:
            headers[TUNNEL_TOKEN_HEADER] = self.tunnel_token
        request = urllib.request.Request(self.endpoint, method='POST',
            headers=headers,
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
            status = exc.code
            try:
                body = exc.read(BODY_LIMIT)
            except Exception:
                body = b''
            finally:
                exc.close()
            # The provider message is kept only in the trace, filtered and cut to 300 characters.
            raw_provider_msg = self._safe_text(provider_error_text(body))
            if not raw_provider_msg and status == 401:
                raw_provider_msg = 'Endpoint rejected Bearer authentication (HTTP 401; check RETAILOPS_API_KEY / --api-key).'
            elif not raw_provider_msg and status == 403:
                raw_provider_msg = 'Endpoint or tunnel policy rejected request (HTTP 403; check RETAILOPS_API_TUNNEL_TOKEN / traffic policy).'
            detail = {'http_status': status, 'provider_message': raw_provider_msg}
            if status == 401:
                detail['auth_layer'] = 'api_key'
            elif status == 403:
                detail['auth_layer'] = 'tunnel_policy_or_forbidden'
            error_map = {
                400: ('api_unavailable', f'Yêu cầu API không hợp lệ (HTTP {status}).', 'bad_request'),
                401: ('api_auth_failed', 'API chưa xác thực được. Chủ demo cần kiểm tra API key/quyền truy cập.', 'authentication_failed'),
                402: ('api_credit_exhausted', 'API không đủ tín dụng. Bạn có thể chọn custom model đã được cấu hình.', 'credit_exhausted'),
                403: ('api_auth_failed', 'API chưa xác thực được. Chủ demo cần kiểm tra API key/quyền truy cập.', 'forbidden'),
                404: ('api_unavailable', f'Không tìm thấy API endpoint (HTTP {status}).', 'not_found'),
                413: ('api_unavailable', f'Dung lượng yêu cầu quá lớn (HTTP {status}).', 'payload_too_large'),
                422: ('api_unavailable', f'Dữ liệu yêu cầu không thể xử lý (HTTP {status}).', 'unprocessable_entity'),
                429: ('api_rate_limited', 'API đang giới hạn lưu lượng. Bạn thử lại sau nhé.', 'rate_limited'),
                503: ('api_unavailable', f'Dịch vụ tạm thời không khả dụng (HTTP {status}).', 'service_unavailable'),
            }
            if status in error_map:
                code, msg, kind = error_map[status]
                raise AgentError(code, msg, {**detail, 'error_kind': kind}) from None
            raise AgentError('api_unavailable', f'API chưa hoàn tất yêu cầu (HTTP {status}). Không tự chuyển sang model khác.', {**detail, 'error_kind': f'http_{status}'}) from None
        except (RuntimeError, OSError, ValueError) as exc:
            # The exception text is filtered for the trace only; URLs, bodies and credentials never reach users.
            err_kind = 'timeout' if isinstance(exc, (TimeoutError, urllib.error.URLError)) and 'timed out' in str(exc).lower() else type(exc).__name__
            raise AgentError('api_unavailable', 'Không nhận được phản hồi API hợp lệ. Bạn có thể thử lại sau.',
                             {'error_kind': err_kind, 'provider_message': self._safe_text(str(exc))}) from None

    def _safe_text(self, text):
        """Provider/transport text that may enter a trace: no key, URL, endpoint or opaque token."""
        return filter_provider_text(text, secrets=(self.key, self.tunnel_token, self.endpoint), keep=(self.model,))

    def _chat_anthropic(self, messages, allow_tools, timeout, *, allowed_tools=None,
                        system_override=None, tool_schemas_override=None):
        validate_messages(messages)
        mode = 'retail' if system_override is not None else request_mode(messages)
        system_prompt = system_override if system_override is not None else (GENERAL_SYSTEM if mode == 'general' else SYSTEM)
        if allowed_tools is not None and system_override is None:
            system_prompt = filter_system_prompt_for_tools(system_prompt, allowed_tools)
        raw_tools = list(tool_schemas_override) if tool_schemas_override is not None else scoped_tools(allowed_tools)
        extra_names = tuple(t['function']['name'] for t in raw_tools) if tool_schemas_override is not None else ()
        anthropic_tools = []
        if mode != 'general' and allow_tools:
            for t in raw_tools:
                fn = t['function']
                anthropic_tools.append({
                    'name': fn['name'],
                    'description': fn['description'],
                    'input_schema': fn['parameters']
                })

        anthropic_messages = []
        pending_ids = []
        i = 0
        while i < len(messages):
            m = messages[i]
            if m['role'] == 'system':
                system_prompt = merge_system(system_prompt, m['content'])
                i += 1
            elif m['role'] == 'user':
                if self.is_vision and m.get('attachment') and m['attachment'].get('type') == 'image' and m['attachment'].get('data'):
                    att = m['attachment']
                    data = att.get('data', '')
                    if ',' in data:
                        data = data.split(',', 1)[1]
                    mime = att.get('mime_type', 'image/jpeg')
                    anthropic_messages.append({
                        'role': 'user',
                        'content': [
                            {'type': 'text', 'text': m['content']},
                            {'type': 'image', 'source': {'type': 'base64', 'media_type': mime, 'data': data}}
                        ]
                    })
                else:
                    anthropic_messages.append({'role': 'user', 'content': m['content']})
                i += 1
            elif m['role'] == 'assistant':
                saved = self._messages.get(i)
                text = m.get('content') or ''
                content = []
                if text:
                    content.append({'type': 'text', 'text': text})
                tool_calls = (saved.get('tool_calls') if saved else None) or m.get('tool_calls') or []
                pending_ids = []
                for j, call in enumerate(tool_calls):
                    fn = call['function']
                    args = json.loads(fn['arguments']) if isinstance(fn['arguments'], str) else fn['arguments']
                    cid = call.get('id') or f'history_{i}_{j}'
                    pending_ids.append(cid)
                    content.append({'type': 'tool_use', 'id': cid, 'name': fn['name'], 'input': args})
                anthropic_messages.append({'role': 'assistant', 'content': content or ''})
                i += 1
            elif m['role'] == 'tool':
                tool_results = []
                while i < len(messages) and messages[i]['role'] == 'tool':
                    tm = messages[i]
                    if not pending_ids:
                        raise ProtocolError('Missing Anthropic tool call ID')
                    cid = pending_ids.pop(0)
                    tool_results.append({'type': 'tool_result', 'tool_use_id': cid, 'content': tm['content']})
                    i += 1
                anthropic_messages.append({'role': 'user', 'content': tool_results})

        payload = {
            'model': self.model,
            'max_tokens': 2048,
            'temperature': 0.2,
            'system': system_prompt,
            'messages': anthropic_messages,
        }
        if anthropic_tools:
            payload['tools'] = anthropic_tools

        result = self.request(payload, timeout)
        if result.get('error'):
            raise AgentError('api_unavailable', 'API báo lỗi xử lý. Không tự chuyển model hoặc gửi lại yêu cầu.')

        content_blocks = result.get('content') or []
        text_parts = []
        raw_tool_calls = []
        for block in content_blocks:
            if block.get('type') == 'text':
                text_parts.append(block.get('text', ''))
            elif block.get('type') == 'tool_use':
                raw_tool_calls.append({
                    'id': block['id'],
                    'type': 'function',
                    'function': {
                        'name': block['name'],
                        'arguments': json.dumps(block.get('input', {}), ensure_ascii=False)
                    }
                })

        entry = {'role': 'assistant', 'content': ''.join(text_parts)}
        if raw_tool_calls:
            entry['tool_calls'] = raw_tool_calls
            self._messages[len(messages)] = entry

        clean = assistant_message({'message': entry}, extra_tool_names=extra_names)
        usage = result.get('usage') or {}
        prompt_tokens = usage.get('input_tokens', 0)
        completion_tokens = usage.get('output_tokens', 0)

        return {'message': clean, 'done_reason': 'stop', 'model': self.model,
                'prompt_eval_count': prompt_tokens, 'eval_count': completion_tokens,
                'reported_cost_usd': None, 'reasoning': None}

    def chat_scoped(self, messages, allow_tools, timeout, allowed_tools):
        return self.chat(messages, allow_tools, timeout, allowed_tools=allowed_tools)

    def chat_profile(self, messages, allow_tools, timeout, *, system_prompt, tool_schemas):
        return self.chat(messages, allow_tools, timeout,
                         system_override=system_prompt, tool_schemas_override=tool_schemas)

    def chat(self, messages, allow_tools, timeout, *, allowed_tools=None,
             system_override=None, tool_schemas_override=None):
        available = list(tool_schemas_override) if tool_schemas_override is not None else scoped_tools(allowed_tools)
        extra_names = tuple(t['function']['name'] for t in available) if tool_schemas_override is not None else ()
        if self.is_anthropic:
            return self._chat_anthropic(messages, allow_tools, timeout, allowed_tools=allowed_tools,
                                        system_override=system_override, tool_schemas_override=tool_schemas_override)
        mode = 'retail' if system_override is not None else request_mode(messages)
        system_prompt = system_override if system_override is not None else (GENERAL_SYSTEM if mode == 'general' else SYSTEM)
        tools = [] if mode == 'general' else available
        tool_choice = 'none' if not tools or not allow_tools else 'auto'
        payload = {'model': self.model, 'messages': self.payload_messages(
                       messages, system_prompt,
                       allowed_tools=(None if system_override is not None else allowed_tools),
                       extra_tool_names=extra_names),
                   'stream': False, 'max_tokens': 2048, 'temperature': 0.2}
        if not self.is_google:
            payload.update(model_sampling())
        thinking = os.environ.get('RETAILOPS_MODEL_ENABLE_THINKING', '').strip().lower()
        if thinking:
            if thinking not in ('true', 'false'):
                raise ValueError('RETAILOPS_MODEL_ENABLE_THINKING must be true or false')
            payload['chat_template_kwargs'] = {'enable_thinking': thinking == 'true'}
        custom_endpoint = self._explicit_endpoint if self.is_custom else os.getenv('RETAILOPS_API_ENDPOINT', '').strip()
        if custom_endpoint:
            if tools and allow_tools:
                payload['tools'] = tools
                payload['tool_choice'] = tool_choice
        elif not self.is_google:
            payload['tools'] = tools
            payload['tool_choice'] = tool_choice
            provider_options = {'allow_fallbacks': False}
            if self.model.startswith('meta/'):
                provider_options['only'] = ['meta']
                payload['reasoning'] = {'effort': 'minimal'}
            payload['provider'] = provider_options
        else:
            if tools:
                payload['tools'] = tools
                payload['tool_choice'] = tool_choice
        result = self.request(payload, timeout)
        if result.get('error'):
            raise AgentError('api_unavailable', 'API báo lỗi xử lý. Không tự chuyển model hoặc gửi lại yêu cầu.')
        returned_model = result.get('model') or ''
        model_matches = (
            returned_model == self.model
            or (self.is_google and (returned_model.startswith(self.model) or returned_model.startswith('models/' + self.model) or self.model in returned_model))
            or (custom_endpoint and (self.model in returned_model or returned_model in self.model or not returned_model))
        )
        if not model_matches:
            raise AgentError('api_model_mismatch', 'API trả về model khác cấu hình; lượt chat chưa được chấp nhận.')
        choices = result.get('choices')
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ProtocolError('Invalid API choices')
        choice = choices[0]
        raw_usage = result.get('usage') if isinstance(result.get('usage'), dict) else {}
        reply_facts = {'finish_reason': str(choice.get('finish_reason'))[:32],
                       'completion_tokens': raw_usage.get('completion_tokens') if type(raw_usage.get('completion_tokens')) is int else None}
        if choice.get('finish_reason') not in ('stop', 'tool_calls'):
            raise ProtocolError('API response incomplete or refused', **reply_facts)
        raw = choice.get('message')
        if not isinstance(raw, dict) or raw.get('role') != 'assistant':
            raise ProtocolError('Invalid API message', **reply_facts)
        entry = {'role': 'assistant', 'content': raw.get('content') or ''}
        if raw.get('tool_calls'):
            entry['tool_calls'] = raw['tool_calls']
        try:
            clean = assistant_message({'message': entry}, extra_tool_names=extra_names)
        except ProtocolError as exc:
            # Tokens were generated even though nothing usable came back: record that, not "0 token".
            exc.diagnostics = {**reply_facts,
                               'had_reasoning': bool(raw.get('reasoning') or raw.get('reasoning_content'))}
            raise
        if clean.get('tool_calls'):
            ids = []
            if not entry.get('tool_calls'):
                entry['tool_calls'] = [
                    {
                        'id': f'call_{i}_{uuid.uuid4().hex[:8]}',
                        'type': 'function',
                        'function': {
                            'name': c['function']['name'],
                            'arguments': json.dumps(c['function']['arguments'], ensure_ascii=False)
                            if isinstance(c['function']['arguments'], dict) else str(c['function']['arguments'])
                        }
                    }
                    for i, c in enumerate(clean['tool_calls'])
                ]
            for call in entry['tool_calls']:
                cid = call.get('id')
                if call.get('type') != 'function' or not isinstance(cid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', cid):
                    raise ProtocolError('Invalid API tool ID')
                ids.append(cid)
            if len(set(ids)) != len(ids):
                raise ProtocolError('Duplicate API tool IDs')
            # Opaque provider reasoning stays in this turn only, never SQLite/trace/UI.
            for key in ('reasoning', 'reasoning_details', 'reasoning_content'):
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
        reasoning_val = raw.get('reasoning') or raw.get('reasoning_content')
        return {'message': clean, 'done_reason': 'stop', 'model': self.model,
                'prompt_eval_count': usage['prompt_tokens'], 'eval_count': usage['completion_tokens'],
                'reported_cost_usd': cost, 'reasoning': reasoning_val}


def api_from_environment():
    vision_enabled = resolve_api_vision_flag()
    explicit_api_key = read_provider_secret('RETAILOPS_API_KEY')
    tunnel_token = read_provider_secret('RETAILOPS_API_TUNNEL_TOKEN')
    if vision_enabled and (not explicit_api_key or not tunnel_token):
        raise ValueError('RETAILOPS_API_VISION=on requires both RETAILOPS_API_KEY and RETAILOPS_API_TUNNEL_TOKEN')
    if os.getenv('RETAILOPS_API_ENABLED', 'false').lower() != 'true':
        return None
    key = (
        explicit_api_key
        or os.getenv('ANTHROPIC_API_KEY')
        or os.getenv('GEMINI_API_KEY')
        or os.getenv('OPENROUTER_API_KEY', '')
    )
    if os.getenv('ANTHROPIC_API_KEY') and not explicit_api_key:
        default_model = 'claude-3-5-haiku-20241022'
    elif os.getenv('GEMINI_API_KEY') and not explicit_api_key:
        default_model = 'gemini-2.5-flash'
    else:
        default_model = API_MODEL
    return OpenRouterAgent(
        key,
        os.getenv('RETAILOPS_API_MODEL', default_model),
        tunnel_token=tunnel_token,
        vision=vision_enabled,
    )
