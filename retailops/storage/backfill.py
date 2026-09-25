"""Safe, idempotent backfill utility linking orders to products by canonical name.
Supports both SQLite and PostgreSQL backends with dry-run mode.
Never modifies order status, amount, version, customer_id, or cancel_reason.
"""
import sqlite3
from pathlib import Path
from typing import Any, Dict


def backfill_sqlite(db_path: Path, dry_run: bool = False) -> Dict[str, Any]:
    db_path = Path(db_path)
    if not db_path.exists():
        return {"error": f"Database file not found: {db_path}"}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "orders" not in tables or "products" not in tables:
            return {"skipped": True, "reason": "orders or products table does not exist"}

        candidates = conn.execute("""
            SELECT o.id, o.name, p.id AS matched_pid
            FROM orders o
            JOIN products p ON p.name = o.name
            WHERE o.product_id IS NULL
        """).fetchall()

        unmatched = conn.execute("""
            SELECT COUNT(*) AS cnt
            FROM orders o
            WHERE o.product_id IS NULL AND NOT EXISTS (
                SELECT 1 FROM products p WHERE p.name = o.name
            )
        """).fetchone()["cnt"]

        total_orders = conn.execute("SELECT COUNT(*) AS cnt FROM orders").fetchone()["cnt"]
        already_linked = conn.execute("SELECT COUNT(*) AS cnt FROM orders WHERE product_id IS NOT NULL").fetchone()["cnt"]

        if not dry_run and candidates:
            with conn:
                conn.execute("""
                    UPDATE orders 
                    SET product_id = (SELECT p.id FROM products p WHERE p.name = orders.name LIMIT 1)
                    WHERE product_id IS NULL AND EXISTS (SELECT 1 FROM products p WHERE p.name = orders.name)
                """)

        return {
            "backend": "sqlite",
            "db_path": str(db_path),
            "total_orders": total_orders,
            "already_linked": already_linked,
            "to_update": len(candidates),
            "updated": 0 if dry_run else len(candidates),
            "unmatched": unmatched,
            "dry_run": dry_run,
        }
    finally:
        conn.close()


def backfill_postgres(conn_str: str, schema: str = "retailops_business", dry_run: bool = False) -> Dict[str, Any]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        return {"error": "psycopg package not available for postgres backfill"}

    with psycopg.connect(conn_str, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL search_path TO {schema}, pg_catalog")

            cur.execute("""
                SELECT o.id, o.name, p.id AS matched_pid
                FROM orders o
                JOIN products p ON p.name = o.name
                WHERE o.product_id IS NULL
            """)
            candidates = cur.fetchall()

            cur.execute("""
                SELECT COUNT(*) AS cnt
                FROM orders o
                WHERE o.product_id IS NULL AND NOT EXISTS (
                    SELECT 1 FROM products p WHERE p.name = o.name
                )
            """)
            unmatched = cur.fetchone()["cnt"]

            cur.execute("SELECT COUNT(*) AS cnt FROM orders")
            total_orders = cur.fetchone()["cnt"]
            cur.execute("SELECT COUNT(*) AS cnt FROM orders WHERE product_id IS NOT NULL")
            already_linked = cur.fetchone()["cnt"]

            if not dry_run and candidates:
                with conn.transaction():
                    cur.execute("""
                        UPDATE orders 
                        SET product_id = (SELECT p.id FROM products p WHERE p.name = orders.name LIMIT 1)
                        WHERE product_id IS NULL AND EXISTS (SELECT 1 FROM products p WHERE p.name = orders.name)
                    """)

            return {
                "backend": "postgres",
                "schema": schema,
                "total_orders": total_orders,
                "already_linked": already_linked,
                "to_update": len(candidates),
                "updated": 0 if dry_run else len(candidates),
                "unmatched": unmatched,
                "dry_run": dry_run,
            }
