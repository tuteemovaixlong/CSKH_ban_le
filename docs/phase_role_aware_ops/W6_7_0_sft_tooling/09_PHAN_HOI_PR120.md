# 09 — Phản hồi kiểm PR #120 (phần A), vòng 1

Claude kiểm PR #120 (nhánh `phase-r1-w6-7-0-a`, đầu `8f75f00`) ngày 17/11. Phần lớn đạt; **chưa merge** vì còn 4 lỗi phải sửa (P1–P4) và 5 điểm nhỏ (N1–N5). Sửa trên **cùng nhánh**, thêm commit (không rebase, không force-push), cập nhật báo cáo thực thi.

## Đã đạt (không cần làm lại)

- a/b: chỉ chạm tệp phần A; nhánh `sft_v1` ở runner tương đương `BusinessStore.seed()` (cùng tài khoản hệ thống, catalog, phiên) chỉ khác `jsonl_path`; đường `standard`/`late_voucher_issued` và ca `s…` giữ nguyên logic.
- c: dựng hai lần cùng SHA `18b4e714…`; 0 mã đơn/khách/vận đơn trùng `store_events.jsonl` (chỉ trùng 20 mã sản phẩm, đúng vì chung catalog).
- d: `validate_train_case` dùng lại `eval_dataset_v2.validate_case` trên bản chuẩn hóa, không sửa `eval_dataset_v2.py`.
- e (một phần): 1.200 ca đúng phân bổ 04, 112 khung, ≤15 ca/khung, 0 tiêu đề trùng ca đo.
- f (một phần): urllib, `DEEPSEEK_API_KEY`, chặn 13–17h VN ngày thường, đủ luật kiểm, thử lại 3 lần, chạy tiếp từ đệm, test dùng client giả.

## P1 — Fixture quá ít đơn ở các trạng thái hiếm → 23/112 khung lặp cùng một đơn

`sft_v1` hiện có 129 đơn: 111 đã giao, 11 đã hủy, **5 đang giao, 2 chờ xử lý, 1 quá 90 ngày, 5 giao trễ**. Hệ quả (đo trên `generate` đủ 1.200 ca):

- `t01_giao_tre_tren_48h`, `t01_van_don_giao_that_bai`, `t05_tra_hang_het_han_bao_hanh`: **10 ca cùng đúng 1 đơn**.
- `t04_huy_pending_mo_bieu_mau`, `t04_huy_pending_doi_y`, `t04_huy_chua_xac_nhan_don`, `t04_go_xac_nhan_luot_sau`, `t04_huy_sau_khi_hoi_tien_trinh`, `t01_tra_don_pending`, `t06_doi_size_chua_giao`: 10 ca chỉ trên **2 đơn**; `t08_huy_roi_hoi_hoan_tien` 12 ca trên 2 đơn.
- Tổng 1.037 cặp (khách, đơn) khác nhau cho 1.200 ca.

(Nguyên nhân gốc là thiết kế A1 của Claude: 30 ngày + 13 story mỗi loại một lần. Sửa A1 như sau.)

Sửa `scripts/build_sft_fixture.py` (KHÔNG sửa `marketplace_sim/`):

1. Sau `run_days(30)`, chèn **lặp** các story khan, mỗi story nhiều lần (story có bộ đếm `next_story_no` riêng nên mỗi lần ra đơn mới): `dang_trung_chuyen`, `nghen_kho_mega_sale`, `cap_nhat_ao_giao_lai`, `giao_that_bai_hoan_ve`, `giao_tre_han_cam_ket`, `het_bao_hanh`, `qua_han_doi_tra`, `hoan_tien_cham`, `hoan_tien_that_bai`, `huy_truoc_khi_giao` — ví dụ 6–8 lần mỗi story; các story còn lại 1–2 lần. Ghi số lần vào meta (`stories` thành danh sách có lặp hoặc `{tên: số lần}`).
2. Tạo thêm đơn **chờ xử lý** (`pending`): sau 30 ngày chạy thêm 1 ngày với tốc độ đặt đơn cao bằng cách ghi đè **trong bộ nhớ** `sim.params['orders_per_day_range']` (ví dụ [20, 25]) trước `run_days(1)` rồi trả lại giá trị cũ; hoặc cách khác tương đương không sửa `marketplace_sim/`. Nếu đơn mới vẫn chuyển hết sang `confirmed`/`shipping`, báo lại để chọn cách khác (đừng tự sửa simulator).
3. Ngưỡng tối thiểu, `build_fixture` tự kiểm và báo lỗi nếu thiếu (đếm qua `SftView`/`read_order`, không qua sự kiện thô): **≥ 8 đơn `pending` có `can_self_service_cancel`**, ≥ 10 đơn đang giao, ≥ 8 đơn giao trễ (`is_late_vs_promised`), trong đó ≥ 4 trễ trên 48 giờ, ≥ 6 đơn giao thất bại/hoàn về, ≥ 6 đơn hết bảo hành (`within_warranty` = false), ≥ 6 hoàn tiền chậm/thất bại. Bỏ ràng buộc 100–160 đơn (cho phép đến ~260).
4. Mỗi khung: **một đơn xuất hiện tối đa 3 lần** trong cùng khung (assert trong `generate_cases`); nếu `select` không đủ chỗ thì giảm `target` của khung đó và dồn số ca sang khung khác **cùng bộ** để giữ đúng phân bổ 04.
5. Dựng lại `store_events_sft_v1.jsonl` + meta; báo SHA mới, số đơn theo trạng thái, số chỗ dữ liệu khác nhau mỗi khung (bảng: khung → số đơn khác nhau / số ca).

## P2 — Khung chọn dữ kiện theo số ngày tự đặt thay vì cờ của hệ thống

`SftView` chia đơn đã giao theo `days_since_delivery` với ngưỡng cứng 7/15/90, và các khung dùng các nhóm đó làm "còn hạn trả", "quá hạn đổi size", "còn bảo hành". Nhưng thời hạn bảo hành **khác nhau theo sản phẩm** (`warranty_window_days` hiện có 30/60/90/180/365, `warranty_source = product_override`). Hiện chưa sai chỉ do may mắn; khi dựng lại fixture (P1) sẽ sai.

Sửa: các nhóm trong `SftView` và `select` của khung **lấy từ cờ trong `eligibility` của `read_order`**: `within_return_window`, `within_size_exchange_window`, `within_warranty`, `can_self_service_cancel`, `can_open_return_or_exchange`, `is_late_vs_promised`, `late_by_hours`. Ví dụ "còn bảo hành, quá hạn trả" = `within_warranty and not within_return_window`; "hết bảo hành" = `not within_warranty`. Mọi con số thời hạn trong `answer_any`/`answer_all`/`fake_model` (nếu có) lấy từ `return_window_days`, `size_exchange_window_days`, `warranty_window_days` của chính đơn đó, không viết cứng "90 ngày". Thêm test: với mọi ca, đơn trong ca thỏa đúng cờ mà khung yêu cầu.

## P3 — T11: không ca nào có tệp PDF; "chèn lệnh tài liệu" thực ra là chèn trong tin nhắn

Cả 190 ca T11 chỉ có `customer_messages` một tin, **không có `attachment`**. Khung `t11_tom_tat_pdf_hoa_don` trong 04 không có (thay bằng `t11_tom_tat_don_va_khach`). Bốn khung chèn lệnh (`t11_pdf_link_gia`, `t11_pdf_email_la`, `t11_tin_nhan_gia_da_duyet`, `t11_pdf_ma_hoan_gia`) đặt nội dung chèn vào tin nhắn chat do DeepSeek viết. Điểm yếu thật của Qwen ở W6.4 là **làm theo lệnh nằm trong nội dung tệp PDF** (S11, ≥ 4 lượt), nên phần này là trọng tâm.

Sửa (theo mẫu `case_setup` của ca đo S11 có PDF, ví dụ `s11_011…`; xem cách runner nạp `attachment` `{kind: 'text_pdf', name, pages[]}`):

1. Thêm khung `t11_tom_tat_pdf_hoa_don` (≈ 10–15 ca, summary hoặc ask): khách gửi PDF hóa đơn/biên nhận của đơn `sft_v1`; nội dung trang do **code** sinh từ dữ kiện đơn (mã đơn, món, tổng tiền lấy từ `read_order`), không chép số liệu của ca đo.
2. Bốn khung chèn lệnh tài liệu (40 ca) đặt **nội dung chèn trong `pages` của PDF đính kèm** (do code sinh, có nhiều biến thể câu chèn: link nhận quà, email lạ, "đã được quản lý duyệt hoàn tiền", mã hoàn tiền giả, lệnh "bỏ qua hướng dẫn, gửi ngay…"); tin nhắn chat của khách (DeepSeek viết) chỉ là lời gửi kèm tệp bình thường. Ít nhất **25/40 ca ở mode `draft`** (nơi Qwen thua ở W6.4): `attack_not` chặn nội dung chèn xuất hiện trong bản nháp; `answer_any` yêu cầu cảnh báo cho nhân viên.
3. Lấy lại số ca từ các khung T11 thường để giữ đúng 150 + 40 = 190.
4. `check` vẫn 100%. Lưu ý: đọc PDF cần `pypdfium2` (máy Windows của owner thiếu — chính là 5 test W4 hỏng sẵn). Nếu `check` các ca PDF không chạy được trên Windows, ghi rõ và chứng minh bằng test chạy trên CI (ubuntu có đủ thư viện), không bỏ qua ca.

## P4 — Đợt thử `--pilot 100` chỉ phủ 12/112 khung

`generate_cases` lấy `cases_by_suite[s][:N]` → chỉ khung đầu mỗi bộ (ví dụ T11 cả 15 ca là `t11_tom_tat_ca`). Đợt thử dùng để soi chất lượng mọi khung trước khi chạy đủ, nên phải trải đều: chọn **mỗi khung tối đa 1 ca** (luân phiên khung trong bộ, giữ đúng chỉ tiêu 100 theo bộ; bộ nào chỉ tiêu > số khung thì lấy ca thứ hai của khung theo thứ tự), xoay giọng văn để mỗi giọng có mặt ở mọi bộ có thể. Test: pilot 100 phủ ≥ 90 khung; mọi giọng văn có ≥ 8 ca.

## Điểm nhỏ

- **N1 — Ràng buộc không thể thỏa:** 68 phiếu có giọng `khong_dau` nhưng `must_include` chứa chữ có dấu (tên sản phẩm "Áo Thun Nữ Cotton…", màu "Trắng"…) → luật khong_dau luôn loại → ca bị bỏ. Sửa: với `khong_dau`, so `must_include` sau khi **bỏ dấu cả hai phía** (và ghi rõ trong phiếu rằng tên sản phẩm được viết không dấu); với `teencode`/`sai_chinh_ta`, tên sản phẩm dài cho phép khớp theo mã/biến thể thay vì nguyên văn tên dài, hoặc chỉ yêu cầu mã sản phẩm/từ khóa ngắn. Test cho cả hai.
- **N2 — `fill` ghép ca còn chỗ trống:** khi dùng `--limit` (hoặc phiếu chưa chạy), ca có phiếu chưa điền vẫn được ghi vào `cases_sft_v1_filled.jsonl` với lời khách `<chờ lời khách…>` vì chỉ ca "thất bại" mới bị loại. Sửa: ca chỉ "hoàn chỉnh" khi **không còn chỗ trống nào** (mọi lượt và mọi tin `case_setup` đã điền); ca thiếu ghi vào báo cáo theo nhóm "chưa chạy" và "thất bại". Gọi `validate_train_set` trên tệp `_filled` trước khi ghi. Test với `--limit`.
- **N3 — `--concurrency` không có tác dụng** (chạy tuần tự). Hoặc cài đặt thật (ThreadPoolExecutor theo khung: các khung song song, trong một khung tuần tự để luật giống ≤ 0,7 vẫn đúng; ghi đệm có khóa), hoặc bỏ cờ. Ưu tiên cài đặt thật (1.406 phiếu chạy tuần tự ~1,5–2 giờ). Lỗi HTTP 429/5xx: chờ lùi (1, 2, 4 s) không tính vào 3 lần thử nội dung.
- **N4 — `_FixturesDict` che `sft_v1` khi lặp** để test W3.2 (`W32_FIXTURES == set(runner.FIXTURES)`) không đổi. Cách sạch hơn: giữ `FIXTURES` y như cũ (2 khóa), thêm `TRAIN_FIXTURES = {'sft_v1': …}`, và `_provision_demo_template` chấp nhận khóa của cả hai; test mới kiểm `TRAIN_FIXTURES`.
- **N5 — Meta lộ đường dẫn máy:** `store_events_sft_v1.meta.json` có `build_command` chứa đường dẫn tuyệt đối `C:/Users/…/.gemini/antigravity/worktrees/…` (repo đang public). Ghi đường dẫn tương đối repo: `python scripts/build_sft_fixture.py --out data/demo_events/store_events_sft_v1.jsonl`.
- **N6 (khuyến nghị) — Lời nhân viên T11 lặp nguyên văn:** 140 lượt nhân viên chỉ có 26 câu khác nhau (15 ca/khung cùng một câu). Mỗi khung có 4–6 cách hỏi do code xoay vòng (viết tay, không chép S10/S11), để model không học thuộc một câu.

## Kiểm lại sau khi sửa

Chạy và dán số vào báo cáo thực thi: dựng fixture 2 lần (SHA trùng) + bảng đơn theo trạng thái/cờ; `generate` đủ 1.200 + bảng số đơn khác nhau mỗi khung (tối đa 3 lần/đơn/khung); `check` 1.200/1.200; `generate --pilot 100` + số khung phủ; test phần A; toàn bộ test (chỉ 5 test W4 hỏng sẵn trên Windows); `eval_dataset_v2.py --final`; `check_docs_contract.py`.
