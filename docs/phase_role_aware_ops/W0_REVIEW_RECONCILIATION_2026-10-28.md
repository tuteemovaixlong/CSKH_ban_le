# Phase R1 W0 — Review Reconciliation

> **Updated:** 2026-10-30 · **Scope:** documentation/source reconciliation only. This file is the canonical W0 docs-review chronology. Implementation remains `BLOCKED`; W1–W6 are not authorized.

## Verdicts apply to different checkouts

The latest Opus report supersedes its earlier path-specific report and reviews the original dirty checkout at `dd544800`. Argon reviews the newer W0 worktree at source revision `bbfd11d0`. Their W0 verdicts therefore do not conflict:

| Review | Checkout | W0 verdict | Meaning |
|---|---|---|---|
| Opus, corrected path | `dd544800` plus dirty local patch | `BLOCKED` | This checkout is not a suitable R1 evidence/base: it is 38 commits behind reported `main` and has uncommitted code/docs changes. |
| Argon follow-up (prior W0 packet) | W0 worktree at `bbfd11d0` | `CHANGES REQUIRED` | The owner direction was substantially consolidated, but the concrete documentation contradictions listed in that report required reconciliation. It is not implementation readiness. |
| Argon owner-delta docs review (2026-10-29, historical) | Same W0 docs tree at source revision `bbfd11d0` | `CHANGES REQUIRED` (0 BLOCKER / 3 MAJOR / 3 MINOR) | Historical; superseded by the 2026-10-30 docs-review sequence below. |
| Argon docs review, rounds 1–5 (2026-10-30) | W0 documentation working tree at `bbfd11d0` plus the reviewed uncommitted docs packet | `CHANGES REQUIRED` in each round | Individual revision-bounded results remain preserved; this table is the only current chronology index. |
| Argon docs review, sixth round (2026-10-30; owner-pasted report) | W0 docs review; report identified stale current labels and duplicated/mixed review-history lists | `CHANGES REQUIRED` (0 BLOCKER / 0 MAJOR / 2 MINOR: `R6-01`, `R6-02`) | R6-01/R6-02 corrections are synchronized locally below; no further Argon review is requested and no Argon `PASS` is claimed. |
| Implementation gate | Owner-provided Argon result | `BLOCKED` (`9 BLOCKER / 6 MAJOR / 3 MINOR`) | Preserve the block; W1–W6 are not authorized. The exact 9/6/3 register was not independently reproduced here. |

The W0 worktree is branch `docs/phase-r1-w0-owner-decisions` at `bbfd11d0ba4c13514a197a6b25802c4e217bedb3`. It has uncommitted documentation changes, but no application-code edits. The original checkout is `feat/phase5-sales-simulator-import` at `dd544800bb087d54a7faf564e723736905620045`; preserve its dirty patch in place. That patch removes non-live sample-order seeding and does not change RBAC.

Argon's follow-up report records the read-only command `git ls-remote origin HEAD refs/heads/main` against GitHub at **2026-10-28T22:00:33+07:00**, with both refs returning `bbfd11d0ba4c13514a197a6b25802c4e217bedb3`. This is timestamp-bounded evidence supplied by Argon. A separate fresh `git ls-remote` attempt in this reconciliation could not reach GitHub; local `origin/main` still points at that SHA. Keep the successful report and failed shell attempt as separate provenance, and repeat a read-only remote check before any later branch, PR or deployment decision.

## Historical owner-delta documentation review (2026-10-29)

Argon's 2026-10-29 review returned `CHANGES REQUIRED` (**0 BLOCKER / 3 MAJOR / 3 MINOR**) and is historical. It identified stale review-scope/index links, incomplete OD-08 propagation, superseded timer/model wording, inconsistent Git evidence, machine-specific paths, and duplicated/underspecified role gates. Its owner-provided summary is [here](archive/W0_ARGON_LATEST_OWNER_DELTA_REVIEW_2026-10-29.md). The later 2026-10-30 rounds are recorded in the canonical chronology and findings section below. Implementation remains blocked.

## Source findings reconciled at `bbfd11d0`

- **Google role synchronization:** allowlists fall back to `DEFAULT_ROLE` or `customer`; an existing membership is updated when the new resolved role differs. This can promote `viewer` or change an existing Staff/Manager role. Do not silently promote/demote.
- **New Viewer data-scope risk:** `IdentityStore.create_membership` only applies the customer-link collision check for role `customer`. A `viewer` may share a `customer_id` with a real customer. Since `viewer` has `READ` and read routes use the session's customer scope, that state may expose the customer's data. This is source-level possibility, not proof it occurs in the real DB. Aggregate inventory must count same-tenant Viewer/customer ID sharing without emitting IDs or PII.
- **Customer-row insertion:** Opus is correct at `bbfd11d0`: `PersistentSessions.login_google` inserts a `customers` row unconditionally. Argon's claim that this happens only for `customer` is inaccurate. This coupling may create customer rows for Staff/Manager; it qualifies the checkpoint-FK concern but does not prove every such path fails.
- **Manager order mutation:** `/api/manager/orders/update-status` can directly change order state, including `pending` to `cancelled`. Include it in OD-04/OD-05.
- **Role constraint drift:** the main source's schema/repository permit five roles, while `scripts/update_ec2.py` attempts a four-role constraint with `check=False` and does not reliably verify command success. The live DB constraint is unknown.
- **Shared findings:** the reports confirm Viewer POST routes, mutable `Application.current_binding`, client-supplied `staff_name`, unbound `/api/tools/execute`, and handoff persistence/resolve risks.
- **Cache nuance:** `SemanticCache` is per `Application`, cached per membership; there is no demonstrated current cross-tenant leak. `ToolCache` is shared per tenant and keyed by tenant/customer/tool/arguments. For internal profiles, bypass caches initially or prove case/profile/projection isolation.
- **Attachment path correction (2026-10-29):** the model card for the exact safetensors Gemma fine-tune supports image input, but the application hard-codes this model ID as text-only and converts images to a filename notice. That is an app-side forwarding mismatch, not evidence that the weights lack vision. The Colab cell starts vLLM/ngrok but sends no image request and does not parse PDFs/documents; runtime capability remains unverified. See [the latest W0 owner delta](W0_OWNER_DECISION_DELTA_2026-10-29.md#8-od-08--re-evaluation-of-imagefile-support).
- **Canonical profile names:** `customer_chat`, `staff_case_assist`, `manager_ops_assist`. Argon's `customer_commerce` and `staff_case_ops` labels are not canonical.

The corrected-path Opus report also contains `dd544800`-specific findings, including missing `platform_admin`/P5-E surfaces, weaker Google tenant checks and the dirty sample-order patch. Those historical findings do not override source at `bbfd11d0`.

## Required controls and simplification proposals

Keep per-request immutable context, server-side actor/role/tenant/profile/case binding before retrieval or tool execution, internal/customer transcript isolation, raw-attachment exclusion from model payloads by default, durable handoff acknowledgement, episode-specific resolution and exact provider-payload tests.

Potential first-slice simplifications are bypassing caches for internal profiles, deferring context serialization/versioning, or excluding evidence upload. These are proposals, not approvals. Stateless internal AI is not yet decided: Staff/Manager need follow-up questions about a selected case. Whether assist history is shared per case or partitioned per staff member remains open. Never reuse Case A context in Case B. Whether handoff episodes need a separate table is also an implementation choice; the durable model must preserve episode IDs so resolving an old episode cannot close a newer one.

## Owner decisions and next gate

This 2026-10-28 reconciliation is retained for review provenance. The newer [2026-10-29 W0 owner decision delta/proposals](W0_OWNER_DECISION_DELTA_2026-10-29.md) controls where it records a newer owner direction and keeps the proposed details explicitly unapproved.

| ID | Direction recorded | Still open |
|---|---|---|
| OD-01 | Keep `opsadmin` in its separate Ops Console; gradually retire `platform_admin`; do not transfer its historical cross-tenant privileges to Manager. | Exact Manager same-tenant `/api/admin/*` scope versus Ops Console boundary remains unselected; ADR, inventory, eligible mapping, session/audit, compatibility and rollback. See 2026-10-29 proposal. |
| OD-02 | **Latest owner direction recorded:** disable Viewer app access; remove membership rows only where safe; otherwise freeze/lock and phase out. | Safe-removal criteria, aggregate collision/session inventory, login synchronization guard, session invalidation and migration/rollback rules. |
| OD-03 | **Latest owner direction recorded:** exactly `waiting` / `in_progress` / `resolved`; no case `cancelled`; 3 minutes without customer reply marks the interaction inactive; every customer reply resets the timer; 1.5 minutes is allowed only in non-production evaluation/specialized test states and never production; overload never auto-closes staff-owned work; completion follow-up and prior ~5-minute post-feedback direction remain distinct. | Exact timer anchor/eligible event and inactive-to-case transition, races/idempotency, completion intent, reopen/history, assist-history sharing and feedback governance. |
| OD-04 | **Owner direction recorded:** pending-order cancellation remains available to Customer, Staff and Manager; Manager may use direct order-status update. Customer requests a return; Staff or Manager approves/rejects. Preserve decision history and DB update; use one shared JSONL data format and record/schema contract for integration input and output. | Proposed permission matrix and DB/outbox/JSONL pattern require owner selection; see latest delta. |
| OD-05 | **Scope clarified:** this is the application's `/api/cancellation-proposals*`, not an LLM provider API. | Proposed compatibility facade and separate return routes require owner confirmation. |
| OD-06 | Case closure is separate from order outcomes. | Proposed separate return/refund vocabulary in latest delta requires owner confirmation. |
| OD-07 | Owner acknowledges migration/backup/session invalidation/rollback as necessary. | Versioning, compatibility, backup, sessions and tested rollback mechanics remain unselected. |
| OD-08 | Image/file processing is included as planned R1 scope across W0–W6; the eventual Colab path may process real data only after explicit secure enablement, using compact case-bound context. | Current application adapter suppresses image pixels for exact Gemma model ID; public Colab/ngrok has no configured vLLM API key and unverified privacy/request controls; current limit is 8,192 tokens and 16,384 is evaluation-only pending L4 evidence. Colab/L4 end-to-end is not tested; storage, type/size/count, scanning, authentication/access, retention/deletion, PDF/OCR and protected projection remain open. |

EC2 OFF, Colab L4 and GitHub Actions usage are owner-reported; no runtime/workflow was checked. The deploy workflow treats `workflow_dispatch` as deploy-eligible after branch and `RETAILOPS_DEPLOY_ENABLED` gates, so do not use it to run tests. Proposed PowerShell/DB commands were not run; `<local-disposable>` placeholders need replacement, and the old checkout's DB guard does not validate host.

Historical review note: the reconciled W0 packet was passed to the independent Opus 5.5 read-only challenge in the [completed historical Argon → Opus handoff](archive/W0_ARGON_RECONCILIATION_HANDOFF_2026-10-28.md). The [three-wave docs review handoff](archive/W0_THREE_WAVE_DOCS_REVIEW_HANDOFF_2026-10-29.md) and its focused Argon `PASS` apply only to the previous docs revision; they do not cover the later owner-delta review result above. No code, live DB or W1–W6 work is authorized by this note.

## Related records

Current records:

- [Canonical R1 design](README.md)
- [Latest W0 owner decision delta/proposals 2026-10-29](W0_OWNER_DECISION_DELTA_2026-10-29.md)
- [W0 baseline and decision register](W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md)
- [Implementation readiness: BLOCKED](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md)
- This file is the canonical review chronology; see the closure note at the end.

Historical review results and handoffs remain in their original files; this chronology is authoritative for sequence/current status. See the [archive index](archive/README.md) for retired prompts.


## 2026-10-30 docs-review chronology and closure

Rounds `RF` (0/4/4), `R2` (0/0/4), `R3` (0/0/5), `R4` (0/0/3), and `R5` (0/0/3) are historical; each original result remains unchanged in its dated record. The supplied R6 report returned `CHANGES REQUIRED` (0/0/2): **R6-01** found R4 still labeled current in the root README and owner-delta result; **R6-02** found omitted R4 links and historical review links mixed into current-source lists. The root README and owner-delta result now identify R6 as latest; this existing reconciliation is the single chronology index, so other indexes should point here rather than repeat round lists. Historical handoffs/review records are retained as revision-bounded records, not active prompts.

**Closure (2026-10-30):** the R6 corrections are applied and the documentation-only review loop is **closed**. All completed review results and handoffs were moved to the [archive](archive/README.md); active pages link here instead of repeating review rounds. No further docs-only review is requested and no Argon `PASS` is claimed. The next review is a single **implementation-readiness review** on an exact clean candidate: one pass, BLOCKER/MAJOR findings only, a fresh self-contained finding register, verdict `READY` or `BLOCKED`, recorded directly in [implementation readiness](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md) without creating a new review file. Implementation remains `BLOCKED`; this record authorizes no code, tests, CI, migration, merge, deployment, or runtime work.
