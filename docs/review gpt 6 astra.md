# Independent Review — Gemini N08 Rollback & Reconciliation

**Kết luận: CHƯA SẴN SÀNG để merge hoặc production.** Chính sách cấm rollback về binary thiếu collision guard là hướng an toàn, nhưng đường maintenance sai route và test mới chưa chứng minh reconciliation dữ liệu giữa hai database.

## Prompt ngắn cho Gemini

> Chỉ xử lý các blocker N08 sau: (1) sửa runbook/Caddy maintenance để chặn đúng các endpoint đăng nhập thực tế (/auth/google/config, /auth/google/login, /auth/google/callback, POST /api/login), có test xác nhận từng route trả 503; (2) làm reconciliation Identity DB ↔ Business DB có journal/idempotency, fail-closed và recovery sau lỗi giữa hai lần commit; (3) mở rộng PostgreSQL integration test với orders/conversations thật, kiểm ownership trước/sau, lỗi sau business commit, lỗi identity commit và restart/retry. Cung cấp log CI chi tiết ở đúng SHA; không tuyên bố 468 PASS nếu log không chứng minh. Không merge/deploy.

## Findings

### P1 — Maintenance Mode chặn sai endpoint

Runbook trong docs/CURRENT_PROJECT_STATUS.md chỉ định chặn /api/auth/*, nhưng retailops/http/public.py định tuyến Google auth tại /auth/google/config, /auth/google/login, /auth/google/callback và token login tại POST /api/login. deploy/Caddyfile hiện chỉ reverse-proxy toàn bộ request, không có matcher hoặc cấu hình maintenance tương ứng. Vì vậy nếu rollback về binary cũ, biện pháp khẩn cấp được mô tả có thể để nguyên các đường đăng nhập/provisioning đang cần khóa.

**Cần sửa:** ghi đúng path/method, cấu hình matcher cụ thể ở proxy hoặc cơ chế maintenance tương đương, và kiểm thử từng route qua adapter/proxy.

### P1 — Test reconciliation không kiểm tra dữ liệu đơn hàng/hội thoại

tests/test_postgres.py::test_identity_rollback_policy_and_account_reconciliation tạo collision trong Identity DB rồi dùng SQL trực tiếp để đổi memberships.customer_id, tạo customer_links, xóa unresolved_collisions và kích hoạt membership. Nó không tạo hay cập nhật orders/conversations trong Business DB, không kiểm external_identities, không gọi runbook/service reconciliation, và không thử đường Caddy rollback. Vì vậy test chứng minh guard và tách mapping Identity sau thao tác thủ công; chưa chứng minh đơn hàng/lịch sử được phân chia đúng hoặc isolation dữ liệu đã khôi phục.

**Cần sửa:** chạy reconciliation thật trên dữ liệu có đơn và hội thoại của cả hai khách; xác nhận mỗi bản ghi thuộc đúng customer_id trước/sau. Tiêm lỗi và restart/retry qua chính quy trình được bàn giao vận hành.

### P1 — Quy trình hai database chưa có recovery an toàn

Runbook chuyển membership và đơn/hội thoại ở hai database riêng rồi mới gỡ quarantine, nhưng không nêu journal, transaction coordinator, idempotency key, checkpoint hay cách phục hồi khi tiến trình dừng giữa chừng. Đây là rủi ro thực tế: trong retailops/identity/store.py, transaction Business DB kết thúc trước các cập nhật Identity DB. Nếu Identity commit lỗi, hai nơi có thể giữ mapping khác nhau; nếu mở lại account/quarantine sớm, quyền truy cập có thể sai.

**Cần sửa:** giữ account bị chặn cho đến khi cả hai phía được đối soát; ghi trạng thái migration bền vững và có bước resume/rollback rõ ràng. Không tuyên bố atomic giữa hai database nếu không có cơ chế bảo đảm điều đó.

## Bằng chứng kiểm tra

- Branch: feature/module-2.5-pr-a; HEAD: 5cc05e4bfcc3716c3aa549f5b5f6275f549ed7da.
- Từ b9389f5 đến HEAD, các thay đổi là status doc, test PostgreSQL, notebook và review; không có thay đổi production code trong phần cập nhật rollback/reconciliation này.
- Chạy full unittest cục bộ: **468 tests, 422 pass, 46 skip, 0 fail/error**. Test PostgreSQL mới nằm trong nhóm bị skip khi thiếu RETAILOPS_TEST_DATABASE_URL, nên không được xác nhận bởi lần chạy cục bộ này.
- scripts/check_docs_contract.py: **PASS 4/4**.
- scripts/build_agent_notebook.py --check: **PASS**.
- git diff --check: **PASS** trước khi ghi review này.
- GitHub Actions run 37042000803 được báo cáo thành công ở SHA trên; trạng thái tổng thể xanh, nhưng log chi tiết của step test không đọc được trong lần kiểm tra này nên con số 468 PASS / 0 SKIP trên CI chưa được xác minh độc lập.

## Quyết định và bước kế tiếp

N08 **chưa sẵn sàng merge/deploy**. Có thể chuyển sang vòng sửa tiếp theo cho ba blocker P1 trên, nhưng chưa nên mở PR B hoặc tuyên bố hoàn tất N08. Sau khi Gemini cập nhật, cần chạy PostgreSQL disposable trên đúng commit, lưu log test đầy đủ, rồi review lại.

*Bản này thay toàn bộ review cũ; chỉ giữ kết luận và các blocker còn liên quan đến lần cập nhật N08 hiện tại.*
