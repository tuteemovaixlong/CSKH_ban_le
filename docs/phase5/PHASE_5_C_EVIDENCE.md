# Phase 5 P5-C Evidence — Sales Simulator & Service-Boundary Import Contract

> **Mã tài liệu**: `PHASE_5_C_EVIDENCE`  
> **Chặng**: Phase 5 — Chặng P5-C (Sales simulator và import contract)  
> **Base SHA**: `80f51569b3bef5ae0793bac1593fb91e39558477` (Merged PR #38 / P5-B deploy)  
> **Branch**: `feat/phase5-sales-simulator-import`  
> **Trạng thái**: OFFLINE/DEV COMPLETED — Chờ Owner Review PR  
> **Phạm vi tuân thủ**: Hoàn toàn offline/dev; simulator KHÔNG ghi thẳng DB; KHÔNG dùng email làm khóa; KHÔNG làm P5-D; KHÔNG gọi Google live OAuth; KHÔNG deploy; KHÔNG đo lường model/paid; KHÔNG mở lại K1–K8.

---

## 1. Mục tiêu và Tiêu chí Nghiệm thu P5-C

Chặng P5-C thiết lập bộ phát sự kiện bán hàng giả lập (`SalesSimulator`) và bộ nhận dữ liệu qua ranh giới dịch vụ (`SalesImportAdapter`), bảo đảm 3 tiêu chí cốt lõi của Phase 5:

1. **P5-K4 (External mapping)**: Ánh xạ `(tenant_id, source_system, external_customer_id) -> RetailOps customer_id` có phạm vi tenant rõ ràng, ghi nhận audit trail vào `identity_events`, và tuyệt đối **không dùng email làm khóa** (mã định danh do hệ thống nguồn cấp).
2. **P5-K5 (Event contract & Idempotency)**: Hợp đồng event chuẩn 11 trường, xác thực HMAC-SHA256, kiểm tra độ lệch timestamp, kiểm tra tenant, bảo đảm tính lũy thừa (idempotency) theo `(source_system, event_id)` — replay không tạo đơn trùng hay audit trùng; giao dịch nguyên tử có rollback toàn diện khi lỗi DB.
3. **P5-K6 (Order visibility & Isolation)**: Sự kiện import tạo/cập nhật đơn hàng và chi tiết sản phẩm (`order_items`); khách hàng chỉ đọc được đơn của chính mình; truy cập đơn của khách hàng khác bị chặn (404 `order_not_found`).

---

## 2. Thiết kế Kiến trúc & Ranh giới Dịch vụ

### 2.1. Hợp đồng Event Chuẩn hóa (Canonical Event Schema)

Mỗi event bao gồm đúng 11 trường bắt buộc:

| Trường | Kiểu dữ liệu | Ràng buộc & Quy tắc |
|---|---|---|
| `source_system` | `str` | Hệ thống phát sinh (ví dụ: `sales_simulator`, `pos_online`, `tiktok_shop`, `shopee`). |
| `event_id` | `str` | Định danh duy nhất của sự kiện từ nguồn phát sinh. |
| `tenant` | `str` | Mã cửa hàng nhận đơn (`tenant_id`). Phải tồn tại và đang `active=1`. |
| `external_customer_id` | `str` | Mã khách hàng tại nguồn. **Cấm dùng email** (từ chối nếu chứa `@` hoặc định dạng email). |
| `order_id` | `str` | Mã đơn hàng tại nguồn (ví dụ: `O-SIM-001`). |
| `status` | `str` | Trạng thái: `pending`, `confirmed`, `shipping`, `delivered`, `cancelled`. |
| `items` | `list[dict]` | Danh sách sản phẩm: `product_id`, `product_title`, `quantity` ($\ge 1$), `unit_price` ($\ge 0$). |
| `total` | `int/float` | Tổng tiền đơn hàng, phải khớp chính xác với $\sum (\text{quantity} \times \text{unit\_price})$. |
| `currency` | `str` | Mã tiền tệ chuẩn (ví dụ: `VND`). |
| `timestamp` | `str` | Thời gian phát sinh ISO-8601 UTC. Kiểm tra chống trôi thời gian (drift tolerance). |
| `signature` | `str` | Chữ ký HMAC-SHA256 64 ký tự hex tính trên chuỗi JSON canonical của 10 trường trên. |

### 2.2. Simulator Cô lập Hoàn toàn (Zero Direct DB Writes)

- `SalesSimulator` (`retailops/sales/simulator.py`) hoạt động hoàn toàn ở tầng ngoài (offline/dev).
- **Không import `sqlite3` hay kết nối DB**: Simulator chỉ tạo dict sự kiện, ký HMAC và phát đi.
- Mọi thao tác ghi dữ liệu bắt buộc phải qua `SalesImportAdapter.ingest_event(...)`.

### 2.3. Ranh giới Nhập liệu & Giao dịch Nguyên tử (`SalesImportAdapter`)

- **Bước 1 — Schema & Non-email Validation**: Kiểm tra đủ 11 trường, kiểu dữ liệu, ràng buộc tổng tiền và cấm email.
- **Bước 2 — Timestamp Drift Check**: Từ chối các event quá cũ ($> 300\text{s}$) hoặc tương lai ($> 60\text{s}$) để chống replay attack.
- **Bước 3 — Tenant Check**: Kiểm tra tenant tồn tại và đang kích hoạt trong `IdentityStore`.
- **Bước 4 — HMAC Verification**: Đối chiếu chữ ký với secret của `(source_system, tenant)` bằng `hmac.compare_digest`.
- **Bước 5 — Tenant-Scoped Customer Mapping**:
  - Tra cứu trong `external_customer_mappings`.
  - Nếu chưa có: cấp phát `customer_id` opaque dạng `cust_<uuid4_hex[:16]>` (khắc phục N08).
- **Bước 6 — Atomic Transaction trong Business Store**:
  - Kiểm tra bảng `imported_events` theo `(source_system, event_id)`: nếu đã xử lý, trả về `is_replay=True, status="already_processed"` mà không ghi đè dữ liệu.
  - Tạo hồ sơ khách hàng `customers` trong DB tenant nếu chưa có.
  - Ghi đơn hàng vào `orders` (bảo đảm ràng buộc status nội bộ: `pending`, `delivered`, `cancelled`).
  - Ghi chi tiết từng sản phẩm vào `order_items`.
  - Ghi nhật ký kiểm toán vào `business_events` (`kind='order_imported'`).
  - Ghi nhận `imported_events` cho lần kiểm tra idempotency tiếp theo.
  - **Rollback Guard**: Nếu có bất kỳ lỗi nào trong giao dịch (lỗi DB, constraint, disk), toàn bộ thay đổi trong DB tenant được rollback sạch sẽ; mapping mới ở identity store không được lưu.
- **Bước 7 — Post-commit Mapping & Audit**:
  - Lưu ánh xạ mới vào `external_customer_mappings` và ghi `identity_events(kind='external_customer_mapped')`.
- **Bước 8 — Cache Invalidation**:
  - Gọi `ToolCache.invalidate(customer=customer_id, tenant_id=tenant_id, order_id=order_id)` làm mất hiệu lực cache cũ của công cụ.

---

## 3. Bằng chứng Thực thi Kiểm thử Offline (Test Evidence)

Toàn bộ 15 test ca của bộ kiểm thử P5-C (`tests/test_phase5_sales_simulator_import.py`) đã chạy thành công 100%:

```text
...............
----------------------------------------------------------------------
Ran 15 tests in 1.960s

OK
```

### Chi tiết các ca kiểm thử:

| Test Case | Tiêu chí | Kết quả | Mô tả xác nhận |
|---|---|:---:|---|
| `test_simulator_emits_valid_canonical_event_without_db` | P5-C | **PASS** | Simulator phát event đủ 11 trường, không có method DB, không ghi vào `orders`. |
| `test_hmac_signature_verification_and_tamper_rejection` | P5-C | **PASS** | Chữ ký hợp lệ được chấp nhận; sửa đổi total, order_id, customer_id hoặc sai secret bị từ chối 401. |
| `test_schema_validation_rejects_missing_fields` | P5-C | **PASS** | Lần lượt bỏ từng trường trong 11 trường bắt buộc đều bị từ chối 400 `missing_event_field`. |
| `test_schema_validation_rejects_invalid_status_and_items` | P5-C | **PASS** | Trạng thái lạ, items rỗng hoặc số lượng $\le 0$ bị từ chối 400. |
| `test_schema_strictly_rejects_email_as_external_customer_id` | P5-K4 | **PASS** | Cấm email: các địa chỉ email đều bị chặn với mã lỗi `invalid_external_customer_id`. |
| `test_timestamp_drift_validation` | P5-C | **PASS** | Event quá hạn (>300s) hoặc tương lai (>60s) bị từ chối 400; thời gian hợp lệ được duyệt. |
| `test_tenant_validation_rejects_unknown_or_inactive` | P5-C | **PASS** | Tenant không tồn tại báo 404 `tenant_not_found`; tenant bị vô hiệu hóa báo 400 `tenant_inactive`. |
| `test_tenant_scoped_customer_mapping_and_cross_tenant_isolation` | P5-K4 | **PASS** | Cùng `external_customer_id` ở Tenant A và Tenant B ánh xạ ra 2 `customer_id` khác biệt; có audit event. |
| `test_explicit_customer_link` | P5-K4 | **PASS** | Gán trước `external_customer_id` vào tài khoản khách hàng có sẵn (Google user) hoạt động chính xác. |
| `test_idempotent_event_ingestion_and_replay_detection` | P5-K5 | **PASS** | Gửi lại cùng event: trả về `is_replay=True`, không tạo đơn thứ hai, không nhân bản audit log. |
| `test_atomic_rollback_on_database_error_leaves_no_traces` | P5-C | **PASS** | Gặp lỗi DB giữa chừng: rollback 100%, không còn đơn, không còn items, không rò rỉ mapping. |
| `test_customer_order_visibility_and_isolation` | P5-K6 | **PASS** | Khách 1 chỉ thấy đơn của khách 1; khách 2 không thấy đơn khách 1; truy vấn chéo báo 404. |
| `test_multi_item_order_persists_to_order_items` | P5-K6 | **PASS** | Đơn nhiều sản phẩm lưu đúng từng dòng vào `order_items` với subtotal và summary name. |
| `test_tool_cache_invalidation_after_import` | P5-C | **PASS** | `ToolCache.invalidate` được gọi ngay sau khi commit đơn hàng mới. |
| `test_pre_signed_fixtures_validation` | P5-C | **PASS** | Các fixture mẫu có sẵn (`single_item`, `multi_item`) đều vượt qua kiểm tra chữ ký và schema. |

### Kiểm thử Hồi quy Toàn diện (Regression Check):
```text
Ran 62 tests in 15.662s

OK
```
Bao gồm: `test_phase5_sales_simulator_import.py`, `test_phase5_google_identity.py`, `test_schema_migration.py`, `test_persistent_identity.py`, `test_business_api.py`.

---

## 4. Trạng thái Nghiệm thu Tiêu chí Phase 5

- [x] **P5-K1 (Smoke isolation)**: PASS trên commit `80f5156` (report `/opt/retailops/e2e-reports/LIVE_SMOKE_20261011T074654Z.json`).
- [x] **P5-K2 (Runtime health)**: PASS trên commit `80f5156` (deploy workflow 38119061325).
- [x] **P5-K3 (Google identity)**: PASS offline trên P5-B (12/12 tests PASS).
- [x] **P5-K4 (External mapping)**: **PASS** — Ánh xạ `external_customer_id` theo tenant scope, không dùng email làm khóa, có audit trail.
- [x] **P5-K5 (Event contract)**: **PASS** — Hợp đồng 11 trường, HMAC, timestamp check, idempotency/replay và atomic rollback.
- [x] **P5-K6 (Order visibility)**: **PASS** — Đơn hàng và chi tiết `order_items` được lưu và cô lập theo customer.
- [ ] **P5-K7 (Complaint workflow)**: PENDING đến P5-D.
- [ ] **P5-K8 (Confirmation and audit)**: PENDING đến P5-D.

---

## 5. Kết luận P5-C

Chặng P5-C (Sales Simulator & Service-Boundary Import Contract) **ĐÃ HOÀN THÀNH ĐẦY ĐỦ VÀ ĐẠT (PASS)** theo đúng các yêu cầu:
- Sales simulator và adapter hoạt động độc lập ở dev/offline.
- Toàn bộ 15 ca kiểm thử và 62 ca hồi quy đều xanh.
- Đã sẵn sàng mở PR để chủ dự án review trước khi triển khai tiếp P5-D.
