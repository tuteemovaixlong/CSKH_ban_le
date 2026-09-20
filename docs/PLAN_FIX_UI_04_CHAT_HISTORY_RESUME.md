# Module 4: Khôi Phục Lịch Sử Chat & Hội Thoại Tiếp Diễn (Chat History Resume & Session Memory)

> **Mục tiêu**: Cho phép khách hàng và nhân viên khi tải lại trang (F5) hoặc mở lại phiên làm việc có thể tải lại toàn bộ lịch sử trò chuyện cũ, xem lại các bong bóng chat và gửi tin nhắn tiếp nối mạch suy nghĩ của Trợ lý AI (Multi-turn Persistent Memory).

---

## 1. Phân Tích Hiện Trạng: Đã Làm Đến Đâu?

### Những gì Backend ĐÃ CÓ sẵn (~70%):
- ✅ **Bảng lưu trữ đa lượt**: Bảng `conversations` và `agent_turns` trong SQLite/PostgreSQL đã lưu đầy đủ `messages` (JSON prompt, user message, tool calls, tool results) và `result` của từng lượt trò chuyện.
- ✅ **Trí nhớ đa lượt của AI**: Hàm `store.history(customer, cid)` đã có sẵn logic trích xuất 6 turns gần nhất để gửi kèm vào prompt cho mô hình LLM khi gọi `/api/chat`. AI đã có khả năng nhớ ngữ cảnh các câu trước trong cùng một `conversation_id`.
- ✅ **API lấy toàn văn hội thoại**: Tuyến API `GET /api/conversations/{id}/messages` (và `GET /api/staff/conversations/{id}/messages`) đã được viết sẵn trong [`retailops/http/routes.py`](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/retailops/http/routes.py), cho phép đọc toàn bộ danh sách `turns` và `feedbacks` với cơ chế bảo mật kiểm tra quyền sở hữu của khách hàng.

### Những gì CHƯA LÀM (Điểm nghẽn khiến lịch sử bị mất):
- ❌ **Backend thiếu endpoint liệt kê hội thoại**: Chưa có route `GET /api/conversations` để lấy danh sách các phiên chat gần đây của khách hàng.
- ❌ **Frontend luôn xóa trắng khi load trang**: Trong [`web/app.js`](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/web/app.js), mỗi lần đăng nhập hoặc F5, hàm `openSession()` luôn gọi `await newConversation()` $\to$ sinh một `conversation_id` ngẫu nhiên mới và gọi `byId('messages').replaceChildren()` xóa sạch toàn bộ bong bóng chat trên màn hình!
- ❌ **Chưa có UI xem và chọn phiên chat cũ**: Chưa có thanh lịch sử hội thoại (Conversation Drawer / History List) để người dùng bấm chuyển đổi giữa các cuộc trò chuyện cũ.

---

## 2. Giải Pháp Tích Hợp Vào Đợt Cải Tổ

### 2.1. Tầng Backend API
1. **Bổ sung route `GET /api/conversations`**:
   - Truy vấn danh sách các phiên chat của khách hàng hiện tại từ bảng `conversations` kèm số lượt trao đổi (`turns_count`) và đoạn trích tin nhắn đầu tiên (`first_message_snippet`).
   - Sắp xếp theo thời gian hoạt động gần nhất (`last_activity DESC`).
2. **Kéo dài thời hạn hội thoại (TTL Context)**:
   - Hiện tại `expires_at = time.time() + 1800` (30 phút). Nâng lên 7 ngày đối với các phiên có tài khoản persistent để khách hàng quay lại sau nhiều ngày vẫn có thể chat tiếp.

### 2.2. Tầng Frontend Web Client (`web/app.js` & `web/index.html`)
1. **Cơ chế tự động Resume phiên gần nhất khi mở trang**:
   - Trong `openSession()`:
     - Gọi `GET /api/conversations` để kiểm tra các phiên chat gần đây của tài khoản.
     - Nếu có phiên chat cũ gần nhất: Tự động tải lại phiên đó bằng `loadConversation(recentConv.id)`:
       - Gọi `GET /api/conversations/{id}/messages` lấy toàn bộ turns.
       - Tái hiện lại toàn bộ bong bóng chat người dùng và AI lên màn hình (`renderTranscript()`).
       - Gán `conversationId = recentConv.id`.
     - Nếu chưa có phiên nào: Mới tạo `newConversation()`.
2. **Thêm ngăn xem lịch sử chat (`#chat-history-drawer` hoặc modal danh sách)**:
   - Thêm nút `[🕒 Lịch sử chat]` trên thanh tiêu đề hộp chat.
   - Bấm vào mở danh sách các phiên chat cũ (ví dụ: *"Hỏi về áo sơ mi P-101 (3 tin nhắn) · 2 giờ trước"*).
   - Bấm chọn phiên nào thì màn hình lập tức nạp lại nội dung phiên đó và cho phép gõ phím chat tiếp!
3. **Giữ nút `[➕ Cuộc trò chuyện mới]`**:
   - Khi người dùng muốn bắt đầu chủ đề mới toanh, bấm nút này để tạo phiên mới như bình thường.

---

## 3. Kế Hoạch Chỉnh Sửa File

### [MODIFY] [retailops/business/store.py](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/retailops/business/store.py)
- Thêm hàm `list_conversations(self, customer, limit=10)`:
  - Truy vấn bảng `conversations` kết hợp `agent_turns` lấy danh sách các phiên chat còn hiệu lực của khách hàng.

### [MODIFY] [retailops/http/routes.py](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/retailops/http/routes.py)
- Thêm xử lý `GET /api/conversations`:
  ```python
  if path == "/api/conversations":
      return (200, {"conversations": app.store.list_conversations(customer)})
  ```

### [MODIFY] [web/app.js](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/web/app.js)
- Thêm hàm `resumeConversation(cid)`:
  - Gọi `GET /api/conversations/{cid}/messages`.
  - Duyệt qua `turns`, parse `messages` và gọi hàm `message(...)` dựng lại bong bóng chat.
- Cập nhật `openSession()`: Tự động khôi phục phiên chat gần nhất thay vì ép tạo mới.
- Thêm xử lý sự kiện bấm chọn cuộc trò chuyện cũ trong danh sách lịch sử.

### [MODIFY] [web/index.html](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/web/index.html)
- Bổ sung nút `🕒 Lịch Sử` cạnh nút `➕ Cuộc trò chuyện mới` trên header khung chat.
- Thêm dialog / popover danh sách các cuộc hội thoại cũ (`#conversation-history-dialog`).

---

## 4. Tiêu Chí Nghiệm Thu (Acceptance Criteria)
- [ ] Khách hàng chat 3 câu với bot -> Bấm F5 tải lại trang -> Toàn bộ 3 câu hỏi và câu trả lời vẫn hiển thị nguyên vẹn trên màn hình.
- [ ] Gõ tiếp câu thứ 4 (ví dụ: *"Thế còn màu trắng thì sao?"*) -> AI hiểu được ngữ cảnh của 3 câu trước và trả lời chính xác.
- [ ] Bấm nút `[➕ Cuộc trò chuyện mới]` -> Màn hình bắt đầu phiên mới sạch sẽ.
- [ ] Bấm nút `[🕒 Lịch sử]` -> Danh sách hiện ra cả 2 phiên chat cũ và mới; bấm vào phiên nào thì load lại phiên đó.
- [ ] Quyền riêng tư: Khách hàng A tuyệt đối không xem được danh sách hay nội dung phiên chat của khách hàng B.
