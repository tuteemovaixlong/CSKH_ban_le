# Plan Review & Handoff Gemini — Phase 4

> Ngày: 2026-10-07
> Branch: `codex/phase4-harness`
> HEAD review: `1f8c344e5e06a6fa170518d31b75f7b5b23d2b1a`
> Trạng thái: **BLOCKED FOR MERGE / READY FOR HARNESS-PREFLIGHT**

## Prompt giao Gemini

```text
Đọc REVIEW_GEMINI_PHASE4_2026-10-07.md. Sửa F1/F2: evidence_refs phải là record_id thật và validator reject ref mồ côi; accepted mock bundle phải dùng harness SHA immutable, không placeholder. Thêm mutation tests, rà field validation normative, chạy full unittest + 6 contract checks + mock 250 + Docker/CI thật; báo PASS/SKIP/FAIL/ERROR. Không sửa runtime/frozen benchmark, không paid/live/merge; cập nhật PR rồi dừng chờ owner review.
```

## Kế hoạch xử lý

1. **Evidence integrity:** truyền `record_id` thật từ runner/grader; validator kiểm tra ref tồn tại, cùng `run_id` và reject orphan.
2. **Harness provenance:** bỏ SHA mặc định placeholder khỏi accepted mock; yêu cầu SHA immutable hoặc đánh dấu bundle preflight.
3. **Schema hardening:** xử lý các field normative còn thiếu: attempt completion/response, chunk structure, redacted error, aggregate run/checksum fields, benchmark identity và qrels source hash.
4. **R11 gate:** thêm executable assertion/state transition để chỉ G5 có thể ghi `READY FOR MEASUREMENT`.
5. **Execution evidence:** chạy targeted/full unittest, docs + six contracts, sidecar/qrels, mock 250 validate/recompute và Docker/CI thật; không chấp nhận fake skip.
6. **Owner handoff:** cập nhật PR bằng HEAD mới, command, counts, artifact paths và PASS/SKIP/FAIL/ERROR; dừng trước owner review.

## Trạng thái hiện tại

| Hạng mục | Trạng thái | Kết luận |
|---|---|---|
| R10 measured zero/safety | CLOSED offline | Giữ adversarial coverage |
| R11 readiness | PARTIAL | Thiếu executable G5-only assertion |
| R12 H8 artifact list | CLOSED | Mutation tests PASS |
| R12 H9 grading/aggregate | CLOSED | Duplicate effective grading bị reject |
| R12 F1 evidence refs | CLOSED | Canonical record_id binding, orphan ref rejected |
| R12 F2 harness provenance | CLOSED | Immutable Git SHA required, placeholder rejected |
| R13 deployment guard | IMPLEMENTED | Local tests pass; container CI pending |
| Docker notebook packaging | CLOSED | `COPY notebooks /app/notebooks` added to Dockerfile |

## Điều kiện đóng

- [x] Không còn `evidence_ref` trỏ tới ID không tồn tại.
- [x] Accepted bundle không chứa harness SHA placeholder.
- [x] Mutation tests chứng minh các lỗi trên bị reject.
- [x] Full local checks (552 tests, 6/6 contracts, mock 250) đã PASS; Docker CLI thiếu được báo cáo chính xác là SKIP.
- [ ] Owner review PR hoàn tất.

## Handoff sau khi đóng

`BUILD HARNESS → PR → CI/clean-checkout replay → OWNER REVIEW → MERGE → G2 MERGED_VERIFIED → G3 SMOKE_AUTHORIZED → G4 LIVE_SMOKE → G5 LANE_MEASUREMENT_READY`.

Không tự merge, không cấp `READY FOR MEASUREMENT`, không chạy paid/cloud/live smoke/full measurement trước các gate tương ứng.
