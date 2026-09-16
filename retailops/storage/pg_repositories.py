"""Same business and identity operations, using PostgreSQL transactions and DDL."""
from retailops.business.store import BusinessStore
from retailops.identity.store import IdentityStore
from retailops.storage.pg_schema import initialize
from retailops.storage.postgres import IDENTITY_SCHEMA, check_schema, tenant_schema, transaction


class PostgresBusinessStore(BusinessStore):
    def __init__(self, dsn, storage_key, *, create=False):
        self.dsn, self.schema = dsn, tenant_schema(storage_key)
        if create:
            with self.connection(write=True) as db:
                initialize(db, self.schema, 'business')
        else:
            check_schema(dsn, self.schema, 'business')

    def connection(self, write=False):
        return transaction(self.dsn, self.schema, write=write)


class PostgresIdentityStore(IdentityStore):
    def __init__(self, dsn, *, create=False):
        self.dsn = dsn
        if create:
            with self.connection(write=True) as db:
                initialize(db, IDENTITY_SCHEMA, 'identity')
        else:
            check_schema(dsn, IDENTITY_SCHEMA, 'identity')
        try:
            with self.connection(write=True) as db:
                db.raw.execute("""
                    ALTER TABLE memberships DROP CONSTRAINT IF EXISTS memberships_role_check;
                    ALTER TABLE memberships ADD CONSTRAINT memberships_role_check CHECK (role IN ('customer', 'viewer', 'staff', 'manager'));
                """)
        except Exception:
            pass

    def connection(self, write=False):
        return transaction(self.dsn, IDENTITY_SCHEMA, write=write)

