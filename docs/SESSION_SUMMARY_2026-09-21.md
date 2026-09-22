# BÁO CÁO TỔNG KẾT PHIÊN LÀM VIỆC — RETAILOPS — 2026-09-21

> **Phiên làm việc:** Tối 2026-09-21 (GMT+7)  
> **Repository:** `tuteemovaixlong/CSKH_ban_le`  
> **Nhánh:** `main`  
> **Commit snapshot:** `fd24e36087280a1877a0a3fa6c6c575f221b60c6` (`fd24e36`)  
> **Application runtime snapshot:** `d3ca3a6ff6fa106af973d4c44c6ee955bce20f13` (`d3ca3a6`)  
> **Audit basis / Documentation baseline reviewed:** `fd24e36` · **Application verified:** `d3ca3a6`  
> **Mục tiêu phiên:** Rà soát toàn diện, đồng bộ hóa 100% tài liệu kỹ thuật/kế hoạch với mã nguồn thực tế và thiết lập cổng kiểm định tính toàn vẹn tài liệu tự động vào CI.

---

## 1. Toàn Cảnh Trạng Thái Hệ Thống Cuối Phiên

### 1.1. Bảng Tóm Tắt Hiện Trạng (System Status Matrix)

| Thành phần / Luồng | Trạng thái | Ghi chú kỹ thuật |
| :--- | :---: | :--- |
| **Git Remote (`origin/main`)** | ✅ Đã đồng bộ (`fd24e36`) | Ahead `b93eb5a` đúng 1 commit, không có commit rẽ nhánh. |
| **Runtime Code (`retailops/`, `web/`, `opsconsole/`, `deploy/`)** | ✅ 100% Bất biến | **0 dòng code runtime bị sửa** trong suốt đợt đồng bộ tài liệu. |
| **Bộ Tài liệu (`docs/*.md`, `README.md`)** | ✅ Truthful Ground Truth | 21 file Markdown được chuẩn hóa, xóa bỏ hoàn toàn overclaim và underclaim. |
| **Cổng Kiểm Định Tài Liệu (`scripts/check_docs_contract.py`)** | ✅ PASS (4/4 Gates) | Kiểm tra Dataset (LF SHA-256), Stale HEAD, Relative links, và AST Tools Inventory. |
| **GitHub Actions CI #227 (Main CI)** | ✅ SUCCESS | Pass toàn bộ 340 tests, offline contract checks, và documentation validation. |
| **GitHub Actions Ops Console #134** | ✅ SUCCESS | Pass trên ma trận môi trường PostgreSQL, Windows và Ubuntu. |
| **GitHub Actions Deploy EC2 #142** | ❌ FAILED (SSM/EC2) | Chết ở bước `aws ssm send-command` do EC2 `i-0fd116d8927d0e412` không ở trạng thái active/SSM-ready. |
| **EC2 Server (`retailops-dev`)** | ⏸️ Stopped / Standby | Cấu hình t3.large, 50 GiB EBS (từ phiên sáng). Cần start instance khi cần chạy live demo. |

---

## 2. Các Kết Quả Đã Hoàn Thành Trong Phiên Tối

### 2.1. Phân định Cấu trúc 3 Tập Dữ liệu Đánh giá (Dataset Hierarchy)
- **`evals/scenarios/master_250_v1.jsonl`** (132.633 bytes, 250 ca):
  - Canonical Frozen Benchmark Dataset — bản ghi chuẩn mốc không thay đổi.
  - Pinned SHA-256 (POSIX LF-normalized): `36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411`.
- **`evals/scenarios/benchmark_250.jsonl`** (132.633 bytes, 250 ca):
  - Active Operational Mirror — bản sao phục vụ thực thi benchmark trực tiếp.
  - Hash đồng nhất `36fa8c7a...` tại thời điểm freeze.
- **`evals/scenarios/baseline_v1.jsonl`** (30 ca):
  - CI Baseline Dataset — tập kịch bản thu nhỏ phục vụ regression nhanh hàng ngày trong CI/CD.

### 2.2. Xây dựng Trình Kiểm định Hợp đồng Tài liệu ([`scripts/check_docs_contract.py`](../scripts/check_docs_contract.py))
Được tích hợp trực tiếp vào [`.github/workflows/ci.yml`](../.github/workflows/ci.yml):
1. **Gate 1 - Dataset Integrity**: Kiểm tra sự tồn tại của 3 tệp, số lượng dòng (250 / 250 / 30) và tính toàn vẹn SHA-256 chuẩn hóa (tự động thay `\r\n` thành `\n` bảo đảm tính nhất quán cross-platform giữa Windows và Linux).
2. **Gate 2 - Stale Git HEAD Detection**: Quét toàn bộ status/plan docs đang hoạt động; chuẩn hóa dòng (loại bỏ markdown ticks, bold) để phát hiện các pattern stale SHA (`Git HEAD: <sha>` hoặc `<sha> (Git HEAD)`). Bắt buộc dùng định dạng chuẩn: `> **Audit basis / Documentation baseline reviewed:** <sha> · **Application verified:** <sha>`.
3. **Gate 3 - Relative Links & Zero File Scheme**: Kiểm tra đệ quy tất cả link markdown trong `docs/` và `README.md`; bảo đảm tất cả relative path đều tồn tại trên đĩa; cấm tuyệt đối URL cục bộ dạng `file:` protocol.
4. **Gate 4 - AST Tool Inventory & Presence Gate**: Dùng `ast.parse` phân tích cú pháp tĩnh từ [`retailops_mcp_server.py`](../retailops_mcp_server.py) (10 tools) và [`agent_protocol.py`](../agent_protocol.py) (12 tools) để xác nhận số lượng tool và đảm bảo toàn bộ 10 MCP tools có mặt trong [`docs/PLAN_MCP_INTEGRATION.md`](PLAN_MCP_INTEGRATION.md).

### 2.3. Rà soát & Đồng bộ Hóa 21 Tài liệu Markdown (Commit `fd24e36`)
1. **[`docs/BUSINESS_TEST_SCENARIOS.md`](BUSINESS_TEST_SCENARIOS.md)**:
   - Chuyển các cột % ước lệ thành 4 trạng thái vận hành chuẩn: `Read-only automated`, `Proposal-only`, `Human handoff`, `Backend transaction verified`.
   - Cập nhật đúng sản phẩm trong đơn hàng: O-101 (Áo thun P-101), O-102 (Áo khoác P-102), O-202 (Áo polo P-202), O-301 (Sơ mi Oxford P-103), O-302 (Khoác gió Bomber P-104), O-303 (Polo nam P-203), O-304 (Bộ nồi Inox P-401).
   - Làm rõ số điện thoại của C-003, C-004 là metadata kịch bản; schema DB `customers` chỉ có `(id, name)`.
   - Làm rõ giới hạn SOP 1 (chưa có API khiếu nại bưu tá) và SOP 4 (voucher sinh trong chat, chưa có API cấp voucher).
2. **[`docs/PLAN_ECOMMERCE_OPS_COPILOT.md`](PLAN_ECOMMERCE_OPS_COPILOT.md)**:
   - Khớp dải đơn hàng O-101..O-304 và tập DeepSeek mở rộng O-305..O-312; danh mục sản phẩm P-101..P-508.
   - Cập nhật đúng số lượng 340 automated tests.
   - Ghi nhận Duyệt 1-Click của Staff là gửi phản hồi chat (`POST /api/staff/reply`), chưa thay đổi trạng thái đơn DB.
3. **[`docs/PLAN_FIX_UI_01_TRUTHFUL_UX.md`](PLAN_FIX_UI_01_TRUTHFUL_UX.md)**:
   - Ghi nhận giá trị mặc định modal Thêm (price 299k, stock 30, warranty 30) và Sửa (`p.price || 299000`, `p.stock ?? 25`), cùng fallback backend `POST /api/manager/products`.
   - Phân tích rõ sai lệch ngữ nghĩa của chỉ số "AI Resolution" (thực chất là Non-handoff rate, 100% khi total_convs = 0).
4. **[`docs/PLAN_FIX_UI_02_MANAGER_PERSISTENCE.md`](PLAN_FIX_UI_02_MANAGER_PERSISTENCE.md)**:
   - Chuẩn hóa tên bảng DB là `business_events` (không phải `events`).
   - Định hướng loại bỏ production fallback tra cứu `stock_map` hardcode.
   - Đưa thời hạn bảo hành vào SSOT (khắc phục dispute_agent hardcode 90 ngày).
   - Định nghĩa tường minh cấu trúc `ActorContext`.
   - Ghi nhận lỗi trùng lặp DOM ID `btn-sidebar-manager-console` trong `web/index.html`.
5. **[`docs/PLAN_FIX_UI_03_OPSCONSOLE_INTEGRITY.md`](PLAN_FIX_UI_03_OPSCONSOLE_INTEGRITY.md)**:
   - Ghi nhận `scripts/run_live_benchmark_http.py` là benchmark producer sinh kết quả có cấu trúc.
   - Bỏ `expected_worker`; trích xuất `actual_worker` từ `subagent_history`. Đổi `unexpected_tools` thành `extra_tools`.
6. **[`docs/PLAN_MCP_INTEGRATION.md`](PLAN_MCP_INTEGRATION.md)**:
   - Ghi nhận kiến trúc `FallbackMCPServer` thuần Python hỗ trợ stdio và SSE HTTP, tương thích tùy chọn `FastMCP`.
   - Ghi nhận adapter in-process và đúng 14 test methods trong `tests/test_mcp_protocol.py`.
   - Liệt kê chính xác 10 công cụ MCP và tham số.
7. **[`docs/PERSISTENT_IDENTITY.md`](PERSISTENT_IDENTITY.md) & [`docs/PLAN_RBAC_GOOGLE_AUTH.md`](PLAN_RBAC_GOOGLE_AUTH.md)**:
   - Sửa các liên kết relative hỏng trỏ tới code thực tế: `../web/index.html`, `../web/app.js`, `../retailops/http/routes.py`, `../retailops/business/store.py`.
   - Phân định rõ 4 application roles (`customer`, `viewer`, `staff`, `manager`) và vai trò hạ tầng `opsadmin` (Caddy Basic Auth).
8. **[`docs/SYSTEM_FOUNDATION.md`](SYSTEM_FOUNDATION.md)**:
   - Sửa đường dẫn RAG thành `retailops/knowledge/`.
   - Xác nhận kiến trúc gồm Supervisor, 4 subagents (`order_agent`, `policy_agent`, `dispute_agent`, `witty_agent`) và `read_worker`.
9. **Các Kế hoạch Chiến lược khác**:
   - [`docs/PLAN_DATA_COLLECTION_FLYWHEEL.md`](PLAN_DATA_COLLECTION_FLYWHEEL.md): Cập nhật 6/6 test pass trong `tests/test_feedback.py`.
   - [`docs/PLAN_DEEPSEEK_DISTILLATION.md`](PLAN_DEEPSEEK_DISTILLATION.md): Đưa YAML frontmatter lên dòng 1, dùng `prepare_cancellation`, bỏ dead link script.
   - [`docs/PLAN_MODEL_SELECTION_STRATEGY.md`](PLAN_MODEL_SELECTION_STRATEGY.md) & [`docs/PLAN_FINE_TUNING_SERVING.md`](PLAN_FINE_TUNING_SERVING.md): Thay `cases.jsonl` bằng `benchmark_250.jsonl`, gắn nhãn Planning Estimates.
   - [`docs/PLAN_MULTIMODAL_ATTACHMENTS.md`](PLAN_MULTIMODAL_ATTACHMENTS.md): Nêu đúng giới hạn chuỗi base64 <= 6M ký tự, không whitelist MIME ở server.
   - [`docs/PLAN_OMNICHANNEL_INTEGRATION.md`](PLAN_OMNICHANNEL_INTEGRATION.md): Bỏ `web/staff.html` khỏi nguồn sự thật.

---

## 3. Đánh Giá Kỹ Thuật & Các Điểm Cần Lưu Ý

### 3.1. Sự Cố Workflow `Deploy baseline runner to EC2 #142`
- **Nguyên nhân**: File [`.github/workflows/deploy-ec2.yml`](../.github/workflows/deploy-ec2.yml) hiện trigger trên mọi sự kiện `push: branches: [main]`:
  ```yaml
  on:
    workflow_dispatch:
    push:
      branches: [main]
  ```
  Khi commit `fd24e36` được push lên `main`, workflow này tự động kích hoạt.
- **Tiến trình chạy của #142**:
  - Bước 1: Verify source, chạy 340 tests, build Docker image, chạy in-container tests -> **Tất cả đều PASS**.
  - Bước 3: `Publish image, activate runner and roll configured public web` -> Gọi lệnh `aws ssm send-command` tới EC2 Instance `i-0fd116d8927d0e412`.
  - Kết quả: Báo lỗi `InvalidInstanceId: Instances [[i-0fd116d8927d0e412]] not in a valid state for account`. Điều này xảy ra do máy chủ EC2 đang ở trạng thái Tắt (Stopped) hoặc SSM Agent chưa online để tiết kiệm chi phí cloud khi không chạy demo.
- **Giải pháp đề xuất (Next Action)**:
  Bổ sung `paths-ignore` vào `deploy-ec2.yml` để các commit chỉ thay đổi tài liệu, markdown hoặc test scripts kiểm định docs không kích hoạt workflow deploy production/demo:
  ```yaml
  on:
    workflow_dispatch:
    push:
      branches: [main]
      paths-ignore:
        - 'docs/**'
        - '*.md'
        - 'scripts/check_docs_contract.py'
  ```

### 3.2. Phạm Vi Bảo Vệ Thực Tế của Gate 4 trong `check_docs_contract.py`
- **Thực tế hiện tại**:
  Gate 4 hiện đóng vai trò là **AST Tool Inventory & Name Presence Gate**:
  - Đảm bảo `retailops_mcp_server.py` khai báo đúng 10 tools qua decorator `@*.tool`.
  - Đảm bảo `agent_protocol.py` khai báo đúng 12 tools trong hằng số `TOOLS`.
  - Đảm bảo tên của cả 10 MCP tools xuất hiện trong `docs/PLAN_MCP_INTEGRATION.md`.
- **Điểm chưa bảo vệ tự động**:
  Hiện script chưa phân tích cú pháp AST của từng tham số (`args`, `defaults`, `type annotations`) và chưa đối chiếu khớp từng ký tự bảng Markdown trong tài liệu.
  *(Lưu ý: Chữ ký 10 công cụ trong tài liệu hiện tại đã được audit thủ công và hoàn toàn khớp với code tại commit `fd24e36`)*.
- **Kế hoạch nâng cấp tương lai**:
  Nâng cấp hàm `check_ast_tools_contract()` để trích xuất đầy đủ `name`, `type`, `default_value` từ AST và so khớp bảng tham số chi tiết trong tài liệu.

### 3.3. Phân biệt Artifact Cục bộ và Mã nguồn Repository
- File `walkthrough.md` được sinh ra trong thư mục AppData cục bộ của Antigravity IDE (`%USERPROFILE%\.gemini\antigravity-ide\brain\...`) phục vụ hiển thị kết quả kiểm thử phiên làm việc cho người dùng.
- Tệp báo cáo chính thức được lưu trực tiếp trong kho mã nguồn GitHub tại [`docs/SESSION_SUMMARY_2026-09-21.md`](SESSION_SUMMARY_2026-09-21.md).

---

## 4. Kế Hoạch Hành Động Tiếp Theo (Backlog & Roadmap)

1. **Hạ tầng CI/CD**:
   - Thêm `paths-ignore` vào `.github/workflows/deploy-ec2.yml` để phân tách rõ ràng luồng deploy runtime và luồng cập nhật tài liệu.
   - Khi cần khởi động demo hệ thống, bật EC2 `i-0fd116d8927d0e412` và chạy `python scripts/update_ec2.py --auto-ip`.
2. **Nâng cấp Cổng Kiểm Định (`check_docs_contract.py`)**:
   - Mở rộng Gate 4 để kiểm tra chi tiết tham số, kiểu dữ liệu và giá trị mặc định của từng tool.
3. **Các Kế Hoạch Kỹ Thuật Tiếp Theo Đã Sẵn Sàng Thực Thi**:
   - **`PLAN_FIX_UI_01_TRUTHFUL_UX`**: Chỉnh sửa giao diện quản lý, chuẩn hóa các trường modal và chỉ số AI Resolution.
   - **`PLAN_FIX_UI_02_MANAGER_PERSISTENCE`**: Hoàn thiện tầng lưu trữ SQLite/PostgreSQL cho các nghiệp vụ quản lý và SSOT bảo hành.
   - **`PLAN_FIX_UI_03_OPSCONSOLE_INTEGRITY`**: Chuẩn hóa Ops Console với benchmark runner.
   - **`PLAN_FIX_UI_04_CHAT_HISTORY_RESUME`**: Lưu trữ và khôi phục lịch sử hội thoại khách hàng.
