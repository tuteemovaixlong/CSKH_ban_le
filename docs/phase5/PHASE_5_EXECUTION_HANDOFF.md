# Phase 5 Execution Handoff — Identity, Sales Simulator, Complaint E2E

## Prompt Gemini

```text
P5-A đã merge dd0947a; operational smoke PASS theo log owner. Chỉ làm P5-B: cấu hình tenant demo rõ ràng cho Google login, bind issuer/sub/verified email → principal/customer, kiểm session/profile và isolation bằng tests offline. Không chọn tenant smoke theo thứ tự tên; không dùng email đơn độc để gán đơn hàng. Tạo PR, cập nhật docs rồi dừng để owner review. Chưa làm simulator/complaint, deploy, chạy model hoặc measurement; không mở lại K1–K8.
```

## Baseline và trạng thái

- G2 baseline SHA: `8868c5c498b1c64241bc791eb0166d82415cfeb0`.
- Current merged/deployed SHA: `dd0947aad3a2dc8884710c8f6c609f42b67417bd`.
- P5-A/G4 report: `/opt/retailops/e2e-reports/LIVE_SMOKE_20261010T042118Z.json` — PASS.
- Reservation cũ `e2e-live-smoke/C-001` được giữ nguyên; smoke dùng tenant synthetic mới.
- Existing Phase 4 gate remains authoritative; Phase 5 cannot rewrite K1–K8.

Nguồn smoke PASS là log owner gửi ngày 2026-10-10; chưa đọc trực tiếp JSON trên EC2. `--mode smoke` kiểm login/session/orders/logout, không gọi model hoặc Google OAuth. Đây là operational smoke PASS, chưa chứng minh G4 per-lane model/DB/KB hay G5.

## Execution order

1. Read Phase 5 plan and acceptance; verify G2 offline replay on merged SHA `8868c5c498b1c64241bc791eb0166d82415cfeb0` (CI/contracts, frozen hashes, mock250 263 attempts with quality185/237, git diff --check) and save evidence. If G2 is not PASS, stop.
2. P5-A smoke isolation and G4 controlled smoke: DONE/PASS trên `dd0947a`.
3. Implement P5-B identity mapping using a dedicated Google test account: DONE/PASS (offline tests 12/12, evidence: [PHASE_5_B_EVIDENCE.md](PHASE_5_B_EVIDENCE.md)).
4. Implement P5-C simulator/import boundary with signed fixtures and replay/idempotency tests. — NEXT
5. Implement P5-D complaint flow using the same session and audit assertions.
6. Run CI and contract checks; obtain owner review and explicit G3 smoke authorization.
7. After authorization, deploy only the reviewed commit and run one controlled G4 smoke with a fresh synthetic tenant; save raw report.
8. Complete P5-K1…P5-K8 and update status docs. Stop before G5 unless separately authorized.

## Required report

Record commit SHA, image digest, tenant/principal/customer identities (synthetic or redacted), Google issuer/sub hash, event IDs, mapping hash, order IDs, complaint text class, proposal/confirmation IDs, audit events, costs, failures and raw artifact paths. Never store OAuth secrets, access tokens or real customer PII.
