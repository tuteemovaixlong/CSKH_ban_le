"""Private demo bearer verification; returns server-owned customer identity."""
import hashlib
import hmac

from retailops.core import require


def authenticate_bearer(header, token_hashes):
    token = header.removeprefix('Bearer ') if header.startswith('Bearer ') else ''
    hashed = hashlib.sha256(token.encode()).hexdigest()
    customer = next((c for expected, c in token_hashes.items() if hmac.compare_digest(expected, hashed)), None)
    require(customer is not None, 401, 'unauthorized', 'Nhập mã truy cập demo hợp lệ.')
    return customer
