# Kịch bản demo trọn vòng bồi thường giao trễ và voucher (< 5 phút)

> Tài liệu hướng dẫn vận hành cho buổi trình diễn trên production sau khi hoàn tất rollout W6.1b-2 theo mục 7 của [`RUNBOOK.md`](RUNBOOK.md).
> Chỉ dùng dữ liệu giả lập của `marketplace_sim`. Bộ sinh sàn ảo không nằm trong image production và luôn chạy trên máy trạm cục bộ của operator.

## 0. Chuẩn bị trước giờ trình diễn (phải nạp dữ liệu trước ít nhất 5 ngày)

1. **Trên EC2 (qua phiên SSM quản trị — thực hiện ít nhất 5 ngày / 120 giờ trước buổi demo):**
   - Cửa hàng demo phải hoàn tất bước `reset-marketplace-demo`, `import-events ... data/demo_events/store_events.jsonl --rebase-clock now --no-notices`, và `seed-account-orders --tenant <tenant_id> --all-customers --no-notices` theo mục 7 của [`RUNBOOK.md`](RUNBOOK.md) **tối thiểu 5 ngày (120 giờ) trước buổi trình diễn**.
   - Lý do kỹ thuật: mỗi tài khoản khách thật được `seed-account-orders` cấp 3 đơn mẫu (`SIM-O-<TAG>-01`, `SIM-O-<TAG>-02`, `SIM-O-<TAG>-03`), trong đó đơn duy nhất ở trạng thái `shipping` là **đơn mẫu `-02` (`SIM-O-<TAG>-02`)** có `promised_delivery_by = lúc nạp + 72 giờ`. Trên production không có sàn giả lập chạy nền nên đơn `-02` giữ nguyên trạng thái `shipping` và chỉ vượt ngưỡng trễ hạn `48` giờ sau `72 + 48 = 120` giờ (~5 ngày).
   - Trước giờ trình diễn, mở phiên `sudo -i` tại `/opt/retailops`, khai báo mảng `cweb` của Docker Compose và biến `TENANT_ID="<tenant_id>"` (không in khóa hay biến mật ra màn hình), rồi **kiểm trước bằng vòng quét** để chắc chắn đơn `-02` của tài khoản khách demo đã có đề xuất ở trạng thái `"proposed"` (chưa duyệt):
     ```bash
     "${cweb[@]}" exec -T -e TENANT_ID="$TENANT_ID" web python -c "import json, os; from retailops.config import database_settings; from retailops.identity.postgres import PostgresSessions; s = PostgresSessions(database_settings(os.environ)[1]); st = s.business_store(os.environ['TENANT_ID']); scan = st.scan_late_delivery_compensations(); items = [x for x in st.list_manager_compensations(status='proposed')['items'] if str(x.get('external_order_id') or '').endswith('-02')]; print(json.dumps({'scan': scan, 'proposed_minus_02_count': len(items), 'external_order_ids': [x['external_order_id'] for x in items]}, ensure_ascii=False))"
     ```
     Kết quả phải liệt kê mã đơn `SIM-O-<TAG>-02` của tài khoản khách demo trong `external_order_ids` với trạng thái `proposed`.

   > **Ghi chú:** Sau mốc 5 ngày (120 giờ) kể từ lúc chạy `seed-account-orders`, **mọi tài khoản khách đã seed** đều có đề xuất bồi thường giao trễ (`proposed`, mệnh giá cố định `50.000 VNĐ`) cho đơn mẫu `-02` của mình; đây là hành vi đúng theo thiết kế.

2. **Trên máy trạm cục bộ của operator** (có bản checkout mã nguồn repo này): khởi tạo sẵn thư mục kho sàn ảo một lần:
   ```bash
   python -m marketplace_sim init --data-dir /tmp/demo_sim --seed 20261106 --merchant-id MERCHANT-SIM-001
   ```
3. **Trên trình duyệt:** mở sẵn 2 cửa sổ ẩn danh tách biệt:
   - **Cửa sổ Khách hàng:** đăng nhập bằng **tài khoản khách demo đã đăng nhập thật** và mở sẵn **đơn mẫu `-02` (`SIM-O-<TAG>-02`)** của chính tài khoản đó. *(Lưu ý: các đơn cửa hàng như `SIM-O-ST-013` trong `store_events.jsonl` thuộc khách giả lập của sàn `SIM-C-...`, không gắn với tài khoản đăng nhập nào nên không thể đăng nhập ở Cửa sổ Khách hàng; `SIM-O-ST-013` chỉ dùng để minh họa tra cứu/duyệt từ phía Staff Desk hoặc Manager Console).*
   - **Cửa sổ Nhân viên / Quản lý:** đăng nhập Staff Desk hoặc Manager Console của cùng cửa hàng.

---

## Bước 1 (0:00 – 1:00) — Khách hỏi về đơn mẫu `-02` giao trễ; AI xác nhận trễ và chuyển nhân viên

1. Ở **Cửa sổ Khách hàng**, chọn **đơn mẫu `-02` (`SIM-O-<TAG>-02`)** của tài khoản demo đang đăng nhập và gửi tin nhắn:
   > `Đơn hàng này của tôi đã quá ngày giao dự kiến, shop kiểm tra giúp tôi với.`
2. Kết quả quan sát trên màn hình:
   - Vòng quét nền của server đã ghi thông báo hệ thống chủ động `sys-notice-<shipment_id>-late_delivery` trong hội thoại của khách và tự tạo đề xuất `delivery_compensations` ở trạng thái `proposed` (loại `amount`, mệnh giá cố định `50.000 VNĐ`) cho đơn `-02`.
   - Trợ lý AI đọc `late_by_hours` do server tính, xác nhận đơn `-02` đã trễ so với thời hạn giao cam kết, **không hứa hẹn và không tự phát mã voucher**, đồng thời chuyển ca hỗ trợ sang nhân viên (`request_human_support`).

## Bước 2 (1:00 – 1:45) — Nhân viên giữ ca hoặc Quản lý duyệt bồi thường 50.000 VNĐ

1. Ở **Cửa sổ Nhân viên / Quản lý**:
   - Nếu dùng **Staff Desk**: bấm **Nhận ca** cho ca vừa mở của đơn `-02` (`SIM-O-<TAG>-02`).
   - Nếu dùng **Manager Console**: mở trực tiếp tab **Bồi thường giao trễ** *(tại đây cũng có thể chỉ thêm các đề xuất của khách sàn giả lập như `SIM-O-ST-013` để minh họa góc nhìn quản trị toàn cửa hàng, nhưng bấm duyệt trên đơn `-02` của tài khoản khách demo để khép trọn vòng phía Cửa sổ Khách hàng)*.
2. Trong khối **Bồi thường giao trễ**, kiểm tra đề xuất trạng thái `proposed` của đơn `-02` với mệnh giá cố định `50.000 VNĐ` (không có ô sửa mệnh giá theo W6.1b-2-D7) và bấm **Duyệt 50.000đ**.
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
