# Phase 5 Fix A — Store Manager navigation & demo-order cleanup

**Trạng thái:** Implementation, unit/integration/UI regression tests (`SQLite` + `PostgreSQL/pgvector` + `tests/test_public_session.js`), và 5 contract checks đã hoàn tất trên nhánh cô lập `fix/phase5-fix-a-manager-nav-order-cleanup` (base `ef40d131ef9244fa51844ae8990a05888990cdc8`). `FIXA-DEPLOY2` (one-time EC2 DB cleanup cho đơn demo `O-819126`) giữ trạng thái **PENDING** cho tới khi chủ dự án chạy quy trình read-only tenant inventory → verified backup → dry-run exact-tuple → `--execute` qua AWS SSM Session Manager.

Phase 5 Fix A là một nhánh xử lý riêng, có phạm vi đóng, cho hai vấn đề được báo cáo: (1) manager khó quay lại trang tổng quan sau khi vào phần hàng hóa/danh mục; (2) đơn demo đã giao còn hiện tên sản phẩm cũ sau khi manager sửa tên sản phẩm P-602 trong database. Đây **không phải** việc triển khai toàn bộ P5-DM, không sửa lại acceptance P5-E, và không mở bug hunt ngoài hai mục này.

## Tài liệu chuẩn và thứ tự đọc

1. [Review và phân tích hiện trạng](PHASE_5_FIX_A_REVIEW_2026-10-20.md) — phân biệt điều đã thấy trên screenshot với điều đã xác minh trong source; ghi rủi ro dữ liệu.
2. [Acceptance criteria](PHASE_5_FIX_A_ACCEPTANCE_CRITERIA.md) — điều kiện đóng phase, CI, deploy và DB cleanup.
3. [Execution handoff](PHASE_5_FIX_A_EXECUTION_HANDOFF.md) — có **trigger prompt cụ thể ngay đầu file** để gửi Argon làm một lượt.
4. [Evidence template](PHASE_5_FIX_A_EVIDENCE.md) — điền SHA, CI, deploy, UI regression, backup và kết quả thao tác dữ liệu; không ghi PASS nếu chưa có bằng chứng.

## Quyết định phạm vi đã khóa

- Giữ sản phẩm **P-602** trong catalog. Ảnh do chủ dự án cung cấp ngày 2026-10-20 cho thấy tên mới **“Quần tây đen hàn quốc”**, giá 520.000₫, tồn kho 40, các biến thể Đen/Size S–L và bảo hành 90 ngày. Đây là bằng chứng ảnh do người dùng cung cấp, chưa phải truy vấn độc lập từ DB.
- Đối tượng cần xử lý là **đơn demo cũ O-819126** cùng bản chụp tên cũ trong đơn; dữ kiện người dùng đã cung cấp trước đó: khách demo `CG-d9b82ffe`, sản phẩm P-602, trạng thái đã giao, tổng 520.000₫. Source tạo ID demo động, vì vậy không được giả định mã này là seed cố định hoặc xóa theo `order_id` toàn cục.
- Chỉ được xóa đúng đơn sau khi xác minh tenant và toàn bộ tuple kỳ vọng ở môi trường đích. Nếu không có đúng một bản ghi khớp, phải dừng và báo cáo, không thay bằng đơn “gần giống”.
- Không xóa P-602, P-603, khách hàng/tài khoản, đơn O-819125/O-819127, hoặc bất kỳ đơn/dữ liệu thật hay không thuộc tuple được duyệt. Không đổi giá, tồn kho, biến thể hay tên mới của P-602.
- Giữ nguyên audit/security history append-only. Bảo toàn cơ chế chống replay bằng purge tombstone/idempotency guard; không tuyên bố mọi bản ghi lịch sử bất biến đã biến mất. Mục tiêu là đơn không còn trong các luồng nghiệp vụ/UI đang hoạt động và không tự tái tạo.

## Liên kết tới roadmap cấp dự án

Xem [acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md), [current status](../CURRENT_PROJECT_STATUS.md), [roadmap](../PLAN_ROADMAP_INDEX.md), [Phase 5 index](../phase5/README.md), [Phase 5 plan](../phase5/PHASE_5_PLAN.md), và tài liệu nền P5-DM: `../phase5/PHASE_5_DM_STORE_DATA_MANAGEMENT_PLAN.md`, `../phase5/PHASE_5_DM_IO_AND_RETENTION_CONTRACT.md`, `../phase5/PHASE_5_DM_ACCEPTANCE_CRITERIA.md`, `../phase5/PHASE_5_DM_EXECUTION_HANDOFF.md`.

Phase 5 Fix A có thể chạy như một remediation độc lập, nhưng **không** chứng minh P5-E, P5-DM, G4/G5 hay readiness cho performance.
