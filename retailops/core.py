"""Shared business errors, vocabulary and asset location; no transport or model I/O."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.9'
DATA_MODE = 'synthetic-demo'
# Order-action reasons are declared once, in data/order_action_reasons.json (see retailops/order_reasons.py).
STATUSES = {"pending": "Chờ xử lý", "shipping": "Đang giao", "delivered": "Đã giao", "cancelled": "Đã hủy"}
EVIDENCE_MAX_BYTES = 10_485_760
PDF_EVIDENCE_MAX_BYTES = 20_971_520
CHAT_ATTACHMENT_JSON_MAX_BYTES = 28_311_552
EVIDENCE_MAX_COUNT = 5
EVIDENCE_RETENTION_SECONDS = 90 * 86400


class BinaryPayload:
    __slots__ = ("data", "content_type", "headers")

    def __init__(self, data: bytes, content_type: str, headers=None):
        self.data = bytes(data)
        self.content_type = str(content_type)
        self.headers = list(headers) if headers else []


class ApiError(Exception):
    def __init__(self, status, code, message, trace=None, headers=None):
        self.status, self.code, self.message = status, code, message
        self.trace = trace
        self.headers = list(headers) if headers else []
        super().__init__(message)


def require(condition, status, code, message, headers=None):
    if not condition:
        raise ApiError(status, code, message, headers=headers)


def fields(body, expected):
    require(isinstance(body, dict) and set(body) == set(expected), 400,
            "invalid_fields", "Các trường của yêu cầu không hợp lệ.")
