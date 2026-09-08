# RetailOps — web hỗ trợ khách hàng bán lẻ trên EC2

**Quy trình sử dụng hiện tại: mở web HTTPS trên EC2. Không cần chạy localhost.**
VS Code dùng để sửa code và Git; GitHub Actions chạy CI/CD; EC2 chạy web/API/PostgreSQL; Colab chỉ phục vụ model khi chọn Custom. Dự án chỉ dùng dữ liệu giả lập.

## Bắt đầu ở đây

[Quy trình EC2: mở web, phát triển, test và dọn phần dư](docs/EC2_WEB_WORKFLOW.md).

Địa chỉ được xác minh ngày 2026-09-08: `https://retailops.54-221-116-13.sslip.io`.
Đây là snapshot, không phải domain cố định: sau stop/start EC2 phải đối chiếu IP và hai biến `RETAILOPS_PUBLIC_HOST` / `RETAILOPS_PUBLIC_ORIGIN` theo runbook.

Mở web trong trình duyệt và dùng tài khoản demo đã cấp. Không chạy `python retailops_api.py`, không tạo `RETAILOPS_DEMO_TOKEN` trên Windows và không dùng token local để đăng nhập EC2. Public web vẫn giữ credential/cookie, tenant, customer và quyền truy cập. PR #26 auto-login localhost đã đóng không merge.

Luồng nghiệp vụ: tra đơn → chọn lý do hủy → xem lại → xác nhận → lưu trạng thái và nhật ký. Model chỉ hỗ trợ hội thoại và công cụ đọc; backend kiểm tra quyền, chủ sở hữu, trạng thái, phiên bản, thời hạn và idempotency trước giao dịch.

## Kiến trúc và tài liệu hiện hành

| Phần | Tài liệu |
| --- | --- |
| Cấu trúc package, cấu hình và ranh giới module | [SYSTEM_FOUNDATION](docs/SYSTEM_FOUNDATION.md) |
| HTTPS, Caddy và cookie phiên | [PUBLIC_HTTPS](docs/PUBLIC_HTTPS.md) |
| Tài khoản, membership và thu hồi credential | [PERSISTENT_IDENTITY](docs/PERSISTENT_IDENTITY.md) |
| PostgreSQL và chuyển dữ liệu SQLite | [POSTGRESQL](docs/POSTGRESQL.md) |
| LangGraph, checkpoint và xác nhận có thể khôi phục | [LANGGRAPH](docs/LANGGRAPH.md) |
| RAG, nguồn trích dẫn và protocol Colab v2 | [RAG_CHAT](docs/RAG_CHAT.md) |
| Chiến lược kiểm thử | [AUTOMATED_TEST_STRATEGY](docs/AUTOMATED_TEST_STRATEGY.md) |
| Evaluation dataset và scoreboard | [evals](evals/README.md) |
| Thiết lập CI/CD | [deploy/SETUP](deploy/SETUP.md) |

RAG hiện dùng PostgreSQL/pgvector schema v3 và feature-hash baseline. Kiểm tra provenance của trích dẫn không đồng nghĩa đã chấm semantic faithfulness. Evaluation Runner & Dashboard là bước phát triển tiếp theo, chưa được coi là hoàn thành chỉ nhờ dataset validator hoặc smoke PASS.

## Phát triển và kiểm thử

Sửa code trên nhánh tính năng, bổ sung regression test, tạo PR, đợi CI xanh rồi merge. Workflow deployment trên main build/publish ECR, triển khai qua SSM và kiểm tra live smoke. Không copy source thủ công lên EC2.

CI giữ unit, HTTP, JavaScript, PostgreSQL/pgvector và Docker tests. Các module private/localhost còn trong source vì test và tương thích; chúng không còn là điều kiện để sử dụng web. Không xóa module hay database chỉ vì tên có chữ `api`, `local` hoặc `artifacts`.

**Chạy trên EC2 qua Session Manager, không chạy các lệnh sau trên PowerShell Windows:**

```bash
sudo python3 /opt/retailops/live-e2e.py --mode smoke
```

Full test có model call, dữ liệu test riêng và restart web, chỉ chạy trong phiên kiểm thử có chủ đích:

```bash
sudo python3 /opt/retailops/live-e2e.py --mode full
```

Các report lưu tại `/opt/retailops/e2e-reports/`. Full runner hiện kiểm tra HTTP qua Caddy, không phải Playwright/browser automation. Kết quả PASS không phải accuracy của model trên toàn bộ evaluation dataset.

## Nguồn model

Trong giao diện chọn Custom model (Colab/Ollama) hoặc API đã được cấu hình. EC2/web và thao tác trực tiếp không cần Colab; chat Custom cần model và endpoint đang hoạt động. Không tự chuyển provider khi một model lỗi. Không đưa token, API key hoặc URL chứa credential vào chat/Git.

[Notebook agent tự chứa](notebooks/colab_agent.ipynb) · [Bộ chọn model](docs/MODEL_SELECTOR.md) · [Hợp đồng agent](docs/AGENT_V04.md).

## Tài liệu lịch sử — không phải hướng dẫn khởi động hằng ngày

Các tài liệu được giữ làm bằng chứng quá trình phát triển, không dùng để quay lại quy trình copy token localhost:

- [Business API 0.2/0.3](docs/BUSINESS_API.md).
- [Hội thoại 0.3](docs/CONVERSATION_V03.md).
- [Baseline L4 đầu tiên](docs/BASELINE_L4_2026-09-06.md) và [baseline guide](BASELINE_GUIDE.md).
