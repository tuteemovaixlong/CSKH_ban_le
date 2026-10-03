"""Two-Database Account Reconciliation Coordinator with Journal, Idempotency & Failure Recovery.

Coordinates identity migration between Identity DB (principals, memberships, customer_links,
external_identities, unresolved_collisions, sessions) and Business DB (customers, orders,
conversations, proposals, business_events, agent_turns, conversation_feedback).

Guarantees:
1. Fail-closed: accounts remain in unresolved_collisions and quarantined until BOTH databases commit.
2. Two-phase Saga with Persistent Journal: records 'started' -> 'business_committed' -> 'completed'.
3. Idempotent & Resumable: bound to immutable canonical plan hash; safely resumes using saved plan.
4. Data Integrity: validates owners, rowcounts, and prevents identity hijacking.
"""
import hashlib
import json
import time
from typing import Any, Dict, List, Optional
from retailops.core import ApiError, require


def canonical_plan_json(plan: Dict[str, Any]) -> str:
    """Deterministic, key-sorted JSON representation for plan immutability."""
    return json.dumps(plan, sort_keys=True, separators=(',', ':'))


def hash_plan(plan: Dict[str, Any]) -> str:
    """Cryptographic hash of the canonical plan."""
    return hashlib.sha256(canonical_plan_json(plan).encode('utf-8')).hexdigest()


def _has_table(db, table_name: str) -> bool:
    """Safe table existence check across SQLite and PostgreSQL without breaking transactions."""
    raw = getattr(db, 'raw', db)
    is_sqlite = type(raw).__module__.startswith('sqlite3')
    if is_sqlite:
        return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone())
    # PostgreSQL
    row = db.execute("SELECT 1 FROM pg_tables WHERE schemaname = current_schema() AND tablename = ?", (table_name,)).fetchone()
    return bool(row)


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
    require(bool(tenant_id), 400, "invalid_tenant", "Tenant ID is required.")
    require(bool(colliding_customer_id), 400, "invalid_colliding_customer", "Colliding customer ID is required.")
    reassignments = plan.get("reassignments", [])
    require(bool(reassignments), 400, "invalid_plan", "Reconciliation plan must contain reassignments.")
    idempotency_key = idempotency_key or f"rec_{tenant_id}_{colliding_customer_id}"

    # -------------------------------------------------------------
    # Step 1: Pre-validation & Journal Check & Initiation (Identity DB)
    # -------------------------------------------------------------
    now = time.time()
    current_status = None
    saved_plan = None
    current_plan_hash = hash_plan(plan)

    with sessions.control.connection(write=True) as id_db:
        # 1a. Validate tenant existence
        t_row = id_db.execute("SELECT id FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        require(bool(t_row), 404, "tenant_not_found", f"Tenant {tenant_id} not found.")

        # 1b. Validate unresolved_collisions table
        col_row = id_db.execute(
            "SELECT 1 FROM unresolved_collisions WHERE tenant_id = ? AND customer_id = ?",
            (tenant_id, colliding_customer_id)
        ).fetchone()

        # 1c. Check existing journal entry
        row = id_db.execute(
            "SELECT status, plan_json, plan_hash FROM reconciliation_journal WHERE id = ?",
            (idempotency_key,)
        ).fetchone()

        if row:
            row_dict = dict(row)
            current_status = row_dict["status"]
            saved_plan = json.loads(row_dict["plan_json"])
            saved_hash = row_dict.get("plan_hash") or hash_plan(saved_plan)

            # Idempotency safety: forbid retrying with a different plan!
            if saved_hash != current_plan_hash:
                raise ApiError(
                    409,
                    "plan_conflict",
                    f"Idempotency key {idempotency_key} is bound to an immutable plan. Cannot resume with modified plan."
                )

            # CRITICAL: Always resume execution using the saved plan from the journal
            plan = saved_plan
            reassignments = plan.get("reassignments", [])

            if current_status == "completed":
                return {
                    "status": "completed",
                    "idempotency_key": idempotency_key,
                    "tenant_id": tenant_id,
                    "colliding_customer_id": colliding_customer_id,
                    "already_completed": True,
                }
        else:
            # First time: must have an active collision record
            require(
                bool(col_row),
                404,
                "collision_not_found",
                f"No active collision record for customer {colliding_customer_id} in tenant {tenant_id}."
            )

            # Record 'started' with canonical plan & plan_hash
            canonical_json = canonical_plan_json(plan)
            id_db.execute(
                "INSERT INTO reconciliation_journal "
                "(id, tenant_id, colliding_customer_id, status, plan_json, plan_hash, error_message, created_at, updated_at) "
                "VALUES (?, ?, ?, 'started', ?, ?, NULL, ?, ?)",
                (idempotency_key, tenant_id, colliding_customer_id, canonical_json, current_plan_hash, now, now)
            )
            current_status = "started"

        # 1d. Identify all memberships belonging to colliding_customer_id in tenant
        m_candidates = id_db.execute(
            "SELECT id, principal_id, customer_id FROM memberships WHERE tenant_id = ? AND role = 'customer'",
            (tenant_id,)
        ).fetchall()
        expected_collision_mids = set()
        for cand in m_candidates:
            cid = cand["customer_id"]
            hash_key = f"{tenant_id}:{cand['principal_id']}:{colliding_customer_id}".encode()
            cand_quarantine_cid = f"cust_{hashlib.sha256(hash_key).hexdigest()[:32]}"
            if cid == colliding_customer_id or cid == cand_quarantine_cid:
                expected_collision_mids.add(cand["id"])

        plan_mids = [item.get("membership_id") for item in reassignments]
        plan_mids_set = set(plan_mids)
        if len(plan_mids) != len(plan_mids_set):
            raise ApiError(400, "duplicate_membership_reassignment", "Plan contains duplicate membership reassignments.")

        # Ensure all colliding memberships are covered in the plan
        if expected_collision_mids:
            missing_mids = expected_collision_mids - plan_mids_set
            if missing_mids:
                raise ApiError(
                    400,
                    "incomplete_membership_coverage",
                    f"Reconciliation plan does not cover all memberships for colliding customer {colliding_customer_id}. Missing memberships: {sorted(missing_mids)}"
                )

        # Validate memberships belong to tenant and colliding customer
        target_cids = set()
        for item in reassignments:
            mid = item.get("membership_id")
            tgt_cid = item.get("target_customer_id")
            require(bool(mid and tgt_cid), 400, "invalid_reassignment", "Each reassignment must specify membership_id and target_customer_id.")
            target_cids.add(tgt_cid)
            m_row = id_db.execute(
                "SELECT tenant_id, customer_id, principal_id FROM memberships WHERE id = ?",
                (mid,)
            ).fetchone()
            require(bool(m_row), 404, "membership_not_found", f"Membership {mid} not found.")
            require(m_row["tenant_id"] == tenant_id, 400, "tenant_mismatch", f"Membership {mid} does not belong to tenant {tenant_id}.")

            hash_key = f"{tenant_id}:{m_row['principal_id']}:{colliding_customer_id}".encode()
            quarantine_cid_hash = f"cust_{hashlib.sha256(hash_key).hexdigest()[:32]}"
            require(
                m_row["customer_id"] in (colliding_customer_id, quarantine_cid_hash, tgt_cid),
                400,
                "membership_customer_mismatch",
                f"Membership {mid} customer ({m_row['customer_id']}) does not match colliding customer {colliding_customer_id}."
            )

            # Pre-check external_identity hijacking before touching business DB
            ext = item.get("external_identity")
            if ext:
                issuer = ext.get("issuer", "https://accounts.google.com")
                sub = ext.get("sub")
                if sub:
                    existing_ext = id_db.execute(
                        "SELECT principal_id FROM external_identities WHERE issuer = ? AND sub = ?",
                        (issuer, sub)
                    ).fetchone()
                    if existing_ext and existing_ext["principal_id"] != m_row["principal_id"]:
                        raise ApiError(
                            409,
                            "external_identity_conflict",
                            f"Identity {issuer}:{sub} is already linked to principal {existing_ext['principal_id']}. Cannot reassign to {m_row['principal_id']}."
                        )

    # -------------------------------------------------------------
    # Step 2: Business DB Updates (Customers, Orders, Conversations)
    # -------------------------------------------------------------
    if current_status == "started":
        b_store = sessions.business_store(tenant_id)
        with b_store.connection(write=True) as b_db:
            has_proposals = _has_table(b_db, "proposals")
            has_events = _has_table(b_db, "business_events")
            has_turns = _has_table(b_db, "agent_turns")
            has_feedback = _has_table(b_db, "conversation_feedback")

            quarantine_cid = f"quarantine_{colliding_customer_id}"
            source_cids = {colliding_customer_id, quarantine_cid}

            # 2a. Pre-validate individual order and conversation ownership/existence
            plan_order_ids = []
            plan_conv_ids = []
            for item in reassignments:
                tgt_cid = item["target_customer_id"]
                for oid in item.get("order_ids", []):
                    ord_row = b_db.execute("SELECT customer_id FROM orders WHERE id = ?", (oid,)).fetchone()
                    if not ord_row:
                        raise ApiError(404, "order_not_found", f"Order {oid} not found in tenant {tenant_id}.")
                    current_owner = ord_row["customer_id"]
                    if current_owner not in source_cids and current_owner != tgt_cid:
                        raise ApiError(
                            403,
                            "order_ownership_conflict",
                            f"Order {oid} is owned by {current_owner}, expected colliding owner {colliding_customer_id}."
                        )
                    plan_order_ids.append(oid)

                for cid in item.get("conversation_ids", []):
                    conv_row = b_db.execute("SELECT customer_id FROM conversations WHERE id = ?", (cid,)).fetchone()
                    if not conv_row:
                        raise ApiError(404, "conversation_not_found", f"Conversation {cid} not found in tenant {tenant_id}.")
                    current_owner = conv_row["customer_id"]
                    if current_owner not in source_cids and current_owner != tgt_cid:
                        raise ApiError(
                            403,
                            "conversation_ownership_conflict",
                            f"Conversation {cid} is owned by {current_owner}, expected colliding owner {colliding_customer_id}."
                        )
                    plan_conv_ids.append(cid)

            # Check duplicates across reassignments
            if len(plan_order_ids) != len(set(plan_order_ids)):
                raise ApiError(400, "duplicate_order_reassignment", "Plan contains duplicate order reassignments across memberships.")
            if len(plan_conv_ids) != len(set(plan_conv_ids)):
                raise ApiError(400, "duplicate_conversation_reassignment", "Plan contains duplicate conversation reassignments across memberships.")

            # 2b. Check complete coverage of all quarantined / colliding data
            raw_orders = b_db.execute(
                "SELECT id, customer_id FROM orders WHERE customer_id IN (?, ?)",
                (colliding_customer_id, quarantine_cid)
            ).fetchall()
            quarantined_order_ids = {r["id"] for r in raw_orders}

            raw_convs = b_db.execute(
                "SELECT id, customer_id FROM conversations WHERE customer_id IN (?, ?)",
                (colliding_customer_id, quarantine_cid)
            ).fetchall()
            quarantined_conv_ids = {r["id"] for r in raw_convs}

            missing_orders = quarantined_order_ids - set(plan_order_ids)
            if missing_orders:
                raise ApiError(
                    400,
                    "incomplete_order_coverage",
                    f"Reconciliation plan does not account for all quarantined orders for {colliding_customer_id}. Unassigned orders: {sorted(missing_orders)}"
                )

            missing_convs = quarantined_conv_ids - set(plan_conv_ids)
            if missing_convs:
                raise ApiError(
                    400,
                    "incomplete_conversation_coverage",
                    f"Reconciliation plan does not account for all quarantined conversations for {colliding_customer_id}. Unassigned conversations: {sorted(missing_convs)}"
                )

            # 2c. Execute updates
            for item in reassignments:
                tgt_cid = item["target_customer_id"]
                tgt_name = item.get("target_customer_name", f"Customer {tgt_cid}")
                b_db.execute(
                    "INSERT INTO customers (id, name) VALUES (?, ?) ON CONFLICT (id) DO UPDATE SET name = excluded.name",
                    (tgt_cid, tgt_name)
                )

                for oid in item.get("order_ids", []):
                    ord_row = b_db.execute("SELECT customer_id FROM orders WHERE id = ?", (oid,)).fetchone()
                    if ord_row and ord_row["customer_id"] in source_cids:
                        cur = b_db.execute(
                            "UPDATE orders SET customer_id = ? WHERE id = ? AND customer_id = ?",
                            (tgt_cid, oid, ord_row["customer_id"])
                        )
                        if getattr(cur, "rowcount", None) == 0:
                            raise ApiError(500, "order_update_failed", f"Failed to update owner for order {oid}.")
                    if has_proposals:
                        b_db.execute("UPDATE proposals SET customer_id = ? WHERE order_id = ?", (tgt_cid, oid))
                    if has_events:
                        b_db.execute("UPDATE business_events SET customer_id = ? WHERE order_id = ?", (tgt_cid, oid))

                for cid in item.get("conversation_ids", []):
                    conv_row = b_db.execute("SELECT customer_id FROM conversations WHERE id = ?", (cid,)).fetchone()
                    if conv_row and conv_row["customer_id"] in source_cids:
                        cur = b_db.execute(
                            "UPDATE conversations SET customer_id = ? WHERE id = ? AND customer_id = ?",
                            (tgt_cid, cid, conv_row["customer_id"])
                        )
                        if getattr(cur, "rowcount", None) == 0:
                            raise ApiError(500, "conversation_update_failed", f"Failed to update owner for conversation {cid}.")
                    if has_turns:
                        b_db.execute("UPDATE agent_turns SET customer_id = ? WHERE conversation_id = ?", (tgt_cid, cid))
                    if has_feedback:
                        b_db.execute("UPDATE conversation_feedback SET customer_id = ? WHERE conversation_id = ?", (tgt_cid, cid))

            # Clean up quarantine placeholder customer record if exists
            b_db.execute("DELETE FROM customers WHERE id = ?", (quarantine_cid,))

        # Fault Injection Point 1a: Crash after Business commit but BEFORE journal update
        if fault_stage == "after_business_commit_before_journal":
            raise RuntimeError("Fault injected after business commit before journal update: journal is still 'started'")

        # Update journal to 'business_committed' in Identity DB
        with sessions.control.connection(write=True) as id_db:
            id_db.execute(
                "UPDATE reconciliation_journal SET status = 'business_committed', updated_at = ? WHERE id = ?",
                (time.time(), idempotency_key)
            )
            current_status = "business_committed"

    # Fault Injection Point 1b: Crash after Business DB commit and journal updated
    if fault_stage == "after_business_commit":
        raise RuntimeError("Fault injected after business commit: process halted before Identity DB updates")

    # -------------------------------------------------------------
    # Step 3: Identity DB Updates (Memberships, Links, Auth, Unquarantine)
    # -------------------------------------------------------------
    with sessions.control.connection(write=True) as id_db:
        # Pre-execution fault injection (for compatibility)
        if fault_stage == "during_identity_commit":
            raise RuntimeError("Fault injected during identity DB commit: transaction will roll back")

        # Collect all collision and temporary quarantine customer IDs to clean up from unresolved_collisions
        del_cids = {colliding_customer_id, f"quarantine_{colliding_customer_id}"}
        for item in reassignments:
            mid = item["membership_id"]
            m_prev = id_db.execute(
                "SELECT customer_id FROM memberships WHERE id = ? AND tenant_id = ?",
                (mid, tenant_id)
            ).fetchone()
            if m_prev and m_prev["customer_id"]:
                del_cids.add(m_prev["customer_id"])

        for item in reassignments:
            mid = item["membership_id"]
            tgt_cid = item["target_customer_id"]

            m_row = id_db.execute(
                "SELECT principal_id FROM memberships WHERE id = ? AND tenant_id = ?",
                (mid, tenant_id)
            ).fetchone()
            if not m_row:
                raise ApiError(404, "membership_not_found", f"Membership {mid} not found in tenant {tenant_id}")
            pid = m_row["principal_id"]

            # 3a. Update membership
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

            # 3d. Check and map external_identities without principal hijacking
            ext = item.get("external_identity")
            if ext:
                issuer = ext.get("issuer", "https://accounts.google.com")
                sub = ext["sub"]
                existing_ext = id_db.execute(
                    "SELECT principal_id FROM external_identities WHERE issuer = ? AND sub = ?",
                    (issuer, sub)
                ).fetchone()
                if existing_ext:
                    if existing_ext["principal_id"] != pid:
                        raise ApiError(
                            409,
                            "external_identity_conflict",
                            f"Identity {issuer}:{sub} is already linked to principal {existing_ext['principal_id']}. Cannot reassign to {pid}."
                        )
                    id_db.execute(
                        "UPDATE external_identities SET email = ? WHERE issuer = ? AND sub = ?",
                        (ext.get("email", ""), issuer, sub)
                    )
                else:
                    ext_hash = hashlib.sha256(f"{issuer}:{sub}".encode()).hexdigest()[:24]
                    ext_id = f"ext_{ext_hash}"
                    id_db.execute(
                        "INSERT INTO external_identities (id, issuer, sub, principal_id, email, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (ext_id, issuer, sub, pid, ext.get("email", ""), time.time())
                    )

        # Fault Injection Point 2b: Crash after Identity DB updates executed, before committing
        if fault_stage == "during_identity_commit_after_updates":
            raise RuntimeError("Fault injected during identity commit after updates executed: transaction will roll back")

        # 3e. Remove from unresolved_collisions
        for cid_to_del in del_cids:
            id_db.execute(
                "DELETE FROM unresolved_collisions WHERE tenant_id = ? AND customer_id = ?",
                (tenant_id, cid_to_del)
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
            "SELECT id, tenant_id, colliding_customer_id, status, plan_json, plan_hash, error_message, created_at, updated_at "
            "FROM reconciliation_journal WHERE id = ?",
            (idempotency_key,)
        ).fetchone()
        if not row:
            return None
        return dict(row)
