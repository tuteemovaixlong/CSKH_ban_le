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
