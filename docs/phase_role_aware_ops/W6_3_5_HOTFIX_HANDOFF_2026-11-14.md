# Phase R1 — W6.3.5 Hotfix Handoff: model không biết khi nào phải chuyển nhân viên và luật một yêu cầu mỗi đơn; job deploy bị huỷ vì hết giờ

> **Trạng thái:** phát hành ngày 2026-11-14, sau khi deploy W6.3.1–W6.3.4 và smoke trên production; xem [biên bản](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-11-14-w631-to-w634-production-deploy-record). Có hiệu lực khi owner merge §30. Executor: Codex.
> **Quyết định áp dụng:** [§30](W0_OWNER_DECISION_DELTA_2026-10-29.md#30-w635-owner-decisions-2026-11-14); F39, F40, F41 trong [W6 backlog](W6_BACKLOG_2026-11-06.md).
> - F39 và F40 đang có trên production. Chúng cũng làm W6.4 chấm hỏng 8 ca đã đóng băng vì những luật hệ thống chưa từng nói với model.
> - F41 làm job deploy bị huỷ giữa chừng.
>
> **Thứ tự:** tạo nhánh từ `origin/main` **sau khi** PR chứa handoff này merge. Hotfix phải merge và deploy trước lượt chạy W6.4 đầu tiên.
> **Nguyên tắc:**
> - Sửa hệ thống cho khớp đặc tả `khoa_luan/eval_pack/03_HE_THONG_VA_DU_LIEU.md` mục 2. **Không sửa** ca trong `evals/suites/` (đã đóng băng, W6.3-D7), `eval_pack` hay kho chính sách.
> - Không gọi LLM thật. Hành vi của model được kiểm bằng smoke trên production sau khi deploy (mục 5).
> - Gặp quyết định chưa có trong tài liệu thì **dừng và hỏi owner**.

## 1. Hiện trạng

1. **F39. Model không biết phải chuyển nhân viên khi việc vượt khả năng của chat.**
   - `eval_pack/03` luật 11: chuyển người thật khi khách yêu cầu gặp nhân viên, khi khách quá bức xúc, hoặc khi việc vượt khả năng của chat **như đổi địa chỉ, xuất hóa đơn VAT, khiếu nại shipper báo giao thất bại sai**.
   - Trong `agent_protocol.py`, mô tả tool `request_human_support` chỉ ghi "Escalate conversation to a live human agent when user requests or on severe complaint." `SYSTEM` không nhắc ba việc trên. Kho chính sách không có tài liệu đổi địa chỉ; `invoice_vat.md` chỉ ghi trợ lý "đề nghị" chuyển nhân viên.
   - Smoke production ngày 2026-11-14, `deepseek-flash`: khách gửi "đơn SIM-O-38588564-02 của tôi nhập nhầm địa chỉ, đổi giúp tôi". Model gọi `get_order`, `search_knowledge` (0 tài liệu), `track_shipment`, rồi hỏi "Bạn có muốn mình chuyển cuộc trò chuyện cho nhân viên hỗ trợ…?". Suy luận của model ghi rõ "tool only escalates when user requests". Không có ca nào được tạo.
   - 7 ca đã đóng băng kỳ vọng `final_state.rows.handoff_episodes: 1` cho các việc này:
     - đổi địa chỉ: `s07_011`, `s07_013`, `s07_014`, `s08_016`, `s08_018`;
     - hóa đơn VAT: `s12_013`;
     - shipper báo không liên lạc được dù khách ở nhà: `s01_008`.
2. **F40. Model không biết mỗi đơn chỉ có một yêu cầu đang mở.**
   - `eval_pack/03` luật 6: "Mỗi đơn chỉ có một yêu cầu đang mở." Server đã chặn yêu cầu thứ hai: `retailops/business/store.py` báo "Đơn hàng này đang có một yêu cầu xử lý chưa hoàn tất.", và `retailops_tools.py` trả `This order already has an open order-action request.`
   - Model chỉ biết luật này qua lỗi tool, khi đơn đã có yêu cầu mở. `SYSTEM` và kho chính sách không nhắc tới.
   - Smoke production: "đơn SIM-O-38588564-02 không thể vừa trả vừa đổi được hả shop". Model trả lời kho chính sách "không thấy quy định cho phép hay cấm làm cả hai trên cùng một đơn, nên mình không dám khẳng định".
   - Ca `s05_022` (τ²-bench retail/19) kỳ vọng trợ lý nói một đơn chỉ gửi được một yêu cầu.
3. **F41. Job deploy và job `offline` sát giới hạn thời gian.**
   - Job deploy trong `.github/workflows/deploy-ec2.yml` có `timeout-minutes: 20`. Lần deploy W6.2 (run `42977788010`) mất 19 phút 36 giây.
   - Lần W6.3.1–W6.3.4 (run `43587559102`) bị huỷ ở phút 20 khi lệnh SSM rollout đang chạy. Rollout vẫn xong trên EC2, nhưng live smoke, cập nhật admin console và dọn image không chạy.
   - Job `offline` trong `.github/workflows/ci.yml` có `timeout-minutes: 18`, đã chạy tới 15 phút 29 giây (PR #105).

## 2. Phạm vi và tiêu chí chấp nhận

Nhánh mới từ `origin/main`, không theo dõi `main`. Không migration, không thêm thư viện.

Code đổi trong:
- `agent_protocol.py`: chỉ `SYSTEM` và mô tả tool `request_human_support`;
- `.github/workflows/deploy-ec2.yml`, `.github/workflows/ci.yml`: chỉ dòng `timeout-minutes` nêu ở hàng 3;
- cộng test và notebook sinh lại.

| # | Việc phải làm | Tiêu chí chấp nhận, test cô lập |
|---|---|---|
| 1 | **F39 (W6.3.5-D1).** Thêm vào `SYSTEM` một quy tắc: khi khách yêu cầu một việc chỉ nhân viên làm được thì gọi `request_human_support` **ngay trong lượt đó, không hỏi lại trước**, rồi nói với khách là đã chuyển. Ba việc: đổi địa chỉ hoặc người nhận của đơn; xuất hoặc sửa hóa đơn VAT; khiếu nại shipper báo giao thất bại sai. Câu hỏi chỉ xin thông tin (ai xuất hóa đơn, giờ nhân viên trực, phí ship) không phải yêu cầu chuyển. Sửa mô tả tool `request_human_support` cho cùng nghĩa. Gợi ý câu chữ cho `SYSTEM` (executor được chỉnh): "Call request_human_support in the same turn, without asking first, when the customer asks for something only staff can do: changing an order's delivery address or recipient, issuing or correcting a VAT invoice, or disputing a carrier's false failed-delivery report. Then tell the customer the case has been transferred. Questions that only ask for information, such as who issues invoices, staff hours or fees, are not requests for a human." | Test đọc `SYSTEM` và schema tool trong `agent_protocol.py`: có đủ ba việc, có ý "trong cùng lượt, không hỏi trước" và có ngoại lệ câu hỏi thông tin. Mô tả tool nêu cả ba trường hợp: khách yêu cầu, khiếu nại nặng, việc cần nhân viên. Câu hiện có về đơn `shipping` ("offer transfer to human support" khi không hủy được) giữ nguyên. `validate_tool` và giới hạn `reason` 1.000 ký tự (W6.3.1-D1) không đổi. Test hiện có của `tests/test_agent_protocol.py` vẫn đạt. Viết test trước, chạy trên code chưa sửa để thấy FAIL. |
| 2 | **F40 (W6.3.5-D2).** Thêm vào `SYSTEM`, gần đoạn về `prepare_order_action`: mỗi đơn chỉ có một yêu cầu hủy, trả hoặc đổi đang mở tại một thời điểm. Khách muốn hai yêu cầu trên một đơn (ví dụ vừa trả vừa đổi) thì trợ lý giải thích luật này và hỏi khách chọn yêu cầu nào. Khi tool báo đơn đã có yêu cầu mở, trợ lý nói như vậy và không cố mở yêu cầu thứ hai. Gợi ý câu chữ: "Each order can have only one open cancel, return or exchange request at a time. If the customer wants two requests on one order, for example to return and exchange it, explain this rule and ask which one they want; if a tool reports an open request, say so and do not try to open another." | Test đọc `SYSTEM`: có luật một yêu cầu đang mở cho mỗi đơn, ví dụ trả và đổi, và cách xử lý khi tool báo đã có yêu cầu mở. Không đổi `retailops/business/store.py` hay thông báo lỗi của `retailops_tools.py`. Viết test trước, thấy FAIL. |
| 3 | **F41 (W6.3.5-D3).** `timeout-minutes` của job `deploy` trong `deploy-ec2.yml` đổi từ 20 thành 40; của job `offline` trong `ci.yml` đổi từ 18 thành 30. Không đổi dòng nào khác của hai workflow. | Test đọc hai tệp YAML dạng văn bản, không thêm thư viện: job `deploy` có `timeout-minutes: 40`, job `offline` có `timeout-minutes: 30`. `python scripts/check_deployment_contract.py` vẫn đạt. Viết test trước, thấy FAIL. Không chạy workflow deploy. |
| 4 | **Kiểm không hồi quy.** `--fake` dùng quỹ đạo viết sẵn, không đọc `SYSTEM`, nên mọi bộ ca phải giữ nguyên kết quả. | Runner `--fake` cho hai tệp hồi quy, `06_vi_du.jsonl` và `evals/suites` (250 ca) đều 100%. `python scripts/check_eval_dataset.py evals/suites --final` báo `cases=250`. `sha256sum` 12 tệp `evals/suites/*.jsonl` khớp bảng đóng băng trong `evals/suites/README.md`. |

Thứ tự bắt buộc với hàng 1, 2, 3: viết test trước, chạy trên code chưa sửa để thấy FAIL, ghi lại dòng lỗi, rồi mới sửa.

## 3. Ngoài phạm vi

- Sửa ca trong `evals/suites/`, 44 kịch bản hồi quy, `eval_pack`, kho chính sách `data/knowledge/`.
- Thêm tool, thêm rào cứng chuyển người theo từ khóa, đổi `retailops/workflow/safety.py` hay `answer_check.py`.
- Đổi `GENERAL_SYSTEM`, các câu khác của `SYSTEM` ngoài phần cần thêm, hay chính sách chuyển người của rào an toàn W6.2.
- Đổi các bước khác của workflow, kể cả bước rollout và smoke.
- Nếu thấy luật khác trong `eval_pack/03` mục 2 cũng chưa có trong prompt, **ghi vào báo cáo**, không sửa.
- Mọi việc của W6.4 trở đi.

## 4. Kiểm tra và báo cáo

Sửa `agent_protocol.py` hay `tests/` thì sinh lại notebook bằng `python scripts/build_agent_notebook.py`.

Chạy và báo đúng số pass, fail, skip của từng lệnh:
- `python -m unittest discover -s tests -q`
- test JS theo `.github/workflows/ci.yml`, chạy bằng Node thật
- `python scripts/build_agent_notebook.py --check`
- `python scripts/build_eval_pack.py --check`
- `python scripts/check_docs_contract.py`
- `python scripts/check_deployment_contract.py`
- `python scripts/check_live_e2e_contract.py`
- `python scripts/check_eval_dataset.py` và `python scripts/check_eval_dataset.py evals/suites --final`
- runner `--fake` cho hai tệp hồi quy, `06_vi_du.jsonl` và `evals/suites` (phải 100%)
- `sha256sum evals/suites/*.jsonl` so với bảng đóng băng
- `git diff --check`

Báo cáo ghi vào `docs/phase_role_aware_ops/W6_3_5_EXECUTION_REPORT_2026-11-14.md`, gồm:
- tệp đổi theo từng hàng, kèm nguyên văn câu đã thêm vào `SYSTEM` và mô tả tool mới;
- bằng chứng FAIL trước khi sửa của hàng 1, 2, 3;
- kết quả từng lệnh;
- DONE hoặc BLOCKED từng hàng;
- URL PR và kết quả CI.

Thêm một dòng mới vào cột của bạn trong [W1 execution log](W1_EXECUTION_LOG_2026-10-31.md), ghi rõ là W6.3.5; không sửa dòng cũ.

**Cấm:**
- merge; push vào `main`; force-push, rebase, reset, stash;
- đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e;
- truy cập EC2, SSM, DB production, Colab hoặc LLM thật, dữ liệu khách hàng;
- thêm thư viện;
- sửa ca trong `evals/suites/`.

## 5. Sau khi báo cáo

Claude chỉ chạy **một** lượt kiểm chứng theo tiêu chí ở mục 2; owner quyết định merge.

Deploy bình thường, không migration. Đây cũng là lần đầu chạy workflow với giới hạn 40 phút. Smoke trên trình duyệt:
- "đơn `<mã đơn>` của tôi nhập nhầm địa chỉ, đổi giúp tôi": Staff Desk có ca mới ngay sau lượt này; câu trả lời nói đã chuyển và không bị cắt. Ca này kiểm cả đường đi F28 của W6.3.1.
- "shop xuất hóa đơn VAT công ty cho đơn `<mã đơn>` được không": tạo ca chuyển nhân viên.
- Với một đơn đã giao, "đơn `<mã đơn>` mình muốn vừa trả vừa đổi size được không": giải thích mỗi đơn chỉ một yêu cầu và hỏi khách chọn một.
- "Mấy giờ shop có nhân viên trực?": trả lời giờ trực, **không** chuyển nhân viên.
- Đóng các ca tạo ra khi smoke.
