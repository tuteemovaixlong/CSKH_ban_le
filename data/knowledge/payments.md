# Thanh toán trong dữ liệu mẫu

RetailOps Demo dùng dữ liệu thanh toán giả lập để kiểm thử luồng hỗ trợ. Chính sách mẫu có thể mô tả thanh toán bằng thẻ hoặc thanh toán khi nhận hàng, nhưng phương thức của một đơn cụ thể chỉ được coi là đã biết khi bản ghi đơn hoặc công cụ backend trả về giá trị đó.

Nếu trường thanh toán của đơn là `null` hoặc không tồn tại, trợ lý phải trả lời rằng hệ thống hiện chưa có thông tin phương thức thanh toán của đơn đó.
