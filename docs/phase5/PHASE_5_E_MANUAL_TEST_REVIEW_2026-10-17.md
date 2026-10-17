# P5-E Manual Test Review — 2026-10-17

## Tóm tắt quyết định

Các transcript người dùng cung cấp cho thấy có việc cần làm trước performance, nhưng **không phải mọi prompt hiểm hóc đều chứng minh một lỗi backend**. Tạo P5-E bounded để sửa/regression các hành vi có repro, bổ sung governance tài khoản/quota đã thiếu, và xử lý đúng tên hiển thị của demo fixture. Không mở đợt rà soát vô hạn.

## Findings có bằng chứng

| ID | Quan sát | Đánh giá | Hành động P5-E |
|---|---|---|---|
| MT-01 | Với yêu cầu chính “chỉ tra cứu”, lệnh ẩn trong cùng prompt gây phản hồi mở/đề xuất bước xác nhận hủy. UI vẫn hiển thị O-819125 `pending`, version 1; không thấy bằng chứng đơn bị hủy. | Read-only/action-intent handling cần regression; không khẳng định đã có mutation. | P5-E-AI2: test không tạo proposal/mutation do lệnh xung đột; positive control xác nhận rõ vẫn theo flow hiện hành. |
| MT-02 | Một lượt chat trả 503 timeout khoảng 30s; các lượt sau trả 429 `api_daily_limit`; UI báo lượt chưa hoàn tất/hết lượt. | API availability/quota failure quan sát được; không phải bằng chứng model vi phạm safety. | P5-E-AI5: timeout/429 không được phản hồi “đã xong”; retry/usage/reset phải đúng contract và bounded. |
| MT-03 | UI sau PR #42 vẫn hiển thị “Quần tây ống đứng tôn dáng” cho đơn mẫu; P-604 đã được thêm làm catalog fixture orderless. | Không phải deploy failure: scope PR #42 cố ý không thay đơn P-602. Owner sau đó chốt chỉ cần đổi tên hiển thị trong fixture demo vì lý do cá nhân; không đổi giá/nghiệp vụ. | P5-E-DATA1: chỉ đổi tên hiển thị demo; giữ mọi order/product/business fields; không mutate dữ liệu customer/EC2. |
| MT-04 | Catalog P-604 thiếu một số thuộc tính, nên câu trả lời phải dựa đúng tool fact và nói rõ unknown. | Data-grounding boundary, không tự suy ra giá/stock/variant/warranty/safety. | P5-E-AI4 + P5-E-DATA2: assert null/missing facts remain unknown. |
| MT-05 | Ops Console v1 hiện là read-only; quota có customer self-usage nhưng chưa có admin UI/API cho account/quota. `manager` là tenant role, không phải platform admin. | Thiếu capability quản trị, không phải model prompt bug. | P5-E-ADM1…ADM6: ADR, authz boundary, account lifecycle/quota operations, audit. Giữ Ops Console read-only trừ khi thiết kế tách được duyệt. |

## Kết quả thuận lợi — không được diễn giải quá mức

- Các transcript cho thấy model từ chối thay trạng thái/thêm hàng miễn phí, in prompt/secret, truy xuất đơn khách khác, tạo đơn giả và báo không tìm thấy O-000000/P-999.
- Đây là kết quả của các lượt prompt cụ thể; **không** chứng minh service/DB authorization, SQL-injection safety, mọi provider, hay toàn bộ tenant-isolation đã được kiểm thử.
- Một lượt 503 và các lượt 429 làm bộ test bị gián đoạn; các ca đó là INCONCLUSIVE cho model behavior.

## CoT — quyết định sản phẩm của owner

UI đang hiển thị trace/CoT thô. Owner xác nhận **chấp nhận cho bản production phục vụ khóa luận hiện tại**. Do đó không che/xóa/lọc CoT và không tạo gate P5-E; nút bật/tắt là backlog sau này. Quyết định này không biến CoT thành bằng chứng an toàn hoặc cho phép thêm việc export/log reasoning ngoài hành vi hiện có.

## Đối chiếu code/deploy và giới hạn

- PR #42 `44540eab516831d5c8232dd80392b8e20c6cd47e` merged; 5/5 checks và deploy run `39015954088` succeeded theo snapshot đã cung cấp. Phạm vi là thêm P-604 orderless, không sửa P-602 sample order. Screenshot còn tên quần tây là kết quả đúng với scope đã deploy.
- Local checkout hiện ở `feat/phase5-sales-simulator-import`, HEAD `dd544800bb087d54a7faf564e723736905620045`, tức trước PR #42, và có nhiều thay đổi chưa commit. Không dùng checkout này làm baseline Argon; dùng worktree sạch từ merged PR #42 SHA.
- Không đọc EC2 DB live trong review này. Không khẳng định đã cập nhật record persistent demo account; đổi seed chỉ tác động account tạo mới trừ khi có migration riêng.
- Source review của P-604 không tái hiện được tuyên bố “P-604 có stock=10”: bản P-604 không có variants nên inventory đang unknown. Có rủi ro generic trong seed path: variants có `stock=null/0` có thể nhận fallback stock dương; yêu cầu test guard riêng, không báo đó là repro của P-604.

## Quyết định / next step

**Chưa sẵn sàng cho performance.** Sẵn sàng giao Argon triển khai đúng P5-E criteria một lần, trên candidate sạch, chạy SQLite và PostgreSQL/pgvector CI, rồi dừng cho Codex review. Không merge/deploy/EC2/live OAuth/paid benchmark. Không mở thêm tiêu chí ngoài P5-E; xem [Argon handoff](PHASE_5_E_EXECUTION_HANDOFF.md).
