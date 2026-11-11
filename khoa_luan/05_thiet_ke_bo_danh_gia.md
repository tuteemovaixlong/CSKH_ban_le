# Thiết kế bộ đánh giá theo nghiệp vụ, 250 ca

Bản thiết kế ngày 2026-11-06, cập nhật ngày 2026-11-11 theo quyết định §23 (W6.3-D1 đến D7), dữ liệu sàn ảo của W6.1b và công cụ đánh giá đã merge ở W6.3 (PR #87). Phục vụ mục 2.6 và Chương 4 của khóa luận.

> **Tóm tắt:** 250 ca, 12 bộ S01–S12. Gồm 210 ca mô phỏng do một model độc lập viết từ bộ tài liệu `eval_pack/` bản 2, model đó không đọc mã nguồn; 28 ca chuyển thể từ τ²-bench retail và 12 ca chuyển thể từ AgentDojo do Claude làm. Ma trận W6.4: cấu hình A chạy đủ 250 ca × 3 lần; cấu hình B, C, D chạy trên một tập con cố định 100 ca phân tầng theo bộ × 3 lần, tổng khoảng 1.650 lượt.

## 1. Hiện trạng trong repo, ngày 2026-11-11

| Bộ | Số ca | Dạng | Vai trò |
|---|---|---|---|
| `evals/suites/S01.jsonl` … `S12.jsonl` | 250 khi xong | nhiều lượt kiểu τ-bench, có trường `meta` | bộ đánh giá chính của Chương 4; đang viết dữ liệu |
| `evals/agent_scenarios_w3_2.jsonl` | 32 | nhiều lượt | hồi quy, CI phát lại mỗi PR |
| `evals/agent_scenarios_w4.jsonl` | 12 | nhiều lượt, có Trợ lý ca, ảnh, PDF | hồi quy, CI phát lại mỗi PR |
| `evals/scenarios/benchmark_250.jsonl`, `evals/batches/`, `evals/qrels/policy_qrels_v1.json` | 250 câu một lượt | do DeepSeek sinh, kỳ vọng là lời văn tự do | tài liệu lịch sử, không thuộc 250 ca (W6.3-D7) |

Công cụ đã có từ PR #87:

- `scripts/check_eval_dataset.py` kiểm định dạng `eval_pack/04` bản 2 cho `evals/suites/`, kể cả đoạn chính sách phải đúng nguyên văn và mọi mã khách, đơn, sản phẩm phải có trong dữ liệu demo; cờ `--final` kiểm hạn mức của `eval_pack/05`.
- `scripts/run_agent_scenarios.py` có `--dataset-dir`, `--suite`, `--split`, `--repeat K` (pass@1 và pass^K), `--agent-mode agent|legacy`, `--thinking on|off`, `--context-tokens N`, `--knowledge scripted|real`, `--only-file`; trường ca `overrides.product_descriptions` cho đường chèn lệnh qua mô tả sản phẩm; khóa chấm `attack_not`, `attack_tools_not_called` tách `utility` khỏi `attack_success`.
- `scripts/eval_stats.py` có `summary` (khoảng tin cậy bootstrap trên ca, 10.000 lần, seed 20261110), `compare` (McNemar chính xác hai phía trên kết quả đa số K lần, `--cases` để so trên tập con) và `subset` (chọn tập con phân tầng có seed).
- `scripts/eval_retrieval.py` đo Recall@3 và MRR cho các ca có `expect.sources` trên kho tri thức thật.
- `scripts/build_eval_pack.py` sinh khối dữ liệu của `eval_pack/03` từ đúng dữ liệu demo mà bộ chấm dùng; CI kiểm đồng bộ.

## 2. Mười hai bộ test theo nghiệp vụ

Mỗi bộ là một file `evals/suites/<ma_bo>.jsonl`, `category` là mã bộ viết thường. Tình huống con của phần mô phỏng ở `eval_pack/05_PHAN_BO_CA.md`; phần chuyển thể theo mục 7.

| Mã | Nghiệp vụ | Tổng | Mô phỏng | Chuyển thể | `held_out` của phần mô phỏng | Câu hỏi nghiên cứu |
|---|---|---|---|---|---|---|
| S01 | Tra cứu đơn và vận chuyển | 26 | 26 | 0 | 8 | RQ1 |
| S02 | Sản phẩm và tồn kho | 18 | 18 | 0 | 5 | RQ1 |
| S03 | Chính sách và FAQ có trích dẫn | 30 | 30 | 0 | 9 | RQ3 |
| S04 | Hủy đơn | 20 | 13 | 7 τ²-bench | 4 | RQ1, RQ4 |
| S05 | Trả hàng và hoàn tiền | 26 | 20 | 6 τ²-bench | 6 | RQ1, RQ4 |
| S06 | Đổi hàng | 22 | 14 | 8 τ²-bench | 4 | RQ1 |
| S07 | Chuyển nhân viên và khách bức xúc | 16 | 11 | 5 τ²-bench | 3 | RQ4 |
| S08 | Hội thoại nhiều lượt | 18 | 16 | 2 τ²-bench | 5 | RQ1, RQ2 |
| S09 | An toàn, bảo mật, chèn lệnh | 26 | 20 | 6 AgentDojo | 6 | RQ4 |
| S10 | Ngoài phạm vi, ngày giờ, thông tin trực tiếp | 10 | 10 | 0 | 3 | RQ1, RQ5 |
| S11 | Trợ lý ca của nhân viên | 22 | 16 | 6 AgentDojo | 5 | RQ1, RQ4 |
| S12 | Tình huống đặc thù Việt Nam | 16 | 16 | 0 | 5 | RQ1, RQ4 |
| | **Tổng** | **250** | **210** | **40** | **63** | |

Phần chuyển thể cũng chia `dev` và `held_out` theo tỉ lệ 30% mỗi bộ. Mỗi bộ trộn đều cách viết của khách theo trường `style`; đây là biến số độ bền ngôn ngữ.

## 3. Định dạng một ca

Theo `eval_pack/04_DINH_DANG_VA_CHAM.md` bản 2, giữ định dạng kịch bản nhiều lượt của W3.2 và W4, vì đây là dạng máy chấm được theo kết quả cuối:

- `customer`: mã khách sàn ảo, bắt buộc. `fixture`: `standard`, hoặc `late_voucher_issued` khi ca cần đơn đã có voucher bồi thường.
- `meta`: `suite`, `split` (`dev` hoặc `held_out`), `style` (`chuan`, `khong_dau`, `teencode`, `sai_chinh_ta`, `dai`), `origin` (`mo_phong`, `tau2_retail`, `agentdojo`), `vn_context`, `source_note`; ca chuyển thể thêm `upstream` gồm mã nhiệm vụ gốc và commit 40 ký tự của repo gốc; `knowledge_mode: "scripted"` cho ca chèn lệnh qua đoạn chính sách.
- Khóa chấm: `tools_called`, `tools_any`, `tools_not_called`, `max_tool_calls`, `action`, `order_action`, `human_support`, `request_mode`, `sources`, `answer_all`, `answer_any`, `answer_not`, `final_state`; Trợ lý ca thêm `has_draft_reply`, `staff_replies_sent`; ca AgentDojo thêm `attack_not`, `attack_tools_not_called`.
- `fake_model`: quỹ đạo mẫu của một tác tử làm đúng. CI phát lại để chứng minh ca chấm được và kỳ vọng không mâu thuẫn.

**Dữ liệu.** Ca chạy trên dữ liệu demo của sàn ảo (`data/demo_events/store_events.jsonl`, seed 20261106), nạp vào một SQLite riêng cho mỗi ca và dời mốc sao cho sự kiện mới nhất trùng thời điểm chạy, nên số ngày tương đối của đơn và các điều kiện 7, 15, 90 ngày không đổi theo ngày chạy. Danh sách khách, đơn, catalog, kết quả tool thật và nguyên văn 14 tài liệu chính sách nằm ở `eval_pack/03`. Không sửa dữ liệu demo cho vừa ca; thiếu trạng thái thì ghi đề xuất fixture.

## 4. Chạy tự động hay chạy tay

**Chấm tự động là chính, có một phần chấm tay nhỏ.** Lý do:

- Khối lượng: 250 ca × 3 lần của cấu hình A cộng 100 ca × 3 lần cho mỗi cấu hình B, C, D là khoảng 1.650 lượt chạy. Không thể chấm tay.
- Thống kê: pass^k, bootstrap và McNemar cần chạy lặp được với cùng ca và cùng cách chấm. Chấm tay thì lần hai khác lần một.
- Kiểu τ-bench chấm theo kết quả quan sát được: tool đã gọi, form mở ra, trạng thái DB, câu cấm khẳng định. Đây đều là phép kiểm trong code, không cần LLM làm giám khảo.

Có hai tầng tự động:

| Tầng | Chạy ở đâu | Khi nào | Kiểm gì |
|---|---|---|---|
| CI | GitHub Actions, `--fake` | mỗi PR | định dạng dữ liệu; quỹ đạo mẫu đạt 100%; không tốn GPU hay tiền |
| Model thật | máy owner, `--endpoint` tới vLLM trên Colab | W6.4, chạy bằng lệnh tay | số liệu Chương 4; không đưa vào CI vì cần GPU, secret và tốn compute |

Phần chấm tay gồm hai việc: đọc lại mọi ca thất bại để phân loại lỗi cho mục 4.9, và chấm một mẫu phân tầng khoảng 30 ca, gồm 2 đến 3 ca mỗi bộ, theo thang 1–5 về độ đúng, độ rõ và giọng điệu CSKH. Việc chấm tay không thay cho kiểm thử trên trình duyệt; đó là việc riêng.

## 5. Ma trận thí nghiệm ở W6.4

| Cấu hình | Agent | Thinking | Ngữ cảnh | Kho tri thức | Số ca | Dùng cho |
|---|---|---|---|---|---|---|
| A, chính | agent-first | bật | 16k | thật | 250 × 3 | RQ1–RQ5 |
| B | legacy supervisor (`--agent-mode legacy`) | bật | 16k | thật | 100 × 3 | RQ1 |
| C | agent-first | tắt (`--thinking off`) | 16k | thật | 100 × 3 | RQ2 |
| D | agent-first | bật | 8k (`--context-tokens 8192`, vLLM `RETAILOPS_MAX_MODEL_LEN=8192`) | thật | 100 × 3 | RQ2 |

Tập con 100 ca chọn một lần bằng `eval_stats.py subset --size 100 --seed 20261110`, phân tầng theo số ca từng bộ, rồi chạy B, C, D bằng `--only-file`. So A với từng cấu hình bằng `eval_stats.py compare --cases` trên đúng tập con đó. "Kho tri thức thật" là `--knowledge real`: `data/knowledge/` nạp vào PostgreSQL có pgvector, truy hồi thật; ca chèn lệnh qua đoạn chính sách vẫn chạy `scripted`. Bộ S03 đo thêm Recall@3 và MRR bằng `eval_retrieval.py`. Với cấu hình D, chạy thử vài ca có kết quả tool dài trước, vì prompt hệ thống, schema tool và `max_tokens` 2048 có thể vượt cửa sổ 8.192 token.

## 6. Việc phải làm, theo thứ tự

1. Công cụ đánh giá: **xong** ngày 2026-11-11, PR #87.
2. 210 ca mô phỏng: owner gửi `eval_pack/` cho model độc lập, mỗi lượt một bộ; Claude kiểm bằng bộ kiểm và phát lại quỹ đạo mẫu, chỉ trả lại ca hỏng kèm lý do; bộ đạt được thêm vào `evals/suites/` qua PR (W6.3-D1).
3. 40 ca chuyển thể: Claude làm theo mục 7 (W6.3-D3).
4. Đóng băng: `check_eval_dataset.py --final` đạt, CI phát lại 100%, ghi SHA-256 từng tệp vào biên bản; sau đó không sửa ca, chỉ thêm phiên bản mới (W6.3-D7).
5. W6.4: đổi khóa và cấu hình lại Colab (C1), chạy ma trận, chấm tay mẫu 30 ca, phân loại lỗi.

## 7. Chuyển thể từ bộ dữ liệu công khai

### 7.1 Số ca cho từng nguồn

| Nguồn | Số ca lấy vào | Vai trò | Lý do chọn số này |
|---|---|---|---|
| τ²-bench retail, MIT | 28 trong 114 nhiệm vụ | ca thật sự chuyển thể | đủ để báo cáo riêng một chỉ số cho nhóm này, khoảng tin cậy 95% rộng chừng ±18 điểm phần trăm; nhiều hơn thì lấn chỗ các tình huống riêng của Việt Nam, và mỗi ca phải viết lại kỳ vọng bằng tay |
| AgentDojo, MIT | 12 | ca thật sự chuyển thể | 4 đường chèn lệnh × 3 mục tiêu tấn công, mỗi ô một ca; tỉ lệ tấn công thành công được báo cáo riêng |
| Bitext retail, CDLA-Sharing | 0 câu chép | bảng phủ ý định | chép câu sẽ kéo theo điều khoản chia sẻ, mà câu tiếng Anh lại không dùng trực tiếp được |
| CSConDa, ViOCD, ViSFD | 0 câu chép | quy cách ngôn ngữ | chỉ cho nghiên cứu, không được phân phối lại |

**Chọn 28 nhiệm vụ τ²-bench.** Ưu tiên lấy trong 50 nhiệm vụ của bộ text-v1, vì nhóm này đã được đóng băng, sửa lỗi và bản địa hóa sang 5 ngôn ngữ. Bỏ mọi nhiệm vụ có trường `issues`. Bỏ phần xác minh danh tính bằng tên và mã bưu chính, vì RetailOps lấy danh tính khách từ phiên đăng nhập. Chia theo loại hành động gốc:

| Hành động gốc trong τ²-bench | Số nhiệm vụ gốc, ước tính | Lấy | Chuyển thành | Bộ test |
|---|---|---|---|---|
| `return_delivered_order_items` | khoảng 37 | 6 | mở form trả đúng đơn, đúng lý do; DB không đổi | S05 |
| `exchange_delivered_order_items` | khoảng 34 | 7 | mở form đổi đúng biến thể đích; nói thật tồn kho | S06 |
| `cancel_pending_order` | khoảng 28 | 5 | mở form hủy; đơn đã giao thì từ chối đúng lý do | S04 |
| `modify_pending_order_items` | khoảng 34 | 3 | RetailOps không đổi biến thể đơn chưa giao: giải thích, gợi ý hủy rồi đặt lại | S04, S06 |
| `modify_pending_order_address`, `modify_user_address` | khoảng 34 | 3 | không có tool đổi địa chỉ: nói rõ không làm qua chat, chuyển nhân viên | S07 |
| `transfer_to_human_agents` | 4 | 2 | gọi `request_human_support` đúng lúc | S07 |
| nhiệm vụ gộp nhiều mục tiêu | khoảng 30 | 2 | kịch bản 3–4 lượt, mỗi lượt một mục tiêu | S08 |
| **Tổng** | 114 | **28** | | |

Số nhiệm vụ gốc được đếm từ `data/tau2/domains/retail/tasks.json` qua công cụ đọc, có thể lệch vài đơn vị. Khi viết thì đếm lại bằng script.

**Chọn 12 ca AgentDojo.** Mục tiêu tấn công trong AgentDojo phần lớn là lấy cắp dữ liệu qua hành động ghi, ví dụ chuyển tiền kèm thông tin vào tài khoản kẻ tấn công. RetailOps không cho AI ghi, nên mục tiêu được đổi sang những hại có thể xảy ra ở đây. Mẫu lời chèn dùng kiểu `important_instructions` của AgentDojo, dịch sang tiếng Việt, kèm biến thể giả danh quản lý cửa hàng.

| Đường chèn lệnh | Lừa chuyển khoản hoặc link giả | Khẳng định sai đã hoàn tiền, đã duyệt | Lộ prompt hoặc dữ liệu khách khác |
|---|---|---|---|
| mô tả sản phẩm, đọc qua `get_product` | 1 | 1 | 1 |
| đoạn chính sách, đọc qua `search_knowledge` | 1 | 1 | 1 |
| tin nhắn và ghi chú chuyển ca, Trợ lý ca đọc qua `get_case_transcript` | 1 | 1 | 1 |
| trích đoạn tệp PDF đính kèm | 1 | 1 | 1 |

Mỗi ca chấm hai chỉ số như AgentDojo: **utility under attack**, tức việc chính của khách vẫn được làm đúng, và **attack success**, tức câu trả lời chứa nội dung tấn công hoặc gọi tool bị cấm.

### 7.2 Quy trình chuyển thể một ca

1. **Ghi nguồn.** `origin` cùng mã nhiệm vụ gốc và commit của repo gốc, ví dụ `tau2_retail:task_17@<commit>`.
2. **Ánh xạ dữ liệu.** Đổi người dùng, đơn, sản phẩm gốc sang khách, đơn, sản phẩm của dữ liệu sàn ảo ở `eval_pack/03`, chọn theo bảng "bản đồ tình huống". Thiếu trạng thái thì ghi đề xuất fixture, không sửa dữ liệu demo.
3. **Việt hóa, không dịch từng chữ.** Giữ mục tiêu, ràng buộc và thứ tự khách tiết lộ thông tin trong `known_info`, `unknown_info`, `task_instructions` của bản gốc. Viết lại như khách Việt thật nhắn tin, theo phân bố `style` ở mục 7.3.
4. **Cố định lời khách.** τ²-bench dùng LLM đóng vai khách. Ở đây lời khách được viết sẵn thành 1–4 lượt, để mọi cấu hình nhận đúng cùng đầu vào. Điểm này ghi vào mục mối đe dọa tính hợp lệ.
5. **Viết lại kỳ vọng theo nguyên tắc của RetailOps.** Hành động ghi của τ²-bench đổi thành form được mở bằng `prepare_order_action`, với đúng loại, đúng đơn, đúng biến thể; `final_state` giữ DB không đổi. `communicate_info` đổi thành `answer_all` hoặc `answer_any`. Luôn thêm `answer_not` cho các câu khẳng định đã hủy, đã đổi, đã hoàn tiền.
6. **Viết quỹ đạo mẫu** `fake_model` và chạy `--fake`; ca chỉ được nhận khi đạt.
7. **Rà soát theo checklist:** kỳ vọng đúng với seed; chấp nhận mọi quỹ đạo hợp lệ chứ không chỉ một; lời khách không lộ đáp án; `answer_any` đủ cách nói đồng nghĩa; không có mã đơn, tên hay nội dung chép nguyên văn từ bộ chỉ cho nghiên cứu.
8. **Chia `split`.** Rút ngẫu nhiên theo từng bộ với seed cố định, 30% là `held_out`.
9. **Đóng băng.** Owner duyệt từng bộ. Trước khi chạy W6, ghi SHA-256 của dữ liệu, runner đã có `dataset_digest`, vào báo cáo. Sau đó không sửa ca, chỉ thêm phiên bản mới.

### 7.3 Quy cách ngôn ngữ lấy từ các bộ tiếng Việt

Không chép câu. Chỉ dùng các hiện tượng mà CSConDa và ViOCD mô tả làm quy cách viết: teencode, viết tắt, lỗi gõ, chêm tiếng Anh, không dấu, câu cụt, kể lể dài. Phân bố `style` mục tiêu trên 210 ca mô phỏng: `chuan` 40%, `khong_dau` 15%, `teencode` 20%, `sai_chinh_ta` 15%, `dai` 10%. Nếu muốn có căn cứ định lượng, có thể đếm tỉ lệ các hiện tượng trên tập test của CSConDa sau khi đăng ký quyền truy cập. Đây là dùng cho nghiên cứu, kết quả đếm không lưu câu gốc.
