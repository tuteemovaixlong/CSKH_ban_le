# 02 — Phạm vi và tiêu chí xong

## Trong phạm vi
1. Sửa **phiếu (brief)** và nếu cần `select`/kỳ vọng của 4 khung lỗi: `t08_bon_luot_doi_size`,
   `t08_doi_chu_de_roi_quay_lai`, `t06_doi_size_hai_chieu`, `t02_chat_lieu_giat_ui_thieu_du_lieu`.
2. Đổi giá trị giả trùng bộ đo ở `t09_the_he_thong_gia_voucher` (mã voucher) và `t11_pdf_email_la` (email/tên miền).
3. Công cụ bộ nhớ đệm lời khách trong `scripts/sft_utterances.py`:
   - `drop-cache`: xóa dòng đệm của các phiếu đã đổi (để bước `fill` cho Glimmer viết lại);
   - `migrate-injection`: thay chuỗi chèn lệnh cũ bằng chuỗi mới trong lời khách đã viết (t09), không gọi model.
4. Test chống trùng giá trị bộ đo (mọi ca + phiếu SFT).
5. `sft_select export --max-tool-chars N` (mặc định 3.000 để tái lập vòng 1; vòng gộp sau sẽ dùng 8.000).
6. Cập nhật SHA ghim trong `tests/test_w670_sft_fixture_cases.py`, dựng lại `notebooks/colab_agent.ipynb`.

## Ngoài phạm vi
- `evals/suites/*`, system prompt, `retailops/*`, runner `scripts/run_agent_scenarios.py`.
- Viết lời khách (kể cả "tạm"), chạy Glimmer/DeepSeek/Qwen, Colab, gọi API, sửa dữ liệu trên Drive hay ổ E:.
- Thước của khung khác (thước v4 đã chốt), sửa `export` cho vòng 2 (chờ owner chọn phương án), trọng tài Neon.
- 23 khung có Tier C cao vì lỗi nội dung thật của model.

## Tiêu chí xong
- Cả 6 khung sinh lại không mâu thuẫn: `sft_cases generate` không báo phiếu tự mâu thuẫn; `check_cases` 1.200/1.200.
- **Phiếu ngoài 6 khung trùng từng byte với v3** (lời khách cũ dùng lại nguyên); báo cáo liệt kê đúng các `brief_id` đổi.
- Test chống trùng bộ đo đỏ trên nhánh gốc (2 chỗ) và xanh sau khi sửa.
- Bộ test liên quan xanh (xem 04); bộ đầy đủ không thêm lỗi mới ngoài 5 lỗi có sẵn trên Windows
  (`test_r1_w4_agent_scenarios` ×2, `test_r1_w4_media_pipeline` ×1, `test_r1_w4_customer_ref_and_v8` ×2 — đã xác nhận
  hỏng y hệt trên `main` 09baa9d ở máy owner).
- Nhánh `phase-r1-w6-7-1-sua-khung` đã push (không PR), kèm báo cáo theo mẫu ở 04.
