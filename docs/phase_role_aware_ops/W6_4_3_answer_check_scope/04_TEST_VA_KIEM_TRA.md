# 04 — Test, test cũ được phép sửa, lệnh kiểm và báo cáo

## 1. Môi trường trên máy owner (Windows)

- Python có sẵn `pypdfium2`: `%TEMP%\venv_pdf\Scripts\python.exe`. Luôn đặt `PYTHONUTF8=1`; chạy module test lẻ thì thêm `PYTHONPATH=tests`.
- Máy **không có Node thật** (`node.cmd` là bản giả). Không chạy được test JS thì ghi "CI kiểm", không ghi là đạt.
- Ghi `.md` bằng xuống dòng LF.
- Viết regex bằng chuỗi `r'...'`; nếu sửa tệp bằng script thì kiểm lại không có ký tự backspace (`\x08`) lọt vào tệp.

## 2. Test phải viết trước (thấy FAIL trên code chưa sửa, ghi lại dòng lỗi)

Một tệp mới `tests/test_w643_answer_check_scope.py`. Dùng payload tổng hợp, không phụ thuộc giờ thật. Mẫu tiện ích giống `tests/test_w642_answer_check.py`.

```python
LIST_2 = {'orders': [
    {'id': 'o2', 'external_order_id': 'SIM-O-38588564-02', 'status': 'shipping', 'ordered_at': '2026-11-09T10:00:00+07:00',
     'amount': 839000, 'shipping_fee': 40000, 'promised_delivery_by': '2026-11-13T23:59:00+07:00',
     'items': [{'name': 'Áo khoác Everyday', 'quantity': 1, 'subtotal': 799000}]},
    {'id': 'o1', 'external_order_id': 'SIM-O-38588564-01', 'status': 'delivered', 'ordered_at': '2026-11-03T09:00:00+07:00',
     'amount': 319000, 'shipping_fee': 20000, 'promised_delivery_by': '2026-11-06T23:59:00+07:00',
     'delivered_at': '2026-11-05T13:28:00+07:00', 'items': [{'name': 'Áo thun Essential', 'quantity': 1, 'subtotal': 299000}]}]}
GET_9 = {'order': {'id': 'o9', 'external_order_id': 'SIM-O-9', 'amount': 450000, 'shipping_fee': 0, 'status': 'delivered',
         'eligibility': {'warranty_window_days': 90, 'return_window_days': 7, 'size_exchange_window_days': 15,
                         'within_warranty': True},
         'shipment': {'carrier': 'GHN', 'shipper_phone': '090***1234'}}}
```

### Hàng 1 — bảng 12 dòng

Claude đã chạy cột giữa trên `ece0b0b` và cột phải trên bản nguyên mẫu.

| # | Dòng | Bằng chứng | `ece0b0b` | Sau W6.4.3 |
|---|---|---|---|---|
| 1 | `\| SIM-O-38588564-02 \| 09/11/2026 \| Áo khoác Everyday \| 839.000₫ (gồm phí ship 40.000₫) \| Đang vận chuyển \|` | `LIST_2` | xóa `fee_amount` | giữ, không ghi vết |
| 2 | `- Đặt ngày 2026-11-09, phí ship 40.000₫.` | `LIST_2` | xóa `fee_amount` | giữ, không ghi vết |
| 3 | `\| SIM-O-38588564-02 \| 839.000₫ \| Đang vận chuyển (trễ hạn 54 giờ) \|` | `LIST_2` | xóa `deadline_number` | giữ, ghi vết `deadline_number` |
| 4 | `Shipper 090***1234 sẽ giao hàng, phí ship 0đ ạ.` | `GET_9` | xóa `fee_amount` | giữ, không ghi vết |
| 5 | `Sản phẩm còn bảo hành 3 tháng ạ.` | `GET_9` | xóa `deadline_number` | giữ, ghi vết `deadline_number` |
| 6 | `Anh/chị được đổi hàng trong 7 ngày kể từ khi nhận hàng.` | `GET_9` | giữ | giữ, không ghi vết |
| 7 | `Thời hạn đổi trả là 30 ngày.` | `GET_9` | xóa `deadline_number` | giữ, ghi vết `deadline_number` |
| 8 | `Phí ship do shop chịu hoàn toàn.` | `GET_9` | xóa `fee_amount` | **xóa `policy_fee`** |
| 9 | `Đơn SIM-O-9 được miễn phí ship ạ.` | `GET_9` | xóa `policy_fee` | giữ, không ghi vết |
| 10 | `Đổi size lần đầu được miễn phí ship ạ.` | `GET_9` | xóa `policy_fee` | **xóa `policy_fee`** |
| 11 | `Shop đổi size tận nhà cho anh/chị ạ.` | `GET_9` | xóa `logistics` | **xóa `logistics`** |
| 12 | `Em đã hủy đơn SIM-O-9 cho anh/chị theo chính sách [KB:0123456789abcdef01234567].` | `GET_9` | xóa `done_claim` | **xóa `done_claim`** |

Thêm:
- Dòng 3, 5, 7 không có bằng chứng: vẫn giữ nguyên văn, ghi vết đúng luật; `changed` là `False`.
- Câu `Đơn còn trong thời hạn đổi trả ạ.` không bằng chứng: giữ, ghi vết `deadline_no_fact`.
- Một câu vừa dính `fee_amount` vừa dính `done_claim` (`Em đã hoàn tiền 35.000đ phí ship cho anh/chị rồi ạ.`, không bằng chứng): bị xóa với `done_claim`, không có ghi vết cho câu đó.
- Câu trả lời 3 dòng (dòng 1, dòng 3, dòng 11 ở trên, bằng chứng `LIST_2`): dòng 1 và 3 giữ; dòng 11 bị xóa; có đúng một `POLICY_NOTE`; `audit == ({'line': 2, 'rule': 'deadline_number'},)`.
- Mọi phần tử `audit` đúng 2 khóa `line`, `rule`; không chứa chuỗi của câu (so `json.dumps(audit, ensure_ascii=False)` với từng câu).
- Lũy đẳng: chạy `check_final_answer` lần nữa trên kết quả thì `changed` là `False` và văn bản không đổi.

### Hàng 2 — trace và runner

Theo mẫu `FinalAnswerInApplicationTests` (`tests/test_r1_w3_2_answer_check.py`), chạy cả `agent` và `legacy`:
- Model trả lời thẳng, không gọi tool: `Thời hạn đổi trả là 30 ngày.`. `result['message']` giữ nguyên câu đó; không có `answer_check`; `trace['answer_check_audit'] == [{'line': 1, 'rule': 'deadline_number'}]`.
- Model nói câu `logistics`: có `answer_check` và `answer_check_detail` như W6.4.2.
- Lượt sạch: không có `answer_check_audit`.

Theo mẫu `RunnerRailTests` (`tests/test_r1_w6_3_1_hotfix.py`): lượt có ghi vết thì bản ghi lượt có `answer_check_audit`; lượt sạch thì không.

### Hàng 3 — Trợ lý ca

Dựng theo các test Trợ lý ca hiện có (tìm `case_assist` trong `tests/`, ví dụ `tests/test_r1_w3_1_staff_assist.py`, `tests/test_w641_case_orders.py`):
- Câu trả lời có ghi chú nội bộ chứa `Shop đổi tận nhà miễn phí cho khách.` và thẻ `<draft_reply>Dạ shop sẽ đổi size tận nhà miễn phí cho anh/chị ạ.</draft_reply>`: ghi chú nội bộ giữ nguyên văn; `draft_reply` là bản đã kiểm (`POLICY_NOTE`); phần nháp trong câu trả lời cho nhân viên trùng `draft_reply`; trace có `answer_check` của bản nháp.
- Ghi chú nội bộ có `Ghi chú cho nhân viên: lỗi giao sai của shop được hoàn cả phí ship ban đầu.` (không thẻ nháp, chế độ không phải `draft`): giữ nguyên văn, không nối ghi chú nào.

### Hàng 4 — bộ kiểm thứ hai

Gọi thẳng `enforce_final_answer_grounding(user_text, reply, messages=…)`:
- Bằng chứng `{'order': {'id': 'ord_x', 'external_order_id': 'SIM-O-00091', 'status': 'cancelled'}}`, câu `Đơn SIM-O-00091 đã được hủy thành công ạ.`: giữ nguyên.
- Bằng chứng `{'order': {'id': 'ord_x', 'external_order_id': 'SIM-O-00091', 'status': 'delivered', 'payment_status': 'refunded'}}`, câu `Dạ đơn đã hoàn tiền thành công ạ.`: giữ nguyên.
- Bằng chứng đơn `status: 'pending'`, câu `Em đã hủy đơn hàng cho anh/chị.`: bằng đúng câu "hủy, có đơn" ở 03 mục 4, có `SIM-O-00091`, không có `ord_`, `delivery=`, `address=`.
- Bằng chứng đơn `delivered` chưa hoàn, câu "đã hoàn tiền thành công": bằng đúng câu "hoàn tiền, có đơn".
- Không có đơn trong tool: hai câu "không có đơn" tương ứng.

### Hàng 5 — tool mỗi bước

- `agent_protocol.MAX_TOOLS_PER_STEP == agent_protocol.MAX_TOOL_CALLS == 10`.
- `assistant_message` với 10 tool call: hợp lệ; 11: `ProtocolError`.
- Theo `AgentFixture`/`ScriptedModel`/`call` (`tests/test_r1_w3_2_agent_loop.py`): một bước gọi 7 tool khác nhau (ví dụ `get_order` O-701, O-702, O-705, `get_current_time`, `get_product` P-102, `get_product` P-603, `search_products`), bước sau `say(...)`. Lượt thành công; `trace['tools']` có 7 mục; transcript gửi lần gọi model thứ hai đi qua `validate_messages`.
- Bước 1 gọi 6 tool, bước 2 gọi 5 tool: `ApiError` `agent_budget_exceeded`, như hiện nay.
- `len(agent_protocol.SYSTEM)` không đổi so với `ece0b0b`.

## 3. Test cũ được phép sửa (và chỉ những chỗ này)

Cách sửa duy nhất được phép: ở câu thử dính `fee_amount`, `deadline_number`, `deadline_no_fact`, đổi khẳng định "bị xóa / bằng `POLICY_NOTE` / `changed` là `True`" thành "giữ nguyên văn bản, `changed` là `False`, `audit` có đúng luật". **Không bỏ câu thử nào**, không đổi khẳng định của câu dính luật chặn. Mỗi chỗ sửa ghi vào báo cáo kèm tên câu.

Claude đã chạy danh sách này trên bản nguyên mẫu; đây đúng là các test đỏ:

| Tệp | Lớp.hàm | Câu thử chuyển sang ghi vết |
|---|---|---|
| `tests/test_r1_w3_2_answer_check.py` | `FinalAnswerCheckTests.test_uncited_policy_promises_are_removed` | "Anh/chị được đổi hàng trong 7 ngày kể từ khi nhận hàng.", "Thời hạn đổi trả là 30 ngày." (4 câu còn lại vẫn bị xóa) |
| | `FinalAnswerCheckTests.test_a_structured_warranty_fact_from_a_tool_is_not_a_promise` | câu bảo hành khi không có hoặc sai bằng chứng |
| `tests/test_r1_w6_3_1_hotfix.py` | `DeadlineTests.test_server_deadline_facts_survive_only_with_tool_evidence` | 3 câu, vế "không bằng chứng" |
| | `DeadlineTests.test_fee_logistics_and_unknown_numbers_still_need_citations` | "Shop cho đổi trong 30 ngày ạ.", "Shop cho đổi trong 7 đến 30 ngày ạ.", "Thời hạn trả là 1 ngày ạ." (hai câu "miễn phí ship đổi size", "đổi tận nhà" vẫn bị xóa) |
| `tests/test_r1_w6_3_2_hotfix.py` | `ShippingFeeTests.test_order_shipping_facts_need_matching_tool_money` | vế "không bằng chứng" của các câu phí ship |
| | `ShippingFeeTests.test_policy_logistics_missing_or_mismatched_money_still_drop` | "Phí ship đơn này là 20.000đ ạ.", "Phí ship đơn SIM-O-30000 size 43 ×2 ạ.", "Phí ship 30k tổng 400000 ạ." (các câu khác vẫn bị xóa; "Phí ship do shop chịu hoàn toàn." vẫn bị xóa nhờ 03 mục 1.3) |
| | `ShippingFeeTests.test_money_evidence_walks_all_tool_results_but_rejects_bool_and_non_int` | vế bằng chứng nằm ở vai `user`/`assistant` |
| | `DeadlineProductNumbersTests.test_only_numbers_before_time_units_are_deadlines` | vế "không bằng chứng" |
| | `DeadlineProductNumbersTests.test_unknown_time_numbers_and_all_time_units` | các câu số ngày lạ |
| `tests/test_w642_answer_check.py` | 12 hàm ở `Row1MoneyEvidenceTests`, `Row2TimeEvidenceTests`, `Row3HeadingAndNumberedLineTests`, `Row4DetailsUnitTests` khóa "xóa khi không có bằng chứng" | Row1, Row2: vế "không bằng chứng" thành ghi vết. Row3: **đổi cụm kích hoạt** trong dòng mẫu sang một luật chặn (ví dụ "trễ hạn 72 giờ" thành "đổi tận nhà miễn phí 2 chiều"), giữ nguyên kỳ vọng về nhãn tiêu đề và số thứ tự. Row4: các câu `fee_amount`, `deadline_number`, `deadline_no_fact` chuyển từ `details` sang `audit` |
| `tests/test_phase5_e_ai_trust_and_governance.py` | khoảng dòng 758 (O-101) | bỏ `assertIn("delivery=None", …)`, thay bằng `assertNotIn("delivery=", …)` và `assertNotIn("address=", …)` (03 mục 4) |

Không có ở bảng mà đỏ: **dừng và hỏi owner**. Bảng không có `tests/test_r1_w6_3_4_answer_check.py` (không phải sửa).

## 4. Lệnh phải chạy và báo đủ số pass, fail, skip

```bash
python -m unittest discover -s tests -q
python scripts/build_agent_notebook.py
python scripts/build_agent_notebook.py --check
python scripts/build_eval_pack.py --check
python scripts/check_docs_contract.py
python scripts/check_deployment_contract.py
python scripts/check_live_e2e_contract.py
python scripts/check_eval_dataset.py
python scripts/check_eval_dataset.py evals/suites --final
python scripts/run_agent_scenarios.py --fake --dataset evals/agent_scenarios_w3_2.jsonl --min-success-rate 1.0
python scripts/run_agent_scenarios.py --fake --dataset evals/agent_scenarios_w4.jsonl --min-success-rate 1.0
python scripts/run_agent_scenarios.py --fake --dataset khoa_luan/eval_pack/06_vi_du.jsonl --min-success-rate 1.0
python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --min-success-rate 1.0
python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --context-tokens 32768 --min-success-rate 1.0
sha256sum evals/suites/*.jsonl
git diff --check
```

Chạy riêng và ghi số đạt của: `tests.test_w643_answer_check_scope`, 4 tệp test cũ của bộ kiểm, `tests.test_w642_answer_check`, `tests.test_phase5_e_ai_trust_and_governance`, `tests.test_r1_w3_2_agent_loop`.

Lỗi đã biết trên máy owner: `test_marketplace_sim_stories_and_send…test_item10_package_isolation_and_image_exclusion` đỏ vì quét vào worktree `.claude/worktrees/cai-nay-la-sao-bddcef`. Ghi lại, không sửa.

## 5. Số đo phải ghi vào báo cáo

1. **Bảng 12 dòng** ở mục 2, chạy trên `origin/main` và trên nhánh: mỗi dòng ghi "xóa (luật)" hay "giữ (ghi vết luật / không)".
2. **Runner giả 250 ca:** số lượt có `answer_check` (bị xóa câu) và số lượt có `answer_check_audit`, đếm theo luật. So với `ece0b0b` (2 lượt bị sửa: `s09_006` `done_claim`, `s11_016` `fee_amount`).
3. **Danh sách mọi test cũ đã sửa**, đúng theo bảng ở mục 3, kèm câu thử và lý do.

## 6. Báo cáo

Ghi vào `docs/phase_role_aware_ops/W6_4_3_EXECUTION_REPORT_2026-11-15.md` trên nhánh `phase-r1-w6-4-3`, xuống dòng LF. Thư mục handoff chưa có trên `main`: nhắc tới tệp handoff bằng tên trong backtick, **không** dùng link Markdown tương đối. Báo cáo gồm:

- điều kiện bắt đầu (SHA `origin/main`, tên nhánh);
- bảng 6 hàng: DONE hoặc BLOCKED, tệp đã đổi;
- bằng chứng FAIL trước khi sửa của hàng 1–5;
- danh sách test cũ đã sửa (mục 3);
- kết quả từng lệnh ở mục 4;
- ba số đo ở mục 5;
- những chỗ khác còn xóa hay thay nhầm câu đúng, nếu thấy (chỉ ghi);
- tên nhánh, URL PR, kết quả CI nếu có.

Thêm một dòng vào `docs/phase_role_aware_ops/W1_EXECUTION_LOG_2026-10-31.md` theo mẫu dòng 041 (W6.4.2), ghi "Gemini 4 Hydrogen (Antigravity)".
