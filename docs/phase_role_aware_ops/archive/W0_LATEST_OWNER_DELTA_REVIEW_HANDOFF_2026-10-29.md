# Phase R1 — W0 Owner-Delta Docs Review Handoff (historical, 2026-10-29)

> **Historical status:** Argon reviewed this 2026-10-29 prompt and returned `CHANGES REQUIRED` (0 BLOCKER / 3 MAJOR / 3 MINOR). This handoff is historical/incomplete; the 2026-10-30 rounds R2–R4 are also historical, and the latest recorded fifth-round review returned `CHANGES REQUIRED` (0 BLOCKER / 0 MAJOR / 3 MINOR; `R5-01`–`R5-03`), recorded in [the R5 result](W0_ARGON_DOCS_REVIEW_ROUND5_2026-10-30.md). Use [the bounded re-review handoff](W0_ARGON_DOCS_REVIEW_HANDOFF_2026-10-30.md) after local synchronization. The current owner direction is [W0_OWNER_DECISION_DELTA_2026-10-29.md](../W0_OWNER_DECISION_DELTA_2026-10-29.md). This prompt does not authorize implementation or clear `BLOCKED`.
> **Review boundary:** the earlier focused Argon `PASS` covered the prior three-wave documentation revision only, not this owner delta.

## Local remediation checks after the reported review

- F-01–F-06 documentation corrections were applied in the uncommitted W0 docs tree, but this handoff is not the active review record; later synchronization findings were recorded in rounds R2–R5. See the [latest recorded R5 result](W0_ARGON_DOCS_REVIEW_ROUND5_2026-10-30.md) and the [bounded current review handoff](W0_ARGON_DOCS_REVIEW_HANDOFF_2026-10-30.md).
- `python -B -X utf8 scripts/check_docs_contract.py` — `PASS 4/4`.
- `git diff --check` — `PASS`.
- These checks did not substitute for the fresh independent Argon re-review requested by this handoff and do not change the separate implementation `BLOCKED` gate.

## Trigger prompt

```text
Perform a fresh, independent, READ-ONLY documentation and contract-consistency review for Phase R1 W0 in:

Repository path: `docs/phase_role_aware_ops/` in the reviewed checkout. Reviewed source/base SHA: `bbfd11d0ba4c13514a197a6b25802c4e217bedb3`; the documentation delta itself was uncommitted/untracked at review time.

Read the current working-tree contents of these documents, including any uncommitted changes:

- docs/phase_role_aware_ops/README.md (canonical product/architecture plan)
- docs/phase_role_aware_ops/W0_OWNER_DECISION_DELTA_2026-10-29.md (latest owner decisions/proposals)
- docs/phase_role_aware_ops/W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md
- docs/phase_role_aware_ops/W0_CONTRACT_FREEZE_AND_GAP_REGISTER_2026-10-29.md
- docs/phase_role_aware_ops/W0_REVIEW_RECONCILIATION_2026-10-28.md
- docs/phase_role_aware_ops/IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md
- docs/phase_role_aware_ops/W0_ROLE_INVENTORY_2026-10-29.md
- docs/phase_role_aware_ops/R1_IMPLEMENTATION_HANDOFF_2026-10-26.md (reference-only; not an active implementation prompt)
- docs/phase_role_aware_ops/W0_THREE_WAVE_DOCS_REVIEW_HANDOFF_2026-10-29.md (historical review prompt/result scope; do not treat it as reviewing this delta)
- docs/CURRENT_PROJECT_STATUS.md
- docs/PLAN_ROADMAP_INDEX.md
- docs/03_EVALUATION/ACCEPTANCE_MATRIX.md
- README.md and docs/README.md where they link to the current R1 packet

Owner directions to verify are recorded consistently and not overstated:
1. Business roles are customer/staff/manager; opsadmin stays on a separate Ops Console. Retire platform_admin gradually and do not transfer its cross-tenant privileges to Manager. The exact same-tenant Manager /api/admin/* boundary remains open.
2. Viewer app access is to be disabled; remove membership only when safe, otherwise freeze/lock and phase out. Do not auto-promote Viewer.
3. Three case states remain waiting/in_progress/resolved. After 3 minutes without customer reply, mark the interaction inactive; each customer reply resets the timer. The 1.5-minute flag is only for non-production evaluation or specialized test states and is prohibited in production. Never auto-close staff-owned work because of system overload. Exact timer start/eligible state and inactive-marker-to-case transition remain open; inactivity must not silently be equated with resolved.
4. OD-08 includes image/file handling across W0-W6. Owner wants a production-capable Colab inference path that can process real customer data when enabled, using compact, server-authorized, case-bound context rather than a full conversation dump by default. Current serving limit is 8,192 tokens; 16,384 is only an evaluation candidate if measured L4 memory/latency/quality permit it. Exact context fields and permitted media projections remain open.
5. The supplied Colab/ngrok launch has no configured vLLM API-key protection and its privacy/request controls are unverified. Documentation must NOT imply it is currently safe or approved for real customer data. Do not send data, run Colab, test a live endpoint, inspect secrets, or make a production change. Any eventual real-data use requires an authenticated/protected endpoint, case/tenant authorization, data minimization, privacy/logging/retention/deletion controls, bounded file handling, and separate release/readiness approval.
6. Current application source suppresses image pixels for the named Gemma model ID; the supplied notebook did not test an image request; PDF/OCR extraction is absent. Distinguish model-level capability from app/endpoint capability. Keep raw attachments out of model payloads by default until an explicitly approved safe projection exists.
7. W0 remains documentation/read-only only. Implementation readiness stays BLOCKED (owner-provided Argon review: 9 BLOCKER / 6 MAJOR / 3 MINOR). A docs PASS cannot authorize W1-W6, code/tests, migration, CI, merge, deploy, DB, EC2, or Colab runtime.

Review for contradictions, stale status/date/review-scope claims, broken relative links, unclear owner-approved versus proposed items, and whether the image/file plan is traceable across W0-W6 with safe boundaries. Do not resolve open policy by inference.

Do not edit files. Do not run application tests/build/CI. Do not use EC2/SSM, database, Colab, browser or live endpoints. Do not expose personal data, credentials, or secrets. If a claim cannot be verified from this docs-only scope, label it NOT VERIFIED.

Return:
- Verdict for this docs delta only: PASS or CHANGES REQUIRED (never READY FOR IMPLEMENTATION).
- Findings with severity, exact file/heading/line, impact, and minimal correction.
- Consistency check for all seven owner directions above, identifying CLOSED / PARTIAL / OPEN.
- Link/heading/status/review-scope checks performed and files not reviewed.
- Explicit confirmation that implementation readiness remains BLOCKED and this review does not authorize code, tests, CI, migration, merge, deployment, or runtime.
```

## Review packet links

- [Canonical R1 design and W0–W6 map](../README.md)
- [Latest owner delta/proposals](../W0_OWNER_DECISION_DELTA_2026-10-29.md)
- [W0 baseline/decision register](../W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md)
- [Contract freeze/gap register](../W0_CONTRACT_FREEZE_AND_GAP_REGISTER_2026-10-29.md)
- [Implementation readiness — BLOCKED](../IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md)
- [Current project status](../../CURRENT_PROJECT_STATUS.md)
- [Acceptance Matrix](../../03_EVALUATION/ACCEPTANCE_MATRIX.md)
- [Roadmap index](../../PLAN_ROADMAP_INDEX.md)
- [Argon result and F-01–F-06](W0_ARGON_LATEST_OWNER_DELTA_REVIEW_2026-10-29.md)
- [Historical second-round Argon docs review (`R2-01`–`R2-04`)](W0_ARGON_DOCS_REVIEW_FOLLOWUP_2026-10-30.md)
- [Latest recorded Argon docs review result (fifth round, `R5-01`–`R5-03`)](W0_ARGON_DOCS_REVIEW_ROUND5_2026-10-30.md)
- [Historical third-round result (`R3-01`–`R3-05`)](W0_ARGON_DOCS_REVIEW_ROUND3_2026-10-30.md)
- [Next docs-only re-review handoff](W0_ARGON_DOCS_REVIEW_HANDOFF_2026-10-30.md)

## Boundary

The owner’s real-customer-data-on-Colab request is recorded as an eventual production target with compact, case-bound context. The current public ngrok/vLLM endpoint is not approved for live data and no data was transferred. The later implementation path must separately complete security/privacy design, provider-payload and isolation tests, runtime validation, and owner-approved readiness/release gates.
