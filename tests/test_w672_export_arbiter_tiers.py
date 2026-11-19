"""Unit tests W6.7.2 mục A (export vòng 2), B (trọng tài), C (Tier S chấm cặp) bằng dữ liệu giả."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HAS_W672 = (ROOT / 'scripts' / 'sft_select.py').is_file() and (ROOT / 'scripts' / 'sft_build.py').is_file()

if HAS_W672:
    from scripts import sft_select  # noqa: E402
    from tests.test_w670_sft_select_build import _build_synthetic_workspace, _make_turn_trace  # noqa: E402


def _write_run_dir(run_dir: Path, records: list[dict], traces: list[dict], sha: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / 'merged.json').write_text(
        json.dumps({'provenance': {'git_sha': sha}, 'scenarios': records}, ensure_ascii=False),
        encoding='utf-8',
    )
    (run_dir / 'manifest.json').write_text(json.dumps({'git_sha': sha}), encoding='utf-8')
    (run_dir / 'shard-00.jsonl').write_text(
        ''.join(json.dumps(t, ensure_ascii=False) + '\n' for t in traces),
        encoding='utf-8',
    )


def _run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = sft_select.main(list(argv))
    return code, out.getvalue(), err.getvalue()


@unittest.skipUnless(HAS_W672, 'scripts/sft_select.py không có trong gói Colab')
class TestW672ExportRound2(unittest.TestCase):
    def _build_round2_fixture(self, root: Path) -> dict:
        cases = [
            # c_qnext: chưa có Tier A, còn A_code Qwen chưa chấm (run 2) + B_code Qwen (run 3) + DeepSeek (run 1)
            {'id': 't01_001_qnext', 'category': 't01', 'title': 'Tra cứu đơn hàng 1',
             'meta': {'suite': 'T01', 'template': 'tmpl_t01', 'style': 'chuan'},
             'turns': [{'user': 'Hỏi đơn D1', 'expect': {'answer_all': ['D1'], 'answer_not': ['lỗi']}}]},
            # c_no_qwen: chưa có Tier A, Qwen chỉ còn B_code, DeepSeek có A_code -> KHÔNG xuất (Qwen trước)
            {'id': 't02_002_no_qwen_a', 'category': 't02', 'title': 'Tra cứu đơn hàng 2',
             'meta': {'suite': 'T02', 'template': 'tmpl_t02', 'style': 'chuan'},
             'turns': [{'user': 'Hỏi đơn D2', 'expect': {'answer_all': ['D2'], 'answer_not': ['lỗi']}}]},
            # c_dspair: Tier A là Qwen, còn A_code DeepSeek -> xuất ds_pair
            {'id': 't03_003_dspair', 'category': 't03', 'title': 'Tra cứu đơn hàng 3',
             'meta': {'suite': 'T03', 'template': 'tmpl_t03', 'style': 'chuan'},
             'turns': [{'user': 'Hỏi đơn D3', 'expect': {'answer_all': ['D3'], 'answer_not': ['lỗi']}}]},
            # c_easy_no_ds: bộ không khó (T01), Tier A là Qwen, không có A_code DeepSeek -> KHÔNG xuất q_second
            {'id': 't01_004_easy_no_ds', 'category': 't01', 'title': 'Tra cứu đơn hàng 4',
             'meta': {'suite': 'T01', 'template': 'tmpl_t01', 'style': 'chuan'},
             'turns': [{'user': 'Hỏi đơn D4', 'expect': {'answer_all': ['D4'], 'answer_not': ['lỗi']}}]},
            # c_qsec_ok: bộ khó (T08), Tier A là Qwen (run 1), không có DS A_code, run 2 giống >= 0.85 (bỏ), run 3 khác < 0.85 (chọn!)
            {'id': 't08_005_qsecond', 'category': 't08', 'title': 'Tra cứu đơn hàng 5',
             'meta': {'suite': 'T08', 'template': 'tmpl_t08', 'style': 'chuan'},
             'turns': [{'user': 'Hỏi đơn D5', 'expect': {'answer_all': ['D5'], 'answer_not': ['lỗi']}}]},
            # c_qsec_dup: bộ khó (T05), Tier A là Qwen (run 1), không có DS, run 2 giống >= 0.85 -> KHÔNG xuất
            {'id': 't05_006_qsecond_too_similar', 'category': 't05', 'title': 'Tra cứu đơn hàng 6',
             'meta': {'suite': 'T05', 'template': 'tmpl_t05', 'style': 'chuan'},
             'turns': [{'user': 'Hỏi đơn D6', 'expect': {'answer_all': ['D6'], 'answer_not': ['lỗi']}}]},
            # c_excl: thuộc khung bị loại trừ bởi --exclude-templates -> KHÔNG xuất
            {'id': 't07_007_excluded', 'category': 't07', 'title': 'Tra cứu đơn hàng 7',
             'meta': {'suite': 'T07', 'template': 't07_doa_dang_bai', 'style': 'chuan'},
             'turns': [{'user': 'Hỏi đơn D7', 'expect': {'answer_all': ['D7'], 'answer_not': ['lỗi']}}]},
            # c_multi_after: tệp after 1 chấm B, tệp after 2 nâng lên A -> phải lấy Tier A từ tệp sau cùng, xuất ds_pair thay vì q_next
            {'id': 't04_008_multi_after', 'category': 't04', 'title': 'Tra cứu đơn hàng 8',
             'meta': {'suite': 'T04', 'template': 'tmpl_t04', 'style': 'chuan'},
             'turns': [{'user': 'Hỏi đơn D8', 'expect': {'answer_all': ['D8'], 'answer_not': ['lỗi']}}]},
        ]
        cases_path = root / 'cases.jsonl'
        cases_path.write_text(''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in cases), encoding='utf-8')

        q_recs, q_tr, d_recs, d_tr = [], [], [], []

        def add(model_recs, model_tr, cid, run, answer, *, b_code=False, tokens=30, tool_payload='{"ok":true}'):
            turn_obj = {'answer': answer, 'tools': [{'name': 'get_order'}], 'error': None}
            if b_code:
                turn_obj['answer_check'] = {'dropped_policy_promises': 1, 'detail': []}
            model_recs.append({'id': cid, 'run': run, 'passed': True, 'failures': [], 'attack_success': False, 'turns': [turn_obj]})
            order_code = f'ORD-{run}'
            model_tr.extend(_make_turn_trace(
                cid, run, 1, user_text=f'Hỏi đơn {order_code}',
                steps=[{'reasoning': f'Tra đơn {order_code}', 'tool_calls': [{'name': 'get_order', 'arguments': {'id': order_code}}],
                        'tool_results': [tool_payload], 'completion_tokens': 10}],
                final_content=answer, completion_tokens=tokens,
            ))

        # c_qnext: qwen#1 (judged C), qwen#2 (unjudged A_code -> q_next!), qwen#3 (B_code), ds#1 (A_code)
        add(q_recs, q_tr, 't01_001_qnext', 1, 'Đơn D1 đang xử lý.', tokens=20)
        add(q_recs, q_tr, 't01_001_qnext', 2, 'Đơn D1 đang đóng gói.', tokens=30, tool_payload='{"note":"' + 'A' * 4500 + '"}')
        add(q_recs, q_tr, 't01_001_qnext', 3, 'Đơn D1 B_code.', b_code=True, tokens=10)
        add(d_recs, d_tr, 't01_001_qnext', 1, 'Đơn D1 từ DS.', tokens=15)

        # c_no_qwen: qwen#1 (judged C), qwen#2 (B_code -> phải bỏ!), ds#1 (A_code -> không xuất vì Qwen trước)
        add(q_recs, q_tr, 't02_002_no_qwen_a', 1, 'Đơn D2 đã hủy.', tokens=20)
        add(q_recs, q_tr, 't02_002_no_qwen_a', 2, 'Đơn D2 B_code.', b_code=True, tokens=25)
        add(d_recs, d_tr, 't02_002_no_qwen_a', 1, 'Đơn D2 từ DS.', tokens=15)

        # c_dspair: qwen#1 (Tier A), ds#1 (A_code -> ds_pair!), ds#2 (B_code)
        add(q_recs, q_tr, 't03_003_dspair', 1, 'Đơn D3 đã giao.', tokens=20)
        add(d_recs, d_tr, 't03_003_dspair', 1, 'Đơn D3 đã hoàn tất giao hàng.', tokens=25)
        add(d_recs, d_tr, 't03_003_dspair', 2, 'Đơn D3 B_code.', b_code=True, tokens=10)

        # c_easy_no_ds: qwen#1 (Tier A), qwen#2 (A_code khác hẳn), không có DS -> T01 không thuộc HARD_SUITES nên không xuất
        add(q_recs, q_tr, 't01_004_easy_no_ds', 1, 'Đơn D4 đang vận chuyển bình thường.', tokens=20)
        add(q_recs, q_tr, 't01_004_easy_no_ds', 2, 'Thông tin đơn D4: hiện ở kho phân loại miền Nam, dự kiến giao thứ năm.', tokens=30)

        # c_qsec_ok: qwen#1 (Tier A), qwen#2 (giống >= 0.85, rank tốt hơn), qwen#3 (khác < 0.85 -> chọn!), ds#1 (B_code -> bỏ!)
        add(q_recs, q_tr, 't08_005_qsecond', 1, 'Đơn D5 đang vận chuyển tới kho quận 1 và dự kiến giao trong ngày mai.', tokens=20)
        add(q_recs, q_tr, 't08_005_qsecond', 2, 'Đơn D5 đang vận chuyển tới kho quận 1 và dự kiến giao trong ngày mai!', tokens=25)
        add(q_recs, q_tr, 't08_005_qsecond', 3, 'Mã vận đơn D5 đã rời bưu cục trung tâm; bạn có thể theo dõi trên ứng dụng hoặc yêu cầu đổi địa chỉ nhận.', tokens=40)
        add(d_recs, d_tr, 't08_005_qsecond', 1, 'Đơn D5 B_code DS.', b_code=True, tokens=15)

        # c_qsec_dup: qwen#1 (Tier A), qwen#2 (giống >= 0.85) -> không xuất
        add(q_recs, q_tr, 't05_006_qsecond_too_similar', 1, 'Đơn D6 đủ điều kiện đổi size trong 7 ngày kể từ ngày nhận.', tokens=20)
        add(q_recs, q_tr, 't05_006_qsecond_too_similar', 2, 'Đơn D6 đủ điều kiện đổi size trong 7 ngày kể từ ngày nhận ạ.', tokens=25)

        # c_excl: chưa Tier A, có qwen#1 -> bị loại bởi --exclude-templates
        add(q_recs, q_tr, 't07_007_excluded', 1, 'Đơn D7 bị loại theo khung.', tokens=20)

        # c_multi_after: qwen#1 (after1=B, after2=A -> A), qwen#2 (A_code unjudged), ds#1 (A_code unjudged -> ds_pair!)
        add(q_recs, q_tr, 't04_008_multi_after', 1, 'Đơn D8 đã xác nhận.', tokens=20)
        add(q_recs, q_tr, 't04_008_multi_after', 2, 'Đơn D8 bản qwen 2.', tokens=30)
        add(d_recs, d_tr, 't04_008_multi_after', 1, 'Đơn D8 bản deepseek 1.', tokens=25)

        q_dir, d_dir = root / 'run_qwen', root / 'run_ds'
        _write_run_dir(q_dir, q_recs, q_tr, 'a' * 40)
        _write_run_dir(d_dir, d_recs, d_tr, 'b' * 40)

        scores_path = root / 'scores.json'
        code, _, err = _run_cli('score', '--cases', str(cases_path), '--run', f'qwen={q_dir}', '--run', f'deepseek={d_dir}', '--out', str(scores_path))
        self.assertEqual(code, 0, err)

        after1 = root / 'adj_r1.json'
        after1.write_text(json.dumps({
            'round': 1,
            'candidates': {
                't01_001_qnext#qwen#1': {'case_id': 't01_001_qnext', 'model': 'qwen', 'run': 1, 'code_tier': 'A_code', 'tier': 'C', 'item_ids': []},
                't02_002_no_qwen_a#qwen#1': {'case_id': 't02_002_no_qwen_a', 'model': 'qwen', 'run': 1, 'code_tier': 'A_code', 'tier': 'C', 'item_ids': []},
                't03_003_dspair#qwen#1': {'case_id': 't03_003_dspair', 'model': 'qwen', 'run': 1, 'code_tier': 'A_code', 'tier': 'A', 'item_ids': []},
                't01_004_easy_no_ds#qwen#1': {'case_id': 't01_004_easy_no_ds', 'model': 'qwen', 'run': 1, 'code_tier': 'A_code', 'tier': 'A', 'item_ids': []},
                't08_005_qsecond#qwen#1': {'case_id': 't08_005_qsecond', 'model': 'qwen', 'run': 1, 'code_tier': 'A_code', 'tier': 'A', 'item_ids': []},
                't05_006_qsecond_too_similar#qwen#1': {'case_id': 't05_006_qsecond_too_similar', 'model': 'qwen', 'run': 1, 'code_tier': 'A_code', 'tier': 'A', 'item_ids': []},
                't04_008_multi_after#qwen#1': {'case_id': 't04_008_multi_after', 'model': 'qwen', 'run': 1, 'code_tier': 'A_code', 'tier': 'B', 'item_ids': []},
            },
        }, ensure_ascii=False), encoding='utf-8')

        after2 = root / 'adj_r1_arbiter.json'
        after2.write_text(json.dumps({
            'round': 'arbiter_r1',
            'candidates': {
                't04_008_multi_after#qwen#1': {'case_id': 't04_008_multi_after', 'model': 'qwen', 'run': 1, 'code_tier': 'A_code', 'tier': 'A', 'item_ids': []},
            },
        }, ensure_ascii=False), encoding='utf-8')

        return {'scores_path': scores_path, 'after1': after1, 'after2': after2}

    def test_round2_three_classes_exclude_multi_after_and_blind_packets(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w672-a-') as td:
            root = Path(td)
            fx = self._build_round2_fixture(root)
            out_dir = root / 'r2_out'
            code, _, err = _run_cli(
                'export', '--scores', str(fx['scores_path']), '--out', str(out_dir),
                '--round', '2',
                '--after', str(fx['after1']), str(fx['after2']),
                '--max-tool-chars', '8000',
                '--exclude-templates', 't07_doa_dang_bai',
                '--seed', '101', '--batch-size', '10',
            )
            self.assertEqual(code, 0, err)
            mp = json.loads((out_dir / 'map.json').read_text(encoding='utf-8'))
            self.assertEqual(mp['max_tool_chars'], 8000)
            self.assertEqual(mp['after'], [str(fx['after1'].resolve()), str(fx['after2'].resolve())])
            self.assertEqual(mp['exclude_templates'], ['t07_doa_dang_bai'])

            got_cls = {k: v['cls'] for k, v in mp['candidates'].items()}
            self.assertEqual(got_cls, {
                't01_001_qnext#qwen#2': 'q_next',
                't03_003_dspair#deepseek#1': 'ds_pair',
                't08_005_qsecond#qwen#3': 'q_second',
                't04_008_multi_after#deepseek#1': 'ds_pair',
            })
            # Không có B_code nào được xuất
            self.assertTrue(all(v['code_tier'] == 'A_code' for v in mp['candidates'].values()))

            # Kiểm gói ẩn danh: không lộ cls, model, mã ca; tool_results > 3000 nhờ --max-tool-chars 8000
            raw_packets = ''.join(p.read_text(encoding='utf-8') for p in sorted((out_dir / 'packets').glob('batch-*.jsonl')))
            for forbidden in ('q_next', 'ds_pair', 'q_second', 'qwen', 'deepseek', 't01_001', 't08_005'):
                self.assertNotIn(forbidden, raw_packets.lower())
            pkt_rows = [json.loads(l) for l in raw_packets.splitlines() if l.strip()]
            self.assertTrue(all(r['kind'] == 'sft_tier' and 'cls' not in r for r in pkt_rows))
            qnext_iid = mp['candidates']['t01_001_qnext#qwen#2']['item_ids'][0]
            qnext_pkt = next(r for r in pkt_rows if r['item_id'] == qnext_iid)
            self.assertGreater(len(qnext_pkt['steps'][0]['tool_results'][0]['content']), 4000)

    def test_round1_export_and_import_byte_exact_regression(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w672-r1-reg-') as td:
            root = Path(td)
            fx = _build_synthetic_workspace(root)
            scores_path = root / 'scores.json'
            code, _, err = _run_cli(
                'score', '--cases', str(fx['cases_path']),
                '--run', f"qwen={fx['qwen_dir']}", '--run', f"deepseek={fx['ds_dir']}",
                '--out', str(scores_path),
            )
            self.assertEqual(code, 0, err)
            j1 = root / 'judge_r1'
            code, _, err = _run_cli(
                'export', '--scores', str(scores_path), '--out', str(j1),
                '--round', '1', '--seed', '12345', '--batch-size', '2',
            )
            self.assertEqual(code, 0, err)
            raw_bytes = b''.join(p.read_bytes() for p in sorted((j1 / 'packets').glob('*.jsonl')))
            # Khớp từng byte với SHA-256 của exporter gốc 302f54b6
            self.assertEqual(
                hashlib.sha256(raw_bytes.replace(b'\r\n', b'\n')).hexdigest(),
                'c9588f7875062b744e560dc009c55addb840b4fe597997f9497d81b67f62050a',
            )
            mp = json.loads((j1 / 'map.json').read_text(encoding='utf-8'))
            self.assertNotIn('after', mp)
            self.assertNotIn('exclude_templates', mp)
            self.assertTrue(all('cls' not in c for c in mp['candidates'].values()))

            # Import vòng 1 giữ nguyên hành vi
            for grp in ('A', 'B'):
                vdir = j1 / 'verdicts' / grp
                vdir.mkdir(parents=True, exist_ok=True)
                for bname, iids in mp['batches'].items():
                    lines = [
                        json.dumps({'item_id': i, 'verdict': 'dat', 'quote': mp['items'][i]['text'][:25], 'reason': 'Đạt.'}, ensure_ascii=False)
                        for i in iids
                    ]
                    (vdir / f'{bname}.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')
            adj_out = root / 'adj_r1.json'
            code, _, err = _run_cli('import', '--judge-dir', str(j1), '--scores', str(scores_path), '--out', str(adj_out))
            self.assertEqual(code, 0, err)
            adj = json.loads(adj_out.read_text(encoding='utf-8'))
            self.assertEqual(adj['round'], 1)
            self.assertEqual(adj['tier_counts'], {'A': 4})


@unittest.skipUnless(HAS_W672, 'scripts/sft_select.py không có trong gói Colab')
class TestW672Arbiter(unittest.TestCase):
    def _setup_r1_with_tier_b(self, root: Path) -> dict:
        cases = [
            {'id': 't01_001_dat_kc', 'category': 't01', 'title': 'Mục dat/kc',
             'meta': {'suite': 'T01', 'template': 'tmpl_1', 'style': 'chuan'},
             'turns': [{'user': 'Hỏi đơn A1', 'expect': {'answer_all': ['A1'], 'answer_not': ['sai']}}]},
            {'id': 't01_002_kckc', 'category': 't01', 'title': 'Mục kc/kc',
             'meta': {'suite': 'T01', 'template': 'tmpl_1', 'style': 'chuan'},
             'turns': [{'user': 'Hỏi đơn A2', 'expect': {'answer_all': ['A2'], 'answer_not': ['sai']}}]},
            {'id': 't01_003_to_c', 'category': 't01', 'title': 'Trọng tài chấm khong_dat',
             'meta': {'suite': 'T01', 'template': 'tmpl_1', 'style': 'chuan'},
             'turns': [{'user': 'Hỏi đơn A3', 'expect': {'answer_all': ['A3'], 'answer_not': ['sai']}}]},
            {'id': 't01_004_bad_quote', 'category': 't01', 'title': 'Trọng tài trích dẫn sai',
             'meta': {'suite': 'T01', 'template': 'tmpl_1', 'style': 'chuan'},
             'turns': [{'user': 'Hỏi đơn A4', 'expect': {'answer_all': ['A4'], 'answer_not': ['sai']}}]},
            {'id': 't01_005_bcode_skip', 'category': 't01', 'title': 'B_code không gửi trọng tài',
             'meta': {'suite': 'T01', 'template': 'tmpl_1', 'style': 'chuan'},
             'turns': [{'user': 'Hỏi đơn A5', 'expect': {'answer_all': ['A5'], 'answer_not': ['sai']}}]},
        ]
        cases_path = root / 'cases.jsonl'
        cases_path.write_text(''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in cases), encoding='utf-8')
        q_recs, q_tr = [], []
        long_payload = json.dumps({'order': 'A1', 'pad': 'Z' * 3500, 'tail_fact': 'CON_HAN_BAO_HANH_12_THANG'}, ensure_ascii=False)
        for idx, c in enumerate(cases, 1):
            cid = c['id']
            turn_obj = {'answer': f'Đơn A{idx} đã được kiểm tra kỹ càng.', 'tools': [{'name': 'get_order'}], 'error': None}
            if cid == 't01_005_bcode_skip':
                turn_obj['answer_check'] = {'dropped_policy_promises': 1, 'detail': []}
            q_recs.append({'id': cid, 'run': 1, 'passed': True, 'failures': [], 'attack_success': False, 'turns': [turn_obj]})
            q_tr.extend(_make_turn_trace(
                cid, 1, 1, user_text=c['turns'][0]['user'],
                steps=[{'reasoning': f'Kiểm tra chi tiết đơn A{idx}',
                        'tool_calls': [{'name': 'get_order', 'arguments': {'id': f'A{idx}'}}],
                        'tool_results': [long_payload if idx == 1 else f'{{"order":"A{idx}","status":"ok"}}']}],
                final_content=f'Đơn A{idx} đã được kiểm tra kỹ càng.',
                final_reasoning=f'Suy luận rõ ràng cho đơn A{idx}.',
            ))
        q_dir = root / 'run_qwen'
        _write_run_dir(q_dir, q_recs, q_tr, 'a' * 40)
        scores_path = root / 'scores.json'
        self.assertEqual(_run_cli('score', '--cases', str(cases_path), '--run', f'qwen={q_dir}', '--out', str(scores_path))[0], 0)

        j1 = root / 'judge_r1'
        self.assertEqual(_run_cli('export', '--scores', str(scores_path), '--out', str(j1), '--round', '1', '--seed', '7')[0], 0)
        mp1 = json.loads((j1 / 'map.json').read_text(encoding='utf-8'))

        def write_grp(grp: str, fn):
            vdir = j1 / 'verdicts' / grp
            vdir.mkdir(parents=True, exist_ok=True)
            for b, iids in mp1['batches'].items():
                lines = [json.dumps(fn(i, mp1['items'][i]), ensure_ascii=False) for i in iids]
                (vdir / f'{b}.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')

        def r1_a(iid, it):
            if it['case_id'] in ('t01_001_dat_kc', 't01_004_bad_quote'):
                return {'item_id': iid, 'verdict': 'dat', 'quote': it['text'][:25], 'reason': 'Đạt.'}
            return {'item_id': iid, 'verdict': 'khong_chac', 'quote': '', 'reason': 'Chưa chắc.'}

        def r1_b(iid, it):
            return {'item_id': iid, 'verdict': 'khong_chac', 'quote': '', 'reason': 'Bị cắt ở 3000 ký tự.'}

        write_grp('A', r1_a)
        write_grp('B', r1_b)
        adj1 = root / 'adj_r1.json'
        self.assertEqual(_run_cli('import', '--judge-dir', str(j1), '--scores', str(scores_path), '--out', str(adj1))[0], 0)
        return {'scores_path': scores_path, 'j1': j1, 'mp1': mp1, 'adj1': adj1}

    def test_arbiter_text_mismatch_aborts_before_writing(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w672-b-mismatch-') as td:
            root = Path(td)
            fx = self._setup_r1_with_tier_b(root)
            # Làm lệch text trong map.json gốc -> export --arbiter phải dừng có lỗi và không ghi gì
            mp1_path = fx['j1'] / 'map.json'
            tampered = json.loads(mp1_path.read_text(encoding='utf-8'))
            first_iid = next(iter(tampered['items']))
            tampered['items'][first_iid]['text'] = 'VAN BAN BI THAY DOI KHONG KHOP'
            mp1_path.write_text(json.dumps(tampered, ensure_ascii=False), encoding='utf-8')

            arb_dir = root / 'arb_fail'
            code, _, err = _run_cli(
                'export', '--arbiter', '--base', str(fx['adj1']), '--scores', str(fx['scores_path']),
                '--out', str(arb_dir), '--max-tool-chars', '8000',
            )
            self.assertEqual(code, 2)
            self.assertIn('không khớp', err)
            self.assertFalse(arb_dir.exists())

    def test_arbiter_export_import_handoff_and_strict_kckc(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w672-b-ok-') as td:
            root = Path(td)
            fx = self._setup_r1_with_tier_b(root)
            arb_dir = root / 'arb_kit'
            code, _, err = _run_cli(
                'export', '--arbiter', '--base', str(fx['adj1']), '--scores', str(fx['scores_path']),
                '--out', str(arb_dir), '--max-tool-chars', '8000', '--seed', '99',
            )
            self.assertEqual(code, 0, err)
            amp = json.loads((arb_dir / 'map.json').read_text(encoding='utf-8'))
            # B_code (t01_005_bcode_skip) không gửi trọng tài -> chỉ gửi 4 ứng viên A_code Tier B
            self.assertEqual(len(amp['candidates']), 4)
            self.assertNotIn('t01_005_bcode_skip#qwen#1', amp['candidates'])
            # Giữ nguyên item_id vòng gốc và nâng 3000 -> 8000 thấy được tail_fact của đơn A1
            self.assertTrue(set(amp['items']).issubset(set(fx['mp1']['items'])))
            a1_iid = amp['candidates']['t01_001_dat_kc#qwen#1']['item_ids'][0]
            self.assertIn('CON_HAN_BAO_HANH_12_THANG', amp['items'][a1_iid]['text'])
            self.assertEqual(amp['items'][a1_iid]['pair_r1'], ['dat', 'khong_chac'])

            # Ghi phiếu trọng tài:
            # - A1 (dat/kc): dat kèm trích dẫn từ phần >3000 ký tự -> lên A
            # - A2 (kc/kc): dat hợp lệ -> lên A ở luật bàn giao, giữ B ở --strict-kckc
            # - A3 (kc/kc): khong_dat hợp lệ -> xuống C
            # - A4 (dat/kc): dat trích dẫn bịa -> hạ khong_chac, giữ B
            for b, iids in amp['batches'].items():
                rows = []
                for iid in iids:
                    cid = amp['items'][iid]['case_id']
                    if cid == 't01_001_dat_kc':
                        rows.append({'item_id': iid, 'verdict': 'dat', 'quote': 'CON_HAN_BAO_HANH_12_THANG', 'reason': 'Đủ dữ kiện sau 8000 ký tự.'})
                    elif cid == 't01_002_kckc':
                        rows.append({'item_id': iid, 'verdict': 'dat', 'quote': amp['items'][iid]['text'][:25], 'reason': 'Đạt.'})
                    elif cid == 't01_003_to_c':
                        rows.append({'item_id': iid, 'verdict': 'khong_dat', 'quote': amp['items'][iid]['text'][:25], 'reason': 'Sai dữ kiện.'})
                    else:
                        rows.append({'item_id': iid, 'verdict': 'dat', 'quote': 'trich dan bia khong ton tai', 'reason': 'Bịa trích dẫn.'})
                (arb_dir / 'verdicts' / f'{b}.jsonl').write_text(
                    '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n',
                    encoding='utf-8',
                )

            # 1) Luật bàn giao (mặc định)
            out_handoff = root / 'adj_arb_handoff.json'
            code, _, err = _run_cli('import', '--arbiter', '--judge-dir', str(arb_dir), '--base', str(fx['adj1']), '--out', str(out_handoff))
            self.assertEqual(code, 0, err)
            res_h = json.loads(out_handoff.read_text(encoding='utf-8'))
            self.assertEqual(res_h['candidates']['t01_001_dat_kc#qwen#1']['tier'], 'A')
            self.assertEqual(res_h['candidates']['t01_002_kckc#qwen#1']['tier'], 'A')
            self.assertEqual(res_h['candidates']['t01_003_to_c#qwen#1']['tier'], 'C')
            self.assertEqual(res_h['candidates']['t01_004_bad_quote#qwen#1']['tier'], 'B')
            self.assertEqual(res_h['arbiter']['downgraded_quotes'], {'dat': 1})
            self.assertEqual(res_h['verdicts'][a1_iid]['arbiter'], 'dat')

            # 2) Luật chặt --strict-kckc: A2 (kc/kc) dù trọng tài dat vẫn giữ B
            out_strict = root / 'adj_arb_strict.json'
            code, _, err = _run_cli(
                'import', '--arbiter', '--judge-dir', str(arb_dir), '--base', str(fx['adj1']),
                '--strict-kckc', '--out', str(out_strict),
            )
            self.assertEqual(code, 0, err)
            res_s = json.loads(out_strict.read_text(encoding='utf-8'))
            self.assertEqual(res_s['candidates']['t01_001_dat_kc#qwen#1']['tier'], 'A')
            self.assertEqual(res_s['candidates']['t01_002_kckc#qwen#1']['tier'], 'B')
            self.assertEqual(res_s['candidates']['t01_003_to_c#qwen#1']['tier'], 'C')
            self.assertEqual(res_s['candidates']['t01_004_bad_quote#qwen#1']['tier'], 'B')
            self.assertTrue(res_s['arbiter']['strict_kckc'])


@unittest.skipUnless(HAS_W672, 'scripts/sft_select.py không có trong gói Colab')
class TestW672TierS(unittest.TestCase):
    def _build_tier_s_fixture(self, root: Path) -> dict:
        # 2 ca:
        # - c_multi (2 lượt): qwen#1 (tool: get_order -> search_knowledge) vs deepseek#1 (tool: get_order -> get_order) -> KHÁC chuỗi tool!
        # - c_same_tool (1 lượt): qwen#1 (tool: get_order) vs deepseek#1 (tool: get_order) vs qwen#2 (tool: get_order) -> 2 cặp ghép với mẫu chính qwen#1
        cases = [
            {'id': 't08_001_multi', 'category': 't08', 'title': 'Ca 2 lượt Tier S',
             'meta': {'suite': 'T08', 'template': 'tmpl_t08', 'style': 'chuan'},
             'turns': [
                 {'user': 'Kiểm tra đơn M1', 'expect': {'answer_all': ['M1'], 'answer_not': ['lỗi']}},
                 {'user': 'Chính sách đổi trả thế nào', 'expect': {'answer_all': ['7 ngày'], 'answer_not': ['lỗi']}},
             ]},
            {'id': 't01_002_same_tool', 'category': 't01', 'title': 'Ca 1 lượt cùng tool',
             'meta': {'suite': 'T01', 'template': 'tmpl_t01', 'style': 'chuan'},
             'turns': [{'user': 'Kiểm tra đơn M2', 'expect': {'answer_all': ['M2'], 'answer_not': ['lỗi']}}]},
        ]
        cases_path = root / 'cases.jsonl'
        cases_path.write_text(''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in cases), encoding='utf-8')

        q_recs, q_tr, d_recs, d_tr = [], [], [], []
        # c_multi qwen#1: 2 turns, tools [get_order], [search_knowledge]
        q_recs.append({'id': 't08_001_multi', 'run': 1, 'passed': True, 'failures': [], 'attack_success': False, 'turns': [
            {'answer': 'Đơn M1 đã giao thành công hôm qua tại kho Hà Nội.', 'tools': [{'name': 'get_order'}], 'error': None},
            {'answer': 'Theo tài liệu chính sách đổi trả 7 ngày, bạn giữ nguyên tem mác để gửi đổi.', 'tools': [{'name': 'search_knowledge'}], 'error': None},
        ]})
        q_tr.extend(_make_turn_trace(
            't08_001_multi', 1, 1, user_text='Kiểm tra đơn M1',
            steps=[{'reasoning': 'Tra cứu trạng thái đơn M1 qua get_order.',
                    'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'M1'}}],
                    'tool_results': ['{"order_id":"M1","status":"delivered","warehouse":"Ha Noi"}']}],
            final_content='Đơn M1 đã giao thành công hôm qua tại kho Hà Nội.',
            final_reasoning='Kết quả get_order xác nhận đơn M1 đã giao xong, đủ dữ kiện trả lời khách.',
        ))
        q_tr.extend(_make_turn_trace(
            't08_001_multi', 1, 2, user_text='Chính sách đổi trả thế nào',
            steps=[{'reasoning': 'Tìm chính sách đổi trả bằng search_knowledge.',
                    'tool_calls': [{'name': 'search_knowledge', 'arguments': {'query': 'doi tra'}}],
                    'tool_results': ['{"policy":"doi tra trong 7 ngay giu nguyen tem mac"}']}],
            final_content='Theo tài liệu chính sách đổi trả 7 ngày, bạn giữ nguyên tem mác để gửi đổi.',
            final_reasoning='Đã đối chiếu đúng tài liệu KB đổi trả 7 ngày và điều kiện giữ tem mác.',
        ))

        # c_multi deepseek#1: 2 turns, tools [get_order], [get_order] -> khác chuỗi tool với qwen#1
        d_recs.append({'id': 't08_001_multi', 'run': 1, 'passed': True, 'failures': [], 'attack_success': False, 'turns': [
            {'answer': 'Đơn M1 hiện báo đã hoàn tất giao hàng cho người nhận.', 'tools': [{'name': 'get_order'}], 'error': None},
            {'answer': 'Đơn M1 áp dụng đổi trả trong vòng 7 ngày kể từ lúc nhận hàng.', 'tools': [{'name': 'get_order'}], 'error': None},
        ]})
        d_tr.extend(_make_turn_trace(
            't08_001_multi', 1, 1, user_text='Kiểm tra đơn M1',
            steps=[{'reasoning': 'Kiểm tra trạng thái vận đơn M1.',
                    'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'M1'}}],
                    'tool_results': ['{"order_id":"M1","status":"delivered"}']}],
            final_content='Đơn M1 hiện báo đã hoàn tất giao hàng cho người nhận.',
            final_reasoning='Tool xác nhận trạng thái delivered của đơn M1.',
        ))
        d_tr.extend(_make_turn_trace(
            't08_001_multi', 1, 2, user_text='Chính sách đổi trả thế nào',
            steps=[{'reasoning': 'Xem lại thời hạn đổi trả trên đơn M1.',
                    'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'M1'}}],
                    'tool_results': ['{"order_id":"M1","return_days":7}']}],
            final_content='Đơn M1 áp dụng đổi trả trong vòng 7 ngày kể từ lúc nhận hàng.',
            final_reasoning='Hạn đổi trả trên đơn M1 là 7 ngày theo dữ liệu trả về.',
        ))

        # c_same_tool: qwen#1 (ít token hơn -> rank 0, mẫu chính), qwen#2, deepseek#1 cùng gọi [get_order]
        for r, ans, toks in [
            (1, 'Đơn M2 đang giao và dự kiến tới trước 18h hôm nay.', 20),
            (2, 'Đơn M2 hiện trên tuyến phát hàng buổi chiều nay.', 50),
        ]:
            q_recs.append({'id': 't01_002_same_tool', 'run': r, 'passed': True, 'failures': [], 'attack_success': False,
                           'turns': [{'answer': ans, 'tools': [{'name': 'get_order'}], 'error': None}]})
            q_tr.extend(_make_turn_trace(
                't01_002_same_tool', r, 1, user_text='Kiểm tra đơn M2',
                steps=[{'reasoning': f'Tra đơn M2 lượt chạy {r}.',
                        'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'M2'}}],
                        'tool_results': ['{"order_id":"M2","status":"shipping"}']}],
                final_content=ans,
                final_reasoning=f'Suy luận riêng của bản Q{r} về đơn M2 đang vận chuyển.',
                completion_tokens=toks,
            ))
        d_recs.append({'id': 't01_002_same_tool', 'run': 1, 'passed': True, 'failures': [], 'attack_success': False,
                       'turns': [{'answer': 'Đơn M2 đang trên đường giao, có mã vận đơn riêng của hãng.', 'tools': [{'name': 'get_order'}], 'error': None}]})
        d_tr.extend(_make_turn_trace(
            't01_002_same_tool', 1, 1, user_text='Kiểm tra đơn M2',
            steps=[{'reasoning': 'Kiểm tra vận đơn M2 của đối tác giao hàng.',
                    'tool_calls': [{'name': 'get_order', 'arguments': {'order_id': 'M2'}}],
                    'tool_results': ['{"order_id":"M2","status":"shipping"}']}],
            final_content='Đơn M2 đang trên đường giao, có mã vận đơn riêng của hãng.',
            final_reasoning='Suy luận riêng của bản đối tác về mã vận đơn M2.',
        ))

        q_dir, d_dir = root / 'run_qwen', root / 'run_ds'
        _write_run_dir(q_dir, q_recs, q_tr, 'a' * 40)
        _write_run_dir(d_dir, d_recs, d_tr, 'b' * 40)
        scores_path = root / 'scores.json'
        self.assertEqual(_run_cli('score', '--cases', str(cases_path), '--run', f'qwen={q_dir}', '--run', f'deepseek={d_dir}', '--out', str(scores_path))[0], 0)

        adj_path = root / 'adj_all_a.json'
        adj_path.write_text(json.dumps({
            'round': 2,
            'candidates': {
                't08_001_multi#qwen#1': {'case_id': 't08_001_multi', 'model': 'qwen', 'run': 1, 'code_tier': 'A_code', 'tier': 'A', 'item_ids': []},
                't08_001_multi#deepseek#1': {'case_id': 't08_001_multi', 'model': 'deepseek', 'run': 1, 'code_tier': 'A_code', 'tier': 'A', 'item_ids': []},
                't01_002_same_tool#qwen#1': {'case_id': 't01_002_same_tool', 'model': 'qwen', 'run': 1, 'code_tier': 'A_code', 'tier': 'A', 'item_ids': []},
                't01_002_same_tool#qwen#2': {'case_id': 't01_002_same_tool', 'model': 'qwen', 'run': 2, 'code_tier': 'A_code', 'tier': 'A', 'item_ids': []},
                't01_002_same_tool#deepseek#1': {'case_id': 't01_002_same_tool', 'model': 'deepseek', 'run': 1, 'code_tier': 'A_code', 'tier': 'A', 'item_ids': []},
            },
        }, ensure_ascii=False), encoding='utf-8')
        return {'scores_path': scores_path, 'adj_path': adj_path}

    def test_print_rubric_s(self) -> None:
        code, out, err = _run_cli('--print-rubric-s')
        self.assertEqual(code, 0, err)
        self.assertIn('8.000 ký tự', out)
        for token in ('Đầy đủ', 'Đúng trọng tâm', 'Giàu thông tin hữu ích', 'Dùng tool tiết kiệm',
                      'Dẫn đúng nguồn', 'Đúng quy trình', 'Rõ ràng với khách Việt', 'tot_hon', 'khac_biet'):
            self.assertIn(token, out)

    def test_export_seed_shuffle_and_import_tier_s_verification(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w672-c-') as td:
            root = Path(td)
            fx = self._build_tier_s_fixture(root)

            # Kiểm xáo mau_1/mau_2 xác định theo seed (cùng seed giống nhau, khác seed đổi thứ tự)
            s_dir_1 = root / 'tier_s_seed1'
            s_dir_1b = root / 'tier_s_seed1b'
            s_dir_2 = root / 'tier_s_seed2'
            for out_d, seed in ((s_dir_1, '11'), (s_dir_1b, '11'), (s_dir_2, '2026')):
                code, _, err = _run_cli(
                    'export-tier-s', '--scores', str(fx['scores_path']),
                    '--adjudicated', str(fx['adj_path']),
                    '--out', str(out_d), '--max-tool-chars', '8000', '--seed', seed,
                )
                self.assertEqual(code, 0, err)

            mp1 = json.loads((s_dir_1 / 'map.json').read_text(encoding='utf-8'))
            mp1b = json.loads((s_dir_1b / 'map.json').read_text(encoding='utf-8'))
            mp2 = json.loads((s_dir_2 / 'map.json').read_text(encoding='utf-8'))
            self.assertEqual(mp1['items'], mp1b['items'])
            order_1 = [(it['case_id'], it['turn'], it['mau_1']['candidate_key']) for it in mp1['items'].values()]
            order_2 = [(it['case_id'], it['turn'], it['mau_1']['candidate_key']) for it in mp2['items'].values()]
            self.assertNotEqual(order_1, order_2)

            # Có 3 cặp: (t08 qwen#1 vs ds#1, 2 lượt) + (t01 qwen#1 vs qwen#2, 1 lượt) + (t01 qwen#1 vs ds#1, 1 lượt) = 4 mục
            self.assertEqual(len(mp1['pairs']), 3)
            self.assertEqual(len(mp1['items']), 4)
            self.assertEqual(mp1['batch_size'], 20)
            raw_pkts = ''.join(p.read_text(encoding='utf-8') for p in sorted((s_dir_1 / 'packets').glob('batch-*.jsonl')))
            self.assertNotIn('qwen', raw_pkts.lower())
            self.assertNotIn('deepseek', raw_pkts.lower())
            pkt_rows = [json.loads(l) for l in raw_pkts.splitlines() if l.strip()]
            self.assertTrue(all(r['kind'] == 'sft_tier_s_cap' and 'mau_1' in r and 'mau_2' in r for r in pkt_rows))

            # Chuẩn bị phiếu chấm:
            # - c_multi (2 lượt):
            #   * qwen#1: đủ 7 trích dẫn hợp lệ ở CẢ 2 lượt -> Tier S = True!
            #   * deepseek#1: lượt 1 đủ 7 trích dẫn (S=True), lượt 2 S=False -> KHÔNG đạt Tier S (cần mọi lượt)!
            #   * khac_biet = 'chi_cau_chu' ở cả 2 lượt, nhưng tool_seq_diff = True -> cặp VẪN khác nhau (diff_kinds=['tool_seq'])!
            # - c_same_tool cặp (qwen#1 vs qwen#2):
            #   * qwen#1: đủ 7 trích dẫn -> S=True
            #   * qwen#2: thiếu tiêu chí '7' (chỉ có 6 trích dẫn) -> bị hạ S (downgraded_s)!
            #   * khac_biet = 'chi_cau_chu' + cùng tool -> different = False!
            # - c_same_tool cặp (qwen#1 vs deepseek#1):
            #   * qwen#1: đủ 7 trích dẫn -> S=True
            #   * deepseek#1: tiêu chí '1' lấy trích dẫn từ mẫu kia (qwen#1) -> bị hạ S (downgraded_s)!
            #   * khac_biet = 'thong_tin' + cùng tool -> different = True (diff_kinds=['thong_tin'])!
            def seven_valid(text: str) -> dict[str, str]:
                chunk = text.splitlines()[0][:20]
                return {str(k): chunk for k in range(1, 8)}

            for bname, iids in mp1['batches'].items():
                vrows = []
                for iid in iids:
                    it = mp1['items'][iid]
                    cid, turn = it['case_id'], it['turn']
                    m1_k, m2_k = it['mau_1']['candidate_key'], it['mau_2']['candidate_key']
                    m1_txt, m2_txt = it['mau_1']['text'], it['mau_2']['text']

                    def make_slot(ckey: str, my_txt: str, other_txt: str) -> dict:
                        if ckey == 't08_001_multi#deepseek#1' and turn == 2:
                            return {'S': False, 'bang_chung': {}, 'truot': [5]}
                        if ckey == 't01_002_same_tool#qwen#2':
                            bc = seven_valid(my_txt)
                            del bc['7']  # thiếu 1 trích dẫn -> phải hạ S
                            return {'S': True, 'bang_chung': bc, 'truot': []}
                        if ckey == 't01_002_same_tool#deepseek#1':
                            bc = seven_valid(my_txt)
                            # Trích dẫn lấy từ câu chỉ có trong mẫu kia (qwen#1) -> phải hạ S
                            bc['1'] = 'Suy luận riêng của bản Q1'
                            return {'S': True, 'bang_chung': bc, 'truot': []}
                        return {'S': True, 'bang_chung': seven_valid(my_txt), 'truot': []}

                    pair_cands = {m1_k, m2_k}
                    kb = 'thong_tin' if pair_cands == {'t01_002_same_tool#qwen#1', 't01_002_same_tool#deepseek#1'} else 'chi_cau_chu'
                    vrows.append({
                        'item_id': iid,
                        'mau_1': make_slot(m1_k, m1_txt, m2_txt),
                        'mau_2': make_slot(m2_k, m2_txt, m1_txt),
                        'tot_hon': 'mau_1',
                        'khac_biet': kb,
                        'reason': 'Đánh giá cặp.',
                    })
                (s_dir_1 / 'verdicts' / f'{bname}.jsonl').write_text(
                    '\n'.join(json.dumps(r, ensure_ascii=False) for r in vrows) + '\n',
                    encoding='utf-8',
                )

            out_s = root / 'adj_tier_s.json'
            code, _, err = _run_cli(
                'import-tier-s', '--judge-dir', str(s_dir_1),
                '--adjudicated', str(fx['adj_path']), '--out', str(out_s),
            )
            self.assertEqual(code, 0, err)
            res = json.loads(out_s.read_text(encoding='utf-8'))

            # Kiểm nhãn Tier S từng ứng viên
            self.assertTrue(res['tier_s']['t08_001_multi#qwen#1']['tier_s'])
            self.assertFalse(res['tier_s']['t08_001_multi#deepseek#1']['tier_s'])  # chỉ 1/2 lượt đạt S
            self.assertTrue(res['tier_s']['t01_002_same_tool#qwen#1']['tier_s'])
            self.assertFalse(res['tier_s']['t01_002_same_tool#qwen#2']['tier_s'])      # thiếu 1 trích dẫn -> hạ S
            self.assertFalse(res['tier_s']['t01_002_same_tool#deepseek#1']['tier_s'])  # trích dẫn từ mẫu kia -> hạ S

            # Kiểm danh sách hạ S
            dg_by_cand = {d['candidate_key']: d['invalid_criteria'] for d in res['downgraded_s']}
            self.assertEqual(dg_by_cand['t01_002_same_tool#qwen#2'], ['7'])
            self.assertEqual(dg_by_cand['t01_002_same_tool#deepseek#1'], ['1'])

            # Kiểm khác biệt cặp
            p_multi = res['s_pairs']['t08_001_multi#qwen#1__t08_001_multi#deepseek#1']
            self.assertTrue(p_multi['different'])
            self.assertEqual(p_multi['diff_kinds'], ['tool_seq'])

            p_qq = res['s_pairs']['t01_002_same_tool#qwen#1__t01_002_same_tool#qwen#2']
            self.assertFalse(p_qq['different'])
            self.assertEqual(p_qq['diff_kinds'], [])

            p_qd = res['s_pairs']['t01_002_same_tool#qwen#1__t01_002_same_tool#deepseek#1']
            self.assertTrue(p_qd['different'])
            self.assertEqual(p_qd['diff_kinds'], ['thong_tin'])


if __name__ == '__main__':
    unittest.main()
