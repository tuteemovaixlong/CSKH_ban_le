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
