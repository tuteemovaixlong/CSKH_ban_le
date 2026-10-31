# Gemini 4 Argon — Owner-direction R1 Review Result (2026-10-26)

> **Verdict:** `PASS WITH REQUIRED CHANGES` — documentation/design readiness only.
> **Boundary:** This record preserves the owner-pasted Gemini 4 Argon review of the owner-directed R1 revision before the current correction patch. It does not approve implementation, tests, CI, deployment, database changes or production runtime.

## Review basis

- Reviewer: Gemini 4 Argon through Antigravity, reported by the owner.
- Review mode: read-only code/docs inspection; no file edits, migrations, live-service checks or deploy verification.
- Scope: the canonical Phase R1 design and linked root/status/roadmap/acceptance/RBAC/identity/admin/AI documents listed in [the handoff](ARGON_OWNER_DIRECTION_REVIEW_HANDOFF_2026-10-26.md).
- Baselines cited by the review: committed `HEAD dd544800` and local source-review ref `origin/main bbfd11d0`; the local ref was not treated as current GitHub HEAD or deployed code.

## Findings requiring correction

### Blocker-level design corrections

1. **Canonical case identity/lifecycle was internally inconsistent.** Some sections treated a case as one `handoff_id` with `pending/resolved/customer_closed`, while other sections described three Staff Desk buckets and separate order-action outcomes. Required correction: make `case_id` the Staff Desk identity with `waiting/in_progress/resolved`; model optional `handoff_id` and optional `order_action_request_id` as separate linked lifecycles; define active/resolved read policy and remove any requirement that `staff_case_assist` always have a pending handoff.
2. **Customer self-cancellation can bypass the R1 human-review target.** The reviewed source exposes `/api/cancellation-proposals` and its confirm route; a customer with `orders:cancel` can currently reach a path that mutates `orders.status = cancelled`. Required correction: label this as current source behavior, explicitly choose the R1 disposition, default to `pending_human_review` for the target, preserve fixture/benchmark compatibility, and model return/refund separately from the current order-status enum.
3. **Internal chat context was not explicitly partitioned per case.** Required correction: use an Internal Assist Store/checkpoint key `(tenant_id, principal_id, case_id)`, fail closed when no case is selected for `staff_case_assist`, and prove that switching Case A → Case B cannot reuse A's transcript/checkpoint/prompt context.

### Major corrections

1. **Cancel/return request fields were missing from the initial AI projection.** Add `request_id`, `order_id`, `action_type`, bounded untrusted `reason`, `review_status`, evidence count/category/availability, and prior decision status/timestamp; keep raw evidence bytes out of model context by default.
2. **Hardcoded/demo identity fallback remained a source gap.** The review identified fallback generation such as `"Mai Anh"`/`"Khách mẫu"` in `retailops/http/routes.py`, `retailops/business/store.py`, `web/index.html` and `web/app.js`, including starter bubbles and staff reply/resolve paths. The target contract must be trusted session-derived `display_name` or `null`, with no canned internal greeting; source cleanup is a separate code task.
3. **Viewer fail-closed coverage was incomplete.** The docs must cover read/transcript access, session resolution, login/provisioning, active-session invalidation, CLI/admin routes, the five customer-bound POST paths (`/api/conversations`, `/api/conversations/{id}/focus`, `/api/chat`, `/api/feedback`, `/api/staff/customer-message`) and secure evidence-serving controls. Viewer must not be auto-mapped to Customer.

### Minor corrections

1. Mark `docs/PLAN_GOOGLE_ACCOUNT_RBAC_PRODUCTION.md` sections 2.1 and 3 as historical roadmap material superseded for current role/approval/Admin Console boundaries by R1.
2. Add a warning in `docs/PERSISTENT_IDENTITY.md` that `--role viewer` examples are migration/audit fixtures only and must not provision new Viewer accounts.
3. Update root/index summaries to distinguish current v0.7/P5-C self-cancel behavior from the proposed R1 human-review policy and forbid demo display-name fallbacks.

## Owner-direction checklist

| # | Owner direction | Result in reviewed revision |
|---|---|---|
| 1 | Exactly `customer`, `staff`, `manager`; owner uses `manager` | PASS |
| 2 | `opsadmin` separate; do not equate to `platform_admin` | PASS |
| 3 | Viewer legacy; safe migration; no auto-promotion | FAIL — scope needed expansion |
| 4 | No canned “Nguyễn Mai Anh” for Staff/Manager | FAIL — source fallback still documented/implemented |
| 5 | One shared workflow/graph with role/task profiles | PASS |
| 6 | Three Desk buckets; separate Handoff view; separate lifecycles | FAIL — case/handoff model contradicted itself |
| 7 | Human-reviewed cancel/return with required reason and optional evidence | FAIL — current customer self-cancel and request schema needed explicit disposition |
| 8 | Selected-case internal AI, server-bound and isolated | FAIL — thread/checkpoint partition and no-case behavior needed explicit contract |

## Cross-document/source notes

- Shared-workflow architecture, three business roles, separate `opsadmin`, and no automatic Viewer promotion were directionally correct.
- The source review confirmed Staff `orders:cancel` in both cited refs (`dd544800` and `bbfd11d0`), not only one ref.
- Manager human `/api/admin/*` behavior and source-ref `platform_admin` differences must remain historical/source findings, not be silently changed or granted to `manager_ops_assist`.
- The review did not verify EC2, GitHub latest state, CI, deployment or runtime.

## Disposition

The required corrections are being applied in the current working tree. The corrected packet must pass `python scripts/check_docs_contract.py` and `git diff --check`, then receive a focused read-only Argon delta review. Until that delta review is recorded, R1 remains docs-only and not implementation-ready.

> **Explicit scope statement:** This review is documentation/design-only; it does not approve implementation, tests, CI, deployment, or production runtime.
