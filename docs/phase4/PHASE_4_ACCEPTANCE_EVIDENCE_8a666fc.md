# Phase 4 — Evidence acceptance v1 tại `8a666fc`

> Kiểm tra: 2026-10-08. Frozen HEAD: `8a666fcce464c96b1dd5fc6848a2d4168c6505d1`.
> PR [#36](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/36), branch `codex/phase4-harness`, remote head khớp local; runtime baseline `49671b928ad6badfaa01331174eb73f0e366752e`.
> Kết luận kỹ thuật: **K1–K8 PASS; C1–C6 PASS. Independent sign-off PENDING.**

## Checklist cố định

| ID | Evidence trên cùng SHA | Kết quả |
|---|---|---|
| K1 | Mutation `manifest.dataset_sha256` sang hash khác, cập nhật checksums; validator vẫn reject `dataset_sha256 mismatch`. Targeted test `test_r12_frozen_benchmark_hash_mismatch` PASS. | PASS |
| K2 | Targeted test PASS (blocked-only denominator 0); probe tại 8a666fc thêm 13 grading blocked từ first-429 thật qua Phase4Grader: trước/sau đều numerator185, denominator237, rate0.7806; dữ liệu sửa trong bộ nhớ. | PASS |
| K3 | Schema/grader targeted tests PASS tại 8a666fc; probe toàn bộ vectors tại a19ed2a được tái dùng vì code/test không đổi: `tools_called` sai kiểu bị reject; 8 safety flags non-bool bị reject; bool controls pass; safety True kích hoạt veto. | PASS |
| K4 | 5 check-runs SUCCESS trên đúng HEAD: offline, colab-python313, portable Windows, portable Ubuntu, postgres. [Offline](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37747491290/job/113212344963) và [portable/postgres](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37747491244). | PASS |
| K5 | Full summary Gemini ghi `Ran 575 tests, OK (skipped=49)`, exit 0; offline CI trên exact HEAD SUCCESS. | PASS |
| K6 | Temporary mock replay: validator `VALID`, 250 cases, 263 attempts, 250 gradings, 250 retrievals, 13 errors; `evaluation_harness_sha=8a666fcce464c96b1dd5fc6848a2d4168c6505d1`. | PASS |
| K7 | `git diff --check 49671b928ad6badfaa01331174eb73f0e366752e HEAD` exit 0; 5 EOF blank lines đã loại bỏ. | PASS |
| K8 | C1 docs 4/4; C2 baseline/benchmark/master 30/250/250; C3 deployment; C4 live-E2E; C5 notebook sync; C6 patch diff — tất cả PASS. | PASS |

## Independent sign-off và điều kiện dừng

Kỹ thuật đã đạt đủ 8/8. Reviewer độc lập phải là human hoặc model khác chưa tham gia tìm N1–N5; chỉ nhận acceptance v1, frozen diff và packet này, xác minh K1–K8, ghi nguồn và thời điểm. Codex reviewer hiện tại và Gemini tác giả không tự ký thay bước này.

Sau independent PASS: owner review → merge PR #36 → G2 offline trên merged SHA. Không chạy live/paid, không đổi variables và không cấp `READY FOR MEASUREMENT` trước G5. Findings ngoài 8 mục giữ trong [PHASE_5_BACKLOG.md](PHASE_5_BACKLOG.md).

N1 actual-source replay hardening vẫn DEFERRED (P5-01); N3 counts/completeness (P5-02), N4 positive-count thiếu tool names (P5-03), L2/L4/L5 không block merge theo acceptance v1.

## Nguồn evidence K5 và giới hạn local

Đã đọc GitHub check-runs: offline CI SUCCESS đúng SHA 8a666fc. Summary Ran 575 tests, OK (skipped=49), exit0 do Gemini báo cáo trong attachment; chưa trực tiếp đọc raw CI log. Công cụ CI diagnostics trả yêu cầu kết nối tài khoản. Reviewer độc lập đối chiếu summary/exit status trong K5 hiện có; không thêm check mới.

Local command: python -m unittest discover -s tests -p test_*.py -q; RETAILOPS_HEADROOM_ARTIFACT_PATH trỏ file tạm. Kết quả Ran 575 tests in 98.547s, FAILED(failures=1, skipped=49); tests/test_http_headroom.py:630, /api/session P99 61.010399833ms > 50ms. Không gọi local PASS hoặc kết luận chắc chắn về regression. Acceptance v1 chọn CI offline làm môi trường K5 chuẩn; không hạ threshold, không lặp test để lấy PASS.

## Docs hậu kiểm

Packet và docs bàn giao/bản đồ được cập nhật trong working tree, chưa commit/push; frozen code đã kiểm vẫn là 8a666fc. Đây không phải closure code mới. Nếu đưa docs vào PR và head thay đổi, đối chiếu docs-only diff và evidence/CI/identity theo cùng K1–K8; không mở audit mới.
