# 02 — Phạm vi và tiêu chí chấp nhận

Làm 6 hàng theo đúng thứ tự. Thiết kế chi tiết ở [03](03_THIET_KE_CHI_TIET.md), test ở [04](04_TEST_VA_KIEM_TRA.md).

| # | Việc | Tiêu chí chấp nhận |
|---|---|---|
| 1 | **`answer_check` chỉ chặn 4 luật; 3 luật số chỉ ghi vết** (F49). Hai chỉnh của `policy_fee`; ngày, giờ, số điện thoại che không đọc thành tiền. | Bảng 12 dòng ở 04 mục 2 cho đúng cột "Sau W6.4.3". Với mọi đầu vào, câu chỉ dính `fee_amount`, `deadline_number`, `deadline_no_fact` được **giữ nguyên văn**, không nối ghi chú, và có đúng một mục `{'line', 'rule'}` trong `AnswerCheck.audit`. Câu dính một trong 4 luật chặn bị xóa như cũ. `changed`, `details`, ba câu ghi chú, cách giữ nhãn tiêu đề của W6.4.2 không đổi với các luật chặn. |
| 2 | **Trace và runner ghi vết.** | Lượt có ghi vết thì có `trace['answer_check_audit']`, kể cả khi câu trả lời không bị sửa. Lượt không có thì không có khóa này. `trace['answer_check']` và `trace['answer_check_detail']` giữ nguyên ý nghĩa. Bản ghi lượt của runner có `answer_check_audit` khi trace có. Không chỗ nào chứa chữ của câu trả lời. |
| 3 | **Trợ lý ca không sửa ghi chú nội bộ** (F51). | Ghi chú cho nhân viên giữ nguyên văn, kể cả khi có câu dính luật chặn. Bản nháp gửi khách (`draft_reply`) vẫn kiểm đủ 4 luật. Phần nháp hiện trong câu trả lời cho nhân viên trùng với `draft_reply` đã kiểm. Trace có `answer_check`, `answer_check_detail`, `answer_check_audit` của bản nháp. |
| 4 | **Bộ kiểm thứ hai xét tool trước khi thay câu trả lời** (F50). | Đơn đã hủy theo tool và câu "đã được hủy thành công": giữ nguyên. Đơn đã hoàn theo tool và câu "đã hoàn tiền thành công": giữ nguyên. Đơn chưa hủy hay chưa hoàn: thay bằng câu nguyên văn ở 03 mục 4, dùng mã sàn (`external_order_id`), không có `ord_`, `delivery=`, `address=`. |
| 5 | **Một bước được dùng hết ngân sách tool của lượt** (F48). | `MAX_TOOLS_PER_STEP == MAX_TOOL_CALLS == 10`. Model xin 7 tool trong một bước thì cả 7 chạy và lượt hoàn tất (HTTP 200). Lịch sử có bước 7 tool vẫn qua `validate_messages`. Xin 11 tool một bước, hoặc tổng cả lượt vượt 10, vẫn trả lỗi như cũ (`ProtocolError` / `agent_budget_exceeded`); không có đường tràn mềm. `SYSTEM` không đổi một ký tự. |
| 6 | **Không hồi quy, có số đo.** | Đủ các lệnh ở 04 mục 4; test cũ chỉ sửa đúng các chỗ ở 04 mục 3, mọi test khác đạt mà không sửa; runner `--fake` cho 250 ca, 32 kịch bản W3.2, 12 kịch bản W4 và 4 ca ví dụ đều 100%; SHA-256 12 tệp `evals/suites` khớp; notebook `colab_agent.ipynb` sinh lại bằng script. Báo cáo có các số đo ở 04 mục 5. |

## Ngoài phạm vi

- Lịch sử hội thoại không giữ lượt gọi tool của lượt trước (W3.2-D8): để W6.5.
- Câu chữ `POLICY_NOTE`; hiện `[KB:…]` thô; khối "Quá trình suy luận" (F20); trạng thái đơn tiếng Anh (`pending`, `delivered`) trong câu thay thế của bộ kiểm thứ hai.
- Nhãn "Nguồn: custom_api"; ngân sách `search_knowledge` mỗi lượt; Waitress `threads=8` (F45).
- Luật mới để bắt lời hứa voucher.
- Chấm ngoại tuyến bằng model.
- `khoa_luan/`: Claude cập nhật trong batch tài liệu.

Nếu thấy chỗ khác cũng xóa hay thay nhầm câu đúng, **ghi vào báo cáo**, không sửa.
