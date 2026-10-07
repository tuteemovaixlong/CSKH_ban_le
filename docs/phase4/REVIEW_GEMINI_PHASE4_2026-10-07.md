# Review độc lập Gemini Phase 4 — R10–R13

> Ngày review: 2026-10-07
> Branch: codex/phase4-harness
> Head: bc3f47fab00b7997d6a57b07943055403ead2df4
> Baseline runtime: 49671b928ad6badfaa01331174eb73f0e366752e

## Prompt sửa bắt buộc — đặt trước khi tiếp tục merge

~~~text
Sửa các blocker trong REVIEW_GEMINI_PHASE4_2026-10-07.md trên branch codex/phase4-harness.

1. Đóng gói evals/harness, evals/qrels, scripts/phase4_harness.py và guard vào Docker/CI;
   test harness trong container phải chạy thật, không dùng ImportError skip để báo xanh.
2. R10 fail-closed: bắt buộc kiểu/số không âm; model_calls=0 và provider_inference_ms=0.0
   chỉ khi có observed zero + zero_reason hợp lệ; missing telemetry phải null + unavailable_reason;
   bác provider time null/>0 khi model_calls=0.
3. R12: mọi grading/retrieval/error join đúng run_id, case_id, logical_request_id và attempt_id;
   enforce unique record IDs, exact canonical artifact list, manifest fields, SHA format và frozen LF hash.
4. Tính aggregate theo logical case; first và eventual không đếm trùng grading/retry.
5. Grader: required_tools phải là subset bắt buộc; S0/S1 hard veto phải ra rejected;
   kiểm unsupported claim/no-evidence đúng theo answerability.
6. R13: bao phủ mọi runtime/deploy path thực tế; xử lý push nhiều commit bằng before..sha đầy đủ,
   không fallback HEAD~1 làm mất commit. Giữ workflow_dispatch và mixed eval+runtime đúng policy.

Thêm mutation tests cho từng lỗi. Chạy full unittest, test harness trong Docker,
6 contract checks, mock 250-case validate/recompute và git diff --check.
Không merge, deploy, live smoke, paid API hoặc measurement. Báo evidence rồi dừng chờ owner review.
~~~

## Phạm vi đã kiểm tra

Đã đối chiếu toàn bộ diff origin/main...HEAD: harness schema/writer/validator/runner/grader/telemetry,
sidecar/qrels, tests, Dockerfile/CI, deployment guard, Phase 4 docs và hai file review/handoff.
Không có thay đổi business runtime hoặc nội dung hai frozen benchmark trong diff.

## Kết quả kiểm tra thực tế

| Kiểm tra | Kết quả |
|---|---|
| Full unittest discovery | PASS, 523 test cases được discover; không có FAIL/ERROR trong lượt chạy local |
| Phase 4 tests | PASS, 21 tests |
| Deployment guard tests | PASS, 6 tests |
| Docs contract | PASS 4/4 |
| Frozen dataset validators | PASS, mỗi benchmark 250 ca |
| Deployment/live-e2e/notebook checks | PASS |
| Docker local build/test | SKIP: máy review không có Docker CLI |
| Mutation probes | FAIL theo contract: các mutation R10/R12 dưới đây vẫn được ACCEPTED |

## Findings nặng — chặn merge

### H1 — Harness test có thể bị skip trong Docker/CI

Dockerfile chỉ copy benchmark baseline, không copy evals/harness, evals/qrels hoặc scripts/phase4_harness.py. Các test Phase 4 bắt ImportError rồi gọi skipTest. Vì vậy test container có thể xanh nhưng không thực thi acceptance R10–R13.

**Evidence:** Dockerfile; tests/test_phase4_schema.py; tests/test_phase4_writer_validator.py; tests/test_phase4_adversarial.py.

### H2 — R10 chưa fail-closed

schema.py chỉ kiểm tra các điều kiện khi model_calls hoặc provider_inference_ms bằng 0. Nó vẫn ACCEPT:

- trace rỗng;
- model_calls âm;
- provider_inference_ms âm;
- model_calls=None/provider_inference_ms=None với model_invocation_observed=False nhưng không có unavailable_reason;
- model_calls=0 với provider_inference_ms=null;
- model_calls=0 với provider_inference_ms > 0.

**Mutation evidence:** probe local trả ACCEPTED cho cả empty_trace, negative_calls, unobserved_missing_reason và zero_provider_null.

### H3 — R12 join provenance bị bỏ qua

validator.py chỉ kiểm graded_attempt_id/attempt_id có tồn tại trong tập attempt_id toàn cục. Không kiểm run_id, case_id hoặc logical_request_id giữa record tham chiếu và attempt đích.

**Mutation evidence:** đổi run_id, case_id hoặc logical_request_id của grading record đều vẫn VALID sau khi checksum được cập nhật.

### H4 — Frozen benchmark hash chưa được enforce trong harness

FROZEN_BENCHMARK_LF_SHA256 được khai báo/import nhưng không được dùng để đối chiếu dataset. runner.py hash raw bytes, không chuẩn hóa LF và không reject benchmark đã bị thay đổi. check_docs_contract riêng không thay thế validator provenance của bundle.

### H5 — Aggregate eventual metrics có thể đếm trùng retry

recompute_aggregate_from_raw tính eventual_success_rate bằng toàn bộ gradings, không chọn một grading cuối cho mỗi logical case. Nhiều grading pass cho cùng case có thể làm numerator vượt số logical case và làm sai eventual rate.

### H6 — Grader không thực thi đủ tool/safety contract

grader.py dùng giao nhau expected_tools ∩ actual_tools; chỉ cần gọi một tool là đủ dù expected nhiều tool. S1 hard veto chỉ trả fail, trong khi contract Phase 4 yêu cầu S0/S1 safety veto phải rejected. Unsupported claim/no-evidence còn phụ thuộc heuristic text và chủ yếu xử lý labeled-unanswerable.

### H7 — R13 guard thiếu runtime paths và không an toàn với push nhiều commit

DEPLOY_ELIGIBLE_PATTERNS không bao phủ các path runtime đã được Docker/workflow sử dụng như opsconsole/**, data/smoke.jsonl, data/products.json, data/mock_shipments.json và mcp_config.json. Probe local cho các path này trả deploy_eligible=false.

get_changed_files_from_git dùng fetch-depth=2 và fallback HEAD~1..HEAD. Với push nhiều commit, diff có thể không bao phủ toàn bộ before..sha, dẫn đến bỏ sót thay đổi runtime và skip deploy sai.

### H8 — Manifest/schema chưa đủ normative fields

validate_manifest chỉ bắt một tập nhỏ: run_id, lane_id, commit/config/dataset SHA và artifact_files dạng list. Chưa enforce provider_id, cache_mode, retry_policy_id, load_profile_id, timestamps, fixture/KB/qrels hashes và exact canonical artifact list theo PHASE_4_RESULTS_SCHEMA.md.

## Findings nhẹ — chưa chặn riêng nếu H1–H8 được sửa

- record_id chưa được kiểm unique trong từng artifact.
- checksums.sha256 chưa validate SHA đúng 64 hex và cho phép filename ngoài canonical set.
- EVAL_AND_DOCS_PATTERNS được khai báo nhưng không dùng.
- qrels/metric no-evidence còn trả 0.0 thay vì N/A/abstain rõ ràng.
- R11 wording đúng, nhưng chưa có executable state-transition test chứng minh chỉ G5 được nâng readiness.
- Qrels hiện là heuristic keyword-generated; chỉ dùng làm fixture/offline smoke, chưa đủ làm live retrieval quality evidence.

## Verdict R10–R13

| Finding | Verdict | Mức |
|---|---|---|
| R10 | FAIL — validator chưa fail-closed | Nặng |
| R11 | PASS về tài liệu; thiếu executable gate assertion | Nhẹ |
| R12 | FAIL — join, frozen hash, manifest và aggregate chưa đủ | Nặng |
| R13 | PARTIAL/FAIL — coverage và multi-commit diff chưa đủ | Nặng |

## Quyết định merge

**BLOCKED FOR MERGE.** CI xanh hiện tại chưa đủ bằng chứng vì harness tests có thể bị skip trong container và mutation probes vẫn lọt. Không chuyển G1/G2 thành đã nghiệm thu, không ghi READY FOR MEASUREMENT.

## Điều kiện mở lại review

1. H1–H8 có diff và mutation tests tương ứng.
2. Docker/CI chạy thật harness tests, không skip vì thiếu package.
3. Full unittest và Phase 4 tests PASS với số SKIP/FAIL/ERROR báo rõ.
4. Mock 250-case bundle validate/recompute PASS sau khi validator mới enforce hash/join/aggregate.
5. R13 test đủ eval-only, runtime-only, mixed, workflow_dispatch và multi-commit push.
6. Owner review diff trước merge.

## Trạng thái

R10: OPEN implementation.
R11: CLOSED(spec), PARTIAL(executable).
R12: OPEN implementation.
R13: OPEN implementation.
Official status: READY FOR HARNESS/PREFLIGHT; BLOCKED FOR MERGE.
