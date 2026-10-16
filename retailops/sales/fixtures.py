"""Deterministic signed sales event fixtures for offline testing and verification."""
from __future__ import annotations

from typing import Any, Dict

from retailops.sales.events import compute_signature
from retailops.sales.simulator import DEFAULT_DEV_SECRET

FIXED_TIMESTAMP = "2026-10-11T12:00:00Z"

FIXTURE_ORDER_SINGLE_ITEM: Dict[str, Any] = {
    "source_system": "sales_simulator",
    "event_id": "evt_fixture_001_single",
    "tenant": "demo-shop-01",
    "external_customer_id": "pos_cust_alpha_101",
    "order_id": "O-FIX-101",
    "status": "delivered",
    "items": [
        {
            "product_id": "P-601",
            "product_title": "Áo sơ mi lụa công sở",
            "variant_name": "Trắng / M",
            "quantity": 1,
            "unit_price": 450000,
        }
    ],
    "total": 450000,
    "currency": "VND",
    "timestamp": FIXED_TIMESTAMP,
}
FIXTURE_ORDER_SINGLE_ITEM["signature"] = compute_signature(FIXTURE_ORDER_SINGLE_ITEM, DEFAULT_DEV_SECRET)

FIXTURE_ORDER_MULTI_ITEM: Dict[str, Any] = {
    "source_system": "tiktok_shop",
    "event_id": "evt_fixture_002_multi",
    "tenant": "demo-shop-01",
    "external_customer_id": "tt_buyer_beta_202",
    "order_id": "O-FIX-102",
    "status": "pending",
    "items": [
        {
            "product_id": "P-601",
            "product_title": "Áo sơ mi lụa công sở",
            "variant_name": "Trắng / L",
            "quantity": 2,
            "unit_price": 450000,
        },
        {
            "product_id": "P-602",
            "product_title": "Quần tây ống đứng tôn dáng",
            "variant_name": "Đen / L",
            "quantity": 1,
            "unit_price": 520000,
        },
    ],
    "total": 1420000,
    "currency": "VND",
    "timestamp": FIXED_TIMESTAMP,
}
FIXTURE_ORDER_MULTI_ITEM["signature"] = compute_signature(FIXTURE_ORDER_MULTI_ITEM, DEFAULT_DEV_SECRET)

FIXTURE_P5D_PENDING_ORDER: Dict[str, Any] = {
    "source_system": "sales_simulator",
    "event_id": "evt_p5d_001_pending",
    "tenant": "demo-shop-01",
    "external_customer_id": "ext_pos_p5d_001",
    "order_id": "O-90001",
    "status": "pending",
    "items": [
        {
            "product_id": "P-601",
            "product_title": "Áo sơ mi lụa công sở",
            "variant_name": "Trắng / M",
            "quantity": 1,
            "unit_price": 450000,
        }
    ],
    "total": 450000,
    "currency": "VND",
    "timestamp": FIXED_TIMESTAMP,
}
FIXTURE_P5D_PENDING_ORDER["signature"] = compute_signature(FIXTURE_P5D_PENDING_ORDER, DEFAULT_DEV_SECRET)

FIXTURE_P5D_DELIVERED_ORDER: Dict[str, Any] = {
    "source_system": "sales_simulator",
    "event_id": "evt_p5d_002_delivered",
    "tenant": "demo-shop-01",
    "external_customer_id": "ext_pos_p5d_001",
    "order_id": "O-90002",
    "status": "delivered",
    "items": [
        {
            "product_id": "P-601",
            "product_title": "Áo sơ mi lụa công sở",
            "variant_name": "Trắng / M",
            "quantity": 1,
            "unit_price": 450000,
        }
    ],
    "total": 450000,
    "currency": "VND",
    "timestamp": FIXED_TIMESTAMP,
}
FIXTURE_P5D_DELIVERED_ORDER["signature"] = compute_signature(FIXTURE_P5D_DELIVERED_ORDER, DEFAULT_DEV_SECRET)


def get_signed_fixtures() -> Dict[str, Dict[str, Any]]:
    """Return immutable copies of pre-signed canonical fixtures."""
    return {
        "single_item": dict(FIXTURE_ORDER_SINGLE_ITEM),
        "multi_item": dict(FIXTURE_ORDER_MULTI_ITEM),
        "p5d_pending": dict(FIXTURE_P5D_PENDING_ORDER),
        "p5d_delivered": dict(FIXTURE_P5D_DELIVERED_ORDER),
    }
