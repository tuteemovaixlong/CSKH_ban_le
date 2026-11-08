"""Tests for real-world retail production tools (shipment tracking, inventory, human handoff)."""
import unittest
from pathlib import Path
import tempfile

from agent_protocol import validate_tool, ProtocolError
from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops_tools import BoundTools
from retailops_conversation import Catalog


class FakeAgent:
    def __init__(self, name="custom"):
        self.name = name
        self.model = name
        self.call_count = 0
        self.responses = []

    def inspect(self):
        return {"name": self.name, "digest": "fixture", "provider": "custom", "agent_protocol": "retailops-agent-v2"}

    def chat(self, messages, allow_tools, timeout):
        self.call_count += 1
        if self.responses:
            return self.responses.pop(0)
        return {
            "message": {"role": "assistant", "content": "Phản hồi mẫu."},
            "prompt_eval_count": 50,
            "eval_count": 25,
            "reported_cost_usd": 0.0
        }


class RetailProductionToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = BusinessStore(Path(self.temp.name) / 'business.sqlite3')
        self.store.seed()
        with self.store.connection() as db:
            db.execute(
                """INSERT INTO shipments (
                    shipment_id, order_id, source_system, external_shipment_id, carrier, tracking_code,
                    status, carrier_status_raw, current_area, estimated_delivery_at, delivered_at,
                    delivery_attempts, shipper_name, shipper_phone_masked, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    'shp_o101', 'O-101', 'marketplace_sim', 'EXT-SHP-101',
                    'Giao Hàng Tiết Kiệm (GHTK)', 'GHTK.VN.0918231',
                    'in_transit', 'transporting', 'Bưu cục Tân Bình, TP.HCM',
                    1794218400.0, None, 0, 'Nguyễn Văn Nam', '090****334', 1794132000.0,
                ),
            )
            db.execute(
                """INSERT INTO shipment_events (
                    shipment_event_id, shipment_id, status, carrier_status_raw,
                    hub_name, district, province, description, occurred_at, estimated_delivery_at, source_event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    'se_s101_1', 'shp_o101', 'picked_up', 'picked',
                    'Kho Shop', 'Cầu Giấy', 'Hà Nội', 'Đã lấy hàng tại shop', 1794110000.0, 1794218400.0, 'evt_s101_1',
                    'se_s101_2', 'shp_o101', 'in_transit', 'transporting',
                    'Bưu cục Tân Bình', 'Tân Bình', 'TP.HCM', 'Đang trung chuyển tới bưu cục phát', 1794132000.0, 1794218400.0, 'evt_s101_2',
                ),
            )
            db.execute(
                """INSERT INTO shipments (
                    shipment_id, order_id, source_system, external_shipment_id, carrier, tracking_code,
                    status, carrier_status_raw, current_area, estimated_delivery_at, delivered_at,
                    delivery_attempts, shipper_name, shipper_phone_masked, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    'shp_o102', 'O-102', 'marketplace_sim', 'EXT-SHP-102',
                    'Giao Hàng Nhanh (GHN)', 'GHN.VN.8839210',
                    'delivered', 'delivered', 'Quận 1, TP.HCM',
                    1794045600.0, 1794042900.0, 1, 'Trần Quốc Tuấn', '098****442', 1794042900.0,
                ),
            )
            db.execute(
                """INSERT INTO orders (
                    id, customer_id, product_id, name, variant, amount, status, version,
                    source_system, external_order_id, ordered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ('O-109', 'C-001', 'P-101', 'Áo thun Essential', 'Trắng / M', 299000, 'pending', 1, 'marketplace_sim', 'SIM-O-0109', 1794100000.0),
            )
        self.catalog = Catalog()
        self.identity = {'name': 'qwen3.5:4b', 'digest': 'abc', 'provider': 'custom'}
        conv = self.store.new_conversation('C-001')
        self.snapshot = {'id': conv['conversation_id'], 'order_id': 'O-101', 'product_id': 'P-001'}
        self.tools = BoundTools(self.store, self.catalog, 'C-001', self.snapshot, self.identity)

    def test_protocol_validates_new_tools(self):
        # Valid calls
        self.assertEqual(validate_tool('track_shipment', {'order_id': 'O-101'}), {'order_id': 'O-101'})
        self.assertEqual(validate_tool('check_inventory', {'product_id': 'P-001', 'size': 'L', 'color': 'den'}),
                         {'product_id': 'P-001', 'size': 'L', 'color': 'den'})
        self.assertEqual(validate_tool('request_human_support', {'reason': 'Can gap nhan vien'}),
                         {'reason': 'Can gap nhan vien'})

        # Invalid calls
        with self.assertRaises(ProtocolError):
            validate_tool('track_shipment', {'order_id': ''})
        with self.assertRaises(ProtocolError):
            validate_tool('check_inventory', {'product_id': 'P-001', 'size': 'L'})  # missing color
        with self.assertRaises(ProtocolError):
            validate_tool('request_human_support', {})  # missing reason

    def test_track_shipment_tool_execution(self):
        # Order O-101 (in-transit GHTK from DB shipments + shipment_events)
        res_101 = self.tools('track_shipment', {'order_id': 'O-101'})
        self.assertEqual(res_101['order_id'], 'O-101')
        self.assertIn('GHTK', res_101['shipment']['carrier'])
        self.assertEqual(res_101['shipment']['status'], 'in_transit')
        self.assertEqual(res_101['shipment']['carrier_status_raw'], 'transporting')
        self.assertEqual(res_101['shipment']['shipper_phone_masked'], '090****334')
        self.assertTrue(len(res_101['shipment']['events']) >= 2)
        self.assertEqual(self.tools.shipment, res_101['shipment'])

        # Order O-102 (delivered GHN)
        res_102 = self.tools('track_shipment', {'order_id': 'O-102'})
        self.assertEqual(res_102['order_id'], 'O-102')
        self.assertIn('GHN', res_102['shipment']['carrier'])
        self.assertEqual(res_102['shipment']['status'], 'delivered')

        # Order O-109 (no shipment row in DB -> returns shipment=None without fabricating)
        res_109 = self.tools('track_shipment', {'order_id': 'SIM-O-0109'})
        self.assertEqual(res_109['external_order_id'], 'SIM-O-0109')
        self.assertEqual(res_109['internal_order_id'], 'O-109')
        self.assertIsNone(res_109['shipment'])

    def test_check_inventory_tool_execution(self):
        # In stock
        res_in = self.tools('check_inventory', {'product_id': 'P-101', 'size': 'M', 'color': 'trang'})
        self.assertEqual(res_in['product_id'], 'P-101')
        self.assertTrue(res_in['in_stock'])
        self.assertEqual(res_in['stock'], 12)

        # Out of stock
        res_out = self.tools('check_inventory', {'product_id': 'P-101', 'size': 'XL', 'color': 'trang'})
        self.assertFalse(res_out['in_stock'])
        self.assertEqual(res_out['stock'], 0)

        # Non-existent product
        res_none = self.tools('check_inventory', {'product_id': 'P-999', 'size': 'M', 'color': 'trang'})
        self.assertEqual(res_none.get('error'), 'product_not_found')

    def test_request_human_support_tool_execution(self):
        res = self.tools('request_human_support', {'reason': 'Khach muon tra hang gap vi loi'})
        self.assertEqual(res['status'], 'escalated_to_human')
        self.assertNotIn('support_rep', res)
        self.assertNotIn('Mai Anh', str(res))
        self.assertTrue(res.get('case_id'))
        self.assertTrue(res.get('handoff_id'))
        self.assertEqual(self.tools.human_support, res)

    def test_application_integration_with_new_tools(self):
        custom = FakeAgent('custom')
        app = Application(self.store, {}, custom)
        cid = app.new_conversation('C-001', {})['conversation_id']

        # Script custom agent to call track_shipment
        custom.responses = [{
            'message': {
                'role': 'assistant',
                'content': '',
                'tool_calls': [{'function': {'name': 'track_shipment', 'arguments': {'order_id': 'O-101'}}}]
            }
        }, {
            'message': {
                'role': 'assistant',
                'content': 'Đơn hàng O-101 đang trên xe trung chuyển GHTK tới bưu cục Tân Bình nhé.'
            }
        }]

        result = app.chat('C-001', {'conversation_id': cid, 'text': 'Đơn O-101 đi đến đâu rồi?', 'request_id': 'a'*32})
        self.assertEqual(result['source'], 'llm_agent')
        self.assertIsNotNone(result.get('shipment'))
        self.assertEqual(result['shipment']['status'], 'in_transit')


if __name__ == '__main__':
    unittest.main()
