# Khóa luận tốt nghiệp — tiến độ

Cập nhật: 2026-11-15. Model đổi sang Qwen3.5-9B theo §31 W6.4-D1; các phần đã viết cập nhật theo W6.4-D11.

## Thông tin chung

- Trường: Đại học Duy Tân · Trường Khoa học Máy tính và Thông tin · Khoa Khoa học Máy tính
- Ngành Khoa học máy tính, chuyên ngành Trí tuệ nhân tạo; lớp môn học CS449A
- Đề tài: **XÂY DỰNG HỆ THỐNG TRỢ LÝ ẢO TÍCH HỢP AI HỖ TRỢ CHĂM SÓC KHÁCH HÀNG CHO KINH DOANH BÁN LẺ**
- Giảng viên hướng dẫn: Phạm Văn Dược · Sinh viên: Lương Anh Tú · Đà Nẵng, 11/2026
- Khóa luận cá nhân, cấu trúc CDIO 4 chương, không dùng Scrum, khoảng 50–60 trang Word
- Model đánh giá: `Qwen/Qwen3.5-9B` bản chính hãng, Apache 2.0, kèm MTP, phục vụ bằng vLLM trên L4 24 GB (W6.4-D1). Bản demo trên production dùng DeepSeek-V4.1-Flash qua API (W6.4-D5). Không có chương tự fine-tune, trừ khi làm kịp phần tùy chọn W6.7 (LoRA chưng cất từ DeepSeek, W6.4-D12). Thiết kế ban đầu dùng Gemma 4 12B bản bên thứ ba, chỉ nhắc ở mục 2.2.

## Tiến độ

| Phần | File | Trạng thái |
|---|---|---|
| Khung sườn | `00_khung_suon.md` | Xong |
| Bìa | trong Word của sinh viên | Xong |
| Lời cảm ơn | `01_loi_cam_on.md` | Xong, còn điền học vị giảng viên và ngày ký |
| Lời cam đoan | `02_loi_cam_doan.md` | Xong, còn điền học vị giảng viên và ngày ký |
| Mở đầu | `03_mo_dau.md` | Xong, bản đoạn văn |
| Sơ đồ dữ liệu, RAG, ngữ cảnh | `04_so_do_du_lieu_rag_ngu_canh.md` | Xong S1–S6, tài liệu tham chiếu cho Chương 2, 3 |
| Thiết kế bộ đánh giá 250 ca | `05_thiet_ke_bo_danh_gia.md` | Xong; 250 ca trong `evals/suites`, đóng băng 2026-11-14 (W6.3-D7) |
| Thực trạng và bộ dữ liệu công khai | `06_nghien_cuu_thuc_trang_va_du_lieu.md` | Xong; dùng cho mục 1.1 và nguồn gốc bộ test |
| Bộ tài liệu cho model độc lập sinh 210 ca | `eval_pack/` | Xong; 210 ca đã sinh, cùng 40 ca chuyển thể gộp thành 250 ca |
| Cơ sở dữ liệu: hiện trạng v8 và thiết kế v9 | `07_co_so_du_lieu.md` | Xong hiện trạng; thiết kế v9 chờ owner duyệt |
| Chương 1 | | **Việc tiếp theo** |
| Chương 2, 3, mục 4.1 | | Viết được ngay |
| Mục 4.2–4.9, Kết luận | | Chờ lượt đo W6.4: Qwen3.5-9B trên L4, `notebooks/colab_eval_w64.py` |
| Mục lục, danh mục bảng, hình | | Word tự tạo ở bước cuối |
| Danh mục viết tắt | | Gom cuối; đã có CSKH, LLM, RAG, RQ, CDIO, GPU |

## Quy tắc văn phong

- Không dùng ngoặc đơn để chú giải thuật ngữ; mỗi thuật ngữ chọn hẳn tiếng Việt hoặc tiếng Anh.
- Viết tắt giới thiệu bằng câu, ví dụ "mô hình ngôn ngữ lớn, gọi tắt là LLM,".
- Giữ trích dẫn trong ngoặc vuông, ví dụ ReAct [Yao 2023]; ghi tạm tác giả và năm, đổi sang số khi chốt tài liệu tham khảo.
- Hạn chế gạch đầu dòng và danh sách đánh số; ưu tiên đoạn văn liền mạch.
- Định dạng Word: tiêu đề in đậm căn giữa cỡ 14; thân Times New Roman 13, căn đều, giãn dòng 1.5, trừ khi khoa có mẫu khác. Dùng Heading 1/2/3 cho chương mục và Insert Caption cho hình, bảng.

## Khi tiếp tục

Viết Chương 1, bắt đầu từ mục 1.1 rồi 1.2 phát biểu bài toán hình thức. Các file ở đây là bản nháp markdown để dán vào Word; sinh viên giữ bản Word chính.
