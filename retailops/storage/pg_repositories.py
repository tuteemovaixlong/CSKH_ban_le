"""Same business and identity operations, using PostgreSQL transactions and DDL."""
from retailops.business.store import BusinessStore
from retailops.core import ApiError
from retailops.identity.store import IdentityStore
from retailops.storage.pg_schema import P5C_BUSINESS_DDL, P5C_IDENTITY_DDL, initialize
from retailops.storage.postgres import (
    BUSINESS_SCHEMA_CURRENT,
    IDENTITY_SCHEMA,
    check_schema,
    tenant_schema,
    transaction,
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
                initialize(db, IDENTITY_SCHEMA, 'identity')
        else:
            if self.read_only:
                check_schema(dsn, IDENTITY_SCHEMA, 'identity', read_only=True)
            else:
                check_schema(dsn, IDENTITY_SCHEMA, 'identity')
            if migrate:
                with self.connection(write=True) as db:
                    row = db.raw.execute("SELECT version FROM retailops_schema WHERE component='identity'").fetchone()
                    if row and row.get('version') in (1, 2, 3):
                        initialize(db, IDENTITY_SCHEMA, 'identity')  # also applies P5C_IDENTITY_DDL
                    else:
                        # P5-C: an already-current schema gets the additive, idempotent mapping-table DDL.
                        for statement in P5C_IDENTITY_DDL:
                            db.raw.execute(statement)
        if migrate:
            with self.connection(write=True) as db:
                db.raw.execute("ALTER TABLE memberships DROP CONSTRAINT IF EXISTS memberships_role_check")
                db.raw.execute(
                    "ALTER TABLE memberships ADD CONSTRAINT memberships_role_check "
                    "CHECK (role IN ('customer', 'viewer', 'staff', 'manager', 'platform_admin'))"
                )

    def connection(self, write=False):
        if self.read_only and write:
            raise ApiError(409, 'read_only_store', 'Kho identity đang ở chế độ chỉ đọc.')
        return transaction(self.dsn, IDENTITY_SCHEMA, write=write, read_only=self.read_only)

