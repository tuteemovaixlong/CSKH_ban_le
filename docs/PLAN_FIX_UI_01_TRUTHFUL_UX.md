# Module 1: Truthful UX, Safe Fallbacks & Role Boundary (P0)

> **Trạng thái:** PARTIALLY IMPLEMENTED (Phần lớn đã hoàn thành; Còn tồn đọng thẻ 0 khi lỗi và fallback Tiêu chuẩn)  
> **Mức độ minh chứng (Evidence):** L1 Automated Tests · L3 Live Deployed  
> **Audit basis / Documentation baseline reviewed:** `b93eb5a` · **Application verified:** `d3ca3a6`  
> **Ngày rà soát:** 2026-09-21  
> **Mục tiêu:** Loại bỏ toàn bộ các số liệu giả lập, số liệu tĩnh hard-code trong giao diện; đảm bảo nguyên tắc *"Dữ liệu không rõ phải hiển thị Chưa rõ (Unknown), không được biến thiếu sót thành số liệu thành tích"*.

---

## 1. Các Vấn Đề Cốt Lõi Được Giải Quyết & Trạng Thái

1. **Số liệu placeholder tĩnh trong HTML (`web/index.html`)** — 🟢 **ĐÃ SỬA**:
   - Đã xóa: Các số cứng AI Resolution `83.5%`, Escalation `16.5%`, CSAT `4.8 / 5.0` đã được xóa khỏi HTML và thay bằng dấu gạch ngang `—`.
   - Tồn đọng: Nếu API `/api/manager/kpis` bị lỗi, catch chỉ gán lỗi cho AI Res, Escalation, CSAT; các thẻ số lượng đơn (`GMV: 0 ₫`, `Pending: 0`, `Delivered: 0`, `Cancelled: 0`) vẫn hiển thị số `0` thay vì báo `Lỗi`.

2. **CSAT xử lý `null` và hiển thị cỡ mẫu (`web/app.js`)** — 🟢 **ĐÃ SỬA**:
   - Nếu có đánh giá: Hiển thị `${avg_csat} / 5.0 (${csat_sample_size} lượt đánh giá thực tế)`.
   - Nếu chưa có: Hiển thị `Chưa có (Chưa có lượt đánh giá (0 lượt))`.

3. **Thuộc tính sản phẩm thiếu không tự gán giá trị mặc định (`web/app.js`)** — 🟡 **MỘT PHẦN**:
   - Đã sửa: Price null hiển thị `Chưa có giá`, Stock null hiển thị `Chưa kiểm kho`, Warranty null hiển thị `Chưa có thông tin`.
   - Tồn đọng: `(p.variants || []).join(', ') || 'Tiêu chuẩn'` vẫn tự gán chữ `Tiêu chuẩn` khi danh mục sản phẩm hoàn toàn thiếu dữ liệu biến thể.

4. **Định danh lại "Tổng Doanh Thu"** — 🟢 **ĐÃ SỬA**:
   - Đã đổi nhãn KPI thành **"Tổng Giá Trị Đơn (GMV)"** kèm mô tả `(Bao gồm đơn đang xử lý và đã giao)`.

5. **Làm rõ tính chất các nút 1-Click SOP (Tab 3 Manager Console)** — 🟡 **MỘT PHẦN**:
   - Đã sửa: Gắn nhãn rõ ràng **`[Mô phỏng]`** trên tất cả các nút bấm SOP 1..5.
   - Tồn đọng: Sau khi bấm nút, thông báo popup client vẫn nói *"SOP 2 ĐÃ PHÊ DUYỆT"* hoặc *"SOP 4 ĐÃ XỬ LÝ"* với `source: 'store_data'` dù phía backend hoàn toàn không thực hiện mutation.

6. **Ẩn Tool Inspector và bảo vệ route `/api/tools/execute`** — 🟢 **ĐÃ SỬA**:
   - Nút Tool Inspector chỉ hiển thị khi có quyền `STAFF` hoặc `MANAGER`. Khách hàng thông thường không nhìn thấy.
   - Backend `retailops/http/routes.py` đã bổ sung kiểm tra quyền `app.require_permission(STAFF)`.

7. **Giá trị mặc định trong Modal Quản lý Sản phẩm (`web/app.js` & `retailops/http/routes.py`)** — 🟡 **MỘT PHẦN (CẦN TỐI ƯU)**:
   - Hiện trạng: Khi mở form Thêm Sản phẩm (`#btn-open-add-product`), client tự điền sẵn dữ liệu mẫu (`price: 299000`, `stock: 30`, `warranty: 30`, `category: 'Thời trang'`, `variants: 'Trắng · Size M, Đen · Size L'`). Khi mở Sửa (`openEditProductModal`), nếu sản phẩm thiếu dữ liệu sẽ fallback `price || 299000`, `stock ?? 25`, `warranty_days || 30`.
   - Phía backend `retailops/http/routes.py`: Route `POST /api/manager/products` cũng gán fallback `price = int(body.get("price", 299000))`, `stock = body.get("stock", 25)`, `warranty_days = int(body.get("warranty_days", 30))`.
   - Rủi ro Truthful UX: Việc tự điền sẵn số liệu cụ thể (299k, 30 cái) thay vì để trống placeholder khiến quản lý dễ lưu nhầm số liệu giả lập vào DB. Cần chuyển sang placeholder thuần túy hoặc yêu cầu nhập tường minh.

8. **Độ lệch ngữ nghĩa của chỉ số "Tỷ lệ tự giải quyết (AI Resolution)"** — 🟡 **MỘT PHẦN**:
   - Hiện trạng công thức trong `retailops/http/routes.py` (dòng 72-73):
     `escalation_rate = round((esc_count / total_convs) * 100, 1) if total_convs > 0 else 0.0`  
     `ai_resolution_rate = round(100.0 - escalation_rate, 1)`
   - Vấn đề: Đây thực chất là **"Tỷ lệ không chuyển người thật" (Non-handoff rate)** chứ không chứng minh khách hàng đã được giải quyết vấn đề thỏa đáng (ví dụ: AI trả lời sai nhưng khách chán nản tự thoát).
   - Đặc biệt: Khi hệ thống mới khởi động chưa có hội thoại nào (`total_convs = 0`), công thức trả về `ai_resolution_rate = 100.0%`, biến việc thiếu dữ liệu thành số liệu thành tích tuyệt đối.
   - Giải pháp: Cần đổi nhãn hiển thị rõ ràng là *"Tỷ lệ không escalate (Non-handoff)"* hoặc khi `total_convs == 0` thì trả về `null` để UI hiển thị `—` (Chưa có dữ liệu).

---

## 2. Kế Hoạch Chỉnh Sửa File

### [MODIFY] `web/index.html`
- Đã hoàn tất: Bỏ các số tĩnh, đổi nhãn GMV, thêm nhãn `[Mô phỏng]` vào các nút SOP 1..5.

### [MODIFY] `web/app.js`
- Đã hoàn tất: Format CSAT kèm số mẫu thực tế, hiển thị rõ khi thiếu giá/tồn kho/bảo hành, ẩn Tool Inspector.
- Cần hoàn thiện tiếp:
  - Khi `loadManagerKPIs()` bắt lỗi catch: gán thẻ GMV và các thẻ đơn hàng thành `—` hoặc `Lỗi tải`.
  - Không fallback variants thành `Tiêu chuẩn` nếu mảng rỗng; hiển thị rõ `Chưa phân loại size/màu`.
  - Form thêm sản phẩm: xóa các giá trị điền sẵn (299k, 30 tồn kho), chuyển về `placeholder` gợi ý để tránh lưu nhầm dữ liệu giả.
  - Làm rõ thông báo popup SOP sau khi click: *"Đã mô phỏng lệnh duyệt trên giao diện (chế độ demo)"*.

### [MODIFY] `retailops/http/routes.py`
- Đã hoàn tất: Bổ sung `app.require_permission(STAFF)` cho route `/api/tools/execute`.
- Cần hoàn thiện tiếp:
  - Khi `total_convs == 0`, trả về `ai_resolution_rate: null` thay vì `100.0`.
  - Bỏ fallback số liệu giả (299k, 25 tồn kho) trong route thêm/sửa sản phẩm; yêu cầu bắt buộc nhập hoặc gán `null`.

---

## 3. Tiêu Chí Nghiệm Thu (Acceptance Criteria)

- [x] Không còn số liệu cứng `83.5%`, `16.5%`, `4.8/5.0` trong HTML khởi tạo.
- [x] CSAT khi chưa có đánh giá hiển thị `Chưa có đánh giá (0 lượt)`, khi có hiển thị đủ số lượt đánh giá thực tế.
- [x] Đổi tiêu đề KPI thành *Tổng Giá Trị Đơn (GMV)*.
- [x] Nút SOP 1..5 đã được gắn nhãn `[Mô phỏng]`.
- [x] Tool Inspector bị ẩn trên phiên khách hàng thông thường; route `/api/tools/execute` yêu cầu quyền STAFF.
- [ ] Khi API `/api/manager/kpis` gặp lỗi mạng, toàn bộ các thẻ KPI (kể cả GMV và số lượng đơn) chuyển sang hiển thị `—` hoặc `Lỗi tải`, không giữ số `0`.
- [ ] Khi `total_convs = 0`, AI Resolution hiển thị `—` (không hiển thị `100%`).
- [ ] Form Thêm/Sửa sản phẩm không tự điền sẵn số liệu giả (299k, tồn kho 30).
- [ ] Không tự gán `Tiêu chuẩn` cho sản phẩm không có thuộc tính variants.
- [x] CI/CD và toàn bộ 340 tests tự động tiếp tục pass 100%.
