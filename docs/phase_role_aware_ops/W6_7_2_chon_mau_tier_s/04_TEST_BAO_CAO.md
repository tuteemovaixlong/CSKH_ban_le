# 04 — Test, lệnh kiểm, báo cáo

## Test bằng dữ liệu giả (tệp mới `tests/test_w672_*.py`)
| Mục | Ca phải có |
|---|---|
| A | ca chưa Tier A có/không có A_code Qwen; ca Tier A Qwen có/không có A_code DeepSeek; bộ khó không có DeepSeek → `q_second` chọn lượt có độ giống < 0,85, bỏ lượt ≥ 0,85; `B_code` không bao giờ xuất; `--exclude-templates`; nhiều `--after`; gói không lộ `cls`/model |
| B | dựng lại ở số ký tự gốc khác `text` gốc → dừng; trọng tài dat/khong_dat/kc; trích dẫn sai → không đổi; `--strict-kckc` |
| C | xáo `mau_1`/`mau_2` theo seed; S thiếu 1 trích dẫn hoặc trích dẫn lấy từ mẫu kia → hạ S; S cần mọi lượt; khác biệt do chuỗi tool hoặc do `khac_biet` |
| D | đủ 5 luật mẫu thứ hai theo đúng thứ tự; trần khung (cả 0,25 cho T09/T10); trần DeepSeek chỉ bỏ mẫu thứ hai, bỏ bộ không khó trước; `--max-per-case 1` trùng `select` cũ |
| E | 2 mẫu/ca cùng tập; nhãn `meta`; lớp phủ áp được ở tin cuối và tin trợ lý trước đó; dòng phủ không áp được → lỗi; mẫu còn chữ Hán → `cjk_text` |
| F | xuất đúng cột, bỏ dòng trùng, không ghi đè; nhập: trống / còn chữ Hán / > 40 ký tự / thêm số / `(xóa)` / đoạn cũ không có trong vết; thêm dấu cách khi chữ Hán dính liền chữ hoặc đứng sau dấu phẩy (`bị⟦褶皱⟧.` → `bị nhăn.`, `hơn,⟦能否⟧ giúp` → `hơn, bạn có thể giúp`), không thêm trước `**`/xuống dòng |

Hồi quy: `export --round 1` + `import` vòng 1 trên bộ giả hiện có trong `tests/test_w670_sft_select_build.py` cho kết quả
trùng từng byte với trước khi sửa.

## Lệnh kiểm (Windows, gốc repo, `PYTHONUTF8=1`)
```
python -m unittest discover -s tests -p "test_w672_*.py"
python -m unittest tests.test_w670_sft_select_build tests.test_w670_ruler_calibration tests.test_w670_sft_fixture_cases tests.test_w644_eval_regrade
python scripts/build_agent_notebook.py && python -m unittest tests.test_audit_remediation
python scripts/check_docs_contract.py
python -m unittest discover -s tests
```
Bộ đầy đủ chỉ được còn 5 lỗi có sẵn trên Windows (`test_r1_w4_agent_scenarios` ×2, `test_r1_w4_media_pipeline` ×1,
`test_r1_w4_customer_ref_and_v8` ×2).

## Mẫu báo cáo (gửi owner chuyển cho Claude)
- Nhánh + SHA đầu nhánh; danh sách tệp đổi.
- Mỗi mục A–F: CLI cuối cùng (lệnh + cờ), quyết định thiết kế đã chọn ở chỗ 03 còn để ngỏ, test đã thêm.
- Kết quả từng lệnh kiểm (chạy/qua/bỏ qua/lỗi).
- Chỗ lệch khỏi 03 (nếu có) và lý do.
