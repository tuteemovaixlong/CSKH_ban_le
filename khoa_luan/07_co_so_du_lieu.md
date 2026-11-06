# Cơ sở dữ liệu RetailOps

Tài liệu để nắm vững database: dùng khi bảo vệ khóa luận và làm căn cứ chốt migration business v9 của W6.1. Kiểm trên code ngày 2026-11-06, `main` tại `d524373`. Phần A là hiện trạng v8 đang chạy production; phần B là thiết kế v9 đề xuất, **chưa được duyệt**.

Nguồn chính: `retailops/storage/pg_schema.py` chứa DDL và các bước migration; `retailops/storage/postgres.py` chứa kết nối, giao dịch và số phiên bản; `retailops/business/store.py` chứa mọi thao tác đọc ghi nghiệp vụ; `retailops/workflow/schema.py` chứa bảng LangGraph.

---

# A. Hiện trạng, business v8 và identity v5

## A1. Tổ chức vật lý

Production chạy **PostgreSQL 16 với pgvector 0.8.6** trong container `postgres`, image ghim theo digest trong `deploy/compose.postgres.yaml`; giới hạn 512 MB RAM, 30 kết nối. Một database tên `retailops`, chủ sở hữu là role `retailops` không có quyền superuser. Dữ liệu nằm trong volume `postgres_data`.

Database chia thành ba loại schema:

| Schema | Số lượng | Chứa gì |
|---|---|---|
| `retailops_identity` | 1, dùng chung | cửa hàng, người dùng, vai trò, phiên đăng nhập, liên kết Google, nhật ký quản trị; 16 bảng |
| `tenant_<32 ký tự hex>` | mỗi cửa hàng một schema | toàn bộ dữ liệu nghiệp vụ, hội thoại, ca, yêu cầu đơn, tri thức, checkpoint; 27 bảng |
| `retailops_extensions` | 1 | extension pgvector, cung cấp kiểu `vector` và toán tử khoảng cách |

Tên schema của một cửa hàng là `tenant_` cộng `storage_key` trong bảng `retailops_identity.tenants`. Hàm `valid_schema` chỉ chấp nhận đúng mẫu `tenant_[a-f0-9]{32}` hoặc `retailops_identity`, nên không thể chèn tên schema tùy ý. Khi tạo schema, quyền `PUBLIC` bị thu hồi.

Môi trường dev và test dùng **SQLite** với cùng logic nghiệp vụ; số phiên bản schema SQLite lệch một bậc so với PostgreSQL. Bộ chạy kịch bản đánh giá dùng SQLite tạm.

## A2. Giao dịch, khóa và an toàn đồng thời

Mọi truy cập đi qua hàm `transaction` trong `postgres.py`. Mỗi giao dịch:

1. `SET LOCAL search_path` về đúng một schema, nên câu SQL của cửa hàng này không thể đọc nhầm bảng của cửa hàng khác.
2. `statement_timeout` 15 giây, `lock_timeout` 5 giây; giao dịch chỉ đọc đặt `READ ONLY`.
3. Giao dịch ghi lấy `pg_advisory_xact_lock` theo tên schema: **mọi lần ghi trong một cửa hàng được xếp hàng tuần tự**. Đổi lại sự đơn giản và đúng đắn là giới hạn thông lượng ghi của một cửa hàng; với quy mô CSKH hiện tại không thành vấn đề.
4. Lỗi PostgreSQL được đổi thành lỗi ứng dụng: `409 read_only_store` hoặc `503 database_unavailable`, không lộ chi tiết kết nối.

Thêm ba cơ chế ở tầng nghiệp vụ:

- **Khóa lạc quan bằng version.** `orders.version`, `cases.version`, `order_action_requests.version`. Người gửi yêu cầu phải gửi kèm version đang thấy; lệch thì `409`. Ví dụ chuyển ca, duyệt yêu cầu, tạo yêu cầu đổi trả.
- **Chống làm trùng bằng khóa duy nhất.** `agent_turns` có `UNIQUE(conversation_id, request_id)`; `case_assist_turns` có `UNIQUE(tenant_id, principal_id, case_id, request_id)`; `imported_events` có `UNIQUE(source_system, event_id)`. Gửi lại cùng mã yêu cầu thì nhận lại kết quả cũ.
- **Chỉ mục duy nhất từng phần** để giữ bất biến: mỗi hội thoại tối đa một ca chưa đóng; mỗi ca tối đa một lượt chuyển người đang chờ; mỗi đơn tối đa một yêu cầu hủy, trả, đổi đang mở.

## A3. Schema `retailops_identity`

| Bảng | Vai trò |
|---|---|
| `tenants` | cửa hàng; `storage_key` quyết định tên schema nghiệp vụ |
| `principals` | một người dùng, không phụ thuộc cửa hàng |
| `memberships` | người dùng thuộc cửa hàng nào, vai trò `customer`, `staff`, `manager`; `customer_id` nối sang khách trong schema nghiệp vụ; vai trò cũ `viewer`, `platform_admin` chỉ còn ở trạng thái bị khóa |
| `credentials`, `sessions` | khóa đăng nhập dạng băm; phiên có hạn và gắn `auth_version` để thu hồi hàng loạt |
| `external_identities` | liên kết tài khoản Google theo cặp `issuer`, `sub` |
| `customer_links`, `unresolved_collisions`, `reconciliation_journal` | ghép người dùng với khách hàng; xử lý trường hợp hai tài khoản trùng một khách |
| `external_customer_mappings` | ánh xạ mã khách của hệ thống ngoài, như sàn, sang khách nội bộ |
| `membership_quota_overrides` | hạn mức gọi model mỗi ngày riêng cho từng thành viên |
| `identity_rate` | bộ đếm giới hạn tần suất, ví dụ 120 request mỗi phút mỗi phiên |
| `provider_daily_usage`, `identity_events`, `admin_audit_log` | đếm lượt gọi model, sự kiện định danh, nhật ký mọi thao tác quản trị kèm trước và sau |

## A4. Schema nghiệp vụ của một cửa hàng

**Bán hàng**

| Bảng | Vai trò | Ghi chú |
|---|---|---|
| `customers` | khách của cửa hàng | chỉ có `id`, `name` |
| `products`, `product_variants` | catalog và biến thể có `size`, `color`, `stock` | `products.variants` là danh sách JSON cũ, `product_variants` là nguồn tồn kho thật |
| `orders` | đơn hàng | `status` chỉ có `pending`, `delivered`, `cancelled`; có `version`, `delivered_at`; **không có** ngày đặt, thanh toán, địa chỉ, hoàn tiền |
| `order_items` | dòng hàng của đơn nhập từ hệ thống ngoài | |
| `imported_events` | mọi sự kiện đã nhận từ hệ thống ngoài, kèm chữ ký | chống nhận trùng |
| `order_purge_tombstones` | dấu vết khi xóa đơn demo | |
| `proposals` | luồng xác nhận hủy đơn đời cũ | giữ để tương thích |

**Hội thoại và ca hỗ trợ**

| Bảng | Vai trò |
|---|---|
| `conversations` | một cuộc chat; có `expires_at` để hết hạn; `order_id`, `product_id` là đơn và sản phẩm đang bàn |
| `agent_turns` | mỗi lượt chat lưu cả danh sách tin nhắn và kết quả dạng JSON, kèm `request_id`, `input_hash` |
| `cases` | ca hỗ trợ: `waiting`, `in_progress`, `resolved`; người giữ ca; các mốc nhắc, hết hạn, hoàn tất; `previous_case_id` khi mở lại |
| `handoff_episodes` | mỗi lần chuyển sang người: `pending`, `resolved`, `customer_closed` |
| `case_feedback_events` | đánh giá của khách, chuẩn hóa thành nhãn `chosen` hoặc `rejected` cho học theo ưu tiên |
| `conversation_feedback` | phản hồi theo hội thoại: đánh giá lượt, CSAT và sự kiện chuyển người; vẫn được ghi khi chuyển người và khi nhân viên trả lời |
| `case_assist_turns` | lượt hỏi của Trợ lý ca, tách theo cửa hàng, người hỏi và ca |

**Yêu cầu hủy, trả, đổi**

| Bảng | Vai trò |
|---|---|
| `order_action_requests` | yêu cầu với `type`, `status`, `refund_status`, lý do, biến thể đích; `CHECK` ràng buộc trạng thái nào thì phải đóng hay mở |
| `order_action_decisions` | nhật ký từng bước duyệt; **trigger chặn UPDATE và DELETE**, chỉ được ghi thêm |
| `order_action_evidence` | ảnh, PDF bằng chứng: kích thước, số trang, SHA-256, kết quả quét ClamAV; tệp nằm trên đĩa, DB giữ đường dẫn |
| `integration_outbox` | sự kiện chờ gửi ra ngoài, có số lần thử và trạng thái `pending`, `published`, `dead` |

**Tri thức, tác tử, vận hành**

| Bảng | Vai trò |
|---|---|
| `knowledge_documents`, `knowledge_chunks` | tài liệu chính sách và các đoạn; `embedding vector(384)` với chỉ mục HNSW cosine; `search_tsv` với chỉ mục GIN |
| `graph_runs`, `graph_checkpoints`, `graph_writes` | checkpoint LangGraph của chat khách để chạy tiếp khi lỗi giữa chừng |
| `business_events` | nhật ký sự kiện nghiệp vụ |
| `provider_daily_usage` | đếm lượt gọi model |
| `retailops_schema` | số phiên bản schema |

## A5. Máy trạng thái

**Ca hỗ trợ.** `waiting` → `in_progress` khi nhân viên nhận ca → `resolved` khi đóng, khách im lặng quá hạn hoặc hoàn tất sau phản hồi. Khách bấm "Tiếp tục" thì mở lại đúng ca đó về `waiting`, sinh episode mới.

**Yêu cầu hủy.** `requested` → `under_review` → `approved` hoặc `rejected`; đóng ở hai trạng thái cuối.

**Yêu cầu trả, đổi.** `requested` → `under_review` → `approved` → `received` → `inspected` → `completed`, hoặc `rejected` ở bước duyệt. Kèm `refund_status`: `not_applicable`, `pending`, `refunded`, `failed`.

Ràng buộc đóng mở được kiểm bằng `CHECK` trong DB, không chỉ trong code.

## A6. Ai ghi vào bảng nào

| Nguồn ghi | Bảng | Hàm chính trong `store.py` |
|---|---|---|
| Server sau mỗi lượt chat của khách | `agent_turns`, `conversations`, `cases`, `graph_*` | `finish_turn`, `customer_message` |
| **Khách bấm nút xác nhận** trên form | `order_action_requests`, `order_action_decisions`, `integration_outbox` | `_create_order_action_request_in_tx` |
| Nhân viên, quản lý | `cases`, `handoff_episodes`, `order_action_*`, `orders` | `claim_case`, `release_case`, `staff_reply`, `transition_order_action_request`, `decide_order_action_refund`, `record_order_action_refund_outcome`, `manager_update_order_status` |
| Server sau mỗi lượt Trợ lý ca | `case_assist_turns` | `save_case_assist_turn` |
| Khách đánh giá | `case_feedback_events` | `record_feedback` |
| Bộ hẹn giờ | `cases`, `agent_turns` | `process_due_case_timers` |
| Cổng tích hợp hệ thống ngoài | `imported_events`, `orders`, `order_items` | `retailops/sales/adapter.py` |
| CLI nạp tri thức | `knowledge_*` | `retailops/knowledge/repository.py` |
| Seed demo | `customers`, `products`, `product_variants`, `orders` | `seed`, `seed_catalog`, `seed_demo_sample_orders` |

**AI không có tool nào ghi vào database.** Tool `prepare_order_action` chỉ đọc điều kiện và mở form; yêu cầu chỉ được tạo khi khách tự bấm nút. Lịch sử hội thoại và checkpoint là do server ghi sau lượt chat, không phải do model quyết định.

Hiện **kết quả hoàn tiền do nhân viên ghi tay** qua `record_order_action_refund_outcome`. Ở v9 việc này chuyển sang nhận từ sự kiện của cổng thanh toán.

## A7. Lịch sử migration

| Phiên bản | Đợt | Thêm gì |
|---|---|---|
| business v1 | nền | `customers`, `orders`, `proposals`, `business_events`, `conversations`, `agent_turns`, `provider_daily_usage` |
| v2 | | bảng LangGraph `graph_runs`, `graph_checkpoints`, `graph_writes` |
| v3 | | `knowledge_documents`, `knowledge_chunks` với pgvector |
| v4 | | `products`, `product_variants`, cột `orders.product_id`; `conversation_feedback` |
| bổ sung Phase 5 | không tăng số | `order_items`, `imported_events`, `order_purge_tombstones`; bên identity thêm `external_customer_mappings`, `membership_quota_overrides`, `admin_audit_log` |
| v5 | W2 | `cases`, `handoff_episodes`, `case_feedback_events`, có backfill ca từ hội thoại cũ |
| v6 | W3 | `orders.delivered_at`; `order_action_requests`, `order_action_decisions` có trigger chỉ ghi thêm, `order_action_evidence`, `integration_outbox` |
| v7 | W3.2 | đổi hàng tổng quát: `exchange_kind` là `other_variant` hoặc `same_variant`, cột biến thể đích |
| v8 | W4 | `case_assist_turns`; bằng chứng nhận PDF, số trang, kết quả quét |
| identity v1–v5 | đến W1 | liên kết khách, xử lý trùng, nhật ký hòa giải; v5 khóa vai trò cũ |

Ứng dụng **từ chối khởi động** khi schema cũ hơn bản yêu cầu. Migration chỉ chạy bằng lệnh operator có cờ `--confirm-preflight --confirm-backup`, theo runbook: backup, diễn tập trên DB nháp, dừng web, backup cuối, migrate, rollout.

## A8. Tự xem dữ liệu trên EC2, chỉ đọc

Vào EC2 bằng SSM, `sudo -i`, `cd /opt/retailops`, tạo mảng `cweb` như ở runbook W5, rồi mở psql trong container:

```bash
"${cweb[@]}" exec -T postgres psql -U postgres -d retailops
```

Trong psql, mở giao dịch chỉ đọc trước khi truy vấn để không thể ghi nhầm:

```sql
BEGIN READ ONLY;

-- Các schema đang có
SELECT nspname FROM pg_namespace WHERE nspname LIKE 'tenant_%' OR nspname LIKE 'retailops_%';

-- Cửa hàng nào ứng với schema nào
SELECT id, name, 'tenant_' || storage_key AS schema, active FROM retailops_identity.tenants;

-- Phiên bản schema
SELECT * FROM retailops_identity.retailops_schema;
SELECT * FROM tenant_xxx.retailops_schema;

-- Kiểm C3 của W6: kho tri thức đã được nạp chưa
SELECT count(*) AS docs FROM tenant_xxx.knowledge_documents WHERE active = 1;
SELECT count(*) AS chunks FROM tenant_xxx.knowledge_chunks;

-- Đơn theo trạng thái
SELECT status, count(*) FROM tenant_xxx.orders GROUP BY status;

-- Ca hỗ trợ theo trạng thái
SELECT status, count(*) FROM tenant_xxx.cases GROUP BY status;

-- Yêu cầu hủy, trả, đổi đang mở
SELECT request_id, type, status, refund_status, order_id
FROM tenant_xxx.order_action_requests WHERE closed_at IS NULL;

ROLLBACK;
```

Thay `tenant_xxx` bằng tên schema lấy ở câu thứ hai. Không dán kết quả có dữ liệu cá nhân vào chat hay tài liệu.

---

# B. Thiết kế business v9 đề xuất cho W6.1

## B1. Nguyên tắc

1. **Dữ liệu nghiệp vụ chỉ vào DB qua cổng tích hợp.** Đơn, thanh toán, vận chuyển, hoàn tiền, catalog do hệ thống nguồn phát sự kiện; RetailOps nhận, kiểm chữ ký, chống trùng, rồi ghi. Hệ thống nguồn trong demo là **sàn ảo** `marketplace_sim/` có kho dữ liệu riêng.
2. **RetailOps không chạm vào tiền.** Thu tiền và hoàn tiền do cổng thanh toán có giấy phép của Ngân hàng Nhà nước thực hiện, theo Nghị định 52/2024/NĐ-CP. RetailOps chỉ lưu tên cổng, mã tham chiếu, số tiền, trạng thái và mốc thời gian. **Không bao giờ lưu** số thẻ, số tài khoản, OTP.
3. **Không lưu địa chỉ đầy đủ.** Chỉ lưu quận, huyện và tỉnh, thành; số điện thoại shipper lưu dạng đã che.
4. **Trạng thái không đi lùi.** Sự kiện cũ đến muộn không được ghi đè trạng thái mới hơn.
5. **Điều kiện do server tính.** Còn bảo hành, đủ điều kiện đổi, giao lại được không là giá trị tính khi đọc, không lưu sẵn.

## B2. Thay đổi bảng `orders`

| Cột | Kiểu | Ràng buộc | Nguồn |
|---|---|---|---|
| `status` | text | thêm giá trị `shipping`; tập mới `pending`, `shipping`, `delivered`, `cancelled` | sự kiện đơn và vận chuyển |
| `ordered_at` | double | not null sau backfill | `order.created` |
| `payment_method` | text | `cod`, `bank_transfer`, `e_wallet`, `card` hoặc null | `order.created` |
| `payment_status` | text | `unpaid`, `paid`, `partially_refunded`, `refunded` | tính từ `payment_transactions` và `refunds` |
| `shipping_fee` | bigint | ≥ 0 | `order.created` |
| `ship_to_area` | text | tối đa 120 ký tự, chỉ quận và tỉnh | `order.created` |
| `delivered_at` | double | đã có, nay được điền | sự kiện vận chuyển `delivered` |

**Luật mới:** đơn `shipping` không mở được yêu cầu hủy tự phục vụ; trợ lý giải thích và chuyển nhân viên. Trả, đổi vẫn chỉ cho `delivered`. Sửa ánh xạ `shipping → delivered` trong `retailops/sales/events.py` thành `shipping → shipping`.

## B3. Bảng mới

**`shipments`**, một dòng cho mỗi vận đơn

| Cột | Ghi chú |
|---|---|
| `shipment_id` | khóa chính |
| `order_id` | FK `orders` |
| `carrier` | ví dụ GHN, GHTK, SPX, Viettel Post, J&T |
| `tracking_code` | duy nhất theo `carrier` |
| `status` | theo bộ trạng thái công khai của GHN: `ready_to_pick`, `picking`, `picked`, `storing`, `transporting`, `sorting`, `delivering`, `delivered`, `delivery_fail`, `waiting_to_return`, `returned`, `cancel`; đối chiếu tài liệu GHN khi viết handoff |
| `current_area` | khu vực hiện tại |
| `shipper_name`, `shipper_phone_masked` | ví dụ `0903.xxx.334` |
| `estimated_delivery_at`, `delivered_at` | mốc thời gian tuyệt đối |
| `delivery_attempts` | số lần giao |
| `updated_at` | thời điểm của sự kiện mới nhất đã áp dụng |

**`shipment_events`**, nhật ký hành trình, chỉ ghi thêm

| Cột | Ghi chú |
|---|---|
| `shipment_event_id` | khóa chính |
| `shipment_id` | FK |
| `occurred_at` | thời điểm sự kiện tại hãng |
| `status`, `location`, `description` | |
| `fail_reason` | khi giao thất bại, ví dụ không liên lạc được |
| `source_event_id` | duy nhất, nối với `imported_events` |

**`payment_transactions`**, mỗi lần thanh toán một dòng vì một đơn có thể thanh toán thất bại rồi trả lại

| Cột | Ghi chú |
|---|---|
| `payment_id` | khóa chính |
| `order_id` | FK |
| `provider` | tên cổng, hoặc hãng vận chuyển khi thu hộ COD |
| `provider_txn_ref` | mã giao dịch phía cổng, duy nhất theo `provider` |
| `method` | như `orders.payment_method` |
| `amount` | bigint, VND |
| `status` | `pending`, `succeeded`, `failed`, `cancelled` |
| `created_at`, `settled_at` | |

**`refunds`**, hoàn tiền do cổng thực hiện

| Cột | Ghi chú |
|---|---|
| `refund_id` | khóa chính |
| `order_id` | FK |
| `request_id` | FK `order_action_requests`, có thể null khi hoàn vì lý do khác |
| `payment_id` | FK `payment_transactions`, null với đơn COD |
| `provider`, `provider_refund_ref` | |
| `amount` | > 0, không vượt số đã thu |
| `channel` | `original_method`, `bank_transfer`, `e_wallet` |
| `status` | `pending`, `processing`, `completed`, `failed` |
| `initiated_at`, `completed_at`, `failure_reason` | |

Cột `order_action_requests.refund_status` giữ nguyên để tương thích, nhưng được cập nhật từ `refunds` thay vì nhân viên ghi tay.

## B4. Sơ đồ quan hệ v9

```mermaid
erDiagram
  customers ||--o{ orders : "đặt"
  orders ||--o{ order_items : "gồm"
  orders ||--o{ shipments : "giao bằng"
  shipments ||--o{ shipment_events : "hành trình"
  orders ||--o{ payment_transactions : "thanh toán"
  orders ||--o{ refunds : "hoàn tiền"
  payment_transactions ||--o{ refunds : "hoàn từ"
  order_action_requests ||--o{ refunds : "theo yêu cầu"
  orders ||--o{ order_action_requests : "hủy trả đổi"
  imported_events ||--o{ shipment_events : "nguồn"
  orders {
    text id PK
    text status "pending shipping delivered cancelled"
    double ordered_at
    text payment_method
    text payment_status
    bigint shipping_fee
    text ship_to_area
    double delivered_at
  }
  shipments {
    text shipment_id PK
    text order_id FK
    text carrier
    text tracking_code
    text status
    int delivery_attempts
  }
  shipment_events {
    text shipment_event_id PK
    text shipment_id FK
    double occurred_at
    text status
    text source_event_id
  }
  payment_transactions {
    text payment_id PK
    text order_id FK
    text provider
    text provider_txn_ref
    bigint amount
    text status
  }
  refunds {
    text refund_id PK
    text order_id FK
    text request_id FK
    text payment_id FK
    bigint amount
    text status
  }
```

## B5. Luồng dữ liệu

```mermaid
flowchart LR
  SIM["Sàn ảo marketplace_sim<br/>kho dữ liệu riêng"] -- "sự kiện ký HMAC" --> IN["Endpoint nhận sự kiện<br/>chỉ trong mạng nội bộ"]
  PAY["Cổng thanh toán giả lập<br/>định dạng webhook của cổng thật"] -- "payment.* refund.*" --> IN
  IN --> AD["Adapter<br/>kiểm chữ ký, chống trùng, không đi lùi"]
  AD --> DB[("Schema của cửa hàng<br/>orders, shipments, payment_transactions, refunds")]
  DB --> TOOL["Tool chỉ đọc<br/>get_order, track_shipment"]
  TOOL --> AGENT["Trợ lý CSKH"]
```

## B6. Migration v9

1. Thêm cột vào `orders`, thay `CHECK` của `status`; backfill `ordered_at` cho đơn cũ bằng thời điểm migrate, ghi rõ là giá trị điền bù.
2. Tạo 4 bảng mới cùng chỉ mục và ràng buộc duy nhất.
3. Thêm trigger chỉ ghi thêm cho `shipment_events`, như `order_action_decisions`.
4. Một giao dịch, chạy lại an toàn, theo runbook như v8.
5. Seed demo được thay bằng kịch bản sự kiện của sàn ảo phát qua adapter. Gỡ dict vận chuyển trong `retailops_tools.py` và `data/mock_shipments.json`.

## B7. Quyết định owner cần chốt

- Thêm trạng thái `shipping` và luật đơn đang giao không tự hủy.
- Danh sách cột của `orders` và 4 bảng mới ở B2, B3.
- Bộ trạng thái vận chuyển theo GHN.
- Cổng thanh toán nào làm mẫu cho định dạng webhook giả lập.
- Có tách sàn ảo thành module W6.1a riêng, làm trước W6.1b phía RetailOps không.
