# RetailOps 0.4 — hội thoại Qwen và công cụ nghiệp vụ

Bản 0.3 định tuyến câu chat bằng regex và ghép câu trả lời có sẵn. Bản 0.4 bỏ
đường chat đó: mọi tin nhắn gửi vào `/api/chat` gọi Qwen, model chọn công cụ đọc
dữ liệu rồi sinh câu trả lời. Lời chào trên màn hình đăng nhập/phiên mới và thông
báo nút bấm vẫn là nội dung giao diện, được ghi nhãn riêng.

## Nâng cấp phiên EC2 + Colab hiện tại

### 1. Mở notebook mới

Tải `notebooks/colab_agent.ipynb` từ PR/nhánh của bản này và upload vào Colab.
Không dùng notebook `colab_inference.ipynb` cũ: proxy cũ chỉ nhận JSON trích xuất,
không nhận lịch sử hoặc native tool calling.

Trước khi đổi notebook, tải kết quả baseline cũ và dừng tunnel/proxy của notebook
cũ. Có thể giữ model đã tải nếu vẫn dùng cùng runtime, nhưng phải dừng tunnel cũ
để tránh giới hạn phiên ngrok. Notebook mới dùng thư mục `/content/retailops_agent`
và cổng proxy 8002. Không có tác vụ giữ Colab sống, chạy nền liên tục hay mua compute.

Chọn GPU L4 nếu được cấp, rồi **chạy từng ô**, không Run all:

1. **Source** → `AGENT_SOURCE_READY` và test thành công. Không upload ZIP.
2. **Runtime/model** → `AGENT_MODEL_READY: qwen3.5:4b retailops-agent-v1`.
   Ô này làm nóng context 8192 trước khi dùng giới hạn thời gian tương tác.
   Kiểm tra bảng `ollama ps`: model thực sự dùng GPU; lần đầu có thể chậm.
3. **Thử hội thoại** → chín lượt gọi model thật với database tạm riêng.
   Báo cáo phải có `READ_ONLY_CHAT_OK: True`. `AGENT_PROTOCOL_CHECKS_OK: True`
   chỉ xác nhận kết nối và công cụ dự kiến đã xuất hiện; phải đọc câu trả lời để
   đánh giá tính đúng và tự nhiên. Nếu FAIL/REVIEW, tải báo cáo JSON để sửa tiếp.
4. **Proxy/tunnel**: Colab Secrets cần `NGROK_AUTHTOKEN` và
   `RETAILOPS_INFERENCE_TOKEN`, bật quyền notebook truy cập. Dùng cùng inference
   token đang có trên EC2; không gửi token qua chat. Ô in:

```text
AGENT_PROXY_READY: retailops-agent-v1
RETAILOPS_MODEL_URL=https://...ngrok-free.dev
RETAILOPS_ALLOWED_HOST=...ngrok-free.dev
```

Giữ phiên Colab đang chạy trong lúc thử giao diện.

### 2. Merge PR và chờ CD

Sau khi xem thay đổi và CI xanh, merge PR vào `main`. Chờ cả **CI** và
**Deploy baseline runner to EC2** của commit mới thành công. CD kích hoạt image
mới trong `deployed.env`, nhưng container API đang chạy cần được tạo lại ở bước sau.

### 3. Cập nhật EC2

Mở EC2 → retailops-dev → Connect → Session Manager. Chạy:

```bash
sudo nano /opt/retailops/inference.env
```

Điền URL/hostname vừa in ở notebook, giữ model `qwen3.5:4b` và cùng inference
token. Các giá trị là văn bản thuần, không có dấu ngoặc Markdown hoặc dấu nháy:

```dotenv
RETAILOPS_MODEL=qwen3.5:4b
RETAILOPS_MODEL_URL=https://YOUR_HOST.ngrok-free.dev
RETAILOPS_ALLOWED_HOST=YOUR_HOST.ngrok-free.dev
RETAILOPS_INFERENCE_TOKEN=YOUR_EXISTING_INFERENCE_TOKEN
```

Trong `/opt/retailops/api.env`, kiểm tra `RETAILOPS_MODEL_ENABLED=true`.
Giữ `RETAILOPS_DEMO_TOKEN` riêng cho giao diện. Sau đó:

```bash
sudo chmod 600 /opt/retailops/inference.env /opt/retailops/api.env
cd /opt/retailops
sudo docker compose --project-name retailops-api --env-file deployed.env -f compose.api.yaml up -d --no-build --pull never --force-recreate --wait --wait-timeout 60
curl --fail --silent --show-error http://127.0.0.1:8080/healthz
```

Kết quả cần chứa `"version": "0.4"` và `"agent_protocol": "retailops-agent-v1"`.
Health chỉ kiểm tra API/database, **không xác nhận model đã kết nối**.
Dữ liệu SQLite và đơn đã hủy được giữ qua migration/tạo lại container.
Nếu health còn 0.3, kiểm tra đúng lần CD trước khi chạy lại lệnh Compose.

### 4. Bấm thử trên giao diện

Giữ cửa sổ PowerShell SSM port forwarding như trước, mở `http://localhost:8080`,
nhấn Ctrl+F5, đăng nhập lại bằng mã demo. Mỗi lần đăng nhập tạo conversation mới.

| Tin nhắn/thao tác | Điều cần quan sát |
|---|---|
| `hello` | Qwen tự viết lời chào; chi tiết có ít nhất một lượt gọi model |
| `Giải thích mọi thứ về đơn O-101` | Gọi `get_order`, dùng trạng thái thật hiện tại; đơn đã hủy vẫn đã hủy |
| `Áo trong đơn đó chất liệu gì?` | Dùng ngữ cảnh và công cụ danh mục; dữ liệu chất liệu còn thiếu, không tự thêm cotton/polyester |
| `Bạn đang chạy model nào?` | Gọi `get_runtime_info`, trả tên model từ runtime |
| `Hôm nay ở Việt Nam ngày mấy?` | Gọi `get_current_time`, dùng ngày từ đồng hồ backend |
| `Giải thích thuật toán SAC` | Model tự diễn đạt phạm vi hỗ trợ cửa hàng |
| `Cho tôi xem O-202` | Backend từ chối đơn của khách khác; không tiết lộ sản phẩm/giá |
| `Hủy O-101` rồi `Tôi xác nhận ngay trong chat` | Chat không hủy đơn; O-101 đã hủy trước đó cũng không hủy lại |

Bấm **Chi tiết lượt trả lời**: xem tên/digest model, số lần gọi, công cụ, latency
và mã lượt. Trả lời dùng công cụ thường cần từ hai lần gọi model, nên latency
không nên so trực tiếp với phép trích xuất ~0,8 giây của baseline cũ.

Không reset database EC2 chỉ để làm lại hủy đơn. Notebook bước 3 đã có đơn pending
riêng để thử luồng mở chọn lý do. Các nút xác nhận của API tiếp tục kiểm tra quyền,
phiên bản và idempotency; model không có công cụ thực hiện giao dịch.

Khi xong, tải ZIP báo cáo bằng ô 5, chạy ô dừng ở cuối rồi **Disconnect and delete
runtime**. Khi Colab tắt, mọi câu chat báo lỗi kết nối; các nút tra/hủy vẫn dùng được.

## Hợp đồng và các giới hạn thực tế

Dựa trên [native tool calling của Ollama](https://docs.ollama.com/capabilities/tool-calling)
và [Chat API](https://docs.ollama.com/api/chat). `agent_protocol.py` chứa system prompt,
danh sách công cụ và schema. Proxy tự xây request; người gọi không truyền model,
system prompt, tools, options hoặc URL upstream tùy ý. Baseline `/api/chat` ở proxy
vẫn giữ schema và prompt cũ; agent dùng `/agent/identity` và `/agent/chat` riêng.

| Công cụ | Quyền |
|---|---|
| `list_orders`, `get_order` | Chỉ đọc đơn thuộc khách gắn với token |
| `get_context` | Đọc lại dữ liệu đơn/sản phẩm đang chọn |
| `search_products`, `get_product` | Đọc danh mục giả lập, tìm theo từ khóa; chưa có vector RAG |
| `prepare_cancellation` | Chỉ kiểm tra điều kiện và mở UI chọn lý do; không tạo proposal, không hủy |
| `get_runtime_info`, `get_current_time` | Đọc danh tính runtime và thời gian Việt Nam |

`retailops_tools.py` phân phối tên công cụ vào hàm tương ứng. Đây là bước thực thi
công cụ có cấu trúc; việc hiểu lời người dùng, chọn công cụ và viết câu trả lời do
model thực hiện. Không còn regex phân loại tin nhắn hoặc câu chat mẫu khi model lỗi.
Quy tắc xác thực, kiểm tra giao dịch và các nút thao tác tiếp tục là code xác định.

- POST `/api/chat` cần `text`, `conversation_id`, `request_id`; frontend mới tự gửi
  UUID. Không nhận lịch sử/customer ID do client tự cung cấp. Client 0.3 phải tải lại.
- `agent_turns` lưu tối đa 6 lượt hoàn tất/phiên; gửi lại model tối đa 16 message,
  4.500 ký tự nội dung và tool call của những lượt gần nhất, luôn giữ nguyên cặp
  tool call/result. Tổng input protocol bị chặn quá 12.000 ký tự/40 message.
  Mỗi câu tối đa 2.000 ký tự. Đây là ngân sách ký tự, không phải tokenizer chính xác.
- Mỗi lượt tối đa 4 lần gọi model, 8 tool calls, 30 giây/lần gọi và tổng vòng agent
  khoảng 110 giây. Một lượt model xử lý tại một thời điểm. UI chờ tối đa 150 giây
  bao gồm kiểm tra danh tính/kết nối; model không tự retry vô hạn.
- Retry trong những lượt còn lưu trả kết quả cũ, có nhãn rõ và không mở lại thẻ hủy.
  Ngoài phạm vi lưu, request có thể chạy lại, nhưng chat không có thao tác ghi đơn.
- Lịch sử hết hạn truy cập sau 30 phút không sử dụng; dữ liệu phiên hết hạn được
  dọn khi tạo conversation mới. Nhật ký nghiệp vụ giữ trace kỹ thuật, không ghi
  token/URL, nội dung prompt hoặc chain of thought. Transcript có câu người dùng
  và tool result, chỉ dùng dữ liệu giả lập; đây chưa phải chính sách lưu trữ sản xuất.
- Quyền đọc, điều kiện hủy và giao dịch được code kiểm soát. **Câu chữ model vẫn có
  thể sai hoặc bỏ sót công cụ**; system prompt không bảo đảm không hallucinate.
  Trace và bài thử GPU giúp phát hiện lỗi. Chưa có đánh giá độc lập hoặc dữ liệu
  cửa hàng thật, fine-tuning, vector search, đổi/trả, thanh toán hay hoàn tiền.

## Kiểm tra và bảo trì

```bash
python -m unittest discover -s tests -v
python scripts/build_agent_notebook.py --check
node --check web/app.js
```

Sau khi sửa bất kỳ source/test/UI được nhúng, chạy lại
`python scripts/build_agent_notebook.py` và commit notebook cùng source. CI chặn
notebook lệch source, chạy tests ở host, build Docker và chạy lại tests trong image.
Bộ test gồm baseline, transaction/idempotency, lịch sử/quyền sở hữu, model lỗi,
công cụ không hợp lệ, race trạng thái và chuỗi HTTP API → proxy → Ollama giả lập.
Các test giả lập không chứng minh chất lượng GPU; chạy notebook và lưu báo cáo thật.

Môi trường phát triển đã chạy 80 tests và toàn bộ source nhúng. Chưa chạy Colab L4
hoặc EC2 thật cho bản agent này tại thời điểm tạo PR. Baseline cũ 83,33% giữ nguyên,
không chuyển thành điểm chính xác của agent 0.4.
