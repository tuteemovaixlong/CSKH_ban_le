# Review GPT 6 Astra — Gemini N08 follow-up

**Kết luận: CHƯA SẴN SÀNG để merge/deploy.** Gemini đã xử lý đúng các route đăng nhập trong app và bổ sung test/tài liệu, nhưng còn lỗi nâng cấp schema, an toàn retry, và khả năng vận hành thật.

## Prompt cô đọng cho Gemini

> Chỉ xử lý blocker N08: thêm migration có version để mọi Identity DB v3 hiện hữu có reconciliation_journal; ràng buộc idempotency key với plan bất biến và chỉ resume bằng plan đã lưu; xác minh owner/count cho mọi order, conversation và dữ liệu liên quan, không nuốt lỗi DB hoặc tự đổi principal của Google sub; nối maintenance Caddy và reconciliation vào quy trình triển khai/vận hành thực tế; sửa fault injection để bao phủ crash sau Business commit trước journal update và lỗi sau khi Identity đã chạy các câu lệnh cập nhật. Thêm regression từ schema v3 cũ, chạy Caddy thật và PostgreSQL disposable, cung cấp log CI đúng SHA. Không merge/deploy.

## Phát hiện

### P1 — PostgreSQL Identity schema v3 hiện hữu không có journal mới

IDENTITY_SCHEMA_CURRENT vẫn là 3. Trong pg_schema.initialize, reconciliation_journal chỉ được tạo ở nhánh migrate từ version 1 hoặc 2. Khi database đã ở version 3, không có DDL bổ sung nào chạy; version 3 vẫn được chấp nhận. Vì vậy database đã nâng cấp trước đó có thể thiếu bảng, và reconcile_collision sẽ lỗi ngay khi truy vấn journal.

Test mới chạy trên database CI được khởi tạo với DDL hiện tại; không có test nâng cấp một database v3 cũ không chứa bảng journal.

**Cần đóng:** thêm migration versioned từ v3 hoặc cơ chế additive migration đảm bảo bảng luôn tồn tại; kiểm thử fixture v3 cũ rồi chạy reconciliation thật.

### P1 — Retry có thể hoàn tất bằng một plan khác với plan đã commit ở Business DB

reconcile_collision đọc plan_json từ journal nhưng chỉ dùng status. Nếu lần đầu đã commit Business theo Plan A và journal là business_committed, lần retry cùng idempotency key với Plan B sẽ bỏ qua cập nhật Business nhưng dùng Plan B để cập nhật membership/customer_links trong Identity. Kết quả là quyền sở hữu hai database lệch nhau.

**Cần đóng:** lưu hash/canonical form của plan, từ chối mọi retry có plan khác và resume bằng plan đã lưu trong journal; kiểm tra tenant, collision và membership trước khi ghi.

### P1 — Có thể đánh dấu hoàn tất dù dữ liệu Business cập nhật thiếu hoặc lỗi

Các lệnh cập nhật orders/conversations chỉ lọc theo ID, không kiểm tra customer_id nguồn hay số dòng bị ảnh hưởng. Một ID sai hoặc bản ghi không còn tồn tại vẫn có thể đi tiếp đến xóa unresolved_collisions và đánh dấu completed. Các cập nhật proposals, business_events, agent_turns và conversation_feedback bắt mọi Exception rồi bỏ qua, kể cả lỗi DB thật. External identity cũng dùng ON CONFLICT để đổi principal_id mà không xác nhận sub hiện tại thuộc đúng account.

**Cần đóng:** kiểm tra nguồn sở hữu và row count trước khi bỏ quarantine; chỉ xem bảng là tùy chọn nếu schema xác định rõ điều đó, không nuốt lỗi tùy ý; không tự chuyển Google sub đang gắn với principal khác.

### P1 — Maintenance Caddy và reconciliation chưa có đường vận hành thực tế

deploy/compose.public.yaml vẫn mount ./Caddyfile; deploy/start-public-web.sh chỉ chép và validate Caddyfile thường. Caddyfile.maintenance được chép vào image ứng dụng nhưng không được cài vào thư mục triển khai hoặc chọn bởi compose. Test chỉ kiểm tra nội dung file và WSGI response, không chạy Caddy với cấu hình maintenance. Do đó biện pháp chặn auth khi rollback về binary cũ chưa được chứng minh là có thể bật theo runbook.

Ngoài ra, tìm kiếm repo chỉ thấy reconcile_collision được định nghĩa và gọi từ tests; chưa có CLI/API/vận hành production để nhân viên chạy reconciliation như tài liệu tuyên bố.

**Cần đóng:** cung cấp lệnh/chuyển cấu hình maintenance có thể thực thi, validate bằng Caddy, và một entry point được bảo vệ cho reconciliation; kiểm thử đúng quy trình operator dùng.

### P2 — Fault injection chưa bao phủ các điểm lỗi mà báo cáo mô tả

Fault after_business_commit được gọi sau khi journal đã chuyển sang business_committed, nên chưa kiểm tra crash trong khoảng Business đã commit nhưng journal vẫn là started. Fault during_identity_commit ném lỗi ngay đầu transaction, trước khi Identity có thay đổi; đây chưa phải lỗi giữa hoặc tại commit sau khi các câu lệnh đã chạy. Test retry dùng cùng đối tượng sessions và cùng plan, không mô phỏng khởi động lại tiến trình hay plan bị đổi.

**Cần đóng:** tiêm lỗi đúng giữa các ranh giới commit và sau các Identity update đã được thực thi; khởi tạo coordinator mới để resume từ journal.

## Điểm đã cải thiện và kiểm chứng

- Maintenance guard trong PublicWeb chặn đúng ba route Google auth và POST /api/login; test WSGI cho các route này có.
- Test PostgreSQL mới tạo orders/conversations thật, kiểm tra ownership hai phía và các mã 404 ở BusinessStore.
- Chạy full unittest cục bộ: **470 tests, 46 skipped, 0 failures/errors**. PostgreSQL integration không chạy cục bộ khi thiếu RETAILOPS_TEST_DATABASE_URL; vì vậy lần chạy này không xác nhận test reconciliation trên PostgreSQL.
- Docs contract **PASS 4/4**; deployment contract **PASS**; eval dataset **PASS**; notebook sync **PASS**; git diff --check **PASS**.
- Gemini báo CI run 37047893366 ở SHA c34c54b thành công, 470 tests với 1 skip và 45 PostgreSQL tests pass. Tôi chưa xác minh độc lập được toàn bộ Actions log/artifact; không dùng báo cáo đó để lấp các lỗ hổng schema/retry nêu trên.

## Quyết định

**Chưa sẵn sàng cho merge/deploy hoặc chuyển PR B.** Có thể tiếp tục vòng sửa N08. Sau khi đóng các blocker, cần chạy migration từ schema v3 cũ, fault/restart recovery, Caddy maintenance thật và PostgreSQL integration trên đúng commit rồi review lại.

*File này thay toàn bộ review cũ; chỉ giữ nhận định và lịch sử cần thiết cho lần sửa N08 hiện tại.*
