"""Explicit database initialization, controlled Business v5..v9 migrations, and offline import."""
import os
from pathlib import Path


def add_parser(commands):
    parser = commands.add_parser('database', help='Initialize PostgreSQL, run Business v5..v9 migration, or import an offline SQLite snapshot.')
    parser.add_argument('--output', type=Path, default=None,
                        help='Workspace directory containing persistent/ when using SQLite (defaults to RETAILOPS_OUTPUT or artifacts).')
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
    mig_v6 = sub.add_parser(
        'migrate-v6',
        help='Explicitly upgrade all tenant business stores to Business v6 (order actions, evidence, outbox).',
    )
    mig_v6.add_argument('--db-path', type=Path, default=None,
                        help='Optional standalone SQLite business file path (defaults to all tenants under --output/persistent).')
    mig_v6.add_argument('--confirm-preflight', action='store_true',
                        help='Confirm read-only preflight checks were completed.')
    mig_v6.add_argument('--confirm-backup', action='store_true',
                        help='Confirm verified database backup was completed.')
    mig_v7 = sub.add_parser(
        'migrate-v7',
        help='Explicitly upgrade all tenant business stores to Business v7 (general exchange: other_variant/same_variant + target variant).',
    )
    mig_v7.add_argument('--db-path', type=Path, default=None,
                        help='Optional standalone SQLite business file path (defaults to all tenants under --output/persistent).')
    mig_v7.add_argument('--confirm-preflight', action='store_true',
                        help='Confirm read-only preflight checks were completed.')
    mig_v7.add_argument('--confirm-backup', action='store_true',
                        help='Confirm verified database backup was completed.')
    mig_v8 = sub.add_parser(
        'migrate-v8',
        help='Explicitly upgrade all tenant business stores to Business v8 (case assistant turns, PDF evidence + scan fields, legacy turn attachment backfill).',
    )
    mig_v8.add_argument('--db-path', type=Path, default=None,
                        help='Optional standalone SQLite business file path (defaults to all tenants under --output/persistent).')
    mig_v8.add_argument('--confirm-preflight', action='store_true',
                        help='Confirm read-only preflight checks were completed.')
    mig_v8.add_argument('--confirm-backup', action='store_true',
                        help='Confirm verified database backup was completed.')
    mig_v9 = sub.add_parser(
        'migrate-v9',
        help='Explicitly upgrade all tenant business stores to Business v9 (orders v9 + backfill, imported_events v2, 8 v9 integration tables).',
    )
    mig_v9.add_argument('--db-path', type=Path, default=None,
                        help='Optional standalone SQLite business file path (defaults to all tenants under --output/persistent).')
    mig_v9.add_argument('--confirm-preflight', action='store_true',
                        help='Confirm read-only preflight checks were completed.')
    mig_v9.add_argument('--confirm-backup', action='store_true',
                        help='Confirm verified database backup was completed.')
    sub.add_parser('check', help='Connect and verify identity and tenant business schema versions read-only.')
    outbox_st = sub.add_parser(
        'outbox-status',
        help='Read-only operator summary of pending, published, and dead integration_outbox events.',
    )
    outbox_st.add_argument('--db-path', type=Path, default=None,
                           help='Optional standalone SQLite business file path (defaults to all tenants under --output/persistent).')
    importer = sub.add_parser('import-sqlite', help='Import an offline persistent snapshot into an empty target.')
    importer.add_argument('--offline-snapshot', type=Path, required=True,
                          help='Copied persistent/ directory; stop source web and all writers before making the copy.')
    imp_ev = sub.add_parser(
        'import-events',
        help='Import a JSONL file of retailops-integration-v2 events into a tenant canonical store.',
    )
    imp_ev.add_argument('--tenant', required=True, help='Target tenant ID.')
    imp_ev.add_argument('--source-system', required=True, help='Connector source_system (e.g. marketplace_sim).')
    imp_ev.add_argument('--file', type=Path, required=True, help='Path to JSONL events file.')
    imp_ev.add_argument('--rebase-clock', choices=('now',), default=None,
                        help="Shift event timestamps by (import_now - latest_occurred_at).")
    purge_leg = sub.add_parser(
        'purge-legacy-demo',
        help='Remove legacy retailops_seed orders that have no linked order_action_requests.',
    )
    purge_leg.add_argument('--tenant', required=True, help='Target tenant ID.')
    purge_leg.add_argument('--dry-run', action='store_true',
                           help='Inspect and report removable vs retained legacy orders without mutating.')
    purge_rcp = sub.add_parser(
        'purge-expired-recipients',
        help='Purge encrypted recipient fields and phone_lookup_hmac past retention_until (manual operator run).',
    )
    purge_rcp.add_argument('--tenant', required=True, help='Target tenant ID.')
    purge_rcp.add_argument('--dry-run', action='store_true',
                           help='Report expired recipient rows without mutating.')
    exp_vreq = sub.add_parser(
        'export-voucher-requests',
        help='Export repeatable JSONL lines of voucher.requested events for all compensations in requested status.',
    )
    exp_vreq.add_argument('--tenant', required=True, help='Target tenant ID.')
    exp_vreq.add_argument('--source-system', required=True, help='Marketplace source_system (e.g. marketplace_sim).')


def run(args):
    from retailops.business.store import (
        _inspect_sqlite_business_ready,
        inspect_sqlite_outbox_status,
        migrate_sqlite_business_v5,
        migrate_sqlite_business_v6,
        migrate_sqlite_business_v7,
        migrate_sqlite_business_v8,
        migrate_sqlite_business_v9,
    )
    from retailops.config import database_settings
    from retailops.core import ApiError
    from retailops.storage.pg_repositories import (
        PostgresIdentityStore,
        inspect_postgres_outbox_status,
        migrate_postgres_business_v5,
        migrate_postgres_business_v6,
        migrate_postgres_business_v7,
        migrate_postgres_business_v8,
        migrate_postgres_business_v9,
    )
    from retailops.storage.postgres import BUSINESS_SCHEMA_CURRENT, IDENTITY_SCHEMA, tenant_schema, transaction

    backend, dsn = database_settings(os.environ)
    action = getattr(args, 'database_action', None)
    preflight_ok = bool(getattr(args, 'confirm_preflight', False))
    backup_ok = bool(getattr(args, 'confirm_backup', False))
    resolved_output = getattr(args, 'output', None) or Path(os.environ.get('RETAILOPS_OUTPUT') or 'artifacts')

    if action == 'outbox-status':
        if backend == 'sqlite':
            target = getattr(args, 'db_path', None) or resolved_output
            return inspect_sqlite_outbox_status(target)
        return inspect_postgres_outbox_status(dsn)

    if action == 'import-events':
        from retailops.integration.intake import import_events_jsonl

        if backend == 'postgresql':
            from retailops.identity.postgres import PostgresSessions

            sessions = PostgresSessions(dsn, data_root=Path(resolved_output))
        else:
            from retailops.identity.persistent import PersistentSessions

            out_root = Path(resolved_output)
            pers_dir = out_root / 'persistent' if (out_root / 'persistent').is_dir() or not (out_root / 'identity.sqlite3').is_file() else out_root
            sessions = PersistentSessions(pers_dir)
        return import_events_jsonl(
            sessions,
            tenant_id=args.tenant,
            source_system=args.source_system,
            jsonl_path=args.file,
            rebase_clock=args.rebase_clock,
        )

    if action == 'purge-legacy-demo':
        import time

        if backend == 'postgresql':
            from retailops.identity.postgres import PostgresSessions

            sessions = PostgresSessions(dsn, data_root=Path(resolved_output))
        else:
            from retailops.identity.persistent import PersistentSessions

            out_root = Path(resolved_output)
            pers_dir = out_root / 'persistent' if (out_root / 'persistent').is_dir() or not (out_root / 'identity.sqlite3').is_file() else out_root
            sessions = PersistentSessions(pers_dir)
        tenant_clean = str(args.tenant or '').strip()
        bstore = sessions.business_store(tenant_clean)
        report = bstore.purge_legacy_demo_orders(dry_run=bool(args.dry_run))
        if not args.dry_run:
            cache = getattr(sessions, 'tool_caches', {}).get(tenant_clean)
            if cache is not None and hasattr(cache, 'clear'):
                cache.clear()
            with sessions.control.connection(write=True) as id_db:
                sessions.control.record_admin_audit(
                    id_db,
                    actor_principal_id='cli-operator',
                    actor_role='operator',
                    tenant_id=tenant_clean,
                    target_membership_id=f'tenant:{tenant_clean}',
                    action='database.purge_legacy_demo',
                    outcome='allowed',
                    before_state={'would_remove_count': report['would_remove_count']},
                    after_state={
                        'removed_count': report['removed_count'],
                        'removed_order_ids': list(report.get('removed_order_ids', [])),
                        'retained_count': report['retained_count'],
                        'retained_order_ids': [r['order_id'] for r in report['retained_orders']],
                    },
                    reason='Operator purge-legacy-demo execution',
                    now=time.time(),
                )
        return report

    if action == 'purge-expired-recipients':
        import time

        if backend == 'postgresql':
            from retailops.identity.postgres import PostgresSessions

            sessions = PostgresSessions(dsn, data_root=Path(resolved_output))
        else:
            from retailops.identity.persistent import PersistentSessions

            out_root = Path(resolved_output)
            pers_dir = out_root / 'persistent' if (out_root / 'persistent').is_dir() or not (out_root / 'identity.sqlite3').is_file() else out_root
            sessions = PersistentSessions(pers_dir)
        tenant_clean = str(args.tenant or '').strip()
        bstore = sessions.business_store(tenant_clean)
        report = bstore.purge_expired_recipients(dry_run=bool(args.dry_run))
        if not args.dry_run:
            with sessions.control.connection(write=True) as id_db:
                sessions.control.record_admin_audit(
                    id_db,
                    actor_principal_id='cli-operator',
                    actor_role='operator',
                    tenant_id=tenant_clean,
                    target_membership_id=f'tenant:{tenant_clean}',
                    action='database.purge_expired_recipients',
                    outcome='allowed',
                    before_state={'would_purge_count': report['would_purge_count']},
                    after_state={
                        'purged_count': report['purged_count'],
                        'order_ids': list(report.get('order_ids', [])),
                    },
                    reason='Operator purge-expired-recipients execution',
                    now=time.time(),
                )
        return report

    if action == 'export-voucher-requests':
        if backend == 'postgresql':
            from retailops.identity.postgres import PostgresSessions

            sessions = PostgresSessions(dsn, data_root=Path(resolved_output))
        else:
            from retailops.identity.persistent import PersistentSessions

            out_root = Path(resolved_output)
            pers_dir = out_root / 'persistent' if (out_root / 'persistent').is_dir() or not (out_root / 'identity.sqlite3').is_file() else out_root
            sessions = PersistentSessions(pers_dir)
        tenant_clean = str(args.tenant or '').strip()
        bstore = sessions.business_store(tenant_clean)
        return bstore.export_voucher_requests(source_system=args.source_system)

    if action == 'migrate-v5':
        if backend == 'sqlite':
            target = getattr(args, 'db_path', None) or resolved_output
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

    if action == 'migrate-v6':
        if backend == 'sqlite':
            target = getattr(args, 'db_path', None) or resolved_output
            return migrate_sqlite_business_v6(
                target,
                preflight_confirmed=preflight_ok,
                backup_confirmed=backup_ok,
            )
        return migrate_postgres_business_v6(
            dsn,
            preflight_confirmed=preflight_ok,
            backup_confirmed=backup_ok,
        )

    if action == 'migrate-v7':
        if backend == 'sqlite':
            target = getattr(args, 'db_path', None) or resolved_output
            return migrate_sqlite_business_v7(
                target,
                preflight_confirmed=preflight_ok,
                backup_confirmed=backup_ok,
            )
        return migrate_postgres_business_v7(
            dsn,
            preflight_confirmed=preflight_ok,
            backup_confirmed=backup_ok,
        )

    if action == 'migrate-v8':
        if backend == 'sqlite':
            db_path = getattr(args, 'db_path', None)
            target = db_path or resolved_output
            return migrate_sqlite_business_v8(
                target,
                preflight_confirmed=preflight_ok,
                backup_confirmed=backup_ok,
                data_root=None if db_path is not None else Path(resolved_output),
            )
        return migrate_postgres_business_v8(
            dsn,
            preflight_confirmed=preflight_ok,
            backup_confirmed=backup_ok,
            data_root=Path(resolved_output),
        )

    if action == 'migrate-v9':
        if backend == 'sqlite':
            db_path = getattr(args, 'db_path', None)
            target = db_path or resolved_output
            return migrate_sqlite_business_v9(
                target,
                preflight_confirmed=preflight_ok,
                backup_confirmed=backup_ok,
                data_root=None if db_path is not None else Path(resolved_output),
            )
        return migrate_postgres_business_v9(
            dsn,
            preflight_confirmed=preflight_ok,
            backup_confirmed=backup_ok,
            data_root=Path(resolved_output),
        )

    if backend == 'sqlite' and action == 'check':
        out_root = Path(resolved_output)
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
                            "cần chạy database migrate-v9 với --confirm-preflight --confirm-backup.",
                        )
        return {'result': 'POSTGRES_SCHEMA_READY', 'version': 1, 'accounts_seeded': False}
    if action == 'migrate':
        from retailops.storage.pg_schema import initialize
        allow_upgrade = bool(preflight_ok and backup_ok)
        with identity.connection() as db:
            tenants = db.execute('SELECT storage_key FROM tenants').fetchall()
        for tenant in tenants:
            schema = tenant_schema(tenant['storage_key'])
            with transaction(dsn, schema, write=True) as db:
                initialize(
                    db,
                    schema,
                    'business',
                    allow_business_v5_upgrade=allow_upgrade,
                    allow_business_v6_upgrade=allow_upgrade,
                    allow_business_v7_upgrade=allow_upgrade,
                    allow_business_v8_upgrade=allow_upgrade,
                    allow_business_v9_upgrade=allow_upgrade,
                )
        return {'result': 'POSTGRES_MIGRATED', 'business_schema_version': BUSINESS_SCHEMA_CURRENT,
                'tenants': len(tenants)}
    return {'result': 'POSTGRES_SCHEMA_READY', 'version': 1, 'accounts_seeded': False}
