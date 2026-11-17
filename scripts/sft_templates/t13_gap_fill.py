"""Gap-fill templates for T01 and T02 (W6.7.0, added after PR #120).

The W6.4 baseline showed Qwen choosing the wrong tool in S02 and the 250 eval
cases expect `track_shipment` (34 times) and `search_products` (15 times) more
often than the first 1,200 training cases covered them (20 and 10). These three
templates add real-data cases for both tools. Every fact in `expect` is read
through the same tool the model must call, never computed here.

- t01_theo_doi_hanh_trinh_dang_giao (8 ca): order in transit, where is it now
- t01_giao_lai_nhieu_lan (8 ca): order delivered after a failed first attempt
- t02_tim_san_pham_theo_mo_ta (10 ca): customer names a kind of product, not an ID
"""
from __future__ import annotations

import random
from typing import Any

from .base import BaseTemplate, Brief


def _tool(view: Any, customer: str):
    from retailops_tools import BoundTools
    return BoundTools(view.store, view.catalog, customer, {}, {})


def _track(view: Any, order: dict[str, Any]) -> dict[str, Any]:
    return _tool(view, order['internal_customer_id'])('track_shipment', {'order_id': order['external_order_id']})


def _area_options(area: str) -> list[str]:
    """Ways an answer may name the parcel's current area: its first part, its province, the province without prefix."""
    parts = [p.strip() for p in str(area or '').split(',') if p.strip()]
    if not parts:
        return []
    options = [parts[0], parts[-1]]
    for prefix in ('TP. ', 'Tỉnh ', 'Thành phố '):
        if parts[-1].startswith(prefix):
            options.append(parts[-1][len(prefix):])
    return list(dict.fromkeys(options))


class T01TheoDoiHanhTrinhDangGiao(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_theo_doi_hanh_trinh_dang_giao', 'T01', 8,
                         description='Đơn đang vận chuyển: tra hành trình bằng track_shipment, nêu đúng vị trí hiện tại')

    def select(self, view: Any) -> list[Any]:
        slots = []
        for order in view.orders_by_status['shipping']:
            shipment = (_track(view, order) or {}).get('shipment') or {}
            if shipment.get('status') == 'in_transit' and _area_options(shipment.get('current_area')):
                slots.append({**order, '_shipment': shipment})
        return slots

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        shipment = slot['_shipment']
        areas = _area_options(shipment.get('current_area'))
        intents = [
            "hoi_kien_hang_dang_o_kho_nao",
            "hoi_hanh_trinh_don_hang",
            "hoi_bao_gio_hang_toi",
            "hoi_don_di_toi_dau_roi",
            "check_lo_trinh_van_chuyen",
            "hoi_ma_van_don_va_vi_tri",
            "sot_ruot_hoi_hang_den_dau",
            "hoi_du_kien_ngay_giao",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_theo_doi_don", intent=intent,
            must_include=[ext_oid],
            must_not_include=[*areas, str(shipment.get('tracking_code') or ''), 'trung chuyển'],
            length="ngắn",
            notes=f"Khách muốn biết đơn {ext_oid} đang ở đâu và khi nào tới; khách không biết mã vận đơn hay vị trí kho",
        )
        brief.must_not_include = [x for x in brief.must_not_include if x]
        case = {
            'id': cid, 'category': 't01', 'title': f'Theo dõi hành trình đơn đang giao {ext_oid}',
            'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T01', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id,
                'source_note': f'T01 track_shipment in transit {ext_oid}', 'slot_key': ext_oid, 'intent': intent,
                'vn_context': [],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi đơn {ext_oid} đang ở đâu>",
                    'expect': {
                        'tools_called': ['track_shipment'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid],
                        'answer_any': [areas],
                        'answer_not': ['đã giao thành công', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'track_shipment', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đơn {ext_oid} đang trung chuyển, kiện hàng hiện ở {shipment.get('current_area')} ạ. "
                                f"Đơn vị vận chuyển dự kiến giao trong vài ngày tới, anh/chị chú ý điện thoại giúp em nhé."},
                    ],
                }
            ],
            'final_state': {'orders': {ext_oid: 'shipping'}, 'rows': {'order_action_requests': 0, 'handoff_episodes': 0}},
        }
        return case, [brief]


class T01GiaoLaiNhieuLan(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t01_giao_lai_nhieu_lan', 'T01', 8,
                         description='Đơn đã giao sau lần giao đầu không thành công: tra track_shipment, giải thích đã phát lại')

    def select(self, view: Any) -> list[Any]:
        slots = []
        for order in view.orders_by_status['delivered']:
            shipment = (_track(view, order) or {}).get('shipment') or {}
            # delivery_attempts counts failed attempts; delivered + at least one failed attempt = redelivered
            if shipment.get('status') == 'delivered' and int(shipment.get('delivery_attempts') or 0) >= 1 and shipment.get('fail_reason'):
                slots.append({**order, '_shipment': shipment})
        return slots

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t01_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        intents = [
            "hoi_sao_giao_nhieu_lan_moi_toi",
            "phan_nan_shipper_giao_lai",
            "hoi_lich_su_giao_hang",
            "thac_mac_lan_giao_dau_that_bai",
            "kiem_tra_don_da_giao_xong_chua",
            "hoi_vi_sao_bao_giao_khong_thanh_cong",
            "hoi_shipper_da_ghe_may_lan",
            "xac_nhan_da_nhan_hang_sau_giao_lai",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_lich_su_giao", intent=intent,
            must_include=[ext_oid], must_not_include=['track_shipment', 'phát lại'],
            length="vừa",
            notes=f"Khách đã nhận đơn {ext_oid} nhưng thắc mắc vì sao trước đó shipper báo giao không được",
        )
        case = {
            'id': cid, 'category': 't01', 'title': f'Lịch sử giao lại nhiều lần đơn {ext_oid}',
            'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T01', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id,
                'source_note': f'T01 track_shipment redelivery {ext_oid}', 'slot_key': ext_oid, 'intent': intent,
                'vn_context': ['giao_that_bai'],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi lịch sử giao đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['track_shipment'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid],
                        'answer_any': [['đã giao', 'giao thành công', 'đã nhận'], ['giao lại', 'phát lại', 'lần giao', 'chưa thành công', 'không thành công']],
                        'answer_not': ['chưa có thông tin', 'đang trên đường giao'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'track_shipment', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ theo hành trình vận chuyển, đơn {ext_oid} giao lần đầu chưa thành công nên bưu tá đã phát lại, "
                                f"và đơn đã giao thành công ở lần giao sau ạ."},
                    ],
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0, 'handoff_episodes': 0}},
        }
        return case, [brief]


class T02TimSanPhamTheoMoTa(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t02_tim_san_pham_theo_mo_ta', 'T02', 10,
                         description='Khách gọi tên loại hàng, không nêu mã: tìm bằng search_products, giới thiệu đúng sản phẩm có trong danh mục')

    def select(self, view: Any) -> list[Any]:
        customers = sorted(view.customers)
        tool = _tool(view, view.customers[customers[0]]['internal_customer_id'])
        keywords = sorted({str(p.get('category') or '').strip().lower() for p in view.catalog.products.values()} - {''})
        slots = []
        for kw in keywords:
            found = tool('search_products', {'query': kw}) or {}
            names = [str(p.get('name')) for p in (found.get('products') or []) if p.get('name')]
            if names:
                slots.append({'query': kw, 'names': names[:5]})
        return slots

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t02_{case_index:03d}_{self.template_id}"
        query, names = slot['query'], slot['names']
        customers = sorted(view.customers) if view else ['SIM-C-5001']
        cust_id = customers[(case_index * 7) % len(customers)]
        intents = [
            "hoi_shop_co_ban_loai_nay_khong",
            "nho_goi_y_mau_theo_loai",
            "tim_mon_theo_mo_ta",
            "hoi_cac_mau_dang_ban",
            "can_mua_qua_tang_hoi_mau",
            "hoi_shop_co_nhung_mau_nao",
            "tim_san_pham_khong_nho_ten",
            "hoi_lua_chon_trong_danh_muc",
            "xin_danh_sach_mau",
            "hoi_mau_moi_ve",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        # Không cấm tên sản phẩm nằm gọn trong từ khóa khách phải nói (danh mục có sản phẩm tên đúng "Áo polo"):
        # cấm nó thì phiếu tự mâu thuẫn, không ai viết đạt (W6.7 đợt đủ 17/11, brf_t02_099).
        from scripts.eval_regrade import v2
        banned = [n for n in names if v2(n) not in v2(query)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_tim_san_pham", intent=intent,
            must_include=[query], must_not_include=[*banned, 'P-'],
            length="ngắn",
            notes=f"Khách muốn mua {query} nhưng không biết tên hay mã sản phẩm cụ thể",
        )
        case = {
            'id': cid, 'category': 't02', 'title': f'Tìm sản phẩm theo mô tả: {query}',
            'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T02', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id,
                'source_note': f'T02 search_products by kind {query}', 'slot_key': f'{query}|{cust_id}', 'intent': intent,
                'vn_context': [],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: tìm {query}>",
                    'expect': {
                        'tools_called': ['search_products'], 'tools_not_called': ['prepare_order_action'],
                        'max_tool_calls': 3, 'action': 'reply', 'human_support': False,
                        'answer_any': [names],
                        'answer_not': ['không kinh doanh', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_products', 'arguments': {'query': query}}]},
                        {'say': f"Dạ shop đang có các mẫu {query}: " + ', '.join(names) + ". Anh/chị muốn xem chi tiết hay kiểm tra size mẫu nào ạ?"},
                    ],
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0, 'handoff_episodes': 0}},
        }
        return case, [brief]
