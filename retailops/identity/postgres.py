"""Persistent account sessions backed by PostgreSQL; cookies and permissions unchanged."""
import threading
from collections import OrderedDict

from retailops.identity.persistent import PersistentSessions, _clean_tenant_id, _env_tenant_id
from retailops.storage.pg_repositories import PostgresBusinessStore, PostgresIdentityStore
from retailops.storage.postgres import BUSINESS_SCHEMA_CURRENT, IDENTITY_SCHEMA, check_schema, tenant_schema, transaction
from retailops.core import ApiError
from retailops.inference_gate import InferenceGate


class PostgresSessions(PersistentSessions):
    def __init__(self, dsn, infer=None, api_infer=None, api_daily_limit=20, capacity=50, data_mode=None, default_tenant_id=None, *, maintenance=True, read_only=False):
        if maintenance and read_only:
            raise ValueError('Read-only PostgreSQL sessions cannot run startup maintenance.')
        self.dsn = dsn
        self.maintenance = bool(maintenance)
        self.read_only = bool(read_only)
        if data_mode is not None:
            self.data_mode = data_mode
        self.default_tenant_id = _clean_tenant_id(default_tenant_id) or _env_tenant_id()
        self.control = PostgresIdentityStore(dsn, migrate=self.maintenance, read_only=self.read_only)
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
            rows = db.execute('SELECT storage_key FROM tenants WHERE active=1').fetchall() or []
        for row in rows:
            key = row.get('storage_key') if isinstance(row, dict) else row['storage_key']
            t_schema = tenant_schema(key)
            with transaction(self.dsn, IDENTITY_SCHEMA, read_only=self.read_only) as db:
                from psycopg import sql
                exists = db.raw.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s', (t_schema,)).fetchone()
                if exists:
                    ver_row = db.raw.execute(
                        sql.SQL('SELECT component,version FROM {}.retailops_schema').format(sql.Identifier(t_schema))
                    ).fetchone()
                    if not ver_row or ver_row.get('component') != 'business':
                        raise ValueError('Unsupported PostgreSQL schema version or component.')
                    if ver_row.get('version') not in (2, 3, 4, 5):
                        raise ValueError('Unsupported PostgreSQL schema version or component.')
                    if ver_row.get('version') < BUSINESS_SCHEMA_CURRENT:
                        raise ApiError(
                            503,
                            'business_migration_required',
                            f"Kho dữ liệu business PostgreSQL ({t_schema}) đang ở schema v{ver_row.get('version')}; "
                            "khởi động bị chặn fail-closed. Hãy chạy lệnh operator database migrate-v5 với "
                            "--confirm-preflight --confirm-backup.",
                        )

    def provision_tenant(self, tenant_id, name, *, seed_demo=False):
        tenant = self.control.ensure_tenant(tenant_id, name)
        store = self._configure_business_store(PostgresBusinessStore(self.dsn, tenant['storage_key'], create=True))
        if seed_demo:
            store.seed()
        return store

    def business_store(self, tenant_id):
        return self._configure_business_store(
            PostgresBusinessStore(
                self.dsn,
                self.control.tenant(tenant_id)['storage_key'],
                migrate=self.maintenance,
                read_only=self.read_only,
            )
        )

    def check_storage(self, member):
        t_schema = tenant_schema(member['storage_key'])
        try:
            check_schema(self.dsn, t_schema, 'business')
        except ValueError:
            raise ApiError(503, 'tenant_storage_unavailable', 'Kho dữ liệu cửa hàng cần quản trị viên kiểm tra.') from None
        with transaction(self.dsn, t_schema, read_only=self.read_only) as db:
            ver_row = db.raw.execute("SELECT version FROM retailops_schema WHERE component='business'").fetchone()
        if not ver_row or ver_row.get('version') != BUSINESS_SCHEMA_CURRENT:
            raise ApiError(
                503,
                'business_migration_required',
                f"Kho dữ liệu business PostgreSQL ({t_schema}) chưa nâng cấp lên schema v{BUSINESS_SCHEMA_CURRENT}; "
                "truy cập bị chặn fail-closed.",
            )

    def metadata(self):
        return {**super().metadata(), 'storage_backend': 'postgresql'}
