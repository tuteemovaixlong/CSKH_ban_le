"""Sàn thương mại điện tử, hãng vận chuyển và cổng thanh toán giả lập (W6.1a).

Package độc lập chỉ dùng thư viện chuẩn Python 3.10+, không import RetailOps.
"""

from __future__ import annotations

CONTRACT_NAME = "retailops-integration-v2"
DEFAULT_DATA_DIR = ".marketplace_sim"
DEFAULT_SEED = 20261106
DEFAULT_MERCHANT_ID = "MERCHANT-SIM-001"
INITIAL_CLOCK_ISO = "2026-10-01T08:00:00+07:00"

__all__ = [
    "CONTRACT_NAME",
    "DEFAULT_DATA_DIR",
    "DEFAULT_SEED",
    "DEFAULT_MERCHANT_ID",
    "INITIAL_CLOCK_ISO",
]
