# Review GPT 6 Astra — N08 rollback và CI PostgreSQL

Ngày: **2026-10-02** · Branch: `feature/module-2.5-pr-a` · HEAD: `7d0df0d`

## Prompt ngắn cho Gemini

> Sửa kết luận rollback N08: hạ schema version về 1 giúp baseline khởi động nhưng không giữ collision guard, vì binary `c6c7a1a` không kiểm tra `unresolved_collisions`; không được gọi cách này là rollback an toàn. Chọn phương án giữ khách collision bị khóa hoặc image tương thích có guard, rồi kiểm chứng với đúng binary và PostgreSQL disposable. Có thể commit và push các thay đổi đã kiểm tra lên đúng branch `feature/module-2.5-pr-a`; workflow CI chỉ chạy push trên `main`, nên nếu branch chưa có PR hãy chạy `workflow_dispatch` trên branch đó. Đọc kết quả GitHub Actions và báo SHA + URL run + trạng thái PostgreSQL tests. Không merge, deploy, hoặc tạo PR mới.

## Kết luận

**Có thể chuyển sang bước CI PostgreSQL trên feature branch; chưa READY để merge hoặc triển khai.** Gemini đã đổi tên test v1→v3 và cập nhật báo cáo, nhưng phương án “version rebind” còn lỗ hổng bảo mật khi rollback về baseline.

## Phát hiện chính

### P1 — Version rebind về v1 làm mất hiệu lực collision guard

Baseline `c6c7a1a` chấp nhận schema v1, nhưng các luồng `login`, `create_session_for_membership` và `get_or_create_google_member` của baseline không kiểm tra `unresolved_collisions` hay từ chối customer có ID trùng. Đổi version DB từ 3 về 1 sẽ giúp binary cũ khởi động, đồng thời cho phép tài khoản collision đăng nhập lại vào cùng `customer_id` và dữ liệu đơn hàng dùng chung. Việc giữ bảng mới trong DB không giúp nếu binary cũ bỏ qua chúng.

Vì vậy, claim trong báo cáo và [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md) rằng baseline có thể phục vụ an toàn chỉ bằng đổi version là chưa đúng. Cần giữ maintenance/auth block cho nhóm collision hoặc dùng image đã có guard tương thích; phải kiểm tra bằng đúng artifact rollback.

### P1 — PostgreSQL migration vẫn chưa được chạy

Kiểm tra độc lập trên working tree:

| Kiểm tra | Kết quả |
| --- | --- |
| Full suite | **467 tổng: 422 PASS, 45 SKIP, 0 FAIL** |
| PR A correctness | **50/50 PASS** |
| PostgreSQL integration | **31/31 SKIP** vì thiếu `RETAILOPS_TEST_DATABASE_URL` |
| Docs, deployment, eval, notebook contracts | **PASS** |

Do test PostgreSQL chưa chạy, migration v1→v3/v2→v3 và test staff dùng chung collision ID vẫn chưa có bằng chứng runtime. Workflow `.github/workflows/ci.yml` đã khai báo PostgreSQL service, DSN disposable và chạy full test suite; CI là bước xác minh phù hợp tiếp theo.

### P2 — Push feature branch riêng không tự kích hoạt CI

Workflow khai báo `push` chỉ cho branch `main`, cùng `pull_request` và `workflow_dispatch`. Vì vậy, push lên `feature/module-2.5-pr-a` sẽ không tự chạy nếu chưa có PR. Nếu chưa có PR, cần chạy CI bằng `workflow_dispatch` với ref feature branch rồi đọc kết quả; chưa có Actions run để xác nhận trong review này.

## Độ ổn định và hướng tiếp theo

Đường nâng cấp tiến lên v1/v2→v3 có version rõ và dễ theo dõi. Đường rollback chưa an toàn về hành vi, dù giữ được dữ liệu bảng. **Cho phép Gemini commit/push branch và chạy CI là hợp lý**, giới hạn ở feature branch; sau khi CI PostgreSQL PASS và rollback có guard tương thích, review lại trước khi merge. Không merge/deploy ở bước này.

## Lịch sử cô đọng

Review trước yêu cầu chốt rollback và đổi nhãn test v1→v3. Gemini đã đổi nhãn và thay restore bằng version rebind; review hiện tại phát hiện rebind bỏ qua collision guard của baseline.
