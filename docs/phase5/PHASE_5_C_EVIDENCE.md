# Phase 5 P5-C Evidence — Sales Simulator & Service-Boundary Import Contract

> **Mã tài liệu**: `PHASE_5_C_EVIDENCE`  
> **Chặng**: Phase 5 — Chặng P5-C (Sales simulator và import contract)  
> **Base SHA**: `80f51569b3bef5ae0793bac1593fb91e39558477` (Merged PR #38 / P5-B deploy)  
> **Branch**: `feat/phase5-sales-simulator-import`  
> **Trạng thái**: N1–N4 ĐÃ SỬA OFFLINE/DEV + PostgreSQL thật cục bộ — CHỜ RE-REVIEW (chưa deploy, chưa P5-D)
>
> **Phạm vi tuân thủ**: Hoàn toàn offline/dev; simulator KHÔNG ghi thẳng DB; KHÔNG dùng email làm khóa; KHÔNG làm P5-D; KHÔNG gọi Google live OAuth; KHÔNG deploy; KHÔNG đo lường model/paid; KHÔNG mở lại K1–K8.

---

## 1. Mục tiêu và Tiêu chí Nghiệm thu P5-C

Chặng P5-C thiết lập bộ phát sự kiện bán hàng giả lập (`SalesSimulator`) và bộ nhận dữ liệu qua ranh giới dịch vụ (`SalesImportAdapter`), bảo đảm 3 tiêu chí cốt lõi của Phase 5:

1. **P5-K4 (External mapping)**: Ánh xạ `(tenant_id, source_system, external_customer_id) -> RetailOps customer_id` có phạm vi tenant rõ ràng, ghi nhận audit trail vào `identity_events`, và tuyệt đối **không dùng email làm khóa** (mã định danh do hệ thống nguồn cấp).
2. **P5-K5 (Event contract & Idempotency)**: Hợp đồng event chuẩn **đúng 11 trường** (không nhận trường thừa), kiểu số nghiêm ngặt, xác thực HMAC-SHA256, kiểm tra độ lệch timestamp, kiểm tra tenant, bảo đảm tính lũy thừa (idempotency) theo `(source_system, event_id)` — replay không tạo đơn trùng hay audit trùng; giao dịch nguyên tử có rollback toàn diện khi lỗi DB.
3. **P5-K6 (Order visibility & Isolation)**: Sự kiện import tạo/cập nhật đơn hàng và chi tiết sản phẩm (`order_items`); khách hàng chỉ đọc được đơn của chính mình; một event không bao giờ đổi chủ của `order_id` đã tồn tại; truy cập đơn của khách hàng khác bị chặn (404 `order_not_found`).

---

## 2. Thiết kế Kiến trúc & Ranh giới Dịch vụ

### 2.1. Hợp đồng Event Chuẩn hóa (Canonical Event Schema)

Mỗi event bao gồm **đúng** 11 trường (thiếu → `missing_event_field`, thừa → `unexpected_event_field`, đều 400):

| Trường | Kiểu dữ liệu | Ràng buộc & Quy tắc |
|---|---|---|
| `source_system` | `str` | Mã định danh `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}` (ví dụ: `sales_simulator`, `pos_online`, `tiktok_shop`, `shopee`). |
| `event_id` | `str` | Cùng định dạng mã định danh; duy nhất theo `(source_system, event_id)`. |
| `tenant` | `str` | Cùng định dạng mã định danh. Phải tồn tại và đang `active=1`. |
| `external_customer_id` | `str` | Mã khách hàng tại nguồn. **Cấm dùng email** (từ chối nếu chứa `@`); phải là mã định danh hợp lệ. |
| `order_id` | `str` | Mã đơn hàng tại nguồn (ví dụ: `O-SIM-001`), cùng định dạng mã định danh. |
| `status` | `str` | Trạng thái: `pending`, `confirmed`, `shipping`, `delivered`, `cancelled`. |
| `items` | `list[dict]` | 1–200 dòng. Mỗi dòng chỉ gồm `product_id`, `product_title`, `quantity`, `unit_price` (bắt buộc) và `variant_id`, `variant_name` (tùy chọn); trường khác → `unexpected_item_field`. |
| `total` | `int` | Số nguyên VND `0 ≤ total ≤ 10^12`, khớp chính xác $\sum (\text{quantity} \times \text{unit\_price})$. |
| `currency` | `str` | Mã ISO 3 chữ in hoa (ví dụ: `VND`). |
| `timestamp` | `str` | Thời gian phát sinh ISO-8601 UTC. Kiểm tra chống trôi thời gian (drift tolerance). |
| `signature` | `str` | Chữ ký HMAC-SHA256 64 ký tự hex tính trên chuỗi JSON canonical của 10 trường trên. |

**Kiểu số nghiêm ngặt (N3):** `quantity` (1…100 000), `unit_price` và `total` (0…10^12) phải là `int` thật. `bool` (kể cả `True == 1`), `float` (kể cả `1.0`, `450000.5`), chuỗi số và `None` đều bị từ chối; không còn `int()` làm tròn ngầm. Giới hạn trên bảo đảm giá trị luôn nằm trong `BIGINT` của PostgreSQL.

### 2.2. Simulator Cô lập Hoàn toàn (Zero Direct DB Writes)

- `SalesSimulator` (`retailops/sales/simulator.py`) hoạt động hoàn toàn ở tầng ngoài (offline/dev).
- **Không import `sqlite3` hay kết nối DB**: Simulator chỉ tạo dict sự kiện, ký HMAC và phát đi.
- Mọi thao tác ghi dữ liệu bắt buộc phải qua `SalesImportAdapter.ingest_event(...)`.

### 2.3. Ranh giới Nhập liệu & Giao dịch Nguyên tử (`SalesImportAdapter`)

- **Bước 1 — Schema & Non-email Validation**: Kiểm tra đúng 11 trường, kiểu dữ liệu nghiêm ngặt, ràng buộc tổng tiền và cấm email.
- **Bước 2 — Timestamp Drift Check**: Từ chối các event quá cũ ($> 300\text{s}$) hoặc tương lai ($> 60\text{s}$) để chống replay attack.
- **Bước 3 — Tenant Check**: Kiểm tra tenant tồn tại và đang kích hoạt trong `IdentityStore`.
- **Bước 4 — HMAC Verification**: Đối chiếu chữ ký với secret của `(source_system, tenant)` bằng `hmac.compare_digest`.
- **Bước 5 — Atomic Transaction trong Business Store** (business store là nguồn sự thật cho "external customer này là customer nào"):
  - Kiểm tra bảng `imported_events` theo `(source_system, event_id)`: nếu đã xử lý, trả về `is_replay=True, status="already_processed"` mà không ghi đè dữ liệu.
  - Xác định `customer_id`: ưu tiên mapping trong identity store; nếu chưa có thì **dùng lại customer đã ghi trong `imported_events`** của cùng `(tenant, source_system, external_customer_id)`; chỉ khi chưa từng import mới cấp `cust_<uuid4_hex>` mới (opaque, khắc phục N08).
  - **N1 — Guard quyền sở hữu**: nếu `orders.id = order_id` đã tồn tại với `customer_id` khác → `409 order_owner_conflict`, rollback toàn bộ (không có customer, order, items, audit, imported_event, mapping nào được ghi). `ON CONFLICT(id) DO UPDATE` không bao giờ cập nhật `customer_id`.
  - Tạo hồ sơ khách hàng `customers`, ghi đơn vào `orders` (status nội bộ: `pending`, `delivered`, `cancelled`), thay thế `order_items`, ghi `business_events(kind='order_imported')` và `imported_events`.
  - **Rollback Guard**: Nếu có bất kỳ lỗi nào trong giao dịch (lỗi DB, constraint, FK, disk), toàn bộ thay đổi trong DB tenant được rollback sạch sẽ; mapping mới ở identity store không được lưu.
- **Bước 6 — Cache Invalidation**: Ngay sau commit, gọi `ToolCache.invalidate(customer=customer_id, tenant_id=tenant_id, order_id=order_id)` — độc lập với tình trạng identity store.
- **Bước 7 — Derived Identity Mapping (N4)**: ghi `external_customer_mappings` bằng `IdentityStore.link_external_customer` kiểu **insert-if-absent** (cùng customer → no-op, không audit trùng; khác customer → `409 external_customer_mapping_conflict`, không ghi đè) và `identity_events(kind='external_customer_mapped')` khi tạo mới.

### 2.4. Nhất quán xuyên hai store (N4)

Business store và identity store là hai database nên không có transaction chung. Thiết kế chọn **business `imported_events` là nguồn sự thật, mapping là chỉ mục dẫn xuất tự phục hồi**:

| Tình huống | Hành vi |
|---|---|
| Identity write lỗi sau business commit (lỗi driver/DB, 5xx) | Đơn đã commit đúng 1 lần; trả `503 identity_mapping_pending` (retryable); không có mapping nửa vời. |
| Retry cùng `event_id` | `already_processed` + hoàn tất mapping bằng đúng customer đã commit; không đơn/audit trùng. |
| Event mới của cùng external customer khi mapping còn thiếu | Dùng lại customer đã commit trong `imported_events` (không cấp customer thứ hai). |
| Quên retry | `SalesImportAdapter.reconcile_mappings(tenant_id)` dựng lại mapping từ `imported_events`, idempotent, báo conflict thay vì ghi đè. |
| Mapping đã trỏ customer khác (4xx) | Lỗi thật (409) được trả nguyên vẹn, không bị che thành `pending`. |

`IdentityStore.link_external_customer` không còn `ON CONFLICT DO UPDATE` nên không thể đổi chủ mapping một cách âm thầm.

### 2.5. PostgreSQL DDL / Migration (N2)

`retailops/storage/pg_schema.py` bổ sung (additive, `IF NOT EXISTS`, không đổi schema version):

- `P5C_BUSINESS_DDL`: `order_items` (FK `orders`/`products`, CHECK quantity/price/subtotal, `BIGINT` cho tiền), `imported_events` (`UNIQUE(source_system, event_id)`, `BIGINT total`), các index `order`/`external customer`.
- `P5C_IDENTITY_DDL`: `external_customer_mappings` (`UNIQUE(tenant_id, source_system, external_customer_id)`, FK `tenants`) và index theo `(tenant_id, customer_id)`.
- Có trong `BUSINESS_DDL`/`IDENTITY_DDL` (schema mới) **và** được `initialize()` áp dụng lên schema đã tồn tại (đường `database migrate`); `PostgresIdentityStore(create=False)` cũng áp dụng DDL mapping cho identity schema đã ở version hiện tại. SQLite thêm index `idx_imported_events_external`.

---

## 3. Bằng chứng Thực thi Kiểm thử

### 3.1. 15 test P5-C gốc (`tests/test_phase5_sales_simulator_import.py`) — vẫn PASS 15/15 sau khi siết contract

| Test Case | Tiêu chí | Kết quả |
|---|---|:---:|
| `test_simulator_emits_valid_canonical_event_without_db` | P5-C | **PASS** |
| `test_hmac_signature_verification_and_tamper_rejection` | P5-C | **PASS** |
| `test_schema_validation_rejects_missing_fields` | P5-C | **PASS** |
| `test_schema_validation_rejects_invalid_status_and_items` | P5-C | **PASS** |
| `test_schema_strictly_rejects_email_as_external_customer_id` | P5-K4 | **PASS** |
| `test_timestamp_drift_validation` | P5-C | **PASS** |
| `test_tenant_validation_rejects_unknown_or_inactive` | P5-C | **PASS** |
| `test_tenant_scoped_customer_mapping_and_cross_tenant_isolation` | P5-K4 | **PASS** |
| `test_explicit_customer_link` | P5-K4 | **PASS** |
| `test_idempotent_event_ingestion_and_replay_detection` | P5-K5 | **PASS** |
| `test_atomic_rollback_on_database_error_leaves_no_traces` | P5-C | **PASS** |
| `test_customer_order_visibility_and_isolation` | P5-K6 | **PASS** |
| `test_multi_item_order_persists_to_order_items` | P5-K6 | **PASS** |
| `test_tool_cache_invalidation_after_import` | P5-C | **PASS** |
| `test_pre_signed_fixtures_validation` | P5-C | **PASS** |

### 3.2. Regression test cho N1–N4 (SQLite, `tests/test_phase5_sales_review_fixes.py`, 26 test)

| Blocker | Test tiêu biểu | Xác nhận |
|---|---|---|
| N1 | `test_other_customer_cannot_take_over_existing_order` | Customer B dùng lại `order_id` của A → 409 `order_owner_conflict`; order/items/audit/imported_events không đổi; không có customer/mapping của B. |
| N1 | `test_same_external_id_from_other_source_is_a_different_customer_and_cannot_take_over` | Cùng `external_customer_id` ở `source_system` khác cũng không chiếm được đơn. |
| N1 | `test_import_cannot_take_over_seeded_demo_order` | Không chiếm được đơn demo có sẵn. |
| N1 | `test_same_customer_can_still_update_its_own_order` | Cùng customer vẫn cập nhật đơn của mình (version 2). |
| N3 | `test_rejects_extra_top_level_field_even_when_signed`, `test_rejects_extra_item_field` | Trường thừa bị từ chối kể cả khi đã ký lại. |
| N3 | `test_rejects_bool_numbers`, `test_rejects_float_numbers_even_when_integral`, `test_rejects_numeric_strings_and_none`, `test_rejects_out_of_range_values` | bool/float/chuỗi/None/ngoài miền đều 400; không ghi gì vào DB. |
| N3 | `test_exact_schema_accepts_valid_event_with_optional_item_fields` | Event hợp lệ (có `variant_*`) vẫn được nhận. |
| N4 | `test_identity_failure_after_business_commit_is_retryable_and_heals_on_replay` | 503 `identity_mapping_pending` → retry `already_processed`, mapping đúng customer đã commit, 1 audit. |
| N4 | `test_next_event_of_same_external_customer_reuses_committed_customer`, `test_repeated_identity_failures_never_create_second_customer` | Không bao giờ có customer thứ hai. |
| N4 | `test_reconcile_is_idempotent_and_reports_conflicts_without_overwriting`, `test_link_external_customer_is_insert_if_absent`, `test_mapping_conflict_is_not_masked_as_pending` | Recovery/idempotency; không ghi đè mapping. |
| N2 (offline) | `N2PostgresDdlContractTests` | DDL P5-C nằm trong `BUSINESS_DDL`/`IDENTITY_DDL`, idempotent, có khóa idempotency, và được áp dụng ở đường migrate. |

### 3.3. PostgreSQL thật (N2 + hành vi N1/N4) — `tests/test_phase5_sales_postgres.py`, 10 test

Chạy trên PostgreSQL 16.2 + pgvector 0.6.2 dùng một lần (database `retailops_test`, `scripts/prepare_test_pgvector.py` như CI). Test tự `skip` khi không có `RETAILOPS_TEST_DATABASE_URL`; CI job `offline` cung cấp PostgreSQL service nên chạy thật.

| Test | Xác nhận |
|---|---|
| `test_fresh_schema_contains_p5c_tables_with_constraints` | Schema mới có `order_items`, `imported_events`, `external_customer_mappings` và constraint. |
| `test_legacy_schema_without_p5c_tables_is_migrated_idempotently` | Xóa 3 bảng → `database migrate` tạo lại; chạy 2 lần vẫn OK. |
| `test_migration_preserves_existing_p5c_rows` | Migrate không mất dữ liệu đã import/mapping. |
| `test_money_columns_hold_values_above_32_bits` | `BIGINT` giữ giá trị 5 tỷ. |
| `test_import_replay_and_tenant_scoped_mapping` | Import/replay/mapping theo tenant trên PostgreSQL. |
| `test_n1_other_customer_cannot_take_over_order` | 409, không thay đổi dữ liệu. |
| `test_rollback_leaves_no_traces_on_postgresql` | FK violation giữa transaction → rollback sạch. |
| `test_n4_identity_failure_after_commit_recovers_by_replay_and_reconcile` | 503 → replay → mapping đúng; reconcile no-op. |
| `test_n4_next_event_after_identity_failure_reuses_customer` | Không sinh customer thứ hai. |
| `test_link_external_customer_conflict_on_postgresql` | Insert-if-absent, 409 khi đổi chủ. |

### 3.4. Kết quả tổng hợp (lần chạy cuối trên working tree của PR)

```text
P5-C (15 gốc) + review-fixes (26):        Ran 41 tests  OK
test_phase5_sales_postgres (PostgreSQL):  Ran 10 tests  OK
python3 scripts/check_docs_contract.py:   SUCCESS (4/4 checks)
python3 scripts/build_agent_notebook.py --check: AGENT_NOTEBOOK_SOURCE_SYNC_OK
python -m unittest discover -s tests (kèm PostgreSQL + pgvector cục bộ): Ran 641 tests, OK (có PostgreSQL thật; ~242s)
```

Bao gồm regression `test_phase5_google_identity.py`, `test_schema_migration.py`, `test_persistent_identity.py`, `test_business_api.py`, `test_pr_a_correctness.py` (kiểm tra contract "schema hiện tại thì không `initialize()`").

> [!NOTE]
> Môi trường cục bộ là Windows/Python 3.10, không có Docker; các bước CI cần Docker (build image, Caddy validate, chạy test trong container, HTTPS proxy) và Node chỉ chạy được trên GitHub Actions của PR. Kết quả CI sẽ được ghi vào PR, không được suy ra từ tài liệu này.

---

## 4. Trạng thái Nghiệm thu Tiêu chí Phase 5

- [x] **P5-K1 (Smoke isolation)**: PASS trên commit `80f5156` (report `/opt/retailops/e2e-reports/LIVE_SMOKE_20261011T074654Z.json`).
- [x] **P5-K2 (Runtime health)**: PASS trên commit `80f5156` (deploy workflow 38119061325).
- [x] **P5-K3 (Google identity)**: PASS offline trên P5-B (12/12 tests PASS).
- [ ] **P5-K4 (External mapping)**: **REMEDIATED — chờ re-review**. SQLite + PostgreSQL thật PASS; DDL/migration có; mapping tự phục hồi sau lỗi identity.
- [ ] **P5-K5 (Event contract)**: **REMEDIATED — chờ re-review**. Đúng 11 trường, strict numeric types, idempotency PASS.
- [ ] **P5-K6 (Order visibility)**: **REMEDIATED — chờ re-review**. Không thể đổi chủ `order_id`; regression test N1 trên SQLite và PostgreSQL.
- [ ] **P5-K7 (Complaint workflow)**: PENDING đến P5-D.
- [ ] **P5-K8 (Confirmation and audit)**: PENDING đến P5-D.

Các mục K4–K6 chỉ được chuyển `[x]` bởi reviewer sau khi CI của PR xanh.

---

## 5. Review độc lập — 2026-10-11 và cách đã xử lý

### Blocker N1 — trùng `order_id` có thể đổi chủ đơn hàng — ĐÃ SỬA

`SalesImportAdapter.ingest_event()` chỉ deduplicate theo `(source_system, event_id)` rồi dùng `ON CONFLICT(id) DO UPDATE` cho `orders` ([retailops/sales/adapter.py](../../retailops/sales/adapter.py)). Một event mới, hợp lệ và có `order_id` cũ nhưng `external_customer_id` khác sẽ ghi đè `customer_id` của đơn. Review tái hiện được: customer A import `order_id=same`, sau đó customer B import event khác với cùng `order_id`; đơn chuyển sang B. Đây vi phạm P5-K6 và có thể làm lộ/mất quyền sở hữu dữ liệu.

**Sửa:** trước khi ghi, adapter đọc chủ hiện tại của `order_id` trong cùng transaction; khác customer → `409 order_owner_conflict` và rollback; `DO UPDATE` không còn đụng `customer_id`. Regression: `N1OrderOwnershipTests` (5 test SQLite) + `test_n1_other_customer_cannot_take_over_order` (PostgreSQL).

### Blocker N2 — PostgreSQL production chưa có migration cho P5-C — ĐÃ SỬA

P5-C thêm `order_items`/`imported_events` trong SQLite `retailops/business/schema.py`, nhưng `retailops/storage/pg_schema.py` không thêm các bảng này vào DDL/migration. Tương tự, `external_customer_mappings` chỉ được tạo trong SQLite `retailops/identity/store.py`, không có trong `IDENTITY_DDL`/migration PostgreSQL. Adapter sẽ không chạy trên backend PostgreSQL đang deploy.

**Sửa:** xem §2.5. Bằng chứng: §3.3 (10 test trên PostgreSQL thật, gồm migrate từ schema thiếu bảng, chạy 2 lần, giữ dữ liệu cũ).

### Lỗi mức vừa N3 — contract không thật sự “exactly 11 fields” và kiểm tra số chưa chặt — ĐÃ SỬA

`validate_event_schema()` chỉ kiểm tra 11 trường bắt buộc nên vẫn nhận extra fields; `int()` làm tròn `unit_price`/`total`, và `bool` được chấp nhận như `int` cho quantity. Điều này cho phép payload sai kiểu vượt qua contract đã ghi trong evidence.

**Sửa:** xem §2.1. Regression: `N3StrictSchemaTests` (10 test). Lưu ý contract tiền tệ hiện là `int` VND; float bị từ chối kể cả khi nguyên (`450000.0`). Nếu nguồn cần số thập phân, phải đổi contract có version, không nới ngầm.

### Lỗi mức vừa N4 — mapping post-commit không nguyên tử xuyên hai store — ĐÃ SỬA

Business transaction commit trước, sau đó mới ghi `external_customer_mappings`. Nếu identity write lỗi, đơn đã tồn tại nhưng mapping thiếu; retry có thể cấp customer khác và ghi đè cùng order. Cần cơ chế transaction boundary/outbox hoặc rollback/reconciliation rõ ràng.

**Sửa:** xem §2.4 (business là nguồn sự thật + mapping insert-if-absent + retry/reconcile). Regression: `N4MappingRecoveryTests` (7 test SQLite) + 2 test PostgreSQL.

**Giới hạn còn lại (nêu rõ):** không có transaction phân tán; trong cửa sổ giữa business commit và identity write, mapping tạm thiếu nhưng API trả `503 identity_mapping_pending` để caller retry, và không thể phát sinh customer thứ hai hay đổi chủ đơn. Chưa có job reconcile định kỳ — `reconcile_mappings` là hàm thủ công/gọi từ script vận hành; việc lên lịch thuộc phạm vi triển khai sau, không thuộc PR này.

## 6. Kết luận P5-C

Chặng P5-C **đã sửa N1–N4 và chờ re-review**:
- Không event nào đổi được chủ `order_id`; contract đúng 11 trường với kiểu số nghiêm ngặt.
- DDL/migration PostgreSQL cho `order_items`, `imported_events`, `external_customer_mappings` đã có và được kiểm bằng PostgreSQL thật.
- Mapping không lệch khi identity write lỗi sau business commit; có retry và reconcile idempotent.
- Chưa deploy, chưa P5-D; K1–K8 không bị mở lại. Sau khi reviewer xác nhận CI xanh mới cập nhật acceptance K4–K6.
