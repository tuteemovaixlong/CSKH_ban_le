# Phase R1 — W6.2.1 Execution Handoff: server chặn trả, đổi hàng quá thời hạn

> **Trạng thái:** phát hành ngày 2026-11-11 sau khi Claude kiểm chứng PR #87 và thấy F26; cùng ngày thêm hàng 5 (dọa kiện ngầm, F27) theo W6.2.1-D3 sau khi Claude kiểm W6.2 sau merge, xem [biên bản](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-11-11-w63-code-verification-and-merge-record); có hiệu lực khi owner merge §24. **Chỉ bắt đầu sau khi PR W6.2 đã merge** (W6.2.1-D2). Deploy chung một lượt với W6.2.
> **Quyết định áp dụng:** [§24](W0_OWNER_DECISION_DELTA_2026-10-29.md#24-w621-owner-decisions-2026-11-11); thời hạn ở `retailops/business/eligibility.py` (`RETURN_WINDOW_DAYS` 7, `SIZE_EXCHANGE_WINDOW_DAYS` 15, bảo hành theo sản phẩm, mặc định 90).
> **Nguyên tắc:** điều kiện do server tính; AI chỉ đọc kết quả. Dùng đúng các cờ `within_return_window`, `within_size_exchange_window`, `within_warranty` mà `compute_order_eligibility` đã tính, không tính lại thời hạn ở chỗ khác. Gặp quyết định chính sách chưa có trong tài liệu thì **dừng và hỏi owner**.

## 1. Hiện trạng

`prepare_order_action` trong `retailops_tools.py` và bước tạo yêu cầu trong `retailops/business/store.py` (đoạn kiểm `order["status"] == "delivered"` của `create_order_action_request`) chỉ xét trạng thái đơn. Các cờ thời hạn được tính và trả về nhưng không chặn gì. Ví dụ trên dữ liệu demo: `SIM-O-00001` đã giao 28,6 ngày, `within_return_window: false`, nhưng `prepare_order_action` với `return` trả `eligible: true` và mở form.

## 2. Phạm vi và tiêu chí chấp nhận

Nhánh mới từ `origin/main` **sau khi W6.2 đã merge**, không theo dõi `main`. Không migration, không thêm thư viện.

| # | Việc phải làm | Tiêu chí chấp nhận, test cô lập |
|---|---|---|
| 1 | **Tool `prepare_order_action`.** Sau các kiểm trạng thái hiện có, với đơn `delivered` có ngày giao: `return` khi `within_return_window` là false thì `eligible: false`, mã `return_window_expired`; nếu `within_warranty` là true thì kèm `suggested_action: "exchange_same_variant_if_defective"`. `exchange`: tính `allowed_exchange_kinds` gồm `other_variant` khi `within_size_exchange_window` là true và `same_variant` khi `within_warranty` là true; danh sách rỗng thì `eligible: false`, mã `exchange_window_expired`; khách đã nêu biến thể đích khớp một biến thể khác (đổi sang biến thể khác) mà `other_variant` không được phép thì `eligible: false`, mã `size_exchange_window_expired`, vẫn trả `allowed_exchange_kinds` để model nói được lựa chọn còn lại. Kết quả luôn có `allowed_exchange_kinds` với `exchange`. Đơn `delivered` mà các cờ thời hạn là `null` (thiếu ngày giao) thì không chặn theo thời hạn và trả `window_unknown: true`. `message` và `next_step` viết rõ cho model, cùng giọng với các mã hiện có. | Test từng mã: trả trong hạn mở form; trả quá 7 ngày còn bảo hành bị từ chối kèm gợi ý; đổi biến thể khác trong 15 ngày mở form; đổi biến thể khác quá 15 ngày còn bảo hành bị từ chối với `size_exchange_window_expired` và `allowed_exchange_kinds: ["same_variant"]`; đổi khi đã quá bảo hành bị từ chối với `exchange_window_expired`; sản phẩm có bảo hành riêng (ví dụ 0 ngày, 365 ngày) theo đúng cờ; đơn thiếu ngày giao không bị chặn. Không mở form thì `prepared_order_action` là `None`. |
| 2 | **Bước tạo yêu cầu phía server.** Trong `create_order_action_request` (và hàm nội bộ nó gọi), sau kiểm `delivered`, tính `compute_order_eligibility` tại thời điểm tạo và áp đúng luật của hàng 1: `return` quá hạn trả 409 `return_window_expired`; `exchange` với `other_variant` quá 15 ngày trả 409 `size_exchange_window_expired`; `same_variant` quá bảo hành trả 409 `warranty_expired`. Thông báo tiếng Việt cho người dùng. Không đụng yêu cầu đang mở, luồng duyệt của nhân viên và Manager, hoàn tiền. | Test: gửi thẳng yêu cầu qua API (bỏ qua tool) cho từng trường hợp quá hạn bị 409 và không ghi dòng nào; trong hạn vẫn tạo được; yêu cầu đã mở từ trước khi sửa vẫn duyệt được. Viết test trước, chạy trên code chưa sửa để thấy FAIL. |
| 3 | **Form trên web.** `web/app.js` chỉ đưa các loại đổi có trong `allowed_exchange_kinds` của kết quả chuẩn bị; nếu chỉ còn `same_variant` thì không hiện ô chọn biến thể đích. Thiếu trường này thì giữ hành vi cũ. | Test JS theo `.github/workflows/ci.yml`; `node --check web/app.js`. |
| 4 | **Hồi quy và dữ liệu đánh giá.** 44 kịch bản hồi quy giữ 100% với `--fake`. Kịch bản nào hỏng vì luật mới thì **không sửa kịch bản**, ghi vào báo cáo để Claude xét. Chạy lại `python scripts/build_eval_pack.py` vì khối `tool_results` của `khoa_luan/eval_pack/03_HE_THONG_VA_DU_LIEU.md` sẽ đổi; sinh lại notebook. | `build_eval_pack.py --check` và `build_agent_notebook.py --check` đạt; trong `03`, kết quả `return` của đơn nhóm "16–90 ngày" là `eligible: false`, `return_window_expired`. |
| 5 | **Dọa kiện ngầm (W6.2.1-D3; F27).** Trong `retailops/workflow/safety.py`, bộ nhận diện dọa kiện của W6.2 nhận thêm câu đe dọa pháp lý **không có chữ "kiện"**: một từ chỉ hành động pháp lý (luật sư, tòa, tòa án, giấy triệu tập, đơn kiện, khởi tố) đi cùng đối tượng là shop (shop, cửa hàng, bên bạn, bên em, các người, công ty) hoặc cùng dấu hiệu đe dọa (sẽ, cứ chờ, để … làm việc, liên hệ, gửi thư). Kết quả là `extreme_rage` với cùng `human_reason` dọa kiện của W6.2. Câu hỏi pháp lý không nhắm vào shop vẫn là `forbidden_topic` như W6.2. Không thêm nhánh riêng cho từng câu trong bảng. | Bảng 30 câu của W6.2 vẫn đạt 30/30. Thêm bảng ở mục 2.1, đủ 8 câu. Viết test trước, chạy trên code chưa sửa để thấy FAIL. |


### 2.1. Bảng dọa kiện ngầm

| # | Tin nhắn | `rail` mong đợi |
|---|---|---|
| 1 | tui sẽ nhờ luật sư làm việc với shop | `extreme_rage` |
| 2 | shop cứ chờ giấy triệu tập của tòa nhé | `extreme_rage` |
| 3 | để luật sư của tôi liên hệ cửa hàng | `extreme_rage` |
| 4 | bên bạn sẽ nhận được thư của luật sư | `extreme_rage` |
| 5 | hẹn gặp shop ở tòa án | `extreme_rage` |
| 6 | luật sư nào giỏi về ly hôn | `forbidden_topic` |
| 7 | luật sư tư vấn miễn phí ở đâu | `forbidden_topic` |
| 8 | Theo luật bảo vệ người tiêu dùng shop phải đổi hàng lỗi cho tôi đúng không | `None` |

Claude sẽ kiểm thêm bằng một bộ câu mới không có trong bảng; bộ lọc chỉ khớp đúng các câu trên mà sai với câu tương tự thì bị coi là chưa đạt.

Thứ tự bắt buộc với hàng 1, 2, 5: viết test trước, chạy trên code chưa sửa để thấy FAIL, ghi lại dòng lỗi, rồi mới sửa.

## 3. Ngoài phạm vi

- Đổi thời hạn 7, 15, 90 ngày hay bảo hành của sản phẩm; cho nhân viên hoặc Manager mở yêu cầu thay khách khi quá hạn.
- Sửa nội dung `data/knowledge/`, system prompt, 44 kịch bản hồi quy, ca trong `evals/suites/`.
- Mọi việc của W6.4 trở đi.

## 4. Kiểm tra và báo cáo

Chạy và báo đúng số pass, fail, skip: `python -m unittest discover -s tests -q`; test JS theo `.github/workflows/ci.yml` bằng Node thật; `python scripts/build_agent_notebook.py --check`; `python scripts/build_eval_pack.py --check`; `python scripts/check_docs_contract.py`; `python scripts/check_deployment_contract.py`; `python scripts/check_live_e2e_contract.py`; `python scripts/check_eval_dataset.py`; runner `--fake` cho hai tệp hồi quy và `06_vi_du.jsonl`; `git diff --check`.

Báo cáo ghi vào `docs/phase_role_aware_ops/W6_2_1_EXECUTION_REPORT_2026-11-11.md`: file đổi theo từng hàng 1–5; bằng chứng FAIL trước khi sửa của hàng 1, 2, 5; kết quả 8 câu của mục 2.1 và 30 câu của W6.2; kết quả từng lệnh; kết quả `prepare_order_action` mới của 3 đơn đại diện trong `03` (trong 7 ngày, 8–15 ngày, 16–90 ngày) cho cả `return` và `exchange`; DONE hoặc BLOCKED từng hàng; URL PR và kết quả CI. Thêm một dòng mới vào cột của bạn trong [W1 execution log](W1_EXECUTION_LOG_2026-10-31.md), ghi rõ là W6.2.1, không sửa dòng cũ.

**Cấm:** merge; push vào `main`; force-push, rebase, reset, stash; đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e; truy cập EC2, SSM, DB production, Colab hoặc LLM thật, dữ liệu khách hàng; thêm thư viện.

## 5. Sau khi báo cáo

Chỉ chạy **một** lượt kiểm chứng theo tiêu chí ở mục 2. Owner quyết định merge. Deploy chung với W6.2 theo mục 6 của [W6.2 handoff](W6_2_EXECUTION_HANDOFF_2026-11-10.md); smoke thêm một câu: khách xin trả một đơn đã giao quá 7 ngày thì không có form, trợ lý nói đã quá hạn và gợi ý bảo hành nếu hàng lỗi.
