# W6.7.2 — Công cụ chọn mẫu: vòng 2 Qwen trước, trọng tài, Tier S, trần, sửa chữ Hán (bàn giao cho Gemini Neon)

Soạn 19/11/2026 (Claude). Người thực thi: **Gemini 4 Neon (High) trong Antigravity** — chỉ viết code + test, đẩy nhánh,
báo cáo; KHÔNG mở PR, KHÔNG merge. Sau đó Claude kiểm một lượt, mở PR, chạy CI GitHub Actions và merge (owner giao 19/11).

**Trạng thái (19/11):** Neon xong (nhánh `phase-r1-w6-7-2-chon-mau`, `78945ec`), Claude kiểm trên dữ liệu thật, đã merge
PR #132 (`main` = `084b39b`). Gói vòng 2 đã xuất và bộ giám khảo đã dựng (xem 06, bước 1).

## Đọc theo thứ tự
1. [01_HIEN_TRANG.md](01_HIEN_TRANG.md) — số liệu và các quyết định của owner ngày 19/11.
2. [02_PHAM_VI_TIEU_CHI.md](02_PHAM_VI_TIEU_CHI.md) — vùng việc của Neon, ngoài vùng, khi nào là xong.
3. [03_THIET_KE_CHI_TIET.md](03_THIET_KE_CHI_TIET.md) — sáu hạng mục (A–F).
4. [04_TEST_BAO_CAO.md](04_TEST_BAO_CAO.md) — test, lệnh kiểm, mẫu báo cáo.
5. [05_PROMPT_NEON.md](05_PROMPT_NEON.md) — prompt dán cho Neon.
6. [06_SAU_MERGE.md](06_SAU_MERGE.md) — Claude chạy trên dữ liệu thật, giám khảo chấm, owner sửa chữ Hán.

## Điều kiện bắt đầu
- **W6.7.1 (Codex) đã merge vào `main`** — cả hai cùng sửa `scripts/sft_select.py`, `scripts/sft_build.py` và test của chúng;
  Neon rẽ nhánh `phase-r1-w6-7-2-chon-mau` từ `origin/main` sau đó (W6.7.1 thêm sẵn `--max-tool-chars`).
- Thư mục này phải có trên `main` (PR tài liệu riêng) hoặc Neon đọc theo đường dẫn tuyệt đối trong worktree
  `d:\year_2026\Work_2026\agentic_AI\CSKH_ban_le\.claude\worktrees\festive-gagarin-17db7e`.

## Quy tắc không đổi
- **Gemini chỉ viết code và chấm — không viết nội dung huấn luyện**: không điền chữ thay cho chữ Hán, không sửa câu
  trả lời/suy luận/lời khách trong bất kỳ mẫu nào (điều khoản Gemini cấm dùng đầu ra để phát triển model khác). Chữ thay
  do owner điền tay.
- Không sửa `evals/suites`, system prompt, `retailops/`, runner `scripts/run_agent_scenarios.py`.
- Không chạy model, không gọi API, không Colab, không đụng Drive hay ổ E:; test bằng dữ liệu giả.
- Chỉ commit/push lên nhánh `phase-r1-w6-7-2-chon-mau`.
