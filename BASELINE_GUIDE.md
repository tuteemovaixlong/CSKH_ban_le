> Historical local-only baseline guide. For the current EC2/Colab configuration, use README.md.

# RetailOps SLM: local baseline starter

Prepared 2026-09-06. Python 3.11+; Python standard library only.

## What this is

A minimal runnable baseline for a small local model to understand Vietnamese /
English requests and emit schema-checked intent + slots. Default model:
`qwen3.5:4b` via a separately installed local Ollama server.

It includes 24 authored synthetic **smoke cases**, versioned local event logs,
opt-in exact-match **extraction** caching, and an evaluator that bypasses the
application cache. No model weights, upstream datasets, or private user data are
bundled. No API key, payment account, or cloud service is needed by this code.
Electricity, hardware, and model downloads are not free resources.

**Not included:** order database, transaction execution, authorization server,
confirmation UI, LangGraph workflow, MCP adapter, complete tau-bench evaluation,
PII redaction, fine-tuning, semantic cache, or controllable prefix-cache serving.
This package does not claim those capabilities. It is the first model experiment,
not the final agent. `cancel_order` is an extracted proposal, NEVER an action.

## Start

Install Ollama from its official website and start the local server. Install
Python 3.11+ separately. Open a terminal inside this folder.

```bash
python -m unittest discover -s tests -v
ollama pull qwen3.5:4b
python retailops_baseline.py doctor
python retailops_baseline.py evaluate --cases data/smoke.jsonl
```

The `doctor` command checks that the local model is already installed and records
its digest, quantization metadata, and the Ollama runtime version. This tool never
pulls a model automatically. Do not replace/pull a model in the middle of a run.

For a lower-memory comparison, pull the 2B variant explicitly:

```bash
ollama pull qwen3.5:2b
python retailops_baseline.py --model qwen3.5:2b evaluate --cases data/smoke.jsonl
```

Default settings are an experiment, not a claim of optimal sampling:
`num_ctx=4096`, `num_predict=256`, `think=false`, `temperature=0`, `seed=42`,
`keep_alive=10m`. The extractor emits a tiny object, not a long answer. Compare
against temperature 0.7 on a development set before fixing a configuration:

```bash
python retailops_baseline.py --temperature 0.7 evaluate --repeats 3
```

Use `--seed 43` / `--seed 44` for separate variation trials. Context and output
limits can be set with `--context 4096 --max-output-tokens 256`.
A seed does not guarantee bit-identical outputs across machines/runtime versions.
If schema, thinking flags, or model loading fail, inspect/update the runtime,
repeat the smoke check, and record the working version. Do not silently change
models. Model file size is NOT total RAM/VRAM usage.

## Predict and inspect exact extraction cache

```bash
python retailops_baseline.py predict --text "Cancel order O-101 because I ordered by mistake."
python retailops_baseline.py predict --text "Look up order O-101" --cache --scope synthetic-demo
python retailops_baseline.py predict --text "Look up order O-101" --cache --scope synthetic-demo
```

The second identical opt-in request may reuse the parsed object. This does NOT
reuse an order status, grant permission, or execute a cancellation. Application
cache reads and writes are disabled for every evaluation attempt.

The key includes exact input, scope, full generation configuration, model digest,
runtime version, prompt, schema, policy version, and code hash. TTL is 600 seconds.
No semantic similarity cache is used. The scope in this CLI is for experiments;
a deployed service must obtain tenant/user permissions from authenticated server
context, never trust a client-provided scope as authorization.

Prefix/KV reuse, if performed internally by Ollama, is separate and is not
controlled or measured as a prefix hit rate by this starter. Keeping the model
loaded with `keep_alive` is not proof of prefix-cache reuse.

## Outputs and interpretation

`artifacts/runs.sqlite3` contains append-only application event records and a
separate extraction-cache table. `artifacts/report-<run-id>.json` contains:

- valid JSON/semantic-schema rate and exact intent/slot match;
- measured wall-clock p50/p95 latency, including model loading when it occurs;
- generated token counts when the local runtime returns them;
- per-category results and failed examples.

These are **extraction metrics**, not end-to-end business task success, a safety
certification, independent generalization accuracy, or a tau-bench score.
The 24 examples are smoke/development fixtures, not a held-out test set.

For serving experiments, separate cold-load, warm-model/prefix-miss, and
warm-prefix phases. This non-streaming starter does not measure TTFT. Do not
label its wall-clock latency as TTFT, and do not infer cached-token counts from
prompt token counts. Run repeats and report both quality and cost/latency.

## Data handling and later training

Use synthetic data only. This minimal version intentionally stores exact request
text and model output locally so experiments can be reproduced; it does not
implement PII redaction or encryption. Keep `artifacts/` out of git. Do not send
real customer data here until a reviewed privacy/retention layer is added.
The code ignores model thinking content and never stores API credentials.
Expected labels are recorded in grader events but never sent to the model.

Before training, implement a curated exporter: select allowed sources, redact,
verify, group-split by scenario/template, deduplicate, and exclude held-out data.
Do NOT train directly on the SQLite dump. Keep raw model proposals distinct from
human corrections. Successful parsing is not enough to label a trajectory correct.
A hash of private text is not anonymization.

## Next implementation milestone

Build the deterministic order service and test it without an LLM. Start with an
order read and a cancellation proposal. A separate confirmation step must bind
an authenticated actor, proposal ID, order version, reason, and expiry. Recheck
current state and permissions inside the write transaction; persist an
idempotency record atomically with the mutation. No write-answer cache.

Only then wrap the service in a small LangGraph workflow, add real end-to-end
state verifiers, and connect tau-bench Retail as a separately versioned adapter.
Do not call your modified demo a standard tau-bench environment.

## Verification performed for this package

Offline unit tests use a fake model response. They exercise validation, cache
isolation/invalidation, expiration, logging/evaluation paths and truncation
handling. Actual Qwen inference and hardware performance were NOT measured when
this package was prepared. Running the commands above is how you obtain your
own first measured baseline.
