# RetailOps — hỗ trợ khách hàng bán lẻ

Baseline Qwen chạy trên Colab; API và giao diện chạy trên CPU/EC2 với dữ liệu giả lập.

- [Chạy giao diện và API, triển khai EC2, nối Colab](docs/BUSINESS_API.md)
- [Hội thoại 0.3: ngữ cảnh, danh mục và cách cập nhật EC2](docs/CONVERSATION_V03.md)
- [Kết quả baseline L4 đầu tiên](docs/BASELINE_L4_2026-09-06.md)
- [Hướng dẫn baseline](BASELINE_GUIDE.md)
- [Thiết lập CI/CD](deploy/SETUP.md)

Luồng nghiệp vụ: tra đơn → chọn lý do hủy → xem lại → xác nhận → lưu trạng thái
và nhật ký. Model chỉ gợi ý luồng; backend kiểm tra chủ sở hữu, trạng thái, phiên
bản đơn, thời hạn đề xuất và idempotency trước khi thực hiện.

API là demo riêng trên localhost/SSM, chưa phải dịch vụ công khai. Lời chào,
tra cứu và danh mục được xử lý bằng quy tắc cùng dữ liệu nguồn, vẫn hoạt động
khi Colab tắt. Các lượt cần model nhận diện sẽ báo lỗi nếu model không kết nối.
Ngữ cảnh phiên chỉ nhớ đơn/sản phẩm đang trao đổi; chưa phải chatbot tổng quát.

```bash
python -m unittest discover -s tests -v
```
