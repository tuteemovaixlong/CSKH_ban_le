"""Unit and offline contract tests for Phase 5 P5-B: Google Test Identity & Tenant Isolation.

Verifies:
- Identity mapping: (issuer, sub, verified_email) -> principal -> tenant/customer.
- No ORDER BY id LIMIT 1: refuses ambiguous tenant selection when multiple tenants exist.
- Email is never used as a sole key: distinct sub -> distinct principal/customer.
- Unverified email cannot claim or link to existing accounts.
- Email update with identical sub updates record while preserving principal and customer.
- Audit events recorded in identity_events.
- /api/session, /api/profile, and customer/tenant order isolation.
- Completely offline, no live credentials or external network calls.
"""
import hashlib
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from retailops.core import ApiError
from retailops.http.public import PublicWeb
from retailops.identity.persistent import PersistentSessions


class Phase5GoogleIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp_dir.name)
        self.sessions = PersistentSessions(self.directory, data_mode="persistent-demo")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_google_identity_mapping_issuer_sub_verified_email(self):
        """P5-B: (issuer, sub, verified_email) maps deterministically to principal and customer."""
        tenant_id = "demo-shop-01"
        self.sessions.provision_tenant(tenant_id, "Demo Shop 01", seed_demo=True)

        issuer = "https://accounts.google.com"
        sub = "google-test-sub-10001"
        email = "tester.alpha@example.com"
        name = "Alpha Tester"

        # Initial login with verified email
        secret = self.sessions.login_google(
            email=email,
            name=name,
            role="customer",
            sub=sub,
            issuer=issuer,
            email_verified=True,
            tenant_id=tenant_id,
        )
        self.assertTrue(secret)

        # Inspect external_identity
        ext = self.sessions.control.external_identity(issuer, sub)
        self.assertIsNotNone(ext)
        self.assertEqual(ext["sub"], sub)
        self.assertEqual(ext["issuer"], issuer)
        self.assertEqual(ext["email"], email)
        principal_id = ext["principal_id"]
        self.assertTrue(principal_id.startswith("prin_"))

        # Inspect customer_link
        link = self.sessions.control.customer_link(tenant_id, principal_id)
        self.assertIsNotNone(link)
        customer_id = link["customer_id"]

        # Resolve session
        member = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={secret}"))
        self.assertEqual(member["tenant_id"], tenant_id)
        self.assertEqual(member["principal_id"], principal_id)
        self.assertEqual(member["customer_id"], customer_id)
        self.assertEqual(member["role"], "customer")

        # Re-login with the same Google sub should resolve to the same principal and customer
        secret2 = self.sessions.login_google(
            email=email,
            name=name,
            role="customer",
            sub=sub,
            issuer=issuer,
            email_verified=True,
            tenant_id=tenant_id,
        )
        member2 = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={secret2}"))
        self.assertEqual(member2["principal_id"], principal_id)
        self.assertEqual(member2["customer_id"], customer_id)

    def test_no_order_by_id_limit_1_refuses_ambiguous_tenant(self):
        """P5-B: When multiple tenants exist and none is configured, Google login refuses to guess via ORDER BY id LIMIT 1."""
        # Create two distinct stores
        self.sessions.provision_tenant("shop-apple", "Apple Store", seed_demo=True)
        self.sessions.provision_tenant("shop-banana", "Banana Store", seed_demo=True)

        # Without explicit tenant_id or default_tenant_id configured, login must fail-closed with 503 ambiguous_tenant
        with self.assertRaises(ApiError) as ctx:
            self.sessions.login_google(
                email="buyer@example.com",
                name="Buyer",
                sub="sub-ambiguous-01",
                email_verified=True,
            )
        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(ctx.exception.code, "ambiguous_tenant")

        # Explicit tenant_id resolves correctly without ambiguity
        sec_apple = self.sessions.login_google(
            email="buyer@example.com",
            name="Buyer",
            sub="sub-ambiguous-01",
            email_verified=True,
            tenant_id="shop-apple",
        )
        mem_apple = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec_apple}"))
        self.assertEqual(mem_apple["tenant_id"], "shop-apple")

    def test_configured_demo_tenant_via_env_or_property(self):
        """P5-B: Configured demo tenant via default_tenant_id or env resolves deterministically."""
        self.sessions.provision_tenant("store-alpha", "Store Alpha", seed_demo=True)
        self.sessions.provision_tenant("store-beta", "Store Beta", seed_demo=True)

        # Set default_tenant_id on sessions
        self.sessions.default_tenant_id = "store-beta"
        secret = self.sessions.login_google(
            email="beta.customer@example.com",
            name="Beta Customer",
            sub="sub-beta-01",
            email_verified=True,
        )
        mem = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={secret}"))
        self.assertEqual(mem["tenant_id"], "store-beta")

        # Test via RETAILOPS_DEMO_TENANT_ID environment variable
        self.sessions.default_tenant_id = None
        with patch.dict(os.environ, {"RETAILOPS_DEMO_TENANT_ID": "store-alpha"}):
            sec_alpha = self.sessions.login_google(
                email="alpha.customer@example.com",
                name="Alpha Customer",
                sub="sub-alpha-01",
                email_verified=True,
            )
            mem_alpha = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec_alpha}"))
            self.assertEqual(mem_alpha["tenant_id"], "store-alpha")

    def test_smoke_tenant_is_never_selected_as_google_fallback(self):
        """P5-B: Smoke/synthetic tenants (e2e-, smoke-, synthetic-) are rejected as Google demo fallback."""
        # 1. Only smoke tenants exist -> fails closed (503)
        self.sessions.provision_tenant("e2e-live-smoke", "Live Smoke Tenant", seed_demo=False)
        self.sessions.provision_tenant("smoke-fixture-tenant", "Fixture Smoke Tenant", seed_demo=False)

        with self.assertRaises(ApiError) as ctx:
            self.sessions.login_google(
                email="user@example.com",
                name="User",
                sub="sub-smoke-test-reject",
                email_verified=True,
            )
        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(ctx.exception.code, "ambiguous_tenant")

        # 2. Add one legitimate non-smoke tenant -> deterministically resolves to it, ignoring smoke tenants
        self.sessions.provision_tenant("shop-legitimate", "Real Shop", seed_demo=True)
        sec = self.sessions.login_google(
            email="real.user@example.com",
            name="Real User",
            sub="sub-smoke-test-resolve",
            email_verified=True,
        )
        mem = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec}"))
        self.assertEqual(mem["tenant_id"], "shop-legitimate")

    def test_email_never_used_as_sole_key(self):
        """P5-B: Distinct Google sub IDs with identical email NEVER share principal or customer."""
        tenant_id = "shared-email-test-tenant"
        self.sessions.provision_tenant(tenant_id, "Shared Email Shop", seed_demo=True)

        shared_email = "victim.user@gmail.com"

        # Legitimate user logs in with Google sub-legit
        sec_legit = self.sessions.login_google(
            email=shared_email,
            name="Legit User",
            sub="google-sub-legit-999",
            email_verified=True,
            tenant_id=tenant_id,
        )
        mem_legit = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec_legit}"))
        pid_legit = mem_legit["principal_id"]
        cid_legit = mem_legit["customer_id"]

        # Different Google account with sub-attacker claims same email (e.g. unverified on attacker IdP)
        sec_attacker = self.sessions.login_google(
            email=shared_email,
            name="Attacker",
            sub="google-sub-attacker-666",
            email_verified=False,
            tenant_id=tenant_id,
        )
        mem_attacker = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec_attacker}"))
        pid_attacker = mem_attacker["principal_id"]
        cid_attacker = mem_attacker["customer_id"]

        # Principals and customer IDs MUST be completely distinct
        self.assertNotEqual(pid_legit, pid_attacker)
        self.assertNotEqual(cid_legit, cid_attacker)

    def test_unverified_email_cannot_link_to_legacy_principal(self):
        """P5-B: Unverified email cannot link to an existing legacy principal."""
        tenant_id = "legacy-test-tenant"
        bstore = self.sessions.provision_tenant(tenant_id, "Legacy Shop", seed_demo=False)

        legacy_email = "target.legacy@example.com"
        clean_email = legacy_email.lower().strip()
        prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", clean_email.split("@")[0])[:25]
        hash_suffix = hashlib.sha256(clean_email.encode()).hexdigest()[:10]
        legacy_pid = f"g_{prefix}_{hash_suffix}"
        legacy_cid = f"CG-{hash_suffix[:8]}"

        # Seed legacy principal
        with self.sessions.control.connection(write=True) as id_db:
            id_db.execute("INSERT INTO principals VALUES (?,?)", (legacy_pid, "Target Legacy"))
            id_db.execute(
                "INSERT INTO memberships VALUES ('m-leg-target', ?, ?, ?, 'customer', 1, 1)",
                (tenant_id, legacy_pid, legacy_cid),
            )
        with bstore.connection(write=True) as bdb:
            bstore.seed_catalog(bdb)
            bdb.execute("INSERT INTO customers VALUES (?,?)", (legacy_cid, "Target Legacy"))
            bdb.execute(
                "INSERT INTO orders (id, customer_id, name, variant, amount, status, version, product_id) "
                "VALUES ('O-TARGET-01', ?, 'Váy Dạ Hội Đỏ', 'Đỏ / S', 950000, 'delivered', 1, 'P-601')",
                (legacy_cid,),
            )

        # Unverified email login with a new sub MUST NOT link to legacy_pid
        sec_unverified = self.sessions.login_google(
            email=legacy_email,
            name="Unverified Claimer",
            sub="sub-unverified-hijack",
            email_verified=False,
            tenant_id=tenant_id,
        )
        mem_unverified = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec_unverified}"))
        self.assertNotEqual(mem_unverified["principal_id"], legacy_pid)
        self.assertNotEqual(mem_unverified["customer_id"], legacy_cid)

    def test_email_update_with_same_sub_preserves_principal_and_customer(self):
        """P5-B: Email change with identical sub preserves identity and updates verified email."""
        tenant_id = "email-change-tenant"
        self.sessions.provision_tenant(tenant_id, "Email Change Shop", seed_demo=True)

        issuer = "https://accounts.google.com"
        sub = "google-sub-fixed-id-555"

        # Login with email 1
        sec1 = self.sessions.login_google(
            email="user.old@example.com",
            name="Fixed User",
            sub=sub,
            issuer=issuer,
            email_verified=True,
            tenant_id=tenant_id,
        )
        mem1 = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec1}"))
        pid1 = mem1["principal_id"]
        cid1 = mem1["customer_id"]

        ext1 = self.sessions.control.external_identity(issuer, sub)
        self.assertEqual(ext1["email"], "user.old@example.com")

        # User changes email on Google, but sub remains identical
        sec2 = self.sessions.login_google(
            email="user.new@example.com",
            name="Fixed User",
            sub=sub,
            issuer=issuer,
            email_verified=True,
            tenant_id=tenant_id,
        )
        mem2 = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec2}"))
        self.assertEqual(mem2["principal_id"], pid1)
        self.assertEqual(mem2["customer_id"], cid1)

        # External identity record updated with new verified email
        ext2 = self.sessions.control.external_identity(issuer, sub)
        self.assertEqual(ext2["email"], "user.new@example.com")

    def test_external_identity_audit_events_recorded(self):
        """P5-B: External identity creation and linking emit audit events into identity_events."""
        tenant_id = "audit-tenant"
        self.sessions.provision_tenant(tenant_id, "Audit Shop", seed_demo=True)

        sub = "google-sub-audit-123"
        self.sessions.login_google(
            email="audit.user@example.com",
            name="Audit User",
            sub=sub,
            email_verified=True,
            tenant_id=tenant_id,
        )

        with self.sessions.control.connection() as db:
            events = [dict(r) for r in db.execute("SELECT * FROM identity_events WHERE tenant_id=?", (tenant_id,)).fetchall()]
        event_kinds = [e["kind"] for e in events]
        self.assertIn("tenant_created", event_kinds)
        self.assertIn("external_identity_created", event_kinds)
        self.assertIn("membership_created", event_kinds)
        self.assertIn("login", event_kinds)

    def test_api_session_profile_and_tenant_customer_isolation(self):
        """P5-B: /api/session, /api/profile and order isolation between customers and tenants."""
        self.sessions.seed_sample_orders = False
        tenant_a = "shop-isolated-a"
        tenant_b = "shop-isolated-b"
        self.sessions.provision_tenant(tenant_a, "Shop A", seed_demo=False)
        self.sessions.provision_tenant(tenant_b, "Shop B", seed_demo=False)

        web = PublicWeb("https://retailops.example.com", self.sessions)

        # Customer 1 in Tenant A
        sec_a1 = self.sessions.login_google(
            email="cust.a1@example.com",
            name="Customer A1",
            sub="sub-cust-a1",
            email_verified=True,
            tenant_id=tenant_a,
        )
        # Customer 2 in Tenant A
        sec_a2 = self.sessions.login_google(
            email="cust.a2@example.com",
            name="Customer A2",
            sub="sub-cust-a2",
            email_verified=True,
            tenant_id=tenant_a,
        )
        # Customer 1 in Tenant B
        sec_b1 = self.sessions.login_google(
            email="cust.b1@example.com",
            name="Customer B1",
            sub="sub-cust-b1",
            email_verified=True,
            tenant_id=tenant_b,
        )

        mem_a1 = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec_a1}"))
        mem_a2 = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec_a2}"))
        mem_b1 = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec_b1}"))

        # Seed order for Customer A1 in Tenant A
        bstore_a = self.sessions.business_store(tenant_a)
        with bstore_a.connection(write=True) as bdb:
            bstore_a.seed_catalog(bdb)
            bdb.execute(
                "INSERT INTO orders (id, customer_id, name, variant, amount, status, version, product_id) "
                "VALUES ('O-A1-001', ?, 'Áo sơ mi lụa công sở', 'Trắng / M', 450000, 'pending', 1, 'P-601')",
                (mem_a1["customer_id"],),
            )

        # Seed order for Customer B1 in Tenant B
        bstore_b = self.sessions.business_store(tenant_b)
        with bstore_b.connection(write=True) as bdb:
            bstore_b.seed_catalog(bdb)
            bdb.execute(
                "INSERT INTO orders (id, customer_id, name, variant, amount, status, version, product_id) "
                "VALUES ('O-B1-001', ?, 'Quần tây ống đứng tôn dáng', 'Đen / L', 520000, 'pending', 1, 'P-602')",
                (mem_b1["customer_id"],),
            )

        # 1. Customer A1 requests /api/session
        status, sess_a1, _, _ = web.route({
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/api/session",
            "HTTP_HOST": "retailops.example.com",
            "HTTP_COOKIE": f"__Host-retailops_account={sec_a1}",
        })
        self.assertEqual(status, 200)
        self.assertEqual(sess_a1["tenant_id"], tenant_a)
        self.assertEqual(sess_a1["principal_id"], mem_a1["principal_id"])
        self.assertEqual(sess_a1["customer_id"], mem_a1["customer_id"])
        self.assertEqual(sess_a1["name"], "Customer A1")
        self.assertEqual(sess_a1["role"], "customer")

        # 2. Customer A1 requests /api/profile
        status, prof_a1, _, _ = web.route({
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/api/profile",
            "HTTP_HOST": "retailops.example.com",
            "HTTP_COOKIE": f"__Host-retailops_account={sec_a1}",
        })
        self.assertEqual(status, 200)
        self.assertEqual(prof_a1["tenant_id"], tenant_a)
        self.assertEqual(prof_a1["principal_id"], mem_a1["principal_id"])
        self.assertEqual(prof_a1["customer_id"], mem_a1["customer_id"])
        self.assertEqual(prof_a1["name"], "Customer A1")
        self.assertEqual(prof_a1["role"], "customer")

        # 3. Customer A1 sees only their order O-A1-001
        status, orders_a1, _, _ = web.route({
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/api/orders",
            "HTTP_HOST": "retailops.example.com",
            "HTTP_COOKIE": f"__Host-retailops_account={sec_a1}",
        })
        self.assertEqual(status, 200)
        a1_ids = [o["id"] for o in orders_a1["orders"]]
        self.assertEqual(a1_ids, ["O-A1-001"])

        # 4. Customer A2 in same Tenant A sees ZERO orders (cannot see A1's order)
        status, orders_a2, _, _ = web.route({
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/api/orders",
            "HTTP_HOST": "retailops.example.com",
            "HTTP_COOKIE": f"__Host-retailops_account={sec_a2}",
        })
        self.assertEqual(status, 200)
        self.assertEqual(len(orders_a2["orders"]), 0)

        # 5. Customer B1 in Tenant B sees only O-B1-001 (cannot see Tenant A's orders)
        status, orders_b1, _, _ = web.route({
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/api/orders",
            "HTTP_HOST": "retailops.example.com",
            "HTTP_COOKIE": f"__Host-retailops_account={sec_b1}",
        })
        self.assertEqual(status, 200)
        b1_ids = [o["id"] for o in orders_b1["orders"]]
        self.assertEqual(b1_ids, ["O-B1-001"])

    def test_same_google_identity_across_tenants_gets_isolated_customers(self):
        """P5-B: One Google principal logging into Tenant 1 and Tenant 2 receives separate customer_ids."""
        t1, t2 = "multi-shop-1", "multi-shop-2"
        self.sessions.provision_tenant(t1, "Multi Shop 1", seed_demo=True)
        self.sessions.provision_tenant(t2, "Multi Shop 2", seed_demo=True)

        issuer = "https://accounts.google.com"
        sub = "google-sub-cross-tenant-777"
        email = "cross.tenant@example.com"

        # Login to Tenant 1 (initial onboarding of unknown Google identity)
        sec1 = self.sessions.login_google(email=email, name="Cross User", sub=sub, issuer=issuer, email_verified=True, tenant_id=t1)
        mem1 = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec1}"))
        pid1, cid1 = mem1["principal_id"], mem1["customer_id"]

        # Provision existing Google identity in Tenant 2 via control plane before login to Tenant 2
        self.sessions.control.get_or_create_google_member(
            t2, email, "Cross User", sub=sub, issuer=issuer, email_verified=True
        )
        sec2 = self.sessions.login_google(email=email, name="Cross User", sub=sub, issuer=issuer, email_verified=True, tenant_id=t2)
        mem2 = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec2}"))
        pid2, cid2 = mem2["principal_id"], mem2["customer_id"]

        # Principal is the same (same physical user)
        self.assertEqual(pid1, pid2)
        # But customer IDs in distinct tenants MUST be distinct
        self.assertNotEqual(cid1, cid2)

        # Customer links exist per tenant
        link1 = self.sessions.control.customer_link(t1, pid1)
        link2 = self.sessions.control.customer_link(t2, pid2)
        self.assertEqual(link1["customer_id"], cid1)
        self.assertEqual(link2["customer_id"], cid2)

    def test_live_mode_security_guards(self):
        """P5-B: In live mode, missing sub is rejected (400 missing_sub) and no demo orders seeded."""
        live_dir = self.directory / "live_mode_store"
        live_sessions = PersistentSessions(live_dir, data_mode="live")
        live_sessions.provision_tenant("live-store", "Live Store", seed_demo=False)

        # Missing sub rejected with 400 missing_sub
        with self.assertRaises(ApiError) as ctx:
            live_sessions.login_google(
                email="live.user@example.com",
                name="Live User",
                sub=None,
                live=True,
                tenant_id="live-store",
            )
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "missing_sub")

        # Valid sub in live mode: logs in and does NOT seed sample orders
        secret = live_sessions.login_google(
            email="live.user@example.com",
            name="Live User",
            sub="live-sub-valid-99",
            email_verified=True,
            live=True,
            tenant_id="live-store",
        )
        mem = live_sessions.control.resolve(live_sessions.cookie_id(f"__Host-retailops_account={secret}"))
        bstore = live_sessions.business_store("live-store")
        orders = bstore.orders(mem["customer_id"])
        self.assertEqual(len(orders), 0)

    def test_invalid_or_nonexistent_tenant_raises_error(self):
        """P5-B: Explicit login to nonexistent tenant raises 503 tenant_unavailable."""
        with self.assertRaises(ApiError) as ctx:
            self.sessions.login_google(
                email="user@example.com",
                name="User",
                sub="sub-test-tenant-err",
                email_verified=True,
                tenant_id="does-not-exist",
            )
        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(ctx.exception.code, "tenant_unavailable")

    def test_inactive_or_smoke_target_tenant_rejected_with_tenant_unavailable(self):
        """P5-K3 remediation: Inactive tenant or smoke-prefixed tenant (case-insensitive) in selector raises 503 tenant_unavailable."""
        self.sessions.provision_tenant("shop-inactive", "Inactive Shop", seed_demo=True)
        self.sessions.provision_tenant("e2e-smoke-999", "Smoke Shop", seed_demo=True)
        self.sessions.provision_tenant("E2E-UPPER-999", "Upper Smoke Shop", seed_demo=True)
        self.sessions.provision_tenant("Smoke-Mixed-999", "Mixed Smoke Shop", seed_demo=True)
        with self.sessions.control.connection(write=True) as db:
            db.execute("UPDATE tenants SET active=0 WHERE id='shop-inactive'")

        for bad_tid in (
            "shop-inactive",
            "e2e-smoke-999",
            "E2E-UPPER-999",
            "Smoke-Mixed-999",
            "SYNTHETIC-DEMO-999",
            "smoke-test-1",
            "synthetic-demo-1",
        ):
            self.sessions.default_tenant_id = bad_tid
            try:
                with self.assertRaises(ApiError) as ctx:
                    self.sessions.resolve_google_tenant(sub="sub-any-1")
                self.assertEqual(ctx.exception.status, 503)
                self.assertEqual(ctx.exception.code, "tenant_unavailable")
            finally:
                self.sessions.default_tenant_id = None

        # Also verify uppercase/mixed-case smoke tenants are excluded from fallback when no real store exists
        only_smoke_dir = self.directory / "only_case_smoke"
        only_smoke_sessions = PersistentSessions(only_smoke_dir, data_mode="persistent-demo")
        only_smoke_sessions.provision_tenant("E2E-UPPER-ONLY", "Upper Smoke", seed_demo=False)
        only_smoke_sessions.provision_tenant("Smoke-Mixed-Only", "Mixed Smoke", seed_demo=False)
        only_smoke_sessions.provision_tenant("SYNTHETIC-UPPER-ONLY", "Synth Upper", seed_demo=False)
        with self.assertRaises(ApiError) as ctx_fb:
            only_smoke_sessions.resolve_google_tenant(sub="sub-case-smoke-fallback")
        self.assertEqual(ctx_fb.exception.status, 503)
        self.assertEqual(ctx_fb.exception.code, "ambiguous_tenant")

    def test_empty_env_selector_falls_back_to_legacy_and_strips_whitespace(self):
        """P5-K3 remediation: Empty RETAILOPS_DEMO_TENANT_ID falls back to GOOGLE_AUTH_TENANT_ID; whitespace/quotes trimmed."""
        from retailops.config import Settings

        self.sessions.provision_tenant("store-alpha", "Store Alpha", seed_demo=True)
        self.sessions.provision_tenant("store-beta", "Store Beta", seed_demo=True)

        # 1. Empty RETAILOPS_DEMO_TENANT_ID falls back to GOOGLE_AUTH_TENANT_ID in both Settings and resolve_google_tenant
        env_fallback = {
            "RETAILOPS_PUBLIC_ORIGIN": "https://retailops.example.com",
            "RETAILOPS_DATA_MODE": "persistent-demo",
            "RETAILOPS_DEMO_TENANT_ID": "   ",
            "GOOGLE_AUTH_TENANT_ID": ' "store-beta" ',
        }
        settings = Settings.from_environment("public", environ=env_fallback)
        self.assertEqual(settings.demo_tenant_id, "store-beta")

        with patch.dict(os.environ, {"RETAILOPS_DEMO_TENANT_ID": "", "GOOGLE_AUTH_TENANT_ID": "  store-beta  "}, clear=False):
            self.assertEqual(self.sessions.resolve_google_tenant(sub="new-sub-fallback"), "store-beta")

        # 2. Conflicting non-empty RETAILOPS_DEMO_TENANT_ID and GOOGLE_AUTH_TENANT_ID fail closed
        env_conflict = {
            "RETAILOPS_PUBLIC_ORIGIN": "https://retailops.example.com",
            "RETAILOPS_DATA_MODE": "persistent-demo",
            "RETAILOPS_DEMO_TENANT_ID": "store-alpha",
            "GOOGLE_AUTH_TENANT_ID": "store-beta",
        }
        with self.assertRaises(ValueError):
            Settings.from_environment("public", environ=env_conflict)

        with patch.dict(os.environ, {"RETAILOPS_DEMO_TENANT_ID": "store-alpha", "GOOGLE_AUTH_TENANT_ID": "store-beta"}, clear=False):
            with self.assertRaises(ApiError) as ctx:
                self.sessions.resolve_google_tenant(sub="new-sub-conflict")
            self.assertEqual(ctx.exception.status, 503)
            self.assertEqual(ctx.exception.code, "ambiguous_tenant")

    def test_membership_resolution_ignores_deactivated_tenants_and_rejects_multi_active_memberships(self):
        """P5-K3 remediation: Membership lookup joins active tenants (t.active=1), ignores case-insensitive smoke memberships,
        fails closed on inactive-only + single-active-store, multiple active memberships, and selector/identity conflicts,
        and preserves unknown identity onboarding in single-store demo without side effects on failure."""
        self.sessions.provision_tenant("store-deactivated", "Deactivated Store", seed_demo=True)
        self.sessions.provision_tenant("store-active-1", "Active Store 1", seed_demo=True)
        self.sessions.provision_tenant("store-active-2", "Active Store 2", seed_demo=True)
        self.sessions.provision_tenant("e2e-smoke-ignore", "Smoke Store", seed_demo=True)
        self.sessions.provision_tenant("E2E-UPPER-IGNORE", "Upper Smoke Store", seed_demo=True)

        def snapshot_state():
            with self.sessions.control.connection() as db:
                prins = {r["id"] for r in db.execute("SELECT id FROM principals").fetchall()}
                exts = {
                    (r["id"], r["issuer"], r["sub"], r["principal_id"])
                    for r in db.execute("SELECT id, issuer, sub, principal_id FROM external_identities").fetchall()
                }
                links = {
                    (r["id"], r["tenant_id"], r["principal_id"], r["customer_id"])
                    for r in db.execute("SELECT id, tenant_id, principal_id, customer_id FROM customer_links").fetchall()
                }
                mems = {
                    (r["id"], r["tenant_id"], r["principal_id"], r["customer_id"], r["active"])
                    for r in db.execute("SELECT id, tenant_id, principal_id, customer_id, active FROM memberships").fetchall()
                }
                sess = {r["id"] for r in db.execute("SELECT id FROM sessions").fetchall()}
            custs = {}
            for tid in ("store-deactivated", "store-active-1", "store-active-2"):
                with self.sessions.control.connection() as db:
                    skey = db.execute("SELECT storage_key FROM tenants WHERE id=?", (tid,)).fetchone()["storage_key"]
                from retailops.business.store import BusinessStore
                bstore = BusinessStore(self.sessions.directory / "tenants" / f"{skey}.sqlite3", create=False)
                with bstore.connection() as bdb:
                    c_ids = {r["id"] for r in bdb.execute("SELECT id FROM customers").fetchall()}
                    custs[tid] = (len(c_ids), c_ids)
            return (
                (len(prins), prins),
                (len(exts), exts),
                (len(links), links),
                (len(mems), mems),
                (len(sess), sess),
                custs,
            )

        issuer = "https://accounts.google.com"
        sub = "google-sub-deactivated-check-01"
        email = "member.check@example.com"

        # Provision memberships in store-deactivated, store-active-1, e2e-smoke-ignore, and E2E-UPPER-IGNORE
        self.sessions.login_google(email=email, name="Member", sub=sub, issuer=issuer, email_verified=True, tenant_id="store-deactivated")
        self.sessions.control.get_or_create_google_member(
            "store-active-1", email, "Member", sub=sub, issuer=issuer, email_verified=True
        )
        self.sessions.control.get_or_create_google_member(
            "e2e-smoke-ignore", email, "Member", sub=sub, issuer=issuer, email_verified=True
        )
        self.sessions.control.get_or_create_google_member(
            "E2E-UPPER-IGNORE", email, "Member", sub=sub, issuer=issuer, email_verified=True
        )

        # Deactivate store-deactivated while keeping its membership active=1
        with self.sessions.control.connection(write=True) as db:
            db.execute("UPDATE tenants SET active=0 WHERE id='store-deactivated'")

        # With 2 active non-smoke stores in DB (store-active-1, store-active-2) and no default_tenant_id,
        # principal has 1 active membership in an active non-smoke store -> login_google resolves store-active-1!
        sec_active1 = self.sessions.login_google(email=email, name="Member", sub=sub, issuer=issuer, email_verified=True)
        mem_active1 = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec_active1}"))
        self.assertEqual(mem_active1["tenant_id"], "store-active-1")

        # (d) Selector conflicting with an existing identity (default_tenant_id, RETAILOPS_DEMO_TENANT_ID,
        #     legacy GOOGLE_AUTH_TENANT_ID alone, or explicit tenant_id) must fail closed on full login_google()
        #     and produce ZERO new principals, external_identities, links, memberships, customers, or sessions.
        before_d = snapshot_state()
        self.sessions.default_tenant_id = "store-active-2"
        try:
            with self.assertRaises(ApiError) as ctx_d1:
                self.sessions.login_google(email=email, name="Member", sub=sub, issuer=issuer, email_verified=True)
            self.assertEqual(ctx_d1.exception.status, 503)
            self.assertEqual(ctx_d1.exception.code, "ambiguous_tenant")
        finally:
            self.sessions.default_tenant_id = None
        with patch.dict(os.environ, {"RETAILOPS_DEMO_TENANT_ID": "store-active-2"}, clear=False):
            with self.assertRaises(ApiError) as ctx_d2:
                self.sessions.login_google(email=email, name="Member", sub=sub, issuer=issuer, email_verified=True)
            self.assertEqual(ctx_d2.exception.status, 503)
            self.assertEqual(ctx_d2.exception.code, "ambiguous_tenant")
        with patch.dict(os.environ, {"RETAILOPS_DEMO_TENANT_ID": "", "GOOGLE_AUTH_TENANT_ID": "store-active-2"}, clear=False):
            with self.assertRaises(ApiError) as ctx_d_leg:
                self.sessions.login_google(email=email, name="Member", sub=sub, issuer=issuer, email_verified=True)
            self.assertEqual(ctx_d_leg.exception.status, 503)
            self.assertEqual(ctx_d_leg.exception.code, "ambiguous_tenant")
        with self.assertRaises(ApiError) as ctx_d3:
            self.sessions.login_google(email=email, name="Member", sub=sub, issuer=issuer, email_verified=True, tenant_id="store-active-2")
        self.assertEqual(ctx_d3.exception.status, 503)
        self.assertEqual(ctx_d3.exception.code, "ambiguous_tenant")
        self.assertEqual(snapshot_state(), before_d)

        # (b) Multiple active memberships: if the principal ALSO has an active membership in store-active-2,
        #     full login_google() without explicit tenant_id (even with default_tenant_id set) must fail closed
        #     with 503 ambiguous_tenant and produce ZERO new links, memberships, customers, or sessions.
        self.sessions.control.get_or_create_google_member(
            "store-active-2", email, "Member", sub=sub, issuer=issuer, email_verified=True
        )
        before_b = snapshot_state()
        with self.assertRaises(ApiError) as ctx_b1:
            self.sessions.login_google(email=email, name="Member", sub=sub, issuer=issuer, email_verified=True)
        self.assertEqual(ctx_b1.exception.status, 503)
        self.assertEqual(ctx_b1.exception.code, "ambiguous_tenant")
        self.sessions.default_tenant_id = "store-active-1"
        try:
            with self.assertRaises(ApiError) as ctx_b2:
                self.sessions.login_google(email=email, name="Member", sub=sub, issuer=issuer, email_verified=True)
            self.assertEqual(ctx_b2.exception.status, 503)
            self.assertEqual(ctx_b2.exception.code, "ambiguous_tenant")
        finally:
            self.sessions.default_tenant_id = None
        self.assertEqual(snapshot_state(), before_b)

        # (a) Inactive-only membership + EXACTLY ONE other active non-smoke store:
        #     known identity whose only membership is in a deactivated tenant (or deactivated membership)
        #     must NOT fall through to the sole active store ('store-active-1') on login_google(),
        #     and must produce ZERO new customer_links, memberships, business customers, or sessions.
        sub_only_inactive = "google-sub-only-inactive-02"
        with self.sessions.control.connection(write=True) as db:
            db.execute("UPDATE tenants SET active=1 WHERE id='store-deactivated'")
        self.sessions.login_google(
            email="only.inactive@example.com",
            name="Only Inactive",
            sub=sub_only_inactive,
            issuer=issuer,
            email_verified=True,
            tenant_id="store-deactivated",
        )
        with self.sessions.control.connection(write=True) as db:
            # Leave ONLY 'store-active-1' active among non-smoke stores!
            db.execute("UPDATE tenants SET active=0 WHERE id IN ('store-deactivated', 'store-active-2')")
            db.execute("DELETE FROM sessions")

        before_a = snapshot_state()
        with self.assertRaises(ApiError) as ctx_a1:
            self.sessions.login_google(
                email="only.inactive@example.com",
                name="Only Inactive",
                sub=sub_only_inactive,
                issuer=issuer,
                email_verified=True,
            )
        self.assertEqual(ctx_a1.exception.status, 503)
        self.assertEqual(ctx_a1.exception.code, "ambiguous_tenant")

        self.sessions.default_tenant_id = "store-active-1"
        try:
            with self.assertRaises(ApiError) as ctx_a2:
                self.sessions.login_google(
                    email="only.inactive@example.com",
                    name="Only Inactive",
                    sub=sub_only_inactive,
                    issuer=issuer,
                    email_verified=True,
                )
            self.assertEqual(ctx_a2.exception.status, 503)
            self.assertEqual(ctx_a2.exception.code, "ambiguous_tenant")
        finally:
            self.sessions.default_tenant_id = None
        self.assertEqual(snapshot_state(), before_a)

        # Also test when the tenant stays active=1 ('store-active-1') but the membership row itself is deactivated (m.active=0):
        with self.sessions.control.connection(write=True) as db:
            db.execute("UPDATE memberships SET active=0 WHERE tenant_id='store-active-1'")
        before_a_mem = snapshot_state()
        with self.assertRaises(ApiError) as ctx_a3:
            self.sessions.login_google(email=email, name="Member", sub=sub, issuer=issuer, email_verified=True)
        self.assertEqual(ctx_a3.exception.status, 503)
        self.assertEqual(ctx_a3.exception.code, "ambiguous_tenant")
        self.assertEqual(snapshot_state(), before_a_mem)

        # (e) Verified-email legacy principal (no external_identities row yet) whose only membership is inactive
        #     (in deactivated 'store-deactivated' or with m.active=0 in 'store-active-1') must fail closed BEFORE any writes
        #     (no new external_identities, customer_links, memberships, customers, or sessions) when logging in with its first Google sub.
        legacy_inactive_email = "legacy.inactive@example.com"
        leg_inact_prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", legacy_inactive_email.split("@")[0])[:25]
        leg_inact_hash = hashlib.sha256(legacy_inactive_email.encode()).hexdigest()[:10]
        leg_inact_pid = f"g_{leg_inact_prefix}_{leg_inact_hash}"
        leg_inact_cid = f"CG-{leg_inact_hash[:8]}"
        with self.sessions.control.connection(write=True) as db:
            db.execute("INSERT INTO principals (id, name) VALUES (?, ?)", (leg_inact_pid, "Legacy Inactive"))
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-leg-inact-1', 'store-deactivated', ?, ?, 'customer', 1, 1)",
                (leg_inact_pid, leg_inact_cid),
            )
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-leg-inact-2', 'store-active-1', ?, ?, 'customer', 0, 1)",
                (leg_inact_pid, leg_inact_cid),
            )

        before_leg_inact = snapshot_state()
        with self.assertRaises(ApiError) as ctx_leg1:
            self.sessions.login_google(
                email=legacy_inactive_email,
                name="Legacy Inactive",
                sub="new-sub-for-legacy-inactive",
                issuer=issuer,
                email_verified=True,
            )
        self.assertEqual(ctx_leg1.exception.status, 503)
        self.assertEqual(ctx_leg1.exception.code, "ambiguous_tenant")

        self.sessions.default_tenant_id = "store-active-1"
        try:
            with self.assertRaises(ApiError) as ctx_leg2:
                self.sessions.login_google(
                    email=legacy_inactive_email,
                    name="Legacy Inactive",
                    sub="new-sub-for-legacy-inactive",
                    issuer=issuer,
                    email_verified=True,
                )
            self.assertEqual(ctx_leg2.exception.status, 503)
            self.assertEqual(ctx_leg2.exception.code, "ambiguous_tenant")
        finally:
            self.sessions.default_tenant_id = None
        self.assertEqual(snapshot_state(), before_leg_inact)

        # Positive control for verified-email legacy principal: active membership in active 'store-active-1' links cleanly
        legacy_active_email = "legacy.active@example.com"
        leg_act_prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", legacy_active_email.split("@")[0])[:25]
        leg_act_hash = hashlib.sha256(legacy_active_email.encode()).hexdigest()[:10]
        leg_act_pid = f"g_{leg_act_prefix}_{leg_act_hash}"
        leg_act_cid = f"CG-{leg_act_hash[:8]}"
        with self.sessions.control.connection(write=True) as db:
            db.execute("INSERT INTO principals (id, name) VALUES (?, ?)", (leg_act_pid, "Legacy Active"))
            db.execute(
                "INSERT INTO memberships (id, tenant_id, principal_id, customer_id, role, active, auth_version) "
                "VALUES ('m-leg-act-1', 'store-active-1', ?, ?, 'customer', 1, 1)",
                (leg_act_pid, leg_act_cid),
            )
        sec_leg_ok = self.sessions.login_google(
            email=legacy_active_email,
            name="Legacy Active",
            sub="new-sub-for-legacy-active",
            issuer=issuer,
            email_verified=True,
        )
        mem_leg_ok = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec_leg_ok}"))
        self.assertEqual(mem_leg_ok["tenant_id"], "store-active-1")
        self.assertEqual(mem_leg_ok["principal_id"], leg_act_pid)
        self.assertEqual(mem_leg_ok["customer_id"], leg_act_cid)

        # (c) Unknown identity onboarding in a single-store demo ('store-active-1' is the sole active non-smoke store):
        #     genuinely new Google identity succeeds on login_google() and resolves to 'store-active-1'.
        sec_new_single = self.sessions.login_google(
            email="new.single@example.com",
            name="New Single Customer",
            sub="google-sub-new-single-store-03",
            issuer=issuer,
            email_verified=True,
        )
        mem_new_single = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec_new_single}"))
        self.assertEqual(mem_new_single["tenant_id"], "store-active-1")

    def test_bootstrap_and_compose_wiring_contract_for_tenant_selector(self):
        """P5-K3 remediation (C.6): Settings -> build_public_app -> Sessions wiring and Compose env_file contract."""
        from retailops.bootstrap import build_public_app
        from retailops.config import Settings
        from retailops.core import ROOT

        env = {
            "RETAILOPS_PUBLIC_ORIGIN": "https://retailops.example.com",
            "RETAILOPS_DATA_MODE": "persistent-demo",
            "RETAILOPS_OUTPUT": str(self.directory),
            "RETAILOPS_DEMO_TENANT_ID": "configured-store-01",
        }
        settings = Settings.from_environment("public", environ=env)
        self.assertEqual(settings.demo_tenant_id, "configured-store-01")
        # Secret-free summary does not leak access_token or database_url
        summary = settings.summary()
        self.assertNotIn("access_token", summary)
        self.assertNotIn("database_url", summary)

        app = build_public_app(settings)
        self.assertEqual(app.sessions.default_tenant_id, "configured-store-01")

        # Verify PostgresSessions path in build_public_app passes default_tenant_id
        pg_env = {
            "RETAILOPS_PUBLIC_ORIGIN": "https://retailops.example.com",
            "RETAILOPS_DATA_MODE": "persistent-demo",
            "RETAILOPS_STORAGE_BACKEND": "postgresql",
            "RETAILOPS_DATABASE_URL": "postgresql://retailops:secretpass@postgres:5432/retailops",
            "RETAILOPS_DEMO_TENANT_ID": "pg-configured-store",
        }
        with patch("retailops.storage.postgres.validate_dsn"), patch("retailops.identity.postgres.PostgresSessions") as mock_pg_sessions:
            pg_settings = Settings.from_environment("public", environ=pg_env)
            self.assertEqual(pg_settings.demo_tenant_id, "pg-configured-store")
            build_public_app(pg_settings)
            mock_pg_sessions.assert_called_once()
            _, kwargs = mock_pg_sessions.call_args
            self.assertEqual(kwargs.get("default_tenant_id"), "pg-configured-store")

        compose_pub = ROOT / "deploy" / "compose.public.yaml"
        compose_pg = ROOT / "deploy" / "compose.postgres.yaml"
        if compose_pub.is_file() and compose_pg.is_file():
            pub_text = compose_pub.read_text(encoding="utf-8")
            pg_text = compose_pg.read_text(encoding="utf-8")
            self.assertIn("- public.env", pub_text)
            self.assertNotIn("RETAILOPS_DEMO_TENANT_ID", pg_text)
            self.assertNotIn("GOOGLE_AUTH_TENANT_ID", pg_text)

    def test_start_public_web_env_validator_preserves_tenant_selector_and_rejects_invalid_keys(self):
        """P5-K3 remediation (C.7): deploy/start-public-web.sh public.env validator accepts tenant selectors, rejects RETAILOPS_DATA_MODE=live, rejects case-insensitive smoke prefixes, and rejects unsupported keys without leaking secrets."""
        import subprocess
        import sys
        from retailops.core import ROOT

        script_path = ROOT / "deploy" / "start-public-web.sh"
        if not script_path.is_file():
            self.skipTest("deploy/start-public-web.sh not present in standalone bundle")

        script_text = script_path.read_text(encoding="utf-8")
        marker = 'python3 - "$PUBLIC_HOSTNAME" "$staging_dir/public.env" <<\'PY\'\n'
        self.assertIn(marker, script_text)
        py_block = script_text.split(marker, 1)[1].split("\nPY\n", 1)[0]

        def run_validator(public_env_content, host="retailops.example.com"):
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                if public_env_content is not None:
                    (tmp_path / "public.env").write_text(public_env_content, encoding="utf-8")
                staged = tmp_path / "staged_public.env"
                proc = subprocess.run(
                    [sys.executable, "-", host, str(staged)],
                    input=py_block,
                    cwd=tmp_path,
                    text=True,
                    capture_output=True,
                    timeout=10,
                )
                staged_text = staged.read_text(encoding="utf-8") if staged.is_file() else ""
                return proc, staged_text

        invite_secret = "secret_invite_token_value_1234567890abcdef"
        # 1. Valid RETAILOPS_DEMO_TENANT_ID is accepted, trimmed, and preserved
        proc_ok, staged_ok = run_validator(
            f"RETAILOPS_PUBLIC_INVITE_TOKEN={invite_secret}\n"
            "RETAILOPS_DATA_MODE=persistent-demo\n"
            'RETAILOPS_DEMO_TENANT_ID="  demo-store-main  "\n'
        )
        self.assertEqual(proc_ok.returncode, 0, proc_ok.stderr)
        self.assertIn("RETAILOPS_DEMO_TENANT_ID=demo-store-main\n", staged_ok)
        self.assertIn("RETAILOPS_DATA_MODE=persistent-demo\n", staged_ok)

        # 2. Legacy GOOGLE_AUTH_TENANT_ID is accepted and preserved
        proc_legacy, staged_legacy = run_validator(
            f"RETAILOPS_PUBLIC_INVITE_TOKEN={invite_secret}\n"
            "GOOGLE_AUTH_TENANT_ID=legacy-store-01\n"
        )
        self.assertEqual(proc_legacy.returncode, 0, proc_legacy.stderr)
        self.assertIn("GOOGLE_AUTH_TENANT_ID=legacy-store-01\n", staged_legacy)

        # 3. Smoke-prefixed tenant selector (lowercase, uppercase, mixed-case) is rejected without printing secret values
        for bad_smoke in ("e2e-smoke-12345", "E2E-UPPER-12345", "Smoke-Mixed-12345", "SYNTHETIC-12345"):
            proc_smoke, _ = run_validator(
                f"RETAILOPS_PUBLIC_INVITE_TOKEN={invite_secret}\n"
                f"RETAILOPS_DEMO_TENANT_ID={bad_smoke}\n"
            )
            self.assertNotEqual(proc_smoke.returncode, 0)
            self.assertIn("Invalid RETAILOPS_DEMO_TENANT_ID in public.env.", proc_smoke.stderr)
            self.assertNotIn(invite_secret, proc_smoke.stderr)
            self.assertNotIn(bad_smoke, proc_smoke.stderr)

        # 4. RETAILOPS_DATA_MODE=live is rejected by start-public-web.sh
        proc_live, _ = run_validator(
            f"RETAILOPS_PUBLIC_INVITE_TOKEN={invite_secret}\n"
            "RETAILOPS_DATA_MODE=live\n"
        )
        self.assertNotEqual(proc_live.returncode, 0)
        self.assertIn("Invalid data mode.", proc_live.stderr)
        self.assertNotIn(invite_secret, proc_live.stderr)

        # 5. Conflicting RETAILOPS_DEMO_TENANT_ID and GOOGLE_AUTH_TENANT_ID rejected
        proc_conflict, _ = run_validator(
            f"RETAILOPS_PUBLIC_INVITE_TOKEN={invite_secret}\n"
            "RETAILOPS_DEMO_TENANT_ID=store-a\n"
            "GOOGLE_AUTH_TENANT_ID=store-b\n"
        )
        self.assertNotEqual(proc_conflict.returncode, 0)
        self.assertIn("Conflicting tenant selectors in public.env.", proc_conflict.stderr)
        self.assertNotIn(invite_secret, proc_conflict.stderr)

        # 6. Unsupported key rejected without leaking secret value
        leaked_api_secret = "sk_live_super_secret_do_not_print_999"
        proc_bad_key, _ = run_validator(
            f"RETAILOPS_PUBLIC_INVITE_TOKEN={invite_secret}\n"
            f"RETAILOPS_API_KEY={leaked_api_secret}\n"
        )
        self.assertNotEqual(proc_bad_key.returncode, 0)
        self.assertIn("public.env contains unsupported settings", proc_bad_key.stderr)
        self.assertNotIn(leaked_api_secret, proc_bad_key.stderr)
        self.assertNotIn(invite_secret, proc_bad_key.stderr)


if __name__ == "__main__":
    unittest.main()
