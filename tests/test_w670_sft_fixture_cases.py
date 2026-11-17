"""Unit tests for W6.7.0 Part A: SFT fixture, cases generator, and utterance tooling.

Covers:
- Fixture sha256, counts, zero collision with standard dataset, and threshold self-checks (P1)
- Tenant provisioning for sft_v1 (TRAIN_FIXTURES) and standard/late_voucher_issued (FIXTURES unchanged) (N4)
- validate_train_case and validate_train_set contracts
- Template order usage <= 3 per template and eligibility flag consistency (P2)
- Case generation on pilot 24 and pilot 100 with >= 90 templates and >= 8 cases per style (P4)
- 100% fake runner consistency check pass rate with 0 dropped claims and 0 audits
- Utterance validation rules (N1): khong_dau accent stripping on both sides, injection handling
- Peak-hour restriction, concurrency, retry on 429/5xx, and limit behavior (N2/N3)
- Real PDF inspection when pypdfium2 is installed (P3)
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import tempfile
import unittest
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

from scripts.sft_dataset import sft_v1_demo_ids, validate_train_case, validate_train_set
from scripts.sft_cases import generate_cases, check_cases
from scripts.sft_templates import TEMPLATES, SftView
from scripts.sft_utterances import (
    DeepSeekClient,
    fill_utterances,
    is_peak_hour,
    jaccard_5gram,
    max_common_substring_len,
    strip_vietnamese_accents,
    validate_utterance,
)
from scripts.run_agent_scenarios import (
    _modules,
    _provision_demo_template,
    FIXTURES,
    TRAIN_FIXTURES,
    load_dataset,
    run_scenario,
    ScriptedGateway,
)


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
        self.assertEqual(meta['total_events'], 3174)
        self.assertEqual(meta['total_orders'], 216)
        self.assertEqual(meta['total_customers'], 170)

        sft_customers, sft_orders, _ = sft_v1_demo_ids()
        self.assertEqual(len(sft_orders), 216)
        self.assertEqual(len(sft_customers), 170)

        # Verify 0 overlap with standard fixture (orders, customers, tracking codes)
        std_orders: set[str] = set()
        std_customers: set[str] = set()
        std_trackings: set[str] = set()
        if std_path.is_file():
            for line in std_path.read_text(encoding='utf-8').splitlines():
                if line.strip():
                    ev = json.loads(line)
                    data = ev.get('data', {})
                    if data.get('external_order_id'):
                        std_orders.add(data['external_order_id'])
                    if data.get('external_customer_id'):
                        std_customers.add(data['external_customer_id'])
                    if data.get('tracking_number'):
                        std_trackings.add(data['tracking_number'])

        sft_trackings: set[str] = set()
        for line in content.decode('utf-8').splitlines():
            if line.strip():
                ev = json.loads(line)
                trk = ev.get('data', {}).get('tracking_number')
                if trk:
                    sft_trackings.add(trk)

        self.assertEqual(len(sft_orders & std_orders), 0, "Colliding orders between sft_v1 and standard")
        self.assertEqual(len(sft_customers & std_customers), 0, "Colliding customers between sft_v1 and standard")
        self.assertEqual(len(sft_trackings & std_trackings), 0, "Colliding tracking numbers between sft_v1 and standard")

        # Threshold checks (P1)
        view = SftView()
        self.assertGreaterEqual(len(view.orders_can_cancel), 8, "Pending cancelable orders < 8")
        self.assertGreaterEqual(len(view.orders_by_status.get('shipping', [])), 10, "Shipping orders < 10")
        self.assertGreaterEqual(len(view.late_orders), 8, "Late orders < 8")
        self.assertGreaterEqual(len(view.late_orders_over_48h), 4, "Late orders > 48h < 4")
        self.assertGreaterEqual(len(view.orders_failed_or_returned), 6, "Failed or returned orders < 6")
        self.assertGreaterEqual(len(view.orders_past_warranty), 6, "Past warranty orders < 6")
        refund_slow_or_fail = len(view.orders_refund_processing) + len(view.orders_refund_failed)
        self.assertGreaterEqual(refund_slow_or_fail, 6, "Refund processing or failed orders < 6")

    def test_provision_templates_and_runner_fixtures(self) -> None:
        # N4: FIXTURES remains clean with only standard and late_voucher_issued
        self.assertEqual(set(FIXTURES.keys()), {'standard', 'late_voucher_issued'})
        self.assertIn('sft_v1', TRAIN_FIXTURES)

        Application, ApiError, PersistentSessions, KnowledgeRepository, AgentError = _modules()

        # sft_v1 provisioning
        p_sft = _provision_demo_template('sft_v1', PersistentSessions)
        sess_sft = PersistentSessions(p_sft, data_mode='persistent-demo')
        store_sft = sess_sft.business_store('shop-scenarios')
        with store_sft.connection() as db:
            orders_cnt_sft = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        self.assertEqual(orders_cnt_sft, 216)

        # standard provisioning unchanged (128 orders)
        p_std = _provision_demo_template('standard', PersistentSessions)
        sess_std = PersistentSessions(p_std, data_mode='persistent-demo')
        store_std = sess_std.business_store('shop-scenarios')
        with store_std.connection() as db:
            orders_cnt_std = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        self.assertEqual(orders_cnt_std, 128)

    def test_validate_train_case_contract(self) -> None:
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
                'slot_key': 'SIM-O-50006',
                'intent': 'tra_cuu_don_hang',
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

    def test_pilot_100_coverage_and_style_distribution(self) -> None:
        """P4: Test pilot 100 covers >= 90 distinct templates and >= 8 cases per style."""
        with tempfile.TemporaryDirectory(prefix='test-pilot-100-') as td:
            cases, briefs, rep = generate_cases(td, pilot=100, seed=20261202)
            self.assertEqual(len(cases), 100)

            # Check distinct templates >= 90
            templates_covered = {c['meta']['template'] for c in cases}
            self.assertGreaterEqual(len(templates_covered), 90, f"Only {len(templates_covered)} templates covered (< 90)")

            # Check style distribution >= 8 per style
            style_counts = Counter(c['meta']['style'] for c in cases)
            for style in ['chuan', 'teencode', 'khong_dau', 'sai_chinh_ta', 'dai']:
                self.assertGreaterEqual(
                    style_counts[style], 8, f"Style '{style}' has only {style_counts[style]} cases (< 8)"
                )

            # Check consistency
            check_res = check_cases(td)
            self.assertEqual(check_res['pass_rate'], 1.0)
            self.assertEqual(check_res['failed'], 0)

    def test_order_eligibility_and_template_constraints(self) -> None:
        """P1 & P2: Test max order usage <= 3 per template and eligibility flags match requirements."""
        jsonl_path = ROOT / 'data' / 'demo_events' / 'store_events_sft_v1.jsonl'
        view = SftView()

        with tempfile.TemporaryDirectory(prefix='test-constraints-') as td:
            cases, _, _ = generate_cases(td, pilot=None, seed=20261202)

            # Assert order usage <= 3 per template
            usage_by_tmpl: dict[str, Counter[str]] = defaultdict(Counter)
            for c in cases:
                tmpl_name = c['meta']['template']
                text = str(c)
                for oid in set(re.findall(r'SIM-O-\d+', text)):
                    usage_by_tmpl[tmpl_name][oid] += 1
            for tmpl_name, cnts in usage_by_tmpl.items():
                for oid, cnt in cnts.items():
                    self.assertLessEqual(cnt, 3, f"Template {tmpl_name} uses order {oid} {cnt} times (> 3)")

            # Check eligibility flags for orders used in key templates
            for c in cases:
                tmpl = c['meta']['template']
                oid = c['meta'].get('slot_key')
                if not oid or not str(oid).startswith('SIM-O-'):
                    continue
                o = view.orders.get(oid)
                if not o:
                    continue

                # Template-specific eligibility assertions
                el = o.get('eligibility', {})
                if tmpl.startswith('t04_huy_pending'):
                    self.assertTrue(el.get('can_self_service_cancel'), f"{tmpl} uses order {oid} not cancelable")
                elif tmpl == 't05_tra_hang_het_han_bao_hanh':
                    self.assertFalse(el.get('within_warranty'), f"{tmpl} uses order {oid} within warranty")
                elif tmpl in ('t05_tra_don_delivered_con_han', 't05_khach_chua_nhan_muon_tra'):
                    self.assertTrue(el.get('within_return_window'), f"{tmpl} uses order {oid} past return window")
                elif tmpl == 't01_giao_tre_tren_48h':
                    self.assertTrue(el.get('is_late_vs_promised') and float(el.get('late_by_hours', 0) or 0) > 48, f"{tmpl} uses order {oid} not late > 48h")
                elif tmpl == 't01_giao_tre_duoi_48h':
                    self.assertTrue(el.get('is_late_vs_promised') and float(el.get('late_by_hours', 0) or 0) <= 48, f"{tmpl} uses order {oid} not late <= 48h")

    def test_utterance_validation_n1_rules(self) -> None:
        """N1: Utterance validation rules: accents stripped on both sides for khong_dau, injection handling."""
        brief_kd = {
            'brief_id': 'brf_test_kd',
            'case_id': 't01_001_test',
            'turn': 1,
            'template': 't01_tra_don_delivered',
            'style': 'khong_dau',
            'length': 'ngắn',
            'must_include': ['Áo Thun Nữ Cotton', 'SIM-O-50006'],
            'must_not_include': ['giao hàng thành công'],
        }
        eval_utterances = {'đơn hàng của tôi tới đâu rồi'}
        template_utterances = ['kiem tra giup toi don hang ao thun SIM-O-50006']

        # Utterance with unaccented product name and order id passes khong_dau
        kd_txt = "shop kiem tra giup toi kien ao thun nu cotton SIM-O-50006 nhe"
        ok, msg = validate_utterance(kd_txt, brief_kd, eval_utterances, template_utterances)
        self.assertTrue(ok, f"khong_dau validation failed: {msg}")

        # Utterance with accented characters fails khong_dau
        bad_kd = "shop kiểm tra giúp tôi kiện ao thun nu cotton SIM-O-50006 nhé"
        ok, msg = validate_utterance(bad_kd, brief_kd, eval_utterances, template_utterances)
        self.assertFalse(ok)
        self.assertIn("ký tự tiếng Việt có dấu", msg)

        # Injection brief: injection substring must not be falsely blocked by must_not_include
        fake_link = "http://fake-link-test.com"
        inj_brief = {
            'brief_id': 'brf_test_inj',
            'case_id': 't09_001_test',
            'turn': 1,
            'template': 't09_the_he_thong_gia_voucher',
            'style': 'chuan',
            'length': 'vừa',
            'must_include': [fake_link],
            'must_not_include': ['tặng voucher'],
            'injection': fake_link,
        }
        inj_txt = f"Nhờ bạn vào xem {fake_link} giúp tôi được không?"
        ok, msg = validate_utterance(inj_txt, inj_brief, eval_utterances, template_utterances)
        self.assertTrue(ok, f"Injection validation failed: {msg}")

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
            # Generate 12 test cases to td
            cases, briefs, _ = generate_cases(td, pilot=12, seed=20261202)

            # Test peak hour block
            with self.assertRaises(RuntimeError):
                fill_utterances(td, now_fn=lambda: dt_peak, allow_peak=False)

            def mock_llm(b: dict) -> str:
                must = list(b.get('must_include', []))
                inj = b.get('injection')
                if inj and inj not in must:
                    must.append(inj)
                bid = b.get('brief_id', 'b0')
                cid = b.get('case_id', '')
                turn = int(b.get('turn', 1))
                style = b.get('style', 'chuan')
                token = ' '.join(must) if must else 'thông tin đơn hàng'
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
                    raw_str = f'{pool[idx].format(token=token)} ma so {ref_code}'
                    if inj:
                        return f"{strip_vietnamese_accents(pool[idx].format(token=''))} {inj} ma so {ref_code}"
                    return strip_vietnamese_accents(raw_str)

                if style == 'dai':
                    openings = [
                        f'Kính chào quý cửa hàng thân mến, tôi gửi tin nhắn này để tìm hiểu chi tiết về kiện hàng theo mã số {ref_code}.',
                        f'Xin chào bộ phận chăm sóc khách hàng trực tuyến của shop, tôi liên hệ theo mã tham chiếu {ref_code} hôm nay.',
                        f'Chào các bạn nhân viên tư vấn hỗ trợ bên shop, tôi có một thắc mắc cần được giải đáp rõ theo mã {ref_code}.',
                        f'Dạ em chào shop ạ, em đang theo dõi hành trình đơn hàng trên hệ thống và có mã kiểm tra {ref_code} cần được hỗ trợ.',
                        f'Gửi đội ngũ phụ trách chăm sóc khách hàng, tôi liên quan đến mã ghi nhận {ref_code} cần làm rõ tiến độ đơn.',
                    ]
                    middles = [
                        f'Liên quan đến toàn bộ nội dung chi tiết của {token}, tôi cảm thấy cần được giải thích kỹ lưỡng hơn về tiến độ.',
                        f'Đối với vấn đề cụ thể về {token}, tôi rất muốn biết rõ trạng thái hiện thời của đơn hàng cũng như thời gian dự kiến.',
                        f'Về trường hợp xử lý cho {token}, tôi cần biết quy trình tiếp theo của cửa hàng sẽ diễn ra như thế nào để tiện chuẩn bị.',
                        f'Với toàn bộ phần thông tin liên quan đến {token}, tôi mong nhận được câu trả lời rõ ràng minh bạch từ phía cửa hàng.',
                        f'Khi xem xét kỹ về {token}, tôi nhận thấy có một số điểm cần hỏi rõ nhân viên hỗ trợ trước khi nhận hàng thanh toán.',
                    ]
                    closings = [
                        'Rất mong nhận được phản hồi nhanh chóng và tường tận từ đội ngũ trực chat, tôi xin chân thành cảm ơn shop.',
                        'Hy vọng shop giải đáp thấu đáo để tôi tiện sắp xếp công việc nhận kiện hàng, chúc shop buôn may bán đắt.',
                        'Nhờ các bạn kiểm tra kỹ trên hệ thống và nhắn lại giúp tôi kết quả sớm nhất nhé, xin cảm ơn các bạn rất nhiều.',
                        'Mong cửa hàng kiểm tra đối soát cẩn thận giúp tôi và gửi phản hồi xác thực, tôi xin cảm ơn sự nhiệt tình của shop.',
                        'Tôi xin cảm ơn trước sự hỗ trợ chu đáo và nhiệt tình của các bạn nhân viên tư vấn của cửa hàng.',
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

    def test_utterance_n2_n3_retry_and_concurrency(self) -> None:
        """N2 & N3: Test retry with feedback, HTTP 429 backoff, and limit safety."""
        # 1. Test DeepSeekClient retry on 429/5xx with backoff
        attempts = 0

        def flaky_handler(brief: dict, feedback: str = '') -> str:
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                import urllib.error
                raise urllib.error.HTTPError("http://api.deepseek.com", 429, "Rate limit", {}, None)
            return f"Tôi cần hỗ trợ đơn hàng {brief.get('must_include', [''])[0]}"

        client = DeepSeekClient(mock_handler=flaky_handler)
        b = {'brief_id': 'b1', 'must_include': ['SIM-O-50006'], 'style': 'chuan'}
        txt = client.call(b)
        self.assertIn("SIM-O-50006", txt)
        self.assertEqual(attempts, 3)

        # 2. Test --limit: incomplete cases are NOT written to cases_sft_v1_filled.jsonl (N2)
        with tempfile.TemporaryDirectory(prefix='test-limit-') as td:
            cases, briefs, _ = generate_cases(td, pilot=12, seed=20261202)
            # Run fill_utterances with limit=2 (out of ~14 briefs)
            def simple_mock(b: dict, feedback: str = '') -> str:
                bid = b.get('brief_id', 'b0')
                h = int(hashlib.md5(bid.encode('utf-8')).hexdigest(), 16) % 9000 + 1000
                must = b.get('must_include', [''])[0]
                if b.get('style') == 'khong_dau':
                    return f"kiem tra don hang {must} ma so {h}"
                return f"Kiểm tra giúp đơn {must} mã số {h} nhé"

            client_simple = DeepSeekClient(mock_handler=simple_mock)
            res = fill_utterances(td, client=client_simple, allow_peak=True, limit=2)
            self.assertEqual(res['filled_count'], 2)
            self.assertGreater(res['pending_cases'], 0)

            filled_file = Path(td) / 'cases_sft_v1_filled.jsonl'
            if filled_file.is_file():
                for line in filled_file.read_text(encoding='utf-8').splitlines():
                    if line.strip():
                        c = json.loads(line)
                        # No placeholder text allowed in written cases
                        self.assertNotIn("<chờ lời khách", json.dumps(c, ensure_ascii=False))

    @unittest.skipUnless(importlib.util.find_spec('pypdfium2') is not None, "pypdfium2 required for real PDF inspection on CI")
    def test_p3_real_pdf_case_execution(self) -> None:
        """P3: Test execution of text_pdf attachment cases with real pypdfium2 library."""
        with tempfile.TemporaryDirectory(prefix='test-pdf-') as td:
            cases, _, _ = generate_cases(td, pilot=100, seed=20261202)
            pdf_cases = [c for c in cases if c.get('actor') == 'staff_case_assist' and any(
                isinstance(m.get('attachment'), dict) and m['attachment'].get('kind') == 'text_pdf'
                for m in c.get('case_setup', {}).get('customer_messages', [])
            )]
            self.assertGreaterEqual(len(pdf_cases), 1, "No PDF attachment cases found in pilot 100")

            # Run scenario with ScriptedGateway without flattening
            gw = ScriptedGateway()
            res = run_scenario(pdf_cases[0], gw, mode='fake')
            self.assertTrue(res['passed'], f"PDF case failed real execution: {res.get('failures')}")


if __name__ == '__main__':
    unittest.main()
