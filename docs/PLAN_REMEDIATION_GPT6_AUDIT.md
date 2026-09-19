# Kế Hoạch Khắc Phục Sau Đợt Rà Soát GPT-6 Astra Pro Mode
**Tài liệu theo dõi kỹ thuật & lộ trình hoàn thiện Production Readiness**  
*Cập nhật: 19/09/2026*

---

## 1. Tổng Quan Rà Soát
Bản rà soát chuyên sâu 40 phút từ GPT-6 Astra Pro Mode đã đánh giá toàn diện codebase tại commit gốc `c2a42853ab4e563af7acf37a40b07869155bccc8`. Báo cáo đánh giá rất cao:
- Lõi giao dịch hủy đơn có kiểm soát (AI không tự ý hủy, backend kiểm tra quyền, owner, version, idempotency).
- Cơ chế checkpointing, lease/fencing, replay sau sự cố.
- Schema PostgreSQL tenant-isolated và bộ CI kiểm thử thực tế.

Đồng thời, báo cáo chỉ ra các điểm hở cần xử lý triệt để trước khi đưa dữ liệu thật lên production.

---

## 2. Phần 1: Các Hạng Mục ĐÃ HOÀN THÀNH 100% (Commit Đợt Này)

### 🟢 P0.1 — Lỗ hổng phân quyền (RBAC) Backend & Transcript Protection
- **Vấn đề**: Route manager (CRUD sản phẩm, KPI, update status) và staff (escalation, reply, resolve) thiếu kiểm tra role; khách thường có thể đọc trộm transcript của khách khác nếu biết CID.
- **Giải pháp đã thực thi**:
  - `retailops/http/routes.py`: Thêm `app.require_permission(MANAGER)` cho 7 route manager.
  - Thêm `app.require_permission(STAFF)` cho các route staff desk.
  - Phân quyền đọc transcript: Nhân viên (`STAFF`) được đọc mọi hội thoại; khách thường (`customer`) chỉ đọc đúng hội thoại của chính mình, người lạ bị chặn HTTP 403 `permission_denied`.
  - Bổ sung test kiểm chứng trong `tests/test_staff_desk.py` và `tests/test_manager_crud.py`.

### 🟢 F08 — Lỗi vLLM Tool Calling 400 Bad Request
- **Vấn đề**: vLLM Server trên GPU Colab L4 thiếu cấu hình tool choice / parser khiến OpenAI SDK / LiteLLM trả lỗi 400.
- **Giải pháp đã thực thi**:
  - Tạo `notebooks/colab_vllm_l4.py` chuẩn hóa với `--enable-auto-tool-choice` và `--tool-call-parser hermes`, tự động warmup với payload `allow_tools=True` trước khi mở tunnel.

### 🟢 Kiến Trúc — Đấu Nối Multi-Agent LangGraph Vào Web Chat
- **Vấn đề**: Web chat thực tế chỉ chạy Single-Agent (`retailops_agent.py`), trong khi đồ thị Multi-Agent supervisor nằm riêng chưa được đưa vào production.
- **Giải pháp đã thực thi**:
  - `retailops/business/application.py`: Đấu nối hàm `run_multiagent` vào `Application.chat()`, tự động đồng bộ `action_proposal` (`exchange_1to1`, `size_exchange`), thông tin bưu tá `shipment`, và trích dẫn RAG lên Web chat.
  - Viết bộ test tích hợp E2E: `tests/test_multiagent_chat_integration.py` (5/5 tests PASS).

### 🟢 Vận Hành — Tự Động Hóa Xử Lý EC2 Đổi IP (Rollout Script)
- **Vấn đề**: Khi EC2 stop/start đổi IP, `rollout-public-web.sh` phát hiện IP mới nhưng chỉ restart Caddy mà không recreate Web, khiến container Web giữ IP cũ trong RAM và trả lỗi 403 `invalid_host`.
- **Giải pháp đã thực thi**:
  - Sửa `deploy/rollout-public-web.sh` dòng 67 để tự động `--force-recreate web caddy` khi IP thay đổi.

---

## 3. Phần 2: Các Hạng Mục SẼ TRIỂN KHAI TIẾP THEO (Giai Đoạn Kế Tiếp)

Dưới đây là 5 hạng mục cần gọi lại để thực hiện ngay ở phiên làm việc tới:

### 1. [P0.2] State Machine Transition Guard cho Đơn Hàng
- **Hiện trạng**: `/api/manager/orders/update-status` đã có role `MANAGER`, nhưng chưa kiểm tra tính hợp lệ của bước chuyển trạng thái (vẫn có thể chuyển ngược `cancelled -> pending` hoặc `delivered -> pending`).
- **Việc cần làm**:
  - Định nghĩa máy trạng thái hợp lệ:
    - `pending -> delivered`: Hợp lệ.
    - `pending -> cancelled`: Hợp lệ.
    - `cancelled -> pending`: Chặn (HTTP 400 `invalid_transition`).
    - `delivered -> pending`: Chặn (HTTP 400 `invalid_transition`).
  - Viết test kiểm tra từ chối các bước chuyển trạng thái phi lý.

### 2. [F11] Băm Nội Dung Ảnh Vào Digest Chống Gửi Trùng
- **Hiện trạng**: `digest` chat chỉ băm `text + attachment.name`. Hai ảnh khác nhau nhưng cùng tên gửi lên cùng `request_id` sẽ bị replay câu trả lời của ảnh trước.
- **Việc cần làm**:
  - Trong `Application.chat()`:
    `att_token = (attachment.get('name', '') + ':' + hashlib.sha256(attachment.get('data', '').encode()).hexdigest()) if attachment else ''`
  - Viết test: gửi 2 request cùng `request_id`, cùng tên ảnh nhưng dữ liệu ảnh khác nhau phải không bị replay nhầm.

### 3. [F06] Đồng Bộ Handoff Contract & Tự Động Tạo Ticket Phía Server
- **Hiện trạng**:
  - Backend `resolve` đổi `reason_code = 'resolved'`, nhưng frontend `app.js` lại check `sentiment_flag === 'resolved'`.
  - Tool `request_human_support` chỉ trả metadata chứ chưa tự lưu ticket/escalation vào DB (phụ thuộc vào client gửi thêm API feedback).
- **Việc cần làm**:
  - Sửa frontend `web/app.js` kiểm tra đúng `reason_code === 'resolved'`.
  - Khi tool `request_human_support` thực thi, backend tự động ghi nhận ngay ticket vào DB.

### 4. [F04] Siết An Toàn Cho Cache (Freshness & Evidence Registration)
- **Hiện trạng**: `ToolCache` trả kết quả sớm khiến `BoundTools` không nạp `versions` của đơn hàng; RAG cache không đăng ký `bound.knowledge.sources` cho lượt mới.
- **Việc cần làm**:
  - Tắt cache đối với `prepare_cancellation`.
  - Khi cache-hit `get_order`, vẫn cập nhật phiên bản đơn hàng vào `bound.versions`.
  - Khi cache-hit `search_knowledge`, tự động đăng ký `sources` vào `bound.knowledge.sources` để vượt qua citation provenance check.

### 5. [P0.3 & F07] Catalog Persistence & Tính Toán KPI Thực Tế
- **Hiện trạng**:
  - `Catalog.save()` nuốt ngoại lệ `except Exception: pass`.
  - `/api/manager/kpis` trả số liệu hardcode tĩnh (`ai_resolution_rate=83.5`, `avg_csat=4.8`).
- **Việc cần làm**:
  - Sửa `Catalog.save()` để không nuốt ngoại lệ âm thầm; chuẩn bị migration catalog sang bảng DB trong PostgreSQL.
  - Viết query tính toán KPI thực tế từ bảng `conversation_feedback` và `agent_turns`.
