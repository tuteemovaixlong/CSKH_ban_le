# Review GPT 6 Astra — PR B #35 / AC-09

Ngày review: **05/10/2026**. Phạm vi hẹp: phần Gemini triển khai `AC09-P99-EVIDENCE` trên candidate `24ec244d4adf7f8983401f4023ff9fc08d58963f`; không audit toàn hệ thống.

## Prompt cô đọng cho Gemini

> Trigger `AC09-ARTIFACT-INTEGRITY`: đọc handoff §12.2 và review hiện hành. Chỉ sửa `tests/test_http_headroom.py`, `.github/workflows/ci.yml` và docs liên quan: dùng output mới ở vị trí ghi được (CI/RUNNER_TEMP, Colab /data), fail khi không ghi/không có artifact, validate SHA/mẫu/metadata; so SLO bằng P99 chưa round và cleanup cả setup. Giữ protocol 10×100, SLO 50ms, runtime timeout 10s. Commit/push branch hiện tại, chạy CI, xác minh artifact trên candidate cuối (chấp nhận synthetic merge đã đối chiếu parents/tree), đồng bộ docs. Báo PASS/SKIP/FAIL, run/artifact URL; dừng trước merge/deploy, không mở audit mới.

## Kết luận

**AC-09 PARTIAL — P99 VERIFIED / ARTIFACT-INTEGRITY PENDING**. **Phép đo P99 trên candidate đã được xác minh và đạt SLO**; chưa bàn giao merge vì đường ghi/upload bằng chứng còn fail-open. Vòng tiếp theo chỉ sửa harness/CI, không sửa runtime và không mở lại N08.

## Bằng chứng độc lập

| Hạng mục | Kết quả |
| --- | --- |
| Branch / HEAD | `feature/module-2.5-pr-b` / `24ec244d4adf7f8983401f4023ff9fc08d58963f` |
| PR #35 | Mở, chưa merge; base main `47ba72a`; mergeable_state `clean` |
| Local focused test | `python -B -X utf8 -m unittest tests.test_http_headroom`: **3 tests = 2 PASS / 1 SKIP / 0 FAIL / 0 ERROR**. SKIP thật vì interpreter reviewer thiếu Waitress; không suy diễn thành PASS socket test. |
| CI | Hai workflow CI `37326589577` và Ops Console `37326589348` trả `completed/success`. Check/job API có 4/5 `completed/success`, Ubuntu portable còn ghi `in_progress` cùng `conclusion=success`; dữ liệu trạng thái chưa nhất quán, chưa gọi 5/5 completed. |
| Artifact CI | ID `11351818526`, tên `headroom-p99-artifact-3b30fed4572969b2815dd99506bd265ac19d9f83`; reviewer tải và đọc độc lập, không chỉ dựa báo cáo Gemini. |
| Provenance | Artifact mang synthetic merge SHA `3b30fed4572969b2815dd99506bd265ac19d9f83`, có parent candidate `24ec244d4adf7f8983401f4023ff9fc08d58963f` và cùng Git tree. Đây là provenance hợp lệ cho candidate; không yêu cầu SHA merge thử bằng PR head. |
| Protocol | 10 batch độc lập, 1.000 mẫu mỗi endpoint; đủ 100 mẫu/endpoint/batch, 60/60 chat HTTP 200, tool hook và saturation xác nhận ở cả 10 batch. |
| P99 | Tính lại nearest-rank index 989 từ samples trong artifact: `/healthz` **1.005ms**, `/api/session` **3.538ms**; khớp summary, đạt ≤50ms. Samples artifact hiện đã round 3 chữ số; đủ xác nhận lần đo này vì cách xa ngưỡng. |
| Contracts | Docs PASS 4/4; deployment, eval dataset, live-E2E, notebook sync và diff check PASS. Đây là contract/sync checks, không phải kết quả live model hoặc full suite local. |

[CI run](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37326589577) · [Ops Console run](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37326589348) · [Artifact](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37326589577/artifacts/11351818526).

## Phát hiện còn mở

### P2 — Ghi/upload artifact có thể chấp nhận file cũ

- `tests/test_http_headroom.py:550–561`: lỗi ghi file chính được chuyển sang fallback; nếu fallback cũng lỗi thì `pass`. Test vẫn có thể thành công dù không có output mới ở đường CI upload.
- `.github/workflows/ci.yml:94–101`: upload luôn chạy (`if: always()`), đường upload trỏ tới JSON đã track trong repo, thiếu file dùng `ignore`. Test skip/fail hoặc chỉ ghi fallback có thể khiến CI upload bản checkout cũ.
- **Tác động:** làm sai tính tin cậy của gate ở lần chạy sau. Artifact CI lần này đã được kiểm tra và hợp lệ; không kết luận bằng chứng hiện tại là giả/cũ.
- **Sửa giới hạn:** chỉ định output mới ngoài tracked fixture, ở nơi ghi được; CI không upload file checkout làm kết quả. Fail rõ nếu không ghi được, thiếu output hoặc metadata/SHA/count sai. Dùng cùng đường output cho writer và uploader; giữ hỗ trợ Colab có source read-only.

### P3 — SLO so sánh P99 đã round

`tests/test_http_headroom.py:468–482,563–569` round P99 trước assertion. Phản ví dụ đã kiểm chứng bằng hàm hiện tại: 989 mẫu 1ms + 11 mẫu 50.0004ms → P99 thật 50.0004ms, round thành 50.0ms và PASS. Dùng float gốc cho assertion và `slo_50ms_met`; chỉ round khi hiển thị, giữ samples đủ precision để kiểm lại.

### P3 — Setup lỗi có thể bỏ cleanup

Hook được patch ở `tests/test_http_headroom.py:165–167`, server được khởi tạo/start ở `231–234`; `try` chính bắt đầu tại `240`. Nếu setup lỗi thì restore hooks/đóng server có thể không chạy. Bao phủ setup bằng `addCleanup`, context manager hoặc `try/finally`; chỉ join/close tài nguyên đã khởi tạo.

## Những phần đã đạt và giới hạn

Đã đạt ở phạm vi harness: six-chat admission, K=1/Q=5, thực thi `get_order` thật, barrier giữ tải qua warm-up/hai endpoint, đo tới hết body, fixture mới và hai probe cookies tránh rate limit. Runtime timeout vẫn 10s, fixture override 30s.

Đây là số đo loopback dưới tải tổng hợp có kiểm soát; chưa chứng minh production SLO, flood reject, DB lock toàn cục hoặc model live. Vòng review này không phát hiện thay đổi API/schema/cache/RBAC; các sửa cần làm chỉ thuộc harness/CI. Chưa có đủ bằng chứng để bảo đảm mọi nâng cấp tương lai không vỡ; Phase 4 sẽ đánh giá chất lượng/tải trước khi chọn nâng cấp embedding/reranker/OCR.

## Đồng bộ tài liệu và điều kiện dừng

Đã đối chiếu Current, Runtime, Sprint, Hardening, Roadmap và Handoff: thay claim ready merge/số P99 cũ bằng measurement CI đã xác minh và gate integrity còn mở; ghi rõ snapshot plan/hash cũ là lịch sử. Nguồn phạm vi coder và điều kiện dừng tại [Handoff §12.2](PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md#122-trigger-ac09-artifact-integrity).

Chỉ đóng vòng này khi: output mới có provenance hợp lệ của candidate cuối, đủ 10×100 samples và metadata đúng; assertion không round; ghi/upload lỗi làm gate fail; setup cleanup đầy đủ; CI checks hoàn tất thành công và docs/contracts khớp evidence. Khi đạt, bàn giao owner merge PR #35 → verification sau merge → Phase 4; không lặp audit toàn hệ thống.

Lịch sử cô đọng: `54b0939` đóng tool/barrier; `234e165` thêm protocol 1.000 mẫu; `24ec244` thêm fallback output nhưng nuốt lỗi. JSON trong repo thuộc parent `234e165` (25.591/34.658ms), không dùng nó thay artifact CI hiện tại. Review này không sửa code/test/config, không commit/push/merge/deploy.
