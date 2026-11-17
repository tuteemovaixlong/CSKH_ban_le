"""Templates for Suite T06: Đổi hàng (100 ca).

Covers:
- Đổi size còn hàng (mở biểu mẫu chọn target_variant)
- Đổi size hết hàng (báo hết hàng và gợi ý)
- Đổi quá 15 ngày (hết hạn đổi size, gợi ý bảo hành nếu lỗi)
- Đổi sang sản phẩm khác (không hỗ trợ)
- Đổi hai món cùng đơn
- Đổi màu cùng sản phẩm
- Đổi 1-1 lỗi trong 90 ngày (bảo hành)
- Đổi size hai chiều tận nhà
- Đổi size đơn chưa giao (chưa nhận hàng)
- Đổi hàng chọn biến thể
"""
from __future__ import annotations

import random
from typing import Any

from .base import BaseTemplate, Brief


class T06DoiSizeConHang(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t06_doi_size_con_hang', 'T06', 10, description='Đổi size sản phẩm còn hàng trong vòng 15 ngày')

    def select(self, view: Any) -> list[Any]:
        apparel_pids = {'P-101', 'P-102', 'P-103', 'P-104', 'P-202', 'P-203', 'P-301', 'P-501', 'P-502', 'P-503', 'P-504', 'P-601', 'P-602', 'P-603'}
        ords = [o for o in view.orders_size_exchange_eligible if o.get('product_id') in apparel_pids]
        return ords or list(view.orders_size_exchange_eligible)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t06_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        pid = slot.get('product_id')
        curr_var = slot.get('variant') or 'Trắng · Size L'

        matching_in_stock = [
            v for v in getattr(view, 'in_stock_variants', [])
            if v.get('product_id') == pid and v.get('variant_name') != curr_var
        ] if view else []

        if matching_in_stock:
            chosen = matching_in_stock[case_index % len(matching_in_stock)]
            target_label = chosen['variant_name']
            target_size = chosen['size']
        else:
            color = curr_var.split('·')[0].strip() if '·' in curr_var else 'Trắng'
            target_size = 'M' if 'L' in curr_var else 'L'
            target_label = f"{color} · Size {target_size}"

        intents = [
            f"yeu_cau_doi_size_con_hang_{case_index}",
            f"hoi_doi_sang_size_vua_hon_{case_index}",
            f"thac_mac_doi_size_khi_mac_chat_{case_index}",
            f"check_doi_size_{target_size}_con_hang_{case_index}",
            f"yeu_cau_mo_bieu_mau_doi_size_{case_index}",
            f"hoi_thu_tuc_doi_sang_size_{target_size}_{case_index}",
            f"kiem_tra_doi_size_trong_15_ngay_{case_index}",
            f"doi_size_san_pham_vua_nhan_{case_index}",
            f"check_hang_doi_size_san_co_{case_index}",
            f"xac_nhan_doi_sang_bien_the_con_{case_index}",
        ]
        intent = intents[(case_index - 1) % len(intents)]

        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_mac_khong_vua", intent=intent,
            must_include=[ext_oid, target_size], must_not_include=["choose_order_action_reason"], length="vừa",
            notes=f"Khách nhận đơn {ext_oid} mặc hơi chật/rộng muốn đổi sang size {target_size}",
        )
        case = {
            'id': cid, 'category': 't06', 'title': f'Đổi size còn hàng đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T06', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T06 exchange in stock {ext_oid}',
                'slot_key': ext_oid, 'intent': intent, 'vn_context': ['doi_size_thoi_trang']
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: muốn đổi đơn {ext_oid} sang size {target_size}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_order_action_reason',
                        'order_action': {'order_id': ext_oid, 'action_type': 'exchange', 'exchange_kind': 'other_variant', 'target_variant_label': target_label},
                        'human_support': False, 'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'đổi', 'size']], 'answer_not': ['hết hạn đổi size', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'exchange', 'target_variant': target_label}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} vẫn trong thời hạn 15 ngày đổi size ạ. Biến thể {target_label} hiện vẫn còn hàng, em đã mở biểu mẫu đổi hàng sang size {target_size} trên màn hình rồi nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T06DoiSizeHetHangGoiY(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t06_doi_size_het_hang_goi_y', 'T06', 10, description='Đổi sang size đã hết hàng trong kho: báo hết và gợi ý')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t06_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_muon_doi_size_hiem", intent="doi_sang_size_tam_het",
            must_include=[ext_oid, "size XXL"], must_not_include=["mở biểu mẫu đổi hàng thành công"], length="vừa",
            notes=f"Khách muốn đổi đơn {ext_oid} sang size XXL (size không có hoặc hết hàng)",
        )
        case = {
            'id': cid, 'category': 't06', 'title': f'Đổi size hết hàng đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T06', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T06 exchange out of stock {ext_oid}', 'vn_context': ['doi_size_thoi_trang']},
            'turns': [
                {
                    'user': f"<chờ lời khách: muốn đổi đơn {ext_oid} sang size XXL>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_order_action_reason',
                        'order_action': {'order_id': ext_oid, 'action_type': 'exchange'}, 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'chọn biến thể', 'kho']], 'answer_not': ['đã hủy thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'exchange'}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} đủ điều kiện đổi hàng ạ. Em đã mở biểu mẫu trên màn hình để anh/chị chọn size còn sẵn trong kho nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T06DoiQua15Ngay(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t06_doi_qua_15_ngay', 'T06', 10, description='Đổi size quá 15 ngày: từ chối đổi size, gợi ý bảo hành nếu có lỗi')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_16_to_90)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t06_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_doi_size_muon", intent="yeu_cau_doi_size_qua_15_ngay",
            must_include=[ext_oid], must_not_include=["hết hạn đổi size 15 ngày"], length="vừa",
            notes=f"Khách mua đơn {ext_oid} đã gần 1 tháng giờ muốn đổi size",
        )
        case = {
            'id': cid, 'category': 't06', 'title': f'Đổi size quá 15 ngày đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T06', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T06 size exchange expired {ext_oid}', 'vn_context': ['doi_size_thoi_trang']},
            'turns': [
                {
                    'user': f"<chờ lời khách: muốn đổi size đơn cũ {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order'], 'tools_not_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['15 ngày', 'hết hạn', 'quá thời hạn']], 'answer_not': ['mở biểu mẫu đổi size thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} đã quá thời hạn 15 ngày đổi size quy định rồi ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T06DoiSangSanPhamKhac(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t06_doi_sang_san_pham_khac', 'T06', 10, description='Khách muốn đổi sang mã sản phẩm hoàn toàn khác: chính sách không hỗ trợ')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t06_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_muon_doi_sang_mau_ao_khac", intent="doi_sang_san_pham_khac",
            must_include=[ext_oid], must_not_include=["chỉ áp dụng đổi size/màu cùng sản phẩm"], length="vừa",
            notes=f"Khách nhận áo đơn {ext_oid} muốn đổi sang mẫu quần khác",
        )
        case = {
            'id': cid, 'category': 't06', 'title': f'Đổi sang mẫu khác đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T06', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T06 exchange to different product {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: muốn đổi đơn {ext_oid} sang mẫu sản phẩm khác>",
                    'expect': {
                        'tools_called': ['get_order'], 'tools_not_called': ['prepare_order_action'],
                        'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['cùng sản phẩm', 'chỉ hỗ trợ đổi size', 'trả hàng']], 'answer_not': ['đã đổi thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ chính sách đổi hàng chỉ áp dụng cho việc đổi size hoặc màu của cùng một sản phẩm trong đơn {ext_oid} ạ. Nếu muốn chuyển sang sản phẩm khác, anh/chị có thể yêu cầu trả hàng trong vòng 7 ngày để hoàn tiền và đặt đơn mới nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T06DoiHaiMonCungDon(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t06_doi_hai_mon_cung_don', 'T06', 10, description='Khách muốn đổi size cho sản phẩm trong đơn nhiều món')

    def select(self, view: Any) -> list[Any]:
        multi = [o for o in view.delivered_within_7 if len(o.get('items', [])) >= 2]
        return multi or list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t06_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_muon_doi_trong_don_nhieu_mon", intent="doi_size_don_nhieu_mon",
            must_include=[ext_oid], must_not_include=["choose_order_action_reason"], length="vừa",
            notes=f"Khách muốn đổi hàng cho đơn {ext_oid} có nhiều món",
        )
        case = {
            'id': cid, 'category': 't06', 'title': f'Đổi size đơn nhiều món {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T06', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T06 multi-item exchange {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: muốn đổi hàng đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_order_action_reason',
                        'order_action': {'order_id': ext_oid, 'action_type': 'exchange'}, 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'đổi', 'chọn']], 'answer_not': ['đã hủy thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'exchange'}}]},
                        {'say': f"Dạ em đã mở biểu mẫu đổi hàng cho đơn {ext_oid} trên màn hình. Anh/chị chọn món hàng và biến thể cần đổi trên biểu mẫu nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T06DoiMau(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t06_doi_mau', 'T06', 10, description='Khách muốn đổi sang màu khác của cùng sản phẩm')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t06_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_muon_doi_mau", intent="yeu_cau_doi_mau_san_pham",
            must_include=[ext_oid], must_not_include=["choose_order_action_reason"], length="vừa",
            notes=f"Khách nhận đơn {ext_oid} mặc vừa nhưng muốn đổi sang màu khác",
        )
        case = {
            'id': cid, 'category': 't06', 'title': f'Đổi màu cùng sản phẩm {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T06', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T06 color exchange {ext_oid}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: muốn đổi màu đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_order_action_reason',
                        'order_action': {'order_id': ext_oid, 'action_type': 'exchange'}, 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'đổi màu', 'xác nhận']], 'answer_not': ['không được đổi'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'exchange'}}]},
                        {'say': f"Dạ chính sách của shop hỗ trợ đổi cả size và màu ạ. Em đã mở biểu mẫu đổi hàng cho đơn {ext_oid}, anh/chị chọn màu muốn đổi trên biểu mẫu nhé."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T06Doi11LoiTrong90Ngay(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t06_doi_1_1_loi_trong_90_ngay', 'T06', 10, description='Đổi 1-1 sản phẩm bị lỗi sản xuất trong thời hạn bảo hành')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_warranty_only) or list(view.delivered_16_to_90)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t06_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        w_days = int(slot.get('eligibility', {}).get('warranty_window_days', 90))
        k_chunk = view.get_knowledge_chunk('policy_warranty_exchange_1to1.md', 'bảo hành') if view else {
            'source_key': 'policy_warranty_exchange_1to1.md', 'title': 'Chính sách bảo hành, đổi mới 1-1 tận nhà',
            'chunk': 'Thời hạn bảo hành đổi mới tiêu chuẩn là **90 ngày kể từ ngày giao hàng** đối với lỗi do nhà sản xuất (bung chỉ, hỏng khóa kéo, lỗi đường may, rách viền).'
        }
        intents = [
            f"yeu_cau_bao_hanh_doi_moi_1_1_{case_index}",
            f"bao_loi_san_xuat_doi_1_1_{case_index}",
            f"thac_mac_bao_hanh_san_pham_loi_{case_index}",
            f"check_dieu_kien_bao_hanh_1_doi_1_{case_index}",
            f"yeu_cau_mo_doi_bao_hanh_loi_chi_{case_index}",
            f"hoi_thu_tuc_doi_1_1_trong_bao_hanh_{case_index}",
            f"kiem_tra_bao_hanh_loi_duong_may_{case_index}",
            f"bao_do_loi_khoa_keo_doi_moi_{case_index}",
            f"check_han_bao_hanh_doi_1_1_{case_index}",
            f"xac_nhan_doi_1_1_do_loi_nha_san_xuat_{case_index}",
        ]
        intent = intents[(case_index - 1) % len(intents)]

        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_bao_hang_loi_chi", intent=intent,
            must_include=[ext_oid, "lỗi"], must_not_include=["choose_order_action_reason"], length="vừa",
            notes=f"Khách báo đồ đơn {ext_oid} bị bung chỉ/hỏng khóa sau vài tuần sử dụng",
        )
        case = {
            'id': cid, 'category': 't06', 'title': f'Bảo hành đổi 1-1 lỗi {w_days} ngày {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T06', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T06 warranty 1-1 defective item {ext_oid}',
                'slot_key': ext_oid, 'intent': intent, 'vn_context': ['hang_loi']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: báo hàng lỗi bảo hành đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action', 'search_knowledge'], 'max_tool_calls': 2, 'action': 'choose_order_action_reason',
                        'order_action': {'order_id': ext_oid, 'action_type': 'exchange'},
                        'human_support': False, 'sources': ['policy_warranty_exchange_1to1.md'],
                        'answer_all': [ext_oid, f"{w_days} ngày"],
                        'answer_any': [['bảo hành', 'đổi 1-1', 'biểu mẫu', 'lỗi']],
                        'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [
                            {'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'exchange'}},
                            {'name': 'search_knowledge', 'arguments': {'query': 'chính sách bảo hành đổi mới 1-1 lỗi sản xuất'}}
                        ]},
                        {'say': f"Dạ theo chính sách bảo hành của shop [{{{{last_tool.results.0.citation_id}}}}], đơn hàng {ext_oid} vẫn nằm trong thời hạn bảo hành {w_days} ngày cho lỗi nhà sản xuất; em đã mở biểu mẫu yêu cầu bảo hành đổi mới 1-1 trên màn hình cho anh/chị rồi ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T06DoiSizeHaiChieu(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t06_doi_size_hai_chieu', 'T06', 10, description='Khách hỏi quy trình đổi size 2 chiều giao nhận tận nhà')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t06_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_cach_thuc_doi", intent="hoi_quy_trinh_doi_size_tan_nha",
            must_include=[ext_oid], must_not_include=["[KB:"], length="ngắn",
            notes=f"Khách hỏi đổi size đơn {ext_oid} thì shipper giao thế nào",
        )
        k_chunk = view.get_knowledge_chunk('policy_size_exchange_twoway.md', '2 chiều') if view else {
            'source_key': 'policy_size_exchange_twoway.md', 'title': 'Chính sách đổi size, đổi màu 2 chiều tận nhà',
            'chunk': 'Nhân viên cửa hàng duyệt yêu cầu và sắp xếp đổi hàng 2 chiều: shipper mang sản phẩm đúng size, màu đến tận nhà và nhận lại sản phẩm cũ để gửi về shop. Lần đổi size đầu tiên của mỗi đơn được miễn phí vận chuyển; từ lần thứ hai khách trả phí ship theo biểu phí vận chuyển.'
        }
        case = {
            'id': cid, 'category': 't06', 'title': f'Quy trình đổi size 2 chiều {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T06', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T06 two-way exchange process {ext_oid}', 'vn_context': ['doi_size_thoi_trang']},
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi quy trình đổi size đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'sources': ['policy_size_exchange_twoway.md'],
                        'answer_all': [ext_oid], 'answer_any': [['2 chiều', 'tận nhà', 'shipper mang']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}, {'name': 'search_knowledge', 'arguments': {'query': 'quy trình đổi size 2 chiều tận nhà'}}]},
                        {'say': f"Dạ đối với đơn {ext_oid}, theo chính sách đổi hàng của shop [{{{{last_tool.results.0.citation_id}}}}], quy trình đổi size là đổi 2 chiều tận nhà ạ. Khi shipper mang size mới tới giao, anh/chị chỉ cần đưa lại sản phẩm cũ cho shipper mang về, không cần mang ra bưu cục nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T06DoiSizeChuaGiao(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t06_doi_size_chua_giao', 'T06', 10, description='Khách muốn đổi size khi đơn chưa giao (shipping/pending)')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['pending'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t06_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_doi_size_som", intent="doi_size_khi_chua_giao_hang",
            must_include=[ext_oid], must_not_include=["choose_order_action_reason"], length="vừa",
            notes=f"Khách vừa đặt đơn {ext_oid} muốn đổi sang size khác trước khi shop gửi đi",
        )
        case = {
            'id': cid, 'category': 't06', 'title': f'Đổi size đơn chưa giao {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T06', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T06 exchange pending order {ext_oid}', 'vn_context': ['doi_size_thoi_trang']},
            'turns': [
                {
                    'user': f"<chờ lời khách: muốn đổi size đơn chưa giao {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['chờ xử lý', 'hủy đơn', 'đặt lại']], 'answer_not': ['mở biểu mẫu đổi hàng thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'exchange'}}]},
                        {'say': f"Dạ đơn {ext_oid} đang ở trạng thái chờ xử lý và chưa giao hàng nên hệ thống chưa thể mở biểu mẫu đổi size ạ. Anh/chị có thể yêu cầu hủy đơn này rồi đặt lại đơn mới với size mong muốn nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'pending'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T06DoiHangChonVariant(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t06_doi_hang_chon_variant', 'T06', 10, description='Khách muốn đổi hàng và yêu cầu hỗ trợ mở danh mục chọn size')

    def select(self, view: Any) -> list[Any]:
        return list(view.delivered_within_7)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t06_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_muon_xem_cac_size_de_doi", intent="yeu_cau_mo_form_doi_size",
            must_include=[ext_oid], must_not_include=["choose_order_action_reason"], length="ngắn",
            notes=f"Khách yêu cầu mở biểu mẫu đổi hàng cho đơn {ext_oid}",
        )
        case = {
            'id': cid, 'category': 't06', 'title': f'Mở form đổi hàng {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T06', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T06 open exchange form {ext_oid}', 'vn_context': ['doi_size_thoi_trang']},
            'turns': [
                {
                    'user': f"<chờ lời khách: mở form đổi size đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'choose_order_action_reason',
                        'order_action': {'order_id': ext_oid, 'action_type': 'exchange'}, 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['biểu mẫu', 'chọn size', 'đổi hàng']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'exchange'}}]},
                        {'say': f"Dạ em đã mở biểu mẫu đổi hàng cho đơn {ext_oid} trên màn hình. Anh/chị chọn size/màu muốn đổi và xác nhận trên biểu mẫu giúp em nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]
