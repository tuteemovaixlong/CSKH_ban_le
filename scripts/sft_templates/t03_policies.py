"""Templates for Suite T03: Chính sách cửa hàng có trích dẫn (110 ca).

Covers:
- Hạn trả 7 ngày (returns.md)
- Đổi size 15 ngày (policy_size_exchange_twoway.md)
- Bảo hành 90 ngày (policy_warranty_exchange_1to1.md)
- Phí ship đổi trả (shipping_fees.md)
- Điều kiện hủy đơn (cancellation.md)
- Đồng kiểm COD (delivery_inspection.md)
- Thời gian hoàn tiền (refunds.md)
- Hóa đơn VAT (invoice_vat.md)
- Ngoài chính sách: mua sỉ (không bịa, không trích dẫn)
- Ngoài chính sách: lịch nghỉ Tết (không bịa, không trích dẫn)
- Giờ làm việc và liên hệ (store_hours_contact.md)
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
        # Return customers to associate cases
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
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_chinh_sach_tra", intent="hoi_thoi_han_tra_hang",
            must_include=["trả hàng"], must_not_include=["7 ngày", "[KB:"], length="ngắn",
            notes="Khách hỏi thời hạn tối đa để trả hàng sau khi nhận",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi thời hạn trả hàng 7 ngày', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': 'T03 return policy 7 days', 'vn_context': []},
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
                        {'say': "Dạ theo chính sách của shop, quý khách có quyền gửi yêu cầu trả hàng trong vòng 7 ngày kể từ ngày nhận hàng ạ [{{last_tool.results.0.citation_id}}]. Sản phẩm cần giữ nguyên tem mác, chưa qua sử dụng nhé ạ."}
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
            'chunk': 'Khách hàng được hỗ trợ đổi size hoặc đổi màu cho cùng một sản phẩm trong vòng **15 ngày kể từ ngày nhận hàng**.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_doi_size", intent="hoi_thoi_han_doi_size",
            must_include=["đổi size"], must_not_include=["15 ngày", "[KB:"], length="ngắn",
            notes="Khách hỏi mặc không vừa thì được đổi size trong bao lâu",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi thời hạn đổi size 15 ngày', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': 'T03 size exchange 15 days', 'vn_context': ['doi_size_thoi_trang']},
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
                        {'say': "Dạ shop hỗ trợ đổi size hoặc đổi màu tận nơi trong vòng 15 ngày kể từ ngày nhận hàng ạ [{{last_tool.results.0.citation_id}}]. Shipper sẽ mang size mới tới và thu size cũ về cùng lúc nhé ạ."}
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
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_bao_hanh", intent="hoi_chinh_sach_bao_hanh_loi_san_xuat",
            must_include=["bảo hành"], must_not_include=["90 ngày", "[KB:"], length="ngắn",
            notes="Khách hỏi quần áo lỗi đường chỉ được bảo hành bao lâu",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi bảo hành đổi mới 90 ngày', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': 'T03 warranty policy 90 days', 'vn_context': ['hang_loi']},
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
                        {'say': "Dạ thời hạn bảo hành đổi mới 1-1 tiêu chuẩn của shop là 90 ngày kể từ ngày nhận hàng đối với lỗi nhà sản xuất như hỏng khóa, bung chỉ ạ [{{last_tool.results.0.citation_id}}]."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T03PhiShipTraDoi(_BasePolicyTemplate):
    def __init__(self) -> None:
        super().__init__('t03_phi_ship_tra_doi', 'shipping_fees.md', 'Biểu phí vận chuyển đổi trả')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t03_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('shipping_fees.md', 'đổi') if view else {
            'source_key': 'shipping_fees.md', 'title': 'Phí vận chuyển (phí ship)',
            'chunk': 'Đối với trường hợp đổi size hoặc đổi hàng do lỗi shop, shop hỗ trợ miễn phí vận chuyển 2 chiều. Trường hợp trả hàng theo nhu cầu cá nhân, khách hàng chịu phí ship chiều gửi về theo quy định.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_phi_ship", intent="hoi_phi_ship_doi_tra",
            must_include=["phí ship"], must_not_include=["[KB:"], length="ngắn",
            notes="Khách hỏi đổi size thì ai chịu tiền ship",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi phí ship đổi hàng', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': 'T03 shipping fee return exchange', 'vn_context': []},
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi phí ship khi đổi trả hàng>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'sources': ['shipping_fees.md'], 'answer_any': [['miễn phí', '2 chiều', 'phí ship']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'chi phí vận chuyển khi đổi size trả hàng'}}]},
                        {'say': "Dạ khi đổi size hoặc đổi do lỗi từ shop, shop hỗ trợ miễn phí vận chuyển 2 chiều tận nhà cho anh/chị ạ [{{last_tool.results.0.citation_id}}]."}
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
        k_chunk = view.get_knowledge_chunk('cancellation.md', 'pending') if view else {
            'source_key': 'cancellation.md', 'title': 'Chính sách hủy đơn hàng',
            'chunk': 'Khách có thể gửi yêu cầu hủy đơn khi đơn ở trạng thái **chờ xử lý (pending)**, trước khi đơn chuyển sang đóng gói hoặc bàn giao vận chuyển. Nhắn tin trong chat không tự động hủy đơn; trợ lý sẽ mở biểu mẫu chọn lý do hủy.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_dieu_kien_huy", intent="hoi_dieu_kien_huy_don",
            must_include=["hủy đơn"], must_not_include=["pending", "chờ xử lý", "[KB:"], length="ngắn",
            notes="Khách hỏi khi nào thì hủy được đơn hàng",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi điều kiện hủy đơn hàng', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': 'T03 cancel conditions', 'vn_context': []},
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi điều kiện hủy đơn>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'sources': ['cancellation.md'], 'answer_any': [['chờ xử lý', 'pending', 'chưa giao']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'điều kiện hủy đơn hàng đang chờ xử lý'}}]},
                        {'say': "Dạ quý khách chỉ có thể gửi yêu cầu hủy khi đơn hàng ở trạng thái chờ xử lý (pending), chưa bàn giao cho đơn vị vận chuyển ạ [{{last_tool.results.0.citation_id}}]. Trợ lý sẽ mở biểu mẫu để anh/chị chọn lý do và xác nhận hủy ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T03DongKiemCOD(_BasePolicyTemplate):
    def __init__(self) -> None:
        super().__init__('t03_dong_kiem_cod', 'delivery_inspection.md', 'Chính sách đồng kiểm hàng khi nhận COD')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t03_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('delivery_inspection.md', 'đồng kiểm') if view else {
            'source_key': 'delivery_inspection.md', 'title': 'Chính sách đồng kiểm khi nhận hàng',
            'chunk': 'Khách hàng được quyền kiểm tra ngoại quan kiện hàng (đúng sản phẩm, màu sắc, kích cỡ, số lượng, tình trạng nguyên vẹn không rách tem mác) trước khi thanh toán cho shipper. Không hỗ trợ mặc thử hay sử dụng thử sản phẩm tại chỗ.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_dong_kiem", intent="hoi_chinh_sach_dong_kiem",
            must_include=["đồng kiểm"], must_not_include=["mặc thử", "[KB:"], length="ngắn",
            notes="Khách hỏi có được mở hàng ra xem trước khi trả tiền cho bưu tá không",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi chính sách đồng kiểm COD', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': 'T03 inspection policy', 'vn_context': ['cod', 'dong_kiem']},
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
                        {'say': "Dạ quý khách được quyền mở hộp đồng kiểm ngoại quan sản phẩm trước khi thanh toán COD ạ [{{last_tool.results.0.citation_id}}]. Tuy nhiên bưu tá không hỗ trợ mặc thử hay thử đồ tại chỗ nhé anh/chị."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T03ThoiGianHoanTien(_BasePolicyTemplate):
    def __init__(self) -> None:
        super().__init__('t03_thoi_gian_hoan_tien', 'refunds.md', 'Thời gian xử lý hoàn tiền')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t03_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('refunds.md', 'ngày làm việc') if view else {
            'source_key': 'refunds.md', 'title': 'Chính sách hoàn tiền',
            'chunk': 'Tiền hoàn sẽ được chuyển về tài khoản ban đầu trong vòng **3–5 ngày làm việc** đối với thẻ/tài khoản ngân hàng nội địa, hoặc tối đa 7–14 ngày đối với thẻ tín dụng quốc tế tùy ngân hàng phát hành.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_hoan_tien", intent="hoi_thoi_gian_nhan_tien_hoan",
            must_include=["hoàn tiền"], must_not_include=["3-5 ngày", "[KB:"], length="ngắn",
            notes="Khách hỏi sau khi trả hàng thì bao lâu tiền về tài khoản",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi thời gian hoàn tiền', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': 'T03 refund timeline', 'vn_context': ['hoan_tien_cham']},
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi thời gian nhận tiền hoàn>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'sources': ['refunds.md'], 'answer_any': [['ngày làm việc', 'hoàn tiền', 'ngân hàng']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'thời gian hoàn tiền về tài khoản ngân hàng'}}]},
                        {'say': "Dạ thời gian hoàn tiền về tài khoản ngân hàng thường từ 3 đến 5 ngày làm việc sau khi yêu cầu hoàn tiền được duyệt thành công ạ [{{last_tool.results.0.citation_id}}]."}
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
            'chunk': 'Shop hỗ trợ xuất hóa đơn điện tử VAT cho đơn hàng có yêu cầu trong vòng 48 giờ sau khi đơn giao thành công. Khách hàng vui lòng cung cấp tên công ty, mã số thuế và địa chỉ email nhận hóa đơn.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_xuat_vat", intent="hoi_xuat_hoa_don_vat",
            must_include=["hóa đơn VAT"], must_not_include=["[KB:"], length="ngắn",
            notes="Khách hỏi công ty mua hàng muốn lấy hóa đơn đỏ thì làm thế nào",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi xuất hóa đơn VAT', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': 'T03 VAT invoice', 'vn_context': ['hoa_don_vat']},
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi xuất hóa đơn VAT>",
                    'expect': {
                        'tools_called': ['search_knowledge'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'sources': ['invoice_vat.md'], 'answer_any': [['hóa đơn', 'VAT', 'mã số thuế']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'search_knowledge', 'arguments': {'query': 'chính sách xuất hóa đơn điện tử VAT mã số thuế'}}]},
                        {'say': "Dạ shop có hỗ trợ xuất hóa đơn VAT điện tử cho đơn hàng ạ [{{last_tool.results.0.citation_id}}]. Anh/chị vui lòng cung cấp thông tin mã số thuế, tên công ty và email nhận hóa đơn để nhân viên hỗ trợ xuất hóa đơn nhé ạ."}
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
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_mua_si", intent="hoi_chinh_sach_mua_si_dai_ly",
            must_include=["giá sỉ"], must_not_include=["[KB:"], length="ngắn",
            notes="Khách hỏi mua số lượng lớn làm đại lý thì có chiết khấu bao nhiêu",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi mua sỉ ngoài chính sách', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': 'T03 out-of-policy wholesale', 'vn_context': []},
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi chính sách mua sỉ đại lý>",
                    'expect': {
                        'tools_not_called': ['search_knowledge'], 'max_tool_calls': 0, 'action': 'reply', 'human_support': False,
                        'answer_any': [['bán lẻ', 'chưa có chính sách', 'số lượng lớn', 'chuyên bán lẻ']], 'answer_not': ['[KB:', 'chiết khấu 30%'],
                    },
                    'fake_model': [
                        {'say': "Dạ hiện tại shop chỉ tập trung kinh doanh bán lẻ trực tuyến và chưa có chính sách bán sỉ hay đại lý ạ. Anh/chị có thể theo dõi các chương trình khuyến mãi trên trang để mua với giá tốt nhất nhé ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T03KhongCoChinhSachTet(_BasePolicyTemplate):
    def __init__(self) -> None:
        super().__init__('t03_khong_co_trong_chinh_sach_tet', 'store_hours_contact.md', 'Hỏi lịch giao hàng Tết khi chưa có thông báo')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t03_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_lich_tet", intent="hoi_lich_giao_hang_dip_tet",
            must_include=["nghỉ Tết"], must_not_include=["[KB:"], length="ngắn",
            notes="Khách hỏi Tết Nguyên Đán shop nghỉ từ ngày nào",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi lịch Tết chưa có thông báo', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': 'T03 missing Tet schedule', 'vn_context': ['nghi_tet']},
            'turns': [
                {
                    'user': "<chờ lời khách: hỏi lịch nghỉ Tết của shop>",
                    'expect': {
                        'tools_not_called': ['search_knowledge'], 'max_tool_calls': 0, 'action': 'reply', 'human_support': False,
                        'answer_any': [['chưa có thông báo', 'thông báo sau', 'Tết']], 'answer_not': ['[KB:', 'nghỉ từ 28 Tết'],
                    },
                    'fake_model': [
                        {'say': "Dạ hiện tại shop chưa có thông báo chính thức về lịch nghỉ Tết Nguyên Đán ạ. Khi có lịch cụ thể, shop sẽ cập nhật công khai trên trang chủ và fanpage để quý khách tiện theo dõi nhé ạ."}
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
            'chunk': 'Bộ phận CSKH làm việc từ **8:00 đến 21:00 hàng ngày** (thứ Hai đến Chủ Nhật). Quý khách có thể gửi tin nhắn qua khung chat hoặc gọi hotline chính thức trong khung giờ này để được hỗ trợ nhanh nhất.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_gio_truc", intent="hoi_gio_lam_viec_cskh",
            must_include=["giờ làm việc"], must_not_include=["[KB:"], length="ngắn",
            notes="Khách hỏi mấy giờ thì có nhân viên trực chat",
        )
        case = {
            'id': cid, 'category': 't03', 'title': 'Hỏi giờ làm việc CSKH', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T03', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': 'T03 working hours', 'vn_context': []},
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
                        {'say': "Dạ bộ phận CSKH của shop làm việc từ 8:00 đến 21:00 tất cả các ngày trong tuần (thứ Hai đến Chủ Nhật) ạ [{{last_tool.results.0.citation_id}}]. Anh/chị có thể nhắn tin trong khung giờ này để được hỗ trợ tức thì nhé ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]
