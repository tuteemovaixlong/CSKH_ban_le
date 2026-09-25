"""Tests for product warranty precedence over general policy and handling of delivery timestamps."""
import unittest

from retailops.business.warranty import (
    check_warranty_eligibility,
    resolve_warranty_period,
)


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
