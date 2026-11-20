"""Unit tests W6.7.4 thẻ H3: lớp chấm ds_next trong export_judge_round và CLI export --ds-next."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

if not (Path(__file__).resolve().parents[1] / 'scripts/sft_select.py').is_file():
    raise unittest.SkipTest('Công cụ SFT không nằm trong gói Colab ứng dụng')

from scripts import sft_select as select  # noqa: E402
from tests.test_w670_sft_select_build import _make_turn_trace  # noqa: E402
from tests.test_w672_select_build_cjk import _mk_cand, _write_scores  # noqa: E402
from tests.w673_regression_pins import snapshot  # noqa: E402

# Pin SHA256 sinh từ mã gốc ff431e140b9fd1149359cad1162e366b93c5c816 cho fixture _build_ds_next_fixture.
ROUND2_DEFAULT_OFF_PINS: dict[str, str] = {
    'map.json': 'a12c70c3c78171dafaf0cefd5bd51cc86ed51725dd7a85b28e762950ba9dd92b',
    'packets/batch-01.jsonl': '0f785be60d32bbb0ebbee883c704adeb8c3fc4604625728dcde4751b8548d50f',
}


def _run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = select.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def _build_ds_next_fixture(root: Path) -> dict[str, Path]:
    """Tạo workspace tổng hợp gồm các loại ca: chỉ còn DS, còn Qwen, đã Tier A, đã Tier S, DS B_code."""
    cases_list = [
        {
            'id': 't01_001_ds_only',
            'category': 't01',
            'title': 'Tra cứu đơn hàng chỉ còn DeepSeek chưa chấm',
            'meta': {'suite': 'T01', 'template': 't01_tpl', 'style': 'chuan'},
            'turns': [{'user': 'Kiểm tra giúp đơn hàng SIM-O-101 đã giao chưa?', 'expect': {}}],
        },
        {
            'id': 't02_002_qwen_unjudged',
            'category': 't02',
            'title': 'Hỏi đổi trả đơn vẫn còn Qwen chưa chấm',
            'meta': {'suite': 'T02', 'template': 't02_tpl', 'style': 'chuan'},
            'turns': [{'user': 'Đơn SIM-O-102 muốn đổi size thì làm sao?', 'expect': {}}],
        },
        {
            'id': 't03_003_has_tier_a',
            'category': 't03',
            'title': 'Bảo hành sản phẩm đã có Qwen Tier A',
            'meta': {'suite': 'T03', 'template': 't03_tpl', 'style': 'chuan'},
            'turns': [{'user': 'Sản phẩm trong đơn SIM-O-103 bảo hành bao lâu?', 'expect': {}}],
        },
        {
            'id': 't04_004_has_tier_s',
            'category': 't04',
            'title': 'Khiếu nại giao chậm đã có Tier S',
            'meta': {'suite': 'T04', 'template': 't04_tpl', 'style': 'chuan'},
            'turns': [{'user': 'Đơn SIM-O-104 giao trễ quá hỗ trợ giúp mình.', 'expect': {}}],
        },
        {
            'id': 't05_005_ds_b_code_only',
            'category': 't05',
            'title': 'Hủy đơn chỉ còn DeepSeek B_code chưa chấm',
            'meta': {'suite': 'T05', 'template': 't05_tpl', 'style': 'chuan'},
            'turns': [{'user': 'Mình muốn hủy đơn hàng SIM-O-105 ngay.', 'expect': {}}],
        },
    ]
    cases_path = root / 'cases.jsonl'
    cases_path.write_text(
        '\n'.join(json.dumps(c, ensure_ascii=False) for c in cases_list) + '\n',
        encoding='utf-8',
    )

    qwen_dir = root / 'run_qwen'
    ds_dir = root / 'run_ds'
    qwen_dir.mkdir(parents=True, exist_ok=True)
    ds_dir.mkdir(parents=True, exist_ok=True)

    qwen_traces: list[dict] = []
    ds_traces: list[dict] = []

    def add_trace(model: str, cid: str, run: int, answer: str) -> None:
        target = qwen_traces if model == 'qwen' else ds_traces
        user_text = next(c['turns'][0]['user'] for c in cases_list if c['id'] == cid)
        target.extend(_make_turn_trace(
            cid, run, 1,
            user_text=user_text,
            final_content=answer,
            final_reasoning='',
        ))

    scores_cases: dict[str, dict] = {}

    # 1. Ca chưa Tier A, hết Qwen A_code chưa chấm, nhiều DeepSeek A_code chưa chấm (run=2 xếp trước run=1 trong a_cands).
    t01_cands = [
        _mk_cand('t01_001_ds_only', 'qwen', 1, 0, 'Dạ đơn SIM-O-101 của anh chị đã được xử lý ở bước kiểm tra đầu tiên.'),
        _mk_cand('t01_001_ds_only', 'deepseek', 3, 1, 'Dạ đơn SIM-O-101 đang trong quá trình vận chuyển tiêu chuẩn ạ.'),
        _mk_cand('t01_001_ds_only', 'deepseek', 2, 2, 'Dạ đơn SIM-O-101 đã giao thành công lúc 10 giờ sáng nay rồi ạ.'),
        _mk_cand('t01_001_ds_only', 'deepseek', 1, 3, 'Dạ đơn SIM-O-101 đã hoàn tất giao nhận tại địa chỉ đã đăng ký ạ.'),
    ]
    scores_cases['t01_001_ds_only'] = {
        'case_id': 't01_001_ds_only', 'suite': 'T01', 'template': 't01_tpl',
        'style': 'chuan', 'actor': 'customer', 'turns_count': 1,
        'candidates': t01_cands, 'rejected': [],
    }
    for c in t01_cands:
        add_trace(c['model'], c['case_id'], c['run'], c['turns_text'][0])

    # 2. Ca chưa Tier A, vẫn còn Qwen A_code chưa chấm -> chỉ xuất q_next, không kèm DeepSeek.
    t02_cands = [
        _mk_cand('t02_002_qwen_unjudged', 'qwen', 1, 0, 'Dạ anh chị vui lòng giữ nguyên tem mác sản phẩm SIM-O-102 để hỗ trợ đổi size ạ.'),
        _mk_cand('t02_002_qwen_unjudged', 'deepseek', 1, 1, 'Dạ shop hỗ trợ đổi size đơn SIM-O-102 trong vòng 7 ngày kể từ khi nhận hàng ạ.'),
    ]
    scores_cases['t02_002_qwen_unjudged'] = {
        'case_id': 't02_002_qwen_unjudged', 'suite': 'T02', 'template': 't02_tpl',
        'style': 'chuan', 'actor': 'customer', 'turns_count': 1,
        'candidates': t02_cands, 'rejected': [],
    }
    for c in t02_cands:
        add_trace(c['model'], c['case_id'], c['run'], c['turns_text'][0])

    # 3. Ca đã có Qwen Tier A -> giữ nguyên nhánh ds_pair.
    t03_cands = [
        _mk_cand('t03_003_has_tier_a', 'qwen', 1, 0, 'Dạ sản phẩm thuộc đơn SIM-O-103 được bảo hành chính hãng 12 tháng ạ.'),
        _mk_cand('t03_003_has_tier_a', 'deepseek', 1, 1, 'Dạ đơn SIM-O-103 áp dụng chính sách bảo hành điện tử 12 tháng toàn quốc ạ.'),
    ]
    scores_cases['t03_003_has_tier_a'] = {
        'case_id': 't03_003_has_tier_a', 'suite': 'T03', 'template': 't03_tpl',
        'style': 'chuan', 'actor': 'customer', 'turns_count': 1,
        'candidates': t03_cands, 'rejected': [],
    }
    for c in t03_cands:
        add_trace(c['model'], c['case_id'], c['run'], c['turns_text'][0])

    # 4. Ca đã có Tier S (DeepSeek) + còn DeepSeek A_code chưa chấm -> không chọn ds_next.
    t04_cands = [
        _mk_cand('t04_004_has_tier_s', 'deepseek', 1, 0, 'Dạ em thành thật xin lỗi vì đơn SIM-O-104 giao trễ và đã ưu tiên thúc đẩy ngay ạ.'),
        _mk_cand('t04_004_has_tier_s', 'deepseek', 2, 1, 'Dạ em đã kiểm tra hành trình đơn SIM-O-104 và báo đơn vị vận chuyển giao gấp ạ.'),
    ]
    scores_cases['t04_004_has_tier_s'] = {
        'case_id': 't04_004_has_tier_s', 'suite': 'T04', 'template': 't04_tpl',
        'style': 'chuan', 'actor': 'customer', 'turns_count': 1,
        'candidates': t04_cands, 'rejected': [],
    }
    for c in t04_cands:
        add_trace(c['model'], c['case_id'], c['run'], c['turns_text'][0])

    # 5. Ca chưa Tier A, hết Qwen A_code, chỉ còn DeepSeek B_code chưa chấm -> không chọn ds_next.
    t05_cands = [
        _mk_cand('t05_005_ds_b_code_only', 'qwen', 1, 0, 'Dạ em chưa thấy yêu cầu hủy đơn SIM-O-105 hợp lệ trong hệ thống ạ.'),
        _mk_cand('t05_005_ds_b_code_only', 'deepseek', 1, 1, 'Dạ đơn SIM-O-105 đang chờ xác nhận hủy từ kho xuất hàng của shop ạ.', code_tier='B_code'),
    ]
    scores_cases['t05_005_ds_b_code_only'] = {
        'case_id': 't05_005_ds_b_code_only', 'suite': 'T05', 'template': 't05_tpl',
        'style': 'chuan', 'actor': 'customer', 'turns_count': 1,
        'candidates': t05_cands, 'rejected': [],
    }
    for c in t05_cands:
        add_trace(c['model'], c['case_id'], c['run'], c['turns_text'][0])

    (qwen_dir / 'shard-00.jsonl').write_text(
        ''.join(json.dumps(t, ensure_ascii=False) + '\n' for t in qwen_traces),
        encoding='utf-8',
    )
    (ds_dir / 'shard-00.jsonl').write_text(
        ''.join(json.dumps(t, ensure_ascii=False) + '\n' for t in ds_traces),
        encoding='utf-8',
    )

    scores_path = root / 'scores.json'
    _write_scores(scores_path, scores_cases, root)

    adj_path = root / 'adj_r1.json'
    adj_payload = {
        'round': 1,
        'candidates': {
            't01_001_ds_only#qwen#1': {'case_id': 't01_001_ds_only', 'model': 'qwen', 'run': 1, 'tier': 'B'},
            't01_001_ds_only#deepseek#3': {'case_id': 't01_001_ds_only', 'model': 'deepseek', 'run': 3, 'tier': 'C'},
            't03_003_has_tier_a#qwen#1': {'case_id': 't03_003_has_tier_a', 'model': 'qwen', 'run': 1, 'tier': 'A'},
            't04_004_has_tier_s#deepseek#1': {'case_id': 't04_004_has_tier_s', 'model': 'deepseek', 'run': 1, 'tier': 'S'},
            't05_005_ds_b_code_only#qwen#1': {'case_id': 't05_005_ds_b_code_only', 'model': 'qwen', 'run': 1, 'tier': 'C'},
        },
    }
    adj_path.write_text(json.dumps(adj_payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'scores': scores_path, 'adj': adj_path}


class TestW674DsNext(unittest.TestCase):
    def test_ds_next_flag_behavior_and_edge_cases(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w674-ds-next-') as td:
            root = Path(td)
            fx = _build_ds_next_fixture(root)

            # (a) & (c) Mặc định tắt cờ -> không có ds_next, trùng pin SHA256 sinh từ ff431e1.
            out_off = root / 'judge_off'
            summary_off = select.export_judge_round(
                fx['scores'], out_off, round_no=2, after_paths=[fx['adj']],
            )
            self.assertEqual(summary_off['by_class'], {'ds_pair': 1, 'q_next': 1})
            map_off = json.loads((out_off / 'map.json').read_text(encoding='utf-8'))
            self.assertEqual(
                set(map_off['candidates'].keys()),
                {'t02_002_qwen_unjudged#qwen#1', 't03_003_has_tier_a#deepseek#1'},
            )
            off_files = {
                p.relative_to(out_off).as_posix(): p.read_bytes()
                for p in sorted(out_off.rglob('*')) if p.is_file()
            }
            self.assertEqual(snapshot(off_files, root), ROUND2_DEFAULT_OFF_PINS)

            # (a) & (b) & chọn đúng unjudged_ds[0], loại Tier S và DS B_code khi bật ds_next=True.
            out_on = root / 'judge_on'
            summary_on = select.export_judge_round(
                fx['scores'], out_on, round_no=2, after_paths=[fx['adj']], ds_next=True,
            )
            self.assertEqual(summary_on['by_class'], {'ds_next': 1, 'ds_pair': 1, 'q_next': 1})
            map_on = json.loads((out_on / 'map.json').read_text(encoding='utf-8'))
            cands_on = map_on['candidates']
            self.assertEqual(
                set(cands_on.keys()),
                {
                    't01_001_ds_only#deepseek#2',
                    't02_002_qwen_unjudged#qwen#1',
                    't03_003_has_tier_a#deepseek#1',
                },
            )
            self.assertEqual(cands_on['t01_001_ds_only#deepseek#2']['cls'], 'ds_next')
            self.assertNotIn('t01_001_ds_only#deepseek#1', cands_on)
            self.assertEqual(cands_on['t02_002_qwen_unjudged#qwen#1']['cls'], 'q_next')
            self.assertFalse(any(k.startswith('t02_002_qwen_unjudged#deepseek#') for k in cands_on))
            self.assertEqual(cands_on['t03_003_has_tier_a#deepseek#1']['cls'], 'ds_pair')
            self.assertFalse(any(k.startswith('t04_004_has_tier_s#') for k in cands_on))
            self.assertFalse(any(k.startswith('t05_005_ds_b_code_only#') for k in cands_on))

            # (d) Xuất -> nhập phiếu giả -> adjudicated có tier cho ứng viên ds_next.
            for group in ('A', 'B'):
                vdir = out_on / 'verdicts' / group
                vdir.mkdir(parents=True, exist_ok=True)
                for batch, ids in map_on['batches'].items():
                    rows = [
                        {
                            'item_id': iid,
                            'verdict': 'dat',
                            'quote': map_on['items'][iid]['text'][:25],
                            'reason': 'Dat chuan',
                        }
                        for iid in ids
                    ]
                    (vdir / f'{batch}.jsonl').write_text(
                        '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n',
                        encoding='utf-8',
                    )
            adj_r2_path = root / 'adj_r2.json'
            code, res = select.import_judge_round(out_on, fx['scores'], adj_r2_path)
            self.assertEqual(code, 0, res)
            self.assertEqual(res['candidates']['t01_001_ds_only#deepseek#2']['tier'], 'A')

    def test_cli_export_ds_next_default_off_and_on(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w674-cli-') as td:
            root = Path(td)
            fx = _build_ds_next_fixture(root)

            cli_off = root / 'cli_off'
            code_off, out_off_txt, err_off = _run_cli(
                'export',
                '--scores', str(fx['scores']),
                '--out', str(cli_off),
                '--round', '2',
                '--after', str(fx['adj']),
            )
            self.assertEqual(code_off, 0, err_off)
            self.assertIn("'ds_pair': 1, 'q_next': 1", out_off_txt)
            cli_off_files = {
                p.relative_to(cli_off).as_posix(): p.read_bytes()
                for p in sorted(cli_off.rglob('*')) if p.is_file()
            }
            self.assertEqual(snapshot(cli_off_files, root), ROUND2_DEFAULT_OFF_PINS)

            cli_on = root / 'cli_on'
            code_on, out_on_txt, err_on = _run_cli(
                'export',
                '--scores', str(fx['scores']),
                '--out', str(cli_on),
                '--round', '2',
                '--after', str(fx['adj']),
                '--ds-next',
            )
            self.assertEqual(code_on, 0, err_on)
            self.assertIn("'ds_next': 1", out_on_txt)
            map_on = json.loads((cli_on / 'map.json').read_text(encoding='utf-8'))
            self.assertEqual(map_on['candidates']['t01_001_ds_only#deepseek#2']['cls'], 'ds_next')


if __name__ == '__main__':
    unittest.main()
