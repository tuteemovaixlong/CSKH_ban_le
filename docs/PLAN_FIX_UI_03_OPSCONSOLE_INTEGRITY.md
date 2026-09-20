# Module 3: Ops Console Observability, Benchmark Importer & Telemetry Integrity (P1)

> **Mục tiêu**: Chuẩn hóa toàn diện đường ống đo lường của Ops Console theo đúng tôn chỉ *"Kết quả đo được, không phải số minh họa"*; loại bỏ việc tự suy diễn/ước lượng token, loại bỏ số liệu hard-code cũ ngày 18/09, chuẩn hóa tên gọi E2E Latency và mở rộng phạm vi theo dõi Feedback.

---

## 1. Các Vấn Đề Cốt Lõi Được Giải Quyết

1. **Chuẩn hóa hàm `import_benchmark()` trong [`opsconsole/evaluation.py`](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/opsconsole/evaluation.py)**:
   - Hiện tại:
     - Tự tính token bằng độ dài ký tự: `prompt_tokens = len(user_text) // 3`, `generated_tokens = len(response) // 3` -> Đây là số giả định, không phải token thật!
     - Tự gán chi phí: `reported_cost_usd = 0.0` -> Vi phạm nguyên tắc "Chi phí chưa đo phải là Unknown/None, không được tự ý gán bằng $0".
     - Tự gán model & provider: `provider: 'custom'`, `model: 'qwen2.5:4b'` -> Không phản ánh đúng model chạy thật (Hệ thống hiện tại đang sử dụng mô hình self-hosted `yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2` qua vLLM Colab L4 hoặc OpenRouter API).
     - Đặt cứng run_id: `'live-benchmark-240-' + ts` trong khi bộ dữ liệu chuẩn là 250 kịch bản.
   - Khắc phục:
     - Đọc token telemetry trực tiếp từ `c.get('trace', {}).get('prompt_tokens')` hoặc `c.get('tokens')`; nếu báo cáo không có thì để `None` (Unknown) chứ không chia 3.
     - Đọc model & provider trực tiếp từ metadata của file báo cáo gốc (`doc.get('model')`, `doc.get('provider')`), phản ánh đúng mô hình Gemma-4-12B đang chạy thực tế thay vì hard-code Qwen.
     - Đặt `reported_cost_usd = c.get('cost') or None`.
     - Sinh run_id tự động dựa trên số ca thực tế: `f"live-benchmark-{len(cases)}-{ts}"`.

2. **Loại bỏ chuỗi tĩnh/fallback cũ trong [`opsconsole/web/admin.js`](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/opsconsole/web/admin.js)**:
   - Hiện tại: Trong hàm `showRun()`, các thẻ card hiển thị copy tĩnh từ bản báo cáo ngày 18/09 (`(94.6%)`, `3.96s`, `8.28s`, `Qwen 2.5 4B`, `Phát hiện 3 ca bẫy tool`).
   - Khắc phục:
     - Thẻ Tỷ lệ thành công: Hiển thị `${fmt(m.passed)} / ${fmt(m.cases)} ca (${pct(m.case_pass_rate)})`.
     - Thẻ Độ trễ: Đổi tên nhãn từ **"Độ trễ TTFT p50"** thành **"Độ trễ E2E Request (p50)"** (vì hệ thống đo thời gian trọn vẹn của HTTP request, chưa phải streaming Time To First Token).
     - Subtext mô hình: Đọc từ `activeRun.manifest?.model || activeRun.manifest?.provider || 'Mô hình phục vụ'`.
     - Thẻ An toàn: Hiển thị tỷ lệ đạt chuẩn của nhóm `safety` từ dữ liệu thật (`m.by_category?.safety?.pass_rate`).

3. **Chuẩn hóa Failure Explorer**:
   - Hiện tại: Phân loại nhầm `isJailbreak = (tools_called.length > 0) || ...` và gắn mô tả cố định về đơn hàng C-002.
   - Khắc phục: Phân loại dựa trên cấu trúc lỗi thật của kịch bản (`c.category === 'safety'`, hoặc c.error chứa `forbidden_tool`), hiển thị lỗi thực tế do validator trả về.

4. **Bổ sung các sự kiện mới vào Allowlist của [`opsconsole/usage.py`](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/opsconsole/usage.py)**:
   - Hiện tại: Chỉ ghi nhận các sự kiện cũ, bỏ sót `feedback_received` (CSAT, turn rating) và `order_status_updated_by_manager`, khiến chúng bị đẩy vào nhóm `other_event`.
   - Khắc phục: Mở rộng `ALLOWLISTED_EVENTS` để Ops Console ghi nhận đầy đủ telemetry về mức độ hài lòng của người dùng và các thao tác điều hành của Store Manager.

---

## 2. Kế Hoạch Chỉnh Sửa File

### [MODIFY] [opsconsole/evaluation.py](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/opsconsole/evaluation.py)
- Sửa hàm `import_benchmark(source)`:
  - Lấy `model = doc.get('model') or doc.get('provider_id') or 'custom'`
  - Lấy `provider = doc.get('provider') or 'custom'`
  - Đọc `prompt_tokens`, `generated_tokens`, `cost` nếu có trong trace, nếu không giữ `None`.
  - Cập nhật định dạng `run_id`.

### [MODIFY] [opsconsole/web/admin.js](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/opsconsole/web/admin.js)
- Sửa hàm `showRun()`:
  - Thay thế toàn bộ chuỗi hard-code bằng dữ liệu động từ `activeRun`.
  - Cập nhật nhãn "Độ trễ E2E (p50)" thay cho "TTFT".
  - Hiển thị Failure Explorer chính xác theo lỗi và category.

### [MODIFY] [opsconsole/usage.py](file:///d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/opsconsole/usage.py)
- Thêm `feedback_received`, `order_status_updated_by_manager` vào danh mục sự kiện được phân tích.

---

## 3. Tiêu Chí Nghiệm Thu (Acceptance Criteria)
- [ ] Chạy `python scripts/check_ops_console.py` và `opsconsole/tests/test_console.py` đạt 100% OK.
- [ ] Mở Ops Console: Khi chọn bất kỳ run nào (240 ca hoặc 250 ca), thẻ hiển thị tự động lấy đúng số liệu của run đó (không còn chữ `94.6%` hay `Qwen 2.5 4B` cố định).
- [ ] Không có token giả tạo hay cost giả tạo bằng $0 trong báo cáo import.
- [ ] Nhãn độ trễ hiển thị đúng bản chất "E2E Latency".
