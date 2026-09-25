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


def _summarize_tool_result(name, args, result):
    if not isinstance(result, dict):
        return 'Kết quả không xác định'
    err = result.get('error')
    if err:
        error_labels = {
            'order_not_found': f"Không tìm thấy đơn hàng {args.get('order_id', '')} trong tài khoản",
            'tool_not_allowed': f"Công cụ '{name}' ngoài phạm vi worker",
            'invalid_tool_arguments': 'Tham số truyền vào công cụ không hợp lệ',
            'product_not_found': f"Chưa tìm thấy sản phẩm {args.get('product_id', '')}",
            'permission_denied': 'Không đủ quyền truy cập tài nguyên',
            'tool_unavailable': 'Nguồn dữ liệu tạm thời chưa sẵn sàng'
        }
        return error_labels.get(err, f'Lỗi: {err}')
    if name == 'get_order':
        order = result.get('order', {})
        return f"Đơn {order.get('id', '')}: {order.get('name', '')} ({order.get('variant', '')}), trạng thái: {order.get('status', '')}"
    if name == 'get_product':
        prod = result.get('product', {})
        mat = prod.get('material', '')
        warr = prod.get('warranty_days')
        warr_str = f", bảo hành {warr} ngày" if warr else ""
        return f"Sản phẩm {prod.get('id', '')}: {prod.get('name', '')}{f', chất liệu: {mat}' if mat else ''}{warr_str}"
    if name == 'get_context':
        order = result.get('order', {})
        prod = result.get('product', {})
        oid = order.get('id')
        pid = order.get('product_id') or prod.get('id')
        parts = []
        if oid:
            parts.append(f"đơn {oid}")
        if pid:
            parts.append(f"sản phẩm {pid}")
        return f"Context: {', '.join(parts) if parts else 'không có focus'}"
    if name == 'search_knowledge':
        results = result.get('results', [])
        return f"Tìm thấy {len(results)} tài liệu chính sách liên quan"
    if name == 'track_shipment':
        shipment = result.get('shipment', {})
        return f"Vận đơn: {shipment.get('carrier', 'N/A')} - {shipment.get('tracking_code', 'Chưa có')}"
    if name == 'list_orders':
        orders = result.get('orders', [])
        return f"Tìm thấy {len(orders)} đơn hàng trong tài khoản"
    return 'Thực thi thành công'


def call_model(gateway, messages, allow_tools, deadline, trace, *, allowed_tools=None):
    from retailops_agent import AgentError
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AgentError('agent_timeout', 'Model vượt thời gian xử lý.', trace)
    validate_messages(messages)
    # Count attempts before transport/normalization, not only successful returns.
    trace['model_calls'] = trace.get('model_calls', 0) + 1
    trace.setdefault('model_responses', 0)
    try:
        seconds = max(1, min(45, math.ceil(remaining)))
        scoped = getattr(gateway, 'chat_scoped', None)
        if allowed_tools is not None and callable(scoped):
            response = scoped(messages, allow_tools, seconds, allowed_tools)
        else:
            # Legacy/test gateways still face the execution-time allowlist below.
            response = gateway.chat(messages, allow_tools, seconds)
        message = assistant_message(response)
        step_thought = response.get('reasoning')
        if step_thought:
            message['_reasoning'] = str(step_thought)
            if not trace.get('reasoning'):
                trace['reasoning'] = str(step_thought)
            else:
                trace['reasoning'] += '\n---\n' + str(step_thought)
    except (AgentError, RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
        code = exc.code if isinstance(exc, AgentError) else 'agent_response_failed'
        trace['reported_cost_usd'] = None
        trace['usage_incomplete'] = True
        err_entry = {'code': code, 'call': trace['model_calls']}
        if isinstance(exc, AgentError) and isinstance(exc.trace, dict):
            for k in ('http_status', 'error_kind', 'stage', 'upstream_code'):
                if k in exc.trace:
                    err_entry[k] = exc.trace[k]
        trace.setdefault('model_errors', []).append(err_entry)
        raise AgentError(code, 'Không nhận được phản hồi hợp lệ từ model. Vui lòng thử lại.', trace) from None
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
                    worker, timeout=60):
    from retailops_agent import AgentError

    state = copy.deepcopy(state)
    state['consecutive_ood_count'] = 0
    trace = state.setdefault('trace', {})
    trace['answer_source'] = 'llm_agent'
    trace['selected_worker'] = worker
    trace['allowed_tools'] = sorted(list(allowed_tools))
    trace.setdefault('steps', [])
    messages = worker_messages(state, prompt)
    deadline = time.monotonic() + timeout
    records = []
    final = None
    for step in range(MAX_MODEL_CALLS):
        step_num = step + 1
        allow = step < MAX_MODEL_CALLS - 1 and state['tool_count'] < MAX_TOOL_CALLS
        try:
            message = call_model(gateway, messages, allow, deadline, trace, allowed_tools=allowed_tools)
        except AgentError as exc:
            final = render(records) if records else None
            if not final:
                raise
            trace.update(answer_source='tool_result', degraded=True, fallback_reason=exc.code)
            trace['steps'].append({
                'step': step_num,
                'worker': worker,
                'action': 'fallback_render',
                'thought': 'Kích hoạt phương án cứu dữ liệu do model gặp ngoại lệ.',
                'summary': f'Khôi phục phản hồi an toàn từ dữ kiện đã có ({exc.code}).',
                'evaluation': 'Đã hoàn tất bằng fallback renderer.',
                'backtrack': True
            })
            break
        calls = message.get('tool_calls', [])
        step_thought = message.pop('_reasoning', None)
        if not calls:
            final = message['content']
            trace['steps'].append({
                'step': step_num,
                'worker': worker,
                'action': 'final_answer',
                'thought': step_thought,
                'summary': 'Tổng hợp dữ kiện và hoàn tất câu trả lời.',
                'evaluation': 'Đầy đủ dữ kiện đã xác minh để phản hồi khách hàng.'
            })
            break
        if not allow or state['tool_count'] + len(calls) > MAX_TOOL_CALLS:
            if records:
                final = render(records)
                if final:
                    trace.update(answer_source='tool_result', degraded=True, fallback_reason='agent_budget_exceeded')
                    trace['steps'].append({
                        'step': step_num,
                        'worker': worker,
                        'action': 'budget_exceeded_fallback',
                        'thought': 'Vượt ngân sách gọi công cụ; tiến hành tổng hợp ngay.',
                        'summary': 'Chuyển sang tổng hợp dữ kiện hiện có.',
                        'evaluation': 'Đạt ngân sách tối đa của lượt.'
                    })
                    break
            raise AgentError('agent_budget_exceeded', 'Model vượt giới hạn gọi công cụ.', trace)
        # Append the assistant ONCE per batch, then exactly one result per call.
        messages.append(message)
        state['fresh'].append(copy.deepcopy(message))
        state['messages'].append(copy.deepcopy(message))
        business_error = False
        step_tools = []
        has_step_error = False
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
            tool_entry = {'name': name, 'status': 'error' if code else 'ok'}
            if code:
                tool_entry['error_code'] = code
            if invalid == 'tool_not_allowed':
                tool_entry['executed'] = False
                tool_entry['stage'] = 'worker_scope_guard'
            trace.setdefault('tools', []).append(tool_entry)
            if code in UNAVAILABLE:
                trace['outcome'] = 'tool_unavailable'
                raise AgentError('tool_unavailable', 'Nguồn dữ liệu chưa sẵn sàng. Chưa thể xác minh kết quả.', trace)
            entry = {'role': 'tool', 'tool_name': name,
                     'content': json.dumps(result, ensure_ascii=False, separators=(',', ':'))}
            messages.append(entry)
            state['fresh'].append(copy.deepcopy(entry))
            state['messages'].append(copy.deepcopy(entry))
            records.append({'name': name, 'args': args, 'result': result})
            business_error = business_error or bool(code)
            if code:
                has_step_error = True
            step_tools.append({
                'name': name,
                'args': args,
                'status': 'error' if code else 'ok',
                'error_code': code,
                'summary': _summarize_tool_result(name, args, result)
            })

        is_backtrack = has_step_error or (step > 0 and any(s.get('backtrack') or any(t.get('status') == 'error' for t in s.get('tools', [])) for s in trace['steps']))
        if has_step_error:
            step_eval = 'Phát hiện giới hạn hoặc lỗi tra cứu; agent tự đánh giá để điều chỉnh hoặc dùng phương án thay thế.'
        else:
            tool_names = ', '.join(t['name'] for t in step_tools)
            step_eval = f'Đã thu thập dữ kiện từ {tool_names}; chuyển sang bước suy luận tiếp theo.'

        trace['steps'].append({
            'step': step_num,
            'worker': worker,
            'action': 'tool_call',
            'thought': step_thought,
            'tools': step_tools,
            'evaluation': step_eval,
            'backtrack': is_backtrack
        })

        if business_error:
            # The LLM cannot overrule an ownership denial or invent a missing order.
            final = render(records)
            if not final:
                successful_records = [r for r in records if not r.get('result', {}).get('error')]
                if successful_records:
                    final = render(successful_records)
            if not final:
                raise AgentError('tool_response_failed', 'Chưa thể xác minh kết quả tra cứu.', trace)
            codes = sorted({r['result']['error'] for r in records if r['result'].get('error')})
            hard_denial = any(code in ('order_not_found', 'permission_denied', 'forbidden') for code in codes)
            partial = any(not r['result'].get('error') for r in records) and not hard_denial
            trace.update(answer_source='tool_result', outcome='partial' if partial else 'business_error')
            if partial:
                trace.update(degraded=True, warning_codes=codes)
            trace['steps'].append({
                'step': step_num + 1,
                'worker': worker,
                'action': 'business_error_render',
                'thought': 'Áp dụng renderer chuyên biệt để phản hồi trung thực kết quả tra cứu thực tế.',
                'summary': 'Tổng hợp kết quả từ dữ kiện an toàn.',
                'evaluation': 'Đã phản hồi minh bạch về giới hạn dữ liệu.'
            })
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
