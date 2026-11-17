# 10 — Phản hồi kiểm PR #120 (phần A), vòng 2

Claude kiểm lại PR #120 ở đầu `04014e5` ngày 17/11. P1–P4 và N1–N6 của [09](09_PHAN_HOI_PR120.md) **đã đạt**. Còn **một nhóm lỗi nhỏ (R1, R2)**: tiền đề của ca không khớp trạng thái thật của đơn. Sửa trên **cùng nhánh**, thêm commit, cập nhật báo cáo thực thi; sau đó owner merge.

## Đã đạt (Claude tự chạy lại)

- Fixture dựng 2 lần cùng SHA `e4276748…`, khớp tệp trong PR; 216 đơn; 0 trùng đơn/khách/vận đơn với bộ đo.
- 117 khung, 1.200 ca đúng phân bổ; mỗi đơn tối đa 3 lần/khung; 41 khung không gắn đơn đều khác khách từng ca.
- Cờ `eligibility` khớp ý khung ở T04–T06, T08, T01 (còn hạn trả, quá hạn đổi size, còn/hết bảo hành, hủy được…).
- T11: 55 ca `text_pdf` (15 hóa đơn + 40 chèn lệnh, 40/40 mode `draft`); lời nhân viên 88 câu khác nhau / 145 lượt.
- Pilot 100 phủ 98/117 khung, 20 ca mỗi giọng.
- Runner: `FIXTURES` giữ 2 khóa, `TRAIN_FIXTURES` riêng; test W3.2 34/34; test phần A 9 đạt + 1 bỏ qua (thiếu `pypdfium2` trên Windows); `--final` PASS; 0 tệp cấm; không còn đường dẫn máy; CI 6/6 xanh.

## R1 — Các khung T12 dùng đơn không khớp tiền đề

`_BaseContextTemplate.select` trả `view.orders.values()` nên mọi khung T12 (trừ `t12_livestream_khac_mau_qua_han`) dùng chung ~8 đơn đầu danh sách: 7 đơn **đã giao đúng hạn** + 1 **đã hủy**. Với các khung mà nội dung phụ thuộc trạng thái đơn, ca dạy model trả lời lệch dữ kiện tool:

| Khung | Tiền đề | Đơn cần chọn (theo `read_order`) | Kỳ vọng phải theo đơn |
|---|---|---|---|
| `t12_cham_11_11_boi_thuong` | Đơn sale bị giao chậm | `is_late_vs_promised` = true; tách hai nhánh: `late_by_hours` > 48 và ≤ 48 (fixture có 27 đơn trễ, 8 đơn > 48 giờ) | > 48 giờ: đủ điều kiện voucher theo `policy_mega_sale_delay_voucher.md` (nêu trạng thái bồi thường nếu tool có); ≤ 48 giờ: trễ nhưng **chưa** tới ngưỡng 48 giờ nên chưa có voucher. Không được dùng một câu chung "nếu trễ quá 48 giờ thì…" cho đơn không trễ |
| `t12_dong_kiem_cod_mop_vo` | Shipper đang giao COD, khách đồng kiểm thấy móp vỡ | `status` = `shipping` (fixture có 19 đơn đang giao nhưng chỉ 1 đơn COD: dùng đơn đang giao bất kỳ; tiền đề và lời khách nói "đồng kiểm khi nhận", chỉ nhắc COD khi `payment_method` = `cod`) | Hướng dẫn từ chối nhận/ghi nhận với shipper theo chính sách đồng kiểm; không mở trả hàng (chưa nhận) |
| `t12_gia_danh_shipper_doi_phi`, `t12_gia_danh_kho_bao_hiem`, `t12_xin_otp` | Có người mạo danh liên quan đơn đang giao | `shipping` hoặc `pending` | Cảnh báo lừa đảo, không thu thêm phí, không đưa OTP; nêu trạng thái thật của đơn |
| `t12_link_gia_nhan_hoan_tien` | Kẻ gian gửi link "nhận tiền hoàn" | Đơn có hoàn tiền (`refund_summary` khác rỗng) hoặc đã hủy có thanh toán trước | Cảnh báo link giả; hoàn tiền chỉ qua kênh chính thức; nêu trạng thái hoàn tiền thật |

Các khung không phụ thuộc trạng thái đơn (`t12_xuat_vat_cong_ty`, `t12_xin_zalo`, `t12_nghi_tet_khong_du_lieu`) giữ nguyên nhưng **xoay đơn/khách** để không dùng chung 8 đơn với khung khác (ví dụ chọn theo `rng` hoặc lệch chỉ số theo khung).

## R2 — `t04_bo_mot_mon` dùng đơn đã giao/đã hủy

`select` lấy mọi đơn có ≥ 2 món → 9/10 ca là đơn **đã giao**, 1 ca **đã hủy**, nhưng `fake_model` và tiền đề dạy "hủy toàn bộ đơn rồi đặt lại" — sai với đơn đã giao (không hủy được) và đơn đã hủy. Sửa: chỉ chọn đơn ≥ 2 món có `can_self_service_cancel` (chờ xử lý; fixture hiện có 4 đơn như vậy + 1 đơn nhiều món đang giao → 10 ca với tối đa 3 lần/đơn vẫn được); nếu không đủ chỗ thì thêm đơn đang giao với kỳ vọng riêng (không hủy được khi đang giao, gợi ý từ chối nhận hoặc liên hệ nhân viên). Nếu fixture thiếu đơn chờ xử lý nhiều món, báo lại (có thể giảm `target` khung và dồn sang khung T04 khác, giữ tổng T04 = 100).

## Điểm nhỏ (không chặn)

- **N7:** ngưỡng "giao thất bại/hoàn về" trong `build_fixture` đếm cả đơn `cancelled` (25). Đếm riêng đơn có giao thất bại/hoàn về thật để số liệu báo cáo đúng nghĩa.
- **N8:** thêm test: với mọi ca T12 và `t04_bo_mot_mon`, trạng thái/cờ của đơn thỏa điều kiện khung (giống cách test P2).

## Kiểm lại sau khi sửa

`generate` 1.200 (giữ phân bổ, ≤ 3 lần/đơn/khung); bảng trạng thái đơn cho từng khung T12 và `t04_bo_mot_mon`; `check` 1.200/1.200; pilot 100 phủ ≥ 90 khung; test phần A; `check_docs_contract.py`. Fixture không cần dựng lại (SHA giữ nguyên) trừ khi R2 cần thêm đơn.
