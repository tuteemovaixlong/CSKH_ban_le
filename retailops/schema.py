"""Transactional schema initialization for legacy and new SQLite databases."""


def migrate(db, component, initialize):
    # Caller holds BEGIN IMMEDIATE; DDL and the marker commit or roll back together.
    db.execute('CREATE TABLE IF NOT EXISTS retailops_schema (component TEXT PRIMARY KEY, version INTEGER NOT NULL)')
    rows = db.execute('SELECT component,version FROM retailops_schema').fetchall()
    if rows and (len(rows) != 1 or rows[0]['component'] != component):
        raise ValueError('Database belongs to another RetailOps component.')
    version = rows[0]['version'] if rows else 0
    target = 3 if component == 'business' else 5
    if version not in range(target + 1):
        raise ValueError('Unsupported database schema version; use the matching application version.')
    if version == 0:
        had_memberships = False
        if component == 'identity':
            had_memberships = bool(
                db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memberships'").fetchone()
            )
        initialize(db)
        initial_version = 1 if (component == 'business' or had_memberships) else target
        db.execute(
            'INSERT INTO retailops_schema VALUES (?,?) ON CONFLICT(component) DO UPDATE SET version=excluded.version',
            (component, initial_version),
        )

    if component == 'business' and version < 2:
        from retailops.workflow.schema import initialize as graph_schema
        graph_schema(db)
        db.execute("UPDATE retailops_schema SET version=2 WHERE component='business'")

    if component == 'business' and version < 3:
        from retailops.business.schema import migrate_v3
        migrate_v3(db)
        db.execute("UPDATE retailops_schema SET version=3 WHERE component='business'")
