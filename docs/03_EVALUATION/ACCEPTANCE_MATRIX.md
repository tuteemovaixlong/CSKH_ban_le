# RetailOps Acceptance Matrix

> **Mục đích:** bảng điều phối nghiệm thu cấp dự án. File này không thay thế acceptance criteria của từng phase; nó chỉ trỏ tới nguồn chuẩn, evidence, gate và bước kế tiếp.
>
> **Cập nhật:** 2026-10-18 (P5-E independent review; các mốc live/deploy giữ nguyên phạm vi cũ)
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

## 3A. P5-E candidate reviewed — CHANGES REQUIRED (2026-10-18)

Nguồn chuẩn: [P5-E plan](../phase5/PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md), [acceptance criteria](../phase5/PHASE_5_E_ACCEPTANCE_CRITERIA.md), [manual-test review](../phase5/PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md), [Argon handoff](../phase5/PHASE_5_E_EXECUTION_HANDOFF.md), [independent review đủ 14 AC](../phase5/REVIEW_ARGON_P5_E_2026-10-18.md). Candidate `7b94f9cd9bfb214fed86831e99cbbd1f69ca2dfb` / [PR #43](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/43): [CI 39048991412](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39048991412) và [Ops 39048991359](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39048991359) SUCCESS, 5/5 checks; raw per-test count chưa được reviewer đọc độc lập.

| P5-E area | Required acceptance | Current disposition | Gate / next action |
|---|---|---|---|
| AI trust / action intent | AI1–AI6 giữ nguyên criteria | **CHANGES REQUIRED** — R1 final-copy leak; AI6 hash chưa frozen; required backend/output regressions R5 còn thiếu. Local suite 13/13 PASS chưa đủ acceptance; CoT vẫn được chấp nhận | R1/R5/R6 trên PR #43 hiện có |
| Account & quota governance | ADM1–ADM6 giữ nguyên criteria | **CHANGES REQUIRED / PARTIAL API** — R2 SQLite upgrade lỗi; R4 chưa có account/quota UI; override concurrency/UTC/expiry evidence R5 thiếu. Ops Console vẫn read-only | R2/R4/R5/R6; không EC2/live admin mutation |
| Demo label / inventory truth | DATA1–DATA2 giữ nguyên criteria | **DATA1 FAIL / DATA2 source-test supported** — label áp dụng cả non-fixture order (R3); null/zero/unknown guards đã có. Không thay facts/order/catalog/EC2 data | R3/R5/R6; preserve DATA2 controls |
| P5-E overall | All 14 criteria on same candidate SHA; exact backend/run and tested-ref mapping, no required skips | **CHANGES REQUIRED / NOT ACCEPTED** — CI xanh, review chưa PASS | Sửa hữu hạn R1–R6 → candidate/CI/evidence → independent re-review; chưa merge/deploy/performance |

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
