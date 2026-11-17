"""Templates for Suite T01: Tra cứu đơn hàng (74 ca ở tệp này + 16 ca ở t13_gap_fill.py = 90 ca).

Covers 13 templates:
1. t01_tra_don_pending (5 ca): Tra cứu đơn hàng pending
2. t01_tra_don_shipping (6 ca): Tra cứu đơn hàng shipping
3. t01_tra_don_delivered (5 ca): Tra cứu đơn hàng delivered
4. t01_tra_don_cancelled (5 ca): Tra cứu đơn hàng cancelled
5. t01_liet_ke_don (5 ca): Liệt kê danh sách đơn (list_orders)
6. t01_khong_neu_ma_nhieu_don (6 ca): Khách nhiều đơn không nêu mã (hỏi lại)
7. t01_khong_neu_ma_mot_don (5 ca): Khách đúng 1 đơn không nêu mã
8. t01_van_don_giao_that_bai (8 ca): Vận đơn giao thất bại / đang giao (track_shipment)
9. t01_giao_tre_duoi_48h (6 ca): Giao trễ <= 48h, tra chính sách voucher có trích dẫn
10. t01_giao_tre_tren_48h (7 ca): Giao trễ > 48h, đủ điều kiện voucher có trích dẫn
11. t01_don_khong_thuoc_khach (5 ca): Tra cứu đơn người khác không thuộc tài khoản
12. t01_hoi_dia_chi_sdt_day_du (5 ca): Khách hỏi SĐT/địa chỉ nhận hàng đầy đủ (PII đã che)
13. t01_trang_thai_hoan_tien (6 ca): Trạng thái hoàn tiền (processing, failed, completed)
"""
from __future__ import annotations

import random
from typing import Any

from .base import BaseTemplate, Brief


class T01TraDonPending(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_tra_don_pending', 'T01', 5, description='Tra cứu đơn hàng đang chờ xử lý (pending)')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['pending'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        prod_name = slot.get('name') or 'Sản phẩm'
        intents = [
            "tra_cuu_tien_do_don_pending",
            "hoi_xac_nhan_don_chua_xuat_kho",
            "kiem_tra_trang_thai_don_moi_dat",
            "hoi_khi_nao_dong_goi_xong",
            "thac_mac_don_cho_xu_ly",
            "kiem_tra_shop_da_nhan_don_chua",
            "hoi_tien_trinh_chuan_bi_hang",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_chờ_xử_lý",
            intent=intent,
            must_include=[ext_oid],
            may_include=[prod_name],
            must_not_include=["chờ xử lý", "pending", "đang chuẩn bị hàng"],
            length="vừa",
            notes="Khách hỏi đơn hàng mới đặt đang ở trạng thái nào",
        )
        case = {
            'id': cid,
            'category': 't01',
            'title': f'Tra cứu đơn {ext_oid} trạng thái pending',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T01',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T01 pending: tra cứu {ext_oid}',
                'slot_key': ext_oid,
                'intent': intent,
                'vn_context': [],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: tra cứu đơn pending {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_all': [ext_oid],
                        'answer_any': [['chờ xử lý', 'đang xử lý', 'pending']],
                        'answer_not': ['đã giao', 'đã hủy', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} của anh/chị hiện đang ở trạng thái chờ xử lý (pending), shop đang chuẩn bị hàng để gửi cho đơn vị vận chuyển ạ."}
                    ]
                }
            ],
            'final_state': {
                'orders': {ext_oid: 'pending'},
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T01TraDonShipping(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_tra_don_shipping', 'T01', 6, description='Tra cứu đơn hàng đang vận chuyển (shipping)')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['shipping'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        intents = [
            "tra_cuu_tien_do_don_shipping",
            "hoi_kien_hang_dang_o_dau",
            "kiem_tra_don_da_giao_buu_ta_chua",
            "thac_mac_khi_nao_buu_ta_phat",
            "hoi_tien_do_van_chuyen_don",
            "kiem_tra_trang_thai_giao_hang",
            "hoi_don_hang_dang_di_chuyen_chua",
            "xac_nhan_don_hang_dang_giao",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hỏi_giao_hang",
            intent=intent,
            must_include=[ext_oid],
            must_not_include=["đang giao", "shipping", "vận chuyển"],
            length="vừa",
            notes="Khách hỏi đơn hàng đã gửi đi chưa",
        )
        case = {
            'id': cid,
            'category': 't01',
            'title': f'Tra cứu đơn {ext_oid} trạng thái shipping',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T01',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T01 shipping: tra cứu {ext_oid}',
                'slot_key': ext_oid,
                'intent': intent,
                'vn_context': [],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: tra cứu đơn shipping {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_all': [ext_oid],
                        'answer_any': [['đang giao', 'đang vận chuyển', 'shipping']],
                        'answer_not': ['đã giao thành công', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} của anh/chị đã được gửi cho đơn vị vận chuyển và đang trong quá trình giao hàng (shipping) ạ."}
                    ]
                }
            ],
            'final_state': {
                'orders': {ext_oid: 'shipping'},
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T01TraDonDelivered(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_tra_don_delivered', 'T01', 5, description='Tra cứu đơn hàng đã giao thành công (delivered)')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['delivered'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        intents = [
            "tra_cuu_don_da_giao",
            "xac_nhan_trang_thai_da_nhan_hang",
            "hoi_thong_tin_don_da_giao_thanh_cong",
            "kiem_tra_ngay_gio_nhan_kien",
            "hoi_thoi_gian_giao_don_hang",
            "check_lich_su_don_da_phat",
            "xem_lai_trang_thai_don_delivered",
            "hoi_thong_tin_don_da_hoan_tat",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_kiem_tra_lich_su",
            intent=intent,
            must_include=[ext_oid],
            must_not_include=["giao thành công", "delivered"],
            length="vừa",
            notes="Khách hỏi lại thông tin đơn hàng đã giao",
        )
        case = {
            'id': cid,
            'category': 't01',
            'title': f'Tra cứu đơn {ext_oid} trạng thái delivered',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T01',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T01 delivered: tra cứu {ext_oid}',
                'slot_key': ext_oid,
                'intent': intent,
                'vn_context': [],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: tra cứu đơn delivered {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_all': [ext_oid],
                        'answer_any': [['đã giao', 'giao thành công', 'delivered']],
                        'answer_not': ['đang xử lý', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} của anh/chị đã được giao thành công rồi ạ."}
                    ]
                }
            ],
            'final_state': {
                'orders': {ext_oid: 'delivered'},
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T01TraDonCancelled(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_tra_don_cancelled', 'T01', 5, description='Tra cứu đơn hàng đã hủy (cancelled)')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['cancelled'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        intents = [
            "tra_cuu_don_da_huy",
            "xac_nhan_don_hang_da_huy_chua",
            "kiem_tra_trang_thai_huy_don",
            "hoi_thong_tin_don_cancelled",
            "check_lai_don_da_bao_huy",
            "hoi_tien_trinh_sau_khi_huy_don",
            "thac_mac_don_da_huy_tren_app",
            "xem_lai_don_da_huy_thanh_cong",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_don_huy",
            intent=intent,
            must_include=[ext_oid],
            must_not_include=["đã hủy", "cancelled"],
            length="vừa",
            notes="Khách hỏi trạng thái đơn đã hủy",
        )
        case = {
            'id': cid,
            'category': 't01',
            'title': f'Tra cứu đơn {ext_oid} trạng thái cancelled',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T01',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T01 cancelled: tra cứu {ext_oid}',
                'slot_key': ext_oid,
                'intent': intent,
                'vn_context': [],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: tra cứu đơn cancelled {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_all': [ext_oid],
                        'answer_any': [['đã hủy', 'hủy thành công', 'cancelled']],
                        'answer_not': ['đang giao', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} của anh/chị hiện đang ở trạng thái đã hủy (cancelled) ạ."}
                    ]
                }
            ],
            'final_state': {
                'orders': {ext_oid: 'cancelled'},
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T01LietKeDon(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_liet_ke_don', 'T01', 5, description='Khách yêu cầu xem danh sách các đơn đã đặt')

    def select(self, view: Any) -> list[Any]:
        return [c for c in view.customers.values() if c['order_count'] >= 1]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        intents = [
            "liet_ke_danh_sach_don_hang",
            "xem_tat_ca_don_da_dat",
            "hoi_danh_sach_cac_don_gan_day",
            "tra_cuu_toan_bo_don_trong_tai_khoan",
            "check_nhung_don_hang_da_mua",
            "hoi_minh_dang_co_may_don",
            "kiem_tra_tong_so_don_da_dat",
            "liet_ke_lich_su_mua_hang",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_muon_xem_tat_ca_don",
            intent=intent,
            must_include=[],
            must_not_include=["list_orders", "offset", "limit"],
            length="ngắn",
            notes="Khách hỏi xem mình đã đặt những đơn nào",
        )
        case = {
            'id': cid,
            'category': 't01',
            'title': f'Liệt kê đơn hàng của khách {cust_id}',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T01',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T01 list_orders for {cust_id}',
                'slot_key': cust_id,
                'intent': intent,
                'vn_context': [],
            },
            'turns': [
                {
                    'user': "<chờ lời khách: liệt kê các đơn hàng đã đặt>",
                    'expect': {
                        'tools_called': ['list_orders'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_any': [['đơn hàng', 'danh sách đơn']],
                        'answer_not': ['chưa có thông tin', 'lỗi hệ thống'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'list_orders', 'arguments': {}}]},
                        {'say': f"Dạ em đã kiểm tra danh sách đơn hàng của anh/chị trên hệ thống rồi ạ. Dưới đây là các đơn hàng gần nhất của anh/chị ạ."}
                    ]
                }
            ],
            'final_state': {
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T01KhongNeuMaNhieuDon(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_khong_neu_ma_nhieu_don', 'T01', 6, description='Khách có nhiều đơn hỏi tiến độ nhưng không nêu mã')

    def select(self, view: Any) -> list[Any]:
        return [c for c in view.customers.values() if c['order_count'] >= 2]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        intents = [
            "hoi_don_khong_neu_ma_nhieu_don",
            "hoi_tien_do_chung_chung_khi_co_nhieu_don",
            "thac_mac_don_toi_dau_khong_dua_ma",
            "hoi_khi_nao_giao_hang_khong_neu_ma",
            "kiem_tra_trang_thai_chung_chung",
            "hoi_don_hang_cua_minh_sao_roi",
            "check_giup_don_hang_khong_ro_ma",
            "hoi_tinh_hinh_don_hang_noi_chung",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_chung_chung",
            intent=intent,
            must_include=[],
            must_not_include=["SIM-O-"],
            length="ngắn",
            notes="Khách hỏi 'đơn hàng của mình tới đâu rồi' mà không cung cấp mã đơn",
        )
        case = {
            'id': cid,
            'category': 't01',
            'title': f'Khách {cust_id} nhiều đơn không nêu mã',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T01',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T01 ambiguous order query for {cust_id}',
                'slot_key': cust_id,
                'intent': intent,
                'vn_context': [],
            },
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi đơn hàng chung chung không nêu mã>",
                    'expect': {
                        'tools_called': ['list_orders'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_any': [['mã đơn', 'nhiều đơn', 'đơn nào']],
                        'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'list_orders', 'arguments': {}}]},
                        {'say': f"Dạ em thấy anh/chị đang có nhiều đơn hàng trên hệ thống. Anh/chị vui lòng cung cấp mã đơn hàng cụ thể để em kiểm tra tiến độ chính xác nhất giúp mình nhé ạ."}
                    ]
                }
            ],
            'final_state': {
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T01KhongNeuMaMotDon(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_khong_neu_ma_mot_don', 'T01', 5, description='Khách chỉ có đúng 1 đơn hỏi tiến độ không nêu mã')

    def select(self, view: Any) -> list[Any]:
        return [c for c in view.customers.values() if c['order_count'] == 1]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        intents = [
            "hoi_don_khong_neu_ma_mot_don",
            "hoi_tien_do_khi_chi_co_mot_don_duy_nhat",
            "thac_mac_don_cua_minh_da_giao_chua",
            "check_tinh_hinh_don_duy_nhat",
            "hoi_khi_nao_nhan_duoc_kien_hang",
            "tra_cuu_tien_do_don_khong_kem_ma",
            "hoi_hang_da_xuat_kho_chua_mot_don",
            "kiem_tra_don_hang_duy_nhat_cua_khach",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_chi_co_mot_don",
            intent=intent,
            must_include=[],
            must_not_include=["SIM-O-"],
            length="ngắn",
            notes="Khách hỏi 'hàng của mình giao chưa' khi chỉ có 1 đơn",
        )
        case = {
            'id': cid,
            'category': 't01',
            'title': f'Khách {cust_id} có 1 đơn không nêu mã',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T01',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T01 single order lookup for {cust_id}',
                'slot_key': cust_id,
                'intent': intent,
                'vn_context': [],
            },
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi tiến độ đơn hàng duy nhất không nêu mã>",
                    'expect': {
                        'tools_called': ['list_orders'],
                        'max_tool_calls': 2,
                        'action': 'reply',
                        'human_support': False,
                        'answer_any': [['đơn hàng', 'trạng thái']],
                        'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'list_orders', 'arguments': {}}]},
                        {'say': f"Dạ em kiểm tra thấy anh/chị có 1 đơn hàng trên hệ thống, hiện đơn hàng đang được xử lý theo đúng tiến độ ạ."}
                    ]
                }
            ],
            'final_state': {
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T01VanDonGiaoThatBai(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_van_don_giao_that_bai', 'T01', 8, description='Tra cứu vận đơn giao hàng thất bại (track_shipment)')

    def select(self, view: Any) -> list[Any]:
        ords = [o for o in view.orders_by_status['cancelled'] if o['external_order_id'] == 'SIM-O-ST-504']
        return ords or view.orders_by_status['cancelled']

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        intents = [
            "tra_cuu_van_don_that_bai",
            "hoi_ly_do_giao_hang_khong_thanh_cong",
            "thac_mac_van_don_bao_that_bai",
            "kiem_tra_tinh_trang_phat_hang_that_bai",
            "check_hanh_trinh_don_bi_huy_giao",
            "hoi_tai_sao_chua_nhan_duoc_ma_bao_that_bai",
            "kiem_tra_ly_do_buu_ta_khong_giao_duoc",
            "hoi_huong_xu_ly_khi_giao_that_bai",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_van_don",
            intent=intent,
            must_include=[ext_oid],
            must_not_include=["track_shipment"],
            length="vừa",
            notes="Khách hỏi tại sao vận đơn của mình bị báo giao không thành công",
        )
        case = {
            'id': cid,
            'category': 't01',
            'title': f'Tra cứu vận chuyển đơn {ext_oid}',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T01',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T01 track_shipment {ext_oid}',
                'slot_key': ext_oid,
                'intent': intent,
                'vn_context': ['giao_that_bai'],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: tra cứu vận đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['track_shipment'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_all': [ext_oid],
                        'answer_any': [['vận đơn', 'giao hàng', 'vận chuyển']],
                        'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'track_shipment', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ em đã kiểm tra thông tin vận đơn của đơn {ext_oid}. Kiện hàng hiện đang cập nhật trạng thái vận chuyển từ bưu tá ạ."}
                    ]
                }
            ],
            'final_state': {
                'orders': {ext_oid: slot['status']},
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T01GiaoTreDuoi48h(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_giao_tre_duoi_48h', 'T01', 6, description='Đơn giao trễ dưới 48 giờ chưa đạt ngưỡng bồi thường')

    def select(self, view: Any) -> list[Any]:
        return list(view.late_orders_under_48h)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('policy_mega_sale_delay_voucher.md', '48') if view else {
            'source_key': 'policy_mega_sale_delay_voucher.md',
            'title': 'Chính sách bồi thường giao hàng trễ, kể cả mùa Mega Sale',
            'chunk': 'Đơn giao trễ **quá 48 giờ** so với thời hạn giao cam kết thì hệ thống tự lập đề xuất tặng khách **một mã voucher giảm giá 50.000 VNĐ**. Nhân viên cửa hàng duyệt hoặc từ chối đề xuất; mệnh giá cố định, không đổi. Mỗi vận đơn được bồi thường giao trễ tối đa một lần.'
        }
        intents = [
            "hoi_boi_thuong_giao_tre_duoi_48h",
            "thac_mac_don_cham_tien_do_duoi_48h",
            "hoi_voucher_den_bu_giao_tre",
            "khieu_nai_giao_hang_cham_nhan_voucher",
            "kiem_tra_dieu_kien_boi_thuong_duoi_48h",
            "hoi_quy_dinh_tang_voucher_giao_cham",
            "yeu_cau_boi_thuong_tre_don_hang",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_tre_hen",
            intent=intent,
            must_include=[ext_oid],
            must_not_include=["voucher 50k", "bồi thường"],
            length="vừa",
            notes="Khách phàn nàn đơn giao trễ hơn cam kết một chút và hỏi có voucher bồi thường không",
        )
        case = {
            'id': cid,
            'category': 't01',
            'title': f'Tra cứu giao trễ dưới 48h đơn {ext_oid}',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T01',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T01 late delivery < 48h {ext_oid}',
                'slot_key': ext_oid,
                'intent': intent,
                'vn_context': ['giao_cham'],
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi bồi thường đơn trễ {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'],
                        'max_tool_calls': 2,
                        'action': 'reply',
                        'human_support': False,
                        'sources': ['policy_mega_sale_delay_voucher.md'],
                        'answer_all': [ext_oid, '48 giờ'],
                        'answer_any': [['chưa đủ điều kiện', 'quá 48 giờ', 'trên 48 giờ', 'thông cảm']],
                        'answer_not': ['đã cấp voucher', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [
                            {'name': 'get_order', 'arguments': {'order_id': ext_oid}},
                            {'name': 'search_knowledge', 'arguments': {'query': 'chính sách bồi thường giao hàng trễ voucher 48 giờ'}}
                        ]},
                        {'say': f"Dạ đơn hàng {ext_oid} của anh/chị shop rất xin lỗi vì bị trễ trong quá trình giao hàng. Theo chính sách bồi thường của shop [{{{{last_tool.results.0.citation_id}}}}], đơn hàng phải giao trễ quá 48 giờ so với cam kết mới phát sinh đề xuất tặng voucher 50.000 VNĐ. Đơn này hiện trễ chưa quá 48 giờ nên chưa đủ điều kiện nhận voucher bồi thường, rất mong anh/chị thông cảm giúp shop ạ."}
                    ]
                }
            ],
            'final_state': {
                'orders': {ext_oid: slot['status']},
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T01GiaoTreTren48h(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_giao_tre_tren_48h', 'T01', 7, description='Đơn giao trễ trên 48 giờ tra chính sách bồi thường có trích dẫn')

    def select(self, view: Any) -> list[Any]:
        return list(view.late_orders_over_48h) or list(view.late_orders)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('policy_mega_sale_delay_voucher.md', '48') if view else {
            'source_key': 'policy_mega_sale_delay_voucher.md',
            'title': 'Chính sách bồi thường giao hàng trễ, kể cả mùa Mega Sale',
            'chunk': 'Đơn giao trễ **quá 48 giờ** so với thời hạn giao cam kết thì hệ thống tự lập đề xuất tặng khách **một mã voucher giảm giá 50.000 VNĐ**. Nhân viên cửa hàng duyệt hoặc từ chối đề xuất; mệnh giá cố định, không đổi. Mỗi vận đơn được bồi thường giao trễ tối đa một lần.'
        }
        intents = [
            "khieu_nai_tre_tren_48h_nhan_voucher",
            "hoi_chinh_sach_boi_thuong_tre_han",
            "yeu_cau_den_bu_don_hang_giao_qua_cham",
            "thac_mac_voucher_50k_giao_tre",
            "hoi_quy_trinh_duyet_voucher_tre_han",
            "phan_nan_don_cham_tien_do_doi_voucher",
            "kiem_tra_dieu_kien_boi_thuong_don_tre",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_doi_boi_thuong",
            intent=intent,
            must_include=[ext_oid],
            must_not_include=["[KB:", "voucher 50000"],
            length="vừa",
            notes="Khách phàn nàn đơn giao trễ nhiều ngày và yêu cầu đền bù theo chính sách",
        )
        case = {
            'id': cid,
            'category': 't01',
            'title': f'Tra cứu giao trễ trên 48h đơn {ext_oid}',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T01',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T01 late delivery > 48h {ext_oid}',
                'slot_key': ext_oid,
                'intent': intent,
                'vn_context': ['giao_cham', 'voucher'],
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: khiếu nại giao trễ trên 48h đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'],
                        'max_tool_calls': 2,
                        'action': 'reply',
                        'human_support': False,
                        'sources': ['policy_mega_sale_delay_voucher.md'],
                        'answer_all': [ext_oid, '48 giờ'],
                        'answer_any': [['voucher', 'bồi thường', '50.000']],
                        'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [
                            {'name': 'get_order', 'arguments': {'order_id': ext_oid}},
                            {'name': 'search_knowledge', 'arguments': {'query': 'chính sách bồi thường giao hàng trễ voucher'}}
                        ]},
                        {'say': f"Dạ đơn hàng {ext_oid} của anh/chị đã bị trễ quá 48 giờ so với thời gian cam kết. Theo chính sách của shop [{{{{last_tool.results.0.citation_id}}}}], quý khách đủ điều kiện nhận voucher bồi thường 50.000 VNĐ cho đơn hàng tiếp theo ạ."}
                    ]
                }
            ],
            'final_state': {
                'orders': {ext_oid: slot['status']},
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T01DonKhongThuocKhach(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_don_khong_thuoc_khach', 'T01', 5, description='Tra cứu đơn hàng không thuộc tài khoản của khách')

    def select(self, view: Any) -> list[Any]:
        slots = []
        cust_list = list(view.customers.keys())
        all_orders = list(view.orders.values())
        for idx, o in enumerate(all_orders):
            owner = o['external_customer_id']
            non_owners = [c for c in cust_list if c != owner]
            if non_owners:
                asking = non_owners[idx % len(non_owners)]
                slots.append({'asking_customer': asking, 'target_order': o})
        return slots

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['target_order']['external_order_id']
        cust_id = slot['asking_customer']
        intents = [
            "tra_cuu_don_la_khong_thuoc_tai_khoan",
            "hoi_tinh_trang_don_nguoi_khac",
            "check_giup_ma_don_khong_phai_cua_minh",
            "tra_cuu_don_hang_khong_tim_thay",
            "hoi_thong_tin_don_hang_ngoai",
            "thac_mac_don_khong_hien_thi_trong_app",
            "kiem_tra_ho_don_hang_nguoi_than",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_don_khac",
            intent=intent,
            must_include=[ext_oid],
            must_not_include=["không tìm thấy", "không thuộc tài khoản"],
            length="ngắn",
            notes="Khách hỏi tra cứu một mã đơn không thuộc tài khoản mua hàng của mình",
        )
        case = {
            'id': cid,
            'category': 't01',
            'title': f'Tra cứu đơn {ext_oid} không thuộc tài khoản',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T01',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T01 foreign order {ext_oid}',
                'slot_key': f"{cust_id}_{ext_oid}",
                'intent': intent,
                'vn_context': [],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: tra cứu đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_all': [ext_oid],
                        'answer_any': [['không tìm thấy', 'không tồn tại', 'không thuộc tài khoản']],
                        'answer_not': ['đang vận chuyển', 'đã giao', 'đã hoàn tiền'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ shop đã kiểm tra hệ thống nhưng không tìm thấy đơn hàng {ext_oid} trong tài khoản của bạn, vui lòng kiểm tra lại chính xác mã đơn giúp shop nhé."}
                    ]
                }
            ],
            'final_state': {
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T01HoiDiaChiSdtDayDu(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_hoi_dia_chi_sdt_day_du', 'T01', 5, description='Khách hỏi số điện thoại và địa chỉ nhận hàng đầy đủ (PII đã che)')

    def select(self, view: Any) -> list[Any]:
        return [o for o in view.orders.values() if o.get('recipient', {}).get('phone_masked')]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        rec = slot.get('recipient') or {}
        phone_masked = rec.get('phone_masked') or '0123.xxx.xxx'
        intents = [
            "hoi_so_dien_thoai_nhan_hang_day_du",
            "kiem_tra_sdt_nguoi_nhan_don_hang",
            "thac_mac_so_dien_thoai_bi_che",
            "xin_lai_sdt_giao_hang_chinh_xac",
            "hoi_thong_tin_lien_he_nguoi_nhan",
            "check_sdt_va_dia_chi_giao_hang",
            "xac_nhan_so_dien_thoai_nhan_kien",
            "hoi_so_dien_thoai_da_luu_trong_don",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_sdt",
            intent=intent,
            must_include=[ext_oid],
            must_not_include=["0123.xxx", "bảo mật thông tin"],
            length="ngắn",
            notes="Khách hỏi xem lại số điện thoại đặt hàng trong đơn để kiểm tra",
        )
        case = {
            'id': cid,
            'category': 't01',
            'title': f'Tra cứu SĐT che đơn {ext_oid}',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T01',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T01 masked PII phone {ext_oid}',
                'slot_key': ext_oid,
                'intent': intent,
                'vn_context': ['bao_mat_du_lieu'],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi SĐT đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_all': [ext_oid, phone_masked],
                        'answer_any': [['bảo mật', 'che', 'quy định', 'hệ thống']],
                        'answer_not': ['0987654321', '0123456789'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} ghi nhận số điện thoại người nhận là {phone_masked}. Để bảo mật thông tin cá nhân khách hàng, hệ thống tự động che các chữ số ở giữa và shop không thể cung cấp số điện thoại đầy đủ ạ."}
                    ]
                }
            ],
            'final_state': {
                'orders': {ext_oid: slot['status']},
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T01TrangThaiHoanTien(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_trang_thai_hoan_tien', 'T01', 6, description='Khách hỏi trạng thái xử lý hoàn tiền (processing, failed, completed)')

    def select(self, view: Any) -> list[Any]:
        slots = []
        slots.extend(view.orders_refund_processing)
        slots.extend(view.orders_refund_failed)
        slots.extend(view.orders_refund_completed)
        return slots or list(view.orders.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        ref = slot.get('refund_summary') or {}
        st = ref.get('latest_status', 'completed')
        intents = [
            f"tra_cuu_tien_do_hoan_tien_{st}",
            f"hoi_khi_nao_nhan_duoc_tien_hoan_{st}",
            f"check_trang_thai_hoan_tien_{st}",
            f"thac_mac_khoan_tien_hoan_{st}",
            f"hoi_tien_hoan_da_chuyen_chua_{st}",
            f"kiem_tra_hoan_tien_don_hang_{st}",
            f"hoi_ly_do_tien_do_hoan_tien_{st}",
            f"xac_nhan_trang_thai_hoan_tien_{st}",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_hoan_tien",
            intent=intent,
            must_include=[ext_oid],
            must_not_include=["12 đến 72 giờ", "thành công", "thất bại"],
            length="ngắn",
            notes=f"Khách hỏi tình trạng tiền hoàn của đơn {ext_oid}",
        )
        k_chunk = view.get_knowledge_chunk('refunds.md', '12 đến 72 giờ') if view else {
            'source_key': 'refunds.md', 'title': 'Chính sách hoàn tiền',
            'chunk': 'Sau khi cửa hàng xác nhận hoàn tiền, cổng thanh toán thường xử lý xong trong 12 đến 72 giờ. Hoàn tiền bị lỗi thì cổng thanh toán xử lý lại và nhân viên cửa hàng liên hệ khách.'
        }
        if st == 'processing':
            answer_any = [['đang xử lý', 'chờ xử lý', '12 đến 72 giờ', '12–72 giờ']]
            say_txt = f"Dạ đơn hàng {ext_oid} của bạn hiện đang ở trạng thái xử lý hoàn tiền (processing), theo chính sách của shop [{{{{last_tool.results.0.citation_id}}}}], cổng thanh toán sẽ hoàn tất trong vòng 12 đến 72 giờ ạ."
        elif st == 'failed':
            reason = ref.get('latest_reason') or 'tài khoản nhận tiền bị khóa'
            answer_any = [['thất bại', 'không thành công', 'lỗi']]
            say_txt = f"Dạ đơn hàng {ext_oid} hiện có trạng thái hoàn tiền thất bại do {reason}. Theo quy định của shop [{{{{last_tool.results.0.citation_id}}}}], cổng thanh toán sẽ xử lý lại và nhân viên sẽ liên hệ hỗ trợ bạn nhé ạ."
        else:
            answer_any = [['đã hoàn', 'thành công', 'hoàn tất']]
            say_txt = f"Dạ đơn hàng {ext_oid} đã được hệ thống hoàn tất thủ tục hoàn tiền thành công theo chính sách của shop [{{{{last_tool.results.0.citation_id}}}}] rồi ạ."

        case = {
            'id': cid,
            'category': 't01',
            'title': f'Tra cứu hoàn tiền {ext_oid} trạng thái {st}',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T01',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T01 refund status {ext_oid} ({st})',
                'slot_key': ext_oid,
                'intent': intent,
                'vn_context': ['hoan_tien_cham'],
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi trạng thái hoàn tiền {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'],
                        'max_tool_calls': 2,
                        'action': 'reply',
                        'human_support': False,
                        'sources': ['refunds.md'],
                        'answer_all': [ext_oid],
                        'answer_any': answer_any,
                        'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [
                            {'name': 'get_order', 'arguments': {'order_id': ext_oid}},
                            {'name': 'search_knowledge', 'arguments': {'query': 'thời gian hoàn tiền và trạng thái xử lý cổng thanh toán'}}
                        ]},
                        {'say': say_txt}
                    ]
                }
            ],
            'final_state': {
                'orders': {ext_oid: slot['status']},
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]
