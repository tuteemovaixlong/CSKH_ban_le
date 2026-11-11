"""W6.2-D4 reset relevance and fail-closed JSONL, SQLite and real PostgreSQL."""
import json
from pathlib import Path
import tempfile
import unittest

from legacy_seed_fixture import seed_legacy_unit_fixture
from retailops.business.store import BusinessStore
from retailops.core import ApiError
from tests._w6_1b_2_pg_base import RealPostgresW61b2Base, pg_test_enabled


class ResetRelevanceMixin:
    def prepare(self):
        seed_legacy_unit_fixture(self.store)
        with self.store.connection(write=True) as db:
            db.execute("UPDATE orders SET source_system='marketplace_sim', external_order_id='SIM-W62-001' WHERE id='O-101'")

    def tombstone(self, order_id):
        with self.store.connection(write=True) as db:
            db.execute("""INSERT INTO order_purge_tombstones(order_id,tenant_id,customer_id,product_id,status,amount,snapshot_name,variant,reason,operator_id,purged_at,pre_counts_json,post_counts_json)
                VALUES (?, 'shop-demo', 'C-001', 'P-101', 'cancelled', 299000, 'Synthetic', 'M', 'test', 'test', 1, '{}', '{}')""", (order_id,))

    def snapshot(self):
        with self.store.connection() as db:
            return {table: [dict(r) for r in db.execute(f"SELECT * FROM {table}").fetchall()] for table in ("orders", "order_purge_tombstones", "business_events", "conversations")}

    def test_related_internal_and_external_ids_block_without_mutation(self):
        self.prepare()
        for order_id in ("O-101", "SIM-W62-001"):
            with self.subTest(order_id=order_id):
                self.tombstone(order_id)
                before = self.snapshot()
                report = self.store.reset_marketplace_demo("marketplace_sim", dry_run=True)
                self.assertIn(order_id, [r["order_id"] for r in report["blocking_tombstones"]])
                with self.assertRaises(ApiError) as error:
                    self.store.reset_marketplace_demo("marketplace_sim")
                self.assertEqual(error.exception.status, 409)
                self.assertEqual(self.snapshot(), before)

    def test_other_source_tombstone_is_informational_and_preserved(self):
        self.prepare()
        self.tombstone("O-202")  # belongs to retailops_seed, not marketplace_sim
        report = self.store.reset_marketplace_demo("marketplace_sim", dry_run=True)
        self.assertEqual(report["blocking_tombstones"], [])
        self.assertEqual([r["order_id"] for r in report["unrelated_tombstones"]], ["O-202"])
        self.store.reset_marketplace_demo("marketplace_sim")
        after = self.snapshot()
        self.assertNotIn("O-101", [r["id"] for r in after["orders"]])
        self.assertIn("O-202", [r["id"] for r in after["orders"]])
        self.assertEqual([r["order_id"] for r in after["order_purge_tombstones"]], ["O-202"])

    def test_reimport_file_tombstone_blocks_without_mutation(self):
        self.prepare()
        self.tombstone("SIM-W62-REIMPORT")
        path = self.root / "reimport.jsonl"
        path.write_text(json.dumps({"contract": "retailops-integration-v2", "event_id": "evt:w62:reimport:1", "event_type": "order.status_changed", "source_system": "marketplace_sim", "merchant_id": "MERCHANT-SIM-001", "occurred_at": "2026-11-11T12:00:00+07:00", "sequence": 1, "data": {"external_order_id": "SIM-W62-REIMPORT", "status": "cancelled", "reason": "synthetic"}}) + "\n", encoding="utf-8")
        before = self.snapshot()
        report = self.store.reset_marketplace_demo("marketplace_sim", dry_run=True, reimport_file=path)
        self.assertEqual([r["order_id"] for r in report["blocking_tombstones"]], ["SIM-W62-REIMPORT"])
        with self.assertRaises(ApiError) as error:
            self.store.reset_marketplace_demo("marketplace_sim", reimport_file=path)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.snapshot(), before)

    def test_bad_reimport_files_refuse_before_any_change(self):
        self.prepare()
        path = self.root / "bad.jsonl"
        before = self.snapshot()
        for payload in (None, b'{broken\n', b'[]\n', b'{"data": []}\n', b'{}\n', b'\xff\n'):
            with self.subTest(payload=payload):
                if payload is not None:
                    path.write_bytes(payload)
                for dry in (False, True):
                    with self.assertRaises(ApiError) as error:
                        self.store.reset_marketplace_demo("marketplace_sim", dry_run=dry, reimport_file=path)
                    self.assertEqual(error.exception.status, 400)
                    self.assertEqual(self.snapshot(), before)


class ResetSqliteW62Tests(ResetRelevanceMixin, unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = BusinessStore(self.root / "business.sqlite3")


@unittest.skipUnless(pg_test_enabled(), "Real PostgreSQL W6.2 reset tests run in PR CI")
class ResetPostgresW62Tests(ResetRelevanceMixin, RealPostgresW61b2Base):
    pass
