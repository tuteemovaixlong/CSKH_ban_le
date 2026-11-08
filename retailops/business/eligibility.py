"""Server-side read-time business eligibility computation (Phase R1 W6.1b-1, W6.1b-D9).

All eligibility flags and temporal offsets are computed dynamically at read time from
canonical database columns (`orders`, `products`, `shipments`, `shipment_events`) and
current policy configuration (`RETURN_WINDOW_DAYS`, `SIZE_EXCHANGE_WINDOW_DAYS`,
`DEFAULT_WARRANTY_DAYS` + `products.warranty_days` override), always accompanied by `as_of`.
Nothing in this module is pre-computed or persisted to database tables.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import time
from typing import Any, Mapping

from retailops.business.warranty import resolve_warranty_period

VN_TZ = timezone(timedelta(hours=7))

# Authoritative store policy windows (grounded in data/knowledge/*.md):
# - data/knowledge/returns.md: 7 days from delivery
# - data/knowledge/policy_size_exchange_twoway.md: 15 days from delivery
# - data/knowledge/policy_warranty_exchange_1to1.md: 90 days default (overridden by products.warranty_days)
RETURN_WINDOW_DAYS = 7
SIZE_EXCHANGE_WINDOW_DAYS = 15
DEFAULT_WARRANTY_DAYS = 90
SECONDS_PER_DAY = 86400.0
SECONDS_PER_HOUR = 3600.0


def _finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return num


def format_vn_iso(epoch_seconds: Any) -> str | None:
    """Format epoch seconds as ISO-8601 in Asia/Ho_Chi_Minh (+07:00), or None."""
    ts = _finite_float(epoch_seconds)
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=VN_TZ).isoformat(timespec="seconds")


def resolve_effective_warranty(
    product: Mapping[str, Any] | None,
    *,
    general_policy_days: int = DEFAULT_WARRANTY_DAYS,
) -> dict[str, Any]:
    """Resolve effective warranty window days from product override or general policy."""
    if isinstance(product, Mapping) and "warranty_days" in product:
        raw_w = product.get("warranty_days")
        if isinstance(raw_w, int) and not isinstance(raw_w, bool) and raw_w == 0:
            return {
                "source": "product_override",
                "warranty_window_days": 0,
                "has_override": True,
            }
    rule = resolve_warranty_period(dict(product) if isinstance(product, Mapping) else None, general_policy_days=general_policy_days)
    return {
        "source": str(rule["source"]),
        "warranty_window_days": int(rule["warranty_days"]),
        "has_override": bool(rule["has_override"]),
    }


def compute_order_eligibility(
    order: Mapping[str, Any],
    *,
    product: Mapping[str, Any] | None = None,
    shipment: Mapping[str, Any] | None = None,
    latest_event_estimated_delivery_at: Any = None,
    as_of: float | int | None = None,
) -> dict[str, Any]:
    """Compute read-time order eligibility and SLA lateness metrics as of `as_of`."""
    as_of_ts = _finite_float(as_of)
    if as_of_ts is None:
        as_of_ts = float(time.time())
    as_of_iso = format_vn_iso(as_of_ts)
    assert as_of_iso is not None

    status = str(order.get("status") or "").strip().lower()
    can_self_service_cancel = status == "pending"
    if can_self_service_cancel:
        cancel_ineligible_code = None
    elif status == "shipping":
        cancel_ineligible_code = "order_already_shipping"
    elif status == "delivered":
        cancel_ineligible_code = "order_already_delivered"
    elif status == "cancelled":
        cancel_ineligible_code = "order_already_cancelled"
    else:
        cancel_ineligible_code = "order_not_pending"

    can_open_return_or_exchange = status == "delivered"

    delivered_ts = _finite_float(order.get("delivered_at"))
    warranty_info = resolve_effective_warranty(product)
    warranty_window_days = int(warranty_info["warranty_window_days"])

    days_since_delivery: float | None
    within_return_window: bool | None
    within_size_exchange_window: bool | None
    within_warranty: bool | None

    if status == "delivered":
        if delivered_ts is None:
            days_since_delivery = None
            within_return_window = None
            within_size_exchange_window = None
            within_warranty = None
        else:
            elapsed_sec = as_of_ts - delivered_ts
            days_since_delivery = round(elapsed_sec / SECONDS_PER_DAY, 4)
            within_return_window = bool(0.0 <= elapsed_sec <= RETURN_WINDOW_DAYS * SECONDS_PER_DAY)
            within_size_exchange_window = bool(0.0 <= elapsed_sec <= SIZE_EXCHANGE_WINDOW_DAYS * SECONDS_PER_DAY)
            within_warranty = bool(
                warranty_window_days > 0
                and 0.0 <= elapsed_sec <= warranty_window_days * SECONDS_PER_DAY
            )
    else:
        days_since_delivery = (
            round((as_of_ts - delivered_ts) / SECONDS_PER_DAY, 4)
            if delivered_ts is not None
            else None
        )
        within_return_window = False
        within_size_exchange_window = False
        within_warranty = False

    est_ts = None
    if isinstance(shipment, Mapping):
        est_ts = _finite_float(shipment.get("estimated_delivery_at"))
    if est_ts is None:
        est_ts = _finite_float(latest_event_estimated_delivery_at)
    latest_estimated_delivery_at = format_vn_iso(est_ts)

    promised_ts = _finite_float(order.get("promised_delivery_by"))
    is_late_vs_promised: bool | None
    late_by_hours: float | None
    if promised_ts is None:
        is_late_vs_promised = None
        late_by_hours = None
    elif status == "delivered":
        if delivered_ts is None:
            is_late_vs_promised = None
            late_by_hours = None
        else:
            diff_sec = delivered_ts - promised_ts
            is_late_vs_promised = bool(diff_sec > 0.0)
            late_by_hours = round(diff_sec / SECONDS_PER_HOUR, 2) if diff_sec > 0.0 else 0.0
    elif status == "cancelled":
        is_late_vs_promised = False
        late_by_hours = 0.0
    else:
        diff_sec = as_of_ts - promised_ts
        is_late_vs_promised = bool(diff_sec > 0.0)
        late_by_hours = round(diff_sec / SECONDS_PER_HOUR, 2) if diff_sec > 0.0 else 0.0

    return {
        "as_of": as_of_iso,
        "can_self_service_cancel": can_self_service_cancel,
        "self_service_cancel_ineligible_reason": cancel_ineligible_code,
        "can_open_return_or_exchange": can_open_return_or_exchange,
        "days_since_delivery": days_since_delivery,
        "return_window_days": RETURN_WINDOW_DAYS,
        "within_return_window": within_return_window,
        "size_exchange_window_days": SIZE_EXCHANGE_WINDOW_DAYS,
        "within_size_exchange_window": within_size_exchange_window,
        "warranty_window_days": warranty_window_days,
        "warranty_source": warranty_info["source"],
        "within_warranty": within_warranty,
        "latest_estimated_delivery_at": latest_estimated_delivery_at,
        "promised_delivery_by": format_vn_iso(promised_ts),
        "is_late_vs_promised": is_late_vs_promised,
        "late_by_hours": late_by_hours,
    }
