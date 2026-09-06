"""Portable graph tables, installed by business schema migration v2."""

DDL = (
    '''CREATE TABLE graph_runs (
        id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
        fingerprint TEXT NOT NULL, seed TEXT NOT NULL, expires_at DOUBLE PRECISION NOT NULL,
        lease_owner TEXT, lease_until DOUBLE PRECISION NOT NULL DEFAULT 0)''',
    '''CREATE TABLE graph_checkpoints (
        run_id TEXT NOT NULL REFERENCES graph_runs(id) ON DELETE CASCADE,
        checkpoint_id TEXT NOT NULL, parent_id TEXT, checkpoint TEXT NOT NULL, metadata TEXT NOT NULL,
        PRIMARY KEY(run_id,checkpoint_id))''',
    '''CREATE TABLE graph_writes (
        run_id TEXT NOT NULL, checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL,
        idx INTEGER NOT NULL, channel TEXT NOT NULL, value TEXT NOT NULL,
        PRIMARY KEY(run_id,checkpoint_id,task_id,idx),
        FOREIGN KEY(run_id) REFERENCES graph_runs(id) ON DELETE CASCADE)''',
)


def initialize(db):
    for statement in DDL:
        db.execute(statement)
