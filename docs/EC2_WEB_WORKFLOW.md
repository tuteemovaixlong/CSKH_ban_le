# Quy trình sử dụng: web HTTPS trên EC2

Quyết định ngày 2026-09-08: dùng web HTTPS hiện có trên EC2 làm giao diện tương tác duy nhất. VS Code dùng để sửa code và Git; không cần khởi động API, tạo token hoặc dựng database trên Windows để sử dụng ứng dụng.

## Phân chia môi trường

| Nơi | Công việc |
| --- | --- |
| Trình duyệt | Mở web EC2, đăng nhập tài khoản demo, chat và thao tác đơn |
| VS Code / Windows | Sửa code, xem diff, commit và push nhánh |
| GitHub Actions | Chạy CI, kiểm tra image, triển khai commit trên main |
| EC2 / Systems Manager | Vận hành Caddy, web, PostgreSQL; chạy live smoke và full test |
| Colab | Chạy model khi chọn Custom; không phải web server nghiệp vụ |

Không cần chạy `python retailops_api.py` trên laptop. Không cần sinh `RETAILOPS_DEMO_TOKEN` hoặc dùng `Set-Clipboard` cho quy trình này. PR #26 về localhost auto-login đã đóng **không merge**; nhánh được giữ để có thể tham khảo/khôi phục, không dùng để triển khai.

## Mở ứng dụng

Địa chỉ ghi nhận lúc kiểm tra ngày 2026-09-08 là `https://retailops.54-221-116-13.sslip.io`. Đây là snapshot, không phải địa chỉ được bảo đảm cố định.

Địa chỉ cấu hình hiện hành nằm trên EC2. Trong Session Manager, chỉ đọc biến không bí mật này:

```bash
sudo grep '^RETAILOPS_PUBLIC_ORIGIN=' /opt/retailops/public.env
```

Mở phần URL sau dấu `=` bằng trình duyệt. Không mở localhost hoặc file `web/index.html` trực tiếp.

Web public vẫn dùng tài khoản/membership và cookie phiên. Không dùng token local cho web EC2, không đưa credential vào URL, Git hoặc log. Không cần cấp lại credential mỗi lần sửa code. Credential đã chia sẻ trong chat/log cần được quản trị viên thu hồi hoặc thay mới. Không bỏ xác thực public hoặc xác nhận thao tác hủy đơn để giải quyết bất tiện local.

## Sửa code và triển khai

Sửa trên nhánh tính năng, thêm regression test ở lớp phù hợp, tạo PR và đợi CI xanh trước khi merge. Push nhánh không triển khai EC2. Workflow `deploy-ec2.yml` chạy trên main, kiểm tra source/image rồi publish ECR, triển khai qua SSM và chạy live smoke khi public web đã được cấu hình.

CI main và deployment là các workflow riêng, không mặc định hiểu rằng deployment đợi toàn bộ workflow CI main. Vì vậy vẫn phải review PR và kiểm tra CI trước merge.

Không chỉnh source trực tiếp trong container đang chạy và không copy code thủ công lên EC2. Cấu hình runtime/credential là cấu hình của môi trường, không commit vào repository.

## Kiểm tra tự động trên EC2

Trong Session Manager:

```bash
sudo python3 /opt/retailops/live-e2e.py --mode smoke
```

Smoke không gọi model. Nó kiểm tra image, HTTPS, đăng nhập/phiên, API đơn và đăng xuất; có tạo danh tính demo tạm và dọn credential sau test.

Full test chỉ chạy có chủ đích, khi model đã sẵn sàng:

```bash
sudo python3 /opt/retailops/live-e2e.py --mode full
```

Full test gọi model, thay đổi dữ liệu tenant synthetic riêng và restart web để kiểm tra persistence. Không chạy trong lúc người khác đang demo hoặc một deployment đang diễn ra. Kiểm tra `selected_provider` trong report để biết thực tế test đã dùng Custom hay API; không suy ra Colab đã được dùng chỉ từ chữ PASS.

Report nằm trong `/opt/retailops/e2e-reports/`. PASS của smoke không thay thế full test, và full test không phải benchmark chất lượng AI trên toàn bộ dataset. Runner hiện dùng HTTP qua Caddy; không được gọi đây là Playwright/browser automation. Nó dùng `curl --resolve ...:127.0.0.1`, nên không chứng minh DNS và truy cập Internet từ máy bên ngoài hoạt động.

## Khởi động lại sau khi stop/start EC2

AWS có thể cấp public IPv4 mới sau stop/start nếu không dùng Elastic IP. Với hostname chứa IP, phải đối chiếu IP hiện tại trong EC2 Console rồi cập nhật **cả hai** biến trong `public.env`:

- `RETAILOPS_PUBLIC_HOST`: hostname, không có scheme;
- `RETAILOPS_PUBLIC_ORIGIN`: `https://` cộng chính hostname đó, không có dấu `/` cuối.

Sau khi đổi cấu hình, recreate web/Caddy theo runbook public, kiểm tra HTTPS rồi chạy smoke. Không tắt kiểm tra Host/Origin và không bỏ xác minh TLS để làm test xanh.

Elastic IP hoặc domain/DNS được quản lý ổn định là cải tiến riêng cần phê duyệt cấu hình/chi phí; lần dọn này không tạo IP, domain, load balancer hay EC2 mới.

Tài liệu AWS: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-instance-addressing.html

## Dọn phần dư đã thực hiện trên EC2

Kiểm tra trước khi dọn xác nhận Caddy reverse-proxy tới `web:8000`, không dùng API cũ `127.0.0.1:8080`.

| Thành phần | Xử lý |
| --- | --- |
| `retailops-api-api-1` | Đã stop và đổi restart policy thành `no`; giữ container để rollback |
| `crazy_wozniak` | Đã xóa container trạng thái Created, không có mount và chưa có process chạy |
| `retailops-web-web-1` | Giữ nguyên container và image; không recreate |
| `retailops-web-caddy-1` | Giữ nguyên |
| `retailops-web-postgres-1` | Giữ nguyên, không xóa volume/data |

Sau khi dọn chỉ còn ba service public stack chạy. HTTPS `/healthz` trả 200, PostgreSQL backend và protocol `retailops-agent-v2`.

Bằng chứng thực thi qua SSM:

- Command ID: `2f6f9b8f-387f-4091-b544-0114fa672d98`.
- Cleanup report: `/opt/retailops/e2e-reports/EC2_WEB_ONLY_CLEANUP_20260908T030312Z.json`.
- Smoke mới: `/opt/retailops/e2e-reports/LIVE_SMOKE_20260908T030313Z.json`, `LIVE_E2E_SMOKE_OK`.
- Runtime image được giữ nguyên: `sha256:eb57d2a2f021d019d6e58703342bc087fbdf2796bec8577ad0699604b0b69d04` của PR #25.
- Full report từ trước lần dọn: `LIVE_FULL_20260908T015447Z.json`, PASS. Không chạy lại full/model trong lần dọn này.

Không xóa `api.env`: public Compose vẫn đọc file này. Không xóa `/opt/retailops/artifacts`: đây là bind mount còn được web sử dụng và có thể chứa dữ liệu/bằng chứng cũ. Giữ `postgres-secrets/`, các volume PostgreSQL/Caddy, cấu hình rollback và báo cáo test. Không chạy `docker compose down -v`, `docker system prune --volumes` hoặc xóa hàng loạt database.

Nhánh PR #26, image cũ và container API đã stop là bản dự phòng, không phải tính năng đang sử dụng. Xóa vĩnh viễn chúng chỉ sau khi review retention/backup; không coi tên file có chữ `api` hoặc `local` là đủ để kết luận thừa.

## Mã tương thích và dữ liệu máy phát triển

`retailops_api.py` và adapter private còn được regression tests import. Chúng được giữ để không phá CI, nhưng không còn là bước khởi động dành cho người dùng. Không cần sửa auth, regenerate notebook của PR #26 hoặc tiếp tục xử lý login local.

Thư mục runtime local chưa được Git theo dõi như `artifacts/` và `artifacts-business-local/` được bỏ qua bằng gitignore, không cần xóa dữ liệu để làm `git status` sạch. Chỉ commit kết quả evaluation đã được kiểm tra không chứa credential/dữ liệu nhạy cảm; kết quả runtime mặc định nên nằm trong artifact/report storage.

Bước phát triển tiếp theo là Evaluation Runner & Dashboard: lưu kết quả, tính metric, vẽ biểu đồ và đính kèm artifact; không tạo thêm giao diện localhost song song.
