# PLAN_PHASE_4_EVALUATION — Scientific Evaluation

> **Merge policy owner chốt 2026-10-08:** [Acceptance v1](PHASE_4_ACCEPTANCE_CRITERIA.md): đúng8check; N1 manifest mutation/N3 denominator/N4 safety types DONE trong scope v1. [Evidence HEAD 8a666fc](PHASE_4_ACCEPTANCE_EVIDENCE_8a666fc.md): K1–K8/C1–C6 PASS, independent sign-off PENDING. Checklist kỹ thuật đạt theo packet; chờ nguồn độc lập xác minh và ký 8/8 → owner review → merge → G2. N1 replay/counts/tool-name semantics, L2/L4/L5 và việc ngoài checklist → [Phase5 backlog](PHASE_5_BACKLOG.md), không block merge. Findings/progress lịch sử bên dưới không mở thêm merge gate.

> **Trạng thái (2026-10-08):** READY FOR HARNESS/PREFLIGHT. HEAD `8a666fc` đạt K1–K8/C1–C6: CI5 success, mock250 PASS, patch whitespace clean; local full-suite rerun has timing variance. K7/C6 PASS trên patch merge; 5 EOF blank lines đã được loại bỏ; independent sign-off PENDING. N1 replay/counts/tool-name semantics vào Phase5, không block merge; chưa merge/G2/live.
> **Mốc code:** main tại 49671b928ad6badfaa01331174eb73f0e366752e.
> **Phạm vi lượt này:** review implementation của Gemini; giữ nguyên runtime và hai frozen benchmark.

## 1. Mục tiêu và phạm vi

Phase 4 đo ba lớp bằng chứng trên master_250_v1.jsonl và mirror benchmark_250.jsonl (250 ca, dev=150, held_out=100):

1. runtime correctness: routing, tool contract, owner scope, safety và HTTP outcome;
2. LLM/RAG quality: outcome, grounding, retrieval, abstain/clarify;
3. operational performance: latency, throughput, concurrency, 429, queueing, model calls và cost.

OCR/vision defect scanning, summarization, live POS/OMS/carrier integration và production GraphRAG là các workstream sau Phase 4. Không đổi prompt, embedding, chunking, reranker và model trong cùng một cell.

## 2. Canonical identities

Mỗi run phải pin:

- system_commit_sha: runtime revision được đo;
- evaluation_harness_sha: runner/fixture/grader/writer/validator revision;
- evaluation_overlay_sha256: hash của evaluation-only controller/instrumentation, hoặc none khi không có overlay;
- dataset/fixture/KB/qrels/config/prompt hashes;
- lane_id, provider_id, endpoint_type, model/checkpoint/revision, sampling thực tế.

provider_id=custom chỉ có nghĩa runtime tạo RemoteAgent với /agent/identity và /agent/chat. vLLM OpenAI-compatible dùng provider_id=api qua endpoint được cấu hình; self-hosted và API reference khác nhau bằng lane_id, endpoint, model và manifest. Không gọi custom là vLLM trực tiếp nếu chưa có bridge /agent/* được pin.

## 3. Protocol chuẩn

- Quality A0: application semantic answer-cache đọc/ghi OFF ở cả hai lane; ToolCache mode ghi riêng; tenant/conversation mới cho mỗi case.
- Load/cache arms: load_cold, load_warm, ablation_on, ablation_off là run ID riêng; warm-up, population và reset phải ghi trong manifest.
- Retry: chỉ retry transport/runtime errors theo retry_policy_id; append mọi attempt; primary quality dùng first attempt; eventual outcome và cumulative wait là secondary. Không rerun câu trả lời sai để tăng điểm.
- Fixture/identity: sidecar immutable case_id → scenario_family, tenant, principal, role, fixture_ref, focus, prior_turns; hash trong manifest.
- Raw bundle: manifest.json, attempts.jsonl, grading.jsonl, retrieval.jsonl, errors.jsonl, aggregate.json, checksums.sha256 theo PHASE_4_RESULTS_SCHEMA.md.

## 4. Gating flow

~~~text
G0 SPEC_ACCEPTED
  → G1 BUILD HARNESS OFFLINE (mock/adversarial, no network/paid cost)
  → G2 MERGED_VERIFIED (CI + clean-checkout replay + frozen hashes)
  → G3 SMOKE_AUTHORIZED (explicit owner approval, quota/price/cap)
  → G4 LIVE_SMOKE per lane (stratified dev IDs, real endpoint/DB/KB)
  → G5 LANE_MEASUREMENT_READY
  → G6 FULL_RUN_AUTHORIZED (separate approval/cap)
  → G7 MEASURED / BASELINE ACCEPTED
~~~

Merge/CI không cấp quyền paid smoke. Một lane bị block không làm lane khác được coi là đã so sánh. G4 chỉ chứng minh live smoke; **chỉ G5** mới được ghi `READY FOR MEASUREMENT` trong lane/run manifest sau khi G4 evidence hợp lệ và completeness/budget/identity checks pass. Tài liệu này không tự chuyển trạng thái.

## 5. Phase 4A và 4B

**Phase 4A — baseline + decision** bắt buộc: B01/B02/B03/B04/B05/B06/B07/B08, A0 quality, offline acceptance, lane preflight và decision về bottleneck. 4A không bị khóa bởi OCR, positive mutation, multi-turn history hoặc embedding/reranker ablation.

**Phase 4B — targeted ablation** mở có điều kiện khi A0 có evidence: cache/history arms, retrieval/embedding/reranker, provider comparison, multimodal/OCR hoặc live-data supplementary suite. Arm chưa chạy ghi DESIGNED hoặc BLOCKED, không đưa điểm rỗng vào scorecard.

## 6. Metrics và decision

Primary outcome là first-attempt trên logical cases:

- first_attempt_success_rate = (pass + abstain_correct) / N_total;
- quality_conditional = (first-attempt pass + first-attempt abstain_correct) / N_graded_first;
- e2e_success và eventual_success báo riêng;
- forbidden_tool_rate, owner/privacy violation và unsupported mutation là hard safety veto;
- retrieval dùng qrels riêng; no-evidence có denominator/N/A riêng;
- latency/load báo p50/p95/p99, throughput, queue wait, 429, fairness, cost.

CI, denominator, blocked/missing và rubric version phải đi cùng mọi metric. Rubric có anchors 0/1/2, provider-blind grading, adjudication và safety veto.

## 7. Implementation backlog trước measurement

| ID | Acceptance check | Dependency | Status |
|---|---|---|---|
| B01 | Grader bắt missing/forbidden/wrong-owner/unsupported-claim và safety severity | schema, taxonomy, fixtures | DONE OFFLINE K3 TYPES — safety type gate PASS tại 8a666fc; L1/order fixes DONE; semantic evidence backlog |
| B02 | Sidecar resolve identity/fixture/focus/prior turns idempotently | frozen JSONL, DB snapshot | OFFLINE IMPLEMENTED — sidecar/hash có; actual-source replay hardening deferred P5-01; live chưa nghiệm thu |
| B03 | Manifest ghi adapter/endpoint/model/sampling và unavailable reasons | infrastructure, reproducibility | PASS OFFLINE GUARD — SHA/coherence/mock deny DONE; live identity/evidence workstream sau |
| B04 | Cache OFF được assert; từng attempt append; first/eventual/cumulative wait tính được | schema, runner | PASS OFFLINE — cache/retry/scheduling/quality denominator DONE; completeness backlog P5-02 |
| B05 | Canonical writer/validator pass join keys, counts, checksums, aggregate recomputation | schema, evidence | ACCEPTABLE v1 SCOPE — canonical/coherence/hash mutation DONE; replay/counts backlog; K7/C6 PASS và independent sign-off PENDING |
| B06 | Qrels/claim labels/answerability/adjudication có version/hash | corpus snapshot, annotation | PASS VALIDATOR SOURCE PIN — CLI improvements L2 backlog, không block merge; live annotation sau |
| B07 | Actual mode/model/tool/timing/cache/load IDs measured hoặc null | harness/instrumentation | PASS OFFLINE MODEL TELEMETRY/K3 TYPES — live measurements chưa chạy |
| B08 | PostgreSQL/pgvector/KB, quota, smoke selector, hard cap và stop rule pass | infra, cost, fixtures | FUTURE LIVE — DB/KB/quota/smoke/cap không block harness merge v1 |

Bảng trên phân biệt implementation offline đã có với acceptance còn thiếu; không ghi các mục đã có là BACKLOG toàn bộ. Gemini tiếp tục theo PLAN_REVIEW_HANDOFF_GEMINI_2026-10-07.md. Status chính thức vẫn READY FOR HARNESS/PREFLIGHT.

## 8. Deliverables và kết luận

Canonical owner là các file trong docs/phase4/. PHASE_4_EXECUTION_HANDOFF.md là entry point cho Gemini BUILD HARNESS. Chỉ dùng SUPPORTED, INCONCLUSIVE hoặc REJECTED sau khi artifact/raw/grader/CI/statistics đủ. Không dùng production-ready từ benchmark này.
