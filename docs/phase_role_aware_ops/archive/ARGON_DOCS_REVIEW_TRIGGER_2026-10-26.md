# Gemini 4 Argon — R1 documentation reconciliation review trigger

> **Execution status:** COMPLETED on 2026-10-26. Argon's `PASS WITH REQUIRED CHANGES` report is summarized in [ARGON_DOCS_REVIEW_2026-10-26.md](ARGON_DOCS_REVIEW_2026-10-26.md); this file is retained as the exact reusable prompt/basis, not as a pending review request.

## Goal

Run an independent, documentation-focused review of the revised Phase R1 packet after the Claude Opus report and four focused Codex sub-agent audits. Check whether the documents truthfully distinguish code behavior, design proposals, owner policy and unverified runtime. This is a review request—not approval to implement.

## Prompt to paste into Gemini 4 Argon in Antigravity

```text
You are Gemini 4 Argon acting as an independent senior reviewer. Review the Phase R1 documentation packet in the current repository after its 2026-10-26 revision. This is a documentation reconciliation review; do not implement or edit code.

OWNER ARCHITECTURE (fixed constraint): Customer, Staff and Manager use ONE shared workflow/LangGraph orchestration core. Role/task-specific request profiles may vary immutable context, instructions, tool capabilities, projections and output/persistence adapters. Do not recommend three separate workflows/graphs.

Read these documents:
- docs/phase_role_aware_ops/README.md
- docs/phase_role_aware_ops/INDEPENDENT_AUDIT_SYNTHESIS_2026-10-26.md
- docs/phase_role_aware_ops/REVIEW_FINDINGS_2026-10-25.md
- docs/phase_role_aware_ops/ARGON_FOLLOWUP_REVIEW_2026-10-25.md
- docs/phase_role_aware_ops/ARGON_REVIEW_TRIGGER.md
- docs/phase_role_aware_ops/CLAUDE_OPUS_REVIEW_TRIGGER.md
- README.md, docs/README.md, docs/CURRENT_PROJECT_STATUS.md,
  docs/PLAN_ROADMAP_INDEX.md, docs/03_EVALUATION/ACCEPTANCE_MATRIX.md,
  docs/01_AI_SYSTEM/README.md and other directly linked docs as needed.

Review independently. Do not treat the Claude report, Codex synthesis, or prior Argon conclusions as automatically correct. Where feasible, verify source citations against the explicitly named local refs `HEAD dd544800` and local `origin/main bbfd11d0`; do not assume origin/main is freshly fetched or equivalent to GitHub latest. If you cannot inspect a source ref, mark the claim unverified rather than guessing. Do not infer EC2, production, CI, or live behavior from source/docs.

Check specifically:
1. Is the classification clear between confirmed current source behavior, conditional risk/blocker for R1 implementation, documentation drift, owner-policy choice, and unverified runtime?
2. Are Claude's P0-1/P0-2/P0-3 findings reconciled fairly—especially that handoff issue is same-tenant wrong-object scope absent cross-tenant proof; internal profiles are not implemented; and current run/checkpoint already has customer/request/purpose/lease scoping while R1 still needs actor/profile/case/projection identity?
3. Are Staff/Manager handoff, reply, resolve, customer return-to-bot, polling, TTL/retention, queue/count, audit actor, attachment and Manager UI/order-detail statements accurate and correctly qualified?
4. Are role provisioning, `DEFAULT_ROLE`, Viewer writes, `platform_admin` differences between the two refs, `/api/admin/*`, and Manager shop-wide order/admin behavior represented without implying a single baseline?
5. Are provider prompt handling, Dispute and `/api/tools/execute` executor allowlists, fail-closed escalation, RAG tenant/case scope, SemanticCache/ToolCache and the unverified product-cache invalidation allegation described precisely?
6. Do both Mermaid diagrams show one shared graph and correctly model profile-aware gateway instructions, server output validation, checkpoint identity, scoped/bypassed caches, generated handoff ID ordering, persistence-before-ack and episode-specific polling?
7. Are acceptance tests objective and sufficient for serialized payload allowlists, tool-level denial, cache isolation, concurrency/races, TTL, role provisioning, event allowlists and fail-closed escalation?
8. Are all relative links valid and all project indexes/status/acceptance rows consistent that R1 is not implementation-ready and not a G4-G7 gate?

Read-only rules:
- Do not edit, stage, commit, stash, reset, or clean any file.
- Do not run tests, migrations, DB writes, live services or deployment commands.
- Treat dirty/untracked files as owner-owned; do not overwrite them.
- Do not claim a finding is fixed merely because a document says so.
- Do not present your review as a code patch or as runtime verification.

Return a concise report in Vietnamese with these sections:
(a) Review basis: refs and documents inspected; any limitation.
(b) Confirmed documentation defects: ranked P0-P3, with exact file/heading/line and replacement recommendation.
(c) Source-claim accuracy: separate confirmed source behavior from conditional R1 risks and unverified claims; highlight disagreements with Claude/Codex/previous Argon.
(d) Shared-workflow, Mermaid and acceptance review.
(e) Owner decisions still open.
(f) Final verdict: exactly one of PASS, PASS WITH REQUIRED CHANGES, or BLOCKED—for documentation packet readiness only, not implementation or runtime.

Do not produce a code patch. End with the minimum document corrections, if any, needed before R1 design sign-off.
```

## Handoff back to Codex

Paste Argon's full report into the project chat. Reconcile any new finding against the cited source ref and the 2026-10-26 synthesis before editing. An Argon docs-review verdict does not by itself approve implementation, production deployment, or owner policy.
