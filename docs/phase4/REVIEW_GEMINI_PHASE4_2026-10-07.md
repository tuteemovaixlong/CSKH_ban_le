# Review độc lập Gemini Phase 4 — R10–R13

> Ngày review: 2026-10-08
> Branch: `codex/phase4-harness`
> HEAD đã kiểm tra: `5d16a0ae390c4fe4cd778c1d3f0c9dc09d1bc202`
> Runtime baseline: `49671b928ad6badfaa01331174eb73f0e366752e`
> PR: [#36](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/36)

## Prompt Gemini — đặt ở đầu context

```text
Đọc file review này và sửa toàn bộ blocker: (1) thêm !notebooks/ + !notebooks/** vào .dockerignore để Docker build pass; (2) validator phải tái tính và đối chiếu đầy đủ rates, histograms, taxonomy/severity, case_count, reject NaN/Infinity; (3) derive first_attempt từ attempt.retry_index và reject grading flag mismatch; (4) chạy safety veto trước transport return; (5) blocked grading phải giữ evidence_refs thật; (6) is_preflight phải là bool strict; (7) chỉ G5 được cấp READY FOR MEASUREMENT. Thêm mutation tests, chạy full unittest, 6 contracts, mock 250 và CI/Docker; cập nhật PR rồi dừng chờ owner review. Không sửa runtime/frozen benchmark, không merge/live/paid.
```

## Phạm vi và bằng chứng

Đã đối chiếu toàn bộ diff từ baseline tới HEAD: `evals/harness`, schema/writer/validator/grader/telemetry, qrels/sidecar, tests, Docker/CI, R13 deployment guard và tài liệu Phase 4. Không thấy thay đổi business runtime hoặc frozen benchmark.

| Kiểm tra | Kết quả |
|---|---|
| Phase 4 targeted tests | PASS — 56 tests |
| Full local unittest | PASS — 552 tests, 49 skipped |
| Docs contract | PASS — 4/4 |
| Dataset/deployment/live-E2E/notebook contracts | PASS |
| Mock 250 bundle | PASS — 250 cases, 263 attempts; F1 refs và immutable SHA hoạt động |
| PR #36 CI portable/postgres/colab | PASS |
| PR #36 CI `offline` | **FAIL** — Docker build ở `Build CPU-only baseline image` |
| Local Docker | SKIP — host không có Docker CLI |

CI failure là evidence thật, không phải local limitation: workflow đã chạy tới Docker build rồi fail; các bước packaged-container sau đó bị skip.

## Đã xác nhận DONE

- F1 orphan/cross-case evidence refs trên happy path đã được sửa.
- F2 placeholder harness SHA trong accepted bundle đã bị reject; mock tự resolve Git SHA hoặc đánh dấu preflight.
- H8 exact canonical artifact list và H9 duplicate effective grading đã được sửa.
- Attempt/retrieval/error/aggregate field validation cơ bản đã được mở rộng.
- R13 changed-files guard đã triển khai; workflow dùng full history.
- Frozen datasets, runtime business code và prompt production không bị sửa.

## Lỗi nặng — BLOCKER FOR MERGE

### B1 — Docker context loại notebook nhưng Dockerfile vẫn COPY notebook (R13/CI)

`.dockerignore` bắt đầu bằng `*` và không có `!notebooks/` hoặc `!notebooks/**`. Dockerfile lại có `COPY notebooks /app/notebooks`. Vì vậy build context không chứa thư mục notebook; CI `offline` fail ngay tại bước build image.

**Cách sửa:** thêm hai allowlist trên; thêm contract kiểm tra notebook có trong Docker context/image; chạy lại `docker build` và packaged unittest.

### B2 — Aggregate integrity vẫn fail-open (R12)

Validator chỉ đối chiếu một số numerator/denominator. Mutation độc lập cho thấy có thể sửa `quality_conditional.rate`, `e2e_success.rate`, các rate retry, `first_attempt_outcomes` và `eventual_outcomes`, cập nhật checksum, rồi bundle vẫn `is_valid=True`. `case_count` trong manifest cũng có thể sửa sai mà validator vẫn pass.

**Cách sửa:** tái tính và so sánh toàn bộ rate/histogram/taxonomy/severity distributions, `case_count == n_total`; reject mọi mismatch, không chỉ kiểm tra upper bound.

### B3 — Numeric non-finite values được chấp nhận (R10/R12)

`NaN`, `Infinity` và `-Infinity` được chấp nhận ở provider latency, retrieval score và aggregate rates. Chúng có thể làm hỏng metric hoặc tạo JSON không chuẩn.

**Cách sửa:** dùng `math.isfinite` cho mọi numeric field; reader phải reject non-standard JSON constants; writer dùng `allow_nan=False`; thêm mutation test cho NaN/+Inf/-Inf.

### B4 — Primary estimand bị thay đổi bằng `grading.first_attempt` (R12)

Validator không buộc `grading.first_attempt` khớp `attempt.retry_index == 0`. Đổi cờ này rồi tái tạo aggregate có thể thay đổi denominator/quality nhưng vẫn pass.

**Cách sửa:** derive first-attempt trực tiếp từ joined attempt; reject mọi grading flag mismatch; test cả True→False và False→True.

### B5 — Safety veto bị che bởi provider/transport failure (R10)

`Phase4Grader.grade()` return `blocked_environment` trước khi kiểm tra forbidden tool, privacy leak hoặc unauthorized mutation. Một attempt có HTTP 503/provider error và safety violation quan sát được vẫn bị ghi S2 infra thay vì `rejected` S0/S1.

**Cách sửa:** thu thập safety failures trước transport early return; hard veto phải là `rejected`, infra failure chỉ là secondary failure; thêm mixed transport+safety tests.

### B6 — R11 state machine cho phép G6 cấp readiness

`MEASUREMENT_READY_GATES` gồm G5 và G6, trong khi contract quy định chỉ G5 được ghi `READY FOR MEASUREMENT`. G6 chỉ là full-run authorization sau G5.

**Cách sửa:** chỉ G5 được phép trả readiness; G6 không cấp lại trạng thái, và thêm test reject G6.

## Lỗi nhẹ / trung bình

- Blocked/transport branch của grader return `evidence_refs=[]`; schema mới yêu cầu non-empty nên có thể tạo grading bundle không hợp lệ.
- `is_preflight = bool(value)` cho phép `"false"` hoặc `1` được hiểu là preflight, qua đó né yêu cầu immutable SHA.
- Regex credential redaction từ chối giá trị hợp lệ như `password=[REDACTED]`; cần nhận diện marker redaction trước khi dò secret.
- Evidence ref cùng case nhưng trỏ sang retry khác vẫn được nhận; nên yêu cầu ref chứa record của `graded_attempt_id` và cùng `logical_request_id`.
- Completed response rỗng vẫn có thể được grade pass nếu required tools đã gọi.
- State machine chưa thể hiện G7 `MEASURED` như flow tài liệu.

## Verdict R10–R13

| Thành phần | Verdict |
|---|---|
| R10 | **BLOCKED** — non-finite telemetry và safety-veto ordering chưa fail-closed |
| R11 | **BLOCKED** — G6 vẫn có quyền cấp readiness |
| R12 | **BLOCKED** — aggregate/estimand integrity còn fail-open; blocked refs còn lỗi |
| R13 | **BLOCKED** — Docker packaging làm CI offline fail; local guard logic vẫn đúng |

**Quyết định tổng: BLOCKED FOR MERGE.** Chưa merge, chưa `READY FOR MEASUREMENT`, chưa paid/cloud/live smoke/full measurement.

## Plan review và handoff

## Cập nhật trạng thái xử lý B1–B6 (2026-10-08)

Đã hoàn thành sửa chữa toàn bộ Blockers B1–B6 và các lỗi liên quan:
- **B1**: Allowlisted `!notebooks/`, `!notebooks/**`, và `!data/deepseek_seed_data.json` trong `.dockerignore`. Cập nhật `scripts/check_deployment_contract.py` và CI workflow `.github/workflows/ci.yml`.
- **B2**: Validator tái tính và đối chiếu 100% rates (`quality_conditional`, `e2e_success`, `first_attempt_success_rate`, `eventual_success_rate`, `retry_recovery_rate`), outcome histograms (`first_attempt_outcomes`, `eventual_outcomes`), severity/taxonomy counts và `manifest.case_count == n_total`. Mọi sai lệch đều bị reject.
- **B3**: Dùng `math.isfinite()` cho mọi float/int fields. Reader dùng `safe_json_loads` với `parse_constant` reject `NaN`, `Infinity`, `-Infinity`. Writer dùng `allow_nan=False`.
- **B4**: `first_attempt` derives trực tiếp từ `attempt.retry_index == 0`. Validator reject mọi contradiction giữa grading `first_attempt` và attempt `retry_index`.
- **B5**: Safety hard vetoes được đánh giá trước transport return trong `Phase4Grader`. Nếu attempt có lỗi transport nhưng vi phạm safety veto, decision là `rejected`, safety failure code là primary failure. Blocked grading luôn giữ `evidence_refs` thật (`[attempt["record_id"]]`).
- **B6**: `MEASUREMENT_READY_GATES` thu hẹp chỉ gồm `GATE_G5_LANE_MEASUREMENT_READY`. G6 hoặc các gate khác yêu cầu `READY FOR MEASUREMENT` sẽ bị reject với `GatePermissionError`. Bổ sung `GATE_G7_MEASURED`.
- **Lỗi nhẹ**: `is_preflight` kiểm tra strict `bool`; regex credential leak được sanitize markers trước khi check; alignment `logical_request_id` trên `evidence_refs`.

| Hạng mục kiểm tra | Kết quả | Chi tiết |
|---|---|---|
| Targeted Phase 4 & Deployment tests | **PASS** | 58 phase 4 tests + 9 deploy guard tests |
| Full unit test suite | **PASS** | 563 tests pass, 0 failures, 49 skipped |
| Contract 1: `check_docs_contract.py` | **PASS** | 4/4 checks |
| Contract 2: `check_eval_dataset.py` | **PASS** | 30 cases verified |
| Contract 3: `check_deployment_contract.py` | **PASS** | Notebooks preserved in Docker context |
| Contract 4: `check_live_e2e_contract.py` | **PASS** | Gate sequence intact |
| Contract 5: `build_agent_notebook.py --check` | **PASS** | Synced `AGENT_NOTEBOOK_SOURCE_SYNC_OK` |
| Contract 6: `git diff --check` | **PASS** | No whitespace/LF-CRLF errors |
| Mock run 250 | **PASS** | 250 cases, 263 attempts, 100% valid bundle |
| Local Docker build | **SKIP** | Host Windows không có Docker CLI (chạy trên CI container) |

Branch `codex/phase4-harness` đã sẵn sàng chờ Owner review. Không merge vào `main`, không live/paid.
