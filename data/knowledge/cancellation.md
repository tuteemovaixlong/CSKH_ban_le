# Chính sách hủy đơn hàng

Tài liệu giả lập của RetailOps Demo, không phải cam kết thương mại thực tế.

## Đơn nào được hủy

Chỉ đơn **chờ xử lý (pending)**, tức shop chưa bàn giao cho đơn vị vận chuyển, mới được gửi yêu cầu hủy. Đơn **đang giao (shipping)** đã rời kho nên không hủy được nữa: khách có thể từ chối nhận khi shipper giao (xem chính sách đồng kiểm) hoặc nhận hàng rồi gửi yêu cầu trả hàng trong 7 ngày. Đơn đã giao, đã hủy hoặc đã chuyển hoàn không mở được yêu cầu hủy mới.

## Cách gửi yêu cầu hủy đơn

Trợ lý kiểm tra điều kiện hủy của đơn rồi mở biểu mẫu hủy trong khung chat. Khách chọn lý do hủy và bấm nút gửi trên biểu mẫu. Tin nhắn như "đồng ý", "xác nhận" hay "hủy ngay" trong khung chat không tự hủy đơn.

## Sau khi gửi yêu cầu hủy

Yêu cầu hủy chờ nhân viên cửa hàng duyệt. Trợ lý không tự duyệt và không hứa trước kết quả. Khi được duyệt, đơn chuyển sang trạng thái đã hủy (`cancelled`); chỉ coi là đã hủy khi dữ liệu đơn ghi nhận trạng thái này. Đơn đã thanh toán trước được hoàn tiền theo chính sách hoàn tiền; đơn thanh toán khi nhận hàng (COD) chưa trả tiền nên không phát sinh khoản hoàn.
