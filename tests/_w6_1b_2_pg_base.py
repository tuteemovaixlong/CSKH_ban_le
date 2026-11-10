"""Shared real-PostgreSQL test harness for Phase R1 W6.1b-2 (Items 1, 4, 5, 8).

Never skips in CI jobs that set `RETAILOPS_REQUIRE_PG_TESTS=1` (`ci.yml` offline, `ops-console.yml`
postgres); skips elsewhere, such as the deploy workflow, when `RETAILOPS_TEST_DATABASE_URL` is unset.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

DSN = os.environ.get("RETAILOPS_TEST_DATABASE_URL", "").strip()
REQUIRE_PG_TESTS = os.environ.get("RETAILOPS_REQUIRE_PG_TESTS", "").strip() == "1"


def pg_test_enabled() -> bool:
    return bool(DSN) or REQUIRE_PG_TESTS


class RealPostgresW61b2Base(unittest.TestCase):
    """Base TestCase provisioning a disposable PostgreSQL schema per test."""

    @classmethod
    def setUpClass(cls) -> None:
        if not DSN:
            raise AssertionError(
                "RETAILOPS_TEST_DATABASE_URL must be set when RETAILOPS_REQUIRE_PG_TESTS=1; PostgreSQL tests for W6.1b-2 must not skip in that job."
            )
        import psycopg
        from scripts.postgres_test_guard import require_disposable_postgres_test_target

        require_disposable_postgres_test_target(DSN, psycopg.conninfo.conninfo_to_dict)

    def clear_pg_schemas(self) -> None:
        from psycopg import sql
        from retailops.storage.postgres import IDENTITY_SCHEMA, transaction

        with transaction(DSN, write=True) as db:
            names = db.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname=? OR nspname ~ '^tenant_[a-f0-9]{32}$'",
                (IDENTITY_SCHEMA,),
            ).fetchall()
            for row in names:
                db.raw.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(row["nspname"]))
                )

    def setUp(self) -> None:
        from retailops.identity.postgres import PostgresSessions
        from retailops.storage.pg_repositories import PostgresIdentityStore
        from retailops.storage.postgres import tenant_schema

        self.temp = tempfile.TemporaryDirectory(prefix="r1-w61b2-realpg-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dsn = DSN
        self.clear_pg_schemas()
        self.addCleanup(self.clear_pg_schemas)
        PostgresIdentityStore(DSN, create=True)
        self.sessions = PostgresSessions(DSN, api_daily_limit=5, data_root=self.root / "data")
        self.store = self.sessions.provision_tenant("shop-demo", "Shop Demo", seed_demo=False)
        self.storage_key = self.sessions.control.tenant("shop-demo")["storage_key"]
        self.tenant_schema_name = tenant_schema(self.storage_key)

    def assert_no_plaintext_in_all_pg_schemas(self, forbidden_Substrings: list[str]) -> int:
        from psycopg import sql
        from retailops.storage.postgres import IDENTITY_SCHEMA, transaction

        scanned_rows = 0
        with transaction(DSN, write=False) as db:
            tables = db.execute(
                """SELECT table_schema, table_name
                   FROM information_schema.tables
                   WHERE table_type='BASE TABLE'
                     AND (table_schema = ? OR table_schema ~ '^tenant_[a-f0-9]{32}$')
                   ORDER BY table_schema, table_name""",
                (IDENTITY_SCHEMA,),
            ).fetchall()
            for tbl in tables:
                sc = tbl["table_schema"]
                tn = tbl["table_name"]
                rows = db.raw.execute(
                    sql.SQL("SELECT * FROM {}.{}").format(
                        sql.Identifier(sc), sql.Identifier(tn)
                    )
                ).fetchall()
                for row in rows:
                    scanned_rows += 1
                    dumped = json.dumps(dict(row), ensure_ascii=False, default=str)
                    for needle in forbidden_Substrings:
                        self.assertNotIn(needle, dumped, f"Plaintext leaked in {sc}.{tn}")
        return scanned_rows
