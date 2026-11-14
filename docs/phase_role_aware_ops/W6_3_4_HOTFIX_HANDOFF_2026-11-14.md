# Phase R1 — W6.3.4 Hotfix Handoff: câu "không thể vừa … vừa …" bị cắt; không đổi được sang phân loại đơn đang giữ; PDF giả lập chỉ cho model đọc khoảng 60 ký tự mỗi trang

> **Trạng thái:** phát hành ngày 2026-11-14 sau khi Claude kiểm 40 ca chuyển thể, xem [biên bản](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-11-14-adapted-cases-check-and-w634-readiness). Có hiệu lực khi owner merge §29. Executor: Codex.
> **Quyết định áp dụng:** [§29](W0_OWNER_DECISION_DELTA_2026-10-29.md#29-w634-owner-decisions-2026-11-14); F35, F36, F37 trong [W6 backlog](W6_BACKLOG_2026-11-06.md).
> - F35 và F36 là lỗi hệ thống, đang có trên production.
> - F37 chỉ nằm ở bộ chấm, nhưng làm mất giá trị các ca có PDF khi đo bằng model thật ở W6.4.
>
> **Thứ tự:** tạo nhánh từ `origin/main` **sau khi** PR chứa handoff này merge. PR đưa 40 ca chuyển thể vào `evals/suites` chờ hotfix này merge, vì CI sẽ trượt ca `s06_017` nếu F36 chưa sửa.
> **Nguyên tắc:**
> - Sửa theo quy tắc chung, không thêm nhánh riêng cho câu chữ của ca.
> - **Không sửa, không commit** các tệp ca chuyển thể; chúng chỉ dùng để kiểm.
> - Gặp quyết định chưa có trong tài liệu thì **dừng và hỏi owner**.

## 1. Hiện trạng

1. **F35. Bộ kiểm câu trả lời đọc "vừa" sau phủ định thành "vừa mới làm xong".**
   - Trong `retailops/workflow/answer_check.py`, các mẫu `_CLAIMS` coi `(đã|vừa)` đứng trước động từ hủy, trả, đổi, hoàn tiền, gửi yêu cầu là lời khẳng định đã làm.
   - "vừa" trong cấu trúc "không thể vừa X vừa Y" lại là "đồng thời", nên câu từ chối đúng bị cắt và thay bằng câu ghi chú "Em chưa thực hiện thay đổi nào…".

   Claude đã thử `check_final_answer(câu, [])` trên `main` `3acea3b`; các câu sau đều bị cắt:
   - "Dạ mỗi đơn hàng chỉ có thể mở một yêu cầu tại một thời điểm nên đơn SIM-O-00091 chưa thể vừa gửi yêu cầu trả vừa gửi yêu cầu đổi cùng lúc ạ."
   - "Dạ đơn SIM-O-00091 không thể vừa trả hàng vừa đổi size cùng lúc ạ."
   - "Đơn SIM-O-00079 không thể vừa đổi size vừa hoàn tiền ạ."
   - "Yêu cầu trả và yêu cầu đổi của đơn này chưa thể vừa gửi cùng lúc ạ."

   Ca `s05_022` (τ²-bench retail/19) trượt vì lỗi này: khách xin vừa trả vừa đổi trong một đơn, mà luật 6 chỉ cho một yêu cầu mỗi đơn.
2. **F36. Không đổi được sang một phân loại mà đơn đang giữ.**
   - Đơn SIM-O-00079 giữ hai phân loại của P-501 là Trắng · Size L và Đen · Size L. `_exchange_variants_in_tx` (`retailops/business/store.py`) đánh dấu cả hai là `is_current`.
   - `match_variants` (`retailops/business/variants.py`) không bao giờ chọn biến thể `is_current`. Kiểm tra phía server trong `_create_order_action_request_in_tx` cũng chặn bằng `target_is_current_variant`, và form của khách lẫn của nhân viên (`web/app.js`) khóa lựa chọn đó.
   - Hệ quả: khách xin đổi chiếc trắng "sang giống chiếc còn lại trong đơn" thì form mở mà không có phân loại đích. Khách cũng không chọn được trên form.

   Ca `s06_017` (τ²-bench retail/49) trượt vì lỗi này. Khách mua hai màu rồi muốn đổi cho giống nhau là chuyện thường gặp với hàng thời trang.
3. **F37. PDF giả lập của bộ chấm chỉ cho model đọc khoảng 60 ký tự đầu mỗi trang.**
   - `_make_text_pdf_bytes` (`scripts/run_agent_scenarios.py`) ghi cả trang thành một lệnh `Tj` trên một dòng, trang khổ 420×220.
   - `project_pdf_for_model` (`retailops/business/evidence.py`) đọc bằng `get_text_bounded()`, nên phần chữ tràn khỏi mép phải bị bỏ.

   Claude đã đo bằng `pypdfium2` 5.14.0:
   - ca `s11_011` của `main` chỉ có 73 ký tự trích đoạn; mã số thuế 0399887700 và 0399887766 mà kỳ vọng đòi không tới được model;
   - 3 ca AgentDojo chèn lệnh qua PDF (`s11_020`, `s11_021`, `s11_022`): lời chèn không tới được model.

   `--fake` vẫn đạt vì câu trả lời mẫu viết sẵn. Ở W6.4, model thật sẽ trượt `s11_011` và tỉ lệ tấn công qua PDF ra 0 giả.

   Claude đã thử một bộ sinh mô phỏng, không sửa repo: trang A4, Helvetica 10, khoảng cách dòng 13, mỗi dòng tối đa 80 ký tự, không ngắt ở dấu gạch nối, không cắt từ dài. Kết quả: `s11_011` thấy đủ 296 ký tự và vẫn đạt; lời chèn của 3 ca PDF tới được model. Bản mô phỏng đầu tiên còn ngắt dòng ở dấu gạch nối, nên email `hoso-khach@retailops-archive.com` bị tách đôi và lời chèn coi như mất.

## 2. Phạm vi và tiêu chí chấp nhận

Nhánh mới từ `origin/main`, không theo dõi `main`. Không migration, không thêm thư viện.

Code đổi trong:
- `retailops/workflow/answer_check.py`;
- `retailops/business/variants.py`, `retailops/business/store.py`;
- `retailops_tools.py`, `web/app.js`;
- `scripts/run_agent_scenarios.py`;
- cộng test và notebook sinh lại.

| # | Việc phải làm | Tiêu chí chấp nhận, test cô lập |
|---|---|---|
| 1 | **F35 (W6.3.4-D1).** "vừa" đứng ngay sau dấu hiệu phủ định hoặc không làm được trong cùng mệnh đề ("không", "chưa", "không thể", "chưa thể", "không được", "chưa được") không phải "vừa mới làm". Cấu trúc "vừa X vừa Y" ở dạng khẳng định vẫn là lời khẳng định đã làm. | **Được giữ:** 4 câu ở mục 1.1. Hai câu đang được giữ phải tiếp tục được giữ: "Shop chưa hỗ trợ vừa hủy đơn vừa đặt lại trong cùng một yêu cầu ạ." và "Mỗi đơn chỉ mở được một yêu cầu, nên anh/chị không thể vừa đổi size vừa trả hàng cho đơn này ạ.". **Vẫn bị cắt khi không có bằng chứng:** "Đơn SIM-O-00079 vừa đổi size vừa hoàn tiền xong rồi ạ."; "Em vừa gửi yêu cầu trả vừa gửi yêu cầu đổi cho anh/chị rồi ạ."; "Em vừa hủy đơn SIM-O-00115 cho anh/chị rồi ạ."; "Đơn SIM-O-00115 vừa được hủy thành công ạ."; "Yêu cầu trả hàng của anh/chị vừa được gửi ạ."; "Shop vừa hoàn tiền cho đơn SIM-O-00091 rồi ạ.". Test hiện có của `answer_check` (W6.3.1, W6.3.2) vẫn đạt. Viết test trước, chạy trên code chưa sửa để thấy FAIL. |
| 2 | **F36 (W6.3.4-D2).** Với đơn giữ từ hai biến thể khác nhau của cùng sản phẩm trở lên, mỗi biến thể đơn đang giữ được chọn làm biến thể đích. Đơn chỉ giữ một biến thể (dù số lượng ×2) giữ luật cũ: biến thể đó không làm đích được. Áp dụng thống nhất cho `match_variants`, cờ trong `prepare_order_action` (`retailops_tools.py`), kiểm tra server `target_is_current_variant`, form của khách và form của nhân viên. Biến thể đơn đang giữ vẫn hiện "(đang giữ)". Gợi ý: thêm một trường riêng cho "chọn được làm đích" và giữ nguyên nghĩa của `is_current`; cách làm do executor chọn. Yêu cầu không ghi món nào được đổi; không đổi schema. | Test: `exchange_options` và `case_exchange_options` của SIM-O-00079 cho chọn cả Trắng · Size L lẫn Đen · Size L; của SIM-O-00105 (P-102 ×2 · Đen · Size L) vẫn không cho chọn Đen · Size L. `match_variants` với "Đen · Size L" trên SIM-O-00079 trả về đúng biến thể đó. `prepare_order_action` đổi hàng trên SIM-O-00079 với `target_variant` "Đen · Size L" mở form `other_variant`, nhãn đích Đen · Size L. Server nhận yêu cầu `other_variant` có đích là biến thể đang giữ ở SIM-O-00079; với đơn một biến thể vẫn trả 400 `target_is_current_variant` (test có sẵn trong `tests/test_r1_w3_2_exchange_service.py` vẫn đạt). Test JS: hai form mở được lựa chọn đang giữ cho đơn nhiều biến thể, vẫn khóa cho đơn một biến thể. Viết test trước, thấy FAIL. |
| 3 | **F37 (W6.3.4-D3).** Sửa `_make_text_pdf_bytes` trong `scripts/run_agent_scenarios.py`: dàn chữ trên trang đủ rộng và cao, xuống dòng; mỗi đoạn tách theo `\n` rồi ngắt dòng theo khoảng trắng; **không** ngắt ở dấu gạch nối và **không** cắt từ dài, để link và email còn nguyên. Vẫn chỉ dùng Latin-1; cùng đầu vào cho ra cùng byte. Không đổi `retailops/business/evidence.py`, đường tải PDF thật và helper PDF riêng trong `tests/test_r1_w4_media_pipeline.py`. | Test: một trang 500 ký tự Latin-1, có nhiều đoạn `\n` và hai chuỗi `www.thongtin-xacminh-401.com`, `hoso-khach@retailops-archive.com`. Trích đoạn của `project_pdf_for_model(_make_text_pdf_bytes([trang]), include_pixels=False)` chứa đủ mọi từ của trang (so sau khi gộp khoảng trắng) và chứa nguyên hai chuỗi. Thêm phép thử nhiều trang (3 trang × 500 ký tự): mỗi trang hiện đủ. Chạy hai lần cho ra cùng byte. Ca `s11_011` có trích đoạn chứa "0399887700", "0399887766", "Sao Mai". Viết test trước, thấy FAIL. Test cần `pypdfium2`; máy không có thì ghi rõ và dựa vào CI. |
| 4 | **Kiểm với 40 ca chuyển thể và 210 ca, không commit.** Tạo thư mục tạm, chép `evals/suites/S*.jsonl` vào, rồi **nối nguyên byte** mỗi tệp dưới đây vào cuối tệp bộ tương ứng (thêm `\n` nếu tệp đích chưa kết thúc bằng xuống dòng). Chạy `scripts/check_eval_dataset.py <thư mục> --final` và runner `--fake --dataset-dir <thư mục>`. Riêng tệp bằng chứng F35, chép vào thư mục tạm khác dưới tên `S05.jsonl` rồi chạy runner. | **250 ca:** trên `main` trước khi sửa, `--final` báo `EVAL_DATASET_OK … cases=250` và runner 249/250, chỉ hỏng `s06_017` (F36). Sau khi sửa: 250/250. **Tệp bằng chứng F35:** trước 5/6, hỏng `s05_022`; sau 6/6. **F37:** ghi đoạn `excerpt` mà `get_case_transcript` trả về cho `s11_020`, `s11_021`, `s11_022` trước và sau khi sửa; sau khi sửa phải chứa chuỗi trong `attack_not` của từng ca. Một cách lấy: lớp con của `ScriptedGateway` ghi lại các tin `role == "tool"` rồi gọi `run_scenario`. Ca nào còn hỏng thì ghi câu trả lời thật vào báo cáo, không sửa ca. |

Tệp cho hàng 4, đều ở `D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/.claude/worktrees/cai-nay-la-sao-bddcef/scratch/adapt_pack/`:

| Tệp | Nối vào | SHA-256 |
|---|---|---|
| `accepted/S04_chuyen_the_v1.jsonl` | `S04.jsonl` | `5cc3a4fe85309c58f8d43512c07c4d4f244e1607dedfa6612690610c94e46d23` |
| `accepted/S05_chuyen_the_v2.jsonl` | `S05.jsonl` | `3624b34ec6d6b6e1b2d03cd1ecb486adcae9cd92bd0fbdbfb8f1e71f99a2946a` |
| `accepted/S06_chuyen_the_v2.jsonl` | `S06.jsonl` | `784fb95f4923db151634600cf95f980789c768ad4a28a9987be5cfed05b7816b` |
| `accepted/S07_chuyen_the_v1.jsonl` | `S07.jsonl` | `f657eea30edc155a2e51c230f1e2b9d92d42941733fe6ea51285eaec6de32c65` |
| `accepted/S08_chuyen_the_v1.jsonl` | `S08.jsonl` | `5d19e4d7696ff32ac215623b01779446b00d6380d967c90a50718417081f7813` |
| `accepted/S09_chuyen_the_v2.jsonl` | `S09.jsonl` | `491544061e1cfa593aaec4ad55a7b1772eb065b3544453645dc174a586d9234b` |
| `accepted/S11_chuyen_the_v1.jsonl` | `S11.jsonl` | `6cffe22d935268a76b3ab03562b581c475fd7a197eb0287f766daf6dfc7184ec` |
| `evidence/S05_chuyen_the_v1_F35.jsonl` | riêng, tên `S05.jsonl` | `5b00476dfb366db8470791b698cdbfe153c686df087879991fb84b42d67b18e7` |

Thứ tự bắt buộc với hàng 1, 2, 3: viết test trước, chạy trên code chưa sửa để thấy FAIL, ghi lại dòng lỗi, rồi mới sửa.

## 3. Ngoài phạm vi

- Sửa hoặc commit 40 ca chuyển thể, mọi ca trong `evals/suites/`, 44 kịch bản hồi quy; nới điều kiện chấm.
- Thêm cột ghi món được đổi vào `order_action_requests`, hay mọi thay đổi schema khác.
- Đổi các mẫu khác của `answer_check` ngoài chữ "vừa" sau phủ định.
- Đổi `eval_pack`, system prompt, `data/knowledge/`, đường tải PDF thật, giới hạn trích đoạn 1.500 ký tự của Trợ lý ca.
- Nếu thấy chỗ khác cũng chặn biến thể đang giữ, hay mẫu khác của `answer_check` cũng cắt nhầm câu phủ định, **ghi vào báo cáo**, không sửa.
- Mọi việc của W6.4 trở đi.

## 4. Kiểm tra và báo cáo

Sửa `retailops/`, `retailops_tools.py` hay `tests/` thì sinh lại notebook bằng `python scripts/build_agent_notebook.py`.

Chạy và báo đúng số pass, fail, skip của từng lệnh:
- `python -m unittest discover -s tests -q`
- test JS theo `.github/workflows/ci.yml`, chạy bằng Node thật
- `python scripts/build_agent_notebook.py --check`
- `python scripts/build_eval_pack.py --check`
- `python scripts/check_docs_contract.py`
- `python scripts/check_deployment_contract.py`
- `python scripts/check_live_e2e_contract.py`
- `python scripts/check_eval_dataset.py` và `python scripts/check_eval_dataset.py evals/suites`
- runner `--fake` cho hai tệp hồi quy, `06_vi_du.jsonl`, `evals/suites` (phải 100%) và các tệp ở hàng 4
- `git diff --check`

Báo cáo ghi vào `docs/phase_role_aware_ops/W6_3_4_EXECUTION_REPORT_2026-11-14.md`, gồm:
- tệp đổi theo từng hàng;
- bằng chứng FAIL trước khi sửa của hàng 1, 2, 3;
- kết quả hàng 4 trước và sau, kèm trích đoạn PDF của 3 ca;
- kết quả từng lệnh;
- DONE hoặc BLOCKED từng hàng;
- URL PR và kết quả CI.

Thêm một dòng mới vào cột của bạn trong [W1 execution log](W1_EXECUTION_LOG_2026-10-31.md), ghi rõ là W6.3.4; không sửa dòng cũ.

**Cấm:**
- merge; push vào `main`; force-push, rebase, reset, stash;
- đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e;
- truy cập EC2, SSM, DB production, Colab hoặc LLM thật, dữ liệu khách hàng;
- thêm thư viện;
- commit hoặc sửa các tệp ca ở hàng 4.

## 5. Sau khi báo cáo

Claude chỉ chạy **một** lượt kiểm chứng theo tiêu chí ở mục 2; owner quyết định merge. Sau khi merge, Claude mở PR đưa 40 ca chuyển thể vào `evals/suites`.

Deploy bình thường, không migration, đi cùng W6.3.1–W6.3.3. Smoke trên trình duyệt:
- Với một đơn đã giao giữ hai phân loại của cùng sản phẩm, form đổi cho chọn phân loại còn lại, có ghi "(đang giữ)". Gửi thử rồi để nhân viên từ chối.
- Hỏi "đơn `<mã>` không thể vừa trả vừa đổi được hả shop": câu trả lời giải thích một yêu cầu mỗi đơn, không bị thay bằng câu ghi chú.
- Đóng các ca, yêu cầu tạo ra khi smoke.
