import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_E2E_PATH = REPO_ROOT / "deploy" / "live-e2e.py"


def load_live_e2e_module():
    spec = importlib.util.spec_from_file_location("live_e2e", LIVE_E2E_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestLiveE2EIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_live_e2e_module()

    def test_smoke_generates_fresh_synthetic_tenant_by_default(self):
        """P5-K1: Default run_smoke creates distinct, non-colliding synthetic tenants."""
        mock_http = MagicMock()
        mock_http.temp_dir = Path("/tmp")
        mock_http.request.side_effect = [
            (200, {"order": {"status": "pending"}}),
            (200, {"logged_out": True}),
            (401, {"error": "unauthorized"}),
            (200, {"order": {"status": "pending"}}),
            (200, {"logged_out": True}),
            (401, {"error": "unauthorized"}),
        ]

        tenants_seen = []

        def fake_issue_member(tenant, principal, customer, role, cred_path):
            tenants_seen.append(tenant)
            return "mem-123", "fake-cred"

        with patch.object(self.mod, "cli") as mock_cli, \
             patch.object(self.mod, "issue_member", side_effect=fake_issue_member), \
             patch.object(self.mod, "revoke_member"), \
             patch.object(self.mod, "login_and_basic_checks"):

            report1 = {"checks": {}}
            self.mod.run_smoke(mock_http, report1, [])

            report2 = {"checks": {}}
            self.mod.run_smoke(mock_http, report2, [])

            self.assertEqual(len(tenants_seen), 2)
            t1, t2 = tenants_seen[0], tenants_seen[1]
            self.assertTrue(t1.startswith("e2e-smoke-"))
            self.assertTrue(t2.startswith("e2e-smoke-"))
            self.assertNotEqual(t1, t2, "Successive smoke runs must use fresh distinct tenants")
            self.assertNotEqual(t1, "e2e-live-smoke", "Old reserved tenant must never be default")

            # Check identity tuple in report
            self.assertIn("identity", report1)
            self.assertEqual(report1["identity"]["tenant"], t1)
            self.assertEqual(report1["identity"]["customer"], "C-001")
            self.assertEqual(report1["identity"]["order_id"], "O-101")

    def test_smoke_accepts_explicit_parameterization_and_env(self):
        """P5-K1: Smoke respects CLI arguments and E2E_* environment variables."""
        mock_http = MagicMock()
        mock_http.temp_dir = Path("/tmp")
        mock_http.request.side_effect = [
            (200, {"order": {"status": "pending"}}),
            (200, {"logged_out": True}),
            (401, {"error": "unauthorized"}),
        ]

        captured = {}

        def fake_issue_member(tenant, principal, customer, role, cred_path):
            captured["tenant"] = tenant
            captured["customer"] = customer
            return "mem-456", "fake-cred"

        with patch.object(self.mod, "cli"), \
             patch.object(self.mod, "issue_member", side_effect=fake_issue_member), \
             patch.object(self.mod, "revoke_member"), \
             patch.object(self.mod, "login_and_basic_checks") as mock_login_checks:

            report = {"checks": {}}
            self.mod.run_smoke(
                mock_http,
                report,
                [],
                tenant="custom-tenant-99",
                customer="C-003",
                order_id="O-301",
            )

            self.assertEqual(captured["tenant"], "custom-tenant-99")
            self.assertEqual(captured["customer"], "C-003")
            mock_login_checks.assert_called_once_with(
                mock_http,
                "custom-tenant-99",
                "fake-cred",
                unittest.mock.ANY,
                report,
                customer="C-003",
                order_id="O-301",
            )
            self.assertEqual(report["identity"]["tenant"], "custom-tenant-99")
            self.assertEqual(report["identity"]["customer"], "C-003")
            self.assertEqual(report["identity"]["order_id"], "O-301")

    def test_env_var_fallbacks(self):
        """P5-K1: Test E2E_TENANT, E2E_CUSTOMER, E2E_ORDER_ID environment variable fallbacks."""
        mock_http = MagicMock()
        mock_http.temp_dir = Path("/tmp")
        mock_http.request.side_effect = [
            (200, {"order": {"status": "pending"}}),
            (200, {"logged_out": True}),
            (401, {"error": "unauthorized"}),
        ]

        with patch.dict(os.environ, {
            "E2E_TENANT": "env-tenant-123",
            "E2E_CUSTOMER": "C-004",
            "E2E_ORDER_ID": "O-304",
        }), \
             patch.object(self.mod, "cli"), \
             patch.object(self.mod, "issue_member", return_value=("mem", "cred")), \
             patch.object(self.mod, "revoke_member"), \
             patch.object(self.mod, "login_and_basic_checks"):

            report = {"checks": {}}
            self.mod.run_smoke(mock_http, report, [])
            self.assertEqual(report["identity"]["tenant"], "env-tenant-123")
            self.assertEqual(report["identity"]["customer"], "C-004")
            self.assertEqual(report["identity"]["order_id"], "O-304")


if __name__ == "__main__":
    unittest.main()
