"""Catalog access and deterministic presentation for explicit UI buttons only.

Chat uses retailops_agent; there is no text intent router in this module.
"""
from datetime import datetime, timedelta, timezone
import json
import math
import re
import unicodedata
from pathlib import Path

from retailops.business.eligibility import compute_order_eligibility, format_vn_iso

_VN_TZ = timezone(timedelta(hours=7))

_PAYMENT_METHOD_LABELS = {
    'cod': 'Thanh toán khi nhận hàng (COD)',
    'bank_transfer': 'Chuyển khoản ngân hàng',
    'e_wallet': 'Ví điện tử',
    'card': 'Thẻ thanh toán',
}

_PAYMENT_STATUS_LABELS = {
    'unpaid': 'Chưa thanh toán',
    'paid': 'Đã thanh toán',
    'partially_refunded': 'Đã hoàn tiền một phần',
    'refunded': 'Đã hoàn tiền',
}

_SHIPMENT_STATUS_LABELS = {
    'created': 'Đã tạo vận đơn',
    'ready_to_pick': 'Chờ lấy hàng',
    'picked': 'Đã lấy hàng',
    'picked_up': 'Đã lấy hàng',
    'in_transit': 'Đang trung chuyển',
    'sorting': 'Đang phân loại tại kho',
    'out_for_delivery': 'Đang giao hàng',
    'delivery_failed': 'Giao hàng không thành công',
    'delivered': 'Đã giao thành công',
    'returning': 'Đang hoàn hàng',
    'returned': 'Đã hoàn hàng về kho',
    'cancelled': 'Đã hủy vận đơn',
    'lost': 'Thất lạc kiện hàng',
    'damaged': 'Kiện hàng hư hỏng',
}

_REFUND_STATUS_LABELS = {
    'pending': 'Chờ xử lý hoàn tiền',
    'processing': 'Đang xử lý hoàn tiền',
    'completed': 'Đã hoàn tiền',
    'failed': 'Hoàn tiền không thành công',
}


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
        from retailops.business.store import VariantStockResult
        if pid not in self.products:
            return VariantStockResult(None, 'product_not_found')
        STOCK_MAP = {
            'P-101': {'S': 5, 'M': 12, 'L': 8, 'XL': 0},
            'P-102': {'S': 0, 'M': 4, 'L': 15, 'XL': 3},
            'P-202': {'S': 20, 'M': 18, 'L': 25, 'XL': 10},
            'P-103': {'S': 8, 'M': 14, 'L': 10, 'XL': 2},
            'P-104': {'S': 10, 'M': 15, 'L': 0, 'XL': 8},
            'P-203': {'S': 12, 'M': 0, 'L': 18, 'XL': 5},
            'P-301': {'39': 4, '40': 8, '41': 0, '42': 6, '43': 2},
            'P-601': {'S': 10, 'M': 15, 'L': 10},
            'P-602': {'S': 12, 'M': 18, 'L': 10},
            'P-603': {'40': 6, '41': 10, '42': 9},
        }
        s_clean = (size or '').upper().strip()
        if pid in STOCK_MAP and s_clean in STOCK_MAP[pid]:
            return VariantStockResult(STOCK_MAP[pid][s_clean], 'ok')
        prod = self.products[pid]
        if prod.get('stock') is None:
            return VariantStockResult(None, 'stock_unknown')
        return VariantStockResult(None, 'variant_not_found')

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


def _format_vn_display_time(value) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return None
        return datetime.fromtimestamp(float(value), tz=_VN_TZ).strftime('%H:%M %d/%m/%Y')
    if isinstance(value, str):
        clean = value.strip()
        if not clean:
            return None
        iso_norm = clean[:-1] + '+00:00' if clean.endswith('Z') else clean
        try:
            dt = datetime.fromisoformat(iso_norm)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_VN_TZ)
            else:
                dt = dt.astimezone(_VN_TZ)
            return dt.strftime('%H:%M %d/%m/%Y')
        except ValueError:
            return clean
    return None


def _ensure_order_details(order: dict, details: dict | None) -> dict:
    if isinstance(details, dict):
        return details
    if isinstance(order.get('eligibility'), dict):
        return order
    eligibility = compute_order_eligibility(order)
    is_unrecorded_seed = (
        order.get('source_system') == 'retailops_seed'
        and order.get('payment_method') is None
    )
    payment_status = None if is_unrecorded_seed else order.get('payment_status')
    return {
        'ordered_at': None if int(order.get('ordered_at_backfilled') or 0) == 1 else format_vn_iso(order.get('ordered_at')),
        'payment_method': order.get('payment_method'),
        'payment_status': payment_status,
        'shipping_fee': int(order['shipping_fee']) if order.get('shipping_fee') is not None else None,
        'ship_to_area': order.get('ship_to_area'),
        'promised_delivery_by': format_vn_iso(order.get('promised_delivery_by')),
        'delivered_at': format_vn_iso(order.get('delivered_at')),
        'refund_summary': order.get('refund_summary'),
        'payment': (
            {'method': order.get('payment_method'), 'status': payment_status}
            if order.get('payment_method') is not None
            else None
        ),
        'delivery': (
            {
                'ship_to_area': order.get('ship_to_area'),
                'promised_delivery_by': format_vn_iso(order.get('promised_delivery_by')),
                'delivered_at': format_vn_iso(order.get('delivered_at')),
            }
            if (order.get('delivered_at') is not None or order.get('promised_delivery_by') is not None)
            else None
        ),
        'refund': order.get('refund'),
        'eligibility': eligibility,
        'as_of': eligibility['as_of'],
    }


def _describe_payment(details: dict) -> str:
    pay = details.get('payment') if isinstance(details.get('payment'), dict) else None
    method = details.get('payment_method') or (pay.get('method') if pay else None)
    pstatus = details.get('payment_status') or (pay.get('status') if pay else None)
    if pay is None and method is None and pstatus is None:
        return 'Thanh toán: Chưa có thông tin thanh toán.'
    method_txt = _PAYMENT_METHOD_LABELS.get(method, str(method)) if method else 'Chưa rõ phương thức thanh toán'
    status_txt = _PAYMENT_STATUS_LABELS.get(pstatus, str(pstatus)) if pstatus else 'chưa rõ trạng thái thanh toán'
    return f'Thanh toán: {method_txt} · {status_txt}.'


def _describe_refund(details: dict) -> str:
    ref = details.get('refund')
    if not isinstance(ref, dict):
        ref = details.get('refund_summary') if isinstance(details.get('refund_summary'), dict) else None
    if ref is None:
        return 'Hoàn tiền: Chưa có thông tin hoàn tiền.'
    latest_status = _REFUND_STATUS_LABELS.get(ref.get('latest_status'), str(ref.get('latest_status') or 'Đang cập nhật'))
    refunded_total = int(ref.get('refunded_total') or 0)
    pending_total = int(ref.get('pending_total') or 0)
    if refunded_total > 0 and pending_total > 0:
        return f'Hoàn tiền: {latest_status} ({format_money(refunded_total)}; đang xử lý {format_money(pending_total)}).'
    if refunded_total > 0:
        return f'Hoàn tiền: {latest_status} ({format_money(refunded_total)}).'
    if pending_total > 0:
        return f'Hoàn tiền: {latest_status} ({format_money(pending_total)}).'
    return f'Hoàn tiền: {latest_status}.'


def _describe_shipping(order: dict, details: dict) -> str:
    deliv = details.get('delivery') if isinstance(details.get('delivery'), dict) else None
    carrier = deliv.get('carrier') if deliv else None
    sstatus = deliv.get('status') if deliv else None
    if carrier or sstatus:
        c_txt = carrier or 'Chưa rõ hãng vận chuyển'
        st_txt = _SHIPMENT_STATUS_LABELS.get(sstatus, str(sstatus)) if sstatus else 'chưa có trạng thái vận đơn'
        ship_part = f'{c_txt} ({st_txt})'
    else:
        ship_part = 'chưa có thông tin vận đơn'

    area = details.get('ship_to_area') or (deliv.get('ship_to_area') if deliv else None)
    area_part = f'khu vực giao: {area}' if area else 'chưa có khu vực giao'

    elig = details.get('eligibility') if isinstance(details.get('eligibility'), dict) else {}
    is_delivered_order = (
        elig.get('self_service_cancel_ineligible_reason') == 'order_already_delivered'
        or order.get('status') == 'delivered'
    )
    if is_delivered_order:
        delivered_dt = _format_vn_display_time(details.get('delivered_at') or (deliv.get('delivered_at') if deliv else None))
        time_part = f'ng\u00e0y giao {delivered_dt}' if delivered_dt else 'chưa có thời điểm giao cụ thể'
    else:
        promised_dt = _format_vn_display_time(details.get('promised_delivery_by') or (deliv.get('promised_delivery_by') if deliv else None))
        eta_dt = _format_vn_display_time((deliv.get('estimated_delivery_at') if deliv else None) or elig.get('latest_estimated_delivery_at'))
        if promised_dt:
            time_part = f'hạn giao cam kết {promised_dt}'
        elif eta_dt:
            time_part = f'dự kiến giao {eta_dt}'
        else:
            time_part = 'chưa có hạn giao dự kiến'

    return f'Vận chuyển: {ship_part}; {area_part}; {time_part}.'


def _describe_eligibility(order: dict, details: dict, reason_labels: dict) -> str:
    elig = details.get('eligibility') if isinstance(details.get('eligibility'), dict) else {}
    can_cancel = bool(elig.get('can_self_service_cancel'))
    inelig = elig.get('self_service_cancel_ineligible_reason')
    can_ret_ex = bool(elig.get('can_open_return_or_exchange'))

    if can_cancel:
        return (
            'Điều kiện xử lý: Đơn đang chờ xử lý, đủ điều kiện gửi yêu cầu hủy sau khi bạn chọn lý do và xác nhận '
            '(chưa áp dụng trả/đổi khi chưa nhận hàng).'
        )
    if inelig == 'order_already_shipping':
        return (
            'Điều kiện xử lý: Đơn đang trong quá trình vận chuyển nên không hỗ trợ hủy tự phục vụ '
            'và chưa mở yêu cầu trả/đổi khi chưa nhận hàng.'
        )
    if inelig == 'order_already_cancelled':
        reason_txt = reason_labels.get(order.get('cancel_reason'), 'Chưa ghi nhận')
        return f'Điều kiện xử lý: Đơn đã hủy (lý do: {reason_txt}); không thực hiện hủy lại và không áp dụng trả/đổi.'
    if inelig == 'order_already_delivered' or can_ret_ex:
        w_ret = elig.get('within_return_window')
        w_ex = elig.get('within_size_exchange_window')
        w_war = elig.get('within_warranty')
        ret_days = elig.get('return_window_days', 7)
        ex_days = elig.get('size_exchange_window_days', 15)
        war_days = elig.get('warranty_window_days', 0)
        if w_ret is None and w_ex is None:
            return (
                'Điều kiện xử lý: Đơn đã giao nên không đủ điều kiện hủy. Chưa có thời điểm giao cụ thể '
                'nên chưa xác định tự động hạn trả hàng/đổi size; bạn vẫn có thể gửi yêu cầu trả/đổi để cửa hàng kiểm tra.'
            )
        ret_txt = f'còn hạn trả hàng ({ret_days} ngày)' if w_ret else f'đã quá hạn trả hàng {ret_days} ngày'
        ex_txt = f'còn hạn đổi size ({ex_days} ngày)' if w_ex else f'đã quá hạn đổi size {ex_days} ngày'
        war_txt = (
            (f', còn hạn bảo hành ({war_days} ngày)' if w_war else f', hết hạn bảo hành ({war_days} ngày)')
            if war_days and w_war is not None
            else ''
        )
        return f'Điều kiện xử lý: Đơn đã giao nên không đủ điều kiện hủy; {ret_txt}, {ex_txt}{war_txt}.'
    return 'Điều kiện xử lý: Đơn hiện không đủ điều kiện hủy tự phục vụ.'


def describe_order(order, status_labels, reason_labels, field=None, *, details=None):
    raw_ext = order.get('external_order_id')
    oid = raw_ext.strip() if isinstance(raw_ext, str) and raw_ext.strip() else str(order['id'])
    resolved = _ensure_order_details(order, details)
    status_text = status_labels.get(order['status'], order['status'])

    if field == 'amount':
        fee = resolved.get('shipping_fee')
        fee_note = f'Phí vận chuyển: {format_money(fee)}.' if fee is not None else 'Chưa có thông tin phí vận chuyển riêng.'
        return (
            f"Giá trị đơn {oid} là {format_money(order['amount'])}. {fee_note} "
            "Đây là giá trị đơn đã ghi nhận, chưa phải báo giá hiện tại cho sản phẩm."
        )
    if field == 'shipping':
        return f"Đơn {oid} ({status_text}). {_describe_shipping(order, resolved)}"
    if field == 'payment':
        return f"Đơn {oid}. {_describe_payment(resolved)} {_describe_refund(resolved)}"
    if field == 'cancellation':
        return f"Đơn {oid}. {_describe_eligibility(order, resolved, reason_labels)}"

    lines = [
        f"Thông tin đơn {oid}",
        f"Trạng thái: {status_text}.",
        f"Sản phẩm: {order['name']} ({order['variant']}) · Giá trị đơn: {format_money(order['amount'])}.",
        _describe_payment(resolved),
        _describe_refund(resolved),
        _describe_shipping(order, resolved),
        _describe_eligibility(order, resolved, reason_labels),
    ]
    return "\n".join(lines)

