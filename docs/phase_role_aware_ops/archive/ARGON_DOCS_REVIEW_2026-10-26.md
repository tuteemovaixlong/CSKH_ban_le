# Gemini 4 Argon — Phase R1 Documentation Review (2026-10-26)

> **Revision boundary:** this report records Argon's review of the prior R1 documentation revision only. It does not cover the owner-directed three-role taxonomy, separate opsadmin/legacy-role handling, Staff Desk lifecycle buckets, cancel/return request UI, or selected-case internal AI added later on 2026-10-26. The new review prompt is in [ARGON_OWNER_DIRECTION_REVIEW_HANDOFF_2026-10-26.md](ARGON_OWNER_DIRECTION_REVIEW_HANDOFF_2026-10-26.md); do not apply this report's PASS to that newer revision.

> **Verdict:** `PASS WITH REQUIRED CHANGES` — documentation packet readiness only. This is not implementation approval, owner-policy approval, CI/deployment evidence, or EC2/runtime verification.
> **Architecture constraint:** Customer, Staff, and Manager remain on one shared workflow/graph. Argon found the packet consistent with this owner direction.

## Review basis and limits

- Read-only review reported by the owner from Gemini 4 Argon in Antigravity.
- Refs inspected: committed `HEAD dd544800bb087d54a7faf564e723736905620045` and local `origin/main bbfd11d0ba4c13514a197a6b25802c4e217bedb3`. The latter's last fetch was reported as 2026-10-24 18:46 +07; it is not proof of current GitHub HEAD or deployed code.
- Argon reports reviewing the full Phase R1 packet and linked status, roadmap, acceptance, RBAC, identity, AI-system, and operations docs, plus the relevant source at both refs. It did not modify files or run tests, migrations, live services, DB writes, or deployment checks.
- Production environment values, GitHub's latest state, and EC2/runtime remain unverified.

## Required documentation corrections

Argon reported **no P0**, **three P1**, **three P2**, and **one P3** documentation defects:

### P1

1. **Manager `/api/admin/*` rights were understated.** At `bbfd11d0`, Manager has P5-E account/quota administration and audit-log read within its own tenant, subject to restrictions including no mutation of `platform_admin`. `platform_admin` has cross-tenant scope under endpoint-specific rules; not every endpoint requires an explicitly supplied `tenant_id`. Preserve the existing human UI/API behavior unless the owner approves a change; keep those capabilities separate from—and denied to by default for—the `manager_ops_assist` AI profile.
2. **Manager Staff Desk entry points were described incorrectly.** The top-nav `#toggle-staff-desk` calls `openStaffDesk()` and loads/polls. The Manager Console `#btn-manager-open-staff-desk` and SOP 6 paths check `typeof refreshStaffQueue === 'function'`, although `refreshStaffQueue` is a DOM button, so those paths currently neither load the queue nor start polling. Test all three entry points separately.
3. **Knowledge projection field names did not match source.** Actual results use `citation_id`, `source_key`, `title`, `excerpt`, `content_sha256`, and `truncated`, not `source` and `version`. Current retrieval allows up to three results and 1,100-character excerpts; stricter 1,000/3,000-character limits may be retained as proposed R1 target caps. `content_sha256` hashes the excerpt, not a document version; citation-ID matching is not an entailment check.

### P2

4. **Mermaid lifecycle and cache paths needed correction.** Reply is non-terminal. Staff `pending → resolved` and customer `pending → customer_closed` are alternative terminal transitions. The architecture diagram should distinguish turn-level SemanticCache from ToolCache inside the executor after authorization and send every candidate—including cache hit and direct Supervisor/fallback output—through common output validation.
5. **Two code risks needed sharper classification.** Product CRUD passes `pid` positionally to `invalidate_product(tenant_id, product_id)`, so product invalidation is a confirmed dormant signature bug on both reviewed refs; it is dormant because `get_product` is not currently ToolCache-cacheable, while separate SemanticCache/catalog revision invalidation exists. Also, prompt/mode handling must be tested across all provider adapters and Local/Remote paths: `request_mode` may classify `sql`, `database`, or `python` as general (not `json` at the reviewed refs), causing tools to be omitted and potentially selecting `GENERAL_SYSTEM` where no explicit system message is supplied.
6. **Role/API matrix, bootstrap, and retention acceptance needed completion.** Viewer currently passes five session/customer-bound POST paths: conversation create, conversation focus, chat, feedback, and staff customer-message. Add session/profile/provider/logout and conversation GET routes to the matrix. `openSession()` calls conversation reads and may create a conversation before role routing; if Staff/Manager customer routes are denied, UI must skip those customer bootstrap calls. Test pending handoff retention when customer B creates a conversation after customer A's conversation exceeds `CONVERSATION_TTL`, because tenant-wide expiry cleanup may cascade-delete feedback; also test expired-conversation writes explicitly.

### P3

7. **Navigation/date drift:** mark the roadmap documentation update as 2026-10-26 while separately identifying the date of operational evidence; add synthesis links from `REVIEW_FINDINGS_2026-10-25.md`, `PLAN_RBAC_GOOGLE_AUTH.md`, and `PLAN_ECOMMERCE_OPS_COPILOT.md`.

## Other source-claim and design conclusions

- Argon agreed with the shared workflow and found the reviewed docs consistently preserve it.
- Argon found no evidence in the reviewed source of a cross-tenant Staff handoff bypass; the demonstrated issue is same-tenant object/lifecycle scope.
- Existing checkpoints already include customer/request/purpose/lease scoping; the R1 gap remains actor/subject/profile/case/projection identity, not a proven current checkpoint collision.
- RAG is tenant-scoped in the reviewed source but is not selected-case-bound.
- Owner decisions remain open: Manager's existing same-tenant P5-E UI/API rights; Platform Admin inheritance; Viewer read-only policy; role provisioning and safe `DEFAULT_ROLE`; personal cancellation; handoff uniqueness, return-to-bot, retention/history and attachments; transcript-derived order lookup; AI fields/KPIs; production `/api/tools/execute`; cache policy; quotas; internal draft/audit access and retention.

## Disposition

The required corrections have been applied in the [Phase R1 design and acceptance](../README.md), [independent audit synthesis](INDEPENDENT_AUDIT_SYNTHESIS_2026-10-26.md), and linked project indexes. The documentation contract validator passed after the edits. R1 remains **not implementation-ready** until owner decisions are resolved (and any further independent review the owner requests is complete). No runtime or deployment conclusion follows from this review.

## Targeted delta review (owner-pasted result, 2026-10-26)

> **Verdict:** `PASS` — documentation readiness against the reviewed refs only. This does not approve owner policy, implementation, tests, CI, deployment, or runtime.

- The owner supplied Argon's read-only delta-review report after the required corrections. Argon rechecked the seven correction groups against the Phase R1 docs and source at committed `HEAD dd544800bb087d54a7faf564e723736905620045` and local tracking `origin/main bbfd11d0ba4c13514a197a6b25802c4e217bedb3`; the report explicitly does not claim that the local ref is GitHub's latest or deployed code.
- Argon marked all seven groups **PASS**: Manager `/api/admin/*` scope; all three Manager Desk entry paths; knowledge result fields/caps/citation semantics; Mermaid cache/output/handoff lifecycle; dormant `invalidate_product` defect and provider/request-mode coverage; Viewer/API/bootstrap and retention acceptance; and dates, links, and status consistency.
- Argon identified two P3-only editorial improvements, neither blocking its `PASS`: update the acceptance-matrix status/next action to remove stale doc-corrections-pending wording, and consolidate narrower synthesis statements with later expanded findings. Both edits are now applied in the acceptance matrix and synthesis.
- The delta report was read-only and reported no test, migration, DB, live-service, deployment, or file-write activity by Argon. Its verdict covers documentation/source-reference consistency only; it does not resolve the owner policy choices listed above.
- After the editorial updates, `python scripts/check_docs_contract.py` passed all four checks (dataset integrity, stale Git HEAD, links/Markdown rules, and dynamic tool contract). `git diff --check` passed for the tracked edited index files; a separate trailing-whitespace scan passed across those files and all eight untracked R1 Markdown files. These are documentation integrity checks, not application tests. Until owner policy choices are explicitly decided, R1 remains **not implementation-ready** and unresolved areas remain deny-by-default.
