# Phase 4 — Plan nghiệm thu cố định và handoff

## Prompt trigger

```text
Đọc docs/phase4/REVIEW_GEMINI_PHASE4_2026-10-07.md và evidence 8a666fc. Dừng sửa code. Giao acceptance v1 + frozen diff + evidence cho model khác/human mới xác minh đúng K1–K8 và ký, gồm summary CI K5. PASS → owner review → merge → G2 offline. Ngoài checklist → backlog Phase 5; chưa cấp readiness trước G5.
```

> Acceptance v1 là nguồn quyết định; đúng 8 check, không thêm mục.
> Frozen HEAD: `8a666fcce464c96b1dd5fc6848a2d4168c6505d1`, PR [#36](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/36).
> Technical verdict: K1–K8/C1–C6 PASS. Independent sign-off PENDING; chưa merge/G2/live.

## Handoff còn lại

1. Không sửa thêm code, benchmark, runtime hoặc threshold; N1/N3/N4 và K7 đã DONE.
2. Giao [evidence packet](PHASE_4_ACCEPTANCE_EVIDENCE_8a666fc.md) và acceptance v1 cho một model khác/human mới chưa tham gia N1–N5.
3. Reviewer chỉ xác minh K1–K8, ghi PASS/FAIL, nguồn và timestamp; không deep scan, không thêm requirement. Reviewer cũ và Gemini tác giả không tự ký.
4. Independent PASS → owner review → merge PR #36 theo policy → G2 offline trên merged checkout/SHA.
5. G2 kiểm merged CI, contracts/frozen hashes và mock replay đúng harness SHA. PASS thì dừng review harness, chuyển lane preflight riêng.
6. Ngoài 8 mục → [Phase 5 backlog](PHASE_5_BACKLOG.md), không block merge. FAIL trong checklist chỉ sửa nguyên nhân K-ID đó.

## Evidence và điều kiện dừng

Packet ghi full SHA, K1–K8, CI links, full test summary/skips/environment, mock counts/SHA/quality, C1–C6, N1 deferral và sign-off PENDING. Packet a19ed2a giữ làm lịch sử.

Kết quả xác minh: CI exact-head 5/5 success; C1–C6 PASS; mock 250 cases/263 attempts với harness SHA đúng 8a666fc; targeted K1–K3 PASS; patch whitespace sạch. Local full-suite rerun có 1 P99 timing failure (61.0104ms > 50ms), còn CI offline là nguồn K5 chuẩn và đã PASS; không hạ threshold, không kết luận chắc chắn về regression từ lần chạy này.

Sau independent sign-off PASS, dừng review harness. Owner review/merge và G2 là bước tiếp theo; không chạy live/paid hoặc cấp `READY FOR MEASUREMENT` trước G5.
Docs hậu kiểm đang ở working tree, chưa commit/push; frozen code vẫn là 8a666fc. Nếu gộp docs vào PR làm đổi SHA, đối chiếu docs-only diff và evidence/CI trên head đó trong cùng checklist; không mở audit mới. K5 raw summary do Gemini báo cáo, reviewer độc lập đối chiếu log CI (xem packet).
