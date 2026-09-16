# Kế hoạch Thu thập Dữ liệu & Vòng lặp Phản hồi Người dùng (Data Flywheel)

> [!IMPORTANT]
> **Ưu tiên Triển khai: GIAI ĐOẠN 1 (Phục vụ Khóa luận Tốt nghiệp — Bước 1)**  
> Đây là hạng mục ưu tiên thực hiện ngay trước thềm bảo vệ khóa luận. Cơ chế thu thập phản hồi người dùng (CSAT, Like/Dislike) và lưu vết can thiệp của tư vấn viên (Human Handoff) sẽ là minh chứng quan trọng cho tính năng **Human-in-the-loop** và vòng lặp tự hoàn thiện hệ thống trong **Chương 3 (Thiết kế Kiến trúc Hệ thống)** của Luận văn tốt nghiệp.

Tài liệu này xác định kiến trúc và lộ trình triển khai hệ thống thu thập dữ liệu hội thoại, phản hồi chất lượng (CSAT, Like/Dislike) và dữ liệu can thiệp của tư vấn viên để phục vụ quá trình tinh chỉnh (Fine-tuning) và tối ưu hóa theo sở thích (RLHF / DPO).

---

## 1. Mục tiêu và Bối cảnh

* **Hiện trạng**: Hệ thống RetailOps đã lưu trữ toàn bộ các lượt trò chuyện thô trong bảng `agent_turns` và sự kiện trong `business_events`. Tuy nhiên, chưa có nhãn chất lượng (tốt/xấu) do người dùng gán và popup đánh giá CSAT khi kết thúc phiên chưa được kết nối API lưu trữ.
* **Mục tiêu**:
  1. Ghi nhận đánh giá CSAT (1–5 sao) và nhận xét khi người dùng kết thúc phiên.
  2. Bổ sung nút phản hồi nhanh (👍 Thích / 👎 Chưa hài lòng) trên từng bong bóng tin nhắn của AI.
  3. Ghi nhận cặp dữ liệu Human Handoff (khi tư vấn viên can thiệp sửa câu trả lời của AI) để làm tập dữ liệu huấn luyện DPO (Direct Preference Optimization).
  4. Cung cấp công cụ tự động trích xuất và làm sạch dữ liệu thành file `.jsonl` chuẩn fine-tuning.

---

## 2. Thiết kế Cơ sở Dữ liệu

### 2.1. PostgreSQL DDL (`retailops/storage/pg_schema.py`)

Bổ sung bảng `conversation_feedback` trong schema `business`:

```sql
CREATE TABLE IF NOT EXISTS conversation_feedback (
    id BIGSERIAL PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_id BIGINT REFERENCES agent_turns(id) ON DELETE SET NULL,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    feedback_type TEXT NOT NULL CHECK(feedback_type IN ('turn_rating', 'session_csat', 'human_handoff')),
    rating INTEGER CHECK(rating BETWEEN 1 AND 5),
    sentiment_flag TEXT CHECK(sentiment_flag IN ('positive', 'negative', 'neutral')),
    reason_code TEXT,
    comment TEXT,
    created_at DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_conv ON conversation_feedback(conversation_id);
CREATE INDEX IF NOT EXISTS idx_feedback_type ON conversation_feedback(feedback_type);
```

---

## 3. Thiết kế API Backend

Bổ sung endpoint nhận phản hồi trong `retailops/http/routes.py`:

* **Endpoint**: `POST /api/feedback`
* **Xác thực**: Kiểm tra session cookie và `customer_id` hợp lệ.
* **Payload Request**:
  ```json
  {
    "conversation_id": "c1a2b3c4-...",
    "turn_id": 128,
    "feedback_type": "turn_rating",
    "sentiment_flag": "negative",
    "reason_code": "wrong_tool_argument",
    "comment": "Bot tra cứu sai mã đơn hàng"
  }
  ```
* **Payload CSAT Session Request**:
  ```json
  {
    "conversation_id": "c1a2b3c4-...",
    "feedback_type": "session_csat",
    "rating": 5,
    "comment": "Hỗ trợ rất nhanh và chuẩn xác!"
  }
  ```

---

## 4. Cải tiến Giao diện Người dùng (UI)

1. **Popup Kết thúc phiên (`web/index.html` & `web/app.js`)**:
   - Khi bấm "Kết thúc phiên" và chọn số sao (1–5 sao), hàm `confirmEndSession()` sẽ gọi `api('/api/feedback', ...)` để lưu lại điểm CSAT vào cơ sở dữ liệu.
2. **Nút Like / Dislike trên tin nhắn AI**:
   - Dưới mỗi phản hồi của AI (Assistant Message), bổ sung hai nút biểu tượng nhỏ: 👍 và 👎.
   - Khi bấm 👎, hiển thị popover nhanh cho phép chọn lý do:
     - `Thông tin chưa chính xác`
     - `Chưa hiểu câu hỏi`
     - `Thái độ chưa phù hợp`
     - `Khác (nhập phản hồi ngắn)`
   - Gửi ngay dữ liệu về backend và vô hiệu hóa nút sau khi đã bình chọn.

---

## 5. Pipeline Xuất Dữ liệu Huấn luyện (`scripts/export_tuning_dataset.py`)

Tạo script tự động phân loại và xuất 2 tập dữ liệu phục vụ huấn luyện:

1. **Tập SFT (Supervised Fine-Tuning - `sft_dataset.jsonl`)**:
   - Lọc các turn từ `agent_turns` thỏa mãn:
     - Nhận được 👍 từ người dùng, HOẶC
     - Thuộc phiên có CSAT >= 4 sao và không bị lỗi hệ thống.
   - Định dạng xuất:
     ```json
     {
       "messages": [
         {"role": "system", "content": "..."},
         {"role": "user", "content": "Kiểm tra đơn hàng ORD-100"},
         {"role": "assistant", "content": null, "tool_calls": [{"function": {"name": "track_shipment", "arguments": {"order_id": "ORD-100"}}}]}
       ]
     }
     ```
2. **Tập DPO (Direct Preference Optimization - `dpo_dataset.jsonl`)**:
   - Lọc các turn nhận được 👎 hoặc kích hoạt Human Handoff:
     - `prompt`: Câu hỏi của khách hàng.
     - `rejected`: Câu trả lời lỗi hoặc chưa đạt của AI.
     - `chosen`: Câu trả lời được tư vấn viên hỗ trợ sửa lại hoặc mẫu chuẩn hóa được phê duyệt.

---

## 6. Kế hoạch Triển khai (Checklist)

- [ ] Cập nhật DDL migration trong [retailops/storage/pg_schema.py](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/retailops/storage/pg_schema.py).
- [ ] Thêm phương thức `record_feedback()` vào [retailops/business/store.py](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/retailops/business/store.py).
- [ ] Thêm route `/api/feedback` vào [retailops/http/routes.py](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/retailops/http/routes.py).
- [ ] Gắn listener và icon Like/Dislike vào hàm render tin nhắn trong [web/app.js](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/web/app.js).
- [ ] Kết nối API lưu CSAT khi bấm kết thúc phiên.
- [ ] Xây dựng script `scripts/export_tuning_dataset.py` và viết unit test kiểm định.
