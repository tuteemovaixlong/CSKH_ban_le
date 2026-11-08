"""Fixed simulator-generated demo datasets and canonical ingestion helpers (W6.1b-D2, D11).

Reads checked-in v2 event files under ``data/demo_events/`` and feeds every line through
Item 4's canonical ``IntegrationIngestService.ingest_event`` write path with clock rebasing.
Never imports ``marketplace_sim``.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from retailops.core import ROOT, require
from retailops.integration.connectors import load_default_status_mapping
from retailops.integration.contract import validate_event_v2
from retailops.integration.ingest import IntegrationIngestService
from retailops.integration.intake import compute_jsonl_rebase_offset

DEMO_EVENTS_DIR = ROOT / "data" / "demo_events"
STORE_EVENTS_PATH = DEMO_EVENTS_DIR / "store_events.jsonl"
ACCOUNT_TEMPLATE_PATH = DEMO_EVENTS_DIR / "account_template.jsonl"
MANIFEST_PATH = DEMO_EVENTS_DIR / "manifest.json"

# Ephemeral per-process random key used strictly for internal demo seeding when
# RETAILOPS_EVENT_DIGEST_KEY_FILE is not configured in local/test environments.
_EPHEMERAL_DEMO_DIGEST_KEY = os.urandom(32)


class _InMemoryControlAdapter:
    """Minimal identity-mapping adapter for standalone BusinessStore instances without Sessions."""

    def __init__(self, tenant_id: str, mappings: dict[tuple[str, str], str] | None = None):
        self._tenant_id = tenant_id
        self._mappings: dict[tuple[str, str], str] = mappings if mappings is not None else {}

    def tenant(self, tenant_id: str) -> dict[str, Any]:
        return {"id": tenant_id, "active": 1}

    def get_external_customer_mapping(
        self, tenant_id: str, source_system: str, external_customer_id: str
    ) -> str | None:
        return self._mappings.get((str(source_system), str(external_customer_id)))

    def link_external_customer(
        self, tenant_id: str, source_system: str, external_customer_id: str, customer_id: str
    ) -> dict[str, Any]:
        key = (str(source_system), str(external_customer_id))
        created = key not in self._mappings
        self._mappings[key] = str(customer_id)
        return {"created": created, "customer_id": str(customer_id)}


class _StandaloneSessionsAdapter:
    """Session-backend shim allowing standalone BusinessStore.seed() to use IntegrationIngestService."""

    def __init__(self, bstore: Any):
        tenant_id = str(getattr(bstore, "tenant_id", None) or "default")
        if not hasattr(bstore, "_standalone_ext_mappings"):
            bstore._standalone_ext_mappings = {}
        self.control = _InMemoryControlAdapter(tenant_id, bstore._standalone_ext_mappings)
        self._bstore = bstore
        self.tool_caches: dict[str, Any] = {}

    def business_store(self, tenant_id: str) -> Any:
        return self._bstore


@lru_cache(maxsize=4)
def _read_raw_jsonl_lines(path_str: str) -> tuple[bytes, ...]:
    path = Path(path_str)
    require(
        path.is_file(),
        500,
        "demo_events_missing",
        f"Không tìm thấy tệp dữ liệu demo: {path.name}.",
    )
    raw = path.read_bytes()
    return tuple(line.rstrip(b"\r") for line in raw.split(b"\n") if line.strip())


def _resolve_sessions_for_store(bstore: Any, sessions: Any = None) -> tuple[Any, bool]:
    if sessions is not None:
        return sessions, True
    ref = getattr(bstore, "_sessions_ref", None)
    if callable(ref):
        resolved = ref()
        if resolved is not None:
            return resolved, True
    return _StandaloneSessionsAdapter(bstore), False


def _resolve_demo_digest_key(svc: IntegrationIngestService) -> bytes:
    if os.environ.get("RETAILOPS_EVENT_DIGEST_KEY_FILE", "").strip():
        return svc._resolve_digest_key()
    return _EPHEMERAL_DEMO_DIGEST_KEY


@lru_cache(maxsize=4)
def _load_prevalidated_store_events(
    path_str: str,
) -> tuple[float | None, tuple[tuple[bytes, dict[str, Any], str], ...]]:
    raw_lines = _read_raw_jsonl_lines(path_str)
    max_ts_probe = compute_jsonl_rebase_offset(list(raw_lines), target_now=0.0)
    # target_now - max_ts == max_ts_probe => max_ts == -max_ts_probe when non-empty
    max_ts = -max_ts_probe if raw_lines else None
    allowed_sources = frozenset({"marketplace_sim"})
    entries: list[tuple[bytes, dict[str, Any], str]] = []
    for raw_line in raw_lines:
        parsed = json.loads(raw_line.decode("utf-8"))
        validated = validate_event_v2(
            parsed,
            allow_requests=False,
            allowed_marketplace_sources=allowed_sources,
        )
        entries.append((raw_line, validated, json.dumps(validated, ensure_ascii=False)))
    return max_ts, tuple(entries)


def seed_demo_store_events(
    bstore: Any,
    *,
    sessions: Any = None,
    jsonl_path: Path | None = None,
) -> dict[str, Any]:
    """Import ``data/demo_events/store_events.jsonl`` into ``bstore`` with ``rebase_clock='now'``."""
    target_path = Path(jsonl_path or STORE_EVENTS_PATH)
    max_ts, prevalidated_entries = _load_prevalidated_store_events(str(target_path.resolve()))
    sess, has_real_sessions = _resolve_sessions_for_store(bstore, sessions)
    tenant_id = str(getattr(bstore, "tenant_id", None) or "default")

    svc = IntegrationIngestService(sess)
    digest_key = _resolve_demo_digest_key(svc)
    validated_mapping = load_default_status_mapping("marketplace_sim")
    rebase_offset = (float(bstore._now()) - max_ts) if max_ts is not None else 0.0

    pending_mappings: list[tuple[str, str]] = []
    received = 0
    duplicates = 0

    existing_ext_map: dict[str, str] = {}
    if has_real_sessions and hasattr(sess.control, "connection"):
        with sess.control.connection() as id_db:
            rows = id_db.execute(
                "SELECT external_customer_id, customer_id FROM external_customer_mappings "
                "WHERE tenant_id=? AND source_system='marketplace_sim'",
                (tenant_id,),
            ).fetchall()
            existing_ext_map = {str(r["external_customer_id"]): str(r["customer_id"]) for r in rows}

    with bstore.connection(write=True) as db:
        bstore.seed_catalog(db)
        bstore._ensure_purge_tombstone_table(db)
        existing_eids = {
            str(r["event_id"])
            for r in db.execute(
                "SELECT event_id FROM imported_events WHERE source_system='marketplace_sim'"
            ).fetchall()
        }
        tombstone_ids = {
            str(r["order_id"])
            for r in db.execute("SELECT order_id FROM order_purge_tombstones").fetchall()
        }
        batch_state: dict[str, Any] | None = (
            {
                "tombstones": tombstone_ids,
                "fresh_imported_events": True,
                "seen_events": set(),
                "entity_max_seq": {},
                "prior_cust_map": {},
                "ext_customer_map": existing_ext_map,
            }
            if not existing_eids
            else None
        )
        for raw_line, prevalidated, prevalidated_json in prevalidated_entries:
            if existing_eids and prevalidated["event_id"] in existing_eids:
                duplicates += 1
                continue
            res = svc.ingest_event(
                raw_line,
                tenant_id=tenant_id,
                connector_source_system="marketplace_sim",
                received_via="import",
                digest_key=digest_key,
                rebase_offset_seconds=rebase_offset,
                _db=db,
                _validated_status_mapping=validated_mapping,
                _skip_tenant_check=True,
                _pending_mappings=pending_mappings,
                _prevalidated=prevalidated,
                _prevalidated_json=prevalidated_json,
                _batch_state=batch_state,
            )
            if res.is_replay:
                duplicates += 1
            else:
                received += 1

    unique_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for ext_cid, cid in pending_mappings:
        pair = (ext_cid, cid)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        unique_pairs.append(pair)
    if has_real_sessions:
        svc._ensure_mappings_batch(tenant_id, "marketplace_sim", unique_pairs)
    else:
        for ext_cid, cid in unique_pairs:
            sess.control.link_external_customer(tenant_id, "marketplace_sim", ext_cid, cid)

    return {
        "received": received,
        "duplicates": duplicates,
        "total_lines": len(prevalidated_entries),
        "rebase_offset_seconds": rebase_offset,
    }


def build_account_template_events(
    *,
    tenant_id: str,
    customer_id: str,
    customer_name: str,
    template_path: Path | None = None,
) -> tuple[str, list[bytes]]:
    """Deterministically rewrite ``account_template.jsonl`` customer/order/entity IDs for one account."""
    target_path = Path(template_path or ACCOUNT_TEMPLATE_PATH)
    raw_lines = _read_raw_jsonl_lines(str(target_path.resolve()))
    tag = hashlib.sha256(f"{tenant_id}:{customer_id}".encode("utf-8")).hexdigest()[:8].upper()
    ext_customer_id = f"SIM-C-ACCT-{tag}"
    order_id_map = {
        "SIM-O-ST-001": f"SIM-O-{tag}-01",
        "SIM-O-ST-002": f"SIM-O-{tag}-02",
        "SIM-O-ST-003": f"SIM-O-{tag}-03",
    }

    rewritten: list[bytes] = []
    cust_seq = 0
    for raw_line in raw_lines:
        ev = json.loads(raw_line.decode("utf-8"))
        etype = ev.get("event_type")
        ev["event_id"] = f"{ev['event_id']}-{tag}"
        data = ev.get("data") or {}

        if etype == "customer.upserted":
            cust_seq += 1
            ev["sequence"] = cust_seq
            data["external_customer_id"] = ext_customer_id
            data["display_name"] = customer_name
        elif etype == "order.created":
            data["external_customer_id"] = ext_customer_id
            old_oid = str(data.get("external_order_id") or "")
            data["external_order_id"] = order_id_map.get(old_oid, f"{old_oid}-{tag}")
        else:
            if "external_order_id" in data and data["external_order_id"] is not None:
                old_oid = str(data["external_order_id"])
                data["external_order_id"] = order_id_map.get(old_oid, f"{old_oid}-{tag}")
            if "external_shipment_id" in data and data["external_shipment_id"] is not None:
                data["external_shipment_id"] = f"{data['external_shipment_id']}-{tag}"
            if "tracking_code" in data and data["tracking_code"] is not None:
                data["tracking_code"] = f"{data['tracking_code']}{tag}"
            if "provider_txn_ref" in data and data["provider_txn_ref"] is not None:
                data["provider_txn_ref"] = f"{data['provider_txn_ref']}-{tag}"
            if "provider_refund_ref" in data and data["provider_refund_ref"] is not None:
                data["provider_refund_ref"] = f"{data['provider_refund_ref']}-{tag}"

        rewritten.append(
            json.dumps(ev, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
    return ext_customer_id, rewritten


def seed_demo_account_orders(
    bstore: Any,
    customer_id: str,
    *,
    sessions: Any = None,
    db: Any = None,
    template_path: Path | None = None,
) -> list[str]:
    """Instantiate the 3-order ``account_template.jsonl`` for ``customer_id`` via Item 4's write path."""
    cid = str(customer_id or "").strip()
    if not cid:
        return []

    sess, has_real_sessions = _resolve_sessions_for_store(bstore, sessions)
    tenant_id = str(getattr(bstore, "tenant_id", None) or "default")
    svc = IntegrationIngestService(sess)
    digest_key = _resolve_demo_digest_key(svc)
    validated_mapping = load_default_status_mapping("marketplace_sim")

    def _check_already_populated(conn: Any) -> tuple[bool, str]:
        if bstore._tombstone_table_exists(conn):
            if conn.execute(
                "SELECT 1 FROM order_purge_tombstones WHERE customer_id=? LIMIT 1",
                (cid,),
            ).fetchone() is not None:
                return True, ""
        if conn.execute(
            "SELECT 1 FROM orders WHERE customer_id=? LIMIT 1",
            (cid,),
        ).fetchone() is not None:
            return True, ""
        cust_row = conn.execute(
            "SELECT name FROM customers WHERE id=? LIMIT 1", (cid,)
        ).fetchone()
        cust_name = str(cust_row["name"]) if cust_row and cust_row["name"] else f"Khách {cid}"
        return False, cust_name

    if db is not None:
        already, pre_name = _check_already_populated(db)
    else:
        with bstore.connection() as rconn:
            already, pre_name = _check_already_populated(rconn)
    if already:
        return []

    ext_cid, rewritten_lines = build_account_template_events(
        tenant_id=tenant_id,
        customer_id=cid,
        customer_name=pre_name,
        template_path=template_path,
    )
    sess.control.link_external_customer(tenant_id, "marketplace_sim", ext_cid, cid)

    def _run_in_tx(conn: Any) -> tuple[list[str], list[tuple[str, str]]]:
        bstore._ensure_purge_tombstone_table(conn)
        if conn.execute(
            "SELECT 1 FROM order_purge_tombstones WHERE customer_id=? LIMIT 1",
            (cid,),
        ).fetchone() is not None:
            return [], []
        if conn.execute(
            "SELECT 1 FROM orders WHERE customer_id=? LIMIT 1",
            (cid,),
        ).fetchone() is not None:
            return [], []

        conn.execute(
            "INSERT INTO customers (id, name) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (cid, pre_name),
        )
        bstore.seed_catalog(conn)
        rebase_offset = compute_jsonl_rebase_offset(
            rewritten_lines, target_now=float(bstore._now())
        )
        pending_mappings: list[tuple[str, str]] = []
        created_oids: list[str] = []
        for raw_line in rewritten_lines:
            res = svc.ingest_event(
                raw_line,
                tenant_id=tenant_id,
                connector_source_system="marketplace_sim",
                received_via="import",
                digest_key=digest_key,
                rebase_offset_seconds=rebase_offset,
                _db=conn,
                _validated_status_mapping=validated_mapping,
                _skip_tenant_check=True,
                _pending_mappings=pending_mappings,
            )
            if not res.is_replay and res.event_type == "order.created" and res.order_id:
                created_oids.append(res.order_id)
        return created_oids, pending_mappings

    if db is not None:
        created_oids, pending_mappings = _run_in_tx(db)
    else:
        with bstore.connection(write=True) as conn:
            created_oids, pending_mappings = _run_in_tx(conn)

    if has_real_sessions:
        seen_pairs: set[tuple[str, str]] = set()
        for ext_c, mapped_c in pending_mappings:
            pair = (ext_c, mapped_c)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            svc._ensure_mapping(tenant_id, "marketplace_sim", ext_c, mapped_c)

    return created_oids
