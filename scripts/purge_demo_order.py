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
from retailops.storage.postgres import validate_dsn


def _resolve_storage_target(args: argparse.Namespace) -> tuple[str, str]:
    raw_backend_env = os.environ.get("RETAILOPS_STORAGE_BACKEND")
    backend_env = raw_backend_env.strip() if raw_backend_env is not None else ""
    if raw_backend_env and not backend_env:
        raise ApiError(
            503,
            "database_configuration_invalid",
            "RETAILOPS_STORAGE_BACKEND không hợp lệ hoặc chỉ chứa khoảng trắng.",
        )
    if backend_env and backend_env not in ("sqlite", "postgresql"):
        raise ApiError(
            503,
            "database_configuration_invalid",
            "Giá trị RETAILOPS_STORAGE_BACKEND không hợp lệ; chỉ chấp nhận 'postgresql' hoặc 'sqlite'.",
        )

    raw_url = os.environ.get("RETAILOPS_DATABASE_URL", "")
    raw_url_file = os.environ.get("RETAILOPS_DATABASE_URL_FILE", "")
    if raw_url and not raw_url.strip():
        raise ApiError(
            503,
            "database_configuration_invalid",
            "RETAILOPS_DATABASE_URL không hợp lệ hoặc chỉ chứa khoảng trắng.",
        )
    if raw_url_file and not raw_url_file.strip():
        raise ApiError(
            503,
            "database_configuration_invalid",
            "RETAILOPS_DATABASE_URL_FILE không hợp lệ hoặc chỉ chứa khoảng trắng.",
        )

    has_url = bool(raw_url.strip())
    has_url_file = bool(raw_url_file.strip())
    if has_url and has_url_file:
        raise ApiError(
            503,
            "database_configuration_invalid",
            "Xung đột cấu hình: không được đặt đồng thời RETAILOPS_DATABASE_URL và RETAILOPS_DATABASE_URL_FILE.",
        )

    has_pg_source = has_url or has_url_file
    env_data_dir = os.environ.get("RETAILOPS_DATA_DIR", "").strip()
    explicit_cli_data_dir = args.data_dir is not None
    cli_data_dir = (args.data_dir or "").strip()
    has_sqlite_dir = explicit_cli_data_dir or bool(env_data_dir)

    if backend_env == "sqlite" and has_pg_source:
        raise ApiError(
            503,
            "database_configuration_invalid",
            "Xung đột cấu hình: RETAILOPS_STORAGE_BACKEND=sqlite không được đi kèm PostgreSQL DSN.",
        )
    if has_pg_source and has_sqlite_dir:
        raise ApiError(
            503,
            "database_configuration_invalid",
            "Xung đột cấu hình: không được chỉ định đồng thời PostgreSQL DSN và --data-dir / RETAILOPS_DATA_DIR.",
        )

    if backend_env == "postgresql" or has_pg_source:
        if not has_pg_source:
            raise ApiError(
                503,
                "database_configuration_missing",
                "RETAILOPS_STORAGE_BACKEND=postgresql yêu cầu RETAILOPS_DATABASE_URL hoặc RETAILOPS_DATABASE_URL_FILE hợp lệ.",
            )
        if explicit_cli_data_dir or env_data_dir:
            raise ApiError(
                503,
                "database_configuration_invalid",
                "Xung đột cấu hình: RETAILOPS_STORAGE_BACKEND=postgresql không được đi kèm --data-dir / RETAILOPS_DATA_DIR.",
            )
        if has_url_file:
            path = Path(raw_url_file.strip())
            try:
                if not path.exists():
                    raise ApiError(
                        503,
                        "database_configuration_missing",
                        "Tệp cấu hình PostgreSQL được khai báo nhưng không tồn tại.",
                    )
                if not path.is_file():
                    raise ApiError(
                        503,
                        "database_configuration_invalid",
                        "Đường dẫn RETAILOPS_DATABASE_URL_FILE không phải là tệp hợp lệ.",
                    )
                dsn = path.read_text(encoding="utf-8").strip()
            except ApiError:
                raise
            except (OSError, UnicodeError):
                raise ApiError(
                    503,
                    "database_configuration_invalid",
                    "Không thể đọc tệp cấu hình PostgreSQL đã khai báo.",
                ) from None
            if not dsn:
                raise ApiError(
                    503,
                    "database_configuration_missing",
                    "Tệp cấu hình PostgreSQL được khai báo nhưng rỗng.",
                )
        else:
            dsn = raw_url.strip()

        try:
            validate_dsn(dsn)
        except ValueError:
            raise ApiError(
                503,
                "database_configuration_invalid",
                "Cấu hình kết nối PostgreSQL không hợp lệ; chi tiết kết nối đã được ẩn.",
            ) from None
        return "postgresql", dsn

    data_dir = cli_data_dir if explicit_cli_data_dir else env_data_dir
    if not data_dir:
        raise ApiError(
            503,
            "database_configuration_missing",
            "Không có PostgreSQL DSN; SQLite chỉ được dùng khi chỉ định rõ --data-dir hoặc RETAILOPS_DATA_DIR.",
        )
    return "sqlite", data_dir


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
        default=None,
        help="Explicit operator identifier recorded in business_events and tombstone (required with --execute)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Explicit SQLite data directory for local/synthetic use when PostgreSQL is not configured",
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
    try:
        operator_id = (args.operator_id or "").strip()
        if args.execute and not operator_id:
            raise ApiError(
                400,
                "purge_operator_required",
                "Chế độ thực thi (--execute) bắt buộc phải có --operator-id để lưu kiểm toán.",
            )
        backend, target = _resolve_storage_target(args)
        if backend == "postgresql":
            sessions = PostgresSessions(target, maintenance=False, read_only=not args.execute)
        else:
            sessions = PersistentSessions(
                Path(target),
                maintenance=False,
                read_only=not args.execute,
            )
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
            operator_id=operator_id,
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
    except (OSError, ValueError):
        _emit_json(
            {
                "status": "aborted",
                "http_status": 503,
                "error": "database_configuration_invalid",
                "message": "Không thể mở cấu hình hoặc kho dữ liệu đã khai báo; thao tác đã dừng.",
            },
            stream=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
