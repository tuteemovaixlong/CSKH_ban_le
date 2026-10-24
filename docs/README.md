# RetailOps documentation

Đây là điểm vào duy nhất của bộ tài liệu. Đọc theo câu hỏi bạn cần trả lời. Cập nhật vận hành ngày 2026-10-24: owner-pasted DB output báo đã xóa các target legacy orders ([biên bản cleanup](04_OPERATIONS/ORDER_DATA_CLEANUP_2026-10-24.md)), PR #45 đã merge vào `main` tại `ae0a2e417baf0bc8011bdb62fc9cf3f7741aac36`, và workstream chặn tự tạo đơn mẫu khi đăng nhập Google đang thực thi theo [DEMO_ORDER_SEEDING_REMEDIATION_HANDOFF_2026-10-24.md](phase5/DEMO_ORDER_SEEDING_REMEDIATION_HANDOFF_2026-10-24.md).

## Workstream hiện hành

- [Phase 5 — Identity, Sales Simulator và Complaint E2E](phase5/README.md)
- [Kết quả cleanup đơn legacy trên database live (2026-10-24)](04_OPERATIONS/ORDER_DATA_CLEANUP_2026-10-24.md)
- [Handoff & thực thi remediation auto-seed khi Google login](phase5/DEMO_ORDER_SEEDING_REMEDIATION_HANDOFF_2026-10-24.md)
- [Phase 5 Fix A — Store Manager navigation & demo-order cleanup](phase5_fix_A/README.md) ([review](phase5_fix_A/PHASE_5_FIX_A_REVIEW_2026-10-20.md) · [criteria](phase5_fix_A/PHASE_5_FIX_A_ACCEPTANCE_CRITERIA.md) · [evidence](phase5_fix_A/PHASE_5_FIX_A_EVIDENCE.md) · [handoff](phase5_fix_A/PHASE_5_FIX_A_EXECUTION_HANDOFF.md))
- [Phase 5 Fix B — controlled demo-order cleanup](phase5_fix_B/README.md) ([review R6](phase5_fix_B/PHASE_5_FIX_B_REVIEW_R6_2026-10-24.md) · [criteria](phase5_fix_B/PHASE_5_FIX_B_ACCEPTANCE_CRITERIA.md) · [evidence](phase5_fix_B/PHASE_5_FIX_B_EVIDENCE.md) · [handoff](phase5_fix_B/PHASE_5_FIX_B_EXECUTION_HANDOFF.md)) — [PR #45](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/45) merged vào `main` tại `ae0a2e417baf0bc8011bdb62fc9cf3f7741aac36`.
- [Phase 4 execution handoff](phase4/PHASE_4_EXECUTION_HANDOFF.md)

| Muốn hiểu | Mở |
|---|---|
| Hệ thống là gì và các thành phần nằm ở đâu | [Project overview](00_OVERVIEW/PROJECT_OVERVIEW.md) → [Codebase map](00_OVERVIEW/CODEBASE_MAP.md) |
| Model, agent, prompt và RAG chạy thế nào | [AI system index](01_AI_SYSTEM/README.md) |
| Dữ liệu, hash và công thức chỉ số | [Data contracts](02_DATA_CONTRACTS/DATA_CONTRACT.md) |
| Quy trình nghiệm thu và thí nghiệm | [Evaluation protocol](03_EVALUATION/EVALUATION_PROTOCOL.md) |
| Trạng thái nghiệm thu toàn dự án | [Acceptance matrix](03_EVALUATION/ACCEPTANCE_MATRIX.md) |
| CI, deploy, rollback và rủi ro | [Operations runbook](04_OPERATIONS/RUNBOOK.md) |
| Quyết định và thuật ngữ viết tắt | [Decision log](04_OPERATIONS/DECISION_LOG.md) · [Glossary](00_OVERVIEW/PROJECT_GLOSSARY.md) |

## Năm tầng

1. [00_OVERVIEW](00_OVERVIEW/PROJECT_OVERVIEW.md) — bối cảnh, bản đồ code và glossary.
2. [01_AI_SYSTEM](01_AI_SYSTEM/README.md) — model, agent, prompt, RAG, safety và reproducibility.
3. [02_DATA_CONTRACTS](02_DATA_CONTRACTS/DATA_CONTRACT.md) — dữ liệu đầu vào và metric contract.
4. [03_EVALUATION](03_EVALUATION/EVALUATION_PROTOCOL.md) — protocol, gate và experiment log.
5. [04_OPERATIONS](04_OPERATIONS/RUNBOOK.md) — CI/CD, vận hành, risk và decision records.

`_digest/` là lớp trích xuất có citation để các public docs tham chiếu. `phase4/` giữ hồ sơ nghiệm thu chi tiết. [Audit file classification](_audit/FILE_CLASSIFICATION.md) là inventory, không phải tài liệu kiến trúc.

## Mốc nguồn

Các digest giữ snapshot `8a666fcce464c96b1dd5fc6848a2d4168c6505d1`. [G2 evidence](phase5/PHASE_5_G2_EVIDENCE_8868c5c.md) ghi PASS trên `8868c5c`; P5-B đã merge/deploy tại `80f5156`. P5-C đã merge tại `a34b479`; deploy workflow rerun `38335308481`, job `115122302562` SUCCESS. Snapshot EC2 `2026-10-13T04:36:57Z` chỉ là runtime evidence lịch sử, không xác nhận trạng thái EC2 hiện tại. **Workstream vận hành hiện tại là Phase 5 Fix B:** trên draft [PR #45](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/45) (R6 code/test candidate `1d09e7d330752d19bb8b4f9dab32e68ddffe53bb`, tested merge SHA `fd061059b3c4411136ba737478b462137e75bac4`), independent read-only review R6 (`0` findings) và GitHub Actions PostgreSQL/pgvector CI (`5/5 SUCCESS`, `0 skipped` trên các job PostgreSQL) đều đã PASS; merge/deploy và live cleanup vẫn blocked chờ phê duyệt và các gate vận hành còn lại. Xem [Fix B packet](phase5_fix_B/README.md), [current status](CURRENT_PROJECT_STATUS.md), [roadmap](PLAN_ROADMAP_INDEX.md) và [acceptance matrix](03_EVALUATION/ACCEPTANCE_MATRIX.md). **P5-DM vẫn là planned, chưa sẵn sàng triển khai:** canonical plan/CSV I/O-retention contract/criteria/evidence/handoff chưa có trong checkout; trạng thái và gate gap được ghi ở [Phase 5 index](phase5/README.md#p5-dm-store-data-management) và [acceptance matrix](03_EVALUATION/ACCEPTANCE_MATRIX.md#3d-p5-dm-store-data-management-gap). Main roadmap: hoàn tất/duyệt P5-E và P5-DM cùng evidence G4 theo các track độc lập; chỉ qua P5-F/G5 preflight khi đủ evidence đã được chấp nhận. Performance/full benchmark chưa được cho phép; operational smoke không tự cấp G5.
