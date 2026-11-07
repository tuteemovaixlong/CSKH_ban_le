"""Kiểm thử cô lập cho hợp đồng sự kiện v2 (W6.1a mục 1)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HAS_MARKETPLACE_SIM = (ROOT / "marketplace_sim").is_dir()

if HAS_MARKETPLACE_SIM:
    from marketplace_sim.contract import (
        ALL_EVENT_TYPES,
        ContractError,
        OUTBOUND_EVENT_TYPES,
        validate_event,
    )


@unittest.skipUnless(
    HAS_MARKETPLACE_SIM,
    "marketplace_sim không đóng gói vào production image.",
)
class EventContractV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.examples_dir = ROOT / "marketplace_sim" / "examples"
        self.examples: dict[str, dict] = {}
        for path in sorted(self.examples_dir.glob("*.json")):
            obj = json.loads(path.read_text(encoding="utf-8"))
            self.examples[obj["event_type"]] = obj

    def test_contract_markdown_matches_handoff_section_3(self) -> None:
        contract_md = (
            ROOT / "marketplace_sim" / "CONTRACT.md"
        ).read_text(encoding="utf-8")
        self.assertIn("## 3. Hợp đồng sự kiện v2", contract_md)
        self.assertIn("retailops-integration-v2", contract_md)
        for etype in ALL_EVENT_TYPES:
            self.assertIn(f"`{etype}`", contract_md)
        self.assertIn("X-Sim-Signature", contract_md)

    def test_every_event_type_has_valid_example(self) -> None:
        self.assertEqual(set(self.examples.keys()), set(ALL_EVENT_TYPES))
        for etype, payload in self.examples.items():
            with self.subTest(event_type=etype):
                validated = validate_event(copy.deepcopy(payload))
                self.assertEqual(validated["event_type"], etype)
                if etype in OUTBOUND_EVENT_TYPES:
                    validate_event(copy.deepcopy(payload), allow_requests=False)
                else:
                    with self.assertRaises(ContractError):
                        validate_event(
                            copy.deepcopy(payload), allow_requests=False
                        )

    def test_contract_nullable_fields_accept_null_values(self) -> None:
        refund = copy.deepcopy(self.examples["refund.updated"])
        refund["data"]["provider_txn_ref"] = None
        refund["data"]["provider_status_raw"] = None
        refund["data"]["initiated_at"] = None
        refund["data"]["completed_at"] = None
        validate_event(refund)

        voucher = copy.deepcopy(self.examples["voucher.issued"])
        for field in (
            "valid_until",
            "external_order_id",
            "external_customer_id",
            "request_ref",
        ):
            voucher["data"][field] = None
        validate_event(voucher)

    def test_missing_required_fields_rejected_everywhere(self) -> None:
        sample = self.examples["order.created"]
        for env_key in list(sample.keys()):
            mutated = copy.deepcopy(sample)
            del mutated[env_key]
            with self.subTest(missing_envelope=env_key):
                with self.assertRaises(ContractError):
                    validate_event(mutated)

        for etype, base in self.examples.items():
            for data_key in list(base["data"].keys()):
                mutated = copy.deepcopy(base)
                del mutated["data"][data_key]
                with self.subTest(event_type=etype, missing_data=data_key):
                    with self.assertRaises(ContractError):
                        validate_event(mutated)

        # Các trường con trong variants, items, recipient
        for sub_key in list(
            self.examples["product.upserted"]["data"]["variants"][0].keys()
        ):
            mutated = copy.deepcopy(self.examples["product.upserted"])
            del mutated["data"]["variants"][0][sub_key]
            with self.assertRaises(ContractError):
                validate_event(mutated)

        for sub_key in list(
            self.examples["order.created"]["data"]["items"][0].keys()
        ):
            mutated = copy.deepcopy(self.examples["order.created"])
            del mutated["data"]["items"][0][sub_key]
            with self.assertRaises(ContractError):
                validate_event(mutated)

        for sub_key in list(
            self.examples["order.created"]["data"]["recipient"].keys()
        ):
            mutated = copy.deepcopy(self.examples["order.created"])
            del mutated["data"]["recipient"][sub_key]
            with self.assertRaises(ContractError):
                validate_event(mutated)

    def test_unknown_fields_rejected_at_all_levels(self) -> None:
        m_env = copy.deepcopy(self.examples["customer.upserted"])
        m_env["extra_top"] = "forbidden"
        with self.assertRaises(ContractError):
            validate_event(m_env)

        for etype, base in self.examples.items():
            mutated = copy.deepcopy(base)
            mutated["data"]["unexpected_field"] = 123
            with self.subTest(event_type=etype):
                with self.assertRaises(ContractError):
                    validate_event(mutated)

        # customer.upserted có thêm phone/email/address -> từ chối
        for forbidden_contact in ("phone", "email", "address"):
            m_cust = copy.deepcopy(self.examples["customer.upserted"])
            m_cust["data"][forbidden_contact] = "0123456789"
            with self.assertRaises(ContractError):
                validate_event(m_cust)

        # Trường lạ trong variants, items, recipient
        m_prod = copy.deepcopy(self.examples["product.upserted"])
        m_prod["data"]["variants"][0]["extra_sku_meta"] = "x"
        with self.assertRaises(ContractError):
            validate_event(m_prod)

        m_ord_item = copy.deepcopy(self.examples["order.created"])
        m_ord_item["data"]["items"][0]["discount"] = 0
        with self.assertRaises(ContractError):
            validate_event(m_ord_item)

        m_ord_rec = copy.deepcopy(self.examples["order.created"])
        m_ord_rec["data"]["recipient"]["email"] = "a@b.com"
        with self.assertRaises(ContractError):
            validate_event(m_ord_rec)

    def test_wrong_types_and_booleans_for_ints_rejected(self) -> None:
        # boolean không được coi là integer
        m_seq = copy.deepcopy(self.examples["customer.upserted"])
        m_seq["sequence"] = True
        with self.assertRaises(ContractError):
            validate_event(m_seq)

        m_price_bool = copy.deepcopy(self.examples["product.upserted"])
        m_price_bool["data"]["price"] = False
        with self.assertRaises(ContractError):
            validate_event(m_price_bool)

        m_price_float = copy.deepcopy(self.examples["product.upserted"])
        m_price_float["data"]["price"] = 299000.5
        with self.assertRaises(ContractError):
            validate_event(m_price_float)

        m_items_empty = copy.deepcopy(self.examples["order.created"])
        m_items_empty["data"]["items"] = []
        with self.assertRaises(ContractError):
            validate_event(m_items_empty)

        with self.assertRaises(ContractError):
            validate_event(["not-a-dict"])

    def test_out_of_domain_values_and_cross_field_rules_rejected(self) -> None:
        bad_cases: list[tuple[str, dict]] = []

        # Sai contract version
        c1 = copy.deepcopy(self.examples["customer.upserted"])
        c1["contract"] = "retailops-integration-v1"
        bad_cases.append(("wrong_contract", c1))

        # Sai event_id regex (quá ngắn hoặc chứa khoảng trắng)
        c2 = copy.deepcopy(self.examples["customer.upserted"])
        c2["event_id"] = "short"
        bad_cases.append(("short_event_id", c2))

        c3 = copy.deepcopy(self.examples["customer.upserted"])
        c3["event_id"] = "bad event id with spaces"
        bad_cases.append(("space_event_id", c3))

        # Sai múi giờ occurred_at (UTC Z thay vì +07:00)
        c4 = copy.deepcopy(self.examples["customer.upserted"])
        c4["occurred_at"] = "2026-10-01T09:00:00Z"
        bad_cases.append(("utc_z_timestamp", c4))

        c5 = copy.deepcopy(self.examples["customer.upserted"])
        c5["occurred_at"] = "2026-10-01T09:00:00+08:00"
        bad_cases.append(("wrong_offset_timestamp", c5))

        # sequence <= 0
        c6 = copy.deepcopy(self.examples["customer.upserted"])
        c6["sequence"] = 0
        bad_cases.append(("zero_sequence", c6))

        # Số tiền âm hoặc vượt 10^12
        c7 = copy.deepcopy(self.examples["payment.updated"])
        c7["data"]["amount"] = -1
        bad_cases.append(("negative_amount", c7))

        c8 = copy.deepcopy(self.examples["payment.updated"])
        c8["data"]["amount"] = 10**12 + 1
        bad_cases.append(("exceed_max_amount", c8))

        # Chuỗi dài quá 500 ký tự
        c9 = copy.deepcopy(self.examples["product.upserted"])
        c9["data"]["description"] = "A" * 501
        bad_cases.append(("text_too_long", c9))

        # Email lọt vào chuỗi văn bản
        c10 = copy.deepcopy(self.examples["customer.upserted"])
        c10["data"]["display_name"] = "Khách user@example.com"
        bad_cases.append(("email_in_text", c10))

        # order.created: total lệch với tổng dòng hàng + phí ship
        c11 = copy.deepcopy(self.examples["order.created"])
        c11["data"]["total"] += 1000
        bad_cases.append(("mismatched_order_total", c11))

        # order.created: promised_delivery_by không sau ordered_at
        c12 = copy.deepcopy(self.examples["order.created"])
        c12["data"]["promised_delivery_by"] = c12["data"]["ordered_at"]
        bad_cases.append(("promised_not_after_ordered", c12))

        # order.created: currency khác VND, payment_method lạ
        c13 = copy.deepcopy(self.examples["order.created"])
        c13["data"]["currency"] = "USD"
        bad_cases.append(("wrong_currency", c13))

        c14 = copy.deepcopy(self.examples["order.created"])
        c14["data"]["payment_method"] = "crypto"
        bad_cases.append(("wrong_payment_method", c14))

        # order.status_changed: trạng thái ngoài danh sách
        c15 = copy.deepcopy(self.examples["order.status_changed"])
        c15["data"]["status"] = "returned"
        bad_cases.append(("invalid_order_status", c15))

        # shipment.updated: số điện thoại shipper chưa che hoặc quá 3 lần thử
        c16 = copy.deepcopy(self.examples["shipment.updated"])
        c16["data"]["shipper_phone_masked"] = "0903123418"
        bad_cases.append(("unmasked_shipper_phone", c16))

        c17 = copy.deepcopy(self.examples["shipment.updated"])
        c17["data"]["delivery_attempts"] = 4
        bad_cases.append(("attempts_gt_3", c17))

        # payment.updated: lệch nguồn và phương thức COD/trả trước
        c18 = copy.deepcopy(self.examples["payment.updated"])
        c18["source_system"] = "marketplace_sim"
        c18["data"]["method"] = "bank_transfer"
        bad_cases.append(("marketplace_sim_prepaid_payment", c18))

        c19 = copy.deepcopy(self.examples["payment.updated"])
        c19["source_system"] = "payment_sim"
        c19["data"]["method"] = "cod"
        bad_cases.append(("payment_sim_cod_payment", c19))

        # refund.updated: kênh lạ hoặc nguồn sai
        c20 = copy.deepcopy(self.examples["refund.updated"])
        c20["data"]["channel"] = "cash"
        bad_cases.append(("invalid_refund_channel", c20))

        c21 = copy.deepcopy(self.examples["refund.updated"])
        c21["source_system"] = "marketplace_sim"
        bad_cases.append(("wrong_refund_source", c21))

        # voucher.issued / voucher.requested: sai quy tắc mệnh giá và vai trò
        c22 = copy.deepcopy(self.examples["voucher.issued"])
        c22["data"]["voucher_type"] = "free_shipping"
        c22["data"]["value"] = 30000
        bad_cases.append(("free_shipping_nonzero_value", c22))

        c23 = copy.deepcopy(self.examples["voucher.requested"])
        c23["data"]["approved_by_role"] = "customer"
        bad_cases.append(("voucher_approved_by_customer", c23))

        c24 = copy.deepcopy(self.examples["voucher.requested"])
        c24["data"]["reason"] = "vip_gift"
        bad_cases.append(("voucher_wrong_reason", c24))

        for label, bad_event in bad_cases:
            with self.subTest(case=label):
                with self.assertRaises(ContractError):
                    validate_event(bad_event)


if __name__ == "__main__":
    unittest.main()
