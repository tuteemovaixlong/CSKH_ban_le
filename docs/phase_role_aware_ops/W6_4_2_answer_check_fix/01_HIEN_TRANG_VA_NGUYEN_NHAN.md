# 01 — Hiện trạng và nguyên nhân

Số dòng ghi theo `origin/main` tại `3239454` (merge #114). Mở lại từng tệp để kiểm trước khi sửa.

## 1. Bằng chứng từ smoke production (2026-11-15, ô DeepSeek, image `sha256:c5250ba7…`)

Tài khoản khách có 3 đơn: `SIM-O-38588564-01` (giao 05/11, đúng hạn), `-02` (đang giao, trễ 54 giờ), `-03` (giao 09/11, trễ 72 giờ). Tool trả đúng dữ liệu; model tính đúng mọi con số.

| Lượt | Câu khách | Thấy trên giao diện | Nguyên nhân |
|---|---|---|---|
| `c7e99b65-…` | liệt kê các đơn của tôi | Đủ 3/3 đơn (F44 đã hết). Mỗi đơn có **một dòng trống** giữa dòng món và dòng ngày đặt; cuối câu nối `POLICY_NOTE` | Mục 3 |
| `da1d2167-…`, `f420e84d-…` | món, giá; phí ship | Đúng, không bị cắt | Dòng chỉ có số `amount`, `shipping_fee` |
| `407909ae-…` | phân tích cả 3 đơn | Bảng tổng đúng (1.587.000 = 1.497.000 + 90.000). **Mất tiêu đề đơn `-03`**: các dòng "trễ đúng 72 giờ", "cửa sổ trả hàng còn khoảng 1 ngày" nằm dưới tiêu đề "`-01` — đơn sạch nhất". Cuối câu vẫn nối `POLICY_NOTE` dù câu trả lời có 2 trích dẫn `[KB:…]` | Mục 4 |

Trace của các lượt này chỉ có `{'dropped_policy_promises': n, 'dropped_done_claims': 0}`: không biết dòng nào bị bỏ, vì luật nào (mục 5).

## 2. Bộ kiểm câu trả lời hoạt động thế nào

`check_final_answer(text, messages)` ở `retailops/workflow/answer_check.py:241` chạy sau khi model viết xong, ở hai chỗ trong `retailops/business/application.py`: dòng 717 (agent và `legacy`) và dòng 1350 (Trợ lý ca; dòng 1364 kiểm bản nháp).

1. `tool_evidence(messages)` (dòng 118) đi qua JSON của mọi tin `role == 'tool'` trong lượt, gom bằng chứng vào `Evidence` (dòng 96):
   - `money_amounts`: giá trị `int` của các khóa trong `_MONEY_FIELDS = ('shipping_fee', 'amount', 'refunded_total', 'pending_total')` (dòng 89), ở mọi độ sâu;
   - `deadline_days`: giá trị `int` của `_DAY_FIELDS = ('return_window_days', 'size_exchange_window_days', 'warranty_window_days', 'warranty_days')` (dòng 90);
   - `has_window`, `has_delivery_date`: có cờ cửa sổ hoặc mốc giao.
2. Tách văn bản theo **dòng** (`split('\n')`), mỗi dòng tách thành câu bằng `_SPLIT` (dòng 32, cắt sau `.!?…`).
3. Mỗi câu qua ba luật theo thứ tự: `_unfounded_handoff` (dòng 235), `_uncited_policy_promise` (dòng 199), `_unfounded_claim` (dòng 219). Câu nào dính luật thì **bỏ nguyên câu**; dòng không còn câu nào thì thành dòng trống. Cuối văn bản nối một ghi chú cho mỗi loại đã bỏ.
4. `_uncited_policy_promise`: câu có `[KB:…]`, là câu hỏi, hoặc có chữ rào đón thì giữ. Không có ngữ cảnh chính sách (`_POLICY_CONTEXT`) thì giữ. Sau đó:
   - có chữ hậu cần (`_LOGISTICS`: tận nhà, 2 chiều, shipper đến lấy…) → bỏ;
   - có chữ phí (`_FEE`): nếu là phí chính sách (`_POLICY_FEE_MATCH`: miễn phí, phí đổi/trả…) → bỏ; nếu là phí ship của đơn thì **mọi số tiền trong câu phải nằm trong `money_amounts`**, không thì bỏ (F30, W6.3.2);
   - có chữ thời hạn (`_DEADLINE`): nếu câu có số đi trước đơn vị thời gian (`_TIME_NUMBER`, dòng 86: ngày, tuần, tháng, năm, giờ) thì **mọi số đó phải nằm trong `deadline_days`**; nếu không có số thì cần `has_window` hoặc `has_delivery_date` (F29, F32, W6.3.1).

## 3. Nguyên nhân 1 — giá món và tổng tiền không phải bằng chứng (F46)

W6.4.0 (F42) thêm `items` vào kết quả đơn: `get_order` có `unit_price`, `quantity`, `subtotal` của từng món (`retailops/business/store.py:2752`); `list_orders` từ W6.4.1 giữ `name`, `variant`, `quantity`, `subtotal` (`retailops_tools.py:149`). `_MONEY_FIELDS` không có `unit_price`, `subtotal`, nên một dòng ghép tiền hàng với phí ship bị coi là lời hứa phí không có bằng chứng.

Cùng lý do, các tổng mà model tự cộng từ dữ liệu tool cũng bị bỏ: tiền hàng của đơn nhiều món (tổng `subtotal`), tổng phí ship hay tổng tiền của nhiều đơn khi khách hỏi "phân tích các đơn".

## 4. Nguyên nhân 2 — số thời gian tool đã tính và cách bỏ dòng tiêu đề (F47)

`compute_order_eligibility` (`retailops/business/eligibility.py`, khối `return` khoảng dòng 184–200) trả `late_by_hours` (số thực, giờ trễ so với hạn cam kết) và `days_since_delivery` (số thực, số ngày từ lúc giao). Model dùng đúng các số này: "trễ 72 giờ", "trễ 3 ngày", "đã giao 4 ngày", "hạn đổi size còn khoảng 10 ngày" (15 − 4,32). Bộ kiểm chỉ nhận 7, 15, 90 nên câu có các số đó và có chữ kích hoạt `_DEADLINE` ("hạn", "quá", "trong", "sau", "trước"…) bị bỏ.

Khi câu bị bỏ nằm trên một **dòng tiêu đề** (ví dụ `**SIM-O-…-03 — trễ hạn 72 giờ, sắp hết hạn trả hàng**`), cả dòng thành trống. Các dòng bên dưới mất tiêu đề và rơi vào mục phía trên.

## 5. Không truy được câu đã bỏ

`application.py:720` và `:1353` chỉ ghi `{'dropped_policy_promises': n, 'dropped_done_claims': m}`. Trace đi nguyên về trình duyệt của khách (`retailops/http/routes.py`, nhánh `/api/chat` trả `(200, result)`), nên **không được ghi chữ của câu bị bỏ vào trace**: chỉ ghi số dòng và tên luật. Runner đánh giá (`scripts/run_agent_scenarios.py:873–893`, `turn_rec`) không chép thông tin này, nên khi phân loại ca thất bại W6.4 không biết câu trả lời có bị bộ kiểm sửa hay không.

## 6. Tái hiện trên `3239454` (Claude chạy, chỉ đọc)

Fixture `standard` (`runner.World({'fixture': 'standard', 'customer': 'SIM-C-0057'}, runner.ScriptedGateway())`), gán 3 đơn cho khách, trong đó `SIM-O-00091` (2 món: 1 × 450.000 và 2 × 520.000 = 1.040.000; phí ship 40.000; tổng 1.530.000), đặt `promised_delivery_by = delivered_at − 72 giờ` để đơn trễ 72 giờ. Bằng chứng là kết quả thật của `get_order('SIM-O-00091')` hoặc `list_orders()` trong cùng lượt.

| # | Dòng model viết | Bằng chứng | Trên `3239454` | Mong đợi sau W6.4.2 |
|---|---|---|---|---|
| 1 | `- Tiền hàng 1.490.000₫ + phí ship 40.000₫ = 1.530.000₫` | `get_order` | **bỏ** | giữ |
| 2 | `- Áo sơ mi lụa công sở 450.000₫, Quần tây đen hàn quốc 1.040.000₫; phí vận chuyển 40.000₫.` | `get_order` | **bỏ** | giữ |
| 3 | `- Đơn giá Quần tây đen hàn quốc 520.000₫ × 2, phí ship 40.000₫.` | `get_order` | **bỏ** | giữ |
| 4 | `- Tổng 1.530.000₫, đã gồm phí ship 40.000₫.` | `get_order` | giữ | giữ |
| 5 | `Tổng phí ship 3 đơn: <tổng 3 phí ship>.` | `list_orders` | **bỏ** | giữ |
| 6 | `Tổng chi <tổng 3 amount>, trong đó phí ship <tổng 3 phí ship>.` | `list_orders` | **bỏ** | giữ |
| 7 | `**SIM-O-00091 — trễ hạn 72 giờ, sắp hết hạn trả hàng**` | `get_order` | **bỏ cả dòng** | giữ nguyên dòng |
| 8 | `- Hạn đổi size còn khoảng 10 ngày.` | `get_order` | **bỏ** | giữ |
| 9 | `- Đã giao được 4 ngày, trong hạn trả 7 ngày.` | `get_order` | **bỏ** | giữ |
| 10 | `**SIM-O-00091 — sắp hết hạn trả hàng**` | `get_order` | giữ | giữ |
| 11 | `Phí đổi hàng là 450.000đ ạ.` | `get_order` | bỏ | **vẫn bỏ** (phí chính sách) |

Các số 72, 10, 4 ở dòng 7–9 đều suy trực tiếp từ `late_by_hours = 72.0` và `days_since_delivery = 4.3169` của chính đơn đó.

## 7. Thấy trong smoke nhưng ngoài phạm vi W6.4.2 (để W6.5)

- `POLICY_NOTE` vẫn nối khi câu trả lời đã có trích dẫn; câu chữ của ghi chú.
- Mã `[KB:…]` hiện thô cho khách.
- Khối "Quá trình suy luận" hiện suy luận tiếng Anh và mã nội bộ cho khách (F20).
- Lịch sử hội thoại gửi model không giữ lượt gọi tool, nên model nghi câu trả lời trước của chính nó là bịa và gọi tool lại.
- Nhãn "Nguồn: custom_api" ở ô DeepSeek (`OpenRouterAgent.inspect`, `retailops_providers.py:236`).
- Lần `search_knowledge` thứ 3 trong một lượt bị chặn (`knowledge_budget_exceeded`).
- Waitress cố định `threads=8` (`retailops/bootstrap.py:69`, F45).
