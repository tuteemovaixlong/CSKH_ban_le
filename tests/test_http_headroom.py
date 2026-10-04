"""Tests for HTTP Chat Admission Limiter and Headroom Protection (F07 / AC-09)."""
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

from retailops.core import ApiError
from retailops.http.public import PublicWeb
from retailops.identity.demo import GuestSessions

INVITE = "fixture_invite_" + "a" * 40
ORIGIN = "https://retailops.example.com"


class SlowModelFixture:
    def __init__(self, enter_event=None, release_event=None):
        self.enter_event = enter_event
        self.release_event = release_event

    def inspect(self):
        return {"name": "slow-fixture", "provider": "custom", "digest": None}

    def chat(self, messages, allow_tools, timeout):
        if self.enter_event:
            self.enter_event.set()
        if self.release_event:
            self.release_event.wait(timeout=5.0)
        return {
            "message": {"role": "assistant", "content": "Done"},
            "eval_count": 1,
            "prompt_eval_count": 5,
        }


class HttpHeadroomTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "public-guests"
        self.sessions = GuestSessions(self.directory, INVITE, api_daily_limit=100)
        self.web = PublicWeb(ORIGIN, self.sessions)

    def _call_wsgi(self, app, environ):
        response_headers = []
        status_code = [None]

        def start_response(status, headers):
            status_code[0] = int(status.split()[0])
            response_headers.extend(headers)

        body_iterable = app(environ, start_response)
        body = b"".join(body_iterable)
        headers_dict = dict(response_headers)
        json_body = json.loads(body.decode("utf-8")) if "application/json" in headers_dict.get("Content-Type", "") else body
        return status_code[0], json_body, response_headers

    def test_chat_admission_overflow_429(self):
        """Admission limits in-flight chat to 6. The 7th request gets 429 server_busy with Retry-After: 5."""
        # Occupy all 6 admission slots
        holders = []
        for _ in range(6):
            self.assertTrue(self.web.chat_admission.acquire(blocking=False))
            holders.append(True)

        env = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/api/chat",
            "HTTP_HOST": "retailops.example.com",
            "HTTP_ORIGIN": ORIGIN,
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": "2",
            "wsgi.input": None,
        }
        status, body, headers = self._call_wsgi(self.web, env)
        self.assertEqual(status, 429)
        self.assertEqual(body.get("error"), "server_busy")
        self.assertIn(("Retry-After", "5"), headers)

        # Release one slot
        self.web.chat_admission.release()
        holders.pop()

        # Clean up remaining holders
        for _ in holders:
            self.web.chat_admission.release()

    def test_healthz_headroom_under_chat_saturation(self):
        """Under saturated 6 in-flight chat load, health check latency P99 <= 50ms."""
        # Hold all 6 chat admission permits
        for _ in range(6):
            self.assertTrue(self.web.chat_admission.acquire(blocking=False))

        try:
            health_env = {
                "REQUEST_METHOD": "GET",
                "PATH_INFO": "/healthz",
                "HTTP_HOST": "retailops.example.com",
            }
            latencies = []
            for _ in range(25):
                t0 = time.monotonic()
                status, body, _ = self._call_wsgi(self.web, health_env)
                lat = (time.monotonic() - t0) * 1000.0
                latencies.append(lat)
                self.assertEqual(status, 200)
                self.assertEqual(body.get("status"), "ok")

            latencies.sort()
            # P99
            p99_idx = int(0.99 * len(latencies))
            p99 = latencies[min(p99_idx, len(latencies) - 1)]
            self.assertLessEqual(p99, 50.0)
        finally:
            for _ in range(6):
                self.web.chat_admission.release()

    def test_waitress_real_http_chat_saturation_headroom(self):
        """B-03: Controlled Waitress 8 workers load test: 6 concurrent in-flight chat requests held by a barrier;
        measures P99 client latency on GET /healthz over real HTTP socket (P99 <= 50ms).
        """
        try:
            from waitress.server import create_server
        except ImportError:
            self.skipTest("Waitress is required in Docker/CI; optional in local test environment.")

        # Barrier coordination:
        # Request 1 enters the model and waits until all other 5 chat requests are admitted
        # and queued in InferenceGate (K=1, Q=5), ensuring exactly 6 Waitress worker threads
        # are actively holding in-flight chat requests simultaneously.
        chat_entered = threading.Event()
        chat_release = threading.Event()

        class BarrierSlowModel:
            def __init__(self, gate):
                self.gate = gate

            def inspect(self):
                return {"name": "barrier-slow-model", "provider": "custom", "digest": None}

            def chat(self, messages, allow_tools, timeout):
                if not chat_release.is_set():
                    t0 = time.monotonic()
                    while self.gate.queue_size < 5 and (time.monotonic() - t0) < 5.0:
                        time.sleep(0.01)
                    chat_entered.set()
                    chat_release.wait(timeout=10.0)
                return {
                    "message": {"role": "assistant", "content": "Done"},
                    "eval_count": 1,
                    "prompt_eval_count": 5,
                }

        self.sessions.infer = BarrierSlowModel(self.sessions.inference_gate)
        self.sessions.api_infer = self.sessions.infer

        server = create_server(self.web, host="127.0.0.1", port=0, threads=8)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        chat_threads = []
        try:
            http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            port = server.effective_port
            base_url = f"http://127.0.0.1:{port}"

            # Login 6 distinct guest sessions to avoid per-conversation lock serialization
            cookies = []
            for _ in range(6):
                login_req = urllib.request.Request(
                    f"{base_url}/api/login",
                    data=json.dumps({"token": INVITE}).encode(),
                    headers={"Host": "retailops.example.com", "Origin": ORIGIN, "Content-Type": "application/json"}
                )
                with http.open(login_req, timeout=5) as resp:
                    cookies.append(resp.headers["Set-Cookie"].split(";")[0])

            # Spawn 6 chat requests across the 6 distinct sessions
            def chat_worker(worker_cookie):
                req = urllib.request.Request(
                    f"{base_url}/api/chat",
                    data=json.dumps({"message": "Hello"}).encode(),
                    headers={
                        "Host": "retailops.example.com",
                        "Origin": ORIGIN,
                        "Content-Type": "application/json",
                        "Cookie": worker_cookie,
                    }
                )
                try:
                    with http.open(req, timeout=10) as r:
                        r.read()
                except Exception:
                    pass

            for i in range(6):
                t = threading.Thread(target=chat_worker, args=(cookies[i],), daemon=True)
                t.start()
                chat_threads.append(t)

            # Wait until all 6 chat requests are actively in-flight inside Waitress worker threads
            self.assertTrue(chat_entered.wait(timeout=10.0))

            # Now 6 out of 8 Waitress worker threads are actively occupied handling chat.
            # Measure 25 healthz requests from an independent client over real HTTP sockets:
            latencies = []
            health_req = urllib.request.Request(
                f"{base_url}/healthz",
                headers={"Host": "retailops.example.com"}
            )
            for _ in range(25):
                t0 = time.monotonic()
                with http.open(health_req, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                lat = (time.monotonic() - t0) * 1000.0
                latencies.append(lat)

            latencies.sort()
            p99_idx = int(0.99 * len(latencies))
            p99 = latencies[min(p99_idx, len(latencies) - 1)]
            self.assertLessEqual(p99, 50.0)
        finally:
            chat_release.set()
            for t in chat_threads:
                t.join(timeout=3.0)
            server.close()
            server.task_dispatcher.shutdown()
            thread.join(timeout=3.0)


if __name__ == "__main__":
    unittest.main()
