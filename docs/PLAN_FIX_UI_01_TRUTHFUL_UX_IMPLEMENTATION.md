# Kế Hoạch Triển Khai Kỹ Thuật: Phase 1.1 — Truthful UX & Safe Fallbacks

> **Kế hoạch mục tiêu:** PR 1.1 thuộc Giai đoạn 1 (Data & Observability Foundation)
> **Tài liệu tham chiếu:** [PLAN_FIX_UI_01_TRUTHFUL_UX.md](PLAN_FIX_UI_01_TRUTHFUL_UX.md) · [PLAN_ROADMAP_INDEX.md](PLAN_ROADMAP_INDEX.md)
> **Commit baseline:** `56fda06`
> **Trạng thái:** HISTORICAL IMPLEMENTATION SPEC (PR 1.1 baseline snapshot commit `56fda06`; toàn bộ Phase 1 gồm FIX 01..FIX 04 được hoàn thiện qua chuỗi commit tiếp nối; xem tổng quan tại [PLAN_ROADMAP_INDEX.md](PLAN_ROADMAP_INDEX.md))
> **Mục tiêu PR:** Pull Request nhỏ, độc lập, không chạm runtime backend lõi, dễ dàng kiểm thử và rollback.

---

## A. Mục Tiêu Chính Xác (Precise Objectives)

Triển khai triệt để nguyên tắc **"Truthful UX"** trên toàn bộ giao diện quản trị cửa hàng (`web/index.html`, `web/app.js`) và endpoint KPI/Product tương ứng trong `retailops/http/routes.py`:
1. **Xóa bỏ hiển thị số 0 gây ngộ nhận khi tải lỗi**: Khi API `/api/manager/kpis` gặp lỗi mạng hoặc chưa tải xong, thẻ Doanh thu (`GMV`) và 4 thẻ trạng thái đơn hàng (`Pending`, `Delivered`, `Cancelled`, `Mặt hàng active`) phải hiển thị `—` hoặc `Lỗi`, tuyệt đối không giữ số `0 ₫` hay `0` khiến người vận hành tưởng cửa hàng rỗng đơn / 0 đồng doanh thu.
2. **Xử lý trung thực tỷ lệ AI Resolution khi hệ thống mới khởi động**: Khi tổng số cuộc hội thoại trong cơ sở dữ liệu bằng 0 (`total_convs == 0`), API phải trả về `null` cho cả `ai_resolution_rate` và `escalation_rate`; giao diện hiển thị `—` (Chưa có dữ liệu), không được tự tính `100.0 - 0.0 = 100.0%` biến sự thiếu vắng dữ liệu thành thành tích tự động hóa tuyệt đối.
3. **Hiển thị trung thực biến thể sản phẩm**: Không tự động gán chữ `'Tiêu chuẩn'` khi danh mục sản phẩm hoàn toàn thiếu thông tin biến thể; hiển thị rõ ràng `'Chưa phân loại'`.
4. **Loại bỏ dữ liệu mẫu điền sẵn (prefill) trong Modal Quản lý Sản phẩm**:
   - Khi bấm **Thêm Món Mới**: Để trống toàn bộ các ô nhập (giá, tồn kho, bảo hành, danh mục, biến thể) để người dùng nhập liệu thật, chỉ dùng thuộc tính HTML `placeholder` để gợi ý định dạng.
   - Khi bấm **Chỉnh Sửa Sản Phẩm**: Nếu sản phẩm trong DB thiếu giá, tồn kho hoặc bảo hành, hiển thị rỗng để người dùng cập nhật, không fallback ngầm về `299000` VNĐ, `25` tồn kho, hay `30` ngày bảo hành.
5. **Backend validation không tự bơm số liệu giả**: Route `POST /api/manager/products` yêu cầu bắt buộc trường `price` hợp lệ (số không âm), không tự fallback về `299000`; không tự gán `stock = 25` hay `warranty_days = 30` mà mặc định là `0` nếu không khai báo; không tự gán `variants = ["Tiêu chuẩn"]`.
6. **Làm rõ tính chất mô phỏng của các nút 1-Click SOP**: Khi quản lý bấm các nút SOP 1..5 trên giao diện, thông báo popup ghi rõ tiền tố `[Mô phỏng]` kèm chú thích `(Chế độ demo giao diện - chưa kết nối backend mutation)` với nguồn thông tin phù hợp, tránh gây ngộ nhận cho người chấm thi/đánh giá rằng hệ thống đã kích hoạt bưu tá hoặc ngân hàng thật.

---

## B. Danh Sách Files Dự Kiến MODIFY

Chỉ chỉnh sửa đúng 4 file sau:

| STT | File | Phạm Vi Chỉnh Sửa |
| :--- | :--- | :--- |
| 1 | `web/index.html` | Khởi tạo ban đầu của `#kpi-revenue` và 4 thẻ mini-pill thành `—`; chuẩn hóa nhãn mô tả AI Resolution thành "Tỷ lệ Tự Động (Non-Handoff)". |
| 2 | `web/app.js` | Khối `catch` của `loadManagerKPIs()`; fallback biến thể trong `renderManagerProductsTable()`; dọn prefill trong `btnOpenAddProd.onclick` và `openEditProductModal()`; bổ sung nhãn `[Mô phỏng]` cho các thông báo popup SOP 1..5. |
| 3 | `retailops/http/routes.py` | Route `GET /api/manager/kpis`: trả về `None` khi `total_convs == 0`; Route `POST /api/manager/products`: bắt buộc `price`, loại bỏ fallback giả lập 299k/25/30 ngày. |
| 4 | `tests/test_manager_crud.py` | Thêm test case kiểm tra `ai_resolution_rate` và `escalation_rate` là `None` khi 0 conversation; kiểm tra validation bắt buộc `price` và không fallback dummy values khi tạo sản phẩm. |

*(Tùy chọn bổ sung assertions nếu cần: `tests/test_audit_remediation.py` để củng cố test suite hiện hữu).*

---

## C. Danh Sách Files Tuyệt Đối Không Được Chạm Tới (Strictly Untouched)

Tuân thủ nghiêm ngặt ranh giới kỹ thuật đã khóa:

- `retailops_conversation.py`: **CẤM CHẠM** — Kiến trúc Catalog và cơ chế in-memory fallback sẽ được chuyển sang PostgreSQL ở Phase 1.2 (`PLAN_FIX_UI_02_MANAGER_PERSISTENCE.md`).
- `retailops/business/store.py`: **CẤM CHẠM** — Giữ nguyên schema SQLite/PostgreSQL hiện hành, không chạy migration DB.
- `retailops/workflow/*`: **CẤM CHẠM** — Toàn bộ LangGraph, routing, multiagent worker, `dispute_agent.py` thuộc Phase 3.
- `retailops_tools.py`: **CẤM CHẠM** — Không sửa định nghĩa tool hay logic `check_inventory`.
- `retailops_mcp_server.py`: **CẤM CHẠM** — Không thay đổi giao thức FastMCP server.
- `evals/*`: **CẤM CHẠM** — Không thay đổi bất kỳ kịch bản nào trong master 250 ca benchmark.
- `scripts/*`: **CẤM CHẠM** — Không chỉnh sửa các cổng kiểm định hợp đồng và deployment.
- `Dockerfile*`, `docker-compose*`, `Caddyfile`: **CẤM CHẠM** — Giữ nguyên hạ tầng đóng gói và proxy.

---

## D. Hiện Trạng Trong Code Hiện Tại (Current Behavior)

### 1. `web/index.html` (Dòng 280, 289-301)
- Dòng 280: Khởi tạo cứng `<strong class="kpi-val" id="kpi-revenue">0 ₫</strong>`.
- Dòng 289, 293, 297, 301: Khởi tạo cứng `<strong id="stat-pending-val">0</strong>`, `<strong id="stat-delivered-val">0</strong>`, `<strong id="stat-cancelled-val">0</strong>`, `<strong id="stat-products-val">0</strong>`.
- Khi trang web vừa mở hoặc API phản hồi chậm, giao diện thể hiện như cửa hàng có 0đ doanh thu và 0 đơn hàng thay vì trạng thái đang chờ dữ liệu (`—`).

### 2. `web/app.js` (Dòng 1850-1863)
```javascript
async function loadManagerKPIs() {
  try {
    const kpis = await api('/api/manager/kpis');
    // ...
    if (byId('kpi-revenue')) byId('kpi-revenue').textContent = money(kpis.total_revenue || 0);
    // ...
    if (byId('stat-pending-val')) byId('stat-pending-val').textContent = kpis.pending_orders ?? 0;
  } catch (e) {
    console.warn('Lỗi tải KPIs:', e);
    if (byId('kpi-ai-res')) byId('kpi-ai-res').textContent = 'Lỗi';
    if (byId('kpi-human-esc')) byId('kpi-human-esc').textContent = 'Lỗi';
    if (byId('kpi-csat')) byId('kpi-csat').textContent = 'Lỗi';
    // KHUYẾT THIẾU: kpi-revenue, kpi-orders-count, stat-pending-val, stat-delivered-val,
    // stat-cancelled-val, stat-products-val hoàn toàn không được xử lý trong catch!
  }
}
```

### 3. `retailops/http/routes.py` (Dòng 70-73)
```python
conv_row = db.execute("SELECT COUNT(*) FROM conversations").fetchone()
total_convs = conv_row[0] if conv_row else 0
escalation_rate = round((esc_count / total_convs) * 100, 1) if total_convs > 0 else 0.0
ai_resolution_rate = round(100.0 - escalation_rate, 1)
```
- Khi `total_convs == 0`, `escalation_rate = 0.0`, dẫn đến `ai_resolution_rate = 100.0%`. Hệ thống mới dựng chưa có khách nào chat đã tự báo cáo AI giải quyết thành công 100%.

### 4. `web/app.js` (Dòng 1906)
```javascript
const tdVar = el('td', '', (p.variants || []).join(', ') || 'Tiêu chuẩn');
```
- Nếu `p.variants` rỗng hoặc không có, tự động gán chữ `'Tiêu chuẩn'`.

### 5. `web/app.js` (Dòng 1938-1960)
- Thêm sản phẩm (`btnOpenAddProd.onclick`):
```javascript
byId('prod-category').value = 'Thời trang';
byId('prod-price').value = '299000';
byId('prod-stock').value = '30';
byId('prod-warranty').value = '30';
byId('prod-variants').value = 'Trắng · Size M, Đen · Size L';
```
- Sửa sản phẩm (`openEditProductModal`):
```javascript
byId('prod-price').value = p.price || 299000;
byId('prod-stock').value = p.stock !== null && p.stock !== undefined ? p.stock : 25;
byId('prod-warranty').value = p.warranty_days || 30;
```

### 6. `retailops/http/routes.py` (Dòng 198-205)
```python
price = int(body.get("price", 299000))
variants = body.get("variants", ["Tiêu chuẩn"])
stock = body.get("stock", 25)
warranty_days = int(body.get("warranty_days", 30))
```
- Tự động điền giá 299.000đ, tồn kho 25 chiếc, biến thể "Tiêu chuẩn" nếu request thiếu dữ liệu.

### 7. `web/app.js` (Dòng 2026-2041)
- Khi click SOP 1..5:
```javascript
message(`⚡ SOP 1 ĐÃ KÍCH HOẠT: Đã gửi lệnh khiếu nại bưu cục...`, 'assistant', 'store_data');
message(`✅ SOP 2 ĐÃ PHÊ DUYỆT: Lệnh Đổi mới 1-1 tận nhà đã được duyệt...`, 'assistant', 'store_data');
```
- Ghi nhận `source: 'store_data'` như một mutation thành công từ cơ sở dữ liệu thật.

---

## E. Hành Vi Kỳ Vọng Sau Khi Sửa (Expected Behavior)

### 1. Trạng thái khởi tạo và Fallback khi lỗi API KPI:
- Khởi tạo HTML: `#kpi-revenue` hiển thị `—`, 4 pill trạng thái đơn hàng hiển thị `—`.
- Khi API `/api/manager/kpis` bị lỗi (mất mạng, server 500):
  - `#kpi-ai-res`: `Lỗi`
  - `#kpi-human-esc`: `Lỗi`
  - `#kpi-csat`: `Lỗi`
  - `#kpi-revenue`: `—`
  - `#kpi-orders-count`: `Lỗi tải dữ liệu`
  - `#stat-pending-val`, `#stat-delivered-val`, `#stat-cancelled-val`, `#stat-products-val`: `—`

### 2. Độ chuẩn xác của chỉ số AI Resolution:
- Trong `retailops/http/routes.py`:
  - Khi `total_convs == 0`: trả về `ai_resolution_rate: None`, `escalation_rate: None`.
  - Khi `total_convs > 0`: tính toán tỷ lệ thật.
- Trong `web/app.js`: Đã có sẵn logic kiểm tra `!== null && !== undefined`. Khi nhận `null`, UI hiển thị dấu gạch ngang `—`.
- Trong `web/index.html`: Thẻ KPI được đổi phụ đề thành `Tỷ lệ phiên không cần can thiệp người thật` để phản ánh đúng bản chất kỹ thuật (Non-handoff rate).

### 3. Hiển thị biến thể trong bảng sản phẩm:
- Khi `(p.variants || []).length === 0`: Hiển thị `Chưa phân loại` thay vì `Tiêu chuẩn`.

### 4. Modal Quản lý Sản phẩm (Thêm/Sửa):
- Khi mở modal thêm món mới: Toàn bộ các ô nhập liệu `prod-name`, `prod-category`, `prod-price`, `prod-stock`, `prod-warranty`, `prod-variants`, `prod-desc` đều để rỗng `''`. Placeholder HTML hướng dẫn định dạng trực quan.
- Khi mở modal sửa: Chỉ điền giá trị nếu thuộc tính tồn tại; nếu `null`/`undefined` thì để ô nhập rỗng `''`.
- Backend `POST /api/manager/products`:
  - Kiểm tra bắt buộc: `require("price" in body and isinstance(body.get("price"), (int, float)) and body["price"] >= 0, 400, "invalid_price", "Giá sản phẩm phải là số không âm.")`.
  - Mặc định an toàn: `variants = []` (nếu không cung cấp), `stock = int(body.get("stock", 0))`, `warranty_days = int(body.get("warranty_days", 0))`.

### 5. Thông báo popup thao tác SOP 1..5:
- Nội dung thông báo hiển thị rõ ràng:
  - `[Mô phỏng] SOP 1: Mô phỏng gửi lệnh khiếu nại bưu cục yêu cầu giao lại trong ca cho đơn O-301. (Chế độ demo giao diện)`
  - `[Mô phỏng] SOP 2: Mô phỏng duyệt lệnh Đổi mới 1-1 tận nhà cho đơn O-302. (Chế độ demo giao diện)`
  - `[Mô phỏng] SOP 3: Mô phỏng duyệt Đổi size 2 chiều freeship cho đơn O-303. (Chế độ demo giao diện)`
  - `[Mô phỏng] SOP 4: Mô phỏng cấp voucher đền bù 50.000đ cho đơn O-304. (Chế độ demo giao diện)`
  - `[Mô phỏng] SOP 5: Mô phỏng tiếp nhận khẩn cấp & kích hoạt Strict Mode. (Chế độ demo giao diện)`
- Tag nguồn: `'ui_simulation'` (hoặc `'demo_sop'`) để phân biệt rạch ròi với `'store_data'`.

---

## F. Kế Hoạch Kiểm Thử (Test Cases Cần Thêm / Sửa)

### 1. Unit Tests Mới trong `tests/test_manager_crud.py`:
- `test_manager_kpis_zero_conversations_returns_none()`:
  - Khởi tạo store mới với 0 conversations.
  - Gọi `GET /api/manager/kpis`.
  - Khẳng định: `res["ai_resolution_rate"] is None` và `res["escalation_rate"] is None`.
- `test_manager_create_product_validation()`:
  - Gọi `POST /api/manager/products` không truyền `price` -> Khẳng định lỗi 400 `invalid_price`.
  - Gọi `POST /api/manager/products` với `price: -5000` -> Khẳng định lỗi 400 `invalid_price`.
  - Gọi `POST /api/manager/products` với payload tối giản (`id`, `name`, `price: 150000`) -> Khẳng định sản phẩm được tạo có `variants == []`, `stock == 0`, `warranty_days == 0`, không bị gán 299k hay 25.

### 2. Bổ sung Assertion trong `tests/test_audit_remediation.py`:
- Trong `test_manager_kpis_real_data_without_dummy_fallback()`:
  - Thêm `self.assertIsNone(res["ai_resolution_rate"])` và `self.assertIsNone(res["escalation_rate"])`.

### 3. Kiểm thử hồi quy toàn diện (Full Regression Suite):
- Chạy toàn bộ 340 tests tự động:
  ```bash
  python -m unittest discover -s tests -p "test_*.py"
  ```
  Yêu cầu: Đạt 100% PASS (340 tests OK, 43 skipped).
- Chạy cổng kiểm tra tính toàn vẹn tài liệu:
  ```bash
  python scripts/check_docs_contract.py
  ```
  Yêu cầu: Đạt 4/4 gates SUCCESS (0 lỗi).

---

## G. Rủi Ro Suy Thoái & Biện Pháp Phòng Ngừa (Regression Risks)

| Rủi Ro Suy Thoái | Mức Độ | Biện Pháp Phòng Ngừa |
| :--- | :--- | :--- |
| **Giao diện web gặp lỗi runtime khi `ai_resolution_rate` trả về `null`** | Thấp | Code `web/app.js` đã có guard `(kpis.ai_resolution_rate !== null && kpis.ai_resolution_rate !== undefined) ? ... : '—'`. Sẽ kiểm tra thêm mọi điểm render liên quan. |
| **Các bài test hiện hữu bị fail khi bắt buộc trường `price` trong API tạo sản phẩm** | Trung bình | Đã kiểm tra: `test_manager_crud_lifecycle` đã truyền sẵn `'price': 399000`. Test `test_manager_rbac_rejection` truyền thiếu price nhưng bị chặn bởi quyền hạn (403) trước khi validate body. |
| **Form HTML chặn submit do trường không bắt buộc bị xóa giá trị** | Thấp | Chỉ các trường có thuộc tính `required` (`prod-id`, `prod-name`, `prod-price`) mới bắt buộc nhập. Các trường khác có thể để trống theo đúng chuẩn HTML form. |
| **Vi phạm hợp đồng kiểm tra tài liệu `check_docs_contract.py`** | Thấp | File kế hoạch sử dụng đường dẫn relative nội bộ chuẩn Markdown, không chứa URI schema tuyệt đối hay mẫu stale Git HEAD. |

---

## H. Trình Tự Thực Thi Khi Được Phê Duyệt

1. Tạo nhánh git riêng: `git checkout -b feat/phase-1.1-truthful-ux`
2. Chỉnh sửa `retailops/http/routes.py` (KPI null handling & product validation)
3. Chỉnh sửa `tests/test_manager_crud.py` và chạy test xác minh
4. Chỉnh sửa `web/index.html` và `web/app.js`
5. Chạy toàn bộ 340 tests regression + 4 script contract check
6. Báo cáo kết quả chi tiết, sẵn sàng cho người dùng nghiệm thu PR.
