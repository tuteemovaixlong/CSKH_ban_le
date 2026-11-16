"""Templates for Suite T04: Hủy đơn hàng (100 ca).

Covers:
- Hủy đơn pending mở biểu mẫu (prepare_order_action)
- Hủy đơn đang giao (shipping): giải thích không tự hủy, gợi ý từ chối nhận
- Hủy đơn đã giao (delivered): chuyển hướng sang trả hàng
- Hủy đơn đã hủy (cancelled): thông báo đơn đã hủy
- Hủy đơn không nêu mã khi có nhiều đơn (hỏi lại, không prepare_order_action)
- Bỏ một món trong đơn (không hỗ trợ hủy riêng món)
- Gõ "xác nhận" ở lượt sau trong chat (tin nhắn chat không hủy được)
- Đổi ý muốn hủy đơn pending
- Hủy đơn chưa xác nhận
- Hỏi tiến trình rồi hủy đơn pending (2 lượt)
"""
from __future__ import annotations

import random
from typing import Any

from .base import BaseTemplate, Brief


class T04HuyPendingMoBieuMau(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t04_huy_pending_mo_bieu_mau', 'T04', 10, description='Hủy đơn pending mở biểu mẫu chọn lý do')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['pending'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t04_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_muon_huy_don", intent="yeu_cau_huy_don_pending",
            must_include=[ext_oid], must_not_include=["choose_cancel_reason", "biểu mẫu"], length="ngắn",
            notes=f"Khách yêu cầu hủy đơn hàng {ext_oid} vừa đặt",
        )
        case = {
            'id': cid, 'category': 't04', 'title': f'Mở biểu mẫu hủy đơn pending {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T04', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T04 cancel pending {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: yêu cầu hủy đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_cancel_reason',
                        'order_action': {'order_id': ext_oid, 'action_type': 'cancel'}, 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'lý do', 'xác nhận']], 'answer_not': ['đã hủy thành công', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'cancel'}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} hiện đang ở trạng thái chờ xử lý nên đủ điều kiện hủy ạ. Em đã mở biểu mẫu hủy đơn trên màn hình, anh/chị vui lòng chọn lý do và bấm xác nhận trên biểu mẫu nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'pending'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T04HuyDangGiaoTuChoiNhan(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t04_huy_dang_giao_tu_choi_nhan', 'T04', 10, description='Hủy đơn đang giao: giải thích không tự hủy, gợi ý từ chối nhận')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['shipping'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t04_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_muon_huy_don_dang_giao", intent="yeu_cau_huy_don_dang_van_chuyen",
            must_include=[ext_oid], must_not_include=["từ chối nhận", "shipping"], length="vừa",
            notes=f"Khách đổi ý muốn hủy đơn {ext_oid} khi đơn đang giao",
        )
        case = {
            'id': cid, 'category': 't04', 'title': f'Hủy đơn shipping {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T04', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T04 cancel shipping {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: muốn hủy đơn đang giao {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['đang vận chuyển', 'đang giao', 'từ chối nhận']], 'answer_not': ['đã hủy thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'cancel'}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} đã được bàn giao cho đơn vị vận chuyển và đang trên đường giao nên không thể hủy trên hệ thống được nữa ạ. Khi shipper liên hệ giao hàng, anh/chị có thể từ chối nhận hàng giúp shop nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'shipping'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T04HuyDaGiaoChuyenTra(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t04_huy_da_giao_chuyen_tra', 'T04', 10, description='Khách đòi hủy đơn đã giao thành công: chuyển sang trả hàng')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['delivered'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t04_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_dung_tu_huy_sau_khi_nhan", intent="doi_huy_don_da_nhan",
            must_include=[ext_oid], must_not_include=["trả hàng", "delivered"], length="ngắn",
            notes=f"Khách nhắn 'hủy đơn {ext_oid} cho tôi' dù đã nhận hàng",
        )
        case = {
            'id': cid, 'category': 't04', 'title': f'Hủy đơn đã giao {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T04', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T04 cancel delivered {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: đòi hủy đơn đã nhận {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['đã giao', 'trả hàng', 'không thể hủy']], 'answer_not': ['đã hủy thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'cancel'}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} đã được giao thành công nên không thể hủy đơn được nữa ạ. Nếu anh/chị không có nhu cầu sử dụng, anh/chị có thể yêu cầu trả hàng trong vòng 7 ngày nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T04HuyDonDaHuy(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t04_huy_don_da_huy', 'T04', 10, description='Khách yêu cầu hủy một đơn vốn đã ở trạng thái hủy')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['cancelled'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t04_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_quen_don_da_huy", intent="yeu_cau_huy_lai_don_da_huy",
            must_include=[ext_oid], must_not_include=["đã được hủy trước đó"], length="ngắn",
            notes=f"Khách yêu cầu hủy đơn {ext_oid} mà không nhớ đơn đã hủy",
        )
        case = {
            'id': cid, 'category': 't04', 'title': f'Hủy đơn đã hủy {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T04', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T04 cancel already cancelled {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: yêu cầu hủy đơn đã hủy {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['đã hủy', 'trước đó', 'cancelled']], 'answer_not': ['mở biểu mẫu'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'cancel'}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} của anh/chị đã được hủy trước đó trên hệ thống rồi ạ, anh/chị không cần thao tác gì thêm nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'cancelled'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T04HuyKhongNeuMaNhieuDon(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t04_huy_khong_neu_ma_nhieu_don', 'T04', 10, description='Khách nhiều đơn yêu cầu hủy nhưng không nêu mã: hỏi lại, không prepare')

    def select(self, view: Any) -> list[Any]:
        return [c for c in view.customers.values() if c['order_count'] >= 2]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t04_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_muon_huy_khong_neu_ma", intent="yeu_cau_huy_chung_chung",
            must_include=["hủy đơn"], must_not_include=["SIM-O-"], length="ngắn",
            notes="Khách nói 'hủy đơn hàng cho mình với' nhưng không cho biết mã đơn",
        )
        case = {
            'id': cid, 'category': 't04', 'title': f'Yêu cầu hủy không nêu mã {cust_id}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T04', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T04 cancel ambiguous for {cust_id}', 'vn_context': []},
            'turns': [
                {
                    'user': "<chờ lời khách: yêu cầu hủy đơn không nêu mã>",
                    'expect': {
                        'tools_called': ['list_orders'], 'tools_not_called': ['prepare_order_action'],
                        'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'answer_any': [['mã đơn', 'nhiều đơn', 'đơn nào']], 'answer_not': ['đã hủy thành công', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'list_orders', 'arguments': {}}]},
                        {'say': f"Dạ em thấy anh/chị có nhiều đơn hàng trên hệ thống. Anh/chị vui lòng cung cấp mã đơn hàng cụ thể muốn hủy để em kiểm tra và hỗ trợ nhé ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T04BoMotMon(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t04_bo_mot_mon', 'T04', 10, description='Khách muốn bỏ 1 món trong đơn: giải thích không hủy lẻ món')

    def select(self, view: Any) -> list[Any]:
        # Orders with multiple items
        multi = [o for o in view.orders.values() if len(o.get('items', [])) >= 2]
        return multi or list(view.orders_by_status['pending'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t04_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_muon_bo_mon", intent="yeu_cau_huy_rieng_mot_mon",
            must_include=[ext_oid], must_not_include=["không thể hủy riêng từng món"], length="vừa",
            notes=f"Khách hỏi đơn {ext_oid} muốn hủy bớt 1 món trong đơn được không",
        )
        case = {
            'id': cid, 'category': 't04', 'title': f'Bỏ một món trong đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T04', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T04 cancel single item {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: muốn bỏ 1 món trong đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order'], 'tools_not_called': ['prepare_order_action'],
                        'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['hủy riêng', 'từng món', 'toàn bộ đơn', 'cả đơn']], 'answer_not': ['đã hủy thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ hệ thống hiện không hỗ trợ hủy riêng từng sản phẩm trong cùng một đơn hàng ạ. Nếu muốn thay đổi, anh/chị cần hủy toàn bộ đơn {ext_oid} và đặt lại đơn mới với các sản phẩm mong muốn nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: slot['status']}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T04GoXacNhanLuotSau(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t04_go_xac_nhan_luot_sau', 'T04', 10, description='2 lượt: mở biểu mẫu hủy, lượt sau khách nhắn "xác nhận" trong chat')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['pending'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t04_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        b1 = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_huy_don", intent="yeu_cau_huy_don_luot_1",
            must_include=[ext_oid], must_not_include=["choose_cancel_reason"], length="ngắn",
            notes=f"Lượt 1: Khách yêu cầu hủy đơn {ext_oid}",
        )
        b2 = Brief(
            brief_id=f"brf_{cid}_t2", case_id=cid, turn=2, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_huy_don", intent="nhan_xac_nhan_huy_trong_chat",
            must_include=["xác nhận"], must_not_include=["bấm nút trên biểu mẫu"], length="ngắn",
            earlier_turns=[{'turn': 1, 'intent': 'yeu_cau_huy_don_luot_1', 'assistant': 'đã mở biểu mẫu hủy đơn'}],
            notes="Lượt 2: Sau khi trợ lý mở form, khách chỉ gõ 'xác nhận hủy nhé shop' trong chat thay vì bấm nút",
        )
        case = {
            'id': cid, 'category': 't04', 'title': f'Gõ xác nhận hủy trong chat {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T04', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T04 chat confirmation does not cancel {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: yêu cầu hủy đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_cancel_reason',
                        'order_action': {'order_id': ext_oid, 'action_type': 'cancel'}, 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'chọn lý do']], 'answer_not': ['đã hủy thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'cancel'}}]},
                        {'say': f"Dạ em đã mở biểu mẫu hủy đơn {ext_oid} trên màn hình. Anh/chị vui lòng chọn lý do và nhấn nút xác nhận trên biểu mẫu giúp em nhé."}
                    ]
                },
                {
                    'user': "<chờ lời khách: gõ xác nhận hủy trong chat>",
                    'expect': {
                        'tools_not_called': ['prepare_order_action'], 'max_tool_calls': 0, 'action': 'reply', 'human_support': False,
                        'answer_any': [['bấm nút', 'trên biểu mẫu', 'khung chat không']], 'answer_not': ['đã hủy thành công'],
                    },
                    'fake_model': [
                        {'say': f"Dạ việc nhắn 'xác nhận' trong khung chat sẽ không tự động hủy đơn được ạ. Anh/chị vui lòng bấm trực tiếp nút xác nhận trên biểu mẫu đang mở trên màn hình để hoàn tất nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'pending'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [b1, b2]


class T04HuyPendingDoiY(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t04_huy_pending_doi_y', 'T04', 10, description='Khách đặt nhầm size muốn hủy đơn pending để đặt lại')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['pending'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t04_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_dat_nham", intent="huy_don_do_dat_nham_size",
            must_include=[ext_oid], must_not_include=["choose_cancel_reason"], length="vừa",
            notes=f"Khách bảo đặt nhầm size muốn hủy đơn {ext_oid} để đặt lại",
        )
        case = {
            'id': cid, 'category': 't04', 'title': f'Hủy đơn đặt nhầm size {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T04', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T04 cancel wrong size {ext_oid}', 'vn_context': ['dat_nham']},
            'turns': [
                {
                    'user': f"<chờ lời khách: đặt nhầm muốn hủy đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_cancel_reason',
                        'order_action': {'order_id': ext_oid, 'action_type': 'cancel'}, 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'xác nhận']], 'answer_not': ['đã hủy thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'cancel'}}]},
                        {'say': f"Dạ đơn {ext_oid} vẫn đang chờ xử lý nên anh/chị hoàn toàn có thể hủy để đặt lại ạ. Em đã mở biểu mẫu hủy trên màn hình rồi nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'pending'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T04HuyChuaXacNhanDon(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t04_huy_chua_xac_nhan_don', 'T04', 10, description='Khách nhắc đến đơn chưa rõ ràng: hỏi xác nhận mã đơn')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['pending'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t04_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_huy", intent="hoi_co_huy_duoc_khong",
            must_include=[ext_oid], must_not_include=["choose_cancel_reason"], length="ngắn",
            notes=f"Khách hỏi đơn {ext_oid} của mình có hủy được không",
        )
        case = {
            'id': cid, 'category': 't04', 'title': f'Hỏi khả năng hủy đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T04', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T04 check cancelability {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi đơn {ext_oid} có hủy được không>",
                    'expect': {
                        'tools_called': ['get_order'], 'tools_not_called': ['prepare_order_action'],
                        'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['chờ xử lý', 'hủy được', 'đủ điều kiện']], 'answer_not': ['đã hủy thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn {ext_oid} hiện đang ở trạng thái chờ xử lý (pending) nên hoàn toàn đủ điều kiện hủy ạ. Nếu anh/chị muốn hủy ngay, hãy báo em để em mở biểu mẫu hỗ trợ mình nhé."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'pending'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T04HuySauKhiHoiTienTrinh(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t04_huy_sau_khi_hoi_tien_trinh', 'T04', 10, description='2 lượt: hỏi tiến độ đơn pending rồi quyết định hủy')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['pending'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t04_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        b1 = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_tien_do", intent="hoi_tien_trinh_don_pending",
            must_include=[ext_oid], must_not_include=["hủy đơn"], length="ngắn",
            notes=f"Lượt 1: Khách hỏi đơn {ext_oid} đã làm tới đâu",
        )
        b2 = Brief(
            brief_id=f"brf_{cid}_t2", case_id=cid, turn=2, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_tien_do", intent="quyet_dinh_huy_don_sau_khi_hoi",
            must_include=["hủy đơn"], must_not_include=["choose_cancel_reason"], length="ngắn",
            earlier_turns=[{'turn': 1, 'intent': 'hoi_tien_trinh_don_pending', 'assistant': f'đơn {ext_oid} đang chờ xử lý'}],
            notes="Lượt 2: Khách quyết định hủy đơn luôn",
        )
        case = {
            'id': cid, 'category': 't04', 'title': f'Hỏi tiến trình rồi hủy {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T04', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T04 check progress then cancel {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi tiến trình đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['chờ xử lý', 'pending']], 'answer_not': ['đã hủy thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn {ext_oid} hiện đang ở trạng thái chờ xử lý (pending), shop đang chuẩn bị hàng ạ."}
                    ]
                },
                {
                    'user': "<chờ lời khách: quyết định hủy đơn luôn>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_cancel_reason',
                        'order_action': {'order_id': ext_oid, 'action_type': 'cancel'}, 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'chọn lý do']], 'answer_not': ['đã hủy thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'cancel'}}]},
                        {'say': f"Dạ em đã mở biểu mẫu hủy đơn {ext_oid} trên màn hình, anh/chị vui lòng chọn lý do và xác nhận giúp em nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'pending'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [b1, b2]
