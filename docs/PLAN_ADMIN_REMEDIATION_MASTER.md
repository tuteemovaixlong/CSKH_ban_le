# Lộ Trình Cải Tổ Toàn Diện Giao Diện Quản Trị & Toàn Vẹn Dữ Liệu RetailOps 2026 (Master Remediation Plan)

> **Cơ sở xây dựng**: Tiếp thu toàn diện kết quả kiểm toán kỹ thuật từ chuyên gia (chuỗi kiểm tra UI → API → Application/Store → Persistence → Telemetry → Deployment).  
> **Cam kết chất lượng**: Không dùng số liệu giả, không tự suy diễn token/cost, Single Source of Truth cho Catalog/Kho hàng, bảo vệ biên giới bảo mật của từng vai trò (RBAC).

---

## 1. Bản Đồ Phân Kỳ 3 Giai Đoạn Thực Hiện

```mermaid
flowchart TD
    subgraph PHASE_1["GIAI ĐOẠN 1 (P0): TRUTHFUL UX & SAFE FALLBACKS (Thực hiện ngay)"]
        M1["MODULE 1 (Truthful UX):<br/>• Xóa bỏ số giả 83.5%, 16.5%, 4.8/5 trong HTML<br/>• Xử lý CSAT null & cỡ mẫu N<br/>• Không gán giá trị mặc định cho trường thiếu (unknown stays unknown)<br/>• Đổi nhãn Tổng Doanh Thu -> Tổng Giá Trị Đơn (GMV)<br/>• Gắn nhãn [Mô phỏng] cho các nút SOP 1..5<br/>• Ẩn Tool Inspector khỏi giao diện khách"]
    end

    subgraph PHASE_2["GIAI ĐOẠN 2 (P0): ARCHITECTURE, PERSISTENCE & CHAT RESUME"]
        M2["MODULE 2 (Persistence & SSOT):<br/>• Khắc phục Container read_only: true<br/>• Đồng bộ Catalog vào DB chung (PostgreSQL / Shared Store)<br/>• check_inventory đọc tồn kho động từ Catalog/DB, bỏ stock_map cứng<br/>• Sửa scope Audit Trail cho Store Manager (toàn shop thay vì 1 khách)<br/>• Tự động mở Store Manager Console khi đăng nhập role manager"]
        M4["MODULE 4 (Chat History Resume & Persistent Memory):<br/>• Bổ sung GET /api/conversations (danh sách phiên chat cũ)<br/>• Tự động Resume phiên chat gần nhất khi F5 / mở lại trang<br/>• Tái hiện đầy đủ bong bóng chat cũ từ agent_turns<br/>• Giao diện danh sách lịch sử trò chuyện & nút Chat mới"]
        M2 --- M4
    end

    subgraph PHASE_3["GIAI ĐOẠN 3 (P1): OPS CONSOLE TELEMETRY & OBSERVABILITY"]
        M3["MODULE 3 (Ops Telemetry):<br/>• Chuẩn hóa import_benchmark: không chia 3 ước lượng token, không cost=0<br/>• Bỏ toàn bộ fallback cứng cũ (94.6%, Qwen 2.5 4B) trong admin.js<br/>• Đổi tên TTFT thành E2E Request Latency chuẩn xác<br/>• Bổ sung feedback_received & manager_updates vào Usage Allowlist"]
    end

    PHASE_1 --> PHASE_2
    PHASE_2 --> PHASE_3
```

---

## 2. Danh Mục Các Tài Liệu Kế Hoạch Thành Phần

Các tài liệu thiết kế và lộ trình chi tiết cho từng giai đoạn được lưu tại:

1. 📄 **[Module 1: Truthful UX, Safe Fallbacks & Role Boundary (P0)](PLAN_FIX_UI_01_TRUTHFUL_UX.md)**
   - Khắc phục giao diện nhanh, giải quyết toàn bộ lỗi hiển thị số giả và thiếu sót về vai trò.
2. 📄 **[Module 2: Store Manager Persistence, Shared Inventory & Audit Scope (P0)](PLAN_FIX_UI_02_MANAGER_PERSISTENCE.md)**
   - Tái cấu trúc cơ chế lưu trữ sản phẩm và tồn kho, loại bỏ sự mất đồng bộ giữa Manager và AI Chatbot.
3. 📄 **[Module 3: Ops Console Observability, Benchmark Importer & Telemetry Integrity (P1)](PLAN_FIX_UI_03_OPSCONSOLE_INTEGRITY.md)**
   - Làm sạch số liệu nghiên cứu, đảm bảo báo cáo khoa học và chỉ số thực nghiệm chuẩn xác 100%.
4. 📄 **[Module 4: Khôi Phục Lịch Sử Chat & Hội Thoại Tiếp Diễn (P0)](PLAN_FIX_UI_04_CHAT_HISTORY_RESUME.md)**
   - Khôi phục phiên chat sau khi F5/mở lại trang, tiếp nối trí nhớ đa lượt cho AI và thêm giao diện lịch sử chat.

---

## 3. Thứ Tự Thực Thi Khuyến Nghị

* **Bước 1**: Triển khai ngay **Module 1 (Truthful UX)**. Bước này an toàn tuyệt đối, không làm thay đổi DB schema, loại bỏ ngay cảm giác "số ảo" cho người dùng khi mở trang web.
* **Bước 2**: Triển khai **Module 2 (Persistence & SSOT)**. Tạo bảng `products` persistent, nối `check_inventory` vào Catalog và mở rộng route Audit cho Manager.
* **Bước 3**: Triển khai **Module 3 (Ops Telemetry)**. Sửa importer và cập nhật giao diện `opsconsole` để phục vụ lấy số liệu thực nghiệm cho Luận văn.
