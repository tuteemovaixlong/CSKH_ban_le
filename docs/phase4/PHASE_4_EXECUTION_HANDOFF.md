# Phase 4 Scientific Evaluation — Execution Handoff

> **Post-merge handoff (2026-10-09):** PR #36 đã merge tại `8868c5c498b1c64241bc791eb0166d82415cfeb0`. EC2 deployment đã cập nhật đúng image và các container healthy. G4 smoke chưa đạt: report `/opt/retailops/e2e-reports/LIVE_SMOKE_20261009T132840Z.json` dừng tại `customer_reserved` cho `e2e-live-smoke/C-001`. Phase 4 dừng ở đây; workstream tiếp theo là [Phase 5](../phase5/PHASE_5_EXECUTION_HANDOFF.md). Không ghi G5/readiness và không chạy full measurement.

> **Merge policy owner chốt 2026-10-08:** [Acceptance v1](PHASE_4_ACCEPTANCE_CRITERIA.md): đúng8check; N1 manifest mutation/N3 denominator/N4 safety types DONE trong scope v1. [Evidence HEAD 8a666fc](PHASE_4_ACCEPTANCE_EVIDENCE_8a666fc.md): K1–K8/C1–C6 PASS, independent sign-off PENDING. Checklist kỹ thuật đạt theo packet; chờ nguồn độc lập xác minh và ký 8/8 → owner review → merge → G2. N1 replay/counts/tool-name semantics, L2/L4/L5 và việc ngoài checklist → [Phase5 backlog](PHASE_5_BACKLOG.md), không block merge. Findings/progress lịch sử bên dưới không mở thêm merge gate.

> Cập nhật bàn giao: 2026-10-08
> Baseline bắt buộc: main / 49671b928ad6badfaa01331174eb73f0e366752e
> **Trạng thái (2026-10-08):** READY FOR HARNESS/PREFLIGHT. HEAD `8a666fc` đạt K1–K8/C1–C6: CI5 success, mock250 PASS, patch whitespace clean; local full-suite rerun has timing variance. K7/C6 PASS trên patch merge; 5 EOF blank lines đã được loại bỏ; independent sign-off PENDING. N1 replay/counts/tool-name semantics vào Phase5, không block merge; chưa merge/G2/live.

> Review hiện hành: [review](REVIEW_GEMINI_PHASE4_2026-10-07.md), [plan](PLAN_REVIEW_HANDOFF_GEMINI_2026-10-07.md), [evidence](PHASE_4_ACCEPTANCE_EVIDENCE_8a666fc.md). Frozen HEAD `8a666fcce464c96b1dd5fc6848a2d4168c6505d1`: 5 CI checks SUCCESS; Gemini báo full suite 575 tests OK/49 skipped; mock250/263, quality185/237. Local full suite có 1 timing failure; xem packet. Independent sign-off PENDING; chưa merge.

> Technical closure đã xong. Giao packet cho model khác/human mới chưa tham gia N1–N5 xác minh đúng 8 mục và ký; sau đó owner review → merge → G2 offline. N1 replay/N3 counts/N4 semantics và L2/L4/L5 giữ Phase 5 backlog.

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
| B01 | Grader bắt missing/forbidden/wrong-owner/unsupported-claim và safety severity | schema, taxonomy, fixtures | DONE OFFLINE K3 TYPES — safety type gate PASS tại 8a666fc; L1/order fixes DONE; semantic evidence backlog |
| B02 | Sidecar map case → identity/fixture/focus/prior turns, setup idempotent | frozen JSONL, DB snapshot | OFFLINE IMPLEMENTED — sidecar/hash có; actual-source replay hardening deferred P5-01; live chưa nghiệm thu |
| B03 | Lane manifest ghi adapter/endpoint/model/sampling và unavailable reasons | infrastructure | PASS OFFLINE GUARD — SHA/coherence/mock deny DONE; live identity/evidence workstream sau |
| B04 | Quality answer-cache OFF được assert; retry append từng attempt; first/eventual/cumulative wait tính được | schema, runner | PASS OFFLINE — cache/retry/scheduling/quality denominator DONE; completeness backlog P5-02 |
| B05 | Writer/validator kiểm join keys, counts, checksums, aggregate recomputation | results schema | ACCEPTABLE v1 SCOPE — canonical/coherence/hash mutation DONE; replay/counts backlog; K7/C6 PASS và independent sign-off PENDING |
| B06 | Qrels/claim labels/answerability/adjudication version/hash | corpus/annotation | PASS VALIDATOR SOURCE PIN — CLI improvements L2 backlog, không block merge; live annotation sau |
| B07 | Actual mode/model/tool/timing/cache/load IDs measured hoặc null | harness/instrumentation | PASS OFFLINE MODEL TELEMETRY/K3 TYPES — live measurements chưa chạy |
| B08 | PostgreSQL/pgvector/KB, quota, smoke selector, cap/stop rule pass | infra, cost | FUTURE LIVE — DB/KB/quota/smoke/cap không block harness merge v1 |

### R13 — deployment guard bắt buộc trong cùng PR

Workflow deploy đã có guard reviewable dựa trên **changed files thực tế**: eval-only/harness-only merge không deploy; mixed eval + runtime giữ policy deploy; `workflow_dispatch` giữ nguyên; unknown path fail-closed. Không hardcode thư mục harness, không ignore rộng toàn `scripts/`, `.github/` hoặc `Dockerfile`, không đổi repo variables và không tắt deploy toàn cục. R13 **DONE OFFLINE/CI**: evidence lịch sử ở HEAD `04ed899` gồm9 guard tests và exact-head offline CI success; CI5 tại HEAD `8a666fc` cũng success; Docker build/packaged checks là các bước bắt buộc của workflow. Toàn diff baseline→HEAD hiện trả `deploy_eligible=true` vì `.dockerignore`, `Dockerfile`, `scripts/check_deployment_contract.py`. Đây là mixed packaging/evaluation; merge có thể deploy theo variable/policy hiện hữu. Chưa kiểm/thay variables, chưa deploy; không ghi PR #36 eval-only hoặc luôn deploy-skipped.

## 6. Điều kiện dừng

Dừng trước smoke nếu G1 hoặc G2 fail. Dừng trước full run nếu lane thiếu identity, fixture/DB/KB, cache/retry assertion, quota/price approval hoặc raw validator. Không biến HTTP 200, mock response, CPU-only run, merge commit hoặc CI xanh thành quality evidence. Dừng merge chỉ khi K1–K8 chưa PASS hoặc thiếu independent sign-off/owner review theo acceptance v1. L2/L4/L5/backlog không chặn merge. Báo R13 eligibility theo diff thực tế cho owner trước merge.

## 7. Report bắt buộc

Report phải có run_id, system/harness/overlay identities, dataset and fixture hashes, lane config, raw artifact links/checksums, first/eventual metrics, denominator/CI, failure taxonomy, cost/quota events, threats to validity và decision. Không dùng production-ready hoặc BASELINE ACCEPTED khi chưa đạt gate tương ứng.
