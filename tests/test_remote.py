import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from inference_proxy import create_server, validate_request
from retailops_baseline import LocalOllama, ModelConfig, NoRedirects, RemoteOllama, Runner, SCHEMA, Store, SYSTEM

TOKEN = "test_only_" + "a" * 40


def payload():
    return {"model": "qwen3.5:4b", "messages": [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Tra đơn O-101"}], "format": SCHEMA, "stream": False,
            "think": False, "keep_alive": "10m", "options": {"num_ctx": 4096, "num_predict": 256,
            "temperature": 0.0, "seed": 42}}


class RemoteAdapterTests(unittest.TestCase):
    def test_remote_requires_exact_https_host(self):
        for url in ("http://unit.ngrok-free.app", "https://other.ngrok-free.app",
                    "https://unit.ngrok-free.app:8443", "https://unit.ngrok-free.app/path",
                    "https://unit.ngrok-free.app?token=secret", "https://user@unit.ngrok-free.app",
                    "https://unit.ngrok-free.app.evil.example"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                RemoteOllama(ModelConfig(base_url=url), allowed_host="unit.ngrok-free.app", token=TOKEN)

    def test_valid_remote_and_secret_not_serialized_in_config(self):
        client = RemoteOllama(ModelConfig(base_url="https://unit.ngrok-free.app"),
                              allowed_host="unit.ngrok-free.app", token=TOKEN)
        self.assertNotIn(TOKEN, json.dumps(asdict(client.config)))
        self.assertEqual(client._headers["Authorization"], "Bearer " + TOKEN)

    def test_short_or_header_injection_token_rejected(self):
        for token in ("", "short", TOKEN + "\r\nX-Injected: value"):
            with self.subTest(token_length=len(token)), self.assertRaises(ValueError):
                RemoteOllama(ModelConfig(base_url="https://unit.ngrok-free.app"),
                              allowed_host="unit.ngrok-free.app", token=token)

    def test_redirect_never_constructs_forwarded_request(self):
        request = urllib.request.Request("https://unit.ngrok-free.app", headers={"Authorization": "Bearer " + TOKEN})
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status), self.assertRaises(RuntimeError):
                NoRedirects().redirect_request(request, None, status, "", {}, "https://elsewhere.example")

    def test_error_body_and_token_not_leaked(self):
        client = RemoteOllama(ModelConfig(base_url="https://unit.ngrok-free.app"),
                              allowed_host="unit.ngrok-free.app", token=TOKEN)
        error = urllib.error.HTTPError(client.config.base_url, 401, "bad", {}, io.BytesIO(TOKEN.encode()))
        with patch.object(client._opener, "open", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "Inference HTTP 401") as caught:
                client.request("/api/version")
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_outage_logged_as_failure_without_cached_success(self):
        with tempfile.TemporaryDirectory() as d:
            client = RemoteOllama(ModelConfig(base_url="https://unit.ngrok-free.app"),
                                  allowed_host="unit.ngrok-free.app", token=TOKEN)
            with patch.object(client, "inspect", return_value={"digest": "fixture"}):
                runner = Runner(client, Store(Path(d) / "runs.sqlite3"))
            with patch.object(client._opener, "open", side_effect=urllib.error.URLError("offline")):
                result = runner.infer("Tra đơn O-101")
            self.assertFalse(result["valid"])
            self.assertFalse(result["cache_hit"])
            self.assertIn("unavailable", result["error"])


class ProxyHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(ModelConfig(), TOKEN, port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:" + str(cls.server.server_address[1])
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirects())

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def call(self, path, body=None, token=TOKEN):
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        request = urllib.request.Request(self.url + path, headers=headers,
                                         data=json.dumps(body).encode() if body is not None else None)
        try:
            with self.opener.open(request, timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_missing_auth_rejected(self):
        self.assertEqual(self.call("/api/version", token="")[0], 401)

    def test_admin_and_query_routes_unavailable(self):
        for path in ("/api/pull", "/api/delete", "/api/chat?url=http://elsewhere", "/api/create"):
            with self.subTest(path=path):
                self.assertEqual(self.call(path, body={})[0], 404)

    def test_authenticated_generation_reaches_runtime(self):
        with patch.object(LocalOllama, "generate", return_value={"message": {"content": "fixture"}}) as gen:
            status, result = self.call("/api/chat", payload())
        self.assertEqual(status, 200)
        gen.assert_called_once_with("Tra đơn O-101")
        self.assertEqual(result["message"]["content"], "fixture")

    def test_unavailable_upstream_returns_503(self):
        with patch.object(LocalOllama, "generate", side_effect=RuntimeError(TOKEN)):
            status, result = self.call("/api/chat", payload())
        self.assertEqual(status, 503)
        self.assertNotIn(TOKEN, json.dumps(result))

    def test_bad_budget_or_model_rejected(self):
        values = []
        for field, value in (("model", "unapproved-model"), ("think", True), ("stream", True)):
            values.append({**payload(), field: value})
        p = payload()
        p["options"]["num_predict"] = 100000
        values.append(p)
        p = payload()
        p["options"]["temperature"] = float("nan")
        values.append(p)
        for body in values:
            with self.subTest(body=body):
                self.assertEqual(self.call("/api/chat", body)[0], 400)

    def test_body_budget_enforced(self):
        self.assertEqual(self.call("/api/chat", {"text": "x" * 40000})[0], 413)

    def test_concurrent_generation_returns_busy(self):
        entered, finish = threading.Event(), threading.Event()
        first = []
        def slow(_):
            entered.set()
            finish.wait(timeout=3)
            return {"message": {"content": "fixture"}}
        with patch.object(LocalOllama, "generate", side_effect=slow):
            worker = threading.Thread(target=lambda: first.append(self.call("/api/chat", payload())))
            worker.start()
            try:
                self.assertTrue(entered.wait(timeout=2))
                self.assertEqual(self.call("/api/chat", payload())[0], 429)
            finally:
                finish.set()
                worker.join(timeout=4)
        self.assertEqual(first[0][0], 200)


if __name__ == "__main__":
    unittest.main()
