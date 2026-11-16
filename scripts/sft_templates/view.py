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

        # Delivered order buckets
        self.delivered_within_7: list[dict[str, Any]] = []
        self.delivered_8_to_15: list[dict[str, Any]] = []
        self.delivered_16_to_90: list[dict[str, Any]] = []
        self.delivered_over_90: list[dict[str, Any]] = []
        self.late_orders: list[dict[str, Any]] = []

        for ord_dict in self.orders_by_status['delivered']:
            el = ord_dict.get('eligibility', {})
            days = el.get('days_since_delivery', 0.0)
            if days <= 7:
                self.delivered_within_7.append(ord_dict)
            elif days <= 15:
                self.delivered_8_to_15.append(ord_dict)
            elif days <= 90:
                self.delivered_16_to_90.append(ord_dict)
            else:
                self.delivered_over_90.append(ord_dict)

            if el.get('late_by_hours', 0.0) > 0:
                self.late_orders.append(ord_dict)

        # Knowledge docs cache
        self.knowledge_docs: dict[str, dict[str, Any]] = {}
        if KNOWLEDGE_DIR.exists():
            for p in sorted(KNOWLEDGE_DIR.glob('*.md')):
                text = p.read_text(encoding='utf-8')
                m = re.search(r'^#\s+(.+?)\s*$', text, re.M)
                title = m.group(1).strip() if m else p.stem
                paras = [para.strip() for para in text.split('\n\n') if para.strip() and not para.strip().startswith('#')]
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
