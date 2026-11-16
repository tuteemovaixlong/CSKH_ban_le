# 05 — Prompt cho Antigravity (Gemini 4 Hydrogen)

Bộ handoff **chưa lên `main`**: Gemini đọc thẳng từ worktree của Claude trên máy owner. Code thì lấy từ `origin/main`, vốn đã có đủ W6.4.0 và bản sửa #112.

Mở một phiên agent mới trong Antigravity, workspace là repo chính `D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le`, chọn chế độ suy luận cao nhất. Dán nguyên khối dưới đây.

```text
Thực hiện W6.4.1 theo bộ handoff nằm TRÊN MÁY, chưa có trên main. Đọc theo đường dẫn tuyệt đối:

HANDOFF = D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/.claude/worktrees/cai-nay-la-sao-bddcef/docs/phase_role_aware_ops/W6_4_1_context_fix/
  README.md, 01_HIEN_TRANG_VA_NGUYEN_NHAN.md, 02_PHAM_VI_VA_TIEU_CHI.md, 03_THIET_KE_CHI_TIET.md, 04_TEST_VA_KIEM_TRA.md, 06_SAU_KHI_MERGE.md

Quyết định áp dụng, cũng chỉ có trên máy, cùng worktree đó:
  docs/phase_role_aware_ops/W0_OWNER_DECISION_DELTA_2026-10-29.md, mục "## 32." (W6.4-D9a, W6.4-D15)
  docs/phase_role_aware_ops/W6_BACKLOG_2026-11-06.md, dòng F44

Mọi tệp trong worktree .claude/worktrees/cai-nay-la-sao-bddcef chỉ để ĐỌC: không sửa, không chép vào nhánh, không commit, không chạy lệnh git trong worktree đó.

Trước khi làm, trong repo chính D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le:
1. git status phải sạch; không sạch thì dừng và báo owner.
2. git fetch origin. Kiểm origin/main là fdaa2c3 hoặc mới hơn (git merge-base --is-ancestor fdaa2c3 origin/main).
3. git switch --no-track -c phase-r1-w6-4-1 origin/main. Không làm trên main.
4. Đọc toàn bộ HANDOFF. Mở từng file code được nhắc tới để kiểm lại số dòng trước khi sửa (số dòng ghi theo fdaa2c3).

Làm 6 hàng ở 02_PHAM_VI_VA_TIEU_CHI.md theo đúng thứ tự, theo thiết kế ở 03_THIET_KE_CHI_TIET.md. Mọi tên trường, tham số và mô tả tool phải đúng nguyên văn trong 03. Với hàng 1–5: viết test trước theo 04 mục 2, chạy trên code chưa sửa để thấy FAIL, ghi lại dòng lỗi, rồi mới sửa.

Không sửa SYSTEM trong agent_protocol.py, answer_check, rào an toàn, luật, kho chính sách, dữ liệu demo, các ca trong evals/suites (đã đóng băng; SHA-256 12 tệp phải khớp bảng trong evals/suites/README.md), workflow CI hay deploy, requirements.

Môi trường: Python có pypdfium2 ở %TEMP%\venv_pdf\Scripts\python.exe, luôn đặt PYTHONUTF8=1 (chạy module test lẻ thì thêm PYTHONPATH=tests). Máy không có Node thật (node.cmd là bản giả): không chạy được test JS thì ghi rõ "CI kiểm", không ghi là đạt. Ghi .md bằng xuống dòng LF.

Chạy đủ các lệnh ở 04 mục 3, ghi đủ số đo ở 04 mục 4. Viết báo cáo docs/phase_role_aware_ops/W6_4_1_EXECUTION_REPORT_2026-11-15.md trên nhánh của bạn, theo 04 mục 5; nhắc tới tệp handoff bằng tên trong backtick, KHÔNG dùng link Markdown tương đối (thư mục handoff chưa có trên main nên check_docs_contract.py sẽ báo link hỏng). Thêm một dòng vào docs/phase_role_aware_ops/W1_EXECUTION_LOG_2026-10-31.md. Commit theo từng hàng, push nhánh phase-r1-w6-4-1 và mở PR vào main (nếu không mở được PR thì báo tên nhánh và SHA).

Cấm: merge; push vào main; force-push, rebase, reset, stash; đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e; truy cập EC2, SSM, DB production, Colab, model thật hay API trả phí, dữ liệu khách hàng; thêm thư viện; sửa ca trong evals/suites; ghi khóa, token hay URL database vào báo cáo hoặc log.

Gặp quyết định chưa có trong tài liệu, hoặc thấy tài liệu mâu thuẫn với code, thì dừng và hỏi owner, không tự chọn.
```

## Ghi chú cho owner

- Trước khi dán, kiểm repo chính đang sạch (`git status`). Hiện nó đang ở nhánh `phase-r1-w6-4-0` cũ của Codex; Gemini sẽ tự tạo nhánh mới từ `origin/main`.
- Đừng xóa hay dọn worktree `cai-nay-la-sao-bddcef` trong lúc Gemini đang làm: bộ handoff nằm trong đó.
- Khi Gemini báo xong, dán báo cáo hoặc link PR cho Claude. Claude kiểm một lượt theo 02, như các hotfix trước. Bạn quyết định merge.
- PR đưa bộ handoff và batch tài liệu lên `main` có thể mở trước hoặc sau PR của Gemini. Hai PR không đụng cùng tệp, trừ `W1_EXECUTION_LOG` nếu batch tài liệu cũng thêm dòng vào đó.
