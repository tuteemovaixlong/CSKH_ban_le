# Kế hoạch Tích hợp Tính năng Gửi File & Hình ảnh (Multimodal Vision & Attachment Support) cho Trợ lý AI

> [!IMPORTANT]
> **Ưu tiên Triển khai Cao: Xử lý Đa phương thức (Multimodal AI) trong CSKH Bán lẻ**  
> Khách hàng mua sắm online thường xuyên cần gửi hình ảnh chụp thực tế: **sản phẩm lỗi/rách, sai màu/kích cỡ, hóa đơn bưu điện, mã vạch đơn hàng** hoặc gửi tài liệu phiếu bảo hành (PDF). Trợ lý AI cần có khả năng "nhìn" và phân tích hình ảnh này để giải quyết khiếu nại nhanh chóng hoặc đính kèm bằng chứng chuyển giao cho nhân viên CSKH (Staff Desk).

---

## 1. Mục tiêu & Các Kịch bản Nghiệp vụ (Use Cases)

1. **Khiếu nại sản phẩm lỗi / sai hàng (Product Defect & Return Claim)**:
   - Khách chụp ảnh áo bị rách chỉ, hộp giày bị móp méo, hoặc sản phẩm sai màu.
   - AI (Gemini Vision) nhận diện hình ảnh, xác thực tình trạng hư hỏng, ghi nhận vào hồ sơ và hướng dẫn khách quy trình đổi trả/bảo hành.
2. **Đọc mã vận đơn / Hóa đơn bưu điện từ ảnh chụp (OCR & Visual Tracking)**:
   - Khách chụp phiếu gửi hàng GHTK/GHN/VNPost hoặc hóa đơn mua hàng.
   - AI đọc mã vận đơn từ ảnh và tự động gọi công cụ `track_shipment` để báo tiến độ giao hàng.
3. **Tìm kiếm & Tư vấn sản phẩm qua hình ảnh (Visual Search)**:
   - Khách gửi ảnh mẫu quần áo/giày dép yêu thích, AI phân tích kiểu dáng, màu sắc và gợi ý sản phẩm phù hợp trong danh mục của cửa hàng.
4. **Lưu trữ bằng chứng đồng bộ sang Bàn làm việc Nhân viên (Staff Desk)**:
   - Khi ca hỗ trợ được chuyển giao (Human Escalation), ảnh khách gửi sẽ hiển thị trực quan trong lịch sử chat trên màn hình của chuyên viên CSKH để nhân viên có ngay bằng chứng đối soát mà không cần bắt khách gửi lại.

---

## 2. Kiến trúc Kỹ thuật (Technical Architecture)

```mermaid
flowchart TD
    User["Khách hàng (Web App / Mobile)"] -->|1. Chọn ảnh / Kéo thả / Dán Ctrl+V| UI["Giao diện Chat Khách hàng"]
    UI -->|2. Preview thumbnail + Nén ảnh client-side| Encoder["Base64 Data URI (Mime: JPEG/PNG/WebP/PDF)"]
    Encoder -->|3. POST /api/chat kèm attachment| Router["Public Web API (/api/chat)"]
    
    Router -->|4. Kiểm tra kích thước & mime type <= 4MB| Validation["Security & Size Guard"]
    Validation --> Storage["Lưu vết đính kèm vào Database (conversations/turns)"]
    
    Validation --> Dispatcher{"Model Routing"}
    Dispatcher -->|Google Gemini API (gemini-2.5-flash)| GeminiVision["Gemini Multimodal Vision\n(inlineData / image_url)"]
    Dispatcher -->|Anthropic Claude API| ClaudeVision["Claude Multimodal\n(type: image / document)"]
    Dispatcher -->|Custom Text-only Model| Fallback["Ghi nhận file + Chuyển giao Staff Desk"]
    
    GeminiVision --> Response["AI phân tích ảnh & Trả lời chi tiết"]
    Response --> UI
    Storage --> StaffDesk["🎧 Bàn làm việc Chuyên viên CSKH (Staff Desk) hiển thị ảnh bằng chứng"]
```

---

## 3. Thiết kế Giao diện Người dùng (UI/UX Design)

### 3.1. Khung nhập tin nhắn Khách hàng
- Thêm nút **📎 Kẹp ghim (Đính kèm tệp)** và **📷 Máy ảnh** cạnh ô nhập tin nhắn.
- Hỗ trợ:
  - Bấm nút để chọn file từ máy tính/điện thoại (`.jpg`, `.jpeg`, `.png`, `.webp`, `.pdf`).
  - **Dán trực tiếp ảnh từ clipboard (`Ctrl + V`)** cực kỳ tiện lợi khi chụp màn hình.
  - Kéo thả file trực tiếp vào khung chat (**Drag & Drop**).
- Thanh hiển thị trước (**Attachment Preview Bar**) nằm ngay trên ô nhập văn bản:
  - Thumbnail ảnh thu nhỏ.
  - Tên file và dung lượng (VD: `ao_rach.jpg (1.2 MB)`).
  - Nút **✕ Hủy đính kèm** để xóa nhanh nếu chọn nhầm.

### 3.2. Hiển thị trong Bong bóng Chat (Chat Transcript)
- Tin nhắn của khách hiển thị thumbnail ảnh rõ nét, bo góc mềm mại, có viền đổ bóng nhẹ.
- Nhấp chuột vào ảnh sẽ mở **Lightbox xem ảnh phóng to đầy đủ (Full-size Image Viewer)**.

### 3.3. Hiển thị trên Bàn làm việc Chuyên viên CSKH (Staff Desk)
- Trong cột hội thoại của Staff Desk, hình ảnh khách gửi được giữ nguyên vị trí thời gian thực.
- Chuyên viên CSKH có thể nhấp vào để kiểm tra chi tiết vết rách/mã bưu cục trước khi bấm **"✓ Hoàn tất ca & Đóng"**.

---

## 4. Đặc tả API & Payload Backend

### 4.1. Request `POST /api/chat`
```json
{
  "conversation_id": "c1a2b3c4-d5e6-7f8a-9b0c-1d2e3f4a5b6c",
  "request_id": "req-9876543210abcdef",
  "text": "Shop ơi, áo này tôi nhận về bị rách một đường dài ở nách áo, shop xem giúp tôi với.",
  "attachment": {
    "type": "image",
    "name": "ao_loi_rach_nach.jpg",
    "mime_type": "image/jpeg",
    "data": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD..."
  }
}
```

### 4.2. Giới hạn An toàn (Security & Resource Boundaries)
- **Kích thước tối đa**: 4 MB (đảm bảo không làm nghẽn băng thông HTTP).
- **Định dạng cho phép**: `image/jpeg`, `image/png`, `image/webp`, `image/gif`, `application/pdf`.
- **Tự động nén ảnh**: JavaScript client-side tự động canvas-resize nếu ảnh chụp bằng camera điện thoại có độ phân giải quá cao (> 1920px), giữ cho payload nhẹ (~200KB - 800KB) giúp gửi siêu nhanh.

---

## 5. Tích hợp Multimodal Provider

### 5.1. Google Gemini Endpoint (`GOOGLE_ENDPOINT`)
Gemini hỗ trợ cấu trúc OpenAI-compatible `image_url`:
```json
{
  "role": "user",
  "content": [
    {
      "type": "text",
      "text": "Shop ơi, áo này tôi nhận về bị rách một đường dài ở nách áo..."
    },
    {
      "type": "image_url",
      "image_url": {
        "url": "data:image/jpeg;base64,/9j/4AAQSkZJRg..."
      }
    }
  ]
}
```

### 5.2. Anthropic Claude Endpoint
Chuyển đổi sang Content Block chuẩn của Anthropic:
```json
{
  "role": "user",
  "content": [
    {
      "type": "text",
      "text": "Shop ơi, áo này tôi nhận về bị rách..."
    },
    {
      "type": "image",
      "source": {
        "type": "base64",
        "media_type": "image/jpeg",
        "data": "/9j/4AAQSkZJRg..."
      }
    }
  ]
}
```

---

## 6. Kế hoạch Kiểm thử & Xác nhận (Verification)

1. **Unit Tests**:
   - `test_multimodal_payload_validation`: Kiểm tra validate kích thước, mime type và cấu trúc base64.
   - `test_gemini_multimodal_translation`: Kiểm tra bộ chuyển dịch `translate()` sinh ra đúng cấu trúc `image_url` cho Gemini.
   - `test_attachment_storage_and_transcript`: Kiểm tra lưu trữ và lấy lại ảnh đính kèm trong lịch sử hội thoại.
2. **Kiểm thử Trực quan (E2E Manual Verification)**:
   - Mở giao diện chat, dán một ảnh chụp sản phẩm từ clipboard hoặc bấm nút đính kèm 📎.
   - Gửi tin nhắn kèm ảnh tới Gemini: Kiểm tra bot phản hồi chính xác nội dung trong ảnh (màu sắc, vật thể, tình trạng hư hại).
   - Mở Bàn làm việc Chuyên viên CSKH (Staff Desk): Kiểm tra ảnh hiển thị sắc nét trong khung hội thoại của nhân viên.
