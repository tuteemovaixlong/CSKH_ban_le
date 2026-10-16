# Review Gemini P5-D — K7/K8 offline

> **Review-round note:** Sections 1–7 preserve the initial review of the pre-remediation patch. Section 8 records the intervening re-review and is superseded. **Section 9 is the current Codex re-review and source of the present verdict.** Earlier hashes/logs are not evidence for the current patch.

> **Ngày:** 2026-10-13 (Asia/Bangkok).
> **Reviewer:** Codex; đối chiếu trực tiếp working tree local, chạy tests và probes offline.
> **Current verdict:** **Implementation re-review PASS for D-R2/D-R3; P5-K7/K8 acceptance pending same-candidate CI. Not ready for owner merge review, deploy, live work, or P5-E.**
> **Scope cố định:** P5-K7/P5-K8, regression bị ảnh hưởng và notebook source sync; không mở audit khác.

## 1. Provenance

- Local base commit: `3ff5d0ee8d4d53df6772a697d2638c9e65bbe7e6`; branch `feat/phase5-sales-simulator-import`.
- P5-D là **working-tree patch chưa commit**. Không có immutable P5-D candidate SHA hoặc CI trên candidate được xác minh trong review này.
- `a34b479eeb633ba55090f43a1f4ed7d85f6a3c9a` là P5-C merged/deployed baseline trong docs/evidence trước đó; object này chưa có trong local Git, nên không gọi đây là commit chứa patch P5-D đã kiểm tra.
- Năm file code/test/notebook của Gemini khớp hashes đã báo cáo; exact hashes nằm trong [manifest](evidence/P5_D_REVIEW_20261013/manifest.json). Các thay đổi docs có trước review được giữ nguyên.
- Đọc attachment Gemini như báo cáo để đối chiếu, không coi đó là bằng chứng thay cho code hoặc log tự chạy.

## 2. Những phần đã đạt

| Nội dung | Kết luận có thể chứng minh | Nguồn local |
|---|---|---|
| Import và identity | Event được map vào customer từ synthetic Google login; session trả cùng tenant/principal/customer; owner thấy `O-90001` | [test_01, line 258](../../tests/test_phase5_complaint_e2e.py), `test_01_same_identity_binding_import_and_session` |
| Order isolation | Customer khác cùng tenant và customer tenant khác không đọc được order | [test_02, line 316](../../tests/test_phase5_complaint_e2e.py), `test_02_order_visibility_isolation_across_customers_and_tenants` |
| Supervisor/dispute | Cancellation route tới dispute, exchange tạo đề xuất staff approval; yêu cầu gặp người/rage route escalation | [tests_03–05](../../tests/test_phase5_complaint_e2e.py), assertions tại lines 359–428 |
| Cross-customer complaint | Không tạo cancel proposal cho order người khác; message không lộ tên sản phẩm | [test_06, line 434](../../tests/test_phase5_complaint_e2e.py), refusal path [dispute_agent.py](../../retailops/workflow/subagents/dispute_agent.py):132–155 / 467–490 |
| Pre-confirmation | Order status/version không đổi trước/ sau tạo proposal; không có `order_cancelled` trước confirmation | [test_08, line 473](../../tests/test_phase5_complaint_e2e.py) |
| Owner/version/idempotency | Wrong customer bị reject; stale version bị reject; exact confirm replay không tăng version/event; key khác bị reject | [tests_09–11](../../tests/test_phase5_complaint_e2e.py), [approval.py](../../retailops/workflow/approval.py):66, [store.py](../../retailops/business/store.py):1036 |
| Persistence và refusal | Reopen giữ order cancelled và audit kinds; exact import replay; delivered order từ chối cancellation | [tests_13–14](../../tests/test_phase5_complaint_e2e.py) |

Các kết luận trên là **SQLite + WSGI route invocation + deterministic mock**, không phải HTTP socket/TLS live, Google OAuth thật, PostgreSQL P5-D hoặc đo chất lượng model. Proposal/chat/audit có thể ghi dữ liệu trước confirmation; bất biến cần giữ là **không mutation trạng thái nghiệp vụ order**, không phải cấm mọi DB write.

## 3. Ba mục cần đóng trong lượt sửa kế tiếp

### D-R1 — P5-K7: chưa chứng minh dispute đọc policy đúng tenant

**P2 / blocker của offline sign-off.** [test_07](../../tests/test_phase5_complaint_e2e.py):455–467 chỉ assert `status == 200` và intent `policy_knowledge`. Nó không assert `search_knowledge`, sources/citations, nội dung policy hoặc tenant isolation; đây cũng là policy question, chưa phải complaint qua dispute. Gateway mock tại lines 78–129 chỉ phát tool call cho cancellation.

Probe thay `KnowledgeTool.search` bằng hàm sẽ raise nếu được gọi: test_07 vẫn PASS, **search call count = 0**. [Raw probe](evidence/P5_D_REVIEW_20261013/probes.json). SQLite hiện trả `knowledge_not_ready` nếu thực sự gọi tool ([tool.py](../../retailops/knowledge/tool.py):42–43). Do đó không được ghi tenant policy/RAG isolation đã verified.

**Closure cố định:** scripted complaint phải đi qua supervisor/dispute và thật sự đọc order + policy bound tenant; assert tool trace, sources/citation/nội dung tenant A, không có marker tenant B trong response/model context; nguồn không sẵn sàng phải được báo đúng, không bịa policy. Tận dụng [test_rag_chat.py](../../tests/test_rag_chat.py) và disposable pgvector CI cho DB assertions. Mock local chỉ chứng minh contract; tests skipped không được dùng để khẳng định PostgreSQL PASS. Không yêu cầu mọi complaint luôn gọi RAG hoặc tái thiết kế RAG.

### D-R2 — P5-K8: chưa có raw lifecycle report và kiểm checksum có ý nghĩa

**P2 / blocker của offline sign-off.** [test_15](../../tests/test_phase5_complaint_e2e.py):751–767 chỉ tính hash fixture rồi assert độ dài 64. Không ghi/read raw report, không so checksum với expected bytes, không reject artifact đã tamper. Probe thay riêng hashlib binding của test bằng digest `0` lặp 64 ký tự: **test vẫn PASS** ([probe](evidence/P5_D_REVIEW_20261013/probes.json)). Các hashes source đúng không thay thế raw E2E evidence mà K8 yêu cầu.

Các đoạn lifecycle đang được kiểm riêng: chat/proposal test_03/08, confirm test_11 tạo proposal trực tiếp, reopen test_13 replay **import**, chưa replay **confirmation** qua app vừa reopen. Cross-tenant confirm cũng chưa được assert. Báo cáo Gemini gọi `test_15_end_to_end_full_lifecycle` nhưng tên test này không tồn tại.

**Closure cố định:** nối một run import → same session → complaint/dispute → proposal từ order/version trả về → confirm → exact confirm replay sau reopen, lưu raw report có identity binding (không cookie/token), event/order/conversation/proposal IDs, trace, before/after state và audit counts. Assert wrong customer/tenant confirm denied, mutation đúng một lần, replay giữ response/state/counts. Lưu checksum của report/fixture theo thuật toán rõ ràng, đọc lại kiểm equality và có tamper-negative assertion. Review logs do Codex tạo ở đây không thay thế report lifecycle của implementation.

### D-R3 — Regression source sync: notebook hiện FAIL

**P2 / blocker của regression bắt buộc.** `python scripts/build_agent_notebook.py --check` exit **1**; `test_colab_agent_notebook_sync` FAIL ([log](evidence/P5_D_REVIEW_20261013/notebook_check.log)). Giải bundle cho thấy chỉ [fixtures.py](../../retailops/sales/fixtures.py) khác working tree; [probe](evidence/P5_D_REVIEW_20261013/probes.json) ghi hashes embedded/current.

**Closure cố định:** sau tất cả thay đổi code/tests/fixtures, regenerate bằng script hiện có rồi chạy `--check` và regression audit sync. Không sửa builder/ngưỡng/check để né failure; không chạy Colab/live model.

## 4. Kết quả tự chạy trên patch đã nhận

| Check | Kết quả | Raw evidence |
|---|---|---|
| `python -m unittest -v tests.test_phase5_complaint_e2e` | **15 PASS**, 5.984s, 0 skipped | [targeted_tests.log](evidence/P5_D_REVIEW_20261013/targeted_tests.log) |
| `python -m unittest discover -s tests -p "test_phase5*.py" -v` | **85 ran; 72 PASS, 13 SKIPPED**, 12.135s, exit 0 | [phase5_tests.log](evidence/P5_D_REVIEW_20261013/phase5_tests.log) |
| 9 regression modules (business/multiagent/public/workflow/auth/persistent/audit/RAG) | **87 ran; 84 PASS, 1 FAIL, 1 ERROR, 1 SKIP**, 20.162s, exit 1 | [regression_tests.log](evidence/P5_D_REVIEW_20261013/regression_tests.log) |
| RAG chạy đúng discovery: `python -m unittest discover -s tests -p test_rag_chat.py -v` | **14 ran; 3 PASS, 11 SKIPPED**, 0.375s, exit 0 | [rag_discovery_tests.log](evidence/P5_D_REVIEW_20261013/rag_discovery_tests.log) |
| Notebook source sync | **FAIL**, exit 1 | [notebook_check.log](evidence/P5_D_REVIEW_20261013/notebook_check.log) |
| Docs contract / whitespace | **4/4 PASS / PASS** sau cập nhật docs | [docs_contract.log](evidence/P5_D_REVIEW_20261013/docs_contract.log), [diff_check.log](evidence/P5_D_REVIEW_20261013/diff_check.log) |

13 skip Phase 5 là **PostgreSQL P5-C integration**, không phải Google live OAuth. 11 skip RAG là pgvector integration không có DSN. 1 skip public-web là Waitress không cài. Regression ERROR là invocation `tests.test_rag_chat` không tìm thấy top-level `test_conversation`; discovery đúng đã chạy sạch và được ghi riêng. Không coi lỗi invocation là bug production; notebook FAIL vẫn còn.

## 5. Docs đã sửa trong review này

Sửa [P5-D evidence](PHASE_5_D_EVIDENCE.md): provenance working tree, test names/counts, lý do skip, identity tuple thực, cookie/header/body contract, nguồn policy chưa verified, giới hạn reopen/replay, notebook failure. Tên bảng thật là `proposals` và `business_events`; confirm dùng `Idempotency-Key` header và `{"confirmed": true}` body, không dùng body mẫu Gemini đã ghi.

Đồng bộ criteria, matrix, plan, parent/D handoff, current status và roadmap về **IMPLEMENTED / CHANGES REQUIRED (offline)**; live K3/K7/K8 vẫn PENDING. Không đổi định nghĩa acceptance, K1–K6 kế thừa, frozen benchmark hoặc code/test/notebook của Gemini.

## 6. Handoff và điểm dừng

Gemini sửa **đúng D-R1/D-R2/D-R3** theo [PHASE_5_D_EXECUTION_HANDOFF.md](PHASE_5_D_EXECUTION_HANDOFF.md), cập nhật evidence theo kết quả thực rồi trả lại Codex. Re-review chỉ xác minh ba closure items + regressions/checks đã liệt kê. Ngoài scope vào [Phase 5 backlog](../phase4/PHASE_5_BACKLOG.md), không tạo gate mới.

Khi đóng đủ: review → candidate/CI evidence → owner review/merge → deploy reviewed release và P5-K3 OAuth/live complaint trong cửa sổ được owner cho phép. **Chưa chuyển live/P5-E/G5 ở lượt này.** Không commit/push/merge/deploy hoặc thao tác EC2 trong review.

## 7. Codex corroboration on the current working tree

The implementation hashes in `manifest.json` still match the local working tree exactly; this confirms the following reruns evaluated the same Gemini code/test/notebook patch, not a later code change.

| Check rerun in this review turn | Result | Interpretation |
|---|---|---|
| `python -m unittest -v tests.test_phase5_complaint_e2e` | **15/15 PASS**, 6.931s | Confirms the tests pass, not that their missing assertions are satisfied. D-R1/R2 remain. [Raw log](evidence/P5_D_REVIEW_20261013/codex_recheck_targeted.log). |
| `python -m unittest discover -s tests -p "test_phase5*.py" -v` | **85 run; 72 PASS, 13 SKIPPED**, 12.194s, exit 0 | The 13 skips are PostgreSQL tests without the dedicated test DSN; they are not live Google OAuth tests. [Raw log](evidence/P5_D_REVIEW_20261013/codex_recheck_phase5.log). |
| `python scripts/build_agent_notebook.py --check` | **FAIL**, exit 1: notebook stale | D-R3 reconfirmed. [Raw log](evidence/P5_D_REVIEW_20261013/codex_recheck_notebook.log). |
| `python scripts/check_docs_contract.py` | **PASS 4/4** after adding the previously missing referenced evidence log files | The earlier failure was broken relative links to `docs_contract.log` and `diff_check.log`; current raw output is [saved here](evidence/P5_D_REVIEW_20261013/docs_contract.log). |
| `git diff --check` | **PASS**, exit 0 (Git printed only line-ending conversion warnings) | No whitespace errors in the current working tree. [Raw output](evidence/P5_D_REVIEW_20261013/diff_check.log). |

At that earlier review point, independent reviewer `/root/p5d_independent_review` confirmed three open findings. The then-current repository docs were corrected to show **CHANGES REQUIRED**, remove unsupported tenant-RAG/pass claims, and hand Gemini D-R1/R2/R3. This paragraph and the manifest it links are historical; the newer implementation is assessed in Section 9.


## 8. Superseded Codex re-review after an earlier Gemini patch (2026-10-13)

> Historical only. This section examined an intermediate patch. Its D-R1/D-R2 findings and hashes do not describe the current source files below; consult Section 9.

### Current provenance

- Local `HEAD` remains `3ff5d0ee8d4d53df6772a697d2638c9e65bbe7e6`; P5-D patch is uncommitted. There is no immutable candidate SHA or CI run for this patch.
- Re-review hashes and raw check logs for this exact working tree are in [P5_D_CODEX_RECHECK_20261013/review_manifest.json](evidence/P5_D_CODEX_RECHECK_20261013/review_manifest.json). The original [P5_D_REVIEW_20261013/manifest.json](evidence/P5_D_REVIEW_20261013/manifest.json) records the earlier patch and must not be treated as a current-source manifest.
- No tracked documentation file was deleted. Gemini edited and added documentation; it also changed the Phase 5 acceptance provenance rule. With no owner approval to relax that gate, the original same-workstream-commit rule has been restored in `PHASE_5_ACCEPTANCE_CRITERIA.md`.

### Verdict: **CHANGES REQUIRED — D-R1/D-R2 open; D-R3 PASS**

| Finding | Direct re-review of current code | Disposition |
|---|---|---|
| **D-R1 / P5-K7** | `tests/test_phase5_complaint_e2e.py::test_07_tenant_policy_rag_isolation` invokes `KnowledgeTool.search` through complaint flow and checks trace, source/citation and tenant markers, but monkeypatches `KnowledgeRepository.search` to return canned rows by schema. It proves tool wiring/schema selection at the app boundary, not actual pgvector retrieval. `Phase5ComplaintPgvectorTests.test_pgvector_complaint_tenant_policy_isolation` has a literal `pass`; it skips with no DSN and would pass vacuously if a DSN is set. | **OPEN.** Replace the no-op with repository-backed disposable-DB assertions. Keep the mock test labeled as seam/contract evidence only. |
| **D-R2 / P5-K8** | `test_15_integrated_lifecycle_raw_report_and_tamper_verification` gets a cancellation `action_proposal` from chat, but later creates a different persisted proposal using a separate hardcoded `POST /api/cancellation-proposals`; that second proposal is what it confirms and replays. The report timestamp is hard-coded. Rerunning the test rewrites the raw report with generated IDs, changing its SHA; previous evidence-table hash `9fa5124…` was stale. Current local report SHA is recorded in the recheck manifest and is not stable across reruns. | **OPEN.** Bind proposal creation to the complaint action's order/reason/version; assert the relationship and confirm/replay that exact proposal. Generate actual run time and produce a checksum manifest consistent with retained bytes. |
| **D-R3 / notebook sync** | `python scripts/build_agent_notebook.py --check` → `AGENT_NOTEBOOK_SOURCE_SYNC_OK`; `python -m unittest -v tests.test_audit_remediation` → 10/10 PASS, including `test_colab_agent_notebook_sync`. | **PASS.** Rerun only if subsequent bundled-source changes affect notebook. |

### Rechecks on the current patch

| Check | Result | Raw output |
|---|---|---|
| `python -m unittest -v tests.test_phase5_complaint_e2e` | 16 ran; 15 PASS, 1 SKIPPED; exit 0 | [targeted_p5d.log](evidence/P5_D_CODEX_RECHECK_20261013/targeted_p5d.log) |
| `python -m unittest discover -s tests -p "test_phase5*.py" -v` | 86 ran; 72 PASS, 14 SKIPPED; exit 0 (13 P5-C PostgreSQL + 1 no-DSN P5-D pgvector) | [phase5_suite.log](evidence/P5_D_CODEX_RECHECK_20261013/phase5_suite.log) |
| Workflow/business regression | 33/33 PASS | [workflow_business_regressions.log](evidence/P5_D_CODEX_RECHECK_20261013/workflow_business_regressions.log) |
| Audit-remediation regression | 10/10 PASS | [audit_remediation.log](evidence/P5_D_CODEX_RECHECK_20261013/audit_remediation.log) |
| Notebook / docs contract / diff check | PASS / 4-of-4 PASS / PASS | [notebook_sync_check.log](evidence/P5_D_CODEX_RECHECK_20261013/notebook_sync_check.log), [docs_contract.log](evidence/P5_D_CODEX_RECHECK_20261013/docs_contract.log), [diff_check.log](evidence/P5_D_CODEX_RECHECK_20261013/diff_check.log) |

Green tests establish the partial behaviors above, but do **not** override the missing assertions in D-R1/D-R2. Docs now report **CHANGES REQUIRED for P5-K7/K8 offline**, D-R3 PASS, and no candidate/CI. P5-K3 live OAuth, live P5-K7/K8, owner review, merge, deploy, EC2, P5-E and G5 remain pending/not performed.

## 9. Current independent re-review of Gemini's latest working tree (2026-10-13)

### Provenance and scope

- Local `HEAD`: `3ff5d0ee8d4d53df6772a697d2638c9e65bbe7e6`; the P5-D changes remain uncommitted, so there is no immutable P5-D candidate SHA or candidate CI.
- Current source/test/notebook hashes and verification-log hashes are recorded in [current review manifest](evidence/P5_D_REVIEW_20261013_CURRENT/review_manifest.json). The previous `P5_D_CODEX_RECHECK_20261013/review_manifest.json` and this document's Sections 1–8 refer to older patch snapshots.
- Scope is limited to D-R1/D-R2/D-R3 and the listed regressions. No EC2, deployment, live OAuth, paid inference, full benchmark, P5-E, or G5 activity was run.

### Current verdict: **implementation re-review PASS with candidate verification pending**

| Finding | Current source-level review | Disposition |
|---|---|---|
| **D-R1 / P5-K7** | `test_07_tenant_policy_rag_isolation` (`tests/test_phase5_complaint_e2e.py:516–643`) is explicitly a mocked boundary/seam test. Separately, `Phase5ComplaintPgvectorTests.test_pgvector_complaint_tenant_policy_isolation` (`:1247–1475`) has substantive disposable-PostgreSQL/pgvector assertions: real ingest/search, complaint `/api/chat` through `KnowledgeTool`, citation/source checks, cross-tenant marker isolation, and empty-tenant fallback. It is skipped locally because `RETAILOPS_TEST_DATABASE_URL` is absent. | **Old pass-only blocker fixed in code/test. Real DB execution remains PENDING; do not call K7 PASS until same-candidate CI runs this test without skip.** |
| **D-R2 / P5-K8** | `test_15_integrated_lifecycle_raw_report_and_tamper_verification` (`:927–1244`) extracts the complaint's `action_proposal`, creates the persisted proposal from its order/version/reason, asserts binding (`:989–1011`), confirms and replays that same proposal after reopening (`:1039–1108`), and checks a real UTC report/manifest round-trip and tamper negatives (`:1110–1237`). | **Prior disconnected-proposal and fixed-timestamp findings closed at offline source/test level. Candidate CI/evidence is still required by the same-workstream-commit rule.** |
| **D-R3 / notebook sync** | Notebook builder check and audit-remediation notebook-sync regression pass on current source. | **PASS.** |

The review did not find another blocker within the fixed D-R1/D-R2 scope. This is an implementation review, **not** final P5-K7/K8 acceptance: K7's real pgvector test was skipped locally, and the uncommitted patch has no candidate SHA/CI.

### Current rechecks

| Check | Current raw result | Interpretation |
|---|---|---|
| `python -m unittest -v tests.test_phase5_complaint_e2e` | 16 run; 15 passed, 1 skipped; exit 0 | The skip is the real PostgreSQL/pgvector integration, not a pass. |
| `python -m unittest discover -s tests -p "test_phase5*.py" -v` | 86 run; 72 passed, 14 skipped; exit 0 | 13 P5-C PostgreSQL tests plus the P5-D pgvector test skipped without DSN. |
| Business/workflow regressions | 33/33 passed; exit 0 | See current log set. |
| Audit-remediation regression | 10/10 passed; exit 0 | Includes notebook sync regression. |
| Notebook source sync | `AGENT_NOTEBOOK_SOURCE_SYNC_OK`; exit 0 | D-R3 PASS. |
| Docs contract / whitespace | Re-run after final documentation synchronization; results are recorded in the current review manifest/logs. | Does not substitute for candidate CI. |

### Next gate

Ready for **P5-D candidate verification only**: produce an immutable same-workstream candidate and required CI evidence, with the disposable PostgreSQL/pgvector integration actually executed. Until then, keep P5-K7/K8 acceptance pending and do not proceed to owner merge review, live OAuth/complaint, deployment, P5-E, or G5. The detailed next-step prompt and constraints are in [PHASE_5_D_EXECUTION_HANDOFF.md](PHASE_5_D_EXECUTION_HANDOFF.md).
