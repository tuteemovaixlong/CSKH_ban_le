# 05 — Prompt cho Codex

Gửi sau khi PR chứa thước v4 + thư mục này đã merge vào `main`. Mức effort: **high**.

---

Bạn là người thực thi W6.7.1 của repo CSKH_ban_le. Trả lời, commit message và báo cáo bằng tiếng Việt.

1. `git fetch origin`, tạo nhánh `phase-r1-w6-7-1-sua-khung` từ `origin/main` (phải chứa
   `docs/phase_role_aware_ops/W6_7_1_sua_khung/`; nếu không có thì dừng và báo).
2. Đọc toàn bộ thư mục `docs/phase_role_aware_ops/W6_7_1_sua_khung/` theo thứ tự trong README (README → 01 → 02 → 03 →
   04 → 06). Không sửa thư mục này.
3. Làm đúng phạm vi ở 02 theo thiết kế 03; chạy kiểm ở 04.
4. Commit trên nhánh đó và `git push -u origin phase-r1-w6-7-1-sua-khung`. **Không mở PR** (kể cả form PR trên GitHub),
   không merge, không push `main` — Claude sẽ kiểm, mở PR, chạy CI và merge.

Bắt buộc:
- Không viết lời khách hàng (không tạo, không sửa câu trong bộ đệm lời khách, không "lời tạm"). Lời khách mới do owner
  cho Muse Glimmer viết sau khi merge. Bạn chỉ sửa phiếu (brief), select, kỳ vọng, giá trị giả, công cụ và test.
- Không sửa `evals/suites/`, system prompt, `retailops/`, runner `scripts/run_agent_scenarios.py`.
- Không chạy model, không gọi API, không Colab, không đụng Drive hay ổ E:.
- Phiếu ngoài 6 khung phải trùng từng byte với v3; nếu không giữ được thì dừng và hỏi.
- Gặp điểm thiết kế mơ hồ: hỏi lại bằng câu hỏi lựa chọn, kèm đề xuất của bạn; không tự mở rộng phạm vi.

Báo cáo cuối (theo mẫu ở 04): tên nhánh + SHA đầu nhánh, danh sách tệp đổi, danh sách `brief_id` phải viết lại (theo
khung) và số phiếu chỉ đổi `injection`, kết quả từng lệnh kiểm.
