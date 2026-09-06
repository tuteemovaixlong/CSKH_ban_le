# RetailOps — hỗ trợ khách hàng bán lẻ

Baseline Qwen chạy trên Colab; API và giao diện chạy trên CPU/EC2 với dữ liệu giả lập.

- [Bộ chọn model 0.4.1: API hoặc Custom model trong giao diện](docs/MODEL_SELECTOR.md)
- [Agent 0.4: Qwen hội thoại, công cụ và hướng dẫn nâng cấp Colab/EC2](docs/AGENT_V04.md)
- [Notebook agent tự chứa](notebooks/colab_agent.ipynb)
- [Chạy giao diện và API, triển khai EC2, nối Colab](docs/BUSINESS_API.md)
- [Hội thoại 0.3: ngữ cảnh, danh mục và cách cập nhật EC2](docs/CONVERSATION_V03.md)
- [Kết quả baseline L4 đầu tiên](docs/BASELINE_L4_2026-09-06.md)
- [Hướng dẫn baseline](BASELINE_GUIDE.md)
- [Thiết lập CI/CD](deploy/SETUP.md)

Luồng nghiệp vụ: tra đơn → chọn lý do hủy → xem lại → xác nhận → lưu trạng thái
và nhật ký. Model chỉ gợi ý luồng; backend kiểm tra chủ sở hữu, trạng thái, phiên
bản đơn, thời hạn đề xuất và idempotency trước khi thực hiện.

API là demo riêng trên localhost/SSM, chưa phải dịch vụ công khai. Ở bản 0.4.1,
bạn chọn custom model (Colab/Ollama) hoặc API OpenRouter ngay trong giao diện.
Mọi câu chat gọi model đã chọn để đọc lịch sử, chọn công cụ đọc dữ liệu và sinh câu trả lời.
Backend kiểm soát quyền truy cập và mọi giao dịch. Các nút tra/hủy vẫn hoạt động
khi Colab tắt; chat báo lỗi kết nối. Xem chi tiết model/tool/latency ngay dưới từng
câu trả lời. Danh mục hiện còn ít dữ liệu, câu trả lời model vẫn cần đánh giá thật.

```bash
python -m unittest discover -s tests -v
```
