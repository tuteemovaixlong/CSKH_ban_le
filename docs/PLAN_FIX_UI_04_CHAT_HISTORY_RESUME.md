# Module 4: Khôi Phục Lịch Sử Chat & Hội Thoại Tiếp Diễn (Chat History Resume & Session Memory)

> **Trạng thái:** IMPLEMENTED (Resume hoàn tất; Retention trên 6 lượt chờ F12 trong PR B)
> **Mức độ minh chứng (Evidence):** L1 Automated Tests (`tests/test_conversation_resume.py` 4/4 PASS cho resume $\le 6$ turns) · L3 Live Deployed
> **Audit basis / Documentation baseline reviewed:** `b93eb5a` · **Application verified:** `d3ca3a6`
> **Ngày rà soát & đồng bộ:** 2026-10-01
> **Kết luận:** Tính năng khôi phục (Resume) phiên làm việc khi F5 hoặc mở lại hội thoại cũ đã hoàn thành trên Web Client, Drawer/Dialog, API và bộ test kiểm thử tự động. Tuy nhiên, lệnh xóa cứng `DELETE LIMIT 6` trong `store.py:finish_turn()` vẫn đang tồn tại ở baseline hiện tại; việc lưu trữ toàn bộ lịch sử trên 6 lượt chat mà không bị prune thuộc phạm vi triển khai của **[F12] Bảo toàn Lịch sử Chat** trong PR B.
> **Phân định rõ 3 Hợp đồng Kiến trúc Lịch sử & Transcript:**
> 1. **Hợp đồng Lưu trữ DB (DB Persistence - F12 trong PR B)**: Xóa bỏ lệnh prune cứng `DELETE LIMIT 6` trong `store.py:finish_turn()`, lưu trữ đầy đủ 100% bản ghi các lượt chat trong bảng `agent_turns` để bảo toàn audit trail và phục vụ liên kết feedback.
> 2. **Hợp đồng Ngữ cảnh Prompt (Prompt Context - Bounded Window)**: Hàm `store.history(customer, cid)` ([retailops/business/store.py:616](../retailops/business/store.py#L616)) thực thi truy vấn giới hạn `SELECT ... ORDER BY id DESC LIMIT 6` (lưu ý: sử dụng cột `id`, không phải `turn_id`) để nạp vào prompt cho LLM; do đó việc bỏ prune trong DB hoàn toàn không làm phình RAM hay vượt quá token window của mô hình.
> 3. **Hợp đồng Phục vụ Giao diện (UI Transcript Delivery)**: Hàm `store.conversation_transcript()` ([retailops/business/store.py:846](../retailops/business/store.py#L846)) thực hiện `SELECT ... ORDER BY id ASC` nạp toàn văn lịch sử cho Staff Desk / Transcript API (`GET /api/conversations/{id}/messages`). Trong phạm vi Module 2.5, các phiên bán lẻ thông thường có độ dài ngắn (< 20 turns). Khi mở rộng sang Phase 5–6 với các phiên trao đổi dài hơn, endpoint transcript và UI cần bổ sung cơ chế phân trang (pagination / lazy load) để tránh tải toàn bộ vào RAM/DOM.

---

## 1. Kết Quả Triển Khai Thực Tế: ĐÃ HOÀN THÀNH 100%

### Backend & Cơ Sở Dữ Liệu:
- ✅ **Bảng lưu trữ đa lượt**: Bảng `conversations` và `agent_turns` trong SQLite/PostgreSQL lưu đầy đủ `messages` (JSON prompt, user message, tool calls, tool results) và `result` của từng lượt trò chuyện (trong phạm vi 6 turns gần nhất; việc giữ toàn bộ >6 turns chờ F12).
- ✅ **Trí nhớ đa lượt của AI**: Hàm `store.history(customer, cid)` trích xuất 6 turns gần nhất qua `SELECT ... LIMIT 6` từ DB để gửi kèm vào prompt cho mô hình LLM khi gọi `/api/chat`.
- ✅ **API lấy toàn văn hội thoại**: Tuyến API `GET /api/conversations/{id}/messages` (và `GET /api/staff/conversations/{id}/messages`) trong `retailops/http/routes.py` cho phép đọc toàn bộ danh sách `turns` và `feedbacks` với cơ chế bảo mật kiểm tra quyền sở hữu khách hàng.
- ✅ **API danh sách hội thoại**: Tuyến API `GET /api/conversations` gọi `store.list_conversations(customer, limit=20)` trả về danh sách các phiên chat còn hạn kèm số lượt trao đổi (`turns_count`) và trích đoạn tin nhắn đầu tiên.
- ✅ **Kéo dài TTL hội thoại**: Hỗ trợ TTL context lên tới 7 ngày (`CONVERSATION_TTL = 7 * 86400`).

### Frontend Web Client (100%):
- ✅ **Cơ chế tự động Resume phiên gần nhất**: Trong `web/app.js`, hàm `openSession()` tự động gọi `GET /api/conversations`; nếu có phiên cũ gần nhất đã có trao đổi (`turns_count > 0`), hàm `loadConversation(id)` được kích hoạt tái tạo đầy đủ bong bóng chat.
- ✅ **Sidebar Conversation History**: Vùng lịch sử hiển thị 10 hội thoại gần nhất ở sidebar với icon, tiêu đề trích đoạn và số lượt trao đổi.
- ✅ **Hộp thoại xem toàn bộ lịch sử (`#conversation-history-dialog`)**: Bấm nút `🕒 Lịch sử` mở danh sách toàn bộ các phiên chat cũ để chuyển đổi.
- ✅ **Nút `➕ Cuộc trò chuyện mới`**: Khởi tạo phiên mới sạch sẽ bất kỳ lúc nào.

---

## 2. Minh Chứng Kiểm Thử Tự Động (Automated Verification)

Hệ thống đã bổ sung bộ kiểm thử chuyên biệt `tests/test_conversation_resume.py` bao phủ toàn bộ vòng đời và biên giới an toàn:
- `test_list_conversations_empty`: Trả về danh sách rỗng khi chưa có hội thoại.
- `test_conversation_ttl_is_7_days`: Xác thực TTL của phiên chat được đặt chuẩn 7 ngày.
- `test_resume_conversation_messages_and_transcript`: Xác thực tải lại trọn vẹn lịch sử chat và bong bóng tin nhắn.
- `test_privacy_isolation_between_customers`: Khách hàng C-002 bị từ chối (HTTP 403) khi cố đọc trộm phiên chat của C-001.

Kết quả kiểm thử: **4 / 4 tests PASS (100%)**.

---

## 3. Tiêu Chí Nghiệm Thu (Acceptance Criteria)

- [x] Khách hàng chat với bot -> F5 tải lại trang -> Lịch sử trò chuyện cũ (tối đa 6 lượt) được tự động khôi phục nguyên vẹn trên màn hình.
- [x] Gõ tiếp tin nhắn mới -> AI hiểu được ngữ cảnh của các câu trước trong cùng phiên và trả lời chuẩn xác.
- [x] Nút `[➕ Cuộc trò chuyện mới]` khởi tạo phiên hội thoại mới sạch sẽ.
- [x] Nút `[🕒 Lịch sử]` và danh sách ở sidebar hiển thị đầy đủ các cuộc trò chuyện cũ để chuyển đổi qua lại.
- [x] Quyền riêng tư: Khách hàng A tuyệt đối không xem được danh sách hay nội dung phiên chat của khách hàng B (HTTP 403).
- [x] Toàn bộ 4 test suite tự động hiện hữu (`tests/test_conversation_resume.py`) tiếp tục pass 100%.
- [ ] **Chờ F12 (PR B)**: Lưu trữ lịch sử vượt quá 6 lượt chat (7–20 turns) không bị xóa cứng khỏi DB, bảo toàn audit trail và liên kết feedback.
