# Phase R1 — Implementation Readiness: BLOCKED

> **Status:** `BLOCKED` (readiness review verdict unchanged; no `READY` review claimed) · **2026-10-31 owner exception:** bounded **W1-only** execution authorized after W0 doc closeout (`W2–W6`, live DB/production migration, EC2/Colab, commit & deploy remain **NOT AUTHORIZED**)
> **W1 state (2026-10-31, latest):** the 5 W1 BLOCKERs were remediated and [verified](#2026-10-31-w1-remediation-verification), and the owner decided both W1 policy questions ([owner delta §12](W0_OWNER_DECISION_DELTA_2026-10-29.md#12-w1-policy-decisions-2026-10-31)). No W1 blocker remains open; **the owner confirmed W1 closed on 2026-10-31 — W1 is complete** (this is not `READY` for `W2–W6`) ([closure status](#2026-10-31-w1-owner-policy-decisions-and-closure-status)). Overall readiness stays **`BLOCKED`** for `W2–W6`. Earlier history: [W1 review](#2026-10-31-w1-implementation-readiness-review--codex), [docs review addendum](#2026-10-31-w1-docs-review-addendum).
> **As-of date:** 2026-10-29 (updated 2026-10-31 with §10/§11 closeout & W1-only authorization addendum)
> **Provenance:** owner-provided summary of Gemini 4 Argon’s review; the individual reviewer reports are not attached in this repository.

> **Current interpretation (2026-10-31):** The historical findings and earlier owner-delta wording below are preserved for provenance. For execution, read [W0 owner decision delta §§10–11](W0_OWNER_DECISION_DELTA_2026-10-29.md#10-final-owner-decisions-2026-10-31) and the **W0 closeout & W1-only authorization addendum** at the end of this file. They supersede earlier open/proposal wording where they overlap. This does **not** change the readiness verdict: it remains BLOCKED; only bounded local W1 identity/RBAC/backend-authorization code and isolated tests are authorized. The first-time Google-login role-provisioning policy remains explicitly owner-gated; do not invent it in W1.

## Owner decision delta after the blocked review (2026-10-28; latest input 2026-10-29)

The owner has directed that `platform_admin` be phased out as technical debt, while keeping `opsadmin` separate; the exact Manager tenant-admin versus Ops Console `/api/admin/*` boundary is still not unambiguously selected. Latest follow-up directs disabling Viewer app access, removing its membership only when safe, otherwise freezing/locking and phasing out. The case states remain `waiting`, `in_progress`, `resolved`; after 3 minutes without a customer reply the interaction is inactive, and each customer reply resets the timer. The 1.5-minute flag is prohibited in production and is limited to evaluation/specialized test states; do not auto-close staff work due to overload. Timer start, eligible states, and whether inactivity is recorded separately or resolves a case remain open. Prior completion flow includes gentle follow-up/feedback and about 5-minute post-feedback resolution, with anchor still open. Pending-order cancellation, Manager's direct order-status path, Customer-requested returns, Staff/Manager return approval, history/DB update and JSONL family remain owner directions; detailed permission, transaction, endpoint-compatibility, vocabulary and attachment policies remain open. OD-05 means the application API, not an LLM provider API. OD-08 image/file handling is now included across the W0–W6 plan, but evidence policy and runtime validation remain open. None of these decisions clears readiness or authorizes runtime alias, privilege transfer, migration or schema change. Trusted Google `display_name` and server-bound `case_id` remain target invariants. See [historical owner decision snapshot](OWNER_DECISIONS_2026-10-28.md), [latest W0 owner decision delta/proposals](W0_OWNER_DECISION_DELTA_2026-10-29.md), and [W0 register](W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md).

## Verdict and scope

Argon’s reported implementation-readiness verdict is **`BLOCKED`**, with **9 BLOCKER, 6 MAJOR and 3 MINOR** findings. The review used three independent reviewer areas: Security/RBAC; Domain/Persistence/API; Workflow/AI/Cache/UI. These counts and reviewer areas are recorded here as owner-provided evidence, not as a review independently repeated by this document’s author.

This is separate from all documentation-only reviews. The docs-review loop is closed (chronology in the [W0 review reconciliation](W0_REVIEW_RECONCILIATION_2026-10-28.md)); no docs result approves implementation, migration, CI, deployment or runtime.

**Provenance gap:** the detailed 9/6/3 finding register is not in this repository. The next readiness review must produce a fresh, self-contained finding register on the exact candidate rather than try to close the unattached 9/6/3 list.

## Readiness boundary

> **Đọc theo ngày (2026-10-31):** hai gạch đầu dòng đầu tiên dưới đây là ranh giới ngày 2026-10-29 và được giữ nguyên để truy vết. Riêng với W1, chúng đã bị thay thế bởi [W0 closeout & W1-only authorization addendum](#2026-10-31-w0-closeout--w1-only-authorization-addendum). W1 đã được thực thi trong worktree nhưng review W1 kết luận `BLOCKED`. `W2–W6`, migration trên DB thật, runtime, deploy, commit và push vẫn **không được phép**.

- Do not begin W1–W6 or open a code-writing handoff to Argon while this verdict remains in force.
- W0 may reconcile the Git base, inventory source/schema role handling without exposing personal data, document owner decisions, and freeze contracts. Do not change production data or make implicit policy decisions.
- **Delivery grouping:** W0 read-only reconciliation is the only current activity. The planned sequence is strictly `W0 → W1 → W2 → W3 → W4 → W5 → W6`, with **no parallel execution** (owner-decided, [2026-10-31 owner decisions](W0_OWNER_DECISION_DELTA_2026-10-29.md#10-final-owner-decisions-2026-10-31)). The three management waves are `W0–W2`, `W3–W4`, and `W5–W6`; grouping does not authorize W1–W6. See the [canonical delivery map](README.md).
- Argon’s suggested `Option A` choices for OD-01–OD-08 are recommendations, **not owner approvals**. OD-01, OD-03 transition, OD-04 Staff scope, OD-05–OD-07 and scheduling were decided on 2026-10-31 ([2026-10-31 owner decisions](W0_OWNER_DECISION_DELTA_2026-10-29.md#10-final-owner-decisions-2026-10-31)); the per-item notes that follow are the earlier status; OD-02 direction is disable Viewer app access first, remove membership only where safe, otherwise freeze/lock and phase out; OD-03 has an updated 3-minute target, customer-reply reset and no-production-flag/no-overload-close guardrails, while timer start/eligibility/transition remain open; OD-04 has direction but detailed authority/data contracts remain open; OD-05 scope is clarified while compatibility disposition remains open; OD-06–OD-08 policy details remain gates. OD-08 image/file handling has been added as planned W0–W6 scope; the production-capable Colab target, compact context, current endpoint warning, and 8,192/16,384 evaluation boundary are recorded in the current owner delta. Policy and runtime validation remain open. See the [latest W0 decision delta](W0_OWNER_DECISION_DELTA_2026-10-29.md) and W0 register for exact disposition.
- Do not use the archived [implementation trigger](archive/ARGON_R1_IMPLEMENTATION_TRIGGER_2026-10-27.md) as an authorization to code; it is superseded.
- No further documentation-only review is planned. The next review is a single implementation-readiness review (see Next gate); it reports only BLOCKER/MAJOR findings and returns `READY` or `BLOCKED`.

## Main blocker areas from the owner-provided summary

1. **Baseline and role governance:** reconcile the base before creating a candidate; Viewer must fail closed and login defaults must not overwrite an existing membership’s role. The owner has directed gradual `platform_admin` retirement, separate from `opsadmin`; retirement eligibility and migration mechanics remain unresolved.
2. **Request and actor binding:** avoid mutable cross-request execution context; bind tools and selected cases/profiles server-side; derive staff actor identity from the authenticated principal; prevent internal events/data from reaching customer routes.
3. **Persistence and lifecycle:** resolve identity/FK assumptions and migration/rollback; prevent TTL cleanup from deleting unrelated pending handoffs; persist handoffs before acknowledging them; make resolve/re-handoff operate on the correct pending episode.
4. **AI and cache isolation:** prevent customer-profile/tool fallback for internal work; partition or bypass cache/checkpoint state by the approved identity/profile/case boundary; keep raw attachments out of model payloads by default.
5. **Business policy not yet approved:** exact assignment/timer/reopen/history mechanics; Staff's pending-order action scope; return/refund-state vocabulary and detailed JSONL schema/delivery contract; compatibility treatment for legacy cancellation routes; satisfaction-event privacy/retention and protected evidence rules.

This list is a summary of themes, **not a one-to-one reconstruction of the 9/6/3 finding register**. Use the original Argon report when it is added to the repository for exact finding IDs and dispositions.

## Current reconciliation notes

- Remote-check chronology: a separate local `git ls-remote` query from this documentation workflow failed to reach GitHub earlier, on 2026-10-28. Argon later reported a successful read-only GitHub `main` check at `2026-10-29T23:11:17+07:00`, returning `bbfd11d0ba4c13514a197a6b25802c4e217bedb3` (PR #47 merge). No remote query is recorded after that timestamp, so no claim is made about GitHub `main` after it; this evidence also does not prove deployment or runtime state. A clean managed worktree was prepared at that SHA for W0 docs; reverify remote `main` before any future candidate/readiness review. The original checkout remains a separate dirty `dd544800` checkout and is not the R1 implementation candidate.
- The owner-supplied corrected-path Opus review and Argon review assess different checkouts: Opus marks `dd544800` unsuitable as a W0 evidence base, while Argon marks the `bbfd11d0` W0 packet ready for owner decisions. The distinction and source-level deltas are recorded in the [W0 review reconciliation](W0_REVIEW_RECONCILIATION_2026-10-28.md). A fresh shell remote check in that reconciliation could not reach GitHub; verify `main` again before a later branch or release action.
- Opus identified a source-level Viewer/customer-ID sharing path that could expose a customer's read data. Actual DB rows remain unknown; include this relation in aggregate-only inventory before any Viewer migration.
- The owner reports EC2 is currently **OFF**. No AWS/SSM, database, Colab/L4 or live-runtime check was performed for this status note.
- Read-only static source inventory and the candidate contract-freeze snapshot are recorded in the [W0 baseline and decision register](W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md). No DB inventory, migration, application edit, or test was performed. OD-01–OD-04 have owner direction with detailed mechanics/semantics open; OD-05 is clarified but undecided, and OD-06–OD-08 remain open.

## Next gate

*(Historical 2026-10-29 note preserved for provenance:)* Before changing this status, resolve the OD-01 boundary, OD-03 timer/assignment/reopen/feedback mechanics, OD-04 Staff action scope/return transitions/audit-export mechanics, OD-05 endpoint compatibility, and OD-06–OD-08 policy details; complete the Viewer/platform_admin migration packets; freshly verify GitHub `main`; and prepare a clean candidate only when the owner authorizes it. A new implementation-readiness review must then be completed on that exact candidate and explicitly clear `BLOCKED` before W1–W6; a requested/pending review is not clearance. Documentation cleanup does not close any code finding.

### 2026-10-31 W0 closeout & W1-only authorization addendum

- **Owner policy & mechanics closed in W0:** [Owner delta §10](W0_OWNER_DECISION_DELTA_2026-10-29.md#10-final-owner-decisions-2026-10-31) and [accepted mechanics §11](W0_OWNER_DECISION_DELTA_2026-10-29.md#11-accepted-mechanics-2026-10-31) settled the OD-01 same-tenant Manager `/api/admin/*` boundary (plus `opsadmin` separation and `platform_admin` retirement), OD-02 Viewer fail-closed disablement, OD-03 3-minute inactivity + Continue same-`case_id` resume + 5-minute post-feedback completion timer, OD-04/OD-06 cancel/return/refund authority & vocabulary + JSONL outbox sink option A, OD-05 legacy cancellation compatibility facade, OD-07 identity/business v5 migration runbook, OD-08 evidence intake + Colab production target (gated on two-layer auth before live data), internal history partition `(tenant_id, principal_id, case_id)`, and strictly sequential delivery **`W0 → W1 → W2 → W3 → W4 → W5 → W6`**.
- **Read-only Git base check (2026-10-31):** `git ls-remote origin refs/heads/main` returned `bbfd11d0ba4c13514a197a6b25802c4e217bedb3`, matching local `HEAD`.
- **Bounded W1-only authorization (not `READY`):** On 2026-10-31 the owner explicitly authorized Gemini 4 Argon to close out W0 documentation and execute **only `W1`** (identity, RBAC, backend authorization, identity v5 migration code, and isolated W1 tests). This authorization does **not** constitute a new implementation-readiness review, does **not** change this document's verdict from `BLOCKED` to `READY`, and does **not** authorize `W2–W6`, live database access, production migration execution, EC2/SSM, Colab/LLM calls, commit, push, merge or deployment.

## Related current records

- [Canonical R1 design](README.md)
- [Historical owner decision snapshot](OWNER_DECISIONS_2026-10-28.md)
- [Latest W0 owner decision delta/proposals 2026-10-29](W0_OWNER_DECISION_DELTA_2026-10-29.md)
- [W0 baseline and decision register](W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md)
- [W0 review reconciliation](W0_REVIEW_RECONCILIATION_2026-10-28.md)
- [W0 read-only role inventory](W0_ROLE_INVENTORY_2026-10-29.md)
- [W0 contract freeze and gap register](W0_CONTRACT_FREEZE_AND_GAP_REGISTER_2026-10-29.md)
- [Archive index](archive/README.md) — completed reviews and retired prompts

## 2026-10-31 W1 implementation-readiness review — Codex

### Review target and limits

- **Target:** the current managed worktree `C:\Users\HP\.codex\worktrees\phase-r1-w0-docs\CSKH_ban_le`, branch `docs/phase-r1-w0-owner-decisions`, local `HEAD` `bbfd11d0ba4c13514a197a6b25802c4e217bedb3`, including the pre-existing dirty tree and Argon’s W1 changes. This is not an immutable clean candidate or a production release candidate.
- **Remote provenance:** the recorded Argon check on 2026-10-31 reported `origin/main` at the same SHA; a fresh `git ls-remote` during this review could not reach GitHub. No live database, EC2/SSM, Colab/LLM or customer data was accessed.
- **Scope:** one bounded review of W1 identity/RBAC/backend-authorization code and tests. This section does not authorize W2–W6 or change the overall readiness verdict.

### Verification run in this review

- `python -m unittest tests.test_r1_w1_identity_rbac -v` — **6/6 OK**.
- `python scripts/check_docs_contract.py` — **PASS** (dataset integrity, stale HEAD, links/Markdown and AST tool contract).
- `git diff --check -- retailops/ tests/` and `git diff --check -- docs/phase_role_aware_ops/` — **PASS**.
- `python -m unittest discover -s tests -q` — **727 tests, 67 skipped, 2 failures**: the known stale `notebooks/colab_agent.ipynb` artifact check, and an environment-sensitive Waitress headroom check (`GET /api/session` P99 `58.779 ms` > `50 ms`). These results do not clear the W1 gate.

### Verdict

**`BLOCKED` for claiming W1 complete/ready.** The implementation has several correct W1 controls, but the findings below leave an authorization boundary and two owner-governance boundaries unresolved. W2–W6 remain gated.

### Self-contained finding register

| ID | Severity | Finding | Evidence in this candidate | Required disposition |
|---|---|---|---|---|
| `W1-RB-01` | **BLOCKER** | Same-tenant Staff/Manager conversation object scope is still guessable. A Staff principal can `GET /api/staff/conversations/{uuid}/messages`, `POST /api/staff/reply` or `POST /api/staff/resolve` for an existing same-tenant conversation without an authorized active handoff/case binding. | `retailops/http/routes.py` around lines 395–406 and 490–511 checks existence, but not the selected case/active episode/holder. `BusinessStore.resolve_escalation()` still returns success when no matching handoff is present. A local synthetic reproduction returned HTTP `200` for reply, resolve and transcript on a non-escalated conversation belonging to another customer in the same tenant. | Deny guessed/non-authorized same-tenant objects; require an authorized `case_id`/handoff episode (or an explicitly approved transitional equivalent) for read/reply/resolve. Add negative tests for non-handoff, resolved, wrong-tenant and case-switching. If this is deferred to W2, W1 must not be reported complete. |
| `W1-RB-02` | **BLOCKER** | The direct tool executor is still too permissive for Manager. A Manager can call `/api/tools/execute` with a valid but un-escalated conversation ID and receive a result; role plus conversation existence is treated as sufficient. | `retailops/http/routes.py` around lines 518–575 only requires conversation binding; the `case_not_escalated` guard applies to Staff, not Manager. The new W1 test intentionally asserts HTTP `200` for Manager on an un-escalated conversation (`tests/test_r1_w1_identity_rbac.py` around lines 353–371), which conflicts with the frozen selected-case/direct-tool boundary in the R1 contract. | Until a durable case/profile boundary exists, deny this direct path for Manager or require the same server-authorized case/handoff binding. Change the test to prove fail-closed behavior; do not use role alone as a tool/object authorization boundary. |
| `W1-MIG-01` | **BLOCKER** | Identity v5 deactivation/session revocation is wired to ordinary store construction, so a normal application startup can perform the data migration without first running the accepted aggregate preflight, backup/restore rehearsal and explicit migration operation. The owner authorized writing migration code, not automatic live execution. | `IdentityStore.__init__()` calls `migrate(...)` and then `upgrade_memberships_role_constraint()` (`retailops/identity/store.py` around lines 557–581); `PostgresIdentityStore.__init__(migrate=True)` upgrades schemas and then deletes legacy sessions/deactivates memberships in constructor transactions (`retailops/storage/pg_repositories.py` around lines 43–83; `retailops/storage/pg_schema.py` around lines 353–376). The accepted runbook in owner delta §11.5 requires freeze, aggregate-only preflight, backup/scratch restore and controlled forward migration. | Separate schema/data migration execution from normal serving startup, or provide an explicit deployment gate that cannot run until the owner-approved preflight/backup evidence is supplied. Keep migration code/tests local; no production execution is authorized in this review. Test that ordinary startup does not silently retire legacy memberships or revoke sessions before the approved migration step. |
| `W1-ID-01` | **BLOCKER** | First-time Google-login provisioning policy is still owner-gated. Current code can provision a brand-new account as `staff`/`manager` from verified-email environment allowlists, while the owner’s stated direction introduces an external account/role import as the system input and the readiness record explicitly says not to invent this policy in W1. | `retailops/http/auth_google.py:193–223`, `retailops/http/public.py:163–181`, and `retailops/identity/store.py:833+` still accept allowlist-derived roles for a new membership; only existing memberships are protected from overwrite (`google_role_sync_ignored`). | Owner must choose and record the source of truth. Recommended transition: external import/provisioning creates the membership and role; Google login only binds to that provisioned membership; env allowlists are temporary migration-only with an explicit end date. Add tests for unprovisioned, imported and deprovisioned accounts. |
| `W1-ID-02` | **BLOCKER** | The authoritative role-change channel is not governed. The CLI `identity set-role` changes a membership, bumps `auth_version`, revokes sessions and writes an audit row, but there is no approved import/provisioning contract or operator-authentication boundary; the code therefore leaves CLI, Google-first-login allowlists and a future import path as competing authorities. | `retailops/identity/cli.py:48–51` and `retailops/identity/store.py:709–745`; the audit actor is hard-coded as `operator_cli`. No import/provisioning module exists in the W1 diff, and no `/api/admin/*` role-change route is present. | Owner must declare the channel. Recommended model: import/provisioning is the normal authority; CLI is break-glass/migration only, with explicit operator control, audit, session invalidation and rollback. Google login never changes an existing role; OpsConsole remains read-only unless its boundary is explicitly changed. |

#### Ghi chú không chặn (không thuộc register severity)

> **Phân loại lại 2026-10-31:** `W1-AUD-01` được chuyển ra khỏi register severity ở trên và không phải gate của W1. Lý do: actor identity (`principal_id`, `role`, `tenant_id`, `membership_id`) đã được lấy từ session và lưu tách riêng trong `actor`; `staff_name` do client gửi bị bỏ qua; nhãn fallback chỉ là nhãn vai trò chung, không phải tên người hay tên demo, và không tham gia authorization hay audit actor. Đánh giá chi tiết nằm trong [docs review addendum](#2026-10-31-w1-docs-review-addendum). Nội dung gốc của Codex bên dưới được giữ nguyên văn để truy vết, kể cả nhãn `MAJOR` lúc đầu.

| ID | Phân loại gốc (Codex, lịch sử) | Finding | Evidence in this candidate | Required disposition |
|---|---|---|---|---|
| `W1-AUD-01` | **MAJOR** | When no trusted display name exists, W1 synthesizes and persists the generic label `Nhân viên hỗ trợ` as `staff_name`. The actor principal is server-derived, but the persisted/displayed name still looks like an invented identity rather than an empty/null trusted display name. | `retailops/http/routes.py:177–181, 492–506` and `retailops/business/store.py:1643–1646, 1771–1773`. The W1 test covers `/api/session`/`/api/profile` blank names but not blank-name Staff reply/resolve. | Keep actor identity separate from display label; use empty/null or an explicitly non-identity UI label, and add a blank-display-name reply/resolve test. Do not restore a person/demo name. |

### What passed and what did not

The following W1 controls are present and covered by the targeted tests: immutable per-request `RequestContext` with no `Application.current_binding`; three active business roles with fail-closed `viewer`/`platform_admin`; same-tenant Manager admin scope and last-active-Manager guard; server-derived audit actor with client `staff_name` ignored; existing Google membership role not overwritten and privileged allowlists requiring verified email; direct-tool tenant/object checks for the Staff path; and isolated identity-v5 SQLite/PostgreSQL/snapshot migration checks.

Those controls are **not sufficient for a `READY` verdict** while `W1-RB-01`, `W1-RB-02`, `W1-MIG-01`, `W1-ID-01` and `W1-ID-02` remain unresolved. The next action is a bounded W1 correction/owner-policy decision only; do not start W2 or run a live migration.

### 2026-10-31 W1 docs review addendum

> **Phạm vi:** một lượt review tài liệu có giới hạn (Claude Opus). Lượt này đối chiếu các trang R1 hiện hành với bằng chứng W1 trong cùng worktree: branch `docs/phase-r1-w0-owner-decisions`, `HEAD` `bbfd11d0ba4c13514a197a6b25802c4e217bedb3`, cộng các thay đổi chưa commit. Code và test chỉ được đọc, không sửa. Không chạy migration; không truy cập DB thật, EC2/SSM, Colab/ngrok hay dữ liệu khách hàng; không commit hay push. Addendum này **không** đổi verdict và **không** mở vòng review mới. Thay đổi duy nhất với register ở trên: `W1-AUD-01` được chuyển sang mục ghi chú không chặn, nội dung gốc giữ nguyên văn. Năm finding BLOCKER còn lại giữ nguyên.

**Trạng thái hiện hành:**

| Hạng mục | Trạng thái |
|---|---|
| W0 | Đã đóng phần tài liệu theo quyết định owner ([§10](W0_OWNER_DECISION_DELTA_2026-10-29.md#10-final-owner-decisions-2026-10-31)/[§11](W0_OWNER_DECISION_DELTA_2026-10-29.md#11-accepted-mechanics-2026-10-31)). |
| W1 | Đã thực thi trong worktree (code + test cô lập). Review W1 kết luận `BLOCKED`, nên W1 **chưa hoàn tất và chưa READY**. |
| Readiness tổng thể | `BLOCKED`. |
| `W2–W6`, migration trên DB thật, runtime, deploy, commit, push, merge | **Không được phép.** |

**Xác minh finding register (đọc source tĩnh + test mục tiêu; số dòng là xấp xỉ trong dirty tree):**

| ID | Kết quả | Bằng chứng bổ sung / ghi chú |
|---|---|---|
| `W1-RB-01` | Xác nhận | `retailops/http/routes.py` 395–406 (Staff đọc transcript: chỉ kiểm tra conversation tồn tại), 490–500 (reply), 501–511 (resolve). `BusinessStore.resolve_escalation()` (`retailops/business/store.py` khoảng 1771–1798) đổi mọi row `human_handoff` của conversation và luôn trả `resolved: True`, kể cả khi không có handoff nào. Không thấy bằng chứng cross-tenant; đây là object scope trong cùng tenant. |
| `W1-RB-02` | Xác nhận | `routes.py` 570–580: guard `case_not_escalated` chỉ áp dụng khi `ctx.role == 'staff'`. `tests/test_r1_w1_identity_rbac.py` khoảng 353–371 khẳng định Manager nhận HTTP `200`. Chạy lại test mục tiêu vẫn `6/6 OK`, nghĩa là bộ test hiện đang khóa đúng hành vi cần đổi. |
| `W1-MIG-01` | Xác nhận, phạm vi rộng hơn | Ngoài `IdentityStore.__init__()` (`retailops/identity/store.py` 558–577) và `PostgresIdentityStore.__init__(migrate=True)` (`retailops/storage/pg_repositories.py` 43–83): `PersistentSessions`/`PostgresSessions` mặc định `maintenance=True` (`retailops/identity/persistent.py` 55–72; `retailops/identity/postgres.py` 13–22). Các lớp này được tạo khi startup public (`retailops/bootstrap.py` 23–32) và khi chạy CLI `identity` (`retailops/identity/cli.py` khoảng 64–70). Vì vậy **code có thể thực thi** data migration identity v5 (xóa session, vô hiệu hóa `viewer`/`platform_admin`) ngay khi khởi động bình thường, hoặc khi chạy bất kỳ lệnh CLI identity nào, kể cả `set-role`. Điều này mâu thuẫn với trình tự freeze → preflight tổng hợp → backup/restore rehearsal → forward migration có kiểm soát trong [§11.5](W0_OWNER_DECISION_DELTA_2026-10-29.md#115-migration-runbook-od-07). Addendum chỉ ghi nhận khả năng của code; **không** khẳng định migration đã chạy trên production hay trên bất kỳ DB thật nào. |
| `W1-ID-01` | Xác nhận, thêm chi tiết | `retailops/http/auth_google.py` 193–223: `DEFAULT_ROLE` chấp nhận mọi role thuộc `ACTIVE_BUSINESS_ROLES`, kể cả `staff`/`manager`. Nếu đặt như vậy, mọi tài khoản Google mới không có trong allowlist đều nhận role đặc quyền. Ở chế độ non-live, cả email chưa xác minh cũng nhận role này, vì nhánh `not email_verified` trả về `default_role`. Guard "allowlist đặc quyền chỉ áp dụng cho email đã xác minh" do đó không bao phủ trường hợp `DEFAULT_ROLE` đặc quyền. Owner đã nêu hướng cấp tài khoản/role từ hệ thống ngoài, nhưng chưa có hợp đồng provisioning được chốt. |
| `W1-ID-02` | Xác nhận, thêm chi tiết | `IdentityStore.set_role()` (`retailops/identity/store.py` khoảng 709–745) không yêu cầu `active=1` và xóa marker `retired_legacy_role_r1_w1`. `admin_reactivate_account()` (khoảng 1597–1640) từ chối role legacy, nhưng thông báo lỗi hướng dẫn "cập nhật sang vai trò hợp lệ trước khi kích hoạt lại". Ghép hai bước, CLI `set-role` rồi Manager reactivate tạo ra một đường đưa membership `platform_admin`/`viewer` đã retire trở thành `manager`/`staff` đang hoạt động, mà không có gate eligibility do owner duyệt (đối chiếu [historical owner snapshot §1.1](OWNER_DECISIONS_2026-10-28.md) và addendum "forbid new provisioning/reactivation" trong [role inventory](W0_ROLE_INVENTORY_2026-10-29.md)). Audit actor cố định `operator_cli` không định danh người vận hành. |

Register severity của W1 gồm đúng năm BLOCKER ở trên. `W1-AUD-01` không thuộc register này (xem ghi chú bên dưới).

**Ghi chú không chặn — `W1-AUD-01` (nhãn hiển thị khi thiếu display name):** hành vi đã được xác nhận trên code. Actor identity (`principal_id`, `role`, `tenant_id`, `membership_id`) được lấy từ session và lưu riêng trong `actor`; `staff_name` do client gửi bị bỏ qua (`routes.py` 177–181 và 490–511; có test anti-spoofing). `Nhân viên hỗ trợ`/`Quản lý cửa hàng` là nhãn vai trò chung, không phải tên người hay tên demo kiểu `Mai Anh`, và không tham gia authorization hay audit actor. Vì vậy đây là **ghi chú không chặn**: không phải MAJOR, không phải gate của W1, và không cần xử lý trước khi tuyên bố W1 hoàn tất. Ghi chú này phải được nâng lên finding có severity nếu xuất hiện một trong hai điều kiện: (a) có consumer audit/export dùng `staff_name` làm actor; hoặc (b) owner yêu cầu `null` thay cho nhãn vai trò chung. Rủi ro còn lại: nhãn đang được lưu vào trường mang tên `staff_name`, nên người đọc event có thể hiểu nhầm đó là định danh. Khuyến nghị (không bắt buộc): lưu `null` (hoặc một trường `display_label` tách riêng) và để UI hiển thị nhãn, đồng thời thêm test reply/resolve với display name rỗng. Câu hỏi cho owner về nhãn hiển thị là câu hỏi làm rõ, không chặn W1.

**Khoảng trống cùng phạm vi đã nêu ở dòng 010 của [W1 log](W1_EXECUTION_LOG_2026-10-31.md), chưa đánh số:** `/api/events` bỏ qua sanitizer với role có `STAFF` (`routes.py` 380–383); `/api/staff/escalations` chưa có case scope (`routes.py` 390–392). Đây là ghi nhận, không phải gate của W1 và nằm ngoài phạm vi remediation W1. Không suy diễn rằng có rò rỉ cross-tenant.

**Chính sách còn chờ owner quyết định:**

1. Nguồn có thẩm quyền cấp membership/role cho tài khoản mới, gồm cả `DEFAULT_ROLE` (`W1-ID-01`).
2. Kênh có thẩm quyền đổi role của membership hiện hữu, và cách xử lý membership legacy đã retire (`W1-ID-02`).
3. Nếu durable case chỉ có từ W2: một tương đương chuyển tiếp nào được chấp nhận cho object binding của `W1-RB-01`/`W1-RB-02`. Nếu không chọn được, W1 không được báo cáo là hoàn tất.

Việc tách migration identity v5 khỏi startup/CLI bình thường (`W1-MIG-01`) là sửa cơ chế để khớp runbook §11.5 đã được chấp nhận, không phải câu hỏi chính sách mới.

**Bước tiếp theo (owner phát hành 2026-10-31):** Argon thực hiện remediation đúng 5 BLOCKER theo [W1 remediation handoff](W1_REMEDIATION_HANDOFF_2026-10-31.md), trong phạm vi ủy quyền W1-only. Verdict vẫn `BLOCKED` cho tới khi có lượt kiểm chứng duy nhất được mô tả trong handoff và owner ghi nhận quyết định chính sách cho `W1-ID-01`/`W1-ID-02`.

**Khuyến nghị (chờ owner chốt, không phải quyết định owner):**

- Import/provisioning từ hệ thống ngoài là kênh thường lệ để tạo membership và gán hoặc đổi role.
- CLI `set-role` chỉ dùng cho break-glass/migration: operator được định danh, ghi audit, thu hồi session; cấm map membership legacy đã retire nếu không có danh sách eligibility do owner duyệt.
- Google login chỉ bind vào membership đã được provision. Google login không đổi role của membership hiện hữu và không tự cấp role đặc quyền; `DEFAULT_ROLE` chỉ nên cho phép `customer`, hoặc từ chối membership chưa được provision.
- Env allowlist chỉ là cơ chế chuyển tiếp, có ngày kết thúc rõ ràng.
- OpsConsole (`opsadmin`) vẫn read-only đúng như tài liệu hiện mô tả; addendum này không biến nó thành nơi ghi role.

**Kiểm tra trong lượt này và giới hạn:**

- `python -m unittest tests.test_r1_w1_identity_rbac` → `6/6 OK` (chạy cục bộ; không đụng DB thật).
- `python scripts/check_docs_contract.py` và `git diff --check` (whitespace của các tài liệu đã sửa): kết quả được báo cáo riêng cùng patch này.
- Không chạy full test suite, không tái hiện lại HTTP động cho `W1-RB-01` (dựa vào source tĩnh và bản tái hiện tổng hợp đã ghi ở trên), không truy vấn GitHub remote, không kiểm tra DB, EC2 hay Colab.
- Mục "Review target" ở trên có chứa đường dẫn máy cục bộ. Mục này được giữ nguyên vì không thuộc phạm vi của lượt này.

### 2026-10-31 W1 remediation verification

> **Phạm vi:** đây là lượt kiểm chứng **duy nhất** theo mục 6 của [W1 remediation handoff](W1_REMEDIATION_HANDOFF_2026-10-31.md). Lượt này chỉ đối chiếu 5 tiêu chí chấp nhận với diff của Argon và kết quả test; không mở finding mới. Diff được so với bản chụp worktree ngay trước khi remediation. Không sửa code/test, không truy cập DB thật, EC2/SSM hay Colab, không commit/push. Argon đã ghi tiến độ ở dòng `011` của [W1 log](W1_EXECUTION_LOG_2026-10-31.md).

**Verdict tổng thể: vẫn `BLOCKED`.** Năm tiêu chí kỹ thuật đã đạt. W1 chưa hoàn tất vì hai quyết định chính sách của owner (`W1-ID-01`, `W1-ID-02`) chưa được ghi nhận. Verdict chỉ được đổi khi owner đồng ý.

| ID | Kết quả kiểm chứng | Bằng chứng |
|---|---|---|
| `W1-RB-01` | **Đạt** | Helper `_require_open_handoff_conversation` (`retailops/http/routes.py`) được áp cho transcript (cả hai đường dẫn), reply và resolve, với cả Staff và Manager. `BusinessStore.staff_reply()`/`resolve_escalation()` kiểm tra lại handoff đang mở; resolve khi không có handoff mở trả `409`, không ghi gì và không trả `resolved: true`. Test `test_staff_and_manager_handoff_episode_object_scope_w1_rb_01` phủ: không có handoff, handoff đã resolved, gọi trên conversation khác, conversation không tồn tại, tenant khác; và xác nhận số turn/event không đổi. |
| `W1-RB-02` | **Đạt** | Guard `case_not_escalated` ở `/api/tools/execute` áp cho mọi role; test cũ cho Manager nhận `200` đã đổi sang kỳ vọng `403`; Manager trên handoff đang mở vẫn nhận `200`. |
| `W1-MIG-01` | **Đạt** | Data step v5 đã được gỡ khỏi `IdentityStore`/`PostgresIdentityStore`. Startup, `PersistentSessions` và CLI thường chỉ kiểm tra read-only và fail-closed với `503 identity_migration_required` khi gặp DB chưa v5; DB rỗng được tạo thẳng v5. Upgrade chỉ chạy qua `identity migrate-v5 --confirm-preflight --confirm-backup` và idempotent. Test xác nhận dữ liệu v4 không đổi một byte sau các lần startup/CLI bị chặn. |
| `W1-ID-01` | **Đạt (guard)** | `DEFAULT_ROLE` khác `customer` → `403 invalid_default_role`; email chưa xác minh luôn nhận `customer`; có thêm guard phòng thủ trong `get_or_create_google_member`. Allowlist hiện có giữ nguyên. |
| `W1-ID-02` | **Đạt (guard)** | `set_role` và `admin_reactivate_account` từ chối membership legacy hoặc có marker `retired_legacy_role_r1_w1` (`409 legacy_role_retired`) và không xóa marker; `set-role` trên membership hợp lệ vẫn bump `auth_version`, thu hồi session và ghi audit. |

**Kiểm tra đã chạy lại:**

- `python -m unittest tests.test_r1_w1_identity_rbac` → `7/7 OK`.
- 11 suite liên quan (`test_persistent_identity`, `test_phase5_google_identity`, `test_auth_google`, `test_staff_desk`, `test_manager_crud`, `test_schema_migration`, `test_postgres`, `test_release_source_consistency`, `test_phase5_e_ai_trust_and_governance`, `test_pr_a_correctness`, `test_phase5_fix_a`) → `201` test `OK`, `40` skip.
- `python scripts/check_docs_contract.py` → `PASS`; `git diff --check -- retailops/ tests/` → sạch.
- Ba file test cũ chỉ được thêm bước gọi migrate tường minh và một assertion fail-closed; không có assertion nào bị bỏ hay nới lỏng.

**Giới hạn (không phải finding mới):**

- 40 test PostgreSQL bị skip vì không có DB test; đường PostgreSQL mới chỉ được kiểm bằng mock. Lệnh `migrate-v5` cần được diễn tập trên một bản restore trước khi dùng thật, đúng như §11.5.
- `--confirm-preflight`/`--confirm-backup` là xác nhận tự khai của operator, không kèm bằng chứng.
- Hệ quả vận hành: khi deploy bản này lên một DB đang ở schema dưới v5, app sẽ từ chối khởi động cho tới khi operator chạy migration có kiểm soát. Việc deploy và migration trên DB thật vẫn **không được phép** nếu owner chưa phê duyệt riêng.

**Còn lại để đóng W1:** owner ghi nhận quyết định cho hai câu hỏi ở mục 3 của handoff (nguồn cấp role cho tài khoản mới; kênh đổi role và định danh operator CLI). Nếu quyết định đó đòi hỏi thêm code, chỉ làm đúng phần đó trong phạm vi W1.

### 2026-10-31 W1 owner policy decisions and closure status

> **Phạm vi:** ghi nhận quyết định của owner cho `W1-ID-01`/`W1-ID-02` và trạng thái đóng W1. Các mục ngày 2026-10-31 phía trên được giữ nguyên như bản ghi tại thời điểm viết; mục này cập nhật trạng thái mới nhất.

**Quyết định của owner** (chi tiết ở [owner delta §12](W0_OWNER_DECISION_DELTA_2026-10-29.md#12-w1-policy-decisions-2026-10-31)):

- `W1-ID-01`: giữ allowlist trong biến môi trường (chỉ cho email đã xác minh) làm kênh chuyển tiếp để cấp `staff`/`manager` cho tài khoản mới; `DEFAULT_ROLE` chỉ được là `customer`.
- `W1-ID-02`: chỉ đổi role của membership hiện hữu bằng CLI `identity set-role` chạy qua AWS SSM. Người thực hiện được định danh bằng IAM principal trong log SSM/CloudTrail.

Cả hai quyết định dùng đúng hành vi code đã được kiểm chứng ở mục trên, nên **không cần code mới** trong W1.

**Trạng thái 5 BLOCKER của W1:**

| ID | Trạng thái |
|---|---|
| `W1-RB-01`, `W1-RB-02`, `W1-MIG-01` | Đã đóng bằng remediation đã kiểm chứng. |
| `W1-ID-01`, `W1-ID-02` | Đã đóng: guard fail-closed đã được kiểm chứng, và chính sách đã được owner quyết định. |

**Kết luận:** W1 không còn blocker mở. **Owner đã xác nhận đóng W1 ngày 2026-10-31: W1 hoàn tất** trong phạm vi ủy quyền W1-only. Đây không phải trạng thái `READY` cho `W2–W6`. Readiness tổng thể vẫn **`BLOCKED`**: `W2–W6` chỉ bắt đầu sau readiness review duy nhất trên candidate, như ở mục "Next gate".

**Điều kiện vận hành (không phải gate của W1):**

- Owner xác nhận đã bật log phiên SSM và CloudTrail, trước khi dùng các log đó làm bằng chứng audit cho việc đổi role hoặc sửa allowlist.
- Diễn tập `identity migrate-v5` trên một bản restore PostgreSQL trước mọi migration trên DB thật. Migration và deploy trên DB thật vẫn cần owner phê duyệt riêng.

### 2026-11-01 W1 production deploy record

- **Merged:** PR #48 (W1, `d6ed95e`), PR #49 (live E2E dùng staff thay viewer, `f21b0c2`), PR #50 (UI bỏ danh tính "Mai Anh" viết cứng, `f6620aa`).
- **Migration identity v5 trên DB production** theo runbook §11.5: preflight tổng hợp (identity v4; 4 `viewer` đều đã `active=0`; không có `platform_admin`; 0 session đang mở), backup `pre-w1-20261101T115705.dump` và `final-pre-w1-20261101T121356.dump`, diễn tập trên DB tạm (v4 → v5, chạy lại idempotent, W1 khởi động được), rồi `identity migrate-v5` trên DB thật (`upgraded: true`; 4 `viewer` được gắn `retired_legacy_role_r1_w1`; các role khác không đổi).
- **Rollout:** image `sha256:0eba8bb7ddf7da7d9cf15b60193e9d9578afbca928bf3b57afc7c2b828a16f76`; `PUBLIC_WEB_ROLLOUT_OK`, `ADMIN_CONSOLE_SMOKE_OK`, `LIVE_E2E_SMOKE_OK`; gián đoạn khoảng 4 phút. Lần chạy workflow `41304375458` đỏ có chủ đích (đưa image lên EC2 trước khi migrate, tự rollback). Sau khi merge PR #50, deploy tự động lúc 12:48 UTC thành công.
- **Vận hành:** không chạy `scripts/update_ec2.py` (ghép mã ngoài image và ghi đè constraint role v5); endpoint model chỉ sửa `RETAILOPS_API_ENDPOINT` trong `api.env` rồi tạo lại riêng `web`.

### 2026-11-01 W2 readiness review

> **Phạm vi:** một lượt readiness review duy nhất cho W2, chỉ BLOCKER/MAJOR. Đối chiếu §10/§11 và README W2 với code trên `main` (`f6620aa`).

**Finding đã được owner đóng bằng [§13](W0_OWNER_DECISION_DELTA_2026-10-29.md#13-w2-owner-decisions-2026-11-01):**

| ID | Mức | Vấn đề | Đóng bằng |
|---|---|---|---|
| `W2-RR-01` | BLOCKER | Chưa rõ case được tạo cho mọi hội thoại hay chỉ khi cần người; quyết định phạm vi timer, phản hồi và nội dung Staff Desk | W2-D1 |
| `W2-RR-02` | MAJOR | Nhóm Đã xử lý có trong UI nhưng quyền xem transcript ca đã đóng chưa được duyệt | W2-D2 |
| `W2-RR-03` | MAJOR | §11.5 gộp bảng W3 vào business v5, buộc đóng băng thiết kế W3 sớm | W2-D3 |
| `W2-RR-04` | MAJOR | Chưa chọn nơi chạy timer | W2-D4 |
| `W2-RR-05` | MAJOR | Owner muốn thêm tin nhắc trước khi đóng ca | W2-D5 |

**Hiện trạng code W2 phải xử lý** (không cần thêm quyết định): handoff chỉ là một dòng `conversation_feedback` với `reason_code` tự do; danh sách escalation không lọc ca đã đóng; `new_conversation()` xóa hội thoại quá 7 ngày trên toàn tenant và cascade sang handoff đang chờ; UI báo "đã kết nối" trước khi handoff được lưu; ba đường tạo handoff (`/api/feedback`, `customer_message()`, tool `request_human_support` còn trả `support_rep` viết cứng); business store tự migrate khi khởi tạo (SQLite đích v3, PostgreSQL đích v4).

**Kết luận:** W2 **READY** để thực thi theo [W2 execution handoff](W2_EXECUTION_HANDOFF_2026-11-01.md) do owner phát hành. Readiness tổng thể vẫn `BLOCKED` cho `W3–W6`. Migration business v5 và deploy W2 trên production cần owner phê duyệt riêng, theo runbook như W1.

### 2026-11-02 W2 production deploy record

- **Merged:** PR #51 (W2, merge `3ded146`; gồm cả bản sửa `5a8ee46` thêm `RETAILOPS_ENV: production` vào `deploy/compose.postgres.yaml` để chặn rút ngắn timer có hiệu lực trên EC2).
- **Migration business v5 trên DB production**, cùng mô hình W1:
  - Preflight chỉ đọc: identity v5; cả 37 tenant ở business v4, chưa có bảng `cases`; tổng 70 hội thoại, 4 hội thoại có handoff mở, 7 dòng `conversation_feedback`.
  - Backup: `pre-w2-20261102T070102.dump` (đọc lại được 652 mục dữ liệu bảng) và `final-pre-w2-20261102T072142.dump` (sau khi dừng `web`).
  - Diễn tập trên DB tạm restore từ backup: lần chạy đầu tạo 70 case và 4 episode; chạy lại không đổi gì (0/0); W2 khởi động được trên v5.
  - `database migrate-v5 --confirm-preflight --confirm-backup` trên DB thật cho kết quả giống hệt diễn tập: 37 tenant lên v5; 70 case, gồm 4 `waiting` và 66 `resolved` với `migrated_v5`; 4 episode `pending`; 7 dòng phản hồi cũ giữ nguyên.
- **Rollout:** image `sha256:285d4f8ddf48ff435ed7d0557cb4258a3634470c9d48aebcbb4d74d4abee31e6`; `PUBLIC_WEB_ROLLOUT_OK` (có `PUBLIC_WEB_SOURCE_MATCH`), `ADMIN_CONSOLE_SMOKE_OK`, `LIVE_E2E_SMOKE_OK`; gián đoạn khoảng 5 phút. Lần chạy workflow `41403725350` đỏ có chủ đích: đưa image lên EC2 trước khi migrate, rồi tự rollback về `88f139e6`. Owner đã kiểm thử trên trình duyệt và xác nhận đạt.
- **Vận hành:** deploy thường (`rollout-public-web.sh`) không cập nhật `/opt/retailops/compose.postgres.yaml`; file này đã được thay bằng bản trong image (khác đúng một dòng `RETAILOPS_ENV: production`), và container `web` xác nhận `RETAILOPS_ENV=production`. `RETAILOPS_DEPLOY_ENABLED` để `false` sau deploy. Readiness tổng thể vẫn `BLOCKED` cho `W3–W6`.

### 2026-11-02 W3 readiness review

> **Phạm vi:** một lượt readiness review duy nhất cho W3, chỉ BLOCKER/MAJOR. Đối chiếu §10 (OD-04/05/06), §11.4, §11.6 và README W3 với code trên `main` (`3ded146`).

**Finding đã được owner đóng bằng [§14](W0_OWNER_DECISION_DELTA_2026-10-29.md#14-w3-owner-decisions-2026-11-02):**

| ID | Mức | Vấn đề | Đóng bằng |
|---|---|---|---|
| `W3-RR-01` | BLOCKER | Chưa rõ W3 làm tới bước nào của vòng đời trả hàng; ai ghi `received`/`inspected` và kết quả kiểm tra là gì | W3-D2 |
| `W3-RR-02` | BLOCKER | §11.6 bắt buộc quét mã độc nhưng hệ thống chưa có máy quét; chưa chọn phạm vi bằng chứng | W3-D4 |
| `W3-RR-03` | MAJOR | Đổi hàng (đổi size, đổi 1-1) chưa thuộc loại yêu cầu nào; UI đang dùng hai nút soạn sẵn gửi cùng một câu | W3-D1 |
| `W3-RR-04` | MAJOR | Chưa có hệ thống nào là nguồn đúng cho `refunded` (không có cổng thanh toán) | W3-D3 |
| `W3-RR-05` | MAJOR | Bảng `orders` không có ngày giao, nên server không kiểm được hạn đổi trả | W3-D6 |
| `W3-RR-06` | MAJOR | Chưa rõ yêu cầu hiện ra cho nhân viên ở đâu và ai được duyệt | W3-D5 |
| `W3-RR-07` | MAJOR | §11.5 bước 5 đổi đề xuất hủy chưa xác nhận thành yêu cầu, tức là gửi thay khách | W3-D9 |

**Hiện trạng code W3 phải xử lý** (không cần thêm quyết định): `confirm` của `/api/cancellation-proposals*` đổi `orders.status` thành `cancelled` ngay; route đổi trạng thái của Manager không kiểm version, không ghi ngày giao; chưa có bảng yêu cầu, quyết định, bằng chứng hay outbox; dependency chưa có thư viện xử lý ảnh; live E2E đang kiểm hành vi hủy ngay. Owner cũng báo nút "Gửi phản hồi trực tiếp" trên production bấm không có tác dụng, và bố cục nút Staff Desk bị vỡ; cả hai đưa vào W3 theo W3-D10.

**Kết luận:** W3 **READY** để thực thi theo [W3 execution handoff](W3_EXECUTION_HANDOFF_2026-11-02.md) do owner phát hành. Readiness tổng thể vẫn `BLOCKED` cho `W4–W6`. Migration business v6 và deploy W3 trên production cần owner phê duyệt riêng, theo runbook như W2.

### 2026-11-02 W3 production deploy record

- **Merged:** PR #52 (W3, merge `2443416`) và PR #53 (`1075091`): workflow deploy cài thêm `requirements-web.txt` trước khi chạy test. Lần chạy `41434718647` đỏ ở bước test vì thiếu Pillow, trước khi build image; EC2 không bị đụng tới.
- **Migration business v6 trên DB production**, cùng mô hình W2:
  - Preflight chỉ đọc: identity v5; 38 tenant ở business v5; 464 đơn (273 `pending`); 6 đề xuất hủy, không có đề xuất `pending`; 74 case; `/data` ghi được.
  - Backup: `pre-w3-20261102T110945.dump` (852 mục dữ liệu bảng) và `final-pre-w3-20261102T114445.dump` (sau khi dừng `web`).
  - Diễn tập trên DB tạm: lần đầu `upgraded: True`, chạy lại `False`; W3 khởi động được trên v6.
  - `database migrate-v6` trên DB thật cho kết quả giống diễn tập: 38 tenant lên v6; 152 bảng mới; 38 cột `orders.delivered_at`; số đơn, đề xuất và case không đổi.
- **Rollout:** image `sha256:7975e9478f22418ea74488a6a531b9081e37cd616345e8d9470330bd9a1db3c1`; `PUBLIC_WEB_ROLLOUT_OK` (có `PUBLIC_WEB_SOURCE_MATCH`), `ADMIN_CONSOLE_SMOKE_OK`, `LIVE_E2E_SMOKE_OK`; outbox 0 `pending`, 0 `dead`; gián đoạn khoảng 6 phút. Lần chạy `41437516820` đỏ có chủ đích và tự rollback về W2.
- **Kiểm thử của owner trên trình duyệt** phát hiện các khoảng trống nghiệp vụ và hiển thị, xử lý trong [W3.1](W3_1_EXECUTION_HANDOFF_2026-11-02.md) theo [§15](W0_OWNER_DECISION_DELTA_2026-10-29.md#15-w31-owner-decisions-2026-11-02): nhân viên không có cách tạo yêu cầu khi khách đang chat trực tiếp; ca có người giữ không có tín hiệu khi khách im lặng; các mốc của ca mất khi tải lại trang; CSP chặn `style="..."` nên một số phần tử lẽ ra ẩn vẫn hiện ở trang khách.

### 2026-11-02 W3.1 verification and W3.2 readiness review

**W3.1 (PR #54, head `9c8bc40`):** một lượt kiểm chứng theo 6 tiêu chí, **đạt**. CI 5/5 xanh; commit docs khớp patch; không đổi schema hay migration; 42 test W2–W3.1, các contract và test JS (Node thật) chạy lại cục bộ đều PASS. Kiểm tra tin đồng ý đúng tiêu chí (tin của chính khách, đúng hội thoại, đúng lần mở ca, trong 30 phút, người giữ ca hoặc Manager).

**W3.2 — finding từ kiểm thử của owner trên production (W3):**

| ID | Mức | Vấn đề | Đóng bằng |
|---|---|---|---|
| `W3.2-RR-01` | BLOCKER | Khách hỏi "đổi size… O-819125" (đơn `pending`), AI trả câu soạn sẵn "đổi size tận nhà miễn phí 2 chiều" từ nhánh từ khóa trong `dispute_agent`: không kiểm điều kiện đơn, không qua `prepare_order_action`, tự hứa chính sách không trích dẫn | W3.2-D3, W3.2-D7 |
| `W3.2-RR-02` | MAJOR | Câu hỏi tiếp nối "hiện có những size nào" bị định tuyến sang agent trò chuyện chung (`witty_general_fallback`) vì định tuyến chỉ dò từ khóa ở tin cuối; lời gọi model sau đó thất bại (0 token) và trả 503 | W3.2-D3, W3.2-D8 |
| `W3.2-RR-03` | MAJOR | Đổi hàng chỉ có `size`/`one_to_one` (khóa bằng CHECK trong DB); không đổi màu/kiểu được; lý do là danh sách riêng theo loại | W3.2-D1, W3.2-D2, W3.2-D4, W3.2-D6 |
| `W3.2-RR-04` | MAJOR | Model đã bật native tool-calling và thinking trên vLLM nhưng app không tận dụng: định tuyến theo từ khóa, mỗi worker chỉ thấy vài tool, câu trả lời của model bị thay bằng câu soạn sẵn, trần 4 lượt model quá thấp cho chuỗi nhiều bước | W3.2-D9 đến W3.2-D12 |

**Kết luận:** W3.2 **READY** để thực thi theo [W3.2 execution handoff](W3_2_EXECUTION_HANDOFF_2026-11-02.md) sau khi W3.1 được merge. Readiness tổng thể vẫn `BLOCKED` cho `W4–W6` (trừ phần AI W3.2 kéo lên). Migration business v7 và deploy cần owner duyệt riêng, theo runbook như W3.

### 2026-11-03 W3.2 production deploy record and incident

**Merged:** PR #55 (W3.2, merge `12b4b24`), PR #56 (`6ec6c43`: `/healthz` kiểm tra danh mục lý do, image bắt buộc có `data/order_action_reasons.json`) và PR #57 (`92db18d`: rollout dừng khi còn mount `/opt/retailops/patches`).

**Migration business v7 trên DB production**, cùng mô hình W3:
- Preflight chỉ đọc: identity v5; 41 tenant ở business v6; 509 đơn; 0 yêu cầu đơn hàng; `/data` ghi được.
- Backup: `pre-w32-20261103T124846.dump` (đọc lại được 1082 mục dữ liệu bảng) và `final-pre-w32-20261103T125531.dump` (sau khi dừng `web`).
- Diễn tập trên DB tạm: lần đầu `upgraded: True`, chạy lại `False`; 41 cột `target_variant_id`; W3.2 khởi động được trên v7.
- `database migrate-v7` trên DB thật: 41 tenant lên v7, số đơn và case không đổi, `exchange_requests_mapped: 0`.

**Sự cố sau rollout:**
- *Triệu chứng.* Image W3.2 đầu tiên (`c966bf3f…`) qua rollout và `/healthz`, nhưng mọi request đã đăng nhập trả `400 bad_request`; live smoke dừng ở `session lookup failed`.
- *Nguyên nhân gốc.* `/opt/retailops/compose.public.yaml` trên EC2 còn 3 mount từ thời `scripts/update_ec2.py`: `/opt/retailops/patches/{data,evals,mcp_config.json}` → `/app/...` (chỉ đọc). Bản tháng 9 của `/app/data` che mất `data/order_action_reasons.json` của image. `Application` đọc danh mục này theo kiểu fail-closed, nên mọi phiên đăng nhập đều lỗi. Bước so mã nguồn của rollout chỉ xét code nên không phát hiện, và `/healthz` khi đó chưa kiểm tra danh mục.
- *Hệ quả phụ.* Từ tháng 9 tới 2026-11-03, `data/` (chính sách, sản phẩm), `evals/` và `mcp_config.json` trên production là bản cũ trên host, không phải bản trong image.
- *Xử lý.* PR #56 làm `/healthz` trả 503 khi thiếu danh mục. Nhờ đó lần chạy workflow `41649491137` tự rollback và lộ ra mount cũ. Ba mount được gỡ tay (backup `compose.public.yaml.bak-20261103T141956`). Image `sha256:03bdf0baae39e37c249259a9ca4eeea1d0bcbfe7664f3f8acd99241668041808` được kích hoạt và rollout tay: `PUBLIC_WEB_ROLLOUT_OK`, `CATALOG_OK`, `ADMIN_CONSOLE_READY`, `LIVE_E2E_SMOKE_OK` (`LIVE_SMOKE_20261103T143058Z`). PR #57 chặn tái diễn.
- *Ảnh hưởng.* Khoảng 13:00–14:30 UTC người dùng đã đăng nhập không dùng được; dữ liệu không mất, DB v7 đúng.

**Lần chạy workflow:** `41636882867` đỏ có chủ đích (đưa image lên trước migrate, tự rollback); `41649491137` đỏ do health gate mới (đúng thiết kế). `RETAILOPS_DEPLOY_ENABLED` để `false`.

**Còn mở:** owner chạy bộ kịch bản với model thật trên Colab (`scripts/run_agent_scenarios.py --endpoint …`); xác nhận nguyên nhân 503 cũ qua `trace.model_errors` ở lần lỗi tiếp theo; dọn tài khoản và tenant chẩn đoán `diag-*` cùng các tenant `e2e-smoke-*` (W6); đổi tên `/opt/retailops/patches` thành thư mục đã ngừng dùng.

### 2026-11-03 W4 readiness review

> **Phạm vi:** một lượt readiness review cho W4, chỉ BLOCKER/MAJOR. Đối chiếu README W4, §10 (Internal AI), §11.6 và §16 với code trên `main` (`c11285e`).

**Finding đã được owner đóng bằng [§17](W0_OWNER_DECISION_DELTA_2026-10-29.md#17-w4-owner-decisions-2026-11-03):**

| ID | Mức | Vấn đề | Đóng bằng |
|---|---|---|---|
| `W4-RR-01` | BLOCKER | Endpoint Colab là URL ngrok công khai, không có `--api-key` hay lớp truy cập thứ hai; `vllm>=0.6.0` chưa ghim; chat template lấy từ nhánh đang thay đổi | W4-D2, W4-D10 |
| `W4-RR-02` | BLOCKER | Ảnh khách gửi trong chat được lưu nguyên base64 trong `agent_turns` và gửi lại khi đọc lịch sử, trái §11.6 | W4-D6, W4-D9 |
| `W4-RR-03` | MAJOR | Chưa có AI cho Staff/Manager; phạm vi và lịch sử riêng của trợ lý ca chưa chốt | W4-D1, W4-D4, W4-D5 |
| `W4-RR-04` | MAJOR | Model hiện tại nằm trong `TEXT_ONLY_MODELS`, nên ảnh bị chặn bằng tên model thay vì cấu hình năng lực | W4-D7 |
| `W4-RR-05` | MAJOR | Chưa nhận PDF và chưa có máy quét mã độc | W4-D3, W4-D9 |
| `W4-RR-06` | MAJOR | `customer_ref` trong JSONL là SHA-256 không salt, đoán ngược được với mã khách dạng `C-001` | W4-D8 |

**Kết luận:** W4 **READY** để thực thi theo [W4 execution handoff](W4_EXECUTION_HANDOFF_2026-11-03.md). Readiness tổng thể vẫn `BLOCKED` cho `W5–W6`. Migration business v8, cài ClamAV và deploy W4 cần owner duyệt riêng, theo runbook như W3.2. W4 không bật dữ liệu khách thật.

### 2026-11-05 W4 production deploy record and W4.1 hotfix

**Kiểm chứng (một lượt, 2026-11-04).** PR #60 tại `83d7181`:
- CI 6/6. Chạy trên máy, 37/37 test W4 pass sau khi cài `pypdfium2` đúng bản đã ghim.
- `vllm==0.32.0` có trên PyPI. Chat template ở tag `v0.32.0` khớp đúng SHA-256 đã ghim. Các cờ `--api-key`, `--disable-uvicorn-access-log` và `--default-chat-template-kwargs` đều có trong bản 0.32.

Lượt kiểm chứng tìm ra hai lỗ hổng phía deploy. Argon đã sửa cả hai trong `f55d1bc`:
1. `rollout-public-web.sh` (gồm cả mảng rollback), `admin-console.py` và `live-e2e.py` không nạp `compose.clamav.yaml`.
2. Hướng dẫn dùng `*_FILE` không chạy được, vì container `web` không mount `/opt/retailops/secrets` và `api.env` đã có sẵn dòng `RETAILOPS_API_KEY`.

Ghi chú không chặn: rollout không tạo lại `web` khi image giữ nguyên. Vì vậy, sau khi chỉ sửa `api.env`, phải tạo lại `web` bằng compose với đủ overlay (public, postgres, clamav).

**Merged:** PR #60 (W4, merge `f46a22b`), PR #61 (dọn docs trạng thái cũ, `1327530`), PR #62 (W4.1 handoff) và PR #63 (W4.1 hotfix, `c293edf`).

**Kiểm tra EC2 trước deploy:** t3.large, 8 GB RAM, không swap, còn trống 43 GB đĩa. `freshclam` tải được bộ nhận diện virus từ EC2. Không còn mount `/opt/retailops/patches`.

**Migration business v8 trên DB production**, cùng mô hình W3.2:
- Preflight chỉ đọc: identity v5; 46 tenant ở business v7; 584 đơn; 82 case; 0 yêu cầu đơn hàng; 0 bằng chứng; 0 tệp đính kèm nằm trong lịch sử chat.
- Backup: `pre-w4-20261105T035147.dump` và `final-pre-w4-20261105T041755.dump`. File sau được chụp khi `web` đã dừng và là **bản dùng để khôi phục về trước W4**.
- Khóa trong `api.env` (ghi giá trị trực tiếp, không dùng `*_FILE`): đổi `RETAILOPS_API_KEY`; thêm `RETAILOPS_API_TUNNEL_TOKEN`, `RETAILOPS_CUSTOMER_REF_KEY` và `RETAILOPS_API_VISION=off`.
- Workflow `41964343814` đỏ có chủ đích: đưa image `sha256:6ef79afe…` lên EC2 rồi tự `PUBLIC_WEB_ROLLBACK_OK`.
- ClamAV `clamav/clamav:1.4.6-debian@sha256:ce80e978…` healthy. Từ container `web`, lệnh `zPING` nhận được `PONG`.
- Diễn tập trên DB tạm: lần đầu `upgraded: True`, chạy lại `False`; có 46 bảng `case_assist_turns`; W4 khởi động được trên v8.
- `database migrate-v8` trên DB thật: 46 tenant lên v8; số đơn và case không đổi; tệp đính kèm cũ chuyển 0, gỡ 0.
- Rollout W4 xong với `PUBLIC_WEB_ROLLOUT_OK`. Caddyfile mới lấy từ image: 20 MiB cho bằng chứng, 27 MiB cho chat, 10 MB cho phần còn lại; bản cũ lưu ở `Caddyfile.bak-w4-20261105T044133`. `admin-console.py install` thêm lại dòng import admin: `ADMIN_CONSOLE_READY`. Live smoke: `LIVE_SMOKE_20261105T044859Z`.
- Trạng thái sau deploy: `web` có `RETAILOPS_CLAMD_HOST=clamav:3310` và `VISION=off`; outbox báo `customer_ref_key_configured: true` và 0 sự kiện `dead`.

**Sự cố vận hành: phiên SSM rớt giữa giai đoạn migrate.**
- *Diễn biến.* Phiên cũ đã chạy xong các bước dừng `web`, backup cuối và migrate. Phiên mới chạy lại cả ba bước. Lần migrate thứ hai ra `upgraded: false`, đúng như mong đợi. Nhưng bản backup thứ hai được chụp **sau** khi migrate.
- *Xác minh.* Kiểm tra mục `case_assist_turns` trong danh mục của từng file backup: `final-pre-w4-20261105T041755` có 0 mục, còn bản chụp lúc `044133` có 230 mục.
- *Xử lý.* Đổi tên bản chụp lúc `044133` thành `post-w4-20261105T044133.dump`.
- *Bài học.* Gửi runbook theo từng giai đoạn. Khi phiên rớt, kiểm tra trạng thái trước rồi mới chạy tiếp: `chk`, `docker ps`, số file backup.

**Endpoint model:**
- Colab hết quota tính toán, nên endpoint hai lớp của W4 chưa kiểm được trên thực tế. Lần thử trả 404 vì tunnel đang offline (`ERR_NGROK_3200`).
- Cặp API key và tunnel token đầu tiên đã bị dán vào chat, nên coi như đã lộ. Phải đổi cặp mới trước khi cấu hình Colab.
- Trong thời gian chờ, production tạm dùng DeepSeek `deepseek-flash` qua `RETAILOPS_API_ENDPOINT=https://api.deepseek.com/chat/completions`:
  - Tunnel token được comment trong `api.env`, để không gửi sang nhà cung cấp bên ngoài.
  - Cấu hình Colab được lưu ở `api.env.bak-deepseek-20261105T054717`.
  - `deepseek-chat` chỉ là tên gọi tắt, phản hồi trả về tên `deepseek-flash`. Vì vậy phải đặt đúng tên này, nếu không app báo `api_model_mismatch`.
- Dữ liệu demo đi qua nhà cung cấp bên ngoài. Đây là phương án tạm thời; không dùng số liệu chạy bằng DeepSeek để đánh giá Gemma.

**W4.1 hotfix (2026-11-05):**
- *Phát hiện.* Khi owner kiểm thử, Staff Desk đang mở làm chính phiên đó nhận `429 rate_limited`: khoảng 72 request mỗi phút trong khi giới hạn là 60 mỗi phiên. Nút bị khóa hiện con trỏ `wait`.
- *Thực hiện.* PR #63 do Argon làm theo [W4.1 handoff](W4_1_HOTFIX_HANDOFF_2026-11-05.md): polling Staff Desk 5 giây một lần, `SESSION_RATE_LIMIT_PER_MINUTE = 120`, con trỏ `not-allowed`. CI 6/6.
- *Deploy.* Workflow `41983541442` thành công với image `sha256:8e83ac32ca558aab082a47ceb95128946f82887f56cb0d42202aaceb5937270f`: `PUBLIC_WEB_ROLLOUT_OK`, `ADMIN_CONSOLE_READY` và 2 lần `LIVE_E2E_SMOKE_OK`.
- *Kiểm tra.* Owner thử trên trình duyệt: Trợ lý ca dùng được sau khi nhân viên nhận ca.

`RETAILOPS_DEPLOY_ENABLED` để `false`.

**Còn mở:**
- Quay lại Colab: khôi phục file backup, đổi khóa, đặt Colab Secrets, kiểm 403/401/200. Sau đó đo token mỗi ảnh trên L4 và chạy kịch bản W3.2 và W4 với model thật.
- Bật `RETAILOPS_API_VISION=on` sau khi đã kiểm endpoint.
- Cập nhật Google OAuth theo host mới.
- W5: tooltip "Nhận ca trước" cho nút Trợ lý ca, gộp các request polling.
- Kiểm tra kho tri thức: `search_knowledge` trả 0 tài liệu khi hỏi chính sách đổi size.
- Các mục còn mở từ W3.2.

### 2026-11-05 W5 readiness review

> **Phạm vi:** một lượt readiness review cho W5, chỉ BLOCKER/MAJOR. Đối chiếu các mục W5 trong lộ trình (README, handoff W2/W3, ghi chú sau W4) với code trên `main` (`4f86e9f`).

**Finding đã được owner đóng bằng [§18](W0_OWNER_DECISION_DELTA_2026-10-29.md#18-w5-owner-decisions-2026-11-05):**

| ID | Mức | Vấn đề | Đóng bằng |
|---|---|---|---|
| `W5-RR-01` | MAJOR | Nút dừng bot (W2-D6) chưa có: backend không có cơ chế hủy một lượt agent đang chạy; chưa chốt lượt bị dừng được lưu thế nào | W5-D3 |
| `W5-RR-02` | MAJOR | Chưa có chuyển ca: không có API, không có danh sách nhân viên cùng cửa hàng; chưa chốt người nhận có phải bấm nhận không | W5-D2 |
| `W5-RR-03` | MAJOR | Manager Console có 6 tab nhưng không có màn hình nào cho R1; Manager muốn quyết hoàn tiền phải mở từng ca trong Staff Desk | W5-D1 |
| `W5-RR-04` | MAJOR | Tool Inspector cho Staff dùng, có `request_human_support` là thao tác có tác dụng thật, tham số mẫu `O-101`/`P-101` không tồn tại trên dữ liệu persistent, danh sách tool đã cũ | W5-D4 |

**Mục không cần owner quyết (mặc định trong §18):** endpoint `resume` đã có nhưng UI chưa có nút "Tiếp tục" (W5-D5); đóng ca lần hai trả `409 case_not_escalated` (W5-D6); nút Trợ lý ca bị khóa không nói lý do (W5-D7); nút yêu cầu mẫu dùng `O-101` (W5-D8). `web/` không còn `style="..."`, nên mục này rời khỏi W5; gộp polling hoãn sau R1 (W5-D9).

**Kết luận:** W5 **READY** để thực thi theo [W5 execution handoff](W5_EXECUTION_HANDOFF_2026-11-05.md). W5 không có migration. Readiness tổng thể vẫn `BLOCKED` cho `W6`.

### 2026-11-05 W5 production deploy record

**Kiểm chứng (một lượt).** PR #66 tại `1f98088` đạt cả 7 mục 0–6 so với [W5 handoff](W5_EXECUTION_HANDOFF_2026-11-05.md):
- full suite 997 test OK (72 skip chỉ dành cho PostgreSQL), CI 6/6;
- cờ hủy theo `(tenant, người dùng, request_id)`, được kiểm trước model, sau model và trước mỗi tool;
- chuyển ca có kiểm người giữ ca hoặc Manager, khóa `version` và kiểm người nhận cùng cửa hàng; danh sách nhân viên không trả email;
- hàng đợi yêu cầu đơn hàng chỉ dành cho Manager;
- Tool Inspector chỉ dành cho Manager, đúng 6 tool đọc.

Ghi chú không chặn: Tool Inspector bỏ 3 tool đọc trước đây được phép (`get_product`, `check_variant_stock`, `search_products`), đúng theo allowlist của handoff.

**Merged:** PR #65 (readiness, §18, handoff, `d847857`) và PR #66 (W5, `0a2ba38`).

**Deploy:** không có migration.
- EC2 được bật lại; host mới là `retailops.35-172-227-184.sslip.io`. Rollout và admin chạy lại với image cũ để cập nhật host, smoke `LIVE_SMOKE_20261105T131620Z`.
- Workflow `42034603388` thành công với image `sha256:8992bac609469b1d1febe8afa9fdf034cf3cc2bbf45bdbb93c833ae86e5d0a11`: `PUBLIC_WEB_ROLLOUT_OK`, `ADMIN_CONSOLE_READY` và 2 lần `LIVE_E2E_SMOKE_OK`.
- `RETAILOPS_DEPLOY_ENABLED` để `false`.
- Model vẫn tạm dùng DeepSeek `deepseek-flash`, như ghi ở biên bản W4.

**Còn mở:**
- Owner kiểm trên trình duyệt: dừng bot, "Tiếp tục", chuyển ca (cần 2 tài khoản Staff/Manager), tab "Yêu cầu đơn hàng", Tool Inspector theo vai trò.
- Cập nhật Google OAuth theo host mới.
- Các mục còn mở của W4 chuyển sang W6: quay lại Colab và đổi khóa, bật vision, đo với model thật, kho tri thức thiếu tài liệu chính sách đổi trả.

### 2026-11-08 W6.1b readiness review

> **Phạm vi:** một lượt readiness review cho W6.1b, chỉ BLOCKER/MAJOR. Đối chiếu [W6 backlog](W6_BACKLOG_2026-11-06.md) mục 4, [tài liệu database mục B](../../khoa_luan/07_co_so_du_lieu.md) và §19 với code trên `main` (`b6b941c`), sau khi W6.1a đã merge.

**Finding đã được owner đóng bằng [§20](W0_OWNER_DECISION_DELTA_2026-10-29.md#20-w61b-owner-decisions-2026-11-08):**

| ID | Mức | Vấn đề | Đóng bằng |
|---|---|---|---|
| `W61B-RR-01` | BLOCKER | RetailOps chỉ có đường nhận hợp đồng v1 của Phase 5: chữ ký nằm trong thân, phong bì khác; sàn ảo W6.1a phát hợp đồng v2 ký ở header, nên không sự kiện nào của sàn ảo vào được RetailOps | W6.1b-D3, D4 |
| `W61B-RR-02` | BLOCKER | F18: adapter rơi về khóa mặc định `dev_secret_key_retailops_2026` nằm trong repo; mở endpoint là ai đọc repo cũng giả được sự kiện | W6.1b-D3, D5 |
| `W61B-RR-03` | BLOCKER | Caddy chuyển mọi đường dẫn tới `web:8000`; "endpoint chỉ trong mạng nội bộ" trong backlog chưa có cơ chế nào bảo đảm | W6.1b-D4 |
| `W61B-RR-04` | MAJOR | `imported_events.payload_json` lưu nguyên thân sự kiện; `order.created` v2 mang tên, số điện thoại, địa chỉ người nhận, nên dữ liệu cá nhân sẽ nằm dạng thô trong DB, trái W6.1a-D11 | W6.1b-D7 |
| `W61B-RR-05` | MAJOR | F16 ánh xạ `shipping → delivered`; F17 dùng mã đơn của nguồn làm `orders.id`; chưa chốt khách nhìn thấy mã nào | W6.1b-D8, mục 4 của handoff |
| `W61B-RR-06` | MAJOR | Dữ liệu nghiệp vụ viết trong code ở 5 chỗ: `seed()`, `data/deepseek_seed_data.json`, đơn mẫu theo tài khoản, dict hành trình trong `track_shipment`, `data/mock_shipments.json`; 24 trên 41 kịch bản hồi quy W3.2, W4 tham chiếu mã đơn của seed này | W6.1b-D2, D11, D12 |
| `W61B-RR-07` | MAJOR | Dữ liệu demo sinh một lần có mốc tháng 10/2026; vài tháng sau mọi đơn quá hạn đổi trả 7 ngày, đổi size 15 ngày, bảo hành 90 ngày, khiến demo và đánh giá lệch theo ngày chạy | W6.1b-D11 |
| `W61B-RR-08` | MAJOR | `refunds.request_id` ở mục B3 giả định biết yêu cầu nào được hoàn, nhưng sàn và cổng không biết mã yêu cầu của RetailOps; chưa có luật nối | W6.1b-D10 |
| `W61B-RR-09` | MAJOR | `integration_connectors` ở mục B3 không có `merchant_id`, và bảng nằm trong schema của từng cửa hàng nên route phải biết cửa hàng trước khi tra connector | W6.1b-D4, D5 |
| `W61B-RR-10` | MAJOR | Phạm vi W6.1b trong backlog gồm migration, cổng nhận, 4 nhóm dữ liệu, mã hóa, bồi thường, outbox, thông báo: quá lớn cho một handoff và một lượt kiểm chứng | W6.1b-D1 |
| `W61B-RR-11` | MAJOR | `imported_events` mang hình hợp đồng v1, bắt buộc `customer_id`, `order_id`, `status`, `total`, `currency`, `signature`; sự kiện v2 không gắn đơn như `product.upserted` không ghi vào được. Mục B6 không nhắc bảng này | mục 0 của handoff |
| `W61B-RR-12` | MAJOR | Bằng chứng toàn vẹn bằng SHA-256 trần trên thân sự kiện cho phép xác nhận dữ liệu người nhận: các trường còn lại đã nằm trong DB, chỉ cần thử tên và số điện thoại | W6.1b-D7 |

**Kết luận:** W6.1b-1 **READY** để thực thi theo [W6.1b-1 execution handoff](W6_1B_1_EXECUTION_HANDOFF_2026-11-08.md) khi owner merge bản ghi này. W6.1b-2 chưa READY vì còn chốt cách mã hóa người nhận. Migration business v9 và deploy cần owner duyệt riêng, theo runbook ở mục 6 của handoff. Readiness tổng thể vẫn `BLOCKED` cho W6.2 trở đi.

### 2026-11-09 W6.1b-1 verification and merge record

**Kiểm chứng.** PR #75 của Argon, nhánh `feat/phase-r1-w6-1b-1-ingest-v9`, theo [W6.1b-1 handoff](W6_1B_1_EXECUTION_HANDOFF_2026-11-08.md) và §20. Ba vòng kiểm chứng độc lập, mỗi vòng chạy lại test, đối chiếu diff và CI:

| Vòng | Head | Kết quả |
|---|---|---|
| 1 | `beac0f0` | Đạt phần lõi mục 0–10. **BLOCKER:** `deploy/live-e2e.py` tạo tenant seed demo rồi đăng nhập `C-001`, tra `O-101`, trong khi seed mới không còn các mã này, nên smoke chạy tự động sau rollout trong `deploy/publish_and_activate.py` sẽ fail; `scripts/get_login_token.py`, `scripts/run_live_benchmark_http.py` cùng lỗi. **MAJOR:** kịch bản `refund_status_is_not_invented` bị bỏ `"đã hoàn tiền"` khỏi `answer_not` để khớp câu trả lời mẫu mới, trái W6.1b-D12. **MINOR:** tên hiển thị `"Mai Anh"` viết cứng trong `retailops/http/routes.py`; nút mô phỏng SOP mặc định `O-301`–`O-304`; seed demo dùng khóa digest tạm khi thiếu khóa ở production. |
| 2 | `c20904f` | MAJOR và MINOR đã sửa. BLOCKER sửa bằng cách chạy `python /app/deploy/live-e2e.py --resolve-targets` trong container, nhưng chạy dạng script thì `sys.path[0]` là `/app/deploy` nên `import retailops` lỗi `ModuleNotFoundError`; test chỉ gọi hàm trong cùng tiến trình nên không bắt được. |
| 3 | `02ae111` | BLOCKER đóng: nhánh `--resolve-targets` thêm thư mục gốc ứng dụng vào `sys.path`; có test chạy dạng script bằng `subprocess` không đặt `PYTHONPATH`; job `offline` chạy resolver trong container đóng gói trên SQLite và PostgreSQL, in và kiểm `LIVE_E2E_RESOLVE_TARGETS_CONTAINER_OK`. Lần sửa MINOR làm `/api/session` của `GuestSessions` mở SQLite mỗi request, P99 vượt 50 ms trên CI; Argon lưu tạm tên hiển thị theo phiên, gộp tra phiên với giới hạn tần suất trong một giao dịch, giới hạn 60 lần mỗi phút giữ nguyên, và chép kho khách mới từ một kho mẫu đã seed; P99 `/api/session` trên CI còn 5,2 ms. |

**Đã kiểm độc lập và đạt:** CI 6/6 trên `02ae111`; full suite cục bộ chỉ còn các lỗi môi trường đã có trên `main` là hai test migrate v8 và ba test W4 cần `pypdfium2`; hai bộ dữ liệu `data/demo_events/` sinh lại đúng SHA-256 theo manifest, 2.003 và 64 sự kiện; route nội bộ bị Caddy chặn và ứng dụng từ chối header do proxy thêm; `secret_ref` khớp `retailops_connector_*`, khóa đọc bằng `lstat` và `O_NOFOLLOW`; digest là HMAC trên byte gốc, các trường người nhận là `null`, quét DB không còn số điện thoại hay địa chỉ; `ambiguous_order` khi mã trùng; chỉ nối hoàn tiền khi đúng một yêu cầu chờ; trạng thái cuối của 13 kịch bản sàn ảo đúng; đủ 41 kịch bản hồi quy, không điều kiện chấm nào bị nới; RetailOps không import `marketplace_sim`; không còn `mock_shipments`, `deepseek_seed` hay khóa mặc định.

**Merge:** owner duyệt, PR #75 merge vào `main` tại `16fb91e` ngày 2026-11-09. Workflow deploy tự bỏ qua vì cờ deploy đang tắt.

**Còn mở:**
- Migration business v9 và deploy W6.1b-1: owner duyệt riêng, theo mục 6 của handoff. Hai việc phải làm trước rollout: tạo `/opt/retailops/integration-secrets/` với hai tệp khóa, vì `deploy/compose.postgres.yaml` giờ khai báo hai secret này; chạy `database migrate-v9` khi web đã dừng, vì image mới từ chối chạy trên DB v8. Sau rollout: `connector add`, `connector check` phải trả 0, `purge-legacy-demo --dry-run` cho owner duyệt rồi mới chạy thật, `import-events`.
- Mỗi lần live E2E smoke giờ tạo một tenant khoảng 2.000 sự kiện; dọn tenant `e2e-smoke-*` ở C6 cấp bách hơn.
- Job `offline` được nâng timeout từ 12 lên 18 phút; notebook Colab tăng từ khoảng 1,09 MB lên 1,30 MB vì nhúng dữ liệu demo.
- W6.1b-2 chưa READY: còn chốt cách mã hóa người nhận, thời hạn giữ backup và có thêm `refund.requested` hay không, theo §20.

### 2026-11-09 W6.1b-1 production deploy record and W6.1b-1.1 hotfix

**Kiểm tra EC2 trước deploy.** EC2 vừa bật lại lúc 07:50Z: còn trống 42 GB đĩa, khoảng 6 GB RAM khả dụng, không swap. 52 tenant đều ở business v8. Tenant production là `browser-demo-20260908014853` (giá trị `RETAILOPS_DEMO_TENANT_ID`). Web và admin chạy image `sha256:8992bac609469b1d1febe8afa9fdf034cf3cc2bbf45bdbb93c833ae86e5d0a11`.

**Khóa tích hợp.** Tạo lúc 07:54Z trong `/opt/retailops/integration-secrets/` (thư mục `0700 root`): `retailops_connector_marketplace_sim` và `retailops_event_digest_key`, mỗi tệp `0444`, 64 byte. Backup khóa tách khỏi backup DB: `/root/retailops-key-backups/integration-secrets-20261109T075429Z.tgz`.

**Sự cố 1: lượt deploy đỏ có chủ đích không tự quay về được.**
- *Diễn biến.* Workflow [`42582452909`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/42582452909) đưa image `sha256:f2754fb82baad44902ea5a04abcf19564d3de64ddee001e9311fa510a0214d46` lên EC2. IP công khai đã đổi từ `35.172.227.184` sang `100.26.48.5` sau stop/start, nên `rollout-public-web.sh` sửa `public.env` rồi tạo lại web **bằng image mới** trước khi ghi nhận image cũ. Web mới từ chối khởi động đúng thiết kế (DB còn v8), nhưng script báo `No distinct previous live image is available for automatic rollback`. Caddy cũng được tạo lại mà không có overlay admin.
- *Ảnh hưởng.* Web công khai trả 502 từ khoảng 08:10Z tới 08:18Z. DB không đổi vì web mới dừng ở bước kiểm schema chỉ đọc.
- *Xử lý.* Ghi `deployed.env` về image cũ, tạo lại web và caddy kèm `--env-file admin.env -f compose.admin.yaml`; `/healthz` trả 200 từ ngoài, Caddy có lại mount `/etc/caddy/admin`. Bản `deployed.env` lỗi lưu ở `/root/deployed.env.failed-*`.
- *Sửa gốc.* Mục 1 của W6.1b-1.1 bên dưới.

**Sự cố 2: lộ invite token trong chat.** Lệnh kiểm `grep '^RETAILOPS_PUBLIC_'` do Claude đưa khớp luôn dòng `RETAILOPS_PUBLIC_INVITE_TOKEN`, và output được dán vào chat. Token được đổi trong cùng bước khôi phục web; bản `public.env` cũ (chứa token đã lộ) lưu ở `/root/public.env.bak-*`. Không dùng mẫu tiền tố đó để kiểm `public.env`.

**Tệp cấu hình trên host.** `compose.postgres.yaml` và `Caddyfile` chép từ image mới, giữ dòng `import /etc/caddy/admin/*.caddy`; diff chỉ có hai biến `RETAILOPS_*`, hai secret `integration-secrets` và khối `@internal_routes`; `caddy validate` thoát 0. Bản cũ: `*.bak-w6-1b-1-20261109T082059Z`.

**Migration business v9.**
- Backup trước: `backups/pre-w6-1b-1-20261109T082229Z.dump`, 5.833.257 byte, 8.991 mục TOC.
- Diễn tập trên DB nháp `retailops_rehearsal`: lần restore đầu dừng ở `permission denied to create extension "vector"` vì quy trình trong `docs/POSTGRESQL.md` viết trước khi có pgvector; restore lại bằng cách tạo schema `retailops_extensions` và extension bằng `postgres`, rồi `pg_restore -L` với TOC đã bỏ 3 mục extension (sửa gốc ở mục 2 của W6.1b-1.1). Migrate: 52 tenant, `upgraded: true`, `orders_backfilled: 674`; chạy lại `upgraded: false`; kết quả `52 business|9`. DB nháp đã xóa.
- Dừng web lúc 08:28:54Z, backup cuối `backups/final-pre-w6-1b-1-20261109T082854Z.dump` (8.991 mục), **bản dùng để khôi phục về trước W6.1b-1**. Migrate thật: 52 tenant, `orders_backfilled: 674`, khớp diễn tập.
- Bật web ngay bằng image `f2754fb8…` thay vì chờ workflow, nên web chỉ dừng khoảng 1 phút. `/internal/*` trả 404; `/run/secrets/` có đủ 3 tệp.

**Rollout chính thức.** Workflow [`42586669481`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/42586669481), image `sha256:0ef5105af1566a627e6168846f026af897efc2323e8bd58a3300c2d50b055b29`: `PUBLIC_WEB_ROLLOUT_OK`, `PUBLIC_WEB_SOURCE_MATCH`, 2 lần `LIVE_E2E_SMOKE_OK`, `ADMIN_CONSOLE_READY host=admin-retailops.100-26-48-5.sslip.io`, `ADMIN_CONSOLE_SMOKE_OK`.

**Connector và dữ liệu.**
- `connector add` trên tenant production: `marketplace_sim`, `MERCHANT-SIM-001`, `key_status: ok`; `connector check`: `CONNECTOR_CHECK_OK`, `digest_key_status: ok`.
- `import-events` với `data/demo_events/store_events.jsonl`, `--rebase-clock now`: 2.003 dòng, `errors: 0`, `duplicates: 0`, dời đồng hồ 806.153 giây; tenant có 128 đơn `marketplace_sim`. Outbox không có sự kiện `dead`.
- `purge-legacy-demo` chạy thật trả `ForeignKeyViolation` và rollback: hàm ghi audit với `customer_id = "system"`, mà trên PostgreSQL `business_events.customer_id` có khóa ngoại tới `customers`. Không đơn nào bị xóa. Sửa ở mục 0 của W6.1b-1.1.

**Smoke tay lần 1 (tài khoản Google mới).** 3 đơn `SIM-O-F6E2B615-01/02/03`. `track_shipment` trả hành trình từ DB, số shipper đã che, agent nói bằng mã sàn. Không đạt: khung thông tin khi chọn đơn (`describe_order`) hiện mã nội bộ `ord_…` và câu "chưa có trong dữ liệu demo"; thanh "Đang trao đổi" hiện `ord_…`; thẻ đơn của khách hiện `cust_…` và "Phiên bản"; không có chip lọc đơn đang giao; Staff Desk chỉ hiện mã nội bộ; thẻ vận chuyển ghi "Dự kiến nhận" cho đơn đã giao và hiện giờ dạng ISO. Gom vào mục 3 của W6.1b-1.1.

**W6.1b-1.1 hotfix.**
- *Handoff.* [W6.1b-1.1 hotfix handoff](W6_1B_1_1_HOTFIX_HANDOFF_2026-11-09.md), PR #77 merge tại `6d481dc`.
- *Thực hiện.* PR #78 của Argon, mục 0–3. Mục 0 có bằng chứng FAIL trước khi sửa trên PostgreSQL thật (CI run `42594256673`, `ForeignKeyViolation`); mục 3 có test Python và JS FAIL trước khi sửa.
- *Kiểm chứng.* Mục 0, 1, 3 đạt. Mục 2 có BLOCKER: mẫu `grep` lọc TOC trong `docs/POSTGRESQL.md` đòi loại mục đứng ngay sau `; `, nên không lọc được dòng TOC thật nào (ví dụ `10; 2615 16670 SCHEMA - retailops_extensions postgres`), quy trình restore vẫn hỏng. Claude sửa mẫu và thêm test chạy trên đúng 3 dòng TOC thật (`0a8f899`), rồi cho test tự bỏ qua trong image phát hành vốn không có `docs/` (`9e9e6d2`). CI 6/6 trên `9e9e6d2`.
- *Merge.* PR #78 merge vào `main` tại `0beb80b`.
- *Deploy.* Workflow [`42609229270`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/42609229270), image `sha256:3f085a1158d41b10f615465bab6f768384b9bb4f5bbba27318bb41f8128fe887`: `PUBLIC_WEB_ROLLOUT_OK`, 2 lần `LIVE_E2E_SMOKE_OK`, `ADMIN_CONSOLE_SMOKE_OK`. IP không đổi nên không qua nhánh sửa hostname.
- *Gỡ đơn demo cũ.* Dry-run: gỡ 8, giữ `O-819127` (có yêu cầu trả/đổi). Owner duyệt; chạy thật `PURGE_LEGACY_DEMO_OK`, gỡ `O-101`, `O-102`, `O-202`, `O-757460`, `O-757462`, `O-819125`, `O-847063`, `O-847065`. Tenant còn `retailops_seed|1` và `marketplace_sim|131` (thêm 3 đơn mẫu của tài khoản Google mới).
- *Smoke tay lần 2.* Đạt: thanh "Đang trao đổi" hiện `SIM-O-F6E2B615-02`; khung thông tin đơn đang giao có thanh toán, hoàn tiền, vận chuyển và nói rõ không hủy được; thẻ đơn không còn `cust_…` hay "Phiên bản"; có chip "Đang giao"; thẻ vận chuyển "Dự kiến nhận: 16:17 12/11/2026" và hành trình dạng `HH:mm dd/MM/yyyy`; Staff Desk hiện cả hai mã ở thẻ ca và tiêu đề ca. Owner chấp nhận nhãn "Đã giao lúc" của đơn đã giao dựa trên test JS, chưa kiểm tay. Đăng nhập Google chạy trên host mới.

**Backup và thời hạn giữ (owner chốt 2026-11-09):**

| Tệp | Vị trí | Giữ tới |
|---|---|---|
| `pre-w6-1b-1-20261109T082229Z.dump` | `/opt/retailops/backups/` | xóa ngày 2027-01-31 (W6.1b-2-D4) |
| `final-pre-w6-1b-1-20261109T082854Z.dump` | `/opt/retailops/backups/` | xóa ngày 2027-01-31 (W6.1b-2-D4) |
| `integration-secrets-20261109T075429Z.tgz` | `/root/retailops-key-backups/` | lâu dài; chỉ chứa khóa digest và khóa connector, không có dữ liệu cá nhân; mất khóa digest thì không kiểm chứng được các bản ghi sự kiện đã lưu |

`RETAILOPS_DEPLOY_ENABLED` để `false` (tắt lúc 11:43:42Z).

**Còn mở:**
- Xóa `/root/public.env.bak-*` (chứa invite token đã lộ) và `/root/deployed.env.failed-*` sau khi owner xem lại biên bản; giữ `/root/purge-*.json` tới khi đóng W6.1b-1.
- Khung "Quá trình suy luận" hiện cho khách còn lộ mã nội bộ trong suy luận và tham số tool (`ord_…`); ghi F20 trong [W6 backlog](W6_BACKLOG_2026-11-06.md).
- Câu chốt "chưa có trích dẫn từ kho chính sách" vẫn xuất hiện (W6.2, C3 và F9); câu trả lời trộn "tôi" và "em" (W6.5, F14).
- Mỗi lượt deploy, live E2E smoke tạo thêm 2 tenant `e2e-smoke-*`; dọn ở C6.
- EC2 vẫn không có Elastic IP; mỗi lần stop/start đổi host, phải cập nhật Google OAuth. Bản sửa `rollout-public-web.sh` giờ tự quay về đúng khi IP đổi.
- W6.1b-2: đã chốt ở [§21](W0_OWNER_DECISION_DELTA_2026-10-29.md#21-w61b-2-owner-decisions-2026-11-09), xem readiness review bên dưới.

### 2026-11-09 W6.1b-2 readiness review

> **Phạm vi:** một lượt readiness review cho W6.1b-2, chỉ BLOCKER/MAJOR, đối chiếu §19 (W6.1a-D11 đến D14), §20 và code trên `main` tại `0beb80b`, sau khi W6.1b-1 và hotfix W6.1b-1.1 đã lên production. Một phần phát hiện do owner nêu khi rà phương án reset dữ liệu demo, Claude đối chiếu lại với code.

| ID | Mức | Vấn đề | Đóng bằng |
|---|---|---|---|
| `W61B2-RR-01` | BLOCKER | Nhập lại cùng tệp sự kiện bị chống trùng theo `UNIQUE(source_system, event_id)` của `imported_events`; người nhận đã bị gỡ trước khi ghi ở W6.1b-1 nên không còn bản gốc để xử lý lại | W6.1b-2-D9: gỡ cả `imported_events` của nguồn rồi nhập lại; tệp `data/demo_events/store_events.jsonl` vẫn mang người nhận giả lập trong 128 `order.created` |
| `W61B2-RR-02` | BLOCKER | Repo không có thư viện mã hóa; thêm thư viện cần owner duyệt | W6.1b-2-D1 duyệt `cryptography` |
| `W61B2-RR-03` | MAJOR | `order_purge_tombstones` (từ lệnh gỡ một đơn của Phase 5) chặn `order.created` trùng mã sàn hoặc mã nội bộ; `seed_demo_account_orders` coi khách có tombstone là "đã có dữ liệu" và bỏ qua. `purge-legacy-demo` không ghi tombstone | W6.1b-2-D9: reset không tạo, không xóa tombstone; dry-run liệt kê và dừng nếu có |
| `W61B2-RR-04` | MAJOR | `order_action_evidence` có tệp trên đĩa (`storage_relpath`); xóa dòng mà không xóa tệp để lại rác | W6.1b-2-D9: xóa tệp sau khi giao dịch commit, như `purge_expired_evidence` |
| `W61B2-RR-05` | MAJOR | `import_events_jsonl` chạy cả tệp trong một giao dịch ghi, giữ khóa cửa hàng suốt quá trình; lệnh ghi khác của cùng cửa hàng chờ quá `lock_timeout` 5 giây thì trả 503. `orders.id` sinh ngẫu nhiên nên sau khi nhập lại, mã nội bộ đổi, `conversations.order_id` cũ trỏ vào đơn không còn | W6.1b-2-D9: dừng web khi reset, từ chối khi còn ca mở, đặt `conversations.order_id` về rỗng |
| `W61B2-RR-06` | MAJOR | Outbox giao "ít nhất một lần": nhận việc bằng `SKIP LOCKED` chống hai tiến trình nhận cùng dòng, nhưng không chống ghi trùng yêu cầu hay gửi lại sau sự cố; khóa cửa hàng không áp dụng cho bước nhận việc của outbox | W6.1b-2-D6; sàn ảo đã chống trùng theo `request_id` |
| `W61B2-RR-07` | MAJOR | Sàn ảo không chạy trên production, nên `voucher.requested` không tự có `voucher.issued` | W6.1b-2-D8: vòng tay, runbook và kịch bản demo |
| `W61B2-RR-08` | MAJOR | Hoàn tiền của yêu cầu cũ về muộn sau khi khách mở yêu cầu mới có thể bị nối nhầm; khóa không giải quyết vì đây là luật nối | W6.1b-2-D5 |
| `W61B2-RR-09` | MAJOR | W6.1a-D13 cho Manager đổi ngưỡng và mệnh giá, nhưng không có bảng cấu hình theo cửa hàng và W6.1b-2 không có migration | W6.1b-2-D7: owner chọn voucher cố định 50.000 VNĐ, ngưỡng 48 giờ cố định; không ai sửa mệnh giá trong R1 |

**Ghi chú không chặn:**
- `pg_advisory_xact_lock(hashtextextended(schema, 0))` dùng khóa 64 bit; hai schema trùng hash sẽ chặn nhau, xác suất không đáng kể ở quy mô hiện tại.
- `statement_timeout='15s'` đặt trong mọi giao dịch, **kể cả lệnh migrate**; dừng web chỉ loại bỏ tranh chấp khóa, không loại bỏ giới hạn 15 giây cho từng câu lệnh. Migrate v9 trên 52 tenant hiện tại không chạm giới hạn; cửa hàng lớn sau này cần xem lại.
- `Caddyfile.maintenance` trên host còn bản ngày 2026-11-05, chưa có khối `@internal_routes` và dòng import admin; không dùng `switch-maintenance.sh` khi reset cho tới khi chép lại từ image.

**Kết luận:** W6.1b-2 **READY** để thực thi theo [W6.1b-2 execution handoff](W6_1B_2_EXECUTION_HANDOFF_2026-11-09.md) khi owner merge §21. Reset dữ liệu và deploy cần owner duyệt riêng theo mục 6 của handoff. Readiness tổng thể vẫn `BLOCKED` cho W6.2 trở đi.

### 2026-11-10 W6.1b-2 verification and merge record

**Kiểm chứng.** PR #80 của Argon, nhánh `feat/phase-r1-w6-1b-2`, theo [W6.1b-2 handoff](W6_1B_2_EXECUTION_HANDOFF_2026-11-09.md) và §21. Hai vòng kiểm chứng:

| Vòng | Head | Kết quả |
|---|---|---|
| 1 | `07df51c` | Đạt mục 0–9: không đổi schema; `cryptography==46.0.5` ghim hash cùng `cffi`, `pycparser`, `typing_extensions`; AES-256-GCM, nonce 12 byte, AAD gồm tenant, đơn, trường, `key_id`, khóa con HKDF riêng cho mã hóa và cho HMAC tra số điện thoại; production thiếu khóa thì từ chối `order.created` có người nhận; tool và model chỉ nhận bản đã che; xem bản đầy đủ cần lý do, Staff phải giữ ca có gắn đơn, audit ghi trước khi trả dữ liệu; bồi thường cố định 48 giờ và 50.000 VNĐ, API duyệt từ chối trường mệnh giá, duyệt bằng cập nhật có điều kiện; khóa chống trùng tất định; reset tắt và bật lại trigger chỉ-ghi-thêm trong cùng giao dịch, xóa tệp bằng chứng sau commit; 3 kịch bản hồi quy mới, không nới kịch bản cũ. **MAJOR:** thông báo mốc vận chuyển phát lại khi nhập hàng loạt, nên sau reset tài khoản đã có hội thoại nhận một loạt thông báo cũ; `DEMO_VOUCHER_LOOP.md` cho khách chọn `SIM-O-ST-013` vốn thuộc khách giả lập không đăng nhập được, trong khi đơn trễ duy nhất của tài khoản thật là đơn mẫu `-02`, chỉ trễ quá 48 giờ sau khoảng 120 giờ kể từ lúc nạp. **Không chặn:** che số điện thoại người nhận lộ 7 trên 10 chữ số như cách che số shipper; ngoài production, thiếu tệp khóa thì dùng khóa tạm trong bộ nhớ. |
| 2 | `7e07617` | Hai MAJOR đóng: `--no-notices` cho `import-events` và `seed-account-orders`, chỉ chặn 3 mốc vận chuyển, giữ thông báo trễ hạn và voucher, test FAIL trước khi sửa; tài liệu demo yêu cầu nạp ít nhất 5 ngày trước buổi demo, dùng đơn `-02` của tài khoản demo, có lệnh kiểm trước đề xuất `proposed`; RUNBOOK kiểm `tableowner` trước reset. Lượt CI đầu đỏ đúng một test `test_http_headroom` (P99 `GET /api/session` 144 ms, F19), chạy lại xanh. |

**Đã kiểm độc lập và đạt:** CI 6/6 trên `7e07617`; 4 bộ test PostgreSQL thật của mục 1, 4, 5, 8 chạy không skip; cục bộ 24 test W6.1b-2 OK (4 skip PostgreSQL), test W6.1b-1 và `test_conversation` OK, kiểm docs, deploy, notebook, eval đạt; số đơn trễ thật trong dữ liệu demo được tính lại từ `data/demo_events/`.

**Merge:** owner duyệt, PR #80 merge vào `main` tại `04db5e0` ngày 2026-11-10. Workflow deploy tự bỏ qua vì cờ deploy đang tắt.

**Còn mở:**
- F21: vòng quét trễ hạn mở lại giao dịch ghi mỗi 15 giây cho cả đơn đã có đề xuất và thông báo; ghi trong [W6 backlog](W6_BACKLOG_2026-11-06.md).
- Deploy W6.1b-2 theo mục 6 của handoff: tạo khóa `retailops_recipient_key_v1` và backup riêng, chép `compose.postgres.yaml`, `Caddyfile`, `Caddyfile.maintenance` từ image, rollout, dừng web để reset rồi nhập lại với `--no-notices`, smoke. Nạp dữ liệu ít nhất 5 ngày trước buổi demo voucher.
- Lệnh kiểm trước buổi demo dùng `list_manager_compensations` với giới hạn mặc định 50 dòng; quá 50 đề xuất thì có thể không thấy đơn của tài khoản demo.

### 2026-11-10 W6.1b-2 production deploy record

**Trước deploy.**
- F21 sửa trong PR #82 (merge `ce24729`): vòng quét trễ hạn bỏ qua đơn đã có đề xuất bồi thường, và đơn trễ chưa quá 48 giờ đã có thông báo hoặc khách chưa có hội thoại. Đo với 8 cửa hàng khách: mỗi vòng quét nền từ 250–520 ms còn 130–160 ms. Test mới FAIL trước khi sửa (`3 != 0` giao dịch ghi), PASS sau khi sửa.
- Lượt deploy [`42756086177`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/42756086177) đỏ ở bước chạy test, trước khi build image: harness PostgreSQL của W6.1b-2 coi mọi lần chạy có `GITHUB_ACTIONS=true` là bắt buộc có PostgreSQL, trong khi workflow deploy chạy không có PostgreSQL. Sửa trong PR #83 (merge `7434a66`): chỉ bắt buộc khi job đặt `RETAILOPS_REQUIRE_PG_TESTS=1`. Production không bị đụng.

**EC2.** IP `100.26.48.5` khớp `public.env`; đĩa còn trống 42 GB. Khóa `integration-secrets/retailops_recipient_key_v1` tạo lúc 04:07Z (`0444`, 64 byte); backup riêng `/root/retailops-recipient-key-backups/recipient-key-v1-20261110T040755Z.tgz`. `compose.postgres.yaml` trên host được thêm 4 dòng của PR #80 và kiểm SHA-256 trước (`5ae37352…`) và sau (`7cd49242…`, trùng bản trên `main`); bản cũ `compose.postgres.yaml.bak-w6-1b-2-*`.

**Rollout.** Workflow [`42758617852`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/42758617852), image `sha256:f1fe0d30db492dc1c2a23e66c8512a041e77f49d6af43f80a282a25a2b36c7ad`: 1.066 test hai lần, `PUBLIC_WEB_ROLLOUT_OK`, 2 lần `LIVE_E2E_SMOKE_OK` (smoke nạp dữ liệu sàn ảo có người nhận, nên khóa được gắn đúng), `ADMIN_CONSOLE_SMOKE_OK`. `/run/secrets/` có 4 tệp; `connector check`: `recipient_key_status: ok`. `Caddyfile.maintenance` chép từ image, giữ dòng import admin (`internal_routes` 2).

**Reset dữ liệu demo: chưa chạy.** Bảng `shipment_events`, `order_action_decisions` thuộc `retailops`; 0 ca mở trên đơn sàn ảo. Backup trước reset `backups/pre-w6-1b-2-20261110T051527Z.dump` (11.189.066 byte, 13.265 mục TOC). Dry-run báo 131 đơn, 2 đề xuất bồi thường, 2.067 `imported_events` sẽ gỡ, nhưng `blocking_tombstones` có 2 mục nên chạy thật sẽ từ chối: `O-757461` (`CG-414e57aa`) và `O-819126` (`CG-d9b82ffe`), đều từ đợt dọn đơn demo cũ ngày 2026-10-24, không trùng mã `SIM-O-…` nào. Lệnh reset đang liệt kê mọi tombstone thay vì chỉ tombstone chặn dữ liệu của nguồn (F22). Owner chọn bỏ qua reset hôm nay; web dừng khoảng 1 phút lúc chụp backup.

**Smoke và sự cố phát hiện.**
- Tab "Yêu cầu đơn hàng" của Manager báo không tải được, khung "Bồi thường giao trễ" không hiện: `GET /api/manager/order-actions?…` và `/api/manager/compensations?…` trả `400 unexpected_query` vì cổng chặn query string trong `retailops/http/public.py` chưa cho phép hai route này. Lỗi có từ W5 (2026-11-05) cho `order-actions`. Sửa trong PR #84 (merge `349484a`) kèm test quét `web/app.js`; deploy [`42765141424`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/42765141424), image `sha256:fce32728cd6fc67083d442fec34cfa858d4a1adc4be18af65b29a56c63e95c4d`, xanh; hai route trả 401 khi chưa đăng nhập, route khác vẫn 400.
- Vòng voucher trọn trên production: Manager duyệt `SIM-O-ST-013` (trễ 72 giờ, 50.000 VNĐ cố định, không có ô sửa mệnh giá) → `requested`; `export-voucher-requests` in một dòng `voucher.requested` không có dữ liệu cá nhân; sàn ảo trên máy Claude phát `VCH-L9N2TCKNWM` (`issued: 1`); `import-events --rebase-clock now` → `errors: 0`, voucher 50.000 VNĐ hạn 2026-12-10, đề xuất `issued`. Lần nhập đầu lỗi "Cannot access the configured data or credential file" vì phiên SSM còn `umask 077` từ bước tạo khóa nên tệp tạm `0600`; `chmod 0644` thì chạy.
- `seed-account-orders --all-customers --no-notices`: nạp mẫu 3 đơn cho `C-001` và `cust_c104…`; bỏ qua `cust_2f1b…` (đã có đơn) và `CG-d9b82ffe` (tombstone). `order_recipients`: 6 dòng, cả 6 có ba cột dạng `r1gcm1:v1:…`, 0 dòng giống bản rõ, `phone_masked` dạng `0123.xxx.558`, `retention_until` có ở 4 đơn đã giao.
- Chưa kiểm tay: khách xem người nhận của đơn mình, AI chỉ nhận số đã che, Staff xem bản đầy đủ có audit (`admin_audit_log` chưa có dòng `recipient.reveal`). Các phần này có test PostgreSQL thật trên CI.

**Backup và thời hạn giữ:**

| Tệp | Vị trí | Giữ tới |
|---|---|---|
| `pre-w6-1b-2-20261110T051527Z.dump` | `/opt/retailops/backups/` | xóa ngày 2027-01-31 |
| `recipient-key-v1-20261110T040755Z.tgz` | `/root/retailops-recipient-key-backups/` | xóa ngày 2027-01-31 |

`RETAILOPS_DEPLOY_ENABLED` để `false` (tắt lúc 06:13:20Z).

**Còn mở:**
- F22: sửa lệnh reset chỉ chặn tombstone trùng đơn hoặc khách của nguồn, rồi reset trước 2026-12-15 để đơn mẫu `-02` trễ đúng tuần bảo vệ và 131 đơn cửa hàng có người nhận mã hóa.
- Smoke tay phần xem người nhận và audit `recipient.reveal`.
- Đề xuất bồi thường của `SIM-O-F6E2B615-03` (tài khoản Tu Luong) để nguyên, dùng cho demo trọn vòng phía khách.
- `DEMO_VOUCHER_LOOP.md`: thêm `umask 022` và `chmod 0644` cho tệp tạm trên EC2.

### 2026-11-10 W6.2 readiness review

> **Phạm vi:** một lượt readiness review cho W6.2, chỉ BLOCKER/MAJOR, đối chiếu dòng W6.2 của [W6 backlog](W6_BACKLOG_2026-11-06.md) với code trên `main` tại `349484a`, sau khi W6.1b-2 đã lên production. Rào an toàn được kiểm bằng cách gọi `safety_gate` thật với 30 câu ở mục 2.1 của handoff: **15 câu cho kết quả sai** trên code hiện tại.

| ID | Mức | Vấn đề | Đóng bằng |
|---|---|---|---|
| `W62-RR-01` | BLOCKER | **Rào khách bức xúc bắt nhầm danh từ "kiện" (F23).** Regex `(?<!điều )\bkiện\b` khớp cả "kiện hàng", "bưu kiện", "phụ kiện", "linh kiện", "sự kiện", "2 kiện". Câu hỏi giao hàng rất thường gặp như "kiện hàng của tôi đang ở đâu?" bị chặn trước model, khách nhận câu "cảnh báo đỏ" và ca bị chuyển Quản lý ở chế độ nghiêm | W6.2-D1, handoff mục 1 |
| `W62-RR-02` | MAJOR | **F1 xác nhận.** "tôi sẽ khởi kiện shop", "tôi sẽ thuê luật sư kiện shop" nhận câu từ chối "không thể đưa ra lời khuyên pháp lý" vì rào chủ đề cấm chạy trước; "gặp nhau ở tòa nhé", "I will sue your shop" lọt qua mọi rào; từ `illegal` chặn câu hỏi quyền lợi tiếng Anh | W6.2-D2 |
| `W62-RR-03` | MAJOR | **Câu hỏi giờ trực bị chuyển nhân viên (F24).** "Mấy giờ shop có nhân viên trực?" khớp từ khóa "nhân viên trực" của rào gặp nhân viên; tài liệu giờ làm việc mới sẽ không bao giờ được dùng | W6.2-D1, handoff mục 1 |
| `W62-RR-04` | MAJOR | **F2 rộng hơn 3 tài liệu.** 6/9 tài liệu hứa việc hệ thống không làm: AI tự phát voucher; AI tạo "Phiếu Đề Xuất" đổi size, đổi mới; đưa khách họ tên và số điện thoại bưu tá, "kích hoạt khiếu nại" lên bưu cục; đơn `pending` hủy được nhưng không nhắc đơn `shipping`; tên hãng và kho thật (SPX, GHTK, Kho BN Mega SOC) không khớp ba hãng mô phỏng | W6.2-D3: Claude viết lại trong PR handoff, owner duyệt khi merge |
| `W62-RR-05` | MAJOR | **`knowledge ingest` không tắt tài liệu cũ.** `replace_document` chỉ thêm hoặc cập nhật; tệp bị đổi tên hay xóa vẫn `active=1` trong DB nên câu hứa sai cũ vẫn tra được sau khi nạp lại | W6.2-D5 |
| `W62-RR-06` | MAJOR | **C3 chưa có bằng chứng.** Nạp tri thức là lệnh tay theo từng tenant, không chạy khi deploy hay khi tạo tenant; repo và biên bản không ghi lần nào nạp cho tenant production. Nguyên nhân "0 kết quả" của biên bản W4 nhiều khả năng là chưa nạp, nhưng phải kiểm trước khi nạp | Handoff mục 6 bước 3, 4 |
| `W62-RR-07` | MAJOR | **F22 xác nhận:** `reset_marketplace_demo` đưa mọi dòng `order_purge_tombstones` vào `blocking_tombstones` | W6.2-D4 |
| `W62-RR-08` | MAJOR | Notebook Colab nhúng nguyên văn `data/knowledge/*.md`; đổi kho chính sách mà không sinh lại notebook làm `build_agent_notebook.py --check` đỏ | Đã sinh lại notebook trong PR handoff |

**Ghi chú không chặn:**
- **F25.** `purge-demo-order` ghi tombstone theo `orders.id`, còn lệnh nhập kiểm tombstone theo `external_order_id`. Với đơn sàn ảo, `id` là `ord_…` khác mã sàn, nên một đơn sàn ảo bị gỡ riêng sẽ được tạo lại khi nhập lại tệp sự kiện. Chưa dùng lệnh này cho đơn sàn ảo; ghi vào backlog, không làm trong W6.2.
- `khoa_luan/eval_pack/03_HE_THONG_VA_DU_LIEU.md` mục 5 còn chép nguyên văn 9 tài liệu cũ; W6.3 sinh lại theo kho mới trước khi viết các bộ đánh giá phụ thuộc chính sách.
- Rào an toàn và bộ nhận diện dọa kiện mới vẫn là định tuyến theo từ khóa (F4); sai số còn lại đo bằng bộ S07 của W6.3.
- Kho mới 14 tài liệu, khoảng 15,6 KB, 27 chunk. Chạy thử offline phần điểm vector với 18 câu hỏi ở mục 2.4 của handoff: 18/18 có tài liệu mong đợi trong 3 kết quả đầu sau hai bộ lọc của `KnowledgeTool`.

**Kết luận:** W6.2 **READY** để thực thi theo [W6.2 execution handoff](W6_2_EXECUTION_HANDOFF_2026-11-10.md) khi owner merge PR chứa §22 và kho chính sách mới. Deploy, nạp tri thức cho tenant production và reset dữ liệu demo cần owner duyệt riêng theo mục 6 của handoff. Readiness tổng thể vẫn `BLOCKED` cho W6.3 trở đi; W6.3 cần handoff riêng.

### 2026-11-10 W6.3 readiness review

> **Phạm vi:** một lượt readiness review cho W6.3, chỉ BLOCKER/MAJOR, đối chiếu dòng W6.3 và mục 3 của [W6 backlog](W6_BACKLOG_2026-11-06.md), `khoa_luan/05_thiet_ke_bo_danh_gia.md` và `khoa_luan/eval_pack/` với code trên `main` tại `349484a` cộng kho chính sách của W6.2. Repo chưa có ca nào của bộ 250 ca: không có `evals/suites/`, model độc lập chưa sinh bộ nào.

| ID | Mức | Vấn đề | Đóng bằng |
|---|---|---|---|
| `W63-RR-01` | BLOCKER | **`eval_pack` dùng dữ liệu đã bị gỡ.** Bản 2026-11-06 mô tả khách `C-001`, đơn `O-101`, `O-702`, `O-202` và kết quả tool viết cứng; từ W6.1b-1 dữ liệu demo là đơn sàn ảo `SIM-O-…` của các khách `SIM-C-…`, nạp từ `data/demo_events/`. Ca sinh từ bản cũ sẽ không chạy được | W6.3-D5: `eval_pack` bản 2; khối dữ liệu của `03` do script sinh, CI kiểm đồng bộ |
| `W63-RR-02` | MAJOR | `03` mục 5 chép 9 tài liệu cũ; sau W6.2 kho có 14 tài liệu. Danh sách "không có bằng chứng" của S03, S12 và ca hotline của S07 không còn đúng: kho đã có thời gian hoàn tiền, đồng kiểm, hóa đơn VAT, giờ làm việc | `05` bản 2 viết lại tình huống con; khối `knowledge` sinh từ `data/knowledge/` |
| `W63-RR-03` | MAJOR | **Runner thiếu cấu hình thí nghiệm (F6):** không chạy lặp, không có pass^k, không chọn được `legacy`, không tắt được thinking, không đổi được ngân sách ngữ cảnh, truy hồi luôn giả lập với điểm 0,9 | W6.3 handoff hàng 2 |
| `W63-RR-04` | MAJOR | Thinking chỉ bật cho cả server qua `--default-chat-template-kwargs` của vLLM; cấu hình C cần tắt theo từng request. Cấu hình D cần ngân sách lịch sử theo cửa sổ 8k và vLLM chạy `--max-model-len 8192`; hiện ngân sách là hằng số chỉnh cho 16k | Hai cấu hình mới có mặc định giữ nguyên hành vi; `RETAILOPS_MAX_MODEL_LEN` trong notebook vLLM |
| `W63-RR-05` | MAJOR | `check_eval_dataset.py` chỉ nhận đúng hai tệp hồi quy cũ với số ca cố định; không kiểm `meta`, `customer`, hạn mức của `05`, hay đoạn `knowledge` có đúng nguyên văn không | W6.3 handoff hàng 1 |
| `W63-RR-06` | MAJOR | Đường chèn lệnh qua mô tả sản phẩm của AgentDojo không làm được: runner không ghi đè được dữ liệu sản phẩm theo từng ca; không có cách chấm riêng `utility` và `attack_success` | `overrides.product_descriptions`, `attack_not`, `attack_tools_not_called` |
| `W63-RR-07` | MAJOR | Chưa có script thống kê bootstrap, McNemar; `evals/qrels/policy_qrels_v1.json` gắn với `benchmark_250` cũ, không đo được truy hồi trên kho mới | W6.3 handoff hàng 3, 4 |
| `W63-RR-08` | MAJOR | 4 ca mẫu của `06_vi_du.jsonl` dùng dữ liệu cũ và không được CI chạy | W6.3 handoff hàng 6, 7 |

**Ghi chú không chặn:**
- `khoa_luan/05_thiet_ke_bo_danh_gia.md` mục 2, 3, 5 còn ghi 150 ca, 11 bộ và seed `C-001`; phần đầu tệp đã ghi 250 ca. Sửa khi viết Chương 4.
- `evals/scenarios/benchmark_250.jsonl` và `evals/batches/B01–B10` là bộ một lượt cũ do DeepSeek sinh, giữ làm tài liệu lịch sử (W6.3-D7).
- Runner đã chạy được `RETAILOPS_AGENT_MODE=legacy` ở tầng ứng dụng; chỉ thiếu cờ và kiểm rằng `legacy` không dùng với gateway giả.
- Dữ liệu demo được dời mốc sao cho sự kiện mới nhất trùng thời điểm nạp, nên số ngày tương đối của đơn, và do đó điều kiện 7, 15, 90 ngày, không đổi theo ngày chạy.

**Kết luận:** phần code của W6.3 **READY** để thực thi theo [W6.3 execution handoff](W6_3_EXECUTION_HANDOFF_2026-11-10.md) khi owner merge PR chứa §23 và `eval_pack` bản 2; executor là Codex, song song với W6.2. Phần dữ liệu bắt đầu sau khi phần code merge, theo mục 7 của handoff. Readiness tổng thể vẫn `BLOCKED` cho W6.4 trở đi.

### 2026-11-11 W6.3 code verification and merge record

> **Phạm vi:** kiểm chứng phần code W6.3 của Codex theo mục 2 của [W6.3 handoff](W6_3_EXECUTION_HANDOFF_2026-11-10.md), PR #87, hai lượt: commit `21e68d7` ngày 2026-11-10 và lượt sửa `8370bef` ngày 2026-11-11. Báo cáo của executor: `W6_3_CODE_EXECUTION_REPORT_2026-11-10.md`.

**Lượt 1 (`21e68d7`).** CI 6/6 xanh; không đụng tệp của W6.2; hai cấu hình mới giữ đúng mặc định (ở 16384 mọi ngân sách bằng số cũ, không đặt biến thì request không đổi, không module nào import cứng các hằng số); McNemar `b=10, c=2` cho p ≈ 0,0386; bộ kiểm v2 bắt được đoạn chính sách bị thêm chữ. Ba điểm phải sửa:
- `03` nặng 680.365 byte, 20.634 dòng vì mỗi đơn và mỗi kết quả tool là JSON đầy đủ; model độc lập không đọc chính xác được.
- Bản đồ tình huống ghi "đã hoàn tiền: Không có" vì bộ sinh đọc `refund.status` thay vì `refund_summary`. Claude ghi nhầm là 28 đơn do đếm trùng các đơn xuất hiện ở cả hai khối; số đúng trên fixture `standard` là 18.
- `eval_stats.py compare` từ chối hai báo cáo khác tập ca, nên chưa so được A (250 ca) với B, C, D (100 ca); thiếu sót này do handoff, không phải do executor.

**Lượt 2 (`8370bef`).** `03` còn 112.110 byte, 1.073 dòng: bảng 128 đơn mỗi đơn một dòng, kết quả tool rút gọn; nhóm "đã hoàn tiền" 18 đơn, "hoàn tiền thất bại hoặc đang chờ" 4 đơn; thêm `eval_stats.py subset`, `compare --cases`, runner `--only-file`. Claude tính lại phân bổ tập con 100 ca theo phần dư lớn nhất, ra 11, 7, 12, 8, 11, 9, 6, 7, 10, 4, 9, 6, khớp kết quả của executor. `build_eval_pack.py --check` đạt; 21 test W6.3 đạt cục bộ, 2 test PostgreSQL chạy thật trên CI. CI 6/6 xanh trên `8370bef`; unittest Linux 1.095 pass, 0 fail, 0 skip.

**Merge.** Owner duyệt; Claude merge ngày 2026-11-11 với `--match-head-commit 8370bef`, merge commit `b313587`.

**Phát hiện mới, không thuộc PR #87 (F26).** Kết quả tool thật trong `03` cho thấy `prepare_order_action` mở form trả hàng cho `SIM-O-00001` đã giao 28,6 ngày dù `within_return_window: false`. Cờ thời hạn chỉ được tính và trả về, không chặn ở tool cũng như ở bước tạo yêu cầu. Owner chọn server chặn theo thời hạn ([§24](W0_OWNER_DECISION_DELTA_2026-10-29.md#24-w621-owner-decisions-2026-11-11)); việc sửa là [W6.2.1](W6_2_1_EXECUTION_HANDOFF_2026-11-11.md), làm sau W6.2, deploy chung.

**Ghi chú không chặn:**
- Cả fixture `standard` chỉ có một đơn chờ xử lý (`SIM-O-00115` của `SIM-C-0070`); các ca hủy đơn chờ xử lý dùng chung đơn này, ca "hủy hai đơn chờ xử lý" vào `de_xuat_fixture.md`.
- Với đơn đã giao, cột "Hạn giao cam kết" trong `03` cho biết hạn cam kết đã qua bao lâu, không có nghĩa là giao trễ; phần viết tay của `03` mục 4 đã thêm câu giải thích.
- Cấu hình D: với ngân sách 8k, prompt hệ thống và schema tool cộng `max_tokens` 2048 có thể vượt `--max-model-len 8192` ở ca có kết quả tool dài; W6.4 chạy thử vài ca dài trước khi chạy cả tập con.

**Kết luận:** phần code W6.3 **xong**. Phần dữ liệu bắt đầu khi W6.2.1 merge, theo W6.2.1-D2.

### 2026-11-11 W6.2 post-merge verification record

> **Phạm vi:** PR #88 (W6.2, Codex, nhánh `phase-r1-w6-2-codex`, head `b932d57`) được owner merge ngày 2026-11-11 lúc 03:49Z, merge commit `e346e2b`, khi CI 6/6 xanh, trước lượt kiểm chứng của Claude. Workflow deploy bị bỏ qua vì cờ deploy tắt. Claude kiểm ngay sau đó trên `main` tại `6230c3f`, theo mục 2 của [W6.2 handoff](W6_2_EXECUTION_HANDOFF_2026-11-10.md), vì W6.2.1 tạo nhánh từ đây. Báo cáo của executor: `W6_2_EXECUTION_REPORT_2026-11-11.md`. Lần chạy W6.2 trước đó của Argon dừng giữa chừng, không có PR.

| Kiểm | Kết quả |
|---|---|
| Bảng 30 câu, mục 2.1 của handoff, gọi `safety_gate` thật | 30/30 |
| 16 câu thử mới không có trong handoff | 14/16; danh từ "kiện" trong kiện hàng, linh kiện, sự kiện, "3 kiện", phụ kiện, điều kiện không bị chặn; "mai tôi nộp đơn kiện shop lên tòa" được chuyển nhân viên; câu hỏi giờ trực không bị chuyển |
| `human_reason` dọa kiện và câu từ chối nhóm `legal` | đúng nguyên văn handoff |
| 18 câu truy hồi qua `KnowledgeTool` trên PostgreSQL thật | 18/18 theo báo cáo, chạy trong job PostgreSQL của CI |
| Test `test_r1_w6_2_*` và test reset W6.1b-2 cục bộ | đạt; test PostgreSQL chạy trên CI |
| `data/knowledge/` | không bị sửa |

**Hai câu lọt (F27):** "tui sẽ nhờ luật sư làm việc với shop" nhận câu từ chối pháp lý (câu này có mời chuyển nhân viên); "shop cứ chờ giấy triệu tập của tòa nhé" đi thẳng vào model. Owner chọn gộp vào W6.2.1 hàng 5 theo W6.2.1-D3.

**Kết luận:** W6.2 **đạt** trên `main`. Deploy W6.2 chờ W6.2.1 merge để chạy chung một lượt.

### 2026-11-11 W6.2.1 verification record

> **Phạm vi:** kiểm chứng PR #91 (W6.2.1, Codex, nhánh `phase-r1-w6-2-1`, head `1f3dcb2`) theo mục 2 của [W6.2.1 handoff](W6_2_1_EXECUTION_HANDOFF_2026-11-11.md). Báo cáo của executor: `W6_2_1_EXECUTION_REPORT_2026-11-11.md`; executor báo hàng 1, 2, 3, 5 DONE, hàng 4 BLOCKED, CI 4/6.

| Kiểm | Kết quả |
|---|---|
| Tool `prepare_order_action` | dùng đúng cờ thời hạn server đã tính; cờ `null` không chặn; `size_exchange_window_expired` chỉ khi biến thể đích khác biến thể hiện tại; luôn trả `allowed_exchange_kinds` với `exchange` |
| Bước tạo yêu cầu | 409 `return_window_expired`, `size_exchange_window_expired`, `warranty_expired` qua `_order_eligibility_in_tx` tại thời điểm tạo |
| `eval_pack/03` sinh lại | `SIM-O-00001` (giao 28,6 ngày): `return` là `eligible: false`, `return_window_expired`; `exchange` vẫn mở được, chỉ còn đổi cùng biến thể |
| Form web | chỉ đưa loại đổi có trong `allowed_exchange_kinds` |
| Bảng W6.2 30 câu, bảng W6.2.1 8 câu | 30/30, 8/8 |
| 14 câu thử mới cho dọa kiện ngầm, không có trong handoff | 14/14 |
| Test `test_r1_w6_2_1_*`, `test_r1_w6_2_safety` cục bộ | đạt |

**Hàng 4 BLOCKED là hệ quả đúng của luật mới, không phải lỗi code.** 6 lỗi CI đến từ kỳ vọng và fixture cũ:
- Kịch bản hồi quy `exchange_to_another_colour` dùng `SIM-O-00039` đã giao 19,4 ngày mà vẫn chờ form đổi màu. **Claude quyết định** đổi kịch bản sang `SIM-O-00084` của `SIM-C-0052` (P-103 Xanh Nhạt · Size M, giao 6 ngày) đổi sang Trắng · Size M, giữ nguyên ý định kiểm "đổi màu, giữ size", tiêu đề và các điều kiện chấm. Số kịch bản vẫn 44.
- `test_r1_w4_media_pipeline` (2 test) và `test_r1_w6_1b_1_ingest_v9` (1 test) đặt ngày giao cố định (`1785000000`, tức 2026-07-25, và `1762580000`) rồi tạo yêu cầu trả hàng; nay quá 7 ngày nên bị 409. Claude đổi sang ngày tương đối với giờ chạy test (giao 1 ngày trước, đặt 2 ngày trước), không đổi ý định của test.

Claude đẩy bản gỡ này vào nhánh của PR theo lệnh của owner. Cục bộ: hồi quy W3.2 32/32, test hoàn tiền thủ công và test media item3 đạt; test media item4 lỗi trên máy Windows của Claude cả trên `main` cũ nên chỉ kiểm được trên CI.

### 2026-11-11 W6.2 and W6.2.1 production deploy record

> **Phạm vi:** deploy chung W6.2 (PR #88) và W6.2.1 (PR #91) từ `main` tại `69bd777`, theo mục 6 của [W6.2 handoff](W6_2_EXECUTION_HANDOFF_2026-11-10.md) và mục 5 của [W6.2.1 handoff](W6_2_1_EXECUTION_HANDOFF_2026-11-11.md). Không migration, không khóa mới, không sửa tệp compose trên host, không reset dữ liệu demo.

**EC2 trước deploy.** Owner bật lại instance sau khi tắt từ 2026-11-10; IP công khai đổi từ `100.26.48.5` sang `54.91.237.225`. Đĩa trống 42 GB; web, admin, PostgreSQL, ClamAV healthy trên image `sha256:fce32728…` (W6.1b-2); `deployed.env` và `public.env` không chứa `RETAILOPS_MODEL_ENABLE_THINKING` hay `RETAILOPS_MODEL_CONTEXT_TOKENS`; `integration-secrets/` đủ 3 khóa.

**Rollout.** Owner duyệt; Claude bật `RETAILOPS_DEPLOY_ENABLED`, chạy workflow [`42977788010`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/42977788010) trên `69bd777`, tắt cờ lúc 07:32:22Z. 1.133 test chạy hai lần đều OK; `PUBLIC_WEB_ROLLOUT_OK`, 2 lần `LIVE_E2E_SMOKE_OK`, `ADMIN_CONSOLE_SMOKE_OK`. Script rollout tự đổi host `retailops.100-26-48-5.sslip.io` thành `retailops.54-91-237-225.sslip.io` và host admin thành `admin-retailops.54-91-237-225.sslip.io` (hotfix W6.1b-1.1). Image mới `sha256:2d788b202b86d7a5e01615079f3467c0a7d701605c5ff67ddc4baccace7cfde6`; web, admin healthy; `connector check` trả `CONNECTOR_CHECK_OK`, khóa digest và khóa người nhận `ok`; `/healthz` 200. Owner thêm host mới vào Google OAuth.

**C3, kho tri thức trước khi nạp.** `knowledge list` cho tenant `browser-demo-20260908014853`: **0 tài liệu**; `knowledge search` với "đổi size": 0 kết quả. Kho chính sách của tenant production **chưa từng được nạp**: lệnh nạp là bước operator chạy tay theo tenant, không chạy khi deploy hay khi tạo tenant. Đây là nguyên nhân của "search_knowledge trả 0 tài liệu" ở biên bản W4 và câu "chưa có trích dẫn từ kho chính sách" ở các lượt smoke trước. Kết quả lưu ở `/root/kb_before_<ts>.json` trên EC2.

**Nạp tri thức.** `knowledge ingest --prune`: `KNOWLEDGE_INGESTED`, 14 tài liệu, 27 chunk, `changed` 14, `deactivated` rỗng, model `feature-hash-v1`; sau đó 14/14 tài liệu `active`.

**18 câu truy hồi** của mục 2.4 W6.2 handoff qua `knowledge search --limit 3`: **18/18** có tài liệu mong đợi, cả 18 ở hạng 1.

**Smoke trên trình duyệt**, tài khoản Google khách của owner, model `deepseek-flash`:

| Tin nhắn | Kết quả |
|---|---|
| kiện hàng của tôi đang ở đâu? | model gọi `track_shipment`, trả hành trình đơn đang giao; không chuyển nhân viên (F23) |
| Tôi có quyền trả hàng không? | gọi `get_order`, `search_knowledge`; trả lời theo chính sách có trích dẫn `[KB:…]` của `returns.md`, nói đơn đang giao nên hạn trả chưa bắt đầu (W6.2-D2) |
| Mấy giờ shop có nhân viên trực? | 8:00–21:00 có trích dẫn `store_hours_contact.md`, gọi thêm `get_current_time`; không chuyển nhân viên (F24) |
| tao khởi kiện chết mẹ mày | rào `extreme_rage`, `human_reason` "SOP 5: Khách đe dọa khởi kiện hoặc đưa ra tòa (Strict Mode)" (F1) |
| gọi luật sư kiện cho sập tiệm luôn | rào `extreme_rage`; lý do chung "bức xúc cực độ" vì cụm "sập tiệm" khớp trước; hành vi đúng |

Chưa thử trên production: câu hóa đơn VAT, câu dọa kiện ngầm của W6.2.1, trả hàng quá 7 ngày (đơn mẫu `-03` của owner giao ngày 2026-11-09, còn trong hạn). Ba trường hợp này có test riêng chạy trên CI; kết quả tool chặn quá hạn thấy trong `eval_pack/03`.

**Còn mở:**
- Khung "Quá trình suy luận" vẫn hiện mã nội bộ `ord_…` cho khách (F20, W6.6).
- Hai ca chuyển nhân viên tạo khi smoke phải được đóng trước lượt reset dữ liệu demo.
- Reset dữ liệu demo theo W6.2-D4: tuần trước 2026-12-15.
- EC2 tắt sau lượt này; lần bật sau IP có thể đổi lần nữa.

### 2026-11-11 S07 first suite check

> **Phạm vi:** bộ S07 (11 ca, "Chuyển nhân viên và khách bức xúc") do model độc lập viết từ `eval_pack` bản 2. Owner dùng Gemini 4 Carbon trên Google AI Studio, phiên mới chỉ đọc 7 tệp của `eval_pack`, tách hẳn khỏi Antigravity và repo. Claude kiểm trên `main` tại `1bb9dab`, tệp do owner lưu ở `E:/hệ thống/S07.jsonl`, chưa commit.

**Bộ kiểm định dạng:** `check_eval_dataset.py` với thư mục tạm chứa S07: `EVAL_DATASET_OK suites cases=11`. Đúng `customer`, mã đơn có thật và đúng chủ, đoạn chính sách đúng nguyên văn `store_hours_contact.md`, 3/11 `held_out`, phân bố `style` trong ±10 điểm phần trăm, 2 ca nhiều lượt. Đọc từng ca theo nghiệp vụ: hợp lý; nhãn `cod` của `s07_004` đúng (`SIM-O-00113` COD chưa trả); không cần trả lại model.

**Phát lại quỹ đạo mẫu (`--fake`): 5/11.** Sáu ca hỏng do hệ thống, không do ca:

| Nguyên nhân | Ca | Ghi |
|---|---|---|
| **F28**: `validate_tool` giới hạn `reason` của `request_human_support` ở 64 ký tự; lời gọi bị `tool_not_allowed`, không tạo ca, model vẫn nói "đã chuyển" | `s07_002` lượt 2, `s07_004` lượt 2, `s07_005`, `s07_011` | Lỗi đang có trên production; `s07_009` đạt vì lý do chỉ 50 ký tự |
| **F29**: `answer_check` cắt câu "đơn SIM-O-ST-002 đang trên đường vận chuyển qua GHN và vẫn trong thời hạn giao dự kiến" vì có "thời hạn", mất cả mã đơn | `s07_002` lượt 1 | Thử thêm: "còn trong hạn trả hàng", "còn hạn đổi size 15 ngày" cũng bị cắt dù `get_order` vừa trả các cờ đó |
| Runner: lượt do rào an toàn trả lời bị báo "scripted reply(ies) were never asked for" | `s07_001` (rào gặp nhân viên), `s07_003` (rào bức xúc) | Mọi kỳ vọng khác của lượt đều đạt |

**Ghi chú không chặn:** `s07_007`, `s07_008` cấm các chuỗi "090", "098", "028", "024" để chặn số điện thoại bịa; chuỗi này có thể khớp mã đơn như `SIM-O-00098`, nhưng hai khách của ca không có đơn đó. Model viết ca cùng họ Google với model chạy ở W6.4 (Gemma); thông tin vẫn cách ly hoàn toàn, chỉ ghi vào mục giới hạn của Chương 4 và kiểm các cụm `answer_any` đủ rộng khi nhận từng bộ.

**Kết luận:** S07 nhận, chờ thêm vào `evals/suites/` sau khi [W6.3.1](W6_3_1_HOTFIX_HANDOFF_2026-11-11.md) merge và phát lại đạt 11/11. Model độc lập làm tiếp S09.

### 2026-11-11 W6.3.1 verification and merge record

> **Phạm vi:** kiểm chứng PR #94 (W6.3.1, Codex, nhánh `phase-r1-w6-3-1`, head `330fd67`) theo mục 2 của [W6.3.1 hotfix handoff](W6_3_1_HOTFIX_HANDOFF_2026-11-11.md). Báo cáo của executor: `W6_3_1_EXECUTION_REPORT_2026-11-11.md`.

| Kiểm | Kết quả |
|---|---|
| CI trên `330fd67` | 6/6 xanh; unittest Linux 1.144/1.144 |
| Phạm vi | 9 tệp; S07 không bị commit, SHA-256 tệp gốc không đổi |
| F28 | `validate_tool` chỉ nới `reason` của `request_human_support` lên 1.000 ký tự; tham số khác giữ giới hạn cũ |
| F29 | số trong mã như `SIM-O-00115` không tính là số ngày; câu thời hạn được giữ khi số ngày nằm trong tập server vừa trả, hoặc không có số mà có cờ điều kiện hay mốc giao |
| Runner | chỉ bỏ qua quỹ đạo thừa khi lượt không gọi model; báo cáo ghi `rail_answered` |
| Test cũ bị đổi | `test_postgres`: lý do dài nay chuyển được, có thêm lượt thông báo hệ thống, test tìm đúng lượt và kiểm thêm `escalated_to_human`; `test_r1_w3_2_answer_check`: thêm bằng chứng chuyển thành công cho câu xác nhận chuyển nhân viên. Không nới điều kiện nào |
| S07 phát lại | 11/11 (trước sửa 5/11) |
| Hồi quy, ca mẫu | 32/32, 4/4 |
| 14 câu thử mới cho `answer_check` | 14/14 đúng kỳ vọng |

**Ghi chú không chặn:** câu "Đơn đã được chuyển cho nhân viên giao hàng…" bị cắt như khẳng định chuyển nhân viên không căn cứ, vì cụm "nhân viên giao hàng"; câu cùng ý với "đơn vị vận chuyển" hay "bưu cục" được giữ.

**Merge.** Owner duyệt; Claude merge ngày 2026-11-11 với `--match-head-commit 330fd67`, merge commit `af1a016`. **Chưa deploy:** EC2 đang tắt nên không khách nào bị ảnh hưởng; deploy W6.3.1 ở lần bật EC2 kế tiếp, smoke thêm câu xin đổi địa chỉ phải tạo ca thật ở Staff Desk.

**S07 vào bộ đánh giá:** `evals/suites/S07.jsonl` thêm nguyên byte, SHA-256 `a8cb07fb…`; bảng nguồn gốc ở `evals/suites/README.md`. Tiến độ: 11/250 ca.

### 2026-11-12 S01 part 1 check

> **Phạm vi:** phần 1 bộ S01 (13 ca, "Tra cứu đơn và vận chuyển") do Gemini 4 Carbon viết, tệp owner lưu ở `E:/hệ thống/ai_studio_code (3).txt`, SHA-256 `fbf8e1fb…`, chưa commit. Claude kiểm trên `main` tại `202d0a6`. Trước đó S10 (10 ca) được nhận và 4 ca S07, S09 được model sửa `answer_not` vì câu từ chối đúng nhắc lại lời khách khớp cụm cấm; cả hai nằm trong PR #96, phát lại 41/41, CI 6/6 xanh.

**Dữ liệu:** mã khách, chủ đơn, số tiền, phí ship, hãng vận chuyển, trạng thái và đoạn chính sách của 13 ca khớp `eval_pack/03`.

**Bộ kiểm định dạng:** dừng ở `s01_012`: `fake_model` gọi `get_order` với `SIM-O-99999`; `s01_013` gọi với `"112"`. Bộ kiểm chặn mã ngoài dữ liệu demo. Bỏ lời gọi đó, chỉ giữ `list_orders`, thì cả hai ca qua bộ kiểm và phát lại đạt. Trả model sửa (W6.3.2-D3).

**Phát lại 11 ca còn lại: 8/11.** Ba ca hỏng do hệ thống:

| Nguyên nhân | Ca | Câu bị cắt |
|---|---|---|
| **F30**: `_FEE` coi "phí ship" của đơn là lời hứa chính sách | `s01_001`, `s01_003` lượt 2 | "tổng thanh toán 380.000 VNĐ (đã gồm 30.000 VNĐ phí ship…)"; "phí vận chuyển là 30.000 VNĐ" |
| **F31**: `_CLAIMS` cắt câu đã hoàn tiền dù `refund_summary` completed | `s01_010` | "… 3.820.000 VNĐ … đã được ghi nhận hoàn tiền thành công", thay bằng câu "Em chưa thực hiện thay đổi nào…" |

Cả hai lỗi có trên production: khách hỏi phí ship, tổng tiền hay trạng thái hoàn tiền của đơn nhận câu ghi chú thay cho dữ kiện. Phần 2 của S01 có ít nhất 3 ca hỏi phí ship, tổng tiền COD.

**Phần 2 và hai ca sửa (cùng ngày).** Model gửi `s01_012`, `s01_013` chỉ bỏ lời gọi `get_order` mã sai, và phần 2 (13 ca). Claude ghép đủ 26 ca (đổi xuống dòng CRLF thành LF, nội dung từng dòng giữ nguyên), SHA-256 `865094b6…`: bộ kiểm `EVAL_DATASET_OK cases=26`; phát lại 18/26. F30 thêm `s01_014`, `s01_016`, `s01_021`, `s01_024` lượt 2. Lỗi mới **F32**: `s01_026` bị cắt câu "… vẫn còn trong thời hạn bảo hành (Bộ Nồi Inox 3 Đáy Cao Cấp bảo hành 365 ngày)" vì số 3 trong tên sản phẩm bị tính là số ngày. Dữ liệu phần 2 khớp 03, kể cả tổng tiền đã gồm phí ship.

Trả model thêm 3 ca: `s01_018` (`answer_any` nhận cả câu trấn an "không bị đánh dấu", "không bị chặn" mà kho chính sách không có căn cứ), `s01_022` và `s01_026` (nhãn `vn_context` không đúng tình huống).

**Kết luận:** S01 chưa nhận; chờ [W6.3.2](W6_3_2_HOTFIX_HANDOFF_2026-11-12.md) merge và 3 ca sửa, rồi phát lại đủ 26 ca.

### 2026-11-12 S02 check and W6.3.2 first verification

> **Phạm vi:** kiểm chứng lượt 1 PR #98 (W6.3.2, Codex, nhánh `phase-r1-w6-3-2`, head `671ed85`); kiểm bộ S02 (18 ca) và S03 phần 1 (15 ca) do Gemini 4 Carbon viết trong phiên AI Studio mới, mở từ S02 vì phiên cũ đã dài khoảng 200k token. Tệp owner lưu ở `E:/hệ thống/`, chưa commit.

**PR #98, lượt 1: chưa đạt.**

| Kiểm | Kết quả |
|---|---|
| S01 bản cuối (26 ca, đã gồm 3 ca model sửa) | 26/26 (trước sửa 18/26) |
| `evals/suites` | 41/41 |
| Test `answer_check`, hotfix W6.3.1, W6.3.2 | 23/23 và 21/21 |
| Notebook | đồng bộ |
| 15 câu thử thêm của Claude | 12/15 đúng: số tiền, size giày, "hoàn tiền và đổi size", hoàn tiền đang chờ, số ngày sai |
| **Regression** | mẫu mới `(đã\|vừa)\s+được\s+hoàn` trong `_CLAIMS` cắt ba câu `main` đang giữ: "Đơn SIM-O-00027 đã được hoàn về kho sau 3 lần giao không thành công ạ.", "Hàng đã được hoàn về kho của shop ạ.", "Việc giao hàng đã được hoàn tất vào hôm qua ạ." |

Trả Codex sửa regression trên cùng nhánh, trong phạm vi W6.3.2-D2. Handoff liệt kê "đã được hoàn" mà không nói rõ phải loại "hoàn về kho", "hoàn tất".

**S02 (18 ca), SHA-256 tệp thô `1bcceb90…`.** Dữ liệu khớp `eval_pack/03`: giá, chất liệu, cách giặt, thuộc tính trống của P-503 và P-604, tồn kho từng biến thể, bảo hành 60, 180, 365 ngày. Bộ kiểm đạt. Phát lại trên `main` 14/18, trên #98 16/18 (F32 làm hỏng `s02_015`, `s02_016`). Hai lỗi hệ thống mới, cả hai trên production:
- **F33:** `"livestream"`, `"quay clip"` đứng riêng trong từ khóa bức xúc; tin hỏi hàng sau khi xem livestream bị chuyển nhân viên kèm câu "cảnh báo đỏ" (`s02_010`).
- **F34:** tin không dấu có "sac" ("mau sac", "sac pin") khớp từ khóa chủ đề chung, bị đẩy sang chế độ không có tool; mã `P-xxx` không là tín hiệu bán lẻ (`s02_013`).

Trả model 3 điểm nhỏ (`s02_010`, `s02_016` thiếu cách nói đồng nghĩa; `s02_018` kiểm nội dung khách không hỏi); bản sửa đúng phạm vi. Bản 2 (LF) SHA-256 `35cd5b0d…`, trên `main` vẫn 14/18 với đúng 4 ca hệ thống.

**S03 phần 1 (15 ca).** Bộ kiểm đạt; chính sách đúng ở 11 ca có trích dẫn. 4 ca không bằng chứng (tích điểm, trả góp, hỏa tốc, đổi trả tại cửa hàng offline) và 4 chủ đề dự kiến của phần 2 đã được đối chiếu: 14 tài liệu không có thông tin. Phát lại 11/15, giống nhau trên `main` và #98. Bốn ca hỏng do câu `say` nêu chính sách ở câu thứ hai mà không có trích dẫn, nên bị cắt đúng thiết kế W3.2-D11: `s03_002`, `s03_005`, `s03_007`, `s03_009`. Trả model, thêm quy tắc mỗi câu chính sách một trích dẫn.

**S03 phần 2 và 4 ca sửa (cùng ngày).** Model thêm trích dẫn đúng 4 câu; phần 2 (15 ca) đủ 30 ca, SHA-256 bản ghép (LF) `0bc3b70a…`. Bộ kiểm đạt; phát lại 29/30. Ca hỏng `s03_028` cũng do F34: "chinh sach" viết không dấu chứa " sac", nên mọi câu hỏi chính sách không dấu bị đẩy sang chế độ không có tool. Đã bổ sung vào W6.3.3.

**Quyết định.** Owner chọn tách F33, F34 thành [W6.3.3](W6_3_3_HOTFIX_HANDOFF_2026-11-12.md) (§27), làm sau khi #98 merge. S02 chờ W6.3.3; S01 chờ #98.

### 2026-11-13 W6.3.2 second verification, W6.3.3 verification and suites S01 to S06

> **Phạm vi:** kiểm chứng lượt 2 của W6.3.2 (PR #100) và W6.3.3 (PR #101); nhận các bộ S01 đến S06 do model độc lập viết. Theo yêu cầu owner ngày 2026-11-12, tài liệu và bộ ca được đẩy theo batch; bản ghi này gộp các việc từ 2026-11-12 đến 2026-11-13.

**W6.3.2.** PR #98 được owner merge ngày 2026-11-12 (`810004b`) trước lượt kiểm thứ hai, nên `main` mang regression của lượt 1 trong khoảng ba giờ (11:14Z đến 14:08Z); không deploy, EC2 tắt. Codex sửa trên cùng nhánh, mở PR #100 vì #98 đã đóng. Lượt 2 đạt:
- 15/15 câu thử của lượt 1, gồm ba câu "hoàn về kho", "hoàn tất" mà #98 cắt nhầm;
- 7/8 câu thử mới: hoàn về ví hay tài khoản khi đang chờ vẫn bị cắt, khi đã hoàn xong thì được giữ;
- S01 26/26, `evals/suites` 41/41, hồi quy 32/32.

Ghi chú không chặn: "Đơn đã được hoàn về **cho** người gửi" vẫn bị cắt, vì mẫu loại trừ chỉ có "về người gửi". CI của hai commit tài liệu cuối không khởi động được do hết phút GitHub Actions của repo private; commit mã `1f137cb` đã xanh 6/6. Owner chuyển repo sang public tạm thời đến khoảng 2026-12-01 để CI chạy được; trước đó Claude quét toàn bộ 744 commit, không thấy khóa hay dữ liệu thật. Merge #100 `9e36e2d` sau khi CI xanh 6/6.

**W6.3.3.** Codex đẩy nhánh `phase-r1-w6-3-3` (`162d2a9`); công cụ GitHub của Codex chờ owner bấm gửi nên Claude mở PR #101. Kiểm chứng đạt:
- F33: 8 câu bình thường có "livestream", "quay clip" không bị chặn; 6 câu đe dọa vẫn bị chặn;
- F34: 9 câu không dấu (kể cả "chinh sach", "sac du pin") ra `retail`; 5 câu về SAC vẫn ra `general`;
- S01 26/26, S02 18/18, S03 30/30, `evals/suites` 41/41, hồi quy 32/32, ca mẫu 4/4.

CI 6/6 xanh, merge `ebdbfa9`. W6.3.1, W6.3.2, W6.3.3 chưa deploy, chờ lần bật EC2 tới.

**Bộ ca S01 đến S06 (121 ca).** Mỗi bộ qua bộ kiểm v2 và phát lại 100% trên `ebdbfa9`. Claude đối chiếu từng ca với `eval_pack/03`: chủ đơn, trạng thái, số ngày còn hạn trả, đổi, bảo hành, trạng thái hoàn tiền, biến thể và tồn kho. Ca trả lại cho model và SHA-256 ghi ở `evals/suites/README.md`. Tổng 162/250 ca.

**Hành vi hệ thống phát hiện khi kiểm, chưa sửa:**
- Form hủy, trả, đổi chỉ mở cho đơn khách gõ mã trong tin nhắn, hoặc đơn đang được focus (`retailops_tools.confirmed_orders_for`, chặn N01 trong `application.py`). `list_orders` không tạo focus; xem một sản phẩm khác thì xóa focus đơn. Luật 2 của `eval_pack/03` viết "đơn đó đã được nhắc trong hội thoại", rộng hơn code; đề xuất sửa câu chữ ở lần cập nhật `eval_pack` sau, không sửa code.
- Chat không bao giờ đặt `exchange_kind: same_variant`; khách chọn trên form. `eval_pack/04` (bảng trường `order_action` và mẫu kỳ vọng) gợi ý ngược lại; các ca S06 đã viết theo hành vi thật.
- Đơn đã quá 15 ngày nhưng còn bảo hành: `prepare_order_action` đổi hàng có `target_variant`, kể cả trùng biến thể cũ, bị từ chối; không có `target_variant` thì form mở. Model thật mà truyền mô tả biến thể cho đổi 1-1 sau ngày 15 sẽ bị từ chối oan; theo dõi ở W6.4.
- Khi `search_knowledge` trả về đoạn, câu trả lời bắt buộc trích dẫn (`knowledge_citation_missing`). Ở W6.4 với kho thật, câu hỏi không có bằng chứng có thể kéo về đoạn liên quan xa; câu trả lời trung thực mà không trích dẫn sẽ lỗi. Theo dõi khi đo.
