# 06 — Sau khi merge

Phần này cho Claude và owner; executor chỉ đọc.

## 1. Kiểm chứng (Claude, trước khi owner merge)

- Diff đúng phạm vi:
  - `answer_check.py`;
  - hai chỗ trong `application.py` (nhánh khách, Trợ lý ca);
  - `topic_filter.py` mục 4;
  - `agent_protocol.py` dòng 33;
  - `turn_rec` của runner;
  - tệp test mới, các test cũ đúng bảng 04 mục 3;
  - notebook sinh lại, báo cáo, dòng W1 log.
- Chạy lại bảng 12 dòng, các test mới và cũ, runner giả 250 ca ở 16k và 32k.
- Thử thêm ca biên ngoài bộ test (ngày, giờ, số điện thoại, câu vừa dính luật số vừa dính luật chặn, Trợ lý ca có và không có thẻ nháp).
- CI xanh.

## 2. Deploy (Claude, chỉ khi owner duyệt riêng)

Như các lần trước: owner bật EC2, mở SSM; Claude bật cờ, chạy `deploy-ec2.yml` trên `main`, **tắt cờ ngay khi job `deploy` chạy**, kiểm `gh variable list`, canh tới khi xong. Không đổi `api.env`.

## 3. Smoke trên production (ô DeepSeek, tài khoản 3 đơn, hội thoại mới)

| # | Câu | Mong đợi |
|---|---|---|
| 1 | liệt kê các đơn của tôi | đủ 3 đơn, không dòng nào bị xóa; nếu model kẻ bảng có ngày "…/2026" thì dòng vẫn còn |
| 2 | phân tích cả 3 đơn giúp tôi | HTTP 200; model gọi nhiều tool trong một bước vẫn chạy |
| 3 | đơn `<mã>` đã hoàn tiền chưa (một đơn đã hoàn, nếu tài khoản có) | không bị thay bằng câu "chưa thực hiện hủy" |

Có câu ghi chú lạ thì owner mở DevTools → Network → `/api/chat` → `trace.answer_check_detail`, `trace.answer_check_audit`, chụp gửi Claude.

## 4. Lượt đo W6.4

- `REPO_SHA` trong `scratch/colab_w64_cells.py` đổi thành commit merge của W6.4.3.
- Báo cáo runner có `answer_check` (câu bị xóa) và `answer_check_audit` (cờ ghi vết) từng lượt. Dùng để đếm khi phân loại ca thất bại (W6.4-D6). Không chấm ngoại tuyến bằng model.

## 5. Tài liệu (Claude, batch tài liệu)

- Biên bản "W6.4.3: kiểm chứng, merge, deploy, smoke" trong `IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md`.
- `khoa_luan/00_khung_suon.md` (mục 2.3.2: bỏ "tối đa 4 tool mỗi bước") và `khoa_luan/04_so_do_du_lieu_rag_ngu_canh.md` (đoạn "Kiểm câu hứa": 4 luật xóa, 3 luật ghi vết, nguyên tắc "code chỉ chặn điều biết chắc").
