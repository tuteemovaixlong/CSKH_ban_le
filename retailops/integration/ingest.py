"""Canonical v2 event ingestion, customer mapping, and reconciliation (W6.1b-D3, D6, D7, D8)."""

from __future__ import annotations

from contextlib import contextmanager
import copy
from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
import os
import stat
import time
from typing import Any, Optional
import uuid

from retailops.core import ApiError, require
from retailops.integration.contract import (
    ensure_w6_1b_1_supported_event,
    iso_vn_to_epoch,
    validate_event_v2,
)
from retailops.integration.recipient_crypto import (
    RecipientKeyring,
    load_recipient_keyring,
    recompute_product_orders_recipient_retention_in_tx,
    sync_order_recipient_retention_in_tx,
)

logger = logging.getLogger("retailops_integration")

MIN_SECRET_KEY_BYTES = 32
ORDER_CREATED_REDACTED_FIELDS = (
    "data.recipient.name",
    "data.recipient.phone",
    "data.recipient.address_line",
)

DEFAULT_ORDER_STATUS_MAP: dict[str, str] = {
    "pending": "pending",
    "confirmed": "pending",
    "shipping": "shipping",
    "delivered": "delivered",
    "cancelled": "cancelled",
}

_ORDER_STATUS_RANK: dict[str, int] = {
    "pending": 0,
    "shipping": 1,
    "delivered": 2,
    "cancelled": 2,
}
_TERMINAL_ORDER_STATUSES = frozenset({"delivered", "cancelled"})

_SHIPMENT_STATUS_RANK: dict[str, int] = {
    "created": 0,
    "picked_up": 1,
    "in_transit": 2,
    "out_for_delivery": 3,
    "delivery_failed": 3,
    "returning": 4,
    "delivered": 5,
    "returned": 5,
    "cancelled": 5,
}
_TERMINAL_SHIPMENT_STATUSES = frozenset({"delivered", "returned", "cancelled"})

_PAYMENT_STATUS_RANK: dict[str, int] = {
    "pending": 0,
    "succeeded": 1,
    "failed": 1,
    "cancelled": 1,
}
_TERMINAL_PAYMENT_STATUSES = frozenset({"succeeded", "failed", "cancelled"})

_REFUND_STATUS_RANK: dict[str, int] = {
    "pending": 0,
    "processing": 1,
    "completed": 2,
    "failed": 2,
}
_TERMINAL_REFUND_STATUSES = frozenset({"completed", "failed"})


def can_advance_order_status(current: str, target: str) -> bool:
    if current == target:
        return True
    if current in _TERMINAL_ORDER_STATUSES:
        return False
    return _ORDER_STATUS_RANK.get(target, -1) >= _ORDER_STATUS_RANK.get(current, 99)


def can_advance_shipment_status(current: str, target: str) -> bool:
    if current == target:
        return True
    if current in _TERMINAL_SHIPMENT_STATUSES:
        return False
    return _SHIPMENT_STATUS_RANK.get(target, -1) >= _SHIPMENT_STATUS_RANK.get(current, 99)


def can_advance_payment_status(current: str, target: str) -> bool:
    if current == target:
        return True
    if current in _TERMINAL_PAYMENT_STATUSES:
        return False
    return _PAYMENT_STATUS_RANK.get(target, -1) >= _PAYMENT_STATUS_RANK.get(current, 99)


def can_advance_refund_status(current: str, target: str) -> bool:
    if current == target:
        return True
    if current in _TERMINAL_REFUND_STATUSES:
        return False
    return _REFUND_STATUS_RANK.get(target, -1) >= _REFUND_STATUS_RANK.get(current, 99)


@dataclass
class ImportResult:
    success: bool
    status: str
    order_id: str
    customer_id: str
    tenant_id: str
    source_system: str
    event_id: str
    event_type: str = ""
    external_order_id: Optional[str] = None
    is_replay: bool = False
    sequence_ignored: bool = False
    items_count: int = 0
    total: int = 0


def read_regular_secret_file(path: str | os.PathLike[str], *, error_code: str = "connector_unavailable") -> bytes:
    """Read a secret key file safely without following symlinks; require >= 32 bytes."""
    raw_path = str(path or "").strip()
    if not raw_path:
        raise ApiError(503, error_code, "Chưa cấu hình đường dẫn tệp khóa bí mật.")
    try:
        st = os.lstat(raw_path)
    except OSError as exc:
        raise ApiError(503, error_code, "Không tìm thấy hoặc không đọc được tệp khóa bí mật.") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ApiError(503, error_code, "Tệp khóa bí mật phải là tệp thường (không chấp nhận symlink/thư mục).")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(raw_path, flags)
    except OSError as exc:
        raise ApiError(503, error_code, "Không mở được tệp khóa bí mật.") from exc
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode):
            raise ApiError(503, error_code, "Tệp khóa bí mật không phải tệp thường.")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            chunks.append(chunk)
        secret_bytes = b"".join(chunks).strip(b"\r\n")
    finally:
        os.close(fd)
    if len(secret_bytes) < MIN_SECRET_KEY_BYTES:
        raise ApiError(503, error_code, "Khóa bí mật quá ngắn (tối thiểu 32 byte).")
    return secret_bytes


def compute_payload_hmac_digest(raw_bytes: bytes, digest_key: bytes) -> str:
    """Compute HMAC-SHA256 hex digest over exact raw received bytes (W6.1b-D7)."""
    if not isinstance(digest_key, (bytes, bytearray)) or len(digest_key) < MIN_SECRET_KEY_BYTES:
        raise ApiError(
            503,
            "connector_unavailable",
            "Khóa HMAC toàn vẹn sự kiện thiếu hoặc ngắn hơn 32 byte.",
        )
    return hmac.new(bytes(digest_key), raw_bytes, hashlib.sha256).hexdigest()


def redact_order_created_recipient(event: dict[str, Any]) -> tuple[dict[str, Any], list[str], str]:
    """Redact recipient PII fields in-place on a copy while keeping keys intact (W6.1b-D7)."""
    redacted = copy.deepcopy(event)
    rec = redacted["data"]["recipient"]
    district = str(rec["district"]).strip()
    province = str(rec["province"]).strip()
    ship_to_area = f"{district}, {province}"[:120]
    rec["name"] = None
    rec["phone"] = None
    rec["address_line"] = None
    return redacted, list(ORDER_CREATED_REDACTED_FIELDS), ship_to_area


class IntegrationIngestService:
    """Service-boundary v2 event intake, canonical writer, and customer mapping manager."""

    def __init__(
        self,
        sessions_or_stores: Any,
        *,
        digest_key: bytes | None = None,
        recipient_keyring: RecipientKeyring | None = None,
    ) -> None:
        self.sessions = sessions_or_stores
        if hasattr(sessions_or_stores, "control"):
            self.identity_store = sessions_or_stores.control
            self.get_bstore = sessions_or_stores.business_store
        elif hasattr(sessions_or_stores, "business_store"):
            self.identity_store = getattr(
                sessions_or_stores, "identity_store", None
            ) or getattr(sessions_or_stores, "control", None)
            self.get_bstore = sessions_or_stores.business_store
        else:
            raise TypeError(
                "sessions_or_stores must provide control (IdentityStore) and business_store(tenant_id)."
            )
        self._explicit_digest_key = bytes(digest_key) if digest_key is not None else None
        self._explicit_recipient_keyring = recipient_keyring

    def _resolve_recipient_keyring(
        self, override: RecipientKeyring | None = None
    ) -> RecipientKeyring:
        if override is not None:
            return override
        if self._explicit_recipient_keyring is not None:
            return self._explicit_recipient_keyring
        return load_recipient_keyring()

    def _resolve_digest_key(self, override: bytes | None = None) -> bytes:
        if override is not None:
            key = bytes(override)
            if len(key) < MIN_SECRET_KEY_BYTES:
                raise ApiError(
                    503,
                    "connector_unavailable",
                    "Khóa HMAC toàn vẹn sự kiện ngắn hơn 32 byte.",
                )
            return key
        if self._explicit_digest_key is not None:
            if len(self._explicit_digest_key) < MIN_SECRET_KEY_BYTES:
                raise ApiError(
                    503,
                    "connector_unavailable",
                    "Khóa HMAC toàn vẹn sự kiện ngắn hơn 32 byte.",
                )
            return self._explicit_digest_key
        key_file = os.environ.get("RETAILOPS_EVENT_DIGEST_KEY_FILE", "").strip()
        return read_regular_secret_file(key_file, error_code="connector_unavailable")

    def link_external_customer(
        self,
        tenant_id: str,
        source_system: str,
        external_customer_id: str,
        customer_id: str,
        customer_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Explicitly pre-link an external customer ID to a RetailOps customer_id in tenant scope."""
        tenant_clean = str(tenant_id).strip()
        self.identity_store.tenant(tenant_clean)
        bstore = self.get_bstore(tenant_clean)
        with bstore.connection(write=True) as db:
            prior = db.execute(
                "SELECT customer_id FROM imported_events "
                "WHERE tenant_id=? AND source_system=? AND external_customer_id=? "
                "AND customer_id IS NOT NULL "
                "ORDER BY created_at LIMIT 1",
                (tenant_clean, source_system, external_customer_id),
            ).fetchone()
            if prior and prior["customer_id"] != customer_id:
                raise ApiError(
                    409,
                    "external_customer_mapping_conflict",
                    f"external_customer_id {external_customer_id} đã có đơn hàng thuộc về {prior['customer_id']}; "
                    "không thể liên kết sang khách hàng khác.",
                )
            db.execute(
                "INSERT INTO customers (id, name) VALUES (?, ?) ON CONFLICT DO NOTHING",
                (customer_id, customer_name or f"Khách {external_customer_id}"),
            )
        return self.identity_store.link_external_customer(
            tenant_clean, source_system, external_customer_id, customer_id
        )

    def _ensure_mapping(
        self,
        tenant_id: str,
        source_system: str,
        external_customer_id: str,
        customer_id: str,
    ) -> dict[str, Any]:
        try:
            return self.identity_store.link_external_customer(
                tenant_id, source_system, external_customer_id, customer_id
            )
        except ApiError as exc:
            if exc.status < 500:
                raise
            error: Exception = exc
        except Exception as exc:
            error = exc
        logger.error(
            "Identity mapping write failed after business commit tenant=%s source=%s customer=%s: %s",
            tenant_id,
            source_system,
            customer_id,
            error.__class__.__name__,
        )
        raise ApiError(
            503,
            "identity_mapping_pending",
            "Sự kiện đã được ghi nhận nhưng ánh xạ khách hàng chưa lưu được; "
            "gửi lại cùng event_id để hoàn tất.",
        ) from error

    def _ensure_mappings_batch(
        self,
        tenant_id: str,
        source_system: str,
        pairs: list[tuple[str, str]],
    ) -> None:
        if not pairs:
            return
        id_store = self.identity_store
        if (
            "link_external_customer" not in getattr(id_store, "__dict__", {})
            and hasattr(id_store, "bulk_link_external_customers")
        ):
            try:
                id_store.bulk_link_external_customers(tenant_id, source_system, pairs)
                return
            except ApiError as exc:
                if exc.status < 500:
                    raise
                error: Exception = exc
            except Exception as exc:
                error = exc
            logger.error(
                "Batch identity mapping write failed after business commit tenant=%s source=%s: %s",
                tenant_id,
                source_system,
                error.__class__.__name__,
            )
            raise ApiError(
                503,
                "identity_mapping_pending",
                "Sự kiện đã được ghi nhận nhưng ánh xạ khách hàng chưa lưu được; "
                "gửi lại cùng event_id để hoàn tất.",
            ) from error
        for ext_cid, cid in pairs:
            self._ensure_mapping(tenant_id, source_system, ext_cid, cid)

    def _invalidate_cache(
        self, tenant_id: str, customer_id: str | None, order_id: str | None = None
    ) -> None:
        if (
            customer_id
            and hasattr(self.sessions, "tool_caches")
            and tenant_id in self.sessions.tool_caches
        ):
            self.sessions.tool_caches[tenant_id].invalidate(
                customer=customer_id, tenant_id=tenant_id, order_id=order_id
            )

    def reconcile_mappings(self, tenant_id: str) -> dict[str, Any]:
        """Rebuild missing derived identity mappings from authoritative business imported_events."""
        tenant_clean = str(tenant_id).strip()
        self.identity_store.tenant(tenant_clean)
        bstore = self.get_bstore(tenant_clean)
        with bstore.connection() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT DISTINCT source_system, external_customer_id, customer_id "
                    "FROM imported_events "
                    "WHERE tenant_id=? AND external_customer_id IS NOT NULL AND customer_id IS NOT NULL "
                    "ORDER BY source_system, external_customer_id, customer_id",
                    (tenant_clean,),
                ).fetchall()
            ]
        healed = 0
        conflicts: list[dict[str, Any]] = []
        for row in rows:
            try:
                result = self.identity_store.link_external_customer(
                    tenant_clean,
                    row["source_system"],
                    row["external_customer_id"],
                    row["customer_id"],
                )
                healed += 1 if result.get("created") else 0
            except ApiError as exc:
                if exc.status >= 500:
                    raise
                conflicts.append({**row, "code": exc.code})
        return {"checked": len(rows), "healed": healed, "conflicts": conflicts}

    def _resolve_customer_in_tx(
        self,
        db: Any,
        *,
        tenant_id: str,
        connector_source: str,
        external_customer_id: str,
        display_name: Optional[str] = None,
        batch_state: dict[str, Any] | None = None,
    ) -> str:
        id_store = self.identity_store
        can_use_batch_map = (
            batch_state is not None
            and "prior_cust_map" in batch_state
            and "ext_customer_map" in batch_state
            and "get_external_customer_mapping" not in getattr(id_store, "__dict__", {})
        )
        if can_use_batch_map:
            assert batch_state is not None
            prior_cid = batch_state["prior_cust_map"].get(external_customer_id)
            mapped_cid = batch_state["ext_customer_map"].get(external_customer_id)
        else:
            prior = db.execute(
                "SELECT customer_id FROM imported_events "
                "WHERE tenant_id=? AND source_system=? AND external_customer_id=? "
                "AND customer_id IS NOT NULL "
                "ORDER BY created_at LIMIT 1",
                (tenant_id, connector_source, external_customer_id),
            ).fetchone()
            prior_cid = str(prior["customer_id"]) if prior else None
            mapped_cid = id_store.get_external_customer_mapping(
                tenant_id, connector_source, external_customer_id
            )
        if prior_cid:
            customer_id = str(prior_cid)
            if mapped_cid and mapped_cid != customer_id:
                raise ApiError(
                    409,
                    "external_customer_mapping_conflict",
                    f"external_customer_id {external_customer_id} đã có dữ liệu thuộc về {customer_id}, "
                    f"không thể tách sang {mapped_cid}.",
                )
        elif mapped_cid:
            customer_id = str(mapped_cid)
        else:
            customer_id = f"cust_{uuid.uuid4().hex}"

        cust_label = display_name or f"Khách {external_customer_id}"
        if display_name:
            db.execute(
                "INSERT INTO customers (id, name) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name",
                (customer_id, cust_label),
            )
        else:
            db.execute(
                "INSERT INTO customers (id, name) VALUES (?, ?) ON CONFLICT DO NOTHING",
                (customer_id, cust_label),
            )
        if can_use_batch_map:
            assert batch_state is not None
            batch_state["prior_cust_map"].setdefault(external_customer_id, customer_id)
        return customer_id

    @staticmethod
    def _max_entity_sequence_in_tx(
        db: Any,
        *,
        tenant_id: str,
        entity_kind: str,
        connector_source: str = "",
        order_id: str = "",
        entity_key: str = "",
        batch_state: dict[str, Any] | None = None,
    ) -> int | None:
        """Return max recorded sequence for the same entity in imported_events (portable SQLite/PG SQL)."""
        if batch_state is not None and "entity_max_seq" in batch_state:
            seq_map: dict[tuple[str, str, str], int] = batch_state["entity_max_seq"]
            return seq_map.get((entity_kind, order_id or connector_source, entity_key))

        if entity_kind == "order":
            row = db.execute(
                "SELECT MAX(sequence) AS max_seq FROM imported_events "
                "WHERE tenant_id=? AND order_id=? "
                "AND event_type IN ('order.created', 'order.status_changed')",
                (tenant_id, order_id),
            ).fetchone()
            return int(row["max_seq"]) if row and row["max_seq"] is not None else None

        if entity_kind == "customer":
            row = db.execute(
                "SELECT MAX(sequence) AS max_seq FROM imported_events "
                "WHERE tenant_id=? AND source_system=? AND external_customer_id=? "
                "AND event_type='customer.upserted'",
                (tenant_id, connector_source, entity_key),
            ).fetchone()
            return int(row["max_seq"]) if row and row["max_seq"] is not None else None

        if entity_kind == "product":
            rows = db.execute(
                "SELECT sequence, payload_json FROM imported_events "
                "WHERE tenant_id=? AND source_system=? AND event_type='product.upserted'",
                (tenant_id, connector_source),
            ).fetchall()
            matched = [
                int(r["sequence"])
                for r in rows
                if r["sequence"] is not None
                and json.loads(str(r["payload_json"])).get("data", {}).get("external_product_id")
                == entity_key
            ]
            return max(matched) if matched else None

        if entity_kind == "shipment":
            rows = db.execute(
                "SELECT sequence, payload_json FROM imported_events "
                "WHERE tenant_id=? AND order_id=? AND event_type='shipment.updated'",
                (tenant_id, order_id),
            ).fetchall()
            matched = [
                int(r["sequence"])
                for r in rows
                if r["sequence"] is not None
                and json.loads(str(r["payload_json"])).get("data", {}).get("external_shipment_id")
                == entity_key
            ]
            return max(matched) if matched else None

        if entity_kind == "payment":
            rows = db.execute(
                "SELECT sequence, payload_json FROM imported_events "
                "WHERE tenant_id=? AND order_id=? AND event_type='payment.updated'",
                (tenant_id, order_id),
            ).fetchall()
            matched = []
            for r in rows:
                if r["sequence"] is None:
                    continue
                d = json.loads(str(r["payload_json"])).get("data", {})
                if f"{d.get('provider')}::{d.get('provider_txn_ref')}" == entity_key:
                    matched.append(int(r["sequence"]))
            return max(matched) if matched else None

        if entity_kind == "refund":
            rows = db.execute(
                "SELECT sequence, payload_json FROM imported_events "
                "WHERE tenant_id=? AND order_id=? AND event_type='refund.updated'",
                (tenant_id, order_id),
            ).fetchall()
            matched = []
            for r in rows:
                if r["sequence"] is None:
                    continue
                d = json.loads(str(r["payload_json"])).get("data", {})
                if f"{d.get('provider')}::{d.get('provider_refund_ref')}" == entity_key:
                    matched.append(int(r["sequence"]))
            return max(matched) if matched else None

        return None

    @staticmethod
    def _recompute_order_payment_status_in_tx(db: Any, order_id: str) -> str:
        """Recompute orders.payment_status from payment_transactions and completed refunds (W6.1b-D6)."""
        paid_row = db.execute(
            "SELECT COALESCE(SUM(amount), 0) AS paid_sum FROM payment_transactions "
            "WHERE order_id=? AND status='succeeded'",
            (order_id,),
        ).fetchone()
        refunded_row = db.execute(
            "SELECT COALESCE(SUM(amount), 0) AS ref_sum FROM refunds "
            "WHERE order_id=? AND status='completed'",
            (order_id,),
        ).fetchone()
        paid_sum = int(paid_row["paid_sum"] or 0) if paid_row else 0
        ref_sum = int(refunded_row["ref_sum"] or 0) if refunded_row else 0
        if paid_sum <= 0:
            new_status = "unpaid"
        elif ref_sum >= paid_sum:
            new_status = "refunded"
        elif ref_sum > 0:
            new_status = "partially_refunded"
        else:
            new_status = "paid"
        db.execute(
            "UPDATE orders SET payment_status=? WHERE id=?",
            (new_status, order_id),
        )
        return new_status

    def ingest_event(
        self,
        event_or_raw: bytes | str | dict[str, Any],
        *,
        tenant_id: str,
        connector_source_system: str = "marketplace_sim",
        received_via: str = "import",
        digest_key: bytes | None = None,
        recipient_keyring: RecipientKeyring | None = None,
        expected_merchant_id: str | None = None,
        status_mapping: dict[str, Any] | None = None,
        actor_principal_id: str | None = None,
        rebase_offset_seconds: float = 0.0,
        _db: Any = None,
        _validated_status_mapping: dict[str, Any] | None = None,
        _skip_tenant_check: bool = False,
        _pending_mappings: list[tuple[str, str]] | None = None,
        _prevalidated: dict[str, Any] | None = None,
        _prevalidated_json: str | None = None,
        _batch_state: dict[str, Any] | None = None,
    ) -> ImportResult:
        """Validate and atomically ingest a single retailops-integration-v2 event."""
        require(
            received_via in ("http", "import"),
            400,
            "invalid_received_via",
            "Trường received_via phải là 'http' hoặc 'import'.",
        )
        tenant_clean = str(tenant_id or "").strip()
        require(
            bool(tenant_clean),
            400,
            "invalid_tenant_id",
            "Thiếu mã cửa hàng (tenant_id).",
        )
        connector_source = str(connector_source_system or "").strip()
        require(
            bool(connector_source),
            400,
            "invalid_source_system",
            "Thiếu mã nguồn tích hợp (source_system).",
        )

        # Resolve digest key BEFORE mutating anything (fail closed 503 if missing/short)
        resolved_digest_key = self._resolve_digest_key(digest_key)

        if _prevalidated is not None and isinstance(event_or_raw, bytes):
            raw_bytes = event_or_raw
            validated = _prevalidated
        else:
            if isinstance(event_or_raw, bytes):
                raw_bytes = event_or_raw
                try:
                    parsed = json.loads(raw_bytes.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ApiError(
                        422, "invalid_event_json", "Thân sự kiện không phải JSON UTF-8 hợp lệ."
                    ) from exc
            elif isinstance(event_or_raw, str):
                raw_bytes = event_or_raw.encode("utf-8")
                try:
                    parsed = json.loads(event_or_raw)
                except json.JSONDecodeError as exc:
                    raise ApiError(
                        422, "invalid_event_json", "Thân sự kiện không phải JSON hợp lệ."
                    ) from exc
            elif isinstance(event_or_raw, dict):
                parsed = copy.deepcopy(event_or_raw)
                raw_bytes = json.dumps(
                    parsed, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ).encode("utf-8")
            else:
                raise ApiError(422, "invalid_event_object", "Sự kiện phải là JSON object.")

            validated = validate_event_v2(
                parsed,
                allow_requests=False,
                allowed_marketplace_sources=frozenset({connector_source}),
            )

        payload_digest = compute_payload_hmac_digest(raw_bytes, resolved_digest_key)
        event_type = validated["event_type"]
        ensure_w6_1b_1_supported_event(event_type)

        if expected_merchant_id is not None and validated["merchant_id"] != expected_merchant_id:
            raise ApiError(
                401,
                "merchant_id_mismatch",
                "Trường merchant_id của sự kiện không khớp với connector cửa hàng.",
            )

        if not _skip_tenant_check:
            with self.identity_store.connection() as id_db:
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

        envelope_source = validated["source_system"]
        event_id = validated["event_id"]
        sequence = int(validated["sequence"])
        occurred_ts = float(iso_vn_to_epoch(validated["occurred_at"], "occurred_at")) + float(
            rebase_offset_seconds
        )
        data = validated["data"]
        active_recipient_keyring: RecipientKeyring | None = None
        if event_type == "order.created" and data.get("recipient") is not None:
            active_recipient_keyring = self._resolve_recipient_keyring(recipient_keyring)
            if (
                not os.environ.get("RETAILOPS_RECIPIENT_KEY_FILE", "").strip()
                and os.environ.get("RETAILOPS_ENV", "").strip().lower()
                not in ("production", "prod", "live")
            ):
                krmap = getattr(self.sessions, "_ephemeral_recipient_keyrings", None)
                if not isinstance(krmap, dict):
                    krmap = {}
                    setattr(self.sessions, "_ephemeral_recipient_keyrings", krmap)
                krmap[tenant_clean] = active_recipient_keyring

        bstore = self.get_bstore(tenant_clean) if _db is None else None
        if (
            bstore is not None
            and active_recipient_keyring is not None
            and not os.environ.get("RETAILOPS_RECIPIENT_KEY_FILE", "").strip()
            and os.environ.get("RETAILOPS_ENV", "").strip().lower()
            not in ("production", "prod", "live")
        ):
            bstore._ephemeral_recipient_keyring = active_recipient_keyring
        now = time.time()
        replay_row: dict[str, Any] | None = None
        mapped_ext_customer_id: str | None = None
        mapped_customer_id: str | None = None
        result_order_id = ""
        result_ext_order_id: str | None = None
        result_items_count = 0
        result_total = 0
        sequence_ignored = False

        @contextmanager
        def _tx_scope():
            if _db is not None:
                yield _db
            else:
                assert bstore is not None
                with bstore.connection(write=True) as conn:
                    bstore._ensure_purge_tombstone_table(conn)
                    yield conn

        with _tx_scope() as db:
            if _validated_status_mapping is not None:
                active_status_mapping = _validated_status_mapping
            elif status_mapping is not None:
                from retailops.integration.connectors import validate_status_mapping

                active_status_mapping = validate_status_mapping(status_mapping)
            else:
                conn_row = db.execute(
                    "SELECT status_mapping_json FROM integration_connectors WHERE source_system=?",
                    (connector_source,),
                ).fetchone()
                if conn_row is not None and conn_row["status_mapping_json"]:
                    from retailops.integration.connectors import validate_status_mapping

                    active_status_mapping = validate_status_mapping(
                        json.loads(str(conn_row["status_mapping_json"]))
                    )
                else:
                    from retailops.integration.connectors import (
                        CONNECTORS_DATA_DIR,
                        load_default_status_mapping,
                    )

                    default_file = CONNECTORS_DATA_DIR / f"{connector_source}.json"
                    if default_file.is_file():
                        active_status_mapping = load_default_status_mapping(connector_source)
                    else:
                        active_status_mapping = load_default_status_mapping("marketplace_sim")

            # Check order purge tombstone before deduplication so purged orders stay blocked
            if "external_order_id" in data and data["external_order_id"] is not None:
                ext_oid_check = str(data["external_order_id"])
                if _batch_state is not None and "tombstones" in _batch_state:
                    has_tomb = ext_oid_check in _batch_state["tombstones"]
                else:
                    has_tomb = (
                        db.execute(
                            "SELECT 1 FROM order_purge_tombstones WHERE order_id=? LIMIT 1",
                            (ext_oid_check,),
                        ).fetchone()
                        is not None
                    )
                if has_tomb:
                    raise ApiError(
                        409,
                        "order_purged_tombstone",
                        f"Đơn hàng {ext_oid_check} đã được quản trị viên xóa khỏi hệ thống (tombstone); không được phép tái tạo.",
                    )

            if (
                _batch_state is not None
                and _batch_state.get("fresh_imported_events")
                and (envelope_source, event_id) not in _batch_state["seen_events"]
            ):
                existing_event = None
            else:
                existing_event = db.execute(
                    "SELECT * FROM imported_events WHERE source_system=? AND event_id=?",
                    (envelope_source, event_id),
                ).fetchone()
            if existing_event is not None:
                if (
                    existing_event["tenant_id"] != tenant_clean
                    or existing_event["payload_digest"] != payload_digest
                ):
                    raise ApiError(
                        409,
                        "event_id_collision",
                        "event_id đã tồn tại với nội dung hoặc cửa hàng khác trong hệ thống nguồn.",
                    )
                replay_row = dict(existing_event)
            else:
                from retailops.integration.connectors import map_raw_status

                imp_event_id = str(uuid.uuid4())
                stored_event = validated
                redacted_fields: list[str] = []
                imp_status_val: str | None = None
                imp_total_val: int | None = None
                imp_currency_val: str | None = None
                seq_track_key: tuple[str, str, str] | None = None

                def _insert_imported_event_row() -> None:
                    payload_json_str = (
                        _prevalidated_json
                        if (_prevalidated_json is not None and not redacted_fields and stored_event is validated)
                        else json.dumps(stored_event, ensure_ascii=False)
                    )
                    db.execute(
                        """INSERT INTO imported_events (
                               id, source_system, event_id, tenant_id,
                               event_type, sequence, received_via, payload_digest, redacted_fields,
                               external_customer_id, customer_id, order_id, status, total, currency,
                               payload_json, signature, created_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                        (
                            imp_event_id,
                            envelope_source,
                            event_id,
                            tenant_clean,
                            event_type,
                            sequence,
                            received_via,
                            payload_digest,
                            json.dumps(redacted_fields, ensure_ascii=False)
                            if redacted_fields
                            else None,
                            mapped_ext_customer_id,
                            mapped_customer_id,
                            result_order_id or None,
                            imp_status_val,
                            imp_total_val,
                            imp_currency_val,
                            payload_json_str,
                            now,
                        ),
                    )
                    if _batch_state is not None:
                        if "seen_events" in _batch_state:
                            _batch_state["seen_events"].add((envelope_source, event_id))
                        if seq_track_key is not None and "entity_max_seq" in _batch_state:
                            prev_s = _batch_state["entity_max_seq"].get(seq_track_key)
                            if prev_s is None or sequence > prev_s:
                                _batch_state["entity_max_seq"][seq_track_key] = sequence

                if event_type == "product.upserted":
                    ext_pid = data["external_product_id"]
                    seq_track_key = ("product", connector_source, ext_pid)
                    max_seq = self._max_entity_sequence_in_tx(
                        db,
                        tenant_id=tenant_clean,
                        entity_kind="product",
                        connector_source=connector_source,
                        entity_key=ext_pid,
                        batch_state=_batch_state,
                    )
                    _insert_imported_event_row()
                    if max_seq is not None and sequence <= max_seq:
                        sequence_ignored = True
                    else:
                        raw_variants = data["variants"]
                        variant_labels = [v["variant_name"] for v in raw_variants]
                        total_stock = (
                            sum(v["stock"] for v in raw_variants if v["stock"] is not None)
                            if any(v["stock"] is not None for v in raw_variants)
                            else None
                        )
                        db.execute(
                            """INSERT INTO products(
                                   id, name, aliases, category, price, stock, warranty_days,
                                   description, variants, material, care, is_system_immutable,
                                   extra_data, created_at, updated_at
                               ) VALUES (?, ?, '[]', ?, ?, ?, ?, ?, ?, ?, ?, 0, '{}', ?, ?)
                               ON CONFLICT(id) DO UPDATE SET
                                   name=excluded.name,
                                   category=excluded.category,
                                   price=excluded.price,
                                   stock=excluded.stock,
                                   warranty_days=excluded.warranty_days,
                                   description=excluded.description,
                                   variants=excluded.variants,
                                   material=excluded.material,
                                   care=excluded.care,
                                   updated_at=excluded.updated_at""",
                            (
                                ext_pid,
                                data["title"],
                                data["category"],
                                data["price"],
                                total_stock,
                                data["warranty_days"],
                                data["description"] or "",
                                json.dumps(variant_labels, ensure_ascii=False),
                                data["material"],
                                data["care"],
                                occurred_ts,
                                occurred_ts,
                            ),
                        )
                        for v in raw_variants:
                            sku = v["sku"]
                            by_sku = db.execute(
                                "SELECT id FROM product_variants WHERE sku=?", (sku,)
                            ).fetchone()
                            if by_sku is not None:
                                db.execute(
                                    """UPDATE product_variants
                                       SET product_id=?, variant_name=?, size=?, color=?, stock=?, price=?
                                       WHERE id=?""",
                                    (
                                        ext_pid,
                                        v["variant_name"],
                                        v["size"],
                                        v["color"],
                                        v["stock"],
                                        v["price"] if v["price"] is not None else data["price"],
                                        by_sku["id"],
                                    ),
                                )
                            else:
                                unmapped_seed = db.execute(
                                    "SELECT id FROM product_variants "
                                    "WHERE product_id=? AND variant_name=? AND (sku IS NULL OR trim(sku) = '') "
                                    "LIMIT 1",
                                    (ext_pid, v["variant_name"]),
                                ).fetchone()
                                if unmapped_seed is not None:
                                    db.execute(
                                        """UPDATE product_variants
                                           SET sku=?, size=?, color=?, stock=?, price=?
                                           WHERE id=?""",
                                        (
                                            sku,
                                            v["size"],
                                            v["color"],
                                            v["stock"],
                                            v["price"] if v["price"] is not None else data["price"],
                                            unmapped_seed["id"],
                                        ),
                                    )
                                else:
                                    var_id = f"{ext_pid}-{sku}".replace(" ", "_")[:80]
                                    db.execute(
                                        """INSERT INTO product_variants(
                                               id, product_id, variant_name, size, color, stock, sku, price
                                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                                        (
                                            var_id,
                                            ext_pid,
                                            v["variant_name"],
                                            v["size"],
                                            v["color"],
                                            v["stock"],
                                            sku,
                                            v["price"] if v["price"] is not None else data["price"],
                                        ),
                                    )
                        recompute_product_orders_recipient_retention_in_tx(
                            db, product_id=ext_pid
                        )

                elif event_type == "customer.upserted":
                    mapped_ext_customer_id = data["external_customer_id"]
                    seq_track_key = ("customer", connector_source, mapped_ext_customer_id)
                    max_seq = self._max_entity_sequence_in_tx(
                        db,
                        tenant_id=tenant_clean,
                        entity_kind="customer",
                        connector_source=connector_source,
                        entity_key=mapped_ext_customer_id,
                        batch_state=_batch_state,
                    )
                    if max_seq is not None and sequence <= max_seq:
                        sequence_ignored = True
                        mapped_customer_id = self._resolve_customer_in_tx(
                            db,
                            tenant_id=tenant_clean,
                            connector_source=connector_source,
                            external_customer_id=mapped_ext_customer_id,
                            display_name=None,
                            batch_state=_batch_state,
                        )
                    else:
                        mapped_customer_id = self._resolve_customer_in_tx(
                            db,
                            tenant_id=tenant_clean,
                            connector_source=connector_source,
                            external_customer_id=mapped_ext_customer_id,
                            display_name=data["display_name"],
                            batch_state=_batch_state,
                        )
                    _insert_imported_event_row()

                elif event_type == "order.created":
                    stored_event, redacted_fields, ship_to_area = redact_order_created_recipient(
                        validated
                    )
                    ext_oid = data["external_order_id"]
                    result_ext_order_id = ext_oid
                    mapped_ext_customer_id = data["external_customer_id"]
                    mapped_customer_id = self._resolve_customer_in_tx(
                        db,
                        tenant_id=tenant_clean,
                        connector_source=connector_source,
                        external_customer_id=mapped_ext_customer_id,
                        batch_state=_batch_state,
                    )

                    existing_order = db.execute(
                        "SELECT id, customer_id, status FROM orders WHERE source_system=? AND external_order_id=?",
                        (connector_source, ext_oid),
                    ).fetchone()
                    if existing_order is not None:
                        internal_oid = str(existing_order["id"])
                        tomb_internal = db.execute(
                            "SELECT 1 FROM order_purge_tombstones WHERE order_id=? LIMIT 1",
                            (internal_oid,),
                        ).fetchone()
                        if tomb_internal is not None:
                            raise ApiError(
                                409,
                                "order_purged_tombstone",
                                f"Đơn hàng {internal_oid} đã bị xóa (tombstone); không được phép tái tạo.",
                            )
                        if existing_order["customer_id"] != mapped_customer_id:
                            raise ApiError(
                                409,
                                "order_owner_conflict",
                                "Đơn hàng nguồn đã thuộc về khách hàng khác; không được đổi chủ đơn hàng.",
                            )
                        result_order_id = internal_oid
                        max_seq = self._max_entity_sequence_in_tx(
                            db,
                            tenant_id=tenant_clean,
                            entity_kind="order",
                            order_id=result_order_id,
                            batch_state=_batch_state,
                        )
                    else:
                        result_order_id = f"ord_{uuid.uuid4().hex}"
                        max_seq = None
                    seq_track_key = ("order", result_order_id, "")

                    items = data["items"]
                    result_items_count = len(items)
                    result_total = int(data["total"])
                    imp_status_val = "pending"
                    imp_total_val = result_total
                    imp_currency_val = data["currency"]

                    _insert_imported_event_row()

                    if max_seq is not None and sequence <= max_seq:
                        sequence_ignored = True
                    else:
                        ordered_at_ts = float(
                            iso_vn_to_epoch(data["ordered_at"], "data.ordered_at")
                        ) + float(rebase_offset_seconds)
                        promised_ts = float(
                            iso_vn_to_epoch(
                                data["promised_delivery_by"], "data.promised_delivery_by"
                            )
                        ) + float(rebase_offset_seconds)

                        resolved_items: list[dict[str, Any]] = []
                        for item in items:
                            sku_row = db.execute(
                                "SELECT id, product_id FROM product_variants WHERE sku=?",
                                (item["sku"],),
                            ).fetchone()
                            if sku_row is not None:
                                prod_id = str(sku_row["product_id"])
                                var_id = str(sku_row["id"])
                            else:
                                prod_id = str(item["external_product_id"])
                                var_id = None
                                db.execute(
                                    """INSERT INTO products (
                                           id, name, aliases, price, variants,
                                           is_system_immutable, extra_data, created_at, updated_at
                                       ) VALUES (?, ?, '[]', ?, '[]', 0, '{}', ?, ?)
                                       ON CONFLICT(id) DO NOTHING""",
                                    (
                                        prod_id,
                                        item["title"],
                                        int(item["unit_price"]),
                                        occurred_ts,
                                        occurred_ts,
                                    ),
                                )
                            resolved_items.append(
                                {
                                    "product_id": prod_id,
                                    "variant_id": var_id,
                                    "title": item["title"],
                                    "variant_name": item["variant_name"],
                                    "quantity": int(item["quantity"]),
                                    "unit_price": int(item["unit_price"]),
                                }
                            )

                        primary_pid = resolved_items[0]["product_id"]
                        primary_title = resolved_items[0]["title"]
                        order_name = (
                            primary_title
                            if len(resolved_items) == 1
                            else f"{primary_title} và {len(resolved_items) - 1} sản phẩm khác"
                        )
                        order_variant = resolved_items[0]["variant_name"] or "Tiêu chuẩn"

                        if existing_order is None:
                            db.execute(
                                """INSERT INTO orders (
                                       id, customer_id, product_id, source_system, external_order_id,
                                       name, variant, amount, status, ordered_at, ordered_at_backfilled,
                                       payment_method, payment_status, shipping_fee, ship_to_area,
                                       promised_delivery_by, version, cancel_reason, delivered_at
                                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, 0, ?, 'unpaid', ?, ?, ?, 1, NULL, NULL)""",
                                (
                                    result_order_id,
                                    mapped_customer_id,
                                    primary_pid,
                                    connector_source,
                                    ext_oid,
                                    order_name,
                                    order_variant,
                                    result_total,
                                    ordered_at_ts,
                                    data["payment_method"],
                                    int(data["shipping_fee"]),
                                    ship_to_area,
                                    promised_ts,
                                ),
                            )
                        else:
                            db.execute(
                                """UPDATE orders
                                   SET name=?, variant=?, amount=?, product_id=?,
                                       ordered_at=?, ordered_at_backfilled=0,
                                       payment_method=?, shipping_fee=?, ship_to_area=?,
                                       promised_delivery_by=?, version=version+1
                                   WHERE id=?""",
                                (
                                    order_name,
                                    order_variant,
                                    result_total,
                                    primary_pid,
                                    ordered_at_ts,
                                    data["payment_method"],
                                    int(data["shipping_fee"]),
                                    ship_to_area,
                                    promised_ts,
                                    result_order_id,
                                ),
                            )

                        db.execute("DELETE FROM order_items WHERE order_id=?", (result_order_id,))
                        for r_item in resolved_items:
                            qty = r_item["quantity"]
                            u_price = r_item["unit_price"]
                            db.execute(
                                """INSERT INTO order_items (
                                       id, tenant_id, order_id, product_id, variant_id,
                                       product_title, variant_name, quantity, unit_price, subtotal, created_at
                                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (
                                    str(uuid.uuid4()),
                                    tenant_clean,
                                    result_order_id,
                                    r_item["product_id"],
                                    r_item["variant_id"],
                                    r_item["title"],
                                    r_item["variant_name"],
                                    qty,
                                    u_price,
                                    qty * u_price,
                                    occurred_ts,
                                ),
                            )

                        if data.get("recipient") is not None:
                            assert active_recipient_keyring is not None
                            enc_rec = active_recipient_keyring.encrypt_recipient_record(
                                data["recipient"],
                                tenant_id=tenant_clean,
                                order_id=result_order_id,
                            )
                            db.execute(
                                """INSERT INTO order_recipients (
                                       order_id, name_enc, phone_enc, address_line_enc,
                                       phone_lookup_hmac, ward, district, province, phone_masked,
                                       created_at, retention_until
                                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                                   ON CONFLICT(order_id) DO UPDATE SET
                                       name_enc=excluded.name_enc,
                                       phone_enc=excluded.phone_enc,
                                       address_line_enc=excluded.address_line_enc,
                                       phone_lookup_hmac=excluded.phone_lookup_hmac,
                                       ward=excluded.ward,
                                       district=excluded.district,
                                       province=excluded.province,
                                       phone_masked=excluded.phone_masked""",
                                (
                                    result_order_id,
                                    enc_rec["name_enc"],
                                    enc_rec["phone_enc"],
                                    enc_rec["address_line_enc"],
                                    enc_rec["phone_lookup_hmac"],
                                    enc_rec["ward"],
                                    enc_rec["district"],
                                    enc_rec["province"],
                                    enc_rec["phone_masked"],
                                    occurred_ts,
                                ),
                            )
                            if existing_order is not None and existing_order["status"] in (
                                "delivered",
                                "cancelled",
                            ):
                                sync_order_recipient_retention_in_tx(
                                    db,
                                    order_id=result_order_id,
                                    status=str(existing_order["status"]),
                                    transition_ts=occurred_ts,
                                )

                        audit_payload = {
                            "source_system": connector_source,
                            "event_id": event_id,
                            "external_customer_id": mapped_ext_customer_id,
                            "external_order_id": ext_oid,
                            "order_id": result_order_id,
                            "total": result_total,
                            "currency": data["currency"],
                            "status": "pending",
                            "actor_principal_id": actor_principal_id,
                            "items_count": result_items_count,
                        }
                        db.execute(
                            "INSERT INTO business_events (customer_id, created_at, kind, order_id, payload) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (
                                mapped_customer_id,
                                now,
                                "order_imported",
                                result_order_id,
                                json.dumps(audit_payload, ensure_ascii=False),
                            ),
                        )

                elif event_type == "order.status_changed":
                    ext_oid = data["external_order_id"]
                    result_ext_order_id = ext_oid
                    ord_row = db.execute(
                        "SELECT id, customer_id, status, delivered_at FROM orders "
                        "WHERE source_system=? AND external_order_id=?",
                        (connector_source, ext_oid),
                    ).fetchone()
                    require(
                        ord_row is not None,
                        404,
                        "order_not_found",
                        f"Không tìm thấy đơn hàng nguồn '{ext_oid}' thuộc '{connector_source}'.",
                    )
                    result_order_id = str(ord_row["id"])
                    mapped_customer_id = str(ord_row["customer_id"])

                    raw_status = data["status"]
                    canonical_status = map_raw_status(
                        active_status_mapping, "order", raw_status
                    )
                    imp_status_val = raw_status

                    seq_track_key = ("order", result_order_id, "")
                    max_seq = self._max_entity_sequence_in_tx(
                        db,
                        tenant_id=tenant_clean,
                        entity_kind="order",
                        order_id=result_order_id,
                        batch_state=_batch_state,
                    )
                    _insert_imported_event_row()

                    curr_order_status = str(ord_row["status"])
                    if (max_seq is not None and sequence <= max_seq) or not can_advance_order_status(
                        curr_order_status, canonical_status
                    ):
                        sequence_ignored = True
                    else:
                        delivered_at_val = ord_row["delivered_at"]
                        if canonical_status == "delivered" and delivered_at_val is None:
                            delivered_at_val = occurred_ts
                        cancel_reason_val = (
                            data["reason"] if canonical_status == "cancelled" else None
                        )
                        db.execute(
                            """UPDATE orders
                               SET status=?,
                                   delivered_at=?,
                                   cancel_reason=COALESCE(?, cancel_reason),
                                   version=version+1
                               WHERE id=?""",
                            (
                                canonical_status,
                                delivered_at_val,
                                cancel_reason_val,
                                result_order_id,
                            ),
                        )
                        sync_order_recipient_retention_in_tx(
                            db,
                            order_id=result_order_id,
                            status=canonical_status,
                            transition_ts=occurred_ts,
                            delivered_at=delivered_at_val,
                        )

                elif event_type == "shipment.updated":
                    ext_oid = data["external_order_id"]
                    ext_shp_id = data["external_shipment_id"]
                    result_ext_order_id = ext_oid
                    ord_row = db.execute(
                        "SELECT id, customer_id FROM orders "
                        "WHERE source_system=? AND external_order_id=?",
                        (connector_source, ext_oid),
                    ).fetchone()
                    require(
                        ord_row is not None,
                        404,
                        "order_not_found",
                        f"Không tìm thấy đơn hàng nguồn '{ext_oid}' thuộc '{connector_source}'.",
                    )
                    result_order_id = str(ord_row["id"])
                    mapped_customer_id = str(ord_row["customer_id"])

                    carrier = data["carrier"]
                    carrier_status_raw = data["carrier_status_raw"]
                    canonical_status = map_raw_status(
                        active_status_mapping,
                        "shipment",
                        carrier_status_raw,
                        carrier=carrier,
                    )
                    imp_status_val = carrier_status_raw

                    existing_shp = db.execute(
                        "SELECT shipment_id, order_id, status, delivery_attempts FROM shipments "
                        "WHERE source_system=? AND external_shipment_id=?",
                        (connector_source, ext_shp_id),
                    ).fetchone()
                    if existing_shp is not None and str(existing_shp["order_id"]) != result_order_id:
                        raise ApiError(
                            409,
                            "shipment_order_conflict",
                            "Vận đơn nguồn đã gắn với đơn hàng khác.",
                        )

                    seq_track_key = ("shipment", result_order_id, ext_shp_id)
                    max_seq = self._max_entity_sequence_in_tx(
                        db,
                        tenant_id=tenant_clean,
                        entity_kind="shipment",
                        order_id=result_order_id,
                        entity_key=ext_shp_id,
                        batch_state=_batch_state,
                    )
                    _insert_imported_event_row()

                    if max_seq is not None and sequence <= max_seq:
                        sequence_ignored = True
                    elif existing_shp is not None and not can_advance_shipment_status(
                        str(existing_shp["status"]), canonical_status
                    ):
                        sequence_ignored = True
                    else:
                        est_ts = (
                            float(
                                iso_vn_to_epoch(
                                    data["estimated_delivery_at"],
                                    "data.estimated_delivery_at",
                                )
                            )
                            + float(rebase_offset_seconds)
                            if data["estimated_delivery_at"] is not None
                            else None
                        )
                        delivered_ts = occurred_ts if canonical_status == "delivered" else None
                        hub_clean = (data["hub_name"] or "").strip()
                        dist_clean = str(data["district"]).strip()
                        prov_clean = str(data["province"]).strip()
                        current_area = (
                            f"{hub_clean}, {dist_clean}, {prov_clean}"
                            if hub_clean
                            else f"{dist_clean}, {prov_clean}"
                        )[:200]
                        incoming_attempts = int(data["delivery_attempts"])

                        if existing_shp is None:
                            shipment_id = f"shp_{uuid.uuid4().hex}"
                            db.execute(
                                """INSERT INTO shipments (
                                       shipment_id, order_id, source_system, external_shipment_id,
                                       carrier, tracking_code, status, carrier_status_raw,
                                       current_area, shipper_name, shipper_phone_masked,
                                       estimated_delivery_at, delivered_at, delivery_attempts, updated_at
                                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (
                                    shipment_id,
                                    result_order_id,
                                    connector_source,
                                    ext_shp_id,
                                    carrier,
                                    data["tracking_code"],
                                    canonical_status,
                                    carrier_status_raw,
                                    current_area,
                                    data["shipper_name"],
                                    data["shipper_phone_masked"],
                                    est_ts,
                                    delivered_ts,
                                    incoming_attempts,
                                    occurred_ts,
                                ),
                            )
                        else:
                            shipment_id = str(existing_shp["shipment_id"])
                            new_attempts = max(
                                int(existing_shp["delivery_attempts"]), incoming_attempts
                            )
                            db.execute(
                                """UPDATE shipments
                                   SET carrier=?,
                                       tracking_code=?,
                                       status=?,
                                       carrier_status_raw=?,
                                       current_area=?,
                                       shipper_name=COALESCE(?, shipper_name),
                                       shipper_phone_masked=COALESCE(?, shipper_phone_masked),
                                       estimated_delivery_at=?,
                                       delivered_at=COALESCE(delivered_at, ?),
                                       delivery_attempts=?,
                                       updated_at=?
                                   WHERE shipment_id=?""",
                                (
                                    carrier,
                                    data["tracking_code"],
                                    canonical_status,
                                    carrier_status_raw,
                                    current_area,
                                    data["shipper_name"],
                                    data["shipper_phone_masked"],
                                    est_ts,
                                    delivered_ts,
                                    new_attempts,
                                    occurred_ts,
                                    shipment_id,
                                ),
                            )

                        db.execute(
                            """INSERT INTO shipment_events (
                                   shipment_event_id, shipment_id, occurred_at, status,
                                   carrier_status_raw, description, fail_reason,
                                   hub_name, district, province, estimated_delivery_at, source_event_id
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                f"shpevt_{uuid.uuid4().hex}",
                                shipment_id,
                                occurred_ts,
                                canonical_status,
                                carrier_status_raw,
                                data["description"],
                                data["fail_reason"],
                                data["hub_name"],
                                data["district"],
                                data["province"],
                                est_ts,
                                imp_event_id,
                            ),
                        )
                        if canonical_status == "delivered":
                            db.execute(
                                "UPDATE orders SET delivered_at=COALESCE(delivered_at, ?) WHERE id=?",
                                (occurred_ts, result_order_id),
                            )
                            ord_after = db.execute(
                                "SELECT status, delivered_at FROM orders WHERE id=?",
                                (result_order_id,),
                            ).fetchone()
                            if ord_after is not None and ord_after["status"] == "delivered":
                                sync_order_recipient_retention_in_tx(
                                    db,
                                    order_id=result_order_id,
                                    status="delivered",
                                    transition_ts=occurred_ts,
                                    delivered_at=ord_after["delivered_at"],
                                )

                elif event_type == "payment.updated":
                    ext_oid = data["external_order_id"]
                    result_ext_order_id = ext_oid
                    ord_row = db.execute(
                        "SELECT id, customer_id FROM orders "
                        "WHERE source_system=? AND external_order_id=?",
                        (connector_source, ext_oid),
                    ).fetchone()
                    require(
                        ord_row is not None,
                        404,
                        "order_not_found",
                        f"Không tìm thấy đơn hàng nguồn '{ext_oid}' thuộc '{connector_source}'.",
                    )
                    result_order_id = str(ord_row["id"])
                    mapped_customer_id = str(ord_row["customer_id"])

                    provider = data["provider"]
                    txn_ref = data["provider_txn_ref"]
                    raw_status = data["provider_status_raw"]
                    canonical_status = map_raw_status(
                        active_status_mapping, "payment", raw_status
                    )
                    amount = int(data["amount"])
                    imp_status_val = raw_status
                    imp_total_val = amount
                    result_total = amount

                    existing_pay = db.execute(
                        "SELECT payment_id, order_id, status FROM payment_transactions "
                        "WHERE provider=? AND provider_txn_ref=?",
                        (provider, txn_ref),
                    ).fetchone()
                    if existing_pay is not None and str(existing_pay["order_id"]) != result_order_id:
                        raise ApiError(
                            409,
                            "payment_order_conflict",
                            "Giao dịch thanh toán nguồn đã gắn với đơn hàng khác.",
                        )

                    seq_track_key = ("payment", result_order_id, f"{provider}::{txn_ref}")
                    max_seq = self._max_entity_sequence_in_tx(
                        db,
                        tenant_id=tenant_clean,
                        entity_kind="payment",
                        order_id=result_order_id,
                        entity_key=f"{provider}::{txn_ref}",
                        batch_state=_batch_state,
                    )
                    _insert_imported_event_row()

                    if max_seq is not None and sequence <= max_seq:
                        sequence_ignored = True
                    elif existing_pay is not None and not can_advance_payment_status(
                        str(existing_pay["status"]), canonical_status
                    ):
                        sequence_ignored = True
                    else:
                        settled_ts = (
                            float(iso_vn_to_epoch(data["settled_at"], "data.settled_at"))
                            + float(rebase_offset_seconds)
                            if data["settled_at"] is not None
                            else (occurred_ts if canonical_status == "succeeded" else None)
                        )
                        if existing_pay is None:
                            db.execute(
                                """INSERT INTO payment_transactions (
                                       payment_id, order_id, provider, provider_txn_ref,
                                       method, amount, status, provider_status_raw,
                                       created_at, settled_at
                                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (
                                    f"pay_{uuid.uuid4().hex}",
                                    result_order_id,
                                    provider,
                                    txn_ref,
                                    data["method"],
                                    amount,
                                    canonical_status,
                                    raw_status,
                                    occurred_ts,
                                    settled_ts,
                                ),
                            )
                        else:
                            db.execute(
                                """UPDATE payment_transactions
                                   SET method=?,
                                       amount=?,
                                       status=?,
                                       provider_status_raw=?,
                                       settled_at=COALESCE(settled_at, ?)
                                   WHERE payment_id=?""",
                                (
                                    data["method"],
                                    amount,
                                    canonical_status,
                                    raw_status,
                                    settled_ts,
                                    existing_pay["payment_id"],
                                ),
                            )
                        self._recompute_order_payment_status_in_tx(db, result_order_id)

                elif event_type == "voucher.issued":
                    ext_vid = str(data["external_voucher_id"])
                    code_val = str(data["code"])
                    vtype_val = str(data["voucher_type"])
                    val_int = int(data["value"])
                    req_ref_raw = data.get("request_ref")
                    req_ref = str(req_ref_raw).strip() if req_ref_raw is not None else ""
                    ext_oid_opt = data.get("external_order_id")
                    result_ext_order_id = str(ext_oid_opt) if ext_oid_opt is not None else None
                    imp_total_val = val_int
                    imp_currency_val = "VND"

                    comp_row = (
                        db.execute(
                            """SELECT * FROM delivery_compensations
                               WHERE request_id = ? OR compensation_id = ?
                               ORDER BY compensation_id ASC
                               LIMIT 1""",
                            (req_ref, req_ref),
                        ).fetchone()
                        if req_ref
                        else None
                    )
                    matched_ord_row = None
                    if comp_row is not None and str(comp_row["status"]) == "requested":
                        cand_ord = db.execute(
                            "SELECT * FROM orders WHERE id = ?",
                            (str(comp_row["order_id"]),),
                        ).fetchone()
                        if (
                            cand_ord is not None
                            and str(cand_ord["source_system"]) == envelope_source
                            and (
                                ext_oid_opt is None
                                or str(cand_ord["external_order_id"] or "") == str(ext_oid_opt)
                            )
                        ):
                            matched_ord_row = cand_ord

                    if comp_row is not None and matched_ord_row is not None:
                        comp_id_str = str(comp_row["compensation_id"])
                        upd_comp = db.execute(
                            """UPDATE delivery_compensations
                               SET status = 'issued'
                               WHERE compensation_id = ?
                                 AND status = 'requested'""",
                            (comp_id_str,),
                        )
                        if upd_comp.rowcount == 1:
                            result_order_id = str(matched_ord_row["id"])
                            result_ext_order_id = matched_ord_row["external_order_id"]
                            mapped_customer_id = str(matched_ord_row["customer_id"])
                            if data.get("external_customer_id"):
                                mapped_ext_customer_id = str(data["external_customer_id"])
                            imp_status_val = "issued"
                            result_total = val_int
                            _insert_imported_event_row()

                            valid_until_ts = (
                                float(iso_vn_to_epoch(data["valid_until"], "data.valid_until"))
                                + float(rebase_offset_seconds)
                                if data.get("valid_until")
                                else None
                            )
                            det_voucher_id = (
                                "vch_"
                                + hashlib.sha256(
                                    f"{envelope_source}\x00{ext_vid}".encode("utf-8")
                                ).hexdigest()[:24]
                            )
                            db.execute(
                                """INSERT INTO vouchers (
                                       voucher_id, source_system, external_voucher_id,
                                       customer_id, order_id, compensation_id,
                                       code, voucher_type, value, valid_until, issued_at
                                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                   ON CONFLICT(source_system, external_voucher_id) DO NOTHING""",
                                (
                                    det_voucher_id,
                                    envelope_source,
                                    ext_vid,
                                    mapped_customer_id,
                                    result_order_id,
                                    comp_id_str,
                                    code_val,
                                    vtype_val,
                                    val_int,
                                    valid_until_ts,
                                    occurred_ts,
                                ),
                            )
                            audit_vch = json.dumps(
                                {
                                    "voucher_id": det_voucher_id,
                                    "external_voucher_id": ext_vid,
                                    "compensation_id": comp_id_str,
                                    "voucher_type": vtype_val,
                                    "value": val_int,
                                    "event_id": event_id,
                                },
                                ensure_ascii=False,
                            )
                            db.execute(
                                "INSERT INTO business_events(customer_id, created_at, kind, order_id, payload) VALUES (?, ?, ?, ?, ?)",
                                (
                                    mapped_customer_id,
                                    occurred_ts,
                                    "voucher_issued",
                                    result_order_id,
                                    audit_vch,
                                ),
                            )
                        else:
                            imp_status_val = "ignored_unmatched_request"
                            _insert_imported_event_row()
                    else:
                        imp_status_val = "ignored_unmatched_request"
                        _insert_imported_event_row()

                elif event_type == "refund.updated":
                    ext_oid = data["external_order_id"]
                    result_ext_order_id = ext_oid
                    ord_row = db.execute(
                        "SELECT id, customer_id, amount FROM orders "
                        "WHERE source_system=? AND external_order_id=?",
                        (connector_source, ext_oid),
                    ).fetchone()
                    require(
                        ord_row is not None,
                        404,
                        "order_not_found",
                        f"Không tìm thấy đơn hàng nguồn '{ext_oid}' thuộc '{connector_source}'.",
                    )
                    result_order_id = str(ord_row["id"])
                    mapped_customer_id = str(ord_row["customer_id"])
                    order_requested_cap = int(ord_row["amount"] or 0)

                    provider = data["provider"]
                    refund_ref = data["provider_refund_ref"]
                    raw_status = data["provider_status_raw"]
                    canonical_status = map_raw_status(
                        active_status_mapping, "refund", raw_status
                    )
                    amount = int(data["amount"])
                    imp_status_val = raw_status
                    imp_total_val = amount
                    result_total = amount

                    existing_ref = db.execute(
                        "SELECT refund_id, order_id, status, request_id, initiated_at FROM refunds "
                        "WHERE provider=? AND provider_refund_ref=?",
                        (provider, refund_ref),
                    ).fetchone()
                    if existing_ref is not None and str(existing_ref["order_id"]) != result_order_id:
                        raise ApiError(
                            409,
                            "refund_order_conflict",
                            "Giao dịch hoàn tiền nguồn đã gắn với đơn hàng khác.",
                        )

                    payment_id_val: str | None = None
                    if data["provider_txn_ref"] is not None:
                        pay_row = db.execute(
                            "SELECT payment_id, order_id FROM payment_transactions "
                            "WHERE provider=? AND provider_txn_ref=?",
                            (provider, data["provider_txn_ref"]),
                        ).fetchone()
                        if pay_row is None:
                            pay_row = db.execute(
                                "SELECT payment_id, order_id FROM payment_transactions "
                                "WHERE order_id=? AND provider_txn_ref=?",
                                (result_order_id, data["provider_txn_ref"]),
                            ).fetchone()
                        if pay_row is None or str(pay_row["order_id"]) != result_order_id:
                            raise ApiError(
                                422,
                                "payment_transaction_not_found",
                                "Không tìm thấy giao dịch thanh toán gốc thuộc đơn hàng cho hoàn tiền này.",
                            )
                        payment_id_val = str(pay_row["payment_id"])

                    seq_track_key = ("refund", result_order_id, f"{provider}::{refund_ref}")
                    max_seq = self._max_entity_sequence_in_tx(
                        db,
                        tenant_id=tenant_clean,
                        entity_kind="refund",
                        order_id=result_order_id,
                        entity_key=f"{provider}::{refund_ref}",
                        batch_state=_batch_state,
                    )
                    will_ignore = (max_seq is not None and sequence <= max_seq) or (
                        existing_ref is not None
                        and not can_advance_refund_status(
                            str(existing_ref["status"]), canonical_status
                        )
                    )

                    if not will_ignore:
                        paid_row = db.execute(
                            "SELECT COALESCE(SUM(amount), 0) AS paid_sum FROM payment_transactions "
                            "WHERE order_id=? AND status='succeeded'",
                            (result_order_id,),
                        ).fetchone()
                        paid_sum = int(paid_row["paid_sum"] or 0) if paid_row else 0
                        other_ref_row = db.execute(
                            "SELECT COALESCE(SUM(amount), 0) AS ref_sum FROM refunds "
                            "WHERE order_id=? AND status <> 'failed' "
                            "AND NOT (provider=? AND provider_refund_ref=?)",
                            (result_order_id, provider, refund_ref),
                        ).fetchone()
                        other_ref_sum = (
                            int(other_ref_row["ref_sum"] or 0) if other_ref_row else 0
                        )
                        effective_total = (
                            amount
                            if canonical_status == "failed"
                            else (other_ref_sum + amount)
                        )
                        if effective_total > paid_sum:
                            raise ApiError(
                                422,
                                "refund_exceeds_paid_amount",
                                "Tổng số tiền hoàn vượt quá số tiền đã thu của đơn hàng.",
                            )

                    _insert_imported_event_row()

                    if will_ignore:
                        sequence_ignored = True
                    else:
                        init_ts = (
                            float(iso_vn_to_epoch(data["initiated_at"], "data.initiated_at"))
                            + float(rebase_offset_seconds)
                            if data["initiated_at"] is not None
                            else occurred_ts
                        )
                        comp_ts = (
                            float(iso_vn_to_epoch(data["completed_at"], "data.completed_at"))
                            + float(rebase_offset_seconds)
                            if data["completed_at"] is not None
                            else (occurred_ts if canonical_status == "completed" else None)
                        )
                        target_req: dict[str, Any] | None = None
                        linked_request_id: str | None = None
                        if existing_ref is not None and existing_ref["request_id"]:
                            # W6.1b-2-D5: Once linked, never relink to another request.
                            linked_request_id = str(existing_ref["request_id"])
                            linked_row = db.execute(
                                "SELECT * FROM order_action_requests WHERE request_id = ?",
                                (linked_request_id,),
                            ).fetchone()
                            if linked_row is not None:
                                target_req = dict(linked_row)
                        else:
                            waiting_rows = db.execute(
                                """SELECT * FROM order_action_requests
                                   WHERE order_id = ? AND refund_status = 'pending'
                                   ORDER BY created_at ASC, request_id ASC""",
                                (result_order_id,),
                            ).fetchall()
                            if len(waiting_rows) == 1:
                                cand = dict(waiting_rows[0])
                                is_approved_waiting = (
                                    cand["status"] in ("approved", "received", "inspected", "completed")
                                    and cand["refund_status"] == "pending"
                                    and cand["refund_decision"] == "approved"
                                )
                                if is_approved_waiting:
                                    req_ref_row = db.execute(
                                        "SELECT COALESCE(SUM(amount), 0) AS req_sum FROM refunds "
                                        "WHERE request_id = ? AND status <> 'failed' "
                                        "AND NOT (provider = ? AND provider_refund_ref = ?)",
                                        (cand["request_id"], provider, refund_ref),
                                    ).fetchone()
                                    req_ref_sum = int(req_ref_row["req_sum"] or 0) if req_ref_row else 0
                                    cand_total_refund = (
                                        amount if canonical_status == "failed" else (req_ref_sum + amount)
                                    )
                                    amount_ok = (
                                        amount <= order_requested_cap
                                        and cand_total_refund <= order_requested_cap
                                    )
                                    dec_row = db.execute(
                                        """SELECT MAX(created_at) AS approved_at
                                           FROM order_action_decisions
                                           WHERE request_id = ?
                                             AND (action = 'refund_approve' OR refund_decision = 'approved')""",
                                        (cand["request_id"],),
                                    ).fetchone()
                                    approved_at_raw = dec_row["approved_at"] if dec_row is not None else None
                                    if approved_at_raw is None:
                                        approved_at_raw = (
                                            cand.get("reviewed_at")
                                            or cand.get("updated_at")
                                            or cand.get("created_at")
                                        )
                                    effective_init_ts = (
                                        float(existing_ref["initiated_at"])
                                        if (
                                            existing_ref is not None
                                            and data["initiated_at"] is None
                                            and existing_ref["initiated_at"] is not None
                                        )
                                        else float(init_ts)
                                    )
                                    ts_ok = effective_init_ts > float(approved_at_raw)
                                    if amount_ok and ts_ok:
                                        target_req = cand
                                        linked_request_id = str(cand["request_id"])
                        if existing_ref is None:
                            db.execute(
                                """INSERT INTO refunds (
                                       refund_id, order_id, request_id, payment_id,
                                       provider, provider_refund_ref, amount, channel,
                                       status, provider_status_raw, initiated_at,
                                       completed_at, failure_reason
                                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (
                                    f"rfd_{uuid.uuid4().hex}",
                                    result_order_id,
                                    linked_request_id,
                                    payment_id_val,
                                    provider,
                                    refund_ref,
                                    amount,
                                    data["channel"],
                                    canonical_status,
                                    raw_status,
                                    init_ts,
                                    comp_ts,
                                    data["failure_reason"],
                                ),
                            )
                        else:
                            db.execute(
                                """UPDATE refunds
                                   SET request_id=COALESCE(request_id, ?),
                                       payment_id=COALESCE(?, payment_id),
                                       amount=?,
                                       channel=?,
                                       status=?,
                                       provider_status_raw=?,
                                       initiated_at=?,
                                       completed_at=COALESCE(completed_at, ?),
                                       failure_reason=?
                                   WHERE refund_id=?""",
                                (
                                    linked_request_id,
                                    payment_id_val,
                                    amount,
                                    data["channel"],
                                    canonical_status,
                                    raw_status,
                                    init_ts,
                                    comp_ts,
                                    data["failure_reason"],
                                    existing_ref["refund_id"],
                                ),
                            )
                        if target_req is not None and linked_request_id is not None:
                            oar_refund_map = {
                                "pending": "pending",
                                "processing": "pending",
                                "completed": "refunded",
                                "failed": "failed",
                            }
                            next_oar_refund_status = oar_refund_map[canonical_status]
                            new_req_ver = int(target_req["version"]) + 1
                            db.execute(
                                """UPDATE order_action_requests
                                   SET refund_status = ?,
                                       version = ?,
                                       updated_at = ?
                                   WHERE request_id = ?""",
                                (
                                    next_oar_refund_status,
                                    new_req_ver,
                                    occurred_ts,
                                    linked_request_id,
                                ),
                            )
                            dec_note = (
                                f"provider={provider} ref={refund_ref} "
                                f"status={canonical_status} ({raw_status})"
                            )[:500]
                            db.execute(
                                """INSERT INTO order_action_decisions (
                                       decision_id, request_id, case_id, order_id, conversation_id,
                                       action, from_status, to_status, from_refund_status, to_refund_status,
                                       refund_decision, inspection_outcome, actor_principal_id, actor_role,
                                       note, created_at
                                   ) VALUES (?, ?, ?, ?, ?, 'refund_provider_update', ?, ?, ?, ?, ?, ?, 'system', 'system', ?, ?)""",
                                (
                                    f"oad_{uuid.uuid4().hex}",
                                    linked_request_id,
                                    target_req["case_id"],
                                    target_req["order_id"],
                                    target_req["conversation_id"],
                                    target_req["status"],
                                    target_req["status"],
                                    target_req["refund_status"],
                                    next_oar_refund_status,
                                    target_req["refund_decision"],
                                    target_req["inspection_outcome"],
                                    dec_note,
                                    occurred_ts,
                                ),
                            )
                            audit_detail = json.dumps(
                                {
                                    "request_id": linked_request_id,
                                    "case_id": target_req["case_id"],
                                    "action": "refund_provider_update",
                                    "from_refund_status": target_req["refund_status"],
                                    "to_refund_status": next_oar_refund_status,
                                    "version": new_req_ver,
                                    "note": dec_note,
                                    "actor": {"principal_id": "system", "role": "system"},
                                },
                                ensure_ascii=False,
                            )
                            db.execute(
                                "INSERT INTO business_events(customer_id, created_at, kind, order_id, payload) VALUES (?, ?, ?, ?, ?)",
                                (
                                    target_req["customer_id"],
                                    occurred_ts,
                                    "order_action_refund_updated",
                                    target_req["order_id"],
                                    audit_detail,
                                ),
                            )
                        self._recompute_order_payment_status_in_tx(db, result_order_id)

        if replay_row is not None:
            r_cid = replay_row.get("customer_id")
            r_ext_cid = replay_row.get("external_customer_id")
            r_oid = replay_row.get("order_id") or ""
            if r_cid and r_ext_cid:
                if _pending_mappings is not None:
                    _pending_mappings.append((str(r_ext_cid), str(r_cid)))
                else:
                    self._ensure_mapping(
                        tenant_clean, connector_source, str(r_ext_cid), str(r_cid)
                    )
            return ImportResult(
                success=True,
                status="already_processed",
                order_id=str(r_oid),
                customer_id=str(r_cid or ""),
                tenant_id=tenant_clean,
                source_system=envelope_source,
                event_id=event_id,
                event_type=str(replay_row.get("event_type") or event_type),
                external_order_id=data.get("external_order_id"),
                is_replay=True,
                items_count=int(len(data.get("items") or [])),
                total=int(replay_row.get("total") or 0),
            )

        self._invalidate_cache(
            tenant_clean, mapped_customer_id, result_order_id or None
        )
        if mapped_ext_customer_id and mapped_customer_id:
            if _pending_mappings is not None:
                _pending_mappings.append((mapped_ext_customer_id, mapped_customer_id))
            else:
                self._ensure_mapping(
                    tenant_clean,
                    connector_source,
                    mapped_ext_customer_id,
                    mapped_customer_id,
                )

        return ImportResult(
            success=True,
            status="imported",
            order_id=result_order_id,
            customer_id=mapped_customer_id or "",
            tenant_id=tenant_clean,
            source_system=envelope_source,
            event_id=event_id,
            event_type=event_type,
            external_order_id=result_ext_order_id,
            is_replay=False,
            sequence_ignored=sequence_ignored,
            items_count=result_items_count,
            total=result_total,
        )
