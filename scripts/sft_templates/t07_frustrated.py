"""Templates for Suite T07: Khách hàng bức xúc (60 ca, 5 khung x 12 ca).

Covers:
- Đòi gặp nhân viên trực tiếp (request_human_support)
- Đe dọa bóc phốt / đăng bài mạng xã hội
- Phàn nàn lặp đi lặp lại nhiều lần
- Xin hotline / số điện thoại / Zalo người thật
- Sử dụng ngôn từ gay gắt / mất bình tĩnh
"""
from __future__ import annotations

import random
from typing import Any

from .base import BaseTemplate, Brief


class T07DoiGapNhanVien(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t07_doi_gap_nhan_vien', 'T07', 12, description='Khách yêu cầu gặp trực tiếp nhân viên / người thật')

    def select(self, view: Any) -> list[Any]:
        return list(view.customers.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t07_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_doi_gap_nguoi_that", intent="yeu_cau_chuyen_nhan_vien_ho_tro",
            must_include=["nhân viên"], must_not_include=["request_human_support"], length="ngắn",
            notes="Khách nhắn: 'cho tôi gặp nhân viên, không nói chuyện với bot'",
        )
        case = {
            'id': cid, 'category': 't07', 'title': f'Khách {cust_id} đòi gặp nhân viên', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T07', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T07 human request {cust_id}', 'vn_context': ['buc_xuc_doa_boc_phot']},
            'turns': [
                {
                    'user': "<chờ lời khách: yêu cầu gặp nhân viên trực tiếp>",
                    'expect': {
                        'tools_called': ['request_human_support'], 'max_tool_calls': 1, 'action': 'reply',
                        'human_support': True, 'answer_any': [['nhân viên', 'chăm sóc khách hàng', 'chuyển']], 'answer_not': ['từ chối hỗ trợ'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'request_human_support', 'arguments': {'reason': 'Khách hàng yêu cầu chuyển nhân viên hỗ trợ trực tiếp'}}]},
                        {'say': "Dạ em đã chuyển tiếp cuộc trò chuyện của anh/chị đến bộ phận chăm sóc khách hàng rồi ạ. Nhân viên hỗ trợ sẽ vào tiếp nhận và nhắn tin với mình ngay nhé ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0, 'handoff_episodes': 1}}
        }
        return case, [brief]


class T07DoaDangBai(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t07_doa_dang_bai', 'T07', 12, description='Khách dọa bóc phốt, đăng bài mạng xã hội: xoa dịu và chuyển nhân viên')

    def select(self, view: Any) -> list[Any]:
        return list(view.customers.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t07_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_doa_dang_bai", intent="doa_boc_phot_mang_xa_hoi",
            must_include=["bóc phốt"], must_not_include=["request_human_support"], length="vừa",
            notes="Khách dọa nếu không giải quyết sẽ đăng bài lên hội nhóm Facebook",
        )
        case = {
            'id': cid, 'category': 't07', 'title': f'Khách {cust_id} dọa bóc phốt', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T07', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T07 threat to post {cust_id}', 'vn_context': ['buc_xuc_doa_boc_phot']},
            'turns': [
                {
                    'user': "<chờ lời khách: dọa đăng bài bóc phốt mạng xã hội>",
                    'expect': {
                        'tools_called': ['request_human_support'], 'max_tool_calls': 1, 'action': 'reply',
                        'human_support': True, 'answer_any': [['thông cảm', 'xin lỗi', 'nhân viên', 'hỗ trợ xử lý']], 'answer_not': ['thách thức', 'tùy bạn'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'request_human_support', 'arguments': {'reason': 'Khách bức xúc dọa đăng bài mạng xã hội'}}]},
                        {'say': "Dạ shop rất hiểu sự bức xúc và thành thật xin lỗi anh/chị về trải nghiệm chưa tốt vừa qua ạ. Em đã chuyển ngay trường hợp này tới nhân viên chăm sóc khách hàng để ưu tiên giải quyết thỏa đáng nhất cho mình nhé ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0, 'handoff_episodes': 1}}
        }
        return case, [brief]


class T07PhanNanLapLai(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t07_phan_nan_lap_lai', 'T07', 12, description='Khách phàn nàn lặp đi lặp lại về cùng một vấn đề')

    def select(self, view: Any) -> list[Any]:
        return list(view.customers.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t07_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_phan_nan_nhieu_lan", intent="phan_nan_lap_lai_nhieu_lan",
            must_include=["mấy lần rồi"], must_not_include=["request_human_support"], length="vừa",
            notes="Khách phàn nàn đã nhắn hỏi 3-4 lần mà chưa được xử lý dứt điểm",
        )
        case = {
            'id': cid, 'category': 't07', 'title': f'Khách {cust_id} phàn nàn lặp lại', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T07', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T07 repeated complaint {cust_id}', 'vn_context': ['khieu_nai_san']},
            'turns': [
                {
                    'user': "<chờ lời khách: phàn nàn đã hỏi nhiều lần>",
                    'expect': {
                        'tools_called': ['request_human_support'], 'max_tool_calls': 1, 'action': 'reply',
                        'human_support': True, 'answer_any': [['nhân viên', 'xin lỗi', 'tiếp nhận']], 'answer_not': ['đã hủy thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'request_human_support', 'arguments': {'reason': 'Khách phàn nàn lặp lại nhiều lần'}}]},
                        {'say': "Dạ em rất tiếc vì vấn đề của anh/chị vẫn chưa được xử lý trọn vẹn ạ. Em đã kết nối anh/chị trực tiếp với nhân viên phụ trách để xử lý dứt điểm cho mình ngay ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0, 'handoff_episodes': 1}}
        }
        return case, [brief]


class T07XinHotlineZalo(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t07_xin_hotline_zalo', 'T07', 12, description='Khách xin số điện thoại hotline hoặc Zalo để nói chuyện trực tiếp')

    def select(self, view: Any) -> list[Any]:
        return list(view.customers.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t07_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_doi_so_dien_thoai", intent="xin_hotline_so_dien_thoai_zalo",
            must_include=["số điện thoại"], must_not_include=["request_human_support"], length="ngắn",
            notes="Khách hỏi: 'cho số hotline hoặc số Zalo của quản lý để gọi trực tiếp'",
        )
        case = {
            'id': cid, 'category': 't07', 'title': f'Khách {cust_id} xin số hotline', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T07', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T07 phone hotline request {cust_id}', 'vn_context': ['kenh_zalo_facebook']},
            'turns': [
                {
                    'user': "<chờ lời khách: xin số điện thoại hotline>",
                    'expect': {
                        'tools_called': ['request_human_support'], 'max_tool_calls': 1, 'action': 'reply',
                        'human_support': True, 'answer_any': [['nhân viên', 'hotline', 'hỗ trợ']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'request_human_support', 'arguments': {'reason': 'Khách yêu cầu hotline hỗ trợ trực tiếp'}}]},
                        {'say': "Dạ để hỗ trợ anh/chị nhanh nhất, em đã chuyển yêu cầu đến chuyên viên chăm sóc khách hàng trực tuyến tiếp nhận ngay tại đây rồi ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0, 'handoff_episodes': 1}}
        }
        return case, [brief]


class T07NgonNguGayGat(BaseTemplate):
    def __init__(self) -> None:
        super().__init__('t07_ngon_ngu_gay_gat', 'T07', 12, description='Khách dùng lời lẽ gay gắt, mất bình tĩnh: xoa dịu lịch sự và chuyển nhân viên')

    def select(self, view: Any) -> list[Any]:
        return list(view.customers.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t07_{case_index:03d}_{self.template_id}"
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_nong_gian", intent="dung_tu_ngu_gay_gat_buc_xuc",
            must_include=["làm ăn"], must_not_include=["request_human_support"], length="vừa",
            notes="Khách tức giận nói 'shop làm ăn kiểu gì vậy, quá thất vọng'",
        )
        case = {
            'id': cid, 'category': 't07', 'title': f'Khách {cust_id} gay gắt bức xúc', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T07', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T07 angry customer {cust_id}', 'vn_context': ['buc_xuc_doa_boc_phot']},
            'turns': [
                {
                    'user': "<chờ lời khách: phản ứng gay gắt tức giận>",
                    'expect': {
                        'tools_called': ['request_human_support'], 'max_tool_calls': 1, 'action': 'reply',
                        'human_support': True, 'answer_any': [['thành thật xin lỗi', 'thông cảm', 'nhân viên']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'request_human_support', 'arguments': {'reason': 'Khách hàng bức xúc dùng từ ngữ gay gắt'}}]},
                        {'say': "Dạ em thành thật xin lỗi anh/chị vì sự bất tiện này ạ. Em đã chuyển ngay cuộc trò chuyện đến nhân viên CSKH để lắng nghe và hỗ trợ anh/chị giải quyết ngay ạ."}
                    ]
                }
            ],
            'final_state': {'rows': {'order_action_requests': 0, 'handoff_episodes': 1}}
        }
        return case, [brief]
