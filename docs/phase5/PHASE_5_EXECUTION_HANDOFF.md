# Phase 5 Execution Handoff — Identity, Sales Simulator, Complaint E2E

## Prompt Gemini

```text
Precondition: verify G2 offline replay on merged SHA 8868c5c498b1c64241bc791eb0166d82415cfeb0; if it is not PASS, stop. Then implement Phase 5 only from docs/phase5/PHASE_5_PLAN.md and PHASE_5_ACCEPTANCE_CRITERIA.md. First parameterize live-e2e smoke with a fresh synthetic tenant/customer/order; never delete or mutate the reserved old customer. Then add dedicated Google test identity mapping and an offline/dev sales simulator with signed, idempotent order events. Add one same-session complaint E2E: Google login → imported order → complaint → dispute proposal/handoff → explicit confirmation → audit/state checks. No real PII, frozen benchmark changes, direct DB shortcut, full measurement, or G5 claim. Add tests/docs. Do not deploy or run G3/G4 until the PR is reviewed and owner authorizes it; then run one controlled G4 smoke, report P5-K1..P5-K8, and stop.
```

## Baseline và trạng thái

- Merged SHA: `8868c5c498b1c64241bc791eb0166d82415cfeb0`.
- Previous G4 report: `/opt/retailops/e2e-reports/LIVE_SMOKE_20261009T132840Z.json`.
- G4 failure: `customer_reserved` for `e2e-live-smoke/C-001`.
- Existing Phase 4 gate remains authoritative; Phase 5 cannot rewrite K1–K8.

## Execution order

1. Read Phase 5 plan and acceptance; verify G2 offline replay on merged SHA `8868c5c498b1c64241bc791eb0166d82415cfeb0` (CI/contracts, frozen hashes, mock250 263 attempts with quality185/237, git diff --check) and save evidence. If G2 is not PASS, stop.
2. Implement P5-A smoke isolation and tests; run offline tests.
3. Implement P5-B identity mapping using a dedicated Google test account; keep live credentials outside Git.
4. Implement P5-C simulator/import boundary with signed fixtures and replay/idempotency tests.
5. Implement P5-D complaint flow using the same session and audit assertions.
6. Run CI and contract checks; obtain owner review and explicit G3 smoke authorization.
7. After authorization, deploy only the reviewed commit and run one controlled G4 smoke with a fresh synthetic tenant; save raw report.
8. Complete P5-K1…P5-K8 and update status docs. Stop before G5 unless separately authorized.

## Required report

Record commit SHA, image digest, tenant/principal/customer identities (synthetic or redacted), Google issuer/sub hash, event IDs, mapping hash, order IDs, complaint text class, proposal/confirmation IDs, audit events, costs, failures and raw artifact paths. Never store OAuth secrets, access tokens or real customer PII.

