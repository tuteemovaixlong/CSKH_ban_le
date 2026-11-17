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
            ("Thủ đô của nước Pháp là gì?", "Paris", "Pháp"),
            ("Hành tinh nào gần Mặt Trời nhất?", "Sao Thủy", "Mặt Trời"),
            ("Đỉnh núi cao nhất thế giới tên là gì?", "Everest", "núi cao nhất"),
            ("Nước sôi ở bao nhiêu độ C?", "100", "nước sôi"),
            ("Ai là tác giả của Truyện Kiều?", "Nguyễn Du", "Truyện Kiều"),
            ("Kim tự tháp Giza nằm ở quốc gia nào?", "Ai Cập", "Kim tự tháp"),
            ("Đại dương lớn nhất trên Trái Đất là gì?", "Thái Bình Dương", "Đại dương lớn nhất"),
            ("Loài động vật có vú nào bay được?", "dơi", "động vật có vú"),
            ("Thủ đô của Nhật Bản là thành phố nào?", "Tokyo", "Nhật Bản"),
            ("Vạn Lý Trường Thành nằm ở nước nào?", "Trung Quốc", "Trường Thành"),
        ]
        q, a, key_word = questions[(case_index - 1) % len(questions)]
        intent = f"hoi_kien_thuc_chung_{case_index}"
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_do", intent=intent, must_include=[key_word],
            must_not_include=["[KB:"], length="ngắn",
            notes=f"Khách hỏi câu hỏi kiến thức phổ thông: {q}",
        )
        case = {
            'id': cid, 'category': 't10', 'title': f'Kiến thức chung {cid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T10', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T10 general knowledge {key_word}',
                'slot_key': key_word, 'intent': intent, 'vn_context': []
            },
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
            ("15 nhân với 8 bằng bao nhiêu?", "120", "15"),
            ("250 cộng 370 bằng mấy?", "620", "250"),
            ("1000 chia cho 4 được mấy?", "250", "1000"),
            ("45 nhân 4 bằng mấy?", "180", "45"),
            ("500 trừ đi 175 còn bao nhiêu?", "325", "500"),
            ("12 nhân 12 bằng mấy?", "144", "12"),
            ("85 cộng 45 bằng bao nhiêu?", "130", "85"),
            ("900 chia cho 3 bằng mấy?", "300", "900"),
            ("350 trừ 80 còn bao nhiêu?", "270", "350"),
            ("60 nhân 5 bằng mấy?", "300", "60"),
        ]
        q, a, num_key = calcs[(case_index - 1) % len(calcs)]
        intent = f"nho_tinh_toan_so_hoc_{case_index}"
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_nho_tinh", intent=intent, must_include=[num_key],
            must_not_include=["[KB:"], length="ngắn",
            notes=f"Khách hỏi phép tính: {q}",
        )
        case = {
            'id': cid, 'category': 't10', 'title': f'Tính toán số học {cid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T10', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T10 math calculation {num_key}',
                'slot_key': num_key, 'intent': intent, 'vn_context': []
            },
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
            ("Dịch giúp câu: 'Xin chào, chúc bạn một ngày tốt lành' sang tiếng Anh", "have a nice day", "ngày tốt lành"),
            ("Câu 'Cảm ơn bạn rất nhiều' tiếng Anh nói thế nào?", "thank you very much", "Cảm ơn bạn rất nhiều"),
            ("Dịch câu 'Tôi muốn mua chiếc áo này' sang tiếng Anh", "I want to buy this shirt", "chiếc áo này"),
            ("Dịch 'Giao hàng tận nơi' sang tiếng Anh", "door-to-door delivery", "Giao hàng tận nơi"),
            ("Dịch 'Hàng chất lượng tốt' sang tiếng Anh", "good quality", "chất lượng tốt"),
            ("Dịch câu 'Bạn có khỏe không' sang tiếng Anh", "how are you", "Bạn có khỏe không"),
            ("Dịch 'Hẹn gặp lại bạn' sang tiếng Anh", "see you later", "Hẹn gặp lại"),
            ("Dịch 'Sản phẩm này giá bao nhiêu' sang tiếng Anh", "how much is this product", "giá bao nhiêu"),
            ("Dịch 'Tôi rất thích chiếc áo này' sang tiếng Anh", "I like this shirt", "thích chiếc áo này"),
            ("Dịch 'Chúc mừng sinh nhật' sang tiếng Anh", "happy birthday", "Chúc mừng sinh nhật"),
        ]
        q, a, key_phrase = phrases[(case_index - 1) % len(phrases)]
        intent = f"nho_dich_cau_tieng_anh_{case_index}"
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_nho_dich", intent=intent, must_include=[key_phrase],
            must_not_include=["[KB:"], length="ngắn",
            notes=f"Khách nhờ dịch câu: {q}",
        )
        case = {
            'id': cid, 'category': 't10', 'title': f'Dịch câu tiếng Anh {cid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T10', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T10 translation {key_phrase}',
                'slot_key': key_phrase, 'intent': intent, 'vn_context': []
            },
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
        topics = [
            ("Thời tiết Hà Nội hôm nay thế nào shop ơi?", "Hà Nội", "thời tiết Hà Nội"),
            ("Tỉ giá USD hôm nay bao nhiêu một đô?", "USD", "tỉ giá USD"),
            ("Giá vàng hôm nay bao nhiêu một chỉ?", "giá vàng", "giá vàng"),
            ("Thời tiết Sài Gòn chiều nay có mưa không?", "Sài Gòn", "thời tiết Sài Gòn"),
            ("Tỉ giá Yên Nhật hôm nay tăng hay giảm?", "Yên Nhật", "tỉ giá Yên Nhật"),
            ("Hôm nay Đà Nẵng trời có nắng không shop?", "Đà Nẵng", "thời tiết Đà Nẵng"),
            ("Tỉ giá đồng Euro hôm nay đổi được bao nhiêu?", "Euro", "tỉ giá Euro"),
            ("Dự báo thời tiết Hải Phòng ngày mai thế nào?", "Hải Phòng", "thời tiết Hải Phòng"),
            ("Giá xăng dầu hôm nay tăng bao nhiêu tiền một lít?", "xăng", "giá xăng"),
            ("Chỉ số chứng khoán VN-Index hôm nay bao nhiêu điểm?", "chứng khoán", "chứng khoán"),
        ]
        q, key_item, topic_name = topics[(case_index - 1) % len(topics)]
        intent = f"hoi_thoi_tiet_ti_gia_live_{case_index}"
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_tin_thoi_su", intent=intent, must_include=[key_item],
            must_not_include=["25.000 VNĐ", "35 độ C", "[KB:"], length="ngắn",
            notes=f"Khách hỏi thông tin thời sự thời gian thực: {q}",
        )
        case = {
            'id': cid, 'category': 't10', 'title': f'Hỏi thời tiết tỉ giá {cid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T10', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T10 realtime data inquiry {topic_name}',
                'slot_key': topic_name, 'intent': intent, 'vn_context': []
            },
            'turns': [
                {
                    'user': f"<chờ lời khách: {q}>",
                    'expect': {
                        'tools_not_called': ['prepare_order_action', 'search_knowledge'], 'max_tool_calls': 0, 'action': 'reply', 'human_support': False,
                        'answer_any': [['chưa có thông tin', 'không có dữ liệu', 'thời gian thực', 'chuyên biệt']], 'answer_not': ['[KB:'],
                    },
                    'fake_model': [
                        {'say': "Dạ em là trợ lý bán hàng nên không có dữ liệu cập nhật thời gian thực về thời tiết hay tỉ giá tài chính ạ. Anh/chị vui lòng tra cứu trên các ứng dụng chuyên biệt giúp em nhé."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0}}
        }
        return case, [brief]
