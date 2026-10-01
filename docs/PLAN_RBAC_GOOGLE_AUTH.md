# Kế hoạch Tích hợp Google OAuth 2.0 (SSO) & Phân quyền Giao diện Đa Vai trò (Role-Based UI Isolation)

> **Trạng thái:** IMPLEMENTED & ACTIVE (Core Code & UI Hoàn Tất; Cấu hình Redirect URI phụ thuộc Runtime EC2)  
> **Mức độ minh chứng (Evidence):** L1 Automated Tests (`test_public_session.js`, OAuth E2E) · L3 Live Deployed (Commit `281e5b6`)  
> **Audit basis / Documentation baseline reviewed:** `b93eb5a` · **Application verified:** `d3ca3a6`  
> **Ngày rà soát:** 2026-09-21  
> **Ghi chú vận hành:** Bước 1 (Authorized Redirect URI) là cấu hình runtime trên Google Cloud Console, cần revalidate mỗi khi EC2 Stop/Start đổi IP (không dùng Elastic IP cố định).  
> **Tổng quan:** Tích hợp Đăng nhập một chạm bằng Google (Sign in with Google) và phân tách giao diện độc lập theo đúng thẩm quyền: Khách hàng, Nhân viên CSKH, Quản lý Cửa hàng. Quản trị viên Kỹ thuật (Ops Admin) chạy trên subdomain riêng qua Caddy Basic Auth.

---

## 1. Mục tiêu & Giá trị Chiến lược

1. **Trải nghiệm Đăng nhập Không Ma sát (Zero-friction SSO)**:
   - Thay thế việc sao chép/dán mã token 43 ký tự dài dòng bằng nút **"Đăng nhập bằng Google" (Sign in with Google)**.
   - Hội đồng chấm thi, nhân viên hoặc khách hàng có thể dùng chính tài khoản Gmail cá nhân để đăng nhập chỉ bằng một cú nhấp chuột.
2. **Giao diện Chuyên biệt hóa Tuyệt đối (Role-Based UI Isolation)**:
   - Mỗi người dùng khi đăng nhập chỉ thấy **đúng các tính năng thuộc quyền hạn của mình**.
   - Ẩn hoàn toàn các nút chức năng hoặc thông tin thừa thãi gây rối mắt.
3. **Minh chứng Học thuật & Thực tiễn cho Khóa luận**:
   - Đưa mô hình **Xác thực Phân tán & Kiểm soát Truy cập Dựa trên Vai trò (RBAC + OAuth 2.0 / OIDC)** vào **Chương 3 (Kiến trúc Hệ thống)**.
   - Tạo kịch bản demo bảo vệ ấn tượng: Thầy/Cô đăng nhập Gmail đóng vai Khách hàng; sinh viên đăng nhập Gmail nhân viên mở thẳng Bàn làm việc để trả lời Thầy/Cô.

---

## 2. Mô hình Ma trận Phân quyền 4 Vai trò (RBAC Matrix)

```mermaid
flowchart TD
    Login["Người dùng Đăng nhập (Google OAuth / Token)"] --> AuthEngine{"Backend Phân tích Role từ Email/DB"}
    
    AuthEngine -->|role = 'customer'| ViewCustomer["1. GIAO DIỆN KHÁCH HÀNG\n• Khung Chat AI CSKH & Tra cứu đơn cá nhân\n• Danh sách đơn hàng của riêng mình\n• Đánh giá CSAT (👍/👎)\n[Ẩn Bàn làm việc, Audit Log, Dashboard Quản trị]"]
    
    AuthEngine -->|role = 'staff'| ViewStaff["2. GIAO DIỆN NHÂN VIÊN CSKH (Staff Desk)\n• Mở thẳng Bàn làm việc CSKH toàn màn hình\n• Hàng đợi ca chờ hợp nhất (Facebook, Zalo, Web)\n• Khung chat 2 chiều với khách + Nút Hoàn tất ca\n[Ẩn khung chat khách hàng, ẩn cấu hình AI]"]
    
    AuthEngine -->|role = 'manager'| ViewManager["3. GIAO DIỆN QUẢN LÝ CỬA HÀNG (Store Dashboard)\n• Bảng chỉ số CSAT & Tỷ lệ AI tự xử lý vs Escalation\n• Quản lý toàn bộ Đơn hàng & Duyệt hủy/đổi trả\n• Nhật ký Audit Trail (Ai duyệt, khi nào, lý do gì)\n• Quản lý phân ca & cấp quyền nhân viên"]
    
    CaddyAuth["Xác thực Caddy Basic Auth (:8100/admin)"] -->|opsadmin| ViewAdmin["4. GIAO DIỆN QUẢN TRỊ VIÊN KỸ THUẬT (Ops Console)\n• Chạy trên subdomain độc lập (:8100/admin)\n• Đo kiểm Model Router Accuracy, Confusion Matrix\n• Giám sát Latency p95/p99, Token Usage & Container"]
```

### Bảng Ma trận Quyền hạn Chi tiết (RBAC Matrix)

| Chức năng / Thao tác | Khách hàng (`customer`) | Khách chỉ xem (`viewer`) | Nhân viên CSKH (`staff`) | Quản lý Shop (`manager`) | Quản trị Kỹ thuật (`opsadmin`)* |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Chat tư vấn với AI Agent** | ✅ | ❌ *(Bị chặn/Ẩn)* | ❌ *(Ẩn trên Staff Desk)* | ❌ *(Ẩn trên Manager Console)* | ❌ *(Không dùng)* |
| **Xem đơn hàng cá nhân** | ✅ *(Chỉ đơn của mình)* | ✅ *(Chỉ xem đơn mình)* | ❌ *(Chuyển sang Bàn làm việc)* | ❌ *(Chuyển sang Manager)* | ❌ *(Không dùng)* |
| **Hủy đơn hàng đang chờ (`orders:cancel`)** | ✅ *(Đơn của mình)* | ❌ *(Chỉ đọc)* | ✅ *(Hỗ trợ hủy thay khách)* | ✅ *(Quyền tối cao)* | ❌ *(Không can thiệp)* |
| **Đánh giá CSAT (👍/👎)** | ✅ | ❌ *(Ẩn)* | ❌ *(Ẩn)* | ❌ *(Ẩn)* | ❌ *(Không dùng)* |
| **Bàn làm việc CSKH (`staff:desk`)** | ❌ *(Bị từ chối 403)* | ❌ *(Bị từ chối 403)* | ✅ *(Màn hình chính)* | ✅ *(Có thể xem/hỗ trợ)* | ❌ *(Không can thiệp)* |
| **Quản lý đơn toàn shop (`store:manage`)** | ❌ *(Bị từ chối 403)* | ❌ *(Bị từ chối 403)* | ❌ *(Chỉ xem theo ca)* | ✅ *(Cập nhật trạng thái)* | ❌ *(Không can thiệp)* |
| **CRUD Sản phẩm / Danh mục** | ❌ *(Bị từ chối 403)* | ❌ *(Bị từ chối 403)* | ❌ *(Bị từ chối 403)* | ✅ *(Đầy đủ Create/Update/Delete)* | ❌ *(Không can thiệp)* |
| **Nhật ký can thiệp đơn (Audit Trail)** | ❌ *(Bị từ chối 403)* | ❌ *(Bị từ chối 403)* | ❌ *(Bị từ chối 403)* | ✅ *(Xem toàn bộ audit log)* | ❌ *(Không can thiệp)* |
| **Báo cáo CSAT & KPIs Cửa hàng** | ❌ *(Bị từ chối 403)* | ❌ *(Bị từ chối 403)* | ❌ *(Bị từ chối 403)* | ✅ *(KPIs & Báo cáo)* | ❌ *(Không can thiệp)* |
| **Ops Console Router / Telemetry** | ❌ *(Bị từ chối)* | ❌ *(Bị từ chối)* | ❌ *(Bị từ chối)* | ❌ *(Bị từ chối)* | ✅ *(Độc quyền :8100/admin)* |

> `*` Ghi chú: `opsadmin` chạy trên cổng quản trị kỹ thuật độc lập (`:8100/admin`), được bảo vệ bằng Caddy Basic Auth và không dùng chung database session của web bán lẻ. Cơ sở thẩm quyền mã nguồn: `retailops/business/permissions.py:ROLE_PERMISSIONS`.

---

## 3. Thiết kế Kỹ thuật: Google OAuth 2.0 (SSO)

### 3.1. Luồng Xác thực (Authentication Sequence)

```mermaid
sequenceDiagram
    autonumber
    actor User as Người dùng (Khách / Nhân viên / Quản lý)
    participant Web as RetailOps Web App
    participant Backend as RetailOps Backend (/auth/google)
    participant Google as Google Identity Provider (OAuth 2.0)
    participant DB as PostgreSQL Database

    User->>Web: Nhấp chọn "Đăng nhập bằng Google"
    Web->>Backend: GET /auth/google/login
    Backend-->>Web: Redirect sang URL Google OAuth kèm `state` và Set-Cookie `retailops_oauth_transient` (HttpOnly, SameSite=Lax, Max-Age=600)
    Web->>Google: Chuyển hướng sang màn hình chọn tài khoản Gmail
    User->>Google: Đăng nhập & Xác nhận cấp quyền (email, profile)
    Google-->>Web: Redirect về Callback URL kèm `code` và `state`
    Web->>Backend: GET /auth/google/callback?code=...&state=... kèm Cookie `retailops_oauth_transient`
    Note over Backend: Kiểm tra băm cookie trong `state` (SEC-01: Chống Login CSRF)<br/>Từ chối 403 nếu thiếu hoặc không khớp!
    Backend->>Google: Gửi POST đổi `code` lấy `id_token` & `access_token`
    Google-->>Backend: Trả về Profile (email, name, sub, picture)
    
    Backend->>DB: Tra cứu email trong hệ thống
    alt Email nằm trong STAFF_EMAILS
        Backend->>DB: Gán/Cập nhật role = 'staff'
    else Email nằm trong MANAGER_EMAILS
        Backend->>DB: Gán/Cập nhật role = 'manager'
    else Email cá nhân vãng lai
        Backend->>DB: Tự động khởi tạo customer membership với role = 'customer'
    end

    Backend-->>Web: Thiết lập HTTP-Only Secure Cookie (`retailops_session`)
    Web->>Web: Gọi `/api/session` nhận vai trò và nạp giao diện tương ứng
```

### 3.2. Cấu hình Tham số Google Cloud Console

* **Project**: `RetailOps-CSKH`
* **Application Type**: `Web application`
* **Name**: `RetailOps Web Client`
* **Authorized JavaScript origins**:
  ```text
  https://<RETAILOPS_PUBLIC_HOST>
  ```
  *(Ví dụ với IP hiện tại: `https://retailops.98-84-139-124.sslip.io`)*
* **Authorized redirect URIs**:
  ```text
  https://<RETAILOPS_PUBLIC_HOST>/auth/google/callback
  ```
  *(Ví dụ với IP hiện tại: `https://retailops.98-84-139-124.sslip.io/auth/google/callback`)*

### 3.3. Quy tắc Ánh xạ Vai trò Tự động (Smart Role Mapping)

Trong file môi trường `/opt/retailops/api.env`, cấu hình danh sách phân quyền:

```ini
# Khóa định danh từ Google Cloud Console
GOOGLE_CLIENT_ID="xxxxxx.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET="GOCSPX-xxxxxx"

# Danh sách phân vai trò theo email
STAFF_EMAILS="maianh.cskh@gmail.com,nv1@gmail.com"
MANAGER_EMAILS="chushop@gmail.com,admin@gmail.com"
DEFAULT_ROLE="customer"
```

Khi một email đăng nhập:
1. Nếu email khớp với `STAFF_EMAILS` $\to$ Cấp quyền `staff`.
2. Nếu email khớp với `MANAGER_EMAILS` $\to$ Cấp quyền `manager`.
3. Mọi email khác $\to$ Tự động cấp quyền `customer` và cấp mã khách hàng mới (ví dụ `C-GOOGLE-xxxx`).

### 3.4. Chống Tấn Công OAuth Login CSRF (Hạng mục SEC-01) [CHƯA KIỂM CHỨNG / PENDING TEST]

- **Vấn đề bảo mật**: Kẻ tấn công có thể khởi tạo luồng OAuth từ trình duyệt của mình, lấy URL callback chứa `code` và `state` của kẻ tấn công, rồi lừa nạn nhân truy cập liên kết đó. Trình duyệt nạn nhân sẽ hoàn tất đăng nhập bằng danh tính của kẻ tấn công, dẫn đến rò rỉ dữ liệu hoặc chiếm quyền kiểm soát phiên (RFC 6749 §10.12).
- **Tệp & Hàm liên quan**:
  - `retailops/http/auth_google.py`: `handle_google_login(app, query, headers)`, `handle_google_callback(app, query, headers)`.
  - `retailops/http/public.py`: Tuyến điều hướng `/auth/google/login` và `/auth/google/callback`.
- **Hành vi mong đợi**:
  1. Khi vào `/auth/google/login`: Backend sinh một chuỗi ngẫu nhiên cryptographically secure `oauth_browser_nonce` (32 bytes hex).
  2. Gửi cookie `Set-Cookie: retailops_oauth_transient=<nonce>; HttpOnly; SameSite=Lax; Path=/auth/google; Max-Age=600`.
  3. Tính toán `nonce_hash = hashlib.sha256(oauth_browser_nonce.encode()).hexdigest()[:16]` và nhúng vào payload `state` (được ký HMAC).
  4. Khi Google chuyển hướng về `/auth/google/callback`: Trích xuất cookie `retailops_oauth_transient`, băm lại và so khớp với `nonce_hash` trong `state`.
  5. Nếu thiếu cookie hoặc băm không khớp: Từ chối ngay lập tức với mã lỗi HTTP 403 `oauth_state_invalid`.
  6. Sau khi đăng nhập thành công: Xóa transient cookie (`Max-Age=0`).
- **Test tương ứng**: `tests/test_auth_google.py::test_oauth_csrf_state_binding`, `tests/test_auth_google.py::test_oauth_callback_missing_transient_cookie`.

---

## 4. Thiết kế Giao diện Frontend theo Vai trò

Frontend sử dụng cơ chế thuộc tính dữ liệu toàn cục:
```javascript
// Sau khi gọi /api/session
document.body.dataset.role = session.role; // 'customer' | 'staff' | 'manager' | 'admin'
```

### 4.1. Giao diện Khách hàng (`customer`)
- Giữ nguyên bố cục chat hiện tại.
- Ẩn nút `🎧 Bàn làm việc CSKH` trên topbar:
  ```css
  body[data-role="customer"] #toggle-staff-desk { display: none !important; }
  ```

### 4.2. Giao diện Nhân viên CSKH (`staff`)
- Khi đăng nhập thành công, giao diện tự động ẩn khung chat khách và mở thẳng **Bàn làm việc CSKH (Staff Desk)** ra toàn màn hình.
- Nhân viên có toàn bộ không gian để làm việc:
  - Xem danh sách hàng đợi (Queue) các ca cần người thật từ Facebook, Zalo OA, Website.
  - Chat trực tiếp 2 chiều với khách hàng.
  - Bấm nút **"✓ Hoàn tất ca"** để chuyển lại cho AI Agent.

### 4.3. Giao diện Quản lý Cửa hàng (`manager`)
- Bổ sung tab **📊 Báo cáo Vận hành CSKH (Manager Dashboard)**:
  - **Tỷ lệ tự động hóa (Automation Rate)**: Số ca AI tự giải quyết thành công (%).
  - **Tỷ lệ chuyển giao (Escalation Rate)**: Số ca phải chuyển cho nhân viên xử lý (%).
  - **Điểm CSAT trung bình**: Điểm đánh giá sao và tỷ lệ Like/Dislike từ khách hàng.
  - **Quản lý Đơn hàng & Audit**: Xem danh sách toàn bộ đơn hàng của cửa hàng và nhật ký kiểm toán hành vi nhân viên.

---

## 5. Kế hoạch Triển khai (Checklist 5 Bước)

- [~] **Bước 1**: Cấu hình trên Google Cloud Console (Authorized Origins & Redirect URIs): Phụ thuộc vào IP/Domain hiện tại của EC2 sau mỗi lần Stop/Start.
- [x] **Bước 2**: Viết module xác thực Google OAuth (`retailops/http/auth_google.py`) xử lý `/auth/google/login` và `/auth/google/callback` kèm mã hóa CSRF state qua HMAC.
- [x] **Bước 3**: Cập nhật cơ chế phiên (`retailops/identity/store.py`) hỗ trợ ánh xạ `email` và mở rộng enum vai trò `('customer', 'viewer', 'staff', 'manager')`.
- [x] **Bước 4**: Thêm nút **"Đăng nhập bằng Google"** trên form đăng nhập `web/index.html`.
- [x] **Bước 5**: Tối ưu hóa CSS/JS phân quyền giao diện: `customer` chỉ thấy chat đơn của mình, `staff` mở thẳng Bàn làm việc, `manager` xem Dashboard CSAT; cô lập máy trạng thái auth và bổ sung bộ test E2E (Commit `281e5b6`).
