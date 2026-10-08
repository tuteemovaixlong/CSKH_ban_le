# Phase 4 — Plan nghiệm thu cố định và handoff Gemini

## Prompt trigger

```text
Đọc docs/phase4/PHASE_4_ACCEPTANCE_CRITERIA.md. Chỉ hoàn tất N1/N3/N4 theo scope đã chốt, chạy đúng 8 check và đóng băng HEAD. Chuyển mọi việc ngoài checklist vào PHASE_5_BACKLOG.md; giao evidence cho reviewer độc lập mới sign-off 8 mục, rồi owner review → merge → G2 offline replay. Không tự chạy live/paid hoặc cấp READY FOR MEASUREMENT.
```

> Owner chốt ngày 2026-10-08: [Acceptance Criteria v1](PHASE_4_ACCEPTANCE_CRITERIA.md) là nguồn quyết định; đúng 8 check, không thêm mục.
> Source HEAD04: N1 manual replay hardening deferred; N3 denominator DONE; N4 safety flag type còn phải sửa. Chưa freeze closure HEAD hoặc có independent sign-off.

## 1. Thực thi

1. Giữ controls N1/N3 đã đạt; sửa type validation cho mọi safety flag grader đang dùng, gồm ownership_violation/identity_collision. Không kéo semantic tool-count/completeness/CLI/gate metadata vào patch.
2. Ghi N1 deferral và mọi việc ngoài scope vào [PHASE_5_BACKLOG.md](PHASE_5_BACKLOG.md). L2/L4/L5 không block merge.
3. Commit closure code/docs, ghi FROZEN_HEAD, push PR #36.
4. Chạy **đúng K1–K8** và bộ6check trong acceptance v1. K5 dùng full CI unittest summary >=563, zero failure/error; báo skipped/local timing limitation. Không hạ P99 threshold.
5. Giao evidence packet cho **một model khác/human mới**, chưa tìm N1–N5. Reviewer chỉ verify 8 mục, không scan rộng. Reviewer Codex cũ/Gemini tác giả không tự sign-off.
6. Nếu8/8 + independent PASS: kết thúc review build, gửi owner review. Nếu FAIL: chỉ nêu/sửa đúng K-ID fail; criteria giữ nguyên, không thêm blocker.
7. Sau freeze mọi phát hiện ngoài8mục → Phase5 backlog, không nhận thêm vào PR hay chặn merge.

## 2. Handoff evidence

Dùng template trong acceptance: PR URL/FROZEN_HEAD/runtime baseline; K1–K8 evidence; CI URLs/full test summary/environment/skips; mock counts/SHA/quality; N1 defer + backlog links. Bảng phải ghi trạng thái thật, không lấy focused rerun để gọi full local PASS. Không thêm acceptance checklist cạnh tranh.

## 3. Owner merge và G2

Independent8/8 PASS → owner review → merge theo policy → G2 merged CI/contracts/frozen-hash/mock replay trên merged SHA. PR có mixed packaging nên guard eligibletrue; không đổi repo variables hoặc tự deploy/live/paid. Sau G2 chuyển lane preflight ở workstream riêng; G3 approval→G4 evidence→G5 readiness→G6 full-run authorization→G7 measured. Merge/G2 không cấp READY FOR MEASUREMENT.
