"""The Manager list routes the web UI calls with a query string must pass the public query gate.

Regression for production 2026-11-10: `GET /api/manager/order-actions?...` (W5) and
`GET /api/manager/compensations?...` (W6.1b-2) returned 400 `unexpected_query`, so the
"Yêu cầu đơn hàng" tab and the late-delivery compensation panel never loaded.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from retailops.core import ApiError
from retailops.http.public import PublicWeb

ROOT = Path(__file__).resolve().parents[1]


class ManagerQueryAllowlistTests(unittest.TestCase):
    def setUp(self) -> None:
        sessions = MagicMock()
        sessions.data_mode = 'persistent-demo'
        sessions.cookie_name = '__Host-retailops_account'
        self.web = PublicWeb('https://retailops.example.com', sessions, start_timer_worker=False)

    def _gate_code(self, path: str, query: str) -> str | None:
        env = {
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': path,
            'QUERY_STRING': query,
            'HTTP_HOST': 'retailops.example.com',
        }
        try:
            self.web.route(env)
        except ApiError as exc:
            return exc.code
        except Exception:
            return None
        return None

    def test_manager_list_routes_accept_query(self) -> None:
        for path, query in (
            ('/api/manager/order-actions', 'status_group=all&limit=50&offset=0'),
            ('/api/manager/compensations', 'status=all&limit=50&offset=0'),
        ):
            self.assertNotEqual(self._gate_code(path, query), 'unexpected_query', path)

    def test_other_routes_still_reject_query(self) -> None:
        self.assertEqual(self._gate_code('/api/orders', 'x=1'), 'unexpected_query')

    def test_every_frontend_query_route_is_allowlisted(self) -> None:
        app_js = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
        paths = set(re.findall(r"api\(['`](/api/[A-Za-z0-9/_-]+)\?", app_js))
        paths |= set(re.findall(r"api\('(/api/[A-Za-z0-9/_-]+)' \+ qs", app_js))
        self.assertTrue(paths)
        for path in sorted(paths):
            self.assertNotEqual(self._gate_code(path, 'limit=1'), 'unexpected_query', path)


if __name__ == '__main__':
    unittest.main()
