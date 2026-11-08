"""Shared HTTP harness for the W3.2 tests: two tenants and cookie sessions for every role.

Requests go through the real PublicWeb router, so permissions, tenant scoping and error
mapping are exercised exactly as in production. No network, no model, no real database.
"""
import io
import json
import secrets
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from retailops.core import ApiError
from retailops.http.public import PublicWeb
from retailops.identity.persistent import PersistentSessions
from legacy_seed_fixture import provision_legacy_unit_tenant

ORIGIN = 'https://retailops.example.com'


class RoleHarness(unittest.TestCase):
    """Tenant `shop-a` (seeded unit fixture + extra orders) and `shop-b`, each with role sessions."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pers = Path(self.temp.name) / 'persistent'
        self.sessions = PersistentSessions(self.pers, data_mode='persistent-demo')
        self.sessions.customer_ref_key = 'test-w32-customer-ref-key-0123456789abcdef'
        self.store_a = provision_legacy_unit_tenant(self.sessions, 'shop-a', 'Shop A')
        self.store_b = provision_legacy_unit_tenant(self.sessions, 'shop-b', 'Shop B')
        self.store_a.add_customer('C-STAFF-A', 'Nhân viên A')
        self.store_a.add_customer('C-MGR-A', 'Quản lý A')
        self.store_b.add_customer('C-STAFF-B', 'Nhân viên B')
        self.web = PublicWeb(ORIGIN, self.sessions)
        self.cust1 = self.issue_cookie('shop-a', 'p-cust-1', 'Khách 1', 'C-001', 'customer')
        self.cust2 = self.issue_cookie('shop-a', 'p-cust-2', 'Khách 2', 'C-002', 'customer')
        self.staff_a = self.issue_cookie('shop-a', 'p-staff-a', 'Nhân viên A', 'C-STAFF-A', 'staff')
        self.mgr_a = self.issue_cookie('shop-a', 'p-mgr-a', 'Quản lý A', 'C-MGR-A', 'manager')
        self.staff_b = self.issue_cookie('shop-b', 'p-staff-b', 'Nhân viên B', 'C-STAFF-B', 'staff')

    def issue_cookie(self, tenant_id, principal_id, name, customer_id, role):
        member = self.sessions.create_member(tenant_id, principal_id, name, customer_id, role)
        token = secrets.token_urlsafe(32)
        self.sessions.control.register_credential(member, token)
        secret = self.sessions.login(token)
        return f'{self.sessions.cookie_name}={secret}'

    def request(self, method, path, body=None, *, cookie=None, headers=None, query=None):
        raw = b'' if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
        env = {'REQUEST_METHOD': method, 'PATH_INFO': path,
               'QUERY_STRING': urllib.parse.urlencode(query or {}),
               'HTTP_HOST': 'retailops.example.com', 'wsgi.input': io.BytesIO(raw)}
        if method != 'GET':
            env['HTTP_ORIGIN'] = ORIGIN
        if body is not None:
            env['CONTENT_TYPE'] = 'application/json'
            env['CONTENT_LENGTH'] = str(len(raw))
        if cookie:
            env['HTTP_COOKIE'] = cookie
        for key, value in (headers or {}).items():
            env['HTTP_' + key.upper().replace('-', '_')] = value
        try:
            status, payload, _, _ = self.web.route(env)
            return status, payload
        except ApiError as err:
            return err.status, {'error': err.code, 'message': err.message}

    def add_order(self, order_id, status, variant, *, product_id='P-102', name='Áo khoác Everyday',
                  customer='C-001', amount=599000, store=None):
        with (store or self.store_a).connection(write=True) as db:
            db.execute(
                'INSERT INTO orders(id, customer_id, product_id, source_system, external_order_id, ordered_at, name, variant, amount, status, version) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)',
                (order_id, customer, product_id, 'retailops_seed', order_id, 1700000000.0, name, variant, amount, status))
