# AI system documentation

Reading path cho hội đồng: [system map](AI_SYSTEM_MAP.md) → [model card](AI_MODEL_CARD.md) → [agent catalog](AI_AGENT_CATALOG.md) → [prompt catalog](AI_PROMPT_CATALOG.md) → [RAG pipeline](AI_RAG_PIPELINE.md) → [evaluation and safety](AI_EVALUATION_AND_SAFETY.md) → [reproducibility](AI_REPRODUCIBILITY.md) → [contamination analysis](AI_CONTAMINATION_ANALYSIS.md).

Các digest là lớp trích xuất có citation: [MODELS](../_digest/code/MODELS.digest), [PROMPTS](../_digest/code/PROMPTS.digest), [AGENTS](../_digest/code/AGENTS.digest), [TOOLS](../_digest/code/TOOLS.digest), [RAG](../_digest/code/RAG.digest), [EVAL](../_digest/code/EVAL.digest) và [CONTRACTS](../_digest/code/CONTRACTS.digest).

Mọi tài liệu ở tầng này chỉ mô tả code/config đã đọc tại SHA ghi trong digest. Provider, deployment, cost, latency hoặc training provenance thiếu evidence đều phải giữ nhãn `[UNVERIFIED]`.
## Phase R1 — Staff/Manager case assistance

Role-aware Staff/Manager case assistance is a proposed workflow contract, not an implemented or runtime-verified AI capability. Readiness remains **BLOCKED** and only W0 documentation/reconciliation is in scope. The documentation-only review loop is closed. For current scope, see the [Phase R1 design](../phase_role_aware_ops/README.md), [latest owner delta](../phase_role_aware_ops/W0_OWNER_DECISION_DELTA_2026-10-29.md), [review chronology](../phase_role_aware_ops/W0_REVIEW_RECONCILIATION_2026-10-28.md), and [blocked readiness](../phase_role_aware_ops/IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md). The supplied Colab/ngrok endpoint is not approved for real customer data; 8,192 tokens is the current serving limit and 16,384 is only an evidence-gated evaluation candidate.
