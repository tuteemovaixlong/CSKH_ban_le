# Phase R1 — W6.1b-1.1 Hotfix Handoff (gỡ đơn demo cũ, rollout khi đổi IP, quy trình restore)

> **Trạng thái:** prompt thực thi do owner phát hành ngày 2026-11-09, sau lượt deploy W6.1b-1 lên production cùng ngày. Hotfix nhỏ: sửa code, test và tài liệu vận hành. Không có migration, không đổi schema, không mở W6.1b-2.
> **Nguyên tắc:** chỉ làm 3 mục ở phần 2. Gặp quyết định chính sách chưa có trong tài liệu thì **dừng và hỏi owner**.

## 1. Lỗi gặp khi deploy W6.1b-1 lên production

Production lúc phát hiện: `main` tại `2a21581`, image `…/retailops@sha256:0ef5105a…`, business v9 trên PostgreSQL.

1. **`database purge-legacy-demo` luôn thất bại trên PostgreSQL.**
   - Dry-run trên tenant production báo 8 đơn `retailops_seed` gỡ được, 1 đơn giữ lại vì có yêu cầu hủy, trả hoặc đổi. Lệnh chạy thật trả `database_unavailable (ForeignKeyViolation)` và rollback cả giao dịch; không đơn nào bị xóa.
   - Chẩn đoán trên DB production: cả 10 khóa ngoại trỏ vào `orders` đều có 0 dòng tham chiếu tới 8 đơn. Lỗi nằm ở dòng audit trong `BusinessStore.purge_legacy_demo_orders` (`retailops/business/store.py`, khoảng dòng 1446): `self.log(conn, "system", "legacy_demo_orders_purged", None, …)`. Hàm `log` ghi vào `business_events` với `customer_id = "system"`. Trên PostgreSQL cột này có `REFERENCES customers(id)` (`retailops/storage/pg_schema.py`, dòng 57), trên SQLite thì không.
   - Test hiện có, `test_purge_legacy_demo_cli_dry_run_retains_referenced_orders_and_preserves_sim_orders` trong `tests/test_r1_w6_1b_1_ingest_v9.py`, chỉ chạy trên SQLite nên không bắt được.
2. **`deploy/rollout-public-web.sh` không tự quay về được khi IP công khai đổi.**
   - EC2 không có Elastic IP; sau stop/start, IP đổi từ `35.172.227.184` sang `100.26.48.5`. Lượt deploy đỏ có chủ đích ([run 42582452909](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/42582452909)) dùng để kéo image mới khi DB còn ở v8.
   - Thứ tự trong script: `deploy-runner.sh` đã trỏ `deployed.env` sang image mới; khối "Refresh auto-generated sslip.io hostname" sửa `public.env` rồi chạy `up -d --force-recreate web caddy`, tức tạo lại web **bằng image mới**; sau đó script mới đọc `previous_image` từ container web đang chạy, lúc này đã là image mới.
   - Web mới từ chối khởi động đúng thiết kế (schema v8, fail-closed). Log ra `PUBLIC_WEB_ALREADY_USES_ACTIVATED_IMAGE`, `PUBLIC_WEB_LIVE_VERIFY_FAILED`, rồi `No distinct previous live image is available for automatic rollback`. **Web công khai trả 502 khoảng 8–10 phút** cho tới khi owner khôi phục bằng tay.
   - Cùng khối đó tạo lại caddy bằng compose không có overlay admin, nên Caddy mất mount `/etc/caddy/admin` (log: `Found orphan containers (retailops-web-admin-1)`).
3. **Quy trình restore trong `docs/POSTGRESQL.md` không chạy được từ khi có pgvector.**
   - Lệnh `pg_restore --exit-on-error --no-owner --no-acl --role=retailops` vào DB mới dừng ngay ở `CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA retailops_extensions`: `permission denied to create extension "vector"`. Role `retailops` không phải superuser.
   - Đây cũng là bước dùng khi rollback sau migrate, nên nếu chỉ phát hiện lúc rollback thật thì rất nguy hiểm.
   - Trình tự đã chạy được trên production ngày 2026-11-09 (DB nháp `retailops_rehearsal`): tạo DB owner `retailops`; bằng `postgres` tạo schema `retailops_extensions` và extension `vector` giống `deploy/init-postgres.sh`; lấy TOC bằng `pg_restore --list`, bỏ các dòng `SCHEMA - retailops_extensions`, `EXTENSION - vector`, `COMMENT - EXTENSION vector`; chép dump và TOC vào container postgres; `pg_restore -L <toc> --exit-on-error --no-owner --no-acl --role=retailops`. Kết quả `restore_exit=0`, migrate v9 diễn tập đạt.

## 2. Phạm vi và tiêu chí chấp nhận

| # | Việc phải làm | Tiêu chí chấp nhận (test cô lập) |
|---|---|---|
| 0 | **Sửa audit của `purge-legacy-demo`.** Trong `purge_legacy_demo_orders`, bỏ dòng `self.log(conn, "system", …)`. Thay bằng một sự kiện `legacy_demo_order_purged` cho **mỗi** đơn bị gỡ, ghi bằng `customer_id` thật của đơn đó và `order_id` của đơn, trong cùng giao dịch xóa. Ở `retailops/storage/cli.py`, thêm `removed_order_ids` vào `after_state` của `record_admin_audit` (`action='database.purge_legacy_demo'`). Không đổi luật chọn đơn gỡ hay giữ (W6.1b-D2). Rà các chỗ ghi `business_events` với `customer_id` không phải mã khách thật trong code W6.1b-1 (`retailops/integration/`, `retailops/business/store.py` phần purge và import); sửa cùng cách nếu có, liệt kê trong báo cáo. | Test mới chạy trên **PostgreSQL thật** (cùng cơ chế các test PostgreSQL hiện có trong `tests/test_r1_w6_1b_1_ingest_v9.py`): tenant có ít nhất 3 đơn `retailops_seed`, 1 đơn trong đó có `order_action_requests`. Dry-run rồi chạy thật qua CLI: `PURGE_LEGACY_DEMO_OK`, `removed_count` đúng, đơn có yêu cầu vẫn còn, `business_events` có đúng một dòng `legacy_demo_order_purged` cho mỗi đơn bị gỡ với `customer_id` thật, `admin_audit_log` có `removed_order_ids`. Chạy lại lần hai: `removed_count = 0`, không lỗi. **Báo cáo phải cho thấy test này FAIL trên `main` trước khi sửa** (dán dòng lỗi `ForeignKeyViolation` hoặc tương đương). Test SQLite hiện có vẫn PASS. |
| 1 | **Sửa `deploy/rollout-public-web.sh` khi IP đổi.** (a) Đọc `web_container`, `previous_image`, `running_image_id` **trước** khối sửa hostname sslip.io. (b) Khối sửa hostname chỉ sửa `public.env` và đặt cờ, ví dụ `host_changed=true`; **không** chạy `up` cho web hay caddy. (c) Điều kiện tạo lại web thêm `host_changed`, ngang với `overlay_changed`. Sau khi web mới healthy, tạo lại caddy để nhận host mới; lệnh tạo lại caddy phải kèm `--env-file admin.env -f compose.admin.yaml` khi cả hai tệp tồn tại, giống `compose(admin=True)` trong `deploy/admin-console.py`. (d) `restore_previous` vẫn quay về `previous_image` cũ khi image mới lỗi; khi `host_changed`, sau rollback cũng tạo lại caddy kèm overlay admin. Giữ nguyên kiểm tra digest pinned và repository cho phép. Thêm chú thích ngắn trong script giải thích thứ tự này và nhắc sự cố 2026-11-09. | Test hợp đồng mới, ví dụ `tests/test_r1_w6_1b_1_1_rollout_ip_change.py`: `previous_image=` xuất hiện trước khối sslip.io; khối sslip.io không chứa `up `; có lệnh tạo lại caddy kèm overlay admin có điều kiện, chạy được bằng `bash -c` với tệp giả trong thư mục tạm (cả hai trường hợp có và không có `admin.env`), theo cách `test_r1_w4_deploy_contracts.py` đang làm; điều kiện rollout có `host_changed`. `bash -n deploy/rollout-public-web.sh` đạt. Các test hiện có về script (`test_r1_w4_deploy_contracts.py`, `test_release_source_consistency.py`, `test_deploy_guard.py`) vẫn PASS; nếu phải sửa regex trong test cũ thì giải thích từng chỗ trong báo cáo. |
| 2 | **Sửa tài liệu vận hành.** (a) `docs/POSTGRESQL.md`, mục "Backup, restore và rollback": thay đoạn restore bằng trình tự có pgvector ở phần 1 mục 3, dạng lệnh chạy được trên EC2 (`docker compose … exec -T postgres …`), không chứa URL, mật khẩu hay khóa. (b) `docs/04_OPERATIONS/RUNBOOK.md` mục 7, phần W6.1b-1: bước 1 trỏ tới trình tự restore mới; bước 4 ghi rõ `rollout-public-web.sh` chỉ cập nhật `compose.public.yaml`, nên `compose.postgres.yaml` và `Caddyfile` trên host phải chép từ image mới trước khi rollout, và phải giữ dòng `import /etc/caddy/admin/*.caddy` mà `admin-console.py` đã thêm. (c) `docs/EC2_WEB_WORKFLOW.md`, mục "Khởi động lại sau khi stop/start EC2": thêm một câu rằng trước khi có bản sửa mục 1, lượt deploy đỏ có chủ đích phải sửa `public.env` bằng tay trước; sau bản sửa thì script tự xử lý. | `python scripts/check_docs_contract.py` PASS. Không có link hỏng trong ba tệp. |

Build lại `notebooks/colab_agent.ipynb` nếu bundle nhúng tệp bị đổi.

## 3. Ngoài phạm vi

- Gắn Elastic IP hoặc domain cố định: cần owner duyệt chi phí, để sau.
- Tự động chép `compose.postgres.yaml` và `Caddyfile` từ image trong `rollout-public-web.sh` hay `publish_and_activate.py`.
- Seed đơn mẫu cho tài khoản Google đã có trước W6.1b-1.
- Mọi việc của W6.1b-2.

## 4. Cấm

Merge; push vào `main`; force-push, rebase, reset, stash; đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e; truy cập EC2/SSM, DB production, Colab hoặc LLM thật, dữ liệu khách hàng; thêm dependency khi chưa hỏi owner.

## 5. Kiểm tra và báo cáo

Chạy và báo đúng số pass/fail/skip: `python -m unittest discover -s tests -q`; test JS theo `.github/workflows/ci.yml` bằng Node thật; `python scripts/build_agent_notebook.py --check`; `python scripts/check_docs_contract.py`; `python scripts/check_deployment_contract.py`; `bash -n deploy/rollout-public-web.sh`; `git diff --check`. Test PostgreSQL ở mục 0 phải chạy thật (không skip) trên CI của PR; nếu máy local không có PostgreSQL thì ghi rõ và dựa vào CI.

Báo cáo gồm: file đổi theo từng mục 0–2; bằng chứng test mục 0 FAIL trước khi sửa; kết quả từng lệnh; DONE/BLOCKED từng mục; URL PR và kết quả CI. Thêm một dòng mới vào cột của bạn trong [W1 execution log](W1_EXECUTION_LOG_2026-10-31.md) (ghi rõ là W6.1b-1.1), không sửa dòng cũ.

## 6. Sau khi báo cáo

Claude kiểm chứng một lượt theo tiêu chí ở phần 2; owner quyết định merge. Deploy không cần migration:

1. Trên EC2, kiểm IP công khai khớp `RETAILOPS_PUBLIC_HOST` trong `public.env`.
2. Bật cờ deploy, chạy workflow **Deploy baseline runner to EC2**, tắt cờ. Mong đợi `PUBLIC_WEB_ROLLOUT_OK`, 2 lần `LIVE_E2E_SMOKE_OK`, `ADMIN_CONSOLE_SMOKE_OK`.
3. Trên EC2, tenant production `browser-demo-20260908014853`: `purge-legacy-demo --dry-run` (mong đợi 8 gỡ, 1 giữ là `O-819127`), owner duyệt, rồi chạy thật. Sau đó tenant còn `retailops_seed|1` và `marketplace_sim|128` (hoặc nhiều hơn nếu có đơn mới).
4. Claude ghi biên bản vào [readiness record](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md).
