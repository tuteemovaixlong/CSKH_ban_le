"""SFT data view wrapping sft_v1 tenant for template data discovery.

W6.7.0 Part A.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = ROOT / 'data' / 'knowledge'


class SftView:
    """Read-only view over sft_v1 demo store events, orders, catalog and knowledge."""

    def __init__(self) -> None:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from scripts.run_agent_scenarios import _modules, _provision_demo_template
        from retailops_tools import BoundTools

        Application, ApiError, PersistentSessions, KnowledgeRepository, AgentError = _modules()
        template_root = _provision_demo_template('sft_v1', PersistentSessions)
        self.sessions = PersistentSessions(template_root, data_mode='persistent-demo')
        self.store = self.sessions.business_store('shop-scenarios')
        self.app = Application(self.store, {}, tenant_id='shop-scenarios')
        self.catalog = self.app.catalog

        self.orders: dict[str, dict[str, Any]] = {}
        self.orders_by_status: dict[str, list[dict[str, Any]]] = {
            'pending': [],
            'shipping': [],
            'delivered': [],
            'cancelled': [],
        }
        self.customers: dict[str, dict[str, Any]] = {}
        self.customer_orders: dict[str, list[dict[str, Any]]] = {}

        # Scan all customers in sft_v1
        events_file = ROOT / 'data' / 'demo_events' / 'store_events_sft_v1.jsonl'
        ext_customers: set[str] = set()
        if events_file.exists():
            for line in events_file.read_text(encoding='utf-8').splitlines():
                if not line.strip():
                    continue
                ev = json.loads(line)
                data = ev.get('data', {})
                if data.get('external_customer_id'):
                    ext_customers.add(data['external_customer_id'])

        for ext_c in sorted(ext_customers):
            int_cid = self.sessions.control.get_external_customer_mapping(
                'shop-scenarios', 'marketplace_sim', ext_c
            )
            if not int_cid:
                continue
            tools = BoundTools(self.store, self.catalog, int_cid, {}, {})
            store_ords = self.store.orders(int_cid)
            detailed_ords = []
            for so in store_ords:
                detailed = tools.read_order(so['id'])
                detailed['external_customer_id'] = ext_c
                detailed['internal_customer_id'] = int_cid
                ext_oid = detailed.get('external_order_id') or detailed['id']
                self.orders[ext_oid] = detailed
                status = detailed['status']
                if status in self.orders_by_status:
                    self.orders_by_status[status].append(detailed)
                detailed_ords.append(detailed)
            self.customers[ext_c] = {
                'external_customer_id': ext_c,
                'internal_customer_id': int_cid,
                'order_count': len(detailed_ords),
            }
            self.customer_orders[ext_c] = detailed_ords

        # Eligibility-driven order classification
        self.orders_return_eligible: list[dict[str, Any]] = []
        self.orders_size_exchange_eligible: list[dict[str, Any]] = []
        self.orders_warranty_only: list[dict[str, Any]] = []
        self.orders_past_warranty: list[dict[str, Any]] = []
        self.orders_can_cancel: list[dict[str, Any]] = []
        self.late_orders: list[dict[str, Any]] = []
        self.late_orders_under_48h: list[dict[str, Any]] = []
        self.late_orders_over_48h: list[dict[str, Any]] = []
        self.orders_failed_or_returned: list[dict[str, Any]] = []

        for ord_dict in self.orders.values():
            if (ord_dict.get("delivery") or {}).get("status") in ("failed", "returned"):
                self.orders_failed_or_returned.append(ord_dict)
            el = ord_dict.get('eligibility', {})
            late_h = float(el.get('late_by_hours', 0.0) or 0.0)
            if late_h > 0:
                self.late_orders.append(ord_dict)
                if late_h <= 48.0:
                    self.late_orders_under_48h.append(ord_dict)
                else:
                    self.late_orders_over_48h.append(ord_dict)

            if el.get('can_self_service_cancel') or ord_dict.get('status') == 'pending':
                self.orders_can_cancel.append(ord_dict)

        for ord_dict in self.orders_by_status['delivered']:
            el = ord_dict.get('eligibility', {})
            within_ret = bool(el.get('within_return_window'))
            within_size = bool(el.get('within_size_exchange_window'))
            within_war = bool(el.get('within_warranty'))

            if within_ret:
                self.orders_return_eligible.append(ord_dict)
            if within_size:
                self.orders_size_exchange_eligible.append(ord_dict)
            if not within_size and within_war:
                self.orders_warranty_only.append(ord_dict)
            if not within_war:
                self.orders_past_warranty.append(ord_dict)

        # Backwards compatible aliases
        self.delivered_within_7 = self.orders_return_eligible
        self.delivered_8_to_15 = [o for o in self.orders_size_exchange_eligible if o not in self.orders_return_eligible]
        self.delivered_16_to_90 = self.orders_warranty_only
        self.delivered_over_90 = self.orders_past_warranty

        # Refund summary classification
        self.orders_refund_processing: list[dict[str, Any]] = []
        self.orders_refund_failed: list[dict[str, Any]] = []
        self.orders_refund_completed: list[dict[str, Any]] = []

        for ord_dict in self.orders.values():
            ref = ord_dict.get('refund_summary') or {}
            st = ref.get('latest_status')
            if st == 'processing':
                self.orders_refund_processing.append(ord_dict)
            elif st == 'failed':
                self.orders_refund_failed.append(ord_dict)
            elif st == 'completed':
                self.orders_refund_completed.append(ord_dict)

        # Variant inventory
        self.product_variants: list[dict[str, Any]] = []
        with self.store.connection() as db:
            for r in db.execute("SELECT * FROM product_variants").fetchall():
                self.product_variants.append(dict(r))
        self.in_stock_variants = [v for v in self.product_variants if (v.get('stock') or 0) > 0]
        self.out_of_stock_variants = [v for v in self.product_variants if (v.get('stock') or 0) == 0]

        # Knowledge docs cache
        self.knowledge_docs: dict[str, dict[str, Any]] = {}
        if KNOWLEDGE_DIR.exists():
            for p in sorted(KNOWLEDGE_DIR.glob('*.md')):
                text = p.read_text(encoding='utf-8')
                m = re.search(r'^#\s+(.+?)\s*$', text, re.M)
                title = m.group(1).strip() if m else p.stem
                paras = [
                    para.strip() for para in text.split('\n\n')
                    if para.strip()
                    and not para.strip().startswith('#')
                    and 'Tài liệu giả lập của RetailOps Demo' not in para
                ]
                self.knowledge_docs[p.name] = {
                    'source_key': p.name,
                    'title': title,
                    'text': text,
                    'paragraphs': paras,
                }

    def get_knowledge_doc(self, source_key: str) -> dict[str, Any]:
        if not source_key.endswith('.md'):
            source_key += '.md'
        return self.knowledge_docs[source_key]

    def get_knowledge_chunk(self, source_key: str, keyword: str | None = None) -> dict[str, str]:
        doc = self.get_knowledge_doc(source_key)
        paras = doc['paragraphs']
        if keyword:
            for p in paras:
                if keyword.lower() in p.lower():
                    return {'source_key': doc['source_key'], 'title': doc['title'], 'chunk': p[:650]}
        # Fallback to first non-empty paragraph
        chunk = paras[0] if paras else doc['text'][:500]
        return {'source_key': doc['source_key'], 'title': doc['title'], 'chunk': chunk[:650]}


import sys
