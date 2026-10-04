# Review GPT 6 Astra — Báo cáo nghiệm thu PR A / N08

**Ngày:** 04/10/2026
**Branch:** `feature/module-2.5-pr-a` → `main`
**Commit nghiệm thu:** `d38554e` (d38554e5465e81acd84a222f00438efe46ddd187)
**Kết luận:** **BLOCKED** cho đến khi PostgreSQL CI xanh — merge là quyết định của owner; chưa merge, chưa deploy, chưa bắt đầu PR B.

> **Ghi chú hiện trạng:** Workflow Ops Console (`ops-console.yml`) job `postgres` từng gặp lỗi teardown Foreign Key (`customer_links_principal_id_fkey`) tại `opsconsole/tests/test_account_usage_postgres.py`. Bản vá đã bổ sung xóa `customer_links` trước khi xóa `principals`. Trạng thái nghiệm thu được giữ là **BLOCKED** cho đến khi toàn bộ checks CI/Ops Console trên PostgreSQL của PR #34 xanh hoàn toàn.

## 1. Phạm vi đã fix

| Nhóm | Hạng mục | Kết quả |
| --- | --- | --- |
| PR A correctness | F01 | Semantic/FAQ cache fail-closed theo query, context, lịch sử và provenance |
| PR A correctness | F02 | Replay, snapshot và cache commit được serialize dưới conv_lock |
| PR A correctness | F03 | Lỗi hạ tầng và HTTP 429 được chuẩn hóa, không thành “thành công giả” |
| PR A correctness | F04 | Proposal hủy chỉ tạo khi đơn và eligibility hợp lệ |
| PR A correctness | F05 | Đơn explicit mới quyết định product context |
| PR A correctness | F06 | Tách size/color và bốn trạng thái tồn kho |
| PR A correctness | F08a | Bot/UI không tuyên bố giao dịch chưa có backend thật |
| PR A correctness | F11 | Catalog thiếu category không làm crash tìm kiếm |
| N08 identity | Schema/guards | PostgreSQL identity v3, collision guard, journal v4, route maintenance có auth |
| N08 identity | Reconciliation | Hai DB có journal/idempotency/recovery; kiểm tra target ownership; đóng TOCTOU bằng reservation + recheck dưới lock |
| N08 P1.1 | Session safety | `IdentityStore.resolve()` re-raise `ApiError`; mọi lỗi lookup safety → 503 `collision_unresolved` (fail-closed) |
| N08 P1.1 | Role regression | `staff`, `manager`, `viewer` resolve thành công, đúng role trong shared harness SQLite/PostgreSQL |

Ngoài phạm vi, không thay đổi: frozen benchmark (SHA-256 LF `36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411`), schema Business (SQLite v3 / PostgreSQL v4), dataset, cấu hình deploy.

## 2. Bằng chứng CI

| Run | head_sha | Vai trò | Kết quả |
| --- | --- | --- | --- |
| 37198909762 | `d38554e` | **Nghiệm thu** | SUCCESS |
| 37197602401 | `eebe8ed` | Final docs tree trước nghiệm thu | SUCCESS |
| 37196429628 | `c4e9976` | Code patch N08-P11 (lịch sử) | SUCCESS |

Chi tiết run 37198909762:

- Job `offline`: success.
  - Host suite: `Ran 479 tests … OK`, 0 SKIP; PostgreSQL và pgvector integration chạy thật.
  - Packaged container suite: `Ran 479 tests … OK (skipped=1)`. Test bị skip là `test_colab_agent_notebook_sync`, vì image không chứa `scripts/build_agent_notebook.py`.
  - Gates xanh: docs contract, `EVAL_DATASET_OK` (30 ca), `LIVE_E2E_CONTRACT_OK`, `AGENT_NOTEBOOK_SOURCE_SYNC_OK` và `DEPLOYMENT_CONTRACT_OK`.
  - Kiểm tra HTTPS/proxy/cookie, persistent account và `POSTGRES_HTTPS_IMPORT_RESTORE_OK` đạt.
- Job `colab-python313`: success (`COLAB_PY313_DEPENDENCIES_OK`).

Bằng chứng local (SQLite): `tests/test_pr_a_correctness.py` đạt 56/56 PASS. Full suite: 429 PASS, 50 SKIP, 0 FAIL/ERROR.

- Phân bổ 50 SKIP: 36 `test_postgres.py`, 11 `test_rag_chat.py`, 2 `test_knowledge.py`, 1 `test_public_web.py`.
- Lý do skip: máy local không có PostgreSQL DSN/Waitress.
- Local skip không được tính là PASS PostgreSQL. PostgreSQL chỉ được xác nhận bằng CI.

## 3. Acceptance criteria

- **AC-01..AC-08 (F01–F06, F08a, F11): PASS** theo các test hiện có trong `tests/test_pr_a_correctness.py` và CI ở trên. PASS ở đây là đạt contract unit/integration đã đặc tả; không có nghĩa đã kiểm chứng mọi tình huống E2E hoặc live LLM.
- **AC-14, AC-15 (gates/CI): PASS.**
- **AC-09..AC-13 (PR B): PENDING TEST.**

## 4. Known limitations

1. Collision chưa xác định chủ sở hữu vẫn bị **quarantine/unresolved**; session customer liên quan bị từ chối (503) cho đến khi operator đối soát có bằng chứng.
2. Identity DB và Business DB **không có distributed ACID**. Journal, idempotency và recovery hỗ trợ fail-closed và resume, nhưng không bảo đảm atomic commit xuyên hai database.
3. Regression non-customer assert `SessionBinding.application.role` ở tầng Python, chưa assert HTTP response.
4. Chưa chạy live LLM/E2E cho các hạng mục PR A; không có số liệu benchmark/Phase 4.
5. `agent_lock` tồn dư vẫn còn (dọn trong PR B, CONV-CLEANUP); ToolCache vẫn theo từng Application, chưa chia sẻ theo tenant (F13).
6. Cache/lock chỉ bảo đảm trong một tiến trình; không suy ra tính nhất quán giữa nhiều pod.

## 5. Bàn giao PR B (bắt đầu sau khi PR A được merge)

Nguồn đặc tả: [Execution Handoff §6](PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md), [Runtime Efficiency](PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md), [Concurrency Sprint](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md), [Module 2.5 §2.2](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md).

| Mã | Mục tiêu | AC / test dự kiến |
| --- | --- | --- |
| F07 | Admission HTTP tối đa 6 chat trên Waitress 8 workers, đặt trước body/session/DB; conv_lock theo conversation; InferenceGate K=1/Q=5, timeout 10 s; 429 + `Retry-After: 5` | AC-09 |
| F09 | Telemetry monotonic: `queue_wait_ms`, `provider_inference_ms`, E2E; giá trị chưa đo giữ null, không giả 0.0; kiểm cả producer và Ops importer | AC-10, `tests/test_inference_gate.py` |
| F12 | Bỏ prune `agent_turns` LIMIT 6; prompt vẫn bounded; transcript API đủ lượt | AC-11, `tests/test_conversation_resume.py` |
| F13 | ToolCache chia sẻ theo tenant/customer; epoch + CAS, discard stale in-flight write; bump sau mutation thành công | AC-12, `tests/test_business_api.py` |
| SEC-01 | OAuth state gắn transient cookie (TTL 600 s, `Path=/auth/google`, Secure, HttpOnly, SameSite=Lax); atomic consume; lỗi 403 `invalid_oauth_state`; kiểm Set-Cookie trên HTTP response | AC-13, `tests/test_auth_google.py` |
| CONV-CLEANUP | Xóa `self.agent_lock` ở Application và session backends sau khi admission + conv_lock + gate đã được test | Module 2.5 §2.2 |

Ràng buộc PR B:

- Không thêm migration DDL; giữ SQLite Business v3 / PostgreSQL Business v4.
- Không sửa frozen benchmark.
- Không đổi ma trận RBAC.
- Gap đã biết: code hiện có `STATE_TTL_SECONDS = 900`, plan yêu cầu 600 s; PR B phải xử lý gap này và có test.

**PR C (product_policy_links / schema v5): DEFERRED** — cần ADR riêng. Phase 4 (benchmark 250 ca, load matrix) vẫn pending sau PR B.

## Tài liệu liên quan

- [N08_STOPPING_CONDITIONS.md](N08_STOPPING_CONDITIONS.md)
- [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md)
- [PLAN_MODULE_2_5_HARDENING_VERIFICATION.md](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md)
- [PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md](PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md)
- [PLAN_ROADMAP_INDEX.md](PLAN_ROADMAP_INDEX.md)
- [SESSION_HANDOFF_2026-10-03.md](SESSION_HANDOFF_2026-10-03.md)
