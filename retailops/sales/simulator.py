"""Sales Simulator for RetailOps (Offline / Dev only).

Generates realistic order events according to the canonical event contract.
Crucially: this simulator DOES NOT connect to, import, or write directly to any database!
It only creates and signs canonical event payloads, and emits them to an import adapter.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from retailops.sales.events import compute_signature

DEFAULT_DEV_SECRET = "dev_secret_key_retailops_2026"

DEFAULT_SAMPLE_ITEMS = [
    {
        "product_id": "P-601",
        "product_title": "Áo sơ mi lụa công sở",
        "variant_name": "Trắng / M",
        "quantity": 1,
        "unit_price": 450000,
    },
    {
        "product_id": "P-602",
        "product_title": "Quần tây đen hàn quốc",
        "variant_name": "Đen / L",
        "quantity": 1,
        "unit_price": 520000,
    },
    {
        "product_id": "P-603",
        "product_title": "Giày lười da bò cao cấp",
        "variant_name": "Nâu / 41",
        "quantity": 1,
        "unit_price": 890000,
    },
]


class SalesSimulator:
    """Offline/dev sales simulator producing canonical signed events.
    
    Zero database access. Zero direct writes to SQLite/PostgreSQL.
    """

    def __init__(
        self,
        tenant_id: str = "demo-shop-01",
        source_system: str = "sales_simulator",
        secret_key: str = DEFAULT_DEV_SECRET,
    ):
        self.tenant_id = str(tenant_id).strip()
        self.source_system = str(source_system).strip()
        self.secret_key = secret_key

    def create_order_event(
        self,
        *,
        event_id: Optional[str] = None,
        order_id: Optional[str] = None,
        external_customer_id: Optional[str] = None,
        status: str = "delivered",
        items: Optional[List[Dict[str, Any]]] = None,
        total: Optional[int] = None,
        currency: str = "VND",
        timestamp: Optional[str] = None,
        source_system: Optional[str] = None,
        tenant: Optional[str] = None,
        secret_override: Optional[str] = None,
        signature_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a valid, canonical signed order event dictionary."""
        effective_source = source_system or self.source_system
        effective_tenant = tenant or self.tenant_id
        effective_order_id = order_id or f"ORD-SIM-{uuid.uuid4().hex[:8].upper()}"
        effective_cust_id = external_customer_id or f"ext_cust_{uuid.uuid4().hex[:8]}"
        event_id = event_id or f"evt_{uuid.uuid4().hex}"

        if items is None:
            # Default to 1 realistic item
            items = [dict(DEFAULT_SAMPLE_ITEMS[0])]
        else:
            items = [dict(item) for item in items]

        calculated_total = sum(int(it["quantity"]) * int(it["unit_price"]) for it in items)
        effective_total = total if total is not None else calculated_total

        if timestamp is None:
            ts_str = datetime.now(timezone.utc).isoformat()
        else:
            ts_str = str(timestamp)

        event: Dict[str, Any] = {
            "source_system": effective_source,
            "event_id": event_id,
            "tenant": effective_tenant,
            "external_customer_id": effective_cust_id,
            "order_id": effective_order_id,
            "status": status,
            "items": items,
            "total": effective_total,
            "currency": currency,
            "timestamp": ts_str,
        }

        secret = secret_override if secret_override is not None else self.secret_key
        if signature_override is not None:
            event["signature"] = signature_override
        else:
            event["signature"] = compute_signature(event, secret)

        return event

    def create_tampered_signature_event(self, **kwargs) -> Dict[str, Any]:
        """Generate an event whose payload is tampered after signing."""
        event = self.create_order_event(**kwargs)
        # Invalidate signature with a wrong hex string
        event["signature"] = "deadbeef" * 8
        return event

    def create_expired_event(self, age_seconds: int = 3600, **kwargs) -> Dict[str, Any]:
        """Generate an event with a timestamp in the past."""
        past_epoch = time.time() - age_seconds
        past_iso = datetime.fromtimestamp(past_epoch, tz=timezone.utc).isoformat()
        return self.create_order_event(timestamp=past_iso, **kwargs)

    def create_future_event(self, future_seconds: int = 3600, **kwargs) -> Dict[str, Any]:
        """Generate an event with a timestamp too far in the future."""
        fut_epoch = time.time() + future_seconds
        fut_iso = datetime.fromtimestamp(fut_epoch, tz=timezone.utc).isoformat()
        return self.create_order_event(timestamp=fut_iso, **kwargs)

    def create_email_key_event(self, email: str = "customer.fake@example.com", **kwargs) -> Dict[str, Any]:
        """Generate an event violating the rule 'Không dùng email làm khóa'."""
        return self.create_order_event(external_customer_id=email, **kwargs)

    def create_mismatched_tenant_event(self, foreign_tenant: str = "other-shop-99", **kwargs) -> Dict[str, Any]:
        """Generate an event targeting an unexpected tenant."""
        return self.create_order_event(tenant=foreign_tenant, **kwargs)
