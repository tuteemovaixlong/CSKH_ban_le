"""Unit tests for W6.7.0 Part A: SFT fixture, cases generator, and utterance tooling.

Covers:
- Fixture sha256, counts, zero collision with standard dataset
- Tenant provisioning for sft_v1, standard, late_voucher_issued (existing unchanged)
- validate_train_case and validate_train_set contracts
- Case generation on a small pilot (e.g. 24 cases) and 100% check pass rate
- Utterance validation rules (must_include, must_not_include, khong_dau, eval deduplication)
- Peak-hour restriction and resume-from-cache behavior with mock client
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

from scripts.sft_dataset import sft_v1_demo_ids, validate_train_case, validate_train_set
from scripts.sft_cases import generate_cases, check_cases
from scripts.sft_utterances import (
    DeepSeekClient,
    fill_utterances,
    is_peak_hour,
    jaccard_5gram,
    max_common_substring_len,
    validate_utterance,
)
from scripts.run_agent_scenarios import _modules, _provision_demo_template, FIXTURES, load_dataset


class TestW670SftFixtureCases(unittest.TestCase):
    def test_fixture_metadata_and_integrity(self) -> None:
        jsonl_path = ROOT / 'data' / 'demo_events' / 'store_events_sft_v1.jsonl'
        meta_path = ROOT / 'data' / 'demo_events' / 'store_events_sft_v1.meta.json'
        std_path = ROOT / 'data' / 'demo_events' / 'store_events.jsonl'

        self.assertTrue(jsonl_path.is_file(), "Missing store_events_sft_v1.jsonl")
        self.assertTrue(meta_path.is_file(), "Missing store_events_sft_v1.meta.json")

        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        content = jsonl_path.read_bytes()
        actual_sha = hashlib.sha256(content).hexdigest()

        self.assertEqual(meta['sha256'], actual_sha, "SHA-256 does not match metadata")
        self.assertEqual(meta['total_events'], 2011)
        self.assertEqual(meta['total_orders'], 129)
        self.assertEqual(meta['total_customers'], 92)

        sft_customers, sft_orders, _ = sft_v1_demo_ids()
        self.assertEqual(len(sft_orders), 129)
        self.assertEqual(len(sft_customers), 92)

        # Verify 0 overlap with standard fixture
        std_orders: set[str] = set()
        std_customers: set[str] = set()
        if std_path.is_file():
            for line in std_path.read_text(encoding='utf-8').splitlines():
                if line.strip():
                    ev = json.loads(line)
                    data = ev.get('data', {})
                    if data.get('external_order_id'):
                        std_orders.add(data['external_order_id'])
                    if data.get('external_customer_id'):
                        std_customers.add(data['external_customer_id'])

        self.assertEqual(len(sft_orders & std_orders), 0, "Colliding orders between sft_v1 and standard")
        self.assertEqual(len(sft_customers & std_customers), 0, "Colliding customers between sft_v1 and standard")

    def test_provision_templates_and_runner_fixtures(self) -> None:
        self.assertIn('sft_v1', FIXTURES)
        self.assertIn('standard', FIXTURES)
        self.assertIn('late_voucher_issued', FIXTURES)

        Application, ApiError, PersistentSessions, KnowledgeRepository, AgentError = _modules()

        # sft_v1 provisioning
        p_sft = _provision_demo_template('sft_v1', PersistentSessions)
        sess_sft = PersistentSessions(p_sft, data_mode='persistent-demo')
        store_sft = sess_sft.business_store('shop-scenarios')
        with store_sft.connection() as db:
            orders_cnt_sft = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        self.assertEqual(orders_cnt_sft, 129)

        # standard provisioning unchanged (128 orders)
        p_std = _provision_demo_template('standard', PersistentSessions)
        sess_std = PersistentSessions(p_std, data_mode='persistent-demo')
        store_std = sess_std.business_store('shop-scenarios')
        with store_std.connection() as db:
            orders_cnt_std = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        self.assertEqual(orders_cnt_std, 128)

    def test_validate_train_case_contract(self) -> None:
        # A valid training case
        valid_case = {
            'id': 't01_001_tra_don_delivered',
            'category': 't01',
            'title': 'Tra cứu đơn hàng delivered',
            'fixture': 'sft_v1',
            'customer': 'SIM-C-5001',
            'meta': {
                'suite': 'T01',
                'split': 'train',
                'style': 'chuan',
                'origin': 'sinh_sft',
                'template': 't01_tra_don_delivered',
                'source_note': 'Test valid case',
                'vn_context': [],
            },
            'turns': [
                {
                    'user': 'Kiểm tra đơn SIM-O-50006',
                    'expect': {
                        'tools_called': ['get_order'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_all': ['SIM-O-50006'],
                        'answer_any': [['giao', 'đơn']],
                        'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': 'SIM-O-50006'}}]},
                        {'say': 'Dạ đơn hàng SIM-O-50006 đã giao thành công.'}
                    ]
                }
            ],
            'final_state': {
                'orders': {'SIM-O-50006': 'delivered'},
                'rows': {'order_action_requests': 0}
            }
        }
        res = validate_train_case(valid_case)
        self.assertEqual(res['id'], 't01_001_tra_don_delivered')

        # Invalid id prefix
        bad_id = dict(valid_case, id='x01_001_invalid_id')
        with self.assertRaises(AssertionError):
            validate_train_case(bad_id)

        # Invalid split (!= train)
        bad_split = json.loads(json.dumps(valid_case))
        bad_split['meta']['split'] = 'dev'
        with self.assertRaises(AssertionError):
            validate_train_case(bad_split)

        # Invalid origin (!= sinh_sft)
        bad_origin = json.loads(json.dumps(valid_case))
        bad_origin['meta']['origin'] = 'mo_phong'
        with self.assertRaises(AssertionError):
            validate_train_case(bad_origin)

        # Invalid fixture (!= sft_v1)
        bad_fixture = json.loads(json.dumps(valid_case))
        bad_fixture['fixture'] = 'standard'
        with self.assertRaises(AssertionError):
            validate_train_case(bad_fixture)

        # Customer not in sft_v1
        bad_cust = json.loads(json.dumps(valid_case))
        bad_cust['customer'] = 'SIM-C-0070'  # standard customer, not sft_v1
        with self.assertRaises(AssertionError):
            validate_train_case(bad_cust)

        # load_dataset branch check
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', suffix='.jsonl', delete=False) as tf:
            tf.write(json.dumps(valid_case, ensure_ascii=False) + '\n')
            temp_path = tf.name
        try:
            loaded = load_dataset(temp_path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]['id'], 't01_001_tra_don_delivered')
        finally:
            os.remove(temp_path)

    def test_sft_cases_generator_and_pilot_check(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-sft-cases-') as td:
            cases, briefs, rep = generate_cases(td, pilot=24, seed=20261202)
            self.assertEqual(len(cases), 24)
            self.assertTrue(len(briefs) >= 24)
            self.assertTrue(rep.is_file())

            # Validate train set
            validate_train_set(cases)

            # Check every template target <= 15
            counts = Counter(c['meta']['template'] for c in cases)
            for tmpl, cnt in counts.items():
                self.assertLessEqual(cnt, 15)

            # Check cases pass fake runner consistency check with 100% rate
            check_res = check_cases(td)
            self.assertEqual(check_res['pass_rate'], 1.0)
            self.assertEqual(check_res['failed'], 0)

    def test_utterance_validation_rules(self) -> None:
        brief = {
            'brief_id': 'brf_test_t1',
            'case_id': 't01_001_test',
            'turn': 1,
            'template': 't01_tra_don_pending',
            'style': 'chuan',
            'length': 'ngắn',
            'must_include': ['SIM-O-50115'],
            'must_not_include': ['chờ xử lý', 'pending'],
        }
        eval_utterances = {'đơn hàng của tôi tới đâu rồi shop ơi'}
        template_utterances = ['Kiểm tra giúp tôi đơn SIM-O-50115 vừa đặt']

        # Missing must_include
        ok, msg = validate_utterance("Tôi muốn kiểm tra hàng", brief, eval_utterances, template_utterances)
        self.assertFalse(ok)
        self.assertIn("Thiếu chuỗi bắt buộc", msg)

        # Contains must_not_include
        ok, msg = validate_utterance("Đơn SIM-O-50115 đang chờ xử lý phải không?", brief, eval_utterances, template_utterances)
        self.assertFalse(ok)
        self.assertIn("Chứa cụm từ cấm", msg)

        # khong_dau with accents
        brief_kd = dict(brief, style='khong_dau')
        ok, msg = validate_utterance("kiem tra giup toi don SIM-O-50115 có dấu", brief_kd, eval_utterances, template_utterances)
        self.assertFalse(ok)
        self.assertIn("ký tự tiếng Việt có dấu", msg)

        # Overlap with eval suite (common substring >= 40)
        long_eval = "đơn hàng của tôi tới đâu rồi shop ơi xin hãy trả lời ngay nhé"
        eval_set = {long_eval}
        ok, msg = validate_utterance(f"SIM-O-50115 {long_eval}", brief, eval_set, template_utterances)
        self.assertFalse(ok)
        self.assertIn("ca đo", msg)

        # Valid utterance
        valid_txt = "Nhờ shop tra giúp tiến độ giao kiện SIM-O-50115 nhé"
        ok, msg = validate_utterance(valid_txt, brief, eval_utterances, template_utterances)
        self.assertTrue(ok)

    def test_utterance_peak_hour_and_mock_cache(self) -> None:
        # Vietnam peak hour: Friday 14:30
        tz_vn = timezone(timedelta(hours=7))
        dt_peak = datetime(2026, 11, 20, 14, 30, tzinfo=tz_vn)  # Friday
        self.assertTrue(is_peak_hour(dt_peak))

        # Off-peak: Friday 18:30
        dt_offpeak = datetime(2026, 11, 20, 18, 30, tzinfo=tz_vn)
        self.assertFalse(is_peak_hour(dt_offpeak))

        # Weekend: Sunday 14:30
        dt_weekend = datetime(2026, 11, 22, 14, 30, tzinfo=tz_vn)
        self.assertFalse(is_peak_hour(dt_weekend))

        with tempfile.TemporaryDirectory(prefix='test-utterances-') as td:
            # Generate 2 test cases to td
            cases, briefs, _ = generate_cases(td, pilot=12, seed=20261202)

            # Test peak hour block
            with self.assertRaises(RuntimeError):
                fill_utterances(td, now_fn=lambda: dt_peak, allow_peak=False)

            # Mock DeepSeek client that outputs compliant utterance
            import hashlib
            import re

            def mock_llm(b: dict) -> str:
                must = b.get('must_include', [])
                bid = b.get('brief_id', 'b0')
                cid = b.get('case_id', '')
                turn = int(b.get('turn', 1))
                style = b.get('style', 'chuan')
                token = ' '.join(must) if must else 'thông tin'
                m = re.search(r'_(\d+)_', cid)
                cnum = int(m.group(1)) if m else 1
                h = int(hashlib.md5(bid.encode('utf-8')).hexdigest(), 16)
                ref_code = f'#{h % 9000 + 1000}'

                if style == 'khong_dau':
                    p1 = [
                        'nho shop kiem tra tinh trang {token} giup toi som nhe',
                        'cho toi hoi don hang {token} da giao den dau roi nhi',
                        'shop oi check dum minh kien hang {token} voi nhe',
                        'minh muon biet thong tin chi tiet ve {token} cam on shop',
                        'ho tro kiem tra tien do {token} giup minh voi nhe ban',
                    ]
                    p_later = [
                        'cho minh hoi them ve {token} duoc khong shop',
                        'vay con van de {token} thi sao nhi ban',
                        'the thi {token} se duoc tinh the nao ha shop',
                        'nho shop giai thich giup them ve {token} nay nhe',
                        'con ve muc {token} thi ben minh ho tro the nao',
                    ]
                    pool = p1 if turn == 1 else p_later
                    idx = (cnum + turn * 3) % len(pool)
                    return f'{pool[idx].format(token=token)} ma so {ref_code}'

                if style == 'dai':
                    openings = [
                        f'Kính chào quý cửa hàng thân mến, tôi gửi tin nhắn này để tìm hiểu theo mã {ref_code}.',
                        f'Xin chào bộ phận hỗ trợ khách hàng, tôi liên hệ theo mã tham chiếu {ref_code} hôm nay.',
                        f'Chào các bạn chăm sóc khách hàng bên shop, tôi có một thắc mắc mã {ref_code} cần giải tỏa.',
                        f'Dạ chào shop, tôi đang theo dõi đơn hàng và có mã kiểm tra {ref_code} cần được hỗ trợ.',
                        f'Gửi đội ngũ hỗ trợ trực tuyến, tôi liên quan đến mã ghi nhận {ref_code} cần làm rõ.',
                    ]
                    middles = [
                        f'Liên quan đến nội dung chi tiết của {token}, tôi cảm thấy chưa thực sự an tâm về tiến độ.',
                        f'Đối với vấn đề cụ thể về {token}, tôi muốn biết rõ trạng thái hiện thời của đơn.',
                        f'Về trường hợp xử lý cho {token}, tôi cần biết quy trình tiếp theo sẽ diễn ra như thế nào.',
                        f'Với toàn bộ phần thông tin của {token}, tôi mong nhận được câu trả lời rõ ràng minh bạch.',
                        f'Khi xem xét kiện hàng {token}, tôi phát hiện có một số điểm cần hỏi kỹ hơn trước khi nhận.',
                    ]
                    closings = [
                        'Rất mong nhận được phản hồi nhanh chóng và tường tận từ đội ngũ trực chat, xin chân thành cảm ơn shop.',
                        'Hy vọng shop giải đáp thấu đáo để tôi tiện sắp xếp công việc nhận kiện hàng, chúc shop buôn may bán đắt.',
                        'Nhờ các bạn kiểm tra kỹ trên hệ thống và nhắn lại giúp tôi kết quả sớm nhất nhé, xin cảm ơn nhiều.',
                        'Mong cửa hàng kiểm tra đối soát cẩn thận giúp tôi và gửi phản hồi xác thực, tôi xin cảm ơn.',
                        'Tôi xin cảm ơn trước sự hỗ trợ chu đáo và nhiệt tình của các bạn nhân viên tư vấn.',
                    ]
                    return f'{openings[cnum % len(openings)]} {middles[(turn + cnum) % len(middles)]} {closings[(turn * 2 + cnum) % len(closings)]}'

                # Standard / teencode / sai_chinh_ta
                p1 = [
                    ('Tôi muốn hỏi thăm tình hình xử lý {token}', 'của tôi theo đơn nhé.'),
                    ('Cho mình xin thông tin cụ thể liên quan tới {token}', 'giúp mình với shop.'),
                    ('Shop vui lòng kiểm tra tiến độ giao hàng cho {token}', 'nhé bạn trực chat.'),
                    ('Gói hàng {token} của tôi hiện tại đang ở bưu cục nào', 'vậy shop ơi.'),
                    ('Kiểm tra giúp đơn {token} xem đã xuất kho giao bưu tá chưa', 'nhé cửa hàng.'),
                    ('Nhờ bạn tra cứu tình trạng hiện tại của {token}', 'giúp mình vào hệ thống.'),
                    ('Mình đang ngóng chờ nhận {token}', 'không biết bao giờ tới nơi.'),
                    ('Cần hỗ trợ gấp về trường hợp kiện {token}', 'này sớm nhé bên bạn.'),
                    ('Vui lòng cập nhật trạng thái mới nhất cho {token}', 'để tôi tiện theo dõi.'),
                    ('Xem hộ mình xem kiện {token} đã bàn giao đi chưa', 'nha bạn trực page.'),
                ]
                p_later = [
                    ('Dạ cho mình hỏi thêm một chút về {token}', 'với cửa hàng ạ.'),
                    ('Thế còn khoản {token} thì tính thế nào', 'vậy shop tư vấn giúp.'),
                    ('Vậy trường hợp {token} này xử lý ra sao', 'hả các bạn chăm sóc.'),
                    ('Nhờ tư vấn thêm giúp tôi vấn đề {token}', 'này một cách cụ thể.'),
                    ('Cho tôi làm rõ thêm nội dung {token}', 'được không bên bán hàng.'),
                    ('Shop giải đáp cụ thể mục {token}', 'giúp mình để mình nắm rõ.'),
                    ('Còn về điều khoản {token} thì thế nào', 'vậy bạn giải thích giúp.'),
                ]
                pool = p1 if turn == 1 else p_later
                pref, suff = pool[(cnum * 3 + turn * 5) % len(pool)]
                return f'{pref.format(token=token)} mã số {ref_code} {suff}'

            client = DeepSeekClient(mock_handler=mock_llm)

            # Run with allow_peak=True
            res = fill_utterances(td, client=client, allow_peak=True, now_fn=lambda: dt_peak)
            self.assertEqual(res['failed_count'], 0)
            self.assertTrue(res['filled_count'] >= 12)

            # Verify cache file and filled cases file exist
            cache_file = Path(td) / 'utterances_cache.jsonl'
            filled_file = Path(td) / 'cases_sft_v1_filled.jsonl'
            self.assertTrue(cache_file.is_file())
            self.assertTrue(filled_file.is_file())

            # Second run resumes from cache
            res2 = fill_utterances(td, client=client, allow_peak=True)
            self.assertEqual(res2['filled_count'], res['filled_count'])


if __name__ == '__main__':
    unittest.main()
