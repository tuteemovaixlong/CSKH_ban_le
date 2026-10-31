# Phase R1 — W1 Remediation Handoff (Gemini 4 Argon)

> **Trạng thái:** prompt thực thi do owner phát hành ngày 2026-10-31, nằm **trong** ủy quyền W1-only đã có ([readiness addendum](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-10-31-w0-closeout--w1-only-authorization-addendum)). Handoff này **không** phải readiness review, **không** đổi verdict `BLOCKED` sang `READY` và **không** mở `W2–W6`.
> **Nguồn finding:** [W1 finding register](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-10-31-w1-implementation-readiness-review--codex) và [docs review addendum](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-10-31-w1-docs-review-addendum).
> **Nguyên tắc phạm vi:** chỉ xử lý đúng 5 BLOCKER trong register. Không mở hạng mục mới, không refactor, không “bới thêm” finding. Mọi thứ không nằm trong mục 2 đều ngoài phạm vi.

## 1. Mục tiêu làm việc

- Worktree: worktree W1 hiện tại; branch `docs/phase-r1-w0-owner-decisions`; `HEAD` `bbfd11d0ba4c13514a197a6b25802c4e217bedb3`, kèm các thay đổi chưa commit.
- Bảo toàn mọi thay đổi sẵn có của owner/Codex/Argon. Không commit, push, merge, reset, stash, checkout hay rebase.
- Không chạy migration trên DB thật; không truy cập EC2/SSM, Colab/ngrok/LLM hay dữ liệu khách hàng; không deploy.

## 2. Phạm vi: 5 BLOCKER và tiêu chí chấp nhận

| ID | Việc phải làm | Tiêu chí chấp nhận (test cô lập) |
|---|---|---|
| `W1-RB-01` | Với **cả Staff và Manager**: `GET /api/staff/conversations/{id}/messages` (và alias `/api/conversations/{id}/messages` khi gọi bằng quyền Staff), `POST /api/staff/reply` và `POST /api/staff/resolve` chỉ được thực hiện khi conversation thuộc store của tenant trong session **và** đang có một handoff episode chưa resolved (`conversation_feedback.feedback_type='human_handoff'` với `reason_code != 'resolved'`). Đây là biểu diễn handoff episode hiện có cho tới khi W2 có durable case. Không có handoff đang mở thì từ chối (403/409), không ghi gì. `resolve` không được trả `resolved: true` khi không có handoff đang mở. | Có test cho: conversation không có handoff; handoff đã resolved; conversation không tồn tại; conversation tenant khác; có handoff ở conversation A nhưng gọi trên conversation B. Mỗi trường hợp đều bị từ chối và không có message/event nào được ghi. Có handoff hợp lệ thì vẫn hoạt động như hiện nay. |
| `W1-RB-02` | `/api/tools/execute`: áp guard `case_not_escalated` cho **cả Manager**, giống Staff. Role Manager hoặc việc biết conversation ID không đủ để cấp quyền. | Sửa assertion hiện có trong `tests/test_r1_w1_identity_rbac.py` (Manager trên conversation chưa escalate) thành kỳ vọng 403 `case_not_escalated`. Manager trên conversation có handoff đang mở vẫn được phép. |
| `W1-MIG-01` | Theo runbook đã chấp nhận ở [§11.5](W0_OWNER_DECISION_DELTA_2026-10-29.md#115-migration-runbook-od-07): khởi động bình thường (`retailops/bootstrap.py`) và các lệnh CLI `identity` thông thường **không** được chạy data step của identity v5 (xóa session, vô hiệu hóa `viewer`/`platform_admin`, đổi role constraint) trên dữ liệu đã có. Chỉ một lệnh operator riêng, chạy tường minh, mới thực thi upgrade; lệnh đó phải yêu cầu tham số xác nhận đã có preflight và backup. Nếu store hiện có chưa ở identity v5 thì startup phải fail-closed với thông báo rõ ràng, không tự migrate. Tạo một DB **mới, rỗng** vẫn được tạo thẳng schema v5. | Test trên fixture v4 cục bộ (SQLite và mock PostgreSQL) có membership legacy và session: khởi tạo store/startup/CLI thường thì không đổi dữ liệu nào và startup từ chối; lệnh migrate tường minh thì migrate đúng và idempotent. Test migration cô lập hiện có vẫn PASS. |
| `W1-ID-01` | Chỉ thêm guard fail-closed, **không** chọn chính sách provisioning: `DEFAULT_ROLE` khác `customer` phải bị từ chối (deny-by-default cho quyền đặc quyền chưa được owner duyệt). Giữ nguyên hành vi allowlist hiện có cho email đã xác minh; không mở rộng, không gỡ. | Test: `DEFAULT_ROLE=staff` hoặc `manager` → bị từ chối; `customer` hoặc để trống → hoạt động như hiện nay; email chưa xác minh không bao giờ nhận role đặc quyền. |
| `W1-ID-02` | Chỉ thêm guard dựa trên quyết định đã có (retire `platform_admin`/`viewer`, cấm reactivation, không alias sang `manager`): `set_role` phải từ chối membership có role legacy hoặc có `disabled_reason='retired_legacy_role_r1_w1'`, và không được xóa marker đó. Đường `admin_reactivate_account` vẫn từ chối role legacy như hiện nay. | Test: `set-role` trên membership legacy đã retire → bị từ chối, dữ liệu không đổi; sau đó Manager reactivate vẫn bị từ chối. `set-role` trên membership hợp lệ vẫn hoạt động như hiện nay (bump `auth_version`, thu hồi session, ghi audit). |

## 3. Ranh giới chờ owner (không tự quyết)

Hai câu hỏi sau vẫn là của owner. Argon **không** được tự chốt và **không** được viết code giả định câu trả lời:

1. Nguồn có thẩm quyền cấp membership/role cho tài khoản mới: import/provisioning từ hệ thống ngoài, allowlist chuyển tiếp hay chỉ membership đã provision (`W1-ID-01`).
2. Kênh có thẩm quyền đổi role cho membership hiện hữu, và cách định danh operator khi dùng CLI (`W1-ID-02`).

Guard ở mục 2 đóng phần rủi ro kỹ thuật. Tuy vậy W1 **chưa được báo cáo là hoàn tất** cho tới khi owner ghi nhận quyết định cho hai câu hỏi này.

## 4. Ngoài phạm vi

- `W2–W6`, bảng durable `cases`/`handoff_episodes`, business v5, timer, UI và notebook Colab.
- `W1-AUD-01` (ghi chú không chặn), sanitizer của `/api/events`, phạm vi danh sách `/api/staff/escalations`.
- Test hiệu năng Waitress, notebook stale, refactor hay dọn dẹp không cần thiết cho 5 mục trên.
- Sửa bất kỳ tài liệu nào trong `docs/phase_role_aware_ops/`, ngoại trừ cột Argon của W1 log.

Nếu việc sửa một mục buộc phải chạm vào phần ngoài phạm vi, hoặc buộc phải chọn chính sách: **dừng lại và hỏi owner**.

## 5. Kiểm tra và báo cáo

Chạy:

- `python -m unittest tests.test_r1_w1_identity_rbac -v`
- Các suite liên quan đã chạy ở W1: `test_persistent_identity`, `test_phase5_google_identity`, `test_auth_google`, `test_staff_desk`, `test_manager_crud`, `test_schema_migration`, `test_postgres`, `test_release_source_consistency`.
- `python scripts/check_docs_contract.py`
- `git diff --check -- retailops/ tests/`

Báo cáo ngắn: danh sách file đã đổi; kết quả từng lệnh, ghi đúng số test pass/fail/skip; trạng thái từng mục trong mục 2 (DONE hoặc BLOCKED kèm lý do); và xác nhận hai câu hỏi ở mục 3 vẫn đang chờ owner. Thêm **một dòng mới** vào cột Argon của [W1 log](W1_EXECUTION_LOG_2026-10-31.md); không sửa dòng cũ và không ghi vào cột Codex.

## 6. Sau khi Argon báo cáo

Chỉ chạy **một** lượt kiểm chứng: đối chiếu 5 tiêu chí chấp nhận ở mục 2 với diff và kết quả test. Không mở finding mới ngoài phạm vi, trừ khi chính thay đổi này tạo ra lỗ hổng mức BLOCKER. Kết quả kiểm chứng được ghi vào [readiness register](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md); verdict chỉ được đổi khi owner đồng ý.
