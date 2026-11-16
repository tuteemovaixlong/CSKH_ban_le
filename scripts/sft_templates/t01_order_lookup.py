"""Templates for Suite T01: Tra cứu đơn hàng (100 ca).

Covers:
- Tra cứu đơn theo trạng thái: pending, shipping, delivered, cancelled
- Liệt kê đơn (list_orders)
- Khách không nêu mã đơn khi có nhiều đơn (hỏi lại)
- Khách không nêu mã đơn khi chỉ có 1 đơn
- Vận đơn giao thất bại / đang giao (track_shipment)
- Đơn giao trễ < 48h vs > 48h (tra chính sách bồi thường voucher)
"""
from __future__ import annotations

import random
from typing import Any

from .base import BaseTemplate, Brief


class T01TraDonPending(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_tra_don_pending', 'T01', 10, description='Tra cứu đơn hàng đang chờ xử lý (pending)')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['pending'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        prod_name = slot.get('name') or 'Sản phẩm'
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_chờ_xử_lý",
            intent="tra_cuu_tien_do_don_pending",
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
        super().__init__('t01_tra_don_shipping', 'T01', 10, description='Tra cứu đơn hàng đang vận chuyển (shipping)')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['shipping'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hỏi_giao_hang",
            intent="tra_cuu_tien_do_don_shipping",
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
        super().__init__('t01_tra_don_delivered', 'T01', 10, description='Tra cứu đơn hàng đã giao thành công (delivered)')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['delivered'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_kiem_tra_lich_su",
            intent="tra_cuu_don_da_giao",
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
        super().__init__('t01_tra_don_cancelled', 'T01', 10, description='Tra cứu đơn hàng đã hủy (cancelled)')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['cancelled'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_don_huy",
            intent="tra_cuu_don_da_huy",
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
        super().__init__('t01_liet_ke_don', 'T01', 10, description='Khách yêu cầu xem danh sách các đơn đã đặt')

    def select(self, view: Any) -> list[Any]:
        # Choose customers with at least 1 order
        return [c for c in view.customers.values() if c['order_count'] >= 1]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_muon_xem_tat_ca_don",
            intent="liet_ke_danh_sach_don_hang",
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
        super().__init__('t01_khong_neu_ma_nhieu_don', 'T01', 10, description='Khách có nhiều đơn hỏi tiến độ nhưng không nêu mã')

    def select(self, view: Any) -> list[Any]:
        return [c for c in view.customers.values() if c['order_count'] >= 2]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_chung_chung",
            intent="hoi_don_khong_neu_ma_nhieu_don",
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
        super().__init__('t01_khong_neu_ma_mot_don', 'T01', 10, description='Khách chỉ có đúng 1 đơn hỏi tiến độ không nêu mã')

    def select(self, view: Any) -> list[Any]:
        return [c for c in view.customers.values() if c['order_count'] == 1]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_chi_co_mot_don",
            intent="hoi_don_khong_neu_ma_mot_don",
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
        super().__init__('t01_van_don_giao_that_bai', 'T01', 10, description='Tra cứu vận đơn giao hàng thất bại (track_shipment)')

    def select(self, view: Any) -> list[Any]:
        # Look for orders with failed delivery or cancelled shipments, e.g. ST-504 or any cancelled
        ords = [o for o in view.orders_by_status['cancelled'] if o['external_order_id'] == 'SIM-O-ST-504']
        return ords or view.orders_by_status['cancelled']

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_van_don",
            intent="tra_cuu_van_don_that_bai",
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
        super().__init__('t01_giao_tre_duoi_48h', 'T01', 10, description='Đơn giao trễ dưới 48 giờ chưa đạt ngưỡng bồi thường')

    def select(self, view: Any) -> list[Any]:
        # Delivered orders with late_by_hours <= 48
        return [o for o in view.orders_by_status['delivered'] if o.get('eligibility', {}).get('late_by_hours', 0.0) <= 48.0]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_tre_hen",
            intent="hoi_boi_thuong_giao_tre_duoi_48h",
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
                'vn_context': ['giao_cham'],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi bồi thường đơn trễ {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order'],
                        'max_tool_calls': 2,
                        'action': 'reply',
                        'human_support': False,
                        'answer_all': [ext_oid],
                        'answer_any': [['giao', 'đơn']],
                        'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} của anh/chị shop rất xin lỗi vì sự chậm trễ trong quá trình giao hàng. Theo chính sách bồi thường, đơn hàng trễ trên 48 giờ mới đủ điều kiện cấp voucher bồi thường, rất mong anh/chị thông cảm giúp shop ạ."}
                    ]
                }
            ],
            'final_state': {
                'orders': {ext_oid: 'delivered'},
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T01GiaoTreTren48h(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_giao_tre_tren_48h', 'T01', 10, description='Đơn giao trễ trên 48 giờ tra chính sách bồi thường có trích dẫn')

    def select(self, view: Any) -> list[Any]:
        # Delivered orders with late_by_hours > 48, like SIM-O-ST-513
        late = [o for o in view.orders_by_status['delivered'] if o.get('eligibility', {}).get('late_by_hours', 0.0) > 48.0]
        return late or view.orders_by_status['delivered']

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('policy_mega_sale_delay_voucher.md', '48') if view else {
            'source_key': 'policy_mega_sale_delay_voucher.md',
            'title': 'Chính sách bồi thường giao hàng trễ, kể cả mùa Mega Sale',
            'chunk': 'Đơn giao trễ **quá 48 giờ** so với thời hạn giao cam kết thì hệ thống tự lập đề xuất tặng khách **một mã voucher giảm giá 50.000 VNĐ**. Nhân viên cửa hàng duyệt hoặc từ chối đề xuất; mệnh giá cố định, không đổi. Mỗi vận đơn được bồi thường giao trễ tối đa một lần.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_doi_boi_thuong",
            intent="hoi_boi_thuong_giao_tre_tren_48h",
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
                'orders': {ext_oid: 'delivered'},
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]
