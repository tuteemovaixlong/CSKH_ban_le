"""Templates for Suite T02: Sản phẩm và tồn kho (90 ca).

Covers:
- Chất liệu / giặt ủi có dữ liệu vs thiếu dữ liệu ("chưa có thông tin", không bịa, không [KB])
- Tồn kho biến thể còn vs hết hàng gợi ý
- Bảo hành riêng từng sản phẩm
- So sánh biến thể / màu
- Tư vấn size khi thiếu bảng size
- Nguồn gốc chính hãng khi thiếu dữ liệu
- Tra cứu sản phẩm không tồn tại trong catalog
"""
from __future__ import annotations

import random
from typing import Any

from .base import BaseTemplate, Brief


class T02ChatLieuGiatUiCoDuLieu(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t02_chat_lieu_giat_ui_co_du_lieu', 'T02', 10, description='Hỏi chất liệu / giặt ủi có dữ liệu trong catalog')

    def select(self, view: Any) -> list[Any]:
        # Products with descriptions containing cotton or fabric details
        return [p for p in view.catalog.products.values() if 'cotton' in (p.get('description') or '').lower()]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t02_{case_index:03d}_{self.template_id}"
        pid = slot['id']
        pname = slot['name']
        cust_id = list(view.customers.keys())[case_index % len(view.customers)] if view else 'SIM-C-5001'
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_chat_lieu",
            intent="hoi_chat_lieu_va_cach_giat",
            must_include=[pname],
            may_include=[pid],
            must_not_include=["[KB:"],
            length="vừa",
            notes="Khách hỏi chất liệu vải và cách giặt ủi sản phẩm",
        )
        case = {
            'id': cid,
            'category': 't02',
            'title': f'Chất liệu và giặt ủi {pid}',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T02',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T02 fabric care for {pid}',
                'vn_context': [],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi chất liệu giặt ủi {pname}>",
                    'expect': {
                        'tools_called': ['get_product'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_all': ['cotton'],
                        'answer_any': [['chất liệu', 'vải', 'giặt']],
                        'answer_not': ['[KB:', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_product', 'arguments': {'product_id': pid}}]},
                        {'say': f"Dạ sản phẩm {pname} ({pid}) được làm từ chất liệu cotton thoáng mát, thấm hút mồ hôi tốt. Khi giặt anh/chị nên giặt nước lạnh và không dùng chất tẩy mạnh để giữ form áo bền đẹp ạ."}
                    ]
                }
            ],
            'final_state': {
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T02ChatLieuGiatUiThieuDuLieu(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t02_chat_lieu_giat_ui_thieu_du_lieu', 'T02', 10, description='Hỏi chất liệu / giặt ủi khi catalog không có trường giặt ủi')

    def select(self, view: Any) -> list[Any]:
        # Products without washing/ironing instructions in description
        return [p for p in view.catalog.products.values() if 'ủi' not in (p.get('description') or '').lower() and 'giặt' not in (p.get('description') or '').lower()]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t02_{case_index:03d}_{self.template_id}"
        pid = slot['id']
        pname = slot['name']
        cust_id = list(view.customers.keys())[(case_index + 5) % len(view.customers)] if view else 'SIM-C-5001'
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_giat_ui_chi_tiet",
            intent="hoi_nhiet_do_ui_khi_thieu_du_lieu",
            must_include=[pname],
            must_not_include=["[KB:", "KB:faq"],
            length="vừa",
            notes="Khách hỏi nhiệt độ ủi chính xác của sản phẩm khi catalog không có thông tin",
        )
        case = {
            'id': cid,
            'category': 't02',
            'title': f'Giặt ủi thiếu dữ liệu {pid}',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T02',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T02 missing care info for {pid}',
                'vn_context': [],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi hướng dẫn giặt ủi chi tiết {pname}>",
                    'expect': {
                        'tools_called': ['get_product'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_any': [['chưa có thông tin', 'chưa có hướng dẫn', 'liên hệ']],
                        'answer_not': ['[KB:'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_product', 'arguments': {'product_id': pid}}]},
                        {'say': f"Dạ hiện tại trong thông tin sản phẩm {pname} shop chưa có thông tin hướng dẫn giặt ủi chi tiết ạ. Anh/chị nên giặt nhẹ nhàng với nước lạnh để đảm bảo độ bền của sản phẩm nhé ạ."}
                    ]
                }
            ],
            'final_state': {
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T02TonKhoBienTheCon(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t02_ton_kho_bien_the_con', 'T02', 10, description='Kiểm tra tồn kho biến thể còn hàng (in_stock)')

    def select(self, view: Any) -> list[Any]:
        slots = []
        for v in getattr(view, 'in_stock_variants', []):
            pid = v.get('product_id')
            p = view.catalog.products.get(pid)
            if p:
                slots.append({
                    'product_id': pid,
                    'name': p['name'],
                    'size': v.get('size') or 'M',
                    'color': v.get('color') or 'Trắng',
                    'stock': v.get('stock') or 1,
                })
        return slots or [
            {'product_id': 'P-101', 'name': 'Áo thun Essential', 'size': 'M', 'color': 'Trắng', 'stock': 12},
            {'product_id': 'P-102', 'name': 'Áo khoác Everyday', 'size': 'L', 'color': 'Đen', 'stock': 15},
            {'product_id': 'P-103', 'name': 'Áo Sơ Mi Oxford Dài Tay', 'size': 'M', 'color': 'Xanh Nhạt', 'stock': 8},
            {'product_id': 'P-104', 'name': 'Áo Khoác Gió Bomber 2 Lớp', 'size': 'M', 'color': 'Đen', 'stock': 14},
            {'product_id': 'P-202', 'name': 'Áo polo', 'size': 'M', 'color': 'Xanh', 'stock': 18},
        ]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t02_{case_index:03d}_{self.template_id}"
        pid = slot['product_id']
        pname = slot['name']
        size = slot['size']
        color = slot['color']
        cust_id = list(view.customers.keys())[case_index % len(view.customers)] if view else 'SIM-C-5001'
        intents = [
            f"kiem_tra_ton_kho_con_hang_{size}_{color}",
            f"hoi_con_size_khong_{size}_{color}",
            f"check_hang_san_co_{size}_{color}",
            f"hoi_dat_mua_mau_{color}_size_{size}",
            f"xac_nhan_con_hang_trong_kho_{size}_{color}",
            f"thac_mac_so_luong_con_lai_{size}_{color}",
            f"kiem_tra_bien_the_con_hang_{size}_{color}",
            f"hoi_mau_va_size_con_ban_khong_{size}_{color}",
            f"check_kho_san_pham_{size}_{color}",
            f"hoi_mua_ngay_size_{size}_{color}",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_mua_hang",
            intent=intent,
            must_include=[pname, size, color],
            must_not_include=["hết hàng", "tạm hết"],
            length="vừa",
            notes=f"Khách hỏi sản phẩm {pname} màu {color} size {size} còn hàng không",
        )
        case = {
            'id': cid,
            'category': 't02',
            'title': f'Tồn kho còn hàng {pid} {color} {size}',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T02',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T02 inventory in stock {pid}',
                'slot_key': f"{pid}_{color}_{size}",
                'intent': intent,
                'vn_context': [],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi tồn kho {pname} màu {color} size {size}>",
                    'expect': {
                        'tools_called': ['check_inventory'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_all': [size],
                        'answer_any': [['còn hàng', 'sẵn hàng', 'trong kho']],
                        'answer_not': ['tạm hết', 'hết hàng', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'check_inventory', 'arguments': {'product_id': pid, 'size': size, 'color': color}}]},
                        {'say': f"Dạ sản phẩm {pname} (màu {color}, size {size}) hiện vẫn còn hàng trong kho ạ, anh/chị có thể yên tâm đặt hàng nhé ạ."}
                    ]
                }
            ],
            'final_state': {
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T02TonKhoBienTheHetGoiY(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t02_ton_kho_bien_the_het_goi_y', 'T02', 10, description='Tồn kho biến thể hết hàng, gợi ý size/màu khác')

    def select(self, view: Any) -> list[Any]:
        slots = []
        for v in getattr(view, 'out_of_stock_variants', []):
            pid = v.get('product_id')
            p = view.catalog.products.get(pid)
            if p:
                slots.append({
                    'product_id': pid,
                    'name': p['name'],
                    'size': v.get('size') or 'XL',
                    'color': v.get('color') or 'Trắng',
                    'suggest_size': 'M' if (v.get('size') or '').upper() == 'XL' else 'L',
                })
        return slots or [
            {'product_id': 'P-101', 'name': 'Áo thun Essential', 'size': 'XL', 'color': 'Trắng', 'suggest_size': 'L'},
            {'product_id': 'P-102', 'name': 'Áo khoác Everyday', 'size': 'S', 'color': 'Đen', 'suggest_size': 'M'},
            {'product_id': 'P-104', 'name': 'Áo Khoác Gió Bomber 2 Lớp', 'size': 'L', 'color': 'Đen', 'suggest_size': 'M'},
        ]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t02_{case_index:03d}_{self.template_id}"
        pid = slot['product_id']
        pname = slot['name']
        size = slot['size']
        color = slot['color']
        suggest = slot.get('suggest_size', 'M')
        cust_id = list(view.customers.keys())[(case_index + 2) % len(view.customers)] if view else 'SIM-C-5001'
        intents = [
            f"kiem_tra_ton_kho_het_hang_{size}_{color}",
            f"hoi_size_het_hang_goi_y_khac_{size}",
            f"thac_mac_con_hang_khong_{size}_{color}",
            f"check_bien_the_tam_het_{size}_{color}",
            f"hoi_size_{size}_mau_{color}_con_khong",
            f"hoi_san_pham_da_chay_hang_chua_{size}",
            f"kiem_tra_kho_het_size_{size}",
            f"check_hang_size_lon_con_khong_{size}",
            f"hoi_khi_nao_ve_them_size_{size}",
            f"hoi_goi_y_size_thay_the_cho_{size}",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_mua_size_lon",
            intent=intent,
            must_include=[pname, size, color],
            must_not_include=["còn nhiều hàng"],
            length="vừa",
            notes=f"Khách hỏi size {size} của {pname} màu {color}",
        )
        case = {
            'id': cid,
            'category': 't02',
            'title': f'Tồn kho hết hàng {pid} {color} {size}',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T02',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T02 inventory out of stock {pid}',
                'slot_key': f"{pid}_{color}_{size}",
                'intent': intent,
                'vn_context': [],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi tồn kho {pname} màu {color} size {size}>",
                    'expect': {
                        'tools_called': ['check_inventory'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_all': [size],
                        'answer_any': [['tạm hết', 'hết hàng', 'không còn']],
                        'answer_not': ['còn 10 sản phẩm', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'check_inventory', 'arguments': {'product_id': pid, 'size': size, 'color': color}}]},
                        {'say': f"Dạ sản phẩm {pname} (màu {color}, size {size}) hiện đang tạm hết hàng ạ. Anh/chị có thể tham khảo size {suggest} hoặc các màu khác còn hàng nhé ạ."}
                    ]
                }
            ],
            'final_state': {
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T02BaoHanhRiengSanPham(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t02_bao_hanh_rieng_san_pham', 'T02', 10, description='Hỏi thời gian bảo hành riêng theo từng sản phẩm')

    def select(self, view: Any) -> list[Any]:
        # Products with warranty_days > 0 (e.g. P-602 warranty 90, P-301 warranty)
        return [p for p in view.catalog.products.values() if p.get('warranty_days')]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t02_{case_index:03d}_{self.template_id}"
        pid = slot['id']
        pname = slot['name']
        days = slot['warranty_days']
        cust_id = list(view.customers.keys())[case_index % len(view.customers)] if view else 'SIM-C-5001'
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_bao_hanh_sp",
            intent="hoi_thoi_gian_bao_hanh_san_pham",
            must_include=[pname],
            must_not_include=["[KB:"],
            length="vừa",
            notes=f"Khách hỏi sản phẩm {pname} được bảo hành bao lâu",
        )
        case = {
            'id': cid,
            'category': 't02',
            'title': f'Bảo hành riêng sản phẩm {pid}',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T02',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T02 product warranty override for {pid}',
                'vn_context': [],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi bảo hành {pname}>",
                    'expect': {
                        'tools_called': ['get_product'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_all': [str(days)],
                        'answer_any': [['bảo hành', 'tháng', 'ngày']],
                        'answer_not': ['[KB:', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_product', 'arguments': {'product_id': pid}}]},
                        {'say': f"Dạ sản phẩm {pname} có chính sách bảo hành chính hãng trong vòng {days} ngày ạ."}
                    ]
                }
            ],
            'final_state': {
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T02SoSanhHaiMau(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t02_so_sanh_hai_mau', 'T02', 10, description='Hỏi so sánh các màu sắc hoặc biến thể của sản phẩm')

    def select(self, view: Any) -> list[Any]:
        # Products with at least 3 variants
        return [p for p in view.catalog.products.values() if len(p.get('variants', [])) >= 3]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t02_{case_index:03d}_{self.template_id}"
        pid = slot['id']
        pname = slot['name']
        cust_id = list(view.customers.keys())[(case_index + 3) % len(view.customers)] if view else 'SIM-C-5001'
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_phan_van_mau",
            intent="so_sanh_cac_mau_sac_bien_the",
            must_include=[pname],
            must_not_include=["[KB:"],
            length="vừa",
            notes="Khách phân vân giữa các màu của sản phẩm",
        )
        case = {
            'id': cid,
            'category': 't02',
            'title': f'So sánh màu sắc {pid}',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T02',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T02 compare variants for {pid}',
                'vn_context': [],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: phân vân màu sắc {pname}>",
                    'expect': {
                        'tools_called': ['get_product'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_any': [['màu', 'biến thể', 'phiên bản']],
                        'answer_not': ['[KB:', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_product', 'arguments': {'product_id': pid}}]},
                        {'say': f"Dạ sản phẩm {pname} hiện có các phiên bản màu sắc khác nhau để anh/chị lựa chọn. Tùy theo phong cách và sở thích mà anh/chị có thể chọn màu phù hợp nhất nhé ạ."}
                    ]
                }
            ],
            'final_state': {
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T02TuVanSizeThieuBang(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t02_tu_van_size_thieu_bang', 'T02', 10, description='Tư vấn size khi sản phẩm chưa có bảng kích cỡ chi tiết')

    def select(self, view: Any) -> list[Any]:
        # Fashion apparel products
        return [p for p in view.catalog.products.values() if any(k in str(p.get('category', '')).lower() for k in ('áo', 'quần', 'thời trang'))]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t02_{case_index:03d}_{self.template_id}"
        pid = slot['id']
        pname = slot['name']
        cust_id = list(view.customers.keys())[case_index % len(view.customers)] if view else 'SIM-C-5001'
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_hoi_chon_size",
            intent="tu_van_size_quan_ao",
            must_include=[pname],
            must_not_include=["[KB:"],
            length="vừa",
            notes="Khách hỏi cao 1m70 nặng 65kg mặc size nào vừa",
        )
        case = {
            'id': cid,
            'category': 't02',
            'title': f'Tư vấn size {pid}',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T02',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T02 size consultation for {pid}',
                'vn_context': ['doi_size_thoi_trang'],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: tư vấn size {pname}>",
                    'expect': {
                        'tools_called': ['get_product'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_any': [['size', 'kích cỡ', 'chiều cao', 'cân nặng']],
                        'answer_not': ['[KB:'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_product', 'arguments': {'product_id': pid}}]},
                        {'say': f"Dạ với sản phẩm {pname}, thông thường size M phù hợp cho người từ 60-68kg, chiều cao 1m65-1m72 ạ. Nếu thích mặc form rộng rãi thoải mái anh/chị có thể cân nhắc lên size L nhé ạ."}
                    ]
                }
            ],
            'final_state': {
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T02NguonGocChinhHangKhongDuLieu(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t02_nguon_goc_chinh_hang_khong_du_lieu', 'T02', 10, description='Hỏi giấy tờ nguồn gốc / xuất xứ khi catalog không có thông tin')

    def select(self, view: Any) -> list[Any]:
        return list(view.catalog.products.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t02_{case_index:03d}_{self.template_id}"
        pid = slot['id']
        pname = slot['name']
        cust_id = list(view.customers.keys())[(case_index + 4) % len(view.customers)] if view else 'SIM-C-5001'
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_nghi_ngai_nguon_goc",
            intent="hoi_giay_to_chung_nhan_chinh_hang",
            must_include=[pname],
            must_not_include=["[KB:"],
            length="vừa",
            notes="Khách hỏi sản phẩm có giấy tờ hải quan hoặc chứng nhận chính hãng không",
        )
        case = {
            'id': cid,
            'category': 't02',
            'title': f'Nguồn gốc chứng nhận {pid}',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T02',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T02 missing origin cert for {pid}',
                'vn_context': [],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi giấy tờ chứng nhận nguồn gốc {pname}>",
                    'expect': {
                        'tools_called': ['get_product'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_any': [['chính hãng', 'shop cam kết', 'chưa có thông tin']],
                        'answer_not': ['[KB:'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_product', 'arguments': {'product_id': pid}}]},
                        {'say': f"Dạ sản phẩm {pname} được shop phân phối cam kết chính hãng 100%. Về giấy tờ chứng nhận cụ thể, hệ thống trợ lý hiện chưa có thông tin chi tiết; nếu anh/chị cần xem hồ sơ kiểm định có thể liên hệ nhân viên hỗ trợ ạ."}
                    ]
                }
            ],
            'final_state': {
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]


class T02SanPhamKhongCo(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t02_san_pham_khong_co', 'T02', 10, description='Khách tìm kiếm sản phẩm hoàn toàn không tồn tại trong catalog')

    def select(self, view: Any) -> list[Any]:
        return [
            {'query': 'giày patin trẻ em 4 bánh', 'non_pid': 'P-999'},
            {'query': 'bàn chải điện siêu âm', 'non_pid': 'P-998'},
            {'query': 'máy hút bụi mini cầm tay', 'non_pid': 'P-997'},
            {'query': 'áo phao bơi cứu sinh', 'non_pid': 'P-996'},
            {'query': 'kính bơi chống sương mù', 'non_pid': 'P-995'},
            {'query': 'nồi chiên không dầu điện tử', 'non_pid': 'P-994'},
            {'query': 'tai nghe chống ồn bluetooth', 'non_pid': 'P-993'},
            {'query': 'đồng hồ thông minh thể thao', 'non_pid': 'P-992'},
            {'query': 'máy cạo râu tự động', 'non_pid': 'P-991'},
            {'query': 'balo chống gù học sinh', 'non_pid': 'P-990'},
            {'query': 'vợt cầu lông cacbon', 'non_pid': 'P-989'},
            {'query': 'sữa bột tăng cân cho bé', 'non_pid': 'P-988'},
            {'query': 'thảm tập yoga cao su', 'non_pid': 'P-987'},
            {'query': 'kính thực tế ảo vr', 'non_pid': 'P-986'},
            {'query': 'nước hoa vùng kín', 'non_pid': 'P-985'},
        ]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t02_{case_index:03d}_{self.template_id}"
        query = slot['query']
        non_pid = slot['non_pid']
        cust_id = list(view.customers.keys())[case_index % len(view.customers)] if view else 'SIM-C-5001'
        intents = [
            f"tim_kiem_san_pham_khong_kinh_doanh_{case_index}",
            f"hoi_shop_co_ban_khong_{case_index}",
            f"check_mat_hang_ngoai_catalog_{case_index}",
            f"hoi_dat_hang_mon_khong_co_{case_index}",
            f"thac_mac_co_kinh_doanh_khong_{case_index}",
            f"kiem_tra_san_pham_khong_ton_tai_{case_index}",
            f"hoi_mua_mon_khong_co_trong_shop_{case_index}",
            f"tim_mat_hang_la_{case_index}",
            f"check_xem_shop_co_mon_nay_khong_{case_index}",
            f"hoi_san_pham_khong_co_trong_kho_{case_index}",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1",
            case_id=cid,
            turn=1,
            suite=self.suite,
            template=self.template_id,
            style=style,
            persona="khách_hàng_tim_mon_khong_ban",
            intent=intent,
            must_include=[query],
            must_not_include=["còn hàng", "đang bán"],
            length="ngắn",
            notes=f"Khách hỏi shop có bán {query} không",
        )
        case = {
            'id': cid,
            'category': 't02',
            'title': f'Sản phẩm không có: {query}',
            'fixture': 'sft_v1',
            'customer': cust_id,
            'meta': {
                'suite': 'T02',
                'split': 'train',
                'style': style,
                'origin': 'sinh_sft',
                'template': self.template_id,
                'source_note': f'T02 non-existent product search {query}',
                'slot_key': query,
                'intent': intent,
                'vn_context': [],
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi mua {query}>",
                    'expect': {
                        'tools_called': ['search_products'],
                        'max_tool_calls': 1,
                        'action': 'reply',
                        'human_support': False,
                        'answer_any': [['không kinh doanh', 'không có', 'chưa có', 'không tìm thấy']],
                        'answer_not': ['còn hàng trong kho', 'chưa có thông tin [KB:'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_products', 'arguments': {'query': query}}]},
                        {'say': f"Dạ hiện tại shop không kinh doanh mặt hàng '{query}' ạ. Shop chủ yếu cung cấp thời trang và phụ kiện, mời anh/chị tham khảo các sản phẩm khác trên gian hàng nhé ạ."}
                    ]
                }
            ],
            'final_state': {
                'rows': {'order_action_requests': 0, 'handoff_episodes': 0}
            }
        }
        return case, [brief]
