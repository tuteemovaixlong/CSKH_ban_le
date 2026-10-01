# Module 3: Ops Console Observability, Benchmark Importer & Telemetry Integrity (P1)

> **Trạng thái:** COMPLETED / VERIFIED (Phase 1.3 hoàn thành 100%)
> **Mức độ minh chứng (Evidence):** L1 Automated Test Baseline (`check_ops_console.py` 19 tests OK, 353/353 unit tests OK)
> **Audit basis / Documentation baseline reviewed:** `b93eb5a` · **Application verified:** `fd24e36`
> **Ngày rà soát & cập nhật:** 2026-09-24
> **Mục tiêu:** Chuẩn hóa toàn diện đường ống đo lường của Ops Console theo đúng tôn chỉ *"Kết quả đo được, không phải số minh họa"*; loại bỏ việc tự suy diễn/ước lượng token, loại bỏ số liệu hard-code cũ ngày 18/09, chuẩn hóa tên gọi E2E Latency, mở rộng phạm vi theo dõi Feedback và tích hợp đầy đủ telemetry phục vụ đo đạc concurrency.

---

## 1. Các Vấn Đề Cốt Lõi Được Giải Quyết

1. **Chuẩn hóa hàm `import_benchmark()` trong [`opsconsole/evaluation.py`](../opsconsole/evaluation.py)**:
   - Hiện tại:
     - Tự tính token bằng độ dài ký tự: `prompt_tokens = len(user_text) // 3`, `generated_tokens = len(response) // 3` -> Đây là số giả định, không phải token thật!
     - Tự gán chi phí: `reported_cost_usd = 0.0` -> Vi phạm nguyên tắc "Chi phí chưa đo phải là Unknown/None, không được tự ý gán bằng $0".
     - Tự gán model & provider: `provider: 'custom'`, `model: 'qwen2.5:4b'` -> Không phản ánh đúng model chạy thật (Hệ thống hiện tại đang sử dụng mô hình self-hosted `yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2` qua vLLM Colab L4 hoặc OpenRouter API).
     - Đặt cứng run_id: `'live-benchmark-240-' + ts` trong khi bộ dữ liệu chuẩn là 250 kịch bản.
   - Khắc phục:
     - Đọc token telemetry trực tiếp từ `c.get('trace', {}).get('prompt_tokens')` hoặc `c.get('tokens')`; nếu báo cáo không có thì để `None` (Unknown) kèm `token_usage_available = False`, không chia 3 và không tự gán 0.
     - Đọc model & provider trực tiếp từ metadata của file báo cáo gốc (`doc.get('model')`, `doc.get('provider')`), phản ánh đúng mô hình Gemma-4-12B đang chạy thực tế thay vì hard-code Qwen.
     - Đặt `reported_cost_usd = c.get('cost') or None`.
     - Sinh run_id tự động dựa trên số ca thực tế: `f"live-benchmark-{len(cases)}-{ts}"`.

2. **Loại bỏ chuỗi tĩnh/fallback cũ trong [`opsconsole/web/admin.js`](../opsconsole/web/admin.js)**:
   - Hiện tại: Trong hàm `showRun()`, các thẻ card hiển thị copy tĩnh từ bản báo cáo ngày 18/09 (`(94.6%)`, `3.96s`, `8.28s`, `Qwen 2.5 4B`, `Phát hiện 3 ca bẫy tool`).
   - Khắc phục:
     - Thẻ Tỷ lệ thành công: Hiển thị `${fmt(m.passed)} / ${fmt(m.cases)} ca (${pct(m.case_pass_rate)})`.
     - Thẻ Độ trễ: Đổi tên nhãn từ **"Độ trễ TTFT p50"** thành **"Độ trễ E2E Request (p50)"** (vì hệ thống đo thời gian trọn vẹn của HTTP request, chưa phải streaming Time To First Token).
     - Subtext mô hình: Đọc từ `activeRun.manifest?.model || activeRun.manifest?.provider || 'Mô hình phục vụ'`.
     - Thẻ An toàn: Hiển thị tỷ lệ đạt chuẩn của nhóm `safety` từ dữ liệu thật (`m.by_category?.safety?.pass_rate`).

3. **Chuẩn hóa Failure Explorer & Quy Tắc Chấm Điểm (Grader Rules)**:
   - Benchmark Producer: Script `scripts/run_live_benchmark_http.py` đóng vai trò sinh kết quả benchmark có cấu trúc chuẩn gửi tới Ops Console.
   - Loại bỏ trường `expected_worker`: Hệ thống phân luồng linh hoạt (ví dụ `order_agent` hoặc `dispute_agent` cùng có thể xử lý tra cứu vận đơn); việc ép buộc so khớp 1-1 tên worker gây false negative không đáng có. Thay vào đó, trích xuất `actual_worker` từ `subagent_history` trong execution trace.
   - Đổi tên `unexpected_tools` thành `extra_tools`: Các công cụ tra cứu bổ sung (như đọc thông tin đơn khi tư vấn) là thông tin ghi nhận phụ trợ (informational), không mặc định coi là lỗi trừ khi vi phạm ràng buộc an toàn (safety constraint).
   - Cấu trúc kết quả từng ca (`Case Result Schema`):
     `{case_id: str, category: str, success: bool, latency_ms: float, actual_worker: str, tools_called: list, extra_tools: list, error: str | null}`.
   - Phân loại lỗi Failure Explorer: Dựa trên `c.category === 'safety'` hoặc `c.error` cụ thể từ grader thay vì gán mô tả cố định.

4. **Bổ Sung Telemetry Đo Đạc Concurrency & Sửa Lỗi Hardcode Cache Trace**:
   - Khắc phục lỗi hardcode `latency_ms = 5.0` trong [retailops/business/application.py](../retailops/business/application.py) dòng 126: Thay thế bằng đo đạc thời gian thực tế `round((time.monotonic() - started) * 1000, 2)`.
   - Bổ sung các trường telemetry đo đạc concurrency vào `trace`:
     - `queue_wait_ms`: Thời gian xếp hàng chờ slot trong InferenceGate.
     - `provider_inference_ms`: Thời gian thực hiện lệnh gọi suy luận mô hình.
     - `graph_retrieval_ms`: Thời gian truy vấn Cypher trên Apache AGE.
     - `rag_retrieval_ms`: Thời gian tìm kiếm hybrid trên PostgreSQL.
     - `db_ms`: Thời gian thực thi các lệnh SQL quan hệ.
     - `model_calls`: Số lượt gọi model thực tế trong turn.
     - `in_flight_inferences`: Số lượng inference đang chạy đồng thời.
   - Bổ sung metric cấp tiến trình: `overload_429_count` ghi nhận tổng số lượt yêu cầu bị từ chối do quá tải (vì request 429 không có completed turn trong DB).

5. **Bổ sung các sự kiện mới vào Allowlist của [`opsconsole/usage.py`](../opsconsole/usage.py)**:
   - Hiện tại: Chỉ ghi nhận các sự kiện cũ, bỏ sót `feedback_received` (CSAT, turn rating) và `order_status_updated_by_manager`, khiến chúng bị đẩy vào nhóm `other_event`.
   - Khắc phục: Mở rộng `ALLOWLISTED_EVENTS` để Ops Console ghi nhận đầy đủ telemetry về mức độ hài lòng của người dùng và các thao tác điều hành của Store Manager.

---

## 2. Kế Hoạch Chỉnh Sửa File

### [MODIFY] `opsconsole/evaluation.py`
- Sửa hàm `import_benchmark(source)`:
  - Lấy `model = doc.get('model') or doc.get('provider_id') or 'custom'`
  - Lấy `provider = doc.get('provider') or 'custom'`
  - Đọc `prompt_tokens`, `generated_tokens`, `cost` nếu có trong trace, nếu không giữ `None` (kèm `token_usage_available = False`).
  - Nhận diện cấu trúc kết quả từ `scripts/run_live_benchmark_http.py`: đọc `actual_worker`, `extra_tools`, bỏ phụ thuộc vào `expected_worker`.
  - Cập nhật định dạng `run_id`.

### [MODIFY] `opsconsole/web/admin.js`
- Sửa hàm `showRun()`:
  - Thay thế toàn bộ chuỗi hard-code bằng dữ liệu động từ `activeRun`.
  - Cập nhật nhãn "Độ trễ E2E Request (p50)" thay cho "TTFT".
  - Hiển thị Failure Explorer chính xác theo lỗi và category, hiển thị `extra_tools` dưới dạng thông tin tham khảo.

### [MODIFY] `opsconsole/usage.py`
- Thêm `feedback_received`, `order_status_updated_by_manager` vào danh mục sự kiện được phân tích.

---

## 3. Tiêu Chí Nghiệm Thu (Acceptance Criteria)

- [x] Chạy `python scripts/check_ops_console.py` và `opsconsole/tests/test_console.py` đạt 100% OK (19/19 tests).
- [x] Mở Ops Console: Khi chọn bất kỳ run nào (240 ca hoặc 250 ca), thẻ hiển thị tự động lấy đúng số liệu của run đó (không còn chữ `94.6%` hay `Qwen 2.5 4B` cố định).
- [x] Không có token giả tạo hay cost giả tạo bằng $0 trong báo cáo import; token không có hiển thị `Chưa có / Unknown`.
- [x] Nhãn độ trễ hiển thị đúng bản chất "Độ trễ E2E Request".
- [x] Báo cáo benchmark phân tách rõ ràng giữa `actual_worker`, công cụ đã gọi và `extra_tools` (mang tính thông tin), không bắt buộc trường `expected_worker`.
- [x] CI/CD và 353 tests tự động tiếp tục pass 100%.
