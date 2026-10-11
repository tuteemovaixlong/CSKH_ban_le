"""Sales Import Adapter — Service-boundary adapter for importing order events.

Validates canonical event schema, HMAC signature, timestamp drift, and tenant binding.
Enforces tenant-scoped external customer mapping (never using email as key).
Guarantees atomic transactional insertion with full rollback on failure,
idempotent deduplication/replay detection, audit logging, and cache invalidation.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Union

from retailops.core import ApiError, require
from retailops.sales.events import (
    INTERNAL_STATUS_MAPPING,
    validate_event_schema,
    validate_timestamp,
    verify_event_signature,
)

logger = logging.getLogger("retailops_sales_adapter")


@dataclass
class ImportResult:
    success: bool
    status: str  # "imported", "already_processed" (replay), etc.
    order_id: str
    customer_id: str
    tenant_id: str
    source_system: str
    event_id: str
    is_replay: bool = False
    items_count: int = 0
    total: int = 0


class SalesImportAdapter:
    """Service-boundary import adapter for sales events into RetailOps."""

    def __init__(
        self,
        sessions_or_stores: Any,
        secret_resolver: Optional[Union[Dict[str, str], Callable[[str, str], Optional[str]]]] = None,
        default_secret: str = "dev_secret_key_retailops_2026",
        max_age_seconds: int = 300,
        max_future_seconds: int = 60,
    ):
        self.sessions = sessions_or_stores
        if hasattr(sessions_or_stores, "control"):
            self.identity_store = sessions_or_stores.control
            self.get_bstore = sessions_or_stores.business_store
        elif hasattr(sessions_or_stores, "business_store"):
            self.identity_store = getattr(sessions_or_stores, "identity_store", None) or getattr(sessions_or_stores, "control", None)
            self.get_bstore = sessions_or_stores.business_store
        else:
            raise TypeError("sessions_or_stores must provide control (IdentityStore) and business_store(tenant_id).")

        self.secret_resolver = secret_resolver
        self.default_secret = default_secret
        self.max_age_seconds = max_age_seconds
        self.max_future_seconds = max_future_seconds

    def resolve_secret(self, source_system: str, tenant_id: str) -> str:
        """Resolve shared secret for a given source system and tenant."""
        if callable(self.secret_resolver):
            resolved = self.secret_resolver(source_system, tenant_id)
            if resolved:
                return resolved
        elif isinstance(self.secret_resolver, dict):
            key = (source_system, tenant_id)
            if key in self.secret_resolver:
                return self.secret_resolver[key]
            if source_system in self.secret_resolver:
                return self.secret_resolver[source_system]
        return self.default_secret

    def link_external_customer(
        self,
        tenant_id: str,
        source_system: str,
        external_customer_id: str,
        customer_id: str,
        customer_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Explicitly link an external customer to a RetailOps customer_id in tenant scope."""
        tenant_clean = str(tenant_id).strip()
        self.identity_store.tenant(tenant_clean)

        # Ensure customer exists in the tenant's business database
        bstore = self.get_bstore(tenant_clean)
        with bstore.connection(write=True) as db:
            db.execute(
                "INSERT INTO customers (id, name) VALUES (?, ?) ON CONFLICT DO NOTHING",
                (customer_id, customer_name or f"Khách {external_customer_id}"),
            )

        # Record mapping in identity store with audit
        return self.identity_store.link_external_customer(
            tenant_clean, source_system, external_customer_id, customer_id
        )

    def ingest_event(
        self,
        event_data: Dict[str, Any],
        *,
        actor_principal_id: Optional[str] = None,
        reference_time: Optional[float] = None,
    ) -> ImportResult:
        """Process and ingest a canonical sales order event via service boundary.
        
        Steps:
        1. Validate canonical schema (all 11 fields, non-empty, non-email customer ID, valid items and totals).
        2. Validate timestamp drift (replay attack mitigation).
        3. Verify tenant existence and active status.
        4. Verify HMAC-SHA256 signature using the resolved secret.
        5. Resolve/assign tenant-scoped customer_id.
        6. Execute atomic business store transaction:
           - Check idempotency in imported_events (if already processed -> return replay result).
           - Insert/update order.
           - Insert order_items.
           - Record business_events audit.
           - Record imported_events.
        7. If new customer mapping, persist to identity store with audit.
        8. Invalidate ToolCache for (tenant, customer).
        """
        # 1. Validate Schema
        validated = validate_event_schema(event_data)

        source_system = validated["source_system"]
        event_id = validated["event_id"]
        tenant_id = validated["tenant"]
        ext_customer_id = validated["external_customer_id"]
        order_id = validated["order_id"]
        status = validated["status"]
        items = validated["items"]
        total = int(validated["total"])
        currency = validated["currency"]
        timestamp_str = validated["timestamp"]
        signature = validated["signature"]

        # 2. Validate Timestamp drift
        validate_timestamp(
            timestamp_str,
            max_age_seconds=self.max_age_seconds,
            max_future_seconds=self.max_future_seconds,
            reference_time=reference_time,
        )

        # 3. Validate Tenant existence & active status
        with self.identity_store.connection() as db:
            tenant_row = db.execute("SELECT * FROM tenants WHERE id=?", (tenant_id,)).fetchone()
        require(tenant_row is not None, 404, "tenant_not_found", f"Cửa hàng {tenant_id} không tồn tại.")
        require(bool(tenant_row["active"]), 400, "tenant_inactive", f"Cửa hàng {tenant_id} chưa được kích hoạt.")

        # 4. Verify HMAC signature
        secret = self.resolve_secret(source_system, tenant_id)
        if not verify_event_signature(event_data, secret):
            raise ApiError(401, "invalid_signature", "Chữ ký HMAC không hợp lệ hoặc sai secret.")

        # 5. Resolve Tenant-Scoped Customer Mapping (P5-K4)
        existing_cid = self.identity_store.get_external_customer_mapping(tenant_id, source_system, ext_customer_id)
        is_new_mapping = False
        if existing_cid:
            customer_id = existing_cid
        else:
            is_new_mapping = True
            customer_id = f"cust_{uuid.uuid4().hex[:16]}"

        # 6. Atomic Transaction in Business Store
        bstore = self.get_bstore(tenant_id)
        now = time.time()

        with bstore.connection(write=True) as db:
            # Idempotency check: (source_system, event_id)
            existing_event = db.execute(
                "SELECT * FROM imported_events WHERE source_system=? AND event_id=?",
                (source_system, event_id),
            ).fetchone()
            if existing_event:
                logger.info(
                    "Idempotent replay detected for event_id=%s source_system=%s order_id=%s",
                    event_id, source_system, existing_event["order_id"],
                )
                return ImportResult(
                    success=True,
                    status="already_processed",
                    order_id=existing_event["order_id"],
                    customer_id=existing_event["customer_id"],
                    tenant_id=tenant_id,
                    source_system=source_system,
                    event_id=event_id,
                    is_replay=True,
                    items_count=len(items),
                    total=total,
                )

            # Ensure customer row exists in tenant's customers table
            db.execute(
                "INSERT INTO customers (id, name) VALUES (?, ?) ON CONFLICT DO NOTHING",
                (customer_id, f"Khách {ext_customer_id}"),
            )

            # Map external status to internal orders table status
            db_status = INTERNAL_STATUS_MAPPING.get(status, "pending")

            # Determine primary product summary and variant
            primary_product_id = items[0]["product_id"]
            primary_title = items[0].get("product_title") or items[0].get("name", "Sản phẩm")
            if len(items) == 1:
                order_name = primary_title
            else:
                order_name = f"{primary_title} và {len(items)-1} sản phẩm khác"
            order_variant = items[0].get("variant_name") or items[0].get("variant") or "Tiêu chuẩn"

            # Upsert into orders table
            db.execute(
                """INSERT INTO orders (id, customer_id, name, variant, amount, status, version, cancel_reason, product_id)
                   VALUES (?, ?, ?, ?, ?, ?, 1, NULL, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       customer_id=excluded.customer_id,
                       name=excluded.name,
                       variant=excluded.variant,
                       amount=excluded.amount,
                       status=excluded.status,
                       version=orders.version+1,
                       product_id=excluded.product_id""",
                (order_id, customer_id, order_name, order_variant, total, db_status, primary_product_id),
            )

            # Insert line items into order_items
            db.execute("DELETE FROM order_items WHERE order_id=?", (order_id,))
            for item in items:
                item_id = str(uuid.uuid4())
                p_id = item["product_id"]
                p_title = item.get("product_title") or item.get("name")
                v_name = item.get("variant_name") or item.get("variant")
                v_id = item.get("variant_id")
                qty = int(item["quantity"])
                u_price = int(item["unit_price"])
                subtotal = qty * u_price
                db.execute(
                    """INSERT INTO order_items
                       (id, tenant_id, order_id, product_id, variant_id, product_title, variant_name, quantity, unit_price, subtotal, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (item_id, tenant_id, order_id, p_id, v_id, p_title, v_name, qty, u_price, subtotal, now),
                )

            # Record audit event in business_events table
            audit_payload = {
                "source_system": source_system,
                "event_id": event_id,
                "external_customer_id": ext_customer_id,
                "order_id": order_id,
                "total": total,
                "currency": currency,
                "status": status,
                "actor_principal_id": actor_principal_id,
                "items_count": len(items),
            }
            db.execute(
                "INSERT INTO business_events (customer_id, created_at, kind, order_id, payload) VALUES (?, ?, ?, ?, ?)",
                (customer_id, now, "order_imported", order_id, json.dumps(audit_payload, ensure_ascii=False)),
            )

            # Record imported_events for idempotency
            db.execute(
                """INSERT INTO imported_events
                   (id, source_system, event_id, tenant_id, external_customer_id, customer_id, order_id, status, total, currency, payload_json, signature, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    source_system,
                    event_id,
                    tenant_id,
                    ext_customer_id,
                    customer_id,
                    order_id,
                    status,
                    total,
                    currency,
                    json.dumps(event_data, ensure_ascii=False),
                    signature,
                    now,
                ),
            )

        # 7. Post-commit: Persist customer mapping in Identity Store if new
        if is_new_mapping:
            self.identity_store.set_external_customer_mapping(tenant_id, source_system, ext_customer_id, customer_id)

        # 8. Cache invalidation: Invalidate ToolCache for tenant & customer
        if hasattr(self.sessions, "tool_caches") and tenant_id in self.sessions.tool_caches:
            self.sessions.tool_caches[tenant_id].invalidate(
                customer=customer_id, tenant_id=tenant_id, order_id=order_id
            )

        logger.info(
            "Successfully ingested order %s for customer %s in tenant %s (event_id=%s)",
            order_id, customer_id, tenant_id, event_id,
        )

        return ImportResult(
            success=True,
            status="imported",
            order_id=order_id,
            customer_id=customer_id,
            tenant_id=tenant_id,
            source_system=source_system,
            event_id=event_id,
            is_replay=False,
            items_count=len(items),
            total=total,
        )
