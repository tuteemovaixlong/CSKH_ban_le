# 04 — Test, lệnh kiểm và báo cáo

## 1. Môi trường trên máy owner (Windows)

- Python có sẵn `pypdfium2`: `%TEMP%\venv_pdf\Scripts\python.exe`. Luôn đặt `PYTHONUTF8=1`. Khi chạy một module test lẻ thì đặt thêm `PYTHONPATH=tests`.
- Máy **không có Node thật**: `node.cmd` trong PATH là bản giả, luôn thoát mã 0 mà không chạy gì. Nếu không tìm được Node thật thì ghi "test JS: không chạy được trên máy, CI kiểm", **không** ghi là đạt.
- Ghi tệp `.md` bằng xuống dòng LF. Trên Windows, `Path.write_text` mặc định ghi CRLF: dùng `write_bytes` hoặc `newline=''`.
- Không chạy test có cờ thời gian thật (`time.sleep` dài) song song với bộ test đầy đủ.

## 2. Test phải viết trước (thấy FAIL trên code chưa sửa, ghi lại dòng lỗi)

Đặt tên tệp như sau. Mỗi test là một hàm riêng, có tên nói rõ điều đang kiểm.

### `tests/test_w641_context.py` (hàng 1)

- Chạy `python -c` ở tiến trình con, lần lượt với biến `RETAILOPS_MODEL_CONTEXT_TOKENS` không đặt, `16384`, `32768`, `8192`, rồi in `agent_protocol.CONTEXT_TOKENS`, `agent_protocol.MAX_CHARACTERS`, `compaction.TOOL_RESULT_MAX_CHARS`. Kỳ vọng: `(16384, 36000, 5200)`, `(16384, 36000, 5200)`, `(32768, 72000, 10400)`, `(8192, 18000, 2600)`.
- Giá trị `2048` và `200000`: tiến trình con thoát khác 0 và thông báo có `RETAILOPS_MODEL_CONTEXT_TOKENS`.
- Import riêng `agent_protocol`, riêng `retailops.workflow.compaction`, riêng `retailops.workflow.agent` ở tiến trình con mới: đều thành công (không import vòng).
- **Đúng thứ tự import của runner:** ở tiến trình con, không đặt biến, `import retailops_providers` trước; sau đó mới đặt `os.environ['RETAILOPS_MODEL_CONTEXT_TOKENS'] = '32768'` rồi `import retailops.workflow.compaction`. Kỳ vọng `agent_protocol.max_characters() == 72000` và `compaction.TOOL_RESULT_MAX_CHARS == 10400`.
- Runner thật: `run_agent_scenarios.main(['--fake', '--context-tokens', '32768', '--only', <một ca>, '--out', …])` ở tiến trình con mới. Thay `retailops.workflow.agent.fit_transcript` bằng hàm bọc ghi lại tham số `limit`, rồi kiểm `limit == 72000 - 200`.

### `tests/test_w641_list_orders.py` (hàng 2)

Dựng fixture như `tests/test_w64_order_items.py` (`runner.World({'fixture': 'standard', 'customer': 'SIM-C-0057'}, runner.ScriptedGateway())`). Muốn có nhiều đơn thì gán thêm đơn cho khách trong fixture bằng `UPDATE orders SET customer_id=?` trong `store.connection(write=True)`.

- Mỗi đơn trong kết quả có **đúng** tập khóa ở 03 mục 2.1 (bỏ qua khóa mà hồ sơ không có), không có khóa nào trong danh sách "Không giữ".
- SIM-O-00091: `items == [{'name': 'Áo sơ mi lụa công sở', 'variant': 'Trắng · Size M', 'quantity': 1, 'subtotal': 450000}, {'name': 'Quần tây đen hàn quốc', 'variant': 'Đen · Size M', 'quantity': 2, 'subtotal': 1040000}]`.
- Không truyền tham số: tối đa 5 đơn, `ordered_at` giảm dần, đúng các khóa cấp trên ở 03 mục 2.3.
- Duyệt bằng `offset=next_offset` tới khi `has_more` false: đi qua đủ `total_count` đơn, không trùng, không sót.
- `offset >= total_count`: `orders` rỗng, `has_more` false, có `note`.
- `limit` là `0`, `21`, `'abc'`, `True`; `offset` là `-1`: trả `{'error': 'invalid_arguments', …}`, không ném exception.
- `validate_tool('list_orders', {})`, `{'limit': 5}`, `{'limit': '5', 'offset': '10'}` hợp lệ và trả về số nguyên. Các trường hợp `{'limit': True}`, `{'limit': 0}`, `{'limit': 21}`, `{'offset': -1}`, `{'page': 1}` báo `ProtocolError`. `validate_tool('get_order', {'order_id': 5})` vẫn báo `ProtocolError`, vì luật chuỗi của các tool khác không đổi.
- Schema trong `TOOLS`: `list_orders` có `limit`, `offset`, `required == []`, và mô tả đúng nguyên văn 03 mục 2.4.
- **Hồi quy F44:** ở cấu hình mặc định 16k, kết quả `list_orders` với 5 đơn của fixture có đủ dữ liệu: `compact_tool_result(result) == dump(result)`, tức không phải rút gọn và còn đủ 5 đơn.
- Tương thích: `order_agent._order(tóm_tắt)` không trả `None` với mọi đơn; khi `has_more` true thì `truncated` true, và rào an toàn ở `topic_filter.py` vẫn nối câu nhắc nếu câu trả lời không nói danh sách chưa đủ.

### `tests/test_w641_case_orders.py` (hàng 3)

- `list_case_orders`: mỗi đơn đúng tập khóa ở 03 mục 3; có `total_count`, `truncated`; giữ `case_id`, `orders`, `count`.
- `get_case_order` vẫn có `eligibility` và `items` đầy đủ (có `unit_price`).
- Mô tả tool đúng nguyên văn.

### `tests/test_w641_compaction.py` (hàng 4)

- Một danh sách 3 dict, mỗi dict có vài chuỗi dài, tổng vượt `limit` chỉ vì chuỗi: sau rút gọn **còn đủ 3 phần tử**, có `_truncated: true`. Đây là test hồi quy F44; code cũ sẽ chỉ giữ 2.
- Một danh sách mà pha A chưa đủ nhưng bỏ `metadata` lồng bên trong thì vừa: còn đủ phần tử, không còn `metadata`.
- Khóa `note` ở cấp trên cùng được giữ; `note` ở cấp lồng thì bị bỏ ở pha B.
- Danh sách quá lớn phải sang pha C: phần tử cuối là chuỗi ghi chú tiếng Việt ở 03 mục 4, có số mục bị ẩn đúng.
- Bất biến: JSON hợp lệ; độ dài ≤ `limit` với mọi `limit` từ 200 tới 12.000; kết quả vừa sẵn thì trả nguyên văn.

**Test cũ có thể phải sửa** vì thứ tự rút gọn hoặc câu ghi chú thay đổi: `tests/test_r1_w3_2_agent_loop.py` (quanh dòng 300–360), `tests/test_r1_w6_3_runner.py`, `tests/test_w64_order_items.py` (kết quả `list_orders` và `list_case_orders` nay là bản tóm tắt; hai tool đó phải so với `items` rút gọn, bốn tool còn lại giữ kỳ vọng cũ). Chỉ được sửa phần kỳ vọng phụ thuộc trực tiếp vào thay đổi, phải giữ mọi bất biến, và **liệt kê từng chỗ sửa kèm lý do trong báo cáo**.

## 3. Lệnh phải chạy và báo đủ số pass, fail, skip

```bash
python -m unittest discover -s tests -q
python scripts/build_agent_notebook.py          # sinh lại notebook vì tests/ và mã nguồn đổi
python scripts/build_agent_notebook.py --check
python scripts/build_eval_pack.py --check
python scripts/check_docs_contract.py
python scripts/check_deployment_contract.py
python scripts/check_live_e2e_contract.py
python scripts/check_eval_dataset.py
python scripts/check_eval_dataset.py evals/suites --final
python scripts/run_agent_scenarios.py --fake --dataset evals/agent_scenarios_w3_2.jsonl
python scripts/run_agent_scenarios.py --fake --dataset evals/agent_scenarios_w4.jsonl
python scripts/run_agent_scenarios.py --fake --dataset khoa_luan/eval_pack/06_vi_du.jsonl
python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --min-success-rate 1.0
python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --context-tokens 32768 --min-success-rate 1.0
sha256sum evals/suites/*.jsonl                  # so với bảng trong evals/suites/README.md
git diff --check
```

Cộng với test JS theo `.github/workflows/ci.yml` nếu có Node thật.

## 4. Số đo phải ghi vào báo cáo

1. **Kích thước kết quả `list_orders`** trên fixture, trước và sau khi sửa, với 1, 3, 5, 10 và 20 đơn (bản trước chỉ trả tối đa 10). Mỗi ô ghi số ký tự JSON thô, số ký tự sau `compact_tool_result` ở 16k và ở 32k, và số đơn còn lại sau rút gọn.
2. **Độ dài `SYSTEM`** và `agent_system` có focus tối đa: phải giữ nguyên 5.993 và 6.284.
3. **Ca có thể bị ảnh hưởng (chỉ thống kê, không sửa ca):** trong 250 ca, đếm các lượt có `list_orders` trong `expect.tools_any` mà `max_tool_calls` ≤ 2. Liệt kê mã ca. Model thật ở những lượt này có thể cần thêm một lần `get_order` mới trả lời đủ.
4. **Phân bố số đơn mỗi khách** trong fixture `standard`: bao nhiêu khách có trên 5 đơn, tức là sẽ thấy `has_more`.

## 5. Báo cáo

Ghi vào `docs/phase_role_aware_ops/W6_4_1_EXECUTION_REPORT_2026-11-15.md` trên nhánh `phase-r1-w6-4-1`, xuống dòng LF. Thư mục handoff chưa có trên `main`, nên **không dùng link Markdown tương đối** tới các tệp handoff (`check_docs_contract.py` sẽ báo link hỏng); nhắc tới chúng bằng tên tệp trong dấu backtick. Báo cáo gồm:

- điều kiện bắt đầu (SHA của `origin/main`, tên nhánh);
- bảng 6 hàng: DONE hoặc BLOCKED, tệp đã đổi;
- bằng chứng FAIL trước khi sửa của từng hàng 1–5 (lệnh và dòng lỗi);
- danh sách test cũ đã sửa, kèm lý do;
- kết quả từng lệnh ở mục 3;
- bốn số đo ở mục 4;
- những chỗ khác cũng làm model thiếu dữ liệu, nếu thấy (chỉ ghi, không sửa);
- tên nhánh, URL PR, kết quả CI nếu có.

Thêm một dòng mới vào cột Antigravity trong `docs/phase_role_aware_ops/W1_EXECUTION_LOG_2026-10-31.md`, ghi rõ là W6.4.1; không sửa dòng cũ. Nếu bảng chưa có cột cho Antigravity thì thêm dòng theo đúng mẫu các dòng gần nhất và ghi "Gemini 4 Hydrogen (Antigravity)" ở ô người thực hiện.
