# Module 2: Store Manager Persistence, Shared Inventory & Audit Scope (P0)

> **Trạng thái:** MERGED TO MAIN & VERIFIED (PR #33 merged tại `a6ec080`, ổn định CI tại `d7ce461`)
> **Mức độ minh chứng (Evidence):** L1 Automated Test Suite (353/353 PASS), L2 Docker Build/Verify PASS, GitHub Actions CI PASS
> **Audit basis / Documentation baseline reviewed:** `b93eb5a` · **Application verified:** `d7ce461` (nhánh `main`)
> **Ngày hoàn thành & nghiệm thu:** 2026-09-23 / 2026-09-24
> **Mục tiêu:** Giải quyết tận gốc vấn đề kiến trúc: Product Catalog & Inventory phải có Single Source of Truth (SSOT), bảo toàn dữ liệu sau khi restart container, đồng bộ tức thì giữa Store Manager và Khách hàng / Chatbot AI, và sửa phạm vi Audit Trail toàn shop.

---

## 1. Các Vấn Đề Cốt Lõi Được Giải Quyết

1. **Lỗi `read_only: true` và In-Memory Catalog phân mảnh**:
   - Hiện tại: `deploy/compose.public.yaml` chạy `read_only: true`. `Catalog.save()` cố ghi vào `data/products.json`, bị lỗi `PermissionError` rồi giữ "mutation kept in-memory". Mỗi phiên đăng nhập tạo một instance `Application` riêng với `Catalog` độc lập trong RAM!
   - Hệ quả: Manager thêm/sửa sản phẩm thì chỉ phiên Manager đó thấy; Customer phiên khác không thấy; container restart là mất sạch.
   - Giải pháp: Chuyển dữ liệu `products` sang bảng cơ sở dữ liệu `products` trong PostgreSQL (hoặc SQLite store hiện có của tenant/system) được bảo toàn qua persistent volume `/var/lib/postgresql/data` hoặc thư mục volume đã mount.

2. **Khớp nối tồn kho giữa Manager và Tool Chatbot (`check_inventory`)**:
   - Hiện tại: Manager sửa tồn kho sản phẩm `P-203` lên 100 cái trong Catalog. Nhưng khi khách chat, tool `check_inventory` trong [`retailops_tools.py`](../retailops_tools.py) lại tra cứu từ một dictionary tĩnh `stock_map` hard-coded! Thậm chí SKU mới thêm vào còn bị chatbot báo mặc định 6 cái!
   - Khắc phục:
     - `check_inventory` phải đọc trực tiếp từ `self.catalog.products[pid]` (hoặc DB kho hàng).
     - Hỗ trợ lưu trữ tồn kho theo biến thể/size trong DB để khi Manager chỉnh sửa tồn kho, Chatbot AI lập tức trả lời đúng số lượng tồn kho mới nhất.
     - Trong môi trường vận hành thực tế (Production), loại bỏ hoàn toàn fallback tra cứu vào `stock_map` hard-code; `stock_map` chỉ được giữ lại trong môi trường unit test cục bộ nếu cần cô lập dữ liệu.

3. **Đồng bộ Thời hạn Bảo hành vào SSOT (Warranty Policy SSOT)**:
   - Hiện tại: `subagents/dispute_agent.py` đang hard-code quy tắc bảo hành 90 ngày cho tất cả sản phẩm khi xử lý khiếu nại đổi trả.
   - Khắc phục: `dispute_agent` phải tra cứu trường `warranty_days` trực tiếp từ Catalog SSOT của sản phẩm (ví dụ `P-104` là 90 ngày, `P-502` là 60 ngày), không giả định thời hạn cố định cho toàn bộ danh mục.

4. **Phạm vi Audit Trail trong Manager Console (`/api/events`)**:
   - Hiện tại: Backend `store.events(customer)` lọc `WHERE customer_id=? LIMIT 30`. Manager chỉ thấy sự kiện của chính tài khoản Manager (hoặc customer mẫu), không thấy các thao tác trên đơn của khách hàng khác!
   - Khắc phục:
     - Bổ sung route chuyên biệt cho Quản lý: `GET /api/manager/events` (hoặc phân nhánh trong `/api/events` khi `role == 'manager'`).
     - Truy vấn sự kiện toàn shop từ bảng chuẩn **`business_events`** (không phải `events`): `SELECT id, customer_id, kind, order_id, payload, created_at FROM business_events ORDER BY id DESC LIMIT 100`.
     - Cột khách hàng hiển thị đúng `customer_id` thật của sự kiện thay vì fallback thành `Hệ thống`.

5. **Thiết Kế ActorContext Chuẩn Hóa Toàn Hệ Thống**:
   - Để kiểm soát thẩm quyền chặt chẽ giữa các vai trò (Customer, Viewer, Staff, Manager) và các tác nhân tự động, hệ thống sử dụng cấu trúc `ActorContext`:
     - `tenant_id`: Mã định danh tenant đa khách hàng.
     - `membership_id`: Lấy từ `member["id"]`.
     - `principal_id`: Định danh người dùng đã xác thực (Google Sub hoặc Session UID).
     - `role`: Phân quyền thực tế lấy từ `member["role"]` (`customer`, `viewer`, `staff`, `manager`).
     - `customer_id`: Mã khách hàng tương ứng (`C-001`, `C-003`...).
     - `actor_type`: Phân loại nguồn thao tác, thuộc tập `('principal', 'agent', 'system')`.

6. **Xử Lý Trùng Lặp DOM ID `btn-sidebar-manager-console` (`web/index.html`)**:
   - Hiện tại `web/index.html` xuất hiện 2 phần tử cùng mang ID `btn-sidebar-manager-console`: nút trên thanh sidebar điều hướng (dòng 73) và nút banner trong order panel (dòng 145).
   - Khắc phục: Phân tách rõ ràng ID:
     - Nút sidebar: `id="btn-sidebar-manager-nav"`
     - Nút banner panel: `id="btn-panel-manager-banner"`
   - Cập nhật event listener trong `web/app.js` để gắn bộ lắng nghe sự kiện độc lập cho cả hai nút.

7. **Tự động mở Store Manager Console khi đăng nhập**:
   - Hiện tại: User đăng nhập `manager` phải tự tìm và bấm nút góc trên mới mở được bảng điều khiển (trong khi `staff` tự động mở Staff Desk).
   - Khắc phục: Trong `openSession()`, bổ sung `if (session.role === 'manager') openManagerConsole();`.

---

## 2. Kế Hoạch Chỉnh Sửa File

### [MODIFY] `web/index.html`
- Sửa trùng lặp ID: đổi thành `btn-sidebar-manager-nav` và `btn-panel-manager-banner`.

### [MODIFY] `web/app.js`
- Trong `openSession()`: Tự động gọi `openManagerConsole()` khi `session.role === 'manager'`.
- Gắn sự kiện click cho cả 2 nút quản trị: `btn-sidebar-manager-nav` và `btn-panel-manager-banner`.
- Trong `loadManagerAuditTrail()`: Đọc đúng trường `ev.customer_id` từ backend trả về.

### [MODIFY] `retailops_conversation.py`
- Nâng cấp `Catalog`:
  - Hỗ trợ `ProductStore` kết nối trực tiếp với DB SQLite/PostgreSQL của hệ thống (`app.store`).
  - Nếu DB chưa có bảng products, tự động nạp seed từ `data/products.json` lần đầu tiên (idempotent seed import).
  - Mọi thao tác `add_product`, `update_product`, `delete_product` đều ghi trực tiếp vào DB, đảm bảo tất cả các phiên `Application` đều đọc chung một bảng dữ liệu.

### [MODIFY] `retailops_tools.py`
- Trong hàm `check_inventory`:
  - Loại bỏ việc phụ thuộc vào dictionary cứng `stock_map` trên môi trường sản xuất.
  - Đọc trực tiếp từ `product = self.catalog.products.get(pid)` và bảng tồn kho DB.

### [MODIFY] `subagents/dispute_agent.py`
- Tra cứu thời hạn bảo hành từ `product.get("warranty_days")` của Catalog SSOT thay vì hard-code 90 ngày.

### [MODIFY] `retailops/http/routes.py`
- Trong nhánh `GET /api/events` / `GET /api/manager/events`:
  - Nếu `getattr(app, 'role', '') == 'manager'`:
    - Truy vấn sự kiện toàn hệ thống từ bảng `business_events` (kèm `customer_id`).
    - Trả về danh sách sự kiện đầy đủ cho Manager.
- Khởi tạo và kiểm tra `ActorContext` khi xử lý request.

### [MODIFY] `retailops/business/schema.py` & `retailops/storage/pg_schema.py`
- Đảm bảo DDL bảng `products`, `product_variants` và `business_events` đồng bộ giữa SQLite và PostgreSQL.

---

## 3. Tiêu Chí Nghiệm Thu (Acceptance Criteria)

- [x] Không còn trùng lặp ID `btn-sidebar-manager-console` trong DOM HTML (đã tách thành `btn-sidebar-manager-nav` và `btn-panel-manager-banner`).
- [x] Manager sửa sản phẩm P-203 tồn kho lên 50 cái -> Mở một tab ẩn danh / session khác kiểm tra thấy đúng 50 cái (kiểm thử tại `test_cross_session_catalog_persistence`).
- [x] Chatbot AI gọi `check_inventory` phản hồi đúng số lượng tồn kho mới được Manager cập nhật, không fallback về hardcoded dictionary tĩnh trong production.
- [x] `dispute_agent` kiểm tra hạn bảo hành chính xác theo từng sản phẩm trong Catalog SSOT và xử lý hết hàng trung thực (`test_dispute_agent_out_of_stock_real_inventory`).
- [x] Manager Console tự động mở khi đăng nhập tài khoản có quyền `manager`.
- [x] Tab Audit Trail truy vấn từ `business_events` qua route `GET /api/manager/events`, hiển thị đầy đủ các sự kiện toàn shop kèm `ActorContext` và mã khách cụ thể (`test_manager_events_and_actor_audit`).
- [x] Toàn bộ test suite tự động tiếp tục pass 100% (353/353 tests PASS, 0 failures).

---

## 4. Báo Cáo Khắc Phục 8 Điểm Nghẽn Kiểm Toán (Audit Remediation for GPT 6 Astra High)

Dựa trên kết quả rà soát chi tiết của GPT 6 Astra High, nhánh `feature/fix-ui-02-manager-persistence` đã được bổ sung giải pháp xử lý triệt để 8 lỗi kỹ thuật:

1. **[P1] Bảo toàn tồn kho biến thể khi sửa thông tin sản phẩm (`update_product`)**:
   - *Nguyên nhân trước đây*: Khi sửa metadata không truyền `variants`, hệ thống tự phân bổ lại `stock // len(variants)` bình quân làm sai lệch số tồn thực tế từng size.
   - *Khắc phục*: Tách biệt hoàn toàn việc cập nhật thông tin sản phẩm khỏi tồn kho biến thể. Chỉ cập nhật tồn kho khi có `variant_stocks` rõ ràng; tự động tính tổng `stock` từ tổng số lượng biến thể.
   - *Minh chứng*: `test_update_product_metadata_preserves_variant_stocks` PASS.

2. **[P1] Khớp chính xác biến thể size & màu và phân biệt trạng thái tồn kho**:
   - *Khắc phục*: Khớp chính xác size và color (không gộp mù quáng các màu khác nhau). Phân biệt rành mạch 4 trạng thái qua `VariantStockResult`: `variant_not_found`, `stock_unknown` (None), `out_of_stock` (0), và `in_stock` (>0).
   - *Minh chứng*: `test_get_variant_stock_exact_color_matching` và `test_check_inventory_unknown_stock_preserves_none` PASS.

3. **[P1] Vô hiệu hóa cache cross-session khi Catalog thay đổi**:
   - *Khắc phục*: Loại bỏ hoàn toàn `get_product` và `list_products` khỏi `ToolCache.CACHEABLE_TOOLS`. Bổ sung kiểm tra `catalog_revision` trong `Application.semantic_cache` để tự động invalidate cache khi dữ liệu sản phẩm bị cập nhật.
   - *Minh chứng*: `test_cross_session_cache_bypass_and_synchronization` PASS.

4. **[P1] Đồng bộ thời hạn bảo hành SSOT & chặn proposal cho đơn không tồn tại**:
   - *Khắc phục*: Cập nhật `data/products.json` thống nhất trường `warranty_days` với mô tả sản phẩm (P-503: 30 ngày, P-504: 30 ngày, P-505: 90 ngày, P-506: 365 ngày). Trong `dispute_agent.py`, tra cứu thời hạn bảo hành thực tế từ sản phẩm; khi khách báo đơn không tồn tại (như `O-999999`), chặn hoàn toàn việc tạo `action_proposal` và yêu cầu khách kiểm tra lại mã đơn.
   - *Minh chứng*: `test_dispute_agent_nonexistent_order_no_proposal` và `test_dispute_agent_uses_actual_product_warranty` PASS.

5. **[P2] Thứ tự import bảng trong `import_sqlite.py`**:
   - *Khắc phục*: Đưa `products` và `product_variants` lên trước `orders` trong danh sách import để thỏa mãn ràng buộc khóa ngoại (Foreign Key) khi nạp vào DB rỗng.
   - *Minh chứng*: `test_import_sqlite_table_dependency_order` PASS.

6. **[P2] Backfill toàn diện đơn hàng & Chặn xóa sản phẩm đã có đơn phát sinh**:
   - *Khắc phục*: Hàm `seed()` tự động backfill `product_id` cho toàn bộ các đơn `O-101`..`O-312`. Hàm `delete_product()` kiểm tra ràng buộc nghiệp vụ: chặn xóa các sản phẩm đã có đơn hàng tham chiếu (`product_has_existing_orders` 400).
   - *Minh chứng*: `test_delete_product_with_existing_orders_blocked` và `test_seed_backfill_deepseek_orders` PASS.

7. **[P2] Tách bạch `principal_id` và `customer_id` trong `ActorContext`**:
   - *Khắc phục*: Chuẩn hóa việc phân định `principal_id` (định danh người đăng nhập thực tế) và `customer_id` (ngữ cảnh khách hàng đang thao tác), tránh nhập nhằng gán đè `principal_id = customer_id`.
   - *Minh chứng*: `test_actor_context_separation_principal_and_customer` PASS.

8. **[P2] Loại bỏ fallback ngầm trong `loadManagerAuditTrail`**:
   - *Khắc phục*: Trong `web/app.js`, loại bỏ việc tự động fallback sang `/api/events` khi `/api/manager/events` gặp lỗi để thông báo lỗi rõ ràng, minh bạch cho quản lý.
   - *Minh chứng*: Source code verified, không còn fallback ngầm.

9. **Hợp Nhất Main (PR #33) & Ổn Định Tương Thích PostgreSQL / Docker (`85834d6`, `d7ce461`)**:
   - *Khắc phục*:
     - Chuẩn hóa index dict_row cho PostgreSQL trên các hàm `get_catalog_revision()`, `update_product()`.
     - Tham số hóa câu lệnh `LIKE ?` tránh hiểu nhầm `%` thành format placeholder trong psycopg.
     - Cập nhật test knowledge schema lên version 4.
     - Bổ sung `data/deepseek_seed_data.json` vào Dockerfile.
   - *Minh chứng*: GitHub Actions CI Run #236 PASS 100% (offline + colab-python313), Ops Console Run #143 PASS 100%, Deploy container verification PASS 100%. Toàn bộ 353 regression tests xanh hoàn toàn.

