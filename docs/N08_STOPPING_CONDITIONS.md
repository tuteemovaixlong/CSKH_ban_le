# N08 — Điều kiện dừng và phạm vi khắc phục P1.1

**Cập nhật:** 04/10/2026
**Branch / HEAD được kiểm tra:** feature/module-2.5-pr-a / 4ef078e
**Trigger:** N08-P11-RESOLVE-FAIL-CLOSED
**Trạng thái:** LOCAL VERIFIED trên SQLite; PostgreSQL và CI trên SHA cuối còn chờ.

## Kết quả hiện tại

IdentityStore.resolve() re-raise ApiError do safety guard phát ra; lỗi truy vấn guard được log nội bộ và trả 503 collision_unresolved. Regression trong tests/reconcile_interleaving_cases.py kiểm tra customer-link mismatch, lỗi ba loại lookup, late takeover, API orders không lộ dữ liệu, và đầy đủ toàn bộ các role non-customer (staff, manager, viewer).

Full suite cục bộ: **479 tests, 429 PASS, 50 SKIP, 0 FAIL/ERROR**. Trong đó 50 tests SKIP gồm 36 tests trong `tests/test_postgres.py` và 14 tests trong `tests/test_pgvector_rag.py` do thiếu PostgreSQL local DSN (`RETAILOPS_TEST_DATABASE_URL`). Lần chạy này **KHÔNG tuyên bố PostgreSQL PASS** cục bộ; kiểm thử PostgreSQL được ủy quyền xác thực trên GitHub Actions CI container.

Docs contract PASS 4/4 checks. Các lệnh check_deployment_contract.py, check_eval_dataset.py và build_agent_notebook.py --check cũng PASS. Cả hai benchmark giữ SHA-256 sau LF normalization: 36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411.

CI run 37137791788 trên code SHA fe25f67 là evidence lịch sử trước bản vá hiện tại; không dùng làm bằng chứng cho working tree này.

## Điều kiện dừng

| Gate | Bằng chứng hiện có | Trạng thái |
| --- | --- | --- |
| P1.1a — Late takeover/session cũ | Shared regression chạy local qua SQLite; CI cũ trên fe25f67 không bao gồm patch hiện tại. | SQLite local PASS; final CI pending |
| P1.1b — customer_links trỏ tới customer unresolved | Regression mới trong shared harness; PublicWeb không trả orders. | SQLite local PASS; PostgreSQL pending CI |
| P1.1c — lỗi safety lookup | Fault injection cho unresolved_collisions, customer_links và membership count; trả fail-closed 503. | SQLite local PASS; PostgreSQL pending CI |
| P1.1d — ranh giới role | Staff, manager và viewer đã có regression đầy đủ trong shared harness; resolve bình thường, không bị cản trở bởi customer collisions. | SQLite local PASS; PostgreSQL pending CI |
| P1.2 — SQLite migration/coordinator | Có CI evidence lịch sử trên fe25f67. | Historical PASS; xác nhận lại trong final CI |
| CI cuối và đồng bộ docs | Full suite và PostgreSQL integration xanh trên cùng SHA cuối; docs khớp evidence. | PENDING |

**Điều kiện dừng N08 chưa đạt để nghiệm thu PR A.** SQLite suite và các cổng hợp đồng cục bộ đã đạt, nhưng PR A chỉ được đánh dấu sẵn sàng sau khi GitHub Actions CI chạy full suite trên PostgreSQL container đạt xanh 100% trên đúng SHA cuối của commit. PR B chỉ bắt đầu sau khi PR A được nghiệm thu/merge theo quyết định riêng.

## Trigger và phạm vi Gemini

**Trigger bắt buộc:** N08-P11-RESOLVE-FAIL-CLOSED

**Đọc trước:** Tài liệu này, PLAN_MODULE_2_5_HARDENING_VERIFICATION.md, PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md, retailops/identity/store.py, retailops/core.py, retailops/http/routes.py, tests/reconcile_interleaving_cases.py, tests/test_pr_a_correctness.py và tests/test_postgres.py.

**Cho phép sửa:** Regression tests trong tests/reconcile_interleaving_cases.py và test wrappers hiện có. Chỉ sửa retailops/identity/store.py nếu test chứng minh còn lỗi thực tế. Notebook chỉ đồng bộ nếu nguồn thay đổi. Cập nhật status docs sau khi có kết quả.

**Ngoài phạm vi:** PR B, schema/migration, benchmark/dataset, cấu hình deploy, merge/deploy, hoặc tệp ngoài allowlist nếu chưa review phạm vi.

## Known limitations

- Collision chưa xác định chủ sở hữu tiếp tục ở quarantine/unresolved cho đến khi có bằng chứng từ operator.
- Identity DB và Business DB không có distributed ACID; journal/idempotency/recovery hỗ trợ fail-closed và resume, không đảm bảo atomic commit xuyên hai database.
- PR B chưa triển khai; concurrency, history retention, ToolCache invalidation, telemetry và OAuth hardening tiếp tục pending.
