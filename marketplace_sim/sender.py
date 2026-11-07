"""Gửi sự kiện qua HTTP ký HMAC-SHA256 chỉ tới loopback hoặc host nội bộ (W6.1a mục 9)."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
import re
import time
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request

RETRY_DELAYS_SECONDS: tuple[int, ...] = (1, 2, 4, 8, 16)
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
DOCKER_SERVICE_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$")


class EndpointNotAllowedError(ValueError):
    """Host nhận sự kiện nằm ngoài danh sách loopback / mạng nội bộ cho phép."""


class SecretFileError(ValueError):
    """Tệp khóa ký không hợp lệ hoặc không đọc được."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise urllib.error.HTTPError(
            req.full_url,
            code,
            "Không chấp nhận HTTP redirect khi gửi sự kiện.",
            headers,
            fp,
        )


def validate_endpoint_url(endpoint: str) -> str:
    """Chỉ cho phép gửi tới localhost, 127.0.0.1, ::1 hoặc tên service không có dấu chấm."""
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise EndpointNotAllowedError("URL đích không được để trống.")
    url = endpoint.strip()
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise EndpointNotAllowedError(
            "URL đích phải dùng giao thức http hoặc https."
        )
    if parsed.username is not None or parsed.password is not None:
        raise EndpointNotAllowedError(
            "URL đích không được chứa thông tin xác thực nhúng."
        )
    hostname = parsed.hostname
    if not hostname:
        raise EndpointNotAllowedError("URL đích thiếu tên máy chủ (host).")

    host_lower = hostname.lower()
    if host_lower in LOOPBACK_HOSTS:
        return url

    if (
        "." not in host_lower
        and ":" not in host_lower
        and not host_lower.isdigit()
        and not host_lower.startswith("0x")
        and DOCKER_SERVICE_HOST_RE.fullmatch(hostname)
    ):
        return url

    raise EndpointNotAllowedError(
        f"Từ chối gửi tới host '{hostname}': chỉ cho phép localhost, 127.0.0.1, ::1 hoặc tên service không có dấu chấm."
    )


def load_signing_secret(secret_file: str | Path) -> bytes:
    """Đọc khóa ký từ tệp mà tuyệt đối không đưa nội dung khóa vào thông báo lỗi."""
    path = Path(secret_file)
    if not path.is_file():
        raise SecretFileError(
            f"Không tìm thấy tệp khóa ký: '{path}'."
        )
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SecretFileError(
            f"Không đọc được tệp khóa ký: '{path}'."
        ) from exc
    if not raw:
        raise SecretFileError("Tệp khóa ký đang rỗng.")
    return raw.encode("utf-8")


def compute_signature(secret_bytes: bytes, timestamp: int, raw_body: bytes) -> str:
    """Tính chữ ký v1=<hex HMAC-SHA256> trên chuỗi '<timestamp>.' + raw_body."""
    signing_input = f"{int(timestamp)}.".encode("ascii") + raw_body
    digest = hmac.new(secret_bytes, signing_input, hashlib.sha256).hexdigest()
    return f"v1={digest}"


def build_signed_headers(
    event_id: str, secret_bytes: bytes, timestamp: int, raw_body: bytes
) -> dict[str, str]:
    return {
        "Content-Type": "application/json; charset=utf-8",
        "X-Sim-Event-Id": event_id,
        "X-Sim-Timestamp": str(int(timestamp)),
        "X-Sim-Signature": compute_signature(secret_bytes, timestamp, raw_body),
    }


def _post_once(
    opener: urllib.request.OpenerDirector,
    url: str,
    raw_body: bytes,
    headers: dict[str, str],
    timeout: float,
) -> tuple[bool, int | None, str | None]:
    req = urllib.request.Request(
        url, data=raw_body, headers=headers, method="POST"
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            code = int(resp.getcode() or 200)
            resp.read()
            if (200 <= code < 300) or code == 409:
                return True, code, None
            return False, code, f"HTTP {code}"
    except urllib.error.HTTPError as exc:
        code = int(exc.code)
        try:
            exc.read()
        except Exception:
            pass
        if (200 <= code < 300) or code == 409:
            return True, code, None
        return False, code, f"HTTP {code}"
    except Exception as exc:
        return False, None, exc.__class__.__name__


def deliver_event_with_retries(
    *,
    endpoint: str,
    event_id: str,
    raw_body: bytes,
    secret_bytes: bytes,
    time_fn: Callable[[], float] = time.time,
    sleep_fn: Callable[[float], None] = time.sleep,
    timeout: float = 5.0,
) -> tuple[str, int, str | None]:
    """Gửi một sự kiện kèm thử lại 1, 2, 4, 8, 16 giây; quá 5 lần thử lại thì dead.

    Trả về ``(status, attempts_made, last_error)`` với ``status`` là ``'sent'`` hoặc ``'dead'``.
    """
    validated_url = validate_endpoint_url(endpoint)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
    )

    max_retries = len(RETRY_DELAYS_SECONDS)
    attempts = 0
    last_error: str | None = None

    for retry_idx in range(max_retries + 1):
        if retry_idx > 0:
            sleep_fn(RETRY_DELAYS_SECONDS[retry_idx - 1])
        attempts += 1
        ts = int(time_fn())
        headers = build_signed_headers(event_id, secret_bytes, ts, raw_body)
        ok, _code, err = _post_once(
            opener, validated_url, raw_body, headers, timeout
        )
        if ok:
            return "sent", attempts, None
        last_error = err or "send_failed"

    return "dead", attempts, last_error
