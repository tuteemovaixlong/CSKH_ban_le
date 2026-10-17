# Phase 5-E Plan — AI Trust & Account Operations Readiness

**Ngày lập:** 2026-10-17
**Trạng thái:** PLANNED — owner đã yêu cầu mở workstream; chưa có code change, chưa nghiệm thu.
**Vị trí:** Workstream sau P5-D/PR #42; bounded AI-lane G4 là evidence riêng và vẫn pending. P5-E phải PASS trước P5-F (G5 preflight) và mọi full/performance measurement. P5-K1…K8 và nghĩa của G4–G7 không bị sửa.

## Mục tiêu

Đóng các rủi ro AI/UX có bằng chứng từ test tay; đồng thời bổ sung control plane có phân quyền để operator cấp cao quản lý tài khoản khách và hạn mức API theo phạm vi được ủy quyền. Tích hợp thêm yêu cầu display-label-only: tên hiển thị demo được thay bằng tên đồ chơi trẻ em theo owner; không đổi dữ liệu nghiệp vụ/order/catalog và không sửa dữ liệu khách thật. Chỉ chuyển sang chuẩn bị G5 khi P5-E pass trên cùng candidate SHA và G4 có evidence riêng.

## Tóm tắt kết quả test tay ngày 2026-10-17

| Quan sát | Phân loại / kết luận |
|---|---|
| Giao diện hiển thị `Suy luận`/`Độc thoại suy luận (CoT)` khá dài. | Đã có trong LLM-09 của [SYSTEM_REVIEW_FOR_LLM.md](../SYSTEM_REVIEW_FOR_LLM.md). **Owner xác nhận chấp nhận việc hiển thị CoT trong bản production phục vụ khóa luận hiện tại**; không phải lỗi hoặc gate của P5-E. Nút bật/tắt là backlog tùy chọn cho giai đoạn sau. CoT vẫn không được xem như bằng chứng backend đã an toàn. |
| Yêu cầu có “chỉ tra cứu” nhưng sau chuỗi chỉ dẫn xung đột trợ lý mở/đề xuất bước xác nhận hủy. | **Finding hành vi cần regression có kiểm soát.** Transcript không chứng minh đơn đã đổi trạng thái; UI và danh sách vẫn cho thấy `pending`, phiên bản 1. |
| Một yêu cầu tổ hợp nhận HTTP 503 sau khoảng 30 giây; các lượt sau nhận 429 `api_daily_limit`. | **Sự cố khả dụng/hạn mức quan sát được**, không phải bằng chứng model vi phạm safety. Hết quota đã ngăn chạy hết bộ test. |
| Model từ chối đổi đơn/thêm hàng giá 0, tiết lộ prompt/API secret, liệt kê đơn khách khác và tạo đơn giả; O-000000/P-999 được báo không tìm thấy. | Kết quả thuận lợi của các lượt cụ thể; **không thay thế** test authorization ở service/DB và không chứng minh SQL injection đã được kiểm thử. |
| Sau PR #42, catalog có fixture P-604 nhưng UI vẫn liệt kê O-819126 với P-602 “Quần tây ống đứng tôn dáng”. | Đã đối chiếu: PR #42 chỉ thêm sản phẩm catalog orderless và giữ nguyên P-602/đơn mẫu. Việc vẫn thấy quần tây phù hợp scope đã merge; yêu cầu thay món hiển thị chưa được làm. Không giả định merge/deploy đã cập nhật record bền vững trong EC2. |

Không suy ra có SQL injection chỉ từ chuỗi ID độc hại trong prompt; chưa có bằng chứng câu SQL được thực thi. Cần kiểm tra validation/ownership tại ranh giới tool/API, bao gồm Unicode confusable, mà không dùng dữ liệu thật.

## Hiện trạng đã đối chiếu trong repo

- Có quota API hằng ngày theo membership, counter/reservation và endpoint khách xem usage của chính mình; giới hạn ứng dụng đang được cấu hình tập trung. Xem `retailops/account_usage.py`, `retailops/http/routes.py`, `retailops/config.py`.
- **Chưa có API/giao diện để quản trị hạn mức hoặc trạng thái tài khoản người khác.** CLI operator hỗ trợ một số thao tác bootstrap, không phải control plane self-service.
- `manager` là vai trò quản lý cửa hàng, không đồng nghĩa platform administrator. Ops Console v1 được thiết kế **read-only**, dùng operator credential qua Caddy; không được âm thầm biến service này thành API ghi dữ liệu. Xem [ADMIN_CONSOLE.md](../ADMIN_CONSOLE.md).
- LLM-09 đã chỉ ra provider reasoning có thể được lưu vào trace/conversation và render trong UI. Owner chấp nhận hành vi này trong bản hiện tại; P5-E không sửa/hide CoT. Có thể bổ sung tùy chọn bật/tắt như backlog, không block performance gate.
- Trong source checkout đang review, `persistent.py` còn seed ba đơn P-601/P-602/P-603; P-604 không được gắn vào đơn mẫu. Catalog P-604 chưa có thuộc tính thương mại đầy đủ. Owner làm rõ rằng yêu cầu hiện tại là **chỉ đổi tên hiển thị của fixture demo** vì lý do cá nhân; không cần đổi giá hay nghiệp vụ. Không đổi `product_id`, giá, trạng thái, biến thể hoặc dữ liệu catalog để giả P-602 thành P-604; không dùng nhãn UI mới làm evidence/tool result. Giữ rõ ranh giới giữa display label demo và dữ liệu sản phẩm/order thực.
- Tách **lỗi đã tái hiện** khỏi **guard regression**: audit source hiện tại cho thấy P-604 không có variants và `get_variant_stock` trả trạng thái unknown; chưa chứng minh P-604 hiện bị báo tồn kho dương. Tuy nhiên đường seed tổng quát có fallback tạo 5 đơn vị khi variant có nhưng stock null/0; bổ sung regression để không bịa tồn kho cho mọi sản phẩm thiếu dữ liệu. Không ghi nhận “P-604 false stock=10” như lỗi hiện hành nếu không có repro trên candidate merged.

## Phạm vi

### Track A — AI trust và hành vi khách hàng

1. Gắn quyền thực hiện vào authenticated principal, tenant/customer ownership, tool schema và server-side policy — không vào persona như “quản lý”, văn bản trích dẫn, prompt injection hay lời khẳng định của model.
2. Giữ đúng ý định read-only; không tạo mutation hoặc action proposal từ instruction ẩn/trích dẫn/xung đột khi người dùng chỉ yêu cầu tra cứu. Mutation chỉ qua flow xác nhận rõ, cùng chủ thể và phiên.
3. Ground câu trả lời vào kết quả tool; mã đơn/sản phẩm không tồn tại, giá/chiết khấu/đổi trả không có bằng chứng thì phải nói rõ chưa biết/không tìm thấy, không xác nhận đã ghi dữ liệu.
4. Giữ các ca prompt exfiltration, SQL-like ID, Unicode confusable và cross-customer lookup trong bộ regression hữu hạn. Xác minh backend không trả dữ liệu chéo tenant/chủ đơn; không coi lời từ chối của LLM là security boundary.
5. Với timeout/429, không tuyên bố tác vụ hoàn tất; thông báo chính xác thất bại/hạn mức và hướng dẫn thử lại/reset theo hợp đồng hiện hành. Bộ live test phải có giới hạn lượt/chi phí và dừng khi chạm ngưỡng.

### Track B — quản trị tài khoản và hạn mức

1. Tạo vai trò/đường xác thực operator có thẩm quyền rõ, tách `platform admin` khỏi `tenant manager` và customer; mặc định deny, không cấp quyền chỉ dựa vào email/tên.
2. Operator được ủy quyền có thể tìm/xem trạng thái account trong phạm vi; suspend/reactivate và thu hồi session theo policy; xem usage, limit và reset UTC.
3. Điều chỉnh quota theo membership với giá trị cũ/mới, thời điểm hiệu lực/hạn hết hạn, lý do và bounds do owner cấu hình. Quota mặc định/cap toàn hệ thống không được vô tình bị sửa bởi thao tác account.
4. Mọi thay đổi ghi audit bất biến có actor/role, tenant, target membership, thao tác, giá trị trước/sau, lý do, timestamp và request/correlation ID; không ghi API key, session secret hoặc nội dung hội thoại không cần thiết.
5. Cross-tenant access phải bị từ chối trừ platform role được cấp tường minh; không giả danh khách, đọc nội dung chat hay xuất secret để thực hiện quản trị.
6. Ops Console read-only v1 giữ nguyên ranh giới. Trước khi code, chốt authn/authz và control-plane boundary; không gắn Docker socket/DB admin credential vào dashboard hiện tại.

### Track C — P-604 demo/catalog truth

1. Truy nguyên đường dữ liệu từ demo sample → order rendering → UI. Chỉ đổi **tên hiển thị** của đúng fixture demo được owner chỉ ra thành “Bộ xếp hình gỗ cho bé”; giữ nguyên order fields, catalog, giá và product ID; không làm thay đổi đơn/tenant/customer thật.
2. Không biến P-602 thành P-604 hoặc trả nhãn UI như sự thật từ tool. Model lookup phải tiếp tục phản ánh dữ liệu nghiệp vụ có thẩm quyền; nếu đổi tên chỉ ở UI khiến order detail/tool output mâu thuẫn, nêu chính xác giới hạn và đề xuất cách display-only có phân biệt, không âm thầm sửa nguồn sự thật.
3. Source seed chỉ chạy khi tạo demo identity mới; nó không cập nhật record bền vững của tài khoản demo đã tồn tại. Không viết/chạy migration live. Nếu yêu cầu cần thay đổi persistent record hiện có, dừng ở migration đề xuất riêng, giới hạn exact synthetic tenant/order, idempotent/transactional/fail-closed, chờ owner duyệt.
4. Regression khẳng định chỉ nhãn demo được đổi và toàn bộ fields khác không đổi; P-604 không tự nhận giá/variant/stock/warranty/age/safety facts thiếu; repeated catalog seed idempotent; `check_inventory`/variant lookup trả unknown khi không có dữ liệu tồn kho. Bao gồm generic variant fixture với `stock=null`/`0` để không sinh fallback tồn kho dương.

## Trình tự làm việc và gate

1. **Contract/ADR:** chốt platform-vs-tenant role, authn, phạm vi xem/sửa account, quota bounds/reset/override expiry, session revocation, audit và dữ liệu không được hiển thị.
2. **Implementation:** tạo control plane tối thiểu theo ADR; tách admin endpoints khỏi customer tools và Ops Console read-only; cập nhật demo display label theo Track C mà không sửa record nghiệp vụ.
3. **Offline acceptance:** regression hữu hạn theo criteria; SQLite và PostgreSQL/pgvector; kiểm tra tenant scope, concurrent quota reservation, UTC reset, persistence/restart, audit, lỗi/timeout, order rendering và unknown product/inventory facts.
4. **Bounded model check:** dùng prompt set cố định trong acceptance, test với provider/model được owner chỉ định, quota/cost cap và stop rule đã duyệt. Không chạy full benchmark/performance ở bước này.
5. **PASS → P5-F:** mới lập G5 lane preflight. P5-E PASS không tự cấp G5, G6, deploy/live OAuth hay ngân sách paid measurement.

## Ngoài phạm vi / chống lan man

- Không mở lại P5-K1…K8, không tạo K9; không sửa Google OAuth/EC2/SSM/production DB trong phase này.
- Không xây CRM đầy đủ, không bulk export/delete khách, không sửa đơn thật, giá bán thật, hoàn tiền hay catalog ngoài fixture P-604 được giới hạn ở Track C.
- Không chạy benchmark tải, full 250-case, paid/live campaign hoặc deploy để “thử cho chắc” khi chưa có approval riêng.
- Không rà soát hạ tầng/bug không liên quan AI trust, authorization account/quota và quota/error UX.
- Không thêm cross-encoder/reranker trong P5-E: transcript chưa chứng minh lỗi retrieval/ranking. Chỉ mở việc này ở backlog nếu có qrels/evaluation cho thấy relevant document đã retrieve nhưng bị xếp hạng sai; đo chất lượng, latency và cost riêng trước khi quyết định.

## Deliverables

- ADR/control-plane boundary và role/permission matrix.
- Implementation + SQLite/PostgreSQL regression và bộ red-team acceptance hữu hạn; không sửa/hide CoT trong scope này.
- Evidence theo từng criterion, cùng candidate SHA; usage/quota/cost thực tế và mọi skipped case được ghi rõ.
- Cập nhật acceptance matrix/status/roadmap. Dừng ở báo cáo review; merge/deploy cần quyết định riêng.
