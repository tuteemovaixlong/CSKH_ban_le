"""Kiểm offline trace_request_sha256 trong nhật ký proxy gợi ý."""
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if not (Path(__file__).resolve().parents[1] / 'scripts/sft_hint_proxy.py').is_file():
    raise unittest.SkipTest('Công cụ SFT không nằm trong gói Colab ứng dụng')

from scripts.eval_telemetry import safe_payload
from scripts.sft_hint_proxy import HintIndex, START, make_server, sha256


def fake_hint(**key):
    text = hashlib.sha256(json.dumps(key, sort_keys=True).encode('utf-8')).hexdigest()
    return {**key, 'hint': text, 'sha256': sha256(text.encode('utf-8'))}


class ProxyTraceHashTests(unittest.TestCase):
    def test_trace_request_sha256_redacted_normal_invalid_and_other_routes(self):
        user_redacted = 'Xem http://x.test/a?order=1 kèm Authorization'
        user_normal = 'Tin nhắn bình thường không có URL hay khóa'
        sys_prompt = 'System prompt giả lập'
        cases = [
            {'id': 'c_redacted', 'meta': {'template': 'tpl'}, 'turns': [{'user': user_redacted}]},
            {'id': 'c_normal', 'meta': {'template': 'tpl'}, 'turns': [{'user': user_normal}]},
        ]
        hint_row = fake_hint(case_id='c_redacted', turn=1)
        captured = []

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                captured.append(('GET', self.path, b''))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'ok')

            def do_POST(self):
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length)
                captured.append(('POST', self.path, body))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')

        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / 'hint_log.jsonl'
            upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
            proxy = make_server(
                ('127.0.0.1', 0),
                f'http://127.0.0.1:{upstream.server_port}',
                HintIndex(cases, [hint_row]),
                log_path,
            )
            for server in (upstream, proxy):
                threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{proxy.server_port}'
            headers = {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer TEST_SECRET_TOKEN',
                'X-API-Key': 'TEST_API_KEY',
            }
            try:
                # 1. Payload có URL chứa '?' và chữ Authorization (được chèn gợi ý)
                redacted_payload = {
                    'messages': [
                        {'role': 'system', 'content': sys_prompt},
                        {'role': 'user', 'content': user_redacted},
                    ],
                    'max_tokens': 256,
                }
                redacted_raw = json.dumps(redacted_payload, ensure_ascii=False).encode('utf-8')
                req1 = urllib.request.Request(
                    base + '/v1/chat/completions', data=redacted_raw, headers=headers
                )
                with urllib.request.urlopen(req1, timeout=5) as resp:
                    self.assertEqual(resp.read(), b'{}')

                # 2. Payload có URL chứa '?' và chữ Authorization (không chèn gợi ý)
                unhinted_redacted_payload = {
                    'messages': [
                        {'role': 'system', 'content': sys_prompt},
                        {'role': 'user', 'content': 'Khác: http://x.test/a?order=1 Authorization'},
                    ],
                }
                unhinted_redacted_raw = json.dumps(
                    unhinted_redacted_payload, ensure_ascii=False
                ).encode('utf-8')
                req2 = urllib.request.Request(
                    base + '/v1/chat/completions', data=unhinted_redacted_raw, headers=headers
                )
                with urllib.request.urlopen(req2, timeout=5) as resp:
                    self.assertEqual(resp.read(), b'{}')

                # 3. Payload thường (không kích hoạt safe_payload redaction)
                normal_payload = {
                    'messages': [
                        {'role': 'system', 'content': sys_prompt},
                        {'role': 'user', 'content': user_normal},
                    ],
                    'max_tokens': 256,
                }
                normal_raw = json.dumps(normal_payload, ensure_ascii=False).encode('utf-8')
                req3 = urllib.request.Request(
                    base + '/v1/chat/completions', data=normal_raw, headers=headers
                )
                with urllib.request.urlopen(req3, timeout=5) as resp:
                    self.assertEqual(resp.read(), b'{}')

                # 4. Route ngoài /v1/chat/completions
                with urllib.request.urlopen(
                    urllib.request.Request(base + '/health', headers=headers), timeout=5
                ) as resp:
                    self.assertEqual(resp.read(), b'ok')

                # 5. Thân không phải JSON -> trả 400 và không thêm dòng nhật ký
                req_bad = urllib.request.Request(
                    base + '/v1/chat/completions', data=b'{not-json', headers=headers
                )
                with self.assertRaises(urllib.error.HTTPError) as err:
                    urllib.request.urlopen(req_bad, timeout=5)
                self.assertEqual(err.exception.code, 400)

                raw_log = log_path.read_text(encoding='utf-8')
                rows = [json.loads(line) for line in raw_log.splitlines()]
                self.assertEqual(len(rows), 4)

                # Kiểm dòng 1 (hinted + redacted): trace_request_sha256 khớp safe_payload(gốc), khác request_sha256
                expected_trace_1 = sha256(
                    json.dumps(safe_payload(redacted_payload), ensure_ascii=False).encode('utf-8')
                )
                self.assertTrue(rows[0]['hinted'])
                self.assertEqual(rows[0]['request_sha256'], sha256(redacted_raw))
                self.assertEqual(rows[0]['trace_request_sha256'], expected_trace_1)
                self.assertNotEqual(rows[0]['trace_request_sha256'], rows[0]['request_sha256'])
                # Upstream thực tế nhận payload đã chèn gợi ý
                self.assertIn(START, captured[0][2].decode('utf-8'))

                # Kiểm dòng 2 (unhinted + redacted)
                expected_trace_2 = sha256(
                    json.dumps(safe_payload(unhinted_redacted_payload), ensure_ascii=False).encode('utf-8')
                )
                self.assertFalse(rows[1]['hinted'])
                self.assertEqual(rows[1]['request_sha256'], sha256(unhinted_redacted_raw))
                self.assertEqual(rows[1]['trace_request_sha256'], expected_trace_2)
                self.assertNotEqual(rows[1]['trace_request_sha256'], rows[1]['request_sha256'])

                # Kiểm dòng 3 (payload thường): hai băm bằng nhau
                self.assertEqual(rows[2]['request_sha256'], sha256(normal_raw))
                self.assertEqual(rows[2]['trace_request_sha256'], rows[2]['request_sha256'])

                # Kiểm dòng 4 (GET /health): không có trace_request_sha256
                self.assertNotIn('trace_request_sha256', rows[3])
                self.assertEqual(len(rows[3]['request_sha256']), 64)

                # Không rò rỉ nội dung lời nhắc, URL, header hay khóa vào nhật ký
                for forbidden in (
                    sys_prompt,
                    user_redacted,
                    user_normal,
                    'http://x.test',
                    'Authorization',
                    'Bearer',
                    'TEST_SECRET_TOKEN',
                    'TEST_API_KEY',
                    'X-API-Key',
                    hint_row['hint'],
                    'messages',
                ):
                    self.assertNotIn(forbidden, raw_log)
            finally:
                proxy.shutdown()
                upstream.shutdown()
                proxy.server_close()
                upstream.server_close()


if __name__ == '__main__':
    unittest.main()
