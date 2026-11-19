"""Kiểm offline proxy và phiếu đỡ bằng ký hiệu giả, không soạn nội dung gợi ý."""
import concurrent.futures
import csv
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

if not (Path(__file__).resolve().parents[1]/'scripts/sft_hint_proxy.py').is_file():
    raise unittest.SkipTest('Công cụ SFT không nằm trong gói Colab ứng dụng')

from scripts.sft_hint_proxy import HintIndex, START, END, make_server, prompt_for_turn, load_scopes
from scripts.sft_hints import export_hints, import_hints, FIELDS, CASE_FIELDS


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def fake_hint(**key):
    # Ký hiệu kiểm giao thức, không chứa hướng dẫn nghiệp vụ.
    text = hashlib.sha256(json.dumps(key,sort_keys=True).encode()).hexdigest()
    return {**key, 'hint': text, 'sha256': digest(text)}


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.case = {'id': 't14_test', 'meta': {'template': 'tpl'}, 'turns': [{'user': chr(85)}]}
        self.payload = {'messages': [{'role': 'system', 'content': chr(83)},
                                     {'role': 'user', 'content': chr(85)}],
                        'tools': [{'type': 'function'}], 'max_tokens': 2048, 'temperature': .6}

    def test_exact_priority_staff_ambiguity_and_no_hint(self):
        hints = [fake_hint(template='tpl', turn=None), fake_hint(case_id='t14_test', turn=1)]
        changed, info = HintIndex([self.case], hints).inject(self.payload)
        self.assertTrue(info['hinted'])
        self.assertEqual(changed['messages'][0]['content'], chr(83) + '\n\n' + START + '\n' + hints[1]['hint'] + '\n' + END)
        self.assertEqual(changed['messages'][1:], self.payload['messages'][1:])
        self.assertEqual({k:v for k,v in changed.items() if k != 'messages'},
                         {k:v for k,v in self.payload.items() if k != 'messages'})
        for cases, rows, only in (([self.case]*2, hints, None), ([self.case], [], None),
                                   ([], hints, None), ([self.case], hints, set())):
            unchanged, info = HintIndex(cases, rows, only).inject(self.payload)
            self.assertEqual(unchanged, self.payload)
            self.assertEqual(info['reason'], 'no_hint')
        staff = {**self.case, 'actor': 'staff_case_assist', 'turns': [{'mode': 'draft', 'user': chr(81)}]}
        payload = json.loads(json.dumps(self.payload))
        payload['messages'][-1]['content'] = prompt_for_turn(staff, staff['turns'][0])
        self.assertTrue(HintIndex([staff], hints).inject(payload)[1]['hinted'])
        for remaining, selected in ((hints[:1], hints[0]),
                                    ([fake_hint(template='tpl', turn=1), hints[0]], fake_hint(template='tpl', turn=1)),
                                    ([fake_hint(case_id='t14_test', turn=None), hints[0]], fake_hint(case_id='t14_test', turn=None))):
            self.assertEqual(HintIndex([self.case], remaining).inject(self.payload)[1]['hint_sha256'], selected['sha256'])

    def test_http_parallel_headers_log_and_https_transport(self):
        captured = []
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                captured.append((self.path, self.headers.get('Authorization'), b''))
                self.send_response(200); self.end_headers(); self.wfile.write(self.path.encode())
            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                captured.append((self.path, self.headers.get('Authorization'), body))
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
        with tempfile.TemporaryDirectory() as td:
            upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
            proxy = make_server(('127.0.0.1', 0), f'http://127.0.0.1:{upstream.server_port}',
                                HintIndex([self.case], [fake_hint(template='tpl', turn=None)]), Path(td)/'log')
            for server in (upstream, proxy):
                threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{proxy.server_port}'
            def send(i):
                payload = json.loads(json.dumps(self.payload))
                if i % 2:
                    payload['messages'][-1]['content'] = chr(86)
                request = urllib.request.Request(base+'/v1/chat/completions',
                    data=json.dumps(payload).encode(), headers={'Authorization':'Bearer TEST', 'Content-Type':'application/json'})
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.read()
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                    self.assertEqual(list(pool.map(send, range(24))), [b'{}']*24)
                for route in ('/health', '/v1/models'):
                    with urllib.request.urlopen(base+route, timeout=5) as response:
                        self.assertEqual(response.read().decode(), route)
                logs = [json.loads(line) for line in (Path(td)/'log').read_text().splitlines()]
                self.assertEqual(len(logs), 26)
                self.assertEqual(sum(row['hinted'] for row in logs), 12)
                self.assertEqual(sum(row['reason']=='no_hint' for row in logs), 14)
                self.assertNotIn('Bearer', (Path(td)/'log').read_text())
                self.assertNotIn('messages', (Path(td)/'log').read_text())
                self.assertTrue(all(auth == 'Bearer TEST' for path,auth,body in captured if body))
                self.assertTrue(all(len(row['request_sha256']) == 64 for row in logs))
            finally:
                proxy.shutdown(); upstream.shutdown(); proxy.server_close(); upstream.server_close()
            # Upstream HTTPS giả: dùng transport giả, không hạ kiểm chứng chỉ, giữ Authorization.
            class Response:
                status=200
                headers={}
                def read(self): return b'{}'
                def __enter__(self): return self
                def __exit__(self,*args): pass
            seen = []
            def transport(request, **options):
                seen.append((request, options))
                return Response()
            tlsproxy = make_server(('127.0.0.1',0), 'https://upstream.invalid', HintIndex([],[]), Path(td)/'tlslog')
            threading.Thread(target=tlsproxy.serve_forever,daemon=True).start()
            # HTTP client giữ urlopen gốc; chỉ patch đường đi upstream trong handler.
            real_open = urllib.request.urlopen
            try:
                with patch('scripts.sft_hint_proxy.urllib.request.urlopen', side_effect=transport):
                    with real_open(urllib.request.Request(f'http://127.0.0.1:{tlsproxy.server_port}/health',
                                                        headers={'Authorization':'Bearer TEST'}),timeout=5) as r:
                        self.assertEqual(r.read(),b'{}')
                self.assertEqual(seen[0][0].full_url,'https://upstream.invalid/health')
                self.assertEqual(seen[0][0].get_header('Authorization'),'Bearer TEST')
                self.assertNotIn('context',seen[0][1])  # urllib dùng kiểm chứng chỉ mặc định.
            finally:
                tlsproxy.shutdown(); tlsproxy.server_close()
        with self.assertRaises(ValueError):
            make_server(('0.0.0.0',0),'http://127.0.0.1',HintIndex([],[]),Path('unused'))

    def test_scoped_staff_endpoints_and_single_case_fallback(self):
        cases=[{**self.case,'id':cid,'actor':'staff_case_assist',
                'turns':[{'mode':'draft','user':chr(81)}]} for cid in ('c1','c2')]
        hints=[fake_hint(template='tpl',turn=None),fake_hint(case_id='c2',turn=1)]
        payload=json.loads(json.dumps(self.payload))
        payload['messages'][-1]['content']=prompt_for_turn(cases[0],cases[0]['turns'][0])
        seen=[]
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                seen.append((self.path,None));self.send_response(200);self.end_headers();self.wfile.write(self.path.encode())
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append((self.path,body));self.send_response(200);self.end_headers();self.wfile.write(b'{}')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'one.txt').write_text('c2\n',encoding='utf-8')
            (root/'both.txt').write_text('c1\nc2\n',encoding='utf-8')
            scopes=load_scopes(root);index=HintIndex(cases,hints,scopes=scopes)
            self.assertFalse(index.inject(payload)[1]['hinted'])
            self.assertFalse(index.inject(payload,scope='both')[1]['hinted'])
            self.assertEqual(index.inject(payload,scope='one')[1]['case_id'],'c2')
            payload['messages'][-1]['content']=chr(90)  # fallback một ca, một lượt.
            self.assertEqual(index.inject(payload,scope='one')[1]['hint_sha256'],hints[1]['sha256'])
            upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
            proxy=make_server(('127.0.0.1',0),f'http://127.0.0.1:{upstream.server_port}',index,root/'log')
            for server in (upstream,proxy):threading.Thread(target=server.serve_forever,daemon=True).start()
            base=f'http://127.0.0.1:{proxy.server_port}'
            try:
                request=urllib.request.Request(base+'/s/one/v1/chat/completions',data=json.dumps(payload).encode(),
                                               headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=5) as r:self.assertEqual(r.read(),b'{}')
                self.assertEqual(seen[-1][0],'/v1/chat/completions')
                self.assertIn(hints[1]['hint'],seen[-1][1]['messages'][0]['content'])
                for route in ('/health','/v1/models'):
                    with urllib.request.urlopen(base+'/s/one'+route,timeout=5) as r:self.assertEqual(r.read().decode(),route)
                    self.assertEqual(seen[-1][0],route)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(base+'/s/unknown/health',timeout=5)
                self.assertEqual(error.exception.code,404)
                log=json.loads((root/'log').read_text().splitlines()[0])
                self.assertEqual((log['case_id'],log['scope'],log['hinted']),('c2','one',True))
            finally:
                proxy.shutdown();upstream.shutdown();proxy.server_close();upstream.server_close()


class HintsTests(unittest.TestCase):
    def test_import_checks_and_hash(self):
        with tempfile.TemporaryDirectory() as td:
            path, out = Path(td)/'sheet.csv', Path(td)/'hints.jsonl'
            def sheet(text, **extra):
                with path.open('w',encoding='utf-8-sig',newline='') as fh:
                    row = dict.fromkeys(FIELDS+CASE_FIELDS,'')
                    row.update(template='tpl', turn=1, goi_y=text, **extra)
                    writer=csv.DictWriter(fh,fieldnames=list(row)); writer.writeheader();writer.writerow(row)
            for text in ('', chr(97)*801, 'SIM-O-99999', 'P-999', 'SIM-C-9999', '123.000 đồng', START, END):
                sheet(text)
                with self.assertRaises(ValueError): import_hints(path,out,eval_utterances=set())
                self.assertFalse(out.exists())
            text = chr(97)*16
            sheet(text)
            with self.assertRaises(ValueError): import_hints(path,out,eval_utterances={text})
            rows=import_hints(path,out,check_only=True,eval_utterances=set())
            self.assertFalse(out.exists()); self.assertEqual(rows[0]['sha256'],digest(text))
            import_hints(path,out,eval_utterances=set());self.assertTrue(out.exists())
            sheet('SIM-O-99999',case_id='case',order_codes='SIM-O-99999')
            self.assertEqual(import_hints(path,out,check_only=True,eval_utterances=set())[0]['case_id'],'case')
            sheet('SIM-O-99998',case_id='case',order_codes='SIM-O-99999')
            with self.assertRaises(ValueError): import_hints(path,out,check_only=True,eval_utterances=set())
            sheet(chr(97)*1200,case_id='case')
            self.assertEqual(len(import_hints(path,out,check_only=True,eval_utterances=set())[0]['hint']),1200)
            sheet(chr(97)*1201,case_id='case')
            with self.assertRaises(ValueError): import_hints(path,out,check_only=True,eval_utterances=set())

    def test_export_blank_bom_counts_and_per_case(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            cases=[{'id':cid,'meta':{'template':'tpl'},'turns':[{'mode':'draft','user':chr(85),'expect':
                    {'tools_called':['get_case_order'],'answer_not':['x'],'human_support':False}}],
                    'case_setup':{'order_id':'SIM-O-99999'}} for cid in ('c1','c2','c3')]
            (root/'cases').write_text('\n'.join(json.dumps(c) for c in cases),encoding='utf-8')
            cand=lambda cid:dict(case_id=cid,model='qwen',run=1,failures_v3=['turn 1: x'])
            scores={'cases':{cid:{'template':'tpl','candidates':[cand(cid)],'rejected':[]} for cid in ('c1','c2')}}
            scores['cases']['c3']={'template':'tpl','candidates':[],'rejected':[dict(reject_reasons=['stale_input'])]}
            (root/'scores').write_text(json.dumps(scores),encoding='utf-8')
            (root/'adj').write_text(json.dumps({'candidates':{'k':dict(case_id='c2',model='qwen',run=1,tier='A')}}),encoding='utf-8')
            rows=export_hints(root/'scores',[root/'adj'],root/'cases',root/'sheet')
            self.assertEqual(len(rows),1); self.assertEqual(rows[0]['so_ca'],1);self.assertEqual(rows[0]['goi_y'],'')
            self.assertEqual(json.loads(rows[0]['loi_thuong_gap']),{'turn 1: x':1})
            self.assertTrue((root/'sheet').read_bytes().startswith(b'\xef\xbb\xbf'))
            with self.assertRaises(FileExistsError): export_hints(root/'scores',[root/'adj'],root/'cases',root/'sheet')
            rows=export_hints(root/'scores',[root/'adj'],root/'cases',root/'per',per_case_templates=['tpl'])
            self.assertEqual((rows[0]['case_id'],rows[0]['mode'],rows[0]['order_codes']),('c1','draft','SIM-O-99999'))


if __name__ == '__main__':
    unittest.main()
