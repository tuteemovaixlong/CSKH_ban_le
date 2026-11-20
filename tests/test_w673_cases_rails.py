"""Bất biến v4 và khung T14; chỉ phiếu, kỳ vọng và test fake."""
import copy
import hashlib
import json
import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path

if not (Path(__file__).resolve().parents[1]/'scripts/sft_cases.py').is_file():
    raise unittest.SkipTest('Công cụ SFT không nằm trong gói Colab ứng dụng')

from scripts import sft_cases, eval_regrade
from scripts.sft_templates import Brief, SftView, TEMPLATES
from scripts.sft_templates.t14_handoff import T14_TEMPLATES, shipment_slots, NO_REPEAT
from scripts.sft_utterances import validate_utterance, verify_utterances
from retailops.workflow.safety import HUMAN_REQUEST_KEYWORDS, EXTREME_RAGE_KEYWORDS
from retailops.guardrails.topic_filter import FORBIDDEN_TOPICS

FOUR = {'t07_xin_hotline_zalo','t03_hoa_don_vat','t07_phan_nan_lap_lai','t07_ngon_ngu_gay_gat'}


class CasesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        cls.cases,cls.briefs,_=sft_cases.generate_cases(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_byte_invariants_084b39b(self):
        # SHA ghim từ v4 sinh tại 084b39b (bộ sinh không đổi tới 0780af0).
        rows=(self.root/'cases_sft_v1.jsonl').read_bytes().splitlines(keepends=True)[:1200]
        outside=b''.join(line for line in rows if json.loads(line)['meta']['template'] not in FOUR)
        self.assertEqual(hashlib.sha256(outside).hexdigest(),'b1e9f16698b4a4661b899d4ebebc2267f469c7022fe5e95b080721d8dc1ec5e9')
        normalized=[]
        for line in rows:
            c=json.loads(line)
            if c['meta']['template'] in FOUR:
                if c['meta']['template']=='t07_xin_hotline_zalo':
                    self.assertEqual([k['source_key'] for k in c['knowledge']],['store_hours_contact.md'])
                    c.pop('knowledge')
                c.pop('final_state',None)
                for turn in c['turns']:
                    turn.pop('expect',None);turn.pop('fake_model',None)
                normalized.append((json.dumps(c,ensure_ascii=False)+'\n').encode())
        self.assertEqual(hashlib.sha256(b''.join(normalized)).hexdigest(),'b8af386a6c093876f83073fa3f88122ebf7735ccdf7e9020665c21bda217f91c')
        ids=[c['id'] for c in self.cases[:1200]]
        self.assertEqual(hashlib.sha256(json.dumps(ids).encode()).hexdigest(),'4956efee533fad96452adc585ad6b11d48fd77858b9c38aeb55d5b190d1c6887')
        briefs=b''.join((self.root/'briefs_sft_v1.jsonl').read_bytes().splitlines(keepends=True)[:1406])
        self.assertEqual(hashlib.sha256(briefs).hexdigest(),'068480e623e15374ea18ede4c4cd816537a4baf3343d610a2c0e73db84e7cd48')
        self.assertTrue(all(c['meta']['suite']=='T14' for c in self.cases[1200:]))

    def test_t14_count_shapes_slots_and_no_utterances(self):
        self.assertEqual((len(self.cases),len(self.briefs)),(1380,1646))
        t14=self.cases[1200:]
        self.assertEqual(Counter(c['meta']['template'] for c in t14),{t.template_id:10 for t in T14_TEMPLATES})
        counts={3:2,4:2,9:2,12:3,13:2}
        for number,tmpl in enumerate(T14_TEMPLATES,1):
            cases=[c for c in t14 if c['meta']['template']==tmpl.template_id]
            uses=Counter(c['meta']['slot_key'] for c in cases)
            self.assertLessEqual(max(uses.values()),3)
            for case in cases:
                self.assertEqual(len(case['turns']),counts.get(number,1))
                self.assertTrue(all(t['user']=='' for t in case['turns']))
                rows=case['final_state']['rows']
                if number!=18:
                    self.assertEqual(rows['handoff_episodes'],int(any(t['expect'].get('human_support') for t in case['turns'])))
                else:
                    self.assertNotIn('human_support',case['turns'][0]['expect'])
                for turn in case['turns']:
                    e=turn['expect']
                    if e.get('human_support') is False:
                        self.assertIn('request_human_support',e['tools_not_called'])
        for b in self.briefs[1406:]:
            self.assertTrue(b['rail_pass'])
            if b['template'] in {T14_TEMPLATES[n-1].template_id for n in (11,14,15,16,17,18)}:
                self.assertTrue(set(NO_REPEAT)<=set(b['must_not_include']))
        self.assertEqual(list(TEMPLATES)[-18:],[t.template_id for t in T14_TEMPLATES])
        view=SftView()
        for number,wanted in ((10,11),(11,12)):
            slots=T14_TEMPLATES[number-1].select(view)
            self.assertEqual(len(slots),wanted)
            self.assertEqual([o['external_order_id'] for o in slots],sorted(o['external_order_id'] for o in slots))
            histories={o['external_order_id']:s for o,s in shipment_slots(view)}
            for o in slots:
                s=histories[o['external_order_id']]
                self.assertTrue(any(any(p in str(e.get('fail_reason') or '').lower() for p in ('không liên lạc','không nghe máy')) for e in s['events']))
                self.assertIn(s['status'],('returned','delivery_failed') if number==10 else ('delivered',))

    def test_new_four_expectations(self):
        self.assertEqual(sft_cases.HANDOFF_EITHER,{'t12_xin_zalo','t07_ngon_ngu_gay_gat'})
        for c in self.cases[:1200]:
            template=c['meta']['template'];e=c['turns'][0]['expect']
            if template in ('t07_xin_hotline_zalo','t03_hoa_don_vat'):
                self.assertFalse(e['human_support']);self.assertIn('request_human_support',e['tools_not_called'])
                self.assertIn('search_knowledge',e['tools_called'])
                self.assertEqual(e['sources'],['store_hours_contact.md' if template.startswith('t07') else 'invoice_vat.md'])
                if template.startswith('t07'):self.assertEqual(len(e['answer_any']),2)
                else:
                    self.assertEqual(e['answer_all'],['7 ngày'])
                    self.assertNotIn('nhân viên',sum(e['answer_any'],[]))
            elif template=='t07_phan_nan_lap_lai':
                self.assertTrue(e['human_support']);self.assertIn('request_human_support',e['tools_called'])
                self.assertEqual(c['final_state']['rows']['handoff_episodes'],1)
            elif template=='t07_ngon_ngu_gay_gat':
                self.assertNotIn('human_support',e)
                self.assertEqual(e['tools_any'],[['list_orders','get_order','track_shipment']])

    def test_all_t14_fake_cases(self):
        path=self.root/'t14.jsonl'
        path.write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in self.cases[1200:]),encoding='utf-8')
        result=sft_cases.check_cases(self.root,cases_path=path)
        self.assertEqual(result['passed'],180,result)


class RailAndRegradeTests(unittest.TestCase):
    def test_rail_pass_false_serialization_and_verify(self):
        brief=Brief('b','c',1,'T14','tpl','chuan','p','i')
        self.assertNotIn('rail_pass',brief.to_dict())
        brief.rail_pass=True
        self.assertTrue(brief.to_dict()['rail_pass'])
        forbidden = re.search(r'\(([^|]+)\|',FORBIDDEN_TOPICS['medical']['patterns'][0])[1]
        texts=[HUMAN_REQUEST_KEYWORDS[0],EXTREME_RAGE_KEYWORDS[0],forbidden]
        for text in texts:
            self.assertFalse(validate_utterance(text,brief.to_dict(),set(),[])[0])
            self.assertIn('Bị rào an toàn chặn',validate_utterance(text,brief.to_dict(),set(),[])[1])
            self.assertTrue(validate_utterance(text,{**brief.to_dict(),'rail_pass':False},set(),[])[0])
        self.assertTrue(validate_utterance(chr(85),brief.to_dict(),set(),[])[0])
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'briefs_sft_v1.jsonl').write_text(json.dumps(brief.to_dict(),ensure_ascii=False)+'\n',encoding='utf-8')
            (root/'utterances_cache.jsonl').write_text(json.dumps({'brief_id':'b','user':texts[0]},ensure_ascii=False)+'\n',encoding='utf-8')
            self.assertTrue(any('Bị rào an toàn chặn' in p for p in verify_utterances(root)['problems']))

    def test_handoff_success_error_missing_status(self):
        case={'id':'x','turns':[{'expect':{'human_support':True}}]}
        for status,passed,unknown in (('ok',True,False),('error',False,False),(None,True,True)):
            tool={'name':'request_human_support'}
            if status is not None:tool['status']=status
            record={'id':'x','run':1,'passed':True,'failures':[],'turns':[{'tools':[tool],'answer':chr(65)}]}
            result=eval_regrade.regrade_record_v3(record,case,{})
            self.assertEqual(result['passed_v3'],passed)
            self.assertEqual('handoff_status_unknown' in result['flags_v3'],unknown)
            if not passed:self.assertTrue(any('human support was not requested' in f for f in result['failures_v3']))


if __name__=='__main__':
    unittest.main()
