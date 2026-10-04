# TÀI LIỆU BÀN GIAO PHIÊN LÀM VIỆC (SESSION HANDOFF) — 02/10/2026

> **Ngày ghi nhận:** 02/10/2026
> **Repository:** `tuteemovaixlong/CSKH_ban_le`
> **Nhánh hiện tại:** `feature/module-2.5-pr-a` (nhánh đích tích hợp: `main`)
> **Trạng thái hệ thống:** PR A Hardening đang hoàn thiện; N08 chưa nghiệm thu (4 P1 blocker đang mở theo [REVIEW_ACCOUNT_ORDER_WORKFLOW.md](REVIEW_ACCOUNT_ORDER_WORKFLOW.md))
> **Kiểm thử hệ thống:** 418 unit tests PASS (0 failures, 0 errors, 43 skipped across 461 total tests)
> **Hợp đồng toàn vẹn:** 4/4 Documentation Contracts PASS, Deployment Contract PASS, Notebook Source Sync PASS
> **Trạng thái EC2:** `retailops-dev` (`i-0fd116d8927d0e412`, `t3.large`) — Sẵn sàng cho triển khai; chưa deploy theo yêu cầu.

---

## 1. TỔNG KẾT TIẾN ĐỘ PHIÊN LÀM VIỆC (SESSION HIGHLIGHTS)

Trong phiên hôm nay (02/10/2026), hệ thống đã hoàn tất các hạng mục cốt lõi của PR A (G01–G10, N01–N07, N03, N08-D live mode). Đợt kiểm tra độc lập tại [REVIEW_ACCOUNT_ORDER_WORKFLOW.md](REVIEW_ACCOUNT_ORDER_WORKFLOW.md) xác nhận **N08 chưa nghiệm thu** và ghi nhận 4 P1 blocker cần xử lý dứt điểm trước khi bàn giao:

### 1.1. Chuẩn Hóa N03: Error Masking & Giám Sát Lỗi DB Nội Bộ
- Khi database bị mất kết nối (`database_unavailable`), công cụ nghiệp vụ trả về cho người dùng mã lỗi công khai `tool_unavailable` kèm HTTP 503.
- Ghi log và telemetry nội bộ đầy đủ: `stage=tool_execution`, `tool=get_order`, `status=503`, `original_code=database_unavailable`.
- Không để lộ chi tiết kỹ thuật cơ sở dữ liệu (connection string, schema, stack trace) ra bên ngoài.
- Không commit turn lỗi vào bộ lưu trữ hội thoại.

### 1.2. Hoàn Thiện N08-A: Đồng Bộ Identity & Business DB, Cách Ly Va Chạm Mơ Hồ (Quarantine)
- Đồng bộ nguyên tử giữa Identity DB và Business DB trong quá trình xử lý migration collision legacy.
- **Không tự gán quyền sở hữu khi va chạm mơ hồ**: Nếu `customer_id` cũ đã có đơn hàng hoặc hội thoại trong Business DB, hệ thống cách ly toàn bộ đơn hàng sang tiền tố `quarantine_<collision_id>`, ghi nhận audit event nội bộ `collision_quarantined_reconciliation_required`.
- Cấp phát `customer_id` mới định dạng `cust_<uuid>` cho cả hai tài khoản bị va chạm, chèn bản ghi tương ứng vào bảng `customers` của Business DB.
- Vô hiệu hóa (invalidate) toàn bộ session cũ bị ảnh hưởng, đảm bảo không rò rỉ dữ liệu giữa các tài khoản.
- Chạy an toàn trong database transaction với cơ chế rollback khi gặp sự cố.

### 1.3. Hoàn Thiện N08-B: Bảo Toàn Tài Khoản & Đơn Hàng Legacy Khi Re-login Google OAuth
- Tự động phát hiện tài khoản Google legacy với principal `g_{clean_prefix}_{hash_suffix}` khi đăng nhập lại qua Google OAuth.
- Liên kết cặp `(issuer, sub)` vào bảng `external_identities` trỏ đến đúng principal legacy.
- Bảo toàn nguyên vẹn membership và `customer_id` cũ, không tạo thêm bản ghi membership dư thừa, giữ nguyên quyền truy cập toàn bộ lịch sử đơn hàng.
- Nếu người dùng đổi email nhưng giữ nguyên Google `sub`, hệ thống giữ nguyên liên kết tài khoản.
- Trong chế độ live (`live`), bắt buộc phải có `sub` hợp lệ; nếu thiếu sẽ từ chối với HTTP 400 `missing_sub`.

### 1.4. Hoàn Thiện N08-C: PostgreSQL Schema Parity & Migration v1 -> v2
- Bổ sung định nghĩa bảng `external_identities` và `customer_links` vào `IDENTITY_DDL`.
- Nâng `IDENTITY_SCHEMA_CURRENT = 2` và `IDENTITY_SCHEMA_COMPATIBLE = (1, 2)`.
- Triển khai migration v1 -> v2 tự động cho component `identity` trên PostgreSQL.
- Cập nhật danh mục bảng `IDENTITY_TABLES` trong `import_sqlite.py` bao gồm cả `external_identities` và `customer_links`.

### 1.5. Hoàn Thiện N08-D: Cấu Hình Live Data Mode & Cách Ly Dữ Liệu Mẫu
- Cấu hình `data_mode="live"` được truyền tải thông suốt qua `Settings` -> `bootstrap.build_public_app()` -> `PersistentSessions` -> OAuth callback.
- Trong chế độ `live`: tài khoản người dùng mới tạo nhận **0 đơn hàng**, không seed catalog demo, không seed đơn hàng mẫu.
- Nếu tiến trình cấp phát khách hàng trong Business DB thất bại, hệ thống trả về HTTP 503 `customer_provision_failed` và từ chối cấp session.

---

## 2. KẾT QUẢ KIỂM THỬ & BẰNG CHỨNG HỆ THỐNG (EVIDENCE)

| Suite Kiểm Thử / Hợp Đồng | Số Lượng / Tiêu Chí | Kết Quả | Ghi Chú |
| :--- | :---: | :---: | :--- |
| **PR A & Foundation Tests** | 56 tests | **56 PASS** (100%) | `test_pr_a_correctness.py` & `test_system_foundation.py` |
| **Full Repo Test Suite** | 461 tests | **418 PASS**, 0 FAIL, 0 ERROR | 43 tests skip có điều kiện (29 PG, 2 pgvector, 11 RAG, 1 waitress) |
| **Documentation Contract** | 4/4 Gates | **PASS** | `check_docs_contract.py` (Dataset, Stale HEAD, Links, AST Tools) |
| **Deployment Contract** | Integrity check | **PASS** | `check_deployment_contract.py` -> `DEPLOYMENT_CONTRACT_OK` |
| **Notebook Synchronization** | Source sync check | **PASS** | `build_agent_notebook.py --check` -> `AGENT_NOTEBOOK_SOURCE_SYNC_OK` |
| **Benchmark Master Dataset** | Canonical LF hash | **PRESERVED** | SHA-256 `81f64611eb09eb4d319a29257e9c456fbffff07779182b130832fd7780062105` |

---

## 3. HƯỚNG DẪN TIẾP TỤC Ở PHIÊN TIẾP THEO

1. **Trạng thái triển khai:** Mã nguồn PR A cốt lõi đã hoàn tất, chưa deploy lên EC2 live. N08 cần khắc phục 4 P1 blocker trước khi nghiệm thu.
2. **Kế hoạch tiếp theo:**
   - Ưu tiên xử lý dứt điểm 4 finding P1 của N08 theo [REVIEW_ACCOUNT_ORDER_WORKFLOW.md](REVIEW_ACCOUNT_ORDER_WORKFLOW.md):
     - `N08-A1`: Rollback đồng bộ hoặc có transaction journal giữa Identity DB và Business DB khi di trú collision.
     - `N08-A2`: Cơ chế fail-closed khi không kết nối được Business DB (không tự ý di trú hoặc cấp session).
     - `N08-B1`: Kiểm tra bắt buộc `email_verified=True` từ Google OAuth userinfo khi link tài khoản legacy.
     - `N08-C1`: Cập nhật `assert_schema()` trong `postgres.py` nhận `IDENTITY_SCHEMA_COMPATIBLE = (1, 2)`.
   - Bổ sung regression tests cho 4 ca lỗi trên và chạy kiểm chứng trên PostgreSQL disposable.
   - Sau khi N08 được nghiệm thu độc lập: hoàn tất bàn giao PR A và chuyển sang PR B (Concurrency, Headroom & Truthful Telemetry).
