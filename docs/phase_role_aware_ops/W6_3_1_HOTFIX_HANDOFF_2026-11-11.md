# Phase R1 — W6.3.1 Hotfix Handoff: chuyển nhân viên thất bại âm thầm, bộ kiểm câu trả lời cắt nhầm, runner chấm lượt rào an toàn

> **Trạng thái:** phát hành ngày 2026-11-11 sau khi Claude kiểm bộ S07 đầu tiên của 210 ca mô phỏng, xem [biên bản](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-11-11-s07-first-suite-check); có hiệu lực khi owner merge §25. Executor: Codex.
> **Quyết định áp dụng:** [§25](W0_OWNER_DECISION_DELTA_2026-10-29.md#25-w631-owner-decisions-2026-11-11); F28, F29 trong [W6 backlog](W6_BACKLOG_2026-11-06.md). Hàng 1 sửa lỗi đang có trên production, nên deploy sau khi merge.
> **Nguyên tắc:** sửa theo quy tắc chung, không thêm nhánh riêng cho câu chữ của ca S07. **Không sửa, không commit** tệp S07: Claude cung cấp tệp ở `E:/hệ thống/S07.jsonl` chỉ để chạy kiểm. Gặp quyết định chưa có trong tài liệu thì **dừng và hỏi owner**.

## 1. Hiện trạng

1. **F28.** `validate_tool` trong `agent_protocol.py` giới hạn mọi tham số tool ở 64 ký tự, trừ `query` và `target_variant`. `request_human_support` có tham số `reason`; model thường ghi lý do dài hơn 64 ký tự, ví dụ "Khách yêu cầu đổi địa chỉ giao hàng cho đơn đang chờ xử lý SIM-O-00115", nên lời gọi bị từ chối với `tool_not_allowed`, không ca nào được tạo. Model vẫn trả lời khách "em đã chuyển cho nhân viên" và `answer_check` không bắt câu này. Trên production chỉ các câu khớp từ khóa của rào an toàn mới thật sự được chuyển người. Kho lưu đã nhận `comment` tới 1.000 ký tự.
2. **F29.** `retailops/workflow/answer_check.py` coi mọi câu có "thời hạn", "hạn đổi", "hạn trả", "hạn bảo hành" là lời hứa chính sách; câu không có `[KB:...]` bị cắt và thay bằng câu ghi chú. Câu dữ kiện có nguồn từ tool của lượt cũng bị cắt: "Đơn SIM-O-1 còn trong hạn trả hàng ạ.", "Đơn SIM-O-1 đang trên đường vận chuyển qua GHN và vẫn trong thời hạn giao dự kiến ạ.", "Đơn của anh/chị còn hạn đổi size 15 ngày ạ." đều bị cắt dù `get_order` vừa trả `eligibility` với `within_return_window`, `return_window_days`, `size_exchange_window_days`, `promised_delivery_by`.
3. **Runner.** Lượt mà rào an toàn trả lời (không gọi model) vẫn bị `scripts/run_agent_scenarios.py` báo "scripted reply(ies) were never asked for: the script is out of date", dù mọi kỳ vọng khác của lượt đều đạt. Model viết ca không biết rào nào sẽ bắt, nên ca không sai.

## 2. Phạm vi và tiêu chí chấp nhận

Nhánh mới từ `origin/main`, không theo dõi `main`. Không migration, không thêm thư viện.

| # | Việc phải làm | Tiêu chí chấp nhận, test cô lập |
|---|---|---|
| 1 | **F28 (W6.3.1-D1).** `validate_tool` nhận `reason` của `request_human_support` dài 1–1.000 ký tự; các tham số khác giữ giới hạn cũ. Thêm vào `answer_check` một loại khẳng định không có căn cứ: câu nói đã chuyển cuộc trò chuyện, yêu cầu hay ca cho nhân viên, bộ phận CSKH hay người thật (ví dụ "em đã chuyển … cho nhân viên", "đã chuyển yêu cầu sang bộ phận") khi không tool nào của lượt trả `status: "escalated_to_human"`; câu đó bị cắt và thêm câu ghi chú: "Em chưa chuyển được cuộc trò chuyện cho nhân viên; anh/chị nhắn \"gặp nhân viên\" để em thử lại ạ." Câu hỏi, câu đề nghị ("em chuyển nhân viên cho anh/chị nhé?", "nếu anh/chị muốn, em chuyển…") không bị cắt. | Test: lời gọi `request_human_support` với `reason` 65, 300, 1.000 ký tự tạo ca chuyển người; 1.001 ký tự bị từ chối. Câu "đã chuyển" bị cắt khi tool lỗi và được giữ khi tool trả `escalated_to_human`; câu đề nghị được giữ. Viết test trước, chạy trên code chưa sửa để thấy FAIL. |
| 2 | **F29 (W6.3.1-D2).** `tool_evidence` thu thêm: tập số ngày từ các trường `return_window_days`, `size_exchange_window_days`, `warranty_window_days` (cùng `warranty_days` đang có); cờ có điều kiện thời hạn khi kết quả tool có một trong `within_return_window`, `within_size_exchange_window`, `within_warranty`; cờ có mốc giao khi có `promised_delivery_by`, `estimated_delivery_at` hoặc `latest_estimated_delivery_at`. Trong `_uncited_policy_promise`, câu chỉ khớp loại thời hạn (không khớp `_FEE`, `_LOGISTICS`) được giữ khi: mọi con số trong câu nằm trong tập số ngày ở trên, hoặc câu không có số và lượt có cờ điều kiện thời hạn hay cờ mốc giao. Câu hứa phí, giao nhận (`_FEE`, `_LOGISTICS`) vẫn phải có trích dẫn như cũ. | Test: ba câu dữ kiện ở mục 1.2 được giữ khi có bằng chứng tool tương ứng và vẫn bị cắt khi lượt không có tool nào; "Shop miễn phí ship đổi size lần đầu ạ." vẫn bị cắt; "đổi trong 30 ngày" vẫn bị cắt khi tool chỉ có 7, 15, 90. Các test hiện có của `answer_check` vẫn đạt. Viết test trước, chạy trên code chưa sửa để thấy FAIL. |
| 3 | **Runner (W6.3.1-D3).** Ở `--fake`, lượt có `model_calls` bằng 0 (rào an toàn trả lời) không bị báo lỗi vì còn bước quỹ đạo chưa dùng; mọi kỳ vọng của lượt vẫn được chấm như cũ. Báo cáo ghi `rail_answered: true` cho lượt đó. | Test với ca tổng hợp: lượt bị rào chặn, kỳ vọng `human_support: true`, quỹ đạo có 2 bước, đạt; cùng ca mà kỳ vọng `tools_called: ["get_order"]` vẫn hỏng. 44 kịch bản hồi quy và 4 ca mẫu vẫn đạt. |
| 4 | **Kiểm với S07, không commit.** Chạy `scripts/check_eval_dataset.py <thư mục tạm chứa S07.jsonl>` và runner `--fake --dataset-dir <thư mục tạm>` với tệp `E:/hệ thống/S07.jsonl`. | Trước khi sửa: 5/11 (Claude đã đo). Sau khi sửa: 11/11. Ca nào còn hỏng thì ghi vào báo cáo, không sửa ca. |

Thứ tự bắt buộc với hàng 1, 2, 3: viết test trước, chạy trên code chưa sửa để thấy FAIL, ghi lại dòng lỗi, rồi mới sửa.

## 3. Ngoài phạm vi

- Sửa hoặc commit S07 và mọi ca trong `evals/suites/`; sửa 44 kịch bản hồi quy hoặc nới điều kiện chấm.
- Đổi rào an toàn, system prompt, nội dung `data/knowledge/`.
- Mọi việc của W6.4 trở đi.

## 4. Kiểm tra và báo cáo

Chạy và báo đúng số pass, fail, skip: `python -m unittest discover -s tests -q`; test JS theo `.github/workflows/ci.yml` bằng Node thật; `python scripts/build_agent_notebook.py --check`; `python scripts/build_eval_pack.py --check`; `python scripts/check_docs_contract.py`; `python scripts/check_deployment_contract.py`; `python scripts/check_live_e2e_contract.py`; `python scripts/check_eval_dataset.py`; runner `--fake` cho hai tệp hồi quy, `06_vi_du.jsonl` và S07 theo hàng 4; `git diff --check`.

Báo cáo ghi vào `docs/phase_role_aware_ops/W6_3_1_EXECUTION_REPORT_2026-11-11.md`: file đổi theo từng hàng; bằng chứng FAIL trước khi sửa của hàng 1, 2, 3; kết quả S07 trước và sau; kết quả từng lệnh; DONE hoặc BLOCKED từng hàng; URL PR và kết quả CI. Thêm một dòng mới vào cột của bạn trong [W1 execution log](W1_EXECUTION_LOG_2026-10-31.md), ghi rõ là W6.3.1, không sửa dòng cũ.

**Cấm:** merge; push vào `main`; force-push, rebase, reset, stash; đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e; truy cập EC2, SSM, DB production, Colab hoặc LLM thật, dữ liệu khách hàng; thêm thư viện; commit hoặc sửa S07.

## 5. Sau khi báo cáo

Chỉ chạy **một** lượt kiểm chứng theo tiêu chí ở mục 2. Owner quyết định merge. Deploy thường, không migration; smoke trên trình duyệt: "đơn `<mã đơn>` của tôi nhập nhầm địa chỉ, đổi giúp tôi" phải tạo ca chuyển nhân viên thật (Staff Desk thấy ca), không chỉ có câu "đã chuyển".
