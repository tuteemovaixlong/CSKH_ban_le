# BÁO CÁO TIẾN ĐỘ & TRẠNG THÁI HỆ THỐNG RETAILOPS 2026

> **Trạng thái:** ACTIVE OPERATIONAL STATUS & EVIDENCE REPORT  
> **Audit basis / Documentation baseline reviewed:** `b93eb5a`  
> **Application snapshot đối chiếu:** Nhánh `main` tại commit `d7ce461` (PR #33 merged `a6ec080`, hotfix compatibility `85834d6` & `d7ce461`)  
> **Kiểm thử & CI:** 353 unit tests PASS (0 failures), 4/4 cổng hợp đồng PASS, GitHub Actions CI (Run #236) & Ops Console (Run #143) **100% SUCCESS**  
> **EC2 Host:** `retailops-dev` / `i-0fd116d8927d0e412` / **t3.large** (Hiện đang **STOPPED** qua đêm để tối ưu chi phí cloud)  
> **Deploy status:** Container image build & test **PASS 100%**; sẵn sàng kích hoạt lại khi bật EC2  
> **Lộ trình kỹ thuật tổng thể:** Xem chi tiết tại [PLAN_ROADMAP_INDEX.md](PLAN_ROADMAP_INDEX.md)  
> **Báo cáo sự cố chi tiết:** [INCIDENT_RECOVERY_2026-09-21.md](INCIDENT_RECOVERY_2026-09-21.md)

---

## 1. BẢNG ĐỐI CHIẾU TIẾN ĐỘ 6 MODULE THEO KHUNG MINH CHỨNG (EVIDENCE RUBRIC)

Theo chuẩn phân cấp minh chứng của [`RELEASE_MANIFEST.md`](RELEASE_MANIFEST.md) (`L1`: Automated tests; `L2`: Docker build/publish; `L3`: Live deployment; `L4`: Real-model E2E artifacts):

| Module | Tên Module | Mức Triển Khai | Cấp Minh Chứng (Evidence) | Tồn Đọng Kỹ Thuật Chính (Gaps) |
| :--- | :--- | :--- | :--- | :--- |
| **Module 1** | **Hệ Thống Lõi TMĐT, 6 SOPs & MCP Server** | **IMPLEMENTED** | **L1/L3 hỗn hợp** *(353 tests PASS, Staff Desk & Manager SSOT healthy)* | Đã hoàn tất Phase 1.1 (Truthful UX) và Phase 1.2 (Store Manager Persistence & Shared Catalog SSOT: bảng `products`, `product_variants` vào PostgreSQL v4 / SQLite v3, đồng bộ `check_inventory`, `dispute_agent`, audit events toàn shop, cùng 8 điểm khắc phục kiểm toán kỹ thuật từ GPT 6 Astra High). |
| **Module 2** | **Đo Baseline Benchmark Cơ Sở & Ops Console** | **PARTIAL** | **L1/L3 hỗn hợp** *(250 ca offline 100% Routing)* | Importer Ops Console vẫn chia 3 ước tính token (`len // 3`) và gán cost $0.0; Tên chỉ số TTFT chưa đổi thành E2E Request Latency. Khắc phục tại `PLAN_FIX_UI_03` (Phase 1 Telemetry). |
| **Module 3** | **Webhook Facebook Messenger (Omnichannel)** | **PLANNED** | **Design-only** *([PLAN_OMNICHANNEL_INTEGRATION.md](PLAN_OMNICHANNEL_INTEGRATION.md))* | Chưa có mã nguồn webhook endpoint, chưa tích hợp Meta App (xếp vào Phase 5 Demo). |
| **Module 4** | **Cổng Quét Mã QR Demo Live** | **PARTIAL** | **L3** *(HTTPS sslip.io, Web mobile responsive)* | Đã có hạ tầng web di động sẵn sàng cho demo; Chưa có module sinh mã QR động / thẻ QR demo (xếp vào Phase 5 Demo). |
| **Module 5** | **Self-Hosted vLLM & Serving Model Agentic** | **IMPLEMENTED / PARTIAL** | **Runtime-dependent** *(Colab L4 vLLM + ngrok)* | Tunnel ngrok và serving phụ thuộc runtime phiên làm việc; Cần giải quyết điểm nghẽn single lock qua `PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md` (Phase 3). |
| **Module 6** | **Đo Lường Evaluation Đối Chứng Luận Văn** | **PARTIAL** | **L1 offline (250 ca) + Runtime note EC2** | Offline Benchmark 250 ca đạt 100.0%; Full Live Benchmark 250 ca trên EC2 và đối chứng DeepSeek sẽ thực thi tại Phase 4 Scientific Evaluation. |

---

## 2. NHỮNG CÔNG VIỆC ĐÃ HOÀN THÀNH (COMPLETED EVIDENCE)

### 2.1. Hợp Nhất Master Benchmark & Chuẩn Hóa Hợp Đồng Dữ Liệu
- **Master Dataset 250 kịch bản**: Tổng hợp toàn bộ 250 kịch bản từ `B01.jsonl` đến `B10.jsonl` vào [`evals/scenarios/benchmark_250.jsonl`](../evals/scenarios/benchmark_250.jsonl) (150 ca `dev`, 100 ca `held_out`).
- **Xác thực Schema 9 trường nghiêm ngặt**: Vượt qua toàn bộ hợp đồng của [`scripts/check_eval_dataset.py`](../scripts/check_eval_dataset.py) và `validate_retailops_jsonl.py`.
- **Đạt điểm tuyệt đối Offline Benchmark**: Đạt **250 / 250 PASS (100.0%)** trên bộ định tuyến giám sát (`run_benchmark_eval.py`), độ trễ p50 = 0.10 ms.

### 2.2. Khắc Phục Toàn Diện Phản Hồi Kiểm Toán Lịch Sử (Audit Remediation)
- **State Machine Guard cho Đơn Hàng**: Chặn các bước chuyển trạng thái phi lý (`cancelled -> pending`, `delivered -> pending`) tại `retailops/http/routes.py:249`, kiểm thử tại `tests/test_manager_crud.py`.
- **Băm Base64 Ảnh Vào Digest [F11]**: Băm nội dung ảnh vào token digest trong `retailops/business/application.py:111`, chống replay sai lệch khi gửi ảnh khác nhau cùng tên.
- **Tự Động Ghi Nhận Ticket Handoff [F06]**: Khi kích hoạt `request_human_support`, hệ thống tự động ghi nhận bản ghi escalation vào `conversation_feedback`.
- **An Toàn Cache [F04]**: Duy trì cập nhật `bound.versions` và `bound.knowledge.sources` khi cache-hit; loại bỏ cache cho các công cụ mutation.
- **Tính Toán KPI Thực Tế Từ DB [P0.3 & F07]**: Endpoint `/api/manager/kpis` truy vấn trực tiếp từ bảng `orders`, `conversations` và `conversation_feedback`, loại bỏ số liệu hard-code tĩnh.

### 2.3. Khôi Phục Lịch Sử Chat & Hội Thoại Tiếp Diễn (Chat History Resume)
- Bổ sung `GET /api/conversations`, client tự động resume phiên gần nhất khi F5, khôi phục toàn bộ bong bóng chat, nâng TTL lên 7 ngày và kiểm thử toàn diện tại `tests/test_conversation_resume.py` (4/4 PASS).

### 2.4. Độc Lập Giao Thức MCP Server & Client
- Triển khai `retailops_mcp_server.py` hỗ trợ stdio và SSE port 8002, kết nối qua `retailops/workflow/mcp_client.py` và kiểm thử tự động tại `tests/test_mcp_protocol.py` (100% PASS).

### 2.5. Hoàn Thiện CI/CD & Xác Minh Hợp Đồng Hệ Thống
- Nhánh `feature/fix-ui-02-manager-persistence` vượt qua toàn bộ **353 Python tests OK** (0 failures), đồng thời vượt qua 4 cổng kiểm định nghiêm ngặt:
  - `python scripts/check_docs_contract.py` $\rightarrow$ PASS (4/4 gates).
  - `python scripts/check_deployment_contract.py` $\rightarrow$ PASS.
  - `python scripts/check_eval_dataset.py` $\rightarrow$ PASS.
  - `python scripts/build_agent_notebook.py --check` $\rightarrow$ PASS (Đồng bộ notebook artifacts).

### 2.6. Hoàn Thành Phase 1.1 (Truthful UX) & Phase 1.2 (Store Manager Persistence SSOT)
- **Phase 1.1 (Truthful UX - PR FIX01 - Commit `56fda06`)**: Xóa số 0 tĩnh khi KPI lỗi mạng, bỏ tự gán "Tiêu chuẩn" cho variants, dọn dữ liệu mẫu prefill trong modal quản lý.
- **Phase 1.2 (Store Manager Persistence & Shared Inventory SSOT - PR FIX02)**:
  - Chuyển toàn bộ Catalog & Tồn kho vào database SSOT (SQLite schema `v3`, PostgreSQL schema `v4`).
  - Lớp proxy `CatalogMapping` đồng bộ thời gian thực giữa các session, không bị mất dữ liệu khi restart container.
  - Khớp nối `check_inventory` và `dispute_agent` trực tiếp với tồn kho variant và `warranty_days` trong DB, xóa hoàn toàn số liệu giả định fallback (`stock_qty=6`).
  - Chuẩn hóa `ActorContext` và mở rộng phạm vi Audit Trail toàn shop qua `GET /api/manager/events`.
  - Phân tách DOM ID `btn-sidebar-manager-nav` và `btn-panel-manager-banner` trong giao diện, tự động mở Manager Console khi đăng nhập vai trò `manager`.
  - Khắc phục triệt để 8 phản hồi kiểm toán kỹ thuật từ GPT 6 Astra High: bảo toàn tồn kho variant khi update product; khớp chính xác size/color và phân biệt rõ `stock_unknown`/`variant_not_found`/`out_of_stock`/`in_stock`; vô hiệu hóa cache cross-session khi Catalog thay đổi; đồng bộ bảo hành và chặn proposal cho đơn không tồn tại; tối ưu thứ tự import bảng; backfill toàn bộ `product_id` cho orders; chặn xóa sản phẩm đã có đơn; tách bạch `principal_id` và `customer_id`.
  - Bổ sung 8 automated tests mới tại `tests/test_manager_crud.py`, đạt **353/353 tests PASS**.

### 2.7. Hợp Nhất Vào Main & Ổn Định Toàn Bộ CI/CD Pipeline (Commit `85834d6` & `d7ce461`)
- **Merge PR #33 vào main** (commit `a6ec080`): Tích hợp toàn bộ Phase 1.2 Store Manager Persistence vào nhánh chính.
- **Khắc phục lỗi index psycopg `dict_row`**: Sửa `p_row[0]`, `ev_row[0]`, `v_sum[0]` thành alias name (`SELECT ... AS max_val / total_stock / cnt`) tại `store.py`, `routes.py`, `demo.py`, đảm bảo tương thích 100% cả SQLite và PostgreSQL.
- **Tham số hóa câu lệnh LIKE**: Sửa `WHERE kind LIKE 'product_%'` thành `WHERE kind LIKE ?` kèm param để chống lỗi hiểu nhầm `%` thành format placeholder trong psycopg.
- **Cập nhật Schema Version Assertion**: Đồng bộ test `tests/test_knowledge.py` assert đúng version hiện hành `BUSINESS_SCHEMA_CURRENT = 4`.
- **Đóng gói Docker Seed Data**: Bổ sung `COPY data/deepseek_seed_data.json /app/data/deepseek_seed_data.json` vào `Dockerfile`, đưa bước kiểm thử container trong Deploy to EC2 về trạng thái PASS 100%.
- **Trạng thái GitHub Actions hiện tại**:
  - `CI` ([Run #236](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/35892629194)): **SUCCESS (Xanh 100%)**
  - `Ops Console` ([Run #143](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/35892629115)): **SUCCESS (Xanh 100%)**
  - `Deploy baseline runner to EC2`: Bước Verify & Test container đã **PASS 100%**; tạm dừng tại bước SSM send-command do EC2 instance đang STOPPED.

---

## 3. LỘ TRÌNH TRIỂN KHAI TIẾP THEO (NEXT PHASES ROADMAP)

Hệ thống tuân thủ nghiêm ngặt lộ trình phụ thuộc kỹ thuật 7 giai đoạn đã thống nhất:

* **Phase 0**: Documentation Truth & Reconciliation — Đã hoàn tất đồng bộ toàn bộ tài liệu dự án, ma trận trạng thái, loại bỏ số liệu giả định.
* **Phase 1**: Data & Observability Foundation:
  - PR 1.1: [PLAN_FIX_UI_01_TRUTHFUL_UX.md](PLAN_FIX_UI_01_TRUTHFUL_UX.md) (**ĐÃ HOÀN THÀNH** — Merged main `56fda06`).
  - PR 1.2: [PLAN_FIX_UI_02_MANAGER_PERSISTENCE.md](PLAN_FIX_UI_02_MANAGER_PERSISTENCE.md) (**ĐÃ HOÀN THÀNH** — Merged main `a6ec080`, CI/CD stabilized `d7ce461`).
  - PR 1.3: [PLAN_FIX_UI_03_OPSCONSOLE_INTEGRITY.md](PLAN_FIX_UI_03_OPSCONSOLE_INTEGRITY.md) (**TIẾP THEO**: Truthful Telemetry: Token/Cost thật & Concurrency fields).
* **Phase 2**: Triển khai GraphRAG Apache AGE v6.2 ([PLAN_GRAPHRAG_AGE.md](PLAN_GRAPHRAG_AGE.md)) trên nhánh `feature/graphrag-age` dựa trên Catalog SSOT từ Phase 1.
* **Phase 3**: Triển khai Runtime Efficiency & Bounded Concurrency ([PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md](PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md)).
* **Phase 4**: Đo lường thực nghiệm khoa học (GraphRAG A/B, Concurrency load test, Đối kháng Gemma-4 vs DeepSeek API) phục vụ Chương 4 Luận văn.
* **Phase 5**: Demo Enhancements (Facebook Messenger Webhook & Cổng QR Live).
* **Phase 6**: Post-Thesis Scaling (Distillation, LoRA Fine-Tuning, AWS Multi-AZ).

---

## 4. QUY TRÌNH BẬT MÁY & ĐỒNG BỘ IP SÁNG MAI (COLD-START & IP REBIND RUNBOOK)

Khi dừng máy qua đêm và bật lại vào sáng hôm sau, AWS sẽ cấp Public IPv4 mới cho instance `i-0fd116d8927d0e412` (do không dùng Elastic IP). Quy trình 4 bước đơn giản để kích hoạt lại toàn bộ hệ thống:

```
[1. Start EC2 Console] ──> [2. Cập nhật IP trong public.env] ──> [3. Re-run Deploy Job] ──> [4. Verify Live Smoke]
```

### Bước 1: Khởi Động Instance Trên AWS Console
1. Truy cập [AWS EC2 Console (us-east-1)](https://us-east-1.console.aws.amazon.com/ec2/home?region=us-east-1#Instances:instanceState=stopped).
2. Tích chọn instance `i-0fd116d8927d0e412` $\rightarrow$ Nhấn **Instance state** $\rightarrow$ Chọn **Start instance**.
3. Chờ ~1-2 phút cho instance chuyển sang `Running` và lấy địa chỉ **Public IPv4** mới (ví dụ: `X.X.X.X`).

### Bước 2: Cập Nhật IP Mới Vào `public.env` (Qua SSM Session Manager)
1. Trong EC2 Console, chọn instance `i-0fd116d8927d0e412` $\rightarrow$ Nhấn **Connect** $\rightarrow$ Chọn tab **Session Manager** $\rightarrow$ Nhấn **Connect**.
2. Chạy lệnh cập nhật (thay `X-X-X-X` bằng IP mới với dấu gạch ngang, ví dụ IP `54.210.88.99` thì hostname là `retailops.54-210-88-99.sslip.io`):
```bash
sudo sed -i 's/RETAILOPS_PUBLIC_HOST=.*/RETAILOPS_PUBLIC_HOST=retailops.X-X-X-X.sslip.io/' /opt/retailops/public.env
sudo sed -i 's|RETAILOPS_PUBLIC_ORIGIN=.*|RETAILOPS_PUBLIC_ORIGIN=https://retailops.X-X-X-X.sslip.io|' /opt/retailops/public.env
```
3. Kiểm tra lại giá trị đã cập nhật:
```bash
sudo grep '^RETAILOPS_PUBLIC_' /opt/retailops/public.env
```

### Bước 3: Kích Hoạt Triển Khai (Deploy) Tự Động
1. Mở GitHub Actions: [Deploy baseline runner to EC2 #149](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/35892629094).
2. Nhấn nút **Re-run failed jobs** (hoặc vào tab *Actions* $\rightarrow$ *Deploy baseline runner to EC2* $\rightarrow$ *Run workflow* trên nhánh `main`).
3. Workflow sẽ tự động:
   - Đẩy Docker image mới nhất lên AWS ECR.
   - Gửi lệnh qua SSM xuống EC2 để kích hoạt container mới.
   - Cập nhật chứng chỉ TLS Caddy cho domain mới và khởi chạy web service.

### Bước 4: Kiểm Tra Live Smoke & Trải Nghiệm Ứng Dụng
1. Trong SSM Session Manager, chạy kiểm tra nhanh:
```bash
sudo python3 /opt/retailops/live-e2e.py --mode smoke
```
2. Mở trình duyệt truy cập: `https://retailops.X-X-X-X.sslip.io`
   - Đăng nhập tài khoản demo (`customer`, `manager` hoặc Google Login).
   - Kiểm tra Catalog và Inventory đã lưu vĩnh viễn trong DB, trải nghiệm Store Manager Console và Chatbot AI.

