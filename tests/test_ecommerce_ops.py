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
            return {"message": {"role": "assistant", "content": None, "tool_calls": calls}}
        return {"message": {"role": "assistant", "content": self.reply}}


import tempfile
from pathlib import Path

class TestEcommerceOps(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = BusinessStore(Path(self.temp.name) / "business.sqlite3")
        self.store.seed()
        self.catalog = Catalog()
        self.tools = BoundTools(
            self.store, self.catalog, "C-003",
            {"order_id": "O-301", "product_id": "P-103"},
            {"name": "test-runner", "provider": "test"}
        )

    def test_sop1_fake_delivery_attempt_lookup(self):
        """SOP 1: Shipper fake delivery attempt -> AI retrieves driver name, phone, and reassign flag."""
        shipment_data = self.tools("track_shipment", {"order_id": "O-301"})
        shipment = shipment_data["shipment"]

        self.assertEqual(shipment_data["order_id"], "O-301")
        self.assertEqual(shipment["carrier"], "SPX Express")
        self.assertEqual(shipment["status"], "delivery_failed_virtual")
        self.assertIn("0934.112.233", shipment["shipper"])
        self.assertIn("Nguyễn Văn Tuấn", shipment["shipper"])
        self.assertTrue(shipment["can_reassign_today"])

    def test_sop2_damaged_item_exchange_proposal(self):
        """SOP 2: Damaged item in transit -> AI checks warranty and generates 1-to-1 exchange proposal."""
        state = {
            "messages": [{"role": "user", "content": "Áo khoác đơn O-302 của mình bị kẹt khóa kéo YKK cứng ngắc không kéo được, shop bảo hành đổi 1-1 giúp mình với!"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {"order_id": "O-302", "product_id": "P-104"},
            "intent": "unknown", "next_worker": "supervisor", "subagent_history": [],
            "sentiment": "neutral", "strict_mode": False, "consecutive_ood_count": 0,
            "action_proposal": None, "requires_human": False, "human_reason": None
        }

        # Step 1: Supervisor routes to dispute agent
        routed_state = run_supervisor(state)
        self.assertEqual(routed_state["next_worker"], "dispute_agent")

        # Step 2: Dispute agent creates 1-to-1 proposal
        gateway = MockGateway(reply="Đã tạo đề xuất đổi mới 1-1.")
        processed_state = run_dispute_agent(routed_state, self.tools, gateway)

        self.assertTrue(processed_state["complete"])
        proposal = processed_state["action_proposal"]
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal["action"], "exchange_1to1")
        self.assertEqual(proposal["order_id"], "O-302")
        self.assertEqual(proposal["status"], "pending_staff_approval")
        self.assertIn("Đổi mới 1-1", processed_state["messages"][-1]["content"])

    def test_sop3_size_exchange_inventory_check(self):
        """SOP 3: Size exchange -> AI checks inventory and generates 2-way exchange proposal."""
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
            "action_proposal": None, "requires_human": False, "human_reason": None
        }

        routed_state = run_supervisor(state)
        self.assertEqual(routed_state["next_worker"], "dispute_agent")

        gateway = MockGateway(reply="Đã tạo đề xuất đổi size.")
        processed_state = run_dispute_agent(routed_state, self.tools, gateway)

        proposal = processed_state["action_proposal"]
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal["action"], "size_exchange")
        self.assertEqual(proposal["order_id"], "O-303")
        self.assertEqual(proposal["target_size"], "L")
        self.assertEqual(proposal["status"], "pending_staff_approval")

    def test_sop4_mega_sale_sorting_delay_voucher(self):
        """SOP 4: Sorting hub bottleneck (>48h delay) -> AI detects delay and provides 50K compensation voucher."""
        tools_c004 = BoundTools(
            self.store, self.catalog, "C-004",
            {"order_id": "O-304", "product_id": "P-401"},
            {"name": "test-runner", "provider": "test"}
        )
        shipment_data = tools_c004("track_shipment", {"order_id": "O-304"})
        shipment = shipment_data["shipment"]

        self.assertEqual(shipment["carrier"], "Giao Hàng Nhanh (GHN)")
        self.assertEqual(shipment["status"], "sorting_delayed")
        self.assertGreater(shipment["delayed_hours"], 48)
        self.assertIn("BN Mega SOC", shipment["current_location"])
        self.assertEqual(shipment["voucher_code"], "SALE50K-BN-SOC")

    def test_sop5_customer_extreme_rage_strict_mode(self):
        """SOP 5: Extreme rage / social boycott threat -> Strict mode de-escalation & red alert escalation."""
        state = {
            "messages": [{"role": "user", "content": "Shop làm ăn như lừa đảo, tôi sẽ bóc phốt lên TikTok cho sập tiệm!"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {}, "intent": "unknown", "next_worker": "supervisor", "subagent_history": [],
            "sentiment": "neutral", "strict_mode": False, "consecutive_ood_count": 0,
            "action_proposal": None, "requires_human": False, "human_reason": None
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
            "action_proposal": None, "requires_human": False, "human_reason": None
        }

        result = run_supervisor(state)
        self.assertTrue(result["requires_human"])
        self.assertEqual(result["next_worker"], "human_escalation")
        self.assertTrue(result["complete"])
        self.assertIn("nhân viên tư vấn", result["messages"][-1]["content"])


if __name__ == "__main__":
    unittest.main()
