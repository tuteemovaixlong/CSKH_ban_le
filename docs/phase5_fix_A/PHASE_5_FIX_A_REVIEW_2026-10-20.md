# Phase 5 Fix A — Review: Manager navigation & demo-order cleanup

**Ngày:** 2026-10-20
**Trạng thái:** Review đã lập từ source checkout và ảnh do chủ dự án cung cấp; code remediation và automated regression (`tests/test_phase5_fix_a.py`, `tests/test_postgres.py`, `tests/test_public_session.js`) đã được triển khai trên nhánh `fix/phase5-fix-a-manager-nav-order-cleanup` (base `ef40d131ef9244fa51844ae8990a05888990cdc8`). Trạng thái mất hàng tab trên ảnh chụp màn hình đầu tiên vẫn được ghi nhận là **unreproduced trên production runtime** (chỉ xác minh được trong source việc `openManagerConsole()` trước đây không reset `currentManagerTab` về `kpis` và thiếu nút quay về tổng quan cố định trong từng tab/header). One-time production DB cleanup (`FIXA-DEPLOY2`) vẫn **PENDING** vì môi trường thực thi cục bộ không có AWS/SSM credentials và chưa truy vấn trực tiếp tenant trên EC2.
**Phạm vi:** đúng hai vấn đề; xem [acceptance criteria](PHASE_5_FIX_A_ACCEPTANCE_CRITERIA.md) và [handoff](PHASE_5_FIX_A_EXECUTION_HANDOFF.md).

## Tóm tắt

Có cơ sở kỹ thuật giải thích vì sao đơn cũ còn tên cũ sau khi sửa catalog: bảng `orders` lưu snapshot sản phẩm (tên/biến thể/giá) tại thời điểm tạo đơn. Sửa tên master trong `products` không tự sửa snapshot của một đơn đã tạo. Bảng manager hiện chưa có API xóa đơn; API xóa sản phẩm từ chối khi sản phẩm còn được đơn tham chiếu.

Vấn đề điều hướng có thể liên quan đến việc tab quản trị giữ trạng thái lần mở trước: `openManagerConsole()` mở dialog/tải dữ liệu nhưng không đặt lại tab về KPI. Tuy vậy, ảnh thứ nhất không có hàng tab, trong khi ảnh thứ hai có; source đang xem vẫn khai báo tab và handler chuyển tab. Vì chưa tái hiện đúng thao tác hoặc kiểm tra asset đang phục vụ, đây là **nguyên nhân khả dĩ, chưa được xác minh**. FIX-A phải thêm đường về tổng quan nhìn thấy được và kiểm thử interaction; không được tuyên bố đã tìm thấy nguyên nhân production chỉ từ ảnh.

## Bằng chứng và giới hạn

### A. Manager không quay lại trang tổng quan

- `web/index.html` khai báo `<dialog>` manager, tab `Tổng quan & KPIs`, tab `Hàng hóa & Kho`, và các panel tương ứng.
- `web/app.js` có `currentManagerTab`/`openManagerConsole()` và click handler đổi class active trên tab/panel. Mở lại console hiện chưa đặt lại tab về `kpis`, nên có thể mở lại ở tab sản phẩm trước đó.
- `web/styles.css` tách hàng tab khỏi vùng panel cuộn; kiểm tra CSS tĩnh hiện có không mô phỏng chuỗi click người dùng.
- Hai screenshot chỉ chứng minh hai trạng thái giao diện khác nhau. Không chứng minh tab đã được click nhưng không hoạt động. Cần xác minh route/asset SHA hiện phục vụ và tái hiện bằng vai trò manager.

**Hướng sửa cần nghiệm thu:** mỗi lần mở bảng quản trị bắt đầu ở tổng quan; trong mọi panel/danh mục luôn có một điều khiển “Về tổng quan”/“Tổng quan & KPIs” hiển thị và hoạt động, kể cả khi nội dung cuộn. Không phụ thuộc nút Back của trình duyệt hoặc hard refresh.

### B. Tên cũ còn trong đơn sau khi đổi tên P-602

- `retailops/business/schema.py` lưu dữ liệu snapshot trong order; frontend render thông tin đơn từ order result thay vì thay lịch sử bằng catalog hiện tại. Vì vậy chỉnh `products.name` thành tên mới không tự đổi `orders.name` đã lưu.
- `retailops/identity/persistent.py` tạo dữ liệu đơn demo bằng ID sinh động, trong đó có đường tạo đơn delivered dùng P-602; không coi O-819126 là ID cố định trong source.
- Nguồn catalog/fixtures/import có thể còn tham chiếu P-602 hoặc tên cũ: `data/products.json`, `retailops/business/store.py`, `retailops/sales/fixtures.py`, `retailops/sales/simulator.py`, cùng adapter import. Cần phân biệt producer runtime với test/evaluation/historical docs; không xóa mọi kết quả `rg` máy móc.
- API manager hiện có đổi trạng thái đơn, nhưng chưa có delete-order API. Product delete có guard khi còn order reference.
- PostgreSQL dùng schema theo tenant; order ID đơn độc không đủ khóa dữ liệu. `order_items`, `proposals`, `business_events`, `conversations`, `imported_events` có các quan hệ và semantics khác nhau; một số FK không cascade hoặc không phải FK. Xóa mù có thể phá audit, replay/idempotency hoặc hội thoại.

## Bằng chứng do chủ dự án cung cấp

Ảnh mới nhất cho thấy catalog P-602 đã được sửa qua vai trò manager thành **“Quần tây đen hàn quốc”**, giá 520.000₫, tồn 40, biến thể Đen/Size S–L, bảo hành 90 ngày. Ảnh là bằng chứng UI do người dùng gửi, chưa chứng minh row tenant/DB hiện tại độc lập.

Tuple mục tiêu theo trao đổi trước đó:

| Trường kỳ vọng | Giá trị |
|---|---|
| Order | `O-819126` |
| Customer | `CG-d9b82ffe` |
| Product | `P-602` |
| Order status | `delivered` / đã giao |
| Order total | `520000 VND` |
| Tên snapshot cũ | `Quần tây ống đứng tôn dáng` |

Tenant ID chưa được chủ dự án cung cấp trong hội thoại và chưa được truy vấn trực tiếp. Target chỉ hợp lệ khi read-only inventory xác nhận đúng **một** tuple này trong tenant synthetic/demo. Nếu giá trị hoặc tenant không khớp, không xóa.

## Chính sách dữ liệu an toàn

1. Giữ P-602 và giá trị catalog mới. Đây là sản phẩm hiện tại, không phải mục tiêu xóa.
2. Gỡ đúng order snapshot O-819126 khỏi dữ liệu nghiệp vụ đang hiển thị, cùng những dependent operational rows được chứng minh thuộc chính đơn đó và được phép xóa theo schema.
3. Trước mọi production write: inventory read-only theo tenant → backup đã kiểm tra → dry-run có counts/keys → transaction có guard theo tuple → post-check. Tạo purge tombstone/replay guard để login seed/import không tái tạo đơn.
4. Bảo toàn append-only business/security audit. Không xóa customer/session, unrelated orders, confirmed workflow history, audit, hay source/idempotency evidence chỉ để làm `rg` sạch. Nếu các record bất biến còn chứa tên cũ thì báo rõ giới hạn; không cam kết xóa lịch sử bất biến.
5. Không dùng generic hard-delete endpoint trong manager UI. Nếu cần lệnh one-time operator maintenance, phải tenant-scoped, dry-run mặc định, explicit execute, idempotent, backup-gated và có audit.

## Kết luận review

- UI: có thể sửa UX an toàn bằng home reset + persistent return-to-overview; vẫn phải reproduction/verify runtime trước khi kết luận root cause.
- Data: catalog rename không đổi order snapshot; xóa order là thay đổi dữ liệu riêng. P-602 phải được giữ theo screenshot mới. Chỉ xóa đúng O-819126 sau khi xác minh tenant/tuple và backup.
- Không có bằng chứng trong review này rằng production DB đã được xóa, deploy đã chạy, hay CI đã xanh.

Đi tiếp theo [acceptance criteria](PHASE_5_FIX_A_ACCEPTANCE_CRITERIA.md), dùng [trigger trong handoff](PHASE_5_FIX_A_EXECUTION_HANDOFF.md), và ghi bằng chứng vào [evidence](PHASE_5_FIX_A_EVIDENCE.md). Các gate cấp dự án vẫn theo [acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md) và [current status](../CURRENT_PROJECT_STATUS.md).
