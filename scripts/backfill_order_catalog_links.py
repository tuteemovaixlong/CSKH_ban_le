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


from retailops.storage.backfill import backfill_sqlite, backfill_postgres



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
