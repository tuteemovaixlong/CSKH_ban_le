# Kịch bản demo trọn vòng bồi thường giao trễ và voucher (< 5 phút)

> Tài liệu hướng dẫn vận hành cho buổi trình diễn trên production sau khi hoàn tất rollout W6.1b-2 theo mục 7 của [`RUNBOOK.md`](RUNBOOK.md).
> Chỉ dùng dữ liệu giả lập của `marketplace_sim`. Bộ sinh sàn ảo không nằm trong image production và luôn chạy trên máy trạm cục bộ của operator.

## 0. Chuẩn bị trước giờ trình diễn (làm sẵn 1 lần)

1. **Trên EC2 (qua phiên SSM quản trị):** cửa hàng demo đã chạy xong mục 7 của [`RUNBOOK.md`](RUNBOOK.md) (đã có khóa `retailops_recipient_key_v1`, đã `reset-marketplace-demo`, đã nhập `data/demo_events/store_events.jsonl --rebase-clock now` và `seed-account-orders --all-customers`). Mở sẵn phiên `sudo -i` tại `/opt/retailops`, khai báo mảng `cweb` của Docker Compose và biến `TENANT_ID="<tenant_id>"` của cửa hàng demo (không in khóa hay biến mật ra màn hình).
2. **Trên máy trạm cục bộ của operator** (có bản checkout mã nguồn repo này): khởi tạo sẵn thư mục kho sàn ảo một lần:
   ```bash
   python -m marketplace_sim init --data-dir /tmp/demo_sim --seed 20261106 --merchant-id MERCHANT-SIM-001
   ```
3. **Trên trình duyệt:** mở sẵn 2 cửa sổ ẩn danh tách biệt:
   - **Cửa sổ Khách hàng:** đăng nhập tài khoản khách sở hữu đơn giao trễ quá 48 giờ (ví dụ đơn mẫu cửa hàng `SIM-O-ST-013` trong bộ `store_events.jsonl`, hoặc đơn `shipping` mẫu của tài khoản khách đã quá `promised_delivery_by` trên 48 giờ).
   - **Cửa sổ Nhân viên / Quản lý:** đăng nhập Staff Desk hoặc Manager Console của cùng cửa hàng.

---

## Bước 1 (0:00 – 1:00) — Khách hỏi về đơn giao trễ; AI xác nhận trễ và chuyển nhân viên

1. Ở **Cửa sổ Khách hàng**, chọn đơn giao trễ (ví dụ `SIM-O-ST-013`) và gửi tin nhắn:
   > `Đơn hàng này của tôi đã quá ngày giao dự kiến, shop kiểm tra giúp tôi với.`
2. Kết quả quan sát trên màn hình:
   - Vòng quét nền của server đã ghi thông báo hệ thống chủ động `sys-notice-<shipment_id>-late_delivery` trong hội thoại của khách và tự tạo một đề xuất `delivery_compensations` ở trạng thái `proposed` (loại `amount`, mệnh giá cố định `50.000 VNĐ`).
   - Trợ lý AI đọc `late_by_hours` do server tính, xác nhận đơn đã trễ so với thời hạn giao cam kết, **không hứa hẹn và không tự phát mã voucher**, đồng thời chuyển ca hỗ trợ sang nhân viên (`request_human_support`).

## Bước 2 (1:00 – 1:45) — Nhân viên giữ ca hoặc Quản lý duyệt bồi thường 50.000 VNĐ

1. Ở **Cửa sổ Nhân viên / Quản lý**:
   - Nếu dùng **Staff Desk**: bấm **Nhận ca** cho ca vừa mở của đơn đó.
   - Nếu dùng **Manager Console**: mở trực tiếp tab **Bồi thường giao trễ**.
2. Trong khối **Bồi thường giao trễ**, kiểm tra đề xuất trạng thái `proposed` với mệnh giá cố định `50.000 VNĐ` (không có ô sửa mệnh giá theo W6.1b-2-D7) và bấm **Duyệt 50.000đ**.
3. Kết quả: trong cùng một giao dịch DB, đề xuất chuyển sang `requested` và sự kiện `voucher.requested` được xếp vào `integration_outbox`.

## Bước 3 (1:45 – 3:00) — Operator xuất yêu cầu `voucher.requested` và phát mã từ sàn ảo

1. Trên **phiên SSM EC2**, xuất JSONL các yêu cầu đang ở trạng thái `requested` (nội dung chỉ gồm mã tham chiếu và mệnh giá, không chứa thông tin người nhận; chạy lặp nhiều lần an toàn):
   ```bash
   "${cweb[@]}" run --rm --no-deps --entrypoint python web \
     -m retailops database export-voucher-requests \
     --tenant "$TENANT_ID" \
     --source-system marketplace_sim > /tmp/voucher_requests.jsonl
   cat /tmp/voucher_requests.jsonl
   ```
2. Lưu dòng JSONL vừa in vào `/tmp/voucher_requests.jsonl` trên **máy trạm cục bộ**, rồi chạy sàn ảo để tiếp nhận yêu cầu và trích sự kiện `voucher.issued`:
   ```bash
   python -m marketplace_sim ingest-requests --data-dir /tmp/demo_sim --file /tmp/voucher_requests.jsonl
   python -m marketplace_sim export --data-dir /tmp/demo_sim --out /tmp/sim_all_events.jsonl
   grep '"voucher.issued"' /tmp/sim_all_events.jsonl > /tmp/voucher_issued.jsonl
   ```

## Bước 4 (3:00 – 4:15) — Operator nhập `voucher.issued` vào RetailOps trên EC2

1. Lưu nội dung `/tmp/voucher_issued.jsonl` lên `/tmp/voucher_issued.jsonl` trên **EC2**, rồi chạy lệnh nhập chuẩn:
   ```bash
   "${cweb[@]}" run --rm --no-deps \
     -v /tmp/voucher_issued.jsonl:/tmp/voucher_issued.jsonl:ro \
     --entrypoint python web \
     -m retailops database import-events \
     --tenant "$TENANT_ID" \
     --source-system marketplace_sim \
     --file /tmp/voucher_issued.jsonl \
     --rebase-clock now
   rm -f /tmp/voucher_requests.jsonl /tmp/voucher_issued.jsonl
   ```
2. Kết quả JSON của `import-events` báo sự kiện `voucher.issued` được ghi vào `vouchers`, nối `compensation_id` tương ứng và chuyển đề xuất sang trạng thái `issued`.

## Bước 5 (4:15 – 5:00) — Khách thấy thông báo chủ động và AI báo đúng mã voucher

1. Quay lại **Cửa sổ Khách hàng**:
   - Trong hội thoại xuất hiện ngay thông báo hệ thống chủ động `sys-notice-<shipment_id>-voucher_issued` hiển thị mã voucher `50.000 VNĐ` vừa phát (không chứa tên, số điện thoại hay địa chỉ người nhận).
   - Khách gửi thêm câu hỏi:
     > `Đơn này của tôi đã có mã voucher hỗ trợ giao trễ chưa?`
   - Trợ lý AI đọc bảng `vouchers` của đơn thuộc khách và trả lời **đúng mã `code` cùng mệnh giá `50.000 VNĐ`**.
2. Kiểm chứng tính lặp an toàn (tùy chọn): nếu chạy lại `export-voucher-requests` hoặc chạy lại `import-events` trên cùng tệp `voucher.issued`, hệ thống nhận diện sự kiện trùng theo `(source_system, event_id)`, giữ nguyên 1 dòng trong `vouchers` và không tạo thêm thông báo.
