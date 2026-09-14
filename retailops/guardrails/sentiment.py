"""Sentiment guardrail for customer interaction.
Detects customer frustration/anger to enforce strict professionalism and prevent joking.
"""
from dataclasses import dataclass
from typing import Literal

SentimentType = Literal["positive", "neutral", "negative"]

FRUSTRATION_KEYWORDS = [
    # Tiếng Việt cáu gắt / bực tức / khiếu nại
    "bực", "tức", "lừa đảo", "lừa", "tệ", "chán", "chậm", "kém", "như hạch", "thất vọng",
    "bố láo", "vớ vẩn", "tẩy chay", "tồi tệ", "làm ăn", "khiếu nại", "kiện", "giao chậm",
    "hỏng", "rách", "thiếu hàng", "mất dạy", "mẹ kiếp", "đcm", "dm", "vcl", "clgt", "đm",
    "quá lâu", "treo đầu dê", "bán thịt chó", "gặp nhân viên", "gặp quản lý",
    # English keywords
    "angry", "scam", "fraud", "terrible", "worst", "horrible", "refund now",
    "unacceptable", "ridiculous", "cheat", "disappointed", "complaint", "sue"
]

POLITE_KEYWORDS = [
    "cảm ơn", "dạ", "ạ", "vui lòng", "phiền shop", "giúp mình", "thank", "thanks", "please"
]


@dataclass
class SentimentResult:
    sentiment: SentimentType
    is_frustrated: bool
    strict_mode_required: bool
    reason: str | None = None


def analyze_sentiment(text: str) -> SentimentResult:
    """Analyze user text for emotional cues and frustration.
    Fast deterministic detection (sub-millisecond) for real-time safety.
    """
    if not text:
        return SentimentResult(sentiment="neutral", is_frustrated=False, strict_mode_required=False)

    lower = text.lower()
    
    # Check for frustration / anger cues
    matched_frustration = [kw for kw in FRUSTRATION_KEYWORDS if kw in lower]
    if matched_frustration:
        return SentimentResult(
            sentiment="negative",
            is_frustrated=True,
            strict_mode_required=True,
            reason=f"Phát hiện cảm xúc tiêu cực: {', '.join(matched_frustration[:3])}"
        )

    # Check for excessive exclamation marks or ALL CAPS shouting
    if lower != text and len(text) > 15 and sum(1 for c in text if c.isupper()) / len(text) > 0.6:
        return SentimentResult(
            sentiment="negative",
            is_frustrated=True,
            strict_mode_required=True,
            reason="Khách hàng đang viết hoa toàn bộ (shouting)"
        )

    # Polite / positive cues
    matched_polite = [kw for kw in POLITE_KEYWORDS if kw in lower]
    if matched_polite:
        return SentimentResult(
            sentiment="positive",
            is_frustrated=False,
            strict_mode_required=False,
            reason="Khách hàng lịch sự"
        )

    return SentimentResult(sentiment="neutral", is_frustrated=False, strict_mode_required=False)
