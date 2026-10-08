# Phase 4 — Infrastructure Specification

**Status (2026-10-08):** READY FOR HARNESS/PREFLIGHT — offline harness/CI/Docker đã có ở HEAD `48b84cd`; N1–N5 còn mở, chưa merge/G2 hoặc live measurement gate.
**Scope:** scientific evaluation only. Không authorize production deploy, model replacement, schema migration, paid API hoặc cloud provisioning.

## 1. Identity và status

- system_commit_sha: 49671b928ad6badfaa01331174eb73f0e366752e (runtime under test).
- evaluation_harness_sha: TBD cho tới khi runner/fixture/grader/writer/validator merge và được hash.
- evaluation_overlay_sha256: hash evaluation-only instrumentation/config; dùng giá trị none khi không có overlay, không để trống.
- frozen benchmark: benchmark_250.jsonl và master_250_v1.jsonl; mỗi file phải ghi hash riêng dù hiện cùng LF hash 36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411.
- G4 chỉ là live smoke. Chỉ G5 được ghi `READY FOR MEASUREMENT` trong lane/run manifest sau khi G4 evidence, completeness, budget và identity checks pass; tài liệu không tự chuyển trạng thái.

## 2. Adapter facts và topology canonical

Code hiện có hai selection:

| Lane | Runtime fact | Phase 4 topology | Required preflight |
|---|---|---|---|
| api-reference-v1 | OpenRouterAgent hoặc configured OpenAI-compatible API endpoint | provider_id=api, endpoint/model do manifest pin | response model/usage, timeout, tool-call IDs, rate-limit identity |
| api-vllm-selfhost-v1 | cùng provider_id=api qua RETAILOPS_API_ENDPOINT trỏ /v1 của vLLM | OpenAI-compatible vLLM /v1/chat/completions; model served ID và checkpoint pin riêng | health/startup, endpoint response, model ID, tokenizer/template/checkpoint/image hashes |
| custom-legacy-v1 | RemoteAgent dùng /agent/identity và /agent/chat | chỉ dùng khi endpoint thực sự cung cấp /agent/* hoặc bridge pinned | protocol handshake, bridge revision, request/response capture |

Không gọi custom-selfhost-v1 là vLLM trực tiếp. Nếu chọn bridge /agent/*, bridge là dependency riêng, có revision/hash và topology variant; không được coi là A0 runtime unchanged.

provider_id không phải vendor/model identity. Manifest bắt buộc ghi lane_id, provider_id, adapter, endpoint_type, endpoint host redacted, provider/vendor, model_id, model_revision, checkpoint_digest, tokenizer_digest, chat_template_digest, serving_image_digest và identity_unavailable_reason nếu field không expose. Mismatch provider/endpoint/model là BLOCKED; proprietary revision không expose chỉ làm giảm reproducibility và phải ghi limitation.

## 3. Sampling/config contract

Current code facts phải được ghi đúng:

- custom RemoteAgent: temperature 0.2 và seed 42 nếu payload thực tế gửi như vậy;
- api adapter: max_tokens 2048, temperature 0.2; top_p/seed chỉ ghi khi request capture chứng minh đã gửi.

Không tự ghi temperature 0, top_p 1 hoặc seed 42/43/44 như cấu hình hiện tại. Mọi config variant có config_sha256 mới.

## 4. Runtime flow và concurrency

Quality request: HTTP admission → session/identity → cache assertion/lookup → workflow/tools → provider adapter → response → raw writer. Ghi riêng HTTP admission, conv_lock và InferenceGate; baseline inference gate không đồng nghĩa nhiều model calls đồng thời.

Load levels 1/2/4/8/16 là client concurrency. K/Q/deadline của InferenceGate, Waitress headroom và vLLM scheduler là các trục riêng, không gộp thành một con số capacity.

## 5. Cache và retry

- A0 quality: semantic answer-cache read/write OFF ở cả hai lane; harness phải assert effective state trước case đầu tiên và fail preflight nếu không chứng minh được.
- ToolCache mode ghi off/fresh-tenant/enabled; quality dùng tenant/conversation mới, mọi hit chéo case là contamination.
- cold/warm/cache ablation chạy run_id riêng, có warm-up/population/reset.
- retry chỉ transport/runtime failure theo retry_policy_id; raw attempts append, giữ first outcome, eventual outcome, backoff và cumulative wait.

## 6. Candidate infrastructure

| Lane | Candidate | Evidence trước paid/GPU |
|---|---|---|
| Control plane | existing t3.large hoặc runner tương đương | ownership/lifecycle rõ; không tự stop shared public host |
| Self-hosted | AWS g6.xlarge/L4-class 24 GB hoặc approved Colab L4 | nvidia-smi, driver/CUDA, VRAM, model load, endpoint smoke |
| CPU contract | CPU-only | chỉ schema/grader/writer/offline evidence; không publish GPU latency |

Hardware/price là TBD cho tới khi owner approval. GPU preflight không authorize run; G4 live smoke cũng chưa phải G5 measurement readiness.

## 7. PostgreSQL/KB preflight

Lane có RAG phải kết nối isolated PostgreSQL/pgvector snapshot, business schema v4, identity schema v4, vector(384), corpus/index hash và một retrieval evidence pass. SQLite business schema v3 chỉ dùng contract subset, không thay cho PostgreSQL RAG evidence. Fixture identity/tenant must be hashed and synthetic.

## 8. Gate-specific checks

- G1 offline: no network, no paid cost, mock provider.
- G2 merged verified: CI PASS, clean checkout replay, frozen hashes, identity tuple.
- G3 smoke authorized: explicit approval ID, price/quota cap, stop rule.
- G4 live smoke: stratified dev IDs per lane, actual endpoint/DB/KB, cache/retry assertion.
- G5 lane measurement ready: **gate duy nhất** cho `READY FOR MEASUREMENT`; smoke artifacts valid, no fallback/mismatch, completeness and budget checks.
- G6 full-run authorized: separate approval/cap and preregistered workload.

## 9. Infrastructure backlog

| ID | Acceptance check | Status |
|---|---|---|
| H01 | adapter topology/response identity/tool-call/timeout preflight | PARTIAL MOCK — manifest có; live adapter/endpoint identity chưa nghiệm thu |
| H02 | cache OFF and retry append controller | PASS OFFLINE CONTROLLER — cache OFF/retry append; N2/N3 acceptance còn mở |
| H03 | fixture/identity/sidecar and PostgreSQL/pgvector/KB preflight | PARTIAL — sidecar offline có/N1 binding mở; live PostgreSQL/KB fixture preflight chưa nghiệm thu |
| H04 | canonical writer/validator and checksums | PARTIAL — canonical bundle/checksums có; N1/N2/N3/L2 acceptance còn mở |
| H05 | quota/cost ledger and smoke/full approval separation | BACKLOG — quota/price cap và live authorization evidence chưa có |
| H06 | clean-checkout replay with system/harness/overlay tuple | PASS BRANCH OFFLINE/CI — tuple ghi đúng HEAD; coherence N1 mở; G2 merged replay chưa có |

Until H01–H06 have evidence, status remains READY FOR HARNESS/PREFLIGHT.
