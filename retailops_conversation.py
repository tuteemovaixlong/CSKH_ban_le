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


class CatalogMapping(dict):
    """Dict-like proxy to BusinessStore products."""
    def __init__(self, store):
        self.store = store
        super().__init__()

    def get(self, key, default=None):
        p = self.store.get_product(key)
        return p if p is not None else default

    def __getitem__(self, key):
        p = self.store.get_product(key)
        if p is None:
            raise KeyError(key)
        return p

    def __contains__(self, key):
        return self.store.get_product(key) is not None

    def __len__(self):
        return len(self.store.list_products())

    def __iter__(self):
        return iter(p['id'] for p in self.store.list_products())

    def values(self):
        return self.store.list_products()

    def items(self):
        return [(p['id'], p) for p in self.store.list_products()]

    def keys(self):
        return [p['id'] for p in self.store.list_products()]

    def pop(self, key, *args):
        return self.store.delete_product(key)


class Catalog:
    def __init__(self, store=None, path=None):
        if store is not None and (isinstance(store, (str, Path)) or not hasattr(store, 'list_products')):
            path = store
            store = None
        self.store = store
        self.path = Path(path or Path(__file__).resolve().parent / 'data/products.json')
        if self.store is not None:
            if not self.store.list_products():
                self.store.seed_catalog()
            self.products = CatalogMapping(self.store)
            self.source = "RetailOps Persistent Database Catalog"
        else:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            self.source = data.get('source', 'RetailOps In-Memory Catalog')
            self.products = {p['id']: p for p in data.get('products', [])}

    def save(self):
        if self.store is not None:
            return
        data = {'source': self.source, 'products': list(self.products.values())}
        try:
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        except (OSError, PermissionError) as exc:
            import logging
            logging.getLogger('retailops.catalog').warning(
                "Catalog file %s cannot be written (read-only filesystem); mutation kept in-memory: %s",
                self.path, exc
            )

    def add_product(self, p, actor=None):
        pid = p.get('id')
        if not pid:
            raise ValueError("Thiếu mã sản phẩm (id).")
        if self.store is not None:
            return self.store.add_product(p, actor=actor)
        self.products[pid] = p
        self.save()
        return p

    def update_product(self, pid, updates, actor=None):
        if self.store is not None:
            return self.store.update_product(pid, updates, actor=actor)
        if pid not in self.products:
            raise KeyError(f"Không tìm thấy sản phẩm {pid}.")
        self.products[pid].update(updates)
        self.save()
        return self.products[pid]

    def delete_product(self, pid, actor=None):
        if pid in ('P-101', 'P-102', 'P-202'):
            raise ValueError(f"Sản phẩm {pid} là sản phẩm cơ sở hệ thống phục vụ kiểm thử, không được phép xóa.")
        if self.store is not None:
            return self.store.delete_product(pid, actor=actor)
        if pid not in self.products:
            raise KeyError(f"Không tìm thấy sản phẩm {pid}.")
        removed = self.products.pop(pid)
        self.save()
        return removed

    def all_products(self):
        if self.store is not None:
            return self.store.list_products()
        return list(self.products.values())

    def get_variant_stock(self, pid, size, color=None):
        if self.store is not None:
            return self.store.get_variant_stock(pid, size, color)
        STOCK_MAP = {
            'P-101': {'S': 5, 'M': 12, 'L': 8, 'XL': 0},
            'P-102': {'S': 0, 'M': 4, 'L': 15, 'XL': 3},
            'P-202': {'S': 20, 'M': 18, 'L': 25, 'XL': 10},
            'P-103': {'S': 8, 'M': 14, 'L': 10, 'XL': 2},
            'P-104': {'S': 10, 'M': 15, 'L': 0, 'XL': 8},
            'P-203': {'S': 12, 'M': 0, 'L': 18, 'XL': 5},
            'P-301': {'39': 4, '40': 8, '41': 0, '42': 6, '43': 2},
        }
        return STOCK_MAP.get(pid, {}).get((size or '').upper().strip(), 0)

    def find(self, text):
        normalized = normalize(text)
        found = []
        for product in self.all_products():
            names = [product['id'], product['name']] + product.get('aliases', [])
            if any(matches(r'(?<![a-z0-9_-])' + re.escape(normalize(name)) + r'(?![a-z0-9_-])', normalized) for name in names):
                found.append(product)
        return found

    def for_order(self, order):
        if order.get('product_id'):
            p = self.products.get(order['product_id'])
            if p:
                return p
        return next((p for p in self.all_products() if p['name'] == order['name']), None)


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

