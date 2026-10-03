# Review GPT 6 Astra — PR A/N08 P1.1 hậu kiểm

**Ngày:** 03/10/2026
**Phạm vi:** Bản sửa của Claude Opus 5.5 High tại `reconcile_collision()`, code SHA `766a594`; đối chiếu thêm trạng thái branch/plan tại HEAD `4f77578`. Không sửa code, không commit/push/merge/deploy.

## Prompt cô đọng cho Gemini

> Sửa blocker P1.1 còn lại: sau khi Business commit nhưng trước Step 3, test interleaving cho phép raw membership takeover; coordinator trả 409 nhưng session đã tồn tại của membership bị đổi vẫn resolve sang customer đích và đọc được đơn vừa chuyển. Thêm fail-closed cho cả session mới lẫn session cũ khi membership.customer_id còn trong unresolved_collisions (hoặc cơ chế tương đương bảo đảm không còn phiên hợp lệ); kiểm thử SQLite + PostgreSQL: tạo session trước, takeover sau Business commit, xác nhận resolve/API đọc đơn bị từ chối, journal/collision giữ đúng và retry an toàn. Giữ phạm vi hẹp, chạy suite/gates/CI trên SHA cuối, cập nhật status/plan và báo số test, skip, SHA, run ID. Chưa merge/deploy/PR B.

## Kết luận

**Chưa sẵn sàng nghiệm thu/merge PR A và chưa nên bắt đầu PR B.** Bản sửa đóng được race trước Business commit đối với các writer tuân thủ reservation/lock, nhưng có một đường rò dữ liệu đã tái hiện được ở nhánh takeover sau Business commit.

## Phát hiện chặn — session cũ vượt qua trạng thái unresolved

Trong `tests/reconcile_interleaving_cases.py`, hook thứ ba mô phỏng membership takeover sau khi Business DB đã commit và trước Step 3. Test hiện có xác nhận journal ở `business_committed`, collision/reservation còn tồn tại và reconciliation trả `409 target_customer_conflict`; nhưng fixture không có session hoạt động trước đó cho membership bị takeover.

Tôi bổ sung phép thử chạy tạm, không ghi file: tạo session hợp lệ trước reconciliation cho `m-ilv-intruder`, chạy đúng takeover hook ở Step 3, rồi gọi `IdentityStore.resolve()` bằng session cũ. Kết quả: reconciliation trả `409 target_customer_conflict`, nhưng session vẫn resolve thành `CG-ilv-alice`; Business DB đã có đơn `O-ILV-A` dưới customer đó. Nguyên nhân là `IdentityStore.resolve()` chỉ kiểm tra session expiry, `auth_version`, membership/tenant active; không kiểm tra membership.customer_id trong `unresolved_collisions`. Raw update không tăng `auth_version`, nên session cũ còn hiệu lực. Đường `GET /api/orders` lấy customer từ session rồi gọi `app.store.orders(customer)` (`retailops/http/routes.py`), nên dữ liệu được truy vấn theo ID customer đã bị takeover.

Đây là blocker trong chính kịch bản late takeover mà implementation/test tuyên bố xử lý fail-closed. Các API tạo membership mới đã tôn trọng reservation; điều còn thiếu là chặn phiên đã phát hành. Khi thêm guard ở session resolution, cần xác nhận cả SQLite và PostgreSQL, và chấp nhận rằng account liên quan bị khóa tạm thời trong lúc reconciliation chưa hoàn tất.

## Phần đã sửa và đã đối chiếu

- P1.1: thêm kiểm tra ownership Identity/Business, reservation trong `unresolved_collisions`, kiểm tra lại dưới lock trước Business commit và trước Step 3; Business guard có `customers` và `conversation_feedback`.
- Các writer membership/customer_link ở luồng tạo membership và Google login kiểm tra reservation; SQLite dùng transaction ghi tuần tự, PostgreSQL dùng advisory lock và table lock trong reconciliation.
- Test mới bao phủ bốn takeover: membership, customer_link, Business `customers`, `conversation_feedback`; có test liên backend.
- P1.2: báo cáo hiện tại ghi migration SQLite legacy nối được coordinator và E2E PostgreSQL/SQLite.
- Những điểm trên giải quyết lỗi static target collision và TOCTOU trước Business commit; chúng không phủ nhận lỗi session cũ ở late-takeover case nêu trên.

## Kết quả kiểm chứng độc lập

- `python -B -X utf8 -m unittest discover -s tests -p "test_*.py"`: **479 test, OK, 50 SKIP, 0 FAIL/ERROR**. Skip thuộc các PostgreSQL/pgvector integration test do máy cục bộ không cấu hình `RETAILOPS_TEST_DATABASE_URL`; CI live PostgreSQL được báo cáo riêng.
- Docs contract, deployment contract, eval dataset và notebook sync: **4/4 PASS** sau khi đồng bộ các tài liệu trong lượt này.
- Hai benchmark sau chuẩn hóa EOL đều giữ SHA-256 `36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411`.
- Local branch: `feature/module-2.5-pr-a`, HEAD `fe25f67` (code SHA đóng P1.1 session-safety).
- CI run `37137791788` trên code SHA `fe25f67`: host `479/479 PASS, 0 SKIP`; container `478 PASS / 1 SKIP`; PostgreSQL 16 và Caddy container live thật, 5/5 marker HTTPS OK.
- Regression hai backend: Session cũ fail-closed 503 `collision_unresolved` sau late takeover, `GET /api/orders` không trả dữ liệu, retry hoàn tất an toàn.

## Quyết định và bước tiếp theo

1. **P1.1 và P1.2 ĐÃ ĐÓNG HOÀN TOÀN** trên cả SQLite lẫn PostgreSQL.
2. CI Run `37137791788` xác nhận code SHA `fe25f67` xanh 100%.
3. Không còn blocker P0/P1; dừng vòng review N08, sẵn sàng nghiệm thu PR A.
4. Tuân thủ cam kết: **chưa merge vào main, chưa deploy lên EC2, chưa bắt đầu PR B**.
