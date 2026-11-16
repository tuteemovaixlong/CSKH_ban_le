# W6.4.3 — Bộ kiểm câu trả lời chỉ chặn điều code biết chắc; bỏ giới hạn 4 tool mỗi bước

> **Trạng thái:** phát hành ngày 2026-11-15; **đã thực thi**, PR [#116](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/116) merge `662cb77`, deploy 2026-11-16. **Executor đọc bộ tài liệu này tại chỗ trên máy owner**, ở `D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/.claude/worktrees/cai-nay-la-sao-bddcef/docs/phase_role_aware_ops/W6_4_3_answer_check_scope/`. Code lấy từ `origin/main` tại `ece0b0b` (merge #115, W6.4.2) hoặc mới hơn.
> **Executor:** Gemini 4 Hydrogen, chạy trong Antigravity trên máy owner.
> **Người kiểm chứng:** Claude, một lượt, theo tiêu chí ở [02](02_PHAM_VI_VA_TIEU_CHI.md). **Owner quyết định merge.**
> **Quyết định áp dụng:** [§32](../W0_OWNER_DECISION_DELTA_2026-10-29.md#32-w64-roadmap-update-2026-11-15) W6.4-D17; F48–F51 trong [W6 backlog](../W6_BACKLOG_2026-11-06.md). Bối cảnh tham vấn: [W6.4.3 tham vấn](../W6_4_3_answer_check_consult/README.md).

## Vì sao có bản sửa này

Smoke production sau deploy W6.4.2 (2026-11-15, ô DeepSeek) hỏng cả hai câu:

1. "liệt kê các đơn của tôi": model kẻ bảng 3 đơn, **cả 3 dòng bảng bị bộ kiểm xóa**. Luật `fee_amount` đọc năm "2026" trong ngày "09/11/2026" thành số tiền 2.026₫, không thấy số đó trong tool nên coi là bịa.
2. "phân tích cả 3 đơn giúp tôi": **HTTP 503**. Model xin hơn 4 tool trong một bước; giao thức từ chối và làm hỏng cả lượt.

Trong 8 lần bộ kiểm xóa nhầm câu đúng, 6 lần do ba luật so khớp số: `fee_amount`, `deadline_number`, `deadline_no_fact`. Code không thể biết chắc một con số trong câu tiếng Việt là bịa hay đúng: có thể là năm, số điện thoại che, "3 tháng" thay cho 90 ngày, hay một tổng tự cộng. Sau tham vấn Gemini 4 Carbon, **owner chốt nguyên tắc: code chỉ chặn những gì code biết chắc đúng hay sai.** Cụ thể:

- giữ 4 luật chặn:
  - "đã chuyển nhân viên": kiểm bằng kết quả tool chuyển ca;
  - "đã hủy/đổi/trả/hoàn tiền": kiểm bằng trạng thái đơn trong tool;
  - lời hứa hậu cần và lời hứa phí: kiểm bằng việc câu có trích dẫn `[KB:…]` hay không;
- 3 luật số **chỉ ghi vết** vào trace: không xóa câu, không nối ghi chú. Trace không bao giờ vào ngữ cảnh model ở lượt sau;
- sửa thêm hai lỗi cùng loại mà tham vấn tìm ra: bộ kiểm thứ hai (`topic_filter.py`) và ghi chú nội bộ của Trợ lý ca;
- bỏ giới hạn 4 tool mỗi bước: một bước được dùng tới hết ngân sách 10 tool của lượt, không có đường "tràn mềm".

Chi tiết và bằng chứng ở [01](01_HIEN_TRANG_VA_NGUYEN_NHAN.md).

## Thứ tự đọc

| Tệp | Nội dung |
|---|---|
| [01_HIEN_TRANG_VA_NGUYEN_NHAN.md](01_HIEN_TRANG_VA_NGUYEN_NHAN.md) | Bằng chứng smoke, kết quả tham vấn, quyết định của owner, vị trí code |
| [02_PHAM_VI_VA_TIEU_CHI.md](02_PHAM_VI_VA_TIEU_CHI.md) | 6 hàng việc và tiêu chí chấp nhận |
| [03_THIET_KE_CHI_TIET.md](03_THIET_KE_CHI_TIET.md) | Tên hằng, khóa trace, câu chữ nguyên văn, luật mới, cách sửa từng chỗ |
| [04_TEST_VA_KIEM_TRA.md](04_TEST_VA_KIEM_TRA.md) | Test phải viết trước, **danh sách test cũ được phép sửa**, lệnh kiểm, số đo, báo cáo |
| [05_PROMPT_CHO_ANTIGRAVITY.md](05_PROMPT_CHO_ANTIGRAVITY.md) | Khối prompt owner dán vào Antigravity |
| [06_SAU_KHI_MERGE.md](06_SAU_KHI_MERGE.md) | Việc của Claude và owner sau khi merge |

Executor ghi báo cáo vào `docs/phase_role_aware_ops/W6_4_3_EXECUTION_REPORT_2026-11-15.md` **trên nhánh của mình**.

## Nguyên tắc

- Tạo nhánh mới `phase-r1-w6-4-3` từ `origin/main` (tại `ece0b0b` hoặc mới hơn). Không theo dõi `main`.
- **Bộ handoff này chỉ để đọc.** Không chép, không sửa, không commit các tệp trong thư mục handoff hay trong worktree `.claude/worktrees/cai-nay-la-sao-bddcef`.
- Hàng 1–5: viết test trước, chạy trên code chưa sửa để thấy FAIL, ghi lại dòng lỗi, rồi mới sửa.
- **Test cũ chỉ được sửa đúng các chỗ liệt kê ở 04 mục 3**, đúng cách đã ghi: đổi khẳng định "câu bị xóa" của ba luật số thành "câu giữ nguyên, có ghi vết". Không bỏ câu thử nào. Test cũ nào khác đỏ thì **dừng và hỏi owner**.
- Không đổi câu `POLICY_NOTE`, `CLAIM_NOTE`, `HANDOFF_NOTE`; không đổi hai khóa cũ trong `trace['answer_check']`.
- Không ghi chữ của câu trả lời vào trace hay báo cáo runner: trace được trả nguyên về trình duyệt của khách.
- Không sửa ca trong `evals/suites/` (đã đóng băng, W6.3-D7). SHA-256 của 12 tệp phải khớp bảng trong `evals/suites/README.md`.
- Không sửa `SYSTEM`, mô tả tool, rào an toàn khác, luật nghiệp vụ, kho chính sách, dữ liệu demo, giao diện web, `khoa_luan/` (Claude sửa phần khóa luận trong batch tài liệu).
- Không migration, không thêm thư viện, không đổi workflow CI hay deploy.
- Gặp quyết định chưa có trong tài liệu thì **dừng và hỏi owner**.

## Cấm

- merge; push vào `main`; force-push, rebase, reset, stash;
- đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e;
- truy cập EC2, SSM, DB production, Colab, model thật hay API trả phí, dữ liệu khách hàng;
- thêm thư viện vào requirements;
- sửa ca trong `evals/suites/`;
- dán khóa, token, URL database vào báo cáo hay log.
