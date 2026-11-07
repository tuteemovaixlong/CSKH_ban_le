"""Kiểm thử cô lập cho CLI, catalog, khách/người nhận, máy trạng thái, tất định và voucher (W6.1a mục 0, 2, 3, 4, 5, 6, 8, 11)."""

from __future__ import annotations

import ast
from collections import defaultdict
from datetime import timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HAS_MARKETPLACE_SIM = (ROOT / "marketplace_sim").is_dir()

if HAS_MARKETPLACE_SIM:
    from marketplace_sim import INITIAL_CLOCK_ISO
    from marketplace_sim.contract import EMAIL_LIKE_RE, parse_iso_vn, validate_event
    from marketplace_sim.simulator import MarketplaceSimulator, SimulatorError
    from marketplace_sim.state_machines import (
        ALLOWED_ORDER_TRANSITIONS,
        StateTransitionError,
        validate_order_transition,
        validate_payment_transition,
        validate_refund_transition,
        validate_shipment_transition,
    )

VIETNAMESE_CHAR_RE = re.compile(
    r"[àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÈÉẺẼẸÊẾỀỂỄỆÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴĐ]"
)
TEN_DIGIT_PHONE_RE = re.compile(r"(?<!\d)0\d{9}(?!\d)")


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    # The CLI itself must select UTF-8; don't let interpreter-wide encoding
    # switches mask a Windows console-codepage regression.
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONIOENCODING", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "marketplace_sim", *args],
        cwd=str(cwd or ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@unittest.skipUnless(
    HAS_MARKETPLACE_SIM,
    "marketplace_sim không đóng gói vào production image.",
)
class MarketplaceSimCoreTests(unittest.TestCase):
    def test_item0_cli_all_commands_and_vietnamese_errors_and_write_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            data_dir = work / "custom_store"
            out_file = work / "exports" / "events.jsonl"
            req_file = work / "inputs" / "voucher_reqs.jsonl"
            req_file.parent.mkdir(parents=True)
            req_file.write_text(
                json.dumps(
                    {
                        "contract": "retailops-integration-v2",
                        "event_id": "evt:retailops:req:cli01",
                        "event_type": "voucher.requested",
                        "source_system": "retailops",
                        "merchant_id": "shop-cli",
                        "occurred_at": "2026-10-05T10:00:00+07:00",
                        "sequence": 1,
                        "data": {
                            "request_id": "req-cli-001",
                            "external_order_id": "SIM-O-00001",
                            "external_customer_id": "SIM-C-0001",
                            "voucher_type": "amount",
                            "value": 50000,
                            "reason": "late_delivery",
                            "approved_by_role": "staff",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            # Lệnh sai tham số trả mã khác 0 kèm thông báo tiếng Việt, không tạo file rác
            bad_invocations = [
                (),
                ("lenh_la",),
                ("run", "--data-dir", str(data_dir), "--days", "3"),  # chưa init
                ("init", "--data-dir", str(data_dir), "--seed", "abc"),
                ("init", "--data-dir", str(data_dir), "--seed", "-5"),
            ]
            for bad_args in bad_invocations:
                res = _run_cli(*bad_args, cwd=work)
                self.assertNotEqual(res.returncode, 0, bad_args)
                self.assertRegex(res.stderr, VIETNAMESE_CHAR_RE)
                self.assertFalse(data_dir.exists())

            # Chạy trọn bộ lệnh hợp lệ trên thư mục tạm
            self.assertEqual(
                _run_cli(
                    "init",
                    "--data-dir",
                    str(data_dir),
                    "--seed",
                    "101",
                    "--merchant-id",
                    "shop-cli",
                    cwd=work,
                ).returncode,
                0,
            )
            self.assertEqual(
                _run_cli(
                    "run", "--data-dir", str(data_dir), "--days", "3", cwd=work
                ).returncode,
                0,
            )
            self.assertEqual(
                _run_cli(
                    "story",
                    "--data-dir",
                    str(data_dir),
                    "giao_dung_han_cod",
                    cwd=work,
                ).returncode,
                0,
            )
            self.assertEqual(
                _run_cli(
                    "advance",
                    "--data-dir",
                    str(data_dir),
                    "--hours",
                    "24",
                    cwd=work,
                ).returncode,
                0,
            )
            self.assertEqual(
                _run_cli(
                    "ingest-requests",
                    "--data-dir",
                    str(data_dir),
                    "--file",
                    str(req_file),
                    cwd=work,
                ).returncode,
                0,
            )
            self.assertEqual(
                _run_cli(
                    "export",
                    "--data-dir",
                    str(data_dir),
                    "--out",
                    str(out_file),
                    cwd=work,
                ).returncode,
                0,
            )
            st_res = _run_cli("status", "--data-dir", str(data_dir), cwd=work)
            self.assertEqual(st_res.returncode, 0)
            status_obj = json.loads(st_res.stdout)
            self.assertEqual(status_obj["merchant_id"], "shop-cli")
            self.assertGreater(status_obj["total_events"], 20)

            # Kiểm tra không có file nào được ghi ra ngoài --data-dir, --out và inputs đã tạo
            top_entries = {p.name for p in work.iterdir()}
            self.assertEqual(top_entries, {"custom_store", "exports", "inputs"})

            # Kiểm tra thư mục mặc định .marketplace_sim/ khi không truyền --data-dir
            default_cwd = work / "default_dir_check"
            default_cwd.mkdir()
            self.assertEqual(_run_cli("init", cwd=default_cwd).returncode, 0)
            self.assertTrue((default_cwd / ".marketplace_sim" / "sim.sqlite3").is_file())

    def test_item2_catalog_skus_d10_products_and_no_test_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sim = MarketplaceSimulator.initialize(Path(tmp) / "store", seed=7)
            out_path = Path(tmp) / "init.jsonl"
            count = sim.export_events(out_path)
            events = [
                json.loads(line)
                for line in out_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(count, len(sim.catalog))
            self.assertEqual(count, 20)

            seen_products: set[str] = set()
            seen_skus: set[str] = set()
            by_pid: dict[str, dict] = {}

            for ev in events:
                validate_event(ev, allow_requests=False)
                self.assertEqual(ev["event_type"], "product.upserted")
                d = ev["data"]
                pid = d["external_product_id"]
                self.assertNotIn(pid, seen_products)
                seen_products.add(pid)
                by_pid[pid] = d

                # Không có trường nào nhắc tới dữ liệu thử nghiệm
                serialized = json.dumps(d, ensure_ascii=False).lower()
                self.assertNotIn("thử nghiệm", serialized)
                self.assertNotIn("dữ liệu mẫu", serialized)

                for v in d["variants"]:
                    self.assertNotIn(v["sku"], seen_skus)
                    seen_skus.add(v["sku"])

            # Kiểm tra chính xác W6.1a-D10 cho P-101, P-102, P-202
            self.assertEqual(
                by_pid["P-101"]["description"],
                "Áo thun cổ tròn, form regular, vải dày vừa, mặc hằng ngày.",
            )
            self.assertEqual(
                by_pid["P-101"]["material"],
                "100% cotton, định lượng 220 g/m²",
            )
            self.assertEqual(
                by_pid["P-101"]["care"],
                "Giặt máy nước lạnh dưới 30°C, lộn trái khi giặt, không dùng chất tẩy, phơi nơi thoáng mát, ủi nhiệt độ thấp.",
            )

            self.assertEqual(
                by_pid["P-102"]["description"],
                "Áo khoác dáng suông có mũ, khóa kéo YKK, hai túi khóa kéo, chống gió và chống nước nhẹ.",
            )
            self.assertEqual(
                by_pid["P-102"]["material"],
                "Vải dù polyester 2 lớp, lót lưới",
            )
            self.assertEqual(
                by_pid["P-102"]["care"],
                "Giặt tay hoặc giặt máy chế độ nhẹ, kéo khóa trước khi giặt, không sấy nhiệt cao, không ủi trực tiếp lên lớp phủ.",
            )

            self.assertEqual(
                by_pid["P-202"]["description"],
                "Áo polo cổ bẻ, tay ngắn, vải cá sấu thoáng khí.",
            )
            self.assertEqual(
                by_pid["P-202"]["material"],
                "Vải cá sấu 65% cotton, 35% polyester",
            )
            self.assertEqual(
                by_pid["P-202"]["care"],
                "Giặt máy nước lạnh, không vắt mạnh, phơi ngang để giữ form cổ.",
            )

    def test_items_3_4_5_6_simulation_invariants_and_state_machines(self) -> None:
        # Kiểm trực tiếp các chuyển trạng thái bị cấm trong máy trạng thái
        for bad_src, bad_dst in [
            ("pending", "shipping"),
            ("pending", "delivered"),
            ("confirmed", "pending"),
            ("confirmed", "delivered"),
            ("shipping", "confirmed"),
            ("delivered", "cancelled"),
            ("cancelled", "confirmed"),
        ]:
            with self.assertRaises(StateTransitionError):
                validate_order_transition(bad_src, bad_dst)

        # Vận đơn không đi lùi; sau 3 lần thất bại chỉ còn nhánh hoàn
        with self.assertRaises(StateTransitionError):
            validate_shipment_transition("sorting", "picked", current_attempts=0)
        with self.assertRaises(StateTransitionError):
            validate_shipment_transition("delivered", "delivering", current_attempts=0)
        with self.assertRaises(StateTransitionError):
            validate_shipment_transition(
                "delivery_fail", "delivering", current_attempts=3
            )
        with self.assertRaises(StateTransitionError):
            validate_shipment_transition(
                "delivering", "delivery_fail", current_attempts=3
            )
        self.assertEqual(
            validate_shipment_transition(
                "delivery_fail", "waiting_to_return", current_attempts=3
            ),
            3,
        )

        # Thanh toán và hoàn tiền không đi lùi
        with self.assertRaises(StateTransitionError):
            validate_payment_transition("PAY_SUCCEEDED", "PAY_PENDING")
        with self.assertRaises(StateTransitionError):
            validate_refund_transition("REFUND_COMPLETED", "REFUND_PROCESSING")
        with self.assertRaises(StateTransitionError):
            validate_refund_transition("REFUND_PROCESSING", "REFUND_INITIATED")

        # Kiểm carriers.json: GHN công khai + 2 hãng giả lập ghi rõ là giả lập
        carriers_raw = json.loads(
            (ROOT / "marketplace_sim" / "data" / "carriers.json").read_text(
                encoding="utf-8"
            )
        )["carriers"]
        self.assertEqual(len(carriers_raw), 3)
        by_code = {c["code"]: c for c in carriers_raw}
        ghn_expected = {
            "ready_to_pick",
            "picking",
            "picked",
            "storing",
            "transporting",
            "sorting",
            "delivering",
            "delivered",
            "delivery_fail",
            "waiting_to_return",
            "return",
            "returned",
            "cancel",
        }
        self.assertEqual(set(by_code["GHN"]["status_codes"].values()), ghn_expected)
        for other_code in set(by_code.keys()) - {"GHN"}:
            self.assertTrue(by_code[other_code]["is_synthetic_codes"])
            self.assertIn("giả lập", by_code[other_code]["note"].lower())

        # Chạy mô phỏng 30 ngày + tua thêm 120 giờ để kết thúc mọi đơn bay dở
        with tempfile.TemporaryDirectory() as tmp:
            sim = MarketplaceSimulator.initialize(Path(tmp) / "sim", seed=2026)
            sim.run_days(30)
            sim.advance_hours(120)
            out_path = Path(tmp) / "out.jsonl"
            sim.export_events(out_path)
            raw_text = out_path.read_text(encoding="utf-8")
            events = [json.loads(line) for line in raw_text.splitlines()]

        phone_prefix = str(sim.params["phone_prefix"])
        self.assertEqual(phone_prefix, "0123")

        # Quét toàn bộ file xuất cho mục 3 (PII/liên hệ)
        self.assertIsNone(EMAIL_LIKE_RE.search(raw_text))
        all_phones_in_file = TEN_DIGIT_PHONE_RE.findall(raw_text)
        recipient_phones: list[str] = []

        order_created_by_id: dict[str, dict] = {}
        order_statuses_by_id: dict[str, list[tuple[str, str]]] = defaultdict(list)
        shipment_events_by_id: dict[str, list[dict]] = defaultdict(list)
        shipment_delivered_at_by_order: dict[str, str] = {}
        payments_by_order: dict[str, list[dict]] = defaultdict(list)
        refunds_by_ref: dict[str, list[dict]] = defaultdict(list)

        # Kiểm thứ tự xuất: occurred_at rồi event_id
        sort_keys = [(ev["occurred_at"], ev["event_id"]) for ev in events]
        self.assertEqual(sort_keys, sorted(sort_keys))

        for ev in events:
            validate_event(ev, allow_requests=False)
            et = ev["event_type"]
            d = ev["data"]

            if et == "customer.upserted":
                self.assertEqual(
                    set(d.keys()), {"external_customer_id", "display_name"}
                )
                self.assertTrue(d["external_customer_id"].startswith("SIM-C-"))

            elif et == "order.created":
                oid = d["external_order_id"]
                order_created_by_id[oid] = d
                rphone = d["recipient"]["phone"]
                self.assertTrue(rphone.startswith(phone_prefix))
                recipient_phones.append(rphone)
                subtotal = sum(i["quantity"] * i["unit_price"] for i in d["items"])
                self.assertEqual(d["total"], subtotal + d["shipping_fee"])
                self.assertGreater(
                    parse_iso_vn(d["promised_delivery_by"], "p"),
                    parse_iso_vn(d["ordered_at"], "o"),
                )

            else:
                # Ngoài order.created, không sự kiện nào có recipient hay address_line
                self.assertNotIn("recipient", d)
                self.assertNotIn("address_line", d)
                self.assertNotIn("phone", d)

            if et == "order.status_changed":
                order_statuses_by_id[d["external_order_id"]].append(
                    (d["status"], ev["occurred_at"])
                )
            elif et == "shipment.updated":
                shipment_events_by_id[d["external_shipment_id"]].append(ev)
                carrier_codes = sim.carriers[d["carrier"]]["status_codes"]
                if d["carrier_status_raw"] == carrier_codes["delivered"]:
                    shipment_delivered_at_by_order[d["external_order_id"]] = ev[
                        "occurred_at"
                    ]
                if d["shipper_phone_masked"] is not None:
                    self.assertIn("x", d["shipper_phone_masked"].lower())
            elif et == "payment.updated":
                payments_by_order[d["external_order_id"]].append(ev)
            elif et == "refund.updated":
                refunds_by_ref[d["provider_refund_ref"]].append(ev)

        # Số điện thoại 10 chữ số chỉ xuất hiện đúng ở recipient.phone
        self.assertEqual(sorted(all_phones_in_file), sorted(recipient_phones))
        self.assertGreater(len(order_created_by_id), 50)

        # Kiểm chuỗi chuyển trạng thái đơn và trùng mốc delivered với vận đơn
        for oid, transitions in order_statuses_by_id.items():
            prev: str | None = None
            for st, occ_at in transitions:
                self.assertIn(st, ALLOWED_ORDER_TRANSITIONS[prev])
                if st == "delivered":
                    self.assertEqual(
                        shipment_delivered_at_by_order.get(oid), occ_at
                    )
                prev = st

        # Kiểm sequence vận đơn và nhánh 3 lần thất bại
        for shp_id, sevents in shipment_events_by_id.items():
            seqs = [e["sequence"] for e in sevents]
            self.assertEqual(seqs, list(range(1, len(sevents) + 1)))
            carrier = sevents[0]["data"]["carrier"]
            inv_map = {
                v: k for k, v in sim.carriers[carrier]["status_codes"].items()
            }
            cur_stage: str | None = None
            cur_att = 0
            for e in sevents:
                stg = inv_map[e["data"]["carrier_status_raw"]]
                cur_att = validate_shipment_transition(
                    cur_stage, stg, current_attempts=cur_att
                )
                cur_stage = stg

        # Kiểm đơn COD chỉ thanh toán thành công khi đơn đã giao
        final_order_status = {
            oid: tr[-1][0] for oid, tr in order_statuses_by_id.items()
        }
        paid_by_order: dict[str, int] = defaultdict(int)
        succeeded_txn_by_order: dict[str, set[str]] = defaultdict(set)
        for oid, pevents in payments_by_order.items():
            for pe in pevents:
                pd = pe["data"]
                if pd["method"] == "cod" and pd["provider_status_raw"] == "COD_SETTLED":
                    self.assertEqual(final_order_status[oid], "delivered")
                if pd["provider_status_raw"] in {"PAY_SUCCEEDED", "COD_SETTLED"}:
                    paid_by_order[oid] += pd["amount"]
                    succeeded_txn_by_order[oid].add(pd["provider_txn_ref"])

        # Kiểm hoàn tiền: không đi lùi, không vượt số đã thu, nối đúng giao dịch (trừ COD)
        refunded_by_order: dict[str, int] = defaultdict(int)
        for rfd_ref, revents in refunds_by_ref.items():
            prev_r: str | None = None
            for re_ev in revents:
                validate_refund_transition(
                    prev_r, re_ev["data"]["provider_status_raw"]
                )
                prev_r = re_ev["data"]["provider_status_raw"]
            last_d = revents[-1]["data"]
            oid = last_d["external_order_id"]
            pmethod = order_created_by_id[oid]["payment_method"]
            if pmethod == "cod":
                self.assertIsNone(last_d["provider_txn_ref"])
                self.assertEqual(last_d["channel"], "bank_transfer")
            else:
                self.assertIn(
                    last_d["provider_txn_ref"], succeeded_txn_by_order[oid]
                )
            if last_d["provider_status_raw"] != "REFUND_FAILED":
                refunded_by_order[oid] += last_d["amount"]

        for oid, r_sum in refunded_by_order.items():
            self.assertLessEqual(r_sum, paid_by_order[oid])

    def test_item6_explicit_refund_guardrails_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sim = MarketplaceSimulator.initialize(Path(tmp) / "store", seed=11)
            sim.insert_story("giao_dung_han_cod")  # Đơn COD SIM-O-ST-001 đã giao
            conn = sim._connect_existing()
            try:
                now_dt = parse_iso_vn(sim._get_meta(conn, "clock_iso"), "c")
                assert now_dt is not None
                order_row = conn.execute(
                    "SELECT external_order_id, paid_amount FROM orders_state WHERE external_order_id = 'SIM-O-ST-001'"
                ).fetchone()
                paid = int(order_row["paid_amount"])

                # Đơn COD hoàn qua kênh khác bank_transfer -> từ chối
                with self.assertRaises(SimulatorError):
                    sim.emit_refund_updated(
                        conn,
                        provider_refund_ref="RFD-BAD-CHAN",
                        external_order_id="SIM-O-ST-001",
                        amount=50000,
                        channel="e_wallet",
                        provider_status_raw="REFUND_INITIATED",
                        failure_reason=None,
                        initiated_dt=now_dt,
                        occurred_dt=now_dt,
                    )

                # Hoàn vượt số tiền đã thu -> từ chối
                with self.assertRaises(SimulatorError):
                    sim.emit_refund_updated(
                        conn,
                        provider_refund_ref="RFD-TOO-MUCH",
                        external_order_id="SIM-O-ST-001",
                        amount=paid + 1,
                        channel="bank_transfer",
                        provider_status_raw="REFUND_INITIATED",
                        failure_reason=None,
                        initiated_dt=now_dt,
                        occurred_dt=now_dt,
                    )
            finally:
                conn.close()

    def test_item8_determinism_params_notes_and_no_wallclock(self) -> None:
        # Mọi tham số trong params.json đều có trường note chứa "giả định"
        raw_params = json.loads(
            (ROOT / "marketplace_sim" / "data" / "params.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertGreaterEqual(len(raw_params), 10)
        for key, entry in raw_params.items():
            self.assertIn("note", entry, key)
            self.assertIn("giả định", entry["note"].lower(), key)

        # Không dùng datetime.now / utcnow / time.time trong simulator & stories
        for mod_name in ("simulator.py", "stories.py", "contract.py"):
            tree = ast.parse(
                (ROOT / "marketplace_sim" / mod_name).read_text(encoding="utf-8")
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in {
                    "now",
                    "utcnow",
                    "today",
                }:
                    self.fail(f"{mod_name} gọi hàm thời gian thực '{node.attr}'.")
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "time"
                    and node.attr == "time"
                ):
                    self.fail(f"{mod_name} gọi time.time() trong chế độ tất định.")

        # Cùng seed -> từng byte giống hệt; khác seed -> khác
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            s1 = MarketplaceSimulator.initialize(
                base / "r1", seed=999, merchant_id="shop-det"
            )
            self.assertEqual(s1.get_status()["clock_iso"], INITIAL_CLOCK_ISO)
            s1.run_days(5)
            s1.insert_story("giao_tre_han_cam_ket")
            s1.advance_hours(12)
            f1 = base / "out1.jsonl"
            s1.export_events(f1)

            s2 = MarketplaceSimulator.initialize(
                base / "r2", seed=999, merchant_id="shop-det"
            )
            s2.run_days(5)
            s2.insert_story("giao_tre_han_cam_ket")
            s2.advance_hours(12)
            f2 = base / "out2.jsonl"
            s2.export_events(f2)

            s3 = MarketplaceSimulator.initialize(
                base / "r3", seed=1000, merchant_id="shop-det"
            )
            s3.run_days(5)
            s3.insert_story("giao_tre_han_cam_ket")
            s3.advance_hours(12)
            f3 = base / "out3.jsonl"
            s3.export_events(f3)

            self.assertEqual(f1.read_bytes(), f2.read_bytes())
            self.assertNotEqual(f1.read_bytes(), f3.read_bytes())

    def test_item11_voucher_ingest_idempotency_invalid_skip_and_seeded_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            req_path = base / "requests.jsonl"
            valid_amount = {
                "contract": "retailops-integration-v2",
                "event_id": "evt:retailops:vreq:1001",
                "event_type": "voucher.requested",
                "source_system": "retailops",
                "merchant_id": "MERCHANT-SIM-001",
                "occurred_at": "2026-10-08T09:00:00+07:00",
                "sequence": 1,
                "data": {
                    "request_id": "req-comp-1001",
                    "external_order_id": "SIM-O-98765",
                    "external_customer_id": "SIM-C-0042",
                    "voucher_type": "amount",
                    "value": 50000,
                    "reason": "late_delivery",
                    "approved_by_role": "staff",
                },
            }
            valid_freeship = {
                "contract": "retailops-integration-v2",
                "event_id": "evt:retailops:vreq:1002",
                "event_type": "voucher.requested",
                "source_system": "retailops",
                "merchant_id": "MERCHANT-SIM-001",
                "occurred_at": "2026-10-08T09:05:00+07:00",
                "sequence": 1,
                "data": {
                    "request_id": "req-comp-1002",
                    "external_order_id": "SIM-O-98766",
                    "external_customer_id": "SIM-C-0043",
                    "voucher_type": "free_shipping",
                    "value": 0,
                    "reason": "late_delivery",
                    "approved_by_role": "manager",
                },
            }
            invalid_contract = {
                "contract": "retailops-integration-v2",
                "event_id": "evt:retailops:vreq:bad1",
                "event_type": "voucher.requested",
                "source_system": "retailops",
                "merchant_id": "MERCHANT-SIM-001",
                "occurred_at": "2026-10-08T09:06:00+07:00",
                "sequence": 1,
                "data": {
                    "request_id": "req-bad-1",
                    "external_order_id": "SIM-O-98767",
                    "external_customer_id": "SIM-C-0044",
                    "voucher_type": "free_shipping",
                    "value": 25000,  # sai hợp đồng: free_shipping phải có value == 0
                    "reason": "late_delivery",
                    "approved_by_role": "staff",
                },
            }
            req_path.write_text(
                "\n".join(
                    [
                        json.dumps(valid_amount, ensure_ascii=False),
                        "{broken json line",
                        json.dumps(invalid_contract, ensure_ascii=False),
                        json.dumps(valid_amount, ensure_ascii=False),  # lặp trong cùng file
                        json.dumps(valid_freeship, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            sim_dir = base / "store_a"
            _run_cli("init", "--data-dir", str(sim_dir), "--seed", "555")
            ing1 = _run_cli(
                "ingest-requests",
                "--data-dir",
                str(sim_dir),
                "--file",
                str(req_path),
            )
            self.assertEqual(ing1.returncode, 0)
            res1 = json.loads(ing1.stdout)
            self.assertEqual(res1["issued"], 2)
            self.assertEqual(res1["duplicates"], 1)
            self.assertEqual(res1["skipped_errors"], 2)
            self.assertIn("Lỗi yêu cầu voucher bị bỏ qua", ing1.stderr)

            # Đọc lại cùng file không phát thêm mã nào
            ing2 = _run_cli(
                "ingest-requests",
                "--data-dir",
                str(sim_dir),
                "--file",
                str(req_path),
            )
            self.assertEqual(ing2.returncode, 0)
            res2 = json.loads(ing2.stdout)
            self.assertEqual(res2["issued"], 0)
            self.assertEqual(res2["duplicates"], 3)

            out_a = base / "vouchers_a.jsonl"
            MarketplaceSimulator(sim_dir).export_events(out_a)
            issued_events = [
                json.loads(line)
                for line in out_a.read_text(encoding="utf-8").splitlines()
                if '"voucher.issued"' in line
            ]
            self.assertEqual(len(issued_events), 2)
            by_ref = {e["data"]["request_ref"]: e["data"] for e in issued_events}
            self.assertEqual(by_ref["req-comp-1001"]["voucher_type"], "amount")
            self.assertEqual(by_ref["req-comp-1001"]["value"], 50000)
            self.assertEqual(
                by_ref["req-comp-1002"]["voucher_type"], "free_shipping"
            )
            self.assertEqual(by_ref["req-comp-1002"]["value"], 0)
            self.assertNotIn("98765", by_ref["req-comp-1001"]["code"])

            # Đổi seed -> mã voucher khác, chứng minh phụ thuộc seed và không đoán được từ mã đơn
            sim_b = MarketplaceSimulator.initialize(base / "store_b", seed=556)
            sim_b.ingest_voucher_requests(req_path)
            out_b = base / "vouchers_b.jsonl"
            sim_b.export_events(out_b)
            issued_b = [
                json.loads(line)["data"]["code"]
                for line in out_b.read_text(encoding="utf-8").splitlines()
                if '"voucher.issued"' in line
            ]
            self.assertNotEqual(
                [e["data"]["code"] for e in issued_events], issued_b
            )


if __name__ == "__main__":
    unittest.main()
