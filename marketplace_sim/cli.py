"""Giao diện dòng lệnh CLI cho python -m marketplace_sim (W6.1a mục 0)."""

from __future__ import annotations

import argparse
import json
import sys
from typing import NoReturn, Sequence

from . import DEFAULT_DATA_DIR, DEFAULT_MERCHANT_ID, DEFAULT_SEED
from .contract import ContractError
from .sender import EndpointNotAllowedError, SecretFileError
from .simulator import MarketplaceSimulator, SimulatorError
from .state_machines import StateTransitionError


class CLIArgumentError(ValueError):
    """Lỗi tham số dòng lệnh."""


class VietnameseArgumentParser(argparse.ArgumentParser):
    """ArgumentParser trả thông báo lỗi tiếng Việt thay vì tiếng Anh mặc định."""

    def error(self, message: str) -> NoReturn:
        raise CLIArgumentError(f"Tham số dòng lệnh không hợp lệ: {message}")


def _positive_int(raw: str) -> int:
    try:
        val = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"'{raw}' không phải là số nguyên hợp lệ."
        ) from exc
    if val <= 0:
        raise argparse.ArgumentTypeError(
            f"Giá trị phải là số nguyên dương (nhận {val})."
        )
    return val


def _non_negative_int(raw: str) -> int:
    try:
        val = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"'{raw}' không phải là số nguyên hợp lệ."
        ) from exc
    if val < 0:
        raise argparse.ArgumentTypeError(
            f"Giá trị phải là số nguyên không âm (nhận {val})."
        )
    return val


def build_parser() -> VietnameseArgumentParser:
    parser = VietnameseArgumentParser(
        prog="python -m marketplace_sim",
        description="Bộ mô phỏng sàn thương mại điện tử, vận chuyển và cổng thanh toán (W6.1a).",
    )
    parser.add_argument(
        "--data-dir",
        dest="global_data_dir",
        default=None,
        help="Thư mục lưu kho dữ liệu SQLite (mặc định: .marketplace_sim/).",
    )

    subparsers = parser.add_subparsers(dest="command")

    # init
    p_init = subparsers.add_parser(
        "init", help="Khởi tạo kho SQLite và phát sự kiện catalog ban đầu."
    )
    p_init.add_argument("--data-dir", default=None)
    p_init.add_argument("--seed", type=_non_negative_int, default=DEFAULT_SEED)
    p_init.add_argument("--merchant-id", default=DEFAULT_MERCHANT_ID)

    # run
    p_run = subparsers.add_parser(
        "run", help="Sinh dữ liệu đơn hàng ngẫu nhiên có seed theo số ngày."
    )
    p_run.add_argument("--data-dir", default=None)
    p_run.add_argument("--days", type=_positive_int, required=True)

    # story
    p_story = subparsers.add_parser(
        "story", help="Chèn một kịch bản có tên tương đối so với đồng hồ."
    )
    p_story.add_argument("--data-dir", default=None)
    p_story.add_argument("name", help="Tên kịch bản trong 13 kịch bản chuẩn.")

    # advance
    p_adv = subparsers.add_parser(
        "advance", help="Tua đồng hồ giả lập và phát các sự kiện đến hạn."
    )
    p_adv.add_argument("--data-dir", default=None)
    p_adv.add_argument("--hours", type=_positive_int, required=True)

    # export
    p_exp = subparsers.add_parser(
        "export", help="Xuất toàn bộ sự kiện ra tệp JSONL theo thứ tự chuẩn."
    )
    p_exp.add_argument("--data-dir", default=None)
    p_exp.add_argument("--out", required=True)

    # ingest-requests
    p_ing = subparsers.add_parser(
        "ingest-requests",
        help="Đọc tệp JSONL các yêu cầu phát voucher từ RetailOps.",
    )
    p_ing.add_argument("--data-dir", default=None)
    p_ing.add_argument("--file", required=True)

    # send
    p_send = subparsers.add_parser(
        "send", help="Gửi các sự kiện chưa gửi tới endpoint loopback."
    )
    p_send.add_argument("--data-dir", default=None)
    p_send.add_argument("--endpoint", required=True)
    p_send.add_argument("--secret-file", required=True)

    # status
    p_stat = subparsers.add_parser(
        "status", help="In số sự kiện theo loại và trạng thái gửi."
    )
    p_stat.add_argument("--data-dir", default=None)

    return parser


def _resolve_data_dir(args: argparse.Namespace) -> str:
    sub_dir = getattr(args, "data_dir", None)
    glob_dir = getattr(args, "global_data_dir", None)
    chosen = sub_dir or glob_dir or DEFAULT_DATA_DIR
    if not str(chosen).strip():
        raise CLIArgumentError("Đường dẫn '--data-dir' không được để trống.")
    return str(chosen)


def _configure_utf8_stdio() -> None:
    """Make redirected CLI output UTF-8 on Windows as well as POSIX."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")


def main(argv: Sequence[str] | None = None) -> int:
    # subprocess callers consume CLI output as UTF-8. Windows otherwise inherits
    # the active ANSI code page for redirected streams unless PYTHONUTF8 is set.
    _configure_utf8_stdio()
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        if not args.command:
            raise CLIArgumentError(
                "Thiếu lệnh cần chạy (chọn một trong: init, run, story, advance, export, ingest-requests, send, status)."
            )

        data_dir = _resolve_data_dir(args)

        if args.command == "init":
            sim = MarketplaceSimulator.initialize(
                data_dir,
                seed=args.seed,
                merchant_id=args.merchant_id,
            )
            info = sim.get_status()
            print(
                json.dumps(
                    {
                        "ok": True,
                        "command": "init",
                        "data_dir": data_dir,
                        "seed": info["seed"],
                        "merchant_id": info["merchant_id"],
                        "clock_iso": info["clock_iso"],
                        "events_created": info["total_events"],
                    },
                    ensure_ascii=False,
                )
            )
            return 0

        sim = MarketplaceSimulator(data_dir)

        if args.command == "run":
            res = sim.run_days(args.days)
            print(
                json.dumps(
                    {"ok": True, "command": "run", "days": args.days, **res},
                    ensure_ascii=False,
                )
            )
            return 0

        if args.command == "story":
            res = sim.insert_story(args.name)
            print(
                json.dumps(
                    {"ok": True, "command": "story", **res},
                    ensure_ascii=False,
                )
            )
            return 0

        if args.command == "advance":
            res = sim.advance_hours(args.hours)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "command": "advance",
                        "hours": args.hours,
                        **res,
                    },
                    ensure_ascii=False,
                )
            )
            return 0

        if args.command == "export":
            count = sim.export_events(args.out)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "command": "export",
                        "out": args.out,
                        "exported_events": count,
                    },
                    ensure_ascii=False,
                )
            )
            return 0

        if args.command == "ingest-requests":
            res = sim.ingest_voucher_requests(args.file)
            for err in res["errors"]:
                print(
                    f"Lỗi yêu cầu voucher bị bỏ qua: {err}",
                    file=sys.stderr,
                )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "command": "ingest-requests",
                        "issued": res["issued"],
                        "duplicates": res["duplicates"],
                        "skipped_errors": len(res["errors"]),
                    },
                    ensure_ascii=False,
                )
            )
            return 0

        if args.command == "send":
            res = sim.send_pending_events(
                endpoint=args.endpoint,
                secret_file=args.secret_file,
            )
            print(
                json.dumps(
                    {"ok": True, "command": "send", **res},
                    ensure_ascii=False,
                )
            )
            return 0

        if args.command == "status":
            info = sim.get_status()
            print(json.dumps(info, ensure_ascii=False, indent=2))
            return 0

        raise CLIArgumentError(f"Lệnh không được hỗ trợ: {args.command}")

    except (
        CLIArgumentError,
        SimulatorError,
        ContractError,
        EndpointNotAllowedError,
        SecretFileError,
        StateTransitionError,
    ) as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 2
