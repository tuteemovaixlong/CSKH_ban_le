# Phase 5 — Identity, Sales Simulator và Complaint E2E

Phase 5 tiếp nối Phase 4 sau merge `8868c5c498b1c64241bc791eb0166d82415cfeb0`. Mục tiêu là tạo một lane dev/synthetic có thể chứng minh:

`Google test account → customer binding → sales-system event → order visibility → complaint chat → proposal/confirmation → audit`.

Đọc theo thứ tự:

1. [Acceptance matrix cấp dự án](../03_EVALUATION/ACCEPTANCE_MATRIX.md)
2. [PHASE_5_PLAN.md](PHASE_5_PLAN.md)
3. [PHASE_5_ACCEPTANCE_CRITERIA.md](PHASE_5_ACCEPTANCE_CRITERIA.md)
4. [PHASE_5_EXECUTION_HANDOFF.md](PHASE_5_EXECUTION_HANDOFF.md)
5. [PHASE_5_D_EXECUTION_HANDOFF.md](PHASE_5_D_EXECUTION_HANDOFF.md) — trigger và handoff cho immutable candidate/CI verification; pgvector test phải chạy không skip.
6. [REVIEW_GEMINI_P5_D_2026-10-13.md](REVIEW_GEMINI_P5_D_2026-10-13.md) và [PHASE_5_D_EVIDENCE.md](PHASE_5_D_EVIDENCE.md) — current implementation review và raw verification logs; D-R2/D-R3 PASS, D-R1 CI evidence pending; chưa phải acceptance sign-off.

Phase 5 không thay đổi frozen benchmark Phase 4, không dùng dữ liệu khách thật, không cấp G5/G6 và không chạy full measurement khi chưa có approval riêng.
