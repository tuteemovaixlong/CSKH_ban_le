# Review GPT 6 Astra — PR B #35 / AC-09

Ngày review: **06/10/2026**. Phạm vi hẹp: phần Gemini triển khai `AC09-ARTIFACT-INTEGRITY` trên candidate `8ba66c8cedafe849ff8377323779366d7b559eff`; không audit toàn hệ thống.

## Prompt cô đọng cho Gemini

> Trigger `AC09-ARTIFACT-INTEGRITY`: đọc handoff §12.2 và review hiện hành. Chỉ sửa `tests/test_http_headroom.py`, `.github/workflows/ci.yml` và docs liên quan: dùng output mới ở vị trí ghi được (CI/RUNNER_TEMP, Colab /data), fail khi không ghi/không có artifact, validate SHA/mẫu/metadata; so SLO bằng P99 chưa round và cleanup cả setup. Giữ protocol 10×100, SLO 50ms, runtime timeout 10s. Commit/push branch hiện tại, chạy CI, xác minh artifact trên candidate cuối (chấp nhận synthetic merge đã đối chiếu parents/tree), đồng bộ docs. Báo PASS/SKIP/FAIL, run/artifact URL; dừng trước merge/deploy, không mở audit mới.

## Kết luận

**AC-09 VERIFIED — P99 & ARTIFACT-INTEGRITY GATES PASSED**. **Phép đo P99 và tính toàn vẹn artifact trên candidate `8ba66c8` đã được xác minh độc lập, đạt SLO unrounded float $\le 50.0$ms, 5/5 check-runs xanh**. Đường ghi/upload fail-closed, assert float gốc, cleanup cả setup đã hoàn tất. Sẵn sàng bàn giao chủ dự án review merge PR #35.

## Bằng chứng độc lập

| Hạng mục | Kết quả |
| --- | --- |
| Branch / HEAD | `feature/module-2.5-pr-b` / `8ba66c8cedafe849ff8377323779366d7b559eff` (`8ba66c8`) |
| PR #35 | Mở, chưa merge; base main `47ba72a`; mergeable_state `clean` |
| Local focused test | `python -B -X utf8 -m unittest tests.test_http_headroom`: **6 tests = 6 PASS / 0 SKIP / 0 FAIL / 0 ERROR** (18.5s). Đã bổ sung 3 regression tests cho fail-closed writer, unrounded boundary 50.0004ms fail, và setup failure cleanup. |
| CI | Hai workflow CI [37415015592](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37415015592) và Ops Console [37415015585](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37415015585) trả `completed/success`. Check/job API có 5/5 `completed/success` (`portable windows-latest`, `portable ubuntu-24.04`, `offline`, `postgres`, `colab-python313`). |
| Artifact CI | ID `11390129084`, tên `headroom-p99-artifact-2ac01ee9ac73974ec7f6cd2a9970efa5266c2a58`; bước `Validate headroom P99 measurement artifact integrity` kiểm tra độc lập và upload fail-closed (bỏ `always()`, `if-no-files-found: error`). |
| Provenance | Artifact mang synthetic merge SHA `2ac01ee9ac73974ec7f6cd2a9970efa5266c2a58`, có parents `47ba72a` (base main) và `8ba66c8` (PR candidate HEAD), Git tree trùng khớp 100% với candidate `8ba66c8`. Đây là provenance hợp lệ cho candidate. |
| Protocol | 10 batch độc lập, 1.000 mẫu mỗi endpoint; đủ 100 mẫu/endpoint/batch, 60/60 chat HTTP 200, tool hook và saturation xác nhận ở cả 10 batch. |
| P99 | Tính lại nearest-rank index 989 từ samples trong artifact: `/healthz` **0.999ms**, `/api/session` **3.468ms** (unrounded float); khớp summary, đạt $\le 50$ms. |
| Contracts | Docs PASS 4/4; deployment, eval dataset, live-E2E, notebook sync và diff check PASS. |

[CI run](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37415015592) · [Ops Console run](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37415015585) · [Artifact](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37415015592/artifacts/11390129084).

## Các phát hiện đã đóng (Resolved Findings)

### P2 — Ghi/upload artifact có thể chấp nhận file cũ (ĐÃ ĐÓNG)

- **Biện pháp khắc phục:**
  - `tests/test_http_headroom.py`: hàm `save_headroom_artifact` ghi vào vị trí writable theo thứ tự `RETAILOPS_HEADROOM_ARTIFACT_PATH` -> `RUNNER_TEMP` -> `/data` -> `tempdir`. Bỏ nuốt lỗi `pass`; nếu không thể ghi được thì raise `RuntimeError` khiến test fail-closed ngay lập tức. Đã có regression test `test_artifact_writer_failure_fails_closed`.
  - `.github/workflows/ci.yml`: biến `RETAILOPS_HEADROOM_ARTIFACT_PATH: ${{ runner.temp }}/headroom_p99_artifact.json` xóa file cũ trước khi chạy. Thêm bước `Validate headroom P99 measurement artifact integrity` kiểm tra độc lập cấu trúc, SHA, sample counts, saturation và unrounded P99. Bước upload bỏ `if: always()` và đặt `if-no-files-found: error`. Không upload JSON checkout tracked trong repo.

### P3 — SLO so sánh P99 đã round (ĐÃ ĐÓNG)

- **Biện pháp khắc phục:**
  - `calc_headroom_percentiles` tính và lưu `p99_raw_ms` dưới dạng unrounded float; assertion `slo_50ms_met` so sánh trực tiếp float gốc này với 50.0ms. Chỉ round 3 chữ số cho hiển thị (`p99_ms`). `raw_samples` bảo toàn độ chính xác float. Đã có regression test `test_percentile_unrounded_boundary_fails_slo` xác nhận case 50.0004ms bị từ chối SLO.

### P3 — Setup lỗi có thể bỏ cleanup (ĐÃ ĐÓNG)

- **Biện pháp khắc phục:**
  - `_run_waitress_batch` bọc toàn bộ khối setup và batch execution trong `try ... finally` an toàn; từng tài nguyên (`hooks_patched`, `server`, `server_thread`, `batch_temp`, `chat_threads`, `chat_release`) được cleanup và restore độc lập trong `finally`. Đã có regression test `test_waitress_batch_setup_failure_cleanup` xác minh hooks và temp dir được phục hồi hoàn chỉnh kể cả khi setup lỗi.

## Những phần đã đạt và giới hạn

Đã đạt ở phạm vi harness: six-chat admission, K=1/Q=5, thực thi `get_order` thật, barrier giữ tải qua warm-up/hai endpoint, đo tới hết body, fixture mới và hai probe cookies tránh rate limit. Runtime timeout vẫn 10s, fixture override 30s.

Đây là số đo loopback dưới tải tổng hợp có kiểm soát; chưa chứng minh production SLO, flood reject, DB lock toàn cục hoặc model live. Vòng review này không phát hiện thay đổi API/schema/cache/RBAC; các sửa đã làm chỉ thuộc harness/CI/docs. Chưa có đủ bằng chứng để bảo đảm mọi nâng cấp tương lai không vỡ; Phase 4 sẽ đánh giá chất lượng/tải trước khi chọn nâng cấp embedding/reranker/OCR.

## Đồng bộ tài liệu và điều kiện dừng

Đã đối chiếu Current, Runtime, Sprint, Hardening, Roadmap và Handoff: cập nhật candidate `8ba66c8`, CI run `37415015592`, artifact ID `11390129084`, xác nhận đóng toàn bộ findings P2 và P3. Toàn bộ 5/5 check-runs CI hoàn tất thành công và docs/contracts khớp evidence.

**Điều kiện dừng thỏa mãn**: Đã dừng trước merge/deploy, không mở rộng audit. Bàn giao chủ dự án duyệt merge PR #35 → verification sau merge trên main → Phase 4.

Lịch sử cô đọng: `54b0939` đóng tool/barrier; `234e165` thêm protocol 1.000 mẫu; `24ec244` thêm fallback output nhưng nuốt lỗi; `8ba66c8` hoàn tất fail-closed artifact pipeline, unrounded assertion, và setup cleanup. Review này không merge/deploy.

