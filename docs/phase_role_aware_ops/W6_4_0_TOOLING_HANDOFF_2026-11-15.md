# Phase R1 — W6.4.0 Handoff: danh sách món của đơn cho model (F42), tham số lấy mẫu cấu hình được, gộp shard, ghi nguồn gốc, script Colab đánh giá

> **Trạng thái:** phát hành ngày 2026-11-15. Có hiệu lực khi owner merge §31. Executor: Codex.
> **Quyết định áp dụng:** [§31](W0_OWNER_DECISION_DELTA_2026-10-29.md#31-w64-owner-decisions-2026-11-15), chủ yếu W6.4-D2, D3, D4, D10, D13; F42 trong [W6 backlog](W6_BACKLOG_2026-11-06.md).
> **Căn cứ:**
> - [W6.4 readiness review](W6_4_READINESS_REVIEW_2026-11-14.md), mục 2, 5 và 8;
> - script thử trên Colab mà owner đã chạy được: `D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/.claude/worktrees/cai-nay-la-sao-bddcef/scratch/colab_test_qwen35_9b_mtp.py`, SHA-256 `ef13e7e1b486e261935a3296d94f899df7ea1575ff1340fa8836cb198e9648b9`. Đây là tệp tham khảo, chỉ đọc, không commit.
>
> **Thứ tự:** tạo nhánh từ `origin/main` **sau khi** PR chứa handoff này merge. Phải merge W6.4.0 xong mới chạy lượt đo W6.4 đầu tiên.
> **Nguyên tắc:**
> - Không sửa ca trong `evals/suites/` (đã đóng băng, W6.3-D7). Không đổi cách chấm hay ngưỡng.
> - Không sửa prompt, mô tả tool hay `answer_check`. Lỗi trích dẫn, lỗi gọi `draft_reply` và văn phong để dành cho W6.5.
> - Không gọi LLM thật, không chạy Colab. Mọi thứ kiểm bằng test offline.
> - Gặp quyết định chưa có trong tài liệu thì **dừng và hỏi owner**.

## 1. Hiện trạng

1. **F42. Model không thấy danh sách món của đơn nhiều sản phẩm.**
   - Kết quả `get_order` mà model nhận có 29 khóa, chỉ có `product_id`, `variant` của món chính và `name` dạng "Áo sơ mi lụa công sở và 1 sản phẩm khác". Claude đã kiểm bằng gateway giả trên ca `s05_022`.
   - Bảng `order_items` có sẵn `product_id`, `variant_id`, `product_title`, `variant_name`, `quantity`, `unit_price`, `subtotal`.
   - `eval_pack/03` ghi đủ từng món. Ví dụ SIM-O-00091: P-601 ×1 · Trắng · Size M; P-602 ×2 · Đen · Size M; tổng 1.530.000 gồm 40.000 phí ship.
   - Dữ liệu demo có 36 đơn nhiều món; 63 ca đã đóng băng nhắc tới các đơn này. Lượt thử Qwen ngày 2026-11-15: ca `s05_022` gọi 6 lần để đoán món thứ hai rồi trả lời rỗng.
2. **Tham số lấy mẫu cố định.** Gateway kiểu OpenAI trong `retailops_providers.py` luôn gửi `temperature 0.2`, `max_tokens 2048`. W6.4-D10 cần chạy với tham số Qwen khuyến nghị (`temperature 1.0, top_p 0.95, top_k 20, presence_penalty 1.5`), còn `max_tokens` chốt ở bước chạy thử.
3. **Runner chạy tuần tự và ghi báo cáo một lần ở cuối.** `eval_stats compare` nhận đúng một báo cáo mỗi bên. Báo cáo chưa có git SHA, tên model hay phiên bản vLLM, và không lưu phần suy nghĩ, lời gọi tool của model. Lượt thử phải dùng một proxy đặt ngoài repo để xem vết.
4. **Chưa có script Colab cho lượt đo.** `notebooks/colab_vllm_l4.py` viết cho Gemma 4 12B trên L4, ghim `vllm==0.32.0` và cài lại, dùng ngrok. Script thử nêu ở phần Căn cứ đã chạy được Qwen3.5-9B với vLLM có sẵn của Colab, MTP, fp8, ở `127.0.0.1`.
   - Bài học từ lượt thử: phải khởi động vLLM bằng `start_new_session=True`, vì bấm Stop một cell gửi `SIGINT` làm vLLM tắt theo.
   - `--knowledge real` cần `RETAILOPS_TEST_DATABASE_URL` trỏ tới PostgreSQL có pgvector, qua được `scripts/postgres_test_guard.py`.

## 2. Phạm vi và tiêu chí chấp nhận

Nhánh mới từ `origin/main`, không theo dõi `main`. Không migration, không thêm thư viện vào requirements của repo. Script Colab được cài gói trong máy Colab lúc chạy, giống `colab_vllm_l4.py`.

| # | Việc phải làm | Tiêu chí chấp nhận, test cô lập |
|---|---|---|
| 1 | **F42 (W6.4-D13).** Dữ liệu đơn trả cho model có thêm trường `items`: danh sách món lấy từ `order_items`, mỗi món gồm `product_id`, `name` (từ `product_title`), `variant` (từ `variant_name`), `quantity`, `unit_price`, `subtotal`. Áp dụng thống nhất cho mọi tool trả đơn cho model: `get_order`, `list_orders`, `get_context` (phần đơn), phần đơn trong kết quả `prepare_order_action`, và `get_case_order`, `list_case_orders` của Trợ lý ca. Giữ nguyên các trường cũ (`name`, `product_id`, `variant`). Không thêm dữ liệu cá nhân. Đơn không có dòng `order_items` thì `items` là danh sách rỗng, không suy đoán. | Test: SIM-O-00091 có 2 món: P-601 ×1, đơn giá 450.000; P-602 ×2, đơn giá 520.000, thành tiền 1.040.000. Một đơn một món có `items` đúng 1 phần tử. Đủ các tool kể trên. Kích thước kết quả `list_orders` với 10 đơn vẫn nằm trong giới hạn hiện có của hệ thống (ghi số ký tự trước và sau vào báo cáo). Nếu `python scripts/build_eval_pack.py --check` báo khác vì kết quả tool mẫu ở `eval_pack/03` mục 3.3 đổi, sinh lại bằng `python scripts/build_eval_pack.py`, không sửa tay, ghi vào báo cáo. Viết test trước, chạy trên code chưa sửa để thấy FAIL. |
| 2 | **Tham số lấy mẫu cấu hình được (W6.4-D10).** Gateway kiểu OpenAI đọc thêm biến môi trường tùy chọn `RETAILOPS_MODEL_TEMPERATURE`, `RETAILOPS_MODEL_TOP_P`, `RETAILOPS_MODEL_TOP_K`, `RETAILOPS_MODEL_PRESENCE_PENALTY`, `RETAILOPS_MODEL_MAX_TOKENS`, có kiểm khoảng giá trị hợp lệ. Không đặt biến thì giữ đúng hành vi cũ (`0.2`, `2048`, không gửi `top_p`, `top_k`, `presence_penalty`). Runner có cờ tương ứng `--temperature`, `--top-p`, `--top-k`, `--presence-penalty`, `--max-tokens`, đặt các biến này cho lượt chạy và ghi vào báo cáo. Không đặt các biến này trên production; nếu `scripts/check_deployment_contract.py` có danh sách biến thí nghiệm cấm đặt trên production thì thêm vào. | Test: không đặt biến thì payload giống hệt hiện tại; đặt đủ biến thì payload có đúng các giá trị; giá trị ngoài khoảng thì báo lỗi rõ. Runner ghi các giá trị vào báo cáo. Đường Anthropic hay Google không đổi. Viết test trước, thấy FAIL. |
| 3 | **Ghi nguồn gốc và vết (W6.4-D3).** Báo cáo runner có khối `provenance`: git SHA (lấy từ `git rev-parse HEAD`, hoặc biến `RETAILOPS_GIT_SHA` khi không có `.git`), id model mà server phục vụ (từ `/v1/models`), phiên bản vLLM (từ `/version` nếu có, không có thì `null`), các tham số lấy mẫu, `context_tokens`, `thinking`, `agent_mode`, `knowledge`. Cờ mới `--trace-out PATH`: ghi JSONL, mỗi dòng là một lần gọi model, gồm mã ca, lượt, lần chạy, request (messages, tools, tham số) và response (content, reasoning, tool_calls, finish_reason, usage, thời gian). **Không ghi header, khóa hay URL có chứa khóa.** | Test với gateway giả: báo cáo có `provenance` đủ khóa; `--trace-out` ghi đúng số lần gọi; trong tệp vết và báo cáo không có chuỗi khóa API thử hay header `Authorization`. Viết test trước, thấy FAIL. |
| 4 | **Gộp shard (W6.4-D3).** Lệnh mới `python scripts/eval_stats.py merge OUT REPORT [REPORT ...]` gộp nhiều báo cáo shard thành một báo cáo mà `summary` và `compare` dùng được. Từ chối, với thông báo rõ, khi: `provenance` khác nhau (trừ thời điểm chạy); SHA dataset khác; trùng cặp (mã ca, lần chạy); cấu hình runner khác. Tóm tắt của báo cáo gộp tính lại từ bản ghi, không cộng dồn tóm tắt của shard. | Test: gộp 2 shard tạo bằng gateway giả thì ra đúng bằng chạy một lần trên cùng các ca, cả `summary` lẫn các chỉ số pass^k; mỗi trường hợp phải từ chối đều có test riêng. `compare` chạy được trên báo cáo gộp. Viết test trước, thấy FAIL. |
| 5 | **Script Colab đánh giá `notebooks/colab_eval_w64.py` (W6.4-D2, D4).** Dựa trên script thử ở phần Căn cứ, chia cell như `colab_vllm_l4.py`. Gồm: nạp và lưu Google Drive (model, cache vLLM, venv, báo cáo; không lưu khóa); kiểm GPU; cài PostgreSQL và pgvector trong máy Colab, tạo DB dùng một lần qua được `postgres_test_guard`; khởi động vLLM cho `Qwen/Qwen3.5-9B` với các cờ của W6.4-D1 (`--max-model-len` chọn 16384 hoặc 8192 cho cấu hình D; fp8 khi GPU dưới 40 GB; MTP; `start_new_session=True`; thử lại không MTP nếu MTP lỗi); clone repo đúng SHA nhập vào; venv cho runner với `requirements-web.txt` và `requirements-postgres.txt` kèm `--require-hashes`; chạy shard song song (chia danh sách ca thành shard, chạy tối đa P tiến trình, mỗi shard một báo cáo và một tệp vết lưu thẳng lên Drive, **bỏ qua shard đã có báo cáo** để chạy tiếp sau khi phiên ngắt); gộp bằng `eval_stats merge`; dừng mọi tiến trình. Các bước tạo lệnh viết thành hàm thuần để test được. | Test offline: dựng lệnh vLLM đúng cờ cho 16k, 8k, có và không MTP, GPU dưới và trên 40 GB; chia shard tất định, không trùng không sót ca; logic bỏ qua shard đã xong; lệnh runner có đúng cờ lấy mẫu, `--trace-out`, `--knowledge real`; script không in hay ghi khóa. Kiểm cú pháp trên Python 3.13 như job `colab-python313`. Không chạy vLLM hay Colab thật. |
| 6 | **Kiểm không hồi quy.** | Runner `--fake` cho hai tệp hồi quy, `06_vi_du.jsonl` và `evals/suites` (250 ca) đều 100%. `check_eval_dataset.py evals/suites --final` báo `cases=250`. SHA-256 12 tệp `evals/suites/*.jsonl` khớp bảng đóng băng. Notebook `colab_agent.ipynb` sinh lại nếu nguồn đổi. |

Thứ tự bắt buộc với hàng 1–5: viết test trước, chạy trên code chưa sửa để thấy FAIL, ghi lại dòng lỗi, rồi mới sửa.

## 3. Ngoài phạm vi

- Sửa ca trong `evals/suites/`, 44 kịch bản hồi quy, kho chính sách, luật hay dữ liệu demo.
- Sửa `SYSTEM`, prompt của Trợ lý ca, mô tả tool, `answer_check`, rào an toàn (thuộc W6.5).
- Đổi model hay cấu hình của production; sửa `notebooks/colab_vllm_l4.py` và `notebooks/colab_agent.ipynb` ngoài việc sinh lại notebook.
- Huấn luyện, chưng cất, LoRA (W6.7).
- Nếu thấy chỗ khác cũng làm model thiếu dữ liệu mà `eval_pack/03` mô tả, **ghi vào báo cáo**, không sửa.

## 4. Kiểm tra và báo cáo

Sửa `retailops/`, `retailops_tools.py`, `retailops_providers.py`, `agent_protocol.py` hay `tests/` thì sinh lại notebook bằng `python scripts/build_agent_notebook.py`.

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

Báo cáo ghi vào `docs/phase_role_aware_ops/W6_4_0_EXECUTION_REPORT_2026-11-15.md` **bằng xuống dòng LF**, gồm:
- tệp đổi theo từng hàng;
- bằng chứng FAIL trước khi sửa;
- ví dụ `items` của SIM-O-00091 trước và sau;
- kích thước `list_orders` trước và sau;
- kết quả từng lệnh;
- DONE hoặc BLOCKED từng hàng;
- URL PR và kết quả CI.

Thêm một dòng mới vào cột của bạn trong [W1 execution log](W1_EXECUTION_LOG_2026-10-31.md), ghi rõ là W6.4.0; không sửa dòng cũ.

**Cấm:**
- merge; push vào `main`; force-push, rebase, reset, stash;
- đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e;
- truy cập EC2, SSM, DB production, Colab hoặc LLM thật, dữ liệu khách hàng;
- thêm thư viện vào requirements của repo;
- sửa ca trong `evals/suites/`.

## 5. Sau khi báo cáo

Claude chỉ chạy **một** lượt kiểm chứng theo tiêu chí ở mục 2; owner quyết định merge.

Hàng 1 đổi dữ liệu mà model trên production nhận, nên deploy bình thường, không migration. Smoke: hỏi "đơn `<mã đơn nhiều món>` gồm những gì, mỗi món giá bao nhiêu" thì trả lời đúng từng món.

Sau khi merge, owner chạy `notebooks/colab_eval_w64.py` trên L4 theo thứ tự của W6.4-D4, bắt đầu bằng 4 ca ví dụ và 12 ca thử. Claude kiểm từng bước rồi mới sang bước sau.
