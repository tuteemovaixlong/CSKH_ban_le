# 01 — Hiện trạng (19/11/2026)

## Bối cảnh
- 1.200 ca SFT từ 120 khung (`scripts/sft_templates/`), lời khách do Muse Glimmer 30B viết theo phiếu (brief).
- Quỹ đạo: Qwen ×4 + DeepSeek ×2 mỗi ca, chấm code v3 (`scripts/eval_regrade.regrade_record_v3`) + giám khảo Gemini.
- Thước v4 (PR trước): 8 khung lấy thước theo ca đo sinh đôi; chấm lại 7.200 lượt → ca có ứng viên 1.018 → 1.052,
  không ca nào ngoài 8 khung đổi kết quả.

## Bốn khung lỗi (lời khách / dữ liệu mâu thuẫn với đáp án — sửa thước không cứu được)
Rà 13 khung mà cả hai model qua code ≤ 15% + đọc lý do `khong_dat` của giám khảo ở 25 khung có ≥ 60% mẫu Tier C.

| Khung | Lỗi | Bằng chứng |
|---|---|---|
| `t08_bon_luot_doi_size` (12 ca) | persona `khách_hàng_doi_size_4_luot` → Glimmer hiểu "đổi size lần thứ 4": lời khách nói "đổi size lần 1/3/4", lượt 1 đã nói "muốn đổi size", lượt 4 có ca xin "đổi sang mẫu khác" (không được đổi khác sản phẩm). Kỳ vọng lượt 3 "miễn phí" chỉ đúng cho lần đổi đầu (`shipping_fees.md`, `s06_014`: từ lần 2 khách trả phí). | Qwen 0/48, DeepSeek 2/24 qua code; 43 lượt mở biểu mẫu ngay lượt 1 |
| `t08_doi_chu_de_roi_quay_lai` (12 ca) | lượt 2 phải là câu hỏi chính sách chung, nhưng lời khách nhắc chính đơn ("đơn SIM-O-50100 đã giao rồi, vậy đổi size được không") → model mở biểu mẫu ở lượt 2, rồi lượt 3 không mở lại. | Qwen 2/48, DeepSeek 2/24; 38 lượt mở form lượt 2, 35 lượt thiếu form lượt 3 |
| `t06_doi_size_hai_chieu` (10 ca) | phiếu "Khách hỏi đổi size đơn X thì shipper giao thế nào" → lời khách "mình muốn đổi size, quy trình thế nào" → mở biểu mẫu hay trả lời đều hợp lý; khung chỉ nhận `reply`. | 34 lượt `choose_order_action_reason` thay vì `reply` |
| `t02_chat_lieu_giat_ui_thieu_du_lieu` (10 ca) | `select` chỉ lọc theo `description`, nhưng phần lớn sản phẩm có trường `care` ghi cách ủi (P-101 "ủi nhiệt độ thấp", P-103 "ủi ở nhiệt độ trung bình") và có cả đồ không ủi được (P-301 giày, P-401 nồi). Đáp án "chưa có thông tin" sai với các sản phẩm đó. | model trích đúng `care` vẫn trượt; 40 lượt trượt cụm "chưa có thông tin" |

Khung KHÔNG lỗi dù nghi ban đầu: `t04_bo_mot_mon` (bộ đo `s04_015/s04_016` cũng coi "không hủy lẻ, chỉ hủy cả đơn"
là đúng), `t05_tra_hang_phi_ship` (KB không nói ai chịu phí gửi trả → đúng là phải nói chưa có thông tin; model bịa
là lỗi thật). 23 khung còn lại có Tier C cao là lỗi nội dung thật của model (bịa chính sách khi chưa tra, cộng trùng
phí ship vào `amount`, mời đổi khi `within_*_window: false`, COD gọi thành chuyển khoản…) — không thuộc PR này.

## Hai chỗ trùng giá trị giả của bộ đo (quét 24 giá trị giả của S09/S11/S12 trong 1.200 ca)
| Khung | Giá trị | Ca bộ đo | Nằm ở đâu trong ca SFT |
|---|---|---|---|
| `t09_the_he_thong_gia_voucher` (10 ca) | mã `VCH-VIP-500K-{n}` chứa nguyên `VCH-VIP-500K` | `s09_015` | chuỗi chèn lệnh `inj` trong phiếu → **nguyên văn** trong lời khách (Glimmer bắt buộc chép nguyên chuỗi `injection`) |
| `t11_pdf_email_la` (10 ca) | `ketoan-uynhiem-{n}@fake-retailops-mail.com` chứa `retailops-mail.com` | `s11_019` (`attack_not`) | trang PDF đính kèm do code khung sinh (`case_setup…attachment.pages[1]`), `attack_not`, `fake_model` — không nằm trong lời Glimmer |

Danh mục khung (`docs/phase_role_aware_ops/W6_7_0_sft_tooling/04_DANH_MUC_KHUNG_CA.md`) đã cấm dùng lại giá trị giả
của ca đo; hai chỗ này lọt vì là chuỗi con.
