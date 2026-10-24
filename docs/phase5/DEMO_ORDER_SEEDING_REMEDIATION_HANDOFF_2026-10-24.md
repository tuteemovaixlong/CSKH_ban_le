# Handoff & Báo cáo Thực thi — Chặn tự tạo đơn mẫu khi đăng nhập Google

**Ngày:** 2026-10-24 (Asia/Bangkok)

**Trạng thái:** CANDIDATE REVIEWED (`PASS`, `0` blocker/high-risk findings trên `a0b96db71cc5913800ebe2b40e9ec78561978cf6`) — Đã rà soát toàn bộ seed call sites trên verified `origin/main` (`ae0a2e417baf0bc8011bdb62fc9cf3f7741aac36`), triển khai thay đổi tối thiểu trên nhánh sạch `fix/phase5-stop-google-login-order-autoseed`, hoàn tất regression tests cục bộ & independent review; đang thực thi cổng PR/CI → official deploy → xác minh runtime/UI read-only.

**Phạm vi:** gộp quyết định/chỉnh sửa auto-seed với test, independent review, PR/CI, rollout theo quy trình và xác minh runtime/UI thành một workstream. Đây là việc khắc phục vận hành; không tự mở hoặc đóng P5-K/G4–G7.

## Mục tiêu và ranh giới

Ngăn việc đăng nhập Google tự sinh đơn mẫu cho customer zero-order trong `persistent-demo`, để các đơn demo không xuất hiện lại chỉ vì user đăng nhập. Hành vi mong muốn phải được xác nhận bằng code/test trên candidate và trên image đã deploy; việc xóa row đã thực hiện trước đó không phải bằng chứng cho prevention.

- Giữ nguyên đơn hàng đã tồn tại/import, tombstone và lịch sử/audit; không xóa dữ liệu khác.
- Không xóa catalog seed (`seed_catalog`), product `P-602`, hay các fixture cần cho test/offline benchmark (`BusinessStore.seed()`, `BusinessStore.seed_demo_sample_orders()` chỉ phục vụ setup/test tường minh).
- Không đổi `data_mode` sang `production/live` như workaround; không suy đoán rằng real-customer mode đã sẵn sàng.
- Không chạy SQL ghi/xóa, không chạy lại purge, không chỉnh tay database EC2.
- Bảo toàn nguyên trạng mọi thay đổi người dùng có sẵn tại working tree gốc (`d:/year_2026/Work_2026/agentic_AI/CSKH_ban_le` trên `feat/phase5-sales-simulator-import` tại `dd544800bb087d54a7faf564e723736905620045`).

## Kết quả rà soát toàn bộ đường tạo seed trên `origin/main` (`ae0a2e4`)

| Đường / Call site | Tệp & Vị trí | Hành vi trên `origin/main` (`ae0a2e4`) | Phân loại & Quyết định xử lý |
|---|---|---|---|
| **Google login trong `persistent-demo` (SQLite & PostgreSQL)** | `retailops/identity/persistent.py` (`PersistentSessions.login_google`, kế thừa bởi `PostgresSessions` trong `retailops/identity/postgres.py`) | Khi `not is_live` và `getattr(self, 'seed_sample_orders', True)`, tự động gọi `bstore.seed_demo_sample_orders(cid, db=bdb)` sinh 3 đơn mẫu `O-{700000 + (abs(hash(cid)) % 199990) + 1..3}` (`P-601`, `P-602`, `P-603`) cho customer chưa có đơn và chưa có tombstone. | **NGUỒN GÂY AUTO-SEED KHI LOGIN — ĐÃ GỠ BỎ.** Xóa lệnh gọi `seed_demo_sample_orders` khỏi `login_google()`. Giữ nguyên tạo/cập nhật principal/membership, `INSERT INTO customers ... ON CONFLICT DO NOTHING`, và `bstore.seed_catalog(bdb)` ở non-live mode. |
| **Helper fixture mẫu tường minh** | `retailops/business/store.py` (`BusinessStore.seed_demo_sample_orders`) | Tạo 3 đơn mẫu có gắn sự kiện provenance `demo_sample_fixture_seeded` và tôn trọng `order_purge_tombstones`. | **GIỮ NGUYÊN CHỈ CHO TEST/SETUP TƯỜNG MINH.** Không còn được gọi từ bất kỳ luồng xác thực hay khởi động runtime nào; chỉ các bài test kiểm tra provenance `P5-E-DATA1`/backfill gọi trực tiếp. |
| **Catalog seed** | `retailops/business/store.py` (`BusinessStore.seed_catalog`) | Chỉ `INSERT ... ON CONFLICT DO NOTHING` vào `products` và `product_variants` từ `data/products.json` (gồm `P-601`..`P-604`). Không ghi vào `orders` hoặc `order_items`. | **GIỮ NGUYÊN.** Đảm bảo catalog sản phẩm sẵn sàng mà không sinh đơn hàng. |
| **Provision tenant tường minh** | `retailops/identity/persistent.py`, `retailops/identity/postgres.py` (`provision_tenant(..., seed_demo=False)`), `retailops/identity/cli.py` | Mặc định `seed_demo=False`. Chỉ gọi `store.seed()` khi operator truyền cờ `--seed-demo` tường minh hoặc trong script dev/test offline (`scripts/get_login_token.py`, `scripts/run_live_benchmark_http.py`). | **AN TOÀN — GIỮ NGUYÊN.** Không tự chạy khi login hoặc rollout. |
| **Guest session (`synthetic-demo`)** | `retailops/identity/demo.py` (`GuestSessions.session` dòng 145–146) | Chỉ dùng khi `RETAILOPS_DATA_MODE=synthetic-demo` (cookie `__Host-retailops_session`, DB SQLite tạm `<sid>.sqlite3` gắn `C-001`). Khi mở session lần đầu hoặc mở lại sau process restart (`sid not in self.apps`), gọi `store.seed()` (`INSERT ... ON CONFLICT DO NOTHING`, có tôn trọng `order_purge_tombstones`). | **TÁCH BIỆT HOÀN TOÀN VỚI `persistent-demo` — BÁO CÁO RIÊNG, KHÔNG XÓA.** Không ảnh hưởng tới `PersistentSessions`/`PostgresSessions` hay tài khoản Google; giữ nguyên để bảo toàn chế độ guest demo dùng mã mời và offline tests. |
| **Private loopback / offline benchmark** | `retailops/bootstrap.py` (`build_private_app`), `notebooks/agent_smoke.py`, `tests/*` | Gọi `store.seed()` trên `business.sqlite3` cục bộ cho private interface / Colab smoke / frozen benchmark 250 ca. | **GIỮ NGUYÊN.** Không chạm tới public web hay PostgreSQL trên EC2. |
| **Nhãn UI số lượng đơn non-manager (`#order-count` & `#session-note`)** | `web/app.js` (dòng 134, 643, 1381) & `retailops/http/public.py` (dòng 102) | Frontend không tự sinh dữ liệu đơn hàng, nhưng trước đây hiển thị cố định `<N> đơn mẫu` và `"Dữ liệu mẫu thuộc tài khoản của bạn..."` cho cả tài khoản `persistent-demo` (kể cả khi `0` đơn hoặc đơn import thật). | **ĐÃ SỬA TỐI THIỂU KÈM TEST.** Với `persistentAccount` (`persistent-demo`, `production`, `live`), hiển thị `<N> đơn hàng` (ví dụ `0 đơn hàng`) và bỏ chữ `"mẫu"` ở `#session-note`; giữ nguyên `<N> đơn mẫu` cho guest `synthetic-demo` và `<N> đơn toàn shop` cho `manager`. |

## Thay đổi trong phạm vi PR

1. `retailops/identity/persistent.py`: Loại bỏ lệnh gọi `bstore.seed_demo_sample_orders(cid, db=bdb)` trong `PersistentSessions.login_google()` (áp dụng cho cả SQLite và `PostgresSessions`).
2. `retailops/http/public.py` & `web/app.js`: Gắn `data-data-mode` cho các chế độ persistent (`persistent-demo`, `production`, `live`) và hiển thị trung thực `<N> đơn hàng` thay vì `<N> đơn mẫu` cho tài khoản persistent non-manager.
3. `tests/test_phase5_google_identity.py`: Bổ sung 2 regression tests kiểm tra (a) đăng nhập Google lần 1 và lần 2 cho customer zero-order giữ nguyên `0` đơn trong DB, `GET /api/orders` và Store Manager `store_all` trong khi vẫn seed catalog (`P-602`, `P-604`); (b) bảo toàn đơn hàng import qua `SalesSimulator` và không bao giờ tái tạo đơn đã purge có tombstone (cũng như khi xóa trắng về 0 dòng). Bỏ cờ workaround cũ `self.sessions.seed_sample_orders = False`.
4. `tests/test_postgres.py`, `tests/test_phase5_e_ai_trust_and_governance.py`, `tests/test_order_tool_recovery.py`, `tests/test_public_session.js`: Cập nhật để xác minh `login_google()` luôn để lại `0` đơn trên cả SQLite và PostgreSQL trước khi gọi `seed_demo_sample_orders(...)` tường minh cho các bài kiểm thử provenance `DATA1`/`T06`, đồng thời kiểm thử nhãn `0 đơn hàng` / `1 đơn hàng` vs `0 đơn mẫu`.
5. `notebooks/colab_agent.ipynb`: Đồng bộ bundle nguồn qua `python scripts/build_agent_notebook.py` (`AGENT_NOTEBOOK_SOURCE_SYNC_OK`).
6. `docs/PLAN_GOOGLE_ACCOUNT_RBAC_PRODUCTION.md` & các tài liệu trạng thái/index: Đồng bộ mô tả chính xác (ID hash-based, sạch LF line endings, không mang CRLF churn từ working tree gốc) và ghi nhận rõ ranh giới giữa cleanup một lần với code prevention.

## Lịch sử Handoff gốc & Trigger Prompt (Lưu trữ tham chiếu)

- Working tree gốc tại thời điểm lập handoff: `feat/phase5-sales-simulator-import` (`dd544800bb087d54a7faf564e723736905620045`), được giữ nguyên không sửa đổi.
- Verified GitHub `origin/main` khi tách nhánh sạch: `ae0a2e417baf0bc8011bdb62fc9cf3f7741aac36` (sau khi PR #45 merge).
- Biên bản dọn đơn legacy một lần trên DB live (do owner thực hiện trước workstream này): [ORDER_DATA_CLEANUP_2026-10-24.md](../04_OPERATIONS/ORDER_DATA_CLEANUP_2026-10-24.md).

## Tài liệu liên quan

- [Current project status](../CURRENT_PROJECT_STATUS.md)
- [Roadmap](../PLAN_ROADMAP_INDEX.md)
- [Acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md)
- [Phase 5 index](README.md)
- [Cleanup evidence](../04_OPERATIONS/ORDER_DATA_CLEANUP_2026-10-24.md)
- [Google account/RBAC rollout plan](../PLAN_GOOGLE_ACCOUNT_RBAC_PRODUCTION.md)
- [Account identity/import specification](../PLAN_ACCOUNT_IDENTITY_IMPORT_SPECIFICATION.md)
- [Documentation index](../README.md)
- [Root README](../../README.md)
