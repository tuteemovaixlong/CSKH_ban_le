"""Unit tests W6.7.2 mục D (select mới + trần), E (sft_build nhiều mẫu + lớp phủ + chặn CJK), F (sft_cjk)."""
from __future__ import annotations

import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HAS_W672 = (
    (ROOT / 'scripts' / 'sft_select.py').is_file()
    and (ROOT / 'scripts' / 'sft_build.py').is_file()
    and (ROOT / 'scripts' / 'sft_cjk.py').is_file()
)

if HAS_W672:
    from scripts import sft_build, sft_cjk, sft_select  # noqa: E402
    from tests.test_w670_sft_select_build import _make_turn_trace  # noqa: E402


def _run_module(mod, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def _mk_cand(cid: str, model: str, run: int, rank: int, text: str, *, code_tier: str = 'A_code') -> dict:
    return {
        'case_id': cid,
        'model': model,
        'run': run,
        'rank': rank,
        'code_tier': code_tier,
        'tool_calls': 1,
        'completion_tokens': 30 + rank,
        'answer_chars': len(text),
        'turns_count': 1,
        'rail_turns': [],
        'turns_text': [text],
    }


def _write_scores(path: Path, cases_dict: dict[str, dict], root: Path) -> None:
    payload = {
        'cases_path': str(root / 'cases.jsonl'),
        'run_dirs': {'qwen': str(root / 'run_qwen'), 'deepseek': str(root / 'run_ds')},
        'repo_sha': {'qwen': 'a' * 40, 'deepseek': 'b' * 40},
        'cases': cases_dict,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')


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


@unittest.skipUnless(HAS_W672, 'scripts/sft_*.py không có trong gói Colab')
class TestW672Select(unittest.TestCase):
    def test_all_five_second_sample_rules_and_rule3_blocked_fallthrough(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w672-d-rules-') as td:
            root = Path(td)
            cases: dict[str, dict] = {}
            adj_cands: dict[str, dict] = {}
            tier_s: dict[str, dict] = {}
            s_pairs: dict[str, dict] = {}

            def add_case(cid: str, suite: str, tmpl: str, cands: list[dict]):
                cases[cid] = {
                    'case_id': cid, 'suite': suite, 'template': tmpl, 'style': 'chuan',
                    'actor': 'customer', 'turns_count': 1, 'candidates': cands, 'rejected': [],
                }
                for c in cands:
                    k = f"{cid}#{c['model']}#{c['run']}"
                    adj_cands[k] = {'case_id': cid, 'model': c['model'], 'run': c['run'],
                                    'code_tier': 'A_code', 'rank': c['rank'], 'item_ids': [], 'tier': 'A'}

            def mark_s(cid: str, model: str, run: int, val: bool = True):
                k = f'{cid}#{model}#{run}'
                tier_s[k] = {'case_id': cid, 'model': model, 'run': run, 'tier_s': val}

            def mark_pair(cid: str, k1: str, k2: str, different: bool):
                s_pairs[f'{k1}__{k2}'] = {'case_id': cid, 'primary': k1, 'other': k2, 'different': different}

            # Thêm các ca đệm (chỉ có 1 mẫu chính Qwen) để không chạm trần khung 50% và không chạm trần DeepSeek 35%
            for suite, tmpl in [('T01', 'tp1'), ('T02', 'tp2'), ('T05', 'tp5'), ('T06', 'tp6'), ('T08', 'tp8'), ('T11', 'tp11')]:
                for pad in range(1, 5):
                    pid = f'{suite.lower()}_pad_{pad}'
                    add_case(pid, suite, tmpl, [_mk_cand(pid, 'qwen', 1, 0, f'Mẫu đệm {pid}.')])

            # Luật 1 (mọi bộ, T01): chính Qwen, có DeepSeek S khác mẫu chính VÀ Qwen S -> ưu tiên luật 1 (DeepSeek S)
            add_case('t01_rule1', 'T01', 'tp1', [
                _mk_cand('t01_rule1', 'qwen', 1, 0, 'Đơn 1 đã giao thành công hôm qua.'),
                _mk_cand('t01_rule1', 'qwen', 2, 1, 'Thông tin khác hoàn toàn cho câu trả lời thứ hai về chính sách bảo hành.'),
                _mk_cand('t01_rule1', 'deepseek', 1, 2, 'Đơn 1 giao xong, bạn có thể đổi trả trong 7 ngày.'),
            ])
            mark_s('t01_rule1', 'qwen', 1, True)
            mark_s('t01_rule1', 'qwen', 2, True)
            mark_s('t01_rule1', 'deepseek', 1, True)
            mark_pair('t01_rule1', 't01_rule1#qwen#1', 't01_rule1#deepseek#1', True)
            mark_pair('t01_rule1', 't01_rule1#qwen#1', 't01_rule1#qwen#2', True)

            # Luật 2 (mọi bộ, T02): chính Qwen, DeepSeek S nhưng different=False (không đạt luật 1), Qwen S khác <0.85 -> luật 2
            add_case('t02_rule2', 'T02', 'tp2', [
                _mk_cand('t02_rule2', 'qwen', 1, 0, 'Sản phẩm còn size M màu đen tại kho trung tâm.'),
                _mk_cand('t02_rule2', 'qwen', 2, 1, 'Hiện tại mẫu áo có sẵn màu đen và trắng, bạn đặt hôm nay giao sau 2 ngày.'),
                _mk_cand('t02_rule2', 'deepseek', 1, 2, 'Sản phẩm còn size M màu đen.'),
            ])
            mark_s('t02_rule2', 'qwen', 1, True)
            mark_s('t02_rule2', 'qwen', 2, True)
            mark_s('t02_rule2', 'deepseek', 1, True)
            mark_pair('t02_rule2', 't02_rule2#qwen#1', 't02_rule2#deepseek#1', False)

            # Luật 3 (bộ khó T05): chính Qwen, DeepSeek A CHƯA chấm cặp Tier S -> nhận DeepSeek A (luật 3)
            add_case('t05_rule3_unjudged', 'T05', 'tp5', [
                _mk_cand('t05_rule3_unjudged', 'qwen', 1, 0, 'Đơn 5 được đổi size miễn phí lần đầu.'),
                _mk_cand('t05_rule3_unjudged', 'qwen', 2, 1, 'Khác nội dung hoàn toàn cho hướng dẫn gửi hàng đổi size qua bưu cục.'),
                _mk_cand('t05_rule3_unjudged', 'deepseek', 1, 2, 'Đơn 5 đủ điều kiện đổi size.'),
            ])

            # Luật 3 BỊ CHẶN → xét tiếp Luật 4 (quyết định 19/11): bộ khó T06, cặp Qwen-DeepSeek ĐÃ chấm Tier S với different=False
            add_case('t06_rule3_blocked_to_4', 'T06', 'tp6', [
                _mk_cand('t06_rule3_blocked_to_4', 'qwen', 1, 0, 'Đơn 6 hỗ trợ đổi hai chiều từ M sang L.'),
                _mk_cand('t06_rule3_blocked_to_4', 'qwen', 2, 1, 'Quy trình đổi hàng gồm xác nhận tồn kho size L và tạo phiếu thu hồi tận nhà.'),
                _mk_cand('t06_rule3_blocked_to_4', 'deepseek', 1, 2, 'Đơn 6 hỗ trợ đổi từ M sang L.'),
            ])
            mark_pair('t06_rule3_blocked_to_4', 't06_rule3_blocked_to_4#qwen#1', 't06_rule3_blocked_to_4#deepseek#1', False)

            # Luật 4 nhưng độ giống >= 0.85 (bộ khó T08) -> KHÔNG lấy mẫu thứ hai
            add_case('t08_rule4_too_sim', 'T08', 'tp8', [
                _mk_cand('t08_rule4_too_sim', 'qwen', 1, 0, 'Đơn 8 đang trên đường giao đến địa chỉ của bạn trong hôm nay.'),
                _mk_cand('t08_rule4_too_sim', 'qwen', 2, 1, 'Đơn 8 đang trên đường giao đến địa chỉ của bạn trong hôm nay!'),
            ])

            # Luật 5 (mẫu chính DeepSeek, bộ khó T11):
            # - t11_rule5_ok: có DeepSeek S khác mẫu chính -> nhận (luật 5)
            # - t11_rule5_no_s: chỉ có DeepSeek Tier A không phải S -> KHÔNG nhận (dù là bộ khó!)
            add_case('t11_rule5_ok', 'T11', 'tp11', [
                _mk_cand('t11_rule5_ok', 'deepseek', 1, 0, 'Ghi chú nội bộ: đơn 11 trễ 20h.'),
                _mk_cand('t11_rule5_ok', 'deepseek', 2, 1, 'Ghi chú nội bộ: kiểm tra cả phiếu bồi thường.'),
            ])
            mark_s('t11_rule5_ok', 'deepseek', 1, True)
            mark_s('t11_rule5_ok', 'deepseek', 2, True)
            mark_pair('t11_rule5_ok', 't11_rule5_ok#deepseek#1', 't11_rule5_ok#deepseek#2', True)

            add_case('t11_rule5_no_s', 'T11', 'tp11', [
                _mk_cand('t11_rule5_no_s', 'deepseek', 1, 0, 'Ghi chú 1.'),
                _mk_cand('t11_rule5_no_s', 'deepseek', 2, 1, 'Ghi chú 2.'),
            ])

            scores_path = root / 'scores.json'
            adj_path = root / 'adj.json'
            sel_path = root / 'selection.json'
            _write_scores(scores_path, cases, root)
            adj_path.write_text(json.dumps({
                'round': 2, 'candidates': adj_cands, 'tier_s': tier_s, 's_pairs': s_pairs,
            }, ensure_ascii=False), encoding='utf-8')

            code, _, err = _run_module(sft_select, 'select', '--scores', str(scores_path), '--adjudicated', str(adj_path), '--out', str(sel_path))
            self.assertEqual(code, 0, err)
            sel = json.loads(sel_path.read_text(encoding='utf-8'))

            seconds = {s['case_id']: (s['model'], s['run'], s['tier'], s['rule']) for s in sel['selected'] if s['role'] == 'second'}
            self.assertEqual(seconds['t01_rule1'], ('deepseek', 1, 'S', 1))
            self.assertEqual(seconds['t02_rule2'], ('qwen', 2, 'S', 2))
            self.assertEqual(seconds['t05_rule3_unjudged'], ('deepseek', 1, 'A', 3))
            self.assertEqual(seconds['t06_rule3_blocked_to_4'], ('qwen', 2, 'A', 4))
            self.assertNotIn('t08_rule4_too_sim', seconds)
            self.assertEqual(seconds['t11_rule5_ok'], ('deepseek', 2, 'S', 5))
            self.assertNotIn('t11_rule5_no_s', seconds)

            # Kiểm --max-per-case 1: chỉ mẫu chính, mỗi ca 1 mẫu
            sel1_path = root / 'selection_one.json'
            code, _, err = _run_module(
                sft_select, 'select', '--scores', str(scores_path), '--adjudicated', str(adj_path),
                '--max-per-case', '1', '--out', str(sel1_path),
            )
            self.assertEqual(code, 0, err)
            sel1 = json.loads(sel1_path.read_text(encoding='utf-8'))
            self.assertEqual(sel1['summary']['by_role']['second'], 0)
            self.assertEqual(len(sel1['selected']), len(cases))

    def test_template_cap_normal_and_easy_tight_t09_t10(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w672-d-tcap-') as td:
            root = Path(td)
            cases, adj_cands, tier_s, s_pairs = {}, {}, {}, {}

            def add_pair_case(cid: str, suite: str, tmpl: str, rule_kind: str):
                # rule_kind: 'r1' (DS S diff) hoặc 'r2' (Qwen S diff)
                cands = [
                    _mk_cand(cid, 'qwen', 1, 0, f'Mẫu chính của {cid} kiểm tra trạng thái đơn hàng.'),
                    _mk_cand(cid, 'qwen', 2, 1, f'Cách diễn giải hoàn toàn khác cho {cid} bổ sung quy trình bảo hành và phí vận chuyển.'),
                    _mk_cand(cid, 'deepseek', 1, 2, f'Bản đối chiếu sâu của {cid}.'),
                ]
                cases[cid] = {'case_id': cid, 'suite': suite, 'template': tmpl, 'style': 'chuan',
                              'actor': 'customer', 'turns_count': 1, 'candidates': cands, 'rejected': []}
                for c in cands:
                    k = f"{cid}#{c['model']}#{c['run']}"
                    adj_cands[k] = {'case_id': cid, 'model': c['model'], 'run': c['run'],
                                    'code_tier': 'A_code', 'rank': c['rank'], 'item_ids': [], 'tier': 'A'}
                if rule_kind == 'r1':
                    tier_s[f'{cid}#deepseek#1'] = {'case_id': cid, 'model': 'deepseek', 'run': 1, 'tier_s': True}
                    s_pairs[f'{cid}#qwen#1__{cid}#deepseek#1'] = {'case_id': cid, 'primary': f'{cid}#qwen#1', 'other': f'{cid}#deepseek#1', 'different': True}
                elif rule_kind == 'r2':
                    tier_s[f'{cid}#qwen#1'] = {'case_id': cid, 'model': 'qwen', 'run': 1, 'tier_s': True}
                    tier_s[f'{cid}#qwen#2'] = {'case_id': cid, 'model': 'qwen', 'run': 2, 'tier_s': True}

            # Khung thường T01: 4 ca chính -> trần floor(0.5 * 4) = 2; có 3 ca đủ chuẩn (2 luật 1, 1 luật 2) -> bỏ luật 2!
            add_pair_case('t01_a', 'T01', 'tmpl_norm', 'r1')
            add_pair_case('t01_b', 'T01', 'tmpl_norm', 'r1')
            add_pair_case('t01_c', 'T01', 'tmpl_norm', 'r2')
            add_pair_case('t01_d', 'T01', 'tmpl_norm', 'none')

            # Khung chặt T09: 4 ca chính -> trần floor(0.25 * 4) = 1; có 3 ca luật 2 -> giữ đúng 1 ca!
            for ch in ('a', 'b', 'c', 'd'):
                add_pair_case(f't09_{ch}', 'T09', 'tmpl_t09', 'r2' if ch != 'd' else 'none')

            # Khung chặt T10: 3 ca chính -> trần floor(0.25 * 3) = 0; có 2 ca luật 2 -> giữ 0!
            for ch in ('a', 'b', 'c'):
                add_pair_case(f't10_{ch}', 'T10', 'tmpl_t10', 'r2' if ch != 'c' else 'none')

            scores_path, adj_path, sel_path = root / 'scores.json', root / 'adj.json', root / 'selection.json'
            _write_scores(scores_path, cases, root)
            adj_path.write_text(json.dumps({'round': 2, 'candidates': adj_cands, 'tier_s': tier_s, 's_pairs': s_pairs}), encoding='utf-8')

            code, _, err = _run_module(
                sft_select, 'select', '--scores', str(scores_path), '--adjudicated', str(adj_path),
                '--seed', '2026', '--out', str(sel_path),
            )
            self.assertEqual(code, 0, err)
            sel = json.loads(sel_path.read_text(encoding='utf-8'))
            sec_by_tmpl: dict[str, list[dict]] = {}
            for s in sel['selected']:
                if s['role'] == 'second':
                    sec_by_tmpl.setdefault(s['template'], []).append(s)

            # T01 giữ đúng 2 ca luật 1, bỏ t01_c (luật 2)
            self.assertEqual(sorted(x['case_id'] for x in sec_by_tmpl['tmpl_norm']), ['t01_a', 't01_b'])
            # T09 giữ đúng 1 ca (25% của 4)
            self.assertEqual(len(sec_by_tmpl['tmpl_t09']), 1)
            # T10 giữ 0 ca (floor(0.25 * 3) = 0)
            self.assertNotIn('tmpl_t10', sec_by_tmpl)
            self.assertEqual(sel['summary']['caps']['template_cap_dropped_count'], 1 + 2 + 2)

    def test_deepseek_share_cap_order_and_never_drops_primary(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w672-d-dscap-') as td:
            root = Path(td)
            cases, adj_cands, tier_s, s_pairs = {}, {}, {}, {}

            def add(cid: str, suite: str, tmpl: str, cands: list[dict]):
                cases[cid] = {'case_id': cid, 'suite': suite, 'template': tmpl, 'style': 'chuan',
                              'actor': 'customer', 'turns_count': 1, 'candidates': cands, 'rejected': []}
                for c in cands:
                    adj_cands[f"{cid}#{c['model']}#{c['run']}"] = {
                        'case_id': cid, 'model': c['model'], 'run': c['run'],
                        'code_tier': 'A_code', 'rank': c['rank'], 'item_ids': [], 'tier': 'A',
                    }

            # 10 ca chính: 7 Qwen + 3 DeepSeek (chính = 30%), thêm 3 mẫu thứ hai DeepSeek:
            # - t01_s (không khó, Tier S, luật 1)  -> phải bị bỏ ĐẦU TIÊN (bộ không khó trước!)
            # - t05_a (bộ khó, Tier A, luật 3)     -> phải bị bỏ THỨ HAI (Tier A trước S!)
            # - t08_s (bộ khó, Tier S, luật 1)     -> phải được GIỮ (khi bỏ 2 cái kia: DS=4 / tổng=11 = 36.4% > 35%, bỏ nốt?
            #   Kiểm toán: nếu 8 Qwen + 3 DS chính (11 chính), thêm 3 DS thứ hai -> tổng 14, DS=6 (42.8%):
            #   bỏ t01_s -> 5/13 = 38.5% > 35%; bỏ t05_a -> 4/12 = 33.3% <= 35% -> DỪNG, GIỮ t08_s!)
            for i in range(1, 7):
                cid = f't03_q_{i}'
                add(cid, 'T03', 'tp_q', [_mk_cand(cid, 'qwen', 1, 0, f'Q {i}')])
            # 3 ca chính DeepSeek (không bao giờ được bỏ)
            for i in range(1, 4):
                cid = f't04_ds_prim_{i}'
                add(cid, 'T04', 'tp_ds', [_mk_cand(cid, 'deepseek', 1, 0, f'DS prim {i}')])
            # 3 ca có mẫu chính Qwen + mẫu thứ hai DeepSeek (mỗi khung có thêm 1 ca đệm để không chạm trần khung 50%)
            add('t01_pad', 'T01', 'tp1', [_mk_cand('t01_pad', 'qwen', 1, 0, 'pad')])
            add('t05_pad', 'T05', 'tp5', [_mk_cand('t05_pad', 'qwen', 1, 0, 'pad')])
            add('t08_pad', 'T08', 'tp8', [_mk_cand('t08_pad', 'qwen', 1, 0, 'pad')])
            # Tổng chính hiện tại: 6 + 3 + 3 = 12 (trong đó 9 Qwen, 3 DS) + 3 ca dưới = 15 chính (12 Qwen, 3 DS)...
            # Điều chỉnh: giảm tp_q xuống 2 ca để tổng chính = 2 + 3 + 3 + 3 = 11 (8 Qwen, 3 DS)!
            for i in range(3, 7):
                del cases[f't03_q_{i}']
                del adj_cands[f't03_q_{i}#qwen#1']

            add('t01_sec_nonhard_s', 'T01', 'tp1', [_mk_cand('t01_sec_nonhard_s', 'qwen', 1, 0, 'Q'), _mk_cand('t01_sec_nonhard_s', 'deepseek', 1, 1, 'DS')])
            tier_s['t01_sec_nonhard_s#deepseek#1'] = {'case_id': 't01_sec_nonhard_s', 'model': 'deepseek', 'run': 1, 'tier_s': True}
            s_pairs['p1'] = {'case_id': 't01_sec_nonhard_s', 'primary': 't01_sec_nonhard_s#qwen#1', 'other': 't01_sec_nonhard_s#deepseek#1', 'different': True}

            add('t05_sec_hard_a', 'T05', 'tp5', [_mk_cand('t05_sec_hard_a', 'qwen', 1, 0, 'Q'), _mk_cand('t05_sec_hard_a', 'deepseek', 1, 1, 'DS')])

            add('t08_sec_hard_s', 'T08', 'tp8', [_mk_cand('t08_sec_hard_s', 'qwen', 1, 0, 'Q'), _mk_cand('t08_sec_hard_s', 'deepseek', 1, 1, 'DS')])
            tier_s['t08_sec_hard_s#deepseek#1'] = {'case_id': 't08_sec_hard_s', 'model': 'deepseek', 'run': 1, 'tier_s': True}
            s_pairs['p3'] = {'case_id': 't08_sec_hard_s', 'primary': 't08_sec_hard_s#qwen#1', 'other': 't08_sec_hard_s#deepseek#1', 'different': True}

            scores_path, adj_path, sel_path = root / 'scores.json', root / 'adj.json', root / 'selection.json'
            _write_scores(scores_path, cases, root)
            adj_path.write_text(json.dumps({'round': 2, 'candidates': adj_cands, 'tier_s': tier_s, 's_pairs': s_pairs}), encoding='utf-8')

            code, _, err = _run_module(sft_select, 'select', '--scores', str(scores_path), '--adjudicated', str(adj_path), '--out', str(sel_path))
            self.assertEqual(code, 0, err)
            sel = json.loads(sel_path.read_text(encoding='utf-8'))

            dropped_ds = [d['case_id'] for d in sel['summary']['caps']['deepseek_cap_dropped']]
            # Phải bỏ bộ không khó (t01_sec_nonhard_s) trước, rồi đến bộ khó Tier A (t05_sec_hard_a), giữ lại bộ khó Tier S (t08_sec_hard_s)!
            self.assertEqual(dropped_ds, ['t01_sec_nonhard_s', 't05_sec_hard_a'])
            remaining_sec = [s['case_id'] for s in sel['selected'] if s['role'] == 'second']
            self.assertEqual(remaining_sec, ['t08_sec_hard_s'])
            self.assertTrue(sel['summary']['caps']['deepseek_cap_satisfied'])
            self.assertLessEqual(sel['summary']['deepseek_share'], 0.35)

            # Kiểm tình huống mẫu chính DeepSeek tự thân > 35%: không bao giờ bỏ mẫu chính!
            cases_only_ds = {
                't01_p1': {'case_id': 't01_p1', 'suite': 'T01', 'template': 'tp', 'style': 'chuan', 'actor': 'customer', 'turns_count': 1,
                           'candidates': [_mk_cand('t01_p1', 'deepseek', 1, 0, 'DS 1')], 'rejected': []},
                't01_p2': {'case_id': 't01_p2', 'suite': 'T01', 'template': 'tp', 'style': 'chuan', 'actor': 'customer', 'turns_count': 1,
                           'candidates': [_mk_cand('t01_p2', 'deepseek', 1, 0, 'DS 2')], 'rejected': []},
            }
            adj_only_ds = {
                't01_p1#deepseek#1': {'case_id': 't01_p1', 'model': 'deepseek', 'run': 1, 'code_tier': 'A_code', 'rank': 0, 'item_ids': [], 'tier': 'A'},
                't01_p2#deepseek#1': {'case_id': 't01_p2', 'model': 'deepseek', 'run': 1, 'code_tier': 'A_code', 'rank': 0, 'item_ids': [], 'tier': 'A'},
            }
            s2, a2, o2 = root / 's2.json', root / 'a2.json', root / 'o2.json'
            _write_scores(s2, cases_only_ds, root)
            a2.write_text(json.dumps({'round': 1, 'candidates': adj_only_ds}), encoding='utf-8')
            self.assertEqual(_run_module(sft_select, 'select', '--scores', str(s2), '--adjudicated', str(a2), '--out', str(o2))[0], 0)
            sel2 = json.loads(o2.read_text(encoding='utf-8'))
            self.assertEqual(len(sel2['selected']), 2)
            self.assertFalse(sel2['summary']['caps']['deepseek_cap_satisfied'])


@unittest.skipUnless(HAS_W672, 'scripts/sft_*.py không có trong gói Colab')
class TestW672BuildAndCjk(unittest.TestCase):
    def _build_cjk_workspace(self, root: Path) -> dict:
        cases = [
            # c_multi: 2 lượt, có 2 mẫu/ca (primary Qwen Tier S + second DeepSeek Tier A)
            # primary Qwen có CJK ở tin trợ lý trước (lượt 1 lặp trong lượt 2) và ở câu trả lời lượt 2 -> sửa bằng lớp phủ
            {'id': 't08_001_multi_cjk', 'category': 't08', 'title': 'Ca 2 lượt 2 mẫu có CJK',
             'meta': {'suite': 'T08', 'template': 'tmpl_t08', 'style': 'chuan'},
             'turns': [
                 {'user': 'Áo này có 褶皱 không shop?', 'expect': {'answer_all': ['áo'], 'answer_not': ['sai']}},
                 {'user': 'Vậy có đổi được không?', 'expect': {'answer_all': ['đổi'], 'answer_not': ['sai']}},
             ]},
            # c_unfixed: mẫu còn chữ Hán chưa sửa -> sft_build phải loại với lý do cjk_text
            {'id': 't01_002_unfixed_cjk', 'category': 't01', 'title': 'Ca còn chữ Hán chưa sửa',
             'meta': {'suite': 'T01', 'template': 'tmpl_t01', 'style': 'chuan'},
             'turns': [{'user': 'Kiểm tra đơn B2', 'expect': {'answer_all': ['B2'], 'answer_not': ['sai']}}]},
            # c_clean: khung thứ 3 để tách train/val
            {'id': 't02_003_clean', 'category': 't02', 'title': 'Ca sạch',
             'meta': {'suite': 'T02', 'template': 'tmpl_t02', 'style': 'chuan'},
             'turns': [{'user': 'Kiểm tra đơn B3', 'expect': {'answer_all': ['B3'], 'answer_not': ['sai']}}]},
        ]
        cases_path = root / 'cases.jsonl'
        cases_path.write_text(''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in cases), encoding='utf-8')

        q_recs, q_tr, d_recs, d_tr = [], [], [], []

        # c_multi Qwen run 1:
        # - Turn 1: câu trả lời có "bị褶皱." (dính liền chữ + dấu chấm) và suy luận có "hơn,能否 giúp"
        # - Turn 2: request.messages chứa lại tin trợ lý lượt 1 (kiểm bỏ dòng trùng khi export + kiểm áp lớp phủ trên tin trước!)
        #           và câu trả lời lượt 2 chứa các ca biên dấu cách: **đậm**, \n, (, chữ, và (xóa)
        t1_ans = 'Dạ áo kiểm tra thấy bị褶皱. Shop hỗ trợ đổi ạ.'
        t1_reason = 'Khách cần rõ hơn,能否 giúp đổi ngay.'
        t2_ans = (
            'Ghi chú từ褶皱**đậm** và từ褶皱\nDòng mới, '
            'cùng từ褶皱(ghi chú) và từ褶皱xong; áo bị 褶皱 lắm.'
        )
        q_recs.append({'id': 't08_001_multi_cjk', 'run': 1, 'passed': True, 'failures': [], 'attack_success': False, 'turns': [
            {'answer': t1_ans, 'tools': [], 'error': None},
            {'answer': t2_ans, 'tools': [], 'error': None},
        ]})
        q_tr.extend(_make_turn_trace(
            't08_001_multi_cjk', 1, 1, user_text=cases[0]['turns'][0]['user'],
            final_content=t1_ans, final_reasoning=t1_reason,
        ))
        # Turn 2 trace: đưa tin trợ lý lượt 1 vào request.messages
        t2_trace = _make_turn_trace(
            't08_001_multi_cjk', 1, 2, user_text=cases[0]['turns'][1]['user'],
            final_content=t2_ans, final_reasoning='Suy luận lượt 2 sạch hoàn toàn.',
        )
        t2_trace[-1]['request']['messages'] = [
            {'role': 'system', 'content': 'SYSTEM PROMPT'},
            {'role': 'user', 'content': cases[0]['turns'][0]['user']},
            {'role': 'assistant', 'content': t1_ans, 'reasoning': t1_reason},
            {'role': 'user', 'content': cases[0]['turns'][1]['user']},
        ]
        q_tr.extend(t2_trace)

        # c_multi DeepSeek run 1 (mẫu thứ hai sạch, không CJK; user turn 1 có CJK nhưng vẫn được giữ!)
        d_recs.append({'id': 't08_001_multi_cjk', 'run': 1, 'passed': True, 'failures': [], 'attack_success': False, 'turns': [
            {'answer': 'Dạ shop kiểm tra áo xong rồi ạ.', 'tools': [], 'error': None},
            {'answer': 'Dạ đơn của bạn đủ điều kiện đổi trong 7 ngày ạ.', 'tools': [], 'error': None},
        ]})
        d_tr.extend(_make_turn_trace('t08_001_multi_cjk', 1, 1, user_text=cases[0]['turns'][0]['user'],
                                     final_content='Dạ shop kiểm tra áo xong rồi ạ.', final_reasoning='Suy luận sạch.'))
        d_tr.extend(_make_turn_trace('t08_001_multi_cjk', 1, 2, user_text=cases[0]['turns'][1]['user'],
                                     final_content='Dạ đơn của bạn đủ điều kiện đổi trong 7 ngày ạ.', final_reasoning='Suy luận sạch lượt 2.'))

        # c_unfixed Qwen run 1: còn chữ Hán trong suy luận, không nằm trong file CSV sửa -> phải bị loại cjk_text
        q_recs.append({'id': 't01_002_unfixed_cjk', 'run': 1, 'passed': True, 'failures': [], 'attack_success': False,
                       'turns': [{'answer': 'Đơn B2 đã giao.', 'tools': [], 'error': None}]})
        q_tr.extend(_make_turn_trace('t01_002_unfixed_cjk', 1, 1, user_text='Kiểm tra đơn B2',
                                     final_content='Đơn B2 đã giao.', final_reasoning='Kiểm tra 确认 đơn B2.'))

        # c_clean Qwen run 1
        q_recs.append({'id': 't02_003_clean', 'run': 1, 'passed': True, 'failures': [], 'attack_success': False,
                       'turns': [{'answer': 'Đơn B3 đang giao.', 'tools': [], 'error': None}]})
        q_tr.extend(_make_turn_trace('t02_003_clean', 1, 1, user_text='Kiểm tra đơn B3',
                                     final_content='Đơn B3 đang giao.', final_reasoning='Đơn B3 hợp lệ.'))

        q_dir, d_dir = root / 'run_qwen', root / 'run_ds'
        _write_run_dir(q_dir, q_recs, q_tr, 'a' * 40)
        _write_run_dir(d_dir, d_recs, d_tr, 'b' * 40)

        scores_path = root / 'scores.json'
        self.assertEqual(_run_module(
            sft_select, 'score', '--cases', str(cases_path),
            '--run', f'qwen={q_dir}', '--run', f'deepseek={d_dir}', '--out', str(scores_path),
        )[0], 0)

        selection = {
            'scores_path': str(scores_path),
            'cases_path': str(cases_path),
            'run_dirs': {'qwen': str(q_dir), 'deepseek': str(d_dir)},
            'repo_sha': {'qwen': 'a' * 40, 'deepseek': 'b' * 40},
            'selected': [
                {'case_id': 't08_001_multi_cjk', 'template': 'tmpl_t08', 'suite': 'T08', 'model': 'qwen',
                 'source_model': 'qwen', 'run': 1, 'role': 'primary', 'tier': 'S', 'rule': None, 'run_dir': str(q_dir), 'turns_count': 2},
                {'case_id': 't08_001_multi_cjk', 'template': 'tmpl_t08', 'suite': 'T08', 'model': 'deepseek',
                 'source_model': 'deepseek', 'run': 1, 'role': 'second', 'tier': 'A', 'rule': 3, 'run_dir': str(d_dir), 'turns_count': 2},
                {'case_id': 't01_002_unfixed_cjk', 'template': 'tmpl_t01', 'suite': 'T01', 'model': 'qwen',
                 'source_model': 'qwen', 'run': 1, 'role': 'primary', 'tier': 'A', 'rule': None, 'run_dir': str(q_dir), 'turns_count': 1},
                {'case_id': 't02_003_clean', 'template': 'tmpl_t02', 'suite': 'T02', 'model': 'qwen',
                 'source_model': 'qwen', 'run': 1, 'role': 'primary', 'tier': 'A', 'rule': None, 'run_dir': str(q_dir), 'turns_count': 1},
            ],
        }
        sel_path = root / 'selection.json'
        sel_path.write_text(json.dumps(selection, ensure_ascii=False), encoding='utf-8')
        return {'cases_path': cases_path, 'scores_path': scores_path, 'sel_path': sel_path, 'q_dir': q_dir}

    def test_cjk_export_dedup_bom_no_overwrite_and_import_validation(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w672-f-valid-') as td:
            root = Path(td)
            fx = self._build_cjk_workspace(root)
            csv_path = root / 'cjk_dot1.csv'

            code, _, err = _run_module(
                sft_cjk, 'export', '--scores', str(fx['scores_path']),
                '--selection', str(fx['sel_path']), '--out', str(csv_path),
            )
            self.assertEqual(code, 0, err)
            raw_bytes = csv_path.read_bytes()
            self.assertTrue(raw_bytes.startswith(b'\xef\xbb\xbf'))  # UTF-8 BOM

            # Không ghi đè tệp đã có
            code_dup, _, _ = _run_module(
                sft_cjk, 'export', '--scores', str(fx['scores_path']),
                '--selection', str(fx['sel_path']), '--out', str(csv_path),
            )
            self.assertEqual(code_dup, 2)

            with open(csv_path, encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                self.assertEqual(reader.fieldnames, ['stt', 'ma_mau', 'luot', 'truong', 'chu_han', 'doan_chua', 'sua_thanh'])
                rows = list(reader)

            # Kiểm bỏ dòng trùng: t08 turn 1 có 2 đoạn (tra_loi + suy_luan), lặp trong request turn 2 phải bị bỏ ->
            # t08 tổng cộng 2 (turn 1) + 5 (turn 2) = 7 đoạn; t01 có 1 đoạn -> tổng 8 dòng!
            self.assertEqual(len(rows), 8)
            self.assertTrue(all(r['sua_thanh'] == '' for r in rows))
            self.assertTrue(any(' ⏎ ' in r['doan_chua'] for r in rows))

            # Kiểm đủ các lỗi khi import CSV: trống, còn CJK, >40 ký tự, thêm số, đoạn gốc không khớp vết
            bad_csv = root / 'bad.csv'
            bad_rows = [dict(r) for r in rows[:5]]
            bad_rows[0]['sua_thanh'] = ''                              # trống
            bad_rows[1]['sua_thanh'] = 'vẫn còn 漢字'                  # còn CJK
            bad_rows[2]['sua_thanh'] = 'a' * 41                        # > 40 ký tự
            bad_rows[3]['sua_thanh'] = 'thêm số 123 mới'               # thêm chữ số
            bad_rows[4]['sua_thanh'] = 'hợp lệ'
            bad_rows[4]['doan_chua'] = 'ngữ cảnh giả mạo⟦褶皱⟧không có trong vết'  # không khớp vết
            with open(bad_csv, 'w', encoding='utf-8-sig', newline='') as f:
                w = csv.DictWriter(f, fieldnames=sft_cjk.CSV_FIELDS)
                w.writeheader()
                w.writerows(bad_rows)

            out_edits = root / 'edits.jsonl'
            code_bad, out_bad, _ = _run_module(
                sft_cjk, 'import', '--csv', str(bad_csv), '--scores', str(fx['scores_path']), '--out', str(out_edits),
            )
            self.assertEqual(code_bad, 1)
            self.assertFalse(out_edits.exists())
            self.assertIn('chưa điền sua_thanh', out_bad)
            self.assertIn('còn chữ Hán', out_bad)
            self.assertIn('> 40', out_bad)
            self.assertIn('thêm chữ số', out_bad)
            self.assertIn('không tìm thấy đoạn gốc', out_bad)

    def test_cjk_spacing_delete_merge_and_build_multi_sample_overlay_and_guard(self) -> None:
        with tempfile.TemporaryDirectory(prefix='test-w672-ef-') as td:
            root = Path(td)
            fx = self._build_cjk_workspace(root)
            orig_trace_bytes = (fx['q_dir'] / 'shard-00.jsonl').read_bytes()

            # Xuất CSV chỉ cho ca t08 (để ca t01 giữ nguyên CJK và bị chặn bởi sft_build -> cjk_text)
            csv_path = root / 'dot1.csv'
            self.assertEqual(_run_module(
                sft_cjk, 'export', '--scores', str(fx['scores_path']),
                '--selection', str(fx['sel_path']), '--out', str(csv_path),
            )[0], 0)
            with open(csv_path, encoding='utf-8-sig', newline='') as f:
                all_rows = list(csv.DictReader(f))

            # Chỉ điền bản sửa cho các dòng của t08 (7 dòng), loại dòng t01 khỏi CSV này
            t08_rows = [r for r in all_rows if r['ma_mau'].startswith('t08_001_multi_cjk|')]
            self.assertEqual(len(t08_rows), 7)
            for r in t08_rows:
                if '能否' in r['chu_han']:
                    r['sua_thanh'] = 'bạn có thể'
                elif 'áo bị ⟦褶皱⟧ lắm' in r['doan_chua']:
                    r['sua_thanh'] = '(xóa)'
                else:
                    r['sua_thanh'] = 'nhăn'
            dot1_filled = root / 'dot1_filled.csv'
            with open(dot1_filled, 'w', encoding='utf-8-sig', newline='') as f:
                w = csv.DictWriter(f, fieldnames=sft_cjk.CSV_FIELDS)
                w.writeheader()
                w.writerows(t08_rows)

            edits_path = root / 'owner_edits_cjk.jsonl'
            # 1) --check-only: qua, không tạo tệp
            code, _, err = _run_module(
                sft_cjk, 'import', '--csv', str(dot1_filled), '--scores', str(fx['scores_path']),
                '--out', str(edits_path), '--check-only',
            )
            self.assertEqual(code, 0, err)
            self.assertFalse(edits_path.exists())

            # 2) Ghi trước 1 dòng thuộc source_csv khác + 1 dòng cũ cùng source_csv để kiểm luật gộp/ghi đè theo source_csv
            other_entry = {'case_id': 't99_other', 'model': 'qwen', 'run': 1, 'old': 'x', 'new': 'y', 'source_csv': 'dot0.csv'}
            stale_entry = {'case_id': 't88_stale', 'model': 'qwen', 'run': 1, 'old': 'x', 'new': 'y', 'source_csv': dot1_filled.name}
            edits_path.write_text(
                json.dumps(other_entry) + '\n' + json.dumps(stale_entry) + '\n',
                encoding='utf-8',
            )

            code, _, err = _run_module(
                sft_cjk, 'import', '--csv', str(dot1_filled), '--scores', str(fx['scores_path']), '--out', str(edits_path),
            )
            self.assertEqual(code, 0, err)
            merged_edits = [json.loads(l) for l in edits_path.read_text(encoding='utf-8').splitlines() if l.strip()]
            # Giữ dòng của dot0.csv, ghi đè dòng cũ của dot1_filled.csv
            self.assertEqual(len(merged_edits), 1 + 7)
            self.assertTrue(any(e['source_csv'] == 'dot0.csv' for e in merged_edits))
            self.assertFalse(any(e['case_id'] == 't88_stale' for e in merged_edits))

            # Kiểm từng quy tắc dấu cách và (xóa) trong edits tạo ra
            t08_edits = [e for e in merged_edits if e['source_csv'] == dot1_filled.name]
            joined_news = '\n'.join(e['new'] for e in t08_edits)
            self.assertIn('bị nhăn.', joined_news)                  # trái chữ, phải dấu chấm -> thêm trái, không thêm phải
            self.assertIn('hơn, bạn có thể giúp', joined_news)      # trái dấu phẩy, phải đã có cách -> thêm trái
            self.assertIn('từ nhăn**đậm**', joined_news)            # không thêm cách trước **
            self.assertIn('từ nhăn\nDòng mới', joined_news)         # không thêm cách trước xuống dòng
            self.assertIn('từ nhăn (ghi chú)', joined_news)         # thêm cách trước (
            self.assertIn('từ nhăn xong', joined_news)              # thêm cách cả hai bên
            self.assertIn('áo bị lắm.', joined_news)                # (xóa) gộp khoảng trắng hai bên

            # W6.7.3 F: dòng của run ngoài selection được bỏ qua và liệt kê.
            build_fail_dir = root / 'build_fail'
            code_fail, _, err_fail = _run_module(
                sft_build, '--selection', str(fx['sel_path']), '--cases', str(fx['cases_path']),
                '--out-dir', str(build_fail_dir), '--owner-edits', str(edits_path),
            )
            self.assertEqual(code_fail, 0, err_fail)
            stats_unused = json.loads((build_fail_dir / 'stats.json').read_text(encoding='utf-8'))
            self.assertTrue(stats_unused['unused_owner_edits'])
            self.assertTrue((build_fail_dir / 'train.jsonl').exists())

            # 4) Ghi tệp lớp phủ sạch (chỉ 7 dòng của t08) -> chạy sft_build
            clean_edits_path = root / 'clean_edits.jsonl'
            clean_edits_path.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in t08_edits), encoding='utf-8')
            build_dir = root / 'build_ok'
            code_ok, _, err_ok = _run_module(
                sft_build, '--selection', str(fx['sel_path']), '--cases', str(fx['cases_path']),
                '--out-dir', str(build_dir), '--owner-edits', str(clean_edits_path),
                '--val-ratio', '0.5', '--seed', '42',
            )
            self.assertEqual(code_ok, 0, err_ok)

            # Vết gốc trên đĩa KHÔNG BỊ SỬA
            self.assertEqual((fx['q_dir'] / 'shard-00.jsonl').read_bytes(), orig_trace_bytes)

            train_rows = [json.loads(l) for l in (build_dir / 'train.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
            val_rows = [json.loads(l) for l in (build_dir / 'val.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
            all_built = train_rows + val_rows
            stats = json.loads((build_dir / 'stats.json').read_text(encoding='utf-8'))
            report = (build_dir / 'build_report.md').read_text(encoding='utf-8')

            # Giữ: t08 primary (2 lượt) + t08 second (2 lượt) + t02 clean (1 lượt) = 5 mẫu; loại t01 vì cjk_text!
            self.assertEqual(len(all_built), 5)
            self.assertEqual(stats['cjk_rejected_count'], 1)
            self.assertEqual(stats['rejected']['by_reason']['cjk_text'], 1)
            self.assertIn('t01_002_unfixed_cjk', report)

            # Kiểm sample_id = {case_id}#t{turn} và {case_id}#t{turn}#2, giữ nguyên case_id và turn
            t08_samples = [r for r in all_built if r['meta']['case_id'] == 't08_001_multi_cjk']
            self.assertEqual(
                sorted(r['meta']['sample_id'] for r in t08_samples),
                ['t08_001_multi_cjk#t1', 't08_001_multi_cjk#t1#2', 't08_001_multi_cjk#t2', 't08_001_multi_cjk#t2#2'],
            )
            # Hai mẫu cùng ca luôn cùng tập (train hoặc val)
            in_train = [r for r in train_rows if r['meta']['case_id'] == 't08_001_multi_cjk']
            in_val = [r for r in val_rows if r['meta']['case_id'] == 't08_001_multi_cjk']
            self.assertIn(len(in_train), (0, 4))
            self.assertIn(len(in_val), (0, 4))

            # Kiểm nhãn meta và lớp phủ áp được trên cả tin cuối và tin trợ lý trước đó (lượt 2)
            t08_p_t2 = next(r for r in t08_samples if r['meta']['sample_id'] == 't08_001_multi_cjk#t2')
            self.assertEqual(t08_p_t2['meta']['source'], 'qwen')
            self.assertEqual(t08_p_t2['meta']['tier'], 'S')
            self.assertEqual(t08_p_t2['meta']['role'], 'primary')
            self.assertEqual(t08_p_t2['meta']['owner_edit'], 'cjk')
            self.assertEqual(t08_p_t2['meta']['turn'], 2)
            # Tin trợ lý trước đó (messages[2]) và tin cuối (messages[-1]) đều đã được phủ sạch CJK
            self.assertIn('bị nhăn.', t08_p_t2['messages'][2]['content'])
            self.assertIn('hơn, bạn có thể giúp', t08_p_t2['messages'][2]['reasoning_content'])
            self.assertIn('từ nhăn**đậm**', t08_p_t2['messages'][-1]['content'])
            self.assertIn('áo bị lắm.', t08_p_t2['messages'][-1]['content'])
            for msg in t08_p_t2['messages']:
                if msg['role'] == 'assistant':
                    self.assertIsNone(sft_select.CJK_RE.search(msg.get('content') or ''))
                    self.assertIsNone(sft_select.CJK_RE.search(msg.get('reasoning_content') or ''))

            # Mẫu thứ hai không sửa có owner_edit = None, role = 'second', source = 'deepseek', tier = 'A'
            t08_s_t1 = next(r for r in t08_samples if r['meta']['sample_id'] == 't08_001_multi_cjk#t1#2')
            self.assertEqual(t08_s_t1['meta']['source'], 'deepseek')
            self.assertEqual(t08_s_t1['meta']['tier'], 'A')
            self.assertEqual(t08_s_t1['meta']['role'], 'second')
            self.assertIsNone(t08_s_t1['meta']['owner_edit'])

            # Kiểm thống kê báo cáo mở rộng
            self.assertEqual(stats['owner_edit_samples'], 2)
            self.assertEqual(stats['by_suite_source_tier_role']['T08|qwen|S|primary'], 2)
            self.assertEqual(stats['by_suite_source_tier_role']['T08|deepseek|A|second'], 2)
            self.assertEqual(stats['by_suite_source_tier_role']['T02|qwen|A|primary'], 1)


if __name__ == '__main__':
    unittest.main()
