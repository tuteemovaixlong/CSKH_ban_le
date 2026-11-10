#!/usr/bin/env python3
"""Regenerate only the four marked blocks from the runner's own demo templates."""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TARGET = ROOT / 'khoa_luan/eval_pack/03_HE_THONG_VA_DU_LIEU.md'
KNOWLEDGE = ROOT / 'data/knowledge'
# Freeze provisioning AND reads. Only relative times leave this script.
NOW = 2000000000.


def relative(value):
    seconds = float(value) - NOW
    if abs(seconds) < .5:
        return 'bây giờ'
    return f'{abs(seconds) / 3600:.2f} giờ ' + ('trước' if seconds < 0 else 'nữa')


def clean(value, aliases, key=''):
    if isinstance(value, dict):
        return {k: clean(v, aliases, k) for k, v in value.items()
                if k not in {'internal_order_id', 'source_event_id', 'shipment_event_id', 'compensation_id',
                             'refund_id', 'payment_id', 'voucher_id', 'request_id', 'created_at', 'updated_at', 'tenant_id'}}
    if isinstance(value, list):
        return [clean(v, aliases, key) for v in value]
    if isinstance(value, str):
        if value in aliases:
            return aliases[value]
        if re.match(r'^\d{4}-\d\d-\d\dT', value):
            return relative(datetime.fromisoformat(value).timestamp())
        if re.fullmatch(r'(ord_|cust_|shp_|rfd_|pay_|vch_)[0-9a-f]+', value):
            return '<mã nội bộ>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if key.endswith('_at') or key in {'promised_delivery_by', 'valid_until', 'as_of'}:
            return relative(value)
        if isinstance(value, float):
            return round(value, 2)
    return value


def fenced(value, aliases):
    return '```json\n' + json.dumps(clean(value, aliases), ensure_ascii=False, indent=2, sort_keys=True) + '\n```'


def generate():
    from scripts.run_agent_scenarios import _provision_demo_template, _DEMO_TEMPLATE_CACHE
    from scripts.eval_dataset_v2 import demo_ids
    from retailops.identity.persistent import PersistentSessions
    from retailops_conversation import Catalog
    from retailops_tools import BoundTools
    # Cached templates from an earlier caller could carry a different clock.
    saved = dict(_DEMO_TEMPLATE_CACHE)
    _DEMO_TEMPLATE_CACHE.clear()
    try:
        with patch('time.time', return_value=NOW):
            stores, sessions_by_fixture = {}, {}
            for fixture in ('standard', 'late_voucher_issued'):
                sessions = PersistentSessions(_provision_demo_template(fixture, PersistentSessions), data_mode='persistent-demo')
                sessions_by_fixture[fixture] = sessions
                stores[fixture] = sessions.business_store('shop-scenarios')
            store = stores['standard']
            aliases = {}
            for fixture, st in stores.items():
                with st.connection() as db:
                    aliases.update({r['id']: r['external_order_id'] for r in db.execute('SELECT id,external_order_id FROM orders')})
                    aliases.update({r['shipment_id']: r['external_shipment_id'] for r in db.execute('SELECT shipment_id,external_shipment_id FROM shipments')})
                for customer in sorted(demo_ids()[0]):
                    internal = sessions_by_fixture[fixture].control.get_external_customer_mapping('shop-scenarios', 'marketplace_sim', customer)
                    if internal:
                        aliases[internal] = customer
            with store.connection() as db:
                orders = [dict(r) for r in db.execute('SELECT * FROM orders ORDER BY external_order_id')]
                customers = {r['id']: r['name'] for r in db.execute('SELECT id,name FROM customers')}
                items = [dict(r) for r in db.execute('SELECT * FROM order_items ORDER BY order_id,product_id,variant_name')]
                shipments = {r['order_id']: dict(r) for r in db.execute('SELECT * FROM shipments ORDER BY external_shipment_id')}
                failed_shipments = {r[0] for r in db.execute("SELECT DISTINCT shipment_id FROM shipment_events WHERE status IN ('failed','delivery_failed')")}
            groups = {label: [] for label in ('chờ xử lý', 'đang giao đúng hạn', 'trễ chưa quá 48 giờ', 'trễ quá 48 giờ',
                      'đã giao trong 7 ngày', '8–15 ngày', '16–90 ngày', 'quá 90 ngày', 'đã hủy', 'giao thất bại',
                      'chuyển hoàn', 'đã hoàn tiền', 'có voucher bồi thường (late_voucher_issued)')}
            customer_lines, tool_samples = [], []
            representatives = {}
            for order in orders:
                oid, cid = order['external_order_id'], order['customer_id']
                tools = BoundTools(store, Catalog(store=store), cid, {}, {}, user_text=oid)
                detail = tools('get_order', {'order_id': oid})['order']
                eligibility = detail['eligibility']
                shipment = shipments.get(order['id'], {})
                labels = []
                if order['status'] == 'pending': labels.append('chờ xử lý')
                late = eligibility.get('late_by_hours') or 0
                if late > 0:
                    labels.append('trễ quá 48 giờ' if late > 48 else 'trễ chưa quá 48 giờ')
                elif order['status'] == 'shipping':
                    labels.append('đang giao đúng hạn')
                if order['status'] == 'delivered':
                    days = eligibility['days_since_delivery']
                    labels.append('đã giao trong 7 ngày' if days <= 7 else '8–15 ngày' if days <= 15 else '16–90 ngày' if days <= 90 else 'quá 90 ngày')
                if order['status'] == 'cancelled': labels.append('đã hủy')
                if shipment.get('status') in {'failed', 'delivery_failed'} or shipment.get('shipment_id') in failed_shipments:
                    labels.append('giao thất bại')
                if shipment.get('status') in {'returning', 'returned', 'return_to_sender'}: labels.append('chuyển hoàn')
                if isinstance(detail.get('refund'), dict) and detail['refund'].get('status') == 'completed':
                    labels.append('đã hoàn tiền')
                for label in labels:
                    groups[label].append(oid)
                    representatives.setdefault(label, order)
                order_items = [{k: item[k] for k in ('product_id', 'product_title', 'variant_name', 'quantity', 'unit_price', 'subtotal')}
                               for item in items if item['order_id'] == order['id']]
                row = dict(customer=aliases[cid], customer_name=customers[cid], order=detail, items=order_items,
                           days_since_order=round((NOW - order['ordered_at']) / 86400, 2),
                           days_since_delivery=eligibility['days_since_delivery'],
                           hours_to_promised_delivery=round((order['promised_delivery_by'] - NOW) / 3600, 2) if order['promised_delivery_by'] else None,
                           carrier=shipment.get('carrier'), shipment_status=shipment.get('status'),
                           delivery_attempts=shipment.get('delivery_attempts', 0))
                customer_lines.append(f'#### {aliases[cid]} · {oid}\n\n' + fenced(row, aliases))
            for label, order in representatives.items():
                oid = order['external_order_id']
                tool = BoundTools(store, Catalog(store=store), order['customer_id'], {}, {}, user_text=oid)
                results = {action: tool('prepare_order_action', {'order_id': oid, 'action_type': action}) for action in ('cancel', 'return', 'exchange')}
                results['track_shipment'] = tool('track_shipment', {'order_id': oid})
                tool_samples.append(f'#### {label} · {oid}\n\n' + fenced(results, aliases))
            foreign = next(o for o in orders if o['customer_id'] != orders[0]['customer_id'])
            tools = BoundTools(store, Catalog(store=store), orders[0]['customer_id'], {}, {}, user_text=foreign['external_order_id'])
            from retailops.core import ApiError
            try:
                foreign_result = tools('get_order', {'order_id': foreign['external_order_id']})
            except ApiError as exc:
                foreign_result = {'error': exc.code, 'status': exc.status, 'message': str(exc)}
            tool_samples.append('#### Tra đơn của khách khác\n\n' + fenced(foreign_result, aliases))
            with store.connection() as db:
                empty = dict(db.execute('SELECT * FROM product_variants WHERE stock=0 ORDER BY product_id,id LIMIT 1').fetchone())
            tool_samples.append('#### Biến thể hết hàng\n\n' + fenced(tools('check_inventory', {k: empty[k] for k in ('product_id', 'size', 'color')}), aliases))
            late = stores['late_voucher_issued']
            with late.connection() as db:
                vouchers = [dict(r) for r in db.execute('SELECT v.*,o.external_order_id FROM vouchers v JOIN orders o ON o.id=v.order_id ORDER BY o.external_order_id')]
            groups['có voucher bồi thường (late_voucher_issued)'] = [v['external_order_id'] for v in vouchers]
            customer_lines.append('### Voucher trong fixture late_voucher_issued\n\n' + fenced(vouchers, aliases))
            customer_lines.insert(0, '### Bản đồ tình huống\n\n| Nhóm | Mã đơn |\n|---|---|\n' + '\n'.join(f'| {label} | {", ".join(ids) or "Không có"} |' for label, ids in groups.items()))
            catalog = []
            for product in sorted(store.list_products(), key=lambda p: p['id']):
                with store.connection() as db:
                    variants = [dict(r) for r in db.execute('SELECT * FROM product_variants WHERE product_id=? ORDER BY id', (product['id'],))]
                catalog.append(f"#### {product['id']} · {product['name']}\n\n" + fenced(dict(product=product, variants=variants), aliases))
            knowledge = '\n\n'.join(f'### {p.name}\n\n' + p.read_text(encoding='utf-8').rstrip() for p in sorted(KNOWLEDGE.glob('*.md')))
            return dict(tool_results='\n\n'.join(tool_samples), customers_orders='\n\n'.join(customer_lines),
                        catalog='\n\n'.join(catalog), knowledge=knowledge)
    finally:
        for key, td in list(_DEMO_TEMPLATE_CACHE.items()):
            td.cleanup()
        _DEMO_TEMPLATE_CACHE.clear()
        _DEMO_TEMPLATE_CACHE.update(saved)


def replace_blocks(text, blocks):
    for name, content in blocks.items():
        start, end = f'<!-- BEGIN GENERATED: {name} -->', f'<!-- END GENERATED: {name} -->'
        if text.count(start) != 1 or text.count(end) != 1:
            raise ValueError(f'Expected exactly one marker pair for {name}')
        left, tail = text.split(start)
        _, right = tail.split(end)
        text = left + start + '\n' + content.rstrip() + '\n' + end + right
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    current = TARGET.read_text(encoding='utf-8')
    updated = replace_blocks(current, generate())
    if args.check:
        if current != updated:
            print('EVAL_PACK_DRIFT: run python scripts/build_eval_pack.py', file=sys.stderr)
            return 1
        print('EVAL_PACK_OK')
    else:
        TARGET.write_text(updated, encoding='utf-8', newline='\n')
        print('EVAL_PACK_BUILT')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
