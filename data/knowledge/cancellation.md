# Chính sách hủy đơn của RetailOps Demo

Tài liệu này chỉ áp dụng cho dữ liệu giả lập trong RetailOps Demo.

Đơn ở trạng thái **chờ xử lý (pending)** có thể được khách hàng gửi yêu cầu hủy. Đơn đã giao hoặc đã hủy không đủ điều kiện mở yêu cầu hủy mới.

Chatbot chỉ được kiểm tra điều kiện và mở bước chọn lý do. Tin nhắn như “đồng ý”, “xác nhận” hoặc “hủy ngay” trong cửa sổ chat không tự thay đổi đơn hàng.

Việc hủy chỉ hoàn tất sau khi người dùng chọn lý do và bấm nút xác nhận riêng. Trước khi ghi dữ liệu, backend kiểm tra lại chủ đơn, quyền hiện tại, trạng thái đơn, phiên bản đơn và thời hạn của yêu cầu. Kết quả thành công phải được xác nhận bằng trạng thái `cancelled` trên bản ghi đơn.
