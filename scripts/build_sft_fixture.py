#!/usr/bin/env python3
"""Build deterministic SFT demo store events fixture (sft_v1).

W6.7.0 Part A.
Seed 20261201, 30 days + extra pending orders, repetitive rare stories, disjoint ID spaces.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / 'data' / 'demo_events' / 'store_events_sft_v1.jsonl'
STANDARD_EVENTS = ROOT / 'data' / 'demo_events' / 'store_events.jsonl'
DEFAULT_SEED = 20261201
DEFAULT_DAYS = 30
DEFAULT_MERCHANT_ID = 'MERCHANT-SIM-001'

COUNTERS_SFT_V1 = {
    'next_customer_no': 5001,
    'next_order_no': 50001,
    'next_shipment_no': 50001,
    'next_payment_no': 50001,
    'next_refund_no': 50001,
    'next_voucher_no': 50001,
    'next_story_no': 501,
}

STORY_REPEATS = {
    'dang_trung_chuyen': 8,
    'nghen_kho_mega_sale': 8,
    'cap_nhat_ao_giao_lai': 8,
    'giao_that_bai_hoan_ve': 8,
    'giao_tre_han_cam_ket': 8,
    'het_bao_hanh': 8,
    'qua_han_doi_tra': 8,
    'hoan_tien_cham': 8,
    'hoan_tien_that_bai': 8,
    'huy_truoc_khi_giao': 8,
    'giao_dung_han_cod': 2,
    'thanh_toan_that_bai_roi_thanh_cong': 2,
    'doi_size_trong_han': 2,
}


def build_fixture(
    out_path: Path | str = DEFAULT_OUT,
    *,
    seed: int = DEFAULT_SEED,
    days: int = DEFAULT_DAYS,
    merchant_id: str = DEFAULT_MERCHANT_ID,
) -> dict[str, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    import importlib
    import random
    sim_mod = importlib.import_module('marketplace_sim.simulator')
    MarketplaceSimulator = sim_mod.MarketplaceSimulator
    parse_iso_vn = sim_mod.parse_iso_vn

    out_file = Path(out_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    meta_file = out_file.with_name(out_file.stem + '.meta.json')

    with tempfile.TemporaryDirectory(prefix='build-sft-fixture-') as td:
        data_dir = Path(td)
        sim = MarketplaceSimulator.initialize(
            data_dir,
            seed=seed,
            merchant_id=merchant_id,
        )

        conn = sqlite3.connect(sim.db_path)
        try:
            with conn:
                for key, val in COUNTERS_SFT_V1.items():
                    conn.execute(
                        'UPDATE sim_meta SET value = ? WHERE key = ?',
                        (str(val), key),
                    )
        finally:
            conn.close()

        sim = MarketplaceSimulator(data_dir)
        sim.run_days(days)

        # 1. Insert repetitive stories to ensure sufficient rare-scenario orders
        for story_name, repeat_count in STORY_REPEATS.items():
            for _ in range(repeat_count):
                sim.insert_story(story_name)

        # 2. Create pending orders right before clock_dt (unconfirmed at current clock)
        conn = sqlite3.connect(sim.db_path)
        conn.row_factory = sqlite3.Row
        try:
            clock_dt = parse_iso_vn(sim._get_meta(conn, 'clock_iso'), 'clock_iso')
            ord_rng = random.Random(seed + 999)
            for _ in range(14):
                ord_dt = clock_dt - timedelta(minutes=ord_rng.randint(2, 10))
                sim._plan_random_order(conn, ord_rng, ord_dt, clock_dt)
            sim._flush_due_scheduled(conn, clock_dt)
            conn.commit()
        finally:
            conn.close()

        n_events = sim.export_events(out_file)

    content_bytes = out_file.read_bytes()
    file_sha256 = hashlib.sha256(content_bytes).hexdigest()

    events_by_type: dict[str, int] = {}
    sft_orders: set[str] = set()
    sft_customers: set[str] = set()
    sft_tracking: set[str] = set()

    for line in out_file.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        etype = ev.get('event_type', 'unknown')
        events_by_type[etype] = events_by_type.get(etype, 0) + 1
        data = ev.get('data', {})
        if data.get('external_order_id'):
            sft_orders.add(data['external_order_id'])
        if data.get('external_customer_id'):
            sft_customers.add(data['external_customer_id'])
        if data.get('tracking_code'):
            sft_tracking.add(data['tracking_code'])

    # Self-check against standard fixture: 0 overlap
    std_orders: set[str] = set()
    std_customers: set[str] = set()
    std_tracking: set[str] = set()
    if STANDARD_EVENTS.exists():
        for line in STANDARD_EVENTS.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            data = ev.get('data', {})
            if data.get('external_order_id'):
                std_orders.add(data['external_order_id'])
            if data.get('external_customer_id'):
                std_customers.add(data['external_customer_id'])
            if data.get('tracking_code'):
                std_tracking.add(data['tracking_code'])

    overlap_orders = sft_orders & std_orders
    overlap_customers = sft_customers & std_customers
    overlap_tracking = sft_tracking & std_tracking

    if overlap_orders:
        raise ValueError(f'Trùng mã đơn với tệp chuẩn: {overlap_orders}')
    if overlap_customers:
        raise ValueError(f'Trùng mã khách với tệp chuẩn: {overlap_customers}')
    if overlap_tracking:
        raise ValueError(f'Trùng mã vận đơn với tệp chuẩn: {overlap_tracking}')

    # 3. Verify thresholds via SftView / read_order
    from scripts.run_agent_scenarios import _modules
    from retailops_tools import BoundTools
    from retailops.integration.demo_seed import seed_demo_store_events

    Application, ApiError, PersistentSessions, KnowledgeRepository, AgentError = _modules()
    with tempfile.TemporaryDirectory(prefix='check-sft-view-') as ptd:
        template_root = Path(ptd) / 'persistent'
        sessions = PersistentSessions(template_root, data_mode='persistent-demo')
        sessions.provision_tenant('shop-check', 'Shop check', seed_demo=False)
        bstore = sessions.business_store('shop-check')
        with bstore.connection(write=True) as db:
            db.executemany("INSERT INTO customers (id, name) VALUES (?, ?) ON CONFLICT DO NOTHING", [("manager", "Manager"), ("system", "System")])
            bstore.seed_catalog(db)
        seed_demo_store_events(bstore, sessions=sessions, jsonl_path=out_file)

        app = Application(bstore, {}, tenant_id='shop-check')
        catalog = app.catalog
        orders = []
        with bstore.connection() as db:
            order_rows = db.execute("SELECT id, customer_id FROM orders").fetchall()
        for row in order_rows:
            tools = BoundTools(bstore, catalog, row["customer_id"], {}, {})
            detailed = tools.read_order(row["id"])
            orders.append(detailed)

        pending_cancel = [o for o in orders if o.get("status") == "pending" and o.get("eligibility", {}).get("can_self_service_cancel")]
        shipping = [o for o in orders if o.get("status") == "shipping"]
        late_orders = [o for o in orders if o.get("eligibility", {}).get("is_late_vs_promised")]
        late_over_48 = [o for o in late_orders if float(o.get("eligibility", {}).get("late_by_hours", 0) or 0) > 48.0]
        delivered = [o for o in orders if o.get("status") == "delivered"]
        failed_returned = [o for o in orders if (o.get("delivery") or {}).get("status") in ("failed", "returned")]
        past_warranty = [o for o in delivered if not o.get("eligibility", {}).get("within_warranty")]
        refund_slow_or_fail = [o for o in orders if (o.get("refund_summary") or {}).get("latest_status") in ("processing", "failed")]

        assert len(pending_cancel) >= 8, f"Số đơn pending có thể hủy {len(pending_cancel)} < 8"
        assert len(shipping) >= 10, f"Số đơn shipping {len(shipping)} < 10"
        assert len(late_orders) >= 8, f"Số đơn giao trễ {len(late_orders)} < 8"
        assert len(late_over_48) >= 4, f"Số đơn giao trễ > 48h {len(late_over_48)} < 4"
        assert len(failed_returned) >= 6, f"Số đơn thất bại/hoàn về {len(failed_returned)} < 6"
        assert len(past_warranty) >= 6, f"Số đơn hết bảo hành {len(past_warranty)} < 6"
        assert len(refund_slow_or_fail) >= 6, f"Số đơn hoàn tiền chậm/thất bại {len(refund_slow_or_fail)} < 6"

    try:
        rel_out = out_file.resolve().relative_to(ROOT.resolve()).as_posix()
        cmd_out = rel_out
    except ValueError:
        cmd_out = out_file.as_posix()

    meta = {
        'seed': seed,
        'days': days,
        'merchant_id': merchant_id,
        'counters': COUNTERS_SFT_V1,
        'stories': STORY_REPEATS,
        'threshold_checks': {
            'pending_cancel': len(pending_cancel),
            'shipping': len(shipping),
            'late_orders': len(late_orders),
            'late_over_48': len(late_over_48),
            'failed_returned': len(failed_returned),
            'past_warranty': len(past_warranty),
            'refund_slow_or_fail': len(refund_slow_or_fail),
        },
        'event_counts_by_type': events_by_type,
        'total_events': n_events,
        'total_orders': len(sft_orders),
        'total_customers': len(sft_customers),
        'sha256': file_sha256,
        'build_command': f'python scripts/build_sft_fixture.py --out {cmd_out}',
    }

    with open(meta_file, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(meta, indent=2, ensure_ascii=False) + '\n')
    return meta


def main() -> int:
    parser = argparse.ArgumentParser(description='Build deterministic SFT demo store events fixture')
    parser.add_argument('--out', default=str(DEFAULT_OUT), help='Output JSONL file path')
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED, help='Simulation seed')
    parser.add_argument('--days', type=int, default=DEFAULT_DAYS, help='Simulation days')
    parser.add_argument('--merchant-id', default=DEFAULT_MERCHANT_ID, help='Merchant ID')
    args = parser.parse_args()

    meta = build_fixture(
        out_path=args.out,
        seed=args.seed,
        days=args.days,
        merchant_id=args.merchant_id,
    )
    print(json.dumps({
        'status': 'OK',
        'total_events': meta['total_events'],
        'total_orders': meta['total_orders'],
        'total_customers': meta['total_customers'],
        'threshold_checks': meta['threshold_checks'],
        'sha256': meta['sha256'],
    }, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
