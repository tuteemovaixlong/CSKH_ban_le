# Phase R1 W0 — Argon docs-only re-review handoff (2026-10-30)

> **Purpose:** request one bounded, independent, read-only re-review after the local corrections for rounds 1–5. Focus on material contradictions in active navigation/status, preservation of historical review boundaries, and the exact R5 corrections; do not create stylistic-only findings or reopen already historical verdicts.
> **Review history:** round 1 `RF-01`–`RF-08` (0/4/4), round 2 `R2-01`–`R2-04` (0/0/4), round 3 `R3-01`–`R3-05` (0/0/5), and round 4 `R4-01`–`R4-03` (0/0/3) are historical. The latest recorded [round 5 result](W0_ARGON_DOCS_REVIEW_ROUND5_2026-10-30.md) is `CHANGES REQUIRED` (0 BLOCKER / 0 MAJOR / 3 MINOR; `R5-01`–`R5-03`). Local R5 synchronization is applied and awaits this bounded re-review.
> **Hard gate:** implementation readiness remains `BLOCKED` (separate owner-provided 9 BLOCKER / 6 MAJOR / 3 MINOR). This docs review cannot authorize W1–W6.

## Trigger prompt

```text
Perform a fresh, independent, READ-ONLY documentation and contract-consistency re-review of Phase R1 W0 in the current working tree.

Use the Phase R1 W0 documentation checkout supplied with this task; identify it by branch `docs/phase-r1-w0-owner-decisions` and committed HEAD below. Do not add a machine-specific path to project documentation.
Committed HEAD at the previous review: bbfd11d0ba4c13514a197a6b25802c4e217bedb3. Documentation changes are uncommitted/untracked; read the working-tree files exactly as they are. Do not assume the remote main ref is current: the last reported `git ls-remote` was at 2026-10-29T23:11:17+07:00 and is timestamp-bounded.

Read the five review records (`W0_ARGON_DOCS_REVIEW_2026-10-30.md`, `W0_ARGON_DOCS_REVIEW_FOLLOWUP_2026-10-30.md`, `W0_ARGON_DOCS_REVIEW_ROUND3_2026-10-30.md`, `W0_ARGON_DOCS_REVIEW_ROUND4_2026-10-30.md`, and `W0_ARGON_DOCS_REVIEW_ROUND5_2026-10-30.md`), then the current W0 owner delta, canonical Phase R1 design, W0 baseline/decision register, contract freeze/gap register, role inventory, readiness block, project status, roadmap, Acceptance Matrix, root/docs indexes, archive index, reference-only implementation handoff, identity/RBAC planning docs, multimodal attachment plan and Phase 5 / Fix A / Fix B status records. Follow relevant links and inspect the current working-tree diff for these docs.

Verify the historical RF-01 through RF-08, R2-01 through R2-04, R3-01 through R3-05 and R4-01 through R4-03 dispositions, plus the local R5-01 through R5-03 corrections:
1. Historical Argon→Opus and three-wave handoffs no longer route readers to superseded prompts; current result and next-handoff links are clear.
2. The archive index distinguishes current source of truth from revision-bounded historical PASS records.
3. Viewer app access is disabled first; remove memberships only after aggregate integrity proof, otherwise freeze/lock and retire gradually. No auto-promotion. The Manager same-tenant `/api/admin/*` scope is tracked centrally under OD-01. Current owner-delta links appear in the five RBAC/identity/copilot docs.
4. Active/non-archive Markdown has no personal Windows checkout paths; scan both slash styles case-insensitively. Historical/archive provenance may remain if labeled historical.
5. The AI index and decision/review records link the latest review and handoff; 2026-10-26 PASS records and the 2026-10-29 three-wave prompt are explicitly historical/revision-bounded.
6. OD-08 image/file handling is traceable in W0/W1/W2/W5 of the reference handoff and in the legacy multimodal plan's R1 boundary. Model capability must not be presented as proof of app or endpoint capability. The supplied public ngrok/vLLM endpoint remains unapproved for real customer data.
7. The 2026-10-28 owner snapshot and Argon→Opus handoff mark OD-02/03/08 and GGUF/`mmproj` material as superseded/historical where applicable.
8. `docs/README.md`, `docs/03_EVALUATION/ACCEPTANCE_MATRIX.md`, and `docs/phase5/README.md` reflect the dated PR #45 merge, targeted cleanup record, PR #46 merge/deploy record and current Phase R1 W0 status without claiming a new runtime check.
9. Historical 2026-10-26 reviews link current owner delta/result/handoff; the 2026-10-29 handoff is historical/incomplete; latest remote provenance uses `2026-10-29T23:11:17+07:00` only as timestamp-bounded evidence.
10. The current roadmap and Fix B index no longer present the pre-merge state as current; the canonical Viewer acceptance is disable-first; repeated footer links are removed and the 2026-10-28 decision snapshot is labeled historical.
11. R3-01: verify the 2026-10-28 review reconciliation and first-round 2026-10-30 review record link the owner delta, the review result current at that time, and the next handoff; no historical record should route readers only to superseded prompts.
12. R3-02: Fix B acceptance criteria, evidence ledger, execution handoff and R6 review carry a historical pre-merge boundary; Fix A `README.md`, acceptance criteria, evidence ledger, and consumed execution handoff label the old Fix B routing as historical, keep retired commands `DO NOT RUN`, and cite the dated PR #45 merge, targeted cleanup record and PR #46 merge/deploy run `40089312937` without claiming a new runtime check or authorizing repeat operations. Also check the Acceptance Matrix, roadmap, and Phase 5 index for present-tense Fix A/Fix B cleanup claims.
13. R3-03: no link target repeats within the same section/paragraph in the W0 register, R1 design index, root README, Acceptance Matrix or roadmap; every related-records entry for `OWNER_DECISIONS_2026-10-28.md` reads "Historical owner decision snapshot".
14. R3-04: active files distinguish `RF-01`–`RF-08` (first round), `R2-01`–`R2-04` (second round) and `R3-01`–`R3-05` (third round), and do not present their historical verdicts as the latest docs result.
15. R3-05: the readiness record says the local remote query failed earlier on 2026-10-28, before Argon's `2026-10-29T23:11:17+07:00` check; no claim is made about GitHub `main` after that timestamp or about deployment/runtime.

16. R4-01: the Fix A Acceptance Matrix override and 2026-10-20 Fix A review mark `FIXA-DEPLOY2 PENDING` as historical pre-merge and cite the dated cleanup/PR #46 deploy records without a new runtime claim.
17. R4-02: normalized duplicate targets are removed in the Roadmap, Fix A README/handoff and RBAC plan; G6/G7 reference the protocol linked in G3.
18. R4-03: the reference R1 handoff checklist and next action refer to the fourth-round result/current docs-only handoff, not the historical owner-delta handoff.
19. R5-01: active docs indexes point to the fifth-round result, while historical synthesis accurately marks R3/R4 as superseded and does not misstate a prior round as current.
20. R5-02: the R3 record preserves its original verdict and clearly distinguishes what was true when it was written from the later R4 review.
21. R5-03: active chronology names all five rounds in order, links each result, and places RF/R2/R3/R4 in historical records while R5 is the latest recorded result.

Also check links/anchors, status/date/review-scope consistency, owner-approved versus proposed language, Git provenance timestamps, and stale verdicts presented as current. Do not resolve open policy by inference.

Scope is documentation-only and read-only. Do not edit files. Do not run application tests/build/CI, inspect live DB or GitHub Actions, access AWS/SSM/EC2, run Colab/ngrok, call model/provider endpoints, inspect secrets, or send customer data. Do not claim remote/runtime state beyond evidence in the reviewed docs. If an item is outside scope, label it NOT VERIFIED.

Return:
- Docs-only verdict: PASS or CHANGES REQUIRED (never READY FOR IMPLEMENTATION).
- Findings with severity, exact file/heading/line, impact, and minimal correction.
- CLOSED/PARTIAL/OPEN tables for RF-01–RF-08, R2-01–R2-04, R3-01–R3-05, R4-01–R4-03 and R5-01–R5-03, preserving original verdicts for historical rounds.
- Checks performed, files read, files only scanned, and material limits.
- Explicit confirmation that implementation readiness remains BLOCKED and this review authorizes no code, tests, CI, migration, merge, deployment or runtime work.
```

## Boundary

This handoff is only for a docs-only re-review. Do not start W1–W6 from a documentation PASS; a separate owner-approved implementation-readiness review must explicitly clear `BLOCKED` first.
