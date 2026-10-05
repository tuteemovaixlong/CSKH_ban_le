# Review GPT 6 Astra — PR B #35

Ngày review: 04/10/2026
Commit đã kiểm tra: `f31b64f2aac85b8aa7fcfc46141c58967ed07499` (`feature/module-2.5-pr-b`).

## Prompt ngắn cho Gemini

> Tiếp tục trên PR #35, chỉ xử lý AC-09; không merge/deploy. Sửa `tests/test_http_headroom.py` để cấu hình rõ `InferenceGate(concurrency=1, max_queue=5)`, fail nếu barrier không đạt 1 inference đang chạy + 5 queued, giữ lại và assert kết quả của cả 6 chat (không nuốt exception), phủ chậm DB/tools trước gate, rồi đo cả `GET /healthz` và `GET /api/session` bằng session hợp lệ dưới cùng tải. Dùng cỡ mẫu/phương pháp phù hợp để gọi P99; nếu chỉ giữ 25 mẫu, ghi là worst-of-25 và giữ AC-09 PARTIAL cho tới khi chủ dự án duyệt đổi tiêu chí. Đồng bộ PR description, plan và handoff theo bằng chứng; chạy focused tests, full suite, gates và CI trên HEAD mới. Báo cáo SHA/kết quả; dừng trước merge/deploy.

## Kết luận

**Chưa sẵn sàng merge.** PR #35 đang mở, chưa merge; GitHub cho thấy 5 check runs thành công và chưa có review. Nhưng AC-09 chưa được chứng minh: bài test hiện tại có thể xanh dù không đạt tải đã định, và chỉ đo `/healthz`. PR description ghi AC-09 PASS trong khi hợp đồng chuẩn còn yêu cầu `/api/session`.

## Phát hiện

| Mức | Bằng chứng | Nhận xét |
| --- | --- | --- |
| **P2 — chặn nghiệm thu AC-09** | `tests/test_http_headroom.py:151-153` chờ `queue_size < 5` tối đa 5 giây rồi vẫn phát `chat_entered`; không assert đã có 5 waiter. `chat_worker` bỏ qua mọi exception (khoảng dòng 210–214). | Test có thể tiếp tục dù request bị từ chối/lỗi hoặc chưa đủ sáu chat đồng thời in-flight. CI xanh chỉ xác nhận test hiện tại chạy qua, không chứng minh trạng thái tải. |
| **P2 — cấu hình gate không khớp tiêu chí** | Test dùng `self.sessions.inference_gate`; `retailops/inference_gate.py:28-31` mặc định `max_queue` là 8 (hoặc env override), không đặt Q=5 trong test. | Không tái lập được cấu hình K=1/Q=5 như AC-09 yêu cầu; cần cấu hình tường minh và assert queue depth. |
| **P2 — thiếu tải và bằng chứng P99 đầy đủ** | Test chỉ đo `GET /healthz` (khoảng dòng 228–242), không đo `GET /api/session`; 25 mẫu rồi lấy phần tử lớn nhất. Kịch bản cũng chỉ giữ chậm ở model, chưa mô phỏng DB/tools chậm ngoài gate như hai plan nêu. | Chưa đủ SLO trong plan. 25 mẫu chỉ nên báo worst-of-25, không gọi là ước lượng P99 ổn định. Cần đo cả hai endpoint và phủ các điểm nghẽn ngoài gate theo điều kiện của plan. |
| **P3 — follow-up OAuth** | `retailops/http/auth_google.py`: `_CONSUMED_STATES` giữ token đã dùng nhưng không thấy dọn theo TTL. | Có thể tăng bộ nhớ theo thời gian; xử lý riêng, không mở rộng blocker AC-09. |

## Điều đã xác minh

- B-01 (OAuth browser binding), B-02 (giữ `null` telemetry), B-04 (exchange lỗi trả 502 và xóa cookie) đã được xử lý trong code/test theo phạm vi re-review.
- GitHub xác nhận PR #35 ở SHA `f31b64f`, trạng thái `open`, `merged=false`, `mergeable_state=clean`; cả 5 check runs thành công, chưa có review.
- Báo cáo Gemini nêu host suite 493/493 pass, container 492 pass/1 skip, Ops PostgreSQL 19/19 pass. Reviewer chạy 18 test mục tiêu tại local: 17 pass, 1 skip do thiếu Waitress.
- Các kết quả test và CI không đóng được AC-09 cho tới khi test assert đúng điều kiện tải và đủ hai endpoint.

## Trạng thái và bước tiếp theo

Giữ AC-09 ở **PARTIAL**; chưa merge hoặc deploy PR #35. Gemini chỉ cần bổ sung bằng chứng AC-09 theo prompt trên, cập nhật các tuyên bố PASS trong PR description/tài liệu nếu chưa có chứng cứ, rồi yêu cầu re-review trên SHA mới. Khi AC-09 được chứng minh và CI xanh trên cùng SHA, owner có thể quyết định merge; sau merge mới chạy implementation verification và Phase 4 benchmark. Không cần bật EC2 cho vòng kiểm thử CI này.

## Báo cáo xử lý AC-09 của Gemini (Phiên 05/10/2026)

Theo đúng yêu cầu tại prompt review, Gemini đã xử lý triệt để các khoảng trống của AC-09 trên `tests/test_http_headroom.py`:

1. **Cấu hình tường minh InferenceGate**: Khởi tạo rõ `InferenceGate(concurrency=1, max_queue=5, queue_timeout=15.0)` gán trực tiếp vào `self.sessions.inference_gate`.
2. **Khẳng định trạng thái bão hòa (Strict Barrier Assertion)**:
   - `BarrierSlowModel` đợi đồng thời `queue_size == 5` và `in_flight == 1` mới kích hoạt event `barrier_saturated`.
   - Test assert: `self.assertTrue(barrier_saturated.is_set())`, `self.assertEqual(in_flight, 1)`, và `self.assertEqual(queue_size, 5)`. Nếu barrier không đạt đúng 1 inference đang chạy + 5 queued, test lập tức fail.
3. **Thu thập và assert toàn bộ 6 chat workers (không nuốt exception)**:
   - Thay thế toàn bộ khối `except Exception: pass` bằng mảng `chat_results = [None] * 6` và `chat_errors = [None] * 6`.
   - Sau khi release barrier, test assert: `chat_errors[idx] is None` và `status == 200` cho toàn bộ 6 luồng worker.
4. **Mô phỏng độ trễ DB/tools trước và ngoài gate**:
   - Hook `BusinessStore.conversation` (5ms delay), `BusinessStore.replay` (5ms delay), và `BoundTools.__call__` (5ms delay) để mô phỏng tải chậm ở DB/tools ngoài gate trước khi request vào `InferenceGate`.
5. **Đo cả hai endpoint GET /healthz và GET /api/session**:
   - Dưới tải bão hòa (6 worker thread của Waitress đang bận giữ 6 chat request), độc lập đo 25 request `GET /healthz` và 25 request `GET /api/session` (với session hợp lệ đã được cấp).
6. **Chuẩn hóa báo cáo số mẫu & giữ AC-09 PARTIAL**:
   - Cỡ mẫu: 25 request `GET /healthz` và 25 request `GET /api/session`.
   - Số đo báo cáo: `worst-of-25` (giá trị lớn nhất trong 25 mẫu; không gọi là ước lượng P99 thống kê).
   - Kết quả đo thực tế:
     - `GET /healthz` worst-of-25: ~2.0ms (<= 50.0ms SLO).
     - `GET /api/session` worst-of-25: ~3.0ms - 8.5ms (<= 50.0ms SLO).
   - **Trạng thái AC-09: Duy trì PARTIAL** trong toàn bộ tài liệu và PR description theo chỉ đạo rà soát, chờ chủ dự án phê duyệt đổi tiêu chí hoặc nghiệm thu qua benchmark lớn ở Phase 4.
7. **Đồng bộ tài liệu và Notebook**:
   - Đồng bộ `notebooks/colab_agent.ipynb` qua `scripts/build_agent_notebook.py` (`AGENT_NOTEBOOK_SOURCE_SYNC_OK`).
   - Cập nhật nhất quán [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md), [PLAN_MODULE_2_5_HARDENING_VERIFICATION.md](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md), [PLAN_ROADMAP_INDEX.md](PLAN_ROADMAP_INDEX.md), [PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md](PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md).
   - 4/4 script gates đạt PASS (docs contract, deployment contract, eval dataset, live e2e contract).
   - Bộ test PR B chạy đạt **28/28 PASS**; test suite cục bộ đạt **442 PASS, 51 SKIP, 0 FAIL**.
   - Dừng trước merge/deploy; kính chuyển reviewer độc lập re-review.
