# Claude Opus — independent Phase R1 review trigger

## Purpose

Use this prompt in a Claude Opus session opened on the current repository/worktree. This is a **blind, read-only independent review** of the Phase R1 design after the Gemini 4 Argon review. Claude must inspect the source itself and must not treat Argon's report, the Codex findings, or the design's target architecture as proof.

The owner has already fixed one architectural constraint:

> Customer, Staff and Manager use **one shared workflow/graph core**. Role/task differences are request profiles that may change instructions, context projection, tool capabilities and output/persistence adapters. Do not propose three separate workflows or three duplicated graphs.

## Prompt

```text
You are Claude Opus acting as an independent senior security, architecture and code reviewer. Perform a READ-ONLY blind review of Phase R1 — Role-aware Staff & Manager Operations — in the current repository.

Repository and review scope:
- Read docs/phase_role_aware_ops/README.md.
- Read docs/phase_role_aware_ops/REVIEW_FINDINGS_2026-10-25.md.
- Read docs/phase_role_aware_ops/ARGON_FOLLOWUP_REVIEW_2026-10-25.md.
- Read docs/phase_role_aware_ops/ARGON_REVIEW_TRIGGER.md.
- Read the project status, roadmap, acceptance matrix and AI-system documents linked by the R1 README.
- Inspect the actual runtime source, schemas, tests and UI files cited by those documents. Code is the source of truth.

Non-negotiable owner architecture:
Customer, Staff and Manager must use ONE shared workflow/LangGraph orchestration core. Per-request profiles may change task instructions, context projection, tool capabilities and output/persistence adapters. Separate API ingress routes and storage boundaries are allowed where necessary for security and data separation. Do not recommend three role-specific workflows, three duplicated graphs, or separate orchestration stacks merely because the profiles differ.

Review independently. Do not merely confirm Argon or Codex findings. For each material finding, cite the exact file path and line range from the repository and classify it as one of:
- confirmed current code behavior;
- documentation drift;
- conditional future risk if R1 is implemented incorrectly;
- design proposal or owner-policy choice.

Required review areas:

1. Handoff and object authorization
- Verify whether Staff/Manager transcript, reply, resolve and future assist operations are bound server-side to one pending opaque handoff episode.
- Check arbitrary conversation IDs, resolved/stale IDs, wrong-tenant IDs, non-handoff conversations, duplicate handoffs and atomic state transitions.
- Check re-handoff after resolve, customer return-to-bot, polling/reload behavior, queue filtering/counts, persistence-before-UI acknowledgement and attachment behavior.
- Check Manager opening the Staff Desk, Manager order detail, and exchange quick-action semantics.

2. Identity, RBAC and audit
- Review all five roles: customer, viewer, staff, manager and platform_admin.
- Review the current inheritance difference between committed HEAD and local origin/main where applicable.
- Review /api/chat, /api/conversations*, /api/orders*, /api/feedback, /api/staff/*, /api/events, /api/account/usage, /api/cancellation-proposals*, /api/manager/* and /api/admin/*.
- Verify that role, tenant, object scope and actor identity are enforced server-side on every read/write/tool operation.
- Check whether client-supplied staff_name or similar fields can spoof audit identity.
- Check whether internal Staff/Manager drafts, principal metadata or audit payloads can leak through customer-facing event/history APIs.

3. One shared workflow with safe profile isolation
- Verify that customer_chat, staff_case_assist and manager_ops_assist can enter one shared orchestration without customer semantics leaking into internal assistance.
- Inspect graph_runs/checkpoints, PostgreSQL foreign keys, subject-customer versus actor-principal identity, purpose, fingerprint and thread-key construction.
- Check whether Staff/Manager identities require a fake customer row or can cause FK failures.
- Check whether mutable singleton Application state can mix selected cases between tabs or requests.
- Check every fallback from multi-agent to single-agent. Internal profiles must not inherit customer prompts or broad customer tool schemas accidentally.

4. Tools, workers, RAG/vector database and cache
- Inspect protocol tool schemas, worker-specific allowlists, server-side execution checks and direct /api/tools/execute.
- Check Dispute worker behavior: schema/executor parity, fail-closed unsupported tools, transcript and attachment preservation, cancellation/escalation behavior and profile-specific instructions.
- Check RAG/pgvector and lexical retrieval tenant isolation and whether retrieval is additionally constrained to the selected case/object scope.
- Check ToolCache and SemanticCache keys for tenant, actor, profile, projection version, case/conversation and arguments. Look for cross-profile or broader-projection returns.
- Check quota and usage telemetry identity for Staff/Manager versus the subject customer.

5. Exact data projections and privacy
- Verify that the proposed exact field allowlists are implementable and testable.
- Check queue fields, transcript limits, order fields, shipment fields, product/inventory fields, knowledge excerpts and Manager KPI fields.
- Check shipper name/phone, voucher/compensation data, customer PII, raw audit/events, product price/material/care and revenue.
- Identify any vague field name, unbounded text, missing type, missing maximum size, or current runtime response that violates the target projection.

6. Documentation and acceptance quality
- Check both Mermaid diagrams for truthful data flow, shared workflow identity, authorization boundaries and separate internal persistence.
- Check that implemented, proposed, historical, simulated and runtime-verified claims are clearly separated.
- Check consistency among README.md, docs/README.md, docs/CURRENT_PROJECT_STATUS.md, docs/PLAN_ROADMAP_INDEX.md, docs/03_EVALUATION/ACCEPTANCE_MATRIX.md and all R1 review records.
- Check relative links and whether the local origin/main SHA is described as a local ref rather than GitHub-latest or deployment evidence.
- Check that acceptance tests are objective, direct-API/tool-level where needed, and cover both allow and deny paths.

Review basis and safety rules:
- Record the exact branch, committed HEAD and local origin/main ref you inspected. Do not assume origin/main was freshly fetched.
- Treat uncommitted files as user-owned. Do not reset, clean, stash, stage, commit or rewrite anything.
- Do not run migrations, make database writes, call live services, deploy, or alter EC2.
- Tests may be inspected but do not claim a test passed unless you actually ran it and can report the command and result. Prefer no test execution for this review.
- Do not call a conditional design risk a confirmed live breach. Do not claim EC2 or production status from source or documentation.
- Do not implement fixes. Report what should change and how it should be tested.
- Treat all owner-decision rows in the R1 design as unapproved unless explicitly confirmed by the owner in the current conversation.

Output a concise review report in Vietnamese with exactly these sections:

(a) Review basis: branch, HEAD, origin/main, files inspected, read-only limits.
(b) Findings: ranked P0–P3, each with classification, impact, exact file/line evidence, remediation and objective test.
(c) Shared-workflow architecture: whether one graph with role/task profiles is preserved safely.
(d) Mermaid, docs and acceptance review.
(e) Owner decisions still open.
(f) Final verdict: exactly one of PASS, PASS WITH REQUIRED CHANGES, or BLOCKED.

If you cannot verify something, say so explicitly. End with a short list of the minimum changes required before R1 implementation. Do not produce a code patch.
```

## Expected result

Bring Claude's report back to Codex. Codex will reconcile it with the Argon and Codex findings, identify disagreements, update the R1 packet if needed, and only then decide whether the design is implementation-ready.

Related records:
- [R1 design](../README.md)
- [Initial Codex findings](REVIEW_FINDINGS_2026-10-25.md)
- [Argon follow-up report](ARGON_FOLLOWUP_REVIEW_2026-10-25.md)
- [Argon revision trigger](ARGON_REVIEW_TRIGGER.md)
