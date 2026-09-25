"""Warranty business logic: precedence between product catalog and general policy, and eligibility checks."""
from typing import Any, Dict, Optional


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

    if not isinstance(order, dict):
        return {
            "status": "cannot_determine",
            "reason": "missing_order",
            "warranty_days": warranty_days,
            "message": "Không tìm thấy dữ liệu đơn hàng để kiểm tra thời hạn bảo hành.",
        }

    delivered_at = order.get("delivered_at")
    if not delivered_at:
        return {
            "status": "cannot_determine",
            "reason": "missing_delivered_at",
            "warranty_days": warranty_days,
            "message": "Không thể kết luận thời hạn bảo hành do hệ thống chưa có ngày nhận hàng thực tế.",
        }

    seconds_in_day = 86400.0
    elapsed_days = (current_time - delivered_at) / seconds_in_day

    if elapsed_days <= warranty_days:
        return {
            "status": "eligible",
            "warranty_days": warranty_days,
            "days_remaining": int(warranty_days - elapsed_days),
        }
    else:
        return {
            "status": "expired",
            "warranty_days": warranty_days,
            "days_exceeded": int(elapsed_days - warranty_days),
        }
