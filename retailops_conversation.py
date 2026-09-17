"""Catalog access and deterministic presentation for explicit UI buttons only.

Chat uses retailops_agent; there is no text intent router in this module.
"""
import json
import re
import unicodedata
from pathlib import Path


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower().replace('đ', 'd'))
                   if unicodedata.category(c) != 'Mn')


def matches(pattern, text):
    return bool(re.search(pattern, text))


class Catalog:
    def __init__(self, path=None):
        self.path = Path(path or Path(__file__).resolve().parent / 'data/products.json')
        data = json.loads(self.path.read_text(encoding='utf-8'))
        self.source = data['source']
        self.products = {p['id']: p for p in data['products']}

    def save(self):
        try:
            data = {'source': self.source, 'products': list(self.products.values())}
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass

    def add_product(self, p):
        pid = p.get('id')
        if not pid:
            raise ValueError("Thiếu mã sản phẩm (id).")
        self.products[pid] = p
        self.save()
        return p

    def update_product(self, pid, updates):
        if pid not in self.products:
            raise KeyError(f"Không tìm thấy sản phẩm {pid}.")
        self.products[pid].update(updates)
        self.save()
        return self.products[pid]

    def delete_product(self, pid):
        if pid in ('P-101', 'P-102', 'P-202'):
            raise ValueError(f"Sản phẩm {pid} là sản phẩm cơ sở hệ thống phục vụ kiểm thử, không được phép xóa.")
        if pid not in self.products:
            raise KeyError(f"Không tìm thấy sản phẩm {pid}.")
        removed = self.products.pop(pid)
        self.save()
        return removed

    def all_products(self):
        return list(self.products.values())

    def find(self, text):
        normalized = normalize(text)
        found = []
        for product in self.products.values():
            names = [product['id'], product['name']] + product.get('aliases', [])
            if any(matches(r'(?<![a-z0-9_-])' + re.escape(normalize(name)) + r'(?![a-z0-9_-])', normalized) for name in names):
                found.append(product)
        return found

    def for_order(self, order):
        # Exact catalog name is the only link in the current single-item fixtures.
        return next((p for p in self.products.values() if p['name'] == order['name']), None)


def format_money(value):
    return f'{value:,}'.replace(',', '.') + ' ₫'


def describe_order(order, status_labels, reason_labels, field=None):
    oid = order['id']
    if field == 'amount':
        return f"Giá trị đơn {oid} là {format_money(order['amount'])}. Đây là giá trị đơn đã ghi nhận, chưa phải báo giá hiện tại cho sản phẩm."
    if field == 'shipping':
        return f"Đơn {oid}: {status_labels[order['status']]}. Hệ thống chưa có mã vận đơn, hãng vận chuyển hoặc ngày giao dự kiến."
    if field == 'payment':
        return f"Đơn {oid} chưa có dữ liệu thanh toán hoặc hoàn tiền trong bản demo này. Mình không thể xác nhận đã thanh toán hay đã hoàn tiền."
    if field == 'cancellation':
        if order['status'] == 'cancelled':
            return f"Đơn {oid} đã hủy. Lý do đã ghi nhận: {reason_labels.get(order['cancel_reason'], 'Chưa có')}. Không thực hiện hủy lại."
        if order['status'] == 'delivered':
            return f"Đơn {oid} đã giao nên không đủ điều kiện hủy. Luồng đổi/trả chưa được triển khai."
        return f"Đơn {oid} đang chờ xử lý nên có thể yêu cầu hủy. Bạn cần chọn lý do và xác nhận; câu hỏi này chưa tạo yêu cầu hủy."
    text = (f"Thông tin đơn {oid}\n"
            f"Trạng thái: {status_labels[order['status']]}.\n"
            f"Sản phẩm: {order['name']}.\n"
            f"Biến thể: {order['variant']}.\n"
            f"Giá trị đơn: {format_money(order['amount'])}.")
    if order['status'] == 'cancelled':
        text += f"\nLý do hủy: {reason_labels.get(order['cancel_reason'], 'Chưa có')}."
    else:
        text += '\n' + ('Đơn có thể yêu cầu hủy sau khi bạn chọn lý do và xác nhận.' if order['status'] == 'pending'
                        else 'Đơn đã giao nên không đủ điều kiện hủy.')
    return text + '\nThông tin thanh toán, địa chỉ nhận và lịch giao chi tiết chưa có trong dữ liệu demo.'

