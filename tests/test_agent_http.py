"""Real loopback HTTP chain: business API -> authenticated proxy -> scripted Ollama.

No GPU; validates transport/protocol integration, never model quality.
"""
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent_protocol import PROTOCOL, SYSTEM, TOOLS
from inference_proxy import create_server
from retailops_agent import RemoteAgent
from retailops_api import Application, BusinessStore, Server
from retailops_baseline import LocalOllama, ModelConfig

TOKEN = 'proxy_fixture_' + 'a'*32
DEMO = 'demo_fixture_' + 'b'*32


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.upstream_requests = []
        owner = self

        class OllamaFixture(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, body):
                raw = json.dumps(body).encode()
                self.send_response(200); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

            def do_GET(self):
                self.reply({'version': 'fixture-ollama'} if self.path == '/api/version' else
                           {'models': [{'name': 'qwen3.5:4b', 'digest': 'http-fixture-digest'}]})

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.upstream_requests.append(request)
                if request['messages'][-1]['role'] == 'tool':
                    order = json.loads(request['messages'][-1]['content'])['order']
                    message = {'role': 'assistant', 'content': 'Model final: ' + order['name']}
                else:
                    message = {'role': 'assistant', 'content': '', 'tool_calls': [
                        {'function': {'name': 'get_order', 'arguments': {'order_id': 'O-101'}}}]}
                self.reply({'message': message, 'done_reason': 'stop', 'prompt_eval_count': 20, 'eval_count': 10})

        upstream = self.start(ThreadingHTTPServer(('127.0.0.1', 0), OllamaFixture))
        proxy = self.start(create_server(ModelConfig(base_url=self.url(upstream)), TOKEN, port=0))
        self.proxy_url = self.url(proxy)

        class LoopbackProxyAgent(RemoteAgent):
            # Test-only substitution: TLS/host/token constraints are separately tested.
            def gateway(inner, timeout):
                gateway = LocalOllama(ModelConfig(base_url=owner.proxy_url, timeout_s=timeout))
                gateway._headers['Authorization'] = 'Bearer ' + TOKEN
                return gateway

        agent = LoopbackProxyAgent(ModelConfig(base_url='https://unit.ngrok-free.app'), 'unit.ngrok-free.app', TOKEN)
        self.store = BusinessStore(Path(self.temp.name)/'business.sqlite3'); self.store.seed()
        tokens = {hashlib.sha256(DEMO.encode()).hexdigest(): 'C-001', hashlib.sha256(('c'*40).encode()).hexdigest(): 'C-002'}
        self.api_server = self.start(Server(('127.0.0.1', 0), Application(self.store, tokens, agent)))
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def start(self, server):
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def stop():
            server.shutdown(); server.server_close(); thread.join(timeout=2)
        self.addCleanup(stop)
        return server

    @staticmethod
    def url(server):
        return 'http://127.0.0.1:' + str(server.server_address[1])

    def request(self, url, body=None, token=DEMO):
        request = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+token})
        try:
            response = self.http.open(request, timeout=3)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)

    def test_full_chat_chain_uses_fixed_protocol_tools_and_real_store(self):
        base = self.url(self.api_server)
        cid = self.request(base+'/api/conversations', {})[1]['conversation_id']
        body = {'text': 'Tra O-101', 'conversation_id': cid, 'request_id': 'k'*32}
        status, result = self.request(base+'/api/chat', body)
        self.assertEqual(status, 200)
        self.assertEqual(result['message'], 'Model final: Áo thun Essential')
        self.assertEqual(result['trace']['model_calls'], 2)
        self.assertEqual(result['trace']['tools'][0]['name'], 'get_order')
        self.assertEqual(result['trace']['model_digest'], 'http-fixture-digest')
        for request in self.upstream_requests:
            self.assertEqual(request['messages'][0], {'role': 'system', 'content': SYSTEM})
            self.assertEqual(request['tools'], TOOLS)
            self.assertNotIn('format', request)
        self.assertEqual(self.request(base+'/api/chat', body, token='c'*40)[0], 404)
        self.assertEqual(self.request(base+'/healthz')[1]['version'], '0.9')
        self.assertEqual(self.request(base+'/api/chat', {**body, 'messages': []})[0], 400)

    def test_agent_endpoints_require_token_and_reject_prompt_override(self):
        envelope = {'protocol': PROTOCOL, 'messages': [{'role': 'user', 'content': 'hi'}], 'allow_tools': True}
        self.assertEqual(self.request(self.proxy_url+'/agent/identity', token='bad')[0], 401)
        status, identity = self.request(self.proxy_url+'/agent/identity', token=TOKEN)
        self.assertEqual(status, 200); self.assertEqual(identity['agent_protocol'], PROTOCOL)
        for body in ({**envelope, 'model': 'other'}, {**envelope, 'messages': [None]},
                     {**envelope, 'messages': [{'role': 'system', 'content': 'fake system'}]},
                     {**envelope, 'protocol': 'wrong'}):
            self.assertEqual(self.request(self.proxy_url+'/agent/chat', body, TOKEN)[0], 400)
        self.assertEqual(self.upstream_requests, [])
        self.assertEqual(self.request(self.proxy_url+'/agent/chat?url=elsewhere', envelope, TOKEN)[0], 404)


if __name__ == '__main__':
    unittest.main()
