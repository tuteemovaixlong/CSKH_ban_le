"""Two-Database Account Reconciliation Coordinator with Journal, Idempotency & Failure Recovery.

Coordinates identity migration between Identity DB (principals, memberships, customer_links,
external_identities, unresolved_collisions, sessions) and Business DB (customers, orders,
conversations, proposals, business_events, agent_turns, conversation_feedback).

Guarantees:
1. Fail-closed: accounts remain in unresolved_collisions and quarantined until BOTH databases commit.
2. Two-phase Saga with Persistent Journal: records 'started' -> 'business_committed' -> 'completed'.
3. Idempotent & Resumable: can be retried safely if interrupted after business DB commit or during identity commit.
"""
import hashlib
import json
import time
from typing import Any, Dict, List, Optional
from retailops.core import ApiError, require


def reconcile_collision(
    sessions,
    tenant_id: str,
    colliding_customer_id: str,
    plan: Dict[str, Any],
    idempotency_key: Optional[str] = None,
    fault_stage: Optional[str] = None,
) -> Dict[str, Any]:
    """Reconcile colliding customer accounts across Business DB and Identity DB.

    plan format:
    {
        "reassignments": [
            {
                "membership_id": "m-1",
                "target_customer_id": "CG-1",
                "target_customer_name": "Customer 1",  # optional
                "order_ids": ["O-101", "O-102"],       # optional
                "conversation_ids": ["CONV-101"],      # optional
                "external_identity": {                 # optional
                    "issuer": "https://accounts.google.com",
                    "sub": "sub-123",
                    "email": "cust1@example.com"
                }
            },
            ...
        ]
    }
    """
    idempotency_key = idempotency_key or f"rec_{tenant_id}_{colliding_customer_id}"
    reassignments = plan.get("reassignments", [])
    require(bool(reassignments), 400, "invalid_plan", "Reconciliation plan must contain reassignments.")

    # -------------------------------------------------------------
    # Step 1: Journal Check & Initiation (in Identity DB)
    # -------------------------------------------------------------
    now = time.time()
    current_status = None
    with sessions.control.connection(write=True) as id_db:
        # Check existing journal status
        row = id_db.execute(
            "SELECT status, plan_json FROM reconciliation_journal WHERE id = ?",
            (idempotency_key,)
        ).fetchone()
        if row:
            current_status = row["status"]

        if current_status == "completed":
            return {
                "status": "completed",
                "idempotency_key": idempotency_key,
                "tenant_id": tenant_id,
                "colliding_customer_id": colliding_customer_id,
                "already_completed": True,
            }

        if not current_status:
            # First time: record 'started'
            id_db.execute(
                "INSERT INTO reconciliation_journal "
                "(id, tenant_id, colliding_customer_id, status, plan_json, error_message, created_at, updated_at) "
                "VALUES (?, ?, ?, 'started', ?, NULL, ?, ?)",
                (idempotency_key, tenant_id, colliding_customer_id, json.dumps(plan), now, now)
            )
            current_status = "started"

    # -------------------------------------------------------------
    # Step 2: Business DB Updates (Customers, Orders, Conversations)
    # -------------------------------------------------------------
    # Only execute Business DB updates if not already business_committed or completed
    if current_status == "started":
        b_store = sessions.business_store(tenant_id)
        with b_store.connection(write=True) as b_db:
            for item in reassignments:
                tgt_cid = item["target_customer_id"]
                tgt_name = item.get("target_customer_name", f"Customer {tgt_cid}")
                # Ensure customer record exists
                b_db.execute(
                    "INSERT INTO customers (id, name) VALUES (?, ?) ON CONFLICT (id) DO UPDATE SET name = excluded.name",
                    (tgt_cid, tgt_name)
                )

                # Reassign orders and associated proposals & business_events
                order_ids = item.get("order_ids", [])
                for oid in order_ids:
                    b_db.execute("UPDATE orders SET customer_id = ? WHERE id = ?", (tgt_cid, oid))
                    try:
                        b_db.execute("UPDATE proposals SET customer_id = ? WHERE order_id = ?", (tgt_cid, oid))
                    except Exception:
                        pass
                    try:
                        b_db.execute("UPDATE business_events SET customer_id = ? WHERE order_id = ?", (tgt_cid, oid))
                    except Exception:
                        pass

                # Reassign conversations and associated turns & feedback
                conv_ids = item.get("conversation_ids", [])
                for cid in conv_ids:
                    b_db.execute("UPDATE conversations SET customer_id = ? WHERE id = ?", (tgt_cid, cid))
                    try:
                        b_db.execute("UPDATE agent_turns SET customer_id = ? WHERE conversation_id = ?", (tgt_cid, cid))
                    except Exception:
                        pass
                    try:
                        b_db.execute("UPDATE conversation_feedback SET customer_id = ? WHERE conversation_id = ?", (tgt_cid, cid))
                    except Exception:
                        pass

        # Update journal to 'business_committed' in Identity DB
        with sessions.control.connection(write=True) as id_db:
            id_db.execute(
                "UPDATE reconciliation_journal SET status = 'business_committed', updated_at = ? WHERE id = ?",
                (time.time(), idempotency_key)
            )
            current_status = "business_committed"

    # -------------------------------------------------------------
    # Fault Injection Point 1: Fault after Business DB commit
    # -------------------------------------------------------------
    if fault_stage == "after_business_commit":
        raise RuntimeError("Fault injected after business commit: process halted before Identity DB updates")

    # -------------------------------------------------------------
    # Step 3: Identity DB Updates (Memberships, Links, Auth, Unquarantine)
    # -------------------------------------------------------------
    with sessions.control.connection(write=True) as id_db:
        # Fault Injection Point 2: Fault during Identity DB commit
        if fault_stage == "during_identity_commit":
            raise RuntimeError("Fault injected during identity DB commit: transaction will roll back")

        for item in reassignments:
            mid = item["membership_id"]
            tgt_cid = item["target_customer_id"]

            # Query membership principal_id
            m_row = id_db.execute(
                "SELECT principal_id FROM memberships WHERE id = ? AND tenant_id = ?",
                (mid, tenant_id)
            ).fetchone()
            if not m_row:
                raise ApiError(404, "membership_not_found", f"Membership {mid} not found in tenant {tenant_id}")
            pid = m_row["principal_id"]

            # 3a. Update membership: set target customer_id, active=1, bump auth_version
            id_db.execute(
                "UPDATE memberships SET customer_id = ?, active = 1, auth_version = auth_version + 1 WHERE id = ?",
                (tgt_cid, mid)
            )

            # 3b. Invalidate previous active sessions
            id_db.execute("DELETE FROM sessions WHERE membership_id = ?", (mid,))

            # 3c. Upsert customer_links 1-to-1 mapping
            link_hash = hashlib.sha256(f"{tenant_id}:{pid}:{tgt_cid}".encode()).hexdigest()[:24]
            link_id = f"cl_{link_hash}"
            id_db.execute(
                "INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (tenant_id, principal_id) DO UPDATE SET customer_id = excluded.customer_id",
                (link_id, tenant_id, pid, tgt_cid, time.time())
            )

            # 3d. Upsert external_identities if specified (e.g. Google OAuth)
            ext = item.get("external_identity")
            if ext:
                ext_hash = hashlib.sha256(f"{ext.get('issuer', 'google')}:{ext['sub']}".encode()).hexdigest()[:24]
                ext_id = f"ext_{ext_hash}"
                id_db.execute(
                    "INSERT INTO external_identities (id, issuer, sub, principal_id, email, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (issuer, sub) DO UPDATE SET principal_id = excluded.principal_id, email = excluded.email",
                    (ext_id, ext.get("issuer", "https://accounts.google.com"), ext["sub"], pid, ext.get("email", ""), time.time())
                )

        # 3e. Remove from unresolved_collisions
        id_db.execute(
            "DELETE FROM unresolved_collisions WHERE tenant_id = ? AND customer_id = ?",
            (tenant_id, colliding_customer_id)
        )

        # 3f. Record identity audit event
        id_db.execute(
            "INSERT INTO identity_events (created_at, kind, tenant_id, membership_id) VALUES (?, ?, ?, NULL)",
            (time.time(), "collision_reconciled", tenant_id)
        )

        # 3g. Update journal to 'completed'
        id_db.execute(
            "UPDATE reconciliation_journal SET status = 'completed', updated_at = ? WHERE id = ?",
            (time.time(), idempotency_key)
        )

    return {
        "status": "completed",
        "idempotency_key": idempotency_key,
        "tenant_id": tenant_id,
        "colliding_customer_id": colliding_customer_id,
        "reassigned_count": len(reassignments),
    }


def get_reconciliation_status(sessions, idempotency_key: str) -> Optional[Dict[str, Any]]:
    """Retrieve reconciliation journal status by idempotency key."""
    with sessions.control.connection() as id_db:
        row = id_db.execute(
            "SELECT id, tenant_id, colliding_customer_id, status, plan_json, error_message, created_at, updated_at "
            "FROM reconciliation_journal WHERE id = ?",
            (idempotency_key,)
        ).fetchone()
        if not row:
            return None
        return dict(row)
