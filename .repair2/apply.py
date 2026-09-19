from pathlib import Path

def change(path, before, after):
    p = Path(path)
    text = p.read_text(encoding='utf-8')
    if text.count(before) != 1:
        raise RuntimeError('Unexpected source: ' + path)
    p.write_text(text.replace(before, after), encoding='utf-8')

change('agent_protocol.py', 'def build_request(model, messages, allow_tools=True):', '''def scoped_tools(allowed_tools=None):
    """Return a validated subset of server-owned schemas; never add client schemas."""
    if allowed_tools is None:
        return TOOLS
    if not isinstance(allowed_tools, (list, tuple, frozenset)):
        raise ProtocolError('Invalid tool scope')
    if len(allowed_tools) > len(TOOLS) or any(not isinstance(n, str) for n in allowed_tools):
        raise ProtocolError('Invalid tool scope')
    names = set(allowed_tools)
    if len(names) != len(allowed_tools) or not names.issubset(TOOL_ARGUMENTS):
        raise ProtocolError('Invalid tool scope')
    return [tool for tool in TOOLS if tool['function']['name'] in names]


def build_request(model, messages, allow_tools=True, *, allowed_tools=None):''')
change('agent_protocol.py', "    tools = [] if mode == 'general' else (TOOLS if allow_tools else [])", "    available = scoped_tools(allowed_tools)\n    tools = [] if mode == 'general' else (available if allow_tools else [])")
change('agent_protocol.py', "    if not isinstance(body, dict) or set(body) != {'protocol', 'messages', 'allow_tools'} or body['protocol'] != PROTOCOL:", "    required = {'protocol', 'messages', 'allow_tools'}\n    if (not isinstance(body, dict) or not required.issubset(body)\n            or set(body) - required - {'allowed_tools'} or body['protocol'] != PROTOCOL):")
change('agent_protocol.py', "    return validate_messages(body['messages']), body['allow_tools']", "    if 'allowed_tools' in body:\n        if not isinstance(body['allowed_tools'], list):\n            raise ProtocolError('Invalid tool scope')\n        scoped_tools(body['allowed_tools'])\n    return validate_messages(body['messages']), body['allow_tools']")
change('retailops_providers.py', 'request_mode, validate_messages', 'request_mode, validate_messages, scoped_tools')
change('retailops_providers.py', '    def _chat_anthropic(self, messages, allow_tools, timeout):', '    def _chat_anthropic(self, messages, allow_tools, timeout, *, allowed_tools=None):')
change('retailops_providers.py', '            for t in TOOLS:', '            for t in scoped_tools(allowed_tools):')
change('retailops_providers.py', '    def chat(self, messages, allow_tools, timeout):\n        if self.is_anthropic:\n            return self._chat_anthropic(messages, allow_tools, timeout)', '    def chat_scoped(self, messages, allow_tools, timeout, allowed_tools):\n        return self.chat(messages, allow_tools, timeout, allowed_tools=allowed_tools)\n\n    def chat(self, messages, allow_tools, timeout, *, allowed_tools=None):\n        available = scoped_tools(allowed_tools)\n        if self.is_anthropic:\n            return self._chat_anthropic(messages, allow_tools, timeout, allowed_tools=allowed_tools)')
change('retailops_providers.py', "        tools = [] if mode == 'general' else TOOLS", "        tools = [] if mode == 'general' else available")
change('retailops_agent.py', 'from agent_protocol import PROTOCOL, build_request', 'from agent_protocol import PROTOCOL, build_request, scoped_tools')
change('retailops_agent.py', "        return gateway.request('/api/chat', build_request(self.config.model, messages, allow_tools))", "        return gateway.request('/api/chat', build_request(self.config.model, messages, allow_tools))\n\n    def chat_scoped(self, messages, allow_tools, timeout, allowed_tools):\n        gateway = LocalOllama(replace(self.config, timeout_s=timeout))\n        return gateway.request('/api/chat', build_request(self.config.model, messages, allow_tools,\n                                                          allowed_tools=allowed_tools))")
change('retailops_agent.py', "        return self.gateway(timeout).request('/agent/chat', {'protocol': PROTOCOL, 'messages': messages, 'allow_tools': allow_tools})", "        return self.gateway(timeout).request('/agent/chat', {'protocol': PROTOCOL, 'messages': messages, 'allow_tools': allow_tools})\n\n    def chat_scoped(self, messages, allow_tools, timeout, allowed_tools):\n        names = [t['function']['name'] for t in scoped_tools(allowed_tools)]\n        return self.gateway(timeout).request('/agent/chat', {'protocol': PROTOCOL, 'messages': messages,\n                                                            'allow_tools': allow_tools, 'allowed_tools': names})")
change('inference_proxy.py', '                    messages, allow_tools = validate_envelope(json.loads(raw))', '                    body = json.loads(raw)\n                    messages, allow_tools = validate_envelope(body)')
change('inference_proxy.py', "self.reply(200, worker.request('/api/chat', build_request(config.model, messages, allow_tools)))", "self.reply(200, worker.request('/api/chat', build_request(config.model, messages, allow_tools,\n                                                                          allowed_tools=body.get('allowed_tools'))))")
change('retailops/business/application.py', 'import threading\n', 'import threading\nimport time\n')
change('retailops/business/application.py', '    def chat(self, customer, body):\n', '    def chat(self, customer, body):\n        started = time.monotonic()\n')
change('retailops/business/application.py', '        except AgentError as exc:\n            self.store.event', "        except AgentError as exc:\n            exc.trace['latency_ms'] = round((time.monotonic() - started) * 1000, 2)\n            self.store.event")
change('retailops/business/application.py', "                            bound.context['order_id'] = order_obj['id']", "                            bound.context = {'order_id': order_obj['id'], 'product_id': order_obj.get('product_id')}")
change('retailops/business/application.py', "                    elif name == 'search_knowledge' and isinstance(cached_res, dict) and 'results' in cached_res:", "                    elif name == 'get_product' and isinstance(cached_res, dict) and isinstance(cached_res.get('product'), dict):\n                        pid = cached_res['product'].get('id')\n                        if bound.context['product_id'] != pid:\n                            bound.context['order_id'] = None\n                        bound.context['product_id'] = pid\n                    elif name == 'search_knowledge' and isinstance(cached_res, dict) and 'results' in cached_res:")
change('retailops_providers.py', "tool_choice = 'none' if mode == 'general' or not allow_tools else 'auto'", "tool_choice = 'none' if not tools or not allow_tools else 'auto'")
p = Path('web/app.js')
s = p.read_text(encoding='utf-8')
a = s.index('function showShipment(')
b = s.index('\nfunction showHumanSupport', a)
s = s[:a] + Path('.repair2/shipment.js').read_text() + s[b:]
a = s.index('  const names = (trace.tools')
b = s.index("  details.append(el('p'", a)
s = s[:a] + Path('.repair2/tool-errors.js').read_text() + s[b:]
s = s.replace('trace.latency_ms !== undefined ?', "typeof trace.latency_ms === 'number' && Number.isFinite(trace.latency_ms) && trace.latency_ms >= 0 ?")
p.write_text(s, encoding='utf-8')
change('.github/workflows/ci.yml', '          node tests/test_knowledge_sources.js\n', '          node tests/test_knowledge_sources.js\n          node tests/test_shipment_ui.js\n')
