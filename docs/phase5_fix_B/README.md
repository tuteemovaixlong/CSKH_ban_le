# Phase 5 Fix B — Safe one-time demo-order cleanup

**Status (2026-10-24): R5 INDEPENDENT STATIC REVIEW PASS — READY FOR PR/CI / POSTGRESQL CI PENDING / LIVE CLEANUP BLOCKED.** [independent review R5](PHASE_5_FIX_B_REVIEW_R5_2026-10-24.md) found no remaining blocker to PR/CI in Fix B scope. R4 guards all specified PostgreSQL test/preparation callers and scopes CI opt-in; R5 requires explicit operator attribution for execute and rejects whitespace-only backend configuration. Local Fix A/B `8/8`, guard `5/5`, targeted regression `102/102`; Ops Console `19 tests / 3 skipped`. Candidate remains uncommitted. No PR/CI, merge, deployment or live database operation has run.

Fix A remains the implementation/CI source of truth. Fix B owns the one-time operational gates: verify source/image and tenant mapping, validate backup/restore, rehearse, inspect a genuinely read-only dry-run, obtain final approval, then execute and post-check. Do **not** treat this uncommitted candidate as accepted or production-ready until exact-candidate GitHub Actions PostgreSQL/pgvector CI (`0 skipped`) and the remaining acceptance gates pass; R5 static review is complete.

## Read and navigation order

1. [independent review R5](PHASE_5_FIX_B_REVIEW_R5_2026-10-24.md) — current static verdict, READY FOR PR/CI; [R3](PHASE_5_FIX_B_REVIEW_R3_2026-10-23.md), [R2](PHASE_5_FIX_B_REVIEW_R2_2026-10-23.md) and [R1](PHASE_5_FIX_B_REVIEW_2026-10-23.md) remain historical.
2. [Acceptance criteria](PHASE_5_FIX_B_ACCEPTANCE_CRITERIA.md) — mandatory code and operational gates.
3. [Evidence ledger](PHASE_5_FIX_B_EVIDENCE.md) — verified local evidence, PostgreSQL CI pending status, and pending live evidence.
4. [Execution handoff](PHASE_5_FIX_B_EXECUTION_HANDOFF.md) — current PR/CI prompt, compact remediation/review history, and pending live gates.

## Related source-of-truth documents

- [Fix A packet](../phase5_fix_A/README.md) · [Fix A review](../phase5_fix_A/PHASE_5_FIX_A_REVIEW_2026-10-20.md) · [Fix A criteria](../phase5_fix_A/PHASE_5_FIX_A_ACCEPTANCE_CRITERIA.md) · [Fix A evidence](../phase5_fix_A/PHASE_5_FIX_A_EVIDENCE.md) · [Fix A handoff](../phase5_fix_A/PHASE_5_FIX_A_EXECUTION_HANDOFF.md).
- [Acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md) · [current status](../CURRENT_PROJECT_STATUS.md) · [roadmap](../PLAN_ROADMAP_INDEX.md) · [Phase 5 index](../phase5/README.md) · [docs index](../README.md).

Fix B does not close P5-E, P5-DM, G4/G5, or performance readiness. Local SQLite/unit verification (`8/8` in `tests.test_phase5_fix_a`, `102/102` across targeted suites) is not evidence of real PostgreSQL execution or production readiness: obtain exact-candidate PostgreSQL/pgvector CI (`0 skipped`) and the remaining operational gates before considering any live operation. R5 static review is complete.
