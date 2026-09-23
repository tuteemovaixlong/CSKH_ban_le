"""Unit tests for Store Manager CRUD, Product Catalog, and Operational KPIs."""
import tempfile
import unittest
from pathlib import Path
from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.http.routes import api_result
from retailops.core import ApiError

ROOT = Path(__file__).resolve().parents[1]


class TestManagerCRUD(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False)
        self.tmp.close()
        self.store = BusinessStore(self.tmp.name, create=True)
        self.store.seed()
        self.app = Application(self.store, {}, role='manager')

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_get_manager_products(self):
        status, res = api_result(self.app, 'C-001', 'GET', '/api/manager/products')
        self.assertEqual(status, 200)
        self.assertIn('products', res)
        self.assertGreaterEqual(res['count'], 8)
        p101 = next((p for p in res['products'] if p['id'] == 'P-101'), None)
        self.assertIsNotNone(p101)
        self.assertEqual(p101['name'], 'Áo thun Essential')

    def test_get_manager_kpis(self):
        status, res = api_result(self.app, 'C-001', 'GET', '/api/manager/kpis')
        self.assertEqual(status, 200)
        self.assertGreater(res['total_orders'], 0)
        self.assertIn('ai_resolution_rate', res)
        self.assertIn('avg_csat', res)
        self.assertIn('total_revenue', res)
        # When store has 0 conversations, AI resolution and escalation rate must be None, not 100.0% / 0.0%
        self.assertIsNone(res['ai_resolution_rate'])
        self.assertIsNone(res['escalation_rate'])

        # Now simulate 2 conversations, 1 with human handoff
        c1 = self.store.new_conversation('C-001', 'custom')['conversation_id']
        c2 = self.store.new_conversation('C-001', 'custom')['conversation_id']
        with self.store.connection(write=True) as db:
            db.execute("INSERT INTO conversation_feedback(conversation_id, customer_id, feedback_type, rating, reason_code, created_at) VALUES (?, 'C-001', 'human_handoff', NULL, 'customer_requested_human', 1001)", (c1,))
        status2, res2 = api_result(self.app, 'C-001', 'GET', '/api/manager/kpis')
        self.assertEqual(status2, 200)
        self.assertEqual(res2['escalation_rate'], 50.0)
        self.assertEqual(res2['ai_resolution_rate'], 50.0)

    def test_manager_create_product_validation(self):
        # 1. Missing price must raise 400 invalid_price
        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/products', {'id': 'P-550', 'name': 'Áo Không Giá'})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, 'invalid_price')

        # 2. Negative price must raise 400 invalid_price
        for bad_price in [-1000, -1, -0.5, "-500"]:
            with self.subTest(bad_price=bad_price):
                with self.assertRaises(ApiError) as ctx:
                    api_result(self.app, 'C-001', 'POST', '/api/manager/products', {'id': 'P-550', 'name': 'Áo Giá Âm', 'price': bad_price})
                self.assertEqual(ctx.exception.status, 400)
                self.assertEqual(ctx.exception.code, 'invalid_price')

        # 3. Boolean price must raise 400 invalid_price
        for bool_price in [True, False]:
            with self.subTest(bool_price=bool_price):
                with self.assertRaises(ApiError) as ctx:
                    api_result(self.app, 'C-001', 'POST', '/api/manager/products', {'id': 'P-550', 'name': 'Áo Giá Bool', 'price': bool_price})
                self.assertEqual(ctx.exception.status, 400)
                self.assertEqual(ctx.exception.code, 'invalid_price')

        # 4. Non-numeric, NaN, Infinity price must raise 400 invalid_price
        for non_num in ['abc', '123a', [], {}, None, float('nan'), float('inf'), float('-inf')]:
            with self.subTest(non_num=non_num):
                with self.assertRaises(ApiError) as ctx:
                    api_result(self.app, 'C-001', 'POST', '/api/manager/products', {'id': 'P-550', 'name': 'Áo Giá Chữ', 'price': non_num})
                self.assertEqual(ctx.exception.status, 400)
                self.assertEqual(ctx.exception.code, 'invalid_price')

        # 4b. NaN / Infinity in stock or warranty_days must raise 400
        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/products', {'id': 'P-550', 'name': 'Áo Lỗi Stock', 'price': 100000, 'stock': float('nan')})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, 'invalid_stock')

        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/products', {'id': 'P-550', 'name': 'Áo Lỗi Warranty', 'price': 100000, 'warranty_days': float('inf')})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, 'invalid_warranty_days')

        # 5. Minimal creation: UNKNOWN != ZERO (omitted optional stock, warranty, category, description must be None, not fabricated defaults)
        status, res = api_result(self.app, 'C-001', 'POST', '/api/manager/products', {'id': 'P-550', 'name': 'Áo Tối Giản', 'price': 150000})
        self.assertEqual(status, 201)
        prod = res['product']
        self.assertEqual(prod['price'], 150000)
        self.assertEqual(prod['variants'], [])
        self.assertIsNone(prod['stock'])
        self.assertIsNone(prod['warranty_days'])
        self.assertIsNone(prod['category'])
        self.assertIsNone(prod['description'])

        # 6. Update validations for price, stock, warranty (including NaN and Infinity)
        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/products/update', {'id': 'P-550', 'price': True})
        self.assertEqual(ctx.exception.code, 'invalid_price')

        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/products/update', {'id': 'P-550', 'price': 'không hợp lệ'})
        self.assertEqual(ctx.exception.code, 'invalid_price')

        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/products/update', {'id': 'P-550', 'price': float('nan')})
        self.assertEqual(ctx.exception.code, 'invalid_price')

        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/products/update', {'id': 'P-550', 'price': float('inf')})
        self.assertEqual(ctx.exception.code, 'invalid_price')

        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/products/update', {'id': 'P-550', 'stock': -5})
        self.assertEqual(ctx.exception.code, 'invalid_stock')

        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/products/update', {'id': 'P-550', 'stock': True})
        self.assertEqual(ctx.exception.code, 'invalid_stock')

        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/products/update', {'id': 'P-550', 'stock': float('nan')})
        self.assertEqual(ctx.exception.code, 'invalid_stock')

        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/products/update', {'id': 'P-550', 'warranty_days': -10})
        self.assertEqual(ctx.exception.code, 'invalid_warranty_days')

        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/products/update', {'id': 'P-550', 'warranty_days': float('inf')})
        self.assertEqual(ctx.exception.code, 'invalid_warranty_days')

        # Clean up
        api_result(self.app, 'C-001', 'POST', '/api/manager/products/delete', {'id': 'P-550'})

    def test_manager_crud_lifecycle(self):
        new_pid = 'P-999'
        # 1. Create product
        payload = {
            'id': new_pid,
            'name': 'Áo Sơ Mi Test Manager',
            'category': 'Áo sơ mi',
            'price': 399000,
            'stock': 50,
            'warranty_days': 60,
            'variants': ['Trắng · Size M', 'Đen · Size L']
        }
        status, res = api_result(self.app, 'C-001', 'POST', '/api/manager/products', payload)
        self.assertEqual(status, 201)
        self.assertEqual(res['product']['id'], new_pid)
        self.assertEqual(res['product']['price'], 399000)

        # 2. Verify exists in GET
        status, res = api_result(self.app, 'C-001', 'GET', '/api/manager/products')
        found = next((p for p in res['products'] if p['id'] == new_pid), None)
        self.assertIsNotNone(found)
        self.assertEqual(found['name'], 'Áo Sơ Mi Test Manager')

        # 3. Update product
        update_payload = {
            'id': new_pid,
            'price': 420000,
            'stock': 45
        }
        status, res = api_result(self.app, 'C-001', 'POST', '/api/manager/products/update', update_payload)
        self.assertEqual(status, 200)
        self.assertEqual(res['product']['price'], 420000)
        self.assertEqual(res['product']['stock'], 45)

        # 4. Try to delete immutable system product P-101 (Should fail safely)
        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/products/delete', {'id': 'P-101'})
        self.assertEqual(ctx.exception.code, 'system_product_immutable')

        # 5. Delete custom product P-999 (Should succeed)
        status, res = api_result(self.app, 'C-001', 'POST', '/api/manager/products/delete', {'id': new_pid})
        self.assertEqual(status, 200)
        self.assertEqual(res['removed']['id'], new_pid)

        # 6. Verify removed
        status, res = api_result(self.app, 'C-001', 'GET', '/api/manager/products')
        found_after = next((p for p in res['products'] if p['id'] == new_pid), None)
        self.assertIsNone(found_after)

    def test_manager_update_order_status(self):
        # Update order O-101 to delivered
        payload = {'order_id': 'O-101', 'status': 'delivered'}
        status, res = api_result(self.app, 'C-001', 'POST', '/api/manager/orders/update-status', payload)
        self.assertEqual(status, 200)
        self.assertEqual(res['new_status'], 'delivered')

        with self.store.connection() as db:
            row = db.execute("SELECT status FROM orders WHERE id='O-101'").fetchone()
            self.assertEqual(row['status'], 'delivered')

    def test_manager_order_invalid_state_transitions(self):
        # O-101 is pending initially. Transition to delivered is valid.
        status, res = api_result(self.app, 'C-001', 'POST', '/api/manager/orders/update-status', {'order_id': 'O-101', 'status': 'delivered'})
        self.assertEqual(status, 200)

        # Transitioning from terminal state 'delivered' to 'pending' must fail
        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/orders/update-status', {'order_id': 'O-101', 'status': 'pending'})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, 'invalid_transition')

        # Transitioning from terminal state 'delivered' to 'cancelled' must fail
        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/orders/update-status', {'order_id': 'O-101', 'status': 'cancelled'})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, 'invalid_transition')

    def test_manager_rbac_rejection(self):
        customer_app = Application(self.store, {}, role='customer')
        for method, path, body in [
            ('GET', '/api/manager/products', None),
            ('GET', '/api/manager/kpis', None),
            ('GET', '/api/manager/benchmark', None),
            ('POST', '/api/manager/products', {'id': 'P-888', 'name': 'Áo Lậu'}),
            ('POST', '/api/manager/products/update', {'id': 'P-101', 'price': 1000}),
            ('POST', '/api/manager/products/delete', {'id': 'P-101'}),
            ('POST', '/api/manager/orders/update-status', {'order_id': 'O-101', 'status': 'delivered'}),
        ]:
            with self.subTest(method=method, path=path):
                with self.assertRaises(ApiError) as ctx:
                    api_result(customer_app, 'C-001', method, path, body)
                self.assertEqual(ctx.exception.status, 403)
                self.assertEqual(ctx.exception.code, 'permission_denied')

    def test_tools_execute_rbac(self):
        customer_app = Application(self.store, {}, role='customer')
        with self.assertRaises(ApiError) as ctx:
            api_result(customer_app, 'C-001', 'POST', '/api/tools/execute', {'tool_name': 'list_orders', 'arguments': {}})
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, 'permission_denied')

        staff_app = Application(self.store, {}, role='staff')
        status, res = api_result(staff_app, 'C-001', 'POST', '/api/tools/execute', {'tool_name': 'list_orders', 'arguments': {}})
        self.assertEqual(status, 200)
        self.assertIn('result', res)

    def test_manager_events_and_actor_audit(self):
        from retailops.identity.contracts import SessionBinding
        binding = SessionBinding(self.app, 'C-001', 'ws1', tenant_id='tenant-demo', principal_id='usr_manager_01', display_name='Manager Test')
        self.app.current_binding = binding

        # 1. Create a product
        pid = 'P-777'
        payload = {
            'id': pid, 'name': 'Áo Audit Trail', 'category': 'Áo', 'price': 250000,
            'stock': 30, 'warranty_days': 45, 'variants': ['Trắng · Size M']
        }
        api_result(self.app, 'C-001', 'POST', '/api/manager/products', payload, binding=binding)

        # 2. Update the product
        api_result(self.app, 'C-001', 'POST', '/api/manager/products/update', {'id': pid, 'price': 270000}, binding=binding)

        # 3. Delete the product
        api_result(self.app, 'C-001', 'POST', '/api/manager/products/delete', {'id': pid}, binding=binding)

        # 4. Fetch manager events
        status, res = api_result(self.app, 'C-001', 'GET', '/api/manager/events', binding=binding)
        self.assertEqual(status, 200)
        self.assertIn('events', res)
        events = res['events']
        
        created_ev = next((e for e in events if e['kind'] == 'product_created' and e['payload'].get('product_id') == pid), None)
        self.assertIsNotNone(created_ev)
        # Verify genuine principal_id vs customer_id separation
        self.assertEqual(created_ev['payload']['actor']['principal_id'], 'usr_manager_01')
        self.assertEqual(created_ev['payload']['actor']['customer_id'], 'C-001')
        self.assertEqual(created_ev['payload']['actor']['role'], 'manager')
        self.assertEqual(created_ev['payload']['actor']['tenant_id'], 'tenant-demo')

        updated_ev = next((e for e in events if e['kind'] == 'product_updated' and e['payload'].get('product_id') == pid), None)
        self.assertIsNotNone(updated_ev)
        self.assertEqual(updated_ev['payload']['updates']['price'], 270000)

        deleted_ev = next((e for e in events if e['kind'] == 'product_deleted' and e['payload'].get('product_id') == pid), None)
        self.assertIsNotNone(deleted_ev)

    def test_cross_session_catalog_persistence(self):
        # Session A: Manager creates product
        pid = 'P-888'
        payload = {
            'id': pid, 'name': 'Sản Phẩm Đa Session', 'category': 'Quần', 'price': 350000,
            'stock': 15, 'warranty_days': 60, 'variants': ['Đen · Size 30', 'Đen · Size 32']
        }
        api_result(self.app, 'C-001', 'POST', '/api/manager/products', payload)

        # Session B: Customer application instance on the same store
        customer_app = Application(self.store, {}, role='customer')
        self.assertIn(pid, customer_app.catalog.products)
        cust_prod = customer_app.catalog.products[pid]
        self.assertEqual(cust_prod['name'], 'Sản Phẩm Đa Session')
        self.assertEqual(cust_prod['price'], 350000)

        # Customer tools bound to customer session can check inventory of new product
        from retailops_tools import BoundTools
        snapshot = {'order_id': None, 'product_id': None}
        tools = BoundTools(self.store, customer_app.catalog, 'C-002', snapshot, {'name': 'test'})
        inv = tools('check_inventory', {'product_id': pid, 'size': '30', 'color': 'Đen'})
        self.assertTrue(inv['in_stock'])
        self.assertGreater(inv['stock'], 0)

        # Session A: Manager updates stock
        api_result(self.app, 'C-001', 'POST', '/api/manager/products/update', {'id': pid, 'price': 390000})

        # Session B immediately observes new price without reload
        self.assertEqual(customer_app.catalog.products[pid]['price'], 390000)

    def test_dispute_agent_out_of_stock_real_inventory(self):
        from retailops.workflow.subagents.dispute_agent import run_dispute_agent
        from retailops_tools import BoundTools

        class MockGateway:
            def __init__(self, reply=""):
                self.reply = reply

            def chat(self, messages, tools_allowed=True, timeout=30):
                return {"message": {"role": "assistant", "content": self.reply}}

        snapshot = {'order_id': 'O-101', 'product_id': 'P-101'}
        tools = BoundTools(self.store, self.app.catalog, 'C-001', snapshot, {'name': 'test'})

        # P-101 XL has stock = 0
        state = {
            "messages": [{"role": "user", "content": "Đơn O-101 mình mặc chật quá, muốn đổi size sang size XL có được không?"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {"order_id": "O-101", "product_id": "P-101"},
            "intent": "unknown", "next_worker": "dispute_agent", "subagent_history": [],
            "sentiment": "neutral", "strict_mode": False, "consecutive_ood_count": 0,
            "action_proposal": None, "requires_human": False, "human_reason": None
        }

        res = run_dispute_agent(state, tools, MockGateway())
        # Since XL is out of stock (stock == 0), no action proposal should be confirmed as ready
        self.assertIsNone(res.get("action_proposal"))
        last_msg = res["messages"][-1]["content"]
        self.assertIn("hết hàng", last_msg.lower())

    def test_variant_stock_preserved_on_metadata_update(self):
        # 1. P-203 has size M Navy stock = 0, size L Navy stock = 18, size S = 12, size XL = 5
        m_stock = self.store.get_variant_stock('P-203', 'M', 'Xanh Navy')
        self.assertEqual(m_stock.stock, 0)
        l_stock = self.store.get_variant_stock('P-203', 'L', 'Xanh Navy')
        self.assertEqual(l_stock.stock, 18)

        # 2. Manager edits description and price, sending UI-style payload with existing variants list
        payload = {
            'id': 'P-203',
            'name': 'Áo Polo Nam Phối Bo Cổ Co Giãn',
            'description': 'Mô tả mới được cập nhật từ giao diện quản trị',
            'price': 429000,
            'variants': ['Xanh Navy · Size S', 'Xanh Navy · Size M', 'Xanh Navy · Size L', 'Xanh Navy · Size XL']
        }
        status, res = api_result(self.app, 'C-001', 'POST', '/api/manager/products/update', payload)
        self.assertEqual(status, 200)

        # 3. Size M Navy MUST still be 0! It must NOT become 55 // 4 = 13!
        m_after = self.store.get_variant_stock('P-203', 'M', 'Xanh Navy')
        self.assertEqual(m_after.stock, 0)
        self.assertEqual(m_after.status, 'ok')

        # 4. Size L Navy MUST still be 18!
        l_after = self.store.get_variant_stock('P-203', 'L', 'Xanh Navy')
        self.assertEqual(l_after.stock, 18)

        # 5. Total stock must be preserved as sum of variants (12 + 0 + 18 + 5 = 35)
        p_prod = self.store.get_product('P-203')
        self.assertEqual(p_prod['stock'], 35)
        self.assertEqual(p_prod['price'], 429000)

    def test_check_inventory_nonexistent_color_variant_not_found(self):
        from retailops_tools import BoundTools
        snapshot = {'order_id': None, 'product_id': None}
        tools = BoundTools(self.store, self.app.catalog, 'C-001', snapshot, {'name': 'test'})

        # Request P-203 with non-existent color "Hồng không tồn tại"
        res = tools('check_inventory', {'product_id': 'P-203', 'size': 'L', 'color': 'Hồng không tồn tại'})
        self.assertEqual(res.get('error'), 'variant_not_found')
        self.assertFalse(res['in_stock'])
        self.assertEqual(res['stock'], 0)
        self.assertIn('không có biến thể', res['status_text'])

    def test_check_inventory_unknown_stock_preserves_none(self):
        from retailops_tools import BoundTools
        # Add product with stock=None
        payload = {
            'id': 'P-559', 'name': 'Áo Khoác Chưa Kiểm Kho', 'category': 'Áo', 'price': 500000,
            'stock': None
        }
        api_result(self.app, 'C-001', 'POST', '/api/manager/products', payload)

        snapshot = {'order_id': None, 'product_id': None}
        tools = BoundTools(self.store, self.app.catalog, 'C-001', snapshot, {'name': 'test'})
        res = tools('check_inventory', {'product_id': 'P-559', 'size': 'L', 'color': 'Tiêu chuẩn'})
        self.assertIsNone(res['stock'])
        self.assertIsNone(res['in_stock'])
        self.assertIn('chưa được cập nhật', res['status_text'])

    def test_cross_session_cache_bypass_and_synchronization(self):
        from retailops_tools import BoundTools
        # Customer App reads product P-203
        cust_app = Application(self.store, {}, role='customer')
        snapshot = {'order_id': None, 'product_id': None}
        cust_tools = BoundTools(self.store, cust_app.catalog, 'C-001', snapshot, {'name': 'test'})
        p_read1 = cust_tools('get_product', {'product_id': 'P-203'})
        self.assertEqual(p_read1['product']['price'], 399000)

        # Manager updates price to 999999
        api_result(self.app, 'C-001', 'POST', '/api/manager/products/update', {'id': 'P-203', 'price': 999999})

        # Customer reads again via tool -> must immediately see 999999 (not cached 399000!)
        p_read2 = cust_tools('get_product', {'product_id': 'P-203'})
        self.assertEqual(p_read2['product']['price'], 999999)

    def test_dispute_agent_nonexistent_order_no_proposal(self):
        from retailops.workflow.subagents.dispute_agent import run_dispute_agent
        from retailops_tools import BoundTools

        class MockGateway:
            def __init__(self, reply=""):
                self.reply = reply

            def chat(self, messages, tools_allowed=True, timeout=30):
                return {"message": {"role": "assistant", "content": self.reply}}

        snapshot = {'order_id': None, 'product_id': None}
        tools = BoundTools(self.store, self.app.catalog, 'C-001', snapshot, {'name': 'test'})

        state = {
            "messages": [{"role": "user", "content": "Đơn hàng O-999999 bị kẹt khóa, shop đổi mới giúp mình với!"}],
            "fresh": [], "trace": {}, "tool_count": 0, "complete": False,
            "bound": {},
            "intent": "unknown", "next_worker": "dispute_agent", "subagent_history": [],
            "sentiment": "negative", "strict_mode": False, "consecutive_ood_count": 0,
            "action_proposal": None, "requires_human": False, "human_reason": None
        }

        res = run_dispute_agent(state, tools, MockGateway())
        # For non-existent order, dispute agent must NOT create an exchange proposal!
        self.assertIsNone(res.get("action_proposal"))
        last_msg = res["messages"][-1]["content"]
        self.assertIn("không tìm thấy", last_msg.lower())

    def test_delete_product_with_existing_orders_blocked(self):
        # Order O-302 references product P-104
        with self.assertRaises(ApiError) as ctx:
            api_result(self.app, 'C-001', 'POST', '/api/manager/products/delete', {'id': 'P-104'})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, 'product_has_existing_orders')
        self.assertIn('phát sinh', ctx.exception.message)

    def test_seed_backfill_deepseek_orders(self):
        with self.store.connection() as db:
            o305 = db.execute("SELECT product_id FROM orders WHERE id='O-305'").fetchone()
            self.assertIsNotNone(o305)
            self.assertEqual(o305['product_id'], 'P-501')

            o306 = db.execute("SELECT product_id FROM orders WHERE id='O-306'").fetchone()
            self.assertIsNotNone(o306)
            self.assertEqual(o306['product_id'], 'P-503')

            o307 = db.execute("SELECT product_id FROM orders WHERE id='O-307'").fetchone()
            self.assertIsNotNone(o307)
            self.assertEqual(o307['product_id'], 'P-506')

    def test_sqlite_to_postgres_import_table_order(self):
        from retailops.storage.import_sqlite import read_database, BUSINESS_TABLES
        snapshot_tables = read_database(self.store.path, 'business', BUSINESS_TABLES)
        table_order = list(snapshot_tables.keys())
        self.assertIn('products', table_order)
        self.assertIn('product_variants', table_order)
        self.assertIn('orders', table_order)
        prod_idx = table_order.index('products')
        var_idx = table_order.index('product_variants')
        order_idx = table_order.index('orders')
        # Products and variants MUST come before orders to satisfy orders.product_id foreign key constraint
        self.assertLess(prod_idx, var_idx)
        self.assertLess(var_idx, order_idx)


if __name__ == '__main__':
    unittest.main()

