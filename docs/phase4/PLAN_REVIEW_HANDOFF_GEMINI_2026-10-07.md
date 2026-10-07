# Plan Review & Handoff Gemini — Phase 4 (cập nhật)

> Ngày: 2026-10-07
> Branch: `codex/phase4-harness`
> HEAD: `ee66045efb8b36dd3f28e2e40fb80a308f415ffa`
> Trạng thái: **BLOCKED FOR MERGE / READY FOR HARNESS-PREFLIGHT**

## Prompt giao Gemini

```text
Đọc REVIEW_GEMINI_PHASE4_2026-10-07.md bản hiện hành và chỉ sửa H8/H9.

H8: validate_manifest phải yêu cầu artifact_files đúng exact CANONICAL_ARTIFACT_FILES,
gồm manifest.json, không thiếu/thừa/duplicate.
H9: không cho phép nhiều grading hiệu lực cho cùng graded_attempt_id; nếu cần adjudication,
thêm version/key và quy tắc chọn duy nhất trước khi tính aggregate. Bảo đảm mọi numerator/
denominator tính theo logical case và không vượt 1.

Bổ sung mutation tests cho thiếu manifest, duplicate grading và aggregate > 1. Kiểm tra thêm
error_ref, qrels hash và benchmark identity theo schema nếu normative. Chạy full unittest,
Phase 4 tests, six contract checks, mock 250-case validate/recompute và Docker tests thật.
Báo PASS/SKIP/FAIL/ERROR kèm command, số lượng và artifact evidence.

Không sửa runtime/frozen benchmark; không paid/cloud/deploy/live smoke/full measurement;
không merge. Mở/cập nhật PR và dừng chờ owner review.
```

## Kế hoạch xử lý

1. **Manifest gate:** exact canonical artifact list và mutation tests.
2. **Grading/metric gate:** unique effective grading per attempt, logical-case aggregation,
   bounded ratios và retry semantics.
3. **Provenance gate:** `error_ref`, qrels hash và benchmark identity theo schema.
4. **Execution gate:** Docker build/run thật; không chấp nhận ImportError skip.
5. **Evidence gate:** full unittest, 38+ Phase 4 tests, six contracts, mock 250-case bundle,
   checksums và clean-checkout replay.
6. **Owner gate:** Gemini mở/cập nhật PR, báo head SHA và dừng trước merge.

## Bảng trạng thái

| Finding | Trước lượt này | Hiện tại | Điều kiện đóng |
|---|---|---|---|
| H1 Docker packaging | OPEN | CLOSED implementation, CI pending | Docker test thật không skip |
| H2 R10 fail-closed | OPEN | CLOSED | Giữ adversarial coverage |
| H3 join provenance | OPEN | CLOSED cho 4 artifact raw | Giữ mutation coverage |
| H4 frozen hash | OPEN | CLOSED nội dung hash | Bổ sung benchmark identity nếu schema yêu cầu |
| H5 retry aggregate | OPEN | PARTIAL | Reject duplicate grading/effective selection |
| H6 grader safety | OPEN | CLOSED phần subset/veto | Bổ sung evidence no-evidence nếu live |
| H7 R13 guard | OPEN | CLOSED logic, CI pending | Chứng minh before..sha/mixed/manual |
| H8 manifest exact list | OPEN | OPEN blocker | Exact list mutation PASS |
| H9 duplicate grading | NEW | OPEN blocker | Duplicate attempt bị reject hoặc version selection |

## Stop conditions

Dừng, không merge nếu còn một trong các điều kiện sau:

- `artifact_files` thiếu/thừa/duplicate mà validator vẫn chấp nhận;
- duplicate grading cùng attempt làm aggregate vượt logical-case denominator;
- Docker/CI skip harness hoặc chưa có evidence container;
- mutation R10/R12/R13 còn được chấp nhận;
- frozen hash, joins, checksums hoặc manifest provenance không được enforce;
- chưa có owner review PR.

## Handoff sau khi đóng blocker

Gemini chỉ được báo `HARNESS_ACCEPTANCE_READY` sau khi H8/H9 và evidence gates đóng. Chuỗi tiếp theo:

`BUILD HARNESS → PR → CI → OWNER REVIEW → MERGE → G2 MERGED_VERIFIED → G3 SMOKE_AUTHORIZED → G4 LIVE_SMOKE → G5 LANE_MEASUREMENT_READY`.

Không tự merge, không cấp `READY FOR MEASUREMENT`, không chạy full measurement trước G5.
