# Review GPT 6 Astra — PR B #35, AC-09

Ngày review: **05/10/2026**
Commit đối chiếu: **e29f4c7f5df13612037489fe0f0681e8c0544e72** trên nhánh **feature/module-2.5-pr-b**.

## Prompt ngắn cho Gemini

> Tiếp tục đúng PR #35, chỉ khép kín bằng chứng AC-09; không merge/deploy. Trong tests/test_http_headroom.py, làm cho một chat thực sự gọi tool và assert hook BoundTools.__call__ đã chạy; nếu không thể tạo luồng đó thì bỏ claim mô phỏng tool chậm. Giữ 6 chat bão hòa trong suốt hai vòng đo; bỏ timeout 10 giây có thể tự nhả barrier hoặc fail rõ nếu barrier mất. Rà mọi claim P99 trong test, docs và PR: phép đo max-of-25 chỉ ghi worst-of-25; test in-process không thay thế tải real Waitress. Cập nhật PR description/docs và giữ AC-09 PARTIAL. Chạy lại test trong môi trường có Waitress, focused suite và CI trên cùng SHA; báo cáo bằng chứng rồi dừng để review lại.

## Kết luận

**Chưa đủ điều kiện đóng AC-09 hoặc merge PR #35.** Test đã được cải thiện và CI xanh, nhưng tool-delay hook chưa chạy, barrier có thể tự hết hạn khi đo, và bằng chứng P99 trong mô tả PR không khớp với test tải thực tế.

## Bằng chứng

- GitHub: PR #35 mở, chưa merge, mergeable_state clean, HEAD e29f4c7; **5/5 check runs SUCCESS**, chưa có review được gửi.
- Local: 13 tests, 12 PASS / 1 SKIP / 0 FAIL; Waitress test bị skip vì interpreter thiếu Waitress, nên chưa tái lập được real-HTTP load test tại local.
- Docs contract PASS 4/4; notebook sync PASS.
- Gemini báo 28/28 focused tests PASS và worst-of-25 dưới 50 ms. CI xác nhận pipeline xanh, nhưng không chứng minh hook tool đã chạy hoặc tải còn bão hòa suốt phép đo.

## Phát hiện

| Mức | Phát hiện | Tác động |
| --- | --- | --- |
| **P2 — Tool delay chưa được kiểm thử** | Test gửi "Hello", supervisor route sang witty_agent, gọi model với allow_tools=False; fake model không trả tool_calls. Hook BoundTools.__call__ chỉ được cài, không có assertion đếm và không được thực thi trong luồng này. | Claim mô phỏng chậm DB/tools chưa chính xác; chưa có bằng chứng ảnh hưởng của tool latency. |
| **P2 — Barrier có thể nhả giữa phép đo** | chat_release.wait(timeout=10.0) tự hết hạn; test chỉ assert 1 inference + 5 queued trước hai vòng đo. | Trên CI chậm, probes có thể tiếp tục sau khi tải bão hòa đã mất. |
| **P2 — Claim P99 cần sửa** | PR description ghi “Verified P99” cho /healthz. Test real Waitress đo worst-of-25. Test cũ test_healthz_headroom_under_chat_saturation đo 25 lần trực tiếp qua WSGI, giữ semaphore nhưng không chạy Waitress; phép tính chọn giá trị lớn nhất và đặt tên P99. | Max-of-25 có thể là empirical percentile theo một quy ước rời rạc, nhưng 25 mẫu và phép đo in-process không đủ bằng chứng cho SLO P99 dưới tải real HTTP. Báo cáo là worst-of-25 hoặc dùng protocol percentile đã được duyệt. |
| **PARTIAL — Cỡ mẫu/tiêu chí** | Plan đặt mục tiêu P99; số đo mới là worst-of-25 và chưa có phê duyệt đổi tiêu chí. | Giữ AC-09 PARTIAL tới khi đáp ứng protocol được duyệt. |

## Bước tiếp theo

Các bổ sung K=1/Q=5, barrier ban đầu, ghi nhận kết quả sáu chat và đo hai endpoint là đúng hướng. Sau follow-up hẹp theo prompt, review lại test và SHA mới. Chỉ chuyển cho chủ dự án quyết định merge khi tool hook được chứng minh, barrier giữ suốt phép đo, các claim P99/worst-of-25 nhất quán và CI xanh cùng SHA. **Chưa merge/deploy; không cần bật EC2.**

### Lịch sử cô đọng

Review 04/10 chặn AC-09 do thiếu cấu hình K=1/Q=5, assertion tải và phép đo /api/session. Commit e29f4c7 xử lý các điểm đó; review này giữ lại tool hook, barrier, và cách diễn giải P99 so với worst-of-25.

---

## Báo cáo Khắc phục & Trạng thái Thực thi (Gemini 05/10/2026)

Tất cả 4 điểm phát hiện của GPT 6 Astra đã được xử lý triệt để trong `tests/test_http_headroom.py`, tài liệu và PR #35:

1. **Thực thi và assert hook tool `BoundTools.__call__` (P2 Resolved):**
   - Chat worker 0 gửi yêu cầu `"Tra cứu đơn hàng O-101"`, supervisor điều phối vào `order_agent` (với `allowed_tools=('get_order', ...)`).
   - `BarrierSlowModel.chat` tại Turn 1 trả về tool call `get_order(order_id="O-101")`.
   - `run_read_worker` thực thi công cụ qua `BoundTools.__call__`, kích hoạt hook `slow_bound_call`: tăng biến đếm `bound_call_count[0] += 1`, phát cờ `tool_called_event`, và giả lập trễ 5ms.
   - Test assert rõ ràng: `tool_called_event.wait(timeout=10.0)` và `self.assertGreaterEqual(bound_call_count[0], 1)`.

2. **Giữ bão hòa 6 chat liên tục suốt hai vòng đo & Bỏ silent timeout (P2 Resolved):**
   - Loại bỏ hoàn toàn việc timeout 10 giây tự giải phóng: trong `BarrierSlowModel.chat`, nếu `chat_release.wait(timeout=30.0)` hết hạn thì set cờ `barrier_timed_out` và ném `RuntimeError` làm test fail ngay lập tức.
   - Sau khi Chat 0 hoàn tất gọi tool và vào Turn 2 giữ slot inference gate (`_active_count == 1`), 5 chat workers còn lại (1..5) mới được gửi, chiếm toàn bộ 5 vị trí trong hàng đợi (`queue_size == 5`).
   - Khẳng định tải bão hòa (1 active inference + 5 queued, 6 Waitress workers bận) được kiểm tra tại 3 mốc:
     - Trước khi bắt đầu các vòng đo: `in_flight == 1`, `queue_size == 5`.
     - Sau vòng đo 1 (25 request `GET /healthz`): `in_flight == 1`, `queue_size == 5`.
     - Sau vòng đo 2 (25 request `GET /api/session`): `in_flight == 1`, `queue_size == 5`.
   - Chỉ khi cả hai vòng đo kết thúc, test mới gọi `chat_release.set()`.
   - Kiểm tra kết quả toàn bộ 6 chat: 0 exception, cả 6 đều trả về HTTP 200.

3. **Rà soát claim P99 & Phân định test in-process WSGI (P2 Resolved):**
   - Đổi tên biến và cách tính trong `test_healthz_headroom_under_chat_saturation`: thay claim `p99` bằng `worst_of_25 = max(latencies)`.
   - Bổ sung docstring ghi rõ test gọi WSGI trực tiếp chỉ là kiểm tra non-interference trong tiến trình, **không thay thế** cho bài test tải đa luồng thực tế qua socket của Waitress.
   - Mọi claim P99 cho phép đo 25 mẫu được sửa thành `worst-of-25` (dẫn chiếu `opsconsole/metrics.py` và `docs/ADMIN_CONSOLE.md`: P99 yêu cầu $\ge 100$ quan sát).

4. **Giữ nguyên trạng thái AC-09 PARTIAL (PARTIAL Kept):**
   - Giữ nguyên trạng thái `PARTIAL` trên PR #35 description và tất cả các file docs (`CURRENT_PROJECT_STATUS.md`, `PLAN_MODULE_2_5_HARDENING_VERIFICATION.md`, `PLAN_ROADMAP_INDEX.md`, `PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md`) chờ chủ dự án phê duyệt tiêu chí/giao thức P99.
   - Không merge, không deploy, không bật EC2. Dừng lại sau khi CI xanh trên cùng commit SHA mới để review.
