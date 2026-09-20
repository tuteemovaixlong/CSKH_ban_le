# Module 1: Truthful UX, Safe Fallbacks & Role Boundary (P0)

> **Mục tiêu**: Loại bỏ toàn bộ các số liệu giả lập, số liệu tĩnh hard-code trong giao diện; đảm bảo nguyên tắc *"Dữ liệu không rõ phải hiển thị Chưa rõ (Unknown), không được biến thiếu sót thành số liệu thành tích"*.

---

## 1. Các Vấn Đề Cốt Lõi Được Giải Quyết

1. **Số liệu placeholder tĩnh trong HTML (`web/index.html`)**:
   - Hiện tại: Thẻ KPI đang chứa sẵn số liệu cứng: AI Resolution: `83.5%`, Escalation: `16.5%`, CSAT: `4.8 / 5.0`. Nếu API `/api/manager/kpis` bị lỗi mạng hoặc crash, số demo này vẫn tồn tại khiến người quản trị lầm tưởng hệ thống đang chạy tốt.
   - Khắc phục: Khởi tạo tất cả bằng dấu gạch ngang `—` hoặc chữ `Đang tải...`. Khi API lỗi, hiển thị cảnh báo đỏ `Không thể tải số liệu` thay vì giữ số cũ.

2. **CSAT xử lý `null` và hiển thị cỡ mẫu (`web/app.js`)**:
   - Hiện tại: Khi chưa có đánh giá nào, backend trả `avg_csat = null`, frontend hiển thị `null / 5.0`.
   - Khắc phục: 
     - Nếu có đánh giá: Hiển thị `${avg_csat} / 5.0 (${csat_sample_size} lượt đánh giá)`.
     - Nếu chưa có: Hiển thị `Chưa có đánh giá (0 lượt)`.

3. **Thuộc tính sản phẩm thiếu không được tự gán giá trị mặc định**:
   - Hiện tại: `price || 299000`, `stock || 25`, `warranty || 30 ngày`. Biến dữ liệu thiếu thành dữ liệu thật!
   - Khắc phục: Hiển thị rõ ràng `Chưa cập nhật giá`, `Chưa kiểm kê kho`, `Chưa có thông tin bảo hành`.

4. **Định danh lại "Tổng Doanh Thu"**:
   - Hiện tại: Cộng toàn bộ đơn hàng chưa hủy kể cả `pending` chưa thanh toán và gọi là "Tổng Doanh Thu".
   - Khắc phục: Đổi nhãn KPI thành **"Tổng Giá Trị Đơn Hàng (GMV)"** kèm chú thích rõ ràng `(Bao gồm đơn đang xử lý và đã giao)`.

5. **Làm rõ tính chất các nút 1-Click SOP (Tab 3 Manager Console)**:
   - Hiện tại: Nút SOP 1..5 chỉ in tin nhắn `message(...)` trên client nhưng tuyên bố "ĐÃ DUYỆT / ĐÃ CẤP VOUCHER".
   - Khắc phục: Gắn nhãn rõ ràng **`[Demo Mô Phỏng]`** trên từng nút hoặc hiển thị hộp thoại xác nhận mô phỏng để người dùng phân biệt rõ giữa hành động nghiệp vụ thực và kịch bản trình diễn.

6. **Ẩn Tool Inspector và bảo vệ route `/api/tools/execute`**:
   - Hiện tại: Khách hàng thông thường nhìn thấy nút Tool Inspector trong sidebar và route `/api/tools/execute` không kiểm tra quyền.
   - Khắc phục: Chỉ hiển thị Tool Inspector khi `role in ('manager', 'staff', 'admin')`. Backend route `/api/tools/execute` bổ sung kiểm tra quyền.

---

## 2. Kế Hoạch Chỉnh Sửa File

### [MODIFY] [web/index.html](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/web/index.html)
- Thay đổi các giá trị mặc định trong HTML:
  - `#kpi-ai-res`: đổi từ `83.5%` -> `—`
  - `#kpi-human-esc`: đổi từ `16.5%` -> `—`
  - `#kpi-csat`: đổi từ `4.8 / 5.0` -> `—`
  - Thêm thẻ hiển thị số lượng mẫu CSAT `#kpi-csat-sample`.
  - Đổi tiêu đề `Tổng Doanh Thu` -> `Tổng Giá Trị Đơn (GMV)`.
  - Bổ sung nhãn `[Mô phỏng]` cho các nút SOP 1..5.

### [MODIFY] [web/app.js](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/web/app.js)
- Trong `loadManagerKPIs()`:
  - Bắt lỗi cụ thể, nếu lỗi hiển thị text `Lỗi tải` thay vì nuốt ngoại lệ `console.warn`.
  - Format CSAT: kiểm tra `kpis.avg_csat !== null` để format kèm `csat_sample_size`.
- Trong `renderManagerProductsTable()`:
  - Nếu `p.price === null || p.price === undefined`, render `Chưa có giá`.
  - Nếu `p.stock === null || p.stock === undefined`, render `Chưa kiểm kho`.
  - Nếu `!p.warranty_days`, render `Không bảo hành / Chưa rõ`.
- Giới hạn hiển thị Tool Inspector: chỉ hiện khi vai trò là `staff` hoặc `manager`.

### [MODIFY] [retailops/http/routes.py](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/retailops/http/routes.py)
- Route `/api/tools/execute`: Thêm kiểm tra quyền `app.require_permission(STAFF)`.
- Route `/api/manager/kpis`: Nếu database query gặp lỗi, không được gán `ai_resolution_rate = 100.0`, mà trả về `ai_resolution_rate = None` hoặc raise lỗi rõ ràng.

---

## 3. Tiêu Chí Nghiệm Thu (Acceptance Criteria)
- [ ] Không còn bất kỳ số liệu cứng nào xuất hiện khi API KPI chưa trả dữ liệu hoặc gặp lỗi.
- [ ] CSAT khi chưa có đánh giá hiển thị `Chưa có đánh giá (0 lượt)`, khi có hiển thị đủ số lượt đánh giá.
- [ ] Sản phẩm thiếu trường hiển thị `Chưa cập nhật`, không bị tự gán `299k/25 cái/30 ngày`.
- [ ] Tool Inspector bị ẩn trên phiên khách thông thường.
- [ ] CI/CD và toàn bộ test suite hiện có tiếp tục pass 100%.
