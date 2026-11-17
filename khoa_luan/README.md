# Khóa luận tốt nghiệp — tiến độ

Cập nhật: 2026-11-17. Sườn viết lại sau lượt đo W6.4 (§33 W6.4-D18 → D20) và kế hoạch chưng cất W6.7 (§33 W6.4-D12b); xem `00_khung_suon.md`.

## Thông tin chung

- Trường: Đại học Duy Tân · Trường Khoa học Máy tính và Thông tin · Khoa Khoa học Máy tính
- Ngành Khoa học máy tính, chuyên ngành Trí tuệ nhân tạo; lớp môn học CS449A
- Đề tài: **XÂY DỰNG HỆ THỐNG TRỢ LÝ ẢO TÍCH HỢP AI HỖ TRỢ CHĂM SÓC KHÁCH HÀNG CHO KINH DOANH BÁN LẺ**
- Giảng viên hướng dẫn: Phạm Văn Dược · Sinh viên: Lương Anh Tú · Đà Nẵng, 11/2026
- Khóa luận cá nhân, cấu trúc CDIO 4 chương + Mở đầu + Kết luận (C–D–I–O, hai vòng: hệ thống rồi chưng cất), không dùng Scrum; owner chốt độ sâu (lý thuyết có công thức, mã có giải thích kỹ) nên thân bài khoảng 72 trang; hỏi giảng viên giới hạn trang và mẫu Word, nếu bị giới hạn 60 trang thì chuyển dẫn xuất sang Phụ lục J
- Model đánh giá: `Qwen/Qwen3.5-9B` bản chính hãng, Apache 2.0, kèm MTP, phục vụ bằng vLLM trên L4 24 GB (W6.4-D1). DeepSeek-V4.1-Flash qua API: demo production (W6.4-D5), tham chiếu trên 250 ca (W6.4-D19), model thầy cho chưng cất. **Chưng cất SFT LoRA (W6.7) là phần chính** (mục 2.8, 3.6, RQ4 ở 4.5). RQ về supervisor và suy luận/ngữ cảnh **hoãn**; không chạy B, C, D thì bỏ khỏi bộ RQ (còn 4 RQ: truy hồi, an toàn, vận hành, chưng cất). Gemma 4 12B của thiết kế ban đầu chỉ nhắc ở 2.9.

## Tiến độ

| Phần | File | Trạng thái |
|---|---|---|
| Khung sườn | `00_khung_suon.md` | Xong lần 4 (17/11): lý thuyết 15 trang, 15 đoạn mã thân bài; giữ bổ sung của Gemini Carbon (mô hình mối đe dọa 2.6, phân loại lỗi 4.4, ablation và phễu dữ liệu 4.5, yêu cầu có ngưỡng 1.5, LLMOps 4.6); 6 thí nghiệm E1–E6 |
| Đoạn mã minh họa | `08_ma_nguon_minh_hoa.md` | Xong: 27 đoạn, **15 vào thân bài** (≤ 25 dòng, giải thích theo mẫu 7 mục, có test liên quan), 12 vào Phụ lục H; M22–M24 chốt dòng sau khi PR #120 merge |
| Lý thuyết chi tiết | `09_co_so_ly_thuyet_chi_tiet.md` | Xong đặc tả: công thức, dẫn xuất, ví dụ số từ hệ thống (KV cache 32 KiB/token, LoRA đếm tay 43.278.336, loss mặt nạ 85/3.007, MTP 2,28), chỗ tính trong mã, 12 câu hỏi phản biện |
| Bìa | trong Word của sinh viên | Xong |
| Lời cảm ơn | `01_loi_cam_on.md` | Xong, còn điền học vị giảng viên và ngày ký |
| Lời cam đoan | `02_loi_cam_doan.md` | Xong, còn điền học vị giảng viên và ngày ký |
| Mở đầu | `03_mo_dau.md` | Xong bản 15/11; **cần sửa 6 chỗ** (phạm vi, mục tiêu, bộ RQ, phương pháp, đóng góp, lời cam đoan) theo `00_khung_suon.md` |
| Sơ đồ dữ liệu, RAG, ngữ cảnh | `04_so_do_du_lieu_rag_ngu_canh.md` | Xong S1–S6, tài liệu tham chiếu cho Chương 2, 3 |
| Thiết kế bộ đánh giá 250 ca | `05_thiet_ke_bo_danh_gia.md` | Xong; 250 ca trong `evals/suites`, đóng băng 2026-11-14 (W6.3-D7) |
| Thực trạng và bộ dữ liệu công khai | `06_nghien_cuu_thuc_trang_va_du_lieu.md` | Xong; dùng cho mục 1.1 và nguồn gốc bộ test |
| Bộ tài liệu cho model độc lập sinh 210 ca | `eval_pack/` | Xong; 210 ca đã sinh, cùng 40 ca chuyển thể gộp thành 250 ca |
| Cơ sở dữ liệu: hiện trạng v8 và thiết kế v9 | `07_co_so_du_lieu.md` | Xong hiện trạng; thiết kế v9 chờ owner duyệt |
| Chương 1 | | **Việc tiếp theo** |
| Chương 2, 3, mục 4.1 | | Viết được ngay |
| Mục 4.1 mốc, 4.3 an toàn, 4.4 phân loại lỗi, 4.6 vận hành (phần đã đo), 4.7 | | **Có số liệu W6.4, viết được** (`docs/phase_role_aware_ops/W6_4_measurement/`) |
| Mục 4.2 truy hồi | | Cần thí nghiệm E1 (CPU, rẻ) |
| Mục 4.5 chưng cất và ablation, Kết luận | | Chờ W6.7 (đo lại 250 × 3 trước ~1/12) |
| RQ supervisor, suy luận/ngữ cảnh; ablation rào an toàn và nén (E6) | | Hoãn; chạy B, C, D và E6 sau W6.7 nếu còn đơn vị |
| Mục lục, danh mục bảng, hình | | Word tự tạo ở bước cuối |
| Danh mục viết tắt | | Gom cuối; đã có CSKH, LLM, RAG, RQ, CDIO, GPU |

## Quy tắc văn phong

- Không dùng ngoặc đơn để chú giải thuật ngữ; mỗi thuật ngữ chọn hẳn tiếng Việt hoặc tiếng Anh.
- Viết tắt giới thiệu bằng câu, ví dụ "mô hình ngôn ngữ lớn, gọi tắt là LLM,".
- Giữ trích dẫn trong ngoặc vuông, ví dụ ReAct [Yao 2023]; ghi tạm tác giả và năm, đổi sang số khi chốt tài liệu tham khảo.
- Hạn chế gạch đầu dòng và danh sách đánh số; ưu tiên đoạn văn liền mạch.
- Định dạng Word: tiêu đề in đậm căn giữa cỡ 14; thân Times New Roman 13, căn đều, giãn dòng 1.5, trừ khi khoa có mẫu khác. Dùng Heading 1/2/3 cho chương mục và Insert Caption cho hình, bảng.

## Khi tiếp tục

Trong lúc chờ W6.7: chạy E1–E3 (rẻ, không cần GPU), sửa Mở đầu theo 6 điểm, viết Chương 1 theo `09_co_so_ly_thuyet_chi_tiet.md`, viết 4.1, 4.3, 4.4. Các file ở đây là bản nháp markdown để dán vào Word; sinh viên giữ bản Word chính.
