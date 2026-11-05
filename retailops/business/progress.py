"""What the customer agent is doing right now, for the progress line of the chat (W3.2-D10).

A turn can take several model calls and tool calls. While the chat request is still open, the page asks this
in-memory record how far the turn got ("đã kiểm tra đơn hàng, kho…"). It holds tool names and statuses only,
is keyed by the authenticated customer and the conversation, and disappears when the turn ends. Nothing here
is stored or shared across processes: a page that cannot see it just shows the generic "đang xử lý".
"""
import re
import threading
import time

_PHASES = ('start', 'model', 'tool', 'done', 'cancelled')
_NAME = re.compile(r'[a-z_]{1,40}')
_MAX_TOOLS = 12
_CANCEL_TTL = 900.0
CANCELLED_MESSAGE = 'Bạn đã dừng câu trả lời.'


class TurnCancelRegistry:
    """Thread-safe, TTL-bounded in-memory cooperative cancellation registry (W5-D3).

    Keyed by `(tenant_id, owner_id, request_id)` so a caller can only stop or query
    their own turn within their own tenant.
    """

    def __init__(self, ttl=_CANCEL_TTL, clock=time.monotonic):
        self._lock = threading.Lock()
        self._items = {}
        self._ttl = float(ttl)
        self._clock = clock

    def _norm_key(self, tenant_id, owner_id, request_id):
        return (str(tenant_id or 'default'), str(owner_id or ''), str(request_id or ''))

    def start(self, tenant_id, owner_id, request_id, *, kind: str, target_id: str):
        key = self._norm_key(tenant_id, owner_id, request_id)
        with self._lock:
            self._expire()
            self._items[key] = {
                'status': 'running',
                'cancel_requested': False,
                'kind': str(kind),
                'target_id': str(target_id),
                'updated': self._clock(),
            }

    def is_cancelled(self, tenant_id, owner_id, request_id) -> bool:
        key = self._norm_key(tenant_id, owner_id, request_id)
        with self._lock:
            item = self._items.get(key)
            return bool(item and item.get('cancel_requested'))

    def finish(self, tenant_id, owner_id, request_id):
        key = self._norm_key(tenant_id, owner_id, request_id)
        with self._lock:
            self._expire()
            item = self._items.get(key)
            if item is not None:
                item['status'] = 'finished'
                item['updated'] = self._clock()

    def request_cancel(self, tenant_id, owner_id, request_id, *, kind: str, target_id: str) -> str:
        """Return `'cancelled'`, `'already_finished'`, or `'not_found'`."""
        key = self._norm_key(tenant_id, owner_id, request_id)
        with self._lock:
            self._expire()
            item = self._items.get(key)
            if item is None or item.get('kind') != str(kind) or item.get('target_id') != str(target_id):
                return 'not_found'
            if item.get('status') == 'running':
                item['cancel_requested'] = True
                item['updated'] = self._clock()
                return 'cancelled'
            return 'already_finished'

    def _expire(self):
        limit = self._clock() - self._ttl
        for key in [k for k, v in self._items.items() if v['updated'] < limit]:
            del self._items[key]


class TurnProgress:
    def __init__(self, ttl=300.0, clock=time.monotonic):
        self._lock = threading.Lock()
        self._items = {}
        self._ttl = ttl
        self._clock = clock

    def start(self, key, request_id):
        with self._lock:
            self._expire()
            self._items[key] = {'request_id': request_id, 'phase': 'start', 'model_calls': 0, 'tools': [],
                                'updated': self._clock()}

    def update(self, key, request_id, snapshot):
        """Record how far the turn got; a stale or unknown turn is ignored."""
        if not isinstance(snapshot, dict):
            return
        tools = [{'name': t['name'], 'status': 'error' if t.get('status') == 'error' else 'ok'}
                 for t in snapshot.get('tools') or []
                 if isinstance(t, dict) and isinstance(t.get('name'), str) and _NAME.fullmatch(t['name'])]
        calls = snapshot.get('model_calls')
        with self._lock:
            item = self._items.get(key)
            if item is None or item['request_id'] != request_id:
                return
            item.update(phase=snapshot['phase'] if snapshot.get('phase') in _PHASES else item['phase'],
                        model_calls=calls if type(calls) is int and 0 <= calls <= 100 else item['model_calls'],
                        tools=tools[:_MAX_TOOLS], updated=self._clock())

    def finish(self, key, request_id):
        with self._lock:
            item = self._items.get(key)
            if item is not None and item['request_id'] == request_id:
                del self._items[key]

    def read(self, key):
        with self._lock:
            self._expire()
            item = self._items.get(key)
            if item is None:
                return {'active': False}
            return {'active': True, 'phase': item['phase'], 'model_calls': item['model_calls'],
                    'tools': [dict(t) for t in item['tools']]}

    def _expire(self):
        limit = self._clock() - self._ttl
        for key in [k for k, v in self._items.items() if v['updated'] < limit]:
            del self._items[key]
