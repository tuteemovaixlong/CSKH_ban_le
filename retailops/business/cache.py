"""3-Tier Cache Engineering: Exact, Semantic (vector cosine), and Tool Execution Cache."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from retailops.knowledge.embedding import DIMENSION, embedding

ORDER_PATTERN = re.compile(r'\b[Oo]-\d+\b')
PRODUCT_PATTERN = re.compile(r'\b[Pp]-\d+\b')
MUTATION_PATTERN = re.compile(
    r'\b(hủy|huy|đổi địa chỉ|doi dia chi|cập nhật địa chỉ|cap nhat dia chi|đổi hàng|giao lại|hoàn tiền đơn|nhân viên|tu van vien|nguoi that|khiếu nại|khieu nai)\b',
    re.IGNORECASE
)


def is_cacheable_query(text: str) -> bool:
    """Check if query is safe for semantic caching.
    
    Queries mentioning specific order numbers, product IDs, or customer mutations
    MUST bypass cache and go directly to agent state machine.
    """
    if not isinstance(text, str):
        return False
    cleaned = text.strip()
    if len(cleaned) < 2 or len(cleaned) > 1000:
        return False
    if ORDER_PATTERN.search(cleaned) or PRODUCT_PATTERN.search(cleaned):
        return False
    if MUTATION_PATTERN.search(cleaned):
        return False
    return True


class SemanticCache:
    """In-memory Semantic Cache with vector cosine similarity.
    
    Works offline or backed by PostgreSQL pgvector.
    Cosine similarity uses dot product since embedding vectors are L2-normalized.
    """

    def __init__(self, min_similarity: float = 0.65, max_entries: int = 1000):
        self.min_similarity = min_similarity
        self.max_entries = max_entries
        self._entries: List[Dict[str, Any]] = []
        self._hash_map: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _query_hash(self, text: str) -> str:
        return hashlib.sha256(text.strip().lower().encode('utf-8')).hexdigest()

    def lookup(self, query_text: str) -> Optional[Dict[str, Any]]:
        """Lookup query text. Returns cache match or None."""
        if not is_cacheable_query(query_text):
            return None

        q_hash = self._query_hash(query_text)

        with self._lock:
            # 1. Exact Match (Tier 1A)
            exact = self._hash_map.get(q_hash)
            now = time.time()
            if exact and exact['expires_at'] > now:
                exact['hit_count'] += 1
                exact['last_hit_at'] = now
                return {
                    'type': 'exact',
                    'similarity': 1.0,
                    'answer': exact['answer'],
                    'action': exact['action'],
                    'entry_id': exact['id'],
                    'hit_count': exact['hit_count']
                }

            # 2. Semantic Cosine Match (Tier 1B)
            try:
                q_vec = embedding(query_text)
            except ValueError:
                return None

            best_entry = None
            best_score = -1.0

            for entry in self._entries:
                if entry['expires_at'] <= now:
                    continue
                # Dot product of normalized vectors = cosine similarity
                score = sum(a * b for a, b in zip(q_vec, entry['vector']))
                if score > best_score:
                    best_score = score
                    best_entry = entry

            if best_entry and best_score >= self.min_similarity:
                best_entry['hit_count'] += 1
                best_entry['last_hit_at'] = now
                return {
                    'type': 'semantic',
                    'similarity': round(best_score, 4),
                    'answer': best_entry['answer'],
                    'action': best_entry['action'],
                    'entry_id': best_entry['id'],
                    'matched_query': best_entry['query_text'],
                    'hit_count': best_entry['hit_count']
                }

        return None

    def store(self, query_text: str, answer: str, action: str = 'reply',
              ttl_seconds: float = 86400, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Store query and response into semantic cache."""
        if not is_cacheable_query(query_text):
            return None
        if not isinstance(answer, str) or not answer.strip():
            return None

        try:
            q_vec = embedding(query_text)
        except ValueError:
            return None

        q_hash = self._query_hash(query_text)
        now = time.time()
        entry_id = str(uuid.uuid4())

        entry = {
            'id': entry_id,
            'query_text': query_text.strip(),
            'query_hash': q_hash,
            'vector': q_vec,
            'answer': answer.strip(),
            'action': action,
            'metadata': metadata or {},
            'hit_count': 0,
            'created_at': now,
            'last_hit_at': now,
            'expires_at': now + ttl_seconds
        }

        with self._lock:
            # Overwrite exact hash if exists
            old = self._hash_map.get(q_hash)
            if old:
                if old in self._entries:
                    self._entries.remove(old)

            if len(self._entries) >= self.max_entries:
                # Evict oldest entry
                evicted = self._entries.pop(0)
                self._hash_map.pop(evicted['query_hash'], None)

            self._entries.append(entry)
            self._hash_map[q_hash] = entry

        return entry_id

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._hash_map.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total_hits = sum(e['hit_count'] for e in self._entries)
            return {
                'entries': len(self._entries),
                'total_hits': total_hits,
                'min_similarity': self.min_similarity
            }


class ToolCache:
    """Short-term read cache for deterministic business tools (get_order, get_product).
    
    Automatically invalidates customer orders when a mutation tool runs.
    """

    CACHEABLE_TOOLS = {'get_order', 'get_product', 'list_products', 'search_knowledge'}
    MUTATING_TOOLS = {'cancel_order', 'confirm_cancellation', 'update_shipping_address'}

    def __init__(self, default_ttl: float = 180.0):
        self.default_ttl = default_ttl
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _key(self, customer: str, tool_name: str, arguments: Dict[str, Any]) -> str:
        args_str = json.dumps(arguments, sort_keys=True, separators=(',', ':'))
        return f"{customer}:{tool_name}:{args_str}"

    def get(self, customer: str, tool_name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if tool_name not in self.CACHEABLE_TOOLS:
            return None
        key = self._key(customer, tool_name, arguments)
        now = time.time()
        with self._lock:
            item = self._cache.get(key)
            if item and item['expires_at'] > now:
                item['hits'] += 1
                return item['result']
            if item:
                del self._cache[key]
        return None

    def set(self, customer: str, tool_name: str, arguments: Dict[str, Any], result: Dict[str, Any],
            ttl: Optional[float] = None) -> None:
        if tool_name not in self.CACHEABLE_TOOLS or not isinstance(result, dict):
            return
        if result.get('error'):
            return  # Do not cache error responses
        key = self._key(customer, tool_name, arguments)
        now = time.time()
        duration = ttl if ttl is not None else self.default_ttl
        with self._lock:
            self._cache[key] = {
                'result': result,
                'expires_at': now + duration,
                'hits': 0,
                'customer': customer
            }

    def invalidate(self, customer: str, order_id: Optional[str] = None) -> int:
        """Invalidate cache entries for a customer upon mutation."""
        removed = 0
        with self._lock:
            keys_to_delete = []
            for k, v in self._cache.items():
                if v.get('customer') == customer:
                    if order_id is None or order_id in k:
                        keys_to_delete.append(k)
            for k in keys_to_delete:
                del self._cache[k]
                removed += 1
        return removed

    def clear(self):
        with self._lock:
            self._cache.clear()
