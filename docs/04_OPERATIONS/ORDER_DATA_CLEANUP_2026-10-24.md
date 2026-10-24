# Kết quả dọn đơn demo legacy trên database live

**Ngày ghi nhận:** 2026-10-24 (Asia/Bangkok; output không kèm timestamp chính xác của câu lệnh).
**Nguồn bằng chứng:** output SSM/psql do chủ dự án dán vào cuộc hội thoại. Raw transcript/artifact chưa được lưu trong repo; assistant không tự kết nối EC2/database để xác nhận độc lập.

## Kết quả được output xác nhận

- Hai đơn được purge trong lượt thao tác cuối:
  - `O-757461` — customer `CG-414e57aa`: giữ 1 business-history event, thêm 1 audit event, unlink 1 conversation, tạo 1 tombstone.
  - `O-819126` — customer `CG-d9b82ffe`: giữ 13 business-history events, thêm 1 audit event, unlink 1 conversation, tạo 1 tombstone.
- Global post-check báo `matching_order_rows=0` trên `tenant_schemas_locked=32`; từng target có `remaining_order_rows=0` và không còn matching target orders cho customer tương ứng.
- Các đơn anh em được giữ lại theo post-check: `O-757460`, `O-757462`, `O-819125`, `O-819127`.
- Đơn `O-847064` của `CG-71316139` đã được xóa trong thao tác SQL trước đó; post-check trước đó còn `O-847063` và `O-847065`. Đây là **direct delete riêng**, không có bằng chứng tombstone/audit workflow như hai đơn trên; không gộp vào số purge có tombstone.

## Phạm vi và giới hạn

- Kết quả đóng mục tiêu hẹp: không còn đơn khớp tên legacy **“Quần tây ống đứng tôn dáng”** trong lần global post-check được dán. Không có bằng chứng rằng mọi dữ liệu demo khác trong hệ thống đã được xóa.
- Đây là SQL/psql operation do owner thực hiện; output không chứng minh `scripts/purge_demo_order.py` từ Fix B đã là công cụ tạo hai dòng purge trên, dù PR #45 sau đó đã merge vào `main` tại `ae0a2e417baf0bc8011bdb62fc9cf3f7741aac36`.
- Operation result không kèm snapshot source/image tại thời điểm chạy lệnh, backup/restore evidence, raw SSM transcript, hay kiểm tra UI/search/KPI ngay sau purge. Vì vậy ghi nhận **business-row removal PASS theo owner-pasted DB output**, nhưng không tự đóng toàn bộ formal acceptance của Fix B.
- Với target legacy có `product_id=NULL`, liên hệ với catalog `P-602` chỉ là đối chiếu legacy-name/price, không phải foreign-key provenance. Catalog `P-602` không bị yêu cầu xóa.
- Không chạy lại purge theo tên rộng. Trước thao tác khác phải query read-only và dùng đúng target tuple; các dòng đã có tombstone không được coi là lệnh cần chạy lại.

## Nguy cơ tái tạo demo data — xử lý riêng

Ở merged `main` baseline `ae0a2e417baf0bc8011bdb62fc9cf3f7741aac36` (cũng như `83bee6c5c42d9996a3230208d30ec6e6f0c5de2e` trước đó), Google login trong `persistent-demo` vẫn gọi `bstore.seed_demo_sample_orders(cid, db=bdb)` cho khách đủ điều kiện chưa có đơn và chưa có tombstone. Hàm seed trả về sớm khi customer đã có order hoặc có purge tombstone; do đó tombstone của `O-757461` và `O-819126` chặn reseed cho chính hai customer đó, nhưng customer mới/zero-order khác (hoặc tài khoản từng xóa hết đơn mà không có tombstone) vẫn có thể nhận bộ 3 đơn mẫu khi đăng nhập Google nếu chưa phát hành bản vá code. Xóa row hiện hữu **không** đồng nghĩa tắt seeding, cũng không chứng minh toàn hệ thống không còn dữ liệu demo.

Workstream khắc phục end-to-end (review toàn bộ seed call sites, gỡ tự tạo đơn mẫu khỏi `PersistentSessions.login_google()`, điều chỉnh nhãn số lượng đơn persistent UI trung thực, regression tests SQLite/PostgreSQL/JS, independent review, PR/CI, official deploy và xác minh runtime read-only) đã được merge qua [PR #46](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/46) vào `main` tại `146401f1831b81d5af4a110f6ddc06e50465b9a8` và deploy chính thức lên EC2 qua run [`40089312937`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40089312937) (`deploy` job `120858580750`, image `629089420698.dkr.ecr.us-east-1.amazonaws.com/retailops@sha256:25193c65e52e7cf7ec41a3a366fa3f76d63c034f686232f405affa04cf1eab63`), với `GET /healthz`, `GET /` (`data-data-mode="persistent-demo"`) và `GET /app.js` (SHA-256 `708b9ec3...`) đã xác minh read-only trên `https://retailops.98-93-228-155.sslip.io`; bước đối chiếu trực quan bảng Orders trong phiên Chrome đã đăng nhập dành cho chủ dự án (xem chi tiết tại [DEMO_ORDER_SEEDING_REMEDIATION_HANDOFF_2026-10-24.md](../phase5/DEMO_ORDER_SEEDING_REMEDIATION_HANDOFF_2026-10-24.md)). Không đổi `data_mode` thành `production/live` như workaround.

## Liên kết

[Current project status](../CURRENT_PROJECT_STATUS.md) · [Acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md) · [Roadmap](../PLAN_ROADMAP_INDEX.md) · [Auto-seed remediation handoff](../phase5/DEMO_ORDER_SEEDING_REMEDIATION_HANDOFF_2026-10-24.md) · [Phase 5 plan](../phase5/PHASE_5_PLAN.md) · [Phase 5 index](../phase5/README.md) · [Documentation index](../README.md).
