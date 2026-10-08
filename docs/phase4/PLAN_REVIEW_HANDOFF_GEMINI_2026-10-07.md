# Phase 4 — Plan nghiệm thu cố định và handoff Gemini

## Prompt trigger

```text
Đọc docs/phase4/REVIEW_GEMINI_PHASE4_2026-10-07.md. N1/N3/N4 DONE; chỉ sửa K7/C6 ở 5 file đã chỉ rõ. Freeze SHA mới, verify đúng 8 check (base→HEAD), lấy sign-off model khác/human mới → owner review → merge → G2 offline. Không mở audit mới hoặc cấp readiness trước G5.
```

> Owner chốt ngày 2026-10-08: [Acceptance Criteria v1](PHASE_4_ACCEPTANCE_CRITERIA.md) là nguồn quyết định; đúng 8 check, không thêm mục.
> Frozen HEAD đã kiểm: `a19ed2a74e457fcba9eee76f206156d1f4ea446b`, PR [#36](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/36).
> N1 mutation / N3 denominator / N4 types DONE. K1–K6 PASS; K7/C6 FAIL, nên K8 chưa đủ6/6; independent sign-off PENDING. Chưa merge/G2/live. [Evidence đúng SHA](PHASE_4_ACCEPTANCE_EVIDENCE_a19ed2a.md).

## 1. Thực thi

1. Chỉ bỏ dòng trống thừa cuối5file trong `docs/phase4/`: `CHAPTER_4_OUTLINE.md`, `PHASE_4_ABLATION_STUDY.md`, `PHASE_4_FAILURE_TAXONOMY.md`, `PHASE_4_THREATS_TO_VALIDITY.md`, `REVIEW_PHASE_4_PLAN.md`. Giữ đúng một newline cuối mỗi file; không đổi nội dung nghiên cứu/code/frozen inputs/ngưỡng.
2. Gộp cập nhật review/plan/handoff/tiến độ đang có trong checkout vào closure docs commit, ghi FROZEN_HEAD mới, push PR #36. Không thêm hardening. Giữ N1 deferral và mọi việc ngoài scope trong [Phase5 backlog](PHASE_5_BACKLOG.md).
3. Chạy **đúng K1–K8** trên SHA mới. K7/C6 dùng `git diff --check 49671b928ad6badfaa01331174eb73f0e366752e HEAD`, lưu output/exit0; không dùng empty working-tree diff thay patch PR. K5 ghi full summary >=563, failures0/errors0 và skipped riêng; CI phải đúng HEAD mới. Không hạ P99 threshold.
4. Tạo packet SHA mới từ [packet a19ed2a](PHASE_4_ACCEPTANCE_EVIDENCE_a19ed2a.md), giữ packet cũ làm lịch sử. Cập nhật entrypoints theo evidence thật; không ghi toàn bộ PASS khi thiếu chứng cứ.
5. Sau8/8 PASS, giao acceptance + frozen diff/evidence cho **một model khác/human mới**, chưa tìm N1–N5. Reviewer chỉ verify 8 mục, không scan rộng. Reviewer Codex/agents cũ và Gemini tác giả không tự sign-off.
6. Nếu8/8 + independent PASS: kết thúc review build, gửi owner review. Nếu FAIL: chỉ sửa nguyên nhân K-ID fail; criteria giữ nguyên, không thêm blocker.
7. Sau freeze mọi phát hiện ngoài8mục → Phase5 backlog, không nhận thêm vào PR hay chặn merge.

## 2. Handoff evidence

Dùng template trong acceptance: PR URL/full FROZEN_HEAD/runtime baseline; K1–K8; commands/test names/results/CI URLs; full summary/environment/skips; mock counts/SHA/185/237; C1–C6; N1 defer; independent source/timestamp và owner/merged SHA/G2. Không thêm acceptance checklist cạnh tranh.

Kết quả a19ed2a đã xác nhận: mutation hash reject; thêm13blocked giữ185/237, blocked-only0/0; 4malformed tools và24non-bool flags reject/16valid bool controls; CI5success; full local575/49skipped OK; mock250/263valid. C1–C5 PASS; K7/C6 FAIL do EOF whitespace. Đây là Codex verification, chưa là independent sign-off.

## 3. Owner merge và G2

Independent8/8 PASS → owner review → merge theo policy → G2 merged CI/contracts/frozen-hash/mock replay trên merged SHA. PR có mixed packaging nên guard eligibletrue; không đổi repo variables hoặc tự deploy/live/paid. Sau G2 chuyển lane preflight ở workstream riêng; G3 approval→G4 evidence→G5 readiness→G6 full-run authorization→G7 measured. Merge/G2 không cấp READY FOR MEASUREMENT.
