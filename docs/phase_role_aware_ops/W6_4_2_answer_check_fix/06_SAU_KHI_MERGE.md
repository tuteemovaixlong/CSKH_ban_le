# 06 — Sau khi merge

Phần này cho Claude và owner; executor chỉ đọc để biết bản sửa sẽ được dùng thế nào.

## 1. Kiểm chứng (Claude, trước khi owner merge)

- Diff đúng phạm vi: `retailops/workflow/answer_check.py`, hai chỗ ghi trace trong `retailops/business/application.py`, `turn_rec` trong `scripts/run_agent_scenarios.py`, tệp test mới, notebook sinh lại, báo cáo, dòng W1 log. Không đụng test cũ của bộ kiểm, `evals/suites`, `SYSTEM`, mô tả tool, rào an toàn.
- Chạy lại `tests/test_w642_answer_check.py`, 4 tệp test cũ của bộ kiểm, runner giả 250 ca ở 16k và 32k.
- Tự chạy bảng 11 dòng ở 01 mục 6 trên nhánh; đối chiếu với báo cáo.
- Kiểm JSON trả về của một lượt bị sửa: có `answer_check_detail`, không có chữ của câu bị bỏ.
- CI xanh.

## 2. Deploy (Claude, chỉ khi owner duyệt riêng)

Như các lần trước: owner bật EC2 và mở phiên SSM; Claude bật cờ `RETAILOPS_DEPLOY_ENABLED`, chạy `deploy-ec2.yml` trên `main`, **tắt cờ ngay khi job `deploy` chạy**, kiểm `gh variable list`, canh tới khi xong. Không đổi `api.env`.

## 3. Smoke trên production

Tài khoản khách đã dùng ở smoke 2026-11-15 (3 đơn), ô DeepSeek, hội thoại mới:

| # | Câu | Mong đợi |
|---|---|---|
| 1 | liệt kê các đơn của tôi | đủ 3 đơn; **không** còn dòng trống giữa các dòng của một đơn; nếu model ghi tiền hàng và phí ship thì dòng đó còn |
| 2 | phân tích cả 3 đơn giúp tôi | mỗi đơn có tiêu đề riêng; dòng số giờ trễ, số ngày còn lại còn nguyên; câu ghi chú cuối chỉ xuất hiện khi thật sự có câu chính sách bị bỏ |

Nếu vẫn có câu ghi chú, owner mở DevTools → Network → yêu cầu `/api/chat` → `trace.answer_check_detail`, chụp màn hình gửi Claude (khóa này không có chữ của câu bị bỏ, chỉ có số dòng và tên luật).

Khi Colab phục vụ Qwen đang chạy: lặp lại hai câu ở ô "Custom model · Colab vLLM".

## 4. Lượt đo W6.4

- `REPO_SHA` trong notebook đo (`scratch/colab_w64_cells.py`) đổi thành commit merge của W6.4.2, dùng một SHA cho mọi bước.
- Báo cáo runner có khóa `answer_check` ở những lượt bị bộ kiểm sửa. Khi phân loại ca thất bại (W6.4-D6), tách nhóm "câu trả lời bị bộ kiểm sửa" theo `rule`, để phân biệt lỗi model với lỗi của bộ kiểm.

## 5. Ghi biên bản

Claude ghi biên bản "W6.4.2: kiểm chứng, merge, deploy, smoke" vào `IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md` trên nhánh tài liệu, đẩy cùng batch tài liệu.
