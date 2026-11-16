# 05 — Prompt cho Antigravity (Gemini 4 Hydrogen)

Bộ handoff **chưa lên `main`**: Gemini đọc thẳng từ worktree của Claude trên máy owner. Code lấy từ `origin/main`, đã có W6.4.1 (#113) và ô Custom (#114).

Mở một phiên agent mới trong Antigravity, workspace là repo chính `D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le`, chọn chế độ suy luận cao nhất. Dán nguyên khối dưới đây.

```text
Thực hiện W6.4.2 theo bộ handoff nằm TRÊN MÁY, chưa có trên main. Đọc theo đường dẫn tuyệt đối:

HANDOFF = D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/.claude/worktrees/cai-nay-la-sao-bddcef/docs/phase_role_aware_ops/W6_4_2_answer_check_fix/
  README.md, 01_HIEN_TRANG_VA_NGUYEN_NHAN.md, 02_PHAM_VI_VA_TIEU_CHI.md, 03_THIET_KE_CHI_TIET.md, 04_TEST_VA_KIEM_TRA.md, 06_SAU_KHI_MERGE.md

Quyết định áp dụng, cũng chỉ có trên máy, cùng worktree đó:
  docs/phase_role_aware_ops/W0_OWNER_DECISION_DELTA_2026-10-29.md, mục "## 32." (W6.4-D16)
  docs/phase_role_aware_ops/W6_BACKLOG_2026-11-06.md, dòng F46 và F47

Mọi tệp trong worktree .claude/worktrees/cai-nay-la-sao-bddcef chỉ để ĐỌC: không sửa, không chép vào nhánh, không commit, không chạy lệnh git trong worktree đó.

Trước khi làm, trong repo chính D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le:
1. git status phải sạch; không sạch thì dừng và báo owner.
2. git fetch origin. Kiểm origin/main là 3239454 hoặc mới hơn (git merge-base --is-ancestor 3239454 origin/main).
3. git switch --no-track -c phase-r1-w6-4-2 origin/main. Không làm trên main.
4. Đọc toàn bộ HANDOFF. Mở từng file code được nhắc tới để kiểm lại số dòng trước khi sửa (số dòng ghi theo 3239454).

Làm 5 hàng ở 02_PHAM_VI_VA_TIEU_CHI.md theo đúng thứ tự, theo thiết kế ở 03_THIET_KE_CHI_TIET.md. Mọi tên hằng, trường, khóa trace và tên luật phải đúng nguyên văn trong 03. Với hàng 1–4: viết test trước theo 04 mục 2, chạy trên code chưa sửa để thấy FAIL, ghi lại dòng lỗi, rồi mới sửa.

KHÔNG nới luật: lời hứa chính sách không trích dẫn vẫn bị bỏ như cũ; chỉ thêm bằng chứng lấy từ trường số của tool trong cùng lượt và đổi cách bỏ dòng tiêu đề. KHÔNG sửa test cũ của bộ kiểm (test_r1_w3_2_answer_check, test_r1_w6_3_1_hotfix, test_r1_w6_3_2_hotfix, test_r1_w6_3_4_answer_check); test cũ nào đỏ thì dừng và hỏi owner. Không đổi ba câu ghi chú và hai khóa cũ của trace['answer_check']. Không ghi chữ của câu bị bỏ vào trace hay báo cáo runner.

Không sửa SYSTEM, mô tả tool, rào an toàn, enforce_final_answer_grounding, luật nghiệp vụ, kho chính sách, dữ liệu demo, giao diện web, các ca trong evals/suites (đã đóng băng; SHA-256 12 tệp phải khớp bảng trong evals/suites/README.md), workflow CI hay deploy, requirements.

Môi trường: Python có pypdfium2 ở %TEMP%\venv_pdf\Scripts\python.exe, luôn đặt PYTHONUTF8=1 (chạy module test lẻ thì thêm PYTHONPATH=tests). Máy không có Node thật (node.cmd là bản giả): không chạy được test JS thì ghi rõ "CI kiểm", không ghi là đạt. Ghi .md bằng xuống dòng LF.

Chạy đủ các lệnh ở 04 mục 3, ghi đủ số đo ở 04 mục 4. Viết báo cáo docs/phase_role_aware_ops/W6_4_2_EXECUTION_REPORT_2026-11-15.md trên nhánh của bạn, theo 04 mục 5; nhắc tới tệp handoff bằng tên trong backtick, KHÔNG dùng link Markdown tương đối (thư mục handoff chưa có trên main nên check_docs_contract.py sẽ báo link hỏng). Thêm một dòng vào docs/phase_role_aware_ops/W1_EXECUTION_LOG_2026-10-31.md. Commit theo từng hàng, push nhánh phase-r1-w6-4-2 và mở PR vào main (nếu không mở được PR thì báo tên nhánh và SHA).

Cấm: merge; push vào main; force-push, rebase, reset, stash; đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e; truy cập EC2, SSM, DB production, Colab, model thật hay API trả phí, dữ liệu khách hàng; thêm thư viện; sửa ca trong evals/suites; ghi khóa, token hay URL database vào báo cáo hoặc log.

Gặp quyết định chưa có trong tài liệu, hoặc thấy tài liệu mâu thuẫn với code, thì dừng và hỏi owner, không tự chọn.
```

## Ghi chú cho owner

- Trước khi dán, kiểm repo chính đang sạch (`git status`). Hiện nó đang ở nhánh `phase-r1-w6-4-1` của lần trước (đã merge); Gemini sẽ tự tạo nhánh mới từ `origin/main`.
- Đừng xóa hay dọn worktree `cai-nay-la-sao-bddcef` trong lúc Gemini đang làm: bộ handoff nằm trong đó.
- Gemini hỏi giữa chừng thì chụp màn hình gửi Claude để soạn câu trả lời.
- Khi Gemini báo xong, dán báo cáo hoặc link PR cho Claude. Claude kiểm một lượt theo 02. Bạn quyết định merge.
