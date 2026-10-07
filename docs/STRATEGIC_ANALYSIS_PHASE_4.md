# Strategic Analysis: Phase 4 Scientific Evaluation

> Ngày: 2026-10-06
> Baseline: main tại 49671b928ad6badfaa01331174eb73f0e366752e
> Trạng thái: READY FOR HARNESS/PREFLIGHT; chưa đủ evidence để ghi READY FOR MEASUREMENT hoặc production readiness.

## Kết luận điều hành

PR A/PR B và hardening runtime hiện đủ để làm baseline engineering. Điều này chưa chứng minh LLM quality, RAG grounding, live business data, OCR hay production SLO. Phase 4 hiện là guarded synthetic/persistent pilot baseline.

## Quyết định phạm vi

Giữ nguyên runtime và hai frozen benchmark 250 ca. BUILD HARNESS được phép thêm evaluation-only schemas, fixture/identity sidecar, qrels, grader, writer, validator và telemetry wrapper dưới phạm vi evaluation. Không được thay business logic, prompt, routing/RBAC, storage schema, frozen inputs hoặc semantics A0. Runtime/adapter change tạo system variant mới.

Canonical identity tuple:

~~~text
system_commit_sha
evaluation_harness_sha
evaluation_overlay_sha256
protocol_version
config_sha256
dataset_sha256
fixture_sha256
qrels_sha256
knowledge_base_sha256
~~~

evaluation_harness_sha chỉ null trong preflight; measurement bundle phải có immutable SHA. API model revision/tokenizer/seed không expose được ghi null + unavailable_reason; mismatch endpoint/provider/model thì block lane.

## Topology và protocol

- custom = RemoteAgent với /agent/identity và /agent/chat.
- api-reference-v1 = OpenRouterAgent/reference endpoint.
- api-vllm-selfhost-v1 = provider_id=api qua OpenAI-compatible vLLM /v1; nếu dùng custom phải có bridge /agent/* được pin.
- A0 quality semantic answer-cache OFF cả hai lane; ToolCache mode ghi riêng.
- cold/warm/cache arms là run ID riêng.
- retry chỉ transport/runtime, append mọi attempt; first-attempt primary, eventual secondary.

## Readiness gates

G0 SPEC_ACCEPTED → G1 BUILD_HARNESS_OFFLINE → G2 MERGED_VERIFIED → G3 SMOKE_AUTHORIZED → G4 LIVE_SMOKE per lane → G5 LANE_MEASUREMENT_READY → G6 FULL_RUN_AUTHORIZED → G7 MEASURED.

Merge/CI không cấp quyền paid smoke. G4 chỉ là live smoke; chỉ G5 được ghi `READY FOR MEASUREMENT` trong lane manifest sau khi evidence, completeness, budget và identity checks pass. Hai lane phải cùng đạt G5 mới được paired comparison.

## B01–B08 implementation backlog

| ID | Acceptance | Dependency | Status |
|---|---|---|---|
| B01 | grader routing/tool/owner/outcome/claim/safety adversarial | schema/taxonomy/fixture | BACKLOG |
| B02 | identity/fixture/focus/prior-turn sidecar idempotent | frozen JSONL/DB | BACKLOG |
| B03 | provider/config manifest + unavailable identity reasons | infrastructure | BACKLOG |
| B04 | cache OFF assertion, retry append, first/eventual/cumulative wait | schema/runner | BACKLOG |
| B05 | canonical writer/validator joins, counts, checksums, recomputation | schema/evidence | BACKLOG |
| B06 | qrels/claim labels/answerability/adjudication version/hash | corpus/annotation | BACKLOG |
| B07 | actual mode/model/tool/timing/cache/load measured or null | harness/telemetry | BACKLOG |
| B08 | PostgreSQL/pgvector/KB, quota/cap/stratified smoke/stop rule | infra/cost/fixture | BACKLOG |

## Phase 4A/4B

4A = harness/preflight + A0 quality baseline + decision; it is not blocked by OCR, multimodal, positive mutation, history or embedding/reranker ablation. 4B opens only after A0 evidence and a named bottleneck; each arm gets arm_id/config hash/raw artifacts and paired analysis.

## Maturity and upgrade decisions

Current maturity: runtime guarded pilot engineering; workflow prototype with rule/worker constraints; RAG experimental baseline using feature-hash-v1 384D; grounding provenance but no claim entailment; synthetic/persistent business data; OCR/vision not accepted; production readiness not established.

Upgrade only when evidence indicates root cause:

- embedding if qrels show candidate recall/paraphrase failure;
- reranker if candidate contains evidence but ranking fails;
- chunking if applicability/exception boundaries are cut;
- OCR/defect scanning only with labeled image/document set and field metrics;
- live POS/OMS/carrier only after system-of-record, freshness, identity mapping, idempotency and audit contract.

## Next action

Gemini receives the BUILD HARNESS prompt from PHASE_4_EXECUTION_HANDOFF.md. Work stops at offline acceptance/merge/reproduction until owner separately authorizes smoke. Current official status remains READY FOR HARNESS/PREFLIGHT.
