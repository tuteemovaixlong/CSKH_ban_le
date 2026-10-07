# Plan Review & Handoff Gemini — Phase 4

> Ngày: 2026-10-07
> Input: branch codex/phase4-harness, head bc3f47fab00b7997d6a57b07943055403ead2df4
> Status: BLOCKED FOR MERGE

## Prompt Gemini

~~~text
Fix Phase 4 harness on branch codex/phase4-harness using REVIEW_GEMINI_PHASE4_2026-10-07.md.

Priorities: Docker packaging/no-skip, fail-closed R10, cross-run/case/logical joins and frozen hash,
logical-case aggregate, required tools and S0/S1 veto, complete R13 runtime paths and multi-commit diff.
Add adversarial mutation tests for each issue.

Run full unittest, Phase 4 tests inside Docker, six contract checks, 250-case mock
validate/recompute and diff check. Report PASS/SKIP/FAIL/ERROR with evidence.
Do not merge, deploy, run live smoke, paid API or measurement. Stop for owner review.
~~~

## Review plan theo thứ tự

1. **Packaging gate:** copy evals/harness, qrels, phase4 scripts và tests cần thiết vào image/CI; bỏ skip giả.
2. **R10 gate:** schema kiểu dữ liệu, non-negative, nullability/unavailable_reason và zero provenance.
3. **R12 provenance gate:** run/case/logical/attempt joins, unique IDs, manifest fields, exact artifacts, frozen LF hash.
4. **Metrics gate:** first/eventual theo logical case; retry recovery và blocked denominator không đếm trùng.
5. **Grader gate:** required tools đầy đủ; S0/S1 hard veto rejected; no-evidence labels rõ.
6. **R13 gate:** runtime path matrix, eval-only/mixed/runtime/manual tests và multi-commit before..sha.
7. **Evidence gate:** Docker tests thật, full suite, six contracts, mock 250 bundle, checksums/recompute.
8. **Handoff gate:** mở PR/update PR, báo head SHA/evidence, dừng chờ owner review trước merge.

## Output bắt buộc từ Gemini

- Diff theo H1–H8.
- Bảng PASS/SKIP/FAIL/ERROR có số lượng test.
- Docker command và kết quả test không skip harness.
- Mutation evidence cho R10/R12/R13.
- Mock 250-case artifact/checksum/recompute.
- Changed-file matrix của deployment guard.
- PR URL/head SHA.
- Danh sách gate còn mở; không tự merge.

## Stop conditions

Dừng và không merge nếu còn một trong các điều kiện:

- test harness bị skip trong Docker;
- mutation R10/R12/R13 vẫn được ACCEPTED;
- frozen hash hoặc manifest provenance không được enforce;
- aggregate retry đếm trùng logical case;
- required tool/S0/S1 veto sai;
- multi-commit deployment guard chưa chứng minh;
- CI xanh nhưng thiếu artifact/evidence tương ứng.

## Handoff sau khi đạt

Chỉ khi H1–H8 đóng, CI và Docker evidence PASS, owner mới review để merge. Sau merge:

G2 MERGED_VERIFIED → G3 SMOKE_AUTHORIZED → G4 LIVE_SMOKE → G5 LANE_MEASUREMENT_READY.

Không tự chuyển READY FOR MEASUREMENT và không chạy full measurement trước G5.
