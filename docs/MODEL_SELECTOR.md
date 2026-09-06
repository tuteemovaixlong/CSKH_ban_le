# RetailOps 0.4.1 — chọn API hoặc custom model trong giao diện

Ngay phía trên lịch sử chat có bộ chọn **Nguồn model**:

- **Custom model · Colab/Ollama**: dùng model và proxy đang cấu hình trên EC2,
  hiện là `qwen3.5:4b`. Cần runtime Colab đang hoạt động khi thử tương tác.
- **API · OpenRouter**: dùng Muse Spark Contributor được chủ demo bật ở backend.
  Bản này hỗ trợ `meta/muse-spark-1.3-contributor` (mặc định) và
  `meta/muse-spark-1.2-contributor`; chưa tích hợp Meta API trực tiếp/Vercel API.

Tên model nằm dưới bộ chọn và được ghi ở mỗi câu trả lời. Mục chưa cấu hình hiện
**Chưa cấu hình** và không chọn được. Trạng thái **Đã cấu hình** không khẳng định
kết nối đang sống: chỉ gửi tin mới gọi model. Chọn nguồn/mở cuộc trò chuyện không
phát sinh lần gọi API tính phí. Tất cả request model vẫn xuất phát từ EC2.

Đổi nguồn mở một conversation mới, bắt đầu lại lịch sử và ngữ cảnh để tin nhắn
Colab không bị gửi sang dịch vụ API. Đơn hàng và nhật ký nghiệp vụ được giữ nguyên.
Khi đang xử lý tin nhắn hoặc có đề xuất chờ xác nhận, cần hoàn tất thao tác trước
khi đổi nguồn. Lỗi chuyển nguồn giữ nguyên conversation hiện tại.

## Cập nhật EC2 đang chạy

Sau khi review/merge PR và chờ CI + CD của commit mới thành công, chạy trong
**EC2 Session Manager**:

```bash
cd /opt/retailops
sudo docker compose --project-name retailops-api --env-file deployed.env -f compose.api.yaml up -d --no-build --pull never --force-recreate --wait --wait-timeout 60
curl --fail --silent --show-error http://127.0.0.1:8080/healthz
```

Health phải có `"version":"0.4.1"`. Giữ cửa sổ PowerShell SSM chuyển tiếp cổng,
mở `http://127.0.0.1:8080`, Ctrl+F5, đăng nhập lại để thấy bộ chọn.

**Có thể dùng Colab ngay với cấu hình hiện tại.** Giao thức proxy
`retailops-agent-v1`, prompt/schema tools và URL custom không đổi; không cần dừng
phiên GPU chỉ để thêm dropdown. Notebook trong repo được tạo lại để đồng bộ source
và test khi dùng cho một phiên mới. Baseline Qwen 24 mẫu không đổi.

## Bật API khi đã sẵn sàng

API mặc định tắt; không cần tạo tài khoản hoặc nạp tiền để dùng phần custom.
Khi có OpenRouter API key và muốn cho phép dùng nó, sửa ngay trên EC2:

```bash
sudo nano /opt/retailops/api.env
```

Giữ các dòng `RETAILOPS_DEMO_TOKEN` và `RETAILOPS_MODEL_ENABLED` hiện tại. Thêm
hoặc cập nhật mỗi cấu hình dưới đây đúng một lần:

```dotenv
RETAILOPS_API_ENABLED=true
RETAILOPS_API_MODEL=meta/muse-spark-1.3-contributor
RETAILOPS_API_DAILY_TURN_LIMIT=20
OPENROUTER_API_KEY=YOUR_ACTUAL_OPENROUTER_KEY
```

Thay placeholder bằng key thật **trong terminal riêng**, không commit file hoặc
gửi key qua chat. API model phải thuộc hai model được liệt kê phía trên; key/model
sai định dạng sẽ khiến cấu hình startup bị từ chối. Đặt lại API_ENABLED=false nếu
chưa cấu hình đủ. Sau đó:

```bash
sudo chmod 600 /opt/retailops/api.env
cd /opt/retailops
sudo docker compose --project-name retailops-api --env-file deployed.env -f compose.api.yaml up -d --no-build --pull never --force-recreate --wait --wait-timeout 60
```

Tải lại trang và đăng nhập. Chọn **API · OpenRouter**, rồi gửi `hello` và
`Cho tôi thông tin đơn O-101`. Chi tiết phải ghi `openrouter`, đúng model API và
công cụ thực tế; không hiển thị giả digest Qwen/Ollama cho lượt dùng API.
Muốn trở lại Colab, chọn **Custom model · Colab/Ollama**.

Muốn tắt API, đặt `RETAILOPS_API_ENABLED=false` và tạo lại container. Backend
không tự đổi từ custom sang API khi Colab ngắt, hoặc từ API sang model khác khi
hết tín dụng. Chưa có quyền truy cập/key thì API vẫn là tùy chọn chưa cấu hình.

## Giới hạn chi phí và dữ liệu

- Mặc định toàn bộ ứng dụng có **20 lần thử chat API/ngày UTC**, lưu trong SQLite
  qua restart. Cấp chỗ trước khi gọi mạng; lần lỗi/timeout vẫn tính vì có thể đã bị
  nhà cung cấp tính phí. Gửi lại request đã hoàn tất còn được lưu không tính lại.
  Đổi conversation không đặt lại hạn mức. Custom model không dùng hạn mức API này.
- Mỗi lần thử giữ giới hạn agent 4 lần gọi model/8 công cụ; API giới hạn 2.048
  output tokens/lần gọi, có bao gồm reasoning tính phí. Hạn mức lượt **không phải
  trần chi tiêu USD**; nên đặt thêm hạn mức cho API key tại nhà cung cấp.
- Chỉ chạy model API được chọn; không có model fallback, web-search plugin hoặc
  công cụ ghi giao dịch. Công cụ vẫn kiểm tra quyền; hủy phải qua UI xác nhận.
- Contributor cho phép prompt/output được dùng cải thiện sản phẩm Meta. Giao diện
  nêu điều này khi chọn API; chỉ sử dụng dữ liệu giả lập, không nhập dữ liệu khách
  thật. [Thông tin Muse Spark Contributor](https://openrouter.ai/meta/muse-spark-1.3-contributor)
- API key và endpoint không xuất hiện trong metadata giao diện. Browser chỉ gửi
  ID `custom` hoặc `api` khi tạo conversation; không được tự truyền model, URL,
  API key hoặc danh tính khách. Provider của một conversation không thay đổi.
- Tool call IDs và khối reasoning do provider trả về được giữ trong bộ nhớ của
  đúng một lượt để trả kết quả công cụ đúng giao thức. Chúng không được ghi vào
  SQLite, business trace hay UI. Chỉ nội dung hội thoại/công cụ thông thường nằm
  trong lịch sử. Chi phí hiển thị là số do API báo, chỉ khi đủ dữ liệu; lỗi mạng
  không được coi là lượt miễn phí.

## Kiểm chứng và phạm vi

```bash
python -m unittest discover -s tests -v
node tests/test_provider_selector.js
python scripts/build_agent_notebook.py --check
```

97 test Python kiểm tra adapter OpenRouter bằng phản hồi giả lập, tool ID/reasoning
roundtrip, lịch sử tách nguồn/khách, không tự fallback, hạn mức/retry qua restart,
định dạng request, lỗi xác thực/tín dụng, và các hợp đồng nghiệp vụ hiện có.
Test JavaScript chạy script giao diện với DOM giả để kiểm tra khóa selector,
chuyển conversation và giữ phiên cũ khi lỗi; đây không phải kiểm tra trình duyệt thật.

Không thực hiện cuộc gọi API trả phí trong lần phát triển này. Tính tương thích và
chất lượng Muse Spark thật cần xác nhận bằng lần gọi có key của chủ demo. Bản này
chỉ thêm lựa chọn model; **web vẫn dùng localhost/SSM**. HTTPS public, phiên khách
riêng và thay HTTP server demo nằm trong bước triển khai web tiếp theo.

Tài liệu giao thức:
[Chat API](https://openrouter.ai/docs/api/reference/overview),
[Tool calling](https://openrouter.ai/docs/guides/features/tool-calling),
[Reasoning](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).
