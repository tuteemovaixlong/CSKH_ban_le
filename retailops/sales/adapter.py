"""Sales Import Adapter — Service-boundary adapter for importing order events.

Validates canonical event schema, HMAC signature, timestamp drift, and tenant binding.
Enforces tenant-scoped external customer mapping (never using email as key).
Guarantees atomic transactional insertion with full rollback on failure,
idempotent deduplication/replay detection, audit logging, and cache invalidation.

Cross-store consistency (N4)
----------------------------
The business store (orders/imported_events) and the identity store
(external_customer_mappings) are separate databases, so no single transaction can
cover both. The design therefore makes the *business* store authoritative for
"which customer does this external customer id belong to":

* The customer id is assigned inside the business transaction, reusing any customer
  already recorded in ``imported_events`` for the same ``(source_system,
  external_customer_id)``. A retry therefore can never mint a second customer.
* The identity mapping is a derived index written after the business commit with
  insert-if-absent semantics. If that write fails the order stays committed, the
  caller gets a retryable ``identity_mapping_pending`` error, and the mapping is
  healed by replaying the same event, by the next event of the same customer, or by
  :meth:`SalesImportAdapter.reconcile_mappings`.
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
        """Explicitly link an external customer to a RetailOps customer_id in tenant scope.

        Insert-if-absent: re-linking to the same customer is a no-op, re-linking to a
        different customer is rejected (409) instead of silently moving ownership.
        """
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

    def _ensure_mapping(self, tenant_id: str, source_system: str, external_customer_id: str,
                        customer_id: str) -> Dict[str, Any]:
        """Idempotently persist the derived identity mapping after a business commit.

        Conflicts (409) propagate unchanged. Any other failure becomes a retryable 503;
        the business data is already committed and the mapping is healed on retry.
        """
        try:
            return self.identity_store.link_external_customer(
                tenant_id, source_system, external_customer_id, customer_id
            )
        except ApiError as exc:
            if exc.status < 500:
                raise
            error: Exception = exc
        except Exception as exc:  # identity store unavailable / driver error
            error = exc
        logger.error(
            "Identity mapping write failed after business commit tenant=%s source=%s customer=%s: %s",
            tenant_id, source_system, customer_id, error.__class__.__name__,
        )
        raise ApiError(
            503,
            "identity_mapping_pending",
            "Đơn hàng đã được ghi nhận nhưng ánh xạ khách hàng chưa lưu được; "
            "gửi lại cùng event_id để hoàn tất.",
        ) from error

    def _invalidate_cache(self, tenant_id: str, customer_id: str, order_id: str) -> None:
        if hasattr(self.sessions, "tool_caches") and tenant_id in self.sessions.tool_caches:
            self.sessions.tool_caches[tenant_id].invalidate(
                customer=customer_id, tenant_id=tenant_id, order_id=order_id
            )

    def reconcile_mappings(self, tenant_id: str) -> Dict[str, Any]:
        """Recovery: rebuild identity mappings missing for already-imported events.

        Business ``imported_events`` is authoritative. Safe to run repeatedly.
        """
        tenant_clean = str(tenant_id).strip()
        self.identity_store.tenant(tenant_clean)
        bstore = self.get_bstore(tenant_clean)
        with bstore.connection() as db:
            rows = [
                dict(r) for r in db.execute(
                    "SELECT DISTINCT source_system, external_customer_id, customer_id "
                    "FROM imported_events WHERE tenant_id=? ORDER BY source_system, external_customer_id, customer_id",
                    (tenant_clean,),
                ).fetchall()
            ]
        healed, conflicts = 0, []
        for row in rows:
            try:
                result = self.identity_store.link_external_customer(
                    tenant_clean, row["source_system"], row["external_customer_id"], row["customer_id"]
                )
                healed += 1 if result.get("created") else 0
            except ApiError as exc:
                if exc.status >= 500:
                    raise
                conflicts.append({**row, "code": exc.code})
        return {"checked": len(rows), "healed": healed, "conflicts": conflicts}

    def ingest_event(
        self,
        event_data: Dict[str, Any],
        *,
        actor_principal_id: Optional[str] = None,
        reference_time: Optional[float] = None,
    ) -> ImportResult:
        """Process and ingest a canonical sales order event via service boundary.

        Steps:
        1. Validate the exact canonical schema (11 fields, strict types, non-email customer id).
        2. Validate timestamp drift (replay attack mitigation).
        3. Verify tenant existence and active status.
        4. Verify HMAC-SHA256 signature using the resolved secret.
        5. Atomic business store transaction:
           - Idempotency check in imported_events (replay -> no mutation).
           - Resolve the customer (identity mapping, else prior imports, else new opaque id).
           - Refuse to change the owner of an existing order (N1).
           - Insert/update order, order_items, audit event and imported_events.
        6. Invalidate ToolCache for (tenant, customer).
        7. Ensure the derived identity mapping (insert-if-absent; also heals after a replay).
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
        total = validated["total"]
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

        # 5. Atomic transaction in the business store
        mapped_cid = self.identity_store.get_external_customer_mapping(tenant_id, source_system, ext_customer_id)
        bstore = self.get_bstore(tenant_id)
        now = time.time()
        replay = None

        with bstore.connection(write=True) as db:
            # Idempotency check: (source_system, event_id)
            existing_event = db.execute(
                "SELECT * FROM imported_events WHERE source_system=? AND event_id=?",
                (source_system, event_id),
            ).fetchone()
            if existing_event:
                replay = dict(existing_event)
            else:
                # Customer resolution. The mapping table is only a cache of the decision
                # recorded in imported_events, so a missing mapping (failed identity write)
                # still resolves to the customer chosen on the first import (N4).
                if mapped_cid:
                    customer_id = mapped_cid
                else:
                    prior = db.execute(
                        "SELECT customer_id FROM imported_events "
                        "WHERE tenant_id=? AND source_system=? AND external_customer_id=? "
                        "ORDER BY created_at LIMIT 1",
                        (tenant_id, source_system, ext_customer_id),
                    ).fetchone()
                    customer_id = prior["customer_id"] if prior else f"cust_{uuid.uuid4().hex}"

                # N1: an existing order can only be updated by its own customer.
                owner = db.execute("SELECT customer_id FROM orders WHERE id=?", (order_id,)).fetchone()
                if owner is not None and owner["customer_id"] != customer_id:
                    logger.warning(
                        "Rejected order ownership change tenant=%s source=%s event_id=%s order_id=%s",
                        tenant_id, source_system, event_id, order_id,
                    )
                    raise ApiError(
                        409,
                        "order_owner_conflict",
                        "order_id đã thuộc về khách hàng khác; không được đổi chủ đơn hàng.",
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
                primary_title = items[0]["product_title"]
                if len(items) == 1:
                    order_name = primary_title
                else:
                    order_name = f"{primary_title} và {len(items)-1} sản phẩm khác"
                order_variant = items[0].get("variant_name") or "Tiêu chuẩn"

                # Upsert into orders table (customer_id is intentionally NOT updated)
                db.execute(
                    """INSERT INTO orders (id, customer_id, name, variant, amount, status, version, cancel_reason, product_id)
                       VALUES (?, ?, ?, ?, ?, ?, 1, NULL, ?)
                       ON CONFLICT(id) DO UPDATE SET
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
                    qty = item["quantity"]
                    u_price = item["unit_price"]
                    db.execute(
                        """INSERT INTO order_items
                           (id, tenant_id, order_id, product_id, variant_id, product_title, variant_name, quantity, unit_price, subtotal, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            str(uuid.uuid4()), tenant_id, order_id, item["product_id"], item.get("variant_id"),
                            item["product_title"], item.get("variant_name"), qty, u_price, qty * u_price, now,
                        ),
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
                        str(uuid.uuid4()), source_system, event_id, tenant_id, ext_customer_id, customer_id,
                        order_id, status, total, currency, json.dumps(event_data, ensure_ascii=False),
                        signature, now,
                    ),
                )

        if replay is not None:
            logger.info(
                "Idempotent replay detected for event_id=%s source_system=%s order_id=%s",
                event_id, source_system, replay["order_id"],
            )
            # A replay also completes a mapping left pending by an earlier identity failure.
            self._ensure_mapping(tenant_id, source_system, ext_customer_id, replay["customer_id"])
            return ImportResult(
                success=True,
                status="already_processed",
                order_id=replay["order_id"],
                customer_id=replay["customer_id"],
                tenant_id=tenant_id,
                source_system=source_system,
                event_id=event_id,
                is_replay=True,
                items_count=len(items),
                total=total,
            )

        # 6. Cache invalidation happens right after commit, independent of identity health.
        self._invalidate_cache(tenant_id, customer_id, order_id)

        # 7. Derived identity mapping (insert-if-absent, audited on creation).
        self._ensure_mapping(tenant_id, source_system, ext_customer_id, customer_id)

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
