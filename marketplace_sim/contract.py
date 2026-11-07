"""Bộ kiểm hợp đồng sự kiện tích hợp v2 (retailops-integration-v2)."""

from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any

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

OUTBOUND_EVENT_TYPES = frozenset(
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
ALL_EVENT_TYPES = OUTBOUND_EVENT_TYPES | REQUEST_EVENT_TYPES

ALLOWED_SOURCES_BY_EVENT: dict[str, frozenset[str]] = {
    "product.upserted": frozenset({"marketplace_sim"}),
    "customer.upserted": frozenset({"marketplace_sim"}),
    "order.created": frozenset({"marketplace_sim"}),
    "order.status_changed": frozenset({"marketplace_sim"}),
    "shipment.updated": frozenset({"marketplace_sim"}),
    "payment.updated": frozenset({"payment_sim", "marketplace_sim"}),
    "refund.updated": frozenset({"payment_sim"}),
    "voucher.issued": frozenset({"marketplace_sim"}),
    "voucher.requested": frozenset({"retailops"}),
}

PAYMENT_METHODS = frozenset({"cod", "bank_transfer", "e_wallet", "card"})
ORDER_STATUSES = frozenset(
    {"pending", "confirmed", "shipping", "delivered", "cancelled"}
)
REFUND_CHANNELS = frozenset({"original_method", "bank_transfer", "e_wallet"})
VOUCHER_TYPES = frozenset({"amount", "free_shipping"})
APPROVER_ROLES = frozenset({"staff", "manager"})


class ContractError(ValueError):
    """Lỗi vi phạm hợp đồng sự kiện v2."""


def _is_int(value: Any) -> bool:
    return type(value) is int


def _require_dict_keys(
    obj: Any, expected: frozenset[str], context: str
) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ContractError(f"{context} phải là object JSON.")
    actual = frozenset(obj.keys())
    missing = sorted(expected - actual)
    if missing:
        raise ContractError(f"{context} thiếu trường bắt buộc: {', '.join(missing)}.")
    extra = sorted(actual - expected)
    if extra:
        raise ContractError(f"{context} chứa trường lạ không cho phép: {', '.join(extra)}.")
    return obj


def _require_str(
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
        raise ContractError(f"Trường '{field}' không được là null.")
    if not isinstance(value, str):
        raise ContractError(f"Trường '{field}' phải có kiểu string.")
    if len(value) > max_len:
        raise ContractError(
            f"Trường '{field}' vượt quá độ dài tối đa {max_len} ký tự."
        )
    if non_empty and not value.strip():
        raise ContractError(f"Trường '{field}' không được rỗng.")
    if EMAIL_LIKE_RE.search(value):
        raise ContractError(
            f"Trường '{field}' không được chứa địa chỉ email."
        )
    return value


def _require_enum(value: Any, allowed: frozenset[str], field: str) -> str:
    text = _require_str(value, field)
    assert text is not None
    if text not in allowed:
        raise ContractError(
            f"Trường '{field}' có giá trị '{text}' ngoài tập cho phép {sorted(allowed)}."
        )
    return text


def _require_int(
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
        raise ContractError(f"Trường '{field}' không được là null.")
    if not _is_int(value):
        raise ContractError(f"Trường '{field}' phải là số nguyên (integer).")
    if value < min_value:
        raise ContractError(
            f"Trường '{field}' phải lớn hơn hoặc bằng {min_value}."
        )
    if max_value is not None and value > max_value:
        raise ContractError(
            f"Trường '{field}' không được vượt quá {max_value}."
        )
    return value


def _require_vnd(
    value: Any, field: str, *, nullable: bool = False, min_value: int = 0
) -> int | None:
    return _require_int(
        value,
        field,
        nullable=nullable,
        min_value=min_value,
        max_value=MAX_VND_AMOUNT,
    )


def parse_iso_vn(value: Any, field: str, *, nullable: bool = False) -> datetime | None:
    """Kiểm và phân tích chuỗi thời gian ISO-8601 múi giờ +07:00."""
    if value is None:
        if nullable:
            return None
        raise ContractError(f"Trường '{field}' không được là null.")
    text = _require_str(value, field, max_len=64)
    assert text is not None
    if not ISO_VN_RE.fullmatch(text):
        raise ContractError(
            f"Trường '{field}' phải theo chuẩn ISO-8601 có múi giờ +07:00."
        )
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ContractError(
            f"Trường '{field}' có ngày giờ ISO-8601 không hợp lệ."
        ) from exc
    if dt.tzinfo is None or dt.utcoffset() != VN_OFFSET:
        raise ContractError(f"Trường '{field}' phải có múi giờ +07:00.")
    return dt


def _validate_product_upserted(data: Any) -> None:
    obj = _require_dict_keys(
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
    _require_str(obj["external_product_id"], "data.external_product_id")
    _require_str(obj["title"], "data.title")
    _require_str(obj["category"], "data.category", nullable=True)
    _require_vnd(obj["price"], "data.price", nullable=True)
    _require_str(obj["description"], "data.description", nullable=True)
    _require_str(obj["material"], "data.material", nullable=True)
    _require_str(obj["care"], "data.care", nullable=True)
    _require_int(
        obj["warranty_days"],
        "data.warranty_days",
        nullable=True,
        min_value=0,
        max_value=36500,
    )
    variants = obj["variants"]
    if not isinstance(variants, list):
        raise ContractError("Trường 'data.variants' phải là danh sách (list).")
    seen_skus: set[str] = set()
    variant_keys = frozenset(
        {"sku", "variant_name", "size", "color", "price", "stock"}
    )
    for idx, var in enumerate(variants):
        v = _require_dict_keys(var, variant_keys, f"data.variants[{idx}]")
        sku = _require_str(v["sku"], f"data.variants[{idx}].sku")
        assert sku is not None
        if sku in seen_skus:
            raise ContractError(f"Trùng SKU '{sku}' trong cùng một sản phẩm.")
        seen_skus.add(sku)
        _require_str(v["variant_name"], f"data.variants[{idx}].variant_name")
        _require_str(v["size"], f"data.variants[{idx}].size", nullable=True)
        _require_str(v["color"], f"data.variants[{idx}].color", nullable=True)
        _require_vnd(v["price"], f"data.variants[{idx}].price", nullable=True)
        _require_int(
            v["stock"],
            f"data.variants[{idx}].stock",
            nullable=True,
            min_value=0,
            max_value=10**9,
        )


def _validate_customer_upserted(data: Any) -> None:
    obj = _require_dict_keys(
        data,
        frozenset({"external_customer_id", "display_name"}),
        "data(customer.upserted)",
    )
    _require_str(obj["external_customer_id"], "data.external_customer_id")
    _require_str(obj["display_name"], "data.display_name")


def _validate_order_created(data: Any) -> None:
    obj = _require_dict_keys(
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
    _require_str(obj["external_order_id"], "data.external_order_id")
    _require_str(obj["external_customer_id"], "data.external_customer_id")
    ordered_dt = parse_iso_vn(obj["ordered_at"], "data.ordered_at")
    promised_dt = parse_iso_vn(
        obj["promised_delivery_by"], "data.promised_delivery_by"
    )
    assert ordered_dt is not None and promised_dt is not None
    if promised_dt <= ordered_dt:
        raise ContractError(
            "Trường 'data.promised_delivery_by' phải sau 'data.ordered_at'."
        )

    items = obj["items"]
    if not isinstance(items, list) or not items:
        raise ContractError("Trường 'data.items' phải là danh sách không rỗng.")
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
        item = _require_dict_keys(raw_item, item_keys, f"data.items[{idx}]")
        _require_str(item["sku"], f"data.items[{idx}].sku")
        _require_str(
            item["external_product_id"], f"data.items[{idx}].external_product_id"
        )
        _require_str(item["title"], f"data.items[{idx}].title")
        _require_str(item["variant_name"], f"data.items[{idx}].variant_name")
        qty = _require_int(
            item["quantity"],
            f"data.items[{idx}].quantity",
            min_value=1,
            max_value=10**6,
        )
        unit_price = _require_vnd(
            item["unit_price"], f"data.items[{idx}].unit_price"
        )
        assert qty is not None and unit_price is not None
        items_subtotal += qty * unit_price

    shipping_fee = _require_vnd(obj["shipping_fee"], "data.shipping_fee")
    total = _require_vnd(obj["total"], "data.total")
    assert shipping_fee is not None and total is not None
    if total != items_subtotal + shipping_fee:
        raise ContractError(
            f"Trường 'data.total' ({total}) không bằng tổng dòng hàng ({items_subtotal}) cộng phí ship ({shipping_fee})."
        )

    currency = _require_str(obj["currency"], "data.currency")
    if currency != "VND":
        raise ContractError("Trường 'data.currency' phải bằng 'VND'.")
    _require_enum(obj["payment_method"], PAYMENT_METHODS, "data.payment_method")

    rec = _require_dict_keys(
        obj["recipient"],
        frozenset(
            {"name", "phone", "address_line", "ward", "district", "province"}
        ),
        "data.recipient",
    )
    _require_str(rec["name"], "data.recipient.name")
    phone = _require_str(rec["phone"], "data.recipient.phone")
    assert phone is not None
    if not RECIPIENT_PHONE_RE.fullmatch(phone):
        raise ContractError(
            "Trường 'data.recipient.phone' phải gồm đúng 10 chữ số bắt đầu bằng 0."
        )
    _require_str(rec["address_line"], "data.recipient.address_line")
    _require_str(rec["ward"], "data.recipient.ward")
    _require_str(rec["district"], "data.recipient.district")
    _require_str(rec["province"], "data.recipient.province")


def _validate_order_status_changed(data: Any) -> None:
    obj = _require_dict_keys(
        data,
        frozenset({"external_order_id", "status", "reason"}),
        "data(order.status_changed)",
    )
    _require_str(obj["external_order_id"], "data.external_order_id")
    _require_enum(obj["status"], ORDER_STATUSES, "data.status")
    _require_str(obj["reason"], "data.reason", nullable=True)


def _validate_shipment_updated(data: Any) -> None:
    obj = _require_dict_keys(
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
    _require_str(obj["external_shipment_id"], "data.external_shipment_id")
    _require_str(obj["external_order_id"], "data.external_order_id")
    _require_str(obj["carrier"], "data.carrier")
    _require_str(obj["tracking_code"], "data.tracking_code")
    _require_str(obj["carrier_status_raw"], "data.carrier_status_raw")
    _require_str(obj["hub_name"], "data.hub_name", nullable=True)
    _require_str(obj["district"], "data.district")
    _require_str(obj["province"], "data.province")
    _require_str(obj["description"], "data.description")
    _require_str(obj["fail_reason"], "data.fail_reason", nullable=True)
    _require_str(obj["shipper_name"], "data.shipper_name", nullable=True)
    masked_phone = _require_str(
        obj["shipper_phone_masked"], "data.shipper_phone_masked", nullable=True
    )
    if masked_phone is not None:
        digits_only = re.sub(r"\D", "", masked_phone)
        if len(digits_only) >= 10 or not MASKED_SHIPPER_PHONE_RE.fullmatch(masked_phone):
            raise ContractError(
                "Trường 'data.shipper_phone_masked' phải ở dạng đã che (ví dụ 0901.xxx.234)."
            )
    parse_iso_vn(
        obj["estimated_delivery_at"], "data.estimated_delivery_at", nullable=True
    )
    _require_int(
        obj["delivery_attempts"],
        "data.delivery_attempts",
        min_value=0,
        max_value=3,
    )


def _validate_payment_updated(data: Any, source_system: str) -> None:
    obj = _require_dict_keys(
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
    _require_str(obj["provider"], "data.provider")
    _require_str(obj["provider_txn_ref"], "data.provider_txn_ref")
    _require_str(obj["external_order_id"], "data.external_order_id")
    method = _require_enum(obj["method"], PAYMENT_METHODS, "data.method")
    if source_system == "marketplace_sim" and method != "cod":
        raise ContractError(
            "Sự kiện payment.updated từ 'marketplace_sim' chỉ áp dụng cho phương thức 'cod'."
        )
    if source_system == "payment_sim" and method == "cod":
        raise ContractError(
            "Sự kiện payment.updated từ 'payment_sim' chỉ áp dụng cho đơn trả trước, không dùng cho 'cod'."
        )
    _require_vnd(obj["amount"], "data.amount")
    _require_str(obj["provider_status_raw"], "data.provider_status_raw")
    parse_iso_vn(obj["settled_at"], "data.settled_at", nullable=True)


def _validate_refund_updated(data: Any) -> None:
    obj = _require_dict_keys(
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
    _require_str(obj["provider"], "data.provider")
    _require_str(obj["provider_refund_ref"], "data.provider_refund_ref")
    _require_str(obj["provider_txn_ref"], "data.provider_txn_ref", nullable=True)
    _require_str(obj["external_order_id"], "data.external_order_id")
    _require_vnd(obj["amount"], "data.amount", min_value=1)
    _require_enum(obj["channel"], REFUND_CHANNELS, "data.channel")
    _require_str(
        obj["provider_status_raw"], "data.provider_status_raw", nullable=True
    )
    _require_str(obj["failure_reason"], "data.failure_reason", nullable=True)
    initiated_dt = parse_iso_vn(
        obj["initiated_at"], "data.initiated_at", nullable=True
    )
    completed_dt = parse_iso_vn(
        obj["completed_at"], "data.completed_at", nullable=True
    )
    if completed_dt is not None and initiated_dt is not None and completed_dt < initiated_dt:
        raise ContractError(
            "Trường 'data.completed_at' không được trước 'data.initiated_at'."
        )


def _validate_voucher_value(voucher_type: str, value: int, field_prefix: str) -> None:
    if voucher_type == "free_shipping" and value != 0:
        raise ContractError(
            f"Trường '{field_prefix}.value' phải bằng 0 khi voucher_type là 'free_shipping'."
        )
    if voucher_type == "amount" and value <= 0:
        raise ContractError(
            f"Trường '{field_prefix}.value' phải lớn hơn 0 khi voucher_type là 'amount'."
        )


def _validate_voucher_issued(data: Any) -> None:
    obj = _require_dict_keys(
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
    _require_str(obj["external_voucher_id"], "data.external_voucher_id")
    _require_str(obj["code"], "data.code")
    vtype = _require_enum(obj["voucher_type"], VOUCHER_TYPES, "data.voucher_type")
    val = _require_vnd(obj["value"], "data.value")
    assert val is not None
    _validate_voucher_value(vtype, val, "data")
    parse_iso_vn(obj["valid_until"], "data.valid_until", nullable=True)
    _require_str(
        obj["external_order_id"], "data.external_order_id", nullable=True
    )
    _require_str(
        obj["external_customer_id"], "data.external_customer_id", nullable=True
    )
    _require_str(obj["request_ref"], "data.request_ref", nullable=True)


def _validate_voucher_requested(data: Any) -> None:
    obj = _require_dict_keys(
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
    _require_str(obj["request_id"], "data.request_id")
    _require_str(obj["external_order_id"], "data.external_order_id")
    _require_str(obj["external_customer_id"], "data.external_customer_id")
    vtype = _require_enum(obj["voucher_type"], VOUCHER_TYPES, "data.voucher_type")
    val = _require_vnd(obj["value"], "data.value")
    assert val is not None
    _validate_voucher_value(vtype, val, "data")
    reason = _require_str(obj["reason"], "data.reason")
    if reason != "late_delivery":
        raise ContractError(
            "Trường 'data.reason' của voucher.requested phải là 'late_delivery'."
        )
    _require_enum(
        obj["approved_by_role"], APPROVER_ROLES, "data.approved_by_role"
    )


def validate_event(
    event: Any, *, allow_requests: bool = True
) -> dict[str, Any]:
    """Kiểm tra một phong bì sự kiện theo hợp đồng retailops-integration-v2.

    Trả về chính dict sự kiện nếu hợp lệ; ném ``ContractError`` nếu vi phạm.
    """
    env = _require_dict_keys(event, ENVELOPE_KEYS, "envelope")

    contract = _require_str(env["contract"], "contract")
    if contract != CONTRACT_VERSION:
        raise ContractError(
            f"Trường 'contract' phải là '{CONTRACT_VERSION}', nhận '{contract}'."
        )

    event_id = _require_str(env["event_id"], "event_id", max_len=128)
    assert event_id is not None
    if not EVENT_ID_RE.fullmatch(event_id):
        raise ContractError(
            "Trường 'event_id' không khớp mẫu [A-Za-z0-9._:-]{8,128}."
        )

    allowed_types = ALL_EVENT_TYPES if allow_requests else OUTBOUND_EVENT_TYPES
    event_type = _require_enum(env["event_type"], allowed_types, "event_type")

    allowed_sources = ALLOWED_SOURCES_BY_EVENT[event_type]
    source_system = _require_enum(
        env["source_system"], allowed_sources, "source_system"
    )

    _require_str(env["merchant_id"], "merchant_id")
    parse_iso_vn(env["occurred_at"], "occurred_at")
    _require_int(env["sequence"], "sequence", min_value=1, max_value=10**9)

    data = env["data"]
    if event_type == "product.upserted":
        _validate_product_upserted(data)
    elif event_type == "customer.upserted":
        _validate_customer_upserted(data)
    elif event_type == "order.created":
        _validate_order_created(data)
    elif event_type == "order.status_changed":
        _validate_order_status_changed(data)
    elif event_type == "shipment.updated":
        _validate_shipment_updated(data)
    elif event_type == "payment.updated":
        _validate_payment_updated(data, source_system)
    elif event_type == "refund.updated":
        _validate_refund_updated(data)
    elif event_type == "voucher.issued":
        _validate_voucher_issued(data)
    elif event_type == "voucher.requested":
        _validate_voucher_requested(data)
    else:  # pragma: no cover
        raise ContractError(f"Loại sự kiện không được hỗ trợ: {event_type}.")

    return env
