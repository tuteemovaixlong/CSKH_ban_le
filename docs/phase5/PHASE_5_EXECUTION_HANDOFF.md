# Phase 5 Execution Handoff — Identity, Sales Simulator, Complaint E2E

## Prompt Gemini — P5-C trigger

```text
Đọc PHASE_5_PLAN.md và PHASE_5_ACCEPTANCE_CRITERIA.md. Chỉ triển khai P5-C offline/dev: sales simulator + service-boundary import adapter với canonical event fields source_system/event_id/tenant/external_customer_id/order_id/status/items/total/currency/timestamp/signature; HMAC, timestamp/schema/tenant checks, tenant-scoped mapping, audit và idempotency/replay. Không dùng email/buyer_identifier làm khóa; simulator không ghi thẳng DB. Thêm signed fixtures, rollback/duplicate tests và cache invalidation sau commit. Không làm P5-D, Google live OAuth, deploy, model/paid measurement hay mở lại K1-K8. Cập nhật evidence/docs, tạo PR và dừng chờ review.
```

## Baseline và trạng thái

- G2 baseline SHA: `8868c5c498b1c64241bc791eb0166d82415cfeb0`.
- Current merged/deployed SHA: `80f51569b3bef5ae0793bac1593fb91e39558477`.
- P5-A/G4 report: `/opt/retailops/e2e-reports/LIVE_SMOKE_20261011T074654Z.json` — PASS.
- Reservation cũ `e2e-live-smoke/C-001` được giữ nguyên; smoke dùng tenant synthetic mới.
- Existing Phase 4 gate remains authoritative; Phase 5 cannot rewrite K1–K8.

Nguồn smoke PASS là log owner gửi ngày 2026-10-11; chưa đọc trực tiếp JSON trên EC2. `--mode smoke` kiểm login/session/orders/logout, không gọi model hoặc Google OAuth. Đây là operational smoke PASS, chưa chứng minh G4 per-lane model/DB/KB hay G5.

## Execution order

1. Read Phase 5 plan and acceptance; verify G2 offline replay on merged SHA `8868c5c498b1c64241bc791eb0166d82415cfeb0` (CI/contracts, frozen hashes, mock250 263 attempts with quality185/237, git diff --check) and save evidence. If G2 is not PASS, stop.
2. P5-A smoke isolation and G4 controlled smoke: DONE/PASS trên `dd0947a`.
3. Implement P5-B identity mapping using a dedicated Google test account: DONE/MERGED/DEPLOYED; offline tests 12/12 PASS (evidence: [PHASE_5_B_EVIDENCE.md](PHASE_5_B_EVIDENCE.md)).
4. Implement P5-C simulator/import boundary with signed fixtures and replay/idempotency tests: DONE/PASS (offline tests 15/15, evidence: [PHASE_5_C_EVIDENCE.md](PHASE_5_C_EVIDENCE.md)).
5. Implement P5-D complaint flow using the same session and audit assertions. — NEXT
6. Run CI and contract checks; obtain owner review for P5-C/P5-D PR.
7. After P5-C/P5-D review and explicit authorization, deploy only the reviewed commit and run one controlled G4 smoke; save raw report.
8. Complete P5-K1…P5-K8 and update status docs. Stop before G5 unless separately authorized.

## Required report

Record commit SHA, image digest, tenant/principal/customer identities (synthetic or redacted), Google issuer/sub hash, event IDs, mapping hash, order IDs, complaint text class, proposal/confirmation IDs, audit events, costs, failures and raw artifact paths. Never store OAuth secrets, access tokens or real customer PII.
