# N08 — Điều kiện dừng và phạm vi khắc phục P1.1

**Cập nhật gate N08:** 04/10/2026 (snapshot trước khi merge PR A)
**Branch:** feature/module-2.5-pr-a
**Code patch:** `c4e9976` (c4e99769ec46be3d8fe33d272527e9c73b3b0ad1)
**Final docs tree đã qua CI:** `eebe8ed` (eebe8edefd52abb1af86e9e8bdf2173413c25fd1)
**Trigger:** N08-P11-RESOLVE-FAIL-CLOSED
**Trạng thái hồ sơ N08:** VERIFIED trên CI run 37197602401 (head_sha = eebe8ed); đây là kết luận gate trước merge PR A, không phải trạng thái dự án hiện tại. PR #34 sau đó đã merge tại 47ba72a; PR #35 hiện cần xử lý các finding trước khi merge. Trạng thái hiện tại: CURRENT_PROJECT_STATUS.md và PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md.

## Kết quả hiện tại

IdentityStore.resolve() re-raise ApiError do safety guard phát ra; lỗi truy vấn guard được log nội bộ và trả 503 collision_unresolved. Regression trong tests/reconcile_interleaving_cases.py kiểm tra customer-link mismatch, lỗi ba loại lookup, late takeover, API orders không lộ dữ liệu, và đầy đủ toàn bộ các role non-customer (staff, manager, viewer).

Full suite cục bộ: **479 tests, 429 PASS, 50 SKIP, 0 FAIL/ERROR** (50 tests SKIP gồm 36 tests trong `tests/test_postgres.py`, 11 tests trong `tests/test_rag_chat.py`, 2 tests trong `tests/test_knowledge.py`, 1 test trong `tests/test_public_web.py` do thiếu PostgreSQL/pgvector local DSN và Waitress). Local không tuyên bố PostgreSQL PASS; các test này chạy thật và PASS trên CI host suite (0 SKIP).

Docs contract PASS 4/4 checks. Các lệnh check_deployment_contract.py, check_eval_dataset.py và build_agent_notebook.py --check cũng PASS. Cả hai benchmark giữ SHA-256 sau LF normalization: 36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411.

Bằng chứng CI:

| CI run | head_sha | Vai trò | Kết quả |
| --- | --- | --- | --- |
| 37197602401 | `eebe8ed` | **Final tree (canonical)** | SUCCESS — host 479/479 PASS, 0 SKIP; container 478 PASS / 1 SKIP; HTTPS/Caddy/PostgreSQL restore PASS |
| 37196429628 | `c4e9976` | Code patch (lịch sử) | SUCCESS — cùng test counts |

1 SKIP trong packaged container là `test_colab_agent_notebook_sync`, bỏ qua khi `scripts/build_agent_notebook.py` không có trong image.

## Điều kiện dừng

| Gate | Bằng chứng hiện có | Trạng thái |
| --- | --- | --- |
| P1.1a — Late takeover/session cũ | Shared regression chạy local qua SQLite và CI host suite trên PostgreSQL container. | VERIFIED (CI 37197602401) |
| P1.1b — customer_links trỏ tới customer unresolved | Regression mới trong shared harness; PublicWeb không trả orders; CI host suite PASS. | VERIFIED (CI 37197602401) |
| P1.1c — lỗi safety lookup | Fault injection cho unresolved_collisions, customer_links và membership count; trả fail-closed 503; CI host suite PASS. | VERIFIED (CI 37197602401) |
| P1.1d — ranh giới role | Staff, manager và viewer đã có regression đầy đủ trong shared harness; resolve thành công, đúng role; CI host suite PASS. | VERIFIED (CI 37197602401) |
| P1.2 — SQLite migration/coordinator | E2E SQLite + PostgreSQL integration PASS trên CI. | VERIFIED (CI 37197602401) |
| CI cuối và đồng bộ docs | Full suite và PostgreSQL integration xanh trên final tree `eebe8ed`; code patch `c4e9976` có CI lịch sử 37196429628. | VERIFIED (CI 37197602401) |

**Điều kiện dừng N08 ĐÃ ĐẠT ĐẦY ĐỦ tại thời điểm gate này được nghiệm thu.** PR #34 sau đó đã merge; PR #35 là giai đoạn tiếp theo và đang chờ sửa theo review độc lập. Tài liệu này chỉ lưu kết quả N08; không dùng các trạng thái merge/deploy ở phần lịch sử bên dưới làm trạng thái hiện tại.

## Trigger và phạm vi Gemini

**Trigger bắt buộc:** N08-P11-RESOLVE-FAIL-CLOSED

**Đọc trước:** Tài liệu này, PLAN_MODULE_2_5_HARDENING_VERIFICATION.md, PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md, retailops/identity/store.py, retailops/core.py, retailops/http/routes.py, tests/reconcile_interleaving_cases.py, tests/test_pr_a_correctness.py và tests/test_postgres.py.

**Cho phép sửa:** Regression tests trong tests/reconcile_interleaving_cases.py và test wrappers hiện có. Chỉ sửa retailops/identity/store.py nếu test chứng minh còn lỗi thực tế. Notebook chỉ đồng bộ nếu nguồn thay đổi. Cập nhật status docs sau khi có kết quả.

**Ngoài phạm vi:** PR B, schema/migration, benchmark/dataset, cấu hình deploy, merge/deploy, hoặc tệp ngoài allowlist nếu chưa review phạm vi.

## Known limitations

- Collision chưa xác định chủ sở hữu tiếp tục ở quarantine/unresolved cho đến khi có bằng chứng từ operator.
- Identity DB và Business DB không có distributed ACID; journal/idempotency/recovery hỗ trợ fail-closed và resume, không đảm bảo atomic commit xuyên hai database.
- PR B chưa triển khai; concurrency, history retention, ToolCache invalidation, telemetry và OAuth hardening tiếp tục pending.
