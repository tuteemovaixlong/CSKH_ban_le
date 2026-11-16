# 07 — Các lệnh sau khi PR code được merge

Bước 1, 2 và 4 thường giao cho phiên Hydrogen H-op, bước 3 cho các phiên giám khảo, theo [06](06_PROMPT_GIAM_KHAO.md). Owner tự làm bước 5–6. Các lệnh dưới đây để tra cứu hoặc chạy tay khi cần.

Chạy trên máy owner, trong repo đã `git pull` về `main`. **Mỗi model một thư mục chấm riêng, đặt ngoài repo, không trộn**: ví dụ `E:\hệ thống\w64_judge_qwen` và `E:\hệ thống\w64_judge_deepseek`.

1. **Chấm lại v2 cho từng model** (vài giây mỗi lệnh):
   ```text
   python scripts/eval_regrade.py v2 --run-dir "<qwen_rec\A>" --suites evals/suites --out "<qwen_rec\A>\regrade_v2.json"
   python scripts/eval_regrade.py v2 --run-dir "<deepseek_ref\A>" --suites evals/suites --out "<deepseek_ref\A>\regrade_v2.json"
   ```
2. **Xuất gói chấm ẩn danh, mỗi model một thư mục**:
   ```text
   python scripts/eval_regrade.py export --label qwen --run-dir "<qwen_rec\A>" --suites evals/suites --out "E:\hệ thống\w64_judge_qwen"
   python scripts/eval_regrade.py export --label deepseek --run-dir "<deepseek_ref\A>" --suites evals/suites --out "E:\hệ thống\w64_judge_deepseek"
   ```
3. **Giao các phiên Hydrogen giám khảo** theo [06_PROMPT_GIAM_KHAO.md](06_PROMPT_GIAM_KHAO.md) bước 2–3 (mỗi phiên nhận xen kẽ lô của cả hai model). Chờ đủ phiếu nhóm A và B cho mọi lô.
4. **Gộp phiếu, từng model**:
   ```text
   python scripts/eval_regrade.py import --judge-dir "E:\hệ thống\w64_judge_qwen" --suites evals/suites --out "E:\hệ thống\w64_judge_qwen\adjudicated.json"
   python scripts/eval_regrade.py import --judge-dir "E:\hệ thống\w64_judge_deepseek" --suites evals/suites --out "E:\hệ thống\w64_judge_deepseek\adjudicated.json"
   ```
   Nếu import báo lỗi phiếu (thiếu, trùng, `item_id` lạ), giao lại đúng lô đó cho một phiên mới cùng nhóm.
5. **Chấm tay mẫu kiểm định**: với từng thư mục chấm, mở `audit_sheet.csv` (20 mục), điền `owner_verdict` (`dat`/`khong_dat`) theo đúng [04_HUONG_DAN_CHAM.md](04_HUONG_DAN_CHAM.md), không xem kết luận của giám khảo trước. Lưu thành `audit_sheet_filled.csv` trong cùng thư mục, rồi:
   ```text
   python scripts/eval_regrade.py audit --judge-dir "E:\hệ thống\w64_judge_qwen" --sheet "E:\hệ thống\w64_judge_qwen\audit_sheet_filled.csv"
   python scripts/eval_regrade.py audit --judge-dir "E:\hệ thống\w64_judge_deepseek" --sheet "E:\hệ thống\w64_judge_deepseek\audit_sheet_filled.csv"
   ```
   Tổng 40 mục của hai model cũng thay cho phần lớn 30 ca chấm tay W6.4-D6.
6. **Gửi Claude** hai tệp `summary.md` (mỗi tệp có ba con số, độ khớp hai giám khảo, đối chứng, độ khớp với owner). Claude chỉ đọc bảng tổng hợp và vài ca lật, rồi viết báo cáo W6.4 (`W6_4_measurement/`) và các dòng §32. Không cần gửi lại toàn bộ dữ liệu.

## Cách đọc kết quả

- **Số chính thức** (bộ chấm gốc) là số chính trong khóa luận. **v2** cho thấy phần thua do định dạng. **Sau xem xét** cho thấy phần thua do chấm theo chữ, kèm phương pháp và độ khớp.
- Nếu độ khớp owner–giám khảo dưới 85%, hoặc đối chứng dưới 90% `dat`, chỉ báo số chính thức và v2 cho model đó; số "sau xem xét" ghi là không đủ tin cậy.
- Giữ `map.json`, gói chấm, phiếu và `summary.md` của cả hai thư mục đến hết bảo vệ (lưu cùng kết quả đo trên Drive).
