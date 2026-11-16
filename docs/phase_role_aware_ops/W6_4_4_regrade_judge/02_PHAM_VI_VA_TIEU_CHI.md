# 02 — Phạm vi và tiêu chí nghiệm thu

## Trong phạm vi (PR code của Hydrogen)

1. **Runner lưu đủ câu trả lời** cho các lượt đo sau này (đo lại sau SFT): bỏ cắt 600 ký tự ở `answer` và `draft_reply` trong báo cáo (`scripts/run_agent_scenarios.py` khoảng dòng 882, 892). Không đổi cách chấm, không đổi `grade_turn`, `squash`, `attack_success`.
2. **Script mới `scripts/eval_regrade.py`**, chỉ thư viện chuẩn Python, ba lệnh:
   - `v2`: chấm lại các kiểm tra chữ bằng bộ chuẩn hóa v2 → `regrade_v2.json`.
   - `export`: xuất **gói chấm ẩn danh** cho giám khảo (các kiểm tra chữ còn hỏng sau v2 + mọi ca bị đánh dấu tấn công + mẫu đối chứng) → `packets/batch-NN.jsonl` + `map.json` (ánh xạ, giám khảo không được đọc).
   - `import`: đọc phiếu chấm của hai giám khảo, kiểm trích dẫn, gộp theo quy tắc bảo thủ → `adjudicated.json` + `summary.md` (ba con số mỗi model, theo bộ, danh sách ca lật, bất đồng giữa giám khảo, mẫu kiểm định cho owner).
3. Test offline cho cả ba lệnh và cho thay đổi runner.

## Ngoài phạm vi

- Sửa `evals/suites/*`, sửa danh sách cụm của ca, đổi số chính thức.
- Chấm lại các kiểm tra không phải chữ (tool, hành động, trạng thái cuối, số tool tối đa, nguồn) — giữ nguyên kết quả gốc.
- Gọi API LLM từ code. Giám khảo là các bot Gemini đọc tệp, không phải code gọi API.
- Sửa bộ lọc production (`answer_check`, `topic_filter`) — các ứng viên F53–F55 để W6.5.

## Tiêu chí nghiệm thu PR

- Toàn bộ test cũ xanh; test mới phủ: chuẩn hóa v2 (bảng ví dụ ở 03), giữ `'****'`, không có cụm rỗng, bốn loại nguồn văn bản, quy tắc lật một chiều, gói chấm không lộ tên model/mã ca thật, kiểm trích dẫn, quy tắc gộp hai giám khảo, ba con số.
- Chạy `v2` trên dữ liệu DeepSeek thật của owner cho ra đúng 2 lượt lật hỏng → đạt (`s03_024` lượt 1, `s04_004` lượt 1) và **0** lượt đạt → hỏng. Ghi kết quả vào báo cáo thực thi.
- `export` trên DeepSeek tạo gói chấm; số mục và số lô ghi trong báo cáo thực thi.
- Không thêm thư viện; không sửa tệp ngoài danh sách ở 03.
- Báo cáo thực thi: `docs/phase_role_aware_ops/W6_4_4_EXECUTION_REPORT_<ngày>.md`.
