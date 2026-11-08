"""Canonical v2 event ingestion, customer mapping, and reconciliation (W6.1b-D3, D6, D7, D8)."""

from __future__ import annotations

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
    ) -> str:
        prior = db.execute(
            "SELECT customer_id FROM imported_events "
            "WHERE tenant_id=? AND source_system=? AND external_customer_id=? "
            "AND customer_id IS NOT NULL "
            "ORDER BY created_at LIMIT 1",
            (tenant_id, connector_source, external_customer_id),
        ).fetchone()
        mapped_cid = self.identity_store.get_external_customer_mapping(
            tenant_id, connector_source, external_customer_id
        )
        if prior:
            customer_id = str(prior["customer_id"])
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
        return customer_id

    def ingest_event(
        self,
        event_or_raw: bytes | str | dict[str, Any],
        *,
        tenant_id: str,
        connector_source_system: str = "marketplace_sim",
        received_via: str = "import",
        digest_key: bytes | None = None,
        expected_merchant_id: str | None = None,
        actor_principal_id: str | None = None,
        rebase_offset_seconds: float = 0.0,
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

        payload_digest = compute_payload_hmac_digest(raw_bytes, resolved_digest_key)

        validated = validate_event_v2(
            parsed,
            allow_requests=False,
            allowed_marketplace_sources=frozenset({connector_source}),
        )
        event_type = validated["event_type"]
        ensure_w6_1b_1_supported_event(event_type)

        if expected_merchant_id is not None and validated["merchant_id"] != expected_merchant_id:
            raise ApiError(
                401,
                "merchant_id_mismatch",
                "Trường merchant_id của sự kiện không khớp với connector cửa hàng.",
            )

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

        bstore = self.get_bstore(tenant_clean)
        now = time.time()
        replay_row: dict[str, Any] | None = None
        mapped_ext_customer_id: str | None = None
        mapped_customer_id: str | None = None
        result_order_id = ""
        result_ext_order_id: str | None = None
        result_items_count = 0
        result_total = 0

        with bstore.connection(write=True) as db:
            bstore._ensure_purge_tombstone_table(db)

            # Check order purge tombstone before deduplication so purged orders stay blocked
            if "external_order_id" in data and data["external_order_id"] is not None:
                ext_oid_check = str(data["external_order_id"])
                tomb = db.execute(
                    "SELECT 1 FROM order_purge_tombstones WHERE order_id=? LIMIT 1",
                    (ext_oid_check,),
                ).fetchone()
                if tomb is not None:
                    raise ApiError(
                        409,
                        "order_purged_tombstone",
                        f"Đơn hàng {ext_oid_check} đã được quản trị viên xóa khỏi hệ thống (tombstone); không được phép tái tạo.",
                    )

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
                stored_event = copy.deepcopy(validated)
                redacted_fields: list[str] = []

                if event_type == "product.upserted":
                    ext_pid = data["external_product_id"]
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

                elif event_type == "customer.upserted":
                    mapped_ext_customer_id = data["external_customer_id"]
                    mapped_customer_id = self._resolve_customer_in_tx(
                        db,
                        tenant_id=tenant_clean,
                        connector_source=connector_source,
                        external_customer_id=mapped_ext_customer_id,
                        display_name=data["display_name"],
                    )

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
                    else:
                        result_order_id = f"ord_{uuid.uuid4().hex}"

                    ordered_at_ts = float(
                        iso_vn_to_epoch(data["ordered_at"], "data.ordered_at")
                    ) + float(rebase_offset_seconds)
                    promised_ts = float(
                        iso_vn_to_epoch(
                            data["promised_delivery_by"], "data.promised_delivery_by"
                        )
                    ) + float(rebase_offset_seconds)

                    items = data["items"]
                    result_items_count = len(items)
                    result_total = int(data["total"])

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
                    canonical_status = DEFAULT_ORDER_STATUS_MAP.get(raw_status)
                    if canonical_status is None:
                        raise ApiError(
                            422,
                            "unknown_status_code",
                            f"Mã trạng thái đơn '{raw_status}' không có trong bảng ánh xạ.",
                        )
                    delivered_at_val = ord_row["delivered_at"]
                    if canonical_status == "delivered" and delivered_at_val is None:
                        delivered_at_val = occurred_ts
                    cancel_reason_val = data["reason"] if canonical_status == "cancelled" else None
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

                # Keep UNIQUE(source_system, event_id) aligned with envelope_source while preserving
                # connector_source on customer-bearing rows when connector_source == envelope_source.
                db.execute(
                    """INSERT INTO imported_events (
                           id, source_system, event_id, tenant_id,
                           event_type, sequence, received_via, payload_digest, redacted_fields,
                           external_customer_id, customer_id, order_id, status, total, currency,
                           payload_json, signature, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                    (
                        str(uuid.uuid4()),
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
                        data.get("status") if event_type == "order.status_changed" else (
                            "pending" if event_type == "order.created" else None
                        ),
                        result_total if event_type == "order.created" else None,
                        data.get("currency") if event_type == "order.created" else None,
                        json.dumps(stored_event, ensure_ascii=False),
                        now,
                    ),
                )

        if replay_row is not None:
            r_cid = replay_row.get("customer_id")
            r_ext_cid = replay_row.get("external_customer_id")
            r_oid = replay_row.get("order_id") or ""
            if r_cid and r_ext_cid:
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
            items_count=result_items_count,
            total=result_total,
        )
