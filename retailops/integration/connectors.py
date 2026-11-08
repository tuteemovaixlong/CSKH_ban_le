"""Per-tenant integration connector registry, signing key validation, and raw status mapping (W6.1b-D5)."""

from __future__ import annotations

from collections.abc import Mapping
import json
import logging
import os
from pathlib import Path
import re
import stat
import time
from typing import Any
import uuid

from retailops.core import ApiError, require
from retailops.integration.ingest import MIN_SECRET_KEY_BYTES, read_regular_secret_file

logger = logging.getLogger("retailops_integration")

REPO_ROOT = Path(__file__).resolve().parents[2]
CONNECTORS_DATA_DIR = REPO_ROOT / "data" / "connectors"

CONNECTOR_KINDS = ("marketplace", "carrier", "payment")
SOURCE_SYSTEM_RE = re.compile(r"^[a-z0-9_]{1,64}$")
SECRET_REF_RE = re.compile(r"^retailops_connector_[a-z0-9_]{1,64}$")

CANONICAL_ORDER_STATUSES = frozenset({"pending", "shipping", "delivered", "cancelled"})
CANONICAL_SHIPMENT_STATUSES = frozenset(
    {
        "created",
        "picked_up",
        "in_transit",
        "out_for_delivery",
        "delivered",
        "delivery_failed",
        "returning",
        "returned",
        "cancelled",
    }
)
CANONICAL_PAYMENT_STATUSES = frozenset({"pending", "succeeded", "failed", "cancelled"})
CANONICAL_REFUND_STATUSES = frozenset({"pending", "processing", "completed", "failed"})


def validate_source_system_name(source_system: str) -> str:
    clean = str(source_system or "").strip()
    if not SOURCE_SYSTEM_RE.fullmatch(clean):
        raise ApiError(
            400,
            "invalid_source_system",
            "Tên source_system chỉ được chứa chữ thường, chữ số và gạch dưới (1..64 ký tự).",
        )
    return clean


def validate_secret_ref(secret_ref: str) -> str:
    clean = str(secret_ref or "").strip()
    if not SECRET_REF_RE.fullmatch(clean):
        raise ApiError(
            400,
            "invalid_secret_ref",
            "Tên secret_ref phải khớp mẫu 'retailops_connector_[a-z0-9_]{1,64}'.",
        )
    return clean


def inspect_secret_file(path: str | os.PathLike[str]) -> tuple[bool, str]:
    """Inspect a secret key file without ever returning or logging secret contents."""
    raw_path = str(path or "").strip()
    if not raw_path:
        return False, "unconfigured_path"
    try:
        st = os.lstat(raw_path)
    except FileNotFoundError:
        return False, "missing_file"
    except OSError:
        return False, "unreadable_file"

    if stat.S_ISLNK(st.st_mode):
        return False, "symlink_rejected"
    if not stat.S_ISREG(st.st_mode):
        return False, "not_regular_file"

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(raw_path, flags)
    except OSError:
        return False, "unreadable_file"
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode):
            return False, "not_regular_file"
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            chunks.append(chunk)
        secret_bytes = b"".join(chunks).strip(b"\r\n")
    except OSError:
        return False, "unreadable_file"
    finally:
        os.close(fd)

    if len(secret_bytes) < MIN_SECRET_KEY_BYTES:
        return False, "key_too_short"
    return True, "ok"


def resolve_connector_secret_path(
    secret_ref: str, *, env: Mapping[str, str] | None = None
) -> str:
    """Resolve ``<RETAILOPS_CONNECTOR_SECRETS_DIR>/<secret_ref>`` after validating ``secret_ref``."""
    clean_ref = validate_secret_ref(secret_ref)
    environ = env if env is not None else os.environ
    secrets_dir = str(environ.get("RETAILOPS_CONNECTOR_SECRETS_DIR", "") or "").strip()
    if not secrets_dir:
        return ""
    return os.path.join(secrets_dir, clean_ref)


def load_connector_secret(
    secret_ref: str, *, env: Mapping[str, str] | None = None
) -> bytes:
    """Read and validate a connector HMAC key from ``RETAILOPS_CONNECTOR_SECRETS_DIR``."""
    try:
        clean_ref = validate_secret_ref(secret_ref)
    except ApiError as exc:
        raise ApiError(
            503,
            "connector_unavailable",
            "Cấu hình secret_ref của connector không hợp lệ.",
        ) from exc
    environ = env if env is not None else os.environ
    secrets_dir = str(environ.get("RETAILOPS_CONNECTOR_SECRETS_DIR", "") or "").strip()
    if not secrets_dir:
        raise ApiError(
            503,
            "connector_unavailable",
            "Chưa cấu hình thư mục RETAILOPS_CONNECTOR_SECRETS_DIR.",
        )
    full_path = os.path.join(secrets_dir, clean_ref)
    return read_regular_secret_file(full_path, error_code="connector_unavailable")


def validate_status_mapping(mapping: Any) -> dict[str, Any]:
    """Validate canonical target statuses in a connector status mapping dictionary."""
    if not isinstance(mapping, dict):
        raise ApiError(
            400,
            "invalid_status_mapping",
            "Bảng ánh xạ trạng thái của connector phải là JSON object.",
        )
    normalized: dict[str, Any] = {
        "order": {},
        "shipment": {},
        "payment": {},
        "refund": {},
    }

    order_map = mapping.get("order", {})
    if not isinstance(order_map, dict):
        raise ApiError(400, "invalid_status_mapping", "Mục 'order' phải là object.")
    for raw_code, canonical in order_map.items():
        if not isinstance(raw_code, str) or not raw_code.strip() or canonical not in CANONICAL_ORDER_STATUSES:
            raise ApiError(
                400,
                "invalid_status_mapping",
                f"Ánh xạ trạng thái đơn '{raw_code}' -> '{canonical}' không hợp lệ.",
            )
        if raw_code == "shipping" and canonical == "delivered":
            raise ApiError(
                400,
                "invalid_status_mapping",
                "Không được phép ánh xạ trạng thái đơn 'shipping' sang 'delivered' (F16).",
            )
        normalized["order"][raw_code] = canonical

    shipment_map = mapping.get("shipment", {})
    if not isinstance(shipment_map, dict):
        raise ApiError(400, "invalid_status_mapping", "Mục 'shipment' phải là object theo hãng.")
    for carrier_code, carrier_table in shipment_map.items():
        if not isinstance(carrier_code, str) or not carrier_code.strip() or not isinstance(carrier_table, dict):
            raise ApiError(
                400,
                "invalid_status_mapping",
                f"Bảng ánh xạ vận đơn của hãng '{carrier_code}' không hợp lệ.",
            )
        normalized["shipment"][carrier_code] = {}
        for raw_code, canonical in carrier_table.items():
            if not isinstance(raw_code, str) or not raw_code.strip() or canonical not in CANONICAL_SHIPMENT_STATUSES:
                raise ApiError(
                    400,
                    "invalid_status_mapping",
                    f"Ánh xạ vận đơn '{carrier_code}:{raw_code}' -> '{canonical}' không hợp lệ.",
                )
            normalized["shipment"][carrier_code][raw_code] = canonical

    payment_map = mapping.get("payment", {})
    if not isinstance(payment_map, dict):
        raise ApiError(400, "invalid_status_mapping", "Mục 'payment' phải là object.")
    for raw_code, canonical in payment_map.items():
        if not isinstance(raw_code, str) or not raw_code.strip() or canonical not in CANONICAL_PAYMENT_STATUSES:
            raise ApiError(
                400,
                "invalid_status_mapping",
                f"Ánh xạ thanh toán '{raw_code}' -> '{canonical}' không hợp lệ.",
            )
        normalized["payment"][raw_code] = canonical

    refund_map = mapping.get("refund", {})
    if not isinstance(refund_map, dict):
        raise ApiError(400, "invalid_status_mapping", "Mục 'refund' phải là object.")
    for raw_code, canonical in refund_map.items():
        if not isinstance(raw_code, str) or not raw_code.strip() or canonical not in CANONICAL_REFUND_STATUSES:
            raise ApiError(
                400,
                "invalid_status_mapping",
                f"Ánh xạ hoàn tiền '{raw_code}' -> '{canonical}' không hợp lệ.",
            )
        normalized["refund"][raw_code] = canonical

    return normalized


def load_default_status_mapping(
    source_system: str, mapping_file: str | Path | None = None
) -> dict[str, Any]:
    """Load and validate a connector's raw->canonical status mapping file."""
    clean_source = validate_source_system_name(source_system)
    path = Path(mapping_file) if mapping_file is not None else (CONNECTORS_DATA_DIR / f"{clean_source}.json")
    if not path.is_file():
        raise ApiError(
            400,
            "missing_status_mapping_file",
            f"Không tìm thấy tệp ánh xạ trạng thái cho '{clean_source}' tại '{path.name}'.",
        )
    try:
        raw_obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApiError(
            400,
            "invalid_status_mapping_file",
            f"Không đọc được tệp JSON ánh xạ trạng thái '{path.name}'.",
        ) from exc
    return validate_status_mapping(raw_obj)


def map_raw_status(
    status_mapping: Mapping[str, Any],
    domain: str,
    raw_code: str,
    *,
    carrier: str | None = None,
) -> str:
    """Translate a raw source status code into its canonical RetailOps status or raise 422."""
    if domain == "shipment":
        carrier_clean = str(carrier or "").strip()
        shipment_section = status_mapping.get("shipment")
        carrier_map = (
            shipment_section.get(carrier_clean)
            if isinstance(shipment_section, Mapping)
            else None
        )
        canonical = (
            carrier_map.get(raw_code) if isinstance(carrier_map, Mapping) else None
        )
        if not isinstance(canonical, str) or canonical not in CANONICAL_SHIPMENT_STATUSES:
            raise ApiError(
                422,
                "unknown_status_code",
                f"Mã trạng thái vận đơn '{raw_code}' của hãng '{carrier_clean}' chưa có trong bảng ánh xạ connector.",
            )
        return canonical

    domain_section = status_mapping.get(domain)
    canonical = (
        domain_section.get(raw_code) if isinstance(domain_section, Mapping) else None
    )
    allowed_sets = {
        "order": CANONICAL_ORDER_STATUSES,
        "payment": CANONICAL_PAYMENT_STATUSES,
        "refund": CANONICAL_REFUND_STATUSES,
    }
    allowed = allowed_sets.get(domain, frozenset())
    if not isinstance(canonical, str) or canonical not in allowed:
        raise ApiError(
            422,
            "unknown_status_code",
            f"Mã trạng thái '{raw_code}' của miền '{domain}' chưa có trong bảng ánh xạ connector.",
        )
    return canonical


class ConnectorManager:
    """Tenant-scoped integration connector administration and runtime lookup."""

    def __init__(self, sessions: Any, *, env: Mapping[str, str] | None = None) -> None:
        self.sessions = sessions
        self.identity_store = sessions.control
        self.get_bstore = sessions.business_store
        self._env = env

    @property
    def env(self) -> Mapping[str, str]:
        return self._env if self._env is not None else os.environ

    @staticmethod
    def _public_connector_view(
        row: Mapping[str, Any], *, key_ready: bool | None = None, key_reason: str | None = None
    ) -> dict[str, Any]:
        view: dict[str, Any] = {
            "connector_id": str(row["connector_id"]),
            "source_system": str(row["source_system"]),
            "kind": str(row["kind"]),
            "merchant_id": str(row["merchant_id"]),
            "secret_ref": str(row["secret_ref"]),
            "enabled": bool(int(row["enabled"])),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }
        if key_ready is not None:
            view["key_ready"] = bool(key_ready)
        if key_reason is not None:
            view["key_status"] = str(key_reason)
        return view

    def _inspect_connector_key(self, secret_ref: str) -> tuple[bool, str]:
        if not SECRET_REF_RE.fullmatch(str(secret_ref or "").strip()):
            return False, "invalid_secret_ref"
        secret_path = resolve_connector_secret_path(secret_ref, env=self.env)
        if not secret_path:
            return False, "missing_secrets_dir"
        return inspect_secret_file(secret_path)

    def add_connector(
        self,
        tenant_id: str,
        *,
        source_system: str,
        kind: str = "marketplace",
        merchant_id: str = "MERCHANT-SIM-001",
        secret_ref: str | None = None,
        status_mapping: dict[str, Any] | None = None,
        status_mapping_file: str | Path | None = None,
        enabled: bool = True,
        actor_principal_id: str = "operator",
        actor_role: str = "operator",
    ) -> dict[str, Any]:
        tenant_clean = str(tenant_id or "").strip()
        self.identity_store.tenant(tenant_clean)
        clean_source = validate_source_system_name(source_system)
        require(
            kind in CONNECTOR_KINDS,
            400,
            "invalid_connector_kind",
            f"Loại connector phải thuộc {CONNECTOR_KINDS}.",
        )
        clean_merchant = str(merchant_id or "").strip()
        require(
            bool(clean_merchant) and len(clean_merchant) <= 128,
            400,
            "invalid_merchant_id",
            "Trường merchant_id không được rỗng và tối đa 128 ký tự.",
        )
        resolved_ref = validate_secret_ref(
            secret_ref if secret_ref is not None else f"retailops_connector_{clean_source}"
        )
        if status_mapping is not None:
            validated_mapping = validate_status_mapping(status_mapping)
        else:
            validated_mapping = load_default_status_mapping(
                clean_source, mapping_file=status_mapping_file
            )

        mapping_json = json.dumps(validated_mapping, ensure_ascii=False, sort_keys=True)
        now = time.time()
        enabled_int = 1 if enabled else 0
        bstore = self.get_bstore(tenant_clean)
        with bstore.connection(write=True) as db:
            existing = db.execute(
                "SELECT * FROM integration_connectors WHERE source_system=?",
                (clean_source,),
            ).fetchone()
            before_state = (
                self._public_connector_view(dict(existing))
                if existing is not None
                else {}
            )
            if existing is None:
                connector_id = f"conn_{uuid.uuid4().hex}"
                db.execute(
                    """INSERT INTO integration_connectors (
                           connector_id, source_system, kind, merchant_id,
                           secret_ref, status_mapping_json, enabled, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        connector_id,
                        clean_source,
                        kind,
                        clean_merchant,
                        resolved_ref,
                        mapping_json,
                        enabled_int,
                        now,
                        now,
                    ),
                )
            else:
                connector_id = str(existing["connector_id"])
                db.execute(
                    """UPDATE integration_connectors
                       SET kind=?, merchant_id=?, secret_ref=?,
                           status_mapping_json=?, enabled=?, updated_at=?
                       WHERE connector_id=?""",
                    (
                        kind,
                        clean_merchant,
                        resolved_ref,
                        mapping_json,
                        enabled_int,
                        now,
                        connector_id,
                    ),
                )
            saved = dict(
                db.execute(
                    "SELECT * FROM integration_connectors WHERE connector_id=?",
                    (connector_id,),
                ).fetchone()
            )

        key_ok, key_reason = self._inspect_connector_key(resolved_ref)
        after_state = self._public_connector_view(
            saved, key_ready=key_ok, key_reason=key_reason
        )
        with self.identity_store.connection(write=True) as id_db:
            self.identity_store.record_admin_audit(
                id_db,
                actor_principal_id=actor_principal_id,
                actor_role=actor_role,
                tenant_id=tenant_clean,
                target_membership_id=f"connector:{clean_source}",
                action="connector.add",
                outcome="allowed",
                before_state=before_state,
                after_state=after_state,
                reason=f"Configure integration connector {clean_source}",
                now=now,
            )
        return after_state

    def disable_connector(
        self,
        tenant_id: str,
        *,
        source_system: str,
        actor_principal_id: str = "operator",
        actor_role: str = "operator",
    ) -> dict[str, Any]:
        tenant_clean = str(tenant_id or "").strip()
        self.identity_store.tenant(tenant_clean)
        clean_source = validate_source_system_name(source_system)
        now = time.time()
        bstore = self.get_bstore(tenant_clean)
        with bstore.connection(write=True) as db:
            existing = db.execute(
                "SELECT * FROM integration_connectors WHERE source_system=?",
                (clean_source,),
            ).fetchone()
            require(
                existing is not None,
                404,
                "connector_not_found",
                f"Không tìm thấy connector '{clean_source}' trong cửa hàng '{tenant_clean}'.",
            )
            before_state = self._public_connector_view(dict(existing))
            db.execute(
                "UPDATE integration_connectors SET enabled=0, updated_at=? WHERE source_system=?",
                (now, clean_source),
            )
            saved = dict(
                db.execute(
                    "SELECT * FROM integration_connectors WHERE source_system=?",
                    (clean_source,),
                ).fetchone()
            )
        after_state = self._public_connector_view(saved)
        with self.identity_store.connection(write=True) as id_db:
            self.identity_store.record_admin_audit(
                id_db,
                actor_principal_id=actor_principal_id,
                actor_role=actor_role,
                tenant_id=tenant_clean,
                target_membership_id=f"connector:{clean_source}",
                action="connector.disable",
                outcome="allowed",
                before_state=before_state,
                after_state=after_state,
                reason=f"Disable integration connector {clean_source}",
                now=now,
            )
        return after_state

    def list_connectors(
        self,
        tenant_id: str,
        *,
        actor_principal_id: str = "operator",
        actor_role: str = "operator",
        record_audit: bool = True,
    ) -> list[dict[str, Any]]:
        tenant_clean = str(tenant_id or "").strip()
        self.identity_store.tenant(tenant_clean)
        bstore = self.get_bstore(tenant_clean)
        with bstore.connection() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM integration_connectors ORDER BY source_system ASC"
                ).fetchall()
            ]
        items: list[dict[str, Any]] = []
        for row in rows:
            key_ok, key_reason = self._inspect_connector_key(str(row["secret_ref"]))
            items.append(
                self._public_connector_view(
                    row, key_ready=key_ok, key_reason=key_reason
                )
            )
        if record_audit:
            with self.identity_store.connection(write=True) as id_db:
                self.identity_store.record_admin_audit(
                    id_db,
                    actor_principal_id=actor_principal_id,
                    actor_role=actor_role,
                    tenant_id=tenant_clean,
                    target_membership_id="connector:*",
                    action="connector.list",
                    outcome="allowed",
                    before_state={},
                    after_state={
                        "count": len(items),
                        "connectors": [item["source_system"] for item in items],
                    },
                    reason="List integration connectors",
                )
        return items

    def get_connector_record(
        self, tenant_id: str, source_system: str
    ) -> dict[str, Any] | None:
        tenant_clean = str(tenant_id or "").strip()
        clean_source = str(source_system or "").strip()
        if not tenant_clean or not SOURCE_SYSTEM_RE.fullmatch(clean_source):
            return None
        with self.identity_store.connection() as id_db:
            t_row = id_db.execute(
                "SELECT id, active FROM tenants WHERE id=?", (tenant_clean,)
            ).fetchone()
        if t_row is None or not bool(t_row["active"]):
            return None
        bstore = self.get_bstore(tenant_clean)
        with bstore.connection() as db:
            row = db.execute(
                "SELECT * FROM integration_connectors WHERE source_system=?",
                (clean_source,),
            ).fetchone()
        if row is None:
            return None
        rec = dict(row)
        rec["status_mapping"] = validate_status_mapping(
            json.loads(str(rec["status_mapping_json"]))
        )
        return rec

    def require_ready_connector(
        self, tenant_id: str, source_system: str, *, require_signing_key: bool = True
    ) -> tuple[dict[str, Any], bytes | None]:
        """Look up a tenant connector; return 404 if absent, 503 if disabled or missing key."""
        rec = self.get_connector_record(tenant_id, source_system)
        if rec is None:
            raise ApiError(
                404,
                "connector_not_found",
                "Không tìm thấy cửa hàng hoặc connector tích hợp.",
            )
        if not bool(int(rec["enabled"])):
            raise ApiError(
                503,
                "connector_unavailable",
                f"Connector '{source_system}' đang tắt.",
            )
        secret_bytes: bytes | None = None
        if require_signing_key:
            secret_bytes = load_connector_secret(str(rec["secret_ref"]), env=self.env)
        return rec, secret_bytes

    def check_connectors(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        """Verify digest key and all enabled connector signing keys without exposing secret bytes."""
        digest_key_file = str(
            self.env.get("RETAILOPS_EVENT_DIGEST_KEY_FILE", "") or ""
        ).strip()
        digest_ok, digest_reason = inspect_secret_file(digest_key_file)
        issues: list[dict[str, str]] = []
        if not digest_ok:
            issues.append(
                {
                    "scope": "event_digest_key",
                    "tenant_id": "*",
                    "source_system": "*",
                    "secret_ref": "retailops_event_digest_key",
                    "reason": digest_reason,
                }
            )

        if tenant_id is not None:
            clean_tid = str(tenant_id).strip()
            self.identity_store.tenant(clean_tid)
            tenant_ids = [clean_tid]
        else:
            with self.identity_store.connection() as id_db:
                tenant_ids = [
                    str(r["id"])
                    for r in id_db.execute(
                        "SELECT id FROM tenants WHERE active=1 ORDER BY id ASC"
                    ).fetchall()
                ]

        checked_enabled = 0
        for tid in tenant_ids:
            try:
                bstore = self.get_bstore(tid)
                with bstore.connection() as db:
                    rows = [
                        dict(r)
                        for r in db.execute(
                            "SELECT source_system, secret_ref, enabled "
                            "FROM integration_connectors WHERE enabled=1 ORDER BY source_system ASC"
                        ).fetchall()
                    ]
            except Exception as exc:
                issues.append(
                    {
                        "scope": "tenant_store",
                        "tenant_id": tid,
                        "source_system": "*",
                        "secret_ref": "*",
                        "reason": f"store_error:{exc.__class__.__name__}",
                    }
                )
                continue

            for row in rows:
                checked_enabled += 1
                src = str(row["source_system"])
                sref = str(row["secret_ref"])
                key_ok, key_reason = self._inspect_connector_key(sref)
                if not key_ok:
                    issues.append(
                        {
                            "scope": "connector_key",
                            "tenant_id": tid,
                            "source_system": src,
                            "secret_ref": sref,
                            "reason": key_reason,
                        }
                    )

        return {
            "ok": len(issues) == 0,
            "digest_key_status": digest_reason,
            "tenants_checked": len(tenant_ids),
            "enabled_connectors_checked": checked_enabled,
            "issues": issues,
        }


def warn_unready_connectors_on_startup(
    sessions: Any,
    *,
    env: Mapping[str, str] | None = None,
    log: logging.Logger | None = None,
) -> list[dict[str, str]]:
    """Log one warning per enabled connector whose key cannot be read at startup (W6.1b-D5).

    Never raises and never includes secret bytes; /healthz remains unaffected.
    """
    if not hasattr(sessions, "control") or not hasattr(sessions, "business_store"):
        return []
    target_logger = log or logger
    warnings_emitted: list[dict[str, str]] = []
    try:
        mgr = ConnectorManager(sessions, env=env)
        with sessions.control.connection() as id_db:
            tenant_ids = [
                str(r["id"])
                for r in id_db.execute(
                    "SELECT id FROM tenants WHERE active=1 ORDER BY id ASC"
                ).fetchall()
            ]
        for tid in tenant_ids:
            try:
                bstore = sessions.business_store(tid)
                with bstore.connection() as db:
                    rows = [
                        dict(r)
                        for r in db.execute(
                            "SELECT source_system, secret_ref "
                            "FROM integration_connectors WHERE enabled=1 ORDER BY source_system ASC"
                        ).fetchall()
                    ]
            except Exception:
                continue
            for row in rows:
                src = str(row["source_system"])
                sref = str(row["secret_ref"])
                ok, reason = mgr._inspect_connector_key(sref)
                if not ok:
                    target_logger.warning(
                        "Integration connector signing key unavailable: source_system=%s reason=%s",
                        src,
                        reason,
                    )
                    warnings_emitted.append(
                        {
                            "tenant_id": tid,
                            "source_system": src,
                            "reason": reason,
                        }
                    )
    except Exception:
        return warnings_emitted
    return warnings_emitted
