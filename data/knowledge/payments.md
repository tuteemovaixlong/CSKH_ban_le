# Phương thức thanh toán

Tài liệu giả lập của RetailOps Demo, không phải cam kết thương mại thực tế.

## Các phương thức thanh toán

Khách có thể thanh toán khi nhận hàng (COD), chuyển khoản ngân hàng, ví điện tử hoặc thẻ. Tiền do cổng thanh toán được cấp phép xử lý; shop và trợ lý không thu tiền trực tiếp và không bao giờ hỏi số thẻ, số tài khoản, mật khẩu hay mã OTP qua chat.

## Thanh toán của một đơn cụ thể

Phương thức và trạng thái thanh toán của một đơn lấy từ dữ liệu của đơn đó. Trường thanh toán trống thì trợ lý nói hệ thống chưa có thông tin thanh toán của đơn, không đoán.

## Thanh toán bị lỗi

Giao dịch trả trước bị lỗi thì đơn chưa được xác nhận thanh toán; khách thanh toán lại theo hướng dẫn của sàn. Trợ lý không tạo link thanh toán và không xác nhận đã nhận tiền khi dữ liệu đơn chưa ghi nhận.
