"""T14: phiếu nghiệp vụ chuyển nhân viên và đối chứng; không chứa lời khách."""
from __future__ import annotations

from functools import lru_cache
from .base import BaseTemplate, Brief
from .t13_gap_fill import _track

NAMES = [
    'doi_nguoi_khong_dau', 'doi_nguoi_vong_vo', 'bot_khong_hieu_doi_nguoi',
    'doa_khieu_nai_san', 'doa_kien', 'doa_dang_bai_khac_tu', 'doi_dia_chi_giao',
    'doi_nguoi_nhan', 'khoi_phuc_don_huy', 'khieu_nai_shipper_nho_xu_ly',
    'khieu_nai_shipper_chi_phan_anh', 'hoi_roi_doi_nguoi', 'chuyen_nha_doi_dia_chi',
    'hoi_gio_lam_viec', 'nhac_shipper_hoi_don', 'khen_nhan_vien_roi_hoi',
    'buc_lan_dau_hoi_don', 'buc_don_co_van_de',
]
INTENTS = [
    ['Yêu cầu trao đổi với con người bằng lối viết không dấu.'],
    ['Diễn đạt gián tiếp mong muốn có người tiếp nhận trao đổi.'],
    ['Hỏi tiến độ đơn hàng.', 'Không hài lòng vì bot phản hồi chung chung và muốn người tiếp nhận.'],
    ['Muốn hủy đơn đang vận chuyển.', 'Dọa phản ánh lên nền tảng bán hàng hoặc đánh giá tiêu cực do không hủy được.'],
    ['Đe dọa khởi kiện cửa hàng vì sản phẩm lỗi gây mất an toàn.'],
    ['Dọa công khai trải nghiệm tiêu cực trên mạng xã hội bằng cách diễn đạt khác từ khóa cố định.'],
    ['Xin thay địa chỉ nhận hàng của đơn chưa giao.'],
    ['Muốn thay người nhận hoặc số liên hệ người nhận của đơn chưa giao.'],
    ['Muốn gỡ trạng thái hủy để nhận lại đơn.', 'Tiếp tục yêu cầu xử lý gỡ hủy vì cần hàng gấp.'],
    ['Phản đối lần báo không liên lạc được dù đã ở nhà; đơn chưa tới hoặc đã hoàn; nhờ shop khiếu nại hãng hoặc thu xếp giao lại.'],
    ['Đã nhận hàng sau giao lại, chỉ thắc mắc lịch sử bị ghi không nghe máy dù có mặt; không yêu cầu shop thực hiện công việc khác.'],
    ['Hỏi tình hình đơn.', 'Hỏi chính sách đồng kiểm khi nhận hàng.', 'Muốn trao đổi tiếp với con người.'],
    ['Hỏi thông tin sản phẩm được nêu trong phiếu.', 'Báo mới chuyển nơi ở, muốn đổi địa chỉ nhận đơn đang vận chuyển.'],
    ['Hỏi thời gian làm việc của bộ phận chăm sóc khách, gồm ngày cuối tuần.'],
    ['Nhắc người giao hàng khi hỏi kiện hàng hiện ở đâu; không yêu cầu gặp người tư vấn.'],
    ['Khen người từng tư vấn rồi hỏi thời hạn đổi kích cỡ.'],
    ['Bực vì chờ nhưng đây là lần hỏi đầu, chỉ muốn biết tiến độ đơn đang giao bình thường.'],
    ['Bực trong lần liên hệ đầu về đơn có vấn đề giao hàng thực tế, chưa đòi người hay đe dọa.'],
]
NO_REPEAT = ['mấy lần rồi', 'lần thứ', 'nhắn hoài']
NO_TRANSFER = ['đã chuyển cuộc trò chuyện', 'đã kết nối nhân viên']
FAKE_ACTION = ['hủy thành công', 'đã hoàn tiền', 'đã xử lý xong']
ORDER_TOOLS = ['list_orders', 'get_order', 'track_shipment']


@lru_cache(maxsize=2)
def shipment_slots(view):
    # track_shipment đọc shipment_events qua cùng công cụ mà model dùng.
    return [(o, _track(view, o).get('shipment') or {})
            for o in sorted(view.orders.values(), key=lambda o: o['external_order_id'])]


class HandoffTemplate(BaseTemplate):
    def __init__(self, number):
        self.number = number
        styles = ['khong_dau', 'teencode', 'sai_chinh_ta'] if number <= 6 else None
        super().__init__('t14_' + NAMES[number - 1], 'T14', 10, allowed_styles=styles,
                         description=INTENTS[number - 1][-1])

    def select(self, view):
        n = self.number
        slots = []
        for order, shipment in shipment_slots(view):
            status = order['status']
            events = shipment.get('events') or []
            failed_contact = any(any(p in str(e.get('fail_reason') or '').lower()
                                     for p in ('không liên lạc', 'không nghe máy')) for e in events)
            if n == 10:
                keep = failed_contact and shipment.get('status') in ('returned', 'delivery_failed')
            elif n == 11:
                keep = failed_contact and status == 'delivered' and shipment.get('status') == 'delivered'
            elif n == 9:
                keep = status == 'cancelled'
            elif n == 5:
                keep = status == 'delivered'
            elif n == 18:
                keep = shipment.get('status') in ('returned', 'delivery_failed') or (
                    status == 'shipping' and order.get('eligibility', {}).get('is_late_vs_promised'))
            elif n in (4, 13, 15, 17):
                keep = status == 'shipping' and shipment.get('status') == 'in_transit'
            else:
                keep = status in ('pending', 'shipping')
            if keep:
                slots.append(order)
        if len(slots) * 3 < self.target:
            raise ValueError(f'{self.template_id}: chỉ có {len(slots)} đơn, không đủ {self.target} ca với trần 3 lần/đơn')
        return slots

    def build(self, slot, rng, case_index, style, view=None):
        n = self.number
        cid = f't14_{case_index:03d}_{self.template_id}'
        oid = slot['external_order_id']
        intents = INTENTS[n - 1]
        knowledge = {}

        def call(name, **arguments):
            return {'call': [{'name': name, 'arguments': arguments}]}

        def turn(kind, *, source=None, handoff=False, optional=False, banned=None, order_answer=False):
            expect = {'action': 'reply', 'max_tool_calls': 3, 'answer_not': list(banned or FAKE_ACTION)}
            fake = []
            answer = ''
            if kind == 'order':
                expect['tools_any'] = [list(ORDER_TOOLS)]
                fake.append(call('get_order', order_id=oid))
                answer = f'Đã tra dữ liệu đơn {oid}. '
            elif kind == 'track':
                expect['tools_called'] = ['track_shipment']
                fake.append(call('track_shipment', order_id=oid))
                answer = f'Đã đối chiếu hành trình đơn {oid}. '
            elif kind == 'product':
                pid = sorted(view.catalog.products)[0]
                expect['tools_called'] = ['get_product']
                fake.append(call('get_product', product_id=pid))
                answer = 'Đã tra thông tin sản phẩm trong danh mục. '
            if source:
                knowledge[source] = view.get_knowledge_chunk(source)
                expect.setdefault('tools_called', []).append('search_knowledge')
                expect['sources'] = [source]
                fake.append(call('search_knowledge', query=knowledge[source]['title']))
                answer += 'Chính sách [{{last_tool.results.0.citation_id}}]. '
            if handoff:
                expect.setdefault('tools_called', []).append('request_human_support')
                expect['human_support'] = True
                expect['answer_any'] = [['nhân viên', 'tư vấn viên', 'bộ phận', 'chuyển', 'hỗ trợ']]
                fake.append(call('request_human_support', reason=self.description))
                if source:
                    # Gateway giả chỉ nội suy kết quả tool cuối; gom cùng bước và
                    # để kết quả KB ở cuối như các khung T12 có sẵn.
                    search_step, handoff_step = fake[-2:]
                    fake[-2:] = [{'call': handoff_step['call'] + search_step['call']}]
                answer += 'Xin lỗi về trải nghiệm này; đã chuyển tới nhân viên hỗ trợ.'
            elif not optional:
                expect['human_support'] = False
                expect.setdefault('tools_not_called', []).append('request_human_support')
                expect['answer_not'] += NO_TRANSFER
            if order_answer:
                expect['answer_all'] = [oid]
            if n == 11:
                expect['answer_any'] = [['đã giao', 'đã nhận'], ['không liên lạc', 'không nghe máy', 'giao thất bại']]
                answer += 'Đơn đã giao sau lần không liên lạc được. Nếu cần, anh/chị có muốn chuyển bộ phận phụ trách không?'
            fake.append({'say': answer or 'Thông tin đã được tra từ kho kiến thức.'})
            return {'user': '', 'expect': expect, 'fake_model': fake}

        if n in (1, 2):
            turns = [turn('none', handoff=True, banned=['từ chối chuyển', 'không thể chuyển', 'đã xử lý xong'])]
        elif n == 3:
            turns = [turn('order'), turn('none', handoff=True)]
        elif n == 4:
            turns = [turn('order', banned=['hủy thành công']), turn('none', handoff=True, banned=FAKE_ACTION)]
        elif n == 5:
            turns = [turn('none', handoff=True, banned=['tòa án có thẩm quyền', 'thuê luật sư', 'hoàn tiền thành công', 'đổi hàng thành công'])]
        elif n == 6:
            turns = [turn('none', handoff=True, banned=['cam kết đền bù', 'tặng voucher'])]
            turns[0]['expect']['answer_any'] = [['xin lỗi', 'thông cảm', 'nhân viên', 'hỗ trợ']]
        elif n in (7, 13):
            address = turn('none', handoff=True, banned=['đã đổi địa chỉ', 'cập nhật địa chỉ thành công', 'đã cập nhật địa chỉ'])
            turns = [address] if n == 7 else [turn('product'), address]
        elif n == 8:
            turns = [turn('none', handoff=True, banned=['đã đổi người nhận', 'đã cập nhật số điện thoại', 'đã đổi tên người nhận'])]
        elif n == 9:
            turns = [turn('order', optional=True, banned=['đã khôi phục', 'giao ngay']),
                     turn('none', handoff=True, banned=['đã khôi phục', 'giao ngay'])]
        elif n in (10, 11):
            turns = [turn('order' if n == 10 else 'track', source='policy_shipper_complaint.md',
                          handoff=n == 10, order_answer=True,
                          banned=['đã gửi khiếu nại tới hãng', 'cam kết giao lại lúc', 'chắc chắn giao lại trong'])]
        elif n == 12:
            turns = [turn('order'), turn('none', source='delivery_inspection.md'), turn('none', handoff=True)]
        elif n == 14:
            turns = [turn('none', source='store_hours_contact.md')]
        elif n == 15:
            turns = [turn('track')]
        elif n == 16:
            turns = [turn('none', source='policy_size_exchange_twoway.md')]
        else:
            turns = [turn('order', optional=n == 18, order_answer=True,
                          banned=['giao thất bại', 'đã hoàn tiền'] if n == 17 else ['cam kết đền bù', 'tặng voucher'])]
        briefs = []
        for k, intent in enumerate(intents, 1):
            needs_order = n in (3, 4, 7, 8, 9, 10, 11, 12, 13, 15, 17, 18) and not (n == 13 and k == 1)
            ban_repeat = n in (11, 14, 15, 16, 17, 18) or turns[k-1]['expect'].get('human_support') is False
            note = 'Mô tả ý định bằng cách viết tự nhiên; tránh các cụm yêu cầu con người hoặc đe dọa cố định mà rào bắt khi viết có dấu.'
            if k > 1:
                note += ' Giữ ngữ cảnh các lượt trước của cùng phiếu ca.'
            if n == 13 and k == 1:
                product = view.catalog.products[sorted(view.catalog.products)[0]]
                note += f" Sản phẩm trong danh mục: {product['name']}."
            briefs.append(Brief(
                brief_id=f'brf_{cid}_t{k}', case_id=cid, turn=k, suite='T14', template=self.template_id,
                style=style, persona='khách_mua_lẻ_' + NAMES[n-1], intent=intent,
                must_include=[oid] if needs_order else [], must_not_include=list(NO_REPEAT) if ban_repeat else [],
                earlier_turns=[{'turn': j+1, 'intent': intents[j]} for j in range(k-1)],
                notes=note, rail_pass=True))
        rows = {'order_action_requests': 0, 'handoff_episodes': int(any(t['expect'].get('human_support') for t in turns))}
        if n == 18:
            rows.pop('handoff_episodes')
        case = {
            'id': cid, 'category': 't14', 'title': self.description, 'fixture': 'sft_v1',
            'customer': slot['external_customer_id'],
            'meta': {'suite': 'T14', 'split': 'train', 'origin': 'sinh_sft', 'style': style,
                     'template': self.template_id, 'source_note': 'T14 nghiệp vụ chuyển nhân viên và đối chứng',
                     'slot_key': oid, 'intent': f'{self.template_id}_{case_index}', 'vn_context': []},
            'turns': turns, 'final_state': {'orders': {oid: slot['status']}, 'rows': rows},
        }
        if knowledge:
            case['knowledge'] = list(knowledge.values())
        return case, briefs


T14_TEMPLATES = [HandoffTemplate(number) for number in range(1, 19)]
