# Phase 5 P5-C Evidence — Sales Simulator & Service-Boundary Import Contract

> **Mã tài liệu**: `PHASE_5_C_EVIDENCE`
>
> **Chặng**: Phase 5 — Chặng P5-C (Sales simulator và import contract)
>
> **Base SHA**: `80f51569b3bef5ae0793bac1593fb91e39558477` (Merged PR #38 / P5-B deploy)
>
> **Branch**: `feat/phase5-sales-simulator-import`
> **Merged SHA**: `a34b479eeb633ba55090f43a1f4ed7d85f6a3c9a` (PR #39); source candidate `3ff5d0ee8d4d53df6772a697d2638c9e65bbe7e6`
> **CI**: merged CI run `38335308462` PASS (offline/Colab, PostgreSQL và portable); P5-C PostgreSQL suite nằm trong job offline, không phải Ops Console.
> **Deploy**: run `38335308481` rerun; deploy job `115122302562` SUCCESS lúc 2026-10-13 11:06 (+07) trên merged SHA `a34b479`. Owner snapshot sau deploy (`2026-10-13T04:36:57Z`) cho thấy web/admin chạy image digest `sha256:2c05827775460a5c56c41855dcd1a216e9c529e89a75614e553e91e00b922c1e`, khớp `deployed.env`; web/admin/PostgreSQL healthy; Caddy ở public + admin network và mount `/etc/caddy/admin`.
> **Trạng thái**: N1–N4 và 4 finding đã sửa; targeted/local/CI verification PASS; **MERGED, DEPLOYED, RUNTIME/TOPOLOGY VERIFIED; P5-K1 PASS**. Owner-pasted excerpts from both smoke JSON reports confirm expected image, health, identity tuples, all listed checks and credential cleanup. Raw JSON/workflow logs/OCI revision labels chưa được archive.
>
> **Phạm vi review implementation P5-C**: Simulator không ghi thẳng DB; không dùng email làm khóa; không làm P5-D; không gọi Google live OAuth; không đo lường model/paid; không mở lại K1–K8. Deploy P5-C được theo dõi riêng trong cập nhật hiện hành phía trên.

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
| `timestamp` | `str` | Thời gian phát sinh ISO-8601 UTC. Kiểm tra chống trôi thời gian (drift tolerance). Từ chối nghiêm ngặt `NaN`, `Infinity`, `-Infinity` và các chuỗi số vô hạn (`invalid_timestamp_format` / `invalid_timestamp_drift`). |
| `signature` | `str` | Chữ ký HMAC-SHA256 64 ký tự hex tính trên chuỗi JSON canonical của 10 trường trên. |

**Kiểu số nghiêm ngặt (N3 & Review-Fix 4):** `quantity` (1…100 000), `unit_price` và `total` (0…10^12) phải là `int` thật. `bool` (kể cả `True == 1`), `float` (kể cả `1.0`, `450000.5`), chuỗi số và `None` đều bị từ chối; không còn `int()` làm tròn ngầm. Timestamp parse và validate từ chối mọi giá trị `math.isnan()` hoặc `math.isinf()`. Giới hạn trên bảo đảm giá trị luôn nằm trong `BIGINT` của PostgreSQL.

### 2.2. Simulator Cô lập Hoàn toàn (Zero Direct DB Writes)

- `SalesSimulator` (`retailops/sales/simulator.py`) hoạt động hoàn toàn ở tầng ngoài (offline/dev).
- **Không import `sqlite3` hay kết nối DB**: Simulator chỉ tạo dict sự kiện, ký HMAC và phát đi.
- Mọi thao tác ghi dữ liệu bắt buộc phải qua `SalesImportAdapter.ingest_event(...)`.

### 2.3. Ranh giới Nhập liệu & Giao dịch Nguyên tử (`SalesImportAdapter`)

- **Bước 1 — Schema, NaN/Infinity & Non-email Validation**: Kiểm tra đúng 11 trường, kiểu dữ liệu nghiêm ngặt, ràng buộc tổng tiền, cấm email và kiểm tra cú pháp timestamp chuẩn ISO-8601 không NaN/Infinity.
- **Bước 2 — Tenant Check**: Kiểm tra tenant tồn tại và đang kích hoạt trong `IdentityStore`.
- **Bước 3 — HMAC Verification**: Đối chiếu chữ ký với secret của `(source_system, tenant)` bằng `hmac.compare_digest`.
- **Bước 4 — Atomic Transaction & Replay / Collision Guard trong Business Store**:
  - Đối chiếu bảng `imported_events` theo `(source_system, event_id)`:
    - Nếu đã tồn tại (`existing_event`): kiểm tra toàn vẹn bản ghi (`payload_json`, `external_customer_id`, `order_id`, `tenant_id`, `signature`). Nếu bất kỳ thuộc tính nào khác biệt → **409 `event_id_collision`** (Review-Fix 2).
    - Nếu khớp chính xác: đánh dấu `replay`. **Exact replay được miễn trừ timestamp drift check** (Review-Fix 3) để có thể heal identity mapping kể cả sau cửa sổ 300s.
  - Nếu là event mới (`existing_event` is None): thực hiện **Timestamp Drift Check** nghiêm ngặt (từ chối nếu $> 300\text{s}$ hoặc tương lai $> 60\text{s}$).
  - **Prior Business Import Authority (Review-Fix 1)**: Truy vấn `imported_events` để tìm customer đã ghi trước đó cho `(tenant, source_system, external_customer_id)`.
    - Nếu đã có prior import: kiểm tra mapping ở identity store. Nếu mapping trỏ tới customer khác → **409 `external_customer_mapping_conflict`** (không cho phép mapping khác tách cùng `external_customer_id`). Dùng đúng prior `customer_id`.
    - Nếu chưa có prior import: đọc mapping từ identity store; nếu chưa có thì cấp mới `cust_<uuid4_hex>`.
  - **N1 — Guard quyền sở hữu**: nếu `orders.id = order_id` đã tồn tại với `customer_id` khác → `409 order_owner_conflict`, rollback toàn bộ. `ON CONFLICT(id) DO UPDATE` không bao giờ cập nhật `customer_id`.
  - **Tạo hồ sơ và đơn hàng**: Nếu là event mới, ghi hồ sơ `customers`, đơn vào `orders`, thay thế `order_items`, ghi `business_events(kind='order_imported')` và `imported_events`.
  - **Rollback Guard**: Nếu có bất kỳ lỗi nào trong giao dịch (lỗi DB, constraint, FK, disk), toàn bộ thay đổi trong DB tenant được rollback sạch sẽ; mapping mới ở identity store không được lưu.
- **Bước 5 — Cache Invalidation**: Ngay sau commit, gọi `ToolCache.invalidate(customer=customer_id, tenant_id=tenant_id, order_id=order_id)` — độc lập với tình trạng identity store.
- **Bước 6 — Derived Identity Mapping & Replay Healing (Review-Fix 2 & N4)**:
  - Nếu là replay: chỉ heal identity mapping bằng đúng tuple đã lưu trong DB `(replay["tenant_id"], replay["source_system"], replay["external_customer_id"], replay["customer_id"])` và trả về `ImportResult(is_replay=True, status="already_processed")`.
  - Nếu là event mới: ghi `external_customer_mappings` bằng `IdentityStore.link_external_customer` (insert-if-absent, kiểm tra prior import trước khi link để chống xung đột). Nếu identity store lỗi → `503 identity_mapping_pending`.

### 2.4. Nhất quán xuyên hai store (N4 & Review Fixes)

Business store và identity store là hai database nên không có transaction chung. Thiết kế chọn **business `imported_events` luôn là nguồn sự thật tối thượng, mapping là chỉ mục dẫn xuất tự phục hồi**:

| Tình huống | Hành vi |
|---|---|
| Identity write lỗi sau business commit (lỗi driver/DB, 5xx) | Đơn đã commit đúng 1 lần; trả `503 identity_mapping_pending` (retryable); không có mapping nửa vời. |
| Retry cùng `event_id` với payload/customer khác | Từ chối 409 `event_id_collision`, không ghi đè và không heal sai. |
| Exact replay sau 300s | Vượt qua drift check, heal mapping bằng đúng tuple đã lưu trong DB; trả `already_processed`. |
| Cố tình link mapping khác cho cùng external customer | `link_external_customer` kiểm tra `imported_events`, từ chối 409 `external_customer_mapping_conflict`. |
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

### 3.2. Regression test cho N1–N4 và PR #39 review fixes (SQLite, `tests/test_phase5_sales_review_fixes.py`, 30 test)

| Finding / Blocker | Test tiêu biểu | Xác nhận |
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
| **PR #39 (1)** | `test_prior_business_import_is_authoritative_and_conflicting_mapping_rejected` | Prior business import là nguồn sự thật tối thượng; `link_external_customer` cố map external ID sang customer khác bị từ chối 409 `external_customer_mapping_conflict`. Sự kiện mới nếu mapping lệch cũng bị chặn 409. |
| **PR #39 (2)** | `test_event_id_collision_rejected_with_different_payload_or_customer` | Cùng `(source_system, event_id)` nhưng payload/customer khác bị từ chối 409 `event_id_collision`. Replay chỉ heal mapping bằng đúng tuple đã lưu trong DB. |
| **PR #39 (3)** | `test_exact_replay_after_300s_bypasses_drift_check_and_heals_mapping` | Exact replay sau 300s vượt qua drift check thành công và heal identity mapping; trong khi event mới ngoài cửa sổ 300s bị chặn 400 `invalid_timestamp_drift`. |
| **PR #39 (4)** | `test_rejects_nan_and_infinity_timestamps` | Timestamp `NaN`, `Infinity`, `-Infinity`, `"nan"`, `"inf"` bị từ chối tại schema validation và parse. |

### 3.3. PostgreSQL contract suite (N2 + hành vi N1/N4 + PR #39) — `tests/test_phase5_sales_postgres.py`, 13 test được cấu hình

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
| `test_prior_business_import_authoritative_on_postgresql` | Prior business import chặn conflicting mapping trên PostgreSQL (409 `external_customer_mapping_conflict`). |
| `test_event_id_collision_rejected_on_postgresql` | Event ID collision với payload khác bị từ chối 409 `event_id_collision` trên PostgreSQL. |
| `test_exact_replay_after_300s_heals_mapping_on_postgresql` | Exact replay sau 300s bypass drift check và heal mapping thành công trên PostgreSQL. |

### 3.4. Kết quả tổng hợp (lần chạy cuối trên working tree của PR)

```text
P5-C (15 gốc) + review-fixes (30):        Ran 45 tests  OK
test_phase5_sales_postgres (PostgreSQL):  13 tests configured in offline CI run 38129938864 (job SUCCESS; raw per-test log not read)
full local suite:                         Ran 648 tests  OK (skipped=65; PostgreSQL integration skipped locally)
python scripts/check_docs_contract.py:    SUCCESS (4/4 checks)
python scripts/check_eval_dataset.py:     EVAL_DATASET_OK baseline_v1.jsonl
python scripts/build_agent_notebook.py --check: AGENT_NOTEBOOK_SOURCE_SYNC_OK
```

Bao gồm regression `test_phase5_google_identity.py`, `test_schema_migration.py`, `test_persistent_identity.py`, `test_business_api.py`, `test_pr_a_correctness.py` (kiểm tra contract "schema hiện tại thì không `initialize()`").

> [!NOTE]
> Môi trường cục bộ là Windows/Python 3.10, không có Docker; các bước CI cần Docker (build image, Caddy validate, chạy test trong container, HTTPS proxy) và Node chỉ chạy được trên GitHub Actions của PR. Kết quả CI sẽ được ghi vào PR, không được suy ra từ tài liệu này.

---

## 4. Trạng thái Nghiệm thu Tiêu chí Phase 5

- [x] **P5-K1 (Smoke isolation)**: PASS trên deploy P5-C run `38335308481`; hai report excerpt dưới đây cùng xác nhận image/runtime/checks và identity tuple.
- [x] **P5-K2 (Runtime health)**: PASS trên P5-C deploy run `38335308481` / job `115122302562`; snapshot `2026-10-13T04:36:57Z` xác nhận digest, health và topology.
- [ ] **P5-K3 (Google identity)**: PARTIAL — offline trên P5-B (12/12 tests PASS); live Google OAuth/state/nonce/session verification chưa chạy.
- [x] **P5-K4 (External mapping):** **PASS trên `3ff5d0e`**. SQLite targeted suite PASS; offline CI job SUCCESS; independent sign-off PASS.
- [x] **P5-K5 (Event contract):** **PASS trên `3ff5d0e`**. 45 targeted tests PASS; offline CI job SUCCESS; independent sign-off PASS.
- [x] **P5-K6 (Order visibility):** **PASS trên `3ff5d0e`**. Ownership/isolation regressions PASS; offline CI job SUCCESS; independent sign-off PASS.
- [ ] **P5-K7 (Complaint workflow)**: P5-D patch has substantive disposable PostgreSQL/pgvector assertions, but the integration test was skipped locally without a DSN. Same-candidate CI execution is still pending; live remains pending.
- [ ] **P5-K8 (Confirmation and audit)**: P5-D offline test now binds proposal fields to the complaint `action_proposal` and verifies reopen/replay/checksum/tamper behavior. Same-candidate CI/evidence and acceptance remain pending; live remains pending.

K4–K6 là acceptance offline/merged của P5-C. P5-D được theo dõi riêng tại [P5-D evidence](PHASE_5_D_EVIDENCE.md) và [review](REVIEW_GEMINI_P5_D_2026-10-13.md); không dùng tài liệu P5-C này để kết luận P5-D đã accepted. P5-K3 live Google identity vẫn pending.

---

## 5. Review độc lập & Xử lý 4 Finding tại PR #39 (2026-10-11)

### Blocker N1 — trùng `order_id` có thể đổi chủ đơn hàng — ĐÃ SỬA

`SalesImportAdapter.ingest_event()` chỉ deduplicate theo `(source_system, event_id)` rồi dùng `ON CONFLICT(id) DO UPDATE` cho `orders` ([retailops/sales/adapter.py](../../retailops/sales/adapter.py)). Một event mới, hợp lệ và có `order_id` cũ nhưng `external_customer_id` khác sẽ ghi đè `customer_id` của đơn. Review tái hiện được: customer A import `order_id=same`, sau đó customer B import event khác với cùng `order_id`; đơn chuyển sang B. Đây vi phạm P5-K6 và có thể làm lộ/mất quyền sở hữu dữ liệu.

**Sửa:** trước khi ghi, adapter đọc chủ hiện tại của `order_id` trong cùng transaction; khác customer → `409 order_owner_conflict` và rollback; `DO UPDATE` không còn đụng `customer_id`. Regression: `N1OrderOwnershipTests` (5 test SQLite) + `test_n1_other_customer_cannot_take_over_order` (PostgreSQL).

### Blocker N2 — PostgreSQL production chưa có migration cho P5-C — ĐÃ SỬA

P5-C thêm `order_items`/`imported_events` trong SQLite `retailops/business/schema.py`, nhưng `retailops/storage/pg_schema.py` không thêm các bảng này vào DDL/migration. Tương tự, `external_customer_mappings` chỉ được tạo trong SQLite `retailops/identity/store.py`, không có trong `IDENTITY_DDL`/migration PostgreSQL. Adapter sẽ không chạy trên backend PostgreSQL đang deploy.

**Sửa:** xem §2.5. Bằng chứng: §3.3 (13 test PostgreSQL được cấu hình trong offline CI, gồm migrate từ schema thiếu bảng, chạy 2 lần, giữ dữ liệu cũ; raw per-test log chưa được đọc độc lập).

### Lỗi mức vừa N3 — contract không thật sự “exactly 11 fields” và kiểm tra số chưa chặt — ĐÃ SỬA

`validate_event_schema()` chỉ kiểm tra 11 trường bắt buộc nên vẫn nhận extra fields; `int()` làm tròn `unit_price`/`total`, và `bool` được chấp nhận như `int` cho quantity. Điều này cho phép payload sai kiểu vượt qua contract đã ghi trong evidence.

**Sửa:** xem §2.1. Regression: `N3StrictSchemaTests` (10 test). Lưu ý contract tiền tệ hiện là `int` VND; float bị từ chối kể cả khi nguyên (`450000.0`). Nếu nguồn cần số thập phân, phải đổi contract có version, không nới ngầm.

### Lỗi mức vừa N4 — mapping post-commit không nguyên tử xuyên hai store — ĐÃ SỬA

Business transaction commit trước, sau đó mới ghi `external_customer_mappings`. Nếu identity write lỗi, đơn đã tồn tại nhưng mapping thiếu; retry có thể cấp customer khác và ghi đè cùng order. Cần cơ chế transaction boundary/outbox hoặc rollback/reconciliation rõ ràng.

**Sửa:** xem §2.4 (business là nguồn sự thật + mapping insert-if-absent + retry/reconcile). Regression: `N4MappingRecoveryTests` (7 test SQLite) + 2 test PostgreSQL.

### 4 Finding bổ sung từ Review PR #39 — ĐÃ SỬA ĐÚNG PHẠM VI

1. **(1) Prior business import luôn là nguồn sự thật (Authoritative Source of Truth):**
   - Không cho phép bất kỳ mapping identity nào tách hoặc trỏ `external_customer_id` đã từng import sang customer khác.
   - `link_external_customer` truy vấn `imported_events` trước khi ghi; nếu đã có prior import với `customer_id` khác → từ chối **409 `external_customer_mapping_conflict`**.
   - Khi ingest event mới, nếu mapping hiện tại mâu thuẫn với prior import trong `imported_events` → từ chối **409 `external_customer_mapping_conflict`**.

2. **(2) Replay cùng `(source_system, event_id)` reject collision nếu khác payload/external_customer_id; chỉ heal stored tuple:**
   - Khi tìm thấy event đã import, adapter so sánh `payload_json`, `external_customer_id`, `order_id`, `tenant_id`, `signature`.
   - Nếu bất kỳ trường nào sai lệch → từ chối **409 `event_id_collision`**.
   - Nếu khớp chính xác (replay hợp lệ), adapter chỉ thực hiện heal identity mapping bằng đúng bộ giá trị `(tenant_id, source_system, external_customer_id, customer_id)` đã lưu trong DB, không lấy dữ liệu chưa kiểm chứng từ caller.

3. **(3) Exact replay được phép bypass timestamp drift-check sau 300s để heal mapping:**
   - Trong trường hợp identity mapping bị lỗi (503) và caller retry sau hơn 300 giây, việc chặn drift check trên replay sẽ khiến hệ thống không thể tự phục hồi mapping.
   - Đã tách luồng: event mới phải vượt qua `validate_timestamp(max_age_seconds=300, max_future_seconds=60)`. Nếu là exact replay của event đã lưu hợp lệ trong `imported_events`, drift check được bỏ qua để heal identity mapping thành công.

4. **(4) Từ chối nghiêm ngặt timestamp `NaN` / `Infinity`:**
   - Bổ sung kiểm tra `math.isnan(ts)` và `math.isinf(ts)` trong `parse_timestamp()` và `validate_timestamp()`.
   - Kiểm tra các biểu diễn chuỗi vô hạn (`"nan"`, `"+nan"`, `"-nan"`, `"inf"`, `"-inf"`, `"infinity"`, v.v.) và raise `ValueError` $\rightarrow$ trả về 400 `invalid_timestamp_format` hoặc `invalid_timestamp_drift`.
   - `validate_event_schema(data)` trực tiếp parse timestamp để từ chối ngay ở bước schema validation.

## 6. Independent sign-off trên candidate HEAD

**Reviewer:** Codex — GPT-6.1 Sol (fresh independent context)

**Thời điểm:** 2026-10-13 (Asia/Bangkok)

**Phạm vi:** P5-K4, P5-K5, P5-K6 và bốn finding PR #39 trên `3ff5d0ee8d4d53df6772a697d2638c9e65bbe7e6`; PR #39 sau đó merge thành `a34b479eeb633ba55090f43a1f4ed7d85f6a3c9a`.

**Phương pháp:** đọc code/evidence, đối chiếu file:line, chạy `python -m unittest tests.test_phase5_sales_simulator_import tests.test_phase5_sales_review_fixes` — 45/45 PASS; xác minh GitHub metadata cho 5/5 required checks trên đúng HEAD.

**Kết quả:** PASS cho K4/K5/K6 và cả bốn finding. PostgreSQL evidence được coi là CI-backed từ offline job; reviewer không tuyên bố đã đọc raw per-test log và không thực hiện deploy/live/paid/EC2.

## 7. Kết luận P5-C

Chặng P5-C **đã sửa N1–N4 và 4 finding PR #39, merge vào `main` tại `a34b479`, CI/deploy PASS**. Snapshot owner `2026-10-13T04:36:57Z` xác nhận web/admin đang chạy đúng digest trong `deployed.env` (`sha256:2c058277…`), web/admin/PostgreSQL healthy, Caddy có public/admin network và mount `/etc/caddy/admin`. Hai report excerpt do owner paste xác nhận P5-K1 PASS. Không cần sửa code hay redeploy P5-C. P5-D implementation re-review hiện: D-R2/D-R3 PASS; D-R1 test có assertions thật nhưng PostgreSQL/pgvector integration bị skip local, nên same-candidate CI còn pending. Xem [P5-D review](REVIEW_GEMINI_P5_D_2026-10-13.md) và [candidate-verification handoff](PHASE_5_D_EXECUTION_HANDOFF.md). Live complaint E2E còn phụ thuộc P5-K3 live Google OAuth. Operational smoke không chứng minh Google live OAuth, AI-lane G4, G5 hoặc paid model measurement.
- Prior business import là nguồn sự thật duy nhất; không thể đổi chủ đơn hàng hoặc tách mapping trái phép.
- Event ID collision được phát hiện và từ chối 409; exact replay heal mapping an toàn sau 300s.
- Contract đúng 11 trường, strict integer, loại bỏ hoàn toàn NaN/Infinity.
- DDL/migration PostgreSQL đầy đủ; PostgreSQL suite được cấu hình trong offline CI job.
- Giữ nguyên phạm vi P5-C. Ở snapshot sau này P5-D patch đã được thêm nhưng chưa accepted; không được dùng evidence P5-C làm bằng chứng đóng K7/K8. Live OAuth chưa chạy, chưa đo lường paid/model.

## 8. P5-K1 Post-deploy smoke evidence (owner-provided excerpts)

| Report | Result / runtime | Isolated identity tuple | Cleanup |
|---|---|---|---|
| `LIVE_SMOKE_20261013T040523Z.json` (04:05:23–04:05:33Z) | `pass=true`; activated image = web image = `sha256:2c058277…`; web `running|healthy`; health `ok`, PostgreSQL, `retailops-agent-v2`, `public-https`; all listed checks true | tenant `e2e-smoke-20261013040523-10330f`; principal `e2e-smoke-4293e63828`; customer `C-001`; order `O-101` | credentials revoked; isolated tenant retained |
| `LIVE_SMOKE_20261013T040555Z.json` (04:05:55–04:06:09Z) | `pass=true`; same exact activated/web digest; same health contract; all listed checks true | tenant `e2e-smoke-20261013040556-122853`; principal `e2e-smoke-c4666bfbfe`; customer `C-001`; order `O-101` | credentials revoked; isolated tenant retained |

Hai tenant khác nhau và không trùng tenant reservation cũ `e2e-live-smoke`; việc dùng lại `C-001`/`O-101` nằm trong tenant riêng. Chỉ các trường chọn lọc được owner paste, không lưu raw report vào repository; smoke này không gọi Google OAuth hay model inference.
