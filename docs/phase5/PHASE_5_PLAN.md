# Phase 5 Plan — Identity-to-Complaint Dev Lane

## Mục tiêu

Xây một đường kiểm thử dev/synthetic có dữ liệu bán hàng mô phỏng và cùng một danh tính khách hàng xuyên suốt Google OAuth, dữ liệu đơn hàng, hội thoại khiếu nại và audit. Kết quả phải đủ rõ để quyết định có xin G5 lane preflight hay dừng sửa.

## Hiện trạng đầu vào

- G2 baseline SHA: `8868c5c498b1c64241bc791eb0166d82415cfeb0`.
- Current merged SHA: `a34b479eeb633ba55090f43a1f4ed7d85f6a3c9a`; deploy run `38335308481` rerun/job `115122302562` succeeded at 2026-10-13 11:06 (+07). Owner snapshot at `2026-10-13T04:36:57Z` confirms web/admin running `deployed.env` digest `sha256:2c058277…`, PostgreSQL healthy, and Caddy public/admin overlay networks and mount. Both post-deploy smoke reports pass and P5-K1 is closed (owner-pasted report excerpts; see acceptance/evidence).
- EC2 deployment và 4 containers được quan sát healthy ngày 2026-10-11; deploy workflow 38119061325 và controlled HTTPS smoke PASS. Report: `/opt/retailops/e2e-reports/LIVE_SMOKE_20261011T074654Z.json`. Không suy ra trạng thái nguồn EC2 hiện tại từ snapshot này.
- Reservation cũ `e2e-live-smoke/C-001` vẫn được giữ nguyên và không dùng làm smoke.
- Google OAuth đã có state/nonce, profile `email/name/sub`, role mapping và session binding.
- `/api/session` hiện trả tenant, principal, customer, name và role.
- `live-e2e.py --mode smoke` đã nhận tenant/customer/order; full mode giữ baseline.
- P5-C candidate `3ff5d0e` (45/45 targeted + independent sign-off) đã merge thành `a34b479` và deploy; runtime digest/health/topology cùng P5-K1 smoke PASS. Xem [evidence](PHASE_5_C_EVIDENCE.md).

## Điều kiện liền kề bắt buộc: G2 sau merge

Trước khi bắt đầu P5-A, phải chạy G2 offline replay trên đúng merged SHA `8868c5c498b1c64241bc791eb0166d82415cfeb0` (hoặc SHA merge mới được owner ghi nhận). G2 phải xác nhận CI/contracts, frozen hashes, mock250 (263 attempts, quality185/237) và `git diff --check`; lưu raw evidence. Nếu G2 FAIL hoặc thiếu evidence thì dừng, không deploy/smoke. Bước này không phải G5 và không cấp quyền chạy full/live measurement.

## Phạm vi theo chặng

### P5-A — Smoke isolation — DONE

- Tham số hóa `E2E_TENANT`, `E2E_CUSTOMER`, `E2E_ORDER_ID`.
- Dùng tenant synthetic mới cho mỗi run hoặc một tenant resettable có owner rõ.
- Không xóa reservation cũ và không sửa trực tiếp PostgreSQL.
- G4 smoke kiểm health, image SHA, login, session binding, orders, logout và revoke.

Evidence: merged/deployed `80f5156`, image `sha256:64d15c4aee29...`, smoke report ở trên.

Nguồn hiện tại: log owner gửi ngày 2026-10-10, chưa đọc trực tiếp raw JSON. Operational smoke này không gọi Google OAuth/model; G4 per-lane real-model/DB/KB và G5 vẫn chưa đủ evidence.

### P5-B — Google test identity — DONE / MERGED / DEPLOYED

- Cấu hình tenant cửa hàng demo rõ ràng (`default_tenant_id` hoặc env `RETAILOPS_DEMO_TENANT_ID` / `GOOGLE_AUTH_TENANT_ID`); loại bỏ hoàn toàn `ORDER BY id LIMIT 1` trong `retailops/identity/persistent.py`. Tenant mỗi smoke run không thể bị chọn làm cửa hàng cho khách Google login.
- Dùng Google test identity mapping offline, không dùng email/PII khách thật; không cần credential thật trong repository.
- Pin issuer, `sub`, email verified và tenant mapping.
- Không dùng email làm khóa duy nhất nếu đã có `sub`; lưu external identity mapping có audit (`identity_events`).
- Không seed đơn demo khi `data_mode=live`; dữ liệu phải đến từ simulator/import.
- Kiểm tra `/api/session`, `/api/profile` và tenant/customer isolation.
- Evidence: [PHASE_5_B_EVIDENCE.md](PHASE_5_B_EVIDENCE.md), suite `tests/test_phase5_google_identity.py` (12/12 PASS).

Real Google OAuth live remains pending; the controlled smoke does not call Google OAuth or model inference.

### P5-C — Sales simulator và import contract — MERGED / DEPLOYED / ACCEPTED

Simulator chỉ chạy offline/dev và phát event JSON qua adapter được kiểm soát. Mỗi event có đủ 11 trường: `source_system`, `event_id`, `tenant`, `external_customer_id`, `order_id`, trạng thái, items, total, currency, timestamp và signature.

Adapter kiểm schema, HMAC/signature, tenant/customer mapping, timestamp hợp lệ và idempotency theo `source_system + event_id`. Adapter ghi audit event và dùng service boundary; simulator không ghi thẳng DB; không dùng email làm khóa; rollback sạch sẽ khi lỗi DB.
Evidence: [PHASE_5_C_EVIDENCE.md](PHASE_5_C_EVIDENCE.md), suite P5-C + regression **45/45 PASS**, offline CI run `38335308462` SUCCESS trên merged `a34b479`; N1–N4 đã sửa và independent sign-off PASS trước merge. Deploy run `38335308481` / job `115122302562` SUCCESS; post-deploy runtime digest/health/topology PASS. Both smoke reports PASS with expected image, distinct synthetic tenants/identity tuples, checks true, credentials revoked; P5-K1 PASS.

### P5-D — Complaint E2E on the same customer identity — implementation re-review PASS; candidate CI pending

Codex re-review xác nhận D-R2 lifecycle binding/replay/checksum test và D-R3 notebook sync PASS. D-R1 có substantive disposable PostgreSQL/pgvector assertions (real ingest/search and complaint path), nhưng test bị **SKIPPED local** vì thiếu DSN; chưa có immutable candidate SHA/CI. Do đó P5-K7/K8 acceptance pending CI chạy test pgvector không skip trên cùng candidate. See [current review](REVIEW_GEMINI_P5_D_2026-10-13.md), [current evidence](PHASE_5_D_EVIDENCE.md), [current recheck set](evidence/P5_D_REVIEW_20261013_CURRENT/), and [candidate-verification handoff](PHASE_5_D_EXECUTION_HANDOFF.md). Chưa owner review/merge/deploy/live; P5-K3 OAuth là prerequisite riêng cho live work.

1. Google test account đăng nhập.
2. Import `order.created`/`order.paid` cho đúng external customer.
3. Xác nhận `/api/session` và `/api/orders` chỉ thấy dữ liệu của customer đó.
4. Gửi complaint về đơn đã import.
5. Supervisor định tuyến dispute, đọc order và policy/RAG đúng tenant.
6. Tạo proposal hoặc human handoff; không tự mutation.
7. Khách xác nhận bằng cùng session.
8. Kiểm trạng thái đơn, audit event và replay idempotency.

### P5-E — G5 preflight liền kề

Sau khi P5-A đến P5-D PASS, lập lane manifest với provider/model/endpoint/config/KB/fixture hashes, quota, cost cap, stop rule và raw report location. Đây chỉ là hồ sơ xin G5; chưa được chạy full 250-case.

## Ngoài phạm vi

Không dùng dữ liệu production/PII thật; không sửa frozen benchmarks; không mở lại K1–K8; không chạy live paid/full measurement; không đổi metric để làm smoke PASS; không bypass collision/reconciliation guard.

## Deliverables

- Smoke runner được parameterize và report có tenant/customer/order identity.
- Google test identity mapping record và test.
- Sales simulator + adapter + event fixtures + replay test.
- Complaint E2E report dùng cùng customer session.
- Cập nhật [PHASE_5_ACCEPTANCE_CRITERIA.md](PHASE_5_ACCEPTANCE_CRITERIA.md), handoff và project status.
