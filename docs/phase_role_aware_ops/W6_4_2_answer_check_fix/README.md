# W6.4.2 — Bộ kiểm câu trả lời không cắt nhầm dữ kiện của tool, giữ tiêu đề, ghi lại câu đã bỏ

> **Trạng thái:** phát hành ngày 2026-11-15; **đã thực thi**, PR [#115](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/115) merge `ece0b0b` (kèm bản sửa `5a09877` của Claude). Phần luật số được W6.4.3 chuyển sang chỉ ghi vết. **Executor đọc bộ tài liệu này tại chỗ trên máy owner**, ở `D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/.claude/worktrees/cai-nay-la-sao-bddcef/docs/phase_role_aware_ops/W6_4_2_answer_check_fix/`. PR đưa thư mục này lên `main` đi sau, cùng batch tài liệu. Code lấy từ `origin/main` tại `3239454` (merge #114) hoặc mới hơn.
> **Executor:** Gemini 4 Hydrogen, chạy trong Antigravity trên máy owner.
> **Người kiểm chứng:** Claude, một lượt, theo tiêu chí ở [02](02_PHAM_VI_VA_TIEU_CHI.md). **Owner quyết định merge.**
> **Quyết định áp dụng:** [§32](../W0_OWNER_DECISION_DELTA_2026-10-29.md#32-w64-roadmap-update-2026-11-15) W6.4-D16; F46 và F47 trong [W6 backlog](../W6_BACKLOG_2026-11-06.md).

## Vì sao có bản sửa này

Smoke production ngày 2026-11-15 sau khi deploy W6.4.1 và #114, ô DeepSeek, tài khoản có 3 đơn. Số liệu model đưa ra đều đúng, nhưng **bộ kiểm câu trả lời** (`retailops/workflow/answer_check.py`) xóa nhầm các dòng đúng:

1. Câu "liệt kê các đơn của tôi": mỗi đơn mất một dòng, cuối câu bị nối "Phần phí, giao nhận và thời hạn em chưa có trích dẫn…". Dòng bị mất có dạng "Tiền hàng 799.000₫ + phí ship 40.000₫ = 839.000₫": giá món (`subtotal`) mà W6.4.0 (F42) mới đưa cho model không được tính là số tiền có bằng chứng (**F46**).
2. Câu "phân tích cả 3 đơn": mất nguyên dòng tiêu đề của đơn thứ 3, nên các dòng của đơn đó nằm dưới tiêu đề đơn thứ 1, người đọc hiểu sai. Tiêu đề có số giờ trễ hoặc số ngày còn lại (ví dụ "trễ hạn 72 giờ"), là số tool tính sẵn (`late_by_hours`, `days_since_delivery`) nhưng bộ kiểm chỉ nhận số ngày của cửa sổ (7, 15, 90). Khi bỏ một dòng, bộ kiểm bỏ luôn nhãn mã đơn (**F47**).
3. Trace chỉ ghi số câu bị bỏ, không ghi câu nào và vì luật nào, nên không truy được nguyên nhân từ production.

Bộ kiểm này chạy trên mọi câu trả lời của 250 ca đo W6.4. Sửa trước lượt đo để điểm không bị kéo xuống bởi lỗi của chính hệ thống. Chi tiết, vị trí code và bảng tái hiện ở [01](01_HIEN_TRANG_VA_NGUYEN_NHAN.md).

## Thứ tự đọc

| Tệp | Nội dung |
|---|---|
| [01_HIEN_TRANG_VA_NGUYEN_NHAN.md](01_HIEN_TRANG_VA_NGUYEN_NHAN.md) | Bằng chứng smoke, cách bộ kiểm hoạt động, bảng tái hiện trên `3239454`, vị trí code |
| [02_PHAM_VI_VA_TIEU_CHI.md](02_PHAM_VI_VA_TIEU_CHI.md) | 5 hàng việc và tiêu chí chấp nhận |
| [03_THIET_KE_CHI_TIET.md](03_THIET_KE_CHI_TIET.md) | Tên trường, công thức, định nghĩa dòng tiêu đề, tên luật, khóa trace |
| [04_TEST_VA_KIEM_TRA.md](04_TEST_VA_KIEM_TRA.md) | Test phải viết trước, lệnh kiểm không hồi quy, bảng số đo, mẫu báo cáo |
| [05_PROMPT_CHO_ANTIGRAVITY.md](05_PROMPT_CHO_ANTIGRAVITY.md) | Khối prompt owner dán vào Antigravity |
| [06_SAU_KHI_MERGE.md](06_SAU_KHI_MERGE.md) | Việc của Claude và owner sau khi merge |

Executor ghi báo cáo vào `docs/phase_role_aware_ops/W6_4_2_EXECUTION_REPORT_2026-11-15.md` **trên nhánh của mình**, không ghi vào thư mục handoff.

## Nguyên tắc

- Tạo nhánh mới `phase-r1-w6-4-2` từ `origin/main` (tại `3239454` hoặc mới hơn). Không theo dõi `main`.
- **Bộ handoff này chỉ để đọc.** Không chép, không sửa, không commit các tệp trong thư mục handoff hay trong worktree `.claude/worktrees/cai-nay-la-sao-bddcef`.
- Hàng 1–4: viết test trước, chạy trên code chưa sửa để thấy FAIL, ghi lại dòng lỗi, rồi mới sửa.
- **Không nới luật.** Lời hứa chính sách không trích dẫn (miễn phí, phí đổi/trả, tận nhà, 2 chiều, "trong 30 ngày"…) vẫn bị bỏ như cũ. Chỉ thêm bằng chứng lấy **từ trường số của tool trong cùng lượt**, và chỉ đổi cách bỏ dòng tiêu đề.
- **Không sửa test cũ** của bộ kiểm (`tests/test_r1_w3_2_answer_check.py`, `tests/test_r1_w6_3_1_hotfix.py`, `tests/test_r1_w6_3_2_hotfix.py`, `tests/test_r1_w6_3_4_answer_check.py`). Test cũ nào đỏ sau khi sửa thì **dừng và hỏi owner**.
- Không đổi câu `POLICY_NOTE`, `CLAIM_NOTE`, `HANDOFF_NOTE`; không đổi hai khóa đang có trong `trace['answer_check']`.
- Không sửa ca trong `evals/suites/` (đã đóng băng, W6.3-D7). SHA-256 của 12 tệp phải khớp bảng trong `evals/suites/README.md`.
- Không sửa `SYSTEM`, mô tả tool, rào an toàn, `enforce_final_answer_grounding`, luật nghiệp vụ, kho chính sách, dữ liệu demo, giao diện web.
- Không migration, không thêm thư viện, không đổi workflow CI hay deploy.
- Gặp quyết định chưa có trong tài liệu thì **dừng và hỏi owner**.

## Cấm

- merge; push vào `main`; force-push, rebase, reset, stash;
- đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e;
- truy cập EC2, SSM, DB production, Colab, model thật hay API trả phí, dữ liệu khách hàng;
- thêm thư viện vào requirements;
- sửa ca trong `evals/suites/`;
- dán khóa, token, URL database vào báo cáo hay log.
