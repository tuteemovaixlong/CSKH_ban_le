"""Bounded native tool-calling loop; no business writes or text routing rules."""
import json
import time
import uuid
from dataclasses import replace

from agent_protocol import (MAX_MODEL_CALLS, MAX_TOOL_CALLS, PROTOCOL, ProtocolError,
                            assistant_message, build_request, validate_messages, validate_tool)
from retailops_baseline import LocalOllama, RemoteOllama


class AgentError(RuntimeError):
    def __init__(self, code, message, trace=None):
        self.code, self.trace = code, trace or {}
        super().__init__(message)


class LocalAgent:
    """Colab-only attended smoke adapter; same system/tools as the proxy."""
    def __init__(self, config):
        self.config = config

    def inspect(self):
        return {**LocalOllama(self.config).inspect(), 'agent_protocol': PROTOCOL}

    def chat(self, messages, allow_tools, timeout):
        gateway = LocalOllama(replace(self.config, timeout_s=timeout))
        return gateway.request('/api/chat', build_request(self.config.model, messages, allow_tools))


class RemoteAgent:
    def __init__(self, config, allowed_host, token):
        self.config, self.allowed_host, self.token = config, allowed_host, token
        # Validate endpoint and credentials before any request.
        RemoteOllama(config, allowed_host=allowed_host, token=token)

    def gateway(self, timeout):
        return RemoteOllama(replace(self.config, timeout_s=timeout), allowed_host=self.allowed_host, token=self.token)

    def inspect(self):
        try:
            identity = self.gateway(10).request('/agent/identity')
        except RuntimeError as exc:
            if '404' in str(exc):
                raise AgentError('proxy_upgrade_required', 'Proxy Colab chưa hỗ trợ agent. Chạy notebook colab_agent.ipynb mới trước.') from None
            raise
        if identity.get('agent_protocol') != PROTOCOL or identity.get('name') != self.config.model or not identity.get('digest'):
            raise AgentError('proxy_upgrade_required', 'Proxy Colab chưa hỗ trợ phiên bản agent. Chạy notebook agent mới trước.')
        return identity

    def chat(self, messages, allow_tools, timeout):
        return self.gateway(timeout).request('/agent/chat', {'protocol': PROTOCOL, 'messages': messages, 'allow_tools': allow_tools})


def run_agent(gateway, text, history, execute, identity, timeout=110):
    """Each successful final answer is model text, never a template fallback."""
    started, deadline = time.monotonic(), time.monotonic() + timeout
    messages = list(history) + [{'role': 'user', 'content': text}]
    fresh = [messages[-1]]
    trace = {'turn_id': str(uuid.uuid4()), 'protocol': PROTOCOL, 'model': identity['name'],
             'provider': identity.get('provider', 'custom'),
             'model_digest': identity.get('digest'), 'ollama_version': identity.get('ollama_version'),
             'reported_cost_usd': 0.0 if identity.get('provider') == 'openrouter' else None,
             'model_calls': 0, 'prompt_tokens': 0, 'generated_tokens': 0, 'tools': [], 'steps': []}
    tool_count = 0
    for step in range(MAX_MODEL_CALLS):
        if time.monotonic() >= deadline:
            raise AgentError('agent_timeout', 'Model đã vượt thời gian xử lý. Đơn hàng chưa bị thay đổi bởi chat.', trace)
        allow_tools = step < MAX_MODEL_CALLS - 1 and tool_count < MAX_TOOL_CALLS
        try:
            validate_messages(messages)
            trace['model_calls'] += 1
            response = gateway.chat(messages, allow_tools, max(1, min(30, int(deadline-time.monotonic()))))
            trace['prompt_tokens'] += response.get('prompt_eval_count') or 0
            trace['generated_tokens'] += response.get('eval_count') or 0
            if trace['reported_cost_usd'] is not None:
                cost = response.get('reported_cost_usd')
                trace['reported_cost_usd'] = round(trace['reported_cost_usd'] + cost, 8) if cost is not None else None
            trace['steps'].append({k: response.get(k) for k in ('load_duration', 'prompt_eval_duration', 'eval_duration')})
            message = assistant_message(response)
        except AgentError as exc:
            trace['reported_cost_usd'] = None  # A failed request may still have been billed.
            raise AgentError(exc.code, str(exc), trace) from None
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
            trace['reported_cost_usd'] = None
            # Never echo upstream bodies, URLs or tokens.
            raise AgentError('agent_response_failed', 'Không nhận được câu trả lời hợp lệ từ model. Chat chưa thực hiện thay đổi đơn.', trace) from None
        messages.append(message); fresh.append(message)
        calls = message.get('tool_calls', [])
        if not calls:
            trace['latency_ms'] = round((time.monotonic()-started)*1000, 2)
            return {'message': message['content'], 'messages': fresh, 'trace': trace}
        if not allow_tools or tool_count + len(calls) > MAX_TOOL_CALLS:
            raise AgentError('agent_budget_exceeded', 'Model chưa hoàn tất trong giới hạn số bước. Bạn rút gọn yêu cầu hoặc dùng nút thao tác nhé.', trace)
        for call in calls:
            function = call['function']; name, arguments = function['name'], function['arguments']
            tool_count += 1
            try:
                validate_tool(name, arguments)
            except ProtocolError:
                result = {'error': 'tool_not_allowed', 'message': 'Tool or arguments are not allowed. No action was performed.'}
            else:
                result = execute(name, arguments)
            if not isinstance(result, dict):
                raise AgentError('tool_response_failed', 'Công cụ trả dữ liệu không hợp lệ.', trace)
            trace['tools'].append({'name': name,
                                   'status': 'error' if result.get('error') else 'ok'})
            entry = {'role': 'tool', 'tool_name': name, 'content': json.dumps(result, ensure_ascii=False, separators=(',', ':'))}
            messages.append(entry); fresh.append(entry)
    raise AgentError('agent_budget_exceeded', 'Model chưa hoàn tất trong giới hạn số bước.', trace)
