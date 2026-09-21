# BÁO CÁO TIẾN ĐỘ & TRẠNG THÁI HỆ THỐNG RETAILOPS 2026

> **Trạng thái:** ACTIVE OPERATIONAL STATUS & EVIDENCE REPORT  
> **Snapshot ngày kiểm tra:** 2026-09-21 (GMT+7)  
> **Git HEAD:** `0c9a7d4abfb716ee3ed6a6d474f146ae293ec577` (Local == Origin/Main, Working tree clean)  
> **Application snapshot đã xác minh:** `d3ca3a6ff6fa106af973d4c44c6ee955bce20f13` (Workflow Verify main CI #3: 340 Python tests OK)  
> **Deploy EC2 gần nhất:** #141 tại snapshot `0b7256c` (Không có thay đổi runtime code giữa `0b7256c` và HEAD `0c9a7d4`)  
> **EC2 Host:** `retailops-dev` / `i-0fd116d8927d0e412` / **t3.large** (2 vCPU, 8 GiB RAM, 50 GiB EBS, ~43 GiB free)  
> **Public IPv4 hiện tại:** `98.84.139.124` (dynamic; không dùng Elastic IP)  
> **Web khách hàng:** https://retailops.98-84-139-124.sslip.io  
> **Admin Console:** https://admin-retailops.98-84-139-124.sslip.io  
> **Runtime containers:** PostgreSQL + Web + Admin + Caddy đang hoạt động (Healthy); SSM Agent Snap active  
> **Báo cáo sự cố chi tiết:** [INCIDENT_RECOVERY_2026-09-21.md](INCIDENT_RECOVERY_2026-09-21.md)

---

## 1. BẢNG ĐỐI CHIẾU TIẾN ĐỘ 6 MODULE THEO KHUNG MINH CHỨNG (EVIDENCE RUBRIC)

Theo chuẩn phân cấp minh chứng của [`RELEASE_MANIFEST.md`](RELEASE_MANIFEST.md) (`L1`: Automated tests; `L2`: Docker build/publish; `L3`: Live deployment; `L4`: Real-model E2E artifacts):

| Module | Tên Module | Mức Triển Khai | Cấp Minh Chứng (Evidence) | Tồn Đọng Kỹ Thuật Chính (Gaps) |
| :--- | :--- | :---: | :---: | :--- |
| **Module 1** | **Hệ Thống Lõi TMĐT, 6 SOPs & MCP Server** | **PARTIAL** | **L3** *(PostgreSQL, Web, Staff Desk, Caddy healthy)* | Catalog vẫn lưu file JSON / in-memory fallback; `check_inventory` tra cứu `stock_map` tĩnh; Nút SOP 1..5 phía Store Manager mới dừng ở mô phỏng. |
| **Module 2** | **Đo Baseline Benchmark Cơ Sở & Ops Console** | **PARTIAL** | **L1/L3 hỗn hợp** *(250 ca offline đạt 100% Routing)* | Importer Ops Console vẫn chia 3 ước tính token (`len // 3`) và gán cost $0.0; Tên chỉ số TTFT chưa đổi thành E2E Request Latency. |
| **Module 3** | **Webhook Facebook Messenger (Omnichannel)** | **PLANNED** | **Design-only** *([PLAN_OMNICHANNEL_INTEGRATION.md](PLAN_OMNICHANNEL_INTEGRATION.md))* | Chưa có mã nguồn webhook endpoint, chưa tích hợp Meta App. |
| **Module 4** | **Cổng Quét Mã QR Demo Live** | **PARTIAL** | **L3** *(HTTPS sslip.io, Web mobile responsive)* | Đã có hạ tầng web di động sẵn sàng cho demo; Chưa có module sinh mã QR động / thẻ QR demo. |
| **Module 5** | **Self-Hosted vLLM & Serving Model Agentic** | **IMPLEMENTED / PARTIAL** | **Runtime-dependent** *(Colab L4 vLLM + ngrok)* | Tunnel ngrok và serving phụ thuộc runtime phiên làm việc; Chưa đóng gói serving cục bộ thường trực trên EC2. |
| **Module 6** | **Đo Lường Evaluation Đối Chứng Luận Văn** | **PARTIAL** | **L1 offline (250 ca) + Runtime note EC2** | Smoke 10/10 và Batch 01 19/25 là ghi nhận runtime EC2 (chưa commit artifact vào Git); Full Live Benchmark 250 ca trên EC2 chưa chạy xong. |

---

## 2. NHỮNG CÔNG VIỆC ĐÃ HOÀN THÀNH (COMPLETED EVIDENCE)

### 2.1. Hợp nhất Master Benchmark & Chuẩn hóa Hợp đồng Dữ liệu
- **Gom 10 Batch thành Master Dataset**: Tổng hợp toàn bộ 250 kịch bản từ `B01.jsonl` đến `B10.jsonl` vào [`evals/scenarios/benchmark_250.jsonl`](../evals/scenarios/benchmark_250.jsonl) (150 ca `dev`, 100 ca `held_out`).
- **Xác thực Schema 9 trường nghiêm ngặt**: Vượt qua toàn bộ hợp đồng của [`scripts/check_eval_dataset.py`](../scripts/check_eval_dataset.py) và `validate_retailops_jsonl.py`.
- **Đạt điểm tuyệt đối Offline Benchmark**: Đạt **250 / 250 PASS (100.0%)** trên bộ định tuyến giám sát (`run_benchmark_eval.py`), độ trễ p50 = 0.10 ms.

### 2.2. Khắc phục Toàn diện Phản hồi Kiểm toán từ GPT-6 Astra Pro
- **Khắc phục Whitelist Tool Khiếu Nại (`dispute_agent.py`)**:
  - Loại bỏ hoàn toàn phương thức nội bộ `read_order`, chuyển sang công cụ đã đăng ký chuẩn `get_order`.
  - Loại bỏ số lượng tồn kho fix cứng (`stock_qty = 15`), chuyển sang đọc dữ liệu động từ DB hoặc trả về 0 an toàn.
- **Bổ sung Nhận diện Tiếng lóng TMĐT Việt Nam (`supervisor.py`)**:
  - Mở rộng regex nhận diện các từ lóng giao vận: *"tài xế", "bom hàng", "giao thất bại", "kẹt kho", "Củ Chi SOC", "Bắc Ninh Mega SOC", "SPX", "GHN", "GHTK"*... không bị định tuyến nhầm sang chế độ tổng quát (`general`).
  - Xử lý triệt để va chạm chuỗi con bằng regex lookbehind: `(?<!điều )\bkiện\b` (tránh hiểu nhầm *"điều kiện"* là khiếu nại *"kiện"*).
- **Vượt qua Chặn Cảnh báo Ngrok (`retailops_providers.py`)**:
  - Bổ sung header `'ngrok-skip-browser-warning': 'true'` vào toàn bộ các HTTP request gửi tới endpoint ngrok, khắc phục dứt điểm lỗi trả về HTML `ERR_NGROK_6024`.

### 2.3. Triển khai & Khởi động EC2 Thành công
- **Cập nhật IP mới & Restart Containers**:
  - Chạy `scripts/update_ec2.py` trên EC2 với IP mới: `98.84.139.124`.
  - Cả 4 container Docker (`postgres`, `admin`, `web`, `caddy`) đều chạy ổn định và đạt trạng thái Healthy.
  - Endpoint `healthz` trả về HTTP 200: `{"status": "ok", "scope": "synthetic-demo", "storage_backend": "postgresql", "agent_protocol": "retailops-agent-v2"}`.

### 2.4. Thực thi Đo Đạc Live Benchmark Thực tế (Live HTTP Evaluation)
> *Ghi chú quan trọng:* Kết quả đợt chạy live dưới đây là **ghi nhận runtime trực tiếp trên EC2** trong phiên kiểm thử. Các file artifact sinh ra không được commit vào Git để bảo đảm working tree sạch sau incident recovery; báo cáo reproducible đã commit trong repo hiện là [`evals/reports/live_benchmark_report_20260918_042301.md`](../evals/reports/live_benchmark_report_20260918_042301.md) (240 ca).
- **Giai đoạn 1 (Smoke Test - 10 ca đầu)**:
  - **Tỷ lệ thành công**: **10 / 10 PASS (100.0%)**.
  - **Độ trễ**: p50 = 24.28s, p95 = 31.39s.
  - Phản hồi chuẩn mực: Khi khách không có mã đơn thì hỏi mã đơn; khi có mã đơn thì gọi tool `get_order`, `track_shipment` để trả về đúng trạng thái thực từ PostgreSQL.
- **Giai đoạn 2 (Batch 01 - 25 ca)**:
  - **Tỷ lệ thành công**: **19 / 25 PASS (76.0%)**.
  - **Độ trễ**: p50 = **20.75s**, p95 = **31.07s**.
  - Báo cáo chi tiết runtime trên EC2:
    - `/home/ssm-user/CSKH_ban_le/evals/reports/live_benchmark_report_20260920_091714.json`
    - `/home/ssm-user/CSKH_ban_le/evals/reports/live_benchmark_report_20260920_091714.md`
    - `/home/ssm-user/CSKH_ban_le/evals/reports/live_benchmark_report_latest.json`

### 2.5. Hoàn thiện CI/CD & Xác Minh Toàn Tuyến
- **CI/CD Xanh 100%**: Snapshot application `d3ca3a6` đã được workflow **Verify main CI #3** kiểm thử vượt qua toàn bộ **340 Python tests OK**, bảo đảm các hợp đồng `PUBLIC_UI_ASSETS_OK`, `PUBLIC_HTTPS_PROXY_COOKIE_FLOW_OK`, `PERSISTENT_HTTPS_ACCOUNT_FLOW_OK`, `POSTGRES_HTTPS_IMPORT_RESTORE_OK`.
- **Thiết kế Đối kháng DeepSeek**: Hoàn thành tài liệu kiến trúc [`PLAN_DEEPSEEK_EVAL_FRAMEWORK.md`](PLAN_DEEPSEEK_EVAL_FRAMEWORK.md).

---

## 3. NHỮNG CÔNG VIỆC CHƯA LÀM ĐƯỢC & TỒN ĐỌNG (PENDING & NEXT STEPS)

### 3.1. Phân tích Chi tiết 6 Ca FAIL trong Batch 01 (19/25 PASS)
- **Hiện tượng**: Trong 25 ca chạy thật của Batch 01, có 6 ca bị đánh giá `FAIL`.
- **Nhiệm vụ phiên tới**:
  1. Chạy lệnh phân tích trích xuất 6 ca lỗi trên EC2:
     ```bash
     python3 -c "import json; r=json.load(open('evals/reports/live_benchmark_report_latest.json')); print('\n'.join(f'🔴 [{c[\"id\"]}] HTTP {c.get(\"status\")} | Lỗi: {c.get(\"error\")} | Tools: {c.get(\"tools_called\")} | Trả lời: {str(c.get(\"response\"))[:90]}' for c in r['cases'] if not c.get('passed')))"
     ```
  2. Xác định nguyên nhân: Do timeout ngrok (>120s), do gọi nhầm tool cấm (`prepare_cancellation`), hay do model phản hồi rỗng để có biện pháp tinh chỉnh prompt/routing.

### 3.2. Lọc Bỏ Rò Rỉ Token Suy Luận (`<|channel>thought...`)
- **Hiện tượng**: Trong một số ca (như `ro_s1_004`, `ro_s1_010`), mô hình Gemma-4 sinh tag suy luận nội bộ `<|channel>thought\n...` xuất hiện trong nội dung câu trả lời cho người dùng.
- **Nhiệm vụ phiên tới**: Bổ sung cơ chế làm sạch chuỗi (regex stripper) trong `retailops_providers.py` hoặc `agent_protocol.py` để bóc tách phần `thought` sang thuộc tính `reasoning`, giữ câu trả lời tự nhiên, thân thiện cho khách hàng.

### 3.3. Thực thi Chạy Toàn Bộ 250 Ca Kiểm Thử (Full Master Benchmark)
- **Kế hoạch**: Sau khi nắm rõ nguyên nhân 6 ca lỗi của Batch 01, chạy toàn bộ 250 kịch bản bằng chế độ chạy ngầm `nohup` trên EC2:
  ```bash
  nohup python3 scripts/run_live_benchmark_http.py > live_bench_full.log 2>&1 &
  ```
- **Mục tiêu**: Thu thập đầy đủ số liệu thực nghiệm p50, p95, accuracy cho toàn bộ 6 SOPs để lập bảng đối chứng đưa vào Chương 4 Luận văn Thạc sĩ.

### 3.4. Kế hoạch Kiểm thử Đối kháng với DeepSeek API
- Giữ ở mức thiết kế trong `docs/PLAN_DEEPSEEK_EVAL_FRAMEWORK.md`. Khi cần triển khai, chỉ cần cấu hình API Key và chạy so sánh trực tiếp song song giữa Gemma-4-12B (Self-hosted) và DeepSeek (Cloud API).

---

## 4. HƯỚNG DẪN LOAD LẠI PHIÊN LÀM VIỆC TIẾP THEO

Khi bạn quay trở lại, chỉ cần copy câu nhắc sau để tiếp tục ngay lập tức:

```text
Tiếp tục phiên làm việc: Hãy đọc file docs/CURRENT_PROJECT_STATUS.md để nắm lại toàn bộ tiến độ. 
Chúng ta sẽ bắt đầu bằng việc:
1. Phân tích chi tiết 6 ca FAIL trong Batch 01 (live_benchmark_report_latest.json).
2. Xử lý triệt để việc rò rỉ token <|channel>thought của Gemma-4.
3. Chạy Full Benchmark 250 ca trên EC2 để thu thập số liệu hoàn chỉnh cho Chương 4 Luận văn.
```
