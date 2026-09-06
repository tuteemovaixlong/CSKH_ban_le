# RetailOps: chạy giao diện với backend thật trên dữ liệu giả lập

## Phạm vi bản 0.2

Giao diện được phục vụ cùng API. Đơn hàng và nhật ký nằm trong SQLite tại
`artifacts/business.sqlite3`; tải lại trang hoặc tạo lại container không khôi phục
đơn đã hủy. Model chỉ trích xuất ý định, không có quyền gọi thao tác hủy.

Đây là ứng dụng demo riêng cho một khách mẫu, không phải triển khai công khai.
Mã truy cập ngẫu nhiên được máy chủ ánh xạ sang `C-001`; người gọi không được
chọn `customer_id`. Chưa có đăng ký, tài khoản cửa hàng thật hoặc cổng thanh toán.
HTTP server thư viện chuẩn chỉ dùng trên localhost/SSM. Trước khi public cần
server production, TLS, xác thực người dùng thực, giới hạn lưu lượng và vận hành.

| Thành phần | Có cần Colab chạy? |
|---|---|
| Xem/tra đơn bằng nút | Không |
| Chọn lý do, tạo đề xuất, xác nhận hủy | Không |
| Lưu dữ liệu và xem nhật ký | Không |
| Nhập câu chat để model hiểu yêu cầu | Có, khi bật kết nối inference |

Hai mã truy cập khác nhau: `RETAILOPS_DEMO_TOKEN` dùng cho trình duyệt → API;
`RETAILOPS_INFERENCE_TOKEN` dùng cho API → proxy Colab. Không dùng chung chúng.
Token demo chỉ giữ trong bộ nhớ trang; tải lại trang cần đăng nhập lại.

## 1. Chạy ngay trên Windows trước khi triển khai

Cần Python 3.11 trở lên và Git. Trong PowerShell tại thư mục repository:

```powershell
git fetch origin
git switch --track origin/feat/business-api-ui
python -m unittest discover -s tests -v
$env:RETAILOPS_DEMO_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(32))"
$env:RETAILOPS_MODEL_ENABLED = "false"
$env:RETAILOPS_API_PORT = "8000"
$env:RETAILOPS_OUTPUT = Join-Path $PWD "artifacts-business-local"
$env:RETAILOPS_DEMO_TOKEN | Set-Clipboard
python retailops_api.py
```

Nếu nhánh đã tồn tại, dùng `git switch feat/business-api-ui`, rồi
`git pull --ff-only`. Commit/stash công việc đang làm trước khi đổi nhánh.

Mở [giao diện local](http://localhost:8000), dán mã từ clipboard vào ô truy cập.
Mã này chỉ xuất hiện trong phiên PowerShell của bạn; không gửi nó qua chat.
Giữ terminal chạy; Ctrl+C để dừng. Thư mục dữ liệu local đã được gitignore.

## 2. Đưa image mới lên EC2

Sau khi review và merge PR vào `main`, chờ CI và workflow
`Deploy baseline runner to EC2` thành công. CD vẫn chỉ kích hoạt image;
chưa tự khởi động hay cập nhật service API. Điều này giữ nguyên quy trình baseline.

Mở `deploy/start-business-api.sh` từ phiên bản đã merge, copy **toàn bộ nội dung**
vào EC2 → retailops-dev → Connect → Session Manager. Script tự chạy qua `sudo`.

Script lấy cấu hình Compose từ đúng image digest trong `/opt/retailops/deployed.env`,
tạo mã demo nếu chưa có và khởi động API. Chạy lại không đổi token hoặc dữ liệu.
Kết quả cuối:

```text
BUSINESS_API_READY
```

API chỉ bind `127.0.0.1:8080` trên EC2. Không mở cổng 8080 ra Internet.
Nếu script báo không tìm thấy `/app/deploy/compose.api.yaml`, CD chưa kích hoạt
image của PR này; kiểm tra đúng workflow và commit trước khi chạy lại.

Sau mỗi CD mới, chạy lại script này để cập nhật API sang image vừa kích hoạt.
Nếu không chạy lại, API tiếp tục phục vụ image cũ. Phiên bản baseline và API
có thể kiểm tra bằng `docker compose ... images` theo cấu hình tương ứng.

## 3. Mở giao diện EC2 trên máy Windows

Trên **máy Windows**, cài [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
và [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html).
Mở lại PowerShell sau cài đặt. Với AWS CLI >= 2.32.0, đăng nhập bằng trình duyệt:

```powershell
aws login --profile retailops-dev --region us-east-1
aws sts get-caller-identity --profile retailops-dev --region us-east-1
```

Chọn tài khoản AWS đang dùng cho dự án. Kiểm tra account là `629089420698`.
Danh tính đăng nhập cần quyền đăng nhập CLI và mở phiên SSM. Tài khoản `cc123`
đã có AdministratorAccess trong cấu hình trước; nếu quyền đã thay đổi, xem
[hướng dẫn AWS login](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html).
Không lấy credential của EC2 để chép sang Windows.

Chạy lệnh sau trong PowerShell và giữ terminal mở:

```powershell
aws ssm start-session --profile retailops-dev --region us-east-1 --target i-0fd116d8927d0e412 --document-name AWS-StartPortForwardingSession --parameters portNumber=8080,localPortNumber=8080
```

Mở [giao diện EC2 qua tunnel riêng](http://localhost:8080).
Đây là cơ chế [SSM port forwarding](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-sessions-start.html#sessions-start-port-forwarding).
Nó cần CLI trên máy bạn, không phải terminal Session Manager trong browser.

Để lấy mã demo, trong terminal **EC2 Session Manager**, chạy:

```bash
sudo sed -n 's/^RETAILOPS_DEMO_TOKEN=//p' /opt/retailops/api.env
```

Dán mã vào ô đăng nhập của ứng dụng. Không chia sẻ output chứa mã.
Đóng tunnel bằng Ctrl+C trong PowerShell khi xong. Backend vẫn chạy trên EC2.

## 4. Các bước bấm thử trước khi dùng model

1. Tra `O-101`: trạng thái Chờ xử lý.
2. Bấm yêu cầu hủy, chọn lý do, mở xác nhận rồi chọn **Giữ đơn hàng**:
   trạng thái giữ nguyên, nhật ký ghi đã bỏ đề xuất.
3. Tạo yêu cầu mới, chọn lý do và xác nhận: trạng thái chuyển Đã hủy.
4. Tải lại trang, nhập lại token: đơn vẫn Đã hủy; nhật ký vẫn còn.
5. Thử hủy `O-102`: backend từ chối vì đơn đã giao.
6. Gửi một câu chat khi model tắt: thông báo model chưa kết nối, không giả câu trả lời AI.

Test tự động còn kiểm tra truy cập đơn `O-202` thuộc `C-002`, gửi lại xác nhận,
hai xác nhận đồng thời, đơn đổi trạng thái sau khi tạo đề xuất và đề xuất hết hạn.
Không có API reset dữ liệu. Muốn demo lại nên dùng một thư mục dữ liệu thử mới
ở local; không xóa database EC2 đang cần giữ để minh chứng.

## 5. Nối Colab khi thực hiện phiên thử tương tác

Bạn đã xác nhận Qwen chạy trên L4 và đã có baseline. Không cần giữ GPU bật
trong khi cài API. Trước khi dừng Colab hãy tải ZIP báo cáo; dữ liệu runtime
Colab có thể mất khi kết thúc phiên. Colab không đảm bảo luôn cấp cùng GPU
hay thời gian chạy; tham khảo [FAQ Colab](https://research.google.com/colaboratory/faq.html).

Dùng notebook tự chứa của PR #1. PR API này không sửa prompt, model hoặc
evaluator, và không yêu cầu merge PR #1 để chạy backend. Notebook baseline cũ
trên main vẫn cần ZIP nếu PR #1 chưa merge.

Khi muốn thử toàn tuyến:

1. Chạy lại source, runtime và một câu thử trong notebook. Xác nhận model đã nạp.
2. Trong Colab Secrets, tạo `NGROK_AUTHTOKEN` từ tài khoản ngrok và
   `RETAILOPS_INFERENCE_TOKEN` là chuỗi ngẫu nhiên URL-safe 32–128 ký tự.
   Cấp quyền đọc cho notebook. Không in token vào output.
3. Trong ô ngrok của notebook, đặt `ENABLE_REMOTE_EXPERIMENT = True`, rồi chạy.
   Đây chỉ là thử nghiệm có người theo dõi trong phiên Colab, không dùng làm server 24/7.
4. Ô đó in `RETAILOPS_MODEL_URL` và `RETAILOPS_ALLOWED_HOST`.
   Trên EC2 mở `sudo nano /opt/retailops/inference.env`, điền hai giá trị này,
   model `qwen3.5:4b` và cùng inference token. Giữ file chỉ root đọc được.
5. Mở `sudo nano /opt/retailops/api.env`, đổi `RETAILOPS_MODEL_ENABLED=true`.
   Giữ token demo riêng đã có. Chạy lại `start-business-api.sh` để Compose
   tạo lại container với môi trường mới.
6. Đăng nhập lại giao diện. Gửi “Kiểm tra đơn O-101”. Nếu Colab tắt hoặc
   endpoint sai, giao diện báo lỗi; các nút thao tác vẫn dùng được.

Muốn thử yêu cầu hủy thành công sau khi `O-101` đã hủy ở bước trước, dùng
database thử mới ở local. Với dữ liệu EC2 hiện tại, model vẫn hiểu yêu cầu nhưng
backend phải từ chối hủy đơn đã hủy. Đây là kết quả mong đợi.

URL ngrok có thể thay đổi khi tạo tunnel mới. Sau khi kết thúc thử nghiệm,
đặt `RETAILOPS_MODEL_ENABLED=false` và chạy lại script; tải kết quả Colab rồi
Disconnect and delete runtime. Không có tác vụ tự giữ Colab sống hoặc mua compute.

## Hợp đồng API

Tất cả `/api/*` cần `Authorization: Bearer <demo-token>`. POST cần JSON.
Không bật CORS; giao diện được phục vụ cùng origin với API.

| Method / route | Mục đích |
|---|---|
| GET `/healthz` | Kiểm tra API/database, không gọi model |
| GET `/api/session` | Khách mẫu và trạng thái đã cấu hình model |
| GET `/api/orders` | Danh sách đơn thuộc danh tính token |
| GET `/api/orders/{id}` | Tra đơn, kiểm tra chủ sở hữu, ghi nhật ký |
| GET `/api/events` | 30 sự kiện gần nhất của khách hiện tại |
| POST `/api/chat` | `{"text":"..."}`; model chỉ đề xuất luồng |
| POST `/api/cancellation-proposals` | `order_id`, `order_version`, `cancel_reason` do người dùng chọn |
| POST `/api/cancellation-proposals/{id}/confirm` | `{"confirmed":true}` và header `Idempotency-Key` |
| POST `/api/cancellation-proposals/{id}/dismiss` | `{}`; bỏ đề xuất chưa thực hiện |

Đề xuất hết hạn sau 10 phút. Xác nhận kiểm tra lại chủ sở hữu, trạng thái và
phiên bản đơn. Cập nhật đơn, kết quả idempotency và audit cùng giao dịch SQLite.
Retry cùng proposal/key trả kết quả đã lưu. Khác key hoặc khác proposal không
thực hiện lại giao dịch. Model không tạo đề xuất database; UI phải chọn lý do.

## Xác minh và giới hạn

57 tests đã qua ở môi trường phát triển, gồm 41 test baseline và 16 test API.
Kiểm tra giao tiếp HTTP chạy với server thật trên loopback và database tạm;
inference trong test dùng mock. JavaScript và shell đã được kiểm tra cú pháp.
Docker build/packaged tests được workflow CI thực hiện; môi trường phát triển
của trợ lý không có Docker. Chưa chạy phiên EC2 → Colab thật hoặc browser QA
trong lần sửa này. Điểm baseline 83,3% của model không phải điểm thành công
nghiệp vụ của API mới.
