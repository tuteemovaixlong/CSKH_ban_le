# Phase 5 Acceptance Criteria — Dev Identity and Sales-to-Complaint Lane

Phase 5 chỉ đạt khi toàn bộ tiêu chí dưới đây có evidence trên cùng commit của workstream. Đây là acceptance cho dev/synthetic lane, không phải G5/G6 approval.

**Điều kiện trước khi nghiệm thu:** G2 offline replay trên merged SHA phải PASS và có evidence gồm CI/contracts, frozen hashes, mock250 (263 attempts; quality185/237) và `git diff --check`. Thiếu G2 evidence thì Phase 5 dừng, không tính P5-K1…P5-K8.

| ID | Tiêu chí | PASS evidence |
|---|---|---|
| P5-K1 | Smoke isolation | Smoke không dùng tenant/customer bị reservation; không sửa/xóa dữ liệu cũ; report ghi identity tuple. |
| P5-K2 | Runtime health | Image đúng merged/deployed SHA; web/admin/PostgreSQL healthy; health contract PASS. |
| P5-K3 | Google identity | Dedicated test account OAuth PASS; state/nonce, issuer, verified email và `sub` được kiểm; session trả đúng tenant/principal/customer/role. |
| P5-K4 | External mapping | Mapping `external_customer_id → RetailOps customer_id` có tenant scope, audit và không dùng email đơn độc làm khóa. |
| P5-K5 | Event contract | Event schema, signature, timestamp, tenant binding và idempotency PASS; replay cùng event không tạo duplicate. |
| P5-K6 | Order visibility | Event import tạo/ cập nhật đúng order; customer chỉ đọc được order của mình; truy cập customer khác bị từ chối. |
| P5-K7 | Complaint workflow | Cùng Google customer session gửi complaint; dispute worker đọc đúng order/policy, tạo proposal/handoff và không mutation trước confirmation. |
| P5-K8 | Confirmation and audit | Confirmation idempotent; trạng thái/audit/event khớp; raw report và checksums được lưu. |

## Tiến độ theo chặng

- **P5-K1 (Smoke isolation):** PASS trên PR #37 `dd0947a`; latest controlled smoke on deployed SHA `80f51569b3bef5ae0793bac1593fb91e39558477` also PASS (report `/opt/retailops/e2e-reports/LIVE_SMOKE_20261011T074654Z.json`).
- **P5-K2 (Runtime health):** PASS operationally trên merged SHA `80f51569b3bef5ae0793bac1593fb91e39558477`; deploy workflow 38119061325 SUCCESS, web/admin/PostgreSQL/Caddy healthy, smoke report `/opt/retailops/e2e-reports/LIVE_SMOKE_20261011T074654Z.json`.
- **P5-K3 (Google identity):** Offline implementation PASS trên PR P5-B (xem [PHASE_5_B_EVIDENCE.md](PHASE_5_B_EVIDENCE.md)); Google OAuth thật live PENDING (chờ môi trường live/owner review).
- **P5-K4 (External mapping):** REMEDIATED, chờ re-review PR #39 — N2/N4 và PR #39 (1)/(2) đã sửa: prior business import là nguồn sự thật tối thượng, cấm mapping tách cùng external ID; DDL/migration PostgreSQL có; mapping tự phục hồi sau lỗi identity; SQLite + PostgreSQL contract PASS (xem [PHASE_5_C_EVIDENCE.md](PHASE_5_C_EVIDENCE.md)). Chưa tính PASS cho tới khi reviewer xác nhận CI.
- **P5-K5 (Event contract):** REMEDIATED, chờ re-review PR #39 — N3 và PR #39 (2)/(3)/(4) đã sửa: đúng 11 trường, strict integer, cấm NaN/Infinity, từ chối event collision 409, exact replay bypass drift-check sau 300s để heal mapping; 15 test gốc + 30 regression test PASS. Chưa tính PASS cho tới khi reviewer xác nhận CI.
- **P5-K6 (Order visibility):** REMEDIATED, chờ re-review PR #39 — N1 đã sửa: `order_id` đã có không thể đổi chủ (409 `order_owner_conflict`), regression test SQLite và PostgreSQL. Chưa tính PASS cho tới khi reviewer xác nhận CI.
- **P5-K7…P5-K8:** PENDING đến P5-D (Complaint workflow E2E và confirmation).

## Điều kiện dừng

FAIL bất kỳ P5-K1…P5-K8 thì dừng tại tiêu chí đó. Không chạy full benchmark, không ghi `READY FOR MEASUREMENT`, không dùng dữ liệu thật và không bypass guard để làm PASS.
