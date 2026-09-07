"""HTML UI assets must load through the real adapters, before login."""
import io
import threading
import unittest
from html.parser import HTMLParser
from http.client import HTTPConnection

from retailops.core import ROOT
from retailops.http.assets import ASSETS
from retailops.http.public import PublicWeb
from retailops.http.private import Server


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'script' and values.get('src'):
            self.urls.append('/' + values['src'].lstrip('/'))
        if tag == 'link' and values.get('rel') == 'stylesheet':
            self.urls.append('/' + values['href'].lstrip('/'))


class UiAssetsTests(unittest.TestCase):
    def public_request(self, path, host='retailops.example.test'):
        captured = {}
        def start(status, headers):
            captured.update(status=int(status.split()[0]), headers=dict(headers))
        app = PublicWeb('https://retailops.example.test', object())
        body = b''.join(app({
            'REQUEST_METHOD': 'GET', 'PATH_INFO': path, 'HTTP_HOST': host,
            'QUERY_STRING': '', 'REMOTE_ADDR': '127.0.0.1',
            'wsgi.input': io.BytesIO(b''),
        }, start))
        return captured['status'], captured['headers'], body

    def test_html_references_all_served_assets(self):
        parser = References()
        parser.feed((ROOT / 'web/index.html').read_text())
        self.assertEqual(set(parser.urls), set(ASSETS) - {'/'})
        for path in parser.urls:
            with self.subTest(path=path):
                code, headers, body = self.public_request(path)
                name, mime = ASSETS[path]
                self.assertEqual(code, 200)
                self.assertEqual(headers['Content-Type'], mime)
                self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
                self.assertEqual(body, (ROOT / 'web' / name).read_bytes())
                self.assertEqual(int(headers['Content-Length']), len(body))

    def test_public_assets_keep_host_and_path_guards(self):
        self.assertEqual(self.public_request('/chat-focus.js', 'evil.example')[0], 403)
        for path in ('/missing.js', '/web/chat-focus.js', '/../public.env'):
            with self.subTest(path=path):
                self.assertEqual(self.public_request(path)[0], 404)

    def test_private_assets_and_unknown_paths(self):
        server = Server(('127.0.0.1', 0), None)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            for path, (name, mime) in ASSETS.items():
                with self.subTest(path=path):
                    client = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                    try:
                        client.request('GET', path)
                        response = client.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.getheader('Content-Type'), mime)
                        self.assertEqual(response.read(), (ROOT / 'web' / name).read_bytes())
                    finally:
                        client.close()
            for path in ('/missing.js', '/../public.env'):
                client = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                try:
                    client.request('GET', path)
                    response = client.getresponse()
                    self.assertEqual(response.status, 404)
                    response.read()
                finally:
                    client.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
