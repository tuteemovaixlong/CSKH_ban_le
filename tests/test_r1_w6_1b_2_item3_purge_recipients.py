"""Tests for Phase R1 W6.1b-2 Item 3: manual `database purge-expired-recipients` CLI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from retailops.identity.persistent import PersistentSessions
from retailops.integration.ingest import IntegrationIngestService
from retailops.integration.recipient_crypto import RecipientKeyring


def _order_ev(eid: str, ext_oid: str) -> dict:
    return {
        "contract": "retailops-integration-v2",
        "event_id": eid,
        "event_type": "order.created",
        "source_system": "marketplace_sim",
        "merchant_id": "MERCHANT-SIM-001",
        "occurred_at": "2026-10-01T10:00:00+07:00",
        "sequence": 1,
        "data": {
            "external_order_id": ext_oid,
            "external_customer_id": f"CUST-{ext_oid}",
            "ordered_at": "2026-10-01T10:00:00+07:00",
            "promised_delivery_by": "2026-10-03T10:00:00+07:00",
            "payment_method": "cod",
            "shipping_fee": 20000,
            "total": 220000,
            "currency": "VND",
            "recipient": {
                "name": f"Người nhận {ext_oid}",
                "phone": "0907654321",
                "address_line": f"Số 10 Đường {ext_oid}",
                "ward": "Phường Đa Kao",
                "district": "Quận 1",
                "province": "TP. Hồ Chí Minh",
            },
            "items": [
                {
                    "external_product_id": "P-101",
                    "sku": "SKU-I3-101",
                    "title": "Áo thun cổ tròn",
                    "variant_name": "Đen / L",
                    "quantity": 1,
                    "unit_price": 200000,
                }
            ],
        },
    }


class PurgeExpiredRecipientsItem3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="r1-w61b2-item3-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out_dir = self.root / "out"
        self.sessions = PersistentSessions(self.out_dir / "persistent")
        self.store = self.sessions.provision_tenant("shop-demo", "Shop Demo", seed_demo=False)
        self.svc = IntegrationIngestService(
            self.sessions,
            digest_key=b"w61b2-item3-digest-secret-32byte!",
            recipient_keyring=RecipientKeyring.from_raw_keys(
                {"v1": b"w61b2-item3-recipient-key-32byte!"}, "v1"
            ),
        )

        # Create 3 orders: 1 expired, 1 future retention_until, 1 undelivered (NULL retention_until)
        r_exp = self.svc.ingest_event(
            json.dumps(_order_ev("evt:i3:1", "SIM-I3-EXP"), ensure_ascii=False).encode("utf-8"),
            tenant_id="shop-demo",
        )
        r_fut = self.svc.ingest_event(
            json.dumps(_order_ev("evt:i3:2", "SIM-I3-FUT"), ensure_ascii=False).encode("utf-8"),
            tenant_id="shop-demo",
        )
        r_null = self.svc.ingest_event(
            json.dumps(_order_ev("evt:i3:3", "SIM-I3-NULL"), ensure_ascii=False).encode("utf-8"),
            tenant_id="shop-demo",
        )
        self.oid_expired = r_exp.order_id
        self.oid_future = r_fut.order_id
        self.oid_undelivered = r_null.order_id

        now = time.time()
        with self.store.connection(write=True) as db:
            db.execute(
                "UPDATE order_recipients SET retention_until = ? WHERE order_id = ?",
                (now - 3600.0, self.oid_expired),
            )
            db.execute(
                "UPDATE order_recipients SET retention_until = ? WHERE order_id = ?",
                (now + 86400.0 * 30, self.oid_future),
            )

    def _run_cli(self, *extra_args: str) -> dict:
        env = {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "RETAILOPS_STORAGE_BACKEND": "sqlite",
            "RETAILOPS_OUTPUT": str(self.out_dir),
        }
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "retailops",
                "database",
                "--output",
                str(self.out_dir),
                "purge-expired-recipients",
                "--tenant",
                "shop-demo",
                *extra_args,
            ],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_dry_run_execute_idempotent_rerun_and_never_automatic(self) -> None:
        # 1. Background worker must NOT purge expired recipients automatically
        self.sessions.run_case_timers_once()
        with self.store.connection() as db:
            row_before = dict(
                db.execute("SELECT * FROM order_recipients WHERE order_id=?", (self.oid_expired,)).fetchone()
            )
        self.assertIsNotNone(row_before["name_enc"])
        self.assertIsNotNone(row_before["phone_lookup_hmac"])

        # 2. --dry-run mutates nothing, writes 0 audit rows, and reports exact count (1)
        dry = self._run_cli("--dry-run")
        self.assertEqual(dry["result"], "PURGE_EXPIRED_RECIPIENTS_DRY_RUN")
        self.assertTrue(dry["dry_run"])
        self.assertEqual(dry["would_purge_count"], 1)
        self.assertEqual(dry["purged_count"], 0)
        self.assertEqual(dry["order_ids"], [self.oid_expired])

        with self.store.connection() as db:
            still_enc = dict(
                db.execute("SELECT * FROM order_recipients WHERE order_id=?", (self.oid_expired,)).fetchone()
            )
        self.assertIsNotNone(still_enc["name_enc"])
        self.assertIsNotNone(still_enc["phone_enc"])
        self.assertIsNotNone(still_enc["address_line_enc"])
        self.assertIsNotNone(still_enc["phone_lookup_hmac"])

        with self.sessions.control.connection() as id_db:
            dry_audits = id_db.execute(
                "SELECT COUNT(*) AS c FROM admin_audit_log WHERE action='database.purge_expired_recipients'"
            ).fetchone()["c"]
        self.assertEqual(dry_audits, 0)

        # 3. Real execution purges ONLY the expired row, keeps area + phone_masked, writes audit
        res1 = self._run_cli()
        self.assertEqual(res1["result"], "PURGE_EXPIRED_RECIPIENTS_COMPLETED")
        self.assertFalse(res1["dry_run"])
        self.assertEqual(res1["purged_count"], 1)
        self.assertEqual(res1["order_ids"], [self.oid_expired])

        with self.store.connection() as db:
            exp_after = dict(
                db.execute("SELECT * FROM order_recipients WHERE order_id=?", (self.oid_expired,)).fetchone()
            )
            fut_after = dict(
                db.execute("SELECT * FROM order_recipients WHERE order_id=?", (self.oid_future,)).fetchone()
            )
            null_after = dict(
                db.execute("SELECT * FROM order_recipients WHERE order_id=?", (self.oid_undelivered,)).fetchone()
            )

        for col in ("name_enc", "phone_enc", "address_line_enc", "phone_lookup_hmac"):
            self.assertIsNone(exp_after[col], col)
            self.assertIsNotNone(fut_after[col], col)
            self.assertIsNotNone(null_after[col], col)

        self.assertEqual(exp_after["phone_masked"], "0907.xxx.321")
        self.assertEqual(exp_after["ward"], "Phường Đa Kao")
        self.assertEqual(exp_after["district"], "Quận 1")
        self.assertEqual(exp_after["province"], "TP. Hồ Chí Minh")

        # 4. Second run is idempotent: no error, reports 0
        res2 = self._run_cli()
        self.assertEqual(res2["purged_count"], 0)
        self.assertEqual(res2["would_purge_count"], 0)

        with self.sessions.control.connection() as id_db:
            audits = [
                json.loads(r["after_json"])
                for r in id_db.execute(
                    "SELECT after_json FROM admin_audit_log WHERE action='database.purge_expired_recipients' ORDER BY id ASC"
                ).fetchall()
            ]
        self.assertEqual(len(audits), 2)
        self.assertEqual(audits[0]["purged_count"], 1)
        self.assertEqual(audits[1]["purged_count"], 0)


if __name__ == "__main__":
    unittest.main()
