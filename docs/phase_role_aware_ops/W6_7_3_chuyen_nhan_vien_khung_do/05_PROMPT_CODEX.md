# 05 — Prompt cho Codex

Gửi sau khi PR chứa thư mục này đã merge vào `main`. Mức effort: **high**.

---

Bạn là người thực thi W6.7.3 của repo CSKH_ban_le. Trả lời, commit message và báo cáo bằng tiếng Việt.

1. `git fetch origin`, tạo nhánh `phase-r1-w6-7-3-khung-do` từ `origin/main` (phải chứa
   `docs/phase_role_aware_ops/W6_7_3_chuyen_nhan_vien_khung_do/`; nếu không có thì dừng và báo).
2. Đọc toàn bộ thư mục đó theo thứ tự trong README (README → 01 → 02 → 03 → 04 → 06). Không sửa thư mục này.
3. Làm đúng phạm vi ở 02 theo thiết kế 03 (năm hạng mục A–E); chạy kiểm ở 04.
4. Commit trên nhánh đó và `git push -u origin phase-r1-w6-7-3-khung-do`. **Không mở PR** (kể cả form PR trên GitHub),
   không merge, không push `main` — Claude sẽ kiểm, mở PR, chạy CI và merge.

Bắt buộc:
- Không viết lời khách (không tạo, không sửa câu trong bộ đệm lời khách, không "lời tạm") và **không viết nội dung gợi
  ý của phiếu đỡ**. Bạn chỉ viết phiếu (brief), kỳ vọng, `fake_model`, công cụ và test.
- Không sửa `evals/suites/`, `agent_protocol.py`, `retailops/` (kể cả `retailops/workflow/safety.py`), runner
  `scripts/run_agent_scenarios.py`. Gợi ý chèn bằng proxy mới, không qua runner.
- Không chạy model, không gọi API, không Colab, không đụng Drive hay ổ E:.
- 1.200 ca cũ và 1.406 phiếu cũ phải giữ đúng bất biến ở 02; không giữ được thì dừng và hỏi.
- Không chép mã đơn, tên, câu khách, URL/tên miền hay giá trị giả nào của bộ đo vào ca/phiếu T14.
- Gặp điểm thiết kế mơ hồ: hỏi lại bằng câu hỏi lựa chọn, kèm đề xuất của bạn; không tự mở rộng phạm vi.

Báo cáo cuối theo mẫu ở 04.
