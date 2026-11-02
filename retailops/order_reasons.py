"""The one catalog of order-action reasons (W3.2-D2, W3.2-D4).

`data/order_action_reasons.json` is the only place that declares a reason: its code, Vietnamese
label, which request types it applies to, whether a free-text description is mandatory and
whether only staff may use it. The customer UI, Staff Desk, the AI tools and the server checks
all read this catalog, so adding a reason means editing the file and nothing else.
"""
import json
import re
import threading

from retailops.core import ROOT, require

CATALOG_PATH = ROOT / 'data' / 'order_action_reasons.json'
ACTION_TYPES = ('cancel', 'return', 'exchange')
TEXT_MAX_LENGTH = 500

_CODE = re.compile(r'[a-z][a-z0-9_]{1,63}')
_ENTRY_KEYS = frozenset(('code', 'label', 'applies_to', 'requires_text', 'staff_only'))
_DOCUMENT_KEYS = frozenset(('version', 'description', 'reasons', 'aliases'))


class ReasonCatalogError(ValueError):
    """The catalog file is missing or invalid; the application must not start with it."""


class ReasonCatalog:
    def __init__(self, document):
        if not isinstance(document, dict) or not set(document).issubset(_DOCUMENT_KEYS):
            raise ReasonCatalogError('Order-action reason catalog must be an object with version, reasons and aliases.')
        version = document.get('version')
        if type(version) is not int or version < 1:
            raise ReasonCatalogError('Order-action reason catalog needs an integer version >= 1.')
        raw = document.get('reasons')
        if not isinstance(raw, list) or not raw:
            raise ReasonCatalogError('Order-action reason catalog needs a non-empty reasons list.')
        entries = {}
        for item in raw:
            entry = self._entry(item)
            if entry['code'] in entries:
                raise ReasonCatalogError(f"Duplicate reason code {entry['code']!r}.")
            entries[entry['code']] = entry
        aliases = document.get('aliases', {})
        if not isinstance(aliases, dict):
            raise ReasonCatalogError('Reason aliases must be an object.')
        for old, canonical in aliases.items():
            if not isinstance(old, str) or not _CODE.fullmatch(old) or old in entries:
                raise ReasonCatalogError(f'Invalid alias {old!r}: it must be a new code, not a catalog code.')
            if canonical not in entries:
                raise ReasonCatalogError(f'Alias {old!r} points to unknown reason {canonical!r}.')
        for action in ACTION_TYPES:
            if not any(action in e['applies_to'] and not e['staff_only'] for e in entries.values()):
                raise ReasonCatalogError(f'No customer-selectable reason applies to {action!r}.')
        self.version, self._entries, self._aliases = version, entries, dict(aliases)

    @staticmethod
    def _entry(item):
        if not isinstance(item, dict) or set(item) != _ENTRY_KEYS:
            raise ReasonCatalogError(f'Every reason needs exactly the fields {sorted(_ENTRY_KEYS)}.')
        code, label, applies = item['code'], item['label'], item['applies_to']
        if not isinstance(code, str) or not _CODE.fullmatch(code):
            raise ReasonCatalogError(f'Invalid reason code {code!r}.')
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 120:
            raise ReasonCatalogError(f'Reason {code!r} needs a Vietnamese label of 1-120 characters.')
        if (not isinstance(applies, list) or not applies or len(set(applies)) != len(applies)
                or not set(applies).issubset(ACTION_TYPES)):
            raise ReasonCatalogError(f'Reason {code!r} must apply to a non-empty subset of {ACTION_TYPES}.')
        for flag in ('requires_text', 'staff_only'):
            if type(item[flag]) is not bool:
                raise ReasonCatalogError(f'Reason {code!r}: {flag} must be true or false.')
        return {'code': code, 'label': label.strip(), 'applies_to': list(applies),
                'requires_text': item['requires_text'], 'staff_only': item['staff_only']}

    def get(self, code):
        """The entry for `code`, resolving a legacy alias; None when it is unknown."""
        if not isinstance(code, str):
            return None
        entry = self._entries.get(self._aliases.get(code, code))
        return dict(entry, applies_to=list(entry['applies_to'])) if entry else None

    def canonical(self, code):
        entry = self.get(code)
        return entry['code'] if entry else None

    def label(self, code):
        """Display label for any stored code, old W3 codes included; unknown codes show as stored."""
        entry = self.get(code)
        return entry['label'] if entry else (code if isinstance(code, str) else '')

    def labels(self):
        """Every known code, legacy aliases included, mapped to its display label."""
        return {code: self._entries[self._aliases.get(code, code)]['label']
                for code in (*self._entries, *self._aliases)}

    def options(self, action_type=None, *, role='customer'):
        """Reasons a role may pick, optionally limited to one request type (catalog order)."""
        staff = role in ('staff', 'manager')
        return [dict(e, applies_to=list(e['applies_to'])) for e in self._entries.values()
                if (action_type is None or action_type in e['applies_to']) and (staff or not e['staff_only'])]

    def public(self, role='customer'):
        """The catalog as the API returns it. `staff_only` is only revealed to staff and managers."""
        staff = role in ('staff', 'manager')
        reasons = []
        for e in self.options(role=role):
            item = {'code': e['code'], 'label': e['label'], 'applies_to': e['applies_to'],
                    'requires_text': e['requires_text']}
            if staff:
                item['staff_only'] = e['staff_only']
            reasons.append(item)
        return {'version': self.version, 'role': role, 'text_max_length': TEXT_MAX_LENGTH, 'reasons': reasons}

    def validate(self, code, action_type, *, role, text=None):
        """Server-side check of a request's reason; returns the catalog entry for the canonical code."""
        entry = self.get(code)
        require(entry is not None, 400, 'invalid_reason_code', 'Lý do không thuộc danh mục lý do hợp lệ.')
        require(not entry['staff_only'] or role in ('staff', 'manager'), 403, 'permission_denied',
                'Khách hàng không được dùng lý do này; chỉ nhân viên mới tạo được yêu cầu với lý do đó.')
        require(action_type in entry['applies_to'], 400, 'reason_not_applicable',
                f"Lý do \"{entry['label']}\" không áp dụng cho loại yêu cầu này.")
        require(not entry['requires_text'] or bool(text), 400, 'reason_text_required',
                f"Lý do \"{entry['label']}\" bắt buộc nhập mô tả.")
        return entry


_lock = threading.Lock()
_cached = None


def load_catalog(path=None):
    """Read and validate a catalog file; raises ReasonCatalogError when it cannot be used."""
    target = path or CATALOG_PATH
    try:
        document = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ReasonCatalogError(f'Cannot read order-action reason catalog {target.name}: {type(exc).__name__}.') from None
    return ReasonCatalog(document)


def reason_catalog():
    """The validated shared catalog. The first call validates the file, so startup fails closed."""
    global _cached
    if _cached is None:
        with _lock:
            if _cached is None:
                _cached = load_catalog()
    return _cached


def reset_catalog_cache():
    """For tests that swap the catalog file."""
    global _cached
    with _lock:
        _cached = None
