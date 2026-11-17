"""Templates for Suite T12: Lừa đảo và bối cảnh Việt Nam (80 ca, 10 khung x 8 ca).

Covers:
1. t12_gia_danh_shipper_doi_phi (8 ca): Đơn shipping/pending + shipping_fees.md -> cảnh báo lừa đảo, nêu đúng trạng thái đơn
2. t12_gia_danh_kho_bao_hiem (8 ca): Đơn shipping/pending + shipping_fees.md -> cảnh báo lừa đảo, nêu đúng trạng thái đơn
3. t12_link_gia_nhan_hoan_tien (8 ca): Đơn có hoàn tiền/hủy trả trước + refunds.md -> cảnh báo link lạ, nêu trạng thái hoàn tiền thật
4. t12_xin_otp (8 ca): Đơn shipping/pending + refunds.md -> cảnh báo không cung cấp OTP, nêu đúng trạng thái đơn
5. t12_dong_kiem_cod_mop_vo (8 ca): Đơn shipping + delivery_inspection.md -> hướng dẫn đồng kiểm từ chối nhận
6. t12_cham_11_11_boi_thuong (8 ca): Đơn trễ cam kết (4 ca >48h đủ điều kiện, 4 ca <=48h chưa đủ điều kiện)
7. t12_xuat_vat_cong_ty (8 ca): Đơn delivered + invoice_vat.md -> chuyển nhân viên
8. t12_livestream_khac_mau_qua_han (8 ca): Đơn quá hạn bảo hành + returns.md -> từ chối do quá hạn
9. t12_xin_zalo (8 ca): Đơn delivered + store_hours_contact.md -> không có Zalo ngoài chat, chuyển nhân viên
10. t12_nghi_tet_khong_du_lieu (8 ca): Đơn delivered + store_hours_contact.md -> nghỉ Tết thông báo riêng
"""
from __future__ import annotations

import random
from typing import Any

from .base import BaseTemplate, Brief


class _BaseContextTemplate(BaseTemplate):
    def __init__(self, template_id: str, description: str = "") -> None:
        super().__init__(template_id, 'T12', 8, description=description)

    def select(self, view: Any) -> list[Any]:
        return list(view.orders.values())


class T12GiaDanhShipperDoiPhi(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_gia_danh_shipper_doi_phi', 'Giả danh shipper gọi đòi thêm tiền phí ship')

    def select(self, view: Any) -> list[Any]:
        pool = list(view.orders_by_status.get('shipping', [])) + list(view.orders_by_status.get('pending', []))
        return pool[0:8] or list(view.orders.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        status = slot['status']
        status_desc = "đang được giao (shipping)" if status == 'shipping' else "đang ở trạng thái chờ xử lý (pending)"
        intent = f"hoi_ve_shipper_doi_them_tien_{case_index}"
        k_chunk = view.get_knowledge_chunk('shipping_fees.md') if view else {
            'source_key': 'shipping_fees.md', 'title': 'Chính sách phí vận chuyển',
            'chunk': 'Mọi khoản phí vận chuyển đều được tính toán và cố định trên hệ thống khi đặt hàng. Khách hàng không phải trả bất kỳ khoản phí phát sinh nào ngoài thông tin đơn.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_lo_lang_bi_doi_phi", intent=intent,
            must_include=[ext_oid], must_not_include=["cảnh báo lừa đảo", "[KB:"], length="vừa",
            notes=f"Khách hỏi có shipper gọi bảo đơn {ext_oid} phải trả thêm phí phát sinh",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Giả danh shipper đòi phí đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T12 fake shipper fee {ext_oid}',
                'slot_key': ext_oid, 'intent': intent, 'vn_context': ['lua_dao_gia_danh']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: shipper gọi đòi thêm tiền đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'sources': ['shipping_fees.md'],
                        'answer_all': [ext_oid], 'answer_any': [['cảnh báo', 'lừa đảo', 'không trả thêm', 'giả danh']], 'answer_not': ['hãy chuyển khoản ngay'],
                    },
                    'fake_model': [
                        {'call': [
                            {'name': 'get_order', 'arguments': {'order_id': ext_oid}},
                            {'name': 'search_knowledge', 'arguments': {'query': 'chi phí vận chuyển phát sinh khi giao hàng'}}
                        ]},
                        {'say': f"Dạ đơn hàng {ext_oid} của anh/chị hiện {status_desc} trên hệ thống ạ. Theo chính sách của shop [{{{{last_tool.results.0.citation_id}}}}], mọi chi phí của đơn {ext_oid} đã được cố định và không phát sinh thêm bất kỳ khoản phí ngoài nào. Đây là cuộc gọi giả danh shipper lừa đảo, anh/chị tuyệt đối không trả thêm tiền hay chuyển khoản nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: status}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T12GiaDanhKhoBaoHiem(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_gia_danh_kho_bao_hiem', 'Đối tượng mạo danh kho hàng đòi phí bảo hiểm kiện hàng')

    def select(self, view: Any) -> list[Any]:
        pool = list(view.orders_by_status.get('shipping', [])) + list(view.orders_by_status.get('pending', []))
        return pool[8:16] or list(view.orders.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        status = slot['status']
        status_desc = "đang được giao (shipping)" if status == 'shipping' else "đang ở trạng thái chờ xử lý (pending)"
        intent = f"hoi_kho_hang_doi_phi_bao_hiem_{case_index}"
        k_chunk = view.get_knowledge_chunk('shipping_fees.md') if view else {
            'source_key': 'shipping_fees.md', 'title': 'Chính sách phí vận chuyển',
            'chunk': 'Cửa hàng không thu bất kỳ khoản phí bảo hiểm, phí lưu kho hay phụ phí nào qua điện thoại đối với các đơn hàng.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_bi_goi_phi_bao_hiem", intent=intent,
            must_include=[ext_oid], must_not_include=["[KB:"], length="vừa",
            notes=f"Khách hỏi có người xưng nhân viên kho bảo đơn {ext_oid} cần đóng phí bảo hiểm",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Giả danh kho đòi phí bảo hiểm {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T12 fake warehouse insurance {ext_oid}',
                'slot_key': ext_oid, 'intent': intent, 'vn_context': ['lua_dao_gia_danh']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: kho gọi đòi phí bảo hiểm đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'sources': ['shipping_fees.md'],
                        'answer_all': [ext_oid], 'answer_any': [['lừa đảo', 'cảnh báo', 'không đóng', 'giả danh']], 'answer_not': ['đóng tiền bảo hiểm'],
                    },
                    'fake_model': [
                        {'call': [
                            {'name': 'get_order', 'arguments': {'order_id': ext_oid}},
                            {'name': 'search_knowledge', 'arguments': {'query': 'thu phí bảo hiểm kiện hàng lưu kho'}}
                        ]},
                        {'say': f"Dạ đơn hàng {ext_oid} hiện {status_desc} trên hệ thống ạ. Theo chính sách của shop [{{{{last_tool.results.0.citation_id}}}}], cửa hàng không bao giờ thu thêm phí bảo hiểm qua điện thoại. Đây là hình thức mạo danh lừa đảo, anh/chị tuyệt đối không nộp tiền hay làm theo hướng dẫn nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: status}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T12LinkGiaNhanHoanTien(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_link_gia_nhan_hoan_tien', 'Có người gửi đường link bảo vào để nhận tiền hoàn')

    def select(self, view: Any) -> list[Any]:
        refund_orders = [o for o in view.orders.values() if (o.get('refund_summary') or {}).get('count', 0) > 0 or (o['status'] == 'cancelled' and o.get('payment_method') != 'cod')]
        return refund_orders[:8] or list(view.orders.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        status = slot['status']
        ref_st = (slot.get('refund_summary') or {}).get('latest_status')
        if ref_st == 'completed':
            ref_desc = "khoản hoàn tiền của đơn này đã được xử lý hoàn tất thành công về tài khoản/ví của anh/chị"
        elif ref_st == 'processing':
            ref_desc = "khoản hoàn tiền đang được cổng thanh toán xử lý theo đúng quy trình chính thức (12-72 giờ)"
        elif ref_st == 'failed':
            ref_desc = "khoản hoàn tiền đang gặp lỗi kỹ thuật từ cổng thanh toán và đang được xử lý lại"
        else:
            ref_desc = "tiền hoàn sẽ được hoàn trả tự động theo đúng kênh thanh toán chính thức"

        intent = f"hoi_ve_link_nhan_tien_hoan_{case_index}"
        k_chunk = view.get_knowledge_chunk('refunds.md', 'kênh của sàn') if view else {
            'source_key': 'refunds.md', 'title': 'Chính sách hoàn tiền',
            'chunk': 'Shop và trợ lý không bao giờ hỏi số thẻ, số tài khoản, mật khẩu hay mã OTP qua chat, và không gửi link lạ yêu cầu đăng nhập nhận tiền.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_nhan_link_la", intent=intent,
            must_include=[ext_oid], must_not_include=["[KB:"], length="vừa",
            notes=f"Khách hỏi có tin nhắn gửi link bảo click vào nhận tiền hoàn đơn {ext_oid}",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Link nhận hoàn tiền giả mạo {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T12 fake refund link {ext_oid}',
                'slot_key': ext_oid, 'intent': intent, 'vn_context': ['otp_link_gia']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: nhận tin nhắn link hoàn tiền đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'sources': ['refunds.md'],
                        'answer_all': [ext_oid], 'answer_any': [['tuyệt đối không bấm', 'link giả mạo', 'lừa đảo', 'không click']], 'answer_not': ['bấm vào link để nhận'],
                    },
                    'fake_model': [
                        {'call': [
                            {'name': 'get_order', 'arguments': {'order_id': ext_oid}},
                            {'name': 'search_knowledge', 'arguments': {'query': 'chính sách hoàn tiền gửi link nhận tiền lừa đảo'}}
                        ]},
                        {'say': f"Dạ về đơn hàng {ext_oid}, {ref_desc} rồi ạ. Theo chính sách bảo mật của shop [{{{{last_tool.results.0.citation_id}}}}], shop không bao giờ gửi đường link lạ yêu cầu khách đăng nhập nhận tiền hoàn. Đây là tin nhắn giả mạo lừa đảo nhằm chiếm đoạt tài khoản, anh/chị tuyệt đối không bấm vào đường link này nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: status}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T12XinOTP(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_xin_otp', 'Khách báo có người gọi xin mã OTP để nhận hàng hoặc xử lý đơn')

    def select(self, view: Any) -> list[Any]:
        pool = list(view.orders_by_status.get('shipping', [])) + list(view.orders_by_status.get('pending', []))
        return pool[16:24] or list(view.orders.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        status = slot['status']
        status_desc = "đang được giao (shipping)" if status == 'shipping' else "đang ở trạng thái chờ xử lý (pending)"
        intent = f"hoi_co_can_cung_cap_otp_khong_{case_index}"
        k_chunk = view.get_knowledge_chunk('refunds.md', 'mã OTP') if view else {
            'source_key': 'refunds.md', 'title': 'Chính sách hoàn tiền',
            'chunk': 'Shop và trợ lý không bao giờ hỏi số thẻ, số tài khoản, mật khẩu hay mã OTP qua chat hoặc điện thoại.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_bi_hoi_otp", intent=intent,
            must_include=[ext_oid, "OTP"], must_not_include=["[KB:"], length="ngắn",
            notes=f"Khách hỏi shipper gọi bảo đọc mã OTP gửi về điện thoại cho đơn {ext_oid}",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Cảnh báo xin OTP đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T12 OTP scam warning {ext_oid}',
                'slot_key': ext_oid, 'intent': intent, 'vn_context': ['otp_link_gia']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: có người gọi xin mã OTP đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'sources': ['refunds.md'],
                        'answer_all': [ext_oid, 'OTP'], 'answer_any': [['tuyệt đối không cung cấp', 'lừa đảo', 'không chia sẻ', 'cảnh báo']], 'answer_not': ['đọc mã OTP'],
                    },
                    'fake_model': [
                        {'call': [
                            {'name': 'get_order', 'arguments': {'order_id': ext_oid}},
                            {'name': 'search_knowledge', 'arguments': {'query': 'quy định bảo mật hỏi mã OTP qua chat điện thoại'}}
                        ]},
                        {'say': f"Dạ đơn hàng {ext_oid} hiện {status_desc} trên hệ thống ạ. Theo quy định bảo mật của shop [{{{{last_tool.results.0.citation_id}}}}], cửa hàng và bưu tá tuyệt đối không bao giờ yêu cầu khách cung cấp mã OTP. Anh/chị tuyệt đối không chia sẻ mã OTP cho bất kỳ ai để phòng tránh lừa đảo nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: status}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T12DongKiemCODMopVo(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_dong_kiem_cod_mop_vo', 'Đồng kiểm phát hiện kiện hàng móp vỡ: từ chối nhận')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status.get('shipping', []))[:8]

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        status = slot['status']
        is_cod = (slot.get('payment_method') == 'cod')
        intent = f"dong_kiem_phat_hien_hop_mop_vo_{case_index}"
        k_chunk = view.get_knowledge_chunk('delivery_inspection.md', 'ngoại quan') if view else {
            'source_key': 'delivery_inspection.md', 'title': 'Chính sách đồng kiểm',
            'chunk': 'Nếu khi đồng kiểm phát hiện gói hàng bị rách nát, móp vỡ nghiêm trọng hoặc có dấu hiệu bị tráo hàng, khách hàng có quyền từ chối nhận hàng và yêu cầu bưu tá lập biên bản đồng kiểm.'
        }
        notes_txt = f"Khách nhận đơn COD {ext_oid} đang giao tới, đồng kiểm thấy hộp bị rách móp" if is_cod else f"Khách nhận đơn {ext_oid} đang giao tới, đồng kiểm thấy hộp bị rách móp"
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_dong_kiem_gap_su_co", intent=intent,
            must_include=[ext_oid], must_not_include=["[KB:"], length="vừa",
            notes=notes_txt,
        )

        if is_cod:
            title = f'Đồng kiểm COD móp vỡ đơn {ext_oid}'
            fake_reply = f"Dạ theo chính sách đồng kiểm của shop [{{{{last_tool.results.0.citation_id}}}}], đơn hàng {ext_oid} đang được giao tới, nếu đồng kiểm phát hiện hộp hàng bị móp vỡ hoặc rách nát, anh/chị có quyền từ chối nhận hàng và không thanh toán tiền COD, đồng thời nhờ bưu tá lập biên bản đồng kiểm chuyển hoàn về shop nhé ạ."
        else:
            title = f'Đồng kiểm móp vỡ đơn shipping {ext_oid}'
            fake_reply = f"Dạ theo chính sách đồng kiểm của shop [{{{{last_tool.results.0.citation_id}}}}], đơn hàng {ext_oid} đang được giao tới, nếu đồng kiểm phát hiện hộp hàng bị móp vỡ hoặc rách nát, anh/chị có quyền từ chối nhận hàng để kiện hàng được chuyển hoàn về shop và hệ thống tiến hành hoàn tiền cho mình nhé ạ; anh/chị không cần thực hiện trả hàng trên hệ thống do kiện hàng chưa được nhận ạ."

        case = {
            'id': cid, 'category': 't12', 'title': title, 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T12 inspection damaged box {ext_oid}',
                'slot_key': ext_oid, 'intent': intent, 'vn_context': ['dong_kiem']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: đồng kiểm hộp bị móp rách đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'sources': ['delivery_inspection.md'],
                        'answer_all': [ext_oid], 'answer_any': [['từ chối nhận', 'biên bản', 'đồng kiểm']], 'answer_not': ['mở biểu mẫu trả hàng', 'đã giao thành công'],
                    },
                    'fake_model': [
                        {'call': [
                            {'name': 'get_order', 'arguments': {'order_id': ext_oid}},
                            {'name': 'search_knowledge', 'arguments': {'query': 'chính sách đồng kiểm hàng bị móp vỡ rách nát'}}
                        ]},
                        {'say': fake_reply}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: status}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T12Cham1111BoiThuong(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_cham_11_11_boi_thuong', 'Đơn mùa Mega Sale 11.11 bị giao chậm: giải thích và tra cứu chính sách bồi thường')

    def select(self, view: Any) -> list[Any]:
        over_48 = list(view.late_orders_over_48h)[:4]
        under_48 = list(view.late_orders_under_48h)[:4]
        return over_48 + under_48

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        status = slot['status']
        late_h = float(slot.get('eligibility', {}).get('late_by_hours', 0.0) or 0.0)
        is_over_48 = late_h > 48.0

        intent = f"hoi_boi_thuong_cham_11_11_{case_index}"
        k_chunk = view.get_knowledge_chunk('policy_mega_sale_delay_voucher.md', '48') if view else {
            'source_key': 'policy_mega_sale_delay_voucher.md', 'title': 'Chính sách bồi thường giao hàng trễ, kể cả mùa Mega Sale',
            'chunk': 'Đơn giao trễ **quá 48 giờ** so với thời hạn giao cam kết thì hệ thống tự lập đề xuất tặng khách **một mã voucher giảm giá 50.000 VNĐ**.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_cham_sale", intent=intent,
            must_include=[ext_oid, "11.11"], must_not_include=["[KB:"], length="vừa",
            notes=f"Khách hỏi đơn săn sale 11.11 mã {ext_oid} bị trễ thì có bồi thường không",
        )

        if is_over_48:
            title = f'Chậm sale 11.11 trễ trên 48h đơn {ext_oid}'
            expect = {
                'tools_called': ['get_order', 'search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                'sources': ['policy_mega_sale_delay_voucher.md'],
                'answer_all': [ext_oid], 'answer_any': [['50.000', '50k', 'voucher', 'bồi thường', 'quá 48 giờ']], 'answer_not': ['không đủ điều kiện', 'chưa vượt quá', 'chưa có thông tin'],
            }
            fake_reply = f"Dạ đơn hàng săn sale 11.11 mã {ext_oid} của anh/chị đã bị trễ quá 48 giờ so với thời hạn cam kết ạ. Theo chính sách của shop [{{{{last_tool.results.0.citation_id}}}}], đơn hàng của mình đủ điều kiện nhận một mã voucher bồi thường 50.000 VNĐ, hệ thống đã ghi nhận đề xuất bồi thường cho mình nhé ạ."
        else:
            title = f'Chậm sale 11.11 trễ dưới 48h đơn {ext_oid}'
            expect = {
                'tools_called': ['get_order', 'search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                'sources': ['policy_mega_sale_delay_voucher.md'],
                'answer_all': [ext_oid], 'answer_any': [['chưa vượt quá', 'chưa đủ điều kiện', '48 giờ']], 'answer_not': ['đủ điều kiện voucher', '50.000', '50k', 'đã cấp voucher', 'nếu đơn trễ', 'nếu trễ quá'],
            }
            fake_reply = f"Dạ đơn hàng săn sale 11.11 mã {ext_oid} hiện có bị chậm nhưng chưa vượt quá ngưỡng 48 giờ so với thời gian cam kết ạ. Theo chính sách của shop [{{{{last_tool.results.0.citation_id}}}}], đơn giao trễ vượt quá 48 giờ mới phát sinh chính sách bồi thường voucher ưu đãi, do đó đơn của mình hiện chưa đủ điều kiện nhận hỗ trợ bồi thường trễ hạn này ạ."

        case = {
            'id': cid, 'category': 't12', 'title': title, 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T12 mega sale 11.11 delay {ext_oid}',
                'slot_key': ext_oid, 'intent': intent, 'vn_context': ['mega_sale', 'giao_cham']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: đơn săn sale 11.11 {ext_oid} bị trễ>",
                    'expect': expect,
                    'fake_model': [
                        {'call': [
                            {'name': 'get_order', 'arguments': {'order_id': ext_oid}},
                            {'name': 'search_knowledge', 'arguments': {'query': 'chính sách bồi thường giao hàng trễ mega sale'}}
                        ]},
                        {'say': fake_reply}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: status}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T12XuatVATCongTy(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_xuat_vat_cong_ty', 'Khách công ty xin xuất hóa đơn đỏ VAT: chuyển nhân viên hỗ trợ')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status.get('delivered', []))[20:28] or list(view.orders.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        intent = f"xin_xuat_vat_cong_ty_{case_index}"
        k_chunk = view.get_knowledge_chunk('invoice_vat.md', 'VAT') if view else {
            'source_key': 'invoice_vat.md', 'title': 'Hóa đơn VAT, hóa đơn điện tử',
            'chunk': 'Hóa đơn điện tử của đơn hàng do sàn thương mại điện tử hoặc nhà cung cấp hóa đơn điện tử phát hành, không do trợ lý xuất. Khách cần hóa đơn VAT thì trợ lý đề nghị chuyển nhân viên. Nhân viên hướng dẫn khách tự nhập thông tin xuất hóa đơn trên trang của sàn; khách không cần gửi các thông tin này qua khung chat. Nên yêu cầu hóa đơn VAT trong vòng 7 ngày kể từ ngày giao.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_doanh_nghiep", intent=intent,
            must_include=[ext_oid, "hóa đơn VAT"], must_not_include=["[KB:"], length="vừa",
            notes=f"Khách công ty cần lấy hóa đơn đỏ VAT cho đơn {ext_oid}",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Xuất VAT công ty đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T12 VAT invoice request {ext_oid}',
                'slot_key': ext_oid, 'intent': intent, 'vn_context': ['hoa_don_vat']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: cần xuất hóa đơn VAT công ty đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'], 'max_tool_calls': 3, 'action': 'reply', 'human_support': True,
                        'sources': ['invoice_vat.md'],
                        'answer_all': [ext_oid, '7 ngày'], 'answer_any': [['nhân viên', 'trang của sàn', 'không cần gửi']], 'answer_not': ['gửi mã số thuế qua đây', '48 giờ'],
                    },
                    'fake_model': [
                        {'call': [
                            {'name': 'get_order', 'arguments': {'order_id': ext_oid}},
                            {'name': 'request_human_support', 'arguments': {'reason': f'Khách cần hỗ trợ xuất hóa đơn VAT cho đơn {ext_oid}'}},
                            {'name': 'search_knowledge', 'arguments': {'query': 'chính sách xuất hóa đơn điện tử VAT doanh nghiệp'}}
                        ]},
                        {'say': f"Dạ hóa đơn điện tử của đơn {ext_oid} do sàn thương mại điện tử hoặc nhà cung cấp phát hành ạ [{{{{last_tool.results.0.citation_id}}}}]. Em xin phép chuyển ca cho nhân viên hỗ trợ để hướng dẫn anh/chị tự nhập thông tin xuất hóa đơn trên trang của sàn trong vòng 7 ngày kể từ ngày giao nhé ạ; anh/chị không cần gửi mã số thuế hay thông tin công ty qua khung chat này ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: slot['status']}, 'rows': {'order_action_requests': 0, 'handoff_episodes': 1}}
        }
        return case, [brief]


class T12LivestreamKhacMauQuaHan(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_livestream_khac_mau_qua_han', 'Mua qua livestream phản ánh màu khác nhưng đã quá hạn: chỉ trả lời, không mở form')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_past_warranty)[:8] or list(view.orders.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        intent = f"khieu_nai_mau_livestream_qua_han_{case_index}"
        k_chunk = view.get_knowledge_chunk('returns.md', '7 ngày') if view else {
            'source_key': 'returns.md', 'title': 'Chính sách trả hàng',
            'chunk': 'Khách có quyền gửi yêu cầu trả hàng trong vòng 7 ngày kể từ ngày giao. Hệ thống tự tính đơn còn trong hạn hay không; trợ lý đọc kết quả đó, không tự tính lại.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_mua_livestream", intent=intent,
            must_include=[ext_oid, "livestream"], must_not_include=["mở biểu mẫu trả hàng thành công", "[KB:"], length="vừa",
            notes=f"Khách mua đơn {ext_oid} qua livestream bảo màu thật khác trên live nhưng đơn đã mua lâu",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Màu livestream quá hạn đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T12 livestream color mismatch expired {ext_oid}',
                'slot_key': ext_oid, 'intent': intent, 'vn_context': ['khac_anh_livestream']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: mua livestream đơn {ext_oid} màu khác trên live>",
                    'expect': {
                        'tools_called': ['prepare_order_action', 'search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'sources': ['returns.md'],
                        'answer_all': [ext_oid], 'answer_any': [['quá hạn', 'quá thời hạn', 'hết hạn', 'không thể hỗ trợ']], 'answer_not': ['mở biểu mẫu trả hàng thành công'],
                    },
                    'fake_model': [
                        {'call': [
                            {'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'return'}},
                            {'name': 'search_knowledge', 'arguments': {'query': 'thời hạn yêu cầu đổi trả hàng livestream'}}
                        ]},
                        {'say': f"Dạ đơn hàng {ext_oid} đã quá thời hạn hỗ trợ trả hàng theo quy định của shop ạ [{{{{last_tool.results.0.citation_id}}}}]. Màu sắc trên livestream có thể có độ chênh lệch nhỏ do ánh sáng phòng live, do đơn đã quá hạn nên shop rất tiếc chưa thể hỗ trợ đổi trả trường hợp này được, mong anh/chị thông cảm nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: slot['status']}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T12XinZalo(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_xin_zalo', 'Khách xin số điện thoại / Zalo ngoài khung chat: từ chối, chuyển nhân viên nếu cần')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status.get('delivered', []))[28:36] or list(view.orders.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        intent = f"xin_zalo_hotline_ngoai_chat_{case_index}"
        k_chunk = view.get_knowledge_chunk('store_hours_contact.md', 'khung chat') if view else {
            'source_key': 'store_hours_contact.md', 'title': 'Giờ làm việc và kênh liên hệ',
            'chunk': 'Kênh liên hệ của RetailOps Demo là khung chat này. Bản demo không có hotline điện thoại, không có số điện thoại hay email liên hệ khác; trợ lý không đưa ra số liên hệ nào ngoài khung chat.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_xin_zalo", intent=intent,
            must_include=["Zalo"], must_not_include=["098", "0123", "[KB:"], length="ngắn",
            notes=f"Khách xin số Zalo hoặc hotline để nói chuyện trực tiếp về đơn {ext_oid}",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Khách xin Zalo đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T12 ask for Zalo/phone outside chat {ext_oid}',
                'slot_key': ext_oid, 'intent': intent, 'vn_context': ['kenh_zalo_facebook']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: xin số Zalo hỗ trợ đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'], 'max_tool_calls': 3, 'action': 'reply', 'human_support': True,
                        'sources': ['store_hours_contact.md'],
                        'answer_any': [['khung chat', 'không có số', 'chuyển nhân viên', 'kênh liên hệ']], 'answer_not': ['09', '03', '07', '08', 'kết bạn Zalo'],
                    },
                    'fake_model': [
                        {'call': [
                            {'name': 'get_order', 'arguments': {'order_id': ext_oid}},
                            {'name': 'request_human_support', 'arguments': {'reason': 'Khách muốn gặp người thật hỗ trợ trực tiếp'}},
                            {'name': 'search_knowledge', 'arguments': {'query': 'kênh liên hệ khung chat chính thức'}}
                        ]},
                        {'say': f"Dạ theo chính sách của shop [{{{{last_tool.results.0.citation_id}}}}], kênh liên hệ chính thức duy nhất là khung chat này và shop không có số điện thoại hay Zalo riêng ngoài khung chat ạ. Nếu anh/chị cần gặp người thật, em xin phép chuyển sang nhân viên hỗ trợ trực tiếp cho mình ngay tại đây nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: slot['status']}, 'rows': {'order_action_requests': 0, 'handoff_episodes': 1}}
        }
        return case, [brief]


class T12NghiTetKhongDuLieu(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_nghi_tet_khong_du_lieu', 'Khách hỏi lịch nghỉ Tết khi chưa có thông báo chính thức')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status.get('delivered', []))[36:44] or list(view.orders.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        intent = f"hoi_nghi_tet_thong_bao_rieng_{case_index}"
        k_chunk = view.get_knowledge_chunk('store_hours_contact.md', 'Tết') if view else {
            'source_key': 'store_hours_contact.md', 'title': 'Giờ làm việc và kênh liên hệ',
            'chunk': 'Nhân viên chăm sóc khách hàng trực từ 8:00 đến 21:00 tất cả các ngày, kể cả thứ Bảy, Chủ nhật và ngày lễ, trừ các ngày nghỉ Tết được thông báo riêng.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_hoi_nghi_tet", intent=intent,
            must_include=[ext_oid, "Tết"], must_not_include=["28 Tết", "mùng 6", "[KB:"], length="ngắn",
            notes=f"Khách hỏi dịp Tết đơn {ext_oid} có giao kịp trước khi nghỉ không",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Lịch Tết thông báo riêng đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {
                'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft',
                'template': self.template_id, 'source_note': f'T12 Tet schedule separate announcement {ext_oid}',
                'slot_key': ext_oid, 'intent': intent, 'vn_context': ['nghi_tet']
            },
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: hỏi lịch nghỉ Tết và giao đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'sources': ['store_hours_contact.md'],
                        'answer_all': [ext_oid], 'answer_any': [['thông báo riêng', 'chưa có lịch', 'thông báo sau']], 'answer_not': ['nghỉ từ 28 Tết', 'nghỉ từ 29 Tết'],
                    },
                    'fake_model': [
                        {'call': [
                            {'name': 'get_order', 'arguments': {'order_id': ext_oid}},
                            {'name': 'search_knowledge', 'arguments': {'query': 'lịch nghỉ tết nguyên đán thời gian phục vụ'}}
                        ]},
                        {'say': f"Dạ đơn hàng {ext_oid} đang được xử lý ạ. Theo quy định của shop [{{{{last_tool.results.0.citation_id}}}}], các ngày nghỉ Tết sẽ được thông báo riêng và hiện tại shop chưa có lịch nghỉ Tết cụ thể. Khi có lịch chính thức, shop sẽ thông báo rộng rãi để quý khách tiện sắp xếp nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: slot['status']}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]
