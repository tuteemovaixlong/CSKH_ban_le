"""Tests for HTTP Chat Admission Limiter and Headroom Protection (F07 / AC-09)."""
import json
import math
import os
import platform
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from datetime import datetime, timezone
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

    def _run_waitress_batch(self, batch_idx, http):
        batch_temp = tempfile.TemporaryDirectory()
        batch_dir = Path(batch_temp.name) / "public-guests"
        sessions = GuestSessions(batch_dir, INVITE, api_daily_limit=100)
        web = PublicWeb(ORIGIN, sessions)
        sessions.inference_gate = InferenceGate(concurrency=1, max_queue=5, queue_timeout=30.0)

        orig_conversation = BusinessStore.conversation
        orig_replay = BusinessStore.replay
        orig_bound_call = BoundTools.__call__

        bound_call_count = [0]
        tool_called_event = threading.Event()

        def slow_conversation(store_self, customer, cid):
            time.sleep(0.005)
            return orig_conversation(store_self, customer, cid)

        def slow_replay(store_self, customer, cid, req_id, digest):
            time.sleep(0.005)
            return orig_replay(store_self, customer, cid, req_id, digest)

        def slow_bound_call(tools_self, name, arguments):
            bound_call_count[0] += 1
            tool_called_event.set()
            time.sleep(0.005)
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

                if not chat_release.is_set():
                    worker_0_holding.set()
                    t0 = time.monotonic()
                    while (self.gate.queue_size < 5 or self.gate.in_flight < 1) and (time.monotonic() - t0) < 15.0:
                        time.sleep(0.01)
                    if self.gate.queue_size == 5 and self.gate.in_flight == 1:
                        barrier_saturated.set()
                    chat_entered.set()

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

        sessions.infer = BarrierSlowModel(sessions.inference_gate)
        sessions.api_infer = sessions.infer

        from waitress.server import create_server
        server = create_server(web, host="127.0.0.1", port=0, threads=8)
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()

        chat_threads = []
        chat_results = [None] * 6
        chat_errors = [None] * 6

        try:
            port = server.effective_port
            base_url = f"http://127.0.0.1:{port}"

            # Login 6 distinct guest sessions for chat workers
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

            # Login 2 probe sessions for measuring /api/session (total 8 logins < 15/min limit)
            probe_cookies = []
            for _ in range(2):
                login_req = urllib.request.Request(
                    f"{base_url}/api/login",
                    data=json.dumps({"token": INVITE}).encode(),
                    headers={"Host": "retailops.example.com", "Origin": ORIGIN, "Content-Type": "application/json"}
                )
                with http.open(login_req, timeout=5) as resp:
                    probe_cookies.append(resp.headers["Set-Cookie"].split(";")[0])

            def chat_worker(worker_cookie, conv_id, idx, text):
                req = urllib.request.Request(
                    f"{base_url}/api/chat",
                    data=json.dumps({
                        "text": text,
                        "conversation_id": conv_id,
                        "request_id": f"req_headroom_b{batch_idx:02d}_w{idx:02d}_abcdef123456",
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

            # Spawn Worker 0 first: tool call get_order on "Tra cứu đơn hàng O-101"
            c0, cid0 = sessions_info[0]
            t0 = threading.Thread(
                target=chat_worker,
                args=(c0, cid0, 0, "Tra cứu đơn hàng O-101"),
                daemon=True
            )
            t0.start()
            chat_threads.append(t0)

            self.assertTrue(tool_called_event.wait(timeout=10.0), f"Batch {batch_idx}: Tool hook timeout")
            self.assertGreaterEqual(bound_call_count[0], 1, f"Batch {batch_idx}: BoundTools.__call__ not called")
            self.assertTrue(worker_0_holding.wait(timeout=10.0), f"Batch {batch_idx}: Worker 0 holding timeout")

            # Spawn Workers 1..5 to saturate queue
            for i in range(1, 6):
                c, cid = sessions_info[i]
                t = threading.Thread(
                    target=chat_worker,
                    args=(c, cid, i, "Hello"),
                    daemon=True
                )
                t.start()
                chat_threads.append(t)

            self.assertTrue(chat_entered.wait(timeout=10.0), f"Batch {batch_idx}: chat_entered timeout")
            self.assertTrue(barrier_saturated.is_set(), f"Batch {batch_idx}: barrier not saturated")
            self.assertEqual(sessions.inference_gate.in_flight, 1, f"Batch {batch_idx}: in_flight != 1")
            self.assertEqual(sessions.inference_gate.queue_size, 5, f"Batch {batch_idx}: queue_size != 5")
            self.assertFalse(barrier_timed_out.is_set(), f"Batch {batch_idx}: barrier timed out")

            # Warm-up: 5 healthz + 5 session (3 on probe 0, 2 on probe 1)
            for _ in range(5):
                h_req = urllib.request.Request(f"{base_url}/healthz", headers={"Host": "retailops.example.com"})
                with http.open(h_req, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    resp.read()

            for p_cookie in [probe_cookies[0]] * 3 + [probe_cookies[1]] * 2:
                s_req = urllib.request.Request(
                    f"{base_url}/api/session",
                    headers={"Host": "retailops.example.com", "Cookie": p_cookie}
                )
                with http.open(s_req, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    s_body = json.loads(resp.read().decode("utf-8"))
                    self.assertIn("customer_id", s_body)

            self.assertEqual(sessions.inference_gate.in_flight, 1, f"Batch {batch_idx}: in_flight lost after warm-up")
            self.assertEqual(sessions.inference_gate.queue_size, 5, f"Batch {batch_idx}: queue lost after warm-up")
            self.assertFalse(barrier_timed_out.is_set())

            batch_t0 = time.monotonic()

            # 100 GET /healthz samples (measuring until response body is completely read)
            health_latencies = []
            health_req = urllib.request.Request(
                f"{base_url}/healthz",
                headers={"Host": "retailops.example.com"}
            )
            for _ in range(100):
                t_req = time.perf_counter()
                with http.open(health_req, timeout=5) as resp:
                    body_bytes = resp.read()
                    lat = (time.perf_counter() - t_req) * 1000.0
                    self.assertEqual(resp.status, 200)
                    body = json.loads(body_bytes.decode("utf-8"))
                    self.assertEqual(body.get("status"), "ok")
                health_latencies.append(lat)
                self.assertLessEqual(
                    time.monotonic() - batch_t0, 20.0,
                    f"Batch {batch_idx} exceeded 20s measurement deadline during healthz"
                )

            self.assertEqual(sessions.inference_gate.in_flight, 1, f"Batch {batch_idx}: in_flight lost after healthz")
            self.assertEqual(sessions.inference_gate.queue_size, 5, f"Batch {batch_idx}: queue lost after healthz")
            self.assertFalse(barrier_timed_out.is_set())

            # 100 GET /api/session samples: split evenly (50 on probe 0, 50 on probe 1)
            session_latencies = []
            session_plan = [probe_cookies[0]] * 50 + [probe_cookies[1]] * 50
            for p_cookie in session_plan:
                s_req = urllib.request.Request(
                    f"{base_url}/api/session",
                    headers={"Host": "retailops.example.com", "Cookie": p_cookie}
                )
                t_req = time.perf_counter()
                with http.open(s_req, timeout=5) as resp:
                    body_bytes = resp.read()
                    lat = (time.perf_counter() - t_req) * 1000.0
                    self.assertEqual(resp.status, 200)
                    body = json.loads(body_bytes.decode("utf-8"))
                    self.assertIn("customer_id", body)
                session_latencies.append(lat)
                self.assertLessEqual(
                    time.monotonic() - batch_t0, 20.0,
                    f"Batch {batch_idx} exceeded 20s measurement deadline during session"
                )

            self.assertEqual(sessions.inference_gate.in_flight, 1, f"Batch {batch_idx}: in_flight lost after session")
            self.assertEqual(sessions.inference_gate.queue_size, 5, f"Batch {batch_idx}: queue lost after session")
            self.assertFalse(barrier_timed_out.is_set())

            batch_duration = time.monotonic() - batch_t0

        finally:
            BusinessStore.conversation = orig_conversation
            BusinessStore.replay = orig_replay
            BoundTools.__call__ = orig_bound_call

            chat_release.set()
            for t in chat_threads:
                t.join(timeout=10.0)
            server.close()
            server.task_dispatcher.shutdown()
            server_thread.join(timeout=3.0)
            batch_temp.cleanup()

        for idx in range(6):
            self.assertIsNone(chat_errors[idx], f"Batch {batch_idx}: worker {idx} error {chat_errors[idx]}")
            self.assertIsNotNone(chat_results[idx], f"Batch {batch_idx}: worker {idx} produced no response")
            self.assertEqual(chat_results[idx][0], 200, f"Batch {batch_idx}: worker {idx} returned {chat_results[idx][0]}")

        batch_meta = {
            "batch_index": batch_idx,
            "duration_seconds": round(batch_duration, 3),
            "healthz_samples": len(health_latencies),
            "session_samples": len(session_latencies),
            "worker_statuses": [r[0] for r in chat_results],
            "bound_calls_count": bound_call_count[0],
            "saturation_confirmed": True,
        }
        return health_latencies, session_latencies, batch_meta

    def test_waitress_real_http_chat_saturation_headroom(self):
        """B-03 / AC-09: Controlled Waitress 8 workers headroom load test under AC09-P99-EVIDENCE protocol:
        - 1,000 observations per endpoint across 10 batches x 100 samples/endpoint.
        - Waitress 8 workers on real loopback socket (127.0.0.1:0).
        - InferenceGate explicitly configured with concurrency=1, max_queue=5, queue_timeout=30.0.
        - Worker 0 actually invokes tool get_order on 'Tra cứu đơn hàng O-101'; asserts BoundTools.__call__ execution.
        - Continuous saturation (1 in-flight + 5 queued) held and verified through both measurement rounds per batch.
        - Strict rate limit compliance: 8 logins/batch (6 chat + 2 probe) < 15/min limit.
        - Session probes split 50/50 across 2 probe cookies (+ 3/2 warm-up) <= 53 calls/cookie < 60/min limit.
        - Full response body read (r.read()) and verified before computing round-trip latency.
        - Empirical nearest-rank P99 calculated: element at index ceil(0.99 * N) - 1 (idx 989 for N=1000).
        - Asserts empirical nearest-rank P99 <= 50.0ms for both /healthz and /api/session.
        - Saves raw latency samples and metadata to evals/reports/headroom_p99_artifact.json.
        """
        try:
            import waitress
            from waitress.server import create_server
        except ImportError:
            self.skipTest("Waitress is required in Docker/CI; optional in local test environment.")

        http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        all_health_latencies = []
        all_session_latencies = []
        batches_meta = []
        suite_t0 = time.monotonic()

        for b in range(10):
            h_lats, s_lats, b_meta = self._run_waitress_batch(b, http)
            all_health_latencies.extend(h_lats)
            all_session_latencies.extend(s_lats)
            batches_meta.append(b_meta)

        total_duration = time.monotonic() - suite_t0

        self.assertEqual(len(all_health_latencies), 1000, f"Expected 1000 /healthz samples, got {len(all_health_latencies)}")
        self.assertEqual(len(all_session_latencies), 1000, f"Expected 1000 /api/session samples, got {len(all_session_latencies)}")

        def calc_percentiles(latencies):
            s = sorted(latencies)
            n = len(s)
            p50_idx = math.ceil(0.50 * n) - 1
            p95_idx = math.ceil(0.95 * n) - 1
            p99_idx = math.ceil(0.99 * n) - 1
            return {
                "n": n,
                "min_ms": round(s[0], 3),
                "p50_ms": round(s[p50_idx], 3),
                "p95_ms": round(s[p95_idx], 3),
                "p99_ms": round(s[p99_idx], 3),
                "max_ms": round(s[-1], 3),
                "mean_ms": round(sum(s) / n, 3),
            }

        health_stats = calc_percentiles(all_health_latencies)
        session_stats = calc_percentiles(all_session_latencies)

        commit_sha = os.environ.get("GITHUB_SHA")
        if not commit_sha:
            try:
                commit_sha = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
                ).decode("utf-8").strip()
            except Exception:
                commit_sha = "unknown"

        waitress_ver = getattr(waitress, "__version__", None)
        if not waitress_ver:
            try:
                import importlib.metadata
                waitress_ver = importlib.metadata.version("waitress")
            except Exception:
                waitress_ver = "unknown"

        artifact_payload = {
            "protocol": "AC09-P99-EVIDENCE",
            "version": "1.0",
            "commit_sha": commit_sha,
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "environment": {
                "os": platform.system(),
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "waitress_version": waitress_ver,
            },
            "configuration": {
                "waitress_workers": 8,
                "gate_concurrency": 1,
                "gate_max_queue": 5,
                "gate_runtime_timeout_seconds": 10.0,
                "fixture_queue_timeout_seconds": 30.0,
                "total_batches": 10,
                "samples_per_batch_per_endpoint": 100,
                "total_samples_per_endpoint": 1000,
                "probe_cookies_per_batch": 2,
                "session_probes_per_cookie": 50,
                "warmup_requests_per_endpoint": 5,
                "session_warmup_cookie_split": [3, 2],
                "percentile_method": "nearest_rank (ceil(p * N) - 1, 0-indexed)",
            },
            "summary": {
                "total_duration_seconds": round(total_duration, 3),
                "saturation_verified": True,
                "tool_hook_executed": True,
                "healthz": {
                    **health_stats,
                    "slo_50ms_met": health_stats["p99_ms"] <= 50.0,
                },
                "api_session": {
                    **session_stats,
                    "slo_50ms_met": session_stats["p99_ms"] <= 50.0,
                },
            },
            "batches": batches_meta,
            "raw_samples": {
                "healthz_ms": [round(x, 3) for x in all_health_latencies],
                "api_session_ms": [round(x, 3) for x in all_session_latencies],
            },
        }

        artifact_path = Path(__file__).resolve().parents[1] / "evals" / "reports" / "headroom_p99_artifact.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        with open(artifact_path, "w", encoding="utf-8") as f:
            json.dump(artifact_payload, f, indent=2)

        self.assertLessEqual(
            health_stats["p99_ms"], 50.0,
            f"GET /healthz empirical nearest-rank P99 ({health_stats['p99_ms']}ms) exceeded 50.0ms SLO"
        )
        self.assertLessEqual(
            session_stats["p99_ms"], 50.0,
            f"GET /api/session empirical nearest-rank P99 ({session_stats['p99_ms']}ms) exceeded 50.0ms SLO"
        )


if __name__ == "__main__":
    unittest.main()
