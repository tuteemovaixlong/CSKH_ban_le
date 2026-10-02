# Review GPT 6 Astra — N08 rollback và CI

Ngày review: **2026-10-02**
Branch: `feature/module-2.5-pr-a` · HEAD local/GitHub: `b9389f58c6ae8c271da29ffb3121f3455def8de8`
Phạm vi: kiểm tra rollback N08, test report và bằng chứng CI; không audit toàn hệ thống.

## Prompt ngắn cho Gemini

> Rà soát N08 rollback: chỉ đặt `active=0` cho membership hiện có trong `unresolved_collisions` chưa chặn baseline v1 tạo membership customer mới bằng ID `CG-{sha256(email)[:8]}` trùng collision. Không tuyên bố rollback về baseline v1 an toàn. Ưu tiên chỉ rollback về image còn collision guard; nếu vẫn hỗ trợ baseline, phải giữ đăng nhập/provisioning khách hàng ở maintenance fail-closed và thêm test PostgreSQL trên disposable DB cho rollback rồi thử tạo Google member collision bằng đúng baseline. Bổ sung quy trình reconciliation/reactivation sau roll-forward. Sửa số liệu: checkout này có 31 test trong `test_postgres.py`, không phải 45. Xác minh run 37035980381 đúng HEAD và ghi URL, SHA, jobs, test/skip counts; nếu không xác minh được, ghi rõ. Không merge/deploy.

## Kết luận

**Chưa READY để merge hoặc production.** Forward migration v1/v2→v3 có test PostgreSQL được khai báo; tuy nhiên rollback về binary baseline v1 vẫn có đường tạo customer membership mới trùng ID collision. Gemini báo CI success, nhưng run đó chưa được xác minh độc lập.

## Phát hiện

### P1 — Rollback guard chỉ khóa membership collision đã biết

Tôi đọc trực tiếp baseline commit `c6c7a1a` qua GitHub connector. `IdentityStore.get_or_create_google_member()` tạo ID khách theo `CG-{hash_suffix[:8]}` và insert membership mới ở trạng thái active mà không kiểm tra `unresolved_collisions`. SQL rollback hiện chỉ đặt `active=0` cho membership customer đã có trong danh sách collision. Một tài khoản Google mới có cùng ID băm rút gọn vẫn có thể được tạo active dưới baseline, nên cách này không bảo đảm fail-closed.

**Khuyến nghị:** không rollback về baseline thiếu guard; chỉ dùng image có collision guard tương thích. Nếu buộc phải dùng baseline, khóa đăng nhập/provisioning khách hàng trong maintenance cho tới khi có kiểm soát độc lập và test chứng minh đường tạo mới bị chặn.

### P2 — Thiếu bước mở khóa sau roll-forward

Rollback đặt `active=0` và tăng `auth_version`; roll-forward không tự khôi phục những membership đó. Runbook cần nêu cách đối soát danh tính, xử lý đơn mơ hồ và kích hoạt lại có audit sau khi collision được giải quyết. Không bật lại hàng loạt chỉ vì migration đã chạy.

### P2 — Test count và CI evidence

Kiểm tra tại checkout này:

| Kiểm tra | Kết quả |
| --- | --- |
| Full suite `python -B -X utf8 -m unittest discover -s tests` | **467 tổng: 422 PASS, 45 SKIP, 0 FAIL/ERROR** |
| `tests/test_postgres.py` | **31 SKIP** vì thiếu `RETAILOPS_TEST_DATABASE_URL` |
| Notebook `--check` | **PASS** |
| Docs contract | **PASS 4/4** |

Claim “45 integration tests trong `test_postgres.py`” không khớp checkout này: discovery thấy 31 test trong file đó.

Sau khi repo được chuyển public, GitHub connector đã đọc được branch `feature/module-2.5-pr-a` tại đúng HEAD `b9389f5` và nội dung baseline nói trên. Khi repo ở private, các thao tác đọc trước đó trả 404; lần đọc lúc public không chứng minh connector có quyền trên repo private.

Run Actions `37035980381` vẫn chưa được xác minh độc lập: connector hiện có không cung cấp thao tác đọc workflow run, còn gọi API công khai trực tiếp bị chặn bởi sandbox. Claim **467 PASS, 0 SKIP trên PostgreSQL** vẫn là báo cáo Gemini, chưa phải bằng chứng tôi đã đọc CI.

Test migration v1→v3 và v2→v3 không thay thế test rollback v3→baseline rồi thử tạo tài khoản mới cùng collision ID.

## Độ ổn định và bước tiếp theo

Đường nâng cấp v1/v2→v3 có version và test riêng nên tương đối rõ. Rollback về v1 chưa an toàn; cần chốt policy rollback, bổ sung test đường tạo collision sau rollback và quy trình reconciliation trước khi merge. Sau đó xác nhận CI của đúng HEAD và cập nhật trạng thái dự án.

**Trạng thái:** sẵn sàng cho vòng sửa và kiểm chứng tiếp theo trên feature branch; **chưa sẵn sàng merge/deploy**.

## Lịch sử cô đọng

Review trước phát hiện version rebind thuần túy làm mất collision guard. Gemini bổ sung khóa các membership collision đã biết; lần kiểm tra này phát hiện baseline vẫn có thể tạo membership mới trùng ID. Repo public cho phép đọc branch và source qua connector; khả năng đọc khi private vẫn chưa được xác nhận.
