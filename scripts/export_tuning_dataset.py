#!/usr/bin/env python3
"""Export curated training datasets (SFT and DPO) from RetailOps feedback and turn records."""
import argparse
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from retailops.business.export import connect_database, export_datasets


def main():
    parser = argparse.ArgumentParser(description="Export SFT and DPO datasets from RetailOps database")
    parser.add_argument("--db-path", help="Path to SQLite database file")
    parser.add_argument("--output-dir", default=str(ROOT / "data"), help="Directory to store .jsonl exports")
    parser.add_argument("--min-rating", type=int, default=4, help="Minimum rating for positive/SFT examples (1-5)")
    args = parser.parse_args()

    try:
        conn = connect_database(args.db_path)
        print(f"[*] Connected to database successfully.")
        stats = export_datasets(conn, args.output_dir, args.min_rating)
        print(f"[+] SFT Dataset exported: {stats['sft_samples']} samples -> {stats['sft_path']}")
        print(f"[+] DPO Dataset exported: {stats['dpo_samples']} samples -> {stats['dpo_path']}")
    except Exception as e:
        print(f"[!] Export failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
