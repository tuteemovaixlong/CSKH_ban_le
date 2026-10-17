# Phase 5-E Execution Handoff — Argon One-Pass Implementation

**Trạng thái:** Owner đã yêu cầu Argon thực hiện implementation bounded theo acceptance này. Candidate/review/CI được phép; merge, deploy và live mutation chưa được phép.
**Nguồn chuẩn:** [P5-E plan](PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md), [P5-E criteria](PHASE_5_E_ACCEPTANCE_CRITERIA.md), [manual-test review](PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md), [acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md).
**Baseline:** PR #42 merged `44540eab516831d5c8232dd80392b8e20c6cd47e`; deploy workflow `39015954088` succeeded. This does not prove current EC2 state or implement the requested demo display-name change.

## Mục tiêu

Thực hiện P5-E-AI1…AI6, P5-E-ADM1…ADM6 và P5-E-DATA1…DATA2 thành **một candidate có cùng SHA**, evidence rõ ràng và review độc lập. Đây là task implementation; không biến thành audit toàn repo hoặc săn thêm bug vô hạn. CoT thô được owner chấp nhận trong bản khóa luận hiện tại; **không ẩn, xóa, lọc hoặc đổi cách render CoT**. Toggle CoT là backlog, không phải acceptance gate.

## Baseline và an toàn workspace

1. Bắt đầu từ một worktree/branch sạch dựa chính xác trên merged PR #42 SHA `44540eab516831d5c8232dd80392b8e20c6cd47e`. Nếu commit chưa có local hoặc remote refs không xác minh được, dừng và báo; không sửa/reset workspace bẩn hiện tại.
2. Ghi `git status`, HEAD/base SHA và diff ban đầu. Giữ nguyên mọi thay đổi đã có; không stash, reset, checkout-overwrite, merge hay cherry-pick vào workspace chính.
3. Đọc plan, criteria, manual-test review, `SYSTEM_REVIEW_FOR_LLM.md`/LLM-09, `ADMIN_CONSOLE.md`, account usage, identity/permission/routes, business tool/order/catalog/inventory code và tests tương ứng. Chỉ mở thêm file theo dependency trực tiếp.
4. Trước code, ghi ngắn ADR cho platform-admin vs tenant-manager/customer, authn/authz, cross-tenant scope, quota limit/expiry/reset, audit fields/session revoke và control-plane boundary. Nếu cần policy chưa được owner quyết định, chọn deny-safe behavior hoặc hỏi owner; không tự cấp quyền global.

## Phạm vi implementation bắt buộc

### A. AI trust — chỉ các repro trong criteria

- Đóng read-only/action-confirmation repro; validate quyền tại server/tool boundary, không dựa vào lời từ chối của model.
- Giữ regression set hữu hạn cho prompt injection/exfiltration, SQL-like/Unicode IDs, ownership, missing facts, false success và timeout/429. Không gọi API key thật, không dùng secret thật làm canary.
- Timeout/503/provider 429/quota 429 phải không tạo xác nhận hoàn tất hoặc business mutation giả; retry bounded, usage accounting khớp policy.
- Không mở rộng sang các phát hiện không tái hiện hoặc không nằm trong criteria; ghi backlog nếu có finding độc lập.

### B. Account/quota governance — control plane tách biệt

- Implement role-scoped account status, session revoke và per-membership quota view/change theo ADR; tenant manager không tự có platform-admin quyền.
- Ghi audit append-only có actor/role, tenant/target, before/after, reason, timestamp và correlation ID; không ghi secret hoặc chat body không cần thiết.
- Không thêm write route/DB credential vào Ops Console v1 read-only nếu ADR không chứng minh boundary an toàn; không gắn Docker socket.

### C. Demo display label và inventory truth — owner đã chốt “chỉ đổi tên”

- Truy nguyên fixture hiển thị món “Quần tây ống đứng tôn dáng”. Chỉ đổi **tên hiển thị của đúng sample/demo fixture** thành “Bộ xếp hình gỗ cho bé”, đúng nơi người dùng nhìn thấy.
- Giữ nguyên các order/business fields, order ID, product ID, amount, variant, status, catalog facts và mọi non-demo/customer data. Không chuyển P-602 thành P-604, không giả giá/stock/warranty/safety data, không chạy migration hay chỉnh EC2 DB.
- Đảm bảo tên hiển thị demo-only không trở thành tool evidence khiến model nói sai sự thật về product ID/catalog. Nếu UI và order-detail/model lookup không thể tách display label an toàn, **dừng riêng phần đó**, báo chính xác mismatch và đề xuất lựa chọn; không đổi dữ liệu nghiệp vụ lén lút.
- Test seeded/new demo fixture và UI/API path để chứng minh label đúng chỗ và mọi order field khác giữ nguyên. Ghi rõ seed chỉ tác động user mới; nó không tự thay record đã tồn tại trên EC2.
- Test P-604 missing/null product facts. Không ghi nhận lỗi “P-604 đang hiện tồn kho 10” như đã tái hiện: source audit thấy P-604 hiện không có variants nên inventory trả unknown. Tuy vậy, thêm guard regression cho generic variant seed `stock=null` hoặc `0` để không bịa stock dương; xác minh explicit-stock control vẫn đúng.

## Kiểm thử / evidence cần nộp

- Chạy test mục tiêu trước; sau đó CI offline cần thiết, SQLite và PostgreSQL/pgvector paths thật, không skip required test. Bao gồm quyền cross-tenant, quota concurrency/UTC reset/expiry, audit/revoke, read-only/action intent, missing facts, P-604 unknown stock, generic null-stock variants, demo label snapshot, persistence/reseed/restart.
- `P5-E-AI1…AI6`, `P5-E-ADM1…ADM6`, `P5-E-DATA1…DATA2` phải có verdict từng dòng trên cùng candidate SHA. `INCONCLUSIVE`, skipped, live chưa chạy hoặc lỗi provider không được ghi thành PASS.
- Cập nhật evidence/review/handoff và docs trạng thái/matrix chỉ theo kết quả thực; ghi lệnh, exit code, count/skips, DB/backend, SHA, CI links, diff file list, limitations và owner decisions.
- Nếu cần GitHub CI, dùng branch/candidate riêng. Có thể tạo PR chỉ để lấy CI/review; **không merge**.

## Cấm trong handoff này

- Không merge, deploy, chạy AWS/SSM/EC2, OAuth live, sửa production DB/config, mutate đơn khách, rotate credential hoặc thay đổi quota thật.
- Không chạy performance/full benchmark/paid provider campaign. Offline deterministic mock/CI được phép; live model test chỉ khi owner duyệt riêng cost/quota cap và stop rule.
- Không sửa Phase 4 frozen benchmark, không mở lại P5-K1…K8, không thay semantics G4–G7.
- Không thêm cross-encoder/reranker; không có retrieval/ranking repro trong transcript. Đưa ra backlog riêng nếu evidence có qrels sau này cho thấy cần.
- Không sửa/hide CoT hoặc biến CoT toggle thành blocker.
- Không tự thêm acceptance criteria giữa chừng. Finding ngoài danh sách ghi vào backlog riêng và dừng.

## Điểm dừng và phản hồi

Kết thúc sau candidate + CI + evidence + self-review; không tự merge/deploy. Trả báo cáo ngắn theo từng AC ID (PASS/FAIL/INCONCLUSIVE/NOT RUN), cùng candidate SHA/base, PostgreSQL skip count, CI, changed-file list, security/role decisions và blockers. P5-E chỉ được đề nghị chuyển sang Codex re-review khi tất cả acceptance pass trên cùng SHA. Nếu một mục không thể làm an toàn hoặc dữ liệu đầu vào/authority thiếu, giữ nguyên trạng thái và hỏi owner thay vì đoán.
