# RetailOps — hỗ trợ khách hàng bán lẻ

Baseline Qwen chạy trên Colab; API và giao diện chạy trên CPU/EC2 với dữ liệu giả lập.

- [Chạy giao diện và API, triển khai EC2, nối Colab](docs/BUSINESS_API.md)
- [Kết quả baseline L4 đầu tiên](docs/BASELINE_L4_2026-09-06.md)
- [Hướng dẫn baseline](BASELINE_GUIDE.md)
- [Thiết lập CI/CD](deploy/SETUP.md)

Luồng nghiệp vụ: tra đơn → chọn lý do hủy → xem lại → xác nhận → lưu trạng thái
và nhật ký. Model chỉ gợi ý luồng; backend kiểm tra chủ sở hữu, trạng thái, phiên
bản đơn, thời hạn đề xuất và idempotency trước khi thực hiện.

API là demo riêng trên localhost/SSM, chưa phải dịch vụ công khai. Khi Colab tắt,
chat báo không kết nối được model; các nút thao tác nghiệp vụ vẫn hoạt động.

```bash
python -m unittest discover -s tests -v
```
