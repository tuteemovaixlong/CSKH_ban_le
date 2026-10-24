# Phase 5 Fix B — Controlled handoff

## Prompt cụ thể cho bước tiếp theo — tạo PR và chạy CI

```text
Thực hiện gate PR/CI cho Phase 5 Fix B theo handoff này và các tài liệu được liên kết. Independent review R5 ngày 2026-10-24 đã PASS trong phạm vi review tĩnh; đây là bước kiểm chứng CI, chưa phải merge/deploy hoặc cleanup live.

1. Đọc README → PHASE_5_FIX_B_REVIEW_R5_2026-10-24.md → acceptance criteria → evidence → handoff trong docs/phase5_fix_B/.
2. Dùng worktree hiện có C:\Users\HP\.codex\worktrees\fixb-readonly-dry-run\CSKH_ban_le trên baseline 83bee6c5c42d9996a3230208d30ec6e6f0c5de2e. Candidate hiện chưa commit; giữ toàn bộ thay đổi đã review, gồm các file untracked trong docs/phase5_fix_B/, scripts/postgres_test_guard.py và tests/test_postgres_test_guard.py. Giữ nguyên workspace chính D:\year_2026\Work_2026\agentic_AI\CSKH_ban_le, stash và các worktree khác. Không reset/clean/checkout đè hay áp dụng stash.
3. Kiểm tra diff khớp review R5; không mở rộng bug hunt. Tạo branch codex/phase5-fix-b-readonly-purge nếu chưa có, commit candidate đã review, push và tạo draft PR vào main để CI và Ops Console tự chạy. Nếu branch/PR đã tồn tại thì dùng đúng candidate và không tạo bản trùng. Ghi candidate head SHA, PR URL và tested merge SHA riêng biệt.
4. Kiểm tra các required jobs: CI offline với PostgreSQL/pgvector thực, colab-python313, Ops Console postgres và các portable jobs. Offline/PostgreSQL jobs phải chạy các integration cases mới với 0 skipped liên quan. Portable skips do không có DB/khả năng OS phải ghi rõ; không gọi chúng là PostgreSQL PASS.
5. Không chạy destructive PostgreSQL suites vào DSN bất kỳ: chỉ dùng disposable service của CI, qua shared guard và explicit opt-in đã scope đúng step. Không dùng production credentials, model API/paid tests hoặc benchmark.
6. Nếu CI lỗi thuộc scope Fix B, sửa tối thiểu trong worktree này, chạy kiểm tra cần thiết, đồng bộ notebook nếu source bundle thay đổi, cập nhật review/evidence và chạy lại CI trên SHA mới. Không lấy CI của baseline/PR cũ làm bằng chứng cho candidate.
7. Đồng bộ README, evidence, acceptance matrix, CURRENT_PROJECT_STATUS, PLAN_ROADMAP_INDEX, docs index và Phase 5 index với kết quả thực. Ghi run/job URLs, SHA, số test/skips và blockers; không suy diễn CI chưa chạy là PASS.
8. Dừng sau PR + CI + cập nhật evidence. Không merge, deploy, bật/tắt EC2, dùng AWS/SSM, đọc secret hoặc kết nối/backup/dry-run/purge production DB. Báo kết quả CI, file thay đổi, candidate head/tested merge SHA, PR URL và bước tiếp theo.
```

## Trạng thái bàn giao — 2026-10-24

- Independent [review R5](PHASE_5_FIX_B_REVIEW_R5_2026-10-24.md): **PASS trong phạm vi review tĩnh; READY FOR PR/CI**.
- Candidate vẫn chưa commit/PR/CI. Local Fix A/B + guard `13/13`; targeted regression trước đó `102/102`; Ops Console `19 tests / 3 skipped`. PostgreSQL thật chưa được kiểm chứng.
- Kết quả review này đóng gate review tĩnh; chưa đóng `FIXB-PG-CI`, các gate production hay performance.
- Prompt PR/CI ở đầu file là hướng dẫn cho bước kế tiếp, không phải bằng chứng bước đó đã chạy. Phiên remediation/review hiện tại dừng ở candidate chưa commit.

## Lịch sử cô đọng — không chạy lại prompt cũ

- [R1](PHASE_5_FIX_B_REVIEW_2026-10-23.md): hai blocker dry-run/backend ở baseline Fix A.
- [R2](PHASE_5_FIX_B_REVIEW_R2_2026-10-23.md): FIXB-1..4; remediation đã được Argon thực thi và self-review trong [R3](PHASE_5_FIX_B_REVIEW_R3_2026-10-23.md).
- R4: mở rộng shared guard, chặn ambient libpq redirect; sửa P1 scope opt-in CI.
- R5: bắt buộc operator attribution, từ chối backend whitespace; review độc lập đã PASS. Dùng prompt PR/CI hiện hành, không replay remediation hoặc review-only prompt cũ.

## Các gate live còn lại

Sau CI và gate repo, một cửa sổ vận hành riêng mới xét source/image, EC2/SSM, mapping tenant, exact tuple và catalog snapshot. Backup phải được kiểm tra và restore trong môi trường cô lập; cùng code/schema phải được rehearsal trên PostgreSQL tổng hợp. Live dry-run phải server-enforced read-only, đúng target, executed=false và counts không đổi; trình evidence đã che thông tin nhạy cảm trước khi xin xác nhận execute cuối cùng.

Chỉ sau xác nhận đó mới execute và post-check dữ liệu/UI/tombstone/audit/retention. Chỉ xóa các hàng vận hành được criteria cho phép; giữ catalog P-602 hiện đã sửa, khách hàng, đơn khác và lịch sử audit/import/hội thoại theo contract. Không dùng runbook Fix A đã thu hồi.

## Liên kết

[Fix B index](README.md) · [review R5](PHASE_5_FIX_B_REVIEW_R5_2026-10-24.md) · [criteria](PHASE_5_FIX_B_ACCEPTANCE_CRITERIA.md) · [evidence](PHASE_5_FIX_B_EVIDENCE.md) · [Fix A evidence — runbook cũ đã thu hồi](../phase5_fix_A/PHASE_5_FIX_A_EVIDENCE.md) · [acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md) · [project status](../CURRENT_PROJECT_STATUS.md) · [roadmap](../PLAN_ROADMAP_INDEX.md) · [Phase 5 index](../phase5/README.md) · [docs index](../README.md).
