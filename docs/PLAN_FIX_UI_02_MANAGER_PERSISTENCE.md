# Module 2: Store Manager Persistence, Shared Inventory & Audit Scope (P0)

> **Trạng thái:** PENDING / P0 HIGHEST PRIORITY (Chưa triển khai)  
> **Mức độ minh chứng (Evidence):** L3 Live Deficiency Ghi nhận từ Kiến trúc  
> **Snapshot tham chiếu:** `d3ca3a6` (Application Verified) · `0c9a7d4` (Git HEAD)  
> **Ngày rà soát:** 2026-09-21  
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

3. **Phạm vi Audit Trail trong Manager Console (`/api/events`)**:
   - Hiện tại: Backend `store.events(customer)` lọc `WHERE customer_id=? LIMIT 30`. Manager chỉ thấy sự kiện của chính tài khoản Manager (hoặc customer mẫu), không thấy các thao tác trên đơn của khách hàng khác!
   - Khắc phục:
     - Bổ sung route chuyên biệt cho Quản lý: `GET /api/manager/events` (hoặc phân nhánh trong `/api/events` khi `role == 'manager'`).
     - Truy vấn sự kiện toàn shop: `SELECT id, customer_id, kind, order_id, payload, created_at FROM events ORDER BY id DESC LIMIT 100`.
     - Cột khách hàng hiển thị đúng `customer_id` thật của sự kiện thay vì fallback thành `Hệ thống`.

4. **Tự động mở Store Manager Console khi đăng nhập**:
   - Hiện tại: User đăng nhập `manager` phải tự tìm và bấm nút góc trên mới mở được bảng điều khiển (trong khi `staff` tự động mở Staff Desk).
   - Khắc phục: Trong `openSession()`, bổ sung `if (session.role === 'manager') openManagerConsole();`.

---

## 2. Kế Hoạch Chỉnh Sửa File

### [MODIFY] `retailops_conversation.py`
- Nâng cấp `Catalog`:
  - Hỗ trợ `ProductStore` kết nối trực tiếp với DB SQLite/PostgreSQL của hệ thống (`app.store`).
  - Nếu DB chưa có bảng products, tự động nạp seed từ `data/products.json` lần đầu tiên (idempotent seed import).
  - Mọi thao tác `add_product`, `update_product`, `delete_product` đều ghi trực tiếp vào DB, đảm bảo tất cả các phiên `Application` đều đọc chung một bảng dữ liệu.

### [MODIFY] `retailops_tools.py`
- Trong hàm `check_inventory`:
  - Loại bỏ việc phụ thuộc duy nhất vào dictionary cứng `stock_map`.
  - Đọc từ `product = self.catalog.products.get(pid)`.
  - Nếu sản phẩm có thông tin `stock` hoặc `variants_stock` trong DB/Catalog, ưu tiên đọc số liệu động này.
  - Bảo tồn fallback an toàn cho các test cũ của P-101..P-301 nếu chưa có variant matrix trong catalog.

### [MODIFY] `retailops/http/routes.py`
- Trong nhánh `GET /api/events`:
  - Nếu `getattr(app, 'role', '') == 'manager'`:
    - Truy vấn sự kiện toàn hệ thống từ bảng `events` (kèm `customer_id`).
    - Trả về danh sách sự kiện đầy đủ cho Manager.
- Đảm bảo quyền `MANAGER` được kiểm soát chặt chẽ.

### [MODIFY] `web/app.js`
- Trong `openSession()`: Tự động gọi `openManagerConsole()` khi `session.role === 'manager'`.
- Trong `loadManagerAuditTrail()`: Đọc đúng trường `ev.customer_id` từ backend trả về.

---

## 3. Tiêu Chí Nghiệm Thu (Acceptance Criteria)

- [ ] Manager sửa sản phẩm P-203 tồn kho lên 50 cái -> Mở một tab ẩn danh / session khác kiểm tra thấy đúng 50 cái.
- [ ] Chatbot AI gọi `check_inventory` phản hồi đúng số lượng tồn kho mới được Manager cập nhật.
- [ ] Manager Console tự động mở khi đăng nhập tài khoản có quyền `manager`.
- [ ] Tab Audit Trail hiển thị đầy đủ các sự kiện mua hàng, hủy đơn, sửa trạng thái đơn của toàn bộ khách hàng trong shop, cột khách hàng hiển thị mã khách cụ thể (C-001, C-002...).
- [ ] Toàn bộ test suite tự động tiếp tục pass 100%.
