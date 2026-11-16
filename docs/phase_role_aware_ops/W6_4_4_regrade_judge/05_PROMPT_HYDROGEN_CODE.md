# 05 — Prompt cho Gemini 4 Hydrogen (phần code)

Dán nguyên khối dưới vào Antigravity. Thay `<ĐƯỜNG_DẪN_HANDOFF>` bằng đường dẫn tuyệt đối của thư mục này nếu tài liệu chưa có trên `main`.

```text
Bạn là executor cho repo CSKH_ban_le (RetailOps). Việc: W6.4.4 phần code — chấm lại kết quả đo W6.4 bằng bộ chuẩn hóa v2 và chuẩn bị/gộp phiếu giám khảo.

Đọc trước, theo thứ tự (chỉ đọc, không sửa):
  <ĐƯỜNG_DẪN_HANDOFF>/README.md
  <ĐƯỜNG_DẪN_HANDOFF>/01_HIEN_TRANG.md
  <ĐƯỜNG_DẪN_HANDOFF>/02_PHAM_VI_VA_TIEU_CHI.md
  <ĐƯỜNG_DẪN_HANDOFF>/03_THIET_KE_CHI_TIET.md
  <ĐƯỜNG_DẪN_HANDOFF>/04_HUONG_DAN_CHAM.md   (để hiểu định dạng gói chấm và phiếu)

Làm:
1. Tạo nhánh phase-r1-w6-4-4 từ origin/main mới nhất.
2. Sửa scripts/run_agent_scenarios.py đúng 2 chỗ ở 03 mục 1 (bỏ cắt 600 ký tự của answer và draft_reply trong báo cáo). Không đổi grade_turn, squash, attack_success hay bất kỳ logic chấm nào.
3. Viết scripts/eval_regrade.py (chỉ thư viện chuẩn) với 4 lệnh v2, export, import, audit đúng 03 mục 2–8. Dùng lại hàm của scripts/eval_stats.py nếu có sẵn hàm tính pass@1/pass^k phù hợp; không sửa eval_stats.py.
4. Viết tests/test_w644_eval_regrade.py: phủ bảng ví dụ ở 03 mục 2, bốn loại nguồn văn bản và quy tắc lật một chiều (mục 3), ẩn danh của export (không có tên model, mã ca, số lần chạy trong batch-*.jsonl), kiểm trích dẫn và gộp bảo thủ hai giám khảo (mục 7), đối chứng, ba con số, audit. Dữ liệu test tự dựng nhỏ trong test, không đọc ổ E:.
5. Chạy toàn bộ test của repo (cách CI chạy) và báo kết quả.
6. Chạy thật trên dữ liệu của owner (chỉ đọc):
     python scripts/eval_regrade.py v2 --run-dir "E:\hệ thống\deepseek_ref-20261116T081916Z-1-001\deepseek_ref\A" --suites evals/suites --out <thư mục tạm ngoài repo>\regrade_v2.json
   Kỳ vọng: đúng 2 lượt lật hỏng → đạt (s03_024 lượt 1, s04_004 lượt 1), 0 lượt đạt → hỏng. Nếu khác, DỪNG và báo, không chỉnh ngưỡng cho khớp.
     python scripts/eval_regrade.py v2 --run-dir "<thư mục qwen_rec\A owner đưa>" --suites evals/suites --out <thư mục tạm ngoài repo>\regrade_v2_qwen.json
   (Qwen chưa có kỳ vọng sẵn: chỉ cần chạy được, ghi số lượt lật hai chiều.)
     python scripts/eval_regrade.py export --label deepseek --run-dir "E:\...\deepseek_ref\A" --suites evals/suites --out <thư mục tạm ngoài repo>\judge_test_deepseek
     python scripts/eval_regrade.py export --label qwen --run-dir "<qwen_rec\A>" --suites evals/suites --out <thư mục tạm ngoài repo>\judge_test_qwen
   (Mỗi thư mục chấm chỉ một model; không trộn.)
   Ghi số mục theo loại và số lô vào báo cáo. Không commit dữ liệu thật hay gói chấm vào repo. Thư mục judge_test chỉ để thử; owner sẽ xuất lại vào thư mục chấm thật sau khi merge.
7. Viết docs/phase_role_aware_ops/W6_4_4_EXECUTION_REPORT_<ngày>.md: tệp đã sửa, kết quả test, kết quả bước 6, điểm còn ngờ.
8. Commit theo từng bước rõ ràng, push nhánh, mở PR vào main. KHÔNG merge.

Cấm: sửa evals/suites/*; sửa logic chấm của runner; thêm thư viện; gọi bất kỳ API LLM nào; merge; push main; force-push/rebase/reset/stash; đổi biến/secret repo; chạy workflow deploy hay live-e2e; chạm EC2, SSM, DB production, Colab; dán khóa hay dữ liệu cá nhân vào bất cứ đâu.
Nếu thiết kế mâu thuẫn với code thật hoặc thiếu thông tin, hỏi lại owner bằng câu hỏi trắc nghiệm ngắn, không tự đoán.
```
