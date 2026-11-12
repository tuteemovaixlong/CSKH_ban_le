# Phase R1 — W0 Owner Decision Delta & Proposals (2026-10-29)

> **Status:** W0 owner decision and accepted-mechanics record (updated 2026-10-31). Sections §1–§9 preserve the 2026-10-29 analysis/proposals; **[§10](#10-final-owner-decisions-2026-10-31) and [§11](#11-accepted-mechanics-2026-10-31) record the settled 2026-10-31 owner decisions and accepted mechanics and govern wherever earlier sections still say open or proposal-only.**
> **Execution gate (2026-10-31):** On 2026-10-31 the owner issued an explicit, bounded **W1-only** authorization (W0 documentation closeout + W1 identity, RBAC, backend authorization, and isolated W1 tests only). This is **not** a new readiness review and does **not** change [implementation readiness](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md) to `READY`. `W2–W6`, live database/production migration, EC2/SSM, Colab/ngrok runtime calls, commit, push, merge and deploy remain **not authorized**.
> **W1 state (2026-10-31, status note only — §10/§11 unchanged):** W1 remediation was executed and verified; the two W1 policy questions are now decided by the owner in [§12](#12-w1-policy-decisions-2026-10-31). No W1 blocker remains open; the owner confirmed W1 closed on 2026-10-31 (W1 complete), and overall readiness stays `BLOCKED` for `W2–W6`. See the [readiness register](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-10-31-w1-owner-policy-decisions-and-closure-status).
> **Authority:** This is newer than [the historical 2026-10-28 owner decision snapshot](OWNER_DECISIONS_2026-10-28.md) only for the OD items below. A later owner follow-up in this thread confirmed the OD-01 separation points, clarified OD-03 reset/flag policy, added image/file processing to the R1 plan, and requested real customer data on Colab inference as the target. This is **not authorization to send live data through the current public ngrok endpoint or bypass the W0/readiness/security gates**. Treat historical proposals in §1–§9 as superseded wherever [§10](#10-final-owner-decisions-2026-10-31) and [§11](#11-accepted-mechanics-2026-10-31) decide or accept them.

## 1. Decision status at a glance

| OD | Latest owner input | W0 disposition |
|---|---|---|
| OD-01 | `opsadmin` stays in its separate Ops Console; retire `platform_admin` gradually; do not transfer cross-tenant privileges to Manager | **Owner direction recorded** for separation and no privilege transfer. Whether Manager retains same-tenant account administration on app `/api/admin/*` remains **open**. |
| OD-02 | Disable Viewer; remove memberships where safe; if removal affects integrity, freeze/lock and phase out | **Owner direction recorded** at policy level. Safe-removal criteria, inventory, session invalidation and rollback remain open. |
| OD-03 | 3-minute no-response interval; customer reply resets it; no automatic closure solely due to system overload; 1.5-minute flag is never enabled in production, only in evaluation and specialized test states | **Owner direction recorded.** Reset rule and production prohibition are settled. Exact timer-starting event, eligible state, and whether inactivity is only recorded or transitions the case to `resolved` remain to be written into the transition contract. |
| OD-04 | Asked for analysis/proposal on Staff scope, JSONL envelope, DB/outbox/retry transaction | **Proposal only; needs owner selection.** |
| OD-05 | Asked what the legacy API decision means | Scope is clarified: application cancellation routes, not model-provider APIs. Proposal only; compatibility decision remains open. |
| OD-06 | “ok” after asking for return/refund vocabulary | Separation is accepted directionally; no exact vocabulary was named. Proposed vocabulary below needs confirmation. |
| OD-07 | “ok” after migration/backup/session/rollback question | Need for a versioned, recoverable migration is acknowledged; exact mechanics and rollback boundary remain open. |
| OD-08 | Include image/file processing across R1; prepare a production-capable Colab inference path that can process real customer data when enabled, using compact case context | **Target direction recorded, not activated.** Do not ship the full transcript by default; use minimized, server-authorized, case-bound context. The current Colab launch is configured for 8,192 tokens; 16,384 is an evaluation candidate only if L4 memory, latency and quality tests support it. Exact fields/media and minimization remain to be frozen. The supplied public ngrok/vLLM endpoint lacks configured API-key protection and verified privacy/request controls, so it is not acceptable for live customer data. The app suppresses image pixels for this model ID; files/PDF are not parsed; no runtime test was run. Evidence policy and readiness remain gates. |

## 2. OD-01 — Manager tenant administration vs `opsadmin`

### What the current source actually does

- The Admin Console login called `opsadmin` is created as a Caddy Basic Auth identity for a separate **read-only Ops Console**; it is not an application membership role. See [`docs/ADMIN_CONSOLE.md`](../ADMIN_CONSOLE.md).
- The app's `/api/admin/accounts*` and `/api/admin/audit-log` are different routes. In the reviewed source, the account-governance layer supports Manager within its tenant and legacy `platform_admin` with a broader explicit tenant scope. See [`retailops/http/routes.py`](../../retailops/http/routes.py) and [`retailops/identity/store.py`](../../retailops/identity/store.py).
- Therefore, “`opsadmin` has a separate page” does **not** mean the current `opsadmin` credential authenticates the app's `/api/admin/*` routes. Converting it to the sole admin would require new authentication/integration and likely changing the read-only console's scope.

### Recommended low-complexity boundary (proposal, not approval)

1. Keep Manager responsible for **same-tenant business account administration** only, with tenant derived from the authenticated server session and no browser-selected cross-tenant scope.
2. Keep `opsadmin` limited to the separate Ops Console/control-plane function. Do not turn it into a hidden business role or use it as an application-session alias.
3. Gradually retire `platform_admin`; do not copy its cross-tenant permissions to Manager or `opsadmin`.
4. If a platform-wide administrative action is ever needed, define that as a separate, explicit Ops Console capability and audit boundary rather than making every `/api/admin/*` route global.

This preserves existing Manager tenant-scoped account administration and avoids building a second write-capable admin system just to retire a legacy role. It requires an owner decision that the term `/api/admin/*` may contain Manager-authorized, tenant-scoped routes. If instead `opsadmin` must be the only caller of every route under that prefix, the routes must be split or moved and the current Manager UI/API contract must be inventoried first.

**Still open:** whether Manager retains same-tenant account administration on app `/api/admin/*`, or if those endpoints should be restructured so `opsadmin` is their sole principal. The owner has confirmed that `opsadmin` remains a separate Ops Console identity and that `platform_admin` cross-tenant permissions must not move to Manager.

## 3. OD-02 — Viewer quarantine/removal

Record the latest direction as: deny/disable application access for Viewer immediately when the approved change is implemented; remove Viewer membership rows only when aggregate inventory proves removal will not break identity/business data integrity. If direct removal could orphan or mis-link data, first freeze the membership (no login/session access and no role promotion), then migrate/relink only under an approved plan and remove it gradually. Invalidate affected sessions. Never delete a customer, order, conversation or audit history as a side effect of removing a Viewer membership.

“Safe to remove” must be based on read-only aggregate checks for shared `customer_id`, foreign-key dependencies, identity collisions and linked sessions—not on email/name inspection or an assumed empty account. Exact rollback and audit treatment remain part of OD-07.

## 4. OD-03 — 3-minute target and timer safety

The owner's latest target supersedes the previous 20-minute target: **3 minutes with no customer response marks the interaction inactive**. Each new customer reply resets the inactivity timer. **1.5 minutes is never enabled in production**; the flag may be enabled only in evaluation and specialized test states. Do not interpret load/overload as a reason to shorten the timer or close/resolve a live customer's or staff-owned case.

### Conservative mechanics proposal

- Keep the production inactivity interval at the owner-selected 3 minutes. The 1.5-minute flag is prohibited in production and may be enabled only in evaluation or specialized test states; record the selected interval and test state with each evaluation result.
- Reset the inactivity timer on every new customer reply. Use durable compare-and-set/versioned transitions so a timeout cannot win against a concurrent customer reply, staff claim, transfer or new handoff.
- Measure inactivity only when a customer response is explicitly awaited. Do not trigger case closure from system load, model queue depth, or overload. The case lifecycle state (`waiting`/`in_progress`) and the “awaiting customer” timer condition are separate facts; exact eligible transitions remain to be frozen.
- Keep completion handling distinct: the agent asks whether anything else is needed, then presents feedback controls; the exact point from which the short post-feedback timer starts is still to be chosen.
- Treat timer/retention as separate clocks. Conversation TTL must not delete a pending case, handoff, decision, evidence or feedback record.

**Still needs specification (owner direction now recorded):** identify the exact outgoing prompt/event that starts the 3-minute timer, which states are eligible, and whether inactivity only records an inactive marker or transitions the case to `resolved`/Đã xử lý. The customer-reply reset and prohibition on enabling the 1.5-minute flag in production are settled. Keep completion-feedback follow-up timing separate unless the owner later replaces that policy.

## 5. OD-04 — Suggested order-action contract (proposal)

The current source already has distinct paths: customer `/api/cancellation-proposals*` and a Manager direct order-status endpoint (`/api/manager/orders/update-status`). These are historical source behavior, not an approval of their present authorization or transaction design.

### Suggested authority matrix

| Actor | Cancel pending order | Return request | Return decision / refund |
|---|---|---|---|
| Customer | May request/confirm cancellation only for their own eligible pending order through a customer-bound path | May create and view their own request | Cannot approve/reject or issue a refund |
| Staff | May assist with cancellation only for an order linked to an authorized case/customer, with a server-derived actor, reason and audit trail; no arbitrary order status editing | May review the linked request | May approve/reject if authorized for that case; approval is not itself payment execution |
| Manager | May use an explicit, audited direct status transition for an authorized tenant order; only enumerated transitions, expected version and reason | May review the linked request | May approve/reject; refund execution should remain a separate verified payment outcome |

This honors the recorded direction that Customer/Staff/Manager can handle pending-order cancellation and Manager may directly update status, while preventing Staff from becoming a generic database/status editor. **Owner must confirm** whether Staff's cancellation is self-service on behalf of the customer or a customer-authorized action, and whether Staff approval may authorize a refund or only the return decision.

### Suggested transaction and JSONL contract

1. Treat the relational DB as the source of truth. In one DB transaction, validate tenant/order ownership, current status and `expected_order_version`; write the request/decision and append-only audit; update the order/return projection; and insert a uniquely identified outbox event.
2. Commit all of that atomically. If the transaction fails, neither business state nor an externally visible success event is written. Do not try to make an external JSONL consumer part of the DB transaction.
3. A worker serializes the committed outbox event to JSONL and delivers it with **at-least-once** semantics. Consumers deduplicate on stable `event_id`/`idempotency_key`; retry with bounded backoff and preserve failed events for operator review. Do not claim exactly-once delivery.
4. Use one versioned JSONL envelope family in both directions (not necessarily identical event types): `schema`, `schema_version`, `event_id`, `event_type`, `occurred_at`, `tenant_id`, `actor {principal_id, role}`, `case_id`, `conversation_id`, `order_action_request_id`, `order_id`, `expected_order_version`, `before`, `after`, `reason_code`, `evidence_refs` (opaque authorized IDs only), `correlation_id`, `idempotency_key`, and `source`. Validate inbound records, allowlist event types, reject unknown/invalid transitions, and audit imports.

The exact required/optional fields, PII policy, evidence references, external consumer contract, refund/payment gateway boundary, and actor/case link policy still need owner approval. JSONL is the interchange/audit export format, **not** a replacement for transactional DB state.

## 6. OD-05 — What `/api/cancellation-proposals*` means and recommended disposition

These are application HTTP routes for business cancellation proposals—not DeepSeek, OpenAI, vLLM or other LLM-provider APIs. Their current tests and callers include customer cancellation UI flows, integration/E2E tests and live-smoke contract code. Removing/renaming them immediately could break deployed clients even if the LLM provider is unchanged.

**Recommendation:** retain the routes as a compatibility facade for the existing cancellation UX, move their behavior behind a shared order-action service when implementation is authorized, and add distinct return-request/review endpoints rather than overloading “cancellation proposal” to mean return/refund. Mark an old route deprecated only after inventorying every UI, test, script and external caller and shipping a compatible replacement; remove it only after a measured deprecation window and explicit approval. The existing route names need not dictate the new domain schema.

This is a proposed migration strategy, not a final route contract. Owner confirmation needed: retain/adapt as above, or version/supersede now and accept the client migration work.

## 7. OD-06 / OD-07 — Proposed status and migration boundaries

### OD-06 proposed vocabulary

Keep three independent dimensions; do not add return/refund states to Staff Desk case state or conflate them with `orders.status`:

- **Case:** `waiting` → `in_progress` → `resolved`.
- **Return request:** `requested` → `under_review` → `approved` **or** `rejected`; an approved return may proceed through `received` → `inspected` → `completed`.
- **Refund execution:** separate `not_applicable` / `pending` / `refunded` / `failed` result, linked to the request/order. “Approved” means permission to proceed, not money already returned. Do not report `completed` until the approved return's required operational steps and any applicable refund are verified.

This vocabulary is a recommendation for owner review, not an approved schema. Confirm whether `under_review` is needed, what inspection may conclude (refund, replacement, no action), and which system is authoritative for `refunded`.

### OD-07 proposed migration guardrails

Use an ordered, versioned migration with preflight aggregate counts, backup/restore evidence, compatibility window, forward migration, post-migration invariants, and a tested rollback/roll-forward decision before production. Invalidate affected sessions only after the new role/access state is committed; preserve append-only audit. If destructive rollback is unsafe because new business actions occurred, use an explicit compensating migration rather than restoring stale DB data. “OK” records agreement that rollback/session handling is required; it does not choose a tool, version number, maintenance window, backup retention or production procedure.

## 8. OD-08 — Re-evaluation of image/file support

### Model and application findings

- The exact [Hugging Face model card](https://huggingface.co/yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2) labels itself `image-text-to-text` and includes an image-input example; its vLLM serving section documents serving the same safetensors model. This supports **model-level image capability**, not proof that this Colab process or RetailOps application passes and processes image bytes correctly. The [vLLM Gemma 4 guide](https://docs.vllm.ai/projects/recipes/en/stable/Google/Gemma4.html) documents Gemma 4 image input over the OpenAI-compatible chat interface.
- The supplied Colab cell uses the **safetensors model ID**, not the GGUF repo; a GGUF-specific `mmproj` requirement should not be used to characterize this exact path. The cell starts the server but sends no image request; it also does not parse PDF/document files.
- **Critical application mismatch at verified source `bbfd11d0`:** `retailops_providers.py` puts this exact model ID in `TEXT_ONLY_MODELS`; `is_vision_model()` therefore returns false, and `OpenRouterAgent.translate()` replaces an image with a filename notice instead of sending `image_url` pixels. The test `tests/test_react_tool_summary_safety.py::test_attachment_handling_for_text_only_and_vision_models` explicitly asserts this behavior for the exact model name. Changing the Colab startup alone will not fix that app-side suppression.
- For `document`, the current adapter emits a filename notice; there is no PDF/OCR/text extraction path. Thus “supports image” does not mean “supports arbitrary files.”
- The supplied `vllm_cmd` does not configure `--api-key`, then exposes port 8001 through a public ngrok URL. Do not send real customer evidence through this tunnel as shown. Current vLLM security documentation warns that API-key protection covers only selected endpoint prefixes and recommends additional network/reverse-proxy controls; the notebook also needs an endpoint-authentication and request-limiting design before any non-synthetic use.
- The notebook's vLLM version is not pinned, and the Jinja template is fetched from the moving vLLM `main` branch and patched at runtime; there is no live L4/Colab request evidence. Pinning the model revision, vLLM build and template digest is required for a reproducible validation. Runtime compatibility, image resolution/limits, template/tool-call interaction, FP8 settings and actual quality remain unverified.

### Phase mapping for safe image/file support (plan only; no implementation in W0)

The owner wants R1 prepared for production use of real customer data on Colab inference once enabled. The data flow should use compact, server-authorized, case-bound context rather than a full conversation dump by default. The supplied Colab launch sets `--max-model-len 8192`; 16,384 may be evaluated if needed, but must not be raised without L4 memory, latency and quality evidence. This target **does not authorize sending live customer data now**: the public Colab/ngrok path lacks configured vLLM API-key protection and verified privacy/request controls, W1/W4 are not authorized, and implementation readiness remains `BLOCKED`. Exact context fields, data minimization and which validated image/document projections may be included remain to be frozen.

| Work package | Image/file scope to add | Minimum boundary |
|---|---|---|
| **W0 — contract/reconciliation** | Decide evidence lifecycle, allowed media types, per-file/request size/count caps, retention/deletion, model-eligibility and whether the model receives raw media or a derived projection. | Read-only design only. Use model capability matrix; do not test with customer data. |
| **W1 — identity/RBAC** | Authorize upload, list, preview and download by authenticated tenant, principal, case/order-action relationship. | Opaque evidence ID is not authorization; cross-tenant and wrong-case access fail closed. |
| **W2 — case/handoff** | Persist evidence references and audit metadata on the correct case/handoff episode without tying evidence retention to conversation TTL. | Retain immutable source/hash and lifecycle/retention metadata; prevent expiry cleanup from deleting active case evidence. |
| **W3 — cancel/return** | Attach optional evidence to the order-action request; include only authorized evidence references and hashes in the shared JSONL envelope, never raw bytes. | Evidence belongs to the request/order/tenant; approval remains human-authorized; DB + audit + outbox stay transactionally consistent. |
| **W4 — shared AI** | Add an explicit per-model capability path: send an image only to an allowlisted vision-capable endpoint after scanning/validation; parse PDF/text separately into a bounded, page-cited projection; construct compact selected-case context. | Current Gemma app adapter suppresses images; fix only in an authorized slice with provider-payload tests. Start from the current 8,192-token serving limit; evaluate 16,384 only if L4 memory/latency/quality evidence supports it. No arbitrary file/raw base64 into tools, cache, checkpoints, logs or prompts; AI output is advisory and cannot mutate orders. |
| **W5 — UI** | Add upload, progress/error states, safe preview, evidence list and access-aware case/order-action detail panel. | Do not expose evidence in customer/staff UI outside its case/order authorization; clearly reject unsupported types. |
| **W6 — verification/rollout** | Test MIME spoof/corrupt/oversized/multiple files, image grounding, PDF extraction/page provenance, tenant/case isolation, deletion/retention, provider payload and failure paths. Pin model revision, vLLM version and chat-template digest for Colab L4 evaluation; measure 8,192 vs optional 16,384 context. | Use synthetic/sanitized fixtures for evaluation. The eventual production path for real data requires a separately reviewed, authenticated/protected endpoint, compact case-bound context, approved data minimization/scope, privacy/retention controls and explicit release approval; do not send real customer data to the current public ngrok tunnel. The 1.5-minute timer flag remains non-production evaluation/specialized-test only. |

**Proposed processing shape:** validated evidence object → authorized, scanned source → (a) image sent only to a verified vision endpoint or (b) document extracted through a bounded PDF/text/OCR parser → versioned, source-linked projection with page/region references and uncertainty → AI analysis shown to Staff/Manager for human review. Keep the original file outside the prompt; never treat model interpretation as proof or as authority to cancel/return/refund.

### Conservative evaluation path (after owner approval, not in W0)

1. The owner has requested real customer data on Colab inference. Before honoring that target, define the minimum payload and allowed modalities, and replace the current public tunnel with an authenticated/protected endpoint and documented privacy, logging, retention/deletion and access controls. Until those gates pass, do not send real customer data; use synthetic/sanitized fixtures. Do not treat the ngrok auth token as inference-endpoint authentication.
2. In a later authorized code slice, replace the hard-coded model-name heuristic with explicit per-provider/model capabilities and test the serialized provider payload; keep attachment-by-default off for Staff/Manager until case-bound authorization and evidence policy exist.
3. Run an authenticated, pinned-environment test against Colab L4 with a small labeled image set (positive image-grounding prompts, text-only control, malformed/oversized/unsupported inputs, tool call plus image, and request logging that proves the image part was parsed). Compare outputs to labels; do not infer capability from HTTP 200 alone.
4. Treat documents separately: either reject them clearly or implement isolated MIME-validated storage plus a controlled PDF/text extraction/OCR projection. Never pass unscanned arbitrary files or raw base64 to tools, logs, caches or checkpoints.
5. Only after evidence controls, retention, access authorization, endpoint authentication, request limits and privacy approval are frozen may an explicit safe image projection be considered for model context.

**Owner direction/request:** include image/file handling in the Phase R1 plan and prepare a production-capable Colab inference path for real customer data when enabled, using compact, case-bound context. The current serving limit is 8,192 tokens; evaluate 16,384 only if needed and measured safe on L4. **Still open:** exact context fields, data minimization, which validated media projections may enter the model, allowed MIME/types, size/count limits, scanning, access, retention/deletion, OCR/PDF policy and Colab endpoint privacy/authentication. The current endpoint is not approved for real data; no runtime test or data transfer was run in this W0 pass.

## 9. Owner confirmations requested (answered in §10)

The smallest confirmations to close policy (not mechanics) are:

1. **OD-01:** accept Manager same-tenant account administration + separate `opsadmin` Ops Console (recommended), or make `opsadmin` the only caller of every `/api/admin/*` route.
2. **OD-03:** confirm the exact timer-start event, eligible state, and whether inactivity remains an inactive marker or transitions the case to `resolved`; the owner has already limited 1.5 minutes to evaluation/specialized test states and prohibited it in production. Do not auto-close staff-owned work because of overload.
3. **OD-04:** approve/revise the authority matrix; decide Staff acting-for-customer conditions and whether Staff may authorize a refund or only return approval.
4. **OD-05:** accept/revise the compatibility-facade recommendation.
5. **OD-06:** accept/revise the proposed separate case / return / refund vocabularies.
6. **OD-07:** confirm migration guardrails; numeric versions/runbook details can be proposed after source/schema inventory.
7. **OD-08:** the target is production-capable inference with real customer data when enabled, using compact case-bound context. Specify exact context fields and eligible media projections; evaluate current 8,192-token serving limit versus 16,384 only with L4 evidence; review endpoint/security/privacy controls before any live transfer.

Until the §10 open mechanics are specified and a fresh readiness review explicitly clears `BLOCKED`, continue W0 documentation/reconciliation only. See [current readiness](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md), [contract freeze](W0_CONTRACT_FREEZE_AND_GAP_REGISTER_2026-10-29.md), [role inventory](W0_ROLE_INVENTORY_2026-10-29.md), and [canonical design](README.md).

## 10. Final owner decisions (2026-10-31)

Owner answers to §9. These supersede the proposal/open status above for the listed items. They are policy decisions; they do **not** clear `BLOCKED` or authorize W1–W6.

| Item | Decision | Still open (mechanics only) |
|---|---|---|
| OD-01 | **Decided:** Manager keeps same-tenant business account administration on app `/api/admin/*`, tenant derived from the server session. `opsadmin` stays the separate read-only Ops Console. `platform_admin` retires gradually; its cross-tenant grants move to no one. | Route-by-route inventory of `/api/admin/*` and retirement migration (OD-07). |
| OD-03 | **Decided:** the 3-minute timer starts when the bot sends a message that awaits the customer's reply, and applies only to cases not held by Staff/Manager (`in_progress` work is never timed out). On expiry the case becomes `resolved` with reason `inactivity`. After `resolved`, the customer sees a **Continue** control; pressing it resumes the **same `case_id`** in `waiting` with a new handoff episode (revised 2026-10-31; see §11.2). Customer-reply reset, production ban on the 1.5-minute flag and no overload-driven closure remain as recorded. | Concurrency/idempotency of timer vs. reply (§11.2), completion-feedback timer anchor, feedback schema/privacy/retention. |
| OD-04 | **Decided (revised 2026-10-31):** every cancel/return request is reviewed by a human before it changes an order. Flow: the customer (through the agent) creates a cancel or return request for their own order, with a mandatory reason and optional evidence → the agent fills the right-side detail panel (order, items, reason, cancel-vs-return, evidence, advisory AI summary) and the request becomes `pending_review` → Staff or Manager checks and confirms the details, then approves or rejects. Customer confirmation **submits** the request; it no longer cancels the order directly (behavior change: today `/api/cancellation-proposals/{id}/confirm` sets `orders.status='cancelled'` at once; under the OD-05 facade it will create a `pending_review` request, so UI copy, tests and live-smoke contracts change in W3). Staff may also raise a cancellation request in the delivery-failure case (shipper repeatedly cannot reach the customer); a Manager decides it. **Refund:** Staff may only submit a refund request; a Manager decides; money movement is a separate payment outcome. Manager keeps the audited direct order-status path. Complaints, warranty and other after-sales work are case work, not order-action requests. | Delivery-failure evidence (attempt count/carrier status); field-level JSONL schema (proposal in §11.4). |
| OD-05 | **Decided:** keep `/api/cancellation-proposals*` as a compatibility facade over a shared order-action service; add separate return routes; deprecate only after caller inventory and an approved window. | Caller inventory. |
| OD-06 | **Decided:** separate vocabularies as proposed in §7 — case `waiting/in_progress/resolved`; return `requested → under_review → approved/rejected → received → inspected → completed`; refund `not_applicable/pending/refunded/failed`. | Which system is authoritative for `refunded`; inspection outcomes. |
| OD-07 | **Decided:** migration guardrails in §7 (versioned migration, aggregate preflight, backup/restore evidence, tested rollback or compensating migration, session invalidation after commit, append-only audit). | Tool, version numbers, runbook — written during W1. |
| OD-08 | **Decided (2026-10-31):** production inference runs on the Colab GPU for now, including images and files, through the protected path in §11.6; migrate later to a managed cloud GPU (for example AWS) when budget allows, by configuration change only. The current unprotected ngrok endpoint stays unapproved for real data until the §11.6 gates pass. | Exact vLLM flags for the pinned version, image token cost on L4, tunnel product choice (§11.6). |
| Scheduling | **Decided:** `W0 → W1 → W2 → W3 → W4 → W5 → W6`, strictly sequential. | — |
| Internal AI | **Decided:** follow-up history is private per principal within an authorized case, partition `(tenant_id, principal_id, case_id)`; internal-assist profiles bypass `ToolCache`/`SemanticCache` in the first slice. | Retention of internal history. |

Remaining policy gate before the readiness review: only the items in the "Still open" column. They are mechanics, not new policy questions; accepted mechanics for each are in [§11](#11-accepted-mechanics-2026-10-31).

## 11. Accepted mechanics (2026-10-31)

These are the "still open" mechanics from §10, written as concrete proposals. Source facts were checked statically at `bbfd11d`; nothing was run. **Owner answers (2026-10-31):** 11.1, 11.3 and 11.5 accepted; 11.2 revised and accepted (resume the same case, typed message = Continue, new linked case only after retention ends); 11.4 sink option A selected; 11.6 revised (Colab is the current production inference host). Recording these mechanics does not clear `BLOCKED` or authorize `W2–W6`; on 2026-10-31 the owner separately granted a bounded **W1-only** execution authorization (W0 closeout + W1 identity/RBAC/backend authorization and isolated tests only).

### 11.1 `/api/admin/*` route inventory (OD-01)

Current routes in [`retailops/http/routes.py`](../../retailops/http/routes.py) (handlers around lines 180–225 and 340–360) with scope rules in [`retailops/identity/store.py`](../../retailops/identity/store.py) (around lines 1074–1100 and 1312):

| Route | Purpose | Current scope at `bbfd11d` | Proposed R1 rule |
|---|---|---|---|
| `GET /api/admin/accounts` (`q`, `limit` 1–200, `tenant_id`) | List memberships + quota | `manager` and `platform_admin` only; Manager limited to own tenant, mismatch audited as denied | Manager only; tenant always from session, `tenant_id` param ignored or must equal session tenant |
| `GET /api/admin/accounts/{membership_id}` | One account detail | Same | Same; foreign-tenant ID → 403/404, audited |
| `GET /api/admin/audit-log` (`membership_id`, `limit`, `tenant_id`) | Read admin audit | Same | Same; read-only |
| `POST /api/admin/accounts/{id}/suspend` | Suspend membership | Same; Manager cannot target `platform_admin` | Same tenant only; deny self-suspend and suspending the last active Manager of a tenant (new guard; not verified in current source) |
| `POST /api/admin/accounts/{id}/reactivate` | Reactivate | Same | Same tenant only |
| `POST /api/admin/accounts/{id}/revoke-sessions` | Force logout | Same | Same tenant only |
| `POST /api/admin/accounts/{id}/quota` | Quota override | Same | Same tenant only |
| `POST /api/admin/audit-log*` | — | 405 append-only | Unchanged |

There is no role-change route; R1 adds none. After `platform_admin` retirement the cross-tenant branch is deleted, not reassigned. `opsadmin` never calls these routes; it stays behind Caddy Basic Auth on the separate read-only console.

### 11.2 Timer vs. concurrent customer message, and resume (OD-03, revised)

Persist the timer on the case row, not in memory: `awaiting_customer_since`, `inactivity_deadline`, `holder` and a `version` integer.

1. The bot sends a message that awaits the customer → in one transaction set `awaiting_customer_since=now`, `inactivity_deadline=now+3 min`, `version+1`. Only for cases with no `holder`.
2. The timer worker resolves with a conditional update: `UPDATE cases SET status='resolved', resolved_reason='inactivity', version=version+1 WHERE case_id=? AND version=? AND status<>'resolved' AND holder IS NULL AND inactivity_deadline<=now()`. Zero rows updated → do nothing.
3. A customer message locks the case row (`SELECT … FOR UPDATE`) in the same transaction that stores the message. If the case is still open → clear the deadline, `version+1`; the case stays open. **Message first → case stays open.**
4. If the case is already `resolved`, the customer UI shows a **Continue** (Tiếp tục) control instead of silently creating work. Pressing it calls a resume endpoint that, in one transaction, sets the **same `case_id`** back to `waiting`, opens a new `handoff_id` episode when human help is needed, sets `resumed_at`, `resume_count+1`, `version+1`, and appends an audit row with reason `customer_resumed`. The resolved history and earlier feedback stay attached to the case.
5. Staff claim also bumps `version` and sets `holder`, so a claim cancels any pending timeout. Repeated or late timer jobs are no-ops because the version no longer matches.

**Resource release and lazy resume (owner direction 2026-10-31):** a resolved case must hold no runtime resources; only durable rows remain. Continue loads the chat back on demand and allocates resources only for the active turn.

| On `resolved` — release | Kept durably |
|---|---|
| Customer human-mode polling (`humanPollingTimer`, `web/app.js` around line 333) is stopped; the case leaves the Staff Desk waiting/in-progress lists, so Desk polling no longer carries it | Transcript, case row, handoff episodes, feedback, audit, order-action requests |
| `holder` and claim cleared; timer columns cleared | Evidence files and metadata (own 90-day retention, §11.6) |
| Workflow run lease released; the checkpoint is kept only until its existing expiry and is never needed for resume | `version`, `resolved_reason`, `resolved_at` |
| Internal-assist context and any in-memory prompt/context projection for the case dropped; no per-case cache entries kept | |

The per-membership `Application` object is cached in an LRU (`retailops/identity/persistent.py` around lines 235–250) and evicted by capacity; it belongs to the session, not to the case, so resolve does not need to touch it.

On **Continue** (or the first message after resolve, if proposal (a) is accepted): load the transcript tail from the DB as a bounded window (the same caps as the AI projection: ≤20 messages, ≤12,000 characters), rebuild the compact case context, start a new workflow run with a fresh lease, restart polling only if a human episode is opened, and restart the 3-minute timer only when the bot next awaits the customer. Nothing is preloaded before the customer acts.

Tests: after resolve, no active polling timer, no lease and no holder for the case; Continue rebuilds context from the DB only (works after a process restart and after `Application` eviction); a resumed chat does not include another case's context.

**Owner decisions (2026-10-31):** (a) a message typed after `resolved` without pressing Continue is treated as pressing Continue, so the customer is never blocked; (b) resume is allowed only while the conversation is retained; after that, a new `case_id` is created and linked through `previous_case_id`.

Tests: reply at T−1 s, reply racing the worker, duplicate timer delivery, claim racing the timer, Continue racing a second Continue (idempotent), Continue after retention ends, Continue after a process restart (resources rebuilt from the DB only).

### 11.3 Timer after feedback (OD-03)

- When the customer signals completion, the bot asks "anything else?". That message is a normal awaiting message and starts the normal 3-minute timer.
- If the customer says no, the bot shows the Like/Dislike or 1–5-star controls and the case gets `feedback_prompted_at`. From that moment a single **5-minute completion timer** replaces the 3-minute timer; the two never run together.
- Submitting feedback does not resolve early and does not reset the timer. It only stores the feedback event, so the customer can still type during the remaining window.
- A new customer message before expiry clears the completion timer and the case continues (back to the normal flow). On expiry the case becomes `resolved` with `resolved_reason='completed'`.
- No feedback is fine: the case still resolves with `completed`, and the absence of feedback is recorded as no event (never as a negative rating).

### 11.4 JSONL envelope and outbox (OD-04/OD-06)

Database state is the source of truth. One transaction writes the decision, the order/return/refund state change, the append-only audit row and one `integration_outbox` row; JSONL is produced only from committed outbox rows.

Proposed `integration_outbox` table: `event_id` (UUID, primary key), `tenant_id`, `event_type`, `payload_json`, `created_at`, `status` (`pending`/`published`/`dead`), `attempts`, `next_attempt_at`, `last_error`, `published_at`.

Worker: select `pending` rows due now with `FOR UPDATE SKIP LOCKED`, append one JSON line per event to the sink, then mark `published`. On failure, back off (for example 1 min, 5 min, 30 min, 2 h, 12 h). After 8 attempts mark `dead` and show it to an operator. Delivery is at-least-once, so consumers deduplicate on `event_id`.

Envelope, one object per line:

| Field | Required | Note |
|---|---|---|
| `schema` | yes | constant `retailops.order_action` |
| `schema_version` | yes | starts at `1`; additive changes only within a major version |
| `event_id`, `event_type`, `occurred_at` | yes | `occurred_at` is UTC ISO-8601 |
| `tenant_id` | yes | |
| `actor.principal_id`, `actor.role` | yes | from the server session; `system` for timer/worker |
| `case_id`, `order_action_request_id`, `order_id` | when applicable | |
| `before`, `after` | yes for state changes | status and version only |
| `reason_code`, `reason_text` | when applicable | `reason_text` ≤500 characters, untrusted |
| `evidence_refs` | optional | opaque evidence IDs plus SHA-256, never bytes or URLs |
| `correlation_id`, `idempotency_key`, `source` | yes | `source` is `app`, `worker` or `import` |

Event types for v1: `cancel_requested`, `return_requested`, `request_approved`, `request_rejected`, `refund_requested`, `refund_decided`, `order_status_changed`, `case_feedback_recorded`.

No names, phone numbers, addresses or free-text chat in the envelope; customers appear only as an opaque `customer_ref`. Inbound JSONL uses the same envelope: validate it against the schema, allowlist the event types, reject unknown or invalid transitions, deduplicate on `event_id`, and audit every import.

**Sink (owner decision 2026-10-31):** option A for v1 — a daily-rotated JSONL file (`<tenant>/<YYYY-MM-DD>.jsonl`) in protected storage outside the web root, append-only, one SHA-256 manifest per closed day. Option B (queue, webhook or object-storage events) is a later upgrade; it reuses the same envelope and outbox, so only the worker's sink adapter changes.

### 11.5 Migration runbook (OD-07)

Current mechanism: a `retailops_schema(component, version)` marker. PostgreSQL is at identity v4 and business v4 ([`retailops/storage/postgres.py`](../../retailops/storage/postgres.py)); SQLite migrates inside one transaction ([`retailops/schema.py`](../../retailops/schema.py)). Proposed R1 versions: identity v5 (role constraint without `viewer`/`platform_admin` for new rows, a disabled-state column, `auth_version` bump) and business v5 (`cases`, `handoff_episodes`, `order_action_requests`, `order_action_decisions`, `integration_outbox`, `case_feedback_events`).

1. **Freeze:** keep deploy disabled and record the exact candidate SHA.
2. **Preflight (read-only, aggregate counts only):** memberships per role per tenant, Viewer and customer ID sharing, active sessions per role, pending handoffs, open cancellation proposals.
3. **Backup:** run `pg_dump`, restore it into a scratch database, and compare row counts before going further.
4. **Forward migration:** one transaction per component; idempotent `IF NOT EXISTS` statements; the version marker is updated in the same transaction.
5. **Data steps:** disable Viewer/`platform_admin` memberships (never delete in this step); bump `auth_version` to invalidate their sessions after commit; backfill open `human_handoff` rows into `cases`/`handoff_episodes`; map open cancellation proposals to `pending_review` requests.
6. **Postcheck invariants:** no active Viewer/`platform_admin`; every open handoff has exactly one case; no orphaned feedback; counts match the preflight.
7. **Rollback:** before any new business writes, restore from the backup. After new writes, use a compensating migration instead of restoring stale data.
8. **Execution rule:** every step checks its exit code and stops on failure (`scripts/update_ec2.py` currently uses `check=False` and must not be the vehicle). Rehearse once on a staging copy and record the timings.

### 11.6 Evidence and production inference on Colab (OD-08, revised)

**Evidence intake (accepted):**
- Allowed types: JPEG, PNG, WebP and PDF.
- Limits: ≤5 files per request, ≤10 MB per image, ≤20 MB and ≤20 pages per PDF.
- Validation: check magic bytes; strip EXIF/GPS; run a malware scan.
- Storage: outside the web root under a random `evidence_id`, with an authorization check on every download.
- Retention: delete files 90 days after the request is closed; keep the hash and metadata.

**Owner decision:** production inference uses the Colab GPU for now. Later, when budget allows, it moves to a managed cloud GPU (for example AWS, or another provider). Support for this exact Gemma 4 fine-tune on the chosen service must be verified at that point.

**How images and files reach Colab**

The EC2 app is the only caller. Colab never stores files.

- **Images.** The app validates the file and re-encodes it (proposal: long edge ≤1024 px). It sends the image as a base64 data URL in an OpenAI-style `image_url` content part inside the normal chat request to vLLM. No separate upload step.
- **PDF with a text layer.** The app extracts the text itself. It sends only a bounded excerpt with page numbers.
- **Scanned PDF.** The app renders a few pages (proposal: ≤3) to images and sends them as images.
- **Request contents.** Each request carries compact, case-bound context only: no customer names, phone numbers or addresses, and EXIF removed.
- **Raw data stays out of storage.** Raw bytes are never written to tools, logs, caches or checkpoints.

**Changes needed in a later authorized slice (W4)**
- **App adapter.** Remove the exact model ID from `TEXT_ONLY_MODELS` ([`retailops_providers.py`](../../retailops_providers.py), around line 65), or replace it with explicit capability config. The existing `image_url` serialization in `translate()` (around line 202) is then reused.
- **Colab launcher** ([`notebooks/colab_vllm_l4.py`](../../notebooks/colab_vllm_l4.py)):
  - add `--api-key` read from Colab secrets;
  - set a per-request image limit;
  - disable request logging;
  - pin `vllm`, which is currently `vllm>=0.6.0`;
  - pin the chat template, which is currently fetched from vLLM `main`.

  Exact flag names must be checked against the pinned vLLM version.
- **Context budget.** Images consume tokens inside the 8,192-token limit. Measure the per-image cost on L4 before fixing the cap.

**Protected endpoint before real customer data**
- **Authentication, two layers.** The vLLM API key is the first layer. The second is the tunnel's own access control: either an ngrok traffic policy (basic auth or an IP allowlist for the EC2 egress IP, if the plan supports it), or Cloudflare Tunnel with an Access service token. A bare public ngrok URL is not acceptable.
- **Secrets.** The endpoint URL and key live in app secrets and are rotated every Colab session.
- **Transport.** TLS only.
- **Health checking.** The app health-checks the endpoint. If it fails, image or file analysis returns "không phân tích được, chuyển nhân viên" and the case continues with humans. Order-action submission never depends on the model.

**Risk the owner accepts by choosing Colab for production**
- Sessions disconnect and the tunnel URL changes, so availability is best-effort.
- Customer images and text are processed on Colab infrastructure under Colab's terms.

Mitigations: data minimization, no storage on Colab, the access layers above and the human fallback. Revisit the choice when moving to a managed GPU.

## 12. W1 policy decisions (2026-10-31)

Đây là câu trả lời của owner cho hai câu hỏi chính sách W1 (mục 3 của [W1 remediation handoff](W1_REMEDIATION_HANDOFF_2026-10-31.md)). Đây là quyết định chính sách: không sửa §10/§11, và không cho phép `W2–W6`, migration trên DB thật, deploy, commit hay push.

| Hạng mục | Quyết định của owner | Hệ quả và giới hạn |
|---|---|---|
| `W1-ID-01` — nguồn cấp membership/role cho tài khoản mới | Giữ **allowlist trong biến môi trường** (`STAFF_EMAILS`/`MANAGER_EMAILS`, chỉ áp dụng cho email Google đã xác minh) làm kênh **chuyển tiếp**. `DEFAULT_ROLE` chỉ được là `customer`, như code đã thực thi; email không có trong allowlist nhận `customer`. Muốn thêm staff/manager thì sửa biến môi trường trên server rồi khởi động lại app. | Chưa đặt ngày kết thúc: kênh này kết thúc khi owner chọn kênh khác. Việc sửa allowlist không có audit trong app; chỉ truy vết được qua việc truy cập server (AWS SSM). Không cần code mới trong W1. |
| `W1-ID-02` — kênh đổi role cho membership hiện hữu | Chỉ dùng lệnh CLI `identity set-role` chạy trên server qua **AWS SSM**. Người thực hiện được định danh bằng IAM principal trong log của SSM/CloudTrail; audit trong app vẫn ghi `operator_cli`. Google login không bao giờ đổi role của membership hiện hữu; `/api/admin/*` không có route đổi role (§11.1); OpsConsole vẫn chỉ đọc. | Điều kiện trước khi dùng log SSM/CloudTrail làm bằng chứng audit: owner xác nhận đã bật log phiên SSM và CloudTrail (chưa được kiểm chứng trong tài liệu này). Không cần code mới trong W1. |

**Hướng tương lai (ghi nhận, chưa phải quyết định để làm):**

- Lệnh CLI "mời theo email" chạy qua SSM, thay cho việc sửa biến môi trường.
- Giao diện OpsConsole cho opsadmin: dán email, chọn role. Cần owner chính thức bỏ ràng buộc "OpsConsole chỉ đọc" ở một đợt sau. Lưu ý opsadmin dùng chung một tài khoản Basic Auth nên giao diện không định danh được người thực hiện.
- Import/provisioning từ hệ thống ngoài.

## 13. W2 owner decisions (2026-11-01)

Owner chốt trước khi phát hành W2. Các quyết định dưới đây **thay thế** những chỗ §10/§11 nói khác; phần còn lại của §10/§11 giữ nguyên. Không cho phép `W3–W6`, deploy hay migration DB thật nếu chưa có phê duyệt riêng.

| ID | Quyết định | Thay thế |
|---|---|---|
| W2-D1 | **Mọi hội thoại đều có một `case_id`.** Timer và phản hồi hài lòng áp dụng cả cho ca chỉ có bot. Staff Desk chỉ hiện case có handoff episode đang mở (Hàng chờ) hoặc có `holder` (Đang xử lý); nhóm Đã xử lý hiện ca đã đóng trong thời hạn lưu. Chat thuần với bot không vào hàng đợi. | Làm rõ §10 OD-03 |
| W2-D2 | **Staff và Manager** được xem **chỉ đọc** transcript của ca đã đóng, cùng tenant, trong thời hạn lưu, có ghi audit. Không được trả lời hay đóng lại ca đã đóng. | Làm rõ README ("resolved read-only only if separately approved") |
| W2-D3 | **Business v5 chỉ gồm bảng của W2**: `cases`, `handoff_episodes`, `case_feedback_events`. `order_action_requests`, `order_action_decisions`, `integration_outbox` chuyển sang **business v6 ở W3**. | §11.5 (gộp 6 bảng vào v5) |
| W2-D4 | Timer chạy bằng **luồng nền trong process `web`** (quét định kỳ khoảng 15 giây), đóng ca bằng cập nhật có điều kiện theo `version`, an toàn khi chạy trùng. Không thêm container. | Làm rõ §11.2 |
| W2-D5 | **Timer khách không trả lời:** đồng hồ chỉ bắt đầu khi bot đã gửi xong câu trả lời và đang chờ khách (thời gian bot xử lý không tính). Sau **5 phút** bot gửi **một** tin nhắc cố định; thêm **3 phút** sau tin nhắc vẫn không trả lời thì đóng ca (`resolved`, lý do `inactivity`). Khách gửi tin bất kỳ lúc nào thì hủy cả hai mốc. Không áp dụng khi ca có `holder` hoặc đang chờ nhân viên. Timer 5 phút sau khi mời đánh giá (§11.3) giữ nguyên và không chạy song song. Production không cho rút ngắn; giá trị ngắn chỉ dùng cho môi trường đánh giá. | §10 OD-03 và §11.2 bước 1–2 (3 phút rồi đóng ngay, không nhắc) |
| W2-D6 | Nút gửi đổi thành **ô vuông đỏ, bấm để dừng** lượt bot đang trả lời: làm ở **W5** (cần backend hỗ trợ hủy). | Mới |
| W2-D7 | Retire `scripts/update_ec2.py` và cập nhật notebook Colab trong repo (không hướng dẫn chạy script này, chỉ sửa `RETAILOPS_API_ENDPOINT` và tạo lại `web`; hỗ trợ domain ngrok tĩnh qua secret `NGROK_DOMAIN`): làm như **mục 0 của W2**. | Mới |

## 14. W3 owner decisions (2026-11-02)

Owner chốt trước khi phát hành W3. Các quyết định dưới đây **thay thế** những chỗ §10/§11 nói khác; phần còn lại giữ nguyên. W3-D1 đến W3-D4 do owner chọn trực tiếp. W3-D5 đến W3-D11 là mặc định do review đề xuất, owner chấp nhận khi áp bản ghi này. Không cho phép `W4–W6`, deploy hay migration DB thật nếu chưa có phê duyệt riêng.

| ID | Quyết định | Thay thế |
|---|---|---|
| W3-D1 | **Ba loại yêu cầu đơn hàng:** hủy (`cancel`), trả (`return`) và **đổi** (`exchange`, kiểu `size` hoặc `one_to_one`). Đổi hàng đi cùng luồng duyệt với trả hàng. Hai nút soạn sẵn "Xác nhận tiếp nhận Đổi 1-1/Đổi Size" bị bỏ. | Mở rộng §10 OD-04 (chỉ hủy/trả) |
| W3-D2 | **Vòng đời trả/đổi đủ bước, chuyển tay:** `requested → under_review → approved/rejected → received → inspected → completed`. Staff/Manager bấm "Đã nhận hàng", "Đã kiểm tra" (kết quả `refund`, `exchange` hoặc `no_action`) và "Hoàn tất". Hủy đơn dừng ở `approved/rejected`; duyệt hủy đổi `orders.status` thành `cancelled` trong cùng transaction. Không nối hệ thống kho hay vận chuyển. Trạng thái `pending_review` trong OD-04 chính là `requested`. | Làm rõ §10 OD-04/OD-06 |
| W3-D3 | **Hoàn tiền ghi tay:** Staff gửi yêu cầu hoàn tiền; Manager duyệt hoặc từ chối; sau khi chuyển tiền ngoài hệ thống, Manager ghi kết quả `refunded` hoặc `failed`. Mọi bước có audit. Không nối cổng thanh toán. | Đóng phần "which system is authoritative for `refunded`" của OD-06 |
| W3-D4 | **Bằng chứng trong W3 chỉ nhận ảnh:** JPEG/PNG/WebP, tối đa 5 ảnh mỗi yêu cầu, ≤10 MB mỗi ảnh; kiểm tra magic bytes; app mã hóa lại ảnh và xóa EXIF/GPS; lưu ngoài web root theo `evidence_id` ngẫu nhiên; kiểm quyền mỗi lần xem; xóa tệp 90 ngày sau khi yêu cầu đóng, giữ hash và metadata. **PDF hoãn** tới khi có máy quét mã độc. | Thu hẹp §11.6 cho W3 |
| W3-D5 | **Yêu cầu vào Hàng chờ qua ca:** tạo yêu cầu thì mở một handoff episode trên ca (dùng hàm handoff của W2), nên ca vào Hàng chờ. Người duyệt theo quy tắc W2: ca có `holder` thì chỉ người giữ hoặc Manager. Chỉ Manager được quyết định yêu cầu hủy do giao thất bại và yêu cầu hoàn tiền. | Mới |
| W3-D6 | **Điều kiện tạo yêu cầu:** hủy chỉ khi đơn `pending`; trả/đổi chỉ khi đơn `delivered`; mỗi đơn tối đa một yêu cầu đang mở. Server **không** chặn theo hạn đổi trả; panel hiển thị số ngày kể từ khi giao để nhân viên tự kiểm theo chính sách. Thêm cột `orders.delivered_at`, ghi từ v6 trở đi; đơn cũ để trống và panel ghi "chưa có ngày giao". | Mới |
| W3-D7 | **JSONL chỉ chiều ra trong W3** (outbox → file theo §11.4). Nhập JSONL từ hệ thống ngoài để sau. Thêm loại sự kiện `exchange_requested` và `request_status_changed` (bổ sung, không phá `schema_version` 1). `case_feedback_recorded` cũng xuất qua outbox. | Bổ sung §11.4 |
| W3-D8 | **Hủy do giao thất bại:** Staff nhập số lần giao thất bại (≥1) và ghi chú; không nối hãng vận chuyển; Manager quyết định. | Đóng phần "delivery-failure evidence" của OD-04 |
| W3-D9 | **Không backfill đề xuất hủy cũ:** dòng `proposals` đang `pending` là bản nháp khách chưa xác nhận; lớp tương thích `/api/cancellation-proposals*` xử lý tiếp khi khách xác nhận. | §11.5 bước 5 ("map open cancellation proposals to `pending_review`") |
| W3-D10 | **Đưa một phần UI Staff Desk lên W3:** gom thao tác ca (nhận/trả ca, hoàn tất, panel yêu cầu đơn hàng) vào **một module "Thao tác ca" thu gọn/mở rộng được**, sửa bố cục header và kiểu nút bị vỡ, sửa nút "Gửi phản hồi trực tiếp" không phản hồi. Phần thiết kế lại còn lại vẫn ở W5. | Kéo một phần W5 lên W3 |
| W3-D11 | **Báo khách khi có quyết định:** mỗi lần yêu cầu đổi trạng thái do người duyệt, hệ thống thêm một tin cố định vào hội thoại của ca. | Mới |

## 15. W3.1 owner decisions (2026-11-02)

Owner chốt sau khi thử W3 trên production. Các quyết định dưới đây **bổ sung** §10/§14; phần còn lại giữ nguyên. W3.1 **không đổi schema DB**. Không cho phép `W4–W6`.

| ID | Quyết định | Thay thế |
|---|---|---|
| W3.1-D1 | **Nhân viên tạo yêu cầu thay khách khi khách đồng ý qua chat.** Nhân viên đề xuất trong chat (hủy, trả, đổi size, đổi 1-1); khách trả lời đồng ý bằng tin nhắn bất kỳ (ví dụ "ok", "được"); **khách chỉ xác nhận bằng tin nhắn, không có nút hay form xác nhận phía khách**; nhân viên trỏ tới tin nhắn đồng ý đó (mặc định chọn sẵn tin mới nhất của khách) rồi bấm tạo yêu cầu. Khách vẫn là người yêu cầu (`raised_by_role='customer'`); nhân viên là người thao tác; mã tin nhắn đồng ý được ghi vào audit và dòng quyết định `submit`. Sau đó nhân viên duyệt và xử lý như yêu cầu khách tự gửi. Hủy do giao thất bại và hoàn tiền giữ quy tắc chỉ Manager. | Bổ sung §10 OD-04 (chỉ khách tự gửi) |
| W3.1-D2 | **Ca có người giữ mà khách im lặng:** sau **5 phút** kể từ tin cuối của nhân viên mà khách không trả lời, Staff Desk gắn nhãn "Khách không phản hồi · N phút" ở danh sách Đang xử lý và ở đầu ca để nhân viên chủ động đóng. Không gửi tin cho khách, **không tự đóng ca có người giữ**. Production không cho rút ngắn. | Bổ sung W2-D5 |
| W3.1-D3 | **Lưu các mốc của ca vào hội thoại:** yêu cầu gặp nhân viên, nhân viên nhận ca, trả ca, đóng ca. Khách và nhân viên tải lại trang vẫn thấy. | Mới |
| W3.1-D4 | **Bỏ toàn bộ `style="..."` trong HTML** (cả trong `web/index.html` lẫn chuỗi HTML do JS tạo), vì CSP production (`style-src 'self'`) chặn chúng. | Mới |
| W3.1-D5 | **Module "Thao tác ca":** form hủy do giao thất bại chuyển vào mục "Thao tác khác", mặc định thu gọn, chỉ hiện khi khách có đơn `pending`; khung có chiều cao tối đa và tự cuộn để transcript luôn còn chỗ. | Bổ sung W3-D10 |
| W3.1-D6 | **Staff Desk dễ nhìn hơn:** cửa sổ mặc định lớn hơn; có nút **Phóng to / Thu nhỏ** để dùng toàn màn hình, nhớ lựa chọn trên trình duyệt; trên màn hình rộng, module "Thao tác ca" thành cột bên phải cạnh transcript thay vì nằm chồng phía trên. | Kéo thêm một phần W5 lên W3.1 |

## 16. W3.2 owner decisions (2026-11-02)

Owner chốt sau khi thử W3/W3.1: tác vụ yêu cầu đơn hàng phải dùng **một mô hình chung**, không set cứng từng tình huống; trợ lý AI phải bám vào mô hình đó. W3.2-D1 đến W3.2-D3 và W3.2-D9 do owner nêu trực tiếp. W3.2-D4 đến W3.2-D8 và W3.2-D10 đến W3.2-D12 là mặc định do review đề xuất, owner chấp nhận khi áp bản ghi này. Không cho phép `W5–W6`; phần AI dưới đây (agent-first cho khách) kéo một phần W4 lên W3.2; AI cho Staff/Manager theo ca và đường ảnh/tệp tới model vẫn ở W4.

| ID | Quyết định | Thay thế |
|---|---|---|
| W3.2-D1 | **Đổi hàng tổng quát:** đổi hàng là "đổi sang biến thể khác" (`other_variant`, chọn biến thể đích từ danh mục biến thể của chính sản phẩm: màu, size, kiểu…) hoặc "đổi cùng biến thể" (`same_variant`, khi hàng lỗi). Không còn kiểu `size`/`one_to_one` riêng. Đổi màu, đổi size, đổi kiểu đi chung một luồng. | W3-D1 (`exchange_kind` ∈ `size`, `one_to_one`) |
| W3.2-D2 | **Lý do dùng chung, khai báo một nơi:** một danh mục lý do duy nhất (mã, nhãn, áp dụng cho loại nào, có bắt buộc mô tả không), dùng cho cả UI khách, Staff Desk, AI và kiểm tra phía server. Thêm lý do mới chỉ sửa danh mục. | Các danh sách lý do riêng theo loại trong code |
| W3.2-D3 | **AI không được set cứng câu trả lời nghiệp vụ:** không trả câu soạn sẵn theo từ khóa cho hủy/trả/đổi; ý định của khách được đưa về mô hình chung (loại, đơn, biến thể đích, lý do); điều kiện lấy từ server (`prepare_order_action`); chính sách (phí, giao nhận, thời hạn) chỉ được nói khi có trích dẫn từ kho chính sách. Câu hỏi tiếp nối trong cùng hội thoại (ví dụ "hiện có những size nào") phải giữ ngữ cảnh đơn/sản phẩm đang bàn. | Nhánh SOP từ khóa trong `dispute_agent`; định tuyến chỉ theo tin nhắn cuối |
| W3.2-D4 | **Danh mục lý do v1:** `change_of_mind` (khách đổi ý), `fit_issue` (không vừa), `defective_item` (lỗi/hư hỏng), `wrong_item` (giao sai sản phẩm/biến thể), `not_as_described` (không giống mô tả), `ordered_by_mistake` (đặt nhầm), `no_longer_needed` (không còn cần), `delivery_failed` (chỉ nhân viên, chỉ hủy), `other` (bắt buộc mô tả). Mã cũ của W3 vẫn đọc và hiển thị được. | Mới |
| W3.2-D5 | **Tồn kho không chặn yêu cầu đổi:** server kiểm tra biến thể đích có thuộc sản phẩm và khác biến thể hiện tại; tồn kho chỉ để hiển thị (panel và AI báo còn/hết/chưa rõ), nhân viên quyết định khi duyệt. | Mới |
| W3.2-D6 | **Migration business v7** (cùng mô hình W2/W3, có diễn tập): thêm trường biến thể đích; chuyển dữ liệu cũ `size` → `other_variant` (biến thể đích để trống), `one_to_one` → `same_variant`; không xóa dòng nào. | Mới |
| W3.2-D7 | **Bỏ đề xuất kiểu cũ của AI** (`size_exchange`, `exchange_1to1`, `cancel_order` với trạng thái `pending_staff_approval`): mọi yêu cầu đơn hàng đi qua luồng W3 (khách xác nhận, hoặc nhân viên tạo theo đồng ý của khách ở W3.1). | Mới |
| W3.2-D8 | **Lỗi model phải chẩn đoán được:** khi lời gọi model thất bại, trace lưu loại lỗi, mã HTTP và đoạn đầu thông báo lỗi của provider (đã lọc bí mật) để tìm nguyên nhân 503. | Mới |
| W3.2-D9 | **Agent-first cho khách:** một vòng agent duy nhất dùng native tool-calling và thinking của model (Gemma 4 12B trên vLLM, `--tool-call-parser gemma4`), thấy đủ bộ tool của khách (chỉ đọc và `prepare_order_action`, `request_human_support`), **tự lập kế hoạch và chọn tool**. Supervisor chỉ giữ rào an toàn chạy bằng code: chủ đề cấm, khách quá bức xúc, yêu cầu gặp người thật. Prompt nêu nguyên tắc và mô tả tool, không chứa kịch bản SOP từng ca. Quyền, điều kiện đơn và việc không tự thay đổi dữ liệu vẫn do server kiểm. | Supervisor định tuyến theo từ khóa và các worker riêng có allowlist hẹp |
| W3.2-D10 | **Ngân sách và tốc độ:** tối đa 6 lượt gọi model và 10 lượt gọi tool mỗi lượt chat, có tổng thời gian tối đa; cho phép nhiều tool trong một bước; kết quả tool rút gọn để vừa giới hạn 8.192 token. UI khách hiện trạng thái tiến trình (ví dụ "đang kiểm tra đơn…", "đang kiểm tra kho…") khi agent chạy nhiều bước. | `MAX_MODEL_CALLS = 4`, `MAX_TOOL_CALLS = 8` |
| W3.2-D11 | **Chuyển đổi an toàn:** agent mới là mặc định; graph cũ giữ sau cờ `RETAILOPS_AGENT_MODE=legacy` để quay lại chỉ bằng cấu hình; câu trả lời cuối qua bước kiểm tra bằng code (không hứa chính sách khi không có trích dẫn; không nói đã thực hiện thay đổi khi server chưa làm). | Mới |
| W3.2-D12 | **Đo trước khi tin:** bộ kịch bản kiểu tau-bench cho các tác vụ của khách (tra đơn, hủy, trả, đổi biến thể, hỏi tiếp nối, ngoài lề, chính sách) chạy bằng gateway giả trên CI; cùng bộ kịch bản có script chạy với model thật trên Colab, do owner chạy, báo tỉ lệ thành công, tính hợp lệ của tool call và độ trễ p50/p95. | Mới |

**Bổ sung §16 (2026-11-03, owner):** cửa sổ ngữ cảnh phục vụ nâng từ 8.192 lên **16.384 token** (vLLM `--max-model-len 16384`), thay con số 8.192 trong W3.2-D10; ngân sách trong code đã nâng theo. `notebooks/colab_llama_server_gguf.py` vẫn `--n_ctx 8192` (không dùng trên production). Chế độ `RETAILOPS_AGENT_MODE=legacy` vẫn là graph cũ nhưng không còn các câu soạn sẵn đã bỏ theo W3.2-D7, nên không giống hệt hành vi W3.

## 17. W4 owner decisions (2026-11-03)

Owner chốt trước khi phát hành W4. Các quyết định dưới đây **bổ sung** §10 (Internal AI), §11.6 và §16; phần còn lại giữ nguyên. W4-D1 đến W4-D3 do owner chọn trực tiếp. W4-D4 đến W4-D10 là mặc định do review đề xuất, owner chấp nhận khi merge bản ghi này. W4 **không** bật dữ liệu khách thật: `RETAILOPS_DATA_MODE` giữ `persistent-demo`. Không cho phép `W5–W6`.

| ID | Quyết định | Thay thế |
|---|---|---|
| W4-D1 | **Trợ lý ca cho Staff/Manager:** trên ca đang chọn, AI tóm tắt ca, trả lời câu hỏi của nhân viên về ca và **soạn nháp** câu trả lời cho khách. Nhân viên sửa rồi tự bấm gửi; AI không tự gửi cho khách, không tạo, duyệt hay đổi trạng thái yêu cầu đơn hàng. | Làm rõ §10 Internal AI |
| W4-D2 | **Endpoint Colab hai lớp:** lớp 1 là vLLM `--api-key` (khóa trong Colab Secrets và `api.env`); lớp 2 là traffic policy của ngrok trên domain tĩnh, chặn mọi request không mang bí mật của lớp này. vLLM dùng header `Authorization: Bearer`, nên lớp 2 kiểm một header bí mật riêng (theo tinh thần "basic auth của ngrok"). Gói ngrok không hỗ trợ thì dừng và hỏi owner. | Chốt lựa chọn tunnel của §11.6 |
| W4-D3 | **Ảnh và PDF tới model, có ClamAV:** ảnh đã làm sạch được gửi tới model khi endpoint đã bảo vệ; PDF có lớp chữ thì trích đoạn kèm số trang; PDF scan thì render tối đa 3 trang thành ảnh. Thêm dịch vụ ClamAV; PDF được nhận làm bằng chứng (≤20 MB, ≤20 trang) chỉ khi quét sạch; máy quét lỗi thì từ chối PDF. | Mở phần PDF đã hoãn ở W3-D4 |
| W4-D4 | **Lịch sử trợ lý ca riêng từng người:** phân vùng `(tenant_id, principal_id, case_id)`; không hiện cho khách hay nhân viên khác; giữ trong thời hạn lưu của ca rồi xóa. | Đóng phần "retention of internal history" của §10 |
| W4-D5 | **Công cụ của trợ lý ca chỉ đọc và gói trong ca:** transcript ca, đơn và yêu cầu đơn hàng của khách trong ca, kho chính sách; bỏ qua `ToolCache`/`SemanticCache`; mỗi lần dùng ghi audit. | Làm rõ §10 |
| W4-D6 | **Không lưu ảnh/tệp thô trong lịch sử:** tệp đính kèm trong chat được làm sạch và lưu như bằng chứng (theo W3-D4 và W4-D3); hội thoại chỉ giữ `evidence_id` và hash. Migration chuyển các tệp đang nằm trong lịch sử cũ sang kho bằng chứng, hoặc thay bằng dấu đã gỡ nếu không hợp lệ. | Thực thi §11.6 "raw bytes never written" |
| W4-D7 | **Giới hạn ảnh tới model:** tối đa 3 ảnh mỗi request, cạnh dài ≤1024 px, không EXIF; năng lực ảnh khai báo bằng cấu hình (`RETAILOPS_API_VISION`), chỉ bật khi endpoint đã có hai lớp bảo vệ. Owner đo chi phí token mỗi ảnh trên L4 trước khi nâng giới hạn. | Thay danh sách `TEXT_ONLY_MODELS` |
| W4-D8 | **`customer_ref` có salt:** HMAC-SHA-256 với khóa bí mật của deploy; áp dụng cho sự kiện mới; chưa có hệ thống ngoài đọc JSONL nên không cần ánh xạ ngược. | Bổ sung §11.4 |
| W4-D9 | **Business v8 và ClamAV theo runbook:** migration có kiểm soát như v5–v7 (bảng lịch sử trợ lý ca, mở rộng loại bằng chứng, chuyển tệp đính kèm cũ). Dịch vụ ClamAV là compose mới; vì deploy thường không làm mới file compose trên EC2, runbook phải cài tay có kiểm tra. | Mới |
| W4-D10 | **Ghim runtime Colab:** ghim phiên bản `vllm` và digest chat template; tắt log request; giới hạn số ảnh mỗi request phía server. | Thực thi §11.6 |

## 18. W5 owner decisions (2026-11-05)

Owner chốt trước khi phát hành W5. Các quyết định dưới đây **bổ sung** §10–§17; phần còn lại giữ nguyên. W5-D1 đến W5-D4 do owner chọn trực tiếp. W5-D5 đến W5-D9 là mặc định do review đề xuất, owner chấp nhận khi merge bản ghi này. W5 không có migration và không bật dữ liệu khách thật. Không cho phép `W6`.

| ID | Quyết định | Thay thế |
|---|---|---|
| W5-D1 | **Manager Console thêm hàng đợi yêu cầu đơn hàng:** tab liệt kê mọi yêu cầu hủy/trả/đổi của cửa hàng theo trạng thái, nổi bật yêu cầu hoàn tiền đang chờ Manager quyết; bấm một dòng thì mở đúng ca trong Staff Desk. Thao tác duyệt vẫn ở panel của ca, không nhân đôi nút. Tổng quan ca và KPI R1 không thuộc W5. | Chốt phạm vi "Manager Console" của W5 |
| W5-D2 | **Chuyển ca thẳng:** người đang giữ ca hoặc Manager chọn một nhân viên đang hoạt động cùng cửa hàng; ca chuyển ngay, không cần người nhận bấm nhận. Ghi audit `case_transferred` và một mốc ca cho khách. Lịch sử Trợ lý ca vẫn riêng từng người. | Mới |
| W5-D3 | **Nút dừng bot:** áp dụng cho chat của khách và Trợ lý ca. Khi dừng, tin của người gửi vẫn lưu, câu trả lời dở bị bỏ, hội thoại có dòng "Bạn đã dừng câu trả lời." để lượt sau hiểu ngữ cảnh. Không cần cắt ngang request tới model đang chạy; kết quả của nó bị bỏ. | Thực thi W2-D6 |
| W5-D4 | **Tool Inspector chỉ cho Manager và chỉ đọc:** chỉ các tool đọc dữ liệu; bỏ `request_human_support`; bắt buộc chọn ca và chạy trong phạm vi khách của ca; tham số mẫu lấy từ dữ liệu của ca. | Mới |
| W5-D5 | **Nút "Tiếp tục"** cho ca đã đóng gọi endpoint `resume` đã có; giữ hành vi gửi tin mới cũng mở lại ca. | Hoàn tất UI của §11.2 |
| W5-D6 | **Đóng ca lần hai trả `ok`:** trên ca đã đóng trả `200 already_resolved`, không ghi thêm audit hay thông báo. | Mới |
| W5-D7 | **Nút Trợ lý ca bị khóa nói rõ lý do** qua `title` và dòng gợi ý dễ thấy (ví dụ "Bấm Nhận ca trước"). | Mới, từ kiểm thử W4 |
| W5-D8 | **Nút yêu cầu mẫu không dùng mã cố định** như `O-101`; dùng câu chung áp dụng cho đơn của chính khách. | Thực thi "đổi nhãn nút mẫu" từ W2 |
| W5-D9 | **Hoãn sau R1:** gộp request polling Staff Desk thành một endpoint (W4.1 đã đủ cho tải hiện tại). Các `style="..."` đã được gỡ hết ở W3.1, nên mục này rời khỏi W5. | Cập nhật lộ trình |

## 19. W6.1a owner decisions (2026-11-06)

Owner chốt hướng W6 ngày 2026-11-06 theo [W6 backlog](W6_BACKLOG_2026-11-06.md) và [tài liệu database mục B](../../khoa_luan/07_co_so_du_lieu.md). Các quyết định dưới đây áp dụng cho **W6.1a**: sàn ảo cùng hợp đồng sự kiện, chưa đụng RetailOps. W6.1a-D1 đến D4 do owner chọn trực tiếp; D5 đến D10 là mặc định đề xuất kèm handoff, owner chấp nhận khi merge bản ghi này. Không cho phép W6.1b trở đi.

| ID | Quyết định | Thay thế |
|---|---|---|
| W6.1a-D1 | **Sàn ảo là package `marketplace_sim/` trong cùng repo**, kho dữ liệu SQLite riêng, chỉ dùng thư viện chuẩn của Python. Không vào image production. RetailOps và sàn ảo không import nhau theo cả hai chiều. | Mới |
| W6.1a-D2 | **Mô hình chuẩn cộng connector:** sàn ảo chỉ phát dữ liệu theo hợp đồng sự kiện v2; việc ánh xạ sang mô hình chuẩn của RetailOps thuộc connector ở W6.1b. | Thay cho dữ liệu vận chuyển nạp cứng trong tool |
| W6.1a-D3 | **Không chạm vào tiền:** cổng thanh toán giả lập chỉ phát trạng thái thanh toán, hoàn tiền; không có số thẻ, số tài khoản, OTP. Thanh toán thật chỉ qua cổng có giấy phép của Ngân hàng Nhà nước. | Mới |
| W6.1a-D4 | **Connector trong R1:** chỉ sàn ảo và cổng thanh toán giả lập. Connector CSV và connector của nền tảng thật để sau R1. | Mới |
| W6.1a-D5 | **Hợp đồng sự kiện v2** như mục 3 của [W6.1a handoff](W6_1A_EXECUTION_HANDOFF_2026-11-06.md): một phong bì chung, 7 loại sự kiện, chữ ký HMAC-SHA256 ở header. | Bổ sung cho hợp đồng sự kiện đơn hàng của Phase 5 |
| W6.1a-D6 | **Sàn ảo phát mã trạng thái gốc**, không phát trạng thái chuẩn. Hãng mô phỏng theo GHN dùng bộ mã công khai của GHN; các hãng khác dùng bộ mã giả lập, ghi rõ là giả lập, không gán là mã thật của hãng đó. | Mới |
| W6.1a-D7 | **Cổng thanh toán giả lập dạng chung**, chưa mô phỏng định dạng riêng của cổng thật nào. Việc chọn cổng làm mẫu để sau, không chặn W6.1a. | Hoãn quyết định chọn cổng |
| W6.1a-D8 | **Hai chế độ:** tất định, với cùng seed và cấu hình thì file xuất giống hệt từng byte; và chạy dần bằng lệnh tua đồng hồ. Có 13 kịch bản có tên cho các tình huống cần đánh giá; kịch bản thứ 13, giao trễ hạn cam kết, thêm ngày 2026-11-07. | Mới |
| W6.1a-D9 | **Đã thay bằng W6.1a-D11, ngày 2026-11-07.** Bản gốc: không có số điện thoại, email, địa chỉ của khách; khu vực giao chỉ quận và tỉnh. Phần còn hiệu lực: tên khách lấy từ danh sách giả lập; số điện thoại shipper đã che; các tỉ lệ như COD, hãng, giao thất bại, mùa sale, thời gian hoàn tiền là **giả định**, ghi rõ trong file cấu hình. | Đã thay |
| W6.1a-D10 | **Nội dung bổ sung cho 3 sản phẩm** P-101, P-102, P-202 trong catalog của sàn ảo, đúng như mục 2 của handoff. Đây là dữ liệu giả lập cho F10. | Thực thi F10 |
| W6.1a-D11 | **Thông tin người nhận lưu đầy đủ trong bảng riêng, có mã hóa.** Tên, số điện thoại, địa chỉ đầy đủ của người nhận nằm ở bảng `order_recipients` riêng, các cột cá nhân được mã hóa; model AI chỉ nhận bản đã che; khách xem được của chính mình; nhân viên giữ ca xem bản đầy đủ và mỗi lần xem đều ghi nhật ký. Trong R1 chỉ dùng dữ liệu giả lập: số điện thoại dùng một tiền tố cố định khai báo trong cấu hình, địa chỉ lấy từ danh sách mẫu. Chạy với khách thật cần danh sách tuân thủ Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 được duyệt riêng. | Thay W6.1a-D9 phần dữ liệu người nhận |
| W6.1a-D12 | **Hành trình và thời hạn giao.** Đơn mang thời hạn giao đã cam kết `promised_delivery_by`; mỗi mốc hành trình mang bưu cục hoặc kho, quận, tỉnh. Thời gian còn lại và việc đã trễ hay chưa do server tính khi đọc, không lưu sẵn. | Mới |
| W6.1a-D13 | **Bồi thường giao trễ do nhân viên duyệt.** Server phát hiện đơn trễ so với thời hạn cam kết theo luật cấu hình được, không do AI quyết; tạo đề xuất bồi thường; nhân viên duyệt; RetailOps gửi yêu cầu phát voucher sang sàn qua outbox; sàn phát mã và báo lại bằng sự kiện `voucher.issued`. AI chỉ được nói với khách về voucher khi mã đã có trong dữ liệu. Mặc định: trễ quá 48 giờ so với cam kết thì đề xuất voucher 50.000 VNĐ, khớp tài liệu chính sách Mega Sale hiện có; quản lý đổi được ngưỡng và mệnh giá. | Thay câu "AI tự phát voucher" của chính sách Mega Sale, xử lý F2 |
| W6.1a-D14 | **Thông báo chủ động cho khách** trong khung chat ở các mốc: bắt đầu giao, giao thất bại, đã giao, trễ hạn cam kết, voucher đã phát. Dùng cơ chế thông báo hệ thống `sys-notice-` đã có; mỗi mốc tối đa một thông báo cho mỗi vận đơn. Phần này thuộc W6.1b. | Mới |
| W6.1a-D15 | **Notebook Colab không mang test của sàn ảo.** `scripts/build_agent_notebook.py` nhúng mọi `tests/*.py` vào `notebooks/colab_agent.ipynb`, nên 3 file `tests/test_marketplace_sim_*.py` làm notebook lệch và CI đỏ ở PR #72. Ngoại lệ duy nhất cho phạm vi mục 1 của handoff: W6.1a được sửa `scripts/build_agent_notebook.py` để bỏ các file `tests/test_marketplace_sim_*.py` khỏi danh sách nhúng; `notebooks/colab_agent.ipynb` giữ nguyên như trên `main`. Notebook không mang sàn ảo, đúng tinh thần cách ly của W6.1a-D1. Bổ sung ngày 2026-11-07 sau lượt kiểm chứng PR #72. | Bổ sung mục 1 của handoff |
| W6.1a-D16 | **Kịch bản `nghen_kho_mega_sale` dùng mốc tương đối** so với đồng hồ như mọi kịch bản khác, để bộ đánh giá dùng làm fixture; "11.11" là nhãn tình huống, không phải ngày đặt bắt buộc. Văn bản trong sự kiện không ghi ngày cụ thể của đợt sale, để không mâu thuẫn với `ordered_at`. Bổ sung ngày 2026-11-07 sau lượt kiểm chứng PR #72. | Làm rõ mục 2 của handoff |

## 20. W6.1b owner decisions (2026-11-08)

Owner chốt hướng W6.1b ngày 2026-11-08 sau [W6.1b readiness review](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-11-08-w61b-readiness-review). W6.1b-D1, D2, D3 và D13 do owner chọn trực tiếp; D4 đến D12 là mặc định đề xuất kèm [W6.1b-1 handoff](W6_1B_1_EXECUTION_HANDOFF_2026-11-08.md), owner chấp nhận khi merge bản ghi này. Chỉ cho phép W6.1b-1; W6.1b-2 cần handoff riêng.

| ID | Quyết định | Thay thế |
|---|---|---|
| W6.1b-D1 | **Chia W6.1b làm hai.** W6.1b-1: migration business v9, cổng nhận sự kiện, đơn, vận chuyển, thanh toán, hoàn tiền, tool đọc DB, dữ liệu demo. W6.1b-2: người nhận có mã hóa, bồi thường giao trễ, voucher, thông báo chủ động. **Một migration v9 duy nhất ở W6.1b-1** tạo đủ 8 bảng của mục B6; 3 bảng của W6.1b-2 để trống tới khi W6.1b-2 dùng; W6.1b-2 không có migration. | Tách dòng W6.1b trong backlog |
| W6.1b-D2 | **Dữ liệu demo production nạp lại từ sàn ảo.** Gỡ mọi dữ liệu nghiệp vụ viết trong code: đơn và khách trong `seed()`, `data/deepseek_seed_data.json`, đơn mẫu theo tài khoản, dict hành trình trong `track_shipment`, `data/mock_shipments.json`. Khi deploy, gỡ đơn demo cũ không còn yêu cầu hủy, trả, đổi nào gắn vào, rồi nhập bộ sự kiện cố định do sàn ảo sinh. | Thực thi F11 phần dữ liệu viết cứng |
| W6.1b-D3 | **Chỉ còn hợp đồng sự kiện v2.** Gỡ đường nhận v1 của Phase 5: adapter v1, `retailops/sales/simulator.py`, fixture v1 và khóa mặc định trong repo. Test Phase 5 còn giá trị viết lại theo v2. | Đóng F18; thay hợp đồng sự kiện đơn hàng của Phase 5 |
| W6.1b-D4 | **Hai đường nhận, cùng một đường ghi.** Route `POST /internal/integrations/<tenant_id>/<source_system>/events` kiểm chữ ký HMAC ở header như mục 3 W6.1a, lệch giờ tối đa 300 giây; Caddy trả `404` cho mọi đường dẫn `/internal/*`, ứng dụng từ chối request có header do proxy thêm. Lệnh operator `database import-events` nhập file JSONL do sàn ảo xuất, không kiểm chữ ký, có ghi audit, có tùy chọn dời mốc thời gian theo lúc nhập. Cả hai đi qua cùng một đường ghi. | Làm rõ "endpoint chỉ trong mạng nội bộ" ở backlog |
| W6.1b-D5 | **Connector theo cửa hàng, khóa ngoài DB.** `integration_connectors` thêm cột `merchant_id`; route phải khớp `merchant_id` của connector. `secret_ref` là tên một Compose secret dạng `retailops_connector_*`, đọc từ `/run/secrets` như secret của database; khóa là tệp thường, tối thiểu 32 byte; thiếu khóa thì connector không nhận sự kiện, server cảnh báo khi khởi động và lệnh `connector check` báo lỗi, nhưng `/healthz` không đổi. Bảng ánh xạ mã trạng thái gốc nằm trong `data/connectors/`; mã chưa có trong bảng thì từ chối sự kiện. | Bổ sung mục B3 |
| W6.1b-D6 | **Thứ tự và không đi lùi.** Sự kiện có `sequence` không lớn hơn bản đã ghi của cùng đối tượng vẫn được lưu vào `imported_events` nhưng không đổi bảng chuẩn; trạng thái chuẩn không đi lùi; `shipment_events` chỉ ghi thêm. | Mới |
| W6.1b-D7 | **Người nhận ở W6.1b-1 chỉ giữ khu vực.** Từ `order.created` chỉ lưu `ship_to_area` gồm quận và tỉnh. Tên, số điện thoại, địa chỉ chi tiết bị gỡ trước khi ghi bất cứ đâu: thay bằng `null`, giữ nguyên khóa và cấu trúc, ghi đường dẫn đã gỡ. Bằng chứng toàn vẹn là HMAC-SHA256 với khóa riêng, tính trên đúng các byte đã nhận trước mọi xử lý; không dùng SHA-256 trần vì xác nhận được bằng cách thử số điện thoại. Lưu đầy đủ có mã hóa thuộc W6.1b-2, khi đó dữ liệu demo được nạp lại. | Áp dụng W6.1a-D11 theo hai bước |
| W6.1b-D8 | **Mã đơn khách nhìn thấy là mã của sàn.** `orders.id` do RetailOps sinh; tool nhận `external_order_id` hoặc `id`, chỉ trong phạm vi đơn của khách, và trả cả hai. Một mã khớp nhiều đơn của cùng khách thì không tự chọn, agent hỏi lại khách. Agent nói bằng mã sàn; Staff Desk hiển thị cả hai. | Làm rõ mục B2 |
| W6.1b-D9 | **Điều kiện tính khi đọc.** Số ngày từ khi giao, còn hạn đổi trả, đổi size, bảo hành, dự kiến giao, đã trễ thời hạn cam kết bao nhiêu giờ, có hủy tự phục vụ được không: server tính từ cột DB và cấu hình chính sách hiện có, kèm `as_of`; không lưu sẵn, không viết cứng. Đơn `shipping` không mở được yêu cầu hủy tự phục vụ. | Thực thi mục B1 điểm 6 và F15 |
| W6.1b-D10 | **Nối hoàn tiền với yêu cầu.** Sàn không biết mã yêu cầu của RetailOps, nên `refund.updated` chỉ được nối khi đơn có đúng một yêu cầu đang chờ hoàn; khi đó `refund_status` cập nhật theo trạng thái chuẩn với người thực hiện là `system`. Không xác định được thì để trống, Staff Desk cảnh báo. Ghi tay kết quả hoàn chỉ còn cho đơn không có connector. | Làm rõ mục B3 về `refunds.request_id` |
| W6.1b-D11 | **Bộ dữ liệu demo cố định.** `data/demo_events/` gồm bộ cửa hàng 30 ngày cộng 13 kịch bản và mẫu 3 đơn cho mỗi tài khoản mới; sinh bằng CLI sàn ảo với seed cố định; `manifest.json` ghi lệnh, seed, SHA-256. Khi nhập, mốc thời gian được dời theo lúc nhập để dữ liệu không quá hạn đổi trả, bảo hành theo thời gian. | Mới |
| W6.1b-D12 | **Bộ hồi quy chuyển sang dữ liệu mới.** 41 kịch bản W3.2, W4 chạy trên dữ liệu demo mới; đổi mã đơn; kịch bản dựa vào dữ liệu viết cứng được sửa theo luật mới; không xóa kịch bản; báo cáo từng thay đổi. | Mới |
| W6.1b-D13 | **Cổng thanh toán giả lập dạng chung suốt R1.** Tích hợp hoặc mô phỏng định dạng webhook của cổng thật như VNPAY, MoMo, ZaloPay để sau khóa luận, dù các cổng này có sandbox miễn phí: không phục vụ câu hỏi nghiên cứu, kéo theo HTTPS công khai, khóa merchant và connector ngoài phạm vi W6.1a-D4. | Đóng mục "Cổng thanh toán nào làm mẫu" của backlog; giữ W6.1a-D7 |

Còn chốt khi viết handoff W6.1b-2 (**đã chốt ngày 2026-11-09 ở [§21](#21-w61b-2-owner-decisions-2026-11-09)**):

- Mã hóa người nhận bằng thư viện tầng ứng dụng hay `pgcrypto`; nơi giữ khóa mã hóa; thời hạn lưu `retention_until`.
- Thời hạn giữ backup DB. Repo chưa có backup định kỳ hay thời hạn giữ; bản mã trong backup cũ còn tới khi backup bị xóa, nên thời hạn lưu người nhận chỉ có nghĩa khi đi cùng thời hạn giữ backup. Ngày 2026-11-09 owner mới chốt riêng cho các bản backup của lượt deploy W6.1b-1: hai bản dump giữ tới hết đợt bảo vệ khóa luận, bản backup khóa tích hợp giữ lâu dài ([biên bản](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-11-09-w61b-1-production-deploy-record-and-w61b-11-hotfix)); chính sách chung vẫn còn chốt.
- Có thêm `refund.requested` không: RetailOps gửi yêu cầu hoàn tiền kèm `request_id` qua outbox, cổng báo lại `refund.updated` có `request_ref`, để nối hoàn tiền chính xác thay cho luật ở W6.1b-D10. Đây là **quyết định chính sách**, vì đổi nguyên tắc ở mục 4 W6 backlog từ chỗ RetailOps chỉ nhận lại trạng thái sang chỗ RetailOps yêu cầu, cổng thực hiện. Về kỹ thuật cần sửa hợp đồng v2 ở cả hai phía cùng lúc và sửa sàn ảo; không cần migration vì `integration_outbox` và `refunds.request_id` đã đủ.

## 21. W6.1b-2 owner decisions (2026-11-09)

Owner chốt W6.1b-2 ngày 2026-11-09 sau khi deploy W6.1b-1 và hotfix W6.1b-1.1 ([biên bản](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-11-09-w61b-1-production-deploy-record-and-w61b-11-hotfix)), đóng ba mục "Còn chốt" của §20. W6.1b-2-D1, D2, D3, D4, D7, D8 do owner chọn trực tiếp; các mục còn lại là mặc định đề xuất kèm [W6.1b-2 handoff](W6_1B_2_EXECUTION_HANDOFF_2026-11-09.md), owner chấp nhận khi merge bản ghi này. Không mở W6.2 trở đi.

| ID | Quyết định | Thay thế |
|---|---|---|
| W6.1b-2-D1 | **Làm đủ W6.1b-2**: người nhận có mã hóa, phát hiện trễ hạn và đề xuất bồi thường do nhân viên duyệt, vòng voucher, thông báo chủ động, cùng lệnh reset dữ liệu demo. Không migration: các bảng `order_recipients`, `delivery_compensations`, `vouchers`, `integration_outbox` đã có từ v9. Owner duyệt thêm một thư viện: `cryptography` (pyca), ghim phiên bản và hash trong `requirements-web.txt`. | Đóng §20 "Còn chốt" |
| W6.1b-2-D2 | **Mã hóa người nhận tầng ứng dụng, AES-256-GCM.** Khóa 32 byte riêng `retailops_recipient_key_v1`, Compose secret trong `/opt/retailops/integration-secrets/`, cùng quy tắc với khóa connector (tệp thường, `lstat`, `O_NOFOLLOW`, tối thiểu 32 byte). Mỗi trường tên, số điện thoại, địa chỉ chi tiết mã hóa riêng: nonce ngẫu nhiên 12 byte; AAD gồm tenant, `order_id`, tên trường, `key_id`; lưu dạng có tiền tố phiên bản và `key_id` để đổi khóa về sau. `phone_lookup_hmac` là HMAC-SHA256 với khóa riêng trên số điện thoại đã chuẩn hóa, không dùng SHA-256 trần. Lưu dạng thường: `phone_masked`, phường, quận, tỉnh. Không dùng `pgcrypto` (không chạy với SQLite, cần superuser tạo extension, khóa đi kèm câu SQL) và không dùng Fernet (không có AAD). | Thực thi W6.1a-D11 |
| W6.1b-2-D3 | **Ai đọc người nhận.** Model và tool của AI chỉ nhận `phone_masked` và khu vực, không bao giờ nhận bản giải mã. Khách xem được người nhận của chính đơn mình. Nhân viên đang giữ ca có gắn đơn đó, hoặc Manager, xem bản đầy đủ qua một thao tác riêng; mỗi lần xem ghi nhật ký người xem, thời điểm, đơn, lý do. Thiếu khóa người nhận thì `connector check` báo lỗi và sự kiện `order.created` có người nhận bị từ chối, không lặng lẽ bỏ trường. `imported_events` vẫn lưu thân sự kiện đã gỡ người nhận như W6.1b-D7. | Thực thi W6.1a-D11 |
| W6.1b-2-D4 | **Thời hạn giữ.** `retention_until` của người nhận: ngày giao cộng max(90 ngày, thời hạn bảo hành của sản phẩm trong đơn); đơn bị hủy: ngày hủy cộng 30 ngày; đơn chưa giao: tính khi giao xong. Lệnh operator `database purge-expired-recipients` có `--dry-run`, **chạy tay**, xóa các cột đã mã hóa và `phone_lookup_hmac`, giữ khu vực và `phone_masked`. Mọi bản dump DB có thể chứa người nhận, gồm hai bản dump của lượt W6.1b-1, và bản backup khóa người nhận: **xóa ngày 2027-01-31**, sau đợt bảo vệ khóa luận (nộp báo cáo 2026-12-19, bảo vệ 2026-12-20 đến 2026-12-23). Backup khóa digest và khóa connector giữ lâu dài vì không chứa dữ liệu cá nhân. Hủy khóa theo `key_id` là cách xóa dữ liệu cá nhân trong backup cũ; R1 chỉ có `v1`. | Đóng §20 mục thời hạn giữ backup |
| W6.1b-2-D5 | **Không thêm `refund.requested`.** Giữ W6.1b-D10, siết luật nối: chỉ nối `refund.updated` vào yêu cầu đã duyệt đang chờ hoàn; số tiền hoàn không vượt yêu cầu; thời điểm hoàn sau thời điểm duyệt; đã nối thì không nối lại. Không khớp thì để trống và Staff Desk cảnh báo. | Đóng §20 mục `refund.requested`; làm rõ W6.1b-D10 |
| W6.1b-2-D6 | **Chống trùng không dựa riêng vào khóa.** Khóa ghi theo cửa hàng (`pg_advisory_xact_lock`) đã tuần tự hóa các lệnh ghi cùng cửa hàng, nhưng outbox giao "ít nhất một lần" và lệnh có thể chạy lại sau sự cố. Vì vậy: `compensation_id` tất định từ đơn, vận đơn và `late_delivery`; duyệt hoặc từ chối là cập nhật có điều kiện `WHERE status='proposed'`, bên thua nhận 409; `event_id` của `voucher.requested` tất định và `request_id` bằng `compensation_id`; `voucher.issued` chỉ ghi khi đề xuất đang `requested`, khóa duy nhất `(source_system, external_voucher_id)` sẵn có; thông báo chủ động có mã tất định `sys-notice-<shipment_id>-<mốc>`. | Mới |
| W6.1b-2-D7 | **Phát hiện trễ hạn trong vòng quét nền** cùng chỗ với hẹn giờ ca và outbox, không phát hiện trong luồng đọc. Trễ quá 48 giờ so với `promised_delivery_by` thì đề xuất **tặng một mã voucher giảm giá 50.000 VNĐ** (`voucher_type` `amount`). Ngưỡng và mệnh giá **cố định** trong R1, là hằng số cấu hình trong code như các thời hạn đổi trả; nhân viên và Manager chỉ duyệt hoặc từ chối, không sửa mệnh giá. Bỏ phần "quản lý đổi được ngưỡng và mệnh giá" của W6.1a-D13 vì cần bảng cấu hình mới mà W6.1b-2 không có migration; để sau khóa luận. AI chỉ nói về voucher khi mã đã có trong `vouchers`. | Thay W6.1a-D13 phần "quản lý đổi được ngưỡng và mệnh giá"; owner chọn 2026-11-09 |
| W6.1b-2-D8 | **Vòng voucher trên production chạy tay.** Sàn ảo không vào image (W6.1a-D1). Lệnh operator xuất các `voucher.requested` đang chờ ra JSONL; operator chạy `python -m marketplace_sim ingest-requests` trên máy mình; nhập `voucher.issued` trở lại bằng `database import-events`. Dữ liệu mỗi vòng vài dòng, không có dữ liệu cá nhân, chép qua phiên SSM được. Runbook và kịch bản demo trọn vòng nằm trong handoff. | Mới |
| W6.1b-2-D9 | **Reset dữ liệu demo bằng gỡ toàn bộ rồi nhập lại.** Lệnh operator gỡ mọi đơn `marketplace_sim` của một cửa hàng cùng bảng con, yêu cầu hủy, trả, đổi và bằng chứng gắn với các đơn đó (gồm tệp trên đĩa, xóa sau khi giao dịch commit), các dòng `imported_events` và outbox của nguồn này; đặt `conversations.order_id` về rỗng; giữ khách, ánh xạ khách ngoài, sản phẩm, connector, khóa và mọi nhật ký audit. Không tạo và không xóa `order_purge_tombstones`: dry-run liệt kê tombstone sẽ chặn nhập lại, có thì dừng để owner quyết. Từ chối chạy khi còn ca hoặc handoff đang mở gắn với đơn sẽ gỡ. Trên production: dừng web, `pg_dump`, dry-run, owner duyệt, gỡ, nhập lại `data/demo_events/store_events.jsonl`, nạp lại mẫu 3 đơn cho mọi thành viên khách hiện có, bật web, smoke. Nhật ký audit và lịch sử chat có thể nhắc mã đơn đã gỡ; đây là hành vi đúng, không sửa. | Thực thi W6.1b-D7 phần "dữ liệu demo được nạp lại" |
| W6.1b-2-D10 | **Thông báo chủ động** theo W6.1a-D14 ở các mốc bắt đầu giao, giao thất bại, đã giao, trễ hạn cam kết, voucher đã phát; tạo khi ghi sự kiện hoặc trong vòng quét nền; mỗi mốc tối đa một thông báo cho mỗi vận đơn theo W6.1b-2-D6. | Thực thi W6.1a-D14 |

## 22. W6.2 owner decisions (2026-11-10)

Owner chốt W6.2 ngày 2026-11-10 sau khi deploy W6.1b-2 ([biên bản](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-11-10-w61b-2-production-deploy-record)), đóng các mục F1, F2, F5, F9 trong phần "Còn chờ" của [W6 backlog](W6_BACKLOG_2026-11-06.md#5-quyết-định-owner). W6.2-D2, D3 và danh sách tài liệu mới trong D3 do owner chọn trực tiếp; các mục còn lại là mặc định đề xuất kèm [W6.2 handoff](W6_2_EXECUTION_HANDOFF_2026-11-10.md), owner chấp nhận khi merge bản ghi này. Không mở W6.3 trở đi; W6.3 có handoff riêng.

| ID | Quyết định | Thay thế |
|---|---|---|
| W6.2-D1 | **Phạm vi W6.2:** C3 kiểm và nạp lại tri thức cho tenant production; F2 và F9 thay nội dung kho chính sách; F1 thứ tự rào an toàn theo W6.2-D2; F23 rào khách bức xúc bắt nhầm chữ "kiện"; F24 rào gặp nhân viên bắt nhầm câu hỏi giờ trực; F22 lệnh reset chỉ dừng vì tombstone liên quan; lệnh nạp tri thức tắt tài liệu không còn trong thư mục. Không migration, không thêm thư viện. | Thực thi dòng W6.2 của W6 backlog mục 4; thêm F22, F23, F24 |
| W6.2-D2 | **Dọa kiện, câu hỏi quyền lợi, câu hỏi luật.** (1) Khách dọa kiện, thưa kiện, đưa ra tòa: rào khách bức xúc, **chuyển nhân viên ngay**. (2) Câu hỏi về quyền lợi gắn với đơn, ví dụ "tôi có quyền trả hàng không", "shop có phải bồi thường không": **không bị rào chặn**; model trả lời theo chính sách của cửa hàng qua `search_knowledge`, có trích dẫn `[KB:...]`, gắn với điều kiện của đơn do server tính; không diễn giải luật. (3) Câu hỏi pháp lý ngoài phạm vi cửa hàng, ví dụ kiện ra tòa án nào, giới thiệu luật sư riêng, tội hình sự: **từ chối khéo**, mời khách hỏi về chính sách của shop và nói rõ có thể chuyển nhân viên. Thứ tự rào: chống prompt injection và nhóm bạo lực, tự hại chạy trước; kế đến khách bức xúc kể cả dọa kiện; rồi các chủ đề cấm còn lại (y tế, pháp lý ngoài phạm vi, chính trị, tôn giáo); cuối cùng là yêu cầu gặp nhân viên. | Đóng F1 "Còn chờ"; owner chọn 2026-11-10 |
| W6.2-D3 | **Kho chính sách 14 tài liệu, Claude viết, owner duyệt khi merge PR handoff.** Viết lại 9 tài liệu cũ, giữ nguyên tên tệp; thêm 5 tài liệu: hoàn tiền, đồng kiểm khi nhận, giờ làm việc và kênh liên hệ, phí vận chuyển, hóa đơn VAT. Toàn bộ là dữ liệu giả lập, ghi rõ ở đầu mỗi tài liệu. Con số khớp code và sàn ảo: trả hàng 7 ngày, đổi size 15 ngày, bảo hành mặc định 90 ngày, bồi thường khi trễ quá 48 giờ bằng voucher 50.000 VNĐ hạn 30 ngày, phí ship 20.000, 30.000, 40.000 VNĐ theo vùng, giao tối đa 3 lần, hoàn tiền 12 đến 72 giờ. Không tài liệu nào hứa việc mà tool không làm: AI không phát voucher, không tạo phiếu, không duyệt, không gửi khiếu nại tới hãng, không đưa số điện thoại đầy đủ của shipper, không đưa hotline. Đơn đang giao không hủy được. | Đóng F2, F9 "Còn chờ"; owner chọn 2026-11-10 |
| W6.2-D4 | **Reset chỉ dừng vì tombstone liên quan.** Tombstone chặn khi `order_id` của nó trùng `id` hoặc `external_order_id` của một đơn thuộc nguồn đang reset, hoặc trùng `external_order_id` trong tệp sự kiện sẽ nhập lại nếu operator truyền tệp đó. Tombstone khác vẫn được liệt kê trong dry-run nhưng không chặn. Giữ nguyên W6.1b-2-D9: không tạo, không xóa tombstone. Ngày reset production do owner chọn, mặc định trong tuần trước 2026-12-15, không bắt buộc cùng lượt deploy W6.2. | Làm rõ W6.1b-2-D9; đóng F22 |
| W6.2-D5 | **Nạp tri thức có tắt tài liệu cũ.** `knowledge ingest --prune` đặt `active=0` cho tài liệu có `source_key` không còn trong thư mục, không xóa dòng nào; thêm `knowledge list` liệt kê tài liệu, trạng thái và checksum. Nạp tri thức cho tenant production là bước operator chạy tay sau deploy, có ghi kết quả trước và sau. | Mới |
| W6.2-D6 | **Một quy tắc mới trong system prompt của agent khách** cho câu hỏi quyền lợi theo W6.2-D2 mục (2). Đây là sửa hành vi, không phải thí nghiệm context engineering của W6.5; W6.4 đo trên bản sau W6.2. F5: giữ DDL `semantic_cache`, chỉ thêm chú thích trong code, vì W6.2 không có migration. F3 để W6.5 làm tùy chọn. F4 sửa trong văn bản khóa luận. | Đóng F5 "Còn chờ" |

## 23. W6.3 owner decisions (2026-11-10)

Owner chốt W6.3 ngày 2026-11-10, cùng ngày phát hành W6.2 handoff. W6.3-D1 đến D4 do owner chọn trực tiếp; các mục còn lại là mặc định đề xuất kèm [W6.3 handoff](W6_3_EXECUTION_HANDOFF_2026-11-10.md), owner chấp nhận khi merge bản ghi này. Không mở W6.4 trở đi.

| ID | Quyết định | Thay thế |
|---|---|---|
| W6.3-D1 | **210 ca mô phỏng do một model độc lập viết** từ bộ tài liệu `khoa_luan/eval_pack/` bản 2, model đó không đọc mã nguồn. Owner gửi bộ tài liệu cho model qua giao diện chat, mỗi lượt một bộ. Claude kiểm tự động bằng bộ kiểm dữ liệu và phát lại quỹ đạo mẫu, chỉ trả lại ca hỏng kèm lý do; Claude, Argon, Codex không tự viết hay sửa kỳ vọng của 210 ca này. | Giữ thiết kế ở W6 backlog mục 3; owner chọn 2026-11-10 |
| W6.3-D2 | **Giữ 250 ca:** 210 mô phỏng, 28 chuyển thể từ τ²-bench retail, 12 chuyển thể từ AgentDojo; 12 bộ S01–S12 theo `eval_pack/05_PHAN_BO_CA.md`. Ma trận W6.4 giữ như W6 backlog mục 3; nếu Colab thiếu compute thì owner quyết giảm số lần lặp hoặc tập con ở W6.4, không viết lại dữ liệu. | Owner chọn 2026-11-10 |
| W6.3-D3 | **40 ca chuyển thể do Claude làm** sau khi bộ kiểm dữ liệu mới đã merge, theo quy trình ở `khoa_luan/05_thiet_ke_bo_danh_gia.md` mục 7.2: ghi `meta.origin` cùng mã nhiệm vụ và commit của repo gốc, ánh xạ sang dữ liệu sàn ảo, viết lại kỳ vọng theo nguyên tắc AI không ghi dữ liệu. Không chép dữ liệu ngoài hai repo MIT này. | Owner chọn 2026-11-10 |
| W6.3-D4 | **Phần code W6.3 do Codex làm, song song với W6.2 do Argon làm.** Hai phần không sửa chung tệp nguồn; tệp sinh tự động `notebooks/colab_agent.ipynb` có thể xung đột: PR merge sau thì merge `main` vào nhánh của mình rồi sinh lại notebook, không rebase. | Owner chọn 2026-11-10 |
| W6.3-D5 | **`eval_pack` bản 2.** Bỏ dữ liệu cũ (`C-001`, `O-101` …); phần dữ liệu của `03` (kết quả tool thật, khách, đơn, catalog, kho chính sách) do script sinh từ `data/demo_events/` và `data/knowledge/`, CI kiểm đồng bộ như notebook. Phần luật nghiệp vụ, tool, định dạng và phân bổ ca do Claude viết tay. Bốn ca mẫu của `06_vi_du.jsonl` viết lại trên dữ liệu mới và được CI phát lại. Mỗi ca ghi `customer` là mã khách sàn ảo. | Thay `eval_pack` bản 2026-11-06 |
| W6.3-D6 | **Hai chế độ kho tri thức khi đánh giá.** CI và kiểm định dạng dùng chế độ `scripted`: đoạn chính sách trong trường `knowledge` của ca. W6.4 dùng chế độ `real`: kho `data/knowledge/` nạp vào PostgreSQL có pgvector, truy hồi thật; trường `knowledge` bị bỏ qua, `sources` vẫn được chấm. Ca chèn lệnh qua đoạn chính sách của AgentDojo luôn chạy `scripted`. Bộ S03 có thêm phép đo Recall@3 và MRR trên kho thật. | Làm rõ F6 |
| W6.3-D7 | **Đóng băng dữ liệu.** Trước lượt chạy đầu tiên của W6.4, ghi SHA-256 của từng tệp `evals/suites/*.jsonl` vào biên bản; sau đó không sửa ca, chỉ thêm phiên bản mới. `evals/scenarios/benchmark_250.jsonl`, `evals/batches/` và `evals/qrels/policy_qrels_v1.json` giữ làm tài liệu lịch sử, không thuộc 250 ca. 44 kịch bản hồi quy W3.2 và W4 vẫn chạy trong CI như cũ. | Mới |

## 24. W6.2.1 owner decisions (2026-11-11)

Owner chốt ngày 2026-11-11 khi Claude kiểm chứng PR #87 và thấy F26: server mở form trả, đổi hàng cho đơn đã quá thời hạn. W6.2.1-D1 và D3 do owner chọn trực tiếp; W6.2.1-D2 là mặc định đề xuất kèm [W6.2.1 handoff](W6_2_1_EXECUTION_HANDOFF_2026-11-11.md), owner chấp nhận khi merge bản ghi này.

| ID | Quyết định | Thay thế |
|---|---|---|
| W6.2.1-D1 | **Server chặn theo thời hạn.** Tool `prepare_order_action` và bước tạo yêu cầu đều từ chối khi quá hạn, với mã lý do riêng: trả hàng quá 7 ngày kể từ ngày giao; đổi sang biến thể khác quá 15 ngày; đổi cùng biến thể do lỗi quá thời hạn bảo hành của sản phẩm. Trả hàng quá hạn nhưng còn bảo hành thì kết quả gợi ý đổi cùng biến thể nếu hàng lỗi. Form trên web chỉ đưa các loại đổi mà server cho phép. Đơn đã giao nhưng thiếu ngày giao thì không chặn theo thời hạn, để nhân viên quyết. Yêu cầu đang mở và quyết định của nhân viên không bị ảnh hưởng. | Làm rõ W6.1b-D9 "điều kiện do server tính"; owner chọn 2026-11-11 |
| W6.2.1-D2 | **Làm sau W6.2, deploy chung một lượt với W6.2.** W6.2.1 sửa `retailops/business/store.py` như W6.2, nên chỉ bắt đầu khi W6.2 đã merge. Bộ tài liệu `eval_pack` chỉ phát hành cho model độc lập sau khi W6.2.1 merge, để kết quả tool trong `03` đã đúng luật thời hạn. | Mới |
| W6.2.1-D3 | **Gộp dọa kiện ngầm vào W6.2.1.** Câu đe dọa pháp lý không có chữ "kiện", như nhờ luật sư làm việc với shop hay bảo shop chờ giấy triệu tập của tòa, được chuyển nhân viên như dọa kiện; câu hỏi pháp lý không nhắm vào shop vẫn bị từ chối khéo theo W6.2-D2. Owner chọn sửa trước buổi bảo vệ thay vì chờ số liệu W6.4. | Mở rộng W6.2-D2; owner chọn 2026-11-11 |

## 25. W6.3.1 owner decisions (2026-11-11)

Owner chọn ngày 2026-11-11 viết handoff sửa ba lỗi Claude tìm thấy khi kiểm bộ S07 đầu tiên ([biên bản](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-11-11-s07-first-suite-check)). Các mục dưới là mặc định đề xuất kèm [W6.3.1 hotfix handoff](W6_3_1_HOTFIX_HANDOFF_2026-11-11.md), owner chấp nhận khi merge bản ghi này.

| ID | Quyết định | Thay thế |
|---|---|---|
| W6.3.1-D1 | **Chuyển nhân viên không được thất bại âm thầm (F28).** `reason` của `request_human_support` nhận tới 1.000 ký tự, bằng giới hạn `comment` của kho lưu. Câu trả lời nói đã chuyển cho nhân viên mà không tool nào của lượt chuyển thành công thì bị cắt, kèm câu ghi chú mời khách nhắn lại. | Mới |
| W6.3.1-D2 | **Dữ kiện thời hạn có nguồn từ tool không bị cắt (F29).** Câu về thời hạn trả, đổi, bảo hành hay mốc giao được giữ khi số ngày trong câu là số server vừa trả, hoặc câu không có số và tool của lượt có cờ điều kiện thời hạn hay mốc giao. Lời hứa về phí và giao nhận vẫn phải có trích dẫn. | Làm rõ W3.2-D11 |
| W6.3.1-D3 | **Lượt do rào an toàn trả lời không bị coi là quỹ đạo lỗi thời.** Ở chế độ `--fake`, bước quỹ đạo chưa dùng của lượt không gọi model thì bỏ qua; mọi kỳ vọng vẫn được chấm. Ca do model độc lập viết không phải đoán rào nào sẽ bắt. | Làm rõ W6.3-D1 |

## 26. W6.3.2 owner decisions (2026-11-12)

Owner chọn ngày 2026-11-12 viết handoff sửa ba lỗi Claude tìm thấy khi kiểm bộ S01 ([biên bản](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-11-12-s01-part-1-check)). Các mục dưới là mặc định đề xuất kèm [W6.3.2 hotfix handoff](W6_3_2_HOTFIX_HANDOFF_2026-11-12.md), owner chấp nhận khi merge bản ghi này.

| ID | Quyết định | Thay thế |
|---|---|---|
| W6.3.2-D1 | **Phí ship và số tiền của đơn lấy từ tool không bị cắt (F30).** Câu chỉ nói "phí ship", "phí vận chuyển", "phí giao" được giữ khi có số tiền và mọi số tiền trong câu là số tool của lượt vừa trả (`shipping_fee`, `amount`, `refunded_total`, `pending_total`). Câu miễn phí, chịu phí, phí đổi, trả, hoàn và câu phí không có số vẫn phải có trích dẫn. | Làm rõ W3.2-D11, W6.3.1-D2 |
| W6.3.2-D2 | **Trạng thái hoàn tiền có nguồn từ tool không bị coi là khẳng định không căn cứ (F31).** Khi tool của lượt cho thấy đơn đã hoàn tiền (`payment_status` refunded/partially_refunded, hoặc hoàn tiền completed), câu nói đơn đã được hoàn tiền được giữ, như câu nói đơn đã hủy khi tool cho thấy đơn đã hủy. Hoàn tiền đang chờ và câu kèm khẳng định khác vẫn bị cắt. | Làm rõ W3.2-D3 |
| W6.3.2-D3 | **Quỹ đạo mẫu chỉ dùng mã có trong dữ liệu demo.** Bộ kiểm giữ quy tắc chặn `order_id`, `product_id` ngoài dữ liệu demo trong `fake_model`. Ca mã sai, mã thiếu viết quỹ đạo mẫu bằng `list_orders` hoặc hỏi lại; kỳ vọng vẫn cho model thật gọi tool với mã sai. | Làm rõ W6.3-D1 |
| W6.3.2-D4 | **Chữ số trong tên sản phẩm, size, số lượng không phải số ngày (F32).** Câu thời hạn chỉ so các số đi ngay trước đơn vị thời gian (ngày, tuần, tháng, năm, giờ) với tập số ngày tool trả; câu không có số như vậy theo quy tắc không có số của W6.3.1-D2. | Làm rõ W6.3.1-D2 |

## 27. W6.3.3 owner decisions (2026-11-12)

Owner chọn ngày 2026-11-12 tách hai lỗi Claude tìm thấy khi kiểm bộ S02 ra khỏi W6.3.2 ([biên bản](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-11-12-s02-check-and-w632-first-verification)). Các mục dưới là mặc định đề xuất kèm [W6.3.3 hotfix handoff](W6_3_3_HOTFIX_HANDOFF_2026-11-12.md), owner chấp nhận khi merge bản ghi này.

| ID | Quyết định | Thay thế |
|---|---|---|
| W6.3.3-D1 | **"livestream", "quay clip" chỉ là bức xúc khi đi cùng ý đe dọa công khai (F33).** Hai chữ này đứng riêng không kích hoạt rào bức xúc; đi cùng bóc phốt, tố cáo, đăng lên mạng, "cho mọi người biết" thì vẫn chuyển nhân viên như cũ. | Làm rõ W6.2-D1 |
| W6.3.3-D2 | **Tín hiệu bán lẻ thắng từ khóa chủ đề chung khi chọn chế độ (F34).** Mã sản phẩm `P-xxx`, mã đơn `SIM-O-` và cụm bán lẻ viết không dấu tính là tín hiệu bán lẻ; bỏ từ viết tắt đứng riêng "sac" khỏi danh sách chủ đề chung. | Mới |
