"""The customer agent: one bounded model -> tools -> model loop (W3.2-D9).

The model plans and calls tools. Code keeps only what must not depend on a model: the three safety rails
(retailops.workflow.safety), the budgets, the server-side validation of every tool call, a size limit on what
goes back to the model, and a check of the final answer. Tools never change business data, so a failed or
stopped turn changes nothing. There is no routing by keyword and no prepared answer for a situation.
"""
import copy
import json
import time
import uuid
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agent_protocol import (MAX_CHARACTERS, MAX_MODEL_CALLS, MAX_TOOL_CALLS, PROTOCOL, TURN_TIMEOUT_SECONDS,
                            ProtocolError, agent_system, assistant_message, model_history, request_mode, sanitize_general_answer,
                            validate_messages, validate_tool)
from retailops_agent import AgentError
from retailops.business.progress import CANCELLED_MESSAGE
from retailops.knowledge.citations import CitationError, cited_sources
from retailops.model_errors import record_model_error
from retailops.workflow.compaction import compact_tool_result, fit_history, fit_transcript, result_limit
from retailops.workflow.safety import safety_gate
from retailops.workflow.subagents.read_worker import summarize_tool_result

MODEL_CALL_TIMEOUT = 45  # seconds for one model call; the deadline of the whole turn still applies
UNAVAILABLE_CODES = ('database_unavailable', 'tool_unavailable', 'order_access_denied')


class AgentState(TypedDict):
    messages: list
    fresh: list
    trace: dict
    tool_count: int
    tool_chars: int
    seen_calls: list
    bound: dict
    complete: bool


def _call_key(name, args):
    return name + json.dumps(args, sort_keys=True, ensure_ascii=False)


def run(gateway, text, history, execute, identity, timeout=TURN_TIMEOUT_SECONDS, *, saver=None,
        capture=lambda: {}, restore=lambda state: None, before_model=lambda: None, attachment=None,
        progress=None, profile=None, is_cancelled=None):
    started = time.monotonic()
    deadline = started + timeout
    tool_validator = profile.validate_tool if profile is not None else validate_tool
    extra_tool_names = profile.tool_names if profile is not None else ()
    initial_bound_snapshot = copy.deepcopy(capture())

    def check_cancelled():
        if is_cancelled is None:
            return False
        try:
            return bool(is_cancelled())
        except Exception:
            return False

    def publish(trace, phase):
        """Tell the web layer how far this turn has got; a broken observer never breaks a turn."""
        if progress is None:
            return
        try:
            progress({'phase': phase, 'model_calls': trace['model_calls'],
                      'tools': [{'name': t['name'], 'status': t['status']} for t in trace['tools']]})
        except Exception:
            pass

    def finish_cancelled(state, trace, stopped_at):
        reply = {'role': 'assistant', 'content': CANCELLED_MESSAGE}
        user_msg = state['fresh'][0] if state.get('fresh') else {'role': 'user', 'content': text}
        prior_len = max(0, len(state['messages']) - len(state['fresh']))
        state['messages'] = state['messages'][:prior_len] + [user_msg, reply]
        state['fresh'] = [user_msg, reply]
        state['bound'] = copy.deepcopy(initial_bound_snapshot)
        restore(state['bound'])
        state['complete'] = True
        trace['cancelled'] = True
        trace['stopped_at'] = stopped_at
        trace['answer_source'] = 'user_cancelled'
        trace['steps'].append({
            'step': trace['model_calls'],
            'worker': 'agent',
            'action': 'cancelled',
            'stopped_at': stopped_at,
            'summary': f'Người dùng dừng câu trả lời tại {stopped_at}.',
        })
        trace['latency_ms'] = round((time.monotonic() - started) * 1000, 2)
        trace['orchestrator'] = 'langgraph'
        publish(trace, 'cancelled')
        return state

    def guard(state):
        state = copy.deepcopy(state)
        if check_cancelled():
            return finish_cancelled(state, state['trace'], 'before_model')
        if profile is not None and profile.skip_safety_gate:
            return state
        verdict = safety_gate(state['messages'][-1]['content'])
        if verdict is None:
            return state
        trace = state['trace']
        trace.update(safety_rail=verdict.rail, answer_source='safety_rail', strict_mode=verdict.strict_mode)
        if verdict.human_reason:
            restore(state['bound'])
            result = execute('request_human_support', {'reason': verdict.human_reason})
            state['tool_count'] += 1
            trace['tools'].append({'name': 'request_human_support',
                                   'status': 'error' if isinstance(result, dict) and result.get('error') else 'ok'})
            state['bound'] = capture()
        reply = {'role': 'assistant', 'content': verdict.reply}
        state['messages'].append(reply)
        state['fresh'].append(reply)
        state['complete'] = True
        trace['steps'].append({'step': 0, 'worker': 'safety_rail', 'action': 'final_answer',
                               'summary': f'Rào an toàn: {verdict.rail}.'})
        trace['latency_ms'] = round((time.monotonic() - started) * 1000, 2)
        trace['orchestrator'] = 'langgraph'
        return state

    def model(state):
        state = copy.deepcopy(state)
        trace = state['trace']
        if profile is not None and profile.force_retail_mode:
            mode = profile.name
        else:
            mode = request_mode(state['messages'])
        trace['request_mode'] = mode
        if check_cancelled():
            return finish_cancelled(state, trace, 'before_model')
        if time.monotonic() >= deadline:
            raise AgentError('agent_timeout', 'Model đã vượt thời gian xử lý. Chat chưa thay đổi đơn.', trace)
        if trace['model_calls'] >= MAX_MODEL_CALLS:
            raise AgentError('agent_budget_exceeded', 'Model chưa hoàn tất trong giới hạn số bước.', trace)
        # The last allowed model call gets no tools, so it has to answer with what it already has.
        allow = trace['model_calls'] < MAX_MODEL_CALLS - 1 and state['tool_count'] < MAX_TOOL_CALLS
        # A retry is an explicit request and reserves another daily API attempt.
        # Never automatically retry potentially billable network calls inside a node.
        before_model()
        publish(trace, 'model')
        outgoing = state['messages']
        if mode == 'general' and outgoing[0].get('role') == 'system':
            outgoing = outgoing[1:]  # the tool-free general mode brings its own system text
        outgoing = fit_transcript(outgoing, MAX_CHARACTERS - 200)
        try:
            validate_messages(outgoing)
            trace['model_calls'] += 1
            call_timeout = max(1, min(MODEL_CALL_TIMEOUT, int(deadline - time.monotonic())))
            chat_profile = getattr(gateway, 'chat_profile', None) if profile is not None else None
            if profile is not None and callable(chat_profile):
                sys_text = outgoing[0]['content'] if outgoing and outgoing[0].get('role') == 'system' else profile.system_prompt_fn(state['bound'])
                response = chat_profile(outgoing, allow, call_timeout, system_prompt=sys_text, tool_schemas=profile.tool_schemas)
            else:
                response = gateway.chat(outgoing, allow, call_timeout)
            trace['prompt_tokens'] += response.get('prompt_eval_count') or 0
            trace['generated_tokens'] += response.get('eval_count') or 0
            if trace['reported_cost_usd'] is not None:
                cost = response.get('reported_cost_usd')
                trace['reported_cost_usd'] = round(trace['reported_cost_usd'] + cost, 8) if cost is not None else None
            if check_cancelled():
                return finish_cancelled(state, trace, 'after_model')
            thought = response.get('reasoning')
            if thought:
                thought = str(thought)
                trace['reasoning'] = f"{trace['reasoning']}\n---\n{thought}" if trace.get('reasoning') else thought
            message = assistant_message(response, extra_tool_names=extra_tool_names)
        except AgentError as exc:
            trace['reported_cost_usd'] = None
            entry = record_model_error(trace, exc, code=exc.code)
            failure = AgentError(exc.code, str(exc), trace)
            failure.http_status = getattr(exc, 'http_status', None) or entry.get('http_status')
            raise failure from None
        except TimeoutError as exc:
            trace['reported_cost_usd'] = None
            record_model_error(trace, exc, code='agent_timeout')
            raise AgentError('agent_timeout', 'Model đã vượt thời gian xử lý. Chat chưa thay đổi đơn.', trace) from None
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
            trace['reported_cost_usd'] = None
            record_model_error(trace, exc, code='agent_response_failed')
            raise AgentError('agent_response_failed', 'Không nhận được câu trả lời hợp lệ từ model. Chat chưa thực hiện thay đổi đơn.', trace) from None

        calls = message.get('tool_calls', [])
        if mode == 'general':
            if calls:
                raise AgentError('agent_response_failed', 'Model general-mode đã trả tool call không hợp lệ. Hãy thử lại tin nhắn.', trace)
            message['content'], removed = sanitize_general_answer(message['content'])
            trace['general_citations_removed'] = trace.get('general_citations_removed', 0) + removed
            if not message['content']:
                raise AgentError('agent_response_failed', 'Model chưa trả câu trả lời general-mode hợp lệ.', trace)

        if calls and (not allow or state['tool_count'] + len(calls) > MAX_TOOL_CALLS):
            raise AgentError('agent_budget_exceeded', 'Model chưa hoàn tất trong giới hạn số bước.', trace)
        if not calls and mode != 'general':
            try:
                cited_sources(message['content'], state['bound'].get('knowledge', {}).get('sources', []))
            except CitationError as exc:
                # Fail before checkpointing a final answer so an explicit retry
                # can regenerate it using the already-checkpointed tool evidence.
                raise AgentError(exc.code, 'Model chưa trích dẫn nguồn hợp lệ. Bạn có thể thử lại tin nhắn này.', trace) from None
        step = {'step': trace['model_calls'], 'worker': 'agent', 'thought': thought or None,
                'action': 'tool_call' if calls else 'final_answer'}
        step.update({k: response[k] for k in ('load_duration', 'prompt_eval_duration', 'eval_duration')
                     if response.get(k) is not None})
        if not calls:
            step['summary'] = 'Tổng hợp dữ kiện và hoàn tất câu trả lời.'
        trace['steps'].append(step)
        state['messages'].append(message)
        state['fresh'].append(message)
        state['complete'] = not calls
        trace['latency_ms'] = round((time.monotonic() - started) * 1000, 2)
        trace['orchestrator'] = 'langgraph'
        if not calls:
            publish(trace, 'done')
        return state

    def tools(state):
        state = copy.deepcopy(state)
        restore(state['bound'])
        trace = state['trace']
        state.setdefault('seen_calls', [])  # a checkpoint written before these fields existed can still resume
        state.setdefault('tool_chars', 0)
        step = trace['steps'][-1]
        step['tools'] = []
        for call in state['messages'][-1]['tool_calls']:
            name, args = call['function']['name'], call['function']['arguments']
            if check_cancelled():
                step['evaluation'] = f'Đã dừng trước khi thực thi công cụ {name}.'
                return finish_cancelled(state, trace, f'before_tool:{name}')
            state['tool_count'] += 1
            key = _call_key(name, args)
            try:
                tool_validator(name, args)
            except ProtocolError:
                result = {'error': 'tool_not_allowed', 'message': 'Tool or arguments are not allowed. No action was performed.'}
            else:
                if key in state['seen_calls']:
                    result = {'error': 'duplicate_call',
                              'message': 'This exact call was already made in this turn; its result is above. Use it or answer.'}
                else:
                    state['seen_calls'].append(key)
                    try:
                        result = execute(name, args)
                    except (RuntimeError, ValueError, OSError, KeyError, TypeError):
                        result = {'error': 'tool_unavailable'}
            if not isinstance(result, dict):
                raise AgentError('tool_response_failed', 'Công cụ trả dữ liệu không hợp lệ.', trace)
            code = result.get('error')
            if code in UNAVAILABLE_CODES:
                raise AgentError('tool_unavailable', 'Nguồn dữ liệu chưa sẵn sàng. Chưa thể xác minh kết quả.', trace)
            entry = {'name': name, 'status': 'error' if code else 'ok'}
            if code:
                entry['error_code'] = code
            trace['tools'].append(entry)
            step['tools'].append({**entry, 'args': args, 'summary': summarize_tool_result(name, args, result)})
            content = compact_tool_result(result, result_limit(state['tool_chars']))
            state['tool_chars'] += len(content)
            message = {'role': 'tool', 'tool_name': name, 'content': content}
            state['messages'].append(message)
            state['fresh'].append(message)
            publish(trace, 'tool')
        failed = any(t['status'] == 'error' for t in step['tools'])
        step['backtrack'] = failed
        step['evaluation'] = ('Một công cụ báo lỗi hoặc từ chối; agent cân nhắc lại kế hoạch với dữ kiện đã có.' if failed else
                              'Đã thu thập dữ kiện từ ' + ', '.join(t['name'] for t in step['tools']) + '; chuyển sang bước tiếp theo.')
        state['bound'] = capture()
        return state

    builder = StateGraph(AgentState)
    builder.add_node('guard', guard)
    builder.add_node('model', model)
    builder.add_node('tools', tools)
    builder.add_edge(START, 'guard')
    builder.add_conditional_edges('guard', lambda s: END if s['complete'] else 'model')
    builder.add_conditional_edges('model', lambda s: END if s['complete'] else 'tools')
    builder.add_conditional_edges('tools', lambda s: END if s['complete'] else 'model')
    graph = builder.compile(checkpointer=saver)
    config = saver.config() if saver else {'recursion_limit': 32, 'callbacks': []}
    checkpoint = graph.get_state(config) if saver else None
    if checkpoint and checkpoint.values:
        trace = checkpoint.values['trace']
        if trace.get('protocol') != PROTOCOL:
            raise AgentError('agent_protocol_changed', 'Phiên bản agent đã thay đổi. Hãy mở cuộc trò chuyện mới.')
        if (trace['model'], trace['model_digest']) != (identity.get('name', 'slm'), identity.get('digest')):
            raise AgentError('model_changed', 'Model đã thay đổi giữa lượt xử lý. Hãy mở cuộc trò chuyện mới.')
        state = graph.invoke(None, config, durability='sync') if checkpoint.next else checkpoint.values
    else:
        user = {'role': 'user', 'content': text}
        if attachment:
            user['attachment'] = attachment
        bound = capture()
        # The loop owns the system turn: the rules plus what the server knows about the conversation focus.
        sys_prompt = profile.system_prompt_fn(bound) if profile is not None else agent_system(bound.get('context'))
        messages = [{'role': 'system', 'content': sys_prompt},
                    *fit_history(model_history(list(history) + [user]))]
        initial = {'messages': messages, 'fresh': [user], 'tool_count': 0, 'tool_chars': 0, 'seen_calls': [],
                   'bound': bound, 'complete': False,
                   'trace': {'turn_id': str(uuid.uuid4()), 'protocol': PROTOCOL, 'model': identity.get('name', 'slm'),
                             'provider': identity.get('provider', 'custom'), 'model_digest': identity.get('digest'),
                             'ollama_version': identity.get('ollama_version'),
                             'reported_cost_usd': 0.0 if identity.get('provider') == 'openrouter' else None,
                             'model_calls': 0, 'prompt_tokens': 0, 'generated_tokens': 0,
                             'tools': [], 'steps': [], 'general_citations_removed': 0}}
        state = graph.invoke(initial, config, **({'durability': 'sync'} if saver else {}))
    state = copy.deepcopy(state)
    state['trace']['tool_count'] = state.get('tool_count', 0)
    state['trace']['resumed_from_checkpoint'] = bool(checkpoint and checkpoint.values)
    state['trace']['metrics_scope'] = 'checkpointed_path; failed attempts are logged separately'
    restore(state['bound'])
    return {'message': state['fresh'][-1]['content'], 'messages': state['fresh'], 'trace': state['trace']}
