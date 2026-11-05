# Phase R1 — W4.1 Hotfix Handoff (Staff Desk polling và giới hạn request)

> **Trạng thái:** prompt thực thi do owner phát hành ngày 2026-11-05, sau khi owner kiểm thử W4 trên production. Hotfix nhỏ, chỉ sửa code và test. Không có migration, không đổi schema, không mở W5–W6.
> **Nguyên tắc:** chỉ làm 3 mục ở phần 2. Gặp quyết định chính sách chưa có trong tài liệu thì **dừng và hỏi owner**.

## 1. Lỗi owner gặp trên production

1. **Staff Desk tự làm phiên của chính mình bị chặn 429.**
   - Mỗi phiên đăng nhập chỉ được 60 request mỗi phút: `self.control.rate('session:'+sid, 60)` trong `retailops/identity/persistent.py`. `PostgresSessions` kế thừa lớp này.
   - Khi Staff Desk đang mở và đã chọn một ca chưa đóng, `pollStaffDesk()` trong `web/app.js` chạy 2,5 giây một lần. Mỗi lần gửi 3 request: transcript, yêu cầu đơn hàng (thêm từ W3, commit `320fa6d`) và hàng đợi.
   - Như vậy riêng việc để Staff Desk mở đã tốn khoảng 72 request mỗi phút. Chưa kể polling bộ đếm giờ của ca (5 giây), tiến trình lượt chat (3 giây) và tiến trình Trợ lý ca (2 giây). Kết quả: chat và Trợ lý ca của cùng phiên nhận `429 rate_limited`.
2. **Nút bị khóa hiện con trỏ "đang chờ".** Quy tắc chung `button:disabled { cursor: wait; }` trong `web/styles.css` làm mọi nút bị khóa (ví dụ nút Trợ lý ca khi chưa nhận ca) trông như app đang treo.

## 2. Phạm vi và tiêu chí chấp nhận

| # | Việc phải làm | Tiêu chí chấp nhận (test cô lập) |
|---|---|---|
| 0 | **Giảm nhịp polling Staff Desk.** Đổi chu kỳ `pollStaffDesk` từ 2.500 ms sang 5.000 ms, khai báo bằng một hằng số có tên (ví dụ `STAFF_DESK_POLL_MS`). Không đổi các polling khác, không đổi nội dung mỗi lần poll. | Test JS: `startStaffDeskPolling()` đăng ký `setInterval` với đúng 5.000 ms. Các test JS hiện có vẫn PASS. |
| 1 | **Nâng giới hạn mỗi phiên.** Đổi giới hạn `session:` trong `retailops/identity/persistent.py` từ 60 lên 120 request mỗi phút, khai báo bằng hằng số có tên kèm chú thích lý do (Staff Desk, bộ đếm giờ và tiến trình cùng chạy trên một phiên). Giữ nguyên giới hạn đăng nhập (`login`, 15 mỗi phút). Không đổi `retailops/identity/demo.py`. | Test: cùng một phiên gọi 120 request trong một cửa sổ phút thì không bị chặn, request thứ 121 nhận `429 rate_limited`; sang phút mới thì gọi lại được. `test_http_headroom` vẫn PASS. |
| 2 | **Con trỏ của nút bị khóa.** Đổi `button:disabled { cursor: wait; }` thành `cursor: not-allowed`, giữ `opacity: .6`. Nút đang chạy thật (có trạng thái riêng) không thuộc phạm vi mục này. | Test: `web/styles.css` không còn `cursor: wait` trong quy tắc `button:disabled`. |

Build lại `notebooks/colab_agent.ipynb` nếu bundle nhúng file web.

## 3. Ngoài phạm vi

- Gộp các request polling thành một endpoint, hoặc đổi kiến trúc polling: để W5.
- Thay đổi quyền dùng Trợ lý ca. Theo W4-D1, Staff phải nhận ca trước; Manager dùng được ngay.
- Bất kỳ thay đổi nào về provider model, Colab hay DeepSeek.

## 4. Cấm

Merge; push vào `main`; force-push, rebase, reset, stash; đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e; truy cập EC2/SSM, DB production, Colab hoặc LLM thật, dữ liệu khách hàng.

## 5. Kiểm tra và báo cáo

Chạy và báo đúng số pass/fail/skip: `python -m unittest discover -s tests -q` (chạy bằng `discover`); test JS theo `.github/workflows/ci.yml` bằng Node thật; `python scripts/build_agent_notebook.py --check`; `python scripts/check_docs_contract.py`; `python scripts/check_deployment_contract.py`; `git diff --check`.

Báo cáo gồm: file đổi theo từng mục 0–2; kết quả từng lệnh; DONE/BLOCKED từng mục; URL PR và kết quả CI. Thêm một dòng mới vào cột của bạn trong [W1 execution log](W1_EXECUTION_LOG_2026-10-31.md) (ghi rõ là W4.1), không sửa dòng cũ.

## 6. Sau khi báo cáo

Chỉ chạy **một** lượt kiểm chứng theo tiêu chí ở phần 2. Owner quyết định merge. Deploy không cần migration: bật cờ deploy, chạy workflow, tắt cờ, rồi smoke, giống W3.1.
