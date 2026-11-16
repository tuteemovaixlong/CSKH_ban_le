# W6.4.1 — Ngữ cảnh 32k, danh sách đơn dạng tóm tắt, phân trang, rút gọn kết quả tool theo thứ tự mới

> **Trạng thái:** phát hành ngày 2026-11-15; **đã thực thi**, PR [#113](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/113) merge `e2975fa`, deploy cùng #114. **Executor đọc bộ tài liệu này tại chỗ trên máy owner**, ở `D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/.claude/worktrees/cai-nay-la-sao-bddcef/docs/phase_role_aware_ops/W6_4_1_context_fix/`. PR đưa thư mục này lên `main` đi sau, cùng batch tài liệu. Code thì lấy từ `origin/main` tại `fdaa2c3` hoặc mới hơn.
> **Executor:** Gemini 4 Hydrogen, chạy trong Antigravity trên máy owner.
> **Người kiểm chứng:** Claude, một lượt, theo tiêu chí ở [02](02_PHAM_VI_VA_TIEU_CHI.md). **Owner quyết định merge.**
> **Quyết định áp dụng:** [§32](../W0_OWNER_DECISION_DELTA_2026-10-29.md#32-w64-roadmap-update-2026-11-15) W6.4-D9a và W6.4-D15; F13 và F44 trong [W6 backlog](../W6_BACKLOG_2026-11-06.md).

## Vì sao có bản sửa này

Smoke production ngày 2026-11-15 sau khi deploy W6.4.0: khách hỏi "liệt kê các đơn của tôi", tài khoản có 3 đơn, nhưng model chỉ thấy 2. Kết quả `list_orders` vượt ngân sách 5.200 ký tự của một kết quả tool, và bước rút gọn cắt mất nguyên đơn thứ 3 (F44). Gốc lỗi có hai phần:

1. Mọi ngân sách cắt chữ tính theo biến `RETAILOPS_MODEL_CONTEXT_TOKENS`, mặc định 16.384, bất kể model thật có cửa sổ bao nhiêu. Trần tổng `MAX_CHARACTERS = 36000` trong `agent_protocol.py` lại cố định, không tăng theo biến này (F13).
2. `list_orders` trả nguyên hồ sơ đầy đủ của từng đơn (thanh toán, vận chuyển, điều kiện xử lý, voucher…), trong khi để liệt kê thì model chỉ cần nhận diện đơn. Bước rút gọn lại cắt chuỗi và cắt phần tử danh sách cùng lúc, nên ở nấc mạnh chỉ còn 2 phần tử.

Chi tiết và vị trí code ở [01](01_HIEN_TRANG_VA_NGUYEN_NHAN.md).

## Thứ tự đọc

| Tệp | Nội dung |
|---|---|
| [01_HIEN_TRANG_VA_NGUYEN_NHAN.md](01_HIEN_TRANG_VA_NGUYEN_NHAN.md) | Bằng chứng, vị trí code, những chỗ khác đang đọc kết quả `list_orders` |
| [02_PHAM_VI_VA_TIEU_CHI.md](02_PHAM_VI_VA_TIEU_CHI.md) | 6 hàng việc và tiêu chí chấp nhận của từng hàng |
| [03_THIET_KE_CHI_TIET.md](03_THIET_KE_CHI_TIET.md) | Trường của bản tóm tắt, tham số phân trang, mô tả tool nguyên văn, thuật toán rút gọn, công thức trần ký tự |
| [04_TEST_VA_KIEM_TRA.md](04_TEST_VA_KIEM_TRA.md) | Test phải viết trước, lệnh kiểm không hồi quy, các số đo phải ghi, mẫu báo cáo |
| [05_PROMPT_CHO_ANTIGRAVITY.md](05_PROMPT_CHO_ANTIGRAVITY.md) | Khối prompt owner dán vào Antigravity |
| [06_SAU_KHI_MERGE.md](06_SAU_KHI_MERGE.md) | Việc của Claude và owner sau khi merge: deploy, `api.env`, smoke, Colab |

Executor ghi báo cáo vào `docs/phase_role_aware_ops/W6_4_1_EXECUTION_REPORT_2026-11-15.md` **trên nhánh của mình**, không ghi vào thư mục handoff.

## Nguyên tắc

- Tạo nhánh mới `phase-r1-w6-4-1` từ `origin/main` (tại `fdaa2c3` hoặc mới hơn). Không theo dõi `main`.
- **Bộ handoff này chỉ để đọc.** Không chép, không sửa, không commit các tệp trong thư mục handoff hay trong worktree `.claude/worktrees/cai-nay-la-sao-bddcef`. §32 (W6.4-D9a, D15) và F44 cũng chỉ có trong worktree đó, chưa có trên `main`.
- Với hàng 1–5: viết test trước, chạy trên code chưa sửa để thấy FAIL, ghi lại dòng lỗi, rồi mới sửa.
- Không sửa ca trong `evals/suites/` (đã đóng băng, W6.3-D7). SHA-256 của 12 tệp phải khớp bảng trong `evals/suites/README.md`.
- Không sửa `SYSTEM` trong `agent_protocol.py`: chỉ còn khoảng 100 ký tự trống so với trần 6.400. Hướng dẫn cho model nằm trong **mô tả tool**.
- Không sửa `answer_check`, rào an toàn, luật, dữ liệu demo, kho chính sách.
- Không migration, không thêm thư viện, không đổi workflow CI hay deploy.
- Gặp quyết định chưa có trong tài liệu thì **dừng và hỏi owner**.

## Cấm

- merge; push vào `main`; force-push, rebase, reset, stash;
- đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e;
- truy cập EC2, SSM, DB production, Colab, model thật hay API trả phí, dữ liệu khách hàng;
- thêm thư viện vào requirements;
- sửa ca trong `evals/suites/`;
- dán khóa, token, URL database vào báo cáo hay log.
