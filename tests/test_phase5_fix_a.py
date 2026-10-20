"""Phase 5 Fix A regression suite: Manager Navigation (FIXA-UI1..UI4) and
Demo Data Source / Targeted Order Purge / Tombstone Guard (FIXA-DATA1..DATA5).
"""
from __future__ import annotations

import io
import json
import secrets
import tempfile
import time
import unittest
from pathlib import Path

from retailops.core import ApiError, ROOT
from retailops.http.public import PublicWeb
from retailops.identity.persistent import PersistentSessions
from retailops.sales.events import compute_signature
from retailops.sales.fixtures import FIXTURE_ORDER_MULTI_ITEM
from retailops.sales.simulator import DEFAULT_DEV_SECRET, DEFAULT_SAMPLE_ITEMS, SalesSimulator
from scripts import purge_demo_order as purge_cli


def _wsgi_call(app, method: str, path: str, *, body=None, cookie: str = "", query: str = ""):
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    captured = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(headers)

    env = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "HTTP_HOST": "shop.example.com",
        "REMOTE_ADDR": "127.0.0.1",
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw),
    }
    if cookie:
        env["HTTP_COOKIE"] = cookie
    out = b"".join(app(env, start_response))
    parsed = json.loads(out.decode("utf-8")) if out else {}
    return captured["status"], parsed, captured["headers"]


class Phase5FixATests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_fixa_ui1_to_ui4_manager_navigation_assets_and_layout_contract(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

        # FIXA-UI1 & UI3: Semantic tablist, tab buttons, and tabpanels exist in HTML
        self.assertIn('id="manager-nav-tabs"', html)
        self.assertIn('role="tablist"', html)
        for tab_key in ("kpis", "products", "sops", "orders", "audit", "accounts"):
            self.assertIn(f'id="tab-btn-{tab_key}"', html)
            self.assertIn(f'aria-controls="tab-content-{tab_key}"', html)
            self.assertIn(f'id="tab-content-{tab_key}"', html)
            self.assertIn(f'aria-labelledby="tab-btn-{tab_key}"', html)

        # FIXA-UI2: Persistent back-to-KPIs navigation buttons exist in header and non-KPI panels
        for back_id in (
            "btn-manager-back-to-kpis",
            "btn-products-back-to-kpis",
            "btn-sops-back-to-kpis",
            "btn-orders-back-to-kpis",
            "btn-audit-back-to-kpis",
            "btn-accounts-back-to-kpis",
        ):
            self.assertIn(f'id="{back_id}"', html)

        # FIXA-UI2: CSS prevents flex-column collapse of .manager-nav-tabs and .manager-console-header
        self.assertIn("flex-shrink: 0;", css)
        self.assertIn("position: sticky;", css)
        self.assertIn("min-height: 44px;", css)
        self.assertIn(".manager-tab-content[hidden]", css)

        # FIXA-UI1 & UI4: JS controller resets to 'kpis' on openManagerConsole() and wires keyboard + back buttons
        self.assertIn("function switchManagerTab(", js)
        self.assertIn("function handleManagerTabKeydown(", js)
        self.assertIn("switchManagerTab('kpis');", js)
        self.assertIn("MANAGER_BACK_KPI_BTN_IDS", js)

    def test_fixa_data1_runtime_sources_and_p602_catalog_preservation(self):
        legacy_name = "Quần tây ống đứng tôn dáng"
        owner_name = "Quần tây đen hàn quốc"

        # 1. Runtime producer files must not contain the legacy order/product snapshot name
        runtime_paths = [
            ROOT / "data" / "products.json",
            ROOT / "retailops" / "business" / "store.py",
            ROOT / "retailops" / "http" / "routes.py",
            ROOT / "retailops" / "sales" / "simulator.py",
            ROOT / "retailops" / "sales" / "fixtures.py",
            ROOT / "notebooks" / "colab_agent.ipynb",
        ]
        for path in runtime_paths:
            content = path.read_text(encoding="utf-8")
            self.assertNotIn(legacy_name, content, f"Legacy snapshot name still present in runtime file {path}")

        # 2. Simulator & fixture items for P-602 use owner-updated name
        p602_sim = [i for i in DEFAULT_SAMPLE_ITEMS if i["product_id"] == "P-602"]
        self.assertEqual(len(p602_sim), 1)
        self.assertEqual(p602_sim[0]["product_title"], owner_name)
        p602_fix = [i for i in FIXTURE_ORDER_MULTI_ITEM["items"] if i["product_id"] == "P-602"]
        self.assertEqual(len(p602_fix), 1)
        self.assertEqual(p602_fix[0]["product_title"], owner_name)

        # 3. Seeded catalog preserves P-602 with owner-updated name and commercial attributes
        sessions = PersistentSessions(self.tmp_path / "p602_cat", data_mode="persistent-demo")
        bstore = sessions.provision_tenant("demo-store", "Demo Store", seed_demo=True)
        p602 = bstore.get_product("P-602")
        self.assertIsNotNone(p602)
        self.assertEqual(p602["id"], "P-602")
        self.assertEqual(p602["name"], owner_name)
        self.assertEqual(p602["price"], 520000)
        self.assertEqual(p602["stock"], 40)
        self.assertEqual(p602["warranty_days"], 90)
        self.assertEqual(p602["variants"], ["Đen · Size S", "Đen · Size M", "Đen · Size L"])

    def test_fixa_data2_to_data5_targeted_purge_guards_retention_and_tombstone(self):
        sessions = PersistentSessions(self.tmp_path / "purge_suite", data_mode="persistent-demo")
        bstore = sessions.provision_tenant("demo-store", "Demo Store", seed_demo=True)
        web = PublicWeb("https://shop.example.com", sessions)

        now = time.time()
        with bstore.connection(write=True) as db:
            db.execute("INSERT INTO customers(id, name) VALUES ('CG-d9b82ffe', 'Demo Customer') ON CONFLICT DO NOTHING")
            db.execute("INSERT INTO customers(id, name) VALUES ('mgr_demo', 'Store Manager') ON CONFLICT DO NOTHING")
            db.execute(
                """INSERT INTO orders(id, customer_id, name, variant, amount, status, version, cancel_reason, product_id)
                   VALUES ('O-819125', 'CG-d9b82ffe', 'Áo sơ mi lụa công sở', 'Trắng / M', 450000, 'pending', 1, NULL, 'P-601'),
                          ('O-819126', 'CG-d9b82ffe', 'Quần tây ống đứng tôn dáng', 'Đen / L', 520000, 'delivered', 1, NULL, 'P-602'),
                          ('O-819127', 'CG-d9b82ffe', 'Giày lười da bò cao cấp', 'Nâu / 41', 890000, 'delivered', 1, NULL, 'P-603')"""
            )
            db.execute(
                """INSERT INTO order_items(id, tenant_id, order_id, product_id, variant_id, product_title, variant_name, quantity, unit_price, subtotal, created_at)
                   VALUES ('oi-819126-1', 'demo-store', 'O-819126', 'P-602', 'P-602-L-Đen', 'Quần tây ống đứng tôn dáng', 'Đen / L', 1, 520000, 520000, ?)""",
                (now,),
            )
            db.execute(
                """INSERT INTO proposals(id, customer_id, order_id, order_version, reason, expires_at, state)
                   VALUES ('prop-819126-dismissed', 'CG-d9b82ffe', 'O-819126', 1, 'changed_mind', ?, 'dismissed')""",
                (now + 600,),
            )
            db.execute(
                """INSERT INTO conversations(id, customer_id, order_id, product_id, revision, expires_at, provider_id)
                   VALUES ('11111111-2222-3333-4444-555555555555', 'CG-d9b82ffe', 'O-819126', 'P-602', 1, ?, 'custom')""",
                (now + 3600,),
            )
            db.execute(
                """INSERT INTO agent_turns(conversation_id, customer_id, request_id, input_hash, messages, result, created_at)
                   VALUES ('11111111-2222-3333-4444-555555555555', 'CG-d9b82ffe', 'req-1', 'hash-1', '[]', '{"message":"ok"}', ?)""",
                (now,),
            )
            db.execute(
                """INSERT INTO business_events(customer_id, created_at, kind, order_id, payload)
                   VALUES ('CG-d9b82ffe', ?, 'demo_sample_fixture_seeded', 'O-819126', '{"fixture":"google_demo_sample_v1"}')""",
                (now,),
            )
            db.execute(
                """INSERT INTO imported_events(id, source_system, event_id, tenant_id, external_customer_id, customer_id, order_id, status, total, currency, payload_json, signature, created_at)
                   VALUES ('imp-819126', 'sales_simulator', 'evt-819126', 'demo-store', 'ext-cg-demo', 'CG-d9b82ffe', 'O-819126', 'delivered', 520000, 'VND', '{}', 'sig-819126', ?)""",
                (now,),
            )

        # Create customer CG-d9b82ffe and manager memberships + cookies
        mid_cust = sessions.create_member(
            "demo-store", "prin_cg_demo", "Demo Customer", "CG-d9b82ffe", role="customer"
        )
        tok_cust = secrets.token_urlsafe(32)
        sessions.control.register_credential(mid_cust, tok_cust)
        cookie_cust = f"{sessions.cookie_name}={sessions.login(tok_cust)}"

        mid_mgr = sessions.create_member(
            "demo-store", "prin_mgr_demo", "Store Manager", "mgr_demo", role="manager"
        )
        tok_mgr = secrets.token_urlsafe(32)
        sessions.control.register_credential(mid_mgr, tok_mgr)
        cookie_mgr = f"{sessions.cookie_name}={sessions.login(tok_mgr)}"

        target_kwargs = dict(
            tenant_id="demo-store",
            order_id="O-819126",
            customer_id="CG-d9b82ffe",
            product_id="P-602",
            status="delivered",
            amount=520000,
            snapshot_name="Quần tây ống đứng tôn dáng",
        )

        # Pre-purge KPI baseline
        code_kpi_before, kpi_before, _ = _wsgi_call(web, "GET", "/api/manager/kpis", cookie=cookie_mgr)
        self.assertEqual(code_kpi_before, 200)

        # 1. Fail-closed guards: wrong tenant, wrong order_id, wrong tuple fields, missing execute reason
        with self.assertRaises(ApiError) as ctx_tenant:
            sessions.purge_demo_order(**{**target_kwargs, "tenant_id": "unknown-tenant"})
        self.assertEqual(ctx_tenant.exception.status, 404)

        with self.assertRaises(ApiError) as ctx_missing:
            sessions.purge_demo_order(**{**target_kwargs, "order_id": "O-999999"})
        self.assertEqual(ctx_missing.exception.code, "purge_target_not_found")

        for field_override in (
            {"customer_id": "C-001"},
            {"product_id": "P-603"},
            {"status": "pending"},
            {"amount": 450000},
            {"snapshot_name": "Quần tây đen hàn quốc"},
        ):
            with self.assertRaises(ApiError) as ctx_mismatch:
                sessions.purge_demo_order(**{**target_kwargs, **field_override})
            self.assertEqual(ctx_mismatch.exception.code, "purge_tuple_mismatch")

        with self.assertRaises(ApiError) as ctx_reason:
            sessions.purge_demo_order(**target_kwargs, execute=True, reason="   ")
        self.assertEqual(ctx_reason.exception.code, "purge_reason_required")

        # 2. Dry-run default (via API & CLI): verifies exact match and counts without mutating DB
        dry_res = sessions.purge_demo_order(**target_kwargs, execute=False)
        self.assertEqual(dry_res["status"], "dry_run_verified")
        self.assertFalse(dry_res["executed"])
        self.assertEqual(dry_res["pre_counts"]["orders_target"], 1)
        self.assertEqual(dry_res["pre_counts"]["order_items_target"], 1)
        self.assertEqual(dry_res["pre_counts"]["proposals_target"], 1)
        self.assertEqual(dry_res["pre_counts"]["conversations_linked"], 1)
        self.assertEqual(dry_res["pre_counts"]["business_events_target"], 1)
        self.assertEqual(dry_res["pre_counts"]["imported_events_target"], 1)
        self.assertEqual(dry_res["pre_counts"]["sibling_order_ids"], ["O-819125", "O-819127"])

        cli_dry_code = purge_cli.main(
            [
                "--data-dir",
                str(self.tmp_path / "purge_suite"),
                "--tenant-id",
                "demo-store",
                "--order-id",
                "O-819126",
                "--customer-id",
                "CG-d9b82ffe",
                "--product-id",
                "P-602",
                "--status",
                "delivered",
                "--amount",
                "520000",
                "--snapshot-name",
                "Quần tây ống đứng tôn dáng",
            ]
        )
        self.assertEqual(cli_dry_code, 0)

        # Order still exists after dry-run
        code_det_before, _, _ = _wsgi_call(web, "GET", "/api/orders/O-819126", cookie=cookie_cust)
        self.assertEqual(code_det_before, 200)

        # 3. Execute targeted purge via CLI --execute
        cli_exec_code = purge_cli.main(
            [
                "--data-dir",
                str(self.tmp_path / "purge_suite"),
                "--tenant-id",
                "demo-store",
                "--order-id",
                "O-819126",
                "--customer-id",
                "CG-d9b82ffe",
                "--product-id",
                "P-602",
                "--status",
                "delivered",
                "--amount",
                "520000",
                "--snapshot-name",
                "Quần tây ống đứng tôn dáng",
                "--execute",
                "--reason",
                "Phase 5 Fix A cleanup of legacy demo snapshot order O-819126",
                "--operator-id",
                "owner-cli",
            ]
        )
        self.assertEqual(cli_exec_code, 0)

        # 4. Idempotent second execution returns already_purged without error
        idem_res = sessions.purge_demo_order(
            **target_kwargs,
            execute=True,
            reason="Idempotent re-run check",
            operator_id="owner-cli",
        )
        self.assertEqual(idem_res["status"], "already_purged")
        self.assertTrue(idem_res["idempotent_replay"])
        self.assertFalse(idem_res["executed"])
        post_counts = idem_res["post_counts"]
        self.assertEqual(post_counts["orders_target"], 0)
        self.assertEqual(post_counts["order_items_target"], 0)
        self.assertEqual(post_counts["proposals_target"], 0)
        self.assertEqual(post_counts["conversations_linked"], 0)
        self.assertEqual(post_counts["conversations_total"], 1)
        self.assertEqual(post_counts["imported_events_target"], 1)
        self.assertEqual(post_counts["business_events_target"], 3)
        self.assertEqual(post_counts["tombstones_target"], 1)
        self.assertEqual(post_counts["sibling_order_ids"], ["O-819125", "O-819127"])

        # 5. Customer & Manager UI/API views reflect removal and recalculated KPIs, while preserving P-602 & siblings
        code_cust_list, cust_list, _ = _wsgi_call(web, "GET", "/api/orders", cookie=cookie_cust)
        self.assertEqual(code_cust_list, 200)
        cust_oids = [o["id"] for o in cust_list["orders"]]
        self.assertEqual(sorted(cust_oids), ["O-819125", "O-819127"])
        self.assertNotIn("O-819126", cust_oids)

        code_cust_det, _, _ = _wsgi_call(web, "GET", "/api/orders/O-819126", cookie=cookie_cust)
        self.assertEqual(code_cust_det, 404)

        code_mgr_list, mgr_list, _ = _wsgi_call(web, "GET", "/api/orders", cookie=cookie_mgr)
        self.assertEqual(code_mgr_list, 200)
        mgr_oids = [o["id"] for o in mgr_list["orders"]]
        self.assertNotIn("O-819126", mgr_oids)
        self.assertIn("O-819125", mgr_oids)
        self.assertIn("O-819127", mgr_oids)

        code_kpi_after, kpi_after, _ = _wsgi_call(web, "GET", "/api/manager/kpis", cookie=cookie_mgr)
        self.assertEqual(code_kpi_after, 200)
        self.assertEqual(kpi_after["total_orders"], kpi_before["total_orders"] - 1)
        self.assertEqual(kpi_after["delivered_orders"], kpi_before["delivered_orders"] - 1)
        self.assertEqual(kpi_after["total_revenue"], kpi_before["total_revenue"] - 520000)

        p602_after = bstore.get_product("P-602")
        self.assertEqual(p602_after["name"], "Quần tây đen hàn quốc")
        self.assertEqual(p602_after["price"], 520000)
        self.assertEqual(p602_after["stock"], 40)

        # 6. Tombstone & Replay Guard (FIXA-DATA5): re-login seed, seed(), seed_catalog(), and SalesImportAdapter
        bstore.seed_demo_sample_orders("CG-d9b82ffe")
        bstore.seed()
        bstore.seed_catalog()
        self.assertTrue(bstore.is_order_purged("O-819126"))
        code_cust_recheck, cust_recheck, _ = _wsgi_call(web, "GET", "/api/orders", cookie=cookie_cust)
        self.assertEqual(code_cust_recheck, 200)
        self.assertEqual(sorted(o["id"] for o in cust_recheck["orders"]), ["O-819125", "O-819127"])

        # Attempting to replay or import an event for tombstoned order O-819126 is rejected with 409 order_purged_tombstone
        sim = SalesSimulator(tenant_id="demo-store", secret_key=DEFAULT_DEV_SECRET)
        purged_event = sim.create_order_event(
            tenant="demo-store",
            external_customer_id="ext-cg-demo",
            order_id="O-819126",
            status="delivered",
            items=[
                {
                    "product_id": "P-602",
                    "product_title": "Quần tây ống đứng tôn dáng",
                    "variant_name": "Đen / L",
                    "quantity": 1,
                    "unit_price": 520000,
                }
            ],
            event_id="evt-replay-purged-819126",
        )
        with self.assertRaises(ApiError) as ctx_tomb:
            sessions.import_sales_event(purged_event)
        self.assertEqual(ctx_tomb.exception.status, 409)
        self.assertEqual(ctx_tomb.exception.code, "order_purged_tombstone")

        # Importing a NEW valid P-602 order with a different order_id succeeds normally
        new_p602_event = sim.create_order_event(
            tenant="demo-store",
            external_customer_id="ext-cg-demo",
            order_id="O-906020",
            status="pending",
            items=[
                {
                    "product_id": "P-602",
                    "product_title": "Quần tây đen hàn quốc",
                    "variant_name": "Đen / M",
                    "quantity": 1,
                    "unit_price": 520000,
                }
            ],
            event_id="evt-new-valid-p602",
        )
        imp_res = sessions.import_sales_event(new_p602_event)
        self.assertTrue(imp_res.success)
        self.assertEqual(imp_res.order_id, "O-906020")


if __name__ == "__main__":
    unittest.main()
