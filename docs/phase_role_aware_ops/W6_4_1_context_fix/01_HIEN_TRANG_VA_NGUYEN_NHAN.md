# 01 — Hiện trạng và nguyên nhân

Số dòng ghi theo `main` tại `fdaa2c3` (merge PR #112). Executor phải mở file để kiểm lại trước khi sửa.

## 1. Bằng chứng trên production (2026-11-15)

- Production chạy W6.4.0, image `sha256:3848352575a0…`, model `deepseek-flash`, chưa đặt `RETAILOPS_MODEL_CONTEXT_TOKENS`, tức đang dùng mặc định 16.384.
- Tài khoản smoke có 3 đơn: `SIM-O-38588564-01`, `-02`, `-03`; mỗi đơn 1 món.
- Câu "liệt kê các đơn của tôi": model gọi `list_orders`, rồi `get_context`, và chỉ nêu được 2 đơn. Phần suy luận ghi: *"The list is truncated with "+1 more". I need the third order… returned_count 3, total_count 3, but only 2 shown."* Model còn cân nhắc đoán mã đơn thứ 3, rồi tự bỏ vì luật cấm bịa mã.
- Câu hỏi riêng từng đơn bằng `get_order` thì đúng hết (món, đơn giá, phí ship, tổng), nên dữ liệu `items` của W6.4.0 không có lỗi. Lỗi nằm ở khâu đóng gói kết quả cho model.

## 2. Ngân sách cắt chữ tính theo một biến cố định 16k

`retailops/workflow/compaction.py`:

| Dòng | Nội dung |
|---|---|
| 14–18 | `context_tokens()` đọc `RETAILOPS_MODEL_CONTEXT_TOKENS`, mặc định `16384`, cho phép 4.096–131.072 |
| 21–22 | `_budget(base, floor) = max(floor, base * context_tokens() // 16384)` |
| 24–28 | `TOOL_RESULT_MAX_CHARS = _budget(5200, 800)`, `TOOL_CONTENT_BUDGET = _budget(12000, 1600)`, `MIN_RESULT_CHARS = _budget(800, 200)`, `HISTORY_CHAR_BUDGET = _budget(6000, 1000)`, `HISTORY_MESSAGE_CHARS = _budget(1500, 300)` |

| Ngân sách | 16k (hiện tại) | 32k |
|---|---:|---:|
| Một kết quả tool | 5.200 | 10.400 |
| Mọi kết quả tool của một lượt | 12.000 | 24.000 |
| Sàn của kết quả đến sau | 800 | 1.600 |
| Lịch sử các lượt trước | 6.000 | 12.000 |
| Một tin trong lịch sử | 1.500 | 3.000 |

Các hằng này tính **một lần lúc import** module. Đổi biến môi trường sau khi app đã chạy thì phải khởi động lại tiến trình.

`agent_protocol.py`:

| Dòng | Nội dung |
|---|---|
| 9 | `CONTEXT_TOKENS = 16384`, chỉ dùng cho `num_ctx` của đường Ollama cũ (dòng 479) |
| 10 | `MAX_CHARACTERS = 36000`, **cố định**, không theo biến môi trường |
| 13 | `MAX_SYSTEM_CHARACTERS = 6400`; `SYSTEM` hiện dài 5.993 ký tự, có focus tối đa là 6.284 |
| 407 | kiểm giao thức: tổng ký tự hội thoại vượt `MAX_CHARACTERS` thì báo `Conversation exceeds context budget` |

`retailops/workflow/agent.py` dòng 148: `fit_transcript(outgoing, MAX_CHARACTERS - 200)` là chốt cuối trước khi gửi model. Vì `MAX_CHARACTERS` cố định, nâng biến lên 32k chỉ nới được ngân sách từng phần; tổng vẫn bị ép về 36.000 ký tự.

## 3. `list_orders` trả nguyên hồ sơ đầy đủ

`retailops_tools.py`:

| Dòng | Nội dung |
|---|---|
| 151–196 | `_resolve_order_or_candidates` dựng hồ sơ đầy đủ của một đơn: mọi cột của bảng `orders` trừ dữ liệu cá nhân, cộng `payment`, `delivery`, `refund`, `refund_summary`, `eligibility`, `vouchers`, `items`, `recipient`, `as_of`, `source`… |
| 198 | `read_order(oid, focus)` |
| 209–220 | `list_orders`: lấy `self.store.orders(customer)`, cắt 10 đơn đầu, gọi `read_order` cho từng đơn, trả `orders`, `truncated`, `returned_count`, `total_count`, và `note` tiếng Anh khi bị cắt |

`retailops/business/store.py` dòng 2737–2739: `orders(customer)` sắp `ORDER BY id`, tức mã tăng dần, **không phải** đơn gần nhất trước.

`agent_protocol.py` dòng 107: mô tả tool hiện tại ("List up to 10 orders … including … server-computed eligibility"), không có tham số.

W6.4.0 đo trên fixture: 10 đơn đầy đủ dài 21.969 ký tự JSON thô, sau rút gọn còn 4.597. Như vậy trung bình **khoảng 2.200 ký tự mỗi đơn**, nên đơn thứ 3 đã chạm trần 5.200.

## 4. Bước rút gọn cắt chuỗi và cắt phần tử cùng lúc

`compaction.py`:

| Dòng | Nội dung |
|---|---|
| 29 | `_STEPS = ((240, 10), (160, 6), (120, 4), (80, 2))`: mỗi nấc vừa cắt chuỗi vừa cắt danh sách |
| 36–46 | `_shrink`: chuỗi dài cắt về `string_cap` kèm `…`; danh sách giữ `list_cap` phần tử đầu, thêm chuỗi `…(+N more)`; dict thì đệ quy |
| 49–68 | `compact_tool_result`: vừa thì trả nguyên; không vừa thì lần lượt thử các nấc, đặt `_truncated: True`; cuối cùng là `preview` |

Một danh sách 3 đơn, mỗi đơn khoảng 2.200 ký tự, phải xuống nấc mà `list_cap` nhỏ hơn 3 mới vừa 5.200. Khi đó nguyên đơn bị bỏ, dù các đơn còn nhiều chuỗi dài có thể rút ngắn.

## 5. Những chỗ khác đang đọc kết quả `list_orders`, phải giữ tương thích

| Vị trí | Đọc gì | Hệ quả nếu đổi tên khóa |
|---|---|---|
| `retailops/guardrails/topic_filter.py` 575–590 | `truncated`, `returned_count`, `total_count`, `orders` | Rào an toàn buộc câu trả lời phải nói rõ danh sách chưa đủ khi `truncated` là true |
| `retailops/workflow/subagents/order_agent.py` 65–77 (`_order`) và 162–173 | mỗi đơn: `external_order_id` hoặc `id`, `status`, `name`, `variant`, `amount`; và `truncated` | Chế độ `legacy` (cấu hình B của W6.4) hiển thị danh sách đơn. Thiếu khóa thì `_order` trả `None` và cả phần hiển thị hỏng |
| `retailops/workflow/subagents/read_worker.py` 93–96 | `len(orders)` | Câu tóm tắt "Tìm thấy N đơn" |
| `retailops_mcp_server.py` 877–880 | tool MCP riêng, có `limit` | **Ngoài phạm vi**, không sửa |

Thẻ "Dữ liệu đơn hàng" trên giao diện chat lấy từ API `focus` (`retailops/business/application.py` 990–1012, `describe_order`), **không** lấy từ `list_orders`, nên không bị ảnh hưởng.

## 6. Trợ lý ca có cùng rủi ro

`retailops/workflow/case_assist.py`:

| Dòng | Nội dung |
|---|---|
| 101–104 | mô tả tool `list_case_orders` |
| 352–414 | `_format_case_order`: hồ sơ đầy đủ một đơn, gồm `items`, `eligibility`, `refund_summary`, `vouchers`… |
| 416–447 | `_list_case_orders`: tối đa 20 đơn (`LIMIT 20`), mỗi đơn là hồ sơ đầy đủ |

## 7. Bộ đánh giá phụ thuộc vào `list_orders` thế nào

- Bộ 250 ca: 80 lượt có `list_orders` trong `expect.tools_any`, tức là được phép dùng `list_orders` **hoặc** tool khác như `get_order`, `track_shipment`. Nhiều lượt có `max_tool_calls` (ví dụ 4). `answer_any` thường đòi tên sản phẩm, trạng thái, số tiền.
- Câu trả lời giả của gateway giả (`fake_model`) gọi `list_orders` ở 81 chỗ. Gateway giả **không đọc** nội dung kết quả tool, nên runner `--fake` vẫn phải đạt 100%.
- `khoa_luan/eval_pack/03_HE_THONG_VA_DU_LIEU.md` mục 3.1 (bảng tool, dòng 40) mô tả `list_orders` trả gì, và phải sửa cho khớp. Mục 3.3 là phần sinh tự động giữa các dấu `<!-- BEGIN GENERATED … -->`: nếu `python scripts/build_eval_pack.py --check` báo khác thì sinh lại bằng script, **không** sửa tay.
