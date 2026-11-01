# Phase R1 — W2 Execution Handoff (Gemini 4 Argon)

> **Trạng thái:** prompt thực thi do owner phát hành ngày 2026-11-01 sau [W2 readiness review](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-11-01-w2-readiness-review) (`READY` cho W2). Không mở `W3–W6`.
> **Quyết định áp dụng:** [§10](W0_OWNER_DECISION_DELTA_2026-10-29.md#10-final-owner-decisions-2026-10-31), [§11.2–§11.3](W0_OWNER_DECISION_DELTA_2026-10-29.md#11-accepted-mechanics-2026-10-31) và **[§13](W0_OWNER_DECISION_DELTA_2026-10-29.md#13-w2-owner-decisions-2026-11-01)**. Chỗ nào §13 nói khác thì theo §13.
> **Nguyên tắc phạm vi:** chỉ làm các mục ở phần 2. Không refactor ngoài phạm vi, không mở finding mới. Gặp quyết định chính sách chưa có trong tài liệu thì **dừng và hỏi owner**.

## 1. Mục tiêu làm việc

- Nhánh mới từ `origin/main`; không commit thẳng vào `main`.
- Không chạy migration trên DB thật; không truy cập EC2/SSM, Colab/LLM hay dữ liệu khách hàng; không deploy. Migration production và deploy W2 làm sau, theo runbook như W1, khi owner duyệt riêng.

## 2. Phạm vi và tiêu chí chấp nhận

| # | Việc phải làm | Tiêu chí chấp nhận (test cô lập) |
|---|---|---|
| 0 | **Vệ sinh vận hành (W2-D7).** Retire `scripts/update_ec2.py`: script phải từ chối chạy và in hướng dẫn đúng, gồm sửa `RETAILOPS_API_ENDPOINT` trong `api.env` rồi tạo lại riêng `web`, và runbook migrate có kiểm soát. Gỡ toàn bộ phần ghép mã từ `/opt/retailops/patches` và phần ghi constraint role. Cập nhật `notebooks/colab_vllm_l4.py` (và `colab_llama_server_gguf.py` nếu cùng mẫu): không nhắc tới `update_ec2.py`; in các lệnh sửa endpoint an toàn; hỗ trợ domain ngrok tĩnh qua secret `NGROK_DOMAIN` (khi có domain thì chỉ dùng token đầu tiên; báo lỗi nếu URL không khớp domain; báo lỗi rõ khi không mở được tunnel nào). Kiểm tra `deploy/source_consistency.py` và tài liệu vận hành có nhắc `update_ec2` để không còn chỉ dẫn sai. Build lại `notebooks/colab_agent.ipynb` nếu nguồn nhúng thay đổi. | Test: chạy `update_ec2.py` thoát mã khác 0 và không ghi file nào; không còn đoạn ALTER constraint hay mount `patches`; `build_agent_notebook.py --check` PASS. |
| 1 | **Business v5 (W2-D3).** Thêm bảng `cases`, `handoff_episodes`, `case_feedback_events` cho cả SQLite và PostgreSQL. Phiên bản business tăng **một bậc** trên mỗi backend (PostgreSQL 4 → 5; SQLite từ phiên bản hiện tại lên bậc kế tiếp); ghi rõ ánh xạ phiên bản trong code. Trường tối thiểu theo §11.2/§11.3: `case_id`, `conversation_id`, `customer_id`, `status` ∈ {`waiting`,`in_progress`,`resolved`}, `holder`, `version`, các mốc timer (chờ khách, hạn nhắc, đã nhắc, hạn đóng, `feedback_prompted_at`), `resolved_reason`, `resolved_at`, `resumed_at`, `resume_count`, `previous_case_id`; episode có định danh riêng và trạng thái `pending`/`resolved`/`customer_closed`. **Dọn hội thoại hết hạn không được cascade xóa case, episode hay feedback.** | Test trên SQLite và mock PostgreSQL: tạo DB mới ra thẳng v5; DB cũ không tự migrate khi khởi động. |
| 2 | **Migration business có kiểm soát** (cùng mô hình `W1-MIG-01`). Khởi tạo store, startup và CLI thường chỉ kiểm tra **read-only**; business chưa v5 thì fail-closed (`503`). Lệnh operator tường minh chạy cho **mọi tenant**, yêu cầu `--confirm-preflight --confirm-backup`, idempotent. **Backfill:** mỗi hội thoại có handoff chưa đóng thành case `waiting` kèm một episode `pending`; các hội thoại khác thành case `resolved` với `resolved_reason='migrated_v5'`. Không xóa dòng `conversation_feedback` cũ. | Test fixture v4 (SQLite và mock PostgreSQL): startup bị chặn và dữ liệu không đổi; lệnh migrate tạo đúng số case và episode; chạy lại không đổi gì. |
| 3 | **Case cho mọi hội thoại (W2-D1).** Tạo hội thoại thì tạo case; API trả `case_id`. Ca chỉ có bot ở `waiting` nhưng không có episode mở thì **không** hiện trên Staff Desk. | Test: hội thoại mới có đúng một case; danh sách Staff Desk không có ca chỉ có bot. |
| 4 | **Yêu cầu gặp nhân viên lưu bền trước khi xác nhận.** Cả ba đường (`/api/feedback` loại `human_handoff`, `customer_message()` ở chế độ nhân viên, tool `request_human_support`) dùng chung một hàm: trong một transaction, đưa case về `waiting`, mở episode mới (tối đa một episode mở mỗi case), rồi mới trả thành công kèm `case_id`/`handoff_id`. Lỗi lưu thì trả lỗi, không được báo "đã kết nối". Bỏ `support_rep` viết cứng trong tool. | Test: lỗi lưu không tạo dòng nào và không trả thành công; gửi trùng không tạo hai episode mở; sau khi resolve, tạo handoff mới mở episode mới và không đụng episode cũ. |
| 5 | **Nhận / trả / đóng ca theo `case_id`.** Endpoint claim (đặt `holder`, sang `in_progress`, tăng `version`, hủy timer) và release. Reply chỉ khi case `waiting`/`in_progress` có episode mở. Resolve chỉ đóng **đúng episode và case được chỉ định**, idempotent, `resolved_reason='staff_resolved'`, bỏ `holder`. Giữ nguyên bảo vệ W1: không đoán UUID, cùng tenant, người thực hiện lấy từ phiên. Chuyển ca (transfer) để W5. | Test: claim tranh chấp chỉ một người thắng (theo `version`); reply/resolve trên ca đã đóng bị chặn; resolve episode cũ không đóng episode mới. |
| 6 | **Danh sách Staff Desk ba nhóm.** API trả Hàng chờ (episode mở, không `holder`), Đang xử lý (có `holder`), Đã xử lý (đã đóng, trong thời hạn lưu). Đếm số chỉ tính ca đang mở. | Test: ca đã đóng không nằm trong Hàng chờ và không được đếm; ca chỉ có bot không xuất hiện. |
| 7 | **Xem ca đã đóng (W2-D2).** Staff và Manager đọc được transcript ca đã đóng: chỉ đọc, cùng tenant, trong thời hạn lưu, ghi audit mỗi lần xem. Reply/resolve vẫn bị chặn. | Test: đọc ca đã đóng trả 200 và có dòng audit; tenant khác hoặc quá hạn lưu bị chặn; reply/resolve trả lỗi. |
| 8 | **Timer (W2-D4, W2-D5, §11.3).** Luồng nền trong `web` quét khoảng 15 giây. Bot gửi xong câu trả lời chờ khách (ca không có `holder`, không chờ nhân viên) thì đặt hạn nhắc +5 phút. Đến hạn: thêm **một** tin nhắc cố định vào transcript và đặt hạn đóng +3 phút. Đến hạn đóng: chuyển `resolved` (`inactivity`) bằng cập nhật có điều kiện theo `version`; job trễ hoặc chạy trùng thì không làm gì. Khách gửi tin thì hủy mọi mốc. Khi mời đánh giá (`feedback_prompted_at`), một timer 5 phút thay thế và đóng ca với `completed`. Thời lượng cấu hình được nhưng production từ chối giá trị ngắn hơn mặc định. | Test với đồng hồ giả: nhắc đúng một lần; đóng đúng mốc; khách trả lời trước hạn hoặc ngay khi worker chạy thì ca vẫn mở; ca có `holder` không bị đóng; chạy worker trùng an toàn; production từ chối giá trị rút ngắn. |
| 9 | **Tiếp tục ca (§11.2).** Khách gửi tin sau khi ca đóng, trong thời hạn lưu: mở lại **đúng `case_id` cũ** (tăng `resume_count`, đặt `resumed_at`, ghi audit `customer_resumed`). Quá hạn lưu thì tạo case mới có `previous_case_id`. Nút "Tiếp tục" trên UI để W5. | Test: mở lại trong hạn giữ nguyên `case_id`; quá hạn thì tạo case mới có liên kết; hai lần mở lại đồng thời chỉ có một lần có hiệu lực. |
| 10 | **Phản hồi hài lòng (§10 OD-03).** Lưu `case_feedback_events` gồm giá trị gốc và nhãn chuẩn hóa: Like hoặc 4–5 sao thành `chosen`, Dislike hoặc 1–3 sao thành `rejected`. Không có phản hồi thì không tạo sự kiện. Xuất JSONL để W3. | Test chuẩn hóa nhãn; gửi phản hồi không đóng ca sớm và không làm mới timer. |
| 11 | **Nối UI tối thiểu, chỉ đủ để tính năng chạy được:** nút gặp nhân viên chờ API thành công rồi mới đổi giao diện; khách đang chat với bot thấy được tin nhắc và trạng thái đã đóng (thăm dò nhẹ khi ca có mốc timer); Staff Desk dùng API mới cho ba nhóm và nút nhận ca, giữ bố cục hiện tại. Không thiết kế lại UI (để W5). Build lại notebook nếu `web/` thay đổi. | Test JS hiện có vẫn PASS; thêm test cho thay đổi ở phía khách nếu có. |

## 3. Ngoài phạm vi

- W3: bảng order-action và outbox (business v6), JSONL, yêu cầu hủy/trả.
- W4: AI theo profile, ngữ cảnh ca cho Staff/Manager.
- W5: nút "Tiếp tục", nút dừng bot (W2-D6), chuyển ca, thiết kế lại Staff Desk, sửa Tool Inspector, đổi nhãn nút mẫu.
- Migration business v5 trên DB thật và deploy W2: làm theo runbook riêng khi owner duyệt.

## 4. Kiểm tra và báo cáo

Chạy và báo đúng số pass/fail/skip:

- `python -m unittest discover -s tests -q`; với PostgreSQL thì dựa vào CI (job `offline` có PostgreSQL thật).
- Các test JS theo `.github/workflows/ci.yml`, chỉ khi có Node thật. Trên máy này `WindowsApps\node.cmd` là shim rỗng, không được dùng.
- `python scripts/build_agent_notebook.py --check`, `python scripts/check_docs_contract.py`, `python scripts/check_deployment_contract.py`, `python scripts/check_live_e2e_contract.py`, `git diff --check`.

Báo cáo gồm: danh sách file đổi theo từng mục 0–11; kết quả từng lệnh; trạng thái DONE/BLOCKED cho từng mục; URL PR và kết quả CI. Thêm một dòng mới vào cột của bạn trong [W1 execution log](W1_EXECUTION_LOG_2026-10-31.md) (ghi rõ là W2), không sửa dòng cũ.

## 5. Sau khi Argon báo cáo

Chỉ chạy **một** lượt kiểm chứng theo tiêu chí ở phần 2. Không mở finding mới ngoài phạm vi, trừ khi chính thay đổi tạo ra lỗi mức BLOCKER. Sau đó owner quyết định merge; migration business v5 và deploy chạy theo runbook có diễn tập như W1.
