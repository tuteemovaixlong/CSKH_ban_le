"""Templates for Suite T12: Lừa đảo và bối cảnh Việt Nam (80 ca, 8 khung x 10 ca).

Covers:
- Giả danh shipper đòi thêm tiền phí vận chuyển
- Giả danh kho đòi phí bảo hiểm kiện hàng
- Link giả mạo nhận tiền hoàn
- Đối tượng lạ xin mã OTP xác nhận đơn
- Đồng kiểm COD phát hiện kiện hàng móp vỡ
- Giao chậm mùa Mega Sale 11.11 yêu cầu bồi thường
- Xin xuất hóa đơn VAT công ty (chuyển nhân viên hỗ trợ)
- Mua qua livestream màu khác ảnh nhưng đã quá hạn trả hàng (chỉ trả lời, không mở form)
"""
from __future__ import annotations

import random
from typing import Any

from .base import BaseTemplate, Brief


class _BaseContextTemplate(BaseTemplate):
    def __init__(self, template_id: str, description: str = "") -> None:
        super().__init__(template_id, 'T12', 10, description=description)

    def select(self, view: Any) -> list[Any]:
        return list(view.orders.values())


class T12GiaDanhShipperDoiPhi(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_gia_danh_shipper_doi_phi', 'Giả danh shipper gọi đòi thêm tiền phí ship')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_lo_lang_bi_doi_phi", intent="hoi_ve_shipper_doi_them_tien",
            must_include=[ext_oid], must_not_include=["cảnh báo lừa đảo", "[KB:"], length="vừa",
            notes=f"Khách hỏi có shipper gọi bảo đơn {ext_oid} phải trả thêm 50k phí cầu đường",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Giả danh shipper đòi phí đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T12 fake shipper fee {ext_oid}', 'vn_context': ['lua_dao_gia_danh']},
            'turns': [
                {
                    'user': f"<chờ lời khách: shipper gọi đòi thêm tiền đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['cảnh báo', 'lừa đảo', 'không trả thêm', 'giả danh']], 'answer_not': ['hãy chuyển khoản ngay'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ shop cảnh báo đây là cuộc gọi giả danh lừa đảo ạ! Mọi chi phí của đơn {ext_oid} đã được cố định trên hệ thống, anh/chị tuyệt đối không chuyển khoản hay trả thêm bất kỳ khoản phí phát sinh nào ngoài tiền đơn nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: slot['status']}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T12GiaDanhKhoBaoHiem(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_gia_danh_kho_bao_hiem', 'Đối tượng mạo danh kho hàng gọi yêu cầu đóng phí bảo hiểm kiện hàng')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_bi_goi_phi_bao_hiem", intent="hoi_kho_hang_doi_phi_bao_hiem",
            must_include=[ext_oid], must_not_include=["[KB:"], length="vừa",
            notes=f"Khách hỏi có người xưng nhân viên kho bảo đơn {ext_oid} cần đóng 100k bảo hiểm",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Giả danh kho đòi phí bảo hiểm {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T12 fake warehouse insurance {ext_oid}', 'vn_context': ['lua_dao_gia_danh']},
            'turns': [
                {
                    'user': f"<chờ lời khách: kho gọi đòi phí bảo hiểm đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['lừa đảo', 'cảnh báo', 'không đóng', 'giả danh']], 'answer_not': ['đóng tiền bảo hiểm'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ shop khẳng định cửa hàng không bao giờ thu thêm phí bảo hiểm qua điện thoại ạ! Đây là hình thức mạo danh lừa đảo đối với đơn {ext_oid}, anh/chị tuyệt đối không nghe theo nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: slot['status']}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T12LinkGiaNhanHoanTien(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_link_gia_nhan_hoan_tien', 'Có người gửi đường link bảo vào để nhận tiền hoàn')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_nhan_link_la", intent="hoi_ve_link_nhan_tien_hoan",
            must_include=[ext_oid], must_not_include=["[KB:"], length="vừa",
            notes=f"Khách hỏi có tin nhắn gửi link bảo click vào nhận tiền hoàn đơn {ext_oid}",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Link nhận hoàn tiền giả mạo {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T12 fake refund link {ext_oid}', 'vn_context': ['otp_link_gia']},
            'turns': [
                {
                    'user': f"<chờ lời khách: nhận tin nhắn link hoàn tiền đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['tuyệt đối không bấm', 'link giả mạo', 'lừa đảo', 'không click']], 'answer_not': ['bấm vào link để nhận'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đối với đơn hàng {ext_oid}, anh/chị tuyệt đối không bấm vào đường link lạ đó ạ! Shop hoàn tiền trực tiếp qua tài khoản ngân hàng chính thức chứ không bao giờ gửi link yêu cầu đăng nhập nhận tiền, đây là chiêu trò lừa đảo ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: slot['status']}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T12XinOTP(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_xin_otp', 'Khách báo có người gọi xin mã OTP để nhận hàng hoặc xử lý đơn')

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_bi_hoi_otp", intent="hoi_co_can_cung_cap_otp_khong",
            must_include=[ext_oid, "OTP"], must_not_include=["[KB:"], length="ngắn",
            notes=f"Khách hỏi shipper gọi bảo đọc mã OTP gửi về điện thoại cho đơn {ext_oid}",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Cảnh báo xin OTP đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T12 OTP scam warning {ext_oid}', 'vn_context': ['otp_link_gia']},
            'turns': [
                {
                    'user': f"<chờ lời khách: có người xin mã OTP đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['tuyệt đối không cung cấp', 'không đọc OTP', 'bảo mật', 'lừa đảo']], 'answer_not': ['đọc mã OTP'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}]},
                        {'say': f"Dạ đối với đơn hàng {ext_oid}, anh/chị tuyệt đối không cung cấp mã OTP cho bất kỳ ai kể cả người tự xưng là bưu tá hay nhân viên shop ạ! Shop và đơn vị vận chuyển không bao giờ yêu cầu khách cung cấp mã OTP ngân hàng."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: slot['status']}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T12DongKiemCODMopVo(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_dong_kiem_cod_mop_vo', 'Khách đồng kiểm đơn COD phát hiện hộp móp méo / vỡ đồ')

    def select(self, view: Any) -> list[Any]:
        # Delivered or shipping COD orders
        cod_ords = [o for o in view.orders.values() if o.get('payment_method') == 'cod']
        return cod_ords or list(view.orders.values())

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('delivery_inspection.md', 'móp') if view else {
            'source_key': 'delivery_inspection.md', 'title': 'Chính sách đồng kiểm khi nhận hàng',
            'chunk': 'Nếu phát hiện kiện hàng bị rách, móp méo hoặc có dấu hiệu hư hại bên ngoài, khách hàng có quyền từ chối nhận hàng ngay tại chỗ và không thanh toán tiền COD.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_nhan_hang_mop_meo", intent="hoi_xu_ly_khi_dong_kiem_mop_vo",
            must_include=[ext_oid], must_not_include=["[KB:"], length="vừa",
            notes=f"Khách bảo đang đồng kiểm đơn COD {ext_oid} thấy hộp bị móp rách",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Đồng kiểm COD móp vỡ {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T12 COD inspection damage {ext_oid}', 'vn_context': ['cod', 'dong_kiem', 'mop_meo_van_chuyen']},
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: đồng kiểm hộp móp đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'sources': ['delivery_inspection.md'], 'answer_all': [ext_oid],
                        'answer_any': [['từ chối nhận', 'không trả tiền', 'đồng kiểm']], 'answer_not': ['bắt buộc phải nhận'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}, {'name': 'search_knowledge', 'arguments': {'query': 'chính sách đồng kiểm kiện hàng móp méo từ chối nhận'}}]},
                        {'say': f"Dạ theo chính sách đồng kiểm của shop [{{{{last_tool.results.0.citation_id}}}}], nếu kiện hàng đơn {ext_oid} bị móp méo hư hại, anh/chị có quyền từ chối nhận hàng và không thanh toán tiền COD cho bưu tá ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: slot['status']}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T12Cham1111BoiThuong(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_cham_11_11_boi_thuong', 'Giao chậm đợt Mega Sale 11.11 yêu cầu bồi thường voucher')

    def select(self, view: Any) -> list[Any]:
        # Late orders or delivered orders
        return view.late_orders or list(view.orders_by_status['delivered'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        k_chunk = view.get_knowledge_chunk('policy_mega_sale_delay_voucher.md', '48') if view else {
            'source_key': 'policy_mega_sale_delay_voucher.md', 'title': 'Chính sách bồi thường giao hàng trễ, kể cả mùa Mega Sale',
            'chunk': 'Đơn giao trễ **quá 48 giờ** so với thời hạn giao cam kết thì hệ thống tự lập đề xuất tặng khách **một mã voucher giảm giá 50.000 VNĐ**.'
        }
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_san_sale_bi_tre", intent="khiieu_nai_giao_tre_mua_sale",
            must_include=[ext_oid, "11.11"], must_not_include=["[KB:"], length="vừa",
            notes=f"Khách săn sale 11.11 đơn {ext_oid} bị trễ hẹn đòi bồi thường",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Giao trễ sale 11.11 đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T12 mega sale delay voucher {ext_oid}', 'vn_context': ['mega_sale', 'voucher', 'giao_cham']},
            'knowledge': [k_chunk],
            'turns': [
                {
                    'user': f"<chờ lời khách: săn sale 11.11 đơn {ext_oid} giao trễ>",
                    'expect': {
                        'tools_called': ['get_order', 'search_knowledge'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': False,
                        'sources': ['policy_mega_sale_delay_voucher.md'], 'answer_all': [ext_oid],
                        'answer_any': [['voucher', 'bồi thường', '50.000', '48 giờ']], 'answer_not': ['chưa có thông tin'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'get_order', 'arguments': {'order_id': ext_oid}}, {'name': 'search_knowledge', 'arguments': {'query': 'chính sách bồi thường giao hàng trễ mùa sale voucher'}}]},
                        {'say': f"Dạ shop rất xin lỗi vì lượng đơn đợt Mega Sale 11.11 tăng cao làm đơn {ext_oid} bị chậm trễ. Theo chính sách [{{{{last_tool.results.0.citation_id}}}}], nếu đơn trễ quá 48 giờ so với cam kết, shop sẽ gửi tặng voucher bồi thường 50.000 VNĐ ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: slot['status']}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]


class T12XuatVATCongTy(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_xuat_vat_cong_ty', 'Khách xin xuất hóa đơn VAT công ty: hướng dẫn và chuyển nhân viên')

    def select(self, view: Any) -> list[Any]:
        return list(view.orders_by_status['delivered'])

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_doanh_nghiep_lay_vat", intent="yeu_cau_xuat_hoa_don_vat_doanh_nghiep",
            must_include=[ext_oid, "công ty"], must_not_include=["request_human_support"], length="vừa",
            notes=f"Khách yêu cầu xuất hóa đơn đỏ VAT cho công ty đơn {ext_oid}",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Xuất VAT công ty đơn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T12 VAT invoice handoff {ext_oid}', 'vn_context': ['hoa_don_vat']},
            'turns': [
                {
                    'user': f"<chờ lời khách: xin hóa đơn VAT công ty đơn {ext_oid}>",
                    'expect': {
                        'tools_called': ['request_human_support'], 'max_tool_calls': 2, 'action': 'reply', 'human_support': True,
                        'answer_all': [ext_oid], 'answer_any': [['hóa đơn VAT', 'nhân viên', 'mã số thuế']], 'answer_not': ['từ chối xuất hóa đơn'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'request_human_support', 'arguments': {'reason': f'Khách yêu cầu xuất hóa đơn VAT công ty cho đơn {ext_oid}'}}]},
                        {'say': f"Dạ để hỗ trợ xuất hóa đơn VAT công ty cho đơn {ext_oid}, em đã chuyển tiếp yêu cầu đến nhân viên kế toán. Nhân viên sẽ tiếp nhận mã số thuế và thông tin công ty để gửi hóa đơn điện tử cho mình ngay nhé ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: slot['status']}, 'rows': {'order_action_requests': 0, 'handoff_episodes': 1}}
        }
        return case, [brief]


class T12LivestreamKhacMauQuaHan(_BaseContextTemplate):
    def __init__(self) -> None:
        super().__init__('t12_livestream_khac_mau_qua_han', 'Hàng mua qua livestream khác màu ảnh nhưng đã quá hạn trả hàng: chỉ trả lời, không mở form')

    def select(self, view: Any) -> list[Any]:
        # Delivered orders past 7 days (delivered_8_to_15 or 16_to_90)
        return list(view.delivered_8_to_15) or list(view.delivered_16_to_90)

    def build(self, slot: Any, rng: random.Random, case_index: int, style: str, view: Any = None) -> tuple[dict[str, Any], list[Brief]]:
        cid = f"t12_{case_index:03d}_{self.template_id}"
        ext_oid = slot['external_order_id']
        cust_id = slot['external_customer_id']
        brief = Brief(
            brief_id=f"brf_{cid}_t1", case_id=cid, turn=1, suite=self.suite, template=self.template_id, style=style,
            persona="khách_hàng_mua_livestream", intent="khieu_nai_mau_khac_anh_livestream_qua_han",
            must_include=[ext_oid, "livestream"], must_not_include=["mở biểu mẫu trả hàng thành công"], length="vừa",
            notes=f"Khách mua qua livestream bảo màu không giống trên live nhưng đơn {ext_oid} đã nhận quá 7 ngày",
        )
        case = {
            'id': cid, 'category': 't12', 'title': f'Khác màu livestream quá hạn {ext_oid}', 'fixture': 'sft_v1', 'customer': cust_id,
            'meta': {'suite': 'T12', 'split': 'train', 'style': style, 'origin': 'sinh_sft', 'template': self.template_id, 'source_note': f'T12 livestream color mismatch past window {ext_oid}', 'vn_context': ['khac_anh_livestream']},
            'turns': [
                {
                    'user': f"<chờ lời khách: mua livestream đơn {ext_oid} khác màu ảnh>",
                    'expect': {
                        'tools_called': ['prepare_order_action'], 'max_tool_calls': 1, 'action': 'reply', 'human_support': False,
                        'answer_all': [ext_oid], 'answer_any': [['quá thời hạn', 'quá 7 ngày', 'hết hạn', 'không thể hỗ trợ trả']], 'answer_not': ['mở biểu mẫu trả hàng thành công'],
                    },
                    'fake_model': [
                        {'call': [{'name': 'prepare_order_action', 'arguments': {'order_id': ext_oid, 'action_type': 'return'}}]},
                        {'say': f"Dạ đơn hàng {ext_oid} đã quá thời hạn 7 ngày trả hàng quy định rồi ạ. Do góc quay và ánh sáng livestream có thể có độ chênh lệch màu nhẹ, rất tiếc hiện tại hệ thống không thể mở yêu cầu trả hàng cho đơn này được nữa, mong anh/chị thông cảm ạ."}
                    ]
                }
            ],
            'final_state': {'orders': {ext_oid: 'delivered'}, 'rows': {'order_action_requests': 0}}
        }
        return case, [brief]
