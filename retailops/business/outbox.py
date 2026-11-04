"""Outbound JSONL outbox envelope validator, append-only daily sink, and SHA-256 day manifests (§11.4, W3-D7, W4-D8)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from retailops.business.evidence import atomic_write_bytes, resolve_protected_subdir
from retailops.core import ApiError, require

OUTBOX_SCHEMA = "retailops.order_action"
OUTBOX_SCHEMA_VERSION = 1
OUTBOX_BACKOFF_SECONDS = (60, 300, 1800, 7200, 43200)
OUTBOX_MAX_ATTEMPTS = 8
CUSTOMER_REF_KEY_MIN_LENGTH = 16


def resolve_customer_ref_key(
    explicit_key: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Resolve HMAC secret key from explicit override, RETAILOPS_CUSTOMER_REF_KEY, or RETAILOPS_CUSTOMER_REF_KEY_FILE.

    Returns (secret_key, error_code, error_message). Never includes secret material in error_message.
    """
    if explicit_key is not None:
        cleaned = str(explicit_key).strip()
        if not cleaned:
            return (
                None,
                "customer_ref_key_missing",
                "Thiếu cấu hình khóa RETAILOPS_CUSTOMER_REF_KEY; outbox không ghi sự kiện mới.",
            )
        if len(cleaned) < CUSTOMER_REF_KEY_MIN_LENGTH:
            return (
                None,
                "customer_ref_key_invalid",
                f"Khóa RETAILOPS_CUSTOMER_REF_KEY phải dài tối thiểu {CUSTOMER_REF_KEY_MIN_LENGTH} ký tự; outbox không ghi sự kiện mới.",
            )
        return cleaned, None, None

    env = os.environ if environ is None else environ
    direct = (env.get("RETAILOPS_CUSTOMER_REF_KEY") or "").strip()
    filepath = (env.get("RETAILOPS_CUSTOMER_REF_KEY_FILE") or "").strip()
    if direct and filepath:
        return (
            None,
            "customer_ref_key_conflict",
            "Chỉ được đặt một trong hai biến RETAILOPS_CUSTOMER_REF_KEY hoặc RETAILOPS_CUSTOMER_REF_KEY_FILE; outbox không ghi sự kiện mới.",
        )
    if filepath:
        try:
            key = Path(filepath).read_text(encoding="utf-8").strip()
        except OSError:
            return (
                None,
                "customer_ref_key_unreadable",
                "Không đọc được tệp khóa RETAILOPS_CUSTOMER_REF_KEY_FILE; outbox không ghi sự kiện mới.",
            )
    else:
        key = direct
    if not key:
        return (
            None,
            "customer_ref_key_missing",
            "Thiếu cấu hình khóa RETAILOPS_CUSTOMER_REF_KEY (hoặc RETAILOPS_CUSTOMER_REF_KEY_FILE); outbox không ghi sự kiện mới.",
        )
    if len(key) < CUSTOMER_REF_KEY_MIN_LENGTH:
        return (
            None,
            "customer_ref_key_invalid",
            f"Khóa RETAILOPS_CUSTOMER_REF_KEY phải dài tối thiểu {CUSTOMER_REF_KEY_MIN_LENGTH} ký tự; outbox không ghi sự kiện mới.",
        )
    return key, None, None


def compute_customer_ref(tenant_id: str, customer_id: str, secret_key: str) -> str:
    """Compute HMAC-SHA-256 salted customer_ref (`custref_<64hex>`) per W4-D8."""
    key_clean, err_code, err_msg = resolve_customer_ref_key(explicit_key=secret_key)
    if not key_clean:
        raise ValueError(err_msg or err_code or "Invalid customer_ref secret key.")
    tid = str(tenant_id or "").strip() or "default"
    cid = str(customer_id or "").strip()
    if not cid:
        raise ValueError("customer_id must not be empty.")
    msg = f"{tid}\x00{cid}".encode("utf-8")
    digest = hmac.new(key_clean.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"custref_{digest}"

ALLOWED_OUTBOX_EVENT_TYPES = frozenset({
    "cancel_requested",
    "return_requested",
    "exchange_requested",
    "request_approved",
    "request_rejected",
    "request_status_changed",
    "refund_requested",
    "refund_decided",
    "order_status_changed",
    "case_feedback_recorded",
})

STATE_CHANGE_EVENT_TYPES = frozenset({
    "cancel_requested",
    "return_requested",
    "exchange_requested",
    "request_approved",
    "request_rejected",
    "request_status_changed",
    "refund_requested",
    "refund_decided",
    "order_status_changed",
})

FORBIDDEN_PII_ENVELOPE_KEYS = frozenset({
    "customer_id",
    "customer_name",
    "name",
    "email",
    "phone",
    "phone_number",
    "address",
    "shipping_address",
    "comment",
    "message",
    "messages",
    "transcript",
    "chat_text",
})

DAY_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl$")
_FILE_LOCKS_GUARD = threading.Lock()
_FILE_LOCKS: dict[str, threading.Lock] = {}


def _file_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _FILE_LOCKS_GUARD:
        lk = _FILE_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _FILE_LOCKS[key] = lk
        return lk


def validate_outbox_envelope(envelope: dict) -> dict:
    """Validate outbound JSONL envelope against §11.4 and W3-D7 contract and reject any PII fields."""
    if not isinstance(envelope, dict):
        raise ValueError("Outbox envelope must be a JSON object.")
    bad_keys = FORBIDDEN_PII_ENVELOPE_KEYS.intersection(envelope.keys())
    if bad_keys:
        raise ValueError(f"Forbidden PII/chat keys in outbox envelope: {sorted(bad_keys)}")
    if envelope.get("schema") != OUTBOX_SCHEMA:
        raise ValueError(f"Unexpected outbox schema: {envelope.get('schema')}")
    if envelope.get("schema_version") != OUTBOX_SCHEMA_VERSION:
        raise ValueError(f"Unexpected outbox schema_version: {envelope.get('schema_version')}")
    ev_id = envelope.get("event_id")
    ev_type = envelope.get("event_type")
    occ = envelope.get("occurred_at")
    tid = envelope.get("tenant_id")
    if not (isinstance(ev_id, str) and ev_id.strip()):
        raise ValueError("Missing event_id in outbox envelope.")
    if ev_type not in ALLOWED_OUTBOX_EVENT_TYPES:
        raise ValueError(f"Unsupported outbox event_type: {ev_type}")
    if not (isinstance(occ, str) and occ.endswith("Z") and "T" in occ):
        raise ValueError("occurred_at must be UTC ISO-8601.")
    if not (isinstance(tid, str) and tid.strip()):
        raise ValueError("Missing tenant_id in outbox envelope.")

    actor = envelope.get("actor")
    if not (
        isinstance(actor, dict)
        and set(actor.keys()) == {"principal_id", "role"}
        and isinstance(actor.get("principal_id"), str)
        and actor["principal_id"].strip()
        and isinstance(actor.get("role"), str)
        and actor["role"].strip()
    ):
        raise ValueError("Invalid actor block in outbox envelope.")

    if "customer_ref" in envelope:
        cref = envelope["customer_ref"]
        if not (isinstance(cref, str) and re.fullmatch(r"(?:custref|cref)_[0-9a-f]{16,64}", cref)):
            raise ValueError("customer_ref must be an opaque hash identifier.")

    if ev_type in STATE_CHANGE_EVENT_TYPES:
        for state_key in ("before", "after"):
            block = envelope.get(state_key)
            if not isinstance(block, dict):
                raise ValueError(f"State change event {ev_type} requires {state_key} object.")
            if FORBIDDEN_PII_ENVELOPE_KEYS.intersection(block.keys()):
                raise ValueError(f"Forbidden PII key inside {state_key}.")

    if "reason_text" in envelope and envelope["reason_text"] is not None:
        if not isinstance(envelope["reason_text"], str) or len(envelope["reason_text"]) > 500:
            raise ValueError("reason_text exceeds 500 characters or is not a string.")

    if "evidence_refs" in envelope and envelope["evidence_refs"] is not None:
        if not isinstance(envelope["evidence_refs"], list):
            raise ValueError("evidence_refs must be a list.")
        for ref in envelope["evidence_refs"]:
            if not (
                isinstance(ref, dict)
                and set(ref.keys()) == {"evidence_id", "sha256"}
                and isinstance(ref.get("evidence_id"), str)
                and isinstance(ref.get("sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])
            ):
                raise ValueError("evidence_refs must contain only opaque evidence_id and sha256.")

    for req_str_key in ("correlation_id", "idempotency_key"):
        val = envelope.get(req_str_key)
        if not (isinstance(val, str) and val.strip()):
            raise ValueError(f"Missing {req_str_key} in outbox envelope.")
    if envelope.get("source") not in ("app", "worker", "import"):
        raise ValueError(f"Invalid source in outbox envelope: {envelope.get('source')}")
    return envelope


def utc_day_string(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def append_outbox_jsonl_line(data_root: Path, tenant_id: str, envelope: dict, *, now_ts: float) -> Path:
    """Validate and append a single JSONL line to <data_root>/integration/<tenant>/<YYYY-MM-DD>.jsonl."""
    validate_outbox_envelope(envelope)
    _, _, target_dir = resolve_protected_subdir(data_root, "integration", tenant_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    day_str = utc_day_string(now_ts)
    jsonl_path = (target_dir / f"{day_str}.jsonl").resolve()
    require(jsonl_path.parent == target_dir.resolve(), 500, "unsafe_storage_path", "Đường dẫn JSONL không hợp lệ.")
    line = (json.dumps(envelope, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    lock = _file_lock(jsonl_path)
    with lock:
        with open(jsonl_path, "ab") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    return jsonl_path


def seal_closed_integration_days(data_root: Path, tenant_id: str, *, now_ts: float) -> int:
    """Write immutable <YYYY-MM-DD>.sha256 manifests for any closed UTC day (< current UTC day)."""
    _, _, target_dir = resolve_protected_subdir(data_root, "integration", tenant_id)
    if not target_dir.is_dir():
        return 0
    current_day = utc_day_string(now_ts)
    sealed = 0
    for jsonl_path in sorted(target_dir.glob("*.jsonl")):
        m = DAY_FILE_RE.fullmatch(jsonl_path.name)
        if not m:
            continue
        file_day = m.group(1)
        if file_day >= current_day:
            continue
        manifest_name = f"{file_day}.sha256"
        manifest_path = target_dir / manifest_name
        if manifest_path.is_file():
            continue
        lock = _file_lock(jsonl_path)
        with lock:
            if manifest_path.is_file():
                continue
            digest = hashlib.sha256(jsonl_path.read_bytes()).hexdigest()
            manifest_bytes = f"{digest}  {jsonl_path.name}\n".encode("utf-8")
            atomic_write_bytes(target_dir, manifest_name, manifest_bytes)
            sealed += 1
    return sealed


def compute_next_backoff_seconds(attempts_after_failure: int) -> int:
    idx = max(0, min(int(attempts_after_failure) - 1, len(OUTBOX_BACKOFF_SECONDS) - 1))
    return int(OUTBOX_BACKOFF_SECONDS[idx])
