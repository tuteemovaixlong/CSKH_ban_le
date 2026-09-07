## Khung hệ thống — 0.10

[Kiến trúc module, cách chạy và phần khung còn lại](docs/SYSTEM_FOUNDATION.md).
Lõi nghiệp vụ, xác thực phiên, HTTP và cấu hình đã được tách trong package `retailops/`.
Entrypoint cũ vẫn tương thích; có thêm `python -m retailops check-config --interface public`
để kiểm tra cấu hình mà không in secret, tạo database hay gọi model.
Có thêm [tài khoản cá nhân và dữ liệu theo cửa hàng](docs/PERSISTENT_IDENTITY.md) ở chế độ `persistent-demo`: logout không xóa đơn, quyền `customer`/`viewer`, migration SQLite và công cụ cấp/thu hồi mã.
Có thêm [backend PostgreSQL và chuyển dữ liệu SQLite](docs/POSTGRESQL.md), dùng chung luật nghiệp vụ và không tự chuyển database đang chạy.
Có thêm [RAG/pgvector với nguồn trích dẫn và bộ chuyển PostgreSQL](docs/KNOWLEDGE.md). RAG bật riêng sau khi chuẩn bị embedding và publish tài liệu.
Có thêm [LangGraph, checkpoint và xác nhận có thể khôi phục](docs/LANGGRAPH.md) trên SQLite/PostgreSQL.
Mặc định vẫn là `synthetic-demo`; cả hai chế độ chỉ dành cho dữ liệu giả lập.

## Web HTTPS trên EC2

[Xem hướng dẫn triển khai HTTPS](docs/PUBLIC_HTTPS.md). Bản mới phục vụ web bằng Caddy + Waitress, có cookie và bộ đơn riêng cho mỗi khách. API được chọn mặc định khi đã cấu hình; không cần giữ laptop/SSM hoặc Colab khi dùng API. Chứng chỉ và kết nối API thật cần xác nhận trên EC2.

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

Web có thể chạy HTTPS công khai trên EC2; API riêng vẫn dùng localhost/SSM.
bạn chọn custom model (Colab/Ollama) hoặc API OpenRouter ngay trong giao diện.
Mọi câu chat gọi model đã chọn để đọc lịch sử, chọn công cụ đọc dữ liệu và sinh câu trả lời.
Backend kiểm soát quyền truy cập và mọi giao dịch. Các nút tra/hủy vẫn hoạt động
khi Colab tắt; chat báo lỗi kết nối. Xem chi tiết model/tool/latency ngay dưới từng
câu trả lời. Danh mục hiện còn ít dữ liệu, câu trả lời model vẫn cần đánh giá thật.

```bash
python -m unittest discover -s tests -v
```
