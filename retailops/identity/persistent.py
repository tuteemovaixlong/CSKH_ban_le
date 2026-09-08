"""Session lifecycle is independent of tenant databases in the persistent synthetic pilot."""
import hashlib
import re
import threading
from collections import OrderedDict
from contextlib import contextmanager
from http.cookies import SimpleCookie
from pathlib import Path

from retailops.account_usage import AccountQuotaStore
from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.core import require
from retailops.identity.contracts import SessionBinding
from retailops.identity.store import IdentityStore


class PersistentSessions:
    # Separate cookie prevents a disposable demo session being reused in this mode.
    cookie_name = '__Host-retailops_account'
    session_seconds = 8 * 3600
    data_mode = 'persistent-demo'

    def __init__(self, directory, infer=None, api_infer=None, api_daily_limit=20, capacity=50):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.control = IdentityStore(self.directory/'identity.sqlite3')
        self.infer, self.api_infer = infer, api_infer
        self.api_daily_limit, self.capacity = api_daily_limit, capacity
        self.agent_lock, self.lock = threading.Lock(), threading.RLock()
        self.apps = OrderedDict()
        self.purge()

    def tenant_path(self, tenant):
        require(re.fullmatch(r'[a-f0-9]{32}', tenant['storage_key']),
                503, 'invalid_storage', 'Không mở được kho dữ liệu cửa hàng.')
        return self.directory/'tenants'/(tenant['storage_key']+'.sqlite3')

    def provision_tenant(self, tenant_id, name, *, seed_demo=False):
        tenant = self.control.ensure_tenant(tenant_id, name)
        store = BusinessStore(self.tenant_path(tenant))
        if seed_demo:
            store.seed()
        return store

    def business_store(self, tenant_id):
        path = self.tenant_path(self.control.tenant(tenant_id))
        require(path.is_file(), 503, 'tenant_storage_unavailable', 'Kho dữ liệu chưa sẵn sàng; cần quản trị viên kiểm tra.')
        return BusinessStore(path, create=False)

    def create_member(self, tenant_id, principal_id, name, customer_id, role='customer'):
        self.business_store(tenant_id).customer(customer_id)
        return self.control.create_membership(tenant_id, principal_id, name, customer_id, role)

    def login(self, token):
        return self.control.login(token, self.session_seconds, self.capacity)

    def cookie_id(self, header):
        cookies = SimpleCookie()
        try:
            cookies.load(header)
            secret = cookies[self.cookie_name].value
        except (KeyError, ValueError):
            secret = ''
        require(re.fullmatch(r'[A-Za-z0-9_-]{43}', secret),
                401, 'unauthorized', 'Nhập mã truy cập cá nhân để mở phiên.')
        return hashlib.sha256(secret.encode()).hexdigest()

    def check_storage(self, member):
        require(self.tenant_path(member).is_file(), 503, 'tenant_storage_unavailable',
                'Kho dữ liệu chưa sẵn sàng; cần quản trị viên kiểm tra.')

    @contextmanager
    def resolve(self, header):
        sid = self.cookie_id(header)
        member = self.control.resolve(sid)
        self.control.rate('session:'+sid, 60)
        self.check_storage(member)
        key = (member['id'], member['auth_version'])
        with self.lock:
            if key not in self.apps:
                app = Application(self.business_store(member['tenant_id']), {}, self.infer, self.api_infer,
                                  self.api_daily_limit, role=member['role'])
                app.quota_store = AccountQuotaStore(self.control, member['id'])
                app.agent_lock = self.agent_lock
                app.default_provider = 'api' if self.api_infer is not None else 'custom'
                self.apps[key] = app
                if len(self.apps) > self.capacity:
                    self.apps.popitem(last=False)  # Drop only a Python object; never delete business files.
            app = self.apps[key]
            self.apps.move_to_end(key)
        yield SessionBinding(app, member['customer_id'], member['storage_key'],
                             tenant_id=member['tenant_id'], principal_id=member['principal_id'], display_name=member['name'])

    def logout(self, header):
        self.control.logout(self.cookie_id(header))

    def purge(self):
        self.control.purge()  # Session rows only. Orders and audits have no session TTL.

    def check_health(self):
        with self.control.connection() as db:
            db.execute('SELECT 1 FROM tenants LIMIT 1').fetchone()

    def metadata(self):
        return {'session_scope': 'persistent-account', 'data_mode': self.data_mode, 'session_seconds': self.session_seconds}
