# Phase R1 — W0 Follow-up Review Handoff (Argon → Opus)

> **Updated:** 2026-10-28
> **Status:** Historical handoff completed: Argon follow-up returned `CHANGES REQUIRED`, followed by the independent Opus 5.5 challenge. Do not reuse the prompt below; rounds 1–4 are historical, and the latest recorded fifth-round result is [W0_ARGON_DOCS_REVIEW_ROUND5_2026-10-30.md](W0_ARGON_DOCS_REVIEW_ROUND5_2026-10-30.md). Use the bounded next-review prompt in [W0_ARGON_DOCS_REVIEW_HANDOFF_2026-10-30.md](W0_ARGON_DOCS_REVIEW_HANDOFF_2026-10-30.md). The [three-wave handoff](W0_THREE_WAVE_DOCS_REVIEW_HANDOFF_2026-10-29.md) is historical and applies only to its reviewed revision. Implementation remains `BLOCKED`; W1–W6 are not authorized. The W0 worktree was based at `bbfd11d0ba4c13514a197a6b25802c4e217bedb3` and contained uncommitted/untracked documentation changes; it was not clean. Argon's report records a direct `git ls-remote origin HEAD refs/heads/main` check at `2026-10-28T22:00:33+07:00` returning `bbfd11d0…` for both refs. A separate local attempt later failed to connect to GitHub; treat that result as historical, timestamp-bounded evidence and recheck before future candidate/readiness/release decisions.

## Historical trigger prompt — completed; do not reuse

You are Gemini 4 Argon performing a **read-only follow-up review** of the Phase R1 W0 packet after the owner clarified decisions on 2026-10-28. Review the current docs and the source baseline; do not implement anything. The supplied 9 BLOCKER / 6 MAJOR / 3 MINOR readiness result remains the controlling implementation verdict unless a newly authorized review changes it. This task cannot authorize implementation.

### Non-negotiable safety boundary

- Do not edit, stage, commit, rebase, merge, push, or create/delete branches or worktrees.
- Do not modify application code, docs, database data/schema, migrations, CI, GitHub settings, AWS/SSM/EC2, Colab, secrets, credentials, or deployment state.
- Do not run application tests, build/deploy workflows, migrations, or commands that write state. You may run only the read-only documentation checks `python scripts/check_docs_contract.py` and `git diff --check`, plus local inspection and Git queries. If any command's side effects are uncertain, do not run it.
- Do not touch or overwrite the separate original checkout at `dd544800`; its dirty patch must remain intact.
- Distinguish owner-provided statements, source-level findings, cached local refs, live remote verification, and runtime facts. Never infer DB counts or deployed behavior from source/docs.

### Establish the exact review target first

1. Report checkout path, branch, `HEAD`, full porcelain status, and whether the worktree is clean. It is expected to contain uncommitted/untracked W0 docs; do not call it clean.
2. The intended source base is `bbfd11d0ba4c13514a197a6b25802c4e217bedb3`. Argon's supplied report records an authoritative read-only `git ls-remote origin HEAD refs/heads/main` at `2026-10-28T22:00:33+07:00`; both refs returned `bbfd11d0ba4c13514a197a6b25802c4e217bedb3`. Local `origin/main` is only a cached ref. A separate shell attempt in this reconciliation failed to connect to GitHub on port 443, so do not claim a newer remote from the cache; repeat the authoritative check when available.
3. Do not rebase, transplant, clean, or alter the working tree. The W0 docs branch is `docs/phase-r1-w0-owner-decisions`; the old `dd544800` checkout is not the R1 base.

### Read these current records first

1. [W0 baseline and decision register](../W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md)
2. [Historical owner decision snapshot](../OWNER_DECISIONS_2026-10-28.md)
3. [Canonical R1 design](../README.md)
4. [W0 review reconciliation](../W0_REVIEW_RECONCILIATION_2026-10-28.md)
5. [Implementation readiness: BLOCKED](../IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md)
6. This handoff and the [archive index](README.md)
7. [Independent audit synthesis](INDEPENDENT_AUDIT_SYNTHESIS_2026-10-26.md) and [implementation handoff](R1_IMPLEMENTATION_HANDOFF_2026-10-26.md)
8. Cross-project summaries: [current project status](../../CURRENT_PROJECT_STATUS.md), [roadmap](../../PLAN_ROADMAP_INDEX.md), [docs index](../../README.md), root [README](../../../README.md), and [acceptance matrix](../../03_EVALUATION/ACCEPTANCE_MATRIX.md).

### Review questions

1. **W0 documentation coherence and links:** verify that the active docs agree on target roles, case/order lifecycle separation, owner direction, readiness state, remote-base provenance, and what remains open. Find broken links, duplicated/conflicting summaries, misleading use of “cancel” for case closure, or any claim that Customer approves a return. Treat dated/archive review snapshots as historical only when labeled as such.
2. **Owner decisions — preserve their exact scope:**
   - Business roles are exactly `customer`, `staff`, `manager`; the owner uses `manager`. `opsadmin` is a separate Ops Admin Console path. `platform_admin` is legacy technical debt to retire gradually, with no alias to Manager or Ops Admin and no transfer of old cross-tenant privileges. `viewer` must fail closed and must never be auto-promoted to Customer.
   - Staff/Manager display name comes from the authenticated Google identity server-side; browser `staff_name` is not trusted actor/audit identity. No trusted name means no canned greeting.
   - `case_id` identifies the selected case. It must be authorized and server-bound before transcript/context or tenant/profile-filtered vector evidence is loaded. Selecting a case for analysis does not claim it.
   - Exactly three case states/buckets: `waiting` (Hàng chờ), `in_progress` (Đang xử lý), `resolved` (Đã xử lý). Do not use `cancelled` as a case state. No customer reply for 20 minutes auto-resolves; a completion signal gets a gentle “anything else?” prompt; if done, request explicit Like/Dislike or 1–5-star feedback and auto-resolve after about 5 minutes. Completed human handoffs go to `resolved`; a customer reply after resolution returns work to `waiting`.
   - Order cancellation, return/refund, handoff episode, case resolution, and customer feedback are separate lifecycles. Pending-order cancellation remains available to Customer, Staff and Manager; Manager may directly update order status. Customer requests a return; Staff or Manager approves/rejects, with decision history and a DB update.
   - Use one shared JSONL format and record/schema contract for integration input and output. Do not invent exact envelope fields, consumer, retry, or transactional guarantees; list them as open until specified. Feedback maps Like or 4–5 stars to `chosen`, Dislike or 1–3 stars to `rejected`; thank the customer and retain it for later offline evaluation/model improvement. One rating must not trigger automatic live-model training.
3. **Source-level security/lifecycle check at the intended base:** read relevant source and tests without modifying them. Confirm or qualify findings about role resolution and membership overwrite, Viewer grants/data scope, `platform_admin` vs `opsadmin`, server-bound actor/case context, customer-safe `/api/events`, `/api/tools/execute`, persistence/foreign-key coupling, handoff persistence and episode resolution, cache/checkpoint isolation, and raw attachments in model payload. Cite exact paths/symbols/lines. If you cannot inspect a source area, say so rather than infer.
4. **Owner-decision register:** list OD-01–OD-08 as owner direction recorded, scope clarified, or still open. In particular, OD-04 authority is now recorded; the remaining questions are Staff's exact order-action scope, return/refund states, DB/audit transaction details, JSONL envelope/consumer/delivery/retry, and data governance—not who requests versus approves a return.
5. **Runtime/provenance:** EC2 is owner-reported OFF; Colab L4 is the owner-reported inference environment; GitHub Actions is the owner-reported CI/CD route. Do not query them. Report runtime/database/membership counts as unavailable unless a sanitized authorized artifact is actually present.

### Required report format

Return a concise report with separate verdicts:

- **W0 docs consistency:** `PASS` or `CHANGES REQUIRED`, with path/line references and only concrete remaining contradictions.
- **GitHub main verification:** `VERIFIED` with exact SHA/date/source, or `UNVERIFIED` with the attempted check and limitation. Do not equate local `origin/main` with GitHub's current main.
- **Source review:** confirmed findings vs owner direction/design vs unverified runtime/database facts.
- **OD-01–OD-08:** recorded direction and remaining open decisions.
- **R1 implementation readiness:** remains `BLOCKED`; W1–W6 are not authorized. Do not issue an implementation PASS or begin code/test/deploy work.
- **Next smallest safe step:** one documentation/reconciliation action only.

Do not edit files. Return findings to the owner for reconciliation; do not attempt to fix them yourself.

## Second-stage prompt — paste into Claude Opus 5.5 after Argon responds

You are Claude Opus 5.5 performing an independent, read-only second review of the Phase R1 W0 documentation and source reconciliation. The owner has supplied Argon's final W0 response; I will provide it after this prompt. First inspect the primary project records linked above and the exact current checkout. Treat Argon's response as a review artifact to challenge—not as ground truth—and distinguish source facts, owner decisions, recommendations, local cached refs, remote verification, and runtime facts.

Do not edit files, stage/commit, alter branches/worktrees, run application tests/builds, access databases/secrets, use AWS/SSM/EC2 or Colab, trigger GitHub Actions, or deploy. The only permitted commands beyond read-only inspection/Git queries are `python scripts/check_docs_contract.py` and `git diff --check`. Do not modify the original dirty `dd544800` checkout. If GitHub is unreachable, say the current remote main is unverified; do not infer it from `origin/main`.

Review whether the docs consistently record: exactly three business roles (`customer`, `staff`, `manager`), separate `opsadmin`, gradual `platform_admin` retirement, Viewer fail-closed/no-auto-promotion, trusted server-side Google display name, authorized server-bound `case_id`, exactly three case states, inactivity/completion/handoff/reopen behavior, separation of case resolution from order cancellation/return/refund, Customer-requested returns approved/rejected by Staff or Manager, one shared JSONL input/output contract, and case-linked Like/Dislike or star feedback without automatic live-model training. Check all current R1 links and stale summaries, and verify the open decisions are not accidentally presented as settled. Challenge Argon's source claims on security, persistence, workflow, caches/checkpoints, provider payloads and over-engineering; suggest simpler safe first-slice options without choosing owner policy.

Return: (1) W0 docs verdict `PASS` or `CHANGES REQUIRED`; (2) exact Git base/remote verification limits; (3) concrete contradictions/link defects with paths; (4) source findings versus owner direction versus runtime unknowns; (5) OD-01–OD-08 recorded direction and remaining gates; (6) minimal future test/build command plan for a separately authorized implementation review, but do **not** execute application tests now; and (7) whether Argon's verdict is supported or where it is not. R1 implementation remains `BLOCKED`; this review cannot authorize W1–W6.

## Previous trigger prompt — superseded; retained for historical provenance only

> Historical only. Do not paste or execute the prompt below; it predates the latest owner clarifications and the current inability to verify GitHub `main` from this environment.

## Historical W0 prompt (kept for provenance)

You are Gemini 4 Argon acting as a READ-ONLY Phase R1 W0 reconciliation and owner-decision reviewer for this repository. Your task is to verify and report the current implementation gate, not to implement features.

### Hard scope boundary

The latest owner-reported implementation-readiness verdict is BLOCKED (9 BLOCKER, 6 MAJOR, 3 MINOR). Treat these counts as owner-provided review evidence; do not claim that you independently reproduced the Argon review unless you actually have its full report and have re-run that review. W0 is limited to source/docs inspection and read-only GitHub/base verification.

Do not edit files; write or patch application code; create, rebase, merge, or push branches; run tests or CI; connect to or query any live database; access credentials or secrets; use AWS/SSM/EC2 or Colab; run migrations; deploy; or contact people. Do not start W1–W6. If your environment cannot complete a read-only check, report the limitation and stop at that boundary.

### Required work

1. **Verify the source base.** Inspect the current checkout and working-tree state without changing it. Confirm the current GitHub main head through an authoritative read-only remote source; do not assume a cached local origin/main is current. The W0 documentation branch was based on bbfd11d0ba4c13514a197a6b25802c4e217bedb3. If GitHub main has advanced, report the exact SHA/date and the difference; do not rebase or transplant this packet. Keep the older dirty dd544800 checkout untouched.
2. **Reconcile roles from source.** At the verified base, trace viewer, platform_admin, and opsadmin through role grants, Google role resolution, existing-membership updates, session/version behavior, route authorization, schema/migrations, CLI and tests. Report concrete paths, symbols, and line references. Separate current source behavior from target owner policy. Do not infer database membership counts from source.
3. **Confirm the recorded owner direction without extending it.** Target business roles are customer, staff, and manager; the store owner uses manager. opsadmin is a separate Ops Admin Console account/path. platform_admin is legacy technical debt to deprecate gradually; do not alias it to manager or opsadmin and do not transfer its historical cross-tenant grants. viewer is legacy, must fail closed, and must never be silently promoted to customer. Staff/Manager identity comes from the authenticated Google account on the server; browser staff_name is not actor/audit identity; absent a trusted display_name, show no canned greeting.
4. **Assess the W0 contract snapshot.** Review the proposed immutable per-request ExecutionContext, API schemas, case lifecycle and transition candidates. Identify which invariants are supported by recorded owner direction and which exact DTO fields, grants, state transitions, or storage rules remain unresolved. In particular, check principal/role/tenant/profile/case binding, mutable singleton context bleed, object authorization, customer-safe events, internal-tool binding, cache/checkpoint partitioning, and raw attachment exclusion from model payload. Do not label the full contract or transition table frozen while policy-dependent choices remain open.
5. **Keep case identity separate from retrieval evidence.** case_id identifies the authorized chat segment; verified conversation/message/handoff/order-action links provide bounded case context. Vector or lexical search is a separate tenant/profile-filtered evidence projection and cannot identify or authorize the case. Selecting a case for pre-analysis does not claim it or change its status.
6. **Report inventory limits honestly.** No live DB membership inventory has been performed. EC2 is reported OFF by the owner; no runtime check is authorized in this task. Do not connect to production. State what an aggregate-only viewer/platform_admin membership and linked-session inventory would need to count, and mark the actual counts unavailable unless a sanitized authorized snapshot is already present in the repository.
7. **Disposition OD-01–OD-08.** Preserve the distinction between owner direction, target shape, recommendation, and open policy. OD-01 has a gradual-retirement direction but still needs ADR, eligibility, session/audit and rollback design. OD-02 has fail-closed/no-auto-promotion and remove-if-safe/otherwise-disable direction; inventory and migration mechanics remain open. OD-03 has exactly three case states (`waiting`, `in_progress`, `resolved`) and no case `cancelled` status; 20-minute inactivity auto-resolve; customer completion → gentle follow-up → explicit satisfaction feedback → approximately 5-minute auto-resolve; completed handoff resolves into Completed and customer reply requeues to waiting. Timer/assignment/reopen mechanics remain open. OD-04 has owner direction for pending-order cancellation by Customer/Staff/Manager, Manager direct status update, Customer as return requester, and Staff/Manager as return approvers; preserve history/DB update and use one JSONL format/schema family for integration input and output. Staff action scope, return states, exact JSONL schema/delivery/retry and feedback data governance remain open. OD-05 means the app's `/api/cancellation-proposals*`, not provider APIs; keep/adapt/supersede is undecided. OD-06 return/refund vocabulary, OD-07 migration/version/rollback, and OD-08 evidence storage/security/retention remain open.
8. **Return a bounded report.** Give one W0 verdict: READY FOR OWNER DECISION or BLOCKED. A READY FOR OWNER DECISION verdict means only that the evidence and unresolved decision list are ready for the owner; it never means implementation-ready. Include:
   - verified GitHub main SHA/date and the inspected checkout SHA/status;
   - a source-inventory table for viewer, platform_admin, and opsadmin;
   - confirmed source findings versus design claims, runtime-unverified facts, and unknown database counts;
   - a contract table separating frozen direction from candidate fields/transitions and open questions;
   - OD-01–OD-08 status, without silently selecting policy;
   - the smallest safe next step for the owner.

Do not issue an implementation-readiness PASS or authorize coding. W1–W6 remain blocked until the owner resolves the open decisions and requests a fresh readiness review on the exact verified base.

### Related project records to read first

- W0 register: docs/phase_role_aware_ops/W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md
- Owner decision delta: docs/phase_role_aware_ops/OWNER_DECISIONS_2026-10-28.md
- Canonical R1 design: docs/phase_role_aware_ops/README.md
- Current blocked readiness: docs/phase_role_aware_ops/IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md
- Independent source/audit synthesis: docs/phase_role_aware_ops/INDEPENDENT_AUDIT_SYNTHESIS_2026-10-26.md
- Existing implementation handoff and acceptance contract: docs/phase_role_aware_ops/R1_IMPLEMENTATION_HANDOFF_2026-10-26.md
- Archive index and superseded prompts: docs/phase_role_aware_ops/archive/README.md

---

## Historical handoff context (superseded)

This prompt is deliberately a W0 closeout task. It is not the archived implementation trigger and does not authorize Argon or another agent to write the R1 feature code. The owner-provided Argon review remains BLOCKED at 9 BLOCKER / 6 MAJOR / 3 MINOR. A previous documentation/design review PASS concerns documentation consistency only.

The W0 documentation branch was created at bbfd11d0ba4c13514a197a6b25802c4e217bedb3. The original dd544800 checkout contains a separate dirty patch and must not be used as the R1 coding base. Argon's follow-up report records a successful direct GitHub check at `2026-10-28T22:00:33+07:00`; the later local `git ls-remote` failure is a separate transport result. Neither result proves deployment or a newer remote after that timestamp. This handoff is completed historical material; its prompts are not active. The later [2026-10-29 three-wave docs review handoff](W0_THREE_WAVE_DOCS_REVIEW_HANDOFF_2026-10-29.md) was used for a separate docs-only review and does not authorize implementation.

Owner-reported operating setup: model inference uses Colab L4 when enabled; AWS EC2 is currently OFF; GitHub Actions is used for CI/CD management, tests, and deployment. These are owner reports, not fresh runtime/CI observations in this handoff. Do not start or query those systems.

## Source-review map

At the verified base, inspect the relevant paths and search for related call sites rather than assuming this list is exhaustive:

- Role permissions and capability mapping: retailops/business/permissions.py
- Google role resolution: retailops/http/auth_google.py
- Identity membership, role changes and auth-version invalidation: retailops/identity/store.py and retailops/identity/persistent.py
- Persistent schemas and repositories: retailops/storage/pg_schema.py and retailops/storage/pg_repositories.py
- API routes, staff operations, customer events and tool execution: retailops/http/routes.py
- Shared graph and supervisor/escalation workflow: retailops/workflow/graph.py and retailops/workflow/supervisor.py
- Tool binding and escalation persistence: retailops_tools.py and relevant retailops/business modules
- Staff/Manager and customer UI: web/app.js and web/index.html
- Current design, decisions and prior findings: the linked records above

Report exact source locations and behavior. Treat prompts and docs as design evidence, not proof that code or runtime already behaves that way.

## Owner-decision status at handoff — historical snapshot (2026-10-28)

| ID | Recorded direction/target | Still open |
|---|---|---|
| OD-01 | Gradually retire platform_admin; keep opsadmin separate; no runtime alias or privilege transfer. | ADR, aggregate inventory, eligibility, session/audit treatment, compatibility and rollback. |
| OD-02 | viewer is legacy; fail closed; never auto-promote to customer; remove a membership only when safe, otherwise disable application access and invalidate affected sessions. | Safe-removal criteria, actual aggregate counts, login synchronization and migration/rollback mechanics. |
| OD-03 | Exactly three case states/buckets: waiting, in_progress, resolved; do not use `cancelled` for case closure. 20-minute inactivity auto-resolve; completion → gentle follow-up → feedback → ~5-minute auto-resolve; completed handoff resolves; customer reply requeues to waiting. | Timer/assignment/reopen mechanics; satisfaction-event schema/privacy/retention. |
| OD-04 | Pending-order cancellation by Customer/Staff/Manager; Manager direct order status update; Customer requests return; Staff or Manager approves/rejects; preserve audit/DB state; use one shared JSONL format and record/schema contract for integration input/output. | Staff's exact acting-for-customer scope; return/refund states; DB/audit transaction consistency; exact JSONL envelope/fields, consumer, delivery and retry. |
| OD-05 | The application's `/api/cancellation-proposals*` business API, not DeepSeek/OpenAI/provider API. | Retain, adapt, or supersede existing endpoints; compatibility/deprecation plan. |
| OD-06 | Keep case closure separate from order cancellation/refund. | Canonical return-request and post-approval order-state vocabulary. |
| OD-07 | No migration strategy is approved. | Versioning, compatibility, backup, session handling and tested rollback. |
| OD-08 | Evidence is optional, protected, and excluded from model context by default; Gemma 4 12B image capability is documented. | Storage, allowed MIME/types, size/count limits, scanning, serving authorization, retention/deletion and backup; the supplied Colab startup cell and current application attachment path still need a separately authorized image/PDF runtime check. |

## Records after the prompt

- [W0 baseline and decision register](../W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md)
- [Historical owner decision snapshot](../OWNER_DECISIONS_2026-10-28.md)
- [Current owner decision delta](../W0_OWNER_DECISION_DELTA_2026-10-29.md)
- [Canonical Phase R1 design](../README.md)
- [Implementation readiness: BLOCKED](../IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md)
- [Independent audit synthesis](INDEPENDENT_AUDIT_SYNTHESIS_2026-10-26.md)
- [Existing implementation handoff](R1_IMPLEMENTATION_HANDOFF_2026-10-26.md)
- [Archive index](README.md)
- [Project status](../../CURRENT_PROJECT_STATUS.md)
- [Roadmap](../../PLAN_ROADMAP_INDEX.md)
- [Acceptance matrix](../../03_EVALUATION/ACCEPTANCE_MATRIX.md)
