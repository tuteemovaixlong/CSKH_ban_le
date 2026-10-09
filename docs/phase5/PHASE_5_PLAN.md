# Phase 5 Plan — Identity-to-Complaint Dev Lane

## Mục tiêu

Xây một đường kiểm thử dev/synthetic có dữ liệu bán hàng mô phỏng và cùng một danh tính khách hàng xuyên suốt Google OAuth, dữ liệu đơn hàng, hội thoại khiếu nại và audit. Kết quả phải đủ rõ để quyết định có xin G5 lane preflight hay dừng sửa.

## Hiện trạng đầu vào

- Merged SHA: `8868c5c498b1c64241bc791eb0166d82415cfeb0`.
- EC2 deployment: image và các container healthy.
- G4 smoke gần nhất FAIL vì customer `C-001` trong tenant `e2e-live-smoke` bị `customer_reserved`.
- Google OAuth đã có state/nonce, profile `email/name/sub`, role mapping và session binding.
- `/api/session` hiện trả tenant, principal, customer, name và role.
- `live-e2e.py` hiện còn hardcode tenant/customer/order; cần cô lập trước khi chạy lại.
- Chưa có adapter hoàn chỉnh nhận event đơn hàng từ một hệ thống bán hàng bên ngoài.

## Điều kiện liền kề bắt buộc: G2 sau merge

Trước khi bắt đầu P5-A, phải chạy G2 offline replay trên đúng merged SHA `8868c5c498b1c64241bc791eb0166d82415cfeb0` (hoặc SHA merge mới được owner ghi nhận). G2 phải xác nhận CI/contracts, frozen hashes, mock250 (263 attempts, quality185/237) và `git diff --check`; lưu raw evidence. Nếu G2 FAIL hoặc thiếu evidence thì dừng, không deploy/smoke. Bước này không phải G5 và không cấp quyền chạy full/live measurement.

## Phạm vi theo chặng

### P5-A — Smoke isolation

- Tham số hóa `E2E_TENANT`, `E2E_CUSTOMER`, `E2E_ORDER_ID`.
- Dùng tenant synthetic mới cho mỗi run hoặc một tenant resettable có owner rõ.
- Không xóa reservation cũ và không sửa trực tiếp PostgreSQL.
- G4 smoke kiểm health, image SHA, login, session binding, orders, logout và revoke.

### P5-B — Google test identity

- Dùng Google account dành riêng cho test, không dùng email/PII khách thật.
- Pin issuer, `sub`, email verified và tenant mapping.
- Không dùng email làm khóa duy nhất nếu đã có `sub`; lưu external identity mapping có audit.
- Không seed đơn demo khi `data_mode=live`; dữ liệu phải đến từ simulator/import.

### P5-C — Sales simulator và import contract

Simulator chỉ chạy offline/dev và phát event JSON qua adapter được kiểm soát. Mỗi event phải có `source_system`, `event_id`, `tenant`, `external_customer_id`, `order_id`, trạng thái, items, total, currency, timestamp và signature.

Adapter phải kiểm schema, HMAC/signature, tenant/customer mapping, timestamp hợp lệ và idempotency theo `source_system + event_id`. Adapter ghi audit event và dùng service boundary; không cho simulator ghi thẳng DB.

### P5-D — Cùng account chạy complaint E2E

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



