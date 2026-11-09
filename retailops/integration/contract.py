"""RetailOps v2 integration event contract validator (W6.1b-D3).

Validates the ``retailops-integration-v2`` envelope and per-event ``data`` payloads
defined in Section 3 of the W6.1a handoff. Standalone RetailOps implementation —
never imports ``marketplace_sim``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any

from retailops.core import ApiError

CONTRACT_VERSION = "retailops-integration-v2"
MAX_VND_AMOUNT = 10**12
MAX_TEXT_LENGTH = 500
VN_OFFSET = timedelta(hours=7)

EVENT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
ISO_VN_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+07:00$"
)
RECIPIENT_PHONE_RE = re.compile(r"^0\d{9}$")
MASKED_SHIPPER_PHONE_RE = re.compile(r"^0\d{1,3}[.*xX-]{2,8}\d{2,4}$")
EMAIL_LIKE_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

ENVELOPE_KEYS = frozenset(
    {
        "contract",
        "event_id",
        "event_type",
        "source_system",
        "merchant_id",
        "occurred_at",
        "sequence",
        "data",
    }
)

INBOUND_EVENT_TYPES = frozenset(
    {
        "product.upserted",
        "customer.upserted",
        "order.created",
        "order.status_changed",
        "shipment.updated",
        "payment.updated",
        "refund.updated",
        "voucher.issued",
    }
)

REQUEST_EVENT_TYPES = frozenset({"voucher.requested"})
ALL_EVENT_TYPES = INBOUND_EVENT_TYPES | REQUEST_EVENT_TYPES
W6_1B_1_SUPPORTED_EVENT_TYPES = INBOUND_EVENT_TYPES

PAYMENT_METHODS = frozenset({"cod", "bank_transfer", "e_wallet", "card"})
ORDER_EVENT_STATUSES = frozenset(
    {"pending", "confirmed", "shipping", "delivered", "cancelled"}
)
REFUND_CHANNELS = frozenset({"original_method", "bank_transfer", "e_wallet"})
VOUCHER_TYPES = frozenset({"amount", "free_shipping"})
APPROVER_ROLES = frozenset({"staff", "manager"})


class ContractValidationError(ApiError):
    """Raised when an integration event violates retailops-integration-v2."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(422, code, message)


def _is_strict_int(value: Any) -> bool:
    return type(value) is int


def _require_object_keys(
    obj: Any, expected: frozenset[str], context: str
) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ContractValidationError(
            "invalid_event_object", f"{context} phải là object JSON."
        )
    actual = frozenset(obj.keys())
    missing = sorted(expected - actual)
    if missing:
        raise ContractValidationError(
            "missing_event_field",
            f"{context} thiếu trường bắt buộc: {', '.join(missing)}.",
        )
    extra = sorted(actual - expected)
    if extra:
        raise ContractValidationError(
            "unexpected_event_field",
            f"{context} chứa trường lạ không cho phép: {', '.join(extra)}.",
        )
    return obj


def _require_text(
    value: Any,
    field: str,
    *,
    nullable: bool = False,
    non_empty: bool = True,
    max_len: int = MAX_TEXT_LENGTH,
) -> str | None:
    if value is None:
        if nullable:
            return None
        raise ContractValidationError(
            "invalid_event_field", f"Trường '{field}' không được là null."
        )
    if not isinstance(value, str):
        raise ContractValidationError(
            "invalid_event_field", f"Trường '{field}' phải có kiểu string."
        )
    if len(value) > max_len:
        raise ContractValidationError(
            "invalid_event_field",
            f"Trường '{field}' vượt quá độ dài tối đa {max_len} ký tự.",
        )
    if non_empty and not value.strip():
        raise ContractValidationError(
            "invalid_event_field", f"Trường '{field}' không được rỗng."
        )
    if EMAIL_LIKE_RE.search(value):
        raise ContractValidationError(
            "email_prohibited_in_event",
            f"Trường '{field}' không được chứa địa chỉ email.",
        )
    return value


def _require_enum_str(
    value: Any, allowed: frozenset[str], field: str, *, code: str = "invalid_event_field"
) -> str:
    text = _require_text(value, field)
    assert text is not None
    if text not in allowed:
        raise ContractValidationError(
            code,
            f"Trường '{field}' có giá trị '{text}' ngoài tập cho phép {sorted(allowed)}.",
        )
    return text


def _require_strict_int(
    value: Any,
    field: str,
    *,
    nullable: bool = False,
    min_value: int = 0,
    max_value: int | None = None,
) -> int | None:
    if value is None:
        if nullable:
            return None
        raise ContractValidationError(
            "invalid_event_field", f"Trường '{field}' không được là null."
        )
    if not _is_strict_int(value):
        raise ContractValidationError(
            "invalid_event_field", f"Trường '{field}' phải là số nguyên (integer)."
        )
    if value < min_value:
        raise ContractValidationError(
            "invalid_event_field",
            f"Trường '{field}' phải lớn hơn hoặc bằng {min_value}.",
        )
    if max_value is not None and value > max_value:
        raise ContractValidationError(
            "invalid_event_field",
            f"Trường '{field}' không được vượt quá {max_value}.",
        )
    return value


def _require_vnd_amount(
    value: Any, field: str, *, nullable: bool = False, min_value: int = 0
) -> int | None:
    return _require_strict_int(
        value,
        field,
        nullable=nullable,
        min_value=min_value,
        max_value=MAX_VND_AMOUNT,
    )


def parse_iso_vn_timestamp(
    value: Any, field: str, *, nullable: bool = False
) -> datetime | None:
    """Validate and parse an ISO-8601 timestamp string carrying explicit +07:00 offset."""
    if value is None:
        if nullable:
            return None
        raise ContractValidationError(
            "invalid_timestamp", f"Trường '{field}' không được là null."
        )
    text = _require_text(value, field, max_len=64)
    assert text is not None
    if not ISO_VN_RE.fullmatch(text):
        raise ContractValidationError(
            "invalid_timestamp",
            f"Trường '{field}' phải theo chuẩn ISO-8601 có múi giờ +07:00.",
        )
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ContractValidationError(
            "invalid_timestamp",
            f"Trường '{field}' có ngày giờ ISO-8601 không hợp lệ.",
        ) from exc
    if dt.tzinfo is None or dt.utcoffset() != VN_OFFSET:
        raise ContractValidationError(
            "invalid_timestamp", f"Trường '{field}' phải có múi giờ +07:00."
        )
    return dt


def iso_vn_to_epoch(
    value: Any, field: str, *, nullable: bool = False
) -> float | None:
    dt = parse_iso_vn_timestamp(value, field, nullable=nullable)
    return float(dt.timestamp()) if dt is not None else None


def _validate_product_upserted_data(data: Any) -> None:
    obj = _require_object_keys(
        data,
        frozenset(
            {
                "external_product_id",
                "title",
                "category",
                "price",
                "description",
                "material",
                "care",
                "warranty_days",
                "variants",
            }
        ),
        "data(product.upserted)",
    )
    _require_text(obj["external_product_id"], "data.external_product_id")
    _require_text(obj["title"], "data.title")
    _require_text(obj["category"], "data.category", nullable=True)
    _require_vnd_amount(obj["price"], "data.price", nullable=True)
    _require_text(obj["description"], "data.description", nullable=True)
    _require_text(obj["material"], "data.material", nullable=True)
    _require_text(obj["care"], "data.care", nullable=True)
    _require_strict_int(
        obj["warranty_days"],
        "data.warranty_days",
        nullable=True,
        min_value=0,
        max_value=36500,
    )
    variants = obj["variants"]
    if not isinstance(variants, list):
        raise ContractValidationError(
            "invalid_event_field", "Trường 'data.variants' phải là danh sách."
        )
    seen_skus: set[str] = set()
    variant_keys = frozenset(
        {"sku", "variant_name", "size", "color", "price", "stock"}
    )
    for idx, raw_var in enumerate(variants):
        var = _require_object_keys(raw_var, variant_keys, f"data.variants[{idx}]")
        sku = _require_text(var["sku"], f"data.variants[{idx}].sku")
        assert sku is not None
        if sku in seen_skus:
            raise ContractValidationError(
                "duplicate_variant_sku",
                f"Trùng SKU '{sku}' trong cùng sự kiện product.upserted.",
            )
        seen_skus.add(sku)
        _require_text(var["variant_name"], f"data.variants[{idx}].variant_name")
        _require_text(var["size"], f"data.variants[{idx}].size", nullable=True)
        _require_text(var["color"], f"data.variants[{idx}].color", nullable=True)
        _require_vnd_amount(var["price"], f"data.variants[{idx}].price", nullable=True)
        _require_strict_int(
            var["stock"],
            f"data.variants[{idx}].stock",
            nullable=True,
            min_value=0,
            max_value=10**9,
        )


def _validate_customer_upserted_data(data: Any) -> None:
    obj = _require_object_keys(
        data,
        frozenset({"external_customer_id", "display_name"}),
        "data(customer.upserted)",
    )
    _require_text(obj["external_customer_id"], "data.external_customer_id")
    _require_text(obj["display_name"], "data.display_name")


def _validate_order_created_data(data: Any) -> None:
    obj = _require_object_keys(
        data,
        frozenset(
            {
                "external_order_id",
                "external_customer_id",
                "ordered_at",
                "items",
                "shipping_fee",
                "total",
                "currency",
                "payment_method",
                "promised_delivery_by",
                "recipient",
            }
        ),
        "data(order.created)",
    )
    _require_text(obj["external_order_id"], "data.external_order_id")
    _require_text(obj["external_customer_id"], "data.external_customer_id")
    ordered_dt = parse_iso_vn_timestamp(obj["ordered_at"], "data.ordered_at")
    promised_dt = parse_iso_vn_timestamp(
        obj["promised_delivery_by"], "data.promised_delivery_by"
    )
    assert ordered_dt is not None and promised_dt is not None
    if promised_dt <= ordered_dt:
        raise ContractValidationError(
            "invalid_promised_delivery_by",
            "Trường 'data.promised_delivery_by' phải sau 'data.ordered_at'.",
        )

    items = obj["items"]
    if not isinstance(items, list) or not items:
        raise ContractValidationError(
            "invalid_items", "Trường 'data.items' phải là danh sách không rỗng."
        )
    item_keys = frozenset(
        {
            "sku",
            "external_product_id",
            "title",
            "variant_name",
            "quantity",
            "unit_price",
        }
    )
    items_subtotal = 0
    for idx, raw_item in enumerate(items):
        item = _require_object_keys(raw_item, item_keys, f"data.items[{idx}]")
        _require_text(item["sku"], f"data.items[{idx}].sku")
        _require_text(
            item["external_product_id"], f"data.items[{idx}].external_product_id"
        )
        _require_text(item["title"], f"data.items[{idx}].title")
        _require_text(item["variant_name"], f"data.items[{idx}].variant_name")
        qty = _require_strict_int(
            item["quantity"],
            f"data.items[{idx}].quantity",
            min_value=1,
            max_value=10**6,
        )
        unit_price = _require_vnd_amount(
            item["unit_price"], f"data.items[{idx}].unit_price"
        )
        assert qty is not None and unit_price is not None
        items_subtotal += qty * unit_price

    shipping_fee = _require_vnd_amount(obj["shipping_fee"], "data.shipping_fee")
    total = _require_vnd_amount(obj["total"], "data.total")
    assert shipping_fee is not None and total is not None
    if total != items_subtotal + shipping_fee:
        raise ContractValidationError(
            "total_mismatch",
            f"Trường 'data.total' ({total}) không bằng tổng dòng hàng ({items_subtotal}) cộng phí ship ({shipping_fee}).",
        )

    currency = _require_text(obj["currency"], "data.currency")
    if currency != "VND":
        raise ContractValidationError(
            "invalid_currency", "Trường 'data.currency' phải bằng 'VND'."
        )
    _require_enum_str(obj["payment_method"], PAYMENT_METHODS, "data.payment_method")

    rec = _require_object_keys(
        obj["recipient"],
        frozenset(
            {"name", "phone", "address_line", "ward", "district", "province"}
        ),
        "data.recipient",
    )
    _require_text(rec["name"], "data.recipient.name")
    phone = _require_text(rec["phone"], "data.recipient.phone")
    assert phone is not None
    if not RECIPIENT_PHONE_RE.fullmatch(phone):
        raise ContractValidationError(
            "invalid_recipient_phone",
            "Trường 'data.recipient.phone' phải gồm đúng 10 chữ số bắt đầu bằng 0.",
        )
    _require_text(rec["address_line"], "data.recipient.address_line")
    _require_text(rec["ward"], "data.recipient.ward")
    _require_text(rec["district"], "data.recipient.district")
    _require_text(rec["province"], "data.recipient.province")


def _validate_order_status_changed_data(data: Any) -> None:
    obj = _require_object_keys(
        data,
        frozenset({"external_order_id", "status", "reason"}),
        "data(order.status_changed)",
    )
    _require_text(obj["external_order_id"], "data.external_order_id")
    _require_enum_str(obj["status"], ORDER_EVENT_STATUSES, "data.status")
    _require_text(obj["reason"], "data.reason", nullable=True)


def _validate_shipment_updated_data(data: Any) -> None:
    obj = _require_object_keys(
        data,
        frozenset(
            {
                "external_shipment_id",
                "external_order_id",
                "carrier",
                "tracking_code",
                "carrier_status_raw",
                "hub_name",
                "district",
                "province",
                "description",
                "fail_reason",
                "shipper_name",
                "shipper_phone_masked",
                "estimated_delivery_at",
                "delivery_attempts",
            }
        ),
        "data(shipment.updated)",
    )
    _require_text(obj["external_shipment_id"], "data.external_shipment_id")
    _require_text(obj["external_order_id"], "data.external_order_id")
    _require_text(obj["carrier"], "data.carrier")
    _require_text(obj["tracking_code"], "data.tracking_code")
    _require_text(obj["carrier_status_raw"], "data.carrier_status_raw")
    _require_text(obj["hub_name"], "data.hub_name", nullable=True)
    _require_text(obj["district"], "data.district")
    _require_text(obj["province"], "data.province")
    _require_text(obj["description"], "data.description")
    _require_text(obj["fail_reason"], "data.fail_reason", nullable=True)
    _require_text(obj["shipper_name"], "data.shipper_name", nullable=True)
    masked = _require_text(
        obj["shipper_phone_masked"], "data.shipper_phone_masked", nullable=True
    )
    if masked is not None:
        digits_only = re.sub(r"\D", "", masked)
        if len(digits_only) >= 10 or not MASKED_SHIPPER_PHONE_RE.fullmatch(masked):
            raise ContractValidationError(
                "invalid_shipper_phone_masked",
                "Trường 'data.shipper_phone_masked' phải ở dạng đã che (ví dụ 0901.xxx.234).",
            )
    parse_iso_vn_timestamp(
        obj["estimated_delivery_at"], "data.estimated_delivery_at", nullable=True
    )
    _require_strict_int(
        obj["delivery_attempts"],
        "data.delivery_attempts",
        min_value=0,
        max_value=3,
    )


def _validate_payment_updated_data(
    data: Any, source_system: str, marketplace_sources: frozenset[str]
) -> None:
    obj = _require_object_keys(
        data,
        frozenset(
            {
                "provider",
                "provider_txn_ref",
                "external_order_id",
                "method",
                "amount",
                "provider_status_raw",
                "settled_at",
            }
        ),
        "data(payment.updated)",
    )
    _require_text(obj["provider"], "data.provider")
    _require_text(obj["provider_txn_ref"], "data.provider_txn_ref")
    _require_text(obj["external_order_id"], "data.external_order_id")
    method = _require_enum_str(obj["method"], PAYMENT_METHODS, "data.method")
    if source_system == "payment_sim" and method == "cod":
        raise ContractValidationError(
            "invalid_payment_source_method",
            "Sự kiện payment.updated từ 'payment_sim' chỉ áp dụng cho đơn trả trước, không dùng cho 'cod'.",
        )
    if source_system in marketplace_sources and source_system != "payment_sim" and method != "cod":
        raise ContractValidationError(
            "invalid_payment_source_method",
            f"Sự kiện payment.updated từ '{source_system}' chỉ áp dụng cho phương thức 'cod'.",
        )
    _require_vnd_amount(obj["amount"], "data.amount")
    _require_text(obj["provider_status_raw"], "data.provider_status_raw")
    parse_iso_vn_timestamp(obj["settled_at"], "data.settled_at", nullable=True)


def _validate_refund_updated_data(data: Any) -> None:
    obj = _require_object_keys(
        data,
        frozenset(
            {
                "provider",
                "provider_refund_ref",
                "provider_txn_ref",
                "external_order_id",
                "amount",
                "channel",
                "provider_status_raw",
                "failure_reason",
                "initiated_at",
                "completed_at",
            }
        ),
        "data(refund.updated)",
    )
    _require_text(obj["provider"], "data.provider")
    _require_text(obj["provider_refund_ref"], "data.provider_refund_ref")
    _require_text(obj["provider_txn_ref"], "data.provider_txn_ref", nullable=True)
    _require_text(obj["external_order_id"], "data.external_order_id")
    _require_vnd_amount(obj["amount"], "data.amount", min_value=1)
    _require_enum_str(obj["channel"], REFUND_CHANNELS, "data.channel")
    _require_text(
        obj["provider_status_raw"], "data.provider_status_raw", nullable=True
    )
    _require_text(obj["failure_reason"], "data.failure_reason", nullable=True)
    initiated_dt = parse_iso_vn_timestamp(
        obj["initiated_at"], "data.initiated_at", nullable=True
    )
    completed_dt = parse_iso_vn_timestamp(
        obj["completed_at"], "data.completed_at", nullable=True
    )
    if completed_dt is not None and initiated_dt is not None and completed_dt < initiated_dt:
        raise ContractValidationError(
            "invalid_refund_timestamps",
            "Trường 'data.completed_at' không được trước 'data.initiated_at'.",
        )


def _validate_voucher_value_rule(voucher_type: str, value: int) -> None:
    if voucher_type == "free_shipping" and value != 0:
        raise ContractValidationError(
            "invalid_voucher_value",
            "Trường 'data.value' phải bằng 0 khi voucher_type là 'free_shipping'.",
        )
    if voucher_type == "amount" and value <= 0:
        raise ContractValidationError(
            "invalid_voucher_value",
            "Trường 'data.value' phải lớn hơn 0 khi voucher_type là 'amount'.",
        )


def _validate_voucher_issued_data(data: Any) -> None:
    obj = _require_object_keys(
        data,
        frozenset(
            {
                "external_voucher_id",
                "code",
                "voucher_type",
                "value",
                "valid_until",
                "external_order_id",
                "external_customer_id",
                "request_ref",
            }
        ),
        "data(voucher.issued)",
    )
    _require_text(obj["external_voucher_id"], "data.external_voucher_id")
    _require_text(obj["code"], "data.code")
    vtype = _require_enum_str(obj["voucher_type"], VOUCHER_TYPES, "data.voucher_type")
    val = _require_vnd_amount(obj["value"], "data.value")
    assert val is not None
    _validate_voucher_value_rule(vtype, val)
    parse_iso_vn_timestamp(obj["valid_until"], "data.valid_until", nullable=True)
    _require_text(
        obj["external_order_id"], "data.external_order_id", nullable=True
    )
    _require_text(
        obj["external_customer_id"], "data.external_customer_id", nullable=True
    )
    _require_text(obj["request_ref"], "data.request_ref", nullable=True)


def _validate_voucher_requested_data(data: Any) -> None:
    obj = _require_object_keys(
        data,
        frozenset(
            {
                "request_id",
                "external_order_id",
                "external_customer_id",
                "voucher_type",
                "value",
                "reason",
                "approved_by_role",
            }
        ),
        "data(voucher.requested)",
    )
    _require_text(obj["request_id"], "data.request_id")
    _require_text(obj["external_order_id"], "data.external_order_id")
    _require_text(obj["external_customer_id"], "data.external_customer_id")
    vtype = _require_enum_str(obj["voucher_type"], VOUCHER_TYPES, "data.voucher_type")
    val = _require_vnd_amount(obj["value"], "data.value")
    assert val is not None
    _validate_voucher_value_rule(vtype, val)
    reason = _require_text(obj["reason"], "data.reason")
    if reason != "late_delivery":
        raise ContractValidationError(
            "invalid_voucher_reason",
            "Trường 'data.reason' của voucher.requested phải là 'late_delivery'.",
        )
    _require_enum_str(
        obj["approved_by_role"], APPROVER_ROLES, "data.approved_by_role"
    )


def validate_event_v2(
    event: Any,
    *,
    allow_requests: bool = True,
    allowed_marketplace_sources: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Validate an event envelope and data payload against retailops-integration-v2.

    Returns the validated ``event`` dict if valid; raises ``ContractValidationError``
    (HTTP 422 ``ApiError``) otherwise.
    """
    env = _require_object_keys(event, ENVELOPE_KEYS, "envelope")

    contract = _require_text(env["contract"], "contract")
    if contract != CONTRACT_VERSION:
        raise ContractValidationError(
            "invalid_contract_version",
            f"Trường 'contract' phải là '{CONTRACT_VERSION}', nhận '{contract}'.",
        )

    event_id = _require_text(env["event_id"], "event_id", max_len=128)
    assert event_id is not None
    if not EVENT_ID_RE.fullmatch(event_id):
        raise ContractValidationError(
            "invalid_event_id",
            "Trường 'event_id' không khớp mẫu [A-Za-z0-9._:-]{8,128}.",
        )

    allowed_types = ALL_EVENT_TYPES if allow_requests else INBOUND_EVENT_TYPES
    event_type = _require_enum_str(
        env["event_type"], allowed_types, "event_type", code="invalid_event_type"
    )

    mkt_sources = (
        frozenset({"marketplace_sim"})
        if allowed_marketplace_sources is None
        else frozenset(allowed_marketplace_sources)
    )
    if event_type in {
        "product.upserted",
        "customer.upserted",
        "order.created",
        "order.status_changed",
        "shipment.updated",
        "voucher.issued",
    }:
        allowed_sources = mkt_sources
    elif event_type == "payment.updated":
        allowed_sources = mkt_sources | frozenset({"payment_sim"})
    elif event_type == "refund.updated":
        allowed_sources = frozenset({"payment_sim"})
    elif event_type == "voucher.requested":
        allowed_sources = frozenset({"retailops"})
    else:  # pragma: no cover
        raise ContractValidationError(
            "invalid_event_type", f"Loại sự kiện không hợp lệ: '{event_type}'."
        )

    source_system = _require_enum_str(
        env["source_system"],
        allowed_sources,
        "source_system",
        code="invalid_source_system",
    )

    _require_text(env["merchant_id"], "merchant_id")
    parse_iso_vn_timestamp(env["occurred_at"], "occurred_at")
    _require_strict_int(env["sequence"], "sequence", min_value=1, max_value=10**9)

    data = env["data"]
    if event_type == "product.upserted":
        _validate_product_upserted_data(data)
    elif event_type == "customer.upserted":
        _validate_customer_upserted_data(data)
    elif event_type == "order.created":
        _validate_order_created_data(data)
    elif event_type == "order.status_changed":
        _validate_order_status_changed_data(data)
    elif event_type == "shipment.updated":
        _validate_shipment_updated_data(data)
    elif event_type == "payment.updated":
        _validate_payment_updated_data(data, source_system, mkt_sources)
    elif event_type == "refund.updated":
        _validate_refund_updated_data(data)
    elif event_type == "voucher.issued":
        _validate_voucher_issued_data(data)
    elif event_type == "voucher.requested":
        _validate_voucher_requested_data(data)

    return env


def ensure_w6_1b_1_supported_event(event_type: str) -> None:
    """Verify inbound event_type is in the canonical supported v2 inbound set (W6.1b-1 + W6.1b-2)."""
    if event_type not in W6_1B_1_SUPPORTED_EVENT_TYPES:
        raise ApiError(
            422,
            "unsupported_event_type",
            f"Loại sự kiện '{event_type}' không được cổng nhận hỗ trợ.",
        )
