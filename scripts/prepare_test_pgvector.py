#!/usr/bin/env python3
"""Create pgvector in the disposable CI database before integration tests."""
import os

DSN = os.environ.get("RETAILOPS_TEST_DATABASE_URL", "")
if not DSN:
    raise SystemExit("RETAILOPS_TEST_DATABASE_URL is required")

import psycopg
from psycopg import sql

options = psycopg.conninfo.conninfo_to_dict(DSN)
if not options.get("dbname", "").startswith("retailops_test"):
    raise SystemExit("Refusing to prepare pgvector outside a retailops_test* database")

with psycopg.connect(DSN, autocommit=True) as connection:
    connection.execute("CREATE SCHEMA IF NOT EXISTS retailops_extensions")
    row = connection.execute("""SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
        WHERE e.extname='vector'""").fetchone()
    if row and row[0] != "retailops_extensions":
        connection.execute("DROP EXTENSION vector")
        row = None
    if not row:
        connection.execute(sql.SQL("CREATE EXTENSION vector WITH SCHEMA {}")
                           .format(sql.Identifier("retailops_extensions")))
    version = connection.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0]
print("TEST_PGVECTOR_READY=" + version)
