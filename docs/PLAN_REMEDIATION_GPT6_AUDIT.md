# Kế Hoạch Khắc Phục Sau Đợt Rà Soát GPT-6 Astra Pro Mode (Historical Audit)

> **Trạng thái:** SUPERSEDED / HISTORICAL AUDIT  
> **Audit basis / Documentation baseline reviewed:** `b93eb5a` · **Application verified:** `fd24e36`  
> **Ngày rà soát & lưu trữ:** 2026-09-22  
> **Kết luận:** Toàn bộ các hạng mục kỹ thuật ngắn hạn đã được triển khai và kiểm thử tự động 100% trong mã nguồn (`tests/test_audit_remediation.py`, `tests/test_manager_crud.py`). Hạng mục Catalog DB Persistence duy nhất còn lại được chuyển giao và theo dõi độc quyền tại [PLAN_FIX_UI_02_MANAGER_PERSISTENCE.md](PLAN_FIX_UI_02_MANAGER_PERSISTENCE.md).

---

## 1. Bối Cảnh Kiểm Toán Lịch Sử

Bản rà soát chuyên sâu 40 phút từ GPT-6 Astra Pro Mode đã đánh giá toàn diện codebase tại commit gốc `c2a42853ab4e563af7acf37a40b07869155bccc8`. Báo cáo đánh giá rất cao:
- Lõi giao dịch hủy đơn có kiểm soát (AI không tự ý hủy, backend kiểm tra quyền, owner, version, idempotency).
- Cơ chế checkpointing, lease/fencing, replay sau sự cố.
- Schema PostgreSQL tenant-isolated và bộ CI kiểm thử thực tế.

Tài liệu này lưu trữ lại bằng chứng hoàn thành của các khuyến nghị kiểm toán.

---

## 2. Các Hạng Mục Đã Hoàn Thành & Minh Chứng Kiểm Thử Tự Động

### 🟢 P0.1 — Lỗ Hổng Phân Quyền (RBAC) Backend & Bảo Vệ Transcript
- **Hiện trạng đã giải quyết**: Bổ sung `app.require_permission(MANAGER)` cho 7 route quản lý và `STAFF` cho staff desk; khách hàng chỉ được đọc hội thoại của chính mình, người lạ bị chặn HTTP 403 `permission_denied`.
- **Minh chứng**: `tests/test_staff_desk.py` và `tests/test_manager_crud.py`.

### 🟢 P0.2 — State Machine Transition Guard Cho Đơn Hàng
- **Hiện trạng đã giải quyết**: Trong `retailops/http/routes.py:249`, thêm kiểm tra tính hợp lệ của bước chuyển trạng thái đơn hàng (`require(cur_status == 'pending', 400, "invalid_transition", ...)`). Chặn mọi nỗ lực chuyển ngược từ `cancelled` hoặc `delivered` về `pending`.
- **Minh chứng**: `tests/test_manager_crud.py:110` và `tests/test_manager_crud.py:116`.

### 🟢 F11 — Băm Base64 Ảnh Vào Digest Chống Replay Sai Lệch
- **Hiện trạng đã giải quyết**: Trong `retailops/business/application.py:111`, băm SHA-256 nội dung Base64 của ảnh vào token digest (`att_data_hash = hashlib.sha256(attachment['data'].encode()).hexdigest()[:16]`). Khách gửi 2 ảnh khác nhau cùng tên tệp sẽ không bị replay câu trả lời cũ.
- **Minh chứng**: `tests/test_audit_remediation.py:57` (`test_f11_attachment_digest_prevents_mismatched_replay`).

### 🟢 F06 — Đồng Bộ Handoff & Tự Động Ghi Nhận Ticket Phía Server
- **Hiện trạng đã giải quyết**: Khi công cụ `request_human_support` được kích hoạt hoặc nhân viên can thiệp, hệ thống tự động ghi nhận bản ghi escalation vào bảng `conversation_feedback` trong DB mà không phụ thuộc vào client.
- **Minh chứng**: `tests/test_audit_remediation.py` (`test_f06_human_handoff_automatic_escalation_record`).

### 🟢 F04 — Siết An Toàn Cho Cache (Freshness & Evidence Registration)
- **Hiện trạng đã giải quyết**: Khi hit ToolCache cho `get_order` / `read_order`, `BoundTools` vẫn nạp `versions` của đơn hàng; đối với `search_knowledge`, `bound.knowledge.sources` được đăng ký đầy đủ để vượt qua kiểm tra trích dẫn; các công cụ mutation bị chặn cache.
- **Minh chứng**: `tests/test_audit_remediation.py` (`test_f04_tool_cache_freshness_and_un_cached_mutation`).

### 🟢 P0.3 & F07 — Tính Toán Chỉ Số KPI Thực Tế Từ DB & Xử Lý An Toàn File Catalog
- **Hiện trạng đã giải quyết**: `Catalog.save()` bắt lỗi ghi đĩa `PermissionError` mà không làm sập ứng dụng; route `/api/manager/kpis` tính toán động `ai_resolution_rate`, `avg_csat`, `escalation_rate` từ bảng `orders`, `conversations`, `conversation_feedback`.
- **Minh chứng**: `tests/test_audit_remediation.py` (`test_p03_catalog_save_handles_error`) và `retailops/http/routes.py:61-75`.

---

## 3. Chuyển Giao Hạng Mục Duy Nhất Còn Lại

Hạng mục **Chuyển đổi Catalog & Kho hàng từ file JSON / RAM sang cơ sở dữ liệu PostgreSQL SSOT** được chuyển giao toàn bộ sang kế hoạch chuyên trách:
👉 **[PLAN_FIX_UI_02_MANAGER_PERSISTENCE.md](PLAN_FIX_UI_02_MANAGER_PERSISTENCE.md)** (Phase 1 SSOT Foundation).
