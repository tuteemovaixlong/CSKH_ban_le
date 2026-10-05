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

from retailops.business.store import BusinessStore
from retailops.core import ApiError
from retailops.http.public import PublicWeb
from retailops.identity.demo import GuestSessions
from retailops.inference_gate import InferenceGate
from retailops_tools import BoundTools

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
        """B-03 / AC-09: Controlled Waitress 8 workers load test:
        - InferenceGate explicitly configured with concurrency=1, max_queue=5.
        - Pre-gate / outside-gate DB and tool latency simulated on chat requests.
        - Barrier asserts exactly 1 active inference + 5 queued chat requests (6 occupied Waitress workers).
        - Chat worker responses and exceptions tracked and asserted (no swallowed exceptions, all 6 HTTP 200).
        - Under saturation, 25 GET /healthz and 25 GET /api/session requests measured over real HTTP socket.
        - Latencies evaluated as worst-of-25 (<= 50.0ms).
        """
        try:
            from waitress.server import create_server
        except ImportError:
            self.skipTest("Waitress is required in Docker/CI; optional in local test environment.")

        # AC-09: Explicitly configure InferenceGate with K=1 concurrency and Q=5 queue
        self.sessions.inference_gate = InferenceGate(concurrency=1, max_queue=5, queue_timeout=15.0)

        # Hook pre-gate DB lookups and tool execution to simulate delay outside the gate
        orig_conversation = BusinessStore.conversation
        orig_replay = BusinessStore.replay
        orig_bound_call = BoundTools.__call__

        def slow_conversation(store_self, customer, cid):
            time.sleep(0.005)  # 5ms simulated pre-gate DB latency
            return orig_conversation(store_self, customer, cid)

        def slow_replay(store_self, customer, cid, req_id, digest):
            time.sleep(0.005)  # 5ms simulated pre-gate DB latency
            return orig_replay(store_self, customer, cid, req_id, digest)

        def slow_bound_call(tools_self, name, arguments):
            time.sleep(0.005)  # 5ms simulated tool latency outside gate
            return orig_bound_call(tools_self, name, arguments)

        BusinessStore.conversation = slow_conversation
        BusinessStore.replay = slow_replay
        BoundTools.__call__ = slow_bound_call

        chat_entered = threading.Event()
        chat_release = threading.Event()
        barrier_saturated = threading.Event()

        class BarrierSlowModel:
            def __init__(self, gate):
                self.gate = gate

            def for_turn(self):
                return self

            def inspect(self):
                return {"name": "barrier-slow-model", "provider": "custom", "digest": None}

            def chat(self, messages, allow_tools, timeout):
                if not chat_release.is_set():
                    t0 = time.monotonic()
                    # Wait until all other 5 chat requests are admitted and queued in InferenceGate
                    while (self.gate.queue_size < 5 or self.gate.in_flight < 1) and (time.monotonic() - t0) < 6.0:
                        time.sleep(0.01)
                    if self.gate.queue_size == 5 and self.gate.in_flight == 1:
                        barrier_saturated.set()
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
        chat_results = [None] * 6
        chat_errors = [None] * 6

        try:
            http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            port = server.effective_port
            base_url = f"http://127.0.0.1:{port}"

            # Login 6 distinct guest sessions and create a conversation for each
            sessions_info = []
            for i in range(6):
                login_req = urllib.request.Request(
                    f"{base_url}/api/login",
                    data=json.dumps({"token": INVITE}).encode(),
                    headers={"Host": "retailops.example.com", "Origin": ORIGIN, "Content-Type": "application/json"}
                )
                with http.open(login_req, timeout=5) as resp:
                    c = resp.headers["Set-Cookie"].split(";")[0]

                conv_req = urllib.request.Request(
                    f"{base_url}/api/conversations",
                    data=json.dumps({}).encode(),
                    headers={"Host": "retailops.example.com", "Origin": ORIGIN, "Content-Type": "application/json", "Cookie": c}
                )
                with http.open(conv_req, timeout=5) as resp:
                    cid = json.loads(resp.read().decode())["conversation_id"]
                sessions_info.append((c, cid))

            # Create an independent 7th valid session for measuring /api/session headroom
            login_req_7 = urllib.request.Request(
                f"{base_url}/api/login",
                data=json.dumps({"token": INVITE}).encode(),
                headers={"Host": "retailops.example.com", "Origin": ORIGIN, "Content-Type": "application/json"}
            )
            with http.open(login_req_7, timeout=5) as resp:
                independent_session_cookie = resp.headers["Set-Cookie"].split(";")[0]

            # Warm up / initialize the session app so seed does not run during latency measurement
            warmup_req = urllib.request.Request(
                f"{base_url}/api/session",
                headers={"Host": "retailops.example.com", "Cookie": independent_session_cookie}
            )
            with http.open(warmup_req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)

            # Spawn 6 chat requests across the 6 distinct sessions
            def chat_worker(worker_cookie, conv_id, idx):
                req = urllib.request.Request(
                    f"{base_url}/api/chat",
                    data=json.dumps({
                        "text": "Hello",
                        "conversation_id": conv_id,
                        "request_id": f"req_headroom_w_{idx:04d}_abcdef123456",
                    }).encode(),
                    headers={
                        "Host": "retailops.example.com",
                        "Origin": ORIGIN,
                        "Content-Type": "application/json",
                        "Cookie": worker_cookie,
                    }
                )
                try:
                    with http.open(req, timeout=15) as r:
                        body_bytes = r.read()
                        chat_results[idx] = (r.status, body_bytes.decode("utf-8"))
                except Exception as exc:
                    chat_errors[idx] = exc

            for i in range(6):
                c, cid = sessions_info[i]
                t = threading.Thread(target=chat_worker, args=(c, cid, i), daemon=True)
                t.start()
                chat_threads.append(t)

            # Wait until request 1 has entered the model and signaled the barrier
            self.assertTrue(chat_entered.wait(timeout=10.0), "Barrier timed out waiting for chat to enter model")

            # AC-09: Fail if barrier does not prove 1 inference actively running and 5 queued
            self.assertTrue(
                barrier_saturated.is_set(),
                f"Saturation barrier failed to reach required load (expected 1 active inference + 5 queued; "
                f"got in_flight={self.sessions.inference_gate.in_flight}, queue_size={self.sessions.inference_gate.queue_size})"
            )
            self.assertEqual(
                self.sessions.inference_gate.in_flight, 1,
                f"Expected exactly 1 in-flight inference, got {self.sessions.inference_gate.in_flight}"
            )
            self.assertEqual(
                self.sessions.inference_gate.queue_size, 5,
                f"Expected exactly 5 queued chat requests, got {self.sessions.inference_gate.queue_size}"
            )

            # Now 6 out of 8 Waitress worker threads are actively holding in-flight chat requests.
            # 1) Measure 25 GET /healthz requests over real HTTP sockets:
            health_latencies = []
            health_req = urllib.request.Request(
                f"{base_url}/healthz",
                headers={"Host": "retailops.example.com"}
            )
            for _ in range(25):
                t0 = time.monotonic()
                with http.open(health_req, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                lat = (time.monotonic() - t0) * 1000.0
                health_latencies.append(lat)

            # 2) Measure 25 GET /api/session requests with a valid session over real HTTP sockets:
            session_latencies = []
            session_req = urllib.request.Request(
                f"{base_url}/api/session",
                headers={
                    "Host": "retailops.example.com",
                    "Cookie": independent_session_cookie,
                }
            )
            for _ in range(25):
                t0 = time.monotonic()
                with http.open(session_req, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    s_body = json.loads(resp.read().decode("utf-8"))
                    self.assertIn("customer_id", s_body)
                lat = (time.monotonic() - t0) * 1000.0
                session_latencies.append(lat)

            # Protocol & Sample Size: 25 samples are insufficient for statistical P99; report worst-of-25
            worst_health = max(health_latencies)
            worst_session = max(session_latencies)
            self.assertLessEqual(
                worst_health, 50.0,
                f"GET /healthz worst-of-25 latency ({worst_health:.2f}ms) exceeded 50.0ms SLO"
            )
            self.assertLessEqual(
                worst_session, 50.0,
                f"GET /api/session worst-of-25 latency ({worst_session:.2f}ms) exceeded 50.0ms SLO"
            )
        finally:
            BusinessStore.conversation = orig_conversation
            BusinessStore.replay = orig_replay
            BoundTools.__call__ = orig_bound_call

            chat_release.set()
            for t in chat_threads:
                t.join(timeout=5.0)
            server.close()
            server.task_dispatcher.shutdown()
            thread.join(timeout=3.0)

        # Assert all 6 chat requests completed without exception and returned HTTP 200
        for idx in range(6):
            self.assertIsNone(
                chat_errors[idx],
                f"Chat worker {idx} raised an unhandled exception: {chat_errors[idx]}"
            )
            self.assertIsNotNone(
                chat_results[idx],
                f"Chat worker {idx} produced no response"
            )
            status, body = chat_results[idx]
            self.assertEqual(status, 200, f"Chat worker {idx} returned HTTP {status} instead of 200: {body}")


if __name__ == "__main__":
    unittest.main()
