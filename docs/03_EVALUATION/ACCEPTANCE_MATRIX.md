# RetailOps Acceptance Matrix

> **Mục đích:** bảng điều phối nghiệm thu cấp dự án. File này không thay thế acceptance criteria của từng phase; nó chỉ trỏ tới nguồn chuẩn, evidence, gate và bước kế tiếp.
>
> **Cập nhật:** 2026-10-24 — PR #45 (Fix B) merged at `ae0a2e417baf0bc8011bdb62fc9cf3f7741aac36`; owner-pasted DB output records removal of targeted legacy rows ([cleanup record](../04_OPERATIONS/ORDER_DATA_CLEANUP_2026-10-24.md)); [PR #46](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/46) disabling implicit Google-login sample-order seeding merged at `146401f1831b81d5af4a110f6ddc06e50465b9a8` and deployed via run [`40089312937`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40089312937) (`sha256:25193c65e52e7cf7ec41a3a366fa3f76d63c034f686232f405affa04cf1eab63`; [handoff & report](../phase5/DEMO_ORDER_SEEDING_REMEDIATION_HANDOFF_2026-10-24.md)). Does not alter P5-K or G2–G7 acceptance.
> **Latest merged/deployed snapshot:** PR #42 SHA `44540eab516831d5c8232dd80392b8e20c6cd47e`; checks 5/5 and deploy run `39015954088` succeeded per owner-provided evidence. Earlier P5-D `709928290d0448adf9eb97403cee38650ecbc918`; PR #41 K3/K7 `8ef8278108c6d82e03d3c89ae304946ec4b53254`; preceding P5-C `a34b479eeb633ba55090f43a1f4ed7d85f6a3c9a`.
> **Active-row audit snapshot:** `ACCEPTANCE_MATRIX_AUDIT_2026-10-17.md`. The snapshot audits these rows; this file and linked phase criteria remain authoritative.

## Cách dùng và thứ tự ưu tiên

1. Criteria theo phase là nguồn quyết định: [Phase 4 Acceptance](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md) và [Phase 5 Acceptance](../phase5/PHASE_5_ACCEPTANCE_CRITERIA.md).
2. Evidence chỉ được tính PASS khi cùng commit/workflow với row đang nghiệm thu. CI xanh hoặc test cục bộ không tự nâng một row thành PASS nếu criteria còn yêu cầu sign-off, deploy hoặc evidence khác.
3. [Evaluation Protocol](EVALUATION_PROTOCOL.md) định nghĩa G2–G7; bảng này chỉ ghi trạng thái hiện tại và hành động kế tiếp.
4. Phát hiện ngoài row/gate đã chốt phải vào backlog; không tự tạo thêm merge gate nếu owner chưa quyết định.

### Trạng thái

| Nhãn | Ý nghĩa |
|---|---|
| **PASS** | Đủ evidence theo criteria tại đúng SHA; có thể đi tiếp theo gate. |
| **PARTIAL / CHANGES REQUIRED** | Có implementation/test evidence nhưng acceptance assertion còn thiếu hoặc review finding mở; đây là trạng thái báo cáo, không phải gate/tiêu chí mới. |
| **REMEDIATED / RE-REVIEW** | Đã sửa và có test, nhưng chưa được reviewer độc lập xác nhận. |
| **PENDING** | Chưa có evidence cần thiết. |
| **HOLD** | Bị giữ bởi một gate/phụ thuộc trước đó. |
| **BLOCKED** | Có lỗi hoặc review finding phải đóng trước khi đi tiếp. |
| **DEFERRED** | Đã được owner đưa ra backlog; không block scope hiện tại. |

## 1. Project gate matrix

| Gate | Phạm vi | Điều kiện nghiệm thu | Evidence hiện có | SHA / scope | Trạng thái | Hành động kế tiếp |
|---|---|---|---|---|---|---|
| G0 | Phase 4 | Spec và merge scope được owner chốt | [Phase 4 criteria](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md) | Phase 4 v1 | PASS | Không mở thêm gate ngoài K1–K8 |
| G1 | Phase 4 | Harness/build và contract checks hoàn tất | [Phase 4 evidence](../phase4/PHASE_4_ACCEPTANCE_EVIDENCE_8a666fc.md) | `8a666fc` | PASS | Đã chuyển sang merged replay |
| G2 | Phase 4/5 prerequisite | Clean merged checkout, frozen hashes, mock250 và contracts cùng SHA | [G2 evidence](../phase5/PHASE_5_G2_EVIDENCE_8868c5c.md) | `8868c5c` | PASS | Giữ làm prerequisite Phase 5 |
| G3 | Live approval | Owner approval, lane, quota, price cap và stop rule | [Evaluation protocol](EVALUATION_PROTOCOL.md#2-g2-đến-g7--checklist-protocol-đã-có) | Chưa cấp | HOLD | Chỉ mở khi owner yêu cầu smoke |
| G4 | Controlled smoke | Operational health/session smoke và, riêng cho AI lane, model/DB/KB evidence | [Phase 5 criteria](../phase5/PHASE_5_ACCEPTANCE_CRITERIA.md) | PR #42 deploy run `39015954088` succeeded; no timestamped current EC2 snapshot supplied in this review. Earlier P5-D run `38886385884` records rollout/smoke at that time. | **Operational deployment recorded; current runtime reconciliation and per-lane AI evidence PENDING** | Use P5-E bounded offline/controlled evidence; inspect live runtime only in a separately authorized window. Do not infer G5 or AI-lane G4 |
| G5 | Measurement readiness | Lane evidence, identity, completeness, budget và validated manifest đầy đủ | [Evaluation protocol](EVALUATION_PROTOCOL.md) | Chưa có | HOLD | Không ghi READY FOR MEASUREMENT |
| G6 | Full measurement approval | Full-run approval/cap riêng | [Evaluation protocol](EVALUATION_PROTOCOL.md) | Chưa có | HOLD | Chờ G5 và owner approval |
| G7 | Measured result | Raw bundle, aggregate, metrics, statistics, cost và limitations | [Evaluation protocol](EVALUATION_PROTOCOL.md) | Chưa có | HOLD | Chưa chạy live/paid |

## Current operational follow-up (not a P5-K/G acceptance row)

| Workstream | Evidence now | Status | Next action |
|---|---|---|---|
| Stop implicit sample-order creation on Google login | Owner-pasted cleanup output confirms the targeted legacy rows are absent ([cleanup record](../04_OPERATIONS/ORDER_DATA_CLEANUP_2026-10-24.md)). [PR #46](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/46) (reviewed code/test SHA `a0b96db71cc5913800ebe2b40e9ec78561978cf6`, independent review `PASS` with `0` blocker/high-risk findings) passed 5/5 required checks ([CI `40088640697`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40088640697) job `120856594646`: `721` tests / `0 skipped` on host + container; [Ops Console `40088640680`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40088640680) job `120856594180`: `19` tests / `0 skipped`), merged to `main` at `146401f1831b81d5af4a110f6ddc06e50465b9a8` (post-merge CI `40089312939` & Ops `40089312947` `SUCCESS`), deployed via official [Deploy `40089312937`](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40089312937) (`deploy` job `120858580750`, ECR image `sha256:25193c65e52e7cf7ec41a3a366fa3f76d63c034f686232f405affa04cf1eab63`, `PUBLIC_WEB_ROLLOUT_OK`, 2× `LIVE_E2E_SMOKE_OK`, `ADMIN_CONSOLE_SMOKE_OK`), and passed read-only HTTPS `/healthz` (`200`), `/` (`data-data-mode="persistent-demo"`), and `/app.js` (`708b9ec3…`) checks on `https://retailops.98-93-228-155.sslip.io` ([report](../phase5/DEMO_ORDER_SEEDING_REMEDIATION_HANDOFF_2026-10-24.md)). | **CODE, CI, DEPLOY & READ-ONLY HTTPS RUNTIME PASS; AUTHENTICATED CHROME ORDERS UI CHECK PENDING OWNER SESSION** | Owner hard-refreshes (`Ctrl+F5`) `https://retailops.98-93-228-155.sslip.io` in logged-in Chrome and visually inspects Customer Orders / Store Manager Orders read-only (no order create/edit/delete). |

## 2. Phase 4 frozen merge matrix

Nguồn chuẩn là [PHASE_4_ACCEPTANCE_CRITERIA.md](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md). [PHASE_4_TEST_MATRIX.md](../phase4/PHASE_4_TEST_MATRIX.md) chỉ mô tả benchmark 250 ca, không phải release gate riêng.

| ID | Acceptance statement | Evidence | SHA | Status | Scope boundary |
|---|---|---|---|---|---|
| K1 | Mutation benchmark hash bị reject | Acceptance evidence K1 | `8a666fc` | PASS | Offline harness |
| K2 | Blocked case không làm đổi quality denominator | Acceptance evidence K2 | `8a666fc` | PASS | Offline harness |
| K3 | Tool trace/safety flags sai kiểu bị reject | Acceptance evidence K3 | `8a666fc` | PASS | Offline harness |
| K4 | Required CI checks xanh | Acceptance evidence K4 | `8a666fc` | PASS | CI |
| K5 | Full suite đạt ngưỡng criteria | Acceptance evidence K5 | `8a666fc` | PASS | CI offline |
| K6 | Mock 250-case bundle hợp lệ | Acceptance evidence K6 | `8a666fc` | PASS | Offline mock |
| K7 | `git diff --check` sạch | Acceptance evidence K7 | `8a666fc` | PASS | Repository hygiene |
| K8 | Sáu contract checks PASS | Acceptance evidence K8 | `8a666fc` | PASS | Offline/CI |
| P4-SIGNOFF | Reviewer độc lập xác minh đúng 8 mục | Owner-provided Antigravity / Claude Sonnet 5.5 sign-off (2026-10-09 11:46 +07), recorded in current status note of [Phase 4 criteria](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md); PR #36 merged; G2 evidence PASS | `cf19766` → G2 `8868c5c` | PASS (owner-provided record; raw CI/sign-off artifact not archived) | Historical v1 packet remains frozen; no reopen |

## 3. Phase 5 dev/synthetic acceptance matrix

Nguồn chuẩn là [PHASE_5_ACCEPTANCE_CRITERIA.md](../phase5/PHASE_5_ACCEPTANCE_CRITERIA.md). P5-K4–K6 chỉ PASS sau khi có sign-off độc lập trên candidate SHA và CI required checks xanh.

| ID | Capability | Required evidence | Current evidence | Candidate / deployed SHA | Status | Next action |
|---|---|---|---|---|---|---|
| P5-K1 | Smoke isolation | Tenant/customer reservation không bị đụng; identity tuple trong report | Owner-pasted fields from both P5-C reports: `pass=true`, expected/runtime digest match, checks and cleanup true, distinct synthetic tenants | Deploy run `38335308481` on `a34b479`; reports `LIVE_SMOKE_20261013T040523Z.json`, `LIVE_SMOKE_20261013T040555Z.json` | **PASS on P5-C (`a34b479`) only** | P5-D run has smoke-success markers, but inspect its latest JSONs for identity/check/cleanup fields before extending this PASS to `709928…` |
| P5-K2 | Runtime health | Image đúng merged SHA; web/admin/PostgreSQL/Caddy healthy; health contract | Owner snapshot `2026-10-13T04:36:57Z`: web/admin match `deployed.env` digest `sha256:2c058277…`, PostgreSQL healthy, Caddy on both networks. P5-D deploy log reports image `sha256:64c18…` and rollout success, but no timestamped full-service snapshot was supplied. | P5-C `a34b479` / digest `2c058277…`; P5-D merge `709928…` / activated image `64c18…` | **PASS on P5-C only; P5-D runtime reconciliation PENDING** | Inspect existing post-deploy service state/report for P5-D before assigning latest-release K2 |
| P5-K3 | Google identity | OAuth state/nonce, issuer, verified email, `sub`, correct session tuple; existing identities cannot be silently re-routed; inactive-only membership fails closed without new customer-link/membership/session; new-customer onboarding is explicit and tenant-scoped | Offline code/regression review and SQLite/PostgreSQL CI completed on PR #41; final PR head `c1c6762…` merged as `8ef8278…`; post-merge CI run `39007432165` succeeded. Live OAuth not run; original EC2 incident root cause remains unconfirmed. | PR #41 final head `c1c6762…` → merged `8ef8278…` | **PASS — offline implementation/regression; live OAuth PENDING** | No more offline K3 fix. Live validation requires successful deployment, dedicated test identity and owner approval. |
| P5-K4 | External mapping | Tenant-scoped mapping, audit, no email key, recovery không split customer | 45 targeted PASS; offline CI SUCCESS; independent sign-off trên candidate `3ff5d0e` | Candidate `3ff5d0e` → merged P5-C `a34b479`; CI `38335308462` | **PASS (offline/merged)** | No further K4 action; accepted for P5-C |
| P5-K5 | Event contract | Exact 11 fields, HMAC, timestamp, tenant binding, idempotency/replay | 45 targeted PASS; offline CI SUCCESS; independent sign-off trên candidate `3ff5d0e` | Candidate `3ff5d0e` → merged P5-C `a34b479`; CI `38335308462` | **PASS (offline/merged)** | No further K5 action; accepted for P5-C |
| P5-K6 | Order visibility | Order owner không đổi; customer isolation; cross-customer access bị từ chối | 45 targeted PASS; offline CI SUCCESS; independent sign-off trên candidate `3ff5d0e` | Candidate `3ff5d0e` → merged P5-C `a34b479`; CI `38335308462` | **PASS (offline/merged)** | No further K6 action; accepted for P5-C |
| P5-K7 | Complaint workflow | Same Google customer session; worker reads correct order/policy, proposal/handoff before mutation | Offline negative-order snapshot assertions and owned-order positive control passed review/CI on PR #41; CI on merge push succeeded. Snapshots cover relevant business state, not every database field. | PR #41 merged `8ef8278…` | **PASS — offline negative-path safety/CI; live same-session acceptance PENDING** | No further offline K7 fix. Live complaint/confirmation requires deployed code, K3 OAuth, and owner approval. See `../phase5/GOOGLE_LOGIN_AMBIGUOUS_TENANT_REVIEW_2026-10-16.md`. |
| P5-K8 | Confirmation/audit | Confirmation idempotent; state/audit/raw checksums khớp | `test_15` lifecycle/report/manifest SHA-256 and tamper rejection pass locally and in both 677-test CI runs on tested PR merge tree containing `dd54480`; merged release includes this implementation. | Candidate `dd54480` → merged `709928…`; tested merge ref `18c7e5f…`; deploy run `38886385884` | **Offline lifecycle evidence PASS; live audit/report acceptance PENDING; overall Phase 5 PENDING** | Keep offline evidence distinct; complete the live same-session lifecycle only after K3 and owner approval |

**P5-D / PR #41 / PR #42 status:** PR #40/P5-D and PR #41 K3/K7 are merged. PR #41 deploy run `39007432153` failed at SSM preflight; PR #42/P-604 later merged at `44540eab…`, checks 5/5 and deploy `39015954088` succeeded. PR #42 added an orderless catalog fixture and preserved the existing P-602 sample order; the visible trouser name is therefore not evidence that deployment failed. The owner has now requested a **demo display-label-only** change, tracked in P5-E; no existing customer/EC2 record may be mutated by this task. Latest-release runtime/K1/K2 reconciliation, live OAuth/complaint/audit and AI-lane G4 remain separately pending; G5–G7 held. Phase 5 is not fully accepted.

## 3A. P5-E candidate reviewed — Round 3 remediated, pending Codex re-review (2026-10-19)

Nguồn chuẩn: [P5-E plan](../phase5/PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md), [acceptance criteria](../phase5/PHASE_5_E_ACCEPTANCE_CRITERIA.md), [manual-test review](../phase5/PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md), [Argon handoff](../phase5/PHASE_5_E_EXECUTION_HANDOFF.md), [independent review](../phase5/REVIEW_ARGON_P5_E_2026-10-18.md), [evidence snapshot](../phase5/PHASE_5_E_EVIDENCE_2026-10-18.md). Reviewed Round 2 snapshot `982801144702b703eb9af3d4d1435a3a75b1b1e4` → Round 3 remediated code candidate `97b11bbcaa67a7b2f4297e63437d5802ee789384` (base `44540eab516831d5c8232dd80392b8e20c6cd47e`, tested merge ref `e10f9b1f24c30533c36f4b6d77aec6fb51e1baa1`) on [PR #43](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/43): [CI 39203490030](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39203490030) (`offline` `117901231330`: `701` tests, `0 skipped`, `pgvector 0.8.6`; `colab-python313` `117901231538`) và [Ops Console 39203490035](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39203490035) (`postgres` `117901231247`: `19` tests, `0 skipped`; portable `117901231530`/`117901231463`: `19` tests, `skipped=2`) SUCCESS, 5/5 checks; local targeted P5-E suite `14/14 PASS` (`0 skipped`).

| P5-E area | Required acceptance | Current disposition | Gate / next action |
|---|---|---|---|
| AI trust / action intent | AI1–AI6 giữ nguyên criteria | **AI2/AI3/AI4/AI6 SUPPORTED; AI1 & AI5 REMEDIATED on `97b11bb` (pending Codex re-review)** — `sanitize_reasoning_text` chặn canary/secret trong `trace.reasoning`/`thought` trong khi giữ nguyên ordinary CoT; PG `test_phase5_e_postgres_governance_and_ai_boundaries` có assertion cho provider `429` (`api_rate_limited`) và daily quota `429` (`api_daily_limit`) + state invariance | Codex re-review trên PR #43 |
| Account & quota governance | ADM1–ADM6 giữ nguyên criteria | **SUPPORTED** — R2/R4/ADM1–ADM6 đã đóng trong review `9828011`; Ops Console vẫn read-only | Không mở lại; giữ nguyên regression SQLite/PG |
| Demo label / inventory truth | DATA1–DATA2 giữ nguyên criteria | **DATA2 SUPPORTED; DATA1 REMEDIATED on `97b11bb` (pending Codex re-review)** — backfill provenance chỉ nhận đúng bộ 3 đơn fixture demo (`P-601`/`P-602`/`P-603`) với đúng thuộc tính kỳ vọng và không có `imported_events`/`order_items`/`sales_event_imported` ngoài fixture; mixed/import provenance giữ nhãn canonical | Codex re-review; không sửa dữ liệu thật/EC2 |
| P5-E overall | All 14 criteria on same candidate SHA; exact backend/run and tested-ref mapping, no required skips | **REMEDIATED / READY FOR CODEX RE-REVIEW (overall review verdict remains `CHANGES REQUIRED` until Codex re-review)** | PR #43 merged at `ef40d131ef9244fa51844ae8990a05888990cdc8`; formal criterion-level reconciliation remains separate from Fix A; chưa mở performance |

## 3B. Phase 5 Fix A — Manager navigation & demo-order cleanup (2026-10-20)

> **Current operational override (2026-10-23):** The former Fix A evidence Step 3/4 shell commands and the old 4-step execution instruction are retracted and must not be run. The action cell in the historical row below is superseded by [Fix B](../phase5_fix_B/README.md); local SQLite PASS does not authorize PostgreSQL or production use.

This is a separate, bounded owner-requested remediation, not a replacement for P5-DM and not evidence for P5-E/G4/G5. Scope has two tracks: (1) manager console navigation back to “Tổng quan & KPIs”; (2) remove only the exact old demo order snapshot `O-819126` after tenant-scoped verification, while preserving the corrected `P-602` catalog row (`Quần tây đen hàn quốc`). SSOT: [packet index](../phase5_fix_A/README.md), [review](../phase5_fix_A/PHASE_5_FIX_A_REVIEW_2026-10-20.md), [acceptance criteria](../phase5_fix_A/PHASE_5_FIX_A_ACCEPTANCE_CRITERIA.md), [evidence](../phase5_fix_A/PHASE_5_FIX_A_EVIDENCE.md), [Argon handoff](../phase5_fix_A/PHASE_5_FIX_A_EXECUTION_HANDOFF.md).

| Phase | Required evidence | Current evidence | Status | Next action |
|---|---|---|---|---|
| P5-Fix-A | `FIXA-UI1…UI4`, `DATA1…DATA5`, `CI1…CI2`, `DEPLOY1…DEPLOY2`, `DOC1` on one isolated candidate from `ef40d131ef9244fa51844ae8990a05888990cdc8`; exact tenant/tuple, validated backup and dry-run before any production write. | [PR #44](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/44) code/test candidate `d39f397a76444f2f1d9704364750c962fdd4c508` (tested merge ref `ef179473c28dd9ca5b90f43bcd48e37ace310c1c`): [CI 39380738696](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39380738696) (`offline` `118489038860`: `704` tests, `0 skipped`, `pgvector 0.8.6`; `colab-python313` `118489038563`) & [Ops Console 39380738698](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39380738698) (`postgres` `118489038510`: `19` tests, `0` skipped; `portable` `118489038886`/`118489039097`: `19` tests, `skipped=2`) `5/5 SUCCESS`; UI/data code and CI are accepted on PR #44. | **CODE & CI PASS; LIVE CLEANUP BLOCKED under Fix B** | Do not use retired Fix A evidence commands/runbook. Follow the current [Fix B packet](../phase5_fix_B/README.md) only after its review, PostgreSQL CI, and operational approval gates pass. |

## 3C. Phase 5 Fix B — one-time live demo-order cleanup (2026-10-24)

Source of truth: [Fix B index](../phase5_fix_B/README.md), [independent review R6](../phase5_fix_B/PHASE_5_FIX_B_REVIEW_R6_2026-10-24.md), [historical review R5](../phase5_fix_B/PHASE_5_FIX_B_REVIEW_R5_2026-10-24.md), [historical self-review R3](../phase5_fix_B/PHASE_5_FIX_B_REVIEW_R3_2026-10-23.md), [historical review R2](../phase5_fix_B/PHASE_5_FIX_B_REVIEW_R2_2026-10-23.md), [criteria](../phase5_fix_B/PHASE_5_FIX_B_ACCEPTANCE_CRITERIA.md), [evidence](../phase5_fix_B/PHASE_5_FIX_B_EVIDENCE.md), and [handoff](../phase5_fix_B/PHASE_5_FIX_B_EXECUTION_HANDOFF.md). This is an operational data action, not P5-DM CRUD and not evidence for P5-E/G4/G5/performance.

| Phase | Required evidence | Current evidence | Status | Next action |
|---|---|---|---|---|
| P5-Fix-B | Resolve FIXB-1..4 and R4/R5/R6 follow-ups; side-effect-free dry-run; fail-closed backend/DSN and explicit operator attribution; guarded disposable PostgreSQL CLI CI (`127.0.0.1:5432`, `dbname=retailops_test`, `user=retailops_test`); source/image and tenant/tuple match; backup/restore; rehearsal; read-only live dry-run; final execute approval; post-check/retention. | Independent review R6 (2026-10-24) PASS (`0` findings) on R6 code/test candidate `1d09e7d330752d19bb8b4f9dab32e68ddffe53bb` (base `83bee6c5c42d9996a3230208d30ec6e6f0c5de2e`). Draft [PR #45](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/45) (tested merge SHA `fd061059b3c4411136ba737478b462137e75bac4`) passed 5/5 checks: [CI 40067793080](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40067793080) (`offline` `120794589040`: `719` tests, `0 skipped` on host + packaged `retailops:ci` container, `PostgresTestGuardTests` `9/9`, `pgvector 0.8.6`; `colab-python313` `120794589233`) & [Ops Console 40067793153](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/40067793153) (`postgres` `120794589333`: `19` tests, `0 skipped`; `portable` `120794589259`/`120794589336`: `19` tests, `skipped=2` due to no PostgreSQL service/DSN in portable mode — not counted as PG PASS). No merge, deploy, or live DB operation. | **CODE, R6 REVIEW & PG CI PASS; MERGE/DEPLOY & LIVE BLOCKED** | Await owner merge/deploy authorization (`FIXB-DEPLOY-APPROVAL`) and separate operational window for `FIXB-SOURCE`..`FIXB-POSTCHECK` per [Fix B handoff](../phase5_fix_B/PHASE_5_FIX_B_EXECUTION_HANDOFF.md). |

## 3D. P5-DM Store Data Management gap

Source/status: [P5-DM entry in the Phase 5 index](../phase5/README.md#p5-dm-store-data-management). This row records project sequencing only; it does not invent or replace phase-specific acceptance criteria.

| Phase | Required evidence | Current evidence | Status | Next action |
|---|---|---|---|---|
| P5-DM | Owner-approved plan and criteria for tenant-scoped roles; product/inventory CRUD and archive; simulated external-system import/export adapters with preview, validation, atomic commit and audit; order/customer edits preserving history; tenant isolation and SQLite/PostgreSQL coverage; real-data import disabled until backup/restore and controls pass. | The high-level direction is recorded in the Phase 5 index. Detailed plan, I/O-retention contract, acceptance criteria, evidence ledger and execution handoff are absent from this candidate checkout; no implementation/evidence is claimed. | **PLANNED / NOT READY** | Create and independently review the canonical P5-DM packet and link it here before implementation. Keep synthetic data only; do not enable real CSV or treat this row as performance acceptance. |

## 4. Review and deployment decision

P5-C remains accepted on its own evidence. P5-D and PR #41 evidence remains scoped to the corresponding candidate/deploy records. PR #42 deployment succeeded according to run `39015954088`, but no timestamped post-deploy runtime snapshot was supplied here; do not claim current EC2 health or infer a persistent order update. Operational deployment does not establish live OAuth, per-lane AI quality, or measurement readiness.

| Decision | Điều kiện bắt buộc | Hiện tại |
|---|---|---|
| Merge P5-C | P5-K4–K6 được reviewer độc lập ký trên cùng candidate SHA; CI bắt buộc xanh | **PASS — merged `a34b479`** |
| Deploy workflow P5-C | Merged SHA; deploy job hoàn tất thành công | **PASS — run `38335308481`, job `115122302562`, SHA `a34b479`** |
| P5-C EC2 runtime reconciliation | Image/release khớp SHA; expected web/admin/DB/Caddy topology và health | **PASS — P5-C post-run snapshot matches configured/runtime digest and expected topology** |
| P5-C post-deploy smoke evidence / P5-K1 | Smoke dùng image kỳ vọng; report ghi identity tuple, không đụng reservation | **PASS on P5-C — both owner-pasted report excerpts meet the fixed assertions; raw JSON remains on EC2** |
| P5-D source/offline acceptance | D-R1 pgvector retrieval/K7 grounding; D-R2 lifecycle/checksum/reopen-confirm replay; D-R3 notebook sync | Historical Round-4 evidence on `dd54480` remains scoped. PR #41 K3/K7 offline work is merged; post-merge CI/Ops succeeded. | P5-D `709928…`; PR #41 merged `8ef8278…` | **Offline gates PASS; live/runtime acceptance PENDING** | No more offline K3/K7 task. Start AI-lane G4 separately; keep live gates separate. |
| P5-D deploy workflow | Merged image rollout and operational smoke | **PASS at run time** — run `38886385884`, attempt 2/job `116951239240`, activated image `64c18…`, two web smoke markers and one admin smoke marker. |
| P5-D runtime/K1-K2 reconciliation | Full report identity/cleanup and timestamped health for web/admin/PostgreSQL/Caddy on exact image | **PENDING** — inspect existing EC2 reports/snapshot; current runtime is not asserted from workflow-time markers. |
| P5-D live K3/K7/K8 | Dedicated real Google test identity; same-session complaint, confirmation and audit | Offline K3/K7 code/regression evidence merged in PR #41; no live Google session or complaint/confirmation/audit evidence was generated. | Live environment not exercised; PR #41 deploy failed at SSM preflight | **PENDING — not an offline code blocker** | Only after successful deployment, dedicated identity and explicit owner approval. |
| READY FOR MEASUREMENT | G5 PASS, không chỉ smoke/CI/mock | HOLD |

P5-C evidence remains scoped to `a34b479`. PR #41 final head `c1c6762…` merged at `8ef8278`; post-merge CI/Ops passed, but automatic deploy `39007432153` failed at SSM preflight (`InvalidInstanceId`). **Merged, not confirmed deployed/live.** Latest-release K1/K2, live K3/K7/K8 and AI-lane G4 remain pending; G5–G7 held. No paid/full measurement is authorized. This does not block offline AI-lane work.

## 5. EC2 power plan

| Công việc | Cần bật EC2? | Lý do | Có thể để EC2 tắt? |
|---|---:|---|---:|
| Sửa code P5-C, review, unit tests, docs và contract checks | Không | Chạy trên máy local hoặc GitHub Actions | Có |
| CI PostgreSQL và full suite của PR | Không | CI tạo PostgreSQL service riêng | Có |
| Owner review, merge PR và cập nhật backlog | Không | Thao tác GitHub/docs | Có |
| Deploy P5-C sau merge và chạy migration PostgreSQL hiện hữu | Đã xong (2026-10-13) | Deploy run `38335308481`, job `115122302562`; dòng này là mốc lịch sử, không phải việc còn chờ | Có |
| Read-only P5-D post-deploy runtime/report reconciliation | Có | Cần truy vấn Session Manager để lấy timestamped container/image health và đọc report JSON đã sinh | Có sau khi capture evidence |
| Dedicated Google OAuth + live same-session complaint (K3/K7/K8) | Có | Cần public web/Google callback và synthetic customer lane | Không trong cửa sổ live test |
| P5-E AI Trust & Account Operations implementation/CI | Không | Offline bounded tests on candidate; no live model/EC2/DB change | Có |
| P5-F G5 preflight document-only (former P5-E) | Không | Manifest/quota/cap/stop-rule planning; không chạy benchmark | Có |
| Full live/paid measurement (G6/G7) | Có | Chỉ sau G5 PASS và owner approval riêng | Không trước approval |
| P5-K1/P5-K2 và G4 controlled smoke | Có | Cần HTTPS endpoint, image và DB thật | Không trong cửa sổ smoke |
| P5-K3 Google OAuth thật | Có | Cần callback HTTPS trỏ tới runtime đang chạy | Có nếu chỉ dùng offline identity tests |
| P5-D offline complaint E2E / P5-K7–K8 | Không | Unit/CI integration dùng session/order/workflow fixtures và CI PostgreSQL/pgvector; current K7 remediation/CI không cần EC2 | Có |
| Future live complaint E2E (after offline acceptance + OAuth authorization) | Có | Cần deployed runtime, live identity/session và owner-approved environment | Không trong cửa sổ hiện tại |
| G5/G6/G7 live measurement | Có, cùng Colab/vLLM hoặc provider đã duyệt | Cần lane runtime, model, DB/KB và evidence live | Có cho tới khi có approval |

**Quy tắc tiết kiệm:** giữ EC2 tắt cho P5-E docs/code/local tests/GitHub CI. Chỉ bật khi có bước deploy, controlled operational smoke hoặc live test được owner-authorized; sau khi lưu raw report thì tắt lại. Mỗi lần stop/start có thể đổi public IP, vì vậy trước HTTPS smoke phải đồng bộ lại hostname/origin và cấp lại Caddy certificate theo [runbook](../04_OPERATIONS/RUNBOOK.md). EC2 bật không đồng nghĩa được phép chạy paid/full measurement; G5/G6 vẫn cần gate riêng.

## 6. Các ma trận không phải SSOT cấp dự án

| Tài liệu | Vai trò | Cách dùng |
|---|---|---|
| [PHASE_4_TEST_MATRIX.md](../phase4/PHASE_4_TEST_MATRIX.md) | Frozen 250-case dataset/test contract | Dùng cho K6/protocol, không tạo gate mới |
| [BUSINESS_TEST_SCENARIOS.md](../BUSINESS_TEST_SCENARIOS.md) | Business/SOP coverage | Dùng để chọn test, không thay acceptance |
| Các bảng AC trong plan Module 2.5/RBAC | Local design or historical snapshots | Chỉ tham khảo khi row hiện hành trỏ tới chúng |

## 7. Anti-loop rule

Review kết thúc khi row bắt buộc đạt PASS hoặc được owner đánh dấu DEFERRED/BACKLOG. Không tiếp tục săn lỗi vô hạn, không thêm K9/P5-K9 trong cùng lượt, và không coi một finding ngoài scope là lý do mở lại gate đã đóng.
