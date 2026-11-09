"""Item 5 tests (W6.1b-2-D6, D8): End-to-end voucher loop (SQLite + Real PostgreSQL).

Covers:
- Approving a proposed compensation transitions status to 'requested', sets request_id = compensation_id,
  and atomically writes deterministic 'voucher.requested' to integration_outbox with approved_by_role.
- process_outbox_batch() validates and publishes 'voucher.requested' cleanly without dead/retried errors.
- CLI `python -m retailops database export-voucher-requests --tenant <id> --source-system marketplace_sim`
  prints repeatable JSONL of 'requested' items.
- Feeding exported JSONL to `python -m marketplace_sim ingest-requests` and importing `voucher.issued`
  via `import-events` (and internal HTTP route) writes 1 row to `vouchers` and transitions compensation to 'issued'.
- Re-exporting and re-importing a second time creates 0 duplicate rows.
- `voucher.issued` without a matching 'requested' compensation records `imported_events` without creating `vouchers`.
- Customer AI tools and Case Assistant tools expose issued vouchers on the customer's own order; AI states
  the exact voucher code only when present in `vouchers`.
"""
from __future__ import annotations

import hashlib
import hmac
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

from agent_protocol import PROTOCOL
from marketplace_sim.simulator import MarketplaceSimulator
from retailops.business.application import Application
from retailops.business.permissions import ROLE_PERMISSIONS
from retailops.core import ROOT
from retailops.http.routes import api_result
from retailops.identity.contracts import RequestContext
from retailops.identity.persistent import PersistentSessions
from retailops.integration.connectors import ConnectorManager
from retailops.integration.ingest import IntegrationIngestService
from retailops.integration.intake import compute_sim_hmac_signature, handle_internal_event_post
from retailops.workflow.case_assist import CaseAssistBoundTools
from retailops_tools import BoundTools
from tests._w6_1b_2_pg_base import RealPostgresW61b2Base, pg_test_enabled


def _ctx(
    role: str,
    principal_id: str,
    *,
    customer_id: str,
    tenant_id: str,
    display_name: str,
) -> RequestContext:
    return RequestContext(
        customer_id=customer_id,
        role=role,
        permissions=ROLE_PERMISSIONS[role],
        tenant_id=tenant_id,
        principal_id=principal_id,
        membership_id=f"mem_{principal_id}",
        display_name=display_name,
        authenticated_session=True,
    )


class _CapturingFakeGateway:
    def __init__(self, responses: list[dict[str, Any]]):
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, messages: list[dict[str, Any]], tools: Any = None, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"messages": json.loads(json.dumps(messages, ensure_ascii=False)), "tools": tools})
        if self._responses:
            return self._responses.pop(0)
        return {"role": "assistant", "content": "Đã kiểm tra đơn hàng.", "tool_calls": []}


class _VoucherLoopSuiteMixin:
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

    def run_item5_voucher_loop_suite(
        self,
        *,
        sessions: Any,
        tenant_id: str,
        cli_env: dict[str, str],
        cli_db_prefix: list[str],
    ) -> None:
        with tempfile.TemporaryDirectory() as sim_tmp:
            tmp_root = Path(sim_tmp)
            sim_dir = tmp_root / "sim_data"
            secrets_dir = tmp_root / "secrets"
            secrets_dir.mkdir(parents=True, exist_ok=True)

            conn_secret_raw = "w6-1b-2-item5-connector-secret-32b!!"
            conn_secret_file = secrets_dir / "retailops_connector_marketplace_sim"
            digest_file = secrets_dir / "retailops_event_digest_key"
            recipient_file = secrets_dir / "retailops_recipient_key_v1"
            conn_secret_file.write_text(conn_secret_raw + "\n", encoding="utf-8")
            digest_file.write_bytes(b"w6-1b-2-item5-digest-key-32bytes!")
            recipient_file.write_bytes(b"w6-1b-2-item5-rcp-key-32-bytes!!")

            base_env = {
                **cli_env,
                "RETAILOPS_CONNECTOR_SECRETS_DIR": str(secrets_dir),
                "RETAILOPS_EVENT_DIGEST_KEY_FILE": str(digest_file),
                "RETAILOPS_RECIPIENT_KEY_FILE": str(recipient_file),
                "RETAILOPS_CUSTOMER_REF_KEY": "item5-test-customer-ref-secret-key-32b",
            }

            # 1. Initialize marketplace_sim with two late-delivery stories (one approved by Staff, one by Manager)
            sim = MarketplaceSimulator.initialize(sim_dir, seed=20261109, merchant_id="MERCHANT-I5-001")
            s1_info = sim.insert_story("giao_tre_han_cam_ket")
            sim.advance_hours(2)
            s2_info = sim.insert_story("giao_tre_han_cam_ket")
            initial_export = tmp_root / "initial_events.jsonl"
            sim.export_events(initial_export)

            ext_oid_staff = s1_info["external_order_id"]
            ext_oid_mgr = s2_info["external_order_id"]

            with patch.dict(os.environ, base_env, clear=False):
                ConnectorManager(sessions).add_connector(
                    tenant_id,
                    source_system="marketplace_sim",
                    merchant_id="MERCHANT-I5-001",
                )

            imp_proc = self._run_cli(
                [
                    "-m",
                    "retailops",
                    "database",
                    *cli_db_prefix,
                    "import-events",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                    "--file",
                    str(initial_export),
                ],
                env_extra=base_env,
            )
            self.assertEqual(imp_proc.returncode, 0, imp_proc.stderr)

            store = sessions.business_store(tenant_id)
            with store.connection() as db:
                ord_staff = dict(
                    db.execute(
                        "SELECT * FROM orders WHERE source_system='marketplace_sim' AND external_order_id=?",
                        (ext_oid_staff,),
                    ).fetchone()
                )
                ord_mgr = dict(
                    db.execute(
                        "SELECT * FROM orders WHERE source_system='marketplace_sim' AND external_order_id=?",
                        (ext_oid_mgr,),
                    ).fetchone()
                )

            # Background scan proposes fixed 50,000 VND compensations for both late orders
            with patch.dict(os.environ, base_env, clear=False):
                scan_res = store.scan_late_delivery_compensations()
            self.assertEqual(scan_res["proposed"], 2)

            with store.connection() as db:
                comp_staff = dict(
                    db.execute(
                        "SELECT * FROM delivery_compensations WHERE order_id=?",
                        (ord_staff["id"],),
                    ).fetchone()
                )
                comp_mgr = dict(
                    db.execute(
                        "SELECT * FROM delivery_compensations WHERE order_id=?",
                        (ord_mgr["id"],),
                    ).fetchone()
                )
            self.assertEqual(comp_staff["status"], "proposed")
            self.assertEqual(comp_mgr["status"], "proposed")

            # Before voucher is issued, AI tools must show empty vouchers list
            app_staff = Application(store, {}, None, None, role="staff", tenant_id=tenant_id)
            app_staff.identity_store = sessions.control
            conv_staff = app_staff.new_conversation(ord_staff["customer_id"], {})
            conv_id_staff = conv_staff["conversation_id"]
            app_staff.focus(ord_staff["customer_id"], conv_id_staff, {"order_id": ord_staff["id"]})

            bt_pre = BoundTools(
                store,
                app_staff.catalog,
                ord_staff["customer_id"],
                store.conversation(ord_staff["customer_id"], conv_id_staff),
                {"customer_id": ord_staff["customer_id"]},
                user_text=f"Kiểm tra đơn {ext_oid_staff}",
            )
            pre_order_out = bt_pre("get_order", {"order_id": ext_oid_staff})["order"]
            self.assertEqual(pre_order_out.get("vouchers"), [])

            # Open & claim a support case on ord_staff so Staff can approve comp_staff
            store.request_human_handoff(
                ord_staff["customer_id"],
                conv_id_staff,
                reason_code="customer_requested",
                comment="Đơn giao trễ",
            )
            case_id = store.staff_desk_cases()["waiting"][0]["case_id"]
            store.claim_case(
                case_id,
                staff_name="Staff I5",
                actor={
                    "principal_id": "p_staff_i5",
                    "role": "staff",
                    "tenant_id": tenant_id,
                    "membership_id": "mem_p_staff_i5",
                },
            )

            ctx_staff = _ctx(
                "staff",
                "p_staff_i5",
                customer_id=ord_staff["customer_id"],
                tenant_id=tenant_id,
                display_name="Staff I5",
            )
            ctx_mgr = _ctx(
                "manager",
                "p_mgr_i5",
                customer_id=ord_mgr["customer_id"],
                tenant_id=tenant_id,
                display_name="Manager I5",
            )

            # 2. Approve comp_staff (as Staff) and comp_mgr (as Manager)
            with patch.dict(os.environ, base_env, clear=False):
                st1, body1 = api_result(
                    app_staff,
                    ctx_staff.customer_id,
                    "POST",
                    f"/api/staff/compensations/{comp_staff['compensation_id']}/approve",
                    {"case_id": case_id, "note": "Staff duyệt voucher giao trễ"},
                    "",
                    None,
                    context=ctx_staff,
                )
                st2, body2 = api_result(
                    app_staff,
                    ctx_mgr.customer_id,
                    "POST",
                    f"/api/staff/compensations/{comp_mgr['compensation_id']}/approve",
                    {"note": "Manager duyệt voucher giao trễ"},
                    "",
                    None,
                    context=ctx_mgr,
                )
            self.assertEqual(st1, 200)
            self.assertEqual(st2, 200)
            # Item 5 requirement: approving atomically sets status='requested' and request_id=compensation_id
            self.assertEqual(body1["compensation"]["status"], "requested")
            self.assertEqual(body1["compensation"]["request_id"], comp_staff["compensation_id"])
            self.assertEqual(body2["compensation"]["status"], "requested")
            self.assertEqual(body2["compensation"]["request_id"], comp_mgr["compensation_id"])

            with store.connection() as db:
                outbox_rows = [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM integration_outbox WHERE event_type='voucher.requested' ORDER BY created_at ASC, event_id ASC"
                    ).fetchall()
                ]
            self.assertEqual(len(outbox_rows), 2)
            payloads_by_req = {
                json.loads(r["payload_json"])["data"]["request_id"]: json.loads(r["payload_json"])
                for r in outbox_rows
            }
            self.assertEqual(
                payloads_by_req[comp_staff["compensation_id"]]["data"]["approved_by_role"],
                "staff",
            )
            self.assertEqual(
                payloads_by_req[comp_mgr["compensation_id"]]["data"]["approved_by_role"],
                "manager",
            )

            # Outbox worker must validate and publish voucher.requested cleanly (0 dead, 0 retried)
            with patch.dict(os.environ, base_env, clear=False):
                ob_res = store.process_outbox_batch()
            self.assertEqual(ob_res["dead"], 0)
            self.assertEqual(ob_res["retried"], 0)
            self.assertGreaterEqual(ob_res["published"], 2)

            # 3. CLI export-voucher-requests outputs repeatable JSONL of 'requested' compensations
            exp_proc_1 = self._run_cli(
                [
                    "-m",
                    "retailops",
                    "database",
                    *cli_db_prefix,
                    "export-voucher-requests",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                ],
                env_extra=base_env,
            )
            self.assertEqual(exp_proc_1.returncode, 0, exp_proc_1.stderr)
            exp_proc_2 = self._run_cli(
                [
                    "-m",
                    "retailops",
                    "database",
                    *cli_db_prefix,
                    "export-voucher-requests",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                ],
                env_extra=base_env,
            )
            self.assertEqual(exp_proc_2.returncode, 0, exp_proc_2.stderr)
            self.assertEqual(exp_proc_1.stdout, exp_proc_2.stdout)

            exported_lines = [ln for ln in exp_proc_1.stdout.splitlines() if ln.strip()]
            self.assertEqual(len(exported_lines), 2)

            req_file = tmp_root / "voucher_requests.jsonl"
            req_file.write_text(exp_proc_1.stdout, encoding="utf-8")

            # 4. Feed requests into marketplace_sim CLI `ingest-requests`, then export & import back!
            sim_ing_1 = self._run_cli(
                [
                    "-m",
                    "marketplace_sim",
                    "ingest-requests",
                    "--data-dir",
                    str(sim_dir),
                    "--file",
                    str(req_file),
                ],
                env_extra={},
            )
            self.assertEqual(sim_ing_1.returncode, 0, sim_ing_1.stderr)
            sim_ing_body_1 = json.loads(sim_ing_1.stdout)
            self.assertEqual(sim_ing_body_1["issued"], 2)
            self.assertEqual(sim_ing_body_1["skipped_errors"], 0)

            after_voucher_export = tmp_root / "after_voucher.jsonl"
            sim_exp_proc = self._run_cli(
                [
                    "-m",
                    "marketplace_sim",
                    "export",
                    "--data-dir",
                    str(sim_dir),
                    "--out",
                    str(after_voucher_export),
                ],
                env_extra={},
            )
            self.assertEqual(sim_exp_proc.returncode, 0, sim_exp_proc.stderr)

            # Deliver one voucher.issued via internal signed HTTP route, and import the full file via import-events
            voucher_lines = [
                ln
                for ln in after_voucher_export.read_bytes().splitlines()
                if b'"voucher.issued"' in ln
            ]
            self.assertEqual(len(voucher_lines), 2)

            ts_int = int(time.time())
            ev0_parsed = json.loads(voucher_lines[0].decode("utf-8"))
            sig_v1 = compute_sim_hmac_signature(conn_secret_raw.encode("utf-8"), ts_int, voucher_lines[0])
            with patch.dict(os.environ, base_env, clear=False):
                http_code, http_resp = handle_internal_event_post(
                    sessions,
                    tenant_id=tenant_id,
                    source_system="marketplace_sim",
                    raw_body=voucher_lines[0],
                    headers={
                        "x-sim-timestamp": str(ts_int),
                        "x-sim-event-id": str(ev0_parsed["event_id"]),
                        "x-sim-signature": sig_v1,
                    },
                )
            self.assertEqual(http_code, 200)
            self.assertEqual(http_resp["status"], "imported")

            imp_vch_1 = self._run_cli(
                [
                    "-m",
                    "retailops",
                    "database",
                    *cli_db_prefix,
                    "import-events",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                    "--file",
                    str(after_voucher_export),
                ],
                env_extra=base_env,
            )
            self.assertEqual(imp_vch_1.returncode, 0, imp_vch_1.stderr)

            with store.connection() as db:
                v_rows = [dict(r) for r in db.execute("SELECT * FROM vouchers ORDER BY voucher_id ASC").fetchall()]
                c_rows = {
                    r["compensation_id"]: dict(r)
                    for r in db.execute("SELECT * FROM delivery_compensations").fetchall()
                }
            self.assertEqual(len(v_rows), 2)
            self.assertEqual(c_rows[comp_staff["compensation_id"]]["status"], "issued")
            self.assertEqual(c_rows[comp_mgr["compensation_id"]]["status"], "issued")

            # 5. Second export + second import creates 0 duplicate rows
            exp_after_issued = self._run_cli(
                [
                    "-m",
                    "retailops",
                    "database",
                    *cli_db_prefix,
                    "export-voucher-requests",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                ],
                env_extra=base_env,
            )
            self.assertEqual(exp_after_issued.returncode, 0)
            self.assertEqual(exp_after_issued.stdout.strip(), "")

            sim_ing_2 = self._run_cli(
                [
                    "-m",
                    "marketplace_sim",
                    "ingest-requests",
                    "--data-dir",
                    str(sim_dir),
                    "--file",
                    str(req_file),
                ],
                env_extra={},
            )
            self.assertEqual(json.loads(sim_ing_2.stdout)["duplicates"], 2)

            imp_vch_2 = self._run_cli(
                [
                    "-m",
                    "retailops",
                    "database",
                    *cli_db_prefix,
                    "import-events",
                    "--tenant",
                    tenant_id,
                    "--source-system",
                    "marketplace_sim",
                    "--file",
                    str(after_voucher_export),
                ],
                env_extra=base_env,
            )
            self.assertEqual(imp_vch_2.returncode, 0)
            with store.connection() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) AS c FROM vouchers").fetchone()["c"], 2)

            # 6. voucher.issued WITHOUT a matching 'requested' compensation stores imported_events but creates NO voucher
            with store.connection() as db:
                imp_before = int(db.execute("SELECT COUNT(*) AS c FROM imported_events").fetchone()["c"])

            unmatched_events = [
                {
                    "contract": "retailops-integration-v2",
                    "event_id": "evt:voucher:unmatched-none:1",
                    "event_type": "voucher.issued",
                    "source_system": "marketplace_sim",
                    "merchant_id": "MERCHANT-I5-001",
                    "occurred_at": "2026-11-09T12:00:00+07:00",
                    "sequence": 1,
                    "data": {
                        "external_voucher_id": "SIM-V-UNMATCHED-1",
                        "code": "VCH-UNMATCHED1",
                        "voucher_type": "amount",
                        "value": 50000,
                        "valid_until": "2026-12-09T12:00:00+07:00",
                        "external_order_id": ext_oid_staff,
                        "external_customer_id": "SIM-C-0001",
                        "request_ref": "comp_does_not_exist_999",
                    },
                },
                {
                    "contract": "retailops-integration-v2",
                    "event_id": "evt:voucher:already-issued:1",
                    "event_type": "voucher.issued",
                    "source_system": "marketplace_sim",
                    "merchant_id": "MERCHANT-I5-001",
                    "occurred_at": "2026-11-09T12:05:00+07:00",
                    "sequence": 1,
                    "data": {
                        "external_voucher_id": "SIM-V-UNMATCHED-2",
                        "code": "VCH-UNMATCHED2",
                        "voucher_type": "amount",
                        "value": 50000,
                        "valid_until": "2026-12-09T12:05:00+07:00",
                        "external_order_id": ext_oid_staff,
                        "external_customer_id": "SIM-C-0001",
                        "request_ref": comp_staff["compensation_id"],
                    },
                },
            ]
            with patch.dict(os.environ, base_env, clear=False):
                svc = IntegrationIngestService(sessions)
                for u_ev in unmatched_events:
                    res_u = svc.ingest_event(u_ev, tenant_id=tenant_id)
                    self.assertTrue(res_u.success)

            with store.connection() as db:
                imp_after = int(db.execute("SELECT COUNT(*) AS c FROM imported_events").fetchone()["c"])
                v_after = int(db.execute("SELECT COUNT(*) AS c FROM vouchers").fetchone()["c"])
            self.assertEqual(imp_after, imp_before + 2)
            self.assertEqual(v_after, 2)

            # 7. Customer AI tools, Case Assistant tools, and Customer Agent expose exact issued voucher code
            vch_staff = next(v for v in v_rows if v["order_id"] == ord_staff["id"])
            expected_code = vch_staff["code"]

            with patch.dict(os.environ, base_env, clear=False):
                bt_post = BoundTools(
                    store,
                    app_staff.catalog,
                    ord_staff["customer_id"],
                    store.conversation(ord_staff["customer_id"], conv_id_staff),
                    {"customer_id": ord_staff["customer_id"]},
                    user_text=f"Đơn {ext_oid_staff} có mã voucher chưa?",
                )
                post_order = bt_post("get_order", {"order_id": ext_oid_staff})["order"]
                self.assertEqual(len(post_order["vouchers"]), 1)
                self.assertEqual(post_order["vouchers"][0]["code"], expected_code)
                self.assertEqual(post_order["vouchers"][0]["value"], 50000)

                ca_tools = CaseAssistBoundTools(
                    store,
                    app_staff.catalog,
                    case_id=case_id,
                    customer_id=ord_staff["customer_id"],
                    conversation_id=conv_id_staff,
                )
                ca_order = ca_tools("get_case_order", {"order_id": ext_oid_staff})["order"]
                self.assertEqual(ca_order["vouchers"][0]["code"], expected_code)

                # Close the human case so customer agent can answer using get_order tool
                api_result(
                    app_staff,
                    ctx_staff.customer_id,
                    "POST",
                    "/api/staff/resolve",
                    {"case_id": case_id},
                    "",
                    None,
                    context=ctx_staff,
                )

                class _VoucherFakeGateway:
                    def inspect(self) -> dict[str, Any]:
                        return {
                            "name": "fake-w61b2-item5-model",
                            "digest": "sha256:fakew61b2i5",
                            "provider": "custom_api",
                            "ollama_version": None,
                            "agent_protocol": PROTOCOL,
                        }

                    def _reply(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
                        tool_msgs = [m for m in messages if m.get("role") == "tool"]
                        if not tool_msgs:
                            msg = {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_vch_1",
                                        "function": {"name": "get_order", "arguments": {"order_id": ext_oid_staff}},
                                    }
                                ],
                            }
                        else:
                            parsed_tool = json.loads(tool_msgs[-1]["content"])
                            vouchers_in_tool = (parsed_tool.get("order") or {}).get("vouchers") or []
                            if vouchers_in_tool:
                                v = vouchers_in_tool[0]
                                msg = {
                                    "role": "assistant",
                                    "content": f"Đơn {ext_oid_staff} đã được cấp mã voucher {v['code']} trị giá {v['value']} VNĐ.",
                                    "tool_calls": [],
                                }
                            else:
                                msg = {
                                    "role": "assistant",
                                    "content": f"Đơn {ext_oid_staff} hiện chưa có mã voucher nào.",
                                    "tool_calls": [],
                                }
                        return {
                            "message": msg,
                            "done_reason": "stop",
                            "model": "fake-w61b2-item5-model",
                            "prompt_eval_count": 80,
                            "eval_count": 30,
                            "reported_cost_usd": None,
                            "reasoning": None,
                        }

                    def chat(self, messages: list[dict[str, Any]], allow_tools: bool, timeout: float) -> dict[str, Any]:
                        return self._reply(messages)

                    def chat_profile(
                        self,
                        messages: list[dict[str, Any]],
                        allow_tools: bool,
                        timeout: float,
                        *,
                        system_prompt: str,
                        tool_schemas: list[dict[str, Any]],
                    ) -> dict[str, Any]:
                        return self._reply(messages)

                app_chat = Application(store, {}, infer=_VoucherFakeGateway(), tenant_id=tenant_id)
                app_chat.identity_store = sessions.control
                chat_res = app_chat.chat(
                    ord_staff["customer_id"],
                    {
                        "conversation_id": conv_id_staff,
                        "text": f"Cho mình xin mã voucher bồi thường của đơn {ext_oid_staff}",
                        "request_id": "req_item5_vch_chat_1",
                    },
                )
                self.assertIn(expected_code, chat_res["message"])


class SQLiteVoucherLoopItem5Tests(_VoucherLoopSuiteMixin, unittest.TestCase):
    def test_sqlite_end_to_end_voucher_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = PersistentSessions(root / "persistent")
            sessions.provision_tenant("shop-vch-sqlite", "Shop Voucher SQLite", seed_demo=False)
            self.run_item5_voucher_loop_suite(
                sessions=sessions,
                tenant_id="shop-vch-sqlite",
                cli_env={"RETAILOPS_STORAGE_BACKEND": "sqlite"},
                cli_db_prefix=["--output", str(root)],
            )


@unittest.skipUnless(
    pg_test_enabled(),
    "Set RETAILOPS_TEST_DATABASE_URL to run real PostgreSQL W6.1b-2 Item 5 tests",
)
class RealPostgresVoucherLoopItem5Tests(RealPostgresW61b2Base, _VoucherLoopSuiteMixin):
    def test_postgres_end_to_end_voucher_loop(self) -> None:
        self.sessions.provision_tenant("shop-vch-pg", "Shop Voucher PG", seed_demo=False)
        self.run_item5_voucher_loop_suite(
            sessions=self.sessions,
            tenant_id="shop-vch-pg",
            cli_env={
                "RETAILOPS_STORAGE_BACKEND": "postgresql",
                "DATABASE_URL": self.dsn,
                "RETAILOPS_OUTPUT": str(self.root),
            },
            cli_db_prefix=["--output", str(self.root)],
        )


if __name__ == "__main__":
    unittest.main()
