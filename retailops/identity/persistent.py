"""Session lifecycle is independent of tenant databases in the persistent synthetic pilot."""
import hashlib
import os
import re
import threading
from collections import OrderedDict
from contextlib import contextmanager
from http.cookies import SimpleCookie
from pathlib import Path

from retailops.account_usage import AccountQuotaStore
from retailops.business.application import Application
from retailops.business.cache import ToolCache
from retailops.business.store import BusinessStore, _inspect_sqlite_business_ready
from retailops.core import require
from retailops.identity.contracts import SessionBinding
from retailops.identity.store import IdentityStore
from retailops.inference_gate import InferenceGate


SMOKE_TENANT_PREFIXES = ('e2e-', 'smoke-', 'synthetic-')


def _clean_tenant_id(value):
    if value is None:
        return ''
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1].strip()
    return text


def _is_smoke_tenant_id(value):
    return _clean_tenant_id(value).lower().startswith(SMOKE_TENANT_PREFIXES)


def _env_tenant_id(env=None, *, strict_conflict=False):
    mapping = os.environ if env is None else env
    primary = _clean_tenant_id(mapping.get('RETAILOPS_DEMO_TENANT_ID'))
    legacy = _clean_tenant_id(mapping.get('GOOGLE_AUTH_TENANT_ID'))
    if primary and legacy and primary != legacy:
        if strict_conflict:
            require(False, 503, 'ambiguous_tenant',
                    'Cấu hình tenant cho đăng nhập Google bị xung đột giữa RETAILOPS_DEMO_TENANT_ID và GOOGLE_AUTH_TENANT_ID.')
        return None
    return (primary or legacy) or None


class PersistentSessions:
    # Separate cookie prevents a disposable demo session being reused in this mode.
    cookie_name = '__Host-retailops_account'
    session_seconds = 8 * 3600
    data_mode = 'persistent-demo'

    def __init__(self, directory, infer=None, api_infer=None, api_daily_limit=20, capacity=50, data_mode=None, default_tenant_id=None, *, maintenance=True, read_only=False):
        if maintenance and read_only:
            raise ValueError('Read-only sessions cannot run startup maintenance.')
        self.directory = Path(directory)
        self.maintenance = bool(maintenance)
        self.read_only = bool(read_only)
        if self.maintenance:
            self.directory.mkdir(parents=True, exist_ok=True)
        if data_mode is not None:
            self.data_mode = data_mode
        self.default_tenant_id = _clean_tenant_id(default_tenant_id) or _env_tenant_id()
        self.control = IdentityStore(
            self.directory/'identity.sqlite3',
            tenant_stores=self.business_store,
            data_mode=data_mode,
            initialize_db=self.maintenance,
            read_only=self.read_only,
        )
        self.infer, self.api_infer = infer, api_infer
        self.api_daily_limit, self.capacity = api_daily_limit, capacity
        self.inference_gate = InferenceGate()
        self.lock = threading.RLock()
        self.tool_caches = {}
        self.apps = OrderedDict()
        self._verify_existing_tenant_schemas()
        if self.maintenance:
            self.purge()

    def _verify_existing_tenant_schemas(self):
        with self.control.connection() as db:
            rows = db.execute('SELECT storage_key FROM tenants WHERE active=1').fetchall()
        for row in rows:
            key = row['storage_key']
            if re.fullmatch(r'[a-f0-9]{32}', str(key or '')):
                t_path = self.directory / 'tenants' / f'{key}.sqlite3'
                if t_path.is_file():
                    _inspect_sqlite_business_ready(t_path)

    def tenant_path(self, tenant):
        require(re.fullmatch(r'[a-f0-9]{32}', tenant['storage_key']),
                503, 'invalid_storage', 'Không mở được kho dữ liệu cửa hàng.')
        return self.directory/'tenants'/(tenant['storage_key']+'.sqlite3')

    def _configure_business_store(self, store):
        store.data_mode = getattr(self, 'data_mode', 'persistent-demo')
        if callable(getattr(self, 'store_clock', None)):
            store.clock = self.store_clock
        if getattr(self, 'case_timer_config', None) is not None:
            store.case_timer_config = self.case_timer_config
        return store

    def provision_tenant(self, tenant_id, name, *, seed_demo=False):
        tenant = self.control.ensure_tenant(tenant_id, name)
        store = self._configure_business_store(BusinessStore(self.tenant_path(tenant)))
        if seed_demo:
            store.seed()
        return store

    def business_store(self, tenant_id):
        path = self.tenant_path(self.control.tenant(tenant_id))
        require(path.is_file(), 503, 'tenant_storage_unavailable', 'Kho dữ liệu chưa sẵn sàng; cần quản trị viên kiểm tra.')
        return self._configure_business_store(
            BusinessStore(
                path,
                create=False,
                initialize_db=self.maintenance,
                read_only=self.read_only,
            )
        )

    def create_member(self, tenant_id, principal_id, name, customer_id, role='customer'):
        self.business_store(tenant_id).customer(customer_id)
        return self.control.create_membership(tenant_id, principal_id, name, customer_id, role)

    def login(self, token):
        return self.control.login(token, self.session_seconds, self.capacity)

    def resolve_google_tenant(self, sub=None, issuer='https://accounts.google.com', tenant_id=None, email=None, email_verified=False):
        explicit_tid = _clean_tenant_id(tenant_id)
        default_tid = _clean_tenant_id(getattr(self, 'default_tenant_id', None))
        env_tid = _env_tenant_id(strict_conflict=True)
        if default_tid and env_tid and default_tid != env_tid:
            require(False, 503, 'ambiguous_tenant',
                    'Cấu hình cửa hàng (tenant) cho đăng nhập Google bị xung đột; cần quản trị viên kiểm tra.')
        configured_tid = default_tid or env_tid
        if explicit_tid and configured_tid and explicit_tid != configured_tid:
            require(False, 503, 'ambiguous_tenant',
                    'Cấu hình cửa hàng (tenant) cho đăng nhập Google bị xung đột; cần quản trị viên kiểm tra.')
        target_tid = explicit_tid or configured_tid
        with self.control.connection() as db:
            if target_tid:
                require(not _is_smoke_tenant_id(target_tid),
                        503, 'tenant_unavailable', f'Cửa hàng {target_tid} không tồn tại hoặc chưa kích hoạt.')
                row = db.execute('SELECT id FROM tenants WHERE id=? AND active=1', (target_tid,)).fetchone()
                require(row is not None, 503, 'tenant_unavailable', f'Cửa hàng {target_tid} không tồn tại hoặc chưa kích hoạt.')

            if sub:
                sub_clean = str(sub).strip()
                issuer_clean = str(issuer).strip() if issuer else 'https://accounts.google.com'
                ext = db.execute('SELECT principal_id FROM external_identities WHERE issuer=? AND sub=?',
                                 (issuer_clean, sub_clean)).fetchone()
                principal_id = ext['principal_id'] if ext else None
                if not principal_id and email_verified and email and sub_clean:
                    email_clean = str(email).strip().lower()
                    if email_clean:
                        prefix = re.sub(r'[^a-zA-Z0-9_-]', '_', email_clean.split('@')[0])[:25]
                        hash_suffix = hashlib.sha256(email_clean.encode()).hexdigest()[:10]
                        legacy_pid = f"g_{prefix}_{hash_suffix}"
                        legacy_p = db.execute('SELECT id FROM principals WHERE id=?', (legacy_pid,)).fetchone()
                        if not legacy_p:
                            legacy_p = db.execute('SELECT id FROM principals WHERE id=?', (email_clean,)).fetchone()
                        if legacy_p:
                            already_bound = db.execute(
                                'SELECT sub FROM external_identities WHERE issuer=? AND principal_id=?',
                                (issuer_clean, legacy_p['id'])
                            ).fetchone()
                            if not (already_bound and already_bound['sub'] != sub_clean):
                                principal_id = legacy_p['id']
                if principal_id:
                    mems = db.execute(
                        '''SELECT m.tenant_id FROM memberships m
                           JOIN tenants t ON t.id = m.tenant_id
                           WHERE m.principal_id=? AND m.active=1 AND t.active=1
                             AND m.role IN ('customer', 'staff', 'manager')''',
                        (principal_id,)
                    ).fetchall()
                    non_smoke_mems = [m['tenant_id'] for m in mems if not _is_smoke_tenant_id(m['tenant_id'])]
                    if len(non_smoke_mems) == 0:
                        require(False, 503, 'ambiguous_tenant',
                                'Tài khoản Google đã liên kết không có cửa hàng đang hoạt động hợp lệ; không tự động chuyển sang cửa hàng khác.')
                    if configured_tid and (len(non_smoke_mems) != 1 or configured_tid != non_smoke_mems[0]):
                        require(False, 503, 'ambiguous_tenant',
                                'Cấu hình cửa hàng (tenant) mặc định xung đột với cửa hàng đã liên kết của tài khoản Google này.')
                    if explicit_tid:
                        if explicit_tid not in non_smoke_mems:
                            require(False, 503, 'ambiguous_tenant',
                                    'Cửa hàng chỉ định xung đột với cửa hàng đã liên kết của tài khoản Google này.')
                        return explicit_tid
                    if len(non_smoke_mems) == 1:
                        return non_smoke_mems[0]
                    require(False, 503, 'ambiguous_tenant',
                            'Hệ thống có nhiều cửa hàng; cần cấu hình rõ cửa hàng (tenant) cho đăng nhập Google thay vì chọn ngẫu nhiên.')

            if target_tid:
                return target_tid

            rows = db.execute('SELECT id FROM tenants WHERE active=1').fetchall()
            require(len(rows) > 0, 503, 'no_active_tenant', 'Chưa có cửa hàng nào hoạt động trên hệ thống.')

            non_smoke = [r['id'] for r in rows if not _is_smoke_tenant_id(r['id'])]
            if len(non_smoke) == 1:
                return non_smoke[0]

            require(False, 503, 'ambiguous_tenant',
                    'Hệ thống có nhiều cửa hàng; cần cấu hình rõ cửa hàng (tenant) cho đăng nhập Google thay vì chọn ngẫu nhiên.')

    def login_google(self, email, name, role='customer', sub=None, issuer='https://accounts.google.com', email_verified=False, live=False, tenant_id=None):
        tenant_id = self.resolve_google_tenant(sub=sub, issuer=issuer, tenant_id=tenant_id, email=email, email_verified=email_verified)
        is_live = live or getattr(self, 'data_mode', None) in ('production', 'live')
        mid, cid = self.control.get_or_create_google_member(
            tenant_id, email, name, role=role, sub=sub, issuer=issuer, email_verified=email_verified, live=is_live
        )
        try:
            bstore = self.business_store(tenant_id)
            with bstore.connection(write=True) as bdb:
                if not is_live:
                    bstore.seed_catalog(bdb)
                bdb.execute("INSERT INTO customers VALUES (?,?) ON CONFLICT DO NOTHING", (cid, name or email))
        except Exception as ex:
            import logging
            logging.getLogger("retailops_identity").error("Failed to provision customer in business store: %s", ex)
            if is_live:
                require(False, 503, 'customer_provision_failed', 'Không thể khởi tạo dữ liệu tài khoản khách hàng.')
        return self.control.create_session_for_membership(mid, self.session_seconds, self.capacity)

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
        tenant_id = member['tenant_id']
        with self.lock:
            if tenant_id not in self.tool_caches:
                self.tool_caches[tenant_id] = ToolCache(default_ttl=180.0)
            tool_cache = self.tool_caches[tenant_id]
            if key not in self.apps:
                app = Application(self.business_store(tenant_id), {}, self.infer, self.api_infer,
                                  self.api_daily_limit, role=member['role'],
                                  tenant_id=tenant_id, tool_cache=tool_cache)
                app.quota_store = AccountQuotaStore(self.control, member['id'])
                app.identity_store = self.control
                app.data_mode = getattr(self, 'data_mode', 'persistent-demo')
                app.inference_gate = getattr(self, 'inference_gate', None) or InferenceGate()
                app.default_provider = 'api' if self.api_infer is not None else 'custom'
                self.apps[key] = app
                if len(self.apps) > self.capacity:
                    self.apps.popitem(last=False)  # Drop only a Python object; never delete business files.
            app = self.apps[key]
            app.identity_store = self.control
            app.data_mode = getattr(self, 'data_mode', 'persistent-demo')
            self.apps.move_to_end(key)
        yield SessionBinding(app, member['customer_id'], member['storage_key'],
                             tenant_id=member['tenant_id'], principal_id=member['principal_id'],
                             display_name=member['name'], membership_id=member['id'], role=member['role'])

    def logout(self, header):
        self.control.logout(self.cookie_id(header))

    def purge(self):
        self.control.purge()  # Session rows only. Orders and audits have no session TTL.

    def check_health(self):
        with self.control.connection() as db:
            db.execute('SELECT 1 FROM tenants LIMIT 1').fetchone()

    def metadata(self):
        return {'session_scope': 'persistent-account', 'data_mode': self.data_mode, 'session_seconds': self.session_seconds}

    def run_case_timers_once(self, now: float | None = None) -> dict:
        totals = {'reminded': 0, 'resolved_inactivity': 0, 'resolved_completed': 0, 'tenants': 0}
        if getattr(self, 'read_only', False):
            return totals
        with self.control.connection() as db:
            rows = db.execute('SELECT id FROM tenants WHERE active=1 ORDER BY id ASC').fetchall() or []
        for row in rows:
            tid = row['id'] if isinstance(row, dict) else row['id']
            try:
                store = self.business_store(tid)
            except ApiError:
                continue
            res = store.process_due_case_timers(now=now)
            totals['tenants'] += 1
            for k in ('reminded', 'resolved_inactivity', 'resolved_completed'):
                totals[k] += int(res.get(k, 0))
        return totals

    @property
    def sales_adapter(self):
        if not hasattr(self, '_sales_adapter') or self._sales_adapter is None:
            from retailops.sales.adapter import SalesImportAdapter
            self._sales_adapter = SalesImportAdapter(self)
        return self._sales_adapter

    def import_sales_event(self, event_data, *, actor_principal_id=None, reference_time=None):
        return self.sales_adapter.ingest_event(
            event_data, actor_principal_id=actor_principal_id, reference_time=reference_time
        )

    def purge_demo_order(
        self,
        *,
        tenant_id: str,
        order_id: str,
        customer_id: str,
        product_id: str,
        status: str,
        amount: int,
        snapshot_name: str,
        execute: bool = False,
        reason: str = "",
        operator_id: str | None = None,
    ) -> dict:
        tenant_clean = _clean_tenant_id(tenant_id)
        require(tenant_clean is not None, 400, 'invalid_tenant_id', 'Mã cửa hàng (tenant_id) không hợp lệ.')
        self.control.tenant(tenant_clean)
        bstore = self.business_store(tenant_clean)
        result = bstore.purge_demo_order(
            tenant_id=tenant_clean,
            order_id=order_id,
            customer_id=customer_id,
            product_id=product_id,
            status=status,
            amount=amount,
            snapshot_name=snapshot_name,
            execute=execute,
            reason=reason,
            operator_id=operator_id,
        )
        if result.get('executed') and hasattr(self, 'tool_caches') and tenant_clean in self.tool_caches:
            self.tool_caches[tenant_clean].invalidate(
                customer=customer_id, tenant_id=tenant_clean, order_id=order_id
            )
        return result
