# BỘ TÌNH HUỐNG KIỂM THỬ NGHIỆP VỤ CSKH THƯƠNG MẠI ĐIỆN TỬ (RETAILOPS BUSINESS TEST SCENARIOS 2026)

> **Tài liệu chuẩn hóa**: Bộ kịch bản kiểm thử nghiệp vụ toàn diện cho hệ thống AI Đa Tác Tử Chăm Sóc Khách Hàng Bán Lẻ & Thương Mại Điện Tử (Shopee, TikTok Shop, D2C).  
> **Phiên bản**: 2.5 — Chuẩn hóa 6 SOPs Vận hành Thực chiến, Tra cứu RAG, Đổi Size 2 Chiều, Xử lý Bưu tá ảo và Phân quyền RBAC.  
> **Đối tượng áp dụng**: Kiểm thử thủ công trên Giao diện Web EC2, Kiểm thử tự động E2E (`live-e2e.py`) và Đối chứng Benchmark Luận văn tốt nghiệp.

---

## PHẦN 1: MA TRẬN PHÂN LOẠI NGHIỆP VỤ (BUSINESS COVERAGE MATRIX)

| Nhóm Nghiệp Vụ | Mã SOP | Tên Nghiệp Vụ / Kịch Bản | Phân Luồng Agent | Tools Thực Thi | Tỷ Lệ Giải Quyết Tự Động |
| :--- | :---: | :--- | :--- | :--- | :---: |
| **Logistics & Vận chuyển** | **SOP 1** | Bưu tá ảo SPX/GHN không giao, báo "không liên lạc được" | `dispute_agent` / `order_agent` | `track_shipment` | **100% (AI)** |
| **Bảo hành & Lỗi sản phẩm** | **SOP 2** | Hàng lỗi, rách chỉ, kẹt khóa kéo, nhận ảnh unboxing | `dispute_agent` | `get_order`, `track_shipment`, `action_proposal: exchange_1to1` | **85% (AI + 1-Click Duyệt)** |
| **Đổi Size / Đổi Mẫu** | **SOP 3** | Khách mặc không vừa, muốn đổi size/màu tận nhà | `dispute_agent` | `check_inventory`, `action_proposal: size_exchange` | **90% (AI + 1-Click Duyệt)** |
| **Hủy Đơn Hàng** | **SOP 4** | Khách muốn hủy đơn hàng trước khi xuất kho | `order_agent` | `prepare_cancellation` | **100% (Xác nhận 2 bước)** |
| **Sự Cố Kẹt Kho Vận** | **SOP 5** | Đơn hàng kẹt kho trung chuyển Mega SOC > 48h | `order_agent` | `track_shipment` (Voucher 50K đền bù) | **100% (AI)** |
| **Khủng Hoảng & Bóc Phốt** | **SOP 6** | Khách giận dữ cực độ, dọa bóc phốt / Gặp nhân viên | `dispute_agent` | `request_human_support` (Priority VIP) | **Chuyển Người Thật (Handoff)** |
| **Chính Sách & Tri Thức** | **RAG-01** | Tra cứu chính sách bảo hành, đổi trả, freeship, hoàn tiền | `policy_agent` | `search_knowledge` | **100% (RAG Trích dẫn)** |
| **Tư Vấn Sản Phẩm** | **PROD-01** | Tư vấn chọn size, chất liệu, tìm kiếm danh mục | `policy_agent` / `order_agent` | `search_products`, `get_product` | **100% (AI)** |
| **Giao Tiếp Tổng Quát** | **GEN-01** | Chào hỏi, cảm ơn, hỏi thăm ngoài lề, trò chuyện đời sống | `witty_agent` | Không cần tool | **100% (AI)** |
| **Bảo Mật & Phân Quyền** | **RBAC-01** | Chặn đọc trộm đơn khác tài khoản, phân quyền Staff/Manager | `backend_guard` | Session Cookie, Role Enforcement | **100% (Chặn HTTP 403)** |

---

## PHẦN 2: CHI TIẾT CÁC TÌNH HUỐNG KIỂM THỬ THỰC CHIẾN

---

### NHÓM 1: LOGISTICS & BƯU TÁ ẢO (SOP 1 & SOP 5)

#### 📋 Kịch bản TC-LOG-01: Bưu tá SPX báo "không liên lạc được" dù khách ở nhà cả ngày (SOP 1)
* **Bối cảnh thực tế**: Đơn vị vận chuyển (SPX Express) đến cuối ca chưa kịp giao, tài xế bấm cập nhật ảo "Khách không nghe máy / Không liên lạc được" để tránh bị phạt KPI giao trễ. Khách hàng bức xúc phản ánh.
* **Tài khoản test**: Khách hàng `C-003` (Trần Thị Mai) — Mã đơn: `O-301`.
* **Câu nói của khách (Input Prompt)**:
  > *"Tại sao đơn O-301 của tôi shipper SPX báo không liên lạc được trong khi tôi ở nhà cả ngày cầm điện thoại? Shop kiểm tra lại ngay!"*
* **Phân luồng mong đợi (Router)**: `dispute_agent` hoặc `order_agent`.
* **Tool thực thi**: `track_shipment(order_id="O-301")`.
* **Dữ liệu hệ thống phản hồi**:
  * Trạng thái vận đơn: `delivery_failed_virtual` ("Bưu tá báo không liên lạc được (Ảo)").
  * Bưu tá phụ trách: Nguyễn Văn Tuấn (SĐT: 0934.112.233).
  * Vị trí: Bưu cục Cầu Giấy 2, Hà Nội.
  * Ghi chú hệ thống: Bưu cục xác nhận không có lịch sử cuộc gọi đi vào thời điểm bấm trạng thái.
* **Kết quả kỳ vọng (Expected Output)**:
  * AI giữ thái độ đồng cảm, xin lỗi về trải nghiệm bực mình của khách.
  * Cung cấp rõ ràng thông tin bưu tá: **Nguyễn Văn Tuấn (0934.112.233)**.
  * Thông báo: Hệ thống đã tự động ghi nhận khiếu nại bưu cục Cầu Giấy 2, yêu cầu bưu tá điều phối giao lại ngay trong ngày (trước 18:00).
* **Tiêu chí Pass**: Có thông tin bưu tá Nguyễn Văn Tuấn + SĐT, không đổ lỗi cho khách, cam kết giao lại trong ngày.

---

#### 📋 Kịch bản TC-LOG-02: Đơn hàng kẹt kho Mega SOC Bắc Ninh > 48h đợt Mega Sale (SOP 5)
* **Bối cảnh thực tế**: Đợt Sale ngày đôi (9.9 / 11.11), lượng hàng ùn ứ tại Tổng kho trung chuyển lớn (Bắc Ninh Mega SOC) hơn 2 ngày không di chuyển.
* **Tài khoản test**: Khách hàng `C-004` (Lê Hoàng Nam) — Mã đơn: `O-304`.
* **Câu nói của khách (Input Prompt)**:
  > *"Đơn O-304 của tôi đặt 3 ngày rồi sao tra cứu vẫn thấy nằm yên ở kho Bắc Ninh vậy shop? Có giao được trước cuối tuần không?"*
* **Phân luồng mong đợi (Router)**: `order_agent`.
* **Tool thực thi**: `track_shipment(order_id="O-304")`.
* **Dữ liệu hệ thống phản hồi**:
  * Trạng thái: `sorting_delayed` (Nghẽn trạm phân loại Mega Sale > 48h).
  * Thời gian trễ: 54 giờ.
  * Địa điểm: Kho Tổng BN Mega SOC (Bắc Ninh).
  * Mã voucher đền bù tự động: `SALE50K-BN-SOC`.
* **Kết quả kỳ vọng (Expected Output)**:
  * Giải thích minh bạch lý do chậm trễ: Do khối lượng hàng hóa đợt Sale quá tải cục bộ tại Tổng kho Bắc Ninh.
  * Cung cấp thời gian dự kiến giao: Ngày 20/09/2026.
  * **Tự động gửi tặng mã giảm giá đền bù**: `SALE50K-BN-SOC` (Giảm 50.000đ cho đơn tiếp theo) để xoa dịu khách hàng.
* **Tiêu chí Pass**: Nêu đúng địa điểm Kho BN Mega SOC, thông báo mã giảm giá đền bù 50K.

---

### NHÓM 2: BẢO HÀNH & HÀNG LỖI DO VẬN CHUYỂN (SOP 2)

#### 📋 Kịch bản TC-WAR-01: Áo sơ mi bị rách chỉ / lỗi khóa kéo, gửi kèm ảnh Unboxing (SOP 2)
* **Bối cảnh thực tế**: Khách nhận hàng khui hộp, phát hiện áo bị sứt chỉ đường nách hoặc kẹt khóa kéo. Khách tải ảnh bằng chứng lên khung chat.
* **Tài khoản test**: Khách hàng `C-003` — Mã đơn: `O-302` (Đã giao thành công 5 ngày trước, sản phẩm `P-104`).
* **Câu nói của khách (Input Prompt)**:
  > *"Shop ơi đơn O-302 tôi vừa khui hàng thì thấy áo bị bung đường chỉ ở nách áo, tôi có gửi ảnh chụp kèm đây này, shop giải quyết đổi cái khác giúp tôi với!"*  
  > *(Đính kèm tệp ảnh: `anh_ao_rach_chi.jpg`)*
* **Phân luồng mong đợi (Router)**: `dispute_agent`.
* **Tool thực thi**: `track_shipment(order_id="O-302")` hoặc `get_order(order_id="O-302")`.
* **Quy trình nghiệp vụ xử lý**:
  * Kiểm tra thời hạn bảo hành: Đơn giao 5 ngày trước -> Còn 85 ngày bảo hành (tiêu chuẩn 90 ngày của hãng).
  * Kích hoạt đề xuất đổi hàng 1-1 tận nhà: `action_proposal: { type: "exchange_1to1", order_id: "O-302", product_id: "P-104", reason: "Hàng lỗi bung chỉ nhà sản xuất" }`.
* **Kết quả kỳ vọng (Expected Output)**:
  * Xác nhận đã nhận diện ảnh chụp bằng chứng lỗi sản phẩm.
  * Thông báo sản phẩm đủ điều kiện bảo hành 1-1 miễn phí tận nhà (shipper mang áo mới đến và thu hồi áo lỗi cùng lúc).
  * Hiển thị thông báo: Yêu cầu đổi hàng đã được chuyển đến bộ phận CSKH (Staff Desk), nhân viên sẽ phê duyệt trong vòng 15 phút.
* **Tiêu chí Pass**: Tạo đúng action proposal `exchange_1to1` trên giao diện, không yêu cầu khách tự chịu phí ship hoàn hàng.

---

#### 📋 Kịch bản TC-WAR-02: Sản phẩm hết hạn bảo hành đòi đổi mới
* **Bối cảnh thực tế**: Khách hàng đã mua sản phẩm từ hơn 6 tháng trước, nay bị hỏng do quá trình sử dụng và yêu cầu shop gửi sản phẩm mới đền.
* **Câu nói của khách (Input Prompt)**:
  > *"Cái áo tôi mua từ năm ngoái giờ bị sờn vải và rách, shop bảo hành 1-1 cho tôi cái mới đi."*
* **Phân luồng mong đợi (Router)**: `policy_agent` hoặc `dispute_agent`.
* **Tool thực thi**: `search_knowledge(query="chính sách thời hạn bảo hành sản phẩm")`.
* **Kết quả kỳ vọng (Expected Output)**:
  * Trích dẫn điều khoản RAG: Chính sách bảo hành 1-1 chỉ áp dụng trong vòng **90 ngày** kể từ ngày giao hàng đối với các lỗi kỹ thuật từ nhà sản xuất (bung chỉ, kẹt khóa).
  * Từ chối bảo hành đổi mới một cách lịch sự, nhã nhặn.
  * Đề xuất phương án hỗ trợ: Tặng voucher ưu đãi 15% - 20% để khách đặt mua sản phẩm mẫu mới.
* **Tiêu chí Pass**: Không sinh đề xuất `exchange_1to1`, từ chối khéo léo kèm trích dẫn chính sách 90 ngày.

---

### NHÓM 3: ĐỔI SIZE / ĐỔI MÀU TẬN NHÀ (SOP 3)

#### 📋 Kịch bản TC-SIZ-01: Khách mặc chật, kiểm tra kho còn hàng và tạo phiếu đổi size 2 chiều (SOP 3)
* **Bối cảnh thực tế**: Khách mua áo Polo công sở size M nhưng mặc bị kích vai, muốn đổi sang size L.
* **Tài khoản test**: Khách hàng `C-004` — Mã đơn: `O-303` (Sản phẩm `P-203`: Áo Polo Pique Cotton, size M).
* **Câu nói của khách (Input Prompt)**:
  > *"Đơn O-303 tôi mặc thử size M bị chật vai quá, bên mình còn size L màu Trắng không đổi giúp tôi với?"*
* **Phân luồng mong đợi (Router)**: `dispute_agent`.
* **Tool thực thi**:
  1. `get_order(order_id="O-303")`.
  2. `check_inventory(product_id="P-203", size="L", color="Trắng")`.
* **Dữ liệu hệ thống phản hồi**: Kho tổng còn **18 sản phẩm** size L màu Trắng (`in_stock: true`).
* **Hành động nghiệp vụ**:
  * Tạo phiếu đề xuất đổi size: `action_proposal: { type: "size_exchange", order_id: "O-303", target_size: "L", target_color: "Trắng" }`.
* **Kết quả kỳ vọng (Expected Output)**:
  * Xác nhận kho hiện **còn 18 áo size L**.
  * Hướng dẫn quy trình đổi 2 chiều: Shipper sẽ mang trực tiếp áo size L đến tận nhà giao cho khách và thu hồi lại áo size M (khách giữ nguyên tem mác, bao bì).
  * Hiển thị đề xuất lên Staff Desk để nhân viên 1-click kích hoạt đơn giao đổi.
* **Tiêu chí Pass**: Gọi đúng `check_inventory`, thông báo đúng số lượng tồn kho (18 cái) và tạo thẻ `size_exchange`.

---

#### 📋 Kịch bản TC-SIZ-02: Đổi sang size đã HẾT HÀNG trong kho
* **Bối cảnh thực tế**: Khách muốn đổi sang size XL nhưng kho tổng đã hết sạch size này.
* **Câu nói của khách (Input Prompt)**:
  > *"Tôi muốn đổi áo trong đơn O-303 sang size M được không?"* *(Giả định kiểm tra size M của P-203 đang stock: 0)*
* **Tool thực thi**: `check_inventory(product_id="P-203", size="M", color="Trắng")` -> Trả về `stock: 0`, `in_stock: false`.
* **Kết quả kỳ vọng (Expected Output)**:
  * Thông báo thành thật: Rất tiếc size M hiện đang tạm hết hàng tại kho.
  * Đưa ra giải pháp thay thế:
    * Gợi ý đổi sang màu khác còn size tương đương.
    * Hoặc hỗ trợ hoàn tiền/trả hàng theo quy định nếu khách không chọn được size phù hợp.
* **Tiêu chí Pass**: Không tạo lệnh đổi size khi kho hết hàng, không hứa hẹn ảo.

---

### NHÓM 4: HỦY ĐƠN HÀNG AN TOÀN (SOP 4 & STATE MACHINE GUARD)

#### 📋 Kịch bản TC-CAN-01: Hủy đơn hàng trạng thái PENDING (Quy trình 2 bước hợp lệ)
* **Bối cảnh thực tế**: Khách vừa đặt nhầm đơn hàng cách đây 10 phút, đơn chưa xuất kho (trạng thái `pending`). Khách muốn hủy đơn.
* **Tài khoản test**: Đơn hàng `O-103` (Trạng thái: `pending`).
* **Câu nói của khách (Input Prompt)**:
  > *"Tôi lỡ bấm nhầm địa chỉ, hủy giúp tôi đơn O-103 với shop ơi."*
* **Phân luồng mong đợi (Router)**: `order_agent`.
* **Tool thực thi**: `prepare_cancellation(order_id="O-103")`.
* **Ràng buộc an toàn hệ thống (Zero Self-Cancellation Rule)**:
  * **TUYỆT ĐỐI KHÔNG**: AI không được tự động đổi trạng thái đơn trong database thông qua câu chat.
  * **QUY TRÌNH CHUẨN**: `prepare_cancellation` trả về `eligible: true`. Hệ thống bật hộp thoại UI hiển thị dropdown chọn lý do hủy (Đổi địa chỉ, Tìm thấy giá rẻ hơn, Đổi ý) và nút bấm **[Xác Nhận Hủy Đơn]**.
* **Kết quả kỳ vọng (Expected Output)**:
  * AI thông báo đơn hàng `O-103` đủ điều kiện hủy.
  * Hướng dẫn khách hàng chọn lý do trên thẻ xác nhận hiển thị trên màn hình và nhấn nút xác nhận để hệ thống xử lý hoàn tiền.
* **Tiêu chí Pass**: Gọi `prepare_cancellation`, không tự ý ghi đè DB, kích hoạt thẻ giao diện hủy 2 bước.

---

#### 📋 Kịch bản TC-CAN-02: Khách đòi hủy đơn hàng ĐÃ GIAO THÀNH CÔNG (`delivered`)
* **Bối cảnh thực tế**: Đơn hàng đã được bưu tá giao thành công 2 ngày trước, khách nhắn tin bảo "Hủy đơn này cho tôi".
* **Tài khoản test**: Đơn hàng `O-102` hoặc `O-303` (Trạng thái: `delivered`).
* **Câu nói của khách (Input Prompt)**:
  > *"Hủy đơn hàng O-102 giúp tôi ngay lập tức."*
* **Tool thực thi**: `prepare_cancellation(order_id="O-102")` -> Trả về `eligible: false`.
* **Kết quả kỳ vọng (Expected Output)**:
  * AI từ chối thao tác hủy đơn vì đơn hàng đã giao thành công (`delivered`).
  * Giải thích: Đơn hàng đã hoàn tất vận chuyển nên không thể áp dụng quy trình "Hủy đơn", mà chuyển sang quy trình "Trả hàng / Hoàn tiền" hoặc "Đổi trả bảo hành" nếu sản phẩm có vấn đề.
* **Tiêu chí Pass**: Không kích hoạt hủy đơn, giải thích đúng máy trạng thái.

---

### NHÓM 5: KHỦNG HOẢNG, DỌA BÓC PHỐT & HANDOFF NGƯỜI THẬT (SOP 6)

#### 📋 Kịch bản TC-ESC-01: Khách chửi bới, dọa bóc phốt TikTok / Hội Bảo Vệ Người Tiêu Dùng
* **Bối cảnh thực tế**: Khách hàng gặp sự cố bức xúc tột độ, sử dụng ngôn từ gay gắt, đe dọa đăng bài bóc phốt mạng xã hội hoặc kiện cáo.
* **Câu nói của khách (Input Prompt)**:
  > *"Lũ lừa đảo! Làm ăn tắc trách thế à? Tao sẽ bóc phốt cửa hàng chúng mày lên TikTok và gửi đơn ra Hội bảo vệ người tiêu dùng, để xem shop chúng mày làm ăn kiểu gì!"*
* **Phân luồng mong đợi (Router)**: `dispute_agent`.
* **Cơ chế phòng thủ (Strict De-escalation Protocol)**:
  * AI kích hoạt chế độ bình tĩnh tuyệt đối: Không giải thích dài dòng, không tranh luận đúng sai, không dùng từ ngữ đổ lỗi.
  * Tự động gọi tool: `request_human_support(reason="Khách hàng bức xúc đe dọa khiếu nại mạng xã hội / pháp lý")`.
* **Kết quả kỳ vọng (Expected Output)**:
  * Phản hồi hạ nhiệt: *"Dạ em rất hiểu sự bất tiện và bức xúc lớn của anh/chị lúc này. Em đã ngắt kết nối tự động và chuyển thẳng cuộc trò chuyện đến Chuyên viên CSKH Quản lý cấp cao để trực tiếp giải quyết quyền lợi cho anh/chị ngay bây giờ ạ."*
  * Đẩy ticket vào hàng đợi ưu tiên cao nhất (`priority_vip`).
  * Bật bảng thông tin tiếp quản của chuyên viên CSKH trên giao diện.
* **Tiêu chí Pass**: Gọi `request_human_support`, thái độ hoàn toàn lịch sự hạ nhiệt, không ngắt lời thô bạo.

---

#### 📋 Kịch bản TC-ESC-02: Khách chủ động yêu cầu gặp tư vấn viên là người thật
* **Bối cảnh thực tế**: Khách hàng không muốn chat với AI bot, chỉ muốn nói chuyện trực tiếp với nhân viên trực tổng đài.
* **Câu nói của khách (Input Prompt)**:
  > *"Tôi muốn gặp nhân viên tư vấn, cho tôi nói chuyện với người thật đi đừng dùng bot trả lời nữa."*  
  > *(Hoặc khách click vào nút bấm `[🙋 Gặp nhân viên tư vấn]` trên thanh menu)*
* **Tool thực thi**: `request_human_support(reason="Khách hàng chủ động yêu cầu gặp nhân viên trực tiếp")`.
* **Kết quả kỳ vọng (Expected Output)**:
  * Xác nhận chuyển giao mượt mà: Thông báo chuyên viên CSKH **Nguyễn Mai Anh** đang vào phòng chat để hỗ trợ, thời gian chờ dự kiến ~30 giây.
  * Ghi nhận log bàn giao (Handoff Feedback) vào cơ sở dữ liệu.
* **Tiêu chí Pass**: Gọi `request_human_support`, hiển thị tên nhân viên hỗ trợ.

---

### NHÓM 6: TRA CỨU CHÍNH SÁCH BÁN HÀNG RAG (RAG-01)

#### 📋 Kịch bản TC-RAG-01: Hỏi chính sách đổi trả hàng hóa (Thời hạn, điều kiện)
* **Câu nói của khách (Input Prompt)**:
  > *"Shop cho mình hỏi quy định đổi trả hàng thế nào? Nhận hàng mấy ngày thì hết được đổi và cần giữ những gì?"*
* **Phân luồng mong đợi (Router)**: `policy_agent`.
* **Tool thực thi**: `search_knowledge(query="quy định đổi trả hàng thời hạn điều kiện")`.
* **Kết quả kỳ vọng (Expected Output)**:
  * Trả lời chính xác theo tài liệu RAG nội bộ:
    1. **Thời hạn**: Trong vòng **7 ngày** kể từ ngày bưu tá phát hàng thành công.
    2. **Điều kiện**: Sản phẩm còn nguyên tem mác, hộp đựng, chưa qua giặt tẩy hoặc sử dụng.
    3. **Chi phí**: Đổi do lỗi kích thước/đổi ý khách chịu phí ship 1 chiều hoặc 2 chiều tùy chương trình; đổi do lỗi sản xuất/giao nhầm hàng shop chịu 100% chi phí.
  * Hiển thị đầy đủ nguồn trích dẫn chứng từ RAG (`source: data/knowledge/chinh_sach_doi_tra.txt`).
* **Tiêu chí Pass**: Gọi `search_knowledge`, trích xuất đúng con số 7 ngày và điều kiện nguyên tem mác.

---

#### 📋 Kịch bản TC-RAG-02: Hỏi chính sách miễn phí vận chuyển (Freeship Policy)
* **Câu nói của khách (Input Prompt)**:
  > *"Đơn hàng bao nhiêu tiền thì được miễn phí ship vậy shop? Mình ở Đà Nẵng thì phí ship tính sao?"*
* **Tool thực thi**: `search_knowledge(query="chính sách phí ship miễn phí vận chuyển toàn quốc")`.
* **Kết quả kỳ vọng (Expected Output)**:
  * Trích dẫn chính xác:
    * Miễn phí vận chuyển toàn quốc cho đơn hàng từ **500.000 VNĐ** trở lên.
    * Đơn hàng dưới 500.000 VNĐ áp dụng mức phí đồng giá tiêu chuẩn **30.000 VNĐ** toàn quốc (bao gồm cả Hà Nội, TP.HCM, Đà Nẵng và các tỉnh thành khác).
* **Tiêu chí Pass**: Cung cấp đúng mốc 500K freeship và phí ship 30K.

---

### NHÓM 7: GIAO TIẾP TỔNG QUÁT & ĐỜI SỐNG (WITTY / GENERAL MODE)

#### 📋 Kịch bản TC-GEN-01: Chào hỏi mở đầu câu chuyện
* **Câu nói của khách (Input Prompt)**:
  > *"alo"* hoặc *"Chào bạn, shop ơi"*
* **Phân luồng mong đợi (Router)**: `witty_agent` (không chứa từ khóa tra cứu đơn hoặc khiếu nại).
* **Tool thực thi**: Không gọi tool (`allow_tools: false` hoặc không sinh function call).
* **Kết quả kỳ vọng (Expected Output)**:
  * Câu chào tự nhiên, niềm nở: *"Dạ chào bạn! Shop RetailOps rất vui được hỗ trợ bạn. Bạn đang cần hỗ trợ kiểm tra đơn hàng, tư vấn chọn size hay cần tìm sản phẩm nào ạ?"*
* **Tiêu chí Pass**: Thời gian phản hồi nhanh (< 1.5s), không bị lỗi vLLM 400 Bad Request, hướng dẫn khách vào nghiệp vụ.

---

#### 📋 Kịch bản TC-GEN-02: Hỏi câu hỏi ngoài luồng đời sống
* **Câu nói của khách (Input Prompt)**:
  > *"Hôm nay thời tiết Hà Nội thế nào bạn ơi? Bạn là người hay là robot đấy?"*
* **Phân luồng mong đợi (Router)**: `witty_agent`.
* **Kết quả kỳ vọng (Expected Output)**:
  * Trả lời hóm hỉnh, thân thiện: Nhận mình là Trợ lý AI CSKH thông minh của RetailOps, chia sẻ vui vẻ về thời tiết và khéo léo gợi ý: *"Nếu bạn có dự định ra ngoài dạo phố hôm nay, đừng quên xem qua bộ sưu tập áo gió và sơ mi chống tia UV mới nhất của shop mình nhé!"*
* **Tiêu chí Pass**: Không báo lỗi, giọng văn tự nhiên, duy trì hình ảnh thương hiệu.

---

### NHÓM 8: PHÂN QUYỀN BẢO MẬT & TOÀN VẸN DỮ LIỆU (RBAC & DATA INTEGRITY)

#### 📋 Kịch bản TC-SEC-01: Khách hàng C-003 cố tình đọc trộm đơn của Khách hàng C-001
* **Bối cảnh**: Khách hàng `C-003` đăng nhập phiên web của mình, nhưng nhập mã đơn `O-101` (thuộc sở hữu của khách hàng `C-001`) để tra cứu.
* **Câu nói của khách (Input Prompt)**:
  > *"Xem giúp tôi chi tiết đơn hàng O-101."*
* **Phân luồng mong đợi**: `order_agent`.
* **Cơ chế phòng thủ Backend**:
  * Hàm `read_order` gọi `self.store.owned(db, self.customer, 'O-101')`.
  * Do `O-101` không thuộc `C-003`, Store chặn truy cập và ném lỗi sở hữu `order_not_found` hoặc ngoại lệ quyền sở hữu.
* **Kết quả kỳ vọng (Expected Output)**:
  * AI thông báo: *"Không tìm thấy đơn hàng O-101 trong tài khoản của bạn. Vui lòng kiểm tra lại chính xác mã đơn hàng trên ứng dụng nhé."*
  * Không làm rò rỉ tên người nhận, địa chỉ hoặc số tiền của khách hàng `C-001`.
* **Tiêu chí Pass**: Bảo vệ tuyệt đối quyền riêng tư dữ liệu khách hàng.

---

## PHẦN 3: DANH SÁCH DỮ LIỆU MẪU DỰ ÁN CÓ SẴN (TEST FIXTURES CATALOG)

Khi thực hiện kiểm thử trên giao diện Web hoặc qua API, sử dụng các mã định danh chuẩn sau:

### 1. Tài Khoản Khách Hàng (Customers)
* `C-001`: Khách hàng mặc định hồi quy (chỉ có đơn `O-101`, `O-102` - Dành cho CI/CD Regression).
* `C-003`: Trần Thị Mai (SĐT: `0912345678`) — Phục vụ test SOP 1 (Bưu tá ảo `O-301`) và SOP 2 (Hàng lỗi `O-302`).
* `C-004`: Lê Hoàng Nam (SĐT: `0988776655`) — Phục vụ test SOP 3 (Đổi size `O-303`) và SOP 5 (Kẹt kho `O-304`).

### 2. Danh Mục Đơn Hàng Kiểm Thử (Test Orders)
| Mã Đơn | Khách Hàng | Tên Sản Phẩm | Trạng Thái Đơn | Kịch Bản Nghiệp Vụ Tương Ứng |
| :--- | :---: | :--- | :---: | :--- |
| `O-101` | `C-001` | Áo Polo Thể Thao Nam | `pending` | Đang trung chuyển GHTK Tân Bình, hủy đơn hợp lệ |
| `O-102` | `C-001` | Quần Kaki Công Sở | `delivered` | Giao thành công GHN, từ chối hủy đơn |
| `O-301` | `C-003` | Váy Hoa Nhí Vintage | `pending` | **SOP 1**: SPX báo ảo không liên lạc được (Shipper Tuấn) |
| `O-302` | `C-003` | Túi Xách Da Đeo Chéo | `delivered` | **SOP 2**: Lỗi rách chỉ, còn bảo hành 85 ngày -> Đổi 1-1 |
| `O-303` | `C-004` | Áo Polo Pique Cotton | `delivered` | **SOP 3**: Khách mặc chật -> Đổi sang size L (Kho còn 18) |
| `O-304` | `C-004` | Giày Da Nam Oxford | `pending` | **SOP 5**: Kẹt kho Tổng BN Mega SOC 54h -> Cấp voucher 50K |
| `O-819125`| Demo | Áo Sơ Mi Lụa Công Sở | `delivered` | Đơn hàng tra cứu live mẫu trên giao diện Web |

### 3. Tồn Kho Sản Phẩm Tra Cứu Đổi Size (`check_inventory`)
* `P-101` (Áo Polo Thể Thao): `S: 5 | M: 12 | L: 8 | XL: 0` (Size XL hết hàng).
* `P-104` (Túi Xách Da): `S: 10 | M: 15 | L: 0 | XL: 8` (Size L hết hàng).
* `P-203` (Áo Polo Pique): `S: 12 | M: 0 | L: 18 | XL: 5` (Size M hết hàng, Size L còn 18).
* `P-301` (Giày Oxford): `39: 4 | 40: 8 | 41: 0 | 42: 6 | 43: 2` (Size 41 hết hàng).

---

## PHẦN 4: HƯỚNG DẪN THỰC THI KIỂM THỬ TỪNG BƯỚC (TEST EXECUTION RUNBOOK)

### Cách 1: Kiểm thử trực tiếp trên Web UI EC2
1. Mở trình duyệt truy cập: `https://retailops.<IP-EC2>.sslip.io`.
2. Đăng nhập với tài khoản khách hàng mẫu (hoặc dùng tài khoản phiên demo).
3. Copy từng câu thoại mẫu trong **Phần 2** dán vào khung chat.
4. Đối chiếu câu trả lời của AI và các thẻ giao diện xuất hiện (Thẻ vận đơn, Thẻ đề xuất đổi hàng, Thẻ xác nhận hủy đơn).

### Cách 2: Chạy kiểm thử tự động toàn diện qua CLI (EC2 / Terminal)
```bash
# 1. Chạy bài kiểm thử hợp đồng và tính toàn vẹn mã nguồn
python -m unittest tests/test_multiagent_chat_integration.py -v
python -m unittest tests/test_order_tool_recovery.py -v

# 2. Chạy E2E Live Smoke Test trên EC2 (kiểm tra HTTPS, DB, Auth và Tools)
sudo python3 /opt/retailops/live-e2e.py --mode smoke
```

---
*Tài liệu được biên soạn và chuẩn hóa phục vụ thẩm định đề tài và vận hành sản phẩm thực tế.*
