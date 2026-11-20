"""Hồi quy offline nhiều lượt chạy, chống lộ gợi ý, tỉ trọng và Tier S."""
import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path

if not (Path(__file__).resolve().parents[1]/'scripts/sft_select.py').is_file():
    raise unittest.SkipTest('Công cụ SFT không nằm trong gói Colab ứng dụng')

from scripts import sft_select as select, sft_build as build, sft_cjk as cjk
from scripts.sft_hint_proxy import START, END, sha256
from tests.test_w670_sft_select_build import _build_synthetic_workspace, _make_turn_trace
from tests.test_w672_select_build_cjk import _mk_cand, _write_scores
from tests.w673_regression_pins import assert_snapshot, snapshot

ROOT = Path(__file__).resolve().parents[1]


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')


class PipelineTests(unittest.TestCase):
    def test_cjk_offsets_export_import_and_build_use_shared_mapping(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cid='t14_001_kiem_vet'
            case=dict(id=cid,meta=dict(template='tpl',suite='T14'),turns=[dict(user=chr(85),expect={})])
            (root/'cases').write_text(json.dumps(case)+'\n',encoding='utf-8')
            specs=[];logs=[]
            for label,offset in (('thuong',0),('goiy',4)):
                folder=root/label;folder.mkdir();records=[];traces=[]
                for run in range(1,5):
                    text=chr(0x4e00+offset+run)
                    records.append(dict(id=cid,run=run,passed=True,failures=[],turns=[dict(user=chr(85),answer=text,tools=[],model_calls=1)]))
                    traces.extend(_make_turn_trace(cid,run,1,user_text=chr(85),final_content=text,final_reasoning=''))
                write(folder/'merged.json',{'scenarios':records})
                (folder/'shard-00.jsonl').write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in traces),encoding='utf-8')
                for t in traces:
                    logs.append(dict(case_id=cid,turn=1,hinted=True,request_sha256=sha256(json.dumps(t['request'],ensure_ascii=False).encode('utf-8'))))
                specs.append(dict(label=label,model='qwen',dir=str(folder),run_offset=offset,hinted=bool(offset),hint_log=str(root/'log') if offset else None))
            (root/'log').write_text(''.join(json.dumps(row)+'\n' for row in logs),encoding='utf-8')
            scores=select.score_runs(root/'cases',{},runs=specs);write(root/'scores',scores)
            entry=scores['cases'][cid];self.assertEqual(len(entry['candidates']),8)
            selected=[select._make_selection_entry(entry,c,scores,tier='A',role='primary' if c['run']==1 else 'second',rule=None)
                      for c in entry['candidates']]
            write(root/'selection',{'selected':selected})
            cjk.export_cjk(root/'scores',root/'selection',root/'sheet')
            with (root/'sheet').open(encoding='utf-8-sig',newline='') as fh:rows=list(csv.DictReader(fh))
            self.assertEqual({r['ma_mau'] for r in rows},{f'{cid}|qwen|{r}' for r in range(1,9)})
            for row in rows:row['sua_thanh']=chr(65+int(row['ma_mau'].split('|')[-1]))
            with (root/'filled').open('w',encoding='utf-8-sig',newline='') as fh:
                writer=csv.DictWriter(fh,fieldnames=cjk.CSV_FIELDS);writer.writeheader();writer.writerows(rows)
            code,result=cjk.import_cjk(root/'filled',root/'scores',root/'edits')
            self.assertEqual(code,0,result)
            edits=[json.loads(x) for x in (root/'edits').read_text(encoding='utf-8').splitlines()]
            self.assertEqual({x['run'] for x in edits},set(range(1,9)))
            build.build_sft_dataset(root/'selection',root/'cases',root/'built',owner_edits_path=root/'edits')
            samples=[json.loads(x) for x in (root/'built'/'train.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual({s['meta']['run']:s['messages'][-1]['content'] for s in samples},
                             {run:chr(65+run) for run in range(1,9)})
            # Dạng scores cũ phải cho CSV xuất và lớp phủ nhập trùng từng byte.
            legacy=select.score_runs(root/'cases',{'qwen':root/'thuong'});write(root/'old_scores',legacy)
            legacy_selected=[select._make_selection_entry(legacy['cases'][cid],c,legacy,tier='A',role='primary',rule=None)
                             for c in legacy['cases'][cid]['candidates']]
            write(root/'old_selection',{'selected':legacy_selected})
            cjk.export_cjk(root/'old_scores',root/'old_selection',root/'old_sheet')
            assert_snapshot(self, 'pipeline_cjk_export', (root/'old_sheet').read_bytes(), root)
            with (root/'old_sheet').open(encoding='utf-8-sig',newline='') as fh:old_rows=list(csv.DictReader(fh))
            for row in old_rows:row['sua_thanh']=chr(65)
            with (root/'old_filled').open('w',encoding='utf-8-sig',newline='') as fh:
                writer=csv.DictWriter(fh,fieldnames=cjk.CSV_FIELDS);writer.writeheader();writer.writerows(old_rows)
            code, result = cjk.import_cjk(root/'old_filled',root/'old_scores',root/'old_edits')
            self.assertEqual(code, 0, result)
            assert_snapshot(self, 'pipeline_cjk_import', (root/'old_edits').read_bytes(), root)

    def test_unused_owner_edits_and_selected_unapplied_error(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); fx=_build_synthetic_workspace(root)
            scores=select.score_runs(fx['cases_path'],{'qwen':fx['qwen_dir']})
            cid=fx['cases'][0]['id'];cand=scores['cases'][cid]['candidates'][0]
            entry=select._make_selection_entry(scores['cases'][cid],cand,scores,tier='A',role='primary',rule=None)
            write(root/'selection',{'selected':[entry]})
            edit=dict(case_id=cid,model='qwen',run=99,old=chr(90)*16,new='')
            (root/'edits').write_text(json.dumps(edit)+'\n',encoding='utf-8')
            stats=build.build_sft_dataset(root/'selection',fx['cases_path'],root/'built',owner_edits_path=root/'edits')
            self.assertEqual(len(stats['unused_owner_edits']),1)
            self.assertEqual(stats['unused_owner_edits'][0]['run'],99)
            self.assertIn('unused_owner_edits',(root/'built'/'build_report.md').read_text(encoding='utf-8'))
            edit['run']=cand['run']
            (root/'edits').write_text(json.dumps(edit)+'\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'không áp được'):
                build.build_sft_dataset(root/'selection',fx['cases_path'],root/'blocked',owner_edits_path=root/'edits')
            self.assertFalse((root/'blocked'/'train.jsonl').exists())

    def test_multi_runs_offset_stale_leak_verification_and_build(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); fx=_build_synthetic_workspace(root)
            merged=json.loads((fx['qwen_dir']/'merged.json').read_text(encoding='utf-8'))
            original={c['id']:c for c in fx['cases']}
            for record in merged['scenarios']:
                for k,turn in enumerate(record['turns']):
                    turn['user']=original[record['id']]['turns'][k]['user']
            write(fx['qwen_dir']/'merged.json',merged)
            specs=[dict(label='r1',model='qwen',dir=str(fx['qwen_dir']),run_offset=0,hinted=False,hint_log=None),
                   dict(label='r2',model='qwen',dir=str(fx['qwen_dir']),run_offset=4,hinted=True,hint_log=None)]
            data=select.score_runs(fx['cases_path'],{},runs=specs)
            cid=fx['cases'][0]['id']; entry=data['cases'][cid]
            runs=entry['candidates']+entry['rejected']
            self.assertEqual(sorted(c['run'] for c in runs),list(range(1,9)))
            hinted=[c for c in runs if c.get('hinted')]
            self.assertTrue(all('hint_unverified' in c['flags'] for c in hinted))
            with self.assertRaises(ValueError):
                select.score_runs(fx['cases_path'],{},runs=[specs[0],{**specs[1],'run_offset':0}])
            logs=[]
            for line in (fx['qwen_dir']/'shard-00.jsonl').read_text(encoding='utf-8').splitlines():
                trace=json.loads(line)
                logs.append(dict(case_id=trace['case_id'],turn=trace['turn'],hinted=True,
                    request_sha256=sha256(json.dumps(trace['request'],ensure_ascii=False).encode('utf-8'))))
            (root/'log').write_text('\n'.join(json.dumps(row) for row in logs),encoding='utf-8')
            specs[1]['hint_log']=str(root/'log')
            data=select.score_runs(fx['cases_path'],{},runs=specs)
            self.assertTrue(all('hint_unverified' not in c['flags'] for c in data['cases'][cid]['candidates']))
            chosen=next(c for c in data['cases'][cid]['candidates'] if c['hinted'])
            selection={'selected':[select._make_selection_entry(data['cases'][cid],chosen,data,tier='A',role='primary',rule=None)]}
            write(root/'selection',selection)
            stats=build.build_sft_dataset(root/'selection',fx['cases_path'],root/'build')
            self.assertEqual(stats['by_hinted'],{'false':0,'true':1})
            sample=json.loads((root/'build'/'train.jsonl').read_text(encoding='utf-8').splitlines()[0])
            self.assertTrue(sample['meta']['hinted']);self.assertEqual(sample['meta']['run'],chosen['run'])
            self.assertIn('hinted',(root/'build'/'build_report.md').read_text(encoding='utf-8'))
            # Chỉ lời nhắc hiện tại đổi; không tạo câu khách mới.
            cases=copy.deepcopy(fx['cases']);cases[0]['turns'][0]['user']+=chr(88)
            fx['cases_path'].write_text('\n'.join(json.dumps(c,ensure_ascii=False) for c in cases),encoding='utf-8')
            changed=select.score_runs(fx['cases_path'],{'qwen':fx['qwen_dir']})
            self.assertTrue(all('stale_input' in c['reject_reasons'] for c in changed['cases'][cid]['rejected']))
            fx['cases_path'].write_text('\n'.join(json.dumps(c,ensure_ascii=False) for c in fx['cases']),encoding='utf-8')
            traces=[json.loads(x) for x in (fx['qwen_dir']/'shard-00.jsonl').read_text(encoding='utf-8').splitlines()]
            for t in traces:
                t['response']['reasoning']=START
            (fx['qwen_dir']/'shard-00.jsonl').write_text('\n'.join(json.dumps(t,ensure_ascii=False) for t in traces),encoding='utf-8')
            changed=select.score_runs(fx['cases_path'],{},runs=specs)
            self.assertTrue(any('hint_leak' in c['reject_reasons'] for c in changed['cases'][cid]['rejected'] if c['hinted']))
            self.assertTrue(changed['cases'][cid]['candidates'])  # lượt không gợi ý không áp luật hint_leak.
            for t in traces:
                t['response']['reasoning']=END
            (fx['qwen_dir']/'shard-00.jsonl').write_text('\n'.join(json.dumps(t,ensure_ascii=False) for t in traces),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'chuỗi đánh dấu'):
                build.build_sft_dataset(root/'selection',fx['cases_path'],root/'blocked')
            self.assertFalse((root/'blocked'/'train.jsonl').exists())

    def test_legacy_score_export_import_select_build_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fx=_build_synthetic_workspace(root)
            dirs={'qwen':fx['qwen_dir'],'deepseek':fx['ds_dir']}
            write(root/'scores',select.score_runs(fx['cases_path'],dirs))
            assert_snapshot(self, 'pipeline_scores', (root/'scores').read_bytes(), root)
            for round_no in (1,2):
                out=root/f'judge{round_no}'
                after=None if round_no==1 else [root/'adj']
                select.export_judge_round(root/'scores',out,round_no=round_no,after_paths=after)
                files={p.relative_to(out).as_posix():p.read_bytes() for p in out.rglob('*') if p.is_file()}
                assert_snapshot(self, 'pipeline_round_'+str(round_no), files, root)
                if round_no==1:
                    judge=root/'import_judge'
                    select.export_judge_round(root/'scores',judge)
                    mapping=json.loads((judge/'map.json').read_text(encoding='utf-8'))
                    for group in ('A','B'):
                        folder=judge/'verdicts'/group;folder.mkdir(parents=True)
                        for batch,ids in mapping['batches'].items():
                            rows=[dict(item_id=iid,verdict='dat',quote=mapping['items'][iid]['text'][:25],reason=chr(82)) for iid in ids]
                            (folder/f'{batch}.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows),encoding='utf-8')
                    code, result = select.import_judge_round(judge,root/'scores',root/'imported')
                    self.assertEqual(code, 0, result)
                    assert_snapshot(self, 'pipeline_import', (root/'imported').read_bytes(), root)
                    scores=json.loads((root/'scores').read_text())
                    judged={f"{cid}#{c['model']}#{c['run']}":dict(case_id=cid,model=c['model'],run=c['run'],tier='A')
                            for cid,entry in scores['cases'].items() for c in entry['candidates']}
                    write(root/'adj',{'candidates':judged})
            select.select_candidates(root/'scores',[root/'adj'],root/'selection',max_per_case=1)
            assert_snapshot(self, 'pipeline_select', {
                'selection':(root/'selection').read_bytes(),
                'selection_report.md':(root/'selection_report.md').read_bytes(),
            }, root)
            build.build_sft_dataset(root/'selection',fx['cases_path'],root/'build')
            assert_snapshot(self, 'pipeline_build', {
                p.name:p.read_bytes() for p in (root/'build').iterdir() if p.is_file()
            }, root)

    def test_pinned_bytes_normalize_only_workspace_paths_and_newlines(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first=json.dumps({'path':str(Path(a)/'run'),'content':chr(65)*3},indent=2).encode()
            second=json.dumps({'path':str(Path(b)/'run'),'content':chr(65)*3},indent=2).encode()
            self.assertEqual(snapshot(first,Path(a)),snapshot(second,Path(b)))
            self.assertEqual(snapshot(first,Path(a)),snapshot(first.replace(b'\n',b'\r\n'),Path(a)))
            changed=json.dumps({'path':str(Path(b)/'run'),'content':chr(66)*3},indent=2).encode()
            self.assertNotEqual(snapshot(first,Path(a)),snapshot(changed,Path(b)))
            self.assertNotEqual(snapshot(first,Path(a)),snapshot(second.replace(b'  ',b' '),Path(b)))

    def test_caps_no_draft_removed_and_unhinted_preferred(self):
        self.assertNotIn('T11',select.HARD_SUITES)
        self.assertNotIn('T14',select.HARD_SUITES);self.assertIn('T14',select.EASY_TIGHT)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); entries={}; adj={}; cases=[]
            for i,mode in enumerate(['draft']*3+['summary']*8+['ask']*8+['']*8):
                cid=f't11_{i}';suite='T11' if mode else 'T01'
                candidates=[_mk_cand(cid,'qwen',run,run-1,chr(65+run)*16) for run in (1,2)]
                candidates[0]['hinted']=True;candidates[1]['hinted']=False
                entries[cid]=dict(case_id=cid,template='tpl'+suite,suite=suite,candidates=candidates,rejected=[],turns_count=1)
                cases.append(dict(id=cid,turns=[dict(mode=mode)]))
                for c in candidates:
                    adj[f"{cid}#qwen#{c['run']}"]=dict(case_id=cid,model='qwen',run=c['run'],tier='A')
            (root/'cases.jsonl').write_text('\n'.join(json.dumps(c) for c in cases),encoding='utf-8')
            _write_scores(root/'scores',entries,root);write(root/'adj',{'candidates':adj})
            plain=select.select_candidates(root/'scores',[root/'adj'],root/'sel',max_per_case=1)
            self.assertTrue(all(x['run']==2 for x in plain['selected']))
            before=(root/'sel').read_bytes()
            select.select_candidates(root/'scores',[root/'adj'],root/'sel',max_per_case=1,suite_caps={},mode_caps={})
            self.assertEqual(before,(root/'sel').read_bytes())
            capped=select.select_candidates(root/'scores',[root/'adj'],root/'sel',max_per_case=1,
                suite_caps={'T11':.5},mode_caps={'T11:summary':.25,'T11:ask':.45})
            kept={x['case_id'] for x in capped['selected']}
            self.assertTrue({'t11_0','t11_1','t11_2'}<=kept)
            self.assertTrue(kept<={x['case_id'] for x in plain['selected']})
            self.assertTrue(capped['summary']['proportion_caps']['dropped'])
            self.assertIn('by_suite_mode_role',capped['summary']['proportion_caps'])
            self.assertIn('Trần tỉ trọng',(root/'selection_report.md').read_text(encoding='utf-8'))
            # T11 không có S thì không được thêm mẫu thứ hai theo luật 3/4.
            no_s=select.select_candidates(root/'scores',[root/'adj'],root/'sel',max_per_case=2)
            self.assertFalse(any(x['role']=='second' for x in no_s['selected'] if x['suite']=='T11'))
            for entry in entries.values():
                for c in entry['candidates']: c['hinted']=False
            for c in adj.values():c['tier']='S'
            _write_scores(root/'scores',entries,root);write(root/'adj',{'candidates':adj})
            with_s=select.select_candidates(root/'scores',[root/'adj'],root/'sel',max_per_case=2,
                suite_caps={'T11':.12},mode_caps={'T11:summary':.25,'T11:ask':.45})
            drops=with_s['summary']['proportion_caps']['dropped']
            self.assertTrue(any(d['role']=='second' for d in drops))
            self.assertTrue(all('draft' not in d['modes'] for d in drops))
            for mode in ('ask','summary'):
                roles=[d['role'] for d in drops if mode in d['modes']]
                if 'primary' in roles and 'second' in roles:
                    self.assertLess(max(i for i,x in enumerate(roles) if x=='second'),min(i for i,x in enumerate(roles) if x=='primary'))
            self.assertTrue({'t11_0','t11_1','t11_2'}<={x['case_id'] for x in with_s['selected']})


if __name__ == '__main__':
    unittest.main()
