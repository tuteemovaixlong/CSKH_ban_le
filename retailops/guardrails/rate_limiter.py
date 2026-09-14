"""Rate limiting and OOD query abuse tracker.
Prevents users from abusing the CSKH bot as a free general-purpose assistant/homework solver.
"""
from dataclasses import dataclass

MAX_CONSECUTIVE_OOD = 2  # Max consecutive out-of-domain queries allowed before cutoff


@dataclass
class OODLimiterResult:
    allow_witty_pivot: bool
    current_count: int
    cutoff_message: str | None = None


def check_ood_limit(consecutive_ood_count: int) -> OODLimiterResult:
    """Check if the user has asked too many consecutive out-of-domain questions."""
    if consecutive_ood_count >= MAX_CONSECUTIVE_OOD:
        return OODLimiterResult(
            allow_witty_pivot=False,
            current_count=consecutive_ood_count,
            cutoff_message=(
                "Dạ em rất vui được trò chuyện cùng anh/chị, nhưng em chỉ được phép hỗ trợ các vấn đề mua sắm và đơn hàng thôi ạ! "
                "Anh/chị đang quan tâm đến sản phẩm nào hoặc cần kiểm tra đơn nào để em tra cứu ngay nhé?"
            )
        )
    return OODLimiterResult(
        allow_witty_pivot=True,
        current_count=consecutive_ood_count
    )
