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

        # Login to Tenant 1
        sec1 = self.sessions.login_google(email=email, name="Cross User", sub=sub, issuer=issuer, email_verified=True, tenant_id=t1)
        mem1 = self.sessions.control.resolve(self.sessions.cookie_id(f"__Host-retailops_account={sec1}"))
        pid1, cid1 = mem1["principal_id"], mem1["customer_id"]

        # Login to Tenant 2
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


if __name__ == "__main__":
    unittest.main()
