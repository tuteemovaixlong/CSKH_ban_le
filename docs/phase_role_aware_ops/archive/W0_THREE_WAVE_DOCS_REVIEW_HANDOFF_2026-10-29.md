# Phase R1 — Focused Argon Documentation Re-review Handoff (2026-10-29)

> **Purpose:** one focused, read-only review of the repaired three-wave documentation delta after the Argon and Opus reviews. This is **not** an implementation-readiness review and cannot authorize W1–W6. The owner-provided implementation-readiness verdict remains `BLOCKED` (9 BLOCKER / 6 MAJOR / 3 MINOR); only W0 read-only work is currently allowed.
> **Historical boundary:** this prompt and its `PASS` apply only to the three-wave revision reviewed on 2026-10-29; they do not cover later owner decisions or docs reviews. This is not an active review or implementation prompt. Its 20-minute timer reference is superseded by the [2026-10-29 owner decision delta](../W0_OWNER_DECISION_DELTA_2026-10-29.md). The canonical chronology and latest supplied R6 report are in the [W0 review reconciliation](../W0_REVIEW_RECONCILIATION_2026-10-28.md); do not use this historical prompt to launch another review.

## Review context

The prior focused three-wave review returned `CHANGES REQUIRED`: Argon reported `1 BLOCKER / 3 MAJOR / 2 MINOR`; Opus 5.5 independently confirmed the core inconsistencies and identified further stale-prompt, lifecycle, traceability, and evidence-scope issues. This re-review should verify the documentation corrections—not repeat a code audit or treat documentation consistency as implementation approval.

The target delivery grouping is:

- Wave 1: `W0–W2` — Foundation & secure case operations.
- Wave 2: `W3–W4` — Business actions & shared AI.
- Wave 3: `W5–W6` — UI, verification & rollout.

The package notation is sequential, **not parallel**: `W0 → (W1, W2) → (W3, W4) → W5 → W6`. The owner has not specified the internal order of `W1` vs. `W2` or `W3` vs. `W4`; the documents must keep those orders explicitly open and must not imply simultaneous execution. While readiness is blocked, W0 means read-only reconciliation/documentation only—not application-test authoring/execution, code, migrations, build/CI, or runtime actions.

## Paste-ready trigger prompt

```text
You are Gemini 4 Argon performing one focused, READ-ONLY documentation-delta review for Phase R1 after the prior Argon and Claude Opus 5.5 reviews.

IMPORTANT SCOPE: Review only whether the documentation changes listed below correctly reconcile the previous three-wave review findings. This is not a fresh implementation-readiness review, not a source-code audit, and not permission to implement. The controlling implementation-readiness status remains BLOCKED (owner-provided: 9 BLOCKER / 6 MAJOR / 3 MINOR); only W0 read-only reconciliation is currently authorized.

Do not edit, stage, commit, rebase, merge, push, create/delete branches or worktrees, modify application code or database, run application tests/build/CI, run migrations, access AWS/SSM/EC2/Colab, call providers, or change runtime/deployment state. Preserve all existing working-tree changes. You may inspect Markdown and run read-only documentation checks if available. Do not make external network calls for this documentation-only review.

Review this documentation packet as one system:
- docs/phase_role_aware_ops/README.md (canonical design and W0–W6 acceptance/evidence traceability)
- docs/phase_role_aware_ops/R1_IMPLEMENTATION_HANDOFF_2026-10-26.md (reference-only handoff; old executable prompts should no longer be active)
- docs/phase_role_aware_ops/W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md
- docs/phase_role_aware_ops/OWNER_DECISIONS_2026-10-28.md
- docs/phase_role_aware_ops/IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md
- docs/phase_role_aware_ops/archive/ARGON_R1_IMPLEMENTATION_TRIGGER_2026-10-27.md
- README.md
- docs/CURRENT_PROJECT_STATUS.md
- docs/PLAN_ROADMAP_INDEX.md
- docs/03_EVALUATION/ACCEPTANCE_MATRIX.md
- docs/README.md
- this handoff file

Prior findings to verify as closed or explicitly preserved as open:
1. Remove contradictory parallel lanes and all stale read/write sub-agent prompts; make sequential/no-parallel policy prominent and consistent. No readiness prompt or implementation trigger may imply that owner approval of W0 alone authorizes W1–W6.
2. Make W0 strictly read-only while readiness is BLOCKED. Negative tests may be designed/documented only; do not authorize writing/running app tests, changing code, migration, build/CI or runtime work.
3. Gate W1–W6 on owner-approved applicable decisions/contracts, freshly verified GitHub main and exact clean candidate SHA, and a completed fresh implementation-readiness review that explicitly clears BLOCKED. A requested or pending review is not clearance. Do not claim the historical bbfd11d0 SHA is still today's latest main.
4. Map each W0–W6 package to acceptance and minimum evidence. Keep feedback responsibility explicitly provisional if split across W2 persistence, W5 UI, and W6 integrated acceptance.
5. Reconcile W2/OD-03: exactly waiting/in_progress/resolved; no case status cancelled; 20-minute inactivity direction; completion follow-up, feedback and approximately 5-minute resolution; completed handoff resolution; customer reply requeue; claim/release/transfer. Keep timer anchor/races, history, feedback schema/privacy, and case_id reuse/reopen mechanics open where not owner-decided.
6. Reconcile W3/OD-04: pending-order cancellation direction for Customer/Staff/Manager; Manager direct order-status path; Customer requests return; Staff or Manager approves/rejects; persist decision history, update DB, common JSONL format/schema family for integration input/output. Keep Staff acting-for-customer scope, exact return/refund vocabulary, transaction/audit/outbox/retry, JSONL envelope/consumer and evidence controls open. State that /api/cancellation-proposals* is an application API, not an LLM provider API; compatibility disposition remains open.
7. Do not encode an unapproved fixed principal/cache partition tuple. Preserve required tenant/case isolation and the still-open choice between per-principal and case-shared internal follow-up history, consistent with ExecutionContext.
8. Ensure the archived 2026-10-27 implementation trigger is prominently marked SUPERSEDED / DO NOT EXECUTE, and that a docs PASS is never presented as code, CI, runtime or readiness PASS.
9. Fix summaries/links/dates as applicable, including the direct canonical-design link in the Acceptance Matrix/Roadmap, heading hierarchy, and wording that W0 read-only is current while W1–W6 await gates.
10. Treat git diff --check as tracked-file-only evidence; verify untracked/new Markdown for whitespace separately or state NOT CHECKED.

Do not resolve unknown policy by inference. In particular, do not choose the order inside W1/W2 or W3/W4, decide case_id reuse, approve a feedback data-governance policy, convert an open OD into a decision, or set an exact AI history partition key. If any such item is still ambiguous, label it OPEN and say whether the documentation correctly preserves that status.

Return a concise report with:
1. Verdict for this docs delta only: PASS or CHANGES REQUIRED (do not say READY FOR IMPLEMENTATION).
2. A finding table with severity, exact file/heading/line, impact and minimal correction; if none, say 0 findings.
3. A checklist of the ten prior finding groups above: CLOSED / PARTIAL / OPEN, with precise references.
4. W0–W6 traceability check and link/heading/Markdown checks performed; identify untracked-file coverage and any NOT CHECKED items.
5. Explicit confirmation that implementation readiness remains BLOCKED and that this review does not authorize code, tests, CI, migration, merge, deploy or production/runtime changes.

Do not edit any files. Do not run application tests/build/CI or inspect application behavior. Do not claim the repository is clean; report the observed status without modifying it.
```

## Current records

- [Canonical R1 design](../README.md)
- [Historical owner decision snapshot](../OWNER_DECISIONS_2026-10-28.md)
- [Current owner decision delta](../W0_OWNER_DECISION_DELTA_2026-10-29.md)
- [Complete review chronology and R6 disposition](../W0_REVIEW_RECONCILIATION_2026-10-28.md)
- [Next docs re-review handoff](W0_ARGON_DOCS_REVIEW_HANDOFF_2026-10-30.md)
- [W0 baseline and decision register](../W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md)
- [Implementation readiness: BLOCKED](../IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md)
- [Three-wave implementation handoff (reference-only)](R1_IMPLEMENTATION_HANDOFF_2026-10-26.md)
- [Prior Argon/Opus review reconciliation](../W0_REVIEW_RECONCILIATION_2026-10-28.md)
- [Archive index](README.md)
