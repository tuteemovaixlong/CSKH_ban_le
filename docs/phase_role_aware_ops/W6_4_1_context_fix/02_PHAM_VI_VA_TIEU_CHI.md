# 02 — Phạm vi và tiêu chí chấp nhận

Làm 6 hàng theo đúng thứ tự. Thiết kế chi tiết của từng hàng ở [03](03_THIET_KE_CHI_TIET.md), danh sách test ở [04](04_TEST_VA_KIEM_TRA.md).

| # | Việc | Tiêu chí chấp nhận |
|---|---|---|
| 1 | **Trần tổng theo cửa sổ (F13 phần cốt lõi).** `MAX_CHARACTERS` và `CONTEXT_TOKENS` trong `agent_protocol.py` tính từ cùng biến `RETAILOPS_MODEL_CONTEXT_TOKENS` mà `compaction.py` đang dùng. | Không đặt biến hoặc đặt 16384: `MAX_CHARACTERS == 36000`, `CONTEXT_TOKENS == 16384`, hành vi y như cũ. Đặt 32768: `MAX_CHARACTERS == 72000`, `CONTEXT_TOKENS == 32768`. Đặt 8192: `MAX_CHARACTERS == 18000`. Giá trị ngoài 4.096–131.072 báo lỗi giống `compaction.context_tokens()`. Không tạo import vòng. |
| 2 | **`list_orders` trả bản tóm tắt, có phân trang, đơn gần nhất trước (F44).** | Mỗi đơn chỉ có đúng các trường tóm tắt ở 03 mục 2.1; không còn `eligibility`, `payment`, `delivery`, `refund`, `vouchers`, `recipient`, `as_of`. Giữ khóa mà rào an toàn và chế độ `legacy` đang đọc. Tham số `limit` (mặc định 5, từ 1 tới 20) và `offset` (mặc định 0) đều tùy chọn; sai kiểu hoặc ngoài khoảng thì trả lỗi rõ, không ném exception. Trả `total_count`, `returned_count`, `offset`, `limit`, `has_more`, `next_offset`, `truncated` (bằng `has_more`). Sắp `ordered_at` giảm dần, rỗng xếp cuối, cùng ngày thì theo `id` giảm dần. Mô tả tool đúng nguyên văn ở 03 mục 2.4. **Ở cấu hình 16k, 5 đơn có đủ dữ liệu như fixture vẫn nằm trọn trong một kết quả tool, không bị cắt phần tử.** |
| 3 | **`list_case_orders` của Trợ lý ca trả bản tóm tắt.** | Mỗi đơn chỉ có các trường ở 03 mục 3; giữ trần 20 đơn; thêm `total_count` và `truncated`. Mô tả tool đúng nguyên văn ở 03 mục 3. `get_case_order` giữ nguyên hồ sơ đầy đủ. |
| 4 | **Rút gọn kết quả tool theo thứ tự mới.** | Thứ tự: (a) rút chuỗi dài qua các nấc, giữ nguyên số phần tử danh sách; (b) bỏ các khóa ít giá trị trong `LOW_VALUE_KEYS`; (c) cuối cùng mới cắt đuôi danh sách, kèm phần tử ghi chú tiếng Việt. Vẫn giữ các bất biến cũ: JSON hợp lệ, có `_truncated: true` khi bị cắt, độ dài không vượt `limit`, kết quả vừa sẵn thì trả nguyên văn. |
| 5 | **Tài liệu cho bộ đánh giá.** | Dòng `list_orders` trong bảng mục 3.1 của `khoa_luan/eval_pack/03_HE_THONG_VA_DU_LIEU.md` mô tả đúng bản tóm tắt và phân trang. Nếu có, dòng `list_case_orders` ở mục 3.2 cũng sửa. `python scripts/build_eval_pack.py --check` đạt; nếu báo khác vì mục sinh tự động thì sinh lại bằng script, không sửa tay. |
| 6 | **Không hồi quy, có số đo.** | Đủ các lệnh ở 04 mục 3; runner `--fake` cho 250 ca, 32 kịch bản W3.2, 12 kịch bản W4 và 4 ca ví dụ đều 100%; SHA-256 12 tệp `evals/suites` khớp; notebook `colab_agent.ipynb` sinh lại bằng script. Báo cáo có bảng số đo kích thước ở 04 mục 4. |

## Ngoài phạm vi

- `SYSTEM`, `answer_check`, rào an toàn, luật nghiệp vụ, kho chính sách, dữ liệu demo.
- Tool MCP `list_orders` trong `retailops_mcp_server.py`.
- Map-reduce bằng một model phụ: owner đã loại, để hướng phát triển.
- Đổi mặc định `--context-tokens` của runner: vẫn là 16384. Lượt đo W6.4 tự truyền 32768 (xem [06](06_SAU_KHI_MERGE.md)).
- Đặt biến môi trường trên production: việc của owner sau khi deploy.

Nếu thấy chỗ nào khác cũng làm model thiếu dữ liệu, **ghi vào báo cáo**, không sửa.
