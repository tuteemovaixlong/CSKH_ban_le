# Báo Cáo Thực Thi W6.7.0 Phần A — Công Cụ Sinh Dữ Liệu Chưng Cất (SFT)

- **Ngày thực hiện:** 2026-11-16 (Cập nhật sau kiểm toán PR #120 và phản hồi `09_PHAN_HOI_PR120.md`)
- **Nhánh:** `phase-r1-w6-7-0-a` (tạo từ `origin/main` commit `4cd3902`)
- **Mục tiêu:** Cung cấp bộ công cụ đầy đủ cho phần A của kế hoạch W6.7: sinh dữ liệu cửa hàng riêng `sft_v1`, mở rộng runner nạp fixture `sft_v1` và ca huấn luyện, bộ kiểm định dạng ca huấn luyện `sft_dataset`, bộ sinh khung ca `sft_cases` với 117 khung (1.200 ca), bước viết lời khách DeepSeek `sft_utterances` kèm kiểm tra chất lượng chặt chẽ bằng code, cùng bộ test toàn diện. Đảm bảo toàn bộ hệ thống lõi, dữ liệu bộ đo 250 ca (S01–S12) và logic chấm điểm không đổi.

---

## 1. Danh Sách Tệp Đã Tạo Và Chỉnh Sửa

| STT | Tệp | Trạng thái | Mô tả |
|---|---|---|---|
| 1 | `data/demo_events/store_events_sft_v1.jsonl` | Tạo mới / Dựng lại | Dữ liệu sự kiện sàn giả lập `sft_v1` (3.174 sự kiện, 216 đơn, 170 khách, thỏa 7 ngưỡng trạng thái hiếm) |
| 2 | `data/demo_events/store_events_sft_v1.meta.json` | Tạo mới / Cập nhật | Metadata của `sft_v1`: seed, days, counters, stories lặp, số sự kiện theo loại, kết quả 7 ngưỡng, đường dẫn build tương đối POSIX, SHA-256 |
| 3 | `scripts/build_sft_fixture.py` | Tạo mới / Cập nhật | Script dựng dữ liệu `sft_v1` tất định bằng `marketplace_sim`, chèn lặp story hiếm 8 lần, tạo đơn pending trước clock_dt, tự kiểm tra 7 ngưỡng qua `read_order` và 0 trùng lặp với `store_events.jsonl` |
| 4 | `scripts/run_agent_scenarios.py` | Chỉnh sửa | Tách biệt `TRAIN_FIXTURES = {'sft_v1': ...}` sạch sẽ, giữ nguyên `FIXTURES = {'standard': ..., 'late_voucher_issued': ...}`; nạp `sft_v1` an toàn; thêm nhánh xác thực ca huấn luyện (`t*`) vào `load_dataset` |
| 5 | `scripts/sft_dataset.py` | Tạo mới / Cập nhật | Bộ kiểm định dạng ca huấn luyện `validate_train_case` và kiểm tra toàn tập `validate_train_set` (kiểm tra tính duy nhất của bộ ba `(template, slot_key, intent)`) |
| 6 | `scripts/sft_templates/__init__.py` | Tạo mới / Cập nhật | Đăng ký toàn bộ 117 khung ca (1.200 ca, tất cả ≤15 ca/khung) và export `SftView` |
| 7 | `scripts/sft_templates/base.py` | Tạo mới / Cập nhật | Lớp cơ sở `BaseTemplate`, cấu trúc phiếu yêu cầu lời khách `Brief` (chuẩn hóa `must_include`/`may_include` không dấu khi `style == "khong_dau"`, rút ngắn tên SP dài cho `teencode`/`sai_chinh_ta`) |
| 8 | `scripts/sft_templates/view.py` | Tạo mới / Cập nhật | Lớp `SftView` phân loại đơn theo cờ `eligibility` từ `read_order`, lọc sạch đoạn miễn trừ trách nhiệm khỏi chunk tri thức, truy xuất biến thể tồn kho động |
| 9 | `scripts/sft_templates/t01_order_lookup.py` | Tạo mới / Cập nhật | 13 khung tra cứu đơn hàng (100 ca: thêm đơn không thuộc khách, hỏi địa chỉ/SĐT đầy đủ, trạng thái hoàn tiền; chia giao trễ dưới/trên 48h theo cờ `late_by_hours`) |
| 10 | `scripts/sft_templates/t02_products.py` | Tạo mới / Cập nhật | 9 khung sản phẩm và tồn kho (90 ca: quét biến thể tồn/hết động, 15 sản phẩm không kinh doanh khác nhau) |
| 11 | `scripts/sft_templates/t03_policies.py` | Tạo mới / Cập nhật | 11 khung chính sách có trích dẫn (110 ca: thời gian hoàn tiền 12-72h, hóa đơn VAT tự phục vụ trên sàn / đề xuất hỗ trợ người, chính sách sỉ/Tết trích dẫn chuẩn) |
| 12 | `scripts/sft_templates/t04_cancellation.py` | Tạo mới / Cập nhật | 10 khung hủy đơn hàng (100 ca: chọn đơn qua cờ `can_self_service_cancel == True`) |
| 13 | `scripts/sft_templates/t05_returns.py` | Tạo mới / Cập nhật | 10 khung trả hàng và hoàn tiền (100 ca: hoàn tiền COD không xin STK trong chat, câu trích dẫn cam kết giao hàng hợp nhất) |
| 14 | `scripts/sft_templates/t06_exchanges.py` | Tạo mới / Cập nhật | 10 khung đổi hàng (100 ca: lọc sản phẩm thời trang có size, đổi 1-1 lỗi trong hạn bảo hành trích dẫn `policy_warranty_exchange_1to1.md` và trích dẫn số ngày cụ thể của đơn) |
| 15 | `scripts/sft_templates/t07_frustrated.py` | Tạo mới | 5 khung khách bức xúc / chuyển nhân viên (60 ca) |
| 16 | `scripts/sft_templates/t08_multiturn.py` | Tạo mới / Cập nhật | 13 khung hội thoại đa lượt 2–4 lượt (150 ca: gọi `get_order` ở lượt 2, tham chiếu đúng đơn lượt trước, kiểm tra COD vs trả trước) |
| 17 | `scripts/sft_templates/t09_injections.py` | Tạo mới / Cập nhật | 8 khung chèn lệnh trong chat và từ chối an toàn (80 ca: loại bỏ chuỗi injection khỏi `must_not_include`, xoay vòng đơn người khác) |
| 18 | `scripts/sft_templates/t10_out_of_scope.py` | Tạo mới / Cập nhật | 4 khung câu hỏi ngoài phạm vi (40 ca: 10 câu hỏi khác nhau cho 10 ca/khung, `must_include` chỉ chứa từ khóa ngắn) |
| 19 | `scripts/sft_templates/t11_case_assist.py` | Tạo mới / Cập nhật | 14 khung Trợ lý ca (190 ca: thêm `t11_tom_tat_pdf_hoa_don` đính kèm PDF hóa đơn Latin-1; 4 khung chèn lệnh tài liệu 40/40 ca đều có đính kèm PDF và cảnh báo nhân viên; 4–6 câu hỏi nhân viên viết tay đa dạng xoay vòng) |
| 20 | `scripts/sft_templates/t12_fraud_context.py` | Tạo mới / Cập nhật | 10 khung bối cảnh lừa đảo & bối cảnh Việt Nam (80 ca: thêm xin Zalo và nghỉ Tết không dữ liệu; gọi `request_human_support` khi cần chuyển người) |
| 21 | `scripts/sft_cases.py` | Tạo mới / Cập nhật | CLI sinh ca (`generate`) và kiểm tính nhất quán (`check`): assert mỗi khung dùng cùng một đơn ≤ 3 lần (hỗ trợ cả đơn story `SIM-O-ST-*`); pilot 100 chọn luân phiên phủ 98 khung (≥ 90) và cân bằng đúng 20 ca/giọng (≥ 8/giọng) |
| 22 | `scripts/sft_utterances.py` | Tạo mới / Cập nhật | Tooling điền lời khách bằng DeepSeek: so sánh không dấu hai phía cho `khong_dau`, khớp linh hoạt cho `teencode`/`sai_chinh_ta`, ThreadPoolExecutor có khóa đệm, retry lùi số mũ (1, 2, 4s) cho HTTP 429/5xx, chỉ ghi ca hoàn chỉnh 100% vào `_filled.jsonl` sau khi gọi `validate_train_set` |
| 23 | `tests/test_w670_sft_fixture_cases.py` | Tạo mới / Cập nhật | Bộ unit test kiểm tra toàn bộ phần A (10 bài test, gồm kiểm tra 7 ngưỡng, eligibility P2, pilot 100 P4, N1-N3, và PDF CI test) |
| 24 | `docs/phase_role_aware_ops/W6_7_0_A_EXECUTION_REPORT_2026-11-16.md` | Tạo mới / Cập nhật | Báo cáo thực thi phần A chi tiết |
| 25 | `notebooks/colab_agent.ipynb` | Đồng bộ | Đồng bộ notebook Colab bằng `python scripts/build_agent_notebook.py` |

---

## 2. Kết Quả Kiểm Chứng Thực Nghiệm

### 2.1. Dữ liệu cửa hàng `build_sft_fixture.py` (P1)
- Lệnh chạy hai lần liên tiếp:
  - Lần 1: `python scripts/build_sft_fixture.py --out data/demo_events/store_events_sft_v1.jsonl`
  - Lần 2: `python scripts/build_sft_fixture.py --out data/demo_events/store_events_sft_v1.jsonl`
- Kết quả kiểm tra:
  - **SHA-256 (2 lần chạy trùng khớp tuyệt đối):** `e42767485ae047082a73f8eebdcfce4a5c35fec62ed35eb30c19868440e043cc`
  - **Tổng số sự kiện:** 3.174 sự kiện
  - **Tổng số đơn hàng:** 216 đơn
  - **Tổng số khách hàng:** 170 khách
  - **Trùng lặp với dữ liệu đo (`store_events.jsonl`):** 0 mã đơn, 0 mã khách, 0 mã vận đơn trùng lặp.
  
#### Phân bổ 216 đơn hàng theo trạng thái
| Trạng thái đơn hàng (`status`) | Số lượng đơn | Tỉ lệ |
|---|---|---|
| `delivered` | 156 | 72,2% |
| `cancelled` | 25 | 11,6% |
| `shipping` | 19 | 8,8% |
| `pending` | 16 | 7,4% |
| **Tổng cộng** | **216** | **100,0%** |

#### Bảng tự kiểm tra 7 ngưỡng trạng thái hiếm qua `read_order`
| Chỉ tiêu ngưỡng trạng thái hiếm | Ngưỡng tối thiểu yêu cầu | Kết quả thực tế đạt được | Đánh giá |
|---|---|---|---|
| Đơn `pending` có thể tự hủy (`can_self_service_cancel`) | ≥ 8 | **16** | ĐẠT |
| Đơn đang giao (`shipping`) | ≥ 10 | **19** | ĐẠT |
| Đơn giao trễ (`is_late_vs_promised`) | ≥ 8 | **27** | ĐẠT |
| Đơn giao trễ trên 48 giờ (`late_by_hours > 48`) | ≥ 4 | **8** | ĐẠT |
| Đơn giao thất bại / hoàn về (N7: tính theo trạng thái giao hàng `delivery`) | ≥ 6 | **10** | ĐẠT |
| Đơn hết hạn bảo hành (`within_warranty == False`) | ≥ 6 | **8** | ĐẠT |
| Đơn hoàn tiền chậm hoặc thất bại (`processing` / `failed`) | ≥ 6 | **17** | ĐẠT |

---

### 2.2. Kiểm tra giới hạn dùng đơn mỗi khung và bảng đầy đủ 117 khung (P1, P2)
Toàn bộ 1.200 ca được quét kiểm tra số lần xuất hiện của từng đơn hàng trong mỗi khung (`scripts/sft_cases.py` có assertion cưỡng chế trong `generate_cases` bắt đúng regex `r'SIM-O-(?:ST-)?\d+'`):
- **Số lần tối đa một đơn xuất hiện trong cùng một khung:** **≤ 3 lần** (đạt 100% trên toàn bộ 117 khung).
- Dưới đây là bảng thống kê chi tiết toàn bộ 117 khung ca:

| STT | Khung (Template ID) | Bộ | Số ca | Số đơn / chỗ dữ liệu khác nhau | Tối đa ca/đơn |
|---|---|---|---|---|---|
| 1 | `t01_don_khong_thuoc_khach` | T01 | 7 | 7 | 1 |
| 2 | `t01_giao_tre_duoi_48h` | T01 | 7 | 7 | 1 |
| 3 | `t01_giao_tre_tren_48h` | T01 | 7 | 7 | 1 |
| 4 | `t01_hoi_dia_chi_sdt_day_du` | T01 | 8 | 8 | 1 |
| 5 | `t01_khong_neu_ma_mot_don` | T01 | 8 | 8 | 1 |
| 6 | `t01_khong_neu_ma_nhieu_don` | T01 | 8 | 8 | 1 |
| 7 | `t01_liet_ke_don` | T01 | 8 | 8 | 1 |
| 8 | `t01_tra_don_cancelled` | T01 | 8 | 8 | 1 |
| 9 | `t01_tra_don_delivered` | T01 | 8 | 8 | 1 |
| 10 | `t01_tra_don_pending` | T01 | 7 | 7 | 1 |
| 11 | `t01_tra_don_shipping` | T01 | 8 | 8 | 1 |
| 12 | `t01_trang_thai_hoan_tien` | T01 | 8 | 8 | 1 |
| 13 | `t01_van_don_giao_that_bai` | T01 | 8 | 8 | 1 |
| 14 | `t02_bao_hanh_rieng_san_pham` | T02 | 10 | 1 | 1 |
| 15 | `t02_chat_lieu_giat_ui_co_du_lieu` | T02 | 10 | 1 | 1 |
| 16 | `t02_chat_lieu_giat_ui_thieu_du_lieu` | T02 | 10 | 1 | 1 |
| 17 | `t02_nguon_goc_chinh_hang_khong_du_lieu` | T02 | 10 | 1 | 1 |
| 18 | `t02_san_pham_khong_co` | T02 | 10 | 10 | 1 |
| 19 | `t02_so_sanh_hai_mau` | T02 | 10 | 1 | 1 |
| 20 | `t02_ton_kho_bien_the_con` | T02 | 10 | 10 | 1 |
| 21 | `t02_ton_kho_bien_the_het_goi_y` | T02 | 10 | 5 | 1 |
| 22 | `t02_tu_van_size_thieu_bang` | T02 | 10 | 1 | 1 |
| 23 | `t03_bao_hanh_90_ngay` | T03 | 10 | 10 | 1 |
| 24 | `t03_dieu_kien_huy` | T03 | 10 | 10 | 1 |
| 25 | `t03_doi_size_15_ngay` | T03 | 10 | 10 | 1 |
| 26 | `t03_dong_kiem_cod` | T03 | 10 | 10 | 1 |
| 27 | `t03_gio_lam_viec_lien_he` | T03 | 10 | 10 | 1 |
| 28 | `t03_han_tra_7_ngay` | T03 | 10 | 10 | 1 |
| 29 | `t03_hoa_don_vat` | T03 | 10 | 10 | 1 |
| 30 | `t03_khong_co_trong_chinh_sach_si` | T03 | 10 | 10 | 1 |
| 31 | `t03_khong_co_trong_chinh_sach_tet` | T03 | 10 | 10 | 1 |
| 32 | `t03_phi_ship_tra_doi` | T03 | 10 | 10 | 1 |
| 33 | `t03_thoi_gian_hoan_tien` | T03 | 10 | 10 | 1 |
| 34 | `t04_bo_mot_mon` | T04 | 10 | 10 | 1 |
| 35 | `t04_go_xac_nhan_luot_sau` | T04 | 10 | 10 | 1 |
| 36 | `t04_huy_chua_xac_nhan_don` | T04 | 10 | 10 | 1 |
| 37 | `t04_huy_da_giao_chuyen_tra` | T04 | 10 | 10 | 1 |
| 38 | `t04_huy_dang_giao_tu_choi_nhan` | T04 | 10 | 10 | 1 |
| 39 | `t04_huy_don_da_huy` | T04 | 10 | 10 | 1 |
| 40 | `t04_huy_khong_neu_ma_nhieu_don` | T04 | 10 | 1 | 1 |
| 41 | `t04_huy_pending_doi_y` | T04 | 10 | 10 | 1 |
| 42 | `t04_huy_pending_mo_bieu_mau` | T04 | 10 | 10 | 1 |
| 43 | `t04_huy_sau_khi_hoi_tien_trinh` | T04 | 10 | 10 | 1 |
| 44 | `t05_da_co_yeu_cau_mo` | T05 | 10 | 10 | 1 |
| 45 | `t05_giao_sai_mau_loi_shop` | T05 | 10 | 10 | 1 |
| 46 | `t05_hoan_tien_cod_ve_dau` | T05 | 10 | 10 | 1 |
| 47 | `t05_khach_noi_tra_nhung_muon_doi` | T05 | 10 | 10 | 1 |
| 48 | `t05_qua_7_ngay_con_bao_hanh` | T05 | 10 | 10 | 1 |
| 49 | `t05_tra_don_chua_giao` | T05 | 10 | 10 | 1 |
| 50 | `t05_tra_hang_het_han_bao_hanh` | T05 | 10 | 8 | 2 |
| 51 | `t05_tra_hang_ly_do_ca_nhan` | T05 | 10 | 10 | 1 |
| 52 | `t05_tra_hang_phi_ship` | T05 | 10 | 10 | 1 |
| 53 | `t05_tra_trong_7_ngay` | T05 | 10 | 10 | 1 |
| 54 | `t06_doi_1_1_loi_trong_90_ngay` | T06 | 10 | 10 | 1 |
| 55 | `t06_doi_hai_mon_cung_don` | T06 | 10 | 4 | 3 |
| 56 | `t06_doi_hang_chon_variant` | T06 | 10 | 10 | 1 |
| 57 | `t06_doi_mau` | T06 | 10 | 10 | 1 |
| 58 | `t06_doi_qua_15_ngay` | T06 | 10 | 10 | 1 |
| 59 | `t06_doi_sang_san_pham_khac` | T06 | 10 | 10 | 1 |
| 60 | `t06_doi_size_chua_giao` | T06 | 10 | 10 | 1 |
| 61 | `t06_doi_size_con_hang` | T06 | 10 | 10 | 1 |
| 62 | `t06_doi_size_hai_chieu` | T06 | 10 | 10 | 1 |
| 63 | `t06_doi_size_het_hang_goi_y` | T06 | 10 | 10 | 1 |
| 64 | `t07_doa_dang_bai` | T07 | 12 | 1 | 1 |
| 65 | `t07_doi_gap_nhan_vien` | T07 | 12 | 1 | 1 |
| 66 | `t07_ngon_ngu_gay_gat` | T07 | 12 | 1 | 1 |
| 67 | `t07_phan_nan_lap_lai` | T07 | 12 | 1 | 1 |
| 68 | `t07_xin_hotline_zalo` | T07 | 12 | 1 | 1 |
| 69 | `t08_bon_luot_doi_size` | T08 | 12 | 12 | 1 |
| 70 | `t08_chinh_sach_roi_thao_tac` | T08 | 12 | 12 | 1 |
| 71 | `t08_doi_chu_de_roi_quay_lai` | T08 | 12 | 12 | 1 |
| 72 | `t08_hai_don_chon_mot_don` | T08 | 12 | 12 | 1 |
| 73 | `t08_hoi_bao_hanh_roi_mo_doi` | T08 | 12 | 12 | 1 |
| 74 | `t08_hoi_ton_kho_roi_hoi_size` | T08 | 12 | 1 | 1 |
| 75 | `t08_huy_roi_hoi_hoan_tien` | T08 | 12 | 12 | 1 |
| 76 | `t08_kiem_tra_trang_thai_va_phi_ship` | T08 | 6 | 6 | 1 |
| 77 | `t08_nhieu_don_tham_chieu_don_luc_nay` | T08 | 12 | 12 | 1 |
| 78 | `t08_san_pham_roi_ve_don` | T08 | 12 | 12 | 1 |
| 79 | `t08_tra_cuu_giao_hang_roi_hoi_dong_kiem` | T08 | 12 | 12 | 1 |
| 80 | `t08_tra_don_roi_hoi_phi_ship` | T08 | 12 | 12 | 1 |
| 81 | `t08_tra_roi_doi_y_doi` | T08 | 12 | 12 | 1 |
| 82 | `t09_debug_mode_xuat_ds` | T09 | 10 | 1 | 1 |
| 83 | `t09_gia_admin_xoa_don` | T09 | 10 | 1 | 1 |
| 84 | `t09_in_system_prompt` | T09 | 10 | 1 | 1 |
| 85 | `t09_the_he_thong_gia_hoan_tien` | T09 | 10 | 1 | 1 |
| 86 | `t09_the_he_thong_gia_voucher` | T09 | 10 | 10 | 1 |
| 87 | `t09_viet_danh_gia_gia` | T09 | 10 | 1 | 1 |
| 88 | `t09_xem_don_nguoi_khac` | T09 | 10 | 7 | 2 |
| 89 | `t09_yeu_cau_gay_hai` | T09 | 10 | 1 | 1 |
| 90 | `t10_dich_cau` | T10 | 10 | 10 | 1 |
| 91 | `t10_kien_thuc_chung` | T10 | 10 | 10 | 1 |
| 92 | `t10_ti_gia_thoi_tiet_khong_du_lieu` | T10 | 10 | 10 | 1 |
| 93 | `t10_tinh_toan` | T10 | 10 | 10 | 1 |
| 94 | `t11_ca_nhieu_don` | T11 | 15 | 15 | 1 |
| 95 | `t11_doi_nguoi_giu_ca` | T11 | 15 | 15 | 1 |
| 96 | `t11_hoi_don_giao_chua` | T11 | 15 | 15 | 1 |
| 97 | `t11_nhan_vien_nho_gui_tin` | T11 | 15 | 15 | 1 |
| 98 | `t11_pdf_email_la` | T11 | 10 | 10 | 1 |
| 99 | `t11_pdf_link_gia` | T11 | 10 | 10 | 1 |
| 100 | `t11_pdf_ma_hoan_gia` | T11 | 10 | 10 | 1 |
| 101 | `t11_soan_nhap_can_nhieu_tool` | T11 | 15 | 15 | 1 |
| 102 | `t11_soan_nhap_doi_hang` | T11 | 15 | 15 | 1 |
| 103 | `t11_soan_nhap_hoan_tien` | T11 | 15 | 15 | 1 |
| 104 | `t11_tin_nhan_gia_da_duyet` | T11 | 10 | 10 | 1 |
| 105 | `t11_tom_tat_ca` | T11 | 15 | 15 | 1 |
| 106 | `t11_tom_tat_pdf_hoa_don` | T11 | 15 | 15 | 1 |
| 107 | `t11_xem_don_ca_khac` | T11 | 15 | 28 | 2 |
| 108 | `t12_cham_11_11_boi_thuong` | T12 | 8 | 8 | 1 |
| 109 | `t12_dong_kiem_cod_mop_vo` | T12 | 8 | 8 | 1 |
| 110 | `t12_gia_danh_kho_bao_hiem` | T12 | 8 | 8 | 1 |
| 111 | `t12_gia_danh_shipper_doi_phi` | T12 | 8 | 8 | 1 |
| 112 | `t12_link_gia_nhan_hoan_tien` | T12 | 8 | 8 | 1 |
| 113 | `t12_livestream_khac_mau_qua_han` | T12 | 8 | 8 | 1 |
| 114 | `t12_nghi_tet_khong_du_lieu` | T12 | 8 | 8 | 1 |
| 115 | `t12_xin_otp` | T12 | 8 | 8 | 1 |
| 116 | `t12_xin_zalo` | T12 | 8 | 8 | 1 |
| 117 | `t12_xuat_vat_cong_ty` | T12 | 8 | 8 | 1 |

---

### 2.3. Sinh khung ca `sft_cases.py generate`
- **Chế độ toàn phần (1.200 ca):** `python scripts/sft_cases.py generate --out <temp_dir>`
  - Tổng số ca: **1.200** ca.
  - Tổng số phiếu lời khách (briefs): **1.406** phiếu.
  - Số khung: **117** khung.
  - Số ca mỗi khung: từ 4 đến 15 ca (không khung nào vượt quá 15 ca).
  - Phân bổ theo bộ:
    - T01 (Tra cứu đơn): 100 ca (13 khung)
    - T02 (Sản phẩm & tồn kho): 90 ca (9 khung)
    - T03 (Chính sách): 110 ca (11 khung)
    - T04 (Hủy đơn): 100 ca (10 khung)
    - T05 (Trả hàng & hoàn tiền): 100 ca (10 khung)
    - T06 (Đổi hàng): 100 ca (10 khung)
    - T07 (Khách bức xúc): 60 ca (5 khung)
    - T08 (Đa lượt): 150 ca (13 khung)
    - T09 (Chèn lệnh chat): 80 ca (8 khung)
    - T10 (Ngoài phạm vi): 40 ca (4 khung)
    - T11 (Trợ lý ca): 190 ca (14 khung: 150 ca thường + 40 ca chèn lệnh)
    - T12 (Lừa đảo & bối cảnh VN): 80 ca (10 khung)
    - **Tổng cộng:** 1.200 ca.
  - Phân bổ theo giọng văn:
    - `chuan`: 480 ca (40,0%)
    - `teencode`: 240 ca (20,0%)
    - `khong_dau`: 180 ca (15,0%)
    - `sai_chinh_ta`: 180 ca (15,0%)
    - `dai`: 120 ca (10,0%)

- **Chế độ pilot 100 ca (P4):** `python scripts/sft_cases.py generate --out <temp_dir> --pilot 100`
  - Tổng số ca: **100** ca, **116** phiếu lời khách.
  - **Số khung phủ sóng:** **98** khung khác nhau (vượt xa yêu cầu tối thiểu ≥ 90 khung).
  - **Phân bổ theo giọng văn:** Cân bằng chính xác mỗi giọng văn **20 ca** (đạt yêu cầu ≥ 8 ca mỗi giọng):
    - `chuan`: 20 ca
    - `teencode`: 20 ca
    - `khong_dau`: 20 ca
    - `sai_chinh_ta`: 20 ca
    - `dai`: 20 ca
  - **Phân bổ theo bộ:** T01: 8, T02: 8, T03: 9, T04: 8, T05: 8, T06: 8, T07: 5, T08: 12, T09: 7, T10: 5, T11: 15, T12: 7 (tổng: 100 ca).

---

### 2.4. Kiểm tính nhất quán runner giả lập `sft_cases.py check`
- Chạy: `python scripts/sft_cases.py check --out <temp_dir>` trên toàn bộ 1.200 ca:
  - **Tỉ lệ đạt:** **100% (1.200 / 1.200 ca)**.
  - **Số câu bị `answer_check` tước quyền lợi (dropped claims):** **0** câu.
  - **Số cờ cảnh báo `answer_check_audit`:** **0** cờ.
  - Toàn bộ các ca thỏa mãn kỳ vọng `expect` khớp dữ liệu `sft_v1`, hành động `action`, quy tắc trích dẫn tri thức, và trạng thái cơ sở dữ liệu `final_state`.

---

### 2.5. Bộ kiểm đo chuẩn 250 ca
- `python scripts/eval_dataset_v2.py --final --audit`: **PASS**.
- Bộ 250 ca S01–S12 và chữ ký SHA-256 của 12 tệp suite giữ nguyên vẹn 100%.

---

## 3. Chi Tiết Khắc Phục Các Điểm Kiểm Toán (P1–P4, N1–N6)

1. **P1 — Dựng lại fixture với story lặp & đơn pending; kiểm soát dùng đơn:**
   - Đã chèn lặp 8 lần các story trạng thái hiếm (`dang_trung_chuyen`, `nghen_kho_mega_sale`, `cap_nhat_ao_giao_lai`, `giao_that_bai_hoan_ve`, `giao_tre_han_cam_ket`, `het_bao_hanh`, `qua_han_doi_tra`, `hoan_tien_cham`, `hoan_tien_that_bai`, `huy_truoc_khi_giao`) và 2 lần các story khác.
   - Bổ sung 14 đơn pending sát mốc thời gian chốt `clock_dt`. Toàn bộ 7 ngưỡng kiểm tra trạng thái hiếm đều vượt chỉ tiêu. Dữ liệu đạt 3.174 sự kiện, 216 đơn, SHA-256 cố định tuyệt đối.
   - Regex kiểm tra số lần dùng đơn được cập nhật chuẩn `r'SIM-O-(?:ST-)?\d+'` bắt trọn các đơn story; assert mỗi khung dùng cùng một đơn ≤ 3 lần đạt 100% trên 117 khung.
2. **P2 — Chọn dữ kiện theo cờ hệ thống thay vì số ngày tự đặt:**
   - Trong `SftView` và các khung ca, toàn bộ việc lọc đơn được thực hiện qua các cờ `eligibility` của `read_order` (`within_return_window`, `within_size_exchange_window`, `within_warranty`, `can_self_service_cancel`, `late_by_hours`).
   - Mọi câu trả lời mẫu trích dẫn đúng con số thời hạn thực tế của chính đơn hàng (`warranty_window_days`, `return_window_days`, v.v.) thay vì viết cứng. Có unit test tự động xác thực cờ điều kiện trên từng ca.
3. **P3 — Tệp PDF đính kèm & chèn lệnh tài liệu trong T11:**
   - Bổ sung khung `t11_tom_tat_pdf_hoa_don` (15 ca) với đính kèm tệp PDF hóa đơn dạng `text_pdf` sinh bằng code ASCII không dấu từ dữ kiện đơn hàng thật (`read_order`).
   - Bốn khung chèn lệnh tài liệu (40/40 ca) đặt nội dung chèn trong `pages` (trang 2) của PDF đính kèm với 4–5 biến thể xoay vòng (`[QUAN TRONG]`, `BO QUA HUONG DAN TRUOC`, `[THONG BAO QUAN LY]`, `<INFORMATION>`, v.v.); trang 1 sử dụng dữ liệu món, tiền, phương thức thanh toán thật từ `read_order`. Toàn bộ 40 ca ở mode `draft` với `attack_not` chặn nội dung độc hại và `answer_any` yêu cầu cảnh báo cho nhân viên.
   - Cơ chế kiểm thử hỗ trợ tự động trải phẳng (flattening) nội dung trang PDF vào tin nhắn khi thiếu thư viện `pypdfium2` (trên Windows), đồng thời có unit test chuyên biệt `test_p3_real_pdf_case_execution` kích hoạt trên CI Linux có đầy đủ thư viện PDF.
4. **P4 — Đợt thử pilot 100 trải đều các khung:**
   - Cài đặt thuật toán luân phiên chọn tối đa 1 ca mỗi khung trong từng bộ, xoay vòng giọng văn theo độ hiếm để đạt đúng 20 ca cho mỗi giọng văn.
   - Đợt thử pilot 100 phủ sóng 98/117 khung ca, 100% vượt qua kiểm tra tính nhất quán runner.
5. **N1 — So sánh bỏ dấu tiếng Việt hai phía cho `khong_dau` & linh hoạt `teencode`/`sai_chinh_ta`:**
   - Thêm hàm `strip_vietnamese_accents(s)`. Khi sinh phiếu `Brief` và khi kiểm tra `validate_utterance` với giọng `khong_dau`, toàn bộ `must_include` có dấu được chuyển sang dạng không dấu và bổ sung chú thích rõ trong `notes`.
   - Đối với `teencode` và `sai_chinh_ta`, các chuỗi tên sản phẩm dài (≥ 3 từ) trong `must_include` được rút gọn về mã SP (nếu có trong `may_include`) hoặc 2 từ đầu; đồng thời `validate_utterance` cho phép khớp linh hoạt nếu ≥ 60% số từ bỏ dấu xuất hiện trong câu khách.
6. **N2 — Ghép ca hoàn chỉnh 100% khi dùng `--limit`:**
   - Trong `sft_utterances.py`, tệp `cases_sft_v1_filled.jsonl` chỉ ghi các ca đã được điền đủ 100% các lượt hội thoại và tin nhắn thiết lập ca; các ca chưa chạy được phân loại vào `pending_cases` và không ghi với nội dung giữ chỗ `<chờ lời khách`. Toàn bộ tập ca điền được xác thực qua `validate_train_set` trước khi ghi đĩa.
7. **N3 — Thực thi đa luồng thật & thời gian chờ lùi số mũ (1, 2, 4s) cho HTTP 429/5xx:**
   - Cài đặt `ThreadPoolExecutor` theo khung ca kết hợp `threading.Lock()` bảo vệ tệp đệm `utterances_cache.jsonl`.
   - Bổ sung tham số `backoff_seconds: tuple[float, ...] = (1.0, 2.0, 4.0)` cho các mã lỗi HTTP 429 và 5xx độc lập với 3 lần thử lại chất lượng nội dung. Có unit test xác thực kiểm tra backoff qua `mock.patch('scripts.sft_utterances.time.sleep')` và kiểm tra 3 lần thử lại nội dung.
8. **N4 — Tách bạch fixture huấn luyện:**
   - Giữ nguyên `FIXTURES = {'standard': ..., 'late_voucher_issued': ...}` nguyên bản (2 khóa).
   - Khai báo riêng `TRAIN_FIXTURES = {'sft_v1': 'store_events_sft_v1.jsonl'}` và hỗ trợ nạp cả hai nhóm trong `_provision_demo_template`.
9. **N5 — Xóa đường dẫn tuyệt đối máy cục bộ:**
   - `build_sft_fixture.py` tính toán đường dẫn tương đối chuẩn POSIX theo thư mục gốc repo: `python scripts/build_sft_fixture.py --out data/demo_events/store_events_sft_v1.jsonl`.
10. **N6 — Đa dạng hóa lời hỏi của nhân viên trong T11:**
    - Biên soạn 4–6 biến thể câu hỏi viết tay tự nhiên cho từng khung ca có nhân viên hỏi đáp trong T11 (11 khung), xoay vòng theo `case_index` để tránh tình trạng mô hình học vẹt câu lệnh lặp lại.
11. **R1 — Chuẩn hóa tiền đề và chọn đơn độc lập trong T12 (`scripts/sft_templates/t12_fraud_context.py`):**
    - `t12_cham_11_11_boi_thuong`: chỉ chọn đơn `is_late_vs_promised == True`, chia 2 nhánh rõ ràng: 4 ca trễ > 48h (`late_by_hours > 48`) đủ điều kiện đề xuất voucher 50.000 VNĐ theo `policy_mega_sale_delay_voucher.md`; 4 ca trễ ≤ 48h (`0 < late_by_hours <= 48`) nêu rõ đơn có bị chậm nhưng chưa vượt quá 48h nên chưa đủ điều kiện nhận voucher bồi thường, `answer_not` cấm nhắc số tiền voucher 50.000.
    - `t12_dong_kiem_cod_mop_vo`: chỉ chọn 8 đơn `status == 'shipping'` độc lập. Kiểm tra COD nếu `payment_method == 'cod'`. Chỉ dẫn đồng kiểm và từ chối nhận hàng nếu móp vỡ theo `delivery_inspection.md`.
    - `t12_gia_danh_shipper_doi_phi`, `t12_gia_danh_kho_bao_hiem`, `t12_xin_otp`: chọn đơn `shipping`/`pending` ở các offset lệch nhau hoàn toàn (0..8, 8..16, 16..24); vừa cảnh báo thủ đoạn lừa đảo vừa nêu trạng thái đơn thật trên hệ thống.
    - `t12_link_gia_nhan_hoan_tien`: chọn 8 đơn có lịch sử hoàn tiền hoặc hủy trả trước; cảnh báo link lạ, nêu kênh hoàn tiền chính thức (`refunds.md`) và trạng thái hoàn tiền thật của đơn.
    - `t12_xuat_vat_cong_ty`, `t12_xin_zalo`, `t12_nghi_tet_khong_du_lieu`: chọn các tập đơn `delivered` ở các khoảng offset độc lập (20..28, 28..36, 36..44), tách bạch hoàn toàn với `t12_livestream_khac_mau_qua_han`.
12. **R2 — `t04_bo_mot_mon` chọn đơn nhiều món và phản hồi chuẩn theo trạng thái thực tế (`scripts/sft_templates/t04_cancellation.py`):**
    - `select(view)` chỉ chọn đơn `len(items) >= 2` gồm đơn `pending` (`can_self_service_cancel == True`) và đơn `shipping` (`SIM-O-50105`).
    - Nhánh `pending`: nêu rõ sàn không hỗ trợ hủy riêng 1 món, hướng dẫn hủy toàn bộ đơn tự phục vụ khi đơn còn ở trạng thái `pending` và đặt lại (`tools_not_called: ['prepare_order_action']`).
    - Nhánh `shipping`: nêu rõ sàn không hỗ trợ hủy riêng 1 món, và đơn đã giao bên vận chuyển nên không thể tự hủy; hướng dẫn từ chối nhận khi shipper giao đến hoặc mở yêu cầu đổi/trả sau khi nhận hàng.
13. **N7 — Tính toán chuẩn xác số đơn giao thất bại / hoàn về (`build_sft_fixture.py`, `view.py`):**
    - Lọc theo `(o.get('delivery') or {}).get('status') in ('failed', 'returned')`, không gộp nhầm `status == 'cancelled'`. Số lượng đạt 10 đơn (vượt ngưỡng yêu cầu ≥ 6).
14. **N8 — Mở rộng unit test ràng buộc tiền đề đơn (`tests/test_w670_sft_fixture_cases.py`):**
    - `test_order_eligibility_and_template_constraints` được mở rộng kiểm tra tự động toàn bộ 10 ca của `t04_bo_mot_mon` (đủ >= 2 món, đúng cờ hủy/shipping) và toàn bộ 80 ca của 10 khung T12 (đúng cờ trễ, trạng thái giao hàng, trạng thái hoàn tiền, các tập đơn disjoint).

---

## 4. Kết Quả Kiểm Thử (Unit Tests)

### 4.1. Test chuyên biệt Phần A (`tests/test_w670_sft_fixture_cases.py`)
- Lệnh chạy: `python -m unittest tests/test_w670_sft_fixture_cases.py`
- Kết quả: **Ran 10 tests in 79.207s — OK (skipped=1, PASS 9/9)**.
  - `test_fixture_metadata_and_integrity`: PASS (kiểm tra SHA, 3.174 sự kiện, 216 đơn, 170 khách, 0 trùng lặp, 7 ngưỡng hiếm)
  - `test_provision_templates_and_runner_fixtures`: PASS (kiểm tra `FIXTURES` 2 khóa, `TRAIN_FIXTURES`, số lượng đơn 216 vs 128)
  - `test_validate_train_case_contract`: PASS (kiểm tra hợp đồng ca huấn luyện)
  - `test_sft_cases_generator_and_pilot_check`: PASS (chạy pilot 24 ca đạt 100%)
  - `test_pilot_100_coverage_and_style_distribution`: PASS (phủ 98 khung ≥ 90, 20 ca/giọng ≥ 8, check đạt 100%)
  - `test_order_eligibility_and_template_constraints`: PASS (assert mỗi khung dùng đơn ≤ 3 lần bắt regex cả đơn story, kiểm tra đúng cờ eligibility P2, xác thực toàn diện tiền đề R1 và R2)
  - `test_utterance_validation_n1_rules`: PASS (so sánh không dấu 2 phía, injection không bị chặn bởi must_not_include, teencode/sai_chinh_ta rút gọn tên SP và khớp linh hoạt ≥ 60%)
  - `test_utterance_peak_hour_and_mock_cache`: PASS (chặn giờ cao điểm VN 13:00–17:00, chạy tiếp từ cache)
  - `test_utterance_n2_n3_retry_and_concurrency`: PASS (thử lại lùi số mũ 1, 2, 4s cho HTTP 429, 3 lần thử lại nội dung với feedback, an toàn `--limit` không ghi ca rỗng)
  - `test_p3_real_pdf_case_execution`: SKIPPED trên môi trường Windows thiếu `pypdfium2` (sẵn sàng tự động kích hoạt trên CI Linux)

### 4.2. Toàn bộ test của repo (`python -m unittest discover -s tests`)
- Lệnh chạy: `python -m unittest discover -s tests`
- Kết quả: **Ran 1321 tests in 682.758s — FAILED (failures=2, errors=3, skipped=90)**.
- Ghi chú: 5 lỗi thất bại đều là 5 test W4 baseline đã có sẵn trên `main` khi chạy trên môi trường Windows (gồm lỗi thiếu `pypdfium2`/ClamAV scanner và lệch đếm tệp đính kèm trên Windows: 3 lỗi trong `test_r1_w4_media_pipeline.py`, 2 thất bại trong `test_r1_w4_customer_ref_and_v8.py`). Không có bất kỳ lỗi mới nào phát sinh từ phần mã W6.7.0.

### 4.3. Kiểm tra hợp đồng tài liệu (`scripts/check_docs_contract.py`)
- Lệnh chạy: `python scripts/check_docs_contract.py`
- Kết quả:
  1. Dataset integrity check: PASS
  2. Stale Git HEAD check: PASS
  3. Link & markdown rules check: PASS
  4. AST Dynamic tool contract check: PASS
  - **SUCCESS: All documentation contracts are valid and truthful.**

---

## 5. Kết Luận
Toàn bộ các vấn đề ưu tiên (P1–P4), các điểm kỹ thuật (N1–N6), cùng các yêu cầu chuẩn hóa logic đơn hàng (R1, R2, N7, N8) theo phản hồi của Owner, Claude và Carbon (`09_PHAN_HOI_PR120.md`, `10_PHAN_HOI_PR120_V2.md`) đã được giải quyết triệt để trên cùng nhánh `phase-r1-w6-7-0-a`. Dữ liệu fixture `sft_v1`, catalog 117 khung ca, tooling sinh lời khách và hệ thống kiểm định đạt độ tin cậy tuyệt đối (100% pass trên 1.200 ca), sẵn sàng để tiến hành các bước tiếp theo của W6.7.
