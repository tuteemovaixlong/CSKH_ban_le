"""Persistent account sessions backed by PostgreSQL; cookies and permissions unchanged."""
import threading
from collections import OrderedDict

from retailops.identity.persistent import PersistentSessions
from retailops.storage.pg_repositories import PostgresBusinessStore, PostgresIdentityStore
from retailops.storage.postgres import check_schema, tenant_schema
from retailops.core import ApiError


class PostgresSessions(PersistentSessions):
    def __init__(self, dsn, infer=None, api_infer=None, api_daily_limit=20, capacity=50):
        self.dsn = dsn
        self.control = PostgresIdentityStore(dsn)
        self.infer, self.api_infer = infer, api_infer
        self.api_daily_limit, self.capacity = api_daily_limit, capacity
        self.agent_lock, self.lock = threading.Lock(), threading.RLock()
        self.apps = OrderedDict()
        self.purge()

    def provision_tenant(self, tenant_id, name, *, seed_demo=False):
        tenant = self.control.ensure_tenant(tenant_id, name)
        store = PostgresBusinessStore(self.dsn, tenant['storage_key'], create=True)
        if seed_demo:
            store.seed()
        return store

    def business_store(self, tenant_id):
        return PostgresBusinessStore(self.dsn, self.control.tenant(tenant_id)['storage_key'])

    def check_storage(self, member):
        try:
            check_schema(self.dsn, tenant_schema(member['storage_key']), 'business')
        except ValueError:
            raise ApiError(503, 'tenant_storage_unavailable', 'Kho dữ liệu cửa hàng cần quản trị viên kiểm tra.') from None

    def metadata(self):
        return {**super().metadata(), 'storage_backend': 'postgresql'}
