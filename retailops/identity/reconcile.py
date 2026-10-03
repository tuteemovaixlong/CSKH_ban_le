"""Two-Database Account Reconciliation Coordinator with Journal, Idempotency & Failure Recovery.

Coordinates identity migration between Identity DB (principals, memberships, customer_links,
external_identities, unresolved_collisions, sessions) and Business DB (customers, orders,
conversations, proposals, business_events, agent_turns, conversation_feedback).

Guarantees:
1. Fail-closed: accounts remain in unresolved_collisions and quarantined until BOTH databases commit.
2. Two-phase Saga with Persistent Journal: records 'started' -> 'business_committed' -> 'completed'.
3. Idempotent & Resumable: bound to immutable canonical plan hash; safely resumes using saved plan.
4. Data Integrity: validates owners, rowcounts, and prevents identity hijacking.
5. Target Ownership (P1.1): every target_customer_id must be either new (no other principal's
   membership/customer_link in the tenant and no Business DB data outside this plan) or proven to
   belong to the reassigned principal; verified before any Business DB write and before the
   journal row is committed, so a rejected plan leaves no data change and no stuck journal.
6. Target Reservation & Serialization (P1.1 TOCTOU):
   - Step 1 reserves every target in unresolved_collisions inside the same Identity transaction
     as the ownership check. Every membership/customer_link writer honours the reservation
     (IdentityStore.create_membership rejects it, get_or_create_google_member never hands it out).
   - Identity writes are globally serialized (SQLite BEGIN IMMEDIATE, PostgreSQL advisory lock;
     PostgreSQL additionally takes LOCK TABLE on the ownership tables against raw writers).
     Step 2 holds that Identity write lock while it re-verifies journal, collision, reservations
     and ownership and while the Business transaction commits, so no Identity write can slip in
     between the last check and the Business commit. Step 3 re-verifies before linking.
   - If a fresh run stops before the Business commit, the journal row and the reservations are
     removed in the same Identity transaction: no data moved, collision unresolved, key reusable.
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


def _target_conflict(message: str) -> ApiError:
    return ApiError(409, "target_customer_conflict", message)


def _is_sqlite(db) -> bool:
    raw = getattr(db, 'raw', db)
    return type(raw).__module__.startswith('sqlite3')


def _lock_identity_ownership(id_db) -> None:
    """Serialize against every writer of the ownership tables for the rest of the transaction.

    SQLite: the write connection already holds BEGIN IMMEDIATE (single writer for the file).
    PostgreSQL: cooperative writers already queue on the identity advisory lock; LOCK TABLE also
    blocks raw INSERT/UPDATE/DELETE that bypass the repository.
    """
    if not _is_sqlite(id_db):
        id_db.execute(
            "LOCK TABLE memberships, customer_links, unresolved_collisions IN SHARE ROW EXCLUSIVE MODE"
        )


def _reservable_targets(reassignments: List[Dict[str, Any]], current_cid_by_mid: Dict[str, str]) -> List[str]:
    """Targets that need a reservation row. A target equal to the membership's current customer id
    (e.g. the per-principal quarantine id) is already held by the collision itself."""
    return [
        item["target_customer_id"] for item in reassignments
        if item["target_customer_id"] != current_cid_by_mid.get(item["membership_id"])
    ]


def _reserve_targets(id_db, tenant_id: str, targets: List[str], fresh_run: bool) -> None:
    """Reserve targets in unresolved_collisions (same transaction as the ownership check).

    A fresh run refuses a target that is already held (another pending reconciliation or an
    unresolved collision). A resumed run re-creates a missing reservation idempotently.
    """
    now = time.time()
    for tgt in targets:
        held = id_db.execute(
            "SELECT 1 FROM unresolved_collisions WHERE tenant_id = ? AND customer_id = ?",
            (tenant_id, tgt)
        ).fetchone()
        if held and fresh_run:
            raise _target_conflict(
                f"Target customer {tgt} is reserved by another pending reconciliation or is itself an unresolved collision."
            )
        if not held:
            id_db.execute(
                "INSERT INTO unresolved_collisions (tenant_id, customer_id, created_at) VALUES (?, ?, ?)",
                (tenant_id, tgt, now)
            )


def _release_fresh_run(id_db, tenant_id: str, idempotency_key: str, plan_hash: str, targets: List[str]) -> None:
    """Compensation for a fresh run that stopped before the Business commit: nothing moved, so
    drop the journal row and the reservations created by Step 1. The collision row stays.
    Skipped when the journal row is no longer this run's 'started' row."""
    j_row = id_db.execute(
        "SELECT status, plan_hash FROM reconciliation_journal WHERE id = ?", (idempotency_key,)
    ).fetchone()
    if not j_row or j_row["status"] != "started" or j_row["plan_hash"] != plan_hash:
        return
    id_db.execute(
        "DELETE FROM reconciliation_journal WHERE id = ? AND status = 'started'",
        (idempotency_key,)
    )
    for tgt in targets:
        id_db.execute(
            "DELETE FROM unresolved_collisions WHERE tenant_id = ? AND customer_id = ?",
            (tenant_id, tgt)
        )


def _load_plan_memberships(id_db, tenant_id: str, colliding_customer_id: str, reassignments: List[Dict[str, Any]]):
    """Re-read the plan's memberships; returns (principal_by_mid, current_cid_by_mid)."""
    principal_by_mid: Dict[str, str] = {}
    current_cid_by_mid: Dict[str, str] = {}
    for item in reassignments:
        mid = item["membership_id"]
        m_row = id_db.execute(
            "SELECT principal_id, customer_id FROM memberships WHERE id = ? AND tenant_id = ?",
            (mid, tenant_id)
        ).fetchone()
        if not m_row:
            raise ApiError(404, "membership_not_found", f"Membership {mid} not found in tenant {tenant_id}")
        principal_by_mid[mid] = m_row["principal_id"]
        current_cid_by_mid[mid] = m_row["customer_id"]
    return principal_by_mid, current_cid_by_mid


def _recheck_identity_under_lock(
    id_db,
    tenant_id: str,
    colliding_customer_id: str,
    idempotency_key: str,
    plan_hash: str,
    reassignments: List[Dict[str, Any]],
) -> set:
    """Step 2 re-verification while the Identity write lock is held. Returns proven targets."""
    j_row = id_db.execute(
        "SELECT status, plan_hash FROM reconciliation_journal WHERE id = ?", (idempotency_key,)
    ).fetchone()
    if not j_row or j_row["status"] != "started" or (j_row["plan_hash"] and j_row["plan_hash"] != plan_hash):
        raise ApiError(409, "reconciliation_state_changed",
                       f"Reconciliation journal {idempotency_key} changed before the Business commit.")
    col_row = id_db.execute(
        "SELECT 1 FROM unresolved_collisions WHERE tenant_id = ? AND customer_id = ?",
        (tenant_id, colliding_customer_id)
    ).fetchone()
    if not col_row:
        raise ApiError(409, "reconciliation_state_changed",
                       f"Collision {colliding_customer_id} is no longer unresolved in tenant {tenant_id}.")
    principal_by_mid, current_cid_by_mid = _load_plan_memberships(
        id_db, tenant_id, colliding_customer_id, reassignments
    )
    reservable = _reservable_targets(reassignments, current_cid_by_mid)
    for tgt in reservable:
        held = id_db.execute(
            "SELECT 1 FROM unresolved_collisions WHERE tenant_id = ? AND customer_id = ?",
            (tenant_id, tgt)
        ).fetchone()
        if not held:
            raise _target_conflict(f"Reservation for target customer {tgt} was lost before the Business commit.")
    return _validate_target_ownership(id_db, tenant_id, colliding_customer_id, reassignments, principal_by_mid)


def _validate_target_ownership(
    id_db,
    tenant_id: str,
    colliding_customer_id: str,
    reassignments: List[Dict[str, Any]],
    principal_by_mid: Dict[str, str],
) -> set:
    """Identity-side P1.1 guard. Returns the set of targets proven to belong to their principal.

    Rejects (409 target_customer_conflict) when a target:
    - is the ambiguous colliding id or its quarantine placeholder;
    - is assigned to more than one principal inside the same plan;
    - is referenced by a membership or customer_link of a different principal in the tenant.
    """
    forbidden = {colliding_customer_id, f"quarantine_{colliding_customer_id}"}
    target_principal: Dict[str, str] = {}
    proven = set()
    for item in reassignments:
        tgt = item["target_customer_id"]
        pid = principal_by_mid[item["membership_id"]]
        if tgt in forbidden:
            raise _target_conflict(
                f"Target customer {tgt} is the ambiguous colliding/quarantine id and cannot be a reconciliation target."
            )
        if target_principal.setdefault(tgt, pid) != pid:
            raise _target_conflict(f"Target customer {tgt} is assigned to more than one principal in the plan.")
        owners = {
            r["principal_id"] for r in id_db.execute(
                "SELECT principal_id FROM memberships WHERE tenant_id = ? AND customer_id = ?",
                (tenant_id, tgt)
            ).fetchall()
        }
        owners |= {
            r["principal_id"] for r in id_db.execute(
                "SELECT principal_id FROM customer_links WHERE tenant_id = ? AND customer_id = ?",
                (tenant_id, tgt)
            ).fetchall()
        }
        if owners - {pid}:
            raise _target_conflict(
                f"Target customer {tgt} already belongs to another principal in tenant {tenant_id}."
            )
        if pid in owners:
            proven.add(tgt)
    return proven


def _validate_business_targets(
    b_db,
    reassignments: List[Dict[str, Any]],
    proven_targets: set,
    fresh_run: bool = False,
) -> None:
    """Business-side P1.1 guard for targets without identity proof.

    An unproven target is only accepted as 'new' when it holds no Business DB data except the
    rows this very reassignment moves to it (which happens when resuming after a partial commit).
    Covers every customer-scoped table touched by the reassignment: customers (fresh run only,
    since a resumed run may already have created the row), orders, conversations, proposals,
    business_events, agent_turns and conversation_feedback.
    """
    has_proposals = _has_table(b_db, "proposals")
    has_events = _has_table(b_db, "business_events")
    has_turns = _has_table(b_db, "agent_turns")
    has_feedback = _has_table(b_db, "conversation_feedback")
    for item in reassignments:
        tgt = item["target_customer_id"]
        if tgt in proven_targets:
            continue
        own_orders = set(item.get("order_ids", []))
        own_convs = set(item.get("conversation_ids", []))
        if fresh_run and b_db.execute("SELECT 1 FROM customers WHERE id = ?", (tgt,)).fetchone():
            raise _target_conflict(
                f"Target customer {tgt} already exists in the Business DB and is not proven "
                f"to belong to the reassigned principal."
            )
        foreign = any(
            r["id"] not in own_orders
            for r in b_db.execute("SELECT id FROM orders WHERE customer_id = ?", (tgt,)).fetchall()
        ) or any(
            r["id"] not in own_convs
            for r in b_db.execute("SELECT id FROM conversations WHERE customer_id = ?", (tgt,)).fetchall()
        )
        if not foreign and has_proposals:
            foreign = any(
                r["order_id"] not in own_orders
                for r in b_db.execute("SELECT order_id FROM proposals WHERE customer_id = ?", (tgt,)).fetchall()
            )
        if not foreign and has_events:
            foreign = any(
                r["order_id"] not in own_orders
                for r in b_db.execute("SELECT order_id FROM business_events WHERE customer_id = ?", (tgt,)).fetchall()
            )
        if not foreign and has_turns:
            foreign = any(
                r["conversation_id"] not in own_convs
                for r in b_db.execute("SELECT conversation_id FROM agent_turns WHERE customer_id = ?", (tgt,)).fetchall()
            )
        if not foreign and has_feedback:
            foreign = any(
                r["conversation_id"] not in own_convs
                for r in b_db.execute(
                    "SELECT conversation_id FROM conversation_feedback WHERE customer_id = ?", (tgt,)
                ).fetchall()
            )
        if foreign:
            raise _target_conflict(
                f"Target customer {tgt} already holds business data outside this plan and is not proven "
                f"to belong to the reassigned principal."
            )


def _apply_business_reassignment(b_db, tenant_id: str, colliding_customer_id: str, reassignments: List[Dict[str, Any]]) -> None:
    """Step 2 Business DB validation and writes (customers, orders, conversations and every
    customer-scoped child table). Runs inside the caller's Business write transaction."""
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
    fresh_run = False

    with sessions.control.connection(write=True) as id_db:
        _lock_identity_ownership(id_db)
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
            fresh_run = True

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
        principal_by_mid: Dict[str, str] = {}
        current_cid_by_mid: Dict[str, str] = {}
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
            principal_by_mid[mid] = m_row["principal_id"]
            current_cid_by_mid[mid] = m_row["customer_id"]

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

        # 1e. P1.1 target ownership guard. Raised inside this transaction, so a rejected plan
        # also rolls back the journal insert above: no data change and no stuck idempotency key.
        proven_targets = _validate_target_ownership(
            id_db, tenant_id, colliding_customer_id, reassignments, principal_by_mid
        )
        # 1f. Reserve the targets in the same transaction as the ownership check, so every
        # cooperative membership/customer_link writer refuses them from now on.
        if current_status in ("started", "business_committed"):
            _reserve_targets(
                id_db, tenant_id, _reservable_targets(reassignments, current_cid_by_mid), fresh_run
            )
        if current_status == "started":
            with sessions.business_store(tenant_id).connection() as b_read:
                _validate_business_targets(b_read, reassignments, proven_targets, fresh_run=fresh_run)

    # -------------------------------------------------------------
    # Step 2: Business DB Updates (Customers, Orders, Conversations)
    # The Identity write lock is held from the final re-verification until the Business commit
    # is recorded, closing the window between the ownership check and the Business commit.
    # -------------------------------------------------------------
    if current_status == "started":
        b_store = sessions.business_store(tenant_id)
        stopped: Optional[BaseException] = None
        with sessions.control.connection(write=True) as id_db:
            _lock_identity_ownership(id_db)
            body_done = False
            try:
                proven_targets = _recheck_identity_under_lock(
                    id_db, tenant_id, colliding_customer_id, idempotency_key, current_plan_hash, reassignments
                )
                with b_store.connection(write=True) as b_db:
                    # Re-check target ownership under the Business write lock, before any write.
                    _validate_business_targets(b_db, reassignments, proven_targets, fresh_run=fresh_run)
                    _apply_business_reassignment(b_db, tenant_id, colliding_customer_id, reassignments)
                    body_done = True
            except Exception as exc:
                # body_done means the Business commit itself failed (outcome unknown); a resumed
                # run may have committed Business data earlier. Keep the journal in both cases.
                if body_done or not fresh_run:
                    raise
                _release_fresh_run(
                    id_db, tenant_id, idempotency_key, current_plan_hash,
                    _reservable_targets(reassignments, current_cid_by_mid)
                )
                stopped = exc

            if stopped is None:
                # Fault Injection Point 1a: Crash after Business commit but BEFORE journal update
                if fault_stage == "after_business_commit_before_journal":
                    raise RuntimeError("Fault injected after business commit before journal update: journal is still 'started'")

                # Update journal to 'business_committed' in Identity DB
                id_db.execute(
                    "UPDATE reconciliation_journal SET status = 'business_committed', updated_at = ? WHERE id = ?",
                    (time.time(), idempotency_key)
                )
                current_status = "business_committed"
        if stopped is not None:
            raise stopped

    # Fault Injection Point 1b: Crash after Business DB commit and journal updated
    if fault_stage == "after_business_commit":
        raise RuntimeError("Fault injected after business commit: process halted before Identity DB updates")

    # -------------------------------------------------------------
    # Step 3: Identity DB Updates (Memberships, Links, Auth, Unquarantine)
    # -------------------------------------------------------------
    with sessions.control.connection(write=True) as id_db:
        _lock_identity_ownership(id_db)
        # Pre-execution fault injection (for compatibility)
        if fault_stage == "during_identity_commit":
            raise RuntimeError("Fault injected during identity DB commit: transaction will roll back")

        # 3-pre. Final P1.1 ownership check, atomic with the membership/link updates below. A
        # conflict here leaves the journal at 'business_committed' and the collision unresolved
        # (fail-closed, resumable once the conflicting writer is removed).
        step3_principals, _ = _load_plan_memberships(id_db, tenant_id, colliding_customer_id, reassignments)
        _validate_target_ownership(id_db, tenant_id, colliding_customer_id, reassignments, step3_principals)

        # Collect all collision and temporary quarantine customer IDs to clean up from unresolved_collisions
        # (including the target reservations taken in Step 1).
        del_cids = {colliding_customer_id, f"quarantine_{colliding_customer_id}"}
        del_cids.update(item["target_customer_id"] for item in reassignments)
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
