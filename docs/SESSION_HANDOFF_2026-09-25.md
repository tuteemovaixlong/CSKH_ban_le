# BÁO CÁO TIẾN ĐỘ & NHẬT KÝ SỰ CỐ (SESSION HANDOFF) — 2026-09-25

> **Thời điểm ghi nhận:** 2026-09-25 00:45:12 (GMT+7 / Asia/Ho_Chi_Minh)  
> **Dự án:** RetailOps CSKH Bán Lẻ (`tuteemovaixlong/CSKH_ban_le`)  
> **Nhánh:** `main`  
> **Commit cơ sở:** `4a4f260` (`fix(workflow): remove single-tool cutoff, keep 4 model calls budget with accurate tool guidance`)  
> **Môi trường thử nghiệm:** AWS EC2 (`retailops-dev`) kết nối custom vLLM backend trên Google Colab GPU (`yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2`) qua ngrok tunnel.  
> **Mục đích tài liệu:** Lưu trữ chi tiết các lỗi vừa phát sinh trong phiên test trực tiếp, nguyên nhân kỹ thuật, tiến độ đã hoàn thành và danh mục công việc cần xử lý ngay khi mở máy lần tới.

---

## 1. Chi Tiết Các Lỗi Gặp Phải Trong Phiên Test

### Sự cố 1: Lỗi `tool_response_failed` ("Chưa thể xác minh kết quả tra cứu.")
- **Thao tác người dùng:** Gửi ảnh chiếc quần tây (`Screenshot 2026-09-24 234028.png`) kèm câu hỏi *"có đơn nào mua cái này chưa"*.
- **Chi tiết kỹ thuật từ Trace:**
  - **Mã lượt:** `66ae62a4-b3bb-4eee-be72-acfc65be36d6`
  - **HTTP Status:** `503`
  - **Lỗi:** `{"error":"tool_response_failed","message":"Chưa thể xác minh kết quả tra cứu."}`
  - **Số lượt gọi model:** `3` | **Thời gian xử lý:** `20.197 s`
  - **Chuỗi công cụ:** `list_orders (ok)` -> `get_order (ok)` -> `prepare_cancellation (error: tool_not_allowed)`.
- **Nguyên nhân gốc rễ (Root Cause):**
  1. Sau khi gọi `list_orders` và `get_order`, model Gemma-4 tự ý gọi thêm công cụ `prepare_cancellation` (vốn là công cụ thuộc `dispute_agent`, không nằm trong danh mục công cụ cho phép `_ALLOWED` của `order_agent`).
  2. Hệ thống ghi nhận `prepare_cancellation` bị lỗi `tool_not_allowed` và kích hoạt hàm tổng hợp dự phòng `_synthesize_order_response`.
  3. Trong hàm `_synthesize_order_response`, việc xử lý các trường hợp kết hợp (vừa có `list_orders`, vừa có `get_order` đã bị khử trùng lặp, vừa có `tool_not_allowed`) đã rơi vào nhánh trả về `return None`.
  4. Do `render(records)` trả về `None`, `read_worker.py` quăng ngoại lệ `AgentError('tool_response_failed', 'Chưa thể xác minh kết quả tra cứu.')`, làm đứt phiên với HTTP 503.

---

### Sự cố 2 & 3: Lỗi `api_unavailable` ("Không nhận được phản hồi hợp lệ từ model. Vui lòng thử lại.")
- **Thao tác người dùng:**
  - Lượt 1: Gõ lệnh *"check giúp tôi đơn O0819127"* (nhập nhầm số `0` thay vì dấu gạch nối `-`).
  - Lượt 2: Gõ lệnh *"check giúp tôi đơn O-819127"*.
- **Chi tiết kỹ thuật từ Trace:**
  - **Mã lượt 1:** `630eb246-e20c-4792-a26c-8011cb3da363` | **Độ trễ:** `372.41 ms` | `routing_reason: witty_general_fallback`
  - **Mã lượt 2:** `971815c5-4c6e-43b8-a9f4-043a59126dfb` | **Độ trễ:** `361.50 ms` | `routing_reason: order_or_product_keywords`
  - **Lỗi:** `{"error":"api_unavailable","message":"Không nhận được phản hồi hợp lệ từ model. Vui lòng thử lại.","model_errors":[{"code":"api_unavailable","call":1}]}`
- **Nguyên nhân gốc rễ (Root Cause):**
  1. **Mất kết nối máy chủ model (Upstream Outage):** Độ trễ chỉ mất ~360ms đã lập tức trả về lỗi. Điều này chứng minh tunnel ngrok hoặc phiên notebook chạy vLLM trên Google Colab đã bị ngắt kết nối (Colab timeout, ngrok session expired hoặc kernel GPU bị crash).
  2. **Vấn đề định tuyến khi gõ sai mã đơn:**
     - Khi gõ `O0819127` (số `0`), regex trong `supervisor.py` (`r'\b(o-\d+|dh\d+|\d{5,})\b'`) không nhận diện được đây là mã đơn, dẫn đến câu hỏi bị đẩy sang `witty_general_fallback`.
     - Sau đó cả 2 cuộc gọi đều gặp sự cố ngắt kết nối API ngrok nên quăng lỗi `api_unavailable`.

---

## 2. Tiến Độ Đã Đạt Được Trước Khi Tạm Dừng

1. **Routing đa phương thức & tệp đính kèm:**
   - Hoàn thiện nhận diện trường `attachment` và các cụm từ chỉ ảnh (`đọc ảnh`, `xem ảnh`, `món này`, `món đó`) trong `retailops/workflow/supervisor.py`.
2. **Khắc phục lỗi vLLM Tools Payload:**
   - Trong `retailops_providers.py`, đã sửa logic để không gửi trường `tools` khi `allow_tools=False` cho custom vLLM endpoint, tránh lỗi `agent_budget_exceeded` do chat template của Gemma-4 tự động chèn `[AVAILABLE_TOOLS]`.
3. **Mở rộng thời gian xử lý:**
   - Tăng timeout của worker từ `30s` lên `60s` trong `retailops/workflow/graph.py` và `retailops/workflow/subagents/order_agent.py`.
4. **Kiểm thử tự động:**
   - Đạt 357/357 unit tests PASS, Ops Console 19/19 tests PASS, Docs Contract 100% hợp lệ.

---

## 3. Danh Mục Công Việc Cần Xử Lý Trong Phiên Kế Tiếp

Ngay khi mở máy để tiếp tục dự án, cần thực hiện theo các bước sau:

### Bước 1: Khởi động lại Colab GPU & Cập nhật ngrok endpoint
1. Mở notebook Colab chạy vLLM với model `yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2`.
2. Lấy URL tunnel ngrok mới (dạng `https://xxxx.ngrok-free.app/v1/chat/completions`).
3. Chạy lệnh cập nhật cấu hình API trên EC2:
   ```bash
   sudo python3 scripts/update_ec2.py --api-endpoint "https://xxxx.ngrok-free.app/v1/chat/completions"
   ```

### Bước 2: Khắc phục Sự cố 1 (Bảo vệ hàm tổng hợp & chặn `prepare_cancellation`)
1. **Trong `retailops/workflow/subagents/order_agent.py`:**
   - Thêm quy định cấm gọi `prepare_cancellation` trong `ORDER_SYSTEM_PROMPT`:
     *"Never call prepare_cancellation; cancellation requests are handled exclusively by dispute specialist."*
   - Củng cố hàm `_synthesize_order_response`: Không bao giờ được phép `return None` nếu trong `tool_results` đã có ít nhất một công cụ thành công (như `list_orders` hoặc `get_order`). Bỏ qua các công cụ phụ bị lỗi `tool_not_allowed` thay vì làm hỏng toàn bộ chuỗi tổng hợp.
2. **Trong `retailops/workflow/subagents/read_worker.py`:**
   - Đảm bảo khi một công cụ bị `tool_not_allowed`, nếu trước đó đã có kết quả hợp lệ từ `list_orders` hoặc `get_order`, hệ thống tiếp tục ưu tiên kết xuất dữ liệu đã xác minh thay vì ném lỗi `tool_response_failed`.

### Bước 3: Tăng cường Regex nhận diện mã đơn trong Supervisor
- Cập nhật regex trong `retailops/workflow/supervisor.py`:
  - Cho phép nhận diện cả `O0819127`, `O-819127`, `o819127`:
    ```python
    has_specific_oid = bool(re.search(r'\b(o[-0-9]\d{5,}|o\d{6,}|dh\d+|\d{5,})\b', lower_msg))
    ```
  - Giúp hệ thống vẫn định tuyến chuẩn xác vào `order_agent` kể cả khi khách gõ nhầm dấu gạch nối thành số 0.

### Bước 4: Kiểm thử End-to-End & Xác nhận trên EC2
- Kiểm tra kịch bản:
  1. Gửi ảnh quần tây + *"có đơn nào mua cái này chưa"*.
  2. Gõ *"check giúp tôi đơn O0819127"* (gõ sai) và *"check giúp tôi đơn O-819127"* (gõ đúng).
- Xác nhận phản hồi hiển thị mượt mà trên giao diện Web.
