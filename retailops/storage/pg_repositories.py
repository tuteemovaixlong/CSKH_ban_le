"""Same business and identity operations, using PostgreSQL transactions and DDL."""
from retailops.business.store import BusinessStore
from retailops.core import ApiError, require
from retailops.identity.store import IdentityStore
from retailops.storage.pg_schema import P5C_BUSINESS_DDL, P5C_IDENTITY_DDL, initialize
from retailops.storage.postgres import (
    BUSINESS_SCHEMA_CURRENT,
    IDENTITY_SCHEMA,
    IDENTITY_SCHEMA_CURRENT,
    check_schema,
    tenant_schema,
    transaction,
    validate_dsn,
)


class PostgresBusinessStore(BusinessStore):
    def __init__(self, dsn, storage_key, *, create=False, migrate=True, read_only=False):
        if create and (not migrate or read_only):
            raise ValueError('Creating a PostgreSQL store is incompatible with read-only/no-migration mode.')
        self.dsn, self.schema = dsn, tenant_schema(storage_key)
        self.read_only = bool(read_only)
        if create:
            with self.connection(write=True) as db:
                initialize(db, self.schema, 'business')
                self.seed_catalog(db)
        else:
            if self.read_only:
                check_schema(dsn, self.schema, 'business', read_only=True)
            else:
                check_schema(dsn, self.schema, 'business')
            if migrate:
                with self.connection(write=True) as db:
                    row = db.raw.execute("SELECT version FROM retailops_schema WHERE component='business'").fetchone()
                    if row and row.get('version') == BUSINESS_SCHEMA_CURRENT:
                        for statement in P5C_BUSINESS_DDL:
                            db.raw.execute(statement)

    def connection(self, write=False):
        if self.read_only and write:
            raise ApiError(409, 'read_only_store', 'Kho cửa hàng đang ở chế độ chỉ đọc.')
        return transaction(self.dsn, self.schema, write=write, read_only=self.read_only)


class PostgresIdentityStore(IdentityStore):
    def __init__(self, dsn, *, create=False, migrate=True, read_only=False):
        if create and (not migrate or read_only):
            raise ValueError('Creating a PostgreSQL identity store is incompatible with read-only/no-migration mode.')
        self.dsn = dsn
        self.read_only = bool(read_only)
        if create:
            with self.connection(write=True) as db:
                initialize(db, IDENTITY_SCHEMA, 'identity', allow_identity_v5_upgrade=False)
        else:
            if self.read_only:
                check_schema(dsn, IDENTITY_SCHEMA, 'identity', read_only=True)
            else:
                check_schema(dsn, IDENTITY_SCHEMA, 'identity')
            if migrate or not self.read_only:
                with self.connection(write=False) as db:
                    row = db.raw.execute("SELECT version FROM retailops_schema WHERE component='identity'").fetchone()
                ver = row.get('version') if row else None
                if ver != IDENTITY_SCHEMA_CURRENT:
                    raise ApiError(
                        503,
                        'identity_migration_required',
                        f"Kho dữ liệu identity PostgreSQL đang ở schema v{ver}; khởi động bị chặn fail-closed. "
                        "Hãy chạy lệnh operator identity migrate-v5 với --confirm-preflight --confirm-backup.",
                    )
            if migrate:
                with self.connection(write=True) as db:
                    for statement in P5C_IDENTITY_DDL:
                        db.raw.execute(statement)

    def connection(self, write=False):
        if self.read_only and write:
            raise ApiError(409, 'read_only_store', 'Kho identity đang ở chế độ chỉ đọc.')
        return transaction(self.dsn, IDENTITY_SCHEMA, write=write, read_only=self.read_only)


def migrate_postgres_identity_v5(dsn, *, preflight_confirmed=False, backup_confirmed=False):
    """Explicit operator migration command for PostgreSQL identity v5 (§11.5).

    Never invoked automatically at web startup, store construction, or ordinary CLI commands.
    """
    require(
        preflight_confirmed is True and backup_confirmed is True,
        400,
        'migration_confirmation_required',
        'Lệnh nâng cấp identity v5 yêu cầu xác nhận tường minh --confirm-preflight và --confirm-backup theo runbook §11.5.',
    )
    validate_dsn(dsn)
    with transaction(dsn, IDENTITY_SCHEMA, write=True) as db:
        from psycopg import sql
        exists = db.raw.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s', (IDENTITY_SCHEMA,)).fetchone()
        require(
            exists is not None,
            404,
            'database_not_found',
            'Không tìm thấy schema identity PostgreSQL hiện hữu để nâng cấp.',
        )
        rows = db.raw.execute(
            sql.SQL('SELECT component,version FROM {}.retailops_schema').format(sql.Identifier(IDENTITY_SCHEMA))
        ).fetchall()
        if len(rows) != 1 or rows[0].get('component') != 'identity':
            raise ValueError('Unsupported PostgreSQL schema version or component.')
        prev_ver = rows[0].get('version')
        if prev_ver not in (1, 2, 3, 4, 5):
            raise ValueError('Unsupported PostgreSQL schema version or component.')
        initialize(db, IDENTITY_SCHEMA, 'identity', allow_identity_v5_upgrade=True)
    return {
        'result': 'IDENTITY_V5_MIGRATED',
        'backend': 'postgresql',
        'schema_version': IDENTITY_SCHEMA_CURRENT,
        'upgraded': bool(prev_ver < IDENTITY_SCHEMA_CURRENT),
    }

