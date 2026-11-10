"""Item 7 tests (W6.1b-2-D6, D10): Proactive system notices at 5 milestones.

Covers:
- Customer with no conversation: all 5 milestones (`out_for_delivery`, `delivery_failed`,
  `delivered`, `late_delivery`, `voucher_issued`) run cleanly without error.
- Customer with multiple conversations: notices post to the latest conversation using
  deterministic `sys-notice-<shipment_id>-<milestone>` `request_id`.
- Re-importing the same event, multiple delivery failure attempts on the same shipment,
  both `shipment.updated` and `order.status_changed` `delivered`, or running background
  scans repeatedly (even after opening a newer conversation) creates zero duplicate notices:
  strictly 1 notice per `(shipment_id, milestone)`.
- Zero recipient data (plaintext or masked) appears anywhere in proactive notice turns.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from retailops.core import ROOT
from retailops.identity.persistent import PersistentSessions
from retailops.integration.connectors import ConnectorManager
from retailops.integration.ingest import IntegrationIngestService
from retailops.integration.intake import compute_sim_hmac_signature, handle_internal_event_post

VN_TZ = timezone(timedelta(hours=7))
BASE_DT = datetime(2026, 11, 5, 8, 0, 0, tzinfo=VN_TZ)


def _iso_at(hours: float) -> str:
    return (BASE_DT + timedelta(hours=hours)).isoformat(timespec="seconds")


def _epoch_at(hours: float) -> float:
    return (BASE_DT + timedelta(hours=hours)).timestamp()


class ProactiveNoticesItem7Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="r1-w61b2-item7-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.secrets_dir = self.root / "secrets"
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        (self.secrets_dir / "retailops_connector_marketplace_sim").write_bytes(b"k" * 32)
        self.digest_file = self.root / "digest_key"
        self.digest_file.write_bytes(b"d" * 32)
        self.recipient_file = self.root / "recipient_key"
        self.recipient_file.write_bytes(b"r" * 32)

        self.env_patcher = patch.dict(
            os.environ,
            {
                "RETAILOPS_CONNECTOR_SECRETS_DIR": str(self.secrets_dir),
                "RETAILOPS_EVENT_DIGEST_KEY_FILE": str(self.digest_file),
                "RETAILOPS_RECIPIENT_KEY_FILE": str(self.recipient_file),
            },
            clear=False,
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

        self.sessions = PersistentSessions(self.root / "tenants")
        self.store = self.sessions.provision_tenant("shop-i7", "Shop Item 7", seed_demo=False)
        self.mgr = ConnectorManager(self.sessions)
        self.mgr.add_connector(
            "shop-i7",
            source_system="marketplace_sim",
            kind="marketplace",
            merchant_id="MERCHANT-SIM-001",
            secret_ref="retailops_connector_marketplace_sim",
        )
        self.store.seed_catalog()
        self.svc = IntegrationIngestService(self.sessions, digest_key=b"d" * 32)
        self.manager_actor = {
            "principal_id": "p_mgr_i7",
            "role": "manager",
            "tenant_id": "shop-i7",
        }

        self.rec_name = "Phạm Ngọc Bảo Châu"
        self.rec_phone = "0938777666"
        self.rec_phone_masked = "0938.xxx.666"
        self.rec_addr = "88B Lý Tự Trọng, Căn hộ 1204"
        self.rec_ward = "Phường Bến Thành"

    def _ingest(self, ev: dict):
        raw = json.dumps(ev, ensure_ascii=False).encode("utf-8")
        return self.svc.ingest_event(raw, tenant_id="shop-i7", received_via="import")

    def _create_shipping_order(self, ext_oid: str, ext_cid: str, ext_shp_id: str) -> tuple[str, str, str]:
        self._ingest(
            {
                "contract": "retailops-integration-v2",
                "event_id": f"ev-c-{ext_oid}",
                "event_type": "customer.upserted",
                "occurred_at": _iso_at(0),
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 1,
                "data": {"external_customer_id": ext_cid, "display_name": "Khách Chủ Động"},
            }
        )
        res_ord = self._ingest(
            {
                "contract": "retailops-integration-v2",
                "event_id": f"ev-o-{ext_oid}",
                "event_type": "order.created",
                "occurred_at": _iso_at(1),
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 1,
                "data": {
                    "external_order_id": ext_oid,
                    "external_customer_id": ext_cid,
                    "ordered_at": _iso_at(1),
                    "promised_delivery_by": _iso_at(24),
                    "currency": "VND",
                    "payment_method": "cod",
                    "items": [
                        {
                            "sku": "SKU-P101-TRANG-M",
                            "external_product_id": "P-101",
                            "title": "Áo sơ mi lụa công sở",
                            "variant_name": "Trắng · Size M",
                            "quantity": 1,
                            "unit_price": 239000,
                        }
                    ],
                    "shipping_fee": 20000,
                    "total": 259000,
                    "recipient": {
                        "name": self.rec_name,
                        "phone": self.rec_phone,
                        "address_line": self.rec_addr,
                        "ward": self.rec_ward,
                        "district": "Quận 1",
                        "province": "TP. Hồ Chí Minh",
                    },
                },
            }
        )
        self._ingest(
            {
                "contract": "retailops-integration-v2",
                "event_id": f"ev-os-ship-{ext_oid}",
                "event_type": "order.status_changed",
                "occurred_at": _iso_at(2),
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 2,
                "data": {"external_order_id": ext_oid, "status": "shipping", "reason": None},
            }
        )
        self._ingest(
            {
                "contract": "retailops-integration-v2",
                "event_id": f"ev-shp-init-{ext_shp_id}",
                "event_type": "shipment.updated",
                "occurred_at": _iso_at(3),
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 1,
                "data": {
                    "external_order_id": ext_oid,
                    "external_shipment_id": ext_shp_id,
                    "carrier": "GHN",
                    "tracking_code": f"TRK-{ext_shp_id}",
                    "carrier_status_raw": "picked",
                    "hub_name": "Kho Tân Bình",
                    "district": "Quận Tân Bình",
                    "province": "TP. Hồ Chí Minh",
                    "description": "Đã lấy hàng",
                    "fail_reason": None,
                    "shipper_name": None,
                    "shipper_phone_masked": None,
                    "estimated_delivery_at": _iso_at(24),
                    "delivery_attempts": 0,
                },
            }
        )
        with self.store.connection() as db:
            shp_id = str(
                db.execute(
                    "SELECT shipment_id FROM shipments WHERE external_shipment_id=?",
                    (ext_shp_id,),
                ).fetchone()["shipment_id"]
            )
        return str(res_ord.order_id), str(res_ord.customer_id), shp_id

    def test_customer_without_conversation_triggers_zero_errors_and_zero_turns(self) -> None:
        oid, _cid, _shp_id = self._create_shipping_order("SIM-O-NOCONV", "SIM-C-NOCONV", "SHP-NOCONV")
        # 1. out_for_delivery
        self._ingest(
            {
                "contract": "retailops-integration-v2",
                "event_id": "ev-nc-ofd",
                "event_type": "shipment.updated",
                "occurred_at": _iso_at(10),
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 2,
                "data": {
                    "external_order_id": "SIM-O-NOCONV",
                    "external_shipment_id": "SHP-NOCONV",
                    "carrier": "GHN",
                    "tracking_code": "TRK-SHP-NOCONV",
                    "carrier_status_raw": "delivering",
                    "hub_name": "Bưu cục Quận 1",
                    "district": "Quận 1",
                    "province": "TP. Hồ Chí Minh",
                    "description": "Đang giao",
                    "fail_reason": None,
                    "shipper_name": "Anh Hùng",
                    "shipper_phone_masked": "0909.xxx.111",
                    "estimated_delivery_at": _iso_at(24),
                    "delivery_attempts": 1,
                },
            }
        )
        # 2. delivery_failed
        self._ingest(
            {
                "contract": "retailops-integration-v2",
                "event_id": "ev-nc-fail",
                "event_type": "shipment.updated",
                "occurred_at": _iso_at(12),
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 3,
                "data": {
                    "external_order_id": "SIM-O-NOCONV",
                    "external_shipment_id": "SHP-NOCONV",
                    "carrier": "GHN",
                    "tracking_code": "TRK-SHP-NOCONV",
                    "carrier_status_raw": "delivery_fail",
                    "hub_name": "Bưu cục Quận 1",
                    "district": "Quận 1",
                    "province": "TP. Hồ Chí Minh",
                    "description": "Giao chưa thành công",
                    "fail_reason": "Khách hẹn chiều giao",
                    "shipper_name": "Anh Hùng",
                    "shipper_phone_masked": "0909.xxx.111",
                    "estimated_delivery_at": _iso_at(36),
                    "delivery_attempts": 1,
                },
            }
        )
        # 3. late_delivery scan (>48h past promised_delivery_by at hour 24 -> hour 75)
        scan_res = self.store.scan_late_delivery_compensations(now=_epoch_at(75))
        self.assertEqual(scan_res["proposed"], 1)
        self.assertEqual(scan_res["notices_emitted"], 0)

        # 4. approve compensation + voucher.issued
        with self.store.connection() as db:
            comp_id = str(
                db.execute("SELECT compensation_id FROM delivery_compensations WHERE order_id=?", (oid,)).fetchone()[
                    "compensation_id"
                ]
            )
        self.store.decide_delivery_compensation(comp_id, decision="approve", actor=self.manager_actor)
        self._ingest(
            {
                "contract": "retailops-integration-v2",
                "event_id": "ev-nc-vch",
                "event_type": "voucher.issued",
                "occurred_at": _iso_at(76),
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 1,
                "data": {
                    "external_voucher_id": "VCH-NOCONV-1",
                    "code": "RO-NOCONV50K",
                    "voucher_type": "amount",
                    "value": 50000,
                    "valid_until": _iso_at(720),
                    "external_order_id": "SIM-O-NOCONV",
                    "external_customer_id": "SIM-C-NOCONV",
                    "request_ref": comp_id,
                },
            }
        )
        # 5. delivered
        self._ingest(
            {
                "contract": "retailops-integration-v2",
                "event_id": "ev-nc-deliv",
                "event_type": "shipment.updated",
                "occurred_at": _iso_at(78),
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 4,
                "data": {
                    "external_order_id": "SIM-O-NOCONV",
                    "external_shipment_id": "SHP-NOCONV",
                    "carrier": "GHN",
                    "tracking_code": "TRK-SHP-NOCONV",
                    "carrier_status_raw": "delivered",
                    "hub_name": "Bưu cục Quận 1",
                    "district": "Quận 1",
                    "province": "TP. Hồ Chí Minh",
                    "description": "Đã giao",
                    "fail_reason": None,
                    "shipper_name": "Anh Hùng",
                    "shipper_phone_masked": "0909.xxx.111",
                    "estimated_delivery_at": _iso_at(78),
                    "delivery_attempts": 2,
                },
            }
        )

        with self.store.connection() as db:
            turns_cnt = int(db.execute("SELECT COUNT(*) AS c FROM agent_turns").fetchone()["c"])
        self.assertEqual(turns_cnt, 0)

    def test_five_milestones_post_to_latest_conversation_once_per_shipment_with_zero_pii(self) -> None:
        oid, cid, shp_id = self._create_shipping_order("SIM-O-CONV5", "SIM-C-CONV5", "SHP-CONV5")

        # Open an older conversation and then a newer conversation -> notices must go to conv_latest
        with patch.object(self.store, "_now", return_value=_epoch_at(4)):
            conv_old = self.store.new_conversation(cid)
        with patch.object(self.store, "_now", return_value=_epoch_at(5)):
            conv_latest = self.store.new_conversation(cid)

        # Milestone 1: out_for_delivery (+ replay)
        ev_ofd = {
            "contract": "retailops-integration-v2",
            "event_id": "ev-c5-ofd",
            "event_type": "shipment.updated",
            "occurred_at": _iso_at(10),
            "source_system": "marketplace_sim",
            "merchant_id": "MERCHANT-SIM-001",
            "sequence": 2,
            "data": {
                "external_order_id": "SIM-O-CONV5",
                "external_shipment_id": "SHP-CONV5",
                "carrier": "GHN",
                "tracking_code": "TRK-SHP-CONV5",
                "carrier_status_raw": "delivering",
                "hub_name": "Bưu cục Quận 1",
                "district": "Quận 1",
                "province": "TP. Hồ Chí Minh",
                "description": "Đang giao",
                "fail_reason": None,
                "shipper_name": "Anh Hùng",
                "shipper_phone_masked": "0909.xxx.111",
                "estimated_delivery_at": _iso_at(24),
                "delivery_attempts": 1,
            },
        }
        self._ingest(ev_ofd)
        self._ingest(ev_ofd)  # replay

        # Milestone 2: delivery_failed (attempt 1 + attempt 2 -> still strictly 1 delivery_failed notice!)
        for seq_no, att, ev_id, hr in (
            (3, 1, "ev-c5-fail-1", 12),
            (4, 2, "ev-c5-fail-2", 20),
        ):
            self._ingest(
                {
                    "contract": "retailops-integration-v2",
                    "event_id": ev_id,
                    "event_type": "shipment.updated",
                    "occurred_at": _iso_at(hr),
                    "source_system": "marketplace_sim",
                    "merchant_id": "MERCHANT-SIM-001",
                    "sequence": seq_no,
                    "data": {
                        "external_order_id": "SIM-O-CONV5",
                        "external_shipment_id": "SHP-CONV5",
                        "carrier": "GHN",
                        "tracking_code": "TRK-SHP-CONV5",
                        "carrier_status_raw": "delivery_fail",
                        "hub_name": "Bưu cục Quận 1",
                        "district": "Quận 1",
                        "province": "TP. Hồ Chí Minh",
                        "description": f"Giao thất bại lần {att}",
                        "fail_reason": f"Không nghe máy ({self.rec_name} - {self.rec_phone})",
                        "shipper_name": "Anh Hùng",
                        "shipper_phone_masked": "0909.xxx.111",
                        "estimated_delivery_at": _iso_at(36),
                        "delivery_attempts": att,
                    },
                }
            )

        # Milestone 3: late_delivery via background scan (run 3 times, including after opening a 3rd conversation!)
        s_first = self.store.scan_late_delivery_compensations(now=_epoch_at(75))
        self.assertEqual(s_first["proposed"], 1)
        self.assertEqual(s_first["notices_emitted"], 1)
        s_second = self.store.scan_late_delivery_compensations(now=_epoch_at(76))
        self.assertEqual(s_second["notices_emitted"], 0)

        with patch.object(self.store, "_now", return_value=_epoch_at(77)):
            conv_third = self.store.new_conversation(cid)

        # Re-scanning after customer opened conv_third must NOT emit a 2nd late_delivery notice for SHP-CONV5!
        s_third = self.store.scan_late_delivery_compensations(now=_epoch_at(77.5))
        self.assertEqual(s_third["notices_emitted"], 0)

        # Milestone 4: voucher_issued (now conv_third is latest -> posts to conv_third once; replay produces no dup)
        with self.store.connection() as db:
            comp_id = str(
                db.execute("SELECT compensation_id FROM delivery_compensations WHERE order_id=?", (oid,)).fetchone()[
                    "compensation_id"
                ]
            )
        self.store.decide_delivery_compensation(comp_id, decision="approve", actor=self.manager_actor)
        ev_vch = {
            "contract": "retailops-integration-v2",
            "event_id": "ev-c5-vch",
            "event_type": "voucher.issued",
            "occurred_at": _iso_at(78),
            "source_system": "marketplace_sim",
            "merchant_id": "MERCHANT-SIM-001",
            "sequence": 1,
            "data": {
                "external_voucher_id": "VCH-CONV5-1",
                "code": "RO-LATE50K-C5",
                "voucher_type": "amount",
                "value": 50000,
                "valid_until": _iso_at(720),
                "external_order_id": "SIM-O-CONV5",
                "external_customer_id": "SIM-C-CONV5",
                "request_ref": comp_id,
            },
        }
        self._ingest(ev_vch)
        self._ingest(ev_vch)  # replay

        # Milestone 5: delivered (both shipment.updated delivered AND order.status_changed delivered -> strictly 1 notice)
        ev_shp_deliv = {
            "contract": "retailops-integration-v2",
            "event_id": "ev-c5-shp-deliv",
            "event_type": "shipment.updated",
            "occurred_at": _iso_at(80),
            "source_system": "marketplace_sim",
            "merchant_id": "MERCHANT-SIM-001",
            "sequence": 5,
            "data": {
                "external_order_id": "SIM-O-CONV5",
                "external_shipment_id": "SHP-CONV5",
                "carrier": "GHN",
                "tracking_code": "TRK-SHP-CONV5",
                "carrier_status_raw": "delivered",
                "hub_name": "Bưu cục Quận 1",
                "district": "Quận 1",
                "province": "TP. Hồ Chí Minh",
                "description": "Giao thành công",
                "fail_reason": None,
                "shipper_name": "Anh Hùng",
                "shipper_phone_masked": "0909.xxx.111",
                "estimated_delivery_at": _iso_at(80),
                "delivery_attempts": 3,
            },
        }
        self._ingest(ev_shp_deliv)
        self._ingest(ev_shp_deliv)
        self._ingest(
            {
                "contract": "retailops-integration-v2",
                "event_id": "ev-c5-ord-deliv",
                "event_type": "order.status_changed",
                "occurred_at": _iso_at(80.1),
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "sequence": 3,
                "data": {"external_order_id": "SIM-O-CONV5", "status": "delivered", "reason": None},
            }
        )

        with self.store.connection() as db:
            notice_rows = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM agent_turns WHERE request_id LIKE 'sys-notice-%' ORDER BY id ASC"
                ).fetchall()
            ]
            old_cnt = int(
                db.execute(
                    "SELECT COUNT(*) AS c FROM agent_turns WHERE conversation_id=?",
                    (conv_old["conversation_id"],),
                ).fetchone()["c"]
            )

        self.assertEqual(old_cnt, 0)
        self.assertEqual(len(notice_rows), 5)

        expected_request_ids = [
            f"sys-notice-{shp_id}-out_for_delivery",
            f"sys-notice-{shp_id}-delivery_failed",
            f"sys-notice-{shp_id}-late_delivery",
            f"sys-notice-{shp_id}-voucher_issued",
            f"sys-notice-{shp_id}-delivered",
        ]
        self.assertEqual([r["request_id"] for r in notice_rows], expected_request_ids)

        # First 3 notices went to conv_latest; last 2 went to conv_third after it became latest
        self.assertEqual(
            [r["conversation_id"] for r in notice_rows],
            [
                conv_latest["conversation_id"],
                conv_latest["conversation_id"],
                conv_latest["conversation_id"],
                conv_third["conversation_id"],
                conv_third["conversation_id"],
            ],
        )

        # Voucher code appears in voucher_issued notice; zero recipient PII anywhere
        vch_notice = json.loads(notice_rows[3]["result"])
        self.assertIn("RO-LATE50K-C5", vch_notice["message"])
        self.assertEqual(vch_notice["author"], "system_case_notice")

        full_dump = json.dumps(notice_rows, ensure_ascii=False)
        for pii_fragment in (
            self.rec_name,
            self.rec_phone,
            self.rec_phone_masked,
            self.rec_addr,
            self.rec_ward,
        ):
            self.assertNotIn(pii_fragment, full_dump)

    def _run_cli(self, args: list[str], env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.update(env_extra)
        return subprocess.run(
            [sys.executable, *args],
            cwd=str(ROOT),
            env=env,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    def test_batch_reimport_and_seed_with_no_notices_suppresses_only_shipment_notices(self) -> None:
        out_dir = self.root / "cli_out"
        pers_dir = out_dir / "persistent"
        cli_sessions = PersistentSessions(pers_dir, api_daily_limit=10)
        bstore = cli_sessions.provision_tenant("shop-no-notices", "Shop No Notices", seed_demo=False)
        bstore.add_customer("cust_acct_n1", "Khách Tài Khoản N1")
        cli_sessions.create_member(
            "shop-no-notices", "p_cust_n1", "Khách Tài Khoản N1", "cust_acct_n1", "customer"
        )
        ConnectorManager(cli_sessions).add_connector(
            "shop-no-notices",
            source_system="marketplace_sim",
            kind="marketplace",
            merchant_id="MERCHANT-SIM-001",
            secret_ref="retailops_connector_marketplace_sim",
        )
        cli_env = {
            "RETAILOPS_STORAGE_BACKEND": "sqlite",
            "RETAILOPS_OUTPUT": str(out_dir),
            "RETAILOPS_CONNECTOR_SECRETS_DIR": str(self.secrets_dir),
            "RETAILOPS_EVENT_DIGEST_KEY_FILE": str(self.digest_file),
            "RETAILOPS_RECIPIENT_KEY_FILE": str(self.recipient_file),
        }
        db_prefix = ["-m", "retailops", "database", "--output", str(out_dir)]
        demo_jsonl = ROOT / "data" / "demo_events" / "store_events.jsonl"

        # 1. Initial import + seed so SIM-C-0001 and cust_acct_n1 exist and have conversations
        imp_init = self._run_cli(
            [
                *db_prefix,
                "import-events",
                "--tenant",
                "shop-no-notices",
                "--source-system",
                "marketplace_sim",
                "--file",
                str(demo_jsonl),
                "--rebase-clock",
                "now",
            ],
            cli_env,
        )
        self.assertEqual(imp_init.returncode, 0, msg=imp_init.stderr)
        seed_init = self._run_cli(
            [
                *db_prefix,
                "seed-account-orders",
                "--tenant",
                "shop-no-notices",
                "--all-customers",
            ],
            cli_env,
        )
        self.assertEqual(seed_init.returncode, 0, msg=seed_init.stderr)

        mapped_sim_c1 = cli_sessions.control.get_external_customer_mapping(
            "shop-no-notices", "marketplace_sim", "SIM-C-0001"
        )
        self.assertIsNotNone(mapped_sim_c1)
        bstore.new_conversation(str(mapped_sim_c1))
        bstore.new_conversation("cust_acct_n1")

        # 2. Reset demo data (conversations & agent_turns preserved)
        rst_1 = self._run_cli(
            [
                *db_prefix,
                "reset-marketplace-demo",
                "--tenant",
                "shop-no-notices",
                "--source-system",
                "marketplace_sim",
            ],
            cli_env,
        )
        self.assertEqual(rst_1.returncode, 0, msg=rst_1.stderr)

        def _sys_notice_ids() -> list[str]:
            with bstore.connection() as db:
                return [
                    str(r["request_id"])
                    for r in db.execute(
                        "SELECT request_id FROM agent_turns WHERE request_id LIKE 'sys-notice-%' ORDER BY id ASC"
                    ).fetchall()
                ]

        before_no_notices = _sys_notice_ids()

        # 3. Re-import store_events.jsonl AND seed-account-orders WITH --no-notices -> ZERO new sys-notice-* turns!
        imp_quiet = self._run_cli(
            [
                *db_prefix,
                "import-events",
                "--tenant",
                "shop-no-notices",
                "--source-system",
                "marketplace_sim",
                "--file",
                str(demo_jsonl),
                "--rebase-clock",
                "now",
                "--no-notices",
            ],
            cli_env,
        )
        self.assertEqual(imp_quiet.returncode, 0, msg=imp_quiet.stderr)

        seed_quiet = self._run_cli(
            [
                *db_prefix,
                "seed-account-orders",
                "--tenant",
                "shop-no-notices",
                "--all-customers",
                "--no-notices",
            ],
            cli_env,
        )
        self.assertEqual(seed_quiet.returncode, 0, msg=seed_quiet.stderr)
        self.assertEqual(_sys_notice_ids(), before_no_notices)

        # 4. Late-delivery background scan AND voucher.issued import (even with --no-notices) AND internal HTTP route STILL emit notices!
        with bstore.connection() as db:
            acct_ship_ord = db.execute(
                """SELECT id, external_order_id FROM orders
                   WHERE customer_id = 'cust_acct_n1' AND status = 'shipping'
                   ORDER BY id ASC LIMIT 1"""
            ).fetchone()
            acct_shp = db.execute(
                "SELECT shipment_id, external_shipment_id FROM shipments WHERE order_id = ? LIMIT 1",
                (str(acct_ship_ord["id"]),),
            ).fetchone()
        self.assertIsNotNone(acct_ship_ord)
        self.assertIsNotNone(acct_shp)
        late_oid = str(acct_ship_ord["id"])
        late_ext_oid = str(acct_ship_ord["external_order_id"])
        late_shp_id = str(acct_shp["shipment_id"])
        late_ext_shp_id = str(acct_shp["external_shipment_id"])

        now_ts = time.time()
        with bstore.connection(write=True) as db:
            db.execute(
                "UPDATE orders SET promised_delivery_by = ? WHERE id = ?",
                (now_ts - 52 * 3600.0, late_oid),
            )
        scan_out = bstore.scan_late_delivery_compensations(now=now_ts)
        self.assertGreaterEqual(scan_out["proposed"], 1)
        self.assertIn(f"sys-notice-{late_shp_id}-late_delivery", _sys_notice_ids())

        with bstore.connection() as db:
            comp_id = str(
                db.execute(
                    "SELECT compensation_id FROM delivery_compensations WHERE order_id = ? LIMIT 1",
                    (late_oid,),
                ).fetchone()["compensation_id"]
            )
        bstore.decide_delivery_compensation(
            comp_id,
            decision="approve",
            actor={"principal_id": "p_mgr_n1", "role": "manager", "tenant_id": "shop-no-notices"},
        )
        with cli_sessions.control.connection() as id_db:
            ext_cust_n1 = str(
                id_db.execute(
                    "SELECT external_customer_id FROM external_customer_mappings WHERE tenant_id='shop-no-notices' AND customer_id='cust_acct_n1'"
                ).fetchone()["external_customer_id"]
            )
        vch_file = self.root / "vch_issued_major1.jsonl"
        vch_ev = {
            "contract": "retailops-integration-v2",
            "event_id": "evt:voucher:SIM-V-MAJ1:1",
            "event_type": "voucher.issued",
            "source_system": "marketplace_sim",
            "merchant_id": "MERCHANT-SIM-001",
            "occurred_at": _iso_at(100),
            "sequence": 1,
            "data": {
                "external_voucher_id": "SIM-V-MAJ1",
                "code": "RO-MAJ1-50K",
                "voucher_type": "amount",
                "value": 50000,
                "valid_until": _iso_at(720),
                "external_order_id": late_ext_oid,
                "external_customer_id": ext_cust_n1,
                "request_ref": comp_id,
            },
        }
        vch_file.write_text(json.dumps(vch_ev, ensure_ascii=False) + "\n", encoding="utf-8")
        imp_vch = self._run_cli(
            [
                *db_prefix,
                "import-events",
                "--tenant",
                "shop-no-notices",
                "--source-system",
                "marketplace_sim",
                "--file",
                str(vch_file),
                "--rebase-clock",
                "now",
                "--no-notices",
            ],
            cli_env,
        )
        self.assertEqual(imp_vch.returncode, 0, msg=imp_vch.stderr)
        self.assertIn(f"sys-notice-{late_shp_id}-voucher_issued", _sys_notice_ids())

        # Internal HTTP route /internal/integrations/... still emits shipment notices
        http_ev_raw = json.dumps(
            {
                "contract": "retailops-integration-v2",
                "event_id": "evt:shp:MAJ1-HTTP-OFD",
                "event_type": "shipment.updated",
                "source_system": "marketplace_sim",
                "merchant_id": "MERCHANT-SIM-001",
                "occurred_at": datetime.fromtimestamp(now_ts, tz=VN_TZ).isoformat(timespec="seconds"),
                "sequence": 99,
                "data": {
                    "external_order_id": late_ext_oid,
                    "external_shipment_id": late_ext_shp_id,
                    "carrier": "GHN",
                    "tracking_code": "TRK-MAJ1-HTTP",
                    "carrier_status_raw": "delivering",
                    "hub_name": "Bưu cục Quận 3",
                    "district": "Quận 3",
                    "province": "TP. Hồ Chí Minh",
                    "description": "Đang giao hàng trực tuyến",
                    "fail_reason": None,
                    "shipper_name": "Anh Minh",
                    "shipper_phone_masked": "0909.xxx.222",
                    "estimated_delivery_at": None,
                    "delivery_attempts": 1,
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")
        ts_int = int(now_ts)
        sig = compute_sim_hmac_signature(b"k" * 32, ts_int, http_ev_raw)
        http_code, _ = handle_internal_event_post(
            cli_sessions,
            tenant_id="shop-no-notices",
            source_system="marketplace_sim",
            raw_body=http_ev_raw,
            headers={
                "x-sim-timestamp": str(ts_int),
                "x-sim-event-id": "evt:shp:MAJ1-HTTP-OFD",
                "x-sim-signature": sig,
            },
            now_fn=lambda: now_ts,
        )
        self.assertEqual(http_code, 200)
        self.assertIn(f"sys-notice-{late_shp_id}-out_for_delivery", _sys_notice_ids())

        # 5. Without --no-notices (default), re-import & seed-account-orders DO emit shipment notices as before!
        rst_2 = self._run_cli(
            [
                *db_prefix,
                "reset-marketplace-demo",
                "--tenant",
                "shop-no-notices",
                "--source-system",
                "marketplace_sim",
            ],
            cli_env,
        )
        self.assertEqual(rst_2.returncode, 0, msg=rst_2.stderr)
        before_default = _sys_notice_ids()

        imp_default = self._run_cli(
            [
                *db_prefix,
                "import-events",
                "--tenant",
                "shop-no-notices",
                "--source-system",
                "marketplace_sim",
                "--file",
                str(demo_jsonl),
                "--rebase-clock",
                "now",
            ],
            cli_env,
        )
        self.assertEqual(imp_default.returncode, 0, msg=imp_default.stderr)
        after_imp_default = _sys_notice_ids()
        self.assertGreater(len(after_imp_default), len(before_default))

        seed_default = self._run_cli(
            [
                *db_prefix,
                "seed-account-orders",
                "--tenant",
                "shop-no-notices",
                "--all-customers",
            ],
            cli_env,
        )
        self.assertEqual(seed_default.returncode, 0, msg=seed_default.stderr)
        after_seed_default = _sys_notice_ids()
        self.assertGreater(len(after_seed_default), len(after_imp_default))


if __name__ == "__main__":
    unittest.main()
