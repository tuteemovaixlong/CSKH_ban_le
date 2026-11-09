"""Warranty business logic: precedence between product catalog and general policy, and eligibility checks."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

_VN_TZ = timezone(timedelta(hours=7))


def _iso_vn(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=_VN_TZ).isoformat(timespec="seconds")


def resolve_warranty_period(product: Optional[Dict[str, Any]], general_policy_days: int = 90) -> Dict[str, Any]:
    """Precedence logic: product specific warranty_days overrides general policy days."""
    if not isinstance(product, dict):
        return {
            "source": "general_policy",
            "warranty_days": general_policy_days,
            "has_override": False,
        }

    product_warranty = product.get("warranty_days")
    if isinstance(product_warranty, (int, float)) and product_warranty > 0:
        return {
            "source": "product_override",
            "warranty_days": int(product_warranty),
            "has_override": True,
            "product_id": product.get("id"),
        }

    return {
        "source": "general_policy",
        "warranty_days": general_policy_days,
        "has_override": False,
    }


def check_warranty_eligibility(
    order: Optional[Dict[str, Any]],
    product: Optional[Dict[str, Any]],
    current_time: float,
    general_policy_days: int = 90,
) -> Dict[str, Any]:
    """Checks warranty eligibility requiring delivered_at; never assumes valid if missing."""
    rule = resolve_warranty_period(product, general_policy_days=general_policy_days)
    warranty_days = rule["warranty_days"]

    as_of = _iso_vn(current_time)
    if not isinstance(order, dict):
        return {
            "status": "cannot_determine",
            "reason": "missing_order",
            "warranty_days": warranty_days,
            "as_of": as_of,
            "message": "Không tìm thấy dữ liệu đơn hàng để kiểm tra thời hạn bảo hành.",
        }

    delivered_at = order.get("delivered_at")
    if not delivered_at:
        return {
            "status": "cannot_determine",
            "reason": "missing_delivered_at",
            "warranty_days": warranty_days,
            "as_of": as_of,
            "message": "Không thể kết luận thời hạn bảo hành do hệ thống chưa có ngày nhận hàng thực tế.",
        }

    seconds_in_day = 86400.0
    elapsed_seconds = float(current_time) - float(delivered_at)
    elapsed_days = elapsed_seconds / seconds_in_day

    if 0.0 <= elapsed_seconds <= warranty_days * seconds_in_day:
        return {
            "status": "eligible",
            "warranty_days": warranty_days,
            "days_remaining": int(warranty_days - elapsed_days),
            "as_of": as_of,
        }
    else:
        return {
            "status": "expired",
            "warranty_days": warranty_days,
            "days_exceeded": max(0, int(elapsed_days - warranty_days)),
            "as_of": as_of,
        }
