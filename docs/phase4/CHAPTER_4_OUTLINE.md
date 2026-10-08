# Chương 4 — Khung trình bày kết quả thực nghiệm

> Chương này trình bày kết quả Phase 4 trên frozen benchmark 250 ca. Nội dung chỉ kết luận trong điều kiện đã đo; không dùng để tuyên bố production readiness.

> **Publication gate:** Nếu chưa có đủ raw artifact/grader/qrels/fixture/telemetry theo `PHASE_4_EVIDENCE_CHECKLIST.md`, dùng mục “evidence status” và ghi `READY FOR HARNESS/PREFLIGHT`; không điền số giả và không ghi `READY FOR MEASUREMENT`.

## 4.1. Mục tiêu và câu hỏi nghiên cứu

- **RQ1:** Hệ thống hiện tại xử lý đúng outcome nghiệp vụ và safety trên 250 ca ở mức nào?
- **RQ2:** api-vllm-selfhost-v1 và api-reference-v1 khác nhau ra sao dưới cùng protocol?
- **RQ3:** Retrieval/grounding, latency, cost và concurrency tạo trade-off nào?
- **RQ4:** Thành phần nào cần nâng cấp trước: embedding, reranker, workflow, OCR hay dữ liệu live?

## 4.2. Hệ thống và phạm vi đánh giá

Mô tả luồng HTTP → session/identity → cache/replay → workflow/tool/model → evidence/citation → response. Ghi rõ PR A/B đã merge và Module 2.5 đã harden runtime; Phase 4 đánh giá chất lượng và hiệu năng, không mở rộng phạm vi sang production integration.

**Nguồn:** `PLAN_PHASE_4_EVALUATION.md`, `PLAN_DEEPSEEK_EVAL_FRAMEWORK.md`, `PHASE_4_INFRASTRUCTURE_SPEC.md`.

## 4.3. Dataset và protocol

Mô tả `benchmark_250.jsonl`: 250 ca, `dev=150`, `held_out=100`; category hiện tại: `order_lookup=65`, `product=35`, `policy=35`, `mixed=40`, `general=15`, `safety=60`. Nêu nguyên tắc frozen hash, không trộn qrels retrieval mới vào benchmark chính.

**Bảng nên có:** phân bố category × split, ví dụ ID và expected outcome.

**Nguồn:** `PHASE_4_TEST_MATRIX.md`, `PHASE_4_REPRODUCIBILITY.md`.

**Bắt buộc bổ sung trước khi kết luận:** bảng sidecar `case_id → scenario_family, tenant/principal/role, fixture, focus, prior_turns`, overlap report giữa dev/held-out và khai báo held-out exposure. Frozen JSONL không được sửa.

## 4.4. Metric và phương pháp chấm

Định nghĩa outcome success, routing accuracy, tool precision/recall, forbidden tool rate, retrieval Recall@k/MRR/nDCG, citation validity, claim support, abstention, latency, throughput, 429, fairness và cost.

**Bảng nên có:** công thức, mẫu số, cách xử lý timeout/skip và confidence interval.

**Nguồn:** `PHASE_4_METRICS_DEFINITION.md`, `PHASE_4_FAILURE_TAXONOMY.md`.

Phải báo riêng `N_total`, `N_graded`, `N_blocked`, quality conditional và end-to-end reliability; `SKIP`, timeout, 429, quota stop và `UNOBSERVED_TRACE` không được biến thành quality pass. Dùng `INCONCLUSIVE` khi thiếu power/evidence và `REJECTED` khi có hard safety veto.

## 4.5. Môi trường và khả năng tái lập

Ghi EC2/GPU/CPU/RAM, vLLM/provider, quantization, seed, model revision, prompt/protocol, DB/KB snapshot, cache mode, concurrency và network. Cung cấp command và manifest để tái chạy.

**Hình nên có:** sơ đồ pipeline evaluation và bảng cấu hình hai provider.

**Nguồn:** `PHASE_4_INFRASTRUCTURE_SPEC.md`, `PHASE_4_RESULTS_SCHEMA.md`, `PHASE_4_REPRODUCIBILITY.md`.

Mỗi bảng phải trỏ tới `manifest.json`, `system_commit_sha`, `evaluation_harness_sha`, provider lane/config hash, fixture/KB/index hash và cache/retry mode. Field không được adapter expose phải ghi `unavailable`, không điền cấu hình giả.

## 4.6. Baseline kết quả chính

Trình bày A0 trên toàn bộ benchmark và riêng held-out. Báo cáo point estimate kèm 95% CI, số ca hợp lệ, số timeout/skip, severe safety failures và taxonomy lỗi.

**Bảng/Hình:** scorecard, confusion matrix routing, category × outcome, waterfall lỗi.

Nếu grader/fixture/schema chưa đạt acceptance, thay scorecard bằng bảng **blocked evidence** và danh sách backlog; không suy chất lượng từ HTTP 200 hoặc offline routing score.

## 4.7. So sánh model/provider

So sánh api-vllm-selfhost-v1 với api-reference-v1 trên cùng ca, prompt, tool contract và grader chỉ khi cả hai lane đạt G4/G5. Phase 4A vẫn đo A0 từng lane; paired provider comparison/A4 là 4B optional nếu một lane bị block. Tách chất lượng nghiệp vụ, grounding/safety, latency và cost; không xếp hạng tuyệt đối ngoài miền benchmark.

**Bảng/Hình:** paired delta, CI plot, P50/P95/P99, cost per successful case.

## 4.8. Retrieval và grounding

Phân tích candidate retrieval, ranking, chunking, citation validity và claim-level support. Chỉ đề xuất multilingual embedding/reranker khi lỗi baseline cho thấy đúng nguyên nhân.

**Bảng/Hình:** Recall@k/MRR/nDCG, failure taxonomy RAG, ví dụ policy claim được hỗ trợ/không hỗ trợ.

**Nguồn:** `PHASE_4_ABLATION_STUDY.md`, `PHASE_4_FAILURE_TAXONOMY.md`.

Qrels/claim labels và corpus/index snapshot là deliverable bắt buộc cho mọi con số Recall/MRR/nDCG/claim support. Tách candidate Recall@k trước filter khỏi served-evidence coverage sau budget; query no-evidence ghi N/A hoặc metric riêng.

## 4.9. Hiệu năng và concurrency

Trình bày các mức concurrency `1/2/4/8/16`, queue wait, provider inference, E2E latency, throughput, 429 và Jain's Fairness Index. Tách cold/warm cache và giải thích headroom HTTP/gate.

**Bảng/Hình:** latency percentile plot, throughput curve, 429/error breakdown, wait-time dispersion.

## 4.10. Cost và vận hành

Tách EC2/GPU-hour, API token cost, storage/egress nếu có; quy đổi cost/case và cost/successful outcome. Nêu các biến động provider price hoặc spot interruption.

**Nguồn:** `PHASE_4_COST_BUDGET.md`, `PHASE_4_RISK_REGISTER.md`.

## 4.11. Ablation và quyết định nâng cấp

Trình bày A0 và các arm đã chạy (cache, history, provider, retrieval/embedding/reranker nếu có). Dùng paired delta và safety gate. Kết quả phải trả lời component nào nên giữ, thay, hoặc hoãn.

**Bảng/Hình:** ablation matrix, quality–latency–cost frontier, decision record.

**Nguồn:** `PHASE_4_ABLATION_STUDY.md`.

Chia rõ **Phase 4A (A0 baseline + decision)** và **Phase 4B (targeted ablation)**. Chỉ trình bày arm có raw artifact và acceptance evidence; arm chưa chạy ghi `DESIGNED/BLOCKED`, không tạo cột điểm rỗng. A3 chỉ được báo cáo khi có prior-turn sidecar; cache ablation phải tách application Semantic Cache khỏi ToolCache/DB/model cache.

## 4.12. Threats to validity và giới hạn

Nêu internal/external validity, benchmark synthetic, provider drift, thiếu live POS/OMS, multimodal/OCR chưa được đánh giá đầy đủ, giới hạn hardware và thời gian chạy. Phân biệt rõ bằng chứng L2/L3/L4.

**Nguồn:** `PHASE_4_THREATS_TO_VALIDITY.md`, `PHASE_4_EVIDENCE_CHECKLIST.md`.

Nêu cụ thể artifact cho leakage/template overlap, held-out exposure, cluster dependence, selective availability, fixture/identity mismatch, grader/schema failure và budget/quota stopping. Gate OCR/vision hoặc distributed concurrency chỉ áp dụng nếu feature/topology đó nằm trong deployment scope.

## 4.13. Kết luận chương

Kết luận theo RQ1–RQ4 bằng số liệu đã đo. Chỉ nói “trong benchmark/điều kiện X”. Nêu quyết định tiếp theo: giữ baseline, chạy A/B embedding/reranker, chuẩn bị OCR/live data, hoặc hoãn vì chưa đủ evidence. Không dùng câu “đã production-ready” nếu chưa có bằng chứng L4 và các gate vận hành riêng.

## 4.14. Phụ lục artifact

Liệt kê run manifest, raw JSONL, metrics, taxonomy, environment, commands, hash và link artifact. Mỗi bảng/hình trong Chương 4 phải truy ngược được tới một file raw và một commit/dataset SHA.

## 4.15. Bảng trạng thái bằng chứng (bắt buộc trước khi viết kết luận)

| Nhóm | Trạng thái được phép | Bằng chứng tối thiểu |
|---|---|---|
| Harness/grader/fixture/qrels/telemetry | `BACKLOG`, `IN_PROGRESS`, `PASS`, `BLOCKED` | Acceptance checks từ `PHASE_4_EVIDENCE_CHECKLIST.md` |
| Phase 4A A0 baseline | `DESIGNED`, `READY FOR HARNESS/PREFLIGHT`, `MEASURED` | Manifest + raw attempts + grading + metrics + taxonomy |
| Phase 4B ablation | `DESIGNED`, `MEASURED`, `REJECTED`, `INCONCLUSIVE` | Arm manifest, paired analysis, safety gate, artifact hashes |
| Production/pilot claim | `OUT OF SCOPE` hoặc `NOT ESTABLISHED` | L4/live data/SLO/rollback evidence; không suy từ 250 ca |

Kết luận chỉ được viết cho hàng có trạng thái `MEASURED` và artifact truy nguyên được. Nếu bất kỳ P1 hoặc gate M01/M02/M03/M05/M06 còn `BACKLOG/BLOCKED`, phần kết luận phải nói rõ **chưa sẵn sàng đo chính thức**.

### Bảng ánh xạ nhanh

| Phần | Metric/đầu ra chính | Tài liệu nguồn |
|---|---|---|
| 4.3 | Category/split, expected outcome | `PHASE_4_TEST_MATRIX.md` |
| 4.4 | Công thức và CI | `PHASE_4_METRICS_DEFINITION.md`, `PHASE_4_STATISTICAL_ANALYSIS.md` |
| 4.5 | Environment/seed/model | `PHASE_4_INFRASTRUCTURE_SPEC.md`, `PHASE_4_REPRODUCIBILITY.md` |
| 4.6–4.7 | Outcome, routing, provider comparison | `PHASE_4_RESULTS_SCHEMA.md`, raw results |
| 4.8 | Recall/MRR/nDCG/grounding | `PHASE_4_ABLATION_STUDY.md`, retrieval traces |
| 4.9 | P50/P95/P99, throughput, 429, fairness | `PHASE_4_METRICS_DEFINITION.md`, concurrency samples |
| 4.10 | GPU/API cost | `PHASE_4_COST_BUDGET.md` |
| 4.11 | Component contribution | `PHASE_4_ABLATION_STUDY.md` |
| 4.12 | Validity limits/evidence level | `PHASE_4_THREATS_TO_VALIDITY.md`, `PHASE_4_EVIDENCE_CHECKLIST.md` |
