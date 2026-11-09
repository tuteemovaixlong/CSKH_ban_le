import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from retailops.identity.persistent import PersistentSessions

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_E2E_PATH = REPO_ROOT / "deploy" / "live-e2e.py"
GET_LOGIN_TOKEN_PATH = REPO_ROOT / "scripts" / "get_login_token.py"
RUN_LIVE_BENCH_PATH = REPO_ROOT / "scripts" / "run_live_benchmark_http.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestLiveE2EIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module("live_e2e", LIVE_E2E_PATH)
        cls.login_token_mod = load_module("get_login_token", GET_LOGIN_TOKEN_PATH)
        cls.live_bench_mod = load_module("run_live_benchmark_http", RUN_LIVE_BENCH_PATH)

    def test_smoke_generates_fresh_synthetic_tenant_by_default(self):
        """P5-K1 + W6.1b-1: Default run_smoke creates distinct synthetic tenants and resolves seeded targets."""
        with tempfile.TemporaryDirectory() as td:
            sessions = PersistentSessions(Path(td) / "persistent")

            mock_http = MagicMock()
            mock_http.temp_dir = Path(td)
            mock_http.request.side_effect = [
                (200, {"order": {"status": "pending"}}),
                (200, {"logged_out": True}),
                (401, {"error": "unauthorized"}),
                (200, {"order": {"status": "pending"}}),
                (200, {"logged_out": True}),
                (401, {"error": "unauthorized"}),
            ]

            tenants_seen = []

            def fake_cli(args):
                if args[:2] == ["identity", "init-tenant"]:
                    tid = args[args.index("--tenant") + 1]
                    name = args[args.index("--name") + 1]
                    sessions.provision_tenant(tid, name, seed_demo="--seed-demo" in args)
                    return {"result": "TENANT_READY", "tenant_id": tid}
                return {}

            def fake_resolve(tenant, *, customer=None, order_id=None, require_staff_customer=False):
                return self.mod.select_seeded_targets(
                    sessions,
                    tenant,
                    customer=customer,
                    order_id=order_id,
                    require_staff_customer=require_staff_customer,
                )

            def fake_issue_member(tenant, principal, customer, role, cred_path):
                tenants_seen.append(tenant)
                mid = sessions.create_member(tenant, principal, principal, customer, role)
                return mid, "fake-cred"

            with patch.object(self.mod, "cli", side_effect=fake_cli), \
                 patch.object(self.mod, "resolve_tenant_targets", side_effect=fake_resolve), \
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

                expected_cid = sessions.control.get_external_customer_mapping(
                    t1, "marketplace_sim", "SIM-C-0070"
                )
                self.assertTrue(expected_cid)
                self.assertNotEqual(expected_cid, "C-001")
                self.assertEqual(report1["identity"]["tenant"], t1)
                self.assertEqual(report1["identity"]["customer"], expected_cid)
                self.assertEqual(report1["identity"]["external_order_id"], "SIM-O-00115")
                self.assertTrue(report1["identity"]["order_id"].startswith("ord_"))

    def test_select_seeded_targets_on_real_demo_tenant_and_overrides(self):
        """W6.1b-1 BLOCKER guard: select_seeded_targets resolves real customer/pending order on --seed-demo tenant."""
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            (out_dir / "persistent" / "tenants").mkdir(parents=True)
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "retailops",
                    "identity",
                    "--output",
                    str(out_dir),
                    "init-tenant",
                    "--tenant",
                    "smoke-demo",
                    "--name",
                    "Smoke Demo",
                    "--seed-demo",
                ],
                check=True,
            )
            sessions = PersistentSessions(out_dir / "persistent")
            targets = self.mod.select_seeded_targets(
                sessions, "smoke-demo", require_staff_customer=True
            )
            bstore = sessions.business_store("smoke-demo")
            orders = bstore.orders(targets["customer"])
            self.assertGreaterEqual(len(orders), 2, "Selected smoke customer must have >= 2 orders")
            pending = next((o for o in orders if o["id"] == targets["order_id"]), None)
            self.assertIsNotNone(pending)
            self.assertEqual(pending["status"], "pending")
            self.assertEqual(pending["external_order_id"], "SIM-O-00115")
            self.assertEqual(targets["external_order_id"], "SIM-O-00115")
            self.assertNotEqual(targets["staff_customer"], targets["customer"])
            # Both customer and staff_customer can be bound to real memberships without error
            cust_mid = sessions.create_member(
                "smoke-demo", "e2e-cust", "E2E Customer", targets["customer"], "customer"
            )
            staff_mid = sessions.create_member(
                "smoke-demo", "e2e-staff", "E2E Staff", targets["staff_customer"], "staff"
            )
            self.assertTrue(cust_mid)
            self.assertTrue(staff_mid)

            # CLI --resolve-targets entrypoint also works against RETAILOPS_OUTPUT
            env = dict(os.environ, RETAILOPS_OUTPUT=str(out_dir), PYTHONPATH=str(REPO_ROOT))
            env.pop("RETAILOPS_DATABASE_URL", None)
            env.pop("RETAILOPS_STORAGE_BACKEND", None)
            cli_out = subprocess.run(
                [
                    sys.executable,
                    str(LIVE_E2E_PATH),
                    "--resolve-targets",
                    "--tenant",
                    "smoke-demo",
                    "--require-staff-customer",
                ],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertEqual(json.loads(cli_out.stdout.strip()), targets)

            # Explicit E2E_CUSTOMER / E2E_ORDER_ID overrides work with both external and internal IDs
            override_by_ext = self.mod.select_seeded_targets(
                sessions,
                "smoke-demo",
                customer="SIM-C-0070",
                order_id="SIM-O-00115",
            )
            self.assertEqual(override_by_ext["customer"], targets["customer"])
            self.assertEqual(override_by_ext["order_id"], targets["order_id"])

            # Also verify overriding onto a second distinct customer/pending order
            with bstore.connection(write=True) as db:
                db.execute(
                    "INSERT INTO customers (id, name) VALUES ('cust_override_test', 'Override Test')"
                )
                db.execute(
                    """INSERT INTO orders (
                           id, customer_id, product_id, source_system, external_order_id,
                           name, variant, amount, status, ordered_at, ordered_at_backfilled,
                           payment_method, payment_status, version
                       ) VALUES (
                           'ord_override_01', 'cust_override_test', 'P-101', 'marketplace_sim',
                           'SIM-O-OVERRIDE-01', 'Áo thun Essential', 'Trắng · Size M',
                           299000, 'pending', 1762600000.0, 0, 'cod', 'unpaid', 1
                       )"""
                )
            override_internal = self.mod.select_seeded_targets(
                sessions,
                "smoke-demo",
                customer="cust_override_test",
                order_id="ord_override_01",
            )
            self.assertEqual(override_internal["customer"], "cust_override_test")
            self.assertEqual(override_internal["order_id"], "ord_override_01")

            override_external = self.mod.select_seeded_targets(
                sessions,
                "smoke-demo",
                order_id="SIM-O-OVERRIDE-01",
            )
            self.assertEqual(override_external["customer"], "cust_override_test")
            self.assertEqual(override_external["order_id"], "ord_override_01")

            # Legacy dead IDs (C-001, O-101) fail closed immediately
            with self.assertRaises(self.mod.E2EFailure):
                self.mod.select_seeded_targets(sessions, "smoke-demo", customer="C-001")
            with self.assertRaises(self.mod.E2EFailure):
                self.mod.select_seeded_targets(sessions, "smoke-demo", order_id="O-101")

    def test_login_token_and_benchmark_scripts_issue_valid_seeded_credentials(self):
        """W6.1b-1 BLOCKER guard: get_login_token.py and run_live_benchmark_http.py work on v2 seeded demo."""
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            (out_dir / "persistent" / "tenants").mkdir(parents=True)
            env = dict(
                os.environ,
                RETAILOPS_OUTPUT=str(out_dir),
                E2E_TENANT="retailops-demo",
                PYTHONPATH=str(REPO_ROOT),
            )
            env.pop("RETAILOPS_DATABASE_URL", None)
            env.pop("RETAILOPS_STORAGE_BACKEND", None)

            res_login = subprocess.run(
                [sys.executable, "-c", self.login_token_mod.PERSISTENT_TOKEN_SCRIPT],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            lines = [ln.strip() for ln in res_login.stdout.splitlines() if ln.strip() and not ln.startswith(("=", "["))]
            self.assertEqual(len(lines), 1)
            sessions = PersistentSessions(out_dir / "persistent")
            sec1 = sessions.login(lines[0])
            expected_cid = sessions.control.get_external_customer_mapping(
                "retailops-demo", "marketplace_sim", "SIM-C-0070"
            )
            with sessions.resolve(f"{sessions.cookie_name}={sec1}") as binding1:
                self.assertEqual(binding1.customer_id, expected_cid)

            res_bench = subprocess.run(
                [sys.executable, "-c", self.live_bench_mod.PERSISTENT_AUTO_TOKEN_SCRIPT],
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            auto_line = next(
                ln for ln in res_bench.stdout.splitlines() if ln.startswith("RETAILOPS_AUTO_TOKEN=")
            )
            auto_tok = auto_line.split("=", 1)[1].strip()
            sec2 = sessions.login(auto_tok)
            with sessions.resolve(f"{sessions.cookie_name}={sec2}") as binding2:
                self.assertEqual(binding2.customer_id, expected_cid)

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

        def fake_resolve(tenant, *, customer=None, order_id=None, require_staff_customer=False):
            captured["resolve"] = (tenant, customer, order_id)
            return {
                "customer": customer,
                "order_id": order_id,
                "external_order_id": "SIM-O-CUSTOM-1",
                "product_id": "P-101",
                "staff_customer": "cust_other",
            }

        def fake_issue_member(tenant, principal, customer, role, cred_path):
            captured["tenant"] = tenant
            captured["customer"] = customer
            return "mem-456", "fake-cred"

        with patch.object(self.mod, "cli"), \
             patch.object(self.mod, "resolve_tenant_targets", side_effect=fake_resolve), \
             patch.object(self.mod, "issue_member", side_effect=fake_issue_member), \
             patch.object(self.mod, "revoke_member"), \
             patch.object(self.mod, "login_and_basic_checks") as mock_login_checks:

            report = {"checks": {}}
            self.mod.run_smoke(
                mock_http,
                report,
                [],
                tenant="custom-tenant-99",
                customer="cust_custom_003",
                order_id="ord_custom_301",
            )

            self.assertEqual(captured["resolve"], ("custom-tenant-99", "cust_custom_003", "ord_custom_301"))
            self.assertEqual(captured["tenant"], "custom-tenant-99")
            self.assertEqual(captured["customer"], "cust_custom_003")
            mock_login_checks.assert_called_once_with(
                mock_http,
                "custom-tenant-99",
                "fake-cred",
                unittest.mock.ANY,
                report,
                customer="cust_custom_003",
                order_id="ord_custom_301",
            )
            self.assertEqual(report["identity"]["tenant"], "custom-tenant-99")
            self.assertEqual(report["identity"]["customer"], "cust_custom_003")
            self.assertEqual(report["identity"]["order_id"], "ord_custom_301")

    def test_env_var_fallbacks(self):
        """P5-K1: Test E2E_TENANT, E2E_CUSTOMER, E2E_ORDER_ID environment variable fallbacks."""
        mock_http = MagicMock()
        mock_http.temp_dir = Path("/tmp")
        mock_http.request.side_effect = [
            (200, {"order": {"status": "pending"}}),
            (200, {"logged_out": True}),
            (401, {"error": "unauthorized"}),
        ]

        def fake_resolve(tenant, *, customer=None, order_id=None, require_staff_customer=False):
            return {
                "customer": customer,
                "order_id": order_id,
                "external_order_id": order_id,
                "product_id": "P-101",
                "staff_customer": "cust_other",
            }

        with patch.dict(os.environ, {
            "E2E_TENANT": "env-tenant-123",
            "E2E_CUSTOMER": "cust_env_004",
            "E2E_ORDER_ID": "ord_env_304",
        }), \
             patch.object(self.mod, "cli"), \
             patch.object(self.mod, "resolve_tenant_targets", side_effect=fake_resolve), \
             patch.object(self.mod, "issue_member", return_value=("mem", "cred")), \
             patch.object(self.mod, "revoke_member"), \
             patch.object(self.mod, "login_and_basic_checks"):

            report = {"checks": {}}
            self.mod.run_smoke(mock_http, report, [])
            self.assertEqual(report["identity"]["tenant"], "env-tenant-123")
            self.assertEqual(report["identity"]["customer"], "cust_env_004")
            self.assertEqual(report["identity"]["order_id"], "ord_env_304")


if __name__ == "__main__":
    unittest.main()
