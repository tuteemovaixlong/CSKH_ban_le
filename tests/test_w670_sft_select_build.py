"""Unit tests for W6.7.0 Part B: sft_select.py and sft_build.py.

Uses only synthetic fixtures constructed inside tempfile (no E: drive, no network).
Guards script imports so the Colab notebook test bundle (which omits scripts/) skips cleanly.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HAS_PART_B = (ROOT / 'scripts' / 'sft_select.py').is_file() and (ROOT / 'scripts' / 'sft_build.py').is_file()

if HAS_PART_B:
    from scripts import eval_regrade, sft_build, sft_select  # noqa: E402


def _make_turn_trace(
    case_id: str,
    run: int,
    turn: int,
    *,
    system_prompt: str = 'SYSTEM PROMPT CHINH XAC',
    user_text: str = 'Khách hỏi đơn hàng',
    steps: list[dict] | None = None,
    final_content: str = 'Dạ đơn hàng đã giao.',
    final_reasoning: str = 'Suy nghĩ bước cuối hợp lý.',
    final_finish_reason: str = 'stop',
    final_error: dict | None = None,
    completion_tokens: int = 40,
    tools_schema: list[dict] | None = None,
    omit_usage: bool = False,
) -> list[dict]:
    """Build synthetic shard-*.jsonl trace records for one turn."""
    tools = tools_schema or [
        {'type': 'function', 'function': {'name': 'get_order', 'description': 'Tra cứu đơn', 'parameters': {'type': 'object'}}}
    ]
    msgs: list[dict] = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_text},
    ]
    records: list[dict] = []
    for st in (steps or []):
        req_msgs = json.loads(json.dumps(msgs))
        raw_tcs = []
        for idx, tc in enumerate(st.get('tool_calls') or []):
            tc_id = tc.get('id') or f'call_{turn}_{len(records)}_{idx}'
            args_val = tc.get('arguments', {})
            raw_tcs.append({
                'id': tc_id,
                'type': 'function',
                'function': {
                    'name': tc['name'],
                    'arguments': args_val if isinstance(args_val, str) else json.dumps(args_val, ensure_ascii=False),
                },
            })
        resp: dict = {
            'content': st.get('content', ''),
            'reasoning': st.get('reasoning', ''),
            'tool_calls': raw_tcs,
            'finish_reason': st.get('finish_reason', 'tool_calls'),
            'usage': {} if omit_usage else {'prompt_tokens': 100, 'completion_tokens': st.get('completion_tokens', 20)},
            'error': st.get('error'),
        }
        records.append({
            'case_id': case_id,
            'run': run,
            'turn': turn,
            'request': {'messages': req_msgs, 'tools': tools},
            'response': resp,
        })
        asst_hist: dict = {
            'role': 'assistant',
            'content': st.get('content', ''),
            'tool_calls': raw_tcs,
        }
        if 'reasoning' in st:
            asst_hist['reasoning'] = st['reasoning']
        if 'reasoning_details' in st:
            asst_hist['reasoning_details'] = st['reasoning_details']
        msgs.append(asst_hist)
        for tc_obj, res_str in zip(raw_tcs, st.get('tool_results') or []):
            msgs.append({
                'role': 'tool',
                'tool_call_id': tc_obj['id'],
                'content': res_str,
            })

    if final_finish_reason is not None:
        final_resp: dict = {
            'content': final_content,
            'reasoning': final_reasoning,
            'tool_calls': [],
            'finish_reason': final_finish_reason,
            'usage': {} if omit_usage else {'prompt_tokens': 120, 'completion_tokens': completion_tokens},
            'error': final_error,
        }
        records.append({
            'case_id': case_id,
            'run': run,
            'turn': turn,
            'request': {'messages': json.loads(json.dumps(msgs)), 'tools': tools},
            'response': final_resp,
        })
    return records


def _build_synthetic_workspace(root: Path) -> dict:
    """Create cases JSONL + qwen (4 runs) + deepseek (2 runs) run directories."""
    cases_path = root / 'cases_sft_v1_filled.jsonl'
    qwen_dir = root / 'run_qwen'
    ds_dir = root / 'run_deepseek'
    qwen_dir.mkdir(parents=True, exist_ok=True)
    ds_dir.mkdir(parents=True, exist_ok=True)

    c1 = {
        'id': 't01_001_tra_don_delivered',
        'category': 't01',
        'title': 'Tra cứu đơn hàng đã giao',
        'fixture': 'sft_v1',
        'customer': 'SIM-C-5001',
        'meta': {'suite': 'T01', 'split': 'train', 'style': 'chuan', 'origin': 'sinh_sft', 'template': 't01_tra_don_delivered'},
        'turns': [
            {
                'user': 'Kiểm tra giúp mình đơn hàng SIM-O-50006 đã giao chưa nhé',
                'expect': {'answer_all': ['SIM-O-50006'], 'answer_any': [['đã giao', 'hoàn tất']], 'answer_not': ['chưa có thông tin']},
            }
        ],
    }
    c2 = {
        'id': 't08_002_da_luot_doi_chu_de',
        'category': 't08',
        'title': 'Hội thoại đa lượt đổi chủ đề',
        'fixture': 'sft_v1',
        'customer': 'SIM-C-5002',
        'meta': {'suite': 'T08', 'split': 'train', 'style': 'teencode', 'origin': 'sinh_sft', 'template': 't08_da_luot'},
        'turns': [
            {
                'user': 'Đơn SIM-O-50007 giao tới đâu rồi shop ơi',
                'expect': {'answer_all': ['SIM-O-50007'], 'answer_not': ['không tìm thấy']},
            },
            {
                'user': 'À cho mình hỏi luôn đơn SIM-O-50008 có hủy được không',
                'expect': {'answer_all': ['SIM-O-50008'], 'answer_any': [['hủy', 'huỷ']], 'answer_not': ['đã hủy xong']},
            },
        ],
    }
    c3 = {
        'id': 't04_003_khong_tier_a',
        'category': 't04',
        'title': 'Yêu cầu hủy đơn không có mẫu Tier A',
        'fixture': 'sft_v1',
        'customer': 'SIM-C-5003',
        'meta': {'suite': 'T04', 'split': 'train', 'style': 'dai', 'origin': 'sinh_sft', 'template': 't04_huy_pending'},
        'turns': [
            {
                'user': 'Nhờ shop kiểm tra giúp xem đơn SIM-O-50009 còn hủy được không ạ',
                'expect': {'answer_all': ['SIM-O-50009'], 'answer_not': ['bị lỗi hệ thống']},
            }
        ],
    }
    c4 = {
        'id': 't11_004_staff_case_assist',
        'category': 't11',
        'title': 'Trợ lý ca soạn nháp cho nhân viên',
        'fixture': 'sft_v1',
        'customer': 'SIM-C-5004',
        'actor': 'staff_case_assist',
        'case_setup': {
            'customer_messages': [{'text': 'Đơn SIM-O-50010 của tôi bị giao trễ quá hạn rồi.'}],
            'handoff_comment': 'Khách yêu cầu kiểm tra bồi thường giao trễ',
        },
        'meta': {'suite': 'T11', 'split': 'train', 'style': 'chuan', 'origin': 'sinh_sft', 'template': 't11_tro_ly_ca'},
        'turns': [
            {
                'user': '',
                'mode': 'draft',
                'expect': {'answer_all': ['SIM-O-50010'], 'answer_not': ['chắc chắn được duyệt']},
            }
        ],
    }

    cases = [c1, c2, c3, c4]
    cases_path.write_text(''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in cases), encoding='utf-8')

    long_tool_payload = json.dumps({'order_id': 'SIM-O-50006', 'status': 'delivered', 'note': 'X' * 4500}, ensure_ascii=False)

    qwen_records = []
    qwen_traces = []

    # ---- Case 1: Qwen runs 1..4
    # Run 1: failed official
    qwen_records.append({
        'id': c1['id'], 'run': 1, 'passed': False, 'failures': ['turn 1: missing phrase'],
        'attack_success': False, 'turns': [{'answer': 'Không rõ đơn.', 'tools': [], 'error': None}],
    })
    qwen_traces.extend(_make_turn_trace(c1['id'], 1, 1, user_text=c1['turns'][0]['user'], final_content='Không rõ đơn.'))

    # Run 2: B_code (answer_check -> dropped), 1 tool
    qwen_records.append({
        'id': c1['id'], 'run': 2, 'passed': True, 'failures': [], 'attack_success': False,
        'turns': [{'answer': 'Đơn SIM-O-50006 đã giao thành công.', 'tools': [{'name': 'get_order'}], 'error': None,
                   'answer_check': {'dropped_policy_promises': 1, 'detail': []}}],
    })
    qwen_traces.extend(_make_turn_trace(
        c1['id'], 2, 1, user_text=c1['turns'][0]['user'],
        steps=[{'reasoning': 'Tra đơn', 'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'SIM-O-50006'}}],
                'tool_results': ['{"status":"delivered"}'], 'completion_tokens': 15}],
        final_content='Đơn SIM-O-50006 đã giao thành công.', completion_tokens=30,
    ))

    # Run 3: A_code, 2 tools (distinct args), 120 completion_tokens -> ranked AFTER run 4
    qwen_records.append({
        'id': c1['id'], 'run': 3, 'passed': True, 'failures': [], 'attack_success': False,
        'turns': [{'answer': 'Đơn SIM-O-50006 đã giao xong rồi ạ.', 'tools': [{'name': 'get_order'}, {'name': 'get_context'}], 'error': None}],
    })
    qwen_traces.extend(_make_turn_trace(
        c1['id'], 3, 1, user_text=c1['turns'][0]['user'],
        steps=[{
            'reasoning': 'Gọi 2 tool khác nhau',
            'tool_calls': [
                {'name': 'get_order', 'arguments': {'order_id': 'SIM-O-50006'}},
                {'name': 'get_context', 'arguments': {'topic': 'shipping'}},
            ],
            'tool_results': ['{"status":"delivered"}', '{"policy":"ok"}'],
            'completion_tokens': 50,
        }],
        final_content='Đơn SIM-O-50006 đã giao xong rồi ạ.', completion_tokens=70,
    ))

    # Run 4: A_code, 1 tool, 80 completion_tokens, long 4500-char tool result + multi-step reasoning -> RANK 0 for c1!
    qwen_records.append({
        'id': c1['id'], 'run': 4, 'passed': True, 'failures': [], 'attack_success': False,
        'turns': [{'answer': 'Dạ đơn SIM-O-50006 đã giao.', 'tools': [{'name': 'get_order'}], 'error': None}],
    })
    qwen_traces.extend(_make_turn_trace(
        c1['id'], 4, 1, user_text=c1['turns'][0]['user'],
        steps=[{
            'reasoning': 'Kiểm tra trạng thái giao hàng của đơn SIM-O-50006',
            'reasoning_details': [{'type': 'text', 'text': 'internal'}],
            'tool_calls': [{'name': 'get_order', 'arguments': '{"order_id": "SIM-O-50006"}'}],
            'tool_results': [long_tool_payload],
            'completion_tokens': 30,
        }],
        final_content='Dạ đơn SIM-O-50006 đã giao.',
        final_reasoning='Tool get_order xác nhận đơn SIM-O-50006 ở trạng thái delivered.',
        completion_tokens=50,
    ))

    # ---- Case 2: Qwen runs 1..4 (multi-turn)
    # Run 1: finish_reason == 'length' in turn 2 -> rejected!
    qwen_records.append({
        'id': c2['id'], 'run': 1, 'passed': True, 'failures': [], 'attack_success': False,
        'turns': [
            {'answer': 'Đơn SIM-O-50007 đang giao.', 'tools': [], 'error': None},
            {'answer': 'Đơn SIM-O-50008 có thể huỷ.', 'tools': [], 'error': None},
        ],
    })
    qwen_traces.extend(_make_turn_trace(c2['id'], 1, 1, user_text=c2['turns'][0]['user'], final_content='Đơn SIM-O-50007 đang giao.'))
    qwen_traces.extend(_make_turn_trace(c2['id'], 1, 2, user_text=c2['turns'][1]['user'], final_content='Đơn SIM-O-50008 có thể huỷ.', final_finish_reason='length'))

    # Run 2: turn['error'] -> rejected!
    qwen_records.append({
        'id': c2['id'], 'run': 2, 'passed': True, 'failures': [], 'attack_success': False,
        'turns': [
            {'answer': 'Đơn SIM-O-50007 đang giao.', 'tools': [], 'error': {'code': 'api_unavailable'}},
            {'answer': 'Đơn SIM-O-50008 có thể huỷ.', 'tools': [], 'error': None},
        ],
    })
    qwen_traces.extend(_make_turn_trace(c2['id'], 2, 1, user_text=c2['turns'][0]['user'], final_content='Đơn SIM-O-50007 đang giao.'))
    qwen_traces.extend(_make_turn_trace(c2['id'], 2, 2, user_text=c2['turns'][1]['user'], final_content='Đơn SIM-O-50008 có thể huỷ.'))

    # Run 3: B_code (audit flag)
    qwen_records.append({
        'id': c2['id'], 'run': 3, 'passed': True, 'failures': [], 'attack_success': False,
        'turns': [
            {'answer': 'Đơn SIM-O-50007 đang giao.', 'tools': [], 'error': None, 'answer_check_audit': [{'rule': 'audit_1'}]},
            {'answer': 'Đơn SIM-O-50008 có thể hủy.', 'tools': [], 'error': None},
        ],
    })
    qwen_traces.extend(_make_turn_trace(c2['id'], 3, 1, user_text=c2['turns'][0]['user'], final_content='Đơn SIM-O-50007 đang giao.', completion_tokens=45))
    qwen_traces.extend(_make_turn_trace(c2['id'], 3, 2, user_text=c2['turns'][1]['user'], final_content='Đơn SIM-O-50008 có thể hủy.', completion_tokens=45))

    # Run 4: A_code -> rank 0 for c2 (will be judged Tier C in round 1!)
    qwen_records.append({
        'id': c2['id'], 'run': 4, 'passed': True, 'failures': [], 'attack_success': False,
        'turns': [
            {'answer': 'Đơn SIM-O-50007 đang vận chuyển tới bạn.', 'tools': [{'name': 'get_order'}], 'error': None},
            {'answer': 'Đơn SIM-O-50008 vẫn hủy được ngay lúc này.', 'tools': [{'name': 'get_order'}], 'error': None},
        ],
    })
    qwen_traces.extend(_make_turn_trace(
        c2['id'], 4, 1, user_text=c2['turns'][0]['user'],
        steps=[{'reasoning': 'Tra đơn SIM-O-50007', 'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'SIM-O-50007'}}],
                'tool_results': ['{"status":"shipping"}'], 'completion_tokens': 20}],
        final_content='Đơn SIM-O-50007 đang vận chuyển tới bạn.', completion_tokens=40,
    ))
    qwen_traces.extend(_make_turn_trace(
        c2['id'], 4, 2, user_text=c2['turns'][1]['user'],
        steps=[{'reasoning': 'Tra đơn SIM-O-50008 thấy đang giao nhưng nói nhầm hủy được',
                'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'SIM-O-50008'}}],
                'tool_results': ['{"status":"shipping","can_cancel":false}'], 'completion_tokens': 20}],
        final_content='Đơn SIM-O-50008 vẫn hủy được ngay lúc này.',
        final_reasoning='Khẳng định hủy được dù tool báo can_cancel false.',
        completion_tokens=40,
    ))

    # ---- Case 3: Qwen runs 1..4 (no Tier A!)
    # Run 1: A_code (will be judged Tier B via disagreement dat vs khong_chac)
    qwen_records.append({
        'id': c3['id'], 'run': 1, 'passed': True, 'failures': [], 'attack_success': False,
        'turns': [{'answer': 'Đơn SIM-O-50009 đang chờ xác nhận, có thể hủy.', 'tools': [{'name': 'get_order'}], 'error': None}],
    })
    qwen_traces.extend(_make_turn_trace(
        c3['id'], 1, 1, user_text=c3['turns'][0]['user'],
        steps=[{'reasoning': 'Kiểm tra SIM-O-50009', 'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'SIM-O-50009'}}],
                'tool_results': ['{"status":"pending","can_cancel":true}'], 'completion_tokens': 20}],
        final_content='Đơn SIM-O-50009 đang chờ xác nhận, có thể hủy.', completion_tokens=30,
    ))
    # Run 2: B_code (duplicate_tool via different JSON key ordering!)
    qwen_records.append({
        'id': c3['id'], 'run': 2, 'passed': True, 'failures': [], 'attack_success': False,
        'turns': [{'answer': 'Đơn SIM-O-50009 có thể hủy.', 'tools': [{'name': 'get_order'}, {'name': 'get_order'}], 'error': None}],
    })
    qwen_traces.extend(_make_turn_trace(
        c3['id'], 2, 1, user_text=c3['turns'][0]['user'],
        steps=[
            {'reasoning': 'Gọi lần 1', 'tool_calls': [{'name': 'get_order', 'arguments': '{"a":1,"order_id":"SIM-O-50009"}'}],
             'tool_results': ['{"status":"pending"}'], 'completion_tokens': 15},
            {'reasoning': 'Gọi lại y hệt', 'tool_calls': [{'name': 'get_order', 'arguments': '{"order_id":"SIM-O-50009","a":1}'}],
             'tool_results': ['{"status":"pending"}'], 'completion_tokens': 15},
        ],
        final_content='Đơn SIM-O-50009 có thể hủy.', completion_tokens=30,
    ))
    # Run 3: missing_stop_call -> rejected
    qwen_records.append({
        'id': c3['id'], 'run': 3, 'passed': True, 'failures': [], 'attack_success': False,
        'turns': [{'answer': 'Đơn SIM-O-50009 có thể hủy.', 'tools': [], 'error': None}],
    })
    qwen_traces.extend(_make_turn_trace(c3['id'], 3, 1, user_text=c3['turns'][0]['user'], final_finish_reason=None))
    # Run 4: attack_success -> rejected
    qwen_records.append({
        'id': c3['id'], 'run': 4, 'passed': True, 'failures': [], 'attack_success': True,
        'turns': [{'answer': 'Đơn SIM-O-50009 có thể hủy.', 'tools': [], 'error': None}],
    })
    qwen_traces.extend(_make_turn_trace(c3['id'], 4, 1, user_text=c3['turns'][0]['user'], final_content='Đơn SIM-O-50009 có thể hủy.'))

    # ---- Case 4: Qwen runs 1..4 (staff_case_assist -> Tier A)
    for r in range(1, 5):
        qwen_records.append({
            'id': c4['id'], 'run': r, 'passed': True, 'failures': [], 'attack_success': False,
            'turns': [{'answer': 'Ghi chú nội bộ: đơn SIM-O-50010 trễ 30h.', 'draft_reply': 'Dạ shop đang kiểm tra đơn SIM-O-50010 cho bạn ạ.',
                       'tools': [{'name': 'get_order'}], 'error': None}],
        })
        qwen_traces.extend(_make_turn_trace(
            c4['id'], r, 1, user_text='Khách hỏi đơn SIM-O-50010 bị giao trễ',
            steps=[{'reasoning': 'Kiểm tra giao trễ SIM-O-50010', 'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'SIM-O-50010'}}],
                    'tool_results': ['{"order_id":"SIM-O-50010","late_hours":30}'], 'completion_tokens': 20}],
            final_content='Ghi chú nội bộ: đơn SIM-O-50010 trễ 30h.\n<draft_reply>Dạ shop đang kiểm tra đơn SIM-O-50010 cho bạn ạ.</draft_reply>',
            final_reasoning='Đơn SIM-O-50010 trễ 30 giờ, chưa đủ ngưỡng 48 giờ.',
            completion_tokens=40 + r * 5,
        ))

    # ---- DeepSeek runs 1..2
    ds_records = []
    ds_traces = []

    # Case 1 DeepSeek run 1 (A_code, fewer tokens than Qwen, still ranked AFTER Qwen!) & run 2 (B_code duplicate_tool)
    ds_records.append({
        'id': c1['id'], 'run': 1, 'passed': True, 'failures': [], 'attack_success': False,
        'turns': [{'answer': 'Đơn SIM-O-50006 đã giao.', 'tools': [{'name': 'get_order'}], 'error': None}],
    })
    ds_traces.extend(_make_turn_trace(
        c1['id'], 1, 1, user_text=c1['turns'][0]['user'],
        steps=[{'reasoning': 'Tra đơn', 'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'SIM-O-50006'}}],
                'tool_results': ['{"status":"delivered"}'], 'completion_tokens': 10}],
        final_content='Đơn SIM-O-50006 đã giao.', completion_tokens=20,
    ))
    ds_records.append({
        'id': c1['id'], 'run': 2, 'passed': True, 'failures': [], 'attack_success': False,
        'turns': [{'answer': 'Đơn SIM-O-50006 đã giao.', 'tools': [{'name': 'get_order'}, {'name': 'get_order'}], 'error': None}],
    })
    ds_traces.extend(_make_turn_trace(
        c1['id'], 2, 1, user_text=c1['turns'][0]['user'],
        steps=[
            {'reasoning': '1', 'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'SIM-O-50006'}}], 'tool_results': ['{}']},
            {'reasoning': '2', 'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'SIM-O-50006'}}], 'tool_results': ['{}']},
        ],
        final_content='Đơn SIM-O-50006 đã giao.', completion_tokens=20,
    ))

    # Case 2 DeepSeek run 1 (A_code, fewer tokens -> chosen in Round 2!) & run 2 (A_code, more tokens)
    for r, toks in [(1, 30), (2, 80)]:
        ds_records.append({
            'id': c2['id'], 'run': r, 'passed': True, 'failures': [], 'attack_success': False,
            'turns': [
                {'answer': 'Đơn SIM-O-50007 đang trên đường giao ạ.', 'tools': [{'name': 'get_order'}], 'error': None},
                {'answer': 'Đơn SIM-O-50008 không thể hủy vì đang giao rồi ạ.', 'tools': [{'name': 'get_order'}], 'error': None},
            ],
        })
        ds_traces.extend(_make_turn_trace(
            c2['id'], r, 1, user_text=c2['turns'][0]['user'],
            steps=[{'reasoning': 'Tra đơn SIM-O-50007', 'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'SIM-O-50007'}}],
                    'tool_results': ['{"status":"shipping"}'], 'completion_tokens': 10}],
            final_content='Đơn SIM-O-50007 đang trên đường giao ạ.',
            final_reasoning='Tool xác nhận đơn SIM-O-50007 đang giao.',
            completion_tokens=toks,
        ))
        ds_traces.extend(_make_turn_trace(
            c2['id'], r, 2, user_text=c2['turns'][1]['user'],
            steps=[{'reasoning': 'Tra đơn SIM-O-50008', 'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'SIM-O-50008'}}],
                    'tool_results': ['{"status":"shipping","can_cancel":false}'], 'completion_tokens': 10}],
            final_content='Đơn SIM-O-50008 không thể hủy vì đang giao rồi ạ.',
            final_reasoning='Tool báo can_cancel là false nên không hủy được.',
            completion_tokens=toks,
        ))

    # Case 3 DeepSeek run 1 & 2: trace error -> rejected!
    for r in (1, 2):
        ds_records.append({
            'id': c3['id'], 'run': r, 'passed': True, 'failures': [], 'attack_success': False,
            'turns': [{'answer': 'Đơn SIM-O-50009 có thể hủy.', 'tools': [], 'error': None}],
        })
        ds_traces.extend(_make_turn_trace(
            c3['id'], r, 1, user_text=c3['turns'][0]['user'],
            final_content='Đơn SIM-O-50009 có thể hủy.',
            final_error={'code': 'timeout', 'kind': 'timeout'},
        ))

    # Case 4 DeepSeek run 1 & 2
    for r in (1, 2):
        ds_records.append({
            'id': c4['id'], 'run': r, 'passed': True, 'failures': [], 'attack_success': False,
            'turns': [{'answer': 'Ghi chú: đơn SIM-O-50010 trễ.', 'tools': [], 'error': None}],
        })
        ds_traces.extend(_make_turn_trace(c4['id'], r, 1, user_text='Khách hỏi đơn SIM-O-50010', final_content='Ghi chú: đơn SIM-O-50010 trễ.'))

    (qwen_dir / 'merged.json').write_text(
        json.dumps({'provenance': {'git_sha': 'a' * 40}, 'scenarios': qwen_records}, ensure_ascii=False),
        encoding='utf-8',
    )
    (qwen_dir / 'manifest.json').write_text(json.dumps({'repeat': 4, 'git_sha': 'a' * 40}), encoding='utf-8')
    (qwen_dir / 'shard-00.jsonl').write_text(''.join(json.dumps(t, ensure_ascii=False) + '\n' for t in qwen_traces), encoding='utf-8')

    (ds_dir / 'merged.json').write_text(
        json.dumps({'provenance': {'git_sha': 'b' * 40}, 'scenarios': ds_records}, ensure_ascii=False),
        encoding='utf-8',
    )
    (ds_dir / 'manifest.json').write_text(json.dumps({'repeat': 2, 'git_sha': 'b' * 40}), encoding='utf-8')
    (ds_dir / 'shard-00.jsonl').write_text(''.join(json.dumps(t, ensure_ascii=False) + '\n' for t in ds_traces), encoding='utf-8')

    return {'cases_path': cases_path, 'qwen_dir': qwen_dir, 'ds_dir': ds_dir, 'cases': cases}


@unittest.skipUnless(HAS_PART_B, 'scripts/sft_select.py and scripts/sft_build.py are absent in the Colab bundle')
class TestW670SftSelectAndBuild(unittest.TestCase):
    def _run_select(self, *argv: str) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = sft_select.main(list(argv))
        return code, buf.getvalue()

    def _run_build(self, *argv: str) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = sft_build.main(list(argv))
        return code, buf.getvalue()

    def _write_verdicts(self, judge_dir: Path, group: str, mapping: dict, decide) -> None:
        folder = judge_dir / 'verdicts' / group
        folder.mkdir(parents=True, exist_ok=True)
        for batch, item_ids in mapping['batches'].items():
            lines = [
                json.dumps(decide(iid, mapping['items'][iid]), ensure_ascii=False)
                for iid in item_ids
            ]
            (folder / f'{batch}.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    def test_print_rubric(self) -> None:
        code, out = self._run_select('--print-rubric')
        self.assertEqual(code, 0)
        self.assertIn('dat', out)
        self.assertIn('khong_dat', out)
        self.assertIn('khong_chac', out)
        self.assertIn('MIN_QUOTE = 8', out)
        self.assertIn(sft_select.REQUIREMENT_TEXT, out)

    def test_end_to_end_score_export_import_select_and_build(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w670-b-') as td:
            root = Path(td)
            fx = _build_synthetic_workspace(root)
            scores_path = root / 'scores.json'

            # 1. SCORE
            code, _ = self._run_select(
                'score',
                '--cases', str(fx['cases_path']),
                '--run', f"qwen={fx['qwen_dir']}",
                '--run', f"deepseek={fx['ds_dir']}",
                '--out', str(scores_path),
            )
            self.assertEqual(code, 0)
            scores = json.loads(scores_path.read_text(encoding='utf-8'))
            self.assertEqual(scores['repo_sha']['qwen'], 'a' * 40)
            self.assertEqual(scores['repo_sha']['deepseek'], 'b' * 40)

            # Check Case 1 candidate ordering: qwen A_code (run 4: 1 tool, 80 tok) < qwen A_code (run 3: 2 tools) < qwen B_code (run 2: dropped) < ds A_code (run 1) < ds B_code (run 2: duplicate_tool)
            c1_cands = scores['cases']['t01_001_tra_don_delivered']['candidates']
            self.assertEqual(
                [(c['model'], c['run'], c['code_tier']) for c in c1_cands],
                [
                    ('qwen', 4, 'A_code'),
                    ('qwen', 3, 'A_code'),
                    ('qwen', 2, 'B_code'),
                    ('deepseek', 1, 'A_code'),
                    ('deepseek', 2, 'B_code'),
                ],
            )
            self.assertEqual(c1_cands[2]['flags'], ['dropped'])
            self.assertEqual(c1_cands[4]['flags'], ['duplicate_tool'])
            c1_rej = scores['cases']['t01_001_tra_don_delivered']['rejected']
            self.assertEqual([(r['model'], r['run']) for r in c1_rej], [('qwen', 1)])

            # Check Case 2 rejections (length, turn_error) and audit flag
            c2_cands = scores['cases']['t08_002_da_luot_doi_chu_de']['candidates']
            self.assertEqual([(c['model'], c['run'], c['code_tier']) for c in c2_cands], [
                ('qwen', 4, 'A_code'),
                ('qwen', 3, 'B_code'),
                ('deepseek', 1, 'A_code'),
                ('deepseek', 2, 'A_code'),
            ])
            self.assertEqual(c2_cands[1]['flags'], ['audit'])
            c2_rej = {(r['model'], r['run']): r['reject_reasons'] for r in scores['cases']['t08_002_da_luot_doi_chu_de']['rejected']}
            self.assertIn('finish_reason_length', c2_rej[('qwen', 1)])
            self.assertIn('turn_error', c2_rej[('qwen', 2)])

            # Check Case 3 rejections (missing_stop_call, attack_success, trace_error)
            c3_rej = {(r['model'], r['run']): r['reject_reasons'] for r in scores['cases']['t04_003_khong_tier_a']['rejected']}
            self.assertIn('missing_stop_call', c3_rej[('qwen', 3)])
            self.assertIn('attack_success', c3_rej[('qwen', 4)])
            self.assertIn('trace_error', c3_rej[('deepseek', 1)])

            # 2. EXPORT ROUND 1
            judge1 = root / 'judge_r1'
            code, _ = self._run_select(
                'export', '--scores', str(scores_path), '--out', str(judge1),
                '--round', '1', '--seed', '12345', '--batch-size', '2',
            )
            self.assertEqual(code, 0)
            map1 = json.loads((judge1 / 'map.json').read_text(encoding='utf-8'))
            # 4 cases -> c1 (1 turn) + c2 (2 turns) + c3 (1 turn) + c4 (1 turn) = 5 items
            self.assertEqual(len(map1['items']), 5)
            for iid in map1['items']:
                self.assertRegex(iid, r'^[0-9a-f]{8}$')

            packets_raw = ''.join(p.read_text(encoding='utf-8') for p in sorted((judge1 / 'packets').glob('batch-*.jsonl')))
            self.assertNotIn('qwen', packets_raw.lower())
            self.assertNotIn('deepseek', packets_raw.lower())
            self.assertIsNone(re.search(r'[ts]\d\d_\d{3}_', packets_raw))
            self.assertNotIn('run_qwen', packets_raw)
            self.assertNotIn('run_deepseek', packets_raw)

            # Verify 3000-char tool result cap and staff_case_assist customer_messages
            packet_rows = [json.loads(line) for p in sorted((judge1 / 'packets').glob('batch-*.jsonl')) for line in p.read_text(encoding='utf-8').splitlines() if line.strip()]
            c1_item_id = map1['candidates']['t01_001_tra_don_delivered#qwen#4']['item_ids'][0]
            c1_packet = next(r for r in packet_rows if r['item_id'] == c1_item_id)
            self.assertLessEqual(len(c1_packet['steps'][0]['tool_results'][0]['content']), 3000)
            self.assertEqual(len(c1_packet['steps'][0]['tool_results'][0]['content']), 3000)

            c4_item_id = map1['candidates']['t11_004_staff_case_assist#qwen#1']['item_ids'][0]
            c4_packet = next(r for r in packet_rows if r['item_id'] == c4_item_id)
            self.assertEqual(c4_packet['context']['role'], 'staff_case_assist')
            self.assertEqual(c4_packet['context']['customer_messages'], ['Đơn SIM-O-50010 của tôi bị giao trễ quá hạn rồi.'])

            # 3. IMPORT ROUND 1
            # - c1 (qwen#4): A & B both 'dat' with valid quotes -> Tier A
            # - c2 (qwen#4): turn 1 both 'dat', turn 2 group B gives valid 'khong_dat' -> Tier C!
            # - c3 (qwen#1): A gives 'dat' with valid quote, B gives 'dat' with INVALID quote -> B downgraded to 'khong_chac' -> Tier B!
            # - c4 (qwen#1): A & B both 'dat' with valid quotes -> Tier A
            def decide_r1_a(iid: str, it: dict) -> dict:
                quote = it['text'][:25]
                return {'item_id': iid, 'verdict': 'dat', 'quote': quote, 'reason': 'Nhất quán.'}

            def decide_r1_b(iid: str, it: dict) -> dict:
                cid, turn = it['case_id'], it['turn']
                if cid == 't08_002_da_luot_doi_chu_de' and turn == 2:
                    return {'item_id': iid, 'verdict': 'khong_dat', 'quote': 'nói nhầm hủy được', 'reason': 'Mâu thuẫn kết quả tool.'}
                if cid == 't04_003_khong_tier_a':
                    return {'item_id': iid, 'verdict': 'dat', 'quote': 'trích dẫn bịa không tồn tại trong văn bản', 'reason': 'Đạt.'}
                return {'item_id': iid, 'verdict': 'dat', 'quote': it['text'][:25], 'reason': 'Nhất quán.'}

            self._write_verdicts(judge1, 'A', map1, decide_r1_a)
            self._write_verdicts(judge1, 'B', map1, decide_r1_b)
            adj1_path = root / 'adjudicated_r1.json'
            code, _ = self._run_select('import', '--judge-dir', str(judge1), '--scores', str(scores_path), '--out', str(adj1_path))
            self.assertEqual(code, 0)
            adj1 = json.loads(adj1_path.read_text(encoding='utf-8'))
            self.assertEqual(adj1['candidates']['t01_001_tra_don_delivered#qwen#4']['tier'], 'A')
            self.assertEqual(adj1['candidates']['t08_002_da_luot_doi_chu_de#qwen#4']['tier'], 'C')
            self.assertEqual(adj1['candidates']['t04_003_khong_tier_a#qwen#1']['tier'], 'B')
            self.assertEqual(adj1['candidates']['t11_004_staff_case_assist#qwen#1']['tier'], 'A')
            self.assertEqual(adj1['downgraded_quotes']['b']['dat'], 1)
            self.assertIsNotNone(adj1['agreement_ab']['kappa'])

            # Also verify invalid quote on 'khong_dat' downgrades to 'khong_chac' -> Tier B (not C)!
            self.assertEqual(
                sft_select.effective_tier_verdict(
                    {'verdict': 'khong_dat', 'quote': 'khong co trong text'},
                    {'text': 'Dạ đơn hàng đã giao thành công.'},
                ),
                'khong_chac',
            )
            self.assertEqual(
                sft_select.effective_tier_verdict(
                    {'verdict': 'khong_dat', 'quote': 'ngan'},  # < 8 chars
                    {'text': 'ngan qua khong du'},
                ),
                'khong_chac',
            )

            # 4. EXPORT ROUND 2 --after adj1
            # c1 and c4 already have Tier A -> skipped; c2 exports next candidate (qwen#3, B_code); c3 exports qwen#2 (B_code)
            judge2 = root / 'judge_r2'
            code, _ = self._run_select(
                'export', '--scores', str(scores_path), '--out', str(judge2),
                '--round', '2', '--after', str(adj1_path), '--seed', '54321', '--batch-size', '10',
            )
            self.assertEqual(code, 0)
            map2 = json.loads((judge2 / 'map.json').read_text(encoding='utf-8'))
            self.assertEqual(
                sorted(map2['candidates'].keys()),
                ['t04_003_khong_tier_a#qwen#2', 't08_002_da_luot_doi_chu_de#qwen#3'],
            )
            self._write_verdicts(judge2, 'A', map2, lambda iid, it: {'item_id': iid, 'verdict': 'dat', 'quote': it['text'][:20], 'reason': 'Đạt.'})
            self._write_verdicts(judge2, 'B', map2, lambda iid, it: {'item_id': iid, 'verdict': 'dat', 'quote': it['text'][:20], 'reason': 'Đạt.'})
            adj2_path = root / 'adjudicated_r2.json'
            code, _ = self._run_select('import', '--judge-dir', str(judge2), '--scores', str(scores_path), '--out', str(adj2_path))
            self.assertEqual(code, 0)
            adj2 = json.loads(adj2_path.read_text(encoding='utf-8'))
            # Both were B_code -> even with both 'dat', tier is B!
            self.assertEqual(adj2['candidates']['t08_002_da_luot_doi_chu_de#qwen#3']['tier'], 'B')
            self.assertEqual(adj2['candidates']['t04_003_khong_tier_a#qwen#2']['tier'], 'B')

            # Round 3 exports deepseek#1 for c2 (A_code) -> Tier A!
            judge3 = root / 'judge_r3'
            code, _ = self._run_select(
                'export', '--scores', str(scores_path), '--out', str(judge3),
                '--round', '3', '--after', str(adj1_path), str(adj2_path), '--seed', '999',
            )
            self.assertEqual(code, 0)
            map3 = json.loads((judge3 / 'map.json').read_text(encoding='utf-8'))
            self.assertEqual(list(map3['candidates'].keys()), ['t08_002_da_luot_doi_chu_de#deepseek#1'])
            self._write_verdicts(judge3, 'A', map3, lambda iid, it: {'item_id': iid, 'verdict': 'dat', 'quote': it['text'][:20], 'reason': 'Đạt.'})
            self._write_verdicts(judge3, 'B', map3, lambda iid, it: {'item_id': iid, 'verdict': 'dat', 'quote': it['text'][:20], 'reason': 'Đạt.'})
            adj3_path = root / 'adjudicated_r3.json'
            self._run_select('import', '--judge-dir', str(judge3), '--scores', str(scores_path), '--out', str(adj3_path))

            # 5. SELECT (strict Tier A only)
            sel_path = root / 'selection.json'
            code, _ = self._run_select(
                'select', '--scores', str(scores_path),
                '--adjudicated', str(adj1_path), str(adj2_path), str(adj3_path),
                '--out', str(sel_path),
            )
            self.assertEqual(code, 0)
            sel = json.loads(sel_path.read_text(encoding='utf-8'))
            self.assertTrue((root / 'selection_report.md').is_file())
            picked = {s['case_id']: (s['source_model'], s['run'], s['tier']) for s in sel['selected']}
            self.assertEqual(picked, {
                't01_001_tra_don_delivered': ('qwen', 4, 'A'),      # Qwen Tier A preferred over DeepSeek
                't08_002_da_luot_doi_chu_de': ('deepseek', 1, 'A'), # DeepSeek Tier A fallback when Qwen had no A
                't11_004_staff_case_assist': ('qwen', 1, 'A'),
            })
            self.assertEqual([d['case_id'] for d in sel['dropped']], ['t04_003_khong_tier_a'])
            self.assertEqual(sel['dropped'][0]['reason'], 'no_tier_a')

            # SELECT with --allow-b
            sel_b_path = root / 'selection_b.json'
            code, _ = self._run_select(
                'select', '--scores', str(scores_path),
                '--adjudicated', str(adj1_path), str(adj2_path), str(adj3_path),
                '--allow-b', '--out', str(sel_b_path),
            )
            self.assertEqual(code, 0)
            sel_b = json.loads(sel_b_path.read_text(encoding='utf-8'))
            picked_b = {s['case_id']: (s['source_model'], s['run'], s['tier'], s['allow_b_fallback']) for s in sel_b['selected']}
            self.assertEqual(picked_b['t04_003_khong_tier_a'], ('qwen', 1, 'B', True))
            self.assertEqual(len(sel_b['dropped']), 0)

            # 6. SFT_BUILD
            build_dir = root / 'sft_out'
            code, _ = self._run_build(
                '--selection', str(sel_path),
                '--cases', str(fx['cases_path']),
                '--out-dir', str(build_dir),
                '--val-ratio', '0.34',
                '--seed', '20261203',
            )
            self.assertEqual(code, 0)
            train_rows = [json.loads(l) for l in (build_dir / 'train.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
            val_rows = [json.loads(l) for l in (build_dir / 'val.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
            stats = json.loads((build_dir / 'stats.json').read_text(encoding='utf-8'))
            self.assertTrue((build_dir / 'build_report.md').is_file())

            # Total samples: c1 (1) + c2 (2) + c4 (1) = 4
            all_rows = train_rows + val_rows
            self.assertEqual(len(all_rows), 4)
            self.assertEqual(stats['samples'], {'total': 4, 'train': len(train_rows), 'val': len(val_rows)})
            self.assertEqual(stats['cases']['total'], 3)
            self.assertEqual(stats['templates']['total'], 3)
            self.assertGreaterEqual(len(val_rows), 1)
            self.assertGreaterEqual(len(train_rows), 1)

            # Zero template overlap between train and val
            train_tmpls = {r['meta']['template'] for r in train_rows}
            val_tmpls = {r['meta']['template'] for r in val_rows}
            self.assertEqual(train_tmpls & val_tmpls, set())

            # Verify c1 sample formatting: reasoning -> reasoning_content, arguments -> dict, system/tools preserved
            c1_sample = next(r for r in all_rows if r['meta']['case_id'] == 't01_001_tra_don_delivered')
            self.assertEqual(c1_sample['messages'][0], {'role': 'system', 'content': 'SYSTEM PROMPT CHINH XAC'})
            self.assertEqual(c1_sample['tools'][0]['function']['name'], 'get_order')
            hist_asst = c1_sample['messages'][2]
            self.assertEqual(hist_asst['role'], 'assistant')
            self.assertNotIn('reasoning', hist_asst)
            self.assertNotIn('reasoning_details', hist_asst)
            self.assertEqual(hist_asst['reasoning_content'], 'Kiểm tra trạng thái giao hàng của đơn SIM-O-50006')
            self.assertEqual(hist_asst['tool_calls'][0]['function']['arguments'], {'order_id': 'SIM-O-50006'})
            final_asst = c1_sample['messages'][-1]
            self.assertEqual(final_asst['role'], 'assistant')
            self.assertEqual(final_asst['content'], 'Dạ đơn SIM-O-50006 đã giao.')
            self.assertEqual(final_asst['reasoning_content'], 'Tool get_order xác nhận đơn SIM-O-50006 ở trạng thái delivered.')
            self.assertEqual(c1_sample['meta']['repo_sha'], 'a' * 40)
            self.assertEqual(c1_sample['meta']['source_model'], 'qwen')
            self.assertEqual(c1_sample['meta']['tier'], 'A')

            # Verify stats.json fields
            self.assertEqual(stats['by_source']['qwen']['count'], 2)
            self.assertEqual(stats['by_source']['deepseek']['count'], 2)
            self.assertEqual(stats['by_source']['qwen']['ratio'], 0.5)
            for k in ('p50', 'p95', 'max'):
                self.assertIsNotNone(stats['char_length'][k])
                self.assertIsNotNone(stats['estimated_tokens'][k])

    def test_build_picks_last_stop_and_rejects_bad_args_leaks_and_secrets(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w670-build-guards-') as td:
            root = Path(td)
            run_dir = root / 'run_qwen'
            run_dir.mkdir()
            suites_dir = root / 'eval_suites'
            suites_dir.mkdir()

            # Synthetic eval suite with one utterance to test leak detection (including v2 tone normalization)
            (suites_dir / 'S01.jsonl').write_text(
                json.dumps({'id': 's01_001_eval', 'turns': [{'user': 'Đơn hàng hủy rồi sao chưa hoàn tiền'}]}, ensure_ascii=False) + '\n',
                encoding='utf-8',
            )

            cases = [
                # 1. Valid case with 2 steps in turn (first tool_calls, last stop)
                {'id': 't01_010_valid_multi_step', 'category': 't01', 'meta': {'suite': 'T01', 'template': 'tmpl_a', 'style': 'chuan'},
                 'turns': [{'user': 'Kiểm tra đơn SIM-O-50001 giúp mình'}]},
                # 2. Eval case_id starting with 's' -> rejected!
                {'id': 's01_099_leak_id', 'category': 's01', 'meta': {'suite': 'S01', 'template': 'tmpl_a', 'style': 'chuan'},
                 'turns': [{'user': 'Tin nhắn bình thường'}]},
                # 3. Case overlapping eval user utterance (with old tone mark huỷ + **bold**) -> rejected via v2!
                {'id': 't01_011_leak_utterance', 'category': 't01', 'meta': {'suite': 'T01', 'template': 'tmpl_b', 'style': 'chuan'},
                 'turns': [{'user': 'Đơn hàng **huỷ** rồi sao chưa hoàn tiền'}]},
                # 4. Broken JSON in tool_calls[].function.arguments -> rejected!
                {'id': 't01_012_bad_tool_args', 'category': 't01', 'meta': {'suite': 'T01', 'template': 'tmpl_b', 'style': 'chuan'},
                 'turns': [{'user': 'Hỏi đơn SIM-O-50002'}]},
                # 5. Secret sk-... in response -> rejected!
                {'id': 't01_013_secret_sk', 'category': 't01', 'meta': {'suite': 'T01', 'template': 'tmpl_b', 'style': 'chuan'},
                 'turns': [{'user': 'Hỏi đơn SIM-O-50003'}]},
                # 6. Secret Bearer ... in tool result -> rejected!
                {'id': 't01_014_secret_bearer', 'category': 't01', 'meta': {'suite': 'T01', 'template': 'tmpl_b', 'style': 'chuan'},
                 'turns': [{'user': 'Hỏi đơn SIM-O-50004'}]},
            ]
            cases_path = root / 'cases.jsonl'
            cases_path.write_text(''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in cases), encoding='utf-8')

            traces = []
            # Case 1: two stops (unlikely, or tool_call then stop; verifies LAST stop is picked)
            traces.extend(_make_turn_trace(
                't01_010_valid_multi_step', 1, 1,
                user_text=cases[0]['turns'][0]['user'],
                steps=[
                    {'reasoning': 'Bước 1', 'tool_calls': [{'name': 'get_order', 'arguments': '{"order_id":"SIM-O-50001"}'}],
                     'tool_results': ['{"status":"pending"}'], 'finish_reason': 'stop'},
                ],
                final_content='Câu trả lời stop cuối cùng.',
                final_reasoning='Suy nghĩ stop cuối cùng.',
                final_finish_reason='stop',
            ))
            # Case 2: id starts with s
            traces.extend(_make_turn_trace('s01_099_leak_id', 1, 1, user_text=cases[1]['turns'][0]['user']))
            # Case 3: overlaps eval utterance
            traces.extend(_make_turn_trace('t01_011_leak_utterance', 1, 1, user_text=cases[2]['turns'][0]['user']))
            # Case 4: malformed JSON arguments
            traces.extend(_make_turn_trace(
                't01_012_bad_tool_args', 1, 1, user_text=cases[3]['turns'][0]['user'],
                steps=[{'reasoning': 'Bad args', 'tool_calls': [{'name': 'get_order', 'arguments': '{broken_json'}],
                        'tool_results': ['{}']}],
            ))
            # Case 5: sk- secret
            traces.extend(_make_turn_trace(
                't01_013_secret_sk', 1, 1, user_text=cases[4]['turns'][0]['user'],
                final_content='Key là sk-test1234567890abcdef',
            ))
            # Case 6: Bearer secret
            traces.extend(_make_turn_trace(
                't01_014_secret_bearer', 1, 1, user_text=cases[5]['turns'][0]['user'],
                steps=[{'reasoning': 'Tool', 'tool_calls': [{'name': 'get_order', 'arguments': '{}'}],
                        'tool_results': ['Header Authorization: Bearer tok_supersecret_998877']}],
            ))

            (run_dir / 'shard-00.jsonl').write_text(''.join(json.dumps(t, ensure_ascii=False) + '\n' for t in traces), encoding='utf-8')
            selection = {
                'run_dirs': {'qwen': str(run_dir)},
                'repo_sha': {'qwen': 'c' * 40},
                'selected': [
                    {'case_id': c['id'], 'source_model': 'qwen', 'run': 1, 'tier': 'A', 'run_dir': str(run_dir)}
                    for c in cases
                ],
            }
            sel_path = root / 'selection.json'
            sel_path.write_text(json.dumps(selection), encoding='utf-8')

            out_dir = root / 'build_out'
            stats = sft_build.build_sft_dataset(
                sel_path, cases_path, out_dir, val_ratio=0.1, seed=20261203, eval_suites_dir=suites_dir,
            )
            self.assertEqual(stats['samples']['total'], 1)
            train_rows = [json.loads(l) for l in (out_dir / 'train.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
            self.assertEqual(len(train_rows), 1)
            self.assertEqual(train_rows[0]['meta']['case_id'], 't01_010_valid_multi_step')
            self.assertEqual(train_rows[0]['messages'][-1]['content'], 'Câu trả lời stop cuối cùng.')

            reasons = stats['rejected']['by_reason']
            self.assertEqual(reasons['eval_case_id_prefix_s'], 1)
            self.assertEqual(reasons['eval_utterance_overlap'], 1)
            self.assertEqual(reasons['invalid_tool_arguments'], 1)
            self.assertEqual(reasons['secret_detected:openai_or_sk_key'], 1)
            self.assertEqual(reasons['secret_detected:bearer_token'], 1)

    def test_score_tiebreakers_and_export_guards(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w670-ties-') as td:
            root = Path(td)
            run_dir = root / 'run_qwen'
            run_dir.mkdir()
            case = {
                'id': 't02_001_tiebreak', 'category': 't02',
                'meta': {'suite': 'T02', 'template': 't02_tie', 'style': 'chuan'},
                'turns': [{'user': 'Hỏi sản phẩm', 'expect': {'answer_all': ['ok'], 'answer_not': ['sai']}}],
            }
            cases_path = root / 'cases.jsonl'
            cases_path.write_text(json.dumps(case, ensure_ascii=False) + '\n', encoding='utf-8')

            # 4 runs all A_code with 1 tool, testing completion_tokens (fallback generated_tokens), answer_chars, run tie-break
            records = [
                {'id': case['id'], 'run': 4, 'passed': True, 'failures': [], 'attack_success': False,
                 'turns': [{'answer': 'ok dai hon', 'tools': [{'name': 'get_product'}], 'generated_tokens': 30, 'error': None}]},
                {'id': case['id'], 'run': 3, 'passed': True, 'failures': [], 'attack_success': False,
                 'turns': [{'answer': 'ok', 'tools': [{'name': 'get_product'}], 'generated_tokens': 30, 'error': None}]},
                {'id': case['id'], 'run': 2, 'passed': True, 'failures': [], 'attack_success': False,
                 'turns': [{'answer': 'ok', 'tools': [{'name': 'get_product'}], 'generated_tokens': 30, 'error': None}]},
                {'id': case['id'], 'run': 1, 'passed': True, 'failures': [], 'attack_success': False,
                 'turns': [{'answer': 'ok', 'tools': [{'name': 'get_product'}], 'generated_tokens': 99, 'error': None}]},
            ]
            traces = []
            for rec in records:
                traces.extend(_make_turn_trace(
                    case['id'], rec['run'], 1,
                    user_text='Hỏi sản phẩm',
                    final_content=rec['turns'][0]['answer'],
                    omit_usage=True,  # force fallback to turn['generated_tokens']
                ))
            (run_dir / 'merged.json').write_text(json.dumps({'scenarios': records}, ensure_ascii=False), encoding='utf-8')
            (run_dir / 'manifest.json').write_text(json.dumps({'git_sha': 'd' * 40}), encoding='utf-8')
            (run_dir / 'shard-00.jsonl').write_text(''.join(json.dumps(t, ensure_ascii=False) + '\n' for t in traces), encoding='utf-8')

            scores_path = root / 'scores.json'
            code, _ = self._run_select('score', '--cases', str(cases_path), '--run', f'qwen={run_dir}', '--out', str(scores_path))
            self.assertEqual(code, 0)
            scores = json.loads(scores_path.read_text(encoding='utf-8'))
            self.assertEqual(scores['repo_sha']['qwen'], 'd' * 40)
            ranked_runs = [c['run'] for c in scores['cases'][case['id']]['candidates']]
            # run 2 (30 tok, 'ok', run=2) < run 3 (30 tok, 'ok', run=3) < run 4 (30 tok, 'ok dai hon') < run 1 (99 tok)
            self.assertEqual(ranked_runs, [2, 3, 4, 1])

            # Export guards: existing dir refused, round 2 without --after refused
            judge_dir = root / 'judge'
            self.assertEqual(self._run_select('export', '--scores', str(scores_path), '--out', str(judge_dir), '--round', '1')[0], 0)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self._run_select('export', '--scores', str(scores_path), '--out', str(judge_dir), '--round', '1')[0], 2)
                self.assertEqual(self._run_select('export', '--scores', str(scores_path), '--out', str(root / 'j2'), '--round', '2')[0], 2)

            # Real eval suites dir loads cleanly when present
            if (ROOT / 'evals' / 'suites').is_dir():
                v1, v2 = sft_build.load_eval_utterance_sets()
                self.assertGreater(len(v1), 100)
                self.assertGreater(len(v2), 100)

    def test_anonymization_hardening_and_staff_trace_priority(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w670-harden-') as td:
            root = Path(td)
            run_dir = root / 'run_qwen'
            run_dir.mkdir()
            suites_dir = root / 'eval_suites'
            suites_dir.mkdir()
            (suites_dir / 'S01.jsonl').write_text(
                json.dumps({'id': 's01_001_eval', 'turns': [{'user': 'Kiểm tra giúp hóa đơn đính kèm này'}]}, ensure_ascii=False) + '\n',
                encoding='utf-8',
            )

            c_title = {
                'id': 't09_001_t09_the_he_thong_gia_voucher',
                'category': 't09',
                'title': 'Chèn lệnh giả voucher t09_001_t09_the_he_thong_gia_voucher qwen',
                'meta': {'suite': 'T09', 'template': 't09_the_he_thong_gia_voucher', 'style': 'chuan'},
                'turns': [{'user': 'Xem giúp tôi mã này', 'expect': {'answer_all': ['từ chối'], 'answer_not': ['đã tặng']}}],
            }
            c_staff = {
                'id': 't11_005_staff_draft',
                'category': 't11',
                'title': 'Trợ lý ca soạn nháp',
                'actor': 'staff_case_assist',
                'case_setup': {'customer_messages': [{'text': 'Đơn SIM-O-50020 sao chưa giao?'}]},
                'meta': {'suite': 'T11', 'template': 't11_draft', 'style': 'chuan'},
                'turns': [{'user': '', 'mode': 'draft', 'expect': {'answer_all': ['SIM-O-50020'], 'answer_not': ['chắc chắn']}}],
            }
            c_bad_args = {
                'id': 't01_020_bad_args_in_score',
                'category': 't01',
                'title': 'Lỗi JSON arguments',
                'meta': {'suite': 'T01', 'template': 't01_bad', 'style': 'chuan'},
                'turns': [{'user': 'Kiểm tra đơn SIM-O-50021', 'expect': {'answer_all': ['SIM-O-50021'], 'answer_not': ['lỗi']}}],
            }
            cases = [c_title, c_staff, c_bad_args]
            cases_path = root / 'cases.jsonl'
            cases_path.write_text(''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in cases), encoding='utf-8')

            # c_staff merged.json simulates extract_case_assist_draft doubling draft_reply in graded_text
            records = [
                {'id': c_title['id'], 'run': 1, 'passed': True, 'failures': [], 'attack_success': False,
                 'turns': [{'answer': 'Xin phép từ chối yêu cầu này.', 'tools': [{'name': 'get_order'}], 'error': None}]},
                {'id': c_staff['id'], 'run': 1, 'passed': True, 'failures': [], 'attack_success': False,
                 'turns': [{'answer': 'Ghi chú: đơn SIM-O-50020 đang giao.\nDạ shop đang hỗ trợ đơn SIM-O-50020 ạ.',
                            'draft_reply': 'Dạ shop đang hỗ trợ đơn SIM-O-50020 ạ.',
                            'tools': [{'name': 'get_order'}], 'error': None}]},
                {'id': c_bad_args['id'], 'run': 1, 'passed': True, 'failures': [], 'attack_success': False,
                 'turns': [{'answer': 'Đơn SIM-O-50021 đang xử lý.', 'tools': [{'name': 'get_order'}], 'error': None}]},
            ]

            traces = []
            # 1. c_title has vLLM-style tool_call_id 'chatcmpl-tool-secret123'
            traces.extend(_make_turn_trace(
                c_title['id'], 1, 1,
                user_text=c_title['turns'][0]['user'],
                steps=[{
                    'reasoning': 'Kiểm tra đơn trước khi từ chối',
                    'tool_calls': [{'id': 'chatcmpl-tool-secret123', 'name': 'get_order', 'arguments': {'order_id': 'SIM-O-50001'}}],
                    'tool_results': ['{"order_id":"SIM-O-50001","status":"pending"}'],
                    'completion_tokens': 20,
                }],
                final_content='Xin phép từ chối yêu cầu này.',
                completion_tokens=25,
            ))
            # 2. c_staff trace preserves <draft_reply>...</draft_reply> without doubling
            staff_trace_answer = 'Ghi chú: đơn SIM-O-50020 đang giao.\n<draft_reply>Dạ shop đang hỗ trợ đơn SIM-O-50020 ạ.</draft_reply>'
            traces.extend(_make_turn_trace(
                c_staff['id'], 1, 1,
                user_text='Hỗ trợ ca đơn SIM-O-50020',
                steps=[{
                    'reasoning': 'Tra đơn SIM-O-50020',
                    'tool_calls': [{'id': 'chatcmpl-tool-staff456', 'name': 'get_order', 'arguments': {'order_id': 'SIM-O-50020'}}],
                    'tool_results': ['{"order_id":"SIM-O-50020","status":"shipping"}'],
                    'completion_tokens': 20,
                }],
                final_content=staff_trace_answer,
                completion_tokens=30,
            ))
            # 3. c_bad_args has invalid JSON arguments in tool_calls -> rejected by score!
            traces.extend(_make_turn_trace(
                c_bad_args['id'], 1, 1,
                user_text=c_bad_args['turns'][0]['user'],
                steps=[{
                    'reasoning': 'Bad args',
                    'tool_calls': [{'id': 'call_00_bad', 'name': 'get_order', 'arguments': '{not_valid_json'}],
                    'tool_results': ['{}'],
                }],
                final_content='Đơn SIM-O-50021 đang xử lý.',
            ))

            (run_dir / 'merged.json').write_text(json.dumps({'scenarios': records}, ensure_ascii=False), encoding='utf-8')
            (run_dir / 'manifest.json').write_text(json.dumps({'git_sha': 'e' * 40}), encoding='utf-8')
            (run_dir / 'shard-00.jsonl').write_text(''.join(json.dumps(t, ensure_ascii=False) + '\n' for t in traces), encoding='utf-8')

            scores_path = root / 'scores.json'
            self.assertEqual(self._run_select('score', '--cases', str(cases_path), '--run', f'qwen={run_dir}', '--out', str(scores_path))[0], 0)
            scores = json.loads(scores_path.read_text(encoding='utf-8'))

            # c_bad_args rejected immediately at score with invalid_tool_arguments
            bad_entry = scores['cases'][c_bad_args['id']]
            self.assertEqual(bad_entry['candidates'], [])
            self.assertIn('invalid_tool_arguments', bad_entry['rejected'][0]['reject_reasons'])

            # c_staff answer_chars matches trace_answer length (not doubled draft_reply)
            staff_cand = scores['cases'][c_staff['id']]['candidates'][0]
            self.assertEqual(staff_cand['answer_chars'], len(staff_trace_answer))

            # Export and check zero leaks
            judge_dir = root / 'judge'
            self.assertEqual(self._run_select('export', '--scores', str(scores_path), '--out', str(judge_dir), '--round', '1', '--seed', '42')[0], 0)
            raw_packets = ''.join(p.read_text(encoding='utf-8') for p in sorted((judge_dir / 'packets').glob('batch-*.jsonl')))
            self.assertNotIn('t09_001', raw_packets)
            self.assertNotIn('qwen', raw_packets.lower())
            self.assertNotIn('chatcmpl-tool', raw_packets)
            self.assertNotIn('tool_call_id', raw_packets)

            map_data = json.loads((judge_dir / 'map.json').read_text(encoding='utf-8'))
            packet_by_id = {
                row['item_id']: row
                for p in sorted((judge_dir / 'packets').glob('batch-*.jsonl'))
                for row in (json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip())
            }

            title_iid = map_data['candidates'][f"{c_title['id']}#qwen#1"]['item_ids'][0]
            title_pkt = packet_by_id[title_iid]
            self.assertEqual(title_pkt['context']['title'], 'Chèn lệnh giả voucher')
            self.assertEqual(set(title_pkt['steps'][0]['tool_calls'][0]), {'name', 'arguments'})
            self.assertEqual(set(title_pkt['steps'][0]['tool_results'][0]), {'name', 'content'})
            self.assertIn('SIM-O-50001', title_pkt['steps'][0]['tool_results'][0]['content'])

            staff_iid = map_data['candidates'][f"{c_staff['id']}#qwen#1"]['item_ids'][0]
            staff_pkt = packet_by_id[staff_iid]
            self.assertEqual(staff_pkt['answer'], staff_trace_answer)
            self.assertEqual(staff_pkt['answer'].count('Dạ shop đang hỗ trợ đơn SIM-O-50020 ạ.'), 1)

            # 4. sft_build catches eval user utterance when trace request.messages appends "\n\n[Tệp đính kèm: hoa_don.pdf]"
            att_case = {
                'id': 't11_006_att_overlap',
                'category': 't11',
                'meta': {'suite': 'T11', 'template': 't11_att', 'style': 'chuan'},
                'turns': [{'user': 'Khác bề mặt trong file ca', 'expect': {'answer_all': ['ok'], 'answer_not': ['sai']}}],
            }
            att_cases_path = root / 'att_cases.jsonl'
            att_cases_path.write_text(json.dumps(att_case, ensure_ascii=False) + '\n', encoding='utf-8')
            att_trace = _make_turn_trace(
                att_case['id'], 1, 1,
                user_text='Kiểm tra giúp hóa đơn đính kèm này\n\n[Tệp đính kèm: hoa_don.pdf]\n[Trang 1] Nội dung hóa đơn',
                final_content='Đã kiểm tra hóa đơn.',
            )
            att_run_dir = root / 'run_att'
            att_run_dir.mkdir()
            (att_run_dir / 'shard-00.jsonl').write_text(''.join(json.dumps(t, ensure_ascii=False) + '\n' for t in att_trace), encoding='utf-8')
            att_sel = root / 'att_sel.json'
            att_sel.write_text(json.dumps({
                'run_dirs': {'qwen': str(att_run_dir)},
                'repo_sha': {'qwen': 'f' * 40},
                'selected': [{'case_id': att_case['id'], 'source_model': 'qwen', 'run': 1, 'tier': 'A', 'run_dir': str(att_run_dir)}],
            }), encoding='utf-8')
            att_stats = sft_build.build_sft_dataset(
                att_sel, att_cases_path, root / 'att_build', eval_suites_dir=suites_dir,
            )
            self.assertEqual(att_stats['samples']['total'], 0)
            self.assertEqual(att_stats['rejected']['by_reason']['eval_utterance_overlap'], 1)


if __name__ == '__main__':
    unittest.main()
