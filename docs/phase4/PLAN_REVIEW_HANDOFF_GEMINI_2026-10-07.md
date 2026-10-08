# Plan Review & Handoff Gemini — Phase 4

> Ngày: 2026-10-08
> Branch: `codex/phase4-harness`
> HEAD review: `5d16a0ae390c4fe4cd778c1d3f0c9dc09d1bc202`
> Trạng thái: **BLOCKED FOR MERGE / READY FOR HARNESS-PREFLIGHT**

## Prompt giao Gemini

```text
Đọc REVIEW_GEMINI_PHASE4_2026-10-07.md và sửa B1–B6: allowlist notebooks trong .dockerignore; tái tính/đối chiếu đầy đủ aggregate và case_count; reject NaN/Inf; derive first_attempt từ attempt; xử lý safety veto trước transport; blocked grading giữ evidence_refs thật; is_preflight strict bool; chỉ G5 cấp READY FOR MEASUREMENT. Thêm mutation tests, full unittest, 6 contracts, mock 250 và Docker/CI. Báo PASS/SKIP/FAIL/ERROR, cập nhật PR rồi dừng chờ owner review. Không sửa runtime/frozen benchmark, không merge/live/paid.
```

## Kế hoạch thực thi

1. **Docker gate:** thêm `!notebooks/` và `!notebooks/**` vào `.dockerignore`; assert notebook tồn tại trong build context/image; chạy Docker build và packaged unittest.
2. **Aggregate gate:** recompute rates, histograms, taxonomy/severity, `case_count`, `n_total`; reject mọi mismatch sau khi checksum được tạo lại.
3. **Numeric gate:** `math.isfinite` cho latency, scores và rates; reject NaN/Inf ở parser/schema/writer.
4. **Estimand gate:** joined `attempt.retry_index` là nguồn duy nhất cho first attempt; grading flag mismatch phải fail.
5. **Safety gate:** safety failures được phân tích trước transport return; S0/S1 luôn `rejected`, infra failure là secondary.
6. **Readiness gate:** chỉ G5 trả `READY FOR MEASUREMENT`; G6 không cấp lại readiness.
7. **Evidence gate:** blocked grading phải có refs thật; strict bool cho `is_preflight`; qrels/sidecar source hash phải fail-closed.
8. **Owner handoff:** cập nhật PR bằng HEAD mới, test count, artifact paths và trạng thái PASS/SKIP/FAIL/ERROR; dừng trước owner review.

## Bảng trạng thái

| Hạng mục | Trạng thái | Điều kiện đóng |
|---|---|---|
| F1/F2 evidence refs + harness SHA | CLOSED happy path | Giữ blocked-branch và strict provenance tests |
| H8 exact artifact list | CLOSED | Không hồi quy |
| H9 duplicate effective grading | CLOSED | Không hồi quy |
| B1 Docker notebooks | RESOLVED IN PR | Allowlisted notebooks trong .dockerignore, check_deployment_contract & CI workflow updated |
| B2 aggregate fail-open | RESOLVED IN PR | Tái tính và đối chiếu toàn bộ rates/histograms/taxonomy/severity, case_count == n_total; reject tampering |
| B3 NaN/Inf | RESOLVED IN PR | math.isfinite cho latency/score/rates, safe_json_loads reject non-standard JSON, allow_nan=False trong writer |
| B4 first-attempt tampering | RESOLVED IN PR | Derived trực tiếp từ attempt.retry_index == 0, validator reject mọi grading flag mismatch |
| B5 safety + transport | RESOLVED IN PR | Safety hard vetoes chạy trước transport early return; mixed case trả rejected S0/S1; blocked giữ real evidence_refs |
| B6 G6 readiness bypass | RESOLVED IN PR | Chỉ G5 cấp READY FOR MEASUREMENT; G6 bị reject với GatePermissionError |
| Blocked refs/preflight bool | RESOLVED IN PR | Real evidence_refs trong blocked grading; strict bool cho is_preflight |
| Sidecar/qrels provenance | CLOSED | Source hash mismatch/missing source fail-closed |
| Owner review | PENDING OWNER | Dừng chờ owner review sau khi đẩy PR |

## Stop conditions

Dừng merge nếu còn bất kỳ điều kiện nào sau đây:

- Docker build fail hoặc packaged tests bị skip do thiếu notebook/harness.
- Aggregate mutation, NaN/Inf, first-attempt tampering hoặc mixed safety+transport vẫn qua validator/grader.
- G6 hoặc non-bool `is_preflight` có thể cấp bypass readiness/provenance.
- Qrels/sidecar source hash không được kiểm tra fail-closed.
- Chưa có CI xanh trên HEAD mới và chưa có owner review.

## Handoff sau khi đóng

`BUILD HARNESS → PR → CI/clean-checkout replay → OWNER REVIEW → MERGE → G2 MERGED_VERIFIED → G3 SMOKE_AUTHORIZED → G4 LIVE_SMOKE → G5 LANE_MEASUREMENT_READY`.

Không tự merge, không cấp `READY FOR MEASUREMENT`, không chạy paid/cloud/live smoke/full measurement trước gate tương ứng.
