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


def run_agent(gateway, text, history, execute, identity, timeout=110, **options):
    """Compatibility entrypoint for EC2 and the Colab smoke runner."""
    from retailops.workflow.agent import run
    return run(gateway, text, history, execute, identity, timeout, **options)
