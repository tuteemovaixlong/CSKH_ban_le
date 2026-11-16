# 02 — Phạm vi và tiêu chí chấp nhận

Làm 5 hàng theo đúng thứ tự. Thiết kế chi tiết ở [03](03_THIET_KE_CHI_TIET.md), danh sách test ở [04](04_TEST_VA_KIEM_TRA.md).

| # | Việc | Tiêu chí chấp nhận |
|---|---|---|
| 1 | **Tiền của món và tổng suy ra là bằng chứng (F46).** `_MONEY_FIELDS` thêm `unit_price`, `subtotal`; `Evidence.derived_money` có tiền hàng mỗi đơn và tổng nhiều đơn. | Dòng 1, 2, 3, 5, 6 ở bảng 01 mục 6 được giữ với đúng bằng chứng đó, và vẫn bị bỏ khi không có bằng chứng. Dòng 11 (phí đổi hàng) vẫn bị bỏ. Câu phí ship có một số tiền không nằm trong bằng chứng (ví dụ 35.000đ) vẫn bị bỏ. Một đơn xuất hiện ở cả `list_orders` và `get_order` chỉ cộng một lần. Bản ghi thanh toán không tính là đơn. Với đầu vào không có `unit_price`, `subtotal`, `money_amounts` y như cũ. |
| 2 | **Số thời gian tool đã tính là bằng chứng (F47 phần 1).** `Evidence.derived_time` lấy từ `late_by_hours` và `days_since_delivery` theo 03 mục 2. | Dòng 7, 8, 9 ở bảng 01 mục 6 được giữ với bằng chứng `get_order` của đơn trễ 72 giờ, giao 4,3169 ngày; vẫn bị bỏ khi không có bằng chứng. "Hạn đổi size còn 12 ngày" (12 không suy ra được) và "Shop cho đổi trong 30 ngày" vẫn bị bỏ. `late_by_hours` bằng 0, `None`, chuỗi hay `bool` không thêm số nào. |
| 3 | **Giữ nhãn khi phải bỏ dòng tiêu đề; bỏ dòng chỉ còn số thứ tự (F47 phần 2).** | Đúng mọi ví dụ ở bảng 03 mục 3.3. Câu trả lời nhiều mục như smoke (3 tiêu đề đơn, tiêu đề đơn thứ 3 có câu bị bỏ) vẫn giữ đủ 3 tiêu đề, các dòng của đơn thứ 3 nằm dưới tiêu đề của nó. Bộ đếm và ghi chú cuối giống hành vi cũ. Chạy lại bộ kiểm trên kết quả thì không đổi. |
| 4 | **Ghi chi tiết câu bị bỏ, không ghi chữ.** `AnswerCheck.details`; `trace['answer_check_detail']`; khóa `answer_check` trong lượt của báo cáo runner. | Mỗi câu bị bỏ có đúng một phần tử 4 khóa ở 03 mục 4.1, đúng số dòng và tên luật ở 03 mục 4.2; `len(details) == dropped_policy + dropped_claims`. `trace['answer_check']` giữ nguyên hai khóa cũ. `answer_check_detail` và khóa `answer_check` của báo cáo runner **không chứa chữ** của câu bị bỏ. Lượt không bị sửa thì không có `answer_check_detail` và không có khóa `answer_check` trong lượt của báo cáo. |
| 5 | **Không hồi quy, có số đo.** | Đủ các lệnh ở 04 mục 3; **mọi test cũ của bộ kiểm đạt mà không sửa**; runner `--fake` cho 250 ca, 32 kịch bản W3.2, 12 kịch bản W4 và 4 ca ví dụ đều 100%; SHA-256 12 tệp `evals/suites` khớp; notebook `colab_agent.ipynb` sinh lại bằng script. Báo cáo có các số đo ở 04 mục 4. |

## Ngoài phạm vi (để W6.5)

- Câu chữ và điều kiện nối `POLICY_NOTE` (vẫn nối khi câu trả lời có trích dẫn).
- Hiển thị `[KB:…]` thô cho khách; khối "Quá trình suy luận" (F20).
- Lịch sử hội thoại không giữ lượt gọi tool.
- Nhãn "Nguồn: custom_api" ở ô DeepSeek; ngân sách `search_knowledge` mỗi lượt.
- Waitress `threads=8` (F45).
- Kiểm bản nháp của Trợ lý ca (dòng 1364): giữ nguyên.
- Mọi luật mới để bắt lời hứa: W6.4.2 chỉ thêm bằng chứng từ tool và sửa cách bỏ dòng.

Nếu thấy chỗ khác của bộ kiểm cũng cắt nhầm dữ kiện của tool, **ghi vào báo cáo**, không sửa.
