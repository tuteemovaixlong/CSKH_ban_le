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
DEICTIC_PATTERN = re.compile(r'\b(nó|món này|cái này|sản phẩm này|đơn này|áo này|quần này|đây|này)\b', re.IGNORECASE)

STATIC_FAQ_PATTERNS = [
    # Giờ mở cửa / làm việc của shop
    re.compile(r'^(shop\s+)?(mở\s+cửa|giờ\s+làm\s+việc|hoạt\s+động)(\s+lúc)?(\s+mấy\s+giờ|\s+khi\s+nào|\s+như\s+thế\s+nào)?$', re.IGNORECASE),
    re.compile(r'^(mấy\s+giờ\s+)?(shop\s+)?(mở\s+cửa|đóng\s+cửa)$', re.IGNORECASE),
    # Địa chỉ / vị trí cửa hàng
    re.compile(r'^(địa\s+chỉ|vị\s+trí)(\s+của)?\s+(shop|cửa\s+hàng)(\s+ở\s+đâu|\s+như\s+thế\s+nào)?$', re.IGNORECASE),
    re.compile(r'^(shop|cửa\s+hàng)\s+(ở\s+đâu|nằm\s+ở\s+đâu)$', re.IGNORECASE),
    # Hotline / liên hệ chung của shop
    re.compile(r'^(số\s+điện\s+thoại|hotline|tổng\s+đài|liên\s+hệ)(\s+của)?\s+(shop|cửa\s+hàng)(\s+là\s+gì|\s+như\s+thế\s+nào)?$', re.IGNORECASE),
    # Lời chào chuẩn
    re.compile(r'^(xin\s+chào|chào\s+shop|hi\s+shop|hello\s+shop)$', re.IGNORECASE),
]


def is_cacheable_query(text: str) -> bool:
    """Check if query is safe for semantic caching.
    
    Queries mentioning specific order numbers, product IDs, customer mutations,
    or context-dependent deictic words MUST bypass cache.
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
    if DEICTIC_PATTERN.search(cleaned):
        return False
    return True


def normalize_faq_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    t = text.strip().lower()
    t = re.sub(r'[\?\.!,;:]', '', t)
    return re.sub(r'\s+', ' ', t).strip()


def is_static_faq_query(text: str) -> bool:
    norm = normalize_faq_text(text)
    if not norm:
        return False
    compound_or_personal = re.compile(
        r'\b(và|hoặc|nhưng|với|của\s+tôi|của\s+em|của\s+mình|tôi|nhận\s+hàng|giao\s+hàng|phí\s+ship|vận\s+chuyển|bảo\s+hành|điều\s+kiện|chính\s+sách|quy\s+định)\b',
        re.IGNORECASE
    )
    if compound_or_personal.search(norm):
        return False
    return any(p.fullmatch(norm) for p in STATIC_FAQ_PATTERNS)


def resolve_faq_intent(text: str) -> Optional[str]:
    """Resolve canonical FAQ intent/topic for semantic cache partitioning."""
    norm = normalize_faq_text(text)
    if not norm:
        return None
    if any(w in norm for w in ("mở cửa", "đóng cửa", "giờ làm việc", "mấy giờ", "hoạt động")):
        return "hours"
    if any(w in norm for w in ("địa chỉ", "vị trí", "ở đâu", "nằm ở đâu", "chi nhánh")):
        return "address"
    if any(w in norm for w in ("hotline", "số điện thoại", "tổng đài", "liên hệ", "sđt")):
        return "hotline"
    if any(w in norm for w in ("xin chào", "chào shop", "hi shop", "hello shop")):
        return "greeting"
    if any(w in norm for w in ("đặt hàng", "mua hàng")):
        return "order_guide"
    return None


def is_cache_eligible_for_lookup(text: str, snapshot: dict, has_prior_turns: bool, attachment=None) -> bool:
    if attachment is not None:
        return False
    if not is_cacheable_query(text):
        return False
    if has_prior_turns is not False:
        return False
    if not isinstance(snapshot, dict) or snapshot.get('order_id') is not None or snapshot.get('product_id') is not None:
        return False
    if not is_static_faq_query(text):
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
        query_topic = resolve_faq_intent(query_text)

        with self._lock:
            # 1. Exact Match (Tier 1A)
            exact = self._hash_map.get(q_hash)
            now = time.time()
            if exact and exact['expires_at'] > now:
                exact_topic = exact.get('topic')
                if not (query_topic and exact_topic and query_topic != exact_topic):
                    exact['hit_count'] += 1
                    exact['last_hit_at'] = now
                    return {
                        'type': 'exact',
                        'similarity': 1.0,
                        'answer': exact['answer'],
                        'action': exact['action'],
                        'entry_id': exact['id'],
                        'hit_count': exact['hit_count'],
                        'topic': exact_topic
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
                entry_topic = entry.get('topic')
                # Intent partitioning: queries with different canonical FAQ topics MUST NOT match
                if query_topic and entry_topic and query_topic != entry_topic:
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
                    'hit_count': best_entry['hit_count'],
                    'topic': best_entry.get('topic')
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
        topic = (metadata or {}).get('topic') or resolve_faq_intent(query_text)

        entry = {
            'id': entry_id,
            'query_text': query_text.strip(),
            'query_hash': q_hash,
            'topic': topic,
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

    CACHEABLE_TOOLS = {'get_order', 'search_knowledge'}
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

    def invalidate_product(self, product_id: Optional[str] = None) -> int:
        """Invalidate cached product entries upon catalog mutation."""
        removed = 0
        with self._lock:
            keys_to_delete = []
            for k, v in self._cache.items():
                if ':get_product:' in k or ':list_products:' in k:
                    if product_id is None or (product_id and product_id in k):
                        keys_to_delete.append(k)
            for k in keys_to_delete:
                del self._cache[k]
                removed += 1
        return removed

    def clear(self):
        with self._lock:
            self._cache.clear()
