# 06 — Sau khi merge (việc của owner, Claude hỗ trợ)

1. **Bộ đệm lời khách**: lấy bản đệm thật (Drive `w67_utterances/…`, bản sao trên ổ E:), sao lưu, chạy
   `drop-cache` rồi `migrate-injection` với `--old-briefs` = phiếu v3 (`acc6850a…`). Kiểm số dòng xóa/đổi khớp báo cáo PR.
2. **Glimmer viết lại** các phiếu bị xóa đệm (4 khung lỗi; ước ≤ 104 phiếu) trên Colab A100 40 GB, cách làm như đợt
   batch 2 (`colab_w67_batch2`): `sft_utterances fill --writer-label muse-glimmer-30b …`, rồi `verify`.
   Có thể ghép cùng phiên A100 với đợt sinh có khung nâng đỡ: Glimmer viết trước, giải phóng GPU, rồi nạp Qwen.
3. **Sinh lại quỹ đạo** cho mọi ca của 6 khung (≈ 66 ca: t08 ×24, t06 ×10, t02 ×10, t09 ×10, t11_pdf_email_la ×10 —
   trừ ca nào phiếu không đổi): Qwen ×4 + DeepSeek ×2, cấu hình như W6.4 (DeepSeek giờ thấp điểm).
   - `t11_pdf_email_la` vốn yếu (Qwen 0/40, chủ yếu `finish_reason_length`, `agent_response_failed`) → cho vào đợt
     **sinh có khung nâng đỡ**.
   - `t09_the_he_thong_gia_voucher`: chạy thường (thước v4 đã có A_code ở 9/10 ca).
4. **Bỏ vết cũ** của các ca này (đầu vào đã đổi), kể cả mẫu đã chấm vòng 1; chấm code v4 rồi đưa vào vòng chấm gộp.
5. Cập nhật tệp bàn giao phiên và phễu dữ liệu (4.5) với số ca/khung bị làm lại và lý do.
