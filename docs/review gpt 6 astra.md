# Review GPT 6 Astra — hậu kiểm Gemini N08 P1.1

**Ngày:** 04/10/2026
**Branch / HEAD:** feature/module-2.5-pr-a / 4ef078e (uncommitted changes in working tree)
**Phạm vi:** Bản vá IdentityStore.resolve(), regression tests, N08 và các status/plan liên kết.

## Tóm tắt hiện trạng

> **Trigger: N08-P11-RESOLVE-FAIL-CLOSED.**
> - Đã sửa lỗi fail-open trong `IdentityStore.resolve()`: re-raise `ApiError`, log nội bộ và fail-closed 503 `collision_unresolved` trên mọi lỗi lookup safety.
> - Đã bổ sung regression cho toàn bộ các vai trò non-customer (`staff`, `manager`, `viewer`) trong shared harness `tests/reconcile_interleaving_cases.py`.
> - SQLite có bằng chứng kiểm thử cục bộ: PR A suite đạt 56/56 PASS; full suite đạt 429 PASS, 50 SKIP, 0 FAIL.
> - PostgreSQL tests bị SKIP ở môi trường local (36 tests trong `tests/test_postgres.py` và 14 tests trong `tests/test_pgvector_rag.py` do không có `RETAILOPS_TEST_DATABASE_URL`). **Không tuyên bố PostgreSQL PASS ở local.**
> - CI PostgreSQL trên đúng SHA cuối: **PENDING**. Chỉ đánh dấu nghiệm thu PR A sau khi GitHub Actions CI chạy full suite trên PostgreSQL container đạt xanh 100%.

## Kết luận & Quyết định

**Local verified trên SQLite; PR A chưa nghiệm thu, chưa merge main, chưa bắt đầu PR B.**

1. **Sửa fail-open hợp lý:** `IdentityStore.resolve()` re-raise `ApiError` trước nhánh bắt `Exception`; lỗi safety lookup được log nội bộ rồi ánh xạ về HTTP 503 `collision_unresolved`. Đóng dứt điểm nhánh lỗi bị nuốt và lỗi lookup bị coi như không có collision.
2. **Regression role viewer đã hoàn tất:** Shared harness `tests/reconcile_interleaving_cases.py` đã tạo và xác thực đầy đủ cả 3 vai trò non-customer (`staff`, `manager`, `viewer`) resolve thành công, đúng role (regression non-customer hiện không assert HTTP response mà assert Python `SessionBinding` có `application.role` tương ứng), kể cả khi có collision ID và dưới fault injection.
3. **Bằng chứng SQLite cục bộ đạt chuẩn:** Chạy độc lập `tests/test_pr_a_correctness.py` đạt 56/56 PASS; full suite đạt 429 PASS, 50 SKIP, 0 FAIL/ERROR.
4. **PostgreSQL chưa được xem là đã kiểm chứng ở local:** 50 tests SKIP (36 trong `test_postgres.py`, 14 trong `test_pgvector_rag.py`). Không tuyên bố PostgreSQL PASS khi test bị skip. Cần chạy CI GitHub Actions container trên đúng commit SHA cuối.
5. **Cổng hợp đồng đạt 100%:** `check_docs_contract.py` (0 lỗi), `check_deployment_contract.py` (PASS), `check_eval_dataset.py` (PASS, 30 ca, benchmark giữ nguyên SHA-256), `build_agent_notebook.py --check` (PASS).
6. **Kế hoạch tiếp theo:** Commit bản vá sạch, đưa đúng SHA lên GitHub để chạy workflow CI (PostgreSQL 16 container); chỉ nghiệm thu PR A sau khi CI xanh; sau khi PR A được merge mới bắt đầu PR B.

## Tài liệu liên quan

- [N08_STOPPING_CONDITIONS.md](N08_STOPPING_CONDITIONS.md)
- [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md)
- [PLAN_MODULE_2_5_HARDENING_VERIFICATION.md](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md)
- [PLAN_ROADMAP_INDEX.md](PLAN_ROADMAP_INDEX.md)
- [PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md](PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md)
- [SESSION_HANDOFF_2026-10-03.md](SESSION_HANDOFF_2026-10-03.md)
