# Phase 5 — Identity, Sales Simulator và Complaint E2E

Phase 5 tiếp nối Phase 4 sau merge `8868c5c498b1c64241bc791eb0166d82415cfeb0`. Mục tiêu là tạo một lane dev/synthetic có thể chứng minh:

`Google test account → customer binding → sales-system event → order visibility → complaint chat → proposal/confirmation → audit`.

## Đường đọc hiện hành

1. [Acceptance matrix cấp dự án](../03_EVALUATION/ACCEPTANCE_MATRIX.md)
2. Active acceptance audit snapshot — 2026-10-17 (`../03_EVALUATION/ACCEPTANCE_MATRIX_AUDIT_2026-10-17.md`)
3. [PHASE_5_PLAN.md](PHASE_5_PLAN.md)
4. [PHASE_5_ACCEPTANCE_CRITERIA.md](PHASE_5_ACCEPTANCE_CRITERIA.md)
5. [PHASE_5_EXECUTION_HANDOFF.md](PHASE_5_EXECUTION_HANDOFF.md)
6. **P5-E active one-time packet:** [independent candidate review 2026-10-18](REVIEW_ARGON_P5_E_2026-10-18.md) (**CHANGES REQUIRED R1–R6**, PR #43 / `7b94f9c…`, CI 5/5 SUCCESS), [manual-test review](PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md), [AI Trust & Account Operations plan](PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md), [acceptance criteria](PHASE_5_E_ACCEPTANCE_CRITERIA.md), [Argon execution handoff](PHASE_5_E_EXECUTION_HANDOFF.md). Covers read-only/action boundaries, account/quota governance, UX for 503/429, and demo-only display-label/inventory truth; it does not reopen P5-K1…K8. Raw CoT is owner-accepted for the thesis release; display toggle is optional backlog.

## Hồ sơ hoàn tất / lịch sử — chỉ tra cứu

- [P5-D review](REVIEW_GEMINI_P5_D_2026-10-13.md) and [P5-D evidence](PHASE_5_D_EVIDENCE.md) retain candidate, merge/deploy, and CI history. Their dated remediation instructions are historical; evidence Section 20 is the PR #41 candidate record and Section 21 is the latest post-PR #42 snapshot. The main [P5-D execution handoff](PHASE_5_D_EXECUTION_HANDOFF.md) stays at its original path for inbound references; evidence manifests retain earlier content hashes, not a claim that current bytes still match those snapshots. Its implementation trigger is consumed and must not be replayed.
- Five consumed remediation packets are grouped in `archive/P5-D-remediation/README.md`. Do not replay their triggers.
- K3/K7 independent review (`GOOGLE_LOGIN_AMBIGUOUS_TENANT_REVIEW_2026-10-16.md`), post-merge completion record (`P5_K3_K7_ONE_PASS_ARGON_HANDOFF_2026-10-17.md`), and older K3 incident history (`GOOGLE_LOGIN_TENANT_CONFIG_HANDOFF_ARGON.md`) record PR #41 (`8ef8278…`) and PR #42/P-604 (`44540ea…`, deploy run `39015954088`). Do not replay K3/K7 fix prompts; these records do not prove latest live acceptance.

Thứ tự gate hiện hành: P5-A…D / PR #42 → P5-E implementation và bounded AI-lane G4 evidence (hai track độc lập; có thể làm theo thứ tự khác nhau) → P5-F G5 preflight sau khi đủ evidence của cả hai → G5/G6/G7 theo gate. P5-F là mã mới cho G5-preflight doc-only đã từng được gọi P5-E; không có implementation phase riêng cho P5-F. Phase 5 không thay đổi frozen benchmark Phase 4, không dùng dữ liệu khách thật, không cấp G5/G6 và không chạy full/performance measurement khi chưa có approval riêng.
