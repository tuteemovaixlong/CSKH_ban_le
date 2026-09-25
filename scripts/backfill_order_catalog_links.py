#!/usr/bin/env python3
"""Safe, idempotent backfill script linking orders to products by canonical name.
Supports both SQLite and PostgreSQL backends with dry-run mode.
Never modifies order status, amount, version, customer_id, or cancel_reason.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def backfill_sqlite(db_path: Path, dry_run: bool = False) -> dict:
    if not db_path.exists():
        return {"error": f"Database file not found: {db_path}"}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Check tables
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "orders" not in tables or "products" not in tables:
            return {"skipped": True, "reason": "orders or products table does not exist"}

        # Find orders needing backfill
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


def backfill_postgres(conn_str: str, schema: str = "retailops_business", dry_run: bool = False) -> dict:
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
                cur.execute("""
                    UPDATE orders 
                    SET product_id = (SELECT p.id FROM products p WHERE p.name = orders.name LIMIT 1)
                    WHERE product_id IS NULL AND EXISTS (SELECT 1 FROM products p WHERE p.name = orders.name)
                """)
                conn.commit()

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


def main():
    parser = argparse.ArgumentParser(description="Backfill product_id on orders safely and idempotently.")
    parser.add_argument("--db", help="Path to SQLite database file")
    parser.add_argument("--pg-url", default=os.environ.get("RETAILOPS_POSTGRES_DSN"), help="PostgreSQL connection string")
    parser.add_argument("--pg-schema", default="retailops_business", help="PostgreSQL business schema")
    parser.add_argument("--dry-run", action="store_true", help="Report without applying changes")
    args = parser.parse_args()

    results = []
    if args.pg_url:
        print("[*] Running backfill on PostgreSQL...")
        res = backfill_postgres(args.pg_url, args.pg_schema, dry_run=args.dry_run)
        results.append(res)
        print(f"    Total: {res.get('total_orders')}, Linked: {res.get('already_linked')}, Updated: {res.get('updated')}, Unmatched: {res.get('unmatched')}")

    sqlite_paths = []
    if args.db:
        sqlite_paths.append(Path(args.db))
    else:
        # Check standard runtime sqlite paths
        for p in [Path("/opt/retailops/business.sqlite3"), ROOT / "data" / "business.sqlite3"]:
            if p.exists():
                sqlite_paths.append(p)

    for p in sqlite_paths:
        print(f"[*] Running backfill on SQLite: {p}...")
        res = backfill_sqlite(p, dry_run=args.dry_run)
        results.append(res)
        print(f"    Total: {res.get('total_orders')}, Linked: {res.get('already_linked')}, Updated: {res.get('updated')}, Unmatched: {res.get('unmatched')}")

    if not results:
        print("[!] No active database specified or found. Use --db or --pg-url.")
        return 0

    mode_str = "DRY-RUN COMPLETE" if args.dry_run else "BACKFILL SUCCESS"
    print(f"\n[+] {mode_str}: All checked databases processed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
