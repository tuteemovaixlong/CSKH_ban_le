# 04 — Kiểm và báo cáo

## Lệnh kiểm (Windows, từ gốc repo, `PYTHONUTF8=1`)
```
python -m unittest tests.test_w670_ruler_calibration tests.test_w670_sft_fixture_cases tests.test_w670_sft_select_build tests.test_w644_eval_regrade
python -m unittest discover -s tests -p "test_w671_*.py"                   # test mới: chống trùng bộ đo, drop-cache, migrate-injection
python scripts/check_docs_contract.py
python scripts/build_agent_notebook.py && python -m unittest tests.test_audit_remediation
python -m unittest discover -s tests                                        # bộ đầy đủ như CI
```
- `tests/test_w670_sft_fixture_cases.py` (`test_full_generation_matches_archived_dataset_and_has_no_contradictions`):
  cập nhật SHA ca + phiếu mới; tập `redo` thêm 6 khung; số phiếu "giữ nguyên v3" và SHA của chúng cập nhật theo — phần
  phiếu ngoài 6 khung phải trùng từng byte với phiếu v3 `acc6850a…`.
- Bộ đầy đủ: chỉ được còn 5 lỗi có sẵn trên Windows (xem 02). Lỗi khác phải sửa hoặc giải thích.

## Kiểm bằng tay (ghi kết quả vào báo cáo)
1. Sinh lại ra thư mục tạm: `python scripts/sft_cases.py generate --out <tmp>` rồi `check --out <tmp>` → 1.200/1.200.
2. So phiếu mới với phiếu v3 (lấy `briefs_sft_v1.jsonl` từ nhánh gốc): liệt kê mọi `brief_id` khác, nhóm theo khung,
   tách riêng nhóm "chỉ khác `injection`" (t09) với nhóm "phải viết lại".
3. Chạy `drop-cache` và `migrate-injection` trên **bản sao** bộ đệm giả (không dùng dữ liệu thật) → in số dòng xóa/đổi.
4. In 1 phiếu mới mỗi khung (đã chuẩn hóa) để owner đọc.

## Mẫu báo cáo (gửi owner chuyển cho Claude; Claude dùng làm mô tả PR)
- Nhánh gốc + commit gốc; danh sách tệp đổi.
- Từng khung: đổi gì (persona/notes/must_not_include/select/giá trị), vì sao.
- SHA mới: `cases_sft_v1.jsonl`, `briefs_sft_v1.jsonl`; số phiếu đổi theo khung; số phiếu chỉ đổi `injection`.
- Danh sách sản phẩm `t02` sau khi sửa `select`.
- Kết quả từng lệnh kiểm (số test chạy/qua/bỏ qua/lỗi) và 5 lỗi có sẵn.
- Việc còn lại cho owner (06).
