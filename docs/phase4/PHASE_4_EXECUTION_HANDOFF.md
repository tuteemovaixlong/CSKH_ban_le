# Phase 4 Scientific Evaluation — Execution Handoff

> Cập nhật bàn giao: 2026-10-08
> Baseline bắt buộc: main / 49671b928ad6badfaa01331174eb73f0e366752e
> Trạng thái: READY FOR HARNESS/PREFLIGHT — chưa đủ bằng chứng đo chính thức; không phải production approval.

> Review hiện hành: [REVIEW_GEMINI_PHASE4_2026-10-07.md](REVIEW_GEMINI_PHASE4_2026-10-07.md); [plan thực thi](PLAN_REVIEW_HANDOFF_GEMINI_2026-10-07.md). HEAD `48b84cd3e265f7852f87e94cecee04a52499eaa3`: B1–B6 cũ đã VERIFIED DONE; 563 tests chạy/49 skipped, 58 Phase 4 + 9 guard PASS; CI/Docker thật xanh. N1–N5 còn mở, chưa merge.

> Công việc tiếp theo: Gemini sửa N1 provenance, N2 case/schedule, N3 blocked denominator, N4 malformed safety telemetry, N5 preflight readiness và L1–L4 theo review. R13 DONE OFFLINE/CI; R10/R11/R12 chưa đạt acceptance đầy đủ. Sau sửa/CI mới dừng owner review.

## 1. Mục tiêu và ranh giới

Bàn giao cho Gemini Antigravity BUILD HARNESS để tạo bằng chứng tái lập được trên hai frozen benchmark 250 ca và tải 1/2/4/8/16. Không sửa runtime business behavior, prompt, RBAC hoặc frozen inputs trong lượt build harness. Harness, fixture sidecar, grader, writer, validator và telemetry là evaluation tooling; mọi evaluation overlay phải có hash riêng và không được gọi là baseline runtime.

Phase 4A gồm offline acceptance, A0 quality protocol, lane preflight và decision về bottleneck. Phase 4B là ablation có điều kiện sau A0. OCR, multimodal, positive mutation, live POS/OMS và embedding/reranker upgrade không khóa Gate 4A.

## 2. Identity sau merge

Mọi manifest và artifact phải ghi đủ:

- system_commit_sha: runtime revision;
- evaluation_harness_sha: merged harness revision;
- evaluation_overlay_sha256: evaluation-only instrumentation/controller, hoặc none khi không có overlay;
- config_sha256, prompt/protocol/grader versions;
- dataset, fixture, KB, qrels hashes;
- lane_id, provider_id, endpoint_type, model/checkpoint/revision và sampling thực tế.

provider_id custom dùng RemoteAgent protocol /agent/identity và /agent/chat. Self-hosted vLLM OpenAI-compatible phải chạy qua provider_id api với endpoint cấu hình, hoặc có bridge /agent/* được pin thành dependency riêng. Không tự đổi adapter trong BUILD HARNESS.

## 3. Canonical gate flow

~~~text
G0 SPEC_ACCEPTED
  → G1 BUILD_HARNESS_OFFLINE (mock/adversarial, no network/no paid cost)
  → G2 MERGED_VERIFIED (CI + clean-checkout replay + frozen hashes)
  → G3 SMOKE_AUTHORIZED (approval, quota, price/cap, stop rule)
  → G4 LIVE_SMOKE per lane (stratified dev IDs + real endpoint/DB/KB)
  → G5 LANE_MEASUREMENT_READY
  → G6 FULL_RUN_AUTHORIZED (separate approval/cap)
  → G7 MEASURED / BASELINE_ACCEPTED
~~~

Merge hoặc CI không tự cấp quyền chạy paid/cloud. G4 chỉ là `LIVE_SMOKE`; **G5 là gate duy nhất** được ghi `READY FOR MEASUREMENT` trong manifest của lane. Tài liệu này vẫn `READY FOR HARNESS/PREFLIGHT` cho tới khi có evidence.

## 4. Trình tự giao việc

1. Chọn checkout sạch ở baseline và chạy local contract checks.
2. Implement B01–B08 bằng mock/offline fixtures; không gọi network.
3. Emit canonical bundle: manifest.json, attempts.jsonl, grading.jsonl, retrieval.jsonl, errors.jsonl, aggregate.json, checksums.sha256.
4. Chạy adversarial acceptance: malformed 200, 429/timeout retry, missing/forbidden tool, wrong owner, no-evidence, missing metadata và corrupted artifact.
5. Mở PR harness; chạy CI và clean-checkout replay; ghi system/harness/overlay tuple. Không tự merge.
6. Xin approval smoke riêng cho từng lane; chạy stratified dev smoke, không dùng held_out để tune.
7. Chỉ sau G5 mới được xin full-run approval và chạy 250 ca. G4 không tự cấp readiness; first attempt là primary; eventual retry là secondary.
8. Phân loại mọi skip/block/error và tái tính aggregate từ raw.

## 5. Backlog và acceptance

| ID | Acceptance check | Dependency | Status |
|---|---|---|---|
| B01 | Grader bắt missing/forbidden/wrong-owner/unsupported-claim và safety severity | schema, taxonomy, fixtures | PARTIAL — safety ordering/empty-string/ref fixes DONE; N4 malformed safety trace và L1 null text còn mở |
| B02 | Sidecar map case → identity/fixture/focus/prior turns, setup idempotent | frozen JSONL, DB snapshot | OFFLINE IMPLEMENTED — sidecar 250 có; N1 source/hash binding và live fixture chưa nghiệm thu |
| B03 | Lane manifest ghi adapter/endpoint/model/sampling và unavailable reasons | infrastructure | PARTIAL — immutable SHA/strict preflight typing DONE; N1 coherence và N5 readiness còn mở; live identity chưa nghiệm thu |
| B04 | Quality answer-cache OFF được assert; retry append từng attempt; first/eventual/cumulative wait tính được | schema, runner | PASS OFFLINE CONTROLLER — cache OFF/retry append có; N2/N3 primary selection/denominator còn mở |
| B05 | Writer/validator kiểm join keys, counts, checksums, aggregate recomputation | results schema | BLOCKED — rate/non-finite/flag fixes DONE; N1/N2/N3 và CLI còn mở |
| B06 | Qrels/claim labels/answerability/adjudication version/hash | corpus/annotation | PARTIAL — qrels/labels offline có; N1 source fail-closed và live annotation chưa nghiệm thu |
| B07 | Actual mode/model/tool/timing/cache/load IDs measured hoặc null | harness/instrumentation | PASS OFFLINE MOCK — measured-zero/non-finite checks có; N4 tool/safety typing còn mở; chưa phải live evidence |
| B08 | PostgreSQL/pgvector/KB, quota, smoke selector, cap/stop rule pass | infra, cost | BACKLOG — live DB/KB/lane quota/smoke/cap chưa authorize/nghiệm thu |

### R13 — deployment guard bắt buộc trong cùng PR

Workflow deploy đã có guard reviewable dựa trên **changed files thực tế**: eval-only/harness-only merge không deploy; mixed eval + runtime giữ policy deploy; `workflow_dispatch` giữ nguyên; unknown path fail-closed. Không hardcode thư mục harness, không ignore rộng toàn `scripts/`, `.github/` hoặc `Dockerfile`, không đổi repo variables và không tắt deploy toàn cục. R13 **DONE OFFLINE/CI** ở HEAD review: 9 guard tests, Docker build và packaged checks PASS. Toàn diff baseline→HEAD hiện trả `deploy_eligible=true` vì `.dockerignore`, `Dockerfile`, `scripts/check_deployment_contract.py`. Đây là mixed packaging/evaluation; merge có thể deploy theo variable/policy hiện hữu. Chưa kiểm/thay variables, chưa deploy; không ghi PR #36 eval-only hoặc luôn deploy-skipped.

## 6. Điều kiện dừng

Dừng trước smoke nếu G1 hoặc G2 fail. Dừng trước full run nếu lane thiếu identity, fixture/DB/KB, cache/retry assertion, quota/price approval hoặc raw validator. Không biến HTTP 200, mock response, CPU-only run, merge commit hoặc CI xanh thành quality evidence. Dừng merge nếu N1–N5 chưa đóng, CLI/response robustness chưa xử lý hoặc CI không xanh trên HEAD mới. Báo R13 eligibility theo diff thực tế cho owner trước merge.

## 7. Report bắt buộc

Report phải có run_id, system/harness/overlay identities, dataset and fixture hashes, lane config, raw artifact links/checksums, first/eventual metrics, denominator/CI, failure taxonomy, cost/quota events, threats to validity và decision. Không dùng production-ready hoặc BASELINE ACCEPTED khi chưa đạt gate tương ứng.
