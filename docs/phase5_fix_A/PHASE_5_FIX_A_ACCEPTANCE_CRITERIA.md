# Phase 5 Fix A — Acceptance Criteria

**Status:** IN PROGRESS / CODE & REGRESSION DELIVERED (`FIXA-UI1..UI3`, `FIXA-DATA1..DATA4`, `FIXA-DOC1` PASS offline; `FIXA-CI1..CI2`, `FIXA-UI4`, `FIXA-DEPLOY1` tracked through PR CI & merge deploy; `FIXA-DATA5` / `FIXA-DEPLOY2` live EC2 execution PENDING operator SSM session). Đây là phase riêng cho hai vấn đề manager UI và order demo; không sửa 14 tiêu chí P5-E hoặc 17 tiêu chí P5-DM. Review: [PHASE_5_FIX_A_REVIEW_2026-10-20.md](PHASE_5_FIX_A_REVIEW_2026-10-20.md). Evidence: [PHASE_5_FIX_A_EVIDENCE.md](PHASE_5_FIX_A_EVIDENCE.md).

## A. Manager home navigation

| ID | Điều kiện PASS | Bằng chứng bắt buộc |
|---|---|---|
| FIXA-UI1 | Manager console mở ở `Tổng quan & KPIs` một cách nhất quán; trạng thái tab cũ không làm chủ cửa hàng bị kẹt ở danh mục/sản phẩm sau khi mở lại. | Regression trên vai trò manager: mở → chọn Hàng hóa & Kho/danh mục → đóng/mở lại → KPI là panel active; ghi trạng thái trước/sau. |
| FIXA-UI2 | Từ mọi tab/danh mục có đường về tổng quan luôn nhìn thấy được, kể cả khi table/panel cuộn hoặc viewport nhỏ. | Browser/UI interaction test xác nhận nút/tab “Về tổng quan” luôn khả dụng; click đưa đúng KPI panel, không chỉ reload trang. |
| FIXA-UI3 | Điều hướng hỗ trợ keyboard/focus và trạng thái semantic tab/panel; các control khác (Đóng, Refresh, CRUD) không bị hỏng. | Automated UI test hoặc browser test + accessibility assertions phù hợp; smoke các nút manager hiện có. |
| FIXA-UI4 | UI/asset thực tế được xác minh là từ merged/deployed SHA, không phải cache hoặc runtime khác. | Ghi source/image digest/asset build identity; smoke manager sau deploy. Nếu không tái hiện production thì ghi đúng “unreproduced”, không khẳng định root cause đã xác minh. |

## B. Giữ catalog P-602, gỡ đúng order demo cũ

| ID | Điều kiện PASS | Bằng chứng bắt buộc |
|---|---|---|
| FIXA-DATA1 | Catalog P-602 được giữ nguyên theo trạng thái manager mới do chủ dự án cung cấp; không xóa sản phẩm, stock, variants, price, warranty hoặc các đơn khác. | Snapshot trước/sau cho P-602/P-603, O-819125/O-819127 và các order không mục tiêu. Expected P-602 display name là `Quần tây đen hàn quốc`; nếu runtime khác thì dừng, báo mismatch. |
| FIXA-DATA2 | Chỉ order demo đúng tuple `O-819126 + CG-d9b82ffe + P-602 + delivered + 520000 VND + old snapshot name` trong một tenant đã xác minh được gỡ khỏi active customer/manager order lists/detail/search. | Read-only tenant inventory và exact-match counts trước; sau purge truy vấn lại cùng tenant; UI list/search không còn đơn; các đơn khác và customer binding không đổi. Không dùng order ID toàn cục. |
| FIXA-DATA3 | P-602/order cũ không tự tái sinh khi login, reseed, replay/import hoặc refresh/restart ứng dụng. P-602 catalog vẫn tồn tại. | Regression fresh persistent demo seed và replay same source event; verify purge tombstone/idempotency guard chặn đúng order ID mà không ngăn đơn P-602 mới hợp lệ tạo ngoài fixture demo. |
| FIXA-DATA4 | Dependent references được kiểm kê và xử lý theo retention semantics; audit/security event append-only được giữ, unrelated conversation/event/order/customer không bị xóa. | Per-tenant before/after reference counts cho `order_items`, `proposals`, `business_events`, `conversations`, `imported_events` và purge audit/tombstone; referential/integrity checks trên SQLite và PostgreSQL/pgvector. Ghi rõ immutable history còn lưu gì. |
| FIXA-DATA5 | Production cleanup có backup/restore evidence, dry-run mặc định, exact-match fail-closed guard, transaction và idempotency. | Backup artifact metadata/hash và restore/list validation theo DB backend; dry-run report; transaction log/counts; second run không xóa thêm hoặc lỗi ngoài contract. Không lưu secret. |

## C. CI, deploy và docs

| ID | Điều kiện PASS | Bằng chứng bắt buộc |
|---|---|---|
| FIXA-CI1 | Targeted UI/data regressions và CI bắt buộc đều PASS trên cùng PR candidate; SQLite + PostgreSQL/pgvector được chạy thật, không tính skip là PASS. | SHA/head, workflow/job IDs, exact commands, test counts và skip counts từ log. |
| FIXA-CI2 | Candidate tách khỏi workspace bẩn hiện tại; required review/checks xanh trước merge; không force/bypass branch protections. | Base SHA, candidate SHA, PR link, checks. Merge chỉ sau khi các điều kiện này đạt. |
| FIXA-DEPLOY1 | Sau merge, standard deploy workflow xác nhận đúng image digest/source; manager UI smoke PASS. | Main merge SHA, deployment run/job, image digest, source-match/rollout markers, smoke report. |
| FIXA-DEPLOY2 | One-time EC2 data cleanup chỉ chạy sau deploy, backup validation và dry-run exact-match. Nếu tenant/tuple không khớp hoặc AWS/SSM không sẵn có thì **STOP**, báo PENDING; không giả nhận đã xóa. | Instance/host/time (không secrets), tenant schema redacted, exact-match count, backup/dry-run/transaction/post-check evidence. |
| FIXA-DOC1 | Review, criteria, handoff, evidence và project index links phản ánh cùng scope/status; phân biệt delivered work khỏi pending work. | `python scripts/check_docs_contract.py`, targeted `git diff --check`, link check PASS. |

## Stop rules / non-goals

- Nếu order tuple không khớp chính xác, có nhiều tenant match, backup chưa xác minh, restore check lỗi, dependent records không phân loại được, hoặc write race không được khóa: dừng trước production mutation và báo owner.
- Không xóa P-602 hoặc đổi thông tin catalog mới; không xóa order khách khác; không xóa audit/security history; không triển khai generic delete-everything API.
- Không sửa P5-E criteria hồi tố, không dùng phase này làm bằng chứng P5-E/P5-DM/G4/G5, không chạy OAuth live, benchmark/performance/paid tests.
