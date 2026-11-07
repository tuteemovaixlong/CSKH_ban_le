"""Máy trạng thái cho đơn hàng, vận đơn, thanh toán và hoàn tiền (W6.1a)."""

from __future__ import annotations


class StateTransitionError(ValueError):
    """Lỗi chuyển trạng thái không hợp lệ hoặc đi lùi."""


ALLOWED_ORDER_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"pending"}),
    "pending": frozenset({"confirmed", "cancelled"}),
    "confirmed": frozenset({"shipping", "cancelled"}),
    "shipping": frozenset({"delivered", "cancelled"}),
    "delivered": frozenset(),
    "cancelled": frozenset(),
}

# Tập các giai đoạn chuẩn nội bộ của sàn ảo (ánh xạ 1-1 sang mã gốc từng hãng).
SHIPMENT_STAGES = frozenset(
    {
        "ready_to_pick",
        "picking",
        "picked",
        "storing",
        "transporting",
        "sorting",
        "delivering",
        "delivered",
        "delivery_fail",
        "waiting_to_return",
        "return",
        "returned",
        "cancel",
    }
)

ALLOWED_SHIPMENT_STAGE_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"ready_to_pick"}),
    "ready_to_pick": frozenset({"picking", "cancel"}),
    "picking": frozenset({"picked", "cancel"}),
    "picked": frozenset({"storing", "transporting"}),
    "storing": frozenset({"transporting", "sorting"}),
    "transporting": frozenset({"sorting", "delivering"}),
    "sorting": frozenset({"delivering"}),
    "delivering": frozenset({"delivered", "delivery_fail"}),
    "delivery_fail": frozenset({"delivering", "waiting_to_return"}),
    "waiting_to_return": frozenset({"return"}),
    "return": frozenset({"returned"}),
    "returned": frozenset(),
    "delivered": frozenset(),
    "cancel": frozenset(),
}

ALLOWED_PAYMENT_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"PAY_PENDING", "COD_PENDING", "COD_SETTLED"}),
    "PAY_PENDING": frozenset({"PAY_SUCCEEDED", "PAY_FAILED"}),
    "PAY_SUCCEEDED": frozenset(),
    "PAY_FAILED": frozenset(),
    "COD_PENDING": frozenset({"COD_SETTLED", "COD_CANCELLED"}),
    "COD_SETTLED": frozenset(),
    "COD_CANCELLED": frozenset(),
}

SUCCEEDED_PAYMENT_STATUSES = frozenset({"PAY_SUCCEEDED", "COD_SETTLED"})

ALLOWED_REFUND_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"REFUND_INITIATED"}),
    "REFUND_INITIATED": frozenset(
        {"REFUND_PROCESSING", "REFUND_COMPLETED", "REFUND_FAILED"}
    ),
    "REFUND_PROCESSING": frozenset({"REFUND_COMPLETED", "REFUND_FAILED"}),
    "REFUND_COMPLETED": frozenset(),
    "REFUND_FAILED": frozenset(),
}


def validate_order_transition(current: str | None, target: str) -> None:
    allowed = ALLOWED_ORDER_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise StateTransitionError(
            f"Chuyển trạng thái đơn không hợp lệ: {current!r} -> {target!r}."
        )


def validate_shipment_transition(
    current_stage: str | None,
    target_stage: str,
    *,
    current_attempts: int,
    max_attempts: int = 3,
) -> int:
    """Kiểm chuyển giai đoạn vận đơn và trả về số lần giao thất bại mới."""
    if target_stage not in SHIPMENT_STAGES:
        raise StateTransitionError(
            f"Giai đoạn vận đơn không hợp lệ: {target_stage!r}."
        )
    allowed = ALLOWED_SHIPMENT_STAGE_TRANSITIONS.get(current_stage, frozenset())
    if target_stage not in allowed:
        raise StateTransitionError(
            f"Vận đơn không được chuyển từ {current_stage!r} sang {target_stage!r}."
        )
    if current_stage == "delivery_fail" and current_attempts >= max_attempts:
        if target_stage != "waiting_to_return":
            raise StateTransitionError(
                f"Sau {max_attempts} lần giao thất bại, vận đơn chỉ được chuyển sang nhánh hoàn ('waiting_to_return'), không được sang {target_stage!r}."
            )
    new_attempts = current_attempts
    if target_stage == "delivery_fail":
        new_attempts = current_attempts + 1
        if new_attempts > max_attempts:
            raise StateTransitionError(
                f"Số lần giao thất bại ({new_attempts}) vượt quá giới hạn {max_attempts}."
            )
    return new_attempts


def validate_payment_transition(current: str | None, target: str) -> None:
    allowed = ALLOWED_PAYMENT_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise StateTransitionError(
            f"Chuyển trạng thái thanh toán không hợp lệ: {current!r} -> {target!r}."
        )


def validate_refund_transition(current: str | None, target: str) -> None:
    allowed = ALLOWED_REFUND_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise StateTransitionError(
            f"Chuyển trạng thái hoàn tiền không hợp lệ: {current!r} -> {target!r}."
        )
