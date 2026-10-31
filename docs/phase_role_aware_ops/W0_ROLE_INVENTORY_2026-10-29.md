# Phase R1 — W0 Read-only Role Inventory

> **Status:** READ-ONLY INVENTORY · NO CODE, MIGRATION, DATABASE OR RUNTIME CHANGE
> **Source revision:** `bbfd11d0ba4c13514a197a6b25802c4e217bedb3`. Argon's supplied report records a read-only GitHub `git ls-remote` result at `2026-10-29T23:11:17+07:00`; this timestamp-bounded evidence is not proof of the current latest `main`. The inventory was inspected in a clean detached worktree at that SHA; no machine-specific checkout path is part of this record.

## Scope and evidence boundary

This inventory records source behavior at the recorded source revision. It does not count live memberships, linked sessions or database rows, and it does not prove that EC2, Colab, GitHub Actions or a deployed runtime has this behavior. No application tests, migration, build, CI run or runtime action was performed for this inventory.

The target business taxonomy from the owner record is `customer`, `staff`, and `manager`. The store owner uses `manager`. `opsadmin` is a separate Ops Admin Console authentication path. `viewer` is legacy and must fail closed; latest owner direction is to disable its app access, then remove membership rows only when safe (otherwise freeze/lock and phase out). `platform_admin` is legacy technical debt to retire gradually. These target directions are policy records, not current source behavior; see [latest owner decision delta](W0_OWNER_DECISION_DELTA_2026-10-29.md).

## Verified role inventory

| Identity / role | Current source behavior at `bbfd11d0` | W0 implication |
|---|---|---|
| `customer` | `ROLE_PERMISSIONS` grants `orders:read` and `orders:cancel` ([`retailops/business/permissions.py`](../../retailops/business/permissions.py), lines 8–13). Google role resolution falls back to `customer` when an email is absent from the staff/manager allowlists ([`retailops/http/auth_google.py`](../../retailops/http/auth_google.py), lines 193–205). | Target business role. Login must not use this fallback to overwrite an existing non-customer membership. |
| `staff` | Grants read, cancel and Staff Desk permissions in the same role map. Staff routes include escalations, transcript access, reply, resolve and `/api/tools/execute` ([`retailops/http/routes.py`](../../retailops/http/routes.py), lines 318–330 and 414–446). | Target business role. Exact case and order-action scope remains an implementation contract. |
| `manager` | Grants staff permissions plus `store:manage`. Current account-admin methods accept `manager` within its tenant ([`retailops/identity/store.py`](../../retailops/identity/store.py), lines 1058–1111), and `/api/orders` exposes `store_all` to `manager` or `platform_admin` ([`retailops/http/routes.py`](../../retailops/http/routes.py), lines 225–232). | Target business role; do not infer cross-tenant privileges from the current source behavior. |
| `viewer` | Remains a valid membership/database role with read-only permissions. SQLite and PostgreSQL schemas allow it, the CLI can create/set it, and existing tests exercise order/policy reads and denied cancellation. | Legacy role outside the target taxonomy. Owner direction: disable app access first; remove membership rows only when safe, otherwise freeze/lock and retire gradually under approved migration/rollback. Never auto-promote it. |
| `platform_admin` | Remains in `ROLE_PERMISSIONS` with read, cancel, staff, manager and `platform:admin` permissions. SQLite/PostgreSQL schemas and identity migrations explicitly allow it. `/api/admin/*` account operations accept `manager` or `platform_admin`; `platform_admin` requires an explicit tenant scope and can cross tenant boundaries under that control path. | Legacy technical debt. Owner direction is gradual retirement with no runtime alias to `manager` and no transfer of historical cross-tenant grants. Stop provisioning, inventory, migrate only explicitly eligible accounts, invalidate sessions and retire schema/RBAC only after a separately approved migration packet. |
| `opsadmin` | Is created by `deploy/admin-console.py` as a Caddy Basic Auth username for the separate admin console. It is not present in `ROLE_PERMISSIONS`, the membership role check, or the application `SessionBinding` role set. | Separate control-plane login, not a business membership role and not an alias for `manager` or `platform_admin`. |

## Google role and membership behavior

The current Google path is:

1. [`retailops/http/public.py`](../../retailops/http/public.py), lines 122–177, exchanges the Google profile and calls `resolve_role_from_email`.
2. [`retailops/http/auth_google.py`](../../retailops/http/auth_google.py), lines 193–205, maps manager/staff email allowlists and otherwise returns `DEFAULT_ROLE` or `customer`.
3. [`retailops/identity/persistent.py`](../../retailops/identity/persistent.py), lines 189–206, passes that role into `get_or_create_google_member`.
4. [`retailops/identity/store.py`](../../retailops/identity/store.py), lines 779–807, looks up an existing membership and updates its role when `existing['role'] != role`, incrementing `auth_version`.

Therefore, an existing `viewer`, `staff` or `manager` membership can be overwritten by the role inferred at login when its email is not in the current allowlists. The source does not yet implement the owner direction that existing role assignments are authoritative and Viewer fails closed. This is a source finding, not a live membership count.

## Trusted display name and actor boundary

The persistent session binding carries the server-side principal, membership, role and principal name ([`retailops/identity/persistent.py`](../../retailops/identity/persistent.py), lines 223–253). However:

- `/api/session` and `/api/profile` still synthesize `Mai Anh` or `Khách mẫu` when the binding has no display name ([`retailops/http/routes.py`](../../retailops/http/routes.py), lines 156–177).
- `/api/staff/reply` and `/api/staff/resolve` accept a browser-supplied `staff_name`, apply a demo fallback, and pass it into persistence ([`retailops/http/routes.py`](../../retailops/http/routes.py), lines 414–430; [`retailops/business/store.py`](../../retailops/business/store.py), lines 1643–1687 and 1744–1755).

The target contract remains: authorization and audit use the server-derived principal; UI may show the server-derived Google display name; if no trusted name exists, show no canned greeting; client `staff_name` must not be an actor/audit field.

## Schema and deployment drift to resolve

- SQLite membership creation and the PostgreSQL schema both allow all five current source roles, including `viewer` and `platform_admin` ([`retailops/identity/store.py`](../../retailops/identity/store.py), lines 27–30 and 434–439; [`retailops/storage/pg_schema.py`](../../retailops/storage/pg_schema.py), lines 80–86).
- The PostgreSQL repository repeats the five-role check ([`retailops/storage/pg_repositories.py`](../../retailops/storage/pg_repositories.py), lines 68–71).
- [`scripts/update_ec2.py`](../../scripts/update_ec2.py), lines 261–270, writes a four-role constraint that excludes `platform_admin`. This is a source/deployment-contract mismatch to resolve in the migration/rollback packet; no live schema was inspected or changed.
- Business tables use `customer_id` foreign keys to `customers`, while every membership, including staff/manager/platform-admin memberships, carries a non-null `customer_id`. The relationship between persistent non-customer identities and business customer rows must be explicitly specified before changing the schema.

## Existing tests and their limits

The repository contains tests for Viewer read access and denied cancellation, Google allowlist/default-role mapping, platform-admin account administration and client-provided staff names. These tests document or protect historical behavior at this base; they do not constitute approval of the owner target contract. No tests were executed in this W0 inventory.

## Remaining W0 gate and 2026-10-31 W0 closeout addendum

The static inventory above is preserved as inspected at `bbfd11d0ba4c13514a197a6b25802c4e217bedb3` (a read-only `git ls-remote origin refs/heads/main` check on 2026-10-31 again returned `bbfd11d0ba4c13514a197a6b25802c4e217bedb3`; live database counts remain uninspected). On 2026-10-31, [owner delta §10](W0_OWNER_DECISION_DELTA_2026-10-29.md#10-final-owner-decisions-2026-10-31) and [accepted mechanics §11](W0_OWNER_DECISION_DELTA_2026-10-29.md#11-accepted-mechanics-2026-10-31) closed the W0 design items below, and the owner issued a bounded **W1-only** execution authorization (not a new readiness review `READY`; `W2–W6` and production database/migration work remain unauthorized):

- **Viewer (`OD-02`, §10 & §11.5):** fail closed across application login, session resolution and routes; never promote `viewer` to `customer`; in identity v5 migration code, disable existing `viewer` memberships (`active=0`, `disabled_reason`), bump `auth_version` and revoke sessions without deleting membership, customer, order, conversation or audit rows.
- **Manager `/api/admin/*` vs `opsadmin` (`OD-01`, §10 & §11.1):** Manager retains same-tenant `/api/admin/accounts*` and `/api/admin/audit-log` (tenant strictly from server session; deny self-suspend and suspending the last active Manager of a tenant; no role-change HTTP route). `opsadmin` stays on the separate read-only Caddy Basic Auth Ops Console.
- **`platform_admin` retirement (`OD-01`, §10 & §11.1 & §11.5):** delete cross-tenant runtime branches in `/api/orders` and `/api/admin/*`, never alias `platform_admin` to `manager` or `opsadmin`, forbid new provisioning/reactivation, and disable legacy `platform_admin` memberships in identity v5 while preserving historical rows/audit.
- **Google role sync & role-assignment policy boundary:** existing membership roles in the Identity DB are authoritative at Google login (never silently overwritten). Any open policy choice on whether brand-new self-service Google logins may still use verified-email `STAFF_EMAILS`/`MANAGER_EMAILS` allowlists versus operator-only role provisioning/role-change authority must be escalated to the owner rather than invented in W1.
- **Server-bound actor/display name:** Staff Desk reply/resolve and audit attribution derive principal, role, tenant and trusted `display_name` from the server session/request context; client `staff_name` is untrusted and never used as actor identity.

**Addendum 2026-10-31 — đối chiếu với code W1 (không phải live inventory):** W1 đã đổi các hành vi nguồn ở bảng phía trên. Bảng đó vẫn là snapshot tại `bbfd11d0` và được giữ nguyên. Trong dirty W1 tree, review ghi nhận các điểm sau:

- Google login không còn ghi đè role của membership hiện hữu.
- Membership mới vẫn có thể nhận `staff`/`manager` qua allowlist, hoặc qua `DEFAULT_ROLE` nếu biến này đặt role đặc quyền (`W1-ID-01`).
- CLI `set-role` cộng với Manager reactivate có thể đưa một membership `platform_admin`/`viewer` đã retire trở lại thành role đang hoạt động mà không có gate eligibility. Điều này mâu thuẫn với dòng "forbid new provisioning/reactivation" ở trên (`W1-ID-02`).
- Khi thiếu display name, reply/resolve lưu nhãn vai trò chung (`Nhân viên hỗ trợ`/`Quản lý cửa hàng`), tách biệt với actor lấy từ session (`W1-AUD-01`; ghi chú không chặn, không thuộc register severity).

Bằng chứng, mức độ và chính sách chờ owner nằm trong [docs review addendum](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-10-31-w1-docs-review-addendum). Không có số liệu membership trên DB thật nào được kiểm tra.

**Cập nhật sau đó cùng ngày:** remediation đã đóng hai điểm ở trên. `DEFAULT_ROLE` giờ chỉ được là `customer`. `set-role` và reactivate từ chối mọi membership legacy đã retire. Owner đã chốt: allowlist trong biến môi trường là kênh chuyển tiếp để cấp role cho tài khoản mới, và đổi role chỉ qua CLI chạy trên AWS SSM ([owner delta §12](W0_OWNER_DECISION_DELTA_2026-10-29.md#12-w1-policy-decisions-2026-10-31)).
