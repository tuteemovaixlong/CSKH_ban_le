# Báo cáo bổ sung G — Chặn vết cũ và giá trị giả của bộ đo

Nhánh: `phase-r1-w6-7-3-khung-do`. Mốc trước G:
`0f21789f1a37dd99d38dc31d46fd3e930e6c3c85`.
SHA commit bổ sung được ghi trong tin bàn giao sau push.

## Vấn đề và thay đổi

So riêng user của lượt không nhận ra ca Trợ lý ca đã đổi tin khách/tệp đính kèm trong case_setup.
Vì vậy các thư mục vết cũ cần được loại theo danh sách ca do Claude xác định, kể cả khi vết từng có A_code/Tier A.

- Mỗi mục `runs.json` nhận thêm `exclude_cases`: đường dẫn tệp UTF-8 (có thể có BOM), một case_id mỗi dòng;
  bỏ qua dòng trống. Chỉ các ứng viên của mục đó có mã trong danh sách bị loại với `stale_input`.
- `sft_select score --exclude-cases FILE` áp danh sách chung cho mọi thư mục/model. Có thể kết hợp danh sách
  chung và danh sách riêng; kết quả là hợp hai danh sách. Không có danh sách thì giữ nguyên đầu ra cũ.
- `sft_build` kiểm toàn bộ tin nhắn của mẫu sau chuẩn hóa/lớp phủ, gồm system, tin khách/nhân viên,
  tin trợ lý trước đó, kết quả tool, câu trả lời cuối và suy luận. Mẫu chứa giá trị giả được loại với
  `eval_value`; stats.json ghi trong rejected.by_reason và rejected.items (kèm eval_values),
  build_report.md có số lượng và danh sách mã mẫu/ca/run/lượt/giá trị trùng.
- `VALUE_RE`, `strings()` và `eval_values()` được chuyển nguyên quy tắc từ test sang
  `scripts/sft_eval_values.py`. Test và build dùng đúng bộ nhận diện này. Tham số thư mục bộ đo tùy chọn
  khớp với `sft_build` hiện có; mặc định vẫn đọc evals/suites. Không thêm trường stats/report khi không có mẫu nhiễm,
  nên dữ liệu giả cũ sạch cho đầu ra trùng từng byte.

## CLI

```text
python scripts/sft_select.py score --cases cases_filled.jsonl --runs runs.json --out scores.json
python scripts/sft_select.py score --cases cases_filled.jsonl --run-dir qwen=run_qwen_v3 --run-dir deepseek=run_ds_v3 --exclude-cases stale_v3_ids.txt --out scores.json
python scripts/sft_build.py --selection selection.json --cases cases_filled.jsonl --out-dir sft
```

Ví dụ một mục trong runs.json (chỉ cấu hình công cụ, không phải nội dung gợi ý):

```json
{"label":"qwen_v3","model":"qwen","dir":"run_qwen_v3","run_offset":0,"hinted":false,"hint_log":null,"exclude_cases":"stale_v3_ids.txt"}
```

Danh sách ca cũ do Claude/owner cung cấp cho từng thư mục vết; không hard-code khung T11 hay mã ca cụ thể trong công cụ.
Không đọc lại dữ liệu thật v3, không sửa bộ đệm lời khách và không chạy model.

## Tệp đổi

- scripts/sft_select.py: danh sách loại ca theo thư mục và cờ dùng chung.
- scripts/sft_build.py: phòng thủ eval_value, thống kê và danh sách trong báo cáo.
- scripts/sft_eval_values.py: module dùng chung mới.
- tests/test_w671_sft_no_eval_values.py: dùng lại module chung, không giữ bản sao bộ nhận diện.
- tests/test_w673_stale_eval_values.py: 5 test mới, gồm 7 vị trí tin nhắn trong test phòng thủ.
- notebooks/colab_agent.ipynb: dựng lại; không chạy Colab/notebook.
- Báo cáo bổ sung này và liên kết từ báo cáo A–F.

## Kiểm chứng

- T11 thay case_setup/tệp đính kèm, user giữ nguyên: mục run có exclude_cases bị stale_input;
  cùng ca ở thư mục mới không có danh sách vẫn giữ; ca ngoài danh sách cũng giữ.
- Cờ CLI dùng chung loại đúng ứng viên của cả Qwen và DeepSeek.
- Giá trị bộ đo trong tool result và sáu vị trí khác đều bị eval_value, có danh sách trong stats/report,
  không xuất vào train.jsonl.
- So với đúng mốc trước G: scores dạng --run-dir và --runs không có danh sách loại trùng byte;
  train.jsonl, val.jsonl, stats.json và build_report.md của dữ liệu giả cũ sạch trùng byte.
- Test xác nhận VALUE_RE/eval_values/strings của test chính là cùng các đối tượng do module dùng chung cung cấp.

| Lệnh/nhóm kiểm | Kết quả |
|---|---|
| `unittest tests.test_w673_stale_eval_values` | 5/5 qua |
| `unittest discover -s tests -p "test_w673_*.py"` | 21/21 qua, gồm 180/180 ca T14 qua gateway giả |
| `unittest discover -s tests -p "test_w672_*.py"` | 11/11 qua |
| Nhóm bảy module hồi quy SFT/regrade/cache/export/no_eval_values ở 04 | 64 test, không lỗi; 1 test PDF bỏ qua vì thiếu pypdfium2 |
| `test_audit_remediation` | 10/10 qua |
| `build_agent_notebook.py --check` | Đồng bộ |
| `check_docs_contract.py`, `git diff --check` | Qua |

Bổ sung G chỉ đổi công cụ, kiểm dữ liệu và test; bộ sinh ca/phiếu, ứng dụng, runner, system prompt và evals/suites không đổi.
Không chạy lại toàn bộ test ứng dụng trong lượt bổ sung G; đã chạy nhóm SFT liên quan và kiểm hồi quy byte.
Kết quả bộ đầy đủ A–F trước đó (5 lỗi Windows trong checkout sạch, thêm lỗi môi trường ở checkout chính) được giữ riêng trong
[báo cáo A–F](BAO_CAO.md), không trình bày như kết quả chạy lại sau G.
