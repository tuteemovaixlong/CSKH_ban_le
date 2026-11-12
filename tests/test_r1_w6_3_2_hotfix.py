"""W6.3.2: synthetic evidence-based regression tests, independent of S01."""
import json
import unittest

from retailops.workflow.answer_check import CLAIM_NOTE, POLICY_NOTE, check_final_answer, tool_evidence


def messages(payload, role='tool', name='get_order'):
    return [{'role': role, 'tool_name': name, 'content': json.dumps(payload, ensure_ascii=False)}]


class ShippingFeeTests(unittest.TestCase):
    ORDER = {'order': {'shipping_fee': 30000, 'amount': 380000}}
    FACTS = (
        'Dạ đơn SIM-O-00084 tổng thanh toán 380.000 VNĐ (đã gồm 30.000 VNĐ phí ship, COD đã thanh toán), hiện đã giao thành công ạ.',
        'Dạ đơn SIM-O-00111 có phí vận chuyển là 30.000 VNĐ và được giao bởi hãng FastShip Nội Địa (FASTSHIP_SIM) ạ.',
        'Phí ship đơn này là 30k ạ.',
    )

    def test_order_shipping_facts_need_matching_tool_money(self):
        for text in self.FACTS:
            with self.subTest(text=text):
                self.assertEqual(check_final_answer(text, messages(self.ORDER)).text, text)
                self.assertEqual(check_final_answer(text).text, POLICY_NOTE)
        text = 'Đơn gồm 2 đôi giày size 43, tổng 1.860.000 VNĐ đã gồm 40.000 VNĐ phí ship ạ.'
        self.assertEqual(check_final_answer(text, messages({'amount': 1860000, 'shipping_fee': 40000})).text, text)
        self.assertEqual(check_final_answer(text).text, POLICY_NOTE)

    def test_money_formats_and_ids(self):
        for money in ('30.000', '30,000', '30000', '30k', '30 nghìn', '30 ngàn', '0,03 triệu',
                      '0.03 triệu', '30000đ', '30000 VNĐ', '30000 VND', '30000₫'):
            text = f'Phí giao hàng SIM-O-00084 cho Bộ Nồi 3 Đáy size 43 ×2 là {money} ạ.'
            with self.subTest(money=money):
                self.assertEqual(check_final_answer(text, messages(self.ORDER)).text, text)
        for money in ('0đ', '500 VND', '1k'):
            text = f'Phí vận chuyển là {money} ạ.'
            amount = {'0đ': 0, '500 VND': 500, '1k': 1000}[money]
            self.assertEqual(check_final_answer(text, messages({'shipping_fee': amount})).text, text)

    def test_policy_logistics_missing_or_mismatched_money_still_drop(self):
        for text in ('Phí ship đơn này là 20.000đ ạ.', 'Phí ship do shop chịu hoàn toàn.',
                     'Đơn được miễn phí ship ạ.', 'Phí đổi hàng là 30.000đ ạ.',
                     'Phí ship 30k và phí trả hàng 30k ạ.', 'Shop chịu phí ship 30k ạ.',
                     'Phí ship 30k, shop hỗ trợ phí giao hàng 30k ạ.', 'Phí ship 30k được miễn cước ạ.',
                     'Phí ship 30k, freeship ạ.', 'Phí ship 30k, không tính thêm phí ạ.',
                     'Phí ship 30k và giao tận nhà ạ.', 'Phí ship đơn SIM-O-30000 size 43 ×2 ạ.',
                     'Phí ship 30k tổng 400000 ạ.'):
            with self.subTest(text=text):
                self.assertEqual(check_final_answer(text, messages(self.ORDER)).text, POLICY_NOTE)

    def test_money_evidence_walks_all_tool_results_but_rejects_bool_and_non_int(self):
        payload = {'orders': [{'shipping_fee': 30000, 'amount': 380000},
                              {'refund_summary': {'refunded_total': 500, 'pending_total': 1000}}]}
        self.assertEqual(tool_evidence(messages(payload, name='list_orders')).money_amounts,
                         frozenset({30000, 380000, 500, 1000}))
        for key in ('shipping_fee', 'amount', 'refunded_total', 'pending_total'):
            for value in (True, '30000', 30000.0):
                with self.subTest(key=key, value=value):
                    self.assertFalse(tool_evidence(messages({key: value})).money_amounts)
        for role in ('user', 'assistant'):
            self.assertEqual(check_final_answer(self.FACTS[0], messages(self.ORDER, role)).text, POLICY_NOTE)
        combined = messages({'shipping_fee': 30000}) + messages({'amount': 380000})
        self.assertEqual(check_final_answer(self.FACTS[0], combined).text, self.FACTS[0])


class RefundTests(unittest.TestCase):
    REFUNDED = {'order': {'payment_status': 'refunded', 'refund_summary': {
        'latest_status': 'completed', 'refunded_total': 3820000}}}
    FACTS = (
        'Khoản thanh toán 3.820.000 VNĐ qua ví điện tử của anh/chị đã được ghi nhận hoàn tiền thành công trên hệ thống nhé.',
        'Đơn SIM-O-00066 đã được hoàn tiền thành công ạ.',
        'Đơn đã được hoàn trả rồi ạ.',
        'Đơn đã được hoàn thành công ạ.',
    )

    def test_refund_facts_need_completed_evidence(self):
        for text in self.FACTS:
            with self.subTest(text=text):
                self.assertEqual(check_final_answer(text, messages(self.REFUNDED)).text, text)
                self.assertEqual(check_final_answer(text).text, CLAIM_NOTE)
                pending = {'payment_status': 'paid', 'refund_summary': {'latest_status': 'pending', 'refunded_total': 0}}
                self.assertEqual(check_final_answer(text, messages(pending)).text, CLAIM_NOTE)

    def test_each_refund_evidence_source(self):
        for payload in ({'payment_status': 'refunded'}, {'payment_status': 'partially_refunded'},
                        {'refund_summary': {'latest_status': 'completed'}},
                        {'refund': {'latest_status': 'completed'}},
                        {'refund_summary': {'refunded_total': 1}}, {'refund': {'refunded_total': 1}}):
            with self.subTest(payload=payload):
                self.assertTrue(tool_evidence(messages({'nested': [payload]})).refunded)
                self.assertEqual(check_final_answer(self.FACTS[1], messages(payload)).text, self.FACTS[1])
        for payload in ({'status': 'completed'}, {'refunded_total': 0},
                        {'refund': {'refunded_total': True}}, {'refund': {'refunded_total': -1}}):
            self.assertFalse(tool_evidence(messages(payload)).refunded)
        self.assertFalse(tool_evidence(messages(self.REFUNDED, role='user')).refunded)

    def test_refund_does_not_prove_other_actions(self):
        for text in ('Đơn đã được hoàn tiền và em đã đổi size cho anh/chị rồi ạ.',
                     'Đơn đã được hoàn tiền và em đã hủy đơn rồi ạ.',
                     'Đơn đã được hoàn tiền và em đã trả hàng rồi ạ.',
                     'Đơn đã được hoàn tiền và em đã gửi yêu cầu rồi ạ.',
                     'Đơn đã được hoàn tiền và yêu cầu đã được tạo ạ.',
                     'Đơn đã được hoàn tiền và hủy rồi ạ.'):
            with self.subTest(text=text):
                self.assertEqual(check_final_answer(text, messages(self.REFUNDED)).text, CLAIM_NOTE)
        self.assertEqual(check_final_answer('Em đã hoàn tiền cho anh/chị rồi ạ.').text, CLAIM_NOTE)
        self.assertEqual(check_final_answer('Đơn của anh/chị đã được hoàn tiền thành công.').text, CLAIM_NOTE)

    def test_refund_context_is_not_another_completed_action(self):
        for text in ('Đơn đã được hoàn tiền sau khi trả hàng ạ.',
                     'Đơn đã được hoàn tiền cho yêu cầu đổi size ạ.'):
            with self.subTest(text=text):
                self.assertEqual(check_final_answer(text, messages(self.REFUNDED)).text, text)


class DeadlineProductNumbersTests(unittest.TestCase):
    EVIDENCE = {'warranty_window_days': 365, 'return_window_days': 7, 'size_exchange_window_days': 15,
                'within_return_window': False, 'within_size_exchange_window': False, 'within_warranty': True}

    def test_only_numbers_before_time_units_are_deadlines(self):
        for text in (
            'Hiện đơn đã hết thời hạn trả hàng và đổi size, nhưng vẫn còn trong thời hạn bảo hành (Bộ Nồi Inox 3 Đáy Cao Cấp bảo hành 365 ngày) ạ.',
            'Giày size 43 ×2 còn thời hạn bảo hành 365 ngày ạ.',
            'Giày size 43 ×2 còn trong thời hạn trả hàng ạ.',
        ):
            with self.subTest(text=text):
                self.assertEqual(check_final_answer(text, messages(self.EVIDENCE)).text, text)
                self.assertEqual(check_final_answer(text).text, POLICY_NOTE)

    def test_unknown_time_numbers_and_all_time_units(self):
        for text in ('Bộ Nồi Inox 3 Đáy bảo hành 30 ngày ạ.', 'Shop đổi trong 30 ngày ạ.'):
            self.assertEqual(check_final_answer(text, messages(self.EVIDENCE)).text, POLICY_NOTE)
        for unit in ('ngày', 'tuần', 'tháng', 'năm', 'giờ'):
            text = f'Shop đổi size 43 trong 7 {unit} ạ.'
            with self.subTest(unit=unit):
                self.assertEqual(check_final_answer(text, messages(self.EVIDENCE)).text, text)
                self.assertEqual(check_final_answer(text, messages({'return_window_days': 15})).text, POLICY_NOTE)
        self.assertEqual(check_final_answer('Shop đổi trong 30 ngày ạ.', messages({
            'return_window_days': 7, 'size_exchange_window_days': 15, 'warranty_window_days': 90})).text, POLICY_NOTE)


if __name__ == '__main__':
    unittest.main()
