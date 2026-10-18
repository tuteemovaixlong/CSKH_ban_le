# ADR P5-E: Account Lifecycle, Per-Membership Quota Overrides & Append-Only Audit Governance

- **Date:** 2026-10-17
- **Status:** Accepted (Phase 5-E Track B)
- **Baseline:** `44540eab516831d5c8232dd80392b8e20c6cd47e` (PR #42 merged on `main`)
- **Related Documents:**
  - [Phase 5-E Execution Handoff](PHASE_5_E_EXECUTION_HANDOFF.md)
  - [Phase 5-E AI Trust & Account Governance Plan](PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md)
  - [Phase 5-E Acceptance Criteria](PHASE_5_E_ACCEPTANCE_CRITERIA.md)
  - [Admin Console Design](../ADMIN_CONSOLE.md)

---

## 1. Context & Problem Statement

Phase 5-E requires operator-controlled account lifecycle and quota governance (`P5-E-ADM1`..`ADM6`) so operators can:
1. Search and inspect accounts (`memberships`) and their current UTC daily API quota usage, effective limit, and next reset time.
2. Temporarily or permanently suspend (`active = 0`) and reactivate (`active = 1`) accounts, and immediately revoke active sessions (`auth_version` bump + `sessions` deletion).
3. Set or clear bounded per-membership daily API quota overrides (`1..10000`) with effective/expiry timestamps and mandatory reason, without mutating the global default cap.
4. Record every privileged state change (and denied cross-tenant/unauthorized operator attempt) in an append-only `admin_audit_log` table with full before/after state snapshots and correlation IDs.
5. Preserve the strict read-only boundary of Ops Console v1 (`opsconsole/server.py`), which has no database credentials, no Docker socket, and no write endpoints.

---

## 2. Decision

### 2.1 Role & Permission Model (`P5-E-ADM1`)

We separate platform-wide administration, tenant-scoped administration, and non-admin roles:

| Role | Permissions | Tenant Scope for Account Governance | Allowed Account Governance Actions |
|---|---|---|---|
| `platform_admin` | `orders:view`, `orders:cancel`, `orders:view_all`, `store:manage`, `platform:admin` | Explicit `tenant_id` filter or cross-tenant | List/search accounts, view account + quota status, suspend/reactivate, revoke sessions, set/clear quota overrides, view `admin_audit_log` |
| `manager` (tenant manager) | `orders:view`, `orders:cancel`, `orders:view_all`, `store:manage` | Strictly restricted to the manager's own authenticated `tenant_id` | Same actions **only** for memberships where `target.tenant_id == actor.tenant_id` and `target.role != 'platform_admin'` |
| `staff` / `viewer` / `customer` | Existing business permissions only (no `store:manage`, no `platform:admin`) | None | Denied (`403 permission_denied`) on all `/api/admin/accounts*` endpoints |

**Hard invariants:**
- Authorization is resolved **exclusively** from the server-verified session (`PersistentSessions.resolve` / `PostgresSessions.resolve`) or server-configured operator token.
- Client-supplied headers, query parameters, or JSON body fields (`role`, `persona`, `is_admin`, `actor_principal_id`) are never trusted for privilege elevation.
- Neither `manager` nor `platform_admin` can impersonate a customer session or read raw customer conversation transcripts via the account governance API.

### 2.2 Control-Plane Boundary (`P5-E-ADM6`)

- **Ops Console v1 (`opsconsole/server.py`):** Remains 100% read-only (`GET` only; `405 read_only_console` for non-GET), isolated from business/identity databases, model credentials, and Docker sockets.
- **Account Governance Control Plane (`/api/admin/accounts*` on `PublicWeb`):**
  - `GET /api/admin/accounts` — Scoped list/search by `tenant_id` (`platform_admin` only for cross-tenant), `q` (membership ID, principal ID, customer ID, display name, or verified external email — filtered **before** applying `limit` `1..200`), `role`, and `active` status.
  - `GET /api/admin/accounts/{membership_id}` — Scoped detail view returning account metadata, active session count, current UTC day API usage, effective daily limit, active quota override (if any), and `next_reset_utc`.
  - `POST /api/admin/accounts/{membership_id}/suspend` — Suspends membership (`active = 0`), increments `auth_version`, deletes all `sessions` for the membership, and writes `admin_audit_log`.
  - `POST /api/admin/accounts/{membership_id}/reactivate` — Reactivates membership (`active = 1`), increments `auth_version`, preserves `tenant_id`/`principal_id`/`customer_id` bindings, and writes `admin_audit_log`.
  - `POST /api/admin/accounts/{membership_id}/revoke-sessions` — Keeps `active` unchanged, increments `auth_version`, deletes all `sessions` for the membership, and writes `admin_audit_log`.
  - `POST /api/admin/accounts/{membership_id}/quota` — Sets (`daily_limit` in `1..10000`, optional `effective_at`/`expires_at`) or clears (`daily_limit: null` / `None`, deleting the row in `membership_quota_overrides` and restoring `default_limit`) a per-membership quota override with mandatory `reason`, and writes `admin_audit_log`.
  - `GET /api/admin/audit-log` — Read-only query of `admin_audit_log` (scoped to `actor.tenant_id` for `manager`, or optional `tenant_id` filter for `platform_admin`).
- All `POST /api/admin/*` endpoints enforce `check_origin(handler)` CSRF protection, strict JSON schema validation, optional `tenant_id` scope verification (`409 tenant_scope_mismatch` + denied audit entry if the operator's selected `tenant_id` does not match the target membership's `tenant_id`), and mandatory non-empty `reason` (`1..500` characters).

### 2.3 Quota Override Storage & Effective Limit Resolution (`P5-E-ADM4`)

1. **Schema (`membership_quota_overrides` in SQLite and PostgreSQL `retailops_identity`):**
   - `membership_id TEXT PRIMARY KEY REFERENCES memberships(id)`
   - `daily_limit INTEGER NOT NULL CHECK(daily_limit BETWEEN 1 AND 10000)`
   - `effective_at REAL/DOUBLE PRECISION NOT NULL`
   - `expires_at REAL/DOUBLE PRECISION` (nullable; when set and `expires_at <= now`, the override is expired)
   - `reason TEXT NOT NULL`
   - `updated_by TEXT NOT NULL`
   - `updated_at REAL/DOUBLE PRECISION NOT NULL`
2. **Resolution in `AccountQuotaStore.reserve_api_attempt(default_limit)`:**
   - Inside an atomic write transaction (`with self.control.connection(write=True) as db:`), resolve the effective daily limit for `self.membership_id`:
     - If a row exists in `membership_quota_overrides` with `effective_at <= now` and `(expires_at IS NULL OR expires_at > now)`, `effective_limit = override.daily_limit`.
     - Otherwise (or after clearing an override via `daily_limit = None`), `effective_limit = default_limit` (the global default `app.api_daily_limit`).
   - Check `provider_daily_usage` for `(day = current_utc_day, provider_id = f"api:{membership_id}")`.
   - If `attempts >= effective_limit`, fail closed with `429 api_daily_limit`.
   - Otherwise increment `attempts` atomically (`INSERT ... ON CONFLICT(day, provider_id) DO UPDATE SET attempts = attempts + 1`).
3. **UTC Reset Window:**
   - Quota buckets key on UTC calendar day (`YYYY-MM-DD`).
   - `next_reset_utc` is reported as `<next-utc-day>T00:00:00Z`.

### 2.4 Append-Only Admin Audit Log (`P5-E-ADM5`)

1. **Schema (`admin_audit_log` in SQLite and PostgreSQL `retailops_identity`):**
   - `id` (`INTEGER PRIMARY KEY AUTOINCREMENT` / `BIGSERIAL PRIMARY KEY`)
   - `created_at` (`REAL` / `DOUBLE PRECISION NOT NULL`)
   - `correlation_id` (`TEXT NOT NULL`)
   - `actor_principal_id` (`TEXT NOT NULL`)
   - `actor_role` (`TEXT NOT NULL`)
   - `tenant_id` (`TEXT NOT NULL`)
   - `target_membership_id` (`TEXT NOT NULL`)
   - `action` (`TEXT NOT NULL`)
   - `outcome` (`TEXT NOT NULL CHECK(outcome IN ('allowed', 'denied'))`)
   - `before_json` (`TEXT NOT NULL`)
   - `after_json` (`TEXT NOT NULL`)
   - `reason` (`TEXT NOT NULL`)
2. **Atomicity & Immutability:**
   - Every allowed admin write executes the state mutation and the `INSERT INTO admin_audit_log` inside the **same** database transaction. If the audit write fails, the state mutation rolls back automatically.
   - Denied operator attempts (e.g., cross-tenant access by a tenant `manager` or `tenant_scope_mismatch`) commit a `denied` audit record before raising `403`/`409`.
   - No `UPDATE` or `DELETE` method or HTTP route is exposed for `admin_audit_log`.
   - Snapshots (`before_json`, `after_json`) never include session secrets, credential hashes, OAuth tokens, or customer chat messages.

### 2.5 SQLite Legacy Role Constraint Migration (`R2`)

- Legacy SQLite identity databases created before Phase 5-E define `memberships.role` with a 4-role `CHECK (role IN ('customer', 'viewer', 'staff', 'manager'))` and child foreign keys from `credentials(membership_id)`, `sessions(membership_id)`, and `membership_quota_overrides(membership_id)`.
- Because SQLite ignores `PRAGMA foreign_keys = OFF` inside an active transaction, `upgrade_sqlite_memberships_role_constraint(path)` opens a connection with `isolation_level = None`, verifies `PRAGMA foreign_keys = OFF` **before** `BEGIN IMMEDIATE`, rebuilds `memberships` via `memberships_p5e_new` with the 5-role constraint (`customer`, `viewer`, `staff`, `manager`, `platform_admin`), runs `PRAGMA foreign_key_check` before `COMMIT`, and restores `PRAGMA foreign_keys = ON`.
- Migration errors are **never swallowed**; any failure rolls back the transaction cleanly (including after `DROP TABLE memberships`) without leaving `memberships_p5e_new` behind or corrupting foreign keys.

### 2.6 Account & Quota Governance UI (`R4`)

- The operator UI for `P5-E-ADM1..ADM6` lives in `web/index.html` + `web/app.js` inside the authenticated Manager/Admin Console on `PublicWeb` (keeping `opsconsole/server.py` and `opsconsole/static/app.js` strictly read-only).
- Visibility & Scope:
  - Hidden and blocked for `customer`, `viewer`, and `staff` sessions.
  - Visible in `#tab-btn-accounts` (`Tài khoản & Quota`) for `manager` (locked to own `tenant_id`) and `platform_admin` (with explicit `#admin-tenant-id-input` selector).
  - Changing `#admin-tenant-id-input` immediately clears `#admin-selected-membership-id` (`clearAdminSelectedAccount()`) and hides `#admin-account-detail-panel` so stale cross-tenant selections cannot be submitted; admin POST payloads also include `tenant_id` verified by the server.
- Displays `quota.next_reset_utc` in both the account table and the detail inspector, and provides explicit controls to suspend, reactivate, revoke sessions, set bounded quota overrides (`1..10000`), and clear quota overrides (`daily_limit: null`) with mandatory reason and explicit confirmation checkbox reset after each action.
