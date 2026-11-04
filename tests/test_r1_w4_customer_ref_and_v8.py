"""Phase R1 W4 isolated tests for Item 7 (salted HMAC-SHA-256 customer_ref) and Item 8 (Business v8 migration)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from retailops.business.outbox import (
    compute_customer_ref,
    resolve_customer_ref_key,
    validate_outbox_envelope,
)
from retailops.config import Settings
from retailops.identity.persistent import PersistentSessions

ROOT = Path(__file__).resolve().parents[1]


class PhaseR1W4SaltedCustomerRefTests(unittest.TestCase):
    """Item 7 (W4-D8): HMAC-SHA-256 customer_ref with secret key/file and missing-key fail-safe outbox behavior."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r1-w4-item7-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "data"
        self.pers = self.root / "persistent"

    def test_hmac_sha256_determinism_key_isolation_non_guessability_and_valid_envelope(self):
        key_a = "deploy-secret-key-alpha-0123456789abcdef"
        key_b = "deploy-secret-key-bravo-fedcba9876543210"

        ref_a1 = compute_customer_ref("shop-a", "C-001", key_a)
        ref_a2 = compute_customer_ref("shop-a", "C-001", key_a)
        ref_b1 = compute_customer_ref("shop-a", "C-001", key_b)
        ref_other_tenant = compute_customer_ref("shop-b", "C-001", key_a)
        ref_other_customer = compute_customer_ref("shop-a", "C-002", key_a)

        # Same tenant + same customer + same key -> identical custref_<64hex>
        self.assertEqual(ref_a1, ref_a2)
        self.assertRegex(ref_a1, r"^custref_[0-9a-f]{64}$")

        # Different key, tenant, or customer -> distinct ref
        self.assertNotEqual(ref_a1, ref_b1)
        self.assertNotEqual(ref_a1, ref_other_tenant)
        self.assertNotEqual(ref_a1, ref_other_customer)

        # Cannot be guessed from unsalted SHA-256 of customer_id or tenant:customer_id
        for candidate in ("C-001", "shop-a:C-001", "shop-a\x00C-001"):
            unsalted_full = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
            self.assertNotIn(unsalted_full[:16], ref_a1)

        # End-to-end envelope creation + validation + JSONL publish via secret file
        secret_file = self.root / "secrets" / "customer_ref.key"
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(f"  {key_a}\n", encoding="utf-8")

        clean_env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("RETAILOPS_CUSTOMER_REF_KEY", "RETAILOPS_CUSTOMER_REF_KEY_FILE")
        }
        clean_env["RETAILOPS_CUSTOMER_REF_KEY_FILE"] = str(secret_file)

        with patch.dict(os.environ, clean_env, clear=True):
            resolved_key, err_code, _ = resolve_customer_ref_key()
            self.assertEqual((resolved_key, err_code), (key_a, None))

            sessions = PersistentSessions(self.pers, data_mode="persistent-demo")
            store = sessions.provision_tenant("shop-a", "Shop A", seed_demo=True)
            store.create_order_action_request(
                "C-001",
                {
                    "order_id": "O-101",
                    "type": "cancel",
                    "expected_order_version": 1,
                    "reason_code": "ordered_by_mistake",
                },
                actor={"principal_id": "C-001", "role": "customer", "tenant_id": "shop-a"},
            )
            conv = store.new_conversation("C-001")
            store.record_feedback(
                "C-001",
                {
                    "conversation_id": conv["conversation_id"],
                    "feedback_type": "session_csat",
                    "rating": 5,
                    "reason_code": "fast_support",
                },
            )
            with store.connection() as db:
                rows = db.execute("SELECT payload_json FROM integration_outbox ORDER BY created_at ASC").fetchall()
            self.assertEqual(len(rows), 2)
            for row in rows:
                env = json.loads(row["payload_json"])
                validate_outbox_envelope(env)
                self.assertEqual(env["customer_ref"], ref_a1)
                self.assertNotIn("C-001", row["payload_json"])
                self.assertNotIn(key_a, row["payload_json"])
            self.assertEqual(rows[0] and json.loads(rows[0]["payload_json"])["actor"]["principal_id"], ref_a1)

            pub = store.process_outbox_batch(batch_size=10)
            self.assertEqual(pub["published"], 2)
            summary = store.outbox_status_summary()
            self.assertNotIn("error", summary)
            self.assertEqual((summary["pending"], summary["published"], summary["dead"]), (0, 2, 0))

    def test_missing_key_skips_new_outbox_writes_and_reports_clear_error_in_outbox_status(self):
        clean_env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("RETAILOPS_CUSTOMER_REF_KEY", "RETAILOPS_CUSTOMER_REF_KEY_FILE")
        }
        with patch.dict(os.environ, clean_env, clear=True):
            sessions = PersistentSessions(self.pers, data_mode="persistent-demo")
            store = sessions.provision_tenant("shop-a", "Shop A", seed_demo=True)

            # Business operations succeed, but zero new rows are written to integration_outbox
            created = store.create_order_action_request(
                "C-001",
                {
                    "order_id": "O-101",
                    "type": "cancel",
                    "expected_order_version": 1,
                    "reason_code": "change_of_mind",
                },
                actor={"principal_id": "C-001", "role": "customer", "tenant_id": "shop-a"},
            )
            self.assertEqual(created["status"], "requested")

            with store.connection() as db:
                cnt = db.execute("SELECT COUNT(*) FROM integration_outbox").fetchone()[0]
            self.assertEqual(cnt, 0)

            summary = store.outbox_status_summary()
            self.assertEqual(summary["error"], "customer_ref_key_missing")
            self.assertIn("RETAILOPS_CUSTOMER_REF_KEY", summary["error_message"])

            cli_env = {
                **clean_env,
                "RETAILOPS_STORAGE_BACKEND": "sqlite",
                "RETAILOPS_OUTPUT": str(self.root),
            }
            proc = subprocess.run(
                [sys.executable, "-m", "retailops", "database", "outbox-status"],
                cwd=str(ROOT),
                env=cli_env,
                capture_output=True,
                encoding="utf-8",
                timeout=15,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertEqual(report["result"], "OUTBOX_STATUS")
            self.assertFalse(report["customer_ref_key_configured"])
            self.assertEqual(report["error"], "customer_ref_key_missing")
            self.assertIn("RETAILOPS_CUSTOMER_REF_KEY", report["message"])
            self.assertEqual(report["totals"], {"pending": 0, "published": 0, "dead": 0})
            self.assertEqual(report["tenants"][0]["error"], "customer_ref_key_missing")

    def test_settings_secret_file_conflict_and_secret_redaction(self):
        secret_val = "super-secret-customer-ref-key-9876543210"
        secret_file = self.root / "cref.secret"
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(secret_val, encoding="utf-8")

        base_env = {
            "RETAILOPS_DATA_MODE": "persistent-demo",
            "RETAILOPS_PUBLIC_ORIGIN": "https://retailops.example.com",
            "RETAILOPS_CUSTOMER_REF_KEY_FILE": str(secret_file),
        }
        settings = Settings.from_environment("public", base_env)
        self.assertEqual(settings.customer_ref_key, secret_val)
        self.assertNotIn(secret_val, repr(settings))
        self.assertNotIn(secret_val, json.dumps(settings.summary()))

        with self.assertRaisesRegex(ValueError, "RETAILOPS_CUSTOMER_REF_KEY"):
            Settings.from_environment(
                "public",
                {**base_env, "RETAILOPS_CUSTOMER_REF_KEY": secret_val},
            )
        with self.assertRaisesRegex(ValueError, "at least 16"):
            Settings.from_environment(
                "public",
                {
                    "RETAILOPS_DATA_MODE": "persistent-demo",
                    "RETAILOPS_PUBLIC_ORIGIN": "https://retailops.example.com",
                    "RETAILOPS_CUSTOMER_REF_KEY": "too-short",
                },
            )


if __name__ == "__main__":
    unittest.main()
