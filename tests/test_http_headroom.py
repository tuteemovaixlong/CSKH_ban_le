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
        """In-process WSGI non-interference check:
        Verifies that holding all 6 chat admission permits does not block /healthz handling
        in the WSGI app callable.

        Note: This direct in-process WSGI invocation test is a thread-cooperation / permit
        non-interference check and does NOT substitute for real multi-threaded Waitress
        socket load testing under concurrency (see test_waitress_real_http_chat_saturation_headroom).
        Sample size (25) is evaluated as worst-of-25 (<= 50.0ms), not statistical P99.
        """
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

            worst_of_25 = max(latencies)
            self.assertLessEqual(
                worst_of_25, 50.0,
                f"In-process /healthz worst-of-25 latency ({worst_of_25:.2f}ms) exceeded 50.0ms SLO"
            )
        finally:
            for _ in range(6):
                self.web.chat_admission.release()

    def test_waitress_real_http_chat_saturation_headroom(self):
        """B-03 / AC-09: Controlled Waitress 8 workers load test:
        - InferenceGate explicitly configured with concurrency=1, max_queue=5, queue_timeout=30.0.
        - Pre-gate / outside-gate DB and tool latency simulated on chat requests.
        - Chat 0 actually invokes a tool (get_order for O-101) and asserts BoundTools.__call__ execution.
        - Barrier asserts exactly 1 active inference + 5 queued chat requests (6 occupied Waitress workers).
        - Continuous saturation (1 in-flight + 5 queued) is held and verified through both measurement rounds.
        - No silent timeout: barrier fails loudly if load is lost prematurely.
        - Chat worker responses and exceptions tracked and asserted (no swallowed exceptions, all 6 HTTP 200).
        - Under saturation, 25 GET /healthz and 25 GET /api/session requests measured over real HTTP socket.
        - Latencies evaluated as worst-of-25 (<= 50.0ms), noting 25 samples cannot constitute statistical P99.
        """
        try:
            from waitress.server import create_server
        except ImportError:
            self.skipTest("Waitress is required in Docker/CI; optional in local test environment.")

        # AC-09: Explicitly configure InferenceGate with K=1 concurrency and Q=5 queue
        self.sessions.inference_gate = InferenceGate(concurrency=1, max_queue=5, queue_timeout=30.0)

        # Hook pre-gate DB lookups and tool execution to simulate delay outside the gate
        orig_conversation = BusinessStore.conversation
        orig_replay = BusinessStore.replay
        orig_bound_call = BoundTools.__call__

        bound_call_count = [0]
        tool_called_event = threading.Event()

        def slow_conversation(store_self, customer, cid):
            time.sleep(0.005)  # 5ms simulated pre-gate DB latency
            return orig_conversation(store_self, customer, cid)

        def slow_replay(store_self, customer, cid, req_id, digest):
            time.sleep(0.005)  # 5ms simulated pre-gate DB latency
            return orig_replay(store_self, customer, cid, req_id, digest)

        def slow_bound_call(tools_self, name, arguments):
            bound_call_count[0] += 1
            tool_called_event.set()
            time.sleep(0.005)  # 5ms simulated tool latency outside gate
            return orig_bound_call(tools_self, name, arguments)

        BusinessStore.conversation = slow_conversation
        BusinessStore.replay = slow_replay
        BoundTools.__call__ = slow_bound_call

        chat_entered = threading.Event()
        worker_0_holding = threading.Event()
        chat_release = threading.Event()
        barrier_saturated = threading.Event()
        barrier_timed_out = threading.Event()

        class BarrierSlowModel:
            def __init__(self, gate):
                self.gate = gate

            def for_turn(self):
                return self

            def inspect(self):
                return {"name": "barrier-slow-model", "provider": "custom", "digest": None}

            def chat(self, messages, allow_tools, timeout):
                # Worker 0 Turn 1: request asks for order inquiry with allow_tools=True
                if allow_tools and not tool_called_event.is_set():
                    return {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_order_001",
                                    "type": "function",
                                    "function": {
                                        "name": "get_order",
                                        "arguments": {"order_id": "O-101"},
                                    },
                                }
                            ],
                        },
                        "eval_count": 1,
                        "prompt_eval_count": 5,
                    }

                # Worker 0 Turn 2 (holding the barrier) or any other chat worker
                if not chat_release.is_set():
                    worker_0_holding.set()
                    t0 = time.monotonic()
                    # Wait until all other 5 chat requests are admitted and queued in InferenceGate
                    while (self.gate.queue_size < 5 or self.gate.in_flight < 1) and (time.monotonic() - t0) < 15.0:
                        time.sleep(0.01)
                    if self.gate.queue_size == 5 and self.gate.in_flight == 1:
                        barrier_saturated.set()
                    chat_entered.set()

                    # Strictly wait for test harness to signal release; do NOT silently proceed on timeout
                    if not chat_release.wait(timeout=30.0):
                        barrier_timed_out.set()
                        raise RuntimeError(
                            f"Barrier timed out waiting for chat_release after 30s! "
                            f"(in_flight={self.gate.in_flight}, queue_size={self.gate.queue_size})"
                        )

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

            # Chat worker function
            def chat_worker(worker_cookie, conv_id, idx, text):
                req = urllib.request.Request(
                    f"{base_url}/api/chat",
                    data=json.dumps({
                        "text": text,
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
                    with http.open(req, timeout=35) as r:
                        body_bytes = r.read()
                        chat_results[idx] = (r.status, body_bytes.decode("utf-8"))
                except Exception as exc:
                    chat_errors[idx] = exc

            # Spawn Worker 0 first with a tool-invoking query: "Tra cứu đơn hàng O-101"
            c0, cid0 = sessions_info[0]
            t0 = threading.Thread(
                target=chat_worker,
                args=(c0, cid0, 0, "Tra cứu đơn hàng O-101"),
                daemon=True
            )
            t0.start()
            chat_threads.append(t0)

            # Assert BoundTools.__call__ actually ran during Worker 0 execution
            self.assertTrue(
                tool_called_event.wait(timeout=10.0),
                "BoundTools.__call__ was not invoked within 10s for tool-calling chat worker"
            )
            self.assertGreaterEqual(
                bound_call_count[0], 1,
                "BoundTools.__call__ hook must have been executed at least once"
            )

            # Wait until Worker 0 has entered the gate on Turn 2 and is ready to hold the barrier
            self.assertTrue(
                worker_0_holding.wait(timeout=10.0),
                "Timed out waiting for Worker 0 to reach Turn 2 in InferenceGate"
            )

            # Now spawn Workers 1 through 5 (to queue up in InferenceGate and saturate all 6 chat slots)
            for i in range(1, 6):
                c, cid = sessions_info[i]
                t = threading.Thread(
                    target=chat_worker,
                    args=(c, cid, i, "Hello"),
                    daemon=True
                )
                t.start()
                chat_threads.append(t)

            # Wait until all 6 workers are admitted and barrier proves full saturation
            self.assertTrue(
                chat_entered.wait(timeout=10.0),
                "Barrier timed out waiting for chats to enter model and queue"
            )
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
            self.assertFalse(barrier_timed_out.is_set(), "Barrier timed out before probes began")

            # Round 1: Measure 25 GET /healthz requests over real HTTP socket
            health_latencies = []
            health_req = urllib.request.Request(
                f"{base_url}/healthz",
                headers={"Host": "retailops.example.com"}
            )
            for _ in range(25):
                t_probe = time.monotonic()
                with http.open(health_req, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                lat = (time.monotonic() - t_probe) * 1000.0
                health_latencies.append(lat)

            # Assert saturation was held throughout Round 1
            self.assertFalse(barrier_timed_out.is_set(), "Barrier timed out during GET /healthz probe round")
            self.assertEqual(
                self.sessions.inference_gate.in_flight, 1,
                f"Saturation lost after Round 1: in_flight={self.sessions.inference_gate.in_flight} (expected 1)"
            )
            self.assertEqual(
                self.sessions.inference_gate.queue_size, 5,
                f"Saturation lost after Round 1: queue_size={self.sessions.inference_gate.queue_size} (expected 5)"
            )

            # Round 2: Measure 25 GET /api/session requests with a valid session over real HTTP socket
            session_latencies = []
            session_req = urllib.request.Request(
                f"{base_url}/api/session",
                headers={
                    "Host": "retailops.example.com",
                    "Cookie": independent_session_cookie,
                }
            )
            for _ in range(25):
                t_probe = time.monotonic()
                with http.open(session_req, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    s_body = json.loads(resp.read().decode("utf-8"))
                    self.assertIn("customer_id", s_body)
                lat = (time.monotonic() - t_probe) * 1000.0
                session_latencies.append(lat)

            # Assert saturation was held throughout Round 2
            self.assertFalse(barrier_timed_out.is_set(), "Barrier timed out during GET /api/session probe round")
            self.assertEqual(
                self.sessions.inference_gate.in_flight, 1,
                f"Saturation lost after Round 2: in_flight={self.sessions.inference_gate.in_flight} (expected 1)"
            )
            self.assertEqual(
                self.sessions.inference_gate.queue_size, 5,
                f"Saturation lost after Round 2: queue_size={self.sessions.inference_gate.queue_size} (expected 5)"
            )

            # Protocol & Sample Size: 25 samples are evaluated as worst-of-25 (max-of-25),
            # strictly distinguished from statistical P99 (which requires >= 100 observations per opsconsole/metrics.py).
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

            # Verify BoundTools.__call__ execution count
            self.assertGreaterEqual(
                bound_call_count[0], 1,
                "BoundTools.__call__ must have been executed at least once during the test"
            )
        finally:
            BusinessStore.conversation = orig_conversation
            BusinessStore.replay = orig_replay
            BoundTools.__call__ = orig_bound_call

            # Explicit release of chat barrier only after all probe rounds and assertions complete
            chat_release.set()
            for t in chat_threads:
                t.join(timeout=10.0)
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
