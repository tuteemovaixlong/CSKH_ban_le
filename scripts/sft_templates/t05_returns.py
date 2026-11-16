"""Templates for Suite T05: Trả hàng và hoàn tiền (100 ca).

Covers:
- Trả hàng trong 7 ngày (mở biểu mẫu choose_order_action_reason: return)
- Quá 7 ngày còn bảo hành (gợi ý đổi 1-1 nếu lỗi)
- Giao sai mẫu lỗi shop (miễn phí ship chiều trả)
- Trả đơn chưa giao (chưa nhận hàng không mở trả)
- Đơn đã có yêu cầu mở
- Hoàn tiền COD về đâu (tài khoản ngân hàng)
- Khách nói trả nhưng thực chất muốn đổi size
- Trả hàng khi đã quá hạn bảo hành (> 90 ngày)
- Phí ship khi trả hàng
- Trả hàng vì lý do cá nhân (đổi ý trong 7 ngày)
"""
from __future__ import annotations

import random
from typing import Any

from .base import BaseTemplate, Brief


class T05TraTrong7Ngay(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t05_tra_trong_7_ngay', 'T05', 10, description='Trả hàng trong vòng 7 ngày mở biểu mẫu trả hàng')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t05_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_muon_tra_hang", intent="yeu_cau_tra_hang_trong_7_ngay",
            must_include=[ext_oid], must_not_include=["choose_order_action_reason", "biểu mẫu"], length="ngắn",
            notes=f"Khách yêu cầu trả hàng đơn {ext_oid} vừa nhận 2-3 hôm",
        )
        case = {
            'id': cid, 'category': 't05', 'title': f'Mở biểu mẫu trả hàng trong 7 ngày {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T05', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T05 return within 7 days {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: yêu cầu trả hàng đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_order_action_reason',
                        'order_action': {'order_id': ext_oid, 'action_type': 'return'}, 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'trả hàng', 'lý do']], 'answer_not': ['quá hạn trả', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'return'}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} hiện vẫn trong thời hạn 7 ngày trả hàng ạ. Em đã mở biểu mẫu trả hàng trên màn hình, anh/chị vui lòng chọn lý do và xác nhận giúp em nhé."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T05Qua7NgayConBaoHanh(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t05_qua_7_ngay_con_bao_hanh', 'T05', 10, description='Trả hàng quá 7 ngày nhưng còn bảo hành: từ chối trả, gợi ý đổi 1-1')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_8_to_15)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t05_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_tra_hang_muon", intent="yeu_cau_tra_hang_qua_7_ngay",
            must_include=[ext_oid], must_not_include=["hết hạn trả hàng", "bảo hành 1-1"], length="vừa",
            notes=f"Khách muốn trả lại đơn {ext_oid} đã nhận hơn 1 tuần",
        )
        case = {
            'id': cid, 'category': 't05', 'title': f'Trả hàng quá 7 ngày đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T05', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T05 return expired but in warranty {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: muốn trả hàng đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['quá thời hạn', 'hết hạn', '7 ngày']], 'answer_not': ['mở biểu mẫu trả hàng thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'return'}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} đã hết hạn 7 ngày trả hàng hoàn tiền rồi ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T05GiaoSaiMauLoiShop(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t05_giao_sai_mau_loi_shop', 'T05', 10, description='Khách nhận sai màu do lỗi shop: hướng dẫn đổi trả miễn phí ship')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t05_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_buc_boi_giao_sai", intent="khieu_nai_giao_sai_mau",
            must_include=[ext_oid, "giao sai"], must_not_include=["choose_order_action_reason"], length="vừa",
            notes=f"Khách khiếu nại đơn {ext_oid} đặt màu đen nhưng nhận màu trắng",
        )
        case = {
            'id': cid, 'category': 't05', 'title': f'Giao sai mẫu đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T05', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T05 wrong item delivered {ext_oid}', 'vn_context': ['giao_sai']},
            'turns': [
                {
                    'user': f"<chờ lời khách: khiếu nại giao sai đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_order_action_reason',
                        'order_action': {'order_id': ext_oid, 'action_type': 'return'}, 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'giao sai', 'trả hàng']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'return'}}]},
                        {'say': f"Dạ shop rất xin lỗi anh/chị vì sự cố giao sai mẫu cho đơn {ext_oid}. Em đã mở biểu mẫu trả hàng trên màn hình để anh/chị thao tác nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T05TraDonChuaGiao(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t05_tra_don_chua_giao', 'T05', 10, description='Khách đòi trả hàng đơn chưa giao (shipping/pending)')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['shipping'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t05_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_nham_lan", intent="doi_tra_don_dang_giao",
            must_include=[ext_oid], must_not_include=["chưa nhận được hàng"], length="ngắn",
            notes=f"Khách bảo 'cho tôi trả đơn {ext_oid}' khi đơn chưa giao đến",
        )
        case = {
            'id': cid, 'category': 't05', 'title': f'Đòi trả đơn chưa giao {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T05', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T05 return undelivered order {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: đòi trả đơn chưa nhận {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['đang giao', 'chưa nhận', 'không thể trả']], 'answer_not': ['mở biểu mẫu trả hàng thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'return'}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} hiện đang trong quá trình vận chuyển và anh/chị chưa nhận hàng nên chưa thể thực hiện thủ tục trả hàng ạ. Khi shipper liên hệ giao hàng, anh/chị có thể từ chối nhận nếu không còn nhu cầu nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'shipping'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T05DaCoYeuCauMo(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t05_da_co_yeu_cau_mo', 'T05', 10, description='Khách yêu cầu trả hàng đơn đã có yêu cầu đang mở')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t05_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_lai_yeu_cau", intent="yeu_cau_tra_don_da_gui_yeu_cau",
            must_include=[ext_oid], must_not_include=["open_request_exists"], length="ngắn",
            notes=f"Khách hỏi lại việc trả hàng đơn {ext_oid}",
        )
        case = {
            'id': cid, 'category': 't05', 'title': f'Yêu cầu trả đơn đã mở {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T05', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T05 open request exists {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: yêu cầu trả hàng đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_order_action_reason',
                        'order_action': {'order_id': ext_oid, 'action_type': 'return'}, 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'trả hàng', 'yêu cầu']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'return'}}]},
                        {'say': f"Dạ em đã mở biểu mẫu trả hàng cho đơn {ext_oid} rồi ạ, anh/chị vui lòng kiểm tra và hoàn tất trên biểu mẫu giúp em nhé."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T05HoanTienCODVeDau(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t05_hoan_tien_cod_ve_dau', 'T05', 10, description='Khách trả hàng hỏi tiền COD đã trả thì nhận lại bằng cách nào')

    def select(self, view: Any) -> list[Any]:
        # COD delivered orders
        cod_ords = [o for o in view.delivered_within_7 if o.get('payment_method') == 'cod']
        return cod_ords or view.delivered_within_7

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t05_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_phuong_thuc_hoan", intent="hoi_phuong_thuc_hoan_tien_cod",
            must_include=[ext_oid], must_not_include=["chuyển khoản ngân hàng", "[KB:"], length="vừa",
            notes=f"Khách hỏi đơn {ext_oid} trả tiền mặt cho shipper thì khi trả hàng shop trả tiền vào đâu",
        )
        case = {
            'id': cid, 'category': 't05', 'title': f'Hoàn tiền COD đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T05', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T05 COD refund method {ext_oid}', 'vn_context': ['cod', 'hoan_vi_ngan_hang']},
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi tiền hoàn COD đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['tài khoản', 'ngân hàng', 'chuyển khoản', 'STK']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ với đơn hàng {ext_oid} thanh toán COD khi nhận hàng, sau khi shop nhận lại sản phẩm và kiểm tra hợp lệ, tiền hoàn sẽ được chuyển khoản trực tiếp vào tài khoản ngân hàng của anh/chị ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T05KhachNoiTraNhungMuonDoi(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t05_khach_noi_tra_nhung_muon_doi', 'T05', 10, description='Khách nói "trả hàng" nhưng thực chất muốn lấy size khác: hướng dẫn đổi size')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t05_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_dung_nham_tu", intent="noi_tra_nhung_muon_doi_size",
            must_include=[ext_oid], must_not_include=["chính sách đổi size 15 ngày"], length="vừa",
            notes=f"Khách bảo 'cho mình trả đơn {ext_oid} để lấy cái size lớn hơn nhé'",
        )
        k_chunk = view.get_knowledge_chunk('policy_size_exchange_twoway.md', '15 ngày') if view else {
            'source_key': 'policy_size_exchange_twoway.md', 'title': 'Chính sách đổi size, đổi màu 2 chiều tận nhà',
            'chunk': 'Khách hàng được hỗ trợ đổi size hoặc đổi màu cho cùng một sản phẩm trong vòng **15 ngày kể từ ngày nhận hàng**.'
        }
        case = {
            'id': cid, 'category': 't05', 'title': f'Nói trả nhưng muốn đổi size {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T05', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T05 return intent is exchange {ext_oid}', 'vn_context': ['doi_size_thoi_trang']},
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: muốn trả hàng lấy size khác đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'sources': ['policy_size_exchange_twoway.md'],
                        'answer_all': [ext_oid], 'answer_any': [['đổi size', 'đổi hàng', '15 ngày']], 'answer_not': ['đã hủy thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}, {'name': 'search_knowledge', 'arguments': {'query': 'chính sách đổi size 2 chiều tận nhà'}}]},
                        {'say': f"Dạ nếu anh/chị muốn lấy size khác cho đơn {ext_oid}, shop có hỗ trợ chính sách đổi size 2 chiều tận nhà trong 15 ngày ạ [{{{{last_tool.results.0.citation_id}}}}]. Anh/chị chỉ cần yêu cầu đổi size thì shipper sẽ mang size mới tới tận nơi cho mình nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T05TraHangHetHanBaoHanh(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t05_tra_hang_het_han_bao_hanh', 'T05', 10, description='Trả hàng đơn đã quá 90 ngày: cả trả hàng và bảo hành đều hết hạn')

    def select(self, view: Any) -> list[Any]:
        # Over 90 days order, e.g. ST-512
        return view.delivered_over_90 or [o for o in view.delivered_16_to_90 if o['external_order_id'] == 'SIM-O-ST-512'] or view.orders_by_status['delivered']

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t05_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_muon_tra_don_rat_cu", intent="doi_tra_don_qua_90_ngay",
            must_include=[ext_oid], must_not_include=["hết hạn trả hàng và bảo hành"], length="vừa",
            notes=f"Khách mua từ mấy tháng trước đòi trả lại đơn {ext_oid}",
        )
        case = {
            'id': cid, 'category': 't05', 'title': f'Trả hàng hết hạn bảo hành {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T05', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T05 return warranty expired {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: đòi trả đơn cũ {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['hết hạn', 'quá thời hạn', 'không thể hỗ trợ']], 'answer_not': ['mở biểu mẫu trả hàng thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'return'}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} đã được giao từ lâu và đã quá cả thời hạn trả hàng (7 ngày) lẫn thời hạn bảo hành (90 ngày) ạ. Rất tiếc shop không thể hỗ trợ đổi trả đơn hàng này được nữa, mong anh/chị thông cảm ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T05TraHangPhiShip(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t05_tra_hang_phi_ship', 'T05', 10, description='Khách hỏi chi phí vận chuyển khi trả hàng hoàn tiền')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t05_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_tinh_toan_chi_phi", intent="hoi_phi_ship_tra_hang_don",
            must_include=[ext_oid], must_not_include=["[KB:"], length="ngắn",
            notes=f"Khách hỏi trả đơn {ext_oid} thì ai trả tiền gửi hàng về",
        )
        k_chunk = view.get_knowledge_chunk('shipping_fees.md', 'đổi') if view else {
            'source_key': 'shipping_fees.md', 'title': 'Phí vận chuyển (phí ship)',
            'chunk': 'Đối với trường hợp đổi size hoặc đổi hàng do lỗi shop, shop hỗ trợ miễn phí vận chuyển 2 chiều. Trường hợp trả hàng theo nhu cầu cá nhân, khách hàng chịu phí ship chiều gửi về theo quy định.'
        }
        case = {
            'id': cid, 'category': 't05', 'title': f'Phí ship trả hàng đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T05', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T05 return shipping fee {ext_oid}', 'vn_context': []},
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi phí ship trả hàng đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'sources': ['shipping_fees.md'],
                        'answer_all': [ext_oid], 'answer_any': [['phí ship', 'lỗi từ shop', 'chiều gửi']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}, {'name': 'search_knowledge', 'arguments': {'query': 'biểu phí vận chuyển đổi trả hàng'}}]},
                        {'say': f"Dạ với đơn hàng {ext_oid}, theo chính sách của shop [{{{{last_tool.results.0.citation_id}}}}], nếu trả hàng do lỗi từ shop thì miễn phí ship, còn trả vì lý do cá nhân thì quý khách thanh toán phí gửi hàng về kho giúp shop nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T05TraHangLyDoCaNhan(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t05_tra_hang_ly_do_ca_nhan', 'T05', 10, description='Khách đổi ý không thích nữa, muốn trả hàng trong 7 ngày')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t05_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_doi_y_khong_thich", intent="tra_hang_ly_do_ca_nhan_trong_han",
            must_include=[ext_oid], must_not_include=["choose_order_action_reason"], length="vừa",
            notes=f"Khách nhận đơn {ext_oid} thấy không hợp gu nên muốn gửi trả lại",
        )
        case = {
            'id': cid, 'category': 't05', 'title': f'Trả hàng lý do cá nhân {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T05', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T05 return personal reason {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: không ưng muốn trả hàng {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_order_action_reason',
                        'order_action': {'order_id': ext_oid, 'action_type': 'return'}, 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'trả hàng', 'chọn lý do']], 'answer_not': ['không được trả'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'return'}}]},
                        {'say': f"Dạ đơn {ext_oid} vẫn đang trong thời hạn 7 ngày nên anh/chị hoàn toàn có thể yêu cầu trả hàng ạ. Em đã mở biểu mẫu trên màn hình, anh/chị chọn lý do và xác nhận giúp em nhé."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]
