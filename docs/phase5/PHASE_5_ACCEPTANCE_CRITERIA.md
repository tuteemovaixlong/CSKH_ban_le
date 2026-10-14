# Phase 5 Acceptance Criteria — Dev Identity and Sales-to-Complaint Lane

Phase 5 chỉ đạt khi toàn bộ tiêu chí dưới đây có evidence trên cùng commit của workstream. Đây là acceptance cho dev/synthetic lane, không phải G5/G6 approval.

**Điều kiện trước khi nghiệm thu:** G2 offline replay trên merged SHA phải PASS và có evidence gồm CI/contracts, frozen hashes, mock250 (263 attempts; quality185/237) và `git diff --check`. Thiếu G2 evidence thì Phase 5 dừng, không tính P5-K1…P5-K8.

| ID | Tiêu chí | PASS evidence |
|---|---|---|
| P5-K1 | Smoke isolation | Smoke không dùng tenant/customer bị reservation; không sửa/xóa dữ liệu cũ; report ghi identity tuple. |
| P5-K2 | Runtime health | Image đúng merged/deployed SHA; web/admin/PostgreSQL healthy; health contract PASS. |
| P5-K3 | Google identity | Dedicated test account OAuth PASS; state/nonce, issuer, verified email và `sub` được kiểm; session trả đúng tenant/principal/customer/role. |
| P5-K4 | External mapping | Mapping `external_customer_id → RetailOps customer_id` có tenant scope, audit và không dùng email đơn độc làm khóa. |
| P5-K5 | Event contract | Event schema, signature, timestamp, tenant binding và idempotency PASS; replay cùng event không tạo duplicate. |
| P5-K6 | Order visibility | Event import tạo/ cập nhật đúng order; customer chỉ đọc được order của mình; truy cập customer khác bị từ chối. |
| P5-K7 | Complaint workflow | Cùng Google customer session gửi complaint; dispute worker đọc đúng order/policy, tạo proposal/handoff và không mutation trước confirmation. |
| P5-K8 | Confirmation and audit | Confirmation idempotent; trạng thái/audit/event khớp; raw report và checksums được lưu. |

## Tiến độ theo chặng

- **P5-K1 (Smoke isolation): PASS** — owner-pasted selected fields from both P5-C reports show `pass=true`, exact `activated_image == web_image == deployed.env` digest `sha256:2c058277…`, all runtime/session/order/logout checks true, and `credentials_revoked=true`. Identity tuples: (`e2e-smoke-20261013040523-10330f`, `e2e-smoke-4293e63828`, `C-001`, `O-101`) and (`e2e-smoke-20261013040556-122853`, `e2e-smoke-c4666bfbfe`, `C-001`, `O-101`). Both use fresh distinct tenants, not reserved tenant `e2e-live-smoke`; tenants are retained for audit. Raw JSON remains on EC2; reviewed fields were pasted by owner.
- **P5-K2 (Runtime health): PASS** — deploy run `38335308481`, job `115122302562`, SUCCESS at 2026-10-13 11:06 (+07) on merged `a34b479`. Owner snapshot `2026-10-13T04:36:57Z` shows web/admin both healthy and running the exact digest in `deployed.env` (`sha256:2c05827775460a5c56c41855dcd1a216e9c529e89a75614e553e91e00b922c1e`), PostgreSQL healthy, and Caddy running on public + admin networks with `/etc/caddy/admin` mounted. Deploy script binds the image tag/pinned digest to `GITHUB_SHA` and invokes smoke with `--expected-image`. The separate un-timestamped `64d15c4…` inventory is superseded by this post-run snapshot. OCI revision labels and raw workflow log were not separately archived.
- **P5-K3 (Google identity):** Offline implementation PASS trên PR P5-B (xem [PHASE_5_B_EVIDENCE.md](PHASE_5_B_EVIDENCE.md)); Google OAuth thật live PENDING (chờ môi trường live/owner review).
- **P5-K4 (External mapping):** **PASS offline/merged trên `a34b479`** — nội dung đã được independent sign-off trước merge; prior business import là nguồn sự thật tối thượng, cấm mapping tách cùng external ID; DDL/migration PostgreSQL có; mapping tự phục hồi sau lỗi identity. Deploy runtime hiện khớp release; complaint E2E thuộc P5-D, chưa nghiệm thu.
- **P5-K5 (Event contract):** **PASS offline/merged trên `a34b479`** — 45 targeted tests và CI required checks PASS; đúng 11 trường, strict integer, cấm NaN/Infinity, từ chối event collision 409, exact replay bypass drift-check sau 300s để heal mapping. Deploy runtime hiện khớp release; complaint E2E thuộc P5-D, chưa nghiệm thu.
- **P5-K6 (Order visibility):** **PASS offline/merged trên `a34b479`** — CI required checks và independent sign-off PASS trước merge; `order_id` đã có không thể đổi chủ (409 `order_owner_conflict`), customer isolation được xác minh. Deploy runtime hiện khớp release; complaint E2E thuộc P5-D, chưa nghiệm thu.
- **P5-K7 (Complaint workflow): implementation/test present; PostgreSQL evidence PENDING.** `test_07_tenant_policy_rag_isolation` verifies complaint tool wiring, tenant-schema selection, citation/source and marker isolation with a mocked repository. A separate disposable PostgreSQL/pgvector test has real repository/chat-path assertions, but it was **SKIPPED locally** because `RETAILOPS_TEST_DATABASE_URL` is not configured. Do not mark K7 PASS until that integration test passes without skip on the immutable candidate CI run.
- **P5-K8 (Confirmation and audit): local offline test PASS; same-candidate acceptance PENDING.** `test_15_integrated_lifecycle_raw_report_and_tamper_verification` binds persisted proposal fields to the complaint `action_proposal`, confirms and replays the same persisted proposal after reopening, checks one business mutation, and writes a real-time report plus SHA-256 manifest with round-trip and tamper-negative assertions. The local test passes; the same-workstream-commit rule still requires candidate CI/evidence.
- **P5-D regression D-R3: PASS** — `python scripts/build_agent_notebook.py --check` and `TestAuditRemediation.test_colab_agent_notebook_sync` both PASS on the current working tree.

Current source review, logs and provenance: [P5-D review](REVIEW_GEMINI_P5_D_2026-10-13.md), [current Codex recheck set](evidence/P5_D_REVIEW_20261013_CURRENT/). D-R2 offline review and D-R3 are PASS; D-R1 has substantive PostgreSQL/pgvector assertions but the local run was skipped. The patch remains uncommitted with no immutable candidate SHA/CI. Keep P5-K7/K8 acceptance pending until candidate CI runs the PostgreSQL test and evidence is refreshed on that same candidate; no owner merge review, live operation or deploy yet.

## Điều kiện dừng

FAIL bất kỳ P5-K1…P5-K8 thì dừng tại tiêu chí đó. Không chạy full benchmark, không ghi `READY FOR MEASUREMENT`, không dùng dữ liệu thật và không bypass guard để làm PASS.
