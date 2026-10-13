"""Canonical sales order event schema, validation, and HMAC signature."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from retailops.core import ApiError, require

CANONICAL_FIELDS = (
    "source_system",
    "event_id",
    "tenant",
    "external_customer_id",
    "order_id",
    "status",
    "items",
    "total",
    "currency",
    "timestamp",
    "signature",
)

VALID_STATUSES = {"pending", "confirmed", "shipping", "delivered", "cancelled"}

ITEM_REQUIRED_FIELDS = ("product_id", "product_title", "quantity", "unit_price")
ITEM_OPTIONAL_FIELDS = ("variant_id", "variant_name")

MAX_ITEMS = 200
MAX_QUANTITY = 100_000
MAX_MONEY = 10 ** 12  # VND; keeps every value inside signed 64-bit database integers
MAX_TEXT = 255

IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}")
CURRENCY_RE = re.compile(r"[A-Z]{3}")

# Mapping from external status to internal RetailOps orders table status
INTERNAL_STATUS_MAPPING = {
    "pending": "pending",
    "confirmed": "pending",
    "shipping": "delivered",
    "delivered": "delivered",
    "cancelled": "cancelled",
}


def compute_signature(payload: Dict[str, Any], secret: str) -> str:
    """Compute HMAC-SHA256 signature over the canonical JSON representation of the payload.
    
    The 'signature' key itself is excluded from hashing.
    Payload keys are deterministically sorted with compact separators.
    """
    require(bool(secret), 400, "missing_secret", "Secret key is required to compute event signature.")
    clean_payload = {k: v for k, v in payload.items() if k != "signature"}
    canonical_bytes = json.dumps(
        clean_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), canonical_bytes, hashlib.sha256).hexdigest()


def sign_event(payload: Dict[str, Any], secret: str) -> str:
    """Alias for compute_signature."""
    return compute_signature(payload, secret)


def verify_event_signature(event_dict: Dict[str, Any], secret: str) -> bool:
    """Verify HMAC-SHA256 signature using constant-time comparison."""
    if not isinstance(event_dict, dict) or not secret:
        return False
    signature = event_dict.get("signature")
    if not signature or not isinstance(signature, str):
        return False
    expected = compute_signature(event_dict, secret)
    return hmac.compare_digest(signature.lower(), expected.lower())


import math


def parse_timestamp(timestamp_val: Any) -> float:
    """Parse ISO-8601 string or numeric timestamp to epoch seconds.

    Rejects boolean types, NaN, Infinity, and malformed date strings.
    """
    if type(timestamp_val) is bool:
        raise ApiError(400, "invalid_timestamp", f"Định dạng thời gian không hợp lệ: {timestamp_val}")
    if isinstance(timestamp_val, (int, float)):
        if math.isnan(timestamp_val) or math.isinf(timestamp_val):
            raise ApiError(400, "invalid_timestamp", "timestamp không được là NaN hoặc Infinity.")
        return float(timestamp_val)
    if isinstance(timestamp_val, str):
        ts_clean = timestamp_val.strip()
        lower = ts_clean.lower()
        if lower in ("nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"):
            raise ApiError(400, "invalid_timestamp", "timestamp không được là NaN hoặc Infinity.")
        if ts_clean.endswith("Z"):
            ts_clean = ts_clean[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(ts_clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            val = dt.timestamp()
            if math.isnan(val) or math.isinf(val):
                raise ApiError(400, "invalid_timestamp", "timestamp không được là NaN hoặc Infinity.")
            return val
        except ValueError:
            pass
        try:
            val = float(ts_clean)
            if math.isnan(val) or math.isinf(val):
                raise ApiError(400, "invalid_timestamp", "timestamp không được là NaN hoặc Infinity.")
            return val
        except ValueError:
            pass
    raise ApiError(400, "invalid_timestamp", f"Định dạng thời gian không hợp lệ: {timestamp_val}")


def validate_timestamp(
    timestamp_val: Any,
    max_age_seconds: int = 300,
    max_future_seconds: int = 60,
    reference_time: Optional[float] = None,
) -> float:
    """Validate timestamp drift against reference time (default time.time())."""
    epoch = parse_timestamp(timestamp_val)
    if math.isnan(epoch) or math.isinf(epoch):
        raise ApiError(400, "invalid_timestamp", "timestamp không được là NaN hoặc Infinity.")
    ref = reference_time if reference_time is not None else time.time()
    if math.isnan(ref) or math.isinf(ref):
        raise ApiError(400, "invalid_timestamp", "reference_time không được là NaN hoặc Infinity.")
    if epoch < ref - max_age_seconds:
        raise ApiError(
            400,
            "expired_timestamp",
            f"Event timestamp đã quá hạn ({ref - epoch:.1f}s > {max_age_seconds}s).",
        )
    if epoch > ref + max_future_seconds:
        raise ApiError(
            400,
            "future_timestamp",
            f"Event timestamp quá xa trong tương lai ({epoch - ref:.1f}s > {max_future_seconds}s).",
        )
    return epoch


def _is_strict_int(value: Any) -> bool:
    """True only for real ints: bool (a subclass of int), float and numeric strings are rejected."""
    return type(value) is int


def _is_identifier(value: Any) -> bool:
    return isinstance(value, str) and IDENTIFIER_RE.fullmatch(value) is not None


def validate_event_schema(data: Any) -> Dict[str, Any]:
    """Validate that the event is *exactly* the canonical contract.

    - exactly the 11 ``CANONICAL_FIELDS`` (missing and unexpected fields are both rejected);
    - each item has exactly the required item fields plus optional ``ITEM_OPTIONAL_FIELDS``;
    - ``quantity``, ``unit_price`` and ``total`` are strict ``int`` (no bool, float or str);
    - identifiers/currency/timestamp are well-formed strings and values are bounded.
    """
    require(isinstance(data, dict), 400, "invalid_event_type", "Event payload must be a JSON object / dict.")

    # 1. Exact field set
    for field in CANONICAL_FIELDS:
        require(field in data, 400, "missing_event_field", f"Thiếu trường bắt buộc trong event: {field}")
    extra = sorted(str(key) for key in data if key not in CANONICAL_FIELDS)
    require(not extra, 400, "unexpected_event_field", f"Event chứa trường không thuộc hợp đồng: {', '.join(extra)}")

    # 2. Identifiers
    require(_is_identifier(data["source_system"]),
            400, "invalid_source_system", "source_system phải là mã định danh hợp lệ (chữ, số, . _ : -).")
    require(_is_identifier(data["event_id"]),
            400, "invalid_event_id", "event_id phải là mã định danh hợp lệ (chữ, số, . _ : -).")
    require(_is_identifier(data["tenant"]),
            400, "invalid_tenant", "tenant phải là mã định danh hợp lệ (chữ, số, . _ : -).")

    # 3. P5-K4: external_customer_id MUST NOT be an email
    ext_cust = data["external_customer_id"]
    require(isinstance(ext_cust, str) and ext_cust.strip(),
            400, "invalid_external_customer_id", "external_customer_id phải là chuỗi không rỗng.")
    require("@" not in ext_cust,
            400, "invalid_external_customer_id",
            "external_customer_id phải là mã định danh từ hệ thống nguồn, không dùng email làm khóa.")
    require(_is_identifier(ext_cust),
            400, "invalid_external_customer_id", "external_customer_id phải là mã định danh hợp lệ (chữ, số, . _ : -).")

    # 4. order_id and status
    require(_is_identifier(data["order_id"]),
            400, "invalid_order_id", "order_id phải là mã định danh hợp lệ (chữ, số, . _ : -).")
    status = data["status"]
    require(isinstance(status, str) and status in VALID_STATUSES, 400, "invalid_status",
            f"Trạng thái đơn hàng không hợp lệ. Cho phép: {sorted(VALID_STATUSES)}")

    # 5. Items validation
    items = data["items"]
    require(isinstance(items, list) and 0 < len(items) <= MAX_ITEMS,
            400, "invalid_items", f"Đơn hàng phải có từ 1 đến {MAX_ITEMS} sản phẩm trong items.")

    calculated_total = 0
    for idx, item in enumerate(items):
        require(isinstance(item, dict), 400, "invalid_item", f"Item tại vị trí {idx} phải là dictionary.")
        extra_item = sorted(str(key) for key in item if key not in ITEM_REQUIRED_FIELDS + ITEM_OPTIONAL_FIELDS)
        require(not extra_item, 400, "unexpected_item_field",
                f"Item tại vị trí {idx} chứa trường không thuộc hợp đồng: {', '.join(extra_item)}")
        require(_is_identifier(item.get("product_id")),
                400, "invalid_item_product_id", f"Item tại vị trí {idx} thiếu product_id hợp lệ.")
        quantity = item.get("quantity")
        require(_is_strict_int(quantity) and 0 < quantity <= MAX_QUANTITY,
                400, "invalid_item_quantity",
                f"Item tại vị trí {idx} phải có quantity là số nguyên từ 1 đến {MAX_QUANTITY}.")
        unit_price = item.get("unit_price")
        require(_is_strict_int(unit_price) and 0 <= unit_price <= MAX_MONEY,
                400, "invalid_item_unit_price",
                f"Item tại vị trí {idx} phải có unit_price là số nguyên không âm (tối đa {MAX_MONEY}).")
        title = item.get("product_title")
        require(isinstance(title, str) and title.strip() and len(title) <= MAX_TEXT,
                400, "invalid_item_title", f"Item tại vị trí {idx} thiếu product_title hợp lệ.")
        for optional in ITEM_OPTIONAL_FIELDS:
            if optional in item:
                value = item[optional]
                require(isinstance(value, str) and value.strip() and len(value) <= MAX_TEXT,
                        400, "invalid_item_" + optional, f"Item tại vị trí {idx} có {optional} không hợp lệ.")
        calculated_total += quantity * unit_price

    # 6. Total amount check (exact, no rounding)
    total = data["total"]
    require(_is_strict_int(total) and 0 <= total <= MAX_MONEY,
            400, "invalid_total", "total phải là số nguyên không âm (VND).")
    require(total == calculated_total,
            400, "total_mismatch",
            f"Tổng tiền đơn hàng ({total}) không khớp với tổng giá trị các sản phẩm ({calculated_total}).")

    # 7. Currency and timestamp
    require(isinstance(data["currency"], str) and CURRENCY_RE.fullmatch(data["currency"]) is not None,
            400, "invalid_currency", "currency phải là mã tiền tệ 3 chữ in hoa (ví dụ: VND).")
    require(isinstance(data["timestamp"], str) and data["timestamp"].strip(),
            400, "invalid_timestamp", "timestamp phải là chuỗi ISO-8601.")
    parse_timestamp(data["timestamp"])

    # 8. Signature format (64-character hex string)
    sig = data["signature"]
    require(isinstance(sig, str) and re.fullmatch(r"[a-fA-F0-9]{64}", sig),
            400, "invalid_signature_format", "signature phải là chuỗi hex SHA256 dài 64 ký tự.")

    return data
