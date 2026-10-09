# AI Reproducibility

## Pins recorded by source

| Item | Rule | Citation |
|---|---|---|
| Source revision | Digest records local source SHA `8a666fcce464c96b1dd5fc6848a2d4168c6505d1`; merged-after-G2 SHA `[UNVERIFIED]` | [MODELS digest](../_digest/code/MODELS.digest) |
| Model identity | Local runtime requires model digest and records model name/digest | [`retailops_baseline.py#L147-L158`](../../retailops_baseline.py#L147) |
| Request determinism | Native request fixes seed `42`, temperature `0.2`, no streaming and no thinking | [`agent_protocol.py#L359-L391`](../../agent_protocol.py#L359) |
| Prompt version | Runtime prompt literals are source-controlled in `agent_protocol.py` and worker modules | [PROMPTS digest](../_digest/code/PROMPTS.digest) |
| Call budgets | 4 model calls and 8 tool calls maximum in native protocol | [`agent_protocol.py#L6-L10`](../../agent_protocol.py#L6) |
| Trace | Trace stores protocol/model/provider/digest, token counters, tool steps and latency | [`graph.py#L117-L153`](../../retailops/workflow/graph.py#L117) |

## Reproduction procedure

1. Pin the source revision shown above and record the actual model identity returned by the runtime.
2. Use the exact runtime prompt and tool scope in [PROMPT catalog](AI_PROMPT_CATALOG.md) and [AGENT catalog](AI_AGENT_CATALOG.md).
3. Keep request parameters and budgets from `agent_protocol.py`; capture trace fields and evidence citations.
4. Record evaluation dataset/hash and gates from [EVAL digest](../_digest/code/EVAL.digest) when available.

## Limits

- [UNVERIFIED] Provider API version, remote revision, model quantization, system hardware and network conditions.
- [UNVERIFIED] Reproduction of production results until merged/G2 runtime and model digest are recorded.
- A deterministic seed does not prove identical output across provider/model revisions; the source only fixes the request field.
