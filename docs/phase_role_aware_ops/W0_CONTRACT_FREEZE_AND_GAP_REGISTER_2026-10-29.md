# Phase R1 — W0 Contract Freeze & Gap Register

> **Status:** W0 CONTRACT CLOSEOUT (2026-10-31) · §10/§11 OWNER DECISIONS & ACCEPTED MECHANICS RECORDED · BOUNDED **W1-ONLY** EXECUTION AUTHORIZED BY OWNER (`BLOCKED` READINESS VERDICT UNCHANGED; `W2–W6` NOT AUTHORIZED) · W1 REMEDIATED & VERIFIED, W1 POLICY DECIDED — W1 COMPLETE (OWNER CONFIRMED 2026-10-31) (see §7 addendum)
> **Source revision:** `bbfd11d0ba4c13514a197a6b25802c4e217bedb3`. Argon recorded a read-only GitHub check at `2026-10-29T23:11:17+07:00`, and repeated `git ls-remote origin refs/heads/main` on `2026-10-31` returning the same SHA (`bbfd11d0ba4c13514a197a6b25802c4e217bedb3`); both are timestamp-bounded Git checks, not deployment/runtime proof.
> **Purpose:** separate owner-frozen invariants and [accepted mechanics (§10/§11)](W0_OWNER_DECISION_DELTA_2026-10-29.md#10-final-owner-decisions-2026-10-31) from `bbfd11d0` source behavior and remaining slice-specific DTO details. This file does not claim a new readiness review (`READY`) or authorize `W2–W6`.

## 1. Invariants that are frozen by owner direction

These are safe contract boundaries for a later implementation prompt:

- Business roles are exactly `customer`, `staff`, and `manager`; the store owner uses `manager`.
- `opsadmin` is a separate Ops Admin Console authentication path. It is not a business membership role and is not a runtime alias for `manager` or `platform_admin`.
- `viewer` is legacy, must fail closed, and must never be silently promoted to `customer` during Google login.
- `platform_admin` is legacy technical debt to retire gradually. Do not alias it to `manager` or transfer its historical cross-tenant/control-plane grants.
- Authorization and audit actor identity come from the server-side authenticated principal, role, tenant and time. A client `staff_name` is not trusted actor identity.
- Staff/Manager internal AI must be bound server-side to an authorized selected `case_id`; a copied title or free-text label is never an authorization key.
- The case transcript projection and the knowledge/vector evidence projection are separate. Vector retrieval can provide filtered policy evidence only after case authorization; it cannot select the case.
- Staff Desk has exactly three case buckets: `waiting`, `in_progress`, and `resolved`. `cancelled` is an order outcome, not a case state.
- Case resolution, order cancellation, return approval and refund are separate objects/outcomes even when linked to one conversation and order.
- Every cancel/return request is human-reviewed: Customer submits; the agent builds the detail panel; authenticated Staff or Manager confirms and approves/rejects. Staff-raised delivery-failure cancellation and refund requests are decided by a Manager. The model cannot approve or write that decision.
- Manager keeps same-tenant account administration on app `/api/admin/*`; `opsadmin` stays the separate read-only Ops Console.
- Inactivity: 3-minute timer from a bot message awaiting the customer, only for cases not held by Staff/Manager; expiry → `resolved` (`inactivity`); the customer's Continue resumes the same `case_id`; resolve releases runtime resources and Continue reloads from the DB on demand.
- Internal follow-up history partition `(tenant_id, principal_id, case_id)`; internal profiles bypass caches in the first slice.
- Delivery is strictly sequential `W0 → W1 → W2 → W3 → W4 → W5 → W6`. Source: [2026-10-31 owner decisions](W0_OWNER_DECISION_DELTA_2026-10-29.md#10-final-owner-decisions-2026-10-31).
- Integration input and output use one JSONL format/schema family (`retailops.order_action` v1) with transactional `integration_outbox` and daily-rotated protected file sink option A, as accepted in [owner delta §11.4](W0_OWNER_DECISION_DELTA_2026-10-29.md#114-jsonl-envelope-and-outbox-od-04od-06).
- Satisfaction feedback may be retained for offline evaluation/model improvement (5-minute post-feedback completion timer accepted in [§11.3](W0_OWNER_DECISION_DELTA_2026-10-29.md#113-timer-after-feedback-od-03)). A single rating must not automatically update or train the live model.
- Raw attachments are excluded from model payload by default; evidence intake limits/validation/90-day retention and the two-layer-authenticated Colab production path are accepted in [owner delta §11.6](W0_OWNER_DECISION_DELTA_2026-10-29.md#116-evidence-and-production-inference-on-colab-od-08-revised) (live customer data remains forbidden on bare unauthenticated public tunnels).

## 2. ExecutionContext snapshot

The minimum invariant boundary is known, but the exact DTO is not owner-frozen. A future request context must be derived from the authenticated session and verified database links, be immutable for the request, and carry enough identity to prevent cross-role or cross-case reuse. The candidate fields that still require contract approval are:

| Boundary | Required behavior | Current source evidence / gap |
|---|---|---|
| Principal | Server-derived `principal_id`, immutable audit actor | `SessionBinding` is a frozen dataclass and carries principal/membership/role, but the application has no separate immutable per-request context ([`retailops/identity/contracts.py`](../../retailops/identity/contracts.py), lines 11–21). |
| Role and tenant | Derived from the session; never selected by browser | `Application` stores role/tenant on a cached app object. `public.py` mutates `app.current_binding` before dispatch ([`retailops/http/public.py`](../../retailops/http/public.py), lines 195–213), so concurrency/context bleed must be resolved before internal profiles are added. |
| Profile | Explicit allowlisted `customer_chat`, `staff_case_assist` or approved manager profile | No `execution_profile` is present in the current chat/tool request or workflow state. |
| Case | Selected `case_id` required for Staff/Manager internal AI; no selected case fails closed | Current `/api/chat` accepts `text`, `conversation_id`, `request_id` and optional attachment only ([`retailops/business/application.py`](../../retailops/business/application.py), lines 118–136). There is no `case_id`. |
| Linked objects | Verify `conversation_id`, `turn_id`/`message_id`, `handoff_id`, `order_action_request_id` and `order_id` against the authorized case | Current source binds chat to `customer_id + conversation_id`; it has no case/episode object or verified link set. |
| Request identity | Bind `request_id` to the context, profile and authorized case | Current graph fingerprint includes digest, application role and provider; the run ID is based on customer, conversation and request, not principal/profile/case ([`retailops/business/application.py`](../../retailops/business/application.py), lines 165–180). |

Internal follow-up history partition is **DECIDED** as `(tenant_id, principal_id, case_id)` — private per principal within an authorized case, with `ToolCache`/`SemanticCache` bypassed for internal profiles in the first slice ([owner delta §10](W0_OWNER_DECISION_DELTA_2026-10-29.md#10-final-owner-decisions-2026-10-31)). W1 introduces only the immutable per-request identity/RBAC authorization context; W4 adds internal execution profiles and case-assist graph state.

## 3. API schema gap

| Current endpoint | Current accepted identity/context | Contract gap before implementation |
|---|---|---|
| `/api/chat` | `text`, `conversation_id`, `request_id`, optional `{type,data,name}` attachment | No internal profile, selected `case_id`, principal-bound context, verified handoff/order-action links or customer/internal transcript separation. |
| `/api/tools/execute` | `tool_name`, `arguments`; Staff permission check | No `case_id`, profile or verified object binding; it creates `BoundTools` with an empty order/product snapshot ([`retailops/http/routes.py`](../../retailops/http/routes.py), lines 436–446). |
| `/api/staff/reply` | `conversation_id`, `message`, optional client `staff_name` | No server actor field, `handoff_id`, claim/assignment or case status transition. The client name is accepted and persisted ([`retailops/http/routes.py`](../../retailops/http/routes.py), lines 414–423). |
| `/api/staff/resolve` | `conversation_id`, optional client `staff_name` | No pending-episode check, no idempotency/expected version and no server actor field. The current store method can return success without a matching conversation or pending handoff ([`retailops/business/store.py`](../../retailops/business/store.py), lines 1744–1755). |
| `/api/staff/escalations` | Staff permission; latest `human_handoff` feedback rows | No explicit `waiting`/`in_progress`/`resolved` case status, assignment, handoff episode identity or customer-safe projection. The query returns handoff rows without filtering resolved reason codes ([`retailops/business/store.py`](../../retailops/business/store.py), lines 1512–1529). |
| `/api/events` | `app.store.events(customer)` | The endpoint must be reviewed for customer-safe event projection before internal events are exposed to any customer session ([`retailops/http/routes.py`](../../retailops/http/routes.py), lines 310–314). |

## 4. Lifecycle and persistence snapshot

The current schema has conversations, agent turns and feedback, but no first-class case or handoff episode table. `conversation_feedback` uses a free-form `reason_code`; handoff rows cascade from a conversation ([`retailops/business/schema.py`](../../retailops/business/schema.py), lines 116–140; [`retailops/storage/pg_schema.py`](../../retailops/storage/pg_schema.py), lines 34–52).

| Target lifecycle direction | Current source shape | Status |
|---|---|---|
| `waiting` | A non-resolved `human_handoff` row or a `customer_message` comment may imply waiting | Candidate mapping only; W2 implements durable `cases`/`handoff_episodes` ([§11.2](W0_OWNER_DECISION_DELTA_2026-10-29.md#112-timer-vs-concurrent-customer-message-and-resume-od-03-revised), [§11.5](W0_OWNER_DECISION_DELTA_2026-10-29.md#115-migration-runbook-od-07)). |
| `in_progress` | No persisted claim, assignee, lease or transfer state in the current handoff table | **Accepted mechanics (§11.2, W2):** `holder` + `version` bump cancels pending inactivity timeout; remaining multi-staff transfer UX stays deferred to W2/W5. |
| `resolved` | `resolve_escalation` changes every `human_handoff` row for the conversation to `reason_code='resolved'` | **Accepted mechanics (§11.2, W2):** episode-scoped resolution with `version`, `resolved_reason`, `resolved_at`, and runtime resource release. |
| Customer reply after resolution | `customer_message` updates the latest non-resolved row or inserts a new `human_handoff` row | **DECIDED (§10 & §11.2, W2):** Continue (or typed message after `resolved`) resumes the **same `case_id`** into `waiting` (with a new `handoff_id` episode when human help is needed) while retained; after retention ends, create a new `case_id` linked via `previous_case_id`. |
| 3-minute inactivity target / customer-reply reset / 1.5-minute flag prohibited in production / 5-minute post-feedback completion timer | `conversations.expires_at` is a conversation retention TTL and cleanup trigger, not a case-resolution timer | **DECIDED & ACCEPTED (§10, §11.2, §11.3, W2):** 3-minute timer starts from bot message awaiting customer when `holder IS NULL`; expiry → `resolved` (`inactivity`) via conditional `version` update; customer message first keeps case open; 1.5-minute flag forbidden in production; `feedback_prompted_at` replaces 3-minute timer with a single 5-minute completion timer (`resolved_reason='completed'`). |
| Satisfaction feedback | Generic `conversation_feedback` allows turn/session/handoff types and 1–5 rating | **Accepted mechanics (§10, §11.3, §11.4, §11.5; W2/W3/W5):** `case_feedback_events` + `case_feedback_recorded` JSONL event; Like/4–5→`chosen`, Dislike/1–3→`rejected`; consent/retention details stay bounded to offline eval. |

`new_conversation()` deletes expired conversations before inserting a new one ([`retailops/business/store.py`](../../retailops/business/store.py), lines 1282–1288). Because child feedback/turn rows use cascade deletion, TTL cleanup must be separated from case/handoff retention before pending work is persisted in this model.

## 5. Cache, checkpoint and provider boundary

- The semantic cache is an application-local query cache keyed by normalized query text and FAQ topic; it has no role, profile, principal or case partition ([`retailops/business/cache.py`](../../retailops/business/cache.py), lines 109–189).
- The tool cache is keyed by tenant, customer, tool name and arguments. It has no profile, principal or case dimension ([`retailops/business/cache.py`](../../retailops/business/cache.py), lines 256–380). That may be acceptable for a strictly customer-scoped read cache, but it is not a sufficient partition for future internal profiles without an approved policy.
- `graph_runs` stores only `customer_id`, fingerprint, seed and lease fields; checkpoints/writes cascade from the run ([`retailops/workflow/schema.py`](../../retailops/workflow/schema.py), lines 4–16). The current run ID is derived from customer, conversation and request, and the workflow state has no principal, role, tenant, profile or case fields ([`retailops/business/application.py`](../../retailops/business/application.py), lines 165–180; [`retailops/workflow/state.py`](../../retailops/workflow/state.py), lines 28–50).
- The model workflow accepts an attachment and places it in the user message when present or when a prior image is referenced ([`retailops/workflow/graph.py`](../../retailops/workflow/graph.py), lines 101–113). The HTTP boundary accepts only broad `image`/`document` types and a base64-like string length limit ([`retailops/business/application.py`](../../retailops/business/application.py), lines 128–135); it has no verified MIME, file count, scanning, OCR/PDF extraction or protected projection policy.
- The exact Gemma-4 fine-tune is included in `retailops_providers.py:TEXT_ONLY_MODELS`; `is_vision_model()` returns false for it, and `OpenRouterAgent.translate()` emits a filename notice instead of image pixels. `tests/test_react_tool_summary_safety.py::test_attachment_handling_for_text_only_and_vision_models` asserts this. The exact model card supports image input, so this is an **application-side capability mismatch**, not evidence that the model is text-only. The supplied Colab cell has no end-to-end image request and no PDF/document extraction. More in the [2026-10-29 owner delta](W0_OWNER_DECISION_DELTA_2026-10-29.md#8-od-08--re-evaluation-of-imagefile-support).

Owner target direction added after the earlier Argon docs review: prepare a production-capable Colab inference path for real customer data when enabled, using compact, server-authorized, case-bound context rather than a full conversation dump by default. Current serving limit is 8,192 tokens; 16,384 is an evaluation candidate only if L4 memory, latency and quality evidence supports it. This target does **not** authorize current live transfer through the supplied public ngrok endpoint, whose vLLM launch command has no configured API-key protection and whose privacy/request controls have not been verified. See the OD-08 section of the 2026-10-29 owner delta linked in the preceding bullet.

These are source gaps to carry into W4/OD-08. This W0 document does not choose a partition key or authorize passing raw attachments to the model or sending live customer data to an unprotected endpoint.

## 6. Freeze disposition

| Area | W0 disposition (updated 2026-10-31) |
|---|---|
| Roles, trusted actor, Manager same-tenant `/api/admin/*` (§11.1), Viewer/`platform_admin` retirement (§11.5), sequential `W0 → W6` | **Frozen owner decisions & accepted W1 mechanics** |
| Per-request `ExecutionContext` field set and history partition | **W1 identity/RBAC request context frozen; internal history partition `(tenant_id, principal_id, case_id)` decided (§10); W4 profile DTO fields deferred to W4** |
| API DTOs for internal chat/tools/reply/resolve | **W1 actor/RBAC/object-binding guard enforced; W2–W4 case/episode/assist DTO extensions deferred to W2–W4** — *Đính chính 2026-10-31: actor từ session và RBAC đã có, nhưng object/case binding **chưa đủ**. Staff vẫn đọc/reply/resolve được bằng UUID, và Manager vẫn gọi được direct tool trên conversation chưa escalate (`W1-RB-01`/`W1-RB-02` trong [readiness register](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-10-31-w1-implementation-readiness-review--codex)). Không được đọc dòng này như W1 đã hoàn tất.* |
| `waiting`/`in_progress`/`resolved` transition table & timers | **Vocabulary and §11.2/§11.3 timer/Continue mechanics accepted (deferred to W2; not started in W1)** |
| Case/handoff/order-action/outbox persistence schema | **Business v5 & JSONL sink option A accepted in §11.4/§11.5 (deferred to W2–W3; W1 touches only identity v5 code/tests)** |
| Cache/checkpoint partitioning | **Internal cache bypass in first slice decided (§10); W4 graph/checkpoint partition deferred to W4** |
| Attachment handling & Colab inference | **§11.6 intake rules and Colab production target accepted (deferred to W3/W4/W6; live customer data still gated on two-layer endpoint auth)** |

## 7. Next gate (2026-10-31 closeout)

Owner decisions in [§10](W0_OWNER_DECISION_DELTA_2026-10-29.md#10-final-owner-decisions-2026-10-31) and accepted mechanics in [§11](W0_OWNER_DECISION_DELTA_2026-10-29.md#11-accepted-mechanics-2026-10-31) close out the W0 policy/mechanics items above. On 2026-10-31 the owner issued a bounded **W1-only** authorization (W0 closeout + W1 identity, RBAC, backend authorization, identity v5 migration code, and isolated W1 tests only). [Implementation readiness](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md) remains `BLOCKED` (no new readiness review `READY` is claimed), and `W2–W6`, live database/production migration execution, EC2/SSM, Colab/LLM runtime calls, commit, push, merge and deploy remain **not authorized**. Any W1 policy detail not settled by the canonical docs (such as first-time Google login role-provisioning policy vs operator-only role-change authority) must stop at that boundary and ask the owner explicitly.

**Addendum 2026-10-31 — trạng thái W1:** W1 đã được thực thi trong worktree nhưng review W1 kết luận `BLOCKED`, nên W1 chưa hoàn tất. Blocker gồm object/case binding (`W1-RB-01`, `W1-RB-02`) và migration identity v5 có thể chạy ngay khi khởi tạo store/CLI thay vì qua bước có kiểm soát theo [§11.5](W0_OWNER_DECISION_DELTA_2026-10-29.md#115-migration-runbook-od-07) (`W1-MIG-01`). Hai chính sách vẫn chờ owner: provisioning role cho Google login lần đầu (`W1-ID-01`) và kênh có thẩm quyền đổi role (`W1-ID-02`). Chi tiết và khuyến nghị (chưa phải quyết định owner) nằm trong [docs review addendum](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-10-31-w1-docs-review-addendum). Các ranh giới không được phép ở trên giữ nguyên.

**Cập nhật sau đó cùng ngày:** 5 BLOCKER đã được remediation và [kiểm chứng](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-10-31-w1-remediation-verification). Object/case binding ở dòng "API DTOs" của bảng §6 giờ đã đạt cho Staff và Manager, theo biểu diễn handoff episode hiện có, cho tới khi W2 có durable case. Owner đã chốt hai chính sách W1 ([owner delta §12](W0_OWNER_DECISION_DELTA_2026-10-29.md#12-w1-policy-decisions-2026-10-31)). W1 không còn blocker mở; owner đã xác nhận đóng W1, nên **W1 hoàn tất**.

## Related records

- [Canonical R1 design](README.md)
- [Historical owner decision snapshot](OWNER_DECISIONS_2026-10-28.md)
- [W0 owner decision delta/proposals 2026-10-29](W0_OWNER_DECISION_DELTA_2026-10-29.md)
- [W0 read-only role inventory](W0_ROLE_INVENTORY_2026-10-29.md)
- [W0 baseline and decision register](W0_BASELINE_AND_DECISION_REGISTER_2026-10-27.md)
- [Implementation readiness: BLOCKED](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md)
- [W0 review reconciliation (review chronology)](W0_REVIEW_RECONCILIATION_2026-10-28.md)
