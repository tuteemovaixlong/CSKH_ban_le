# Phase 5-E — Bounded Remediation Handoff (2026-10-18, Updated 2026-10-19 Round 3)

## Trạng thái thực thi Round 3 (Ready for Codex Re-Review)

- **Reviewed Baseline (Round 2):** PR #43 head `982801144702b703eb9af3d4d1435a3a75b1b1e4`, base `44540eab516831d5c8232dd80392b8e20c6cd47e`, tested merge ref `50fa050b4c9fa7afea59c6201e4f29aca8d4274d` ([CI 39140778461](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39140778461), [Ops Console 39140778477](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39140778477)).
- **Round 3 Code Candidate:** `97b11bbcaa67a7b2f4297e63437d5802ee789384` (base `44540eab516831d5c8232dd80392b8e20c6cd47e`, tested merge ref `e10f9b1f24c30533c36f4b6d77aec6fb51e1baa1`), followed by the docs synchronization commit on PR #43.
- **CI & Ops Console on `97b11bbcaa67a7b2f4297e63437d5802ee789384`:**
  - [CI run 39203490030](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39203490030): `offline` (`117901231330`, `Ran 701 tests in 107.624s — OK` [`0 skipped`] + packaged rerun `Ran 701 tests in 115.721s — OK` [`0 skipped`], `TEST_PGVECTOR_READY=0.8.6`) and `colab-python313` (`117901231538`) — **SUCCESS**.
  - [Ops Console run 39203490035](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39203490035): `postgres` (`117901231247`, `Ran 19 tests in 1.056s — OK` [`0 skipped`]), `portable (ubuntu-24.04)` (`117901231530`, `Ran 19 tests — OK (skipped=2)`), `portable (windows-latest)` (`117901231463`, `Ran 19 tests — OK (skipped=2)`) — **SUCCESS**.
  - Local P5-E targeted suite: `14/14 PASS` (`0 skipped`).
- **Disposition:** Ba finding bounded (`AI1`, `DATA1`, `AI5`) đã được sửa và kiểm chứng (`REMEDIATED / READY FOR CODEX RE-REVIEW`); overall verdict giữ nguyên `CHANGES REQUIRED` cho tới khi Codex hoàn tất re-review độc lập.

## Prompt kích hoạt một lần cho Argon (Consumed in Round 3)

```text
Đọc kỹ docs/phase5/PHASE_5_E_EXECUTION_HANDOFF.md, docs/phase5/REVIEW_ARGON_P5_E_2026-10-18.md, docs/phase5/PHASE_5_E_EVIDENCE_2026-10-18.md, docs/phase5/PHASE_5_E_ACCEPTANCE_CRITERIA.md và các tài liệu được liên kết. Tiếp tục trên PR #43 / branch hiện có từ candidate 982801144702b703eb9af3d4d1435a3a75b1b1e4; giữ nguyên workspace chính đang có thay đổi, không reset hoặc ghi đè.

Chỉ xử lý ba finding còn mở trong review:
1) AI1: chặn canary/secret trong trace.reasoning và các trường reasoning/thought được bảo toàn; giữ nguyên CoT thông thường đang được owner chấp nhận. Thêm regression cho canary ở bề mặt này.
2) DATA1: siết điều kiện backfill provenance để chỉ nhận đúng bộ fixture demo và các thuộc tính kỳ vọng; mixed/import provenance phải giữ nhãn canonical. Thêm regression cho legacy fixture có nguồn nhập hỗn hợp. Không sửa dữ liệu thật.
3) AI5: bổ sung PostgreSQL/pgvector assertion cho provider/quota HTTP 429, error contract và bảo đảm business state không đổi; giữ parity với SQLite.

Không thêm acceptance criteria, không mở bug hunt mới, không sửa các phần đã được review là đóng, không đổi catalog/order/giá nghiệp vụ. Chạy regression mục tiêu, toàn bộ 14 tiêu chí P5-E, CI offline với PostgreSQL/pgvector và Ops Console khi phù hợp; ghi số test/skips theo log thực tế. Tạo candidate SHA mới trên PR #43, cập nhật evidence/review/docs cùng SHA và tested merge ref. Dừng sau self-review + CI + docs; báo candidate SHA, tested merge ref, workflow/job IDs, test counts/skips, files changed và blockers. Không merge, deploy, chạy AWS/SSM/EC2, OAuth live, sửa production DB/config, chạy benchmark/performance hoặc paid tests.
```

## Tài liệu đọc theo thứ tự

1. [Review hiện hành](REVIEW_ARGON_P5_E_2026-10-18.md) — verdict, các mục đã đóng và ba finding còn lại.
2. [Evidence snapshot](PHASE_5_E_EVIDENCE_2026-10-18.md) — nguồn, runs, test counts và giới hạn.
3. [Acceptance criteria](PHASE_5_E_ACCEPTANCE_CRITERIA.md) — 14 tiêu chí cố định.
4. [Plan P5-E](PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md) và [manual-test input](PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md).
5. [Acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md), [current status](../CURRENT_PROJECT_STATUS.md), [roadmap](../PLAN_ROADMAP_INDEX.md), [codebase map](../00_OVERVIEW/CODEBASE_MAP.md).

## Ràng buộc cứng

- Preserve the pre-existing primary checkout without operating on it; its recorded provenance is branch `feat/phase5-sales-simulator-import` at `dd544800bb087d54a7faf564e723736905620045` (machine path omitted). Never reset, checkout, or overwrite it.
- Làm việc trên candidate/worktree P5-E sạch (`isolated P5-E worktree (machine path omitted)`) và branch PR #43.
- Giữ quyết định sản phẩm của owner: CoT thông thường được phép hiển thị; chỉ chặn canary/secret exfiltration.
- Mọi tiêu chí bắt buộc phải chạy thật trên SQLite và PostgreSQL/pgvector qua CI; không ghi skip là PASS, không sửa dữ liệu khách/EC2.
