# RetailOps 0.3 — hội thoại có ngữ cảnh và dữ liệu nguồn

> Tài liệu lịch sử bản 0.2/0.3. Với phiên bản hiện tại, dùng [AGENT_V04.md](AGENT_V04.md), gồm notebook mới, hợp đồng chat và các bước nâng cấp.

## Thay đổi

Bản 0.2 nhận diện tra/hủy đơn nhưng các lời chào, câu hỏi sản phẩm và câu ngoài
phạm vi đều dễ rơi vào lời nhắc chung. Bản này bổ sung lớp hội thoại có giới hạn:

- Lời chào/cảm ơn và hướng dẫn phạm vi hỗ trợ.
- Thông tin đầy đủ của đơn thuộc khách đang đăng nhập: trạng thái, sản phẩm,
  biến thể, giá trị đơn, lý do hủy nếu có và điều kiện hủy.
- Danh mục sản phẩm giả lập trong `data/products.json`. Dữ liệu thiếu được nói rõ;
  không suy diễn chất liệu, giá bán hiện tại, thanh toán, tồn kho hoặc lịch giao.
- Nhớ mã đơn/sản phẩm của từng cuộc trò chuyện. Các câu “đơn này”, “áo này”,
  “chất liệu gì?” có thể dùng ngữ cảnh đã xác định. Mỗi lượt đọc lại dữ liệu đơn.
- Chọn đơn bằng nút cũng cập nhật ngữ cảnh. Nêu sản phẩm khác sẽ bỏ mã đơn cũ
  để yêu cầu hủy sau đó không nhắm vào một đơn không liên quan.
- Cuộc trò chuyện mới bỏ ngữ cảnh, không reset trạng thái đơn hay nhật ký.

## Phân biệt vai trò của model

Đây là lớp định tuyến bằng quy tắc và dựng câu trả lời từ dữ liệu có cấu trúc,
không phải chatbot sinh văn bản tự do, RAG embedding hay model đã fine-tune.
Nhãn nguồn ở mỗi tin nhắn phân biệt:

| Nhãn | Cách trả lời |
|---|---|
| Hướng dẫn hỗ trợ | Quy tắc lời chào/phạm vi, không gọi model |
| Dữ liệu đơn hàng | Đọc đơn từ SQLite sau kiểm tra chủ sở hữu |
| Danh mục sản phẩm mẫu | Đọc danh mục fixture, không tự thêm thuộc tính |
| Model nhận diện · Backend trả lời | Gọi Qwen qua proxy hiện có, kiểm tra JSON rồi đọc dữ liệu/đề xuất luồng |

Các yêu cầu hủy bằng chat vẫn gọi model; nút yêu cầu hủy vẫn dùng API cấu trúc.
Các cách diễn đạt nghiệp vụ chưa được quy tắc xử lý cũng dùng model nhận diện.
Nếu dùng tham chiếu như “hủy đơn này”, server chỉ bổ sung mã đơn đã được xác
định và kiểm tra quyền trong chính phiên. Không gửi lịch sử hội thoại đầy đủ
hoặc cho phép model tự chọn khách hàng. Model không tạo proposal hoặc hủy đơn.

Độ bao phủ ngôn ngữ còn giới hạn; đây chưa phải trợ lý tổng quát. Luồng đổi/trả,
hoàn tiền và sửa địa chỉ chưa được triển khai. Câu ngoài phạm vi, ví dụ SAC,
được chuyển về hướng dẫn hỗ trợ cửa hàng thay vì lặp lời nhắc nhập mã đơn.

Prompt, schema, model và evaluator baseline không đổi. Báo cáo L4 83,33%
vẫn là báo cáo cũ; không gọi độ đúng của lớp quy tắc này là độ chính xác mới của Qwen.

## Ngữ cảnh và dữ liệu

Thêm bảng SQLite `conversations` bằng `CREATE TABLE IF NOT EXISTS`. Không đổi
hoặc reset orders/proposals/business_events; đơn đã hủy vẫn giữ nguyên.
Context chỉ chứa mã đơn/sản phẩm, chủ phiên, revision và thời hạn 30 phút.
Mỗi đăng nhập/tab tạo một conversation ID mới, giữ trong bộ nhớ trang.
Không phải lịch sử chat dài hạn. Tải lại trang cần đăng nhập và tạo phiên mới.

Conversation ID không thay thế xác thực: các endpoint đều kiểm tra demo token
và chủ conversation. Revision giúp từ chối kết quả ghi ngữ cảnh bị đua giữa các
yêu cầu đồng thời. Nhiều mã đơn, lookup thất bại hoặc lỗi model không được dùng
mã đơn cũ làm mục tiêu ngầm. Context cũ hết hạn được xóa khi tạo phiên mới.

Thêm hai endpoint:

| Endpoint | Body | Kết quả |
|---|---|---|
| POST `/api/conversations` | `{}` | Mã cuộc trò chuyện mới, context rỗng |
| POST `/api/conversations/{id}/focus` | `{"order_id":"O-102"}` | Tra đơn thuộc khách và cập nhật context |
| POST `/api/chat` | `{"text":"Áo này là gì?","conversation_id":"..."}` | Trả lời và context mới |

Client cũ vẫn gửi được `/api/chat` chỉ có `text`, nhưng không có trí nhớ phiên.
Các API proposal/confirm/dismiss và mã chống thực hiện lặp giữ nguyên.

## Cập nhật EC2 đang chạy

1. Review/merge PR hội thoại, chờ CI và CD trên `main` thành công.
2. Trên terminal **EC2 Session Manager**, chạy:

```bash
cd /opt/retailops
sudo docker compose --project-name retailops-api --env-file deployed.env -f compose.api.yaml up -d --no-build --pull never --force-recreate --wait --wait-timeout 60
curl --fail --silent --show-error http://127.0.0.1:8080/healthz
```

Health response phải có `"version":"0.3"` (có thể có khoảng trắng).
Lệnh dùng image digest đã được CD kích hoạt; không tự fetch code từ nhánh feature.
Nếu vẫn hiện 0.2 hoặc không có version, kiểm tra CD đã chạy đúng commit mới.

3. Giữ PowerShell SSM port-forward mở, tải lại `http://localhost:8080`, đăng nhập
   bằng mã demo cũ. Không thay `api.env` hoặc `inference.env` cho bản này.
4. Colab notebook/proxy hiện tại tương thích, không cần upload lại hoặc đổi token.
   Nếu bạn đã kết thúc Colab, các câu tra cứu/danh mục/lời chào vẫn chạy;
   khởi động lại model và cập nhật URL ngrok khi thử phần có gọi Qwen.

## Chuỗi kiểm tra trên giao diện

| Thao tác / câu nhập | Kết quả cần đạt |
|---|---|
| `hello` | Lời chào và các việc có thể hỗ trợ; nguồn Hướng dẫn hỗ trợ |
| `O-101, cho tôi biết mọi thứ về mã đơn này` | Thông tin đơn đầy đủ; nếu đã hủy thì vẫn Đã hủy |
| `Đơn này bao nhiêu tiền?` | Giá trị của đúng đơn vừa xem |
| Chọn O-102 bằng nút, rồi hỏi `Áo này là gì?` | Áo khoác Everyday, biến thể Đen / L |
| `Áo này chất liệu gì?` | Nói chưa có dữ liệu chất liệu |
| `Áo này giá bao nhiêu?` | Nói chưa có giá bán hiện tại, không dùng giá trị đơn làm giá bán |
| `Có size S không?` | Liệt kê biến thể ghi nhận, không khẳng định có size S hay còn hàng |
| `giải thích thuật toán SAC` | Báo ngoài phạm vi cửa hàng |
| Bấm Cuộc trò chuyện mới, hỏi `Đơn này thế nào?` | Hỏi mã đơn vì phiên mới chưa có context |
| Tra đơn chưa hủy rồi gửi `Hủy đơn này vì tôi đặt nhầm` | Model nhận diện, chọn lý do và xác nhận riêng; không tự hủy |

Không xóa database EC2 để có đơn pending. Đơn O-101 của bạn đã hủy vẫn được giữ.
Có thể thử hủy lại để xác nhận backend từ chối; dùng database tạm local nếu cần
diễn lại một lần hủy thành công từ đầu.

## Xác minh

76 tests offline qua ở môi trường phát triển, gồm test HTTP với server thật,
context theo khách/tab, đổi sản phẩm, thiếu dữ liệu, context hết hạn, cập nhật
đồng thời, schema nâng cấp không reset đơn, các guard hủy/idempotency hiện có.
Đã chạy lại các câu người dùng cung cấp để xem response từ lớp dữ liệu.
JavaScript được kiểm tra cú pháp và các ID/asset của HTML được đối chiếu.
Inference trong tests dùng mock; chưa chạy lại GPU thật, browser QA hoặc EC2
trong môi trường trợ lý. CI sẽ build Docker và chạy toàn bộ tests trong image.
