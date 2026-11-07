"""Kiểm thử cô lập cho 13 kịch bản có tên, gửi sự kiện HTTP HMAC và cách ly hai chiều (W6.1a mục 7, 9, 10)."""

from __future__ import annotations

import ast
from datetime import timedelta
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
HAS_MARKETPLACE_SIM = (ROOT / "marketplace_sim").is_dir()

if HAS_MARKETPLACE_SIM:
    from marketplace_sim.contract import parse_iso_vn, validate_event
    from marketplace_sim.sender import (
        EndpointNotAllowedError,
        RETRY_DELAYS_SECONDS,
        validate_endpoint_url,
    )
    from marketplace_sim.simulator import MarketplaceSimulator
    from marketplace_sim.stories import STORY_NAMES


def _collect_story_summary(events: list[dict], order_id: str) -> dict:
    order_created = None
    order_statuses: list[tuple[str, str]] = []
    shipments: list[dict] = []
    payments_by_txn: dict[str, list[dict]] = {}
    refunds: list[dict] = []

    for ev in events:
        validate_event(ev, allow_requests=False)
        et = ev["event_type"]
        d = ev["data"]
        if et == "order.created" and d["external_order_id"] == order_id:
            order_created = d
        elif et == "order.status_changed" and d["external_order_id"] == order_id:
            order_statuses.append((d["status"], ev["occurred_at"]))
        elif et == "shipment.updated" and d["external_order_id"] == order_id:
            shipments.append(ev)
        elif et == "payment.updated" and d["external_order_id"] == order_id:
            payments_by_txn.setdefault(d["provider_txn_ref"], []).append(ev)
        elif et == "refund.updated" and d["external_order_id"] == order_id:
            refunds.append(ev)

    return {
        "order_created": order_created,
        "order_statuses": order_statuses,
        "shipments": shipments,
        "payments_by_txn": payments_by_txn,
        "refunds": refunds,
    }


@unittest.skipUnless(
    HAS_MARKETPLACE_SIM,
    "marketplace_sim không đóng gói vào production image.",
)
class StoriesAndSenderTests(unittest.TestCase):
    def test_item7_all_13_stories_deterministic_and_final_states(self) -> None:
        expected_names = (
            "giao_dung_han_cod",
            "dang_trung_chuyen",
            "cap_nhat_ao_giao_lai",
            "giao_that_bai_hoan_ve",
            "nghen_kho_mega_sale",
            "hoan_tien_cham",
            "hoan_tien_that_bai",
            "thanh_toan_that_bai_roi_thanh_cong",
            "huy_truoc_khi_giao",
            "doi_size_trong_han",
            "qua_han_doi_tra",
            "het_bao_hanh",
            "giao_tre_han_cam_ket",
        )
        self.assertEqual(STORY_NAMES, expected_names)
        self.assertEqual(len(STORY_NAMES), 13)

        for story in STORY_NAMES:
            with self.subTest(story=story), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                s1 = MarketplaceSimulator.initialize(base / "a", seed=4242)
                r1 = s1.insert_story(story)
                f1 = base / "a.jsonl"
                s1.export_events(f1)

                s2 = MarketplaceSimulator.initialize(base / "b", seed=4242)
                r2 = s2.insert_story(story)
                f2 = base / "b.jsonl"
                s2.export_events(f2)

                # Hai lần chạy trên hai kho mới cho cùng chuỗi sự kiện hệt từng byte
                self.assertEqual(f1.read_bytes(), f2.read_bytes())
                self.assertEqual(r1["external_order_id"], r2["external_order_id"])

                events = [
                    json.loads(line)
                    for line in f1.read_text(encoding="utf-8").splitlines()
                ]
                clock_dt = parse_iso_vn(s1.get_status()["clock_iso"], "clock")
                assert clock_dt is not None
                oid = r1["external_order_id"]
                info = _collect_story_summary(events, oid)

                final_order_status, final_order_ts = info["order_statuses"][-1]
                shp_list = info["shipments"]
                txns = info["payments_by_txn"]
                rfds = info["refunds"]

                if story == "giao_dung_han_cod":
                    self.assertEqual(final_order_status, "delivered")
                    self.assertEqual(
                        shp_list[-1]["data"]["carrier_status_raw"], "delivered"
                    )
                    self.assertEqual(len(txns), 1)
                    only_txn = next(iter(txns.values()))[-1]
                    self.assertEqual(only_txn["source_system"], "marketplace_sim")
                    self.assertEqual(only_txn["data"]["method"], "cod")
                    self.assertEqual(
                        only_txn["data"]["provider_status_raw"], "COD_SETTLED"
                    )

                elif story == "dang_trung_chuyen":
                    self.assertEqual(final_order_status, "shipping")
                    self.assertEqual(
                        shp_list[-1]["data"]["carrier_status_raw"], "transporting"
                    )
                    only_txn = next(iter(txns.values()))[-1]
                    self.assertEqual(
                        only_txn["data"]["provider_status_raw"], "PAY_SUCCEEDED"
                    )

                elif story == "cap_nhat_ao_giao_lai":
                    self.assertEqual(final_order_status, "delivered")
                    raw_codes = [e["data"]["carrier_status_raw"] for e in shp_list]
                    self.assertEqual(raw_codes.count("delivery_fail"), 1)
                    self.assertEqual(raw_codes[-1], "delivered")
                    fail_ev = next(
                        e
                        for e in shp_list
                        if e["data"]["carrier_status_raw"] == "delivery_fail"
                    )
                    deliv_ev = shp_list[-1]
                    fail_dt = parse_iso_vn(fail_ev["occurred_at"], "f")
                    deliv_dt = parse_iso_vn(deliv_ev["occurred_at"], "d")
                    assert fail_dt is not None and deliv_dt is not None
                    self.assertEqual(fail_dt.date(), deliv_dt.date())

                elif story == "giao_that_bai_hoan_ve":
                    self.assertEqual(final_order_status, "cancelled")
                    raw_codes = [e["data"]["carrier_status_raw"] for e in shp_list]
                    self.assertEqual(raw_codes.count("delivery_fail"), 3)
                    self.assertEqual(raw_codes[-1], "returned")
                    self.assertEqual(len(txns), 0)

                elif story == "nghen_kho_mega_sale":
                    self.assertEqual(final_order_status, "shipping")
                    last_shp = shp_list[-1]
                    self.assertEqual(
                        last_shp["data"]["carrier_status_raw"], "sorting"
                    )
                    sort_dt = parse_iso_vn(last_shp["occurred_at"], "s")
                    assert sort_dt is not None
                    self.assertGreater(
                        clock_dt - sort_dt, timedelta(hours=48)
                    )

                elif story == "hoan_tien_cham":
                    self.assertEqual(final_order_status, "delivered")
                    self.assertTrue(rfds)
                    last_rfd = rfds[-1]
                    self.assertEqual(
                        last_rfd["data"]["provider_status_raw"],
                        "REFUND_PROCESSING",
                    )
                    self.assertIsNone(last_rfd["data"]["completed_at"])
                    proc_dt = parse_iso_vn(last_rfd["occurred_at"], "p")
                    assert proc_dt is not None
                    self.assertGreaterEqual(
                        clock_dt - proc_dt, timedelta(days=10)
                    )

                elif story == "hoan_tien_that_bai":
                    self.assertTrue(rfds)
                    last_rfd = rfds[-1]["data"]
                    self.assertEqual(last_rfd["channel"], "e_wallet")
                    self.assertEqual(
                        last_rfd["provider_status_raw"], "REFUND_FAILED"
                    )
                    self.assertTrue(last_rfd["failure_reason"])

                elif story == "thanh_toan_that_bai_roi_thanh_cong":
                    self.assertEqual(len(txns), 2)
                    txn_lists = list(txns.values())
                    self.assertEqual(
                        txn_lists[0][-1]["data"]["provider_status_raw"],
                        "PAY_FAILED",
                    )
                    self.assertEqual(
                        txn_lists[1][-1]["data"]["provider_status_raw"],
                        "PAY_SUCCEEDED",
                    )

                elif story == "huy_truoc_khi_giao":
                    statuses_only = [s for s, _ in info["order_statuses"]]
                    self.assertEqual(
                        statuses_only, ["pending", "confirmed", "cancelled"]
                    )
                    self.assertEqual(len(shp_list), 0)

                elif story == "doi_size_trong_han":
                    self.assertEqual(final_order_status, "delivered")
                    deliv_dt = parse_iso_vn(final_order_ts, "d")
                    assert deliv_dt is not None
                    self.assertEqual(clock_dt - deliv_dt, timedelta(days=5))

                elif story == "qua_han_doi_tra":
                    self.assertEqual(final_order_status, "delivered")
                    deliv_dt = parse_iso_vn(final_order_ts, "d")
                    assert deliv_dt is not None
                    self.assertEqual(clock_dt - deliv_dt, timedelta(days=20))

                elif story == "het_bao_hanh":
                    self.assertEqual(final_order_status, "delivered")
                    deliv_dt = parse_iso_vn(final_order_ts, "d")
                    assert deliv_dt is not None
                    self.assertEqual(clock_dt - deliv_dt, timedelta(days=100))

                elif story == "giao_tre_han_cam_ket":
                    self.assertEqual(final_order_status, "delivered")
                    deliv_dt = parse_iso_vn(final_order_ts, "d")
                    promised_dt = parse_iso_vn(
                        info["order_created"]["promised_delivery_by"], "p"
                    )
                    assert deliv_dt is not None and promised_dt is not None
                    self.assertEqual(
                        deliv_dt - promised_dt, timedelta(hours=72)
                    )

    def test_item9_loopback_http_hmac_dedup_retries_and_secret_safety(self) -> None:
        # Kiểm danh sách host cho phép và từ chối host công khai
        for allowed in (
            "http://localhost:8080/ingest",
            "http://127.0.0.1:9000/events",
            "http://[::1]:8081/events",
            "http://retailops_web:8000/internal/events",
            "http://connector-svc/events",
        ):
            self.assertEqual(validate_endpoint_url(allowed), allowed)

        for forbidden in (
            "https://example.com/webhook",
            "http://8.8.8.8:8080/events",
            "http://192.168.1.50:8080/events",
            "http://svc.internal.local/events",
            "http://2130706433:8080/events",
            "http://0x7f000001/events",
            "ftp://localhost:8080/events",
            "http://admin:pass@localhost:8080/events",
            "",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(EndpointNotAllowedError):
                    validate_endpoint_url(forbidden)

        secret_text = "TEST_CONNECTOR_SIGNING_KEY_DO_NOT_PRINT_998877"
        received_events: dict[str, bytes] = {}
        request_log: list[tuple[str, dict[str, str], bytes]] = []
        mode = {"behavior": "normal"}

        class LoopbackCollector(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                hdrs = {k.lower(): v for k, v in self.headers.items()}
                ev_id = hdrs.get("x-sim-event-id", "")
                request_log.append((ev_id, hdrs, raw_body))

                if mode["behavior"] == "always_503":
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(b"unavailable")
                    return

                # Kiểm chữ ký HMAC-SHA256 phía nhận
                ts = hdrs["x-sim-timestamp"]
                expected_sig = (
                    "v1="
                    + hmac.new(
                        secret_text.encode("utf-8"),
                        ts.encode("ascii") + b"." + raw_body,
                        hashlib.sha256,
                    ).hexdigest()
                )
                if not hmac.compare_digest(
                    hdrs.get("x-sim-signature", ""), expected_sig
                ):
                    self.send_response(401)
                    self.end_headers()
                    return

                if ev_id in received_events:
                    self.send_response(409)
                    self.end_headers()
                    return

                received_events[ev_id] = raw_body
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

        server = HTTPServer(("127.0.0.1", 0), LoopbackCollector)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop_server() -> None:
            server.shutdown()
            thread.join()
            server.server_close()

        self.addCleanup(stop_server)

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            secret_file = base / "connector.secret"
            secret_file.write_text(secret_text + "\n", encoding="utf-8")

            sim_dir = base / "sim_send"
            sim = MarketplaceSimulator.initialize(sim_dir, seed=77)
            endpoint = f"http://127.0.0.1:{port}/api/internal/events"

            # Gửi lần đầu qua CLI -> toàn bộ 20 sự kiện catalog được ký đúng và nhận đủ
            proc1 = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "marketplace_sim",
                    "send",
                    "--data-dir",
                    str(sim_dir),
                    "--endpoint",
                    endpoint,
                    "--secret-file",
                    str(secret_file),
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(proc1.returncode, 0, proc1.stderr)
            self.assertEqual(len(received_events), 20)
            self.assertNotIn(secret_text, proc1.stdout)
            self.assertNotIn(secret_text, proc1.stderr)

            # Gửi lại lần hai -> không gửi lại bản đã sent, không tạo bản nhận mới
            before_reqs = len(request_log)
            proc2 = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "marketplace_sim",
                    "send",
                    "--data-dir",
                    str(sim_dir),
                    "--endpoint",
                    endpoint,
                    "--secret-file",
                    str(secret_file),
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(proc2.returncode, 0)
            self.assertEqual(len(request_log), before_reqs)
            self.assertEqual(len(received_events), 20)

            # Giả lập phía nhận đã có sẵn event (trả 409) -> vẫn coi là sent ở lần đầu
            conn = sim._connect_existing()
            try:
                with conn:
                    conn.execute(
                        "UPDATE events SET delivery_status = 'pending' WHERE seq_pk = 1"
                    )
            finally:
                conn.close()
            res_409 = sim.send_pending_events(
                endpoint=endpoint, secret_file=secret_file
            )
            self.assertEqual(res_409, {"sent": 1, "dead": 0})
            self.assertEqual(len(received_events), 20)

            # Host công khai bị từ chối qua CLI và không lộ khóa trong thông báo lỗi
            proc_pub = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "marketplace_sim",
                    "send",
                    "--data-dir",
                    str(sim_dir),
                    "--endpoint",
                    "https://public.example.org/hook",
                    "--secret-file",
                    str(secret_file),
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(proc_pub.returncode, 0)
            self.assertNotIn(secret_text, proc_pub.stdout)
            self.assertNotIn(secret_text, proc_pub.stderr)

            # Lỗi 503 liên tiếp -> thử lại đúng 1, 2, 4, 8, 16 giây rồi đánh dấu dead
            mode["behavior"] = "always_503"
            conn = sim._connect_existing()
            try:
                with conn:
                    conn.execute(
                        "UPDATE events SET delivery_status = 'pending', delivery_attempts = 0 WHERE seq_pk = 2"
                    )
            finally:
                conn.close()
            recorded_sleeps: list[float] = []
            res_dead = sim.send_pending_events(
                endpoint=endpoint,
                secret_file=secret_file,
                time_fn=lambda: 1791000000.0,
                sleep_fn=recorded_sleeps.append,
            )
            self.assertEqual(res_dead, {"sent": 0, "dead": 1})
            self.assertEqual(
                tuple(int(s) for s in recorded_sleeps), RETRY_DELAYS_SECONDS
            )
            st = sim.get_status()
            self.assertEqual(st["by_delivery_status"].get("dead"), 1)
            self.assertNotIn(
                secret_text, (sim_dir / "sim.sqlite3").read_bytes().decode("latin-1")
            )


class MarketplaceSimIsolationTests(unittest.TestCase):
    def test_item10_package_isolation_and_image_exclusion(self) -> None:
        if not HAS_MARKETPLACE_SIM:
            # Đang chạy bên trong container image retailops:ci -> package không có mặt
            self.assertIsNone(importlib.util.find_spec("marketplace_sim"))
            return

        sim_root = ROOT / "marketplace_sim"
        stdlib_names = set(sys.stdlib_module_names)

        # 1. Không file nào trong marketplace_sim/ import retailops, agent_protocol hay retailops_*
        #    và chỉ dùng thư viện chuẩn của Python
        for py_path in sorted(sim_root.rglob("*.py")):
            tree = ast.parse(
                py_path.read_text(encoding="utf-8"), filename=str(py_path)
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        self.assertFalse(
                            top == "retailops"
                            or top == "agent_protocol"
                            or top.startswith("retailops_"),
                            f"{py_path} import module bị cấm '{alias.name}'",
                        )
                        self.assertIn(
                            top,
                            stdlib_names | {"marketplace_sim"},
                            f"{py_path} dùng thư viện ngoài chuẩn '{alias.name}'",
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.level and node.level > 0:
                        continue
                    if node.module:
                        top = node.module.split(".")[0]
                        self.assertFalse(
                            top == "retailops"
                            or top == "agent_protocol"
                            or top.startswith("retailops_"),
                            f"{py_path} import module bị cấm '{node.module}'",
                        )
                        self.assertIn(
                            top,
                            stdlib_names | {"marketplace_sim"},
                            f"{py_path} dùng thư viện ngoài chuẩn '{node.module}'",
                        )

        # 2. Không file .py nào ngoài marketplace_sim/ và tests/ import marketplace_sim
        for py_path in sorted(ROOT.rglob("*.py")):
            rel_parts = py_path.relative_to(ROOT).parts
            if rel_parts[0] in {"marketplace_sim", "tests", ".git"}:
                continue
            tree = ast.parse(
                py_path.read_text(encoding="utf-8"), filename=str(py_path)
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotEqual(
                            alias.name.split(".")[0],
                            "marketplace_sim",
                            f"{py_path} ngoài phạm vi import marketplace_sim",
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotEqual(
                        node.module.split(".")[0],
                        "marketplace_sim",
                        f"{py_path} ngoài phạm vi import marketplace_sim",
                    )

        # 3. check_deployment_contract.py đạt và Dockerfile/.dockerignore không đưa marketplace_sim vào image
        if (ROOT / "Dockerfile").is_file():
            dockerfile_text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
            dockerignore_text = (ROOT / ".dockerignore").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("marketplace_sim", dockerfile_text)
            self.assertNotIn("marketplace_sim", dockerignore_text)

        check_script = ROOT / "scripts" / "check_deployment_contract.py"
        if check_script.is_file():
            proc = subprocess.run(
                [sys.executable, str(check_script)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("DEPLOYMENT_CONTRACT_OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()
