# Review GPT 6 Astra — PR B #35 / AC-09

Ngày review: **05/10/2026 — Asia/Bangkok**. Phạm vi: bản sửa AC-09 mới, bằng chứng CI và tài liệu bàn giao liên quan; không audit toàn hệ thống.

## Prompt cô đọng cho Gemini

> Thực thi trigger AC09-P99-EVIDENCE trong PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md §12.1 trên PR #35. Chỉ hoàn thiện tests/test_http_headroom.py và artifact CI nếu cần: thu 1.000 mẫu/endpoint qua Waitress thật theo 10 batch, giữ tải 1 active + 5 queued và tool hook; đo đến hết response body, tính nearest-rank P99, lưu raw samples/SHA/config. Giữ runtime timeout 10s, fixture 30s; không đổi API/schema/cache/dataset, không hạ SLO. Đồng bộ docs/PR bằng kết quả thật, chạy focused tests + contracts + CI trên candidate cuối; báo PASS/SKIP/FAIL và artifact rồi dừng trước merge/deploy. Không mở lại N08 hoặc audit toàn hệ thống.

## Kết luận và quyết định

**Bản sửa tool hook, barrier và cách ghi worst-of-25 đã đạt. Không phát hiện lỗi P1/P2 mới trong phần test vừa sửa.** CI xanh đúng SHA. **Sẵn sàng sang bước cuối thu bằng chứng P99**, chưa đủ điều kiện đóng AC-09 hoặc merge PR #35 theo tiêu chí gốc.

AC-09 giữ **PARTIAL** vì phép đo 25 mẫu chưa đáp ứng protocol nghiệm thu P99. Đây là khoảng trống bằng chứng, không phải yêu cầu viết lại kiến trúc. Handoff đã có phạm vi file, trigger, protocol và điều kiện dừng; không cần thêm một vòng audit rộng.

## Bằng chứng độc lập

| Nguồn | Kết quả và giới hạn |
| --- | --- |
| Git / PR | Branch `feature/module-2.5-pr-b`; HEAD **54b0939ced600f0d45e62b110f85010912394f04**. [PR #35](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/35) mở, chưa merge, mergeable_state clean; base main `47ba72a248fb3c2cced20005e6cef9c978dd53a3`. |
| GitHub Actions | Check-runs API xác nhận **5/5 SUCCESS** trên đúng HEAD: Windows portable, Ubuntu portable, Colab Python 3.13, PostgreSQL, offline. [CI 37317875004](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37317875004) / [Ops Console 37317874825](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37317874825). Không suy ra số tests chỉ từ check xanh. Legacy status API trả pending/0 statuses vì không có legacy entries; không phải kết luận Actions lỗi. |
| Reviewer local, focused PR B | **28 tests: 27 PASS / 1 SKIP / 0 FAIL / 0 ERROR**. SKIP duy nhất là real-Waitress socket test vì Python 3.10.7 hiện thiếu Waitress. Không ghi rằng test này đã chạy tại local reviewer. |
| Gemini local | Báo **28/28 PASS** trong môi trường có Waitress. Được phân biệt với kết quả reviewer; CI cài Waitress trước discovery và chạy lại trong Docker. |
| Contracts | Docs **PASS 4/4**; deployment, dataset, live-E2E contract và notebook sync **PASS** trong vòng kiểm tra này. Sau đồng bộ docs: docs contract và `git diff --check` PASS. |
| Frozen datasets | Hai file vẫn có 250 cases, không đổi trong diff. SHA-256 chuẩn LF: `36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411`. Raw bytes CRLF tại Windows: `81f64611eb09eb4d319a29257e9c456fbffff07779182b130832fd7780062105` cho cả hai file. Phân biệt raw và LF-normalized hash. |

Báo cáo Gemini ghi full SHA có đuôi `52ba5c...`, khác SHA thực tế dù cùng prefix `54b0939`. Tài liệu review/handoff mới dùng SHA đọc trực tiếp từ Git và PR, không dùng full SHA sai trong attachment.

## Xác minh các sửa đổi

| Nội dung | Đối chiếu | Kết quả |
| --- | --- | --- |
| Tool hook thực thi | [tests/test_http_headroom.py](../tests/test_http_headroom.py#L169): worker 0 gửi tra cứu O-101; fake model trả `get_order`, hook gọi lại `orig_bound_call`; event/count được assert. Worker 0 chỉ vào model call thứ hai sau tool đã hoàn tất. | **ĐẠT** — không còn claim hook chỉ được cài mà chưa chạy. |
| Tải bão hòa trong phép đo | [Test barrier](../tests/test_http_headroom.py#L355) kiểm tra 1 active + 5 queued trước probes và sau mỗi vòng endpoint. Không có chat bổ sung để thay thế waiter rời queue; mất queue không được phục hồi âm thầm. Barrier timeout đặt cờ và raise. | **ĐẠT** trong harness tải kiểm soát. |
| Cách ghi metric | Hai test dùng `worst_of_25`; direct WSGI được ghi rõ là non-interference check. PR description đã bỏ claim “Verified P99” của phép đo này. | **ĐẠT** về tính trung thực; **AC-09 vẫn PARTIAL**. |
| Timeout | [InferenceGate](../retailops/inference_gate.py#L30) mặc định 10s. [Headroom fixture](../tests/test_http_headroom.py#L151) dùng 30s. Commit mới không sửa runtime gate. | Override fixture hợp lệ; không cần nâng runtime timeout. |

## Phần còn thiếu và cách xử lý

1. **Bằng chứng P99:** SLO gốc vẫn là P99 ≤50ms cho cả health/session dưới tải kiểm soát. Worst-of-25 không được tự coi là nghiệm thu thay thế. Protocol tiếp theo dùng 1.000 mẫu/endpoint, 10 batch và nearest-rank, lưu raw artifact; chi tiết trong handoff §12.1. Mỗi batch dùng fixture DB/session/server độc lập, hai probe cookies (50 mẫu/cookie + warm-up), giữ nguyên rate limiter 60/phút và login 15/phút; không được mở rộng vòng đo trên một cookie duy nhất rồi gặp 429 quota. Đây là P99 thực nghiệm của môi trường đo, không phải chứng minh production SLO.
2. **Ranh giới đo chưa đồng nhất:** healthz hiện đo đến status/headers mà không đọc body; session đọc và decode body. Body healthz nhỏ nên đây là giới hạn đo nhẹ, không phải regression. Protocol mới đo đến đọc hết body ở cả hai endpoint.
3. **Docs bị lệch, đã chỉnh trong review này:** Hardening/Sprint ghi nhầm timeout runtime 30s; Current còn mục “Hiện hành” ở e29f4c7 nói hook chưa chạy; Sprint còn chờ PR A; handoff dùng gate N08 làm hiện hành. Đã sửa/đánh dấu lịch sử và liên kết về gate PR B. Các nhãn pending lịch sử trong Sprint được tách khỏi ma trận AC hiện hành.

Các sleep DB/tool 5ms là mô phỏng; sáu chat được giữ chủ yếu tại model gate. Bằng chứng này không bao phủ DB lock toàn cục, flood request bị reject, mạng ngoài loopback hoặc model live. Admission 6 trên Waitress 8 không tạo pool hai worker riêng. Những giới hạn đó không mở rộng phạm vi AC-09 hiện tại.

## Tài liệu đã đồng bộ

- [PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md](PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md#121-trigger-ac09-p99-evidence): trigger, allowlist file, protocol, artifact và điều kiện dừng.
- [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md): SHA/run hiện hành, local PASS/SKIP, loại bỏ findings cũ còn gọi hiện hành; PR C deferred.
- [PLAN_MODULE_2_5_HARDENING_VERIFICATION.md](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md): runtime 10s / fixture 30s; AC-09 PARTIAL.
- [PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md): PR A merged, PR B gate hiện hành; status historical tách khỏi ma trận AC.
- [PLAN_ROADMAP_INDEX.md](PLAN_ROADMAP_INDEX.md) và [PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md](PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md): bước cuối AC-09, baseline lịch sử và liên kết protocol.

Chỉ sửa tài liệu ở working tree; không sửa code/test/config/notebook/dataset, không commit/push/merge/deploy. Bằng chứng CI của 54b0939 không bao gồm các chỉnh tài liệu chưa commit này.

## Bàn giao và điều kiện dừng

**Đi tiếp:** AC09-P99-EVIDENCE → CI xanh trên candidate cuối + raw artifact → xác nhận hẹp AC-09 → chủ dự án quyết định merge PR #35 → verification sau merge → Phase 4 frozen benchmark/load matrix 1/2/4/8/16.

**Dừng review/fix AC-09** khi protocol đạt cho hai endpoint, giữ saturation/tool assertion, tests/contracts không lỗi và CI đúng SHA. Nếu phép đo fail, báo lỗi và nguyên nhân cụ thể; không kéo thêm bug ngoài phạm vi. Nếu chủ dự án chọn chấp nhận worst-of-25 với limitation, ghi quyết định đổi tiêu chí riêng trước khi đổi AC-09; hiện chưa có quyết định đó. Không cần bật EC2 cho vòng CI này.

Lịch sử cô đọng: e29f4c7 bổ sung K=1/Q=5 và hai endpoint; 54b0939 khép tool hook, barrier và metric labeling. Những phát hiện cũ này đã đóng, không giữ nguyên bản review cũ ở cuối file.

---

## Báo cáo Thực thi Trigger AC09-P99-EVIDENCE (05/10/2026)

Trigger `AC09-P99-EVIDENCE` theo giao thức tại [handoff §12.1](PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md#121-trigger-ac09-p99-evidence) đã được thực thi đầy đủ trên PR #35:

1. **Giao thức đo đạc 10 batch x 100 mẫu/endpoint trên Waitress thật:**
   - 10 batch độc lập, mỗi batch chạy trên tiến trình Waitress 8 workers với socket loopback `127.0.0.1:0`.
   - `InferenceGate(concurrency=1, max_queue=5)`: duy trì chính xác 1 in-flight inference + 5 queued requests bằng barrier suốt cả 2 vòng đo (`GET /healthz` và `GET /api/session`).
   - Chat Worker 0 gửi `"Tra cứu đơn hàng O-101"`, kích hoạt tool `get_order`, và assert hook `BoundTools.__call__` thực thi $\ge 1$ lần ở mỗi batch.
   - Tuân thủ nghiêm ngặt giới hạn tốc độ: 8 logins/batch (6 chat + 2 probe) $< 15$ logins/phút; 100 mẫu `/api/session` chia đều 50 mẫu/cookie (+ warm-up 3/2) $\le 53$ calls/cookie $< 60$ calls/phút. Không có lỗi 429 hay exception ngoài ý muốn nào (toàn bộ 60 chat requests đạt HTTP 200).
   - Đo round-trip client bằng `time.perf_counter()` từ lúc gửi request tới khi **đọc toàn bộ response body** (`resp.read()`) và xác thực nội dung HTTP 200 / payload hợp lệ.

2. **Kết quả P99 thực nghiệm (Nearest-Rank, N=1.000 mẫu/endpoint):**
   - **`GET /healthz` (N=1.000):**
     - Min: `1.082 ms`
     - P50: `1.988 ms`
     - P95: `15.338 ms`
     - **P99 (index 989): `25.655 ms`** ($\le 50.0\text{ms}$ SLO $\rightarrow$ **PASS**)
     - Max: `27.525 ms`
     - Mean: `3.147 ms`
   - **`GET /api/session` (N=1.000, 2 probe cookies):**
     - Min: `8.397 ms`
     - P50: `10.463 ms`
     - P95: `25.618 ms`
     - **P99 (index 989): `33.464 ms`** ($\le 50.0\text{ms}$ SLO $\rightarrow$ **PASS**)
     - Max: `37.119 ms`
     - Mean: `11.912 ms`

3. **Lưu trữ Raw Artifact & Cấu hình CI:**
   - Dữ liệu chi tiết 1.000 mẫu latency cùng metadata (OS, Python, Waitress, tham số gate, trạng thái bão hòa, kết quả 60 chats) được lưu tại [`evals/reports/headroom_p99_artifact.json`](../evals/reports/headroom_p99_artifact.json).
   - Workflow `.github/workflows/ci.yml` được bổ sung step `actions/upload-artifact` trong job `offline` để lưu trữ artifact phục vụ kiểm toán độc lập.
   - Runtime timeout của `retailops/inference_gate.py` giữ nguyên mặc định 10s; fixture test dùng override 30s.

4. **Trạng thái & Điều kiện dừng:**
   - AC-09 đã có đầy đủ bằng chứng thực nghiệm P99 đạt chuẩn ($\le 50.0\text{ms}$ trên cả hai endpoint dưới tải bão hòa Waitress).
   - Sẵn sàng bàn giao cho chủ dự án xem xét và duyệt merge PR #35.
   - **DỪNG LẠI TRƯỚC MERGE VÀ DEPLOY. KHÔNG BẬT EC2.**

