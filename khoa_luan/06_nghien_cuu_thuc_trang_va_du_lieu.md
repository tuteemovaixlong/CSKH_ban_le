# Thực trạng CSKH thương mại điện tử Việt Nam và bộ dữ liệu công khai

Tra cứu ngày 2026-11-06. Dùng cho mục 1.1 của khóa luận và để xây bộ đánh giá trong `05_thiet_ke_bo_danh_gia.md`. Số liệu báo chí nên đối chiếu lại với báo cáo gốc trước khi đưa vào khóa luận.

## 1. Thực trạng

**Thương mại điện tử là lĩnh vực bị khiếu nại nhiều nhất.** Năm 2025, Ủy ban Cạnh tranh Quốc gia thuộc Bộ Công Thương nhận 896 đơn thư liên quan đến bảo vệ quyền lợi người tiêu dùng. Thương mại điện tử chiếm 191 vụ, tức 21,3%, đứng đầu mọi nhóm. Hành vi vi phạm phổ biến nhất là doanh nghiệp không thương lượng với người tiêu dùng, chiếm 26,9%. Trong thương mại điện tử, các rủi ro nổi bật là sản phẩm không đúng mô tả, gian lận thương hiệu và bảo mật dữ liệu cá nhân [Dân trí 2026; Thanh tra 2026].

**Bốn nhóm nội dung khiếu nại**, theo số liệu 9 tháng năm 2025, là chất lượng hàng hóa và hậu mãi kém; thông tin không minh bạch và gian lận; rủi ro thanh toán và bảo mật dữ liệu; giao hàng và logistics. Ba vấn đề gây bức xúc nhất là hoàn tiền chậm, khóa tài khoản và giao sai hàng [Doanh nghiệp Hội nhập; Báo Tin tức].

**Đổi trả là yếu tố tạo niềm tin.** Theo khảo sát của Shopee năm 2023, 6 trên 10 người tiêu dùng yên tâm hơn khi có chính sách trả hàng hoàn tiền. Theo Chỉ số thương mại điện tử 2023, rào cản lớn khi mua online là không tin người bán, chiếm 41%, và khó kiểm định chất lượng, chiếm 33% [VnEconomy]. Khảo sát 6.000 người ở Đông Nam Á cho thấy chỉ 12% người Việt chấp nhận bảo đảm đổi trả thấp hơn để đổi lấy giá rẻ hơn [Thanh Niên]. Khi đổi trả hoặc hoàn tiền, khách thường phải chờ nhiều ngày, có khi nhiều tháng [Quản lý Nhà nước 2023]. Chưa tìm được khảo sát công khai nào đưa tỉ lệ cụ thể cho từng lý do trả hàng như sai size, hàng lỗi hay không đúng mô tả.

**Khung pháp lý.** Luật Bảo vệ quyền lợi người tiêu dùng số 19/2023/QH15 có hiệu lực từ 01/7/2024 và lần đầu quy định giao dịch từ xa. Điều 37 buộc người bán công khai điều kiện, phương thức và quy trình đổi trả. Người tiêu dùng được đổi, trả khi hàng không đúng cam kết hoặc bị lỗi. Chính sách riêng của shop không được tước quyền tối thiểu đó [dms.gov.vn; thuvienphapluat.vn]. Một nguồn nhắc tới Luật Thương mại điện tử số 122/2025/QH15 cần đọc kèm; chưa kiểm văn bản gốc.

**Hệ quả cho thiết kế hệ thống và bộ test.** Bốn nhóm khiếu nại ứng với các bộ test S01 giao hàng, S05 hoàn tiền, S06 đổi hàng không đúng mô tả, S09 bảo mật dữ liệu. Yêu cầu công khai quy trình đổi trả của Điều 37 là cơ sở pháp lý cho việc trợ lý phải trích dẫn chính sách ở S03. Việc doanh nghiệp không thương lượng là vi phạm hàng đầu, nên luồng chuyển nhân viên ở S07 và Trợ lý ca ở S11 có ý nghĩa thực tế.

## 2. Bộ dữ liệu công khai đã xem

| Bộ dữ liệu | Ngôn ngữ | Nội dung | License | Dùng được gì |
|---|---|---|---|---|
| τ-bench và τ²-bench, miền retail [Yao 2024; Barres 2025] | Anh, cùng 5 ngôn ngữ khác, không có tiếng Việt | tác tử gọi tool với DB đơn hàng; hủy, sửa đơn chờ xử lý, trả, đổi đơn đã giao; chấm theo trạng thái DB cuối | MIT | **Cấu trúc nhiệm vụ và cách chấm**; dịch, chuyển thể một nhóm nhiệm vụ sang dữ liệu của RetailOps |
| Bitext Retail eCommerce | Anh | 46 ý định trong 13 nhóm, mỗi ý định khoảng 1.000 câu, tổng hợp | CDLA-Sharing 1.0, phải ghi nguồn, sản phẩm phái sinh dùng cùng điều khoản | **Danh mục ý định làm bảng phủ**; không chép câu |
| CSConDa, ura-hcmut | Việt | 9.849 cặp hỏi đáp thật từ CSKH của một công ty phần mềm; có teencode, viết tắt, lỗi gõ, chêm tiếng Anh | CC BY-NC 4.0, phải đăng ký, chỉ nghiên cứu | **Tham khảo cách khách Việt viết**; không chép vào repo |
| UIT-ViOCD | Việt | 5.485 đánh giá có nhãn khiếu nại hay không, nhiều ngành hàng | chỉ cho nghiên cứu | tham khảo cách diễn đạt khiếu nại |
| UIT-ViSFD | Việt | 11.122 bình luận điện thoại trên sàn, nhãn khía cạnh và cảm xúc | chỉ cho nghiên cứu | tham khảo |
| 5CD-AI Vietnamese E-commerce Multi-turn Chat | Việt | 1.482 hội thoại tư vấn sản phẩm, có vẻ là dữ liệu tổng hợp | Apache 2.0 | ít giá trị: kiến thức sản phẩm chung, không khớp catalog |
| AgentDojo [Debenedetti 2024] | Anh | 97 nhiệm vụ, 629 ca tấn công chèn lệnh; chấm theo trạng thái môi trường | MIT | **Mẫu tấn công chèn lệnh gián tiếp** cho S09 |
| InjecAgent | Anh | 1.054 ca chèn lệnh một bước | chưa kiểm license | tham khảo |

**Vì sao không lắp thẳng được:**
- **Ngôn ngữ:** bộ có cấu trúc đúng thì là tiếng Anh; bộ tiếng Việt thì không có tool, không có DB và không có kết quả mong đợi.
- **Hành vi khác nhau:** τ-bench cho tác tử tự sửa và hủy đơn sau khi khách đồng ý. RetailOps cố ý không cho AI ghi dữ liệu; AI chỉ mở form, khách tự xác nhận. Kết quả mong đợi vì vậy phải viết lại.
- **Dữ liệu nền khác nhau:** các bộ ngoài dựa trên DB của chúng, không khớp mã đơn, sản phẩm và biến thể của RetailOps.
- **License:** CSConDa, ViOCD và ViSFD chỉ cho nghiên cứu. Chép vào repo là phân phối lại, nên không làm.

## 3. Đề xuất: dữ liệu mô phỏng có căn cứ, kèm phần chuyển thể từ bộ công khai

Mỗi ca ghi trường `origin` để khóa luận báo cáo được nguồn gốc. Có ba loại:

| `origin` | Số ca | Cách làm |
|---|---|---|
| `mo_phong` | khoảng 110 | Viết mới trên dữ liệu seed và fixture của RetailOps. Tình huống bám theo thực trạng ở mục 1, các tài liệu trong `data/knowledge/` và danh mục ý định của Bitext. Cách viết mô phỏng các hiện tượng ngôn ngữ mà CSConDa mô tả: teencode, viết tắt, lỗi gõ, chêm tiếng Anh, không dấu. |
| `tau2_retail` | khoảng 28 | Chuyển thể nhiệm vụ retail của τ²-bench: dịch sang tiếng Việt, đổi sang mã đơn của RetailOps, viết lại kết quả mong đợi theo nguyên tắc AI không ghi dữ liệu. Ghi mã nhiệm vụ gốc và license MIT. Nhóm này cho phép so sánh với một benchmark quốc tế. |
| `agentdojo` | khoảng 12 | Chuyển thể mẫu tấn công chèn lệnh gián tiếp: lệnh giấu trong mô tả sản phẩm, đoạn chính sách, tệp đính kèm hoặc ghi chú chuyển ca, vào bộ S09 và S11. |

Bảng phủ ý định theo Bitext. Mỗi ý định trong phạm vi có ít nhất một ca. Ý định ngoài phạm vi kiểm việc từ chối đúng hoặc chuyển nhân viên.

| Nhóm Bitext | Ý định | Bộ test |
|---|---|---|
| ORDER | track_order, cancel_order, change_order, request_invoice | S01, S04, S06; xuất hóa đơn thuộc S10 |
| DELIVERY | track_delivery, delivery_issue, delivery_time, shipping_costs, missing_item, wrong_item, damaged_delivery | S01, S03, S05, S06 |
| RETURNS | return_policy, refund_policy, return_product, request_refund, refund_status | S03, S05 |
| PRODUCT | product_information, availability, exchange_product, product_issue | S02, S06 |
| PAYMENT | payment_methods, payment_issue, pay | S03; thanh toán trong chat thuộc S10 |
| SALES, STORE | sales_period, store_location, store_opening_hours | S03 |
| CONTACT | human_agent, customer_service | S07 |
| ACCOUNT, APP, CART, FEEDBACK | order_history; còn lại như đổi mật khẩu, khóa tài khoản, giỏ hàng | S01; còn lại S10, riêng đòi đặt lại mật khẩu hay xem dữ liệu người khác thuộc S09 |
| USER | request_right_to_rectification | S09, chuyển nhân viên |

Điều chỉnh số ca theo thực trạng: S05 hoàn tiền tăng từ 12 lên 14, vì hoàn tiền chậm là bức xúc số một; S02 sản phẩm giảm từ 14 xuống 12. Tổng vẫn 150.

**Lưu ý phương pháp cần ghi trong khóa luận.** Bộ dữ liệu được xây với sự hỗ trợ của AI và do tác giả rà soát. Để giảm thiên lệch: 30% số ca để riêng làm `held_out`, không xem khi chỉnh prompt; các bộ cũ W3.2 và W4 đã dùng trong lúc phát triển nên chỉ làm bộ hồi quy, không tính vào 150 ca.

## Nguồn

- [Dân trí: Thương mại điện tử dẫn đầu khiếu nại của người tiêu dùng năm 2025](https://dantri.com.vn/kinh-doanh/thuong-mai-dien-tu-dan-dau-khieu-nai-cua-nguoi-tieu-dung-nam-2025-20260706151252129.htm)
- [Thanh tra: Khiếu nại tiêu dùng năm 2025, xu hướng số hóa và thách thức hậu mãi](https://thanhtra.com.vn/tieu-dung-AA9F50895/khieu-nai-tieu-dung-nam-2025-xu-huong-so-hoa-va-thach-thuc-hau-mai-fd59fe7ae.html)
- [Doanh nghiệp Hội nhập: khiếu nại thương mại điện tử chủ yếu ở khâu hoàn tiền và giao hàng](https://doanhnghiephoinhap.vn/uy-ban-canh-tranh-quoc-gia-khieu-nai-ve-thuong-mai-dien-tu-tang-chu-yeu-o-khau-hoan-tien-va-giao-hang-119088.html)
- [Báo Tin tức: Thương mại điện tử và bài toán giữ niềm tin người tiêu dùng](https://baotintuc.vn/thuong-mai-dien-tu-tri-gia-hang-chuc-ty-usd-va-bai-toan-giu-niem-tin-nguoi-tieu-dung-post1400066.html)
- [Thương hiệu và Công luận: khiếu nại thương mại điện tử chiếm 21,7%](https://thuonghieucongluan.com.vn/so-don-khieu-nai-trong-linh-vuc-thuong-mai-dien-tu-chiem-21-7-a282292.html)
- [VnEconomy: Thế khó của người dùng online khi trả hàng hoàn tiền](https://vneconomy.vn/the-kho-cua-nguoi-dung-online-khi-tra-hang-hoan-tien.htm)
- [Thanh Niên: Người mua hàng online không còn chạy theo giá rẻ](https://thanhnien.vn/nguoi-mua-hang-online-khong-con-chay-theo-gia-re-185261006162916796.htm)
- [Quản lý Nhà nước 2023: Giải pháp quản trị người tiêu dùng mua hàng trực tuyến](https://www.quanlynhanuoc.vn/2023/07/11/giai-phap-quan-tri-nguoi-tieu-dung-tham-gia-mua-hang-truc-tuyen-tai-viet-nam/)
- [Cục Quản lý và Phát triển thị trường trong nước: Bảo vệ quyền lợi người tiêu dùng trong thương mại điện tử theo Luật 2023](https://dms.gov.vn/tin-chi-tiet/-/chi-tiet/bao-ve-quyen-loi-nguoi-tieu-dung-trong-hoat-%C4%91ong-thuong-mai-%C4%91ien-tu-theo-luat-bao-ve-quyen-loi-nguoi-tieu-dung-nam-2023-87436-4.html)
- [Thư viện pháp luật: quy trình đổi trả trong giao dịch từ xa từ 1/7/2024](https://thuvienphapluat.vn/hoi-dap-phap-luat/tu-172024-quy-trinh-doi-tra-san-pham-hang-hoa-dich-vu-trong-giao-dich-tu-xa-phai-co-cac-thong-tin-g-138025937.html)
- [Luật Bảo vệ quyền lợi người tiêu dùng 2023, Chương III](https://vi.wikisource.org/wiki/Lu%E1%BA%ADt_B%E1%BA%A3o_v%E1%BB%87_quy%E1%BB%81n_l%E1%BB%A3i_ng%C6%B0%E1%BB%9Di_ti%C3%AAu_d%C3%B9ng_n%C6%B0%E1%BB%9Bc_C%E1%BB%99ng_h%C3%B2a_x%C3%A3_h%E1%BB%99i_ch%E1%BB%A7_ngh%C4%A9a_Vi%E1%BB%87t_Nam_2023/Ch%C6%B0%C6%A1ng_III)
- [sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench) và [sierra-research/tau-bench](https://github.com/sierra-research/tau-bench); bài báo [τ-bench, arXiv 2406.12045](https://arxiv.org/pdf/2406.12045)
- [Bitext Retail eCommerce dataset](https://huggingface.co/datasets/bitext/Bitext-retail-ecommerce-llm-chatbot-training-dataset)
- [CSConDa, ura-hcmut/Vietnamese-Customer-Support-QA](https://huggingface.co/datasets/ura-hcmut/Vietnamese-Customer-Support-QA); bài báo [arXiv 2507.22542](https://arxiv.org/pdf/2507.22542)
- [UIT-ViOCD](https://huggingface.co/datasets/tarudesu/ViOCD); bài báo [arXiv 2104.11969](https://arxiv.org/abs/2104.11969)
- [UIT-ViSFD](https://github.com/LuongPhan/UIT-ViSFD)
- [5CD-AI Vietnamese E-commerce Multi-turn Chat](https://huggingface.co/datasets/5CD-AI/Vietnamese-Ecommerce-Multi-turn-Chat)
- [AgentDojo](https://github.com/ethz-spylab/agentdojo); [bài giới thiệu của Invariant Labs](https://invariantlabs.ai/blog/agentdojo)
