# INCIDENT & RECOVERY REPORT — RETAILOPS — 2026-09-21

> **Ngày ghi nhận:** 2026-09-21 (GMT+7)  
> **Cửa sổ sự cố chính:** tối 2026-09-20 đến rạng sáng 2026-09-21  
> **Repository:** `tuteemovaixlong/CSKH_ban_le`  
> **Nhánh:** `main`  
> **HEAD sau khi xử lý:** `d3ca3a6ff6fa106af973d4c44c6ee955bce20f13`  
> **EC2:** `retailops-dev` / `i-0fd116d8927d0e412`  
> **Public IPv4 hiện tại:** `98.84.139.124` (dynamic, không dùng Elastic IP)  
> **Web:** https://retailops.98-84-139-124.sslip.io  
> **Admin:** https://admin-retailops.98-84-139-124.sslip.io

Tài liệu này tổng hợp toàn bộ chuỗi lỗi, thay đổi code, thao tác hạ tầng và xác minh được thực hiện trong phiên xử lý tối 2026-09-20 / rạng sáng 2026-09-21. Mục tiêu là để lần sau có thể đọc một file duy nhất và hiểu vì sao hệ thống lỗi, đã sửa gì, cấu hình EC2 hiện tại ra sao, và cần vận hành thế nào.

---

## 1. Tóm tắt điều hành

Trong phiên này có ba nhóm vấn đề chính:

1. **CI/CD deploy sang EC2 liên tục đỏ** dù Docker image push lên ECR thành công.
2. **EC2 hết dung lượng root**, làm containerd không giải nén được image và về sau làm SSM Agent không khởi động được remote shell.
3. **Google OAuth đăng nhập thành công nhưng UI quay lại màn hình login**, nguyên nhân cuối cùng là JavaScript frontend crash trước khi `openSession()` được gọi.

Ngoài ra CI về cuối phiên đỏ vì **generated Colab notebook bị stale** so với source hiện tại.

Kết quả cuối cùng:

- EC2 đã nâng từ **t3.medium → t3.large**.
- Root EBS đã nâng từ **20 GiB → 50 GiB**.
- Partition root đã mở rộng từ khoảng **19 GiB → 49 GiB**.
- Filesystem `/` hiện khoảng **48 GiB usable**, còn khoảng **43 GiB free**, mức dùng khoảng **11%** tại thời điểm kiểm tra.
- RAM usable khoảng **7.6 GiB**.
- Docker, PostgreSQL, web, admin và Caddy đều chạy lại ổn định.
- SSM Agent Snap hoạt động.
- Public IP sau Stop/Start đổi từ `54.226.168.35` sang `98.84.139.124`; `scripts/update_ec2.py --auto-ip` đã cập nhật host/origin/Caddy.
- Deploy EC2 **#140 và #141 thành công** sau khi hạ tầng được phục hồi và frontend bug được sửa.
- Notebook generated đã được đồng bộ lại; full CI configuration được kiểm tra lại thành công trên snapshot `main` đã đồng bộ.

---

## 2. Timeline sự cố và phục hồi

### 2.1. Deploy #135 — SSM document worker timeout

Run:

- **Deploy EC2 #135**
- Commit: `87494685d03cf3779bb1450fe297cfe4fcffb636`
- Image đã push thành công lên ECR.
- ECR digest được tạo thành công.
- Workflow fail ở bước SSM với thông báo dạng:

```text
document process failed unexpectedly:
ipc messaging received timeout signal
```

Điểm quan trọng: warning của Docker:

```text
WARNING! Your credentials are stored unencrypted in '/home/runner/.docker/config.json'
```

**không phải nguyên nhân fail**. Push ECR đã hoàn tất; lỗi nằm ở bước SSM thực thi lệnh trên EC2.

Fix được thêm:

- Commit `268c4745ce6a1f2c8656110adb8cb606c86d8b22`
- Message: `fix(deploy): retry transient SSM document worker timeout once`

Logic mới nhận diện lỗi transient của SSM document worker và retry một lần thay vì fail ngay.

### 2.2. Deploy #136–#137 — phát hiện root disk/containerd hết chỗ

Sau khi có retry, các run tiếp theo vẫn lỗi. Đến **Deploy #137**, log chỉ ra lỗi thực sự ở tầng host:

```text
no space left on device
/var/lib/containerd/...
```

Nghĩa là ECR không có vấn đề; image đã tải được nhưng containerd không còn đủ chỗ để extract layer.

Fix tiếp theo:

- Commit `d345eb0e08da03e6fc31acdcdd7f942fa3037646`
- Message: `fix(deploy): prune stale Docker data before EC2 image pull`

Thêm cleanup an toàn trước pull:

```bash
docker image prune -af
docker builder prune -af
```

Không dùng `--volumes` để tránh xóa PostgreSQL/Caddy persistent data.

### 2.3. Deploy #138–#139 — SSM fail trước khi remote shell chạy

Khi root disk đã từng chạm 100%, tình trạng nặng hơn: SSM command có thể fail **trước cả khi shell trên EC2 bắt đầu chạy**. Vì vậy cleanup nằm trong lệnh SSM cũng không thể tự cứu host nữa.

Các thay đổi:

- `9a08eece8b565e6436e371742745bac77103f774`  
  `fix(deploy): fail fast on EC2 disk pressure and prune releases`
- `dd867299b1ac48dc295d6f1d8e9c82f564f47e22`  
  `fix(deploy): classify empty SSM failure as worker startup failure`

Pipeline được bổ sung:

- preflight EC2 trước khi publish release tiếp theo;
- `docker image prune -af`;
- `docker builder prune -af`;
- vacuum journal;
- kiểm tra dung lượng root;
- fail fast nếu root còn dưới ngưỡng an toàn;
- cleanup release cũ sau rollout thành công;
- nhận diện trường hợp SSM status `Failed` nhưng stdout/stderr rỗng là lỗi worker/startup trước shell;
- retry worker failure một lần rồi báo rõ nguyên nhân thay vì che giấu.

Kết luận ở thời điểm này: **không thể tiếp tục chữa bằng GitHub Actions**, vì chính SSM không còn mở được remote shell trên host.

---

## 3. Thao tác trực tiếp trên EC2

### 3.1. Nâng root EBS 20 GiB → 50 GiB

Sau khi tăng volume trên AWS Console, EC2 thấy disk 50 GiB nhưng partition root vẫn chỉ 19 GiB:

```text
nvme0n1      50G
└─nvme0n1p1  19G  /
```

Filesystem lúc đó:

```text
/dev/root ext4 19G 4.9G 14G 27% /
```

Đã mở rộng partition và ext4 online:

```bash
sudo growpart /dev/nvme0n1 1
sudo resize2fs /dev/nvme0n1p1
```

Kết quả:

```text
nvme0n1      50G
└─nvme0n1p1  49G  /
```

```text
/dev/root ext4 48G 4.9G 43G 11% /
```

Như vậy nguyên nhân `no space left on device` đã được giải quyết ở tầng storage.

### 3.2. Nâng instance type t3.medium → t3.large

Instance được Stop → Change instance type → Start.

Cấu hình mới:

- **Instance type:** `t3.large`
- **vCPU:** 2
- **RAM:** 8 GiB danh nghĩa
- `free -h` ghi nhận khoảng **7.6 GiB usable**
- Tại thời điểm kiểm tra:
  - used khoảng 662 MiB
  - available khoảng 7.0 GiB
- **Swap:** 0 B

Không có yêu cầu tạo lại máy hoặc restore dữ liệu: EBS, Docker volumes, PostgreSQL data, IAM role và Security Group được giữ nguyên qua Stop/Start.

### 3.3. Public IP thay đổi sau Stop/Start

Không dùng Elastic IP theo quyết định vận hành/chi phí.

IP cũ:

```text
54.226.168.35
```

IP mới:

```text
98.84.139.124
```

Đã chạy:

```bash
sudo python3 scripts/update_ec2.py --auto-ip
```

Script cập nhật thành công:

- `RETAILOPS_PUBLIC_HOST`
- `RETAILOPS_PUBLIC_ORIGIN`
- `admin.env`
- admin Caddy host
- patch source dưới `/opt/retailops/patches`
- compose public/admin
- recreate containers
- database constraint `memberships_role_check`

URL mới:

```text
https://retailops.98-84-139-124.sslip.io
https://admin-retailops.98-84-139-124.sslip.io
```

Vì không có Elastic IP, mỗi lần Stop/Start cần kiểm tra Public IPv4 và chạy lại `update_ec2.py --auto-ip` nếu IP đổi.

---

## 4. Tình trạng Docker/SSM sau khi phục hồi

Sau nâng cấp EC2:

```text
retailops-web-admin-1      healthy
retailops-web-web-1        healthy
retailops-web-caddy-1      up
retailops-web-postgres-1   healthy
```

Mức sử dụng tại thời điểm kiểm tra:

| Container | CPU | RAM |
|---|---:|---:|
| admin | ~0.01% | ~19.6 MiB / 128 MiB |
| web | ~0.02% | ~81 MiB / 512 MiB |
| caddy | ~0.00% | ~49.5 MiB / 256 MiB |
| postgres | ~0.04% | ~54.7 MiB / 512 MiB |

Docker storage:

```text
Images:       4 active, ~1.226 GB
Volumes:      3 active, ~87.45 MB
Build cache:  0
```

SSM Agent được cài bằng **Snap**, không phải systemd unit truyền thống:

```text
amazon-ssm-agent.amazon-ssm-agent  enabled  active
```

Lệnh đúng để kiểm tra/restart:

```bash
sudo snap services amazon-ssm-agent
sudo snap restart amazon-ssm-agent
```

Không dùng `systemctl restart amazon-ssm-agent` trên host này vì unit đó không tồn tại theo kiểu cài Snap.

SSM user cũng không có quyền Docker socket mặc định; dùng:

```bash
sudo docker ps
sudo docker stats --no-stream
sudo docker system df
```

Không cần thêm user vào group `docker` chỉ để tiện thao tác production.

---

## 5. Bug Google OAuth: đăng nhập xong nhưng UI quay lại màn hình cũ

### 5.1. Triệu chứng

Flow nhìn từ người dùng:

1. bấm đăng nhập Google;
2. chọn tài khoản;
3. OAuth callback quay về RetailOps;
4. URL trở lại trang web;
5. login overlay vẫn hiện, phần giao diện phía sau không được mở.

Ban đầu có thể nghi OAuth/session/cookie, nhưng kiểm tra source cho thấy Google OAuth không phải điểm cuối gây ra màn hình bị khóa.

### 5.2. Root cause frontend

Trong `web/app.js`, code bootstrap gắn handler:

```js
byId('about').onclick = () => byId('about-dialog').showModal();
byId('close-about').onclick = () => byId('about-dialog').close();
```

Trong DOM thực tế, `web/index.html` có `id="about"` nhưng **không còn**:

- `about-dialog`
- `close-about`

Do đó browser có thể lỗi khi gán `.onclick` cho `null`. Đoạn này chạy **trước** logic `openSession()`.

Hậu quả:

```text
Google OAuth success
→ callback/session được tạo
→ redirect về /
→ app.js bootstrap
→ JavaScript crash
→ openSession() không chạy
→ login overlay không được unlock
```

### 5.3. Fix

Commit:

- `66e870e56730de0157a3dae1d1e68c8b56caa342`  
  `fix(ui): guard removed about dialog before session bootstrap`

Binding mới chỉ được tạo khi element tồn tại.

Regression test:

- `0b7256cc76209035edb688061e9ce5805a06ec5b`  
  `test(ui): model missing optional dialog nodes like the real DOM`

Test DOM stub được làm giống browser thật hơn: element bị xóa phải trả về `null` thay vì tự động sinh mock element, nhờ đó loại bug này sẽ bị CI bắt.

Kết quả deploy:

- **Deploy #140:** success
- **Deploy #141:** success

### 5.4. Các fix auth/UI trước đó trong cùng buổi

Các commit liên quan trước khi tìm ra crash cuối cùng:

- `df4091fa66226c27712f4d7985868c824dcc6a27`  
  `fix(auth): harden google oauth state, add guest session login, and dynamic frontend config check`
- `281e5b6007cfbdd6cd2552cfacbfc3a6f572b07a`  
  `fix(ui): isolate auth state machine, fix sidebar z-index leak, and add oauth e2e tests`
- `079dac9e6ac2cd59041c0b3bc8e876b0c4690f3a`  
  `fix(ci): pass google auth availability via body data attribute, eliminating fetch in unit tests`
- `87494685d03cf3779bb1450fe297cfe4fcffb636`  
  `fix(ci): guard style property on mocked DOM elements in unit test VM`

Các run deploy #132, #133, #134 đều success. Vấn đề còn sót lại cuối cùng là DOM/bootstrap crash nói trên.

---

## 6. CI đỏ cuối phiên: generated notebook stale

Sau fix UI, CI #226 fail ở cả `offline` và `colab-python313` với cùng thông báo:

```text
Notebook is stale: run python scripts/build_agent_notebook.py
```

Đây không phải lỗi EC2, OAuth, PostgreSQL hay Docker. Source đã đổi nhưng `notebooks/colab_agent.ipynb` chưa được regenerate.

Đã chạy logic tương đương:

```bash
python scripts/build_agent_notebook.py
python scripts/build_agent_notebook.py --check
```

và đồng bộ notebook vào `main`:

- `d3ca3a6ff6fa106af973d4c44c6ee955bce20f13`
- `chore(notebook): sync generated Colab agent source bundle`

Để không kích hoạt thêm một vòng EC2 deploy chỉ vì verify CI, một branch tạm `ci-notebook-sync` được dùng để chạy lại **toàn bộ cấu hình CI** trên snapshot `main` đã đồng bộ.

Kết quả verify:

- `colab-python313`: success
- `offline`: success
- notebook sync check: success
- JavaScript tests: success
- unit/PostgreSQL/HTTP tests: success
- deployment contract: success
- Docker image build: success
- packaged app tests: success
- HTTPS + cookie session check: success

Historical CI #226 vẫn có thể hiện màu đỏ trong Actions vì đó là run của commit trước khi notebook được sync; không đại diện cho source hiện tại.

---

## 7. Benchmark report làm working tree bị dirty

Trên EC2, `git status` phát hiện:

Tracked files bị benchmark ghi đè:

```text
evals/reports/live_benchmark_report_latest.json
evals/reports/live_benchmark_report_latest.md
```

Các report timestamp mới ở trạng thái untracked.

Đã tạo backup:

```text
/home/ssm-user/retailops-benchmark-backup-20260920-170345
```

Backup chứa cả `latest` và report timestamp.

Đã restore hai file tracked về Git:

```bash
git restore   evals/reports/live_benchmark_report_latest.json   evals/reports/live_benchmark_report_latest.md
```

Đã chạy `git clean -n evals/reports/` để preview các file untracked sẽ bị xóa. Tại thời điểm đó chỉ là preview; không coi `git clean -n` là thao tác xóa.

Bài học: runtime benchmark không nên liên tục ghi artifact vào Git working tree trên production host. Nên ưu tiên thư mục artifact/runtime riêng hoặc có policy rõ về report generated.

---

## 8. Các commit chính trong phiên

| Commit | Nội dung |
|---|---|
| `df4091f` | Harden Google OAuth state, guest login, dynamic frontend config |
| `281e5b6` | Isolate auth state machine, fix sidebar z-index leak, OAuth E2E |
| `079dac9` | Google auth availability qua body data attribute cho CI |
| `8749468` | Guard mocked DOM `style` trong CI |
| `268c474` | Retry SSM document worker transient timeout |
| `d345eb0` | Prune stale Docker data trước EC2 image pull |
| `9a08eec` | EC2 disk preflight, fail fast, prune releases |
| `dd86729` | Phân loại empty SSM failure là worker startup failure |
| `66e870e` | Guard optional/removed about dialog trước session bootstrap |
| `0b7256c` | Regression test cho missing optional DOM nodes |
| `d3ca3a6` | Sync generated Colab notebook source bundle |

---

## 9. Deploy run chính trong chuỗi incident

| Deploy | Commit | Kết quả | Ý nghĩa |
|---:|---|---|---|
| #132 | `df4091f` | ✅ | Auth hardening deploy được |
| #133 | `281e5b6` | ✅ | UI/auth-state changes deploy được |
| #134 | `079dac9` | ✅ | Google-auth frontend config change deploy được |
| #135 | `8749468` | ❌ | SSM worker IPC timeout |
| #136 | `268c474` | ❌ | Retry chưa đủ để cứu host |
| #137 | `d345eb0` | ❌ | Disk/containerd pressure; `no space left on device` |
| #138 | `9a08eec` | ❌ | Host/SSM vẫn chưa đủ khỏe để self-heal |
| #139 | `dd86729` | ❌ | SSM fail trước remote shell; cần can thiệp EC2 |
| #140 | `66e870e` | ✅ | EC2 đã phục hồi; frontend bootstrap fix deploy thành công |
| #141 | `0b7256c` | ✅ | Regression-test commit deploy thành công; rerun cũng success |

---

## 10. Cấu hình hệ thống hiện tại

### EC2

```text
Instance:      retailops-dev
Instance ID:   i-0fd116d8927d0e412
Type:          t3.large
vCPU:          2
RAM:           8 GiB nominal (~7.6 GiB usable)
Swap:          0
Root EBS:      50 GiB
Root FS:       ext4, ~48 GiB usable
Used:          ~4.9 GiB
Free:          ~43 GiB
Root usage:    ~11%
Public IPv4:   98.84.139.124 (dynamic)
Elastic IP:    không dùng
```

### Public endpoints

```text
Web:   https://retailops.98-84-139-124.sslip.io
Admin: https://admin-retailops.98-84-139-124.sslip.io
```

### Runtime containers

```text
retailops-web-web-1
retailops-web-admin-1
retailops-web-postgres-1
retailops-web-caddy-1
```

PostgreSQL data vẫn nằm trên persistent Docker volume; không có thao tác `down -v` hoặc prune volume trong quá trình khắc phục.

---

## 11. Runbook vận hành sau này

### Khi EC2 chỉ reboot

Kiểm tra:

```bash
free -h
df -h /
sudo docker ps
sudo snap services amazon-ssm-agent
```

Reboot thông thường không nhất thiết đổi public IP, nhưng vẫn nên kiểm tra.

### Khi EC2 Stop/Start hoặc đổi instance type

Public IPv4 có thể đổi. Sau khi máy lên:

```bash
cd /home/ssm-user/CSKH_ban_le
git pull origin main
sudo python3 scripts/update_ec2.py --auto-ip
```

Sau đó:

```bash
sudo docker ps
sudo docker stats --no-stream
sudo docker system df
```

Và smoke:

```bash
sudo python3 /opt/retailops/live-e2e.py --mode smoke
```

### Khi disk tăng nhưng `/` chưa tăng

```bash
lsblk
df -hT /
sudo growpart /dev/nvme0n1 1
sudo resize2fs /dev/nvme0n1p1
df -hT /
```

Chỉ dùng chuỗi trên khi root device/filesystem đúng là NVMe partition 1 + ext4 như cấu hình hiện tại.

### Lệnh không được dùng tùy tiện

Không chạy:

```bash
docker system prune --volumes
docker compose down -v
```

vì có thể xóa persistent data.

---

## 12. Các quyết định vận hành được chốt

1. **Không dùng Elastic IP** vì cân nhắc chi phí; chấp nhận cập nhật IP thủ công/tự động bằng `update_ec2.py --auto-ip` sau Stop/Start.
2. **Giữ `sudo docker ...`** thay vì thêm SSM user vào `docker` group.
3. **Không tạo swap ngay**: 8 GiB RAM hiện còn dư lớn; theo dõi thực tế trước.
4. **Không xóa Docker volumes** trong cleanup tự động.
5. **Deploy phải fail fast khi EC2 có disk pressure** thay vì tiếp tục push/release vô ích.
6. **Frontend DOM tests phải mô phỏng element missing bằng `null`**, tránh mock tự tạo element làm che bug browser thật.
7. **Generated notebook phải được sync sau thay đổi source** để CI không đỏ vì stale bundle.

---

## 13. Trạng thái kết thúc phiên

Hạ tầng và web đã trở lại trạng thái có thể vận hành:

- storage pressure đã được xử lý;
- instance đã nâng RAM;
- SSM active;
- Docker runtime nhẹ và sạch;
- PostgreSQL/web/admin healthy;
- public IP/origin đã cập nhật;
- frontend OAuth bootstrap bug đã có fix + regression test;
- Deploy #140/#141 thành công;
- generated notebook đã đồng bộ;
- CI configuration đã được re-verify thành công.

Nếu mở phiên làm việc mới, nên bắt đầu bằng:

```bash
cd /home/ssm-user/CSKH_ban_le
git status
git pull origin main
free -h
df -h /
sudo docker ps
sudo snap services amazon-ssm-agent
```

Sau đó kiểm tra web bằng URL hiện tại và chạy smoke test trước khi tiếp tục benchmark hoặc thay đổi inference.
