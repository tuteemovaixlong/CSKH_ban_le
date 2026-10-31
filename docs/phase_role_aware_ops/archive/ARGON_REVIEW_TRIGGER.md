# Gemini 4 Argon — Phase R1 revision-review trigger

Use this prompt in the Antigravity local session running **Gemini 4 Argon** after the owner has reviewed the open policy choices (or has explicitly instructed the team to retain the documented conservative defaults), and after the revised documentation receives the focused [2026-10-26 Argon docs review](ARGON_DOCS_REVIEW_TRIGGER_2026-10-26.md). The expected work is a read-only design/source review, not implementation. The reconciled Claude/Codex assessment is [here](INDEPENDENT_AUDIT_SYNTHESIS_2026-10-26.md).

```text
You are Gemini 4 Argon acting as an independent reviewer. Perform a READ-ONLY revision review of Phase R1 in the current repository.

Read:
- docs/phase_role_aware_ops/README.md
- docs/phase_role_aware_ops/REVIEW_FINDINGS_2026-10-25.md
- docs/phase_role_aware_ops/ARGON_FOLLOWUP_REVIEW_2026-10-25.md
- docs/phase_role_aware_ops/INDEPENDENT_AUDIT_SYNTHESIS_2026-10-26.md
- docs/phase_role_aware_ops/ARGON_REVIEW_TRIGGER.md
- the linked runtime sources and related project docs named by the design.

Architecture constraint from the owner (not an open question): Customer, Staff and Manager must use ONE shared workflow/LangGraph core. Per-request profiles may change task instructions, context projection, tool capabilities and output/persistence adapter. Separate ingress APIs or stores are allowed for security; do not propose three role-specific graphs/workflows.

Review the revised design against code, with source as truth. Independently verify the prior Argon follow-up claims and the design's proposed responses, especially:
1. pending-handoff object binding for staff transcript/reply/resolve/assist; atomic stale/resolved/wrong-tenant checks; `handoff.order_id IS NULL` and server-derived, ownership-verified `allowed_order_ids`;
2. PostgreSQL `graph_runs.customer_id` FK, actor-vs-subject identity, profile/case/projection-scoped `purpose`, fingerprint and thread key; ensure all profiles use the same graph and internal profiles fail closed rather than reaching customer `single_agent` prompt/tools;
3. Dispute worker tool schemas vs executor, fail-closed tool handling, transcript/attachment evidence, profile-specific task semantics, and Supervisor/cancellation/handoff behavior for Staff text quoting a customer;
4. session-derived actor audit, separation of internal drafts/audit from customer `business_events` and `GET /api/events`, ToolCache scope, membership quota and error telemetry;
5. full endpoint matrix for `customer`, `viewer`, `staff`, `manager`, `platform_admin`, including `/api/admin/*`, `/api/account/usage`, events, cancellation, Manager endpoints and proposed R1 endpoints;
6. complete tool matrix for `customer_chat`, `staff_case_assist`, `manager_ops_assist`, exact model field projections/caps, and no pseudo-tool exposure;
7. handoff lifecycle, re-handoff/poll, persistence-before-UI acknowledgement, attachment behavior, Manager Desk/order-detail UI, and truthful labels for exchange actions;
8. Mermaid accuracy and consistency among design, review record, status, roadmap, and links.

Treat all items in the design's owner-decision table as UNAPPROVED unless the owner has explicitly answered them in the current conversation or an authoritative project record. Review the documented deny-by-default proposals as proposals; do not silently convert them into owner policy. Call out any field/limit/permission that remains ambiguous or not objectively testable.

Review basis:
- Record exact committed HEAD and local `origin/main` ref. The prior report used `dd544800bb087d54a7faf564e723736905620045` and `bbfd11d0ba4c13514a197a6b25802c4e217bedb3`; verify whether those refs remain available. Do not assume local `origin/main` was freshly fetched.
- Separate committed source behavior from uncommitted working-tree changes. Do not treat docs, tests not run, or source review as deployment/runtime evidence.
- If a prior finding cannot be reproduced, state that and cite the code path/ref checked.

Rules:
- Read-only: do not edit/create/delete/stage/commit/reset files; do not run migrations, call live services, deploy, or alter the working tree.
- Independently inspect source; do not merely endorse prior reports.
- Separate confirmed code behavior, doc drift, conditional future risks, and design proposals. Do not call a future risk a live breach.
- Rank findings P0–P3 with evidence (exact file + line ranges), impact, remediation and objective tests.
- Do not implement fixes and do not propose three workflows.
- End with one verdict: PASS, PASS WITH REQUIRED CHANGES, or BLOCKED.

Write a concise report in Vietnamese with: (a) review basis/refs, (b) findings with evidence, (c) Mermaid/doc accuracy, (d) authorization and acceptance gaps, (e) owner decisions still open, (f) verdict and required next changes.
```

Expected result: an independent evidence-backed review report. Bring it back to Codex before any R1 implementation. Current review history and status are linked from [the design](../README.md) and [the Argon follow-up record](ARGON_FOLLOWUP_REVIEW_2026-10-25.md).
