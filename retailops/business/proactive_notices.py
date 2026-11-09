"""Proactive customer system notices at key shipment and compensation milestones (W6.1b-2-D6, D10).

Emits deterministic `sys-notice-<shipment_id>-<milestone>` turns into the customer's
latest conversation using the existing `system_case_notice` (`sys-notice-`) mechanism.
Contains zero recipient personal data and guarantees at most one notice per
`(shipment_id, milestone)` across event replays, background rescans, and multiple conversations.
"""
from __future__ import annotations

import json
from typing import Any

PROACTIVE_NOTICE_MILESTONES = frozenset(
    {
        "out_for_delivery",
        "delivery_failed",
        "delivered",
        "late_delivery",
        "voucher_issued",
    }
)

DEFAULT_CONVERSATION_TTL_SECONDS = 7 * 86400.0


def build_proactive_notice_request_id(shipment_id: str, milestone: str) -> str:
    """Return deterministic `sys-notice-<shipment_id>-<milestone>` identifier (W6.1b-2-D6)."""
    ship_clean = str(shipment_id or "").strip()
    mile_clean = str(milestone or "").strip()
    if not ship_clean:
        raise ValueError("shipment_id must be non-empty for proactive notice")
    if mile_clean not in PROACTIVE_NOTICE_MILESTONES:
        raise ValueError(f"Unsupported proactive notice milestone: {mile_clean!r}")
    return f"sys-notice-{ship_clean}-{mile_clean}"


def emit_proactive_shipment_notice_in_tx(
    db: Any,
    *,
    customer_id: str,
    shipment_id: str,
    milestone: str,
    notice_text: str,
    order_id: str | None = None,
    now_ts: float,
    ttl_seconds: float = DEFAULT_CONVERSATION_TTL_SECONDS,
) -> int | None:
    """Insert a proactive `sys-notice-<shipment_id>-<milestone>` turn into the customer's latest conversation.

    - Deduplicates across all conversations in the tenant schema (`SELECT id FROM agent_turns WHERE request_id = ?`).
    - No-ops cleanly and returns `None` when the customer has no conversation.
    - Caller must pass `notice_text` containing zero recipient PII.
    """
    cust_clean = str(customer_id or "").strip()
    if not cust_clean:
        return None
    req_id = build_proactive_notice_request_id(shipment_id, milestone)

    existing = db.execute(
        "SELECT id FROM agent_turns WHERE request_id = ? LIMIT 1",
        (req_id,),
    ).fetchone()
    if existing is not None:
        return int(existing["id"] if "id" in existing else existing[0])

    conv = db.execute(
        """SELECT c.id, c.order_id, c.product_id, c.expires_at
           FROM conversations c
           WHERE c.customer_id = ?
           ORDER BY c.expires_at DESC,
                    COALESCE((SELECT MAX(t.created_at) FROM agent_turns t WHERE t.conversation_id = c.id), 0) DESC,
                    c.id DESC
           LIMIT 1""",
        (cust_clean,),
    ).fetchone()
    if conv is None:
        return None

    conv_id = str(conv["id"])
    case_row = db.execute(
        "SELECT case_id FROM cases WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 1",
        (conv_id,),
    ).fetchone()
    case_id_val = str(case_row["case_id"]) if case_row is not None and case_row["case_id"] else None

    turn_messages = [{"role": "assistant", "content": notice_text}]
    turn_result: dict[str, Any] = {
        "message": notice_text,
        "author": "system_case_notice",
        "source": "interface",
        "milestone": milestone,
        "shipment_id": str(shipment_id),
        "order_id": order_id,
        "case_id": case_id_val,
        "context": {
            "order_id": conv["order_id"] or order_id,
            "product_id": conv["product_id"],
        },
        "trace": {
            "proactive_milestone": milestone,
            "shipment_id": str(shipment_id),
            "order_id": order_id,
        },
    }
    db.execute(
        """INSERT INTO agent_turns(conversation_id, customer_id, request_id, input_hash, messages, result, created_at)
           VALUES (?, ?, ?, 'system-case-notice', ?, ?, ?)
           ON CONFLICT(conversation_id, request_id) DO NOTHING""",
        (
            conv_id,
            cust_clean,
            req_id,
            json.dumps(turn_messages, ensure_ascii=False),
            json.dumps(turn_result, ensure_ascii=False),
            float(now_ts),
        ),
    )
    new_exp = max(float(conv["expires_at"]), float(now_ts) + float(ttl_seconds))
    db.execute("UPDATE conversations SET expires_at = ? WHERE id = ?", (new_exp, conv_id))
    turn_row = db.execute(
        "SELECT id FROM agent_turns WHERE conversation_id = ? AND request_id = ?",
        (conv_id, req_id),
    ).fetchone()
    if turn_row is None:
        return None
    return int(turn_row["id"] if "id" in turn_row else turn_row[0])
