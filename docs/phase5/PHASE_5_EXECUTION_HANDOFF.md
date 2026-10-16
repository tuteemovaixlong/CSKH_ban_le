# Phase 5 Execution Handoff — Identity, Sales Simulator, Complaint E2E

> **Current status (2026-10-13):** PR #39 đã merge vào `main` tại `a34b479eeb633ba55090f43a1f4ed7d85f6a3c9a`; 45 targeted tests, CI và independent sign-off PASS. Deploy run `38335308481` rerun, job `115122302562` SUCCESS lúc 11:06 (+07). Owner snapshot `2026-10-13T04:36:57Z` confirms web/admin running `deployed.env` digest `sha256:2c058277…`, web/admin/PostgreSQL healthy, and Caddy's expected public/admin networks and `/etc/caddy/admin` mount. Owner-pasted excerpts from both smoke reports show P5-K1 PASS. **P5-D implementation re-review: D-R2/D-R3 PASS; D-R1 has real PostgreSQL/pgvector assertions but the local test was skipped. K7/K8 acceptance remains pending immutable same-workstream candidate CI.**

## Handoff hiện tại — candidate CI verification

Trigger Gemini, current verdict, context chain và candidate-verification steps nằm tại [PHASE_5_D_EXECUTION_HANDOFF.md](PHASE_5_D_EXECUTION_HANDOFF.md). Không reimplement: cần immutable candidate SHA và CI phải chạy pgvector integration không skip; sau đó dừng để Codex kiểm tra evidence. Chưa chuyển sang OAuth/live.

P5-D offline closure hiện HOLD. Không yêu cầu re-review/redeploy P5-C: runtime image/health/topology và P5-K1 đã xác nhận. P5-K3 live OAuth chỉ là dependency của một bước live ở tương lai, không phải việc cần làm trong lượt sửa này. Không chạy EC2, OAuth, model/paid hay live E2E.

## Baseline và trạng thái

- G2 baseline SHA: `8868c5c498b1c64241bc791eb0166d82415cfeb0`.
- Current merged SHA: `a34b479eeb633ba55090f43a1f4ed7d85f6a3c9a`; deploy job `115122302562` succeeded. Owner snapshot `2026-10-13T04:36:57Z` reconciles runtime digest `sha256:2c058277…`, health and admin topology.
- Latest P5-C/G4 operational smoke reports: `/opt/retailops/e2e-reports/LIVE_SMOKE_20261013T040523Z.json` and `LIVE_SMOKE_20261013T040555Z.json` — both PASS (owner-pasted selected fields; raw files remain on EC2).
- Reservation cũ `e2e-live-smoke/C-001` được giữ nguyên; smoke dùng tenant synthetic mới.
- Existing Phase 4 gate remains authoritative; Phase 5 cannot rewrite K1–K8.

Hai latest smoke reports được xác nhận qua các trường owner paste ngày 2026-10-13; `--mode smoke` kiểm image/health/login/session/orders/logout, không gọi model hoặc Google OAuth. Đây là operational smoke PASS, chưa chứng minh G4 per-lane model/DB/KB hay G5.

## Execution order

1. **G2 prerequisite: DONE** — offline replay PASS on `8868c5c498b1c64241bc791eb0166d82415cfeb0`; evidence is [PHASE_5_G2_EVIDENCE_8868c5c.md](PHASE_5_G2_EVIDENCE_8868c5c.md). Do not rerun unless the relevant source/contract changes.
2. P5-A implementation passed on `dd0947a`; latest controlled operational smoke evidence is from deployed SHA `80f51569b3bef5ae0793bac1593fb91e39558477`, report `/opt/retailops/e2e-reports/LIVE_SMOKE_20261011T074654Z.json` (not an AI-lane/model G4 result).
3. Implement P5-B identity mapping using a dedicated Google test account: DONE/MERGED/DEPLOYED; offline tests 12/12 PASS (evidence: [PHASE_5_B_EVIDENCE.md](PHASE_5_B_EVIDENCE.md)).
4. Implement P5-C simulator/import boundary: IMPLEMENTED and MERGED at `a34b479`; K4–K6 independently signed off on source candidate `3ff5d0e`; offline acceptance PASS.
5. **Runtime reconciliation:** PASS on owner snapshot `2026-10-13T04:36:57Z`: runtime web/admin image equals `deployed.env` digest `sha256:2c058277…`; web/admin/PostgreSQL healthy; Caddy public/admin networks and admin mount present. Deploy job succeeded on merged `a34b479`.
6. **P5-K1:** PASS from owner-pasted excerpts of both reports: matching expected/runtime digest, all smoke assertions true, distinct synthetic tenant tuples, credentials revoked; raw JSON retained on EC2.
7. **P5-D implementation re-review:** D-R2 lifecycle/test and D-R3 notebook sync PASS; D-R1 has non-vacuous PostgreSQL/pgvector assertions, but local run skipped without DSN. P5-K7/K8 acceptance remains pending immutable candidate CI on the same workstream commit, with pgvector test executed without skip. See [current review](REVIEW_GEMINI_P5_D_2026-10-13.md), [current logs](evidence/P5_D_REVIEW_20261013_CURRENT/), and [P5-D evidence](PHASE_5_D_EVIDENCE.md).
8. Dừng sau candidate CI evidence để Codex kiểm tra; không merge/deploy/bật EC2 hoặc OAuth/live. P5-K3 và owner authorization vẫn prerequisite riêng cho live complaint.

## Required report

Record commit SHA, image digest, tenant/principal/customer identities (synthetic or redacted), Google issuer/sub hash, event IDs, mapping hash, order IDs, complaint text class, proposal/confirmation IDs, audit events, costs, failures and raw artifact paths. Never store OAuth secrets, access tokens or real customer PII.
