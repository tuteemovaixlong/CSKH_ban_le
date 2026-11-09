"""Kiểm thử tích hợp W6.1b-1 giữa marketplace_sim và RetailOps (bỏ qua trong production image)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from retailops.integration.contract import (
    ALL_EVENT_TYPES,
    ContractValidationError,
    INBOUND_EVENT_TYPES,
    W6_1B_1_SUPPORTED_EVENT_TYPES,
    validate_event_v2,
)

ROOT = Path(__file__).resolve().parents[1]
HAS_MARKETPLACE_SIM = (ROOT / "marketplace_sim").is_dir()

if HAS_MARKETPLACE_SIM:
    from marketplace_sim.simulator import MarketplaceSimulator
    from marketplace_sim.stories import STORY_NAMES


@unittest.skipUnless(
    HAS_MARKETPLACE_SIM,
    "marketplace_sim không đóng gói vào production image.",
)
class MarketplaceSimContractBridgeTests(unittest.TestCase):
    """W6.1b-1 Item 1: mọi ví dụ và file export của sàn ảo đều qua bộ kiểm v2 của RetailOps."""

    def test_all_marketplace_sim_examples_pass_retailops_v2_validator(self) -> None:
        examples_dir = ROOT / "marketplace_sim" / "examples"
        seen: set[str] = set()
        for path in sorted(examples_dir.glob("*.json")):
            ev = json.loads(path.read_text(encoding="utf-8"))
            etype = ev["event_type"]
            seen.add(etype)
            with self.subTest(file=path.name, event_type=etype):
                validated = validate_event_v2(copy.deepcopy(ev))
                self.assertEqual(validated["event_type"], etype)
                if etype in INBOUND_EVENT_TYPES:
                    validate_event_v2(copy.deepcopy(ev), allow_requests=False)
                else:
                    with self.assertRaises(ContractValidationError):
                        validate_event_v2(copy.deepcopy(ev), allow_requests=False)
        self.assertEqual(seen, set(ALL_EVENT_TYPES))

    def test_full_simulator_export_passes_retailops_v2_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_dir = Path(tmp) / "sim_store"
            sim = MarketplaceSimulator.initialize(store_dir, seed=20261108)
            sim.run_days(5)
            for story_name in STORY_NAMES:
                sim.insert_story(story_name)
            export_path = Path(tmp) / "exported.jsonl"
            count = sim.export_events(export_path)
            self.assertGreater(count, 50)
            lines = export_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), count)
            seen_types: set[str] = set()
            for line in lines:
                ev = json.loads(line)
                validated = validate_event_v2(ev, allow_requests=False)
                seen_types.add(validated["event_type"])
            # 7 loại sự kiện trước khi phát voucher từ init + run + 13 story đều có mặt và vượt qua bộ kiểm
            self.assertEqual(seen_types, set(INBOUND_EVENT_TYPES) - {"voucher.issued"})

            # Phát thêm voucher.issued qua ingest_voucher_requests để kiểm đủ cả 8 loại inbound
            req_example = json.loads(
                (ROOT / "marketplace_sim" / "examples" / "voucher.requested.json").read_text(
                    encoding="utf-8"
                )
            )
            req_jsonl = Path(tmp) / "voucher_requests.jsonl"
            req_jsonl.write_text(
                json.dumps(req_example, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            req_res = sim.ingest_voucher_requests(req_jsonl)
            self.assertEqual(req_res["issued"], 1)
            export_all_path = Path(tmp) / "exported_all_8.jsonl"
            count_all = sim.export_events(export_all_path)
            self.assertEqual(count_all, count + 1)
            seen_all_types: set[str] = set()
            for line in export_all_path.read_text(encoding="utf-8").splitlines():
                ev = json.loads(line)
                validated = validate_event_v2(ev, allow_requests=False)
                seen_all_types.add(validated["event_type"])
            self.assertEqual(seen_all_types, set(INBOUND_EVENT_TYPES))

    def test_connector_mapping_file_matches_marketplace_sim_carriers_and_states(self) -> None:
        from marketplace_sim.state_machines import (
            ALLOWED_ORDER_TRANSITIONS,
            ALLOWED_PAYMENT_TRANSITIONS,
            ALLOWED_REFUND_TRANSITIONS,
        )
        from retailops.integration.connectors import load_default_status_mapping

        carriers_cfg = json.loads(
            (ROOT / "marketplace_sim" / "data" / "carriers.json").read_text(encoding="utf-8")
        )["carriers"]
        mapping = load_default_status_mapping("marketplace_sim")

        for carrier in carriers_cfg:
            code = carrier["code"]
            self.assertIn(code, mapping["shipment"])
            expected_raw_codes = set(carrier["status_codes"].values())
            self.assertEqual(set(mapping["shipment"][code].keys()), expected_raw_codes)

        order_codes = {s for targets in ALLOWED_ORDER_TRANSITIONS.values() for s in targets}
        payment_codes = {s for targets in ALLOWED_PAYMENT_TRANSITIONS.values() for s in targets}
        refund_codes = {s for targets in ALLOWED_REFUND_TRANSITIONS.values() for s in targets}
        self.assertEqual(set(mapping["order"].keys()), order_codes)
        self.assertEqual(set(mapping["payment"].keys()), payment_codes)
        self.assertEqual(set(mapping["refund"].keys()), refund_codes)

    def test_marketplace_sim_send_delivers_all_events_to_loopback_internal_route(self) -> None:
        import os
        import threading
        from unittest.mock import patch
        from wsgiref.simple_server import WSGIRequestHandler, make_server
        from retailops.http.public import PublicWeb
        from retailops.identity.persistent import PersistentSessions
        from retailops.integration.connectors import ConnectorManager

        class QuietHandler(WSGIRequestHandler):
            def log_message(self, format, *args):  # noqa: A002
                pass

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sim_dir = root / "sim_store"
            sim = MarketplaceSimulator.initialize(sim_dir, seed=20261108)
            sim.run_days(2)
            pre_status = sim.get_status()
            total_events = pre_status["total_events"]
            self.assertGreater(total_events, 15)

            secrets_dir = root / "secrets"
            secrets_dir.mkdir(parents=True, exist_ok=True)
            conn_key_file = secrets_dir / "retailops_connector_marketplace_sim"
            digest_key_file = secrets_dir / "retailops_event_digest_key"
            recipient_key_file = secrets_dir / "retailops_recipient_key_v1"
            conn_key_file.write_text("sim-loopback-hmac-secret-32-bytes-ok!!\n", encoding="utf-8")
            digest_key_file.write_text("sim-loopback-digest-key-32-bytes-ok!!\n", encoding="utf-8")
            recipient_key_file.write_text("sim-loopback-recipient-key-32-bytes-ok!\n", encoding="utf-8")

            sessions = PersistentSessions(root / "persistent")
            sessions.provision_tenant("shop-demo", "Shop Demo", seed_demo=False)
            env_vars = {
                "RETAILOPS_CONNECTOR_SECRETS_DIR": str(secrets_dir),
                "RETAILOPS_EVENT_DIGEST_KEY_FILE": str(digest_key_file),
                "RETAILOPS_RECIPIENT_KEY_FILE": str(recipient_key_file),
            }
            with patch.dict(os.environ, env_vars, clear=False):
                ConnectorManager(sessions).add_connector(
                    "shop-demo",
                    source_system="marketplace_sim",
                    merchant_id=pre_status["merchant_id"],
                )
                pub = PublicWeb("https://retailops.example.test", sessions, start_timer_worker=False)
                httpd = make_server("127.0.0.1", 0, pub, handler_class=QuietHandler)
                port = httpd.server_address[1]
                t = threading.Thread(target=httpd.serve_forever, daemon=True)
                t.start()
                try:
                    endpoint = f"http://127.0.0.1:{port}/internal/integrations/shop-demo/marketplace_sim/events"
                    send_res = sim.send_pending_events(
                        endpoint=endpoint,
                        secret_file=conn_key_file,
                    )
                    self.assertEqual(send_res, {"sent": total_events, "dead": 0})
                    post_status = sim.get_status()
                    self.assertEqual(post_status["by_delivery_status"], {"sent": total_events})
                finally:
                    httpd.shutdown()
                    httpd.server_close()

    def test_item4_full_30_days_plus_13_stories_import_counts_states_and_zero_pii(self) -> None:
        import hashlib
        import hmac
        import re
        from retailops.identity.persistent import PersistentSessions
        from retailops.integration.intake import import_events_jsonl

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sim_dir = root / "sim_store"
            sim = MarketplaceSimulator.initialize(sim_dir, seed=20261106)
            sim.run_days(30)
            story_order_ids: dict[str, str] = {}
            for story_name in STORY_NAMES:
                s_res = sim.insert_story(story_name)
                story_order_ids[story_name] = s_res["external_order_id"]

            export_file = root / "sim_30d_13stories.jsonl"
            total_exported = sim.export_events(export_file)
            raw_lines = export_file.read_bytes().splitlines()
            self.assertEqual(len(raw_lines), total_exported)

            # Parse raw JSONL to gather expected entity sets and PII values to verify redaction
            exp_orders: set[str] = set()
            exp_shipments: set[str] = set()
            exp_shipment_events = 0
            exp_payments: set[tuple[str, str]] = set()
            exp_refunds: set[tuple[str, str]] = set()
            raw_phones: set[str] = set()
            raw_addresses: set[str] = set()
            raw_line_by_event: dict[tuple[str, str], bytes] = {}

            for raw_line in raw_lines:
                ev = json.loads(raw_line.decode("utf-8"))
                raw_line_by_event[(ev["source_system"], ev["event_id"])] = raw_line
                et = ev["event_type"]
                d = ev["data"]
                if et == "order.created":
                    exp_orders.add(d["external_order_id"])
                    raw_phones.add(d["recipient"]["phone"])
                    raw_addresses.add(d["recipient"]["address_line"])
                elif et == "shipment.updated":
                    exp_shipments.add(d["external_shipment_id"])
                    exp_shipment_events += 1
                elif et == "payment.updated":
                    exp_payments.add((d["provider"], d["provider_txn_ref"]))
                elif et == "refund.updated":
                    exp_refunds.add((d["provider"], d["provider_refund_ref"]))

            from retailops.integration.recipient_crypto import RecipientKeyring

            digest_key = b"w6-1b-1-item4-e2e-digest-secret-32b!!"
            recipient_keyring = RecipientKeyring.from_raw_keys(
                {"v1": b"w6-1b-1-item4-e2e-rcp-secret-32b!"}, "v1"
            )
            sessions = PersistentSessions(root / "persistent")
            sessions.provision_tenant("shop-e2e", "Shop E2E", seed_demo=False)

            imp_res = import_events_jsonl(
                sessions,
                tenant_id="shop-e2e",
                source_system="marketplace_sim",
                jsonl_path=export_file,
                digest_key=digest_key,
                recipient_keyring=recipient_keyring,
            )
            self.assertEqual(
                (imp_res["received"], imp_res["duplicates"], imp_res["errors"]),
                (total_exported, 0, 0),
            )

            bstore = sessions.business_store("shop-e2e")
            with bstore.connection() as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"],
                    len(exp_orders),
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) AS c FROM shipments").fetchone()["c"],
                    len(exp_shipments),
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) AS c FROM shipment_events").fetchone()["c"],
                    exp_shipment_events,
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) AS c FROM payment_transactions").fetchone()["c"],
                    len(exp_payments),
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) AS c FROM refunds").fetchone()["c"],
                    len(exp_refunds),
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) AS c FROM imported_events").fetchone()["c"],
                    total_exported,
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) AS c FROM order_recipients").fetchone()["c"],
                    len(exp_orders),
                )
                for empty_tbl in ("delivery_compensations", "vouchers"):
                    self.assertEqual(
                        db.execute(f"SELECT COUNT(*) AS c FROM {empty_tbl}").fetchone()["c"],
                        0,
                        empty_tbl,
                    )

                # Verify F10: P-101, P-102, P-202 have description, material, care from marketplace_sim
                for pid in ("P-101", "P-102", "P-202"):
                    p_row = dict(
                        db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
                    )
                    self.assertTrue(bool(p_row["description"]), pid)
                    self.assertTrue(bool(p_row["material"]), pid)
                    self.assertTrue(bool(p_row["care"]), pid)

                # Verify final canonical states of all 13 named stories (W6.1a Section 2 table)
                def _story_state(name: str) -> dict:
                    ext_oid = story_order_ids[name]
                    o = dict(
                        db.execute(
                            "SELECT * FROM orders WHERE source_system='marketplace_sim' AND external_order_id=?",
                            (ext_oid,),
                        ).fetchone()
                    )
                    shp_r = db.execute(
                        "SELECT * FROM shipments WHERE order_id=?", (o["id"],)
                    ).fetchone()
                    pays = [
                        dict(r)
                        for r in db.execute(
                            "SELECT * FROM payment_transactions WHERE order_id=? ORDER BY created_at ASC",
                            (o["id"],),
                        ).fetchall()
                    ]
                    refs = [
                        dict(r)
                        for r in db.execute(
                            "SELECT * FROM refunds WHERE order_id=? ORDER BY initiated_at ASC",
                            (o["id"],),
                        ).fetchall()
                    ]
                    return {
                        "order": o,
                        "shipment": dict(shp_r) if shp_r else None,
                        "payments": pays,
                        "refunds": refs,
                    }

                s1 = _story_state("giao_dung_han_cod")
                self.assertEqual(s1["order"]["status"], "delivered")
                self.assertEqual(s1["order"]["payment_status"], "paid")
                self.assertEqual(s1["payments"][-1]["status"], "succeeded")

                s2 = _story_state("dang_trung_chuyen")
                self.assertEqual(s2["order"]["status"], "shipping")
                self.assertEqual(s2["shipment"]["status"], "in_transit")

                s3 = _story_state("cap_nhat_ao_giao_lai")
                self.assertEqual(s3["order"]["status"], "delivered")
                self.assertEqual(s3["shipment"]["status"], "delivered")
                self.assertEqual(s3["shipment"]["delivery_attempts"], 1)

                s4 = _story_state("giao_that_bai_hoan_ve")
                self.assertEqual(s4["order"]["status"], "cancelled")
                self.assertEqual(s4["shipment"]["status"], "returned")
                self.assertEqual(s4["shipment"]["delivery_attempts"], 3)

                s5 = _story_state("nghen_kho_mega_sale")
                self.assertEqual(s5["order"]["status"], "shipping")
                self.assertEqual(s5["shipment"]["status"], "in_transit")

                s6 = _story_state("hoan_tien_cham")
                self.assertEqual(s6["order"]["status"], "delivered")
                self.assertEqual(s6["refunds"][-1]["status"], "processing")

                s7 = _story_state("hoan_tien_that_bai")
                self.assertEqual(s7["order"]["status"], "delivered")
                self.assertEqual(s7["refunds"][-1]["status"], "failed")
                self.assertTrue(bool(s7["refunds"][-1]["failure_reason"]))

                s8 = _story_state("thanh_toan_that_bai_roi_thanh_cong")
                self.assertEqual(len(s8["payments"]), 2)
                self.assertEqual(
                    [p["status"] for p in s8["payments"]], ["failed", "succeeded"]
                )
                self.assertEqual(s8["order"]["payment_status"], "paid")

                s9 = _story_state("huy_truoc_khi_giao")
                self.assertEqual(s9["order"]["status"], "cancelled")
                self.assertIsNone(s9["shipment"])

                for delivered_story in ("doi_size_trong_han", "qua_han_doi_tra", "het_bao_hanh"):
                    sd = _story_state(delivered_story)
                    self.assertEqual(sd["order"]["status"], "delivered", delivered_story)
                    self.assertIsNotNone(sd["order"]["delivered_at"], delivered_story)

                s13 = _story_state("giao_tre_han_cam_ket")
                self.assertEqual(s13["order"]["status"], "delivered")
                self.assertAlmostEqual(
                    (s13["order"]["delivered_at"] - s13["order"]["promised_delivery_by"]) / 3600.0,
                    72.0,
                    places=3,
                )
                s13_elig = bstore.order_eligibility(s13["order"], db=db)
                self.assertTrue(s13_elig["is_late_vs_promised"])
                self.assertEqual(s13_elig["late_by_hours"], 72.0)
                self.assertIsNotNone(s13_elig["as_of"])

                # Also verify doi_size_trong_han, qua_han_doi_tra, het_bao_hanh computed windows at sim clock
                sim_now_ts = max(
                    r["occurred_at"]
                    for r in db.execute("SELECT occurred_at FROM shipment_events").fetchall()
                )
                s_size = bstore.order_eligibility(_story_state("doi_size_trong_han")["order"], now=sim_now_ts, db=db)
                self.assertTrue(s_size["within_size_exchange_window"])
                s_exp = bstore.order_eligibility(_story_state("qua_han_doi_tra")["order"], now=sim_now_ts, db=db)
                self.assertFalse(s_exp["within_return_window"])
                self.assertFalse(s_exp["within_size_exchange_window"])
                self.assertTrue(s_exp["within_warranty"])
                s_warr = bstore.order_eligibility(_story_state("het_bao_hanh")["order"], now=sim_now_ts, db=db)
                self.assertFalse(s_warr["within_warranty"])

                # Verify HMAC digest over raw bytes and PII redaction across entire DB
                for r in db.execute(
                    "SELECT source_system, event_id, event_type, payload_digest, redacted_fields, payload_json FROM imported_events"
                ).fetchall():
                    raw_b = raw_line_by_event[(r["source_system"], r["event_id"])]
                    expected_digest = hmac.new(digest_key, raw_b, hashlib.sha256).hexdigest()
                    self.assertEqual(r["payload_digest"], expected_digest)
                    self.assertNotEqual(r["payload_digest"], hashlib.sha256(raw_b).hexdigest())
                    if r["event_type"] == "order.created":
                        rec = json.loads(r["payload_json"])["data"]["recipient"]
                        self.assertIsNone(rec["name"])
                        self.assertIsNone(rec["phone"])
                        self.assertIsNone(rec["address_line"])
                        self.assertTrue(bool(rec["ward"]))
                        self.assertTrue(bool(rec["district"]))
                        self.assertTrue(bool(rec["province"]))

                full_phone_re = re.compile(r"\b0123\d{6}\b")
                for tbl_r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall():
                    tbl = tbl_r["name"]
                    for row in db.execute(f"SELECT * FROM {tbl}").fetchall():
                        txt = json.dumps(dict(row), ensure_ascii=False)
                        self.assertIsNone(full_phone_re.search(txt), f"Phone leak in {tbl}")
                        for addr in raw_addresses:
                            self.assertNotIn(addr, txt, f"Address leak in {tbl}")

    def test_demo_events_manifest_reproduces_exact_sha256(self) -> None:
        import hashlib
        import subprocess
        import sys

        demo_dir = ROOT / "data" / "demo_events"
        manifest = json.loads((demo_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["contract"], "retailops-integration-v2")
        self.assertEqual(set(manifest["datasets"].keys()), {"store_events", "account_template"})

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            for ds_name, spec in manifest["datasets"].items():
                checked_in_file = demo_dir / spec["file"]
                self.assertTrue(checked_in_file.is_file(), spec["file"])
                checked_in_bytes = checked_in_file.read_bytes()
                self.assertEqual(
                    hashlib.sha256(checked_in_bytes).hexdigest(),
                    spec["sha256"],
                    f"Checked-in {spec['file']} SHA-256 mismatch vs manifest.json",
                )

                sim_data_dir = tmp_root / f"sim_{ds_name}"
                repro_jsonl = tmp_root / f"repro_{spec['file']}"
                for cmd_template in spec["commands"]:
                    cmd = [
                        sys.executable
                        if tok == "python"
                        else str(sim_data_dir)
                        if tok == "<data_dir>"
                        else str(repro_jsonl)
                        if tok == "<out_jsonl>"
                        else tok
                        for tok in cmd_template
                    ]
                    proc = subprocess.run(
                        cmd,
                        cwd=str(ROOT),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )
                    self.assertEqual(proc.returncode, 0, f"{ds_name} failed: {proc.stderr}")

                repro_bytes = repro_jsonl.read_bytes()
                repro_lines = [ln for ln in repro_bytes.splitlines() if ln.strip()]
                self.assertEqual(len(repro_lines), spec["event_count"], ds_name)
                self.assertEqual(
                    hashlib.sha256(repro_bytes).hexdigest(),
                    spec["sha256"],
                    f"Reproduced {ds_name} SHA-256 mismatch vs manifest.json",
                )


if __name__ == "__main__":
    unittest.main()
