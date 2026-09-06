# RetailOps 0.5 — web HTTPS chạy trên EC2

Web/API chạy trên EC2; Caddy nhận HTTPS và chuyển request tới Waitress trong mạng
Docker riêng. Trình duyệt khách không cần SSM. Khi dùng API đã cấu hình, laptop và
Colab có thể tắt. EC2 vẫn phải ở trạng thái **Running** và API cần còn hạn mức/tín dụng.

Bản này dành cho demo được mời, sử dụng dữ liệu giả lập. Mỗi khách nhập mã mời chung
để nhận cookie `Secure`, `HttpOnly`, `SameSite=Strict` và bộ đơn riêng. Không dùng
mã truy cập của bản SSM làm phiên nghiệp vụ trên web công khai.

## 1. Đưa image mới lên EC2

Merge PR chứa bản 0.5, chờ **CI** và **Deploy baseline runner to EC2** cùng thành công.
CD cập nhật `/opt/retailops/deployed.env`; chưa bật web công khai chỉ bằng việc merge.

## 2. Cho phép truy cập HTTP/HTTPS

AWS Console → EC2 → Instances → `retailops-dev` (`i-0fd116d8927d0e412`)
→ Security → mở Security group → Edit inbound rules. Thêm:

| Type | Protocol | Port | Source |
|---|---|---|---|
| HTTP | TCP | 80 | `0.0.0.0/0` |
| HTTPS | TCP | 443 | `0.0.0.0/0` |

Lưu. Không cần mở 8000, 8080, 22 hoặc cổng model. Cấu hình mới không công khai các
cổng này. Nếu máy có UFW đang active, kiểm tra `sudo ufw status` và cho phép
`sudo ufw allow 80/tcp`, `sudo ufw allow 443/tcp`. Không bật/tắt hoặc reset firewall.

Đây là mở cổng cho web công khai theo yêu cầu; không cấp thêm IAM hoặc thuê GPU.
[Yêu cầu HTTPS của Caddy](https://caddyserver.com/docs/automatic-https#overview).

## 3. Chạy bộ cài HTTPS trên EC2

Mở [deploy/start-public-web.sh](../deploy/start-public-web.sh), copy toàn bộ file,
dán vào **EC2 → Connect → Session Manager**, nhấn Enter. Không chạy file này trong
PowerShell Windows. Script tự đọc IPv4 public bằng IMDSv2, kiểm tra đúng instance,
kiểm tra DNS và lấy file triển khai từ image digest đã chạy CD.

Mặc định tạo địa chỉ dạng `https://retailops.12-34-56-78.sslip.io` (ví dụ, không phải
link của bạn). Không cần đăng ký tên miền. `sslip.io` là dịch vụ DNS bên ngoài;
chứng chỉ TLS được cấp riêng cho máy bạn qua Caddy. [Tài liệu DNS/TLS](https://sslip.io/).
Nếu đã có tên miền riêng, trỏ bản ghi A tới IPv4 của EC2 rồi điền `PUBLIC_HOSTNAME`
ở đầu script trước khi chạy. Không thêm `https://` hoặc dấu `/` vào biến hostname.

Script cài `/opt/retailops/compose.public.yaml`, `Caddyfile`, `public.env`, chạy
Compose project **retailops-web**, giữ chứng chỉ trong volume `caddy_data`. Script
không in mã mời/API key và không gọi inference. Khi chạy lại, mã mời/cấu hình custom
được giữ nguyên; cấu hình HTTPS cũ được sao lưu trước khi thay. Dữ liệu SSM cũ trong
`artifacts/business.sqlite3` không bị thay đổi.

Kết quả cần có:

```text
PUBLIC_HTTPS_READY
Open https://retailops.<IP-của-bạn>.sslip.io
```

Chỉ dòng `PUBLIC_HTTPS_READY` xác nhận curl đã kiểm tra chứng chỉ công khai hợp lệ
và health của web. Container Healthy đơn thuần chưa xác nhận TLS. Script kiểm tra
TLS trên EC2; bước tiếp theo kiểm tra đường truy cập từ Internet.

## 4. Mở link và thử từ thiết bị khác

Đọc mã mời **trong terminal riêng của bạn**, không gửi lại vào chat/log hỗ trợ:

```bash
sudo sed -n 's/^RETAILOPS_PUBLIC_INVITE_TOKEN=//p' /opt/retailops/public.env
```

Mở đúng link script in, nhập mã mời. Đây là mã mời mới, khác mã bản localhost.
Thử bằng điện thoại dùng 4G/5G; đóng PowerShell SSM vẫn phải mở web và tra đơn được.
Chia sẻ link và mã mời cho nhà tuyển dụng, không chia sẻ inference token/API key.

## 5. Bật API để chat khi Colab tắt

Trong `sudo nano /opt/retailops/api.env`, giữ cấu hình cũ và thêm/cập nhật:

```dotenv
RETAILOPS_API_ENABLED=true
RETAILOPS_API_MODEL=meta/muse-spark-1.3-contributor
RETAILOPS_API_DAILY_TURN_LIMIT=20
OPENROUTER_API_KEY=YOUR_ACTUAL_OPENROUTER_KEY
```

Thay placeholder ngay trong terminal riêng. Không bật API khi chưa có key thật;
cấu hình thiếu hoặc sai định dạng sẽ khiến web từ chối khởi động. Mặc định API tắt.
Nếu chưa có key, web vẫn có luồng tra/hủy đơn trực tiếp; chat API chưa hoạt động.
Muse Spark ở bản này được gọi qua **OpenRouter**, chưa phải Meta API trực tiếp.

Sau khi sửa:

```bash
cd /opt/retailops
sudo chmod 600 api.env inference.env public.env
sudo docker compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml up -d --no-build --pull never --force-recreate --wait --wait-timeout 60
```

Tải lại web: API được chọn mặc định khi đã bật. Gửi `hello`, `Tra đơn O-101` và
kiểm tra nguồn `openrouter`, model và công cụ thực tế trong chi tiết. Sau khi lượt
API thật thành công, tắt laptop/Colab và thử lại từ điện thoại để xác nhận toàn bộ.

Custom model mặc định tắt ở web công khai để không phụ thuộc Colab cũ. Muốn bật,
đặt `RETAILOPS_PUBLIC_CUSTOM_ENABLED=true` trong `public.env`, kiểm tra URL/token
trong `inference.env`, rồi tạo lại container web bằng lệnh trên. Chỉ chọn custom
khi Colab đang chạy. Web không tự chuyển nguồn khi model ngắt.

## Phiên, dữ liệu và giới hạn

- Cookie có hiệu lực 8 giờ và được kiểm tra từ database; qua restart vẫn dùng được.
  Tải lại trang giữ đơn và nhật ký của khách, mở một cuộc trò chuyện mới. Đóng phiên
  thu hồi cookie phía server; lần đăng nhập sau tạo bộ đơn mới. Hết hạn không truy cập
  lại được. Dữ liệu hết hạn được dọn khi có đăng nhập mới hoặc khởi động web.
- Tối đa 50 phiên còn hiệu lực; hạn chế 15 lần đăng nhập/phút cho toàn bộ demo và
  60 request API/phút/phiên. Giới hạn lưu trong SQLite, không reset khi restart.
- Tất cả khách chia sẻ 20 lần thử chat API/ngày UTC theo mặc định; đổi phiên không
  reset. Lần lỗi vẫn có thể bị tính phí nên vẫn tính lượt. Quota public lưu riêng
  với ứng dụng SSM của chủ dự án. Đặt thêm giới hạn chi tiêu cho key ở OpenRouter.
- Hủy chỉ xảy ra khi người dùng chọn lý do, xem lại và xác nhận. Khách A không đọc,
  hủy hoặc xem lịch sử của khách B. Dữ liệu cũ của chủ dự án không được đưa lên web.
- Contributor có thể dùng prompt/output để cải thiện sản phẩm Meta; UI ghi rõ điều
  này. Chỉ dùng dữ liệu giả lập. [Thông tin model](https://openrouter.ai/meta/muse-spark-1.3-contributor).
- Rotate mã mời bằng một giá trị ngẫu nhiên mới trong `public.env` rồi tạo lại web
  sẽ thu hồi các phiên public cũ. Không sửa token qua form/chat của khách.

## Duy trì, cập nhật và xử lý lỗi

Caddy và web dùng `restart: unless-stopped`; thoát terminal không dừng container.
Chứng chỉ tự gia hạn nếu DNS vẫn trỏ đúng EC2 và cổng 80/443 vẫn truy cập được.
EC2, IPv4, lưu trữ và API vẫn chịu phí theo tài khoản của bạn; DNS miễn phí không
có nghĩa toàn bộ hệ thống miễn phí. Script không cấp phát thêm máy hoặc Elastic IP.

Nếu Stop/Start EC2 làm đổi IPv4, địa chỉ miễn phí cũ sẽ không theo IP mới. Chạy lại
script với `PUBLIC_HOSTNAME="retailops.IP-MỚI-VỚI-DẤU-GẠCH.sslip.io"`, hoặc cập nhật
DNS của tên miền riêng. Reboot không phải Stop/Start. Không xóa volume chứng chỉ để
thử lại vì có thể làm phát sinh cấp chứng chỉ lặp.

Nếu có `PUBLIC_TLS_PENDING`, kiểm tra SG, UFW, DNS và log:

```bash
cd /opt/retailops
sudo docker compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml ps
sudo docker compose --project-name retailops-web --env-file deployed.env --env-file public.env -f compose.public.yaml logs --tail 60 caddy web
```

Trường hợp CA hoặc dịch vụ DNS giới hạn cấp chứng chỉ cần xử lý theo log; không
bỏ qua xác minh TLS hoặc chấp nhận cảnh báo chứng chỉ để coi là hoàn tất.

Sau mỗi lần CD, chạy lại bộ cài để lấy Compose/Caddyfile mới từ đúng image, hoặc
lệnh `up ... --force-recreate` phía trên nếu cấu hình triển khai không đổi. CD chưa
tự khởi động lại web public để tránh công khai khi chủ dự án chưa hoàn tất cấu hình.

Muốn dừng web public, chạy cùng lệnh Compose nhưng thay `up ...` bằng `stop`.
Không dùng `down -v` vì sẽ xóa volume chứng chỉ. Bản SSM vẫn hoạt động riêng.

## Kiểm chứng bản sửa

Bộ test kiểm tra business logic, phiên/cookie, nguồn model, hai khách độc lập,
quota qua restart và HTTP thật qua Waitress. CI còn khởi động Caddy + Waitress
trong Docker với CA **chỉ dành cho test**, xác minh TLS, chuyển HTTP sang HTTPS,
cookie, kiểm tra Origin và logout. CI không xin chứng chỉ công khai và không gọi
API tính phí/GPU. Chứng chỉ thật, inbound AWS và inference API thật phải được xác
nhận trên EC2 bằng các bước trên.
