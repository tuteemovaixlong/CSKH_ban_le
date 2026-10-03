# BÁO CÁO TIẾN ĐỘ & TRẠNG THÁI HỆ THỐNG RETAILOPS 2026

> **Trạng thái:** ACTIVE OPERATIONAL STATUS & EVIDENCE REPORT<br>
> **Audit basis / Documentation baseline reviewed:** `b93eb5a`<br>
> **Application snapshot đối chiếu:** Nhánh `main` tại commit `c6c7a1a`<br>
> **Kiểm thử & CI:** 429 unit tests PASS (0 failures, 0 errors, 50 skipped across 479 total tests cục bộ; skip do không có PostgreSQL local); GitHub Actions CI Run 37132194550 trên nhánh feature/module-2.5-pr-a, code SHA `766a594` (PostgreSQL 16 container thật & Caddy live): host suite **479/479 PASS, 0 SKIP**; packaged container suite **478 PASS / 1 SKIP trên 479 tests** (0 failures), 4/4 cổng hợp đồng PASS 100%<br>
> **EC2 Host:** `retailops-dev` / `i-0fd116d8927d0e412` / **t3.large** (Sẵn sàng tắt máy sau phiên làm việc để tối ưu chi phí cloud)<br>
> **Deploy status:** Main baseline đã có container build/live rolling deploy PASS; candidate `feature/module-2.5-pr-a` chưa deploy lên EC2 theo mục 2.9; instance sẵn sàng kích hoạt lại khi bật.<br>
> **Lộ trình kỹ thuật tổng thể:** Xem chi tiết tại [PLAN_ROADMAP_INDEX.md](PLAN_ROADMAP_INDEX.md)<br>
> **Kế hoạch đợt build tiếp theo:** [PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md)<br>
> **Báo cáo sự cố & bàn giao:** [INCIDENT_RECOVERY_2026-09-21.md](INCIDENT_RECOVERY_2026-09-21.md) và [SESSION_HANDOFF_2026-10-03.md](SESSION_HANDOFF_2026-10-03.md)

---

## 1. BẢNG ĐỐI CHIẾU TIẾN ĐỘ 6 MODULE THEO KHUNG MINH CHỨNG (EVIDENCE RUBRIC)

Theo chuẩn phân cấp minh chứng của [`RELEASE_MANIFEST.md`](RELEASE_MANIFEST.md) (`L1`: Automated tests; `L2`: Docker build/publish; `L3`: Live deployment; `L4`: Real-model E2E artifacts):

| Module | Tên Module | Mức Triển Khai | Cấp Minh Chứng (Evidence) | Tồn Đọng Kỹ Thuật Chính (Gaps) |
| :--- | :--- | :--- | :--- | :--- |
| **Module 1** | **Hệ Thống Lõi TMĐT, 6 SOPs & MCP Server** | **IMPLEMENTED** | **L1/L3 hỗn hợp** *(353+ tests PASS, Staff Desk & Manager SSOT healthy)* | Đã hoàn tất Phase 1.1 (Truthful UX) và Phase 1.2 (Store Manager Persistence & Shared Catalog SSOT: bảng `products`, `product_variants` vào PostgreSQL v4 / SQLite v3, đồng bộ `check_inventory`, `dispute_agent`, audit events toàn shop). Còn tồn đọng các ca rò rỉ context F04–F06. |
| **Module 2** | **Đo Baseline Benchmark Cơ Sở & Ops Console** | **IMPLEMENTED** | **L1/L3 hỗn hợp** *(250 ca offline 100% Routing, 19/19 Ops Console tests OK)* | Hoàn tất Phase 1.3 (`PLAN_FIX_UI_03`): Bỏ chia 3 token, chi phí chưa đo để Unknown/None, chuẩn hóa nhãn E2E Request Latency, mở rộng allowlist Usage, bổ sung concurrency telemetry (`queue_wait_ms`, `in_flight_inferences`, `overload_429_count`). |
| **Module 2.5** | **Kiểm Thử & Ổn Định Vận Hành (Quality Gate)** | **PR A IMPLEMENTED / ALL ASTRA BLOCKERS RESOLVED & VERIFIED ON CI** | **L1 CI PASS (host 479/479 PASS; container 478 PASS, 1 SKIP; Run ID 37132194550 trên code SHA `766a594`)** *([PLAN_MODULE_2_5_HARDENING_VERIFICATION.md](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md))* | **PR A và Blocker N08 hoàn tất & verify trên CI:** Xử lý triệt để các phát hiện theo review GPT 6 Astra xhigh (preflight check bao phủ 100% memberships, orders, conversations; đồng bộ luồng SQLite migration giữ unresolved_collisions và fail-closed 503; script Caddy maintenance idempotent, bắt lỗi thiếu backup và phục hồi an toàn; kiểm thử E2E cả SQLite lẫn PostgreSQL; P1.1: reconciliation từ chối `target_customer_id` thuộc principal/membership khác trước mọi ghi Business DB, và đóng TOCTOU bằng reservation + kiểm tra lại dưới lock trước khi commit Business). CI Run 37132194550 đạt SUCCESS (host 479/479 PASS; container 478 PASS / 1 SKIP), PostgreSQL 16 và Caddy live container thật. Nhánh `feature/module-2.5-pr-a` sẵn sàng nghiệm thu; chưa merge `main`, chưa deploy. |
| **Module 3** | **Webhook Facebook Messenger (Omnichannel)** | **PLANNED** | **Design-only** *([PLAN_OMNICHANNEL_INTEGRATION.md](PLAN_OMNICHANNEL_INTEGRATION.md))* | Chờ hoàn tất nghiệm thu Module 2.5 trước khi mở cổng webhook tiếp nhận tin nhắn từ Meta API (xếp vào Phase 5 Demo). |
| **Module 4** | **Cổng Quét Mã QR Demo Live** | **PARTIAL** | **L3** *(HTTPS sslip.io, Web mobile responsive)* | Đã có hạ tầng web di động sẵn sàng cho demo; Chưa có module sinh mã QR động / thẻ QR demo (xếp vào Phase 5 Demo). |
| **Module 5** | **Self-Hosted vLLM & Serving Model Agentic** | **IMPLEMENTED / PARTIAL** | **Runtime-dependent** *(Colab L4 vLLM + ngrok)* | Đã tối ưu CUDA Graphs, prefix caching, fp8 kv cache và xử lý an toàn ảnh text-only. Cần hoàn tất chuẩn hóa headroom và timeout gate ở Module 2.5 PR B. |
| **Module 6** | **Đo Lường Evaluation Đối Chứng Luận Văn** | **PARTIAL** | **L1 offline (250 ca) + Runtime note EC2** | Offline Benchmark 250 ca đạt 100.0%; Full Live Benchmark 250 ca trên EC2 và đối chứng DeepSeek sẽ thực thi tại Phase 4 Scientific Evaluation sau Module 2.5. |

---

## 2. NHỮNG CÔNG VIỆC ĐÃ HOÀN THÀNH (COMPLETED EVIDENCE)

### 2.1. Hợp Nhất Master Benchmark & Chuẩn Hóa Hợp Đồng Dữ Liệu
- **Master Dataset 250 kịch bản**: Tổng hợp toàn bộ 250 kịch bản từ `B01.jsonl` đến `B10.jsonl` vào [`evals/scenarios/benchmark_250.jsonl`](../evals/scenarios/benchmark_250.jsonl) (150 ca `dev`, 100 ca `held_out`).
- **Xác thực Schema 9 trường nghiêm ngặt**: Vượt qua toàn bộ hợp đồng của [`scripts/check_eval_dataset.py`](../scripts/check_eval_dataset.py) và `validate_retailops_jsonl.py`.
- **Đạt điểm tuyệt đối Offline Benchmark**: Đạt **250 / 250 PASS (100.0%)** trên bộ định tuyến giám sát (`run_benchmark_eval.py`), độ trễ p50 = 0.10 ms.

### 2.2. Khắc Phục Toàn Diện Phản Hồi Kiểm Toán Lịch Sử (Audit Remediation)
- **State Machine Guard cho Đơn Hàng**: Chặn các bước chuyển trạng thái phi lý (`cancelled -> pending`, `delivered -> pending`) tại `retailops/http/routes.py:249`, kiểm thử tại `tests/test_manager_crud.py`.
- **Băm Base64 Ảnh Vào Digest [F11]**: Băm nội dung ảnh vào token digest trong `retailops/business/application.py:111`, chống replay sai lệch khi gửi ảnh khác nhau cùng tên.
- **Tự Động Ghi Nhận Ticket Handoff [F06]**: Khi kích hoạt `request_human_support`, hệ thống tự động ghi nhận bản ghi escalation vào `conversation_feedback`.
- **An Toàn Cache [F04]**: Duy trì cập nhật `bound.versions` và `bound.knowledge.sources` khi cache-hit; loại bỏ cache cho các công cụ mutation.
- **Tính Toán KPI Thực Tế Từ DB [P0.3 & F07]**: Endpoint `/api/manager/kpis` truy vấn trực tiếp từ bảng `orders`, `conversations` và `conversation_feedback`, loại bỏ số liệu hard-code tĩnh.

### 2.3. Khôi Phục Lịch Sử Chat & Hội Thoại Tiếp Diễn (Chat History Resume)
- Bổ sung `GET /api/conversations`, client tự động resume phiên gần nhất khi F5, khôi phục toàn bộ bong bóng chat, nâng TTL lên 7 ngày và kiểm thử toàn diện tại `tests/test_conversation_resume.py` (4/4 PASS).

### 2.4. Độc Lập Giao Thức MCP Server & Client
- Triển khai `retailops_mcp_server.py` hỗ trợ stdio và SSE port 8002, kết nối qua `retailops/workflow/mcp_client.py` và kiểm thử tự động tại `tests/test_mcp_protocol.py` (100% PASS).

### 2.5. Hoàn Thiện CI/CD & Xác Minh Hợp Đồng Hệ Thống
- Nhánh `feature/fix-ui-02-manager-persistence` vượt qua toàn bộ **353 Python tests OK** (0 failures), đồng thời vượt qua 4 cổng kiểm định nghiêm ngặt:
  - `python scripts/check_docs_contract.py` $\rightarrow$ PASS (4/4 gates).
  - `python scripts/check_deployment_contract.py` $\rightarrow$ PASS.
  - `python scripts/check_eval_dataset.py` $\rightarrow$ PASS.
  - `python scripts/build_agent_notebook.py --check` $\rightarrow$ PASS (Đồng bộ notebook artifacts).

### 2.6. Hoàn Thành Phase 1.1 (Truthful UX) & Phase 1.2 (Store Manager Persistence SSOT)
- **Phase 1.1 (Truthful UX - PR FIX01 - Commit `56fda06`)**: Xóa số 0 tĩnh khi KPI lỗi mạng, bỏ tự gán "Tiêu chuẩn" cho variants, dọn dữ liệu mẫu prefill trong modal quản lý.
- **Phase 1.2 (Store Manager Persistence & Shared Inventory SSOT - PR FIX02)**:
  - Chuyển toàn bộ Catalog & Tồn kho vào database SSOT (SQLite schema `v3`, PostgreSQL schema `v4`).
  - Lớp proxy `CatalogMapping` đồng bộ thời gian thực giữa các session, không bị mất dữ liệu khi restart container.
  - Khớp nối `check_inventory` và `dispute_agent` trực tiếp với tồn kho variant và `warranty_days` trong DB, xóa hoàn toàn số liệu giả định fallback (`stock_qty=6`).
  - Chuẩn hóa `ActorContext` và mở rộng phạm vi Audit Trail toàn shop qua `GET /api/manager/events`.
  - Phân tách DOM ID `btn-sidebar-manager-nav` và `btn-panel-manager-banner` trong giao diện, tự động mở Manager Console khi đăng nhập vai trò `manager`.
  - Khắc phục triệt để 8 phản hồi kiểm toán kỹ thuật từ GPT 6 Astra High: bảo toàn tồn kho variant khi update product; khớp chính xác size/color và phân biệt rõ `stock_unknown`/`variant_not_found`/`out_of_stock`/`in_stock`; vô hiệu hóa cache cross-session khi Catalog thay đổi; đồng bộ bảo hành và chặn proposal cho đơn không tồn tại; tối ưu thứ tự import bảng; backfill toàn bộ `product_id` cho orders; chặn xóa sản phẩm đã có đơn; tách bạch `principal_id` và `customer_id`.
  - Bổ sung 8 automated tests mới tại `tests/test_manager_crud.py`, đạt **353/353 tests PASS**.

### 2.7. Hợp Nhất Vào Main & Ổn Định Toàn Bộ CI/CD Pipeline (Commit `85834d6` & `d7ce461`)
- **Merge PR #33 vào main** (commit `a6ec080`): Tích hợp toàn bộ Phase 1.2 Store Manager Persistence vào nhánh chính.
- **Khắc phục lỗi index psycopg `dict_row`**: Sửa `p_row[0]`, `ev_row[0]`, `v_sum[0]` thành alias name (`SELECT ... AS max_val / total_stock / cnt`) tại `store.py`, `routes.py`, `demo.py`, đảm bảo tương thích 100% cả SQLite và PostgreSQL.
- **Tham số hóa câu lệnh LIKE**: Sửa `WHERE kind LIKE 'product_%'` thành `WHERE kind LIKE ?` kèm param để chống lỗi hiểu nhầm `%` thành format placeholder trong psycopg.
- **Cập nhật Schema Version Assertion**: Đồng bộ test `tests/test_knowledge.py` assert đúng version hiện hành `BUSINESS_SCHEMA_CURRENT = 4`.
- **Đóng gói Docker Seed Data**: Bổ sung `COPY data/deepseek_seed_data.json /app/data/deepseek_seed_data.json` vào `Dockerfile`, đưa bước kiểm thử container trong Deploy to EC2 về trạng thái PASS 100%.

### 2.8. Nâng Cấp Chuỗi Suy Luận ReAct, Sửa Lỗi HTTP 500 & Xử Lý Ảnh Text-Only (Phiên 25/09/2026)
- **Trực Quan Hóa Quá Trình Suy Luận ReAct & Backtracking (Commit `35dfa03`)**:
  - Giao diện Web UI hiện thị trực tiếp quy trình suy luận vòng lặp: Suy luận (Reasoning) $\rightarrow$ Gọi công cụ (Tool Call) $\rightarrow$ Kết quả thực tế (Observation) $\rightarrow$ Đánh giá & Quay lui (Evaluation/Backtracking).
  - Người dùng và đánh giá viên có thể mở rộng khối "Chuỗi suy luận agent & công cụ" để kiểm toán từng bước reasoning của SLM Gemma-4-12B.
- **Khắc Phục Dứt Điểm Lỗi HTTP 500 Khi Xử Lý Đơn/Sản Phẩm Trống (Commit `2d30cdb`)**:
  - Sửa lỗi `AttributeError: 'NoneType' object has no attribute 'get'` trong `_summarize_tool_result` khi context trả về `order=None` hoặc `prod=None`.
  - Kiểm tra kiểu dữ liệu an toàn `isinstance(..., dict)` và bọc phòng vệ exception, ngăn chặn sập endpoint `/api/chat`.
- **Khắc Phục Treo Inference 45.44s & HTTP 503 Khi Gửi Ảnh Cho Text-only Model (Commit `c6c7a1a`)**:
  - Model `yuxinlu1/gemma-4-12B-agentic` là kiến trúc CausalLM thuần văn bản. Việc gửi token Base64 hình ảnh vào vLLM khiến engine bị nghẽn không thể giải mã hình ảnh.
  - Tách bạch hàm `is_vision_model()`: Với text-only models, tự động trích xuất thông tin ảnh thành ngữ cảnh văn bản an toàn (chẳng hạn metadata mô tả ảnh), không gửi chuỗi Base64 làm treo engine.

### 2.9. Tiến Độ Triển Khai PR A & Hiện Trạng Nghiệm Thu N08 (Phiên 02/10/2026 - 03/10/2026)
> **Trạng thái:** PR A đã hoàn tất mã nguồn cốt lõi, kiểm thử fault-injection hai database và giải quyết triệt để các phát hiện blocker theo review của GPT 6 Astra; **N08 ĐÃ HOÀN TẤT & ĐƯỢC XÁC THỰC E2E TRÊN CẢ SQLITE LẪN POSTGRESQL**.<br>
> *(Lưu ý lịch sử: Ngày 02/10/2026, N08 từng bị tạm giữ do môi trường Windows thiếu PostgreSQL live cục bộ; đến phiên 03/10/2026, toàn bộ integration test đã được xác thực 100% xanh trên CI container thật và bổ sung đầy đủ kiểm thử E2E đa backend).*

- **N03 (An Toàn Dữ Liệu & Error Masking - ĐÃ ĐẠT)**:
  - Khi database gặp sự cố gián đoạn (`database_unavailable`), công cụ nghiệp vụ trả về cho người dùng mã lỗi công khai `tool_unavailable` kèm HTTP 503.
  - Ghi log và telemetry nội bộ đầy đủ: `stage=tool_execution`, `tool=get_order`, `status=503`, `original_code=database_unavailable`.
  - Không để lộ chi tiết kỹ thuật cơ sở dữ liệu nội bộ và không commit turn lỗi vào conversation turn store.
- **N08-D (Cấu Hình Live Data Mode & Cách Ly Dữ Liệu Mẫu - ĐÃ ĐẠT)**:
  - Hỗ trợ cấu hình `data_mode="live"` xuyên suốt `Settings` -> `bootstrap` -> `PersistentSessions` -> OAuth callback.
  - Tài khoản live nhận 0 đơn hàng, không seed catalog demo, không seed đơn mẫu. Lỗi provision khách hàng trả về HTTP 503 `customer_provision_failed` và từ chối cấp session.
- **Xử lý Toàn diện Các Phát hiện Blocker N08 theo Review GPT 6 Astra (03/10/2026)**:
  1. **Bao phủ Đầy đủ Mọi Membership & Quarantined Data trong Reconciliation (P1)**:
     - Trong `reconcile_collision()` (`retailops/identity/reconcile.py`), bổ sung preflight validation đối chiếu tập membership trong plan với toàn bộ customer memberships đang va chạm (`incomplete_membership_coverage`).
     - Bổ sung kiểm tra độ bao phủ 100% toàn bộ đơn hàng (`incomplete_order_coverage`) và hội thoại (`incomplete_conversation_coverage`) bị quarantine trong Business DB (`customer_id IN (colliding_customer_id, quarantine_{colliding_customer_id})`).
     - Kiểm tra trùng lặp (`duplicate_membership_reassignment`, `duplicate_order_reassignment`, `duplicate_conversation_reassignment`) và quyền sở hữu.
     - Chỉ xóa `unresolved_collisions` (bao gồm `colliding_customer_id`, `quarantine_{colliding_customer_id}` và các ID tạm thời) sau khi toàn bộ quy trình đối soát hai database đã commit thành công.
  2. **Đồng bộ Luồng Migration SQLite với Coordinator/CLI & Kiểm Thử E2E (P1)**:
     - Trong `retailops/identity/store.py:migrate_legacy_collisions()`, khi xảy ra va chạm dữ liệu mơ hồ (`is_ambiguous = True`), lưu giữ `(tenant_id, customer_id)` trong `unresolved_collisions` (thay vì xóa nhầm).
     - Bảo vệ fail-closed 503 `collision_unresolved` cho mọi nỗ lực login / tạo session của các tài khoản va chạm trước khi có đối soát thủ công.
     - Đồng bộ coordinator `reconcile_collision` và CLI `identity reconcile-collision` tiếp nhận mượt mà các va chạm từ migration SQLite.
     - Bổ sung kiểm thử end-to-end từ legacy DB qua migration đến reconciliation cho cả **SQLite** (`test_n08_a1_two_db_transaction_recovery_and_journal` trong `test_pr_a_correctness.py`) và **PostgreSQL** (`test_identity_v1_legacy_collision_migration_to_reconciliation_on_postgres` trong `test_postgres.py`).
  3. **Script Caddy Maintenance An Toàn Khi Chạy Lặp & CI Kiểm Thử Trực Tiếp (P2)**:
     - Nâng cấp `deploy/switch-maintenance.sh`: Kiểm tra matcher `@auth_maintenance` trước khi sao lưu; nếu đang ở chế độ bảo trì mà gọi `enable` lặp lại $\rightarrow$ báo `AUTH_MAINTENANCE_ALREADY_ENABLED` và không làm hỏng file backup `Caddyfile.normal.bak`; nếu đang ở chế độ bình thường mà gọi `disable` lặp lại $\rightarrow$ báo `AUTH_MAINTENANCE_ALREADY_DISABLED`.
     - Xử lý nghiêm ngặt: Từ chối `disable` và thoát lỗi (exit 1) nếu thiếu file backup cấu hình bình thường; kiểm tra xác nhận reload container Caddy thành công trước khi in trạng thái.
     - CI (`scripts/check_public_https.py`) thực thi trực tiếp script vận hành này với chuỗi kiểm thử lặp: `status` (NORMAL) $\rightarrow$ `enable` $\rightarrow$ `enable` (lặp) $\rightarrow$ `status` (MAINTENANCE) $\rightarrow$ xác nhận 4 route auth trả về 503 $\rightarrow$ `disable` $\rightarrow$ `disable` (lặp) $\rightarrow$ kiểm thử thiếu backup báo lỗi $\rightarrow$ khôi phục và xác nhận 200 `/healthz`.
  4. **Nâng cấp Identity Schema v4 & Journal Bất Biến**:
     - Nâng cấp `IDENTITY_SCHEMA_CURRENT = 4` và `IDENTITY_SCHEMA_COMPATIBLE = (1, 2, 3, 4)`. Migration tự động nâng cấp v1/v2/v3 lên v4, tạo bảng `reconciliation_journal`, index `idx_reconciliation_journal_tenant`, và cột `plan_hash TEXT` trên cả PostgreSQL (`retailops/storage/pg_schema.py`) và SQLite (`retailops/identity/store.py`).
     - Khóa cứng `idempotency_key` với plan hash canonical bất biến; từ chối retry với plan bị sửa đổi (HTTP 409 `plan_conflict`); luôn resume bằng plan lưu trong journal.
     - **Chính sách Rollback an toàn**: Cấm tuyệt đối rollback về image baseline thiếu collision guard; chỉ cho phép rollback về image tương thích hỗ trợ schema v4 và duy trì kiểm tra `unresolved_collisions`. Trong trường hợp khẩn cấp, sử dụng Caddy Maintenance Mode fail-closed 503 cho 4 auth routes.
  5. **P1.1 — Xác minh quyền sở hữu `target_customer_id` trước mọi ghi Business DB**:
     - `retailops/identity/reconcile.py` (`_validate_target_ownership`, `_validate_business_targets`): trong transaction Identity (sau khi chèn journal), từ chối HTTP 409 `target_customer_conflict` nếu đích là colliding/quarantine id, bị gán cho >1 principal trong plan, đang thuộc membership/customer_link của principal khác trong cùng tenant, hoặc (khi chưa được chứng minh thuộc đúng principal) đã có dữ liệu Business DB ngoài phạm vi plan. Kiểm tra Business được chạy lại dưới write lock trước khi ghi.
     - Khi bị từ chối, transaction Identity rollback cả dòng journal: dữ liệu không đổi, collision vẫn `unresolved` (503 `collision_unresolved`), idempotency key không bị kẹt và retry với plan hợp lệ hoàn tất bình thường.
     - Regression test dùng chung `tests/reconcile_target_cases.py`: SQLite (`test_n08_p11_reconciliation_rejects_target_owned_by_other_principal_sqlite`) và PostgreSQL (`test_reconciliation_rejects_target_owned_by_other_principal_on_postgres`).
  6. **P1.1 (đóng nốt) — Chặn TOCTOU giữa kiểm tra ownership Identity và commit Business** (code SHA `766a594`):
     - **Serialization:** mọi transaction ghi Identity đã tuần tự hóa toàn cục (SQLite `BEGIN IMMEDIATE`; PostgreSQL `pg_advisory_xact_lock`). Reconciliation còn khóa thêm `memberships`, `customer_links`, `unresolved_collisions` ở chế độ `SHARE ROW EXCLUSIVE` trên PostgreSQL. Thứ tự khóa luôn là Identity → Business (giống migration legacy) nên không có deadlock.
     - **Reservation:** sau khi kiểm tra ownership ở Step 1, các `target_customer_id` mới được ghi vào sổ `unresolved_collisions` cùng transaction với journal. Mọi luồng ghi membership/customer_link hợp lệ đều tuân thủ sổ này: `create_membership` (mọi role) trả 409 `customer_reserved`; `get_or_create_google_member` không cấp cid đang reserved và trả 503 `collision_unresolved` nếu customer_link trỏ tới cid đang reserved. `migrate_legacy_collisions`, migration `pg_schema` và `import_sqlite` (chỉ vào DB rỗng) chỉ dùng id sẵn có của membership và bỏ qua id unresolved. Lần chạy mới gặp đích đang bị giữ sẽ trả 409 `target_customer_conflict`.
     - **Kiểm tra lại dưới lock trước khi commit Business (Step 2):** mở transaction ghi Identity (giữ lock) → `_recheck_identity_under_lock` (journal vẫn `started` cùng plan hash, collision vẫn còn, reservation còn đủ, ownership hợp lệ) → mở transaction ghi Business → `_validate_business_targets` (gồm `customers` và `conversation_feedback`) → chuyển dữ liệu → cập nhật journal `business_committed` ngay trong transaction Identity đó. Nếu lỗi xảy ra trước khi chuyển dữ liệu ở lần chạy mới, coordinator bù trừ ngay trong transaction Identity: xóa journal và reservation (409 `reconciliation_state_changed` / `target_customer_conflict`). Kết quả: dữ liệu không đổi, collision vẫn unresolved, key không bị kẹt.
     - **Step 3:** kiểm tra lại ownership dưới lock trước khi gán membership/link; khi hoàn tất thì giải phóng reservation. Rủi ro còn lại: SQL ghi thô (bỏ qua store) chen vào giữa Step 2 và Step 3 sẽ bị chặn fail-closed (409, journal giữ `business_committed`, collision vẫn unresolved, member vẫn nhận 503); sau khi gỡ xung đột, resume cùng key sẽ hoàn tất.
     - Test interleaving dùng chung `tests/reconcile_interleaving_cases.py` (chèn hành vi của principal khác ngay trước Step 2 và Step 3) gồm 4 kiểu xâm nhập: membership takeover, customer_link takeover, chèn dòng `customers`, chèn dòng `conversation_feedback`. Test xác nhận snapshot của customers, orders, conversations, agent_turns, conversation_feedback, proposals và business_events không đổi. SQLite: `test_n08_p11_reconciliation_toctou_target_taken_after_preflight_sqlite`. PostgreSQL: `test_reconciliation_toctou_target_taken_after_preflight_on_postgres`. Đối chứng âm: chạy với reconcile.py/store.py cũ thì test lỗi (dữ liệu bị chuyển rồi mới vỡ UNIQUE `customer_links`).
- **Trạng thái kiểm thử & xác thực CI (03/10/2026)**:
  - **Môi trường máy trạm Windows:** Local test suite: 429 PASS, 50 SKIP, 0 FAIL/ERROR trên 479 tests; nguyên nhân từng SKIP cần tham chiếu output của lần chạy tương ứng.
    - Đã kiểm chứng Maintenance Mode fail-closed 503 trên toàn bộ 4 auth routes trong `tests/test_public_web.py`.
    - Đã kiểm chứng Reconciliation Coordinator hai database có journal, plan hash immutability, full membership/order/conv coverage check, recovery sau fault injection, và SQLite E2E trong `tests/test_pr_a_correctness.py`.
    - Đã kiểm chứng PostgreSQL E2E migration $\rightarrow$ reconciliation và preflight coverage checks trong `tests/test_postgres.py`.
  - **Môi trường GitHub Actions CI Runner (PostgreSQL 16 + pgvector container thật & Caddy live):**
    - CI Run 37132194550 (code SHA `766a594`): host suite **479/479 PASS, 0 SKIP** — toàn bộ PostgreSQL integration tests chạy trên PostgreSQL thật, gồm test migration collision sang reconciliation E2E, regression P1.1 và test interleaving TOCTOU P1.1 (SQLite + PostgreSQL đều `ok`); packaged container suite 478 PASS / 1 SKIP (notebook builder không đóng gói trong image).
    - 4/4 cổng hợp đồng (docs, deployment, eval dataset, notebook) đạt **PASS 100%**.
    - Public HTTPS verification: Đạt `PUBLIC_UI_ASSETS_OK`, `PUBLIC_HTTPS_PROXY_COOKIE_FLOW_OK`, `PUBLIC_CADDY_MAINTENANCE_SWITCH_OK` (chuyển đổi Caddy live mode maintenance qua script vận hành với idempotency, missing backup guard, và khôi phục sạch sẽ), `PERSISTENT_HTTPS_ACCOUNT_FLOW_OK`, `POSTGRES_HTTPS_IMPORT_RESTORE_OK`.
  - **KẾT LUẬN NGHIỆM THU ASTRA REVIEW:** Toàn bộ phát hiện Blocker N08 theo review của GPT 6 Astra xhigh đã được xử lý triệt để, đồng bộ state machine đa backend, và kiểm chứng thành công trên cả SQLite lẫn PostgreSQL. Nhánh `feature/module-2.5-pr-a` đã sẵn sàng cho bước nghiệm thu mã nguồn (Code Review Approval); tuân thủ cam kết: **chưa merge vào main, chưa deploy lên EC2, chưa bắt đầu PR B**.

---

## 3. LỘ TRÌNH TRIỂN KHAI TIẾP THEO (NEXT PHASES ROADMAP)

Hệ thống tuân thủ nghiêm ngặt lộ trình phụ thuộc kỹ thuật 7 giai đoạn đã thống nhất:

* **Phase 0**: Documentation Truth & Reconciliation — Đã hoàn tất đồng bộ toàn bộ tài liệu dự án, ma trận trạng thái, loại bỏ số liệu giả định.
* **Phase 1**: Data & Observability Foundation:
  - PR 1.1: [PLAN_FIX_UI_01_TRUTHFUL_UX.md](PLAN_FIX_UI_01_TRUTHFUL_UX.md) (**ĐÃ HOÀN THÀNH** — Merged main `56fda06`).
  - PR 1.2: [PLAN_FIX_UI_02_MANAGER_PERSISTENCE.md](PLAN_FIX_UI_02_MANAGER_PERSISTENCE.md) (**ĐÃ HOÀN THÀNH** — Merged main `a6ec080`, CI/CD stabilized `d7ce461`).
  - PR 1.3: [PLAN_FIX_UI_03_OPSCONSOLE_INTEGRITY.md](PLAN_FIX_UI_03_OPSCONSOLE_INTEGRITY.md) (**ĐÃ HOÀN THÀNH** — Truthful Telemetry & Concurrency telemetry merged).
* **Module 2.5 (Quality Gate)**: System Hardening & Verification ([PLAN_MODULE_2_5_HARDENING_VERIFICATION.md](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md))
  - **PR A**: Context, Cache & Dispute Correctness + Account Identity N08 (**ĐÃ HOÀN TẤT VÀ VƯỢT QUA TOÀN BỘ CỔNG CI** — Sẵn sàng Code Review Nghiệm thu, chưa merge main/deploy EC2).
  - **PR B**: Concurrency, Headroom & Truthful Telemetry (Khắc phục F07, F09, BUG-01, BUG-04).
  - **PR C**: Relational Knowledge & Clean Schema Migration (Khắc phục F10; chính thức thay thế Apache AGE trên EC2 bằng SQL Relational Linkage).
* **Phase 4**: Đo lường thực nghiệm khoa học (Concurrency load test, Đối kháng Gemma-4 vs DeepSeek API trên 250 ca) phục vụ Chương 4 Luận văn.
* **Phase 5**: Demo Enhancements (Facebook Messenger Webhook & Cổng QR Live).
* **Phase 6**: Post-Thesis Scaling (Distillation, LoRA Fine-Tuning, AWS Multi-AZ).

---

## 4. QUY TRÌNH BẬT MÁY & ĐỒNG BỘ IP SÁNG MAI (COLD-START & IP REBIND RUNBOOK)

Khi dừng máy qua đêm và bật lại vào sáng hôm sau, AWS sẽ cấp Public IPv4 mới cho instance `i-0fd116d8927d0e412` (do không dùng Elastic IP). Quy trình 4 bước đơn giản để kích hoạt lại toàn bộ hệ thống:

```
[1. Start EC2 Console] ──> [2. Cập nhật IP trong public.env] ──> [3. Re-run Deploy Job] ──> [4. Verify Live Smoke]
```

### Bước 1: Khởi Động Instance Trên AWS Console
1. Truy cập [AWS EC2 Console (us-east-1)](https://us-east-1.console.aws.amazon.com/ec2/home?region=us-east-1#Instances:instanceState=stopped).
2. Tích chọn instance `i-0fd116d8927d0e412` $\rightarrow$ Nhấn **Instance state** $\rightarrow$ Chọn **Start instance**.
3. Chờ ~1-2 phút cho instance chuyển sang `Running` và lấy địa chỉ **Public IPv4** mới (ví dụ: `X.X.X.X`).

### Bước 2: Cập Nhật IP Mới Vào `public.env` (Qua SSM Session Manager)
1. Trong EC2 Console, chọn instance `i-0fd116d8927d0e412` $\rightarrow$ Nhấn **Connect** $\rightarrow$ Chọn tab **Session Manager** $\rightarrow$ Nhấn **Connect**.
2. Chạy lệnh cập nhật (thay `X-X-X-X` bằng IP mới với dấu gạch ngang, ví dụ IP `54.210.88.99` thì hostname là `retailops.54-210-88-99.sslip.io`):
```bash
sudo sed -i 's/RETAILOPS_PUBLIC_HOST=.*/RETAILOPS_PUBLIC_HOST=retailops.X-X-X-X.sslip.io/' /opt/retailops/public.env
sudo sed -i 's|RETAILOPS_PUBLIC_ORIGIN=.*|RETAILOPS_PUBLIC_ORIGIN=https://retailops.X-X-X-X.sslip.io|' /opt/retailops/public.env
```
3. Kiểm tra lại giá trị đã cập nhật:
```bash
sudo grep '^RETAILOPS_PUBLIC_' /opt/retailops/public.env
```

### Bước 3: Kích Hoạt Triển Khai (Deploy) Tự Động
1. Mở GitHub Actions: [Deploy baseline runner to EC2 #149](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/35892629094).
2. Nhấn nút **Re-run failed jobs** (hoặc vào tab *Actions* $\rightarrow$ *Deploy baseline runner to EC2* $\rightarrow$ *Run workflow* trên nhánh `main`).
3. Workflow sẽ tự động:
   - Đẩy Docker image mới nhất lên AWS ECR.
   - Gửi lệnh qua SSM xuống EC2 để kích hoạt container mới.
   - Cập nhật chứng chỉ TLS Caddy cho domain mới và khởi chạy web service.

### Bước 4: Kiểm Tra Live Smoke & Trải Nghiệm Ứng Dụng
1. Trong SSM Session Manager, chạy kiểm tra nhanh:
```bash
sudo python3 /opt/retailops/live-e2e.py --mode smoke
```
2. Mở trình duyệt truy cập: `https://retailops.X-X-X-X.sslip.io`
   - Đăng nhập tài khoản demo (`customer`, `manager` hoặc Google Login).
   - Kiểm tra Catalog và Inventory đã lưu vĩnh viễn trong DB, trải nghiệm Store Manager Console và Chatbot AI.

---

## 5. TRẠNG THÁI BÀN GIAO PHIÊN LÀM VIỆC & KẾ HOẠCH SÁNG MAI (HANDOFF FOR NEXT MORNING)

### 5.1. Tóm Tắt Trạng Thái Lưu Trữ
- **Nhánh Git:** `feature/module-2.5-pr-a`
- **Head Commit:** `c34c54b4e682346340faf17a08db9a1d40a149b0` (`c34c54b`)
- **Trạng thái working tree:** Clean (100% đã commit và push lên `origin/feature/module-2.5-pr-a`).
- **Trạng thái CI:** GitHub Actions Run ID `37047893366` **SUCCESS** (Job `offline` và Job `colab-python313` đều xanh).
- **Cam kết tuân thủ:** Chưa merge vào nhánh `main`, chưa deploy lên EC2, chưa tạo PR mới.

### 5.2. Các Hạng Mục N08 Đã Xử Lý Dứt Điểm
1. **Blocker 1 (Auth Maintenance Mode):**
   - Proxy Caddy: `deploy/Caddyfile.maintenance` chặn đích danh 4 route: `GET /auth/google/config`, `GET /auth/google/login`, `GET /auth/google/callback`, `POST /api/login` trả về HTTP 503 JSON `maintenance_mode`.
   - App layer: `retailops/http/public.py` kiểm tra `RETAILOPS_AUTH_MAINTENANCE` chặt chẽ (`is True`), trả về 503 fail-closed.
   - Regression test: `test_auth_maintenance_mode_blocks_all_login_routes_with_503` trong `tests/test_public_web.py`.
2. **Blocker 2 (Two-Database Reconciliation):**
   - Điều phối đối soát: `retailops/identity/reconcile.py` (`reconcile_collision`, `get_reconciliation_status`).
   - Bảng journal: `reconciliation_journal` trong `retailops/storage/pg_schema.py` và `retailops/identity/store.py`.
   - Các pha xử lý có journal: `started` -> `business_committed` -> `completed` (hoặc `rolled_back`).
   - Đảm bảo idempotency key và khôi phục sau lỗi (fault recovery/resume) giữa 2 phase Business DB và Identity DB.
   - Unit test: `test_n08_reconciliation_coordinator_journal_idempotency_and_recovery` trong `tests/test_pr_a_correctness.py`.
3. **Blocker 3 (PostgreSQL Test Real Data & Fault Injection):**
   - Test `test_identity_rollback_policy_and_account_reconciliation` trong `tests/test_postgres.py`.
   - Khởi tạo `products`, `orders` thật (`O-REC-001`, `O-REC-002`, `O-REC-003`), `conversations` thật (UUID 36 ký tự) trong Business DB PostgreSQL thật.
   - Tiêm lỗi sau Business DB commit và trong Identity DB commit; xác minh trạng thái fail-closed 503 `collision_unresolved`.
   - Thực thi retry/resume tự động và xác minh 100% tính cô lập dữ liệu (Alice và Bob chỉ xem được tài nguyên của mình, tra cứu chéo trả về 404 Not Found).

### 5.3. Hướng Dẫn Sáng Mai Bật Máy Làm Tiếp
1. **Kiểm tra trạng thái repository:**
   ```bash
   git status
   git log -n 3 --oneline
   ```
   *(Xác nhận đang ở nhánh `feature/module-2.5-pr-a` tại commit `c34c54b`, working tree clean)*
2. **Kiểm tra nhanh 4 cổng hợp đồng:**
   ```bash
   python scripts/check_docs_contract.py
   python scripts/check_deployment_contract.py
   python scripts/check_eval_dataset.py
   python scripts/build_agent_notebook.py --check
   ```
   *(Tất cả 4 lệnh đều phải báo PASS)*
3. **Kiểm tra local test suite (nếu cần chạy lại):**
   ```bash
   python -m unittest discover -s tests -p "test_*.py"
   ```
   *(Kỳ vọng: 470 tests, 424 PASS, 46 SKIP, 0 FAIL, 0 ERROR)*
4. **Bước tiếp theo theo lộ trình dự án:**
   - Xem xét nghiệm thu PR A (Code Review & Merge Decision vào `main`).
   - Bắt đầu triển khai **Module 2.5 PR B** (Concurrency, Headroom & Truthful Telemetry theo kế hoạch [PLAN_MODULE_2_5_HARDENING_VERIFICATION.md](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md)).
