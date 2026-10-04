"""Tests for HTTP Chat Admission Limiter and Headroom Protection (F07 / AC-09)."""
import json
import os
import tempfile
import threading
import time
import unittest
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


if __name__ == "__main__":
    unittest.main()
