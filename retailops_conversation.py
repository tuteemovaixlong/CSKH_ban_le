"""Grounded presentation and bounded routing, separate from the model baseline.

Rules handle small talk and catalog/read-only questions. Novel business phrasing
still uses the existing extraction model. No reply from this module executes a
cancellation, claims missing catalog attributes, or sends chat history to Colab.
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


def order_ids(text):
    return sorted(set(re.findall(r'(?<![A-Za-z0-9_-])[A-Z]{1,6}-[0-9]{1,8}(?![A-Za-z0-9_-])', text.upper())) -
                  set(re.findall(r'\bP-[0-9]{1,8}\b', text.upper())))


class Catalog:
    def __init__(self, path=None):
        data = json.loads((path or Path(__file__).resolve().parent / 'data/products.json').read_text(encoding='utf-8'))
        self.source = data['source']
        self.products = {p['id']: p for p in data['products']}

    def find(self, text):
        normalized = normalize(text)
        found = []
        for product in self.products.values():
            names = [product['id'], product['name']] + product['aliases']
            if any(matches(r'(?<![a-z0-9_-])' + re.escape(normalize(name)) + r'(?![a-z0-9_-])', normalized) for name in names):
                found.append(product)
        return found

    def for_order(self, order):
        # Exact catalog name is the only link in the current single-item fixtures.
        return next((p for p in self.products.values() if p['name'] == order['name']), None)

    def describe(self, product, field=None):
        name = product['name']
        if field == 'variants':
            return (f"{name}: các biến thể đã ghi nhận là {', '.join(product['variants'])}. "
                    "Danh mục chưa xác nhận các biến thể khác hoặc tình trạng còn hàng.")
        if field in ('material', 'care', 'stock', 'price'):
            labels = {'material': 'chất liệu', 'care': 'hướng dẫn bảo quản', 'stock': 'tồn kho', 'price': 'giá bán hiện tại'}
            value = product.get(field)
            return (f"{name}: {value}." if value is not None else
                    f"Danh mục hiện chưa có thông tin {labels[field]} của {name}. Mình chưa thể xác nhận thông tin này.")
        return (f"{name} ({product['id']})\n{product['description']}\n"
                f"Nhóm sản phẩm: {product['category']}.\n"
                f"Biến thể đã ghi nhận: {', '.join(product['variants'])}.\n"
                "Chưa có dữ liệu chất liệu, tồn kho hoặc hướng dẫn bảo quản. "
                "Biến thể trong danh mục không có nghĩa là còn hàng.")


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


def route(text, catalog):
    """A route is a UI/read decision, never an authorization or a transaction."""
    n = normalize(text).strip()
    clean = re.sub(r'[^a-z0-9\s]', '', n).strip()
    ids, products = order_ids(text), catalog.find(text)
    if len(ids) > 1 or len(products) > 1:
        return {'kind': 'ambiguous', 'ids': ids, 'products': products}
    if re.fullmatch(r'(hello|hi|hey|xin chao|chao|chao ban|chao shop|alo|hello shop|hi shop)', clean):
        return {'kind': 'greeting', 'ids': ids, 'products': products}
    if re.fullmatch(r'(cam on( ban| shop| nhe)?|thanks|thank you|ok|okay|oke|tam biet|bye)', clean):
        return {'kind': 'courtesy', 'ids': ids, 'products': products}
    if matches(r'\b(sac|thuat toan|algorithm|lap trinh|code python|thoi tiet|weather|hom nay la ngay|ngay may|today.s date)\b', n):
        return {'kind': 'outside', 'ids': ids, 'products': products}
    if matches(r'\b(doi tra|doi size|doi ao|refund|return item|hoan tien|chinh sua dia chi)\b', n):
        return {'kind': 'unsupported_business', 'ids': ids, 'products': products}
    if matches(r'\b(khong|dung|chua)\s+(muon\s+)?huy\b|\bgiu\s+(nguyen\s+)?don\b|\b(do not|don.t) cancel\b', n):
        return {'kind': 'keep', 'ids': ids, 'products': products}
    if matches(r'\b(da huy|huy chua|huy duoc khong|co the huy|tai sao.*huy|can.*cancel|already cancel)\b', n):
        return {'kind': 'order', 'field': 'cancellation', 'ids': ids, 'products': products}
    # Cancellation requests go through the existing model, then the same explicit UI confirmation.
    if matches(r'\b(huy|cancel)\b', n):
        return {'kind': 'model', 'ids': ids, 'products': products}
    field = next((field for field, pattern in (
        ('material', r'\b(chat lieu|vai gi|material|fabric)\b'),
        ('care', r'\b(bao quan|giat|wash|care)\b'),
        ('stock', r'\b(con hang|het hang|ton kho|stock|available)\b'),
        ('variants', r'\b(size|kich co|mau sac|mau gi|mau nao|color|colour)\b'),
        ('price', r'\b(gia ban|product price)\b'),
    ) if matches(pattern, n)), None)
    product_reference = matches(r'\b(san pham|ao|quan|giay|product|item)\s+(nay|do|ay|vua roi)\b|\b(this|that) (product|item)\b', n)
    if products or field or product_reference or matches(r'\b(ao|quan|giay|san pham|product)\b.*\b(la gi|mo ta|thong tin|what|describe)\b', n):
        if field is None and matches(r'\b(gia|bao nhieu|price|how much)\b', n):
            field = 'price'
        return {'kind': 'product', 'field': field, 'reference': product_reference,
                'unknown_named': not products and not product_reference and matches(r'\b(ao|quan|giay)\s+\w+', n),
                'ids': ids, 'products': products}
    for field, pattern in (
        ('amount', r'\b(gia|tong tien|bao nhieu|how much|total|price)\b'),
        ('shipping', r'\b(giao hang|van don|van chuyen|bao gio.*giao|khi nao.*giao|tracking|shipping|delivery)\b'),
        ('payment', r'\b(thanh toan|payment|paid)\b'),
    ):
        if matches(pattern, n):
            return {'kind': 'order', 'field': field, 'ids': ids, 'products': products}
    if ids or matches(r'\b(don (nay|do|ay)|ma (nay|do)|thong tin|chi tiet|trang thai|tinh trang|order status|details)\b', n):
        return {'kind': 'order', 'field': None, 'ids': ids, 'products': products}
    return {'kind': 'model' if matches(r'\b(don|order|purchase|mua|hang|shop)\b', n) else 'outside',
            'ids': ids, 'products': products}
