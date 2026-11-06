# Thiết kế bộ đánh giá theo nghiệp vụ, 250 ca

Bản thiết kế ngày 2026-11-06, chưa viết dữ liệu. Số ca từng bộ đã điều chỉnh theo thực trạng trong `06_nghien_cuu_thuc_trang_va_du_lieu.md`. Phục vụ mục 2.6 và Chương 4 của khóa luận, chạy với model thật ở W6.

> **Cập nhật 2026-11-06:** nâng lên **250 ca, 12 bộ**, thêm bộ S12 tình huống đặc thù Việt Nam. Gồm 210 ca mô phỏng, 28 ca chuyển thể từ τ²-bench, 12 ca chuyển thể từ AgentDojo. Số ca từng bộ và bộ tài liệu cho model độc lập sinh 210 ca mô phỏng nằm ở `eval_pack/`; bảng số ca ở `eval_pack/05_PHAN_BO_CA.md` thay cho bảng ở mục 2 dưới đây. Ma trận W6: cấu hình A chạy đủ 250 ca × 3 lần; cấu hình B, C, D chỉ chạy trên một tập con cố định 100 ca phân tầng theo bộ × 3 lần, tổng khoảng 1.650 lượt thay vì 3.000. Phát hiện cần kiểm ở W6: rào chủ đề pháp lý chạy trước rào khách quá bức xúc, nên câu dọa kiện có thể bị từ chối thay vì được chuyển nhân viên; bộ S07 có ca kiểm điểm này.

## 1. Hiện trạng trong repo

| Bộ | Số ca | Dạng | Máy chấm được | Hạn chế |
|---|---|---|---|---|
| `evals/scenarios/benchmark_250.jsonl` | 250 | một lượt, DeepSeek sinh | chỉ tool mong đợi và tool cấm | `expected_outcome` là lời văn tự do; nhiều câu không có mã đơn cụ thể; `run_benchmark_eval.py` chỉ chạy supervisor cũ, không chạy agent-first |
| `evals/agent_scenarios_w3_2.jsonl` | 29 | nhiều lượt kiểu τ-bench | tool, form mở ra, câu bắt buộc và câu cấm, trạng thái DB cuối | ít ca; truy hồi tri thức bị giả lập bằng tài liệu gắn sẵn điểm 0,9 |
| `evals/agent_scenarios_w4.jsonl` | 12 | nhiều lượt, có Trợ lý ca, ảnh, PDF | như trên, thêm số lượt Trợ lý ca, bằng chứng | ít ca |
| `evals/qrels/policy_qrels_v1.json` | 250 truy vấn | nhãn liên quan | Recall@k, MRR | chỉ 75 truy vấn có nguồn liên quan; gắn với benchmark_250 |

`scripts/run_agent_scenarios.py` đã có: chế độ `--fake` cho CI, chế độ `--endpoint` cho model thật, lọc theo `--category`, báo cáo tỉ lệ thành công, tỉ lệ tool call hợp lệ, độ trễ p50/p95. Còn thiếu: chạy lặp k lần để tính pass^k, công tắc agent-first và `legacy` cho RQ1, bật tắt thinking và đổi cửa sổ ngữ cảnh cho RQ2, chế độ dùng kho tri thức thật cho RQ3, và script thống kê bootstrap, McNemar.

Kết luận: bộ mới dùng **định dạng kịch bản nhiều lượt của W3.2 và W4**, vì đây là dạng duy nhất máy chấm được theo kết quả cuối. benchmark_250 giữ làm bộ phụ về độ đa dạng ngôn ngữ, không dùng làm số liệu chính.

## 2. Mười một bộ test theo nghiệp vụ

Mỗi bộ là một file `evals/suites/<ma_bo>.jsonl`, `category` trùng mã bộ.

| Mã | Nghiệp vụ | Số ca | Nội dung chính | Câu hỏi nghiên cứu |
|---|---|---|---|---|
| S01 | Tra cứu đơn và vận chuyển | 16 | xem đơn, liệt kê đơn, giao thất bại, đơn đang giao, đơn không tồn tại, mã đơn viết sai | RQ1 |
| S02 | Sản phẩm và tồn kho | 12 | tìm sản phẩm, thuộc tính, size màu còn hàng, hết hàng, sản phẩm không có | RQ1 |
| S03 | Chính sách và FAQ có trích dẫn | 20 | đổi trả, bảo hành, vận chuyển, thanh toán, voucher sale; 6 ca không có bằng chứng phải từ chối | RQ3 |
| S04 | Hủy đơn | 14 | đơn chờ xử lý hủy được, đơn đã giao, đơn đã hủy, đơn của khách khác, chưa rõ đơn nào, khách nói "xác nhận" trong chat | RQ1, RQ4 |
| S05 | Trả hàng và hoàn tiền | 14 | trả đơn đã giao, quá hạn, hỏi tiến độ hoàn tiền, không tự khẳng định đã hoàn | RQ1, RQ4 |
| S06 | Đổi hàng | 14 | đổi size, đổi màu, biến thể hết hàng, đổi 1-1 hàng lỗi, đổi sang sản phẩm khác | RQ1 |
| S07 | Chuyển nhân viên và khách bức xúc | 10 | đòi gặp người, dọa bóc phốt, dọa kiện, hỏi giờ làm việc không bị chuyển nhầm | RQ4 |
| S08 | Hội thoại nhiều lượt | 12 | "đơn này", "áo đó", đổi chủ đề giữa chừng, sửa lại ý, mở lại ca đã đóng | RQ1, RQ2 |
| S09 | An toàn và bảo mật | 16 | chèn lệnh trực tiếp, chèn lệnh trong tài liệu và mô tả sản phẩm, đòi xem đơn người khác, đòi prompt và khóa API, giả danh nhân viên, chủ đề cấm | RQ4 |
| S10 | Ngoài phạm vi, giờ, thông tin trực tiếp | 8 | câu hỏi kiến thức chung, hỏi ngày giờ, hỏi thời tiết hay tỉ giá | RQ1, RQ5 |
| S11 | Trợ lý ca của Staff và Manager | 14 | tóm tắt, hỏi đáp, soạn nháp có `[KB:...]`, đòi xem ca khác, không lộ thông tin cá nhân, không khẳng định đã duyệt | RQ1, RQ4 |
| | **Tổng** | **150** | | |

Mỗi bộ trộn đều cách viết của khách: có dấu, không dấu, viết tắt, sai chính tả, câu cụt, câu dài kể lể. Đây là biến số độ bền ngôn ngữ, ghi ở trường `style`.

## 3. Định dạng một ca

Giữ đúng định dạng W3.2 và W4, thêm năm trường:

- `suite`: mã bộ, ví dụ `S04`.
- `split`: `dev` hoặc `held_out`. Khoảng 30% mỗi bộ là `held_out`, không được xem khi chỉnh prompt, để tránh rò dữ liệu đánh giá.
- `style`: `chuan`, `khong_dau`, `teencode`, `sai_chinh_ta` hoặc `dai`.
- `source_note`: ca này dựa trên tình huống thực tế nào, ví dụ một điều khoản trong `data/knowledge/` hay một khiếu nại thường gặp.
- `origin`: `mo_phong`, `tau2_retail` hoặc `agentdojo`; hai loại sau ghi kèm mã nhiệm vụ gốc. Nguồn và lý do xem `06_nghien_cuu_thuc_trang_va_du_lieu.md`.

Phần chấm giữ nguyên các khóa đã có: `tools_called`, `tools_any`, `tools_not_called`, `max_tool_calls`, `action`, `order_action`, `safety_rail`, `request_mode`, `sources`, `answer_all`, `answer_any`, `answer_not`, `final_state`. Mỗi ca có `fake_model` là quỹ đạo mẫu của một tác tử làm đúng. CI phát lại quỹ đạo này để chứng minh ca chấm được và kỳ vọng không mâu thuẫn.

Dữ liệu seed hiện có: khách `C-001` với các đơn O-101 chờ xử lý, O-102 đã giao, các đơn O-301 đến O-312, biến thể có tồn bằng 0 như P-102 size S, P-301 size 41, đơn O-202 của khách `C-002`. Fixture `standard` có thêm O-701, O-702, O-705, O-710. Nếu cần trạng thái mới, ví dụ đơn quá hạn trả hàng, thêm fixture có tên riêng, không sửa seed.

## 4. Chạy tự động hay chạy tay

**Chấm tự động là chính, có một phần chấm tay nhỏ.** Lý do:

- Khối lượng: 150 ca × 3 lần lặp × 3 đến 4 cấu hình là từ 1.350 đến 1.800 lượt chạy. Không thể chấm tay.
- Thống kê: pass^k, bootstrap và McNemar cần chạy lặp được với cùng ca và cùng cách chấm. Chấm tay thì lần hai khác lần một.
- Kiểu τ-bench chấm theo kết quả quan sát được: tool đã gọi, form mở ra, trạng thái DB, câu cấm khẳng định. Đây đều là phép kiểm trong code, không cần LLM làm giám khảo.

Có hai tầng tự động:

| Tầng | Chạy ở đâu | Khi nào | Kiểm gì |
|---|---|---|---|
| CI | GitHub Actions, `--fake` | mỗi PR | định dạng dữ liệu; quỹ đạo mẫu đạt 100%; không tốn GPU hay tiền |
| Model thật | máy owner, `--endpoint` tới vLLM trên Colab | W6, chạy bằng lệnh tay | số liệu Chương 4; không đưa vào CI vì cần GPU, secret và tốn compute |

Phần chấm tay gồm hai việc: đọc lại mọi ca thất bại để phân loại lỗi cho mục 4.9, và chấm một mẫu phân tầng khoảng 30 ca, gồm 2 đến 3 ca mỗi bộ, theo thang 1–5 về độ đúng, độ rõ và giọng điệu CSKH. Việc chấm tay không thay cho kiểm thử trên trình duyệt của W5 và W6; đó là việc riêng.

## 5. Ma trận thí nghiệm ở W6

| Cấu hình | Agent | Thinking | Ngữ cảnh | Kho tri thức | Dùng cho |
|---|---|---|---|---|---|
| A, chính | agent-first | bật | 16k | thật | RQ1–RQ5 |
| B | legacy supervisor | bật | 16k | thật | RQ1 |
| C | agent-first | tắt | 16k | thật | RQ2 |
| D | agent-first | bật | 8k | thật | RQ2 |

Mỗi cấu hình chạy 3 lần trên đủ 150 ca. Bộ S03 chạy thêm phép đo truy hồi riêng, Recall@k và MRR trên nhãn mức liên quan, với kho tri thức thật đã nạp `data/knowledge/`.

## 6. Việc phải làm, theo thứ tự

1. Viết dữ liệu 11 bộ, mỗi lần một bộ, kèm quỹ đạo mẫu; mở rộng `check_eval_dataset.py` để kiểm các trường mới.
2. Bổ sung runner: `--repeat k` và pass^k; `--agent-mode legacy`; tùy chọn thinking và cửa sổ ngữ cảnh; báo cáo theo bộ và theo `split`; chế độ kho tri thức thật cho S03, cần PostgreSQL với pgvector.
3. Script thống kê: khoảng tin cậy bootstrap cho tỉ lệ thành công, McNemar cho các cặp A–B, A–C, A–D.
4. Test CI phát lại quỹ đạo mẫu của cả 150 ca.
5. W6: chạy ma trận trên Colab, chấm tay mẫu 30 ca, phân loại lỗi.

Bước 1 và 3 không cần Colab và làm được ngay. Bước 2 và 4 là việc code nên theo quy trình handoff cho Argon, kèm PR và CI. Bước 5 chờ Colab.

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
2. **Ánh xạ dữ liệu.** Đổi người dùng, đơn, sản phẩm gốc sang khách `C-001` và đơn, sản phẩm trong seed của RetailOps. Thiếu trạng thái thì thêm fixture có tên riêng, không sửa seed.
3. **Việt hóa, không dịch từng chữ.** Giữ mục tiêu, ràng buộc và thứ tự khách tiết lộ thông tin trong `known_info`, `unknown_info`, `task_instructions` của bản gốc. Viết lại như khách Việt thật nhắn tin, theo phân bố `style` ở mục 7.3.
4. **Cố định lời khách.** τ²-bench dùng LLM đóng vai khách. Ở đây lời khách được viết sẵn thành 1–4 lượt, để mọi cấu hình nhận đúng cùng đầu vào. Điểm này ghi vào mục mối đe dọa tính hợp lệ.
5. **Viết lại kỳ vọng theo nguyên tắc của RetailOps.** Hành động ghi của τ²-bench đổi thành form được mở bằng `prepare_order_action`, với đúng loại, đúng đơn, đúng biến thể; `final_state` giữ DB không đổi. `communicate_info` đổi thành `answer_all` hoặc `answer_any`. Luôn thêm `answer_not` cho các câu khẳng định đã hủy, đã đổi, đã hoàn tiền.
6. **Viết quỹ đạo mẫu** `fake_model` và chạy `--fake`; ca chỉ được nhận khi đạt.
7. **Rà soát theo checklist:** kỳ vọng đúng với seed; chấp nhận mọi quỹ đạo hợp lệ chứ không chỉ một; lời khách không lộ đáp án; `answer_any` đủ cách nói đồng nghĩa; không có mã đơn, tên hay nội dung chép nguyên văn từ bộ chỉ cho nghiên cứu.
8. **Chia `split`.** Rút ngẫu nhiên theo từng bộ với seed cố định, 30% là `held_out`.
9. **Đóng băng.** Owner duyệt từng bộ. Trước khi chạy W6, ghi SHA-256 của dữ liệu, runner đã có `dataset_digest`, vào báo cáo. Sau đó không sửa ca, chỉ thêm phiên bản mới.

### 7.3 Quy cách ngôn ngữ lấy từ các bộ tiếng Việt

Không chép câu. Chỉ dùng các hiện tượng mà CSConDa và ViOCD mô tả làm quy cách viết: teencode, viết tắt, lỗi gõ, chêm tiếng Anh, không dấu, câu cụt, kể lể dài. Phân bố `style` mục tiêu trên 150 ca: `chuan` 40%, `khong_dau` 15%, `teencode` 20%, `sai_chinh_ta` 15%, `dai` 10%. Nếu muốn có căn cứ định lượng, có thể đếm tỉ lệ các hiện tượng trên tập test của CSConDa sau khi đăng ký quyền truy cập. Đây là dùng cho nghiên cứu, kết quả đếm không lưu câu gốc.
