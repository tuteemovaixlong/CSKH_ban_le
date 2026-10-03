# TÀI LIỆU BÀN GIAO PHIÊN LÀM VIỆC (SESSION HANDOFF) — 03/10/2026

> **Ngày ghi nhận:** 03/10/2026 (11:15 GMT+7)  
> **Repository:** `tuteemovaixlong/CSKH_ban_le`  
> **Nhánh hiện tại:** `feature/module-2.5-pr-a` (Target tích hợp: `main`)  
> **Head Commit SHA:** `872b8ee3d06eb2f939ac40aefef1baa49468b84f` (`872b8ee`)  
> **Trạng thái GitHub Actions CI:** **SUCCESS** — Run ID [`37095321746`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37095321746)  
> **Kết quả kiểm thử:** 427 PASS (máy trạm local) / **473 PASS trên PostgreSQL 16 container & Caddy live trên CI** (0 FAIL, 0 ERROR across 474 tests, 1 skip)  
> **Cam kết vận hành:** **Chưa merge vào `main`**, **chưa deploy lên EC2**, **chưa tạo PR mới**.  

---

## 1. TỔNG KẾT KẾT QUẢ XỬ LÝ TOÀN BỘ BLOCKER TỪ REVIEW GPT 6 ASTRA XHIGH

Toàn bộ các blocker / findings kỹ thuật được nêu trong `docs/review gpt 6 astra.md` đã được giải quyết triệt để và kiểm chứng trên CI:

### 1.1. Finding 1 (P1): Versioned Migration v4 Cho Identity DB Hiện Hữu
- **Vấn đề:** Không được dựa vào drop/recreate DB. Cần migration có versioning rõ ràng từ Identity schema v3 lên v4.
- **Giải pháp:**
  - `retailops/storage/postgres.py`: Cập nhật `IDENTITY_SCHEMA_CURRENT = 4`, `IDENTITY_SCHEMA_COMPATIBLE = (1, 2, 3, 4)`.
  - `retailops/storage/pg_schema.py`: Bổ sung nhánh migration v3 $\rightarrow$ v4 tạo bảng `reconciliation_journal`, index `idx_reconciliation_journal_tenant`, cột `plan_hash TEXT`, và bump version lên 4.
  - `retailops/storage/pg_repositories.py`: Kích hoạt auto-upgrade cho version in `(1, 2, 3)`.
  - `retailops/identity/store.py`: Thêm `reconciliation_journal` và cột `plan_hash TEXT` vào SQLite migration `migrate_legacy_collisions()`.

### 1.2. Finding 2 (P1): Khóa Idempotency Key Với Canonical Plan Hash Bất Biến
- **Vấn đề:** Nếu retry với plan bị thay đổi, hệ thống có thể đối soát sai lệch.
- **Giải pháp:**
  - `retailops/identity/reconcile.py`: Tính `canonical_plan_json(plan)` (sắp xếp keys và lists theo thứ tự chuẩn) và sinh `plan_hash` (SHA-256 64 ký tự).
  - Khi tra cứu journal: nếu `saved_hash != current_plan_hash`, từ chối ngay với HTTP 409 `plan_conflict`.
  - Khi resume: luôn sử dụng `saved_plan` đã ghi nhận trong journal, không bao giờ dùng plan truyền vào khi retry.

### 1.3. Finding 3 (P1): Kiểm Tra Quyền Sở Hữu Nguồn, Rowcount & Chống Chiếm Đoạt Google Sub
- **Vấn đề:** Phải xác thực `order_ids` và `conversation_ids` thực sự thuộc về `colliding_customer_id`, kiểm tra `rowcount > 0`, không được nuốt exception DB tùy tiện, và kiểm tra không cho phép chiếm đoạt `sub` đã gắn với principal khác.
- **Giải pháp:**
  - Trước khi cập nhật: `SELECT customer_id FROM orders WHERE id=?` và `SELECT customer_id FROM conversations WHERE id=?`. Nếu không tìm thấy $\rightarrow$ 404 `order_not_found` / `conversation_not_found`; nếu không thuộc `colliding_customer_id` $\rightarrow$ 403 `order_ownership_conflict` / `conversation_ownership_conflict`.
  - Kiểm tra `cursor.rowcount > 0` sau khi execute UPDATE.
  - Tra cứu cấu trúc DB an toàn qua `_has_table` (truy vấn schema catalog), loại bỏ hoàn toàn mẫu hình `try: execute() except: pass`.
  - Kiểm tra `external_identities`: nếu `(issuer, sub)` đã thuộc principal khác, từ chối với HTTP 409 `external_identity_conflict`.

### 1.4. Finding 4 (P2): Nối Caddy Maintenance và Reconciliation Vào Quy Trình Vận Hành
- **Vấn đề:** Cần công cụ vận hành chuyển đổi maintenance mode thực tế và CLI đối soát cho operator.
- **Giải pháp:**
  - Bổ sung script [`deploy/switch-maintenance.sh`](../deploy/switch-maintenance.sh): Hỗ trợ `enable`, `disable`, `status` với `caddy reload` (zero-downtime) và graceful restart.
  - Bổ sung lệnh CLI [`retailops/identity/cli.py`](../retailops/identity/cli.py): `reconcile-collision` và `reconciliation-status`.
  - [`scripts/check_public_https.py`](../scripts/check_public_https.py): Thêm bước test switch Caddy maintenance mode trên Caddy container thật, xác nhận 4 route auth trả về 503 `maintenance_mode`.

### 1.5. Finding 5 (P1): Chuẩn Hóa Điểm Crash Fault Injection & Bảo Vệ Khỏi Tái Va Chạm Khi Restart
- **Vấn đề:** Điểm crash cần chuẩn: crash sau Business commit trước journal update, crash trong Identity sau khi updates đã chạy. Ngoài ra, khi restart process, `migrate_legacy_collisions` không được tự ý mutate memberships đang chờ đối soát.
- **Giải pháp:**
  - Thêm 2 stage: `after_business_commit_before_journal` và `during_identity_commit_after_updates`.
  - Trong `migrate_legacy_collisions`: Kiểm tra `already_unresolved` trong `unresolved_collisions`. Nếu collision đã được ghi nhận, chỉ xóa session để bảo vệ quyền truy cập và bỏ qua việc tự động chia nhỏ sang `cust_<hash>`, bảo toàn trạng thái cho reconciliation coordinator.

---

## 2. BẰNG CHỨNG KIỂM ĐỊNH TRÊN GITHUB ACTIONS CI

- **Workflow Run ID:** `37095321746`
- **URL Run:** [https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37095321746](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37095321746)
- **Job `offline` (ID: `110978788939`):** `SUCCESS`
  - Đã chạy 474 tests trên PostgreSQL 16 container thật: **473 PASS**, 1 SKIP, 0 FAIL, 0 ERROR.
  - Toàn bộ 45/45 PostgreSQL integration tests: **100% PASS**.
  - 4/4 Cổng hợp đồng: **PASS 100%** (`check_docs_contract.py`, `check_deployment_contract.py`, `check_eval_dataset.py`, `build_agent_notebook.py --check`).
  - Public HTTPS verification: `PUBLIC_UI_ASSETS_OK`, `PUBLIC_HTTPS_PROXY_COOKIE_FLOW_OK`, `PUBLIC_CADDY_MAINTENANCE_SWITCH_OK`, `PERSISTENT_HTTPS_ACCOUNT_FLOW_OK`, `POSTGRES_HTTPS_IMPORT_RESTORE_OK`.
- **Job `colab-python313` (ID: `110978788950`):** `SUCCESS`
  - Public HTTPS verification: `PUBLIC_UI_ASSETS_OK`, `PUBLIC_HTTPS_PROXY_COOKIE_FLOW_OK`, `PERSISTENT_HTTPS_ACCOUNT_FLOW_OK`, `POSTGRES_HTTPS_IMPORT_RESTORE_OK`.
- **Job `colab-python313` (ID: `110973740107`):** `SUCCESS`

---

## 3. CHECKLIST SÁNG MAI KHI BẬT MÁY (RESUME CHECKLIST)

Khi bật máy vào sáng mai, bạn chỉ cần thực hiện các bước sau:

1. **Xác nhận trạng thái Git:**
   ```bash
   git status
   git log -n 3 --oneline
   ```
   *Kỳ vọng: Branch `feature/module-2.5-pr-a`, HEAD commit `c34c54b`, working tree sạch (clean).*

2. **Chạy kiểm tra nhanh 4 cổng hợp đồng:**
   ```bash
   python scripts/check_docs_contract.py
   python scripts/check_deployment_contract.py
   python scripts/check_eval_dataset.py
   python scripts/build_agent_notebook.py --check
   ```
   *Kỳ vọng: Tất cả 4 cổng đều thông báo PASS / OK.*

3. **Chạy local test suite (tùy chọn):**
   ```bash
   python -m unittest discover -s tests -p "test_*.py"
   ```
   *Kỳ vọng: 470 tests, 424 PASS, 46 SKIP, 0 FAIL, 0 ERROR (46 skip do không có PG local).*

4. **Nhiệm vụ tiếp theo:**
   - Xem xét nghiệm thu PR A và ra quyết định merge vào `main` (khi người phụ trách phê duyệt).
   - Tiếp tục triển khai **Module 2.5 PR B** (Concurrency, Headroom & Truthful Telemetry theo tài liệu [PLAN_MODULE_2_5_HARDENING_VERIFICATION.md](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md)).
