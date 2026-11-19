# 02 — Phạm vi, bất biến, tiêu chí xong

## Trong phạm vi (chi tiết ở 03)
- **A. Thước:** đổi kỳ vọng 4 khung (`t07_xin_hotline_zalo`, `t03_hoa_don_vat`, `t07_phan_nan_lap_lai`,
  `t07_ngon_ngu_gay_gat`) trong `scripts/sft_cases.py` (và `fake_model`/`final_state` của khung nếu cần cho `check`);
  vá `eval_regrade.regrade_record_v3` (chuyển nhân viên phải thành công).
- **B. Khung T14** mới `scripts/sft_templates/t14_handoff.py`: 18 khung × 10 ca = 180 ca chuyển/không chuyển nhân viên,
  đăng ký **sau cùng** trong `TEMPLATES`; `T14` vào `EASY_TIGHT` (trần mẫu thứ hai 25 %), **không** vào `HARD_SUITES` của `scripts/sft_select.py`.
- **C. Kiểm "lọt rào"** cho lời khách: cờ phiếu `rail_pass`, kiểm trong `scripts/sft_utterances.py` (fill + verify).
- **D. Khung đỡ:** proxy chèn gợi ý `scripts/sft_hint_proxy.py`, công cụ phiếu đỡ `scripts/sft_hints.py`, hỗ trợ lượt
  chạy có gợi ý trong `sft_select score/select` và `sft_build` (nhãn, chặn lộ gợi ý). **Không** viết nội dung gợi ý.
- **E. Tỉ trọng T11 + Tier S đúng chỗ:** T11 ra khỏi `HARD_SUITES`; trần tỉ trọng theo bộ/chế độ (mặc định tắt) trong
  `sft_select select`; phiếu đỡ theo ca cho T11 `draft`.
- Test mới `tests/test_w673_*.py`; cập nhật SHA ghim (`tests/test_w670_sft_fixture_cases.py`, …); dựng lại
  `notebooks/colab_agent.ipynb`.

## Ngoài phạm vi
- `evals/suites/*`, `agent_protocol.py` (system prompt, mô tả tool), `retailops/*` (kể cả `safety.py`), runner
  `scripts/run_agent_scenarios.py`.
- Viết lời khách (kể cả "tạm"), viết nội dung phiếu đỡ, chạy Glimmer/Qwen/DeepSeek, Colab, gọi API, Drive, ổ E:.
- Sửa ứng dụng theo F59–F61 (rào không dấu, hàng đợi ưu tiên SOP 5, câu `RAGE_REPLY`).
- Thước các khung khác (đã chốt ở v4/W6.7.1).

## Bất biến (test phải chứng minh)
1. **1.200 ca cũ**: mọi ca ngoài 4 khung ở mục A trùng từng byte với v4; 4 khung đó chỉ khác `expect` (và
   `fake_model`/`final_state`), **không khác `user`, `case_setup`, `customer`, mã đơn**. Thứ tự và `id` giữ nguyên.
2. **Phiếu cũ**: 1.406 phiếu v4 trùng từng byte (kể cả sau khi thêm trường `rail_pass` — chỉ ghi ra khi `True`).
   → không phải viết lại câu khách nào của 1.200 ca.
3. Khung T14 sinh **sau** mọi khung cũ và không làm đổi trạng thái RNG dùng cho khung cũ (khung cũ sinh trước, đã xong).
4. Không giá trị giả nào của bộ đo trong ca/phiếu T14 (`tests/test_w671_sft_no_eval_values.py` phủ cả T14).
5. Hành vi với lượt chạy không gợi ý không đổi: `export --round 1/2`, `import`, `select --max-per-case 1`, `sft_build`
   trên dữ liệu giả cũ cho kết quả trùng từng byte với trước khi sửa (trừ nhãn mới chỉ xuất hiện khi có lượt gợi ý).

## Tiêu chí xong
- `sft_cases generate` ra 1.380 ca (1.200 + 180), không phiếu tự mâu thuẫn; `sft_cases check` (gateway giả) qua
  1.380/1.380 với `fake_model` của từng khung.
- Mọi bất biến ở trên có test; test mới xanh; bộ đầy đủ chỉ còn 5 lỗi có sẵn trên Windows
  (`test_r1_w4_agent_scenarios` ×2, `test_r1_w4_media_pipeline` ×1, `test_r1_w4_customer_ref_and_v8` ×2).
- Nhánh `phase-r1-w6-7-3-khung-do` đã push (không PR), kèm báo cáo theo mẫu ở 04.
