# Phase R1 — W6.3.2 Hotfix Handoff: bộ kiểm câu trả lời cắt nhầm phí ship và trạng thái hoàn tiền của đơn

> **Trạng thái:** phát hành ngày 2026-11-12 sau khi Claude kiểm phần 1 bộ S01, xem [biên bản](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-11-12-s01-part-1-check). Có hiệu lực khi owner merge §26. Executor: Codex.
> **Quyết định áp dụng:** [§26](W0_OWNER_DECISION_DELTA_2026-10-29.md#26-w632-owner-decisions-2026-11-12); F30, F31 trong [W6 backlog](W6_BACKLOG_2026-11-06.md). Cả hai lỗi đang có trên production; deploy cùng W6.3.1 ở lần bật EC2 tới.
> **Nguyên tắc:** sửa theo quy tắc chung, đọc bằng chứng từ kết quả tool như F29 ở [W6.3.1](W6_3_1_HOTFIX_HANDOFF_2026-11-11.md). Không thêm nhánh riêng cho câu chữ của ca S01. **Không sửa, không commit** tệp S01. Gặp quyết định chưa có trong tài liệu thì **dừng và hỏi owner**.

## 1. Hiện trạng

1. **F30.** Trong `retailops/workflow/answer_check.py`, `_FEE` coi mọi câu có "phí ship", "phí vận chuyển", "phí giao" là lời hứa chính sách. Câu không có `[KB:...]` bị cắt và thay bằng `POLICY_NOTE`. Phí ship của một đơn lại là dữ liệu đơn (luật 8 của `eval_pack/03`): `get_order` và `list_orders` trả trường `shipping_fee`. Hai câu sau bị cắt dù `get_order` vừa trả `shipping_fee: 30000`, `amount: 380000`:
   - "Dạ đơn SIM-O-00084 … tổng thanh toán 380.000 VNĐ (đã gồm 30.000 VNĐ phí ship, COD đã thanh toán), hiện đã giao thành công ạ."
   - "Dạ đơn SIM-O-00111 có phí vận chuyển là 30.000 VNĐ và được giao bởi hãng FastShip Nội Địa (FASTSHIP_SIM) ạ."

   Khách hỏi phí ship hay tổng tiền của đơn chỉ nhận được câu ghi chú "Phần phí, giao nhận và thời hạn em chưa có trích dẫn…".
2. **F31.** `_unfounded_claim` chỉ miễn cho chữ "hủy" khi tool cho thấy đơn đã hủy (`Evidence.cancelled`). Câu nói đơn đã được hoàn tiền vẫn bị cắt dù `get_order` trả `payment_status: "refunded"` và `refund_summary` có `latest_status: "completed"`, `refunded_total: 3820000`. Ví dụ: "Khoản thanh toán 3.820.000 VNĐ qua ví điện tử của anh/chị đã được ghi nhận hoàn tiền thành công trên hệ thống nhé." bị thay bằng `CLAIM_NOTE` "Em chưa thực hiện thay đổi nào trên đơn qua chat…", trả lời sai ý khách.

## 2. Phạm vi và tiêu chí chấp nhận

Tạo nhánh mới từ `origin/main`, không theo dõi `main`. Không migration, không thêm thư viện. Code chỉ đổi trong `retailops/workflow/answer_check.py`, cộng test.

| # | Việc phải làm | Tiêu chí chấp nhận, test cô lập |
|---|---|---|
| 1 | **F30 (W6.3.2-D1).** `tool_evidence` thu thêm tập số tiền từ các trường `shipping_fee`, `amount`, `refunded_total`, `pending_total` của mọi kết quả tool trong lượt (số nguyên, không phải bool). Câu khớp `_FEE` **chỉ** qua cụm "phí ship", "phí vận chuyển", "phí giao (hàng)" được giữ khi thỏa đủ ba điều kiện: không khớp nhánh nào khác của `_FEE` (miễn phí, miễn cước, freeship, phí đổi/trả/hoàn, không mất/tốn/tính phí, chịu/trả/hỗ trợ phí); không khớp `_LOGISTICS`; có ít nhất một số tiền và mọi số tiền trong câu đều thuộc tập trên. Số tiền được nhận ở các dạng "30.000", "30000", "30,000", "30k", "30 nghìn"/"30 ngàn", có hoặc không kèm "đ", "VNĐ", "VND". Chữ số nằm trong mã (`SIM-O-00084`) không tính, như `_FACT_ID` ở F29. | Test, mỗi câu kèm kết quả `get_order` giả có `shipping_fee: 30000`, `amount: 380000`: hai câu ở mục 1.1 được giữ; "Phí ship đơn này là 30k ạ." được giữ. Vẫn bị cắt: cùng các câu khi lượt không có tool nào; "Phí ship đơn này là 20.000đ ạ." (số không khớp); "Phí ship do shop chịu hoàn toàn." (không có số); "Đơn được miễn phí ship ạ."; "Phí đổi hàng là 30.000đ ạ." (phí đổi là chính sách). Các test hiện có của `answer_check` vẫn đạt. Viết test trước, chạy trên code chưa sửa để thấy FAIL. |
| 2 | **F31 (W6.3.2-D2).** `Evidence` thêm cờ `refunded`, bật khi một kết quả tool có `payment_status` là `refunded` hoặc `partially_refunded`, hoặc có `refund_summary`/`refund` với `latest_status: "completed"` hoặc `refunded_total` > 0. Khi cờ bật, câu khẳng định chỉ khớp `_CLAIMS` qua động từ hoàn tiền ("hoàn tiền", "hoàn trả", "đã được hoàn") được giữ. Câu có thêm khẳng định khác (hủy khi đơn chưa hủy, đổi, trả hàng, gửi/tạo yêu cầu) vẫn bị cắt. | Test với `get_order` giả có `payment_status: "refunded"`, `refund_summary.latest_status: "completed"`: câu ở mục 1.2 và "Đơn SIM-O-00066 đã được hoàn tiền thành công ạ." được giữ. Vẫn bị cắt: cùng câu khi lượt không có tool; cùng câu khi hoàn tiền `pending` (`refunded_total: 0`, `latest_status: "pending"`, `payment_status: "paid"`); "Đơn đã được hoàn tiền và em đã đổi size cho anh/chị rồi ạ." khi không có bằng chứng đổi; "Em đã hoàn tiền cho anh/chị rồi ạ." khi lượt không có tool. Test hiện có `'Đơn của anh/chị đã được hoàn tiền thành công.'` (không có tool) vẫn bị cắt. Viết test trước, thấy FAIL. |
| 3 | **Kiểm với S01 phần 1, không commit.** Tệp `E:/hệ thống/ai_studio_code (3).txt` có 13 ca; bỏ hai dòng `s01_012`, `s01_013` (đang trả lại model viết ca), chép 11 dòng còn lại vào thư mục tạm dưới tên `S01.jsonl`. Chạy `scripts/check_eval_dataset.py <thư mục tạm>` và runner `--fake --dataset-dir <thư mục tạm>`. | Trước khi sửa: 8/11, hỏng `s01_001`, `s01_003`, `s01_010` (Claude đã đo). Sau khi sửa: 11/11. Ca nào còn hỏng thì ghi câu trả lời thật vào báo cáo, không sửa ca. |

Thứ tự bắt buộc với hàng 1, 2: viết test trước, chạy trên code chưa sửa để thấy FAIL, ghi lại dòng lỗi, rồi mới sửa.

## 3. Ngoài phạm vi

- Sửa hoặc commit S01 và mọi ca trong `evals/suites/`; sửa 44 kịch bản hồi quy hoặc nới điều kiện chấm.
- Nới bộ kiểm `check_eval_dataset.py` cho mã đơn ngoài dữ liệu demo trong `fake_model` (W6.3.2-D3 giữ nguyên quy tắc).
- Đổi `POLICY_NOTE`, `CLAIM_NOTE`, rào an toàn, system prompt, nội dung `data/knowledge/`.
- Ghi chú không chặn của W6.3.1 ("chuyển cho nhân viên giao hàng").
- Mọi việc của W6.4 trở đi.

## 4. Kiểm tra và báo cáo

Chạy và báo đúng số pass, fail, skip của từng lệnh:
- `python -m unittest discover -s tests -q`
- test JS theo `.github/workflows/ci.yml`, chạy bằng Node thật
- `python scripts/build_agent_notebook.py --check`
- `python scripts/build_eval_pack.py --check`
- `python scripts/check_docs_contract.py`
- `python scripts/check_deployment_contract.py`
- `python scripts/check_live_e2e_contract.py`
- `python scripts/check_eval_dataset.py` và `python scripts/check_eval_dataset.py evals/suites`
- runner `--fake` cho hai tệp hồi quy, `06_vi_du.jsonl`, `evals/suites` (phải 100%) và S01 theo hàng 3
- `git diff --check`

Báo cáo ghi vào `docs/phase_role_aware_ops/W6_3_2_EXECUTION_REPORT_2026-11-12.md`, gồm:
- tệp đổi theo từng hàng;
- bằng chứng FAIL trước khi sửa của hàng 1, 2;
- kết quả S01 trước và sau;
- kết quả từng lệnh;
- DONE hoặc BLOCKED từng hàng;
- URL PR và kết quả CI.

Thêm một dòng mới vào cột của bạn trong [W1 execution log](W1_EXECUTION_LOG_2026-10-31.md), ghi rõ là W6.3.2; không sửa dòng cũ.

**Cấm:** merge; push vào `main`; force-push, rebase, reset, stash; đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e; truy cập EC2, SSM, DB production, Colab hoặc LLM thật, dữ liệu khách hàng; thêm thư viện; commit hoặc sửa S01.

## 5. Sau khi báo cáo

Claude chỉ chạy **một** lượt kiểm chứng theo tiêu chí ở mục 2; owner quyết định merge. Deploy bình thường, không migration, đi cùng W6.3.1. Smoke trên trình duyệt với một đơn của tenant production:
- "đơn `<mã đơn>` phí ship bao nhiêu" phải trả đúng số tiền;
- với một đơn đã hoàn tiền, "đơn `<mã đơn>` hoàn tiền chưa" phải nói đã hoàn, không ra câu "Em chưa thực hiện thay đổi nào…".
