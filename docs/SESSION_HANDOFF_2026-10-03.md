# TÀI LIỆU BÀN GIAO PHIÊN LÀM VIỆC (SESSION HANDOFF) — 03/10/2026

> **Ghi chú supersede ngày 04/10/2026:** Đây là snapshot lịch sử cho code SHA fe25f67 và CI run 37137791788. Phiên làm việc 04/10/2026 đã hoàn tất trigger N08-P11-RESOLVE-FAIL-CLOSED (code patch `c4e9976`); final docs tree `eebe8ed` được CI run 37197602401 xác nhận SUCCESS (host 479/479 PASS, 0 SKIP; container 478 PASS / 1 SKIP). CI run 37196429628 trên `c4e9976` là bằng chứng lịch sử của code patch. PR A/N08 sau đó đã merge qua PR #34 tại 47ba72a; PR #35 hiện mở ở head 166e289 và đang chờ sửa theo review độc lập. Phần dưới đây là snapshot lịch sử. Trạng thái hiện hành: [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md) và [PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md](PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md).


> **Ngày ghi nhận:** 03/10/2026 (12:20 GMT+7)
> **Repository:** `tuteemovaixlong/CSKH_ban_le`
> **Nhánh hiện tại:** `feature/module-2.5-pr-a` (Target tích hợp: `main`)
> **Head Commit SHA:** `fe25f67` (code fix đóng hoàn toàn P1.1 session-safety; CI xác minh thành công)<br>
> **Kết quả kiểm thử cục bộ:** **479 tests, 429 PASS, 50 SKIP, 0 FAIL, 0 ERROR** (skip do không có PG local; các test PG chạy trên CI container)<br>
> **Kết quả kiểm thử CI (GitHub Actions Run 37137791788):** host suite **479/479 PASS, 0 SKIP**; packaged container suite **478 PASS, 1 SKIP, 0 FAIL, 0 ERROR**, trên PostgreSQL 16 và Caddy live container thật<br>
> **Cổng hợp đồng:** 4/4 cổng hợp đồng PASS 100% (`check_docs_contract.py`, `check_deployment_contract.py`, `check_eval_dataset.py`, `build_agent_notebook.py --check`)<br>
> **Cam kết vận hành:** **Chưa merge vào `main`**, **chưa deploy lên EC2**, **chưa bắt đầu PR B**.

---

## 1. TỔNG KẾT CÁC SỬA ĐỔI N08 VÀ TRẠNG THÁI HẬU KIỂM

Toàn bộ các phát hiện Blocker N08 (P1.1, P1.2) theo review của GPT 6 Astra xhigh đã được xử lý triệt để và đạt PASS trong CI Run 37137791788 trên code SHA `fe25f67`. Dưới đây là chi tiết các hạng mục đã hoàn thành.

### 1.1. Finding 1 (P1): Kiểm Tra Độ Bao Phủ Đầy Đủ Mọi Membership & Quarantined Data
- **Vấn đề:** Plan thiếu thành viên có thể gỡ quarantine khi collision vẫn còn; nếu plan chỉ có 1 trong 2 thành viên, coordinator gỡ unresolved flag khiến thành viên còn lại có thể truy cập trái phép.
- **Giải pháp:**
  - `retailops/identity/reconcile.py`: Bổ sung preflight validation đối chiếu tập membership trong plan với toàn bộ customer memberships đang va chạm (`incomplete_membership_coverage`).
  - Bổ sung kiểm tra độ bao phủ 100% toàn bộ đơn hàng (`incomplete_order_coverage`) và hội thoại (`incomplete_conversation_coverage`) bị quarantine trong Business DB (`customer_id IN (colliding_customer_id, quarantine_{colliding_customer_id})`).
  - Kiểm tra trùng lặp (`duplicate_membership_reassignment`, `duplicate_order_reassignment`, `duplicate_conversation_reassignment`) và quyền sở hữu.
  - Chỉ xóa `unresolved_collisions` (bao gồm `colliding_customer_id`, `quarantine_{colliding_customer_id}` và các ID tạm thời) sau khi toàn bộ quy trình đối soát hai database đã commit thành công.

### 1.2. Finding 2 (P1): Đồng Bộ Luồng Migration SQLite Với Coordinator/CLI & E2E Testing
- **Vấn đề:** SQLite migration `migrate_legacy_collisions()` xóa `unresolved_collisions`, khiến coordinator trả về `collision_not_found` và dữ liệu bị kẹt ở `quarantine_<id>`.
- **Giải pháp:**
  - `retailops/identity/store.py`: Khi `is_ambiguous = True`, lưu giữ `(tenant_id, customer_id)` và các ID tạm thời trong `unresolved_collisions` (thay vì xóa nhầm).
  - Giữ trạng thái fail-closed 503 `collision_unresolved` cho mọi nỗ lực login / tạo session của các tài khoản va chạm trước khi có đối soát thủ công.
  - Đồng bộ coordinator `reconcile_collision` và CLI `identity reconcile-collision` tiếp nhận mượt mà các va chạm từ migration SQLite.
  - Bổ sung kiểm thử end-to-end từ legacy DB qua migration đến reconciliation cho cả **SQLite** (`test_n08_a1_two_db_transaction_recovery_and_journal` trong `test_pr_a_correctness.py`) và **PostgreSQL** (`test_identity_v1_legacy_collision_migration_to_reconciliation_on_postgres` trong `test_postgres.py`).

### 1.3. Finding 3 (P2): Script Caddy Maintenance An Toàn Khi Chạy Lặp & CI Kiểm Thử Trực Tiếp
- **Vấn đề:** `deploy/switch-maintenance.sh` ghi đè backup khi enable lặp lại; disable không kiểm tra backup tồn tại; CI chưa gọi trực tiếp script này.
- **Giải pháp:**
  - `deploy/switch-maintenance.sh`: Kiểm tra matcher `@auth_maintenance` trước khi sao lưu; nếu đang ở chế độ bảo trì mà gọi `enable` lặp lại $\rightarrow$ báo `AUTH_MAINTENANCE_ALREADY_ENABLED` và không làm hỏng file backup `Caddyfile.normal.bak`; nếu đang ở chế độ bình thường mà gọi `disable` lặp lại $\rightarrow$ báo `AUTH_MAINTENANCE_ALREADY_DISABLED`.
  - Xử lý nghiêm ngặt: Từ chối `disable` và thoát lỗi (exit 1) nếu thiếu file backup cấu hình bình thường; kiểm tra xác nhận reload container Caddy thành công trước khi in trạng thái.
  - CI (`scripts/check_public_https.py`): Thực thi trực tiếp script vận hành này với chuỗi kiểm thử lặp: `status` (NORMAL) $\rightarrow$ `enable` $\rightarrow$ `enable` (lặp) $\rightarrow$ `status` (MAINTENANCE) $\rightarrow$ xác nhận 4 route auth trả về 503 $\rightarrow$ `disable` $\rightarrow$ `disable` (lặp) $\rightarrow$ kiểm thử thiếu backup báo lỗi $\rightarrow$ khôi phục và xác nhận 200 `/healthz`.

### 1.4. Finding 4 (P2): Đồng Bộ Tài Liệu Trạng Thái & Nâng Cấp Schema Identity v4
- **Vấn đề:** `docs/CURRENT_PROJECT_STATUS.md` có đoạn cũ tự mâu thuẫn giữa đầu tài liệu và mục 2.9 (ghi N08 BLOCKED do skip test PG, và mô tả schema v3).
- **Giải pháp:**
  - Hợp nhất trạng thái rõ ràng theo trình tự thời gian: phân định rõ ngữ cảnh lịch sử phiên 02/10/2026 và tiến độ hoàn tất ngày 03/10/2026.
  - Chuẩn hóa mô tả Identity Schema v4 (`IDENTITY_SCHEMA_CURRENT = 4`) với bảng `reconciliation_journal` và cột `plan_hash TEXT` trên cả PostgreSQL và SQLite.

### 1.5. Blocker P1.1: Xác Minh Quyền Sở Hữu `target_customer_id` Trước Mọi Ghi Business DB
- **Vấn đề:** Plan có thể gán nhầm đích sang customer đang thuộc principal/membership khác trong cùng tenant, khiến dữ liệu bị chuyển vào tài khoản của người khác.
- **Giải pháp:**
  - `retailops/identity/reconcile.py`: `_validate_target_ownership` (Identity) và `_validate_business_targets` (Business) chạy trong transaction Identity trước mọi ghi Business DB; từ chối HTTP 409 `target_customer_conflict`. Chỉ chấp nhận đích mới hoặc đích đã được chứng minh thuộc đúng principal (membership/customer_link). Kiểm tra Business được lặp lại dưới write lock.
  - Bị từ chối $\rightarrow$ rollback cả dòng journal: dữ liệu không đổi, collision vẫn unresolved, key không kẹt; retry cùng key với plan hợp lệ hoàn tất.
  - Regression test SQLite + PostgreSQL qua `tests/reconcile_target_cases.py`.

### 1.6. P1.1 (đóng hoàn toàn) — Reservation, TOCTOU recheck và Session Safety Fail-Closed (code SHA `fe25f67`)
- **Vấn đề:** Sau preflight, principal khác vẫn có thể chiếm `target_customer_id` trước khi Business commit, hoặc thực hiện raw takeover sau Business commit nhưng trước Step 3, khiến session cũ có thể đọc đơn hàng đã chuyển.
- **Giải pháp:**
  - **Serialization:** Transaction ghi Identity tuần tự hóa toàn cục (SQLite `BEGIN IMMEDIATE`, PostgreSQL advisory xact lock); reconciliation khóa thêm `memberships`/`customer_links`/`unresolved_collisions` ở chế độ `SHARE ROW EXCLUSIVE` trên PostgreSQL. Thứ tự khóa luôn là Identity → Business.
  - **Reservation:** Đích mới được ghi vào `unresolved_collisions` cùng transaction với journal ở Step 1. `create_membership` trả 409 `customer_reserved`; `get_or_create_google_member` không cấp cid đang reserved và trả 503 nếu link trỏ tới cid đang reserved. Migration/import chỉ dùng id sẵn có và bỏ qua id unresolved.
  - **Step 2:** Giữ lock Identity → kiểm tra lại journal/collision/reservation/ownership → kiểm tra Business (gồm `customers`, `conversation_feedback`) → chuyển dữ liệu → journal `business_committed` trong cùng transaction Identity. Nếu lỗi trước khi chuyển dữ liệu ở lần chạy mới, coordinator bù trừ: xóa journal và reservation, trả 409; dữ liệu không đổi, collision vẫn unresolved, key không kẹt.
  - **Session Safety Fail-Closed (`IdentityStore.resolve`):** Khi resolve session của customer (`role == 'customer'`), kiểm tra bắt buộc `unresolved_collisions` (cả `customer_id` của membership lẫn `customer_id` trong `customer_links` nếu khác) và kiểm tra va chạm membership (`col_cnt > 1`). Nếu tài khoản hoặc customer đích đang unresolved $\rightarrow$ từ chối ngay lập tức HTTP 503 `collision_unresolved`. Phiên phi-khách hàng (`staff`, `manager`, `viewer`) resolve thành công, đúng role độc lập (không assert HTTP response).
  - **Step 3 & Late Takeover Guard:** Kiểm tra lại ownership dưới lock trước khi gán membership/link; khi hoàn tất thì giải phóng reservation. Nếu raw SQL chen vào giữa Step 2 và Step 3 (late takeover), Step 3 bắt lỗi 409, journal giữ `business_committed`, collision vẫn unresolved; phiên cũ của tài khoản bị takeover lập tức nhận 503 `collision_unresolved` và API `GET /api/orders` không trả dữ liệu (không lộ order đã chuyển). Sau khi gỡ takeover, resume cùng key hoàn tất bình thường và dữ liệu trả về chính xác.
  - **Regression test hai backend:** `tests/reconcile_interleaving_cases.py` tích hợp kiểm thử phiên pre-existing, gọi `PublicWeb` `GET /api/orders` trước takeover (200), trong late takeover (503 `collision_unresolved`, 0 orders), và sau hoàn tất (200). Đã kiểm chứng PASS trên cả SQLite (`test_n08_p11_reconciliation_toctou_target_taken_after_preflight_sqlite`) và PostgreSQL (`test_reconciliation_toctou_target_taken_after_preflight_on_postgres`).

### 1.7. Trạng thái tại snapshot 03/10 — bằng chứng lịch sử
- Full suite cục bộ: **479 tests, 429 PASS, 50 SKIP, 0 FAIL/ERROR**; các PostgreSQL/pgvector tests skip vì máy local không có `RETAILOPS_TEST_DATABASE_URL`.
- Bốn gate docs/deployment/eval/notebook đạt PASS 100%; benchmark giữ nguyên LF SHA-256 `36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411`.
- GitHub Actions CI run `37137791788` trên code SHA `fe25f67`: host suite **479/479 PASS, 0 SKIP**; container suite **478 PASS / 1 SKIP** trên PostgreSQL 16 và Caddy live container thật.
- **Quyết định lịch sử tại snapshot 03/10:** Khi đó tài liệu ghi nhận sẵn sàng nghiệm thu dựa trên fe25f67. Trạng thái này đã được supersede; xem ghi chú đầu file và N08_STOPPING_CONDITIONS.md.

---

## 2. CHECKLIST VẬN HÀNH TIẾP THEO

1. **Xác nhận trạng thái Git:**
   ```bash
   git status
   git log -n 3 --oneline
   ```
   *Kỳ vọng: Branch `feature/module-2.5-pr-a`, working tree sạch (clean).*

2. **Chạy kiểm tra nhanh 4 cổng hợp đồng:**
   ```bash
   python scripts/check_docs_contract.py
   python scripts/check_deployment_contract.py
   python scripts/check_eval_dataset.py
   python scripts/build_agent_notebook.py --check
   ```
   *Kỳ vọng: Tất cả 4 cổng đều thông báo PASS / OK.*

3. **Chạy local test suite:**
   ```bash
   python -B -X utf8 -m unittest discover -s tests -p "test_*.py"
   ```
   *Kết quả: 479 tests, 429 PASS, 50 SKIP, 0 FAIL, 0 ERROR (PostgreSQL/pgvector integration skip do không có DSN local).*

4. **Nhiệm vụ tiếp theo:**
   - Trigger `N08-P11-RESOLVE-FAIL-CLOSED`: đã hoàn tất (xem Mục 3–4).
   - CI PostgreSQL trên SHA cuối: đã SUCCESS (run 37197602401 trên `eebe8ed`).
   - Bước tiếp theo: review / nghiệm thu PR A; merge main là quyết định riêng. Sau khi PR A được merge, mới bắt đầu **Module 2.5 PR B** theo [PLAN_MODULE_2_5_HARDENING_VERIFICATION.md](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md).

---

## 3. CẬP NHẬT PHIÊN LÀM VIỆC (04/10/2026) — HOÀN TẤT TRIGGER N08-P11-RESOLVE-FAIL-CLOSED & REGRESSION ROLE VIEWER

1. **Khắc phục `IdentityStore.resolve()`:**
   - Import `ApiError` và `logging` trong `retailops/identity/store.py`.
   - Trong khối guard `role == 'customer'`: bắt tường minh `except ApiError: raise` (không bao giờ nuốt lỗi 503 guard), đồng thời bắt `except Exception as e:` ghi log nội bộ qua logger và raise `ApiError(503, 'collision_unresolved', 'Tài khoản đang chờ xử lý va chạm dữ liệu.')` (fail-closed an toàn, không rò rỉ chi tiết truy vấn nội bộ ra client).
   - Duy trì phân quyền vai trò: các phiên phi-khách hàng (`staff`, `manager`, `viewer`) bỏ qua guard va chạm khách hàng và resolve thành công, đúng role (regression non-customer hiện không assert HTTP response mà assert `SessionBinding`).

2. **Bổ sung Regression Tests (`tests/reconcile_interleaving_cases.py`):**
   - Đã thêm regression cho customer-link unresolved (Gate P1.1b): nhận 503 `collision_unresolved`, 0 orders trên PublicWeb `/api/orders`.
   - Đã thêm regression cho toàn bộ các non-customer roles (`staff`, `manager`, `viewer`) (Gate P1.1d): resolve thành công, đúng role tương ứng ngay cả khi `customer_id` có trong `unresolved_collisions` (không assert HTTP response).
   - Đã thêm regression cho lỗi lookup safety qua cơ chế fault injection (Gate P1.1c): lỗi lookup `unresolved_collisions`, `customer_links`, `memberships count` đều fail-closed 503 trên customer, không ảnh hưởng non-customer (`staff`, `manager`, `viewer`).
   - Bảo toàn test late takeover hai backend SQLite và PostgreSQL (Gate P1.1a).

3. **Kết quả kiểm chứng cục bộ:**
   - Full test suite: **479 tests, 429 PASS, 50 SKIP, 0 FAIL, 0 ERROR** (50 tests SKIP gồm 36 tests trong `tests/test_postgres.py`, 11 tests trong `tests/test_rag_chat.py`, 2 tests trong `tests/test_knowledge.py`, 1 test trong `tests/test_public_web.py` do thiếu PostgreSQL local DSN và Waitress).
   - Kiểm thử PostgreSQL/pgvector được ủy quyền xác thực trên GitHub Actions CI container.
   - 4 cổng hợp đồng: PASS 100% (`check_docs_contract.py`, `check_deployment_contract.py`, `check_eval_dataset.py`, `build_agent_notebook.py --check`).

4. **Kết quả xác thực trên GitHub Actions CI (canonical: run 37197602401, head_sha `eebe8ed`; lịch sử: run 37196429628 trên code patch `c4e9976`, cùng kết quả):**
   - Host suite: **479/479 PASS, 0 SKIP, 0 FAIL, 0 ERROR** trên live PostgreSQL 16 và pgvector container.
   - Packaged container suite: **478 PASS, 1 SKIP, 0 FAIL, 0 ERROR** (`test_colab_agent_notebook_sync` bỏ qua do không có `scripts/build_agent_notebook.py` trong image).
   - Live HTTPS deployment & Caddy maintenance: PASS.
   - **Quyết định:** N08 hoàn tất đầy đủ. PR A đủ điều kiện chuyển sang bước review / nghiệm thu code. Tuyệt đối chưa merge main, chưa deploy EC2, chưa bắt đầu PR B.
