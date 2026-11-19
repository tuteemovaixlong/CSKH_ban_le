# 03 — Thiết kế chi tiết

Nguyên tắc chung: chỉ đổi những gì cần để lời khách (do Glimmer viết lại sau) **không còn mâu thuẫn** với kỳ vọng; kỳ
vọng giữ đúng quy ước bộ đo (thước v4). Mỗi chỗ sửa có chú thích tiếng Việt nêu lý do + ca bộ đo làm căn cứ (nếu có).
`fake_model` chỉ dùng cho runner giả: chỉnh tối thiểu nếu cần để `check_cases` vẫn 100%.

## 1. `t08_bon_luot_doi_size` (`scripts/sft_templates/t08_multiturn.py`, lớp `T08BonLuotDoiSize`)
Mục tiêu: 4 lượt của **một** lần đổi size đầu tiên — tra đơn → hỏi hạn → hỏi phí → nhờ mở đổi.
- `persona`: bỏ con số lượt (ví dụ `khách_hàng_doi_size_lan_dau`); persona là chữ Glimmer đọc được.
- Lượt 1 (`tra_don_luot_1`): `notes` "Chỉ hỏi đơn {mã} đang ở đâu/đã giao chưa; CHƯA nói muốn đổi";
  `must_not_include` thêm `"đổi size"`, `"đổi hàng"`.
- Lượt 2 (`hoi_thoi_han_doi_luot_2`): `notes` "Hỏi chung đổi size được trong bao lâu; chưa nhờ mở đổi";
  `must_not_include` các cụm số lần (`"lần 2"`, `"lần thứ 2"`, `"lần 3"`, `"lần thứ 3"`, `"lần 4"`, `"lần thứ 4"`)
  và `"mở biểu mẫu"`, `"mở đổi"`.
- Lượt 3 (`hoi_phi_ship_doi_luot_3`): `notes` "Hỏi đổi size có mất phí ship không — đây là LẦN ĐỔI ĐẦU TIÊN của đơn";
  `must_not_include` các cụm số lần như trên + `"lần nữa"`.
- Lượt 4 (`mo_bieu_mau_doi_size_luot_4`): `notes` "Nhờ mở đổi sang size khác của CÙNG sản phẩm trong đơn {mã}";
  `must_not_include` `"mẫu khác"`, `"sản phẩm khác"` + cụm số lần.
- Thêm `earlier_turns` (như `t08_doi_chu_de_roi_quay_lai`) để Glimmer giữ mạch.
- Kỳ vọng giữ nguyên (lượt 3 "miễn phí / 2 chiều / tận nhà" đúng cho lần đổi đầu).

## 2. `t08_doi_chu_de_roi_quay_lai` (`T08DoiChuDeRoiQuayLai`)
- Lượt 2: `notes` "Chuyển sang hỏi CHÍNH SÁCH CHUNG đổi size (bao nhiêu ngày); KHÔNG nhắc mã đơn, KHÔNG nhờ mở đổi";
  `must_not_include` thêm mã đơn `{ext_oid}`, `"mở biểu mẫu"`, `"mở đổi"`, `"đổi giúp"`.
  Kiểm `brief_conflicts`: mã đơn không nằm trong `must_include` của lượt 2 (`["đổi size"]`).
- Lượt 3: `notes` "Quay lại đơn {mã}, NHỜ MỞ ĐỔI SIZE cho đơn đó" (kỳ vọng `choose_order_action_reason` giữ nguyên).

## 3. `t06_doi_size_hai_chieu` (`scripts/sft_templates/t06_exchanges.py`)
- `notes` "Khách chỉ hỏi quy trình đổi size 2 chiều tận nhà cho đơn {mã} (shipper giao/nhận thế nào); CHƯA quyết định
  đổi, KHÔNG nhờ mở đổi"; `must_not_include` thêm `"muốn đổi"`, `"đổi giúp"`, `"mở đổi"`, `"mở biểu mẫu"`.
- Kỳ vọng `reply` giữ nguyên (như `s06_014` lượt 1: hỏi quy trình/phí thì trả lời, chưa mở biểu mẫu).

## 4. `t02_chat_lieu_giat_ui_thieu_du_lieu` (`scripts/sft_templates/t02_products.py`)
- `select`: chỉ sản phẩm **quần áo** (loại trừ giày dép, gia dụng, đồ gia dụng thông minh, phụ kiện, đồ chơi) mà
  chữ "ủi" không có trong `care` (có thể `null`) lẫn `description`. Với `sft_v1` hiện có 8 sản phẩm:
  P-104, P-202, P-203, P-501, P-502, P-503, P-504, P-601 (đủ 10 ca, lặp 2). Ghi danh sách ra trong báo cáo.
- Phiếu giữ ý "hỏi nhiệt độ ủi chính xác"; kỳ vọng giữ thước v4 (`s02_004`: cụm "chưa có thông tin…").
- Đổi `select` làm đổi sản phẩm của các ca → phiếu đổi → lời khách viết lại (liệt kê `brief_id`).

## 5. `t09_the_he_thong_gia_voucher` (`scripts/sft_templates/t09_injections.py`)
- Đổi `code` sang dạng không chứa bất kỳ chuỗi nào của bộ đo, đổi luôn mệnh giá cho khác `s09_015`, ví dụ
  `code = f"UUDAI-VVIP-{case_index:02d}"`, "voucher giảm 300k". Cập nhật `attack_not`/`answer_not` (đang dùng `code` và
  "500k"/"500.000") cho khớp mệnh giá mới.
- Lời khách: chuỗi `injection` nằm nguyên văn trong lời Glimmer → **không viết lại**, dùng `migrate-injection` (mục 7).

## 6. `t11_pdf_email_la` (`scripts/sft_templates/t11_case_assist.py`, dòng `fake_email = …`)
- Đổi tên miền sang miền dành riêng, không trùng bộ đo, ví dụ `f"ketoan-uynhiem-{case_index}@thanhtoan-ncc.example"`.
- Kiểm mọi chỗ dùng email (trang PDF, `attack_not`, `fake_model`). Không đụng lời Glimmer (`customer_messages[].text`).

## 7. Công cụ đệm lời khách (`scripts/sft_utterances.py`)
Bộ đệm `utterances_cache.jsonl` khóa theo `brief_id` (dòng `{"brief_id","user","writer","model"}`); phiếu đổi mà không
xóa đệm thì `fill` dùng lại lời cũ.
- `drop-cache --dir D --old-briefs OLD.jsonl`: so phiếu hiện tại của `D` với `OLD.jsonl` (phiếu v3), xóa dòng đệm của
  mọi `brief_id` có phiếu khác (trừ trường hợp chỉ khác `injection` — để `migrate-injection` xử lý). Ghi bản sao lưu
  `utterances_cache.before_drop.jsonl`, in danh sách đã xóa.
- `migrate-injection --dir D --old-briefs OLD.jsonl`: với phiếu chỉ khác `injection`, thay **đúng một** lần chuỗi
  injection cũ bằng chuỗi mới trong lời đã viết; giữ `writer`/`model`, thêm `"migrated": "injection"`. Dừng có lỗi nếu
  chuỗi cũ xuất hiện 0 hoặc > 1 lần. Không gọi model.
- Cả hai: chạy được offline, có test bằng dữ liệu giả, không đụng dòng đệm của phiếu không đổi.

## 8. Test chống trùng giá trị bộ đo (tệp test mới, ví dụ `tests/test_w671_sft_no_eval_values.py`)
- Gom giá trị giả của bộ đo từ `evals/suites/S*.jsonl`: mọi chuỗi `attack_not`, cộng các mã/email/URL/tên miền trong
  `turns` và `case_setup` (regex mã `[A-Z]{2,}(?:-[A-Z0-9]+)+`, email, `https?://…`, `tên.(com|org|net|vn|io|xyz|info)`),
  dài ≥ 8 ký tự, bỏ `SIM-…`, `KB:…`, `P-…`, `retailops.local`.
- Sinh 1.200 ca + phiếu (`generate_cases`), khẳng định không giá trị nào là chuỗi con của ca/phiếu nào.
- Trên nhánh gốc test phải bắt đúng 2 chỗ (`VCH-VIP-500K` ×10, `retailops-mail.com` ×10).

## 9. `sft_select export --max-tool-chars N`
- Thay hằng `MAX_TOOL_RESULT_CHARS` bằng tham số truyền vào `_extract_turn_steps`/`export_judge_round` (mặc định 3.000),
  ghi `max_tool_chars` vào `map.json`, và câu "cắt tối đa 3.000 ký tự" trong `RUBRIC_TEXT` lấy theo tham số.
- Test: xuất cùng dữ liệu ở 3.000 trùng từng byte với hành vi cũ; ở 8.000 thì `tool_results` dài hơn.
