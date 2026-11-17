"""Templates for Suite T03: Chính sách cửa hàng có trích dẫn (110 ca).

Covers 11 templates:
1. t03_han_tra_7_ngay (returns.md)
2. t03_doi_size_15_ngay (policy_size_exchange_twoway.md)
3. t03_bao_hanh_90_ngay (policy_warranty_exchange_1to1.md)
4. t03_phi_ship_tra_doi (shipping_fees.md)
5. t03_dieu_kien_huy (cancellation.md)
6. t03_dong_kiem_cod (delivery_inspection.md)
7. t03_thoi_gian_hoan_tien (refunds.md) - 12 đến 72 giờ
8. t03_hoa_don_vat (invoice_vat.md) - chuyển nhân viên, không gửi MST qua chat, hạn 7 ngày
9. t03_khong_co_trong_chinh_sach_si (faq.md) - tra cứu, trả lời chưa có chính sách, không [KB:]
10. t03_khong_co_trong_chinh_sach_tet (store_hours_contact.md) - nghỉ Tết thông báo riêng
11. t03_gio_lam_viec_lien_he (store_hours_contact.md) - 8:00 đến 21:00
"""
from __future__ import annotations

import random
from typing import Any

from .base import BaseTemplate, Brief


class _BasePolicyTemplate(BaseTemplate):
    def __init__(self, template_id: str, doc_key: str, description: str = "") -> None:
        super().__init__(template_id, 'T03', 10, description=description)
        self.doc_key = doc_key

    def select(self, view: Any) -> list[Any]:
        return list(view.customers.values())


class T03HanTra7Ngay(_BasePolicyTemplate):
    def __init__(self) -> None:
        super().__init__('t03_han_tra_7_ngay', 'returns.md', 'Chính sách thời hạn trả hàng trong 7 ngày')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t03_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('returns.md', '7 ngày') if view else {
            'source_key': 'returns.md', 'title': 'Chính sách trả hàng',
            'chunk': 'Khách có quyền gửi yêu cầu trả hàng trong vòng **7 ngày kể từ ngày giao** (ngày giao ghi trong dữ liệu đơn). Sản phẩm phải chưa qua sử dụng, còn tem mác, phụ kiện và quà tặng kèm. Hệ thống tự tính đơn còn trong hạn trả hàng hay không; trợ lý đọc kết quả đó, không tự tính lại.'
        }
        intents = [
            f"hoi_thoi_han_tra_hang_{case_index}",
            f"tra_cuu_chinh_sach_tra_7_ngay_{case_index}",
            f"hoi_duoc_tra_trong_bao_lau_{case_index}",
            f"check_han_tra_hang_quy_dinh_{case_index}",
            f"thac_mac_so_ngay_duoc_tra_{case_index}",
            f"hoi_dieu_kien_tra_hang_7_ngay_{case_index}",
            f"kiem_tra_quy_dinh_thoi_gian_tra_{case_index}",
            f"hoi_nhan_hang_roi_duoc_tra_may_ngay_{case_index}",
            f"check_chinh_sach_tra_san_pham_{case_index}",
            f"xac_nhan_thoi_han_tra_do_{case_index}",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_chinh_sach_tra", intent=intent,
            must_include=["trả hàng"], must_not_include=["7 ngày", "[KB:"], length="ngắn",
            notes="Khách hỏi thời hạn tối đa để trả hàng sau khi nhận",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi thời hạn trả hàng 7 ngày', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': 'T03 return policy 7 days',
                'slot_key': cust_id, 'intent': intent, 'vn_context': []
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi thời hạn trả hàng>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'sources': ['returns.md'], 'answer_all': ['7 ngày'], 'answer_any': [['trả hàng', 'đổi trả']], 'answer_not': ['15 ngày', '30 ngày', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'thời hạn yêu cầu trả hàng kể từ ngày giao'}}]},
                        {'say': f"Dạ theo chính sách của shop, quý khách có quyền gửi yêu cầu trả hàng trong vòng 7 ngày kể từ ngày nhận hàng ạ [{{{{last_tool.results.0.citation_id}}}}]. Sản phẩm cần giữ nguyên tem mác, chưa qua sử dụng nhé ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T03DoiSize15Ngay(_BasePolicyTemplate):
    def __init__(self) -> None:
        super().__init__('t03_doi_size_15_ngay', 'policy_size_exchange_twoway.md', 'Chính sách đổi size trong vòng 15 ngày')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t03_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('policy_size_exchange_twoway.md', '15 ngày') if view else {
            'source_key': 'policy_size_exchange_twoway.md', 'title': 'Chính sách đổi size, đổi màu 2 chiều tận nhà',
            'chunk': 'Khách hàng được hỗ trợ đổi size hoặc đổi màu cho cùng một sản phẩm trong vòng **15 ngày kể từ ngày nhận hàng**. Nhân viên giao hàng mang sản phẩm mới đến và nhận lại sản phẩm đổi cùng một lúc.'
        }
        intents = [
            f"hoi_thoi_han_doi_size_{case_index}",
            f"tra_cuu_chinh_sach_doi_size_15_ngay_{case_index}",
            f"hoi_mac_khong_vua_doi_may_ngay_{case_index}",
            f"check_han_doi_mau_doi_size_{case_index}",
            f"thac_mac_quy_dinh_doi_size_tan_nha_{case_index}",
            f"hoi_thoi_gian_doi_size_ao_quan_{case_index}",
            f"kiem_tra_chinh_sach_doi_15_ngay_{case_index}",
            f"hoi_doi_size_co_duoc_lau_khong_{case_index}",
            f"check_so_ngay_cho_phep_doi_size_{case_index}",
            f"xac_nhan_han_doi_size_hai_chieu_{case_index}",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_doi_size", intent=intent,
            must_include=["đổi size"], must_not_include=["15 ngày", "[KB:"], length="ngắn",
            notes="Khách hỏi mặc không vừa thì được đổi size trong bao lâu",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi thời hạn đổi size 15 ngày', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': 'T03 size exchange 15 days',
                'slot_key': cust_id, 'intent': intent, 'vn_context': ['doi_size_thoi_trang']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi thời hạn đổi size>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'sources': ['policy_size_exchange_twoway.md'], 'answer_all': ['15 ngày'], 'answer_any': [['đổi size', 'đổi màu']], 'answer_not': ['7 ngày', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'thời hạn đổi size đổi màu tận nhà'}}]},
                        {'say': f"Dạ theo chính sách shop hỗ trợ đổi size hoặc đổi màu tận nhà trong vòng 15 ngày kể từ ngày nhận hàng, bưu tá sẽ mang size mới tới giao và thu hồi sản phẩm cũ cùng lúc ạ [{{{{last_tool.results.0.citation_id}}}}]."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T03BaoHanh90Ngay(_BasePolicyTemplate):
    def __init__(self) -> None:
        super().__init__('t03_bao_hanh_90_ngay', 'policy_warranty_exchange_1to1.md', 'Chính sách bảo hành đổi mới 1-1 trong 90 ngày')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t03_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('policy_warranty_exchange_1to1.md', '90 ngày') if view else {
            'source_key': 'policy_warranty_exchange_1to1.md', 'title': 'Chính sách bảo hành, đổi mới 1-1 tận nhà',
            'chunk': 'Thời hạn bảo hành đổi mới tiêu chuẩn là **90 ngày kể từ ngày giao hàng** đối với lỗi do nhà sản xuất (bung chỉ, hỏng khóa kéo, lỗi đường may, rách viền).'
        }
        intents = [
            f"hoi_chinh_sach_bao_hanh_loi_san_xuat_{case_index}",
            f"tra_cuu_bao_hanh_doi_moi_90_ngay_{case_index}",
            f"hoi_loi_khoa_keo_bao_hanh_may_ngay_{case_index}",
            f"check_thoi_gian_bao_hanh_bung_chi_{case_index}",
            f"thac_mac_quy_dinh_doi_1_1_{case_index}",
            f"hoi_do_loi_duoc_bao_hanh_bao_lau_{case_index}",
            f"kiem_tra_che_do_bao_hanh_san_pham_{case_index}",
            f"hoi_bao_hanh_loi_may_mac_{case_index}",
            f"check_chinh_sach_bao_hanh_90_ngay_{case_index}",
            f"xac_nhan_thoi_han_bao_hanh_1_doi_1_{case_index}",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_bao_hanh", intent=intent,
            must_include=["bảo hành"], must_not_include=["90 ngày", "[KB:"], length="ngắn",
            notes="Khách hỏi quần áo lỗi đường chỉ được bảo hành bao lâu",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi bảo hành đổi mới 90 ngày', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': 'T03 warranty policy 90 days',
                'slot_key': cust_id, 'intent': intent, 'vn_context': ['hang_loi']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi thời hạn bảo hành lỗi sản xuất>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'sources': ['policy_warranty_exchange_1to1.md'], 'answer_all': ['90 ngày'], 'answer_any': [['bảo hành', 'đổi mới']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'thời hạn bảo hành đổi mới lỗi nhà sản xuất'}}]},
                        {'say': f"Dạ thời hạn bảo hành đổi mới 1-1 tiêu chuẩn của shop là 90 ngày kể từ ngày nhận hàng đối với lỗi nhà sản xuất như hỏng khóa, bung chỉ ạ [{{{{last_tool.results.0.citation_id}}}}]."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T03PhiShipTraDoi(_BasePolicyTemplate):
    def __init__(self) -> None:
        super().__init__('t03_phi_ship_tra_doi', 'shipping_fees.md', 'Chính sách phí vận chuyển đổi trả')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t03_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('shipping_fees.md', 'đổi size') if view else {
            'source_key': 'shipping_fees.md', 'title': 'Chính sách phí vận chuyển',
            'chunk': 'Cửa hàng miễn phí vận chuyển 2 chiều cho khách đổi size hoặc đổi màu lần đầu trong thời hạn quy định. Trả hàng vì lỗi sản phẩm hoặc giao sai: cửa hàng chịu toàn bộ chi phí vận chuyển.'
        }
        intents = [
            f"hoi_phi_ship_doi_size_{case_index}",
            f"tra_cuu_phi_van_chuyen_tra_hang_{case_index}",
            f"hoi_doi_size_co_mat_phi_ship_khong_{case_index}",
            f"check_chi_phi_giao_nhan_doi_tra_{case_index}",
            f"thac_mac_ai_tra_phi_ship_khi_doi_{case_index}",
            f"hoi_phi_ship_2_chieu_doi_hang_{case_index}",
            f"kiem_tra_quy_dinh_phi_van_chuyen_doi_{case_index}",
            f"hoi_phi_ship_khi_shop_giao_sai_{case_index}",
            f"check_chinh_sach_mien_phi_ship_doi_{case_index}",
            f"xac_nhan_phi_ship_doi_size_lan_dau_{case_index}",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_phi_ship", intent=intent,
            must_include=["phí ship"], must_not_include=["[KB:"], length="ngắn",
            notes="Khách hỏi đổi size thì ai trả phí ship",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi phí ship đổi size', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': 'T03 exchange shipping fee',
                'slot_key': cust_id, 'intent': intent, 'vn_context': []
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi phí ship đổi size>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'sources': ['shipping_fees.md'], 'answer_any': [['miễn phí', '2 chiều', 'shop chịu']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'chính sách phí ship đổi size đổi màu 2 chiều'}}]},
                        {'say': f"Dạ theo chính sách shop miễn phí vận chuyển 2 chiều cho khách hàng đổi size hoặc đổi màu lần đầu trong thời hạn quy định ạ [{{{{last_tool.results.0.citation_id}}}}]."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T03DieuKienHuy(_BasePolicyTemplate):
    def __init__(self) -> None:
        super().__init__('t03_dieu_kien_huy', 'cancellation.md', 'Điều kiện hủy đơn hàng')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t03_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('cancellation.md', 'chờ xử lý') if view else {
            'source_key': 'cancellation.md', 'title': 'Chính sách hủy đơn hàng',
            'chunk': 'Khách hàng có thể hủy đơn hàng tự phục vụ khi đơn ở trạng thái **chờ xử lý (pending)** và chưa bàn giao cho đơn vị vận chuyển.'
        }
        intents = [
            f"hoi_dieu_kien_huy_don_hang_{case_index}",
            f"tra_cuu_chinh_sach_huy_pending_{case_index}",
            f"hoi_khi_nao_duoc_tu_huy_don_{case_index}",
            f"check_dieu_kien_huy_don_tren_he_thong_{case_index}",
            f"thac_mac_trang_thai_nao_thi_huy_duoc_{case_index}",
            f"hoi_chinh_sach_huy_truoc_khi_giao_{case_index}",
            f"kiem_tra_quy_dinh_huy_don_hang_{case_index}",
            f"hoi_huy_don_chua_xuat_kho_{case_index}",
            f"check_quy_trinh_huy_don_pending_{case_index}",
            f"xac_nhan_dieu_kien_huy_don_moi_dat_{case_index}",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_dieu_kien_huy", intent=intent,
            must_include=["hủy đơn"], must_not_include=["[KB:"], length="ngắn",
            notes="Khách hỏi khi nào thì có thể tự hủy đơn hàng",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi điều kiện hủy đơn hàng', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': 'T03 cancellation conditions',
                'slot_key': cust_id, 'intent': intent, 'vn_context': []
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi điều kiện hủy đơn>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'sources': ['cancellation.md'], 'answer_any': [['chờ xử lý', 'pending', 'chưa bàn giao']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'điều kiện tự hủy đơn hàng chờ xử lý pending'}}]},
                        {'say': f"Dạ quý khách có thể tự hủy đơn hàng khi đơn còn ở trạng thái chờ xử lý (pending) và chưa bàn giao cho đơn vị vận chuyển ạ [{{{{last_tool.results.0.citation_id}}}}]."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T03DongKiemCOD(_BasePolicyTemplate):
    def __init__(self) -> None:
        super().__init__('t03_dong_kiem_cod', 'delivery_inspection.md', 'Chính sách đồng kiểm nhận hàng COD')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t03_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('delivery_inspection.md', 'đồng kiểm') if view else {
            'source_key': 'delivery_inspection.md', 'title': 'Chính sách đồng kiểm',
            'chunk': 'Khách có quyền đồng kiểm khi nhận hàng: được mở gói để kiểm tra bên ngoài sản phẩm: đúng mẫu, đúng màu, đúng size, đủ số lượng, không móp vỡ. Bưu tá không hỗ trợ thử đồ hoặc bóc seal niêm phong bảo mật.'
        }
        intents = [
            f"hoi_chinh_sach_dong_kiem_cod_{case_index}",
            f"tra_cuu_quyen_kiem_tra_hang_khi_nhan_{case_index}",
            f"hoi_co_duoc_boc_hang_kiem_tra_khong_{case_index}",
            f"check_quy_dinh_dong_kiem_ngoai_quan_{case_index}",
            f"thac_mac_co_duoc_mac_thu_do_khong_{case_index}",
            f"hoi_kiem_tra_hang_truoc_khi_tra_tien_{case_index}",
            f"kiem_tra_chinh_sach_dong_kiem_{case_index}",
            f"hoi_co_duoc_xem_hang_truoc_khong_{case_index}",
            f"check_quyen_dong_kiem_voi_shipper_{case_index}",
            f"xac_nhan_chinh_sach_kiem_tra_ngoai_quan_{case_index}",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_dong_kiem", intent=intent,
            must_include=["đồng kiểm"], must_not_include=["[KB:"], length="ngắn",
            notes="Khách hỏi nhận hàng COD có được mở ra xem trước không",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi chính sách đồng kiểm COD', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': 'T03 COD delivery inspection',
                'slot_key': cust_id, 'intent': intent, 'vn_context': ['dong_kiem']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi chính sách đồng kiểm>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'sources': ['delivery_inspection.md'], 'answer_any': [['đồng kiểm', 'kiểm tra ngoại quan', 'mặc thử']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'chính sách đồng kiểm bóc gói hàng trước khi trả tiền COD'}}]},
                        {'say': f"Dạ quý khách được quyền mở hộp đồng kiểm ngoại quan sản phẩm trước khi thanh toán COD ạ [{{{{last_tool.results.0.citation_id}}}}]. Tuy nhiên bưu tá không hỗ trợ mặc thử hay thử đồ tại chỗ nhé anh/chị."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T03ThoiGianHoanTien(_BasePolicyTemplate):
    def __init__(self) -> None:
        super().__init__('t03_thoi_gian_hoan_tien', 'refunds.md', 'Thời gian xử lý hoàn tiền 12 đến 72 giờ')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t03_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('refunds.md', '12 đến 72 giờ') if view else {
            'source_key': 'refunds.md', 'title': 'Chính sách hoàn tiền',
            'chunk': 'Sau khi cửa hàng xác nhận hoàn tiền, cổng thanh toán thường xử lý xong trong **12 đến 72 giờ**. Ngân hàng hoặc ví điện tử có thể cần thêm thời gian để tiền hiện trong tài khoản của khách.'
        }
        intents = [
            f"hoi_thoi_gian_nhan_tien_hoan_{case_index}",
            f"tra_cuu_thoi_gian_cong_thanh_toan_hoan_{case_index}",
            f"hoi_bao_lau_nhan_duoc_tien_tra_hang_{case_index}",
            f"check_tien_do_hoan_tien_12_72_gio_{case_index}",
            f"thac_mac_bao_nhieu_gio_thi_tien_ve_{case_index}",
            f"hoi_thoi_gian_hoan_tat_thu_tuc_hoan_{case_index}",
            f"kiem_tra_quy_dinh_thoi_gian_hoan_tien_{case_index}",
            f"hoi_thoi_han_xu_ly_hoan_tien_cua_cong_{case_index}",
            f"check_bao_lau_co_tien_trong_tai_khoan_{case_index}",
            f"xac_nhan_thoi_gian_hoan_tien_chinh_thuc_{case_index}",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_hoan_tien", intent=intent,
            must_include=["hoàn tiền"], must_not_include=["12 đến 72 giờ", "[KB:"], length="ngắn",
            notes="Khách hỏi sau khi trả hàng thì bao lâu tiền về tài khoản",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi thời gian hoàn tiền 12-72h', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': 'T03 refund timeline 12-72h',
                'slot_key': cust_id, 'intent': intent, 'vn_context': ['hoan_tien_cham']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi thời gian nhận tiền hoàn>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'sources': ['refunds.md'], 'answer_any': [['12 đến 72 giờ', '12–72 giờ', '72 giờ']], 'answer_not': ['3 đến 5 ngày', '3-5 ngày', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'thời gian hoàn tiền cổng thanh toán xử lý bao lâu'}}]},
                        {'say': f"Dạ sau khi cửa hàng xác nhận hoàn tiền, cổng thanh toán sẽ xử lý hoàn tất trong vòng 12 đến 72 giờ ạ [{{{{last_tool.results.0.citation_id}}}}]. Sau đó ngân hàng hoặc ví điện tử sẽ cập nhật số dư về tài khoản của quý khách nhé ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T03HoaDonVAT(_BasePolicyTemplate):
    def __init__(self) -> None:
        super().__init__('t03_hoa_don_vat', 'invoice_vat.md', 'Chính sách xuất hóa đơn điện tử VAT')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t03_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('invoice_vat.md', 'VAT') if view else {
            'source_key': 'invoice_vat.md', 'title': 'Hóa đơn VAT, hóa đơn điện tử',
            'chunk': 'Hóa đơn điện tử của đơn hàng do sàn thương mại điện tử hoặc nhà cung cấp hóa đơn điện tử phát hành, không do trợ lý xuất. Khách cần hóa đơn VAT thì trợ lý đề nghị chuyển nhân viên. Nhân viên hướng dẫn khách tự nhập thông tin xuất hóa đơn trên trang của sàn; khách không cần gửi các thông tin này qua khung chat. Nên yêu cầu hóa đơn VAT trong vòng 7 ngày kể từ ngày giao.'
        }
        intents = [
            f"hoi_xuat_hoa_don_vat_{case_index}",
            f"tra_cuu_chinh_sach_hoa_don_do_cong_ty_{case_index}",
            f"hoi_thu_tuc_lay_hoa_don_vat_{case_index}",
            f"check_han_yeu_cau_hoa_don_dien_tu_{case_index}",
            f"thac_mac_gui_ma_so_thue_lay_vat_{case_index}",
            f"hoi_co_xuat_vat_duoc_khong_{case_index}",
            f"kiem_tra_quy_dinh_xuat_hoa_don_cong_ty_{case_index}",
            f"hoi_lay_hoa_don_dien_tu_o_dau_{case_index}",
            f"check_huong_dan_nhap_thong_tin_vat_{case_index}",
            f"xac_nhan_thoi_han_xuat_vat_7_ngay_{case_index}",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_xuat_vat", intent=intent,
            must_include=["hóa đơn VAT"], must_not_include=["[KB:"], length="ngắn",
            notes="Khách hỏi công ty mua hàng muốn lấy hóa đơn đỏ thì làm thế nào",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi xuất hóa đơn VAT', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': 'T03 VAT invoice policy',
                'slot_key': cust_id, 'intent': intent, 'vn_context': ['hoa_don_vat']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi xuất hóa đơn VAT>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'sources': ['invoice_vat.md'], 'answer_all': ['7 ngày'], 'answer_any': [['nhân viên', 'trang của sàn', 'không cần gửi']], 'answer_not': ['gửi mã số thuế qua đây', '48 giờ'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'chính sách xuất hóa đơn điện tử VAT mã số thuế'}}]},
                        {'say': f"Dạ hóa đơn điện tử do sàn thương mại điện tử hoặc nhà cung cấp phát hành, trợ lý không trực tiếp xuất hóa đơn được ạ [{{{{last_tool.results.0.citation_id}}}}]. Em xin phép đề nghị chuyển nhân viên để hỗ trợ hướng dẫn anh/chị tự nhập thông tin xuất hóa đơn trên trang của sàn trong vòng 7 ngày kể từ ngày giao nhé ạ; anh/chị không cần gửi mã số thuế hay thông tin công ty qua khung chat này ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T03KhongCoChinhSachSi(_BasePolicyTemplate):
    def __init__(self) -> None:
        super().__init__('t03_khong_co_trong_chinh_sach_si', 'faq.md', 'Hỏi chính sách mua sỉ / đại lý ngoài phạm vi')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t03_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('faq.md') if view else {
            'source_key': 'faq.md', 'title': 'Câu hỏi thường gặp',
            'chunk': 'Cửa hàng phục vụ khách hàng mua sắm bán lẻ trực tuyến. Các thắc mắc về đơn hàng, vận chuyển, đổi trả vui lòng tra cứu theo các chính sách tương ứng.'
        }
        intents = [
            f"hoi_chinh_sach_mua_si_dai_ly_{case_index}",
            f"hoi_chiet_khau_mua_so_luong_lon_{case_index}",
            f"thac_mac_gia_si_cho_cua_hang_{case_index}",
            f"check_chinh_sach_lay_si_quan_ao_{case_index}",
            f"hoi_dang_ky_lam_dai_ly_phan_phoi_{case_index}",
            f"tra_cuu_chinh_sach_mua_buon_{case_index}",
            f"hoi_gia_si_khi_lay_tren_50_cai_{case_index}",
            f"check_bang_gia_si_ban_buon_{case_index}",
            f"hoi_hop_dong_dai_ly_si_{case_index}",
            f"xac_nhan_chinh_sach_ban_si_{case_index}",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_mua_si", intent=intent,
            must_include=["giá sỉ"], must_not_include=["[KB:"], length="ngắn",
            notes="Khách hỏi mua số lượng lớn làm đại lý thì có chiết khấu bao nhiêu",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi mua sỉ ngoài chính sách', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': 'T03 out-of-policy wholesale',
                'slot_key': cust_id, 'intent': intent, 'vn_context': []
            },
            'knowledge': [],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi chính sách mua sỉ đại lý>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'answer_any': [['bán lẻ', 'chưa có chính sách', 'không có chính sách', 'chưa có thông tin']], 'answer_not': ['[KB:', 'chiết khấu 30%'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'chính sách bán buôn bán sỉ chiết khấu đại lý'}}]},
                        {'say': "Dạ em đã kiểm tra trong kho chính sách nhưng hiện tại shop chưa có thông tin về chính sách bán sỉ hay đại lý ạ. Quý khách có thể theo dõi các chương trình ưu đãi trên gian hàng nhé ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T03KhongCoChinhSachTet(_BasePolicyTemplate):
    def __init__(self) -> None:
        super().__init__('t03_khong_co_trong_chinh_sach_tet', 'store_hours_contact.md', 'Hỏi lịch giao hàng Tết khi chưa có thông báo cụ thể')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t03_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('store_hours_contact.md', 'Tết') if view else {
            'source_key': 'store_hours_contact.md', 'title': 'Giờ làm việc và kênh liên hệ',
            'chunk': 'Nhân viên chăm sóc khách hàng trực từ 8:00 đến 21:00 tất cả các ngày, kể cả thứ Bảy, Chủ nhật và ngày lễ, trừ các ngày nghỉ Tết được thông báo riêng.'
        }
        intents = [
            f"hoi_lich_giao_hang_dip_tet_{case_index}",
            f"tra_cuu_lich_nghi_tet_nguyen_dan_{case_index}",
            f"hoi_tet_shop_nghi_tu_ngay_nao_{case_index}",
            f"check_lich_giao_hang_xuyen_tet_{case_index}",
            f"thac_mac_ngay_lam_viec_dip_tet_{case_index}",
            f"hoi_lich_nghi_tet_am_lich_{case_index}",
            f"kiem_tra_thoi_gian_phuc_vu_tet_{case_index}",
            f"hoi_tet_co_giao_hang_khong_{case_index}",
            f"check_thong_bao_nghi_tet_{case_index}",
            f"xac_nhan_lich_truc_tet_cua_shop_{case_index}",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_lich_tet", intent=intent,
            must_include=["nghỉ Tết"], must_not_include=["[KB:"], length="ngắn",
            notes="Khách hỏi Tết Nguyên Đán shop nghỉ từ ngày nào",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi lịch Tết chưa có thông báo', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': 'T03 missing Tet schedule',
                'slot_key': cust_id, 'intent': intent, 'vn_context': ['nghi_tet']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi lịch nghỉ Tết của shop>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'sources': ['store_hours_contact.md'], 'answer_any': [['thông báo riêng', 'chưa có lịch', 'chưa có thông báo']], 'answer_not': ['nghỉ từ 28 Tết', 'nghỉ từ 29 Tết'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'lịch nghỉ tết nguyên đán thời gian làm việc'}}]},
                        {'say': f"Dạ theo quy định của shop, các ngày nghỉ Tết sẽ được thông báo riêng và hiện tại shop chưa có lịch nghỉ Tết cụ thể ạ [{{{{last_tool.results.0.citation_id}}}}]. Khi có thông báo chính thức, shop sẽ đăng tải công khai để quý khách tiện theo dõi nhé ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T03GioLamViecLienHe(_BasePolicyTemplate):
    def __init__(self) -> None:
        super().__init__('t03_gio_lam_viec_lien_he', 'store_hours_contact.md', 'Hỏi giờ làm việc và các kênh liên hệ chính thức')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t03_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('store_hours_contact.md', 'giờ') if view else {
            'source_key': 'store_hours_contact.md', 'title': 'Giờ làm việc và kênh liên hệ',
            'chunk': 'Nhân viên chăm sóc khách hàng trực từ **8:00 đến 21:00 tất cả các ngày**, kể cả thứ Bảy, Chủ nhật và ngày lễ, trừ các ngày nghỉ Tết được thông báo riêng. Kênh liên hệ của RetailOps Demo là khung chat này. Bản demo không có hotline điện thoại, không có số điện thoại hay email liên hệ khác.'
        }
        intents = [
            f"hoi_gio_lam_viec_cskh_{case_index}",
            f"tra_cuu_khung_gio_truc_chat_{case_index}",
            f"hoi_may_gio_nhan_vien_nghi_{case_index}",
            f"check_gio_hoat_dong_cua_shop_{case_index}",
            f"thac_mac_chu_nhat_co_truc_khong_{case_index}",
            f"hoi_gio_mo_cua_ho_tro_khach_hang_{case_index}",
            f"kiem_tra_thoi_gian_lam_viec_online_{case_index}",
            f"hoi_khung_gio_nhan_vien_ho_tro_{case_index}",
            f"check_gio_truc_tong_dai_chat_{case_index}",
            f"xac_nhan_gio_lam_viec_hang_ngay_{case_index}",
        ]
        intent = intents[(case_index - 1) % len(intents)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_gio_truc", intent=intent,
            must_include=["giờ làm việc"], must_not_include=["[KB:"], length="ngắn",
            notes="Khách hỏi mấy giờ thì có nhân viên trực chat",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi giờ làm việc CSKH', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': 'T03 working hours',
                'slot_key': cust_id, 'intent': intent, 'vn_context': []
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi giờ làm việc của shop>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'sources': ['store_hours_contact.md'], 'answer_any': [['8:00', '21:00', 'hàng ngày', 'giờ làm việc']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'khung giờ làm việc bộ phận chăm sóc khách hàng'}}]},
                        {'say': f"Dạ bộ phận CSKH của shop làm việc từ 8:00 đến 21:00 tất cả các ngày trong tuần (thứ Hai đến Chủ Nhật) ạ [{{{{last_tool.results.0.citation_id}}}}]. Anh/chị có thể nhắn tin trong khung giờ này để được hỗ trợ tức thì nhé ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]
