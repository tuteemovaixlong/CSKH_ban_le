# Kế Hoạch Triển Khai: Chuyển Đổi Sang Google Account & Phân Quyền Động (RBAC Production)

> **Mã tài liệu**: `PLAN_GOOGLE_ACCOUNT_RBAC_PRODUCTION`
> **Trạng thái**: Kế hoạch phân kỳ triển khai (Phasing Roadmap — Dự kiến sau Module 2.5)
> **Phiên bản kiến trúc**: Module 2.5+ / Production Hardening Roadmap
> **Nguồn đặc tả kỹ thuật chuẩn (SSOT)**: Toàn bộ hợp đồng dữ liệu, chuỗi định danh, UUIDv4 opaque IDs, DB-backed RBAC SSOT và quy trình import đơn hàng được định nghĩa chuẩn tại [PLAN_ACCOUNT_IDENTITY_IMPORT_SPECIFICATION.md](PLAN_ACCOUNT_IDENTITY_IMPORT_SPECIFICATION.md). Tài liệu này đóng vai trò lộ trình phân kỳ 4 giai đoạn triển khai (Phasing Overview), không duy trì bảng yêu cầu kỹ thuật độc lập.
> **Mục tiêu**: Loại bỏ phụ thuộc vào dữ liệu gắn sẵn trong demo, phân định rõ ràng giữa guest per-session DB và persistent account, khắc phục triệt để lỗ hổng va chạm mã khách hàng N08, chuyển đổi sang định danh người dùng thực qua Google OAuth 2.0 (SSO) gắn với 3 vai trò (Roles: Khách hàng, Nhân viên CSKH, Chủ cửa hàng) mà không làm ảnh hưởng đến bộ Master Benchmark 250 ca đóng băng.

---

## 1. Bối cảnh & Vấn đề Cần Giải Quyết

### 1.1. Hiện trạng hệ thống
- Hệ thống hiện tại có 2 cơ chế:
  1. **Dữ liệu gắn sẵn (Hardcoded Seed Data)**: Trong `retailops/business/store.py`, hàm `seed()` tự động tạo khách hàng mẫu `C-001` (Nguyễn Văn A) và các đơn hàng mẫu `O-101`, `O-102`, `O-202`, `O-301..O-312`. Đối với guest demo, mỗi phiên truy cập được cấp một SQLite DB riêng biệt gắn với session token demo.
  2. **Google OAuth 2.0 (SSO) & Persistent Store**: Đã có khung tại `retailops/http/auth_google.py` và `retailops/identity/persistent.py`, tuy nhiên:
     - Tại `retailops/identity/persistent.py`, khi tài khoản Google đăng nhập lần đầu vẫn còn đoạn mã chèn 3 đơn hàng giả lập (`sample_orders`: `O-700101..O-700103`).
     - Tồn tại lỗ hổng P1 (N08): ID khách hàng phát sinh từ tiền tố `CG-` ghép 8 ký tự hex đầu của SHA-256 email (32-bit entropy). Thực nghiệm đã chứng minh va chạm hash (collision) giữa các email khác nhau trong cùng tenant, dẫn tới hai account khác nhau có nguy cơ cùng trỏ vào một `customer_id`.
     - Vai trò (Role) khi login bị ghi đè bởi cấu hình biến môi trường (`MANAGER_EMAILS`, `STAFF_EMAILS`) thay vì tôn trọng Single Source of Truth (SSOT) từ bảng `memberships` trong cơ sở dữ liệu.

### 1.2. Hạn chế cần khắc phục
- **Tách bạch môi trường**: Phân định rạch ròi giữa môi trường demo (có sẵn dữ liệu mẫu phục vụ kiểm thử) và môi trường khách hàng thực (khách thật khi đăng nhập bắt đầu với 0 đơn hàng).
- **Tránh va chạm định danh**: Thay thế hoàn toàn mã hash 32-bit bằng định danh server-generated opaque UUIDv4/CUST-ID có ràng buộc duy nhất `(tenant_id, principal_id)` và `(issuer, sub, tenant_id)` theo đặc tả tại [PLAN_ACCOUNT_IDENTITY_IMPORT_SPECIFICATION.md](PLAN_ACCOUNT_IDENTITY_IMPORT_SPECIFICATION.md).
- **Định danh audit minh bạch**: Nhân viên CSKH và Chủ cửa hàng thao tác trên hệ thống phải ghi nhận rõ `principal_id` thực hiện trong audit log thay vì chỉ dựa vào `staff_name` hay context do client tự gửi.

### 1.3. Yêu cầu tiên quyết (Invariants & Constraints)
1. **Bảo toàn Master Benchmark 250 ca**: Không sửa đổi file `evals/scenarios/benchmark_250.jsonl` (SHA-256 LF `36fa8c7a...`) và các script benchmark CI-CD. Hàm `seed()` truyền thống vẫn được giữ nguyên cho môi trường offline test / benchmark.
2. **Không phá vỡ Regression Tests hiện có**: Môi trường test tự động vẫn chạy độc lập bằng in-memory/sqlite fixtures mà không phụ thuộc vào kết nối mạng tới máy chủ Google.
3. **Tuân thủ Zero-Trust & Cô lập Khách hàng (Customer Isolation)**: Ràng buộc SQL Ownership `WHERE id = ? AND customer_id = ?` luôn được thực thi nghiêm ngặt tại tầng lưu trữ. Account Google A tuyệt đối không xem được hoặc thao tác trên đơn hàng của Account Google B.

---

## 2. Kiến trúc Định danh & Ma trận Phân quyền (RBAC)

```mermaid
flowchart TD
    User([Người dùng / Nhân viên / Chủ shop]) -->|Click 'Đăng nhập Google'| GAuth[Google OAuth 2.0 / Accounts]
    GAuth -->|Authorization Code Flow + Planned PKCE/State HMAC| Callback[/auth/google/callback]
    Callback --> UserInfo[Google UserInfo: Issuer, Sub, Email, Tên, Avatar]
    UserInfo --> ResolvePrincipal[Resolve/Provision Principal & Verified Profile]
    ResolvePrincipal --> ResolveTenant[Xác định Tenant theo domain / invitation / selection]
    ResolveTenant --> CheckMembership{Tra cứu Membership trong DB}

    CheckMembership -->|Đã có Membership trong DB| UseDBRole[Sử dụng Role từ Membership DB làm SSOT]
    CheckMembership -->|Chưa có - User mới| InitialRole[Khởi tạo: Check Invitation / Bootstrap Env / Default customer]

    UseDBRole --> Session[Cấp phiên làm việc: actor_principal_id, tenant_id, role, customer_id, auth_version]
    InitialRole --> Session

    Session --> RouteAccess{Điều hướng giao diện theo Role}
    RouteAccess -->|manager| UI_Mgr[Giao diện Quản trị: Kho hàng, Đơn hàng, Doanh thu, Audit]
    RouteAccess -->|staff| UI_Staff[Giao diện Staff Desk: Đổi hàng, Hỗ trợ khiếu nại theo case-scoped context]
    RouteAccess -->|customer| UI_Cust[Giao diện Khách hàng: Chat Bot, Đơn hàng cá nhân, Giỏ hàng]
```

### 2.1. Ma trận Phân quyền 3 Phân Hệ (3-Role Permissions Matrix)

| Quyền hạn & Chức năng | Khách hàng (`customer`) | Nhân viên CSKH (`staff`) | Chủ cửa hàng (`manager`) |
| :--- | :---: | :---: | :---: |
| **Đăng nhập** | Google Account cá nhân | Google Account công ty/nhân viên | Google Account chủ shop |
| **Trò chuyện với AI Agent** | Có (phạm vi đơn của mình) | Có (hỗ trợ tư vấn) | Có |
| **Tra cứu đơn hàng** | Chỉ xem đơn của chính mình | Xem đơn theo case hỗ trợ được gán | Toàn quyền tra cứu & lọc mọi đơn trong tenant |
| **Yêu cầu Đổi trả / Hủy đơn** | Tạo đề xuất (Proposal) | Tiếp nhận & xác minh theo case | Toàn quyền duyệt & xử lý trực tiếp |
| **Quản trị Danh mục Kho hàng** | Không (Chỉ xem Catalog) | Xem tồn kho biến thể | Toàn quyền quản trị (/api/manager/products) |
| **Xem Doanh thu & Báo cáo** | Không | Không | Toàn quyền truy cập KPI & Doanh thu |
| **Xem Lịch sử Audit Log & LLM** | Không | Không | Toàn quyền truy cập audit & chi phí |

---

## 3. Kế Hoạch Triển Khai Chi Tiết (4 Giai Đoạn)

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
    - Tạo bản ghi trong `customers(id, name)` với `id = cust_<uuid4>`, `name = Google User Name`.
    - Danh sách đơn hàng khởi tạo ban đầu là **rỗng (0 đơn)**.
- [ ] **Bước 2.2**: Cung cấp chế độ Sandbox / Đơn thử nghiệm tách biệt:
  - Khách hàng thử nghiệm trong chế độ Sandbox (`ALLOW_DEMO_TOKEN=true`) có thể tạo đơn hàng thử nghiệm qua endpoint riêng.
  - Mã đơn nội bộ tuân thủ định dạng chuỗi hợp lệ xuyên suốt từ HTTP route đến Agent parser (`O-<digits>` hoặc internal canonical format).

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
  - Kịch bản 1: Login tài khoản thuộc `MANAGER_EMAILS` -> Nhận session có role `manager`, truy cập được `/api/manager/products` (POST, cập nhật `/update`, xóa `/delete`).
  - Kịch bản 2: Login tài khoản thuộc `STAFF_EMAILS` -> Nhận session có role `staff`, truy cập được Staff Desk, bị chặn khi sửa kho.
  - Kịch bản 3: Login tài khoản khách hàng thông thường -> Nhận role `customer`, chỉ truy xuất được đơn hàng có `customer_id` của chính mình.
  - Kịch bản 4: Kiểm tra tính cô lập: Khách hàng Google A cố tình truy cập hoặc hủy đơn của Khách hàng Google B -> Nhận lỗi `404 order_not_found` hoặc `403 forbidden`.
  - Kịch bản 5: CSRF State verification bảo vệ chống tấn công Replay State.
- [ ] **Bước 4.2**: Xác nhận tính toàn vẹn:
  - Chạy toàn bộ regression test suite đảm bảo 100% PASS.
  - Chạy `python scripts/check_docs_contract.py` đảm bảo không vi phạm hợp đồng tài liệu.
  - Chạy `python scripts/check_deployment_contract.py` đảm bảo cấu hình triển khai hợp lệ.

---

## 4. Bảng So Sánh Trước & Sau Khi Triển Khai

| Đặc tính | Trước khi triển khai (Hiện tại) | Sau khi triển khai (Production Plan) |
| :--- | :--- | :--- |
| **Phương thức xác thực chính** | Nhập mã token tĩnh hoặc dữ liệu seed | **Google OAuth 2.0 (SSO Single Sign-On)** |
| **Phân quyền Role** | Biến môi trường ghi đè khi login | **Role SSOT từ DB `tenant_memberships` + thu hồi tức thì qua `auth_version`** |
| **Dữ liệu Khách hàng** | Guest per-session SQLite hoặc sample orders | **Tài khoản sạch (0 đơn), đơn hàng gắn chặt với cá nhân** |
| **Mã khách hàng (N08)** | SHA-256 32-bit `CG-` dễ gây va chạm hash | **Server-generated UUIDv4/CUST-ID, unique constraints chặt chẽ** |
| **Cô lập dữ liệu (Multi-tenancy)** | Dễ lẫn lộn dữ liệu giữa các phiên demo | **Cô lập tuyệt đối giữa các Google Account và Tenant** |
| **Giao diện đăng nhập** | Ô nhập token dài dòng, dễ nhầm lẫn | **1-Click "Đăng nhập bằng Google" tiện lợi, bảo mật** |
| **Hỗ trợ Benchmark/CI-CD** | Chạy offline tốt | **Vẫn giữ nguyên seed cho chế độ test offline** |

---

## 5. Kết luận & Điều Kiện Chuyển Tiếp

Kế hoạch này vạch rõ lộ trình chuẩn bị cho **Giai đoạn C (Identity & Real Data)** và **Giai đoạn D (Nguồn đơn & Lifecycle)** trong tương lai. Kế hoạch này được tách biệt độc lập khỏi việc hoàn thiện PR A và PR B thuộc Module 2.5, đảm bảo không làm gián đoạn các hợp đồng kiểm thử và benchmark hiện hành.
