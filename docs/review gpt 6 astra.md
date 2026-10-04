# Review GPT 6 Astra — Báo cáo nghiệm thu PR A / N08

**Ngày:** 04/10/2026
**Branch:** `feature/module-2.5-pr-a` → `main` (PR #34, đang mở, chưa merge/deploy)
**Commit nghiệm thu & candidate:** `ee78b41` (ee78b41664b6cff6fa6424f9d937682dc7b9e819)
**Bằng chứng CI trên head:**
- CI run [37202690835](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37202690835): **SUCCESS** (host 479/479 PASS, container 478 PASS / 1 SKIP; Colab Python 3.13 PASS; gates xanh)
- Ops Console run [37202690842](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37202690842): **SUCCESS** (Job `postgres` PASS 19/19 tests, teardown FK đã fix; các jobs `portable` Windows & Ubuntu PASS)
**Kết luận:** **READY FOR MERGE** — PR #34 còn mở, đủ điều kiện kỹ thuật; quyết định merge thuộc về owner; chưa merge vào `main`, chưa deploy EC2, chưa bắt đầu PR B.

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
| Ops Console | Teardown fix | `opsconsole/tests/test_account_usage_postgres.py` xóa `customer_links` trước khi xóa `principals` |

Ngoài phạm vi, không thay đổi: frozen benchmark (SHA-256 LF `36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411`), schema Business (SQLite v3 / PostgreSQL v4), dataset, cấu hình deploy.

## 2. Bằng chứng CI

| Run | head_sha | Workflow / Vai trò | Kết quả |
| --- | --- | --- | --- |
| 37202690835 | `ee78b41` | **CI (PR #34 head)** | SUCCESS |
| 37202690842 | `ee78b41` | **Ops Console / PostgreSQL (PR #34 head)** | SUCCESS |
| 37198909762 | `d38554e` | CI nghiệm thu trước đó | SUCCESS |
| 37197602401 | `eebe8ed` | Final docs tree trước nghiệm thu | SUCCESS |
| 37196429628 | `c4e9976` | Code patch N08-P11 (lịch sử) | SUCCESS |

Chi tiết các run trên head `ee78b41`:

- **CI run 37202690835:**
  - Job `offline`: success. Host suite: `Ran 479 tests … OK`, 0 SKIP; PostgreSQL và pgvector integration chạy thật. Packaged container suite: `Ran 479 tests … OK (skipped=1)`. Test bị skip là `test_colab_agent_notebook_sync`, vì image không chứa `scripts/build_agent_notebook.py`. Các gates xanh: docs contract, `EVAL_DATASET_OK` (30 ca), `LIVE_E2E_CONTRACT_OK`, `AGENT_NOTEBOOK_SOURCE_SYNC_OK`, `DEPLOYMENT_CONTRACT_OK`, HTTPS/proxy/cookie, persistent account và `POSTGRES_HTTPS_IMPORT_RESTORE_OK`.
  - Job `colab-python313`: success (`COLAB_PY313_DEPENDENCIES_OK`).
- **Ops Console run 37202690842:**
  - Job `postgres`: success (`Ran 19 tests in 1.105s ... OK`). Bổ sung xóa `customer_links` theo `principal_id` trước khi xóa `principals` đã giải quyết triệt để lỗi foreign key violation teardown.
  - Jobs `portable (windows-latest)` và `portable (ubuntu-24.04)`: success (`Ran 19 tests ... OK (skipped=2)`).
- **Trạng thái PR #34:** `state=open`, `mergeable=True`, `mergeable_state=clean`. PR còn mở, chưa merge, chưa deploy.

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
