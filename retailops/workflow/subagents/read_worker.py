"""Bounded read-only worker runtime; no business write or provider fallback.

Expected lookup failures are business results. Transport/protocol failures are
errors unless an explicit renderer can safely present already-retrieved data.
"""
import copy
import math
import time
import json

from agent_protocol import (MAX_MODEL_CALLS, MAX_TOOL_CALLS, ProtocolError,
                            assistant_message, validate_messages, validate_tool)
from retailops.core import ApiError

# These indicate unavailable infrastructure, NOT an empty database/search result.
UNAVAILABLE = frozenset(('database_unavailable', 'knowledge_unavailable',
                         'knowledge_not_ready', 'tool_unavailable'))


def worker_messages(state, prompt):
    """Keep complete history and attachments; caller owns the worker instruction."""
    history = copy.deepcopy(state['messages'])
    if history and history[0].get('role') == 'system':
        history = history[1:]
    messages = [{'role': 'system', 'content': prompt}, *history]
    validate_messages(messages)
    return messages


def call_model(gateway, messages, allow_tools, deadline, trace, *, allowed_tools=None):
    from retailops_agent import AgentError
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AgentError('agent_timeout', 'Model v\u01b0\u1ee3t th\u1eddi gian x\u1eed l\u00fd.', trace)
    validate_messages(messages)
    # Count attempts before transport/normalization, not only successful returns.
    trace['model_calls'] = trace.get('model_calls', 0) + 1
    trace.setdefault('model_responses', 0)
    try:
        seconds = max(1, min(30, math.ceil(remaining)))
        scoped = getattr(gateway, 'chat_scoped', None)
        if allowed_tools is not None and callable(scoped):
            response = scoped(messages, allow_tools, seconds, allowed_tools)
        else:
            # Legacy/test gateways still face the execution-time allowlist below.
            response = gateway.chat(messages, allow_tools, seconds)
        message = assistant_message(response)
    except (AgentError, RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
        code = exc.code if isinstance(exc, AgentError) else 'agent_response_failed'
        trace['reported_cost_usd'] = None
        trace['usage_incomplete'] = True
        trace.setdefault('model_errors', []).append({'code': code, 'call': trace['model_calls']})
        raise AgentError(code, 'Kh\u00f4ng nh\u1eadn \u0111\u01b0\u1ee3c ph\u1ea3n h\u1ed3i h\u1ee3p l\u1ec7 t\u1eeb model. Vui l\u00f2ng th\u1eed l\u1ea1i.', trace) from None
    trace['model_responses'] += 1
    trace['prompt_tokens'] = trace.get('prompt_tokens', 0) + (response.get('prompt_eval_count') or 0)
    trace['generated_tokens'] = trace.get('generated_tokens', 0) + (response.get('eval_count') or 0)
    cost = response.get('reported_cost_usd')
    if trace.get('reported_cost_usd') is not None and cost is not None:
        trace['reported_cost_usd'] = round(trace['reported_cost_usd'] + cost, 8)
    else:
        trace['reported_cost_usd'] = None
    return message


def run_read_worker(state, execute, gateway, *, prompt, allowed_tools, render,
                    worker, timeout=30):
    from retailops_agent import AgentError

    state = copy.deepcopy(state)
    state['consecutive_ood_count'] = 0
    trace = state.setdefault('trace', {})
    trace['answer_source'] = 'llm_agent'
    messages = worker_messages(state, prompt)
    deadline = time.monotonic() + timeout
    records = []
    final = None
    for step in range(MAX_MODEL_CALLS):
        allow = step < MAX_MODEL_CALLS - 1 and state['tool_count'] < MAX_TOOL_CALLS
        try:
            message = call_model(gateway, messages, allow, deadline, trace, allowed_tools=allowed_tools)
        except AgentError as exc:
            final = render(records) if records else None
            if not final:
                raise
            trace.update(answer_source='tool_result', degraded=True, fallback_reason=exc.code)
            break
        calls = message.get('tool_calls', [])
        if not calls:
            final = message['content']
            break
        if not allow or state['tool_count'] + len(calls) > MAX_TOOL_CALLS:
            raise AgentError('agent_budget_exceeded', 'Model v\u01b0\u1ee3t gi\u1edbi h\u1ea1n g\u1ecdi c\u00f4ng c\u1ee5.', trace)
        # Append the assistant ONCE per batch, then exactly one result per call.
        messages.append(message)
        state['fresh'].append(copy.deepcopy(message))
        state['messages'].append(copy.deepcopy(message))
        business_error = False
        for call in calls:
            name = call['function']['name']
            args = call['function']['arguments']
            state['tool_count'] += 1
            invalid = None
            if name not in allowed_tools:
                invalid = 'tool_not_allowed'
            else:
                try:
                    validate_tool(name, args)
                except ProtocolError:
                    invalid = 'invalid_tool_arguments'
            if invalid:
                result = {'error': invalid}
            else:
                try:
                    result = execute(name, args)
                except ApiError as exc:
                    result = {'error': exc.code if exc.status < 500 else 'tool_unavailable'}
                except (RuntimeError, ValueError, OSError, KeyError, TypeError):
                    result = {'error': 'tool_unavailable'}
            if not isinstance(result, dict):
                result = {'error': 'tool_unavailable'}
            code = result.get('error')
            trace.setdefault('tools', []).append({'name': name,
                'status': 'error' if code else 'ok', **({'error_code': code} if code else {})})
            if code in UNAVAILABLE:
                trace['outcome'] = 'tool_unavailable'
                raise AgentError('tool_unavailable', 'Ngu\u1ed3n d\u1eef li\u1ec7u ch\u01b0a s\u1eb5n s\u00e0ng. Ch\u01b0a th\u1ec3 x\u00e1c minh k\u1ebft qu\u1ea3.', trace)
            entry = {'role': 'tool', 'tool_name': name,
                     'content': json.dumps(result, ensure_ascii=False, separators=(',', ':'))}
            messages.append(entry)
            state['fresh'].append(copy.deepcopy(entry))
            state['messages'].append(copy.deepcopy(entry))
            records.append({'name': name, 'args': args, 'result': result})
            business_error = business_error or bool(code)
        if business_error:
            # The LLM cannot overrule an ownership denial or invent a missing order.
            final = render(records)
            if not final:
                raise AgentError('tool_response_failed', 'Ch\u01b0a th\u1ec3 x\u00e1c minh k\u1ebft qu\u1ea3 tra c\u1ee9u.', trace)
            codes = sorted({r['result']['error'] for r in records if r['result'].get('error')})
            hard_denial = any(code in ('order_not_found', 'permission_denied', 'forbidden') for code in codes)
            partial = any(not r['result'].get('error') for r in records) and not hard_denial
            trace.update(answer_source='tool_result', outcome='partial' if partial else 'business_error')
            if partial:
                trace.update(degraded=True, warning_codes=codes)
            break
    if not final:
        raise AgentError('agent_response_failed', 'Model ch\u01b0a tr\u1ea3 l\u1eddi h\u1ee3p l\u1ec7.', trace)
    if not isinstance(final, str) or len(final) > 7500:
        raise AgentError('tool_response_failed', 'Response exceeds the safe output budget.', trace)
    # Never expose hidden reasoning as a substitute for a missing final response.
    answer = {'role': 'assistant', 'content': final}
    state['messages'].append(answer)
    state['fresh'].append(copy.deepcopy(answer))
    state['complete'] = True
    state['subagent_history'].append(worker + ':done')
    return state
