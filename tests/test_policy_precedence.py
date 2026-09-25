"""Tests for product warranty precedence over general policy and handling of delivery timestamps."""
import unittest


def resolve_warranty_period(product: dict, general_policy_days: int = 90) -> dict:
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


def check_warranty_eligibility(order: dict, product: dict, current_time: float) -> dict:
    """Checks warranty eligibility requiring delivered_at; never assumes valid if missing."""
    rule = resolve_warranty_period(product)
    warranty_days = rule["warranty_days"]

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


class PolicyPrecedenceTests(unittest.TestCase):
    def test_product_with_specific_warranty_overrides_general_policy(self):
        p603_leather_shoes = {"id": "P-603", "warranty_days": 180}
        resolved = resolve_warranty_period(p603_leather_shoes, general_policy_days=90)
        self.assertEqual(resolved["warranty_days"], 180)
        self.assertEqual(resolved["source"], "product_override")
        self.assertTrue(resolved["has_override"])

    def test_product_without_specific_warranty_defaults_to_general_policy(self):
        p101_shirt = {"id": "P-101", "warranty_days": None}
        resolved = resolve_warranty_period(p101_shirt, general_policy_days=90)
        self.assertEqual(resolved["warranty_days"], 90)
        self.assertEqual(resolved["source"], "general_policy")
        self.assertFalse(resolved["has_override"])

    def test_missing_delivered_at_returns_cannot_determine(self):
        order = {"id": "O-819127", "status": "delivered", "delivered_at": None}
        product = {"id": "P-603", "warranty_days": 180}
        check = check_warranty_eligibility(order, product, current_time=1700000000.0)
        self.assertEqual(check["status"], "cannot_determine")
        self.assertEqual(check["reason"], "missing_delivered_at")
        self.assertEqual(check["warranty_days"], 180)

    def test_delivered_at_within_warranty_period(self):
        delivered_at = 1700000000.0
        current_time = delivered_at + (30 * 86400.0)  # 30 days after
        order = {"id": "O-819127", "status": "delivered", "delivered_at": delivered_at}
        product = {"id": "P-603", "warranty_days": 180}
        check = check_warranty_eligibility(order, product, current_time=current_time)
        self.assertEqual(check["status"], "eligible")
        self.assertEqual(check["days_remaining"], 150)


if __name__ == "__main__":
    unittest.main()
