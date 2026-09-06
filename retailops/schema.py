"""Transactional schema initialization for legacy and new SQLite databases."""


def migrate(db, component, initialize):
    # Caller holds BEGIN IMMEDIATE; DDL and the marker commit or roll back together.
    db.execute('CREATE TABLE IF NOT EXISTS retailops_schema (component TEXT PRIMARY KEY, version INTEGER NOT NULL)')
    rows = db.execute('SELECT component,version FROM retailops_schema').fetchall()
    if rows and (len(rows) != 1 or rows[0]['component'] != component):
        raise ValueError('Database belongs to another RetailOps component.')
    version = rows[0]['version'] if rows else 0
    target = 2 if component == 'business' else 1
    if version not in range(target + 1):
        raise ValueError('Unsupported database schema version; use the matching application version.')
    if version == 0:
        initialize(db)
        db.execute('INSERT INTO retailops_schema VALUES (?,1) ON CONFLICT(component) DO UPDATE SET version=1', (component,))

    if component == 'business' and version < 2:
        from retailops.workflow.schema import initialize as graph_schema
        graph_schema(db)
        db.execute("UPDATE retailops_schema SET version=2 WHERE component='business'")
