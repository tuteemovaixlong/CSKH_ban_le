# 01 — Hiện trạng, nguyên nhân và quyết định

Số dòng ghi theo `origin/main` tại `ece0b0b4004ad1fdfddfbcca8abaa86cc69fe408`. Mở lại từng tệp để kiểm trước khi sửa.

## 1. Smoke production sau W6.4.2 (image `sha256:1034776f…`, ô DeepSeek)

| Lượt | Câu khách | Kết quả | Nguyên nhân |
|---|---|---|---|
| `9cdbe635-…` | liệt kê các đơn của tôi | Bảng 5 cột chỉ còn dòng tiêu đề; cả 3 dòng đơn bị xóa; nối `POLICY_NOTE` | `fee_amount`: năm 2026 trong ngày "09/11/2026" bị đọc là 2.026₫. Cột trạng thái có "trễ hạn 54 giờ" thì dính `deadline_number`, vì bản tóm tắt `list_orders` không có `late_by_hours` |
| `725b77cc-…` | phân tích cả 3 đơn giúp tôi | **HTTP 503** `agent_response_failed`, `ProtocolError: Too many tool calls in a model step` | Model gọi lại `list_orders` (lượt trước nó thấy một bảng rỗng), rồi xin hơn 4 tool một bước. `assistant_message` (`agent_protocol.py:391–392`) ném lỗi, cả lượt hỏng |

Claude tái hiện trên `ece0b0b`. Bằng chứng là `list_orders` của hai đơn, và với các dòng `get_order` là một đơn có `shipping_fee = 0` và `warranty_window_days = 90`:

| # | Dòng | Bằng chứng | Trên `ece0b0b` |
|---|---|---|---|
| 1 | `\| SIM-O-38588564-02 \| 09/11/2026 \| Áo khoác Everyday \| 839.000₫ (gồm phí ship 40.000₫) \| Đang vận chuyển \|` | `list_orders` | xóa, `fee_amount` |
| 2 | `- Đặt ngày 2026-11-09, phí ship 40.000₫.` | `list_orders` | xóa, `fee_amount` |
| 3 | `\| SIM-O-38588564-02 \| 839.000₫ \| Đang vận chuyển (trễ hạn 54 giờ) \|` | `list_orders` | xóa, `deadline_number` |
| 4 | `Shipper 090***1234 sẽ giao hàng, phí ship 0đ ạ.` | `get_order` | xóa, `fee_amount` (1234 đọc thành tiền) |
| 5 | `Sản phẩm còn bảo hành 3 tháng ạ.` | `get_order` (90 ngày) | xóa, `deadline_number` |
| 6 | `Thời hạn đổi trả là 30 ngày.` | `get_order` | xóa, `deadline_number` |
| 7 | `Phí ship do shop chịu hoàn toàn.` | `get_order` | xóa, `fee_amount` (không có số) |
| 8 | `Đơn SIM-O-9 được miễn phí ship ạ.` | `get_order`, `shipping_fee = 0` | xóa, `policy_fee` |
| 9 | `Đổi size lần đầu được miễn phí ship ạ.` | `get_order`, `shipping_fee = 0` | xóa, `policy_fee` |
| 10 | `Shop đổi size tận nhà cho anh/chị ạ.` | `get_order` | xóa, `logistics` |
| 11 | `Em đã hủy đơn SIM-O-9 cho anh/chị theo chính sách [KB:0123456789abcdef01234567].` | `get_order` (đơn chưa hủy) | xóa, `done_claim` |

Dòng 1–5 là câu đúng bị xóa nhầm. Dòng 6 là thời hạn bịa. Dòng 7 là lời hứa "shop chịu phí ship" bị bắt nhầm luật (lẽ ra phải là `policy_fee`). Dòng 8 đúng với dữ liệu, dòng 9 là lời hứa chính sách. Dòng 10–11 là chặn đúng.

## 2. Lịch sử xóa nhầm

6 lần ở nhóm so khớp số (F29, F30, F32, F46, F47, lỗi đọc năm). 2 lần ở nhóm khẳng định đã làm (F31, F35), đều đã sửa. Nhóm lời hứa rõ chữ (`logistics`, `policy_fee`) chưa xóa nhầm lần nào.

## 3. Tham vấn Gemini 4 Carbon (2026-11-15) — các điểm Claude đã kiểm lại trong code

- **Bộ kiểm thứ hai có lỗi** (F50). `enforce_final_answer_grounding` mục 4, `retailops/guardrails/topic_filter.py:618–643`, chạy *trước* `answer_check` (`application.py:708`).
  - Câu trả lời có "đã hoàn tiền thành công" hay "đã (được) hủy … thành công" là bị thay **cả câu trả lời**. Hàm không xét đơn trong tool đã hủy hay đã hoàn thật chưa.
  - Câu thay thế còn dùng mã nội bộ `ord_…` (trái W6.1b-D8), in `delivery=…`, `address=…` dạng dữ liệu thô, và với câu hoàn tiền lại nói "chưa thực hiện hủy".
- **Ghi chú nội bộ của Trợ lý ca bị sửa** (F51). `application.py:1351` chạy `check_final_answer` trên toàn văn câu trả lời của Trợ lý ca, nên ghi chú cho nhân viên bị cắt câu và nối ghi chú xưng "em… anh/chị". Ca `s11_016` lượt 2 là ví dụ.
- **Lịch sử được kiểm lại theo cùng giới hạn tool mỗi bước.** `validate_messages` (`agent_protocol.py:434`, gọi `assistant_message` ở dòng 468) chạy lại `assistant_message` cho mọi lượt assistant trong lịch sử. Nâng giới hạn ở một chỗ là đủ cho cả hai.
- **Còn một chỗ trả 503 nữa** ở `retailops/workflow/agent.py:195`, khi tổng tool cả lượt vượt 10. Owner giữ nguyên chỗ này.
- **Trace không vào ngữ cảnh model:**
  - `store.history` (`retailops/business/store.py:4233`) chỉ đọc cột `messages` của `agent_turns`; trace nằm ở cột `result`.
  - `model_history` (`agent_protocol.py`) bỏ thêm lượt gọi tool và kết quả tool của các lượt trước.

## 4. Quyết định của owner (§32 W6.4-D17)

1. **4 luật chặn giữ nguyên** hành vi xóa câu và nối ghi chú: `handoff_claim`, `done_claim`, `logistics`, `policy_fee`. Thêm hai chỉnh nhỏ, cả hai dựa trên chữ hoặc trên trường của tool:
   - "phí ship … do shop chịu" là `policy_fee` (dòng 7);
   - "miễn phí ship" của chính đơn có `shipping_fee = 0` không phải lời hứa (dòng 8), trừ khi câu nói về đổi, trả, hoàn, bảo hành (dòng 9 vẫn chặn).
2. **3 luật số chỉ ghi vết** vào `trace['answer_check_audit']`: tên luật và số dòng, không xóa câu, không nối ghi chú. Ngày tháng, giờ và số điện thoại che không được đọc thành tiền, để số đếm không nhiễu.
3. **Bộ kiểm thứ hai** chỉ thay câu trả lời khi tool của lượt không cho thấy đơn đã hủy (với câu hủy) hay đã hoàn (với câu hoàn); dùng mã sàn; không in dữ liệu thô.
4. **Trợ lý ca:** không sửa ghi chú nội bộ; chỉ kiểm bản nháp gửi khách, và phần nháp hiện trong khung của nhân viên là bản đã kiểm.
5. **Tool mỗi bước = ngân sách cả lượt (10).** Không có đường tràn mềm; vượt 10 cả lượt thì vẫn lỗi như hiện nay. `SYSTEM` giữ nguyên.
6. **Không chấm ngoại tuyến bằng model.** Runner ghi các cờ ghi vết vào báo cáo để đếm.

Rủi ro owner chấp nhận: một thời hạn hay một số phí bịa (dòng 6) không bị chặn nữa, chỉ được ghi vết.
