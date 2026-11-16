# 05 — Prompt cho Antigravity (Gemini 4 Hydrogen)

Bộ handoff **chưa lên `main`**: Gemini đọc thẳng từ worktree của Claude trên máy owner. Code lấy từ `origin/main`, đã có W6.4.2 (#115).

Mở một phiên agent mới trong Antigravity, workspace là repo chính `D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le`, chọn chế độ suy luận cao nhất. Dán nguyên khối dưới đây.

```text
Thực hiện W6.4.3 theo bộ handoff nằm TRÊN MÁY, chưa có trên main. Đọc theo đường dẫn tuyệt đối:

HANDOFF = D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/.claude/worktrees/cai-nay-la-sao-bddcef/docs/phase_role_aware_ops/W6_4_3_answer_check_scope/
  README.md, 01_HIEN_TRANG_VA_NGUYEN_NHAN.md, 02_PHAM_VI_VA_TIEU_CHI.md, 03_THIET_KE_CHI_TIET.md, 04_TEST_VA_KIEM_TRA.md, 06_SAU_KHI_MERGE.md

Quyết định áp dụng, cũng chỉ có trên máy, cùng worktree đó:
  docs/phase_role_aware_ops/W0_OWNER_DECISION_DELTA_2026-10-29.md, mục "## 32." (W6.4-D17)
  docs/phase_role_aware_ops/W6_BACKLOG_2026-11-06.md, dòng F48, F49, F50, F51
Bối cảnh (không bắt buộc): docs/phase_role_aware_ops/W6_4_3_answer_check_consult/README.md

Mọi tệp trong worktree .claude/worktrees/cai-nay-la-sao-bddcef chỉ để ĐỌC: không sửa, không chép vào nhánh, không commit, không chạy lệnh git trong worktree đó.

Trước khi làm, trong repo chính D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le:
1. git status phải sạch; không sạch thì dừng và báo owner.
2. git fetch origin. Kiểm origin/main là ece0b0b hoặc mới hơn (git merge-base --is-ancestor ece0b0b origin/main).
3. git switch --no-track -c phase-r1-w6-4-3 origin/main. Không làm trên main, không dùng nhánh phase-r1-w6-4-2 cũ.
4. Đọc toàn bộ HANDOFF. Mở từng file code được nhắc tới để kiểm lại số dòng trước khi sửa (số dòng ghi theo ece0b0b).

Làm 6 hàng ở 02_PHAM_VI_VA_TIEU_CHI.md theo đúng thứ tự, theo 03_THIET_KE_CHI_TIET.md. Mọi tên hằng, trường, khóa trace, tên luật và câu chữ phải đúng nguyên văn trong 03. Với hàng 1–5: viết test trước theo 04 mục 2, chạy trên code chưa sửa để thấy FAIL, ghi lại dòng lỗi, rồi mới sửa.

Test cũ CHỈ được sửa đúng các chỗ ở 04 mục 3 và đúng cách đã ghi (đổi "bị xóa" thành "giữ + ghi vết" cho 3 luật số; không bỏ câu thử nào). Test cũ nào khác đỏ thì dừng và hỏi owner. Không đổi ba câu ghi chú, hai khóa cũ của trace['answer_check'], SYSTEM. Không ghi chữ của câu trả lời vào trace hay báo cáo runner. Không làm "tràn mềm" cho tool.

Không sửa mô tả tool, rào an toàn khác, luật nghiệp vụ, kho chính sách, dữ liệu demo, giao diện web, khoa_luan/, các ca trong evals/suites (đã đóng băng; SHA-256 12 tệp phải khớp bảng trong evals/suites/README.md), workflow CI hay deploy, requirements.

Môi trường: Python có pypdfium2 ở %TEMP%\venv_pdf\Scripts\python.exe, luôn đặt PYTHONUTF8=1 (chạy module test lẻ thì thêm PYTHONPATH=tests). Máy không có Node thật (node.cmd là bản giả): không chạy được test JS thì ghi "CI kiểm". Ghi .md bằng xuống dòng LF. Viết regex bằng chuỗi r'...'; nếu sửa tệp bằng script thì kiểm lại không có ký tự backspace (\x08).

Chạy đủ lệnh ở 04 mục 4, ghi đủ số đo ở 04 mục 5. Viết báo cáo docs/phase_role_aware_ops/W6_4_3_EXECUTION_REPORT_2026-11-15.md trên nhánh của bạn theo 04 mục 6; nhắc tới tệp handoff bằng tên trong backtick, KHÔNG dùng link Markdown tương đối. Thêm một dòng vào docs/phase_role_aware_ops/W1_EXECUTION_LOG_2026-10-31.md. Commit theo từng hàng, push nhánh phase-r1-w6-4-3 và mở PR vào main (nếu không mở được PR thì báo tên nhánh và SHA).

Cấm: merge; push vào main; force-push, rebase, reset, stash; đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e; truy cập EC2, SSM, DB production, Colab, model thật hay API trả phí, dữ liệu khách hàng; thêm thư viện; sửa ca trong evals/suites; ghi khóa, token hay URL database vào báo cáo hoặc log.

Gặp quyết định chưa có trong tài liệu, hoặc thấy tài liệu mâu thuẫn với code, thì dừng và hỏi owner, không tự chọn.
```

## Ghi chú cho owner

- Trước khi dán, kiểm repo chính đang sạch (`git status`). Repo chính có thể còn ở nhánh `phase-r1-w6-4-2` của lần trước (đã merge); Gemini tự tạo nhánh mới từ `origin/main`.
- Đừng dọn worktree `cai-nay-la-sao-bddcef` trong lúc Gemini làm.
- Gemini hỏi giữa chừng thì chụp màn hình gửi Claude. Xong thì gửi báo cáo hoặc link PR; Claude kiểm một lượt theo 02; bạn quyết định merge.
