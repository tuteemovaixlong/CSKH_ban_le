"""Item 8 tests (W6.1b-2-D9): reset-marketplace-demo and seed-account-orders (SQLite + Real PostgreSQL).

Covers:
- CLI `python -m retailops database seed-account-orders --tenant <id> --all-customers [--dry-run]`:
  dry-run reports eligible vs skipped accounts without mutating; real run seeds 3 sample orders per
  existing customer membership (`role='customer'`) via `seed_demo_account_orders`, skips accounts that
  already have orders, and writes `admin_audit_log`.
- CLI `python -m retailops database reset-marketplace-demo --tenant <id> --source-system marketplace_sim [--dry-run]`:
  - Refuses (exit != 0 / 409) with zero DB or disk mutation when open cases or open handoffs are attached
    to target orders, or when `order_purge_tombstones` would block re-import; `--dry-run` lists them cleanly.
  - Neither creates nor deletes `order_purge_tombstones`.
  - In a single transaction removes all orders of `source_system` plus `order_items`, `proposals`,
    `shipments`, `shipment_events`, `payment_transactions`, `refunds`, `order_recipients`,
    `delivery_compensations`, `vouchers`, `order_action_requests`, `order_action_decisions`,
    `order_action_evidence`, plus `imported_events` and `integration_outbox` of that source, and resets
    `conversations.order_id = NULL` for conversations pointing at removed orders.
  - Deletes evidence files on disk only AFTER DB commit; if disk deletion fails, DB remains committed and
    failed files are listed in `failed_evidence_files`.
  - Preserves `customers`, `external_customer_mappings`, `products`, `product_variants`,
    `integration_connectors`, keys, `business_events`, `admin_audit_log`, `agent_turns`, and keeps
    append-only triggers on `shipment_events` and `order_action_decisions` active.
  - Running `reset-marketplace-demo` twice consecutively succeeds without error.
  - Re-importing `data/demo_events/store_events.jsonl` and running `seed-account-orders --all-customers`
    restores exact baseline per-table row counts and preserves identical sample order `external_order_id`s.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any
import unittest
from unittest.mock import patch

from PIL import Image

from retailops.core import ApiError, ROOT
from retailops.identity.persistent import PersistentSessions
from tests._w6_1b_2_pg_base import RealPostgresW61b2Base, pg_test_enabled

BUSINESS_RESET_TABLES = (
    "orders",
    "order_items",
    "proposals",
    "shipments",
    "shipment_events",
    "payment_transactions",
    "refunds",
    "order_recipients",
    "delivery_compensations",
    "vouchers",
    "order_action_requests",
    "order_action_decisions",
    "order_action_evidence",
    "imported_events",
    "integration_outbox",
)

PRESERVED_BUSINESS_TABLES = (
    "customers",
    "products",
    "product_variants",
    "integration_connectors",
)


def _sample_png_bytes() -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (24, 24), (30, 140, 210))
    img.save(buf, format="PNG")
    return buf.getvalue()


class _ResetDemoSuiteMixin:
    def _run_cli(self, argv: list[str], *, env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-X", "utf8", *argv],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def _snapshot_counts(self, sessions: Any, tenant_id: str) -> dict[str, int]:
        bstore = sessions.business_store(tenant_id)
        counts: dict[str, int] = {}
        with bstore.connection() as db:
            for tbl in (*BUSINESS_RESET_TABLES, *PRESERVED_BUSINESS_TABLES, "order_purge_tombstones", "business_events", "agent_turns"):
                row = db.execute(f"SELECT COUNT(*) AS cnt FROM {tbl}").fetchone()
                counts[tbl] = int(row["cnt"])
        with sessions.control.connection() as id_db:
            counts["external_customer_mappings"] = int(
                id_db.execute(
                    "SELECT COUNT(*) AS cnt FROM external_customer_mappings WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchone()["cnt"]
            )
            counts["admin_audit_log"] = int(
                id_db.execute(
                    "SELECT COUNT(*) AS cnt FROM admin_audit_log WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchone()["cnt"]
            )
        return counts

    def _customer_external_order_ids(self, bstore: Any, customer_id: str) -> list[str]:
        with bstore.connection() as db:
            rows = db.execute(
                "SELECT external_order_id FROM orders WHERE customer_id = ? ORDER BY external_order_id ASC",
                (customer_id,),
            ).fetchall()
        return [str(r["external_order_id"]) for r in rows]

    def run_item8_reset_demo_suite(
        self,
        *,
        sessions: Any,
        tenant_id: str,
        cli_env: dict[str, str],
        cli_db_prefix: list[str],
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            secrets_dir = tmp_root / "secrets"
            secrets_dir.mkdir(parents=True, exist_ok=True)
            conn_secret_file = secrets_dir / "retailops_connector_marketplace_sim"
            digest_file = secrets_dir / "retailops_event_digest_key"
            recipient_file = secrets_dir / "retailops_recipient_key_v1"
            conn_secret_file.write_text("w6-1b-2-item8-connector-secret-32b!!\n", encoding="utf-8")
            digest_file.write_bytes(b"w6-1b-2-item8-digest-key-32bytes!")
            recipient_file.write_bytes(b"w6-1b-2-item8-rcp-key-32-bytes!!")

            base_env = {
                **cli_env,
                "RETAILOPS_CONNECTOR_SECRETS_DIR": str(secrets_dir),
                "RETAILOPS_EVENT_DIGEST_KEY_FILE": str(digest_file),
                "RETAILOPS_RECIPIENT_KEY_FILE": str(recipient_file),
                "RETAILOPS_CUSTOMER_REF_KEY": "item8-test-customer-ref-secret-key-32b",
            }

            bstore = sessions.business_store(tenant_id)
            bstore.customer_ref_key = "item8-test-customer-ref-secret-key-32b"

            # Provision 2 customer memberships + 1 staff + 1 manager membership
            bstore.add_customer("cust_acct_1", "Khách Tài Khoản 1")
            bstore.add_customer("cust_acct_2", "Khách Tài Khoản 2")
            bstore.add_customer("staff_acct_c", "Nhân Viên 1")
            bstore.add_customer("mgr_acct_c", "Quản Lý 1")
            sessions.create_member(tenant_id, "p_cust_1", "Khách Tài Khoản 1", "cust_acct_1", "customer")
            sessions.create_member(tenant_id, "p_cust_2", "Khách Tài Khoản 2", "cust_acct_2", "customer")
            sessions.create_member(tenant_id, "p_staff_1", "Nhân Viên 1", "staff_acct_c", "staff")
            sessions.create_member(tenant_id, "p_mgr_1", "Quản Lý 1", "mgr_acct_c", "manager")

            manager_actor = {
                "principal_id": "p_mgr_1",
                "role": "manager",
                "tenant_id": tenant_id,
                "membership_id": "mem_mgr_1",
                "display_name": "Quản Lý 1",
            }

            # 1. Configure marketplace_sim connector and import store_events.jsonl
            add_conn = self._run_cli(
                [
                    "-m",
                    "retailops",
                    "connector",
                    "add",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                    "--kind",
                    "marketplace",
                    "--merchant-id",
                    "MERCHANT-SIM-001",
                    "--secret-ref",
                    "retailops_connector_marketplace_sim",
                ],
                env_extra=base_env,
            )
            self.assertEqual(add_conn.returncode, 0, msg=add_conn.stderr)

            demo_jsonl = ROOT / "data" / "demo_events" / "store_events.jsonl"
            imp_first = self._run_cli(
                [
                    *cli_db_prefix,
                    "import-events",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                    "--file",
                    str(demo_jsonl),
                    "--rebase-clock",
                    "now",
                ],
                env_extra=base_env,
            )
            self.assertEqual(imp_first.returncode, 0, msg=imp_first.stderr)

            # 2. Seed sample 3-order template for all customer memberships (dry-run -> real -> repeat)
            seed_dry = self._run_cli(
                [
                    *cli_db_prefix,
                    "seed-account-orders",
                    "--tenant",
                    tenant_id,
                    "--all-customers",
                    "--dry-run",
                ],
                env_extra=base_env,
            )
            self.assertEqual(seed_dry.returncode, 0, msg=seed_dry.stderr)
            seed_dry_out = json.loads(seed_dry.stdout)
            self.assertTrue(seed_dry_out["dry_run"])
            self.assertEqual(seed_dry_out["eligible_count"], 2)
            self.assertEqual(seed_dry_out["seeded_accounts_count"], 0)
            self.assertEqual(self._customer_external_order_ids(bstore, "cust_acct_1"), [])

            seed_real_1 = self._run_cli(
                [
                    *cli_db_prefix,
                    "seed-account-orders",
                    "--tenant",
                    tenant_id,
                    "--all-customers",
                ],
                env_extra=base_env,
            )
            self.assertEqual(seed_real_1.returncode, 0, msg=seed_real_1.stderr)
            seed_real_1_out = json.loads(seed_real_1.stdout)
            self.assertFalse(seed_real_1_out["dry_run"])
            self.assertEqual(seed_real_1_out["seeded_accounts_count"], 2)
            self.assertEqual(seed_real_1_out["orders_created_count"], 6)

            # Running seed-account-orders again skips accounts that already have orders
            seed_repeat = self._run_cli(
                [
                    *cli_db_prefix,
                    "seed-account-orders",
                    "--tenant",
                    tenant_id,
                    "--all-customers",
                ],
                env_extra=base_env,
            )
            self.assertEqual(seed_repeat.returncode, 0, msg=seed_repeat.stderr)
            seed_repeat_out = json.loads(seed_repeat.stdout)
            self.assertEqual(seed_repeat_out["seeded_accounts_count"], 0)
            self.assertEqual(seed_repeat_out["skipped_count"], 2)

            baseline_counts = self._snapshot_counts(sessions, tenant_id)
            self.assertGreater(baseline_counts["orders"], 6)
            self.assertGreater(baseline_counts["order_recipients"], 6)
            self.assertGreater(baseline_counts["payment_transactions"], 0)
            self.assertGreater(baseline_counts["shipments"], 0)
            self.assertGreater(baseline_counts["shipment_events"], 0)

            acct1_ext_oids_before = self._customer_external_order_ids(bstore, "cust_acct_1")
            acct2_ext_oids_before = self._customer_external_order_ids(bstore, "cust_acct_2")
            self.assertEqual(len(acct1_ext_oids_before), 3)
            self.assertEqual(len(acct2_ext_oids_before), 3)

            # 3. Create return request + real evidence file on disk + conversation focus + proposal + open handoff
            with bstore.connection() as db:
                deliv_ord = db.execute(
                    """SELECT id, version FROM orders
                       WHERE customer_id = 'cust_acct_1' AND status = 'delivered'
                       ORDER BY id ASC LIMIT 1"""
                ).fetchone()
                pending_ord = db.execute(
                    """SELECT id, customer_id, version FROM orders
                       WHERE source_system = 'marketplace_sim' AND status = 'pending'
                       ORDER BY id ASC LIMIT 1"""
                ).fetchone()
                ship_ord = db.execute(
                    """SELECT o.id, o.customer_id
                       FROM orders o
                       JOIN shipments s ON s.order_id = o.id
                       WHERE o.source_system = 'marketplace_sim' AND o.status = 'shipping'
                       ORDER BY o.id ASC LIMIT 1"""
                ).fetchone()
            self.assertIsNotNone(deliv_ord)
            self.assertIsNotNone(ship_ord)
            deliv_oid = str(deliv_ord["id"])

            conv = bstore.new_conversation("cust_acct_1")
            cid = conv["conversation_id"]
            bstore.customer_message("cust_acct_1", cid, "Tôi cần trả đơn hàng bị lỗi đường chỉ.")
            with bstore.connection(write=True) as db:
                db.execute(
                    "UPDATE conversations SET order_id = ? WHERE id = ?",
                    (deliv_oid, cid),
                )
                if pending_ord is not None:
                    db.execute(
                        """INSERT INTO proposals(id, customer_id, order_id, order_version, reason, expires_at, state, confirm_key)
                           VALUES ('prop_item8_demo', ?, ?, ?, 'changed_mind', ?, 'pending', 'ck_item8')""",
                        (
                            str(pending_ord["customer_id"]),
                            str(pending_ord["id"]),
                            int(pending_ord["version"]),
                            time.time() + 3600.0,
                        ),
                    )

            ret_res = bstore.create_order_action_request(
                "cust_acct_1",
                {
                    "order_id": deliv_oid,
                    "type": "return",
                    "expected_order_version": int(deliv_ord["version"]),
                    "reason_code": "defective_item",
                    "reason_text": "Sản phẩm bị bung đường may",
                    "conversation_id": cid,
                },
            )
            req_id = str(ret_res["order_action"]["request_id"])
            case_id = str(ret_res["order_action"]["case_id"])
            ev_up = bstore.upload_order_action_evidence(
                req_id,
                _sample_png_bytes(),
                customer_id="cust_acct_1",
                filename="loi_duong_chi.png",
            )
            ev_id = str(ev_up["evidence"]["evidence_id"])
            _, ev_row = bstore.get_order_action_evidence_record(req_id, ev_id)
            ev_disk_path = bstore._resolve_evidence_file_path(ev_row["storage_relpath"])
            self.assertTrue(ev_disk_path.is_file())
            # Trigger an order_action_decisions row via start_review on claim
            bstore.claim_case(case_id, staff_name="Quản Lý 1", actor=manager_actor)

            # 4. Guard A: Open case & open handoff attached to target order MUST block real reset
            dry_blocked_case = self._run_cli(
                [
                    *cli_db_prefix,
                    "reset-marketplace-demo",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                    "--dry-run",
                ],
                env_extra=base_env,
            )
            self.assertEqual(dry_blocked_case.returncode, 0, msg=dry_blocked_case.stderr)
            dry_case_json = json.loads(dry_blocked_case.stdout)
            self.assertGreaterEqual(len(dry_case_json["open_cases"]), 1)
            self.assertGreaterEqual(len(dry_case_json["open_handoffs"]), 1)

            counts_before_blocked_case = self._snapshot_counts(sessions, tenant_id)
            real_blocked_case = self._run_cli(
                [
                    *cli_db_prefix,
                    "reset-marketplace-demo",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                ],
                env_extra=base_env,
            )
            self.assertNotEqual(real_blocked_case.returncode, 0)
            self.assertEqual(self._snapshot_counts(sessions, tenant_id), counts_before_blocked_case)
            self.assertTrue(ev_disk_path.is_file())

            # Close the case & handoff (leaving conversations.order_id = deliv_oid and return request + evidence intact)
            bstore.resolve_escalation(case_id=case_id, actor=manager_actor)

            # 5. Create proposed compensation -> approve -> issue voucher so compensations, outbox, vouchers exist
            late_oid = str(ship_ord["id"])
            now_ts = time.time()
            with bstore.connection(write=True) as db:
                db.execute(
                    "UPDATE orders SET promised_delivery_by = ? WHERE id = ?",
                    (now_ts - 52 * 3600.0, late_oid),
                )
            scan_res = bstore.scan_late_delivery_compensations(now=now_ts)
            self.assertGreaterEqual(scan_res["proposed"], 1)
            with bstore.connection() as db:
                comp_row = db.execute(
                    "SELECT compensation_id FROM delivery_compensations WHERE order_id = ? LIMIT 1",
                    (late_oid,),
                ).fetchone()
            comp_id = str(comp_row["compensation_id"])
            bstore.decide_delivery_compensation(
                comp_id,
                decision="approve",
                actor=manager_actor,
                note="Duyệt voucher giao trễ trước khi reset demo",
            )

            req_jsonl = tmp_root / "voucher_requests.jsonl"
            issued_jsonl = tmp_root / "voucher_issued.jsonl"
            exp_proc = self._run_cli(
                [
                    *cli_db_prefix,
                    "export-voucher-requests",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                ],
                env_extra=base_env,
            )
            self.assertEqual(exp_proc.returncode, 0, msg=exp_proc.stderr)
            req_jsonl.write_text(exp_proc.stdout, encoding="utf-8")

            if importlib.util.find_spec("marketplace_sim") is not None:
                sim_dir = tmp_root / "sim_state"
                sim_all_jsonl = tmp_root / "sim_all_events.jsonl"
                init_sim = self._run_cli(
                    ["-m", "marketplace_sim", "init", "--data-dir", str(sim_dir), "--seed", "20261109"],
                    env_extra=base_env,
                )
                self.assertEqual(init_sim.returncode, 0, msg=init_sim.stderr)
                sim_ing = self._run_cli(
                    [
                        "-m",
                        "marketplace_sim",
                        "ingest-requests",
                        "--data-dir",
                        str(sim_dir),
                        "--file",
                        str(req_jsonl),
                    ],
                    env_extra=base_env,
                )
                self.assertEqual(sim_ing.returncode, 0, msg=sim_ing.stderr)
                sim_exp = self._run_cli(
                    [
                        "-m",
                        "marketplace_sim",
                        "export",
                        "--data-dir",
                        str(sim_dir),
                        "--out",
                        str(sim_all_jsonl),
                    ],
                    env_extra=base_env,
                )
                self.assertEqual(sim_exp.returncode, 0, msg=sim_exp.stderr)
                v_lines = [
                    ln
                    for ln in sim_all_jsonl.read_text(encoding="utf-8").splitlines()
                    if '"voucher.issued"' in ln
                ]
                self.assertEqual(len(v_lines), 1)
                issued_jsonl.write_text("\n".join(v_lines) + "\n", encoding="utf-8")
            else:
                req_env = json.loads(exp_proc.stdout.strip().splitlines()[0])
                issued_ev = {
                    "contract": "retailops-integration-v2",
                    "event_id": "evt:voucher:SIM-V-I8-01:1",
                    "event_type": "voucher.issued",
                    "source_system": "marketplace_sim",
                    "merchant_id": "MERCHANT-SIM-001",
                    "occurred_at": req_env["occurred_at"],
                    "sequence": 1,
                    "data": {
                        "external_voucher_id": "SIM-V-I8-01",
                        "external_customer_id": req_env["data"]["external_customer_id"],
                        "external_order_id": req_env["data"]["external_order_id"],
                        "request_ref": comp_id,
                        "code": "ROPS50KI8",
                        "voucher_type": "amount",
                        "value": 50000,
                        "valid_until": "2026-12-31T23:59:59+07:00",
                    },
                }
                issued_jsonl.write_text(json.dumps(issued_ev, ensure_ascii=False) + "\n", encoding="utf-8")

            imp_vouch = self._run_cli(
                [
                    *cli_db_prefix,
                    "import-events",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                    "--file",
                    str(issued_jsonl),
                ],
                env_extra=base_env,
            )
            self.assertEqual(imp_vouch.returncode, 0, msg=imp_vouch.stderr)

            # 6. Guard B: Tombstone in order_purge_tombstones blocks reset and is NOT deleted
            with bstore.connection(write=True) as db:
                db.execute(
                    """INSERT INTO order_purge_tombstones(
                           order_id, tenant_id, customer_id, product_id, status, amount,
                           snapshot_name, variant, reason, operator_id, purged_at,
                           pre_counts_json, post_counts_json
                       ) VALUES (?, ?, 'cust_acct_1', 'P-101', 'cancelled', 299000,
                                 'Áo thun Essential', 'Trắng · Size L', 'test_tombstone',
                                 'op_1', ?, '{}', '{}')""",
                    ("ord_tombstone_guard_1", tenant_id, now_ts),
                )

            dry_tomb = self._run_cli(
                [
                    *cli_db_prefix,
                    "reset-marketplace-demo",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                    "--dry-run",
                ],
                env_extra=base_env,
            )
            self.assertEqual(dry_tomb.returncode, 0, msg=dry_tomb.stderr)
            dry_tomb_json = json.loads(dry_tomb.stdout)
            self.assertEqual(len(dry_tomb_json["blocking_tombstones"]), 1)

            counts_with_tomb = self._snapshot_counts(sessions, tenant_id)
            real_tomb = self._run_cli(
                [
                    *cli_db_prefix,
                    "reset-marketplace-demo",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                ],
                env_extra=base_env,
            )
            self.assertNotEqual(real_tomb.returncode, 0)
            self.assertEqual(self._snapshot_counts(sessions, tenant_id), counts_with_tomb)
            self.assertTrue(ev_disk_path.is_file())

            # Remove temporary test tombstone to run the clean reset flow
            with bstore.connection(write=True) as db:
                db.execute("DELETE FROM order_purge_tombstones WHERE order_id = 'ord_tombstone_guard_1'")

            # 7. Clean dry-run reports exact counts & mutates nothing
            pre_reset_counts = self._snapshot_counts(sessions, tenant_id)
            self.assertGreaterEqual(pre_reset_counts["vouchers"], 1)
            self.assertGreaterEqual(pre_reset_counts["delivery_compensations"], 1)
            self.assertGreaterEqual(pre_reset_counts["order_action_requests"], 1)
            self.assertGreaterEqual(pre_reset_counts["order_action_decisions"], 1)
            self.assertGreaterEqual(pre_reset_counts["order_action_evidence"], 1)
            self.assertGreaterEqual(pre_reset_counts["integration_outbox"], 1)

            dry_clean = self._run_cli(
                [
                    *cli_db_prefix,
                    "reset-marketplace-demo",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                    "--dry-run",
                ],
                env_extra=base_env,
            )
            self.assertEqual(dry_clean.returncode, 0, msg=dry_clean.stderr)
            dry_clean_json = json.loads(dry_clean.stdout)
            self.assertTrue(dry_clean_json["dry_run"])
            self.assertEqual(dry_clean_json["blocking_tombstones"], [])
            self.assertEqual(dry_clean_json["open_cases"], [])
            self.assertEqual(dry_clean_json["open_handoffs"], [])
            self.assertEqual(dry_clean_json["evidence_files_count"], 1)
            self.assertEqual(dry_clean_json["table_counts"]["orders"], pre_reset_counts["orders"])
            self.assertEqual(self._snapshot_counts(sessions, tenant_id), pre_reset_counts)
            self.assertTrue(ev_disk_path.is_file())

            # 8. Real reset-marketplace-demo removes target rows & disk file, preserves customers/catalog/audit/turns
            real_reset_1 = self._run_cli(
                [
                    *cli_db_prefix,
                    "reset-marketplace-demo",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                ],
                env_extra=base_env,
            )
            self.assertEqual(real_reset_1.returncode, 0, msg=real_reset_1.stderr)
            reset_1_json = json.loads(real_reset_1.stdout)
            self.assertFalse(reset_1_json["dry_run"])
            self.assertEqual(reset_1_json["failed_evidence_files"], [])
            self.assertFalse(ev_disk_path.exists())

            post_reset_counts = self._snapshot_counts(sessions, tenant_id)
            for tbl in BUSINESS_RESET_TABLES:
                self.assertEqual(post_reset_counts[tbl], 0, f"Expected {tbl} == 0 after reset")
            self.assertEqual(post_reset_counts["order_purge_tombstones"], 0)
            for tbl in PRESERVED_BUSINESS_TABLES:
                self.assertEqual(post_reset_counts[tbl], pre_reset_counts[tbl], f"Expected {tbl} preserved")
            self.assertEqual(
                post_reset_counts["external_customer_mappings"],
                pre_reset_counts["external_customer_mappings"],
            )
            self.assertEqual(post_reset_counts["business_events"], pre_reset_counts["business_events"])
            self.assertEqual(post_reset_counts["agent_turns"], pre_reset_counts["agent_turns"])
            self.assertGreater(post_reset_counts["admin_audit_log"], pre_reset_counts["admin_audit_log"])

            # Verify conversations.order_id does not point to any missing order
            with bstore.connection() as db:
                dangling_conv = db.execute(
                    """SELECT id, order_id FROM conversations
                       WHERE order_id IS NOT NULL
                         AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.id = conversations.order_id)"""
                ).fetchall()
                self.assertEqual(list(dangling_conv), [])
                conv_after = db.execute("SELECT order_id FROM conversations WHERE id = ?", (cid,)).fetchone()
                self.assertIsNone(conv_after["order_id"])

            # Verify append-only triggers on order_action_decisions & shipment_events remain enforced!
            if getattr(bstore, "_supports_skip_locked", False):
                with bstore.connection() as db:
                    trgs = {
                        str(r["tgname"]): str(r["tgenabled"])
                        for r in db.execute(
                            """SELECT t.tgname, t.tgenabled::text AS tgenabled
                               FROM pg_trigger t
                               JOIN pg_class c ON c.oid = t.tgrelid
                               JOIN pg_namespace n ON n.oid = c.relnamespace
                               WHERE n.nspname = current_schema()
                                 AND t.tgname IN ('trg_order_action_decisions_immutable', 'trg_shipment_events_immutable')"""
                        ).fetchall()
                    }
                self.assertEqual(trgs.get("trg_order_action_decisions_immutable"), "O")
                self.assertEqual(trgs.get("trg_shipment_events_immutable"), "O")
            else:
                with bstore.connection() as db:
                    trgs_sq = {
                        str(r["name"])
                        for r in db.execute(
                            """SELECT name FROM sqlite_master
                               WHERE type = 'trigger'
                                 AND name IN ('order_action_decisions_no_delete', 'shipment_events_no_delete')"""
                        ).fetchall()
                    }
                self.assertEqual(trgs_sq, {"order_action_decisions_no_delete", "shipment_events_no_delete"})

            # 9. Consecutive second reset succeeds with 0 rows deleted
            real_reset_2 = self._run_cli(
                [
                    *cli_db_prefix,
                    "reset-marketplace-demo",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                ],
                env_extra=base_env,
            )
            self.assertEqual(real_reset_2.returncode, 0, msg=real_reset_2.stderr)
            reset_2_json = json.loads(real_reset_2.stdout)
            self.assertEqual(reset_2_json["deleted_counts"]["orders"], 0)

            # 10. Re-import store_events.jsonl + seed-account-orders --all-customers => exact baseline counts & order IDs!
            imp_second = self._run_cli(
                [
                    *cli_db_prefix,
                    "import-events",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                    "--file",
                    str(demo_jsonl),
                    "--rebase-clock",
                    "now",
                ],
                env_extra=base_env,
            )
            self.assertEqual(imp_second.returncode, 0, msg=imp_second.stderr)

            seed_real_2 = self._run_cli(
                [
                    *cli_db_prefix,
                    "seed-account-orders",
                    "--tenant",
                    tenant_id,
                    "--all-customers",
                ],
                env_extra=base_env,
            )
            self.assertEqual(seed_real_2.returncode, 0, msg=seed_real_2.stderr)

            reimported_counts = self._snapshot_counts(sessions, tenant_id)
            for tbl in (*BUSINESS_RESET_TABLES, *PRESERVED_BUSINESS_TABLES, "external_customer_mappings"):
                self.assertEqual(
                    reimported_counts[tbl],
                    baseline_counts[tbl],
                    f"Table {tbl} count mismatch after reset + re-import: {reimported_counts[tbl]} != {baseline_counts[tbl]}",
                )
            self.assertEqual(self._customer_external_order_ids(bstore, "cust_acct_1"), acct1_ext_oids_before)
            self.assertEqual(self._customer_external_order_ids(bstore, "cust_acct_2"), acct2_ext_oids_before)

            # 11. Disk deletion error after commit does NOT rollback DB; reports failed_evidence_files
            with bstore.connection() as db:
                re_deliv = db.execute(
                    "SELECT id, version FROM orders WHERE customer_id = 'cust_acct_2' AND status = 'delivered' LIMIT 1"
                ).fetchone()
            conv2 = bstore.new_conversation("cust_acct_2")
            cid2 = conv2["conversation_id"]
            bstore.customer_message("cust_acct_2", cid2, "Yêu cầu trả đơn test lỗi xóa file")
            ret2 = bstore.create_order_action_request(
                "cust_acct_2",
                {
                    "order_id": str(re_deliv["id"]),
                    "type": "return",
                    "expected_order_version": int(re_deliv["version"]),
                    "reason_code": "defective_item",
                    "reason_text": "Kiểm tra lỗi xóa file",
                    "conversation_id": cid2,
                },
            )
            req2_id = str(ret2["order_action"]["request_id"])
            case2_id = str(ret2["order_action"]["case_id"])
            ev2 = bstore.upload_order_action_evidence(
                req2_id,
                _sample_png_bytes(),
                customer_id="cust_acct_2",
                filename="fail_unlink.png",
            )
            _, ev2_row = bstore.get_order_action_evidence_record(req2_id, str(ev2["evidence"]["evidence_id"]))
            bstore.resolve_escalation(case_id=case2_id, actor=manager_actor)

            with patch.object(Path, "unlink", side_effect=PermissionError("simulated_disk_busy")):
                res_disk_err = bstore.reset_marketplace_demo("marketplace_sim", dry_run=False)
            self.assertEqual(len(res_disk_err["failed_evidence_files"]), 1)
            self.assertEqual(
                res_disk_err["failed_evidence_files"][0]["storage_relpath"],
                ev2_row["storage_relpath"],
            )
            with bstore.connection() as db:
                self.assertEqual(
                    int(db.execute("SELECT COUNT(*) AS cnt FROM orders WHERE source_system = 'marketplace_sim'").fetchone()["cnt"]),
                    0,
                )


class Item8ResetDemoSqliteTests(unittest.TestCase, _ResetDemoSuiteMixin):
    def test_sqlite_reset_marketplace_demo_and_seed_account_orders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            pers_dir = out_dir / "persistent"
            sessions = PersistentSessions(pers_dir, api_daily_limit=10)
            sessions.provision_tenant("shop-demo", "Shop Demo", seed_demo=False)
            self.run_item8_reset_demo_suite(
                sessions=sessions,
                tenant_id="shop-demo",
                cli_env={"RETAILOPS_STORAGE_BACKEND": "sqlite", "RETAILOPS_OUTPUT": str(out_dir)},
                cli_db_prefix=["-m", "retailops", "database", "--output", str(out_dir)],
            )


@unittest.skipUnless(
    pg_test_enabled(),
    "Set RETAILOPS_TEST_DATABASE_URL to run real PostgreSQL W6.1b-2 Item 8 tests",
)
class RealPostgresResetDemoItem8Tests(RealPostgresW61b2Base, _ResetDemoSuiteMixin):
    def test_postgres_reset_marketplace_demo_and_seed_account_orders(self) -> None:
        dsn = os.environ["RETAILOPS_TEST_DATABASE_URL"]
        self.run_item8_reset_demo_suite(
            sessions=self.sessions,
            tenant_id="shop-demo",
            cli_env={
                "RETAILOPS_STORAGE_BACKEND": "postgresql",
                "RETAILOPS_DATABASE_URL": dsn,
                "RETAILOPS_OUTPUT": str(self.root / "data"),
            },
            cli_db_prefix=["-m", "retailops", "database", "--output", str(self.root / "data")],
        )


if __name__ == "__main__":
    unittest.main()
