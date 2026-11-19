# 04 — Test, lệnh kiểm, báo cáo

## Test mới (`tests/test_w673_*.py`, dữ liệu giả, không gọi model)
| Mục | Ca phải có |
|---|---|
| Bất biến | sinh lại: 1.200 ca đầu — ngoài 4 khung mục A trùng từng byte với ca v4 sinh ở `084b39b`; 4 khung chỉ khác `expect`/`fake_model`/`final_state`; 1.406 phiếu cũ trùng từng byte; thứ tự `id` giữ nguyên; T14 đứng sau cùng |
| A | kỳ vọng mới của 4 khung đúng bảng 03 (`tools_called/tools_not_called/human_support/sources/answer_any` và `HANDOFF_EITHER` còn đúng 2 khung); `regrade_record_v3`: chuyển `ok` → đạt, chuyển lỗi → trượt "not requested", vết không có `status` → giữ cách cũ + cờ `handoff_status_unknown`, hồi quy: các bản ghi giả hiện có cho kết quả như trước |
| B | đủ 18 khung × 10 ca; mỗi ca có `fake_model` qua `sft_cases check`; `final_state.handoff_episodes` đúng (1/0); khung nhiều lượt đúng số lượt và kỳ vọng từng lượt; mọi phiếu T14 có `rail_pass`; khung "lần đầu"/đối chứng có `must_not_include` cụm lặp lại; mỗi đơn ≤ 3 lần/khung; `T14 ∈ EASY_TIGHT`, `T14 ∉ HARD_SUITES`; test chống trùng giá trị bộ đo phủ T14 |
| C | câu lọt rào → qua; câu rào bắt (`human_request`, `extreme_rage`, `forbidden_topic`) → trượt đúng lý do, cả ở `verify`; phiếu không cờ → không kiểm rào (câu bị rào bắt vẫn qua như cũ); `to_dict()` không có khóa `rail_pass` khi `False` |
| D1 | proxy với upstream giả: khớp lời khách → tin `system` có khối đánh dấu đúng dạng, `tools`/tin khác/tham số không đổi; không khớp/khớp nhiều ca/không có gợi ý → chuyển nguyên + log `no_hint`; header `Authorization` chuyển nguyên, không có trong log; `/health`, `/v1/models` chuyển nguyên; chạy song song nhiều yêu cầu |
| D2 | `export`: đúng cột, BOM, không ghi đè, đếm lỗi thường gặp; `import`: trống / > 800 ký tự / có mã đơn / có số tiền / có chuỗi đánh dấu / trùng câu bộ đo → lỗi; hợp lệ → `hints.jsonl` có `sha256` |
| D3 | `--runs` hai thư mục cùng model với `run_offset` → số run không trùng, trùng → dừng; `stale_input` khi lời khách đổi; `hint_leak` chỉ với lượt có gợi ý; `hint_unverified`; `select` cùng tier ưu tiên không gợi ý; dạng `--run-dir` cũ cho kết quả trùng từng byte |
| E | `T11 ∉ HARD_SUITES` (mẫu thứ hai T11 chỉ luật 1/2/5); `--suite-cap`/`--mode-cap`: tắt → trùng từng byte; bật → bỏ đúng thứ tự, không bỏ `draft`, không thêm mẫu chế độ khác bù vào; báo cáo theo bộ × chế độ × vai; phiếu đỡ theo ca (`--per-case-templates`) và proxy ưu tiên gợi ý theo ca; proxy với upstream HTTPS giả |
| D4 | `meta.hinted`; thống kê theo `hinted`; mẫu còn chuỗi đánh dấu → dừng lỗi trước khi ghi |

## Lệnh kiểm (Windows, gốc repo, `PYTHONUTF8=1`)
```
python -m unittest discover -s tests -p "test_w673_*.py"
python -m unittest discover -s tests -p "test_w672_*.py"
python -m unittest tests.test_w670_sft_select_build tests.test_w670_ruler_calibration tests.test_w670_sft_fixture_cases tests.test_w644_eval_regrade tests.test_w671_sft_cache tests.test_w671_sft_export tests.test_w671_sft_no_eval_values
python scripts/sft_cases.py generate --out <thư mục tạm>   (rồi)   python scripts/sft_cases.py check --out <thư mục tạm>
python scripts/build_agent_notebook.py && python -m unittest tests.test_audit_remediation
python scripts/check_docs_contract.py
python -m unittest discover -s tests
```
Bộ đầy đủ chỉ được còn 5 lỗi có sẵn trên Windows (`test_r1_w4_agent_scenarios` ×2, `test_r1_w4_media_pipeline` ×1,
`test_r1_w4_customer_ref_and_v8` ×2).

## Mẫu báo cáo (gửi owner chuyển cho Claude)
- Nhánh + SHA đầu nhánh; danh sách tệp đổi.
- SHA256 mới của `cases_sft_v1.jsonl` và `briefs_sft_v1.jsonl` (sinh ở đầu nhánh); số ca/phiếu; danh sách `brief_id`
  mới (T14) mà Glimmer phải viết; xác nhận 1.406 phiếu cũ trùng từng byte.
- Mỗi mục A–E: CLI cuối cùng, quyết định ở chỗ 03 để ngỏ, test đã thêm.
- Số đơn fixture dùng cho từng khung T14 (và khung nào phải dùng lại đơn).
- Kết quả từng lệnh kiểm (chạy/qua/bỏ qua/lỗi); chỗ lệch khỏi 03 và lý do.
