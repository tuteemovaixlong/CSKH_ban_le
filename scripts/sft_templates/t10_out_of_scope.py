"""Templates for Suite T10: Câu hỏi ngoài phạm vi (40 ca, 4 khung x 10 ca).

Covers:
- Kiến thức chung thế giới (trả lời ngắn hoặc từ chối nhẹ)
- Tính toán số học đơn giản
- Dịch câu sang tiếng nước ngoài
- Tỉ giá ngoại tệ / thời tiết thời gian thực khi không có dữ liệu (không đoán số liệu)
"""
from __future__ import annotations

import random
from typing import Any

from .base import BaseTemplate, Brief


class _BaseOutOfScopeTemplate(BaseTemplate):
    def __init__(self, template_id: str, description: str = "") -> None:
        super().__init__(template_id, 'T10', 10, description=description)

    def select(self, view: Any) -> list[Any]:
        return list(view.customers.values())


class T10KienThucChung(_BaseOutOfScopeTemplate):
    def __init__(self) -> None:
        super().__init__('t10_kien_thuc_chung', 'Hỏi câu hỏi kiến thức phổ thông không liên quan bán hàng')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t10_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        questions = [
            ("Thủ đô của nước Pháp là gì?", "Paris"),
            ("Hành tinh nào gần Mặt Trời nhất?", "Sao Thủy"),
            ("Đỉnh núi cao nhất thế giới tên là gì?", "Everest"),
            ("Nước sôi ở bao nhiêu độ C?", "100"),
            ("Ai là tác giả của Truyện Kiều?", "Nguyễn Du"),
        ]
        q, a = questions[case_index % len(questions)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_do", intent="hoi_kien_thuc_chung", must_include=[q],
            must_not_include=["[KB:"], length="ngắn",
            notes=f"Khách hỏi câu hỏi ngoài lề: {q}",
        )
        case = {
            'id': cid, 'category': 't10', 'title': f'Kiến thức chung {cid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T10', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T10 general knowledge {q}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: {q}>",
                    'expect': {
                        'tools_not_called': ['prepare_order_action', 'search_knowledge'], 'max_tool_calls': 0, 'action': 'reply', 'human_support': False,
                        'answer_all': [a], 'answer_any': [['dạ', 'là']], 'answer_not': ['[KB:', 'chưa có thông tin'],
                    },
                    'fake_model': [
                        {'say': f"Dạ câu trả lời là {a} ạ. Em là trợ lý CSKH của shop thời trang, anh/chị có cần hỗ trợ gì về sản phẩm hoặc đơn hàng không ạ?"}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T10TinhToan(_BaseOutOfScopeTemplate):
    def __init__(self) -> None:
        super().__init__('t10_tinh_toan', 'Yêu cầu tính toán phép tính số học')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t10_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        calcs = [
            ("15 nhân với 8 bằng bao nhiêu?", "120"),
            ("250 cộng 370 bằng mấy?", "620"),
            ("1000 chia cho 4 được mấy?", "250"),
            ("45 nhân 4 bằng mấy?", "180"),
            ("500 trừ đi 175 còn bao nhiêu?", "325"),
        ]
        q, a = calcs[case_index % len(calcs)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_nho_tinh", intent="nho_tinh_toan_so_hoc", must_include=[q],
            must_not_include=["[KB:"], length="ngắn",
            notes=f"Khách hỏi phép tính: {q}",
        )
        case = {
            'id': cid, 'category': 't10', 'title': f'Tính toán số học {cid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T10', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T10 math calculation {q}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: {q}>",
                    'expect': {
                        'tools_not_called': ['prepare_order_action', 'search_knowledge'], 'max_tool_calls': 0, 'action': 'reply', 'human_support': False,
                        'answer_all': [a], 'answer_any': [['kết quả', 'bằng', 'là']], 'answer_not': ['[KB:'],
                    },
                    'fake_model': [
                        {'say': f"Dạ kết quả là {a} ạ. Em là trợ lý của shop, anh/chị cần hỗ trợ gì về mua sắm quần áo nữa không ạ?"}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T10DichCau(_BaseOutOfScopeTemplate):
    def __init__(self) -> None:
        super().__init__('t10_dich_cau', 'Yêu cầu dịch một câu ngắn sang tiếng Anh')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t10_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        phrases = [
            ("Dịch giúp câu: 'Xin chào, chúc bạn một ngày tốt lành' sang tiếng Anh", "have a nice day"),
            ("Câu 'Cảm ơn bạn rất nhiều' tiếng Anh nói thế nào?", "thank you very much"),
            ("Dịch câu 'Tôi muốn mua chiếc áo này' sang tiếng Anh", "I want to buy this shirt"),
            ("Dịch 'Giao hàng tận nơi' sang tiếng Anh", "door-to-door delivery"),
            ("Dịch 'Hàng chất lượng tốt' sang tiếng Anh", "good quality"),
        ]
        q, a = phrases[case_index % len(phrases)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_nho_dich", intent="nho_dich_cau_tieng_anh", must_include=[q],
            must_not_include=["[KB:"], length="ngắn",
            notes=f"Khách nhờ dịch: {q}",
        )
        case = {
            'id': cid, 'category': 't10', 'title': f'Dịch câu tiếng Anh {cid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T10', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T10 translation {q}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: {q}>",
                    'expect': {
                        'tools_not_called': ['prepare_order_action', 'search_knowledge'], 'max_tool_calls': 0, 'action': 'reply', 'human_support': False,
                        'answer_all': [a], 'answer_any': [['dịch', 'tiếng Anh là']], 'answer_not': ['[KB:'],
                    },
                    'fake_model': [
                        {'say': f"Dạ câu này dịch sang tiếng Anh là: \"{a}\" ạ. Anh/chị có cần hỗ trợ gì về sản phẩm của shop nữa không ạ?"}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T10TiGiaThoiTietKhongDuLieu(_BaseOutOfScopeTemplate):
    def __init__(self) -> None:
        super().__init__('t10_ti_gia_thoi_tiet_khong_du_lieu', 'Hỏi thời tiết / tỉ giá tiền tệ không có dữ liệu thời gian thực')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t10_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        questions = [
            "Thời tiết Hà Nội hôm nay thế nào shop ơi?",
            "Tỉ giá USD hôm nay bao nhiêu một đô?",
            "Giá vàng hôm nay bao nhiêu một chỉ?",
            "Thời tiết Sài Gòn chiều nay có mưa không?",
            "Tỉ giá Yên Nhật hôm nay tăng hay giảm?",
        ]
        q = questions[case_index % len(questions)]
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_tin_thoi_su", intent="hoi_thoi_tiet_ti_gia_live", must_include=[q],
            must_not_include=["25.000 VNĐ", "35 độ C", "[KB:"], length="ngắn",
            notes=f"Khách hỏi thông tin thời sự thời gian thực: {q}",
        )
        case = {
            'id': cid, 'category': 't10', 'title': f'Hỏi thời tiết tỉ giá {cid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T10', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T10 realtime data inquiry {q}', 'vn_context': []},
            'turns': [
                {
                    'user': f"<chờ lời khách: {q}>",
                    'expect': {
                        'tools_not_called': ['prepare_order_action', 'search_knowledge'], 'max_tool_calls': 0, 'action': 'reply', 'human_support': False,
                        'answer_any': [['chưa có thông tin', 'không có dữ liệu', 'thời gian thực', 'chuyên biệt']], 'answer_not': ['[KB:'],
                    },
                    'fake_model': [
                        {'say': "Dạ em là trợ lý bán hàng nên không có dữ liệu cập nhật thời gian thực về thời tiết hay tỉ giá tài chính ạ. Anh/chị vui lòng tra cứu trên các ứng dụng thời sự chuyên biệt giúp em nhé."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]
