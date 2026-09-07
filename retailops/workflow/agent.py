"""Explicit bounded model -> tools -> model graph. Tools remain read-only."""
import copy
import json
import time
import uuid
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from agent_protocol import (MAX_MODEL_CALLS, MAX_TOOL_CALLS, PROTOCOL, ProtocolError,
                            assistant_message, request_mode, sanitize_general_answer,
                            validate_messages, validate_tool)
from retailops_agent import AgentError
from retailops.knowledge.citations import CitationError, cited_sources


class AgentState(TypedDict):
    messages: list
    fresh: list
    trace: dict
    tool_count: int
    bound: dict
    complete: bool


def run(gateway, text, history, execute, identity, timeout=110, *, saver=None,
        capture=lambda: {}, restore=lambda state: None, before_model=lambda: None):
    started, deadline = time.monotonic(), time.monotonic()+timeout

    def model(state):
        state = copy.deepcopy(state)
        trace = state['trace']
        mode = request_mode(state['messages'])
        trace['request_mode'] = mode
        if time.monotonic() >= deadline:
            raise AgentError('agent_timeout', 'Model đã vượt thời gian xử lý. Chat chưa thay đổi đơn.', trace)
        if trace['model_calls'] >= MAX_MODEL_CALLS:
            raise AgentError('agent_budget_exceeded', 'Model chưa hoàn tất trong giới hạn số bước.', trace)
        allow = trace['model_calls'] < MAX_MODEL_CALLS-1 and state['tool_count'] < MAX_TOOL_CALLS
        # A retry is an explicit request and reserves another daily API attempt.
        # Never automatically retry potentially billable network calls inside a node.
        before_model()
        try:
            validate_messages(state['messages'])
            trace['model_calls'] += 1
            response = gateway.chat(state['messages'], allow, max(1, min(30, int(deadline-time.monotonic()))))
            trace['prompt_tokens'] += response.get('prompt_eval_count') or 0
            trace['generated_tokens'] += response.get('eval_count') or 0
            if trace['reported_cost_usd'] is not None:
                cost = response.get('reported_cost_usd')
                trace['reported_cost_usd'] = round(trace['reported_cost_usd']+cost, 8) if cost is not None else None
            trace['steps'].append({k: response.get(k) for k in ('load_duration', 'prompt_eval_duration', 'eval_duration')})
            message = assistant_message(response)
        except AgentError as exc:
            trace['reported_cost_usd'] = None
            raise AgentError(exc.code, str(exc), trace) from None
        except (RuntimeError, ValueError, OSError, KeyError, TypeError):
            trace['reported_cost_usd'] = None
            raise AgentError('agent_response_failed', 'Không nhận được câu trả lời hợp lệ từ model. Chat chưa thực hiện thay đổi đơn.', trace) from None

        calls = message.get('tool_calls', [])
        if mode == 'general':
            if calls:
                raise AgentError('agent_response_failed', 'Model general-mode đã trả tool call không hợp lệ. Hãy thử lại tin nhắn.', trace)
            message['content'], removed = sanitize_general_answer(message['content'])
            trace['general_citations_removed'] = trace.get('general_citations_removed', 0) + removed
            if not message['content']:
                raise AgentError('agent_response_failed', 'Model chưa trả câu trả lời general-mode hợp lệ.', trace)

        if calls and (not allow or state['tool_count']+len(calls) > MAX_TOOL_CALLS):
            raise AgentError('agent_budget_exceeded', 'Model chưa hoàn tất trong giới hạn số bước.', trace)
        if not calls and mode != 'general':
            try:
                cited_sources(message['content'], state['bound'].get('knowledge', {}).get('sources', []))
            except CitationError as exc:
                # Fail before checkpointing a final answer so an explicit retry
                # can regenerate it using the already-checkpointed tool evidence.
                raise AgentError(exc.code, 'Model chưa trích dẫn nguồn hợp lệ. Bạn có thể thử lại tin nhắn này.', trace) from None
        state['messages'].append(message)
        state['fresh'].append(message)
        state['complete'] = not calls
        trace['latency_ms'] = round((time.monotonic()-started)*1000, 2)
        trace['orchestrator'] = 'langgraph'
        return state

    def tools(state):
        state = copy.deepcopy(state)
        restore(state['bound'])
        for call in state['messages'][-1]['tool_calls']:
            name, args = call['function']['name'], call['function']['arguments']
            state['tool_count'] += 1
            try:
                validate_tool(name, args)
            except ProtocolError:
                result = {'error': 'tool_not_allowed', 'message': 'Tool or arguments are not allowed. No action was performed.'}
            else:
                result = execute(name, args)
            if not isinstance(result, dict):
                raise AgentError('tool_response_failed', 'Công cụ trả dữ liệu không hợp lệ.', state['trace'])
            state['trace']['tools'].append({'name': name, 'status': 'error' if result.get('error') else 'ok'})
            entry = {'role': 'tool', 'tool_name': name, 'content': json.dumps(result, ensure_ascii=False, separators=(',', ':'))}
            state['messages'].append(entry)
            state['fresh'].append(entry)
        state['bound'] = capture()
        return state

    builder = StateGraph(AgentState)
    builder.add_node('model', model)
    builder.add_node('tools', tools)
    builder.add_edge(START, 'model')
    builder.add_conditional_edges('model', lambda s: END if s['complete'] else 'tools')
    builder.add_edge('tools', 'model')
    graph = builder.compile(checkpointer=saver)
    config = saver.config() if saver else {'recursion_limit': 32, 'callbacks': []}
    checkpoint = graph.get_state(config) if saver else None
    if checkpoint and checkpoint.values:
        trace = checkpoint.values['trace']
        if trace.get('protocol') != PROTOCOL:
            raise AgentError('agent_protocol_changed', 'Phiên bản agent đã thay đổi. Hãy mở cuộc trò chuyện mới.')
        if (trace['model'], trace['model_digest']) != (identity['name'], identity.get('digest')):
            raise AgentError('model_changed', 'Model đã thay đổi giữa lượt xử lý. Hãy mở cuộc trò chuyện mới.')
        state = graph.invoke(None, config, durability='sync') if checkpoint.next else checkpoint.values
    else:
        user = {'role': 'user', 'content': text}
        initial = {'messages': list(history)+[user], 'fresh': [user], 'tool_count': 0,
                   'bound': capture(), 'complete': False,
                   'trace': {'turn_id': str(uuid.uuid4()), 'protocol': PROTOCOL, 'model': identity['name'],
                             'provider': identity.get('provider', 'custom'), 'model_digest': identity.get('digest'),
                             'ollama_version': identity.get('ollama_version'),
                             'reported_cost_usd': 0.0 if identity.get('provider') == 'openrouter' else None,
                             'model_calls': 0, 'prompt_tokens': 0, 'generated_tokens': 0,
                             'tools': [], 'steps': [], 'general_citations_removed': 0}}
        state = graph.invoke(initial, config, **({'durability': 'sync'} if saver else {}))
    state = copy.deepcopy(state)
    state['trace']['resumed_from_checkpoint'] = bool(checkpoint and checkpoint.values)
    state['trace']['metrics_scope'] = 'checkpointed_path; failed attempts are logged separately'
    restore(state['bound'])
    return {'message': state['fresh'][-1]['content'], 'messages': state['fresh'], 'trace': state['trace']}
