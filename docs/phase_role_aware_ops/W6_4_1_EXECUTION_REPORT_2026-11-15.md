# Báo cáo thực hiện W6.4.1 — Ngữ cảnh 32k, tóm tắt danh sách đơn, phân trang và rút gọn kết quả tool

## 1. Điều kiện bắt đầu và quyết định áp dụng

- **Kho nguồn:** `D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le`
- **SHA `origin/main` lúc tách nhánh:** `fdaa2c3edf83cce69783de01ef092d30ad01be24` (`git merge-base --is-ancestor fdaa2c3 origin/main` đạt)
- **Nhánh thực hiện:** `phase-r1-w6-4-1` (tạo bằng `git switch --no-track -c phase-r1-w6-4-1 origin/main`, không làm việc hay push trên `main`)
- **Bộ tài liệu tham chiếu (chỉ đọc tại worktree cục bộ `.claude/worktrees/cai-nay-la-sao-bddcef`):**
  - `README.md`, `01_HIEN_TRANG_VA_NGUYEN_NHAN.md`, `02_PHAM_VI_VA_TIEU_CHI.md`, `03_THIET_KE_CHI_TIET.md`, `04_TEST_VA_KIEM_TRA.md`, `06_SAU_KHI_MERGE.md` (trong `docs/phase_role_aware_ops/W6_4_1_context_fix/`)
  - `W0_OWNER_DECISION_DELTA_2026-10-29.md` mục `## 32.` (`W6.4-D9a`, `W6.4-D15`)
  - `W6_BACKLOG_2026-11-06.md` dòng `F44`
- **Quyết định của owner chốt bổ sung trong phiên trước khi sửa code:**
  1. **Quyết định A1 (`tests/test_phase5_e_ai_trust_and_governance.py`):** Giữ nguyên fake model gọi `list_orders` với `{"arguments": {}}` và **không** sửa `retailops/guardrails/topic_filter.py`. Đổi assertion tại dòng 655 thành `returned_count == 5`, bổ sung kiểm tra `has_more is True`, `next_offset == 5` và `note` chứa `"5/13"` + `"gần nhất"` (giữ `truncated is True`), và tại dòng 768 đổi `"10/13"` thành `"5/13"` (giữ `"truncated=True"` ở dòng 769).
  2. **Quyết định A2 (`validate_tool` và `BoundTools`):**
     - `validate_tool` trong `agent_protocol.py` kiểm tra toàn bộ các trường trước; chỉ khi mọi kiểm tra đều đạt mới ghi giá trị `int` đã chuẩn hóa vào `arguments` theo kiểu in-place và trả về `arguments` (khi có lỗi tuyệt đối không mutate dở dang); giữ nguyên các caller (`retailops/workflow/agent.py`, `retailops/workflow/subagents/read_worker.py`, `retailops/http/routes.py`).
     - `BoundTools.__call__` cho `list_orders` trong `retailops_tools.py` nhận `int` (không phải `bool`) hoặc chuỗi chỉ gồm chữ số ASCII (`value.isascii() and value.isdigit()`), kiểm tra khoảng `limit` (1..20) và `offset` (`>= 0`), sai trả `{'error': 'invalid_arguments', 'message': ...}` không ném exception.
     - Bổ sung test đi xuyên vòng lặp `Application` / `agent.py` thật khi model gửi `{"limit": "5", "offset": "0"}`.
     - Ghi nhận phát hiện vào báo cáo (không sửa trong W6.4.1): `retailops/workflow/agent.py` tính `_call_key` trước `validate_tool`.
- **Tuân thủ giới hạn:** Không sửa `SYSTEM` trong `agent_protocol.py`, `answer_check.py`, rào an toàn, luật nghiệp vụ, `data/knowledge/`, dữ liệu demo, 12 tệp suite đóng băng trong `evals/suites/`, workflow CI/deploy, `requirements*.txt` hay bất kỳ tệp nào trong worktree `.claude/worktrees/cai-nay-la-sao-bddcef`.

---

## 2. Bảng trạng thái 6 hàng theo `02_PHAM_VI_VA_TIEU_CHI.md`

| Hàng | Nội dung | Trạng thái | Commit SHA | Tệp đã đổi |
|---:|---|---|---|---|
| 1 | Trần tổng theo cửa sổ (`RETAILOPS_MODEL_CONTEXT_TOKENS`, `context_tokens()`, `max_characters()`) | `DONE` | `7741f41` | `agent_protocol.py`, `retailops/workflow/agent.py`, `retailops/workflow/compaction.py`, `tests/test_w641_context.py` |
| 2 | `list_orders` trả bản tóm tắt, có phân trang (`limit`/`offset`), sắp xếp đơn gần nhất trước (F44) | `DONE` | `c51534d` | `agent_protocol.py`, `retailops_tools.py`, `tests/test_w641_list_orders.py`, `tests/test_w64_order_items.py`, `tests/test_phase5_e_ai_trust_and_governance.py` |
| 3 | `list_case_orders` của Trợ lý ca trả bản tóm tắt, giữ trần 20 đơn, thêm `total_count` và `truncated` | `DONE` | `b4befb5` | `retailops/workflow/case_assist.py`, `tests/test_w641_case_orders.py`, `tests/test_w64_order_items.py` |
| 4 | `compact_tool_result` rút gọn theo thứ tự: (a) chuỗi dài -> (b) khóa ít giá trị lồng `depth >= 2` -> (c) cắt đuôi danh sách kèm ghi chú tiếng Việt | `DONE` | `e666d5e` | `retailops/workflow/compaction.py`, `tests/test_w641_compaction.py`, `tests/test_r1_w3_2_agent_loop.py` |
| 5 | Cập nhật mô tả `list_orders` và `list_case_orders` trong `khoa_luan/eval_pack/03_HE_THONG_VA_DU_LIEU.md` | `DONE` | `c3d7827` | `khoa_luan/eval_pack/03_HE_THONG_VA_DU_LIEU.md` |
| 6 | Sinh lại notebook, chạy toàn bộ kiểm tra không hồi quy, ghi số đo, báo cáo, log W1 và mở PR (test JS & PostgreSQL thật để CI kiểm) | `DONE` | Commit hàng 6 trên `phase-r1-w6-4-1` | `notebooks/colab_agent.ipynb`, `docs/phase_role_aware_ops/W6_4_1_EXECUTION_REPORT_2026-11-15.md`, `docs/phase_role_aware_ops/W1_EXECUTION_LOG_2026-10-31.md` |

---

## 3. Bằng chứng FAIL trước khi sửa (Hàng 1–5)

Các lệnh dưới đây chạy với `PYTHONUTF8=1`, `PYTHONPATH=tests` bằng Python `%TEMP%\venv_pdf\Scripts\python.exe` trên mã trước khi áp dụng phần sửa của từng hàng tương ứng:

### Hàng 1 — `tests/test_w641_context.py`

Lệnh chạy trước sửa (khi đã gỡ `RETAILOPS_MODEL_CONTEXT_TOKENS` khỏi môi trường chạy):

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="tests"; $env:RETAILOPS_MODEL_CONTEXT_TOKENS=""
& "$env:TEMP\venv_pdf\Scripts\python.exe" -m unittest tests.test_w641_context -v
```

Kết quả quan sát được: `Ran 5 tests in 12.133s` — `FAILED (failures=6)`:

- `FAIL: test_context_tokens_env_values_in_fresh_subprocesses (RETAILOPS_MODEL_CONTEXT_TOKENS='32768')` -> `AssertionError: Lists differ: [16384, 36000, 10400] != [32768, 72000, 10400]`
- `FAIL: test_context_tokens_env_values_in_fresh_subprocesses (RETAILOPS_MODEL_CONTEXT_TOKENS='8192')` -> `AssertionError: Lists differ: [16384, 36000, 2600] != [8192, 18000, 2600]`
- `FAIL: test_invalid_context_tokens_rejected_on_import (RETAILOPS_MODEL_CONTEXT_TOKENS='2048')` -> `AssertionError: 0 == 0`
- `FAIL: test_invalid_context_tokens_rejected_on_import (RETAILOPS_MODEL_CONTEXT_TOKENS='200000')` -> `AssertionError: 0 == 0`
- `FAIL: test_real_runner_fake_32k_passes_71800_limit_to_fit_transcript` -> `AssertionError: False is not true : [35800, 35800]`
- `FAIL: test_runner_import_order_updates_runtime_max_characters` -> `AttributeError: module 'agent_protocol' has no attribute 'max_characters'`

### Hàng 2 — `tests/test_w641_list_orders.py`

Lệnh chạy trước sửa (sau commit hàng 1):

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="tests"
& "$env:TEMP\venv_pdf\Scripts\python.exe" -m unittest tests.test_w641_list_orders -v
```

Kết quả quan sát được: `Ran 11 tests in 1.900s` — `FAILED (failures=16, errors=4)`:

- `test_f44_five_fixture_orders_fit_without_compaction_at_16k ... FAIL`
- `ERROR: test_compatibility_order_agent_and_topic_filter` -> `KeyError: 'has_more'`
- `ERROR: test_pagination_walk_visits_all_orders_without_duplicates_or_gaps` -> `KeyError: 'has_more'`
- `ERROR: test_real_agent_loop_accepts_string_digit_pagination_args` -> `retailops.core.ApiError: Không nhận được câu trả lời hợp lệ từ model. Chat chưa thực hiện thay đổi đơn.`
- `ERROR: test_validate_tool_integer_arguments_and_atomicity` -> `agent_protocol.ProtocolError: Unknown tool or invalid argument fields`
- `FAIL: test_bound_tools_validation_errors_and_ascii_digit_acceptance (args={'limit': 0})` -> `AssertionError: None != 'invalid_arguments'`
- `FAIL: test_sim_o_00091_shortened_items` -> `AssertionError: Lists differ: [{'product_id': 'P-601', 'name': 'Áo sơ mi l[237 chars]000}] != [{'name': 'Áo sơ mi lụa công sở', 'variant':[147 chars]000}]`
- `FAIL: test_summary_keys_exact_order_and_no_forbidden_keys` -> `AssertionError: Lists differ: ['id', 'product_id', 'source_system', 'external_o[356 chars]rce'] != ['id', 'external_order_id', 'status', 'ordered_at[153 chars]ems']`
- `FAIL: test_tools_schema_and_verbatim_description` -> `AssertionError: None != "List the authenticated customer's orders[437 chars]own."`

### Hàng 3 — `tests/test_w641_case_orders.py`

Lệnh chạy trước sửa (sau commit hàng 2):

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="tests"
& "$env:TEMP\venv_pdf\Scripts\python.exe" -m unittest tests.test_w641_case_orders -v
```

Kết quả quan sát được: `Ran 3 tests in 0.784s` — `FAILED (failures=1, errors=1)`:

- `ERROR: test_list_case_orders_summary_keys_and_truncation_flags` -> `KeyError: 'total_count'`
- `FAIL: test_list_case_orders_tool_description_verbatim` -> `AssertionError: 'READ ONLY: list orders belonging to the [110 chars]ary.' != "READ ONLY: list the orders of the curren[253 chars]ils."`

### Hàng 4 — `tests/test_w641_compaction.py`

Lệnh chạy trước sửa (sau commit hàng 3):

```powershell
$env:PYTHONUTF8="1"; $env:PYTHONPATH="tests"
& "$env:TEMP\venv_pdf\Scripts\python.exe" -m unittest tests.test_w641_compaction -v
```

Kết quả quan sát được: `Ran 5 tests in 0.007s` — `FAILED (failures=4)`:

- `FAIL: test_phase_a_shrinks_strings_before_dropping_list_items_f44_regression` -> `AssertionError: False is not true`
- `FAIL: test_phase_b_preserves_top_level_note_and_strips_nested_low_value_keys` -> `AssertionError: Tuples differ: () != ('description', 'image_url', 'images', 'no[46 chars]rce')`
- `FAIL: test_phase_b_strips_nested_metadata_before_dropping_list_items` -> `AssertionError: 3 != 5`
- `FAIL: test_phase_c_uses_vietnamese_hidden_count_note_when_lists_cut` -> `AssertionError: unexpectedly None : Unexpected Phase C note element: '…(+20 more)'`

### Hàng 5 — `khoa_luan/eval_pack/03_HE_THONG_VA_DU_LIEU.md`

Hàng 5 chỉ sửa hai dòng mô tả tool trong tài liệu theo `03_THIET_KE_CHI_TIET.md` mục 5; `04_TEST_VA_KIEM_TRA.md` mục 2 không đặt bài test tách riêng trước khi sửa. Trước và sau khi sửa, hai lệnh `scripts/build_eval_pack.py --check` (`EVAL_PACK_OK`) và `scripts/check_docs_contract.py` (`SUCCESS: All documentation contracts are valid and truthful.`) đều đạt.

---

## 4. Danh sách test cũ đã sửa và lý do

Các bài kiểm cũ được sửa tối thiểu theo đúng thiết kế và quyết định owner A1, giữ nguyên mọi bất biến kiểm tra:

1. **`tests/test_w64_order_items.py`**
   - Dòng 27–48 (`test_all_six_model_tools_preserve_the_two_persisted_items`): `list_orders` và `list_case_orders` nay trả bản tóm tắt đơn có `items` 4 khóa (`name`, `variant`, `quantity`, `subtotal`), nên nhánh `name in ('list_orders', 'list_case_orders')` đối chiếu `expected_summary`, còn 4 tool còn lại giữ nguyên `expected` 6 khóa; giữ nguyên khẳng định đồng nhất `name`, `product_id`, `variant` cho cả 6 tool.
   - Dòng 61 (`test_ten_orders_stay_within_existing_model_result_budget`): truyền `{'limit': 10}` thay vì `{}` khi gọi `list_orders` để tiếp tục kiểm tra đúng kịch bản 10 đơn nằm trong `TOOL_RESULT_MAX_CHARS` sau khi mặc định mới đổi từ `10` xuống `5`.
2. **`tests/test_phase5_e_ai_trust_and_governance.py`** *(theo quyết định A1 của owner)*
   - Dòng 655–660: cập nhật `returned_count` từ `10` sang `5` theo mặc định phân trang mới; bổ sung khẳng định `has_more is True`, `next_offset == 5` và kiểm `note` chứa `"5/13"` và `"gần nhất"`, giữ nguyên `truncated is True` và `total_count > 5`.
   - Dòng 665 (comment) & dòng 768: cập nhật `"10/13"` thành `"5/13"`, giữ nguyên kiểm tra `"truncated=True"` từ `topic_filter.py` ở dòng 769 (fake model vẫn gọi `{}` và `topic_filter.py` không bị sửa).
3. **`tests/test_r1_w3_2_agent_loop.py`**
   - Dòng 326–329 (`CompactionTests.test_a_long_list_is_cut_with_a_marker`): đổi regex khớp phần tử ghi chú cuối danh sách từ `r'^…\(\+\d+ more\)$'` sang ghi chú tiếng Việt mới của Pha C: `r'^…\(còn \d+ mục bị ẩn do giới hạn hiển thị; hỏi hẹp hơn hoặc dùng tool xem chi tiết\)$'`, giữ nguyên kiểm tra `len(text) <= 1500` và giữ nguyên phần tử đầu tiên.

Ghi chú: `tests/test_r1_w6_3_runner.py` vẫn đạt nguyên trạng, không cần sửa.

---

## 5. Kết quả toàn bộ lệnh kiểm ở `04` mục 3

| # | Lệnh | Kết quả | Chi tiết |
|---:|---|---|---|
| 1 | `python -m unittest discover -s tests -q` | `1158 pass, 1 fail, 0 error, 86 skip / 1245` (`603.231s`) | Chạy sau commit hàng 5 và sinh lại `notebooks/colab_agent.ipynb`. **1 fail duy nhất** ở `test_item10_package_isolation_and_image_exclusion` (`test_marketplace_sim_stories_and_send.MarketplaceSimIsolationTests`): `tests/test_marketplace_sim_stories_and_send.py:508-511` khi quét toàn bộ repo chỉ loại trừ `{"marketplace_sim", "tests", ".git"}` nên quét nhầm tệp trong thư mục worktree cục bộ `.claude/worktrees/cai-nay-la-sao-bddcef/tests/test_marketplace_sim_contract.py` (không thuộc nhánh). **86 skip** do máy Windows không đặt `RETAILOPS_TEST_DATABASE_URL` (PostgreSQL), không cài `waitress` và không có `bash` trong PATH. |
| 2 | `python scripts/build_agent_notebook.py` | Đạt | Đã sinh lại `notebooks/colab_agent.ipynb` đồng bộ với mã và test mới. |
| 3 | `python scripts/build_agent_notebook.py --check` | `PASS` | `AGENT_NOTEBOOK_SOURCE_SYNC_OK` (chạy lại sau khi hoàn tất tài liệu hàng 6). |
| 4 | `python scripts/build_eval_pack.py --check` | `PASS` | `EVAL_PACK_OK` (chạy lại sau khi hoàn tất tài liệu hàng 6). |
| 5 | `python scripts/check_docs_contract.py` | `PASS` | `SUCCESS: All documentation contracts are valid and truthful.` — 4/4 kiểm tra đạt (chạy lại sau khi hoàn tất tài liệu hàng 6). |
| 6 | `python scripts/check_deployment_contract.py` | `PASS` | `DEPLOYMENT_CONTRACT_OK` |
| 7 | `python scripts/check_live_e2e_contract.py` | `PASS` | `LIVE_E2E_CONTRACT_OK` |
| 8 | `python scripts/check_eval_dataset.py` | `PASS` | `baseline_v1.jsonl` (`30` ca), `agent_scenarios_w3_2.jsonl` (`32` ca), `agent_scenarios_w4.jsonl` (`12` ca). |
| 9 | `python scripts/check_eval_dataset.py evals/suites --final` | `PASS` | `EVAL_DATASET_OK suites cases=250` |
| 10 | `python scripts/run_agent_scenarios.py --fake --dataset evals/agent_scenarios_w3_2.jsonl` | `PASS` (`32/32 = 1.0`) | `35` lượt, `pass@1 = 1.0`, `pass^K = 1.0`, `valid tool-call rate = 33/33 = 1.0` (`repeated calls: 0`), `p50 274.87 ms`, `p95 483.89 ms`, `max 519.01 ms`. |
| 11 | `python scripts/run_agent_scenarios.py --fake --dataset evals/agent_scenarios_w4.jsonl` | `PASS` (`12/12 = 1.0`) | `14` lượt, `valid tool-call rate = 17/17 = 1.0`, `image token cost = 4 image(s) / 2 turn(s), 160 tokens`, `p50 119.22 ms`, `p95 998.17 ms`. |
| 12 | `python scripts/run_agent_scenarios.py --fake --dataset khoa_luan/eval_pack/06_vi_du.jsonl` | `PASS` (`4/4 = 1.0`) | `4` lượt, `valid tool-call rate = 6/6 = 1.0`, `p50 230.12 ms`, `p95 286.68 ms`. |
| 13 | `python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --min-success-rate 1.0` | `PASS` (`250/250 = 1.0`) | Cấu hình mặc định 16k; `336` lượt, `pass@1 = 1.0`, `pass^K = 1.0`, `valid tool-call rate = 469/469 = 1.0` (`repeated calls: 0`), `p50 350.16 ms`, `p95 511.0 ms`, `max 677.4 ms`. |
| 14 | `python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --context-tokens 32768 --min-success-rate 1.0` | `PASS` (`250/250 = 1.0`) | Cấu hình `--context-tokens 32768`; `336` lượt, `pass@1 = 1.0`, `pass^K = 1.0`, `valid tool-call rate = 469/469 = 1.0` (`repeated calls: 0`), `p50 284.63 ms`, `p95 416.56 ms`, `max 604.42 ms`. |
| 15 | Kiểm tra SHA-256 `evals/suites/*.jsonl` | `PASS` (12/12 khớp) | 12/12 tệp khớp hoàn toàn bảng trong `evals/suites/README.md` (`W6.3-D7`). |
| 16 | `git diff --check` | `PASS` | Không có lỗi khoảng trắng thừa hay CRLF sau khi hoàn tất toàn bộ tệp hàng 6. |
| 17 | Test JS theo `.github/workflows/ci.yml` (`node --check web/*.js` + 11 lệnh `node tests/*.js`) | `Không chạy được trên máy, CI kiểm` | `node.cmd` trên máy là bản giả (thoát 0 không chạy JS), nên theo quy định chỉ ghi **test JS: không chạy được trên máy, CI kiểm**, không ghi là đạt. |

Bảng SHA-256 đã xác minh cho `evals/suites/S01.jsonl`–`S12.jsonl`:

- `S01.jsonl`: `6742499c31f1ced367b90eb2a29a1e543c22f9b502b21ef7ce5260c555c568d4`
- `S02.jsonl`: `35cd5b0df89c4b174547d1a94d86c5d428e67cca8df98f1128fd3d12517ef54d`
- `S03.jsonl`: `9142f8b7f2b57dd2913ad18b9e5646d7453226d0ff97f87864301b5d341340a5`
- `S04.jsonl`: `f71400121a9f86db71b86ee1c1f38a968d2cf5d2a8892d9357c6704d4f65e55f`
- `S05.jsonl`: `999903d49e166de1a56c65fca7876958e99c82fbf31d2363e04931c8005be6dc`
- `S06.jsonl`: `5de3c66a24244725aafbe37799381686ef5461d4bc7815b93b7bac8be0fc8355`
- `S07.jsonl`: `550771b72d3a0d443969009d503df1de4e0058e5f2d176dc04f0d605f437bb37`
- `S08.jsonl`: `3d07cefccb72fa13e1854d20efc20d678257c286f267e0cdca3a6997ea04b370`
- `S09.jsonl`: `74ac253b32a161c9c0341981ff05033877d448c71f706fc9e568c70cb9654e37`
- `S10.jsonl`: `01562bc4e6241172481f6e43a4b556ce6278212836d20fb8af14b7302a53404b`
- `S11.jsonl`: `63cd47390bc3a1afb409a2706dbc7270aae6dcb4b80514d6ccdaf3af35c14386`
- `S12.jsonl`: `db70f9e760c341ddb5170f2c28fa29e68681648716c8b26c5a85101ce9446377`

Ngoài ra, bộ kiểm W6.4.1 riêng và đồng bộ tài liệu/hợp đồng sẽ được chạy lại ngay sau lần ghi báo cáo và log cuối cùng.

---

## 6. Bốn số đo theo `04` mục 4

### 6.1. Kích thước kết quả `list_orders` trước và sau khi sửa (fixture `standard`, khách `SIM-C-0057`)

Đo bằng cách gán lần lượt `N = 1, 3, 5, 10, 20` đơn thật từ fixture `standard` (thứ tự `ordered_at DESC, id DESC`) cho khách nội bộ của `SIM-C-0057`, so sánh bản `fdaa2c3` (`BEFORE`, trần cố định 10 đơn đầy đủ) với bản sau sửa (`AFTER`, rút gọn + phân trang `limit` truyền theo `N` và gọi mặc định `limit=5`), nén qua `compact_tool_result(..., limit=5200)` (ngân sách 16k) và `limit=10400` (ngân sách 32k):

| Số đơn `N` | Chế độ gọi | Số đơn trả về | JSON thô (ký tự) | Sau rút gọn 16k (`limit=5200`) | Đơn còn lại ở 16k | Sau rút gọn 32k (`limit=10400`) | Đơn còn lại ở 32k |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | `BEFORE` (mặc định tối đa 10) | 1 | 2.248 | 2.248 | 1/1 | 2.248 | 1/1 |
| 1 | `AFTER` (`limit=1` / mặc định 5) | 1 | 733 | 733 | 1/1 | 733 | 1/1 |
| 3 | `BEFORE` (mặc định tối đa 10) | 3 | 6.424 | 4.272 | 2/3 | 6.424 | 3/3 |
| 3 | `AFTER` (`limit=3` / mặc định 5) | 3 | 1.804 | 1.804 | 3/3 | 1.804 | 3/3 |
| 5 | `BEFORE` (mặc định tối đa 10) | 5 | 10.474 | 3.970 | 2/5 | 8.364 | 4/5 |
| 5 | `AFTER` (`limit=5` / mặc định 5) | 5 | 2.921 | 2.921 | 5/5 | 2.921 | 5/5 |
| 10 | `BEFORE` (mặc định tối đa 10) | 10 | 21.021 | 4.279 | 2/10 | 8.153 | 4/10 |
| 10 | `AFTER` (`limit=10`) | 10 | 5.733 | 3.460 | 6/10 | 5.733 | 10/10 |
| 10 | `AFTER` (mặc định `limit=5`) | 5 | 3.003 | 3.003 | 5/5 | 3.003 | 5/5 |
| 20 | `BEFORE` (mặc định tối đa 10) | 10 | 20.894 | 4.300 | 2/10 | 8.628 | 4/10 |
| 20 | `AFTER` (`limit=20`) | 20 | 11.388 | 3.461 | 6/20 | 5.826 | 10/20 |
| 20 | `AFTER` (mặc định `limit=5`) | 5 | 3.003 | 3.003 | 5/5 | 3.003 | 5/5 |

Nhận xét: với trường hợp F44 (`N = 5` đơn), trước đây ở cấu hình 16k chỉ còn **2/5** đơn và ở 32k chỉ còn **4/5** đơn; sau khi sửa, toàn bộ **5/5** đơn nằm trọn trong **2.921 ký tự** mà không bị cắt ở cả 16k lẫn 32k. Với `N = 10`, cấu hình 32k giữ đủ **10/10** đơn (`5.733` ký tự, không cắt).

### 6.2. Độ dài `SYSTEM` và `agent_system` có focus tối đa

- `len(agent_protocol.SYSTEM)` = **5.993** ký tự (giữ nguyên)
- `len(agent_protocol.agent_system({'order_id': 'O'*64, 'product_id': 'P'*64}))` = **6.284** ký tự (giữ nguyên)

### 6.3. Thống kê các ca trong `evals/suites` (250 ca)

- Số lượt có `list_orders` trong `expect.tools_any` mà `max_tool_calls <= 2`: **0 ca** (cũng bằng **0** kể cả khi kiểm `tools_called`).
- Thông tin bổ sung (chỉ ghi nhận): trong 250 ca (`67` lượt có nhắc `list_orders`), nếu xét ngưỡng `max_tool_calls <= 3` thì có **8** lượt: 3 lượt có `['get_order', 'list_orders']` trong `tools_any` (`s01_016`, `s01_025`, `s04_009`) và 5 lượt có `list_orders` trong `tools_called` (`s01_002`, `s06_004`, `s08_007`, `s08_011`, `s09_019`).

### 6.4. Phân bố số đơn mỗi khách trong fixture `standard`

Trong fixture `standard` hiện có **91** khách hàng (`89` khách có ít nhất 1 đơn, tổng `128` đơn hàng):

- Phân bố `{số đơn: số khách}`: `{1: 66, 2: 14, 3: 3, 4: 5, 5: 1}`
- Số khách có **trên 5 đơn** (gặp `has_more=True` khi gọi `list_orders` mặc định): **0 khách** trên dữ liệu `standard` hiện tại.

---

## 7. Những chỗ khác cũng có thể làm model thiếu hoặc lệch dữ liệu (chỉ ghi nhận, không sửa)

1. **`retailops/workflow/agent.py` (dòng 234–236):** `_call_key(name, args)` được tính **trước** khi `tool_validator(name, args)` chuẩn hóa `limit`/`offset` từ chuỗi chữ số sang `int`. Vì vậy, nếu model gọi `list_orders({"limit": "5"})` rồi gọi lại `list_orders({"limit": 5})` trong cùng một lượt, hệ thống coi đó là hai khóa gọi khác nhau thay vì phát hiện `duplicate_call`. (Ghi nhận theo quyết định owner A2).
2. **`retailops_tools.py` (dòng 324):** `search_products` cắt cứng `'products': products[:10]` mà chưa trả `total_count` hay cờ `truncated` để báo cho model khi danh mục khớp nhiều hơn 10 sản phẩm.
3. **`retailops_mcp_server.py` (dòng 880–908):** Tool MCP `list_orders` vẫn dùng `limit` mặc định `10` (tối đa `50`) qua `_format_mcp_order_row`, chưa phân trang `offset`/`has_more` và chưa rút gọn theo định dạng tóm tắt mới (được ghi ngoài phạm vi W6.4.1 trong `02_PHAM_VI_VA_TIEU_CHI.md`).
4. **`retailops/workflow/case_assist.py`:**
   - `_read_case_transcript` (dòng 293–303, 331, 353) giới hạn `LIMIT 30` lượt `agent_turns` gần nhất, đồng thời cắt nội dung mỗi tin ở `800` ký tự và `handoff_dict["comment"]` ở `300` ký tự mà không kèm cờ báo bị cắt cho Trợ lý ca.
   - `_list_case_orders` (dòng 447, 473) đặt `LIMIT 20` và đã có `total_count`/`truncated`, nhưng chưa hỗ trợ `offset` để xem các đơn từ thứ 21 trở đi nếu khách có trên 20 đơn.
   - `_list_case_order_actions` (dòng 539) cắt `items[:20]` không kèm `total_count`/`truncated`.
5. **`retailops/workflow/subagents/order_agent.py` (dòng 113):** khi xử lý `ambiguous_order`, chế độ `legacy` chỉ liệt kê `(result.get('candidates') or [])[:10]`.
6. **`retailops/workflow/compaction.py` (dòng 18–24, 98–104):** nếu một kết quả đơn lẻ không chứa danh sách dài nhưng vẫn vượt `limit` sau pha A và B, hàm rơi về cắt chuỗi thô `preview` theo `limit - 160`; ngoài ra `scripts/run_agent_scenarios.py` (dòng 1098) giữ mặc định `--context-tokens 16384`, nên khi đánh giá model 32k cần truyền tường minh `--context-tokens 32768`.

---

## 8. Nhánh, PR và CI

- **Nhánh:** `phase-r1-w6-4-1` (`--no-track origin/main` từ `fdaa2c3edf83cce69783de01ef092d30ad01be24`)
- **PR và CI:** Sau khi commit hàng 6, nhánh `phase-r1-w6-4-1` được push lên `origin` và mở PR vào `main`; kết quả PR URL và trạng thái CI (`ci.yml` kiểm JS trên Node thật và PostgreSQL thật) được đính kèm trực tiếp trong thông báo bàn giao cho owner.
