#!/usr/bin/env python3
"""One-shot fail-closed targeted demo order purge CLI (Phase 5 Fix A).

Defaults to --dry-run unless --execute is explicitly supplied.
Requires full target tuple: tenant_id, order_id, customer_id, product_id,
status, amount, and snapshot_name.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from retailops.core import ApiError
from retailops.identity.persistent import PersistentSessions
from retailops.identity.postgres import PostgresSessions


def _resolve_dsn() -> str | None:
    dsn = os.environ.get("RETAILOPS_DATABASE_URL", "").strip()
    if dsn:
        return dsn
    dsn_file = os.environ.get("RETAILOPS_DATABASE_URL_FILE", "").strip()
    if dsn_file and Path(dsn_file).is_file():
        return Path(dsn_file).read_text(encoding="utf-8").strip()
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Targeted fail-closed demo order purge with dry-run default."
    )
    parser.add_argument("--tenant-id", required=True, help="Target tenant ID")
    parser.add_argument("--order-id", required=True, help="Expected order ID (e.g. O-819126)")
    parser.add_argument("--customer-id", required=True, help="Expected customer ID (e.g. CG-d9b82ffe)")
    parser.add_argument("--product-id", required=True, help="Expected product ID (e.g. P-602)")
    parser.add_argument("--status", required=True, help="Expected order status (e.g. delivered)")
    parser.add_argument("--amount", required=True, type=int, help="Expected order amount in VND (e.g. 520000)")
    parser.add_argument(
        "--snapshot-name",
        required=True,
        help="Expected denormalized order snapshot name",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Execute the purge transaction (defaults to read-only dry-run when omitted)",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Mandatory operator audit reason when --execute is set",
    )
    parser.add_argument(
        "--operator-id",
        default="cli-operator",
        help="Operator identifier recorded in business_events and tombstone",
    )
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("RETAILOPS_DATA_DIR", ""),
        help="SQLite persistent data directory (used when PostgreSQL DSN is not configured)",
    )
    return parser


def _emit_json(payload: dict, *, stream=None) -> None:
    target = stream if stream is not None else sys.stdout
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if hasattr(target, "buffer"):
        target.buffer.write(text.encode("utf-8"))
        target.flush()
    else:
        target.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    dsn = _resolve_dsn()
    if dsn:
        sessions = PostgresSessions(dsn)
    else:
        data_dir = Path(args.data_dir) if args.data_dir else (ROOT / "var" / "persistent")
        sessions = PersistentSessions(data_dir)

    try:
        result = sessions.purge_demo_order(
            tenant_id=args.tenant_id,
            order_id=args.order_id,
            customer_id=args.customer_id,
            product_id=args.product_id,
            status=args.status,
            amount=int(args.amount),
            snapshot_name=args.snapshot_name,
            execute=bool(args.execute),
            reason=args.reason,
            operator_id=args.operator_id,
        )
        _emit_json(result, stream=sys.stdout)
        return 0
    except ApiError as exc:
        err_payload = {
            "status": "aborted",
            "http_status": exc.status,
            "error": exc.code,
            "message": exc.message,
        }
        _emit_json(err_payload, stream=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
