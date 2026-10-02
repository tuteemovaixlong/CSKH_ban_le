# Kế Hoạch Triển Khai: Chuyển Đổi Sang Google Account & Phân Quyền Động (RBAC Production)

> **Mã tài liệu**: `PLAN_GOOGLE_ACCOUNT_RBAC_PRODUCTION`  
> **Trạng thái**: Sẵn sàng triển khai (Ready for Implementation)  
> **Phiên bản kiến trúc**: Module 2.5+ / Production Hardening  
> **Mục tiêu**: Loại bỏ phụ thuộc vào dữ liệu gắn sẵn (hardcoded seed data `C-001`, `O-101`..), chuyển đổi 100% sang định danh người dùng thực qua Google OAuth 2.0 (SSO) gắn chặt chẽ với 3 vai trò (Roles: Khách hàng, Nhân viên CSKH, Chủ cửa hàng) mà không làm ảnh hưởng đến bộ Master Benchmark 250 ca đóng băng.

---

## 1. Bối cảnh & Vấn đề Cần Giải Quyết

### 1.1. Hiện trạng hệ thống
- Hệ thống hiện tại có 2 cơ chế song song:
  1. **Dữ liệu gắn sẵn (Hardcoded Seed Data)**: Trong `retailops/business/store.py`, hàm `seed()` tự động tạo khách hàng mẫu `C-001` (Nguyễn Văn A) và các đơn hàng mẫu `O-101`, `O-102`, `O-202`, `O-301..O-312`.
  2. **Google OAuth 2.0 (SSO)**: Đã có nền tảng tại `retailops/http/auth_google.py` và `retailops/identity/persistent.py`, nhưng trong `retailops/identity/persistent.py:68-83` khi tài khoản Google đăng nhập lần đầu vẫn còn đoạn mã chèn 3 đơn hàng giả lập (`sample_orders`).

### 1.2. Hạn chế của việc dùng dữ liệu gắn sẵn
- Không phản ánh đúng môi trường vận hành bán lẻ thực tế (Production): Mọi khách hàng dùng chung dữ liệu `C-001` dễ gây nhầm lẫn context và rò rỉ thông tin cá nhân giữa các người dùng.
- Thiếu tính định danh thực tế: Nhân viên CSKH và Chủ cửa hàng không thể audit được chính xác hành động nào do cá nhân nào thực hiện nếu dùng token chung.

### 1.3. Yêu cầu tiên quyết (Invariants & Constraints)
1. **Bảo toàn Master Benchmark 250 ca**: Không sửa đổi file `evals/scenarios/benchmark_250.jsonl` (SHA-256 `36fa8c7a...`) và các script benchmark CI-CD. Hàm `seed()` truyền thống vẫn được giữ nguyên cho môi trường offline test / benchmark.
2. **Không phá vỡ 114 Unit/Regression Tests hiện có**: Môi trường test tự động vẫn chạy trơn tru mà không yêu cầu kết nối mạng tới máy chủ Google.
3. **Tuân thủ Zero-Trust & Cô lập Khách hàng (Customer Isolation)**: Khách hàng Google A tuyệt đối không xem được hoặc thao tác trên đơn hàng của Khách hàng Google B.

---

## 2. Kiến trúc Định danh & Ma trận Phân quyền (RBAC)

```mermaid
flowchart TD
    User([Người dùng / Nhân viên / Chủ shop]) -->|Click 'Đăng nhập Google'| GAuth[Google OAuth 2.0 / Accounts]
    GAuth -->|Authorization Code Flow + PKCE/State HMAC| Callback[/auth/google/callback]
    Callback --> UserInfo[Google UserInfo: Email, Tên, Sub, Avatar]
    UserInfo --> ResolveRole{Phân giải Role tự động}
    
    ResolveRole -->|Email thuộc MANAGER_EMAILS| ManagerRole[Role: manager - Chủ cửa hàng]
    ResolveRole -->|Email thuộc STAFF_EMAILS| StaffRole[Role: staff - Nhân viên CSKH]
    ResolveRole -->|Email khác / Khách tự do| CustomerRole[Role: customer - Khách hàng]
    
    ManagerRole --> PrincipalMgr[Tạo/Cập nhật Principal & Membership: manager]
    StaffRole --> PrincipalStaff[Tạo/Cập nhật Principal & Membership: staff]
    CustomerRole --> PrincipalCust[Tạo/Cập nhật Principal & Membership: customer]
    
    PrincipalMgr --> UI_Mgr[Mở giao diện Quản trị: Kho hàng, Đơn, Doanh thu, Audit]
    PrincipalStaff --> UI_Staff[Mở giao diện Staff Desk: Tiếp nhận Khiếu nại, Đổi 1-1, Đổi Size]
    PrincipalCust --> UI_Cust[Mở giao diện Khách hàng: Chat Bot, Đơn hàng cá nhân, Giỏ hàng]
```

### 2.1. Ma trận Phân quyền 3 Phân Hệ (3-Role Permissions Matrix)

| Quyền hạn & Chức năng | Khách hàng (`customer`) | Nhân viên CSKH (`staff`) | Chủ cửa hàng (`manager`) |
| :--- | :---: | :---: | :---: |
| **Đăng nhập** | Google Account cá nhân | Google Account công ty/nhân viên | Google Account chủ shop |
| **Trò chuyện với AI Agent** | Có (phạm vi đơn của mình) | Có (hỗ trợ tư vấn) | Có |
| **Tra cứu đơn hàng** | Chỉ xem đơn của chính mình | Xem mọi đơn cần xử lý khiếu nại | Toàn quyền tra cứu & lọc mọi đơn |
| **Yêu cầu Đổi trả / Hủy đơn** | Tạo đề xuất (Proposal) | Xác nhận tiếp nhận đề xuất | Toàn quyền duyệt & xử lý trực tiếp |
| **Quản trị Danh mục Kho hàng** | Không (Chỉ xem Catalog) | Xem tồn kho biến thể | Toàn quyền CRUD sản phẩm & kho |
| **Xem Doanh thu & Báo cáo** | Không | Không | Toàn quyền truy cập KPI & Doanh thu |
| **Xem Lịch sử Audit Log & LLM** | Không | Không | Toàn quyền truy cập audit & chi phí |

---

## 3. Kế hoạch Triển Khai Chi Tiết (4 Giai Đoạn)

### Giai đoạn 1: Hạ tầng Google Cloud Console & Cấu hình Môi trường EC2
- [ ] **Bước 1.1**: Đăng ký Google Cloud Project (hoặc dùng project hiện có), cấu hình OAuth Consent Screen với scope: `openid`, `email`, `profile`.
- [ ] **Bước 1.2**: Tạo **OAuth 2.0 Client ID** (Web Application):
  - **Authorized JavaScript origins**:
    - `https://retailops.34-204-15-44.sslip.io`
    - `https://admin-retailops.34-204-15-44.sslip.io`
    - `http://127.0.0.1:8000` (dành cho local testing)
  - **Authorized redirect URIs**:
    - `https://retailops.34-204-15-44.sslip.io/auth/google/callback`
    - `http://127.0.0.1:8000/auth/google/callback`
- [ ] **Bước 1.3**: Thiết lập biến môi trường an toàn trên máy chủ EC2 (`/home/ssm-user/CSKH_ban_le/.env` và `/opt/retailops/docker-compose.yml`):
  ```bash
  GOOGLE_CLIENT_ID="<client-id>.apps.googleusercontent.com"
  GOOGLE_CLIENT_SECRET="<client-secret>"
  MANAGER_EMAILS="chushop@gmail.com,owner@retailops.vn"
  STAFF_EMAILS="cskh@retailops.vn,nhanvien1@gmail.com"
  DEFAULT_ROLE="customer"
  ALLOW_DEMO_TOKEN="false" # Tắt cổng đăng nhập token giả lập trên Production
  ```

---

### Giai đoạn 2: Tách biệt Môi trường & Làm sạch Dữ liệu Khách hàng Thực
- [ ] **Bước 2.1**: Refactor `retailops/identity/persistent.py`:
  - Loại bỏ hoàn toàn đoạn mã chèn 3 đơn hàng giả lập (`sample_orders`: `O-700101`, `O-700102`, `O-700103`) tại dòng 71-85 khi tài khoản Google đăng nhập.
  - Khi khách hàng Google đăng nhập lần đầu:
    - Tạo `principal` và `membership` chuẩn.
    - Tạo bản ghi trong `customers(id, name)` với `id = cid`, `name = Google User Name`.
    - Danh sách đơn hàng khởi tạo ban đầu là **rỗng** (Không có đơn ảo).
- [ ] **Bước 2.2**: Cung cấp API / Nút tiện ích "Đặt đơn hàng mẫu" cho khách hàng thực tế trải nghiệm:
  - Khách hàng sau khi login có thể bấm nút "Tạo đơn thử nghiệm từ Catalog" trên giao diện để tự tạo một đơn hàng thực tế mang tên và mã khách hàng của chính mình (ví dụ `O-NEW123456`).
  - Đơn hàng này được lưu trực tiếp vào cơ sở dữ liệu và thuộc sở hữu duy nhất của tài khoản Google đó.

---

### Giai đoạn 3: Phân quyền Giao diện UI/UX & Tối ưu Trải nghiệm (Frontend Polish)
- [ ] **Bước 3.1**: Cập nhật `web/index.html` & `web/app.js`:
  - Khi biến `googleAuthConfigured` là `true` và `ALLOW_DEMO_TOKEN !== "true"`:
    - Ẩn toàn bộ form nhập mã token cá nhân thủ công.
    - Đặt nút **"Đăng nhập bằng Google"** làm phương thức xác thực duy nhất ở trung tâm màn hình đăng nhập.
- [ ] **Bước 3.2**: Hiển thị Huy hiệu Người dùng (User Badge & Role Indicator):
  - Sau khi đăng nhập thành công, hiển thị trên header:
    - Ảnh đại diện Google (Avatar).
    - Tên hiển thị & Email Google.
    - Huy hiệu vai trò:
      - 👑 **Chủ cửa hàng (Manager)**: Hiển thị tab Quản lý kho, Quản trị đơn, Báo cáo tài chính.
      - 🎧 **Nhân viên CSKH (Staff)**: Hiển thị tab Staff Desk tiếp nhận yêu cầu đổi trả/bảo hành.
      - 👤 **Khách hàng (Customer)**: Hiển thị tab Chat CSKH và danh sách đơn hàng cá nhân.
- [ ] **Bước 3.3**: Nút Đăng xuất (`/api/logout`): Xóa session cookie an toàn, chuyển hướng về trang đăng nhập.

---

### Giai đoạn 4: Kiểm thử Bảo mật, Cô lập Dữ liệu & Hợp đồng Kiểm thử
- [ ] **Bước 4.1**: Viết bộ test chuyên biệt `tests/test_google_rbac_production.py`:
  - Kịch bản 1: Login tài khoản thuộc `MANAGER_EMAILS` -> Nhận session có role `manager`, truy cập được `/api/products` (POST/DELETE/PUT).
  - Kịch bản 2: Login tài khoản thuộc `STAFF_EMAILS` -> Nhận session có role `staff`, truy cập được Staff Desk, bị chặn khi sửa kho.
  - Kịch bản 3: Login tài khoản khách hàng thông thường -> Nhận role `customer`, chỉ truy xuất được đơn hàng có `customer_id` của chính mình.
  - Kịch bản 4: Kiểm tra tính cô lập: Khách hàng Google A cố tình truy cập hoặc hủy đơn của Khách hàng Google B -> Nhận lỗi `404 order_not_found` hoặc `403 forbidden`.
  - Kịch bản 5: CSRF State verification bảo vệ chống tấn công Replay State.
- [ ] **Bước 4.2**: Xác nhận tính toàn vẹn:
  - Chạy `python -m unittest discover tests` đảm bảo 114+ tests đạt 100% OK.
  - Chạy `python scripts/check_docs_contract.py` đảm bảo không vi phạm hợp đồng tài liệu.
  - Chạy `python scripts/check_deployment_contract.py` đảm bảo cấu hình triển khai hợp lệ.

---

## 4. Bảng So Sánh Trước & Sau Khi Triển Khai

| Đặc tính | Trước khi triển khai (Hiện tại) | Sau khi triển khai (Production Plan) |
| :--- | :--- | :--- |
| **Phương thức xác thực chính** | Nhập mã token tĩnh hoặc dữ liệu seed | **Google OAuth 2.0 (SSO Single Sign-On)** |
| **Phân quyền Role** | Token giả lập cấu hình sẵn trong env | **Tự động phân giải qua Email Google + DB RBAC** |
| **Dữ liệu Khách hàng** | Dùng chung `C-001` và các đơn `O-101`, `O-102` | **Profile Google thực, đơn hàng gắn chặt với cá nhân** |
| **Cô lập dữ liệu (Multi-tenancy)** | Dễ lẫn lộn dữ liệu giữa các phiên demo | **Cô lập tuyệt đối giữa các Google Account** |
| **Giao diện đăng nhập** | Ô nhập token dài dòng, dễ nhầm lẫn | **1-Click "Đăng nhập bằng Google" tiện lợi, bảo mật** |
| **Hỗ trợ Benchmark/CI-CD** | Chạy offline tốt | **Vẫn giữ nguyên seed cho chế độ test offline** |

---

## 5. Kết luận & Hướng Dẫn Kích Hoạt

Kế hoạch này giúp RetailOps chuyển mình từ một hệ thống **Demo / Prototype có dữ liệu gắn sẵn** thành một hệ thống **E-Commerce Operations SaaS Production hoàn chỉnh**, sẵn sàng cho người dùng thật (khách hàng, nhân viên và chủ shop) vận hành thực tế trên đám mây AWS EC2.
