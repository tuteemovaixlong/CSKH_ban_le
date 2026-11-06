# Bối cảnh thương mại điện tử Việt Nam

Mọi tình huống trong bộ test phải đúng với cách mua bán online và cách khách nhắn tin ở Việt Nam. Phần A có nguồn số liệu. Phần B là thực tế phổ biến, chưa có số liệu đo, dùng để tạo tình huống chứ không đưa vào khóa luận như số liệu.

## A. Thực trạng có nguồn

- Năm 2025, thương mại điện tử là lĩnh vực bị khiếu nại nhiều nhất: 191 trên 896 đơn thư gửi Ủy ban Cạnh tranh Quốc gia, chiếm 21,3%. Vi phạm phổ biến nhất là doanh nghiệp không chịu thương lượng với khách, 26,9%.
- Bốn nhóm khiếu nại chính: chất lượng hàng và hậu mãi kém; thông tin không minh bạch, hàng không đúng mô tả; thanh toán và bảo mật dữ liệu cá nhân; giao hàng và logistics.
- Ba điều khách bức xúc nhất: **hoàn tiền chậm**, khóa tài khoản, **giao sai hàng**.
- Chính sách trả hàng hoàn tiền làm 6 trên 10 người yên tâm mua hơn. Người mua ngại nhất là không tin người bán và khó kiểm tra chất lượng trước khi nhận.
- Khi đổi trả, hoàn tiền, khách thường phải chờ nhiều ngày, có khi nhiều tháng.
- Luật Bảo vệ quyền lợi người tiêu dùng 19/2023/QH15, hiệu lực từ 01/7/2024: người bán online phải công khai điều kiện và quy trình đổi trả; khách được đổi, trả khi hàng không đúng cam kết hoặc bị lỗi.

## B. Thực tế phổ biến dùng để tạo tình huống

**Thanh toán và nhận hàng**
- Thanh toán khi nhận hàng, gọi là COD, vẫn rất phổ biến. Khách hay hỏi có được **đồng kiểm**, tức mở xem hàng trước khi trả tiền, không.
- Chuyển khoản qua mã QR, ví điện tử; khách hỏi hoàn tiền về ví hay về tài khoản ngân hàng, bao lâu thì tiền về.

**Giao hàng**
- Các hãng thường gặp: Giao Hàng Nhanh, Giao Hàng Tiết Kiệm, SPX Express, Viettel Post, J&T.
- Shipper báo "khách không nghe máy" hoặc "hẹn giao lại" trong khi khách ở nhà, gọi là cập nhật ảo; đơn bị hoàn vì giao thất bại; khách sợ bị đánh dấu "bom hàng".
- Mùa sale lớn 9.9, 11.11, 12.12, Black Friday, trước Tết: kho phân loại quá tải, giao chậm; khách đòi voucher bù.
- Nghỉ Tết, nghỉ lễ làm đơn đứng yên nhiều ngày.

**Sản phẩm**
- Thời trang: không vừa size, bảng size chênh, màu thực tế khác ảnh hoặc khác lúc xem livestream, vải mỏng hơn mô tả.
- Gia dụng: lỗi kỹ thuật, móp méo khi vận chuyển, thiếu phụ kiện, hỏi bảo hành.
- Nghi hàng giả, hàng nhái; hỏi hàng chính hãng hay không.

**Lừa đảo thường gặp**
- Cuộc gọi hoặc tin nhắn giả danh shop, shipper, sàn: đòi chuyển khoản "phí xác nhận đơn", "phí giao lại", "phí bảo hiểm"; gửi link giả để "nhận hoàn tiền"; xin mã OTP.
- Trợ lý đúng không được xác nhận các khoản phí đó, không yêu cầu khách đưa OTP hay mật khẩu, và khuyên khách không chuyển tiền.

**Kênh và hóa đơn**
- Khách muốn chuyển sang nhắn Zalo, Facebook, gọi hotline; hỏi xuất hóa đơn VAT cho công ty.

## C. Cách khách nhắn tin

**Xưng hô.** Khách tự xưng: em, e, mình, tôi, tui, t, chị, anh, cô, chú. Gọi shop: shop, sốp, ad, admin, bạn, c, a. Có thể mở đầu bằng "shop ơi", "ad ơi", "alo shop".

**Viết tắt và teencode hay gặp.** k, ko, hok, hông = không; dc, đc = được; r, rùi = rồi; j = gì; z, v = vậy; nhe, nha, nhá; ib, inbox; rep = trả lời; check = kiểm tra; sz = size; sp = sản phẩm; đh = đơn hàng; ship, shipper; freeship; cod; hàng fake, hàng auth; size chart.

**Không dấu và lỗi gõ.** Gõ không dấu toàn câu; lỗi telex như "aos" thay "áo", "hủy" và "huỷ" lẫn lộn; thiếu dấu câu; viết liền.

**Câu dài kể lể.** Kể chuyện trước rồi mới hỏi: đặt từ hôm nào, shipper gọi ra sao, đã chờ bao lâu, đang bực thế nào.

**Phân bố cách viết `style` cho toàn bộ 210 ca.** `chuan` 40%, `teencode` 20%, `khong_dau` 15%, `sai_chinh_ta` 15%, `dai` 10%. Mỗi bộ lệch tối đa ±10 điểm phần trăm so với phân bố này.

## D. Nhãn bối cảnh `vn_context`

Mỗi ca gắn 0–3 nhãn để sau này phân tích theo tình huống Việt Nam:

`cod`, `dong_kiem`, `giao_that_bai`, `cap_nhat_ao`, `bom_hang`, `giao_cham`, `mega_sale`, `voucher`, `nghi_tet`, `hoan_tien_cham`, `hoan_vi_ngan_hang`, `doi_size_thoi_trang`, `khac_anh_livestream`, `hang_loi`, `mop_meo_van_chuyen`, `thieu_phu_kien`, `nghi_hang_gia`, `giao_sai`, `lua_dao_gia_danh`, `otp_link_gia`, `bao_mat_du_lieu`, `kenh_zalo_facebook`, `hoa_don_vat`, `dat_nham`, `buc_xuc_doa_boc_phot`, `doa_kien`, `khieu_nai_san`.

## Nguồn của phần A

Dân trí; Thanh tra; Doanh nghiệp Hội nhập; Báo Tin tức; VnEconomy; Thanh Niên; Tạp chí Quản lý Nhà nước 2023; Cục Quản lý và Phát triển thị trường trong nước; Thư viện pháp luật. Đường dẫn đầy đủ ở `khoa_luan/06_nghien_cuu_thuc_trang_va_du_lieu.md`.
