"""Internal HTTP event intake (HMAC-SHA256 verification) and operator JSONL batch import (W6.1b-D4)."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import time
from typing import Any, Callable

from retailops.core import ApiError, require
from retailops.integration.connectors import ConnectorManager, validate_source_system_name
from retailops.integration.contract import iso_vn_to_epoch
from retailops.integration.ingest import ImportResult, IntegrationIngestService

MAX_TIMESTAMP_SKEW_SECONDS = 300
MAX_EVENT_BODY_BYTES = 262144

PROXY_WSGI_HEADERS = (
    "HTTP_X_FORWARDED_FOR",
    "HTTP_X_FORWARDED_HOST",
    "HTTP_X_FORWARDED_PROTO",
    "HTTP_X_FORWARDED_PORT",
    "HTTP_FORWARDED",
    "HTTP_VIA",
    "HTTP_X_REAL_IP",
)


def assert_no_proxy_headers(environ: dict[str, Any]) -> None:
    """Reject with 404 if any reverse-proxy header is present on an /internal/* request."""
    for key in PROXY_WSGI_HEADERS:
        val = environ.get(key)
        if val is not None and str(val).strip():
            raise ApiError(404, "not_found", "Không tìm thấy đường dẫn.")


def compute_sim_hmac_signature(secret_bytes: bytes, timestamp: int, raw_body: bytes) -> str:
    signing_input = f"{int(timestamp)}.".encode("ascii") + raw_body
    digest = hmac.new(secret_bytes, signing_input, hashlib.sha256).hexdigest()
    return f"v1={digest}"


def handle_internal_event_post(
    sessions: Any,
    *,
    tenant_id: str,
    source_system: str,
    raw_body: bytes,
    headers: dict[str, str],
    now_fn: Callable[[], float] = time.time,
) -> tuple[int, dict[str, Any]]:
    """Verify connector state, HMAC headers, merchant_id, and ingest raw event bytes."""
    if not hasattr(sessions, "control") or not hasattr(sessions, "business_store"):
        raise ApiError(404, "not_found", "Không tìm thấy đường dẫn.")

    mgr = ConnectorManager(sessions)
    connector, secret_bytes = mgr.require_ready_connector(
        tenant_id, source_system, require_signing_key=True
    )
    assert secret_bytes is not None

    # Ensure event digest key is also available before accepting traffic (fail closed 503)
    svc = IntegrationIngestService(sessions)
    resolved_digest_key = svc._resolve_digest_key()

    raw_ts = str(headers.get("x-sim-timestamp", "") or "").strip()
    if not raw_ts or not (raw_ts.lstrip("-").isdigit()):
        raise ApiError(401, "invalid_timestamp", "Thiếu hoặc sai định dạng header X-Sim-Timestamp.")
    ts_int = int(raw_ts)
    now_ts = float(now_fn())
    if abs(now_ts - float(ts_int)) > MAX_TIMESTAMP_SKEW_SECONDS:
        raise ApiError(
            401,
            "stale_timestamp",
            "Header X-Sim-Timestamp lệch quá 300 giây so với đồng hồ máy chủ.",
        )

    raw_sig = str(headers.get("x-sim-signature", "") or "").strip()
    if not raw_sig.startswith("v1=") or len(raw_sig) != 67:
        raise ApiError(401, "invalid_signature", "Thiếu hoặc sai định dạng header X-Sim-Signature.")
    expected_sig = compute_sim_hmac_signature(secret_bytes, ts_int, raw_body)
    if not hmac.compare_digest(raw_sig.lower(), expected_sig.lower()):
        raise ApiError(401, "invalid_signature", "Chữ ký X-Sim-Signature không hợp lệ.")

    header_event_id = str(headers.get("x-sim-event-id", "") or "").strip()
    if not header_event_id:
        raise ApiError(401, "missing_event_id_header", "Thiếu header X-Sim-Event-Id.")

    try:
        parsed_preview = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError(
            422, "invalid_event_json", "Thân sự kiện không phải JSON UTF-8 hợp lệ."
        ) from exc
    if not isinstance(parsed_preview, dict):
        raise ApiError(422, "invalid_event_object", "Thân sự kiện phải là JSON object.")

    if parsed_preview.get("event_id") != header_event_id:
        raise ApiError(
            401,
            "event_id_mismatch",
            "Header X-Sim-Event-Id không khớp với event_id trong thân sự kiện.",
        )
    if parsed_preview.get("merchant_id") != connector["merchant_id"]:
        raise ApiError(
            401,
            "merchant_id_mismatch",
            "Trường merchant_id không khớp với connector đã cấu hình.",
        )

    res: ImportResult = svc.ingest_event(
        raw_body,
        tenant_id=tenant_id,
        connector_source_system=source_system,
        received_via="http",
        digest_key=resolved_digest_key,
        expected_merchant_id=str(connector["merchant_id"]),
        status_mapping=connector["status_mapping"],
    )
    if res.is_replay:
        raise ApiError(
            409,
            "duplicate_event",
            f"Sự kiện '{res.event_id}' đã được ghi nhận trước đó.",
        )
    return 200, {
        "ok": True,
        "status": res.status,
        "event_id": res.event_id,
        "event_type": res.event_type,
        "order_id": res.order_id or None,
        "sequence_ignored": res.sequence_ignored,
    }


def compute_jsonl_rebase_offset(
    raw_lines: list[bytes], *, target_now: float
) -> float:
    """Compute ``target_now - max(occurred_at)`` across valid JSON event lines."""
    max_occurred: float | None = None
    for raw_line in raw_lines:
        if not raw_line.strip():
            continue
        try:
            obj = json.loads(raw_line.decode("utf-8"))
        except Exception:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("occurred_at"), str):
            try:
                ts = iso_vn_to_epoch(obj["occurred_at"], "occurred_at")
            except ApiError:
                continue
            if max_occurred is None or ts > max_occurred:
                max_occurred = ts
    if max_occurred is None:
        return 0.0
    return float(target_now) - float(max_occurred)


def import_events_jsonl(
    sessions: Any,
    *,
    tenant_id: str,
    source_system: str,
    jsonl_path: str | Path,
    rebase_clock: str | None = None,
    now_fn: Callable[[], float] = time.time,
    actor_principal_id: str = "operator",
    actor_role: str = "operator",
    digest_key: bytes | None = None,
    record_audit: bool = True,
) -> dict[str, Any]:
    """Import a JSONL file of v2 events through the canonical write path without signature checks."""
    tenant_clean = str(tenant_id or "").strip()
    clean_source = validate_source_system_name(source_system)
    sessions.control.tenant(tenant_clean)
    require(
        rebase_clock in (None, "now"),
        400,
        "invalid_rebase_clock",
        "Tham số --rebase-clock chỉ chấp nhận giá trị 'now'.",
    )

    path = Path(jsonl_path)
    if not path.is_file():
        raise ApiError(404, "events_file_not_found", f"Không tìm thấy tệp JSONL: '{path}'.")

    svc = IntegrationIngestService(sessions, digest_key=digest_key)
    resolved_digest_key = svc._resolve_digest_key()

    mgr = ConnectorManager(sessions)
    connector = mgr.get_connector_record(tenant_clean, clean_source)
    status_mapping = connector["status_mapping"] if connector is not None else None
    from retailops.integration.connectors import (
        CONNECTORS_DATA_DIR,
        load_default_status_mapping,
        validate_status_mapping,
    )

    if status_mapping is not None:
        validated_mapping = validate_status_mapping(status_mapping)
    else:
        default_file = CONNECTORS_DATA_DIR / f"{clean_source}.json"
        validated_mapping = (
            load_default_status_mapping(clean_source)
            if default_file.is_file()
            else load_default_status_mapping("marketplace_sim")
        )

    with sessions.control.connection() as id_db:
        tenant_row = id_db.execute(
            "SELECT id, active FROM tenants WHERE id=?", (tenant_clean,)
        ).fetchone()
    require(
        tenant_row is not None,
        404,
        "tenant_not_found",
        f"Cửa hàng {tenant_clean} không tồn tại.",
    )
    require(
        bool(tenant_row["active"]),
        400,
        "tenant_inactive",
        f"Cửa hàng {tenant_clean} chưa được kích hoạt.",
    )

    file_bytes = path.read_bytes()
    raw_lines = [
        line.rstrip(b"\r")
        for line in file_bytes.split(b"\n")
        if line.strip()
    ]

    import_now = float(now_fn())
    rebase_offset_seconds = (
        compute_jsonl_rebase_offset(raw_lines, target_now=import_now)
        if rebase_clock == "now"
        else 0.0
    )

    received = 0
    duplicates = 0
    errors = 0
    sequence_ignored = 0
    error_details: list[dict[str, Any]] = []
    pending_mappings: list[tuple[str, str]] = []

    bstore = sessions.business_store(tenant_clean)
    with bstore.connection(write=True) as db:
        bstore._ensure_purge_tombstone_table(db)
        for idx, raw_line in enumerate(raw_lines, 1):
            db.execute("SAVEPOINT sp_import_evt")
            try:
                res = svc.ingest_event(
                    raw_line,
                    tenant_id=tenant_clean,
                    connector_source_system=clean_source,
                    received_via="import",
                    digest_key=resolved_digest_key,
                    actor_principal_id=actor_principal_id,
                    rebase_offset_seconds=rebase_offset_seconds,
                    _db=db,
                    _validated_status_mapping=validated_mapping,
                    _skip_tenant_check=True,
                    _pending_mappings=pending_mappings,
                )
                db.execute("RELEASE SAVEPOINT sp_import_evt")
                if res.is_replay:
                    duplicates += 1
                else:
                    received += 1
                    if res.sequence_ignored:
                        sequence_ignored += 1
            except ApiError as exc:
                db.execute("ROLLBACK TO SAVEPOINT sp_import_evt")
                db.execute("RELEASE SAVEPOINT sp_import_evt")
                if exc.status >= 500:
                    raise
                errors += 1
                error_details.append(
                    {"line": idx, "code": exc.code, "message": exc.message}
                )

    unique_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for ext_cid, cid in pending_mappings:
        pair = (ext_cid, cid)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        unique_pairs.append(pair)
    svc._ensure_mappings_batch(tenant_clean, clean_source, unique_pairs)

    summary = {
        "result": "EVENTS_IMPORTED",
        "tenant_id": tenant_clean,
        "source_system": clean_source,
        "file": path.name,
        "total_lines": len(raw_lines),
        "received": received,
        "duplicates": duplicates,
        "errors": errors,
        "sequence_ignored": sequence_ignored,
        "rebase_clock": rebase_clock,
        "rebase_offset_seconds": round(rebase_offset_seconds, 6),
        "error_details": error_details[:20],
    }

    if record_audit:
        with sessions.control.connection(write=True) as id_db:
            sessions.control.record_admin_audit(
                id_db,
                actor_principal_id=actor_principal_id,
                actor_role=actor_role,
                tenant_id=tenant_clean,
                target_membership_id=f"connector:{clean_source}",
                action="database.import_events",
                outcome="allowed",
                before_state={},
                after_state={
                    "file": path.name,
                    "total_lines": len(raw_lines),
                    "received": received,
                    "duplicates": duplicates,
                    "errors": errors,
                    "rebase_clock": rebase_clock,
                    "rebase_offset_seconds": round(rebase_offset_seconds, 6),
                },
                reason=f"Operator import-events from {path.name}",
                now=import_now,
            )

    return summary
