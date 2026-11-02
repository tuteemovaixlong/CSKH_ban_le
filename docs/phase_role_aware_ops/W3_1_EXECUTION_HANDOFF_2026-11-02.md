# Phase R1 — W3.1 Execution Handoff (Gemini 4 Argon)

> **Trạng thái:** gói sửa nhỏ do owner phát hành ngày 2026-11-02 sau khi thử W3 trên production ([deploy record](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-11-02-w3-production-deploy-record)). Không mở `W4–W6`.
> **Quyết định áp dụng:** [§14](W0_OWNER_DECISION_DELTA_2026-10-29.md#14-w3-owner-decisions-2026-11-02) và **[§15](W0_OWNER_DECISION_DELTA_2026-10-29.md#15-w31-owner-decisions-2026-11-02)**.
> **Nguyên tắc phạm vi:** chỉ làm các mục ở phần 2. **Không đổi schema DB và không thêm migration**; nếu thấy bắt buộc phải đổi schema thì **dừng và hỏi owner**. Gặp quyết định chính sách chưa có trong tài liệu cũng dừng và hỏi.

## 1. Mục tiêu làm việc

- Nhánh mới từ `origin/main`; không commit thẳng vào `main`.
- Không truy cập EC2/SSM, DB thật, Colab/LLM hay dữ liệu khách hàng; không deploy. Vì không có migration, deploy W3.1 dùng workflow thường khi owner duyệt.

## 2. Phạm vi và tiêu chí chấp nhận

| # | Việc phải làm | Tiêu chí chấp nhận (test cô lập) |
|---|---|---|
| 0 | **Bỏ `style="..."` (W3.1-D4).** Chuyển mọi thuộc tính `style` trong `web/index.html` và trong chuỗi HTML do `web/app.js` tạo (`innerHTML`, template string) sang class trong `web/styles.css` hoặc thuộc tính `hidden`. Thêm luật chung `[hidden] { display: none !important; }`. Gán `element.style` bằng JS vẫn được phép (CSP không chặn). Trên trang khách, ô chọn tệp và thanh xem trước tệp đính kèm phải ẩn khi chưa dùng; các nút chỉ dành cho Manager phải ẩn với tài khoản khác. | Test mới: `web/index.html` không còn `style=`; chuỗi HTML trong `web/app.js` không còn `style=`; test JS hiện có vẫn PASS. |
| 1 | **Lưu mốc của ca (W3.1-D3).** Khi yêu cầu gặp nhân viên, nhân viên nhận ca, trả ca và nhân viên đóng ca: ghi một lượt hệ thống cố định vào hội thoại của ca, **trong cùng transaction** với thay đổi trạng thái, `request_id` có tiền tố `sys-notice-`. Loại các lượt này khỏi lịch sử gửi cho model và khỏi các phép đếm lượt (như `sys-reminder-`/`sys-oar-` hiện nay), và không làm mới timer. UI khách và Staff Desk hiển thị chúng như dòng hệ thống; UI không vẽ thêm bản sao phía trình duyệt. | Test: mỗi mốc ghi đúng một lượt; tải lại transcript vẫn thấy; lịch sử gửi model không chứa `sys-notice-`; transaction lỗi thì không có lượt nào. |
| 2 | **Nhãn "Khách không phản hồi" (W3.1-D2).** Tính khi đọc (không thêm cột): ca `in_progress` có `holder`, tin cuối là của nhân viên và đã quá ngưỡng mà khách chưa trả lời. Ngưỡng `RETAILOPS_CASE_HELD_SILENCE_SECONDS`, mặc định 300; production từ chối giá trị nhỏ hơn (giống W2). API Staff Desk trả `customer_silent_seconds`; UI gắn nhãn "Khách không phản hồi · N phút" trong danh sách Đang xử lý và ở đầu ca. Không gửi tin cho khách, không đóng ca. | Test với đồng hồ giả: chưa tới ngưỡng thì không có nhãn; quá ngưỡng thì có; khách trả lời thì nhãn mất; ca không có `holder` không bị gắn; production từ chối giá trị rút ngắn. |
| 3 | **Nhân viên tạo yêu cầu theo đồng ý của khách (W3.1-D1).** `GET /api/staff/cases/<case_id>/orders`: đơn của khách trong ca, kèm loại yêu cầu được phép (`pending` thì hủy; `delivered` thì trả/đổi) và yêu cầu đang mở nếu có. `POST /api/staff/cases/<case_id>/order-actions` nhận `order_id`, `expected_order_version`, `type`, `exchange_kind`, `reason_code`, `reason_text`, `consent_turn_id`. Người gọi phải đang giữ ca hoặc là Manager. `consent_turn_id` phải là **tin nhắn của khách** (không phải bot, nhân viên hay hệ thống) trong hội thoại của ca, thuộc lần mở ca hiện tại và trong vòng 30 phút. Dùng lại dịch vụ tạo yêu cầu của W3: `raised_by_role='customer'`; dòng quyết định `submit` và audit ghi người thao tác là nhân viên, kèm `consent_turn_id` và một đoạn trích ngắn của tin đồng ý; outbox ghi actor là nhân viên. Yêu cầu tạo theo cách này duyệt theo quy tắc của yêu cầu khách tự gửi. | Test: thiếu hoặc sai `consent_turn_id` (tin của bot/nhân viên, ca khác, quá 30 phút) bị từ chối; nhân viên không giữ ca bị chặn; tạo thành công có audit và dòng quyết định đúng; đơn đã có yêu cầu mở bị 409; nhân viên duyệt được yêu cầu này. |
| 4 | **Module "Thao tác ca" (W3.1-D1, W3.1-D5).** Thêm mục "Tạo yêu cầu theo đồng ý của khách": chọn đơn (kèm trạng thái và loại được phép), loại (hủy, trả, đổi size, đổi 1-1), lý do, và **tin nhắn đồng ý** (danh sách tin gần nhất của khách trong ca, mới nhất lên đầu và được chọn sẵn, có trích nội dung và giờ), rồi bấm tạo. Phía khách không có nút hay form xác nhận: khách chỉ nhắn "ok", "được"… Chuyển form hủy do giao thất bại vào mục "Thao tác khác", mặc định thu gọn, chỉ hiện khi khách có đơn `pending`. Khung module có chiều cao tối đa và tự cuộn; transcript luôn còn chỗ hiển thị. Build lại `notebooks/colab_agent.ipynb`. | Test JS: chưa chọn tin đồng ý thì nút tạo bị khóa; gửi đúng payload; "Thao tác khác" mặc định thu gọn; test JS hiện có vẫn PASS; `build_agent_notebook.py --check` PASS. |
| 5 | **Staff Desk dễ nhìn hơn (W3.1-D6).** Cửa sổ mặc định lớn hơn (khoảng 96% chiều rộng và 92% chiều cao màn hình, bỏ giới hạn 1120px/850px hiện tại). Thêm nút **Phóng to / Thu nhỏ** ở header: phóng to thì dialog chiếm toàn màn hình (không bo góc, không viền), nhớ lựa chọn bằng `localStorage`, `Esc` vẫn đóng dialog như cũ. Bố cục: cột hàng đợi có độ rộng cố định; trên màn hình rộng (khoảng ≥1400px) module "Thao tác ca" thành **cột bên phải** cạnh transcript, có cuộn riêng; màn hình hẹp hơn thì giữ kiểu xếp chồng thu gọn được như mục 4. Header ca hiển thị gọn trên một hàng. Không dùng `style="..."` (mục 0). | Test JS: bấm phóng to thì dialog có class toàn màn hình và lưu `localStorage`, mở lại vẫn giữ; bấm thu nhỏ thì về kích thước mặc định; CSS có quy tắc bố cục ba cột cho màn hình rộng; test JS hiện có vẫn PASS. |

## 3. Ngoài phạm vi

- Đổi schema hoặc migration; lý do đổi hàng mới (ví dụ "muốn đổi màu/mẫu khác" khi khách đổi ý) chưa được owner quyết định.
- W4, W5, W6 theo README.

## 4. Kiểm tra và báo cáo

Chạy và báo đúng số pass/fail/skip: `python -m unittest discover -s tests -q`; test JS theo `.github/workflows/ci.yml` (dùng Node thật nếu có; không dùng `WindowsApps\node.cmd`); `python scripts/build_agent_notebook.py --check`, `python scripts/check_docs_contract.py`, `python scripts/check_deployment_contract.py`, `python scripts/check_live_e2e_contract.py`, `git diff --check`.

Báo cáo gồm: file đổi theo từng mục 0–5; kết quả từng lệnh; DONE/BLOCKED từng mục; URL PR và kết quả CI. Thêm một dòng mới vào cột của bạn trong [W1 execution log](W1_EXECUTION_LOG_2026-10-31.md) (ghi rõ là W3.1), không sửa dòng cũ.

## 5. Sau khi Argon báo cáo

Chỉ chạy **một** lượt kiểm chứng theo tiêu chí ở phần 2. Owner quyết định merge; deploy dùng workflow thường (không migration), sau đó owner thử lại trên trình duyệt.
