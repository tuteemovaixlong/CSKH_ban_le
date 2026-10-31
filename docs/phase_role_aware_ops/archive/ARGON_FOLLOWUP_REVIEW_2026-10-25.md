# Gemini 4 Argon — Phase R1 Follow-up Review (2026-10-25)

> **Verdict reported by Argon:** `PASS WITH REQUIRED CHANGES`. This is a source/design review, not implementation approval, a test result, or evidence about the deployed EC2 runtime.

## Review basis and limits

- This synthesis records the follow-up report pasted by the project owner on 2026-10-25; Codex did not independently rerun Argon's full source audit in creating this summary.
- Argon reports read-only comparison of committed `HEAD dd544800bb087d54a7faf564e723736905620045` and local `origin/main bbfd11d0ba4c13514a197a6b25802c4e217bedb3`. Its report explicitly says `origin/main` was not freshly fetched from GitHub for that review.
- No tests, database migrations, live services, Google OAuth, LLM gateway, deployment, or EC2 runtime were checked.
- Argon accepted the owner constraint: Customer, Staff, and Manager must use one shared workflow/graph core. Request profiles, authorization, input/output adapters, and stores may differ; the graph must not be duplicated by role.

## Findings that must be reflected in the design

### P0 — Current object-scope gap; future case-assist binding

Argon reports that Staff/Manager transcript, reply, and resolve routes are tenant-scoped but are not bound to one pending handoff episode. The reported paths allow access to an arbitrary conversation in the same tenant; resolve may return success without changing a matching pending handoff. The proposed `staff_case_assist` order rule also fails when a handoff has no `order_id` even though the customer mentioned a valid order in the transcript.

**Design requirement:** make each Desk operation resolve an opaque `handoff_id` to exactly one pending episode in the authenticated tenant, and re-check that state atomically for read/reply/resolve/assist. A server-side `allowed_order_ids` set may include a transcript-mentioned order only after verifying that it belongs to the case customer and tenant; the model cannot choose the customer or expand that set. This is a code-level finding at the reviewed refs, not a claim about a live exploit.

### P0 — One graph requires profile-safe persistence and dispatch

Argon reports that PostgreSQL `graph_runs.customer_id` is non-null and foreign-keyed to `customers(id)`. A Staff/Manager identity created outside the customer table could therefore fail if used as `customer_id`. Reusing customer identity/thread keys for internal assistance risks checkpoint/history collisions. The current `single_agent` fallback may also select customer instructions and the broad customer tool schema if an internal profile reaches it.

**Design requirement:** keep one shared LangGraph orchestration core for all three profiles; include `execution_profile` in typed per-invocation state and make internal profiles fail closed rather than falling through to a customer-only `single_agent` path. Redesign graph-run actor/subject references so internal principals do not require a fake customer row. Scope `purpose`, fingerprint and thread key by tenant, actor, profile, conversation/handoff, and projection version. Never put selected-case context on mutable singleton `Application` state.

### P1 — Worker, audit, cache and quota boundaries

- Argon reports the Dispute worker exposes all 12 protocol tool schemas but handles only 7, silently ignores unsupported calls, drops earlier transcript turns and attachment evidence, and uses customer-facing reply templates. Supervisor keyword escalation may create a false handoff when Staff quotes a customer.
- Client-provided `staff_name` can spoof the displayed actor. Internal events written under a customer's business-event identity may be returned by customer-facing `GET /api/events`; future internal drafts or principal metadata must not be stored there.
- `ToolCache` lacks a profile/projection scope. Staff/Manager AI usage must be charged to the authenticated staff/manager membership, not the customer; error telemetry must not query a Staff principal as if it were a customer.

**Design requirement:** use profile-specific, server-enforced tool allowlists with fail-closed handling; preserve selected-case transcript/evidence for Staff; disable customer-only cancellation/escalation semantics for internal profiles. Derive actor attribution from session binding, store internal audit/assist history separately, and give customer event APIs a strict public-field/kind allowlist. Add profile/projection/case scope to cache keys or bypass caches for internal assistance. Separate usage/quota identity from the subject customer.

### P1/P2 — Handoff and UI behavior

Argon reports defects at both reviewed refs: re-handoff may be closed by an old resolved row; the UI may announce a handoff before persistence succeeds; Human Mode attachment submissions are rejected; resolved rows can crowd pending queue entries/counts; Manager's Desk entry does not load/poll the queue; Manager order view can route through customer-owned conversation focus and return 404; exchange approval buttons send reply text rather than execute an exchange.

**Design requirement:** model immutable handoff episodes with separate status and a dedicated `handoff_id`; update UI only after persistence confirmation; poll the active episode; filter pending queue/count; either implement attachment storage safely or disable the control clearly. Label exchange quick actions as reply templates unless a real exchange transaction exists. Provide a separately authorized Manager order-detail path if shop-wide detail is intended.

### P1 — Role baseline correction and complete surface coverage

- `dd544800` does not define `platform_admin` in `ROLE_PERMISSIONS`; Argon reports `bbfd11d0` does define it and grants `READ`, `CANCEL`, `STAFF`, `MANAGER`, and `PLATFORM_ADMIN`. Thus the existing R1 note that access must not be inferred from inheritance is a target-policy statement, not an accurate description of `bbfd11d0` runtime behavior.
- Argon reports `viewer` has `READ` but can still reach several write routes that do not check the permission, including chat/conversation and handoff/customer-message paths.
- The design needs all five roles and the customer, manager, admin, usage, events, cancellation, and future R1 endpoints, plus direct-call tests.

**Design requirement:** record present inheritance accurately while keeping the future `platform_admin` business-console policy explicitly unapproved. Prefer a least-privilege target (no Staff Desk/Manager business access for platform admin unless the owner approves it; `/api/admin/*` remains a distinct capability). If `viewer` means read-only, deny writes in backend routes, not only UI.

### P2 — Diagram and field-projection corrections

- In the architecture Mermaid diagram, tool/data exchange must show the server tool executor applying the allowlisted projection before returning results to the model; do not draw a direct data-to-model path.
- In the handoff sequence, internal AI assist history must use a separate `Internal Assist Store`, not the handoff queue participant.
- Define exact shipment/product fields, message-count and text-size caps. Conservative proposal: exclude shipper name/phone and compensation voucher identifiers; do not pass full product or order payloads. The exact policy remains for owner approval.

### P3 — Snapshot/ref drift

Argon flags `docs/CURRENT_PROJECT_STATUS.md` and `docs/PLAN_ROADMAP_INDEX.md` as still describing `origin/main 83bee6c` while the R1 packet cites `bbfd11d0`. The workspace currently has `origin/main` at `bbfd11d0ba4c13514a197a6b25802c4e217bedb3`; its reflog shows a fetch on 2026-10-24 18:46 +07, not a fetch performed for this documentation update. Preserve the earlier `83bee6c` seeding observation as a dated historical snapshot, and make the newer local-ref observation explicit. Neither ref establishes current GitHub state or EC2 deployment state.

## Owner decisions remain open

The follow-up did not approve product policy. Before implementation, decide or explicitly accept conservative defaults for:

1. Whether `platform_admin` may use Staff Desk/Manager business APIs in addition to separate `/api/admin/*` privileges.
2. Whether `viewer` is strictly read-only; whether Staff's `orders:cancel` remains only for personal orders and outside Desk AI.
3. Handoff lifecycle (`customer_closed` on return-to-bot; one pending episode per conversation), attachment support, and access/retention for resolved history.
4. Whether Staff assistance may look up only transcript-mentioned orders after verifying ownership when the episode has no linked `order_id`.
5. Exact model field allowlists (including shipper/voucher, product price/material/care, and Manager revenue), `/api/tools/execute` production policy, and separate Staff/Manager quotas.

## Required next gate

Revise and cross-link the R1 design, record owner decisions or visibly pending conservative proposals, then ask Argon for a read-only review of the revised packet. Do not start runtime implementation until the endpoint/tool/data contracts, PostgreSQL checkpoint identity, handoff lifecycle, and acceptance tests are implementation-ready. See [R1 design](../README.md), [synthesized Codex findings](REVIEW_FINDINGS_2026-10-25.md), and [Argon revision-review prompt](ARGON_REVIEW_TRIGGER.md).

## 2026-10-26 independent reconciliation addendum

The owner subsequently supplied a Claude Opus report (`PASS WITH REQUIRED CHANGES`) and requested independent review. Three read-only Codex sub-agents reviewed security/RBAC/API, workflow/LLM/tools/RAG/cache, and UI/lifecycle; a fourth reviewed docs/acceptance/baseline. Their reconciled assessment is recorded in [INDEPENDENT_AUDIT_SYNTHESIS_2026-10-26.md](INDEPENDENT_AUDIT_SYNTHESIS_2026-10-26.md). It refines, rather than erases, this report: same-tenant handoff object-scope is confirmed, but cross-tenant access is not evidenced; current checkpoint customer/request/purpose/lease scoping exists, while actor/profile/case/projection scoping remains a conditional R1 blocker. The local refs and limits are stated in the synthesis.

The documentation-only Argon review completed on 2026-10-26 with verdict `PASS WITH REQUIRED CHANGES`; see [ARGON_DOCS_REVIEW_2026-10-26.md](ARGON_DOCS_REVIEW_2026-10-26.md) and the [trigger used](ARGON_DOCS_REVIEW_TRIGGER_2026-10-26.md). This addendum preserves the historical follow-up review and does not approve implementation or owner-policy choices.
