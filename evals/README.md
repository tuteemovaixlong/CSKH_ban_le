# RetailOps evaluation foundation

The evaluation suite is organized around observable outcomes rather than one fixed reasoning trajectory.

## Scoreboards

### Business correctness

- final order state;
- tenant/customer ownership;
- role permission enforcement;
- stale-version rejection;
- explicit confirmation requirement;
- idempotent mutation and audit integrity.

### Agent behavior

- task success;
- tool selection;
- argument validity;
- correct clarification / abstention;
- unnecessary model/tool calls;
- general-vs-retail request mode.

### Retrieval and grounding

- relevant source retrieval;
- no-evidence behavior;
- citation provenance;
- semantic support/entailment as a separate grade;
- unauthorized retrieval rate.

### Systems and cost

- end-to-end latency;
- model/tool/database/checkpoint timings when available;
- model calls and logical tool calls per task;
- prompt/generated tokens;
- reported cost or explicit unknown usage;
- retries, timeouts and failures.

## Dataset schema

Each JSONL scenario contains:

- `id`: unique stable scenario identifier;
- `split`: `dev` or `held_out`;
- `category`: scenario family;
- `user_text`: synthetic user message;
- `expected_mode`: `general` or `retail`;
- `expected_tools`: allowed/expected tool names for the task family;
- `forbidden_tools`: tools that must not be called;
- `expected_outcome`: high-level observable result;
- `safety`: named invariants that must hold.

The dataset intentionally avoids real customer data, credentials and destructive production operations.

## Evaluation policy

A task can have more than one valid tool trajectory. The verifier should grade the final evidence and backend state first, then efficiency. Safety failures always fail the scenario even when the natural-language answer looks plausible.

Real-model evaluation is opt-in and budgeted. CI should validate dataset/contracts and deterministic scripted-model behavior without paying for external inference by default.

## W3.2 agent scenarios (`agent_scenarios_w3_2.jsonl`)

Tau-bench style conversations of one synthetic customer (`C-001` of a fresh demo store in a temporary directory) with
the situations of the W3.2 handoff: order lookup, cancelling a pending order, returning or exchanging a delivered one,
changing colour or size, orders that are not eligible, follow-up questions, off-topic text, policy answers that need a
citation and a customer who wants a person. Each record holds:

- `turns[].user`: what the customer says;
- `turns[].expect`: what the code can check: tools that must (`tools_called`, `tools_any`) or must not (`tools_not_called`,
  `max_tool_calls`) be used, the form the chat opened (`action`, `order_action`, with the target variant by label), a safety
  rail, request mode, sources, phrases the answer needs (`answer_all`, `answer_any`) and **what it must not claim**
  (`answer_not`);
- `final_state`: statuses of orders and counts of rows (requests, proposals, outbox, hand-offs) after the conversation;
- `turns[].fake_model`: the replies of the scripted fake gateway that CI plays (`{"call": [...]}` steps, then one
  `{"say": ...}`; `{{last_tool.results.0.citation_id}}` quotes the last tool result). A real model ignores it;
- `knowledge`: the policy documents the knowledge search returns (an empty list means "no evidence").

```bash
python scripts/check_eval_dataset.py                    # format check (also checks baseline_v1.jsonl)
python scripts/run_agent_scenarios.py --fake            # fake gateway: no model, no network (CI: tests/test_r1_w3_2_agent_scenarios.py)
python scripts/run_agent_scenarios.py --endpoint https://<id>.ngrok-free.app/v1/chat/completions --out report.json
```

The last form is for the **owner** with the real model (the "Endpoint API OpenAI" printed by `notebooks/colab_vllm_l4.py`;
`--model` or `RETAILOPS_API_MODEL` for the served name, `RETAILOPS_API_KEY` if the endpoint needs a key). Without `--endpoint`
the script refuses to run. The report gives the success rate, the valid tool-call rate (a known tool with arguments that
pass the schema; business refusals count as valid) and the latency p50/p95 per customer turn. Nothing outside the
temporary store is read or written.


## W6.3 — bộ công cụ đánh giá bản 2

Chỉ dùng dữ liệu giả lập. CI phát lại quỹ đạo mẫu bằng `--fake`. Phần code W6.3
không chạy model thật; các lệnh endpoint dưới đây dành cho owner ở W6.4.
Không đặt hai biến thí nghiệm mới trên production.

```sh
python scripts/check_eval_dataset.py
python scripts/check_eval_dataset.py evals/suites --final
python scripts/build_eval_pack.py
python scripts/build_eval_pack.py --check
python scripts/run_agent_scenarios.py --fake --dataset khoa_luan/eval_pack/06_vi_du.jsonl
python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --repeat 3 --out fake.json
```

Ma trận A–D của W6 backlog mục 3: A chạy 250 ca; B/C/D chạy cùng tập con cố định
100 ca do owner chọn, không phải 100 ca đầu hay một tập con lấy ngẫu nhiên mỗi lần.
Đặt `SUBSET_IDS` thành 100 mã ca đã đóng băng; dùng cùng danh sách để lấy báo cáo
A trên tập con (`A100.json`) trước khi so sánh McNemar với B/C/D. Không sửa ca.

```sh
# Các khóa endpoint đọc từ biến/file có sẵn, không ghi vào lệnh hay báo cáo.
# Kho real yêu cầu RETAILOPS_TEST_DATABASE_URL và RETAILOPS_ALLOW_DESTRUCTIVE_TEST_DATABASE=1
# trỏ đúng PostgreSQL dùng một lần trên loopback như CI (xem scripts/postgres_test_guard.py).
python scripts/run_agent_scenarios.py --endpoint "$ENDPOINT" --dataset-dir evals/suites --agent-mode agent --thinking on --context-tokens 16384 --knowledge real --repeat 3 --out A.json
python scripts/run_agent_scenarios.py --endpoint "$ENDPOINT" --dataset-dir evals/suites --only $SUBSET_IDS --agent-mode agent --thinking on --context-tokens 16384 --knowledge real --repeat 3 --out A100.json
python scripts/run_agent_scenarios.py --endpoint "$ENDPOINT" --dataset-dir evals/suites --only $SUBSET_IDS --agent-mode legacy --thinking on --context-tokens 16384 --knowledge real --repeat 3 --out B.json
python scripts/run_agent_scenarios.py --endpoint "$ENDPOINT" --dataset-dir evals/suites --only $SUBSET_IDS --agent-mode agent --thinking off --context-tokens 16384 --knowledge real --repeat 3 --out C.json
# Owner khởi động lại vLLM với RETAILOPS_MAX_MODEL_LEN=8192 cho D.
python scripts/run_agent_scenarios.py --endpoint "$ENDPOINT" --dataset-dir evals/suites --only $SUBSET_IDS --agent-mode agent --thinking on --context-tokens 8192 --knowledge real --repeat 3 --out D.json
python scripts/eval_stats.py summary A.json A100.json B.json C.json D.json
python scripts/eval_stats.py compare A100.json B.json
python scripts/eval_stats.py compare A100.json C.json
python scripts/eval_stats.py compare A100.json D.json
python scripts/eval_retrieval.py --dataset evals/suites/S03.jsonl --out retrieval.json
```

Có thể lọc `--suite S03 S11` và `--split held_out`; `--repeat` nhận 1–5.
`--agent-mode legacy` cần `--endpoint`. `--thinking default` không gửi thêm trường;
`on/off` gửi `chat_template_kwargs.enable_thinking`. `--context-tokens` nhận
4096–131072, mặc định 16384. Các ngân sách ký tự co giãn theo N/16384 với mức sàn;
ở mặc định giữ nguyên 5200/12000/800/6000/1500. Giới hạn bảo vệ giao thức hiện có vẫn áp dụng.

Chế độ `real` nạp toàn bộ `data/knowledge/` đúng một lần mỗi lượt chạy vào schema
PostgreSQL riêng và xóa schema khi xong. Ca có `meta.knowledge_mode: "scripted"`
luôn dùng đoạn của ca. `overrides.product_descriptions` chỉ đổi SQLite tạm của ca.
`expect.attack_not` và `expect.attack_tools_not_called` đo `attack_success` riêng,
không làm đổi điểm `utility`. Báo cáo giữ từng lần chạy, metadata, lỗi, token,
tool, độ trễ, cấu hình, hash file và tổng hợp theo suite/split/style/origin.

`pass_at_1` là trung bình tỉ lệ đạt từng ca; `pass_power_k` là tỉ lệ ca đạt mọi lần.
Bootstrap 95% lấy mẫu trên ca 10.000 lần với seed 20261110, giữ các lần chạy của một
ca cùng nhau. McNemar ghép mã ca, dùng đa số nghiêm ngặt; hòa với K chẵn tính không đạt.
Báo cáo khác tập ca hoặc hash dữ liệu không so sánh được.
