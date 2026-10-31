# Phase R1 — Review Findings (2026-10-25)

> **Status:** review synthesis; documentation/design work remains open; no implementation approval. This file records code-review evidence and design blockers, not a claim about the currently deployed EC2 runtime.

> **Scope note:** this is the initial Codex review synthesis. A later owner-pasted Argon follow-up reported additional P0/P1 findings and doc corrections; those are recorded in [ARGON_FOLLOWUP_REVIEW_2026-10-25.md](ARGON_FOLLOWUP_REVIEW_2026-10-25.md) and integrated as proposals in the current [R1 design](../README.md). Where the initial synthesis said the role/API matrix was still incomplete, that describes the pre-revision packet; the current target matrix is expanded but remains subject to owner decisions and review.

> **Later reconciliation:** the 2026-10-26 independent source/docs audit and the subsequent Argon documentation-only review are recorded in [independent audit synthesis](INDEPENDENT_AUDIT_SYNTHESIS_2026-10-26.md) and [Argon docs review](ARGON_DOCS_REVIEW_2026-10-26.md). This 2026-10-25 document remains the initial findings snapshot; read those later records for corrected source claims and current disposition.

## Review basis and verdict

- Argon review: `PASS WITH REQUIRED CHANGES`.
- Follow-up Codex sub-agent audits: security/authorization; handoff/UI lifecycle; R1 docs and LLM case-assist architecture.
- Compared committed `HEAD dd544800` with the workspace's local tracking ref `origin/main bbfd11d0`. The latter was not freshly fetched during these reviews.
- Reviews were read-only. No tests, live services, deployments or migrations were run.

**Overall verdict:** the direction—one shared workflow with role/task-aware context and server-side authorization—is sound. The R1 packet is **not implementation-ready** until the baseline/role matrix, handoff lifecycle, API and persistence boundaries, and owner decisions below are closed.

## Architecture decision recorded from the owner

Use **one shared LangGraph/workflow core**, not three independent Customer, Staff and Manager workflows. Select a per-request execution profile to adjust task instructions, context projection, tool capabilities and output adapter. Different API ingress routes and persistence targets are compatible with one workflow and may be required for security; they do not imply duplicated graphs.

The existing Customer chat workflow is implemented. Staff/Manager case-assist profiles and their selected-case binding are proposals only.

## Findings

### A. Implementation blockers for future Staff/Manager AI assistance

1. **Do not reuse `/api/chat` unchanged for internal case assistance.** Current chat binds a customer conversation and customer-bound tools, then saves the answer into that customer's conversation history (`retailops/business/application.py:118–137, 269–270, 394`). This is not a confirmed current leak; it means a future Staff draft must use a request/API and persistence boundary that keeps internal assistance out of the customer transcript. The underlying shared workflow may still be reused with a Staff profile.
2. **Bind the selected case on the server per request.** Resolve `handoff_id` to its tenant, conversation, customer and permitted order/product objects. Do not let model arguments select the customer/case, and do not store mutable selected-case context on a shared `Application` object. `current_binding` is mutable and has a fallback reader, but these audits did not establish a current cross-user actor-confusion exploit; treat it as a design hazard and pass actor/context explicitly.
3. **Separate Customer and Staff task semantics inside the same graph.** Customer rage/escalation heuristics and customer cancellation behavior must not run as if a Staff request quoting customer text were itself a customer request. Preserve one workflow, but make routing/profile rules explicit and test them.
4. **Enforce tool scope at the server boundary.** Worker names and tools are different: workers may have several tools. Order has six allowlisted tools; Policy uses `search_knowledge`; Witty has none. Dispute currently enables model tool calling without passing a worker-specific schema allowlist, while its handler accepts a narrower set (`retailops/workflow/subagents/dispute_agent.py:228–244`). Fix/test this before reusing that path for case assistance. RAG uses tenant-bound PostgreSQL/pgvector plus lexical search; it does not bind the selected support case by itself.
5. **Partition or disable caches for internal assistance.** Current review did not confirm cross-role/customer leakage in the existing cache path: `SemanticCache` is per cached `Application`, and `ToolCache` keys include tenant, customer, tool and arguments. However, the tool cache is tenant-shared and has no projection/case dimension; a future profile with different field projections must add the relevant scope to the key or bypass cache.

### B. Current handoff and Staff Desk behavior to fix or explicitly accept

The handoff is currently represented mainly by rows in `conversation_feedback`, not a first-class case episode. The same findings were observed at both reviewed refs:

- Multiple pending handoff rows can be created for one conversation; the displayed feedback-row ID is not used as the ID for reply/resolve. UI/API operations address the conversation instead.
- `reason_code` and `comment` are reused as mutable status/current-note fields. Resolve can affect all handoffs for a conversation; original reason/comment are not an immutable episode record.
- Customer “return to bot” changes browser state without closing the server-side handoff. Reload/polling can disagree about which old/new episode is active.
- Staff transcript/reply/resolve are tenant-scoped but not tied to a specific pending handoff episode. If policy is pending-case-only, this is an object-scope gap, not merely a UI issue.
- Queue can include resolved rows, has a fixed 20-row limit, and does not present a reliable total pending count.
- Human Mode UI sends attachments, but the endpoint currently rejects fields beyond `conversation_id` and `message`.
- Manager can open the Staff Desk dialog, but the Manager path does not call the queue-loading function or start polling; the dialog opening alone is not a working queue.
- Staff “approve exchange” quick actions currently send replies; they do not perform or persist an exchange transaction. Label them as reply templates or implement the actual business operation separately.

**Design correction:** propose a dedicated opaque `handoff_id` (not the sequential feedback row ID), a separate lifecycle status such as `pending`/`resolved`/`customer_closed`, immutable initial reason/comment, and atomic reply/resolve against exactly one pending episode. An opaque ID is defense-in-depth, never a substitute for authorization. Owner confirmation is still needed for lifecycle and history semantics.

### C. Roles, API coverage, audit and baseline gaps

- The design matrix currently focuses on Customer, Staff and Manager. The compared `origin/main` ref also has `viewer` and `platform_admin`, plus `/api/admin/*`. Expand role/endpoint coverage; do not imply permissions for omitted roles.
- `viewer` has `orders:read`, but feedback and customer-message routes do not perform the same permission check as Staff reply/resolve. If Viewer is intended to be read-only, block those writes; otherwise document and test the explicit exception. This is a same-customer write path, not evidence of cross-customer access.
- Staff reply/resolve accept `staff_name` from the request body. Use authenticated session identity for audit attribution.
- `/api/tools/execute` is a direct tool endpoint, not an LLM sub-agent. Review found validation and customer-bound tools; no ownership bypass was confirmed. Still decide whether it is disabled outside dev/harness and test every exposed tool's scope.
- The Manager “view order” UI path uses a conversation-focus/customer-ownership route; it needs a dedicated read-only Manager order-detail path if shop-wide order detail is intended.
- Existing docs contain stale baseline/status claims and some older plans describe simulated/planned capabilities as if operational. Mark `implemented`, `proposed`, `historical` and `simulated` consistently.

## Owner decisions still needed

| Decision | Conservative proposal for discussion—not yet approved |
|---|---|
| Who can enter Staff Desk? | Customer cannot; Staff and Manager by explicit permission; Viewer denied unless specifically approved; Platform Admin does not inherit Desk use implicitly. |
| Viewer writes | Return 403 for handoff/message writes if Viewer means read-only. |
| Staff `orders:cancel` | Separate personal/customer cancellation from Staff Desk; do not expand it into an AI action. Decide whether the existing permission remains. |
| Handoff lifecycle | One active pending episode per conversation; customer return-to-bot closes that episode as `customer_closed`; resolved history is separate from pending queue. Confirm or change this policy. |
| `/api/tools/execute` | Disable in persistent/production unless a specifically scoped operator use case is approved. |
| AI fields | Deny shipper personal phone and compensation voucher by default; explicitly approve product fields and aggregate revenue before exposing them to a model. |
| Resolved history | Decide whether Staff, Manager or both can view it, and set retention. |

## Required acceptance tests before implementation approval

1. Full role × endpoint × tenant/object matrix for the five roles in the reviewed baseline; include direct API calls, not UI-only tests.
2. Two parallel Staff-assist requests for different `handoff_id`s cannot mix context, output or actor.
3. Internal AI draft is absent from customer transcript; caches cannot return a broader projection into a narrower profile.
4. Staff cannot read/reply/resolve a non-handoff, resolved, stale or wrong-tenant case; invalid resolve does not report false success.
5. Create duplicate handoff requests, resolve A then create B, poll/reload and verify B remains active until B itself closes.
6. Human Mode attachment is either explicitly unsupported in UI or accepted, safely stored and shown to Staff.
7. Dispute model schemas match the server execution allowlist; unsupported tool calls fail closed.
8. Manager Desk loads/polls from both entry buttons; quick replies are clearly not represented as exchange mutations.
9. Intercept model gateway payloads and assert Manager receives only approved aggregates/task fields, never raw shop-wide orders/events by default.

## Review source links

- [Phase R1 design](../README.md)
- [Argon follow-up report (owner-pasted, summarized)](ARGON_FOLLOWUP_REVIEW_2026-10-25.md)
- [Argon revision-review prompt](ARGON_REVIEW_TRIGGER.md)
- Runtime sources named in the design's [source-of-truth index](../README.md#7-tài-liệu-liên-quan-và-nguồn-chuẩn)
