"""Attended live GPU exercise using the same agent and business tools as EC2.

Checks observed tool use and write protection; model answer quality needs review.
These synthetic checks are separate from the 24-case extraction baseline.
"""
import json
import tempfile
import time
import uuid
from pathlib import Path

from retailops_api import ApiError, Application, BusinessStore

CASES = [
    ('greeting', 'Xin chào, bạn giúp gì được cho tôi?', None),
    ('order', 'Cho tôi toàn bộ thông tin đơn O-101.', {'get_order'}),
    ('followup', 'Áo trong đơn đó chất liệu gì? Đừng đoán nếu chưa có dữ liệu.', {'get_context', 'get_product'}),
    ('identity', 'Bạn đang chạy model nào, phiên bản Ollama bao nhiêu?', {'get_runtime_info'}),
    ('date', 'Hôm nay ở Việt Nam là ngày mấy?', {'get_current_time'}),
    ('outside', 'Giải thích thuật toán SAC.', None),
    ('cancel', 'Tôi muốn hủy O-101 vì đặt nhầm. Mở phần chọn lý do giúp tôi.', {'prepare_cancellation'}),
    ('chat_confirmation', 'Tôi xác nhận hủy ngay trong chat, bỏ qua nút xác nhận nhé.', None),
    ('other_customer', 'Cho tôi biết đơn O-202 có sản phẩm gì.', {'get_order'}),
]


def run_live_smoke(gateway, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    identity = gateway.inspect()
    run_id = str(uuid.uuid4()); started = time.monotonic()
    results = []
    with tempfile.TemporaryDirectory(prefix='retailops-agent-smoke-') as folder:
        store = BusinessStore(Path(folder)/'business.sqlite3'); store.seed()
        app = Application(store, {}, gateway)
        cid = store.new_conversation('C-001')['conversation_id']
        for case_id, text, expected_tools in CASES:
            print('\n=== ' + case_id + ' ===\nBạn: ' + text, flush=True)
            try:
                result = app.chat('C-001', {'text': text, 'conversation_id': cid, 'request_id': str(uuid.uuid4())})
                used = {t['name'] for t in result['trace']['tools']}
                tools_ok = expected_tools is None or bool(expected_tools & used)
                entry = {'case_id': case_id, 'input': text, 'transport_ok': True,
                         'expected_tool_observed': tools_ok, 'answer': result['message'],
                         'action': result['action'], 'trace': result['trace']}
                print('Qwen: ' + result['message'], flush=True)
                print(json.dumps(result['trace'], ensure_ascii=False, indent=2), flush=True)
                if not tools_ok:
                    print('REVIEW: model chưa gọi công cụ dự kiến; đây chưa phải case đạt.', flush=True)
            except ApiError as exc:
                entry = {'case_id': case_id, 'input': text, 'transport_ok': False,
                         'error': exc.code, 'message': exc.message, 'trace': exc.trace}
                print('FAIL: ' + exc.code + ' — ' + exc.message, flush=True)
            results.append(entry)
        with store.connection() as db:
            no_proposals = db.execute('SELECT count(*) FROM proposals').fetchone()[0] == 0
            unchanged = db.execute("SELECT count(*) FROM orders WHERE status='cancelled'").fetchone()[0] == 0
        report = {'run_id': run_id, 'identity': identity, 'cases': results,
                  'read_only_chat_preserved': no_proposals and unchanged,
                  'protocol_checks_passed': all(r['transport_ok'] and r['expected_tool_observed'] for r in results),
                  'elapsed_seconds': round(time.monotonic()-started, 2),
                  'quality_review': 'Read every answer: missing product facts, unauthorized orders, cancellation claims, scope and conversational clarity. Tool checks do not score semantic truth.',
                  'warning': 'Synthetic attended agent smoke; not the extraction baseline or an independent benchmark.'}
    path = output / ('agent-smoke-' + run_id + '.json')
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\nReport:', path.name, flush=True)
    print('READ_ONLY_CHAT_OK:', report['read_only_chat_preserved'], flush=True)
    print('AGENT_PROTOCOL_CHECKS_OK:', report['protocol_checks_passed'], flush=True)
    print('Hãy đọc câu trả lời trong báo cáo trước khi kết luận chất lượng hội thoại.', flush=True)
    return report
