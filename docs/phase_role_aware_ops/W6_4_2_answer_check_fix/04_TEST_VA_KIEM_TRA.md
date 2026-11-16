# 04 — Test, lệnh kiểm và báo cáo

## 1. Môi trường trên máy owner (Windows)

- Python có sẵn `pypdfium2`: `%TEMP%\venv_pdf\Scripts\python.exe`. Luôn đặt `PYTHONUTF8=1`. Khi chạy một module test lẻ thì đặt thêm `PYTHONPATH=tests`.
- Máy **không có Node thật**: `node.cmd` trong PATH là bản giả, luôn thoát mã 0 mà không chạy gì. Nếu không tìm được Node thật thì ghi "test JS: không chạy được trên máy, CI kiểm", **không** ghi là đạt.
- Ghi tệp `.md` bằng xuống dòng LF. Trên Windows, `Path.write_text` mặc định ghi CRLF: dùng `write_bytes` hoặc `newline=''`.
- Không chạy test có cờ thời gian thật song song với bộ test đầy đủ.

## 2. Test phải viết trước (thấy FAIL trên code chưa sửa, ghi lại dòng lỗi)

Một tệp mới `tests/test_w642_answer_check.py`. Mỗi test là một hàm riêng, tên nói rõ điều đang kiểm. Dùng payload tổng hợp, **không** phụ thuộc giờ thật. Hàm tiện ích giống các test cũ:

```python
def messages(payload, name='get_order'):
    return [{'role': 'tool', 'tool_name': name, 'content': json.dumps(payload, ensure_ascii=False)}]
```

Dữ liệu dùng chung:

```python
ITEMS_91 = [{'name': 'Áo sơ mi lụa công sở', 'variant': 'Trắng · Size M', 'quantity': 1, 'unit_price': 450000, 'subtotal': 450000},
            {'name': 'Quần tây đen hàn quốc', 'variant': 'Đen · Size M', 'quantity': 2, 'unit_price': 520000, 'subtotal': 1040000}]
ORDER_91 = {'order': {'id': 'ord_91', 'external_order_id': 'SIM-O-00091', 'amount': 1530000, 'shipping_fee': 40000,
                      'items': ITEMS_91,
                      'eligibility': {'late_by_hours': 72.0, 'days_since_delivery': 4.3169, 'return_window_days': 7,
                                      'size_exchange_window_days': 15, 'warranty_window_days': 90,
                                      'within_return_window': True}}}
LIST_3 = {'orders': [
    {'id': 'ord_91', 'external_order_id': 'SIM-O-00091', 'amount': 1530000, 'shipping_fee': 40000,
     'items': [{'name': i['name'], 'quantity': i['quantity'], 'subtotal': i['subtotal']} for i in ITEMS_91]},
    {'id': 'ord_58', 'external_order_id': 'SIM-O-00058', 'amount': 440000, 'shipping_fee': 20000,
     'items': [{'name': 'Áo thun', 'quantity': 1, 'subtotal': 420000}]},
    {'id': 'ord_57', 'external_order_id': 'SIM-O-00057', 'amount': 179000, 'shipping_fee': 30000,
     'items': [{'name': 'Tất', 'quantity': 1, 'subtotal': 149000}]}],
    'total_count': 3, 'has_more': False}
```

### Hàng 1 — tiền

- Với `messages(ORDER_91)`, ba dòng sau **giữ nguyên**; không có bằng chứng thì kết quả là `POLICY_NOTE`:
  - `- Tiền hàng 1.490.000₫ + phí ship 40.000₫ = 1.530.000₫`
  - `- Áo sơ mi lụa công sở 450.000₫, Quần tây đen hàn quốc 1.040.000₫; phí vận chuyển 40.000₫.`
  - `- Đơn giá Quần tây đen hàn quốc 520.000₫ × 2, phí ship 40.000₫.`
- Với `messages(ORDER_91)` vẫn bỏ: `Phí ship đơn này là 35.000đ ạ.`, `Phí đổi hàng là 450.000đ ạ.`, `Shop miễn phí ship đổi size lần đầu ạ.`
- `tool_evidence(messages(ORDER_91))`: `money_amounts` chứa `450000`, `520000`, `1040000`; `derived_money == frozenset({1490000})` (một đơn nên không có tổng nhiều đơn).
- `tool_evidence(messages(LIST_3, 'list_orders')).derived_money == frozenset({1490000, 420000, 149000, 2149000, 90000, 2059000})` (tiền hàng từng đơn; tổng `amount` 1.530.000 + 440.000 + 179.000; tổng phí ship; tổng tiền hàng 1.490.000 + 420.000 + 149.000). Với bằng chứng đó giữ `Tổng phí ship 3 đơn: 90.000₫.` và `Tổng chi 2.149.000₫, trong đó phí ship 90.000₫.`
- Khử trùng: `messages(LIST_3, 'list_orders') + messages(ORDER_91)` cho cùng `derived_money` như trên.
- Thêm `messages({'payments': [{'payment_id': 'pay_1', 'amount': 999000}]})` vào bằng chứng: các tổng không đổi.
- `subtotal` là `True`, `'450000'`, `450000.0`, hoặc một món thiếu `subtotal`: không có tiền hàng của đơn đó; `items` rỗng: không thêm gì.
- Hồ sơ đơn thiếu cả `id` lẫn `external_order_id` (như payload của test cũ): không tính vào tổng nhiều đơn.

### Hàng 2 — thời gian

- `tool_evidence(messages(ORDER_91)).derived_time == frozenset({72, 3, 4, 5, 2, 10, 11, 85, 86})`.
- Với `messages(ORDER_91)` giữ nguyên; không có bằng chứng thì bị bỏ:
  - `**SIM-O-00091 — trễ hạn 72 giờ, sắp hết hạn trả hàng**`
  - `- Hạn đổi size còn khoảng 10 ngày.`
  - `- Đã giao được 4 ngày, trong hạn trả 7 ngày.`
  - `- Đơn giao hàng trễ, quá hạn 3 ngày.`
- Với `messages(ORDER_91)` vẫn bỏ: `- Hạn đổi size còn 12 ngày.`, `Shop cho đổi trong 30 ngày ạ.`
- `late_by_hours` là `0.0`, `None`, `'72'`, `True`: không thêm số giờ hay số ngày trễ.
- `days_since_delivery = 20.0` với cửa sổ 7, 15, 90: thêm `20`, `70` (90 − 20); không thêm số nào cho cửa sổ 7 và 15.

### Hàng 3 — dòng tiêu đề

- Mỗi dòng ở bảng 03 mục 3.3, không có bằng chứng: dòng đầu của `result.text` đúng cột "Sau W6.4.2" (kết quả là `<dòng> + '\n\n' + POLICY_NOTE`, hoặc chỉ `POLICY_NOTE` nếu dòng trống); `dropped_policy == 1`.
- Câu trả lời dạng smoke, không có bằng chứng:

```text
**SIM-O-38588564-01 — đơn đúng hạn**
- Giao 05/11, sớm hơn mốc cam kết 06/11.

**SIM-O-38588564-03 — trễ hạn 72 giờ, sắp hết hạn trả hàng**
- Cam kết 06/11 nhưng giao 09/11.

**SIM-O-38588564-02 — đang giao**
- Đang ở trạm trung chuyển Đà Nẵng.
```

  Kết quả còn đủ 3 tiêu đề theo đúng thứ tự, tiêu đề thứ hai là `**SIM-O-38588564-03**` và nằm ngay trên dòng `- Cam kết 06/11 nhưng giao 09/11.`; `dropped_policy == 1`; có đúng một `POLICY_NOTE`.
- `1. Shop miễn phí đổi trả 2 chiều.` → chỉ còn `POLICY_NOTE` (mục 3.4, không còn "1." treo).
- Lũy đẳng: chạy `check_final_answer` lần nữa trên mọi kết quả ở hàng này thì `changed` là `False` và văn bản không đổi.

### Hàng 4 — chi tiết

- Văn bản 5 dòng, không có bằng chứng: (1) `Shop đổi size tận nhà cho anh/chị ạ.` (2) `Phí ship đơn này là 35.000đ ạ.` (3) `Thời hạn đổi trả là 30 ngày.` (4) `Em đã hủy đơn SIM-O-00115 cho anh/chị rồi ạ.` (5) `Em đã chuyển cuộc trò chuyện cho nhân viên rồi ạ.` → `details` đúng thứ tự `logistics`, `fee_amount`, `deadline_number`, `done_claim`, `handoff_claim`, với `line` 1–5 và `kind` tương ứng ở 03 mục 4.2; `len(details) == dropped_policy + dropped_claims`. Claude đã chạy cả 5 câu trên `3239454`: mỗi câu đều bị bỏ đúng loại.
- `Shop miễn phí đổi hàng ạ.` → `rule == 'policy_fee'` (câu có "2 chiều" sẽ rơi vào `logistics` vì luật hậu cần xét trước). `Thời hạn đổi trả là bao lâu thì em chưa rõ, em sẽ kiểm tra thêm.` → không bị bỏ. Một câu thời hạn không số, không cờ (`Đơn còn trong thời hạn đổi trả ạ.`, không bằng chứng) → `deadline_no_fact`.
- Dòng tiêu đề được thay bằng nhãn → `heading_label_kept` là `True`; các dòng khác là `False`.
- Mọi phần tử đúng 4 khóa; không phần tử nào chứa chuỗi của câu bị bỏ (so `json.dumps(details, ensure_ascii=False)` với từng câu).
- Văn bản không bị sửa → `details == ()`.
- **Ứng dụng**, theo mẫu `FinalAnswerInApplicationTests` trong `tests/test_r1_w3_2_answer_check.py`, chạy cả `agent` và `legacy`: model gọi `get_order` rồi nói `Đơn O-701 đã giao. Shop sẽ đổi size tận nhà miễn phí 2 chiều cho anh/chị ạ.` → `trace['answer_check'] == {'dropped_policy_promises': 1, 'dropped_done_claims': 0}`; `trace['answer_check_detail'] == [{'line': 1, 'kind': 'policy', 'rule': 'logistics', 'heading_label_kept': False}]`; `result['message']` và `json.dumps(trace['answer_check_detail'], ensure_ascii=False)` không chứa `tận nhà`. Lượt có trích dẫn hợp lệ thì không có `answer_check_detail`. Nếu chữ của câu bị bỏ vẫn xuất hiện ở chỗ khác trong JSON trả về (ví dụ vết suy luận hay vết từng bước), **ghi vào báo cáo**, không sửa: đó là việc của F20.
- **Runner**, theo mẫu `RunnerRailTests` trong `tests/test_r1_w6_3_1_hotfix.py` (lấy `runner.load_dataset()[0]`, thay `turns`): một lượt mà model giả nói câu có lời hứa không trích dẫn → bản ghi lượt có `answer_check` với `detail` đúng; `answer` và `answer_check` của bản ghi lượt không chứa câu bị bỏ. Một lượt không bị sửa → không có khóa `answer_check`.

**Không sửa test cũ.** Nếu một test có sẵn đỏ sau khi sửa, dừng lại, ghi tên test và dòng lỗi vào báo cáo, hỏi owner.

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

Chạy riêng 4 tệp test cũ của bộ kiểm và ghi số test đạt: `test_r1_w3_2_answer_check`, `test_r1_w6_3_1_hotfix`, `test_r1_w6_3_2_hotfix`, `test_r1_w6_3_4_answer_check`.

Cộng với test JS theo `.github/workflows/ci.yml` nếu có Node thật.

## 4. Số đo phải ghi vào báo cáo

1. **Bảng 11 dòng ở 01 mục 6**, chạy trên `origin/main` và trên nhánh của bạn, mỗi dòng ghi "giữ" hoặc "bỏ". Dựng như Claude đã làm: fixture `standard`, khách `SIM-C-0057`, gán `SIM-O-00091` và 2 đơn khác cho khách, đặt `promised_delivery_by = delivered_at - 72*3600` cho `SIM-O-00091`, bằng chứng là kết quả thật của `get_order('SIM-O-00091')` hoặc `list_orders()` qua `BoundTools`. Script đo để ngoài repo hoặc xóa trước khi commit.
2. **Kích thước bằng chứng suy ra trên fixture `standard`:** với mỗi đơn có trong fixture, gọi `get_order` rồi đếm `len(derived_time)` và `len(derived_money)`; ghi nhỏ nhất, trung vị, lớn nhất. Đây là thước đo rủi ro chấp nhận ở 03 mục 1.3 và 2.
3. **Runner giả 250 ca:** số lượt có khóa `answer_check` trong báo cáo, và đếm theo `rule`. Không sửa ca nào vì con số này.

## 5. Báo cáo

Ghi vào `docs/phase_role_aware_ops/W6_4_2_EXECUTION_REPORT_2026-11-15.md` trên nhánh `phase-r1-w6-4-2`, xuống dòng LF. Thư mục handoff chưa có trên `main`, nên **không dùng link Markdown tương đối** tới các tệp handoff (`check_docs_contract.py` sẽ báo link hỏng); nhắc tới chúng bằng tên tệp trong dấu backtick. Báo cáo gồm:

- điều kiện bắt đầu (SHA của `origin/main`, tên nhánh);
- bảng 5 hàng: DONE hoặc BLOCKED, tệp đã đổi;
- bằng chứng FAIL trước khi sửa của từng hàng 1–4 (lệnh và dòng lỗi);
- xác nhận không sửa test cũ, kèm số test đạt của 4 tệp test cũ;
- kết quả từng lệnh ở mục 3;
- ba số đo ở mục 4;
- hai rủi ro chấp nhận ở 03 mục 1.3 và 2, kèm số đo 4.2;
- những chỗ khác bộ kiểm cũng cắt nhầm, nếu thấy (chỉ ghi, không sửa);
- tên nhánh, URL PR, kết quả CI nếu có.

Thêm một dòng mới vào `docs/phase_role_aware_ops/W1_EXECUTION_LOG_2026-10-31.md` theo đúng mẫu dòng 040 (W6.4.1), ghi "Gemini 4 Hydrogen (Antigravity)" ở ô người thực hiện; không sửa dòng cũ.
