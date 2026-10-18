# Phase 5-E — Codex Re-review Handoff (2026-10-18)

## Trạng thái và candidate

P5-E candidate PR #43 đã sẵn sàng cho **CODEX RE-REVIEW**, nhưng overall verdict vẫn **CHANGES REQUIRED**. Không diễn giải trạng thái này thành merge, deploy hoặc P5-E/Phase 5 PASS.

- Candidate head: `baa70b15731fd82b909c36e0b89cb7d9b41ca342`
- Base: `44540eab516831d5c8232dd80392b8e20c6cd47e`
- Tested merge ref: `d3655b89e165ba09db53ac7ad13e9b4a787cb3fe`
- PR: [#43](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/43)
- CI: [39099835679](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39099835679)
- Ops Console: [39099835635](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39099835635)
- CI/Ops: 5/5 SUCCESS theo metadata; không suy ra raw test count/backend coverage.
- Local targeted P5-E: 14/14 PASS, 0 skip.

Nguồn đọc chuẩn là [review độc lập](REVIEW_ARGON_P5_E_2026-10-18.md), [P5-E plan](PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md), [acceptance criteria](PHASE_5_E_ACCEPTANCE_CRITERIA.md), [manual-test review](PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md), [acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md) và [current status](../CURRENT_PROJECT_STATUS.md).

## Bounded findings cần đối chiếu

Các finding dưới đây map vào 14 criteria hiện có; không thêm gate hoặc mở bug-hunt ngoài scope:

- **AI1:** tool arguments/results và legacy replay còn cần chứng minh canary/prompt không lọt qua bề mặt trung gian.
- **AI2:** `request_human_support` có side effect khi intent là read-only; phải giữ đúng action/confirmation boundary.
- **AI4:** final answer phải ground vào tool result, gồm missing/unknown và list truncation.
- **ADM2:** phải áp tenant scope trước search limit; limit không được làm rộng phạm vi.
- **ADM3:** stale tenant selection phải bị từ chối/làm mới trước lifecycle action.
- **ADM4:** còn thiếu reset và có mismatch khi clear per-membership override; giữ đúng UTC, bounds và trạng thái quota.
- **DATA1:** generated-ID regex edge và giới hạn với legacy order; display label không thành nguồn sự thật.
- **R6:** evidence/docs phải map đúng head → base → tested merge ref, CI/Ops metadata, local count/skip và limitations.

## Cách đóng re-review

1. Đối chiếu từng finding với đúng AC và evidence của candidate; giữ các positive controls và phân biệt SQLite với PostgreSQL/pgvector.
2. Xác minh final output, persisted/replay surfaces, tenant scoping, lifecycle confirmation, quota reset/clear semantics và demo-label provenance; không dùng metadata CI làm bằng chứng raw coverage.
3. Kiểm tra evidence mapping và liên kết docs; ghi rõ mọi limitation. Không tự sửa verdict review thành PASS.
4. Dừng sau re-review/evidence update. Không merge/deploy, AWS/SSM/EC2, OAuth live, production DB/config, benchmark/full measurement hoặc paid model tests.

## Chính sách không đổi

Raw CoT được owner chấp nhận cho bản khóa luận; không hide/filter/change CoT và không biến quyết định này thành gate. Không sửa P5-K1…K8, G4–G7, frozen benchmark, order/product/catalog facts hoặc dữ liệu khách thật. P5-E và bounded AI-lane G4 là hai track độc lập; P5-F/G5 chỉ được xem xét khi đủ evidence của cả hai.
