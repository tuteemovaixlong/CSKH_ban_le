"""Synthetic unit-test fixture helper for historical tests targeting C-001/C-002 and O-101/O-102/O-202.

Production/runtime ``BusinessStore.seed()`` and ``PersistentSessions.provision_tenant(..., seed_demo=True)``
now exclusively ingest simulator-generated v2 events from ``data/demo_events/`` (W6.1b-D2, D11).
Isolated unit tests that exercise role RBAC, order-action state machines, or HTTP envelopes
against synthetic IDs (``C-001``, ``O-101``, ``O-102``, ``O-202``, ``O-301``..``O-304``) call this
test-only fixture helper instead.
"""
from __future__ import annotations

from typing import Any


LEGACY_UNIT_CUSTOMERS: tuple[tuple[str, str], ...] = (
    ("C-001", "Mai Anh"),
    ("C-002", "Khách mẫu"),
    ("C-003", "Trần Thị Mai"),
    ("C-004", "Lê Hoàng Nam"),
    ("manager", "Quản lý cửa hàng"),
    ("system", "Hệ thống"),
)

LEGACY_UNIT_ORDERS: tuple[tuple[str, str, str, str, int, str, str], ...] = (
    ("O-101", "C-001", "Áo thun Essential", "Trắng · Size M · Số lượng 1", 299000, "pending", "P-101"),
    ("O-102", "C-001", "Áo khoác Everyday", "Đen · Size L · Số lượng 1", 799000, "delivered", "P-102"),
    ("O-202", "C-002", "Áo polo", "Xanh · Size M · Số lượng 1", 399000, "pending", "P-202"),
    ("O-301", "C-003", "Áo Sơ Mi Oxford Dài Tay", "Trắng · Size M · Số lượng 1", 350000, "pending", "P-103"),
    ("O-302", "C-003", "Áo Khoác Gió Bomber 2 Lớp", "Đen · Size L · Số lượng 1", 550000, "delivered", "P-104"),
    ("O-303", "C-004", "Áo Polo Nam Phối Bo Cổ Co Giãn", "Xanh Navy · Size M · Số lượng 1", 399000, "delivered", "P-203"),
    ("O-304", "C-004", "Bộ Nồi Inox 3 Đáy Cao Cấp", "Bạc · Bộ 3 món · Số lượng 1", 1250000, "pending", "P-401"),
)


def seed_legacy_unit_fixture(store: Any) -> Any:
    """Seed catalog, C-001..C-004, and O-101..O-304 into ``store`` for isolated unit tests."""
    with store.connection(write=True) as db:
        db.executemany(
            "INSERT INTO customers (id, name) VALUES (?, ?) ON CONFLICT DO NOTHING",
            list(LEGACY_UNIT_CUSTOMERS),
        )
        store.seed_catalog(db)
        store._ensure_purge_tombstone_table(db)
        tombstoned_oids = {
            str(r["order_id"])
            for r in db.execute("SELECT order_id FROM order_purge_tombstones").fetchall()
        }
        seed_ts = float(store._now())
        orders_to_seed = [
            (oid, cid, name, variant, amount, status, pid, "retailops_seed", oid, seed_ts, 1)
            for oid, cid, name, variant, amount, status, pid in LEGACY_UNIT_ORDERS
            if oid not in tombstoned_oids
        ]
        db.executemany(
            "INSERT INTO orders(id, customer_id, name, variant, amount, status, product_id, "
            "source_system, external_order_id, ordered_at, ordered_at_backfilled) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            orders_to_seed,
        )
    return store


def provision_legacy_unit_tenant(sessions: Any, tenant_id: str, name: str) -> Any:
    """Provision ``tenant_id`` with ``seed_demo=False`` and populate ``seed_legacy_unit_fixture``."""
    store = sessions.provision_tenant(tenant_id, name, seed_demo=False)
    return seed_legacy_unit_fixture(store)
