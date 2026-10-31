# Gemini 4 Argon — Phase R1 Implementation Trigger

> **SUPERSEDED — DO NOT EXECUTE (2026-10-29).** This historical prompt conflicts with the current sequential delivery policy, contains stale implementation/testing instructions, and cannot clear the owner-provided `BLOCKED` readiness state. Use only for provenance. Any future implementation prompt requires explicit owner authorization after fresh base verification and a completed readiness review that clears the gate.

Read these files first:

- `docs/phase_role_aware_ops/W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md`
- `docs/phase_role_aware_ops/README.md`
- `docs/phase_role_aware_ops/R1_IMPLEMENTATION_HANDOFF_2026-10-26.md`
- `docs/phase_role_aware_ops/INDEPENDENT_AUDIT_SYNTHESIS_2026-10-26.md`
- `docs/phase_role_aware_ops/ARGON_FINAL_FOCUSED_DOCS_REVIEW_2026-10-26_RESULT.md`
- `docs/CURRENT_PROJECT_STATUS.md`, `docs/PLAN_ROADMAP_INDEX.md`, `docs/03_EVALUATION/ACCEPTANCE_MATRIX.md`

You are Gemini 4 Argon, the **implementation agent** for Phase R1. The documentation/review assistant is a separate role: it maintains docs and independently challenges your reports/diffs, but it does not implement or repair application code. The W0 register is the current scope and evidence boundary; older reviews apply only to their cited refs.

## Execution rules

- Work in an isolated clean candidate based on a verified post-PR-46 mainline. `bbfd11d0ba4c13514a197a6b25802c4e217bedb3` is locally verified as a cached post-PR-46 baseline (PR #47 merge, available fetch evidence no later than 2026-10-24); do **not** claim it is today’s latest GitHub `main` without verifying that separately. Never transplant the dirty `dd544800` working-tree patch wholesale.
- First perform a read-only source inventory and decision preflight. Then implement small, reviewable R1 slices for all fully specified owner directions. Do not block safe characterization/foundation work because an unrelated owner choice is open; stop only at the exact affected privilege, lifecycle, or migration boundary and return one consolidated owner question list.
- Do not silently promote `viewer`, overwrite an existing membership role with a new-account default, equate `platform_admin` with `opsadmin`, or grant Manager cross-tenant/platform-admin capability. The owner direction is to retire `platform_admin`, but database migration execution still requires a separate ADR, aggregate inventory, migration/rollback plan, tests and explicit production approval.
- Preserve the invariant: three business roles (`customer`, `staff`, `manager`); owner uses `manager`; `opsadmin` is a separate Admin Console login; one shared workflow/graph; selected-case server binding for Staff/Manager AI; three case buckets and separate handoff/order-action lifecycles; cancel/return requires human review; AI is advisory only.
- No production database writes, production migrations, EC2/SSM actions, merge, or deploy without separate owner approval. Local candidate code/tests are within the implementation task once the candidate baseline and affected policy are clear.

## Bounded independent code review

- Use at most **three direct sub-agents in one parallel review round**: Security/RBAC, Domain/Persistence, and Workflow/AI/UI.
- Give each the exact candidate SHA/diff, acceptance criteria and a distinct read-only review scope. Do not let reviewers spawn/fork additional agents or chats. Do not repeat a full three-agent round for every small edit; fix findings and re-run only targeted checks, then request one focused re-review if needed.
- Return reviewer names/IDs, exact prompts, findings, dispositions and test evidence. Your own review does not count as independent approval.

Your work/report must:

1. State the exact checkout/ref you inspected. `bbfd11d0ba4c13514a197a6b25802c4e217bedb3` is locally verified as a cached post-PR-46 baseline (PR #47 merge, fetched no later than 2026-10-24 in the available record), but **is not verified as today’s latest GitHub main**. Do not claim otherwise.
2. Inspect actual code and tests for identity/role provisioning, API authorization and actor attribution, case/handoff lifecycle, cancellation/return, workflow/checkpoint, tools/cache/quota/audit. Distinguish verified current source behavior from R1 target and conditional risk; cite paths and symbols/line ranges.
3. Confirm the eight owner directions in `ARGON_OWNER_DIRECTION_REVIEW_2026-10-26_RESULT.md` are design directions already reflected in docs, not eight unresolved approvals. Separately list the implementation decisions still open in the W0 register.
4. Preserve the role boundary: exactly `customer`, `staff`, `manager` as business roles; owner uses `manager`; `opsadmin` is a separate Admin Console path. `platform_admin` retirement is an owner-directed target requiring its own ADR, aggregate inventory, migration tests and rollback plan. `viewer` is legacy; never silently promote it or overwrite an existing membership role with a new-login default. Do not change role behavior until its disposition is approved.
5. Preserve one shared workflow/graph, selected-case server binding for Staff/Manager AI, the three case buckets, a separate handoff view, distinct case/handoff/order-action lifecycles, human review for cancel/return, and AI advisory-only behavior.
6. Identify broken/stale docs links, source paths and status claims, including the known incorrect `retailops/retailops_tools.py` reference (the source file is at repository root as `retailops_tools.py`). Do not alter the historical Argon PASS record.
7. Implement W0 characterization/foundation and the fully specified implementation slices; add direct tests tied to acceptance. Preserve unresolved policies as fail-closed. For any blocked policy boundary, make no implicit decision and list the exact owner choice needed.
8. Return exact files changed, candidate/base SHA, migration/schema changes (if any), test commands/results, independent reviewer identities/prompts/findings, unresolved owner decisions, and remaining risks. Distinguish local test evidence from CI, deployment, and live runtime.

Do not claim implementation, merge, CI, deployment, EC2 or production runtime approval from this prompt. Stop before any production mutation and wait for explicit owner approval for those gates.
