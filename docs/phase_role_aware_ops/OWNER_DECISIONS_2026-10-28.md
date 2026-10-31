# Phase R1 — Owner decision delta (2026-10-28)

> **Status:** W0 documentation/reconciliation record only. This file records owner direction; it does not authorize application-code changes, database migration, merge, CI, EC2, Colab or deploy.
> **Revision note:** historical 2026-10-28 snapshot. The 2026-10-29 [W0 owner decision delta/proposals](W0_OWNER_DECISION_DELTA_2026-10-29.md) supersedes this snapshot for OD-02 Viewer disposition, OD-03 timer direction, and OD-08 image/file capability—including the obsolete GGUF/`mmproj` characterization in this file. Use the newer delta for current policy; this file remains historical evidence only.

## 1. Decisions recorded

### 1.1 Business roles and admin paths

- The only business roles are `customer`, `staff` and `manager`.
- The store owner uses `manager`; there is no separate `owner` role.
- `opsadmin` is a separate authentication path for the read-only Ops Admin Console. It is not a business-chat role and is not an alias for any application membership role.
- `platform_admin` is legacy technical debt, not a fourth target business role. The target is to deprecate and remove it gradually. Do **not** implement `platform_admin = manager` as a runtime alias and do **not** transfer its historical cross-tenant/control-plane privileges to Manager.

The deprecation still requires a separate ADR and migration packet before code or data changes:

1. stop provisioning new `platform_admin` memberships;
2. run an aggregate-only inventory of existing memberships, tenants, active state and linked sessions;
3. migrate only explicitly eligible, same-tenant accounts to `manager` after owner approval;
4. remove legacy cross-tenant/platform-admin grants from migrated accounts;
5. invalidate affected sessions and preserve audit history;
6. provide backup, forward-compatibility and tested rollback evidence; and
7. retire the role from schema/RBAC only after no dependency remains.

Until that packet is approved, current `platform_admin` source behavior is a historical/drift finding, not a permission grant for the target design.

### 1.2 Viewer

`viewer` is legacy and is not in the target taxonomy. It must fail closed at backend authorization and must never be silently promoted to `customer` by Google login, `DEFAULT_ROLE`, or any other login-time synchronization. Owner direction: remove a legacy Viewer membership only when that is safe; if it cannot safely be removed, disable its application access (and invalidate affected sessions) rather than leave it usable. This concerns the app membership/access, not disabling the person's Google account. Aggregate inventory and a tested migration/rollback plan are still required; W0 performs no migration.

### 1.3 Trusted display name and audit actor

- Audit and authorization use the server-derived authenticated `principal_id`, role, tenant and timestamp.
- A browser-supplied `staff_name` is not a trusted actor field. Future Staff/Manager reply, resolve, handoff and audit APIs must ignore or reject it; it must not be persisted as the actor.
- Internal UI may show the Google account `display_name` obtained server-side from the authenticated session. If no trusted display name is available, the UI must show no canned greeting or demo identity.
- Presentation `display_name` is separate from the immutable audit principal.

### 1.4 Case selection, context and vector retrieval

- `case_id` is the primary work-item identity. `conversation_id` identifies the conversation; `turn_id`/`message_id` identifies transcript items; `handoff_id` identifies one handoff episode; `order_action_request_id` identifies a cancel/return request; `order_id` is a verified business object.
- A copied chat title, free-text label or browser-supplied name may be a UX shortcut only. It never authorizes access and never identifies a retrieval scope by itself.
- Every Staff/Manager internal AI turn must be server-bound to `principal_id`, role, `tenant_id`, `execution_profile` and an explicitly selected `case_id`, plus only verified linked objects. No selected case means fail closed.
- Case transcript/context and knowledge/vector evidence are separate projections. The case binding identifies **which chat segment** is being discussed; the vector store supplies tenant/profile-allowlisted policy or knowledge evidence and cannot independently identify the requested chat segment.
- Vector/lexical retrieval must run only after case authorization, with tenant/profile/projection filters, bounded citations and auditable retrieval metadata. Raw attachments are excluded from model payload by default.
- Internal questions, prompts and drafts are stored outside the customer transcript and customer-facing event API.

## 2. Decision-register disposition

| ID | Current disposition after owner direction | Still required before implementation |
|---|---|---|
| `OD-01` | **Owner direction recorded:** deprecate/remove `platform_admin`; keep `opsadmin` separate; no runtime alias. | ADR, aggregate inventory, eligible mapping rules, session handling, rollback and retirement migration approval. |
| `OD-02` | **Owner direction recorded:** Viewer is legacy, fail closed, never auto-promote; remove a membership only if safe, otherwise disable its app access. | Aggregate inventory, affected-session handling, migration and rollback tests. |
| `OD-03` | **Owner direction recorded:** Staff and Manager can receive/claim, release and transfer cases. Use exactly three case statuses/buckets: `waiting` (Hàng chờ), `in_progress` (Đang xử lý), `resolved` (Đã xử lý); do not use `cancelled` as a case status. After 20 minutes without customer reply, auto-resolve. If the customer signals completion, gently ask if they need anything else; if not, request Like/Dislike or 1–5-star satisfaction feedback, then auto-resolve after about 5 minutes. Like/4–5 maps to `chosen`, Dislike/1–3 to `rejected`; show a thank-you and retain feedback linked to the outcome for later model improvement. Completed human handoff work also becomes `resolved`; a customer reply after resolution reopens/requeues work to `waiting`. | Define timer anchor/reset and race/idempotency rules, exact completion-intent handling, whether reopening reuses the same `case_id`, resolved-history access, feedback event schema and privacy/retention. Do not train/update the live model automatically per rating. Order cancellation remains a separate order-action outcome. |
| `OD-04` | **Owner direction recorded:** Customer, Staff and Manager retain the stated ability to cancel a pending order; Manager may use the direct order-status update path. Customer is the return requester; Staff or Manager may approve/reject the return request. Preserve decision history, update the DB and use one JSONL data format/schema for both integration input and output. | Define Staff's exact acting-for-customer scope; exact JSONL envelope/fields, audit history and DB transaction/outbox/retry contract, return/refund states and external consumer contract. AI cannot decide/approve. |
| `OD-05` | **Scope clarified:** this refers to the app's `/api/cancellation-proposals*` business routes, not DeepSeek/OpenAI/provider APIs. The 20-minute/5-minute auto-close direction is for a conversation/case, not this order-cancellation API. | Keep/adapt/supersede and compatibility/deprecation plan for existing app clients. |
| `OD-06` | **OPEN; explanation provided.** | Canonical return-request and post-approval fulfillment/refund states. Keep these distinct from case/handoff status and decide whether order status needs any new values. |
| `OD-07` | **OPEN.** | Migration versioning, compatibility, backup, session and rollback plan. |
| `OD-08` | **Technical question checked:** Gemma 4 12B supports image input; the named GGUF needs a compatible `mmproj` and this fine-tune's vision quality is not author-tested. The reviewed application currently classifies the named fine-tune as text-only and sends document names without PDF/OCR extraction. | Decide whether attachments may be sent to AI; storage, MIME/size/count, scanning, access and retention policy remain open. The supplied Colab startup cell starts vLLM/ngrok but does not itself issue an image request, configure a compatible `mmproj`, or perform PDF extraction, so current L4 endpoint capability remains unverified. |

For OD-08, the [official Gemma 4 12B model card](https://huggingface.co/google/gemma-4-12b-it) demonstrates image input. The [named fine-tune's GGUF repository](https://huggingface.co/yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2-GGUF) does not include the vision projector; its model-owner discussion says a compatible Gemma 4 `mmproj` is required and notes that vision quality on this fine-tune has not been personally tested. This establishes technical capability, not that the current Colab/L4 serving endpoint is configured or validated for image requests.

### 2.1 OD-03/OD-04 lifecycle boundary

Use one case lifecycle vocabulary only: `waiting`, `in_progress`, and `resolved` (Staff Desk labels Hàng chờ, Đang xử lý, Đã xử lý). Do not call a closed case “cancelled” or add a `cancelled` case bucket. The 20-minute timeout, customer-completion flow, and completed human handoff all end at `resolved`. This never sets `orders.status='cancelled'`, approves a return, or issues a refund; cancelling an order does not by itself close its case.

For returns, Customer submits the request; an authenticated Staff or Manager may approve/reject it. Retain approver principal/role, time, request/order linkage, decision and relevant state/version. Persist the decision and database update consistently. Owner selected JSONL as the single data format/schema family for both integration input and output; exact envelope/fields, delivery and retry mechanics remain to be specified. Do not let the model approve or write the decision.

Customer satisfaction feedback applies both when the agent completes a case end-to-end and after Staff/Manager intervention (including an order-cancellation case). Offer Like/Dislike and/or a 1–5-star control; normalize Like or 4–5 stars to the owner-selected `chosen` label, and Dislike or 1–3 stars to `rejected`. Show a brief thank-you after submission. Store feedback linked to the case/outcome for later offline evaluation and model improvement; do not treat it as an order decision or automatically train/update the live model from one rating. Exact event schema, privacy/retention and consent boundaries remain implementation details to approve.

## 3. W0 consequence

The owner direction narrows the contract but does not lift the Argon readiness block. W0 may update docs, inspect source and prepare aggregate-only inventory/reconciliation. W1–W6 remain unauthorized until the unresolved implementation decisions above are approved and a new readiness review is completed on an exact clean candidate. The SHA `bbfd11d0ba4c13514a197a6b25802c4e217bedb3` is the baseline recorded at the time of the prior review; it is not an assertion that this remains the latest GitHub `main`. Verify remote `main` afresh before preparing a future candidate. A requested or pending readiness review is not clearance; the completed review must explicitly clear `BLOCKED`.

## Related records

- [Canonical R1 design](README.md)
- [Current owner decision delta](W0_OWNER_DECISION_DELTA_2026-10-29.md)
- [W0 review reconciliation (review chronology)](W0_REVIEW_RECONCILIATION_2026-10-28.md)
- [W0 baseline and decision register](W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md)
- [Current implementation readiness: BLOCKED](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md)
- [Archive index](archive/README.md)

