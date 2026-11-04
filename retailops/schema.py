"""Transactional schema initialization for legacy and new SQLite databases.

Backend schema version mapping for Phase R1 W2/W3/W3.2/W4:
- SQLite business schema current:     7 (logical Business v8; SQLite 6 = v7, 5 = v6, 4 = v5)
- PostgreSQL business schema current: 8 (logical Business v8; PostgreSQL 7 = v7, 6 = v6, 5 = v5)
- SQLite identity schema current:     5
- PostgreSQL identity schema current: 5
"""
from retailops.business.schema import SQLITE_BUSINESS_SCHEMA_CURRENT


def migrate(db, component, initialize, *, target_version=None):
    # Caller holds BEGIN IMMEDIATE; DDL and the marker commit or roll back together.
    db.execute('CREATE TABLE IF NOT EXISTS retailops_schema (component TEXT PRIMARY KEY, version INTEGER NOT NULL)')
    rows = db.execute('SELECT component,version FROM retailops_schema').fetchall()
    if rows and (len(rows) != 1 or rows[0]['component'] != component):
        raise ValueError('Database belongs to another RetailOps component.')
    version = rows[0]['version'] if rows else 0
    max_supported = SQLITE_BUSINESS_SCHEMA_CURRENT if component == 'business' else 5
    target = max_supported if target_version is None else int(target_version)
    if version not in range(max_supported + 1) or target not in range(1, max_supported + 1):
        raise ValueError('Unsupported database schema version; use the matching application version.')
    if version == 0:
        had_memberships = False
        had_business_tables = False
        if component == 'identity':
            had_memberships = bool(
                db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memberships'").fetchone()
            )
        elif component == 'business':
            had_business_tables = bool(
                db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name IN ('orders','conversations','proposals','business_events','products')"
                ).fetchone()
            )
        initialize(db)
        if component == 'business' and not had_business_tables:
            from retailops.workflow.schema import initialize as graph_schema
            from retailops.business.schema import ensure_case_tables, ensure_order_action_tables
            graph_schema(db)
            ensure_case_tables(db)
            if target >= 5:
                ensure_order_action_tables(db)
            initial_version = target
        else:
            initial_version = 1 if (had_business_tables or had_memberships) else target
        db.execute(
            'INSERT INTO retailops_schema VALUES (?,?) ON CONFLICT(component) DO UPDATE SET version=excluded.version',
            (component, initial_version),
        )
        version = initial_version

    if component == 'business' and version < 2 and target >= 2:
        from retailops.workflow.schema import initialize as graph_schema
        graph_schema(db)
        db.execute("UPDATE retailops_schema SET version=2 WHERE component='business'")
        version = 2

    if component == 'business' and version < 3 and target >= 3:
        from retailops.business.schema import migrate_v3
        migrate_v3(db)
        db.execute("UPDATE retailops_schema SET version=3 WHERE component='business'")
        version = 3

    if component == 'business' and version < 4 and target >= 4:
        from retailops.business.schema import backfill_business_v5_cases, ensure_case_tables
        ensure_case_tables(db)
        backfill_business_v5_cases(db)
        db.execute("UPDATE retailops_schema SET version=4 WHERE component='business'")
        version = 4

    if component == 'business' and version < 5 and target >= 5:
        from retailops.business.schema import ensure_order_action_tables
        ensure_order_action_tables(db)
        db.execute("UPDATE retailops_schema SET version=5 WHERE component='business'")
        version = 5

    if component == 'business' and version < 6 and target >= 6:
        # Business v7 (W3.2-D6): rewrite the W3 request table to the general-exchange shape. Needs
        # PRAGMA foreign_keys=OFF before BEGIN, which the operator migration sets.
        from retailops.business.schema import ensure_order_action_tables, migrate_order_action_exchange_v7
        migrate_order_action_exchange_v7(db)
        ensure_order_action_tables(db)
        db.execute("UPDATE retailops_schema SET version=6 WHERE component='business'")
        version = 6

    if component == 'business' and version < 7 and target >= 7:
        # Business v8 (W4-D9): partitioned case_assist_turns + order_action_evidence PDF/scan shape.
        from retailops.business.schema import (
            ensure_case_assist_tables,
            ensure_order_action_tables,
            migrate_order_action_evidence_v8,
        )
        migrate_order_action_evidence_v8(db)
        ensure_order_action_tables(db)
        ensure_case_assist_tables(db)
        db.execute("UPDATE retailops_schema SET version=7 WHERE component='business'")
