"""Unit tests for RetailOps Guardrails (Sentiment, Topic Filter, Rate Limiter)."""
import unittest

from retailops.guardrails.rate_limiter import check_ood_limit
from retailops.guardrails.sentiment import analyze_sentiment
from retailops.guardrails.topic_filter import check_topic_safety


class GuardrailTests(unittest.TestCase):

    def test_sentiment_frustration_detection(self):
        # Negative sentiments
        res1 = analyze_sentiment("Làm ăn quá tệ, giao hàng chậm như rùa!")
        self.assertEqual(res1.sentiment, "negative")
        self.assertTrue(res1.strict_mode_required)

        res2 = analyze_sentiment("Shop lừa đảo à? Tôi muốn khiếu nại!")
        self.assertEqual(res2.sentiment, "negative")
        self.assertTrue(res2.strict_mode_required)

        # All caps shouting
        res3 = analyze_sentiment("TAI SAO KHONG TRA LOI TIN NHAN CUA TOI???")
        self.assertEqual(res3.sentiment, "negative")
        self.assertTrue(res3.strict_mode_required)

        # Positive sentiments
        res4 = analyze_sentiment("Dạ shop kiểm tra giúp em với ạ, em cảm ơn!")
        self.assertEqual(res4.sentiment, "positive")
        self.assertFalse(res4.strict_mode_required)

        # Neutral
        res5 = analyze_sentiment("Đơn hàng O-101 khi nào giao?")
        self.assertEqual(res5.sentiment, "neutral")
        self.assertFalse(res5.strict_mode_required)

    def test_topic_filter_blacklist(self):
        # Medical
        med = check_topic_safety("Tôi bị đau bụng thì uống thuốc gì khỏi?")
        self.assertFalse(med.is_safe)
        self.assertEqual(med.category, "medical")
        self.assertIn("chuyên môn y tế", med.refusal_message)

        # Legal
        leg = check_topic_safety("Tôi sẽ thuê luật sư khởi kiện shop ra tòa án")
        self.assertFalse(leg.is_safe)
        self.assertEqual(leg.category, "legal")

        # Politics
        pol = check_topic_safety("Quan điểm của shop về cuộc bầu cử chính trị là gì?")
        self.assertFalse(pol.is_safe)
        self.assertEqual(pol.category, "politics_religion")

        # Safe retail questions
        safe1 = check_topic_safety("Shop có áo sơ mi màu trắng size L không?")
        self.assertTrue(safe1.is_safe)

        safe2 = check_topic_safety("Giải thích thuật toán SAC cho tôi nghe")
        self.assertTrue(safe2.is_safe)  # Not forbidden, just out-of-domain (handled by witty agent)

    def test_ood_rate_limiter(self):
        # 1st OOD inquiry
        lim1 = check_ood_limit(0)
        self.assertTrue(lim1.allow_witty_pivot)

        # 2nd OOD inquiry
        lim2 = check_ood_limit(1)
        self.assertTrue(lim2.allow_witty_pivot)

        # 3rd consecutive OOD inquiry -> Cutoff
        lim3 = check_ood_limit(2)
        self.assertFalse(lim3.allow_witty_pivot)
        self.assertIsNotNone(lim3.cutoff_message)
        self.assertIn("chỉ được phép hỗ trợ các vấn đề mua sắm", lim3.cutoff_message)


if __name__ == "__main__":
    unittest.main()
