# W6.4.0 execution report — 2026-11-15

## Điều kiện bắt đầu và phạm vi

- Đã `git fetch origin`; `origin/main` là `9086714bdc01d8f15a5a30ed353eaa2835934204`, merge PR #109, chứa commit tài liệu `bcd3794`: handoff W6.4.0, §31, F42 và readiness review. Đã đọc toàn bộ handoff, §31 và readiness review, gồm mục 2, 5, 8.
- Checkout ban đầu thực tế ở `phase-r1-w6-3-5`, sạch. `main` đang được checkout ở `.claude/worktrees/cai-nay-la-sao-bddcef`, cũng sạch. Chạy `git pull --ff-only` tại checkout giữ main: `Already up to date.` Sau đó `git switch --no-track -c phase-r1-w6-4-0 origin/main` tại repo chính. Không đặt upstream là main.
- Đọc, không chạy hoặc commit, tệp tham khảo `D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/.claude/worktrees/cai-nay-la-sao-bddcef/scratch/colab_test_qwen35_9b_mtp.py`. Kiểm SHA-256 **trước khi đọc nội dung/dùng làm tham khảo**: `ef13e7e1b486e261935a3296d94f899df7ea1575ff1340fa8836cb198e9648b9`, khớp handoff.
- Làm hàng 1–5 theo thứ tự, từng hàng viết test rồi chạy trên phần code tương ứng chưa sửa. Không sửa prompt, mô tả tool, `answer_check`, ca hồi quy, `evals/suites`, dữ liệu demo, requirements hoặc cách chấm/ngưỡng. Không migration. Không production, model thật, Colab thật, deploy hoặc live-e2e. `check_live_e2e_contract.py` là kiểm tra tĩnh offline.

## Kết quả theo hàng

| Hàng | Trạng thái | Tệp và kết quả |
|---|---|---|
| 1 — F42 | DONE | `retailops/business/store.py`: đọc đúng sáu trường từ `order_items` trong transaction; sắp xếp theo dữ liệu món để tránh UUID sinh ngẫu nhiên làm đảo thứ tự. `retailops_tools.py`, `retailops/workflow/case_assist.py`: thêm `items` cho đủ sáu tool. Giữ trường cũ, whitelist dữ liệu món, thiếu dòng thì `[]`. `tests/test_w64_order_items.py`: 3 test đạt, gồm đủ sáu tool, một món/không món và giới hạn compact. |
| 2 — lấy mẫu | DONE | `retailops_providers.py`: năm biến tùy chọn, mặc định vẫn 0.2/2048, không gửi ba tham số còn lại khi không đặt. Temperature hữu hạn [0,2], top_p (0,1], presence_penalty [-2,2], top_k/max_tokens là số nguyên dương. `scripts/run_agent_scenarios.py`: năm cờ, đặt biến riêng trong lượt chạy, khôi phục môi trường và ghi giá trị hiệu lực. Anthropic/Google giữ đường cũ. Không có danh sách biến thí nghiệm cấm production trong `check_deployment_contract.py`, nên không thêm danh sách mới. `tests/test_w64_sampling.py`: 5 test đạt. |
| 3 — provenance/vết | DONE | `scripts/eval_telemetry.py`, `scripts/run_agent_scenarios.py`: git HEAD hoặc `RETAILOPS_GIT_SHA`, model từ `/v1/models`, vLLM từ `/version` (không có: null), lấy mẫu, context/thinking/agent_mode/knowledge. `--trace-out`: JSONL từng request thực tế và response trước kiểm protocol, kể cả length/timeout; mã ca, lượt, lần chạy, nội dung/suy nghĩ/tool/finish/usage/thời gian. Không lưu headers; lọc khóa API/tunnel đã dùng, tên header xác thực và URL mang query/credentials trong cả trace/báo cáo. `tests/test_w64_trace.py`: 4 test đạt. `tests/gemma_fakes.py` hỗ trợ hai GET metadata; test adapter W3.2/W4 chấp nhận đúng ba URL và vẫn kiểm header cho **mọi** request, gồm cả metadata. |
| 4 — merge | DONE | `scripts/eval_stats.py merge OUT REPORT...`; xác minh provenance (bỏ thời điểm chạy), toàn bộ digest dataset, cấu hình/mode/model/report và cặp ca/lần chạy duy nhất. Tính lại qua `report_from_records` dùng chung với runner; không cộng summary shard. `summary`, `compare`, pass^k đều dùng được. `tests/test_w64_merge.py`: 6 test đạt, có test riêng từng lý do từ chối, hai shard fake repeat=3 khớp chạy toàn bộ. |
| 5 — Colab | DONE (offline) | `notebooks/colab_eval_w64.py`: cell cấu hình một bước D4 mỗi lần, SHA đầy đủ, Drive model/cache/venv/báo cáo/vết, GPU/vLLM có sẵn, fp8 dưới 40 GB, 16k/8k, MTP và fallback, phiên tiến trình riêng, PostgreSQL+pgvector dùng một lần qua guard. Venv Python 3.12 riêng vì hash PostgreSQL chỉ phủ 3.11/3.12; cài ba requirements **sẵn có** web/postgres/graph với `--require-hashes`. Shard tất định, tối đa P tiến trình, bỏ báo cáo đã hoàn tất kể cả ca được chấm fail; báo cáo ghi atomic, phần chưa xong chạy lại. Manifest ngăn trộn cấu hình khi resume. Dừng nhóm tiến trình khi ngắt và có cell STOP. Khóa chỉ trong bộ nhớ/env con, không trong command/log/Drive. `tests/test_w64_colab.py`: 8 test đạt; `.github/workflows/ci.yml` thêm kiểm cú pháp script vào job `colab-python313`; Python 3.13.15 local compile đạt. Không khởi động Colab/vLLM/PostgreSQL thật trong lượt này. |
| 6 — không hồi quy | DONE | Full snapshot cuối 1.128 pass, 0 fail/error, 86 skip / 1.214 method. Fake W3.2 32/32, W4 12/12, ví dụ 4/4, suites 250/250. Dataset final cases=250, 12/12 hash khớp. Notebook đã sinh lại. Chi tiết đầy đủ bên dưới. |

## Bằng chứng test trước sửa

Lệnh từng hàng: `python -B -X utf8 -m unittest discover -s tests -p <tệp> -v`.

| Hàng | Tệp test | Kết quả trên code chưa sửa và dòng lỗi |
|---|---|---|
| 1 | `test_w64_order_items.py` | 3 method, 6 subtest FAIL (cả sáu tool), 1 ERROR, 1 method PASS: `AssertionError: None != [{'product_id': 'P-601', ...}]`; `KeyError: 'items'`. Lượt đầu có lỗi tên import fixture `CaseTools`; sửa thành `CaseAssistBoundTools` rồi chạy lại **trước** khi sửa code. |
| 2 | `test_w64_sampling.py` | 5 method, 15 subtest/expectation FAIL và 2 ERROR: `ValueError not raised`; payload vẫn temperature 0.2, max_tokens 2048, top_p/top_k/presence_penalty None; `error: unrecognized arguments: --temperature 1.0 --top-p 0.95 --top-k 20 --presence-penalty 1.5 --max-tokens 4096`. Một ERROR là tên model Anthropic ngoài allowlist của fixture, sau đó đổi fixture sang model đã được duyệt; không sửa allowlist. |
| 3 | `test_w64_trace.py` | 3 ERROR: `ModuleNotFoundError: No module named 'scripts.eval_telemetry'`; `error: unrecognized arguments: --trace-out ...`. Sau sửa bổ sung kiểm length/timeout, tổng cuối 4 method. |
| 4 | `test_w64_merge.py` | 6 method, 13 ERROR tính cả subtest: `AttributeError: module 'scripts.eval_stats' has no attribute 'merge_reports'`; `invalid choice: 'merge' (choose from 'summary', 'compare', 'subset')`. |
| 5 | `test_w64_colab.py` | `ImportError: cannot import name 'colab_eval_w64' from 'notebooks'`; tệp triển khai chưa tồn tại. Sau sửa bổ sung test giới hạn P và ngắt tiến trình, tổng cuối 8 method. |

Test mới cuối: **26 pass, 0 fail, 0 error, 0 skip**, 8.288s. Không dùng lỗi môi trường/import fixture ban đầu để thay thế bằng chứng lỗi chức năng của hàng 1–2.

## SIM-O-00091 và kích thước kết quả

Trước: `name="Áo sơ mi lụa công sở và 1 sản phẩm khác"`, `product_id="P-601"`, `variant="Trắng · Size M"`, `amount=1530000`, không có `items`.

Sau: giữ các trường trên và thêm:

```json
[
  {"product_id":"P-601","name":"Áo sơ mi lụa công sở","variant":"Trắng · Size M","quantity":1,"unit_price":450000,"subtotal":450000},
  {"product_id":"P-602","name":"Quần tây đen hàn quốc","variant":"Đen · Size M","quantity":2,"unit_price":520000,"subtotal":1040000}
]
```

Đo fixture SQLite dùng một lần, gán các đơn demo cho cùng khách chỉ trong fixture để `list_orders` trả đủ 10 đơn. Dùng `compaction.dump` (UTF-8 JSON, ensure_ascii=False, separators gọn) và `compact_tool_result`:

| Lượt đo | JSON thô (ký tự) | Model nhận sau compact (ký tự) | Giới hạn một tool |
|---|---:|---:|---:|
| Trước sửa hàng 1 | 19.425 | 3.990 | 5.200 |
| Sau sửa hàng 1 | 21.969 | 4.597 | 5.200 |

Hai lần tạo fixture riêng có UUID thứ tự đơn ngẫu nhiên, nên số này là hai phép đo quan sát, không phải delta trên cùng mười đơn. Kết quả compact nằm trong ngân sách hiện có. **Giới hạn đã thấy, không sửa trong W6.4.0:** list nhiều đơn đã bị compact/cắt phần đuôi trước thay đổi này; raw JSON mười đơn vượt 5.200 ngay từ trước. Không tăng ngân sách F13 hoặc đổi rào/cách compact; tool `get_order` giúp truy vấn hẹp từng đơn.

## Các lệnh mục 4

Đếm unittest theo method (pass = tổng trừ fail/error/skip); runner/dataset theo ca; build/contract/JS/diff theo lượt lệnh exit 0. Không tự suy số assertion của script không công bố số lượng. Môi trường: Windows, Python 3.10.7; interpreter có PDF sẵn ở `%TEMP%/venv_pdf/Scripts/python.exe`; Node thực v24.22.1 từ executable trong gói CodexPrimaryRuntime. Không cài thư viện. Python 3.13.15 chỉ dùng kiểm cú pháp.

| Lệnh | Pass | Fail | Error | Skip | Bằng chứng |
|---|---:|---:|---:|---:|---|
| `python -m unittest discover -s tests -q`, checkout có worktree lồng | 1123 | 2 | 0 | 86 | 1.211 method, 474.560s; hai lỗi giải thích bên dưới |
| Cùng lệnh trên snapshot nguồn sạch cuối | 1128 | 0 | 0 | 86 | 1.214 method, 413.338s, `OK (skipped=86)` |
| Nguyên bài package-isolation trên snapshot sạch | 1 | 0 | 0 | 0 | 0.955s, không sửa bài test |
| Suite adapter W3.2/W4 sau cập nhật metadata | 43 | 0 | 0 | 0 | 34 + 9 method, 24.452s + 9.228s |
| Test mới `test_w64_*.py` | 26 | 0 | 0 | 0 | 8.288s |
| JS theo `.github/workflows/ci.yml` | 11 | 0 | 0 | 0 | 10 tệp và lượt public_session persistent; tệp W6.1b-2 có thêm 4/4 node:test đạt |
| `node --check web/*.js` (từng tệp) | 3 | 0 | 0 | 0 | app.js, chat-focus.js, embed.js |
| `python scripts/build_agent_notebook.py --check` | 1 | 0 | 0 | 0 | `AGENT_NOTEBOOK_SOURCE_SYNC_OK` sau sinh lại bằng script |
| `python scripts/build_eval_pack.py --check` | 1 | 0 | 0 | 0 | `EVAL_PACK_OK`; không cần sinh lại eval_pack/03 |
| `python scripts/check_docs_contract.py` | 1 | 0 | 0 | 0 | 4 nhóm PASS |
| `python scripts/check_deployment_contract.py` | 1 | 0 | 0 | 0 | `DEPLOYMENT_CONTRACT_OK` |
| `python scripts/check_live_e2e_contract.py` | 1 | 0 | 0 | 0 | `LIVE_E2E_CONTRACT_OK`, chỉ kiểm tĩnh |
| `python scripts/check_eval_dataset.py` | 74 | 0 | 0 | 0 | baseline 30 + W3.2 32 + W4 12 |
| `python scripts/check_eval_dataset.py evals/suites --final` | 250 | 0 | 0 | 0 | `EVAL_DATASET_OK suites cases=250` |
| Runner `--fake --dataset evals/agent_scenarios_w3_2.jsonl` | 32 | 0 | 0 | 0 | 100%, 35 lượt, 33/33 tool call hợp lệ |
| Runner `--fake --dataset evals/agent_scenarios_w4.jsonl` | 12 | 0 | 0 | 0 | 100%, 14 lượt, 17/17 tool call hợp lệ |
| Runner `--fake --dataset khoa_luan/eval_pack/06_vi_du.jsonl` | 4 | 0 | 0 | 0 | 100%, 6/6 tool call hợp lệ |
| Runner `--fake --dataset-dir evals/suites --min-success-rate 1.0` | 250 | 0 | 0 | 0 | 100%, 336 lượt, 469/469 tool call hợp lệ |
| SHA-256 so bảng `evals/suites/README.md` | 12 | 0 | 0 | 0 | Đủ S01–S12 khớp byte; không đổi ca |
| Python 3.13 compile `notebooks/colab_eval_w64.py` | 1 | 0 | 0 | 0 | `COLAB_W64_PY313_SYNTAX_OK` |
| `git diff --check` | 1 | 0 | 0 | 0 | Chưa thấy lỗi whitespace; kiểm lại sau cập nhật tài liệu |

Lượt mặc định ban đầu W4 dừng sau ca 1 với `ModuleNotFoundError: No module named 'pypdfium2'`; không sửa code/ca để né. Dừng full suite dùng interpreter thiếu PDF và chạy lại toàn bộ với interpreter PDF đã có. Launcher `node` trong PATH không phát stdout dù exit 0; đã chạy lại toàn bộ JS bằng executable Node thật, có đủ marker kết quả. Sandbox lúc đầu không khởi động vì app cập nhật; các lệnh cần ghi temp được chạy qua cơ chế phê duyệt, không đổi cấu hình sandbox.

Hai lỗi của full suite đầu có PDF:

- `test_item10_package_isolation_and_image_exclusion`: `AssertionError: 'marketplace_sim' == 'marketplace_sim'` khi quét vào `.claude/worktrees/cai-nay-la-sao-bddcef/tests/test_marketplace_sim_contract.py` của worktree cũ. Không sửa bài test hay xóa/move worktree. Kiểm bộ nguồn sạch bằng cách sao chép đúng 685 tệp tracked/tệp mới của nhánh vào thư mục tạm ngoài repo, không kèm `.git`, `.claude` hay artifact.
- `test_real_adapter_sends_both_item0_headers_measures_image_tokens_and_redacts_secrets`: assertion URL chỉ chấp nhận `/v1/chat/completions`, nên GET `/v1/models` mới làm fail. Đổi assertion sang đúng ba URL, giữ toàn bộ kiểm Bearer/tunnel token cho **mọi** request, số ảnh/token và không lọt khóa. Chạy lại hai suite adapter: **43/43**. Đây là thay đổi test để phản ánh GET của hàng 3, không đổi cách chấm ca eval. Snapshot cuối có thêm 3 test bổ sung mới, tổng **1.214 method, 1.128 pass, 86 skip, 0 fail/error**. Đối chiếu 18 tệp mã/test/notebook/CI đã đổi giữa snapshot và checkout cuối: giống byte hoàn toàn.

## Kiểm chứng và bổ sung của Claude (2026-11-15)

Claude kiểm chứng một lượt theo mục 2 handoff trên `184ac87`, trong worktree riêng, không chạm checkout của Codex.

| Kiểm | Kết quả |
|---|---|
| `test_w64_*` và adapter W3.2, W4 | 69/69 đạt |
| notebook, eval pack, docs, deployment, live-e2e contract; `check_eval_dataset.py evals/suites --final` | đều OK; `cases=250` |
| SHA-256 12 tệp `evals/suites` | 12/12 khớp bảng đóng băng |
| Fake 250 ca chạy liền, so với 2 shard (`shard_case_ids`) rồi `eval_stats merge` | `by_category`, `aggregates` khớp; `summary` khớp trừ `latency_ms` (hai lần chạy đo thời gian riêng, đúng kỳ vọng); `compare` chạy được; vết 717 dòng bằng `model_calls`; gộp một shard với chính nó bị từ chối |
| F42 trên Postgres | `PostgresBusinessStore` kế thừa đúng `read_order_details_in_tx`; cột `unit_price`, `subtotal` là BIGINT |
| Shard song song với `--knowledge real` | mỗi tiến trình tạo schema riêng tên ngẫu nhiên (`RealKnowledge`) và chỉ xóa schema đó, không tranh chấp DB |

**Bổ sung hàng 5 (commit của Claude trên nhánh này).** Bản `184ac87` đẩy output của vLLM, các shard và mọi lệnh cài đặt vào `DEVNULL`. Hệ quả: vLLM không khởi động hay một shard hỏng thì chỉ có câu báo chung, dò lỗi tốn đơn vị điện toán; và không ghi được tỉ lệ chấp nhận MTP mà W6.4-D7 (tốc độ) và D12(h) (mốc trước LoRA) cần. Đã sửa:

- `quiet()`: lỗi thì báo tên bước, mã thoát và 40 dòng output cuối **đã che** các bí mật truyền vào; không in lệnh đầy đủ hay SQL. Các lệnh `psql` và guard truyền mật khẩu DB để che.
- `start_server()`: log vLLM ghi ra `/content/w64_logs/vllm-<ctx>.log` trên đĩa runtime, không lên Drive; khóa vẫn chỉ nằm trong `VLLM_API_KEY`. Khởi động hỏng thì in đuôi log đã che, trước khi thử lại không MTP.
- `run_shards(..., log_dir, secrets)`: mỗi shard ghi log trên đĩa runtime; xong hay hỏng đều lưu bản đã che cạnh báo cáo (`shard-NNN.log` trên Drive); shard hỏng báo tên shard, mã thoát và đuôi log.
- `parse_metrics()`, `metrics_delta()`, `fetch_metrics()`: mỗi lần chạy một bước, CELL 5 lưu `vllm_metrics-<UTC>.json` vào thư mục bước, kể cả khi bước hỏng hay bị ngắt: bộ đếm `spec_decode` trước và sau, tỉ lệ chấp nhận token nháp, độ dài chấp nhận trung bình (cách vLLM tính: 1 + accepted/drafts), token sinh mỗi giây cộng gộp, cùng các dòng gốc của bộ đếm.
- CELL 7 xóa thêm biến `SECRETS`.

Test viết trước, chạy trên `184ac87` thấy 5 ERROR: `AttributeError: module 'notebooks.colab_eval_w64' has no attribute 'log_tail'`, `... 'parse_metrics'`, `TypeError: Popen.__init__() got an unexpected keyword argument 'secrets'`, `TypeError: run_shards() got an unexpected keyword argument 'log_dir'`, `TypeError: start_server() takes 2 positional arguments but 3 were given`. Sau sửa `test_w64_colab.py` 13/13 đạt. Sinh lại `colab_agent.ipynb` bằng `build_agent_notebook.py` (`AGENT_NOTEBOOK_SOURCE_SYNC_OK`); Python 3.13.15 compile script đạt; toàn bộ `python -m unittest discover -s tests -q`: 1.219 test, 1.133 đạt, 86 skip, 0 fail/error, 514,5 giây (`OK (skipped=86)`).

**Chỉ kiểm được khi chạy thật:** `apt-get install python3.12` phụ thuộc bản Ubuntu của máy Colab. Bước `examples` đầu tiên sẽ cho biết; nếu hỏng, thông báo giờ hiện dòng lỗi của apt.

## PR và CI

- Nhánh: `phase-r1-w6-4-0`, base `origin/main` `9086714`; không merge, không push main, không force-push/rebase/reset/stash.
- PR: [#110](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/110), Claude mở sau khi push `fc5bbcc`.
- CI trên `fc5bbcc` (run `43676369060`): 6/6 job xanh, gồm `offline` (10 phút 58 giây; nguồn `Ran 1219 tests`, `OK`; image `Ran 1207 tests`, `OK (skipped=27)`), `postgres`, `colab-python313` (có bước compile `colab_eval_w64.py`), `portable` Ubuntu và Windows, `clamav-smoke`. Commit chỉ cập nhật mục này sẽ chạy CI lại; kết quả cuối xem trên PR.
- Owner quyết định merge sau một lượt kiểm chứng của Claude theo handoff. `MAX_TOKENS=2048` trong script chỉ là giá trị khởi đầu của bước thử; owner chốt tại D4, dùng nhất quán cho A–D. Script không tự chạy bước tiếp theo.
