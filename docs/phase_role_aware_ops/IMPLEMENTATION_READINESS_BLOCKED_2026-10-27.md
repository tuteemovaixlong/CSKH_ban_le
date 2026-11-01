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
