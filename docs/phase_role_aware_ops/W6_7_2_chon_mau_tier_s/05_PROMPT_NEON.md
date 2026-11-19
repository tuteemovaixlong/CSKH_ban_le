# 05 — Prompt cho Gemini Neon (Antigravity)

Gửi sau khi W6.7.1 (Codex) đã merge vào `main`. Model: **Gemini 4 Neon, mức High** (không xhigh). Mở Antigravity ở repo
chính `D:\year_2026\Work_2026\agentic_AI\CSKH_ban_le` (hoặc worktree Antigravity mới cho repo này).

---

Bạn là người thực thi W6.7.2 của repo CSKH_ban_le. Trả lời, commit message và báo cáo bằng tiếng Việt.

1. `git fetch origin`, tạo nhánh `phase-r1-w6-7-2-chon-mau` từ `origin/main`. Kiểm `origin/main` đã có W6.7.1
   (`docs/phase_role_aware_ops/W6_7_1_sua_khung/` và cờ `--max-tool-chars` trong `scripts/sft_select.py`); chưa có thì dừng và báo.
2. Đọc toàn bộ thư mục bàn giao W6.7.2 theo thứ tự README → 01 → 02 → 03 → 04 → 06:
   `docs/phase_role_aware_ops/W6_7_2_chon_mau_tier_s/` trên `origin/main`; nếu chưa có trên `main` thì đọc (chỉ đọc) tại
   `d:\year_2026\Work_2026\agentic_AI\CSKH_ban_le\.claude\worktrees\festive-gagarin-17db7e\docs\phase_role_aware_ops\W6_7_2_chon_mau_tier_s\`.
   Bản thử tham chiếu (chỉ đọc) nằm trong `…\festive-gagarin-17db7e\scratch\w67_trong_tai\` và `…\scratch\w67_cjk\`.
3. Làm đúng 6 hạng mục A–F ở 02 theo thiết kế 03; viết test bằng dữ liệu giả; chạy kiểm ở 04.
4. Commit trên nhánh đó và `git push -u origin phase-r1-w6-7-2-chon-mau`. **Không mở PR**, không merge, không push `main`.

Bắt buộc:
- Bạn chỉ viết code và test. **Không viết, không sửa, không gợi ý bất kỳ chữ nào của mẫu huấn luyện** (câu trả lời, suy
  luận, lời khách, chữ thay cho chữ Hán) — owner làm phần đó.
- Không mở dữ liệu thật (ổ E:, Drive, `scratch/*.json` lớn); không chạy model, không gọi API, không Colab.
- Không sửa `evals/suites/`, system prompt, `retailops/`, `scripts/run_agent_scenarios.py`.
- Không đổi hành vi `export --round 1` / `import` vòng 1; nếu không giữ được thì dừng và hỏi.
- Gặp điểm thiết kế mơ hồ: hỏi lại bằng câu hỏi lựa chọn kèm đề xuất; không tự mở rộng phạm vi.

Báo cáo cuối theo mẫu ở 04.
