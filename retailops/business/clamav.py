"""ClamAV clamd TCP INSTREAM malware scanner client with fail-closed semantics (W4-D3)."""
from __future__ import annotations

import os
import socket
import struct
import time

from retailops.core import ApiError

DEFAULT_CLAMD_PORT = 3310
DEFAULT_CLAMD_TIMEOUT_SECONDS = 15.0
INSTREAM_CHUNK_BYTES = 65_536
MAX_CLAMD_REPLY_BYTES = 4096


class ClamdScanner:
    """Streams raw bytes over TCP to clamd using the null-delimited zINSTREAM protocol."""

    def __init__(
        self,
        host: str | None,
        port: int = DEFAULT_CLAMD_PORT,
        *,
        timeout_seconds: float = DEFAULT_CLAMD_TIMEOUT_SECONDS,
    ) -> None:
        self.host = (host or "").strip()
        self.port = int(port)
        self.timeout_seconds = float(timeout_seconds)

    @classmethod
    def from_environment(cls, environ=None) -> ClamdScanner:
        env = os.environ if environ is None else environ
        host = (env.get("RETAILOPS_CLAMD_HOST") or "").strip()
        raw_port = (env.get("RETAILOPS_CLAMD_PORT") or str(DEFAULT_CLAMD_PORT)).strip()
        raw_timeout = (env.get("RETAILOPS_CLAMD_TIMEOUT_SECONDS") or str(DEFAULT_CLAMD_TIMEOUT_SECONDS)).strip()
        try:
            port = int(raw_port)
        except ValueError:
            port = DEFAULT_CLAMD_PORT
        try:
            timeout_seconds = float(raw_timeout)
        except ValueError:
            timeout_seconds = DEFAULT_CLAMD_TIMEOUT_SECONDS
        if port <= 0 or port > 65535 or timeout_seconds <= 0:
            return cls("", DEFAULT_CLAMD_PORT, timeout_seconds=DEFAULT_CLAMD_TIMEOUT_SECONDS)
        return cls(host, port, timeout_seconds=timeout_seconds)

    def scan_bytes(self, payload: bytes) -> dict:
        """Scan bytes via clamd zINSTREAM. Returns clean metadata or raises fail-closed ApiError."""
        if not self.host:
            raise ApiError(
                503,
                "malware_scanner_unavailable",
                "Dịch vụ quét mã độc chưa sẵn sàng; từ chối nhận tệp PDF để đảm bảo an toàn.",
            )
        data = bytes(payload)
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout_seconds) as sock:
                sock.settimeout(self.timeout_seconds)
                sock.sendall(b"zINSTREAM\x00")
                offset = 0
                total = len(data)
                while offset < total:
                    chunk = data[offset : offset + INSTREAM_CHUNK_BYTES]
                    sock.sendall(struct.pack("!I", len(chunk)))
                    sock.sendall(chunk)
                    offset += len(chunk)
                sock.sendall(struct.pack("!I", 0))

                chunks: list[bytes] = []
                received = 0
                while received < MAX_CLAMD_REPLY_BYTES:
                    piece = sock.recv(min(1024, MAX_CLAMD_REPLY_BYTES - received))
                    if not piece:
                        break
                    chunks.append(piece)
                    received += len(piece)
                    if b"\x00" in piece or b"\n" in piece:
                        break
        except OSError:
            raise ApiError(
                503,
                "malware_scanner_unavailable",
                "Máy quét mã độc không phản hồi; từ chối nhận tệp PDF để đảm bảo an toàn.",
            ) from None

        raw_reply = b"".join(chunks).split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()
        if not raw_reply:
            raise ApiError(
                503,
                "malware_scanner_unavailable",
                "Phản hồi từ máy quét mã độc rỗng; từ chối nhận tệp PDF.",
            )
        # Standard clamd response format: "stream: OK" or "stream: <Signature> FOUND" or "stream: <Reason> ERROR"
        _, _, verdict = raw_reply.partition(":")
        verdict = (verdict or raw_reply).strip()
        if verdict == "OK":
            return {
                "status": "clean",
                "engine": "clamav",
                "scanned_at": time.time(),
            }
        if verdict.endswith("FOUND"):
            raise ApiError(
                422,
                "malware_detected",
                "Tệp PDF bị từ chối vì phát hiện mã độc khi quét an toàn.",
            )
        raise ApiError(
            503,
            "malware_scanner_unavailable",
            "Máy quét mã độc báo lỗi nội bộ; từ chối nhận tệp PDF để đảm bảo an toàn.",
        )
