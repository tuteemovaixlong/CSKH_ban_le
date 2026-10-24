# Handoff & Báo cáo Thực thi — Chặn tự tạo đơn mẫu khi đăng nhập Google

**Ngày:** 2026-10-24 (Asia/Bangkok)

**Trạng thái:** MERGED & DEPLOYED TO EC2 (`146401f1831b81d5af4a110f6ddc06e50465b9a8`, image `sha256:25193c65e52e7cf7ec41a3a366fa3f76d63c034f686232f405affa04cf1eab63`); READ-ONLY HTTPS `/healthz` + PUBLIC ASSETS VERIFIED; AUTHENTICATED CHROME ORDERS UI CHECK PENDING OWNER BROWSER SESSION.

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

## Bằng chứng Kiểm thử, Independent Review, PR/CI, Rollout & Runtime Read-Only

- **Independent read-only review (Gemini 4 Argon):** Verdict **`PASS`** (`BLOCKER: 0`, `HIGH: 0`, `MEDIUM: 0`, `LOW: 1` đã cập nhật câu chữ doc, `NIT: 2` đã dọn khoảng trắng cuối dòng) trên immutable code/test candidate `a0b96db71cc5913800ebe2b40e9ec78561978cf6` (PR HEAD `189db5240fabe69990e0e2e45b9ff004890ceba0`, code/test tree giữ nguyên).
- **PR & Required GitHub Actions CI (`0 skipped` trên toàn bộ PostgreSQL jobs):**
  - [PR #46](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/46) (`fix/phase5-stop-google-login-order-autoseed` → `main`, base `ae0a2e417baf0bc8011bdb62fc9cf3f7741aac36`, tested merge ref `50baf11312e4530933c88db3e8292672350340d8`) đạt **5/5 checks `SUCCESS`**:
    - [CI `40088640697`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40088640697): [`offline` `120856594646`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40088640697/job/120856594646) trên PostgreSQL 16 + `pgvector 0.8.6` đạt **`Ran 721 tests` → `OK` (`0 skipped`)** trên cả host (`115.064s`) và packaged container `retailops:ci` (`122.421s`), kèm `HEADROOM_ARTIFACT_INTEGRITY_OK`; [`colab-python313` `120856594293`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40088640697/job/120856594293) `SUCCESS`.
    - [Ops Console `40088640680`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40088640680): [`postgres` `120856594180`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40088640680/job/120856594180) đạt **`Ran 19 tests` → `OK` (`0 skipped`)**; hai job `portable` (`120856594319`, `120856594328`) `SUCCESS` (`skipped=2` do chế độ portable không gắn PostgreSQL service).
  - Sau khi merge vào `main` tại **`146401f1831b81d5af4a110f6ddc06e50465b9a8`**, post-merge [CI `40089312939`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40089312939) (`offline` `120858550842`: `721` tests, `0 skipped` trên host + container; `colab-python313` `120858551090`) và [Ops Console `40089312947`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40089312947) (`postgres` `120858551110`: `19` tests, `0 skipped`; `portable` `120858551027`/`120858551180`) đều `SUCCESS`.
- **Official EC2 Deployment:**
  - Workflow [`Deploy baseline runner to EC2` run `40089312937`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40089312937) (`filter` `120858550841` `SUCCESS`, [`deploy` `120858580750`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40089312937/job/120858580750) `SUCCESS` lúc `2026-10-24T11:23:43Z`) trên merged SHA `146401f1831b81d5af4a110f6ddc06e50465b9a8`:
    - Pinned ECR image: `629089420698.dkr.ecr.us-east-1.amazonaws.com/retailops@sha256:25193c65e52e7cf7ec41a3a366fa3f76d63c034f686232f405affa04cf1eab63` (tag `146401f1831b81d5af4a110f6ddc06e50465b9a8-40089312937-1`).
    - Rollout & smoke markers: `PUBLIC_WEB_SOURCE_MATCH=74812fabdd34b2f2bbf1b7f05c1b2db67b5e2c6af9b91f8ad2384f066f079f15`, `PUBLIC_WEB_ROLLOUT_OK`, `LIVE_E2E_SMOKE_OK` (`LIVE_SMOKE_20261024T112246Z.json`, `LIVE_SMOKE_20261024T112317Z.json`), `ADMIN_CONSOLE_SMOKE_OK` (`admin-retailops.98-93-228-155.sslip.io`).
- **Xác minh Runtime/UI Read-Only & Ranh giới Gate Chrome:**
  - Kiểm tra HTTPS read-only trực tiếp tới `https://retailops.98-93-228-155.sslip.io` (không ghi DB, không mở session, không tạo/sửa/xóa đơn):
    - `GET /healthz` → HTTP `200` (`status="ok"`, `version="0.9"`, `data_mode="persistent-demo"`, `storage_backend="postgresql"`, `agent_protocol="retailops-agent-v2"`, `hosting="public-https"`).
    - `GET /` → HTTP `200` với `<body data-auth="cookie" data-data-mode="persistent-demo" data-google-auth="true">`.
    - `GET /app.js` → HTTP `200`, SHA-256 `708b9ec31790fdd2dc51ee5078cdd92a9aaf032f63fd20cc354c278d444c6be2` (khớp 100% `web/app.js` của commit `146401f1831b81d5af4a110f6ddc06e50465b9a8`, có logic `persistentAccount ? ' đơn hàng' : ' đơn mẫu'`).
  - **Gate Chrome có xác thực (không giả lập PASS):** Môi trường thực thi của agent không gắn công cụ điều khiển trình duyệt Chrome và không giữ phiên đăng nhập Google OAuth / mã quản trị viên live. Chủ dự án chỉ cần bấm `Ctrl+F5` trên `https://retailops.98-93-228-155.sslip.io` trong phiên Chrome sẵn có (để làm mới cache `app.js` 300s) và xem read-only danh sách Đơn hàng / `📋 Đơn hàng Shop` để xác nhận trực quan rằng đăng nhập lại không tự sinh đơn mới và các đơn đã xóa không tái xuất hiện (không tạo/sửa/xóa đơn).

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
