"""Shared business errors, vocabulary and asset location; no transport or model I/O."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.6'
DATA_MODE = 'synthetic-demo'
REASONS = {"ordered_by_mistake": "Tôi đặt nhầm", "no_longer_needed": "Tôi không còn cần"}
STATUSES = {"pending": "Chờ xử lý", "delivered": "Đã giao", "cancelled": "Đã hủy"}

class ApiError(Exception):
    def __init__(self, status, code, message, trace=None):
        self.status, self.code, self.message = status, code, message
        self.trace = trace
        super().__init__(message)


def require(condition, status, code, message):
    if not condition:
        raise ApiError(status, code, message)


def fields(body, expected):
    require(isinstance(body, dict) and set(body) == set(expected), 400,
            "invalid_fields", "Các trường của yêu cầu không hợp lệ.")
