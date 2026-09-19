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


if __name__ == '__main__':
    unittest.main()
