import asyncio
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


try:
    from retailops_mcp_server import app
    from retailops.workflow.mcp_client import RetailOpsMCPClient
except ImportError:
    import os
    sys.path.insert(0, os.getcwd())
    from retailops_mcp_server import app
    from retailops.workflow.mcp_client import RetailOpsMCPClient


class RetailOpsMCPProtocolTests(unittest.TestCase):
    """Tests for MCP Tools, Resources, Prompts, and Guardrails."""

    def test_all_tools_registered(self):
        tools = asyncio.run(app.list_tools())
        tool_names = {t.name for t in tools}
        expected_tools = {
            "track_shipment",
            "check_inventory",
            "search_knowledge",
            "get_order",
            "list_orders",
            "create_return_proposal",
            "calculate_voucher_discount",
            "estimate_shipping_fee",
            "request_human_support",
            "search_product_specs"
        }
        self.assertTrue(expected_tools.issubset(tool_names), f"Missing tools: {expected_tools - tool_names}")

    def test_all_resources_registered(self):
        resources = asyncio.run(app.list_resources())
        resource_uris = {str(r.uri) for r in resources}
        expected_resources = {
            "retailops://policies/warranty-90d",
            "retailops://policies/mega-soc-delay",
            "retailops://catalog/products"
        }
        self.assertTrue(expected_resources.issubset(resource_uris), f"Missing resources: {expected_resources - resource_uris}")

    def test_prompt_registered(self):
        prompts = asyncio.run(app.list_prompts())
        prompt_names = {p.name for p in prompts}
        self.assertIn("retail_copilot_assistant", prompt_names)

    def test_track_shipment_tool(self):
        # 1. Normal order
        res1 = asyncio.run(app.call_tool("track_shipment", {"order_id": "O-101"}))
        data1 = json.loads(res1.content[0].text)
        self.assertEqual(data1["order_id"], "O-101")
        self.assertIn("shipment", data1)
        self.assertEqual(data1["shipment"]["carrier"], "Giao Hàng Tiết Kiệm (GHTK)")

        # 2. Mega SOC delayed order (>48h)
        res2 = asyncio.run(app.call_tool("track_shipment", {"order_id": "O-304"}))
        data2 = json.loads(res2.content[0].text)
        self.assertTrue(data2["is_delayed_mega_soc"])
        self.assertEqual(data2["compensation_voucher"], "SALE50K-BN-SOC")

        # 3. Virtual delivery suspicion
        res3 = asyncio.run(app.call_tool("track_shipment", {"order_id": "O-301"}))
        data3 = json.loads(res3.content[0].text)
        self.assertTrue(data3["is_virtual_delivery_suspected"])

    def test_check_inventory_tool(self):
        # In-stock item
        res = asyncio.run(app.call_tool("check_inventory", {"product_id": "P-101", "size": "M"}))
        data = json.loads(res.content[0].text)
        self.assertEqual(data["product_id"], "P-101")
        self.assertEqual(data["size"], "M")
        self.assertTrue(data["in_stock"])
        self.assertGreater(data["available_qty"], 0)

        # Out-of-stock size
        res_oos = asyncio.run(app.call_tool("check_inventory", {"product_id": "P-101", "size": "XL"}))
        data_oos = json.loads(res_oos.content[0].text)
        self.assertEqual(data_oos["available_qty"], 0)
        self.assertFalse(data_oos["in_stock"])

    def test_calculate_voucher_discount(self):
        # Mega SOC delay voucher (SALE50K-BN-SOC)
        res = asyncio.run(app.call_tool("calculate_voucher_discount", {"order_amount": 299000, "voucher_code": "SALE50K-BN-SOC"}))
        data = json.loads(res.content[0].text)
        self.assertTrue(data["is_valid"])
        self.assertEqual(data["discount_amount"], 50000)
        self.assertEqual(data["final_amount"], 249000)

        # Percentage voucher (RETAIL10)
        res_perc = asyncio.run(app.call_tool("calculate_voucher_discount", {"order_amount": 300000, "voucher_code": "RETAIL10"}))
        data_perc = json.loads(res_perc.content[0].text)
        self.assertTrue(data_perc["is_valid"])
        self.assertEqual(data_perc["discount_amount"], 30000)
        self.assertEqual(data_perc["final_amount"], 270000)

        # Non-existent voucher
        res_invalid = asyncio.run(app.call_tool("calculate_voucher_discount", {"order_amount": 100000, "voucher_code": "INVALID_CODE"}))
        data_invalid = json.loads(res_invalid.content[0].text)
        self.assertFalse(data_invalid["is_valid"])
        self.assertEqual(data_invalid["discount_amount"], 0)

    def test_create_return_proposal(self):
        res = asyncio.run(app.call_tool("create_return_proposal", {
            "order_id": "O-102",
            "reason": "Rộng eo, cần đổi sang size M",
            "solution_type": "exchange"
        }))
        data = json.loads(res.content[0].text)
        self.assertEqual(data["status"], "proposal_created")
        self.assertEqual(data["order_id"], "O-102")
        self.assertTrue(data["proposal_id"].startswith("RET-"))
        self.assertTrue(data["door_to_door_service"])
        self.assertIn("100% Free", data["shipping_fee_responsible"])

    def test_estimate_shipping_fee(self):
        # Hanoi standard
        res_hn = asyncio.run(app.call_tool("estimate_shipping_fee", {"destination_province": "Hà Nội", "weight_grams": 500}))
        data_hn = json.loads(res_hn.content[0].text)
        self.assertEqual(data_hn["standard_delivery"]["fee"], 22000)

        # Provincial address
        res_prov = asyncio.run(app.call_tool("estimate_shipping_fee", {"destination_province": "Lạng Sơn", "weight_grams": 500}))
        data_prov = json.loads(res_prov.content[0].text)
        self.assertEqual(data_prov["standard_delivery"]["fee"], 35000)

    def test_request_human_support(self):
        res = asyncio.run(app.call_tool("request_human_support", {
            "reason": "Shipper có thái độ không đúng mực",
            "urgency": "vip"
        }))
        data = json.loads(res.content[0].text)
        self.assertEqual(data["status"], "escalated_to_human")
        self.assertEqual(data["urgency"], "vip")
        self.assertIn("VIP", data["queue"])
        self.assertTrue(data["ticket_id"].startswith("CSKH-"))

    def test_search_product_specs_and_guardrail(self):
        # 1. Legitimate technical specs query
        res_valid = asyncio.run(app.call_tool("search_product_specs", {"query": "áo thun cotton 250 gsm giặt nhiệt độ bao nhiêu"}))
        data_valid = json.loads(res_valid.content[0].text)
        self.assertEqual(data_valid["status"], "success")
        self.assertIn("technical_specifications", data_valid)

        # 2. Guardrail Trigger: Policy / Return query attempted on external specs search
        res_blocked = asyncio.run(app.call_tool("search_product_specs", {"query": "chính sách bồi thường khi shipper làm mất hàng"}))
        data_blocked = json.loads(res_blocked.content[0].text)
        self.assertEqual(data_blocked["status"], "blocked_by_guardrail")
        self.assertTrue(data_blocked["is_policy_query"])
        self.assertEqual(data_blocked["suggested_tool"], "search_knowledge")

    def test_mcp_resources_reading(self):
        # Read warranty policy
        w_res = asyncio.run(app.read_resource("retailops://policies/warranty-90d"))
        self.assertTrue(len(w_res[0].content) > 100)
        self.assertIn("bảo hành", w_res[0].content.lower())

        # Read mega soc delay policy
        m_res = asyncio.run(app.read_resource("retailops://policies/mega-soc-delay"))
        self.assertTrue(len(m_res[0].content) > 100)
        self.assertIn("mega soc", m_res[0].content.lower())

        # Read catalog
        c_res = asyncio.run(app.read_resource("retailops://catalog/products"))
        cat_json = json.loads(c_res[0].content)
        self.assertIn("products", cat_json)
        self.assertTrue(len(cat_json["products"]) > 0)

    def test_mcp_client_adapter(self):
        client = RetailOpsMCPClient()
        tools = client.list_tools_sync()
        self.assertGreaterEqual(len(tools), 10)

        res = client.call_tool_sync("track_shipment", {"order_id": "O-101"})
        self.assertEqual(res.get("order_id"), "O-101")

        policy_text = client.read_resource_sync("retailops://policies/warranty-90d")
        self.assertIn("bảo hành", policy_text.lower())

    def test_fallback_mcp_server_jsonrpc_protocol(self):
        from retailops_mcp_server import FallbackMCPServer
        server = FallbackMCPServer("Test-RetailOps-Engine")

        @server.tool()
        def sample_tool(order_id: str, count: int = 1) -> dict:
            """Sample tool doc."""
            return {"received_order": order_id, "count": count}

        @server.resource("retailops://test/resource")
        def sample_res():
            """Sample resource doc."""
            return json.dumps({"status": "ok"})

        @server.prompt()
        def sample_prompt(topic: str = "general"):
            """Sample prompt doc."""
            return f"Prompt for {topic}"

        # 1. initialize
        init_res = asyncio.run(server.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"}))
        self.assertEqual(init_res["id"], 1)
        self.assertEqual(init_res["result"]["serverInfo"]["name"], "Test-RetailOps-Engine")

        # 2. ping
        ping_res = asyncio.run(server.handle_jsonrpc({"jsonrpc": "2.0", "id": 2, "method": "ping"}))
        self.assertEqual(ping_res["result"], {})

        # 3. tools/list
        tools_res = asyncio.run(server.handle_jsonrpc({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}))
        tools = tools_res["result"]["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "sample_tool")
        self.assertIn("order_id", tools[0]["inputSchema"]["properties"])

        # 4. tools/call
        call_res = asyncio.run(server.handle_jsonrpc({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "sample_tool", "arguments": {"order_id": "O-999", "count": 3}}
        }))
        call_payload = json.loads(call_res["result"]["content"][0]["text"])
        self.assertEqual(call_payload["received_order"], "O-999")
        self.assertEqual(call_payload["count"], 3)

        # 5. resources/list & read
        res_list = asyncio.run(server.handle_jsonrpc({"jsonrpc": "2.0", "id": 5, "method": "resources/list"}))
        self.assertEqual(len(res_list["result"]["resources"]), 1)

        res_read = asyncio.run(server.handle_jsonrpc({
            "jsonrpc": "2.0",
            "id": 6,
            "method": "resources/read",
            "params": {"uri": "retailops://test/resource"}
        }))
        self.assertIn("ok", res_read["result"]["contents"][0]["text"])

        # 6. prompts/list & get
        p_list = asyncio.run(server.handle_jsonrpc({"jsonrpc": "2.0", "id": 7, "method": "prompts/list"}))
        self.assertEqual(len(p_list["result"]["prompts"]), 1)

        p_get = asyncio.run(server.handle_jsonrpc({
            "jsonrpc": "2.0",
            "id": 8,
            "method": "prompts/get",
            "params": {"name": "sample_prompt", "arguments": {"topic": "returns"}}
        }))
        self.assertIn("returns", p_get["result"]["messages"][0]["content"]["text"])

    def test_fallback_mcp_sse_http_server(self):
        from retailops_mcp_server import FallbackMCPServer
        import threading, time, urllib.request

        server = FallbackMCPServer("HTTP-Test-Server")
        @server.tool()
        def ping_tool(msg: str = "pong") -> dict:
            return {"echo": msg}

        test_port = 18099
        t = threading.Thread(target=lambda: server.run(transport="sse", host="127.0.0.1", port=test_port), daemon=True)
        t.start()
        time.sleep(0.3)

        try:
            # 1. GET /health
            with urllib.request.urlopen(f"http://127.0.0.1:{test_port}/health") as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["status"], "healthy")
                self.assertEqual(data["server"], "HTTP-Test-Server")

            # 2. POST /messages/
            req_bytes = json.dumps({
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": "ping_tool", "arguments": {"msg": "hello-mcp"}}
            }).encode("utf-8")
            req = urllib.request.Request(
                f"http://127.0.0.1:{test_port}/messages/",
                data=req_bytes,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req) as resp:
                call_res = json.loads(resp.read().decode("utf-8"))
                echo_text = json.loads(call_res["result"]["content"][0]["text"])
                self.assertEqual(echo_text["echo"], "hello-mcp")
        finally:
            pass


if __name__ == "__main__":
    unittest.main()
