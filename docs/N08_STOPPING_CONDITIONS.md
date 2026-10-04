# N08 — Điều kiện dừng và phạm vi khắc phục P1.1

**Cập nhật:** 04/10/2026
**Branch / Code commit được kiểm tra:** feature/module-2.5-pr-a / c4e9976 (c4e99769ec46be3d8fe33d272527e9c73b3b0ad1)
**Trigger:** N08-P11-RESOLVE-FAIL-CLOSED
**Trạng thái:** VERIFIED trên cả SQLite local và PostgreSQL CI Container (CI Run 37196429628 SUCCESS); ĐỦ ĐIỀU KIỆN CHUYỂN SANG REVIEW / NGHIỆM THU PR A (merge là quyết định riêng, PR B chưa bắt đầu).

## Kết quả hiện tại

IdentityStore.resolve() re-raise ApiError do safety guard phát ra; lỗi truy vấn guard được log nội bộ và trả 503 collision_unresolved. Regression trong tests/reconcile_interleaving_cases.py kiểm tra customer-link mismatch, lỗi ba loại lookup, late takeover, API orders không lộ dữ liệu, và đầy đủ toàn bộ các role non-customer (staff, manager, viewer).

Full suite cục bộ: **479 tests, 429 PASS, 50 SKIP, 0 FAIL/ERROR** (50 tests SKIP gồm 36 tests trong `tests/test_postgres.py`, 11 tests trong `tests/test_rag_chat.py`, 2 tests trong `tests/test_knowledge.py`, 1 test trong `tests/test_public_web.py` do thiếu PostgreSQL local DSN và Waitress). Toàn bộ các bài kiểm thử này đã được xác thực đạt 100% trên GitHub Actions CI container.

Docs contract PASS 4/4 checks. Các lệnh check_deployment_contract.py, check_eval_dataset.py và build_agent_notebook.py --check cũng PASS. Cả hai benchmark giữ SHA-256 sau LF normalization: 36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411.

GitHub Actions CI run 37196429628 trên code SHA `c4e9976` đạt **SUCCESS (Xanh 100%)**:
- Host suite: **479/479 PASS, 0 SKIP, 0 FAIL, 0 ERROR** trên PostgreSQL 16 và pgvector service container.
- Packaged container suite: **478 PASS, 1 SKIP, 0 FAIL, 0 ERROR** (1 test skip là `test_colab_agent_notebook_sync` bỏ qua khi `scripts/build_agent_notebook.py` không có trong image).
- Caddy live proxy & HTTPS deployment: PASS.

## Điều kiện dừng

| Gate | Bằng chứng hiện có | Trạng thái |
| --- | --- | --- |
| P1.1a — Late takeover/session cũ | Shared regression chạy local qua SQLite và CI host suite trên PostgreSQL container. | VERIFIED (CI 37196429628 PASS) |
| P1.1b — customer_links trỏ tới customer unresolved | Regression mới trong shared harness; PublicWeb không trả orders; CI host suite PASS. | VERIFIED (CI 37196429628 PASS) |
| P1.1c — lỗi safety lookup | Fault injection cho unresolved_collisions, customer_links và membership count; trả fail-closed 503; CI host suite PASS. | VERIFIED (CI 37196429628 PASS) |
| P1.1d — ranh giới role | Staff, manager và viewer đã có regression đầy đủ trong shared harness; resolve bình thường, đúng role; CI host suite PASS. | VERIFIED (CI 37196429628 PASS) |
| P1.2 — SQLite migration/coordinator | E2E SQLite + PostgreSQL integration PASS trong CI run 37196429628. | VERIFIED (CI 37196429628 PASS) |
| CI cuối và đồng bộ docs | Full suite và PostgreSQL integration xanh 100% trên commit SHA c4e9976; docs khớp evidence. | VERIFIED (CI 37196429628 SUCCESS) |

**Điều kiện dừng N08 ĐÃ ĐẠT ĐẦY ĐỦ.** Toàn bộ các cổng kỹ thuật P1.1, P1.2, ranh giới vai trò non-customer, fault injection và PostgreSQL integration test đã được xác minh thành công trên CI run 37196429628. PR A đủ điều kiện chuyển sang bước review / nghiệm thu code. Quyết định merge vào `main` là bước riêng; tuyệt đối chưa merge, chưa deploy lên EC2 và chưa bắt đầu PR B.

## Trigger và phạm vi Gemini

**Trigger bắt buộc:** N08-P11-RESOLVE-FAIL-CLOSED

**Đọc trước:** Tài liệu này, PLAN_MODULE_2_5_HARDENING_VERIFICATION.md, PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md, retailops/identity/store.py, retailops/core.py, retailops/http/routes.py, tests/reconcile_interleaving_cases.py, tests/test_pr_a_correctness.py và tests/test_postgres.py.

**Cho phép sửa:** Regression tests trong tests/reconcile_interleaving_cases.py và test wrappers hiện có. Chỉ sửa retailops/identity/store.py nếu test chứng minh còn lỗi thực tế. Notebook chỉ đồng bộ nếu nguồn thay đổi. Cập nhật status docs sau khi có kết quả.

**Ngoài phạm vi:** PR B, schema/migration, benchmark/dataset, cấu hình deploy, merge/deploy, hoặc tệp ngoài allowlist nếu chưa review phạm vi.

## Known limitations

- Collision chưa xác định chủ sở hữu tiếp tục ở quarantine/unresolved cho đến khi có bằng chứng từ operator.
- Identity DB và Business DB không có distributed ACID; journal/idempotency/recovery hỗ trợ fail-closed và resume, không đảm bảo atomic commit xuyên hai database.
- PR B chưa triển khai; concurrency, history retention, ToolCache invalidation, telemetry và OAuth hardening tiếp tục pending.
