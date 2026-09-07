"""Explicit database initialization and offline import; never automatic at web startup."""
import os
from pathlib import Path


def add_parser(commands):
    parser = commands.add_parser('database', help='Initialize PostgreSQL or import an offline SQLite snapshot.')
    commands = parser.add_subparsers(dest='database_action', required=True)
    commands.add_parser('init', help='Create/validate the identity schema; no demo accounts are seeded.')
    commands.add_parser('migrate', help='Upgrade every tenant business schema; stop web writers and back up first.')
    commands.add_parser('check', help='Connect and verify the PostgreSQL identity schema version.')
    importer = commands.add_parser('import-sqlite', help='Import an offline v0.7 persistent snapshot into an empty target.')
    importer.add_argument('--offline-snapshot', type=Path, required=True,
                          help='Copied persistent/ directory; stop source web and all writers before making the copy.')


def run(args):
    from retailops.config import database_settings
    from retailops.storage.pg_repositories import PostgresIdentityStore
    from retailops.storage.postgres import BUSINESS_SCHEMA_CURRENT
    backend, dsn = database_settings(os.environ)
    if backend != 'postgresql':
        raise ValueError('This command requires RETAILOPS_STORAGE_BACKEND=postgresql.')
    if args.database_action == 'import-sqlite':
        from retailops.storage.import_sqlite import import_snapshot
        return import_snapshot(dsn, args.offline_snapshot)
    identity = PostgresIdentityStore(dsn, create=args.database_action == 'init')
    if args.database_action == 'migrate':
        from retailops.storage.pg_schema import initialize
        from retailops.storage.postgres import transaction, tenant_schema
        with identity.connection() as db:
            tenants = db.execute('SELECT storage_key FROM tenants').fetchall()
        for tenant in tenants:
            schema = tenant_schema(tenant['storage_key'])
            with transaction(dsn, schema, write=True) as db:
                initialize(db, schema, 'business')
        return {'result': 'POSTGRES_MIGRATED', 'business_schema_version': BUSINESS_SCHEMA_CURRENT,
                'tenants': len(tenants)}
    return {'result': 'POSTGRES_SCHEMA_READY', 'version': 1, 'accounts_seeded': False}
