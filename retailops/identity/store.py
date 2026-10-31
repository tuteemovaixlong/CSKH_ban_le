"""Durable principals, memberships and revocable sessions; credentials stored as hashes."""
import hashlib
import json
import logging
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path

from retailops.business.permissions import ACTIVE_BUSINESS_ROLES, LEGACY_DISABLED_ROLES, ROLE_PERMISSIONS
from retailops.core import ApiError, require
from retailops.schema import migrate

logger = logging.getLogger("retailops_identity")

IDENTITY_V5_DISABLE_REASON = 'retired_legacy_role_r1_w1'
MEMBERSHIPS_ROLE_CHECK_SQL = (
    "CHECK(role IN ('customer','staff','manager') OR (role IN ('viewer','platform_admin') AND active = 0))"
)


def initialize(db):
    statements = [
        '''CREATE TABLE IF NOT EXISTS tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL,
            storage_key TEXT UNIQUE NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)))''',
        'CREATE TABLE IF NOT EXISTS principals (id TEXT PRIMARY KEY, name TEXT NOT NULL)',
        f'''CREATE TABLE IF NOT EXISTS memberships (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
            principal_id TEXT NOT NULL REFERENCES principals(id), customer_id TEXT NOT NULL,
            role TEXT NOT NULL {MEMBERSHIPS_ROLE_CHECK_SQL}, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            auth_version INTEGER NOT NULL DEFAULT 1, disabled_reason TEXT, UNIQUE(tenant_id,principal_id))''',
        '''CREATE TABLE IF NOT EXISTS credentials (hash TEXT PRIMARY KEY, membership_id TEXT NOT NULL REFERENCES memberships(id),
            created_at REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, membership_id TEXT NOT NULL REFERENCES memberships(id),
            auth_version INTEGER NOT NULL, expires_at REAL NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS idx_sessions_membership ON sessions(membership_id)',
        'CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at)',
        'CREATE TABLE IF NOT EXISTS identity_rate (bucket TEXT PRIMARY KEY, window INTEGER NOT NULL, count INTEGER NOT NULL)',
        '''CREATE TABLE IF NOT EXISTS provider_daily_usage (day TEXT NOT NULL, provider_id TEXT NOT NULL,
            attempts INTEGER NOT NULL, PRIMARY KEY(day,provider_id))''',
        '''CREATE TABLE IF NOT EXISTS identity_events (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL,
            kind TEXT NOT NULL, tenant_id TEXT, membership_id TEXT)''',
        '''CREATE TABLE IF NOT EXISTS external_identities (id TEXT PRIMARY KEY, issuer TEXT NOT NULL,
            sub TEXT NOT NULL, principal_id TEXT NOT NULL REFERENCES principals(id), email TEXT,
            created_at REAL NOT NULL, UNIQUE(issuer, sub))''',
        '''CREATE TABLE IF NOT EXISTS customer_links (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
            principal_id TEXT NOT NULL REFERENCES principals(id), customer_id TEXT NOT NULL,
            created_at REAL NOT NULL, UNIQUE(tenant_id, principal_id), UNIQUE(tenant_id, customer_id))''',
        '''CREATE TABLE IF NOT EXISTS unresolved_collisions (tenant_id TEXT NOT NULL REFERENCES tenants(id),
            customer_id TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(tenant_id, customer_id))''',
        '''CREATE TABLE IF NOT EXISTS reconciliation_journal (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(id),
            colliding_customer_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('started', 'business_committed', 'identity_committed', 'completed')),
            plan_json TEXT NOT NULL,
            plan_hash TEXT,
            error_message TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS idx_reconciliation_journal_tenant ON reconciliation_journal(tenant_id, colliding_customer_id)',
        '''CREATE TABLE IF NOT EXISTS external_customer_mappings (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(id),
            source_system TEXT NOT NULL,
            external_customer_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE(tenant_id, source_system, external_customer_id))''',
        'CREATE INDEX IF NOT EXISTS idx_ext_cust_mappings_tenant_cust ON external_customer_mappings(tenant_id, customer_id)',
        '''CREATE TABLE IF NOT EXISTS membership_quota_overrides (
            membership_id TEXT PRIMARY KEY REFERENCES memberships(id),
            daily_limit INTEGER NOT NULL CHECK(daily_limit BETWEEN 1 AND 10000),
            effective_at REAL NOT NULL,
            expires_at REAL,
            reason TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            updated_at REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at REAL NOT NULL,
            correlation_id TEXT NOT NULL,
            actor_principal_id TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            target_membership_id TEXT NOT NULL,
            action TEXT NOT NULL,
            outcome TEXT NOT NULL CHECK(outcome IN ('allowed', 'denied')),
            before_json TEXT NOT NULL,
            after_json TEXT NOT NULL,
            reason TEXT NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS idx_admin_audit_tenant ON admin_audit_log(tenant_id, id DESC)',
        'CREATE INDEX IF NOT EXISTS idx_admin_audit_target ON admin_audit_log(target_membership_id, id DESC)',
    ]
    for statement in statements:
        db.execute(statement)


def migrate_legacy_collisions(db, tenant_stores=None):
    """Saga / idempotent multi-database recovery process across independent business and identity database boundaries.
    Atomically resolves any legacy collisions where multiple customer memberships
    in the same tenant share a customer_id, and guarantees unique customer_links.

    If ambiguous collisions exist with business data (orders/conversations):
    - Ambiguous orders/conversations are quarantined under a designated quarantine customer.
    - An identity event 'collision_quarantined_reconciliation_required' is recorded.
    - Each colliding membership receives a fresh, distinct customer_id (cust_<hash>).
    - Business customers table is updated with corresponding customer records.
    - Affected active sessions are invalidated to prevent stale identity hijacking.
    """
    db.execute('''CREATE TABLE IF NOT EXISTS external_identities (
        id TEXT PRIMARY KEY,
        issuer TEXT NOT NULL,
        sub TEXT NOT NULL,
        principal_id TEXT NOT NULL REFERENCES principals(id),
        email TEXT,
        created_at REAL NOT NULL,
        UNIQUE(issuer, sub)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS customer_links (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id),
        principal_id TEXT NOT NULL REFERENCES principals(id),
        customer_id TEXT NOT NULL,
        created_at REAL NOT NULL,
        UNIQUE(tenant_id, principal_id),
        UNIQUE(tenant_id, customer_id)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS unresolved_collisions (
        tenant_id TEXT NOT NULL REFERENCES tenants(id),
        customer_id TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY(tenant_id, customer_id)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS reconciliation_journal (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id),
        colliding_customer_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('started', 'business_committed', 'identity_committed', 'completed')),
        plan_json TEXT NOT NULL,
        plan_hash TEXT,
        error_message TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_reconciliation_journal_tenant ON reconciliation_journal(tenant_id, colliding_customer_id)')
    db.execute('''CREATE TABLE IF NOT EXISTS external_customer_mappings (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id),
        source_system TEXT NOT NULL,
        external_customer_id TEXT NOT NULL,
        customer_id TEXT NOT NULL,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        UNIQUE(tenant_id, source_system, external_customer_id)
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_ext_cust_mappings_tenant_cust ON external_customer_mappings(tenant_id, customer_id)')
    db.execute('''CREATE TABLE IF NOT EXISTS membership_quota_overrides (
        membership_id TEXT PRIMARY KEY REFERENCES memberships(id),
        daily_limit INTEGER NOT NULL CHECK(daily_limit BETWEEN 1 AND 10000),
        effective_at REAL NOT NULL,
        expires_at REAL,
        reason TEXT NOT NULL,
        updated_by TEXT NOT NULL,
        updated_at REAL NOT NULL
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS admin_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at REAL NOT NULL,
        correlation_id TEXT NOT NULL,
        actor_principal_id TEXT NOT NULL,
        actor_role TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        target_membership_id TEXT NOT NULL,
        action TEXT NOT NULL,
        outcome TEXT NOT NULL CHECK(outcome IN ('allowed', 'denied')),
        before_json TEXT NOT NULL,
        after_json TEXT NOT NULL,
        reason TEXT NOT NULL
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_admin_audit_tenant ON admin_audit_log(tenant_id, id DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_admin_audit_target ON admin_audit_log(target_membership_id, id DESC)')
    try:
        db.execute('ALTER TABLE reconciliation_journal ADD COLUMN plan_hash TEXT')
    except Exception:
        pass

    # Helper to resolve tenant business database connection
    def get_tenant_db_conn(t_id):
        if tenant_stores:
            try:
                if callable(tenant_stores):
                    store = tenant_stores(t_id)
                elif isinstance(tenant_stores, dict):
                    store = tenant_stores.get(t_id)
                else:
                    store = getattr(tenant_stores, 'business_store', lambda _: None)(t_id)
                if store:
                    return store.connection(write=True)
            except Exception:
                pass
        try:
            main_rows = [r[2] for r in db.execute("PRAGMA database_list").fetchall() if r[1] == 'main']
            if main_rows and main_rows[0]:
                p = Path(main_rows[0])
                t_row = db.execute("SELECT storage_key FROM tenants WHERE id=?", (t_id,)).fetchone()
                if t_row:
                    t_file = p.parent / 'tenants' / f"{t_row['storage_key']}.sqlite3"
                    if t_file.is_file():
                        from retailops.business.store import BusinessStore
                        return BusinessStore(t_file, create=False).connection(write=True)
        except Exception:
            pass
        return None

    collision_groups = db.execute('''
        SELECT tenant_id, customer_id, COUNT(*) as cnt
        FROM memberships
        WHERE role = 'customer'
        GROUP BY tenant_id, customer_id
        HAVING cnt > 1
    ''').fetchall()

    unresolved_collision_members = set()

    for grp in collision_groups:
        t_id, c_id = grp['tenant_id'], grp['customer_id']
        members = db.execute('''
            SELECT m.id, m.principal_id, p.name
            FROM memberships m
            JOIN principals p ON p.id=m.principal_id
            WHERE m.tenant_id=? AND m.customer_id=? AND m.role='customer'
            ORDER BY m.id
        ''', (t_id, c_id)).fetchall()

        already_unresolved = db.execute(
            "SELECT 1 FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?",
            (t_id, c_id)
        ).fetchone()
        if already_unresolved:
            for m in members:
                unresolved_collision_members.add(m['id'])
                db.execute('DELETE FROM sessions WHERE membership_id=?', (m['id'],))
            continue

        b_conn_ctx = get_tenant_db_conn(t_id)
        if not b_conn_ctx:
            # N08-A2 FAIL-CLOSED: Business DB unavailable / resolver error / mount missing.
            # Do NOT mutate memberships, do NOT assign random CIDs, do NOT log legacy_collision_migrated!
            # Invalidate all active sessions for colliding members to prevent leaked access.
            for m in members:
                unresolved_collision_members.add(m['id'])
                db.execute('DELETE FROM sessions WHERE membership_id=?', (m['id'],))
            db.execute(
                'INSERT INTO unresolved_collisions (tenant_id, customer_id, created_at) VALUES (?,?,?) '
                'ON CONFLICT(tenant_id, customer_id) DO NOTHING',
                (t_id, c_id, time.time())
            )
            db.execute('DELETE FROM customer_links WHERE tenant_id=? AND customer_id=?', (t_id, c_id))
            db.execute(
                'INSERT INTO identity_events(created_at, kind, tenant_id, membership_id) VALUES (?,?,?,?)',
                (time.time(), 'legacy_collision_unresolved_storage_unavailable', t_id, None)
            )
            continue

        with b_conn_ctx as bdb:
            quarantine_cid = f"quarantine_{c_id}"
            # Check original c_id AND quarantine_cid for orders/conversations (idempotent recovery N08-A1)
            orig_orders = bdb.execute("SELECT count(*) AS total FROM orders WHERE customer_id=?", (c_id,)).fetchone()['total']
            quarantined_orders = bdb.execute("SELECT count(*) AS total FROM orders WHERE customer_id=?", (quarantine_cid,)).fetchone()['total']
            has_orders = (orig_orders + quarantined_orders) > 0

            try:
                orig_convs = bdb.execute("SELECT count(*) AS total FROM conversations WHERE customer_id=?", (c_id,)).fetchone()['total']
                quarantined_convs = bdb.execute("SELECT count(*) AS total FROM conversations WHERE customer_id=?", (quarantine_cid,)).fetchone()['total']
                has_convs = (orig_convs + quarantined_convs) > 0
            except Exception as e:
                raise RuntimeError(f"Failed to query conversations for customer {c_id} in tenant {t_id}: {e}") from e

            is_ambiguous = (has_orders or has_convs)
            new_cids = {}

            if is_ambiguous:
                # Ambiguous collision: quarantine orders & conversations pending manual reconciliation
                bdb.execute("INSERT INTO customers (id, name) VALUES (?,?) ON CONFLICT DO NOTHING",
                            (quarantine_cid, "Quarantined Ambiguous Collision"))
                if orig_orders > 0:
                    bdb.execute("UPDATE orders SET customer_id=? WHERE customer_id=?", (quarantine_cid, c_id))
                if orig_convs > 0:
                    try:
                        bdb.execute("UPDATE conversations SET customer_id=? WHERE customer_id=?", (quarantine_cid, c_id))
                    except Exception as e:
                        raise RuntimeError(f"Failed to update conversations for customer {c_id}: {e}") from e

                for m in members:
                    pid = m['principal_id']
                    hash_key = f"{t_id}:{pid}:{c_id}".encode()
                    new_cid = f"cust_{hashlib.sha256(hash_key).hexdigest()[:32]}"
                    new_cids[m['id']] = new_cid
                    bdb.execute("INSERT INTO customers (id, name) VALUES (?,?) ON CONFLICT DO NOTHING",
                                (new_cid, m['name']))
            else:
                for secondary in members[1:]:
                    sec_pid = secondary['principal_id']
                    sec_hash_key = f"{t_id}:{sec_pid}:{c_id}".encode()
                    new_cid = f"cust_{hashlib.sha256(sec_hash_key).hexdigest()[:32]}"
                    new_cids[secondary['id']] = new_cid
                    bdb.execute("INSERT INTO customers (id, name) VALUES (?,?) ON CONFLICT DO NOTHING",
                                (new_cid, secondary['name']))

        # Business DB transaction is now committed. Execute Identity DB updates:
        if is_ambiguous:
            for m in members:
                unresolved_collision_members.add(m['id'])
                new_cid = new_cids[m['id']]
                db.execute('UPDATE memberships SET customer_id=? WHERE id=?', (new_cid, m['id']))
                db.execute('DELETE FROM sessions WHERE membership_id=?', (m['id'],))
                db.execute(
                    'INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) '
                    'VALUES (?,?,?,?,?) ON CONFLICT(tenant_id, principal_id) DO UPDATE SET customer_id=excluded.customer_id',
                    (str(uuid.uuid4()), t_id, m['principal_id'], new_cid, time.time())
                )
                db.execute(
                    'INSERT INTO unresolved_collisions (tenant_id, customer_id, created_at) VALUES (?,?,?) '
                    'ON CONFLICT(tenant_id, customer_id) DO NOTHING',
                    (t_id, new_cid, time.time())
                )

            db.execute(
                'INSERT INTO identity_events(created_at, kind, tenant_id, membership_id) VALUES (?,?,?,?)',
                (time.time(), 'collision_quarantined_reconciliation_required', t_id, None)
            )
            db.execute(
                'INSERT INTO unresolved_collisions (tenant_id, customer_id, created_at) VALUES (?,?,?) '
                'ON CONFLICT(tenant_id, customer_id) DO NOTHING',
                (t_id, c_id, time.time())
            )
        else:
            for secondary in members[1:]:
                new_cid = new_cids[secondary['id']]
                db.execute('UPDATE memberships SET customer_id=? WHERE id=?', (new_cid, secondary['id']))
                db.execute('DELETE FROM sessions WHERE membership_id=?', (secondary['id'],))
                db.execute(
                    'INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) '
                    'VALUES (?,?,?,?,?) ON CONFLICT(tenant_id, principal_id) DO UPDATE SET customer_id=excluded.customer_id',
                    (str(uuid.uuid4()), t_id, secondary['principal_id'], new_cid, time.time())
                )
                db.execute(
                    'INSERT INTO identity_events(created_at, kind, tenant_id, membership_id) VALUES (?,?,?,?)',
                    (time.time(), 'legacy_collision_migrated', t_id, secondary['id'])
                )
            # Link primary member
            db.execute(
                'INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) '
                'VALUES (?,?,?,?,?) ON CONFLICT(tenant_id, principal_id) DO UPDATE SET customer_id=excluded.customer_id',
                (str(uuid.uuid4()), t_id, members[0]['principal_id'], c_id, time.time())
            )
            db.execute('DELETE FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?', (t_id, c_id))

    unlinked = db.execute('''
        SELECT m.id, m.tenant_id, m.principal_id, m.customer_id, p.name
        FROM memberships m
        JOIN principals p ON p.id=m.principal_id
        LEFT JOIN customer_links cl ON cl.tenant_id = m.tenant_id AND cl.principal_id = m.principal_id
        WHERE m.role = 'customer' AND cl.id IS NULL
    ''').fetchall()

    for m in unlinked:
        if m['id'] in unresolved_collision_members:
            continue
        try:
            is_unres = db.execute(
                'SELECT 1 FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?',
                (m['tenant_id'], m['customer_id'])
            ).fetchone()
        except Exception:
            is_unres = None
        if is_unres:
            continue
        existing_link = db.execute(
            'SELECT 1 FROM customer_links WHERE tenant_id=? AND customer_id=?',
            (m['tenant_id'], m['customer_id'])
        ).fetchone()
        assigned_cid = m['customer_id'] if not existing_link else f"cust_{uuid.uuid4().hex}"
        if assigned_cid != m['customer_id']:
            db.execute('UPDATE memberships SET customer_id=? WHERE tenant_id=? AND principal_id=?',
                       (assigned_cid, m['tenant_id'], m['principal_id']))
        db.execute(
            'INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) VALUES (?,?,?,?,?) '
            'ON CONFLICT(tenant_id, principal_id) DO UPDATE SET customer_id=excluded.customer_id',
            (str(uuid.uuid4()), m['tenant_id'], m['principal_id'], assigned_cid, time.time())
        )
        b_conn_ctx = get_tenant_db_conn(m['tenant_id'])
        if b_conn_ctx:
            with b_conn_ctx as bdb:
                bdb.execute("INSERT INTO customers (id, name) VALUES (?,?) ON CONFLICT DO NOTHING",
                            (assigned_cid, m['name']))


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value)


def valid_name(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 100


def upgrade_sqlite_memberships_role_constraint(path, *, fail_hook=None):
    """Safely upgrade legacy SQLite identity schemas to R1 W1 identity v5.

    - Disables legacy 'viewer' and 'platform_admin' memberships (never deletes rows),
      records disabled_reason, bumps auth_version, and revokes their active sessions.
    - Enforces the v5 role CHECK constraint so only ('customer', 'staff', 'manager')
      can ever be active while disabled legacy rows preserve full FK integrity.
    - Bumps retailops_schema ('identity') version to 5 inside the same atomic transaction.

    SQLite requires PRAGMA foreign_keys=OFF to be executed outside any active transaction
    before rebuilding a referenced parent table, then verified via PRAGMA foreign_key_check
    inside the transaction before committing. Never swallows errors or leaves temporary tables behind.
    """
    db = sqlite3.connect(Path(path), timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        mem_ddl = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='memberships'").fetchone()
        has_temp = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('memberships_p5e_new', 'memberships_r1_v5_new')"
        ).fetchone()
        if not mem_ddl or not mem_ddl[0]:
            return False

        existing_cols = {r[1] for r in db.execute('PRAGMA table_info(memberships)').fetchall()}
        norm_ddl = ' '.join(mem_ddl[0].split()).replace(', ', ',')
        has_v5_check = (
            "role IN ('viewer','platform_admin') AND active = 0" in norm_ddl
            and 'disabled_reason' in existing_cols
        )
        if 'disabled_reason' in existing_cols:
            has_active_legacy = bool(
                db.execute(
                    "SELECT 1 FROM memberships WHERE role IN ('viewer', 'platform_admin') "
                    "AND (active <> 0 OR disabled_reason IS NULL) LIMIT 1"
                ).fetchone()
            )
        else:
            has_active_legacy = bool(
                db.execute(
                    "SELECT 1 FROM memberships WHERE role IN ('viewer', 'platform_admin') LIMIT 1"
                ).fetchone()
            )

        has_schema_tbl = bool(
            db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='retailops_schema'").fetchone()
        )
        schema_row = (
            db.execute("SELECT version FROM retailops_schema WHERE component='identity'").fetchone()
            if has_schema_tbl
            else None
        )
        needs_version_bump = bool(schema_row is not None and int(schema_row[0]) < 5)
        needs_rebuild = bool(not has_v5_check or has_active_legacy)

        if not needs_rebuild and not has_temp and not needs_version_bump:
            return False

        db.execute('PRAGMA foreign_keys=OFF')
        fk_state = db.execute('PRAGMA foreign_keys').fetchone()
        if fk_state and fk_state[0] != 0:
            raise sqlite3.OperationalError('Unable to disable SQLite foreign_keys outside transaction for schema rebuild.')
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('DROP TABLE IF EXISTS memberships_p5e_new')
            db.execute('DROP TABLE IF EXISTS memberships_r1_v5_new')
            if needs_rebuild:
                auth_ver_expr = 'COALESCE(auth_version, 1)' if 'auth_version' in existing_cols else '1'
                dis_reason_expr = 'disabled_reason' if 'disabled_reason' in existing_cols else 'NULL'
                has_sessions = bool(
                    db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'").fetchone()
                )
                has_events = bool(
                    db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='identity_events'").fetchone()
                )
                legacy_to_disable = db.execute(
                    f"SELECT id, tenant_id FROM memberships "
                    f"WHERE role IN ('viewer', 'platform_admin') "
                    f"AND (active <> 0 OR {dis_reason_expr} IS NULL)"
                ).fetchall()
                if has_sessions:
                    db.execute(
                        "DELETE FROM sessions WHERE membership_id IN ("
                        "SELECT id FROM memberships WHERE role IN ('viewer', 'platform_admin'))"
                    )
                if has_events and legacy_to_disable:
                    now_ts = time.time()
                    for lr in legacy_to_disable:
                        db.execute(
                            'INSERT INTO identity_events(created_at, kind, tenant_id, membership_id) VALUES (?,?,?,?)',
                            (now_ts, 'legacy_role_disabled', lr['tenant_id'], lr['id']),
                        )
                db.execute(f'''CREATE TABLE memberships_r1_v5_new (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
                    principal_id TEXT NOT NULL REFERENCES principals(id), customer_id TEXT NOT NULL,
                    role TEXT NOT NULL {MEMBERSHIPS_ROLE_CHECK_SQL},
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
                    auth_version INTEGER NOT NULL DEFAULT 1,
                    disabled_reason TEXT,
                    UNIQUE(tenant_id,principal_id))''')
                db.execute(
                    f'''INSERT INTO memberships_r1_v5_new
                        (id, tenant_id, principal_id, customer_id, role, active, auth_version, disabled_reason)
                        SELECT
                            id,
                            tenant_id,
                            principal_id,
                            customer_id,
                            role,
                            CASE WHEN role IN ('viewer', 'platform_admin') THEN 0 ELSE active END,
                            CASE
                                WHEN role IN ('viewer', 'platform_admin') AND (active <> 0 OR {dis_reason_expr} IS NULL)
                                THEN ({auth_ver_expr}) + 1
                                ELSE {auth_ver_expr}
                            END,
                            CASE
                                WHEN role IN ('viewer', 'platform_admin')
                                THEN COALESCE({dis_reason_expr}, '{IDENTITY_V5_DISABLE_REASON}')
                                ELSE {dis_reason_expr}
                            END
                        FROM memberships''',
                )
                if callable(fail_hook):
                    fail_hook(db)
                db.execute('DROP TABLE memberships')
                db.execute('ALTER TABLE memberships_r1_v5_new RENAME TO memberships')
            if has_schema_tbl:
                db.execute("UPDATE retailops_schema SET version=5 WHERE component='identity' AND version < 5")
            fk_violations = db.execute('PRAGMA foreign_key_check').fetchall()
            if fk_violations:
                raise sqlite3.IntegrityError(
                    f"Foreign key integrity check failed after memberships migration: {[tuple(r) for r in fk_violations]}"
                )
            db.execute('COMMIT')
            return bool(needs_rebuild or needs_version_bump)
        except Exception:
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise
    finally:
        try:
            db.execute('PRAGMA foreign_keys=ON')
        finally:
            db.close()


def _inspect_sqlite_identity_ready(path):
    """Read-only inspection of an identity SQLite file without modifying a single byte.

    Returns 'empty' for a missing, zero-byte, or zero-table file; 'v5_ready' when already at
    identity schema v5 with the retired-role CHECK constraint and disabled_reason column;
    raises ValueError for wrong component / unsupported future version; and raises
    ApiError(503, 'identity_migration_required', ...) when an existing pre-v5 identity DB is found.
    """
    db_path = Path(path)
    if not db_path.exists() or db_path.stat().st_size == 0:
        return 'empty'
    uri = db_path.resolve().as_uri() + '?mode=ro'
    ro_db = None
    try:
        ro_db = sqlite3.connect(uri, uri=True, timeout=5)
        ro_db.row_factory = sqlite3.Row
        tables = {
            r[0]
            for r in ro_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        if not tables:
            return 'empty'
        if 'retailops_schema' in tables:
            rows = ro_db.execute('SELECT component, version FROM retailops_schema').fetchall()
            if rows and (len(rows) != 1 or rows[0]['component'] != 'identity'):
                raise ValueError('Database belongs to another RetailOps component.')
            if not rows:
                raise ApiError(
                    503,
                    'identity_migration_required',
                    'Kho dữ liệu identity thiếu dấu vết schema v5; khởi động bị chặn fail-closed. '
                    'Hãy chạy lệnh operator identity migrate-v5 với --confirm-preflight --confirm-backup.',
                )
            ver = rows[0]['version']
            if ver not in range(1, 6):
                raise ValueError('Unsupported database schema version; use the matching application version.')
            if ver < 5:
                raise ApiError(
                    503,
                    'identity_migration_required',
                    f'Kho dữ liệu identity đang ở schema v{ver}; khởi động bị chặn fail-closed. '
                    'Hãy chạy lệnh operator identity migrate-v5 với --confirm-preflight --confirm-backup.',
                )
            if 'memberships' not in tables:
                raise ApiError(
                    503,
                    'identity_migration_required',
                    'Kho dữ liệu identity chưa đầy đủ bảng memberships v5; khởi động bị chặn fail-closed.',
                )
            mem_ddl = ro_db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='memberships'").fetchone()
            cols = {r[1] for r in ro_db.execute('PRAGMA table_info(memberships)').fetchall()}
            norm_ddl = ' '.join((mem_ddl[0] if mem_ddl and mem_ddl[0] else '').split()).replace(', ', ',')
            has_v5_check = (
                "role IN ('viewer','platform_admin') AND active = 0" in norm_ddl
                and 'disabled_reason' in cols
            )
            if not has_v5_check:
                raise ApiError(
                    503,
                    'identity_migration_required',
                    'Bảng memberships chưa có ràng buộc schema v5; khởi động bị chặn fail-closed. '
                    'Hãy chạy lệnh operator identity migrate-v5 với --confirm-preflight --confirm-backup.',
                )
            has_active_legacy = bool(
                ro_db.execute(
                    "SELECT 1 FROM memberships WHERE role IN ('viewer', 'platform_admin') "
                    "AND (active <> 0 OR disabled_reason IS NULL) LIMIT 1"
                ).fetchone()
            )
            if has_active_legacy:
                raise ApiError(
                    503,
                    'identity_migration_required',
                    'Kho dữ liệu identity còn tài khoản legacy chưa retire sang v5; khởi động bị chặn fail-closed.',
                )
            return 'v5_ready'
        if 'memberships' in tables:
            raise ApiError(
                503,
                'identity_migration_required',
                'Kho dữ liệu identity legacy chưa nâng cấp lên schema v5; khởi động bị chặn fail-closed. '
                'Hãy chạy lệnh operator identity migrate-v5 với --confirm-preflight --confirm-backup.',
            )
        raise ValueError('Database belongs to another RetailOps component.')
    except sqlite3.Error as exc:
        raise ApiError(
            503,
            'database_unavailable',
            'Cơ sở dữ liệu tạm thời gián đoạn. Vui lòng thử lại sau ít phút.',
        ) from exc
    finally:
        if ro_db is not None:
            ro_db.close()


def migrate_sqlite_identity_v5(
    path,
    *,
    preflight_confirmed=False,
    backup_confirmed=False,
    tenant_stores=None,
    fail_hook=None,
):
    """Explicit operator migration command for SQLite identity v5 (§11.5).

    Never invoked automatically at web startup, store construction, or ordinary CLI commands.
    """
    require(
        preflight_confirmed is True and backup_confirmed is True,
        400,
        'migration_confirmation_required',
        'Lệnh nâng cấp identity v5 yêu cầu xác nhận tường minh --confirm-preflight và --confirm-backup theo runbook §11.5.',
    )
    db_path = Path(path)
    require(
        db_path.is_file() and db_path.stat().st_size > 0,
        404,
        'database_not_found',
        'Không tìm thấy kho dữ liệu identity hiện hữu để nâng cấp.',
    )
    uri = db_path.resolve().as_uri() + '?mode=ro'
    ro_db = sqlite3.connect(uri, uri=True, timeout=5)
    ro_db.row_factory = sqlite3.Row
    try:
        tables = {
            r[0]
            for r in ro_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        if 'retailops_schema' in tables:
            rows = ro_db.execute('SELECT component, version FROM retailops_schema').fetchall()
            if rows and (len(rows) != 1 or rows[0]['component'] != 'identity'):
                raise ValueError('Database belongs to another RetailOps component.')
            if rows and rows[0]['version'] not in range(1, 6):
                raise ValueError('Unsupported database schema version; use the matching application version.')
        elif 'memberships' not in tables:
            raise ValueError('Database belongs to another RetailOps component.')
    finally:
        ro_db.close()

    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('BEGIN IMMEDIATE')
        migrate(conn, 'identity', initialize)
        initialize(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    upgraded = upgrade_sqlite_memberships_role_constraint(db_path, fail_hook=fail_hook)

    conn2 = sqlite3.connect(db_path, timeout=5)
    conn2.row_factory = sqlite3.Row
    try:
        conn2.execute('PRAGMA foreign_keys=ON')
        conn2.execute('BEGIN IMMEDIATE')
        migrate_legacy_collisions(conn2, tenant_stores=tenant_stores)
        conn2.commit()
    except Exception:
        conn2.rollback()
        raise
    finally:
        conn2.close()

    return {
        'result': 'IDENTITY_V5_MIGRATED',
        'backend': 'sqlite',
        'schema_version': 5,
        'upgraded': bool(upgraded),
    }


class IdentityStore:
    def __init__(self, path, tenant_stores=None, data_mode=None, *, initialize_db=True, read_only=False):
        if initialize_db and read_only:
            raise ValueError('Read-only identity stores cannot initialize or migrate a database.')
        self.path = Path(path)
        self.initialize = bool(initialize_db)
        self.read_only = bool(read_only)
        self.tenant_stores = tenant_stores
        self.data_mode = data_mode
        if self.initialize:
            state = _inspect_sqlite_identity_ready(self.path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connection() as db:
                db.execute('PRAGMA journal_mode=WAL')
            if state == 'empty':
                with self.connection(write=True) as db:
                    migrate(db, 'identity', initialize)
            else:
                with self.connection(write=True) as db:
                    migrate_legacy_collisions(db, tenant_stores=tenant_stores)
        else:
            if not self.path.is_file():
                raise ApiError(503, 'database_unavailable', 'Kho dữ liệu identity chưa tồn tại; không tự khởi tạo khi chạy purge.')
            if not self.read_only:
                state = _inspect_sqlite_identity_ready(self.path)
                if state == 'empty':
                    raise ApiError(503, 'database_unavailable', 'Kho dữ liệu identity đang rỗng; chưa được khởi tạo schema v5.')
            else:
                try:
                    header = self.path.read_bytes()[:16]
                except OSError:
                    header = b''
                if header == b'SQLite format 3\x00':
                    state = _inspect_sqlite_identity_ready(self.path)
                    if state == 'empty':
                        raise ApiError(503, 'database_unavailable', 'Kho dữ liệu identity đang rỗng; chưa được khởi tạo schema v5.')

    def upgrade_memberships_role_constraint(self, *, fail_hook=None):
        hook = fail_hook if fail_hook is not None else getattr(self, '_migration_fail_hook', None)
        return upgrade_sqlite_memberships_role_constraint(self.path, fail_hook=hook)

    def migrate_legacy_collisions(self, tenant_stores=None):
        stores = tenant_stores if tenant_stores is not None else self.tenant_stores
        with self.connection(write=True) as db:
            migrate_legacy_collisions(db, tenant_stores=stores)

    @contextmanager
    def connection(self, write=False):
        if self.read_only and write:
            raise ApiError(409, 'read_only_store', 'Kho identity đang ở chế độ chỉ đọc.')
        db = None
        try:
            if self.read_only:
                uri = self.path.resolve().as_uri() + '?mode=ro'
                db = sqlite3.connect(uri, uri=True, timeout=5)
            else:
                db = sqlite3.connect(self.path, timeout=5)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except (sqlite3.IntegrityError, sqlite3.ProgrammingError):
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass
            raise
        except sqlite3.Error as exc:
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass
            if self.read_only and 'readonly' in str(exc).lower():
                raise ApiError(409, 'read_only_store', 'Kho identity đang ở chế độ chỉ đọc.') from exc
            raise ApiError(503, 'database_unavailable', 'Cơ sở dữ liệu tạm thời gián đoạn. Vui lòng thử lại sau ít phút.') from exc
        except Exception:
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass
            raise
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def event(db, kind, tenant=None, membership=None):
        db.execute('INSERT INTO identity_events(created_at,kind,tenant_id,membership_id) VALUES (?,?,?,?)',
                   (time.time(), kind, tenant, membership))

    def ensure_tenant(self, tenant_id, name):
        require(valid_id(tenant_id) and valid_name(name), 400, 'invalid_tenant', 'Thông tin cửa hàng không hợp lệ.')
        with self.connection(write=True) as db:
            row = db.execute('SELECT * FROM tenants WHERE id=?', (tenant_id,)).fetchone()
            if row:
                require(row['name'] == name, 409, 'tenant_conflict', 'Mã cửa hàng đã dùng với tên khác.')
            else:
                db.execute('INSERT INTO tenants(id,name,storage_key) VALUES (?,?,?)', (tenant_id, name, uuid.uuid4().hex))
                self.event(db, 'tenant_created', tenant_id)
        return self.tenant(tenant_id)

    def tenant(self, tenant_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM tenants WHERE id=?', (tenant_id,)).fetchone()
        require(row is not None and row['active'], 404, 'tenant_not_found', 'Không tìm thấy cửa hàng đang hoạt động.')
        return dict(row)

    def create_membership(self, tenant_id, principal_id, name, customer_id, role):
        require(valid_id(principal_id) and valid_name(name) and valid_id(customer_id) and role in ACTIVE_BUSINESS_ROLES,
                400, 'invalid_membership', 'Thông tin tài khoản hoặc quyền không hợp lệ.')
        self.tenant(tenant_id)
        with self.connection(write=True) as db:
            person = db.execute('SELECT name FROM principals WHERE id=?', (principal_id,)).fetchone()
            require(person is None or person['name'] == name, 409, 'principal_conflict', 'Mã người dùng đã thuộc tên khác.')
            require(db.execute('SELECT 1 FROM memberships WHERE tenant_id=? AND principal_id=?',
                               (tenant_id, principal_id)).fetchone() is None,
                    409, 'membership_exists', 'Tài khoản đã thuộc cửa hàng này.')
            db.execute('INSERT INTO principals VALUES (?,?) ON CONFLICT DO NOTHING', (principal_id, name))
            # P1.1 reservation: a customer id held in unresolved_collisions (ambiguous collision or a
            # target reserved by a pending reconciliation) cannot be handed to another membership.
            require(db.execute('SELECT 1 FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?',
                               (tenant_id, customer_id)).fetchone() is None,
                    409, 'customer_reserved', 'Mã khách hàng đang bị khóa chờ đối soát; không thể gán cho tài khoản khác.')
            if role == 'customer':
                existing_link = db.execute(
                    'SELECT principal_id FROM customer_links WHERE tenant_id=? AND customer_id=?',
                    (tenant_id, customer_id)
                ).fetchone()
                require(existing_link is None or existing_link['principal_id'] == principal_id,
                        409, 'customer_link_conflict', 'Mã khách hàng đã được gán cho tài khoản khác trong cửa hàng này.')
                db.execute(
                    'INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) '
                    'VALUES (?,?,?,?,?) ON CONFLICT(tenant_id, principal_id) DO UPDATE SET customer_id=excluded.customer_id',
                    (str(uuid.uuid4()), tenant_id, principal_id, customer_id, time.time())
                )
            mid = str(uuid.uuid4())
            db.execute('INSERT INTO memberships(id,tenant_id,principal_id,customer_id,role) VALUES (?,?,?,?,?)',
                       (mid, tenant_id, principal_id, customer_id, role))
            self.event(db, 'membership_created', tenant_id, mid)
        return mid

    def membership(self, membership_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM memberships WHERE id=?', (membership_id,)).fetchone()
        require(row is not None, 404, 'membership_not_found', 'Không tìm thấy tài khoản.')
        return dict(row)

    def register_credential(self, membership_id, token):
        require(isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', token),
                400, 'invalid_credential', 'Credential phải do bộ sinh mã ngẫu nhiên của quản trị tạo.')
        with self.connection(write=True) as db:
            row = db.execute('SELECT * FROM memberships WHERE id=? AND active=1', (membership_id,)).fetchone()
            require(row is not None, 404, 'membership_not_found', 'Không tìm thấy tài khoản đang hoạt động.')
            db.execute('DELETE FROM credentials WHERE membership_id=?', (membership_id,))
            db.execute('INSERT INTO credentials VALUES (?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), membership_id, time.time()))
            db.execute('UPDATE memberships SET auth_version=auth_version+1 WHERE id=?', (membership_id,))
            db.execute('DELETE FROM sessions WHERE membership_id=?', (membership_id,))
            self.event(db, 'credential_rotated', row['tenant_id'], membership_id)

    def set_role(self, membership_id, role):
        require(role in ACTIVE_BUSINESS_ROLES, 400, 'invalid_role', 'Quyền không hợp lệ.')
        with self.connection(write=True) as db:
            row = db.execute('SELECT * FROM memberships WHERE id=?', (membership_id,)).fetchone()
            require(row is not None, 404, 'membership_not_found', 'Không tìm thấy tài khoản.')
            prev_role = row['role']
            prev_disabled = row['disabled_reason'] if 'disabled_reason' in row.keys() else None
            require(
                prev_role in ACTIVE_BUSINESS_ROLES and prev_disabled != IDENTITY_V5_DISABLE_REASON,
                409,
                'legacy_role_retired',
                'Tài khoản thuộc vai trò cũ đã ngưng hỗ trợ; không được đổi vai trò hoặc khôi phục từ tài khoản đã retire.',
            )
            prev_auth_ver = int(row['auth_version'])
            new_auth_ver = prev_auth_ver + 1
            db.execute(
                'UPDATE memberships SET role=?, auth_version=? WHERE id=?',
                (role, new_auth_ver, membership_id),
            )
            db.execute('DELETE FROM sessions WHERE membership_id=?', (membership_id,))
            self.event(db, 'role_changed', row['tenant_id'], membership_id)
            self.record_admin_audit(
                db,
                actor_principal_id='operator_cli',
                actor_role='operator',
                tenant_id=row['tenant_id'],
                target_membership_id=membership_id,
                action='set_role',
                outcome='allowed',
                before_state={
                    'role': prev_role,
                    'active': bool(row['active']),
                    'auth_version': prev_auth_ver,
                    'disabled_reason': prev_disabled,
                },
                after_state={
                    'role': role,
                    'active': bool(row['active']),
                    'auth_version': new_auth_ver,
                    'disabled_reason': prev_disabled,
                },
                reason='operator_set_role',
            )

    def revoke(self, membership_id):
        with self.connection(write=True) as db:
            row = db.execute('SELECT tenant_id FROM memberships WHERE id=?', (membership_id,)).fetchone()
            require(row is not None, 404, 'membership_not_found', 'Không tìm thấy tài khoản.')
            db.execute(
                "UPDATE memberships SET active=0, auth_version=auth_version+1, disabled_reason='operator_revoked' WHERE id=?",
                (membership_id,),
            )
            db.execute('DELETE FROM credentials WHERE membership_id=?', (membership_id,))
            db.execute('DELETE FROM sessions WHERE membership_id=?', (membership_id,))
            self.event(db, 'membership_revoked', row['tenant_id'], membership_id)

    def rate(self, bucket, limit):
        window = int(time.time()) // 60
        with self.connection(write=True) as db:
            row = db.execute('SELECT "window",count FROM identity_rate WHERE bucket=?', (bucket,)).fetchone()
            require(row is None or row['window'] != window or row['count'] < limit,
                    429, 'rate_limited', 'Có quá nhiều yêu cầu. Vui lòng thử lại sau một phút.')
            db.execute('''INSERT INTO identity_rate VALUES (?,?,1) ON CONFLICT(bucket) DO UPDATE SET
                count=CASE WHEN identity_rate."window"=excluded."window" THEN identity_rate.count+1 ELSE 1 END,
                "window"=excluded."window"''', (bucket, window))

    def login(self, token, lifetime, capacity):
        self.rate('login', 15)  # Commit bad-login attempts separately from failed authentication.
        require(isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', token),
                401, 'unauthorized', 'Mã truy cập cá nhân chưa đúng hoặc đã bị thu hồi.')
        with self.connection(write=True) as db:
            row = db.execute('''SELECT m.* FROM credentials c JOIN memberships m ON c.membership_id=m.id
                JOIN tenants t ON t.id=m.tenant_id
                WHERE c.hash=? AND m.active=1 AND t.active=1 AND m.role IN ('customer', 'staff', 'manager')''',
                (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            require(row is not None, 401, 'unauthorized', 'Mã truy cập cá nhân chưa đúng hoặc đã bị thu hồi.')
            if row['role'] == 'customer':
                col_cnt = db.execute(
                    "SELECT count(*) as total FROM memberships WHERE tenant_id=? AND customer_id=? AND role='customer'",
                    (row['tenant_id'], row['customer_id'])
                ).fetchone()['total']
                try:
                    unres = db.execute(
                        "SELECT 1 FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?",
                        (row['tenant_id'], row['customer_id'])
                    ).fetchone()
                except Exception:
                    unres = None
                if col_cnt > 1 or unres:
                    require(False, 503, 'collision_unresolved', 'Tài khoản đang chờ xử lý va chạm dữ liệu.')
            db.execute('DELETE FROM sessions WHERE expires_at<=?', (time.time(),))
            require(db.execute('SELECT count(*) AS total FROM sessions').fetchone()['total'] < capacity,
                    429, 'session_capacity', 'Hệ thống đã đủ phiên đăng nhập. Vui lòng thử lại sau.')
            secret = secrets.token_urlsafe(32)
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (hashlib.sha256(secret.encode()).hexdigest(),
                       row['id'], row['auth_version'], time.time()+lifetime))
            self.event(db, 'login', row['tenant_id'], row['id'])
        return secret

    def create_session_for_membership(self, membership_id, lifetime, capacity):
        with self.connection(write=True) as db:
            row = db.execute('''SELECT m.* FROM memberships m
                JOIN tenants t ON t.id=m.tenant_id
                WHERE m.id=? AND m.active=1 AND t.active=1 AND m.role IN ('customer', 'staff', 'manager')''',
                (membership_id,)).fetchone()
            require(row is not None, 401, 'unauthorized', 'Tài khoản chưa được kích hoạt hoặc không tồn tại.')
            if row['role'] == 'customer':
                col_cnt = db.execute(
                    "SELECT count(*) as total FROM memberships WHERE tenant_id=? AND customer_id=? AND role='customer'",
                    (row['tenant_id'], row['customer_id'])
                ).fetchone()['total']
                try:
                    unres = db.execute(
                        "SELECT 1 FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?",
                        (row['tenant_id'], row['customer_id'])
                    ).fetchone()
                except Exception:
                    unres = None
                if col_cnt > 1 or unres:
                    require(False, 503, 'collision_unresolved', 'Tài khoản đang chờ xử lý va chạm dữ liệu.')
            db.execute('DELETE FROM sessions WHERE expires_at<=?', (time.time(),))
            require(db.execute('SELECT count(*) AS total FROM sessions').fetchone()['total'] < capacity,
                    429, 'session_capacity', 'Hệ thống đã đủ phiên đăng nhập. Vui lòng thử lại sau.')
            secret = secrets.token_urlsafe(32)
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (hashlib.sha256(secret.encode()).hexdigest(),
                       row['id'], row['auth_version'], time.time()+lifetime))
            self.event(db, 'login', row['tenant_id'], row['id'])
        return secret

    def get_or_create_google_member(self, tenant_id, email, name, role='customer', customer_id=None, sub=None, issuer='https://accounts.google.com', email_verified=False, live=False):
        email_clean = email.strip().lower()
        require(role in ACTIVE_BUSINESS_ROLES, 400, 'invalid_role', 'Quyền không hợp lệ.')
        name_clean = name.strip() if (name and isinstance(name, str) and name.strip()) else email_clean.split('@')[0]
        sub_clean = str(sub).strip() if (sub and str(sub).strip()) else None
        issuer_clean = str(issuer).strip() if (issuer and str(issuer).strip()) else 'https://accounts.google.com'

        is_live = live or getattr(self, 'data_mode', None) in ('production', 'live')
        if is_live and not sub_clean:
            require(False, 400, 'missing_sub', 'Live Google authentication requires a verified sub.')

        self.tenant(tenant_id)
        with self.connection(write=True) as db:
            principal_id = None
            # 1. External identity check: UNIQUE(issuer, sub)
            if sub_clean:
                ext = db.execute('SELECT * FROM external_identities WHERE issuer=? AND sub=?',
                                 (issuer_clean, sub_clean)).fetchone()
                if ext:
                    principal_id = ext['principal_id']
                    existing_check = db.execute(
                        'SELECT role, active FROM memberships WHERE tenant_id=? AND principal_id=?',
                        (tenant_id, principal_id),
                    ).fetchone()
                    if existing_check is not None:
                        require(
                            existing_check['role'] in ACTIVE_BUSINESS_ROLES,
                            403,
                            'legacy_role_disabled',
                            'Vai trò tài khoản cũ đã ngưng hỗ trợ; vui lòng liên hệ quản trị viên.',
                        )
                        require(
                            bool(existing_check['active']),
                            403,
                            'account_disabled',
                            'Tài khoản đang bị tạm ngưng hoạt động.',
                        )
                    db.execute('UPDATE principals SET name=? WHERE id=?', (name_clean, principal_id))
                    if email_verified and ext['email'] != email_clean:
                        db.execute('UPDATE external_identities SET email=? WHERE issuer=? AND sub=?',
                                   (email_clean, issuer_clean, sub_clean))

            # 2. If not found by (issuer, sub), check if this is a returning legacy principal (ONLY IF email_verified is True!)
            if not principal_id:
                if email_verified and sub_clean:
                    prefix = re.sub(r'[^a-zA-Z0-9_-]', '_', email_clean.split('@')[0])[:25]
                    hash_suffix = hashlib.sha256(email_clean.encode()).hexdigest()[:10]
                    legacy_pid = f"g_{prefix}_{hash_suffix}"
                    legacy_p = db.execute('SELECT id, name FROM principals WHERE id=?', (legacy_pid,)).fetchone()
                    if not legacy_p:
                        legacy_p = db.execute('SELECT id, name FROM principals WHERE id=?', (email_clean,)).fetchone()

                    if legacy_p:
                        # Check if legacy principal is already bound to a different sub
                        already_bound = db.execute(
                            'SELECT sub FROM external_identities WHERE issuer=? AND principal_id=?',
                            (issuer_clean, legacy_p['id'])
                        ).fetchone()
                        if already_bound and already_bound['sub'] != sub_clean:
                            # Bound to another sub! Do not merge identities
                            principal_id = None
                        else:
                            active_mem = db.execute(
                                '''SELECT m.id FROM memberships m
                                   JOIN tenants t ON t.id = m.tenant_id
                                   WHERE m.principal_id=? AND m.tenant_id=? AND m.active=1 AND t.active=1
                                     AND m.role IN ('customer', 'staff', 'manager')''',
                                (legacy_p['id'], tenant_id)
                            ).fetchone()
                            require(active_mem is not None, 503, 'ambiguous_tenant',
                                    'Tài khoản đã tồn tại không có cửa hàng đang hoạt động hợp lệ; không tự động chuyển sang cửa hàng khác.')
                            principal_id = legacy_p['id']
                            db.execute(
                                'INSERT INTO external_identities (id, issuer, sub, principal_id, email, created_at) '
                                'VALUES (?,?,?,?,?,?) ON CONFLICT(issuer, sub) DO UPDATE SET principal_id=excluded.principal_id',
                                (str(uuid.uuid4()), issuer_clean, sub_clean, principal_id, email_clean, time.time())
                            )
                            self.event(db, 'external_identity_linked', tenant_id, None)

                if not principal_id:
                    if role != 'customer':
                        require(
                            bool(email_verified),
                            403,
                            'unverified_privileged_role',
                            'Email chưa xác minh không được cấp quyền đặc quyền.',
                        )
                    principal_id = f"prin_{uuid.uuid4().hex}"
                    db.execute('INSERT INTO principals (id, name) VALUES (?,?)', (principal_id, name_clean))
                    effective_sub = sub_clean or f"demo_{uuid.uuid4().hex}"
                    db.execute(
                        'INSERT INTO external_identities (id, issuer, sub, principal_id, email, created_at) '
                        'VALUES (?,?,?,?,?,?) ON CONFLICT(issuer, sub) DO NOTHING',
                        (str(uuid.uuid4()), issuer_clean, effective_sub, principal_id, email_clean if email_verified else None, time.time())
                    )
                    self.event(db, 'external_identity_created', tenant_id, None)

            existing = db.execute('SELECT * FROM memberships WHERE tenant_id=? AND principal_id=?',
                                  (tenant_id, principal_id)).fetchone()
            if existing:
                require(
                    existing['role'] in ACTIVE_BUSINESS_ROLES,
                    403,
                    'legacy_role_disabled',
                    'Vai trò tài khoản cũ đã ngưng hỗ trợ; vui lòng liên hệ quản trị viên.',
                )
                require(
                    bool(existing['active']),
                    403,
                    'account_disabled',
                    'Tài khoản đang bị tạm ngưng hoạt động.',
                )
                mid = existing['id']
                cid = existing['customer_id']
                if existing['role'] == 'customer':
                    col_cnt = db.execute(
                        "SELECT count(*) as total FROM memberships WHERE tenant_id=? AND customer_id=? AND role='customer'",
                        (tenant_id, cid)
                    ).fetchone()['total']
                    try:
                        unres = db.execute(
                            "SELECT 1 FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?",
                            (tenant_id, cid)
                        ).fetchone()
                    except Exception:
                        unres = None
                    if col_cnt > 1 or unres:
                        require(False, 503, 'collision_unresolved', 'Tài khoản đang chờ xử lý va chạm dữ liệu.')

                # Phase R1 W1: Google login never silently overwrites an existing membership's role.
                if existing['role'] != role:
                    self.event(db, 'google_role_sync_ignored', tenant_id, mid)
                db.execute(
                    'INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) '
                    'VALUES (?,?,?,?,?) ON CONFLICT(tenant_id, principal_id) DO UPDATE SET customer_id=excluded.customer_id',
                    (str(uuid.uuid4()), tenant_id, principal_id, cid, time.time())
                )
                return mid, cid

            if role != 'customer':
                require(
                    bool(email_verified),
                    403,
                    'unverified_privileged_role',
                    'Email chưa xác minh không được cấp quyền đặc quyền.',
                )

            # 3. Customer linkage: UNIQUE(tenant_id, customer_id) and UNIQUE(tenant_id, principal_id)
            cust_link = db.execute('SELECT * FROM customer_links WHERE tenant_id=? AND principal_id=?',
                                   (tenant_id, principal_id)).fetchone()
            if cust_link:
                cid = cust_link['customer_id']
                # P1.1 reservation: never materialise a membership on a reserved customer id.
                if db.execute('SELECT 1 FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?',
                              (tenant_id, cid)).fetchone():
                    require(False, 503, 'collision_unresolved', 'Tài khoản đang chờ xử lý va chạm dữ liệu.')
            else:
                cid = customer_id or f"cust_{uuid.uuid4().hex}"
                existing_cust = db.execute(
                    'SELECT principal_id FROM customer_links WHERE tenant_id=? AND customer_id=?',
                    (tenant_id, cid)
                ).fetchone()
                existing_mem = db.execute(
                    "SELECT 1 FROM memberships WHERE tenant_id=? AND customer_id=? AND role='customer'",
                    (tenant_id, cid)
                ).fetchone()
                try:
                    unres = db.execute(
                        "SELECT 1 FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?",
                        (tenant_id, cid)
                    ).fetchone()
                except Exception:
                    unres = None
                if (existing_cust and existing_cust['principal_id'] != principal_id) or existing_mem or unres:
                    cid = f"cust_{uuid.uuid4().hex}"
                db.execute(
                    'INSERT INTO customer_links (id, tenant_id, principal_id, customer_id, created_at) VALUES (?,?,?,?,?) '
                    'ON CONFLICT(tenant_id, principal_id) DO UPDATE SET customer_id=excluded.customer_id',
                    (str(uuid.uuid4()), tenant_id, principal_id, cid, time.time())
                )

            mid = str(uuid.uuid4())
            db.execute('INSERT INTO memberships(id,tenant_id,principal_id,customer_id,role) VALUES (?,?,?,?,?)',
                       (mid, tenant_id, principal_id, cid, role))
            self.event(db, 'membership_created', tenant_id, mid)
            return mid, cid

    def resolve(self, sid):
        with self.connection() as db:
            row = db.execute('''SELECT m.*,t.storage_key,p.name FROM sessions s
                JOIN memberships m ON m.id=s.membership_id JOIN tenants t ON t.id=m.tenant_id
                JOIN principals p ON p.id=m.principal_id
                WHERE s.id=? AND s.expires_at>? AND s.auth_version=m.auth_version
                  AND m.active=1 AND t.active=1 AND m.role IN ('customer', 'staff', 'manager')''',
                (sid, time.time())).fetchone()
            require(row is not None, 401, 'session_expired', 'Phiên đã kết thúc hoặc quyền đã thay đổi. Vui lòng đăng nhập lại.')
            # P1.1 session safety: existing customer sessions fail-closed when customer_id is unresolved
            # (colliding, in quarantine, or reserved by an ongoing reconciliation).
            if row['role'] == 'customer':
                try:
                    unres = db.execute(
                        "SELECT 1 FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?",
                        (row['tenant_id'], row['customer_id'])
                    ).fetchone()
                    if unres:
                        require(False, 503, 'collision_unresolved', 'Tài khoản đang chờ xử lý va chạm dữ liệu.')

                    link_row = db.execute(
                        "SELECT customer_id FROM customer_links WHERE tenant_id=? AND principal_id=?",
                        (row['tenant_id'], row['principal_id'])
                    ).fetchone()
                    if link_row and link_row['customer_id'] != row['customer_id']:
                        link_unres = db.execute(
                            "SELECT 1 FROM unresolved_collisions WHERE tenant_id=? AND customer_id=?",
                            (row['tenant_id'], link_row['customer_id'])
                        ).fetchone()
                        if link_unres:
                            require(False, 503, 'collision_unresolved', 'Tài khoản đang chờ xử lý va chạm dữ liệu.')

                    col_cnt = db.execute(
                        "SELECT count(*) as total FROM memberships WHERE tenant_id=? AND customer_id=? AND role='customer'",
                        (row['tenant_id'], row['customer_id'])
                    ).fetchone()['total']
                    if col_cnt > 1:
                        require(False, 503, 'collision_unresolved', 'Tài khoản đang chờ xử lý va chạm dữ liệu.')
                except ApiError:
                    raise
                except Exception as e:
                    logger.error("Session safety check query failed for customer %s in tenant %s: %s",
                                 row['customer_id'], row['tenant_id'], e)
                    require(False, 503, 'collision_unresolved', 'Tài khoản đang chờ xử lý va chạm dữ liệu.')
            return dict(row)

    def logout(self, sid):
        with self.connection(write=True) as db:
            row = db.execute('SELECT membership_id FROM sessions WHERE id=?', (sid,)).fetchone()
            db.execute('DELETE FROM sessions WHERE id=?', (sid,))
            if row:
                self.event(db, 'logout', membership=row['membership_id'])

    def purge(self):
        with self.connection(write=True) as db:
            db.execute('DELETE FROM sessions WHERE expires_at<=?', (time.time(),))
            db.execute('DELETE FROM identity_rate WHERE "window"<?', (int(time.time())//60-2,))

    def reserve_api_attempt(self, limit):
        day = time.strftime('%Y-%m-%d', time.gmtime())
        with self.connection(write=True) as db:
            row = db.execute("SELECT attempts FROM provider_daily_usage WHERE day=? AND provider_id='api'", (day,)).fetchone()
            require(row is None or row['attempts'] < limit, 429, 'api_daily_limit', 'Đã hết lượt chat API hôm nay (UTC).')
            db.execute("""INSERT INTO provider_daily_usage VALUES (?,'api',1) ON CONFLICT(day,provider_id)
                DO UPDATE SET attempts=provider_daily_usage.attempts+1""", (day,))
            cutoff = (datetime.now(timezone.utc) - timedelta(days=31)).date().isoformat()
            db.execute("DELETE FROM provider_daily_usage WHERE day < ?", (cutoff,))

    def external_identity(self, issuer, sub):
        sub_clean = str(sub).strip() if (sub and str(sub).strip()) else ''
        issuer_clean = str(issuer).strip() if (issuer and str(issuer).strip()) else 'https://accounts.google.com'
        with self.connection() as db:
            row = db.execute('SELECT * FROM external_identities WHERE issuer=? AND sub=?',
                             (issuer_clean, sub_clean)).fetchone()
        return dict(row) if row else None

    def customer_link(self, tenant_id, principal_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM customer_links WHERE tenant_id=? AND principal_id=?',
                             (tenant_id, principal_id)).fetchone()
        return dict(row) if row else None

    def external_customer_mapping(self, tenant_id, source_system, external_customer_id):
        tenant_clean = str(tenant_id).strip()
        source_clean = str(source_system).strip()
        ext_cust_clean = str(external_customer_id).strip()
        with self.connection() as db:
            row = db.execute(
                'SELECT * FROM external_customer_mappings WHERE tenant_id=? AND source_system=? AND external_customer_id=?',
                (tenant_clean, source_clean, ext_cust_clean)
            ).fetchone()
        return dict(row) if row else None

    def get_external_customer_mapping(self, tenant_id, source_system, external_customer_id):
        row = self.external_customer_mapping(tenant_id, source_system, external_customer_id)
        return row['customer_id'] if row else None

    def set_external_customer_mapping(self, tenant_id, source_system, external_customer_id, customer_id):
        return self.link_external_customer(tenant_id, source_system, external_customer_id, customer_id)

    def link_external_customer(self, tenant_id, source_system, external_customer_id, customer_id):
        """Insert-if-absent mapping (tenant, source_system, external_customer_id) -> customer_id.

        Idempotent for the same customer (``created`` False, no extra audit event). A mapping that
        already points at a different customer is never overwritten: 409 external_customer_mapping_conflict.
        """
        tenant_clean = str(tenant_id).strip()
        source_clean = str(source_system).strip()
        ext_cust_clean = str(external_customer_id).strip()
        cid_clean = str(customer_id).strip()
        require(tenant_clean and source_clean and ext_cust_clean and cid_clean,
                400, 'invalid_mapping_fields', 'Thiếu trường ánh xạ khách hàng.')
        # P5-K4: Do NOT use email as key
        require('@' not in ext_cust_clean, 400, 'invalid_external_customer_id',
                'external_customer_id phải là mã định danh từ hệ thống nguồn, không dùng email làm khóa.')
        self.tenant(tenant_clean)
        now = time.time()
        with self.connection(write=True) as db:
            row = db.execute(
                'SELECT * FROM external_customer_mappings WHERE tenant_id=? AND source_system=? AND external_customer_id=?',
                (tenant_clean, source_clean, ext_cust_clean)
            ).fetchone()
            if row is not None:
                require(row['customer_id'] == cid_clean, 409, 'external_customer_mapping_conflict',
                        'external_customer_id đã được ánh xạ tới khách hàng khác trong cửa hàng này.')
                return {**dict(row), 'created': False}
            mapping_id = str(uuid.uuid4())
            db.execute('''INSERT INTO external_customer_mappings (id, tenant_id, source_system, external_customer_id, customer_id, created_at, updated_at)
                          VALUES (?,?,?,?,?,?,?)''',
                       (mapping_id, tenant_clean, source_clean, ext_cust_clean, cid_clean, now, now))
            self.event(db, 'external_customer_mapped', tenant_clean, None)
        return {'id': mapping_id, 'tenant_id': tenant_clean, 'source_system': source_clean,
                'external_customer_id': ext_cust_clean, 'customer_id': cid_clean,
                'created_at': now, 'updated_at': now, 'created': True}

    @staticmethod
    def _sanitize_audit_payload(payload):
        forbidden = {
            'token', 'secret', 'token_hash', 'hash', 'password', 'cookie',
            'oauth_code', 'oauth_state', 'messages', 'chat', 'prompt', 'content',
        }
        if isinstance(payload, dict):
            return {
                str(k): IdentityStore._sanitize_audit_payload(v)
                for k, v in payload.items()
                if str(k).lower() not in forbidden
            }
        if isinstance(payload, list):
            return [IdentityStore._sanitize_audit_payload(item) for item in payload]
        return payload

    def record_admin_audit(
        self,
        db,
        *,
        actor_principal_id,
        actor_role,
        tenant_id,
        target_membership_id,
        action,
        outcome,
        before_state,
        after_state,
        reason,
        correlation_id=None,
        now=None,
    ):
        require(outcome in ('allowed', 'denied'), 400, 'invalid_audit_outcome', 'Trạng thái audit không hợp lệ.')
        now_ts = float(now if now is not None else time.time())
        corr_id = str(correlation_id).strip() if correlation_id else str(uuid.uuid4())
        before_str = json.dumps(self._sanitize_audit_payload(before_state or {}), ensure_ascii=False, sort_keys=True)
        after_str = json.dumps(self._sanitize_audit_payload(after_state or {}), ensure_ascii=False, sort_keys=True)
        entry = {
            'created_at': now_ts,
            'correlation_id': corr_id,
            'actor_principal_id': str(actor_principal_id or 'unknown'),
            'actor_role': str(actor_role or 'unknown'),
            'tenant_id': str(tenant_id or 'unknown'),
            'target_membership_id': str(target_membership_id or '*'),
            'action': str(action),
            'outcome': outcome,
            'before_json': before_str,
            'after_json': after_str,
            'reason': str(reason or ''),
        }
        hook = getattr(self, '_audit_write_hook', None)
        if callable(hook):
            hook(db, entry)
        db.execute(
            '''INSERT INTO admin_audit_log (
                   created_at, correlation_id, actor_principal_id, actor_role,
                   tenant_id, target_membership_id, action, outcome,
                   before_json, after_json, reason
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (
                entry['created_at'],
                entry['correlation_id'],
                entry['actor_principal_id'],
                entry['actor_role'],
                entry['tenant_id'],
                entry['target_membership_id'],
                entry['action'],
                entry['outcome'],
                entry['before_json'],
                entry['after_json'],
                entry['reason'],
            ),
        )
        return entry

    def _check_admin_scope(
        self,
        actor,
        target_tenant_id,
        action,
        *,
        target_membership_id='*',
        reason='permission_check',
        correlation_id=None,
    ):
        actor_dict = actor if isinstance(actor, dict) else {}
        actor_role = str(actor_dict.get('role') or '')
        actor_pid = str(actor_dict.get('principal_id') or 'unknown')
        actor_tid = str(actor_dict.get('tenant_id') or '').strip()
        target_tid = str(target_tenant_id or '').strip()

        if actor_role != 'manager':
            with self.connection(write=True) as db:
                self.record_admin_audit(
                    db,
                    actor_principal_id=actor_pid,
                    actor_role=actor_role or 'customer',
                    tenant_id=actor_tid or target_tid or 'unknown',
                    target_membership_id=target_membership_id,
                    action=action,
                    outcome='denied',
                    before_state={},
                    after_state={'error': 'permission_denied'},
                    reason=reason or 'unauthorized_role',
                    correlation_id=correlation_id,
                )
            raise ApiError(403, 'permission_denied', 'Tài khoản này không có quyền quản trị tài khoản.')

        if not actor_tid or (target_tid and target_tid != actor_tid):
            with self.connection(write=True) as db:
                self.record_admin_audit(
                    db,
                    actor_principal_id=actor_pid,
                    actor_role=actor_role,
                    tenant_id=actor_tid or target_tid or 'unknown',
                    target_membership_id=target_membership_id,
                    action=action,
                    outcome='denied',
                    before_state={},
                    after_state={'error': 'cross_tenant_denied', 'actor_tenant_id': actor_tid, 'target_tenant_id': target_tid},
                    reason=reason or 'cross_tenant_access',
                    correlation_id=correlation_id,
                )
            raise ApiError(403, 'permission_denied', 'Quản lý cửa hàng không có quyền truy cập hoặc thao tác trên cửa hàng khác.')
        return actor_tid

    @staticmethod
    def _validate_admin_reason(reason):
        require(isinstance(reason, str) and 0 < len(reason.strip()) <= 500,
                400, 'invalid_reason', 'Cần nhập lý do thao tác quản trị (1-500 ký tự).')
        return reason.strip()

    def _build_account_view(self, db, row, default_limit=20, now_ts=None):
        from retailops.account_usage import AccountQuotaStore
        now_val = float(now_ts if now_ts is not None else time.time())
        mid = row['id']
        sess_row = db.execute(
            'SELECT count(*) AS cnt FROM sessions WHERE membership_id=? AND auth_version=? AND expires_at>?',
            (mid, row['auth_version'], now_val),
        ).fetchone()
        active_sessions = int(sess_row['cnt']) if sess_row else 0
        audit_row = db.execute(
            'SELECT max(created_at) AS last_at FROM admin_audit_log WHERE target_membership_id=?',
            (mid,),
        ).fetchone()
        last_audit_at = float(audit_row['last_at']) if (audit_row and audit_row['last_at'] is not None) else None

        quota_store = AccountQuotaStore(self, mid)
        eff_limit, override_info = quota_store._resolve_effective_limit(db, default_limit, now_ts=now_val)
        day_utc = datetime.fromtimestamp(now_val, tz=timezone.utc).date().isoformat()
        att_key = quota_store._key('api', 'attempts')
        att_row = db.execute(
            'SELECT attempts FROM provider_daily_usage WHERE day=? AND provider_id=?',
            (day_utc, att_key),
        ).fetchone()
        used = int(att_row['attempts']) if att_row else 0
        dt_now = datetime.fromtimestamp(now_val, tz=timezone.utc)
        tomorrow = datetime.combine(dt_now.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

        return {
            'membership_id': mid,
            'tenant_id': row['tenant_id'],
            'principal_id': row['principal_id'],
            'customer_id': row['customer_id'],
            'display_name': row['principal_name'],
            'role': row['role'],
            'active': bool(row['active']),
            'disabled_reason': row['disabled_reason'] if 'disabled_reason' in row.keys() else None,
            'auth_version': int(row['auth_version']),
            'active_session_count': active_sessions,
            'last_audit_at': last_audit_at,
            'quota': {
                'day_utc': day_utc,
                'used': used,
                'limit': eff_limit,
                'default_limit': default_limit,
                'remaining': max(0, eff_limit - used),
                'exhausted': used >= eff_limit,
                'override': override_info,
                'next_reset_utc': tomorrow.strftime('%Y-%m-%dT%H:%M:%SZ'),
            },
        }

    def admin_list_accounts(self, actor, *, tenant_id=None, query=None, limit=50, default_limit=20, correlation_id=None):
        actor_dict = actor if isinstance(actor, dict) else {}
        actor_role = str(actor_dict.get('role') or '')
        actor_tid = str(actor_dict.get('tenant_id') or '').strip()
        requested_tid = str(tenant_id).strip() if tenant_id is not None and str(tenant_id).strip() else (actor_tid if actor_role == 'manager' else '')
        effective_tid = self._check_admin_scope(
            actor,
            requested_tid,
            'list_accounts',
            target_membership_id='*',
            reason='list_accounts',
            correlation_id=correlation_id,
        )
        require(type(limit) is int and 1 <= limit <= 200, 400, 'invalid_limit', 'Giới hạn danh sách không hợp lệ.')
        q_clean = str(query).strip().lower() if query else ''
        with self.connection() as db:
            if q_clean:
                rows = db.execute(
                    '''SELECT m.*, p.name AS principal_name
                       FROM memberships m
                       JOIN principals p ON p.id = m.principal_id
                       WHERE m.tenant_id = ?
                       ORDER BY m.id ASC''',
                    (effective_tid,),
                ).fetchall()
            else:
                rows = db.execute(
                    '''SELECT m.*, p.name AS principal_name
                       FROM memberships m
                       JOIN principals p ON p.id = m.principal_id
                       WHERE m.tenant_id = ?
                       ORDER BY m.id ASC
                       LIMIT ?''',
                    (effective_tid, limit),
                ).fetchall()
            accounts = []
            for row in rows:
                if q_clean:
                    haystack = f"{row['id']} {row['principal_id']} {row['customer_id']} {row['principal_name']} {row['role']}".lower()
                    if q_clean not in haystack:
                        continue
                accounts.append(self._build_account_view(db, row, default_limit=default_limit))
                if len(accounts) >= limit:
                    break
        return {'tenant_id': effective_tid, 'accounts': accounts, 'count': len(accounts)}

    def admin_get_account(self, actor, membership_id, *, tenant_id=None, default_limit=20, correlation_id=None):
        mid = str(membership_id or '').strip()
        require(bool(mid), 400, 'invalid_membership_id', 'Mã tài khoản không hợp lệ.')
        with self.connection() as db:
            row = db.execute(
                '''SELECT m.*, p.name AS principal_name
                   FROM memberships m
                   JOIN principals p ON p.id = m.principal_id
                   WHERE m.id = ?''',
                (mid,),
            ).fetchone()
        if row is None:
            actor_role = str((actor or {}).get('role') or '')
            actor_tid = str((actor or {}).get('tenant_id') or '').strip()
            self._check_admin_scope(
                actor,
                tenant_id or actor_tid or 'unknown',
                'get_account',
                target_membership_id=mid,
                reason='get_account_not_found',
                correlation_id=correlation_id,
            )
            raise ApiError(404, 'account_not_found', 'Không tìm thấy tài khoản trong cửa hàng.')
        target_tid = row['tenant_id']
        if tenant_id and str(tenant_id).strip() != target_tid:
            self._check_admin_scope(
                actor,
                str(tenant_id).strip(),
                'get_account',
                target_membership_id=mid,
                reason='tenant_mismatch',
                correlation_id=correlation_id,
            )
            raise ApiError(404, 'account_not_found', 'Không tìm thấy tài khoản trong cửa hàng.')
        self._check_admin_scope(
            actor,
            target_tid,
            'get_account',
            target_membership_id=mid,
            reason='get_account',
            correlation_id=correlation_id,
        )
        with self.connection() as db:
            return {'account': self._build_account_view(db, row, default_limit=default_limit)}

    def _load_target_for_admin_mutation(self, actor, membership_id, action, reason, correlation_id=None, expected_tenant_id=None):
        mid = str(membership_id or '').strip()
        require(bool(mid), 400, 'invalid_membership_id', 'Mã tài khoản không hợp lệ.')
        with self.connection() as db:
            row = db.execute(
                '''SELECT m.*, p.name AS principal_name
                   FROM memberships m
                   JOIN principals p ON p.id = m.principal_id
                   WHERE m.id = ?''',
                (mid,),
            ).fetchone()
        exp_tid = str(expected_tenant_id).strip() if (expected_tenant_id is not None and str(expected_tenant_id).strip()) else ''
        if row is None:
            actor_tid = str((actor or {}).get('tenant_id') or '').strip()
            self._check_admin_scope(
                actor,
                exp_tid or actor_tid or 'unknown',
                action,
                target_membership_id=mid,
                reason=reason or action,
                correlation_id=correlation_id,
            )
            raise ApiError(404, 'account_not_found', 'Không tìm thấy tài khoản.')
        self._check_admin_scope(
            actor,
            row['tenant_id'],
            action,
            target_membership_id=mid,
            reason=reason or action,
            correlation_id=correlation_id,
        )
        if exp_tid and exp_tid != row['tenant_id']:
            with self.connection(write=True) as db:
                self.record_admin_audit(
                    db,
                    actor_principal_id=(actor or {}).get('principal_id'),
                    actor_role=(actor or {}).get('role'),
                    tenant_id=row['tenant_id'],
                    target_membership_id=mid,
                    action=action,
                    outcome='denied',
                    before_state={'target_tenant_id': row['tenant_id']},
                    after_state={
                        'error': 'tenant_scope_mismatch',
                        'expected_tenant_id': exp_tid,
                        'actual_tenant_id': row['tenant_id'],
                    },
                    reason=reason or action,
                    correlation_id=correlation_id,
                )
            raise ApiError(409, 'tenant_scope_mismatch', 'Tài khoản mục tiêu không thuộc cửa hàng (tenant_id) đang chọn.')
        if action == 'reactivate_account' and row['role'] not in ACTIVE_BUSINESS_ROLES:
            with self.connection(write=True) as db:
                self.record_admin_audit(
                    db,
                    actor_principal_id=(actor or {}).get('principal_id'),
                    actor_role=(actor or {}).get('role'),
                    tenant_id=row['tenant_id'],
                    target_membership_id=mid,
                    action=action,
                    outcome='denied',
                    before_state={'role': row['role'], 'active': bool(row['active'])},
                    after_state={'error': 'legacy_role_retired'},
                    reason=reason or action,
                    correlation_id=correlation_id,
                )
            raise ApiError(
                409,
                'legacy_role_retired',
                'Vai trò tài khoản cũ đã ngưng hỗ trợ; cần cập nhật sang vai trò hợp lệ trước khi kích hoạt lại.',
            )
        return row

    def admin_suspend_account(self, actor, membership_id, *, reason, correlation_id=None, default_limit=20, expected_tenant_id=None):
        row = self._load_target_for_admin_mutation(
            actor,
            membership_id,
            'suspend_account',
            str(reason or 'suspend_account'),
            correlation_id=correlation_id,
            expected_tenant_id=expected_tenant_id,
        )
        reason_clean = self._validate_admin_reason(reason)
        mid = row['id']
        actor_dict = actor if isinstance(actor, dict) else {}
        if actor_dict.get('membership_id') == mid or (
            actor_dict.get('principal_id') and actor_dict.get('principal_id') == row['principal_id']
            and actor_dict.get('tenant_id') == row['tenant_id']
        ):
            raise ApiError(400, 'self_lockout_forbidden', 'Không thể tự khóa tài khoản đang đăng nhập của chính mình.')

        now_ts = time.time()
        last_manager_denied = False
        with self.connection(write=True) as db:
            cur = db.execute(
                '''SELECT m.*, p.name AS principal_name
                   FROM memberships m
                   JOIN principals p ON p.id = m.principal_id
                   WHERE m.id = ?''',
                (mid,),
            ).fetchone()
            require(cur is not None, 404, 'account_not_found', 'Không tìm thấy tài khoản.')
            if cur['role'] == 'manager' and bool(cur['active']):
                other_mgr_cnt = db.execute(
                    "SELECT count(*) AS cnt FROM memberships WHERE tenant_id=? AND role='manager' AND active=1 AND id<>?",
                    (cur['tenant_id'], mid),
                ).fetchone()['cnt']
                if int(other_mgr_cnt) < 1:
                    self.record_admin_audit(
                        db,
                        actor_principal_id=actor_dict.get('principal_id'),
                        actor_role=actor_dict.get('role'),
                        tenant_id=cur['tenant_id'],
                        target_membership_id=mid,
                        action='suspend_account',
                        outcome='denied',
                        before_state={
                            'active': bool(cur['active']),
                            'role': cur['role'],
                        },
                        after_state={'error': 'last_active_manager_forbidden'},
                        reason=reason_clean,
                        correlation_id=correlation_id,
                        now=now_ts,
                    )
                    last_manager_denied = True
            if not last_manager_denied:
                sess_cnt = db.execute(
                    'SELECT count(*) AS cnt FROM sessions WHERE membership_id=?',
                    (mid,),
                ).fetchone()['cnt']
                before_state = {
                    'active': bool(cur['active']),
                    'auth_version': int(cur['auth_version']),
                    'role': cur['role'],
                    'customer_id': cur['customer_id'],
                    'active_sessions': int(sess_cnt),
                }
                new_auth_ver = int(cur['auth_version']) + 1
                db.execute(
                    "UPDATE memberships SET active=0, disabled_reason='admin_suspended', auth_version=? WHERE id=?",
                    (new_auth_ver, mid),
                )
                db.execute('DELETE FROM sessions WHERE membership_id=?', (mid,))
                self.event(db, 'account_suspended', cur['tenant_id'], mid)
                after_state = {
                    'active': False,
                    'disabled_reason': 'admin_suspended',
                    'auth_version': new_auth_ver,
                    'role': cur['role'],
                    'customer_id': cur['customer_id'],
                    'active_sessions': 0,
                }
                audit = self.record_admin_audit(
                    db,
                    actor_principal_id=actor_dict.get('principal_id'),
                    actor_role=actor_dict.get('role'),
                    tenant_id=cur['tenant_id'],
                    target_membership_id=mid,
                    action='suspend_account',
                    outcome='allowed',
                    before_state=before_state,
                    after_state=after_state,
                    reason=reason_clean,
                    correlation_id=correlation_id,
                    now=now_ts,
                )
                updated = db.execute(
                    '''SELECT m.*, p.name AS principal_name
                       FROM memberships m
                       JOIN principals p ON p.id = m.principal_id
                       WHERE m.id = ?''',
                    (mid,),
                ).fetchone()
                view = self._build_account_view(db, updated, default_limit=default_limit, now_ts=now_ts)
        if last_manager_denied:
            raise ApiError(
                409,
                'last_active_manager_forbidden',
                'Không thể tạm ngưng quản lý đang hoạt động cuối cùng của cửa hàng.',
            )
        return {'status': 'ok', 'account': view, 'audit_correlation_id': audit['correlation_id']}

    def admin_reactivate_account(self, actor, membership_id, *, reason, correlation_id=None, default_limit=20, expected_tenant_id=None):
        row = self._load_target_for_admin_mutation(
            actor,
            membership_id,
            'reactivate_account',
            str(reason or 'reactivate_account'),
            correlation_id=correlation_id,
            expected_tenant_id=expected_tenant_id,
        )
        reason_clean = self._validate_admin_reason(reason)
        mid = row['id']
        actor_dict = actor if isinstance(actor, dict) else {}
        now_ts = time.time()
        with self.connection(write=True) as db:
            cur = db.execute(
                '''SELECT m.*, p.name AS principal_name
                   FROM memberships m
                   JOIN principals p ON p.id = m.principal_id
                   WHERE m.id = ?''',
                (mid,),
            ).fetchone()
            require(cur is not None, 404, 'account_not_found', 'Không tìm thấy tài khoản.')
            cur_disabled = cur['disabled_reason'] if 'disabled_reason' in cur.keys() else None
            require(
                cur['role'] in ACTIVE_BUSINESS_ROLES and cur_disabled != IDENTITY_V5_DISABLE_REASON,
                409,
                'legacy_role_retired',
                'Vai trò tài khoản cũ đã ngưng hỗ trợ và không được phép kích hoạt lại.',
            )
            before_state = {
                'active': bool(cur['active']),
                'auth_version': int(cur['auth_version']),
                'role': cur['role'],
                'customer_id': cur['customer_id'],
            }
            new_auth_ver = int(cur['auth_version']) + 1
            db.execute(
                'UPDATE memberships SET active=1, disabled_reason=NULL, auth_version=? WHERE id=?',
                (new_auth_ver, mid),
            )
            self.event(db, 'account_reactivated', cur['tenant_id'], mid)
            after_state = {
                'active': True,
                'auth_version': new_auth_ver,
                'role': cur['role'],
                'customer_id': cur['customer_id'],
            }
            audit = self.record_admin_audit(
                db,
                actor_principal_id=actor_dict.get('principal_id'),
                actor_role=actor_dict.get('role'),
                tenant_id=cur['tenant_id'],
                target_membership_id=mid,
                action='reactivate_account',
                outcome='allowed',
                before_state=before_state,
                after_state=after_state,
                reason=reason_clean,
                correlation_id=correlation_id,
                now=now_ts,
            )
            updated = db.execute(
                '''SELECT m.*, p.name AS principal_name
                   FROM memberships m
                   JOIN principals p ON p.id = m.principal_id
                   WHERE m.id = ?''',
                (mid,),
            ).fetchone()
            view = self._build_account_view(db, updated, default_limit=default_limit, now_ts=now_ts)
        return {'status': 'ok', 'account': view, 'audit_correlation_id': audit['correlation_id']}

    def admin_revoke_sessions(self, actor, membership_id, *, reason, correlation_id=None, default_limit=20, expected_tenant_id=None):
        row = self._load_target_for_admin_mutation(
            actor,
            membership_id,
            'revoke_sessions',
            str(reason or 'revoke_sessions'),
            correlation_id=correlation_id,
            expected_tenant_id=expected_tenant_id,
        )
        reason_clean = self._validate_admin_reason(reason)
        mid = row['id']
        actor_dict = actor if isinstance(actor, dict) else {}
        now_ts = time.time()
        with self.connection(write=True) as db:
            cur = db.execute(
                '''SELECT m.*, p.name AS principal_name
                   FROM memberships m
                   JOIN principals p ON p.id = m.principal_id
                   WHERE m.id = ?''',
                (mid,),
            ).fetchone()
            require(cur is not None, 404, 'account_not_found', 'Không tìm thấy tài khoản.')
            sess_cnt = db.execute(
                'SELECT count(*) AS cnt FROM sessions WHERE membership_id=?',
                (mid,),
            ).fetchone()['cnt']
            before_state = {
                'active': bool(cur['active']),
                'auth_version': int(cur['auth_version']),
                'active_sessions': int(sess_cnt),
            }
            new_auth_ver = int(cur['auth_version']) + 1
            db.execute(
                'UPDATE memberships SET auth_version=? WHERE id=?',
                (new_auth_ver, mid),
            )
            db.execute('DELETE FROM sessions WHERE membership_id=?', (mid,))
            self.event(db, 'sessions_revoked', cur['tenant_id'], mid)
            after_state = {
                'active': bool(cur['active']),
                'auth_version': new_auth_ver,
                'active_sessions': 0,
            }
            audit = self.record_admin_audit(
                db,
                actor_principal_id=actor_dict.get('principal_id'),
                actor_role=actor_dict.get('role'),
                tenant_id=cur['tenant_id'],
                target_membership_id=mid,
                action='revoke_sessions',
                outcome='allowed',
                before_state=before_state,
                after_state=after_state,
                reason=reason_clean,
                correlation_id=correlation_id,
                now=now_ts,
            )
            updated = db.execute(
                '''SELECT m.*, p.name AS principal_name
                   FROM memberships m
                   JOIN principals p ON p.id = m.principal_id
                   WHERE m.id = ?''',
                (mid,),
            ).fetchone()
            view = self._build_account_view(db, updated, default_limit=default_limit, now_ts=now_ts)
        return {'status': 'ok', 'account': view, 'audit_correlation_id': audit['correlation_id']}

    def admin_set_quota_override(
        self,
        actor,
        membership_id,
        *,
        daily_limit,
        reason,
        expires_at=None,
        effective_at=None,
        correlation_id=None,
        default_limit=20,
        expected_tenant_id=None,
        _now=None,
    ):
        row = self._load_target_for_admin_mutation(
            actor,
            membership_id,
            'set_quota_override',
            str(reason or 'set_quota_override'),
            correlation_id=correlation_id,
            expected_tenant_id=expected_tenant_id,
        )
        reason_clean = self._validate_admin_reason(reason)
        if daily_limit is not None:
            require(
                type(daily_limit) is int and 1 <= daily_limit <= 10000,
                400,
                'invalid_quota_limit',
                'Hạn mức ngày phải là số nguyên từ 1 đến 10000 (hoặc null để xóa ghi đè).',
            )
        now_ts = float(_now if _now is not None else time.time())
        eff_ts = float(effective_at) if effective_at is not None else now_ts
        exp_ts = None
        if daily_limit is not None and expires_at is not None:
            require(
                isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool) and float(expires_at) > eff_ts,
                400,
                'invalid_expires_at',
                'Thời điểm hết hạn ghi đè hạn mức phải lớn hơn thời điểm bắt đầu có hiệu lực.',
            )
            exp_ts = float(expires_at)

        mid = row['id']
        actor_dict = actor if isinstance(actor, dict) else {}
        actor_pid = str(actor_dict.get('principal_id') or 'unknown')
        with self.connection(write=True) as db:
            cur = db.execute(
                '''SELECT m.*, p.name AS principal_name
                   FROM memberships m
                   JOIN principals p ON p.id = m.principal_id
                   WHERE m.id = ?''',
                (mid,),
            ).fetchone()
            require(cur is not None, 404, 'account_not_found', 'Không tìm thấy tài khoản.')
            prev_ov = db.execute(
                'SELECT daily_limit, effective_at, expires_at, reason, updated_by, updated_at '
                'FROM membership_quota_overrides WHERE membership_id=?',
                (mid,),
            ).fetchone()
            before_state = {
                'default_limit': default_limit,
                'override': dict(prev_ov) if prev_ov is not None else None,
            }
            if daily_limit is None:
                db.execute('DELETE FROM membership_quota_overrides WHERE membership_id=?', (mid,))
                self.event(db, 'quota_override_cleared', cur['tenant_id'], mid)
                after_state = {
                    'default_limit': default_limit,
                    'override': None,
                    'cleared': True,
                }
            else:
                db.execute(
                    '''INSERT INTO membership_quota_overrides (
                           membership_id, daily_limit, effective_at, expires_at, reason, updated_by, updated_at
                       ) VALUES (?,?,?,?,?,?,?)
                       ON CONFLICT(membership_id) DO UPDATE SET
                           daily_limit=excluded.daily_limit,
                           effective_at=excluded.effective_at,
                           expires_at=excluded.expires_at,
                           reason=excluded.reason,
                           updated_by=excluded.updated_by,
                           updated_at=excluded.updated_at''',
                    (mid, daily_limit, eff_ts, exp_ts, reason_clean, actor_pid, now_ts),
                )
                self.event(db, 'quota_override_set', cur['tenant_id'], mid)
                after_state = {
                    'default_limit': default_limit,
                    'override': {
                        'daily_limit': daily_limit,
                        'effective_at': eff_ts,
                        'expires_at': exp_ts,
                        'reason': reason_clean,
                        'updated_by': actor_pid,
                        'updated_at': now_ts,
                    },
                }
            audit = self.record_admin_audit(
                db,
                actor_principal_id=actor_pid,
                actor_role=actor_dict.get('role'),
                tenant_id=cur['tenant_id'],
                target_membership_id=mid,
                action='set_quota_override',
                outcome='allowed',
                before_state=before_state,
                after_state=after_state,
                reason=reason_clean,
                correlation_id=correlation_id,
                now=now_ts,
            )
            view = self._build_account_view(db, cur, default_limit=default_limit, now_ts=now_ts)
        return {'status': 'ok', 'account': view, 'audit_correlation_id': audit['correlation_id']}

    def admin_list_audit_logs(self, actor, *, tenant_id=None, target_membership_id=None, limit=100, correlation_id=None):
        actor_dict = actor if isinstance(actor, dict) else {}
        actor_role = str(actor_dict.get('role') or '')
        actor_tid = str(actor_dict.get('tenant_id') or '').strip()
        requested_tid = str(tenant_id).strip() if tenant_id is not None and str(tenant_id).strip() else (actor_tid if actor_role == 'manager' else '')
        effective_tid = self._check_admin_scope(
            actor,
            requested_tid,
            'list_audit_logs',
            target_membership_id=str(target_membership_id or '*'),
            reason='list_audit_logs',
            correlation_id=correlation_id,
        )
        require(type(limit) is int and 1 <= limit <= 500, 400, 'invalid_limit', 'Giới hạn truy vấn audit không hợp lệ.')
        with self.connection() as db:
            if target_membership_id:
                rows = db.execute(
                    '''SELECT * FROM admin_audit_log
                       WHERE tenant_id=? AND target_membership_id=?
                       ORDER BY id DESC LIMIT ?''',
                    (effective_tid, str(target_membership_id).strip(), limit),
                ).fetchall()
            else:
                rows = db.execute(
                    '''SELECT * FROM admin_audit_log
                       WHERE tenant_id=?
                       ORDER BY id DESC LIMIT ?''',
                    (effective_tid, limit),
                ).fetchall()
        logs = []
        for r in rows:
            d = dict(r)
            try:
                d['before'] = json.loads(d.get('before_json') or '{}')
            except Exception:
                d['before'] = {}
            try:
                d['after'] = json.loads(d.get('after_json') or '{}')
            except Exception:
                d['after'] = {}
            logs.append(d)
        return {'tenant_id': effective_tid, 'audit_logs': logs, 'count': len(logs)}
