"""Templates for Suite T08: Hội thoại đa lượt (150 ca, 13 khung).

Covers:
- Tra đơn rồi hỏi phí ship (2 lượt)
- Hỏi sản phẩm rồi quay về đơn hàng (2 lượt)
- Hỏi trả hàng rồi đổi ý sang đổi size (2 lượt)
- Hủy đơn rồi hỏi về hoàn tiền (2 lượt)
- Nhiều đơn, lượt sau tham chiếu "đơn lúc nãy" (2 lượt)
- Đổi chủ đề hỏi chính sách rồi quay lại đơn (3 lượt)
- Hỏi chính sách rồi thực hiện thao tác (2 lượt)
- 4 lượt quy trình đổi size đầy đủ (4 lượt)
- Hỏi tồn kho rồi hỏi tư vấn size (2 lượt)
- Tra cứu giao hàng rồi hỏi đồng kiểm (2 lượt)
- Hỏi bảo hành rồi mở đổi hàng (2 lượt)
- Có 2 đơn, chọn 1 đơn để thao tác (2 lượt)
- Kiểm tra trạng thái và hỏi phí ship (2 lượt)
"""
from __future__ import annotations

import random
from typing import Any

from .base import BaseTemplate, Brief


class T08TraDonRoiHoiPhiShip(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t08_tra_don_roi_hoi_phi_ship', 'T08', 12, description='Tra cứu đơn rồi hỏi phí ship của chính đơn đó (2 lượt)')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['delivered'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t08_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        fee = slot.get('shipping_fee') or 30000
        b1 = Brief(brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_tra_don", intent=f"tra_cuu_don_hang_luot_1_{case_index}", must_include=[ext_oid], length="ngắn")
        b2 = Brief(brief_id=f"brf_{cid}_t2", case_id=cid, turn=2, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_tra_don", intent=f"hoi_phi_ship_don_vua_tra_{case_index}", must_include=["phí ship"],
                   earlier_turns=[{'turn': 1, 'intent': 'tra_cuu_don_hang_luot_1', 'assistant': f'đơn {ext_oid} đã giao'}], length="ngắn")
        case = {
            'id': cid, 'category': 't08', 'title': f'Tra đơn rồi hỏi phí ship {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T08', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T08 order then ship fee {ext_oid}',
                'slot_key': ext_oid, 'intent': f"order_then_fee_{case_index}", 'vn_context': []
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: tra cứu đơn {ext_oid}>",
                    'expect': {'tools_called': ['get_order'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['đã giao', 'giao thành công']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} của anh/chị đã được giao thành công rồi ạ."}
                    ]
                },
                {
                    'user': "<chờ lời khách: hỏi phí ship của đơn này là bao nhiêu>",
                    'expect': {
                        'tools_called': ['get_order'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['phí ship', 'phí vận chuyển', 'VNĐ']], 'answer_not': ['đã hủy']
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ theo thông tin đơn {ext_oid}, phí vận chuyển của đơn hàng này là {fee:,} VNĐ anh/chị nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [b1, b2]


class T08SanPhamRoiVeDon(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t08_san_pham_roi_ve_don', 'T08', 12, description='Hỏi thông tin sản phẩm rồi quay lại hỏi về đơn hàng của mình (2 lượt)')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['delivered'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t08_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        pid = slot.get('product_id') or 'P-101'
        b1 = Brief(brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_hoi_sp", intent="hoi_thong_tin_san_pham_luot_1", must_include=["áo"], length="ngắn")
        b2 = Brief(brief_id=f"brf_{cid}_t2", case_id=cid, turn=2, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_hoi_sp", intent="quay_lai_hoi_don_hang_luot_2", must_include=[ext_oid],
                   earlier_turns=[{'turn': 1, 'intent': 'hoi_thong_tin_san_pham_luot_1', 'assistant': 'tư vấn sản phẩm'}], length="ngắn")
        case = {
            'id': cid, 'category': 't08', 'title': f'Hỏi sản phẩm rồi về đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T08', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T08 product then order {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi thông tin áo>",
                    'expect': {'tools_called': ['get_product'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'answer_any': [['sản phẩm', 'áo', 'chất liệu']], 'answer_not': ['[KB:']},
                    'fake_model': [
                        {'call': [{'name': 'get_product', 'arguments': {'product_id': pid}}]},
                        {'say': f"Dạ sản phẩm {pid} của shop được làm từ chất liệu cao cấp, mặc rất thoáng mát ạ."}
                    ]
                },
                {
                    'user': f"<chờ lời khách: kiểm tra đơn {ext_oid}>",
                    'expect': {'tools_called': ['get_order'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['đơn hàng', 'giao']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} của anh/chị đã được giao thành công rồi ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [b1, b2]


class T08TraRoiDoiYDoi(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t08_tra_roi_doi_y_doi', 'T08', 12, description='Hỏi trả hàng rồi đổi ý muốn đổi size thay vì trả tiền (2 lượt)')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t08_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        b1 = Brief(brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_doi_tra", intent="hoi_tra_hang_luot_1", must_include=[ext_oid], length="ngắn")
        b2 = Brief(brief_id=f"brf_{cid}_t2", case_id=cid, turn=2, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_doi_tra", intent="doi_y_sang_doi_size_luot_2", must_include=["đổi size"],
                   earlier_turns=[{'turn': 1, 'intent': 'hoi_tra_hang_luot_1', 'assistant': f'hướng dẫn trả hàng đơn {ext_oid}'}], length="ngắn")
        case = {
            'id': cid, 'category': 't08', 'title': f'Trả hàng đổi ý sang đổi size {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T08', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T08 return then change to exchange {ext_oid}', 'vn_context': ['doi_size_thoi_trang']},
            'turns': [
                {
                    'user': f"<chờ lời khách: muốn trả hàng đơn {ext_oid}>",
                    'expect': {'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_order_action_reason', 'order_action': {'order_id': ext_oid, 'action_type': 'return'}, 'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'trả hàng']], 'answer_not': ['đã hủy']},
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'return'}}]},
                        {'say': f"Dạ em đã mở biểu mẫu trả hàng cho đơn {ext_oid} trên màn hình rồi ạ."}
                    ]
                },
                {
                    'user': "<chờ lời khách: thôi đổi ý sang đổi size giúp mình>",
                    'expect': {'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_order_action_reason', 'order_action': {'order_id': ext_oid, 'action_type': 'exchange'}, 'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['đổi size', 'biểu mẫu']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'exchange'}}]},
                        {'say': f"Dạ em đã chuyển sang biểu mẫu đổi size cho đơn {ext_oid} rồi ạ, anh/chị chọn size mới trên biểu mẫu giúp em nhé."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [b1, b2]


class T08HuyRoiHoiHoanTien(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t08_huy_roi_hoi_hoan_tien', 'T08', 12, description='Hủy đơn pending rồi hỏi tiền đã trả trước hoàn về đâu (2 lượt)')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['pending'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t08_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        is_cod = (slot.get('payment_method') == 'cod')

        k_chunk = view.get_knowledge_chunk('refunds.md', '12 đến 72 giờ') if view else {
            'source_key': 'refunds.md', 'title': 'Chính sách hoàn tiền',
            'chunk': 'Đơn thanh toán khi nhận hàng (COD) bị hủy trước khi giao: khách chưa trả tiền nên không có khoản hoàn. Đơn đã thanh toán trước bị hủy: hoàn toàn bộ số tiền đã trả. Sau khi cửa hàng xác nhận hoàn tiền, cổng thanh toán thường xử lý xong trong 12 đến 72 giờ.'
        }

        b1 = Brief(brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_huy_don", intent=f"yeu_cau_huy_don_luot_1_{case_index}", must_include=[ext_oid], length="ngắn")
        b2 = Brief(brief_id=f"brf_{cid}_t2", case_id=cid, turn=2, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_huy_don", intent=f"hoi_tien_hoan_ve_dau_luot_2_{case_index}", must_include=["hoàn tiền"],
                   earlier_turns=[{'turn': 1, 'intent': 'yeu_cau_huy_don_luot_1', 'assistant': f'đã mở biểu mẫu hủy đơn {ext_oid}'}], length="ngắn")

        if is_cod:
            say_t2 = f"Dạ theo chính sách hoàn tiền của shop [{{{{last_tool.results.0.citation_id}}}}], đơn hàng {ext_oid} thanh toán COD khi nhận hàng nên khi hủy trước khi giao anh/chị chưa trả tiền, do đó sẽ không phát sinh khoản tiền hoàn nào ạ."
            ans_any_t2 = [['chưa trả tiền', 'không phát sinh', 'chưa thanh toán']]
        else:
            say_t2 = f"Dạ theo chính sách hoàn tiền [{{{{last_tool.results.0.citation_id}}}}], sau khi đơn hàng {ext_oid} hoàn tất hủy, cổng thanh toán sẽ xử lý hoàn tiền về tài khoản ban đầu trong vòng 12 đến 72 giờ ạ."
            ans_any_t2 = [['12 đến 72 giờ', '12–72 giờ', 'tài khoản']]

        case = {
            'id': cid, 'category': 't08', 'title': f'Hủy đơn rồi hỏi hoàn tiền {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T08', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T08 cancel then refund inquiry {ext_oid}',
                'slot_key': ext_oid, 'intent': f"cancel_then_refund_{case_index}", 'vn_context': []
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: yêu cầu hủy đơn {ext_oid}>",
                    'expect': {'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_cancel_reason', 'order_action': {'order_id': ext_oid, 'action_type': 'cancel'}, 'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'hủy']], 'answer_not': ['đã hủy thành công']},
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'cancel'}}]},
                        {'say': f"Dạ em đã mở biểu mẫu hủy đơn {ext_oid} trên màn hình để anh/chị chọn lý do và xác nhận ạ."}
                    ]
                },
                {
                    'user': "<chờ lời khách: hủy xong thì tiền hoàn về đâu>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'sources': ['refunds.md'], 'answer_any': ans_any_t2, 'answer_not': ['3 đến 5 ngày', '3-5 ngày', 'chưa có thông tin']
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'thời gian hoàn tiền khi hủy đơn hàng'}}]},
                        {'say': say_t2}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'pending'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [b1, b2]


class T08NhieuDonThamChieuDonLucNay(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t08_nhieu_don_tham_chieu_don_luc_nay', 'T08', 12, description='Khách có nhiều đơn, lượt sau nói "đơn lúc nãy" (2 lượt)')

    def select(self, view: Any) -> list[Any]:
        return [c for c in view.customers.values() if c['order_count'] >= 2]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t08_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        ords = view.customer_orders[cust_id] if view else []
        ord1 = ords[0] if ords else {'external_order_id': 'SIM-O-50006', 'status': 'delivered'}
        ext_oid = ord1['external_order_id']
        b1 = Brief(brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_nhieu_don", intent=f"tra_cuu_don_cu_the_luot_1_{case_index}", must_include=[ext_oid], length="ngắn")
        b2 = Brief(brief_id=f"brf_{cid}_t2", case_id=cid, turn=2, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_nhieu_don", intent=f"hoi_them_ve_don_vua_hoi_{case_index}", must_include=["đơn lúc nãy"],
                   earlier_turns=[{'turn': 1, 'intent': 'tra_cuu_don_cu_the_luot_1', 'assistant': f'đơn {ext_oid} đã giao'}], length="ngắn")
        case = {
            'id': cid, 'category': 't08', 'title': f'Tham chiếu đơn lúc nãy {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T08', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T08 refer to focused order {ext_oid}',
                'slot_key': ext_oid, 'intent': f"refer_focused_order_{case_index}", 'vn_context': []
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: tra cứu đơn {ext_oid}>",
                    'expect': {'tools_called': ['get_order'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['đã giao', 'giao thành công']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} của anh/chị đã được giao thành công rồi ạ."}
                    ]
                },
                {
                    'user': "<chờ lời khách: thế đơn lúc nãy có được đổi hàng không>",
                    'expect': {
                        'tools_called': ['get_order'], 'tools_not_called': ['list_orders'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['đổi hàng', 'đổi size', '15 ngày']], 'answer_not': ['chưa có thông tin']
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ em đã kiểm tra lại đơn {ext_oid} lúc nãy, đơn hàng này đã giao và vẫn còn trong thời hạn 15 ngày đổi size ạ. Nếu anh/chị muốn đổi size, em sẽ hỗ trợ mở biểu mẫu đổi hàng nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: ord1['status']}, 'rows': {'order_action_requests': 0}}
        }
        return case, [b1, b2]


class T08DoiChuDeRoiQuayLai(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t08_doi_chu_de_roi_quay_lai', 'T08', 12, description='Đổi chủ đề hỏi chính sách rồi quay lại đơn cũ (3 lượt)')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t08_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        b1 = Brief(brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_hoi_don", intent="tra_don_luot_1", must_include=[ext_oid], length="ngắn")
        b2 = Brief(brief_id=f"brf_{cid}_t2", case_id=cid, turn=2, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_hoi_don", intent="chuyen_sang_hoi_chinh_sach_luot_2", must_include=["đổi size"],
                   earlier_turns=[{'turn': 1, 'intent': 'tra_don_luot_1', 'assistant': f'đơn {ext_oid} đã giao'}], length="ngắn")
        b3 = Brief(brief_id=f"brf_{cid}_t3", case_id=cid, turn=3, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_hoi_don", intent="quay_lai_mo_doi_don_cu_luot_3", must_include=[ext_oid],
                   earlier_turns=[{'turn': 2, 'intent': 'chuyen_sang_hoi_chinh_sach_luot_2', 'assistant': 'chính sách đổi 15 ngày'}], length="ngắn")
        k_chunk = view.get_knowledge_chunk('policy_size_exchange_twoway.md', '15 ngày') if view else {
            'source_key': 'policy_size_exchange_twoway.md', 'title': 'Chính sách đổi size, đổi màu 2 chiều tận nhà',
            'chunk': 'Khách hàng được hỗ trợ đổi size hoặc đổi màu cho cùng một sản phẩm trong vòng **15 ngày kể từ ngày nhận hàng**.'
        }
        case = {
            'id': cid, 'category': 't08', 'title': f'Đổi chủ đề rồi quay lại đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T08', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T08 topic switch and return {ext_oid}', 'vn_context': ['doi_size_thoi_trang']},
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: kiểm tra đơn {ext_oid}>",
                    'expect': {'tools_called': ['get_order'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['đã giao', 'giao thành công']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} của anh/chị đã được giao thành công rồi ạ."}
                    ]
                },
                {
                    'user': "<chờ lời khách: shop cho đổi size trong bao nhiêu ngày>",
                    'expect': {'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'sources': ['policy_size_exchange_twoway.md'], 'answer_all': ['15 ngày'], 'answer_any': [['đổi size', 'đổi màu']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'thời hạn đổi size đổi màu 15 ngày'}}]},
                        {'say': "Dạ shop hỗ trợ đổi size trong vòng 15 ngày kể từ ngày nhận hàng ạ [{{last_tool.results.0.citation_id}}]."}
                    ]
                },
                {
                    'user': f"<chờ lời khách: vậy mở đổi size cho đơn {ext_oid} giúp mình>",
                    'expect': {'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_order_action_reason', 'order_action': {'order_id': ext_oid, 'action_type': 'exchange'}, 'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'đổi']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'exchange'}}]},
                        {'say': f"Dạ em đã mở biểu mẫu đổi hàng cho đơn {ext_oid} rồi ạ, anh/chị chọn size mới trên biểu mẫu giúp em nhé."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [b1, b2, b3]


class T08ChinhSachRoiThaoTac(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t08_chinh_sach_roi_thao_tac', 'T08', 12, description='Hỏi chính sách trả hàng rồi yêu cầu mở trả hàng đơn cụ thể (2 lượt)')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t08_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('returns.md', '7 ngày') if view else {
            'source_key': 'returns.md', 'title': 'Chính sách trả hàng',
            'chunk': 'Khách có quyền gửi yêu cầu trả hàng trong vòng **7 ngày kể từ ngày giao** (ngày giao ghi trong dữ liệu đơn). Sản phẩm phải chưa qua sử dụng, còn tem mác, phụ kiện và quà tặng kèm. Hệ thống tự tính đơn còn trong hạn trả hàng hay không; trợ lý đọc kết quả đó, không tự tính lại.'
        }
        b1 = Brief(brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_hoi_chinh_sach", intent="hoi_chinh_sach_tra_hang_luot_1", must_include=["trả hàng"], length="ngắn")
        b2 = Brief(brief_id=f"brf_{cid}_t2", case_id=cid, turn=2, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_hoi_chinh_sach", intent="mo_tra_hang_don_cu_the_luot_2", must_include=[ext_oid],
                   earlier_turns=[{'turn': 1, 'intent': 'hoi_chinh_sach_tra_hang_luot_1', 'assistant': 'chính sách trả hàng trong 7 ngày'}], length="ngắn")
        case = {
            'id': cid, 'category': 't08', 'title': f'Hỏi chính sách rồi mở trả {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T08', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T08 policy then action {ext_oid}', 'vn_context': []},
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi thời hạn trả hàng>",
                    'expect': {'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'sources': ['returns.md'], 'answer_all': ['7 ngày'], 'answer_any': [['trả hàng', 'đổi trả']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'thời hạn trả hàng quy định 7 ngày'}}]},
                        {'say': "Dạ thời hạn trả hàng là 7 ngày kể từ ngày nhận hàng ạ [{{last_tool.results.0.citation_id}}]."}
                    ]
                },
                {
                    'user': f"<chờ lời khách: mở trả hàng cho đơn {ext_oid} giúp mình>",
                    'expect': {'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_order_action_reason', 'order_action': {'order_id': ext_oid, 'action_type': 'return'}, 'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'trả hàng']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'return'}}]},
                        {'say': f"Dạ em đã mở biểu mẫu trả hàng cho đơn {ext_oid} rồi ạ, anh/chị chọn lý do và xác nhận trên biểu mẫu giúp em nhé."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [b1, b2]


class T08BonLuotDoiSize(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t08_bon_luot_doi_size', 'T08', 12, description='Hội thoại 4 lượt quy trình đổi size chi tiết')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t08_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        b1 = Brief(brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_doi_size_4_luot", intent="tra_don_luot_1", must_include=[ext_oid], length="ngắn")
        b2 = Brief(brief_id=f"brf_{cid}_t2", case_id=cid, turn=2, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_doi_size_4_luot", intent="hoi_thoi_han_doi_luot_2", must_include=["đổi size"], length="ngắn")
        b3 = Brief(brief_id=f"brf_{cid}_t3", case_id=cid, turn=3, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_doi_size_4_luot", intent="hoi_phi_ship_doi_luot_3", must_include=["phí ship"], length="ngắn")
        b4 = Brief(brief_id=f"brf_{cid}_t4", case_id=cid, turn=4, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_doi_size_4_luot", intent="mo_bieu_mau_doi_size_luot_4", must_include=[ext_oid], length="ngắn")
        k_chunk = view.get_knowledge_chunk('policy_size_exchange_twoway.md', '15 ngày') if view else {
            'source_key': 'policy_size_exchange_twoway.md', 'title': 'Chính sách đổi size, đổi màu 2 chiều tận nhà',
            'chunk': 'Khách hàng được hỗ trợ đổi size hoặc đổi màu cho cùng một sản phẩm trong vòng **15 ngày kể từ ngày nhận hàng**.'
        }
        case = {
            'id': cid, 'category': 't08', 'title': f'4 lượt quy trình đổi size {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T08', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T08 4 turns exchange {ext_oid}', 'vn_context': ['doi_size_thoi_trang']},
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: tra cứu đơn {ext_oid}>",
                    'expect': {'tools_called': ['get_order'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['đã giao', 'giao thành công']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} đã giao thành công rồi ạ."}
                    ]
                },
                {
                    'user': "<chờ lời khách: đổi size trong bao lâu>",
                    'expect': {'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'sources': ['policy_size_exchange_twoway.md'], 'answer_all': ['15 ngày'], 'answer_any': [['đổi size']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'thời hạn đổi size 15 ngày'}}]},
                        {'say': "Dạ thời hạn đổi size là 15 ngày ạ [{{last_tool.results.0.citation_id}}]."}
                    ]
                },
                {
                    'user': "<chờ lời khách: đổi size có mất phí ship không>",
                    'expect': {'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'sources': ['policy_size_exchange_twoway.md'], 'answer_any': [['miễn phí', '2 chiều', 'tận nhà']], 'answer_not': ['mất 50.000']},
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'chi phí vận chuyển đổi size'}}]},
                        {'say': "Dạ lần đổi size đầu tiên của mỗi đơn được hỗ trợ miễn phí vận chuyển 2 chiều tận nhà ạ [{{last_tool.results.0.citation_id}}]."}
                    ]
                },
                {
                    'user': f"<chờ lời khách: mở đổi size cho đơn {ext_oid}>",
                    'expect': {'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_order_action_reason', 'order_action': {'order_id': ext_oid, 'action_type': 'exchange'}, 'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'đổi']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'exchange'}}]},
                        {'say': f"Dạ em đã mở biểu mẫu đổi hàng cho đơn {ext_oid} rồi ạ, anh/chị chọn size mới trên biểu mẫu nhé."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [b1, b2, b3, b4]


class T08HoiTonKhoRoiHoiSize(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t08_hoi_ton_kho_roi_hoi_size', 'T08', 12, description='Hỏi tồn kho biến thể rồi hỏi tư vấn size (2 lượt)')

    def select(self, view: Any) -> list[Any]:
        return list(view.catalog.products.values())[:10]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t08_{case_index:03d}_{self.template_id}"
        pid = slot['id']
        pname = slot['name']
        cust_id = list(view.customers.keys())[case_index % len(view.customers)] if view else 'SIM-C-5001'
        b1 = Brief(brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_mua_sam", intent="hoi_ton_kho_luot_1", must_include=[pname], length="ngắn")
        b2 = Brief(brief_id=f"brf_{cid}_t2", case_id=cid, turn=2, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_mua_sam", intent="hoi_tu_van_size_luot_2", must_include=["size"], length="ngắn")
        case = {
            'id': cid, 'category': 't08', 'title': f'Tồn kho rồi hỏi size {pid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T08', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T08 stock then size {pid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi tồn kho {pname}>",
                    'expect': {'tools_called': ['get_product'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'answer_any': [['sản phẩm', 'biến thể', 'kho']], 'answer_not': ['[KB:']},
                    'fake_model': [
                        {'call': [{'name': 'get_product', 'arguments': {'product_id': pid}}]},
                        {'say': f"Dạ sản phẩm {pname} ({pid}) hiện đang có các size và màu sẵn trong kho ạ."}
                    ]
                },
                {
                    'user': "<chờ lời khách: 65kg mặc size nào vừa>",
                    'expect': {'tools_not_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'answer_any': [['size', 'M', 'L']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'say': f"Dạ với cân nặng 65kg, anh/chị mặc size M sẽ vừa vặn, hoặc size L nếu thích mặc rộng rãi thoải mái nhé ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [b1, b2]


class T08TraCuuGiaoHangRoiHoiDongKiem(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t08_tra_cuu_giao_hang_roi_hoi_dong_kiem', 'T08', 12, description='Tra cứu vận đơn giao hàng rồi hỏi chính sách đồng kiểm (2 lượt)')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['shipping'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t08_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('delivery_inspection.md', 'đồng kiểm') if view else {
            'source_key': 'delivery_inspection.md', 'title': 'Chính sách đồng kiểm khi nhận hàng',
            'chunk': 'Khách hàng được quyền kiểm tra ngoại quan kiện hàng trước khi thanh toán cho shipper.'
        }
        b1 = Brief(brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_hoi_tien_trinh", intent="tra_cuu_van_don_luot_1", must_include=[ext_oid], length="ngắn")
        b2 = Brief(brief_id=f"brf_{cid}_t2", case_id=cid, turn=2, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_hoi_tien_trinh", intent="hoi_chinh_sach_dong_kiem_luot_2", must_include=["đồng kiểm"], length="ngắn")
        case = {
            'id': cid, 'category': 't08', 'title': f'Tra vận chuyển rồi hỏi đồng kiểm {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T08', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T08 tracking then inspection {ext_oid}', 'vn_context': ['dong_kiem']},
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: tra cứu vận đơn {ext_oid}>",
                    'expect': {'tools_called': ['track_shipment'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['đang vận chuyển', 'vận đơn']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'track_shipment', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ kiện hàng {ext_oid} đang vận chuyển giao đến cho anh/chị ạ."}
                    ]
                },
                {
                    'user': "<chờ lời khách: nhận hàng có được đồng kiểm không>",
                    'expect': {'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'sources': ['delivery_inspection.md'], 'answer_any': [['đồng kiểm', 'kiểm tra ngoại quan']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'chính sách đồng kiểm hàng trước khi nhận'}}]},
                        {'say': "Dạ quý khách được kiểm tra ngoại quan kiện hàng trước khi thanh toán cho bưu tá ạ [{{last_tool.results.0.citation_id}}]."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'shipping'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [b1, b2]


class T08HoiBaoHanhRoiMoDoi(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t08_hoi_bao_hanh_roi_mo_doi', 'T08', 12, description='Hỏi chính sách bảo hành rồi mở đổi hàng lỗi (2 lượt)')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_16_to_90)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t08_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        curr_var = slot.get('variant') or 'Trắng · Size L'
        k_chunk = view.get_knowledge_chunk('policy_warranty_exchange_1to1.md', '90 ngày') if view else {
            'source_key': 'policy_warranty_exchange_1to1.md', 'title': 'Chính sách bảo hành, đổi mới 1-1 tận nhà',
            'chunk': 'Thời hạn bảo hành đổi mới tiêu chuẩn là **90 ngày kể từ ngày giao hàng** đối với lỗi do nhà sản xuất.'
        }
        b1 = Brief(brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_hoi_bao_hanh", intent="hoi_chinh_sach_bao_hanh_luot_1", must_include=["bảo hành"], length="ngắn")
        b2 = Brief(brief_id=f"brf_{cid}_t2", case_id=cid, turn=2, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_hoi_bao_hanh", intent="mo_doi_bao_hanh_don_cu_the_luot_2", must_include=[ext_oid], length="ngắn")
        case = {
            'id': cid, 'category': 't08', 'title': f'Hỏi bảo hành rồi mở đổi {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T08', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T08 warranty then exchange {ext_oid}', 'vn_context': ['hang_loi']},
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi thời hạn bảo hành>",
                    'expect': {'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'sources': ['policy_warranty_exchange_1to1.md'], 'answer_all': ['90 ngày'], 'answer_any': [['bảo hành', 'đổi mới']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'thời hạn bảo hành 90 ngày'}}]},
                        {'say': "Dạ chính sách bảo hành đổi mới 1-1 là 90 ngày cho lỗi nhà sản xuất ạ [{{last_tool.results.0.citation_id}}]."}
                    ]
                },
                {
                    'user': f"<chờ lời khách: vậy đơn {ext_oid} bị bung chỉ hỗ trợ đổi giúp mình>",
                    'expect': {'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_order_action_reason', 'order_action': {'order_id': ext_oid, 'action_type': 'exchange'}, 'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'bảo hành']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'exchange'}}]},
                        {'say': f"Dạ em đã mở biểu mẫu bảo hành đổi mới cho đơn {ext_oid} rồi ạ, anh/chị xác nhận trên biểu mẫu giúp em nhé."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [b1, b2]


class T08HaiDonChonMotDon(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t08_hai_don_chon_mot_don', 'T08', 12, description='Khách có 2 đơn, liệt kê rồi chọn 1 đơn để tra cứu (2 lượt)')

    def select(self, view: Any) -> list[Any]:
        return [c for c in view.customers.values() if c['order_count'] == 2]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t08_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        ords = view.customer_orders[cust_id] if view else []
        ord1 = ords[0] if ords else {'external_order_id': 'SIM-O-50006', 'status': 'delivered'}
        ext_oid = ord1['external_order_id']
        b1 = Brief(brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_chon_don", intent="liet_ke_cac_don_luot_1", must_include=["đơn hàng"], length="ngắn")
        b2 = Brief(brief_id=f"brf_{cid}_t2", case_id=cid, turn=2, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_chon_don", intent="chon_don_de_tra_cuu_luot_2", must_include=[ext_oid], length="ngắn")
        case = {
            'id': cid, 'category': 't08', 'title': f'Chọn 1 trong 2 đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T08', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T08 pick 1 of 2 orders {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': "<chờ lời khách: xem danh sách đơn>",
                    'expect': {'tools_called': ['list_orders'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'answer_any': [['danh sách', 'đơn hàng']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'list_orders', 'arguments': {}}]},
                        {'say': "Dạ em gửi danh sách các đơn hàng của anh/chị trên hệ thống rồi ạ."}
                    ]
                },
                {
                    'user': f"<chờ lời khách: kiểm tra chi tiết đơn {ext_oid}>",
                    'expect': {'tools_called': ['get_order'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['đơn hàng', 'trạng thái']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} của anh/chị hiện đang ở trạng thái {ord1['status']} ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: ord1['status']}, 'rows': {'order_action_requests': 0}}
        }
        return case, [b1, b2]


class T08KiemTraTrangThaiVaPhiShip(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t08_kiem_tra_trang_thai_va_phi_ship', 'T08', 6, description='Tra cứu trạng thái đơn rồi hỏi chi tiết thanh toán / phí ship (2 lượt)')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['delivered'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t08_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        b1 = Brief(brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_tra_don", intent="tra_cuu_don_luot_1", must_include=[ext_oid], length="ngắn")
        b2 = Brief(brief_id=f"brf_{cid}_t2", case_id=cid, turn=2, suite=self.suite, template=self.template_id, style=style,
                   persona="khách_hàng_tra_don", intent="hoi_thanh_toan_luot_2", must_include=["thanh toán"], length="ngắn")
        case = {
            'id': cid, 'category': 't08', 'title': f'Trạng thái và thanh toán {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T08', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T08 status then payment {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: tra cứu đơn {ext_oid}>",
                    'expect': {'tools_called': ['get_order'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['đã giao', 'giao thành công']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} đã giao thành công rồi ạ."}
                    ]
                },
                {
                    'user': "<chờ lời khách: đơn này thanh toán phương thức gì>",
                    'expect': {'tools_not_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False, 'answer_any': [['thanh toán', 'COD', 'chuyển khoản']], 'answer_not': ['chưa có thông tin']},
                    'fake_model': [
                        {'say': f"Dạ đơn hàng {ext_oid} sử dụng phương thức thanh toán {slot.get('payment_method') or 'COD'} ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [b1, b2]
