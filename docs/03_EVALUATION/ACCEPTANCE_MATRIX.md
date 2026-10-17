# RetailOps Acceptance Matrix

> **Mục đích:** bảng điều phối nghiệm thu cấp dự án. File này không thay thế acceptance criteria của từng phase; nó chỉ trỏ tới nguồn chuẩn, evidence, gate và bước kế tiếp.
>
> **Cập nhật:** 2026-10-13
> **Merged baseline:** `a34b479eeb633ba55090f43a1f4ed7d85f6a3c9a` (P5-C, PR [#39](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/39)); P5-B baseline `80f51569b3bef5ae0793bac1593fb91e39558477`.

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
| G4 | Controlled smoke | Operational health/session smoke và, riêng cho AI lane, model/DB/KB evidence | [Phase 5 criteria](../phase5/PHASE_5_ACCEPTANCE_CRITERIA.md) | P5-C merged `a34b479`; deploy run `38335308481`; two owner-pasted post-deploy smoke report excerpts. `80f5156` is the earlier P5-B baseline. | **PASS operational smoke only**; per-lane AI evidence PENDING | Không suy ra G5 hoặc AI-lane G4 |
| G5 | Measurement readiness | Lane evidence, identity, completeness, budget và validated manifest đầy đủ | [Evaluation protocol](EVALUATION_PROTOCOL.md) | Chưa có | HOLD | Không ghi READY FOR MEASUREMENT |
| G6 | Full measurement approval | Full-run approval/cap riêng | [Evaluation protocol](EVALUATION_PROTOCOL.md) | Chưa có | HOLD | Chờ G5 và owner approval |
| G7 | Measured result | Raw bundle, aggregate, metrics, statistics, cost và limitations | [Evaluation protocol](EVALUATION_PROTOCOL.md) | Chưa có | HOLD | Chưa chạy live/paid |

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
| P5-K1 | Smoke isolation | Tenant/customer reservation không bị đụng; identity tuple trong report | Owner-pasted fields from both reports: `pass=true`; exact same expected/runtime digest; all smoke checks true; distinct synthetic tenants; credential revocation true | Deploy run `38335308481` on `a34b479`; `LIVE_SMOKE_20261013T040523Z.json`, `LIVE_SMOKE_20261013T040555Z.json` | **PASS (owner-provided report excerpts)** | Không rerun; raw JSON files remain on EC2 |
| P5-K2 | Runtime health | Image đúng merged SHA; web/admin/PostgreSQL/Caddy healthy; health contract | Deploy run/job SUCCESS; owner snapshot `2026-10-13T04:36:57Z`: web/admin healthy and both image IDs match `deployed.env` digest `sha256:2c058277…`; PostgreSQL healthy; Caddy running on default + admin networks with `/etc/caddy/admin` mount | Merged `a34b479`; runtime digest `sha256:2c05827775460a5c56c41855dcd1a216e9c529e89a75614e553e91e00b922c1e` | **PASS (deploy + post-deploy runtime)** | No runtime action; retain snapshot as evidence. OCI revision label/raw deploy log not separately captured |
| P5-K3 | Google identity | OAuth state/nonce, issuer, verified email, `sub`, session tuple | Offline tests PASS; live OAuth chưa chạy | P5-B `80f5156` | PARTIAL / PENDING live | Không dùng live OAuth trong P5-C |
| P5-K4 | External mapping | Tenant-scoped mapping, audit, no email key, recovery không split customer | 45 targeted PASS; offline CI SUCCESS; independent sign-off trên candidate `3ff5d0e` | Candidate `3ff5d0e` → merged `a34b479`; CI `38335308462` | **PASS (offline/merged)** | No K4 action; close fixed P5-D findings before next stage |
| P5-K5 | Event contract | Exact 11 fields, HMAC, timestamp, tenant binding, idempotency/replay | 45 targeted PASS; offline CI SUCCESS; independent sign-off trên candidate `3ff5d0e` | Candidate `3ff5d0e` → merged `a34b479`; CI `38335308462` | **PASS (offline/merged)** | No K5 action; close fixed P5-D findings before next stage |
| P5-K6 | Order visibility | Order owner không đổi; customer isolation; cross-customer access bị từ chối | 45 targeted PASS; offline CI SUCCESS; independent sign-off trên candidate `3ff5d0e` | Candidate `3ff5d0e` → merged `a34b479`; CI `38335308462` | **PASS (offline/merged)** | No K6 action; close fixed P5-D findings before next stage |
| P5-K7 | Complaint workflow | Cùng Google customer session; worker đọc đúng order/policy, proposal/handoff trước mutation | D-R1 source/test review confirms substantive disposable PostgreSQL/pgvector assertions; local test **SKIPPED** without `RETAILOPS_TEST_DATABASE_URL` | Uncommitted patch on base `3ff5d0e`; no immutable candidate SHA/CI | **PENDING same-candidate PostgreSQL CI**; live PENDING | Require CI run of pgvector test without skip; no live/deploy |
| P5-K8 | Confirmation/audit | Confirmation idempotent; state/audit/raw checksums khớp | D-R2 offline lifecycle test and source review PASS: complaint `action_proposal` fields bound to persisted proposal; same proposal confirmed/replayed after reopen; report/manifest round-trip and tamper assertions | Uncommitted patch on base `3ff5d0e`; no immutable candidate SHA/CI | **PARTIAL — local PASS, same-candidate CI/evidence pending**; live PENDING | Require immutable candidate CI/evidence, then owner review; no live/deploy |

**P5-D status:** Codex implementation re-review finds D-R2 and D-R3 PASS and the former D-R1 no-op replaced by substantive pgvector assertions; however, the real PostgreSQL test was skipped locally. P5-K7/K8 acceptance remains pending an immutable same-workstream candidate and CI evidence (including execution of the pgvector test). See [current review](../phase5/REVIEW_GEMINI_P5_D_2026-10-13.md) and [current recheck set](../phase5/evidence/P5_D_REVIEW_20261013_CURRENT/). Not ready for owner merge review, live work, or deploy.

### Non-gating AI probe fixture

P-604 (children's wooden block set) is an orderless synthetic fixture for factuality probes only. Its price, stock, warranty, recommended age, safety warnings/certifications, and variants are intentionally unknown. Focused SQLite regression passed locally; PostgreSQL regression runs in candidate CI. These tests do **not** establish model quality or product safety. Prompt probes and any live-model result remain separate evaluation work and do not add a new P5/G0–G7 merge gate. See [AI evaluation notes](../01_AI_SYSTEM/AI_EVALUATION_AND_SAFETY.md#7-catalog-factuality-probe--p-604-2026-10-17).

## 3A. Owner-requested P5-E workstream — AI Trust, Account Governance & Catalog Hygiene

Nguồn chuẩn: [P5-E plan](../phase5/PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md), [acceptance criteria](../phase5/PHASE_5_E_ACCEPTANCE_CRITERIA.md), [manual-test review](../phase5/PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md), [Argon handoff](../phase5/PHASE_5_E_EXECUTION_HANDOFF.md), [ADR](../phase5/ADR_P5_E_ACCOUNT_QUOTA_GOVERNANCE.md), [P5-E evidence packet](../phase5/PHASE_5_E_EVIDENCE_2026-10-17.md).

| ID | Capability | Required evidence | Current evidence | Status | Gate / next action |
|---|---|---|---|---|---|
| P5-E-AI1 | Prompt injection, persona, encoding & secret/canary resistance | Plain/reversed/Base64/hex canary blocked; CoT UI preserved | [P5-E evidence](../phase5/PHASE_5_E_EVIDENCE_2026-10-17.md) (`test_p5e_ai1_*`) | **REMEDIATED / RE-REVIEW** | Independent Codex review on candidate SHA |
| P5-E-AI2 | Read-only vs mutation intent boundary & confirmation gate | Quoted/conflicting cancel text in read-only query produces zero mutation/proposal; positive control mutates once on confirm | [P5-E evidence](../phase5/PHASE_5_E_EVIDENCE_2026-10-17.md) (`test_p5e_ai2_*`) | **REMEDIATED / RE-REVIEW** | Independent Codex review on candidate SHA |
| P5-E-AI3 | Entity, owner, tenant & Unicode confusable / SQL-like ID boundary | Foreign/missing/confusable/SQL-like IDs fail closed (`404`) on SQLite & PostgreSQL | [P5-E evidence](../phase5/PHASE_5_E_EVIDENCE_2026-10-17.md) (`test_p5e_ai3_*`, `test_postgres.py`) | **REMEDIATED / RE-REVIEW** | Independent Codex review on candidate SHA |
| P5-E-AI4 | Factuality grounding, unknown handling (`P-604`), `list_orders` truncation contract | `stock_unknown` preserved; `returned_count`/`total_count`/`note` on truncated `list_orders` | [P5-E evidence](../phase5/PHASE_5_E_EVIDENCE_2026-10-17.md) (`test_p5e_ai4_*`, `test_postgres.py`) | **REMEDIATED / RE-REVIEW** | Independent Codex review on candidate SHA |
| P5-E-AI5 | Timeout (`504`), provider `429`, quota (`429`), and `503` truthfulness | Structured error codes; zero false completion or business mutation | [P5-E evidence](../phase5/PHASE_5_E_EVIDENCE_2026-10-17.md) (`test_p5e_ai5_*`, `test_postgres.py`) | **REMEDIATED / RE-REVIEW** | Independent Codex review on candidate SHA |
| P5-E-AI6 | Bounded, deterministic, zero-paid-call adversarial manifest | Frozen SHA-256 manifest, `max_api_calls=0`, `max_attempts_per_case=1` | [P5-E evidence](../phase5/PHASE_5_E_EVIDENCE_2026-10-17.md) (`test_p5e_ai6_*`) | **REMEDIATED / RE-REVIEW** | Independent Codex review on candidate SHA |
| P5-E-ADM1 | Admin RBAC & tenant authorization boundary | `401` unauthenticated; `403` customer/viewer/staff & cross-tenant manager; `platform_admin` explicit tenant | [P5-E evidence](../phase5/PHASE_5_E_EVIDENCE_2026-10-17.md) (`test_p5e_adm1_and_adm2_*`, `test_postgres.py`) | **REMEDIATED / RE-REVIEW** | Independent Codex review on candidate SHA |
| P5-E-ADM2 | Scoped account list/detail view without secret exposure | No token/hash/cookie/secret in payload; includes `quota` & `next_reset_utc` | [P5-E evidence](../phase5/PHASE_5_E_EVIDENCE_2026-10-17.md) (`test_p5e_adm1_and_adm2_*`, `test_postgres.py`) | **REMEDIATED / RE-REVIEW** | Independent Codex review on candidate SHA |
| P5-E-ADM3 | Account suspend, reactivate, session revocation, self-lockout guard | Immediate `401` across session/conversations/chat; `auth_version` bump; `400 self_lockout_forbidden` | [P5-E evidence](../phase5/PHASE_5_E_EVIDENCE_2026-10-17.md) (`test_p5e_adm3_*`, `test_postgres.py`) | **REMEDIATED / RE-REVIEW** | Independent Codex review on candidate SHA |
| P5-E-ADM4 | Per-membership quota inspection & bounded override | `1..10000` validation; override persistence across restart; expiry fallback to `default_limit` | [P5-E evidence](../phase5/PHASE_5_E_EVIDENCE_2026-10-17.md) (`test_p5e_adm4_*`, `test_postgres.py`) | **REMEDIATED / RE-REVIEW** | Independent Codex review on candidate SHA |
| P5-E-ADM5 | Append-only `admin_audit_log` & transactional rollback | `405` on POST audit-log; allowed/denied correlation; rollback on audit failure | [P5-E evidence](../phase5/PHASE_5_E_EVIDENCE_2026-10-17.md) (`test_p5e_adm5_*`, `test_postgres.py`) | **REMEDIATED / RE-REVIEW** | Independent Codex review on candidate SHA |
| P5-E-ADM6 | Control-plane isolation & CSRF origin protection | Cross-origin POST rejected (`403 invalid_origin`); Ops Console v1 remains read-only | [P5-E evidence](../phase5/PHASE_5_E_EVIDENCE_2026-10-17.md) (`test_p5e_adm6_*`, `test_postgres.py`) | **REMEDIATED / RE-REVIEW** | Independent Codex review on candidate SHA |
| P5-E-DATA1 | Synthetic demo sample order display label (`display_name`) | `display_name: "Bộ xếp hình gỗ cho bé"` on synthetic `P-602` sample order; canonical DB `name` unchanged | [P5-E evidence](../phase5/PHASE_5_E_EVIDENCE_2026-10-17.md) (`test_p5e_data1_*`, `test_postgres.py`) | **REMEDIATED / RE-REVIEW** | Independent Codex review on candidate SHA |
| P5-E-DATA2 | Incomplete catalog (`P-604`) alias & variant stock fallback safety | Natural-language alias lookup for `P-604`; `stock=None` -> `None`, `stock=0` -> `0` (never `5`) | [P5-E evidence](../phase5/PHASE_5_E_EVIDENCE_2026-10-17.md) (`test_p5e_data2_*`, `test_postgres.py`) | **REMEDIATED / RE-REVIEW** | Independent Codex review on candidate SHA |

> **Gate boundary:** P5-E PASS does **not** automatically close `G4` or authorize `G5`/`G6`/`G7` performance benchmarking.

## 4. Review and deployment decision

CI PR được đọc qua GitHub check-run metadata đúng PR HEAD. Job offline có DSN PostgreSQL và chạy full `unittest discover`; raw per-test log chưa được đọc độc lập. `git diff --check` của working tree và remediation range `39be636..3ff5d0e` PASS; full PR range còn whitespace từ commit trước, ghi [backlog P5-11](../phase4/PHASE_5_BACKLOG.md#p5-11--p5-c-pr-whitespace), không mở gate mới. Deploy run `38335308481`, deploy job `115122302562`, SUCCESS lúc 2026-10-13 11:06 (+07) trên merged `a34b479`. Owner post-deploy snapshot `2026-10-13T04:36:57Z` confirms web/admin both run `deployed.env` digest `sha256:2c058277…`, all four expected services healthy/running, and Caddy has the admin network/mount. Owner-pasted excerpts from both reports show `pass=true`, identical activated/web image, healthy PostgreSQL-backed public endpoint, successful session/order/logout assertions, unique synthetic tenants and revoked credentials. P5-K1 therefore PASS; raw JSON files themselves remain on EC2 and are not archived in this review.

| Decision | Điều kiện bắt buộc | Hiện tại |
|---|---|---|
| Merge P5-C | P5-K4–K6 được reviewer độc lập ký trên cùng candidate SHA; CI bắt buộc xanh | **PASS — merged `a34b479`** |
| Deploy workflow P5-C | Merged SHA; deploy job hoàn tất thành công | **PASS — run `38335308481`, job `115122302562`, SHA `a34b479`** |
| EC2 runtime reconciliation | Image/release khớp SHA; expected web/admin/DB/Caddy topology và health | **PASS — post-run snapshot matches configured/runtime digest and expected topology** |
| Post-deploy smoke evidence / P5-K1 | Smoke dùng image kỳ vọng; report ghi identity tuple, không đụng reservation | **PASS — both owner-pasted report excerpts meet the fixed assertions; raw JSON remains on EC2** |
| P5-D offline candidate acceptance | D-R1 pgvector retrieval; D-R2 lifecycle/checksum/reopen-confirm replay; D-R3 notebook source sync | **PENDING same-candidate CI: D-R2/D-R3 review PASS; D-R1 integration test SKIPPED locally** |
| READY FOR MEASUREMENT | G5 PASS, không chỉ smoke/CI/mock | HOLD |

P5-C merge/sign-off, runtime health/topology, và P5-K1 đều PASS. P5-D working-tree patch: 16 tests ran, 15 PASS and 1 pgvector integration SKIPPED; D-R2/D-R3 passed current source review and D-R1 has substantive test assertions, but real DB execution and same-candidate CI remain pending. Do not start EC2/live. P5-K3 live OAuth remains a separate prerequisite for any future live complaint acceptance.

## 5. EC2 power plan

| Công việc | Cần bật EC2? | Lý do | Có thể để EC2 tắt? |
|---|---:|---|---:|
| Sửa code P5-C, review, unit tests, docs và contract checks | Không | Chạy trên máy local hoặc GitHub Actions | Có |
| CI PostgreSQL và full suite của PR | Không | CI tạo PostgreSQL service riêng | Có |
| Owner review, merge PR và cập nhật backlog | Không | Thao tác GitHub/docs | Có |
| Deploy P5-C sau merge và chạy migration PostgreSQL hiện hữu | Có | Cần web, Caddy và PostgreSQL runtime trên EC2 | Không trong cửa sổ deploy |
| P5-K1/P5-K2 và G4 controlled smoke | Có | Cần HTTPS endpoint, image và DB thật | Không trong cửa sổ smoke |
| P5-K3 Google OAuth thật | Có | Cần callback HTTPS trỏ tới runtime đang chạy | Có nếu chỉ dùng offline identity tests |
| P5-D complaint E2E / P5-K7–K8 | Có | Cần session, order và workflow trên deployed runtime | Không trong cửa sổ E2E |
| G5/G6/G7 live measurement | Có, cùng Colab/vLLM hoặc provider đã duyệt | Cần lane runtime, model, DB/KB và evidence live | Có cho tới khi có approval |

**Quy tắc tiết kiệm:** giữ EC2 tắt trong toàn bộ giai đoạn P5-C re-review và CI. Chỉ bật ngay trước deploy/smoke/E2E; sau khi lưu raw report thì tắt lại. Mỗi lần stop/start có thể đổi public IP, vì vậy trước HTTPS smoke phải đồng bộ lại hostname/origin và cấp lại Caddy certificate theo [runbook](../04_OPERATIONS/RUNBOOK.md). EC2 bật không đồng nghĩa được phép chạy paid/full measurement; G5/G6 vẫn cần gate riêng.

## 6. Các ma trận không phải SSOT cấp dự án

| Tài liệu | Vai trò | Cách dùng |
|---|---|---|
| [PHASE_4_TEST_MATRIX.md](../phase4/PHASE_4_TEST_MATRIX.md) | Frozen 250-case dataset/test contract | Dùng cho K6/protocol, không tạo gate mới |
| [BUSINESS_TEST_SCENARIOS.md](../BUSINESS_TEST_SCENARIOS.md) | Business/SOP coverage | Dùng để chọn test, không thay acceptance |
| Các bảng AC trong plan Module 2.5/RBAC | Local design or historical snapshots | Chỉ tham khảo khi row hiện hành trỏ tới chúng |

## 7. Anti-loop rule

Review kết thúc khi row bắt buộc đạt PASS hoặc được owner đánh dấu DEFERRED/BACKLOG. Không tiếp tục săn lỗi vô hạn, không thêm K9/P5-K9 trong cùng lượt, và không coi một finding ngoài scope là lý do mở lại gate đã đóng.
