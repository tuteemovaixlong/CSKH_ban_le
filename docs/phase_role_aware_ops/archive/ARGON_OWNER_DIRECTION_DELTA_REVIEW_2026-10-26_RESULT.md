# Gemini 4 Argon — Owner-direction Delta Review Result (2026-10-26)

> **Verdict:** `PASS WITH REQUIRED CHANGES` — documentation/design readiness only.
> **Scope:** read-only review of the patched owner-directed R1 packet after the initial required-change review. Argon reported zero blockers, two major findings and three minor findings. The corrections for this report have now been applied in the working tree; a fresh read-only delta review is required before calling the packet docs-ready.

## Review basis and limits

- Reviewer: Gemini 4 Argon through Antigravity.
- No files were edited; no tests, migrations, database writes, deploys, live-service or EC2 checks were performed.
- Ref comparison used committed `HEAD dd544800` and local `origin/main bbfd11d0`; neither was treated as current GitHub HEAD or deployed runtime.
- The review inspected the handoff packet, canonical R1 README, status/roadmap/acceptance/index docs, AI-system index, RBAC/OAuth/identity/Admin Console/Ecommerce docs, relative links and Mermaid blocks.

## Findings

### Major

1. **Endpoint matrix and order derivation still used `handoff_id` as the selected-case identity.** The prior patch had correctly introduced `case_id`, but the matrix glossary, active-case row and transcript-derived order rule still referred to `case handoff_id`, `handoff.order_id` and `handoff.customer_id`. The docs also mixed “each handoff episode is a case” with “a case may link one or more handoff episodes.”
   - Required correction: bind `Selected case` to opaque `case_id`, with optional verified `handoff_id`/`order_action_request_id`; use `case.customer_id`; define a case as linking zero or one handoff episode, with a new case/handoff after the prior case closes.
2. **`PLAN_GOOGLE_ACCOUNT_RBAC_PRODUCTION.md` still presented older role/approval/Admin Console content as active.** Sections 2.1 and 3 needed explicit historical/superseded banners, including the old `admin-retailops` OAuth-origin example, hard-coded Manager approval/audit claims and provisioning defaults.
   - Required correction: mark the document and those sections as historical roadmap material superseded in part by R1; state that `opsadmin` is a separate Admin Console path and that current role/approval/provisioning policy comes from R1.

### Minor

1. Correct the source claim to say Customer and Staff have `orders:cancel` in both audited refs (`dd544800`, `bbfd11d0`), while Customer self-confirm behavior remains current-source behavior rather than R1 target policy.
2. Update root `README.md` to label self-cancel as v0.7/P5-C baseline and add the trusted `display_name`/`null`, no-demo-name rule to the R1 summary.
3. Add `docs/01_AI_SYSTEM/README.md` to handoff scope, link the review result from R1’s related-doc list, and separate browser evidence serving controls from the Viewer migration paragraph for implementation discoverability.

## Checklist result in the reviewed revision

- Owner directions 1, 3, 4 and 5: PASS.
- Owner directions 2, 7 and 8: marked FAIL only because the historical production-plan text and the remaining `handoff_id` terminology could still mislead implementation.
- Owner direction 6: marked FAIL because the matrix/order derivation/cardinality terminology was not yet fully aligned.
- Delta items 1, 3, 4, 5, 6, 8 and 9: PASS.
- Delta items 2 and 10: FAIL through the selected-case/handoff terminology and historical production-plan labeling.
- Delta items 7 and 11: PASS with editorial follow-up.

## Verification reported by Argon

- Relative links, anchors, stale-head check and whitespace: PASS.
- Mermaid blocks: PASS by read-only inspection.
- `check_docs_contract.py` and `git diff --check`: PASS in the reviewed state.
- GitHub latest state, EC2, containers, database, Google OAuth live state, CI and deployment: NOT VERIFIED.

## Disposition

The above corrections are applied in the current working tree. The local validation gates pass again. This record must remain immutable as the historical result for this review; the next step is a focused Argon delta review of only these corrections.

> **Explicit scope statement:** This review is documentation/design-only; it does not approve implementation, tests, CI, deployment, or production runtime.
