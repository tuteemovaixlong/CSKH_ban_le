"""Tests for Phase R1 W6.1b-2 Item 2: role-aware recipient read, AI zero-PII boundary, and audited reveal."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_protocol import PROTOCOL
from retailops.business.application import Application
from retailops.business.permissions import ROLE_PERMISSIONS
from retailops.core import ApiError
from retailops.http.routes import api_result
from retailops.identity.contracts import RequestContext
from retailops.identity.persistent import PersistentSessions
from retailops.integration.ingest import IntegrationIngestService
from retailops.workflow.case_assist import CaseAssistBoundTools
from retailops_tools import BoundTools


class _CapturingFakeGateway:
    """Fake model gateway capturing every message payload sent to LLM."""

    def __init__(self, steps: list[dict]):
        self.steps = list(steps)
        self.calls: list[dict] = []

    def inspect(self):
        return {
            "name": "fake-w61b2-item2-model",
            "digest": "sha256:fakew61b2i2",
            "provider": "custom_api",
            "ollama_version": None,
            "agent_protocol": PROTOCOL,
        }

    def chat(self, messages, allow_tools, timeout):
        self.calls.append(
            {
                "method": "chat",
                "messages": json.loads(json.dumps(messages, ensure_ascii=False)),
                "allow_tools": allow_tools,
            }
        )
        msg = self.steps.pop(0)
        return {
            "message": msg,
            "done_reason": "stop",
            "model": "fake-w61b2-item2-model",
            "prompt_eval_count": 100,
            "eval_count": 40,
            "reported_cost_usd": None,
            "reasoning": None,
        }

    def chat_profile(self, messages, allow_tools, timeout, *, system_prompt, tool_schemas):
        self.calls.append(
            {
                "method": "chat_profile",
                "messages": json.loads(json.dumps(messages, ensure_ascii=False)),
                "system_prompt": system_prompt,
                "allow_tools": allow_tools,
            }
        )
        msg = self.steps.pop(0)
        return {
            "message": msg,
            "done_reason": "stop",
            "model": "fake-w61b2-item2-model",
            "prompt_eval_count": 100,
            "eval_count": 40,
            "reported_cost_usd": None,
            "reasoning": None,
        }


def _ctx(
    role: str,
    principal_id: str,
    *,
    customer_id: str,
    tenant_id: str = "shop-a",
    display_name: str = "Test Actor",
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


def _order_created_event(
    *,
    event_id: str,
    ext_order_id: str,
    ext_customer_id: str,
    name: str,
    phone: str,
    address_line: str,
) -> dict:
    return {
        "contract": "retailops-integration-v2",
        "event_id": event_id,
        "event_type": "order.created",
        "source_system": "marketplace_sim",
        "merchant_id": "MERCHANT-SIM-001",
        "occurred_at": "2026-10-20T09:00:00+07:00",
        "sequence": 1,
        "data": {
            "external_order_id": ext_order_id,
            "external_customer_id": ext_customer_id,
            "ordered_at": "2026-10-20T09:00:00+07:00",
            "promised_delivery_by": "2026-10-22T09:00:00+07:00",
            "payment_method": "cod",
            "shipping_fee": 20000,
            "total": 320000,
            "currency": "VND",
            "recipient": {
                "name": name,
                "phone": phone,
                "address_line": address_line,
                "ward": "Phường Võ Thị Sáu",
                "district": "Quận 3",
                "province": "TP. Hồ Chí Minh",
            },
            "items": [
                {
                    "external_product_id": "P-101",
                    "sku": "SKU-I2-101",
                    "title": "Áo sơ mi Oxford",
                    "variant_name": "Xanh / M",
                    "quantity": 1,
                    "unit_price": 300000,
                }
            ],
        },
    }


class RecipientRoleAccessItem2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="r1-w61b2-item2-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.digest_file = self.root / "digest_key"
        self.digest_file.write_bytes(b"w61b2-item2-digest-secret-32byte!")
        self.recipient_file = self.root / "recipient_key_v1"
        self.recipient_file.write_bytes(b"w61b2-item2-recipient-key-32byte!")

        self.env_patcher = patch.dict(
            os.environ,
            {
                "RETAILOPS_EVENT_DIGEST_KEY_FILE": str(self.digest_file),
                "RETAILOPS_RECIPIENT_KEY_FILE": str(self.recipient_file),
            },
            clear=False,
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

        self.sessions = PersistentSessions(self.root / "persistent")
        self.store_a = self.sessions.provision_tenant("shop-a", "Shop A", seed_demo=False)
        self.store_b = self.sessions.provision_tenant("shop-b", "Shop B", seed_demo=False)
        self.store_a.seed_catalog()
        self.store_b.seed_catalog()

        self.svc = IntegrationIngestService(self.sessions)

        self.name_a = "Lê Hoàng Khánh Vy"
        self.phone_a = "0905678123"
        self.addr_a = "77B Trần Quốc Thảo, Tầng 4"
        res_a = self.svc.ingest_event(
            json.dumps(
                _order_created_event(
                    event_id="evt:i2:ordA:1",
                    ext_order_id="SIM-ORD-A-100",
                    ext_customer_id="SIM-CUST-A",
                    name=self.name_a,
                    phone=self.phone_a,
                    address_line=self.addr_a,
                ),
                ensure_ascii=False,
            ).encode("utf-8"),
            tenant_id="shop-a",
        )
        self.oid_a = res_a.order_id
        with self.store_a.connection() as db:
            self.cid_a = db.execute("SELECT customer_id FROM orders WHERE id=?", (self.oid_a,)).fetchone()[
                "customer_id"
            ]

        self.name_b = "Đặng Quốc Bảo"
        self.phone_b = "0912345987"
        self.addr_b = "199 Điện Biên Phủ, P.15"
        res_b = self.svc.ingest_event(
            json.dumps(
                _order_created_event(
                    event_id="evt:i2:ordB:1",
                    ext_order_id="SIM-ORD-B-200",
                    ext_customer_id="SIM-CUST-B",
                    name=self.name_b,
                    phone=self.phone_b,
                    address_line=self.addr_b,
                ),
                ensure_ascii=False,
            ).encode("utf-8"),
            tenant_id="shop-a",
        )
        self.oid_b = res_b.order_id
        with self.store_a.connection() as db:
            self.cid_b = db.execute("SELECT customer_id FROM orders WHERE id=?", (self.oid_b,)).fetchone()[
                "customer_id"
            ]

        # Ingest shipment on order A so track_shipment can also be scanned
        self.svc.ingest_event(
            json.dumps(
                {
                    "contract": "retailops-integration-v2",
                    "event_id": "evt:i2:shipA:1",
                    "event_type": "shipment.updated",
                    "source_system": "marketplace_sim",
                    "merchant_id": "MERCHANT-SIM-001",
                    "occurred_at": "2026-10-20T12:00:00+07:00",
                    "sequence": 1,
                    "data": {
                        "external_shipment_id": "SHIP-I2-A-1",
                        "external_order_id": "SIM-ORD-A-100",
                        "carrier": "GHN",
                        "tracking_code": "GHN888999",
                        "carrier_status_raw": "delivering",
                        "hub_name": "Kho Quận 3",
                        "district": "Quận 3",
                        "province": "TP. Hồ Chí Minh",
                        "description": "Đang giao hàng cho khách",
                        "fail_reason": None,
                        "shipper_name": "Nguyễn Shipper",
                        "shipper_phone_masked": "098****111",
                        "estimated_delivery_at": "2026-10-21T18:00:00+07:00",
                        "delivery_attempts": 1,
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            tenant_id="shop-a",
        )

    def _make_app(self, store, *, tenant_id: str = "shop-a", infer=None) -> Application:
        app = Application(store, {}, infer=infer, tenant_id=tenant_id)
        app.identity_store = self.sessions.control
        return app

    def test_all_ai_tools_and_fake_gateway_payloads_never_contain_plaintext_recipient(self) -> None:
        forbidden = [
            self.name_a,
            self.phone_a,
            self.addr_a,
            "Trần Quốc Thảo",
            "r1gcm1:",
        ]

        # 1. Scan every customer BoundTools output directly
        app_plain = self._make_app(self.store_a)
        created_conv = self.store_a.new_conversation(self.cid_a, "custom")
        conv = self.store_a.conversation(self.cid_a, created_conv["conversation_id"])
        bt = BoundTools(
            self.store_a,
            app_plain.catalog,
            self.cid_a,
            conv,
            {"customer_id": self.cid_a},
            user_text=f"Kiểm tra đơn {self.oid_a}",
        )
        tool_outputs = {
            "list_orders": bt("list_orders", {}),
            "get_order": bt("get_order", {"order_id": self.oid_a}),
            "track_shipment": bt("track_shipment", {"order_id": self.oid_a}),
            "search_products": bt("search_products", {"query": "Oxford"}),
            "search_knowledge": bt("search_knowledge", {"query": "đổi trả"}),
        }
        dumped_bt = json.dumps(tool_outputs, ensure_ascii=False)
        for needle in forbidden:
            self.assertNotIn(needle, dumped_bt)
        self.assertEqual(
            tool_outputs["get_order"]["order"]["recipient"],
            {
                "phone_masked": "0905.xxx.123",
                "ward": "Phường Võ Thị Sáu",
                "district": "Quận 3",
                "province": "TP. Hồ Chí Minh",
            },
        )

        # 2. Run full customer chat loop through _CapturingFakeGateway and scan all gateway payloads
        fake_gw = _CapturingFakeGateway(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "get_order",
                                "arguments": {"order_id": "SIM-ORD-A-100"},
                            },
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": "Số điện thoại người nhận đã được che bảo mật là 0905.xxx.123 tại Phường Võ Thị Sáu, Quận 3, TP. Hồ Chí Minh.",
                },
            ]
        )
        app_chat = self._make_app(self.store_a, infer=fake_gw)
        cust_ctx = _ctx("customer", "p_cust_a", customer_id=self.cid_a, tenant_id="shop-a")
        code, chat_res = api_result(
            app_chat,
            self.cid_a,
            "POST",
            "/api/chat",
            body={
                "conversation_id": conv["id"],
                "request_id": "req_item2_cust_chat_0001",
                "text": "Cho mình hỏi số điện thoại và địa chỉ người nhận đơn SIM-ORD-A-100?",
            },
            context=cust_ctx,
        )
        self.assertEqual(code, 200)
        self.assertIn("0905.xxx.123", chat_res["message"])
        gw_dump = json.dumps(fake_gw.calls, ensure_ascii=False)
        for needle in forbidden:
            self.assertNotIn(needle, gw_dump)
        self.assertIn("0905.xxx.123", gw_dump)

        # 3. Escalate case, run CaseAssistBoundTools + app.case_assist through fake gateway, scan all payloads
        conv = self.store_a.conversation(self.cid_a, conv["id"])
        self.store_a.remember(self.cid_a, conv, self.oid_a, "P-101")
        esc = self.store_a.request_human_handoff(
            self.cid_a,
            conv["id"],
            reason_code="customer_requested",
            comment="Cần kiểm tra đơn",
        )
        case_id = esc["case_id"]
        staff_actor = {"principal_id": "p_staff_1", "role": "staff", "tenant_id": "shop-a"}
        self.store_a.claim_case(case_id, staff_name="Staff One", actor=staff_actor)

        cabt = CaseAssistBoundTools(
            self.store_a,
            app_plain.catalog,
            case_id=case_id,
            customer_id=self.cid_a,
            conversation_id=conv["id"],
        )
        ca_outputs = {
            "get_case_transcript": cabt("get_case_transcript", {}),
            "list_case_orders": cabt("list_case_orders", {}),
            "get_case_order": cabt("get_case_order", {"order_id": self.oid_a}),
            "list_case_order_actions": cabt("list_case_order_actions", {}),
        }
        dumped_ca = json.dumps(ca_outputs, ensure_ascii=False)
        for needle in forbidden:
            self.assertNotIn(needle, dumped_ca)
        self.assertEqual(ca_outputs["get_case_order"]["order"]["recipient"]["phone_masked"], "0905.xxx.123")

        ca_gw = _CapturingFakeGateway(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "ca_1", "function": {"name": "get_case_transcript", "arguments": {}}},
                        {
                            "id": "ca_2",
                            "function": {"name": "get_case_order", "arguments": {"order_id": self.oid_a}},
                        },
                    ],
                },
                {
                    "role": "assistant",
                    "content": "Đơn SIM-ORD-A-100 giao về Quận 3, SĐT che 0905.xxx.123.",
                },
            ]
        )
        app_ca = self._make_app(self.store_a, infer=ca_gw)
        staff_ctx = _ctx("staff", "p_staff_1", customer_id="C-STAFF-1", tenant_id="shop-a")
        ca_code, _ = api_result(
            app_ca,
            "C-STAFF-1",
            "POST",
            f"/api/staff/cases/{case_id}/assist",
            body={
                "mode": "ask",
                "question": "Tóm tắt thông tin giao hàng của đơn trong ca này.",
                "provider_id": "custom",
                "request_id": "req_item2_case_assist_001",
            },
            context=staff_ctx,
        )
        self.assertEqual(ca_code, 200)
        ca_gw_dump = json.dumps(ca_gw.calls, ensure_ascii=False)
        for needle in forbidden:
            self.assertNotIn(needle, ca_gw_dump)

    def test_customer_isolation_staff_hold_enforcement_and_audited_reveal(self) -> None:
        app_a = self._make_app(self.store_a, tenant_id="shop-a")
        cust_a_ctx = _ctx("customer", "p_cust_a", customer_id=self.cid_a, tenant_id="shop-a")
        cust_b_ctx = _ctx("customer", "p_cust_b", customer_id=self.cid_b, tenant_id="shop-a")

        # Customer A views own order detail -> sees decrypted recipient
        code_own, own_res = api_result(
            app_a, self.cid_a, "GET", f"/api/orders/{self.oid_a}", context=cust_a_ctx
        )
        self.assertEqual(code_own, 200)
        self.assertEqual(own_res["order"]["recipient"]["name"], self.name_a)
        self.assertEqual(own_res["order"]["recipient"]["phone"], self.phone_a)
        self.assertEqual(own_res["order"]["recipient"]["address_line"], self.addr_a)

        # Customer A CANNOT view Customer B's order even when guessing exact external_order_id or internal_order_id
        for target_id in (self.oid_b, "SIM-ORD-B-200"):
            with self.assertRaises(ApiError) as err_cross_cust:
                api_result(app_a, self.cid_a, "GET", f"/api/orders/{target_id}", context=cust_a_ctx)
            self.assertEqual(err_cross_cust.exception.status, 404)

        # Customer CANNOT call reveal-recipient endpoint -> 403
        with self.assertRaises(ApiError) as err_cust_rev:
            api_result(
                app_a,
                self.cid_a,
                "POST",
                f"/api/staff/orders/{self.oid_a}/reveal-recipient",
                body={"reason": "Khách tự gọi"},
                context=cust_a_ctx,
            )
        self.assertEqual(err_cust_rev.exception.status, 403)

        # Manager GET /api/orders returns masked only, NOT decrypted recipient
        mgr_a_ctx = _ctx("manager", "p_mgr_a", customer_id="C-MGR-A", tenant_id="shop-a")
        _, mgr_orders = api_result(app_a, "C-MGR-A", "GET", "/api/orders", context=mgr_a_ctx)
        mgr_ord_a = next(o for o in mgr_orders["orders"] if o["id"] == self.oid_a)
        self.assertNotIn("recipient", mgr_ord_a)
        self.assertEqual(mgr_ord_a["recipient_masked"]["phone_masked"], "0905.xxx.123")

        # Create an open escalated case for Customer A linked to oid_a, initially unclaimed (status='waiting')
        created_conv_a = self.store_a.new_conversation(self.cid_a, "custom")
        conv_a = self.store_a.conversation(self.cid_a, created_conv_a["conversation_id"])
        self.store_a.remember(self.cid_a, conv_a, self.oid_a, "P-101")
        esc_a = self.store_a.request_human_handoff(
            self.cid_a,
            conv_a["id"],
            reason_code="customer_requested",
            comment="Hỗ trợ giao hàng",
        )
        case_a = esc_a["case_id"]

        staff1_ctx = _ctx("staff", "p_staff_1", customer_id="C-ST-1", tenant_id="shop-a")
        staff2_ctx = _ctx("staff", "p_staff_2", customer_id="C-ST-2", tenant_id="shop-a")

        # Unheld Staff receives 403
        with self.assertRaises(ApiError) as err_unheld:
            api_result(
                app_a,
                "C-ST-1",
                "POST",
                f"/api/staff/orders/{self.oid_a}/reveal-recipient",
                body={"reason": "Liên hệ hãng vận chuyển", "case_id": case_a},
                context=staff1_ctx,
            )
        self.assertEqual(err_unheld.exception.status, 403)

        # Staff 1 claims case_a
        api_result(app_a, "C-ST-1", "POST", f"/api/staff/cases/{case_a}/claim", body={}, context=staff1_ctx)

        # Staff 2 (not holding case_a) receives 403
        with self.assertRaises(ApiError) as err_other_staff:
            api_result(
                app_a,
                "C-ST-2",
                "POST",
                f"/api/staff/orders/{self.oid_a}/reveal-recipient",
                body={"reason": "Xem thử", "case_id": case_a},
                context=staff2_ctx,
            )
        self.assertEqual(err_other_staff.exception.status, 403)

        # Staff 1 holding case_a linked to oid_a CANNOT reveal oid_b (unlinked order) -> 403
        with self.assertRaises(ApiError) as err_unlinked_order:
            api_result(
                app_a,
                "C-ST-1",
                "POST",
                f"/api/staff/orders/{self.oid_b}/reveal-recipient",
                body={"reason": "Xem đơn khách B"},
                context=staff1_ctx,
            )
        self.assertEqual(err_unlinked_order.exception.status, 403)

        # Staff 1 missing/blank reason -> 400
        with self.assertRaises(ApiError) as err_blank_reason:
            api_result(
                app_a,
                "C-ST-1",
                "POST",
                f"/api/staff/orders/{self.oid_a}/reveal-recipient",
                body={"reason": "   ", "case_id": case_a},
                context=staff1_ctx,
            )
        self.assertEqual(err_blank_reason.exception.status, 400)

        # Other-store Manager (shop-b) denied 403 on shop-a
        mgr_b_ctx = _ctx("manager", "p_mgr_b", customer_id="C-MGR-B", tenant_id="shop-b")
        with self.assertRaises(ApiError) as err_cross_mgr:
            api_result(
                app_a,
                "C-MGR-B",
                "POST",
                f"/api/staff/orders/{self.oid_a}/reveal-recipient",
                body={"reason": "Quản lý cửa hàng khác"},
                context=mgr_b_ctx,
            )
        self.assertEqual(err_cross_mgr.exception.status, 403)

        # Zero audit rows for recipient.reveal so far
        with self.sessions.control.connection() as id_db:
            cnt0 = id_db.execute(
                "SELECT COUNT(*) AS c FROM admin_audit_log WHERE action='recipient.reveal'"
            ).fetchone()["c"]
        self.assertEqual(cnt0, 0)

        # Staff 1 holding case_a reveals oid_a with reason -> 200 + exactly 1 audit row
        code_rev1, rev1 = api_result(
            app_a,
            "C-ST-1",
            "POST",
            f"/api/staff/orders/{self.oid_a}/reveal-recipient",
            body={"reason": "Xác minh địa chỉ giao lại với GHN", "case_id": case_a},
            context=staff1_ctx,
        )
        self.assertEqual(code_rev1, 200)
        self.assertTrue(rev1["audited"])
        self.assertEqual(rev1["recipient"]["name"], self.name_a)
        self.assertEqual(rev1["recipient"]["phone"], self.phone_a)
        self.assertEqual(rev1["recipient"]["address_line"], self.addr_a)

        # Same-tenant Manager reveals oid_b without holding a case -> 200 + 2nd audit row
        code_rev2, rev2 = api_result(
            app_a,
            "C-MGR-A",
            "POST",
            f"/api/staff/orders/{self.oid_b}/reveal-recipient",
            body={"reason": "Đối soát khiếu nại vận chuyển cấp quản lý"},
            context=mgr_a_ctx,
        )
        self.assertEqual(code_rev2, 200)
        self.assertEqual(rev2["recipient"]["name"], self.name_b)
        self.assertEqual(rev2["recipient"]["phone"], self.phone_b)

        with self.sessions.control.connection() as id_db:
            audit_rows = [
                dict(r)
                for r in id_db.execute(
                    "SELECT * FROM admin_audit_log WHERE action='recipient.reveal' ORDER BY id ASC"
                ).fetchall()
            ]
        self.assertEqual(len(audit_rows), 2)
        self.assertEqual(audit_rows[0]["actor_principal_id"], "p_staff_1")
        self.assertEqual(audit_rows[0]["actor_role"], "staff")
        self.assertEqual(audit_rows[0]["target_membership_id"], f"order:{self.oid_a}")
        self.assertEqual(audit_rows[0]["reason"], "Xác minh địa chỉ giao lại với GHN")
        self.assertEqual(audit_rows[1]["actor_principal_id"], "p_mgr_a")
        self.assertEqual(audit_rows[1]["actor_role"], "manager")
        self.assertEqual(audit_rows[1]["target_membership_id"], f"order:{self.oid_b}")

        # Audit log itself never contains decrypted recipient PII
        audit_dump = json.dumps(audit_rows, ensure_ascii=False)
        for needle in (self.name_a, self.phone_a, self.addr_a, self.name_b, self.phone_b, self.addr_b):
            self.assertNotIn(needle, audit_dump)


if __name__ == "__main__":
    unittest.main()
