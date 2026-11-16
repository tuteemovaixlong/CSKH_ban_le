#!/usr/bin/env python3
"""Build deterministic SFT demo store events fixture (sft_v1).

W6.7.0 Part A (PR 1).
Reproduces the prototype: seed 20261201, 30 days, 13 stories, disjoint ID spaces.
"""
from __future__ import annotations

import argparse
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
    sim_mod = importlib.import_module('marketplace_sim.simulator')
    stories_mod = importlib.import_module('marketplace_sim.stories')
    MarketplaceSimulator = sim_mod.MarketplaceSimulator
    STORY_NAMES = stories_mod.STORY_NAMES

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
        for story_name in STORY_NAMES:
            sim.insert_story(story_name)

        n_events = sim.export_events(out_file)

    content_bytes = out_file.read_bytes()
    file_sha256 = hashlib.sha256(content_bytes).hexdigest()

    events_by_type: dict[str, int] = {}
    sft_orders: set[str] = set()
    sft_customers: set[str] = set()

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

    # Self-check against standard fixture
    std_orders: set[str] = set()
    std_customers: set[str] = set()
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

    overlap_orders = sft_orders & std_orders
    overlap_customers = sft_customers & std_customers

    if overlap_orders:
        raise ValueError(f'Trùng mã đơn với tệp chuẩn: {overlap_orders}')
    if overlap_customers:
        raise ValueError(f'Trùng mã khách với tệp chuẩn: {overlap_customers}')
    if not (100 <= len(sft_orders) <= 160):
        raise ValueError(f'Số đơn {len(sft_orders)} nằm ngoài khoảng [100, 160]')

    meta = {
        'seed': seed,
        'days': days,
        'merchant_id': merchant_id,
        'counters': COUNTERS_SFT_V1,
        'stories': list(STORY_NAMES),
        'event_counts_by_type': events_by_type,
        'total_events': n_events,
        'total_orders': len(sft_orders),
        'total_customers': len(sft_customers),
        'sha256': file_sha256,
        'build_command': f'python scripts/build_sft_fixture.py --out {out_file.as_posix()}',
    }

    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
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
        'sha256': meta['sha256'],
    }, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
