# RetailOps Release Manifest

This file freezes the implementation baseline used by the first vNext evaluation work.
It is evidence metadata, not a production-readiness claim.

## Baseline

- Repository: `tuteemovaixlong/CSKH_ban_le`
- Git commit: `a054fa0ade54a085269a4e9c30ea9df8385ea033`
- Latest merged PR at baseline: `#22` — `Route technical general Q&A outside RetailOps tool mode`
- Agent protocol: `retailops-agent-v2`
- Architecture: modular monolith + durable LangGraph + deterministic business services
- Public data mode: `persistent-demo`
- Live storage last verified on 2026-09-07: PostgreSQL
- Live pgvector last verified on 2026-09-07: `0.8.6`
- Current knowledge embedding baseline: `feature-hash-v1`
- Current graph budgets: `MAX_MODEL_CALLS=4`, `MAX_TOOL_CALLS=8`
- Current transcript limits: `MAX_MESSAGES=40`, `MAX_CHARACTERS=18000`

## Evidence levels

Use these levels consistently in reports:

- L1 — code merged / automated tests pass.
- L2 — image built, published and activated by deployment workflow.
- L3 — exact release rolled into the live service and runtime health verified.
- L4 — external/user-path real-model + business workflow E2E verified and saved as an artifact.

At creation of this manifest, PR #22 is confirmed through L3. A complete fresh L4 artifact remains a separate acceptance item.

## Evaluation rules

1. Do not use software test count as an agent-quality score.
2. Historical Qwen extraction metrics remain separate from current end-to-end agent metrics.
3. Compare architecture/model/retrieval changes on the same dataset and report denominator, failures and blocked cases.
4. Separate business correctness, agent behavior, retrieval/grounding and system/cost scoreboards.
5. Do not convert unavailable provider usage into zero cost; report it as unknown.
6. A valid citation proves provenance only; semantic entailment is measured separately.
7. No unsafe mutation may pass because the final answer merely claims success; final backend state is authoritative.

## Baseline runtime facts

The release rollout path verifies HTTPS `/healthz`, a live static-asset hash and the exact target container image before reporting success. The latest PR #22 rollout recreated the public web container on the exact ECR digest and reached healthy state.

This manifest intentionally contains no credentials, tokens, DSNs, private customer data or hidden model reasoning.
