"""Operator CLI for per-tenant integration connectors: add, disable, list, check (W6.1b-D5)."""

from __future__ import annotations

import os
from pathlib import Path

from retailops.config import database_settings
from retailops.core import ApiError
from retailops.identity.persistent import PersistentSessions
from retailops.integration.connectors import CONNECTOR_KINDS, ConnectorManager


def add_parser(commands) -> None:
    parser = commands.add_parser(
        "connector",
        help="Manage tenant integration connectors and verify signing/digest secret files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.environ.get("RETAILOPS_OUTPUT", "/data")),
        help="Same RETAILOPS_OUTPUT directory as the public web process.",
    )
    actions = parser.add_subparsers(dest="connector_action", required=True)

    p_add = actions.add_parser("add", help="Add or update a tenant integration connector.")
    p_add.add_argument("--tenant", required=True)
    p_add.add_argument("--source-system", default="marketplace_sim")
    p_add.add_argument("--kind", choices=CONNECTOR_KINDS, default="marketplace")
    p_add.add_argument("--merchant-id", default="MERCHANT-SIM-001")
    p_add.add_argument("--secret-ref", default=None)
    p_add.add_argument("--status-mapping-file", type=Path, default=None)

    p_dis = actions.add_parser("disable", help="Disable an integration connector.")
    p_dis.add_argument("--tenant", required=True)
    p_dis.add_argument("--source-system", required=True)

    p_list = actions.add_parser("list", help="List tenant connectors without exposing secrets.")
    p_list.add_argument("--tenant", required=True)

    p_check = actions.add_parser(
        "check",
        help="Verify enabled connector signing keys and event digest key.",
    )
    p_check.add_argument("--tenant", default=None)


def _open_sessions(args):
    backend, dsn = database_settings(os.environ)
    if backend == "postgresql":
        from retailops.identity.postgres import PostgresSessions

        return PostgresSessions(dsn, data_root=args.output)
    return PersistentSessions(args.output / "persistent")


def run(args) -> dict:
    sessions = _open_sessions(args)
    mgr = ConnectorManager(sessions)
    action = args.connector_action
    if action == "add":
        connector = mgr.add_connector(
            args.tenant,
            source_system=args.source_system,
            kind=args.kind,
            merchant_id=args.merchant_id,
            secret_ref=args.secret_ref,
            status_mapping_file=args.status_mapping_file,
        )
        return {"result": "CONNECTOR_READY", "tenant_id": args.tenant, "connector": connector}
    if action == "disable":
        connector = mgr.disable_connector(
            args.tenant,
            source_system=args.source_system,
        )
        return {"result": "CONNECTOR_DISABLED", "tenant_id": args.tenant, "connector": connector}
    if action == "list":
        items = mgr.list_connectors(args.tenant, record_audit=True)
        return {"result": "CONNECTOR_LIST", "tenant_id": args.tenant, "connectors": items}
    if action == "check":
        report = mgr.check_connectors(tenant_id=args.tenant)
        if not report["ok"]:
            reasons = "; ".join(
                f"{item['scope']}:{item['tenant_id']}:{item['source_system']}={item['reason']}"
                for item in report["issues"]
            )
            raise ApiError(503, "connector_check_failed", reasons)
        return {"result": "CONNECTOR_CHECK_OK", **report}
    return {"result": "UNKNOWN_ACTION"}
