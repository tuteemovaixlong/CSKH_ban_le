"""W6.1b-2.1 (F21): the background late-delivery scan must not reopen write transactions for handled orders."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from retailops.identity.persistent import PersistentSessions
from tests.test_r1_w6_1b_2_item4_compensations import _seed_late_test_orders


class LateScanWriteBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="r1-w61b21-scan-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        rec_key = root / "retailops_recipient_key_v1"
        rec_key.write_bytes(b"R" * 32)
        dig_key = root / "retailops_event_digest_key"
        dig_key.write_bytes(b"D" * 32)
        env_patch = patch.dict(
            os.environ,
            {
                "RETAILOPS_RECIPIENT_KEY_FILE": str(rec_key),
                "RETAILOPS_EVENT_DIGEST_KEY_FILE": str(dig_key),
                "RETAILOPS_CUSTOMER_REF_KEY": "test-customer-ref-secret-key-012345",
            },
        )
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.sessions = PersistentSessions(root / "persistent")
        self.store = self.sessions.provision_tenant("shop-demo", "Shop Demo", seed_demo=False)

    def _count_write_transactions(self, fn):
        store = self.store
        original = store.connection
        counter = {"write": 0}

        def counting(*args, **kwargs):
            if kwargs.get("write") or (args and args[0]):
                counter["write"] += 1
            return original(*args, **kwargs)

        with patch.object(store, "connection", side_effect=counting):
            result = fn()
        return counter["write"], result

    def test_second_scan_opens_no_write_transaction(self) -> None:
        scan_now = 1_762_700_000.0
        _seed_late_test_orders(self.sessions, self.store, tenant_id="shop-demo", base_ts=scan_now)

        first_writes, first = self._count_write_transactions(
            lambda: self.store.scan_late_delivery_compensations(now=scan_now)
        )
        self.assertGreaterEqual(first["proposed"], 1)
        self.assertGreaterEqual(first_writes, 1)

        second_writes, second = self._count_write_transactions(
            lambda: self.store.scan_late_delivery_compensations(now=scan_now)
        )
        self.assertEqual(second["proposed"], 0)
        self.assertEqual(second_writes, 0, "handled late orders must not reopen write transactions")

    def test_order_crossing_threshold_later_still_gets_one_proposal(self) -> None:
        scan_now = 1_762_700_000.0
        by_ext = _seed_late_test_orders(self.sessions, self.store, tenant_id="shop-demo", base_ts=scan_now)
        self.store.scan_late_delivery_compensations(now=scan_now)
        self.store.scan_late_delivery_compensations(now=scan_now)
        later = scan_now + 2 * 3600.0
        out = self.store.scan_late_delivery_compensations(now=later)
        self.assertGreaterEqual(out["proposed"], 1)
        with self.store.connection() as db:
            rows = db.execute(
                "SELECT COUNT(*) AS n FROM delivery_compensations WHERE order_id = ?",
                (by_ext["SIM-I4-47H"]["id"],),
            ).fetchone()
        self.assertEqual(int(rows["n"] if "n" in rows.keys() else rows[0]), 1)
        again_writes, again = self._count_write_transactions(
            lambda: self.store.scan_late_delivery_compensations(now=later)
        )
        self.assertEqual(again["proposed"], 0)
        self.assertEqual(again_writes, 0)


if __name__ == "__main__":
    unittest.main()
