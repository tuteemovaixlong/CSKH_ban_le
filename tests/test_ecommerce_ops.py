"""Automated End-to-End Test Suite for E-Commerce Ops Copilot 2026 (6 SOPs).
Verifies logistics telemetry, warranty exchange 1-1, size exchange, mega sale voucher,
sentiment guardrails, and human escalation.
"""
import unittest
from retailops_tools import BoundTools
from retailops.business.store import BusinessStore
from retailops_conversation import Catalog
from retailops.workflow.supervisor import run_supervisor
from retailops.workflow.subagents.dispute_agent import run_dispute_agent
from retailops.workflow.subagents.order_agent import run_order_agent


class MockGateway:
    def __init__(self, reply="", tool_calls=None):
        self.reply = reply
        self.tool_calls = tool_calls or []

    def chat(self, messages, tools_allowed=True, timeout=30):
        if tools_allowed and self.tool_calls:
            calls = self.tool_calls
            self.tool_calls = []
            return {"message": {"role": "assistant", "content": "", "tool_calls": calls}}
        return {"message": {"role": "assistant", "content": self.reply}}


import tempfile
from pathlib import Path

class TestEcommerceOps(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = BusinessStore(Path(self.temp.name) / "business.sqlite3")
        self.store.seed()
        now_ts = self.store._now()
        with self.store.connection() as db:
            db.execute(
                """INSERT INTO shipments (
                    shipment_id, order_id, source_system, external_shipment_id, carrier, tracking_code,
                    status, carrier_status_raw, current_area, estimated_delivery_at, delivered_at,
                    delivery_attempts, shipper_name, shipper_phone_masked, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "shp_o301", "O-301", "marketplace_sim", "EXT-SHP-301",
                    "SPX Express", "SPX.VN.9928110",
                    "delivery_failed", "DELIVERY_FAIL", "Bưu cục Cầu Giấy 2, Hà Nội",
                    now_ts + 14400.0, None, 1,
                    "Nguyễn Văn Tuấn", "093****233", now_ts - 1800.0,
                ),
            )
            db.execute(
                """INSERT INTO shipment_events (
                    shipment_event_id, shipment_id, occurred_at, status, carrier_status_raw,
                    description, fail_reason, hub_name, district, province, estimated_delivery_at, source_event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "se_o301_1", "shp_o301", now_ts - 1800.0, "delivery_failed", "DELIVERY_FAIL",
                    "Giao hàng không thành công", "Không liên lạc được người nhận",
                    "Bưu cục Cầu Giấy 2", "Cầu Giấy", "Hà Nội", now_ts + 14400.0, "evt_o301_fail_1",
                ),
            )
            db.execute(
                "UPDATE orders SET status = 'shipping', promised_delivery_by = ? WHERE id = 'O-304'",
                (now_ts - 54.0 * 3600.0,),
            )
            db.execute(
                """INSERT INTO shipments (
                    shipment_id, order_id, source_system, external_shipment_id, carrier, tracking_code,
                    status, carrier_status_raw, current_area, estimated_delivery_at, delivered_at,
                    delivery_attempts, shipper_name, shipper_phone_masked, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "shp_o304", "O-304", "marketplace_sim", "EXT-SHP-304",
                    "Giao Hàng Nhanh (GHN)", "GHN.VN.8821990",
                    "in_transit", "congested_at_soc", "Kho Tổng BN Mega SOC, Bắc Ninh",
                    now_ts + 48.0 * 3600.0, None, 0,
                    None, None, now_ts - 3600.0,
                ),
            )
        self.catalog = Catalog()
        self.tools = BoundTools(
            self.store, self.catalog, "C-003",
            {"order_id": "O-301", "product_id": "P-103"},
            {"name": "test-runner", "provider": "test"}
        )

    def test_sop1_fake_delivery_attempt_lookup(self):
        """SOP 1: Shipper failed delivery attempt -> DB-backed shipment exposes masked driver phone and fail reason."""
        shipment_data = self.tools("track_shipment", {"order_id": "O-301"})
        shipment = shipment_data["shipment"]

        self.assertEqual(shipment_data["order_id"], "O-301")
        self.assertEqual(shipment["carrier"], "SPX Express")
        self.assertEqual(shipment["status"], "delivery_failed")
        self.assertEqual(shipment["carrier_status_raw"], "DELIVERY_FAIL")
        self.assertEqual(shipment["shipper_name"], "Nguyễn Văn Tuấn")
        self.assertEqual(shipment["shipper_phone_masked"], "093****233")
        self.assertNotIn("0934112233", str(shipment_data))
        self.assertEqual(shipment["delivery_attempts"], 1)
        self.assertIn("Không liên lạc", shipment["fail_reason"])

    def test_sop2_damaged_item_goes_to_the_model_with_server_tools(self):
        """SOP 2 (W3.2-D3/D7): a damaged-item complaint reaches the dispute worker, which lets the model read the
        order with the server tools and answer in its own words. No scripted 1-to-1 proposal exists any more."""
        state = {
            "messages": [{"role": "user", "content": "Áo khoác đơn O-302 của mình bị kẹt khóa kéo YKK cứng ngắc không kéo được, shop bảo hành đổi 1-1 giúp mình với!"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {"order_id": "O-302", "product_id": "P-104"},
            "intent": "unknown", "next_worker": "supervisor", "subagent_history": [],
            "sentiment": "neutral", "strict_mode": False, "consecutive_ood_count": 0,
            "requires_human": False, "human_reason": None
        }

        # Step 1: Supervisor routes to the dispute worker
        routed_state = run_supervisor(state)
        self.assertEqual(routed_state["next_worker"], "dispute_agent")

        # Step 2: the model reads the order through the server tool and writes the reply itself
        read_order = {"function": {"name": "get_order", "arguments": {"order_id": "O-302"}}}
        gateway = MockGateway(reply="Em rất tiếc về sự cố khóa kéo ạ. Em đã xem đơn O-302, anh/chị gửi ảnh lỗi để em báo CSKH nhé.",
                              tool_calls=[read_order])
        processed_state = run_dispute_agent(routed_state, self.tools, gateway)

        self.assertTrue(processed_state["complete"])
        self.assertEqual(processed_state["messages"][-1]["content"], gateway.reply)
        self.assertEqual([t["name"] for t in processed_state["trace"]["tools"]], ["get_order"])
        self.assertNotIn("action_proposal", processed_state)
        self.assertIsNone(self.tools.prepared_order_action)  # only prepare_order_action opens a form, and it was not called

    def test_sop3_size_exchange_reads_stock_from_the_server_and_prepares_the_target_variant(self):
        """SOP 3 (W3.2-D1/D5/D7): inventory comes from the server tool; the exchange is a general "other variant"
        request whose target is matched to a real variant of the product. Stock informs, it does not decide."""
        # 1. Direct tool check
        inv = self.tools("check_inventory", {"product_id": "P-203", "size": "L", "color": "Xanh Navy"})
        self.assertTrue(inv["in_stock"])
        self.assertGreaterEqual(inv["stock"], 1)

        # 2. Workflow check
        state = {
            "messages": [{"role": "user", "content": "Đơn O-303 mình mặc size M bị chật quá, muốn đổi size sang size L có còn hàng không shop?"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {"order_id": "O-303", "product_id": "P-203"},
            "intent": "unknown", "next_worker": "supervisor", "subagent_history": [],
            "sentiment": "neutral", "strict_mode": False, "consecutive_ood_count": 0,
            "requires_human": False, "human_reason": None
        }

        routed_state = run_supervisor(state)
        self.assertEqual(routed_state["next_worker"], "dispute_agent")

        prepare = {"function": {"name": "prepare_order_action", "arguments": {
            "order_id": "O-303", "action_type": "exchange", "target_variant": "size L"}}}
        gateway = MockGateway(reply="Size L còn hàng ạ, em đã mở form để anh/chị chọn lý do rồi bấm xác nhận.",
                              tool_calls=[prepare])
        tools_c004 = BoundTools(
            self.store, self.catalog, "C-004",
            {"order_id": "O-303", "product_id": "P-203"},
            {"name": "test-runner", "provider": "test"}
        )
        processed_state = run_dispute_agent(routed_state, tools_c004, gateway)

        self.assertEqual(processed_state["messages"][-1]["content"], gateway.reply)
        prepared = tools_c004.prepared_order_action
        self.assertEqual((prepared["order"]["id"], prepared["action_type"], prepared["exchange_kind"], prepared["target_variant_id"]),
                         ("O-303", "exchange", "other_variant", "P-203-L-Xanh_Navy"))
        self.assertNotIn("action_proposal", processed_state)

    def test_sop4_mega_sale_sorting_delay_voucher(self):
        """SOP 4: Sorting hub bottleneck (>48h delay) -> DB-backed shipment + read-time eligibility detects delay without unverified voucher."""
        tools_c004 = BoundTools(
            self.store, self.catalog, "C-004",
            {"order_id": "O-304", "product_id": "P-401"},
            {"name": "test-runner", "provider": "test"}
        )
        shipment_data = tools_c004("track_shipment", {"order_id": "O-304"})
        shipment = shipment_data["shipment"]

        self.assertEqual(shipment["carrier"], "Giao Hàng Nhanh (GHN)")
        self.assertEqual(shipment["status"], "in_transit")
        self.assertEqual(shipment["carrier_status_raw"], "congested_at_soc")
        self.assertIn("BN Mega SOC", shipment["current_area"])
        self.assertTrue(shipment_data["eligibility"]["is_late_vs_promised"])
        self.assertGreater(shipment_data["eligibility"]["late_by_hours"], 48)
        self.assertNotIn("voucher_code", shipment)

    def test_sop5_customer_extreme_rage_strict_mode(self):
        """SOP 5: Extreme rage / social boycott threat -> Strict mode de-escalation & red alert escalation."""
        state = {
            "messages": [{"role": "user", "content": "Shop làm ăn như lừa đảo, tôi sẽ bóc phốt lên TikTok cho sập tiệm!"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {}, "intent": "unknown", "next_worker": "supervisor", "subagent_history": [],
            "sentiment": "neutral", "strict_mode": False, "consecutive_ood_count": 0,
            "requires_human": False, "human_reason": None
        }

        result = run_supervisor(state)
        self.assertTrue(result["requires_human"])
        self.assertEqual(result["next_worker"], "human_escalation")
        self.assertIn("bóc phốt", result["human_reason"])
        self.assertTrue(result["complete"])
        self.assertIn("xin lỗi", result["messages"][-1]["content"].lower())

    def test_sop6_customer_requests_human_support(self):
        """SOP 6: Customer asks for human agent -> Handover to staff desk queue."""
        state = {
            "messages": [{"role": "user", "content": "Tôi muốn gặp người thật tư vấn, đừng trả lời tự động nữa."}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {}, "intent": "unknown", "next_worker": "supervisor", "subagent_history": [],
            "sentiment": "neutral", "strict_mode": False, "consecutive_ood_count": 0,
            "requires_human": False, "human_reason": None
        }

        result = run_supervisor(state)
        self.assertTrue(result["requires_human"])
        self.assertEqual(result["next_worker"], "human_escalation")
        self.assertTrue(result["complete"])
        self.assertIn("nhân viên tư vấn", result["messages"][-1]["content"])


if __name__ == "__main__":
    unittest.main()
