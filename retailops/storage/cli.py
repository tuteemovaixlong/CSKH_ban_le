"""Explicit database initialization, controlled Business v5 migration, and offline import."""
import os
from pathlib import Path


def add_parser(commands):
    parser = commands.add_parser('database', help='Initialize PostgreSQL, run Business v5 migration, or import an offline SQLite snapshot.')
    parser.add_argument('--output', type=Path, default=Path('artifacts'),
                        help='Workspace directory containing persistent/ when using SQLite.')
    sub = parser.add_subparsers(dest='database_action', required=True)
    sub.add_parser('init', help='Create/validate the identity schema; no demo accounts are seeded.')
    mig = sub.add_parser('migrate', help='Apply additive DDL to current-version PostgreSQL tenant schemas.')
    mig.add_argument('--confirm-preflight', action='store_true',
                     help='Confirm read-only preflight checks were completed.')
    mig.add_argument('--confirm-backup', action='store_true',
                     help='Confirm verified database backup was completed.')
    mig_v5 = sub.add_parser(
        'migrate-v5',
        help='Explicitly upgrade all tenant business stores to Business v5 and backfill cases/episodes.',
    )
    mig_v5.add_argument('--db-path', type=Path, default=None,
                        help='Optional standalone SQLite business file path (defaults to all tenants under --output/persistent).')
    mig_v5.add_argument('--confirm-preflight', action='store_true',
                        help='Confirm read-only preflight checks were completed.')
    mig_v5.add_argument('--confirm-backup', action='store_true',
                        help='Confirm verified database backup was completed.')
    sub.add_parser('check', help='Connect and verify identity and tenant business schema versions read-only.')
    importer = sub.add_parser('import-sqlite', help='Import an offline persistent snapshot into an empty target.')
    importer.add_argument('--offline-snapshot', type=Path, required=True,
                          help='Copied persistent/ directory; stop source web and all writers before making the copy.')


def run(args):
    from retailops.business.store import _inspect_sqlite_business_ready, migrate_sqlite_business_v5
    from retailops.config import database_settings
    from retailops.core import ApiError
    from retailops.storage.pg_repositories import PostgresIdentityStore, migrate_postgres_business_v5
    from retailops.storage.postgres import BUSINESS_SCHEMA_CURRENT, IDENTITY_SCHEMA, tenant_schema, transaction

    backend, dsn = database_settings(os.environ)
    action = getattr(args, 'database_action', None)
    preflight_ok = bool(getattr(args, 'confirm_preflight', False))
    backup_ok = bool(getattr(args, 'confirm_backup', False))

    if action == 'migrate-v5':
        if backend == 'sqlite':
            target = getattr(args, 'db_path', None) or getattr(args, 'output', Path('artifacts'))
            return migrate_sqlite_business_v5(
                target,
                preflight_confirmed=preflight_ok,
                backup_confirmed=backup_ok,
            )
        return migrate_postgres_business_v5(
            dsn,
            preflight_confirmed=preflight_ok,
            backup_confirmed=backup_ok,
        )

    if backend == 'sqlite' and action == 'check':
        out_root = Path(getattr(args, 'output', Path('artifacts')))
        pers = out_root / 'persistent' if (out_root / 'persistent').is_dir() else out_root
        from retailops.identity.store import _inspect_sqlite_identity_ready
        id_file = pers / 'identity.sqlite3'
        if not id_file.is_file():
            raise ApiError(404, 'database_not_found', 'Không tìm thấy kho identity SQLite để kiểm tra.')
        _inspect_sqlite_identity_ready(id_file)
        t_dir = pers / 'tenants'
        checked = 0
        if t_dir.is_dir():
            for tf in sorted(t_dir.glob('*.sqlite3')):
                _inspect_sqlite_business_ready(tf)
                checked += 1
        return {'result': 'SQLITE_SCHEMA_READY', 'tenants_checked': checked}

    if backend != 'postgresql':
        raise ValueError('This command requires RETAILOPS_STORAGE_BACKEND=postgresql.')
    if action == 'import-sqlite':
        from retailops.storage.import_sqlite import import_snapshot
        return import_snapshot(dsn, args.offline_snapshot)
    identity = PostgresIdentityStore(dsn, create=action == 'init')
    if action == 'check':
        with identity.connection(write=False) as db:
            tenants = db.execute('SELECT storage_key FROM tenants WHERE active=1').fetchall() or []
        for tenant in tenants:
            t_schema = tenant_schema(tenant['storage_key'])
            with transaction(dsn, IDENTITY_SCHEMA, read_only=True) as db:
                from psycopg import sql
                exists = db.raw.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s', (t_schema,)).fetchone()
                if exists:
                    ver_row = db.raw.execute(
                        sql.SQL('SELECT component,version FROM {}.retailops_schema').format(sql.Identifier(t_schema))
                    ).fetchone()
                    if not ver_row or ver_row.get('component') != 'business':
                        raise ValueError('Unsupported PostgreSQL schema version or component.')
                    if ver_row.get('version') < BUSINESS_SCHEMA_CURRENT:
                        raise ApiError(
                            503,
                            'business_migration_required',
                            f"Kho dữ liệu business PostgreSQL ({t_schema}) đang ở schema v{ver_row.get('version')}; "
                            "cần chạy database migrate-v5 với --confirm-preflight --confirm-backup.",
                        )
        return {'result': 'POSTGRES_SCHEMA_READY', 'version': 1, 'accounts_seeded': False}
    if action == 'migrate':
        from retailops.storage.pg_schema import initialize
        allow_v5 = bool(preflight_ok and backup_ok)
        with identity.connection() as db:
            tenants = db.execute('SELECT storage_key FROM tenants').fetchall()
        for tenant in tenants:
            schema = tenant_schema(tenant['storage_key'])
            with transaction(dsn, schema, write=True) as db:
                initialize(db, schema, 'business', allow_business_v5_upgrade=allow_v5)
        return {'result': 'POSTGRES_MIGRATED', 'business_schema_version': BUSINESS_SCHEMA_CURRENT,
                'tenants': len(tenants)}
    return {'result': 'POSTGRES_SCHEMA_READY', 'version': 1, 'accounts_seeded': False}
