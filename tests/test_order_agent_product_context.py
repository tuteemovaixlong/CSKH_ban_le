"""Tests for order worker product context handling, prompt guidelines, and warranty rendering."""
import unittest

from retailops.workflow.subagents.order_agent import (
    ORDER_SYSTEM_PROMPT,
    _product,
    _synthesize_order_response,
)


class OrderAgentProductContextTests(unittest.TestCase):
    def test_product_renderer_includes_warranty_days_when_present(self):
        product_leather_shoes = {
            "id": "P-603",
            "name": "Giày lười da bò cao cấp",
            "material": "Da bò thật 100%",
            "care": "Lau sạch bụi bằng khăn ẩm, đánh xi định kỳ",
            "warranty_days": 180,
        }
        rendered = _product(product_leather_shoes)
        self.assertIn("P-603: Giày lười da bò cao cấp", rendered)
        self.assertIn("Chất liệu: Da bò thật 100%", rendered)
        self.assertIn("Bảo hành: 180 ngày", rendered)

    def test_product_renderer_without_warranty(self):
        product_simple = {
            "id": "P-101",
            "name": "Áo thun Basic",
            "material": "Cotton 100%",
        }
        rendered = _product(product_simple)
        self.assertIn("P-101: Áo thun Basic", rendered)
        self.assertIn("Chất liệu: Cotton 100%", rendered)
        self.assertNotIn("Bảo hành:", rendered)

    def test_prompt_enforces_product_id_lookup_for_order_items(self):
        self.assertIn("product_id (P-...)", ORDER_SYSTEM_PROMPT)
        self.assertIn("NEVER pass an order ID to get_product", ORDER_SYSTEM_PROMPT)
        self.assertIn("NEVER call search_products with generic words", ORDER_SYSTEM_PROMPT)
        self.assertIn("exact warranty_days from get_product", ORDER_SYSTEM_PROMPT)
        self.assertIn("Never claim 12 months", ORDER_SYSTEM_PROMPT)

    def test_synthesizer_renders_product_from_tool_results(self):
        tool_results = [
            {
                "name": "get_product",
                "args": {"product_id": "P-603"},
                "result": {
                    "product": {
                        "id": "P-603",
                        "name": "Giày lười da bò cao cấp",
                        "material": "Da bò thật 100%",
                        "warranty_days": 180,
                    }
                },
            }
        ]
        text = _synthesize_order_response(tool_results)
        self.assertIsNotNone(text)
        self.assertIn("Giày lười da bò cao cấp", text)
        self.assertIn("Da bò thật 100%", text)
        self.assertIn("180 ngày", text)


if __name__ == "__main__":
    unittest.main()
