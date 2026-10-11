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


def parse_timestamp(timestamp_val: Any) -> float:
    """Parse ISO-8601 string or numeric timestamp to epoch seconds."""
    if isinstance(timestamp_val, (int, float)):
        return float(timestamp_val)
    if isinstance(timestamp_val, str):
        ts_clean = timestamp_val.strip()
        if ts_clean.endswith("Z"):
            ts_clean = ts_clean[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(ts_clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            pass
        try:
            return float(ts_clean)
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
    ref = reference_time if reference_time is not None else time.time()
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


def validate_event_schema(data: Any) -> Dict[str, Any]:
    """Validate that the event matches all canonical fields and invariants."""
    require(isinstance(data, dict), 400, "invalid_event_type", "Event payload must be a JSON object / dict.")

    # 1. Required canonical fields
    for field in CANONICAL_FIELDS:
        require(field in data, 400, "missing_event_field", f"Thiếu trường bắt buộc trong event: {field}")

    # 2. String identifier validation
    require(isinstance(data["source_system"], str) and data["source_system"].strip(),
            400, "invalid_source_system", "source_system phải là chuỗi không rỗng.")
    require(isinstance(data["event_id"], str) and data["event_id"].strip(),
            400, "invalid_event_id", "event_id phải là chuỗi không rỗng.")
    require(isinstance(data["tenant"], str) and data["tenant"].strip(),
            400, "invalid_tenant", "tenant phải là chuỗi không rỗng.")

    # 3. P5-K4: external_customer_id MUST NOT be an email
    ext_cust = data["external_customer_id"]
    require(isinstance(ext_cust, str) and ext_cust.strip(),
            400, "invalid_external_customer_id", "external_customer_id phải là chuỗi không rỗng.")
    require("@" not in ext_cust and not re.search(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", ext_cust),
            400, "invalid_external_customer_id",
            "external_customer_id phải là mã định danh từ hệ thống nguồn, không dùng email làm khóa.")

    # 4. order_id and status
    require(isinstance(data["order_id"], str) and data["order_id"].strip(),
            400, "invalid_order_id", "order_id phải là chuỗi không rỗng.")
    status = data["status"]
    require(status in VALID_STATUSES, 400, "invalid_status",
            f"Trạng thái đơn hàng không hợp lệ: {status}. Cho phép: {sorted(VALID_STATUSES)}")

    # 5. Items validation
    items = data["items"]
    require(isinstance(items, list) and len(items) > 0,
            400, "invalid_items", "Đơn hàng phải có ít nhất một sản phẩm trong items.")

    calculated_total = 0
    for idx, item in enumerate(items):
        require(isinstance(item, dict), 400, "invalid_item", f"Item tại vị trí {idx} phải là dictionary.")
        require("product_id" in item and isinstance(item["product_id"], str) and item["product_id"].strip(),
                400, "invalid_item_product_id", f"Item tại vị trí {idx} thiếu product_id hợp lệ.")
        require("quantity" in item and isinstance(item["quantity"], int) and item["quantity"] > 0,
                400, "invalid_item_quantity", f"Item tại vị trí {idx} phải có quantity nguyên dương.")
        require("unit_price" in item and isinstance(item["unit_price"], (int, float)) and item["unit_price"] >= 0,
                400, "invalid_item_unit_price", f"Item tại vị trí {idx} phải có unit_price không âm.")
        title = item.get("product_title") or item.get("name")
        require(bool(title and isinstance(title, str)),
                400, "invalid_item_title", f"Item tại vị trí {idx} thiếu product_title.")
        calculated_total += int(item["quantity"]) * int(item["unit_price"])

    # 6. Total amount check
    total = data["total"]
    require(isinstance(total, (int, float)) and total >= 0,
            400, "invalid_total", "total phải là số không âm.")
    require(abs(int(total) - calculated_total) == 0,
            400, "total_mismatch",
            f"Tổng tiền đơn hàng ({total}) không khớp với tổng giá trị các sản phẩm ({calculated_total}).")

    # 7. Currency
    require(isinstance(data["currency"], str) and data["currency"].strip(),
            400, "invalid_currency", "currency phải là chuỗi mã tiền tệ (ví dụ: VND).")

    # 8. Signature format (64-character hex string)
    sig = data["signature"]
    require(isinstance(sig, str) and re.fullmatch(r"[a-fA-F0-9]{64}", sig),
            400, "invalid_signature_format", "signature phải là chuỗi hex SHA256 dài 64 ký tự.")

    return data
