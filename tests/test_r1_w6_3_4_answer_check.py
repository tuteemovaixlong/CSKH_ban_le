"""W6.3.4-D1: negated concurrency must not look like completed work."""
import json
import unittest

from retailops.workflow.answer_check import CLAIM_NOTE, check_final_answer


class NegatedConcurrencyTests(unittest.TestCase):
    def test_handoff_refusals_are_kept(self):
        for text in (
            'Dạ mỗi đơn hàng chỉ có thể mở một yêu cầu tại một thời điểm nên đơn SIM-O-00091 chưa thể vừa gửi yêu cầu trả vừa gửi yêu cầu đổi cùng lúc ạ.',
            'Dạ đơn SIM-O-00091 không thể vừa trả hàng vừa đổi size cùng lúc ạ.',
            'Đơn SIM-O-00079 không thể vừa đổi size vừa hoàn tiền ạ.',
            'Yêu cầu trả và yêu cầu đổi của đơn này chưa thể vừa gửi cùng lúc ạ.',
            'Shop chưa hỗ trợ vừa hủy đơn vừa đặt lại trong cùng một yêu cầu ạ.',
            'Mỗi đơn chỉ mở được một yêu cầu, nên anh/chị không thể vừa đổi size vừa trả hàng cho đơn này ạ.',
        ):
            with self.subTest(text=text):
                result = check_final_answer(text, [])
                self.assertEqual(result.text, text)
                self.assertFalse(result.changed)

    def test_all_decided_negation_prefixes(self):
        for prefix in ('không', 'chưa', 'không thể', 'chưa thể', 'không được', 'chưa được'):
            text = f'Đơn SIM-O-00079 {prefix} vừa đổi size vừa hoàn tiền ạ.'
            with self.subTest(prefix=prefix):
                self.assertEqual(check_final_answer(text, []).text, text)

    def test_negation_does_not_create_an_extra_action_after_a_proven_refund(self):
        text = ('Shop đã hoàn tiền cho đơn SIM-O-00091, nhưng đơn không thể '
                'vừa đổi size vừa trả hàng ạ.')
        messages = [{'role': 'tool', 'content': json.dumps({'payment_status': 'refunded'})}]
        self.assertEqual(check_final_answer(text, messages).text, text)

    def test_unsupported_completed_actions_are_still_cut(self):
        for text in (
            'Đơn SIM-O-00079 vừa đổi size vừa hoàn tiền xong rồi ạ.',
            'Em vừa gửi yêu cầu trả vừa gửi yêu cầu đổi cho anh/chị rồi ạ.',
            'Em vừa hủy đơn SIM-O-00115 cho anh/chị rồi ạ.',
            'Đơn SIM-O-00115 vừa được hủy thành công ạ.',
            'Yêu cầu trả hàng của anh/chị vừa được gửi ạ.',
            'Shop vừa hoàn tiền cho đơn SIM-O-00091 rồi ạ.',
            'Đơn chưa thể vừa trả hàng vừa đổi size, nhưng em vừa hủy đơn cho anh/chị rồi ạ.',
            # Only the negated "vừa … vừa" pair is masked; a third "vừa" in the same run-on clause is a claim.
            'Đơn không thể vừa đổi vừa trả và em vừa hủy đơn SIM-O-00115 rồi ạ.',
            'Em không thể vừa đổi vừa trả nên em vừa hủy đơn SIM-O-00115 rồi ạ.',
        ):
            with self.subTest(text=text):
                result = check_final_answer(text, [])
                self.assertEqual(result.text, CLAIM_NOTE)
                self.assertEqual(result.dropped_claims, 1)


if __name__ == '__main__':
    unittest.main()
