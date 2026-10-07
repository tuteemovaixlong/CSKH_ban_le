# Review độc lập Gemini Phase 4 — cập nhật R10–R13

> Ngày review: 2026-10-07
> Branch: `codex/phase4-harness`
> HEAD đã kiểm tra: `ee66045efb8b36dd3f28e2e40fb80a308f415ffa`
> Runtime baseline: `49671b928ad6badfaa01331174eb73f0e366752e`

## Prompt Gemini — sửa trước merge

```text
Tiếp tục sửa Phase 4 harness trên branch codex/phase4-harness theo review này.

1. R12: manifest.artifact_files phải đúng exact CANONICAL_ARTIFACT_FILES, gồm manifest.json,
   không cho thiếu, thừa hoặc duplicate; validator phải reject mọi biến thể.
2. R12 metrics: mỗi attempt chỉ có một grading hiệu lực trong bundle accepted; nếu hỗ trợ
   adjudication/version mới thì phải có khóa/version và quy tắc chọn duy nhất. Reject duplicate
   grading cho cùng attempt hoặc bảo đảm aggregate không thể có numerator/denominator > 1.
3. Bổ sung kiểm tra error_ref, qrels_sha256 và benchmark identity/provenance nếu chúng là field
   bắt buộc trong PHASE_4_RESULTS_SCHEMA.md.
4. Thêm mutation tests cho các lỗi trên, chạy full unittest, Phase 4 tests, six contract checks,
   mock 250-case validate/recompute và Docker tests thật. Báo PASS/SKIP/FAIL/ERROR kèm evidence.

Không sửa runtime/frozen benchmark; không paid API, cloud, deploy, live smoke, full measurement
hoặc merge. Mở/cập nhật PR rồi dừng chờ owner review.
```

## Phạm vi và bằng chứng

Đã đối chiếu diff từ runtime baseline đến HEAD, gồm Docker/CI, `evals/harness`, qrels/sidecar,
tests, deployment guard và tài liệu Phase 4. Không thấy thay đổi business runtime hoặc nội dung
hai frozen benchmark.

| Kiểm tra | Kết quả thực tế |
|---|---|
| Phase 4 unit tests | PASS — 38 test targeted |
| Full unittest local | Có output test nhưng tiến trình local không trả summary/exit rõ ràng trong môi trường review; cần CI/Docker xác nhận |
| Docs contract | PASS 4/4 |
| Deployment/live-e2e/notebook checks | PASS |
| Frozen benchmark validators | PASS — 250 ca mỗi file; LF SHA-256 của cả hai là `36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411` |
| Mock 250-case bundle | PASS — validate 250 cases, 263 attempts, 250 gradings, 250 retrievals, 13 errors |
| Docker local build/test | SKIP — máy review không có Docker CLI |
| Git diff check | PASS |

## Đã đóng

| Mục | Trạng thái | Evidence |
|---|---|---|
| H1 / Docker packaging | CLOSED(spec/implementation), evidence Docker còn chờ CI | Dockerfile đã copy `evals`, `scripts`, `tests`; CI chạy unittest trong image |
| H2 / R10 measured zero | CLOSED | schema strict non-negative/nullability/zero reason; adversarial tests reject mutation |
| H3 / R12 cross-record joins | CLOSED cho run/case/logical/attempt | validator đối chiếu grading, retrieval, errors với attempt đích |
| H4 / frozen LF hash | CLOSED cho nội dung benchmark | runner và validator reject dataset hash sai; cả hai file hiện cùng LF hash |
| H6 / required tools và safety veto | CLOSED phần contract chính | required tools dùng `issubset`; S0/S1 safety veto trả `rejected` |
| H7 / R13 paths và multi-commit | CLOSED về logic | runtime paths đã mở rộng; workflow `fetch-depth: 0`; dùng `before..sha`; unknown path fail-closed |

## Lỗi nặng — còn chặn merge

### H8 — `artifact_files` chưa exact canonical list

`validate_manifest()` chỉ kiểm tra các file bắt buộc không thuộc `manifest.json`; nếu bỏ
`manifest.json` khỏi `artifact_files`, bundle vẫn được chấp nhận. Probe đã tạo manifest thiếu
`manifest.json` và validator trả `True`. Điều này vi phạm yêu cầu exact canonical artifact list
và cho phép manifest tự mô tả không đầy đủ.

### H9 — duplicate grading làm sai aggregate

Validator kiểm tra duplicate `grading_id` và `record_id`, nhưng chưa reject hai grading khác ID
trỏ cùng `graded_attempt_id`. Probe thêm một grading cho cùng attempt: validator trả invalid chỉ
vì aggregate được tạo trước bị lệch; nếu attacker sửa aggregate theo raw records, bundle có thể
qua validator với `quality_conditional.denominator=6`, `first_attempt_success_rate=1.2` cho 5 case.
Contract phải chọn một grading hiệu lực duy nhất cho mỗi attempt hoặc reject duplicate trước khi
tính metric.

Hai lỗi này thuộc R12 và vẫn là **BLOCKER FOR MERGE**.

## Lỗi nhẹ / giới hạn còn lại

- Benchmark identity chưa tách rõ `benchmark_id`/path trong manifest; hiện hai frozen file có cùng hash
  nên integrity vẫn kiểm được, nhưng provenance lane chưa chỉ rõ file nào được chạy.
- `error_ref` chưa được kiểm tra ngược bắt buộc tới `errors.jsonl`.
- `retrieval.qrels_sha256` chưa được đối chiếu bắt buộc với manifest qrels hash.
- Grader no-evidence vẫn dựa một phần vào nhãn/heuristic; phù hợp offline fixture, chưa đủ bằng chứng
  cho live retrieval quality.
- Docker/CI evidence chưa thể xác nhận từ máy local vì thiếu Docker CLI.
- R11 readiness transition vẫn cần executable assertion rằng chỉ G5 mới cấp `READY FOR MEASUREMENT`.

## Verdict hiện tại

| Mục | Kết luận |
|---|---|
| R10 | **DONE / CLOSED** |
| R11 | **CLOSED(spec), PARTIAL(executable)** |
| R12 | **PARTIAL — H8/H9 còn blocker** |
| R13 | **CLOSED(spec/implementation), CI evidence pending** |

### Phân loại

- **Nặng:** H8 exact artifact list; H9 duplicate grading/aggregate integrity.
- **Nhẹ:** benchmark identity field, `error_ref`, qrels hash join, heuristic no-evidence, thiếu Docker evidence local, executable G5 assertion.

## Quyết định và điều kiện mở lại

**BLOCKED FOR MERGE.** Không chuyển sang `READY FOR MEASUREMENT`.

Chỉ mở lại review khi Gemini có diff và mutation tests chứng minh:

1. manifest exact canonical list được reject khi thiếu/thừa/duplicate;
2. duplicate grading cùng attempt bị reject hoặc có adjudication/version selection normative;
3. aggregate luôn có numerator/denominator hợp lệ theo logical case;
4. Docker/CI chạy thật Phase 4 tests, không skip harness;
5. full suite, six contract checks, mock 250 bundle và clean-checkout replay có evidence;
6. owner review PR trước merge.

Trạng thái chính thức: **READY FOR HARNESS/PREFLIGHT**.
