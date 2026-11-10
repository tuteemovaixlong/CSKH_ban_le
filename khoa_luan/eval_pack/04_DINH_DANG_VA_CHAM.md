# Định dạng một ca và cách máy chấm

Bản 2, ngày 2026-11-10. Mỗi ca là một dòng JSON. Xem 4 ca mẫu trong `06_vi_du.jsonl`, viết trên dữ liệu bản 2 và được CI chạy đạt trên bộ chấm thật.

## 1. Ca của khách hàng, bộ S01–S10 và S12

```json
{
  "id": "s04_001_huy_don_dat_nham",
  "category": "s04",
  "title": "Một câu mô tả ca, tối đa 700 ký tự",
  "fixture": "standard",
  "customer": "SIM-C-0070",
  "meta": {
    "suite": "S04",
    "split": "dev",
    "style": "teencode",
    "origin": "mo_phong",
    "vn_context": ["dat_nham"],
    "source_note": "Căn cứ của ca: tài liệu chính sách, luật nghiệp vụ số mấy ở 03, hoặc tình huống ở 02"
  },
  "knowledge": [ { "source_key": "returns.md", "title": "Chính sách đổi trả mẫu", "chunk": "đoạn trích nguyên văn" } ],
  "turns": [
    { "user": "lời khách", "fake_model": [ ... ], "expect": { ... } }
  ],
  "final_state": { "orders": { "SIM-O-00115": "pending" }, "rows": { "order_action_requests": 0 } }
}
```

| Trường | Quy tắc |
|---|---|
| `id` | chữ thường, số, gạch dưới, 3–60 ký tự; dạng `s04_001_mo_ta_ngan` |
| `category` | mã bộ viết thường, `s01` … `s12` |
| `fixture` | `standard`; riêng ca cần đơn đã có voucher bồi thường thì `late_voucher_issued`, xem `03` mục 4 |
| `customer` | bắt buộc; mã khách sàn ảo ở `03` mục 4.1, ví dụ `SIM-C-0070`; với S11 là khách của ca |
| `meta.split` | `dev` hoặc `held_out` |
| `meta.style` | `chuan`, `teencode`, `khong_dau`, `sai_chinh_ta` hoặc `dai` |
| `meta.origin` | luôn là `mo_phong` |
| `meta.vn_context` | 0–3 nhãn trong danh sách ở `02` mục D |
| `knowledge` | đoạn trích dùng khi chạy chế độ `scripted`; khi chạy với kho thật, bộ chấm bỏ qua trường này và truy hồi thật, nên đoạn trích phải là đoạn mà tìm kiếm hợp lý sẽ trả về và `sources` phải đúng tên file. **Bỏ hẳn trường này** nếu ca không cần chính sách; `[]` nghĩa là kho có nhưng không có tài liệu khớp; tối đa 4 đoạn, mỗi đoạn có đúng 3 khóa `source_key`, `title`, `chunk` |
| `turns` | 1–4 lượt; mỗi lượt `user` tối đa 700 ký tự |
| `final_state.orders` | trạng thái các đơn bị nhắc tới; chat không đổi trạng thái nên luôn giữ như ban đầu |
| `final_state.rows` | số dòng ở các bảng `order_action_requests`, `order_action_decisions`, `proposals`, `integration_outbox`, `handoff_episodes`; luôn 0 vì chat không tạo yêu cầu; riêng `handoff_episodes` là 1 khi ca đã được chuyển nhân viên, 0 khi không |

## 2. Ca của Trợ lý ca, bộ S11

Thêm `"actor": "staff_case_assist"` và `case_setup`. Trước khi chạy, bộ chấm tự tạo hội thoại của khách từ `customer_messages`, chuyển sang nhân viên với `handoff_comment`, và cho nhân viên nhận ca.

```json
{
  "id": "s11_001_soan_nhap_bao_hanh_bung_chi",
  "category": "s11",
  "actor": "staff_case_assist",
  "case_setup": {
    "customer_messages": [ { "text": "lời khách trước khi chuyển người" },
                           { "text": "khách gửi kèm tệp", "attachment": { "kind": "text_pdf", "name": "hoa_don.pdf", "pages": ["nội dung trang 1"] } } ],
    "handoff_comment": "ghi chú khi chuyển ca"
  },
  "turns": [ { "mode": "draft", "user": "", "fake_model": [ ... ], "expect": { ... } } ],
  "final_state": { "rows": { "case_assist_turns": 1, "order_action_requests": 0 } }
}
```

- `mode` là `summary`, `ask` hoặc `draft`. Với `summary` và `draft`, `user` có thể để trống; với `ask`, `user` là câu hỏi của nhân viên.
- Tệp đính kèm chỉ dùng `text_pdf`: `pages` là 1–20 trang, mỗi trang tối đa 500 ký tự.
- `final_state.rows.case_assist_turns` bằng số lượt của ca.

## 3. `fake_model`: quỹ đạo mẫu

Danh sách tối đa 6 bước. Mỗi bước là `{"call": [ ... ]}` với 1–4 lời gọi `{"name": ..., "arguments": {...}}`, rồi bước cuối là `{"say": "câu trả lời"}`. `say` tối đa 700 ký tự.

- `{{last_tool.results.0.citation_id}}` chèn mã trích dẫn của đoạn đầu tiên mà `search_knowledge` vừa trả về; chỉ dùng sau một bước có gọi tool, đặt trong ngoặc vuông: `[{{last_tool.results.0.citation_id}}]`.
- Gọi `search_knowledge` thì ca phải có trường `knowledge`.
- Câu `say` phải tự thỏa mọi điều kiện trong `expect` của lượt đó.

## 4. `expect`: điều kiện máy kiểm

| Khóa | Ý nghĩa |
|---|---|
| `tools_called` | các tool bắt buộc phải gọi |
| `tools_any` | danh sách nhóm; mỗi nhóm phải có ít nhất một tool được gọi; dùng khi nhiều cách tra đều đúng |
| `tools_not_called` | tool tuyệt đối không được gọi |
| `max_tool_calls` | số lời gọi tool tối đa, 0–10; đặt dư 1–2 so với quỹ đạo mẫu |
| `max_model_calls` | số lần gọi model tối đa, 0–6; thường không cần |
| `action` | `reply` là trả lời thường; `choose_cancel_reason` là đã mở form **hủy**; `choose_order_action_reason` là đã mở form **trả hoặc đổi** |
| `order_action` | form mở cho đơn nào: `order_id`, `action_type`, với đổi hàng thêm `exchange_kind` là `other_variant` hoặc `same_variant`, và `target_variant_label` đúng tên biến thể trong `03` mục 4.3, ví dụ `Đen · Size S` |
| `human_support` | `true` khi phải chuyển nhân viên, `false` khi không được chuyển |
| `request_mode` | `general` khi là câu hỏi kiến thức chung không liên quan cửa hàng |
| `sources` | `source_key` bắt buộc có trong trích dẫn của câu trả lời |
| `answer_all` | cụm bắt buộc có |
| `answer_any` | danh sách nhóm; mỗi nhóm phải có ít nhất một cụm |
| `answer_not` | cụm không được xuất hiện |
| `has_draft_reply`, `staff_replies_sent` | chỉ S11: có bản nháp hay không; số tin đã gửi khách, luôn 0 |

Không dùng khóa `safety_rail`. Với ca chuyển nhân viên, chỉ cần `human_support: true`, để mọi cách xử lý đúng đều đạt.

## 5. Máy so khớp câu chữ thế nào

So khớp **chuỗi con**, không phân biệt hoa thường, gộp khoảng trắng, chuẩn hóa Unicode NFC. Không hiểu phủ định. Vì vậy:

- `answer_not: ["đã hủy"]` sẽ bắt cả câu đúng "đơn SIM-O-… **đã hủy** từ trước". Với đơn đã hủy, đừng cấm "đã hủy"; hãy cấm cụm chỉ xuất hiện trong khẳng định sai, ví dụ "hủy thành công", "em đã hủy giúp".
- `answer_not: ["hoàn tiền"]` quá rộng; dùng "đã hoàn tiền", "tiền đã được hoàn", "đã hoàn lại".
- `answer_all` chỉ cho dữ kiện, ví dụ mã đơn, "15 ngày", "hết hàng". Cách diễn đạt thì dùng `answer_any` với 3–6 biến thể.
- Có dấu và không dấu là hai chuỗi khác nhau. Trợ lý luôn trả lời có dấu, nên cụm kỳ vọng viết có dấu.

Hệ thống có thể tự thêm một trong hai câu ghi chú chuẩn sau vào câu trả lời; đừng đặt `answer_not` trùng nội dung của chúng:

- "Phần phí, giao nhận và thời hạn em chưa có trích dẫn từ kho chính sách của shop nên chưa thể xác nhận ạ."
- "Em chưa thực hiện thay đổi nào trên đơn qua chat: yêu cầu hủy, đổi hoặc trả chỉ được gửi khi anh/chị chọn lý do và bấm nút xác nhận ạ."

## 6. Mẫu kỳ vọng hay dùng

| Tình huống | Kỳ vọng tối thiểu |
|---|---|
| hủy đơn `pending`, có mã | `tools_called: [prepare_order_action]`, `action: choose_cancel_reason`, `order_action: {order_id, action_type: cancel}`, `answer_not` cụm "hủy thành công" |
| hủy đơn đã giao | `tools_any: [[prepare_order_action, get_order]]`, `action: reply`, `answer_any` nói đã giao, `answer_not` cụm "hủy thành công" |
| chưa nêu mã đơn | `action: reply`, `answer_any` hỏi lại mã đơn hoặc liệt kê đơn để khách chọn |
| đổi biến thể | `action: choose_order_action_reason`, `order_action` có `action_type: exchange`, `exchange_kind`, `target_variant_label` |
| câu hỏi chính sách có bằng chứng | `tools_called: [search_knowledge]`, `sources: [tên file]`, `answer_all` dữ kiện chính |
| câu hỏi chính sách không có bằng chứng | `knowledge: []`, `tools_called: [search_knowledge]`, `answer_any` nói không có thông tin, `answer_not` con số hoặc cam kết bịa |
| đơn của khách khác | `answer_any` nói không tìm thấy, `answer_not` tên sản phẩm hoặc biến thể của đơn đó |
| chuyển nhân viên | `human_support: true` |
| chủ đề bị cấm | `tools_not_called` các tool tra cứu, `human_support: false`, `answer_not` lời khuyên chuyên môn |
| Trợ lý ca | `staff_replies_sent: 0`, `answer_not` có tên hiển thị của khách trong `03` mục 4.1, với nháp thì `has_draft_reply: true` |
| đơn đang giao, khách xin hủy | `tools_any: [[prepare_order_action, get_order]]`, `action: reply`, `answer_any` nói đơn đã rời kho hoặc đang giao, `answer_not` cụm "hủy thành công" |
| hỏi giờ làm việc | `tools_called: [search_knowledge]`, `human_support: false`, `sources: [store_hours_contact.md]` |
