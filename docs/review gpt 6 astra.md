# Review GPT 6 Astra — Gemini N08 follow-up

**Ngày:** 03/10/2026
**Kết luận:** **CHƯA SẴN SÀNG merge/deploy hoặc nghiệm thu N08; chưa nên chuyển PR A sang PR B.** Có tiến bộ đáng kể và CI PostgreSQL được báo cáo xanh, nhưng còn một lỗ hổng P1 trong reconciliation có thể bỏ sót thành viên đang dùng chung customer_id, cùng một đường recovery SQLite không nối được vào coordinator.

## Prompt cô đọng cho Gemini

> Chỉ sửa các blocker N08 trên branch hiện tại; chưa merge/deploy và chưa bắt đầu PR B. Trong `reconcile_collision`, bắt buộc kiểm tra plan bao phủ đúng toàn bộ customer memberships đang va chạm và toàn bộ orders/conversations bị quarantine; từ chối nếu thiếu, trùng hoặc sai owner, và chỉ xóa `unresolved_collisions` sau khi đối soát đủ. Đồng bộ migration SQLite `migrate_legacy_collisions` với coordinator/CLI để dữ liệu `quarantine_<id>` có thể được khôi phục an toàn; thêm E2E từ DB legacy qua migration đến reconciliation cho cả SQLite và PostgreSQL. Sửa `switch-maintenance.sh` để enable/disable lặp lại an toàn, không báo disable thành công nếu thiếu backup hoặc chưa reload được; CI phải thực thi chính script này. Đồng bộ trạng thái mâu thuẫn trong `CURRENT_PROJECT_STATUS.md`, chạy lại full suite và CI trên SHA cuối, đính kèm log. Chỉ cập nhật báo cáo trạng thái sau khi các gate đều pass.

## Phát hiện cần xử lý

### P1 — Plan thiếu thành viên có thể gỡ quarantine khi collision vẫn còn

`reconcile_collision()` chỉ kiểm tra các membership được liệt kê trong `plan.reassignments` (`retailops/identity/reconcile.py`, khoảng dòng 146–162); hàm không đối chiếu danh sách đó với **toàn bộ** memberships thuộc tenant/customer va chạm. Cuối giao dịch Identity, hàm xóa bản ghi `unresolved_collisions` dù các membership bị bỏ sót vẫn giữ `colliding_customer_id` (`reconcile.py`, khoảng dòng 300–340).

Đường migration PostgreSQL v1/v2 giữ collision trong `memberships` và tạo `unresolved_collisions` để coordinator xử lý. Nếu operator gửi plan chỉ có một trong hai membership, coordinator có thể cập nhật membership đó rồi xóa cờ unresolved; membership còn lại tiếp tục mang chung customer_id và có thể đăng nhập lại vào cùng dữ liệu. Đây là rủi ro cách ly dữ liệu, không chỉ là thiếu dữ liệu trong báo cáo.

**Điều kiện đóng:** preflight phải chứng minh tập membership trong plan bằng đúng tập cần xử lý; mọi bản ghi phải được gán duy nhất hoặc được giữ quarantine có trạng thái unresolved. Kiểm thử plan thiếu/thừa/trùng membership và xác nhận không xóa unresolved, không cấp session.

### P1 — SQLite quarantine không thể tiếp tục qua reconciliation CLI

Trong `retailops/identity/store.py:migrate_legacy_collisions()` (khoảng dòng 192–253), collision có orders/conversations được chuyển sang `quarantine_<customer_id>`, memberships được cấp customer ID riêng, rồi `unresolved_collisions` bị xóa. Nhưng `reconcile_collision()` yêu cầu bản ghi unresolved cho chính collision (`reconcile.py`, khoảng dòng 89–94) và chỉ chấp nhận order/conversation có owner là collision ID hoặc target ID. Vì vậy trạng thái do migration SQLite tạo ra không được coordinator chấp nhận; CLI `reconcile-collision` có thể dừng ở `collision_not_found`, còn dữ liệu quarantine không có đường phân bổ được kiểm chứng.

Test hiện có kiểm tra quarantine và việc hai tài khoản không thấy order; test coordinator PostgreSQL lại dựng trạng thái collision trực tiếp. Chưa có test end-to-end migration SQLite → reconciliation. Cần thống nhất state machine cho hai backend và chứng minh dữ liệu quarantine được khôi phục hoặc giữ unresolved có thể vận hành.

### P2 — Script Caddy maintenance chưa an toàn khi lặp và chưa được CI chạy trực tiếp

`deploy/switch-maintenance.sh` luôn ghi đè `Caddyfile.normal.bak` khi enable. Nếu enable lần hai trong lúc đã ở maintenance, backup chuẩn có thể bị thay bằng config maintenance; `disable` sau đó không khôi phục normal config. Nếu backup không tồn tại, nhánh disable vẫn reload file hiện tại và in `AUTH_MAINTENANCE_DISABLED`, dù maintenance có thể vẫn bật.

CI hiện kiểm tra `bash -n` và kiểm thử Caddy bằng cách thay/reload file trong script HTTPS; chưa gọi `switch-maintenance.sh` để kiểm chứng enable → status → disable, lặp enable, lỗi reload và thiếu backup. Do đây là emergency fail-closed control, cần kiểm thử chính xác thao tác operator sẽ chạy và chỉ in thành công sau khi xác nhận trạng thái Caddy.

### P2 — Tài liệu trạng thái tự mâu thuẫn

`docs/CURRENT_PROJECT_STATUS.md` phần đầu ghi mọi Astra blocker đã giải quyết, CI pass và PR A sẵn sàng nghiệm thu; mục 2.9 phía dưới vẫn ghi N08 BLOCKED vì PostgreSQL tests bị skip, và phần migration vẫn mô tả Identity schema v3. Các đoạn cũ này làm sai lệch trạng thái bàn giao dù docs contract hiện pass. Cần hợp nhất trạng thái hiện tại với lịch sử được ghi nhãn rõ, không để hai verdict đối nghịch.

### P2 — Full suite Windows chưa ổn định trong lần xác minh này

Chạy hai lần `python -B -X utf8 -m unittest discover -s tests`: mỗi lần **474 tests, 47 skipped, 1 ERROR** do `ConnectionAbortedError [WinError 10053]` trong HTTP tests; mỗi lần lỗi ở test khác. Hai test lỗi khi chạy full suite đều **pass khi chạy riêng**. Đây chưa chứng minh regression sản phẩm, nhưng cũng không thể báo full suite local là pass; cần xác định/ghi nhận ổn định môi trường hoặc test harness. 47 test skip gồm nhóm PostgreSQL do máy này không có test DSN, nên chúng không được xác nhận bởi lần chạy local.

## Điểm tốt và bằng chứng

- Identity schema được nâng lên v4; migration PostgreSQL v3→v4 tạo journal và `plan_hash`. Có integration test tạo trạng thái v3 thiếu journal rồi xác nhận startup nâng cấp; CI được Gemini báo cáo chạy PostgreSQL 16.
- `reconcile_collision()` ràng buộc idempotency key với plan hash, resume bằng plan lưu journal, kiểm tra owner cho các order/conversation được khai báo, chặn Google `sub` đang gắn principal khác, và có fault injection sau các ranh giới commit. Đây là cải thiện kiến trúc đúng hướng.
- Gemini báo CI run `37095321746` thành công tại SHA `872b8ee`; branch HEAD hiện là `abef8e9`, và diff `872b8ee..HEAD` chỉ gồm `docs/CURRENT_PROJECT_STATUS.md` và `docs/SESSION_HANDOFF_2026-10-03.md`. Tôi chưa mở/đối chiếu độc lập log Actions từ GitHub trong lượt này, nên ghi nhận đây là bằng chứng được báo cáo, không phải xác minh remote độc lập.
- Kiểm tra cục bộ: docs contract **PASS 4/4**; deployment contract **PASS**; eval dataset **PASS**; notebook sync **PASS**; `git diff --check` **PASS**. SHA-256 chuẩn hóa LF của cả hai benchmark khớp hash đóng băng `36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411`; raw Windows CRLF hash khác nhưng hai file giống nhau.
- Mã đối soát đã tách thành module riêng, migration có version và các bước journal giúp nâng cấp dễ kiểm soát hơn. Tuy nhiên, hai đường migration chưa được nối E2E; chưa thể gọi tích hợp đa backend ổn định.

## Phạm vi và quyết định bước tiếp theo

Đặc tả `PLAN_ACCOUNT_IDENTITY_IMPORT_SPECIFICATION.md` vẫn là kiến trúc đích sau Module 2.5: import JSONL/XLSX và các hợp đồng RBAC/import còn mang nhãn planned. Luồng migration hiện tạo ID `cust_` từ SHA-256 rút gọn 32 ký tự (128-bit), không phải toàn bộ kiến trúc UUIDv4/import đã hoàn tất. Không nên dùng kết quả N08 này để tuyên bố toàn bộ account/import plan đã xong.

**Quyết định:** chặn nghiệm thu/merge/deploy PR A cho tới khi P1 được đóng và kiểm thử E2E trên cả backend; chạy lại CI trên SHA cuối và cập nhật tài liệu trạng thái. Sau đó review lại PR A. Khi được nghiệm thu/merge mới bắt đầu PR B theo roadmap; PR B vẫn là concurrency, history retention, cache synchronization và OAuth CSRF, không gộp thêm import/RBAC target architecture.

## Lịch sử cô đọng

- Review trước: N08 còn thiếu migration v3→v4, plan bất biến, kiểm tra ownership, đường vận hành maintenance và fault recovery.
- Gemini đã bổ sung các phần này cùng CI PostgreSQL/Caddy; lần review hiện tại phát hiện hai blocker về hoàn chỉnh reconciliation/migration đa backend, một rủi ro script maintenance, tài liệu trạng thái mâu thuẫn và full suite Windows chưa ổn định.

*File này thay toàn bộ nội dung review cũ; chỉ giữ kết luận, bằng chứng và lịch sử tối thiểu cho vòng N08 hiện tại.*
