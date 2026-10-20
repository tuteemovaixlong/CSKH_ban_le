# Phase 5 Fix A — Execution Handoff

## Trigger prompt for Gemini Argon — copy/paste the full block

```text
Đọc và làm đúng toàn bộ packet Phase 5 Fix A:
- docs/phase5_fix_A/README.md
- docs/phase5_fix_A/PHASE_5_FIX_A_REVIEW_2026-10-20.md
- docs/phase5_fix_A/PHASE_5_FIX_A_ACCEPTANCE_CRITERIA.md
- docs/phase5_fix_A/PHASE_5_FIX_A_EVIDENCE.md
- docs/phase5_fix_A/PHASE_5_FIX_A_EXECUTION_HANDOFF.md
và các tài liệu liên quan được link ở đó, đặc biệt P5-DM I/O/retention, PostgreSQL backup và current project status.

Thực hiện một lượt đầy đủ đúng phạm vi Phase 5 Fix A, không mở rộng bug hunt:

1) FIX MANAGER NAVIGATION. Reproduce và kiểm tra source/asset SHA thực sự đang được phục vụ. Khi manager mở Store Manager, đưa về “Tổng quan & KPIs”; khi đang ở Hàng hóa/danh mục, luôn có đường điều hướng hiển thị được để quay về tổng quan, kể cả trong panel cuộn/viewport nhỏ. Thêm regression interaction/browser test cho open → products/category → return to overview → close/reopen. Ảnh cho thấy tab thiếu ở một trạng thái nhưng root cause chưa được xác nhận; không ghi là đã sửa đúng root cause nếu chưa tái hiện.

2) FIX DEMO DATA SOURCE, GIỮ P-602. Chủ dự án đã sửa master product P-602 thành “Quần tây đen hàn quốc” qua giao diện manager; screenshot ngày 2026-10-20 cho thấy giá 520.000 VND, tồn 40, variants Đen/Size S–L, warranty 90 ngày. GIỮ catalog row P-602 và các thuộc tính hiện hành; không xóa/đổi P-602, P-603, customer, account, sessions, O-819125/O-819127 hay bất kỳ bản ghi không thuộc target. Sửa mọi active demo seed/import path để snapshot cũ “Quần tây ống đứng tôn dáng” không được sinh lại; phân biệt runtime producer với tests, evaluation và historical docs.

3) SAFE TARGETED ORDER PURGE. Chỉ target demo order theo tuple kỳ vọng: O-819126, customer CG-d9b82ffe, product P-602, delivered, amount 520000 VND, order snapshot name “Quần tây ống đứng tôn dáng”. Order ID này có thể được sinh động; tenant ID chưa biết và chưa được xác minh. Trước mutation, dùng read-only inventory xác định đúng tenant/schema và xác nhận có đúng một row khớp toàn bộ tuple. Nếu không có hoặc có nhiều kết quả, tenant/fields khác, references không phân loại được, hoặc backup chưa valid: STOP, không xóa, không đoán tenant/record khác.

Không thêm generic manager hard-delete API. Nếu cần command one-shot, yêu cầu dry-run mặc định, tenant và tuple bắt buộc, exact-match guard, idempotent transaction, pre/post counts, operator audit và restore-tested backup. Xóa đúng order khỏi active business tables/UI và các disposable direct dependents đã phân loại; giữ append-only business/security audit và history theo retention contract. Thiết kế purge tombstone/replay guard để login seed/import/replay không tái tạo đúng demo order. Không xóa audit/import/idempotency history mù; báo rõ record lịch sử nào còn giữ và vì sao. Đơn phải biến mất khỏi customer/manager list, search, detail và KPI được tính lại; P-602 catalog vẫn còn.

4) TEST + CI. Làm trên clean isolated worktree/candidate dựa trên latest main đã có PR #43 merge SHA ef40d131ef9244fa51844ae8990a05888990cdc8; KHÔNG sửa, reset, stash, hoặc đưa các thay đổi bẩn chưa commit từ workspace feat/phase5-sales-simulator-import vào candidate. Thêm regression UI, seed/reseed/replay, exact purge guard, no-collateral changes, retention/tombstone, SQLite và PostgreSQL/pgvector. Chạy targeted tests, toàn CI bắt buộc, docs contract, browser/UI checks nếu có; ghi test counts và skips đúng log. Sửa đồng bộ docs phase packet, acceptance matrix, current status, phase5 README và roadmap.

5) PR / MERGE / DEPLOY / EC2 CLEANUP. Tạo candidate PR, không bypass branch protection. Chờ toàn bộ required CI/review PASS; sau đó merge theo quy trình repo (owner đã yêu cầu merge/deploy). Xác nhận official deploy workflow chạy trên merged SHA, ghi image digest/source-match/rollout và kiểm UI runtime. Chỉ sau đó chạy read-only EC2 inventory → verified backup (theo runbook PostgreSQL/SQLite) → dry-run exact tuple → execute tenant-scoped one-time purge. Dùng AWS/SSM chỉ nếu credential/role và đúng instance đã được xác minh; không sửa config/secrets, không dùng lệnh DELETE toàn cục, không purge ngoài tenant/tuple đã xác nhận. Nếu không có quyền/kênh SSM hoặc không thể kiểm chứng backup/tenant, dừng ở code+deploy và để FIXA-DEPLOY2 PENDING; đưa lệnh Session Manager cụ thể, an toàn, để chủ dự án chạy; tuyệt đối không giả nhận đã xóa.

6) DỪNG. Không chạy OAuth live, benchmark/performance, paid tests; không sửa P5-E 14 criteria hoặc P5-DM 17 criteria. Không báo PASS cho Phase 5/P5-E/G4/G5 nhờ FIX-A. Cập nhật evidence file và báo: review/finding disposition; base/candidate/merge SHA; PR và CI workflow/job IDs; test counts/skips; files changed; deploy run/digest; backup/dry-run/DB result và exact affected row counts; criteria từng mục; phần nào còn pending/blocker. Không mở Round mới ngoài scope này.
```

## Điều phối và trạng thái

- Trạng thái hiện tại: **CONSUMED FOR CODE/TEST/CI/DEPLOY — LIVE EC2 DATA CLEANUP (`FIXA-DEPLOY2`) PENDING OPERATOR SSM EXECUTION**.
- [Review](PHASE_5_FIX_A_REVIEW_2026-10-20.md) ghi nhận các kết luận từ rà soát read-only và phân biệt rõ phần đã xác minh trong source với phần unreproduced trên runtime; [criteria](PHASE_5_FIX_A_ACCEPTANCE_CRITERIA.md) là nguồn PASS/FAIL; bằng chứng chi tiết và lệnh SSM an toàn cho bước cleanup trên EC2 nằm tại [evidence](PHASE_5_FIX_A_EVIDENCE.md).
- Phase này tách biệt khỏi P5-DM handoff hiện hành; không được coi là quyền thực hiện toàn bộ P5-DM.
- Workspace bẩn gốc (`feat/phase5-sales-simulator-import`) được giữ nguyên hoàn toàn không chạm tới; candidate sạch được thực hiện trên worktree cô lập từ merged `main` (`ef40d131ef9244fa51844ae8990a05888990cdc8`).
- Xem thêm [acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md), [current status](../CURRENT_PROJECT_STATUS.md), [roadmap](../PLAN_ROADMAP_INDEX.md), [phase5 index](../phase5/README.md) và [root docs index](../README.md).
