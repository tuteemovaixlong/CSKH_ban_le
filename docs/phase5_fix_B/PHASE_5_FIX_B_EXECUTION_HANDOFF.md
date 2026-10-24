# Phase 5 Fix B — Controlled handoff

## Historical PR/CI prompt — consumed on PR #45 (DO NOT REPLAY)

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

## Trạng thái bàn giao — 2026-10-24 (sau R6 endpoint/port hardening & gate PR/CI trên PR #45)

- Independent [review R6](PHASE_5_FIX_B_REVIEW_R6_2026-10-24.md): **PASS (`0` findings)** trên R6 candidate `1d09e7d330752d19bb8b4f9dab32e68ddffe53bb` (kế thừa và siết chặt sau [review R5](PHASE_5_FIX_B_REVIEW_R5_2026-10-24.md)).
- Nhánh `codex/phase5-fix-b-readonly-purge` trên draft [PR #45](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/45) (base `83bee6c5c42d9996a3230208d30ec6e6f0c5de2e`) đã xác minh metadata các run R5 trước đó (`40059900590`/`40059900574` trên `7121534364c9d5b060251ec56e2ac71b57faf983`, merge SHA `0e8dee126fb5a70bf0640cb19d1f421b10b6714f`; docs-sync `40060838037`/`40060838077` trên `f112baa568f53f9f4fbc874ba66ab1142bd13ccf`, merge SHA `74de04ddd24c0eaa75e3be6b89799abcf3a1e702`) và đẩy R6 code/test candidate `1d09e7d330752d19bb8b4f9dab32e68ddffe53bb` (`refs/pull/45/merge` → tested merge SHA `fd061059b3c4411136ba737478b462137e75bac4`).
- Toàn bộ 5/5 required GitHub Actions jobs trên candidate `1d09e7d330752d19bb8b4f9dab32e68ddffe53bb` đạt **SUCCESS**:
  - [CI `40067793080`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40067793080): [`offline` `120794589040`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40067793080/job/120794589040) chạy PostgreSQL 16 + `pgvector 0.8.6` (`TEST_PGVECTOR_READY=0.8.6`), host `Ran 719 tests` (`0 skipped`) và packaged container `retailops:ci` `Ran 719 tests` (`0 skipped`), gồm toàn bộ suite Fix B & shared guard (`test_postgres`: `40/40`, `test_phase5_sales_postgres`: `13/13`, `test_phase5_complaint_e2e`: `20/20`, `test_knowledge`: `5/5`, `test_rag_chat`: `14/14`, `test_phase5_fix_a`: `8/8`, `test_postgres_test_guard`: `9/9`); [`colab-python313` `120794589233`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40067793080/job/120794589233) `SUCCESS`.
  - [Ops Console `40067793153`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40067793153): [`postgres` `120794589333`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40067793153/job/120794589333) `Ran 19 tests` (`0 skipped`); [`portable (ubuntu-24.04)` `120794589259`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40067793153/job/120794589259) và [`portable (windows-latest)` `120794589336`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40067793153/job/120794589336) mỗi job `Ran 19 tests` với `skipped=2` (hai suite PostgreSQL thiếu DB/DSN trong chế độ portable — không tính là PostgreSQL PASS).
- Kết quả này đóng `FIXB-CODE-DRYRUN`, `FIXB-BACKEND`, `FIXB-DSN`, `FIXB-AUDIT`, `FIXB-PG-CI`, `FIXB-ERRORS`, `FIXB-DOCS` và candidate synthetic rehearsal (`FIXB-REHEARSAL`). **Chưa merge, chưa deploy, chưa bật/tắt EC2 hay thao tác live DB.** Các gate `FIXB-DEPLOY-APPROVAL`, `FIXB-SOURCE`, `FIXB-ENV`, `FIXB-TARGET`, `FIXB-CATALOG`, `FIXB-BACKUP`, `FIXB-DRYRUN`, `FIXB-EXECUTE`, `FIXB-POSTCHECK`, `FIXB-RETENTION` (live counts) và performance vẫn **BLOCKED / PENDING**.

## Lịch sử cô đọng — không chạy lại prompt cũ

- [R1](PHASE_5_FIX_B_REVIEW_2026-10-23.md): hai blocker dry-run/backend ở baseline Fix A.
- [R2](PHASE_5_FIX_B_REVIEW_R2_2026-10-23.md): FIXB-1..4; remediation đã được Argon thực thi và self-review trong [R3](PHASE_5_FIX_B_REVIEW_R3_2026-10-23.md).
- R4: mở rộng shared guard, chặn ambient libpq redirect; sửa P1 scope opt-in CI.
- [R5](PHASE_5_FIX_B_REVIEW_R5_2026-10-24.md): bắt buộc operator attribution, từ chối backend whitespace; review tĩnh PASS và PR #45 mở tại `7121534`.
- [R6](PHASE_5_FIX_B_REVIEW_R6_2026-10-24.md): siết `scripts/postgres_test_guard.py` chỉ nhận đúng endpoint PostgreSQL disposable của workflow (`dbname=retailops_test`, `user=retailops_test`, `host=127.0.0.1`, explicit `port=5432`, conninfo allowlist), bổ sung regression cho default port và port-forward sai (`9/9` guard tests); review độc lập chỉ đọc PASS và CI PostgreSQL/pgvector PASS (`0 skipped`) trên `1d09e7d`.

## Các gate live còn lại

Sau CI và gate repo, một cửa sổ vận hành riêng mới xét source/image, EC2/SSM, mapping tenant, exact tuple và catalog snapshot. Backup phải được kiểm tra và restore trong môi trường cô lập; cùng code/schema phải được rehearsal trên PostgreSQL tổng hợp. Live dry-run phải server-enforced read-only, đúng target, executed=false và counts không đổi; trình evidence đã che thông tin nhạy cảm trước khi xin xác nhận execute cuối cùng.

Chỉ sau xác nhận đó mới execute và post-check dữ liệu/UI/tombstone/audit/retention. Chỉ xóa các hàng vận hành được criteria cho phép; giữ catalog P-602 hiện đã sửa, khách hàng, đơn khác và lịch sử audit/import/hội thoại theo contract. Không dùng runbook Fix A đã thu hồi.

## Liên kết

[Fix B index](README.md) · [review R6](PHASE_5_FIX_B_REVIEW_R6_2026-10-24.md) · [historical review R5](PHASE_5_FIX_B_REVIEW_R5_2026-10-24.md) · [criteria](PHASE_5_FIX_B_ACCEPTANCE_CRITERIA.md) · [evidence](PHASE_5_FIX_B_EVIDENCE.md) · [Fix A evidence — runbook cũ đã thu hồi](../phase5_fix_A/PHASE_5_FIX_A_EVIDENCE.md) · [acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md) · [project status](../CURRENT_PROJECT_STATUS.md) · [roadmap](../PLAN_ROADMAP_INDEX.md) · [Phase 5 index](../phase5/README.md) · [docs index](../README.md).
