# P5-D Execution Handoff — Complaint E2E on the Same Customer Identity

## Trigger prompt for Gemini Antigravity — create candidate and run CI

> **Chỉ dán trigger ngắn dưới đây vào cửa sổ chat Gemini. Hướng dẫn chi tiết và các nguồn context nằm trong file này.**

```text
Làm việc tại D:\year_2026\Work_2026\agentic_AI\CSKH_ban_le.
Đọc docs/phase5/PHASE_5_D_EXECUTION_HANDOFF.md, docs/phase5/REVIEW_GEMINI_P5_D_2026-10-13.md (Section 9 là review mới nhất), docs/phase5/PHASE_5_ACCEPTANCE_CRITERIA.md và docs/03_EVALUATION/ACCEPTANCE_MATRIX.md.

Owner đã ủy quyền cho bạn tạo immutable candidate commit và push branch để chạy CI cho P5-D. Không sửa lại implementation đã được Codex review. Trước khi commit, kiểm tra git status, branch, HEAD và đối chiếu source hashes trong docs/phase5/evidence/P5_D_REVIEW_20261013_CURRENT/review_manifest.json; giữ nguyên mọi thay đổi ngoài P5-D/docs hiện có và dừng nếu phát hiện file ngoài scope cần sửa.

Mục tiêu duy nhất: tạo candidate SHA từ working tree hiện tại và chạy workflow .github/workflows/ci.yml, job offline. Job này provision PostgreSQL/pgvector pinned image và RETAILOPS_TEST_DATABASE_URL. Xác minh raw CI log có test_phase5_complaint_e2e.Phase5ComplaintPgvectorTests.test_pgvector_complaint_tenant_policy_isolation ... ok (không có skipped), cùng test count và exit 0. Job ops-console không đủ làm bằng chứng P5-D.

Được phép commit/push candidate và mở/cập nhật PR nếu cần để CI chạy; không được merge PR, rewrite history, deploy, bật EC2, chạy live OAuth/complaint, model trả phí, full benchmark, P5-E hoặc G5. Không mở rộng audit.

Nếu candidate CI fail hoặc pgvector bị skip: lưu run/job URL, raw log, skip/failure reason và checksum; giữ P5-K7/K8 PENDING, cập nhật evidence chỉ để ghi blocker rồi dừng. Nếu CI pass: lưu exact candidate SHA, workflow run/job, test counts, raw log và checksums. Chỉ cập nhật acceptance/status docs bằng kết quả thực tế; nếu việc cập nhật docs tạo SHA mới, phải chạy lại CI trên SHA cuối cùng trước khi gọi evidence là same-SHA. Không tự tuyên bố P5-K7/K8 PASS nếu thiếu điều kiện criteria.

Dừng sau candidate CI evidence hoặc blocker chính xác. Báo cáo files changed, SHA cuối, PR/run/job URL, test/skip counts, artifact paths/checksums và xác nhận không merge/deploy/EC2/live/paid/P5-E/G5.
```

## Context chain

Đọc các nguồn dưới đây để nối trạng thái, acceptance, evidence và implementation. Criteria quyết định nghiệm thu; matrix tổng hợp trạng thái; handoff này hướng dẫn thực hiện P5-D và không thay đổi gate đã chốt.

| Thứ tự | Nguồn | Context cần lấy |
|---|---|---|
| 1 | [CURRENT_PROJECT_STATUS.md](../CURRENT_PROJECT_STATUS.md) | Snapshot merged/deployed và giới hạn evidence hiện tại. |
| 2 | [PHASE_5_PLAN.md](PHASE_5_PLAN.md) | Mục tiêu, luồng P5-D, quan hệ với P5-A/B/C/E. |
| 3 | [PHASE_5_ACCEPTANCE_CRITERIA.md](PHASE_5_ACCEPTANCE_CRITERIA.md) | Định nghĩa chuẩn P5-K7/K8 và dependency P5-K3 live. |
| 4 | [ACCEPTANCE_MATRIX.md](../03_EVALUATION/ACCEPTANCE_MATRIX.md) | Gate/status, evidence theo row, điều kiện chuyển bước. |
| 5 | [PHASE_5_EXECUTION_HANDOFF.md](PHASE_5_EXECUTION_HANDOFF.md) | Handoff tổng, execution order và report requirements. |
| 6 | [PHASE_5_C_EVIDENCE.md](PHASE_5_C_EVIDENCE.md) | Import/mapping/ownership/replay contracts đã được nghiệm thu. |
| 7 | [PHASE_5_B_EVIDENCE.md](PHASE_5_B_EVIDENCE.md) | Google identity implementation offline; phân biệt với OAuth thật chưa chạy. |
| 8 | [PLAN_ROADMAP_INDEX.md](../PLAN_ROADMAP_INDEX.md) | Bước hiện tại và các bước sau; không thực hiện P5-E trong scope này. |

Đọc code/tests theo đường đi thực tế của P5-D; bảng này là bản đồ tham chiếu, không yêu cầu audit toàn bộ hệ thống.

| Nhóm | Code gốc | Tests tham chiếu |
|---|---|---|
| Sales event/import | [adapter.py](../../retailops/sales/adapter.py), [simulator.py](../../retailops/sales/simulator.py), [events.py](../../retailops/sales/events.py), [fixtures.py](../../retailops/sales/fixtures.py) | [test_phase5_sales_simulator_import.py](../../tests/test_phase5_sales_simulator_import.py), [test_phase5_sales_review_fixes.py](../../tests/test_phase5_sales_review_fixes.py), [test_phase5_sales_postgres.py](../../tests/test_phase5_sales_postgres.py) |
| Identity/session/HTTP | [persistent.py](../../retailops/identity/persistent.py), [identity/store.py](../../retailops/identity/store.py), [auth_google.py](../../retailops/http/auth_google.py), [routes.py](../../retailops/http/routes.py) | [test_phase5_google_identity.py](../../tests/test_phase5_google_identity.py), [test_persistent_identity.py](../../tests/test_persistent_identity.py), [test_auth_google.py](../../tests/test_auth_google.py) |
| Supervisor/dispute/approval | [supervisor.py](../../retailops/workflow/supervisor.py), [dispute_agent.py](../../retailops/workflow/subagents/dispute_agent.py), [graph.py](../../retailops/workflow/graph.py), [state.py](../../retailops/workflow/state.py), [approval.py](../../retailops/workflow/approval.py) | [test_workflows.py](../../tests/test_workflows.py), [test_multiagent_flow.py](../../tests/test_multiagent_flow.py), [test_multiagent_chat_integration.py](../../tests/test_multiagent_chat_integration.py) |
| Policy/RAG tenant context | [knowledge/tool.py](../../retailops/knowledge/tool.py), [repository.py](../../retailops/knowledge/repository.py), [citations.py](../../retailops/knowledge/citations.py), [data/knowledge](../../data/knowledge/) | [test_rag_chat.py](../../tests/test_rag_chat.py), [test_knowledge.py](../../tests/test_knowledge.py) |
| Business/proposal/audit | [application.py](../../retailops/business/application.py), [business/store.py](../../retailops/business/store.py) | [test_business_api.py](../../tests/test_business_api.py), [test_audit_remediation.py](../../tests/test_audit_remediation.py) |
| Runner tham khảo và docs checks | [live-e2e.py](../../deploy/live-e2e.py) — chỉ đọc, không chạy live; [check_docs_contract.py](../../scripts/check_docs_contract.py) | Chạy targeted P5-D tests mới và regression liên quan theo instructions dưới đây. |

## Candidate creation and CI handoff — implementation đã review, acceptance còn pending

**Review verdict hiện tại:** implementation re-review PASS cho D-R2/D-R3; D-R1 có test PostgreSQL/pgvector thật nhưng bị SKIPPED local vì thiếu DSN. Chưa có immutable P5-D candidate SHA/CI, do đó P5-K7/K8 chưa được accepted. Xem [review Section 9](REVIEW_GEMINI_P5_D_2026-10-13.md), [current recheck set](evidence/P5_D_REVIEW_20261013_CURRENT/), và [P5-D evidence](PHASE_5_D_EVIDENCE.md). Các thư mục `P5_D_CODEX_RECHECK_20261013` và `P5_D_REVIEW_20261013` là snapshot cũ, không phải provenance của source hiện tại.

| Finding | Tình trạng current source | Bằng chứng còn cần cho acceptance |
|---|---|---|
| **D-R1 / K7 tenant policy** | Current test `test_07` is a mocked seam test. A separate disposable PostgreSQL/pgvector test now has real ingest/search, complaint-path, source/citation, tenant A/B marker and empty-tenant assertions; it skipped locally without `RETAILOPS_TEST_DATABASE_URL`. | Required CI on immutable candidate must execute this DB test without skip and pass. A skipped test is not a PASS. |
| **D-R2 / K8 raw lifecycle** | Offline source/test re-review PASS: proposal derives from complaint action; same proposal is confirmed and replayed after reopen; raw report/manifest round-trip and tamper assertions exist. | Required candidate CI/evidence on the same workstream SHA per acceptance rule. |
| **D-R3 / notebook sync** | PASS on current recheck. No builder changes needed. | Re-run only if bundled source changes; preserve current builder and audit-sync results. |

**Stop rule:** không reimplement P5-D. Tạo candidate từ source đã review, chạy đúng CI offline có pgvector và capture evidence; giữ K7/K8 pending nếu CI fail/skip hoặc SHA evidence không cùng candidate. Không mở rộng audit, không merge/deploy/live, rồi dừng.

## Hướng dẫn implementation ban đầu (historical reference; không chạy lại)

Khối sau ghi lại implementation scope ban đầu để tra cứu. Trigger hiện hành ở đầu file chỉ yêu cầu candidate/CI verification.

```text
Bạn là implementation agent cho RetailOps. Hãy thực hiện P5-D offline trong repository hiện tại, sau đó báo cáo để reviewer độc lập kiểm tra. Không tự mở rộng scope.

MỤC TIÊU
Xây và kiểm thử complaint E2E trên cùng một synthetic customer identity đã được dùng để import order ở P5-C:
import order.created/order.paid -> session/customer binding -> complaint -> supervisor/dispute_agent -> policy/RAG lookup đúng tenant -> proposal hoặc human handoff -> customer confirmation trong cùng session -> idempotent state transition + audit/replay evidence.

ĐỌC TRƯỚC (bắt buộc)
1. docs/phase5/PHASE_5_PLAN.md
2. docs/phase5/PHASE_5_ACCEPTANCE_CRITERIA.md
3. docs/phase5/PHASE_5_EXECUTION_HANDOFF.md
4. docs/03_EVALUATION/ACCEPTANCE_MATRIX.md
5. docs/CURRENT_PROJECT_STATUS.md
6. docs/phase5/PHASE_5_C_EVIDENCE.md
7. docs/phase5/PHASE_5_B_EVIDENCE.md
8. docs/PLAN_ROADMAP_INDEX.md

Đọc các code/test links trong "Context chain" khi trace flow. Kiểm tra git status/branch/HEAD thực tế trước khi sửa; baseline merged ghi trong docs không mặc nhiên là local HEAD. Báo cáo provenance của patch, không reset/checkout đè thay đổi sẵn có.

BASELINE VÀ PHẠM VI
- P5-C đã merge tại a34b479eeb633ba55090f43a1f4ed7d85f6a3c9a; P5-K4/K5/K6 đã PASS offline/merged.
- P5-K3 Google OAuth thật vẫn PENDING. Vì vậy lần này chỉ làm implementation và tests offline; không tuyên bố P5-K7 live PASS.
- Chỉ xử lý P5-D / P5-K7 / P5-K8. Không mở P5-E, G5, full benchmark hoặc measurement.
- Chỉ dùng synthetic fixtures/test identities. Không dùng production data, PII thật, OAuth secret, access token, model trả phí hay live provider.
- Không sửa frozen benchmark, không mở lại Phase 4 K1-K8 hoặc Phase 5 P5-K1-P5-K6, không thêm gate mới.
- Không bật EC2, không deploy, không chạy live OAuth, không chạy HTTPS/live E2E trong phiên này.
- Giữ nguyên các thay đổi chưa commit khác trong working tree; không reset/revert file của người dùng.

CODE HIỆN CÓ PHẢI KIỂM TRA TRƯỚC KHI SỬA
- retailops/workflow/supervisor.py
- retailops/workflow/subagents/dispute_agent.py
- retailops/workflow/graph.py
- retailops/workflow/state.py
- retailops/workflow/approval.py
- retailops/http/routes.py
- retailops/sales/adapter.py và simulator/import contract P5-C
- deploy/live-e2e.py
- tests/test_workflows.py
- tests/test_multiagent_flow.py
- tests/test_rag_chat.py
- tests/test_audit_remediation.py
- tests/test_business_api.py

TẬN DỤNG API/FLOW ĐÃ CÓ
Kiểm tra và tái sử dụng đúng flow hiện có, không tạo một proposal subsystem song song:
- /api/session
- /api/orders
- /api/chat
- /api/cancellation-proposals
- /api/cancellation-proposals/{id}/confirm
- /api/cancellation-proposals/{id}/dismiss

YÊU CẦU IMPLEMENTATION
1. Tạo một fixture/runner offline tạo tenant, customer, synthetic external_customer_id, imported order và session tuple cố định; ghi rõ tenant/principal/customer/order/event IDs.
2. Chứng minh order import và complaint dùng cùng tenant + customer binding; không dùng email đơn độc làm khóa.
3. Complaint phải đi qua supervisor và được route tới dispute_agent (hoặc human handoff theo policy), không bypass workflow bằng gọi thẳng mutation.
4. Dispute worker chỉ được đọc order thuộc customer/session hiện tại và policy/RAG thuộc đúng tenant; cross-tenant/cross-customer lookup phải bị từ chối hoặc không lộ dữ liệu.
5. Trước confirmation, chỉ được tạo proposal/handoff ở trạng thái chờ; tuyệt đối không đổi trạng thái order và không ghi mutation business.
6. Confirmation phải yêu cầu đúng customer/session owner, kiểm tra order version/ownership, có idempotency key, replay cùng request không tạo mutation/audit/event trùng.
7. Persist và kiểm tra audit/business events đủ để replay; raw evidence phải có checksum/hash của fixture/report, không lưu secret/token/PII thật.
8. Nếu flow hiện tại chưa đủ, sửa tối thiểu trong code hiện có và bổ sung regression tests; không đổi contract P5-C ngoài phần cần để nối flow.

TEST CASES TỐI THIỂU
- Same identity: import -> session -> orders chỉ thấy order của customer đó.
- Complaint routing: complaint được supervisor route tới dispute_agent và có trace/handoff/proposal tương ứng.
- Tenant policy/RAG isolation: đúng tenant đọc được policy; tenant/customer khác không đọc được order/context.
- No pre-confirm mutation: state/order/audit trước confirmation chứng minh không có mutation ngoài proposal/handoff.
- Confirmation owner/session: session khác hoặc customer khác bị từ chối.
- Confirmation idempotency: lần đầu áp dụng đúng một lần; replay cùng idempotency key trả replayed; key khác hoặc payload khác bị từ chối đúng contract.
- Restart/replay: proposal/confirmation/audit/event vẫn nhất quán sau reopen/replay nếu storage hiện có hỗ trợ.
- Failure path: model/tool/policy không chắc chắn -> human handoff hoặc refusal, không tự ý mutation.
- Regression: toàn bộ test liên quan P5-C/P5-B và business/proposal hiện có vẫn PASS.

TẠO/CẬP NHẬT EVIDENCE
- Tạo docs/phase5/PHASE_5_D_EVIDENCE.md nếu chưa có.
- Mọi claim phải trỏ tới file:line hoặc test name, ghi rõ offline implementation evidence.
- Cập nhật tối thiểu các file sau nếu trạng thái thay đổi:
  docs/phase5/PHASE_5_ACCEPTANCE_CRITERIA.md
  docs/phase5/PHASE_5_EXECUTION_HANDOFF.md
  docs/phase5/PHASE_5_PLAN.md
  docs/CURRENT_PROJECT_STATUS.md
  docs/PLAN_ROADMAP_INDEX.md
  docs/03_EVALUATION/ACCEPTANCE_MATRIX.md
- Không ghi P5-K3 live PASS. Không ghi P5-K7/P5-K8 PASS nếu thiếu đủ evidence; phân biệt rõ OFFLINE IMPLEMENTED/PENDING LIVE.

KIỂM TRA BẮT BUỘC TRƯỚC KHI BÁO CÁO
- Chạy targeted P5-D tests.
- Chạy regression tests bị ảnh hưởng và P5-C/P5-B suites liên quan.
- python scripts/check_docs_contract.py
- git diff --check
- Nếu môi trường không có PostgreSQL/Docker thì ghi rõ test nào skipped và không bịa PASS.
- Không chạy EC2/deploy/live OAuth/paid model/full benchmark.

ĐẦU RA CUỐI
Báo cáo ngắn, có:
1. files changed và lý do;
2. test commands + kết quả chính xác (PASS/FAIL/SKIPPED);
3. P5-K7 offline status và P5-K8 offline status;
4. dependency còn lại: P5-K3 live Google OAuth trước live complaint acceptance;
5. evidence path và checksum/hash;
6. commit SHA/branch nếu có commit;
7. xác nhận không deploy, không EC2, không live OAuth, không paid/full measurement.

Dừng sau báo cáo để Codex review; không tự merge. Không tiếp tục sang P5-E/G5 và không săn thêm bug ngoài các test/criteria trên.
```

## Handoff metadata

- **Owner:** Gemini Antigravity thực hiện implementation; reviewer độc lập kiểm tra sau đó.
- **Phase:** P5-D — Complaint E2E on the same customer identity.
- **Current gate:** D-R2/D-R3 implementation review PASS; D-R1 database test implemented but local run SKIPPED. P5-K7/K8 acceptance pending immutable same-workstream candidate CI; P5-K3/live K7/K8 PENDING.
- **Prerequisites:** P5-C merged/deployed; P5-K1/K2/K4/K5/K6 PASS; P5-K3 live OAuth vẫn PENDING.
- **Current merged baseline:** `a34b479eeb633ba55090f43a1f4ed7d85f6a3c9a`.
- **Authoritative criteria:** [PHASE_5_ACCEPTANCE_CRITERIA.md](PHASE_5_ACCEPTANCE_CRITERIA.md).
- **Project matrix:** [ACCEPTANCE_MATRIX.md](../03_EVALUATION/ACCEPTANCE_MATRIX.md).
- **Parent handoff:** [PHASE_5_EXECUTION_HANDOFF.md](PHASE_5_EXECUTION_HANDOFF.md).

## P5-D next-step plan — candidate verification only

### 1. Reconnaissance and candidate boundary

Read review Section 9 and the current-run logs/manifest. Check branch, worktree and whether an immutable candidate SHA already exists. Preserve changes and do not reimplement P5-D. The owner has authorized candidate commit/push for this bounded CI run. Stop if unrelated files need modification.

### 2. Candidate commit and CI

Commit the already-reviewed working tree with a clear P5-D candidate message and push the branch/PR. Use the existing `.github/workflows/ci.yml` `offline` job only: it provisions disposable PostgreSQL/pgvector and sets `RETAILOPS_TEST_DATABASE_URL`. Confirm the D-R1 pgvector test runs and passes without skip; capture exact SHA, run/job URL, test counts, raw log and checksums. The ops-console job alone is insufficient.

### 3. Verification and same-SHA evidence

Verify the required candidate CI result, confirm pgvector did not skip, and update evidence/matrix/status only with same-SHA results. If documentation changes after the first CI run, push the final docs SHA and rerun the required CI before treating the evidence as same-SHA. P5-K3 live remains a separate pending dependency.

### 4. Documentation and stop point

Stop after reporting exact-SHA candidate evidence or a precise blocker. Do not merge, deploy, start EC2, run OAuth/live, or start P5-E/G5.

## Candidate-verification checklist

- [x] Current source re-review: D-R2 lifecycle and D-R3 notebook sync PASS.
- [x] Current source contains non-vacuous D-R1 disposable PostgreSQL/pgvector assertions.
- [ ] Immutable candidate SHA exists and matches the CI-tested SHA.
- [ ] Candidate CI executes pgvector without skip and passes required checks.
- [ ] Evidence manifest binds source hashes and logs to that candidate SHA.
- [ ] Keep P5-K3 live OAuth, live P5-K7/K8, P5-E and G5 explicitly pending.

## Stop conditions

Stop after candidate CI evidence or a precise blocker is reported. Do not silently weaken acceptance, self-declare P5-K7/K8 accepted, create another gate, move to P5-E, or initiate live operations.
