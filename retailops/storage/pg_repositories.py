"""Same business and identity operations, using PostgreSQL transactions and DDL."""
from retailops.business.store import BusinessStore
from retailops.identity.store import IdentityStore
from retailops.storage.pg_schema import P5C_IDENTITY_DDL, initialize
from retailops.storage.postgres import IDENTITY_SCHEMA, check_schema, tenant_schema, transaction


class PostgresBusinessStore(BusinessStore):
    def __init__(self, dsn, storage_key, *, create=False):
        self.dsn, self.schema = dsn, tenant_schema(storage_key)
        if create:
            with self.connection(write=True) as db:
                initialize(db, self.schema, 'business')
                self.seed_catalog(db)
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
            with self.connection(write=True) as db:
                row = db.raw.execute("SELECT version FROM retailops_schema WHERE component='identity'").fetchone()
                if row and row.get('version') in (1, 2, 3):
                    initialize(db, IDENTITY_SCHEMA, 'identity')  # also applies P5C_IDENTITY_DDL
                else:
                    # P5-C: an already-current schema gets the additive, idempotent mapping-table DDL.
                    for statement in P5C_IDENTITY_DDL:
                        db.raw.execute(statement)
        with self.connection(write=True) as db:
            db.raw.execute("ALTER TABLE memberships DROP CONSTRAINT IF EXISTS memberships_role_check")
            db.raw.execute(
                "ALTER TABLE memberships ADD CONSTRAINT memberships_role_check "
                "CHECK (role IN ('customer', 'viewer', 'staff', 'manager', 'platform_admin'))"
            )

    def connection(self, write=False):
        return transaction(self.dsn, IDENTITY_SCHEMA, write=write)

